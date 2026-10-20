import sys
import unittest
from pathlib import Path

WORKER_DIR = Path(__file__).resolve().parents[1] / "services" / "xianyu-worker"
sys.path.insert(0, str(WORKER_DIR))

from evaluate_retrieval import answer_is_correct, evaluate, resolve_relevant_ids


class FakeKnowledgeBase:
    def __init__(self, faqs: list[dict]):
        self._faqs = faqs

    def list_faqs(self) -> list[dict]:
        return [dict(row) for row in self._faqs]


class FakePipeline:
    retrieval_mode = "bm25"

    def __init__(self, faqs: list[dict], rankings: dict[str, list[int]]):
        self.kb = FakeKnowledgeBase(faqs)
        self._faqs = {int(row["id"]): row for row in faqs}
        self._rankings = rankings

    def recall(self, query: str, limit: int = 5) -> list[dict]:
        return [self._faqs[faq_id] for faq_id in self._rankings[query][:limit]]


class RetrievalEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.faqs = [
            {"id": 1, "scene": "发货", "question": "何时发货", "answer": "24 小时内发出", "enabled": True},
            {"id": 2, "scene": "售后", "question": "能退吗", "answer": "非质量问题不退", "enabled": True},
            {"id": 3, "scene": "发货", "question": "默认快递", "answer": "圆通或申通", "enabled": False},
        ]

    def test_resolve_relevant_ids_ignores_disabled_faqs(self):
        case = {"relevant": [{"scene": "发货"}]}
        self.assertEqual(resolve_relevant_ids(case, self.faqs), {1})

    def test_answer_correctness_checks_required_and_forbidden_phrases(self):
        case = {"required_phrases": ["24 小时", "发出"], "forbidden_phrases": ["72 小时"]}
        self.assertTrue(answer_is_correct("24 小时内发出", case))
        self.assertFalse(answer_is_correct("72 小时内发出", case))

    def test_evaluate_calculates_recall_mrr_and_answer_accuracy(self):
        pipeline = FakePipeline(self.faqs, {"何时寄出": [2, 1]})
        cases = [{
            "query": "何时寄出",
            "relevant": [{"scene": "发货", "question_contains": "何时"}],
            "required_phrases": ["24 小时"],
            "forbidden_phrases": [],
        }]

        report = evaluate(pipeline, cases, ks=(1, 2))

        self.assertEqual(report["metrics"]["recall@1"], 0.0)
        self.assertEqual(report["metrics"]["recall@2"], 1.0)
        self.assertEqual(report["metrics"]["mrr"], 0.5)
        self.assertEqual(report["metrics"]["answer_accuracy"], 0.0)

    def test_empty_dataset_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "评测集不能为空"):
            evaluate(FakePipeline(self.faqs, {}), [])

    def test_case_without_matching_faq_is_rejected(self):
        pipeline = FakePipeline(self.faqs, {"不存在": []})
        with self.assertRaisesRegex(ValueError, "未匹配到知识库问答"):
            evaluate(pipeline, [{"query": "不存在", "relevant": [{"scene": "不存在"}]}])


if __name__ == "__main__":
    unittest.main()
