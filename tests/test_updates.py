from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from astrbot_plugin_meme_forge.core.extensions import (
    ExtensionRelease,
    ExtensionStatus,
    ReleaseAsset,
)
from astrbot_plugin_meme_forge.core.updates import (
    UpdateCheckError,
    compare_engine_versions,
    format_check_error,
    latest_compatible_release,
)
from astrbot_plugin_meme_forge.main import MemeForgePlugin


class UpdateVersionTests(unittest.TestCase):
    def test_latest_release_stays_inside_supported_range(self) -> None:
        payload = {
            "releases": {
                "0.2.3": [{"yanked": False}],
                "0.2.3.post1": [{"yanked": False}],
                "0.2.4": [{"yanked": True}],
                "0.3.0": [{"yanked": False}],
                "invalid": [{"yanked": False}],
            }
        }
        self.assertEqual(latest_compatible_release(payload), "0.2.3.post1")

    def test_missing_compatible_release_is_reported(self) -> None:
        with self.assertRaises(UpdateCheckError):
            latest_compatible_release({"releases": {"0.3.0": [{"yanked": False}]}})

    def test_version_comparison_states(self) -> None:
        self.assertEqual(compare_engine_versions("0.2.2", "0.2.3"), "update_available")
        self.assertEqual(compare_engine_versions("0.2.3", "0.2.3"), "current")
        self.assertEqual(compare_engine_versions("0.2.4", "0.2.3"), "newer")
        self.assertEqual(compare_engine_versions("unknown", "0.2.3"), "unknown")

    def test_empty_timeout_error_is_readable(self) -> None:
        self.assertEqual(format_check_error(TimeoutError()), "检查超时")


class UpdateCommandTests(unittest.IsolatedAsyncioTestCase):
    class Event:
        @staticmethod
        def plain_result(text: str) -> str:
            return text

    @staticmethod
    def extension_release(tag: str) -> ExtensionRelease:
        return ExtensionRelease(
            tag=tag,
            asset=ReleaseAsset(
                name="meme-emoji-test",
                url="https://example.com/meme-emoji",
                size=1,
                sha256="0" * 64,
            ),
        )

    @staticmethod
    def extension_status(tag: str | None) -> ExtensionStatus:
        installed = tag is not None
        return ExtensionStatus(
            installed=installed,
            tag=tag,
            library_path="test" if installed else None,
            library_valid=installed,
            license_present=installed,
            resources_present=installed,
            external_loading_enabled=installed,
        )

    @staticmethod
    async def collect(generator) -> str:
        return "\n".join([result async for result in generator])

    async def test_reports_engine_and_extension_updates_without_installing(
        self,
    ) -> None:
        plugin = MemeForgePlugin.__new__(MemeForgePlugin)
        plugin.engine = SimpleNamespace(version="0.2.2")
        plugin.extension = SimpleNamespace(
            latest_release=AsyncMock(
                return_value=self.extension_release("v0.0.6+build.43")
            ),
            status=lambda: self.extension_status("v0.0.6+build.42"),
        )

        with patch(
            "astrbot_plugin_meme_forge.main.fetch_latest_compatible_meme_generator",
            new=AsyncMock(return_value="0.2.3"),
        ):
            output = await self.collect(plugin.check_updates(self.Event()))

        self.assertIn("有兼容更新可用", output)
        self.assertIn("v0.0.6+build.43", output)
        self.assertIn("有更新可用", output)
        self.assertIn("只检查，不会下载或安装任何更新", output)

    async def test_one_failed_source_does_not_hide_the_other_result(self) -> None:
        plugin = MemeForgePlugin.__new__(MemeForgePlugin)
        plugin.engine = SimpleNamespace(version="0.2.3")
        plugin.extension = SimpleNamespace(
            latest_release=AsyncMock(return_value=self.extension_release("v1.0.0")),
            status=lambda: self.extension_status("v1.0.0"),
        )

        with patch(
            "astrbot_plugin_meme_forge.main.fetch_latest_compatible_meme_generator",
            new=AsyncMock(side_effect=UpdateCheckError("PyPI unavailable")),
        ):
            output = await self.collect(plugin.check_updates(self.Event()))

        self.assertIn("最新版本：检查失败（PyPI unavailable）", output)
        self.assertIn("已是最新版本，且本地校验通过", output)


if __name__ == "__main__":
    unittest.main()
