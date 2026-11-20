# 当前 Instagram Creator 的 Reel 和轮播在 Share 前能回读哪些元数据？

Type: task
Label: wayfinder:task
Status: resolved
Blocked by: 03

## Question

在操作者当前的 Creator 账号上，分别准备 Reel 和两图轮播，记录实际界面语言和运行模式。两个编辑器能回读哪个已选地点、哪些正文标签，以及什么 AI 开关状态？

按约定覆盖显式开启和关闭 AI。对每项记录请求值、页面终值及对应帖型，显式关闭另记入口可见性和操作前状态。缺失、不可用或回读不一致时保留实际观察。使用 `--no-publish`，记录每次运行的停止点，并链接可复核的字段证据。

验收口径见[Instagram 哪些组合可以沿用已有验收，哪些还需要验证？](03-instagram-acceptance.md#answer)。

地点取证时保留所点候选行显示的名称、地址（如有），以及列表收起后控件显示的名称。若名称和地址分行显示，记录当前上传器能否按地点名称命中。[一条地点请求怎样匹配候选并报告选中的地点？](09-location-match-and-result.md#answer)

## Answer

2026-11-20，在同一个本地 Chrome 有头 Profile、代码版本 `ebdeb43` 上，Reel 和两图轮播都用 `--no-publish` 走到「分享」按钮可用。设置页显示「创作者工具和控制选项」，两个编辑器的页面语言均为 `zh-cn`。以下结果限于这个简体中文 Creator 账号的发布前页面。

| 实测命令 | 帖子地点 | 配文话题 | AI 请求与回读 | 停止点与字段证据 |
| --- | --- | --- | --- | --- |
| `instagram upload-video`，4 秒纯色视频 | 请求 `Shanghai`，选中后读到 `Shanghai` | `#color #study`，顺序与正文一致 | `--ai-generated`，入口可见，从关切到开，回读 `true`，结果为 `set` | 「新 Reels」的「分享」前，`prepared`，退出 0。[Reel 字段记录](../research/instagram-creator-2026-11-20/reel.json) |
| `instagram upload-note`，两张不同的 JPEG | 请求 `Shanghai`，选中后读到 `Shanghai` | `#color #study`，顺序与正文一致 | `--no-ai-generated`，「添加 AI 标签」可见，操作前已关，无需点击。分享前仍读到 `false`，结果为 `default_off` | 「创建新帖子」的「分享」前，`prepared`，退出 0。[两图轮播字段记录](../research/instagram-creator-2026-11-20/carousel.json) |

两次成功运行均把话题直接写进正文。编辑器回读的全文是第一行 `Color study`，空一行，再接 `Two tones #color #study`。两次的地点列表中，第 1 行是近似名称 `Shanghai,china`，第 2 和第 4 行都叫 `Shanghai`。上传器点击第 2 行，该行随后从页面移除，分享前地点框显示 `Shanghai`。所点行只显示名称，没有显示地址。本次样本无法检验地址分行时的匹配行为。

轮播成功前另有两次运行，均在分享前退出。

- **素材阶段。** 首次传入两张约 2.5 KB 的纯色 PNG，页面显示「无法上传文件」并提示文件过小。CLI 在上传阶段超时，退出 1，没有进入元数据编辑器。[上传错误摘录](../research/instagram-creator-2026-11-20/carousel-upload-error.json)
- **选项阶段。** 换用两张 JPEG 后，CLI 点中 `Shanghai`，但读回空值，按 `location=mismatch` 退出 1。同时把显式关闭 AI 记为 `default_off/entry_missing`，该次没有读到开关值。失败时保存的页面同时包含「放弃帖子？」确认框和创建编辑器，截图中仍可见选中的 `Shanghai`，以及处于关闭状态的「添加 AI 标签」。CLI 在双弹窗状态下未完成回读。同样的图片和参数在上表的复测中通过。[选项失败时的 CLI 结果与页面摘录](../research/instagram-creator-2026-11-20/carousel-options-error.json) · [确认框与编辑器截图](../research/instagram-creator-2026-11-20/carousel-discard-dialog.png)
