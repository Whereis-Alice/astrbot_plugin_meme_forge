# Third-Party Notices

## astrbot_plugin_memelite

- Project: https://github.com/Zhalslar/astrbot_plugin_memelite
- Author: Zhalslar and contributors
- License: GNU Affero General Public License v3.0 or later

Meme 工坊派生并重构了该项目的 AstrBot 对接、参数收集和 meme 管理思路。
本仓库的 `LICENSE` 保留相同的 AGPL-3.0-or-later 许可条件。

## meme_emoji

- Project: https://github.com/anyliew/meme_emoji
- Maintainer: anyliew and contributors
- License file: MIT License, copyright (c) 2021 MeetWq

该仓库是用户指定的表情扩展来源。它声明只兼容 Python 版
`meme_generator==0.1.14`。Meme 工坊不会把该旧版依赖安装进 AstrBot 环境，
以免降级 Pillow 或破坏 AstrBot 的核心依赖约束。

## meme-emoji

- Project: https://github.com/anyliew/meme-emoji
- Maintainer: anyliew and contributors
- License: MIT License

这是 `meme_emoji` README 指向的 Rust 兼容版本。Meme 工坊的可选扩展安装器从其
GitHub Releases 下载平台动态库，并从同一 release 标签同步资源。动态库和资源不随
本插件源码分发，安装后仍受该项目的许可证、免责声明及资源权利说明约束。

## meme-generator-rs

- Project: https://github.com/MemeCrafters/meme-generator-rs
- Maintainers: MemeCrafters contributors
- License: MIT License

The `meme_generator` Python package is the runtime generation engine. It is
installed separately from PyPI through `requirements.txt` and is not copied
into this plugin repository.

## astrbot_plugin_meme_grabber

- Project: https://github.com/XTsat/astrbot_plugin_meme_grabber
- Author: XTsat and contributors
- License: GNU Affero General Public License v3.0 or later

本插件参考该项目的消息/引用表情提取交互，并将其功能重新实现为独立的
`MemeGrabber` 模块。实现不依赖上游的内部 `AiocqhttpMessageEvent` 类型，避免
AstrBot 或平台适配器升级造成的硬耦合；普通图片下载、大小限制和协议校验复用
本插件已有的输入收集器。提取结果会暂存到插件数据目录，并按配置延迟清理，
避免消息发送尚未完成时删除临时文件。

## No Endorsement

References to upstream project names identify technical provenance only. They
do not imply that the upstream maintainers endorse this fork or provide support
for it. Please report Meme 工坊 integration problems to this project's
maintainer; report template or resource defects to the repository that owns the
affected template or resource.
