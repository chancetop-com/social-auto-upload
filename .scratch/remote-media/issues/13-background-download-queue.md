# 13: 后台入队并立即返回

Status: ready-for-agent
Blocked by: 11

**What to build:** 调度 App 省略 `--wait` 时，在后台进程接手后即可退出。随后从另一个 CLI 进程传同一 ID 和 URL，可取得正在下载的那份素材。

规格见[网络素材预下载与上传 CLI 规格](../spec.md)。

## 验收条件

- [ ] 让本机源站暂缓发送正文。请求持久化且独立后台进程接手后，默认命令已退出 `0`，stdout 为单个含 `task_id` 和 `status="accepted"` 的 JSON 对象。放行源站后，即使原调用方已退出，下载仍能完成。
- [ ] 整组输入通过校验才入队。缺少 ID 或 URL、直链无效或并发配置无效时退出 `2`，错误仅写 stderr。队列写入或后台启动失败时退出 `1`，结果含 `task_id`、`status="failed"`、顶层 `reason="queue_unavailable"` 和 `items=[]`。
- [ ] 在下载仍进行时用同一 ID 和 URL 再执行 `--wait`，源站观察到一次传输，两条命令共用其结果。队列清空后后台进程自行退出。
- [ ] 同一资源根目录下的多个命令和 ID 共用 `SAU_DOWNLOAD_CONCURRENCY` 上限。用本机并行请求验证默认值 `1` 和更大的正整数。后台进程启动时读取该值，修改在下次启动时生效。
