from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from astrbot_plugin_meme_forge.core.grabber import MemeGrabber, MemeGrabError

GIF_BYTES = b"GIF89a" + b"\x00" * 32
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class Image:
    def __init__(self, data: bytes) -> None:
        self.data = data


class Reply:
    def __init__(self, chain: list[object], identifier: str = "reply-1") -> None:
        self.chain = chain
        self.id = identifier


class FakeCollector:
    async def read_image_component(self, component: Image) -> bytes:
        return component.data

    async def read_image_source(self, source: str) -> bytes:
        if source == "mface://one":
            return GIF_BYTES
        raise AssertionError(f"unexpected image source: {source}")


class FakeAction:
    async def call_action(self, action: str, **kwargs):
        if action == "get_msg":
            return {"message": [{"type": "mface", "data": {"url": "mface://one"}}]}
        raise AssertionError(f"unexpected action: {action} {kwargs}")


class FakeEvent:
    def __init__(
        self,
        messages: list[object],
        *,
        platform: str = "webchat",
        group_id: str = "",
        raw_message=None,
    ) -> None:
        self._messages = messages
        self._platform = platform
        self._group_id = group_id
        self.message_obj = SimpleNamespace(raw_message=raw_message)
        self.bot = SimpleNamespace(api=FakeAction())

    def get_messages(self):
        return self._messages

    def get_platform_name(self) -> str:
        return self._platform

    def get_group_id(self) -> str:
        return self._group_id


class MemeGrabberTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_send_mode_overrides_static_delivery_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            grabber = MemeGrabber(Path(directory), FakeCollector(), {"grabber_send_mode": "file"})
            png_files = await grabber.extract(FakeEvent([Image(PNG_BYTES)]))
            gif_files = await grabber.extract(FakeEvent([Image(GIF_BYTES)]))

            self.assertEqual(MemeGrabber.command_send_mode("图片"), "image")
            self.assertEqual(MemeGrabber.command_send_mode("IMAGE"), "image")
            self.assertEqual(MemeGrabber.command_send_mode("文件"), "file")
            self.assertIsNone(MemeGrabber.command_send_mode("压缩"))
            self.assertEqual(type(grabber.build_components(png_files)[0]).__name__, "File")
            self.assertEqual(
                type(grabber.build_components(png_files, send_mode="image")[0]).__name__,
                "Image",
            )
            self.assertEqual(
                type(grabber.build_components(gif_files, send_mode="image")[0]).__name__,
                "File",
            )

    async def test_extracts_reply_image_and_preserves_gif_as_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            grabber = MemeGrabber(Path(directory), FakeCollector(), {})
            files = await grabber.extract(FakeEvent([Reply([Image(GIF_BYTES)])]))
            components = grabber.build_components(files)

            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].path.read_bytes(), GIF_BYTES)
            self.assertEqual(files[0].path.suffix, ".gif")
            self.assertTrue(files[0].animated)
            self.assertEqual(type(components[0]).__name__, "File")

    async def test_uses_onebot_reply_fallback_for_official_emoji(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            grabber = MemeGrabber(Path(directory), FakeCollector(), {})
            files = await grabber.extract(
                FakeEvent([Reply([])], platform="aiocqhttp")
            )

            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].path.read_bytes(), GIF_BYTES)

    async def test_honors_group_whitelist_and_cleans_expired_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = {
                "grabber_list_mode": "whitelist",
                "grabber_group_list": "10001",
                "grabber_retention_minutes": 5,
            }
            grabber = MemeGrabber(Path(directory), FakeCollector(), config)
            with self.assertRaises(MemeGrabError):
                await grabber.extract(FakeEvent([Image(PNG_BYTES)], group_id="10002"))

            stale = Path(directory) / "meme_old.png"
            stale.write_bytes(PNG_BYTES)
            old_time = time.time() - 10 * 60
            os.utime(stale, (old_time, old_time))
            self.assertEqual(await grabber.cleanup_expired(), 1)
            self.assertFalse(stale.exists())


if __name__ == "__main__":
    unittest.main()
