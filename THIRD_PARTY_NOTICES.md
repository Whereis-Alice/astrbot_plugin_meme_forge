# Third-Party Notices

## astrbot_plugin_memelite

- Project: https://github.com/Zhalslar/astrbot_plugin_memelite
- Author: Zhalslar and contributors
- License: GNU Affero General Public License v3.0 or later

Meme 工坊派生并重构了该项目的 AstrBot 对接、参数收集和 meme 管理思路。
v1.5.0 进一步参考其 v3.0.4/v3.0.5 的头像缓存和 QQ 官方 Bot 适配，
但使用本项目已有的 HTTPS、超时、响应大小限制和平台无关消息模型重新实现。
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

## meme-generator-gouqi

- Project: https://github.com/amalopyy123/meme-generator-gouqi
- Author: amalopyy123
- Reviewed revision: `40eb41cf7c308315a3186e74954ff011d9c26dd0`
- Declared license at reviewed revision: none

该仓库是可选 Gouqi 扩展的模板设计与素材来源。其 Python 模块依赖旧版
`add_meme` API，Meme 工坊不会导入或执行这些模块，而是针对当前
`meme_generator 0.2.x` 在本项目内提供受限的 Pillow 兼容渲染层。

本插件仓库不包含 Gouqi 上游源码、缓存文件或图片素材。管理员明确确认后，安装器
才会从原仓库的固定审阅提交下载 31 个列入白名单的图片/GIF，并逐项校验路径、大小
和 Git blob 哈希。上游 `master` 的新提交只会在更新检查中报告，不会自动执行。

GitHub 仓库公开可见不代表授予复制、修改、分发或素材使用许可。部署者应在安装前
取得上游作者及相关素材权利人的授权；Meme 工坊的 AGPL-3.0-or-later 许可证不覆盖
运行时下载的 Gouqi 素材。

## sekai-stickers

- Project: https://github.com/TheOriginalAyaka/sekai-stickers
- Author: TheOriginalAyaka and contributors
- License: MIT License
- Reviewed commit: `49189d2e63ed715df5de053261f3bc09d9e817f2`

可选 PJSK 表情工坊的 359 张贴纸底图，以及每张图的默认文字位置、角度和字号，来自该仓库的
`public/img` 与角色定义数据。Meme 工坊不打包这些文件；管理员执行 `/pjsk素材安装 确认` 后，
安装器只从上述固定提交下载清单内的文件，并逐项校验相对路径、字节数和 Git blob 哈希
（底图合计 22,374,334 字节）。

MIT 许可覆盖该仓库的代码与文件组织。贴纸中的角色形象出自 SEGA / Colorful Palette /
Crypton Future Media 的《プロジェクトセカイ カラフルステージ！ feat. 初音ミク》，相关版权归
原权利人所有。本仓库的 AGPL-3.0-or-later 许可证不覆盖运行时下载的这些素材，部署者应确认
自己的使用场景符合原权利人对二次创作的规定。

## nonebot_plugin_pjsk

- Project: https://github.com/Agnes4m/nonebot_plugin_pjsk
- Authors: Agnes4m, lgc-NB2Dev and contributors
- License: MIT License
- Reviewed commit: `9d310136c199e156efc27dfbebebc1f7e72f16bc`

PJSK 表情使用的手写字体 `YurukaFangTang.ttf`（5,152,848 字节）由该仓库分发，安装器从同一
固定提交下载并校验哈希。除这一个字体文件外，本插件没有使用其代码。

## Evaluated but not used

### astrbot_plugin_pjsk

- Project: https://github.com/camera-2018/astrbot_plugin_pjsk
- Author: camera-2018
- Declared license: README 写明 MIT，但仓库内没有 LICENSE 文件

该插件是本项目 PJSK 表情功能的直接功能参考，但其代码没有被引入。原因有三：渲染链路依赖
Playwright + Chromium，插件启动时会自动安装浏览器运行文件与 Linux 系统依赖（可能需要 root
权限），与本项目「只用 Pillow 在本机渲染、不引入浏览器运行时」的边界不符；许可证只在 README
里提到、缺少 LICENSE 文件，再分发条件无法确认；其仓库随包分发了手写字体，本插件改为在管理员
确认后从原始 MIT 仓库下载。Meme 工坊借鉴的是「先看列表、再按编号出图」这一交互形式，并把它
改成带序号的图片总览加全局序号选择。

### meme_maker

- Project: https://github.com/dionaka/meme_maker
- Author: dionaka
- Declared license: none

该仓库启发了本插件的 Meme Maker 功能，但其代码没有被引入：上游是概念验证性质的
固定区域贴图脚本，依赖 OpenCV 与 dlib，且在检视时未声明任何许可证。Meme 工坊的
图层化模板、约束校验和渲染流程均基于本项目已有的 Pillow 成像层独立实现。

### astrbot_plugin_apiver_meme_drawer_arcaea_pjsk

- Project: https://github.com/kamicry/astrbot_plugin_apiver_meme_drawer_arcaea_pjsk
- Author: kamicry
- Declared license: 表述冲突（仓库内同时出现 AGPL 与 MIT 声明）

本插件只借鉴了「分步向导式贴图」这一交互形式，没有引入其代码或资源。不采用的原因：
许可声明自相矛盾，无法确认再分发条件；核心功能依赖用户自行部署的 Vercel 接口，与本
插件「默认本地渲染、不引入外部服务依赖」的边界不符；仓库随包分发约 26 张 SEGA /
lowiro 作品的曲绘，本项目不分发第三方版权素材。

## No Endorsement

References to upstream project names identify technical provenance only. They
do not imply that the upstream maintainers endorse this fork or provide support
for it. Please report Meme 工坊 integration problems to this project's
maintainer; report template or resource defects to the repository that owns the
affected template or resource.
