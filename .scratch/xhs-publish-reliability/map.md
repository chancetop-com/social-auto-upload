# 小红书发布链路可靠性对齐 — 路线图

## Destination

一份可交给后续会话实施的可实施规格（`spec.md`），围绕两个目标改进小红书发布链路（`upload-video` / `upload-note` / `check`，**本地与托管两种模式**）：

1. **降低账号封禁风险**（第一优先）——减少可被判为脚本/滥用的行为与不可逆操作；
2. **采用更可靠的机制**——选择器、发布结果检查、登录态检查等，凡上游更可靠即采用。

覆盖提交语义、判定信号、选择器基线、人类化交互、发布节奏、上传完成判定、元数据校验、会话与身份、模式一致性，并给出 shared 层（humanize 等）向其它平台复用的边界与迁移顺序。**产出规格，不写实现。**

## Notes

### 已确认约束（charter）

- **两个目标**（用户明确，2026-11-10）：① **降低账号封禁风险**（第一优先）；② **采用更可靠的机制**（选择器、发布检查、check login）。冲突时的顺序：**① > ② > 代码整洁**；任何“更可靠但会让行为更像脚本”的改动都要按 ① 重新评估。
- **仿照对象**：`xpzouying/xiaohongshu-mcp`（发布链路信号）+ `xpzouying/headless_browser`（浏览器）。**它是参考实现，不是我们的上游**（我们没有它的历史包袱，也无意对齐它的行为）；只借信号，不移植、不引入 Go。**「它这么做」不构成任何决定的理由**——理由只能是 ①封禁风险 > ②可靠性 > ③整洁。
- **禁止对齐下界**：上游比我们弱的地方（成功判据把验证页当成功、发布链路不判风控页、发布前无停顿）不得为了“对齐”而退步，须在 03/07/10 中记录理由。
- **双模式同步改**：本地 + 托管；选择器、行为、判定与运行模式无关。
- **选择器基线原则**：以“可信信号强度”为准——我们的可靠性不如它就采用它的；无法判定时双代并存 + 命中日志（决定见 05）。
- **用户明确要求**：humanize 这类通用防封手段应能被其它 15 个平台复用（决定见 15）。
- **产出是规格**，本图内不改代码。
- 覆盖范围包含此前审计出的“托管模式一致性”问题（见 13、14），不另开一张图。

### 领域词汇

使用 `GLOSSARY.md`：发布超时预算、发布结果未知、设置后回读（set-then-readback）、登录失效、本地模式 / 托管浏览器模式、Browser session。

### 代码事实

- 入口：`sau_commands/xiaohongshu.py` → `uploader/xiaohongshu_uploader/main.py`。
- 预算：`uploader/publish_timeout.py` 已有 `PublishTimeoutBudget`（目前仅 `uploader/tk_uploader/main_chrome.py` 使用；小红书自建了一套等价逻辑且缺 clamp）。
- 测试：`tests/test_xiaohongshu_uploader.py`（`FakeLocator` / `RecordingPage` / `FakeKeyboard`）。
- 会话接缝：`utils/browser_session.py`（托管分支忽略 `launch_kwargs` / `context_kwargs` / `init_script` / `context_setup`）。

### 技能

`/grilling`、`/domain-modeling` 用于决议；`/research` 用于外部事实。

### 置信度

结论必须标注：**代码明确 / 注释声称 / 仅推断 / 需真机验证**。

## Decisions so far

<!-- 一条已关闭工单一行：- [标题](链接) — 一句话结论 -->

- [01 — 上游发布链路可信信号清单](./issues/01-upstream-signal-audit.md) — 发布按钮靠自定义元素状态属性（`is-publish`/`submit-disabled`）零中文；成功判据仅是“URL 不含 `/publish/publish`”，**会把验证页当成功、不可照抄**；风控页分类函数存在但**发布链路从不调用**；打字是 `InsertText` 逐字+随机间隔（**无 key 事件**）；发布前**没有** `BeforeSubmit` 停顿。
- [02 — 真机 DOM 取证（发布页/图文页）](./issues/02-live-dom-snapshot.md) — `xhs-publish-btn` 现网存在（旧版选择器为 0）；`submit-disabled` 只表示“可提交”不表示“填完”，但**可作视频就绪信号**（标题框/“分辨率”警告都会提前误判）；正文是 tiptap 非 Quill；**一次话题插入产生 2 个同值 `a[data-topic]`**，“数量 +1”不可用；登录失效是 `/login` 前缀 + login-box，**未观察到 `/website-login`**；`.feature-guide__btn` 与图片 AI 弹窗是常驻覆盖层。
- [03 — 发布提交语义：预算底座 + 单次点击](./issues/03-publish-submit-semantics.md) — 提交段定为 `ARM（1s 轮询就绪，窗口 min(60s,预算)）→ FIRE（先置位再派发，只点一次）→ OBSERVE（判据与窗口**保持现状**：只认 `publish/success`、直到预算耗尽）`；重试只允许发生在「确定未派发」的 ARM 侧；点击后落登录/验证页一律 **9**、点击前归 10；预算底座已落地但**零 clamp**是现存缺口。

## Not yet specified

- **`check` 是否改轻量页**：上游用消费端 `/explore`（轻），我们用创作后台发布页（重但贴发布能力）；是否改成“轻量页 + creator 会话探针”组合。
- **素材校验**：图片数量/尺寸/格式、视频时长/大小——两边都没有，是否需要作为可靠性的一部分。
- **视频封面流程**是否也要“可信信号化”（现为增强步骤，失败即跳过）。
- **托管下的登录能力补齐**：把 Profile 里的二维码抓出来返回给调用方（现为完全禁止）。
- **多账号隔离与设备画像轮换**：托管模式由 Profile 承担（Out of scope）；本地模式若长期多号运行，是否需要每号独立 `user_data_dir` 之外的隔离手段。

## Out of scope

- 可见范围、商品绑定、URL 图片下载——属能力补齐，不是“降低封禁风险 / 提高可靠性”。
- **代理**（`XHS_PROXY` 一类）：托管模式由 Profile 承担出口；本地模式加代理属独立的部署议题。
- `sau_backend.py` / Vue 前端 / 调度 App 本身。
- 上游 Go 代码移植、`headless_browser` 复刻、浏览器构建分发（自建指纹浏览器）。
- 多账号并发隔离（托管由 Profile 承担）。
