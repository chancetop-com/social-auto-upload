# 09: Instagram 与 TikTok 并行准备视频和图文

Status: ready-for-agent

Blocked by: 08

批次：第一批 · [托管 Profile 默认共享规格](../spec.md)

## What to build

在同一托管 Profile 里运行两条发布命令，每个平台在自己的编辑器准备草稿，按自己的时间和结果结束。

| 平台 | 本单负责的托管入口 |
| --- | --- |
| Instagram、TikTok | `upload-video`、`upload-note` |

## Acceptance criteria

- [ ] 离线逐项运行四个发布入口，从启动、登录探测、准备到清理全程占用本平台。探针和预览页关闭后，发布命令仍持有资格。成功及失败退出均保留同行草稿的内容、位置和可编辑性。
- [ ] 用本机 Chromium 双连接让 Instagram 正在编辑时启动 TikTok，设置相同 URL 或改变标签顺序。TikTok 始终使用自己新开的页面；在提交前丢页时本次报错，Instagram 草稿仍可继续编辑。
- [ ] 让一条命令进入客户端发布闸门，另一条先完成或失败。核对两份不同的草稿、各自发起提交的时间与次数，以及先退出者只清理自己的页面。
- [ ] 离线覆盖准备完成、提交前失败、已提交、提交后结果未知及登录失效。分别核对适用的结果文件、退出码和 `publish_attempted=true`，提交后丢页不再点击发布。
