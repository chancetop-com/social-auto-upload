# 16 — 测试与验收策略

Status: resolved
Type: grilling
Blocked by: 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14, 15, 18, 19
Assignee: wayfinder-session (opencode)

## Question

定义这套改动的测试与验收策略（仓库惯例：每个 effort 收尾前必须有测试策略）。需要确认：

1. **离线层**：`tests/test_xiaohongshu_uploader.py` 的 `FakeLocator` / `RecordingPage` / `FakeKeyboard` 需扩展什么（可见性、属性读取、mouse、坐标、时钟注入）；是否新建 fake 文件。
2. **每条决议的正/负断言**：至少一组；哪些决议**不可离线验证**（选择器真实存在、风控页、人类化效果、限流词真实文案）。
3. **真机验收**：`--no-publish` 干跑清单、一次真实发布的最小验收、如何注入失败（断网/改 URL/改选择器）。
4. **不测什么**：平台风控、验证码、扫码、指纹、真实封禁。
5. **与现有测试的关系**：哪些文件改动、哪些零改动（作为回归基线）。
6. 是否需要“契约表”测试（如退出码矩阵）作为 spec 的可执行镜像。

产出：测试矩阵 + 真机验收清单 + 不测清单。

## Comments

- 来自 **07**（2026-11-11）：新增一组**必须覆盖**的断言 —— 07 §0 状态机（C1–C4 × `login`/`verification` × 点击前/后）。全部可用现有 `RecordingPage`（改 `url` 属性）+ `FakeLocator`（login-box 的 count/可见性）单测覆盖，**不需要**真机。与问题 4「不测平台风控/验证码」的关系：真实验证码**页面不测**，但「分类器命中后我们抛什么、码是什么、文案说没说‘先核对’」**必须测**。真机缺口两条（见 07 §8）：`/website-login*` 是否真会出现；正常发布页上 login-box 的 count 与可见性。
- 来自 **18**（2026-11-11）：再 +1 组断言 —— 退出码 `10` 时 stderr 是否带 `publish_attempted=true`：点击前检出登录/验证页 → **不含该行**；点击后检出 → **含且仅一行**（`9` 不带，`0`/`1` 不带）。纯单测可覆盖（`RecordingPage.url` + 分类器）。
- **Q1 决议（2026-11-11，选项 A）**：DOM/浏览器 double 抽到 `tests/fakes_xhs_dom.py`，另建 `tests/fakes_clock.py`（`FakeClock`：`monotonic()` + `sleep()` 推进虚拟时间）；测试用 context manager 同时 patch 被测模块的 `time.monotonic` 与 `asyncio.sleep`。**生产代码不新增 clock/sleep 参数**（沿用 `test_publish_timeout.py` 已有的 patch 路线）。理由：单文件将翻倍、共享层断言对象与 15 的 TikTok/Instagram 迁移同源、轮询与静默窗口（06/09）必须可确定性断言，而真注入会把测试关切渗入生产签名。
- **Q2 决议（2026-11-11）**：按「前提／机制分离」立表 —— 前提（选择器在现网存在、真实文案、风控页真的出现）可以只靠真机/已有取证；机制（判定、异常、退出码、日志）不许用「需要真机」豁免单测。**托管模式真机验收降为可选**（可能没有可用账号），缺失时在 spec 记「未验证（仅离线断言）」而非阻塞。**05 的常量表断言是过渡期脚手架**：用于删除旧分支时有断言跟着改，**旧分支删除完成后同批删除**（避免断言退化成同义反复）；05 的永久保障改为「代码里只有一条路径」＋行为断言（命中日志级别），不再断言常量集合内容。
- **Q3 决议（2026-11-11，选项 A）**：`--no-publish` 语义**升级为「跑到 ARM 就绪」**：就绪谓词（存在 + 可见 + `is-publish` + `submit-disabled` + 06 hit-test + 10 落点复核）通过 → 打一条日志 → return 0，**不 FIRE**；且**跳过 `wait_until_allowed`**（干跑不被 `--not-before` 卡住）。`docs/CLI.md:465/498/511` 三处措辞跟着改（归 17）；TikTok / Instagram 后补的 `--no-publish` 必须同语义（15 的四件套才同水位）。副作用（可接受）：ARM 未就绪时干跑 **exit 1**，这是预期信号。**事实澄清**：现状 `--no-publish` 在 ARM 之前 return（`main.py:1160/1343`），且代码里 `xhs-publish-btn` / `is-publish` / `submit-disabled` **零命中**——ARM 是 03 新增语义，不是现状。
- **Q4 决议（2026-11-11，选项 A）**：真机失败注入**只做四类**（前三强制、第四可选）：① 移走账号文件 → `10` 且不启浏览器；② 改坏 `galaxy_creator_session_id` 值（保留字段、保留未过期）→ 启浏览器 → C1 判 `login` → `10`；③ 假 mp4（沿用 `research/probe_video_failure.py --bad`）→ `div.fail` → 点击前 `1`；④（可选）20MB PNG 验证逐张完成态与 60s clamp。**明确不做**：断网/恢复（制造不可判定中间态，与 charter ① 冲突，24 探针已证）、改 URL / 改选择器注入（属离线或人工探针）、真实发布后杀浏览器模拟 `9`（制造真实未知态）、托管模式真机（无账号则跳过并记未验证）。
- **Q5 决议（2026-11-11，选项 A + 删除原则）**：**机制已消失的用例直接删，不留纪念性断言**——删后若无代码路径对应，一律不保留。据此：`/captcha/verify` 具体用例删（价值由通用「未知路径 → `None`」断言覆盖，不为它给 07 加无证据路径）；toast/拒绝词 3 条、`cookie_auth` 预检 1 条、`LoginProbeTests` 的 4 条 xhs 用例、`test_login_markers_mid_upload_raise_login_required` 的 xhs 分支，全删。改写仅限「行为还在、判据变了」：OBSERVE 成功判据、ARM 截止、`fill_meta` 键盘动作、`test_adspower_cli.py:354`（14 把 `set_defaults(headless=True)` 改成 `False`，该断言必红）。kuaishou 侧用例零改动（15 不迁）；`test_publish_timeout.py` 只加不改。
- **Q6 决议（2026-11-11，选项 A）**：退出码契约表做成**表驱动的可执行镜像** `tests/test_xhs_exit_contract.py`：一行一场景，断言异常类型/字段（`reason`、`publish_attempted`）+ `sau_cli.main` 实际返回码 + stderr（含/不含 `publish_attempted=true` 行）；表写在测试文件里，**不解析** `docs/CLI.md`（派生投影）、不引入第二数据源；外加一条 meta 断言：表覆盖码集合 == spec 列出的集合。用例组织按决议分段（`DecisionNN...` + `test_NN_...`），运行沿用 `python -m unittest ...`，不新增 runner。

