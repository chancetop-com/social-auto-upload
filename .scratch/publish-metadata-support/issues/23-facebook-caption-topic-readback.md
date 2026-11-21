# 23: Facebook 个人主页与 Page 核对公开配文

Status: ready-for-agent
Resolution: completed
Blocked by: 21

## What to build

`sau facebook`、`sau facebook-page` 各自的 `upload-video` 与 `upload-note` 支持直接在配文里写话题。Page Reel 的独立关键词栏继续保留页面原值。

## Acceptance criteria

- [ ] 在受控编辑器以四条命令分别核对发布前全文。覆盖现有标题与正文组合、各入口支持的文件输入、重复词、换行、紧邻标点和含片段的链接。
- [ ] 按最终公开配文报告每处话题的文字证据，保留顺序与重复次数。给 Page Reel 的独立关键词栏预填内容，验证正文话题只进入正文；独立标题按原输入处理。
- [ ] 在个人主页及 Page 模拟正文被改写或整帖超限，命令指出差异或限制并停止。最终发布或排期动作零次，沿用各入口的既有结果输出。
- [ ] 更新个人主页与 Page 的四个 CLI 示例，从公开配文取话题。以受控页面核对命令结果，文档标明验收阶段和证据来源。

[发布元数据规格](../spec.md) · [配文话题与旧参数迁移](05-tags-native-and-fallback.md#answer)
