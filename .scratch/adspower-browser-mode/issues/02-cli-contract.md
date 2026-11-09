# 02 — AdsPower 模式的 CLI 契约与激活规则

Status: resolved
Type: grilling
Blocked by: —
Assignee: LukeChen

## Question

把 AdsPower 模式的用户可见契约写成可直接实现的参数矩阵与退出码表。需要确认：

1. 激活：`ADSPOWER_API_KEY` 非空（strip 后）激活；空串/空白/未设置不激活；是否受 `ADSPOWER_API_BASE` 影响。
2. 冲突：`MLX_API_TOKEN` 与 `ADSPOWER_API_KEY` 同时非空 → 退出 `1`；文案怎么写；在何处判定（`sau_cli.main` 还是各命令 `run()`）。
3. Profile 参数：`--profile-id` 必填并映射 AdsPower `user_id`；`--folder-id` 不要求、传了忽略；缺 `--profile-id` → 退出 `2`。
4. `--account`：AdsPower 下可选，缺省标签 `profile_id`；本地模式仍必填；`verify` / `delete` 仍要求 `--account`。
5. `--headless` / `--headed` / `--debug`：与 MLX 相同的映射。
6. `login`：AdsPower 下拒绝并退出 `1`；`check` / `upload-*` 可用。
7. 退出码：`0` 成功、`1` 运行失败、`2` 用法错误、`10` Login required、`130` 用户中断；与 MLX 完全一致。
8. `check` 语义：`0` 已登录、`10` 需人工登录、`1` 运行失败、`2` 参数错误。
9. 错误文案：未设置 key、双模式冲突、缺 profile、API 不可达、key 无效、Profile 不存在、Profile 已运行等分别落在哪个退出码；哪些沿用 AdsPower 原始 `msg`。
10. 参数注册范围：哪些 action 注册 `--profile-id` / `--folder-id`；`login` 是否注册但不使用（与 MLX 对齐）。
11. 向后兼容：MLX 与本地模式的参数解析、默认值、错误码不变；现有 `tests/test_multilogin_cli.py` 应继续通过。
12. 明确“无 key 安装”不在范围，避免在 CLI 里留下半支持的开关。

## Context

- charter 见 [map.md](../map.md)。
- 现有 MLX 契约：`docs/CLI.md` 的「Multilogin X 模式」；`sau_commands/multilogin.py`。
- 需要产出参数矩阵（本地 / MLX / AdsPower 三列）与退出码表，供 ticket 03/08 引用。

### Research 01 的直接输入

- AdsPower 可能同时使用 HTTP 状态与 JSON `code` 表达错误，契约不能假设「业务错误永远 HTTP 200」。
- `ADSPOWER_API_BASE` 非法（带 path / query / userinfo）应作为用法错误退出 `2`；末尾 `/` 归一化。
- V2 的 `profile_id` 与 `--profile-id` 直接对齐；`--headless` 映射为字符串 `"1"` / `"0"`。
- 不暴露 `delete_cache` / `cdp_mask` / `launch_args` 等危险参数，由 provider 固定安全值。
- 需要裁决：Profile 不存在 → `1`（运行期）；stop 失败 → 只 warning，不改变已上传结果的退出码。

## Answer

决议日期：2026-11-09（HITL grilling）。以下内容可直接作为 ticket 03 / 08 的输入。

### 1. 激活

- 仅当 `ADSPOWER_API_KEY` 去除首尾空白后非空时激活 AdsPower 模式；未设置、空串、纯空白都不激活。
- `ADSPOWER_API_BASE` **不参与激活**；它单独存在时不改变模式、不告警。默认地址 `http://127.0.0.1:50325`。
- 实际使用的 key 是 strip 后的值；key 只存在于 client 实例，不写入 argv、日志、异常文本或 `repr`。
- 不新增任何 provider 选择 flag（如 `--browser-provider`）；模式完全由环境变量决定。
- 无 key 的 AdsPower 安装不在范围：CLI 不做端口探测、不警告，静默按本地 / MLX 原逻辑运行。

