from __future__ import annotations

import asyncio
import base64
import mimetypes
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar

from .arguments import option_specs_from_params
from .engine import MemeEngine, MemeEngineError
from .extensions import MemeEmojiExtensionManager
from .history import MemeUsageHistory


class DashboardError(RuntimeError):
    """Raised for a user-correctable Dashboard request error."""


class MemeDashboard:
    """Serialize runtime meme data for the plugin Page without exposing file paths."""

    _MATERIAL_SUFFIXES: ClassVar[set[str]] = {
        ".apng",
        ".bmp",
        ".gif",
        ".jpeg",
        ".jpg",
        ".png",
        ".webp",
    }

    def __init__(
        self,
        engine: MemeEngine,
        extension: MemeEmojiExtensionManager,
        config: Any,
    ) -> None:
        self.engine = engine
        self.extension = extension
        self.config = config
        self._preview_lock = asyncio.Lock()

    def _config_value(self, key: str, default: Any) -> Any:
        try:
            return self.config.get(key, default)
        except AttributeError:
            try:
                return self.config[key]
            except (KeyError, TypeError):
                return default

    @property
    def max_preview_bytes(self) -> int:
        megabytes = max(1, min(int(self._config_value("dashboard_preview_max_mb", 4)), 16))
        return megabytes * 1024 * 1024

    @staticmethod
    def _range_text(minimum: int, maximum: int) -> str:
        return str(minimum) if minimum == maximum else f"{minimum}-{maximum}"

    def _resolve(self, key: str) -> Any:
        meme = self.engine.resolve(str(key).strip())
        if meme is None:
            raise DashboardError("没有找到该 meme。")
        return meme

    def meme_summary(self, meme: Any) -> dict[str, Any]:
        params = self.engine.get_params(meme)
        key = str(getattr(meme, "key", ""))
        return {
            "key": key,
            "keywords": self.engine.get_keywords(meme),
            "tags": self.engine.get_tags(meme),
            "enabled": not self.engine.is_disabled(meme),
            "images": {
                "min": int(params.min_images),
                "max": int(params.max_images),
                "label": self._range_text(int(params.min_images), int(params.max_images)),
            },
            "texts": {
                "min": int(params.min_texts),
                "max": int(params.max_texts),
                "label": self._range_text(int(params.min_texts), int(params.max_texts)),
            },
            "has_materials": self._material_directory(key).is_dir(),
        }

    def meme_detail(self, key: str) -> dict[str, Any]:
        meme = self._resolve(key)
        detail = self.meme_summary(meme)
        params = self.engine.get_params(meme)
        detail["default_texts"] = list(getattr(params, "default_texts", []) or [])
        detail["options"] = [
            {
                "name": spec.name,
                "type": spec.kind,
                "default": spec.default,
                "choices": list(spec.choices),
                "minimum": spec.minimum,
                "maximum": spec.maximum,
                "description": spec.description,
                "aliases": list(spec.bare_aliases),
                "flags": list(spec.flag_aliases),
            }
            for spec in option_specs_from_params(params)
        ]
        detail["materials"] = self._materials_for_meme(meme)
        return detail

    def catalog(
        self,
        *,
        query: str = "",
        tag: str = "",
        status: str = "all",
        offset: int = 0,
        limit: int = 60,
    ) -> dict[str, Any]:
        query_text = query.strip().casefold()
        tag_text = tag.strip().casefold()
        status_text = status.strip().casefold()
        items: list[dict[str, Any]] = []
        tags: set[str] = set()
        for meme in sorted(self.engine.memes, key=lambda item: str(item.key)):
            summary = self.meme_summary(meme)
            tags.update(summary["tags"])
            searchable = " ".join(
                [summary["key"], *summary["keywords"], *summary["tags"]]
            ).casefold()
            if query_text and query_text not in searchable:
                continue
            if tag_text and tag_text not in {
                value.casefold() for value in summary["tags"]
            }:
                continue
            if status_text == "enabled" and not summary["enabled"]:
                continue
            if status_text == "disabled" and summary["enabled"]:
                continue
            items.append(summary)

        bounded_offset = max(0, int(offset))
        bounded_limit = max(1, min(int(limit), 100))
        return {
            "items": items[bounded_offset : bounded_offset + bounded_limit],
            "total": len(items),
            "offset": bounded_offset,
            "limit": bounded_limit,
            "tags": sorted(tags),
        }

    def overview(self, history: MemeUsageHistory, extension_status: Any) -> dict[str, Any]:
        total = len(self.engine.memes)
        enabled = len(self.engine.available_memes())
        return {
            "engine_version": self.engine.version,
            "trigger_prefix": str(self._config_value("trigger_prefix", "meme")),
            "total_memes": total,
            "enabled_memes": enabled,
            "disabled_memes": total - enabled,
            "usage_records": len(history.records),
            "extension": {
                "installed": bool(extension_status.installed),
                "tag": extension_status.tag,
                "library_valid": bool(extension_status.library_valid),
                "resources_present": bool(extension_status.resources_present),
            },
        }

    def history(
        self,
        usage: MemeUsageHistory,
        *,
        session: str | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        records = usage.recent(session=session or None, limit=limit)
        return {
            "items": [
                {
                    "key": record.key,
                    "trigger": record.trigger,
                    "platform": record.platform,
                    "session": record.session,
                    "sender_id": record.sender_id,
                    "sender_name": record.sender_name,
                    "created_at": record.created_at,
                }
                for record in records
            ],
            "conversations": usage.conversation_summaries(),
        }

    @staticmethod
    def _data_url(data: bytes, media_type: str) -> str:
        return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"

    @staticmethod
    def _guess_media_type(data: bytes, fallback: str = "image/png") -> str:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return "image/webp"
        return fallback

    async def preview(self, key: str) -> dict[str, str]:
        meme = self._resolve(key)
        try:
            async with self._preview_lock:
                image = await asyncio.wait_for(self.engine.preview(meme), timeout=30)
        except (asyncio.TimeoutError, MemeEngineError) as exc:
            raise DashboardError(f"预览生成失败：{exc}") from exc
        if len(image) > self.max_preview_bytes:
            raise DashboardError(
                f"预览图片超过 {self.max_preview_bytes // 1024 // 1024} MB 限制。"
            )
        media_type = self._guess_media_type(image)
        return {"media_type": media_type, "data_url": self._data_url(image, media_type)}

    @property
    def _material_root(self) -> Path:
        return self.extension.meme_home / "resources" / "images"

    def _material_directory(self, key: str) -> Path:
        root = self._material_root.resolve(strict=False)
        directory = (root / key).resolve(strict=False)
        if directory != root and root not in directory.parents:
            raise DashboardError("素材路径无效。")
        return directory

    def _materials_for_meme(self, meme: Any) -> dict[str, Any]:
        directory = self._material_directory(str(meme.key))
        if not directory.is_dir():
            return {"total": 0, "truncated": False, "items": []}
        items: list[dict[str, Any]] = []
        total = 0
        for candidate in sorted(directory.rglob("*")):
            if not candidate.is_file() or candidate.suffix.casefold() not in self._MATERIAL_SUFFIXES:
                continue
            total += 1
            if len(items) >= 60:
                continue
            relative = candidate.relative_to(directory).as_posix()
            items.append({"name": relative, "size": candidate.stat().st_size})
        return {"total": total, "truncated": total > len(items), "items": items}

    def materials(self, key: str) -> dict[str, Any]:
        return self._materials_for_meme(self._resolve(key))

    def material(self, key: str, name: str) -> dict[str, str]:
        meme = self._resolve(key)
        requested = PurePosixPath(name)
        if (
            not name
            or requested.is_absolute()
            or ".." in requested.parts
            or requested.suffix.casefold() not in self._MATERIAL_SUFFIXES
        ):
            raise DashboardError("素材文件名无效。")

        directory = self._material_directory(str(meme.key))
        target = (directory / requested).resolve(strict=False)
        if (directory != target and directory not in target.parents) or not target.is_file():
            raise DashboardError("没有找到素材文件。")
        size = target.stat().st_size
        if size > self.max_preview_bytes:
            raise DashboardError(
                f"素材图片超过 {self.max_preview_bytes // 1024 // 1024} MB 限制。"
            )
        data = target.read_bytes()
        media_type = mimetypes.guess_type(target.name)[0] or self._guess_media_type(data)
        return {"media_type": media_type, "data_url": self._data_url(data, media_type)}
