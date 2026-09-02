from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import quote

import aiohttp

from . import pjsk_catalog

PYPI_API_URL = "https://pypi.org/pypi/meme-generator/json"
SUPPORTED_MINIMUM = (0, 2, 3, 0)
SUPPORTED_MAXIMUM = (0, 3, 0, 0)
SUPPORTED_RANGE_TEXT = ">=0.2.3,<0.3"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024

#: Branch watched for new PJSK artwork on the upstream sticker repository.
PJSK_STICKER_BRANCH: Final = "main"
#: GitHub API entry point for the repository pinned in :mod:`pjsk_catalog`.
PJSK_STICKER_API_URL: Final = (
    "https://api.github.com/repos/"
    + pjsk_catalog.SOURCE_REPOSITORY.removeprefix("https://github.com/").strip("/")
)
USER_AGENT: Final = "astrbot-plugin-meme-forge/update-check"


class UpdateCheckError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SourceRevision:
    """One upstream commit, as reported by the GitHub commits API."""

    commit: str
    committed_at: str
    url: str

    @property
    def short_commit(self) -> str:
        """First twelve characters, which is what the chat replies show."""
        return self.commit[:12]


def parse_source_revision(payload: Any) -> SourceRevision:
    """Validate one GitHub commit payload before trusting any of its fields."""
    if not isinstance(payload, dict):
        raise UpdateCheckError("GitHub 返回格式无效")
    commit = str(payload.get("sha") or "")
    details = payload.get("commit")
    author = details.get("author") if isinstance(details, dict) else None
    committed_at = str(author.get("date") or "") if isinstance(author, dict) else ""
    url = str(payload.get("html_url") or "")
    if (
        not re.fullmatch(r"[0-9a-f]{40}", commit)
        or not committed_at
        or not url.startswith("https://")
    ):
        raise UpdateCheckError("GitHub 响应缺少提交信息")
    return SourceRevision(commit=commit, committed_at=committed_at, url=url)


def stable_version_key(value: str) -> tuple[int, int, int, int] | None:
    match = re.fullmatch(
        r"v?(\d+)\.(\d+)\.(\d+)(?:\.post(\d+))?",
        str(value).strip(),
    )
    if match is None:
        return None
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        int(match.group(4) or 0),
    )


def latest_compatible_release(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise UpdateCheckError("PyPI 返回格式无效")
    releases = payload.get("releases")
    if not isinstance(releases, dict):
        raise UpdateCheckError("PyPI 响应缺少版本列表")

    candidates: list[tuple[tuple[int, int, int, int], str]] = []
    for raw_version, raw_files in releases.items():
        version = str(raw_version).strip()
        key = stable_version_key(version)
        if key is None or not (SUPPORTED_MINIMUM <= key < SUPPORTED_MAXIMUM):
            continue
        if not isinstance(raw_files, list) or not any(
            isinstance(file, dict) and not bool(file.get("yanked"))
            for file in raw_files
        ):
            continue
        candidates.append((key, version))

    if not candidates:
        raise UpdateCheckError(
            f"PyPI 没有可用的兼容版本（要求 {SUPPORTED_RANGE_TEXT}）"
        )
    return max(candidates)[1]


def compare_engine_versions(current: str, latest: str) -> str:
    current_key = stable_version_key(current)
    latest_key = stable_version_key(latest)
    if current_key is None or latest_key is None:
        return "unknown"
    if current_key < latest_key:
        return "update_available"
    if current_key > latest_key:
        return "newer"
    return "current"


def format_check_error(error: BaseException) -> str:
    if isinstance(error, TimeoutError):
        return "检查超时"
    detail = str(error).strip() or type(error).__name__
    return detail if len(detail) <= 200 else detail[:197] + "..."


async def _fetch_json(
    url: str,
    label: str,
    headers: dict[str, str] | None = None,
) -> Any:
    """GET one small JSON document with a hard cap on the response size."""
    timeout = aiohttp.ClientTimeout(total=20, connect=10, sock_read=10)
    request_headers = {"User-Agent": USER_AGENT}
    request_headers.update(headers or {})
    async with (
        aiohttp.ClientSession(
            timeout=timeout,
            trust_env=True,
            headers=request_headers,
        ) as session,
        session.get(url) as response,
    ):
        response.raise_for_status()
        if response.content_length and response.content_length > MAX_RESPONSE_BYTES:
            raise UpdateCheckError(f"{label}响应超过安全大小限制")
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.content.iter_chunked(64 * 1024):
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise UpdateCheckError(f"{label}响应超过安全大小限制")
            chunks.append(chunk)
        data = b"".join(chunks)
    try:
        return json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateCheckError(f"{label}返回的 JSON 无效") from exc


async def fetch_latest_compatible_meme_generator() -> str:
    payload = await _fetch_json(PYPI_API_URL, "PyPI ")
    return latest_compatible_release(payload)


async def fetch_pjsk_sticker_revision() -> SourceRevision:
    """Read the newest commit of the upstream PJSK artwork repository."""
    url = f"{PJSK_STICKER_API_URL}/commits/{quote(PJSK_STICKER_BRANCH, safe='')}"
    payload = await _fetch_json(
        url,
        "GitHub ",
        headers={"Accept": "application/vnd.github+json"},
    )
    return parse_source_revision(payload)
