"""Run the labeled 170-case route, retrieval, answer, and latency evaluation."""
import argparse
import csv
import json
import re
import statistics
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8787"
DATASET = ROOT / "evaluation" / "faq_metric_170_cases.json"
REPORT = ROOT / "evaluation" / "faq_metric_170_live_report.json"
AUDIT_CSV = ROOT / "evaluation" / "faq_metric_170_intent_audit.csv"

def get_json(path):
    with urllib.request.urlopen(BASE + path, timeout=15) as response:
        return json.load(response)

def relevant_ids(case, faqs):
    ids = set()
    for rule in case.get("relevant", []):
        for faq in faqs:
            if not faq.get("enabled", True):
                continue
            if rule.get("scene") and rule["scene"] != faq.get("scene"):
                continue
            if rule.get("question_contains") and rule["question_contains"] not in faq.get("question", ""):
                continue
            ids.add(int(faq["id"]))
    return ids

def answer_ok(reply, case):
    text = re.sub(r"\s+", "", str(reply or ""))
    if not text or "Model call limits exceeded" in text:
        return False
    if case.get("category") == "order_realtime":
        query = case.get("query", "")
        unsupported_promises = (
            "我帮您核对", "我帮你核对", "我帮您核实", "我去帮您核实", "我帮你核实",
            "我帮你看看", "我帮您看看", "帮你一起看", "帮您一起看", "我帮您查询", "我帮你查询",
            "我这边帮着看", "我帮着看", "我帮您查", "我帮你查",
        )
        if any(phrase in text for phrase in unsupported_promises):
            return False
        if "地址" in query:
            return any(phrase in text for phrase in ("订单里自行", "订单中自行", "订单里尝试", "订单中尝试"))
        limitation = any(phrase in text for phrase in (
            "查不到实时", "看不到实时", "没法确认", "无法确认", "没法直接判断", "查不到实时订单",
        ))
        self_service = any(phrase in text for phrase in (
            "订单详情", "订单里", "订单页面", "官方渠道", "快递官方", "官方客服", "联系承运方",
            "联系快递", "网点电话", "快递员电话", "物流轨迹",
        ))
        return limitation and self_service
    if str(case.get("category", "")).startswith("return_policy"):
        query = case.get("query", "")
        if "多久需要验货" in query:
            compact = re.sub(r"[^\w]", "", text)
            timely = "及时验货" in compact or "尽快验货" in compact
            return timely and "建议" in compact and "当天" in compact
        if "检查" in query or "验货" in query or "发现问题" in query:
            return any(term in text for term in ("验货", "检查"))
        compact = re.sub(r"[^\w]", "", text)
        policy = "非质量问题" in compact and ("不退" in compact or ("不支持" in compact and "退" in compact))
        return policy and ("七天" not in query or "七天" in text or "无理由" in text)
    if case.get("category") == "shipping_carrier_multiturn":
        return "圆通" in text and any(term in text for term in ("可以", "能", "安排", "发"))
    required = [re.sub(r"\s+", "", str(x)) for x in case.get("required_phrases", [])]
    forbidden = [re.sub(r"\s+", "", str(x)) for x in case.get("forbidden_phrases", [])]
    return all(x in text for x in required) and not any(x in text for x in forbidden)

def route_decision_reason(out, handoff, confidence, threshold, policy):
    if handoff:
        return out.get("handoff_reason") or "接口返回人工转接/审批标记"
    if out.get("route_decision_reason"):
        return out["route_decision_reason"]
    if not policy.get("low_confidence_handoff", False):
        return "低置信度转人工策略未启用"
    if isinstance(confidence, (int, float)) and isinstance(threshold, (int, float)):
        if confidence < threshold:
            return "置信度低于阈值但接口未返回转人工标记"
        return "置信度达到阈值，接口未返回转人工标记"
    return "接口未返回置信度或阈值，无法归因"

def summarize_intents(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get("intent") or "(missing)"].append(row)
    summary = {}
    for intent, items in grouped.items():
        confidences = [r["intent_confidence"] for r in items if isinstance(r.get("intent_confidence"), (int, float))]
        summary[intent] = {
            "cases": len(items),
            "mean_confidence": round(statistics.mean(confidences), 4) if confidences else None,
            "min_confidence": min(confidences) if confidences else None,
            "max_confidence": max(confidences) if confidences else None,
            "below_threshold_cases": sum(r.get("confidence_below_threshold") is True for r in items),
            "handoff_marker_cases": sum(bool(r.get("handoff_marker")) for r in items),
        }
    return summary

def write_intent_audit_csv(rows):
    fields = ["case_id", "category", "query", "expected_route", "intent", "intent_confidence",
              "confidence_threshold", "confidence_below_threshold", "intent_stage_detail",
              "handoff_marker", "route_decision_reason"]
    with AUDIT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

