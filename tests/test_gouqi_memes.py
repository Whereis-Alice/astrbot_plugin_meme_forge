from __future__ import annotations

import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from astrbot_plugin_meme_forge.core.engine import MemeEngine, MemeInputs
from astrbot_plugin_meme_forge.core.gouqi_memes import (
    GouqiRenderError,
    _compose_twist_frame,
    build_gouqi_memes,
)


def png_bytes(color: str = "#38bdf8") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (96, 72), color).save(output, format="PNG")
    return output.getvalue()


class GouqiMemeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.memes = build_gouqi_memes(Path(self.directory.name) / "memes")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_catalog_exposes_all_reviewed_templates(self) -> None:
        self.assertEqual(len(self.memes), 10)
        by_key = {meme.key: meme for meme in self.memes}
        self.assertEqual(by_key["i_squeeze"].info.params.min_images, 2)
        self.assertIn("线稿", by_key["line_art"].info.keywords)
        self.assertEqual(by_key["line_art"].source, "gouqi")

    def test_line_art_uses_custom_engine_adapter(self) -> None:
        meme = next(item for item in self.memes if item.key == "line_art")
        engine = MemeEngine({})
        output = asyncio.run(
            engine.generate(
                meme,
                MemeInputs(
                    images=[("input.png", png_bytes())],
                    texts=[],
                    options={},
                ),
            )
        )
        self.assertTrue(output.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_invalid_input_has_readable_error(self) -> None:
        meme = next(item for item in self.memes if item.key == "line_art")
        with self.assertRaises(GouqiRenderError):
            meme.generate_from_inputs(
                SimpleNamespace(images=[("broken", b"not-image")], texts=[])
            )

    def test_twist_restores_hidden_template_background_behind_transparency(self) -> None:
        template = Image.new("RGBA", (20, 20), (12, 34, 56, 255))
        # Keep the artwork RGB while making the input slot transparent, as in
        # the reviewed Gouqi PNGs.
        for y in range(6, 14):
            for x in range(6, 14):
                template.putpixel((x, y), (210, 180, 90, 0))

        rotated = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        rotated.putpixel((4, 4), (30, 200, 120, 255))
        output = _compose_twist_frame(template, rotated, (6, 6))

        self.assertEqual(output.getpixel((7, 7)), (210, 180, 90, 255))
        self.assertEqual(output.getpixel((10, 10)), (30, 200, 120, 255))
        self.assertEqual(output.getchannel("A").getextrema(), (255, 255))

    def test_twist_does_not_invent_black_backdrop_without_hidden_artwork(self) -> None:
        template = Image.new("RGBA", (12, 12), (12, 34, 56, 255))
        for y in range(3, 9):
            for x in range(3, 9):
                template.putpixel((x, y), (0, 0, 0, 0))
        rotated = Image.new("RGBA", (6, 6), (0, 0, 0, 0))

        output = _compose_twist_frame(template, rotated, (3, 3))

        self.assertEqual(output.getpixel((5, 5)), (0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
