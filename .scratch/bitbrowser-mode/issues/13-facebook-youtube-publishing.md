# 13: Facebook、Facebook Page 和 YouTube 完成受控发布

Status: ready-for-agent
Resolution: completed
Blocked by: 07

## What to build

对没有发布前停止开关的五个入口，调度方能从受控页面验证正常提交，并在发布动作已经派发后区分结果未知、登录失效和已确认成功。

## Acceptance criteria

- [ ] 从正式 `sau` 入口分别运行 Facebook 个人和 Facebook Page 的 `upload-video`、`upload-note`，以及 YouTube 的 `upload-video`。使用模拟比特浏览器 Local API 和受控平台页面，按现有参数走完整发布流程。
- [ ] 逐项核对 API 收到的窗口 ID、发布目标、新页面的归属、stdout、stderr 和平台结果。五条成功路径各自恰好提交一次，均退出 `0`。
- [ ] 发布动作已派发后注入断线或无法确认提交结果，命令退出 `9`，无自动重发。调用方可按作品核对后再决定是否重跑。
- [ ] 在派发前及派发后分别模拟平台要求登录或人机验证，均退出 `10`。只有派发后的 `10` 在 stderr 多出独立一行 `publish_attempted=true`。另让退出清理失败，确认已取得的 `9` 或 `10` 及相应信号仍可被调用方读取。

[比特浏览器托管模式规格](../spec.md) · [发布失败契约](04-failure-contract.md)

## Comments

已完成并合并到 `feat/bitbrowser-managed-mode`（最终集成 HEAD `6b5d490`）。离线契约证据：`tests/test_bitbrowser_publishing.py`。真机验收由 14 独立跟踪。
