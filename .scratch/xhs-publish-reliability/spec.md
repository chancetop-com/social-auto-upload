# 小红书发布链路可靠性 — 实施规格

- 状态：**规格定稿，未实施**。本 effort 只产出本文件，不改生产代码、不改选择器、不执行测试。
- 范围：`sau xiaohongshu upload-video` / `upload-note` / `check` / `login`，**本地模式与托管模式同步改**。
- 来源：决议 ticket [03](./issues/03-publish-submit-semantics.md)–[27](./issues/27-schedule-readback.md)；取证见 [research/](./research/)。
- 术语以仓库根目录 `GLOSSARY.md` 为准；本规格新增术语必须在实施第一步回写（见 §9.1）。

## 权威关系

| 层次 | 文件 | 地位 |
| --- | --- | --- |
| 本规格 | `.scratch/xhs-publish-reliability/spec.md` | **单一权威**：行为、判定、退出码、选择器、顺序 |
| 决议档案 | `issues/NN-*.md` | 理由与取证过程；与本文冲突时以本文为准（本文是它们的汇总与最新修订） |
| CLI 文档 | `docs/CLI.md` | **派生投影**：只投影参数、退出码与用户可见文案；本文 §4 的退出码表是母本 |
| 术语 | `GLOSSARY.md` | 术语定义；本文 §9.1 列出必须新增/修订的条目 |

## 置信度标记

`[代码明确]` 当前工作树 grep/读码可证 · `[实机]` 2026-11-11 真机取证（02/22/23/24/26）· `[上游代码]` `xpzouying/xiaohongshu-mcp` 源码 · `[设计]` 本规格新增决策 · `[仅推断]` 无直接证据，实施前须复核 · `[需真机]` 只能真机验证。

> 排序原则（charter）：**① 降低封禁风险 > ② 可靠性 > ③ 整洁**。`[上游代码]` 只作事实来源，不构成任何决定的理由；上游比我们弱的地方不"对齐"（记录见 §7）。

---

## 0. 摘要

三句话：**把"点一次发布"变成机器可证明的语义（ARM→FIRE→OBSERVE + 退出码契约），把每一个判据换成有实机证据的结构信号（选择器矩阵 + 四档可用性判定），把不可逆动作前的一切不确定性变成点击前 `exit 1`。**

| # | 改动 | 一句话 |
| --- | --- | --- |
| 1 | 预算底座 | 小红书接入 `PublishTimeoutBudget` 的 `clamp_*`，删除裸 `timeout=30000`；预算耗尽在点击前 = 1、点击后 = 9 |
| 2 | 提交语义 | `ARM`（1s 轮询 `xhs-publish-btn`，窗 `min(60s,预算)`）→ `FIRE`（先置位再派发，只点一次）→ `OBSERVE`（500ms 轮询，窗 `min(15s,预算)`，只认 URL） |
| 3 | 判定原语 | 新增 `utils/dom.py`：四档角色（attached/visible/interactive/editable）+ hit-test + 覆盖层清障；`count()` 只用于集合基数 |
| 4 | 选择器矩阵 | 16 个环节逐项定基线；发布按钮只留 `xhs-publish-btn`；文本兜底**中文单语**且只在结构失败后 |
| 5 | 人类化交互 | 上游 11 个动作全量进 `utils/humanize.py`，按语义锚点接线；逐字符分派（ASCII 真键 / 中文 `insert_text`）；>1000 字一次性 `insert_text` |
| 6 | 上传完成 | 图文逐张 + 每瓦片完成态（`.mask.uploading` 消失）；视频复用 ARM 谓词（窗 `min(600s,预算)`）；失败即时中止 |
| 7 | 话题 | 候选 name 归一化全等、顺序全扫；编辑区内新增**恰好 1 个**；缺失降级、插错/多插中止 |
| 8 | 元数据与回读 | 标题 UTF-16 加权 ≤20 预检；正文 `.length-error` 单次检查；定时开关/值三处回读（C1/C2/C3）不一致即 1 |
| 9 | 会话与身份 | 删两次独立预检；会话真伪只由发布页那一次观测判定；`check` 用发布页 + 上传锚点 `attached`；写回只写成功、原子替换 |
| 10 | 模式一致性 | 删 8 处 `if multilogin:` 门；`mode` 取代布尔；`provider_label()` 公开；四句文案 + `publish_attempted` 后缀 |
| 11 | 调用方契约 | CLI 不做节流；`0/1/9/10/11` 的机器语义固定，`10` 点击后额外打 stderr `publish_attempted=true` |
| 12 | 参数与可观测性 | 默认有头、`debug` 默认关并删 `DEBUG_MODE`；托管忽略参数每 run 一条 WARNING；两种模式各一条启动日志 |
| 13 | 测试与验收 | `tests/fakes_xhs_dom.py` + `tests/fakes_clock.py`；退出码表做成可执行镜像；真机只做正路 + 三类注入 |

---

## 1. 目标与非目标

### 1.1 目标

1. **发布提交不可逆动作前可证明**：任何 `exit 1` 都意味着"确定未发布"，任何"可能已发布"都只能是 `9` 或 `10+publish_attempted`。
2. **判据只认有证据的信号**：选择器、就绪、上传完成、登录失效、越限、定时生效，每一项都有实机或代码证据；无证据项不入基线。
3. **两种模式同码、同文案、同检查点**：判定与运行模式无关，模式只决定补救文案。
4. **行为层可复用**：humanize / 判定原语 / 开关读取 / 风控分类形状进 `utils/`，为其余 15 个平台迁移出边界与顺序。
5. 规格细到"实施会话不需要再做产品决策"：每个单元的判定标准、失败语义、测试点、顺序与依赖明确。

### 1.2 非目标（本规格不交付）

- 不写实现代码、不跑测试、不建分支。
- 不实现节流/冷却/熔断（归调用方 App，见 §3 U14）。
- 不移植上游 Go 代码、不复刻 `headless_browser`。
- 不改本地模式浏览器配置（persistent profile / 真 Chrome / UA / stealth，见 §8.1 第 3 条）。
- 不实现发布结果自动对账（见 §8.1 第 2 条）。
- 不实现身份回读（见 §8.1 第 7 条）；不实现媒体素材校验、视频封面可信信号化、失败截图去重（见 §8.2）。

---

## 2. 代码基线与现状总览

> 行号为当前工作树位置；实施时以 `rg -n` 复核后再改。所有"缺陷"都是本规格要消除的现状，不是待讨论项。

### 2.1 文件地图

| 文件 | 角色 | 本规格涉及的改动 |
| --- | --- | --- |
| `sau_commands/xiaohongshu.py` | CLI 命令层（upload-video / upload-note / check / login） | 删除 `cookie_auth` 预检与异常映射（§3 U9）；`check` 退出码 |
| `sau_commands/arguments.py` | 全局运行参数 | `set_defaults(headless=True)` → `False`（U13） |
| `uploader/xiaohongshu_uploader/main.py` | 发布链路主实现（~1500 行） | 绝大部分改动集中于此 |
| `uploader/xiaohongshu_uploader/main.py` 的 `_xhs_user_agent` / `stealth` 注入 | 本地指纹现状 | **本轮不动**（§8.1 第 3 条） |
| `uploader/publish_timeout.py` | `PublishTimeoutBudget` | 不改契约，只被调用（U1） |
| `uploader/publish_gate.py` | `--not-before` 闸门 | 不改 |
| `utils/browser_session.py` | 本地/托管会话接缝 | `provider_label()` 公开；忽略参数 WARNING；启动日志（U13） |
| `utils/humanize.py`（新） | 行为层 | U5 |
| `utils/dom.py`（新） | 判定原语 | U3 |
| `utils/controls.py`（新） | 开关状态读取 | U3/U11 |
| `utils/blocked.py`（新） | 风控分类形状 | U10/U11 |
| `conf.py` / `conf.example.py` | 配置 | 删 `DEBUG_MODE`（U13） |
| `tests/test_xiaohongshu_uploader.py` | 现有单测（`FakeLocator`/`RecordingPage`/`FakeKeyboard`） | 拆分 + 改写（U12） |
| `docs/CLI.md` | 派生投影 | 逐条回写（§9.2） |

### 2.2 十一个现存缺陷（本规格的靶子）

| # | 缺陷 | 证据 |
| --- | --- | --- |
| 1 | **发布按钮选择器全死**：`button:has-text("发布")`（`:1182`/`:1365`）/ `("定时发布")`（`:1180`/`:1363`）现网 0 命中，`xhs-publish-btn` 在代码里零命中 → 每次点击等到超时 | `[实机]` 02；`[代码明确]` |
| 2 | **点击可重入**：`publish_clicked` 在点击前未置位，点击抛错时循环重入点击（同一次运行可点两次，demo S5 已复现 2 次点击 + exit 0） | `[代码明确]` `main.py:1170-1201` / `:1353-1384` |
| 3 | **登录判定是子串匹配**：`_LOGIN_URL_MARKERS`（`:101`）对整条 URL 匹配（`login`/`captcha`/`verify`/…），query 里带 `login` 即命中，且本地模式因 `if multilogin:` 门**完全不判登录页** | `[代码明确]` `main.py:101-117` |
| 4 | **预算无 clamp**：小红书 0 处 `clamp_ms`/`clamp_seconds`，`wait_for_url`（`:1106`/`:1314`）、`wait_for_selector(...,timeout=3000)`（`:1112`）、`upload_input.wait_for(...,timeout=30000)`（`:1320`）、`title_container.wait_for(...,timeout=3000)`（`:1328`）用裸超时；观察窗还被写死 `timeout_ms=3000`（`:1184-1186`/`:1367-1369`） | `[代码明确]` |
| 5 | **文案扫描**：`_XHS_PUBLISH_FAILURE_KEYWORDS`（`:54-62`）+ `_find_publish_failure`（`:656-687`）7 类容器 × 最多 12 元素 × 每 0.3s 扫 toast，无真机证据且不改变结局 | `[代码明确]` |
| 6 | **上传完成靠关键词与标题框**：`:1118` 的 `['上传成功','分辨率','100%',…]`、`:1122-1127` 的 `div.stage`、`:1139-1142` 的标题框都会提前误判；`handle_upload_error`（`:1033-1035`）无调用点（死代码） | `[实机]` 02；`[代码明确]` |
| 7 | **话题不校验**：点候选第一项、不回读；整页 `a[data-topic]` 每次 +2（含预览镜像） | `[实机]` 02/23 |
| 8 | **元数据静默截断**：`fill_title` 的 `self.title[:20]`（`:592`）；定时开关/时间零回读（`:522-529`）；`#publish-container`（`:834`）是 class 写成 id，主路径恒 0 靠 JS 兜底 | `[实机]` 22/26；`[代码明确]` |
| 9 | **双重预检**：本地 `cookie_auth`（`:335-378`，网络）+ 托管 `is_logged_in`（`:286-332`）各起一次浏览器/发布页，一次发布 2 次浏览器 / 2 次发布页 / 4 个 context | `[代码明确]` |
| 10 | **模式漂移**：8 处 `if multilogin:` 门（`:1104`/`:1173`/`:1192`/`:1196`/`:1312`/`:1356`/`:1375`/`:1379`）；文案写死 "Multilogin"（`:113-117`），AdsPower 用户被指错 App | `[代码明确]` |
| 11 | **默认值混乱**：`set_defaults(headless=True)`（`sau_commands/arguments.py:90`）；`DEBUG_MODE` 三处口径不一（`conf.py:7`、uploader 默认 `:480`/`:996`/`:1261`、CLI `--debug` 默认 False）且 CLI 路径从未读过它；托管静默丢弃 `launch_kwargs` 等四类参数（`utils/browser_session.py:139-144`） | `[代码明确]` |

---

## 3. 改动单元

每个单元统一七段：**现状 / 目标 / 判定标准 / 失败语义 / 测试点 / 验收方式 / 顺序与依赖**。单元之间没有隐含顺序，§5 给出可执行的分批。

### U1 预算底座（clamp）

**现状** `[代码明确]`

- `PublishTimeoutBudget` 已在 `uploader/publish_timeout.py` 就绪（15 分钟契约见文件头注释），小红书已调用 `start_publish_budget`（`main.py:648`，调用点 `:1097`/`:1305`）与 `wait_until_allowed`（`:1164`/`:1347`）。
- 但小红书**零 clamp**：`page.wait_for_url(publish_url)`（`:1106`/`:1314`，Playwright 默认 30s）、`wait_for_selector('input.upload-input', timeout=3000)`（`:1112`）、`upload_input.wait_for(state="attached", timeout=30000)`（`:1320`）、`title_container.wait_for(state="visible", timeout=3000)`（`:1328`）。上传等待还是裸 `asyncio.sleep(2)`（`:1146`）/ `sleep(1)`（`:1333`）。
- 对比：TikTok / 抖音 / 知乎 / 微博 已全部 clamp。

