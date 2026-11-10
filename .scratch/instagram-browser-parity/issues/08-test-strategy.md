# 08 — 第一波参数契约的测试与验收策略

Status: resolved
Type: grilling
Blocked by: 07

## Question

为 07 的参数契约设计测试与验收策略：

- 离线契约测试覆盖哪些点：flag 注册与默认值、set-then-readback、on/值 + 入口缺失失败、off + 入口缺失成功、location 精确匹配/候选报错、alt-text 数量与长度、collaborators 上限、AI/评论互斥。
- 用 fake 控件还是真实 DOM：哪些逻辑可以在内存 fake 上测（不登录），哪些必须真实账号。
- 真实账号手工验收：哪些项必须真发（location/alt_text/comments/AI/collaborators），用什么账号，验收证据怎么留。
- 现有 `tests/test_instagram_uploader.py` 如何扩展；是否新增测试文件。
- 退出码 0/1/2/9/10/11 的测试点。
- 不引入 manifest；漂移靠真实账号复跑。

## Answer

用户确认（2026-11-10，HITL 逐题）。一句话结论：**第一波缩为 4 项（location / alt_text / 关评论 / AI 标识）；测试分三层（纯逻辑 + fake 控制件 + 真实 DOM happy path）；所有静态输入错误统一 exit 2；真实账号真发验收本轮不做，只作为独立附录的待验收清单；漂移靠真实 DOM 用例当哨兵。**

### 0. 范围修订（会回写 07 与地图）

- **collaborators 完全不实现**，本轮不做 `--collaborators`，第一波 9 → 4 项。理由：验收需要第二账号且“邀请发出”与“对方接受”分离，收益不足以撑起本轮。
- **退出码破坏性变更**：caption >2200 由 `ValueError → 1` 改为 `UsageError → 2`。这是对 07「退出码保持向后兼容」的有意修订；依赖旧退出码的脚本需要适配。
- 4 项最终为：`--location`、`--alt-text`（仅 `upload-note`）、`--no-comments`、`--ai-generated/--no-ai-generated`。

### 1. 三层与文件落点

| 层 | 位置 | 负责 | 依赖 |
|---|---|---|---|
| 纯逻辑 | 新增 `uploader/meta_uploader/insgraph_uploader/options.py` + 新增 `tests/test_instagram_options.py` | 校验、三态映射、`options` 结果记录、status/reason 判定 | 零浏览器、零登录 |
| fake 控制件 | 同文件 `tests/test_instagram_options.py` | set→回读、入口缺失、off 已满足、disabled-but-satisfied、mismatch | 注入式 control resolver；不启动 Chrome |
| 真实 DOM | 扩展 `tests/test_instagram_uploader.py` | 4 个入口的 happy path 与页面结构交互 | 真实 Chrome `page.set_content` |

- 控制件采用与 TikTok 相同的 duck-typed 协议（resolve / read / set），Uploader 内新增 `_apply_options(page, ...)`；fake 只实现被调用的原语。
- 真实 DOM 只验 happy path（定位 + 点击 + 回读），**不重复堆**缺失/不一致/降级分支——这些留在 fake 层。

### 2. 离线覆盖清单

#### A. 纯逻辑（无浏览器）

| # | 测点 |
|---|---|
| A1 | parser 注册：`upload-video` / `upload-note` 都有 `--location`、`--no-comments`、`--ai-generated/--no-ai-generated`；`--alt-text` 只在 `upload-note`；`--thumbnail` 仍只在 `upload-video` |
| A2 | `--ai-generated` 与 `--no-ai-generated` 同传 → argparse `SystemExit(2)` |
| A3 | 全不传 → 4 项均 `not_requested`，不产生回读要求 |
| A4 | 三态保真：`True` / `False` / `None` 不互相压缩 |
| A5 | 静态校验一律 `UsageError → 2`：caption >2200、图片+视频互斥、thumbnail 用于图片、alt-text 数量非 0 且 ≠ 图数、单项 >1000、location 空串 |
| A6 | `options` 结构：每项 `requested/applied/status/reason`；5 个 status 全覆盖 |

#### B. fake 控制件（不登录）

