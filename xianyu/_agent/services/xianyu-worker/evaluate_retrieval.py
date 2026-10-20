"""Evaluate FAQ retrieval without calling the chat-completions model."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipeline import AgentPipeline, KnowledgeBase, PROJECT_ROOT


def resolve_relevant_ids(case: dict, faqs: list[dict]) -> set[int]:
    relevant: set[int] = set()
    for rule in case.get("relevant", []):
        for faq in faqs:
            if not faq.get("enabled", True):
                continue
            if rule.get("scene") and rule["scene"] != faq.get("scene"):
                continue
            if rule.get("question_contains") and rule["question_contains"] not in faq.get("question", ""):
                continue
            relevant.add(int(faq["id"]))
    return relevant


def answer_is_correct(answer: str, case: dict) -> bool:
    required = case.get("required_phrases", [])
    forbidden = case.get("forbidden_phrases", [])
    return bool(answer) and all(term in answer for term in required) and not any(term in answer for term in forbidden)


def evaluate(pipeline: AgentPipeline, cases: list[dict], ks: tuple[int, ...] = (1, 3, 5)) -> dict:
    if not cases:
        raise ValueError("评测集不能为空")
    if not ks or any(k < 1 for k in ks):
        raise ValueError("K 必须是正整数")
    faqs = pipeline.kb.list_faqs()
    recalls = {k: [] for k in ks}
    reciprocal_ranks: list[float] = []
    correctness: list[float] = []
    details = []
    for case in cases:
        relevant = resolve_relevant_ids(case, faqs)
        if not relevant:
            raise ValueError(f"评测项未匹配到知识库问答：{case.get('query', '')}")
        results = pipeline.recall(case["query"], limit=max(ks))
        retrieved = [int(row["id"]) for row in results]
        for k in ks:
            recalls[k].append(len(set(retrieved[:k]) & relevant) / len(relevant))
        rank = next((index for index, faq_id in enumerate(retrieved, start=1) if faq_id in relevant), 0)
        reciprocal_ranks.append(1 / rank if rank else 0.0)
        top_answer = results[0]["answer"] if results else ""
        is_correct = answer_is_correct(top_answer, case)
        correctness.append(float(is_correct))
        details.append({
            "query": case["query"],
            "relevant_ids": sorted(relevant),
            "retrieved_ids": retrieved,
            "first_relevant_rank": rank or None,
            "answer_correct": is_correct,
        })
    count = len(cases)
    return {
        "cases": count,
        "retrieval_mode": pipeline.retrieval_mode,
        "metrics": {
            **{f"recall@{k}": round(sum(values) / count, 4) for k, values in recalls.items()},
            "mrr": round(sum(reciprocal_ranks) / count, 4),
            "answer_accuracy": round(sum(correctness) / count, 4),
        },
        "details": details,
    }


def main():
    parser = argparse.ArgumentParser(description="评测 Xianyu Agent Desk FAQ 混合检索")
    parser.add_argument("--dataset", type=Path, default=PROJECT_ROOT / "evaluation" / "faq_retrieval_eval.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cases = json.loads(args.dataset.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise ValueError("评测集 JSON 顶层必须是数组")
    report = evaluate(AgentPipeline(kb=KnowledgeBase()), cases)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
