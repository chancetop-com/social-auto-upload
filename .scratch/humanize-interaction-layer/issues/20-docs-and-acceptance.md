# 20 — 文档与验收脚手架

**What to build:** 把人类化交互层的对外契约写进四处文档，并建立真机验收与「未验证平台」的记录骨架：`docs/CLI.md` 新增「人类化交互层（全平台）」一节（默认开启、`HUMANIZE=0` 语义、覆盖边界、失败语义、与 15 分钟预算的关系、force 准入一句话、托管未验证、链接规格）；`GLOSSARY.md` 补四词条；`CHANGELOG.md` 建 `[Unreleased] ### 人类化交互层（15 平台）` 骨架；umbrella skill 加三行。同时创建 `.scratch/humanize-rollout/acceptance.md` 模板（三平台表头 + 12 个未验证平台表）。

规格依据：§8、§6.4。

Blocked by: 04, 05, 06

Status: resolved

- [x] `docs/CLI.md` 新节落位并链接 `.scratch/humanize-rollout/spec.md`（不在 docs 存副本）
- [x] `GLOSSARY.md` 四词条只写「是什么」：人类化交互层 / 交互真实度 / 清空策略 / stillOn
- [x] `CHANGELOG.md` 骨架建立，W1 真机结果已写入（未做写「未验证」）
- [x] umbrella skill 三行：默认开启、`HUMANIZE=0` 退回原生、出问题先关它再报
- [x] `acceptance.md` 模板含三平台表头与 12 平台未验证表（实际 13 行，口径见 Answer）；表头固定注明「`--no-publish` 干跑、未点真实发布」
- [x] CLI 新节注明：真机验收口径为 `--no-publish` 停在就绪点，发布点击不在本轮验收范围
- [x] `README.md` 与平台级 `SKILL.md` 未被改动

## Answer

- `docs/CLI.md` 在「发布超时预算（全平台）」之后新增「人类化交互层（全平台）」：默认开启、`HUMANIZE=0`（strip 后比较）是唯一语义回滚开关（一次 `insert_text` / 一次原生 `locator.click` / 零停顿）、覆盖边界（`set_input_files` / 文件选择器 / `select_option` / `evaluate` / 读回保持原生）、失败语义（候选缺失与元素不可用均退出 `1`，`click_dispatched="maybe"` 禁止重派发，无运行时降级）、与 15 分钟预算的关系（只吃剩余、clamp 到 0、不加预算）、`force` 准入一句话、`--no-publish` 验收口径、托管模式未验证，并链接规格 §2/§6.4（不存副本）。
- `GLOSSARY.md` 增四词条（人类化交互层 / 交互真实度 / 清空策略 / stillOn），只写「是什么」；`CHANGELOG.md` 建 `### 人类化交互层（15 平台）` 父节（默认开启、`HUMANIZE=0` 回滚、三处 `--no-publish` 结果、未验证清单），W1–W5 五个小节降为 `####` 嵌套其下；umbrella skill 加三行。
- `acceptance.md` 保留小红书/Instagram/TikTok 三节原始记录，题注补「只验本地模式、托管未验证、`--no-publish` 不点发布」，补「未验证平台」表。
- 偏差（计数）：未验证平台表实际 **13 行**，不是工单/规格写的 12。§6.4/§9 的 12 是把 Facebook 个人主页与 Facebook Page 计为一个 Facebook 家族；两者各有独立 Skill、CLI 平台名与离线测试文件，故分行列出，并在表下写明口径。
- `README.md` 与全部 `skills/<platform>/SKILL.md` 未改动；全量 `pytest -q` 全绿。
