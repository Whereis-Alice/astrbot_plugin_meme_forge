from __future__ import annotations

import asyncio
import base64
import os
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse
from urllib.request import url2pathname

import aiohttp
from astrbot.api import logger
from astrbot.api import message_components as Comp
from astrbot.api.event import AstrMessageEvent

from .arguments import (
    MemeArgumentParser,
    OptionSpec,
    OptionValue,
    option_specs_from_params,
)
from .engine import MemeInputs

QQ_OFFICIAL_PLATFORMS = frozenset({"qq_official", "qq_official_webhook"})
AVATAR_DOWNLOAD_LIMIT = 2 * 1024 * 1024


class InputCollectionError(RuntimeError):
    pass


@dataclass(slots=True)
class _MessageMedia:
    images: list[tuple[str, bytes]]
    reply_texts: list[str]
    mentioned_targets: list[tuple[str, str | None]]


class ParamsCollector:
    def __init__(self, config: Any):
        self.config = config
        self._session: aiohttp.ClientSession | None = None
        self._avatar_cache: OrderedDict[str, bytes] = OrderedDict()

    def _config_value(self, key: str, default: Any) -> Any:
        try:
            return self.config.get(key, default)
        except AttributeError:
            try:
                return self.config[key]
            except (KeyError, TypeError):
                return default

    @property
    def max_input_bytes(self) -> int:
        megabytes = max(1, int(self._config_value("max_input_image_mb", 20)))
        return megabytes * 1024 * 1024

    @property
    def avatar_cache_size(self) -> int:
        return max(0, min(int(self._config_value("avatar_cache_size", 20)), 256))

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30, connect=10, sock_read=20)
            self._session = aiohttp.ClientSession(timeout=timeout, trust_env=True)
        return self._session

    async def _download_image(
        self,
        url: str,
        *,
        max_bytes: int | None = None,
    ) -> bytes:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise InputCollectionError(
                f"不支持的图片地址协议: {parsed.scheme or 'unknown'}"
            )

        size_limit = self.max_input_bytes
        if max_bytes is not None:
            size_limit = min(size_limit, max(1, max_bytes))

        session = await self._get_session()
        async with session.get(url, allow_redirects=True) as response:
            response.raise_for_status()
            if response.content_length and response.content_length > size_limit:
                raise InputCollectionError(
                    f"输入图片超过 {size_limit // 1024 // 1024} MB 限制"
                )
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.content.iter_chunked(64 * 1024):
                size += len(chunk)
                if size > size_limit:
                    raise InputCollectionError(
                        f"输入图片超过 {size_limit // 1024 // 1024} MB 限制"
                    )
                chunks.append(chunk)
            return b"".join(chunks)

    async def _decode_image(self, source: str) -> bytes:
        if source.startswith("base64://"):
            try:
                data = base64.b64decode(source[9:], validate=False)
            except (ValueError, TypeError) as exc:
                raise InputCollectionError("图片 Base64 数据无效") from exc
            if len(data) > self.max_input_bytes:
                raise InputCollectionError(
                    f"输入图片超过 {self.max_input_bytes // 1024 // 1024} MB 限制"
                )
            return data

        if source.startswith(("http://", "https://")):
            return await self._download_image(source)

        parsed = urlparse(source)
        if parsed.scheme == "file":
            if parsed.netloc not in {"", "localhost"}:
                raise InputCollectionError("不支持远程 file:// 图片地址")
            local_path = url2pathname(unquote(parsed.path))
            if (
                os.name == "nt"
                and len(local_path) >= 3
                and local_path[0] in {"/", "\\"}
                and local_path[2] == ":"
            ):
                local_path = local_path[1:]
            path = Path(local_path)
        else:
            path = Path(source)
        if not path.is_file():
            raise InputCollectionError(f"找不到输入图片: {path.name or source}")
        if path.stat().st_size > self.max_input_bytes:
            raise InputCollectionError(
                f"输入图片超过 {self.max_input_bytes // 1024 // 1024} MB 限制"
            )
        return await asyncio.to_thread(path.read_bytes)

    def _cached_avatar(self, key: str) -> bytes | None:
        capacity = self.avatar_cache_size
        if capacity == 0:
            self._avatar_cache.clear()
            return None
        while len(self._avatar_cache) > capacity:
            self._avatar_cache.popitem(last=False)
        avatar = self._avatar_cache.get(key)
        if avatar is None:
            return None
        self._avatar_cache.move_to_end(key)
        return avatar

    def _remember_avatar(self, key: str, avatar: bytes) -> None:
        capacity = self.avatar_cache_size
        if capacity == 0:
            return
        self._avatar_cache[key] = avatar
        self._avatar_cache.move_to_end(key)
        while len(self._avatar_cache) > capacity:
            self._avatar_cache.popitem(last=False)

    async def _get_cached_avatar(
        self,
        cache_key: str,
        url: str,
        description: str,
    ) -> bytes | None:
        if avatar := self._cached_avatar(cache_key):
            return avatar
        try:
            avatar = await self._download_image(
                url,
                max_bytes=AVATAR_DOWNLOAD_LIMIT,
            )
        except (aiohttp.ClientError, InputCollectionError, asyncio.TimeoutError) as exc:
            logger.warning("[meme_forge] 获取 %s 头像失败: %s", description, exc)
            return None
        if avatar:
            self._remember_avatar(cache_key, avatar)
        return avatar or None

    async def get_avatar(self, user_id: str) -> bytes | None:
        """Return a cached classic QQ avatar for a numeric QQ identifier."""
        if not user_id.isdigit():
            return None
        encoded_id = quote(user_id, safe="")
        return await self._get_cached_avatar(
            f"qq:{user_id}",
            f"https://q4.qlogo.cn/headimg_dl?dst_uin={encoded_id}&spec=640",
            f"QQ 用户 {user_id}",
        )

    async def get_qq_official_avatar(
        self,
        appid: str,
        openid: str,
    ) -> bytes | None:
        """Return an app-scoped QQ Official Bot avatar for an opaque openid."""
        appid = str(appid).strip()
        openid = str(openid).strip()
        if not appid or not openid:
            return None
        return await self._get_cached_avatar(
            f"qq_official:{appid}:{openid}",
            "https://q.qlogo.cn/qqapp/"
            f"{quote(appid, safe='')}/{quote(openid, safe='')}/0",
            f"QQ 官方用户 {openid}",
        )

    @staticmethod
    def _qq_official_appid(event: AstrMessageEvent) -> str:
        platform = getattr(getattr(event, "bot", None), "platform", None)
        appid = getattr(platform, "appid", None)
        if appid:
            return str(appid).strip()
        config = getattr(platform, "config", None)
        if isinstance(config, dict):
            return str(config.get("appid") or "").strip()
        return ""

    async def _get_event_avatar(
        self,
        event: AstrMessageEvent,
        target_id: str,
        *,
        explicit_qq: bool,
    ) -> bytes | None:
        platform_name = str(event.get_platform_name())
        if platform_name in QQ_OFFICIAL_PLATFORMS:
            appid = self._qq_official_appid(event)
            if appid:
                avatar = await self.get_qq_official_avatar(appid, target_id)
                if avatar:
                    return avatar
            if not explicit_qq:
                return None
        if explicit_qq or platform_name == "aiocqhttp":
            return await self.get_avatar(target_id)
        return None

    async def _get_user_info(
        self,
        event: AstrMessageEvent,
        target_id: str,
    ) -> tuple[str, str | None] | None:
        if event.get_platform_name() != "aiocqhttp" or not target_id.isdigit():
            return None
        try:
            user_info = await event.bot.get_stranger_info(user_id=int(target_id))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - adapter APIs have no common error base
            logger.warning("[meme_forge] 获取用户 %s 信息失败: %s", target_id, exc)
            return None
        nickname = str(user_info.get("nickname") or target_id)
        gender = user_info.get("sex")
        return nickname, str(gender) if gender is not None else None

    @staticmethod
    def _component_user_id(component: Any) -> str:
        return str(
            getattr(component, "qq", None) or getattr(component, "user_id", None) or ""
        )

    @staticmethod
    def _image_source(component: Any) -> str:
        return str(
            getattr(component, "url", None)
            or getattr(component, "path", None)
            or getattr(component, "file", None)
            or ""
        )

    async def read_image_component(self, component: Any) -> bytes:
        """Read one AstrBot image component with the configured safety limits."""
        source = self._image_source(component)
        if not source:
            raise InputCollectionError("引用消息中没有可读取的图片地址")
        return await self.read_image_source(source)

    async def read_image_source(self, source: str) -> bytes:
        """Read an adapter-provided image source with the configured safety limits."""
        return await self._decode_image(source)

    async def _read_image_component(
        self,
        component: Any,
        owner_name: str,
        options: dict[str, OptionValue],
    ) -> tuple[str, bytes] | None:
        source = self._image_source(component)
        if not source:
            return None
        try:
            data = await self.read_image_component(component)
        except InputCollectionError:
            raise
        except Exception as exc:
            raise InputCollectionError(f"读取输入图片失败: {exc}") from exc
        return str(options.get("name") or owner_name), data

    async def _collect_message_media(
        self,
        event: AstrMessageEvent,
        options: dict[str, OptionValue],
    ) -> _MessageMedia:
        images: list[tuple[str, bytes]] = []
        reply_texts: list[str] = []
        mentioned_targets: dict[str, str | None] = {}
        chain = list(event.get_messages() or [])
        sender_name = str(event.get_sender_name() or event.get_sender_id())

        # Replied media is explicit user input and must win over avatar fallback.
        for reply in (segment for segment in chain if isinstance(segment, Comp.Reply)):
            reply_name = str(
                getattr(reply, "sender_nickname", None)
                or getattr(reply, "sender_id", None)
                or sender_name
            )
            reply_has_text = False
            for segment in list(getattr(reply, "chain", None) or []):
                if isinstance(segment, Comp.Image):
                    image = await self._read_image_component(
                        segment, reply_name, options
                    )
                    if image:
                        images.append(image)
                elif isinstance(segment, Comp.Plain):
                    lines = [
                        line.strip()
                        for line in str(segment.text).splitlines()
                        if line.strip()
                    ]
                    reply_texts.extend(lines)
                    reply_has_text = reply_has_text or bool(lines)
            if not reply_has_text:
                reply_texts.extend(
                    line.strip()
                    for line in str(
                        getattr(reply, "message_str", "") or ""
                    ).splitlines()
                    if line.strip()
                )

        self_id = str(event.get_self_id())
        for segment in chain:
            if isinstance(segment, Comp.Reply):
                continue
            if isinstance(segment, Comp.Image):
                image = await self._read_image_component(segment, sender_name, options)
                if image:
                    images.append(image)
            elif isinstance(segment, Comp.At):
                target_id = self._component_user_id(segment)
                if target_id and target_id != self_id:
                    target_name = str(getattr(segment, "name", None) or "").strip()
                    previous_name = mentioned_targets.get(target_id)
                    if target_id not in mentioned_targets or (
                        not previous_name and target_name
                    ):
                        mentioned_targets[target_id] = target_name or None

        return _MessageMedia(
            images=images,
            reply_texts=reply_texts,
            mentioned_targets=list(mentioned_targets.items()),
        )

    async def _append_target(
        self,
        event: AstrMessageEvent,
        target_id: str,
        images: list[tuple[str, bytes]],
        options: dict[str, OptionValue],
        *,
        explicit_qq: bool,
        image_name_override: str | None,
        target_name: str | None = None,
    ) -> None:
        user_info = await self._get_user_info(event, target_id)
        nickname = user_info[0] if user_info else target_name or target_id
        if user_info:
            options.setdefault("name", nickname)
            if user_info[1]:
                options.setdefault("gender", user_info[1])
        avatar = await self._get_event_avatar(
            event,
            target_id,
            explicit_qq=explicit_qq,
        )
        if avatar:
            images.append((image_name_override or nickname, avatar))

    async def collect(
        self,
        event: AstrMessageEvent,
        params: Any,
        argument_text: str,
    ) -> MemeInputs:
        specs = option_specs_from_params(params)
        runtime_option_names = {spec.name for spec in specs}
        for name in ("name", "gender"):
            if name not in runtime_option_names:
                specs.append(
                    OptionSpec(
                        name=name,
                        kind="str",
                        bare_aliases=(name,),
                        flag_aliases=(name,),
                    )
                )
        parser = MemeArgumentParser(specs)
        parsed = parser.parse(argument_text)
        if event.get_platform_name() in QQ_OFFICIAL_PLATFORMS:
            remaining_texts: list[str] = []
            for text in parsed.texts:
                if text.startswith("@") and len(text) > 1:
                    parsed.target_ids.append(text[1:])
                else:
                    remaining_texts.append(text)
            parsed.texts = remaining_texts
            parsed.target_ids = list(dict.fromkeys(parsed.target_ids))
        if parsed.errors:
            raise InputCollectionError("；".join(parsed.errors))

        options = parsed.options
        image_name_override = str(options["name"]) if "name" in parsed.options else None
        media = await self._collect_message_media(event, options)
        images = media.images

        collected_targets: set[str] = set()
        for target_id, target_name in media.mentioned_targets:
            collected_targets.add(target_id)
            await self._append_target(
                event,
                target_id,
                images,
                options,
                explicit_qq=False,
                image_name_override=image_name_override,
                target_name=target_name,
            )
        for target_id in parsed.target_ids:
            if target_id in collected_targets:
                continue
            collected_targets.add(target_id)
            await self._append_target(
                event,
                target_id,
                images,
                options,
                explicit_qq=True,
                image_name_override=image_name_override,
            )

        sender_id = str(event.get_sender_id())
        sender_name = str(event.get_sender_name() or sender_id)
        self_id = str(event.get_self_id())
        platform_name = str(event.get_platform_name())
        can_use_avatar_fallback = (
            platform_name == "aiocqhttp" or platform_name in QQ_OFFICIAL_PLATFORMS
        )
        if can_use_avatar_fallback and len(images) < params.min_images:
            await self._append_target(
                event,
                sender_id,
                images,
                options,
                explicit_qq=False,
                image_name_override=image_name_override,
                target_name=sender_name,
            )
        if (
            platform_name == "aiocqhttp"
            and len(images) < params.min_images
            and (avatar := await self.get_avatar(self_id))
        ):
            images.append(("bot", avatar))
        images = images[: params.max_images]

        texts = list(parsed.texts)
        if len(texts) < params.min_texts:
            texts.extend(media.reply_texts[: params.min_texts - len(texts)])
        if len(texts) < params.min_texts:
            defaults = list(getattr(params, "default_texts", []) or [])
            texts.extend(defaults[: params.min_texts - len(texts)])
        texts = texts[: params.max_texts]

        generation_options = {
            key: value for key, value in options.items() if key in runtime_option_names
        }
        return MemeInputs(images=images, texts=texts, options=generation_options)

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._avatar_cache.clear()
