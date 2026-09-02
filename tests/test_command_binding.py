from __future__ import annotations

import ast
import inspect
import re
import types
import typing
import unittest
from pathlib import Path
from typing import Any

from astrbot_plugin_meme_forge.core.arguments import command_tail, command_tokens
from astrbot_plugin_meme_forge.main import MemeForgePlugin

MAIN_PATH = Path(__file__).resolve().parents[1] / "main.py"
MAIN_TREE = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))


def command_decorators(node: ast.AST) -> list[ast.Call]:
    """Return the @filter.command / @filter.command_group calls on one function."""
    found: list[ast.Call] = []
    for decorator in getattr(node, "decorator_list", []):
        if not isinstance(decorator, ast.Call):
            continue
        target = decorator.func
        if not isinstance(target, ast.Attribute):
            continue
        if target.attr not in {"command", "command_group"}:
            continue
        if not (isinstance(target.value, ast.Name) and target.value.id == "filter"):
            continue
        found.append(decorator)
    return found


def command_handlers() -> list[tuple[str, ast.AST, list[ast.Call]]]:
    """Every command handler declared in main.py, straight from the source tree."""
    handlers: list[tuple[str, ast.AST, list[ast.Call]]] = []
    for node in ast.walk(MAIN_TREE):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        decorators = command_decorators(node)
        if decorators:
            handlers.append((node.name, node, decorators))
    return handlers


def command_names(handler_name: str) -> list[str]:
    """Collect the command name plus every alias registered for one handler."""
    names: list[str] = []
    for name, _node, decorators in command_handlers():
        if name != handler_name:
            continue
        for decorator in decorators:
            for argument in decorator.args:
                if isinstance(argument, ast.Constant) and isinstance(
                    argument.value, str
                ):
                    names.append(argument.value)
            for keyword in decorator.keywords:
                if keyword.arg != "alias":
                    continue
                if isinstance(keyword.value, ast.Set | ast.List | ast.Tuple):
                    for element in keyword.value.elts:
                        if isinstance(element, ast.Constant) and isinstance(
                            element.value, str
                        ):
                            names.append(element.value)
    return list(dict.fromkeys(names))


class CoreCommandBinding:
    """Replay how AstrBot binds command arguments, so the tests can prove it.

    ``astrbot/core/star/filter/command.py`` registers every parameter after
    ``self`` / ``event`` as a *named* one (including ``*args``), and
    ``astrbot/core/pipeline/process_stage/method/star_request.py`` then calls
    ``call_handler(event, handler, **params)`` -- keywords only. 4.27.x reads the
    signature with ``eval_str=True`` while 4.26.x does not, which matters because
    main.py uses ``from __future__ import annotations``; both are covered here.
    """

    def __init__(self, handler: Any, names: list[str], *, eval_str: bool) -> None:
        signature = (
            inspect.signature(handler, eval_str=True)
            if eval_str
            else inspect.signature(handler)
        )
        self.handler = handler
        self.names = names
        self.handler_params: dict[str, Any] = {}
        for index, (key, value) in enumerate(signature.parameters.items()):
            if index < 2:
                continue
            if value.default is inspect.Parameter.empty:
                self.handler_params[key] = value.annotation
            else:
                self.handler_params[key] = value.default

    def tokens(self, message_str: str) -> list[str]:
        """The token list the core hands to ``validate_and_convert_params``."""
        text = re.sub(r"\s+", " ", message_str.strip())
        matched = False
        for name in self.names:
            if text.startswith(f"{name} ") or text == name:
                matched = True
                text = text[len(name) :].strip()
        if not matched:
            raise AssertionError(f"没有指令名匹配 {message_str!r}")
        return [token for token in text.split(" ") if token]

    def bind(self, message_str: str) -> dict[str, Any]:
        """The keyword arguments the core would pass to the handler."""
        result: dict[str, Any] = {}
        params = self.tokens(message_str)
        for index, (key, expected) in enumerate(self.handler_params.items()):
            if index >= len(params):
                if (
                    isinstance(expected, type | types.UnionType)
                    or typing.get_origin(expected) is typing.Union
                    or expected is inspect.Parameter.empty
                ):
                    raise ValueError("必要参数缺失")
                result[key] = expected
                continue
            if expected is None:
                result[key] = (
                    int(params[index]) if params[index].isdigit() else params[index]
                )
            else:
                result[key] = params[index]
        return result

    def call_args(self, message_str: str) -> dict[str, Any]:
        """Bind against the real signature, raising exactly like the core would."""
        params = self.bind(message_str)
        inspect.signature(self.handler).bind(object(), object(), **params)
        return params


