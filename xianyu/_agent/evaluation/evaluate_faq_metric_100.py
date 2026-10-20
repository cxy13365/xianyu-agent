"""Run a 100-case FAQ eval against a temporary DB copy and inspect project traces read-only."""
import argparse,json,os,shutil,sqlite3,sys,tempfile,time
from pathlib import Path
from statistics import mean
ROOT=Path(__file__).resolve().parents[1]
WORKER=ROOT/"services"/"xianyu-worker"

def run_cases(dataset_path):
 temp=tempfile.TemporaryDirectory(prefix="faq100_eval_")
 previous=os.environ.get("DATA_DIR")
 os.environ["DATA_DIR"]=temp.name
 shutil.copy2(WORKER/"data"/"agent_desk.db",Path(temp.name)/"agent_desk.db")
 sys.path.insert(0,str(WORKER))
 from evaluate_retrieval import resolve_relevant_ids,answer_is_correct
 from pipeline import AgentPipeline,KnowledgeBase
 try:
  cases=json.loads(dataset_path.read_text(encoding="utf-8-sig"))
  if len(cases)!=100: raise ValueError(f"expected 100 cases, got {len(cases)}")
  pipeline=AgentPipeline(kb=KnowledgeBase())
  pipeline.recall("评估预热",limit=1) # model/cache warmup excluded
  faqs=pipeline.kb.list_faqs()
  hits_top1=hits_top5=answered=0
  timings=[]
  details=[]
  for case in cases:
   relevant=resolve_relevant_ids(case,faqs)
   if not relevant: raise ValueError(f"no matching FAQ: {case['query']}")
   started=time.perf_counter()
   result=pipeline.recall(case["query"],limit=5)
   elapsed=(time.perf_counter()-started)*1000
   timings.append(elapsed)
   ids=[int(x["id"]) for x in result]
   hit1=bool(ids and ids[0] in relevant)
   hit5=bool(set(ids[:5])&relevant)
   correct=bool(result and hit1 and answer_is_correct(result[0]["answer"],case))
   hits_top1+=hit1; hits_top5+=hit5; answered+=correct
   details.append({"case_id":case["case_id"],"category":case["category"],"query":case["query"],"top1_faq_id":ids[0] if ids else None,"relevant_faq_ids":sorted(relevant),"hit_top1":hit1,"hit_top5":hit5,"ai_answered_correctly":correct,"retrieval_latency_ms":round(elapsed,2)})
  count=len(cases)
  return {"case_count":count,"warmup_excluded":True,"retrieval_mode":pipeline.retrieval_mode,
   "metrics":{"offline_ai_answer_rate_proxy_pct":round(100*answered/count,2),"knowledge_hit_rate_top1_pct":round(100*hits_top1/count,2),"knowledge_hit_rate_top5_pct":round(100*hits_top5/count,2),"mean_retrieval_latency_ms":round(mean(timings),2),"median_retrieval_latency_ms":round(sorted(timings)[count//2],2)},
   "details":details}
 finally:
  if previous is None: os.environ.pop("DATA_DIR",None)
  else: os.environ["DATA_DIR"]=previous
  temp.cleanup()

def runtime_observations():
 trace_db=WORKER/"data"/"agent_desk.db"
 c=sqlite3.connect(f"file:{trace_db.as_posix()}?mode=ro",uri=True)
 try:
  rows=c.execute("SELECT payload FROM traces WHERE chat_id IS NULL OR chat_id!='console-test'").fetchall()
  valid=[];lat=[];hits=0
  for (raw,) in rows:
   try: p=json.loads(raw)
   except (TypeError,json.JSONDecodeError): continue
   valid.append(p);hits+=bool(p.get("evidence"))
   v=p.get("total_latency_ms")
   if isinstance(v,(int,float)) and v>=0:lat.append(float(v))
  return {"trace_count":len(valid),"knowledge_hit_trace_count":hits,"knowledge_hit_rate_pct":round(100*hits/len(valid),2) if valid else None,"pipeline_latency_sample_count":len(lat),"mean_pipeline_latency_ms":round(mean(lat),1) if lat else None,"limitation":"历史轨迹 hit=含 evidence；耗时为内部流水线耗时，不是端到端送达时间。"}
 finally:c.close()

def main():
 ap=argparse.ArgumentParser()
 ap.add_argument("--dataset",type=Path,default=ROOT/"evaluation"/"faq_metric_100_cases.json")
 ap.add_argument("--output",type=Path,default=ROOT/"evaluation"/"faq_metric_100_report.json")
 a=ap.parse_args()
 result={"dataset":str(a.dataset.relative_to(ROOT)),"faq_testset":run_cases(a.dataset),"project_runtime_traces":runtime_observations(),
  "definitions":{"offline_ai_answer_rate":"correct Top-1 FAQ answer / 100; offline proxy, no live human handoff or model generation","knowledge_hit_rate":"queries with relevant FAQ in Top-1 or Top-5 / 100","testset_average_latency":"mean retrieval time per case after warmup","project_average_latency":"mean total_latency_ms from stored project traces"}}
 a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__":main()

