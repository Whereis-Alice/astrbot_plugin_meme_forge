from __future__ import annotations

import asyncio
import hashlib
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar

from astrbot.api import logger
from astrbot.api import message_components as Comp
from astrbot.api.event import AstrMessageEvent

from .collector import InputCollectionError, ParamsCollector


class MemeGrabError(RuntimeError):
    """Raised when no downloadable meme image can be extracted."""


@dataclass(frozen=True, slots=True)
class ExtractedMemeFile:
    path: Path
    filename: str
    media_type: str
    animated: bool


class MemeGrabber:
    """Extract images from a message without depending on a platform event class."""

    _SEND_MODE_ALIASES: ClassVar[dict[str, str]] = {
        "图片": "image",
        "image": "image",
        "文件": "file",
        "file": "file",
    }
    _IMAGE_SUFFIXES: ClassVar[set[str]] = {
        ".apng",
        ".bmp",
        ".gif",
        ".jpeg",
        ".jpg",
        ".png",
        ".webp",
    }

    def __init__(self, data_dir: Path, collector: ParamsCollector, config: Any):
        self.data_dir = data_dir
        self.collector = collector
        self.config = config

    def _config_value(self, key: str, default: Any) -> Any:
        try:
            return self.config.get(key, default)
        except AttributeError:
            try:
                return self.config[key]
            except (KeyError, TypeError):
                return default

    @property
    def max_files(self) -> int:
        return max(1, min(int(self._config_value("grabber_max_files", 8)), 20))

    @property
    def retention_seconds(self) -> int:
        minutes = max(5, int(self._config_value("grabber_retention_minutes", 60)))
        return min(minutes, 7 * 24 * 60) * 60

    @staticmethod
    def _event_group_id(event: AstrMessageEvent) -> str:
        get_group_id = getattr(event, "get_group_id", None)
        if not callable(get_group_id):
            return ""
        try:
            return str(get_group_id() or "")
        except Exception:  # noqa: BLE001 - adapters expose varied event APIs
            return ""

    def _is_allowed(self, event: AstrMessageEvent) -> bool:
        if not bool(self._config_value("grabber_enabled", True)):
            return False
        group_id = self._event_group_id(event)
        if not group_id:
            return True
        mode = str(self._config_value("grabber_list_mode", "disabled")).casefold()
        groups = {
            line.strip()
            for line in str(self._config_value("grabber_group_list", "")).splitlines()
            if line.strip()
        }
        if mode == "blacklist":
            return group_id not in groups
        if mode == "whitelist":
            return group_id in groups
        return True

    @staticmethod
    def _is_image_component(component: Any) -> bool:
        return isinstance(component, Comp.Image) or type(component).__name__ == "Image"

    @staticmethod
    def _is_reply_component(component: Any) -> bool:
        return isinstance(component, Comp.Reply) or type(component).__name__ == "Reply"

    @classmethod
    def _reply_images(cls, reply: Any) -> list[Any]:
        images: list[Any] = []
        seen: set[int] = set()
        for attribute in ("chain", "message", "origin", "content"):
            for component in list(getattr(reply, attribute, None) or []):
                identity = id(component)
                if identity in seen:
                    continue
                seen.add(identity)
                if cls._is_image_component(component):
                    images.append(component)
                elif cls._is_reply_component(component):
                    images.extend(cls._reply_images(component))
        return images

    @staticmethod
    def _raw_segments(event: AstrMessageEvent) -> list[dict[str, Any]]:
        message_obj = getattr(event, "message_obj", None)
        raw_message = getattr(message_obj, "raw_message", None)
        if isinstance(raw_message, dict):
            raw_message = raw_message.get("message", raw_message.get("messages", []))
        return [segment for segment in raw_message or [] if isinstance(segment, dict)]

    @staticmethod
    def _onebot_action(event: AstrMessageEvent) -> Any | None:
        if str(event.get_platform_name()) != "aiocqhttp":
            return None
        api = getattr(getattr(event, "bot", None), "api", None)
        action = getattr(api, "call_action", None)
        return action if callable(action) else None

    async def _read_onebot_segments(
        self,
        event: AstrMessageEvent,
        segments: list[dict[str, Any]],
    ) -> list[bytes]:
        action = self._onebot_action(event)
        if action is None:
            return []

        result: list[bytes] = []
        for segment in segments:
            if str(segment.get("type", "")).casefold() not in {"image", "mface"}:
                continue
            data = segment.get("data")
            if not isinstance(data, dict):
                continue
            source = data.get("url")
            if not source and data.get("file"):
                try:
                    image = await action("get_image", file=data["file"])
                    source = image.get("file") if isinstance(image, dict) else None
                except Exception as exc:  # noqa: BLE001 - adapter action errors vary
                    logger.warning("[meme_forge] 读取 QQ 表情文件失败: %s", exc)
                    continue
            if not source:
                continue
            try:
                result.append(await self.collector.read_image_source(str(source)))
            except (InputCollectionError, OSError, asyncio.TimeoutError) as exc:
                logger.warning("[meme_forge] 读取 QQ 表情图片失败: %s", exc)
        return result

    async def _read_reply_onebot_fallback(
        self,
        event: AstrMessageEvent,
        reply: Any,
    ) -> list[bytes]:
        action = self._onebot_action(event)
        message_id = getattr(reply, "id", None) or getattr(reply, "message_id", None)
        if action is None or not message_id:
            return []
        try:
            response = await action("get_msg", message_id=message_id)
        except Exception as exc:  # noqa: BLE001 - adapter action errors vary
            logger.warning("[meme_forge] 获取 QQ 被引用消息失败: %s", exc)
            return []
        segments = response.get("message", []) if isinstance(response, dict) else []
        return await self._read_onebot_segments(event, list(segments or []))

    async def _collect_image_bytes(self, event: AstrMessageEvent) -> list[bytes]:
        image_components: list[Any] = []
        replies: list[Any] = []
        for component in list(event.get_messages() or []):
            if self._is_image_component(component):
                image_components.append(component)
            elif self._is_reply_component(component):
                replies.append(component)
                image_components.extend(self._reply_images(component))

        images: list[bytes] = []
        for component in image_components[: self.max_files]:
            try:
                images.append(await self.collector.read_image_component(component))
            except (InputCollectionError, OSError, asyncio.TimeoutError) as exc:
                logger.warning("[meme_forge] 读取待提取图片失败: %s", exc)

        if len(images) < self.max_files:
            for reply in replies:
                if self._reply_images(reply):
                    continue
                images.extend(await self._read_reply_onebot_fallback(event, reply))
                if len(images) >= self.max_files:
                    break

        if len(images) < self.max_files and not image_components:
            images.extend(await self._read_onebot_segments(event, self._raw_segments(event)))

        unique: list[bytes] = []
        seen_hashes: set[str] = set()
        for image in images:
            digest = hashlib.sha256(image).hexdigest()
            if digest not in seen_hashes:
                seen_hashes.add(digest)
                unique.append(image)
            if len(unique) >= self.max_files:
                break
        return unique

    @staticmethod
    def _detect_media(data: bytes) -> tuple[str, str, bool]:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return ".png", "image/png", b"acTL" in data[: 1024 * 1024]
        if data.startswith((b"GIF87a", b"GIF89a")):
            return ".gif", "image/gif", True
        if data.startswith(b"\xff\xd8\xff"):
            return ".jpg", "image/jpeg", False
        if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return ".webp", "image/webp", True
        if data.startswith(b"BM"):
            return ".bmp", "image/bmp", False
        return ".bin", "application/octet-stream", False

    def _filename(self, suffix: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"meme_{timestamp}_{uuid.uuid4().hex[:10]}{suffix}"

    async def _materialize(self, data: bytes) -> ExtractedMemeFile:
        suffix, media_type, animated = self._detect_media(data)
        filename = self._filename(suffix)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        target = self.data_dir / filename
        await asyncio.to_thread(target.write_bytes, data)
        return ExtractedMemeFile(
            path=target,
            filename=filename,
            media_type=media_type,
            animated=animated,
        )

    @classmethod
    def command_send_mode(cls, value: str | None) -> str | None:
        """Map a user-facing extraction mode to the internal send mode."""

        normalized = str(value or "").strip().casefold()
        if not normalized:
            return None
        return cls._SEND_MODE_ALIASES.get(normalized)

    def build_components(
        self,
        files: list[ExtractedMemeFile],
        *,
        send_mode: str | None = None,
    ) -> list[Any]:
        selected_mode = send_mode or str(
            self._config_value("grabber_send_mode", "file")
        ).casefold()
        components: list[Any] = []
        for item in files:
            if selected_mode == "image" and not item.animated:
                components.append(Comp.Image.fromFileSystem(str(item.path)))
            else:
                components.append(Comp.File(file=str(item.path), name=item.filename))
        return components

    async def extract(self, event: AstrMessageEvent) -> list[ExtractedMemeFile]:
        if not bool(self._config_value("grabber_enabled", True)):
            raise MemeGrabError("表情提取功能当前已关闭。")
        if not self._is_allowed(event):
            raise MemeGrabError("当前群聊未获准使用表情提取功能。")

        await self.cleanup_expired()
        images = await self._collect_image_bytes(event)
        if not images:
            raise MemeGrabError("没有找到可提取的图片或 QQ 表情。")

        files: list[ExtractedMemeFile] = []
        for image in images:
            try:
                files.append(await self._materialize(image))
            except OSError as exc:
                logger.warning("[meme_forge] 写入提取表情失败: %s", exc)
        if not files:
            raise MemeGrabError("表情已找到，但无法写入插件临时目录。")
        return files

    def _cleanup_sync(self, cutoff: float | None) -> int:
        if not self.data_dir.is_dir():
            return 0
        removed = 0
        for candidate in self.data_dir.iterdir():
            if not candidate.is_file() or candidate.suffix.casefold() not in self._IMAGE_SUFFIXES | {".bin"}:
                continue
            if cutoff is not None and candidate.stat().st_mtime >= cutoff:
                continue
            try:
                candidate.unlink()
                removed += 1
            except OSError as exc:
                logger.warning("[meme_forge] 清理提取文件失败 %s: %s", candidate.name, exc)
        return removed

    async def cleanup_expired(self) -> int:
        return await asyncio.to_thread(
            self._cleanup_sync,
            time.time() - self.retention_seconds,
        )

    async def cleanup_all(self) -> int:
        return await asyncio.to_thread(self._cleanup_sync, None)

    @staticmethod
    def safe_material_name(name: str) -> str:
        """Validate a material-relative path before it is resolved on disk."""
        path = PurePosixPath(name)
        if not name or path.is_absolute() or ".." in path.parts:
            raise MemeGrabError("素材文件名无效。")
        normalized = re.sub(r"/+", "/", path.as_posix()).strip("/")
        if not normalized or normalized.startswith("../"):
            raise MemeGrabError("素材文件名无效。")
        return normalized
