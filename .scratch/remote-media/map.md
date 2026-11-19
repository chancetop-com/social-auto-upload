# 网络素材预下载与上传

Label: wayfinder:map

## Destination

形成可交给实现者的 CLI 规格。调度 App 收到 post 任务后调用 CLI 预下载 HTTP(S) 媒体直链（含签名链接），可选择入队即返回或等待文件就绪。发布时传本地路径或原 URL，CLI 取得完整本地文件后交给现有上传流程。

## Notes

- 用户已确认覆盖各平台现有的 `upload-video --file`、`upload-note --images` 和已提供的 `--thumbnail`。同一图文可混用本地路径和直链，图片的输入顺序就是上传顺序。[现有 CLI](../../docs/CLI.md)
- 预下载通过参数选择返回时机。入队即返回时，返回成功仅表示下载请求已被接受。等待完成时，成功返回可用的本地路径。调度 App 随后单独调用发布命令。[素材预下载](../../GLOSSARY.md#素材预下载)
- 调度 App 中途打断预下载后，可以用相同的 `--task-id` 和原 URL 发起发布。CLI 在该资源目录内查找完整文件或可用断点，整组素材就绪后才交给上传器。
- 下载中断后，只有源站对同一版本的文件返回与本地断点匹配的字节范围时，才追加到未完成文件。若源站返回整份文件，则从头写盘。[HTTP 范围请求](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.5)
- 从网络读取到本地写盘须全程分块，包括首次下载、续传和文件校验。单个大文件的大小可以超过可用内存；每个活动下载仅保留固定大小的缓冲，逐块写入文件。
- 按 Wayfinder 建图。选型查官方文档和源码，结合项目支持的 Python 版本及依赖；行为决策用 grilling 和 domain-modeling 与调用方确认。[项目依赖](../../pyproject.toml)

## Decisions so far

- [哪些下载库能让中断的媒体直链下载可靠续传](issues/01-download-library.md) — 标准库可行，首选复用现有 Requests；固定大小分块写盘已在两个文件大小上验证，跨进程恢复需要保存并校验断点。
- [同一 URL 的本地副本什么时候可以复用](issues/02-local-copy.md) — 预下载必填 `--task-id`。发布可复用指定 ID 下的相同 URL，或省略 ID，在同一资源根目录下生成一次性 ID 子目录，结束时删除。
- [哪些本地素材可以清理，由谁触发](issues/06-retention.md) — 带 `--task-id` 的 post 确认发布成功后，CLI 删除整个对应子目录；失败、结果未知或仅验证时保留。
- [入队返回后由谁下载，发布命令怎样接手](issues/05-download-queue.md) — 同一资源根目录共用后台下载队列，默认并发为 `1`。发布优先取材，确认成功后取消同一 ID 的剩余下载并清理。
- [预下载命令怎样返回入队结果或本地路径](issues/03-predownload-cli.md) — `sau media predownload` 默认返回入队回执，加 `--wait` 则按输入顺序返回每项的本地路径或失败原因。
- [素材下载中断后怎样恢复并报告结果](issues/04-interrupted-upload.md) — 发布取材遇到首个必需素材下载失败就报错并退出 `1`。无论是否传 `--task-id`，15 分钟发布预算都从整组素材就绪、进入平台上传流程时开始。
- [是否按任务目录的最后修改时间回收闲置七天的素材](issues/09-idle-task-directories.md) — 调度 App 每天无参数调用 `sau media cleanup`，回收无人使用且目录 `mtime` 已满七天的任务目录。
- [如何按任务 ID 直接删除本地素材](issues/10-delete-task-resources.md) — `sau media delete` 必填 `--task-id`，带 `--url` 删除单项，省略则删除整个任务目录。发布占用时两种删除都退出 `1`。
- [素材链接或内容变化时怎样刷新](issues/07-refresh-source.md) — 同一任务、同一 URL 复用完整文件，更新内容时先删后取。首次使用新签名 URL 时从头下载。

## Not yet specified

<!-- 暂无尚待明确为决策单的问题。 -->

## Out of scope

首版的远程来源限于直接返回媒体文件的 HTTP(S) 链接。解析社交平台分享页不在这次范围内。

从本地向发布平台上传时的断点续传属于平台上传流程，超出本次范围。

[调度 App 隔日重跑时应怎样选择下一条命令](issues/08-next-day-retry.md) — 重跑时机和命令选择属于外部调度 App，本仓库负责 CLI 的输入、行为和返回结果。
