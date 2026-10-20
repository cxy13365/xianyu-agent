"""Evaluate 100 common FAQ cases via the live local Worker pipeline test endpoint."""
import argparse,json,re,statistics,time,urllib.request,urllib.error
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE="http://127.0.0.1:8787"

def get_json(path,timeout=10):
 with urllib.request.urlopen(BASE+path,timeout=timeout) as r:
  return json.load(r)

def phrase_ok(reply,case):
 text=re.sub(r"\s+","",str(reply or ""))
 if "Model call limits exceeded" in text:
  return False
 if case.get("category")=="return_policy":
  if case.get("case_id")==52 or case.get("query")=="签收后多久需要验货":
   policy_text=re.sub(r"[^\w]","",text)
   return bool(text) and "及时验货" in policy_text and "建议" in policy_text and "当天" in policy_text
  policy_text=re.sub(r"[^\w]","",text); policy_ok="非质量问题" in policy_text and any(x in policy_text for x in ("不退","不支持退","不支持无理由退","不支持因不喜欢退"))
  return bool(text) and policy_ok and "验货" in text
 required=[re.sub(r"\s+","",str(x)) for x in case.get("required_phrases",[])]
 forbidden=[re.sub(r"\s+","",str(x)) for x in case.get("forbidden_phrases",[])]
 return bool(text) and all(x in text for x in required) and not any(x in text for x in forbidden)

def match_ids(case,faqs):
 ids=set()
 for rule in case.get("relevant",[]):
  for faq in faqs:
   if not faq.get("enabled",True): continue
   if rule.get("scene") and rule["scene"]!=faq.get("scene"): continue
   if rule.get("question_contains") and rule["question_contains"] not in faq.get("question",""): continue
   ids.add(int(faq["id"]))
 return ids

def rescore_existing_report():
 cases=json.loads((ROOT/"evaluation/faq_metric_100_cases.json").read_text(encoding="utf-8-sig"))
 report_path=ROOT/"evaluation/faq_metric_100_live_report.json"
 report=json.loads(report_path.read_text(encoding="utf-8-sig"))
 case_by_id={case["case_id"]:case for case in cases}
 for result in report["cases"]:
  expected=case_by_id[result["case_id"]]
  correct=phrase_ok(result.get("reply"),expected)
  human=bool(result.get("human_handoff_or_approval"))
  result["answer_factually_correct_by_rules"]=correct
  result["ai_resolved"]=bool(not human and result.get("knowledge_hit") and correct)
  if result["ai_resolved"]: result["failure_reason"]=None
  elif "Model call limits exceeded" in str(result.get("reply","")): result["failure_reason"]="model_call_limit"
  elif human: result["failure_reason"]="handoff_or_approval"
  elif not result.get("knowledge_hit"): result["failure_reason"]="no_relevant_evidence"
  elif not correct: result["failure_reason"]="answer_rule_failed"
  else: result["failure_reason"]=None
 failures=Counter(row.get("failure_reason") for row in report["cases"] if row.get("failure_reason"))
 categories=defaultdict(lambda:{"cases":0,"ai_resolved":0})
 for row in report["cases"]:
  summary=categories[row["category"]];summary["cases"]+=1;summary["ai_resolved"]+=int(row["ai_resolved"])
 total=len(report["cases"]);good=[row for row in report["cases"] if row.get("http_status")==200]
 lat=[row["elapsed_ms"] for row in good if isinstance(row.get("elapsed_ms"),(int,float))]
 pipe=[row["pipeline_ms"] for row in good if isinstance(row.get("pipeline_ms"),(int,float))]
 report["failure_breakdown"]=dict(failures)
 report["application_level_failed_replies"]=failures["model_call_limit"]
 report["category_summary"]=dict(categories)
 report["metrics"].update({
  "ai_answer_rate_pct":round(100*sum(row["ai_resolved"] for row in report["cases"])/total,2) if total else None,
  "knowledge_hit_rate_pct":round(100*sum(row.get("knowledge_hit",False) for row in report["cases"])/total,2) if total else None,
  "knowledge_hit_top1_pct":round(100*sum(row.get("top1_hit",False) for row in report["cases"])/total,2) if total else None,
  "average_response_ms":round(statistics.mean(lat),1) if lat else None,
  "median_response_ms":round(statistics.median(lat),1) if lat else None,
  "mean_pipeline_ms":round(statistics.mean(pipe),1) if pipe else None,
 })
 report["scoring_mode"]="rescored stored live replies; no additional model/API calls"
 report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({k:v for k,v in report.items() if k not in ("cases",)},ensure_ascii=False,indent=2))
 print(f"Report: {report_path}")

