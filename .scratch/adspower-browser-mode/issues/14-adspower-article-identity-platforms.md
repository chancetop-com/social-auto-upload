# 14 — AdsPower 模式文章/身份/Meta 平台端到端

Status: ready-for-agent
Type: task
Blocked by: 11, 12
Assignee: —

## What to build

验证并补齐 AdsPower 模式在文章、身份绑定与 Meta 平台上的行为，使其与 MLX 分支对齐：

- dayu / zhihu / xueqiu：Profile 即身份，不读 cookie 或 `.identity.json`，不做账号 ID 比对；dayu 不写 `timezone_id`；zhihu/xueqiu 跳过剪贴板权限。
- facebook / facebook-page / instagram：`--proxy` / 环境代理不转发，Profile 拥有出口 IP、指纹与身份；Instagram 不读 identity、不做 account-id 比对。
- `verify` / `delete` 在这些平台始终本地执行，仍要求 `--account`；AdsPower 激活不影响。
- `_log_identity_unverified` 按 provider 输出：MLX 保持原文案，AdsPower 使用中立/AdsPower 文案。
- bilibili 在 AdsPower 下 login/check/upload 均退出 `1`。
- 为上述 6 个平台新增 AdsPower 模式离线测试，并与 MLX golden 断言对照。

## Acceptance criteria

- [ ] dayu / zhihu / xueqiu / instagram 的 AdsPower 路径不调用 cookie/identity 读取函数。
- [ ] Meta 平台 AdsPower 路径不转发 proxy/launch kwargs，不调用 `new_context`/`set_init_script`/`grant_permissions`。
- [ ] 任何平台的 `verify`/`delete` 在 AdsPower 激活时仍走本地并要求 `--account`。
- [ ] 身份未校验日志在 MLX 下字节不变，在 AdsPower 下不宣称为 Multilogin。
- [ ] bilibili 在 AdsPower 下 `login/check/upload-video` 全部退出 `1`。
- [ ] 新增测试全绿，且不改动既有平台业务断言。

## Context

- 规格：§7.4（平台特有约束）、§8（登录检测与身份）、§4.1（verify/delete 本地）、§11.1。
- 设计裁决：ticket 06（术语）、ticket 07（身份绑定与代理事实）。