**目标** 单一 deadline 贯穿整条链路；任何等待的实参一律来自 `budget.clamp_ms()` / `budget.clamp_seconds()`。

**判定标准**

1. 发布链路内**零**裸 `timeout=` 字面量（静态断言）。
2. 每次等待前先 `check_pre_click()`；`clamp` 返回 ≤0 → `budget.pre_click_error()`。
3. 点击前预算耗尽 → `exit 1`（文案 `发布超时（15 分钟）：尚未点击发布，未发布任何内容`）；点击后耗尽 → `exit 9`。**这两个出口只能由预算模块产生，不允许业务代码自定义"处理超时"。**
4. 不设"就绪超时"独立错误类型：单次等待用尽 → 该环节 `ElementUnusableError`（`exit 1`）。
5. 登录/会话预检不计入 15 分钟预算（它发生在任何导航之前或作为导航后观测，见 U9）。

**失败语义** 点击前 = `budget.pre_click_error()`（返回 `RuntimeError`）→ **1**；点击后 = `budget.timeout_error(publish_clicked=True)`（`PublishResultUnknownError`）→ **9**。**不加新错误类、不加新码**（`clamp_*` 在预算耗尽时自身就抛 `pre_click_error()`）。

**测试点** clamp 返回值随剩余预算收缩；预算耗尽点分别落在点击前/后 → 1/9；`--not-before` 顺延后剩余预算正确；`PublishTimeoutBudget` 既有 10 条用例只加不改。

**验收** 离线单测 + 静态断言（`rg "timeout=[0-9]" uploader/xiaohongshu_uploader/` 为空）。

**顺序与依赖** 最先做（U2/U3/U6/U7/U8 全部依赖 clamp）。依据 [03](./issues/03-publish-submit-semantics.md)、[06](./issues/06-readiness-and-visibility.md) §4。

---

### U2 提交语义：ARM → FIRE → OBSERVE

**现状** `[代码明确]`

- 点击前无就绪谓词（`xhs-publish-btn` / `is-publish` / `submit-disabled` 在生产代码**零命中**）；`publish_clicked` 在点击**之后**置位，点击抛错时循环重入（`:1170-1201`/`:1353-1384`）。
- 成功判据已是"URL 命中 `publish/success`"（`:699`），但观察窗写死 3s（`:1184-1186`/`:1367-1369`）、每 0.3s 扫 7 类容器找拒绝词（`:656-687`/`:689-716`）。
- `XHS_PUBLISH_SUCCESS_URL_PATTERN`（`:32`）定义后从未使用（死常量）；`--no-publish` 在**任何就绪判断之前** return（`:1160-1162`/`:1343-1345`）。

**目标** 三段式，单次运行**至多派发一次**。

**判定标准**（可直接实现）

| 阶段 | 观测 | 结论 | 码 | 可重试 |
| --- | --- | --- | --- | --- |
| ARM | 就绪谓词未满足，1s 后再试 | 继续等 | — | 是（**唯一允许重试处**） |
| ARM | 窗 `min(60s, 剩余预算)` 用尽 | 确定未发布 | 1 | 是 |
| ARM | 预算耗尽 | 确定未发布 | 1 | 是 |
| ARM | 轮内命中登录/验证（C2） | 会话失效，未发布 | 10 | 是（修会话后无条件重跑） |
| FIRE | 派发后任意异常 | 可能已发布 | 9 | 否 |
| FIRE | 派发后异常且页面已是登录/验证 | 会话失效，可能已发布 | 10 + `publish_attempted=true` | 否（先核对） |
| OBSERVE | `min(15s,剩余预算)` 内 URL 离开 `/publish/publish` 且不是登录/验证页 | 成功 | 0 | — |
| OBSERVE | 窗口内落登录/验证页（C4） | 会话失效，可能已发布 | 10 + `publish_attempted=true` | 否（先核对） |
| OBSERVE | 15s 到点仍在 `/publish/publish` | 未确认成功（可能已发布） | 9 | 否（先核对） |
| OBSERVE | 预算先于 15s 耗尽 | 结果未知 | 9 | 否 |

**ARM 谓词（唯一一份，09 复用）**

1. `xhs-publish-btn` 存在；2. 按 06 的 `interactive` 档可用（含 `disabled`/`pointer-events`/hit-test）；3. `is-publish != "false"`（属性缺失视为通过）；4. `submit-disabled != "true"`（属性缺失视为通过）。
- 每轮**重新解析**，不缓存 locator（抗重渲染）。
- 新版存在但禁用时**不回落旧版**；旧版选择器整体删除（见 U4）。
- 定时发布复用同一元素（只变 `submit-text`）`[实机 26]`，**不按策略换按钮**。

**FIRE**

1. 先置 `publish_clicked = True`，再派发（不变量：置位在不可回退点之前）。
2. 派发前顺序：`before_submit` 停顿（U5）→ 落点复核（`interactive` hit-test，U3）→ 人类化点击（U5）。
3. 点击机制必须能回答"确定未派发 / 可能已派发"：`mouse.down` 之前任何异常 = 确定未派发；`mouse.down` 之后任何异常 = 可能已派发。
4. 派发后无论抛什么，**不再触碰按钮**。

**OBSERVE**

- 500ms 轮询；判据只认 URL：`urlsplit(page.url).path` 不含 `/publish/publish` 且 `classify_blocked()` 为 `None` → 0。
- **禁止**任何文案扫描（限流词/拒绝词/toast 全删，三张词表为空）。
- C4 轮询与 URL 判定同一循环：分类命中优先级高于"仍在页面上 → 9"。

**`--no-publish`（干跑）**

- 语义升级为"**跑到 ARM 就绪**"：谓词通过 → 打一条日志 → `return 0`，不进入 FIRE。
- 干跑**跳过** `wait_until_allowed`（不被 `--not-before` 卡住）。
- ARM 未就绪 → `exit 1`（预期信号，不是缺陷）。
- 定时发布干跑同样执行 U8 的 C1/C2/C3。

**失败语义** 见上表；异常类型：`RuntimeError`（ARM/上传/话题，均 1）、`PublishResultUnknownError`（9）、`LoginRequiredError`（10）。**不新增错误类，不新增退出码。**

**测试点** 谓词四条件逐个不满足 → 继续等；满足 → **恰好 1 次** `mouse.down`；FIRE 抛错 → 9 且零二次点击；ARM 用尽 → 1；离开 + 非登录页 → 0；15s 未离开 → 9；登录页命中 → 10 且 `publish_attempted` 正确；零文本扫描（断言无 toast 扫描调用、无关键词常量）。

**验收** 离线（虚拟时钟 + `RecordingLocator.click` 计数）；真机正路 `--no-publish` 见 §9.3。

**顺序与依赖** 依赖 U1、U3、U5 的点击接口；与 U10（分类器）联调。依据 [03](./issues/03-publish-submit-semantics.md)、[04](./issues/04-rate-limit-and-rejection.md)、[07](./issues/07-risk-page-classification.md)。

---

### U3 判定原语与页面就绪

**现状** `[代码明确]` 28 处 `count()`（存在性判定）+ 9 处 `force=True`（`:830`/`:838`/`:857`/`:869`/`:876`/`:893`/`:930`/`:934`/`:1057`）；`is_logged_in` 的正向锚点只做 `count()`（`:324-326`），隐藏元素也算命中；无 hit-test，遮挡靠 `force=True` 绕过。

**目标** 新模块 `utils/dom.py`（共享层，06 §5 + 15 接口草案），零平台知识。

**判定标准**

**A. 页面就绪**

1. `goto` 统一 `wait_until="domcontentloaded"` + clamp；`wait_for_url` 仅作 URL 守卫，同样 clamp。
2. 首次交互前执行**一次** DOM 静默门：`MutationObserver`（`childList`+`attributes`+`characterData`，`subtree`），连续 500ms 无变更通过，总上限 3s（clamp）。未静默 → `warning`（`dom-not-quiet`）+ 继续，**不失败**。
3. 静默门只做一次；之后每个动作等自己的目标，不再有就绪类固定 `sleep`。

**B. 四档角色**（`check(locator, role, *, point=None) -> (ok, reason)`）

| 角色 | 判据 | reason 枚举 |
| --- | --- | --- |
| `ATTACHED` | 在 DOM 且 connected；`count()==1`（多义 → `ambiguous:N`，禁止 `.first`）；容器/属性匹配；不要求可见 | `not-attached` / `ambiguous:N` |
| `VISIBLE` | `is_visible()` 且祖先链 `display/visibility` 非隐藏、`opacity` 连乘 ≥ 0.1（**计算样式**）且自身 `aria-hidden != "true"` | `zero-box` / `opacity-zero` / `aria-hidden` |
| `INTERACTIVE` | `VISIBLE` + 非 `disabled`/`aria-disabled="true"`/class 词元 `disabled` + `pointer-events != none` + 真实落点 `elementFromPoint` 命中自身或后代（默认落点=包围盒中心；发布按钮用 65% x） | `disabled` / `covered-by:<tag.class\|#id\|text[:40]>` / `probe-failed` |
| `EDITABLE` | `VISIBLE` + 非 `readonly`/`disabled` +（`input`/`textarea` 或 `contenteditable="true"`） | `readonly` / `not-contenteditable` / `disabled` |

**C. 不确定时分档（按"离派发远近"）**

| 来源 | 处理 |
| --- | --- |
| `VISIBLE`/`ATTACHED` 探测抛异常 | **放行** + `warning`（兜底是 Playwright actionability，`force=True` 已删） |
| `INTERACTIVE` hit-test 探测抛异常 | **阻断** `ElementUnusableError(reason=probe-failed)`（否则会被记成"可能已发布"→ 9） |
| 祖先（非自身）`aria-hidden="true"` | 仅 `warning`，不判隐藏 |

**D. 遮挡清障**（最多 2 轮，每步后重新 hit-test）

1. 已知覆盖层注册表（数据驱动，按 U4 锚点）：`.feature-guide__btn`「我知道了」→ 点击；图文 `role="dialog"`「图片可以编辑啦」→ 弹窗内确认/关闭；`div.d-popover` → `Esc`。
2. `Esc` → 200ms → 再 hit-test。
3. 仍未通过 → `ElementUnusableError(covered-by:…)`。
- **永不**摘节点/注入 `display:none`；**永不**点空白；正文字段输入中不清障（例外：`.feature-guide__btn` 可随时点）。

**E. 首目标表（环节 → 角色 → 信号）**

| 环节 | 角色 | 目标信号 |
| --- | --- | --- |
| 视频/图文上传前 | `ATTACHED` | `.upload-content input.upload-input`（`accept` 含 video/image，唯一） |
| 标题 / 正文 | `EDITABLE` | `div.d-input input` / `div.tiptap[role=textbox]` |
| 发布按钮 | `INTERACTIVE` | U2 的 ARM 谓词 |
| 上传完成 | — | 归 U6 |
| 开关/弹窗按钮 | `INTERACTIVE` | U4 对应锚点 |

> 反例（必须留在实现注释里）：空状态没有标题/发布按钮；视频标题框 t=3s 已在但按钮 t≈12s 才可点 → **"元素出现"不能作为阶段就绪判据**。

**失败语义** `ElementMissingError(what, role, tried, elapsed_ms, publish_clicked)` / `ElementUnusableError(what, role, selector, reason, tried, elapsed_ms, publish_clicked)` → 一律 **1**；`publish_clicked` 只改文案（"未点击发布" / "发布可能已发出"），不升级为 9。

**测试点** 四档边界 + `ambiguous:N`；`probe-failed` 阻断 / 可见性探测失败放行；覆盖层两轮上限、不摘节点；静默门 500ms/3s（虚拟时钟）；所有等待实参 clamp。

**验收** 离线；真机验证覆盖层实际行为（§8.3）。

**顺序与依赖** U1 之后、U2/U4-U8 之前。依据 [06](./issues/06-readiness-and-visibility.md)、[15](./issues/15-shared-layer-boundary.md)。

---

### U4 选择器基线矩阵

**现状** `[代码明确]` 与 `[实机]` 见下表"现选择器"列；三处死锚点：发布按钮三条中文 `has-text`、`#publish-container`（实为 class `.publish-container`）、封面 `div.upload-cover` / `.cover-plugin-preview div.default.pointer`。

**目标** 结构优先、文本最后；发布主链路（上传→标题→正文→话题→发布）**零中文依赖**；文本兜底只在结构失败后且**只保留中文**（`locale=en-US` 下界面仍全中文，无英文界面 `[实机 22]`）。

**判定标准**

1. 候选按"容器限定 + 结构属性（id > 容器 class > 设计系统类）> 元素属性 > 文本"排序。
2. 统一解析器：`resolve(scope, candidates) -> Resolved(locator, selector, kind, role)`；`kind ∈ {structure, upstream, text-zh}`。
3. 命中日志：每次解析打 `debug`（环节、kind、selector、URL）；`kind != structure` 额外打 `info`。
4. 文件输入类（图文/视频/封面）**禁止无条件 `.first`**：`count != 1` 且无法用容器收窄 → `unusable`（多义）。
5. 新分支稳定命中且旧分支 0 命中 → 删旧分支（删除条件见矩阵末列）；文本兜底需在目标语言界面验证过一次。