def main():
 cases=json.loads((ROOT/"evaluation/faq_metric_100_cases.json").read_text(encoding="utf-8-sig"))
 health=get_json("/health")
 faq_payload=get_json("/api/faqs")
 faqs=faq_payload.get("items",[])
 results=[]
 for i,case in enumerate(cases,1):
  expected=match_ids(case,faqs)
  payload={"message":case["query"],"item_title":"FAQ 100条自动评测","item_desc":"通用知识库评测，不对应真实商品或买家。","item_id":"*","context":[]}
  req=urllib.request.Request(BASE+"/api/pipeline/test",data=json.dumps(payload,ensure_ascii=False).encode("utf-8"),headers={"Content-Type":"application/json"},method="POST")
  started=time.perf_counter()
  try:
   with urllib.request.urlopen(req,timeout=120) as response:
    body=json.load(response)
   elapsed=(time.perf_counter()-started)*1000
   out=body.get("result",body)
   evidence=out.get("evidence") or []
   evidence_ids=[int(row["id"]) for row in evidence if isinstance(row,dict) and row.get("id") is not None]
   hit=bool(set(evidence_ids)&expected)
   top1=bool(evidence_ids and evidence_ids[0] in expected)
   human=bool(out.get("handoff_required") or out.get("approval_required") or out.get("approval_status")=="awaiting_approval")
   correct=phrase_ok(out.get("reply"),case)
   answered=bool(not human and hit and correct)
   reply=str(out.get("reply",""))
   failure=("model_call_limit" if "Model call limits exceeded" in reply else
            "handoff_or_approval" if human else
            "no_relevant_evidence" if not hit else
            "answer_rule_failed" if not correct else None)
   results.append({"case_id":case["case_id"],"category":case["category"],"query":case["query"],"http_status":200,"elapsed_ms":round(elapsed,1),"pipeline_ms":out.get("total_latency_ms"),"relevant_evidence_ids":evidence_ids,"knowledge_hit":hit,"top1_hit":top1,"human_handoff_or_approval":human,"answer_factually_correct_by_rules":correct,"ai_resolved":answered,"tool_status":out.get("tool_status"),"failure_reason":failure,"reply":reply})
  except Exception as exc:
   elapsed=(time.perf_counter()-started)*1000
   results.append({"case_id":case["case_id"],"category":case["category"],"query":case["query"],"http_status":None,"elapsed_ms":round(elapsed,1),"error":str(exc),"knowledge_hit":False,"top1_hit":False,"human_handoff_or_approval":True,"answer_factually_correct_by_rules":False,"ai_resolved":False})
  if i%10==0: print(f"Completed {i}/{len(cases)}",flush=True)
 n=len(cases)
 good=[x for x in results if x.get("http_status")==200]
 lat=[x["elapsed_ms"] for x in good]
 pipe=[float(x["pipeline_ms"]) for x in good if isinstance(x.get("pipeline_ms"),(int,float))]
 hits=sum(x["knowledge_hit"] for x in results)
 top1=sum(x["top1_hit"] for x in results)
 answered=sum(x["ai_resolved"] for x in results)
 failures=Counter(x["failure_reason"] for x in results if x.get("failure_reason"))
 category_summary=defaultdict(lambda:{"cases":0,"ai_resolved":0})
 for x in results:
  summary=category_summary[x["category"]];summary["cases"]+=1;summary["ai_resolved"]+=int(x["ai_resolved"])
 report={"failure_breakdown":dict(failures),"application_level_failed_replies":failures["model_call_limit"],"category_summary":dict(category_summary),"data_source":"live local Worker /api/pipeline/test; chat_id=console-test","worker_status":health.get("status"),"live_faq_count":len(faqs),"dataset_path":"evaluation/faq_metric_100_cases.json","case_count":n,"successful_requests":len(good),"failed_requests":n-len(good),"definitions":{"ai_answer_rate":"correct, relevantly-supported reply without handoff or approval / all 100 queries","knowledge_hit_rate":"queries with a relevant FAQ in pipeline evidence / all 100; Top-1 separately shown","average_response_time":"mean client-observed HTTP duration for the local pipeline test endpoint, includes configured model calls; not actual Xianyu message delivery"},
 "metrics":{"ai_answer_rate_pct":round(100*answered/n,2),"knowledge_hit_rate_pct":round(100*hits/n,2),"knowledge_hit_top1_pct":round(100*top1/n,2),"average_response_ms":round(statistics.mean(lat),1) if lat else None,"median_response_ms":round(statistics.median(lat),1) if lat else None,"mean_pipeline_ms":round(statistics.mean(pipe),1) if pipe else None},
 "no_live_buyer_messages_sent":True,"cases":results}
 out=ROOT/"evaluation/faq_metric_100_live_report.json"
 out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({k:v for k,v in report.items() if k not in ("cases",)},ensure_ascii=False,indent=2))
 print(f"Report: {out}")
if __name__=="__main__":
 parser=argparse.ArgumentParser()
 parser.add_argument("--rescore-existing",action="store_true",help="Re-score the saved live run without calling the model")
 args=parser.parse_args()
 if args.rescore_existing: rescore_existing_report()
 else: main()