### 2. 双模式冲突

- `MLX_API_TOKEN.strip()` 与 `ADSPOWER_API_KEY.strip()` 同时非空 → 抛 `RuntimeError` → 退出 `1`（不是用法错误 `2`）。
- 判定位置：`sau_cli.main()` 内，`parse_args()` 之后、`dispatch()` 之前，位于现有 `try` 块中。
- 因此在 `--help`、未知子命令、缺必填参数时仍保持 argparse 原语义；冲突优先于 `login` 拒绝等命令级判断。
- 固定文案：`MLX_API_TOKEN 与 ADSPOWER_API_KEY 不能同时设置；请只保留一个。`
- 直接调用 `sau_commands.<platform>.run()` 的内部调用方不经过该检查；CLI 契约只覆盖 `sau` 入口。

### 3. `ADSPOWER_API_BASE` 校验

- 仅在 AdsPower 激活后、发第一个请求前解析。
- 合法：`http` / `https`，必须有 host，端口可选，禁止 userinfo、path、query、fragment；末尾 `/` 归一化去掉。
- 非法 → `UsageError` → 退出 `2`；合法但连不上 → 运行期退出 `1`（429 见第 5 节）。
- 默认值 `http://127.0.0.1:50325`；允许覆盖为 `http://local.adspower.net:50325` 等官方地址。

### 4. 参数矩阵

| 参数 / 行为 | 本地模式 | MLX 模式 | AdsPower 模式 |
| --- | --- | --- | --- |
| `--account` | login/check/upload-* 必填；verify/delete 必填 | 可选；无身份/cookie/输出语义 | 可选；无身份/cookie/输出语义（与 MLX 一致） |
| `--folder-id` | 静默忽略 | 必填 | 注册但静默忽略；传值不报错、不告警 |
| `--profile-id` | 静默忽略 | 必填 | 必填；strip 后映射 AdsPower `user_id`（V2 `profile_id`） |
| 缺 `--profile-id` / `--folder-id` | 不适用 | 退出 `2` | 只对 `--profile-id` 退出 `2` |
| `--headless` | 默认 True | 默认 True，传给 start | 默认 True，传给 start（V2 编码 `"1"/"0"`） |
| `--headed` | 覆盖为 False | 覆盖为 False | 覆盖为 False |
| `--debug` | uploader 行为 | uploader 行为 | uploader 行为；不传给 AdsPower |
| `login` | 允许 | 拒绝，退出 `1` | 拒绝，退出 `1` |
| `verify` / `delete` | 本地执行 | 本地执行 | 本地执行 |
| `check` 未登录 | 打印 `invalid`，退出 `1` | 退出 `10` | 退出 `10` |
| Bilibili | 允许 | 拒绝，退出 `1` | 拒绝，退出 `1` |

- `--profile-id` 只校验 strip 后非空；不猜 `user_id` 格式。Profile 不存在、被占用、内核未就绪等交给服务端，退出 `1`。
- `--account` 纯空白不做特殊处理：它没有可观察作用，不产生身份判断，也不改变 cookie 路径。
- 共享旗标的 help 改成中性文案；`--profile-id` 标注“MLX / AdsPower 模式必填”，`--folder-id` 标注“MLX 模式必填；AdsPower 模式忽略”。
- 注册范围与 MLX 逐 action 对齐：除 `bilibili` 外所有 `check` 与 `upload-*` 注册；`login`、`verify`、`delete`、`article` 不注册。
- AdsPower 激活时 `sau <p> login` 进入 `run()` 后拒绝并退出 `1`；若显式传 `--profile-id`，argparse 退出 `2`（与 MLX 一致）。
- 不打印模式 banner；`check` 成功只输出 `valid`，保持 stdout 可解析。

### 5. 退出码

全量继承 MLX，并新增一个双方统一的限流码：

