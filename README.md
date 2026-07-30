# Meme 工坊

Meme 工坊是一个面向 AstrBot 4.x 的本地表情包生成插件。它基于
[`Zhalslar/astrbot_plugin_memelite`](https://github.com/Zhalslar/astrbot_plugin_memelite)
重构，重点解决生成选项无法传递、引用消息取图错误、依赖升级后导入失败和资源检查卡住等问题。

插件使用独立标识 `astrbot_plugin_meme_forge`。默认命令格式为
`/meme <关键词> [文本或参数]`，因此可以和原 `memelite` 插件同时安装而不会抢同一条关键词消息。

## 主要功能

- 对接当前 `meme_generator 0.2.x`，在本地生成静态图和 GIF。
- 自动读取每个 meme 的参数定义，不依赖“奶茶”“对称”等硬编码特例。
- 支持自然参数、`key=value` 和命令行风格参数。
- 提供 `/meme工坊随机`，从当前已加载且未禁用的完整表情库中随机生成一个 meme；按需安装的 `meme_emoji` 扩展也会自动参与随机选择。
- 支持当前消息图片、引用图片、引用文字、@用户和纯文本 QQ 号头像。
- 支持关键词别名、禁用列表、生成超时、并行数限制和静态大图压缩。
- 提供可终止的资源检查命令，网络异常不会无限阻塞 AstrBot 启动。
- 可按需接入 `anyliew/meme_emoji` 系列表情，扩展文件不会塞进插件安装包。

## 已处理的上游问题

| 上游记录 | 本插件的处理 |
|---|---|
| [#35](https://github.com/Zhalslar/astrbot_plugin_memelite/issues/35)、[#49](https://github.com/Zhalslar/astrbot_plugin_memelite/issues/49)、[#57](https://github.com/Zhalslar/astrbot_plugin_memelite/issues/57) 新版 API 导入失败 | 不再 `from meme_generator import Meme`，按 0.2.x 对象 API 读取元数据，并恢复依赖安装阶段遗留的临时 namespace module |
| [#47](https://github.com/Zhalslar/astrbot_plugin_memelite/issues/47) 资源检查卡住 | 默认不在启动时检查；手动检查运行在可超时终止的子进程中 |
| [#50](https://github.com/Zhalslar/astrbot_plugin_memelite/issues/50) 部分表情参数无效 | 从运行时参数元数据解析布尔别名、枚举、类型和范围 |
| [#51](https://github.com/Zhalslar/astrbot_plugin_memelite/issues/51) 引用图片被头像替代 | 引用图片和当前显式图片排在自动头像补位之前 |
| [#30](https://github.com/Zhalslar/astrbot_plugin_memelite/issues/30) 额外前缀混入文字 | 在关键词匹配前按边界移除专属前缀，只把关键词后的内容交给参数解析 |
| [PR #54](https://github.com/Zhalslar/astrbot_plugin_memelite/pull/54) 显式名称被覆盖 | `name`/`gender` 作为收集器元参数处理，平台信息只用于缺省补充 |
| [PR #56](https://github.com/Zhalslar/astrbot_plugin_memelite/pull/56) 别名和管理文案 | 支持 WebUI 动态别名，并使用独立、明确的启用/禁用命令文案 |

## 安装

要求：

- AstrBot `>=4.16,<5`
- Python 3.10 或更高版本
- 可访问 PyPI；下载表情资源时还需要访问 GitHub/CDN

将 `astrbot_plugin_meme_forge` 目录安装到 AstrBot 的 `data/plugins`，然后在插件管理页重载插件。
AstrBot 会根据 `requirements.txt` 安装：

```text
meme_generator>=0.2.3,<0.3
tomlkit>=0.13,<1
```

首次生成若提示缺少资源，由管理员执行：

```text
/meme工坊资源检查
```

资源检查在独立子进程中运行，并受配置的超时时间限制。默认不会在每次启动时自动检查。

部分精简 Linux 或 Docker 镜像可能缺少图形运行库，可按发行版安装相应软件包。例如 Debian/Ubuntu：

```bash
apt-get update && apt-get install -y libegl1 libgl1 libglib2.0-0
```

## 快速开始

下面示例假设 AstrBot 的唤醒前缀为 `/`，插件的 `trigger_prefix` 保持默认值 `meme`：

```text
/meme 奶茶 左手
/meme 奶茶 双手
/meme 奶茶 position=left
/meme 奶茶 --position both
/meme 对称 上
/meme 喜报 "今天放假"
```

希望继续使用 `/奶茶 左手` 这种直接关键词形式时，可在插件配置中将 `trigger_prefix` 设为空字符串。
如果原 `memelite` 仍处于启用状态，不建议开启直接关键词模式，否则两个插件都可能响应同一条消息。

### 图片和引用

- 当前消息附带的图片会作为生成输入。
- 回复一条图片消息再发送 `/meme 摸`，会优先使用被回复的图片，不会先拿发送者头像补位。
- 回复一条文字消息再使用需要文字的 meme，引用文字会在显式文字不足时补入。
- 在 QQ/OneBot 平台可使用真实 @。也可写 `/meme 摸 @114514` 获取指定 QQ 头像。
- 输入不足时才会尝试补发送者和机器人头像；非 QQ 平台不会生成随机 QQ 号冒充头像。

## 参数规则

插件读取 `meme.info.params.options`，所以新版本生成器增加的选项通常无需修改插件即可使用。

| 写法 | 示例 | 说明 |
|---|---|---|
| 自然别名 | `/meme 奶茶 左手` | 匹配 meme 声明的中文长短别名 |
| 键值 | `/meme 奶茶 position=left` | 支持字符串、整数、浮点和布尔类型 |
| 长选项 | `/meme 奶茶 --position left` | 兼容常见命令行写法 |
| 布尔开关 | `/meme 奶茶 --left` | 也支持 `--left=false`、`--no-left` |
| 引号文本 | `/meme 喜报 "今天 放假"` | 引号中的内容作为同一段文本 |

参数会检查枚举值和数值范围。拼错参数时插件会返回具体错误，不会把无效选项悄悄传给生成器。
可用参数可通过下面的详情命令查询：

```text
/meme工坊详情 奶茶
```

## 管理命令

| 命令 | 权限 | 说明 |
|---|---|---|
| `/meme工坊帮助` | 所有人 | 查看当前已加载的 meme 列表 |
| `/meme工坊详情 <关键词>` | 所有人 | 查看图片数、文本数、选项和预览 |
| `/meme工坊随机` | 所有人 | 从当前已加载且未禁用的完整表情库中随机生成一个 meme；别名为 `/随机meme` |
| `/meme工坊最近` | 所有人 | 查看自己最近触发的 3 个不同 meme；别名为 `/最近meme` |
| `/meme工坊黑名单` | 所有人 | 查看禁用列表 |
| `/meme工坊禁用 <关键词>` | 管理员 | 按稳定的 meme key 禁用 |
| `/meme工坊启用 <关键词>` | 管理员 | 重新启用 |
| `/meme工坊资源检查` | 管理员 | 检查并下载内置资源 |
| `/meme工坊扩展状态` | 所有人 | 查看 `meme_emoji` 扩展文件状态 |
| `/meme工坊扩展安装 确认` | 管理员 | 安装或更新扩展，完成后需重启 |

所有管理命令都使用“Meme 工坊”命名空间，不会覆盖原插件的 `/meme帮助`、`/禁用meme` 等命令。

`/meme工坊最近` 按发送者和平台分别记录当前插件运行期间的最近 3 个不同 meme，按最近触发到最早触发排列。输出中的触发词可以直接用于下一次 `/meme <触发词>`；插件重启后历史会清空。

## 接入 meme_emoji

用户指定的 [`anyliew/meme_emoji`](https://github.com/anyliew/meme_emoji) 仓库明确只兼容
`meme_generator==0.1.14`。这个旧版本要求 `Pillow<11`，会和当前 AstrBot 的 Pillow 版本发生依赖保护冲突。
直接降级会重现 `astrbot_plugin_memelite` 的依赖类 Issues，因此本插件不会修改或降级 AstrBot 的核心依赖。

`meme_emoji` README 为当前 Rust 版生成器指定了同作者维护的
[`anyliew/meme-emoji`](https://github.com/anyliew/meme-emoji)。Meme 工坊的扩展安装器会：

1. 从该仓库最新 GitHub Release 选择当前系统和 CPU 对应的动态库。
2. 校验 GitHub 提供的 SHA-256；缺少校验值时拒绝安装。
3. 从同一 release 标签下载资源源码包，只安全解压 `resources` 目录。
4. 将动态库和资源放入 `$MEME_HOME`，并用 TOML 解析器开启 `load_external_memes`。
5. 记录安装版本、哈希和资源数量，供状态命令核对。

安装并重启后，扩展 meme 会进入生成器的运行时列表，因此 `/meme工坊随机` 会和内置 meme 一起随机选择它们。随机命令仍会使用当前消息、引用内容和平台头像作为输入；如果随机到的 meme 需要图片而当前消息没有可用图片，插件会明确提示缺少输入。

安装前请注意：

- 动态库约 16–18 MB，资源约 416 MB。
- 下载与解压期间至少需要约 1.1 GB 可用磁盘空间。
- 支持 Windows x86_64、Linux x86_64/ARM64、macOS Intel/Apple Silicon 和 Android ARM64。
- 动态库只会在 `meme_generator` 初始化时加载，因此安装或更新后必须重启 AstrBot。
- 上游动态库必须与 `meme_generator` 的 Rust 核心 ABI 兼容；若日志提示版本不兼容，请等待上游发布匹配构建。
- 图片资源来自第三方仓库，使用前请阅读其许可证、免责声明和内容说明。

安装命令：

```text
/meme工坊扩展安装 确认
```

插件本体不包含这 400+ MB 资源，卸载插件也不会自动删除 `$MEME_HOME` 中由生成器共用的资源。

## 配置

| 配置项 | 默认值 | 说明 |
|---|---:|---|
| `require_wake` | `true` | 群聊要求 AstrBot 唤醒前缀或 @机器人 |
| `trigger_prefix` | `"meme"` | 插件专属触发前缀；设为空可直接用关键词 |
| `fuzzy_match` | `false` | 在整条消息中搜索触发词，开启后更易误触 |
| `keyword_aliases` | `[]` | 自定义触发词到已有名称/关键词的映射 |
| `disabled_memes` | `[]` | 禁用列表，建议通过管理命令维护 |
| `generation_timeout` | `30` | 单次生成超时，单位秒 |
| `max_parallel_generations` | `2` | 同时运行的生成任务数量，重载后生效 |
| `compress_output` | `true` | 压缩过大的静态图片，不处理 GIF |
| `max_output_size` | `512` | 静态输出图片最大边长 |
| `max_input_image_mb` | `20` | 每张输入图片大小上限 |
| `check_resources_on_start` | `false` | 是否在启动后后台检查资源 |
| `resource_check_timeout` | `180` | 资源检查最长运行秒数 |
| `extension_download_timeout` | `1800` | 扩展大文件下载超时，重载后生效 |

## 常见问题

### 输入 `/奶茶 左手` 没有响应

默认隔离模式要求 `/meme 奶茶 左手`。如需直接关键词命令，请将 `trigger_prefix` 设为空。
群聊还需要满足 AstrBot 自身的唤醒规则。

### `奶茶 左手` 仍生成右手版本

先执行 `/meme工坊详情 奶茶`，确认当前生成器暴露了 `left`/`左手` 参数。
本插件会将 `左手` 解析为布尔选项 `left=true`。也可使用更明确的
`/meme 奶茶 position=left` 进行验证。

### 提示缺少图片或字体资源

执行 `/meme工坊资源检查`。若超时，检查容器 DNS、代理和对 GitHub/CDN 的访问；子进程会在超时后被终止，不需要重启来解除卡住状态。

### 扩展安装完成但列表没有新增表情

先重启 AstrBot，再执行 `/meme工坊扩展状态`。确认动态库校验、资源目录和外部加载三项均正常，随后查看日志中是否有 ABI 不兼容或缺少系统库的信息。

## 数据与网络

- 插件配置由 AstrBot 管理。
- 扩展安装记录位于 `data/plugin_data/astrbot_plugin_meme_forge`。
- 生成器资源位于 `$MEME_HOME`；未设置环境变量时通常为用户目录下的 `.meme_generator`。
- 输入 URL 只允许 HTTP/HTTPS，保持原 HTTPS，不再强制降级为明文 HTTP。
- 下载受超时和大小限制；扩展动态库必须通过 SHA-256 校验。

## 致谢与上游

本项目特别感谢并参考以下上游项目：

- [`Zhalslar/astrbot_plugin_memelite`](https://github.com/Zhalslar/astrbot_plugin_memelite)：AstrBot 对接流程、消息输入和管理功能的上游参考。本项目是在其 AGPL-3.0 代码基础上的重构与扩展。
- [`anyliew/meme_emoji`](https://github.com/anyliew/meme_emoji)：用户指定接入的 Python 表情扩展来源和内容项目，采用 MIT License。
- [`anyliew/meme-emoji`](https://github.com/anyliew/meme-emoji)：上述扩展面向当前 `meme-generator-rs` 的官方对应实现和 release 构建，采用 MIT License。
- [`MemeCrafters/meme-generator-rs`](https://github.com/MemeCrafters/meme-generator-rs)：实际的表情生成引擎，采用 MIT License。
- `astrbot_plugin_memelite` 的 Issue 与 PR 贡献者，尤其是参数解析 PR #54 和关键词别名 PR #56 提供的复现与改进思路。

完整的来源和许可说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 许可证

由于本项目派生自 AGPL-3.0 上游，插件代码继续使用 **GNU Affero General Public License v3.0 or later**。
运行时下载的第三方动态库与资源仍分别受其上游许可证和声明约束，详见 `THIRD_PARTY_NOTICES.md`。
