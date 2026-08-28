<p align="center">
  <img src="assets/logo.svg" alt="Meme 工坊 · MEME FORGE" width="360">
</p>

# Meme 工坊

Meme 工坊是面向 AstrBot 4.x 的本地 meme 表情包生成插件。它使用独立的
`astrbot_plugin_meme_forge` 标识和默认 `/meme` 触发前缀，可以与旧版
`astrbot_plugin_memelite` 并存。

除了常规生成，插件还提供完整参数解析、随机 meme、个人收藏、QQ 表情提取、
`meme_emoji` 与 Gouqi 扩展、自己动手做模板的 Meme Maker，以及用于查看、管理和创作的
AstrBot Dashboard 页面。

## 功能概览

- 自动读取运行时 meme 元数据，支持自然别名、`key=value` 和命令行风格参数。
- 正确传递单个 meme 的选项，例如 `/meme 奶茶 左手`、`/meme 奶茶 position=left`。
- 支持 QQ OneBot 与 QQ 官方 Bot 的头像输入；官方 Bot 使用应用范围内的 `openid`，并兼容常见 At 文本格式。
- 从所有已加载且未禁用的 meme 中随机生成，安装扩展后的 meme 也会参与随机。
- 按“平台 + 用户 ID”独立、跨重启保存的个人收藏夹。
- 引用当前或历史消息，提取普通图片和 QQ OneBot 可访问的表情为可保存文件。
- 提供最近使用记录：个人最近 3 个、当前会话最近记录、管理员全局记录。
- 可选安装 Gouqi 扩展的 10 个自定义模板；素材逐文件校验，安装后立即参与随机、收藏和 WebUI 管理。
- 提供只读更新检查，分别报告内置引擎、`meme_emoji` 和 Gouqi 扩展状态。
- 内置 Meme Maker：用图层化模板自己做表情包，保存后即刻变成可以直接触发的 meme。
- 在 Dashboard 中搜索、筛选、预览、查看参数与素材、启停单个 meme，查看最近生成记录，并在工作台里可视化编辑自制模板。

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
/meme 摸 @114514
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
| 用户头像 | `/meme 摸 @114514` | OneBot 可使用 QQ 号；QQ 官方 Bot 也识别消息链 At、`<@openid>` 和 `<@!openid>` |

查看某个 meme 可用的图片数、文字数和选项：

```text
/meme工坊详情 奶茶
```

## 指令

| 指令 | 权限 | 说明 |
|---|---|---|
| `/meme工坊帮助` | 所有人 | 输出当前已加载 meme 的列表图 |
| `/meme工坊扩展列表` | 所有人 | 只输出当前已加载扩展 meme 的列表图 |
| `/meme工坊详情 <关键词>` | 所有人 | 查看一个 meme 的预览、输入数量和参数 |
| `/meme工坊随机` | 所有人 | 从当前可用表情库随机生成一个 meme |
| `/meme工坊最近` | 所有人 | 查看自己本次插件运行期间最近触发的 3 个不同 meme |
| `/meme工坊本群最近` | 所有人 | 查看当前群聊或私聊最近成功生成的 meme |
| `/meme工坊全局最近` | 管理员 | 查看全部会话最近成功生成的 meme |
| `/meme工坊收藏` | 所有人 | 引用 Bot 发送的 meme 后收藏 |
| `/meme工坊收藏夹` | 所有人 | 查看自己的收藏和可复用命令 |
| `/meme工坊取消收藏 <关键词>` | 所有人 | 从自己的收藏夹移除一项 |
| `/meme工坊提取 [图片\|文件]` | 所有人 | 提取当前消息或引用消息中的图片、可访问 QQ 表情；可单次指定发送方式 |
| `/meme工坊黑名单` | 所有人 | 查看禁用列表 |
| `/meme工坊禁用 <关键词>` | 管理员 | 禁用一个 meme |
| `/meme工坊启用 <关键词>` | 管理员 | 重新启用一个 meme |
| `/meme工坊资源检查` | 管理员 | 检查并下载 meme-generator 资源 |
| `/meme工坊更新检查` | 管理员 | 只读检查内置引擎与扩展是否有兼容更新 |
| `/meme工坊扩展状态` | 所有人 | 查看 `meme_emoji` 扩展状态 |
| `/meme工坊扩展安装 确认` | 管理员 | 下载或更新扩展，完成后重启 AstrBot |
| `/meme工坊Gouqi扩展状态` | 所有人 | 查看 Gouqi 审阅版本、素材校验和加载数量 |
| `/meme工坊Gouqi扩展安装 确认` | 管理员 | 下载并热加载 Gouqi 审阅素材，无需重启 |
| `/meme工坊自制列表` | 所有人 | 查看本地自制模板及其触发词 |
| `/meme工坊自制新建 <模板ID> <触发词...>` | 管理员 | 引用一张图片，快速生成一个底部字幕模板 |
| `/meme工坊自制删除 <模板ID>` | 管理员 | 删除一个自制模板及其素材 |
| `/meme工坊自制重载` | 管理员 | 重新扫描自制模板目录并热加载 |

