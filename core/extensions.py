from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import shutil
import tarfile
import tempfile
from collections.abc import MutableMapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

import aiohttp
import tomlkit
from astrbot.api import logger


class ExtensionInstallError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    name: str
    url: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ExtensionRelease:
    tag: str
    asset: ReleaseAsset


@dataclass(frozen=True, slots=True)
class ExtensionStatus:
    installed: bool
    tag: str | None
    library_path: str | None
    library_valid: bool
    license_present: bool
    resources_present: bool
    external_loading_enabled: bool


class MemeEmojiExtensionManager:
    API_URL = "https://api.github.com/repos/anyliew/meme-emoji/releases/latest"
    SOURCE_REPOSITORY = "https://github.com/anyliew/meme_emoji"
    RUST_REPOSITORY = "https://github.com/anyliew/meme-emoji"
    USER_AGENT = "astrbot-plugin-meme-forge/1.0"
    MAX_LIBRARY_BYTES = 64 * 1024 * 1024
    MAX_ARCHIVE_BYTES = 700 * 1024 * 1024
    MAX_RESOURCE_BYTES = 700 * 1024 * 1024
    MIN_FREE_BYTES = 1_100 * 1024 * 1024

    def __init__(self, data_dir: Path, config: Any):
        self.data_dir = data_dir
        self.config = config
        configured_home = os.getenv("MEME_HOME")
        self.meme_home = (
            Path(configured_home).expanduser()
            if configured_home
            else Path.home() / ".meme_generator"
        )
        self.manifest_path = data_dir / "meme_emoji_extension.json"
        self._session: aiohttp.ClientSession | None = None
        self._install_lock = asyncio.Lock()

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
                60, int(self._config_value("extension_download_timeout", 1800))
            )
            timeout = aiohttp.ClientTimeout(
                total=timeout_seconds,
                connect=30,
                sock_read=180,
            )
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                trust_env=True,
                headers={"User-Agent": self.USER_AGENT},
            )
        return self._session

    @staticmethod
    def platform_asset_name(
        system: str | None = None,
        machine: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> str:
        system_name = (system or platform.system()).casefold()
        machine_name = (machine or platform.machine()).casefold()
        env = environment if environment is not None else os.environ
        architecture = {
            "amd64": "x86_64",
            "x64": "x86_64",
            "x86_64": "x86_64",
            "arm64": "aarch64",
            "aarch64": "aarch64",
        }.get(machine_name)
        if architecture is None:
            raise ExtensionInstallError(f"meme-emoji 暂不支持 CPU 架构: {machine_name}")

        if system_name == "windows" and architecture == "x86_64":
            return "meme-emoji-windows-x86_64.dll"
        if system_name == "darwin":
            return f"meme-emoji-macos-{architecture}.dylib"
        if system_name == "linux":
            if architecture == "aarch64" and (
                env.get("ANDROID_ROOT") or env.get("TERMUX_VERSION")
            ):
                return "meme-emoji-android-aarch64.so"
            return f"meme-emoji-linux-{architecture}.so"
        raise ExtensionInstallError(f"meme-emoji 暂不支持操作系统: {system_name}")

    async def latest_release(self) -> ExtensionRelease:
        session = await self._get_session()
        async with session.get(self.API_URL) as response:
            response.raise_for_status()
            payload = await response.json()

        expected_name = self.platform_asset_name()
        asset_payload = next(
            (
                asset
                for asset in payload.get("assets", [])
                if asset.get("name") == expected_name
            ),
            None,
        )
        if asset_payload is None:
            raise ExtensionInstallError(
                f"最新 release 没有当前平台构建: {expected_name}"
            )

        digest = str(asset_payload.get("digest") or "")
        if not digest.startswith("sha256:"):
            raise ExtensionInstallError("release 未提供 SHA-256，已拒绝安装")
        return ExtensionRelease(
            tag=str(payload["tag_name"]),
            asset=ReleaseAsset(
                name=expected_name,
                url=str(asset_payload["browser_download_url"]),
                size=int(asset_payload["size"]),
                sha256=digest.removeprefix("sha256:"),
            ),
        )

    async def _download(
        self,
        url: str,
        destination: Path,
        *,
        maximum_bytes: int,
        expected_size: int | None = None,
    ) -> tuple[int, str]:
        session = await self._get_session()
        digest = hashlib.sha256()
        size = 0
        async with session.get(url, allow_redirects=True) as response:
            response.raise_for_status()
            if response.content_length and response.content_length > maximum_bytes:
                raise ExtensionInstallError("下载文件超过安全大小限制")
            with destination.open("wb") as output:
                async for chunk in response.content.iter_chunked(1024 * 1024):
                    size += len(chunk)
                    if size > maximum_bytes:
                        raise ExtensionInstallError("下载文件超过安全大小限制")
                    output.write(chunk)
                    digest.update(chunk)
                    if size and size % (50 * 1024 * 1024) < len(chunk):
                        logger.info(
                            "[meme_forge] 扩展已下载 %.1f MB", size / 1024 / 1024
                        )
        if expected_size is not None and size != expected_size:
            raise ExtensionInstallError(
                f"下载大小不符：预期 {expected_size}，实际 {size}"
            )
        return size, digest.hexdigest()

    @staticmethod
    def _resource_relative_path(member_name: str) -> Path | None:
        path = PurePosixPath(member_name)
        if path.is_absolute() or ".." in path.parts:
            raise ExtensionInstallError(f"压缩包包含不安全路径: {member_name}")
        try:
            resource_index = path.parts.index("resources")
        except ValueError:
            return None
        relative_parts = path.parts[resource_index + 1 :]
        if not relative_parts:
            return None
        return Path(*relative_parts)

    @classmethod
    def _extract_resources(
        cls, archive_path: Path, destination: Path
    ) -> tuple[int, int, str, bytes]:
        destination.mkdir(parents=True, exist_ok=True)
        destination_root = destination.resolve()
        count = 0
        total_bytes = 0
        resource_probe = ""
        license_bytes: bytes | None = None
        with tarfile.open(archive_path, mode="r:gz") as archive:
            for member in archive:
                member_path = PurePosixPath(member.name)
                if (
                    member.isfile()
                    and len(member_path.parts) == 2
                    and member_path.name == "LICENSE"
                    and member.size <= 128 * 1024
                ):
                    license_source = archive.extractfile(member)
                    if license_source is not None:
                        with license_source:
                            license_bytes = license_source.read()
                    continue
                relative = cls._resource_relative_path(member.name)
                if relative is None or member.isdir():
                    continue
                if not member.isfile() or member.issym() or member.islnk():
                    raise ExtensionInstallError(
                        f"压缩包资源不是普通文件: {member.name}"
                    )
                count += 1
                total_bytes += member.size
                if not resource_probe:
                    resource_probe = relative.as_posix()
                if count > 10_000 or total_bytes > cls.MAX_RESOURCE_BYTES:
                    raise ExtensionInstallError("扩展资源超过安全解压限制")

                target = (destination / relative).resolve()
                if (
                    target != destination_root
                    and destination_root not in target.parents
                ):
                    raise ExtensionInstallError(f"资源路径越界: {member.name}")
                source = archive.extractfile(member)
                if source is None:
                    raise ExtensionInstallError(f"无法读取压缩包资源: {member.name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + ".meme-forge.part")
                try:
                    with source, temporary.open("wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
        if count == 0:
            raise ExtensionInstallError("压缩包中没有找到 resources 文件")
        if not license_bytes:
            raise ExtensionInstallError("压缩包中没有找到上游 LICENSE")
        return count, total_bytes, resource_probe, license_bytes

    @staticmethod
    def _merge_staged_resources(staging: Path, destination: Path) -> None:
        """Atomically replace individual resources and roll back merge failures."""
        destination.mkdir(parents=True, exist_ok=True)
        backup = Path(
            tempfile.mkdtemp(prefix=".meme-emoji-backup-", dir=destination.parent)
        )
        replaced: list[tuple[Path, Path | None]] = []
        try:
            for source in sorted(path for path in staging.rglob("*") if path.is_file()):
                relative = source.relative_to(staging)
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                backup_target: Path | None = None
                if target.exists():
                    if not target.is_file():
                        raise ExtensionInstallError(
                            f"资源目标不是普通文件: {relative.as_posix()}"
                        )
                    backup_target = backup / relative
                    backup_target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(target, backup_target)
                replaced.append((target, backup_target))
                os.replace(source, target)
        except Exception:
            rollback_errors: list[str] = []
            for target, backup_target in reversed(replaced):
                try:
                    target.unlink(missing_ok=True)
                    if backup_target is not None and backup_target.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(backup_target, target)
                except OSError as exc:
                    rollback_errors.append(f"{target}: {exc}")
            if rollback_errors:
                logger.error(
                    "[meme_forge] 扩展资源回滚不完整: %s",
                    "; ".join(rollback_errors),
                )
            raise
        finally:
            try:
                shutil.rmtree(backup)
            except OSError as exc:
                logger.warning("[meme_forge] 无法清理资源备份目录 %s: %s", backup, exc)

    def _enable_external_memes(self) -> None:
        config_path = self.meme_home / "config.toml"
        self.meme_home.mkdir(parents=True, exist_ok=True)
        if config_path.exists():
            document = tomlkit.parse(config_path.read_text(encoding="utf-8"))
        else:
            document = tomlkit.document()
        meme_table = document.get("meme")
        if not isinstance(meme_table, MutableMapping):
            meme_table = tomlkit.table()
            document["meme"] = meme_table
        if "load_builtin_memes" not in meme_table:
            meme_table["load_builtin_memes"] = True
        meme_table["load_external_memes"] = True
        temporary = config_path.with_name("config.toml.meme-forge.part")
        try:
            temporary.write_text(tomlkit.dumps(document), encoding="utf-8")
            os.replace(temporary, config_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _read_manifest(self) -> dict[str, Any]:
        if not self.manifest_path.is_file():
            return {}
        try:
            value = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def status(self) -> ExtensionStatus:
        manifest = self._read_manifest()
        library_text = manifest.get("library_path")
        library = Path(library_text) if isinstance(library_text, str) else None
        expected_digest = str(manifest.get("library_sha256") or "")
        library_valid = bool(
            library
            and library.is_file()
            and expected_digest
            and self._sha256_file(library) == expected_digest
        )
        license_text = manifest.get("license_path")
        license_path = Path(license_text) if isinstance(license_text, str) else None
        license_present = bool(
            license_path and license_path.is_file() and license_path.stat().st_size > 0
        )
        resource_probe = manifest.get("resource_probe")
        resources_present = bool(
            isinstance(resource_probe, str)
            and resource_probe
            and (self.meme_home / "resources" / resource_probe).is_file()
        )
        external_enabled = False
        config_path = self.meme_home / "config.toml"
        if config_path.is_file():
            try:
                document = tomlkit.parse(config_path.read_text(encoding="utf-8"))
                external_enabled = bool(
                    document.get("meme", {}).get("load_external_memes", False)
                )
            except (OSError, ValueError, TypeError):
                pass
        return ExtensionStatus(
            installed=bool(manifest),
            tag=str(manifest.get("tag")) if manifest.get("tag") else None,
            library_path=str(library) if library else None,
            library_valid=library_valid,
            license_present=license_present,
            resources_present=resources_present,
            external_loading_enabled=external_enabled,
        )

    async def install(self) -> ExtensionStatus:
        if self._install_lock.locked():
            raise ExtensionInstallError("扩展安装任务已经在运行")

        async with self._install_lock:
            release = await self.latest_release()
            current = self.status()
            if (
                current.tag == release.tag
                and current.library_valid
                and current.license_present
                and current.resources_present
            ):
                self._enable_external_memes()
                return self.status()

            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.meme_home.mkdir(parents=True, exist_ok=True)
            data_free = shutil.disk_usage(self.data_dir).free
            resource_free = shutil.disk_usage(self.meme_home).free
            if min(data_free, resource_free) < self.MIN_FREE_BYTES:
                raise ExtensionInstallError(
                    "磁盘空间不足，安装扩展至少需要约 1.1 GB 可用空间"
                )

            library_temp: Path | None = None
            archive_temp: Path | None = None
            resource_staging: Path | None = None
            commit_staging: list[Path] = []
            try:
                library_fd, library_temp_name = tempfile.mkstemp(
                    prefix="meme-emoji-library-", suffix=".part", dir=self.data_dir
                )
                library_temp = Path(library_temp_name)
                os.close(library_fd)
                archive_fd, archive_temp_name = tempfile.mkstemp(
                    prefix="meme-emoji-resources-",
                    suffix=".tar.gz",
                    dir=self.data_dir,
                )
                archive_temp = Path(archive_temp_name)
                os.close(archive_fd)
                resource_staging = Path(
                    tempfile.mkdtemp(
                        prefix=".meme-emoji-resources-", dir=self.meme_home
                    )
                )

                _, library_digest = await self._download(
                    release.asset.url,
                    library_temp,
                    maximum_bytes=self.MAX_LIBRARY_BYTES,
                    expected_size=release.asset.size,
                )
                if library_digest != release.asset.sha256:
                    raise ExtensionInstallError("动态库 SHA-256 校验失败")

                archive_url = (
                    "https://codeload.github.com/anyliew/meme-emoji/tar.gz/"
                    + quote(release.tag, safe="")
                )
                await self._download(
                    archive_url,
                    archive_temp,
                    maximum_bytes=self.MAX_ARCHIVE_BYTES,
                )
                (
                    resource_count,
                    resource_bytes,
                    resource_probe,
                    license_bytes,
                ) = await asyncio.to_thread(
                    self._extract_resources,
                    archive_temp,
                    resource_staging,
                )

                await asyncio.to_thread(
                    self._merge_staged_resources,
                    resource_staging,
                    self.meme_home / "resources",
                )

                libraries_dir = self.meme_home / "libraries"
                libraries_dir.mkdir(parents=True, exist_ok=True)
                library_path = libraries_dir / release.asset.name
                library_staging = libraries_dir / (release.asset.name + ".part")
                commit_staging.append(library_staging)
                await asyncio.to_thread(shutil.copyfile, library_temp, library_staging)
                os.replace(library_staging, library_path)
                license_path = libraries_dir / "meme-emoji.LICENSE"
                license_staging = libraries_dir / "meme-emoji.LICENSE.part"
                commit_staging.append(license_staging)
                license_staging.write_bytes(license_bytes)
                os.replace(license_staging, license_path)
                self._enable_external_memes()

                manifest = {
                    "schema_version": 1,
                    "source_repository": self.SOURCE_REPOSITORY,
                    "runtime_repository": self.RUST_REPOSITORY,
                    "tag": release.tag,
                    "asset": asdict(release.asset),
                    "library_path": str(library_path),
                    "library_sha256": release.asset.sha256,
                    "license_path": str(license_path),
                    "resource_files": resource_count,
                    "resource_bytes": resource_bytes,
                    "resource_probe": resource_probe,
                    "installed_at": datetime.now(timezone.utc).isoformat(),
                }
                temporary_manifest = self.manifest_path.with_suffix(".json.part")
                commit_staging.append(temporary_manifest)
                temporary_manifest.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                os.replace(temporary_manifest, self.manifest_path)
                return self.status()
            finally:
                for temporary in (library_temp, archive_temp, *commit_staging):
                    if temporary is None:
                        continue
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        logger.warning("[meme_forge] 无法清理临时文件: %s", temporary)
                if resource_staging is not None:
                    try:
                        shutil.rmtree(resource_staging)
                    except OSError as exc:
                        logger.warning(
                            "[meme_forge] 无法清理资源暂存目录 %s: %s",
                            resource_staging,
                            exc,
                        )

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
