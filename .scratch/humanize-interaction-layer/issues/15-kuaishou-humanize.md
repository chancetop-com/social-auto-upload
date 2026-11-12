# 15 — 快手：手写清空序列保留与封面定位收窄

**What to build:** 视频与图文表单接入人类化。描述/正文保留现有 `Backspace → Control+A → Delete` 清空序列，只把键改由 `Humanizer.press` 执行；话题逐字。封面设置的无文本 `div` 先收窄到具体可点目标再点；Joyride 引导层与「我知道了」保持原生并加标记；定时日期仍由 JS setter 写值，点击只负责打开 picker。

规格依据：§3.6、§2.4、§4。波次：W4。

Blocked by: 01

Status: ready-for-agent

- [x] 描述/正文清空序列逐键保留；话题逐字
- [x] 描述聚焦 4 级回退中，正常路径走 Humanizer；回退分支删 force 并让零尺寸直接失败
- [x] 封面目标收窄为唯一可点元素；仍无稳定目标则记入残留清单，不猜坐标
- [x] 引导层/notice 带 `# native-click: chrome`，引导层的 force 带三字段标记
- [x] `tests/test_kuaishou_humanize.py` 三条
- [x] 快手入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [x] `CHANGELOG.md` 的 W4 小节加本平台一行

## Answer

视频与图文两条发布链共 13 个可见点击改走 `Humanizer`（含两处发布前的 `before_submit`、切图文 tab 的 `after_navigate`），4 个文本点保留 `Backspace → Control+A → Delete` 清空序列、话题逐字且最多 3 个；>1000 码点由共享层整段 `insert_text`。
描述聚焦 4 级策略全部改用坐标点击并删除 `force`（零尺寸目标以 `zero-box` 硬失败）；封面入口从 `nth(0)` 收窄到 `div:visible` 首个可见 div。
登录二维码、文件入口、「我知道了」提示条共 8 处保持原生并带 `# native-click`；唯一 `force` 在 Joyride 引导层，带三字段 `# humanize-impossible` 标记。
`tests/test_kuaishou_humanize.py` 10 个用例（事件序列 / 字段读回 / 静态门 / `HUMANIZE=0`）全绿；包内门 A–E 零违规。
残留：封面入口的具体命中区仍为 `needs-live`（无真机 DOM），未猜点坐标；`tests/test_kuaishou_publish_dialog.py` 因确认弹窗函数新增 `humanizer` 参数做了最小签名适配。