| 码 | 含义 | 典型场景 |
| --- | --- | --- |
| `0` | 成功 | 上传已提交；check 已登录；stop 失败但主操作成功（仅 warning） |
| `1` | 运行失败 | API 不可达、key 无效、Profile 不存在/被占用、CDP 连不上、上传失败、网络错误、发布选项回读不一致 |
| `2` | 用法错误 | 缺 `--profile-id`、`ADSPOWER_API_BASE` 非法、本地缺 `--account`、未知子命令 |
| `9` | 发布结果未知 | 发布点击已发出但未观察到成功页；禁止自动重发 |
| `10` | 需要登录 | 登录页、登录表单、验证码、2FA |
| `11` | 请求过于频繁（429） | MLX Launcher 或 AdsPower Local API 返回 HTTP 429；由调度层退避重试 |
| `130` | 用户中断 | `Ctrl-C`；不捕获，由 SIGINT 自然产生 |

- `11` 是 **MLX 与 AdsPower 共用**的新契约；这是本 effort 对 MLX 的一次已批准行为变更（原 `429 → 1`，现 `429 → 11`），必须在 map 的 charter 与 `docs/CLI.md` 同步记录。
- 实现上新增 `RateLimitedError`（`utils/errors.py`），两个 client 在 HTTP 429 时抛出；`sau_cli.main()` 统一映射为 `11`。CLI 不 sleep、不自动重试。
- 若上传/check 已成功，仅 stop 阶段遇到 429：仍按 stop 失败处理，只 warning，保持原退出码（通常 `0`）。
- 若 HTTP 200 但业务 `code` 表示限流，research 01 尚未确认；先以 HTTP 429 为判据，后续有官方 code 再扩展。
- Profile 已运行**不做预检**（与 MLX 一致）：直接 start；服务端拒绝 → `1`（429 则 `11`）；start 成功即视为本次会话拥有，结束时 stop。并发同 Profile 由调度层保证。

### 6. 错误文案结构

与 MLX 同构，AdsPower 额外带业务 `code`：

- 通用：`<动作>失败：HTTP <status>；code=<code>；msg=<msg>`；无 `msg` 时截取响应体前 500 字符。
- 连不上：固定文案，提示检查 AdsPower 桌面应用、Local API 开关、同机部署与端口。
- 401/403：`1`，提示检查 `ADSPOWER_API_KEY` 与账号 Local API 权限。
- 429：`11`，文案点明“请求过于频繁”，不重试。
- Profile 不存在 / 被占用 / 内核未就绪：`1`，保留原始 `msg`。
- `ADSPOWER_API_BASE` 非法：`2`，属于用法错误，不发网络请求。

固定模板建议：

- 缺 Profile：`AdsPower 模式需要提供 --profile-id。`
- 双模式冲突：`MLX_API_TOKEN 与 ADSPOWER_API_KEY 不能同时设置；请只保留一个。`
- login 拒绝：`AdsPower 模式不支持 CLI 登录；请在 AdsPower 中登录 Profile {profile} 后重试。`
- 平台拒绝：`AdsPower 模式不支持 {platform}；请在本地模式（不设置 ADSPOWER_API_KEY）下重试。`
- 连不上：`无法连接 AdsPower Local API（{base}）。\n请确认：1) AdsPower 桌面应用已启动；2) 本地 API 已开启；3) CLI 与 AdsPower 在同一台机器且端口未被占用。`

### 7. 兼容与测试义务

- 本地模式与 MLX 的参数解析、默认值、错误码保持不变；**唯一例外**是 429 从 `1` 改为 `11`（已批准）。
- 现有 `tests/test_multilogin_cli.py` 必须继续通过；新增测试至少覆盖：激活矩阵、双模式冲突、base 合法性、缺 Profile、folder 忽略、login 拒绝、注册范围、退出码 11、token 不出现在输出。
- 文档与术语更新归 ticket 06；测试层级与矩阵归 ticket 05；provider 接口与模块落点归 ticket 03。

### 8. 明确不在本 ticket

- Profile 生命周期细节（start 失败是否 stop、CDP 重试、取消时的 stop、active 是否用于诊断）：ticket 04。
- 是否使用 V1/V2 端点：ticket 10。
- 结果标签的真实落地：ticket 04 若需要再裁决。
