from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

import aiohttp
from astrbot.api import logger
from astrbot.api import message_components as Comp
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core import AstrBotConfig
from astrbot.core.star import StarTools
from astrbot.core.star.filter.event_message_type import EventMessageType
from quart import jsonify, request

from .core.arguments import strip_trigger_prefix
from .core.collector import InputCollectionError, ParamsCollector
from .core.dashboard import DashboardError, MemeDashboard
from .core.engine import MemeEngine, MemeEngineError, MemeGenerationError
from .core.extensions import ExtensionInstallError, MemeEmojiExtensionManager
from .core.favorites import (
    FavoriteEntry,
    GeneratedMemeRecord,
    MemeOutputIndex,
    add_favorite,
    dump_favorites,
    normalize_favorites,
    remove_favorite,
)
from .core.gouqi_extension import GouqiExtensionError, GouqiExtensionManager
from .core.grabber import MemeGrabber, MemeGrabError
from .core.history import MemeUsageHistory
from .core.updates import (
    SUPPORTED_RANGE_TEXT,
    compare_engine_versions,
    fetch_latest_compatible_meme_generator,
    format_check_error,
)
from .utils import compress_static_image

PLUGIN_ID = "astrbot_plugin_meme_forge"
OUTPUT_INDEX_KV_KEY = "generated_meme_outputs_v1"
FAVORITES_KV_PREFIX = "meme_favorites_v1"
USAGE_HISTORY_KV_KEY = "meme_usage_history_v1"


class GenerationBusyError(RuntimeError):
    """Raised when all configured generation slots are occupied."""


class FavoriteLookupError(RuntimeError):
    """Raised when a quoted message cannot be mapped to a generated meme."""


class MemeForgePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        data_dir = StarTools.get_data_dir(PLUGIN_ID)
        self.collector = ParamsCollector(config)
        self.engine = MemeEngine(config)
        self.grabber = MemeGrabber(
            data_dir / "grabbed_memes",
            self.collector,
            config,
        )
        self.extension = MemeEmojiExtensionManager(
            data_dir,
            config,
        )
        self.gouqi_extension = GouqiExtensionManager(data_dir, config)
        self.dashboard = MemeDashboard(
            self.engine,
            self.extension,
            config,
            gouqi_extension=self.gouqi_extension,
        )
        parallel = max(1, int(self._config_value("max_parallel_generations", 2)))
        self._generation_slots = asyncio.Semaphore(parallel)
        self._resource_task: asyncio.Task[None] | None = None
        self._recent_memes: dict[str, list[tuple[str, str]]] = {}
        self._output_index = MemeOutputIndex(max_records=500)
        self._usage_history = MemeUsageHistory(
            max_records=self._history_limit(),
        )
        self._storage_lock = asyncio.Lock()
        self._register_dashboard_apis()

    def _config_value(self, key: str, default: Any) -> Any:
        try:
            return self.config.get(key, default)
        except AttributeError:
            try:
                return self.config[key]
            except (KeyError, TypeError):
                return default

    def _history_limit(self) -> int:
        return max(100, min(int(self._config_value("history_limit", 500)), 2_000))

    def _register_dashboard_apis(self) -> None:
        apis = [
            ("dashboard/overview", self.dashboard_overview, ["GET"], "Meme 工坊概览"),
            ("dashboard/memes", self.dashboard_memes, ["GET"], "Meme 工坊表情列表"),
            ("dashboard/meme", self.dashboard_meme, ["GET"], "Meme 工坊表情详情"),
            ("dashboard/preview", self.dashboard_preview, ["GET"], "Meme 工坊表情预览"),
            ("dashboard/materials", self.dashboard_materials, ["GET"], "Meme 工坊素材列表"),
            ("dashboard/material", self.dashboard_material, ["GET"], "Meme 工坊素材预览"),
            ("dashboard/history", self.dashboard_history, ["GET"], "Meme 工坊使用记录"),
            ("dashboard/meme-enabled", self.dashboard_meme_enabled, ["POST"], "Meme 工坊表情启停"),
        ]
        for suffix, handler, methods, description in apis:
            self.context.register_web_api(
                f"/{PLUGIN_ID}/{suffix}",
                handler,
                methods,
                description,
            )

    @staticmethod
    def _dashboard_error(message: str, status: int = 400):
        return jsonify({"ok": False, "error": message}), status

    async def dashboard_overview(self):
        """Return the compact state shown at the top of the plugin Page."""
        try:
            extension_status, gouqi_status = await asyncio.gather(
                asyncio.to_thread(self.extension.status),
                asyncio.to_thread(self.gouqi_extension.status),
            )
            return jsonify(
                {
                    "ok": True,
                    **self.dashboard.overview(
                        self._usage_history,
                        extension_status,
                        gouqi_status,
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001 - Dashboard must report failures as JSON
            logger.exception("[meme_forge] 读取 Dashboard 概览失败")
            return self._dashboard_error(f"读取概览失败：{exc}", 500)

    async def dashboard_memes(self):
        """Return a paged, searchable list of runtime-loaded memes."""
        try:
            payload = self.dashboard.catalog(
                query=request.args.get("q", ""),
                tag=request.args.get("tag", ""),
                status=request.args.get("status", "all"),
                offset=request.args.get("offset", 0),
                limit=request.args.get("limit", 60),
            )
            return jsonify({"ok": True, **payload})
        except (DashboardError, TypeError, ValueError) as exc:
            return self._dashboard_error(str(exc))

    async def dashboard_meme(self):
        """Return details and runtime argument metadata for one meme."""
        try:
            return jsonify(
                {
                    "ok": True,
                    "item": self.dashboard.meme_detail(request.args.get("key", "")),
                }
            )
        except DashboardError as exc:
            return self._dashboard_error(str(exc), 404)

    async def dashboard_preview(self):
        """Generate a selected meme preview as a bounded data URL."""
        try:
            return jsonify(
                {
                    "ok": True,
                    **await self.dashboard.preview(request.args.get("key", "")),
                }
            )
        except DashboardError as exc:
            return self._dashboard_error(str(exc))

    async def dashboard_materials(self):
        """Return material image names for a selected meme without local paths."""
        try:
            return jsonify(
                {
                    "ok": True,
                    **self.dashboard.materials(request.args.get("key", "")),
                }
            )
        except DashboardError as exc:
            return self._dashboard_error(str(exc), 404)

    async def dashboard_material(self):
        """Return one validated source-material image as a bounded data URL."""
        try:
            return jsonify(
                {
                    "ok": True,
                    **self.dashboard.material(
                        request.args.get("key", ""),
                        request.args.get("name", ""),
                    ),
                }
            )
        except DashboardError as exc:
            return self._dashboard_error(str(exc), 404)

    async def dashboard_history(self):
        """Return global or selected-conversation successful generation records."""
        try:
            payload = self.dashboard.history(
                self._usage_history,
                session=request.args.get("session", "") or None,
                limit=request.args.get("limit", 30),
            )
            return jsonify({"ok": True, **payload})
        except (DashboardError, TypeError, ValueError) as exc:
            return self._dashboard_error(str(exc))

    async def dashboard_meme_enabled(self):
        """Enable or disable one meme by stable key from the Dashboard Page."""
        payload = await request.get_json(silent=True) or {}
        key = str(payload.get("key", "")).strip()
        enabled = payload.get("enabled")
        if not key or not isinstance(enabled, bool):
            return self._dashboard_error("需要提供 meme key 和布尔 enabled 值。")

        meme = self.engine.resolve(key)
        if meme is None:
            return self._dashboard_error("没有找到该 meme。", 404)
        canonical_key = str(meme.key)
        disabled = list(self._config_value("disabled_memes", []) or [])
        matching = {
            value
            for value in disabled
            if str(value) == canonical_key
            or self.engine.canonical_key(str(value)) == canonical_key
        }
        if enabled:
            updated = [value for value in disabled if value not in matching]
        else:
            updated = disabled if matching else [*disabled, canonical_key]
        try:
            self.config["disabled_memes"] = updated
            self.config.save_config()
        except Exception as exc:  # noqa: BLE001 - config storage differs across installs
            logger.exception("[meme_forge] Dashboard 保存禁用列表失败")
            return self._dashboard_error(f"保存设置失败：{exc}", 500)
        return jsonify({"ok": True, "item": self.dashboard.meme_summary(meme)})

    @staticmethod
    def _recent_history_key(event: AstrMessageEvent) -> str:
        return f"{event.get_platform_name()}:{event.get_sender_id()}"

    def _remember_meme(
        self,
        event: AstrMessageEvent,
        meme: Any,
        trigger: str | None = None,
    ) -> None:
        """Keep the latest three distinct memes for this sender and platform."""
        key = str(getattr(meme, "key", "")).strip()
        if not key:
            return
        name = str(trigger or "").strip()
        if not name:
            keywords = self.engine.get_keywords(meme)
            name = keywords[0] if keywords else key

        history_key = self._recent_history_key(event)
        history = [
            entry
            for entry in self._recent_memes.get(history_key, [])
            if entry[1] != key
        ]
        history.insert(0, (name, key))
        self._recent_memes[history_key] = history[:3]

    def _preferred_trigger(self, meme: Any, trigger: str | None = None) -> str:
        trigger_text = str(trigger or "").strip()
        if trigger_text:
            return trigger_text
        keywords = self.engine.get_keywords(meme)
        return keywords[0] if keywords else str(getattr(meme, "key", "meme"))

    def _format_trigger_command(self, trigger: str) -> str:
        prefix = str(self._config_value("trigger_prefix", "meme")).strip()
        if not prefix:
            return f"/{trigger}"
        separator = " " if prefix[-1].isalnum() else ""
        return f"/{prefix}{separator}{trigger}"

    @staticmethod
    def _favorite_storage_key(event: AstrMessageEvent) -> str:
        owner = f"{event.get_platform_name()}:{event.get_sender_id()}"
        return f"{FAVORITES_KV_PREFIX}:{owner}"

    @staticmethod
    def _find_reply(event: AstrMessageEvent) -> Any | None:
        return next(
            (
                component
                for component in list(event.get_messages() or [])
                if isinstance(component, Comp.Reply)
            ),
            None,
        )

    @classmethod
    def _reply_images(cls, reply: Any) -> list[Any]:
        images: list[Any] = []
        seen_components: set[int] = set()
        for attribute in ("chain", "message", "origin", "content"):
            for component in list(getattr(reply, attribute, None) or []):
                identity = id(component)
                if identity in seen_components:
                    continue
                seen_components.add(identity)
                if isinstance(component, Comp.Image):
                    images.append(component)
                elif isinstance(component, Comp.Reply):
                    images.extend(cls._reply_images(component))
        return images

    async def _remember_generated_output(
        self,
        event: AstrMessageEvent,
        meme: Any,
        image: bytes,
        trigger: str | None = None,
        *,
        track_usage: bool = False,
    ) -> None:
        key = str(getattr(meme, "key", "")).strip()
        if not key:
            return
        preferred_trigger = self._preferred_trigger(meme, trigger)
        async with self._storage_lock:
            self._output_index.remember(
                image,
                session=event.unified_msg_origin,
                key=key,
                trigger=preferred_trigger,
            )
            try:
                await self.put_kv_data(OUTPUT_INDEX_KV_KEY, self._output_index.dump())
            except Exception as exc:  # noqa: BLE001 - storage backends vary by install
                logger.warning("[meme_forge] 保存已生成 meme 索引失败: %s", exc)
            if track_usage:
                self._usage_history.max_records = self._history_limit()
                self._usage_history.remember(
                    key=key,
                    trigger=preferred_trigger,
                    platform=event.get_platform_name(),
                    session=event.unified_msg_origin,
                    sender_id=event.get_sender_id(),
                    sender_name=event.get_sender_name() or event.get_sender_id(),
                )
                try:
                    await self.put_kv_data(
                        USAGE_HISTORY_KV_KEY,
                        self._usage_history.dump(),
                    )
                except Exception as exc:  # noqa: BLE001 - storage backends vary by install
                    logger.warning("[meme_forge] 保存 meme 使用记录失败: %s", exc)

    async def _match_quoted_meme(
        self,
        event: AstrMessageEvent,
    ) -> GeneratedMemeRecord:
        reply = self._find_reply(event)
        if reply is None:
            raise FavoriteLookupError("请引用 Bot 发送的 meme 图片后再使用该命令。")

        reply_sender = str(
            getattr(reply, "sender_id", None) or getattr(reply, "qq", None) or ""
        )
        self_id = str(event.get_self_id() or "")
        if reply_sender not in {"", "0"} and self_id and reply_sender != self_id:
            raise FavoriteLookupError("只能收藏 Bot 发送的 meme 图片。")

        images = self._reply_images(reply)
        if not images:
            raise FavoriteLookupError("被引用的消息中没有图片。")

        last_error: Exception | None = None
        for image_component in images:
            try:
                image = await self.collector.read_image_component(image_component)
            except (
                InputCollectionError,
                OSError,
                aiohttp.ClientError,
                asyncio.TimeoutError,
            ) as exc:
                last_error = exc
                continue
            if record := self._output_index.match(
                image,
                session=event.unified_msg_origin,
            ):
                return record

        if last_error is not None:
            raise FavoriteLookupError(f"读取被引用图片失败：{last_error}") from last_error
        raise FavoriteLookupError(
            "没有识别到这张图片对应的 Meme 工坊生成记录。"
            "请确认引用的是本插件近期发送的 meme。"
        )

    async def _load_favorites(self, event: AstrMessageEvent) -> list[FavoriteEntry]:
        raw = await self.get_kv_data(self._favorite_storage_key(event), [])
        return normalize_favorites(raw)

    async def _save_favorites(
        self,
        event: AstrMessageEvent,
        favorites: list[FavoriteEntry],
    ) -> None:
        await self.put_kv_data(
            self._favorite_storage_key(event),
            dump_favorites(favorites),
        )

    async def _refresh_gouqi_memes(self, *, reload_engine: bool) -> int:
        gouqi_memes: list[Any] = []
        if self._config_value("gouqi_extension_enabled", True):
            try:
                gouqi_memes = await asyncio.to_thread(self.gouqi_extension.load_memes)
            except Exception as exc:  # noqa: BLE001 - invalid extension data is isolated
                logger.warning("[meme_forge] Gouqi 扩展加载失败: %s", exc)
        self.engine.set_extension_memes("gouqi", gouqi_memes)
        if reload_engine:
            await asyncio.to_thread(self.engine.reload_memes)
        return len(gouqi_memes)

    async def initialize(self) -> None:
        await self._refresh_gouqi_memes(reload_engine=False)
        await self.engine.initialize()
        try:
            records = await self.get_kv_data(OUTPUT_INDEX_KV_KEY, [])
            self._output_index = MemeOutputIndex(records, max_records=500)
        except Exception as exc:  # noqa: BLE001 - storage backends vary by install
            logger.warning("[meme_forge] 读取已生成 meme 索引失败: %s", exc)
        try:
            usage_records = await self.get_kv_data(USAGE_HISTORY_KV_KEY, [])
            self._usage_history = MemeUsageHistory(
                usage_records,
                max_records=self._history_limit(),
            )
        except Exception as exc:  # noqa: BLE001 - storage backends vary by install
            logger.warning("[meme_forge] 读取 meme 使用记录失败: %s", exc)
        try:
            await self.grabber.cleanup_expired()
        except OSError as exc:
            logger.warning("[meme_forge] 清理过期提取文件失败: %s", exc)
        if self._config_value("check_resources_on_start", False):
            self._resource_task = asyncio.create_task(self._background_resource_check())

    async def _background_resource_check(self) -> None:
        timeout = float(self._config_value("resource_check_timeout", 180))
        try:
            await self.engine.check_resources(timeout)
        except asyncio.TimeoutError:
            logger.warning("[meme_forge] 启动资源检查在 %.0f 秒后终止", timeout)
        except asyncio.CancelledError:
            raise
        except (MemeEngineError, OSError) as exc:
            logger.warning("[meme_forge] 启动资源检查失败: %s", exc)

    @filter.command(
        "meme工坊帮助",
        alias={"meme工坊列表", "meme工坊菜单", "梗图工坊帮助"},
    )
    async def meme_help(self, event: AstrMessageEvent):
        """查看 Meme 工坊支持的表情和触发词。"""
        try:
            output = await asyncio.wait_for(self.engine.render_list(), timeout=60)
        except (asyncio.TimeoutError, MemeEngineError) as exc:
            yield event.plain_result(
                f"列表图生成失败：{exc}\n当前已加载 {len(self.engine.memes)} 个 meme。"
            )
            return
        yield event.chain_result([Comp.Image.fromBytes(output)])

    @filter.command("meme工坊详情", alias={"梗图工坊详情"})
    async def meme_details(
        self,
        event: AstrMessageEvent,
        keyword: str | None = None,
    ):
        """查看一个 meme 的图片、文本和选项参数。"""
        if not keyword:
            yield event.plain_result("请指定 meme 名称或关键词。")
            return
        meme = self.engine.resolve(keyword)
        if meme is None:
            yield event.plain_result(f"没有找到 meme：{keyword}")
            return
        try:
            preview = await asyncio.wait_for(self.engine.preview(meme), timeout=30)
        except (asyncio.TimeoutError, MemeEngineError) as exc:
            yield event.plain_result(
                f"{self.engine.format_info(meme)}\n\n预览生成失败：{exc}"
            )
            return
        await self._remember_generated_output(event, meme, preview, keyword)
        yield event.chain_result(
            [Comp.Plain(self.engine.format_info(meme)), Comp.Image.fromBytes(preview)]
        )

    @filter.command("meme工坊禁用")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def disable_meme(
        self,
        event: AstrMessageEvent,
        keyword: str | None = None,
    ):
        """禁用一个 meme。"""
        if not keyword:
            yield event.plain_result("请指定要禁用的 meme。")
            return
        key = self.engine.canonical_key(keyword)
        if key is None:
            yield event.plain_result(f"没有找到 meme：{keyword}")
            return
        disabled = list(self._config_value("disabled_memes", []) or [])
        meme = self.engine.resolve(key)
        if meme is not None and self.engine.is_disabled(meme):
            yield event.plain_result(f"{key} 已经处于禁用状态。")
            return
        disabled.append(key)
        self.config["disabled_memes"] = disabled
        self.config.save_config()
        yield event.plain_result(f"已禁用 meme：{key}")

    @filter.command("meme工坊启用")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def enable_meme(
        self,
        event: AstrMessageEvent,
        keyword: str | None = None,
    ):
        """重新启用一个 meme。"""
        if not keyword:
            yield event.plain_result("请指定要启用的 meme。")
            return
        key = self.engine.canonical_key(keyword)
        if key is None:
            yield event.plain_result(f"没有找到 meme：{keyword}")
            return
        disabled = list(self._config_value("disabled_memes", []) or [])
        matching = {
            value
            for value in disabled
            if self.engine.canonical_key(str(value)) == key or value == key
        }
        if not matching:
            yield event.plain_result(f"{key} 当前没有被禁用。")
            return
        self.config["disabled_memes"] = [
            value for value in disabled if value not in matching
        ]
        self.config.save_config()
        yield event.plain_result(f"已启用 meme：{key}")

    @filter.command("meme工坊黑名单")
    async def disabled_memes(self, event: AstrMessageEvent):
        """查看已禁用的 meme。"""
        disabled = list(self._config_value("disabled_memes", []) or [])
        text = "、".join(map(str, disabled)) if disabled else "无"
        yield event.plain_result(f"当前禁用的 meme：{text}")

    @filter.command("meme工坊资源检查")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def check_resources(self, event: AstrMessageEvent):
        """检查并下载 meme-generator 所需的内置资源。"""
        timeout = float(self._config_value("resource_check_timeout", 180))
        yield event.plain_result(f"开始检查 meme 资源，最长等待 {int(timeout)} 秒。")
        try:
            await self.engine.check_resources(timeout)
        except asyncio.TimeoutError:
            yield event.plain_result(
                "资源检查超时，子进程已终止；请检查网络或代理配置。"
            )
            return
        except (MemeEngineError, OSError) as exc:
            yield event.plain_result(f"资源检查失败：{exc}")
            return
        yield event.plain_result(
            f"资源检查完成，当前加载 {len(self.engine.memes)} 个 meme。"
        )

    @filter.command("meme工坊扩展状态")
    async def extension_status(self, event: AstrMessageEvent):
        """查看 meme_emoji 扩展安装状态。"""
        status = await asyncio.to_thread(self.extension.status)
        lines = [
            f"安装记录：{'有' if status.installed else '无'}",
            f"版本：{status.tag or '未安装'}",
            f"动态库校验：{'通过' if status.library_valid else '未通过'}",
            f"上游许可证：{'已保存' if status.license_present else '缺失'}",
            f"资源目录：{'存在' if status.resources_present else '缺失'}",
            f"外部 meme 加载：{'已启用' if status.external_loading_enabled else '未启用'}",
        ]
        if status.installed:
            lines.append("更新或首次安装后需要重启 AstrBot 才会加载动态库。")
        yield event.plain_result("\n".join(lines))

    @filter.command("meme工坊更新检查", alias={"meme更新检查"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def check_updates(self, event: AstrMessageEvent):
        """Check compatible engine and reviewed extension revisions without installing."""
        engine_task = asyncio.create_task(
            asyncio.wait_for(fetch_latest_compatible_meme_generator(), timeout=20)
        )
        extension_task = asyncio.create_task(
            asyncio.wait_for(self.extension.latest_release(), timeout=20)
        )
        status_task = asyncio.create_task(
            asyncio.wait_for(asyncio.to_thread(self.extension.status), timeout=20)
        )
        gouqi_revision_task = asyncio.create_task(
            asyncio.wait_for(self.gouqi_extension.latest_revision(), timeout=20)
        )
        gouqi_status_task = asyncio.create_task(
            asyncio.wait_for(
                asyncio.to_thread(self.gouqi_extension.status),
                timeout=20,
            )
        )
        (
            latest_engine,
            latest_extension,
            extension_status,
            latest_gouqi,
            gouqi_status,
        ) = await asyncio.gather(
            engine_task,
            extension_task,
            status_task,
            gouqi_revision_task,
            gouqi_status_task,
            return_exceptions=True,
        )
        for result in (
            latest_engine,
            latest_extension,
            extension_status,
            latest_gouqi,
            gouqi_status,
        ):
            if isinstance(result, asyncio.CancelledError):
                raise result

        current_engine = self.engine.version
        lines = ["Meme 工坊更新检查", "", "内置 meme_generator："]
        if isinstance(latest_engine, BaseException):
            logger.warning("[meme_forge] 检查 meme_generator 更新失败: %s", latest_engine)
            engine_error = format_check_error(latest_engine)
            lines.extend(
                [
                    f"- 当前版本：{current_engine}",
                    f"- 最新版本：检查失败（{engine_error}）",
                    f"- 兼容范围：{SUPPORTED_RANGE_TEXT}",
                ]
            )
        else:
            engine_state = compare_engine_versions(current_engine, latest_engine)
            state_text = {
                "current": "已是最新兼容版本",
                "update_available": "有兼容更新可用",
                "newer": "当前版本高于 PyPI 最新兼容版本",
                "unknown": "版本格式无法比较",
            }[engine_state]
            lines.extend(
                [
                    f"- 当前版本：{current_engine}",
                    f"- 最新兼容版本：{latest_engine}",
                    f"- 状态：{state_text}",
                    f"- 兼容范围：{SUPPORTED_RANGE_TEXT}",
                ]
            )

        lines.extend(["", "meme_emoji 扩展："])
        if isinstance(extension_status, BaseException):
            logger.warning("[meme_forge] 读取扩展状态失败: %s", extension_status)
            current_extension = "状态读取失败"
            emoji_status_available = False
            emoji_installed = False
            emoji_healthy = False
        else:
            current_extension = extension_status.tag or "未安装"
            emoji_status_available = True
            emoji_installed = extension_status.installed
            emoji_healthy = all(
                (
                    extension_status.library_valid,
                    extension_status.license_present,
                    extension_status.resources_present,
                    extension_status.external_loading_enabled,
                )
            )

        lines.append(f"- 当前版本：{current_extension}")
        if isinstance(latest_extension, BaseException):
            logger.warning("[meme_forge] 检查 meme_emoji 更新失败: %s", latest_extension)
            extension_error = format_check_error(latest_extension)
            lines.append(f"- 最新版本：检查失败（{extension_error}）")
        else:
            lines.append(f"- 最新版本：{latest_extension.tag}")
            if not emoji_status_available:
                extension_state = "无法判断本地安装状态"
            elif not emoji_installed:
                extension_state = "尚未安装"
            elif current_extension != latest_extension.tag:
                extension_state = "有更新可用"
            elif not emoji_healthy:
                extension_state = "版本最新，但本地安装不完整或校验未通过"
            else:
                extension_state = "已是最新版本，且本地校验通过"
            lines.append(f"- 状态：{extension_state}")

        supported_gouqi = self.gouqi_extension.SUPPORTED_COMMIT
        lines.extend(["", "Gouqi 扩展："])
        if isinstance(gouqi_status, BaseException):
            logger.warning("[meme_forge] 读取 Gouqi 扩展状态失败: %s", gouqi_status)
            gouqi_installed = False
            gouqi_healthy = False
            current_gouqi = "状态读取失败"
            gouqi_status_available = False
        else:
            gouqi_installed = gouqi_status.installed
            gouqi_healthy = gouqi_status.assets_valid
            current_gouqi = (
                gouqi_status.commit[:12] if gouqi_status.commit else "未安装"
            )
            gouqi_status_available = True
        lines.extend(
            [
                f"- 当前版本：{current_gouqi}",
                f"- 插件已审阅版本：{supported_gouqi[:12]}",
            ]
        )
        if isinstance(latest_gouqi, BaseException):
            logger.warning("[meme_forge] 检查 Gouqi 上游提交失败: %s", latest_gouqi)
            lines.append(
                f"- 上游最新提交：检查失败（{format_check_error(latest_gouqi)}）"
            )
            upstream_reviewed = False
        else:
            lines.append(f"- 上游最新提交：{latest_gouqi.commit[:12]}")
            upstream_reviewed = latest_gouqi.commit == supported_gouqi

        if not gouqi_status_available:
            gouqi_state = "无法判断本地安装状态"
        elif not gouqi_installed:
            gouqi_state = "尚未安装"
        elif gouqi_status.commit != supported_gouqi:
            gouqi_state = "本地不是插件当前审阅版本"
        elif not gouqi_healthy:
            gouqi_state = "已安装，但素材缺失或哈希校验未通过"
        else:
            gouqi_state = "已安装，审阅素材校验通过"
        lines.append(f"- 状态：{gouqi_state}")
        if not isinstance(latest_gouqi, BaseException) and not upstream_reviewed:
            lines.append("- 提示：上游有未审阅改动，需等待 Meme 工坊适配后更新。")
        lines.append("- 许可：上游暂未声明开源许可证，不会打包进本插件。")

        lines.extend(
            [
                "",
                "内置素材：只读检查无法逐项判断；需要时执行 /meme工坊资源检查。",
                "本命令只检查，不会下载或安装任何更新。",
            ]
        )
        if not isinstance(latest_extension, BaseException) and (
            not emoji_installed
            or current_extension != latest_extension.tag
            or not emoji_healthy
        ):
            lines.append(
                "扩展可执行 /meme工坊扩展更新 确认，完成后重启 AstrBot。"
            )
        if (
            not gouqi_installed
            or not gouqi_healthy
            or (
                not isinstance(gouqi_status, BaseException)
                and gouqi_status.commit != supported_gouqi
            )
        ):
            lines.append("Gouqi 扩展可执行 /meme工坊Gouqi扩展安装 确认。")
        yield event.plain_result("\n".join(lines))

    @filter.command("meme工坊扩展安装", alias={"meme工坊扩展更新"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def install_extension(
        self,
        event: AstrMessageEvent,
        confirmation: str | None = None,
    ):
        """安装或更新 anyliew/meme_emoji 的兼容扩展。"""
        if confirmation != "确认":
            yield event.plain_result(
                "该操作会从上游下载约 400+ MB 资源，并临时占用约 1.1 GB 磁盘。"
                "请使用 /meme工坊扩展安装 确认 继续。"
            )
            return
        yield event.plain_result(
            "开始安装 meme_emoji 扩展；下载和解压可能需要较长时间。"
        )
        try:
            status = await self.extension.install()
        except (
            ExtensionInstallError,
            aiohttp.ClientError,
            asyncio.TimeoutError,
            OSError,
        ) as exc:
            yield event.plain_result(f"扩展安装失败：{exc}")
            return
        yield event.plain_result(
            f"meme_emoji 兼容扩展 {status.tag or ''} 已安装。请重启 AstrBot 后使用。"
        )

    @filter.command(
        "meme工坊Gouqi扩展状态",
        alias={"meme工坊枸杞扩展状态"},
    )
    async def gouqi_extension_status(self, event: AstrMessageEvent):
        """查看 Gouqi 兼容扩展的审阅版本和素材状态。"""
        status = await asyncio.to_thread(self.gouqi_extension.status)
        loaded = sum(
            1 for meme in self.engine.memes if getattr(meme, "source", "") == "gouqi"
        )
        lines = [
            f"安装记录：{'有' if status.installed else '无'}",
            f"本地版本：{status.commit[:12] if status.commit else '未安装'}",
            f"插件审阅版本：{self.gouqi_extension.SUPPORTED_COMMIT[:12]}",
            f"素材校验：{'通过' if status.assets_valid else '未通过'}",
            f"素材文件：{status.asset_files} 个",
            f"已加载 meme：{loaded} 个",
            f"扩展开关：{'已启用' if self._config_value('gouqi_extension_enabled', True) else '已关闭'}",
            "上游许可证：暂未声明；素材不会打包进本插件。",
        ]
        yield event.plain_result("\n".join(lines))

    @filter.command(
        "meme工坊Gouqi扩展安装",
        alias={
            "meme工坊Gouqi扩展更新",
            "meme工坊枸杞扩展安装",
            "meme工坊枸杞扩展更新",
        },
    )
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def install_gouqi_extension(
        self,
        event: AstrMessageEvent,
        confirmation: str | None = None,
    ):
        """Install reviewed Gouqi assets without executing upstream Python."""
        if confirmation != "确认":
            yield event.plain_result(
                "Gouqi 上游目前未声明开源许可证。仅在你已获得作者及素材使用授权时继续；"
                "本操作会从原仓库下载约 7 MB 素材，不会执行其中的 Python。"
                "请使用 /meme工坊Gouqi扩展安装 确认 继续。"
            )
            return
        yield event.plain_result("开始安装 Gouqi 审阅素材并校验每个文件。")
        try:
            status = await self.gouqi_extension.install()
            loaded = await self._refresh_gouqi_memes(reload_engine=True)
        except (
            GouqiExtensionError,
            aiohttp.ClientError,
            asyncio.TimeoutError,
            OSError,
        ) as exc:
            yield event.plain_result(f"Gouqi 扩展安装失败：{exc}")
            return
        if not status.assets_valid:
            yield event.plain_result("Gouqi 扩展安装完成，但素材复核未通过，未加载。")
            return
        if not self._config_value("gouqi_extension_enabled", True):
            yield event.plain_result(
                f"Gouqi 扩展 {status.commit[:12] if status.commit else ''} 已安装；"
                "当前扩展开关已关闭，启用配置并重载插件后生效。"
            )
            return
        yield event.plain_result(
            f"Gouqi 扩展 {status.commit[:12] if status.commit else ''} 已安装，"
            f"已热加载 {loaded} 个 meme，无需重启 AstrBot。"
        )

    @filter.command("meme工坊提取", alias={"meme提取", "提取meme"})
    async def extract_meme(
        self,
        event: AstrMessageEvent,
        send_mode: str | None = None,
    ):
        """Extract message images, optionally forcing image or file delivery."""
        event.stop_event()
        mode_text = str(send_mode or "").strip()
        selected_mode = self.grabber.command_send_mode(mode_text)
        if mode_text and selected_mode is None:
            yield event.plain_result(
                "提取模式只支持“图片”或“文件”。\n"
                "例如：/meme提取 图片 或 /meme提取 文件"
            )
            return
        try:
            files = await self.grabber.extract(event)
        except MemeGrabError as exc:
            yield event.plain_result(str(exc))
            return
        except Exception:  # noqa: BLE001 - adapters can expose malformed payloads
            logger.exception("[meme_forge] 提取表情失败")
            yield event.plain_result("表情提取失败，请查看 AstrBot 日志。")
            return
        yield event.chain_result(
            self.grabber.build_components(files, send_mode=selected_mode)
        )

    @filter.command("meme工坊收藏", alias={"meme收藏"})
    async def favorite_meme(self, event: AstrMessageEvent):
        """收藏被引用的 Meme 工坊图片。"""
        event.stop_event()
        try:
            record = await self._match_quoted_meme(event)
        except FavoriteLookupError as exc:
            yield event.plain_result(str(exc))
            return

        entry = FavoriteEntry(key=record.key, trigger=record.trigger)
        max_favorites = max(1, int(self._config_value("max_favorites", 50)))
        evicted: list[FavoriteEntry] = []
        try:
            async with self._storage_lock:
                favorites = await self._load_favorites(event)
                updated, is_new = add_favorite(
                    favorites,
                    entry,
                    max_favorites=max_favorites,
                )
                updated_keys = {favorite.key for favorite in updated}
                evicted = [
                    favorite
                    for favorite in favorites
                    if favorite.key not in updated_keys
                ]
                await self._save_favorites(event, updated)
        except Exception as exc:  # noqa: BLE001 - storage backends vary by install
            logger.exception("[meme_forge] 保存收藏失败")
            yield event.plain_result(f"收藏保存失败：{exc}")
            return

        action = "已收藏" if is_new else "已在收藏夹中，并移到最前"
        lines = [
            f"{action}：{record.trigger}（key: {record.key}）",
            f"下次可用：{self._format_trigger_command(record.trigger)}",
        ]
        if len(evicted) == 1:
            removed = evicted[0]
            lines.append(
                f"收藏已达上限，已移除最早收藏：{removed.trigger}"
                f"（key: {removed.key}）"
            )
        elif evicted:
            removed = "、".join(
                f"{favorite.trigger}（key: {favorite.key}）"
                for favorite in evicted
            )
            lines.append(f"收藏上限已降低，已移除较早收藏：{removed}")
        yield event.plain_result("\n".join(lines))

    @filter.command("meme工坊收藏夹", alias={"meme收藏夹"})
    async def favorite_list(self, event: AstrMessageEvent):
        """查看当前用户的 Meme 收藏夹。"""
        try:
            async with self._storage_lock:
                favorites = await self._load_favorites(event)
        except Exception as exc:  # noqa: BLE001 - storage backends vary by install
            logger.exception("[meme_forge] 读取收藏失败")
            yield event.plain_result(f"收藏读取失败：{exc}")
            return

        if not favorites:
            yield event.plain_result(
                "你的收藏夹还是空的。请引用 Bot 发送的 meme 后回复 /meme收藏。"
            )
            return

        lines = [f"你的 Meme 收藏（{len(favorites)} 个）："]
        for index, entry in enumerate(favorites, start=1):
            meme = self.engine.resolve(entry.key)
            trigger = entry.trigger
            status = ""
            if meme is None:
                status = "，当前未加载"
            elif self.engine.resolve(trigger) is not meme:
                trigger = self._preferred_trigger(meme)
            lines.append(
                f"{index}. {trigger}（key: {entry.key}{status}）"
                f"\n   命令：{self._format_trigger_command(trigger)}"
            )
        lines.append("使用 /meme取消收藏 <触发词> 可移除收藏。")
        yield event.plain_result("\n".join(lines))

    @filter.command("meme工坊取消收藏", alias={"meme取消收藏"})
    async def unfavorite_meme(
        self,
        event: AstrMessageEvent,
        keyword: str | None = None,
    ):
        """Remove one meme from the current user's favorites."""
        if not keyword:
            yield event.plain_result("请指定要取消收藏的 meme 触发词。")
            return

        result_message: str | None = None
        key: str | None = None
        try:
            async with self._storage_lock:
                favorites = await self._load_favorites(event)
                key = self.engine.canonical_key(keyword)
                if key is None:
                    key = next(
                        (
                            entry.key
                            for entry in favorites
                            if entry.key.casefold() == keyword.casefold()
                            or entry.trigger.casefold() == keyword.casefold()
                        ),
                        None,
                    )
                if key is None:
                    result_message = f"没有找到 meme：{keyword}"
                else:
                    updated, removed = remove_favorite(favorites, key)
                    if not removed:
                        result_message = f"{key} 当前不在收藏夹中。"
                    else:
                        await self._save_favorites(event, updated)
        except Exception as exc:  # noqa: BLE001 - storage backends vary by install
            logger.exception("[meme_forge] 删除收藏失败")
            yield event.plain_result(f"取消收藏失败：{exc}")
            return
        if result_message is not None:
            yield event.plain_result(result_message)
            return
        assert key is not None
        yield event.plain_result(f"已取消收藏：{key}")

    async def _generate_meme(
        self,
        event: AstrMessageEvent,
        meme: Any,
        argument_text: str,
    ) -> tuple[bytes, dict[str, Any]]:
        """Collect event input and run one meme through the shared safeguards."""
        params = self.engine.get_params(meme)
        inputs = await self.collector.collect(event, params, argument_text)

        wait_timeout = min(10.0, float(self._config_value("generation_timeout", 30)))
        try:
            await asyncio.wait_for(self._generation_slots.acquire(), wait_timeout)
        except asyncio.TimeoutError as exc:
            raise GenerationBusyError from exc

        try:
            timeout = float(self._config_value("generation_timeout", 30))
            image = await asyncio.wait_for(
                self.engine.generate(meme, inputs),
                timeout=timeout,
            )
        finally:
            self._generation_slots.release()

        if self._config_value("compress_output", True):
            max_size = max(128, int(self._config_value("max_output_size", 512)))
            try:
                image = await asyncio.to_thread(compress_static_image, image, max_size)
            except (OSError, ValueError) as exc:
                logger.warning("[meme_forge] 输出图片压缩失败，发送原图: %s", exc)

        return image, inputs.options

    @filter.command("meme工坊随机", alias={"随机meme"})
    async def random_meme(self, event: AstrMessageEvent):
        """从当前已加载且未禁用的完整 meme 库中随机生成一个。"""
        meme = self.engine.random_meme()
        if meme is None:
            yield event.plain_result("当前没有可用的 meme，请检查资源或禁用列表。")
            return

        event.stop_event()
        self._remember_meme(event, meme)
        try:
            image, option_values = await self._generate_meme(event, meme, "")
        except InputCollectionError as exc:
            yield event.plain_result(
                f"随机选中的 meme「{meme.key}」无法使用当前输入：{exc}"
            )
            return
        except GenerationBusyError:
            yield event.plain_result("当前生成任务较多，请稍后再试。")
            return
        except asyncio.TimeoutError:
            logger.warning("[meme_forge] 随机生成 %s 超时", meme.key)
            yield event.plain_result("随机 meme 生成超时。")
            return
        except MemeGenerationError as exc:
            yield event.plain_result(str(exc))
            return
        except Exception:  # noqa: BLE001 - native generators expose varied failures
            logger.exception("[meme_forge] 随机生成 %s 时发生异常", meme.key)
            yield event.plain_result("随机 meme 生成失败，请查看 AstrBot 日志。")
            return

        await self._remember_generated_output(
            event,
            meme,
            image,
            track_usage=True,
        )
        logger.info(
            "[meme_forge] 随机 meme=%s option_keys=%s",
            meme.key,
            sorted(option_values),
        )
        yield event.chain_result([Comp.Image.fromBytes(image)])

    @filter.command("meme工坊最近", alias={"最近meme"})
    async def recent_memes(self, event: AstrMessageEvent):
        """Show this sender's latest three distinct meme triggers."""
        history = self._recent_memes.get(self._recent_history_key(event), [])
        if not history:
            yield event.plain_result("你还没有触发过 meme。")
            return

        lines = ["最近触发的 meme（从新到旧）："]
        for index, (name, key) in enumerate(history, start=1):
            lines.append(f"{index}. {name}（key: {key}）")
        yield event.plain_result("\n".join(lines))

    @filter.command("meme工坊本群最近", alias={"meme群最近"})
    async def conversation_recent_memes(self, event: AstrMessageEvent):
        """查看当前群聊或私聊中最近成功生成的 meme。"""
        records = self._usage_history.recent(
            session=event.unified_msg_origin,
            limit=10,
        )
        if not records:
            yield event.plain_result("当前会话还没有成功生成记录。")
            return
        lines = ["当前会话最近生成的 meme："]
        for index, record in enumerate(records, start=1):
            lines.append(
                f"{index}. {record.sender_name}：{record.trigger}（key: {record.key}）"
            )
        yield event.plain_result("\n".join(lines))

    @filter.command("meme工坊全局最近", alias={"meme全局最近"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def global_recent_memes(self, event: AstrMessageEvent):
        """查看全部会话中最近成功生成的 meme（管理员）。"""
        records = self._usage_history.recent(limit=15)
        if not records:
            yield event.plain_result("还没有成功生成记录。")
            return
        lines = ["全局最近生成的 meme："]
        for index, record in enumerate(records, start=1):
            lines.append(
                f"{index}. {record.sender_name}：{record.trigger}（{record.session}）"
            )
        yield event.plain_result("\n".join(lines))

    @filter.event_message_type(EventMessageType.ALL)
    async def meme_handle(self, event: AstrMessageEvent):
        """匹配触发词并生成 meme。"""
        if self._config_value("require_wake", True) and not event.is_at_or_wake_command:
            return

        scoped_text = strip_trigger_prefix(
            event.message_str,
            str(self._config_value("trigger_prefix", "meme")),
        )
        if scoped_text is None:
            return
        match = self.engine.match(
            scoped_text,
            fuzzy=bool(self._config_value("fuzzy_match", False)),
        )
        if match is None:
            return

        if self.engine.is_disabled(match.meme):
            return
        event.stop_event()
        self._remember_meme(event, match.meme, match.trigger)

        try:
            image, option_values = await self._generate_meme(
                event,
                match.meme,
                match.argument_text,
            )
        except InputCollectionError as exc:
            yield event.plain_result(f"参数解析失败：{exc}")
            return
        except GenerationBusyError:
            yield event.plain_result("当前生成任务较多，请稍后再试。")
            return
        except asyncio.TimeoutError:
            logger.warning("[meme_forge] 生成 %s 超时", match.meme.key)
            yield event.plain_result("meme 生成超时。")
            return
        except MemeGenerationError as exc:
            yield event.plain_result(str(exc))
            return
        except Exception:  # noqa: BLE001 - native generators expose varied failures
            logger.exception("[meme_forge] 生成 %s 时发生异常", match.meme.key)
            yield event.plain_result("meme 生成失败，请查看 AstrBot 日志。")
            return

        await self._remember_generated_output(
            event,
            match.meme,
            image,
            match.trigger,
            track_usage=True,
        )
        logger.info(
            "[meme_forge] 触发 meme=%s trigger=%s option_keys=%s",
            match.meme.key,
            match.trigger,
            sorted(option_values),
        )
        yield event.chain_result([Comp.Image.fromBytes(image)])

    async def terminate(self) -> None:
        """Cancel background work and close network sessions."""
        if self._resource_task and not self._resource_task.done():
            self._resource_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._resource_task
        await self.collector.close()
        await self.extension.close()
        await self.gouqi_extension.close()
        try:
            await self.grabber.cleanup_all()
        except OSError as exc:
            logger.warning("[meme_forge] 清理提取文件失败: %s", exc)
