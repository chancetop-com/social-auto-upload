# 12 — 身份绑定平台在 MLX 模式下的账号一致性

Status: resolved
Type: grilling
Blocked by: 03
Assignee: —

## Question

知乎、雪球、大鱼号、Instagram 的现有检测不只看“是否登录”，还会把页面上的用户 ID 与本地 `.identity.json` / 账号 JSON 比对，防止 cookie 与账号文件错配。MLX 模式没有 `--account`、也没有本地 cookie 文件，需要决定：

1. **只验证“已登录”**：Profile 本身就是账号身份，不再比对用户 ID。风险：调度 App 传错 profile_id 时无法发现。
2. **引入 Profile 元数据**：要求用户在 Multilogin Profile 的 name/notes 里写入账号标识，CLI 读取并与 `--account` 比对。需要约定格式（如 `account:douyin:creator-a`），并定义读取方式（MLX profile search/summary API）。
3. **MLX 模式仍要求 `--account`**，但只作为“期望账号 ID”传给平台检测，无法验证时只告警不失败。
4. **放弃这些平台的 MLX 支持**，保留本地模式。
5. 如果选 1：错误提示与日志如何标注“本次未校验账号一致性”？是否需要调度侧承担该风险？

## Context

- 研究 03 第 2.3 节：`read_zhihu_identity` / `read_xueqiu_identity` / `read_dayu_identity` / `instagram_identity` 都依赖本地绑定文件；MLX 无该文件。
- 现有实现：`uploader/zhihu_uploader/session.py:76`、`xueqiu_uploader/session.py:88`、`dayu_uploader/session.py:87`、`meta_uploader/insgraph_uploader/main.py:64-81`。
- 已确认：MLX 模式 `--account` 可省略；folder_id/profile_id 由调度 App 传入。
- 这一决策只影响“检测严格度”，不影响上传本身。

## Answer

决策（2026-11-05）：**方案 1 —— 只验证“已登录”，不校验账号身份。**

### 规则

- MLX 模式下，**Profile 就是账号身份**。CLI 只回答“这个 Profile 当前是否已登录”，不回答“这个 Profile 是不是调度 App 以为的那个账号”。
- `read_zhihu_identity` / `read_xueqiu_identity` / `read_dayu_identity` / `instagram_identity` 及其 `.identity.json` / 账号 JSON 逻辑**原样保留给本地模式**；MLX 分支**从不调用**，也不读取 Profile name/notes、不新增 MLX 元数据 API。
- `--account` 在 MLX 下仍然只是 **Account label**（日志/输出用），缺省 `profile_id`（ticket 06），不具备“期望账号”语义；不作为 `is_logged_in` 的入参。
- 不做“无法校验时告警”的软校验，避免把调度侧风险伪装成 CLI 能处理的问题。

### 日志与文案

MLX 会话建立后、登录检测前，用平台 loguru 打一行 INFO（console + `logs/<platform>.log`）：

```
账号一致性未校验：以 Multilogin Profile 为身份（profile_id=<id>），请调度侧确保 profile_id 与目标账号匹配。
```

- 只打一次，不改变 stdout 契约（`check` 仍只打印 `valid` / `invalid`）。
- 不是 warning、不影响退出码；避免每条任务都产生告警噪音。
- 错误路径不需要重复这句话；文档与部署前提负责说明。

### 风险归属

- **调度 App 承担**“profile_id 传错 → 发到别的账号”的风险；CLI 不提供任何补偿性校验。
- 该风险必须在 ticket 09 的“调度侧责任”小节写明，并在 `docs/` 的 MLX 使用说明里重复一次（知乎、雪球、大鱼号、Instagram 点名）。
- 未来若要加身份校验，另开 ticket：必须引入 `--expect-account` + Profile 元数据约定，不能复用本契约的 `--account`。

### 对下游 ticket 的约束

- **ticket 09**：平台表里四平台标注“MLX 仅校验登录态”；验收清单加一条“Profile A 的登录态可被 check 通过，CLI 不声称账号一致性”。
- **ticket 13**：TikTok 不涉及身份绑定，`is_logged_in` 同样只判登录态。
- **测试**：`test_mlx_platform_contract.py` 对四平台断言 identity reader 未被调用（`patch(..., side_effect=AssertionError)`），同时验证本地模式仍调用。
