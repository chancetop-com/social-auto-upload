# 20: Instagram 按候选名称选点并写入结果

Status: ready-for-agent
Resolution: completed
Blocked by: None (can start immediately)

## What to build

Reel 与图片帖按候选的名称匹配 `--location`。调用方可从现有结果 JSON 分别读取所点候选和编辑器收起后的名称。

## Acceptance criteria

- [ ] `sau instagram upload-video` 和 `upload-note` 各验一次命中和一次无同名候选。省略保留当前值并报告未请求，显式空白在上传前退出 `2`。
- [ ] 在受控编辑器将名称与地址分行显示，安排近似候选在前、两个同名异址候选在后。完整名称忽略大小写与多余空白，选首个同名行，并仅记录该行可见的地址。另覆盖只显示名称的候选。
- [ ] 候选列表已收起且地点框读回所选名称才可继续。成功 JSON、默认及自定义结果文件保留原 `options.location` 与顶层状态，以兼容方式补上所点行证据。
- [ ] 空列表、只有近似建议、入口缺失、明确资格限制以及选中后无法确认分别给出原因。用受控编辑器核对失败时退出 `1`、Share 零点击。
- [ ] 实机以 `--no-publish` 检查地点终值，文档在两条命令的地点栏分别标记实测账号、语言、阶段和 CLI 行为。名称与地址分行的受控证据单列。

[发布元数据规格](../spec.md) · [帖子地点匹配与回读](09-location-match-and-result.md#answer) · [Instagram Creator 的发布前字段回读](11-instagram-creator-field-readback.md#answer) · [八条命令的验收基线与输出](10-release-evidence.md#answer)