async def legacy_sticker_command(
    self: Any,
    event: Any,
    selector: str | None = None,
    *args: str,
):
    """The signature that crashed: kept only so the tests can prove why."""


async def legacy_random_command(self: Any, event: Any, *args: str):
    """Same story for /sk随机."""


class CommandTailTests(unittest.TestCase):
    """command_tail / command_tokens recover what the core used to inject."""

    def test_the_command_name_is_dropped_and_whitespace_is_normalised(self) -> None:
        self.assertEqual(command_tail("sk 122 哟"), "122 哟")
        self.assertEqual(command_tail("  sk\t122   哟 "), "122 哟")
        self.assertEqual(command_tail("SK 122 哟"), "122 哟")

    def test_a_bare_command_has_no_arguments(self) -> None:
        for message in ("sk", "sk随机", "  sk  ", ""):
            with self.subTest(message=message):
                self.assertEqual(command_tail(message), "")
                self.assertEqual(command_tokens(message), ())
        self.assertEqual(command_tail(None), "")

    def test_a_leftover_wake_prefix_is_still_one_token(self) -> None:
        self.assertEqual(command_tail("/sk 122 哟"), "122 哟")
        self.assertEqual(command_tokens("/sk随机 你好"), ("你好",))

    def test_tokens_keep_order_and_drop_empties(self) -> None:
        self.assertEqual(command_tokens("sk 122 哟"), ("122", "哟"))
        self.assertEqual(
            command_tokens("meme工坊自制新建 mykey 触发词1 触发词2"),
            ("mykey", "触发词1", "触发词2"),
        )


class CommandSignatureInvariantTests(unittest.TestCase):
    """Every command handler must take only (self, event).

    AstrBot passes command arguments by keyword, so any extra parameter -- and
    especially ``*args`` -- is a latent TypeError. This test reads main.py itself,
    so a newly added handler cannot quietly bring the crash back.
    """

    def test_no_handler_declares_extra_parameters(self) -> None:
        handlers = command_handlers()
        self.assertGreaterEqual(len(handlers), 25)
        for name, node, _decorators in handlers:
            with self.subTest(handler=name):
                args = node.args
                self.assertEqual([item.arg for item in args.args], ["self", "event"])
                self.assertEqual(args.posonlyargs, [])
                self.assertEqual(args.kwonlyargs, [])
                self.assertEqual(args.defaults, [])
                self.assertIsNone(args.vararg)
                self.assertIsNone(args.kwarg)

    def test_command_names_stay_single_tokens(self) -> None:
        """command_tail drops one token, so a name may never contain a space."""
        for name, _node, _decorators in command_handlers():
            for registered in command_names(name):
                with self.subTest(handler=name, command=registered):
                    self.assertNotIn(" ", registered)
                    self.assertTrue(registered.strip())


class CoreBindingTests(unittest.TestCase):
    """The real handlers accept nothing, so no core version can mis-bind them."""

    SAMPLES = (
        ("pjsk_sticker_command", "sk 122 哟"),
        ("pjsk_sticker_command", "sk 122 哟 -s 40 -c"),
        ("pjsk_sticker_command", "SK 未来3 早上好"),
        ("pjsk_sticker_command", "sk"),
        ("pjsk_random_command", "sk随机 你好"),
        ("pjsk_random_command", "sk随机"),
        ("pjsk_sheet_command", "sk表情 全部"),
        ("pjsk_character_command", "sk角色 16"),
        ("install_pjsk_assets", "sk素材安装 确认"),
        ("maker_create", "meme工坊自制新建 mykey 触发词1 触发词2"),
        ("maker_delete", "meme工坊自制删除 mykey"),
        ("extract_meme", "meme提取 文件"),
        ("meme_details", "meme工坊详情 666"),
        ("disable_meme", "meme工坊禁用 奶茶"),
        ("enable_meme", "meme工坊启用 奶茶"),
        ("unfavorite_meme", "meme取消收藏 sk 206"),
        ("install_extension", "meme工坊扩展安装 确认"),
        ("install_gouqi_extension", "meme工坊Gouqi扩展安装 确认"),
    )

    def test_every_handler_binds_cleanly_on_both_core_versions(self) -> None:
        for handler_name, message in self.SAMPLES:
            handler = getattr(MemeForgePlugin, handler_name)
            names = command_names(handler_name)
            for eval_str in (True, False):
                with self.subTest(handler=handler_name, message=message, eval=eval_str):
                    binding = CoreCommandBinding(handler, names, eval_str=eval_str)
                    self.assertEqual(binding.handler_params, {})
                    self.assertEqual(binding.call_args(message), {})

    def test_the_plugin_reparses_exactly_what_the_core_would_have_split(self) -> None:
        for handler_name, message in self.SAMPLES:
            handler = getattr(MemeForgePlugin, handler_name)
            binding = CoreCommandBinding(
                handler, command_names(handler_name), eval_str=True
            )
            with self.subTest(handler=handler_name, message=message):
                self.assertEqual(command_tokens(message), tuple(binding.tokens(message)))

    def test_the_old_signature_really_did_crash(self) -> None:
        """Documents the reported bug: /sk 122 哟 -> unexpected keyword args."""
        names = command_names("pjsk_sticker_command")
        for eval_str in (True, False):
            with self.subTest(eval=eval_str):
                legacy = CoreCommandBinding(
                    legacy_sticker_command, names, eval_str=eval_str
                )
                self.assertEqual(sorted(legacy.handler_params), ["args", "selector"])
                params = legacy.bind("sk 122 哟")
                self.assertEqual(params["selector"], 122)
                self.assertEqual(params["args"], "哟")
                with self.assertRaises(TypeError):
                    inspect.signature(legacy_sticker_command).bind(
                        object(), object(), **params
                    )

    def test_the_old_signature_also_broke_the_bare_command(self) -> None:
        """Without arguments 4.27.x raised 必要参数缺失; 4.26.x injected "str"."""
        names = command_names("pjsk_random_command")
        modern = CoreCommandBinding(legacy_random_command, names, eval_str=True)
        with self.assertRaises(ValueError):
            modern.bind("sk随机")
        legacy = CoreCommandBinding(legacy_random_command, names, eval_str=False)
        self.assertEqual(legacy.bind("sk随机"), {"args": "str"})


