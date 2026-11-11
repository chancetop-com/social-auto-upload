# 14 — 托管模式默认值与参数可见性

Status: resolved
Type: grilling
Blocked by: —
Assignee: wayfinder-session (opencode)

## Question

托管模式的默认值和被丢弃的参数都不可观测。需要确认：

1. **`headless` 缺省**：`parser.set_defaults(headless=True)`（`arguments.py:90`）硬编码，直接透传到 provider（Multilogin `headless_mode=true` / AdsPower `headless=1`）。改为按模式解析（托管默认有头、本地用 `conf.LOCAL_CHROME_HEADLESS`）？还是保留默认但打日志？`--headed` 的帮助文案是否改写（现在写的是 “Run with browser UI”）。
2. **`debug` 缺省**：CLI 默认 `False`（`--debug` store_true），`conf.DEBUG_MODE=True`，uploader dataclass 默认 `True`。三处口径如何统一（失败截图是否默认开）。
3. **参数静默丢弃**：托管分支忽略 `launch_kwargs` / `context_kwargs` / `init_script` / `context_setup`（`utils/browser_session.py:139-144`），16 个平台受影响。是 warn 一次、还是 raise？warn 的文案与去重策略。
4. **`--account` 在托管下只作 label**：是否需要显式提示或文档化。
5. **启动日志**：是否补 `headless=` 与 `ignored_params` 字段。
6. **登录能力**：托管下 `login` 被完全禁止，是否补“从 Profile 抓二维码返回”（可作为独立 ticket 或明确不做）。

产出：CLI/日志契约 + 对 16 个平台的影响判定 + 是否拆成独立改动的建议。

## Answer

决议 2026-11-11。置信度：**代码明确** / **注释声称** / **仅推断** / **需真机验证**。
排序依据始终是 charter ①降封禁风险 > ②可靠性 > ③整洁；下列每条都注明它靠哪一条站立。

### 1. `headless` 默认 = 有头（一条规则，不按模式分叉）

- `sau_commands/arguments.py:90` 的 `parser.set_defaults(headless=True)` 改为 **`False`**。本地与托管同一条默认，不再按模式解析。
- `--headless` 显式无头；`--headed` 保留（与默认等价，仅为兼容调度侧既有显式传参）。
- 本地**不再解析** `conf.LOCAL_CHROME_HEADLESS`（现状即未读，非回归）；该配置项只服务 uploader/examples 的直接调用，在 `docs/install.md` 标注作用域。
- 影响面：`add_runtime_flags` 的 **32 个命令**（16 平台的 login / check / upload 等）。
- 必须同步的文档（不改就会自相矛盾）：`docs/CLI.md:145-147`（三列都写“默认 True”）、`docs/CLI.md:251,258`（`check --headed` 示例与“直接映射”说明）、`docs/CLI.md:838-850`（“都不传就 headless=True”）。
- 置信度：默认值位置 **代码明确**；“有头比无头更不容易被判为脚本”**仅推断**（未做真机对照）。决议靠 ① 的保守取舍：托管模式的卖点是真 Profile + 真浏览器，没有理由默认把它藏起来；07 的验证页后续也要人工能看见。该推断即便不成立，本决定也不产生额外风险。

### 2. `debug` 默认 = 关，且删掉 `DEBUG_MODE`

- CLI `--debug` 的默认保持 **False**，并成为**唯一来源**。
- 删除 `conf.DEBUG_MODE`：`conf.example.py:7`、`docs/install.md:81`，以及 5 个 uploader 的 import 与 **12 处构造默认值**（`ks_uploader/main.py`×3、`tencent_uploader/main.py`×3、`douyin_uploader/main.py`×3、`xiaohongshu_uploader/main.py`×3、`youtube_uploader/main.py`×1）全部改 `False`。
- 事实（写在这里供实施核对）：`args.debug` 每次都被显式传给 uploader，**CLI 路径从未读过 `DEBUG_MODE`**，所以“在 conf 里开 debug”一直是假的；且上传器默认值本身不一致（`zhihu`/`dayu` = False，`alipay` = True）。
- 明确**不做**“默认开”：小红书失败截图位于 0.5s 重试循环内且无去重（`uploader/xiaohongshu_uploader/main.py:1199`、`1382`），默认开会写出成百上千张图。去重落地后再评估（已登记图谱 Not yet specified）。
- 置信度：**代码明确**。

### 3. 托管忽略的本地参数：每 run 一条 WARNING，不 raise

- 覆盖四类参数 + 一个 CLI 参数：`launch_kwargs`、`context_kwargs`、`init_script`、`context_setup`、`--account`（见 §4）。
- 只在**非空**时计入：`init_script=False`、`{}`、`None` 不报。
- 每次 run **一条**（session 每次启动只建一次，无需额外去重；将来出现多 session/run 再加 run 级标记）。
- 文案固定中文、**只报键名不报值**（UA / proxy 之类不进日志）：
  `托管模式忽略本地浏览器参数：launch_kwargs, context_kwargs, init_script；Profile 负责指纹与界面语言，语言/UA/时区请在 Profile 内设置`
