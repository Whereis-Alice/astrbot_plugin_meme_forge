from __future__ import annotations

import asyncio
import importlib
import io
import os
import sys
from dataclasses import dataclass
from typing import Any

import meme_generator as imported_meme_generator
from astrbot.api import logger

from .arguments import OptionValue, format_option_spec, option_specs_from_params


class MemeEngineError(RuntimeError):
    pass


class MemeGenerationError(MemeEngineError):
    pass


@dataclass(frozen=True, slots=True)
class MemeMatch:
    meme: Any
    trigger: str
    argument_text: str


@dataclass(frozen=True, slots=True)
class MemeInputs:
    images: list[tuple[str, bytes]]
    texts: list[str]
    options: dict[str, OptionValue]


class MemeEngine:
    def __init__(self, config: Any):
        self.config = config
        self.module: Any = imported_meme_generator
        self.memes: list[Any] = []
        self._by_key: dict[str, Any] = {}
        self._trigger_map: dict[str, Any] = {}
        self._sorted_triggers: list[str] = []

    @property
    def version(self) -> str:
        get_version = getattr(self.module, "get_version", None)
        if callable(get_version):
            try:
                return str(get_version())
            except (RuntimeError, TypeError, ValueError) as exc:
                logger.debug("[meme_forge] 无法读取生成器版本: %s", exc)
        return "unknown"

    def _config_value(self, key: str, default: Any) -> Any:
        try:
            return self.config.get(key, default)
        except AttributeError:
            try:
                return self.config[key]
            except (KeyError, TypeError):
                return default

    @staticmethod
    def _module_is_ready(module: Any) -> bool:
        return callable(getattr(module, "get_memes", None))

    def _recover_module(self) -> Any:
        if self._module_is_ready(self.module):
            return self.module

        # AstrBot dependency recovery can leave a temporary namespace module in
        # sys.modules. Reload only the package root after pip has completed.
        importlib.invalidate_caches()
        sys.modules.pop("meme_generator", None)
        module = importlib.import_module("meme_generator")
        if not self._module_is_ready(module):
            location = getattr(module, "__file__", None) or "unknown location"
            raise MemeEngineError(
                f"meme_generator API 不完整 ({location})，请重装 meme_generator>=0.2.3"
            )
        self.module = module
        return module

    async def initialize(self) -> None:
        self._recover_module()
        await asyncio.to_thread(self.reload_memes)

    @staticmethod
    def get_info(meme: Any) -> Any | None:
        return getattr(meme, "info", None)

    @classmethod
    def get_keywords(cls, meme: Any) -> list[str]:
        info = cls.get_info(meme)
        values = (
            getattr(info, "keywords", [])
            if info is not None
            else getattr(meme, "keywords", [])
        )
        return [str(value) for value in values if str(value).strip()]

    @classmethod
    def get_params(cls, meme: Any) -> Any:
        info = cls.get_info(meme)
        if info is not None and hasattr(info, "params"):
            return info.params
        return meme.params_type

    @classmethod
    def get_tags(cls, meme: Any) -> list[str]:
        info = cls.get_info(meme)
        values = (
            getattr(info, "tags", []) if info is not None else getattr(meme, "tags", [])
        )
        return sorted(str(value) for value in values)

    def _custom_aliases(self) -> dict[str, str]:
        raw = self._config_value("keyword_aliases", []) or []
        aliases: dict[str, str] = {}
        if isinstance(raw, dict):
            items = raw.items()
        elif isinstance(raw, list):
            items = (
                (item.get("alias", ""), item.get("original", ""))
                for item in raw
                if isinstance(item, dict)
            )
        else:
            return aliases

        for alias, original in items:
            alias_text = str(alias).strip()
            original_text = str(original).strip()
            if alias_text and original_text:
                aliases[alias_text] = original_text
        return aliases

    def reload_memes(self) -> None:
        get_memes = self._recover_module().get_memes
        memes = list(get_memes())

        by_key: dict[str, Any] = {}
        trigger_map: dict[str, Any] = {}
        for meme in memes:
            key = str(getattr(meme, "key", "")).strip()
            if not key:
                continue
            by_key[key] = meme
            trigger_map.setdefault(key, meme)
            for keyword in self.get_keywords(meme):
                existing = trigger_map.setdefault(keyword, meme)
                if existing is not meme:
                    logger.warning(
                        "[meme_forge] 重复触发词 %s，保留 meme %s",
                        keyword,
                        getattr(existing, "key", "unknown"),
                    )

        for alias, original in self._custom_aliases().items():
            target = trigger_map.get(original) or by_key.get(original)
            if target is None:
                logger.warning(
                    "[meme_forge] 忽略无效关键词别名 %s -> %s", alias, original
                )
                continue
            trigger_map[alias] = target

        self.memes = list(by_key.values())
        self._by_key = by_key
        self._trigger_map = trigger_map
        self._sorted_triggers = sorted(
            trigger_map, key=lambda value: (-len(value), value)
        )
        logger.info(
            "[meme_forge] 已加载 %d 个 meme、%d 个触发词 (meme_generator %s)",
            len(self.memes),
            len(self._trigger_map),
            self.version,
        )

    def _refresh_aliases(self) -> None:
        # Configuration can be edited in WebUI without reloading the plugin.
        base: dict[str, Any] = {}
        for meme in self.memes:
            base[str(meme.key)] = meme
            for keyword in self.get_keywords(meme):
                base.setdefault(keyword, meme)
        for alias, original in self._custom_aliases().items():
            target = base.get(original) or self._by_key.get(original)
            if target is not None:
                base[alias] = target
        self._trigger_map = base
        self._sorted_triggers = sorted(base, key=lambda value: (-len(value), value))

    def match(self, text: str, *, fuzzy: bool = False) -> MemeMatch | None:
        self._refresh_aliases()
        normalized = text.strip()
        if not normalized:
            return None

        if fuzzy:
            matches: list[tuple[int, int, str]] = []
            for trigger in self._sorted_triggers:
                position = normalized.find(trigger)
                if position >= 0:
                    matches.append((position, -len(trigger), trigger))
            if not matches:
                return None
            position, _, trigger = min(matches)
            argument_text = (
                normalized[:position] + " " + normalized[position + len(trigger) :]
            ).strip()
        else:
            trigger = next(
                (
                    candidate
                    for candidate in self._sorted_triggers
                    if normalized == candidate
                    or (
                        normalized.startswith(candidate)
                        and normalized[len(candidate) : len(candidate) + 1].isspace()
                    )
                ),
                "",
            )
            if not trigger:
                return None
            argument_text = normalized[len(trigger) :].strip()

        return MemeMatch(
            meme=self._trigger_map[trigger],
            trigger=trigger,
            argument_text=argument_text,
        )

    def resolve(self, name: str) -> Any | None:
        self._refresh_aliases()
        return self._by_key.get(name) or self._trigger_map.get(name)

    def canonical_key(self, name: str) -> str | None:
        meme = self.resolve(name)
        return str(meme.key) if meme is not None else None

    def is_disabled(self, meme: Any) -> bool:
        disabled = set(self._config_value("disabled_memes", []) or [])
        key = str(getattr(meme, "key", ""))
        if key in disabled:
            return True
        if any(keyword in disabled for keyword in self.get_keywords(meme)):
            return True
        return any(self.resolve(str(value)) is meme for value in disabled)

    def format_info(self, meme: Any) -> str:
        params = self.get_params(meme)
        lines = [f"名称: {meme.key}"]
        keywords = self.get_keywords(meme)
        if keywords:
            lines.append("关键词: " + "、".join(keywords))
        lines.append(
            f"图片: {params.min_images} 张"
            if params.min_images == params.max_images
            else f"图片: {params.min_images}~{params.max_images} 张"
        )
        lines.append(
            f"文本: {params.min_texts} 段"
            if params.min_texts == params.max_texts
            else f"文本: {params.min_texts}~{params.max_texts} 段"
        )
        if getattr(params, "default_texts", None):
            lines.append("默认文本: " + " / ".join(params.default_texts))
        specs = option_specs_from_params(params)
        if specs:
            lines.append("参数:")
            lines.extend(f"- {format_option_spec(spec)}" for spec in specs)
        tags = self.get_tags(meme)
        if tags:
            lines.append("标签: " + "、".join(tags))
        return "\n".join(lines)

    @staticmethod
    def _unwrap_result(result: Any, action: str) -> bytes:
        if isinstance(result, io.BytesIO):
            return result.getvalue()
        if isinstance(result, (bytes, bytearray, memoryview)):
            return bytes(result)

        if all(hasattr(result, attr) for attr in ("min", "max", "actual")):
            raise MemeGenerationError(
                f"{action}参数数量不符：需要 {result.min}~{result.max}，实际 {result.actual}"
            )
        for attr in ("feedback", "error", "path"):
            detail = getattr(result, attr, None)
            if detail:
                if attr == "path":
                    raise MemeGenerationError(
                        f"{action}缺少资源 {detail}，请执行 /meme工坊资源检查"
                    )
                raise MemeGenerationError(f"{action}失败：{detail}")
        if type(result).__name__ == "TextOverLength":
            text = str(getattr(result, "text", ""))
            preview = text if len(text) <= 80 else text[:77] + "..."
            raise MemeGenerationError(f"{action}文本过长：{preview}")
        raise MemeGenerationError(f"{action}失败：{result!r}")

    async def generate(self, meme: Any, inputs: MemeInputs) -> bytes:
        params = self.get_params(meme)
        if self.get_info(meme) is not None and hasattr(self.module, "Image"):
            images = [
                self.module.Image(name=str(name), data=data)
                for name, data in inputs.images[: params.max_images]
            ]
            result = await asyncio.to_thread(
                meme.generate,
                images,
                inputs.texts[: params.max_texts],
                inputs.options,
            )
        else:
            from meme_generator.utils import run_sync

            runner = run_sync(meme)
            result = await runner(
                images=[data for _, data in inputs.images[: params.max_images]],
                texts=inputs.texts[: params.max_texts],
                args=inputs.options,
            )
        return self._unwrap_result(result, f"生成 {meme.key} 时")

    async def preview(self, meme: Any) -> bytes:
        result = await asyncio.to_thread(meme.generate_preview)
        return self._unwrap_result(result, f"生成 {meme.key} 预览时")

    async def render_list(self) -> bytes:
        tools = importlib.import_module("meme_generator.tools")
        properties = {meme.key: tools.MemeProperties() for meme in self.memes}
        result = await asyncio.to_thread(
            tools.render_meme_list,
            meme_properties=properties,
            exclude_memes=[],
            sort_by=tools.MemeSortBy.KeywordsPinyin,
            sort_reverse=False,
            text_template="{index}. {keywords}",
            add_category_icon=True,
        )
        return self._unwrap_result(result, "生成 meme 列表时")

    async def check_resources(self, timeout: float) -> str:
        script = (
            "from meme_generator.resources import check_resources; check_resources()"
        )
        creationflags = 0
        if os.name == "nt":
            creationflags = 0x08000000  # CREATE_NO_WINDOW
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=creationflags,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            process.kill()
            await process.communicate()
            raise
        if process.returncode:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise MemeEngineError(detail or f"资源检查退出码: {process.returncode}")
        await asyncio.to_thread(self.reload_memes)
        output = stdout.decode("utf-8", errors="replace").strip()
        return output[-1000:]
