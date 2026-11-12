# 03 — TikTok：发布流接入人类化

**What to build:** TikTok 视频与图文发布路径接入人类化。配文（Draft.js）保留现有 `End → ControlOrMeta+A → Delete` 清空序列后逐字；话题改为逐字输入 + 有界等待 + 候选按文本全等点选，失败保留纯文本并关联想；41 个可见点击走 `Humanizer`，选项控件集中在 `TiktokOptionControl` 等公共底座上改。`locator_base` 可能是 `frame_locator`——传给 `Humanizer` 的必须是 `page`。

规格依据：§3.12、§2.4、§4。波次：W1（真机探针）。

Blocked by: 01

Status: ready-for-agent

- [ ] 公共选项/开关控件先改，覆盖多个调用点；不改单个选项的既有状态校验
- [ ] 配文与话题清空保留平台手写序列；每次输入恰一次 `after_type`
- [ ] 话题候选全等匹配；匹配失败不中止发布
- [ ] hidden file input 的 force 兜底保留并带三字段标记；其余 `force` 全删
- [ ] 发布点带 `before_submit`；切 Photos tab 带 `after_navigate`
- [ ] `tests/test_tiktok_humanize.py` 三条（含 >1000 码点一次 bulk 断言）
- [ ] TikTok 入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [ ] `CHANGELOG.md` 的 W1 小节加本平台一行

