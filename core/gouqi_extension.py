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
from typing import Any, ClassVar
from urllib.parse import quote

import aiohttp
from astrbot.api import logger


class GouqiExtensionError(RuntimeError):
    """Raised when the reviewed Gouqi extension cannot be installed or loaded."""


@dataclass(frozen=True, slots=True)
class GouqiSourceRevision:
    commit: str
    committed_at: str
    url: str


@dataclass(frozen=True, slots=True)
class GouqiExtensionStatus:
    installed: bool
    commit: str | None
    assets_valid: bool
    asset_files: int
    templates: int
    source_license_declared: bool


class GouqiExtensionManager:
    """Install only reviewed assets from meme-generator-gouqi.

    The upstream Python modules target the retired ``add_meme`` API and are not
    executed. Renderers live in this plugin, while this manager downloads only
    the exact image blobs reviewed for ``SUPPORTED_COMMIT``.
    """

    SOURCE_REPOSITORY = "https://github.com/amalopyy123/meme-generator-gouqi"
    API_URL = "https://api.github.com/repos/amalopyy123/meme-generator-gouqi"
    SOURCE_BRANCH = "master"
    SUPPORTED_COMMIT = "40eb41cf7c308315a3186e74954ff011d9c26dd0"
    SUPPORTED_COMMITTED_AT = "2026-08-08T08:55:53Z"
    USER_AGENT = "astrbot-plugin-meme-forge/gouqi-extension"
    MAX_API_BYTES = 2 * 1024 * 1024
    MAX_ARCHIVE_BYTES = 24 * 1024 * 1024
    MAX_EXTRACTED_BYTES = 16 * 1024 * 1024
    MAX_ARCHIVE_MEMBERS = 1_000
    TEMPLATE_COUNT = 10

    # Git blob hashes and sizes from SUPPORTED_COMMIT. The unused duplicate
    # ``ucifinac_action3.png`` and all Python/cache files are intentionally absent.
    EXPECTED_ASSETS: ClassVar[dict[str, tuple[int, str]]] = {
        "memes/ceshi/images/background.png": (
            84_884,
            "7251bcae192f6177957d240120822d53159bb4a8",
        ),
        "memes/eav_grill/images/background.png": (
            92_579,
            "01dc44f4189d864f609a7f6b9911040c3c1fc768",
        ),
        "memes/greeting_cat/images/greeting_cat.gif": (
            373_416,
            "cd47246f92d73c354fef79d4dfa3a80c1e613a06",
        ),
        "memes/haine_shoot/images/haine0.png": (
            346_568,
            "eb59f512007f3f067663d325a8342a847e3c0758",
        ),
        "memes/haine_shoot/images/haine1.png": (
            346_519,
            "8498f9ea2764905755b7b6d58a74e6982cb6b478",
        ),
        "memes/haine_shoot/images/haine2.png": (
            345_893,
            "87ee899b2f31c2cacd104d4f5bdfc848b476940a",
        ),
        "memes/haine_shoot/images/haine3.png": (
            345_288,
            "d8f7a2bac47217a4b808ff7c9c9adae5835c9714",
        ),
        "memes/haine_shoot/images/haine4.png": (
            344_781,
            "00908f269293b14ec61ff10cd248004cf20b8475",
        ),
        "memes/haine_shoot/images/haine5.png": (
            342_506,
            "052ec7c536a92cd04870a7e1a1a166f751ca4332",
        ),
        "memes/haine_shoot/images/haine6.png": (
            339_184,
            "5cc5bd5a979f68e72fefb2a97a49af900895a07e",
        ),
        "memes/haine_shoot/images/haine7.png": (
            333_374,
            "ef1c6073695bff3812b09faef7585b97f07be2bc",
        ),
        "memes/haine_shoot/images/haine8.png": (
            335_268,
            "1c6b84edd9a8b444a20dfaef8e27891a517550b6",
        ),
        "memes/haine_shoot/images/haine9.png": (
            341_644,
            "6c77fe7c8975ba0751e5428f298780395b262037",
        ),
        "memes/haine_shoot/images/stain0.png": (
            4_262,
            "4a74fc68a4e8d5af69d5415eff2a902044e69f39",
        ),
        "memes/haine_shoot/images/stain1.png": (
            4_262,
            "8629d3ecab02c749e86d31c441efa934495ea1bb",
        ),
        "memes/haine_shoot/images/stain2.png": (
            4_262,
            "909fdba5227665a4f7fd541a92fc5327e044c883",
        ),
        "memes/haine_shoot/images/stain3.png": (
            7_261,
            "a91f1f0d028fe1a5e4d638ae42da301c7f68565f",
        ),
        "memes/haine_shoot/images/stain4.png": (
            26_750,
            "e30b7ab2ad704d85c5213011c43c4f3a9b7930a1",
        ),
        "memes/haine_shoot/images/stain5.png": (
            37_745,
            "34c7d1eb8e6bfd02ed42899c2b583e1b070a98ca",
        ),
        "memes/haine_shoot/images/stain6.png": (
            37_745,
            "d58cb23b4a7173d9e8340ee370e0a4ed1badfbe9",
        ),
        "memes/i_squeeze/images/ct_rucyfina_hand.png": (
            139_964,
            "9f4357f745a2955cbee489e57f4374a7846b8168",
        ),
        "memes/lucifina_chan_squeeze/images/ct_rucyfinac1.png": (
            276_670,
            "95383f43b405603bd76a31d0acc72f4e6b88a7f9",
        ),
        "memes/lucifina_squeeze/images/ct_rucyfina1.png": (
            344_521,
            "c4282797de86fa8b91df2e997a0856f1fd0847fa",
        ),
        "memes/lucifinac_twist/images/lucifinac_action1.png": (
            218_757,
            "1f5218f20f1f7d0ba1b9c9b52f0f74121ecb2028",
        ),
        "memes/lucifinac_twist/images/lucifinac_action2.png": (
            221_527,
            "5259eb3a19c8f90b9369edd296eacbc6610b3003",
        ),
        "memes/lucifinac_twist/images/lucifinac_action3.png": (
            219_697,
            "f97f75c66551a25f685a87c4f7f199058d018c0e",
        ),
        "memes/lucifinac_twist/images/lucifinac_action4.png": (
            216_075,
            "228162604ece7892db79d6d45b3109a380d7af85",
        ),
        "memes/luluka_twist/images/luluka_action1.png": (
            227_492,
            "fde349b62896569379951ec347c58859e8380aac",
        ),
        "memes/luluka_twist/images/luluka_action2.png": (
            228_406,
            "135d380289abcef2ff39c2a5b8c45ea1f60dd9db",
        ),
        "memes/luluka_twist/images/luluka_action3.png": (
            225_953,
            "68d9c447d9b21528d2eef1d32c30114c21d88635",
        ),
        "memes/luluka_twist/images/luluka_action4.png": (
            228_141,
            "614f5206f98734d327b2a6ebb01cb74dffaee877",
        ),
    }

    def __init__(self, data_dir: Path, config: Any):
        self.data_dir = data_dir
        self.config = config
        self.extension_dir = data_dir / "gouqi_extension"
        self.assets_root = self.extension_dir / "assets"
        self.manifest_path = self.extension_dir / "manifest.json"
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
                60, int(self._config_value("gouqi_download_timeout", 600))
            )
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(
                    total=timeout_seconds,
                    connect=30,
                    sock_read=120,
                ),
                trust_env=True,
                headers={"User-Agent": self.USER_AGENT},
            )
        return self._session

    @staticmethod
    def _git_blob_sha(data: bytes) -> str:
        header = f"blob {len(data)}\0".encode("ascii")
        try:
            digest = hashlib.sha1(usedforsecurity=False)
        except TypeError:  # pragma: no cover - compatibility with older OpenSSL builds
            digest = hashlib.sha1()
        digest.update(header)
        digest.update(data)
        return digest.hexdigest()

    @classmethod
    def _validate_asset(cls, relative: str, data: bytes) -> None:
        expected = cls.EXPECTED_ASSETS.get(relative)
        if expected is None:
            raise GouqiExtensionError(f"未审阅的 Gouqi 素材路径: {relative}")
        expected_size, expected_sha = expected
        if len(data) != expected_size:
            raise GouqiExtensionError(f"Gouqi 素材大小校验失败: {relative}")
        if cls._git_blob_sha(data) != expected_sha:
            raise GouqiExtensionError(f"Gouqi 素材 Git blob 校验失败: {relative}")

    @classmethod
    def _archive_relative_path(cls, member_name: str) -> str | None:
        path = PurePosixPath(member_name)
        if path.is_absolute() or ".." in path.parts:
            raise GouqiExtensionError(f"Gouqi 压缩包包含不安全路径: {member_name}")
        try:
            index = path.parts.index("memes")
        except ValueError:
            return None
        relative = PurePosixPath(*path.parts[index:]).as_posix()
        return relative if relative in cls.EXPECTED_ASSETS else None

    @classmethod
    def _extract_reviewed_assets(cls, archive_path: Path, staging: Path) -> None:
        staging.mkdir(parents=True, exist_ok=False)
        staging_root = staging.resolve()
        seen: set[str] = set()
        extracted_bytes = 0
        members = 0
        try:
            with tarfile.open(archive_path, mode="r:gz") as archive:
                for member in archive:
                    members += 1
                    if members > cls.MAX_ARCHIVE_MEMBERS:
                        raise GouqiExtensionError("Gouqi 压缩包文件数量超过安全限制")
                    relative = cls._archive_relative_path(member.name)
                    if relative is None:
                        continue
                    if relative in seen:
                        raise GouqiExtensionError(
                            f"Gouqi 压缩包包含重复素材: {relative}"
                        )
                    if not member.isfile() or member.issym() or member.islnk():
                        raise GouqiExtensionError(f"Gouqi 素材不是普通文件: {relative}")
                    expected_size = cls.EXPECTED_ASSETS[relative][0]
                    if member.size != expected_size:
                        raise GouqiExtensionError(f"Gouqi 素材大小校验失败: {relative}")
                    extracted_bytes += member.size
                    if extracted_bytes > cls.MAX_EXTRACTED_BYTES:
                        raise GouqiExtensionError("Gouqi 素材超过安全解压限制")
                    source = archive.extractfile(member)
                    if source is None:
                        raise GouqiExtensionError(f"无法读取 Gouqi 素材: {relative}")
                    data = source.read(expected_size + 1)
                    cls._validate_asset(relative, data)
                    target = (staging / PurePosixPath(relative)).resolve()
                    if target != staging_root and staging_root not in target.parents:
                        raise GouqiExtensionError(f"Gouqi 素材路径越界: {relative}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    seen.add(relative)
        except tarfile.TarError as exc:
            raise GouqiExtensionError("Gouqi 下载包不是有效的 tar.gz") from exc

        missing = sorted(set(cls.EXPECTED_ASSETS) - seen)
        if missing:
            raise GouqiExtensionError(
                "Gouqi 压缩包缺少审阅素材: " + "、".join(missing[:3])
            )

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError):
            return {}

    def status(self) -> GouqiExtensionStatus:
        manifest = self._read_manifest(self.manifest_path)
        valid = bool(manifest) and str(manifest.get("commit") or "") == str(
            self.SUPPORTED_COMMIT
        ) and str(manifest.get("supported_commit") or "") == str(
            self.SUPPORTED_COMMIT
        )
        if valid:
            for relative, (expected_size, expected_sha) in self.EXPECTED_ASSETS.items():
                target = self.assets_root / PurePosixPath(relative)
                try:
                    data = target.read_bytes()
                except OSError:
                    valid = False
                    break
                if len(data) != expected_size or self._git_blob_sha(data) != expected_sha:
                    valid = False
                    break
        return GouqiExtensionStatus(
            installed=bool(manifest),
            commit=str(manifest.get("commit")) if manifest.get("commit") else None,
            assets_valid=valid,
            asset_files=len(self.EXPECTED_ASSETS) if valid else 0,
            templates=self.TEMPLATE_COUNT if valid else 0,
            source_license_declared=False,
        )

    async def _read_limited_json(
        self, response: aiohttp.ClientResponse
    ) -> dict[str, Any]:
        if response.content_length and response.content_length > self.MAX_API_BYTES:
            raise GouqiExtensionError("Gouqi API 响应超过安全大小限制")
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.content.iter_chunked(64 * 1024):
            size += len(chunk)
            if size > self.MAX_API_BYTES:
                raise GouqiExtensionError("Gouqi API 响应超过安全大小限制")
            chunks.append(chunk)
        try:
            payload = json.loads(b"".join(chunks))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GouqiExtensionError("Gouqi API 返回的 JSON 无效") from exc
        if not isinstance(payload, dict):
            raise GouqiExtensionError("Gouqi API 返回格式无效")
        return payload

    async def latest_revision(self) -> GouqiSourceRevision:
        session = await self._get_session()
        url = f"{self.API_URL}/commits/{quote(self.SOURCE_BRANCH, safe='')}"
        async with session.get(url) as response:
            response.raise_for_status()
            payload = await self._read_limited_json(response)
        commit = str(payload.get("sha") or "")
        commit_data = payload.get("commit")
        author_data = commit_data.get("author") if isinstance(commit_data, dict) else None
        committed_at = (
            str(author_data.get("date") or "") if isinstance(author_data, dict) else ""
        )
        html_url = str(payload.get("html_url") or "")
        if len(commit) != 40 or not committed_at or not html_url.startswith("https://"):
            raise GouqiExtensionError("Gouqi API 响应缺少提交信息")
        return GouqiSourceRevision(commit, committed_at, html_url)

    async def _download_archive(self, destination: Path) -> tuple[int, str]:
        session = await self._get_session()
        url = (
            "https://codeload.github.com/amalopyy123/meme-generator-gouqi/tar.gz/"
            + self.SUPPORTED_COMMIT
        )
        digest = hashlib.sha256()
        size = 0
        async with session.get(url, allow_redirects=True) as response:
            response.raise_for_status()
            if (
                response.content_length
                and response.content_length > self.MAX_ARCHIVE_BYTES
            ):
                raise GouqiExtensionError("Gouqi 下载包超过安全大小限制")
            with destination.open("wb") as output:
                async for chunk in response.content.iter_chunked(1024 * 1024):
                    size += len(chunk)
                    if size > self.MAX_ARCHIVE_BYTES:
                        raise GouqiExtensionError("Gouqi 下载包超过安全大小限制")
                    output.write(chunk)
                    digest.update(chunk)
        return size, digest.hexdigest()

    def _write_manifest(self, archive_size: int, archive_sha256: str) -> None:
        payload = {
            "schema_version": 1,
            "source_repository": self.SOURCE_REPOSITORY,
            "source_branch": self.SOURCE_BRANCH,
            "commit": self.SUPPORTED_COMMIT,
            "supported_commit": self.SUPPORTED_COMMIT,
            "committed_at": self.SUPPORTED_COMMITTED_AT,
            "archive_size": archive_size,
            "archive_sha256": archive_sha256,
            "asset_files": len(self.EXPECTED_ASSETS),
            "templates": self.TEMPLATE_COUNT,
            "source_license_declared": False,
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

    async def install(self) -> GouqiExtensionStatus:
        if self._install_lock.locked():
            raise GouqiExtensionError("Gouqi 扩展安装任务已经在运行")

        async with self._install_lock:
            current = await asyncio.to_thread(self.status)
            if current.commit == self.SUPPORTED_COMMIT and current.assets_valid:
                return current

            self.extension_dir.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(self.extension_dir).free < 64 * 1024 * 1024:
                raise GouqiExtensionError("磁盘空间不足，Gouqi 扩展至少需要 64 MB 可用空间")

            archive_fd, archive_name = tempfile.mkstemp(
                prefix="gouqi-extension-",
                suffix=".tar.gz.part",
                dir=self.extension_dir,
            )
            os.close(archive_fd)
            archive_path = Path(archive_name)
            staging = Path(
                tempfile.mkdtemp(prefix=".gouqi-assets-", dir=self.extension_dir)
            )
            backup = self.extension_dir / ".gouqi-assets-backup"
            replaced_existing = False
            try:
                archive_size, archive_sha256 = await self._download_archive(archive_path)
                # mkdtemp creates the directory; extraction requires a fresh target.
                staging.rmdir()
                await asyncio.to_thread(
                    self._extract_reviewed_assets,
                    archive_path,
                    staging,
                )

                if backup.exists():
                    shutil.rmtree(backup)
                if self.assets_root.exists():
                    os.replace(self.assets_root, backup)
                    replaced_existing = True
                os.replace(staging, self.assets_root)
                try:
                    self._write_manifest(archive_size, archive_sha256)
                except Exception:
                    shutil.rmtree(self.assets_root, ignore_errors=True)
                    if replaced_existing and backup.exists():
                        os.replace(backup, self.assets_root)
                    raise
                if backup.exists():
                    try:
                        shutil.rmtree(backup)
                    except OSError as exc:
                        logger.warning(
                            "[meme_forge] 无法清理 Gouqi 素材备份 %s: %s",
                            backup,
                            exc,
                        )
                return await asyncio.to_thread(self.status)
            finally:
                archive_path.unlink(missing_ok=True)
                shutil.rmtree(staging, ignore_errors=True)
                if backup.exists() and not self.assets_root.exists():
                    os.replace(backup, self.assets_root)

    def load_memes(self) -> list[Any]:
        status = self.status()
        if not status.assets_valid:
            return []
        from .gouqi_memes import build_gouqi_memes

        memes = build_gouqi_memes(self.assets_root / "memes")
        logger.info(
            "[meme_forge] 已加载 Gouqi 扩展 %d 个 meme (%s)",
            len(memes),
            self.SUPPORTED_COMMIT[:12],
        )
        return memes

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
