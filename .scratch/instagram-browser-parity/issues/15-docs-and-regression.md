# 15 — 文档、术语与全量回归收口

Status: ready-for-agent
Type: task
Blocked by: 11, 12, 13, 14
规格依据: spec.md §9、§10

## What to build

让仓库文档与新行为一致：CLI 参考、更新日志、Instagram 相关 Skill 与术语表；明确标注四项仍待真实账号真发验收。同时跑完整 A/B/C/D 测试矩阵，确认不传新参数时旧行为不变。

## Acceptance criteria

- [ ] `docs/CLI.md` Instagram 段补四个 flag 的说明与示例，写明“未传不动页面默认”。
- [ ] `docs/CLI.md` 明确 caption 超长退出码由 `1` 改为 `2`；`CHANGELOG.md` 单独标注这是破坏性变更。
- [ ] `CHANGELOG.md` `[Unreleased]` 增加 Instagram 小节，四项标 `offline-verified / post-publish unverified`，不宣称已真发验收。
- [ ] Instagram 相关 Skill 不再写“Instagram 当前暂停”等过时描述；只列已实现参数，不承诺未做能力。
- [ ] 需要时同步术语表（设置后回读、入口缺失、账号不合格等），与现有术语风格一致。
- [ ] 全量运行 A（纯逻辑）、B（fake）、C（真实 DOM 哨兵）、D（退出码）测试并全绿；C 层需要本机 Chrome。
- [ ] 复核不传新参数时两个上传命令的参数、行为、结果字段（除 `options`）与退出码不变。
- [ ] 确认没有遗留 TODO、占位文案或“待实现”标记进入用户文档。
- [ ] 不修改 spec 与 map；不关闭父工单。

## Comments

- 2026-11-10：由 `spec.md` 拆分。
