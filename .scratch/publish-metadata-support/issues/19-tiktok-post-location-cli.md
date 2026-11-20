# 19: TikTok 为视频与 Photos 设置帖子地点

Status: ready-for-agent
Blocked by: None (can start immediately)

## What to build

使用 `sau tiktok upload-video` 或 `upload-note` 时，作者可以在 Studio 依名称请求帖子地点，并从终端判断是否选到了预期候选。

## Acceptance criteria

- [ ] 两条命令的 `--location` 省略时保留网页原值，空串或纯空白在上传前退出 `2`。
- [ ] 视频和 Photos 各覆盖一次成功和一次无同名候选。比较完整名称时忽略大小写、去首尾空白、合并连续空白。跳过近似建议，按页面顺序点击首个同名行。
- [ ] 成功时从收起后的控件读到名称；终端列出请求、所点行的名称和可见地址、最终名称，保留原成功摘要。
- [ ] 在受控 Studio 分别复现无匹配、地点入口缺失、明确资格提示、列表未收起、读值为空或错误。逐项报告原因，退出 `1`，发布点击零次。Photos 页签不可用时沿用帖型入口诊断。
- [ ] 实机通过 `--no-publish` 核对终值。为视频和 Photos 分别补齐 CLI 地点文档，注明账号样本、实际语言、观察阶段及 CLI 接入情况。

[发布元数据规格](../spec.md) · [帖子地点匹配与回读](09-location-match-and-result.md#answer) · [TikTok 视频与 Photos 地点样本](02-tiktok-location-by-post-type.md#answer) · [八条命令的验收基线与输出](10-release-evidence.md#answer)