**矩阵（实施时以此为准；`主候选` 之外都是兜底）**

| # | 环节 | 现选择器 | 主候选 | 兜底顺序 | 中文依赖 | 置信度 | 删旧条件 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 发布按钮（即时/定时共用） | `button:has-text("发布")` / `("定时发布")` — **0 命中** | `xhs-publish-btn` + `is-publish` + `submit-disabled` | 无（只留新版） | 无 | 即时=实机；定时=实机（同一元素，`submit-text` 变） | **本次直接删**旧版与三条中文 `has-text` |
| 2 | 标题 | `input[placeholder*="填写标题"]` | `div.d-input input`（与现选择器同一节点） | `input[placeholder*="填写标题"]` | 仅兜底 | 实机 | 结构稳定命中后删中文 |
| 3 | 正文 | `p[data-placeholder*="输入正文描述"]` | `div.tiptap[role="textbox"][contenteditable="true"]` | `div.ProseMirror[contenteditable="true"]` → 中文 placeholder 上溯 `[contenteditable=true]` | 仅兜底 | 实机 | 同上 |
| 4 | 图文上传 input | `input[type="file"][accept*=image]`.first | 首张 `div.upload-content input.upload-input`（`count==1`）；第 2 张起 `.img-preview-area .entry`（「+」瓦片）→ file chooser | `.img-list .top input[type=file][multiple]` | 无 | 实机（24） | 命中后删 `.first` 猜测 |
| 5 | 视频上传 input | `div[class^='upload-content'] input[class='upload-input']` | `div.upload-content input.upload-input` | `input[type="file"][accept*=".mp4"]` / `[accept*=video]` | 无 | 实机 | 删旧 `div[class^=...]` 写法 |
| 6 | 话题候选 | `#creator-editor-topic-container .item` → `.name` | 同现（上游同款） | 无 | 无 | 实机（50 项/次） | — |
| 7 | 话题回读 | **无** | `div.tiptap[role=textbox] a[data-topic]`（**限定编辑区**） | 无 | 无 | 实机（23：编辑区 +1，整页 +2） | — |
| 8 | 定时开关 | `.custom-switch-card` 过滤「定时发布」→ `.d-switch` | `.post-time-wrapper .d-switch` | `.post-time-switch-container .d-switch` | 无 | 实机（26） | 稳定后删中文卡片过滤 |
| 9 | 定时时间输入 | `.d-datepicker-input-filter input.d-text` | 同现 | `.date-picker-container input` | 无 | 实机（两者各 1） | **双结构兜底不设删除期限** |
| 10 | 原创开关 | `.custom-switch-card` 过滤「原创声明」→ `.d-switch` | `.original-wrapper .d-switch` | 中文卡片（容器限定 + 精确） | 仅兜底 | 实机 | 稳定后删中文 |
| 11 | 原创确认弹窗 | `[role=dialog], .d-modal, .d-dialog` 过滤「声明原创」 | `div.d-modal.creator-modal-style` | 确认按钮 `div.d-modal button.custom-button` → 文本 `声明原创` | 仅兜底 | 主=实机 1 样本；按钮=上游 | 两个账号各出现一次后删 `[role=dialog]` |
| 12 | 内容类型声明 | `get_by_text("添加内容类型声明")` + **`#publish-container div`（恒 0）** | `.publish-container` 内文本 `添加内容类型声明` 的 `[tabindex="1"]` | 同文案点击；选项限定 `.declaration-drop-down .d-option` + 精确文案 | **必须**（选项是中文枚举） | 实机（22） | 修 `.publish-container` 后 JS 兜底仅作后备 |
| 13 | 封面弹窗 | `text=设置封面` / `div.upload-cover`（**0**）/ `div.cover-plugin-preview div.default.pointer`（**0**）/「上传封面」/`div.upload-wrapper input[type=file]`/「确定」 | 悬停 `.cover-plugin-preview .cover > .default` → `.cover-edit-entry`（容器 `.cover-edit-stack`）→ `.d-modal.cover-modal.creator-modal-style.main-cover-editor-modal` → 弹窗内 `input[type=file][accept*=image]` 直接 `set_input_files` → `完成` | 文本 `编辑封面`；`上传` tab 仅在 input 缺失时兜底（点 tab 会拉起系统文件选择器，禁止作为主路径） | 仅兜底 | 实机（2026-11-12 跑通） | 已删 `设置封面` 文本兜底 |
| 14 | 登录二维码 | `.login-box-container` + 「APP扫一扫登录」+ xpath `following-sibling::div//img`；`img.css-wemwzq` | 切换图标 `img.css-wemwzq` → 二维码 `img.css-1lhmg90` | 文本 `APP扫一扫登录` 容器内 `img` | 仅兜底 | 实机（22） | 真机确认结构后删文本 xpath |
| 15 | 登录态正向锚点 | `input.upload-input`、`div.progress-div [class^="upload-btn-input"]`、`div[class*=upload-content] input`、`button:has-text("发布")`（**0**） | 前三条（零文本） | 无 | 无 | 实机（空状态） | **本次删**中文发布按钮 |
| 16 | 登录失效（负向） | `div[class*=login-box]` + URL `/login` 前缀 | **URL path 前缀优先**（`/login` → login；`/website-login/captcha` → verification；裸 `/website-login` → login），DOM 仅佐证 | — | 无 | 实机（`/login` + login-box；`/website-login*` 未观察到） | 不删；`/website-login*` 确认不出现后可由实施删除 |
| 17 | 添加图片瓦片（新增环节） | 无 | `.img-preview-area .entry`（含 `svg.add-img-icon`） | `.img-list .top input[type=file][multiple]` | 无 | 存在=实机；触发 filechooser=实机（24） | — |

**失败文案（两类，必须带"已尝试顺序"与"是否已点击发布"）** — 逐项模板见 [05](./issues/05-selector-baseline.md) 的"失败文案约定"表；实现时以错误对象字段（`what`/`tried`/`reason`/`publish_clicked`）填充，**不把选择器拼进成功日志**。

**失败语义** 缺失 → `ElementMissingError`；找到但不可用（含多义文件 input、`probe-failed`、话题回读不符）→ `ElementUnusableError`；一律点击前 **1**。

**测试点** 过渡期常量表断言（用于删旧分支时有断言跟着改，**旧分支删完即同批删除**）；永久保障 = "代码里只有一条路径" + 命中日志级别断言。行为断言：首选 `debug`、非首选 `info`。

**验收** 真机 `--no-publish` 正路看命中日志（首选结构分支）。

**顺序与依赖** U1/U3 之后立即做（U2/U6/U7/U8 都读这张表）。依据 [05](./issues/05-selector-baseline.md)、[22](./issues/22-english-ui-evidence.md)、[26](./issues/26-readback-signal-evidence.md)。

---

### U5 人类化交互（`utils/humanize.py`）

**现状** `[代码明确]` `fill()` 瞬时设值（定时 `:528`、标题 `:592`、拍摄地点 `:858`、拍摄日期 `:882`、转载来源 `:903`）；`keyboard.type(..., delay=30)` 固定间隔（`:626`；地点/正文另有 `delay` 缺省 `:539`/`:603`）；`_js_click_by_text` 走 `el.click()`（`:156-173`，`isTrusted=false`）；9 处 `force=True`；`Control+KeyA`（`:601`）在 macOS 下无效；`keyboard.insert_text` 全仓未用于打字。

**目标** 上游 11 个动作**全量实现**，按**语义锚点**接线；共享层，零平台依赖。

**判定标准**

**A. 参数表（原样采用上游，单例，平台不得复制）**

| 动作 | μ | σ | min | max | 均值 | 接线 |
| --- | --- | --- | --- | --- | --- | --- |
| `Keystroke` | -2.12 | 0.50 | 30ms | 400ms | 136ms | 每字符 |
| `AfterType` | -0.51 | 0.40 | 200ms | 3s | 0.65s | 每次输入完 |
| `AfterNavigate` | 0.41 | 0.45 | 600ms | 6s | 1.67s | `goto` 后 |
| `BeforeSubmit` | 0.0 | 0.40 | 400ms | 4s | 1.08s | FIRE 前（超出上游） |
| `PointerSettle` | -1.20 | 0.35 | 200ms | 1200ms | 0.32s | 每次点击 |
| `ClickHold` | -2.47 | 0.33 | 45ms | 250ms | 89ms | 每次点击（按下保持） |
| `BeforeClick` / `AfterClick` | -1.61 / -0.92 | 0.45 / 0.35 | 80ms / 150ms | 1s / 2s | 0.22s / 0.42s | 不默认接 |
| `BetweenScroll` | -0.22 | 0.40 | 250ms | 3s | 0.87s | 需要滚动时 |
| `Reading` / `AfterInteract` | -0.36 / 0.88 | 0.40 / 0.30 | 300ms / 2s | 3s / 3s | 0.76s / 2.52s | 不接（API 保留） |

**B. 打字：逐字符分派 + 千字分流**

1. `len(text) ≤ 1000`（`HumanizeProfile.type_horizon_chars`，单例常量）→ 逐字符：ASCII 走 `keyboard.press(char)`（真 key 事件），中文/emoji 走 `insert_text(char)`；每字符后采样 `Keystroke`。
2. `> 1000` → **一次** `keyboard.insert_text(text)`，零 `press`、零 `Keystroke` 采样；打一条 `info`（`type_text→bulk insert_text, chars=NNN`）；仍走一次 `after_type`。
3. **禁止**剪贴板 paste（失败会粘上一条内容 → 静默发错正文）、**禁止** `fill()`。
4. 输入长度**无时间上限**；超时按预算语义（点击前 1）。
5. 清理键保留并走采样；`Control+KeyA` → `ControlOrMeta+A`。

**C. 点击：全站统一**

顺序固定：`bounding_box` → 内缩 `min(size*0.15, 8px)` 随机落点 → 贝塞尔曲线移动（`steps=clamp(round(dist/10),10,40)`，控制点沿法线偏移，每步 5–9ms）→ `sleep(PointerSettle)` → **stillOn 复核**（落点元素仍是目标、位置 ±1px、按 `interactive` 档 hit-test）→ `mouse.down` → `sleep(ClickHold)` → `mouse.up`。

不变量：**内部零重试**（重试只在 ARM）；不存在无 `stillOn` 的坐标点击；`force=True` 全删；`el.click()` 全删。`bounding_box` 不可得或 `stillOn` 不符 → 抛"确定未派发"；`mouse.down` 之后任何异常 → 标记"可能已派发"。

**D. API 契约**（15 的接口草案）

```python
LogNormal(mu, sigma, min_s, max_s) / HumanizeProfile(11 个动作 + type_horizon_chars=1000 + enabled=True)
DEFAULT_PROFILE                      # 唯一参数表
Humanizer(page, *, profile=DEFAULT_PROFILE, rng=None, sleep=asyncio.sleep)
  .type_text / .click / .after_type / .before_submit / .after_navigate
  .between_scroll / .reading / .after_interact / .before_click / .after_click
```

- 注入 `rng` / `sleep`；同一 seed 完全可复现。
- 总开关：`profile.enabled=False` 或 `HUMANIZE=0` → 零时延快路径（文本一次 `insert_text`、点击一次 `locator.click`）。
- 平台差异只用 `dataclasses.replace(DEFAULT_PROFILE, ...)`；不 import `uploader.*`。

**E. 接线表（小红书）**

| 时点 | 动作 |
| --- | --- |
| `goto` 后 | `after_navigate` |
| 每次点击（约 22 处） | `click()`（内含 settle + stillOn + hold） |
| 每次文本输入完（标题/正文/话题/日期/地点/来源） | `type_text` + `after_type` |
| FIRE 前一次 | `before_submit` |
| 真实滚动处 | `scroll_into_view_if_needed` + `between_scroll` |
| `Reading`/`AfterInteract`/`BeforeClick`/`AfterClick` | **不接** |

**F. 时间上界（15 分钟预算内）** 标题 20 字 ≈2.7s；正文 1000 字 ≈2.3min；10 标签 ≈10.9s；总计 ≈2.6min。

**失败语义** 文本/点击异常 → 原样上抛，由调用点按"确定未派发/可能已派发"分类（U2/U3）；不新增异常类型、不新增退出码。

**测试点** 字符分派（ASCII `press` / 中文 `insert_text`）；`sleep` 次数与区间；点击序列 `move→settle→stillOn→down→hold→up`；`stillOn` 失败**无 `down`**；同 seed 可复现；`HUMANIZE=0` 零 sleep；1000/1001 边界（1001 → 恰 1 次 `insert_text`、0 `press`）；`fill(`/`el.click()`/`force=True` 静态计数 = 0（**豁免** YouTube `_fill_editable`，见 U11）。

