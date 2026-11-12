# 01 — 15 个平台的交互调用点清单与分类

Status: resolved
Type: research
Blocked by:

## Question

把 15 个浏览器上传器里所有页面交互调用点逐条列出来，并分类。这是规格里「每个字段怎么改」的唯一事实来源。

覆盖的 uploader：

`alipay_uploader`、`baijiahao_uploader`、`dayu_uploader`、`douyin_uploader`、`hupu_uploader`、`ks_uploader`、`meta_uploader/facebook_uploader`、`meta_uploader/facebook_page_uploader`、`meta_uploader/insgraph_uploader`、`tencent_uploader`、`tk_uploader/main_chrome.py`、`weibo_uploader`、`xueqiu_uploader`、`youtube_uploader`、`zhihu_uploader`。

要回答：

1. 每个 `fill()` / `keyboard.type()` / `press_sequentially()` 调用：文件:行号、选择器、写入的字段语义（标题/正文/标签/地点/链接/时间…）、目标元素类型（`input` / `textarea` / `contenteditable`）、**打开时是否已带默认值**。
2. 每个 `.click()` 调用：分成四类——(a) 可见按钮/选项，可坐标点击；(b) 导航或提交页跳转的点击；(c) 触发文件选择器的点击；(d) 对隐藏/零尺寸/不可命中元素的硬点（与 `force=True` 交叉标注）。
3. 9 处 `evaluate("el => el.click()")`：各自在点什么、为什么非要用 JS。
4. 19 处 `force=True`：各自的目标元素、注释里已写的原因（如果有）、所在流程阶段。
5. 3 处 `select_option()` 与 31 处 `set_input_files()`：确认都在「保持原生」范围内，列出例外。
6. 1 处 `hover()`：在做什么。
7. 每个 uploader 的 `page` 生命周期：是单 page 还是多 page/多 tab，`Humanizer` 实例该在哪里创建。

输出：`.scratch/humanize-rollout/research/01-inventory.md`，按平台分节，每节一张表（行号 / 调用 / 分类 / 字段语义 / 目标元素 / 默认值 / 处置建议）。末尾给一张汇总计数表，核对与地图里记录的规模一致。

置信度标注：`[code]` 全部条目都应为此档；涉及「页面打开时是否有默认值」的，标 `[inferred]` 并说明依据（静态 HTML、注释、既有测试），无法判断的标 `[needs-live]`。

不要改任何生产代码。

## Answer

清单与全部横向专题见 [`../research/01-inventory.md`](../research/01-inventory.md)（15 个平台各一张表 + 9 处 `el.click()` / 18 处 `force=True` / `select_option`+`set_input_files` / `hover` / page 生命周期 / 对账 / 风险 Top 5）。

- 对账：9 个模式共 413 次命中，落在 **386 个唯一行**、**374 个真实调用**、**371 个页面交互调用点**；27 行同时命中 2 个模式（`click(force=True)`、`evaluate("el => el.click()")`）。
- 差异均已定位：`click` 303→**294**（8 行注释/文档字符串 + 1 行字符串实参 + 4 处跨行调用）；`force=True` 19→**18**（tk:1030 是 docstring）；`set_input_files` 31→**28**（2 处注释 + 1 f-string）；`select_option` 3→**0 个 Playwright API**（zhihu 本地同名方法 1 定义 + 2 调用）。
- 分类分布（345 张表行）：可坐标点击 220、文本输入 31、导航/提交 28、隐藏或不可命中 28、富文本 18、文件选择触发 10、非交互 9（+1 hover）。
- 处置分布：改 Humanizer **246**、保持原生 **54**、待定 **45**（force 白名单 18、搜索型输入、动画/覆盖层目标）。
- 计数盲区 3 处：TikTok 配文与话题用 `keyboard.insert_text`（不在 12 条 `keyboard.type` 内）；YouTube 的 `.type(delay=…)` 与 `_click_if_present`；Facebook Page 的小时/分钟用 `locator.press(digit)`。
- 生命周期：14 个平台发布路径单 page；**微博有 2 个**（首页 page + `expect_popup` 的 `publish_page`，需 2 个 Humanizer）。dayu/xueqiu/zhihu 的第二个 tab 均为只读。
- 最危险 5 处：YouTube `_fill_editable`（注释明确反对逐字，防 `#` 联想浮层卡死）、微博发布按钮（中心被空 div 覆盖，只能 `el.click()`）、抖音 `_native_click`（重复坐标点击 + 合成事件，8 处调用）、TikTok `insert_text` 配文、大鱼 `#author` 预填（清空会抹掉作者）。
- 置信度：行号/调用/分类/目标元素全部 `[code]`；默认值列与处置列的非显然判断逐条标 `[inferred]` / `[needs-live]` 并写明依据。
