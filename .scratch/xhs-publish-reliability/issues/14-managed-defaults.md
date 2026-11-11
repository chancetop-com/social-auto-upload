# 14 — 托管模式默认值与参数可见性

Status: open
Type: grilling
Blocked by: —
Assignee: —

## Question

托管模式的默认值和被丢弃的参数都不可观测。需要确认：

1. **`headless` 缺省**：`parser.set_defaults(headless=True)`（`arguments.py:90`）硬编码，直接透传到 provider（Multilogin `headless_mode=true` / AdsPower `headless=1`）。改为按模式解析（托管默认有头、本地用 `conf.LOCAL_CHROME_HEADLESS`）？还是保留默认但打日志？`--headed` 的帮助文案是否改写（现在写的是 “Run with browser UI”）。
2. **`debug` 缺省**：CLI 默认 `False`（`--debug` store_true），`conf.DEBUG_MODE=True`，uploader dataclass 默认 `True`。三处口径如何统一（失败截图是否默认开）。
3. **参数静默丢弃**：托管分支忽略 `launch_kwargs` / `context_kwargs` / `init_script` / `context_setup`（`utils/browser_session.py:139-144`），16 个平台受影响。是 warn 一次、还是 raise？warn 的文案与去重策略。
4. **`--account` 在托管下只作 label**：是否需要显式提示或文档化。
5. **启动日志**：是否补 `headless=` 与 `ignored_params` 字段。
6. **登录能力**：托管下 `login` 被完全禁止，是否补“从 Profile 抓二维码返回”（可作为独立 ticket 或明确不做）。

产出：CLI/日志契约 + 对 16 个平台的影响判定 + 是否拆成独立改动的建议。
