# 17 — 百家号：contenteditable 清空与搜索候选全等

**What to build:** 标题、合集搜索、声明与发布接入人类化。标题是 `contenteditable` 且页面可能自动填文件名：保留「点标题 → Ctrl+A → Backspace」清空序列后逐字。合集搜索逐字输入，固定等待换成有界等待，候选项按合集名全等匹配（`.first` 仅降级）。创作声明改点组件本体，删除 force；发布遮挡走清浮层。

规格依据：§3.2、§2.4、§4。波次：W5（本波热点，先做）。

Blocked by: 01

Status: ready-for-agent

- [ ] 标题清空序列保留；自动填的文件名被完全替换
- [ ] 搜索候选按全等命中；命中不到时沿用现有跳过策略，不中止发布
- [ ] 声明组件改点本体，force 删除；发布点无 force
- [ ] 零 `fill(`、零 `el.click()`
- [ ] `tests/test_baijiahao_humanize.py` 三条（含标题替换与搜索全等）
- [ ] 百家号入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [ ] `CHANGELOG.md` 的 W5 小节加本平台一行