**验收** 离线断言 + 真机 dry-run（`--no-publish`）+ `HUMANIZE=0` 对照。

**顺序与依赖** U1/U3 之后、U2 的点击接口前完成。依据 [10](./issues/10-humanize-subset.md)、[25](./issues/25-long-text-budget.md)。

---

### U6 上传完成判定

**现状** `[代码明确]`/`[实机]` 图文一次性塞全部文件（`:1316-1322` 的 `set_input_files`）后等"标题框出现"；视频靠关键词 `['上传成功','分辨率','重新上传','编辑封面','已上传','已选择','100%']`（`:1118`）+ `div.stage` 扫描（`:1122-1127`）+ 标题框兜底（`:1139-1142`）；`handle_upload_error`（`:1033-1035`）无调用点。

**目标** 素材就绪是填元数据的前置闸；闸门各自只认一个结构信号；**任何一次失败整体中止**。

**判定标准**（状态表）

| 内容 | 观测 | 动作 | 码 |
| --- | --- | --- | --- |
| 图文 | 第 i 张已派发，`.img-preview-area .pr` 数 ≥ i+1 **且** `tiles[i].querySelector('.mask.uploading') == null` | 派发第 i+1 张 | — |
| 图文 | 派发后 60s（clamp）未到 i+1 | 中止，`unusable`（含第 k/共 N 张 + 未点击发布） | 1 |
| 图文 | 计数 == N，复检一次 DOM 静默（500ms/上限 3s）后仍 ≥ N | 进 `fill_meta` | — |
| 图文 | 静默后计数 > N | `warning`，继续（多图可事后人工删） | — |
| 图文 | 静默后计数 < N | 继续等到 60s 窗口耗尽 → 中止 | 1 |
| 视频 | U2 的 ARM 谓词满足 | 进 `fill_meta` | — |
| 视频 | 600s（clamp）未满足 | 中止，`unusable`（含禁用原因） | 1 |
| 视频 | `div.fail`（class 恰为 `fail`） | **立即**中止，`unusable`（不等 600s）；`.video-container-loading-text` 是进度文案（正路「视频上传中」），**不判失败** | 1 |
| 两者 | 预算耗尽 | U1 的 pre-click 文案（不是"处理超时"） | 1 |
| 两者 | 上传 input 缺失/多义/`set_files` 抛错 | 立即中止（不等待） | 1 |
| 两者 | `--no-publish` | 仍过就绪闸，然后停 | 0 |

**图文实现约束**

1. **逐张派发**（不批量）；张间 1s；每张轮询 500ms。
2. 首张：`div.upload-content input.upload-input`，`count == 1`。
3. 第 2 张起：点 `.img-preview-area .entry`（"+"瓦片）→ `expect_file_chooser()` → `set_files([1 张])`；备选 `.img-list .top input[type=file][multiple]`。
4. **禁止** `inputs[0]` / `.first` 兜底（会把视频 input 当图片 input）。
5. **不重传**、不降级少图：重传同文件会 N+1，且失败后重跑代价低。
6. 收口：最后一张后再等一次 DOM 静默，静默后复检计数（吸收"预览数到位 ≠ 服务端收齐"）。

**视频实现约束**

1. 谓词**只有一份**（U2 ARM helper），两个窗口：就绪窗 `min(600s, 剩余预算)` / 1s；点击窗 `min(60s, 预算)`。
2. 删除全部关键词扫描、`div.stage` 扫描、"标题框出现即放行"。
3. `div.fail`（class 恰为 `fail`）是唯一即时失败信号。`.video-container-loading-text` 与进度共用（2026-11-12 真机：正路「视频上传中」，失败「视频上传失败，请重新上传」且同时存在 `div.fail`），因此**不**作信号、不恢复文案扫描。`input.upload-input` 恒在、`submit-disabled` 失败态恒 `true`，都**不能**当信号。
4. 60s/张 与 600s 就绪窗不缩短（20MB PNG 实测 25.5s，慢时段 >40s）。

**失败语义** 上传失败统一 `RuntimeError`（`missing`/`unusable`，点击前）→ **1**；不按图文/视频/第几张分叉。

**测试点** `.pr` 计数 + `.mask.uploading` 消失判完成；`div.fail` → 1；静默复检 ≥N 放行 / >N warning；第 2 张走 file chooser；预算耗尽文案；`--no-publish` 同闸。

**验收** 真机图文 2 张 + 视频正路 + 假 mp4（`div.fail`）注入，见 §9.3。

**顺序与依赖** U1/U3/U4 之后。依据 [09](./issues/09-upload-completion.md)、[24](./issues/24-multi-image-timeline-evidence.md)。

---

### U7 话题插入与校验

**现状** `[代码明确]`/`[实机]` 点候选**第一项**（`:627-633`，不读 `.name`、不校验）、点完不回读（`a[data-topic]` 在代码中零命中）；上限三处口径（CLI `>10` 报错 `return 1`、`fill_tags` 运行时静默截断 `:610-616`、失败时 `Backspace` 清理 `:634-641`）；整页 `a[data-topic]` 每次 +2（含预览镜像）。

**目标** 话题是**增强项**：缺失一律降级；**插错必须中止**。

**判定标准**

| 情形 | 动作 | 出口 |
| --- | --- | --- |
| 候选未出现，或 3 次点击后 **0 个新增** | 降级：保留纯文本 `#tag` + 一个空格，`warning` | 无失败 |
| 新增 ≥1，但 name **≠** 请求 tag（含 `data-topic` 解析失败） | 中止（点击前），`reason=topic-mismatch` | 1 |
| 新增 **> 1**（编辑区内） | 中止（`reason=topic-multi-insert`） | 1 |
| 恰好 1 个新增且 name 全等 | 成功 | — |

**候选匹配**

1. 顺序扫描 `#creator-editor-topic-container .item` **全部**渲染项（真机热榜排序，精确项可能在第 4 位）；读 `.name` 的 `text_content()`。
2. 归一化（两侧同规则）：去前导 `#` → `strip` → 内部连续空白折叠 → `casefold`。
3. 只点 name **全等**项；多个全等取最前并打 `info`（`topic-ambiguous:N`）；**无全等即判无候选**，不做前缀/包含匹配。
4. 容器需 `ATTACHED`；被点项需 `INTERACTIVE`。

**候选就绪与重试**

1. 轮询 200ms，deadline `min(5s, clamp)`，每轮**重新扫**。
2. **就绪条件 = `.item` 数 > 0**，不是容器可见（容器以 0 项空壳先出现，约 430–570ms 才出 50 项）。
3. 最多 **3 次**点击；退出条件：连续找不到 / 用满 3 次 / deadline 到。
4. 循环内**不回读**；循环后统一回读一次。

**回读判据**

1. 作用域 = 正文编辑器根 `div.tiptap[role=textbox]`（不查整页；预览镜像在编辑器外）。
2. 基线 `S0` **按标签条目固定**：该标签第一次点击前取一次，**重试不刷新**；新增 = 点击后多重集合 − `S0`。
3. 轮询 50ms，窗口 `min(1s, clamp)`；节点只需 `ATTACHED`。
4. `data-topic` → JSON → `name`；解析失败算"name 未知"→ 插错。

**正文形态（无候选）** 保留 `#tag` + 一个空格，**不按 `Backspace` 清理**（连击是机器节奏，且可能多删正文）。

示例（`desc="海边的日落"`，`tags=["旅行","治愈"]`，`旅行` 无候选）：
- 现状：`海边的日落⏎#治愈[话题]#`
- 本规格：`海边的日落⏎#旅行 #治愈[话题]#`

**输入前复位** **不做** `ArrowDown×20 + Enter×2`（220 事件/10 标签 + 可能加空段落）；23 已证连续插入无需任何复位。

**上限口径** 只在校验期一处：`validate_upload_args()`（发布前、开浏览器前）`>10` → `warning` 列出被丢弃项 + `tags[:10]`；删除 `fill_tags` 运行时截断（`:610-616`）；CLI 两处 `>10` 由报错 `return 1` 降为同文案 warning（`sau_commands/xiaohongshu.py:404-406` video / `:432-434` note）。

**失败语义** 插错/多插 → `ElementUnusableError`（`reason` 如上，带 `tag`/`observed_names`/`new_nodes`/`attempts`）→ **1**（点击前）；**不新增退出码**。

**测试点** 全等匹配（1/4/50 项）；0 项空壳不误判；无候选降级 + 空格；插错中止；编辑区 2 个新增 → 中止；**基线不刷新**；预算 clamp；截断口径。

**验收** 离线为主；真机多话题插入已由 23 取证，无需重复。

**顺序与依赖** U3/U4 之后（依赖 `ATTACHED`/`INTERACTIVE` 与编辑区锚点）。依据 [08](./issues/08-topic-insertion.md)、[23](./issues/23-topic-multi-insert-evidence.md)。

---

### U8 元数据、越限与定时回读

**现状** `[代码明确]`/`[实机]` `fill_title` 的 `self.title[:20]` 静默截断（`:590-592`）；无正文越限检查；定时开关/时间零回读（`:522-529`，日期被拒失焦后静默回滚 → 按错误时间发布）；原创只有点前状态读取（`:945-971`）；声明失败降级（`:788-841`）、封面失败降级（`:1037-1094`）。

**目标** 不可逆动作前的表单状态尽量可证；能证则拦，不能证则记录为已知缺口。

**判定标准**

**A. 控件 × 设置 × 回读 × 不一致动作**

| 控件 | 设置 | 回读 | 不一致/失败 |
| --- | --- | --- | --- |
| 标题 | 按平台口径预检后**原样**填充（不截断用户输入） | 输入后**等待 ≥350ms / 轮询至 500ms** 再查 `.edit-container .suffix.max_suffix`（或 `.d-input-wrapper.c-input_max`）**存在性** | 存在 → `exit 1`（未发布） |
| 正文 | 逐字/批量输入（U5）+ 话题（U7）全部完成后 | 单次查 `div.edit-container div.length-error` 存在性 | 存在 → `exit 1` |
| 定时开关 | 点击 `.post-time-wrapper .d-switch` | **C1**（点后）+ **C2** + **C3**（见 C） | `exit 1` |
| 定时时间 | 逐字写入 `YYYY-MM-DD HH:MM` | **C2**（`blur()` 后约 300ms 读 `input.value`）+ **C3** | `exit 1` |
| 原创 `true` | 点前读状态（`read_switch_state`）；未开 → 点击 + 确认弹窗（勾选须知 → `声明原创`） | 点后**不读** | 任一步失败 → `exit 1` |
| 原创 `false` | 点前读；开着 → 点一次关；控件缺失视为 off | 点后不读 | `warning` 继续 |
| 原创 `None` | 不操作 | — | — |
| 内容类型声明 | 现有流程（入口 + 选项 + 二级字段） | 无 | `warning` 继续 |
| 封面（视频） | 现有流程（`.cover-edit-entry` → 弹窗 `上传`/`完成`） | 无 | `warning` 继续，首帧兜底 |
| 封面（图文） | 第 1 张图即封面 | — | — |

**B. 标题长度口径（平台口径，上游等价式）**

```text
weighted = Σ(2 if utf16_unit > 127 else 1 for each UTF-16 code unit)
length   = ceil(weighted / 2)          # ≤ 20
```

- 显式传入超限 → `validate_upload_args` 抛 `ValueError`（浏览器未启动）→ **1**，消息含"当前 X / 上限 20"并注明口径；**不截断**。
- 自动推导标题 → 同口径截到 ≤20 + `warning`。
- `fill_title` 删除 `self.title[:20]`。

**C. 定时三检查点**

| 点 | 项 | 信号 | 时机 |
| --- | --- | --- | --- |
| C1 点后 | 开关 | `.d-switch-simulator` class **含 `checked` 且不含 `unchecked`**；`.date-picker-container input` `attached` | 点击后（06 就绪，不用固定 `sleep(1)`） |
| C2 写入后 | 开关 + 值 | 开关同 C1；`input.value` 以 `%Y-%m-%d %H:%M` 解析后**按分钟** == 请求值 | `blur()` → 约 300ms → 单次读（不轮询） |
| C3 FIRE 前 | 开关 + 值 + 时效 | 同 C1/C2；且请求值**仍 > now()**（本机墙上时间） | ARM 就绪后、`wait_until_allowed` **之后**、FIRE 之前 |

- 解析比较，不要求字符串全等；读失败/空值/不可解析 = 不一致；**不重试**；`--no-publish` 同样检查。
- **失焦只许 `blur()`**：禁止 Tab / Enter（26 复现：Tab 把焦点交给发布按钮，Enter 触发「暂存离开」并离开编辑器）；也不点空白区。
- 边界：`now + 2h < t <= now + 14d`；**墙上时间语义，不换算**（aware 输入忽略 offset，按其自带墙上时间格式化）。下界已有（`uploader/base_video.py:81-96`，min lead 2h），**上界 14d 为新增**；越界在 `validate_base_args` → 1（浏览器未启动）。
- 即时发布（`publish_date` 为空）完全不进入 C1–C3。

