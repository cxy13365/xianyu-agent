"""Generate reproducible compatibility snapshots for the pre-LangChain pipeline."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = PROJECT_ROOT / "services" / "xianyu-worker"
sys.path.insert(0, str(WORKER_DIR))

from config_store import ConfigStore
from evaluate_retrieval import evaluate
from pipeline import AgentPipeline, KnowledgeBase


CASES_PATH = PROJECT_ROOT / "evaluation" / "pipeline_compat_cases.json"
RETRIEVAL_CASES_PATH = PROJECT_ROOT / "evaluation" / "faq_retrieval_eval.json"
MOCK_OUTPUT_PATH = PROJECT_ROOT / "evaluation" / "legacy_pipeline_mock_baseline.json"
LIVE_OUTPUT_PATH = PROJECT_ROOT / "evaluation" / "legacy_pipeline_live_baseline.json"
RETRIEVAL_OUTPUT_PATH = PROJECT_ROOT / "evaluation" / "legacy_retrieval_baseline.json"
SETTINGS_PATH = WORKER_DIR / "data" / "settings.json"


def _normalized(value):
    if isinstance(value, dict):
        return {
            key: _normalized(item)
            for key, item in value.items()
            if key not in {"latency_ms", "total_latency_ms", "tool_call_id"}
        }
    if isinstance(value, list):
        return [_normalized(item) for item in value]
    return value


def _knowledge_base(temp_dir: Path) -> KnowledgeBase:
    kb = KnowledgeBase(
        temp_dir / "baseline.db",
        faq_path=PROJECT_ROOT / "knowledge_base.json",
        product_path=temp_dir / "products.json",
    )
    kb.import_products([
        {
            "id": "baseline-item",
            "title": "脱敏基线商品",
            "description": "二手数码商品，具体状态以实拍和商品描述为准。",
            "price": "899",
            "images": [],
            "url": "",
        }
    ])
    kb.set_strategy("baseline-item", 760, 899, 3)
    return kb


def _run_cases(mode: str) -> dict:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if mode == "mock":
        os.environ["API_KEY"] = ""
        provider = {"configured": False, "model": "deterministic-fallback"}
    else:
        config = ConfigStore(SETTINGS_PATH).load()
        if not config.get("api_key"):
            raise RuntimeError("当前 settings.json 未配置模型 API Key，无法生成真实模型基线")
        ConfigStore.apply_environment(config)
        provider = {
            "configured": True,
            "model": str(config.get("model_name", "")),
            "base_url": str(config.get("model_base_url", "")),
        }

    with tempfile.TemporaryDirectory(prefix="xianyu-pipeline-baseline-") as directory:
        pipeline = AgentPipeline(kb=_knowledge_base(Path(directory)))
        results = []
        for case in cases:
            result = pipeline.process(
                case["message"],
                case["item_desc"],
                case.get("context", []),
                item_id=case.get("item_id", "baseline-item"),
                chat_id=f"baseline-{case['id']}",
                bargain_round=int(case.get("bargain_round", 0)),
            )
            results.append({"id": case["id"], "input": case, "output": _normalized(result)})
    return {
        "schema_version": 1,
        "pipeline": "legacy-pre-langchain",
        "mode": mode,
        "provider": provider,
        "cases": results,
    }


def _run_retrieval() -> dict:
    cases = json.loads(RETRIEVAL_CASES_PATH.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="xianyu-retrieval-baseline-") as directory:
        return evaluate(AgentPipeline(kb=_knowledge_base(Path(directory))), cases)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成旧 Pipeline 兼容基线")
    parser.add_argument("--mode", choices=("mock", "live", "retrieval", "all"), default="all")
    args = parser.parse_args()

    jobs = []
    if args.mode in {"mock", "all"}:
        jobs.append((MOCK_OUTPUT_PATH, _run_cases("mock")))
    if args.mode in {"live", "all"}:
        jobs.append((LIVE_OUTPUT_PATH, _run_cases("live")))
    if args.mode in {"retrieval", "all"}:
        jobs.append((RETRIEVAL_OUTPUT_PATH, _run_retrieval()))

    for path, payload in jobs:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()
