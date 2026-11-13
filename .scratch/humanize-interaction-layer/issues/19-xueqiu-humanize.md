# 19 — 雪球：空守卫样板与预览遮罩

**What to build:** 文章标题依赖平台已有的「非空即拒绝」守卫（清空 = none），正文聚焦、工具栏传图、裁剪、分享范围、预览与关闭遮罩、发布接入人类化。失焦与发布后核对路径保持原生并加标记。

规格依据：§3.13、§2.4、§4。波次：W5。

Blocked by: 01

Status: resolved

- [x] 标题守卫保持有效（非空输入就拒绝），不清空
- [x] 预览遮罩关闭用坐标点击（不删遮罩、不强点）
- [x] 发布点 `before_submit`；零 `fill(`、零 `el.click()`、无 force
- [x] `tests/test_xueqiu_humanize.py` 三条（含守卫与遮罩关闭）
- [x] 雪球入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [x] `CHANGELOG.md` 的 W5 小节加本平台一行

## Answer

- 13 个交互点按 §3.13 落地：标题 `T/none`（保留 `:153` 的「非空即拒绝」守卫，只坐标聚焦 + 逐字，零清空键，是全仓清空策略样板）、正文坐标聚焦（HTML 粘贴仍原生）、工具栏「上传图片」、封面「确认裁剪」、分享范围/创作声明下拉（先读 `inner_text`，已选对则跳过，避免点开关收起容器）+ 精确文本选项、「预览」、预览遮罩关闭（坐标点 `index_preview_ > index_close_`，保留「不删遮罩/不强点」注释，随后只断言父层隐藏）、发布 `before_submit`。实例在 `upload_in` 的 `context.new_page()` 之后按 `cached.page is not page` 缓存，停顿经 `_humanize_pause` 吃 15 分钟预算。
- 保留原生并逐条标记：正文失焦标题 ×2 `# native-click: focus`（粘贴/上传后让编辑器落定块）、`verification.py:59` 发布后「内容管理」只读核对 `# native-click: read`；正文与封面文件输入仍 `set_input_files`（`N/file`）。包内门 A–E 全绿，零 `fill(`、零 `el.click()`、零 `force`。
- `tests/test_xueqiu_humanize.py`（10 例）：正文路径事件序列（2 次坐标 `down`，标题失焦原生 ×2，`Meta+V` 粘贴与 file chooser 原生）、填表路径（标题逐字 + 分享范围跳过 + 声明下拉/选项 + 预览共 4 次 `down`）、封面裁剪确认（裁剪 1 次 `down`、文件入口原生）、遮罩关闭（1 次 `down`、遮罩节点零操作）、发布 `before_submit` 先于 `down` 且 hit-test 先于 `down`；字段读回（标题值全等且零 `press` 清空键、守卫「已有草稿」在输入前停工）；`HUMANIZE=0`（每字段一次 `insert_text`、原生 click、零停顿）。
- 偏差/未验证：真机未跑（W5 只做离线门与单测，`--no-publish` 干跑留给 20 号验收）；封面/正文图片的 `expect` 断言与内容核对由既有的真浏览器用例（`tests/test_xueqiu_uploader.py`）覆盖，人类化用例里 patch 掉以保持零浏览器。
