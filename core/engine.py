from __future__ import annotations

import asyncio
import importlib
import io
import json
import os
import random
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, ClassVar

import meme_generator as imported_meme_generator
from astrbot.api import logger
from PIL import Image as PILImage

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
    _BUILTIN_KEYS_MARKER: ClassVar[str] = "MEME_FORGE_BUILTIN_KEYS="
    _builtin_key_cache: ClassVar[frozenset[str] | None] = None
    _builtin_key_probe_failed: ClassVar[bool] = False

    def __init__(self, config: Any):
        self.config = config
        self.module: Any = imported_meme_generator
        self.memes: list[Any] = []
        self._by_key: dict[str, Any] = {}
        self._trigger_map: dict[str, Any] = {}
        self._sorted_triggers: list[str] = []
        self._extension_memes: dict[str, list[Any]] = {}
        self._source_by_key: dict[str, str] = {}
        # Alias and disabled-list caches: chat traffic hits match()/is_disabled()
        # on every message, and rebuilding both maps for ~1.5k triggers is costly.
        self._reload_token = 0
        self._alias_signature: tuple[Any, ...] | None = None
        self._disabled_signature: tuple[Any, ...] | None = None
        self._disabled_keys: frozenset[str] = frozenset()

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

    def set_extension_memes(self, name: str, memes: list[Any]) -> None:
        """Replace one reviewed extension's runtime meme objects."""
        normalized = str(name).strip()
        if not normalized:
            raise ValueError("extension name must not be empty")
        self._extension_memes[normalized] = list(memes)

    @classmethod
    def _load_builtin_keys(cls) -> frozenset[str] | None:
        """Read the built-in registry in an isolated meme-generator home."""
        if cls._builtin_key_cache is not None:
            return cls._builtin_key_cache
        if cls._builtin_key_probe_failed:
            return None

        script = (
            "import json\n"
            "from meme_generator import get_meme_keys\n"
            f"print({cls._BUILTIN_KEYS_MARKER!r} + json.dumps(get_meme_keys()))\n"
        )
        creationflags = 0x08000000 if os.name == "nt" else 0
        try:
            with tempfile.TemporaryDirectory(prefix="meme-forge-builtins-") as home:
                environment = os.environ.copy()
                environment["MEME_HOME"] = home
                completed = subprocess.run(
                    [sys.executable, "-c", script],
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    env=environment,
                    timeout=30,
                    check=False,
                    creationflags=creationflags,
                )
            if completed.returncode:
                detail = completed.stderr.strip() or f"exit code {completed.returncode}"
                raise MemeEngineError(detail)
            marker_line = next(
                (
                    line
                    for line in reversed(completed.stdout.splitlines())
                    if line.startswith(cls._BUILTIN_KEYS_MARKER)
                ),
                "",
            )
            if not marker_line:
                raise MemeEngineError("isolated registry did not return meme keys")
            payload = json.loads(marker_line.removeprefix(cls._BUILTIN_KEYS_MARKER))
            if not isinstance(payload, list) or not all(
                isinstance(value, str) and value for value in payload
            ):
                raise MemeEngineError("isolated registry returned invalid meme keys")
        except (
            MemeEngineError,
            OSError,
            subprocess.SubprocessError,
            TypeError,
            ValueError,
        ) as exc:
            cls._builtin_key_probe_failed = True
            logger.warning(
                "[meme_forge] 无法区分内置与原生外部扩展 meme: %s",
                exc,
            )
            return None

        cls._builtin_key_cache = frozenset(payload)
        return cls._builtin_key_cache

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
        builtin_keys = self._load_builtin_keys()
        sources: list[tuple[str, list[Any]]] = [("meme_generator", list(get_memes()))]
        sources.extend(self._extension_memes.items())

        by_key: dict[str, Any] = {}
        trigger_map: dict[str, Any] = {}
        source_by_key: dict[str, str] = {}
        duplicate_keys: list[str] = []
        duplicate_triggers: list[str] = []
        for source, memes in sources:
            for meme in memes:
                key = str(getattr(meme, "key", "")).strip()
                if not key:
                    continue
                existing_key = by_key.get(key)
                if existing_key is not None:
                    duplicate_keys.append(f"{key}({source})")
                    continue
                by_key[key] = meme
                effective_source = source
                if (
                    source == "meme_generator"
                    and builtin_keys is not None
                    and key not in builtin_keys
                ):
                    effective_source = "external"
                source_by_key[key] = effective_source
                trigger_map[key] = meme
                for keyword in self.get_keywords(meme):
                    existing = trigger_map.setdefault(keyword, meme)
                    if existing is not meme:
                        duplicate_triggers.append(
                            f"{keyword}→{getattr(existing, 'key', 'unknown')}"
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
        self._source_by_key = source_by_key
        self._sorted_triggers = sorted(
            trigger_map, key=lambda value: (-len(value), value)
        )
        self._reload_token += 1
        self._alias_signature = (
            self._reload_token,
            tuple(sorted(self._custom_aliases().items())),
        )
        self._disabled_signature = None
        self._log_duplicates("meme key", duplicate_keys)
        self._log_duplicates("触发词", duplicate_triggers)
        logger.info(
            "[meme_forge] 已加载 %d 个 meme、%d 个触发词 (meme_generator %s)",
            len(self.memes),
            len(self._trigger_map),
            self.version,
        )

    @staticmethod
    def _log_duplicates(label: str, entries: list[str]) -> None:
        """Report collisions once instead of one warning line per entry."""
        if not entries:
            return
        preview = "、".join(entries[:8])
        if len(entries) > 8:
            preview += f" 等 {len(entries)} 项"
        logger.info(
            "[meme_forge] %d 个%s重复，已保留先加载的实现：%s",
            len(entries),
            label,
            preview,
        )
        logger.debug("[meme_forge] 重复%s完整列表：%s", label, "、".join(entries))

    def get_source(self, meme: Any) -> str:
        key = str(getattr(meme, "key", ""))
        return self._source_by_key.get(
            key,
            str(getattr(meme, "source", "meme_generator")),
        )

    def extension_memes(self) -> list[Any]:
        """Return all loaded native and compatibility-layer extension memes."""
        return [
            meme
            for meme in self.memes
            if self.get_source(meme) != "meme_generator"
        ]

    def available_memes(self) -> list[Any]:
        """Return loaded memes that are not disabled by the current config."""
        self._refresh_aliases()
        return [meme for meme in self.memes if not self.is_disabled(meme)]

    def random_meme(self) -> Any | None:
        """Choose one enabled meme from the complete runtime-loaded library."""
        candidates = self.available_memes()
        return random.choice(candidates) if candidates else None

    def _refresh_aliases(self) -> None:
        # Configuration can be edited in WebUI without reloading the plugin,
        # so re-check the alias config cheaply and only rebuild when it moved.
        aliases = self._custom_aliases()
        signature = (self._reload_token, tuple(sorted(aliases.items())))
        if signature == self._alias_signature and self._sorted_triggers:
            return

        base: dict[str, Any] = {}
        for meme in self.memes:
            base[str(meme.key)] = meme
            for keyword in self.get_keywords(meme):
                base.setdefault(keyword, meme)
        for alias, original in aliases.items():
            target = base.get(original) or self._by_key.get(original)
            if target is not None:
                base[alias] = target
        self._trigger_map = base
        self._sorted_triggers = sorted(base, key=lambda value: (-len(value), value))
        self._alias_signature = signature

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

    def disabled_keys(self) -> frozenset[str]:
        """Canonical keys plus raw entries of the configured disable list."""
        raw = self._config_value("disabled_memes", []) or []
        entries = tuple(sorted({str(value) for value in raw}))
        signature = (self._reload_token, entries)
        if signature == self._disabled_signature:
            return self._disabled_keys

        resolved: set[str] = set(entries)
        if entries:
            self._refresh_aliases()
            for entry in entries:
                target = self._by_key.get(entry) or self._trigger_map.get(entry)
                if target is not None:
                    resolved.add(str(getattr(target, "key", "")))
        self._disabled_keys = frozenset(resolved - {""})
        self._disabled_signature = signature
        return self._disabled_keys

    def is_disabled(self, meme: Any) -> bool:
        disabled = self.disabled_keys()
        if not disabled:
            return False
        if str(getattr(meme, "key", "")) in disabled:
            return True
        return any(keyword in disabled for keyword in self.get_keywords(meme))

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
        extension_generate = getattr(meme, "generate_from_inputs", None)
        if callable(extension_generate):
            try:
                result = await asyncio.to_thread(extension_generate, inputs)
            except Exception as exc:
                raise MemeGenerationError(
                    f"生成 {meme.key} 失败：{str(exc).strip() or type(exc).__name__}"
                ) from exc
            return self._unwrap_result(result, f"生成 {meme.key} 时")

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
        extension_preview = getattr(meme, "generate_preview", None)
        if callable(getattr(meme, "generate_from_inputs", None)) and callable(
            extension_preview
        ):
            try:
                result = await asyncio.to_thread(extension_preview)
            except Exception as exc:
                raise MemeGenerationError(
                    f"生成 {meme.key} 预览失败：{str(exc).strip() or type(exc).__name__}"
                ) from exc
            return self._unwrap_result(result, f"生成 {meme.key} 预览时")
        result = await asyncio.to_thread(meme.generate_preview)
        return self._unwrap_result(result, f"生成 {meme.key} 预览时")

    async def render_list(self) -> bytes:
        tools = importlib.import_module("meme_generator.tools")
        native_memes = [
            meme
            for meme in self.memes
            if not callable(getattr(meme, "generate_from_inputs", None))
        ]
        extension_memes = [
            meme
            for meme in self.memes
            if callable(getattr(meme, "generate_from_inputs", None))
        ]
        properties = {meme.key: tools.MemeProperties() for meme in native_memes}
        result = await asyncio.to_thread(
            tools.render_meme_list,
            meme_properties=properties,
            exclude_memes=[],
            sort_by=tools.MemeSortBy.KeywordsPinyin,
            sort_reverse=False,
            text_template="{index}. {keywords}",
            add_category_icon=True,
        )
        native = self._unwrap_result(result, "生成 meme 列表时")
        if not extension_memes:
            return native

        from .gouqi_memes import render_gouqi_list_panel

        extension = await asyncio.to_thread(
            render_gouqi_list_panel,
            extension_memes,
        )
        return await asyncio.to_thread(self._append_list_panel, native, extension)

    async def render_extension_list(self) -> bytes:
        memes = self.extension_memes()
        if not memes:
            raise MemeEngineError(
                "当前没有加载扩展 meme；请先安装扩展，并按安装提示重启或启用扩展。"
            )

        native_extensions = [
            meme
            for meme in memes
            if not callable(getattr(meme, "generate_from_inputs", None))
        ]
        custom_extensions = [
            meme
            for meme in memes
            if callable(getattr(meme, "generate_from_inputs", None))
        ]
        panels: list[bytes] = []
        if native_extensions:
            tools = importlib.import_module("meme_generator.tools")
            selected_keys = {str(meme.key) for meme in native_extensions}
            native_keys = {
                str(meme.key)
                for meme in self.memes
                if not callable(getattr(meme, "generate_from_inputs", None))
            }
            properties = {
                meme.key: tools.MemeProperties() for meme in native_extensions
            }
            result = await asyncio.to_thread(
                tools.render_meme_list,
                meme_properties=properties,
                exclude_memes=sorted(native_keys - selected_keys),
                sort_by=tools.MemeSortBy.KeywordsPinyin,
                sort_reverse=False,
                text_template="{index}. {keywords}",
                add_category_icon=True,
            )
            panels.append(self._unwrap_result(result, "生成扩展 meme 列表时"))

        if custom_extensions:
            from .gouqi_memes import render_gouqi_list_panel

            panels.append(
                await asyncio.to_thread(
                    render_gouqi_list_panel,
                    custom_extensions,
                )
            )

        output = panels[0]
        for panel in panels[1:]:
            output = await asyncio.to_thread(self._append_list_panel, output, panel)
        return output

    @staticmethod
    def _append_list_panel(native: bytes, extension: bytes) -> bytes:
        with (
            PILImage.open(io.BytesIO(native)) as native_image,
            PILImage.open(io.BytesIO(extension)) as extension_image,
        ):
            first = native_image.convert("RGBA")
            second = extension_image.convert("RGBA")
        width = max(first.width, second.width)
        canvas = PILImage.new(
            "RGBA",
            (width, first.height + second.height),
            (255, 255, 255, 255),
        )
        canvas.alpha_composite(first, ((width - first.width) // 2, 0))
        canvas.alpha_composite(
            second,
            ((width - second.width) // 2, first.height),
        )
        output = io.BytesIO()
        canvas.save(output, format="PNG")
        return output.getvalue()

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
