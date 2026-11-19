# 调度 App 隔日重跑时应怎样选择下一条命令

Type: grilling
Label: wayfinder:grilling
Status: resolved
Assignee: chancetio (Codex)
Blocked by: 03, 04, 07

## Question

调度 App 次日恢复同一个 post 时，哪些组合需要写进 CLI 规格的验收场景？从 App 上次实际拿到的结果出发，分别考虑仅收到入队回执、等待返回部分失败或任务已清理，以及发布结果未知。结合本次持有的资源目录 ID、原 URL 或更新后的签名 URL，确认各场景下 App 能否直接发布、是否需要再次等待素材，或是否应先核对平台发布结果。每个选定的场景应写明调用方可观察的结果。

预下载可观察结果见[预下载命令怎样返回入队结果或本地路径](03-predownload-cli.md)。涉及发布取材和签名链接的场景分别依赖[素材下载中断后怎样恢复并报告结果](04-interrupted-upload.md)与[素材链接或内容变化时怎样刷新](07-refresh-source.md)。

## Answer

按范围关闭。隔日是否重跑、何时重跑、选择哪条命令，由独立的调度 App 决定。CLI 对每次命令调用的行为和返回结果已由上面三项决策覆盖。
