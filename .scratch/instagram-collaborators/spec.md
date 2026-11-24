# Instagram 发布时协作者邀请（Collaborators）

Status: ready-for-agent

## Problem Statement

Instagram 的协作帖（Collab）允许作者把最多若干账号加为同一条 Feed 帖、轮播或 Reel 的协作者；对方接受邀请后，同一条作品出现在其主页，互动数据合并。当前 `sau instagram upload-video` / `upload-note` 不读取也不修改协作者，作者只能在网页上手动添加，调度方也无法从结果中知道这次发布选中了谁。

本仓此前把 collaborators 明确移出第一波，理由是真发验收需要第二账号，且「邀请发出」与「对方接受」是两件事。本次补上**发布前邀请**，但把不可控的接受状态留在 CLI 语义之外。

2026-11-24 的真实账号探测确认：

- 图文/轮播与 Reels 都有协作者入口，但 Reels 的已选账号只在 Collaborators 面板内可读，图文还会在预览图上渲染 chip。
- 网页上限为 5；第 6 个会被页面静默忽略。
- 请求 `nike` 时，子串匹配会误选 `_nikeza5`；必须按 username 精确匹配。

## Solution

两个 Instagram 发布命令新增可重复的 `--collaborator USERNAME`。上传器在点击 Share 前打开 Collaborators 控件，逐个添加账号，并在**每次添加后立即回读**该 username 是否已选中；首个失败即停止，不发布。结果在既有 `options` 对象中新增 `collaborators` 记录。

`status=set` 只表示「作者已在创建页选中该账号」，不表示邀请已送达、待接受或已接受。接受状态、发布后回读、增删协作者均不在本次范围。

## User Stories

1. 作为作者，我希望在发布 Reel 或图文/轮播时用 `--collaborator` 邀请 1–5 个账号，以便共同署名同一条作品。
2. 作为作者，我希望同一个参数在两个发布命令上行为一致，以便脚本按帖型复用。
3. 作为作者，我希望可以直接传 `alice` 或 `@alice`，以便从 App 复制用户名后不必手动清洗。
4. 作为作者，我希望大写输入被统一成小写，以便不与 Instagram 的用户名规则冲突。
5. 作为作者，我希望 `alice` 与 `Alice` 被视为同一个请求并在上传前报错，以便发现脚本里的重复项。
6. 作为调度方，我希望空值、重复值和超过 5 个的请求在启动浏览器前以退出码 `2` 结束，以便低成本修正。
7. 作为作者，我希望只按 username 精确匹配，绝不被显示名或包含关系误导，以免把作品署给错误的账号。
8. 作为作者，我希望请求 `nike` 时不会选中 `_nikeza5`，以免发错协作者。
9. 作为作者，我希望某个 username 加不进去时立即停止，以免在错误的协作者集合上继续发布。
10. 作为作者，我希望失败发生在点击 Share 之前，以便修正后重跑。
11. 作为调度方，我希望结果告诉我每个请求的 username 是否已在创建页选中，以便区分「没加上」与「已邀请但对方未接受」。
12. 作为调度方，我希望 `applied` 按请求顺序记录已确认的 username，以便与输入一一对应。
13. 作为调度方，我希望结果能区分「搜索无候选」「有候选但无同 username」「点击后未选中」「入口缺失」和「面板未收起」，以便安排补救动作。
14. 作为调度方，我希望 `set` 的文档含义明确为「已选中」，以免把邀请状态误读成接受。
15. 作为既有结果消费方，我希望新增字段是纯增量，旧字段与退出码保持不变。
16. 作为中文界面的账号使用者，我希望命令不依赖英文文案。
17. 作为英文界面的账号使用者，我希望命令不依赖中文文案。
18. 作为 `--no-publish` 使用者，我希望协作者在停到 Share 前已经完成设置与回读，以便干跑能覆盖这项能力。
19. 作为验收者，我不希望为了合并这次能力而准备第二个账号去接受邀请。
20. 作为托管模式使用者，我希望现有会话行为不变，协作者控件复用同一选项管线。
21. 作为作者，我希望其余发布选项（替代文字、地点、AI 标识、关闭评论）不受协作者影响。
22. 作为作者，我希望创建页被前台确认框遮挡时安全停止，而不是把读不到控件误报成入口缺失。
23. 作为调度方，我希望结果文件与 stdout、`--result PATH` 三处内容一致。
24. 作为调度方，我希望退出码继续遵循现有语义：静态错误 `2`、发布前失败 `1`、登录 `10`、限流 `11`、点击后未知 `9`。
25. 作为维护者，我希望上限 5 的来源、日期和漂移风险写在文档里，以便平台变化时快速定位。
26. 作为维护者，我希望不引入新的测试接缝，而是复用现有的纯逻辑、fake 控制件、受控 DOM 与 CLI 边界。
27. 作为作者，我希望不提供「移除协作者」的反向参数，因为新建创建页本来就没有已选协作者。
28. 作为维护者，我希望未来的 `user_tags` 实现不会把协作者 chip 误当成用户标签；本次不实现用户标签，但需在文档中留下这个边界。

