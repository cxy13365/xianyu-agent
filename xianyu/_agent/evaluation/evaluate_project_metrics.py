"""Evaluate the project FAQ test set and report real trace observations read-only."""
import argparse, json, os, shutil, sqlite3, sys, tempfile
from pathlib import Path
from statistics import mean

ROOT=Path(__file__).resolve().parents[1]
WORKER=ROOT/"services"/"xianyu-worker"

def run_retrieval(dataset_path):
    temp=tempfile.TemporaryDirectory(prefix="xianyu_eval_")
    os.environ["DATA_DIR"]=temp.name
    shutil.copy2(WORKER/"data"/"agent_desk.db",Path(temp.name)/"agent_desk.db")
    sys.path.insert(0,str(WORKER))
    from evaluate_retrieval import evaluate
    from pipeline import AgentPipeline,KnowledgeBase
    try:
        cases=json.loads(dataset_path.read_text(encoding="utf-8"))
        report=evaluate(AgentPipeline(kb=KnowledgeBase()),cases)
        return report
    finally:
        temp.cleanup()
        os.environ.pop("DATA_DIR",None)

def project_observations():
    db=WORKER/"data"/"agent_desk.db"
    c=sqlite3.connect(f"file:{db.as_posix()}?mode=ro",uri=True)
    try:
        rows=c.execute("SELECT payload FROM traces WHERE chat_id IS NULL OR chat_id!='console-test'").fetchall()
        valid=[];latencies=[];hits=0
        for (raw,) in rows:
            try: p=json.loads(raw)
            except (TypeError,json.JSONDecodeError): continue
            valid.append(p)
            hits+=bool(p.get("evidence"))
            v=p.get("total_latency_ms")
            if isinstance(v,(int,float)) and v>=0: latencies.append(float(v))
        return {
          "trace_source":"services/xianyu-worker/data/agent_desk.db; excludes console-test",
          "trace_count":len(valid),
          "knowledge_base_hit_rate_pct":round(100*hits/len(valid),2) if valid else None,
          "knowledge_base_hit_numerator":hits,
          "knowledge_base_hit_denominator":len(valid),
          "mean_pipeline_latency_ms":round(mean(latencies),1) if latencies else None,
          "latency_sample_count":len(latencies),
          "ai_answer_rate_status":"not_observable_from_trace_schema; offline test-set answer accuracy is reported separately",
          "maintenance_effort_reduction_status":"not_observable; no before/after human-maintenance time records",
          "limitation":"Trace hit rate means a trace contained retrieval evidence. Pipeline latency is not buyer-message-to-delivered-reply end-to-end time."
        }
    finally: c.close()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--dataset",type=Path,default=ROOT/"evaluation"/"project_faq_metric_cases.json")
    ap.add_argument("--output",type=Path,default=ROOT/"evaluation"/"project_metrics_eval_report.json")
    a=ap.parse_args()
    faq=run_retrieval(a.dataset)
    report={
      "data_source":"project_faq_test_set_and_read_only_runtime_traces",
      "faq_test_set":{"path":str(a.dataset.relative_to(ROOT)),"case_count":faq["cases"],"retrieval_mode":faq["retrieval_mode"],"metrics":faq["metrics"],"details":faq["details"],
        "ai_answer_rate_proxy":"answer_accuracy on curated common-FAQ cases; offline proxy, not production independent-resolution rate"},
      "project_runtime":project_observations(),
      "definitions":{
        "offline_common_faq_answer_rate":"cases whose top retrieved answer contains every required phrase and no forbidden phrase / all test cases",
        "knowledge_base_hit_rate":"runtime traces with non-empty evidence / valid runtime traces",
        "knowledge_maintenance_effort_reduction":"(pre-AI matched manual minutes - post-AI matched manual minutes) / pre-AI matched manual minutes; unavailable without logged time observations",
        "average_response_time":"mean total_latency_ms over runtime traces; this project field measures internal pipeline latency, not end-to-end delivery"
      }
    }
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=="__main__": main()