## Answer

**决议（2026-11-11）**：测试策略 =「前提/机制分离」+「机制消失即删」+ 表驱动契约镜像 + 真机只做正路与四类低风险注入；托管真机可选。产出如下，可直接进 `spec.md` 的「测试与验收」单元。

### 0. 三条原则

1. **前提 vs 机制**：选择器在现网存在、真实文案、风控页真的出现 = **前提**，可只靠已有取证（02/22/23/24）或真机；判定逻辑、异常类型、字段、退出码、日志 = **机制**，一律离线单测，不许用「需要真机」豁免。
2. **机制消失即删**：决议删掉的行为，其用例**直接删**，不重写成「纪念性断言」；删后无代码路径对应的用例一律不保留。只在「行为还在、判据变了」时改写。
3. **托管真机可选**：可能没有可用账号；缺测时在 spec 标「未验证（仅离线断言）」，不阻塞交付。

### 1. 夹具与时间接缝

- **`tests/fakes_xhs_dom.py`**（新，从 `test_xiaohongshu_uploader.py` 抽出并扩展）：
  - `FakeLocator`：`count` / `first` / `nth` / `locator` / `get_attribute`（含 `is-publish`、`submit-disabled`）/ `is_visible` / 计算样式脚本 / 子节点树 `/text`；**未 scripted 的选择器一律抛错**（照 `tests/fakes.py` 的 `ForbiddenApiError` 风格），避免静默通过。
  - `RecordingPage`：`url` 可写、`main_frame.url`、`goto` 记录、`evaluate` 脚本化（可见性计算、`document.elementFromPoint` 命中/落空/覆盖层）、`mouse`（`click`/`move`/`down`/`up` 全记录坐标）、`keyboard`（`press`/`down`/`up`/`insert_text`/`type`）、`screenshot`、`wait_for_*`（`timeout` 必须来自 clamp，记录实参）。
  - `RecordingLocator` 的 `click()` 记录调用次数——03「单次点击」用计数断言。
