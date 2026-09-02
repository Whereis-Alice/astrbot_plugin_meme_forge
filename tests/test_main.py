from __future__ import annotations

import asyncio
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
        self.assertEqual(config["avatar_cache_size"], 20)
        self.assertTrue(config["transparent_output_as_gif"])


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


class DisabledListTests(unittest.TestCase):
    @staticmethod
    def _plugin(disabled: list[str]) -> MemeForgePlugin:
        plugin = MemeForgePlugin.__new__(MemeForgePlugin)
        plugin.config = {"disabled_memes": list(disabled)}
        plugin.engine = SimpleNamespace(
            canonical_key=lambda value: {"旧别名": "old_meme"}.get(value, value)
        )
        return plugin

    def test_enabling_drops_stable_key_and_stale_alias(self) -> None:
        plugin = self._plugin(["petpet", "旧别名"])
        self.assertEqual(plugin._next_disabled_list(["old_meme"], True), ["petpet"])

    def test_disabling_appends_sorted_targets(self) -> None:
        plugin = self._plugin(["petpet", "旧别名"])
        self.assertEqual(
            plugin._next_disabled_list(["kiss", "hug"], False),
            ["petpet", "旧别名", "hug", "kiss"],
        )

    def test_disabling_never_duplicates_existing_entries(self) -> None:
        plugin = self._plugin(["petpet"])
        self.assertEqual(plugin._next_disabled_list(["petpet"], False), ["petpet"])

    def test_missing_config_key_falls_back_to_empty_list(self) -> None:
        plugin = self._plugin([])
        plugin.config = {}
        self.assertEqual(plugin._disabled_keys(), [])
        self.assertEqual(plugin._next_disabled_list(["kiss"], False), ["kiss"])


class SaveDisabledListTests(unittest.IsolatedAsyncioTestCase):
    class FakeConfig(dict):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.saves = 0

        def save_config(self) -> None:
            self.saves += 1

    async def test_writes_list_and_saves_once(self) -> None:
        plugin = MemeForgePlugin.__new__(MemeForgePlugin)
        plugin.config = self.FakeConfig({"disabled_memes": ["petpet"]})
        plugin._config_lock = asyncio.Lock()

        await plugin._save_disabled_list(["petpet", "kiss"])

        self.assertEqual(plugin.config["disabled_memes"], ["petpet", "kiss"])
        self.assertEqual(plugin.config.saves, 1)

    async def test_concurrent_saves_are_serialised(self) -> None:
        plugin = MemeForgePlugin.__new__(MemeForgePlugin)
        plugin.config = self.FakeConfig({"disabled_memes": []})
        plugin._config_lock = asyncio.Lock()

        await asyncio.gather(
            plugin._save_disabled_list(["a"]),
            plugin._save_disabled_list(["a", "b"]),
        )

        self.assertEqual(plugin.config.saves, 2)
        self.assertIn(plugin.config["disabled_memes"], (["a"], ["a", "b"]))


if __name__ == "__main__":
    unittest.main()
