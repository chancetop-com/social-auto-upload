# 13 — 本地/托管失败语义统一

Status: resolved
Type: grilling
Blocked by: 03
Assignee: wayfinder-session (opencode)

## Question

同一种失败在两种模式下给出不同出口，调度侧无法写出统一规则。需要确认：

1. **登录失效退出码**：本地现为 `RuntimeError` → exit 1（`sau_commands/xiaohongshu.py:313-317`），托管为 `LoginRequiredError` → exit 10。统一为 10？
2. **错误文案**：`main.py:116-119` 硬编码“请在 Multilogin 应用中登录”，AdsPower 用户会被指错 App；是否改用 `login_required_error()` / `managed_app_label()`（`sau_commands/browser.py:273-284`）。
3. **参数命名**：`_raise_if_login_required(..., multilogin=True)` 实为“任何托管模式”（`session.managed`，含 AdsPower）。是否改名并补测试。
4. **判定标准漂移**：`check` 的宽松/严格差异是否由 12 统一（交叉引用，不重复决策）。
5. 是否需要一次性的“退出码契约表”作为 spec 的一部分（0/1/2/9/10/11 与各失败类型映射）。

产出：错误类型 × 模式 × 退出码 三维表 + 文案规范 + 需要改的调用点清单。

## Comments

- 来自 **07**（2026-11-11）：规则已统一，本票**只需核对、不要重决**——登录/验证一律 `LoginRequiredError` + **exit 10**，字段为 `reason`(`login`|`verification`) 与 `publish_attempted`；检查点 C1–C4 两端必调，`if multilogin:` 这道**门**删除、参数保留（仅决定补救文案）。本票问题 3「改名为 `multilogin` → 任意托管」仍成立且现在更有必要（参数不再控制是否检查，只控制文案来源，需与 `managed_app_label()` 对齐，否则 AdsPower 用户会被指到 Multilogin）。本票问题 2 的硬编码文案（`main.py:116-119`）随 07 的 `reason` 一起改写。

## Answer

**决议**：运行中的失败语义本来就已经统一（07/03/04 定死），本票的真正产出是**同一套信号在两种模式下共用一个判定器、一句文案、一个参数来源**：判据用 07 的 `classify_blocked(page)`，文案在 **raise 点拼**（不做模板体系、不改 `sau_cli.py`），运行模式从 **`session.mode`** 取（不是布尔），退出码一律 10。运行前的预检/`check` 归 **12**（已于同会话期内关闭，直接引用，不重决）。

### 0. 退出码契约表（spec 的单一权威，按失败类型切）

| 失败类型 | 本地 | 托管 | 码 | 异常 / 字段 | 重跑规则 |
|---|---|---|---|---|---|
| 登录失效（未派发） | 10 | 10 | **10** | `LoginRequiredError(reason="login", publish_attempted=False)` | 修会话后**无条件**重跑 |
| 登录失效（已派发） | 10 | 10 | **10** | `reason="login"`, `publish_attempted=True` | **先核对**笔记是否存在 |
| 要求人机验证（未派发 / 已派发） | 10 | 10 | **10** | `reason="verification"`, `publish_attempted=False/True` | 过验证后通常不必重扫码；已派发同上看核对 |
| ARM 就绪窗用尽 / 预算耗尽（**确定**未派发） | 1 | 1 | 1 | `budget.timeout_error(publish_clicked=False)` | 可重跑 |
| FIRE 派发后异常 | 9 | 9 | 9 | `PublishResultUnknownError` | **禁止**自动重跑 |
| OBSERVE 15s 未离开 `/publish/publish` | 9 | 9 | 9 | `PublishResultUnknownError` | 先核对再重跑 |
| 图文缺图 / 视频失败态（点击前，09） | 1 | 1 | 1 | 上传失败 `RuntimeError` | 可重跑 |
| 话题插错 / 多插（点击前，08） | 1 | 1 | 1 | `reason="topic-mismatch"` / `"topic-multi-insert"` | 可重跑 |
| 用法错误（缺 `--account` 等） | 2 | 2 | 2 | `UsageError` | 修正参数 |
| 429（Launcher / Local API） | — | 11 | 11 | `RateLimitedError` | 退避重试 |
| 双凭证冲突 / 不支持平台 / Profile 或 CDP 失败 | 1 | 1 | 1 | `RuntimeError` | 处理后重跑 |
| `Ctrl-C` | 130 | 130 | 130 | `KeyboardInterrupt` | — |
| **运行前**预检（本地：文件缺失 / 无 `galaxy_creator_session_id` / 已过期；托管无前置） | 10 | — | 10 | `LoginRequiredError(reason="login", publish_attempted=False)`（12 §1） | 修会话后重跑 |
| `check`（本地 / 托管） | 10 | 10 | 10 | 「确定未登录」→ 10；`classify_blocked` 命中 → 10；结构异常 / 导航 5xx / 超时 → **1**（12 §2） | 按 12 的表 |