class FakeEvent:
    """Only the surface the command handlers actually touch."""

    def __init__(self, message_str: str) -> None:
        self.message_str = message_str
        self.stopped = False

    def stop_event(self) -> None:
        self.stopped = True

    def plain_result(self, text: str) -> dict[str, Any]:
        return {"plain": text}

    def chain_result(self, chain: list[Any]) -> dict[str, Any]:
        return {"chain": chain}


class PjskCommandArgumentTests(unittest.IsolatedAsyncioTestCase):
    """End to end: the序号 and the caption must reach the renderer."""

    def setUp(self) -> None:
        self.plugin = MemeForgePlugin.__new__(MemeForgePlugin)
        self.emitted: list[tuple[Any, str, dict[str, Any]]] = []

        async def no_block() -> None:
            return None

        async def fake_emit(
            event: Any,
            sticker: Any,
            text: str,
            options: dict[str, Any],
        ) -> tuple[bytes, None]:
            self.emitted.append((sticker, text, options))
            return b"png-bytes", None

        self.plugin._pjsk_block_reason = no_block
        self.plugin._pjsk_emit = fake_emit

    @staticmethod
    async def drain(generator: Any) -> list[Any]:
        return [item async for item in generator]

    async def test_sk_passes_the_index_and_the_caption(self) -> None:
        event = FakeEvent("sk 122 哟")
        results = await self.drain(self.plugin.pjsk_sticker_command(event))
        self.assertTrue(event.stopped)
        self.assertEqual(len(self.emitted), 1)
        sticker, text, options = self.emitted[0]
        self.assertEqual(sticker.index, 122)
        self.assertEqual(text, "哟")
        self.assertIsNone(options.get("font_size"))
        self.assertIn("chain", results[0])

    async def test_sk_keeps_multi_word_captions_and_render_options(self) -> None:
        event = FakeEvent("sk 122 早上 好 -s 40")
        await self.drain(self.plugin.pjsk_sticker_command(event))
        _sticker, text, options = self.emitted[0]
        self.assertEqual(text, "早上 好")
        self.assertEqual(options.get("font_size"), 40)

    async def test_sk_random_passes_its_caption(self) -> None:
        event = FakeEvent("sk随机 你好")
        results = await self.drain(self.plugin.pjsk_random_command(event))
        self.assertEqual(len(self.emitted), 1)
        self.assertEqual(self.emitted[0][1], "你好")
        self.assertIn("chain", results[0])

    async def test_bare_sk_shows_the_usage_instead_of_an_error(self) -> None:
        event = FakeEvent("sk")
        results = await self.drain(self.plugin.pjsk_sticker_command(event))
        self.assertEqual(self.emitted, [])
        self.assertIn("plain", results[0])
        self.assertIn("/sk", results[0]["plain"])

    async def test_sk_random_subcommand_still_reaches_the_random_path(self) -> None:
        event = FakeEvent("sk 随机 你好")
        await self.drain(self.plugin.pjsk_sticker_command(event))
        self.assertEqual(len(self.emitted), 1)
        self.assertEqual(self.emitted[0][1], "你好")


if __name__ == "__main__":
    unittest.main()
