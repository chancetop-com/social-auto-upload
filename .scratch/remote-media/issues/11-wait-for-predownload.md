# 11: 等待预下载并取得本地文件

Status: ready-for-agent
Resolution: completed
Blocked by: None (can start immediately)

**What to build:** 调度 App 用 `sau media predownload --task-id ID --urls URL [URL ...] --wait` 一次提交多条 HTTP(S) 媒体直链。命令返回每个输入对应的本地路径或失败原因，取得的完整文件可供后续发布使用。

规格见[网络素材预下载与上传 CLI 规格](../spec.md)。

## 验收条件

- [x] 用本机 HTTP 源站提供两份已知内容。从实际 `sau` 命令取得退出码 `0` 和单个 JSON 对象，其中 `task_id` 对应输入，`status="ready"`，`items` 中的绝对 `path` 可读，文件字节与源站一致。日志和诊断写入 stderr。
- [x] 按资源目录 ID 和完整 URL（含签名参数）查找本地副本。同 ID 内重复的 URL 只传输一次，每个输入位置仍有一项。同名且不同 URL 的内容分别保存，不同 ID 独立下载相同 URL。
- [x] 同一 ID 有完整副本时，源站换版后再次等待仍返回旧副本。源站对未完成的签名 URL 返回 HTTP 403 时，该项报告实际原因。
- [x] 一项返回 404 后继续取得其余项。结束时退出 `1` 并给出 `status="failed"`，成功位置提供 `path`，失败位置提供 `reason`，顺序与 `--urls` 一致。
- [x] 缺少 ID、缺少 URL 或一组输入中含无效参数时，退出 `2`，诊断仅写 stderr。源站收到零次下载请求。
- [x] 从网络读取、处理重定向、校验到落盘均使用有界缓冲。只在文件完整后交付最终路径。资源保存在项目下载根目录内该 ID 的直属子目录，下载产物和断点均由 Git 忽略。

## Comments

实际 `sau media predownload --wait` 配合本机 HTTP 源站验证了输入顺序、去重、跨 ID 隔离、403/404、参数与 stdout/stderr 契约，以及完整文件的原子交付。见 `tests/test_remote_media_wait.py`。
