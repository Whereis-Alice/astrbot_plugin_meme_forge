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
        self.gouqi_extension = SimpleNamespace(assets_root=self.root / "gouqi-assets")
        self.dashboard = MemeDashboard(
            self.engine,
            self.extension,
            {"dashboard_preview_max_mb": 1, "trigger_prefix": "meme"},
            gouqi_extension=self.gouqi_extension,
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

    async def test_gouqi_source_and_material_directory_are_exposed(self) -> None:
        self.engine.one.source = "gouqi"
        self.engine.one.material_directory = (
            self.gouqi_extension.assets_root / "memes" / "one" / "images"
        )
        self.engine.one.material_directory.mkdir(parents=True)
        (self.engine.one.material_directory / "asset.png").write_bytes(PNG_BYTES)

        detail = self.dashboard.meme_detail("one")

        self.assertEqual(detail["source"], "gouqi")
        self.assertEqual(detail["materials"]["total"], 1)
        material = self.dashboard.material("one", "asset.png")
        self.assertTrue(material["data_url"].startswith("data:image/png;base64,"))

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

        overview = self.dashboard.overview(
            history,
            SimpleNamespace(
                installed=False,
                tag=None,
                library_valid=False,
                resources_present=False,
            ),
        )
        self.assertEqual(overview["top_memes"][0]["key"], "one")
        self.assertEqual(overview["top_memes"][0]["count"], 1)
        self.assertEqual(overview["active_conversations"][0]["session"], "qq:group:10001")
        self.assertEqual(overview["recent_records"][0]["sender_name"], "Alice")
        self.assertNotIn("image", overview["recent_records"][0])

    async def test_catalog_supports_source_filter_and_sorting(self) -> None:
        self.engine.two.source = "external"
        self.engine.two.params_type.min_images = 2
        self.engine.two.params_type.max_images = 4

        payload = self.dashboard.catalog()
        self.assertEqual(
            payload["sources"],
            [
                {"source": "external", "count": 1},
                {"source": "meme_generator", "count": 1},
            ],
        )

        external = self.dashboard.catalog(source="External")
        self.assertEqual([item["key"] for item in external["items"]], ["two"])
        # 来源与标签列表始终基于全量数据，筛选后仍能切回其它来源。
        self.assertEqual(len(external["sources"]), 2)
        self.assertEqual(external["tags"], ["animal", "fun", "work"])

        by_images = self.dashboard.catalog(sort="images")
        self.assertEqual([item["key"] for item in by_images["items"]], ["two", "one"])
        by_name_desc = self.dashboard.catalog(sort="key_desc")
        self.assertEqual([item["key"] for item in by_name_desc["items"]], ["two", "one"])

        fallback = self.dashboard.catalog(sort="not-a-sort")
        self.assertEqual(fallback["sort"], "key")
        self.assertEqual([item["key"] for item in fallback["items"]], ["one", "two"])

    async def test_overview_reports_sources_and_tag_count(self) -> None:
        self.engine.two.source = "gouqi"

        overview = self.dashboard.overview(
            MemeUsageHistory(),
            SimpleNamespace(
                installed=False,
                tag=None,
                library_valid=False,
                resources_present=False,
            ),
        )

        self.assertEqual(
            overview["sources"],
            [
                {"source": "gouqi", "count": 1},
                {"source": "meme_generator", "count": 1},
            ],
        )
        self.assertEqual(overview["tag_count"], 3)
        self.assertEqual(overview["disabled_memes"], 1)

    async def test_material_index_drives_has_materials(self) -> None:
        self.assertEqual(self.dashboard._material_index(), frozenset())

        directory = self.extension.meme_home / "resources" / "images" / "one"
        directory.mkdir(parents=True)
        (directory / "asset.png").write_bytes(PNG_BYTES)

        self.assertEqual(self.dashboard._material_index(), frozenset({"one"}))
        summaries = {item["key"]: item for item in self.dashboard.catalog()["items"]}
        self.assertTrue(summaries["one"]["has_materials"])
        self.assertFalse(summaries["two"]["has_materials"])


if __name__ == "__main__":
    unittest.main()