- **表的形状**：行按**失败类型**（调度侧实际能看到的分类），不按观测点；`C1–C4` 等检测点写在表下方一段，只说明“某一行为什么会在这里被判出来”，不占列。
- **权威副本在 `spec.md`**；`docs/CLI.md:160-171` 的对外表（只有码、没有 `reason` / `publish_attempted`）保留，并在 spec 中声明为**派生投影**，避免两份漂移。本票不改 `docs/CLI.md`——运行中码值没变，变的只有文案。
- 最后两行**不由本票决定**：07 把“本地预检 / `check`”整块移交 **12**，12 已于 2026-11-11 关闭，上表直接引用其 §1/§2 的结论（本票只负责它在整张表里不缺行）。

### 1. 文案：在 raise 点拼，四句话 + 一个后缀

不做模板体系，不新增渲染器，`sau_cli.py` 继续 `print(str(exc))`。消息由 raise 点根据 `reason`、`publish_attempted`、`session.mode` 选句：

| 场景 | 文案 |
|---|---|
| 本地 · login | `小红书登录态无效：请运行 sau xiaohongshu login --account <账号名> 重新扫码后重试。` |
| 托管 · login | `小红书登录态无效：请在 {App} 中登录该 Profile 后重试。` |
| 本地 · verification | `小红书要求人机验证：请在浏览器中完成验证后重试。` |
| 托管 · verification | `小红书要求人机验证：请在 {App} 中完成该 Profile 的验证后重试。` |
| 任一 · `publish_attempted=True` | 上句后追加 `发布可能已发出：重跑前请先确认该笔记是否存在。` |

- `{App}` 取 `provider_label(session.mode)` → `Multilogin` / `AdsPower`。**不再写死 Multilogin**，这是本票要修的缺陷。
- **不带 `profile_id`**：`BrowserSession` 目前只有 `mode`（`:94-101`），不为了文案新增字段；句子用“该 Profile”。
- 本地句不解析 `account_file` 文件名去还原账号名，只给占位符 `<账号名>`，避免与 `resolve_account_file` 的落盘规则耦合。
- `reason` / `publish_attempted` 两个字段**保留**（07 §2）：虽然 CLI 不消费它们，但测试与后续日志按字段断言，不靠字符串匹配。

### 2. 参数：删掉 `multilogin` 布尔，改用 `session.mode`

07 说“删门保参数”，本票把**参数本身也删掉**，因为模式早已在会话对象上：

- `uploader/xiaohongshu_uploader/main.py:1096`、`:1304`：`*, multilogin: bool = False` → 删除，改为 `*, mode: str`（`"local" | "multilogin" | "adspower"`）。
- `:1236`、`:1419`：`multilogin=session.managed` → `mode=session.mode`。
- 07 的“参数只决定补救文案”在本票由 `mode` 承担；布尔是**信息丢失**的那一步，留着就无法写出 AdsPower。
- `utils/browser_session.py`：`_PROVIDER_LABELS` / `_provider_label` 改为公开 `provider_label(mode)`（内部调用点同步、`__all__` 补一项）。这是本票唯一动 `utils/` 的地方。

### 3. 判定器：用 07 的，删掉现存的 substring 分类

现网 `main.py:101` 的 `_LOGIN_URL_MARKERS = ("login", "captcha", "verify", "two-factor", "2fa")` 是**子串**匹配：任何查询串里带 `login` 都会命中（如 `?redirectPath=…`），也不区分验证与登录，与 07 的 path 分类器直接冲突。整块删除（`_LOGIN_URL_MARKERS`、`_raise_if_login_required` `:104-118`），换成 07 §1 的 `classify_blocked(page) -> None | "login" | "verification"`（主框架 path 为主 + 可见 `login-box` 补强；命中 path 即短路）。落点先放小红书模块内，抽到共享层归 **15**。

