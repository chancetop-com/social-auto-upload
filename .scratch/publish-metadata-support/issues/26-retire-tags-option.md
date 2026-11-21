# 26: 十三条命令统一移除 `--tags`

Status: ready-for-agent
Resolution: completed
Blocked by: 22, 23, 24, 25

## What to build

七个平台统一以最终公开配文为话题来源。旧脚本会在参数解析时收到用法错误，迁移说明帮助作者决定哪些词应写入公开配文。

## Acceptance criteria

- [ ] 对小红书、Rednote、Instagram、TikTok、Facebook 个人主页、Facebook Page 的 `upload-video` 与 `upload-note`，以及 `youtube upload-video`，逐条核对传 `--tags` 在解析阶段退出 `2`，上传和发布均未开始。各命令帮助与现行用法一致。
- [ ] 十三条命令分别用配文中的 `#话题` 验收替代调用。核对平台既有标题与正文组合、受支持的正文文件输入以及最终公开全文。YouTube Studio 和 Facebook Page Reel 的独立关键词保留预填值。
- [ ] 检查小红书、Rednote、TikTok 六个编辑器的 CLI 验收记录均已覆盖同名特殊行点选、原位关联、完整原稿。Instagram 验证既有成功 JSON 及两种结果文件，另三平台沿用终端摘要和退出码。
- [ ] 更新现行文档与调用示例，提供旧参数报错及改写为「今天喝了 #咖啡，配上 #栗子蛋糕。」的示例，说明一词已关联、另一词无同名候选时的逐词结果。提醒旧 YouTube 用户自行选择哪些后台词需要公开。
- [ ] 核对四个主平台共八行文档均按命令、字段区分网页能力、CLI 接入和实际样本，注明证据阶段和未实测项。实机验收沿用支持入口的 `--no-publish`，其余入口以受控页面核对命令行为。

[发布元数据规格](../spec.md) · [配文话题与旧参数迁移](05-tags-native-and-fallback.md#answer) · [八条命令的验收基线与输出](10-release-evidence.md#answer) · [六个编辑器的特殊候选实测](14-created-topic-readback.md#answer)
