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
- **文本兜底单语中文**（22 取证后修订，2026-11-11）：结构选择器能覆盖的环节绝不引入文本；文本不可省时**只保留中文**——`locale=en-US` 下界面仍全中文，英文界面不存在，原「中英双语、英文优先」约束作废（证据见 22）。
- **发布按钮只留新版**：`xhs-publish-btn` 为唯一入口，旧版 `.publish-page-publish-btn button.bg-red` 不做兜底（决定见 05）。
- **用户明确要求**：humanize 这类通用防封手段应能被其它 15 个平台复用（决定见 15、10）。**2026-11-11 加强**：humanize 的行为集合按上游**全量采纳**，且其它平台**也要改成这样**（不只是「可复用」）。
- **产出是规格**，本图内不改代码。
- **节流归调用方**（用户明确，2026-11-11）：发布间隔、日上限、失败冷却、连续失败熔断由调度 App 实现，本规格**不实现、不设默认值、不建状态文件**；CLI 只保证「调用方能据此判定」的信号（契约见 18）。
- 覆盖范围包含此前审计出的“托管模式一致性”问题（见 13、14），不另开一张图。

### 领域词汇

使用 `GLOSSARY.md`：发布超时预算、发布结果未知、设置后回读（set-then-readback）、登录失效、本地模式 / 托管浏览器模式、Browser session。

### 代码事实

- 入口：`sau_commands/xiaohongshu.py` → `uploader/xiaohongshu_uploader/main.py`。
- 预算：`uploader/publish_timeout.py` 已有 `PublishTimeoutBudget`（目前仅 `uploader/tk_uploader/main_chrome.py` 使用；小红书自建了一套等价逻辑且缺 clamp）。
- 测试：`tests/test_xiaohongshu_uploader.py`（`FakeLocator` / `RecordingPage` / `FakeKeyboard`）。
- 会话接缝：`utils/browser_session.py`（托管分支忽略 `launch_kwargs` / `context_kwargs` / `init_script` / `context_setup`）。
- 选择器现状（05 实机比对）：发布按钮与 `XHS_LOGIN_POSITIVE_SELECTORS` 里的 `button:has-text("发布")` 现网均 **0 命中**；`#publish-container` 是 **class**（`.publish-container`）不是 id，`_click_declaration_option` 主路径恒为 0，实际一直走 JS 文本兜底。

### 技能

`/grilling`、`/domain-modeling` 用于决议；`/research` 用于外部事实。

### 置信度

结论必须标注：**代码明确 / 注释声称 / 仅推断 / 需真机验证**。

## Decisions so far

<!-- 一条已关闭工单一行：- [标题](链接) — 一句话结论 -->

