# 01 — 上游发布链路可信信号清单

Status: resolved
Type: research
Blocked by: —
Assignee: research-subagent

## Question

以 `xpzouying/xiaohongshu-mcp`（Go + go-rod）为参照，逐项核实其发布链路的**可信信号**实现，产出带文件/函数名的清单，供 03（提交语义）、04（限流策略）、05（选择器基线）、08（话题）、09（上传完成）、11（元数据）引用。需覆盖：

1. **发布按钮**：`xhs-publish-btn` 的 `is-publish` / `submit-disabled`；旧版 `.publish-page-publish-btn button.bg-red` 的 `disabled` / `aria-disabled` / `disabled` class；`clickPublishWidget` 的落点算法（ScrollIntoView + quad + 65% 横向）。
2. **成功信号**：`waitPublishSuccess` 的 URL 判据（不含 `/publish/publish`）与超时值。
3. **话题**：`verifyInsertedTopic` 回读 `a[data-topic]`（数量 +1、`data-topic` JSON 的 `name` 字段）、`selectTopicItem` 的重试口径。
4. **图文上传完成**：`.img-preview-area .pr` 计数等待与单张超时。
5. **视频就绪**：以“发布按钮可点”作为上传/处理完成的信号。
6. **风控页**：`/website-login/captcha` 与 `/website-login` 的 path 判定、为何用 `EscapedPath`、为何用 CDP `Page.getFrameTree`。
7. **humanize**：`Keystroke` / `AfterType` / `BeforeSubmit` / `PointerSettle` / `ClickHold` 的分布参数；`Type` 用 `InsertText` 逐 rune 的实现；鼠标曲线与抖动算法。
8. **标题长度**：`CalcTitleLength` 的 UTF-16 口径与 `(byteLen+1)/2` 的换算。
9. **内容长度**：`div.title-container div.max_suffix` / `div.edit-container div.length-error` 的读取时机。

要求：标注源码路径与函数名；区分 **代码明确实现 / 注释声称 / 仅推断**；只陈述事实，不评价质量。产出 `research/01-upstream-signal-audit.md`，并在 `## Answer` 中给出可被 05 直接引用的矩阵雏形（环节 × 选择器/属性 × 依赖中文 × 置信度）。

## Answer

结论落盘：`research/01-upstream-signal-audit.md`（11 节 + 矩阵雏形）。读取基线：
`xiaohongshu-mcp` @ `3b352aa0`、`headless_browser` @ `d28e37c7`。

### 对后续决议最有影响的六条

1. **发布按钮零中文**：新版 `xhs-publish-btn` + 属性 `is-publish!="false"`、`submit-disabled!="true"`；旧版 `.publish-page-publish-btn button.bg-red` + `disabled`/`aria-disabled`/class。**注意两条怪癖**：`disabled` 属性**存在即禁用**（`disabled="false"` 也算）；新版 `submit-disabled=="true"` 时**不回落旧版**。→ 05 若做双代并存，必须自行定义“找到但禁用”是否回落。
2. **成功判据不安全**：`waitPublishSuccess` 只判「URL 不含 `/publish/publish`」，15s/500ms。**跳登录页或验证页同样满足**，且不校验作品 ID、不读提示文案。→ **不可照抄**；03 必须叠加“离开发布页 ≠ 登录/验证页”的排除条件，07 负责提供判据。
3. **风控页分类存在但发布链路从未调用**：`CheckPageBlocked` 仅用于 search（`search.go:131/193`、`search_ready.go:172`）。→ 07 只能借用分类函数，**行为要自己设计**；也说明我们托管模式的 `_raise_if_login_required` 实际领先于上游。
4. **打字没有人化事件**：`Type` 逐 rune 调 CDP `Input.insertText`，**不产生 keydown/keyup/char**，只有随机间隔。→ 10 的结论要改写：上游买的是“时间分布”，不是“按键事件”；Playwright 的 `keyboard.type` 在事件真实性上反而更强，我们缺的是时间分布。
5. **发布前没有停顿**：`BeforeSubmit` 分布存在但**发布链路未使用**（只有 `notification_reply.go` 用）。点发布前只有 `Click` 内的 `PointerSettle`(200–1200ms) + `ClickHold`(45–250ms)。→ 10 的“发布前停顿”是新增项，不是对齐项。
6. **长度校验是“节点存在即失败”**：`div.title-container div.max_suffix` / `div.edit-container div.length-error` 出现即报错（不判可见、不比较数值），配合 UTF-16 口径（中文 1 字、ASCII 0.5 字、emoji 2 字，上限 20）。→ 11 可直接采用，成本极低。

### 其余可直接引用的事实

- 话题：`a[data-topic]` 数量必须**严格 +1**，`data-topic` JSON 的 `name` 与 tag `EqualFold`，回读窗口仅 **1s**；联想项 5s/200ms/最多点 3 次；无匹配降级为纯文本 `#tag`。
- 图文：逐张 `SetFiles` + `.img-preview-area .pr` 计数 `>= i+1`，单张 **60s**/500ms，张间 sleep 1s。
- 视频：唯一完成信号是“发布按钮可点击”（10min 窗口，外层 page deadline 5min，先到者生效——**先到者仅推断**）。
- 定时：ISO8601，`now+1h` ~ `now+14d`；标签 `len>=10` 截前 10。
- 浏览器：内置 CloakBrowser + `--fingerprint`/`--fingerprint-platform`/`--fingerprint-brand=Chrome`、`WithStealthJS(false)`、每页 `Network.setUserAgentOverride`（真实版本 + brands + `zh-CN,zh`）。**与本地模式无关，托管模式由 Profile 承担。**

### 尚未验证 / 留给真机

- `xhs-publish-btn` 是否出现在**我们的账号与页面变体**上（→ 02）。
- CAPTCHA/验证页在发布链路的真实触发路径与 path 形态（→ 02、07）。
- 60s/张、10min 视频窗口在真实网络下的余量（→ 09）。
