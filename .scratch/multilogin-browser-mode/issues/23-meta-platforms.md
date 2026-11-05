# 23 — 平台迁移：Facebook / Facebook Page / Instagram

**What to build:** Meta 三个上传入口在 MLX 模式下可 `check` 与上传；`*_PROXY` 与本地 launch 假设被静默丢弃，出口 IP 由 Profile 决定。Instagram 的本地身份比对在 MLX 下跳过。

**Blocked by:** 17.

**Status:** ready-for-agent

- [ ] Facebook、Facebook Page、Instagram 的上传入口都支持 keyword-only `session`，MLX 分支只执行 `upload_in(session)`。
- [ ] 三个平台各自新增 `is_logged_in(context)`：明确未登录返回 False，网络/5xx/超时/结构异常抛异常；预算 15–30s。
- [ ] MLX 分支静默忽略 `channel="chrome"` 与各自代理配置（含 `--proxy` 传入的值）。
- [ ] Instagram MLX 下不读取 `.identity.json`、不做用户 ID 比对；会话建立后输出“账号一致性未校验”的 INFO。
- [ ] 三个平台的本地 `launch_kwargs` / `context_kwargs` / `init_script` 用 golden dict 锁定。
- [ ] `check` 返回 0 / 10 / 1 / 2；`upload-*` 返回 0 / 10 / 1，成功后 Stop 恰好一次。
- [ ] MLX 全程不读写 `cookies/*.json`，不调用 spec §6.2 的禁止 API。
- [ ] 新增登录检测、身份 reader 未被调用、禁止 API 的测试。