def rescore_existing_report():
    cases = json.loads(DATASET.read_text(encoding="utf-8-sig"))
    case_map = {case["case_id"]: case for case in cases}
    report = json.loads(REPORT.read_text(encoding="utf-8-sig"))
    for row in report["cases"]:
        expected = case_map[row["case_id"]]
        expected_handoff = expected["expected_route"] == "human"
        actual_handoff = bool(row.get("actual_handoff"))
        answer_correct = bool(expected["expected_route"] == "ai" and not actual_handoff and answer_ok(row.get("reply"), expected))
        correctly_handled = bool((expected_handoff and actual_handoff) or (not expected_handoff and not actual_handoff and answer_correct))
        row["expected_route"] = expected["expected_route"]
        row["expected_handoff"] = expected_handoff
        row["route_correct"] = expected_handoff == actual_handoff
        row["answer_factually_correct_by_rules"] = answer_correct
        row["ai_resolved"] = correctly_handled
        row["correctly_handled"] = correctly_handled
    rows = report["cases"]
    total = len(rows)
    route_correct = sum(row["route_correct"] for row in rows)
    expected_handoffs = sum(row["expected_handoff"] for row in rows)
    actual_handoffs = sum(row["actual_handoff"] for row in rows)
    true_positive = sum(row["expected_handoff"] and row["actual_handoff"] for row in rows)
    kb_rows = [row for row in rows if row.get("knowledge_applicable") and row.get("http_status") == 200]
    good = [row for row in rows if row.get("http_status") == 200]
    latencies = [row["elapsed_ms"] for row in good]
    pipe_latencies = [row["pipeline_ms"] for row in good if isinstance(row.get("pipeline_ms"), (int, float))]
    route_misses = sum(not row["route_correct"] for row in rows)
    answer_misses = sum(row["expected_route"] == "ai" and not row["answer_factually_correct_by_rules"] for row in rows)
    report["failure_breakdown"] = {"route_mismatch": route_misses, "ai_answer_rule_failed": answer_misses}
    report["definitions"]["ai_answer_rate"] = "预期转人工且实际转人工，或预期AI回答且未转人工并回答正确的数量 / 全部有效用例数"
    category_summary = defaultdict(lambda: {"cases": 0, "expected_handoff": 0, "actual_handoff": 0, "ai_resolved": 0, "route_correct": 0})
    for row in rows:
        summary = category_summary[row["category"]]
        summary["cases"] += 1
        summary["expected_handoff"] += int(row["expected_handoff"])
        summary["actual_handoff"] += int(row["actual_handoff"])
        summary["ai_resolved"] += int(row["ai_resolved"])
        summary["route_correct"] += int(row["route_correct"])
    report["category_summary"] = dict(category_summary)
    report["intent_summary"] = summarize_intents(rows)
    report["metrics"].update({
        "ai_answer_rate_pct": round(100 * sum(row["correctly_handled"] for row in rows) / total, 2) if total else None,
        "correctly_handled_cases": sum(row["correctly_handled"] for row in rows),
        "correct_ai_answer_cases": sum(row["answer_factually_correct_by_rules"] for row in rows),
        "correct_expected_handoff_cases": true_positive,
        "handoff_rate_pct": round(100 * actual_handoffs / total, 2) if total else None,
        "handoff_accuracy_pct": round(100 * route_correct / total, 2) if total else None,
        "handoff_precision_pct": round(100 * true_positive / actual_handoffs, 2) if actual_handoffs else None,
        "handoff_recall_pct": round(100 * true_positive / expected_handoffs, 2) if expected_handoffs else None,
        "knowledge_hit_rate_pct": round(100 * sum(bool(row.get("knowledge_hit")) for row in kb_rows) / len(kb_rows), 2) if kb_rows else None,
        "knowledge_hit_cases": sum(bool(row.get("knowledge_hit")) for row in kb_rows),
        "knowledge_applicable_cases": len(kb_rows),
        "knowledge_hit_top1_pct": round(100 * sum(bool(row.get("top1_hit")) for row in kb_rows) / len(kb_rows), 2) if kb_rows else None,
        "average_response_ms": round(statistics.mean(latencies), 1) if latencies else None,
        "median_response_ms": round(statistics.median(latencies), 1) if latencies else None,
        "p95_response_ms": round(sorted(latencies)[int(.95 * (len(latencies) - 1))], 1) if latencies else None,
        "mean_pipeline_ms": round(statistics.mean(pipe_latencies), 1) if pipe_latencies else None,
        "expected_handoff_cases": expected_handoffs, "actual_handoff_cases": actual_handoffs,
        "correct_route_cases": route_correct,
    })
    report["scoring_mode"] = "re-scored saved live replies with case-aligned semantic rubrics; no model/API calls"
    write_intent_audit_csv(rows)
    report["intent_audit_csv"] = str(AUDIT_CSV)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, ensure_ascii=False, indent=2))
    print(f"Report: {REPORT}")

