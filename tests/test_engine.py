from __future__ import annotations

import asyncio
import shlex
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from astrbot_plugin_meme_forge.core.arguments import (
    MemeArgumentParser,
    option_specs_from_params,
)
from astrbot_plugin_meme_forge.core.engine import (
    MemeEngine,
    MemeGenerationError,
)


class MemeEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = MemeEngine({})
        cls.engine.reload_memes()

    def test_real_bubble_tea_metadata_accepts_left_hand(self) -> None:
        match = self.engine.match("奶茶 左手")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.meme.key, "bubble_tea")
        parser = MemeArgumentParser(
            option_specs_from_params(self.engine.get_params(match.meme))
        )
        parsed = parser.parse(match.argument_text)
        self.assertEqual(parsed.options, {"left": True})
        self.assertEqual(parsed.texts, [])

    def test_real_symmetric_metadata_accepts_top(self) -> None:
        match = self.engine.match("对称 上")
        self.assertIsNotNone(match)
        assert match is not None
        parser = MemeArgumentParser(
            option_specs_from_params(self.engine.get_params(match.meme))
        )
        self.assertEqual(parser.parse(match.argument_text).options, {"top": True})

    def test_custom_alias_is_live(self) -> None:
        config = {"keyword_aliases": [{"alias": "喝一杯", "original": "奶茶"}]}
        engine = MemeEngine(config)
        engine.reload_memes()
        match = engine.match("喝一杯 双手")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.meme.key, "bubble_tea")
        self.assertEqual(match.argument_text, "双手")

    def test_random_meme_uses_all_enabled_runtime_memes(self) -> None:
        builtin = SimpleNamespace(
            key="builtin",
            info=SimpleNamespace(keywords=[]),
        )
        extension = SimpleNamespace(
            key="meme_emoji_extension",
            info=SimpleNamespace(keywords=[]),
        )
        disabled = SimpleNamespace(
            key="disabled",
            info=SimpleNamespace(keywords=[]),
        )
        engine = MemeEngine({"disabled_memes": ["disabled"]})
        engine.memes = [builtin, extension, disabled]

        with patch(
            "astrbot_plugin_meme_forge.core.engine.random.choice",
            side_effect=lambda candidates: candidates[-1],
        ) as choose:
            selected = engine.random_meme()

        self.assertIs(selected, extension)
        choose.assert_called_once()
        self.assertEqual(choose.call_args.args[0], [builtin, extension])

    def test_every_runtime_option_accepts_a_typed_value(self) -> None:
        checked = 0
        for meme in self.engine.memes:
            specs = option_specs_from_params(self.engine.get_params(meme))
            parser = MemeArgumentParser(specs)
            for spec in specs:
                if spec.kind == "bool":
                    raw_value = "true"
                elif spec.choices:
                    raw_value = spec.choices[0]
                elif spec.default is not None:
                    raw_value = str(spec.default)
                elif spec.minimum is not None:
                    raw_value = str(spec.minimum)
                elif spec.maximum is not None and spec.maximum < 0:
                    raw_value = str(spec.maximum)
                else:
                    raw_value = "0" if spec.kind in {"int", "float"} else "value"
                parsed = parser.parse(shlex.quote(f"{spec.name}={raw_value}"))
                self.assertEqual(
                    parsed.errors,
                    [],
                    msg=f"{meme.key}.{spec.name}: {parsed.errors}",
                )
                self.assertIn(spec.name, parsed.options)
                checked += 1
        self.assertGreater(checked, 0)

    def test_exact_match_requires_trigger_boundary(self) -> None:
        self.assertIsNone(self.engine.match("奶茶店"))

    def test_extension_key_collision_keeps_existing_meme(self) -> None:
        params = SimpleNamespace(
            min_images=0,
            max_images=0,
            min_texts=0,
            max_texts=0,
            default_texts=[],
            options=[],
        )
        builtin = SimpleNamespace(
            key="same",
            info=SimpleNamespace(keywords=["内置"], tags=set(), params=params),
        )
        duplicate = SimpleNamespace(
            key="same",
            info=SimpleNamespace(keywords=["扩展冲突"], tags=set(), params=params),
        )
        added = SimpleNamespace(
            key="extension_only",
            info=SimpleNamespace(keywords=["扩展新增"], tags=set(), params=params),
        )
        engine = MemeEngine({})
        engine.module = SimpleNamespace(
            get_memes=lambda: [builtin],
            get_version=lambda: "test",
        )
        engine.set_extension_memes("test", [duplicate, added])

        engine.reload_memes()

        self.assertIs(engine.resolve("same"), builtin)
        self.assertIs(engine.resolve("扩展新增"), added)
        self.assertIsNone(engine.resolve("扩展冲突"))

    def test_incomplete_namespace_module_is_reimported(self) -> None:
        engine = MemeEngine({})
        stale = SimpleNamespace(__file__=None)
        engine.module = stale
        recovered = SimpleNamespace(get_memes=list, get_version=lambda: "0.2.3")
        with (
            patch.dict(sys.modules, {"meme_generator": stale}),
            patch(
                "astrbot_plugin_meme_forge.core.engine.importlib.import_module",
                return_value=recovered,
            ) as import_module,
        ):
            self.assertIs(engine._recover_module(), recovered)
        import_module.assert_called_once_with("meme_generator")

    def test_text_over_length_has_readable_error(self) -> None:
        class TextOverLength:
            text = "a" * 100

        with self.assertRaisesRegex(MemeGenerationError, r"文本过长：a{77}\.\.\."):
            MemeEngine._unwrap_result(TextOverLength(), "生成 test 时")


class ResourceCheckTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_kills_resource_subprocess(self) -> None:
        class FakeProcess:
            returncode = None

            def __init__(self) -> None:
                self.killed = False

            async def communicate(self):
                if self.killed:
                    return b"", b""
                await asyncio.sleep(60)
                return b"", b""

            def kill(self) -> None:
                self.killed = True

        process = FakeProcess()
        engine = MemeEngine({})
        with (
            patch(
                "astrbot_plugin_meme_forge.core.engine.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ),
            self.assertRaises(asyncio.TimeoutError),
        ):
            await engine.check_resources(0.001)
        self.assertTrue(process.killed)


if __name__ == "__main__":
    unittest.main()