- 不 raise 的理由：16 个 `browser_session` 调用平台里有 8 个至少传一项（小红书、Instagram、抖音、快手、YouTube、腾讯、微博、虎扑），其中 `channel` / `viewport` / `permissions=geolocation` 在托管下**本来就该丢**；raise 会把“本地调优”误判成错误。
- 已知后果登记（不是新决策）：Instagram 依赖 `locale=en-US` 而托管丢弃 → Profile 必须人工保持英文（`uploader/meta_uploader/insgraph_uploader/main.py:105-108` 注释已承认）；小红书 `locale=zh-CN` 被丢弃但 22 已证界面恒中文，无实际影响；虎扑的 UA/视口/stealth 由 Profile 承担。
- 置信度：丢弃事实 **代码明确**；“只有语言两项有真实后果”是由代码 + 注释推出的**仅推断**，未逐平台真机验证。

### 4. `--account` 在托管下无意义

- 托管下**不读、不校验、不参与任何标签**；`resolve_account_label`（`sau_commands/browser.py:234`）的托管分支改为直接返回 `profile_id`。
- 传了就进 §3 的 `ignored` 列表（同一行 warning），不单独告警——避免调度侧每 run 多一条噪音。
- `require_local_account`（`browser.py:247`）保持托管跳过；**例外不变**：`login` / `verify` / `delete` 是本地专属动作，托管凭证存在时仍必须 `--account`（`require_account`，`browser.py:254`）。
- 文档：`docs/CLI.md:140` 删掉“仅日志/结果标签”，改为“托管下忽略；身份由 `--profile-id` 决定”；`251` 的示例同步。
- 置信度：**代码明确**。

### 5. 启动日志：两种模式各一条，字段固定

- 位置：`browser_session`（`utils/browser_session.py:126` 本地分支 / `:204` 托管分支），两种模式都打：
  `browser session ready: mode=local|multilogin|adspower, headless=headed|headless, identity=account_file:<path>|profile:<id>, ignored=<keys|->`
- 托管保留既有细节（`folder_id` / `port` / `endpoint`）作为附加字段；本地新增整条（现在本地**一行都没有**）。
- 目的：① 改了默认值后，日志必须能证明这次到底是 headed（否则默认值改了等于不可观测）；② 13 的“模式一致性”排查需要本地侧有基线。
- 置信度：**代码明确**。

### 6. 托管 `login`：不做

- 维持 `reject_managed_login`（`sau_commands/browser.py:313`，exit 1），文案统一归 **13**（`managed_app_label`）。
- “从 Profile 抓二维码返回”属**能力补齐**，不服务 ①/②；由图谱 Not yet specified 移入 **Out of scope**。
- 置信度：**代码明确**。

### 对 16 个平台的影响判定

| 影响 | 范围 | 判定 |
|---|---|---|
| 默认开始有界面（Q1） | 全部 16 个 `browser_session` 平台 | 行为变更，需每平台一次 `check` 冒烟；托管窗口会出现在使用者桌面，这是本决定的已知代价 |
| 失败不再自动截图（Q2） | 全部平台 | 行为变更但仅影响取证；`--debug` 可恢复 |
| 忽略参数 WARNING（Q3） | 只在本平台传了非空参数时出现（8 个） | 纯新增，不影响发布 |
| 启动日志（Q5） | 全部平台 | 纯新增 |
| `--account` 语义（Q4） | 全部平台的托管分支 | 输出 label 从 `--account` 变 `profile_id`；调度侧若解析输出文本需核对 |

### 拆分建议（本票产出要求）

**拆 2 个改动**：

1. **「参数契约」**（行为变更）：Q1 headless 默认 + Q2 debug 默认与删 `DEBUG_MODE` + Q4 托管 `--account` + 文档表格。验证方式：16 平台各跑一次 `check`（本地 + 托管）。
2. **「session 可观测性」**（纯增量，可先落）：Q3 忽略参数 WARNING + Q5 启动日志。验证方式：单测断言“托管非空参数恰好一条 warning、本地零条”。

### 测试要点

- 默认值：`--headless` / `--headed` 都不传 → `headless is False`；`--headless` → True；`--headed` → False（`add_runtime_flags` 单测，覆盖共享默认）。
- 删除后无残留：`grep -rn "DEBUG_MODE" --include="*.py" .` 只剩 CHANGELOG 历史文本。
- session 层：托管 + 非空 `launch_kwargs`/`context_kwargs`/`init_script` → **恰好一条** warning 且只含键名；本地同参数 → 零 warning。
- 启动日志：两种模式各一条，含 `mode` / `headless` / `identity` / `ignored` 四字段。
- 回归点：`tests/test_sau_browser_cli.py`、`tests/test_multilogin_cli.py`、`tests/test_adspower_cli.py`、`tests/test_browser_session.py`、`tests/test_adspower_browser_session.py`。
