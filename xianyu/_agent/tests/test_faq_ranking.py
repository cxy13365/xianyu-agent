import gc
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

WORKER_DIR = Path(__file__).resolve().parents[1] / "services" / "xianyu-worker"
sys.path.insert(0, str(WORKER_DIR))

from pipeline import AgentPipeline, KnowledgeBase


class FakeEmbeddingGateway:
    enabled = True
    model = "fake-embedding-v1"

    def __init__(self):
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [
            [
                float(sum(term in text for term in ("发货", "快递", "寄出"))),
                float(sum(term in text for term in ("退货", "售后", "退款"))),
            ]
            for text in texts
        ]


class FailingEmbeddingGateway:
    enabled = True
    model = "failing-embedding-v1"

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("模拟向量服务不可用")


class FaqRankingTests(unittest.TestCase):
    def setUp(self):
        self.embedding_patch = patch("pipeline.EmbeddingGateway", return_value=type("DisabledEmbedding", (), {"enabled": False})())
        self.embedding_patch.start()
        self.addCleanup(self.embedding_patch.stop)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.kb = KnowledgeBase(Path(self.temp_dir.name) / "faqs.db")
        with self.kb._connect() as conn:
            conn.execute("DELETE FROM faqs")
        self.kb._write_faqs([])

    def tearDown(self):
        del self.kb
        gc.collect()
        self.temp_dir.cleanup()

    def test_only_enabled_scene_is_used_by_coarse_ranking(self):
        enabled_id = self.kb.add_faq("发货时效", "多久寄出", "24 小时内", enabled=True)
        self.kb.add_faq("发货时效", "多久寄出", "72 小时内", enabled=False)
        pipeline = AgentPipeline(kb=self.kb)
        candidates = pipeline.recall("发货时效")
        self.assertEqual([row["id"] for row in candidates], [enabled_id])

    def test_question_and_answer_are_sent_to_reranker(self):
        faq_id = self.kb.add_faq("物流", "什么时候发货", "今天拍下明天发出")
        pipeline = AgentPipeline(kb=self.kb)
        pipeline.model.json = Mock(return_value={"ranking": [{"id": faq_id, "score": 0.9}]})
        pipeline.rerank("明天能寄吗", [{**self.kb.list_faqs()[0], "coarse_score": 0.5}])
        request = pipeline.model.json.call_args.args[1]
        self.assertIn('"question": "什么时候发货"', request)
        self.assertIn('"answer": "今天拍下明天发出"', request)

    def test_update_persists_editable_fields_and_enabled_state(self):
        faq_id = self.kb.add_faq("旧场景", "旧问法", "旧回答")
        updated = self.kb.update_faq(faq_id, "新场景", "新问法", "新回答", "新关键词", False)
        self.assertEqual(updated["scene"], "新场景")
        self.assertEqual(updated["question"], "新问法")
        self.assertEqual(updated["answer"], "新回答")
        self.assertEqual(updated["keywords"], "新关键词")
        self.assertFalse(updated["enabled"])

    def test_faqs_are_persisted_as_json(self):
        faq_id = self.kb.add_faq("本地场景", "本地问题", "本地回答")
        stored = self.kb.faq_path.read_text(encoding="utf-8")
        self.assertIn('"scene": "本地场景"', stored)

        reloaded = KnowledgeBase(self.kb.db_path, self.kb.faq_path)
        self.assertEqual(reloaded.list_faqs()[0]["id"], faq_id)

    def test_delete_removes_faq(self):
        faq_id = self.kb.add_faq("待删除", "问题", "回答")
        self.assertTrue(self.kb.delete_faq(faq_id))
        self.assertEqual(self.kb.list_faqs(), [])
        self.assertFalse(self.kb.delete_faq(faq_id))

    def test_unanswered_question_is_suggested_after_three_unique_occurrences(self):
        self.kb.record_unanswered_question("什么时候补货？", "chat-1:1", "chat-1")
        self.kb.record_unanswered_question("什么时候补货", "chat-1:2", "chat-1")
        self.assertEqual(self.kb.list_question_suggestions(), [])

        suggestion = self.kb.record_unanswered_question("什么时候补货！", "chat-2:3", "chat-2")

        self.assertEqual(suggestion["status"], "pending")
        self.assertEqual(suggestion["occurrence_count"], 3)
        self.assertEqual(len(self.kb.list_question_suggestions()), 1)

    def test_unanswered_question_occurrence_is_deduplicated_and_resolved_by_faq(self):
        for key in ("chat-1:1", "chat-1:1", "chat-2:2", "chat-3:3"):
            self.kb.record_unanswered_question("支持自提吗？", key, key.split(":")[0])
        suggestion = self.kb.list_question_suggestions()[0]
        self.assertEqual(suggestion["occurrence_count"], 3)

        self.kb.add_faq("交易方式", "支持自提吗", "暂不支持自提")

        self.assertEqual(self.kb.list_question_suggestions(), [])

    def test_product_import_and_price_strategy_are_persisted_as_json(self):
        imported = self.kb.import_products([{
            "title": "真实商品",
            "description": "真实描述",
            "price": "899",
            "images": ["https://example.com/item.jpg"],
            "url": "https://www.goofish.com/item?id=123456",
        }])
        self.assertEqual(imported[0]["id"], "123456")
        self.kb.set_strategy("123456", 760, 899, 4)

        stored = json.loads(self.kb.product_path.read_text(encoding="utf-8"))
        self.assertEqual(stored[0]["title"], "真实商品")
        self.assertEqual(stored[0]["price_safety"]["min_price"], 760)
        self.assertEqual(self.kb.get_strategy("123456")["max_bargain_rounds"], 4)

    def test_hybrid_retrieval_persists_and_reuses_faq_vectors(self):
        shipping_id = self.kb.add_faq("发货", "多久寄出", "24 小时内发出", "发货 快递")
        self.kb.add_faq("售后", "能退款吗", "非质量问题不退", "退货 售后")
        embedding = FakeEmbeddingGateway()
        pipeline = AgentPipeline(kb=self.kb, embedding=embedding)

        first = pipeline.recall("什么时候寄出")
        second = pipeline.recall("发什么快递")

        self.assertEqual(first[0]["id"], shipping_id)
        self.assertEqual(first[0]["retrieval_mode"], "bm25+vector")
        self.assertEqual(embedding.calls, 2)
        self.assertEqual(len(self.kb.get_faq_vectors(embedding.model)), 2)
        self.assertEqual(second[0]["id"], shipping_id)

    def test_updating_faq_invalidates_cached_vector(self):
        faq_id = self.kb.add_faq("发货", "多久寄出", "24 小时内")
        embedding = FakeEmbeddingGateway()
        AgentPipeline(kb=self.kb, embedding=embedding).recall("多久发货")
        self.assertIn(faq_id, self.kb.get_faq_vectors(embedding.model))

        self.kb.update_faq(faq_id, "发货", "几天发出", "48 小时内")
        self.assertNotIn(faq_id, self.kb.get_faq_vectors(embedding.model))

    def test_embedding_failure_falls_back_to_bm25(self):
        shipping_id = self.kb.add_faq("发货时效", "多久寄出", "24 小时内发出", "发货 快递")
        pipeline = AgentPipeline(kb=self.kb, embedding=FailingEmbeddingGateway())

        candidates = pipeline.recall("什么时候发货")

        self.assertEqual(candidates[0]["id"], shipping_id)
        self.assertEqual(pipeline.retrieval_mode, "bm25")
        self.assertEqual(candidates[0]["retrieval_mode"], "bm25")


if __name__ == "__main__":
    unittest.main()
