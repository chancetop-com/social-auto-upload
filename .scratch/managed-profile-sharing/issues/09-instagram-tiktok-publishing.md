# 09: Instagram 与 TikTok 并行准备视频和图文

Status: ready-for-agent
Resolution: completed

Blocked by: 08

批次：第一批 · [托管 Profile 默认共享规格](../spec.md)

## What to build

在同一托管 Profile 里运行两条发布命令，每个平台在自己的编辑器准备草稿，按自己的时间和结果结束。

| 平台 | 本单负责的托管入口 |
| --- | --- |
| Instagram、TikTok | `upload-video`、`upload-note` |

## Acceptance criteria

- [x] 离线逐项运行四个发布入口，从启动、登录探测、准备到清理全程占用本平台。探针和预览页关闭后，发布命令仍持有资格。成功及失败退出均保留同行草稿的内容、位置和可编辑性。
- [x] 用本机 Chromium 双连接让 Instagram 正在编辑时启动 TikTok，设置相同 URL 或改变标签顺序。TikTok 始终使用自己新开的页面；在提交前丢页时本次报错，Instagram 草稿仍可继续编辑。
- [x] 让一条命令进入客户端发布闸门，另一条先完成或失败。核对两份不同的草稿、各自发起提交的时间与次数，以及先退出者只清理自己的页面。
- [x] 离线覆盖准备完成、提交前失败、已提交、提交后结果未知及登录失效。分别核对适用的结果文件、退出码和 `publish_attempted=true`，提交后丢页不再点击发布。

## Comments

9 个离线 Chromium 场景从独立安装的 CLI 运行四个发布入口。两条命令准备不同的草稿，分别到达自己的发布时刻，各自只提交一次。两页 URL 相同、标签顺序变化或关闭 TikTok 编辑器时，Instagram 原稿仍可编辑。TikTok 在等待中丢页会立即退出并释放平台名额。提交后丢页返回 9；提交后跳到登录页返回 10 并输出 `publish_attempted=true`。最终定向验证通过 202 项与 126 个子用例，另有两次释放名额后重新进入的复验。完整平台回归通过 529 项和 245 个子用例。验收提交为 `c14be47`，场景见 `tests/test_shared_instagram_tiktok.py`。真实站点验收另记于 #14。
