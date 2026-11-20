# 25: TikTok 在配文原位关联话题

Status: ready-for-agent
Blocked by: 21

## What to build

`sau tiktok upload-video` 从 `--title` 识别配文话题，`upload-note` 从 Photos 正文或其既有文件输入识别，在每个话题原位点选并回读。

## Acceptance criteria

- [ ] 视频与 Photos 各验普通同名候选和同名 `Add`，从编辑器中的话题标记读到原词才报告「已关联」。用 `--no-publish` 核对两种帖型点选 `Add` 后的关联与全文，分别记录网页与 CLI 证据。
- [ ] 用同时含重复词、链接片段、换行和标点的配文核对原文。修正自动追加的空格后仍能回读同名标记，原稿自己的空格与标点逐字保留。Photos 的独立标题按原输入处理。
- [ ] 受控页面只给近似建议时，报告「保留文字，无同名候选」。达到可关联数量上限时逐词说明原因并保留原稿。两种情况均以全文一致作为继续的条件。
- [ ] 选成其他话题、吞字、错位、意外追加或触及整帖硬限制时说明原因，发布点击零次。终端逐词结果保留顺序、重复次数和原成功摘要。
- [ ] 视频与 Photos 分别更新 CLI 配文话题栏，注明接入行为、实测账号、界面语言及阶段。

[发布元数据规格](../spec.md) · [配文话题与旧参数迁移](05-tags-native-and-fallback.md#answer) · [六个编辑器的逐词回读](12-inline-topic-readback.md#answer) · [同名特殊候选的点选决定](13-topic-create-candidate.md#answer) · [六个编辑器的特殊候选实测](14-created-topic-readback.md#answer)
