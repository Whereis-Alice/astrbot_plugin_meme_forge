# Meme 工坊

Meme 工坊是面向 AstrBot 4.x 的本地 meme 表情包生成插件。它使用独立的
`astrbot_plugin_meme_forge` 标识和默认 `/meme` 触发前缀，可以与旧版
`astrbot_plugin_memelite` 并存。

除了常规生成，插件还提供完整参数解析、随机 meme、个人收藏、QQ 表情提取、
`meme_emoji` 扩展，以及用于查看和管理表情库的 AstrBot Dashboard 页面。

## 功能概览

- 自动读取运行时 meme 元数据，支持自然别名、`key=value` 和命令行风格参数。
- 正确传递单个 meme 的选项，例如 `/meme 奶茶 左手`、`/meme 奶茶 position=left`。
- 从所有已加载且未禁用的 meme 中随机生成，安装扩展后的 meme 也会参与随机。
- 按“平台 + 用户 ID”独立、跨重启保存的个人收藏夹。
- 引用当前或历史消息，提取普通图片和 QQ OneBot 可访问的表情为可保存文件。
- 提供最近使用记录：个人最近 3 个、当前会话最近记录、管理员全局记录。
- 在 Dashboard 中搜索、筛选、预览、查看参数与素材、启停单个 meme，并查看最近生成记录。

## 安装

要求：

- AstrBot `>=4.16,<5`
- Python 3.10 或更高版本
- 可访问 PyPI；首次下载生成资源或安装扩展时还需要访问 GitHub/CDN

将 `astrbot_plugin_meme_forge` 放入 AstrBot 的 `data/plugins` 目录，然后在插件管理页面重载插件。
AstrBot 会根据 `requirements.txt` 安装依赖：

```text
meme_generator>=0.2.3,<0.3
tomlkit>=0.13,<1
```

首次使用若缺少生成资源，请由管理员执行：

```text
/meme工坊资源检查
```

资源检查在可超时终止的独立进程中运行，默认不会在每次启动时阻塞 AstrBot。
部分精简 Linux 或 Docker 镜像可能需要图形运行库，例如 Debian/Ubuntu：

```bash
apt-get update && apt-get install -y libegl1 libgl1 libglib2.0-0
```

## 生成表情

默认触发格式为：

```text
/meme <关键词> [文本或参数]
```

例如：

```text
/meme 奶茶 左手
/meme 奶茶 双手
/meme 奶茶 position=left
/meme 奶茶 --position both
/meme 对称 上
/meme 喜报 "今天放假"
```

若希望使用 `/奶茶 左手` 这样的直接关键词形式，可将 `trigger_prefix` 设为空。
此模式可能与其他 meme 插件同时响应同一消息；仍在使用 memelite 时，建议保留默认前缀。

### 参数规则

插件从每个 meme 的运行时参数定义中读取类型、选项、范围和别名。可使用：

| 写法 | 示例 | 说明 |
|---|---|---|
| 自然别名 | `/meme 奶茶 左手` | 使用 meme 声明的中文或短别名 |
| 键值 | `/meme 奶茶 position=left` | 支持字符串、整数、浮点数和布尔值 |
| 长选项 | `/meme 奶茶 --position both` | 命令行风格写法 |
| 布尔开关 | `/meme 对称 --top` | 也支持 `--top=false`、`--no-top` |
| 带空格文本 | `/meme 喜报 "今天 放假"` | 引号内作为同一段文本 |

查看某个 meme 可用的图片数、文字数和选项：

```text
/meme工坊详情 奶茶
```

## 指令

| 指令 | 权限 | 说明 |
|---|---|---|
| `/meme工坊帮助` | 所有人 | 输出当前已加载 meme 的列表图 |
| `/meme工坊详情 <关键词>` | 所有人 | 查看一个 meme 的预览、输入数量和参数 |
| `/meme工坊随机` | 所有人 | 从当前可用表情库随机生成一个 meme |
| `/meme工坊最近` | 所有人 | 查看自己本次插件运行期间最近触发的 3 个不同 meme |
| `/meme工坊本群最近` | 所有人 | 查看当前群聊或私聊最近成功生成的 meme |
| `/meme工坊全局最近` | 管理员 | 查看全部会话最近成功生成的 meme |
| `/meme工坊收藏` | 所有人 | 引用 Bot 发送的 meme 后收藏 |
| `/meme工坊收藏夹` | 所有人 | 查看自己的收藏和可复用命令 |
| `/meme工坊取消收藏 <关键词>` | 所有人 | 从自己的收藏夹移除一项 |
| `/meme工坊提取` | 所有人 | 提取当前消息或引用消息中的图片、可访问 QQ 表情 |
| `/meme工坊黑名单` | 所有人 | 查看禁用列表 |
| `/meme工坊禁用 <关键词>` | 管理员 | 禁用一个 meme |
| `/meme工坊启用 <关键词>` | 管理员 | 重新启用一个 meme |
| `/meme工坊资源检查` | 管理员 | 检查并下载 meme-generator 资源 |
| `/meme工坊扩展状态` | 所有人 | 查看 `meme_emoji` 扩展状态 |
| `/meme工坊扩展安装 确认` | 管理员 | 下载或更新扩展，完成后重启 AstrBot |