**D. 正文长度**

- 时机：正文 + 话题全部输入完成后单次检查；**节点存在即失败**（不判可见、不读数值）。
- 计数口径：正文逐字符计数，上限 1000；话题锚点**计入**且按 `#name` 计（`#旅行pov[话题]#` → 7），与标题的 UTF-16 加权**不同**。
- 越限时 `submit-disabled` 仍为 `false`（平台不拦）→ 点击前检查是唯一闸门。

**失败语义** 全部发生在点击前 → **1**（`publish_attempted=False`）；不新增码、不产生 9、不写回账号文件。

**测试点** 标题 UTF-16 加权（ASCII/CJK/emoji/组合字符边界）；自动标题截断；2h/14d 边界；aware offset 被忽略；`max_suffix` 等待窗口；正文 `length-error`；C1/C2/C3 五种失败（回滚、迟到重置、时效过期、读失败、不可解析）；`--no-publish` 同拦；即时发布不进检查。

**验收** 真机定时正路只证明"能到 ARM"（不证明定时生效，见 §8.3）。

**顺序与依赖** U3/U5/U7 之后。依据 [11](./issues/11-set-then-readback.md)、[26](./issues/26-readback-signal-evidence.md)、[27](./issues/27-schedule-readback.md)。

---

### U9 会话、身份与 `check`

**现状** `[代码明确]` 发布链路本地跑 `cookie_auth`（网络，`:335-378`）、托管跑 `is_logged_in`（`:286-332`），各带一个 `_xhs_user_agent` 探测 context（`:139-153`）→ 一次发布 2 次浏览器 / 2 次发布页 / 4 个 context；`cookie_auth` 任意异常 → `False`（网络故障 = 失效，`:374-376`）；本地 `invalid` 退出码为 1（`sau_commands/xiaohongshu.py:394-396`）；`check` 只读不写；登录成功写回后**再起第二个浏览器复核**（`:437-438`）。

**目标** 会话可用性只有一个权威来源：**发布页那一次导航后的只读观测**；网络故障 ≠ 失效。

**判定标准**

**A. 发布前预检（只有一条零网络快路）**

| 模式 | 前置 | 失败 |
| --- | --- | --- |
| 本地 | ① 账号文件存在；② `storage_state` 有 `galaxy_creator_session_id`；③ 该 cookie `expires` 未过（`expires ≤ 0` 视为未知 → 放行） | **10**，**不启动浏览器**，stderr 给 `sau xiaohongshu login --account …` |
| 托管 | 无前置 | — |

- **删除** `cookie_auth` 与 `is_logged_in` 两个预检（发布链路）。
- 真判定交给 C1（goto 后 `classify_blocked`）→ 命中 10。

**B. 风控分类器**

`classify_blocked(page) -> None | "login" | "verification"`（同步、只读、不注入 JS）：

1. 读 `urlsplit(page.main_frame.url).path`；**只比 path**，不读 query、不 `unquote`。
2. 路径集（长前缀优先）：`/website-login/captcha` → verification；`/website-login`（裸与未知子路径）→ login；`/login` → login；其余 `None`。
3. path 未命中时补强：`div[class*='login-box']` 按 06 的 `visible` 档可见 → login（短路：path 命中不查 DOM）。
4. **不做**非跳转式验证码弹层识别；读失败按"不拦截"处理。

**C. 检查点（两端必调，模式只决定文案）**

| 点 | 位置 | `publish_attempted` |
| --- | --- | --- |
| C1 | `goto` 之后 | False |
| C2 | 每个可能 >2s 的等待循环每轮一次（视频预览轮询、图文标题等待、ARM 轮询） | False（ARM 轮内仍为 False） |
| C3 | `wait_until_allowed` 之后、进 ARM 之前（**必查**，最后安全退出点） | False |
| C4 | OBSERVE 轮询（500ms） | **取自 `publish_clicked` 变量**，True |
| — | FIRE 异常分支 | True |

- `publish_attempted` **必须现取 `publish_clicked`**，禁止按调用点硬编码。
- 检查点抛出的 `LoginRequiredError` 不得被宽 `except Exception` 吞掉（视频预览轮询 `:1144`、图文标题等待 `:1331`、FIRE 分支）。
- 合并规则：**页面状态命中压过同点的一切超时/异常分类**；命中绝不把 0 抬成 10。

**D. `check` 行为契约**

```text
本地: 前置(0 网络) ──失败──▶ invalid / 10（不起浏览器）
        └─通过─▶ new_context(storage_state) ─▶ goto 发布页 ─▶ 观测
托管: 建 context(Profile) ───────────────────▶ goto 发布页 ─▶ 观测

观测 = classify_blocked(page)?
  ├─ login / verification ─▶ invalid + reason(stderr) / 10
  ├─ None 且上传入口锚点 attached (count ≥ 1) ─▶ valid / 0 ─▶ [本地] 原子写回
  ├─ None 且一个锚点都没有 ─▶ invalid + "页面结构异常" / 1
  └─ 导航 5xx / 超时 / 离开创作域 ─▶ 1（探测失败，不是失效）
```

- 页面 = **发布页**（不改轻量页）；锚点用 `attached` 档（后台健康检查，避免慢加载误判）。
- **不做**两级结果（`valid` / `valid-but-degraded`）；stdout 不变（`valid`/`invalid`），`reason` 走 stderr；`invalid` 退出码 1 → **10**。

**E. 登录链路**

- 扫码完成判定继续用 `_is_xhs_login_completed`（`:272-283`），但**判据换成** `classify_blocked` 返回 `None`，删掉现在并存的 `/login` 前缀判断与 login-box 可见判断两套。
- **删除登录后的第二次浏览器复核**（`:437-438` 的 `cookie_auth`）：改为**同一 context 内**导航一次发布页，跑 D 的 `probe_session()`；通过 → 原子写回 → `success`；未通过 → **1**（不判 10，避免扫码循环）。
- `xiaohongshu_cookie_gen`（`:404-471`）的二维码抓取、3s × 100 轮询、超时不动。

**F. cookie 写回**

| 出口 | 写回 |
| --- | --- |
| 发布成功（0）/ `--no-publish` 走完 | ✅（现状写点 `:1227`/`:1410`） |
| 登录成功（同 context 复核通过） | ✅（现状 `:437`，复核 `:438` 改为同 context） |
| `check` = `valid`（本地） | ✅ **新增** |
| `1` / `9` / `10` | ❌ |
| 托管模式 | ❌（不读不写；`account_file=None`，见 `sau_commands/xiaohongshu.py:301`/`:332`） |

- 按**结果码**判定，不按"有没有抛异常"；写盘 = `*.tmp` + `os.replace`。
- **身份回读不做**（不读 `__INITIAL_STATE__`，不输出 nickname/userId）。将来若做，首选 cookie `x-user-id-creator.xiaohongshu.com`，范式复用大鱼号 `identity.json`。

**失败语义** `LoginRequiredError(reason, publish_attempted)` → **10**；预检失败（本地快路）→ **10**；探测失败 → **1**；登录后复核未就绪 → **1**。

**测试点** 前置三态（有/缺/过期）；`check` 四出口；写回矩阵（0/9/10 各一条）；登录复核同 context（断言只 `new_page` 一次）；`classify_blocked` 四种 path + `?redirectPath=` 不误判。

**验收** 真机注入①（移走账号文件）与②（改坏 cookie 值），见 §9.3。

**顺序与依赖** U10 的分类器与文案就位后落地；`check` 可独立先合。依据 [12](./issues/12-session-and-identity.md)、[07](./issues/07-risk-page-classification.md)。

---

### U10 本地/托管失败语义统一

**现状** `[代码明确]` 8 处 `if multilogin:` 门（`:1104`/`:1173`/`:1192`/`:1196`/`:1312`/`:1356`/`:1375`/`:1379`，各占 2 行）；`_LOGIN_URL_MARKERS`（`:101`）子串匹配；文案写死 "Multilogin"（`:113-117`）；`_raise_if_login_required(..., multilogin=True)`（`:104-117`）实为"任何托管模式"；参数声明 `multilogin: bool = False`（`:1096`/`:1304`），调用点传 `session.managed`（`:1236`/`:1419`）。

**目标** 同一判定器、同一句文案来源、同一码，两种模式没有分叉。

**判定标准**

1. 判定器 = U9 的 `classify_blocked`；删除 `_LOGIN_URL_MARKERS` 与 `_raise_if_login_required`。
2. 参数：`upload_video_content` / `upload_note_content` 的 `*, multilogin: bool = False` → `*, mode: str`（`"local"|"multilogin"|"adspower"`）；调用点传 `session.mode`。
3. `utils/browser_session.py`：`_provider_label` → 公开 `provider_label(mode)`，`__all__` 补一项。
4. 文案在 **raise 点**拼（不做模板体系、不改 `sau_cli.py`）：

| 场景 | 文案 |
| --- | --- |
| 本地 · login | `小红书登录态无效：请运行 sau xiaohongshu login --account <账号名> 重新扫码后重试。` |
| 托管 · login | `小红书登录态无效：请在 {App} 中登录该 Profile 后重试。` |
| 本地 · verification | `小红书要求人机验证：请在浏览器中完成验证后重试。` |
| 托管 · verification | `小红书要求人机验证：请在 {App} 中完成该 Profile 的验证后重试。` |
| 任一 · `publish_attempted=True` | 上句后追加 `发布可能已发出：重跑前请先确认该笔记是否存在。` |

- `{App}` 取 `provider_label(mode)`；**不带 `profile_id`**；本地句只给 `<账号名>` 占位符（不解析文件名）。
- `reason` / `publish_attempted` 字段保留（供测试与日志断言）。

**删除清单**：`_XHS_PUBLISH_FAILURE_KEYWORDS`（`:54-62`）、`XhsPublishRejectedError`（`:67-68`）及两处 `except`（`:1191-1194`/`:1374-1377`）、`_find_publish_failure`（`:656-687`）、`XHS_PUBLISH_SUCCESS_URL_PATTERN`（`:32`，死常量）、`_LOGIN_URL_MARKERS`（`:101`）、`_raise_if_login_required`（`:104-117`）、`handle_upload_error`（`:1033-1035`）、`check_original_declaration`（`:980-982`，无调用点）。

**失败语义** 见 §4 退出码契约表（单一权威）。

**测试点** 本地模式**也能判出登录页**（最核心回归）；四文案 × 两模式 + `AdsPower` 出现且 `Multilogin` 不出现；`classify_blocked` 四种 path；`publish_attempted` 派发前 False / 派发后 True。

**验收** 离线全覆盖；托管侧若真机账号缺失则记"未验证（仅离线断言）"。

**顺序与依赖** 与 U9 同批；`provider_label` 是 U11 共享层的一项。依据 [13](./issues/13-failure-semantics-parity.md)、[07](./issues/07-risk-page-classification.md)。

---

### U11 共享层边界与迁移顺序

**现状** `[代码明确]` 判定与行为散落在各平台 uploader；`multilogin` 布尔与写死文案在 15 个平台重复；`classify_blocked` 尚不存在；`PublishTimeoutBudget` 已有但仅 TikTok 使用。

**目标** 定清"抽什么、放哪、怎么迁"，为后续逐平台迁移提供可执行顺序。**本规格只定边界与顺序，不在本 effort 实施迁移。**

**判定标准**

**A. 抽四块 + 一个小件**

| 模块 | 内容 | 平台知识 |
| --- | --- | --- |
| `utils/humanize.py` | U5 全部 | **零** |
| `utils/dom.py` | 四档 + `resolve`/`wait_resolved` + 覆盖层清障 + 两个 Error | **零**（覆盖层是数据） |
| `utils/controls.py` | `read_switch_state(locator) -> bool \| None`（`aria-checked` → `is_checked()` → `None`） | **零** |
| `utils/blocked.py` | `BlockedKind`、`BlockedRules`、`classify(page, rules)` | **零**（规则是数据） |
| `utils/browser_session.py` | `provider_label(mode)` 公开 | 模式枚举 |

**不抽**：上传完成循环（09 的信号只有小红书取证）、日期/定时回读、声明/封面弹窗、本地会话快路与 cookie 身份键、预算（`PublishTimeoutBudget` / `publish_gate` 留 `uploader/`）。

**B. 依赖方向** `utils/*` 只依赖 patchright + stdlib + `utils/errors.py`；**不得** import `uploader.*` / `sau_commands.*` / 平台常量。行为层不 import、不读 deadline、不自己计时。

**C. 迁移顺序**

