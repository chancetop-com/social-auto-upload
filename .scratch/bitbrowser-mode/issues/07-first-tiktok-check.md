# 07: 用窗口 ID 完成第一次 TikTok 登录检查

Status: ready-for-agent
Resolution: completed
Blocked by: None (can start immediately)

## What to build

运营者从比特浏览器桌面复制窗口 ID 后，可以在窗口关闭的情况下运行 TikTok `check`。CLI 打开对应的 Profile，复用其中的登录态，并在检查结束时归还窗口。沿用 AdsPower 的目标、HTTP 客户端和 Managed browser provider 分工，接入现有 Browser session。

## Acceptance criteria

- [ ] 从正式 `sau tiktok check` 入口连接模拟 Local API 和受控 TikTok 页面。验证请求带 `x-api-key`，按去除首尾空白的 `--profile-id` 打开一次，从 `data.ws` 连接唯一的现有上下文，在新页完成检查并按同一 ID 关闭一次。已登录时 stdout 仅有 `valid`，退出 `0`。
- [ ] `BITBROWSER_API_KEY`、`ADSPOWER_API_KEY`、`MLX_API_TOKEN` 各自去除首尾空白。三者全空走本地模式，单独设置任意一个选中对应提供方。任意两种或三种同时有效，在参数解析成功后、命令分发前退出 `1`，仅列出冲突变量名，桌面 API 请求数为零。
- [ ] `BITBROWSER_API_BASE` 仅在比特浏览器模式下生效，空白或未设使用 `http://127.0.0.1:54345`，合法覆盖地址实际收到请求。地址格式非法或窗口 ID 缺失、空白时退出 `2`，API 请求数为零。仅设置地址按原有模式处理。
- [ ] 按复制的字符串 ID 选择 Profile，不以展示序号、窗口名称、`--account` 或 `--folder-id` 查找。核对省略及传入后两项时的身份和结果标签。`--debug` 保留上传器语义。帮助、参数解析和既有本地专用命令遵循现有 CLI 契约。
- [ ] 冷启动覆盖显式 `--headed`、`--headless` 及省略开关时的 `LOCAL_CHROME_HEADLESS`（缺省有头）。有头请求只需 ID，无头请求另含 `args=["--headless"]` 和 `ignoreDefaultUrls=true`，省略 `newPageUrl`。记录本次请求的模式。
- [ ] 用比特浏览器样例验证 POST、JSON、健康检查和窗口业务响应。用可识别的测试 Token 检查 stdout、stderr、日志、异常、结果及对象的可打印表示，均无凭据值。

[比特浏览器托管模式规格](../spec.md) · [模式选择决定](02-activation.md)

## Comments

已完成并合并到 `feat/bitbrowser-managed-mode`（最终集成 HEAD `6b5d490`）。离线契约证据：`tests/test_bitbrowser_client.py`, `tests/test_bitbrowser_cli.py`, `tests/test_bitbrowser_browser_session.py`。真机验收由 14 独立跟踪。
