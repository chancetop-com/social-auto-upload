# 05 — AdsPower 模式的测试策略

Status: resolved
Type: grilling
Blocked by: 03, 04
Assignee: LukeChen

## Question

在没有真实 AdsPower 的当前机器上，定义能证明 AdsPower 模式正确、且不破坏本地/MLX 的测试矩阵。需要确认：

1. 测试层级：纯离线 `unittest`；不启动真实浏览器、不访问网络。
2. `AdsPowerClient` 单测：注入 `http_get` / `http_post`；覆盖 v1/v2 响应、`code != 0`、HTTP 非 200、超时、key 脱敏、URL 编码。
3. provider / browser session 测试：fake client + fake browser；断言调用顺序（probe → start → connect → yield → disconnect → stop）、失败路径、取消路径、`contexts` 数量异常。
4. 契约矩阵：激活/冲突、参数缺失、退出码、登录失效、禁止 cookie IO、禁止 `new_context`、禁止 `set_init_script`、token/key 不落日志。
5. 本地回归：现有 `tests/test_multilogin_*.py`、`tests/test_mlx_*.py`、`tests/test_browser_session.py` 全部通过；必要时更新 fake 接口但不变更断言语义。
6. 平台回归：各平台 CLI 的 golden dict / legacy 路径不变；AdsPower 模式只替换 session 来源。
7. opt-in 冒烟：`SAU_ADSPOWER_SMOKE=1` 默认跳过；只验证 start/connect/stop，不上传；依赖 ticket 09。
8. fixture：AdsPower v1/v2 响应样本放 `tests/fixtures/adspower/`，脱敏，不含真实 key/profile。
9. 测试命名与文件划分：新增 `tests/test_adspower_client.py`、`tests/test_browser_session_adspower.py`、`tests/test_adspower_cli.py`，还是并入现有 MLX 文件。
10. 覆盖率目标与“不测什么”（真实平台风控、验证码、代理指纹、发布结果）。
11. CI 约束：默认套件不得需要 AdsPower 桌面应用；不得依赖端口 50325。

## Context

- 参考 MLX 测试策略：`.scratch/multilogin-browser-mode/issues/07-test-strategy.md`。
- 现有测试资产：`tests/fakes.py`、`tests/test_browser_session.py`、`tests/test_multilogin_client.py`、`tests/test_mlx_*.py`。
- 机器事实：无 AdsPower、50325 未监听。

## Answer

决议日期：2026-11-09（HITL grilling，逐题确认）。一句话结论：**新增 4 个全离线 `unittest` 文件（client / browser-session / CLI / 平台守卫），不写冒烟；模板行为只测一次，AdsPower 只测组合与归一化；平台回归靠 8 个现有 `test_mlx_*` 零改动 + `managed` 真值表 + 禁 `mode == "multilogin"` 的静态守卫。**

### 0. 与前序 ticket 的对齐与一处修正

- 严格遵循 **03（provider 接缝）**、**04（生命周期/`StartIncompleteError`）**、**10（只做 V2）** 的已定契约。
- **修正 ticket 问题 2 的旧假设**：不再覆盖 "v1/v2 响应"。V1 已在 ticket 10 写入 Out of scope，client 测试**不测任何 V1 响应、不做 fallback 用例**。
- **不建冒烟文件**（本会话裁决）：真实 AdsPower 验证全部归 **09 — 真实 AdsPower smoke**，本 ticket 不引入 `SAU_ADSPOWER_SMOKE` 或 `@skipUnless` 冒烟测试。

### 1. 文件划分与层级（Q1 / Q9）

| 文件 | 状态 | 层级 / 覆盖 |
|---|---|---|
| `tests/test_adspower_client.py` | 新增 | 单元：`AdspowerClient` 的 V2 HTTP/JSON 契约、超时、key 脱敏、`RateLimitedError`、`StartIncompleteError` |
| `tests/test_adspower_browser_session.py` | 新增 | provider/session：`AdspowerProvider` 组合、ws 端点原样传递、`StartIncompleteError` 先 stop 再抛、日志与 `repr` 脱敏 |
| `tests/test_adspower_cli.py` | 新增 | CLI 契约：激活/冲突/base 校验/参数矩阵/退出码/脱敏 + 一条 douyin 端到端接线用例 |
| `tests/test_adspower_platform_contract.py` | 新增 | 迁移守卫：禁止上传器按 provider 名分支 |
| `tests/fixtures/adspower/*.json` | 新增 | 脱敏响应样本 |
| `tests/fakes.py` | 修改 | 追加 `FakeManagedProvider`、`FakeAdspowerClient`、`FakeHttp`；迁入共享 `FakeResponse` / `FakeHttpGet` |
| `tests/test_browser_session.py` | 修改 | 接缝迁移 + `managed` 真值表；本地用例不动 |
| `tests/test_multilogin_client.py` | 修改 | 只改为 import 共享 fake；断言不动 |
| `tests/test_multilogin_cli.py` | 修改 | 只加 429→`11` 与 re-export shim 断言；其余不动 |
| `tests/test_mlx_*.py`（8 个）、`test_douyin_upload_seam.py`、`test_tiktok_*` | 零改动 | 作为接缝回归基线 |

