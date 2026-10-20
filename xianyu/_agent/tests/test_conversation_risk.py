import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path


WORKER = Path(__file__).resolve().parents[1] / "services" / "xianyu-worker"
sys.path.insert(0, str(WORKER))

from context_manager import ChatContextManager


class ConversationRiskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = ChatContextManager(db_path=str(Path(self.temp.name) / "chat.db"))

    def tearDown(self):
        self.temp.cleanup()

    def track(self, chat_id, message, index, *, buyer="buyer-1", observed_at=None):
        return self.manager.track_conversation_topic(
            chat_id,
            buyer,
            f"item-{chat_id}",
            message,
            f"{chat_id}:{index}",
            observed_at=observed_at,
        )

    def test_same_matter_only_counts_once(self):
        first = self.track("chat-1", "最低多少？", 1)
        follow_up = self.track("chat-1", "280能出吗？", 2)

        self.assertTrue(first["new_topic"])
        self.assertFalse(follow_up["new_topic"])
        self.assertEqual(follow_up["turn_count"], 1)
        self.assertEqual(follow_up["risk_level"], "normal")

    def test_five_topics_across_conversations_marks_buyer_high_risk(self):
        cases = [
            ("chat-1", "最低多少？"),
            ("chat-1", "包邮吗？"),
            ("chat-2", "今天可以发货吗？"),
            ("chat-2", "成色怎么样？"),
            ("chat-3", "支持退货吗？"),
        ]
        result = None
        for index, (chat_id, message) in enumerate(cases, 1):
            result = self.track(chat_id, message, index)

        self.assertIsNotNone(result)
        self.assertEqual(result["turn_count"], 5)
        self.assertEqual(result["risk_level"], "high")
        self.assertTrue(result["risk_marked_now"])

        self.manager.add_message_by_chat("chat-3", "buyer-1", "item-chat-3", "user", "支持退货吗？")
        conversation = self.manager.list_conversations()[0]
        self.assertEqual(conversation["turn_count"], 5)
        self.assertEqual(conversation["risk_level"], "high")
        self.assertEqual(conversation["risk_label"], "高风险用户")

    def test_topics_older_than_thirty_days_are_not_counted(self):
        now = datetime.now()
        self.track("old-chat", "最低多少？", 1, observed_at=now - timedelta(days=31))
        messages = ["包邮吗？", "今天发货吗？", "成色怎样？", "支持退货吗？"]
        result = None
        for index, message in enumerate(messages, 2):
            result = self.track(f"chat-{index}", message, index, observed_at=now)

        self.assertEqual(result["turn_count"], 4)
        self.assertEqual(result["risk_level"], "normal")

    def test_duplicate_delivery_is_idempotent(self):
        first = self.track("chat-1", "包邮吗？", 1)
        duplicate = self.track("chat-1", "包邮吗？", 1)

        self.assertTrue(first["new_topic"])
        self.assertTrue(duplicate["duplicate_message"])
        self.assertEqual(duplicate["turn_count"], 1)

    def test_recent_messages_returns_the_latest_ten_rounds_in_order(self):
        for index in range(12):
            self.manager.add_message_by_chat("chat-1", "buyer-1", "item-1", "user", f"问题 {index}")
            self.manager.add_message_by_chat("chat-1", "seller-1", "item-1", "assistant", f"回答 {index}")

        messages = self.manager.get_recent_messages_by_chat("chat-1")

        self.assertEqual(len(messages), 20)
        self.assertEqual(messages[0]["content"], "问题 2")
        self.assertEqual(messages[-1]["content"], "回答 11")
        self.assertEqual([message["role"] for message in messages[:4]], ["user", "assistant", "user", "assistant"])


if __name__ == "__main__":
    unittest.main()