| 步 | 平台 | 前置 | 风险注记 |
| --- | --- | --- | --- |
| 0 | 共享层落库 + 测试夹具 | 本规格 | 小红书先接线验证接口 |
| 1 | **小红书** | — | 本规格主体 |
| 2 | **TikTok** | 补 `--no-publish`；对齐预算 | 3627 行；先 `HUMANIZE=0` 对照 |
| 3 | **Instagram** | 补 `--no-publish`；先对齐 controls | 有并行改动，需 rebase 后重跑 |
| 4 | 抖音 | — | 声明/定时环节多 |
| 5 | 快手 | — | — |
| 6 | 视频号 | — | — |
| 7 | YouTube | — | 英文界面不影响（只用结构选择器） |
| 8 | Meta 其余（facebook / facebook_page） | 步 3 结论 | 与 IG 共享 `meta_uploader` |
| 9 | 支付宝 / 百家号 / 微博 / 虎扑 | — | 长尾，批量提交 |
| 10 | 大鱼 / 知乎 / 雪球（文章流） | **已解阻**（25） | 标题逐字（≤100 字 ≈14s），正文保持现有 HTML 粘贴 |

- **每步只改一个平台**（灰度粒度 = 提交/发布）；只有全局 `HUMANIZE=0` 开关，**不设平台级开关**。
- **已取证的登录/风控规则不得被空规则替换**：无真机证据前保留现有登录判定并映射到 `LoginRequiredError`，不允许 `classify` 恒返回 `None` 把失效降级成 1。
- 不迁也不删：`bilibili`（biliup 子进程）、`uploader/xhs_uploader/`（CLI 不可达）、`uploader/tk_uploader/main.py`（若 CLI 走 `main_chrome`）。

**D. 静态断言豁免** `fill(` = 0 **豁免** YouTube `_fill_editable`（逐字输入 `#` 会触发话题补全并卡死流程）；豁免形式 = 唯一 helper + 注释写明原因。文章正文的剪贴板粘贴不与长配文 `insert_text` 合并。

**E. 每步验收四件套**

1. 离线单测（humanize / dom / controls / blocked 的契约断言）。
2. 静态断言：该平台目录 `fill(` / `el.click()` / `force=True` = 0；裸 `timeout=` = 0；`count()` 只作集合基数。
3. 真机 dry-run（**不真实发布**）：`--no-publish` 跑到 ARM 就绪 → 0，留命中日志与截图（显式 `--debug`）。**强制**：小红书 / TikTok / Instagram；其余可选。
4. `HUMANIZE=0` 对照：同输入再跑 → 0，记录耗时差。

**失败语义** 共享层不定义退出码；错误类型仍映射 1。

**测试点** 四模块契约；同 seed 可复现；`type_horizon_chars` 只出现在 `utils/humanize.py`。

**验收** 小红书全绿 + 三个强制平台 dry-run（迁移在后续 effort）。

**顺序与依赖** 步 0 依赖 U3/U5/U10 的接口定稿。依据 [15](./issues/15-shared-layer-boundary.md)、[25](./issues/25-long-text-budget.md)。

---

### U12 测试与验收策略

**现状** `tests/test_xiaohongshu_uploader.py`（725 行）单文件含 `FakeLocator`（`:13-51`）/`RecordingKeyboard`（`:54-62`）/`RecordingLocator`（`:65-77`）/`RecordingPage`（`:80-91`），21 条用例；3 条拒绝词用例（`:322-365`/`:366-401`/`:402-440`）、1 条 `cookie_auth` 用例（`:181-192`）、`test_mlx_xhs_kuaishou.py` 的 4 条 `LoginProbeTests`（`:682-724`，helper 在 `:664-672`）与 `/captcha/verify` 用例将被删除；托管真机可能无账号。

**目标** 前提可只靠真机、机制必须离线；机制消失即删用例；退出码表做成可执行镜像。

**判定标准**

**A. 三条原则**

1. **前提 vs 机制**：选择器存在、真实文案、风控页出现 = 前提（可只靠取证/真机）；判定、异常、字段、退出码、日志 = 机制（必须离线单测）。
2. **机制消失即删**：删掉的行为其用例直接删，不改写成纪念性断言。
3. **托管真机可选**：缺测时标"未验证（仅离线断言）"，不阻塞。

**B. 夹具**

- `tests/fakes_xhs_dom.py`（新，抽出并扩展）：`FakeLocator`（`count`/`first`/`nth`/`get_attribute`/`is_visible`/计算样式/子节点/`/text`；**未 scripted 选择器抛错**）、`RecordingPage`（可写 `url`、`main_frame.url`、`goto`、`evaluate`（含 `elementFromPoint`）、`mouse.*`、`keyboard.*`、`screenshot`、`wait_for_*` 记录 timeout）、`RecordingLocator.click` 计数。
- `tests/fakes_clock.py`（新）：`FakeClock`（`monotonic`/`advance`/`sleep`）+ context manager 替换被测模块的 `time.monotonic` 与模块级 `asyncio` 名。**生产代码不新增 clock/sleep 参数。**

**C. 测试矩阵** — 逐决议正/负断言见 [16](./issues/16-test-strategy.md) §2；必须覆盖：ARM 四条件与单次点击、OBSERVE URL 判定与零文本扫描、四档判定与 `probe-failed` 分档、C1–C4 × login/verification × 点击前后、话题恰好 +1、逐瓦片完成态、UTF-16 标题、定时三检查点、会话前置三态与 `check` 四出口、`provider_label` 两值、默认有头、忽略参数 WARNING。

**D. 退出码契约镜像** `tests/test_xhs_exit_contract.py`（新）：表驱动，一行一场景（异常/字段 → 码 → stderr 断言），覆盖集合 `{0,1,2,9,10,11,130}` + meta 断言防漏测；**不解析** `docs/CLI.md`。

**E. 既有用例处置** 删 4 条（拒绝词 ×3、`cookie_auth` ×1）+ `test_mlx_xhs_kuaishou.py` 的 xhs 登录探针与 `/captcha/verify`；改 3 条（OBSERVE 判据、`fill_meta` 键盘动作、ARM 截止）+ `test_adspower_cli.py:354`（默认 headless）；`kuaishou` 与其余平台、`test_publish_timeout.py` **零改动**作为回归基线。

**F. 组织与运行** 按决议分段（`Decision03SubmitTests` … `Decision13ParityTests`，`test_03_*`）；`python -m unittest ...`；不新增 runner。

**失败语义** 不适用（测试层）。

**测试点** 每单元的"测试点"段落即本单元的输入清单；新增/改写的每个用例必须能指出它锚定哪条判定标准（一行一断言）。

**验收** 全量 `python -m unittest discover -s tests -t .` 绿 + §9.3 真机清单。

**顺序与依赖** 夹具与断言在步 0 定稿；随各单元落地同步写。

---

### U13 运行参数与可观测性

**现状** `[代码明确]` `arguments.py:90` `set_defaults(headless=True)`；`conf.DEBUG_MODE=True`（`conf.py:7`）+ uploader 默认值三处（`:480`/`:996`/`:1261`）+ CLI `--debug` 默认 False 三处口径不一（CLI 路径从未读 `DEBUG_MODE`）；托管分支静默丢弃 `launch_kwargs`/`context_kwargs`/`init_script`/`context_setup`（`utils/browser_session.py:139-144`，本地分支 `:126-137`）；本地分支零启动日志；`--account` 在托管下只作 label。

**目标** 默认值一条规则、被忽略的参数可观测、启动事实可证明。

**判定标准**

1. **`headless` 默认 = 有头**：`set_defaults(headless=True)` → `False`；`--headless` 显式无头；`--headed` 保留（等价默认，兼容调度侧）。**CLI 参数层**不读 `conf.LOCAL_CHROME_HEADLESS`（现状如此，非回归）；uploader 直接调用路径的默认值仍取该配置（`:386`/`:409`/`:481`/`:997`/`:1262`），**本轮不动**，只在 `docs/install.md` 标注其作用域。
2. **`debug` 默认 = 关，唯一来源 = CLI**：删除 `conf.DEBUG_MODE`（`conf.py:7`、`conf.example.py:7`、`docs/install.md:81`、`main.py:17` 的 import 与 `:480`/`:996`/`:1261` 三处默认值 → `False`，其余 uploader 的同类 import/默认值一并删）。**不默认开**（失败截图落在 0.5s 重试循环内且无去重，见 §8.2）。
3. **托管忽略参数 = 每 run 一条 WARNING，不 raise**：只统计非空（`init_script=False`/`{}`/`None` 不计）；文案固定中文、**只报键名**：
   `托管模式忽略本地浏览器参数：launch_kwargs, context_kwargs, init_script；Profile 负责指纹与界面语言，语言/UA/时区请在 Profile 内设置`
4. **`--account` 托管下无意义**：不读不校验不参与标签；`resolve_account_label` 托管分支直接返回 `profile_id`；传了进 ignored 列表。例外不变：`login`/`verify`/`delete` 仍必须 `--account`。
5. **启动日志两种模式各一条**：
   `browser session ready: mode=local|multilogin|adspower, headless=headed|headless, identity=account_file:<path>|profile:<id>, ignored=<keys|->`
   托管保留 `folder_id`/`port`/`endpoint` 附加字段。
6. **托管 `login` 维持拒绝**（`reject_managed_login`，1），文案归 U10。

**失败语义** 参数错误 → 2；托管单凭证冲突/不支持平台/Profile 或 CDP 失败 → 1；429 → 11（码表不变）。

**测试点** 三种参数组合的 `headless` 值；`grep DEBUG_MODE` 只剩 CHANGELOG；托管非空参数恰好一条 warning 且只含键名（本地零条）；启动日志四字段两模式各一条；`test_adspower_cli.py`/`test_browser_session.py` 等回归。

**验收** 16 平台各跑一次 `check` 冒烟（本地 + 托管，托管缺账号则本地）。

**顺序与依赖** **可独立先合**，拆两个改动：①参数契约（行为变更）②session 可观测性（纯增量）。依据 [14](./issues/14-managed-defaults.md)。

---

### U14 发布节奏与调用方契约

**现状** `[代码明确]` 无任何节流/冷却/熔断代码；只有 `--not-before` 的本地等待。

**目标** 明确"CLI 保证什么、调用方负责什么"，并补齐 `10` 的点击前后歧义。

**判定标准**

1. **节流完全不属于 CLI**：不建状态文件、不做预检、不加参数、**不设任何默认数字**。
2. **调用方契约（规范）**：

| 信号 | 含义 | App 动作 |
| --- | --- | --- |
| `0` | 已发布；或 `--no-publish` 已准备完成 | 计数 +1、记录时刻 |
| `1` | 确定未发布 | 可无条件重跑（冷却另议） |
| `9` | 已派发、未确认成功，**帖子可能已存在** | **禁止自动重跑**；先核对 |
| `10` + stderr `publish_attempted=true` | 点击后才落登录/验证页，**帖子可能已存在** | 先核对，再排人工登录 |
| `10`（无该行） | 点击前登录失效，**没有发布** | 排人工登录，登录后可直接重跑 |
| `11` | 桌面应用/Launcher 429 | 退避重试 |

3. **`publish_attempted` stderr 行**：仅当派发后才检出登录/验证页时，退出 `10` 额外向 stderr 打**单独一行** `publish_attempted=true`；固定 token、无本地化、无前缀、无时间戳；点击前 `10` **不打**该行。码表不动。
4. **`--not-before` 机制不动**，但**禁止**拿它做发布间隔/排程（等待发生在填表后、点击前，浏览器与托管 Profile 全程被占用）。
5. 「每天 50 篇」是上游作者个人经验、非平台规则，**不作依据**。

**失败语义** 沿用 §4 表；不新增码、不新增状态文件。

**测试点** 点击前 `10` stderr 不含该行；点击后 `10` 含且仅一行；`9`/`0`/`1` 不含；`--not-before` 顺延后预算正确。

**验收** 离线断言（表驱动镜像包含该行）。

**顺序与依赖** 随 U9/U10 的异常字段一并落地；`publish_attempted` 行属共享层（16 平台同形）。依据 [18](./issues/18-publish-pacing.md)。

---

## 4. 退出码契约表（单一权威）

> 按**失败类型**切（调度侧实际能看到的分类），不按观测点。`docs/CLI.md:160-174` 是派生投影（只有码、没有 `reason`/`publish_attempted`），不得反向定义本表。

