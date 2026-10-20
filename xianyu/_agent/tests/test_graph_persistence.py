import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


WORKER = Path(__file__).resolve().parents[1] / "services" / "xianyu-worker"
import sys
sys.path.insert(0, str(WORKER))

from graph_persistence import GraphPersistence
from pipeline import AgentPipeline, KnowledgeBase, PipelineReplyBot


class DisabledEmbedding:
    enabled = False
    model = "disabled"


class GraphPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.kb = KnowledgeBase(root / "knowledge.db")
        self.kb.set_reply_policy(simulate_human_typing=False)
        self.store = GraphPersistence(root / "graph.db")
        self.env = patch.dict(os.environ, {"API_KEY": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.store.close()
        self.temp.cleanup()

    def pipeline(self):
        return AgentPipeline(kb=self.kb, embedding=DisabledEmbedding(), persistence=self.store)

    def test_chat_thread_binding_is_stable(self):
        first = self.store.thread_for_chat("chat-a")
        self.assertEqual(first, self.store.thread_for_chat("chat-a"))
        self.assertNotEqual(first, self.store.thread_for_chat("chat-b"))

    def test_interrupt_modify_approve_runs_safety_before_completion(self):
        pipeline = self.pipeline()
        pending = pipeline.process(
            "最低多少钱", "测试商品", chat_id="chat-price", to_user_id="buyer",
            approval_required=True,
        )
        self.assertEqual(pending["approval_status"], "interrupted")
        run = self.store.latest_run("chat-price")
        self.assertEqual(run["status"], "interrupted")
        self.assertEqual(run["nodes"][-1]["status"], "interrupted")

        approved = pipeline.resume("chat-price", "modify", "只要 1 元")
        self.assertEqual(approved["approval_status"], "approved")
        prices = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", approved["reply"])]
        self.assertTrue(prices)
        self.assertGreaterEqual(min(prices), float(approved["strategy"]["min_price"]))

    def test_resume_does_not_approve_or_send_and_later_modify_is_supported(self):
        pipeline = self.pipeline()
        pipeline.process(
            "最低多少钱", "测试商品", chat_id="chat-resume", to_user_id="buyer",
            approval_required=True,
        )
        paused = pipeline.pause("chat-resume")
        self.assertEqual(paused["status"], "paused")
        resumed = pipeline.resume("chat-resume", "resume")
        self.assertEqual(resumed["approval_status"], "awaiting_approval")
        self.assertEqual(self.store.latest_run("chat-resume")["status"], "awaiting_approval")
        modified = pipeline.resume("chat-resume", "modify", "只要 1 元")
        self.assertEqual(modified["approval_status"], "approved")

    def test_shadow_returns_legacy_and_persists_comparison(self):
        bot = PipelineReplyBot(kb=self.kb, mode="shadow", persistence=self.store)
        bot.pipeline.embedding = DisabledEmbedding()
        bot.legacy_pipeline.embedding = DisabledEmbedding()
        reply = bot.generate_reply(
            "什么时候发货", "测试商品", [], chat_id="chat-shadow",
            item_id="*", to_user_id="buyer",
        )
        self.assertEqual(reply, bot.last_result["reply"])
        self.assertEqual(bot.last_result["run_mode"], "shadow")
        rows = self.store.list_shadow()
        self.assertEqual(len(rows), 1)
        self.assertIn("intent", rows[0]["comparison"])
        self.assertIn("price_safety", rows[0]["comparison"])
        self.assertTrue(PipelineReplyBot._price_safe({
            "intent": "shipping", "reply": "24 小时内发货", "strategy": {"min_price": 760},
        }))


if __name__ == "__main__":
    unittest.main()