| # | 测点 |
|---|---|
| B1 | set → 回读一致 → `set` / exit 0 |
| B2 | set → 回读不一致 → `mismatch` / exit 1 |
| B3 | 显式 on/值 + 入口缺失 → `unsupported` + `reason=entry_missing` / exit 1 |
| B4 | 显式 off + 入口缺失 → `default_off` / exit 0 |
| B5 | 显式 off + 入口存在但已 off → `default_off`，不点击 / exit 0 |
| B6 | 控件 disabled 但已满足 → 成功且不点击 |
| B7 | 未传 → 零控件交互 |
| B8 | location：大小写不敏感精确匹配；无匹配 → 错误信息含候选列表 / exit 1；多个同名候选取第一个，不额外记录歧义 |
| B9 | alt_text：单图 1 条 / 轮播 N 条，顺序与数量严格对应 |
| B10 | Advanced settings 未展开时开关不可见 → 先展开、可重复调用幂等 |

#### C. 真实 DOM（`test_instagram_uploader.py`）

| # | 测点 |
|---|---|
| C1 | location：`Add location` 输入 + 选中候选 + 回读 |
| C2 | alt_text：编辑页 `Accessibility → Alt text` 输入 + 回读 |
| C3 | 关评论：`Advanced settings → Turn off commenting` |
| C4 | AI 标识：`Add AI label` 开关 |

#### D. 退出码

| 码 | 含义 | 测点 |
|---|---|---|
| 0 | 成功（含 off 已满足） | B1/B4/B5/B6 |
| 1 | 运行时失败（mismatch、入口缺失、location 无匹配） | B2/B3/B8 |
| 2 | 静态输入错误 | A2/A5，浏览器未启动 |
| 9 | 发布结果未知 | 现有用例保留 |
| 10 | 需要登录 | 只加 1 条 Instagram guarded 路径“未登录 → `LoginRequiredError`”；映射本身由 `tests/test_adspower_cli.py:547/558` 覆盖 |
| 11 | 限流 | 同上，不重复测映射 |

### 3. status 与失败归因

保持 07 的 5 个 status，并为每项增加 `reason`：

- `entry_missing`：选择器没命中，倾向漂移/回归。
- `account_ineligible`：入口存在但账号类型不支持。

离线 fake 同时模拟两种；真实归因只能在待验收真发时确认。四类结果的映射：

- 未传 → `not_requested`，无 reason。
- 成功 → `set`。
- off 且入口缺失/已 off → `default_off`。
- 请求 on/值但缺失或不可用 → `unsupported` + reason，exit 1。
- 写入后回读不一致 → `mismatch`，exit 1。

AI 与关评论是两个**独立**开关，无互斥（与 TikTok 的 `--no-comments` / `--aigc` 一致）。

### 4. 真实账号验收（本轮不做，只出清单）

- 作为 09 实施规格的**独立附录**，不阻塞实现与合并。
- 规格里 4 项标注 `offline-verified / post-publish unverified`，并写明“未完成验收前不得对外宣称已支持”。
- 附录**不写账号名**；只写：前置条件（可发帖的 Personal 账号 + English UI）、每项真发步骤、通过判据、证据留法、验完用 `sau instagram delete` 删帖。
- 判据：location 发布后地点可见；alt_text 发布后编辑页可回读；关评论发布后评论区关闭；AI 标识发布后可见。
- 证据：结论与帖子 URL 写入 `research/08-acceptance-evidence.md`（进 Git）；截图/录屏放仓库外，文内只引用路径与时间（沿用 06 约定）。
- collaborators 不在此清单内。

### 5. 漂移策略

- 4 条真实 DOM happy-path 即哨兵：选择器一变，CI 立刻红，不依赖登录态。
- 不引入 manifest，不排期真实账号复跑。
- 手工复跑触发条件：真实 DOM 用例变红、Instagram composer 前端改版、用户报告某项不生效。
- 文档与 CHANGELOG 沿用仓库惯例，把真发验收标为“待验收”（参见 `docs/CLI.md:730`、`CHANGELOG.md:71`）。

### 6. 本轮明确不测

- Stories、定时发布、配乐、选帧封面、user_tags、collaborators。
- caption add-ons、product tagging、品牌内容、partnership ads。
- 发布后洞察、通知、webhook、评论管理。
- 网络层与真实 Instagram 后端的契约（无公网依赖）。

### 7. 要传给 09 的硬约束

1. 新文件：`tests/test_instagram_options.py` + `insgraph_uploader/options.py`；`test_instagram_uploader.py` 只加真实 DOM 与 10/11 守卫。
2. 静态校验放在浏览器启动前，统一 `UsageError`；caption 也改 2。
3. `options` 结果字段与 5 status + reason 枚举照 07 + 本文档。
4. 真发验收清单作为附录，不写账号，不阻塞合并。
5. 不新增 manifest 或漂移检测工具。
