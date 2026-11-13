# 03 — GoLogin 模式的 CLI 契约与激活细则

Status: open
Type: grilling
Blocked by: 01
Assignee: —

## Question

把 GoLogin 模式的用户可见契约写成参数矩阵，供实现直接照抄：

1. **激活与配置**
   - `GOLOGIN_API_TOKEN` 非空激活；`GOLOGIN_RUNTIME` 缺省/空 = 本地，`0` = 本地，`1` = 云端。
   - `GOLOGIN_RUNTIME` 出现非法值（`2`、`true`、`cloud`、纯空白）时：退出 `2`（用法错误）还是 `1`（运行失败）？在哪一层判定？
   - `GOLOGIN_RUNTIME` 单独存在但无 token：静默忽略并留在本地模式，还是报错？
   - 云端与本地是否各有一个 base URL 覆盖变量（如 `GOLOGIN_API_BASE` / `GOLOGIN_LOCAL_API_BASE`）；校验规则是否沿用 AdsPower 的「仅 http/https、无 userinfo/path/query」。
2. **Profile 参数**
   - 复用 `--profile-id` 还是新增 `--gologin-profile-id`；GoLogin 的 profile id 是 24 位 hex，是否需要格式校验。
   - `--folder-id` 在 GoLogin 下：忽略、报错，还是保留给未来。
   - 缺 `--profile-id` 的退出码与文案。
3. **`--account`**
   - GoLogin 下可选、缺省标签 = `profile_id`；是否与 MLX/AdsPower 完全一致。
   - `verify` / `delete` 仍要求 `--account`。
4. **`--headless`**
   - 本地运行时：是否直接透传 GoLogin 的 headless 开关。
   - 云端运行时：无意义时是拒绝（退出 `2`/`1`）还是静默忽略；若要静默忽略，是否进 `ignored=` 启动行。
5. **`login` / `check` / `upload-*`**
   - `login` 在 GoLogin 下拒绝并退出 `1`；`check` 语义与 MLX/AdsPower 对齐。
6. **冲突文案**
   - 三元冲突时点名哪几个变量；`DUAL_CREDENTIALS_MESSAGE` 是改名还是保留。
7. **向后兼容**
   - 本地、MLX、AdsPower 的参数解析、默认值、错误码不变；现有 `tests/test_multilogin_cli.py` / `tests/test_adspower_*.py` 继续通过。

## Context

- 激活与三方冲突已由 map 的 charter 定死；本 ticket 只解决剩余细则。
- 参照 `sau_commands/browser.py` 的现有结构与 `docs/CLI.md` 的托管模式章节。
