# 18: 小红书与 Rednote 按名称设置帖子地点

Status: ready-for-agent
Blocked by: None (can start immediately)

## What to build

小红书与 Rednote 的视频、图文命令均接受 `--location`。同名不同地址时，终端同时给出所点候选的可见地址和列表收起后的地点名称。

## Acceptance criteria

- [ ] 从两端 `sau` 的 `upload-video`、`upload-note` 分别验证省略时保留页面原值，显式空串或纯空白在上传前退出 `2`。自主拍摄声明里的 `--shoot-location` 与帖子地点分别写入对应控件。
- [ ] 四个入口各验一次命中和一次无同名候选。比较完整名称时忽略大小写、去除首尾空白并合并连续空白。在「房山人民公园」排在两个「人民公园」之前时，选择首个「人民公园」。
- [ ] 成功要求列表已收起且控件显示所选名称。终端给出请求、所点行名称及可见地址、最终名称和原成功摘要。
- [ ] 空列表或只有近似建议报告无匹配。受控页面分别复现入口缺失、明确资格提示、列表未收起、终值为空或不符；按原因退出 `1`，发布点击零次。
- [ ] 实机用 `--no-publish` 核对当前地点终值。更新四条命令的地点栏，区分网页样本和 CLI 接入，记录实际账号、语言及观察阶段。

[发布元数据规格](../spec.md) · [帖子地点匹配与回读](09-location-match-and-result.md#answer) · [小红书和 Rednote 地点样本](01-xhs-rednote-post-location.md#answer) · [八条命令的验收基线与输出](10-release-evidence.md#answer)