## Implementation Decisions

### 范围与语义

- **只做发布时邀请**：在创建页选中协作者，随发布提交。
- **不做**：接受/拒绝邀请、邀请状态查询、发布后协作者回读、发布后增删协作者、`user_tags`（标记用户）、Stories。
- 协作者与「标记用户」「`@提及`」是不同概念，使用 [GLOSSARY.md](../../GLOSSARY.md) 中「协作者」「协作者邀请」的定义。
- 两帖型都支持；不因 Reels 的 UI 差异而缩小范围。

### CLI 契约

| Flag | 适用命令 | 形态 | 取值 | 未传时 |
|---|---|---|---|---|
| `--collaborator USERNAME` | `upload-video` / `upload-note` | `action="append"`，可重复 | 单个 Instagram username | `None`，不动页面默认 |

- 不提供 `--collaborators a,b` 逗号分隔形态。
- 不提供移除协作者的 flag。
- 重复 flag 的顺序就是请求顺序。
- 示例：

```bash
sau instagram upload-video --account creator --file demo.mp4 --title "标题" \
  --collaborator alice --collaborator bob
```

### 静态校验（浏览器启动前，退出 `2`）

对每个值依次执行：

1. 去掉首尾空白。
2. 去掉一个前导 `@`（`@` 不属于 Instagram 用户名）。
3. 转小写（Instagram 用户名只允许小写）。

然后校验：

| 校验 | 规则 | 行为 |
|---|---|---|
| 空值 | 归一化后为空 | `UsageError` → 退出 `2` |
| 重复 | 归一化后完全相同的值出现两次 | 报出重复 username，退出 `2`；不静默去重 |
| 数量 | 超过 5 | 报出实际数量与上限，退出 `2` |
| 字符集 | 不额外校验 | 中间出现 `@` 或非法字符时留到页面搜索，按无候选失败（退出 `1`） |

- 上限 5 来自 2026-11-24 网页实测（图文与 Reels 均 5）；Meta Content Publishing API 文档写 3，但本 CLI 自动化的是网页，按网页能力。
- 归一化与校验必须是纯函数，CLI 与上传器构造两处复用，禁止只在一处实现。

### 匹配规则

- 候选行文本形态为 `username display name`；只取首个 token 作为 username。
- 规范化后与请求 **精确相等** 才算命中；已在入口统一小写。
- 显示名、头像、认证标记不参与匹配。
- 禁止包含、前缀、模糊匹配。实测反例：请求 `nike` 会命中 `_nikeza5`。
- 若出现多个完全同名行（不应发生），取页面顺序第一个，不额外报歧义。

### UI 交互

入口选择器按优先级：

1. 创建页表单中稳定的 `name="creation-collaborator-input"` 输入框。
2. 英文 `Add collaborators` 的 placeholder / aria-label。
3. 中文「添加合作者」的 placeholder / aria-label。
4. 更宽的中英文回退。

- 控件限定在当前创建弹窗内，不得全页定位。
- 禁止 hash 类名。
- 所有可见交互走现有 `Humanizer` 行为层；`HUMANIZE=0` 时保留原生快速路径。

#### 图文 / 轮播

1. 聚焦/点击协作者入口，打开 **Collaborators 面板**（勾选列表 + Done）。
2. 清空输入框，逐字符输入 username。
3. 等待结果，按 username 首 token 精确匹配候选行。
4. 用人类化点击选中该行。
5. **逐个回读**：确认该 username 的预览图标签（带关闭按钮的 `span`）出现，再处理下一个。
6. 全部完成后点击 Done 收起面板；确认面板已收起。

#### Reels

1. 聚焦/点击协作者入口，打开同一个 **Collaborators 面板**。
2. 逐个输入 username，按精确匹配选中行。
3. **逐个回读**：确认该行的 checkbox 变为 `aria-checked="true"` / `checked`。
4. 全部完成后点击 Done 收起面板；实测 Done 不会清空已选。
5. 不把「重开面板做集合比对」作为常规回读；Done 后的用户名不可读是已知行为。

#### 两帖型的分支

