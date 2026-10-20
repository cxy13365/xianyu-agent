import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

WORKER = Path(__file__).resolve().parents[1] / "services" / "xianyu-worker"
sys.path.insert(0, str(WORKER))
from pipeline import AgentPipeline, IntentClassification, KnowledgeBase, ModelGateway
from faq_tools import execute_faq_tool, search_faq
from test_faq_ranking import FakeEmbeddingGateway, FailingEmbeddingGateway

class FaqToolTests(unittest.TestCase):
    def setUp(self):
        self.embedding_patch = patch("pipeline.EmbeddingGateway", return_value=type("DisabledEmbedding", (), {"enabled": False})())
        self.embedding_patch.start()
        self.addCleanup(self.embedding_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.kb = KnowledgeBase(Path(self.temp.name) / "faq.db")
        self.kb._write_faqs([])
        self.shipping = self.kb.add_faq("发货", "什么时候寄出", "24 小时内发货", "发货 快递")
        self.kb.add_faq("售后", "能退货吗", "非质量问题不退", "退款")
        self.kb.add_faq("发货", "什么时候发货", "不要采用停用答案", enabled=False)
        self.env = patch.dict(os.environ, {"API_KEY": "test-only", "EMBEDDING_API_KEY": ""})
        self.env.start()
        self.pipeline = AgentPipeline(kb=self.kb)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_bm25_search_returns_real_enabled_answers(self):
        result = search_faq(self.pipeline, "什么时候发货")
        self.assertEqual(result["retrieval_mode"], "bm25")
        self.assertEqual(result["embedding_status"], "not_configured")
        self.assertEqual(result["items"][0]["id"], self.shipping)
        self.assertNotIn("不要采用停用答案", json.dumps(result, ensure_ascii=False))

    def test_hybrid_tool_returns_and_persists_vectors(self):
        self.pipeline.embedding = FakeEmbeddingGateway()
        result = search_faq(self.pipeline, "什么时候寄出")
        self.assertEqual(result["retrieval_mode"], "bm25+vector")
        self.assertEqual(result["embedding_status"], "active")
        self.assertEqual(result["items"][0]["id"], self.shipping)
        self.assertEqual(len(self.kb.get_faq_vectors(self.pipeline.embedding.model)), 2)

    def test_service_failure_is_explicit_and_bm25_still_works(self):
        self.pipeline.embedding = FailingEmbeddingGateway()
        result = search_faq(self.pipeline, "什么时候发货")
        self.assertEqual(result["retrieval_mode"], "bm25")
        self.assertEqual(result["embedding_status"], "unavailable")
        self.assertEqual(result["items"][0]["id"], self.shipping)

    def test_no_match_and_empty_knowledge_base(self):
        self.assertEqual(search_faq(self.pipeline, "XYZ")['items'], [])
        self.kb._write_faqs([])
        self.assertEqual(search_faq(self.pipeline, "发货")['items'], [])

    def test_tool_rejects_unknown_names_and_invalid_arguments(self):
        for name, args in [("delete_faq", {}), ("search_faq", []), ("search_faq", {}),
                           ("search_faq", {"query": " "}), ("search_faq", {"query": "x", "limit": True}),
                           ("search_faq", {"query": "x", "limit": 6}),
                           ("search_faq", {"query": "x", "command": "unexpected"})]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                execute_faq_tool(self.pipeline, name, args)

    def test_json_uses_langchain_structured_output(self):
        gateway = ModelGateway()
        structured = Mock()
        structured.invoke.return_value = IntentClassification(intent="shipping", confidence=0.91)
        gateway.chat = Mock()
        gateway.chat.with_structured_output.return_value = structured
        result = gateway.json("分类", "发货时间", {"intent": "general", "confidence": 0.68}, IntentClassification)
        self.assertEqual(result, {"intent": "shipping", "confidence": 0.91})
        gateway.chat.with_structured_output.assert_called_once_with(IntentClassification, method="json_mode")

    def test_fast_mode_remains_explicit(self):
        self.kb.set_reply_policy(simulate_human_typing=False)
        with patch("agent_graph.create_agent", side_effect=AssertionError("must not call")):
            result = self.pipeline.process('什么时候发货', '测试商品')
        self.assertEqual(result['tool_status'], 'fast_mode')

    def test_api_search_and_validation_without_live_account(self):
        from fastapi.testclient import TestClient
        # Prevent the API module's global Runtime from touching production data.
        with patch('pipeline.KnowledgeBase', return_value=self.kb), patch('config_store.ConfigStore') as store, patch('graph_persistence.GraphPersistence'):
            store.return_value.load.return_value = {}
            api = importlib.import_module('control_api')
        runtime = SimpleNamespace(kb=self.kb, store=SimpleNamespace(load=lambda: {}))
        with patch.object(api, 'runtime', runtime):
            client = TestClient(api.app)
            result = client.post('/api/faqs/search', json={"query": "什么时候发货"})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['items'][0]['id'], self.shipping)
            for payload in [{"query": " "}, {"query": "发货", "limit": 9}, {"query": "发货", "limit": True}]:
                self.assertEqual(client.post('/api/faqs/search', json=payload).status_code, 422)


if __name__ == '__main__':
    unittest.main()
