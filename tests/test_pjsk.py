"""Tests for the PJSK catalogue, argument parser, assets and workbench."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from astrbot_plugin_meme_forge.core import pjsk, pjsk_catalog
from astrbot_plugin_meme_forge.core.dashboard import DashboardError, MemeDashboard
from astrbot_plugin_meme_forge.core.imaging import ImageRenderError
from astrbot_plugin_meme_forge.core.pjsk_assets import PjskAssetError, PjskAssetManager
from astrbot_plugin_meme_forge.core.pjsk_command import (
    PjskCommandError,
    coerce_options,
    parse_arguments,
    resolve_target,
    usage_lines,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"x" * 32


def blank_artwork() -> bytes:
    """A canvas-sized transparent PNG standing in for real artwork."""
    canvas = Image.new(
        "RGBA",
        (pjsk_catalog.CANVAS_WIDTH, pjsk_catalog.CANVAS_HEIGHT),
        (12, 18, 32, 255),
    )
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


class PjskCatalogTests(unittest.TestCase):
    def test_catalogue_indexes_every_reviewed_image_once(self) -> None:
        stickers = pjsk_catalog.stickers()
        self.assertEqual(len(stickers), pjsk_catalog.IMAGE_COUNT)
        self.assertEqual(len(pjsk_catalog.characters()), 26)
        self.assertEqual(len(pjsk_catalog.expected_images()), pjsk_catalog.IMAGE_COUNT)
        self.assertEqual(
            [item.index for item in stickers],
            list(range(1, pjsk_catalog.IMAGE_COUNT + 1)),
        )
        self.assertEqual(
            len({item.image for item in stickers}), pjsk_catalog.IMAGE_COUNT
        )

    def test_character_ranges_are_contiguous(self) -> None:
        cursor = 1
        for character in pjsk_catalog.characters():
            self.assertEqual(character.first_index, cursor)
            self.assertEqual(character.count, len(character.numbers))
            cursor = character.last_index + 1
        self.assertEqual(cursor - 1, pjsk_catalog.IMAGE_COUNT)

    def test_selector_accepts_index_alias_and_character_number(self) -> None:
        self.assertEqual(pjsk_catalog.sticker_by_index(137).index, 137)
        for token in ("206", "miku3", "未来3", "MIKU 3", "#206"):
            selection = pjsk_catalog.parse_selector(token)
            self.assertIsNotNone(selection, token)
            self.assertEqual(selection.sticker.index, 206, token)
            self.assertTrue(selection.is_exact, token)
        loose = pjsk_catalog.parse_selector("未来")
        self.assertEqual(loose.character.key, "miku")
        self.assertIsNone(loose.sticker)
        self.assertFalse(loose.is_exact)
        self.assertEqual(pjsk_catalog.parse_selector("rui16").sticker.index, 286)

    def test_selector_rejects_out_of_range_and_unknown_tokens(self) -> None:
        for token in ("360", "0", "-3", "nope", "", "未来99"):
            self.assertIsNone(pjsk_catalog.parse_selector(token), token)
        self.assertIsNone(pjsk_catalog.sticker_by_index(0))
        self.assertIsNone(pjsk_catalog.sticker_by_index(pjsk_catalog.IMAGE_COUNT + 1))

    def test_labels_stay_human_readable(self) -> None:
        sticker = pjsk_catalog.sticker_by_index(206)
        self.assertEqual(sticker.label, "206. 初音未来 03")
        self.assertEqual(sticker.name, "Miku 03")
        self.assertEqual(sticker.image, "Miku/Miku_03.png")
        self.assertEqual(len(pjsk_catalog.character_stickers(sticker.character)), 13)


class PjskArgumentTests(unittest.TestCase):
    def test_dash_options_are_split_from_caption_words(self) -> None:
        parsed = parse_arguments(
            ["206", "hello", "world", "-s", "40", "--旋转", "-2.5", "-c"]
        )
        self.assertEqual(parsed.words, ("206", "hello", "world"))
        self.assertEqual(parsed.font_size, 40.0)
        self.assertEqual(parsed.rotate, -2.5)
        self.assertTrue(parsed.curve)
        self.assertIsNone(parsed.scale)

    def test_inline_values_and_fullwidth_digits_are_accepted(self) -> None:
        parsed = parse_arguments(["--size=40", "--scale", "３"])
        self.assertEqual(parsed.font_size, 40.0)
        self.assertEqual(parsed.scale, 3)

    def test_invalid_options_report_a_readable_reason(self) -> None:
        for case in (["-s"], ["-s", "abc"], ["-s", "999"], ["-c=1"]):
            with self.assertRaises(PjskCommandError):
                parse_arguments(case)

    def test_target_resolution_supports_two_step_selection(self) -> None:
        target = resolve_target(["206", "hello", "world"])
        self.assertEqual(target.sticker.index, 206)
        self.assertEqual(target.text, "hello world")
        split = resolve_target(["未来", "3", "早上好"])
        self.assertEqual(split.sticker.index, 206)
        self.assertEqual(split.text, "早上好")
        loose = resolve_target(["未来", "早上好"])
        self.assertIsNone(loose.sticker)
        self.assertEqual(loose.text, "早上好")
        empty = resolve_target([])
        self.assertIsNone(empty.character)
        self.assertEqual(empty.text, "")
        with self.assertRaises(PjskCommandError):
            resolve_target(["nope"])

    def test_webui_options_reuse_the_chat_bounds(self) -> None:
        options = coerce_options(
            {"x": "10", "y": 20, "rotate": "", "font_size": None, "scale": 3, "curve": 1}
        )
        self.assertEqual((options.x, options.y), (10.0, 20.0))
        self.assertIsNone(options.rotate)
        self.assertIsNone(options.font_size)
        self.assertEqual(options.scale, 3)
        self.assertTrue(options.curve)
        with self.assertRaises(PjskCommandError):
            coerce_options({"x": "abc"})
        with self.assertRaises(PjskCommandError):
            coerce_options({"scale": 9})

    def test_help_block_points_at_both_steps(self) -> None:
        text = "\n".join(usage_lines())
        self.assertIn("/pjsk表情", text)
        self.assertIn("/pjsk 206", text)


class PjskRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.sticker = pjsk_catalog.sticker_by_index(206)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_text_is_normalised_and_capped(self) -> None:
        self.assertEqual(pjsk.normalise_text(r"a\nb"), "a\nb")
        self.assertEqual(pjsk.normalise_text("  \n  "), "")
        long_text = pjsk.normalise_text("字" * 400)
        self.assertEqual(len(long_text), pjsk.MAX_TEXT_LENGTH)
        many_lines = pjsk.normalise_text("\n".join(["行"] * 20))
        self.assertEqual(len(many_lines.splitlines()), pjsk.MAX_TEXT_LINES)

    def test_layout_clamps_overrides_into_the_canvas(self) -> None:
        try:
            layout = pjsk.resolve_layout(
                self.sticker,
                "hello",
                x=9999,
                y=-500,
                rotate=99,
                font_size=9999,
                line_spacing=99,
            )
        except ImageRenderError as exc:
            self.skipTest(f"没有可用的 CJK 字体：{exc}")
        self.assertTrue(0 <= layout.x <= pjsk_catalog.CANVAS_WIDTH)
        self.assertTrue(0 <= layout.y <= pjsk_catalog.CANVAS_HEIGHT)
        self.assertEqual(layout.rotate, 10.0)
        self.assertEqual(layout.line_spacing, pjsk.MAX_LINE_SPACING)
        self.assertTrue(pjsk.MIN_FONT_SIZE <= layout.font_size <= pjsk.MAX_FONT_SIZE)

    def test_empty_text_falls_back_to_the_upstream_caption(self) -> None:
        try:
            layout = pjsk.resolve_layout(self.sticker, "   ")
        except ImageRenderError as exc:
            self.skipTest(f"没有可用的 CJK 字体：{exc}")
        self.assertEqual(" ".join(layout.lines), self.sticker.default_text)

    def test_render_produces_a_scaled_png(self) -> None:
        image_path = self.root / "Miku_03.png"
        image_path.write_bytes(blank_artwork())
        try:
            data = pjsk.render_sticker(
                self.sticker,
                "早上好",
                image_path=image_path,
                scale=2,
            )
        except ImageRenderError as exc:
            self.skipTest(f"没有可用的 CJK 字体：{exc}")
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(io.BytesIO(data)) as rendered:
            self.assertEqual(
                rendered.size,
                (pjsk_catalog.CANVAS_WIDTH * 2, pjsk_catalog.CANVAS_HEIGHT * 2),
            )

    def test_sticker_path_follows_the_catalogue_layout(self) -> None:
        path = pjsk.sticker_path(self.root, self.sticker)
        self.assertEqual(path.parent.name, "Miku")
        self.assertEqual(path.name, "Miku_03.png")


class PjskAssetManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.manager = PjskAssetManager(Path(self.directory.name), {})

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_image_path_only_resolves_catalogue_members(self) -> None:
        resolved = self.manager.image_path("Miku/Miku_03.png")
        self.assertEqual(resolved.parent, self.manager.images_root / "Miku")
        for bad in ("nope.png", "../secret.png", "Miku/Miku_99.png"):
            with self.assertRaises(PjskAssetError):
                self.manager.image_path(bad)

    def test_status_reports_a_missing_install(self) -> None:
        status = self.manager.status()
        self.assertFalse(status.installed)
        self.assertFalse(status.ready)
        self.assertEqual(status.images, 0)
        self.assertEqual(status.expected_images, pjsk_catalog.IMAGE_COUNT)
        self.assertFalse(status.font_installed)


def asset_stub(root: Path, **overrides: object) -> SimpleNamespace:
    """Stand in for PjskAssetManager without touching the network."""
    state = {
        "installed": True,
        "ready": True,
        "verified": True,
        "images": pjsk_catalog.IMAGE_COUNT,
        "image_bytes": pjsk_catalog.IMAGE_BYTES,
        "font_installed": True,
        "installed_at": "2026-01-01T00:00:00+00:00",
        "commit": pjsk_catalog.SOURCE_COMMIT,
        "font_commit": PjskAssetManager.FONT_COMMIT,
    }
    state.update(overrides)
    images_root = root / "img"
    return SimpleNamespace(
        images_root=images_root,
        font_path=root / PjskAssetManager.FONT_NAME,
        image_path=lambda relative: images_root.joinpath(*relative.split("/")),
        status=lambda: SimpleNamespace(**state),
        STICKER_REPOSITORY=PjskAssetManager.STICKER_REPOSITORY,
        STICKER_LICENSE=PjskAssetManager.STICKER_LICENSE,
        FONT_REPOSITORY=PjskAssetManager.FONT_REPOSITORY,
        FONT_LICENSE=PjskAssetManager.FONT_LICENSE,
        FONT_BYTES=PjskAssetManager.FONT_BYTES,
    )


class PjskDashboardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.assets = asset_stub(self.root)
        self.dashboard = self.build(self.assets)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def build(self, assets: object, **config: object) -> MemeDashboard:
        settings = {"dashboard_preview_max_mb": 4, "pjsk_output_scale": 2}
        settings.update(config)
        return MemeDashboard(
            SimpleNamespace(memes=[], version="test"),
            SimpleNamespace(meme_home=self.root / "meme-home"),
            settings,
            pjsk_assets=assets,
        )

    def write_artwork(self, relative: str) -> Path:
        path = self.assets.image_path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blank_artwork())
        return path

    def test_workbench_is_gated_by_config_and_availability(self) -> None:
        self.assertTrue(self.dashboard.pjsk_enabled)
        without_assets = self.build(None)
        self.assertFalse(without_assets.pjsk_enabled)
        with self.assertRaises(DashboardError):
            without_assets.pjsk_catalog()
        disabled = self.build(self.assets, pjsk_enabled=False)
        self.assertFalse(disabled.pjsk_enabled)
        with self.assertRaises(DashboardError):
            disabled.pjsk_catalog()

    def test_overview_block_never_needs_the_artwork(self) -> None:
        block = self.build(None).pjsk_overview()
        self.assertFalse(block["enabled"])
        self.assertFalse(block["ready"])
        self.assertEqual(block["stickers"], pjsk_catalog.IMAGE_COUNT)
        self.assertEqual(block["characters"], 26)
        ready = self.dashboard.pjsk_overview(self.assets.status())
        self.assertTrue(ready["ready"])
        self.assertEqual(ready["images"], pjsk_catalog.IMAGE_COUNT)

    def test_catalog_payload_drives_the_picker(self) -> None:
        payload = self.dashboard.pjsk_catalog()
        self.assertEqual(payload["total"], pjsk_catalog.IMAGE_COUNT)
        self.assertEqual(len(payload["characters"]), 26)
        self.assertEqual(payload["output_scale"], 2)
        first = payload["characters"][0]
        self.assertEqual(first["first_index"], 1)
        self.assertIn("range_label", first)
        sticker = payload["items"][205]
        self.assertEqual(sticker["index"], 206)
        self.assertEqual(sticker["character"], "miku")
        limits = payload["limits"]
        self.assertEqual(limits["canvas"]["width"], pjsk_catalog.CANVAS_WIDTH)
        self.assertEqual(limits["scale"], [1, pjsk.MAX_OUTPUT_SCALE])

    async def test_status_reports_provenance(self) -> None:
        payload = await self.dashboard.pjsk_status()
        status = payload["status"]
        self.assertTrue(status["ready"])
        self.assertEqual(status["expected_images"], pjsk_catalog.IMAGE_COUNT)
        self.assertEqual(status["sticker_license"], "MIT")
        self.assertEqual(status["font_license"], "MIT")
        self.assertEqual(status["install_command"], "/pjsk素材安装 确认")
        self.assertEqual(payload["output_scale"], 2)

    async def test_sticker_endpoint_returns_a_data_url(self) -> None:
        self.write_artwork("Miku/Miku_03.png")
        payload = await self.dashboard.pjsk_sticker("miku3")
        self.assertEqual(payload["index"], 206)
        self.assertEqual(payload["media_type"], "image/png")
        self.assertTrue(payload["data_url"].startswith("data:image/png;base64,"))

    async def test_sticker_endpoint_rejects_bad_selectors(self) -> None:
        for token in ("", None, "未来", "999"):
            with self.assertRaises(DashboardError):
                await self.dashboard.pjsk_sticker(token)

    async def test_missing_artwork_points_at_the_install_command(self) -> None:
        with self.assertRaises(DashboardError) as caught:
            await self.dashboard.pjsk_render({"index": 206, "text": "hello"})
        self.assertIn("pjsk素材安装", str(caught.exception))

    async def test_render_reports_the_effective_layout(self) -> None:
        self.write_artwork("Miku/Miku_03.png")
        try:
            payload = await self.dashboard.pjsk_render(
                {"index": "206", "text": "早上好", "font_size": 40, "curve": True}
            )
        except DashboardError as exc:
            self.skipTest(f"渲染不可用：{exc}")
        self.assertEqual(payload["index"], 206)
        self.assertEqual(payload["character"], "miku")
        self.assertTrue(payload["layout"]["curve"])
        self.assertEqual(payload["layout"]["lines"], ["早上好"])
        self.assertIn("-s 40", payload["command"])
        self.assertTrue(payload["data_url"].startswith("data:image/png;base64,"))

    async def test_render_rejects_out_of_range_options(self) -> None:
        self.write_artwork("Miku/Miku_03.png")
        with self.assertRaises(DashboardError):
            await self.dashboard.pjsk_render({"index": 206, "rotate": 90})

    def test_command_hint_can_be_pasted_into_chat(self) -> None:
        sticker = pjsk_catalog.sticker_by_index(206)
        options = coerce_options({"font_size": 40, "curve": True, "scale": 3})
        command = MemeDashboard._pjsk_command(sticker, "hello\nworld", options)
        self.assertEqual(command, r"/pjsk 206 hello\nworld -s 40 -c --scale 3")


if __name__ == "__main__":
    unittest.main()