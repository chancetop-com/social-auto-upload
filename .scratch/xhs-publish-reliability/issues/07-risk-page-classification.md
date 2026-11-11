# 07 — 风控页与登录失效的分级

Status: resolved
Type: grilling
Blocked by: 03
Assignee: wayfinder-session (opencode)

## Question

决定“被踢出登录 / 被要求验证”时抛什么、退出码是什么、两种模式是否一致。需要确认：

1. **判定依据**：按 path（`/website-login/captcha` vs `/website-login`）还是 path + DOM？是否采用等价于 CDP `Page.getFrameTree` 的主框架读取（不注入 JS）？是否会误把 `?redirectPath=/website-login/captcha` 的登录页判成验证页（上游用 `EscapedPath` 规避）。
2. **错误类型与退出码**：新增 `VerificationRequiredError`？复用 `LoginRequiredError` + exit 10？还是同一错误带 `reason` 字段？调度侧的可操作性差异是什么（人工扫码 vs 人工重登）。
3. **模式一致**：本地模式现在完全不判风控页，是否同步。
4. **检查点位置**：goto 后、填写中、点发布前、点发布后——分别做什么。现只有 goto 后与 `except` 分支。
5. **与 03 的交叉**：已点发布后被踢登录，是“结果未知（9）”还是“登录失效（10）”？必须给出唯一答案。

产出：状态机（检测点 × 命中 × 抛什么 × 退出码 × 是否可重试）+ 与 03 判定表的合并方式。

## Evidence from 02（真机取证）

- 无会话访问 `/publish/publish…` 与 `/`，落地均为 **`https://creator.xiaohongshu.com/login…`**（带 `redirectReason=401&lastUrl=…`），且 `div[class*='login-box']` = 1。
- **未观察到** `/website-login` 或 `/website-login/captcha`；本次未触发验证码，验证页 path 仍属「需真机验证」。
- 上游 `EscapedPath` 处理的是网页端 `/website-login` 场景，与 creator 后台 `/login` 不同源。

## Comments

- 来自 04 的约束（2026-11-11）：发布后的观察窗固定 15s，窗口内必须能判出登录/验证页；点击后命中 → `10`（文案带「发布可能已发出，重跑前先核对」），本地与托管一致。具体路径/DOM 判定仍归本票。

## Answer

**决议**：登录/验证判定收敛为**一个只读分类器** —— 两条信号（主框架 path 为主、可见 login-box 补强）、两种语义（`login` / `verification`）、**一个退出码 10**、四个检查点两端一致调用；与 03/04 的冲突用一条优先级解决：**页面状态分类命中压过同一点上的一切超时/异常分类**。

### 0. 状态机（可直接进 spec）

| 点 | 位置 | 分类命中 | 退出码 | `publish_attempted` | 可重跑 |
|---|---|---|---|---|---|
| C1 | `goto` 之后（现存） | `login` / `verification` | **10** | `False` | 修会话后**无条件**重跑 |
| C2 | 任何**可能超过 ~2s 的等待循环**每轮一次：视频预览轮询（2s）、图文标题等待（1s）、ARM 就绪轮询（1s） | 同上 | **10** | `False` | 同上 |
| C3 | `wait_until_allowed` 返回后、进 ARM 之前（**必查**，最后的安全退出点） | 同上 | **10** | `False` | 同上 |
| C4 | OBSERVE 轮询（500ms，与 04 同窗） | 同上 | **10** | `True` | **先核对笔记是否存在** |
| — | FIRE 异常分支（点击抛错） | 同上 | **10** | `True` | 同上 |
| — | 以上未命中 | — | 照 03/04 原表（1 / 9 / 0） | — | 照原表 |

`publish_attempted` 的语义 = **「本次运行是否已越过不可回退点」**（03 §3 的 `publish_clicked`），不是「发布成功」：它必须在派发**之前**置位，因此 `True` 只证明「可能已提交」，`False` 才证明「按钮从未被派发过」。

### 1. 判定器

`classify_blocked(page) -> None | "login" | "verification"`（同步、只读）

