# 30 — 会话可观测性：忽略参数 WARNING 与启动日志

**What to build:** 一次托管模式运行结束时，用户能从日志里回答三个问题：这次用的是哪个 provider、浏览器是有头还是无头、哪些本地浏览器参数被静默丢掉了。每个 run 恰好一条 WARNING（只在真有参数被丢时）和恰好一条启动日志。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] `provider_label(mode)` 公开可用，三种模式各自返回正确标签（AdsPower 不得显示为 Multilogin）
- [ ] 托管模式下一次 run 恰好一条 WARNING；只报**键名**，不报值；空值（`False`/`{}`/`None`）不计入；本地模式零条
- [ ] WARNING 文案固定中文，并说明"Profile 负责指纹与界面语言，语言/UA/时区请在 Profile 内设置"
- [ ] 两种模式各恰好一条启动日志，字段齐全：`mode`、`headless`（headed/headless）、`identity`（账号文件或 profile id）、`ignored`（键名列表或 `-`）；托管附加 `folder_id`/`port`/`endpoint`
- [ ] 托管模式下 `--account` 不读、不校验、不参与显示标签；标签直接取 profile id，且若传入则计入 ignored
- [ ] 例外不变：`login`/`verify`/`delete` 仍必须 `--account`
- [ ] 现有 browser session 相关回归测试全绿；新增断言只锚定上面四条