- 控件注册表已经能区分视频/图文；同一控件按帖型选择图片来源（预览图标签 vs 面板 checkbox）。
- 两帖型的入口、面板、Done 相同；差异只在逐次回读的证据形态。
- 入口存在但页面明确禁用/提示账号不合格时，按 `unsupported` + `account_ineligible` / `control_disabled` 处理。

### 选项管线

- 发布选项数据类新增 `collaborators: tuple[str, ...] | None`。
- 选项结果键追加 `collaborators`；未请求时写 `not_requested`。
- 应用顺序：`alt_text → location → collaborators → ai_generated → comments`。
- 选项处理前仍执行创建页遮挡检查；遮挡时协作者记 `mismatch` + `editor_obscured`，不点 Share。
- 每个 username 前检查发布预算；所有等待按剩余预算收紧，计入既有 15 分钟总预算。
- 协作者列表内部首个失败即停；`applied` 为失败前已确认选中的 username 列表，按请求顺序。
- 不引入新的测试接缝：控件实现既有的 `resolve/read/set` 选项协议。

### 结果 schema

结果新增第五个 `options` 键：

```json
"collaborators": {
  "requested": ["alice", "bob"],
  "applied": ["alice"],
  "status": "mismatch",
  "reason": "no_same_username_candidate"
}
```

> 这段 schema 来自已确认的选项结果契约，不是工作示例；`requested` 为归一化后的请求，`applied` 为已确认选中的 username。

| 字段 | 含义 |
|---|---|
| `requested` | 归一化后的请求列表；未传为 `null` |
| `applied` | 已确认选中的 username，按请求顺序；没有确认项时为空数组，无法读取时为 `null` |
| `status` | `not_requested` / `set` / `unsupported` / `mismatch` |
| `reason` | 可选；见下表 |

不新增 `invite_state` 等字段。`status=set` 只表示创建页已选中，不代表邀请已送达或已被接受。

### 失败映射与退出码

| 情形 | status | reason | 退出 |
|---|---|---|---|
| 未传 | `not_requested` | — | 0 |
| 全部逐个确认选中 | `set` | — | 0 |
| 入口缺失 | `unsupported` | `entry_missing` | 1 |
| 入口禁用 / 页面明确账号不合格 | `unsupported` | `account_ineligible` / `control_disabled` | 1 |
| 搜索无任何候选 | `mismatch` | `no_candidates` | 1 |
| 有候选但无同 username | `mismatch` | **`no_same_username_candidate`**（新增） | 1 |
| 点击后未选中 / 回读不到 | `mismatch` | `selection_failed` / `final_mismatch` | 1 |
| Collaborators 面板未收起 | `mismatch` | `list_not_collapsed` | 1 |
| 创建页被遮挡 | `mismatch` | `editor_obscured` | 1 |

- 若页面实际上限低于 5，逐个回读会在第 N 个失败，按 `final_mismatch` 记录，并在 `detail` 说明页面拒绝。
- `list_not_collapsed` 的文档描述拓宽为「候选列表或协作者面板未收起」，不新增原因值。
- 任何 `unsupported` / `mismatch` 都不点击 Share，抛出聚合错误（退出 `1`）。
- 选项失败发生在点击前，绝不映射为退出 `9`。
- 退出码：静态错误 `2`；运行时失败 `1`；登录 `10`；限流 `11`；发布结果未知 `9` 保持不变。

### 语言与选择器

- 当前代码的本地模式不固定界面语言：本地会话只传代理；`locale=en-US` 仅在托管模式生效。2026-11-24 实测同一 Profile 先渲染 `zh-CN`，账号语言改为 English 后渲染 `en`。
- 因此协作者控件必须结构优先、中英文回退，不能只认一种界面语言。
- 已知文档漂移：旧 CHANGELOG 条目与 `instagram-browser-parity` 的 issue 17 声称本地模式固定 en-US，但 `178f442`（persistent local profiles）已改为保留 Profile 语言；当前 CLI 文档的描述才准确。本次不修历史文档，另记清理任务。
- 托管模式沿用现有契约：Profile 界面必须人工保持 English。

### 兼容性与限制

- `--collaborator` 不设 `required`，不给默认值；不传时行为、结果字段与退出码与现状一致。
- `options` 新增第五个键是纯增量；旧消费方忽略即可。
- 既有四项选项的顺序、status 与 reason 不变；既有 `--tags` 移除、caption 2200 等契约不变。
- 静态上限 5 是新的有意限制；超过 5 的请求以前没有定义，现在退出 `2`。
- 网页上限可能随账号、地区或灰度漂移；文档必须标注证据日期、账号与「网页 vs API」差异。

## Testing Decisions