- **`tests/fakes_clock.py`**（新）：`FakeClock(start=1000.0)`，`monotonic()` / `advance(s)` / `sleep(s)`（推进虚拟时间并立即返回）。context manager `fake_time(*modules)` 做两件事：`patch("time.monotonic", clock.monotonic)`（沿用 `test_publish_timeout.py:62` 的既有路线）＋把每个目标模块的模块级 `asyncio` 名替换为 `SimpleNamespace(sleep=clock.sleep)`——**不 patch 全局 `asyncio.sleep`**。生产代码不新增 clock/sleep 参数。

### 2. 测试矩阵

| 决议 | 离线正/负断言（各至少一） | 只能真机 / 不可验证 |
|---|---|---|
| 03 | ARM 谓词四条件逐个不满足→继续等；满足→仅 1 次点击；FIRE 抛错→9 且**不再点击**；ARM 窗口用尽→1 | 视频就绪真实 ~12s 抖动；定时发布按钮 DOM（同一元素待确认） |
| 04 | 离开 `/publish/publish` 且非登录/验证页→0；15s 未离开→9；**零文本扫描**（断言无文本选择器、无 toast 扫描调用） | 限流真实文案存在性（决议就是不识别，故不测） |
| 05 | 行为断言：命中日志级别（首选 `debug`、非首选 `info`）、只有一条代码路径；**常量表断言为过渡期脚手架，删旧分支时同批删除** | 选择器现网命中（02/22 已取证，非测试项） |
| 06 | 四档判定（attached/visible/interactive/editable）边界；`ambiguous:N`；hit-test `probe-failed` 阻断、可见性探测失败放行；覆盖层→点击+Esc、**不摘节点**；等待全部 clamp | 计算样式/动画在真浏览器的语义 |
| 07 | C1–C4 × `login`/`verification` × 点击前/后；**未知路径→`None`**（含 `?redirectPath=` 不误判）；可见 login-box 补强（06 的 visible 档）；四文案 × 两模式 + `AdsPower` 不出现 `Multilogin`；`publish_attempted` 点击前置 False | `/website-login*` 是否真出现；正常发布页 login-box 的 count/可见性；**验证页真实 path**（现无证据） |
| 08 | 编辑区多重集合差**恰好 +1** 通过、>1 中止、0 降级保留纯文本；候选 0 项→50 项就绪时序（虚拟时钟）；重试底座不刷新 | 候选排序（23 已取证） |
| 09 | 逐张 `.pr` `>= i+1`；`.mask.uploading` 消失判完成；`div.fail`→点击前 1；静默复检 `>=N` 放行、`>N` warning；第 2 张起点走 file chooser | 真实上传耗时（24：20MB 25.5s，慢时段 >40s） |
| 10 | 曲线数学（固定种子）；ASCII→真 key 事件、CJK/emoji→`insert_text`；`ControlOrMeta+A`；`stillOn` 失败→放弃且不重试；`HUMANIZE=0` 快路径零随机 | 「看起来像人」不可测（仅推断，不设断言） |
| 11 | UTF-16 加权 `ceil(w/2)≤20`；标题/正文越限→点击前 1；原创 `true` 失败→1；`false`/声明/封面失败→降级；`--schedule` 边界 2h–14d、aware offset 被忽略 | `.max_suffix` / `.length-error` 存在与文案（26 取证中） |
| 12 | 快路失败→10 且**不启浏览器**；`check` 四出口（0/10/1/探测失败）；写回只写成功、原子替换；托管不读不写；登录后同 context 复核，未就绪→1 | 真实 cookie 30 天有效期 |
| 13 | 8 处门删除后本地也能判出登录页（**最核心回归**）；`provider_label` 两种托管值；`session.mode` 三值 | — |
| 14 | 默认有头；`DEBUG_MODE` 删除；忽略参数每 run 一条 WARNING、只报键名；`--account` 托管下进 ignored | 托管真实启动日志（需 AdsPower/MLX，属 smoke，可选） |
| 15 | 小红书接好后本图全部用例绿；`HUMANIZE=0` 前后可比 | TikTok/Instagram 真机 dry-run（不在本图实施） |
| 18 | 退出码 10 的 `publish_attempted` 行有无（见 §6 契约表） | 调度 App 侧行为（不在本仓库） |
| 19 | 无（决议是「本轮不改」） | — |