### 4. 调用点清单（两模式共用，删 8 处 `if multilogin:`）

| 检测点（07） | 位置 | 现在 | 改为 |
|---|---|---|---|
| C1 `goto` 之后 | `:1105`（视频）、`:1313`（图文） | `if multilogin: _raise_if_login_required(page)` | `classify_blocked` 无条件调用，`publish_attempted=False` |
| C2 每轮 >2s 等待循环 | 视频预览轮询 `:1109-1148`、图文标题等待 `:1324-1330` | **完全没有**检查 | 每轮一次 `classify_blocked`，`False` |
| C3 进 ARM 之前 | `wait_until_allowed`（`:1164`、`:1347`）之后 | **完全没有** | 必查一次，`False`（最后的安全退出点） |
| ARM 预算耗尽分支 | `:1173-1174`、`:1356-1357` | `if multilogin:` 门 | 无条件调用，`publish_attempted=publish_clicked` |
| FIRE 异常分支 | `:1195-1197`、`:1378-1380` | `if multilogin:` 门 | 无条件调用，`publish_attempted=True` |
| OBSERVE 轮询 | `_wait_publish_outcome` `:689`（04 重写为 500ms / URL 判定） | 无检查 | 每轮 `classify_blocked`，`True` |
| `XhsPublishRejectedError` 分支 | `:1191-1193`、`:1374-1376` | `if multilogin:` + 该异常 | 异常本身由 **04** 整块删除，本票不处理 |

- 合并规则沿用 07：**页面状态命中压过同点的 1 / 9 / 超时**；`publish_attempted` 在派发**之前**置位（03 §3），因此“点击后异常”分支传 `True` 时，`publish_clicked` 已为真。
- `sau_commands/xiaohongshu.py` 的**运行前**预检不属本票的 8 个调用点：12 已定**从发布链路删除** `cookie_auth` / `is_logged_in` 两次独立启动（`uploader/xiaohongshu_uploader/main.py:286-378`、`sau_commands/xiaohongshu.py:313-317`），改由 C1 统一判定；本票按 12 引用，不重复实现。

### 5. 测试要求（策略归 16，这里是最小断言集）

`tests/test_xiaohongshu_uploader.py`（沿用 `FakeLocator` / `RecordingPage`）：

1. 本地模式**也**能判出登录页（现在是 0 覆盖，因为门挡住了）——这是本票最核心的回归断言。
2. 四种文案组合的字符串 + `exc.reason` / `exc.publish_attempted` 字段断言；托管版必须出现 `AdsPower` 且**不出现** `Multilogin`。
3. `classify_blocked`：`/login/x` → login、`/website-login/captcha` → verification、`?redirectPath=/website-login/captcha` 的登录页 → login（按 path 优先）。
4. `publish_attempted` 在派发**前**为 `False`、派发后任何 10 均为 `True`。

### 6. 与其它票的边界

- **12**：运行前预检退出码、`check` 宽松/严格 → 已闭（本地预检 10、`check` 失效 10 / 探测失败 1、发布链路预检整块删除），本票只在 §0 表中接行、§4 中引用，不重决。
- **03/04/07**：检测点、码值、窗口、判定顺序均已定，本票只做“两端同码同文案同判定器”的落实。
- **15**：`classify_blocked` 与 `provider_label` 是否进共享层、其余 15 个平台的 `if multilogin:` 门与“Multilogin”写死文案 → 随 15 的平台迁移处理，**本票只修小红书**。
- **16**：用 §0 表做正/负断言；§5 是最小集。
- **17**：把 §0 表、§1 文案表、§2 参数来源并入 spec，并声明 `docs/CLI.md` 为派生投影。

### 7. 修订记录（本票内被推翻的中间结论）

- 2026-11-11 grilling 中曾定为“结构化上抛 + `sau_cli.py` 边界渲染四模板 + 每平台导出 `LABEL`”，随后用户否决：**不做模板体系、照旧在 raise 点带文案**。否决后 `multilogin` 参数由“改名保留”改为“删除”——模式来自 `session.mode`，无需再传。