常用短别名包括 `/随机meme`、`/最近meme`、`/meme收藏`、`/meme收藏夹`、
`/meme提取` 和 `/提取meme`。为降低与其他插件的冲突，优先使用完整的“meme工坊”命名空间。

## 收藏夹

引用 Bot 通过 Meme 工坊发送的图片，然后发送：

```text
/meme收藏
```

之后使用：

```text
/meme收藏夹
```

收藏按“平台 + 用户 ID”隔离，**会写入 AstrBot 的插件 KV 存储，因此重启后仍会保留**。
它会一直保存，直到用户执行取消收藏、超出 `max_favorites` 上限导致最早条目被移除，或管理员删除插件数据。
收藏夹默认上限为每位用户 50 项；重复收藏同一 meme 会将该项移到最前面。

收藏功能保存的是图片指纹、meme key 和触发词，不保存图片内容。它只能识别插件近期产生并已建立索引的图片；被平台大幅裁剪、加水印，或升级到支持收藏功能前发送的旧图，可能无法匹配。

## 表情提取

`/meme工坊提取` 会优先读取当前消息中的图片；没有可读图片时，也会检查引用消息。
在 QQ OneBot 适配器中，如果引用消息的普通链路没有带出表情图片，插件会尝试通过 `get_msg` 和 `get_image` 获取 `mface` 或图片文件。

- 普通静态图可以配置为图片或文件发送。
- GIF、APNG、WebP 等可能为动画的表情固定作为文件发送，避免丢失动画帧。
- 提取文件保存在插件数据目录的临时缓存中，按 `grabber_retention_minutes` 延迟清理，不会在消息刚发出时立即删除。
- 可通过白名单或黑名单限制群聊；私聊不受群列表限制。
- QQ 官方表情是否可提取取决于 OneBot 实现是否提供可下载的图片/文件标识。平台未提供时，插件不会伪造或绕过访问限制。

## Dashboard WebUI

重载插件后，在 AstrBot Dashboard 的插件页面打开 **Meme 工坊**。页面支持浅色和夜间主题，并提供：

- 名称、关键词、标签和启用状态筛选。
- 单个 meme 启用或禁用，变更会立即保存到 `disabled_memes`。
- 运行时输入数量、默认文本、自然别名、参数 flag、枚举值和数值范围。
- 按需生成的 meme 预览，以及 `$MEME_HOME/resources/images/<meme key>` 下可用的素材图片。
- 全局最近成功生成记录，或按会话筛选查看群友/私聊参与者的最近触发情况。

页面所有接口均通过 AstrBot Plugin Page Bridge 访问；预览和素材以受大小限制的 data URL 返回，页面不会暴露服务器上的绝对路径。Dashboard 管理员可见的最近记录不含生成图片，只包含触发词、meme key、平台、会话、用户和时间。

## meme_emoji 扩展

