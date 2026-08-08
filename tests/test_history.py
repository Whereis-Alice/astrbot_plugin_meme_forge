from __future__ import annotations

import unittest

from astrbot_plugin_meme_forge.core.history import MemeUsageHistory


class MemeUsageHistoryTests(unittest.TestCase):
    def test_persists_filters_and_summarizes_conversations(self) -> None:
        history = MemeUsageHistory(max_records=3)
        history.remember(
            key="one",
            trigger="一",
            platform="qq",
            session="qq:group:100",
            sender_id="alice",
            sender_name="Alice",
            created_at="2026-08-08T00:00:00+00:00",
        )
        history.remember(
            key="two",
            trigger="二",
            platform="qq",
            session="qq:group:100",
            sender_id="bob",
            sender_name="Bob",
            created_at="2026-08-08T00:01:00+00:00",
        )
        history.remember(
            key="three",
            trigger="三",
            platform="qq",
            session="qq:private:alice",
            sender_id="alice",
            sender_name="Alice",
            created_at="2026-08-08T00:02:00+00:00",
        )

        self.assertEqual(
            [record.key for record in history.recent(session="qq:group:100")],
            ["two", "one"],
        )
        self.assertEqual(
            [record.key for record in history.recent(sender_id="alice")],
            ["three", "one"],
        )
        summaries = history.conversation_summaries()
        self.assertEqual(summaries[0]["session"], "qq:private:alice")
        self.assertEqual(summaries[1]["count"], 2)

        restored = MemeUsageHistory(history.dump(), max_records=3)
        self.assertEqual([record.key for record in restored.records], ["three", "two", "one"])

    def test_discards_malformed_records_and_bounds_history(self) -> None:
        history = MemeUsageHistory([{"key": "invalid"}], max_records=20)
        self.assertEqual(history.records, [])
        for index in range(21):
            history.remember(
                key=str(index),
                trigger=str(index),
                platform="test",
                session="test:group:1",
                sender_id="sender",
                sender_name="sender",
                created_at=f"2026-08-08T00:0{index}:00+00:00",
            )
        self.assertEqual(len(history.records), 20)
        self.assertEqual(history.records[0].key, "20")
        self.assertEqual(history.records[-1].key, "1")


if __name__ == "__main__":
    unittest.main()
