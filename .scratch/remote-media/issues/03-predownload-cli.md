# 预下载命令怎样返回入队结果或本地路径

Type: grilling
Label: wayfinder:grilling
Status: resolved
Assignee: chancetio (Codex)
Blocked by: 05

## Question

独立预下载命令的名字、输入、输出和退出状态是什么？用户已确定由参数选择入队即返回或等待下载完成。默认采用哪一种？入队成功返回什么，调度 App 如何得知后续的完成或失败？等待完成时如何按输入顺序返回本地路径，一组素材中仅部分成功时怎样报告？

等待期间若收到“任务已清理”，通过哪些输出字段和退出状态告知调度 App？并发数从哪里配置，无效值如何反馈？共享范围和清理行为见[入队返回后由谁下载，发布命令怎样接手](05-download-queue.md)。

预下载的两种返回模式都要求传 `--task-id`。命令示例应覆盖预下载和随后以同一 ID 发布的流程。发布省略 ID 时的临时下载规则见[同一 URL 的本地副本什么时候可以复用](02-local-copy.md)。

## Comments

- 已确认默认入队即返回，加 `--wait` 时等待本次请求的素材就绪。入队后，App 可以用同一 ID 和原 URL 直接发布，或再次调用预下载并加 `--wait` 取得结果；无需单独的状态查询命令。
- 已确认等待一组素材时，单项失败后继续其余下载。整组结束后按输入顺序为每项返回可用路径或失败原因；只要有一项失败，命令退出 `1`。

## Answer

`sau media predownload --task-id ID --urls URL [URL ...] [--wait]` 接受一条或多条 HTTP(S) 媒体直链，包括签名链接。两种模式都必填资源目录 ID。CLI 先校验整组参数，再入队。同一 ID 内重复出现的完整 URL 共用一次下载。等待结果按输入位置一一对应，重复 URL 的每个位置都有一项。

默认在请求已持久化且后台下载进程已接手时返回。App 可以直接安排发布，也可以稍后以同一 ID 和原 URL 再次执行预下载并加 `--wait`，取得本地路径或失败原因。App 通过这两种调用取得后续结果，无需轮询。队列接手与断点复用遵循[入队返回后由谁下载，发布命令怎样接手](05-download-queue.md)。

### 调度 App 的调用示例

以下示例是拟实现的 CLI 规格。先提交两张图片。若 App 提前需要本地路径，可执行第二条命令。发布时可以直接执行第三条命令。

```sh
sau media predownload --task-id post-42 \
  --urls 'https://cdn.example.com/cover.jpg' 'https://cdn.example.com/detail.jpg'

sau media predownload --task-id post-42 --wait \
  --urls 'https://cdn.example.com/cover.jpg' 'https://cdn.example.com/detail.jpg'

sau tiktok upload-note --account demo --task-id post-42 \
  --images 'https://cdn.example.com/cover.jpg' 'https://cdn.example.com/detail.jpg'
```

### 输出与退出码

预下载命令将一次调用的结果作为单个 JSON 对象写入 stdout，日志和诊断写入 stderr。所有结果对象都带调用方传入的 `task_id`。

| 调用结果 | 退出码 | App 读到的结果 |
| --- | --- | --- |
| 默认模式下已入队 | `0` | `{"task_id":"post-42","status":"accepted"}`。此时文件可能仍在下载。 |
| 等待的素材全部就绪 | `0` | `status="ready"`，`items` 中每一项都有完整文件的绝对 `path`。 |
| 等待的素材有一项或多项失败 | `1` | 继续其余下载，整组结束后返回 `status="failed"`。有完整文件的项给出 `path`，失败的项给出 `reason`。 |
| 等待期间，App 按 URL 删除了本次请求中的一个素材 | `1` | 对应输入位置返回 `{"reason":"item_deleted"}`，继续等待其余项。整组结束时返回 `status="failed"` 及按输入顺序排列的 `items`。 |
| 等待期间，发布成功触发清理或调度 App 显式删除整个任务目录 | `1` | 结束等待并返回 `status="task_cleared"` 和 `items=[]`。目录里的旧路径已失效。 |
| 队列写入或后台进程启动失败 | `1` | `status="failed"`、顶层 `reason="queue_unavailable"`、`items=[]`。 |
| 参数或配置无效 | `2` | 入队前退出，诊断仅写 stderr。 |
| 用户按 Ctrl-C 中断 | `130` | App 按退出码处理中断，无需解析 JSON。 |

例如，示例中的第二张图下载失败时，等待命令退出 `1`，stdout 可返回以下对象。App 可按 `--urls` 的顺序定位失败项。

```json
{
  "task_id": "post-42",
  "status": "failed",
  "items": [
    {"path": "/srv/sau/downloads/post-42/cover.jpg"},
    {"reason": "HTTP 404"}
  ]
}
```

### 下载并发数

环境变量 `SAU_DOWNLOAD_CONCURRENCY` 接受正整数，未设置时取 `1`。无效值（如 `0`、负数或非整数）在入队前报错并退出 `2`。同一资源根目录下，预下载与发布取材共用正在运行的后台进程的上限。后台进程启动时读取该值，修改在下次启动后台进程时生效。
