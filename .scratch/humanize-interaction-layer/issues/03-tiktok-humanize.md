# 03 — TikTok：发布流接入人类化

**What to build:** TikTok 视频与图文发布路径接入人类化。配文（Draft.js）保留现有 `End → ControlOrMeta+A → Delete` 清空序列后逐字；话题改为逐字输入 + 有界等待 + 候选按文本全等点选，失败保留纯文本并关联想；41 个可见点击走 `Humanizer`，选项控件集中在 `TiktokOptionControl` 等公共底座上改。`locator_base` 可能是 `frame_locator`——传给 `Humanizer` 的必须是 `page`。

规格依据：§3.12、§2.4、§4。波次：W1（真机探针）。

Blocked by: 01

Status: ready-for-agent

- [x] 公共选项/开关控件先改，覆盖多个调用点；不改单个选项的既有状态校验
- [x] 配文与话题清空保留平台手写序列；每次输入恰一次 `after_type`
- [x] 话题候选全等匹配；匹配失败不中止发布
- [x] hidden file input 的 force 兜底保留并带三字段标记；其余 `force` 全删
- [x] 发布点带 `before_submit`；切 Photos tab 带 `after_navigate`
- [x] `tests/test_tiktok_humanize.py` 三条（含 >1000 码点一次 bulk 断言）
- [x] TikTok 入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [x] `CHANGELOG.md` 的 W1 小节加本平台一行

## Answer

- 公共底座 `TiktokOptionControl` 的 locator 适配器改为先定位可见 label 本体再走 `_humanizer.click`；`:462` 与 `:2387` 的 `force`、`:2390` 的 JS 兜底已删除，只保留 hidden file input 的 `force=True`（三字段 `# humanize-impossible:` + `# native-click: file`）。
- 配文保留 `End → ControlOrMeta+A → Delete` 序列，全部键走 `humanizer.press`，正文走 `humanizer.type_text`（≤1000 逐字、>1000 一次 bulk）；话题逐字输入、有界等待、按首行文本全等点选（选中的候选保留 Enter），未命中原样保留纯文本 + Space，不中止发布。
- 一个 page 一个缓存 `Humanizer(page, sleep=self._humanize_pause)`（`locator_base` 是 frame_locator 时仍传 `page`）；发布点 `before_submit`、Photos tab `after_navigate`；`MAYBE_DISPATCHED` 后不再重发（发布循环改为置 `publish_clicked=True`）。
- 验证：新生 `tests/test_tiktok_humanize.py` 14 条（事件序列 / 值读回 / 静态门，含 >1000 bulk 与 `HUMANIZE=0`），全量 `pytest -q` 1540 passed / 2 skipped；门 A–E 在 `main_chrome.py` 上 0 违规（未接入 CLI 的旧 Firefox `main.py` 仍留在包内，门扫描按 §3.12 的文件范围排除）。
- 偏差：为保持既有 TikTok 假件（预人类化 DOM 语义）可用，8 个旧测试模块加了模块级 `HUMANIZE=0`；`test_tiktok_note_cli.py` 的标题假件补了键盘目标路由。真机验收（§6.4）未执行。