| 失败类型 | 本地 | 托管 | 码 | 异常 / 字段 | 重跑规则 |
| --- | --- | --- | --- | --- | --- |
| 发布成功（或 `--no-publish` 已准备完成） | 0 | 0 | **0** | return | — |
| 登录失效（未派发） | 10 | 10 | **10** | `LoginRequiredError(reason="login", publish_attempted=False)` | 修会话后**无条件**重跑 |
| 登录失效（已派发） | 10 | 10 | **10** | `reason="login"`, `publish_attempted=True` + stderr 行 | **先核对**笔记是否存在 |
| 要求人机验证（未/已派发） | 10 | 10 | **10** | `reason="verification"`, `publish_attempted=False/True` | 过验证后通常不必重扫码；已派发同样先核对 |
| 运行前预检失败（本地：文件缺失 / 无 `galaxy_creator_session_id` / 已过期） | 10 | — | **10** | `LoginRequiredError(reason="login", publish_attempted=False)` | 修会话后重跑；**不启浏览器** |
| `check`：确定未登录 / 分类命中 | 10 | 10 | **10** | `LoginRequiredError`（`reason` 走 stderr） | 人工登录 |
| `check`：结构异常 / 导航 5xx / 超时 / 探测失败 | 1 | 1 | **1** | `RuntimeError` | 排查后重跑（故障 ≠ 失效） |
| ARM 就绪窗用尽 / 预算耗尽（**确定**未派发） | 1 | 1 | **1** | `budget.pre_click_error()` | 可重跑 |
| 上传失败（缺图 / 视频 `div.fail` / input 多义） | 1 | 1 | **1** | `RuntimeError`（`missing`/`unusable`） | 可重跑 |
| 话题插错 / 多插（点击前） | 1 | 1 | **1** | `reason=topic-mismatch` / `topic-multi-insert` | 可重跑 |
| 元数据失败（标题超限 / 正文越限 / 原创 true 失败 / 定时回读不一致） | 1 | 1 | **1** | `ValueError` / `ElementUnusableError` | 可重跑 |
| FIRE 派发后异常 | 9 | 9 | **9** | `PublishResultUnknownError` | **禁止**自动重跑 |
| OBSERVE 15s 未离开 `/publish/publish` | 9 | 9 | **9** | `PublishResultUnknownError` | 先核对再重跑 |
| 用法错误（缺 `--account` 等） | 2 | 2 | **2** | `UsageError` | 修正参数 |
| 429（Launcher / Local API） | — | 11 | **11** | `RateLimitedError` | 退避重试 |
| 双凭证冲突 / 不支持平台 / Profile 或 CDP 失败 | 1 | 1 | **1** | `RuntimeError` | 处理后重跑 |
| `Ctrl-C` | 130 | 130 | **130** | `KeyboardInterrupt`（`main` 不捕获） | — |

**stderr 机器信号**：仅 `10` 且 `publish_attempted=True` 时打单独一行 `publish_attempted=true`。其余任何码都不打。

**合并规则**（07 §5，唯一答案）：页面状态分类命中**压过**同点的一切超时/异常分类；命中只会把 `1/9` 拉成 `10`，绝不把 `0` 抬成 `10`。

**检查点↔码的关系**（不占表列）：C1/C2/C3 命中 → 10（False）；C4 与 FIRE 异常分支 → 10（True）；未命中 → 按上表 1/9/0。

---

## 5. 实施顺序与依赖

> 粒度 = 可独立评审/合入的改动；顺序满足依赖，允许并行（同批内）。

| 批 | 内容 | 依赖 | 可独立合入 | 验证 |
| --- | --- | --- | --- | --- |
| S1 | **参数契约**（U13 ①②④） + **session 可观测性**（U13 ③⑤） | — | 是（拆两个改动） | 默认值单测 + 16 平台 `check` 冒烟 |
| S2 | **预算 clamp**（U1） | S1 无 | 是 | 静态断言 + 预算单测 |
| S3 | **判定原语 `utils/dom.py` + `utils/controls.py`**（U3） | S2（可选 budget 透传） | 是 | 四档/hit-test/静默门单测 |
| S4 | **选择器矩阵收敛**（U4）：删死锚点、`xhs-publish-btn`、`.publish-container`、封面新结构 | S3 | 是 | 过渡期常量断言 + 日志级别 |
| S5 | **提交语义 ARM/FIRE/OBSERVE**（U2）+ `--no-publish` 升级 | S2/S3（点击接口可先用 `locator.click`，S6 替换） | 是 | 单次点击计数、OBSERVE 判据、1/9/10 |
| S6 | **人类化交互 `utils/humanize.py`**（U5） | S3 | 是 | 字符分派/点击序列/1000 边界/`HUMANIZE=0` |
| S7 | **风控分类 + 模式一致性**（U9/U10）：`classify_blocked`、C1–C4、删 8 门、文案、`provider_label` | S4/S5 | 是（可与 S5 同批评审） | 本地也判出登录页；四文案 |
| S8 | **上传完成**（U6） | S3/S4/S5（复用 ARM 谓词） | 是 | 逐瓦片完成态、`div.fail`、60s/600s |
| S9 | **话题**（U7） | S3/S4 | 是 | 全等匹配、恰好 +1、降级/中止 |
| S10 | **元数据与定时回读**（U8） | S3/S6（逐字输入） | 是 | 标题口径、C1/C2/C3 |
| S11 | **会话与 `check`**（U9 A–F） | S7（分类器） | 是 | 前置三态、四出口、写回矩阵 |
| S12 | **测试收尾 + 文档回写**（U12 + §9） | 全部 | — | 全量 unittest 绿 + 真机清单 |

**硬前置（已补齐）**：TikTok / Instagram 的 `--no-publish`（同语义：跑到发布就绪点即停）已于 2026-11-12 补齐并通过真机干跑；U11 步 2/3 的迁移可以按计划开始。

**回滚粒度**：一批一提交；S1/S6/S7 是行为变更最集中的三处，出问题时优先回滚它们（其余批依赖它们的接口，回滚须同批回退）。

---

## 6. 决议索引（ticket ↔ 单元 ↔ 修订关系）

| 单元 | 主依据 | 被谁修订（以本规格为准） |
| --- | --- | --- |
| U1 预算 | 03 | — |
| U2 提交语义 | 03、04 | 04 改 OBSERVE（15s/URL/零文案）；07 改登录页判定（10 + `publish_attempted`）；18 补 stderr 行 |
| U3 判定原语 | 06、15 | 15 把 `dom.py` 直接落 `utils/` |
| U4 选择器矩阵 | 05、22 | 09 改第 4 行（逐张/file chooser）；22 改第 13 行（封面新结构）并删英文；26 改第 1 行（定时同元素）与第 8/9 行（simulator class） |
| U5 humanize | 10 | 25 改打字口径（1000 字分流） |
| U6 上传完成 | 09 | 24 升级为每瓦片完成态 + `div.fail` 即时失败 |
| U7 话题 | 08 | 23 把"1–2 个新增"收紧为"恰好 1 个" |
| U8 元数据/回读 | 11、27 | 26 换标题锚点并加 ≥350ms 等待；27 覆盖"定时无回读"两行 |
| U9 会话/check | 12、07 | 07 定 10 与分类器；12 定预检/check/写回 |
| U10 模式一致性 | 13、07 | 13 删 `multilogin` 参数本身（不只删门） |
| U11 共享层 | 15 | 25 解阻文章流并豁免 YouTube `fill` |
| U12 测试 | 16 | 07/18 各加一组断言；16 的 Q1–Q6 决议 |
| U13 参数 | 14 | 19 不改浏览器配置，只沿用 14 的 CLI 默认 |
| U14 节奏 | 18 | 04 的"主动节奏是唯一杠杆"更正为"杠杆在 CLI 之外" |

**已关闭但不再作为前提的票**：19（本轮不改本地浏览器配置）、20（不做自动对账）、21（同账号不并发是部署前提）。

---

## 7. 与上游的偏离记录（charter "禁止对齐下界"）

> 「上游这么做」不构成理由；下列每一项都是**我方更强**或**我方更安全**的偏离，实施时不得为了"对齐"退回去。

| 环节 | 上游 | 本规格 | 理由 |
| --- | --- | --- | --- |
| 发布就绪窗 | 固定 15s | `min(60s, 预算)` | 视频实测 ~12s 且抖动；`1` 可安全重跑 |
| 预算 | 无总预算概念 | 全部 clamp | 裸超时会超支 15 分钟 |
| 成功判据 | URL 不含 `/publish/publish` | 离开且**不在登录/验证页** | 上游会把登录/验证页当成功 |
| 观察窗 | 15s，超时返回无差别 error | `min(15s, 预算)` → exit 9 | 机器可区分"可能已发布" |
| 失败分档 | 无（return error） | 0/1/9/10 | 调度器需要可执行语义 |
| 文案扫描 | 发布链路不调用风控分类 | 不扫描，只判 URL | 无真机证据，且不改变结局 |
| 点击命中复核 | widget 路径无 `stillOn` | 坐标点击前必复核 | 点空会被记成 9 |
| 打字底层 | 逐 rune `insertText` | ASCII 真 key 事件 / 非 ASCII `insertText` | 提高真实性，同级成本 |
| 提交前停顿 | 发布链路不用 `BeforeSubmit` | FIRE 前采样一次 | 提交前停顿是防指纹锚点 |
| 定时回读 | 只点开关 + 固定 sleep，无回读 | C1/C2/C3 三处回读 | 日期被拒会静默回滚 → 按错误时间发布 |
| 越限判据 | `page.Has` 存在即失败 | 采纳 + 修正锚点与 ≥350ms 等待 | 上游锚点在现网已死 |
| 上传判据 | 一批/固定 sleep（历史）→ 逐张计数 | 逐张 + 每瓦片完成态 + 静默复检 | 上游有静默丢图事故；其"预览数=N 即完成"有假完成竞态 |
| 文件 input 兜底 | `accept` 匹配不上取 `inputs[0]` | 禁止 `.first`，走"+"瓦片 file chooser | 上游 issue #868 自承会误取视频 input |
| 视频失败面 | 只能等窗口耗尽 | `div.fail` 即时中止 | 等下去无收益 |
| 遮挡兜底 | `elem.Remove()` / 随机点空白 | 已知覆盖层 + Esc，永不摘节点 | 改 DOM 是可被页面观测的非人类行为 |
| 登录判据 | `/website-login[/captcha]` 唯一 | `/login` 为主 + 兼容常量 + 可见 login-box | 实机只观察到 `/login` |
| 话题回读 | 整页严格 `previous+1` | 编辑区内"恰好 +1"（多重集合差） | 整页每次 +2（预览镜像），上游判据必挂 |
| 话题复位 | `ArrowDown×20 + Enter×2` | 不复位 | 220 事件/10 标签；真机连续插入无需复位 |
| 回读厚度 | 薄口径（原创点前一次 + `Has`） | 采纳，但定时三项加回读（27） | 缺口真实存在 |
| 会话预检 | `ensureCreatorSession`（读 cookie 等 15s） | 发布页一次观测 | 我们本来就要导航发布页 |
| 身份回读 | 读 `__INITIAL_STATE__` | 不做（将来首选 cookie 键） | 不降风险、不解决已观察故障 |
| 节流 | README 建议"每天 50 篇" | 不做，交调用方 | 作者个人经验，非平台规则 |
| 结果对账 | 不做（只有两个 creator URL） | 不做 | ① 更像脚本；不是"对齐" |
| 托管 login | 不支持 | 维持拒绝 | 能力补齐，不服务 ①② |

---

## 8. 本轮不做

### 8.1 Out of scope（不做，且不再评估）

1. **节流/冷却/熔断的实现与调参**：整体归调用方 App；本规格只提供调用方契约（U14）。
2. **发布结果自动对账**：`exit 9` 之后不回「笔记管理」核对、不改判 `9→0/1`；收尾维持 `9` + 人工核对。重开条件：无（除非整个 destination 重画）。
3. **本地模式浏览器卫生改造**：persistent `user_data_dir`、真 Chrome `channel`、删 UA 半修、删 `stealth.min.js` 全部维持现状。**本轮不消解"每次全新指纹、无历史无缓存"这个最弱环，也不提供"现状足够安全"的断言**；无前后取证。重开条件：出现"本地模式被拒/封显著高于托管"的实机证据，或托管不可用成为常态。
4. **托管下的登录能力补齐**（从 Profile 抓二维码返回）：`login` 维持拒绝。
5. **代理**（`XHS_PROXY` 一类）：托管由 Profile 承担出口；本地加代理属独立部署议题。
6. **多账号并发隔离与设备画像轮换**：托管由 Profile 承担；本地多号隔离留待独立议题。
7. **身份回读**（nickname/userId）：不做；将来若做，首选 cookie `x-user-id-creator.xiaohongshu.com`，范式复用大鱼号 `identity.json`。
8. **可见范围、商品绑定、URL 图片下载**：能力补齐，不服务 ①②。
9. `sau_backend.py` / Vue 前端 / 调度 App 本身；上游 Go 移植；`headless_browser` 复刻；浏览器构建分发。

### 8.2 待定项（雾：可能成为后续票，本轮不实施）

1. **素材校验**：图片数量/尺寸/格式、视频时长/大小——两边都没有，是否需要作为可靠性的一部分。
2. **视频封面流程可信信号化**：现为增强步骤，失败即跳过；是否值得补回读。
3. **失败截图去重**：小红书失败截图落在 0.5s 重试循环内且无去重（`main.py:704-708`/`:1199-1200`/`:1382-1383`）；且**现状 `page.screenshot()` 未传 `path=`，字节被丢弃、实际不落盘** —— "默认开"要连同"落盘 + 去重 + 命名"一起设计，不是改一个默认值。这是 `debug` 默认关的原因之一。
4. **托管 Profile 画像契约**：界面语言 / UA / 时区 / 视口由 Profile 承担，哪几项是硬要求、启动时能否校验。