- [01 — 上游发布链路可信信号清单](./issues/01-upstream-signal-audit.md) — 发布按钮靠自定义元素状态属性（`is-publish`/`submit-disabled`）零中文；成功判据仅是“URL 不含 `/publish/publish`”，**会把验证页当成功、不可照抄**；风控页分类函数存在但**发布链路从不调用**；打字是 `InsertText` 逐字+随机间隔（**无 key 事件**）；发布前**没有** `BeforeSubmit` 停顿。
- [02 — 真机 DOM 取证（发布页/图文页）](./issues/02-live-dom-snapshot.md) — `xhs-publish-btn` 现网存在（旧版选择器为 0）；`submit-disabled` 只表示“可提交”不表示“填完”，但**可作视频就绪信号**（标题框/“分辨率”警告都会提前误判）；正文是 tiptap 非 Quill；**一次话题插入产生 2 个同值 `a[data-topic]`**（1 个编辑器 + 1 个预览镜像，23 已定位），“数量 +1”整页不可用；登录失效是 `/login` 前缀 + login-box，**未观察到 `/website-login`**；`.feature-guide__btn` 与图片 AI 弹窗是常驻覆盖层。
- [03 — 发布提交语义：预算底座 + 单次点击](./issues/03-publish-submit-semantics.md) — 提交段定为 `ARM（1s 轮询就绪，窗口 min(60s,预算)）→ FIRE（先置位再派发，只点一次）→ OBSERVE`；重试只允许发生在「确定未派发」的 ARM 侧；点击后落登录/验证页**保持 10**（但带「发布可能已发出」标志，须先确认再重跑），点击前归 10 且可无条件重跑；预算底座已落地但**零 clamp**是现存缺口。**OBSERVE 段已于 2026-11-11 由 04 修订**（15s 窗口、按 URL 判定、无文案扫描、超时 9）。
- [04 — 限流与拒绝提示的处理口径](./issues/04-rate-limit-and-rejection.md) — **不识别任何提示文案**：删除限流词/拒绝词/toast 扫描，三张词表全空（「操作频繁」等两条仅来自自研提交、无真机证据）；OBSERVE 固定 `min(15s, 预算)`、500ms：离开且非登录/验证页→**0**，登录/验证页→**10**，未离开→**9**。
- [05 — 选择器基线矩阵](./issues/05-selector-baseline.md) — 16 个环节逐项定基线：**结构优先、文本最后**；发布按钮只留 `xhs-publish-btn`（旧版与三条中文 `has-text` 直接删）；标题/正文/上传/定时/原创开关都能上零文本结构锚点；话题回读限定**编辑区**、每次插入**恰好 +1**（整页 +2 是预览镜像；23 已证）；登录失效不采用 `/website-login`；文本兜底**中文单语**（22 已证无英文界面）；命中打 `debug`、非首选打 `info`，新分支稳定命中即删旧。
- [06 — 页面就绪与元素可用性判定](./issues/06-readiness-and-visibility.md) — 就绪 = **目标自带信号 + 一次 DOM 静默**（500ms / 上限 3s，未静默放行并交目标判据），**不照搬上游固定 2s+1s**；判定按角色四档 `attached / visible / interactive / editable`（`visible` 用计算样式 + 祖先 opacity ≥ 0.1 + 自身 aria-hidden；`interactive` 在**真实落点**做 hit-test），`attached` 内建唯一性、多义即 `ambiguous:N`；遮挡只走**已知覆盖层点击 + Esc**（永不摘节点、永不点空白）；所有等待 `clamp`，**不设独立“就绪超时”错误**；不确定按“离派发远近”：可见性探测失败**放行**、hit-test `probe-failed` **阻断**（否则会被 03 记成 exit 9）。
- [21 — 同一账号的并发与 Profile 生命周期所有权](./issues/21-concurrency-ownership.md) — **前提：调度侧保证同一账号不并发**（与 `CLI.md:195` 一致），故不引入进程间锁、不做 active 预检、不改 Stop 所有权；多账号并发靠独立 Profile 天然成立；若将来允许多实例须重开（届时需账号级锁 + Stop 所有权 + cookie 原子写）。
- [07 — 风控页与登录失效的分级](./issues/07-risk-page-classification.md) — 判定收敛为**一个只读分类器**：主框架 **path 为主**（`/website-login/captcha`→验证、`/website-login`→登录、`/login`→登录；只看 path、不 `unquote`）+ **可见 login-box 补强**（按 06 的 `visible` 档），**不做**非跳转式验证码弹层；`LoginRequiredError` 加 `reason`(login|verification) 与 `publish_attempted`，**两者同码 10**、不加新码；**删「门」保参数**（两端必调，模式只决定补救文案），预检探针的退出码交 12；四检查点（goto 后 / 每个 >2s 等待循环 / FIRE 前必查 / OBSERVE 轮询）；合并规则：**页面状态命中压过同点的 1/9/超时**，点击前 `publish_attempted=False`、点击后 `True`。
- [08 — 话题插入校验与编辑器状态](./issues/08-topic-insertion.md) — 话题是**增强项**：缺失一律降级（保留纯文本 `#tag` + 空格，不按 `Backspace` 清理），**插错必须中止**（点击发布前 exit 1，`reason=topic-mismatch|topic-multi-insert`）；候选按 name **归一化全等**、**顺序全扫全部渲染项**（真机热榜排序，精确项可能在第 4 位）；重试沿用上游「找→点 5s/200ms/最多 3 次」，成功判据改为编辑区**多重集合差**（基线**按标签固定、重试不刷新**；23 修订：编辑区内**恰好 1 个新增**，>1 即中止）；候选就绪看 `.item > 0` 而非容器可见（0 项空壳先出现，约 430–570ms 才出 50 项）；**不抄** 20×ArrowDown + 2×Enter（220 事件/单且可能加空段落；23 证实连续插入无需任何复位）；`>10` 收敛为**校验期截断 + warning**（CLI 不再报错）。
- [23 — 连续多话题插入取证](./issues/23-topic-multi-insert-evidence.md) — 连续插第 2/3 个话题**无需任何复位动作**；`a[data-topic]` 整页每次 +2（1 编辑器 + 1 预览镜像），**必须限定 `div.tiptap[role=textbox]`，编辑区内恰好 +1**；点击后下拉**0–2ms 从 DOM 移除**（双插是理论风险）；`.name` 采样 30/30 带 `#`，精确项三次都排第 4；候选容器可见 ≠ 就绪（约 430–570ms 才出 50 项）。据此把 08 的「1–2 个新增」收紧为「恰好 1 个」。
- [09 — 上传完成判定：图文逐张 + 视频就绪](./issues/09-upload-completion.md) — **图文逐张**（不做批量：上游 `44061fd` 有静默丢图事故），每张 `.img-preview-area .pr` 计数 `>= i+1`（60s/张，clamp 预算，500ms 轮询）+ 最后一张后**一次 DOM 静默复检**（静默后 `>= N` 放行、`> N` 记 warning）；首张用空状态唯一 input，**第 2 张起点「+」瓦片走 file chooser**（禁止上游 `inputs[0]` 兜底，05 第 4 行据此修订）；**视频就绪复用 03 的发布按钮谓词**（一个 helper、两个窗口：09 就绪窗 `min(600s, 预算)`、03 ARM 窗 `min(60s, 预算)`），删全部关键词扫描与标题框兜底；**任何一次失败整体中止**（exit 1、点击前）：不重传、不降级少图、失败面即时收敛为 `missing`/`unusable`；删死代码 `handle_upload_error`；不预留分段配额；新增 24 补多图时间线/第 2 张入口/视频失败态取证。
- [10 — 人类化交互的最小可行子集](./issues/10-humanize-subset.md) — 上游 11 个动作**全量实现**但按**语义锚点**接线（不机械垫时延：有动作 ≠ 像人）；打字**逐字符分派**——ASCII 走真 key 事件、中文/emoji 只能 `insert_text`（与上游同级，Playwright 对非 US 布局只发 input；**不做** IME 伪造）；**打字无时间上限（C）**，超时走既有预算语义；点击**全站统一**曲线+抖动+`stillOn`+按下保持、**无内部重试**（重试只在 03 的 ARM）、删 `el.click()` 与 `force=True`；日期逐字键入不回读（归 11）；`Control+KeyA` → `ControlOrMeta+A` 修 macOS 缺陷；API 落 `utils/humanize.py`（参数原样采用上游 + 可覆盖 + `HUMANIZE=0` 快路径），其余平台迁移归 15。长文平台的预算冲突见 25。
- [11 — 设置后回读与元数据校验](./issues/11-set-then-readback.md) — 采用**上游薄口径**（看过上游后主动推翻早前的全量回读方案）：只保留原创**点前**读状态 + 标题/正文**单次 `Has`** 越限检查；定时开关/时间、内容类型、封面**零回读**；原创 `true` 失败→`exit 1` 中止，`false`/声明/封面失败→降级继续；标题按 **UTF-16 加权 `ceil(加权/2)≤20`**，显式超限报错不截断、自动生成标题按同口径截断，正文/标题越限均 `exit 1`（点击前）；`--schedule` 边界 **2h–14d**、**墙上时间不换算**（aware offset 被忽略）；**「定时设置结果不可观测」登记为已知缺口**（→26），与 charter「禁止对齐下界」的冲突已记录。
- [22 — 英文界面文案与选择器取证](./issues/22-english-ui-evidence.md) — **英文界面不存在**：`locale=en-US` + `Accept-Language: en-US`（`navigator.language` 实测 `en-US`）下，标题/正文/原创开关与弹窗/内容类型声明及二级/封面弹窗/登录页（含 `APP扫一扫登录` 二维码面板）**仍全部中文**，图文编辑器 `bodyText` 指纹与 zh-CN 逐字相同；`<html>` 无 `lang`、无 i18n 文案表、响应头无 `Content-Language`。→ 17 删除全部英文兜底，文本兜底收敛为中文单语；05 第 13 行封面候选实机修正为 `.cover-edit-entry` → `.d-modal.cover-modal…`（`上传`/`完成`）。
- [14 — 托管模式默认值与参数可见性](./issues/14-managed-defaults.md) — 默认改成**有头**（一条规则，本地不再读 `conf.LOCAL_CHROME_HEADLESS`）；`debug` 默认**关**且 `DEBUG_MODE` 删除（CLI 路径从未读过它）；托管忽略的本地参数每 run 打**一条 WARNING**（只报键名，不 raise、不报值）；`--account` 在托管下**无意义**（标签一律 `profile_id`，传了算被忽略；login/verify/delete 仍需要）；session 层**两种模式**都打一条启动日志（mode/headless/identity/ignored）；托管 `login` 不做（移出范围）；实施拆 2 个改动（参数契约 / session 可观测性）。
- [24 — 多图上传时间线取证](./issues/24-multi-image-timeline-evidence.md) — **`.pr` 文件选中即插入**（早于首个上传 PUT），判据升级为**每项完成态**：`tiles[i].querySelector('.mask.uploading') == null`；`aria-busy` 全程 `false`、无百分比节点，**不可用**；`.entry` 确实触发 filechooser 并指向 `.img-list .top input[type=file][multiple]`（两个同 accept input 只能靠 `[multiple]` 区分）；重复派发同一文件 **N+1**、拖拽只改序、删除 `.close-btn` −1；视频失败有结构信号 **`div.fail`** 可即时 exit 1（`upload-input` 恒在、`submit-disabled` 失败态恒 `true`，都不能当信号）；20MB PNG 本机 25.5s、慢速时段 >40s，60s 保留 + clamp。
- [15 — 共享层边界与迁移顺序](./issues/15-shared-layer-boundary.md) — 只抽四块 + 一个小件进 `utils/`（humanize / 判定原语 / 开关读取 / 风控分类形状 / `provider_label`），**预算留 `uploader/`**、行为层不读 deadline；无状态函数为主、只有 humanize 保留注入类；迁移顺序 **小红书 → TikTok → Instagram** → 其余按风险×同构（文章流已由 25 解阻）；只有全局 `HUMANIZE=0` 开关；bilibili（biliup）与旧 `xhs_uploader`/`tk main.py` 不迁不删（`xhs_uploader` 已于 2026-11-12 删除，见 `.scratch/legacy-web-removal/spec.md`）；验收四件套，真机 **dry-run 不真实发布**（TikTok/Instagram 需先补 `--no-publish`）；静态断言 `fill(`=0 **豁免 YouTube `_fill_editable`**（25 修订）。
- [13 — 本地/托管失败语义统一](./issues/13-failure-semantics-parity.md) — 运行中语义本就统一（07）；本票落**三件事**：① 删 `if multilogin:` 门（8 处）并改用 **`session.mode`** 而非布尔（`utils/browser_session.py` 的 `provider_label()` 转公开），② 删 substring 判定器（`main.py:101-118`，`"login"` 会命中任何含该词的 URL）换 07 的 `classify_blocked`，③ **不做文案模板**——`LoginRequiredError` 仍在 raise 点带文案（四句 + “发布可能已发出”后缀），托管句写 `AdsPower`/`Multilogin` 且**不带 `profile_id`**。产出**按失败类型切**的退出码契约表（spec 单一权威，`docs/CLI.md` 为派生投影），运行前预检/`check` 行**引用 12**；其余 15 平台的同类门与写死文案留 **15**。
- [12 — 会话预检、check 判定与身份回读](./issues/12-session-and-identity.md) — 会话可用性只有**一个权威来源**：发布页那一次导航后的只读观测（07 分类器 + 05 第 15 行锚点）。**删掉本地 `cookie_auth` 预检与托管 `is_logged_in` 预检**（一次发布从 2 次浏览器 / 2 次发布页降到 1/1）；本地只留**零网络快路**（账号文件 + `galaxy_creator_session_id` 存在且未过期 —— `cookies/xiaohongshu_180.json` 里确实有、约 30 天），快路失败 → **10** 且不启浏览器；网络/5xx/超时/结构异常 → **1**（故障 ≠ 失效）。`check` = **发布页**（不改轻量页）+ 上传锚点 **attached**：命中分类器 → 10（带 `reason`）、锚点 → 0、锚点缺失或探测失败 → 1；**`invalid` 退出码 1 → 10**，stdout 仍 `valid`/`invalid`，不做两级。**写回只写成功**（发布 0 / `--no-publish` / 登录成功 / `check` valid，其中 `check` 写回是新增点），`1`/`9`/`10` 一律不写（按结果码而非有无抛异常；现状本已等价，改动只为可断言），写盘改**原子替换**；托管不读不写。登录后复核**不再起第二个浏览器**，改同 context 一次发布页导航，未就绪判 **1** 不判 10（避免扫码循环）。**身份回读不做**；将来若要，取证首选 `x-user-id-creator.xiaohongshu.com` 这个 cookie 而非 `__INITIAL_STATE__`，范式复用大鱼号 `identity.json`，边界归 15。
- [26 — 回读/越限信号真机取证](./issues/26-readback-signal-evidence.md) — **标题锚点是死的**：`div.title-container` 现网 0 个；真实信号是 `.edit-container .suffix` 越限时改类名 `max_suffix`（文案 `21 / 20`），输入后 **306–344ms** 才切换 → 11 的标题检查必须换锚点并加 ≥350ms 等待。**正文锚点有效**：`div.edit-container div.length-error` 在 1001 字命中（上限 1000，0/1000 与 1001 边界实测）；话题**计入**且按 `#name` 计（`#旅行pov[话题]#` → 7，不含 `[话题]#`），正文逐字符计数；越限时 `submit-disabled` 仍 `false`。**定时开关状态可读**（`.d-switch-simulator` checked/unchecked + 日期输入出现/消失，三次可逆；定时发布复用同一 `xhs-publish-btn`，仅 `submit-text` 变）；**日期被拒在失焦后静默回滚**到上次合法值（默认 `now+1h`），无错误文案 → 缺口从「不可观测」收窄为「可观测但本轮未实现」，是否补读 → 27。原创点后 `checked` 稳定可读；声明入口文本会变为所选标签；封面无稳定 `img.src` 信号。**流程约束：定时时间输入禁止 Enter/Tab**（Tab 把焦点送到 `xhs-publish-btn`，Enter 触发「暂存离开」并离开编辑器）。
- [18 — 发布节奏、失败冷却与熔断](./issues/18-publish-pacing.md) — **节流整体移交调用 App**：CLI 不建状态文件、不做预检、不加参数、**不设任何默认数字**；规格只落一张「调用方契约」（`0`/`1`/`9`/`10`/`11` → App 动作，核心是 `1`=可无条件重跑、`9` 与 `10+publish_attempted`=禁止自动重跑先核对）。补 `10` 的点击前后歧义：**退出码仍是 10**，仅在点击后才检出登录/验证页时多打一行 stderr `publish_attempted=true`（码表不动，07 的 `publish_attempted` 由此从「异常标志+中文后缀」升级为机器信号）。`--not-before` 机制不动，但**禁止拿它做节流/排程**（等待发生在填表后、浏览器与托管 Profile 全程被占用，会卡住 App 自身调度）。**「每天 50 篇」是上游作者个人实操经验、非平台规则**，不作依据。`9` 与「实际是限流」仍不可区分（04），故 `9` 一律先核对。
- [27 — 定时设置后的单次回读](./issues/27-schedule-readback.md) — **补、且分三处断言**：C1 点开关后读 `.d-switch-simulator` `checked` + 日期输入 attached；C2 `blur()` + 约 300ms 后读 `input.value`（`%Y-%m-%d %H:%M` 解析按分钟比，回滚即 `exit 1`）；C3 FIRE 前复核开关/值/**请求值仍 > now**——后者是唯一堵住 `--not-before` 把定时时刻等过去（CLI.md:88 的「拒绝或立即发布」）的地方。读失败/空值/不可解析一律阻断、不重试、`--no-publish` 同拦、不新增码不产生 9。**上游零回读**（只点开关 + 固定 sleep，日期只校验 `now+1h–14d`），按 charter 记为「禁止对齐下界」偏离；残留风险：只证客户端接受、平台边界未真机验证、时效是粗判、时钟口径不变。
- [17 — 汇总可实施规格](./issues/17-assemble-spec.md) — 产出 [`spec.md`](./spec.md)（1058 行）：§2 十一缺陷 → §3 十四个改动单元（每单元七段含行号）→ §4 退出码契约母本 → §5 S1–S12 实施顺序 → §7 二十四项上游偏离 → §8 本轮不做（9 out of scope / 4 待定 / 15 已知缺口）→ §9 回写与真机验收。合并 03→04→07→18 的提交语义四层修订与 05→09/22/26 的矩阵四次修订；汇总期补充代码事实：失败截图**未传 `path` 根本不落盘**、`XHS_PUBLISH_SUCCESS_URL_PATTERN` 与 `check_original_declaration` 为死代码、`pre_click_error()` 返回 `RuntimeError`（不造新错误类）。
- [25 — 长文本平台的打字预算口径](./issues/25-long-text-budget.md) — **对 10 的 C 作显式修订**：`Humanizer.type_text` 内部按 **1000 字**（`HumanizeProfile.type_horizon_chars`，单例、平台不得覆盖）自动分流——`≤1000` 逐字（小红书正文 2.3min 不变）、`>1000` **一次 `keyboard.insert_text`**；**不用剪贴板 paste**（写失败会粘进用户上一条内容 → 静默发错正文）、不用 `fill`；打字成本被结构性封顶 → **预算仍是 15min 常数、不加平台表/工厂、不加 `exit 2`、18 不需豁免**。真相更正：TikTok 描述是 **4000**（2200 是 IG）；YouTube 描述**故意用 `fill`**（`#` 触发补全）；文章正文是 **HTML 粘贴**、永不进打字路径 → 15 的步 10 解阻、逐平台上界表作废，`fill(`=0 断言豁免 YouTube `_fill_editable`。
- [16 — 测试与验收策略](./issues/16-test-strategy.md) — 夹具抽 `tests/fakes_xhs_dom.py` + `tests/fakes_clock.py`（虚拟时钟 = patch `time.monotonic` + 替换模块级 `asyncio` 名，**生产签名零改动**）；两条原则「前提可只靠真机、机制必须离线」「机制消失即删用例、不留纪念性断言」；**`--no-publish` 升级为「跑到 ARM 就绪」**（现状在 ARM 前 return，且 `xhs-publish-btn`/`is-publish`/`submit-disabled` 代码里 **零命中**，ARM 是新增语义）；真机只做正路 + 三类低风险注入（改坏 cookie 验证 C1、假 mp4 验 `div.fail`、移走账号文件验快路），断网/改 URL/杀浏览器明确不做，**托管真机无账号则可选**；退出码表做成表驱动镜像 `tests/test_xhs_exit_contract.py`（`0/1/2/9/10/11/130` + `publish_attempted` 行 + 覆盖集合 meta 断言）；`/captcha/verify`（无取证）、toast/拒绝词、`is_logged_in` 相关用例**全删**，kuaishou 与其余平台零改动作回归基线。

## Not yet specified

- **素材校验**：图片数量/尺寸/格式、视频时长/大小——两边都没有，是否需要作为可靠性的一部分。
- **视频封面流程**是否也要“可信信号化”（现为增强步骤，失败即跳过）。
- **失败截图去重**：小红书失败截图落在 0.5s 重试循环内且无去重（`main.py:1199`、`1382`），这是 14 把 `debug` 默认关的直接原因；去重落地后才谈“失败留证默认开”。
- **托管 Profile 画像契约**：界面语言 / UA / 时区 / 视口由 Profile 承担，但哪几项是硬要求、启动时能否校验（现在只有 Instagram 一条代码注释说“必须人工保持英文”）—— 等 12 的会话预检成型后再定是否成票。
- **多账号隔离与设备画像轮换**：托管模式由 Profile 承担（Out of scope）；本地模式若长期多号运行，是否需要每号独立 `user_data_dir` 之外的隔离手段。

> **本图收尾（2026-11-11）**：以上五项均未毕业成票，已在 [`spec.md`](./spec.md) §8.2/§8.1 按「待定项 / Out of scope」登记（不丢；本图不再开新票）。全部工单已关闭，目的地（`spec.md`）已达成。

## Out of scope

- **发布节奏、失败冷却与熔断的实现与调参**：整体由调用方 App 负责；本规格只提供「调用方契约」（18）。
- 可见范围、商品绑定、URL 图片下载——属能力补齐，不是“降低封禁风险 / 提高可靠性”。
- **代理**（`XHS_PROXY` 一类）：托管模式由 Profile 承担出口；本地模式加代理属独立的部署议题。
- `sau_backend.py` / Vue 前端 / 调度 App 本身。
- 上游 Go 代码移植、`headless_browser` 复刻、浏览器构建分发（自建指纹浏览器）。
- **本地模式浏览器卫生改造**（persistent `user_data_dir` / 真 Chrome `channel` / 删 UA 半修与 `stealth.min.js`）：用户决定本轮不改、维持现状；代价是本图不消解「每次全新指纹、无历史无缓存」这个最弱环，未做任何前后取证（[19](./issues/19-local-browser-hygiene.md)）。
- **托管下的登录能力补齐（从 Profile 抓二维码返回）**：能力补齐，不服务 ①降封禁风险 / ②可靠性；本轮维持 `login` 拒绝，文案归 13（[14](./issues/14-managed-defaults.md)）。
- 多账号并发隔离（托管由 Profile 承担）。
- **发布结果未知后的自动对账**：`exit 9` 之后回「笔记管理」按标题/时间核对是否真的发出（以及是否把 `9` 改判 `0/1`）。属"发布后回后台翻列表"的脚本行为，charter ① 优先于它对人工成本的节省；收尾维持 `9` + 人工核对，**不再评估**（[20](./issues/20-publish-reconciliation.md)）。
