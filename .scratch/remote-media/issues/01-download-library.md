# 哪些下载库能让中断的媒体直链下载可靠续传

Type: research
Label: wayfinder:research
Status: resolved
Assignee: chancetio (Codex)

## Question

在项目的 Python 版本和依赖约束下，哪些主流方案能用 HTTP(S) 媒体直链下载到本地，并在 CLI 退出后利用磁盘上的未完成文件续传？比较已有 HTTP 客户端、可嵌入的下载库和成熟下载工具。用一手资料区分库内置行为、调用方需要补的逻辑与服务端前提，特别检查服务器忽略 Range、远端文件发生变化和签名链接过期的情况。给出有依据的首选和适用条件。

标准库是否足够？比较大视频按块写盘时的内存占用，并说明下载并发数从默认的 `1` 调高后，哪些开销随并发数增长。

## Answer

建议复用项目已有的 Requests。Python 标准库同样能按固定大小读写；两者的跨进程续传都要由 CLI 保存未完成文件，并确认服务端仍在返回同一版本、从预期位置开始的字节。需要现成交付断点状态的工具时，aria2 可作为备选。

本机在并发为 1、读取块为 1 MiB 时测试了 16 MiB 和 128 MiB 两种文件。两个客户端各自中断进程后都能从 4 MiB 处继续并通过 SHA-256 校验。Requests 在两种大小下的 Python 分配峰值均为 2.05 MiB。测试条件、进程 RSS、库的差异及 HTTP 边界见[下载库比较与实测](../research/01-download-library.md)。

研究分支为本地 `research/remote-media-download-library`，调研快照为 `2898505`。