def main():
    cases = json.loads(DATASET.read_text(encoding="utf-8-sig"))
    health = get_json("/health")
    policy = get_json("/api/reply-policy")
    agent_mode = get_json("/api/agent-mode")
    faqs = get_json("/api/faqs").get("items", [])
    results = []
    for index, case in enumerate(cases, 1):
        expected_ids = relevant_ids(case, faqs)
        payload = {
            "message": case["query"], "item_title": "170条扩展评测（非真实买家）",
            "item_desc": "自动评测虚拟问题，无真实商品、订单或买家。",
            "item_id": "*", "context": case.get("context", []),
        }
        request = urllib.request.Request(
            BASE + "/api/pipeline/test",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = json.load(response)
            elapsed = (time.perf_counter() - started) * 1000
            out = body.get("result", body)
            evidence = out.get("evidence") or []
            ids = [int(row["id"]) for row in evidence if isinstance(row, dict) and row.get("id") is not None]
            hit = bool(set(ids) & expected_ids) if case.get("knowledge_applicable") else None
            top1 = bool(ids and ids[0] in expected_ids) if case.get("knowledge_applicable") else None
            handoff = bool(out.get("handoff_required") or out.get("approval_required") or out.get("pending_approval") or out.get("approval_status") == "awaiting_approval")
            confidence = out.get("confidence")
            threshold = policy.get("confidence_threshold")
            stages = out.get("stages") or []
            intent_stage = next((stage for stage in stages if stage.get("name") == "intent"), None)
            expected_handoff = case["expected_route"] == "human"
            correct = answer_ok(out.get("reply"), case) if case["expected_route"] == "ai" and not handoff else False
            ai_resolved = bool((expected_handoff and handoff) or (not expected_handoff and not handoff and correct))
            results.append({
                "case_id": case["case_id"], "category": case["category"], "expected_route": case["expected_route"],
                "query": case["query"], "http_status": 200, "elapsed_ms": round(elapsed, 1),
                "pipeline_ms": out.get("total_latency_ms"), "relevant_evidence_ids": ids,
                "intent": out.get("intent"), "intent_confidence": confidence,
                "confidence_threshold": threshold,
                "confidence_below_threshold": (confidence < threshold) if isinstance(confidence, (int, float)) and isinstance(threshold, (int, float)) else None,
                "intent_stage_detail": intent_stage.get("detail") if intent_stage else None,
                "route_decision_reason": route_decision_reason(out, handoff, confidence, threshold, policy),
                "handoff_marker": handoff,
                "knowledge_applicable": bool(case.get("knowledge_applicable")), "knowledge_hit": hit,
                "top1_hit": top1, "expected_handoff": expected_handoff, "actual_handoff": handoff,
                "route_correct": handoff == expected_handoff, "answer_factually_correct_by_rules": correct,
                "ai_resolved": ai_resolved, "correctly_handled": ai_resolved, "tool_status": out.get("tool_status"),
                "reply": str(out.get("reply", "")),
            })
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000
            expected_handoff = case["expected_route"] == "human"
            results.append({
                "case_id": case["case_id"], "category": case["category"], "expected_route": case["expected_route"],
                "query": case["query"], "http_status": None, "elapsed_ms": round(elapsed, 1),
                "error": str(exc), "knowledge_applicable": bool(case.get("knowledge_applicable")),
                "intent": None, "intent_confidence": None, "confidence_threshold": policy.get("confidence_threshold"),
                "confidence_below_threshold": None, "intent_stage_detail": None,
                "route_decision_reason": "请求失败，无意图输出", "handoff_marker": False,
                "knowledge_hit": False if case.get("knowledge_applicable") else None,
                "top1_hit": False if case.get("knowledge_applicable") else None,
                "expected_handoff": expected_handoff, "actual_handoff": False,
                "route_correct": False, "answer_factually_correct_by_rules": False,
                "ai_resolved": False, "correctly_handled": False,
            })
        if index % 10 == 0:
            print(f"Completed {index}/{len(cases)}", flush=True)

    successful = [row for row in results if row.get("http_status") == 200]
    latencies = [row["elapsed_ms"] for row in successful]
    pipe_latencies = [row["pipeline_ms"] for row in successful if isinstance(row.get("pipeline_ms"), (int, float))]
    kb_rows = [row for row in successful if row.get("knowledge_applicable")]
    expected_handoffs = [row for row in results if row["expected_handoff"]]
    actual_handoffs = [row for row in results if row["actual_handoff"]]
    true_positive = sum(row["expected_handoff"] and row["actual_handoff"] for row in results)
    route_correct = sum(row["route_correct"] for row in results)
    failures = Counter(
        "model_call_limit" if "Model call limits exceeded" in row.get("reply", "") else "request_error"
        for row in results if row.get("http_status") != 200 or "Model call limits exceeded" in row.get("reply", "")
    )
    failures["route_mismatch"] = sum(not row["route_correct"] for row in results)
    failures["ai_answer_rule_failed"] = sum(row["expected_route"] == "ai" and not row["answer_factually_correct_by_rules"] for row in results)
    category_summary = defaultdict(lambda: {"cases": 0, "expected_handoff": 0, "actual_handoff": 0, "ai_resolved": 0, "route_correct": 0})
    for row in results:
        summary = category_summary[row["category"]]
        summary["cases"] += 1
        summary["expected_handoff"] += int(row["expected_handoff"])
        summary["actual_handoff"] += int(row["actual_handoff"])
        summary["ai_resolved"] += int(row["ai_resolved"])
        summary["route_correct"] += int(row["route_correct"])
    total = len(results)
    report = {
        "dataset_path": str(DATASET), "case_count": total, "successful_requests": len(successful),
        "failed_requests": total - len(successful), "worker_status": health.get("status"),
        "reply_policy": policy, "agent_mode": agent_mode, "live_faq_count": len(faqs), "category_summary": dict(category_summary),
        "intent_summary": summarize_intents(results),
        "failure_breakdown": dict(failures), "no_live_buyer_messages_sent": True,
        "data_source": "local Worker /api/pipeline/test; chat_id=console-test",
        "definitions": {
            "ai_answer_rate": "预期转人工且实际转人工，或预期AI回答且未转人工并回答正确的数量 / 全部有效用例数",
            "handoff_rate": "实际转人工或人工审批的数量 / 全部有效用例数",
            "handoff_accuracy": "转人工/不转人工决策正确的数量 / 全部有效用例数；同时报告转人工精确率与召回率",
            "knowledge_hit_rate": "出现相关证据的知识库适用用例数 / 全部知识库适用用例数；不适用用例不进入分母",
            "average_response_time": "本地测试接口端到端请求耗时均值；包含模型调用，不代表闲鱼消息送达时延",
        },
        "metrics": {
            "ai_answer_rate_pct": round(100 * sum(row["ai_resolved"] for row in results) / total, 2),
            "correctly_handled_cases": sum(row["correctly_handled"] for row in results),
            "correct_ai_answer_cases": sum(row["answer_factually_correct_by_rules"] for row in results),
            "correct_expected_handoff_cases": true_positive,
            "handoff_rate_pct": round(100 * len(actual_handoffs) / total, 2),
            "handoff_accuracy_pct": round(100 * route_correct / total, 2),
        "handoff_precision_pct": round(100 * true_positive / len(actual_handoffs), 2) if actual_handoffs else None,
            "handoff_recall_pct": round(100 * true_positive / len(expected_handoffs), 2) if expected_handoffs else None,
            "knowledge_hit_rate_pct": round(100 * sum(bool(row["knowledge_hit"]) for row in kb_rows) / len(kb_rows), 2) if kb_rows else None,
            "knowledge_hit_cases": sum(bool(row["knowledge_hit"]) for row in kb_rows),
            "knowledge_applicable_cases": len(kb_rows),
            "knowledge_hit_top1_pct": round(100 * sum(bool(row["top1_hit"]) for row in kb_rows) / len(kb_rows), 2) if kb_rows else None,
            "average_response_ms": round(statistics.mean(latencies), 1) if latencies else None,
            "median_response_ms": round(statistics.median(latencies), 1) if latencies else None,
            "p95_response_ms": round(sorted(latencies)[int(.95 * (len(latencies) - 1))], 1) if latencies else None,
            "mean_pipeline_ms": round(statistics.mean(pipe_latencies), 1) if pipe_latencies else None,
            "expected_handoff_cases": len(expected_handoffs), "actual_handoff_cases": len(actual_handoffs),
            "correct_route_cases": route_correct,
        },
        "scoring_mode": "live run scored with case-aligned semantic rules",
        "intent_audit": {
            "fields_per_case": ["intent", "intent_confidence", "confidence_threshold", "confidence_below_threshold", "intent_stage_detail", "handoff_marker", "route_decision_reason"],
            "confidence_scale": "0-1; a display percentage in intent_stage_detail is informational",
            "note": "handoff_marker表示pipeline测试接口返回的转人工/审批标记，不等同于真实人工坐席已接单；/api/pipeline/test独立跑pipeline，不验证消息投递",
        },
        "intent_audit_csv": str(AUDIT_CSV),
        "cases": results,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_intent_audit_csv(results)
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, ensure_ascii=False, indent=2))
    print(f"Report: {REPORT}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rescore-existing", action="store_true", help="Re-score saved responses without additional model calls")
    args = parser.parse_args()
    if args.rescore_existing:
        rescore_existing_report()
    else:
        main()
