# 08 — 文档、术语、Skills 与 CHANGELOG

Status: open
Type: grilling
Blocked by: 03, 04, 05, 06, 07
Assignee: —

## Question

定义文档交付面：

1. **术语（`GLOSSARY.md`）**
   - 「GoLogin」条目怎么写；「本地运行时 / 云端运行时」是否要成为正式术语，与现有「托管浏览器模式」「Profile」的关系。
   - `GOLOGIN_RUNTIME` 的 `0/1` 是否要写进术语表（还是只写进 CLI 文档）。
2. **`docs/CLI.md`**
   - 新增 `#gologin-模式` 锚点，结构对齐 MLX / AdsPower 章节；通用托管章节的模式列表怎么加第三项。
   - 退出码表扩成五列后的可读性。
3. **README 与 Skill**
   - README 的托管模式说明、AI Agent 区域；18 个 Skill 的统一模板怎么加 GoLogin。
4. **CHANGELOG**
   - 记录为新增 provider，不改动既有行为；三方冲突文案变更是否算 breaking。
5. **验收清单**
   - 文档验收怎么核对（文件清单 + 人工走查），真实冒烟仍标外部阻塞。

## Context

- 参照 `.scratch/adspower-browser-mode/issues/06-docs-glossary-deployment.md` 与 `15-docs-glossary-skills.md` 的产出。
- 文档改动在实现阶段执行；本轮 spec 只列清单与文案骨架。
