# 22: Instagram 核对完整配文并报告逐词结果

Status: ready-for-agent
Resolution: completed
Blocked by: 21

## What to build

Reel 与图片帖从最终公开配文识别话题，调用方可在既有结果输出里核对全文是否一致及逐词观察结果。

## Acceptance criteria

- [ ] 从 `sau instagram upload-video`、`upload-note` 使用既有标题和正文组合及支持的正文文件输入，逐字回读编辑器全文。两种帖型均覆盖重复词、链接片段、空行与标点。
- [ ] 直接写在配文中的话题只出现原稿中的次数，按顺序报告，包括重复词。链接片段不计作话题；仅观察到文字时，结果按文字记录。
- [ ] 受控编辑器产生吞字、错位或多余追加时指出差异，触及整帖硬限制时报错；失败时 Share 点击零次。
- [ ] 以 `--no-publish` 到达 Share 前，成功为 `prepared`。核对成功 JSON、默认及 `--result PATH` 文件，新增话题证据兼容原选项和顶层状态。文档按帖型注明 CLI 行为、实测账号、实际语言及阶段。

[发布元数据规格](../spec.md) · [配文话题与旧参数迁移](05-tags-native-and-fallback.md#answer) · [Instagram Creator 的发布前字段回读](11-instagram-creator-field-readback.md#answer) · [八条命令的验收基线与输出](10-release-evidence.md#answer)
