from __future__ import annotations

import asyncio
import base64
import mimetypes
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar

from . import pjsk, pjsk_catalog
from .arguments import option_specs_from_params
from .engine import MemeEngine, MemeEngineError
from .extensions import MemeEmojiExtensionManager
from .gouqi_extension import GouqiExtensionManager
from .history import MemeUsageHistory
from .imaging import ImageRenderError
from .maker import (
    ALIGNMENTS,
    FIT_MODES,
    MAX_ASSET_BYTES,
    MAX_CANVAS,
    MAX_CANVAS_PIXELS,
    MAX_IMAGE_SLOTS,
    MAX_KEYWORDS,
    MAX_SLOTS,
    MAX_TEMPLATES,
    MAX_TEXT_SLOTS,
    MIN_CANVAS,
    VERTICAL_ALIGNMENTS,
    MakerError,
    MakerMeme,
    MakerStore,
    MakerTemplate,
    caption_template_payload,
    decode_data_url,
)
from .pjsk_command import PjskArguments, PjskCommandError, coerce_options

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_PLUGIN_VERSION: str | None = None
#: Literal token the chat parser turns back into a line break.
_LINE_BREAK_TOKEN = r"\n"


def plugin_version() -> str:
    """Return the plugin version declared in metadata.yaml (read once, cached).

    Parsed with a regex instead of a YAML loader so the Dashboard never gains a
    dependency just to display a version string.
    """
    global _PLUGIN_VERSION
    if _PLUGIN_VERSION is None:
        try:
            text = (_PLUGIN_ROOT / "metadata.yaml").read_text(encoding="utf-8")
        except OSError:
            text = ""
        match = re.search(r"^version:[ \t]*[\"']?([^\"'\s#]+)", text, re.MULTILINE)
        _PLUGIN_VERSION = match.group(1) if match else "unknown"
    return _PLUGIN_VERSION


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
        maker_store: MakerStore | None = None,
        pjsk_assets: Any | None = None,
    ) -> None:
        self.engine = engine
        self.extension = extension
        self.gouqi_extension = gouqi_extension
        self.maker_store = maker_store
        self.pjsk_assets = pjsk_assets
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
        pjsk_status: Any | None = None,
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
            "plugin_version": plugin_version(),
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
            "maker": self.maker_overview(),
            "pjsk": self.pjsk_overview(pjsk_status),
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

    def _custom_material_roots(self) -> list[Path]:
        """Roots that extension memes may expose their own material folders under."""
        roots: list[Path] = []
        if self.gouqi_extension is not None:
            roots.append(self.gouqi_extension.assets_root.resolve(strict=False))
        if self.maker_store is not None:
            roots.append(self.maker_store.root.resolve(strict=False))
        return roots

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
            allowed = self._custom_material_roots()
            if not allowed:
                raise DashboardError("扩展素材目录不可用。")
            if not any(
                directory == root or root in directory.parents for root in allowed
            ):
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

    # ------------------------------------------------------------------
    # Meme Maker (user-authored templates)
    # ------------------------------------------------------------------

    @property
    def maker_enabled(self) -> bool:
        if self.maker_store is None:
            return False
        return bool(self._config_value("maker_enabled", True))

    def _require_maker(self) -> MakerStore:
        if self.maker_store is None or not self.maker_enabled:
            raise DashboardError("表情包工作台未启用，请在插件配置中开启 maker_enabled。")
        return self.maker_store

    @staticmethod
    def maker_limits() -> dict[str, Any]:
        return {
            "templates": MAX_TEMPLATES,
            "slots": MAX_SLOTS,
            "image_slots": MAX_IMAGE_SLOTS,
            "text_slots": MAX_TEXT_SLOTS,
            "keywords": MAX_KEYWORDS,
            "asset_mb": MAX_ASSET_BYTES // 1024 // 1024,
            "canvas": {
                "min": MIN_CANVAS,
                "max": MAX_CANVAS,
                "max_pixels": MAX_CANVAS_PIXELS,
            },
            "fit_modes": list(FIT_MODES),
            "alignments": list(ALIGNMENTS),
            "vertical_alignments": list(VERTICAL_ALIGNMENTS),
        }

    def maker_overview(self) -> dict[str, Any]:
        total = len(self.maker_store.keys()) if self.maker_store is not None else 0
        return {
            "enabled": self.maker_enabled,
            "total": total,
            "limits": self.maker_limits(),
        }

    def _reserved_maker_keys(self) -> set[str]:
        """Keys already owned by non-maker memes, so drafts cannot shadow them."""
        reserved: set[str] = set()
        for meme in self.engine.memes:
            if self._source_of(meme) == "maker":
                continue
            key = str(getattr(meme, "key", "")).strip()
            if key:
                reserved.add(key)
        return reserved

    def _asset_data_url(
        self,
        store: MakerStore,
        template: MakerTemplate,
        name: str | None,
    ) -> str | None:
        path = store.asset_path(template, name)
        if path is None:
            return None
        try:
            if path.stat().st_size > self.max_preview_bytes:
                return None
            data = path.read_bytes()
        except OSError:
            return None
        media_type = mimetypes.guess_type(path.name)[0] or self._guess_media_type(data)
        return self._data_url(data, media_type)

    def _template_summary(self, store: MakerStore, template: MakerTemplate) -> dict[str, Any]:
        summary = template.summary()
        summary["has_base"] = store.asset_path(template, template.base) is not None
        summary["has_overlay"] = store.asset_path(template, template.overlay) is not None
        summary["loaded"] = isinstance(self.engine.resolve(template.key), MakerMeme)
        return summary

    def maker_templates(self) -> dict[str, Any]:
        store = self._require_maker()
        items = [self._template_summary(store, template) for template in store.templates()]
        return {
            "items": items,
            "total": len(items),
            "limits": self.maker_limits(),
        }

    def maker_template(self, key: str) -> dict[str, Any]:
        store = self._require_maker()
        try:
            template = store.load(key)
        except MakerError as exc:
            raise DashboardError(str(exc)) from exc
        item = self._template_summary(store, template)
        item["base_data_url"] = self._asset_data_url(store, template, template.base)
        item["overlay_data_url"] = self._asset_data_url(store, template, template.overlay)
        return {"item": item, "limits": self.maker_limits()}

    def maker_scaffold(
        self,
        key: str,
        keywords: Any,
        *,
        width: int = 640,
        height: int = 640,
        title: str = "",
        with_image_slot: bool = False,
    ) -> dict[str, Any]:
        """Return a ready-to-edit bottom-caption draft for the workbench."""
        self._require_maker()
        try:
            bounded_width = max(MIN_CANVAS, min(int(width), MAX_CANVAS))
            bounded_height = max(MIN_CANVAS, min(int(height), MAX_CANVAS))
        except (TypeError, ValueError) as exc:
            raise DashboardError("画布尺寸无效。") from exc
        words: Any = keywords if isinstance(keywords, str) else list(keywords or [])
        try:
            return {
                "draft": caption_template_payload(
                    str(key or "").strip() or "my_meme",
                    words,
                    width=bounded_width,
                    height=bounded_height,
                    title=title,
                    with_image_slot=with_image_slot,
                )
            }
        except MakerError as exc:
            raise DashboardError(str(exc)) from exc

    def maker_save(
        self,
        payload: dict[str, Any],
        *,
        base_data: bytes | None = None,
        overlay_data: bytes | None = None,
        remove_base: bool = False,
        remove_overlay: bool = False,
    ) -> dict[str, Any]:
        store = self._require_maker()
        try:
            template = store.save(
                payload,
                base_data=base_data,
                overlay_data=overlay_data,
                remove_base=remove_base,
                remove_overlay=remove_overlay,
                reserved_keys=self._reserved_maker_keys(),
            )
        except MakerError as exc:
            raise DashboardError(str(exc)) from exc
        except OSError as exc:
            raise DashboardError(f"模板写入失败：{exc}") from exc
        return {"item": self._template_summary(store, template)}

    def maker_delete(self, key: str) -> dict[str, Any]:
        store = self._require_maker()
        try:
            removed = store.delete(key)
        except MakerError as exc:
            raise DashboardError(str(exc)) from exc
        return {"key": removed}

    @staticmethod
    def decode_upload(value: Any) -> bytes:
        """Decode one Dashboard image upload, mapping errors to DashboardError."""
        try:
            return decode_data_url(value)
        except MakerError as exc:
            raise DashboardError(str(exc)) from exc

    async def maker_preview(
        self,
        payload: dict[str, Any],
        *,
        base_data: bytes | None = None,
        overlay_data: bytes | None = None,
        remove_base: bool = False,
        remove_overlay: bool = False,
    ) -> dict[str, str]:
        """Render an unsaved draft in a scratch directory so editing stays safe."""
        store = self._require_maker()
        try:
            async with self._preview_lock:
                image = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._render_draft,
                        store,
                        payload,
                        base_data,
                        overlay_data,
                        remove_base,
                        remove_overlay,
                    ),
                    timeout=30,
                )
        except MakerError as exc:
            raise DashboardError(str(exc)) from exc
        except ImageRenderError as exc:
            raise DashboardError(f"预览渲染失败：{exc}") from exc
        except asyncio.TimeoutError as exc:
            raise DashboardError("预览渲染超时，请缩小画布或减少图层。") from exc
        except OSError as exc:
            raise DashboardError(f"预览渲染失败：{exc}") from exc
        if len(image) > self.max_preview_bytes:
            raise DashboardError(
                f"预览图片超过 {self.max_preview_bytes // 1024 // 1024} MB 限制。"
            )
        media_type = self._guess_media_type(image)
        return {"media_type": media_type, "data_url": self._data_url(image, media_type)}

    @staticmethod
    def _render_draft(
        store: MakerStore,
        payload: dict[str, Any],
        base_data: bytes | None,
        overlay_data: bytes | None,
        remove_base: bool,
        remove_overlay: bool,
    ) -> bytes:
        draft = dict(payload or {})
        if not str(draft.get("key") or "").strip():
            draft["key"] = "draft_preview"
        base = base_data
        overlay = overlay_data
        if base is None or overlay is None:
            try:
                saved = store.load(str(draft["key"]))
            except MakerError:
                saved = None
            if saved is not None:
                if base is None and not remove_base:
                    path = store.asset_path(saved, saved.base)
                    base = path.read_bytes() if path is not None else None
                if overlay is None and not remove_overlay:
                    path = store.asset_path(saved, saved.overlay)
                    overlay = path.read_bytes() if path is not None else None
        with tempfile.TemporaryDirectory(prefix="meme-forge-draft-") as scratch_root:
            scratch = MakerStore(Path(scratch_root))
            scratch.ensure_root()
            template = scratch.save(draft, base_data=base, overlay_data=overlay)
            return MakerMeme(template, scratch).generate_preview()
    # ------------------------------------------------------------ PJSK 表情工坊

    @property
    def pjsk_enabled(self) -> bool:
        if self.pjsk_assets is None:
            return False
        return bool(self._config_value("pjsk_enabled", True))

    def _require_pjsk(self) -> Any:
        if self.pjsk_assets is None or not self.pjsk_enabled:
            raise DashboardError("PJSK 表情工坊未启用，请在插件配置中开启 pjsk_enabled。")
        return self.pjsk_assets

    def pjsk_output_scale(self) -> int:
        try:
            scale = int(self._config_value("pjsk_output_scale", 2))
        except (TypeError, ValueError):
            scale = 2
        return max(1, min(pjsk.MAX_OUTPUT_SCALE, scale))

    @staticmethod
    def pjsk_limits() -> dict[str, Any]:
        """Bounds the workbench sliders share with the chat argument parser."""
        return {
            "canvas": {
                "width": pjsk_catalog.CANVAS_WIDTH,
                "height": pjsk_catalog.CANVAS_HEIGHT,
            },
            "rotate": [-10, 10],
            "font_size": [pjsk.MIN_FONT_SIZE, pjsk.MAX_FONT_SIZE],
            "line_spacing": [pjsk.MIN_LINE_SPACING, pjsk.MAX_LINE_SPACING],
            "scale": [1, pjsk.MAX_OUTPUT_SCALE],
            "text_lines": pjsk.MAX_TEXT_LINES,
            "text_length": pjsk.MAX_TEXT_LENGTH,
        }

    def pjsk_overview(self, status: Any | None = None) -> dict[str, Any]:
        """Header block for the Page; the caller stats the artwork off-thread."""
        return {
            "enabled": self.pjsk_enabled,
            "characters": len(pjsk_catalog.characters()),
            "stickers": pjsk_catalog.IMAGE_COUNT,
            "installed": bool(getattr(status, "installed", False)),
            "ready": bool(getattr(status, "ready", False)),
            "images": int(getattr(status, "images", 0) or 0),
            "expected_images": pjsk_catalog.IMAGE_COUNT,
        }

    def _pjsk_status_payload(self, status: Any) -> dict[str, Any]:
        manager = self.pjsk_assets
        return {
            "enabled": self.pjsk_enabled,
            "installed": bool(getattr(status, "installed", False)),
            "ready": bool(getattr(status, "ready", False)),
            "verified": bool(getattr(status, "verified", False)),
            "images": int(getattr(status, "images", 0) or 0),
            "expected_images": pjsk_catalog.IMAGE_COUNT,
            "image_bytes": int(getattr(status, "image_bytes", 0) or 0),
            "expected_image_bytes": pjsk_catalog.IMAGE_BYTES,
            "font_installed": bool(getattr(status, "font_installed", False)),
            "font_bytes": int(getattr(manager, "FONT_BYTES", 0) or 0),
            "installed_at": getattr(status, "installed_at", None),
            "commit": getattr(status, "commit", None),
            "font_commit": getattr(status, "font_commit", None),
            "sticker_repository": getattr(manager, "STICKER_REPOSITORY", None),
            "sticker_license": getattr(manager, "STICKER_LICENSE", None),
            "font_repository": getattr(manager, "FONT_REPOSITORY", None),
            "font_license": getattr(manager, "FONT_LICENSE", None),
            "install_command": "/sk素材安装 确认",
        }

    async def pjsk_status(self) -> dict[str, Any]:
        """Report artwork readiness plus the provenance shown in the Page."""
        manager = self._require_pjsk()
        try:
            status = await asyncio.to_thread(manager.status)
        except OSError as exc:
            raise DashboardError(f"读取 PJSK 素材状态失败：{exc}") from exc
        return {
            "status": self._pjsk_status_payload(status),
            "limits": self.pjsk_limits(),
            "output_scale": self.pjsk_output_scale(),
        }

    def pjsk_catalog(self) -> dict[str, Any]:
        """Full character and sticker index, so the picker filters locally."""
        self._require_pjsk()
        characters = [
            {
                "key": character.key,
                "name": character.name_zh,
                "display_name": character.display_name,
                "color": character.color,
                "aliases": list(character.aliases),
                "first_index": character.first_index,
                "last_index": character.last_index,
                "count": character.count,
                "range_label": character.range_label,
            }
            for character in pjsk_catalog.characters()
        ]
        items = [
            {
                "index": sticker.index,
                "local_index": sticker.local_index,
                "character": sticker.character.key,
                "name": sticker.name,
                "label": sticker.label,
                "default_text": sticker.default_text,
                "x": sticker.x,
                "y": sticker.y,
                "rotate": sticker.rotate,
                "font_size": sticker.font_size,
            }
            for sticker in pjsk_catalog.stickers()
        ]
        return {
            "characters": characters,
            "items": items,
            "total": len(items),
            "limits": self.pjsk_limits(),
            "output_scale": self.pjsk_output_scale(),
        }

    @staticmethod
    def _pjsk_sticker(index: Any) -> Any:
        """Resolve a 序号 or 角色+编号 token into exactly one sticker."""
        text = str("" if index is None else index).strip()
        if not text:
            raise DashboardError("需要提供 PJSK 序号。")
        selection = pjsk_catalog.parse_selector(text)
        sticker = None if selection is None else selection.sticker
        if sticker is None:
            raise DashboardError(f"没有找到 PJSK 序号「{text}」。")
        return sticker

    @staticmethod
    def _pjsk_read(path: Path) -> bytes:
        if not path.is_file():
            raise DashboardError(
                "PJSK 素材还没安装，请管理员先执行 /sk素材安装 确认。"
            )
        return path.read_bytes()

    async def pjsk_sticker(self, index: Any) -> dict[str, Any]:
        """Return one untouched base artwork for the workbench preview."""
        manager = self._require_pjsk()
        sticker = self._pjsk_sticker(index)
        path = manager.image_path(sticker.image)
        try:
            data = await asyncio.to_thread(self._pjsk_read, path)
        except OSError as exc:
            raise DashboardError(f"读取 PJSK 底图失败：{exc}") from exc
        if len(data) > self.max_preview_bytes:
            raise DashboardError(
                f"底图超过 {self.max_preview_bytes // 1024 // 1024} MB 限制。"
            )
        media_type = self._guess_media_type(data)
        return {
            "index": sticker.index,
            "label": sticker.label,
            "media_type": media_type,
            "data_url": self._data_url(data, media_type),
        }

    @staticmethod
    def _pjsk_command(sticker: Any, text: str, options: PjskArguments) -> str:
        """Chat command that reproduces the draft, offered for copying."""
        parts = ["/sk", str(sticker.index)]
        caption = pjsk.normalise_text(text)
        if caption:
            parts.append(caption.replace("\n", _LINE_BREAK_TOKEN))
        pairs = (
            ("-x", options.x),
            ("-y", options.y),
            ("-r", options.rotate),
            ("-s", options.font_size),
            ("-l", options.line_spacing),
        )
        for flag, value in pairs:
            if value is not None:
                parts.append(f"{flag} {value:g}")
        if options.curve:
            parts.append("-c")
        if options.scale is not None:
            parts.append(f"--scale {options.scale}")
        return " ".join(parts)

    @staticmethod
    def _render_pjsk_draft(
        sticker: Any,
        text: str,
        image_path: Path,
        font_path: Path,
        options: dict[str, Any],
    ) -> tuple[bytes, dict[str, Any]]:
        """Render one draft and report the geometry that was actually used."""
        if not image_path.is_file():
            raise DashboardError(
                "PJSK 素材还没安装，请管理员先执行 /sk素材安装 确认。"
            )
        geometry = {key: value for key, value in options.items() if key != "scale"}
        layout = pjsk.resolve_layout(sticker, text, font_path=font_path, **geometry)
        image = pjsk.render_sticker(
            sticker,
            text,
            image_path=image_path,
            font_path=font_path,
            **options,
        )
        return image, {
            "lines": list(layout.lines),
            "x": round(layout.x, 2),
            "y": round(layout.y, 2),
            "rotate": round(layout.rotate, 2),
            "font_size": layout.font_size,
            "line_spacing": round(layout.line_spacing, 2),
            "curve": layout.curve,
        }

    async def pjsk_render(self, payload: Any) -> dict[str, Any]:
        """Render one workbench draft without sending it to a chat."""
        manager = self._require_pjsk()
        source = dict(payload or {})
        sticker = self._pjsk_sticker(source.get("index"))
        try:
            options = coerce_options(source)
        except PjskCommandError as exc:
            raise DashboardError(str(exc)) from exc
        render_options = options.render_options()
        if render_options.get("scale") is None:
            render_options["scale"] = self.pjsk_output_scale()
        text = str(source.get("text") or "")
        try:
            async with self._preview_lock:
                image, layout = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._render_pjsk_draft,
                        sticker,
                        text,
                        manager.image_path(sticker.image),
                        manager.font_path,
                        render_options,
                    ),
                    timeout=30,
                )
        except ImageRenderError as exc:
            raise DashboardError(f"预览渲染失败：{exc}") from exc
        except asyncio.TimeoutError as exc:
            raise DashboardError("预览渲染超时，请减少文字或降低输出倍数。") from exc
        except OSError as exc:
            raise DashboardError(f"预览渲染失败：{exc}") from exc
        if len(image) > self.max_preview_bytes:
            raise DashboardError(
                f"预览图片超过 {self.max_preview_bytes // 1024 // 1024} MB 限制。"
            )
        media_type = self._guess_media_type(image)
        return {
            "index": sticker.index,
            "label": sticker.label,
            "character": sticker.character.key,
            "layout": layout,
            "command": self._pjsk_command(sticker, text, options),
            "media_type": media_type,
            "data_url": self._data_url(image, media_type),
        }
