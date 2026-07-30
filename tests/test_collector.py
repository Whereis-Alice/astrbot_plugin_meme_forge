from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import AsyncMock

from astrbot.api import message_components as Comp

from astrbot_plugin_meme_forge.core.collector import ParamsCollector


class Params:
    min_images = 1
    max_images = 1
    min_texts = 1
    max_texts = 1
    default_texts: ClassVar[list[str]] = ["默认文字"]
    options: ClassVar[list[object]] = []


class FakeEvent:
    def __init__(self, messages: list[object], platform: str = "webchat"):
        self._messages = messages
        self._platform = platform

    def get_messages(self):
        return self._messages

    def get_sender_id(self):
        return "10001"

    def get_self_id(self):
        return "20002"

    def get_sender_name(self):
        return "发送者"

    def get_platform_name(self):
        return self._platform


class ParamsCollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_reply_image_and_text_precede_avatar_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reply_path = Path(directory) / "reply.png"
            reply_path.write_bytes(b"reply-image")
            reply = Comp.Reply(
                id="1",
                sender_id="30003",
                sender_nickname="被回复者",
                chain=[Comp.Image(str(reply_path)), Comp.Plain("引用文字")],
            )
            collector = ParamsCollector({})
            collector.get_avatar = AsyncMock(return_value=b"avatar")  # type: ignore[method-assign]
            try:
                inputs = await collector.collect(FakeEvent([reply]), Params(), "")
            finally:
                await collector.close()

        self.assertEqual(inputs.images, [("被回复者", b"reply-image")])
        self.assertEqual(inputs.texts, ["引用文字"])
        collector.get_avatar.assert_not_awaited()  # type: ignore[attr-defined]

    async def test_explicit_text_beats_reply_and_default(self) -> None:
        reply = Comp.Reply(id="1", chain=[Comp.Plain("引用文字")])
        collector = ParamsCollector({})
        collector.get_avatar = AsyncMock(return_value=None)  # type: ignore[method-assign]
        try:
            inputs = await collector.collect(FakeEvent([reply]), Params(), "显式文字")
        finally:
            await collector.close()
        self.assertEqual(inputs.texts, ["显式文字"])

    async def test_reply_message_string_is_used_when_chain_has_no_plain(self) -> None:
        class TextOnlyParams:
            min_images = 0
            max_images = 0
            min_texts = 1
            max_texts = 1
            default_texts: ClassVar[list[str]] = ["默认文字"]
            options: ClassVar[list[object]] = []

        reply = Comp.Reply(id="1", chain=[], message_str="引用文字")
        collector = ParamsCollector({})
        try:
            inputs = await collector.collect(FakeEvent([reply]), TextOnlyParams(), "")
        finally:
            await collector.close()
        self.assertEqual(inputs.texts, ["引用文字"])

    async def test_file_uri_image_is_supported(self) -> None:
        class ImageOnlyParams:
            min_images = 1
            max_images = 1
            min_texts = 0
            max_texts = 0
            default_texts: ClassVar[list[str]] = []
            options: ClassVar[list[object]] = []

        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "input.png"
            image_path.write_bytes(b"input-image")
            collector = ParamsCollector({})
            try:
                inputs = await collector.collect(
                    FakeEvent([Comp.Image(image_path.as_uri())]),
                    ImageOnlyParams(),
                    "",
                )
            finally:
                await collector.close()
        self.assertEqual(inputs.images, [("发送者", b"input-image")])

    async def test_message_at_and_text_at_do_not_duplicate_avatar(self) -> None:
        class TwoImageParams:
            min_images = 2
            max_images = 2
            min_texts = 0
            max_texts = 0
            default_texts: ClassVar[list[str]] = []
            options: ClassVar[list[object]] = []

        collector = ParamsCollector({})
        collector._get_user_info = AsyncMock(  # type: ignore[method-assign]
            return_value=("目标用户", "female")
        )
        collector.get_avatar = AsyncMock(  # type: ignore[method-assign]
            side_effect=[b"target-avatar", b"sender-avatar"]
        )
        try:
            inputs = await collector.collect(
                FakeEvent([Comp.At(qq="30003")], platform="aiocqhttp"),
                TwoImageParams(),
                "@30003",
            )
        finally:
            await collector.close()

        self.assertEqual(
            inputs.images,
            [
                ("目标用户", b"target-avatar"),
                ("发送者", b"sender-avatar"),
            ],
        )
        self.assertEqual(inputs.options, {})
        self.assertEqual(collector.get_avatar.await_count, 2)  # type: ignore[attr-defined]

    async def test_synthetic_name_labels_image_but_is_not_sent_to_engine(self) -> None:
        class ImageOnlyParams:
            min_images = 1
            max_images = 1
            min_texts = 0
            max_texts = 0
            default_texts: ClassVar[list[str]] = []
            options: ClassVar[list[object]] = []

        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "input.png"
            image_path.write_bytes(b"input-image")
            collector = ParamsCollector({})
            try:
                inputs = await collector.collect(
                    FakeEvent([Comp.Image(str(image_path))]),
                    ImageOnlyParams(),
                    "name=显式名称",
                )
            finally:
                await collector.close()
        self.assertEqual(inputs.images, [("显式名称", b"input-image")])
        self.assertEqual(inputs.options, {})


if __name__ == "__main__":
    unittest.main()
