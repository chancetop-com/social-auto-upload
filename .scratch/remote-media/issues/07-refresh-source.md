# 素材链接或内容变化时怎样刷新

Type: grilling
Label: wayfinder:grilling
Status: resolved
Assignee: chancetio (Codex)
Blocked by: 02

## Question

同一资源目录内已经有某个 URL 的完整副本，发布时直接复用。若调用方知道该 URL 已换了内容，是否需要提供显式刷新？若签名在下载中途过期，调用方提交新 URL 后，怎样报告或处理旧链接留下的部分文件？

## Comments

- 已确认同一任务 ID、同一完整 URL 有完整文件就直接复用，即使源站已覆盖内容。需要重新获取时，调度 App 先调用 `sau media delete`，再重新下载。首版无需 `--refresh`。
- 已确认签名过期时，旧请求按实际下载错误报告（例如 HTTP 403）。同一任务 ID 首次收到新签名 URL 时从头下载，旧 URL 的断点留在任务目录，随目录清理。
- 调度 App 需要两种删除范围：删除指定任务的全部本地素材，或仅删除该任务中的一个素材，以便单独重新下载。

## Answer

同一任务 ID 和同一完整 URL 命中完整本地文件时，预下载和发布都直接复用，即使源站已经替换内容。调度 App 确知需要新版时，先按该 URL 删除，成功后再以原 URL 取材。首版无需 `--refresh`。例如，只更新一篇图文中的一张图可调用：

```sh
sau media delete --task-id post-42 --url "$url" &&
  sau media predownload --task-id post-42 --urls "$url" --wait
```

去掉删除命令的 `--url "$url"` 即删除整个任务目录。发布占用、取消下载和等待结果遵循[如何按任务 ID 直接删除本地素材](10-delete-task-resources.md)。

签名过期导致下载失败时，旧请求报告源站实际返回的错误，例如 HTTP 403。App 用同一任务 ID 提交新签名 URL 时，CLI 按完整 URL 查找素材。首次使用这个新地址时从头下载，旧链接的断点保留到 App 按旧 URL 删除该素材或任务目录被清理。[同一 URL 的本地副本什么时候可以复用](02-local-copy.md)
