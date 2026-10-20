import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


WORKER = Path(__file__).resolve().parents[1] / "services" / "xianyu-worker"
import sys
sys.path.insert(0, str(WORKER))

from agent_graph import MODEL_CALL_LIMIT, NODE_MAX_ATTEMPTS, TOOL_CALL_LIMIT, AgentState
from langchain_core.messages import AIMessage
from pipeline import AgentPipeline, KnowledgeBase


class AgentGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.kb = KnowledgeBase(Path(self.temp.name) / "graph.db")
        self.kb._write_faqs([])
        self.kb.add_faq("发货", "什么时候发货", "24 小时内发货", "发货 快递")
        self.no_key = patch.dict(os.environ, {"API_KEY": ""})
        self.no_key.start()
        self.pipeline = AgentPipeline(kb=self.kb)

    def tearDown(self):
        self.no_key.stop()
        self.temp.cleanup()

    def test_graph_exports_confirmed_limits_and_state(self):
        self.assertEqual((MODEL_CALL_LIMIT, TOOL_CALL_LIMIT, NODE_MAX_ATTEMPTS), (4, 6, 2))
        self.assertIn("rewritten_query", AgentState.__annotations__)
        self.assertIn("tool_status", AgentState.__annotations__)

    def test_process_runs_the_graph_and_keeps_contract(self):
        self.pipeline.graph = Mock(wraps=self.pipeline.graph)
        result = self.pipeline.process("什么时候发货", "测试商品")
        self.pipeline.graph.invoke.assert_called_once()
        for key in ("intent", "confidence", "reply", "rewritten_query", "evidence", "stages"):
            self.assertIn(key, result)
        self.assertEqual([stage["name"] for stage in result["stages"]], ["intent", "rewrite", "recall", "rerank", "reply"])

    def test_unexpected_node_error_retries_twice_then_degrades(self):
        self.pipeline.recall = Mock(side_effect=RuntimeError("temporary"))
        result = self.pipeline.process("什么时候发货", "测试商品")
        self.assertEqual(self.pipeline.recall.call_count, 2)
        self.assertEqual(result["evidence"], [])
        self.assertEqual(result["reply"], "在的，具体想了解商品哪一方面呢？")

    def test_low_confidence_route_skips_retrieval(self):
        self.kb.set_reply_policy(low_confidence_handoff=True, confidence_threshold=0.9)
        self.pipeline.recognize_intent = Mock(return_value=("general", 0.5))
        self.pipeline.recall = Mock(side_effect=AssertionError("route must skip retrieval"))
        result = self.pipeline.process("想了解一下", "测试商品")
        self.assertTrue(result["handoff_required"])
        self.assertEqual(result["reply"], "-")

    def test_deterministic_safety_node_still_guards_price(self):
        result = self.pipeline.process("最低多少钱", "测试商品")
        self.assertGreaterEqual(
            min(float(value) for value in __import__("re").findall(r"\d+(?:\.\d+)?", result["reply"])),
            float(result["strategy"]["min_price"]),
        )

    def test_reply_uses_create_agent_read_only_tool_and_limits(self):
        captured = {}

        class FakeAgent:
            def invoke(inner_self, _payload):
                captured["tools"][0].invoke({"query": "最低多少钱", "limit": 3})
                return {"messages": [
                    AIMessage(content="", tool_calls=[{
                        "name": "search_faq", "args": {"query": "最低多少钱", "limit": 3},
                        "id": "faq-call-1", "type": "tool_call",
                    }]),
                    AIMessage(content="只要 1 元"),
                ]}

        def fake_create_agent(**kwargs):
            captured.update(kwargs)
            return FakeAgent()

        def budgeted_json(system, user, fallback, schema):
            self.assertTrue(self.pipeline.model._consume_model_calls())
            return fallback

        self.pipeline.model.json = Mock(side_effect=budgeted_json)
        with patch.dict(os.environ, {"API_KEY": "test-only"}), patch(
            "agent_graph.create_agent", side_effect=fake_create_agent,
        ):
            result = self.pipeline.process("最低多少钱", "测试商品")

        self.assertEqual(result["tool_status"], "completed")
        self.assertEqual(result["tool_calls"][0]["tool_call_id"], "faq-call-1")
        self.assertEqual(captured["tools"][0].name, "search_faq")
        self.assertEqual([item.run_limit for item in captured["middleware"]], [4, 6])
        self.assertNotEqual(result["reply"], "只要 1 元")

    def test_reply_agent_limit_message_uses_safe_fallback(self):
        class FakeAgent:
            def invoke(self, _payload):
                return {"messages": [AIMessage(content="Model call limits exceeded: run limit (1/1)")]}

        self.pipeline.model.json = Mock(side_effect=lambda _system, _user, fallback, _schema: fallback)
        with patch.dict(os.environ, {"API_KEY": "test-only"}), patch(
            "agent_graph.create_agent", return_value=FakeAgent(),
        ):
            result = self.pipeline.process("什么时候发货", "测试商品")
        self.assertNotIn("Model call limits exceeded", result["reply"])
        self.assertEqual(result["reply"], "24 小时内发货")
        self.assertEqual(result["tool_status"], "limit_reached")


if __name__ == "__main__":
    unittest.main()
