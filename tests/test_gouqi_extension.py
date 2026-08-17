from __future__ import annotations

import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from astrbot_plugin_meme_forge.core.gouqi_extension import (
    GouqiExtensionError,
    GouqiExtensionManager,
)


class GouqiExtensionManagerTests(unittest.TestCase):
    @staticmethod
    def _archive(path: Path, files: dict[str, bytes]) -> None:
        with tarfile.open(path, mode="w:gz") as archive:
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))

    def test_extracts_only_reviewed_assets(self) -> None:
        first = b"first-image"
        second = b"second-image"
        expected = {
            "memes/one/images/a.png": (
                len(first),
                GouqiExtensionManager._git_blob_sha(first),
            ),
            "memes/two/images/b.gif": (
                len(second),
                GouqiExtensionManager._git_blob_sha(second),
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "source.tar.gz"
            self._archive(
                archive,
                {
                    "repo/memes/one/images/a.png": first,
                    "repo/memes/two/images/b.gif": second,
                    "repo/memes/one/__init__.py": b"raise RuntimeError()",
                    "repo/memes/one/__pycache__/bad.pyc": b"code",
                },
            )
            staging = root / "staging"
            with patch.object(GouqiExtensionManager, "EXPECTED_ASSETS", expected):
                GouqiExtensionManager._extract_reviewed_assets(archive, staging)

            self.assertEqual(
                (staging / "memes/one/images/a.png").read_bytes(), first
            )
            self.assertEqual(
                (staging / "memes/two/images/b.gif").read_bytes(), second
            )
            self.assertFalse((staging / "memes/one/__init__.py").exists())

    def test_tampered_asset_is_rejected(self) -> None:
        original = b"reviewed"
        expected = {
            "memes/one/images/a.png": (
                len(original),
                GouqiExtensionManager._git_blob_sha(original),
            )
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "source.tar.gz"
            self._archive(
                archive,
                {"repo/memes/one/images/a.png": b"tampered"},
            )
            with (
                patch.object(GouqiExtensionManager, "EXPECTED_ASSETS", expected),
                self.assertRaises(GouqiExtensionError),
            ):
                GouqiExtensionManager._extract_reviewed_assets(
                    archive,
                    root / "staging",
                )

    def test_status_revalidates_installed_files(self) -> None:
        data = b"reviewed"
        relative = "memes/one/images/a.png"
        expected = {
            relative: (len(data), GouqiExtensionManager._git_blob_sha(data))
        }
        with tempfile.TemporaryDirectory() as directory:
            manager = GouqiExtensionManager(Path(directory), {})
            target = manager.assets_root / relative
            target.parent.mkdir(parents=True)
            target.write_bytes(data)
            manager.manifest_path.write_text(
                json.dumps(
                    {
                        "commit": manager.SUPPORTED_COMMIT,
                        "supported_commit": manager.SUPPORTED_COMMIT,
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(GouqiExtensionManager, "EXPECTED_ASSETS", expected):
                status = manager.status()
                self.assertTrue(status.assets_valid)
                target.write_bytes(b"tampered")
                self.assertFalse(manager.status().assets_valid)

    def test_archive_path_rejects_traversal(self) -> None:
        with self.assertRaises(GouqiExtensionError):
            GouqiExtensionManager._archive_relative_path(
                "repo/memes/one/images/../../outside.png"
            )


if __name__ == "__main__":
    unittest.main()

