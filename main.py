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

from .core.arguments import strip_trigger_prefix
from .core.collector import InputCollectionError, ParamsCollector
from .core.engine import MemeEngine, MemeEngineError, MemeGenerationError
from .core.extensions import ExtensionInstallError, MemeEmojiExtensionManager
from .utils import compress_static_image

PLUGIN_ID = "astrbot_plugin_meme_forge"


class MemeForgePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.collector = ParamsCollector(config)
        self.engine = MemeEngine(config)
        self.extension = MemeEmojiExtensionManager(
            StarTools.get_data_dir(PLUGIN_ID),
            config,
        )
        parallel = max(1, int(self._config_value("max_parallel_generations", 2)))
        self._generation_slots = asyncio.Semaphore(parallel)
        self._resource_task: asyncio.Task[None] | None = None

    def _config_value(self, key: str, default: Any) -> Any:
        try:
            return self.config.get(key, default)
        except AttributeError:
            try:
                return self.config[key]
            except (KeyError, TypeError):
                return default

    async def initialize(self) -> None:
        await self.engine.initialize()
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

        params = self.engine.get_params(match.meme)
        try:
            inputs = await self.collector.collect(event, params, match.argument_text)
        except InputCollectionError as exc:
            yield event.plain_result(f"参数解析失败：{exc}")
            return

        wait_timeout = min(10.0, float(self._config_value("generation_timeout", 30)))
        try:
            await asyncio.wait_for(self._generation_slots.acquire(), wait_timeout)
        except asyncio.TimeoutError:
            yield event.plain_result("当前生成任务较多，请稍后再试。")
            return

        try:
            timeout = float(self._config_value("generation_timeout", 30))
            image = await asyncio.wait_for(
                self.engine.generate(match.meme, inputs),
                timeout=timeout,
            )
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
        finally:
            self._generation_slots.release()

        if self._config_value("compress_output", True):
            max_size = max(128, int(self._config_value("max_output_size", 512)))
            try:
                image = await asyncio.to_thread(compress_static_image, image, max_size)
            except (OSError, ValueError) as exc:
                logger.warning("[meme_forge] 输出图片压缩失败，发送原图: %s", exc)

        logger.info(
            "[meme_forge] 触发 meme=%s trigger=%s option_keys=%s",
            match.meme.key,
            match.trigger,
            sorted(inputs.options),
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