扩展列表会自动排除当前 `meme_generator` 版本的内置模板，同时包含已经加载的
`meme_emoji`（以及其他原生外部包）和 Gouqi 模板。安装 `meme_emoji` 后仍需按安装提示
重启 AstrBot；Gouqi 安装成功后会立即出现在扩展列表中。

常用短别名包括 `/随机meme`、`/最近meme`、`/meme扩展列表`、`/meme收藏`、`/meme收藏夹`、
`/meme提取`、`/提取meme`、`/meme更新检查` 和 `/meme自制列表`。为降低与其他插件的冲突，优先使用完整的“meme工坊”命名空间。

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

单次提取可在指令后指定发送方式，覆盖 `grabber_send_mode` 默认配置：

```text
/meme提取 图片
/meme提取 文件
```

三个兼容指令 `/meme工坊提取`、`/meme提取`、`/提取meme` 均支持该参数；也兼容英文 `image` 和 `file`。没有参数时继续使用配置默认值。

- 普通静态图可以配置为图片或文件发送。
- GIF、APNG、WebP 等可能为动画的表情固定作为文件发送，避免丢失动画帧。
- 提取文件保存在插件数据目录的临时缓存中，按 `grabber_retention_minutes` 延迟清理，不会在消息刚发出时立即删除。
- 可通过白名单或黑名单限制群聊；私聊不受群列表限制。
- QQ 官方表情是否可提取取决于 OneBot 实现是否提供可下载的图片/文件标识。平台未提供时，插件不会伪造或绕过访问限制。

## 自制表情包（Meme Maker）

Meme Maker 让你不写代码也能做自己的 meme：一个模板 = 一块画布 + 若干图层，图层分成
**图片位**（运行时由用户提供的图片填充）和**文字位**（运行时由用户输入的文本填充）。
保存后模板会立刻热加载成一个正常的 meme，可以像内置 meme 一样触发、随机、收藏和禁用。

最快的做法是引用一张图片，然后发送：

```text
/meme工坊自制新建 my_meme 我的表情 myme
```

这会生成一个「底部字幕」模板：引用的图片作为底图，下方留出一条字幕区。之后就能用
`/meme 我的表情 今天放假` 触发。想精细调整位置、圆角、描边、旋转和层级，请到 WebUI 的
**工作台**里可视化编辑（见下一节）。

要点：

- 模板保存在插件隔离数据目录的 `maker/<模板ID>/` 下，`template.json` 记录图层，素材与它同目录，卸载插件不会影响其他 meme。
- 模板 ID 只允许小写字母、数字和下划线（`^[a-z][a-z0-9_]{1,31}$`），触发词最多 8 个；触发词与已有 meme 冲突时按加载顺序保留先注册的那个。
- 图片位按顺序对应用户提供的图片，数量必须刚好匹配；文字位可以留默认文本，用户不传时使用默认值。
- 底图（base）和覆盖层（overlay）是模板自带的固定素材，覆盖层始终画在最上层，图片位可以选择画在底图之下（`behind_base`）来做「透过窗口」类效果。
- 任一输入图片是动图时，输出为 GIF；全部为静态图时输出 PNG。
- 关闭配置项 `maker_enabled` 会从运行时移除全部自制 meme，但模板文件保留。

容量限制：

| 项目 | 上限 |
|---|---:|
| 模板总数 | 200 |
| 单模板图层数 | 16 |
| 图片位 / 文字位 | 4 / 8 |
| 画布边长 | 64 – 2048 px |
| 画布总像素 | 4,000,000 |
| 单个素材文件 | 8 MB |

## Dashboard WebUI

重载插件后，在 AstrBot Dashboard 的插件页面打开 **Meme 工坊**。页面自带一套独立的设计系统：顶部是品牌栏（主题、信息密度、刷新），下面是横向标签导航，内容居中限宽，底部状态栏显示插件版本与统计。没有侧边栏，所以在窄屏和全屏下都能看到完整功能。

