"""透明输出改用 GIF 投递，绕开 QQ 手机端不渲染 PNG alpha 的问题。"""

from __future__ import annotations

import asyncio
import io
import unittest
from types import SimpleNamespace
from unittest import mock

from PIL import Image

from astrbot_plugin_meme_forge.core.imaging import (
    has_transparency,
    to_delivery_bytes,
)
from astrbot_plugin_meme_forge.main import MemeForgePlugin

BODY_COLOUR = (12, 200, 90, 255)


def encode(image: Image.Image, image_format: str, **options: object) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=image_format, **options)
    return buffer.getvalue()


def transparent_png() -> bytes:
    image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    image.paste(BODY_COLOUR, (2, 2, 6, 6))
    return encode(image, "PNG")


def opaque_png() -> bytes:
    return encode(Image.new("RGB", (8, 8), (30, 60, 90)), "PNG")


def jpeg_bytes() -> bytes:
    return encode(Image.new("RGB", (8, 8), (30, 60, 90)), "JPEG")


def animated_png() -> bytes:
    first = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    first.paste(BODY_COLOUR, (0, 0, 4, 4))
    second = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    second.paste(BODY_COLOUR, (4, 4, 8, 8))
    return encode(
        first,
        "PNG",
        save_all=True,
        append_images=[second],
        duration=[120, 200],
        loop=0,
    )


class DeliveryConversionTests(unittest.TestCase):
    """只有真的带透明像素的图才会被重新编码。"""

    def test_transparent_still_becomes_a_transparent_gif(self) -> None:
        source = transparent_png()
        converted = to_delivery_bytes(source)
        self.assertNotEqual(converted, source)
        with Image.open(io.BytesIO(converted)) as image:
            self.assertEqual(image.format, "GIF")
            self.assertIn("transparency", image.info)
            rgba = image.convert("RGBA")
        self.assertEqual(rgba.getpixel((0, 0))[3], 0)
        self.assertEqual(rgba.getpixel((3, 3)), BODY_COLOUR)

    def test_conversion_is_idempotent(self) -> None:
        converted = to_delivery_bytes(transparent_png())
        self.assertIs(to_delivery_bytes(converted), converted)

    def test_images_that_display_fine_are_returned_untouched(self) -> None:
        cases = (
            ("opaque_png", opaque_png()),
            ("jpeg", jpeg_bytes()),
            ("gif", to_delivery_bytes(transparent_png())),
            ("garbage", b"not an image"),
            ("empty", b""),
        )
        for name, payload in cases:
            with self.subTest(name=name):
                self.assertIs(to_delivery_bytes(payload), payload)

    def test_animation_keeps_every_frame_and_its_timing(self) -> None:
        converted = to_delivery_bytes(animated_png())
        durations: list[object] = []
        with Image.open(io.BytesIO(converted)) as image:
            self.assertEqual(image.format, "GIF")
            self.assertEqual(getattr(image, "n_frames", 1), 2)
            for index in range(2):
                image.seek(index)
                durations.append(image.info.get("duration"))
        self.assertEqual(durations, [120, 200])

    def test_transparency_probe_ignores_fully_opaque_alpha(self) -> None:
        opaque_rgba = encode(Image.new("RGBA", (4, 4), (1, 2, 3, 255)), "PNG")
        self.assertTrue(has_transparency(transparent_png()))
        self.assertFalse(has_transparency(opaque_rgba))
        self.assertFalse(has_transparency(jpeg_bytes()))


class PluginDeliveryTests(unittest.IsolatedAsyncioTestCase):
    """转换发生在记住输出之前，收藏指纹才能对上真正发出去的图。"""

    def setUp(self) -> None:
        self.plugin = MemeForgePlugin.__new__(MemeForgePlugin)
        self.plugin.config = {}

    async def test_helper_converts_by_default(self) -> None:
        converted = await self.plugin._delivery_bytes(transparent_png())
        with Image.open(io.BytesIO(converted)) as image:
            self.assertEqual(image.format, "GIF")

    async def test_helper_can_be_switched_off(self) -> None:
        source = transparent_png()
        self.plugin.config = {"transparent_output_as_gif": False}
        self.assertIs(await self.plugin._delivery_bytes(source), source)

    async def test_a_broken_conversion_still_sends_the_original(self) -> None:
        source = transparent_png()
        with mock.patch(
            "astrbot_plugin_meme_forge.main.to_delivery_bytes",
            side_effect=RuntimeError("boom"),
        ):
            self.assertIs(await self.plugin._delivery_bytes(source), source)

    async def test_generated_meme_is_converted_before_it_is_returned(self) -> None:
        source = transparent_png()
        inputs = SimpleNamespace(options={"hand": "left"})

        async def collect(event, params, argument_text):
            return inputs

        async def generate(meme, payload):
            return source

        self.plugin.config = {"compress_output": False}
        self.plugin.engine = SimpleNamespace(
            get_params=lambda meme: SimpleNamespace(),
            generate=generate,
        )
        self.plugin.collector = SimpleNamespace(collect=collect)
        self.plugin._generation_slots = asyncio.Semaphore(1)
        image, options = await self.plugin._generate_meme(
            None,
            SimpleNamespace(key="milk_tea"),
            "左手",
        )
        self.assertEqual(options, inputs.options)
        with Image.open(io.BytesIO(image)) as decoded:
            self.assertEqual(decoded.format, "GIF")

    async def test_pjsk_remembers_exactly_what_it_sends(self) -> None:
        source = transparent_png()
        remembered: list[bytes] = []

        async def render(sticker, text, options):
            return source

        async def remember(event, record, image, trigger, track_usage=False):
            remembered.append(image)

        self.plugin._render_pjsk = render
        self.plugin._remember_meme = lambda *args, **kwargs: None
        self.plugin._remember_generated_output = remember
        image, error = await self.plugin._pjsk_emit(
            None,
            SimpleNamespace(index=1, name="miku_01"),
            "哟",
            {},
        )
        self.assertIsNone(error)
        self.assertIsNotNone(image)
        with Image.open(io.BytesIO(image)) as decoded:
            self.assertEqual(decoded.format, "GIF")
        self.assertEqual(remembered, [image])


if __name__ == "__main__":  # pragma: no cover - manual runs only
    unittest.main()
