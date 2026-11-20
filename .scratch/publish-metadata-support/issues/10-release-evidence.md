# 调用方如何知道某个帖型支持什么，以及本次请求实际生效了什么？

Type: grilling
Label: wayfinder:grilling
Status: resolved
Blocked by: 03, 04, 05, 09, 11, 12, 13

## Question

按小红书、Rednote、Instagram 和 TikTok 的视频与图文入口列出八行验收项。确定文档和已有结果输出需要表达哪些信息，包括调用方请求、回读到的值、降级、账号不可用、尚无实测和已知不支持。说明旧开关和结果文件的兼容要求，为每个缺口写出最小可复验场景以及优先交付顺序。

Instagram 轮播显式关闭 AI 时，一次在编辑器中读到关闭，一次遇到确认框遮挡且 CLI 报 `entry_missing`。确定调用方如何区分这两类证据。[当前 Instagram Creator 的 Reel 和轮播在 Share 前能回读哪些元数据？](11-instagram-creator-field-readback.md#answer)

迁移示例应覆盖旧 `--tags` 的参数报错，以及调用方如何把希望公开的话题写进配文。以一句含两个话题的配文说明逐词结果：一个有同名候选并点选，另一个无同名候选而保留文字。验收记录应标明点选后的关联是否已实际回读，目前「新建话题」和 `Add` 的样本只覆盖跳过操作。[各平台的标签写到哪里，什么结果算设置成功？](05-tags-native-and-fallback.md#answer) · [小红书、Rednote 和 TikTok 怎样在发布前区分已关联的话题和普通文字？](12-inline-topic-readback.md#answer) · [遇到同名的「新建话题」或 Add 候选时，发布命令应该点选还是保留文字？](13-topic-create-candidate.md#answer)

## Comments

- 2026-11-20，操作者确认 CLI 文档采用八行表，每条发布命令一行。AI 声明、帖子地点、配文话题分别注明网页实测结果、CLI 已接入行为和实测账号样本。缺样本标「未实测」，页面明确提示资格限制才标「账号不可用」。
- 操作者确认话题功能的交付条件。小红书和 Rednote 的视频、图文编辑器均需点选同名的「新建话题」，TikTok 的视频、图片帖编辑器均需点选同名的 `Add`。六处都要在发布前回读到该词的关联，并核对整句配文。现有样本只覆盖这些特殊候选被跳过的情形。[发布前逐词回读记录](12-inline-topic-readback.md#answer)
- 操作者确认沿用各命令已有的结果输出。Instagram 两条命令保留现有 JSON、默认结果文件和 `--result PATH`。小红书、Rednote 和 TikTok 的六条命令通过现有终端输出和退出码报告，本轮无需为它们新增 `--result`。[Instagram 结果字段](../../../docs/CLI.md#instagram-发布选项)

## Answer

八条命令的支持范围写入 CLI 文档，每条命令的实际结果从它已有的输出读取。Instagram 中「放弃帖子？」仍挡住编辑器时，按发布前失败处理，即使只请求了关闭 AI 也须停止。执行结果要让调用方区分「读到关闭」「确认入口缺失」「当前无法读取编辑器」。

### 八条命令的验收基线

以下各行以 `sau` 开头运行。CLI 栏以 `ebdeb43` 为准，此版本仍接受 `--tags`。账号栏标注地点与配文取证时的样本。历史 AI 验收的账号和观察阶段随对应证据列出。

| 命令 | 地点与配文样本 | AI 声明证据 | 帖子地点回读 | 配文话题回读 | 当前 CLI |
| --- | --- | --- | --- | --- | --- |
| `xiaohongshu upload-video` | 中文，`180`，账号类型未核验 | 本帖型显式选 AI 后的终值待验 | 候选行有上海地址，收起显示「人民公园」 | 正文锚点读到 `#coffee`，逗号位置已核对 | `--content-type ai` 失败可告警继续。无帖子地点参数。旧话题入口为 `--tags` |
| `xiaohongshu upload-note` | 中文，`180`，账号类型未核验 | 下拉可见「笔记含AI合成内容」，选中终值待验 | 候选行有北京地址，收起显示「房山人民公园」 | 正文锚点读到 `#coffee`，逗号位置已核对 | `--content-type ai` 失败可告警继续。无帖子地点参数。旧话题入口为 `--tags` |
| `rednote upload-video` | 中文，`rednote`，账号类型未核验 | 已有 AI 声明回读匹配并到达发布前的记录 | 候选行有上海地址，收起显示「人民公园」 | 正文锚点读到 `#coffee` | `--content-type ai` 要求回读。无帖子地点参数。旧话题入口为 `--tags` |
| `rednote upload-note` | 中文，`rednote`，账号类型未核验 | 已有带 AI 声明的双图验收，到达发布前 | 候选行有成都地址，收起显示「人民公园」 | 正文锚点读到 `#coffee` | `--content-type ai` 要求回读。无帖子地点参数。旧话题入口为 `--tags` |
| `instagram upload-video` | 简体中文，Creator，Reel | 关切到开，分享前读到 `true` | 首个同名 `Shanghai`，候选只显示名称，选中后名称一致 | 分享前正文含 `#color #study` | 已接入 AI 开关、地点和配文，可读 JSON。地点仍按候选整行匹配 |
| `instagram upload-note` | 简体中文，Creator，两图轮播 | 开关原本已关，分享前读到 `false`。另一次受确认框遮挡，读值为空 | 首个同名 `Shanghai`，选中后名称一致。遮挡样本另记地点回读失败 | 分享前正文含 `#color #study` | 已接入 AI 开关、地点和配文，可读 JSON。地点仍按候选整行匹配 |
| `tiktok upload-video` | 英文 Studio，`lukechen`，账号类型未核验 | 既有视频发布后读到创作者 AI 标识 | 候选行有英国地址，收起显示 `London Eye` | 视频配文读到 `#coffee` 关联标记 | 已接入 `--aigc`、`--no-aigc`。无地点参数。旧话题入口为 `--tags`，视频配文取 `--title` |
| `tiktok upload-note` | 英文 Studio，`lukechen`，Photos，账号类型未核验 | 既有公开账号图片帖发布后读到创作者 AI 标识 | 候选行有英国地址，收起显示 `London Eye` | 图片帖正文读到 `#coffee` 关联标记 | 已接入 `--aigc`、`--no-aigc`。无地点参数。旧话题入口为 `--tags`，图片帖正文取 `--note` |

网页证据按帖型分别留存在[小红书与 Rednote 地点记录](01-xhs-rednote-post-location.md#answer)、[TikTok 地点记录](02-tiktok-location-by-post-type.md#answer)、[六个编辑器的配文话题记录](12-inline-topic-readback.md#answer)和[Instagram Creator 字段记录](11-instagram-creator-field-readback.md#answer)。历史对照见[小红书声明菜单](../../xhs-publish-reliability/research/22-english-ui-evidence.md)、[Rednote 声明验收](../../rednote-support/acceptance.md)、[TikTok 发布后验收](../../tiktok-browser-parity/acceptance-local.md)和[Instagram Personal 与 Creator 样本](03-instagram-acceptance.md#answer)。

### 调用方如何读结果

- 每个请求字段报告请求值、页面实际读到的终值、是否允许继续，以及降级或失败原因。省略参数记为未请求。逐词结果保留配文中的顺序和重复次数。地点分别记录所点候选行的名称和可见地址，以及收起后控件显示的名称。
- Instagram 沿用 `--result PATH`、默认结果文件、成功时的 JSON 输出、现有 `options` 字段和顶层发布状态。新增证据可以追加。小红书、Rednote、TikTok 在现有终端诊断中给出逐项结果，保留原成功摘要及退出码约定。
- 文档标明实测账号、语言、帖型、观察阶段和证据来源。某帖型缺样本标「未实测」。网页有控件而命令尚未接入时明确写「CLI 未接入」。只有页面明确说明资格限制才标「账号不可用」。只在有依据的具体范围标「已知不支持」，例如小红书和 Rednote 的单选内容类型没有独立的 AI 关闭参数。

**Instagram 显式关闭 AI 的三种验收结果**

| 分享前的状态 | AI 结果 | 本次是否可继续 |
| --- | --- | --- |
| 编辑器可操作，开关可见且已关 | `requested=false, applied=false, status=default_off`。若由开切到关并回读成功，沿用 `status=set` | 其他字段通过后可继续 |
| 在可操作的编辑器中确认没有 AI 入口 | `requested=false, applied=null, status=default_off, reason=entry_missing` | 其他字段通过后可继续 |
| 「放弃帖子？」处于前台，编辑器被遮挡，最终无法核对 AI 请求 | 回读失败，`applied=null`，结果说明确认框遮挡编辑器。沿用选项回读失败的 `mismatch` | 停在 Share 前，退出 `1`，顶层为 `not_submitted` |

历史失败记录中的 AI 一项仍是 `default_off/entry_missing`。该次因地点 `mismatch` 提前退出。`Share` 所在的创建弹窗在失败现场位于 `aria-hidden="true"` 的祖先下，前台确认框只有「放弃」与「取消」。最小回归场景只传 `--no-ai-generated`，对上表三种页面分别核对回读值、退出结果和 Share 点击次数。遮挡时点击次数必须为零，排除地点失败替 AI 挡住提交的情形。[历史失败结果](../research/instagram-creator-2026-11-20/carousel-options-error.json) · [现场截图](../research/instagram-creator-2026-11-20/carousel-discard-dialog.png) · [可见开关的复测结果](../research/instagram-creator-2026-11-20/carousel.json)

### 最小复验场景与交付顺序

1. **先验发布前必须停止的情形。** 小红书两种帖型分别请求 `--content-type ai`，记录收起后显示的声明，并覆盖读回其他值或缺值时停止。Rednote 沿用已有两种帖型的验收。TikTok 两种帖型各测一次显式关闭且入口确实缺失，再测一次控件存在但终值仍开启。Instagram 用上表的三种页面验收。四个平台保留已有 AI 参数名，互斥值在上传前报用法错误。
2. **再验帖子地点。** 八条命令分别用中性素材在发布前核对一次成功匹配和一次无同名候选。成功样本记录第一个同名行、可见地址及收起后的名称；失败样本含近似建议或空列表都应停止。另覆盖入口缺失、明确的资格提示和选中后读值不符。Instagram 可复用现有同名行样本，候选按两行显示名称与地址的情况用受控页面核对，真实账号栏按已有证据填写。小红书和 Rednote 的 `--shoot-location` 继续用于自主拍摄声明。
3. **配文话题按六个编辑器的结果交付。** 小红书、Rednote 的视频和图文各点选一次「新建话题」，TikTok 视频和图片帖各点选一次 `Add`。每处都要从编辑器读到同名关联，再核对含标点的完整配文，六处全部通过才能交付话题功能。Instagram 两条命令以编辑器全文为准。

迁移时，十三条既有媒体发布命令移除 `--tags`，传旧参数在解析阶段退出 `2`。例如，小红书图文原参数片段 `--note '今天喝了咖啡，配上栗子蛋糕。' --tags 咖啡,栗子蛋糕` 改为 `--note '今天喝了 #咖啡，配上 #栗子蛋糕。'`。若「咖啡」有同名候选，点选并读到同名锚点，则报告「已关联」；若「栗子蛋糕」只有近似候选，则报告「保留文字，无同名候选」。整句逐字一致才放行。这个示例是验收预期，既有六个样本的第二个词实际都返回过同名的特殊候选。[各平台的标签写到哪里，什么结果算设置成功？](05-tags-native-and-fallback.md#answer)
