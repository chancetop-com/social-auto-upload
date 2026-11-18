# 19: YouTube 登录检查与视频发布

Status: ready-for-agent

Blocked by: 08

批次：第二批 · [托管 Profile 默认共享规格](../spec.md)

## What to build

让 YouTube 登录检查和视频发布与同行共用 Profile，验证探针和视频发布只使用自己的页面，并回归 YouTube 本地模式。

| 平台 | 本单负责的托管入口 |
| --- | --- |
| YouTube | `check`、`upload-video` |

## Acceptance criteria

- [ ] 从正式 CLI 运行 YouTube 登录检查。检查在自己的临时页识别登录态，探针结束后临时页已关闭，同行的页面、导航位置和内容仍在。
- [ ] 从正式 CLI 运行 YouTube 视频发布，预置可编辑的同行草稿，核对本次命令打开、操作和关闭的页面。分别在成功与失败清理后验证同行仍可继续编辑。
- [ ] 在离线环境区分提交前失败、已提交、结果未知与登录失效。核对各动作既有的结果格式、退出码、适用的 `publish_attempted=true` 和提交次数，同行结果独立保留。
- [ ] 通过既有本地模式入口回归登录态来源、本地 Profile 生命周期、结果格式和退出码。
