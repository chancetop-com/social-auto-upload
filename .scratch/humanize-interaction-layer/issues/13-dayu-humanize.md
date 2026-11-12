# 13 — 大鱼号：跨 iframe 正文与 `#author` 保留

**What to build:** 视频表单与图文表单接入人类化。图文正文在独立 iframe 内：聚焦与工具栏点击用 frame 内 `Locator`；正文粘贴保持原生。`#author` 的清空策略为 `none`（缺省保留页面预填，只有显式传 `author` 才覆盖）；两个标题字段的预填未知，按「先读空再写」处理。定时与发表各点接入。

规格依据：§3.3、§2.4、§4。波次：W4。

Blocked by: 01

Status: ready-for-agent

- [ ] iframe 内目标用 frame 内 `Locator`；不把 `frame_locator` 当 page 传给 `Humanizer`
- [ ] `#author` 不被清空；显式传值时覆盖
- [ ] 标签逐字 + Enter；每个标签一次 `after_type`
- [ ] 失焦专用点击带 `# native-click: focus`；文件入口带 `# native-click: file`
- [ ] `tests/test_dayu_humanize.py` 三条（含 `#author` 不被抹、iframe 正文事件序列）
- [ ] 大鱼入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [ ] `CHANGELOG.md` 的 W4 小节加本平台一行

