# 20 — 文档与验收脚手架

**What to build:** 把人类化交互层的对外契约写进四处文档，并建立真机验收与「未验证平台」的记录骨架：`docs/CLI.md` 新增「人类化交互层（全平台）」一节（默认开启、`HUMANIZE=0` 语义、覆盖边界、失败语义、与 15 分钟预算的关系、force 准入一句话、托管未验证、链接规格）；`GLOSSARY.md` 补四词条；`CHANGELOG.md` 建 `[Unreleased] ### 人类化交互层（15 平台）` 骨架；umbrella skill 加三行。同时创建 `.scratch/humanize-rollout/acceptance.md` 模板（三平台表头 + 12 个未验证平台表）。

规格依据：§8、§6.4。

Blocked by: 04, 05, 06

Status: ready-for-agent

- [ ] `docs/CLI.md` 新节落位并链接 `.scratch/humanize-rollout/spec.md`（不在 docs 存副本）
- [ ] `GLOSSARY.md` 四词条只写「是什么」：人类化交互层 / 交互真实度 / 清空策略 / stillOn
- [ ] `CHANGELOG.md` 骨架建立，W1 真机结果已写入（未做写「未验证」）
- [ ] umbrella skill 三行：默认开启、`HUMANIZE=0` 退回原生、出问题先关它再报
- [ ] `acceptance.md` 模板含三平台表头与 12 平台未验证表，与实际记录一致
- [ ] `README.md` 与平台级 `SKILL.md` 未被改动

