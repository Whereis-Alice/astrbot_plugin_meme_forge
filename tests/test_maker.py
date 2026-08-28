from __future__ import annotations

import asyncio
import base64
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from astrbot_plugin_meme_forge.core.engine import MemeEngine, MemeInputs
from astrbot_plugin_meme_forge.core.imaging import ImageRenderError
from astrbot_plugin_meme_forge.core.maker import (
    MAX_TEMPLATES,
    ImageSlot,
    MakerError,
    MakerStore,
    TextSlot,
    caption_template_payload,
    decode_data_url,
    normalize_key,
    normalize_keywords,
    template_from_payload,
)


def png_bytes(color: str = "#38bdf8", size: tuple[int, int] = (120, 90)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


def gif_bytes(frames: int = 3) -> bytes:
    images = [
        Image.new("RGB", (64, 64), (index * 60 % 255, 90, 160)) for index in range(frames)
    ]
    output = io.BytesIO()
    images[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=images[1:],
        duration=120,
        loop=0,
    )
    return output.getvalue()


def sample_payload(key: str = "demo") -> dict:
    return {
        "key": key,
        "title": "示例模板",
        "keywords": ["示例", "demo"],
        "width": 320,
        "height": 320,
        "background": "#101418",
        "slots": [
            {
                "type": "image",
                "x": 20,
                "y": 20,
                "width": 280,
                "height": 200,
                "fit": "cover",
                "radius": 18,
            },
            {
                "type": "text",
                "x": 16,
                "y": 236,
                "width": 288,
                "height": 64,
                "color": "#ffffff",
                "stroke_color": "#000000",
                "stroke_width": 3,
                "bold": True,
            },
        ],
    }


class NormalizationTests(unittest.TestCase):
    def test_key_is_normalized_and_validated(self) -> None:
        self.assertEqual(normalize_key(" My-Template 1 "), "my_template_1")
        for bad in ("", "1abc", "a", "x" * 40, "!!!"):
            with self.subTest(bad=bad), self.assertRaises(MakerError):
                normalize_key(bad)

    def test_keywords_accept_text_and_lists(self) -> None:
        self.assertEqual(normalize_keywords("摸头，pat  pat"), ("摸头", "pat"))
        self.assertEqual(normalize_keywords(["a", "a", "b"]), ("a", "b"))
        with self.assertRaises(MakerError):
            normalize_keywords([])
        with self.assertRaises(MakerError):
            normalize_keywords(["x" * 20])
        with self.assertRaises(MakerError):
            normalize_keywords(list("abcdefghij"))

    def test_slot_values_are_clamped(self) -> None:
        slot = ImageSlot.from_payload(
            {
                "x": "12.6",
                "width": 99999,
                "fit": "NONSENSE",
                "opacity": 40,
                "rotate": "nan",
                "radius": -5,
            }
        )
        self.assertEqual(slot.x, 13)
        self.assertEqual(slot.width, 2048)
        self.assertEqual(slot.fit, "cover")
        self.assertEqual(slot.opacity, 1.0)
        self.assertEqual(slot.rotate, 0.0)
        self.assertEqual(slot.radius, 0)

        text = TextSlot.from_payload({"color": "red", "align": "RIGHT", "max_lines": 99})
        self.assertEqual(text.color, "#111111")
        self.assertEqual(text.align, "right")
        self.assertEqual(text.max_lines, 12)

    def test_canvas_area_is_limited(self) -> None:
        payload = sample_payload()
        payload["width"] = 2048
        payload["height"] = 2048
        with self.assertRaises(MakerError):
            template_from_payload(payload)

    def test_slot_count_limits(self) -> None:
        payload = sample_payload()
        payload["slots"] = [{"type": "image"} for _ in range(5)]
        with self.assertRaises(MakerError):
            template_from_payload(payload)
        payload["slots"] = []
        with self.assertRaises(MakerError):
            template_from_payload(payload)
        payload["slots"] = [{"type": "sticker"}]
        with self.assertRaises(MakerError):
            template_from_payload(payload)

    def test_data_url_decoding(self) -> None:
        raw = png_bytes()
        encoded = "data:image/png;base64," + base64.b64encode(raw).decode()
        self.assertEqual(decode_data_url(encoded), raw)
        with self.assertRaises(MakerError):
            decode_data_url("")
        with self.assertRaises(MakerError):
            decode_data_url("not*base64*")
        with self.assertRaises(MakerError):
            decode_data_url(base64.b64encode(raw).decode(), limit=16)


class MakerStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.store = MakerStore(Path(self.directory.name) / "maker")
        self.store.ensure_root()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_save_load_delete_round_trip(self) -> None:
        template = self.store.save(sample_payload(), base_data=png_bytes("#222831"))
        self.assertEqual(template.base, "base.png")
        self.assertEqual(self.store.keys(), ["demo"])

        loaded = self.store.load("demo")
        self.assertEqual(loaded.keywords, ("示例", "demo"))
        self.assertEqual(loaded.width, 320)
        self.assertEqual(len(loaded.image_slots), 1)
        self.assertEqual(len(loaded.text_slots), 1)
        self.assertIsNotNone(self.store.asset_path(loaded, loaded.base))

        self.store.save({"key": "demo", "title": "改名"})
        self.assertEqual(self.store.load("demo").title, "改名")
        self.assertEqual(len(self.store.load("demo").slots), 2)

        removed = self.store.save({"key": "demo"}, remove_base=True)
        self.assertIsNone(removed.base)
        self.assertIsNone(self.store.asset_path(removed, "base.png"))

        self.assertEqual(self.store.delete("demo"), "demo")
        self.assertEqual(self.store.keys(), [])
        with self.assertRaises(MakerError):
            self.store.delete("demo")

    def test_reserved_keys_block_new_templates(self) -> None:
        with self.assertRaises(MakerError):
            self.store.save(sample_payload("petpet"), reserved_keys={"petpet"})
        self.store.save(sample_payload("petpet2"), reserved_keys={"petpet"})
        self.store.save({"key": "petpet2", "title": "更新"}, reserved_keys={"petpet2"})

    def test_path_escape_is_rejected(self) -> None:
        for bad in ("../evil", "a/b", "..", "C:/tmp", "a\\b", ""):
            with self.subTest(bad=bad), self.assertRaises(MakerError):
                self.store.template_directory(bad)

    def test_template_directory_stays_under_root(self) -> None:
        directory = self.store.template_directory("Some-Template")
        self.assertEqual(directory.name, "some_template")
        self.assertEqual(directory.parent, self.store.root.resolve(strict=False))

    def test_unreadable_template_is_skipped(self) -> None:
        self.store.save(sample_payload("good"))
        broken = self.store.root / "broken"
        broken.mkdir()
        (broken / "template.json").write_text("{oops", encoding="utf-8")
        self.assertEqual([item.key for item in self.store.templates()], ["good"])

    def test_asset_must_be_a_supported_image(self) -> None:
        with self.assertRaises(MakerError):
            self.store.save(sample_payload(), base_data=b"definitely-not-an-image")

    def test_template_cap(self) -> None:
        for index in range(3):
            self.store.save(sample_payload(f"t{index}"))
        original = MAX_TEMPLATES
        try:
            import astrbot_plugin_meme_forge.core.maker as maker_module

            maker_module.MAX_TEMPLATES = 3
            with self.assertRaises(MakerError):
                self.store.save(sample_payload("t9"))
        finally:
            maker_module.MAX_TEMPLATES = original


class MakerRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.store = MakerStore(Path(self.directory.name) / "maker")
        self.store.ensure_root()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_static_render_returns_png(self) -> None:
        self.store.save(sample_payload())
        meme = self.store.build_memes()[0]
        self.assertEqual(meme.source, "maker")
        self.assertEqual(meme.info.params.min_images, 1)
        self.assertEqual(meme.info.params.max_texts, 1)
        output = meme.generate_from_inputs(
            SimpleNamespace(images=[("a.png", png_bytes())], texts=["你好世界"])
        )
        self.assertTrue(output.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_animated_input_produces_gif(self) -> None:
        self.store.save(sample_payload())
        meme = self.store.build_memes()[0]
        output = meme.generate_from_inputs(
            SimpleNamespace(images=[("a.gif", gif_bytes())], texts=["动图"])
        )
        self.assertTrue(output.startswith((b"GIF87a", b"GIF89a")))

    def test_preview_needs_no_user_input(self) -> None:
        self.store.save(sample_payload())
        meme = self.store.build_memes()[0]
        self.assertTrue(meme.generate_preview().startswith(b"\x89PNG"))

    def test_engine_can_drive_maker_memes(self) -> None:
        payload = sample_payload("forge_maker_probe")
        payload["keywords"] = ["自制探针模板"]
        self.store.save(payload)
        engine = MemeEngine({})
        engine.set_extension_memes("maker", self.store.build_memes())
        engine.reload_memes()
        matched = engine.match("自制探针模板")
        self.assertIsNotNone(matched)
        assert matched is not None
        self.assertEqual(matched.meme.key, "forge_maker_probe")
        self.assertEqual(matched.argument_text, "")
        meme = matched.meme
        self.assertEqual(engine.get_source(meme), "maker")
        output = asyncio.run(
            engine.generate(
                meme,
                MemeInputs(images=[("a.png", png_bytes())], texts=["文案"], options={}),
            )
        )
        self.assertTrue(output.startswith(b"\x89PNG"))

    def test_wrong_image_count_is_reported(self) -> None:
        self.store.save(sample_payload())
        meme = self.store.build_memes()[0]
        with self.assertRaises(ImageRenderError):
            meme.generate_from_inputs(SimpleNamespace(images=[], texts=[]))

    def test_text_only_template_needs_a_base_image(self) -> None:
        payload = sample_payload("textonly")
        payload["slots"] = [dict(payload["slots"][1])]
        with self.assertRaises(MakerError):
            self.store.save(payload)
        self.assertEqual(self.store.keys(), [])

        self.store.save(payload, base_data=png_bytes("#0f172a", (320, 320)))
        meme = self.store.build_memes()[0]
        self.assertEqual(meme.info.params.max_images, 0)
        self.assertTrue(
            meme.generate_from_inputs(
                SimpleNamespace(images=[], texts=["只有文字"])
            ).startswith(b"\x89PNG")
        )

    def test_defaults_fill_omitted_captions(self) -> None:
        payload = sample_payload("twotexts")
        payload["slots"] = [
            {"type": "text", "x": 0, "y": 0, "width": 320, "height": 80},
            {
                "type": "text",
                "x": 0,
                "y": 200,
                "width": 320,
                "height": 80,
                "default": "预设文案",
            },
        ]
        template = self.store.save(payload, base_data=png_bytes("#1f2933", (320, 320)))
        self.assertEqual(template.min_texts, 1)
        self.assertEqual(template.default_texts, ["预设文案"])
        meme = self.store.build_memes()[0]
        self.assertEqual(meme.info.params.min_texts, 1)
        self.assertEqual(meme.info.params.max_texts, 2)
        self.assertTrue(
            meme.generate_from_inputs(
                SimpleNamespace(images=[], texts=["首行"])
            ).startswith(b"\x89PNG")
        )

    def test_caption_template_payload_is_valid(self) -> None:
        payload = caption_template_payload(
            "caption", ["配字"], width=480, height=360, title="配字"
        )
        template = self.store.save(payload, base_data=png_bytes("#334155", (480, 360)))
        self.assertEqual(template.key, "caption")
        self.assertEqual(len(template.text_slots), 1)
        meme = self.store.build_memes()[0]
        self.assertTrue(
            meme.generate_from_inputs(
                SimpleNamespace(images=[], texts=["这是一段比较长的中文说明文字用来测试自动换行"])
            ).startswith(b"\x89PNG")
        )

    def test_long_latin_text_is_hard_wrapped(self) -> None:
        payload = caption_template_payload("wrap", ["wrap"], width=320, height=240)
        self.store.save(payload, base_data=png_bytes("#475569", (320, 240)))
        meme = self.store.build_memes()[0]
        self.assertTrue(
            meme.generate_from_inputs(
                SimpleNamespace(images=[], texts=["Supercalifragilisticexpialidocious" * 3])
            ).startswith(b"\x89PNG")
        )


if __name__ == "__main__":
    unittest.main()