理由：按 provider 分文件，一个 provider 的契约失败不会污染另一个的测试报告；与 `test_multilogin_client.py` / `test_mlx_*` 命名对称。

### 2. client 层（Q2 / Q8）

**注入面**：

```python
class AdspowerClient:
    def __init__(
        self,
        key: str,
        base: str,
        http_get: Callable[..., Any] | None = None,
        http_post: Callable[..., Any] | None = None,
    ) -> None: ...
```

- `http_post` 是 ticket 03 未写全的必需补充：V2 的 `start` / `stop` 都是 POST，只注入 `http_get` 会迫使测试 patch 全局 `requests`。
- `base` 由 CLI 层校验并归一化后传入；client 不重复校验。
- 共享 fake 迁到 `tests/fakes.py`：`FakeResponse`、`FakeHttpGet`（或合并为 `FakeHttp`，按 `get_calls` / `post_calls` 记录）；`test_multilogin_client.py` 改 import，断言不变。

**每个请求的固定断言**：URL、method、`Authorization: Bearer <key>`、`timeout`（probe `3`，其余 `30`）；start/stop 额外断言 JSON body **完全等于**固定字典。

**用例矩阵**：

| 原语 | 正向 | 负向 |
|---|---|---|
| `probe` | 200 → 通过 | 连接拒绝/超时 → 固定“无法连接”文案（含 base，不含 key）；401/403 → 提示检查 `ADSPOWER_API_KEY`；500 → `HTTP 500`；**429 → `RateLimitedError`** |
| `start` | 200+`code:0`+非空 ws → 原样返回；headless → `"1"`/`"0"`；body 六字段精确（`last_opened_tabs/proxy_detection/delete_cache/cdp_mask` 固定值） | ws 缺失/空 → `StartIncompleteError`；非法 JSON / 缺 `code` → `StartIncompleteError`；`code != 0` → `RuntimeError`；401/403/404/500 → `RuntimeError`；**429 → `RateLimitedError`**；超时 → `RuntimeError` |
| `stop` | 200+`code:0`（**无 `data`**）→ 成功 | `code != 0` → `RuntimeError`；非 2xx → `RuntimeError`；429 → `RateLimitedError`；**不断言“已停止”特例**（09 未验证） |
| `status` | `Active` / `Inactive` → 对应字符串 | `data` 缺失/异常 → `"unknown"`；传输错误 → `RuntimeError` |

- 所有原语**只发一次请求**：断言 `len(http.calls) == 1`，锁住“client 不重试”（ticket 10 §7）。
- key 脱敏：`key not in str(exc)`、`repr(client) == "AdspowerClient(token=<redacted>)"`。
- `ADSPOWER_API_BASE` 合法性属于 CLI 层（`UsageError` → `2`），client 测试不重复。

**fixture**：`tests/fixtures/adspower/`，一文件一类响应：`start_ok.json`、`start_missing_ws.json`、`start_business_error.json`、`start_unauthorized.json`、`stop_ok.json`、`active_running.json`、`active_stopped.json`、`status_ok.json`、`malformed.json`。全部脱敏：固定假 key、假 profile UUID、`msg` 用官方文档原话。

### 3. provider / session 层（Q3）

- **通用模板只测一次**：`_managed_session` 的 probe→start→connect→yield→close→stop、3×10s/2s→4s、`contexts != 1` fail-fast、yield 抛异常仍 stop、取消 shield、stop 失败只 warning、start 失败不 stop、probe 失败不 start/stop，全部留在 `tests/test_browser_session.py`，替身为通用 `FakeManagedProvider`。
- **MLX 用例 1:1 迁移**：`multilogin=target` → `managed=MultiloginProvider(target, FakeMultiloginClient(...))`，删除 `_patch_client`，**其余断言逐字不动**。
- **`managed` 真值表**（新增）：

```python
for mode, expected in (("local", False), ("multilogin", True), ("adspower", True)):
    self.assertIs(BrowserSession(..., mode=mode).managed, expected)
```