### 3. 真机验收清单（本地模式强制；托管可选）

前置：`--no-publish` 已升级到 ARM 就绪（Q3，属 03/17 的前置改动）；显式 `--debug`（14 默认关）；本地账号 cookie 有效。

| # | 步骤 | 期望 |
|---|---|---|
| 1 | 视频正路：`sau xiaohongshu upload-video --account <a> --file <mp4> --title T --no-publish` | exit 0；日志含 ARM 就绪行；命中日志显示 `xhs-publish-btn`（首选 `debug`，非首选 `info`） |
| 2 | 图文正路：2 张图 `upload-note ... --no-publish` | exit 0；第 2 张经「+」瓦片/file chooser；逐张完成态与静默复检通过 |
| 3 | 定时正路：`--schedule <2h–14d>` | 到 ARM 就绪 exit 0；**不验证**定时是否生效（11/26 的已知缺口） |
| 4 | 注入①：移走账号文件 | exit 10；**无 `browser session ready` 日志**（证明未启浏览器） |
| 5 | 注入②：改坏 `galaxy_creator_session_id` 一个字符（字段在、未过期） | 启浏览器 → C1 判 `login` → exit 10；stderr **不含** `publish_attempted=true` |
| 6 | 注入③：假 mp4 | 页面出现 `div.fail` → 点击前 exit 1；stderr 不含 `publish_attempted=true` |
| 7 | 注入④（可选）：20MB PNG | 逐张完成态正常；60s 判据不误杀 |
| 8 | 一次真实发布（最小验收）：1 篇图文，不带 `--no-publish` | exit 0；URL 离开 `/publish/publish`；人工删除该笔记 |
| 9 | 托管（可选）：有账号时重复 1/2，并断言一条 `browser session ready` 日志 | 同本地；无账号则记「未验证」 |

验收证据：命令行尾部日志 + `--debug` 截图，结论写回 `spec.md` 的验收章节（不新建目录）。

### 4. 不测清单

- 平台风控策略、真实验证码页面、扫码登录、浏览器指纹、真实封禁率（外部黑箱，且需制造风险行为）。
- **断网/恢复**：落在 `9` 的「不可判定」语义里，且会向平台暴露异常请求序列（与 charter ① 冲突）；24 的探针已证行为，不重复。
- **改 URL / 改选择器注入**：属离线 fake 或人工探针，不是验收步骤。
- **真实发布后杀浏览器**模拟 `9`：制造真实「已发布但未知」，把人工核对成本塞给验收。
- humanize 的「像人」效果、迁移后封禁率下降：**仅推断**，不设断言（与 15:133 一致）。
- 调度 App 的节奏/熔断行为（18 的契约消费方，不在本仓库）。
- 托管真机：**可选**，无账号不阻塞。

### 5. 既有用例处置

