# 08: 七个平台都能检查登录态并报告失败原因

Status: ready-for-agent
Blocked by: 07

## What to build

调度方对每个平台使用同一个 `check` 约定，并能根据退出码和脱敏诊断决定是修正连接、安排人工处理，还是退避重试。

## Acceptance criteria

- [ ] 逐项从正式 CLI 运行大陆版小红书、Rednote、TikTok、Instagram、Facebook 个人、Facebook Page、YouTube 的 `check`。模拟 Local API 收到所选窗口 ID，各平台在该 Profile 自己的新页读取登录态。七项成功结果均为 stdout 仅有 `valid`，退出 `0`。
- [ ] 在受控页面分别模拟平台要求登录和人机验证，退出 `10`，保留各自的原因，stderr 没有 `publish_attempted=true` 行。探测超时、站点 5xx 或页面结构异常退出 `1`。
- [ ] 模拟本机服务不可达、Token 被拒、窗口不存在和发布前 CDP 连接失败。命令退出 `1`，诊断指出失败操作和已知原因，输出已脱敏。
- [ ] 分别让探测、查询和启动返回 HTTP 429，命令退出 `11`，无自动重试。HTTP 200 且 `success=false`（包括“请求频繁”文案），以及无法识别的业务响应均退出 `1`。
- [ ] 按实际操作检验客户端能力。对运行中窗口的端口查询分别返回 HTTP 404 和超时，诊断可区分两者，均在开页前退出 `1` 并保留窗口。具备所需能力但缺少已打开窗口列表或 `opened` 筛选时仍可检查。无需探测版本或回退到旧接口。

[比特浏览器托管模式规格](../spec.md) · [失败契约](04-failure-contract.md)
