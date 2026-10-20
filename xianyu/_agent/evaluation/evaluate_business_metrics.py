"""Calculate demo KPIs and read-only project trace observations."""
import argparse, json, sqlite3
from pathlib import Path
from statistics import mean
ROOT=Path(__file__).resolve().parents[1]
def evaluate(d):
 f,h,k,l=d["common_faq"],d["human_handoff"],d["knowledge_maintenance"],d["response_latency"]
 if f["eligible_inquiries"]<=0 or h["human_handoffs_before_ai"]<=0 or k["manual_minutes_before_ai"]<=0: raise ValueError("denominators must be positive")
 if h["matched_inquiries_before_ai"]!=h["matched_inquiries_after_ai"]: raise ValueError("handoff cohorts must match")
 if not l["ai_seconds"] or len(l["ai_seconds"])!=len(l["baseline_seconds"]): raise ValueError("latency samples must be paired")
 before,after=mean(l["baseline_seconds"]),mean(l["ai_seconds"])
 return {"data_source":d.get("data_source","unspecified"),"note":d.get("note",""),
 "sample_sizes":{"faq_inquiries":f["eligible_inquiries"],"matched_handoff_inquiries":h["matched_inquiries_before_ai"],"maintenance_items":k["matched_work_items"],"paired_latency_samples":len(l["ai_seconds"])},
 "metrics":{"ai_answer_rate_pct":round(100*f["ai_resolved_without_human"]/f["eligible_inquiries"],2),
 "human_handoff_reduction_pct":round(100*(h["human_handoffs_before_ai"]-h["human_handoffs_after_ai"])/h["human_handoffs_before_ai"],2),
 "knowledge_maintenance_effort_reduction_pct":round(100*(k["manual_minutes_before_ai"]-k["manual_minutes_after_ai"])/k["manual_minutes_before_ai"],2),
 "average_response_seconds_before":round(before,3),"average_response_seconds_after":round(after,3),
 "latency_reduction_pct":round(100*(before-after)/before,2) if before else None}}
def observations():
 p=ROOT/"services/xianyu-worker/data/agent_desk.db"
 if not p.exists(): return {"available":False,"reason":"project trace DB missing"}
 c=sqlite3.connect(f"file:{p.as_posix()}?mode=ro",uri=True)
 try:
  rows=c.execute("SELECT chat_id,payload FROM traces WHERE chat_id IS NULL OR chat_id!='console-test'").fetchall()
  lat=[]; evidence=handoff=0
  for _,raw in rows:
   try: d=json.loads(raw)
   except (TypeError,json.JSONDecodeError): continue
   v=d.get("total_latency_ms")
   if isinstance(v,(int,float)) and v>=0: lat.append(v)
   evidence+=bool(d.get("evidence")); handoff+=bool(d.get("handoff_required"))
  return {"available":True,"source":"SQLite traces; console-test excluded","trace_count":len(rows),"latency_sample_count":len(lat),"mean_pipeline_latency_ms":round(mean(lat),1) if lat else None,"traces_with_evidence":evidence,"traces_flagged_handoff":handoff,"limitation":"Pipeline latency is not end-to-end delivery time; no comparable pre-AI baseline exists."}
 finally: c.close()
def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--dataset",type=Path,default=ROOT/"evaluation/business_metrics_demo.json"); ap.add_argument("--output",type=Path); a=ap.parse_args()
 report={"business_demo":evaluate(json.loads(a.dataset.read_text(encoding="utf-8"))),"project_observations":observations()}
 out=json.dumps(report,ensure_ascii=False,indent=2)
 if a.output: a.output.write_text(out+"\n",encoding="utf-8")
 print(out)
if __name__=="__main__": main()

