# 16 — 支付宝生活号：合集合并与发布接入

**What to build:** 生活号视频发布表单接入人类化：标题与描述清空后逐字，封面弹窗、合集下拉、质量提示与两次发布点击全量改；合集选择的两级点击（force 首选 + 无 force 重试）合并为一次坐标点击。登录扫码与文件入口保持原生并加标记。

规格依据：§3.1、§4。波次：W5。

Blocked by: 01

Status: resolved

- [x] 合集选择合并为一次 `Humanizer.click`，force 首选删除
- [x] 合集下拉先收窄两个候选分支到唯一 Locator
- [x] 两次发布点击都带 `before_submit`；发布入口带 `after_navigate`
- [x] 零 `fill(`、零 `el.click()`、无 force
- [x] `tests/test_alipay_humanize.py` 三条
- [x] 支付宝入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [x] `CHANGELOG.md` 的 W5 小节加本平台一行

## Answer

- 发布链路单 `Humanizer`（`upload_in` 的 `new_page()` 之后构造，`sleep=self._humanize_pause`）；标题/描述走 `sel` 清空后逐字，描述先 `\r\n`→`\n`，>1000 由共享层整段 bulk。
- 合集两级点击合并为一次 `Humanizer.click`：两条下拉候选分支先计数再 `_unique` 收窄（多义硬错），force 首选整段删除；选项的滚入视口交给 `Humanizer`。
- 封面入口/弹窗上传 tab/「完 成」、质量提示「继续发布」、发布与 AIGC 二次发布全部坐标点击；两处发布各付一次 `before_submit`，「发布视频」入口点后付 `after_navigate`。
- 原生仅 2 处：登录 iframe 扫码 tab（`login`）与「上传图片」文件入口（`file`），`set_input_files` 两处未动；门 A–E 零违规。
- 未验证（无真机环境）：真实 antd5 弹窗/下拉的落点命中、质量弹窗出现时序与 AIGC 二次点击的真实触发条件；`check_ai_label` 的 `radio.check()` 不在 §3.1 表内，保持现状。
