# 17: Instagram 在编辑器被遮挡时阻止分享

Status: ready-for-agent
Resolution: completed
Blocked by: None (can start immediately)

## What to build

Reel 与图片帖在当前可操作的编辑器中回读 AI 标签。调用方仅请求关闭 AI 时，也能从现有 JSON 判断编辑器是否被「放弃帖子？」挡住。

## Acceptance criteria

- [ ] 从 `sau instagram upload-video` 与 `upload-note` 覆盖省略、开启、关闭。省略保留当前值；显式开启须读到开启。互斥参数在上传前退出 `2`。
- [ ] 单独传 `--no-ai-generated`，不请求地点。原本已关记 `applied=false, status=default_off`；从开切到关并确认记 `applied=false, status=set`；确认入口缺失记 `applied=null, status=default_off, reason=entry_missing`。
- [ ] 受控编辑器中让前台确认框持续遮挡创建页。AI 记录 `applied=null, status=mismatch` 并说明遮挡原因，顶层 `not_submitted`，退出 `1`，Share 点击零次。可见开关仍开启、或无法回读时也应阻止分享。
- [ ] 核对成功 JSON、默认文件及 `--result PATH` 保留原选项和顶层状态。实机用 `--no-publish` 验证发布前终值。两条命令的文档分别标注历史 Personal、当前 Creator 的实测帖型、语言和阶段。

[发布元数据规格](../spec.md) · [AI 声明契约](04-ai-disclosure-contract.md#answer) · [Instagram Creator 的发布前字段回读](11-instagram-creator-field-readback.md#answer) · [八条命令的验收基线与输出](10-release-evidence.md#answer)
