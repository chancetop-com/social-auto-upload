# 05 — 波次、回滚与文档同步

Status: open
Type: grilling
Blocked by: 01, 02

## Question

15 个平台不可能同时落地，而且只有 TikTok / Instagram / 小红书能做真机验收。要定的是「按什么顺序做、怎么退、文档改哪些」。

要定的事：

1. **波次**：第一波放哪几个？候选依据——(a) 有真机账号（TikTok、Instagram）；(b) 调用点最少（facebook 仅 1 fill + 2 click）；(c) 业务量最大（抖音、视频号、快手）。三者冲突时以哪个为准？
2. **回滚单位**：目前只有全局 `HUMANIZE=0`。是否需要按平台开关（例如 `HUMANIZE_EXCLUDE=tiktok,weibo`）？多一个开关就多一份契约，值得吗？
3. **验收门槛**：离线测试要断言到什么程度才算一个平台「完成」——只断言事件序列（走没走 `keyboard.press`、有没有 `mouse.move→down→up`、有没有 `force`），还是要连同「字段值最终等于预期」一起断言？
4. **真机验收记录**：TikTok / Instagram / 小红书 三家的验收要记录什么（发帖类型、字段、耗时、是否触发风控、帖子是否已删），落在哪个文件？未做的平台怎么标注？
5. **文档同步**：哪些必须改——`docs/CLI.md`（`HUMANIZE` 语义）、`GLOSSARY.md`（补「Humanize 交互层」词条）、`CHANGELOG.md`、各平台 `SKILL.md`？规格里要逐条列出，还是交给实施期判断？
6. **失败回退**：某个平台改严格后连续失败，是回退该平台到原生、还是保留并标注已知问题？

产出：波次表（平台 / 依据 / 验收方式）+ 回滚契约 + 完成定义 + 文档清单。

## Answer

（待决议）