| 文件 | 删 | 改 | 不动 |
|---|---|---|---|
| `tests/test_xiaohongshu_uploader.py` | `test_find_publish_failure_detects_community_rule_toast`、`test_find_publish_failure_ignores_rate_limit_toast`、`test_wait_publish_outcome_fails_fast_on_rejection`、`test_setup_returns_detail_when_cookie_invalid_without_handle` | `test_wait_publish_outcome_returns_success_on_success_url`（04 判据）、`test_video_fill_meta_*`（10 键盘动作）、`test_publish_deadline_raises_before_publish_click`（03 ARM） | 其余 8 条（UA、creator URL、validate、note 存在性、`apply_declarations` ×4、标题默认值） |
| `tests/test_mlx_xhs_kuaishou.py` | `LoginProbeTests` 的 4 条 xhs 用例（12 删 `is_logged_in`）、`test_login_markers_mid_upload_raise_login_required` 的 xhs 分支、`test_xhs_note_captcha_redirect_raises_login_required`（`/captcha/verify` 无任何取证） | 两条 `test_xhs_*_login_redirect_*` 各补本地模式用例（13 删门） | 全部 kuaishou 用例（15 不迁）、本地 golden launch/context 用例（19 不改） |
| `tests/test_adspower_cli.py` | — | `test_headed_maps_to_headless_false_and_default_is_true`（14 默认改 `False`） | 其余 |
| `tests/test_publish_timeout.py` | — | — | 既有 10 条；只**新增** clamp/耗尽用例 |
| 其它（`test_publish_gate` / `test_browser_session` / `test_multilogin_*` / 其余平台） | — | — | **零改动，作为回归基线** |

### 6. 契约镜像（`tests/test_xhs_exit_contract.py`）

表驱动，逐行：场景 → 抛出的异常/返回值 → 期望码 → stderr 断言。覆盖集合 `{0,1,2,9,10,11,130}`，meta 断言防止新增码漏测。

| 场景 | 抛出 | 码 | stderr |
|---|---|---|---|
| 发布成功 | return | 0 | 无错误行 |
| ARM 未就绪 / 预算耗尽（点击前） | `RuntimeError`（`budget.pre_click_error()`） | 1 | 文案含「尚未点击发布」 |
| 图文缺图 / 视频 `div.fail` | `RuntimeError` | 1 | — |
| 话题插错 / 多插 | `RuntimeError`（`reason=topic-mismatch|topic-multi-insert`） | 1 | — |
| Profile/CDP/双凭证 | `RuntimeError` | 1 | — |
| 用法错误 | `UsageError` | 2 | 先打 usage |
| FIRE 后异常 / OBSERVE 超时 | `PublishResultUnknownError` | 9 | 含「禁止自动重发」，**不含** `publish_attempted=true` |
| `login` 未派发 | `LoginRequiredError(reason="login", publish_attempted=False)` | 10 | 本地/托管句；**无** `publish_attempted=true` |
| `login` 已派发 | 同上 `True` | 10 | 含**恰好一行** `publish_attempted=true` |
| `verification` 未/已派发 | `reason="verification"` | 10 | 同上规则 |
| 限流 | `RateLimitedError` | 11 | — |
| `Ctrl-C` | `KeyboardInterrupt` 传播（`main` 不捕获） | 130（shell 呈现） | — |

### 7. 组织与运行

- 用例按决议分段：`class Decision03SubmitTests` … `Decision13ParityTests`，方法名 `test_03_<behavior>`；契约表单独文件。
- 运行：`python -m unittest tests.test_xiaohongshu_uploader tests.test_xhs_exit_contract tests.test_mlx_xhs_kuaishou tests.test_publish_timeout -v`；全量 `python -m unittest discover -s tests -t .`。仓库无 CI、无 pytest，不新增 runner。

### 8. 已知缺口（随 spec 记录）

- 07：验证页真实 path 未取证（`/website-login*` 未观察到）；「未知路径→`None`」是**保守但不完备**的判据。
- 11/26：定时设置结果不可观测；真机第 3 项只证明「能到 ARM」，不证明定时生效。
- 托管真机若跳过，则 13/14 的托管侧只剩离线断言（`mode`/`provider_label`/日志），文案与启动日志**未经真机**。
- `--no-publish` 升级到 ARM 是**前置改动**；若不实施，第 1–3 项退化为「填表完成」验收。