用户指定的 [`anyliew/meme_emoji`](https://github.com/anyliew/meme_emoji) Python 仓库面向
`meme_generator==0.1.14`，直接安装会要求旧版 Pillow，可能破坏现有 AstrBot 环境。

因此本插件不降级 AstrBot 依赖，而是使用其 README 指向的
[`anyliew/meme-emoji`](https://github.com/anyliew/meme-emoji) Rust 兼容实现：

1. 从 GitHub Release 选择当前平台的动态库。
2. 校验上游提供的 SHA-256；未提供校验值时拒绝安装。
3. 从同一 release 下载资源包，只安全解压 `resources` 目录。
4. 将动态库和资源安装到 `$MEME_HOME`，并启用 `load_external_memes`。
5. 重启 AstrBot 后，扩展 meme 会和内置 meme 一起被加载、随机选择和管理。

安装命令：

```text
/meme工坊扩展安装 确认
```

安装前请预留约 1.1 GB 可用空间。动态库与资源不包含在本插件发布包中，且仍分别受上游的许可证、免责声明和资源权利说明约束。

## 配置

### 生成与收藏

| 配置项 | 默认值 | 说明 |
|---|---:|---|
| `require_wake` | `true` | 群聊是否遵循 AstrBot 唤醒规则 |
| `trigger_prefix` | `meme` | 生成触发前缀；设为空可直接使用关键词 |
| `fuzzy_match` | `false` | 在整条消息中模糊查找关键词，可能增加误触发 |
| `keyword_aliases` | `[]` | 自定义关键词到现有 key/关键词的映射 |
| `disabled_memes` | `[]` | 已禁用 meme 的稳定 key 列表 |
| `max_favorites` | `50` | 每位用户最多收藏数 |
| `generation_timeout` | `30` | 单次生成超时（秒） |
| `max_parallel_generations` | `2` | 同时运行的生成任务数，重载后生效 |
| `compress_output` | `true` | 是否压缩过大的静态图 |
| `max_output_size` | `512` | 静态输出图最大边长 |
| `max_input_image_mb` | `20` | 单张输入图片大小上限（MB） |

### 资源、扩展与 Dashboard

| 配置项 | 默认值 | 说明 |
|---|---:|---|
| `check_resources_on_start` | `false` | 启动后后台检查资源 |
| `resource_check_timeout` | `180` | 资源检查超时（秒） |
| `extension_download_timeout` | `1800` | 扩展下载超时（秒） |
| `history_limit` | `500` | 持久化最近成功生成记录上限，范围 100-2000 |
| `dashboard_preview_max_mb` | `4` | 单张 WebUI 预览/素材传输上限（MB） |

### 表情提取

| 配置项 | 默认值 | 说明 |
|---|---:|---|
| `grabber_enabled` | `true` | 是否启用提取命令 |
| `grabber_send_mode` | `file` | 静态图优先作为文件或图片发送 |
| `grabber_max_files` | `8` | 单次最大提取文件数，范围 1-20 |
| `grabber_retention_minutes` | `60` | 临时提取文件保留时间，范围 5-10080 分钟 |
| `grabber_list_mode` | `disabled` | 群聊范围：关闭、白名单或黑名单 |
| `grabber_group_list` | 空 | 群号列表，每行一个 |

## 数据、隐私与网络

- 个人收藏、生成输出索引和最近生成记录保存在 AstrBot 的插件隔离 KV 存储中。
- 收藏和输出索引不保存图片内容；输出索引只存图片指纹、会话、meme key 和触发词。
- 最近生成记录只保存 meme key、触发词、平台、会话、发送者 ID/名称和时间；数量受 `history_limit` 限制。
- `/meme工坊最近` 只保留当前插件运行期间每位用户最近的 3 个不同 meme；它不是持久记录。
- Dashboard 中的全局和会话记录面向拥有 AstrBot Dashboard 权限的管理员，请按部署环境的隐私要求配置权限。
- 生成资源和扩展安装会访问上游 GitHub/CDN；用户图片下载只接受 HTTP/HTTPS，并受超时和大小限制。

## 常见问题

### `/奶茶 左手` 没有响应

默认模式要求 `/meme 奶茶 左手`。如需直接关键词形式，将 `trigger_prefix` 设为空，并确认群聊符合 AstrBot 的唤醒规则。

### `奶茶 左手` 仍然生成右手版本

先执行 `/meme工坊详情 奶茶` 或在 WebUI 中查看该版本运行时暴露的参数。通常可使用 `/meme 奶茶 左手`、`/meme 奶茶 position=left` 或 `/meme 奶茶 --position left`。插件不会为某个 meme 写死特殊规则，而是按照当前引擎的参数元数据解析。

### 扩展安装完成但列表没有新增 meme

先重启 AstrBot，再执行 `/meme工坊扩展状态`。确认动态库校验、资源目录和外部加载均正常；若仍失败，请查看 AstrBot 日志中的 ABI 或系统库错误。

### WebUI 中没有素材图片

素材只在本机已下载的 `$MEME_HOME/resources/images/<meme key>` 中显示。未下载资源、该 meme 没有素材目录，或图片超过 `dashboard_preview_max_mb` 时，页面不会显示可查看的素材。

## 许可证

本项目派生自 AGPL-3.0-or-later 上游，代码继续使用
[GNU Affero General Public License v3.0 or later](LICENSE)。完整的第三方来源、许可证和边界说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 致谢

- [`Zhalslar/astrbot_plugin_memelite`](https://github.com/Zhalslar/astrbot_plugin_memelite)：AstrBot 对接、消息输入、参数收集和管理思路的上游参考。
- [`XTsat/astrbot_plugin_meme_grabber`](https://github.com/XTsat/astrbot_plugin_meme_grabber)：表情提取交互和 QQ OneBot 回退处理的上游参考；其公开 issue 在本次整合时为 0。
- [`anyliew/meme_emoji`](https://github.com/anyliew/meme_emoji) 与 [`anyliew/meme-emoji`](https://github.com/anyliew/meme-emoji)：扩展表情和 Rust 兼容实现来源。
- [`MemeCrafters/meme-generator-rs`](https://github.com/MemeCrafters/meme-generator-rs)：实际使用的 meme 生成引擎。