- **主题**：极光 / 午夜 / 碳墨 / 紫梅 / 日光 / 米纸，共 6 套（4 暗 2 亮），在顶栏的主题菜单里带色卡预览切换，键盘 `↑`/`↓` + `Enter` 也能选。
- **信息密度**：宽松 / 紧凑一键切换，紧凑模式在同屏内塞进更多卡片。
- 主题与密度记在浏览器本地，下次打开保持不变；还没自己选过主题时，页面会跟随 AstrBot Dashboard 的明暗模式（暗色→极光，亮色→日光）。

四个标签页可用地址栏 `#overview` / `#library` / `#maker` / `#records` 直接进入：

- **总览**：表情库总量与启用比例、来源分布、`meme_emoji` 与 Gouqi 扩展状态、常用 meme 排行、活跃会话和最近活动时间线。卡片上的快捷入口可直接跳到对应标签并带上筛选条件。
- **表情库**：搜索名称与关键词，按标签、启用状态、来源筛选，并可按 key、图片数、文字数或来源排序；支持网格与列表两种密度。
- **工作台**：可视化编辑自制模板（`maker_enabled` 关闭时这里显示提示，标签徽标显示“关”）。
- **记录**：全局最近成功生成记录表，或切换到会话视角查看某个群聊/私聊参与者的触发情况。

表情库的具体能力：

- 单击卡片打开右侧详情抽屉，内含可复制的指令示例、按需生成的预览、参数说明与素材缩略图；素材点击后在灯箱中放大查看。
- 详情里列出运行时输入数量、默认文本、自然别名、参数 flag、枚举值和数值范围，便于确认某个 meme 到底能传什么参数。
- 单个 meme 可直接启停；进入多选模式后可框选当前页（**选中本页**）或跨页累积，一次最多批量处理 200 个 meme。
- 所有启停变更都会立刻写入插件配置的 `disabled_memes`，与聊天内的禁用命令共用同一份列表。
- 快捷键：`/` 聚焦搜索框，`Esc` 关闭抽屉、灯箱、确认框或退出多选。

工作台的具体能力：

- 左侧是模板列表（含图层数量和加载状态），中间是按真实画布比例缩放的编辑区，右侧是属性面板。
- 画布上可拖动、缩放图层，选中后用方向键微调，`Delete` 删除；可开关像素网格辅助对齐。
- 图片位可设置填充方式（裁切填满 / 完整包含 / 拉伸）、圆角、圆形裁切、旋转、不透明度、水平翻转、灰度和是否画在底图之下。
- 文字位可设置默认文本、颜色、描边、字号与最小字号、粗体、水平/垂直对齐、旋转、行距、最大行数和强制大写。
- **空白模板**从零开始，**字幕草稿**一键生成经典底部字幕布局；底图与覆盖层可直接上传图片。
- **渲染预览**用占位图跑一次真实渲染管线，所见即所得；保存后立即热加载，无需重启。
- 删除模板会同时删除其素材目录，操作前有确认框，且不可撤销。

页面所有接口均通过 AstrBot Plugin Page Bridge 访问；预览和素材以受大小限制的 data URL 返回，页面不会暴露服务器上的绝对路径。素材缩略图按需懒加载并限制并发，避免一次打开大量素材时拖慢 Dashboard。Dashboard 管理员可见的最近记录不含生成图片，只包含触发词、meme key、平台、会话、用户和时间。

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

## Gouqi 扩展

