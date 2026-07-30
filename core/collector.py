from __future__ import annotations

import asyncio
import base64
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
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


class InputCollectionError(RuntimeError):
    pass


@dataclass(slots=True)
class _MessageMedia:
    images: list[tuple[str, bytes]]
    reply_texts: list[str]
    mentioned_ids: list[str]


class ParamsCollector:
    def __init__(self, config: Any):
        self.config = config
        self._session: aiohttp.ClientSession | None = None

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

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30, connect=10, sock_read=20)
            self._session = aiohttp.ClientSession(timeout=timeout, trust_env=True)
        return self._session

    async def _download_image(self, url: str) -> bytes:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise InputCollectionError(
                f"不支持的图片地址协议: {parsed.scheme or 'unknown'}"
            )

        session = await self._get_session()
        async with session.get(url, allow_redirects=True) as response:
            response.raise_for_status()
            if (
                response.content_length
                and response.content_length > self.max_input_bytes
            ):
                raise InputCollectionError(
                    f"输入图片超过 {self.max_input_bytes // 1024 // 1024} MB 限制"
                )
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.content.iter_chunked(64 * 1024):
                size += len(chunk)
                if size > self.max_input_bytes:
                    raise InputCollectionError(
                        f"输入图片超过 {self.max_input_bytes // 1024 // 1024} MB 限制"
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

    async def get_avatar(self, user_id: str) -> bytes | None:
        if not user_id.isdigit():
            return None
        url = f"https://q4.qlogo.cn/headimg_dl?dst_uin={user_id}&spec=640"
        try:
            return await self._download_image(url)
        except (aiohttp.ClientError, InputCollectionError, asyncio.TimeoutError) as exc:
            logger.warning("[meme_forge] 获取 QQ 头像 %s 失败: %s", user_id, exc)
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
            data = await self._decode_image(source)
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
        mentioned_ids: list[str] = []
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
                    mentioned_ids.append(target_id)

        return _MessageMedia(
            images=images,
            reply_texts=reply_texts,
            mentioned_ids=list(dict.fromkeys(mentioned_ids)),
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
    ) -> None:
        user_info = await self._get_user_info(event, target_id)
        nickname = user_info[0] if user_info else target_id
        if user_info:
            options.setdefault("name", nickname)
            if user_info[1]:
                options.setdefault("gender", user_info[1])
        avatar = (
            await self.get_avatar(target_id)
            if explicit_qq or event.get_platform_name() == "aiocqhttp"
            else None
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
        if parsed.errors:
            raise InputCollectionError("；".join(parsed.errors))

        options = parsed.options
        image_name_override = str(options["name"]) if "name" in parsed.options else None
        media = await self._collect_message_media(event, options)
        images = media.images

        collected_targets: set[str] = set()
        for target_id in media.mentioned_ids:
            collected_targets.add(target_id)
            await self._append_target(
                event,
                target_id,
                images,
                options,
                explicit_qq=False,
                image_name_override=image_name_override,
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
        can_use_qq_fallback = event.get_platform_name() == "aiocqhttp"
        if (
            can_use_qq_fallback
            and len(images) < params.min_images
            and (avatar := await self.get_avatar(sender_id))
        ):
            images.append((image_name_override or sender_name, avatar))
        if (
            can_use_qq_fallback
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