- **AdsPower 专属用例只测组合与归一化**，不复制上述矩阵：
  - 真实 `AdspowerProvider(AdspowerTarget(pid), FakeAdspowerClient(...))`；
  - `start` 返回的 `ws://...` **原样**进入 `connect_over_cdp`（断言 `connect_calls[0]["url"] == ws_url`，不得拼成 http）；
  - `mode == "adspower"` 且 `session.managed is True`；
  - `StartIncompleteError`：事件顺序 `start → stop`，且异常原样抛出；其它 start 异常**不** stop；
  - 连接失败文案含 `adspower`、`profile_id`、endpoint `host:port`、尝试次数，不含 key；
  - 日志：INFO 只有 `profile_id` 与 `host:port`，完整 ws 路径不出现；`repr(client)` 脱敏。

`tests/fakes.py` 追加：

- `FakeManagedProvider`：`mode`、`profile_id`、`connect_url`、`probe_error`、`start_error`、`status_error`、`status_value`、`stop_error`、`events`、`calls`；
- `FakeAdspowerClient`：同步 `probe/start/stop/status`，固定 `ws_url`，可注入各阶段异常，记录 `events`。

### 4. CLI 契约矩阵（Q4）

`tests/test_adspower_cli.py` 镜像 `test_multilogin_cli.py` 的四类结构：

| 类 | 断言 |
|---|---|
| 激活 | 未设置 / 空串 / 纯空白 → 本地；非空 → AdsPower；`ADSPOWER_API_BASE` 单独存在**不激活** |
| 冲突 | 两个 key 同时非空 → `main()` 返回 `1`，文案精确；冲突优先于命令级拒绝；`--help` / 未知子命令仍走 argparse 原语义 |
| base | 合法（含末尾 `/` 归一化）→ 继续；非法（path/query/userinfo/无 host）→ `2`，且**不发任何请求**（fake http 调用数为 0） |
| 参数 | 缺 `--profile-id` → `2`；`--folder-id` 静默忽略；`--account` 可省略；`login` → `1`；`bilibili` → `1`；`verify`/`delete` 仍本地且要求 `--account`；`check` 未登录 → `10` |
| 注册范围 | 除 bilibili 外 `check`/`upload-*` 有 `--folder-id`/`--profile-id`；`login`/`verify`/`delete` 没有 |
| 退出码 | `0`/`1`/`2`/`9`/`10`/`11`；`RateLimitedError` → `11`；probe/start 的 429 → `11`；**stop 阶段 429 不改变已成功结果的 `0`** |
| 脱敏 | key 不出现在 stdout / stderr / 异常 / `repr` |

- **`130` 不测**：对齐 MLX 现状——`docs/CLI.md` 声明，`tests/` 无断言，取消路径由通用 `CancelledError` + shield 用例覆盖。
- **一条 douyin 端到端接线用例**：`ADSPOWER_API_KEY` + `FakePlaywright` + 注入的 provider，跑 `sau_cli.main(["douyin", "check", ...])`，断言走 `connect_over_cdp`、**不调 `launch` / `new_context` / `storage_state`**、不构造 cookie 文件。
- `sau_cli.main()` 的 `RateLimitedError` 分支必须排在 `except Exception` 之前，测试双向锁住（返回码 + 异常类型）。

**`tests/test_multilogin_cli.py` 只允许两处新增**：

1. 429 → `11` 用例（本 effort 唯一批准的 MLX 可观察行为变更）；
2. `sau_commands.multilogin` re-export shim 的符号清单（`multilogin_enabled`、`resolve_multilogin_target`、`add_multilogin_flags`、`resolve_account_label`、`require_local_account`、`reject_multilogin_login`、`reject_multilogin_platform`、`login_required_error`、`require_account`）。

其余断言逐字不动。

### 5. 本地与 MLX 回归（Q5）

**阶段 1（纯重构）允许的测试改动只有两类**：

- `tests/test_browser_session.py` 的 `multilogin=` → `managed=` 迁移与 `managed` 真值表；
- `tests/test_multilogin_client.py` 改为 import 共享 fake。

**必须零改动且全绿**：8 个 `test_mlx_*.py`、`test_douyin_upload_seam.py`、`test_tiktok_local_mode.py`、`test_tiktok_exit_codes.py`、`test_tiktok_note_cli.py`、`test_tiktok_settings.py`、`test_sau_browser_cli.py`。

理由（已核实）：平台测试直接构造 `BrowserSession(..., mode="multilogin")`，而上传器改造后只看 `session.managed`。`mode="multilogin"` 已经走同一条代码路径，因此平台测试**不需要**为 AdsPower 改任何一行；它们若变红，说明重构改变了可观察行为，应修生产代码而不是改断言。

