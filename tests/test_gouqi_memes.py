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


if __name__ == "__main__":
    unittest.main()

