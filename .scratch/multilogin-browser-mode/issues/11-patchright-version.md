# 11 — patchright 版本策略

Status: resolved
Type: grilling
Blocked by: 02
Assignee: —

## Question

调研发现当前 `patchright==1.58.2` 对应 Chromium 145，而 Mimic 最新 core 是 Chromium 156；1.58.2 还存在 CDP attach 的 `Frame was detached` 竞态（1.62.1 修复），且没有 `no_defaults` 参数。需要决定：

1. **维持 1.58.2**：不动依赖，接受版本落后与 attach 崩溃风险；MLX 分支做连接重试与“少开 tab”约束。
2. **最低升级到 `patchright>=1.62.1`**：修复 attach 崩溃，但仍是 Chromium 151，与 Mimic 156 差 5 个大版本。
3. **升级到 `patchright==1.64.1`**（推荐候选）：Chromium 156 对齐，支持 `connect_over_cdp(..., no_defaults=True)`，减少对 Mimic 默认 context 的覆盖。
4. **MLX 路径改用上游 `playwright==1.64.1`**：避开 patchright 的 CDP 补丁，但本地模式仍需 patchright，两个客户端并存/按模式 import；注意同一进程不要同时连接同一浏览器。
5. 升级的回归范围：本地模式所有平台是否要重跑？哪些平台最依赖 patchright 的防检测（抖音/小红书/快手）？
6. 升级是否阻塞 v1？能否先按 1.58.2 设计、在实施阶段作为独立 PR 升级？

## Context

- 研究 02 的版本表与风险分析：`.scratch/multilogin-browser-mode/research/02-patchright-mimic-cdp.md` 第 5 节。
- 当前依赖声明：`pyproject.toml` → `patchright==1.58.2`；`requirements.txt` 里是 `playwright==1.52.0`（历史遗留，两套并存）。
- 本机没有 MLX，版本兼容只能靠普通 Chrome 156 的实测推断。
- 升级会影响本地模式，属于“改变原有行为”的少数例外，需要明确批准。

## Answer

决策（2026-11-05，用户批准）：**升级到 `patchright==1.64.4`，精确固定。**

### 实测影响（2026-11-05，本地安装 1.58.2 与 1.64.4 对比）

| 项 | 1.58.2 | 1.64.4 |
|---|---|---|
| 内置 Chromium | 145.0.7632.6（rev 1208） | 156.0.8078.4（rev 1248） |
| `requires_python` | 3.9+ | 3.10+（项目要求 3.10–3.12，匹配） |
| `chromium.connect_over_cdp` | 无 `no_defaults` | 有 `no_defaults`、`artifacts_dir`；`timeout` 接受 `timedelta` |
| `browser.new_context` | — | 新增 `record_video_fps`、`focus_control`；`client_certificates` 类型放宽 |
| `context.storage_state` | — | 新增 `credentials`、`opfs` |
| `context.add_init_script` | 返回 `None` | 返回类型注解变化，但 `await context.add_init_script(...)` 用法不变 |

- 已逐个核对仓库中所有 `from patchright.async_api import ...` 的符号，1.64.4 全部存在。
- 本仓库使用的 `locator` / `get_by_*` / `wait_for_*` / `expect_*` / `evaluate` / `storage_state` / `new_context` / `grant_permissions` / `route` 均在，签名只增不改。
- 结论：**代码 API 破坏风险低；主要影响是运行时浏览器版本与 anti-detection 行为。**

### 决策

- `pyproject.toml`：`patchright==1.58.2` → `patchright==1.64.4`（精确 pin，不用 `>=`）；同步更新 `uv.lock`。
- `requirements.txt` 不动：它是旧的 Web/Flask 环境（`playwright==1.52.0`，本就没有 patchright），与 CLI 依赖不是同一套。
- 作为**独立提交**先落地（仓库是个人 fork，不走 PR 流程），不与 MLX 功能代码混在一起；不阻塞设计，但阻塞“实现完成”。
- 支持 Python 3.10–3.12（patchright 1.64 的下限 3.10 与项目一致）。

### 本地模式回归范围

**只做测试用例回归，不做真实账号的完整验证回归**（用户决定，2026-11-05）。

必须做：

1. `uv lock --upgrade-package patchright && uv sync`；
2. 重新执行 `patchright install chromium`（新 revision，旧浏览器不会自动替换；文档 `docs/install.md` / `docs/update.md` 已有该命令，补一句“升级依赖后需重跑”）；
3. 现有默认测试套件全绿（`python -m unittest discover -s tests`，离线、不启浏览器）；
4. 确认 `channel="chrome"` / `LOCAL_CHROME_PATH` 路径仍走系统 Chrome（静态检查即可，无需起浏览器）。

不做：

- 不执行真实账号的登录/上传冒烟；
- 不验证平台风控、验证码、指纹差异。

因此“patchright stealth 行为是否影响平台”属于**已知未验证风险**：由实际使用暴露；若出现平台级失败且无法快速定位，再按回滚条款处理。

### MLX 侧

- `connect_over_cdp(url, no_defaults=True)`：使用 1.64 的新参数，减少 Playwright 对 Mimic 默认 context 的覆盖（ticket 02）。
- 若 ticket 08 在真实 Mimic 上发现 `no_defaults=True` 导致 attach/行为异常，允许退回“不传该参数”；这不影响本 pin 决策。
- `Frame was detached` 竞态在 1.64 已修复；ticket 05 的 3 次连接重试**保留**作为冷启动兜底。

### 回滚

- 依赖回滚：恢复 `patchright==1.58.2` + `uv lock` + `patchright install chromium` 即可；除 `no_defaults=True` 外没有代码依赖 1.64 的新 API（`no_defaults` 在 1.58 不存在，回滚时需同步删掉该 kwarg）。
- 回滚触发条件：默认测试用例失败，或实际使用中出现平台级失败且无法在 1 天内定位。

### 对下游 ticket 的约束

- **ticket 09**：依赖清单写 `patchright==1.64.4`；部署/升级步骤包含重装 Chromium；MLX 时序写 `connect_over_cdp(..., no_defaults=True)`（可回退）。
- **ticket 08**：真机验证项加一条“`no_defaults=True` 下 attach 是否稳定”。
- **ticket 07**：`test_browser_session` 断言 `connect_over_cdp` 带 `no_defaults=True`；升级提交的回归清单按本文件执行。
