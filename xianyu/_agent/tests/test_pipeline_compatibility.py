import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]

from scripts.generate_pipeline_compat_baseline import _knowledge_base, _normalized
from pipeline import AgentPipeline


class PipelineCompatibilityTests(unittest.TestCase):
    def test_deterministic_cases_match_pre_langchain_snapshot(self):
        baseline = json.loads(
            (PROJECT_ROOT / "evaluation" / "legacy_pipeline_mock_baseline.json").read_text(encoding="utf-8")
        )
        expected = {case["id"]: case for case in baseline["cases"]}

        with patch.dict(os.environ, {"API_KEY": ""}), tempfile.TemporaryDirectory() as directory:
            pipeline = AgentPipeline(kb=_knowledge_base(Path(directory)))
            for case_id, snapshot in expected.items():
                case = snapshot["input"]
                actual = pipeline.process(
                    case["message"],
                    case["item_desc"],
                    case.get("context", []),
                    item_id=case.get("item_id", "baseline-item"),
                    chat_id=f"baseline-{case_id}",
                    bargain_round=int(case.get("bargain_round", 0)),
                )
                self.assertEqual(_normalized(actual), snapshot["output"], case_id)


if __name__ == "__main__":
    unittest.main()
