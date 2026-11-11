# 05 — 选择器基线矩阵

Status: open
Type: grilling
Blocked by: 01, 02
Assignee: —

## Question

用 01（上游信号清单）与 02（真机 DOM）的实证，逐环节决定选择器基线：**采用上游 / 保留现状 / 双代并存**。产出“环节 × 现选择器 × 候选 × 中文依赖 × 决策 × 兜底顺序 × 命中日志”矩阵。

必须覆盖：发布按钮、标题、正文、图文上传 input、视频上传 input、话题候选、话题回读、定时开关、定时时间输入、原创开关、原创确认弹窗、内容类型菜单项、封面弹窗、登录二维码、登录态正向锚点。

约束：

- **主发布链路（上传 → 标题 → 正文 → 话题 → 发布）零中文依赖**为默认目标。
- 保留中文的项必须：限定容器 + 精确匹配 + 有结构兜底。
- 双代并存的项必须打命中日志（写明哪一代），便于真机验证后删旧分支。
- 每项给出“找不到/找到但不可用”两种失败文案。

产出：矩阵表 + 每项的兜底顺序 + 何时可以删除旧分支。

## Evidence from 02（真机取证）

- `xhs-publish-btn`（`is-publish`/`submit-disabled`）存在且可用；旧版 `.publish-page-publish-btn button.bg-red` 现网为 **0**。
- 正文为 `div.tiptap[role=textbox]`（ProseMirror），`div.ql-editor` 为 0。
- 标题 `div.d-input input` 与 `input[placeholder*="填写标题"]` 是同一节点。
- 话题候选：`#creator-editor-topic-container .item .name`（单次 50 个）。
- 定点：`.post-time-wrapper .d-switch`、`.d-datepicker-input-filter input.d-text`、`.d-switch-simulator` class 状态均与现有选择器一致。
- 详见 `research/02-live-dom-snapshot.md` §2/§3/§4/§5。
