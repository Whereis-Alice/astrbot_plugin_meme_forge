"""Download and verify the optional PJSK sticker assets.

Nothing in this directory is shipped with the plugin. Operators opt in with an
explicit confirmation, the artwork is pulled from pinned upstream commits, and
every file is checked before it replaces whatever was installed before.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import aiohttp
from astrbot.api import logger

from . import pjsk_catalog as catalog


class PjskAssetError(RuntimeError):
    """Raised when the PJSK assets cannot be installed or verified."""


@dataclass(frozen=True, slots=True)
class PjskAssetStatus:
    """Snapshot of what is currently installed under the data directory."""

    installed: bool
    ready: bool
    images: int
    image_bytes: int
    font_installed: bool
    commit: str | None
    font_commit: str | None
    installed_at: str | None
    verified: bool

    @property
    def expected_images(self) -> int:
        return catalog.IMAGE_COUNT


class PjskAssetManager:
    """Install the sticker artwork and handwriting font on demand."""

    STICKER_REPOSITORY = "https://github.com/TheOriginalAyaka/sekai-stickers"
    STICKER_COMMIT = catalog.SOURCE_COMMIT
    STICKER_LICENSE = "MIT"
    FONT_REPOSITORY = "https://github.com/Agnes4m/nonebot_plugin_pjsk"
    FONT_COMMIT = "9d310136c199e156efc27dfbebebc1f7e72f16bc"
    FONT_LICENSE = "MIT"
    FONT_MEMBER = "fonts/YurukaFangTang.ttf"
    FONT_NAME = "YurukaFangTang.ttf"
    FONT_BYTES = 5_152_848
    FONT_SHA256 = "433002bcfede16330146912e43eef4696bfda71b9d29f9cd2297bfea5e04b212"

    USER_AGENT = "astrbot-plugin-meme-forge/pjsk-assets"
    MAX_STICKER_ARCHIVE_BYTES = 48 * 1024 * 1024
    MAX_FONT_ARCHIVE_BYTES = 12 * 1024 * 1024
    MAX_ARCHIVE_MEMBERS = 4_000
    MAX_IMAGE_BYTES = 256 * 1024
    REQUIRED_FREE_BYTES = 96 * 1024 * 1024
    PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

    def __init__(self, data_dir: Path, config: Any):
        self.data_dir = Path(data_dir)
        self.config = config
        self.root = self.data_dir / "pjsk"
        self.images_root = self.root / "img"
        self.font_path = self.root / self.FONT_NAME
        self.manifest_path = self.root / "manifest.json"
        self._session: aiohttp.ClientSession | None = None
        self._install_lock = asyncio.Lock()

    # ------------------------------------------------------------------ config

    def _config_value(self, key: str, default: Any) -> Any:
        try:
            return self.config.get(key, default)
        except AttributeError:
            try:
                return self.config[key]
            except (KeyError, TypeError):
                return default

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout_seconds = max(
                120, int(self._config_value("pjsk_download_timeout", 900))
            )
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(
                    total=timeout_seconds,
                    connect=30,
                    sock_read=180,
                ),
                trust_env=True,
                headers={"User-Agent": self.USER_AGENT},
            )
        return self._session

    # ------------------------------------------------------------------ status

    def image_path(self, relative: str) -> Path:
        """Resolve one catalogue-relative image path inside the data dir."""
        if relative not in catalog.expected_images():
            raise PjskAssetError(f"不在目录中的 PJSK 素材: {relative}")
        return self.images_root / PurePosixPath(relative)

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def status(self) -> PjskAssetStatus:
        """Cheap check used on every load: manifest, file count and font size."""
        manifest = self._read_manifest(self.manifest_path)
        commit = str(manifest.get("sticker_commit") or "") or None
        font_commit = str(manifest.get("font_commit") or "") or None
        images = 0
        image_bytes = 0
        if self.images_root.is_dir():
            for relative in catalog.expected_images():
                try:
                    image_bytes += (
                        self.images_root / PurePosixPath(relative)
                    ).stat().st_size
                except OSError:
                    continue
                images += 1
        try:
            font_installed = self.font_path.stat().st_size == self.FONT_BYTES
        except OSError:
            font_installed = False
        ready = (
            commit == self.STICKER_COMMIT
            and images == catalog.IMAGE_COUNT
            and image_bytes == catalog.IMAGE_BYTES
            and font_installed
        )
        return PjskAssetStatus(
            installed=bool(manifest),
            ready=ready,
            images=images,
            image_bytes=image_bytes,
            font_installed=font_installed,
            commit=commit,
            font_commit=font_commit,
            installed_at=str(manifest.get("installed_at") or "") or None,
            verified=bool(manifest.get("image_digest") == catalog.IMAGE_DIGEST),
        )

    def aggregate_digest(self, root: Path | None = None) -> str:
        """Hash every catalogued image into one digest, in sorted path order."""
        base = self.images_root if root is None else root
        digest = hashlib.sha256()
        for relative in sorted(catalog.expected_images()):
            try:
                data = (base / PurePosixPath(relative)).read_bytes()
            except OSError as exc:
                raise PjskAssetError(f"PJSK 素材缺失: {relative}") from exc
            digest.update(relative.encode("utf-8"))
            digest.update(b"\n")
            digest.update(hashlib.sha256(data).hexdigest().encode("ascii"))
            digest.update(b"\n")
        return digest.hexdigest()

    def verify(self) -> bool:
        """Recompute the image digest and the font hash from disk."""
        try:
            if self.aggregate_digest() != catalog.IMAGE_DIGEST:
                return False
            font = self.font_path.read_bytes()
        except (OSError, PjskAssetError):
            return False
        return (
            len(font) == self.FONT_BYTES
            and hashlib.sha256(font).hexdigest() == self.FONT_SHA256
        )

    # ---------------------------------------------------------------- download

    async def _download(self, url: str, destination: Path, limit: int) -> tuple[int, str]:
        session = await self._get_session()
        digest = hashlib.sha256()
        size = 0
        async with session.get(url, allow_redirects=True) as response:
            response.raise_for_status()
            if response.content_length and response.content_length > limit:
                raise PjskAssetError("PJSK 下载包超过安全大小限制")
            with destination.open("wb") as output:
                async for chunk in response.content.iter_chunked(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise PjskAssetError("PJSK 下载包超过安全大小限制")
                    output.write(chunk)
                    digest.update(chunk)
        return size, digest.hexdigest()

    @staticmethod
    def _archive_parts(member_name: str) -> tuple[str, ...]:
        path = PurePosixPath(member_name)
        if path.is_absolute() or ".." in path.parts:
            raise PjskAssetError(f"PJSK 压缩包包含不安全路径: {member_name}")
        return path.parts

    def _extract_stickers(self, archive_path: Path, staging: Path) -> int:
        """Extract only catalogued images, verifying each one, into staging."""
        staging.mkdir(parents=True, exist_ok=False)
        staging_root = staging.resolve()
        wanted = catalog.expected_images()
        seen: dict[str, str] = {}
        total_bytes = 0
        members = 0
        try:
            with tarfile.open(archive_path, mode="r:gz") as archive:
                for member in archive:
                    members += 1
                    if members > self.MAX_ARCHIVE_MEMBERS:
                        raise PjskAssetError("PJSK 压缩包文件数量超过安全限制")
                    parts = self._archive_parts(member.name)
                    if len(parts) < 4 or parts[1] != "public" or parts[2] != "img":
                        continue
                    relative = PurePosixPath(*parts[3:]).as_posix()
                    if relative not in wanted:
                        continue
                    if relative in seen:
                        raise PjskAssetError(f"PJSK 压缩包包含重复素材: {relative}")
                    if not member.isfile() or member.issym() or member.islnk():
                        raise PjskAssetError(f"PJSK 素材不是普通文件: {relative}")
                    if member.size > self.MAX_IMAGE_BYTES:
                        raise PjskAssetError(f"PJSK 素材过大: {relative}")
                    source = archive.extractfile(member)
                    if source is None:
                        raise PjskAssetError(f"无法读取 PJSK 素材: {relative}")
                    data = source.read(self.MAX_IMAGE_BYTES + 1)
                    if len(data) != member.size:
                        raise PjskAssetError(f"PJSK 素材大小校验失败: {relative}")
                    if not data.startswith(self.PNG_MAGIC):
                        raise PjskAssetError(f"PJSK 素材不是 PNG: {relative}")
                    target = (staging / PurePosixPath(relative)).resolve()
                    if staging_root not in target.parents:
                        raise PjskAssetError(f"PJSK 素材路径越界: {relative}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    seen[relative] = hashlib.sha256(data).hexdigest()
                    total_bytes += len(data)
        except tarfile.TarError as exc:
            raise PjskAssetError("PJSK 下载包不是有效的 tar.gz") from exc

        missing = sorted(wanted - set(seen))
        if missing:
            raise PjskAssetError(
                "PJSK 压缩包缺少素材: " + "、".join(missing[:3])
            )
        if total_bytes != catalog.IMAGE_BYTES:
            raise PjskAssetError("PJSK 素材总大小与预期不符")
        digest = hashlib.sha256()
        for relative in sorted(seen):
            digest.update(relative.encode("utf-8"))
            digest.update(b"\n")
            digest.update(seen[relative].encode("ascii"))
            digest.update(b"\n")
        if digest.hexdigest() != catalog.IMAGE_DIGEST:
            raise PjskAssetError("PJSK 素材摘要校验失败")
        return total_bytes

    def _extract_font(self, archive_path: Path, destination: Path) -> None:
        """Extract and hash-verify the single handwriting font we need."""
        wanted = PurePosixPath(self.FONT_MEMBER).parts
        members = 0
        payload: bytes | None = None
        try:
            with tarfile.open(archive_path, mode="r:gz") as archive:
                for member in archive:
                    members += 1
                    if members > self.MAX_ARCHIVE_MEMBERS:
                        raise PjskAssetError("PJSK 字体包文件数量超过安全限制")
                    parts = self._archive_parts(member.name)
                    if parts[1:] != wanted:
                        continue
                    if not member.isfile() or member.issym() or member.islnk():
                        raise PjskAssetError("PJSK 字体不是普通文件")
                    if member.size != self.FONT_BYTES:
                        raise PjskAssetError("PJSK 字体大小校验失败")
                    source = archive.extractfile(member)
                    if source is None:
                        raise PjskAssetError("无法读取 PJSK 字体")
                    payload = source.read(self.FONT_BYTES + 1)
                    break
        except tarfile.TarError as exc:
            raise PjskAssetError("PJSK 字体包不是有效的 tar.gz") from exc
        if payload is None:
            raise PjskAssetError("PJSK 字体包缺少 " + self.FONT_MEMBER)
        if len(payload) != self.FONT_BYTES:
            raise PjskAssetError("PJSK 字体大小校验失败")
        if hashlib.sha256(payload).hexdigest() != self.FONT_SHA256:
            raise PjskAssetError("PJSK 字体 sha256 校验失败")
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _write_manifest(self, image_bytes: int, archive_sha256: str) -> None:
        payload = {
            "schema_version": 1,
            "sticker_repository": self.STICKER_REPOSITORY,
            "sticker_commit": self.STICKER_COMMIT,
            "sticker_license": self.STICKER_LICENSE,
            "sticker_archive_sha256": archive_sha256,
            "font_repository": self.FONT_REPOSITORY,
            "font_commit": self.FONT_COMMIT,
            "font_license": self.FONT_LICENSE,
            "font_sha256": self.FONT_SHA256,
            "images": catalog.IMAGE_COUNT,
            "image_bytes": image_bytes,
            "image_digest": catalog.IMAGE_DIGEST,
            "installed_at": datetime.now(timezone.utc).isoformat(),
        }
        temporary = self.manifest_path.with_suffix(".json.part")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.manifest_path)
        finally:
            temporary.unlink(missing_ok=True)

    # ----------------------------------------------------------------- install

    async def install(self) -> PjskAssetStatus:
        """Download, verify and atomically swap in the PJSK assets."""
        if self._install_lock.locked():
            raise PjskAssetError("PJSK 素材安装任务已经在运行")

        async with self._install_lock:
            current = await asyncio.to_thread(self.status)
            if current.ready and current.verified:
                return current

            self.root.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(self.root).free < self.REQUIRED_FREE_BYTES:
                raise PjskAssetError("磁盘空间不足，PJSK 素材至少需要 96 MB 可用空间")

            archive_fd, archive_name = tempfile.mkstemp(
                prefix="pjsk-stickers-", suffix=".tar.gz.part", dir=self.root
            )
            os.close(archive_fd)
            archive_path = Path(archive_name)
            font_fd, font_name = tempfile.mkstemp(
                prefix="pjsk-font-", suffix=".tar.gz.part", dir=self.root
            )
            os.close(font_fd)
            font_archive = Path(font_name)
            staging = Path(tempfile.mkdtemp(prefix=".pjsk-img-", dir=self.root))
            backup = self.root / ".img-backup"
            replaced_existing = False
            try:
                _, archive_sha256 = await self._download(
                    self._codeload_url(self.STICKER_REPOSITORY, self.STICKER_COMMIT),
                    archive_path,
                    self.MAX_STICKER_ARCHIVE_BYTES,
                )
                await self._download(
                    self._codeload_url(self.FONT_REPOSITORY, self.FONT_COMMIT),
                    font_archive,
                    self.MAX_FONT_ARCHIVE_BYTES,
                )
                # mkdtemp already created the directory; extraction wants it gone.
                staging.rmdir()
                image_bytes = await asyncio.to_thread(
                    self._extract_stickers, archive_path, staging
                )
                await asyncio.to_thread(self._extract_font, font_archive, self.font_path)

                if backup.exists():
                    shutil.rmtree(backup)
                if self.images_root.exists():
                    os.replace(self.images_root, backup)
                    replaced_existing = True
                os.replace(staging, self.images_root)
                try:
                    self._write_manifest(image_bytes, archive_sha256)
                except Exception:
                    shutil.rmtree(self.images_root, ignore_errors=True)
                    if replaced_existing and backup.exists():
                        os.replace(backup, self.images_root)
                    raise
                if backup.exists():
                    try:
                        shutil.rmtree(backup)
                    except OSError as exc:
                        logger.warning(
                            "[meme_forge] 无法清理 PJSK 素材备份 %s: %s", backup, exc
                        )
                logger.info(
                    "[meme_forge] PJSK 素材已安装：%d 张贴纸 (%s)",
                    catalog.IMAGE_COUNT,
                    self.STICKER_COMMIT[:12],
                )
                return await asyncio.to_thread(self.status)
            finally:
                archive_path.unlink(missing_ok=True)
                font_archive.unlink(missing_ok=True)
                shutil.rmtree(staging, ignore_errors=True)
                if backup.exists() and not self.images_root.exists():
                    os.replace(backup, self.images_root)

    @staticmethod
    def _codeload_url(repository: str, commit: str) -> str:
        slug = repository.removeprefix("https://github.com/").strip("/")
        return f"https://codeload.github.com/{slug}/tar.gz/{commit}"

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
