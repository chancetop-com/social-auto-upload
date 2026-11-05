# 15 — MLX 连接底座：errors / Launcher client / browser_session

**What to build:** 建立后续所有平台共用的唯一浏览器生命周期入口。完成后，本地模式与新 MLX 模式都能通过同一个上下文管理器取得 `BrowserSession`，但本票**不接 CLI、不改任何 `sau_commands`**；验证方式是离线单测。

**Blocked by:** 14.

**Status:** ready-for-agent

- [ ] 新增 `LoginRequiredError` 与 `UsageError` 两个错误类型，语义与 spec §4.2 的退出码 10 / 2 对应。
- [ ] Launcher 客户端支持 `probe` / `start` / `stop` / `status`：Bearer 鉴权、3s 版本探活、`verify=True`、固定 base URL、`headless_mode` 透传；`stop` 把 `profile already stopped` 视为成功；429 不在 CLI 内等待。
- [ ] 客户端允许注入 `http_get` 以便离线测试；token 只存在于实例内，不进入日志、异常文本或任何 dataclass。
- [ ] `browser_session` 的本地分支与现有各平台 `launch` / `new_context` / `set_init_script` / `context_setup` 行为等价，且不暴露 `owned` / `stop()` 给调用方。
- [ ] MLX 分支按 spec §5.4 执行：probe → start → `connect_over_cdp` 10s × 3 次（退避 2s→4s）→ 校验恰好 1 个 context → yield → `browser.close()`（只断开）→ finally `stop`；取消路径用 `asyncio.shield`。
- [ ] 失败路径符合 spec §5.5：Start 失败不 Stop 别人的 Profile；connect 失败时查一次 status 并入错误；Stop 失败且上传成功时只 warning、不覆盖原异常；`contexts` 数量异常时 fail-fast 并 Stop。
- [ ] 新增手写测试替身（FakePlaywright / Browser / Context），可控制 `contexts` 长度、close 顺序，触碰禁止 API 时直接失败。
- [ ] 单测覆盖：Start/Stop URL 与鉴权、超时、错误码、Stop 幂等、token 卫生、本地参数等价、MLX 生命周期、重试与退避、finally Stop、shield、Stop 失败 warning。
- [ ] 默认测试离线、不启浏览器、不访问网络；本票不修改 `sau_cli.py` 或 `sau_commands/`。
