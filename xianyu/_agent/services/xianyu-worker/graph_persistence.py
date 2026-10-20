"""SQLite persistence for LangGraph checkpoints, chat bindings and rollout data."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


GRAPH_DB_PATH = Path("data/agent_graph.db")
ACTIVE_STATUSES = {"interrupted", "paused", "awaiting_approval"}


class GraphPersistence:
    def __init__(self, path: str | Path = GRAPH_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._checkpoint_connection = sqlite3.connect(self.path, check_same_thread=False)
        self.checkpointer = SqliteSaver(self._checkpoint_connection)
        self.checkpointer.setup()
        self._init_tables()

    def close(self):
        self._checkpoint_connection.close()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _init_tables(self):
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS chat_threads (
                  chat_id TEXT PRIMARY KEY,
                  thread_id TEXT NOT NULL UNIQUE,
                  created_at REAL NOT NULL,
                  updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS graph_runs (
                  run_id TEXT PRIMARY KEY,
                  chat_id TEXT NOT NULL,
                  thread_id TEXT NOT NULL,
                  mode TEXT NOT NULL,
                  status TEXT NOT NULL,
                  item_id TEXT NOT NULL DEFAULT '*',
                  to_user_id TEXT NOT NULL DEFAULT '',
                  draft_reply TEXT NOT NULL DEFAULT '',
                  final_reply TEXT NOT NULL DEFAULT '',
                  result_json TEXT,
                  nodes_json TEXT NOT NULL DEFAULT '[]',
                  created_at REAL NOT NULL,
                  updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_graph_runs_chat_updated
                  ON graph_runs(chat_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS shadow_comparisons (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  chat_id TEXT NOT NULL,
                  thread_id TEXT NOT NULL,
                  legacy_json TEXT NOT NULL,
                  graph_json TEXT NOT NULL,
                  comparison_json TEXT NOT NULL,
                  created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_shadow_created
                  ON shadow_comparisons(created_at DESC);
                """
            )

    def thread_for_chat(self, chat_id: str) -> str:
        chat_id = str(chat_id or "console-test")
        now = time.time()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT thread_id FROM chat_threads WHERE chat_id=?", (chat_id,),
            ).fetchone()
            if row:
                connection.execute(
                    "UPDATE chat_threads SET updated_at=? WHERE chat_id=?", (now, chat_id),
                )
                return str(row["thread_id"])
            thread_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO chat_threads(chat_id,thread_id,created_at,updated_at) VALUES(?,?,?,?)",
                (chat_id, thread_id, now, now),
            )
            return thread_id

    def begin_run(
        self, chat_id: str, thread_id: str, mode: str, item_id: str, to_user_id: str = "",
    ) -> str:
        run_id, now = str(uuid.uuid4()), time.time()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO graph_runs(
                       run_id,chat_id,thread_id,mode,status,item_id,to_user_id,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (run_id, chat_id, thread_id, mode, "running", item_id, to_user_id, now, now),
            )
        return run_id

    def update_run(self, run_id: str, **values):
        allowed = {"status", "draft_reply", "final_reply", "result_json", "nodes_json", "to_user_id"}
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return
        for key in ("result_json", "nodes_json"):
            if key in updates and not isinstance(updates[key], str):
                updates[key] = json.dumps(updates[key], ensure_ascii=False)
        updates["updated_at"] = time.time()
        assignments = ",".join(f"{key}=?" for key in updates)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE graph_runs SET {assignments} WHERE run_id=?",
                [*updates.values(), run_id],
            )

    @staticmethod
    def _run(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        result = dict(row)
        result["result"] = json.loads(result.pop("result_json") or "null")
        result["nodes"] = json.loads(result.pop("nodes_json") or "[]")
        return result

    def latest_run(self, chat_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM graph_runs WHERE chat_id=? ORDER BY updated_at DESC LIMIT 1",
                (chat_id,),
            ).fetchone()
        return self._run(row)

    def active_run(self, chat_id: str) -> dict | None:
        run = self.latest_run(chat_id)
        return run if run and run["status"] in ACTIVE_STATUSES else None

    def list_active_runs(self, limit: int = 500) -> list[dict]:
        """返回每个会话最新且仍需人工处理的 Graph 运行记录。"""
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        with self._connect() as connection:
            rows = connection.execute(
                f"""SELECT runs.* FROM graph_runs AS runs
                    JOIN (
                      SELECT chat_id, MAX(updated_at) AS latest_updated_at
                      FROM graph_runs GROUP BY chat_id
                    ) AS latest
                      ON latest.chat_id=runs.chat_id
                     AND latest.latest_updated_at=runs.updated_at
                    WHERE runs.status IN ({placeholders})
                    ORDER BY runs.updated_at DESC LIMIT ?""",
                [*sorted(ACTIVE_STATUSES), max(1, min(int(limit), 1000))],
            ).fetchall()
        return [self._run(row) for row in rows if row is not None]

    def record_shadow(self, chat_id: str, thread_id: str, legacy: dict, graph: dict, comparison: dict):
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO shadow_comparisons(
                       chat_id,thread_id,legacy_json,graph_json,comparison_json,created_at
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    chat_id, thread_id, json.dumps(legacy, ensure_ascii=False),
                    json.dumps(graph, ensure_ascii=False), json.dumps(comparison, ensure_ascii=False),
                    time.time(),
                ),
            )

    def list_shadow(self, limit: int = 50) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM shadow_comparisons ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        return [{
            "id": row["id"],
            "chat_id": row["chat_id"],
            "thread_id": row["thread_id"],
            "legacy": json.loads(row["legacy_json"]),
            "graph": json.loads(row["graph_json"]),
            "comparison": json.loads(row["comparison_json"]),
            "created_at": row["created_at"],
        } for row in rows]

    def daily_intent_agreement(self, day: str) -> dict:
        """统计 Shadow 模式中两条真实流水线的意图判断一致率。"""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT comparison_json FROM shadow_comparisons WHERE date(created_at, 'unixepoch', 'localtime')=?",
                (day,),
            ).fetchall()
        matches = []
        for row in rows:
            try:
                matches.append(bool(json.loads(row["comparison_json"])["intent"]["match"]))
            except (KeyError, TypeError, json.JSONDecodeError):
                continue
        return {
            "intent_agreement_rate": round(100 * sum(matches) / len(matches), 1) if matches else None,
            "intent_agreement_sample_count": len(matches),
        }
