from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from astrbot.core import AstrBotConfig

from astrbot_plugin_meme_forge.core.arguments import strip_trigger_prefix


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


if __name__ == "__main__":
    unittest.main()