好的测试只观察外部行为：命令退出码、结果 JSON、页面选中状态、Share 点击次数。不断言私有方法调用顺序、选择器实现细节或等待时长。

### 已确认的接缝

不新增接缝，复用现有 Instagram 发布选项测试的四层：

| 接缝 | 现有先例 | 覆盖 |
|---|---|---|
| **CLI 命令边界（最高，主接缝）** | 现有 Instagram 受控 CLI 与 `--no-publish` 测试 | flag 解析、静态错误退出 `2`、精确匹配、逐个回读、首个失败即停、结果 JSON、Share 零点击、`--no-publish` |
| 纯逻辑 | 现有 Instagram 选项纯逻辑测试 | 归一化、去重、上限、status/reason 映射 |
| fake 控制件 | 现有选项管线 fake 测试 | 选项顺序、失败聚合、预算、结果落盘 |
| 受控 DOM | 现有 location / DOM 测试 | 图文 chip、Reels 面板 + Done、中英文入口、`nike` 反例 |

真实账号的 `--no-publish` 是人工验收，不是单元测试接缝。

### 测试矩阵

1. **纯逻辑**
   - trim、前导 `@`、转小写、空值、重复、超过 5。
   - 未传 `not_requested`；成功 `set`；空候选、无同 username、点击失败、回读失败、面板未收起的状态映射。
   - `requested` 与 `applied` 的顺序。
2. **fake 控制件**
   - 逐个成功；首个失败即停；`applied` 保留已确认部分。
   - 入口缺失/禁用；面板 Done 失败；预算耗尽。
   - 任何失败都不触发 Share。
3. **受控 DOM**
   - 图文：面板、图片 chip、中英文 placeholder、`nike` vs `_nikeza5` 不误选。
   - Reels：面板、checkbox 勾选、Done 关闭与保留、5 人上限。
   - 遮挡：前台确认框挡住创建页时记 `editor_obscured`。
4. **CLI 边界**
   - 两个命令都注册 `--collaborator`；`verify` / `delete` 不注册。
   - 空值/重复/超过 5 → 退出 `2`，零浏览器。
   - 受控页面 → 退出 `1`，Share 零点击，结果文件与 stdout 一致。
   - `--no-publish` 成功 → `prepared`，协作者在停止点前已确认。
5. **真实账号 `--no-publish`（人工）**
   - 图文与 Reels 各一次，1–5 个协作者，停在 Share 前，结果为 `prepared`。
   - 不要求第二账号接受邀请；接受状态不阻塞合并。

### 回归

- `options` 固定包含五个键；未传 `--collaborator` 时零控件交互。
- 既有 location / alt_text / comments / ai_generated 测试全绿。
- 既有 `--no-publish`、结果输出、退出码测试不变。

## Out of Scope

- 接受/拒绝邀请、邀请状态、发布后协作者回读与增删。
- 第二账号的「邀请 → 接受」真发验收。
- `user_tags`（标记用户）与协作者的 DOM 区分；本 CLI 不设置 user tags。未来若支持 user tags，需要重新确认 chip 的判别方式。
- Stories（平台不支持协作者）。
- 托管模式（MLX / AdsPower / 比特浏览器）的真实账号验收；代码路径复用现有会话。
- 固定本地模式 locale 或修改历史文档中的英文界面承诺。
- 官方 Content Publishing API、OAuth、公网媒体。
- 新建 `issues/` 工单；任务拆分见 [map.md](./map.md)。

## Further Notes

- 完整实测记录与未覆盖项见 [findings.md](./findings.md)。
- 关键证据：
  - 中文图文入口：`evidence/01-note-entry-zh.png`
  - 中文图文 5 个 chip 与面板：`evidence/02-note-chips-zh.png`
  - 英文 Reels 5 人面板：`evidence/03-reels-panel-en.png`
  - Done 后重开仍保留勾选：`evidence/04-reels-reopened-five-en.png`
- 已知风险：
  - 网页上限可能随账号/地区/灰度漂移；静态 5 是当前证据下的选择。
  - 图文 chip 与 user tag 的视觉/DOM 形态接近；当前没有 user tag，暂不需要区分。
  - Reels 的已选用户名只在面板打开时可读；因此采用逐个回读，不做 Done 后的集合比对。
  - 图文面板的 Done 未单独点击；面板与 Reels 是同一组件，Done 行为由 Reels 探测确认。
- 术语已写入 [GLOSSARY.md](../../GLOSSARY.md)：`协作者（collaborator）`、`协作者邀请（collaborator invite）`。
- 已解决的评审点：Reels 面板收不起来复用 `list_not_collapsed`；证据已清理为 4 张关键截图。