### 8.3 已知缺口、残留风险与需真机验证

| # | 项 | 状态 | 影响 |
| --- | --- | --- | --- |
| 1 | `/website-login*` 与真实验证页 path 未观察到 | 需真机 | 该分支可能是死代码；非跳转式验证码弹层不识别（落在 1/9） |
| 2 | 正常发布页上 `login-box` 的 count/可见性未单验 | 需真机 | 可能产生假 10（真机验收必须确认一次） |
| 3 | 定时回读只证客户端接受，不证服务端受理 | 残留风险 | 服务端另有规则时仍按 OBSERVE 判定；平台 2h/14d 边界未真机验证 |
| 4 | C3 时效是粗判 | 残留风险 | 只保证"请求值仍晚于本机现在"，不保证满足平台最小提前量 |
| 5 | `9` 与"实际是限流"不可区分 | 残留风险 | 故 `9` 一律先核对、不自动重跑 |
| 6 | 观察窗 15s 对"慢成功"是否够用 | 需真机 | 偏短会把"慢但对"推进 9（安全但噪声大） |
| 7 | 定时发布成功后是否跳转 `publish/success` | 需真机 | 不跳转则每次定时发布都会等到预算/窗口耗尽 → 9 |
| 8 | `--no-publish` 升级到 ARM 是前置改动 | 前置 | 不实施则真机验收退化为"填表完成" |
| 9 | humanize 的"像人"效果 | 仅推断 | **不设断言**；任何"降低封禁率"的说法都不成立 |
| 10 | 点击后落登录页的真实频率 | 需真机 | 影响 `publish_attempted` 行的实际价值，但契约无论如何成立 |
| 11 | 首张之后的图片上传：`.entry` → file chooser 已实机确认；20MB 单张 25.5s | 实机 | 60s 保留；更慢时段仍未覆盖 |
| 12 | 登录后同 context 复核若页面未就绪 → 1 | 设计 | 运维需知道"扫码成功也可能 exit 1" |
| 13 | 本地只写成功 → 长期失败时多一次重登 | 设计（可恢复） | 不制造假 10 |
| 14 | 托管真机若跳过 | 可选项 | U10/U13 的托管侧只剩离线断言 |
| 15 | `type_horizon_chars=1000` 对部分编辑器可能被截断 | 需真机 | 截断即异常 → 点击前 1；重开条件见 25 |

---

## 9. 回写与验收

### 9.1 `GLOSSARY.md` 必须新增/修订

| 条目 | 动作 |
| --- | --- |
| `Login required（登录失效）` | 改成"本地与托管**同码 10**；探测失败（网络/5xx/结构异常）是 1；点击后检出带 `publish_attempted=true`" |
| **人机验证（verification）** | 新增：`reason="verification"`，与登录同码 10，区别只在补救动作 |
| **publish_attempted** | 新增：本次运行是否已越过不可回退点（派发前即置位）；`True` 只证明"可能已提交" |
| **ARM / FIRE / OBSERVE** | 新增（发布提交三段） |
| **元素角色（attached/visible/interactive/editable）** | 新增（若认为属于实现细节，可只列 `interactive`） |

### 9.2 `docs/CLI.md` 回写清单（派生投影）

| 位置 | 改动 |
| --- | --- |
| `:88` | 定时"拒绝或立即发布"→ "CLI 在 FIRE 前复核，不一致 `exit 1`" |
| `:140` | `--account` 托管下"忽略；身份由 `--profile-id` 决定" |
| `:145-147` | 三列默认值 headless True → **False（有头）** |
| `:160-174` | 退出码表：与 §4 对齐（含 `publish_attempted` 行说明），声明母本在 spec |
| `:69-96` / `:98-114` | `--not-before` 与 15 分钟预算语义保持；补"禁止用 `--not-before` 做节流" |
| `:195-202` | 保留"同 Profile 不并发"；补 `1/9/10/11` 调用方动作（U14 表） |
| `:251,258` | `check --headed` 示例与"直接映射"说明同步默认值 |
| `:432-511` | 小红书子命令段：`--no-publish` 措辞、声明/定时说明、超时与立即拒绝段落按本规格改写 |
| `:465/498/511` | `--no-publish` 措辞 → "跑到 ARM 就绪" |
| `:505-510` | 删"限流保留重试"条款 |
| `:634` | 平台字符上限事实修正（TikTok 4000；2200 是 Instagram） |
| `:838-850` | "都不传就 headless=True" → False |
| `skills/xiaohongshu-upload/references/cli-contract.md:147` | 同 `:505-510` |

### 9.3 真机验收清单（本地强制；托管可选）

前置：`--no-publish` 已升级到 ARM 就绪（S5）；显式 `--debug`（默认关）；本地 cookie 有效。

> 2026-11-12 用本地账号 `180` 实跑（macOS + patchright headed）。结论写入下表「实际结果」；
> 这次实跑同时暴露并修复了 5 个离线测试覆盖不到的真机问题，见本节末尾。

| # | 步骤 | 期望 | 实际结果 |
| --- | --- | --- | --- |
| 1 | 视频正路：`sau xiaohongshu upload-video --account <a> --file <mp4> --title T --no-publish` | 0；日志含 ARM 就绪行；命中日志 `xhs-publish-btn` | ✅ 0；`视频已经传完啦` 后 `ARM 就绪，--no-publish 停在发布按钮前`；命中 `div.upload-content input.upload-input`（structure） |
| 2 | 图文正路：2 张图 `upload-note … --no-publish` | 0；第 2 张经"+"瓦片/file chooser；逐瓦片完成态 + 静默复检通过 | ✅ 0；第 1 张走上传入口、第 2 张命中 `.img-preview-area .entry`（structure）并 `expect_file_chooser`；两瓦片完成态通过 |
| 3 | 定时正路：`--schedule <2h–14d>` | 到 ARM 就绪 0；**不验证**定时是否生效（§8.3 #3） | ✅ 0；C1/C2/C3 全部通过（`2026-11-13 12:00`），到 ARM 就绪停止 |
| 4 | 注入①：移走账号文件（用不存在的账号名） | 10；**无** `browser session ready` 日志（证明未启浏览器） | ✅ 10；stderr 为本地登录句；**无** `browser session ready` |
| 5 | 注入②：改坏会话 cookie | 启浏览器 → C1 判 login → 10；stderr **不含** `publish_attempted=true` | ✅ 10；`invalid` + 本地登录句；无 `publish_attempted=true`。注意：只改 `galaxy_creator_session_id` **不会**失效（服务端仍认会话），需改 `customer-sso-sid` / `access-token-creator.xiaohongshu.com` / `galaxy.creator.beaker.session.id` 这组 |
| 6 | 注入③：假 mp4（文本改名 .mp4） | `div.fail` → 点击前 1；stderr 不含该行 | ✅ 1；`div.fail — 视频上传失败（div.fail）`，点击前中止 |
| 7 | 注入④（可选）：20MB PNG | 逐瓦片完成态正常；60s 不误杀 | 未执行（可选） |
| 8 | 真实发布（最小验收）：1 篇图文，不带 `--no-publish` | 0；URL 离开 `/publish/publish`；人工删除该笔记 | ✅ 0；`图文发布成功`，OBSERVE 确认离开 `/publish/publish`；测试笔记标题「SAU真实发布验收」（2026-11-12 11:09），**待人工删除** |
| 9 | 托管（可选）：有账号时重复 1/2 | 同本地；断言一条 `browser session ready` | 未执行（本机无 MLX/AdsPower 凭证） |

**2026-11-12 真机复测发现并已修复**

1. `probe_session` 只等 3s 做单次快照：发布页上传入口在 `domcontentloaded` 后约 5s 才挂载 → 误判「页面结构异常」。改为 15s 有界轮询（每轮先分类，命中即 10）。
2. 坐标点击前未滚动：正文编辑区/发布按钮常在首屏下方，`elementFromPoint` 返回 `null` → `covered-by:unknown`。新增 `utils/dom.ensure_in_viewport`，`Humanizer.click` 与 ARM 谓词先滚入视口（对照上游：上游也是 `ScrollIntoView` + 200ms 再 `humanize.ClickAt`）。
3. 文本输入用坐标点击会被底部固定 `xhs-publish-btn` 遮住：按上游做法改为 `focus()`（仍逐字人类化输入），按钮/开关保留坐标点击。
   封面入口 `.cover-edit-entry` 只有悬停首帧预览后才渲染；弹窗内的图片 input 直接 `set_input_files`，不点「上传」tab（点 tab 会拉起系统文件选择器并留在屏幕上）。
4. `.video-container-loading-text` 在正路显示「视频上传中」，不是失败信号；失败态同时有 `div.fail`。因此该节点不再作信号（对照上游：上游只等发布按钮，10 分钟；我们的 `div.fail` 即时中止是加强）。
5. 定时时间输入框自带默认值（now+~1h）：`focus` 后直接键入会追加成两段日期。改为 `ControlOrMeta+A` 全选后逐字替换，仍只 `blur()`（C2/C3 通过）。

### 9.3.1 三平台 `--no-publish` 真机回归（2026-11-12）

本地 headed + 真实 cookie，全部只跑到“就绪点”即停，未点击发布。

| 平台 | 用例 | 选项 | 结果 |
| --- | --- | --- | --- |
| 小红书 | 图文 2 张 | 原创 + AI 声明 + 话题 | 0 |
| 小红书 | 图文 1 张 | 自主拍摄（地点+日期）/ 来源转载 | 0（二级声明菜单已收窄到 `div.d-popover.d-dropdown .d-option`） |
| 小红书 | 视频 14s | 原创 + 虚构演绎 + 话题 | 0 |
| 小红书 | 视频 3.5s | 原创 | 1（平台禁用原创开关，属视频时长/资格限制；换成 14s 后 0） |
| 小红书 | 视频 + `--thumbnail` | 封面 | ✅ 0：先悬停首帧预览 → `.cover-edit-entry` 才渲染 → 弹窗内「上传」→ 选图 → 「完成」，日志 `封面已经设置完成` |
| 小红书 | 定时 | `--schedule` | 0（C1/C2/C3 通过） |
| TikTok | 视频 14s | `--privacy friends` + `--no-comments` + `--aigc` | 0，发布按钮就绪 |
| TikTok | 图文 2/3 张 | `--privacy friends` + 选项 | 0 |
| TikTok | `--privacy public` | — | 1：该账号可见范围菜单只有 `Followers / Friends / Only you`，无 `Everyone/Public`；严格失败正确 |
| Instagram | Reel 14s | `--no-comments` + `--ai-generated` | 0，Share 就绪 |
| Instagram | 轮播 2/3 张 | `--alt-text` ×N + `--no-comments` + `--ai-generated` | 0，选项回读一致 |

真机修正：小红书二级声明菜单多义（已收窄）、PK 封面引导遮挡（已清障）、封面入口需先悬停预览（已加 `Humanizer.hover` 并接线）；TikTok / Instagram 的 `--no-publish` 为新实现（就绪窗口 60s 或剩余预算，超时退出 1）。

**明确不做**的注入：断网/恢复、改 URL/改选择器、真实发布后杀浏览器、真实验证码页面。

### 9.4 离线验收命令

```bash
python -m unittest tests.test_xiaohongshu_uploader tests.test_xhs_exit_contract \
  tests.test_mlx_xhs_kuaishou tests.test_publish_timeout -v
python -m unittest discover -s tests -t .
```

验收证据：命令行尾部日志 + `--debug` 截图，结论回写本文件 §9.3 的"实际结果"列（实施时追加，不新建目录）。

**2026-11-12 离线结果**（本机无真机环境，§9.3 全部未执行）：

```text
Ran 76 tests in 3.441s
OK

Ran 1447 tests in 111.967s
OK (skipped=2)
```

（集成分支基线 1451 条；删除 5 条机制消失用例 + 新增 1 条 `PENDING` 守卫，净减 4。）

---

## 10. 实施者检查清单（开工前 5 分钟）

1. `rg -n "multilogin" uploader/xiaohongshu_uploader/main.py` → 应有 8 处门 + 2 处签名（本规格要全部改掉）。
2. `rg -n "xhs-publish-btn|is-publish|submit-disabled" uploader/` → **应为 0 命中**（ARM 是新增语义，不是修 bug）。
3. `rg -n "clamp_(ms|seconds)" uploader/xiaohongshu_uploader/` → **应为 0 命中**（U1 是纯新增）。
4. `rg -n "DEBUG_MODE" --include="*.py" .` → 记录当前命中数（实施后应为 0）。
5. 确认 `--no-publish` 当前在 ARM **之前** return（`main.py:1160`/`:1343`）——U2 会改。
6. 打开 `tests/test_xiaohongshu_uploader.py` 的 `FakeLocator`/`RecordingPage`，确认 `mouse`/`insert_text`/`elementFromPoint` 是否已存在（U12 要扩）。

