from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from astrbot.core import AstrBotConfig

from astrbot_plugin_meme_forge.core.arguments import strip_trigger_prefix
from astrbot_plugin_meme_forge.main import MemeForgePlugin


class TriggerPrefixTests(unittest.TestCase):
    def test_word_prefix_requires_boundary(self) -> None:
        self.assertEqual(
            strip_trigger_prefix("meme 奶茶 左手", "meme"),
            "奶茶 左手",
        )
        self.assertIsNone(strip_trigger_prefix("meme工坊帮助", "meme"))

    def test_punctuation_prefix_can_touch_keyword(self) -> None:
        self.assertEqual(
            strip_trigger_prefix("#奶茶 左手", "#"),
            "奶茶 左手",
        )

    def test_empty_prefix_keeps_direct_keyword(self) -> None:
        self.assertEqual(
            strip_trigger_prefix("奶茶 左手", ""),
            "奶茶 左手",
        )


class PluginSchemaTests(unittest.TestCase):
    def test_keyword_aliases_use_astrbot_template_list_schema(self) -> None:
        schema_path = Path(__file__).parents[1] / "_conf_schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        alias_schema = schema["keyword_aliases"]
        template = alias_schema["templates"]["alias_mapping"]
        self.assertEqual(set(template["items"]), {"alias", "original"})

        with tempfile.TemporaryDirectory() as directory:
            config = AstrBotConfig(
                str(Path(directory) / "config.json"),
                schema=schema,
            )
        self.assertEqual(config["keyword_aliases"], [])
        self.assertEqual(config["max_favorites"], 50)
        self.assertTrue(config["grabber_enabled"])
        self.assertEqual(config["grabber_send_mode"], "file")
        self.assertEqual(config["grabber_max_files"], 8)
        self.assertEqual(config["history_limit"], 500)
        self.assertEqual(config["dashboard_preview_max_mb"], 4)


class RecentMemeTests(unittest.TestCase):
    class Event:
        def __init__(self, sender_id: str, platform: str = "test") -> None:
            self.sender_id = sender_id
            self.platform = platform

        def get_sender_id(self) -> str:
            return self.sender_id

        def get_platform_name(self) -> str:
            return self.platform

    def test_keeps_three_distinct_memes_per_sender(self) -> None:
        plugin = MemeForgePlugin.__new__(MemeForgePlugin)
        plugin._recent_memes = {}
        plugin.engine = SimpleNamespace(get_keywords=lambda meme: [meme.keyword])
        event = self.Event("alice")
        memes = [SimpleNamespace(key=f"meme_{index}", keyword=f"表情{index}") for index in range(4)]

        for meme in memes:
            plugin._remember_meme(event, meme)

        history = plugin._recent_memes["test:alice"]
        self.assertEqual([entry[1] for entry in history], ["meme_3", "meme_2", "meme_1"])

        plugin._remember_meme(event, memes[1], "自定义触发词")
        self.assertEqual(
            plugin._recent_memes["test:alice"],
            [("自定义触发词", "meme_1"), ("表情3", "meme_3"), ("表情2", "meme_2")],
        )

        other_event = self.Event("bob")
        self.assertNotIn("test:bob", plugin._recent_memes)
        plugin._remember_meme(other_event, memes[0])
        self.assertEqual(plugin._recent_memes["test:bob"], [("表情0", "meme_0")])


if __name__ == "__main__":
    unittest.main()
