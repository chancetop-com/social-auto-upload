# 15 — 快手：手写清空序列保留与封面定位收窄

**What to build:** 视频与图文表单接入人类化。描述/正文保留现有 `Backspace → Control+A → Delete` 清空序列，只把键改由 `Humanizer.press` 执行；话题逐字。封面设置的无文本 `div` 先收窄到具体可点目标再点；Joyride 引导层与「我知道了」保持原生并加标记；定时日期仍由 JS setter 写值，点击只负责打开 picker。

规格依据：§3.6、§2.4、§4。波次：W4。

Blocked by: 01

Status: ready-for-agent

- [ ] 描述/正文清空序列逐键保留；话题逐字
- [ ] 描述聚焦 4 级回退中，正常路径走 Humanizer；回退分支删 force 并让零尺寸直接失败
- [ ] 封面目标收窄为唯一可点元素；仍无稳定目标则记入残留清单，不猜坐标
- [ ] 引导层/notice 带 `# native-click: chrome`，引导层的 force 带三字段标记
- [ ] `tests/test_kuaishou_humanize.py` 三条
- [ ] 快手入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [ ] `CHANGELOG.md` 的 W4 小节加本平台一行