1. **读哪**：`urlsplit(page.main_frame.url).path`。`page.url` 是主框架 URL 的本地缓存属性，同步、无往返、**不注入 JS**。（上游用 CDP `Page.getFrameTree` 是因为 rod 的 `page.Info()` 不受 `page.Timeout` 约束、页面取消后还会多打一次 CDP —— 该理由在 Playwright 栈里不成立，不照搬。）
2. **只比 path**：不读 query、不 `unquote`。`urlsplit().path` 本就保留 `%2F` 编码，等价上游 `EscapedPath`。这从根上消灭 `?redirectPath=/website-login/captcha` 把登录页误判成验证页的路径。
3. **路径集与优先级**（验证 → 登录 → 未知子路径归登录，抄上游 `classifyBlockedPath`）：
   - `/website-login/captcha`（含子路径）→ `verification`
   - `/website-login`（裸路径与未知子路径）→ `login`
   - `/login`（含子路径）→ `login` ← 02 的实机判据，**主路径**
   - 其余 → `None`
   与 05 的关系：05 反对的是「照搬上游把 `/website-login` 当**唯一**判据」；本票保留 `/login` 为主、把 `/website-login*` 降为**兼容常量**（无我方证据，见 §7），且 05 已把验证页形态整体留给本票。
4. **DOM 补强**：`div[class*='login-box']` 存在，且按 **06 的 `visible` 档**（计算样式 + 祖先 opacity ≥ 0.1 + `aria-hidden`）判为可见 → `login`。裸 `is_visible()` 不看 opacity，会把「常驻但透明」的节点误判。**仅在 path 未命中时执行**（短路，命中 path 即不查 DOM）。
5. **不做**非跳转式验证码弹层识别：无任何真机证据；凭空造选择器违反 05「结构优先、无证据不入基线」。
6. **读失败**：`page.url` 没有失败模式；页面已关闭时也返回最后已知 URL。若将来出现无法判定，按「不拦截」处理（与上游「读不到返回 nil」一致），交原有超时路径收场。

### 2. 异常与退出码

`LoginRequiredError` 增两个**带默认值**的可选字段（现有 3 处 `raise` 不必全改）：

| 字段 | 取值 | 语义 |
|---|---|---|
| `reason` | `"login"` / `"verification"` | 决定 stderr 文案与人工动作 |
| `publish_attempted` | `False`（默认）/ `True` | 03 §5 原建议名照用，决定「可无条件重跑」还是「先核对」 |

- **两者都是 exit 10**；不新增错误类、不新增退出码。
- 为什么不分码：① 人工动作同类（都是「人到会话里把状态修好」），机器侧永远禁止自动重试；② 新码会外溢到 `docs/CLI.md`、`skills/…/cli-contract.md` 之外的 `sau_backend.py` / 调度 App 码表，而它们在 **Out of scope**；③ 验证与登录的真实差异在动作（过验证码后 cookie 通常未废，可能直接重跑；登录失效必须先扫码），用 `reason` 表达足够且可断言。

### 3. 模式一致

- **删的是「门」，不是参数**：运行中检查点两端**一律调用**（只读页面，零副作用）；`multilogin` / `mode` 只决定补救文案 —— 本地「`sau xiaohongshu login --account …` 重新扫码」，托管「到 Multilogin 里登录这个 Profile 后再跑」。
- 判据与模式无关。托管模式的 cookie 仍由 Profile 自己管理，本票**不读不写** `storage_state`；正因看不见 Profile 的 cookie，页面观测是托管模式**唯一**可知会话死亡的途径 —— 它比本地更依赖这个检查。
- `cookie_auth` 预检保持本地专属不动；其退出码语义（确定失效 vs 探测失败）**交 12**。

### 4. 实现约束

- 底层 `classify_blocked(page)` + 薄包装 `raise_if_blocked(page, *, mode, publish_attempted)`；OBSERVE 只要分类结果，不必抛。
- `publish_attempted` **必须从发布循环的 `publish_clicked` 变量现取**（`publish_attempted=publish_clicked`），**禁止按调用点硬编码**：C2 的 ARM 轮（`False`）与 C4（`True`）极易写反，写反的后果是把「可无条件重跑」错发给一个可能已经发出去的帖子。
- 检查点抛出的 `LoginRequiredError` **不得被既有 `except Exception` 吞掉**（视频预览轮询 `:1144`、图文标题等待 `:1331`、FIRE 异常分支都有宽 `except`）——移植时须显式放行。
- 成本：`page.url` 无往返；login-box 查询仅在 path 未命中时发生，约 1ms 量级。

