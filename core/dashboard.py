from __future__ import annotations

import asyncio
import base64
import mimetypes
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar

from .arguments import option_specs_from_params
from .engine import MemeEngine, MemeEngineError
from .extensions import MemeEmojiExtensionManager
from .gouqi_extension import GouqiExtensionManager
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
        *,
        gouqi_extension: GouqiExtensionManager | None = None,
    ) -> None:
        self.engine = engine
        self.extension = extension
        self.gouqi_extension = gouqi_extension
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

    def _source_of(self, meme: Any) -> str:
        get_source = getattr(self.engine, "get_source", None)
        if callable(get_source):
            return str(get_source(meme))
        return str(getattr(meme, "source", "meme_generator"))

    def _resolve(self, key: str) -> Any:
        meme = self.engine.resolve(str(key).strip())
        if meme is None:
            raise DashboardError("没有找到该 meme。")
        return meme

    def meme_summary(
        self,
        meme: Any,
        *,
        material_index: frozenset[str] | None = None,
    ) -> dict[str, Any]:
        params = self.engine.get_params(meme)
        key = str(getattr(meme, "key", ""))
        source = self._source_of(meme)
        return {
            "key": key,
            "source": source,
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
            "has_materials": self._has_materials(meme, key, material_index),
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

    _SORTERS: ClassVar[dict[str, Any]] = {
        "key": lambda item: (item["key"],),
        "key_desc": lambda item: (item["key"],),
        "images": lambda item: (-item["images"]["max"], item["key"]),
        "texts": lambda item: (-item["texts"]["max"], item["key"]),
        "source": lambda item: (item["source"], item["key"]),
    }

    def catalog(
        self,
        *,
        query: str = "",
        tag: str = "",
        status: str = "all",
        source: str = "",
        sort: str = "key",
        offset: int = 0,
        limit: int = 60,
    ) -> dict[str, Any]:
        query_text = query.strip().casefold()
        tag_text = tag.strip().casefold()
        status_text = status.strip().casefold()
        source_text = source.strip().casefold()
        sort_key = sort.strip().casefold()
        if sort_key not in self._SORTERS:
            sort_key = "key"

        material_index = self._material_index()
        items: list[dict[str, Any]] = []
        tags: set[str] = set()
        source_counts: dict[str, int] = {}
        for meme in self.engine.memes:
            summary = self.meme_summary(meme, material_index=material_index)
            tags.update(summary["tags"])
            source_counts[summary["source"]] = source_counts.get(summary["source"], 0) + 1
            searchable = " ".join(
                [summary["key"], *summary["keywords"], *summary["tags"]]
            ).casefold()
            if query_text and query_text not in searchable:
                continue
            if tag_text and tag_text not in {
                value.casefold() for value in summary["tags"]
            }:
                continue
            if source_text and summary["source"].casefold() != source_text:
                continue
            if status_text == "enabled" and not summary["enabled"]:
                continue
            if status_text == "disabled" and summary["enabled"]:
                continue
            items.append(summary)

        items.sort(key=self._SORTERS[sort_key], reverse=sort_key == "key_desc")
        bounded_offset = max(0, int(offset))
        bounded_limit = max(1, min(int(limit), 100))
        return {
            "items": items[bounded_offset : bounded_offset + bounded_limit],
            "total": len(items),
            "offset": bounded_offset,
            "limit": bounded_limit,
            "sort": sort_key,
            "tags": sorted(tags),
            "sources": [
                {"source": name, "count": count}
                for name, count in sorted(source_counts.items())
            ],
        }

    def overview(
        self,
        history: MemeUsageHistory,
        extension_status: Any,
        gouqi_status: Any | None = None,
    ) -> dict[str, Any]:
        total = len(self.engine.memes)
        enabled = len(self.engine.available_memes())
        source_counts: dict[str, int] = {}
        tags: set[str] = set()
        for meme in self.engine.memes:
            name = self._source_of(meme)
            source_counts[name] = source_counts.get(name, 0) + 1
            tags.update(self.engine.get_tags(meme))
        return {
            "engine_version": self.engine.version,
            "trigger_prefix": str(self._config_value("trigger_prefix", "meme")),
            "total_memes": total,
            "enabled_memes": enabled,
            "disabled_memes": total - enabled,
            "sources": [
                {"source": name, "count": count}
                for name, count in sorted(source_counts.items())
            ],
            "tag_count": len(tags),
            "usage_records": len(history.records),
            "top_memes": history.meme_summaries(limit=5),
            "active_conversations": history.conversation_summaries(limit=5),
            "recent_records": [
                {
                    "key": record.key,
                    "trigger": record.trigger,
                    "platform": record.platform,
                    "session": record.session,
                    "sender_id": record.sender_id,
                    "sender_name": record.sender_name,
                    "created_at": record.created_at,
                }
                for record in history.recent(limit=5)
            ],
            "extension": {
                "installed": bool(extension_status.installed),
                "tag": extension_status.tag,
                "library_valid": bool(extension_status.library_valid),
                "resources_present": bool(extension_status.resources_present),
            },
            "gouqi_extension": {
                "installed": bool(getattr(gouqi_status, "installed", False)),
                "commit": getattr(gouqi_status, "commit", None),
                "assets_valid": bool(getattr(gouqi_status, "assets_valid", False)),
                "templates": int(getattr(gouqi_status, "templates", 0)),
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

    def _material_index(self) -> frozenset[str]:
        """List built-in material folder names with one directory scan."""
        root = self._material_root
        try:
            return frozenset(entry.name for entry in root.iterdir() if entry.is_dir())
        except OSError:
            return frozenset()

    def _has_materials(
        self,
        meme: Any,
        key: str,
        material_index: frozenset[str] | None = None,
    ) -> bool:
        if getattr(meme, "material_directory", None) is None and material_index is not None:
            return key in material_index
        try:
            return self._material_directory(key, meme=meme).is_dir()
        except (DashboardError, OSError):
            return False

    def _material_directory(self, key: str, *, meme: Any | None = None) -> Path:
        if meme is None:
            meme = self.engine.resolve(key)
        custom_directory = getattr(meme, "material_directory", None)
        if custom_directory is not None:
            directory = Path(custom_directory).resolve(strict=False)
            if self.gouqi_extension is None:
                raise DashboardError("扩展素材目录不可用。")
            root = self.gouqi_extension.assets_root.resolve(strict=False)
            if directory != root and root not in directory.parents:
                raise DashboardError("扩展素材路径无效。")
            return directory
        root = self._material_root.resolve(strict=False)
        directory = (root / key).resolve(strict=False)
        if directory != root and root not in directory.parents:
            raise DashboardError("素材路径无效。")
        return directory

    def _materials_for_meme(self, meme: Any) -> dict[str, Any]:
        directory = self._material_directory(str(meme.key), meme=meme)
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

        directory = self._material_directory(str(meme.key), meme=meme)
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
