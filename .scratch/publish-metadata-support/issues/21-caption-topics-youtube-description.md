# 21: 从公开配文识别话题，先接通 YouTube 简介

Status: ready-for-agent
Resolution: completed
Blocked by: None (can start immediately)

## What to build

通过 `sau youtube upload-video` 交付可由其他媒体发布命令复用的配文话题识别规则。作者直接在简介内写公开话题，调用方按其在原文中的出现顺序取得结果。

## Acceptance criteria

- [ ] 用一句含重复话题、换行、紧邻标点以及带 `#片段` 的 URL 的简介，从命令入口核对写入和回读的全文。每处公开话题按原位计一次，URL 片段保留在链接中。
- [ ] 标题中另放一个话题，在 Studio 后台预填关键词。只在简介传入公开话题时，结果只计简介内的词，独立标题和关键词栏分别保留自己的原文。覆盖命令既有的简介输入方式。
- [ ] 在受控 Studio 核对调用方的逐词文字结果。吞字、错位或意外追加时指出差异；触及整帖硬限制时报错，提交动作零次。通过受控页面演示成功路径。
- [ ] 这一批先接通配文输入，现有旧参数调用仍可通过既有回归。更新 YouTube CLI 文档，说明简介、标题、后台关键词各自的行为；旧参数的统一移除由最后一张迁移工单验收。

[发布元数据规格](../spec.md) · [配文话题与旧参数迁移](05-tags-native-and-fallback.md#answer)
