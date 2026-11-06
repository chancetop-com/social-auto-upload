# 17 — 文档、Skill 与术语表同步

Status: ready-for-agent
Type: task
Blocked by: 11, 12, 13, 14, 15, 16
规格依据: spec.md §9

## What to build

仓库文档、CLI 参考、Agent Skill 与术语表与新 TikTok 行为一致，并明确指出哪些能力仍待真实账号验收。运营和后续 Agent 不应再看到“TikTok 没有 upload-note”或“未知结果可以重发”这类过时描述。

## Acceptance criteria

- [ ] README 平台表 TikTok 图文列改为支持，并注明仅 Multilogin 模式、Profile 需 English (US)。
- [ ] `docs/CLI.md` 退出码表加入 `9` 并写“禁止自动重发”；TikTok 小节补新 flag、`upload-note` 示例与限制。
- [ ] TikTok Skill 删除“没有 upload-note，不要虚构”；补 `upload-note` 与新 flag 示例；退出码补 `9`；保留“未知结果先核查、不能直接重发”的约束。
- [ ] CHANGELOG 的 Unreleased 增加 TikTok 小节；未做真实账号验收的能力标注“待验收”。
- [ ] GLOSSARY 增加“设置后回读”“发布结果未知”“Photos tab / 图片帖”三个术语。
- [ ] 文档不承诺已排除的能力（`--cover-ms`、`--cover-index`、`--bgm`、`--json`、内容复用分项）。
- [ ] `examples/` 若更新，只演示 keyword-only 新参数且不破坏旧调用。