### 5. 与 03/04 的合并（唯一答案）

| 原表条目 | 分类命中时的处置 |
|---|---|
| 03「ARM 窗口用尽 → 1」 | **改判 10**（`publish_attempted=False`） |
| 03「ARM 预算耗尽 → 1」 | 同上 |
| 03「FIRE 派发后异常 → 9」 | **改判 10**（`publish_attempted=True`） |
| 04「OBSERVE 落登录/验证页 → 10」 | 不变（本票只补 `reason`/`publish_attempted`） |
| 04「OBSERVE 未离开 / 15s 到点 → 9」 | **分类命中时改判 10**；未命中照旧 9 |
| 04「OBSERVE 离开且非登录/验证页 → 0」 | 不变；命中绝不产生 0 |

理由：(a) **不损失安全性** —— 9 与 10 都禁止自动重发，10 只多一条「先把会话修好」的指引，而会话已死时「去笔记管理核对」这个动作本身做不了；(b) **不制造假成功** —— 命中只会把 0 拉回 10；(c) **可测** —— 一条规则、一张表，16 不必为「异常先还是 URL 先」排顺序。

### 6. 对下游工单的约束

- **12**：预检探针失败现在走 `RuntimeError` → **1**；按本票「登录失效 = 10」，12 需区分「确定失效 → 10」与「探测失败（网络/5xx/结构异常）→ 1」，并优先复用 `classify_blocked`。`check` 是否改用轻量页、是否复用同一分类器仍归 12。
- **13**：规则已由本票统一，13 只核对两端**同码、同文案、同检查点**，不再各写一套。
- **16**：按 §0 做正负断言；检查点可用 `RecordingPage.url` + `FakeLocator` 全覆盖单测；真机缺口见 §8。
- **17**：把 §0/§1/§2/§5 并入规格；同时更新 `GLOSSARY.md` 的 `Login required` 条目（现文只写「托管模式下…10」），并补 `verification` 与 `publish_attempted` 两个词。
- **22**：本票判定**不依赖任何文案**（纯 path + 结构节点），22 无需为登录/验证取证；`/website-login*` 的真机形态见 §8。

### 7. 置信度

- **代码明确**：`_LOGIN_URL_MARKERS`（`main.py:101`）对**整个 URL** 做子串匹配（含 query）；8 处 `if multilogin:` 门（`:1104`/`:1174`/`:1193`/`:1197`/`:1313`/`:1357`/`:1376`/`:1380`）；`LoginRequiredError` 零字段；`sau_cli.py:84` → 10；本地预检 `cookie_auth` 失败抛 `RuntimeError`（`:509`）→ 1；`page.url` 为本地属性。
- **上游代码明确**：`/website-login[/captcha]` 常量；「验证优先、未知子路径归登录、只看 path、`EscapedPath`、读失败不拦截」；发布链路**从不调用**该分类器。
- **实机证据（02）**：登录落地为 `/login…` 前缀 + `login-box` 可见；`/website-login` 未观察到。
- **仅推断**：`/website-login*` 在 creator 后台是否会出现；login-box 是否可能常驻但透明。
- **用户决策（非事实）**：四检查点覆盖度、页面状态优先于超时/异常、复用 10 不分码。

### 8. 残差风险与需真机验证

1. `/website-login*` 可能永不出现 → 该分支是死代码（代价：一行常量 + 一个单测）。真机确认不存在后可由 17 删除。
2. 非跳转式验证码弹层不识别 → 该情形落在 9（点击后）或 1（点击前）；因无证据，宁可少判也不造选择器。
3. 正常发布页上 `login-box` 的 count 与可见性需真机确认一次：若它以 06 的 `visible` 档「可见」的形式常驻，会产生假 10。
4. 「点击后落登录页」是否伴随已提交的发布仍未证（03 §9 #4）；本票只保证语义**可区分**，不保证该情形频率。
5. `goto` 重定向未完成时读到中间 URL 的风险很低（`goto` 等导航完成、C1 在 settle 之后）；OBSERVE 是轮询，瞬时误差不改变结论。
