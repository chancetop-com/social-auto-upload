# 15 — 文档、术语、Skills、CHANGELOG 与验收清单

Status: ready-for-agent
Type: task
Blocked by: 13, 14
Assignee: —

## What to build

把 AdsPower 模式作为“托管浏览器模式”的第二 provider 完整写进用户文档与 Skill，不改变本地/MLX 既有文档入口：

- `GLOSSARY.md`：泛化 Profile；新增托管浏览器模式、AdsPower、Local API、API Key、`user_id`；MLX 专属词显式标注。
- `docs/CLI.md`：三个章节（本地 / MLX / AdsPower），保留旧锚点 `#multilogin-x-模式`；参数矩阵、退出码含 `11`、平台表、部署前提、调度责任、身份风险、安全、Bearer/重置、不支持清单。
- `README.md`：`#### 托管浏览器模式（可选）` + MLX/AdsPower 两个子节；两套示例；退出码含 `11` 与 MLX 429 提示。
- `docs/skill-distribution.md`、`skills/social-auto-upload/SKILL.md`、17 个平台 Skill：统一模板；Bilibili 为“不支持”特例。
- `CHANGELOG.md`：`[Unreleased]` 增加 `### 托管浏览器（AdsPower）`，并注明真实冒烟未执行（ticket 09）。
- `.scratch/adspower-browser-mode/acceptance.md`：逐项核对文件清单，写明“真实 AdsPower 冒烟未执行（ticket 09）”。

## Acceptance criteria

- [ ] 文档中的退出码表包含 `11`，并说明 MLX 429 已由 `1` 改为 `11`。
- [ ] 旧链接 `docs/CLI.md#multilogin-x-模式` 仍可定位。
- [ ] AdsPower 参数矩阵明确：`--profile-id` 必填、`--folder-id` 忽略、`--account` 可选。
- [ ] 部署前提写明付费版、同机、Local API、Chromium Profile、已人工登录、TikTok English (US)。
- [ ] 明确不支持：无 key 安装、V1、Firefox、Docker/跨机、Bilibili、CLI 登录。
- [ ] 18 个 Skill 均能说明两种托管模式；Bilibili 明确不支持。
- [ ] `acceptance.md` 逐项列出并勾选，真实冒烟标为未执行。

## Context

- 规格：§11.5（文档验收）、§9（安全）、§10（部署与调度）、§2（书写规范）。
- 设计裁决：ticket 06。
