from __future__ import annotations

import io
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tomlkit

from astrbot_plugin_meme_forge.core.extensions import (
    ExtensionInstallError,
    MemeEmojiExtensionManager,
)


class ExtensionManagerTests(unittest.TestCase):
    def test_platform_asset_selection(self) -> None:
        self.assertEqual(
            MemeEmojiExtensionManager.platform_asset_name("Windows", "AMD64", {}),
            "meme-emoji-windows-x86_64.dll",
        )
        self.assertEqual(
            MemeEmojiExtensionManager.platform_asset_name("Linux", "aarch64", {}),
            "meme-emoji-linux-aarch64.so",
        )
        self.assertEqual(
            MemeEmojiExtensionManager.platform_asset_name(
                "Linux", "aarch64", {"ANDROID_ROOT": "/system"}
            ),
            "meme-emoji-android-aarch64.so",
        )

    def test_resource_path_rejects_traversal(self) -> None:
        with self.assertRaises(ExtensionInstallError):
            MemeEmojiExtensionManager._resource_relative_path(
                "repo/resources/../../outside.txt"
            )

    def test_extracts_only_resources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "source.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                license_payload = b"MIT License"
                license_info = tarfile.TarInfo("repo/LICENSE")
                license_info.size = len(license_payload)
                archive.addfile(license_info, io.BytesIO(license_payload))
                payload = b"image"
                resource = tarfile.TarInfo("repo/resources/images/demo/a.png")
                resource.size = len(payload)
                archive.addfile(resource, io.BytesIO(payload))
                ignored = tarfile.TarInfo("repo/src/lib.rs")
                ignored.size = 3
                archive.addfile(ignored, io.BytesIO(b"src"))
            count, size, probe, license_bytes = (
                MemeEmojiExtensionManager._extract_resources(
                    archive_path, root / "output"
                )
            )
            self.assertEqual((count, size), (1, 5))
            self.assertEqual(probe, "images/demo/a.png")
            self.assertEqual(license_bytes, b"MIT License")
            self.assertEqual(
                (root / "output/images/demo/a.png").read_bytes(),
                b"image",
            )
            self.assertFalse((root / "output/src/lib.rs").exists())

    def test_toml_update_preserves_existing_sections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = MemeEmojiExtensionManager(root / "data", {})
            manager.meme_home = root / "meme-home"
            manager.meme_home.mkdir()
            config_path = manager.meme_home / "config.toml"
            config_path.write_text(
                '[resource]\nresource_url = "test"\n', encoding="utf-8"
            )
            manager._enable_external_memes()
            document = tomlkit.parse(config_path.read_text(encoding="utf-8"))
            self.assertEqual(document["resource"]["resource_url"], "test")
            self.assertTrue(document["meme"]["load_external_memes"])

    def test_resource_merge_rolls_back_replaced_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staging = root / "staging"
            destination = root / "resources"
            staging.mkdir()
            destination.mkdir()
            (staging / "a.txt").write_text("new-a", encoding="utf-8")
            (staging / "b.txt").write_text("new-b", encoding="utf-8")
            (destination / "a.txt").write_text("old-a", encoding="utf-8")
            (destination / "b.txt").write_text("old-b", encoding="utf-8")

            real_replace = os.replace
            failed = False

            def fail_second_resource(source, target):
                nonlocal failed
                source_path = Path(source)
                target_path = Path(target)
                if (
                    not failed
                    and source_path == staging / "b.txt"
                    and target_path == destination / "b.txt"
                ):
                    failed = True
                    raise OSError("simulated merge failure")
                return real_replace(source, target)

            with (
                patch(
                    "astrbot_plugin_meme_forge.core.extensions.os.replace",
                    side_effect=fail_second_resource,
                ),
                self.assertRaises(OSError),
            ):
                MemeEmojiExtensionManager._merge_staged_resources(staging, destination)

            self.assertEqual(
                (destination / "a.txt").read_text(encoding="utf-8"), "old-a"
            )
            self.assertEqual(
                (destination / "b.txt").read_text(encoding="utf-8"), "old-b"
            )
            self.assertEqual(list(root.glob(".meme-emoji-backup-*")), [])


if __name__ == "__main__":
    unittest.main()
