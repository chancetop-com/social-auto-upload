# 19: YouTube 登录检查与视频发布

Status: resolved

Blocked by: 08

批次：第二批 · [托管 Profile 默认共享规格](../spec.md)

## What to build

让 YouTube 登录检查和视频发布与同行共用 Profile，验证探针和视频发布只使用自己的页面，并回归 YouTube 本地模式。

| 平台 | 本单负责的托管入口 |
| --- | --- |
| YouTube | `check`、`upload-video` |

## Acceptance criteria

- [x] 从正式 CLI 运行 YouTube 登录检查。检查在自己的临时页识别登录态，探针结束后临时页已关闭，同行的页面、导航位置和内容仍在。
- [x] 从正式 CLI 运行 YouTube 视频发布，预置可编辑的同行草稿，核对本次命令打开、操作和关闭的页面。分别在成功与失败清理后验证同行仍可继续编辑。
- [x] 在离线环境区分提交前失败、已提交、结果未知与登录失效。核对各动作既有的结果格式、退出码、适用的 `publish_attempted=true` 和提交次数，同行结果独立保留。
- [x] 通过既有本地模式入口回归登录态来源、本地 Profile 生命周期、结果格式和退出码。

## Comments

以安装后的 CLI 和本机 Chromium 运行 8 个离线场景。YouTube 在自己的页面检查登录、上传、核对结果和清理。并行的 Instagram 草稿在真实的客户端发布时间闸门等待，YouTube 退出后仍可编辑，随后独立生成成功结果。提交后被重定向到登录页时退出码为 10，并输出 `publish_attempted=true`；丢页或未收到确认时退出码为 9。现有 59 项本地与托管回归分别在 Python 3.10、3.11 和 3.12 上通过。验收提交为 `3b8ab0a`，测试见 `tests/test_shared_youtube_cli.py`。
