from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

from astrbot_plugin_meme_forge.core.dashboard import DashboardError, MemeDashboard
from astrbot_plugin_meme_forge.core.history import MemeUsageHistory

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"x" * 32


class FakeParams:
    min_images: ClassVar[int] = 0
    max_images: ClassVar[int] = 1
    min_texts: ClassVar[int] = 1
    max_texts: ClassVar[int] = 2
    default_texts: ClassVar[list[str]] = ["default"]
    options: ClassVar[list[object]] = []


class FakeMeme:
    def __init__(self, key: str, keywords: list[str], tags: list[str]) -> None:
        self.key = key
        self.keywords = keywords
        self.tags = tags
        self.params_type = FakeParams()


class FakeEngine:
    def __init__(self) -> None:
        self.one = FakeMeme("one", ["first", "one"], ["animal", "fun"])
        self.two = FakeMeme("two", ["second"], ["work"])
        self.memes = [self.one, self.two]
        self.disabled = {"two"}
        self.preview_bytes = PNG_BYTES
        self.version = "test"

    def resolve(self, key: str):
        return next(
            (
                meme
                for meme in self.memes
                if key == meme.key or key in meme.keywords
            ),
            None,
        )

    def get_params(self, meme: FakeMeme) -> FakeParams:
        return meme.params_type

    def get_keywords(self, meme: FakeMeme) -> list[str]:
        return meme.keywords

    def get_tags(self, meme: FakeMeme) -> list[str]:
        return meme.tags

    def is_disabled(self, meme: FakeMeme) -> bool:
        return meme.key in self.disabled

    def available_memes(self) -> list[FakeMeme]:
        return [meme for meme in self.memes if meme.key not in self.disabled]

    async def preview(self, meme: FakeMeme) -> bytes:
        return self.preview_bytes


class MemeDashboardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.engine = FakeEngine()
        self.extension = SimpleNamespace(meme_home=self.root / "meme-home")
        self.dashboard = MemeDashboard(
            self.engine,
            self.extension,
            {"dashboard_preview_max_mb": 1, "trigger_prefix": "meme"},
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    async def test_catalog_filters_and_reports_runtime_status(self) -> None:
        all_items = self.dashboard.catalog()
        self.assertEqual(all_items["total"], 2)
        self.assertEqual(all_items["tags"], ["animal", "fun", "work"])

        searched = self.dashboard.catalog(query="SECOND")
        self.assertEqual([item["key"] for item in searched["items"]], ["two"])

        enabled = self.dashboard.catalog(status="enabled")
        self.assertEqual([item["key"] for item in enabled["items"]], ["one"])

        overview = self.dashboard.overview(
            MemeUsageHistory(),
            SimpleNamespace(
                installed=False,
                tag=None,
                library_valid=False,
                resources_present=False,
            ),
        )
        self.assertEqual(overview["trigger_prefix"], "meme")
        self.assertEqual(overview["enabled_memes"], 1)

    async def test_material_listing_counts_all_and_rejects_path_traversal(self) -> None:
        directory = self.extension.meme_home / "resources" / "images" / "one"
        directory.mkdir(parents=True)
        for index in range(61):
            (directory / f"{index}.png").write_bytes(PNG_BYTES)

        materials = self.dashboard.materials("one")
        self.assertEqual(materials["total"], 61)
        self.assertTrue(materials["truncated"])
        self.assertEqual(len(materials["items"]), 60)
        with self.assertRaises(DashboardError):
            self.dashboard.material("one", "../outside.png")

    async def test_preview_size_limit_and_history_serialization(self) -> None:
        self.engine.preview_bytes = PNG_BYTES + b"x" * (1024 * 1024)
        with self.assertRaises(DashboardError):
            await self.dashboard.preview("one")

        self.engine.preview_bytes = PNG_BYTES
        preview = await self.dashboard.preview("one")
        self.assertTrue(preview["data_url"].startswith("data:image/png;base64,"))

        history = MemeUsageHistory()
        history.remember(
            key="one",
            trigger="first",
            platform="qq",
            session="qq:group:10001",
            sender_id="42",
            sender_name="Alice",
            created_at="2026-08-08T12:00:00+00:00",
        )
        payload = self.dashboard.history(history, session="qq:group:10001")
        self.assertEqual(payload["items"][0]["key"], "one")
        self.assertNotIn("image", payload["items"][0])
        self.assertEqual(payload["conversations"][0]["count"], 1)


if __name__ == "__main__":
    unittest.main()