**不新增平台级 golden dict**：本地参数基线已由现有 per-platform local 用例与 `test_browser_session.py` 的 `launch_kwargs` / `context_kwargs` 断言覆盖。

### 6. 平台回归与迁移守卫（Q6）

- **静态守卫**（`tests/test_adspower_platform_contract.py`）扫描 `uploader/` 与 `sau_commands/`，断言不存在按 provider 名分支：

```python
PATTERN = re.compile(r"""\.mode\s*[=!]=\s*["']multilogin["']""")
```

  - 必须同时匹配单双引号：现有 `uploader/meta_uploader/insgraph_uploader/main.py:446` 用的是单引号，是最容易漏改的一处。
  - 当前基线：**28 处**，全部在 `uploader/`（`sau_commands/` 为 0）。失败信息逐行列出 `path:line: content`。
  - 守卫锁的是“漏改即落回本地分支（调 `launch` / `new_context` / 写 cookie）”这一真实风险；现有平台测试用 `mode="multilogin"`，抓不到漏改。
- **不做** B 方案（8 个文件 × 约 20 个用例循环两种 mode）：证明的内容与“属性真值表 + 源码无残留”等价，却要改 28 处构造、运行时翻倍。MLX 的“每平台真跑”是因为平台逻辑各异，不是因为 provider 不同。
- 平台运行时的 AdsPower 覆盖由第 4 节那条 douyin 接线用例承担，其余平台由共享 `managed` 路径 + 守卫保证。

### 7. 冒烟（Q7）

- **不做 opt-in 冒烟文件**，不引入 `SAU_ADSPOWER_SMOKE`。
- 真实 AdsPower 的验证全部归 **09 — 真实 AdsPower smoke**；默认套件与默认验收都**不依赖**真实 AdsPower，与 MLX“不得把真实 MLX 作为默认验收前提”一致。

### 8. 覆盖率口径与不测什么（Q10）

- **不设覆盖率数字**。判定标准：每条契约至少一条正向 + 一条负向断言；`python -m unittest discover -s tests` 全绿即阻断合并。
- **明确不测**：
  - 各平台真实发布成功、平台风控、验证码/扫码/短信 2FA、地区跳转、Profile 指纹、代理出口 IP；
  - 真实 AdsPower 进程是否存在、V2 在旧客户端上的真实状态码、429 的真实形状、重复 stop 的真实响应、`contexts` 真实数量、冷启动耗时（全部归 09）；
  - AdsPower V1、无 key 安装、Firefox Profile、Profile 创建/代理管理/Cookie 导入导出；
  - `sau_backend.py`、`myUtils/`、Vue 前端；
  - 真实桌面应用 / 端口 50325 / 跨机 / Docker 拓扑。

### 9. CI 约束（Q11）

- 默认套件纯离线：不连接或监听 50325、不启动浏览器、不 import 时探测 AdsPower。
- 所有 HTTP 走注入的 `http_get`/`http_post`；所有 CDP 走 `FakePlaywright`。
- **不加全局网络护栏**（不在 `tests/__init__.py` patch `requests`）：对齐 MLX 现状——`tests/__init__.py` 为空，10 处 `MultiloginClient` 构造全部注入 `http_get`，靠注入纪律而非全局 patch。
- 不真睡：`asyncio.sleep` 用 `patch` 断言退避序列，测试运行时间不因新增用例显著增加。

### 10. 完成定义

- **阶段 1**：全量套件绿 + 守卫绿 + 平台/本地测试零断言改动。
- **阶段 2**：4 个新文件全绿 + `test_multilogin_cli.py` 的 429→11 与 shim 断言通过。

### 对下游 ticket 的约束

- **08（汇总规格）**：必须包含“测试矩阵”小节，逐条对应本文第 2–6 节；写明“不建冒烟、真实 AdsPower 归 09、V1 不测”；不得把真实 AdsPower 列为默认验收前提。
- **09（真实 smoke）**：是本 effort 唯一真机验证入口；至少覆盖 04/10 留存的 5 个未知项（已运行 start 返回形状、重复 stop、429 形状、`contexts` 数量、冷启动超时残留）。
- **03 / 04 实现**：必须保留 `AdspowerClient(key, base, http_get=, http_post=)`、`FakeAdspowerClient`、`BrowserSession.managed`、`StartIncompleteError` 四个供测试使用的名字。
- **07（平台清单）**：迁移表以**实测 28 处** `session.mode == "multilogin"` 为准（全部在 `uploader/`），并标注 `insgraph_uploader/main.py:446` 的单引号写法。