[`amalopyy123/meme-generator-gouqi`](https://github.com/amalopyy123/meme-generator-gouqi)
使用旧版 Python `add_meme` API，不能直接放入本插件使用。Meme 工坊为它提供独立兼容层：

1. 只安装插件已经人工审阅的固定上游提交，不跟随 `master` 自动执行新代码。
2. 仅从原仓库下载 31 个明确列出的图片/GIF 素材；不会解压或执行其中的 `.py`、`.pyc`。
3. 对每个素材同时核对路径、大小和 Git blob 哈希；任一文件不符就拒绝安装。
4. 使用本插件的 Pillow 渲染适配层生成图片，并限制输入像素、动画帧数和 GIF 输出大小。
5. 安装成功后立即热加载，无需重启；10 个模板会自动接入随机、收藏、最近记录、禁用和 Dashboard。

安装前先查看提示：

```text
/meme工坊Gouqi扩展安装
```

确认拥有作者和素材使用授权后执行：

```text
/meme工坊Gouqi扩展安装 确认
```

可用模板如下。表格中的图片数量也可通过 `/meme工坊详情 <关键词>` 或 Dashboard 查看。

| Key | 关键词 | 图片 | 输出 |
|---|---|---:|---|
| `ceshi` | 测试 | 1 | 静态图，需要 1 段文本 |
| `eav_grill` | 伊娃烧 | 1 | 动图 |
| `greeting_cat` | 挥手猫 | 1 | 动图 |
| `haine_shoot` | 海涅喷射 | 1 | 动图 |
| `i_squeeze` | 我捏 | 2 | 动图 |
| `line_art` | 线稿化、线稿、素描线稿 | 1 | 静态图或跟随输入动图 |
| `lucifina_chan_squeeze` | 小露西菲娜捏 | 1 | 动图 |
| `lucifina_squeeze` | 露西菲娜捏 | 1 | 动图 |
| `lucifinac_twist` | 小露西菲娜旋转、小露西旋转、小菲娜旋转 | 1 | 动图 |
| `luluka_twist` | 露露卡旋转 | 1 | 动图 |

截至审阅提交 `40eb41cf7c30`，Gouqi 上游没有声明开源许可证。公开可见不等于获得复制或使用授权，因此本插件不分发其源码和素材，安装命令也会在确认前再次提示。请先取得上游作者及相关素材权利人的许可；具体边界见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 更新检查

管理员可执行：

```text
/meme工坊更新检查
```

该命令会并行检查：

- 当前 `meme_generator` 版本，以及 PyPI 上符合插件兼容范围 `>=0.2.3,<0.3` 的最新稳定版本。
- 当前平台已安装的 `meme_emoji` 版本、最新 GitHub Release，以及本地动态库、许可证、资源和外部加载配置是否完整。
- Gouqi 本地素材是否完整、插件当前审阅提交和上游 `master` 最新提交是否一致。

检查是只读操作，不会运行 `pip`、下载扩展或修改配置。`meme_emoji` 有更新时，按结果提示执行 `/meme工坊扩展更新 确认`，完成后重启 AstrBot。Gouqi 上游出现新提交时只会报告“未审阅”，不会下载或执行；需要先由 Meme 工坊更新适配版本。内置素材没有独立的只读版本接口，因此需要检查或补齐素材时仍执行 `/meme工坊资源检查`。

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
| `avatar_cache_size` | `20` | 最近头像的内存缓存数量；设为 `0` 关闭，重载后清空 |

### 资源、扩展与 Dashboard

| 配置项 | 默认值 | 说明 |
|---|---:|---|
| `check_resources_on_start` | `false` | 启动后后台检查资源 |
| `resource_check_timeout` | `180` | 资源检查超时（秒） |
| `extension_download_timeout` | `1800` | 扩展下载超时（秒） |
| `gouqi_extension_enabled` | `true` | 是否注册已安装的 Gouqi 模板，重载后生效 |
| `gouqi_download_timeout` | `600` | Gouqi 固定审阅素材下载超时（秒） |
| `history_limit` | `500` | 持久化最近成功生成记录上限，范围 100-2000 |
| `maker_enabled` | `true` | 是否加载自制模板并在 WebUI 显示工作台；关闭只是取消注册，不删除模板文件 |
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
- QQ 与 QQ 官方 Bot 头像缓存只保存在插件进程内存中，不写入插件数据目录，插件重载或关闭时会清空。
- Dashboard 中的全局和会话记录面向拥有 AstrBot Dashboard 权限的管理员，请按部署环境的隐私要求配置权限。
- 更新检查会访问 PyPI、GitHub Release/Commit API；生成资源和扩展安装会访问相应上游 GitHub/CDN。Gouqi 安装只下载固定审阅提交的图片素材。网络图片和头像会访问其原始地址或腾讯头像 CDN，并受协议、超时和大小限制。

## 常见问题

### `/奶茶 左手` 没有响应

默认模式要求 `/meme 奶茶 左手`。如需直接关键词形式，将 `trigger_prefix` 设为空，并确认群聊符合 AstrBot 的唤醒规则。

### `奶茶 左手` 仍然生成右手版本

先执行 `/meme工坊详情 奶茶` 或在 WebUI 中查看该版本运行时暴露的参数。通常可使用 `/meme 奶茶 左手`、`/meme 奶茶 position=left` 或 `/meme 奶茶 --position left`。插件不会为某个 meme 写死特殊规则，而是按照当前引擎的参数元数据解析。

### 扩展安装完成但列表没有新增 meme

先重启 AstrBot，再执行 `/meme工坊扩展状态`。确认动态库校验、资源目录和外部加载均正常；若仍失败，请查看 AstrBot 日志中的 ABI 或系统库错误。

如果安装的是 Gouqi 扩展，不需要重启：执行 `/meme工坊Gouqi扩展状态`，确认“素材校验”为“通过”、“扩展开关”为“已启用”。如果安装时开关已关闭，启用 `gouqi_extension_enabled` 后重载插件。

### WebUI 中没有素材图片

素材只显示本机已下载的内置/扩展资源；Gouqi 素材保存在插件隔离数据目录中，也会通过同一受限接口显示。未下载资源、该 meme 没有素材目录，或图片超过 `dashboard_preview_max_mb` 时，页面不会显示可查看的素材。

### 自制模板保存了却触发不了

先执行 `/meme工坊自制列表` 确认模板已加载。常见原因有三个：配置项 `maker_enabled` 被关闭；
触发词和已有 meme 重复（日志里会有“重复触发词”提示，保留先注册的那个）；或者提供的图片数量
和模板的图片位数量不一致——图片位必须刚好填满。

### WebUI 打开时没有配色，切一次主题才正常

v1.9.1 已修复。AstrBot 会重写插件页的 `data-theme` 属性，旧版本的主题变量挂在这个属性上，被改写后全部失效。如果升级后仍然出现，请在 Dashboard 页面强制刷新一次（`Ctrl`/`Cmd` + `Shift` + `R`），浏览器可能还缓存着旧的样式和脚本。

### 插件列表里看不到图标

AstrBot 只读取插件根目录下的 `logo.png`，没有其他回退路径。手动复制或打包插件时请确保根目录的 `logo.png` 一起带上（`assets/` 里的图标文件不会被识别）。

### QQ 官方 Bot 没有自动带入头像

确认使用的是 AstrBot 的 `qq_official` 或 `qq_official_webhook` 适配器，并且平台配置中存在有效 `appid`。QQ 官方 Bot 的用户标识是应用范围内的 `openid`，不能按普通 QQ 号互换；腾讯头像 CDN 不可用时，插件会保留其他已提供的图片或返回该 meme 的正常参数不足提示，不会伪造用户 ID。

## 许可证

本项目派生自 AGPL-3.0-or-later 上游，代码继续使用
[GNU Affero General Public License v3.0 or later](LICENSE)。完整的第三方来源、许可证和边界说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 致谢

- [`Zhalslar/astrbot_plugin_memelite`](https://github.com/Zhalslar/astrbot_plugin_memelite)：AstrBot 对接、消息输入、参数收集和管理思路的上游参考；v1.5.0 继续参考其头像缓存与 QQ 官方 Bot 适配，并按本项目的下载安全边界重新实现。
- [`XTsat/astrbot_plugin_meme_grabber`](https://github.com/XTsat/astrbot_plugin_meme_grabber)：表情提取交互和 QQ OneBot 回退处理的上游参考；其公开 issue 在本次整合时为 0。
- [`anyliew/meme_emoji`](https://github.com/anyliew/meme_emoji) 与 [`anyliew/meme-emoji`](https://github.com/anyliew/meme-emoji)：扩展表情和 Rust 兼容实现来源。
- [`amalopyy123/meme-generator-gouqi`](https://github.com/amalopyy123/meme-generator-gouqi)：Gouqi 扩展的模板设计与素材来源；感谢作者提供这些自定义 meme。由于上游尚未声明许可证，本插件不打包其源码和素材。
- [`MemeCrafters/meme-generator-rs`](https://github.com/MemeCrafters/meme-generator-rs)：实际使用的 meme 生成引擎。
- [`dionaka/meme_maker`](https://github.com/dionaka/meme_maker)：Meme Maker 的灵感来源。该仓库本身是概念验证（固定区域贴图、依赖 OpenCV 与 dlib，且未声明许可证），因此本插件没有移植其代码，而是用现有的 Pillow 渲染层重新实现了一套图层化模板。
- [`kamicry/astrbot_plugin_apiver_meme_drawer_arcaea_pjsk`](https://github.com/kamicry/astrbot_plugin_apiver_meme_drawer_arcaea_pjsk)：分步向导式的贴图交互思路参考。其代码未被引入，原因是许可声明存在冲突（同时出现 AGPL 与 MIT 表述）、功能依赖用户自行部署的 Vercel 接口，并且随包分发了约 26 张 SEGA / lowiro 的版权曲绘。本插件坚持本地渲染、不分发第三方版权素材，因此只借鉴了交互形式。
