import sqlite3
import os
import json
import hashlib
import re
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from loguru import logger


class ChatContextManager:
    """
    聊天上下文管理器
    
    负责存储和检索用户与商品之间的对话历史，使用SQLite数据库进行持久化存储。
    支持按会话ID检索对话历史，以及议价次数统计。
    """

    RISK_WINDOW_DAYS = 30
    RISK_TURN_THRESHOLD = 5
    
    def __init__(self, max_history=100, db_path="data/chat_history.db"):
        """
        初始化聊天上下文管理器
        
        Args:
            max_history: 每个对话保留的最大消息数
            db_path: SQLite数据库文件路径
        """
        self.max_history = max_history
        self.db_path = db_path
        self._init_db()
        
    def _init_db(self):
        """初始化数据库表结构"""
        # 确保数据库目录存在
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
            
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 创建消息表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            chat_id TEXT
        )
        ''')
        
        # 检查是否需要添加chat_id字段（兼容旧数据库）
        cursor.execute("PRAGMA table_info(messages)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'chat_id' not in columns:
            cursor.execute('ALTER TABLE messages ADD COLUMN chat_id TEXT')
            logger.info("已为messages表添加chat_id字段")
        
        # 创建索引以加速查询
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_user_item ON messages (user_id, item_id)
        ''')
        
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_chat_id ON messages (chat_id)
        ''')
        
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_timestamp ON messages (timestamp)
        ''')
        
        # 创建基于会话ID的议价次数表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_bargain_counts (
            chat_id TEXT PRIMARY KEY,
            count INTEGER DEFAULT 0,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # 创建商品信息表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS items (
            item_id TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            price REAL,
            description TEXT,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # 记录人工接管的发生时间；用于控制台按天统计接管率。
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS manual_takeovers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_manual_takeovers_created_at
        ON manual_takeovers (created_at)
        ''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS dashboard_metric_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            takeover_tracking_started_at DATETIME NOT NULL
        )
        ''')
        cursor.execute(
            "INSERT OR IGNORE INTO dashboard_metric_settings (id, takeover_tracking_started_at) VALUES (1, ?)",
            (datetime.now().isoformat(),),
        )

        # “一件事”去重后的对话事项。事项在单会话内去重，风险轮数按买家跨会话汇总。
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversation_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            buyer_user_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            topic_key TEXT NOT NULL,
            topic_category TEXT NOT NULL,
            normalized_text TEXT NOT NULL,
            topic_summary TEXT NOT NULL,
            first_message TEXT NOT NULL,
            last_message TEXT NOT NULL,
            first_seen_at DATETIME NOT NULL,
            last_seen_at DATETIME NOT NULL,
            UNIQUE(chat_id, topic_key)
        )
        ''')
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_conversation_topics_buyer_seen
        ON conversation_topics (buyer_user_id, last_seen_at)
        ''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS risk_message_events (
            occurrence_key TEXT PRIMARY KEY,
            chat_id TEXT NOT NULL,
            buyer_user_id TEXT NOT NULL,
            topic_id INTEGER,
            created_at DATETIME NOT NULL
        )
        ''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS buyer_risk_profiles (
            buyer_user_id TEXT PRIMARY KEY,
            turn_count INTEGER NOT NULL DEFAULT 0,
            risk_level TEXT NOT NULL DEFAULT 'normal',
            risk_marked_at DATETIME,
            last_evaluated_at DATETIME NOT NULL
        )
        ''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS risk_schema_migrations (
            migration_key TEXT PRIMARY KEY,
            completed_at DATETIME NOT NULL
        )
        ''')
        needs_risk_backfill = cursor.execute(
            "SELECT 1 FROM risk_schema_migrations WHERE migration_key='recent_topics_v1'"
        ).fetchone() is None
        
        conn.commit()
        conn.close()
        logger.info(f"聊天历史数据库初始化完成: {self.db_path}")
        if needs_risk_backfill:
            self._backfill_recent_risk_topics()

    def _backfill_recent_risk_topics(self):
        """首次升级时将已有的最近 30 天买家消息纳入风险轮数。"""
        cutoff = (datetime.now() - timedelta(days=self.RISK_WINDOW_DAYS)).isoformat()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """SELECT id, chat_id, user_id, item_id, content, timestamp
                   FROM messages
                   WHERE role='user' AND chat_id IS NOT NULL AND timestamp>=?
                   ORDER BY id ASC""",
                (cutoff,),
            ).fetchall()
        finally:
            conn.close()

        try:
            for row in rows:
                observed_at = datetime.fromisoformat(str(row["timestamp"]))
                self.track_conversation_topic(
                    row["chat_id"], row["user_id"], row["item_id"], row["content"],
                    f"history:{row['id']}", observed_at=observed_at,
                )
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO risk_schema_migrations (migration_key, completed_at) VALUES (?, ?)",
                    ("recent_topics_v1", datetime.now().isoformat()),
                )
                conn.commit()
            finally:
                conn.close()
            if rows:
                logger.info(f"已回填最近30天的 {len(rows)} 条买家消息用于风险轮数统计")
        except Exception as exc:
            logger.exception(f"回填历史对话风险轮数失败，下次启动将重试: {exc}")

    def record_manual_takeover(self, chat_id):
        """记录一次会话进入人工接管状态的事件。"""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO manual_takeovers (chat_id, created_at) VALUES (?, ?)",
                (chat_id, datetime.now().isoformat()),
            )
            conn.commit()
        except Exception as e:
            logger.error(f"记录人工接管事件时出错: {e}")
            conn.rollback()
        finally:
            conn.close()

    def daily_activity_metrics(self, day=None):
        """返回指定自然日的真实消息与人工接管数据。"""
        day = day or datetime.now().date().isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            tracking_started_at = conn.execute(
                "SELECT takeover_tracking_started_at FROM dashboard_metric_settings WHERE id=1"
            ).fetchone()[0]
            reply_count = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE role='assistant' AND date(timestamp)=?",
                (day,),
            ).fetchone()[0]
            buyer_conversation_count = conn.execute(
                """SELECT COUNT(DISTINCT chat_id) FROM messages
                   WHERE role='user' AND chat_id IS NOT NULL AND date(timestamp)=? AND timestamp>=?""",
                (day, tracking_started_at),
            ).fetchone()[0]
            takeover_conversation_count = conn.execute(
                "SELECT COUNT(DISTINCT chat_id) FROM manual_takeovers WHERE date(created_at)=? AND created_at>=?",
                (day, tracking_started_at),
            ).fetchone()[0]
            return {
                "reply_count": int(reply_count),
                "buyer_conversation_count": int(buyer_conversation_count),
                "takeover_conversation_count": int(takeover_conversation_count),
                "takeover_tracking_started_at": tracking_started_at,
            }
        finally:
            conn.close()
        

            
    def save_item_info(self, item_id, item_data):
        """
        保存商品信息到数据库
        
        Args:
            item_id: 商品ID
            item_data: 商品信息字典
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # 从商品数据中提取有用信息
            price = float(item_data.get('soldPrice', 0))
            description = item_data.get('desc', '')
            
            # 将整个商品数据转换为JSON字符串
            data_json = json.dumps(item_data, ensure_ascii=False)
            
            cursor.execute(
                """
                INSERT INTO items (item_id, data, price, description, last_updated) 
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(item_id) 
                DO UPDATE SET data = ?, price = ?, description = ?, last_updated = ?
                """,
                (
                    item_id, data_json, price, description, datetime.now().isoformat(),
                    data_json, price, description, datetime.now().isoformat()
                )
            )
            
            conn.commit()
            logger.debug(f"商品信息已保存: {item_id}")
        except Exception as e:
            logger.error(f"保存商品信息时出错: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    def get_item_info(self, item_id):
        """
        从数据库获取商品信息
        
        Args:
            item_id: 商品ID
            
        Returns:
            dict: 商品信息字典，如果不存在返回None
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "SELECT data FROM items WHERE item_id = ?",
                (item_id,)
            )
            
            result = cursor.fetchone()
            if result:
                return json.loads(result[0])
            return None
        except Exception as e:
            logger.error(f"获取商品信息时出错: {e}")
            return None
        finally:
            conn.close()

    def add_message_by_chat(self, chat_id, user_id, item_id, role, content):
        """
        基于会话ID添加新消息到对话历史
        
        Args:
            chat_id: 会话ID
            user_id: 用户ID (用户消息存真实user_id，助手消息存卖家ID)
            item_id: 商品ID
            role: 消息角色 (user/assistant)
            content: 消息内容
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # 插入新消息，使用chat_id作为额外标识
            cursor.execute(
                "INSERT INTO messages (user_id, item_id, role, content, timestamp, chat_id) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, item_id, role, content, datetime.now().isoformat(), chat_id)
            )
            
            # 检查是否需要清理旧消息（基于chat_id）
            cursor.execute(
                """
                SELECT id FROM messages 
                WHERE chat_id = ? 
                ORDER BY timestamp DESC 
                LIMIT ?, 1
                """, 
                (chat_id, self.max_history)
            )
            
            oldest_to_keep = cursor.fetchone()
            if oldest_to_keep:
                cursor.execute(
                    "DELETE FROM messages WHERE chat_id = ? AND id < ?",
                    (chat_id, oldest_to_keep[0])
                )
            
            conn.commit()
        except Exception as e:
            logger.error(f"添加消息到数据库时出错: {e}")
            conn.rollback()
        finally:
            conn.close()

    def get_context_by_chat(self, chat_id):
        """
        基于会话ID获取对话历史
        
        Args:
            chat_id: 会话ID
            
        Returns:
            list: 包含对话历史的列表
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                """
                SELECT role, content FROM messages 
                WHERE chat_id = ? 
                ORDER BY timestamp ASC
                LIMIT ?
                """, 
                (chat_id, self.max_history)
            )
            
            messages = [{"role": role, "content": content} for role, content in cursor.fetchall()]
            
            # 获取议价次数并添加到上下文中
            bargain_count = self.get_bargain_count_by_chat(chat_id)
            if bargain_count > 0:
                messages.append({
                    "role": "system", 
                    "content": f"议价次数: {bargain_count}"
                })
            
        except Exception as e:
            logger.error(f"获取对话历史时出错: {e}")
            messages = []
        finally:
            conn.close()
        
        return messages

    def get_recent_messages_by_chat(self, chat_id, limit=20):
        """返回侚务控制台用的最近消息。limit=20 对应最近 10 轮问答的最大消息数。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """SELECT id, role, content, timestamp
                   FROM messages
                   WHERE chat_id=?
                   ORDER BY id DESC
                   LIMIT ?""",
                (chat_id, max(1, min(int(limit), 20))),
            ).fetchall()
            return [dict(row) for row in reversed(rows)]
        finally:
            conn.close()

    @staticmethod
    def _normalize_topic_text(message):
        """去掉礼貌词、标点和议价数字，让“最低多少”与“280能出吗”稳定归为同一事项。"""
        text = str(message or "").strip().lower()
        text = re.sub(r"\d+(?:\.\d+)?", "#", text)
        for filler in ("你好", "哈喽", "亲", "请问", "麻烦", "谢谢", "啊", "呀", "呢", "吧", "嘛", "吗", "么"):
            text = text.replace(filler, "")
        text = re.sub(r"[\s，。！！？?~～、：:;；,.!]+", "", text)
        return text[:120] or "empty"

    @classmethod
    def _topic_descriptor(cls, message):
        text = str(message or "").strip()
        normalized = cls._normalize_topic_text(text)
        topic_rules = (
            ("price", "price:negotiation", "询问或协商价格", ("便宜", "最低", "少点", "砍价", "刀", "优惠", "价格", "多少钱", "出价", "能出")),
            ("shipping_fee", "shipping:fee", "询问运费或是否包邮", ("包邮", "运费", "邮费", "到付")),
            ("shipping_time", "shipping:dispatch", "询问发货时间", ("发货", "今天发", "明天发", "什么时候发")),
            ("delivery_time", "shipping:delivery", "询问到货时间", ("到货", "几天到", "多久到", "时效")),
            ("availability", "availability:stock", "询问库存或是否在售", ("还在", "有货", "库存", "卖了吗", "被拍", "预留")),
            ("authenticity", "quality:authenticity", "询问真伪", ("正品", "真假", "保真", "验货")),
            ("condition", "quality:condition", "询问成色或瑕疵", ("成色", "瑕疵", "划痕", "磕碰", "破损", "问题")),
            ("battery", "quality:battery", "询问电池状况", ("电池", "健康度", "循环次数")),
            ("specification", "quality:specification", "询问型号或规格", ("型号", "规格", "尺寸", "颜色", "版本", "容量")),
            ("accessories", "quality:accessories", "询问配件", ("配件", "包装", "盒子", "充电器", "发票")),
            ("return", "after_sale:return", "询问退换或退款", ("退货", "退款", "退换", "七天无理由")),
            ("warranty", "after_sale:warranty", "询问保修或售后", ("保修", "保修期", "售后", "质保")),
            ("transaction", "transaction:method", "询问交易或交付方式", ("面交", "自提", "怎么买", "怎么拍", "交易方式")),
        )
        for category, key, summary, keywords in topic_rules:
            if any(keyword in text for keyword in keywords):
                return category, key, normalized, summary
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        return "general", f"general:{digest}", normalized, text[:40] or "其他事项"

    @staticmethod
    def _same_general_topic(current, existing):
        if current == existing:
            return True
        if min(len(current), len(existing)) >= 4 and (current in existing or existing in current):
            return True
        return SequenceMatcher(None, current, existing).ratio() >= 0.72

    def track_conversation_topic(
        self, chat_id, buyer_user_id, item_id, message, occurrence_key, *, observed_at=None,
    ):
        """
        记录买家当前事项，返回最近 30 天跨会话的去重轮数与风险状态。
        occurrence_key 用于抵抗 WebSocket 重复投递。
        """
        now = observed_at or datetime.now()
        now_iso = now.isoformat()
        cutoff = (now - timedelta(days=self.RISK_WINDOW_DAYS)).isoformat()
        category, topic_key, normalized, summary = self._topic_descriptor(message)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            duplicate = conn.execute(
                "SELECT topic_id FROM risk_message_events WHERE occurrence_key=?",
                (occurrence_key,),
            ).fetchone()
            is_new_topic = False
            topic_id = int(duplicate["topic_id"] or 0) if duplicate else 0
            if not duplicate:
                if category == "general":
                    candidates = conn.execute(
                        """SELECT id, topic_key, normalized_text FROM conversation_topics
                           WHERE chat_id=? AND topic_category='general'""",
                        (chat_id,),
                    ).fetchall()
                    matched = next(
                        (row for row in candidates if self._same_general_topic(normalized, row["normalized_text"])),
                        None,
                    )
                    if matched:
                        topic_id, topic_key = int(matched["id"]), str(matched["topic_key"])
                else:
                    matched = conn.execute(
                        "SELECT id FROM conversation_topics WHERE chat_id=? AND topic_key=?",
                        (chat_id, topic_key),
                    ).fetchone()
                    if matched:
                        topic_id = int(matched["id"])

                if topic_id:
                    conn.execute(
                        """UPDATE conversation_topics
                           SET last_message=?, last_seen_at=?, buyer_user_id=?, item_id=?
                           WHERE id=?""",
                        (message, now_iso, buyer_user_id, item_id, topic_id),
                    )
                else:
                    cursor = conn.execute(
                        """INSERT INTO conversation_topics
                           (chat_id, buyer_user_id, item_id, topic_key, topic_category,
                            normalized_text, topic_summary, first_message, last_message,
                            first_seen_at, last_seen_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            chat_id, buyer_user_id, item_id, topic_key, category,
                            normalized, summary, message, message, now_iso, now_iso,
                        ),
                    )
                    topic_id = int(cursor.lastrowid)
                    is_new_topic = True
                conn.execute(
                    """INSERT INTO risk_message_events
                       (occurrence_key, chat_id, buyer_user_id, topic_id, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (occurrence_key, chat_id, buyer_user_id, topic_id, now_iso),
                )

            turn_count = int(conn.execute(
                """SELECT COUNT(*) FROM conversation_topics
                   WHERE buyer_user_id=? AND last_seen_at>=?""",
                (buyer_user_id, cutoff),
            ).fetchone()[0])
            risk_level = "high" if turn_count >= self.RISK_TURN_THRESHOLD else "normal"
            previous = conn.execute(
                "SELECT risk_level, risk_marked_at FROM buyer_risk_profiles WHERE buyer_user_id=?",
                (buyer_user_id,),
            ).fetchone()
            risk_marked_now = risk_level == "high" and (not previous or previous["risk_level"] != "high")
            risk_marked_at = (
                now_iso if risk_marked_now
                else (previous["risk_marked_at"] if previous and risk_level == "high" else None)
            )
            conn.execute(
                """INSERT INTO buyer_risk_profiles
                   (buyer_user_id, turn_count, risk_level, risk_marked_at, last_evaluated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(buyer_user_id) DO UPDATE SET
                     turn_count=excluded.turn_count,
                     risk_level=excluded.risk_level,
                     risk_marked_at=excluded.risk_marked_at,
                     last_evaluated_at=excluded.last_evaluated_at""",
                (buyer_user_id, turn_count, risk_level, risk_marked_at, now_iso),
            )
            conn.commit()
            return {
                "chat_id": chat_id,
                "buyer_user_id": buyer_user_id,
                "topic_id": topic_id,
                "topic_key": topic_key,
                "topic_summary": summary,
                "new_topic": is_new_topic,
                "duplicate_message": bool(duplicate),
                "turn_count": turn_count,
                "risk_level": risk_level,
                "risk_marked_now": risk_marked_now,
                "risk_marked_at": risk_marked_at,
                "risk_reason": f"最近{self.RISK_WINDOW_DAYS}天已识别{turn_count}个独立事项",
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def list_conversations(self, limit=50):
        """返回最近会话，供控制台接管和人工回复。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cutoff = (datetime.now() - timedelta(days=self.RISK_WINDOW_DAYS)).isoformat()
            rows = conn.execute(
                """WITH recent_topic_counts AS (
                       SELECT buyer_user_id, COUNT(*) AS turn_count
                       FROM conversation_topics
                       WHERE last_seen_at>=?
                       GROUP BY buyer_user_id
                   )
                   SELECT m.chat_id, m.item_id, m.content AS last_message, m.timestamp,
                          (SELECT user_id FROM messages u
                           WHERE u.chat_id=m.chat_id AND u.role='user'
                           ORDER BY u.id DESC LIMIT 1) AS buyer_user_id,
                          COALESCE(rtc.turn_count, 0) AS turn_count,
                          CASE WHEN COALESCE(rtc.turn_count, 0)>=? THEN 'high' ELSE 'normal' END AS risk_level,
                          CASE WHEN COALESCE(rtc.turn_count, 0)>=? THEN p.risk_marked_at ELSE NULL END AS risk_marked_at,
                          (SELECT t.topic_summary FROM conversation_topics t
                           WHERE t.chat_id=m.chat_id ORDER BY t.last_seen_at DESC, t.id DESC LIMIT 1)
                           AS last_topic_summary
                   FROM messages m
                   JOIN (SELECT chat_id, MAX(id) AS max_id FROM messages
                         WHERE chat_id IS NOT NULL GROUP BY chat_id) latest
                     ON latest.max_id=m.id
                   LEFT JOIN recent_topic_counts rtc ON rtc.buyer_user_id=(
                       SELECT user_id FROM messages u
                       WHERE u.chat_id=m.chat_id AND u.role='user'
                       ORDER BY u.id DESC LIMIT 1
                   )
                   LEFT JOIN buyer_risk_profiles p ON p.buyer_user_id=rtc.buyer_user_id
                   ORDER BY m.id DESC LIMIT ?""",
                (
                    cutoff, self.RISK_TURN_THRESHOLD, self.RISK_TURN_THRESHOLD,
                    max(1, min(int(limit), 200)),
                ),
            ).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                item["risk_label"] = "高风险用户" if item["risk_level"] == "high" else ""
                item["risk_reason"] = f"最近{self.RISK_WINDOW_DAYS}天已识别{item['turn_count']}个独立事项"
                items.append(item)
            return items
        finally:
            conn.close()

    def increment_bargain_count_by_chat(self, chat_id):
        """
        基于会话ID增加议价次数
        
        Args:
            chat_id: 会话ID
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # 使用UPSERT语法直接基于chat_id增加议价次数
            cursor.execute(
                """
                INSERT INTO chat_bargain_counts (chat_id, count, last_updated)
                VALUES (?, 1, ?)
                ON CONFLICT(chat_id) 
                DO UPDATE SET count = count + 1, last_updated = ?
                """,
                (chat_id, datetime.now().isoformat(), datetime.now().isoformat())
            )
            
            conn.commit()
            logger.debug(f"会话 {chat_id} 议价次数已增加")
        except Exception as e:
            logger.error(f"增加议价次数时出错: {e}")
            conn.rollback()
        finally:
            conn.close()

    def get_bargain_count_by_chat(self, chat_id):
        """
        基于会话ID获取议价次数
        
        Args:
            chat_id: 会话ID
            
        Returns:
            int: 议价次数
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "SELECT count FROM chat_bargain_counts WHERE chat_id = ?",
                (chat_id,)
            )
            
            result = cursor.fetchone()
            return result[0] if result else 0
        except Exception as e:
            logger.error(f"获取议价次数时出错: {e}")
            return 0
        finally:
            conn.close()
