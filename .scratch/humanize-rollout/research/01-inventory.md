# 01 — 15 个浏览器上传器的页面交互调用点清单与分类

> 工单：[`../issues/01-interaction-inventory.md`](../issues/01-interaction-inventory.md)
> 范围：`utils/humanize.py` 交互层移植所需的**调用点事实**。不设计 spec，不改生产代码。
> 研究方式：只读工作树 + `grep -rEn` 全量枚举，逐行读上下文；未启动浏览器、未跑流程。

## 0. 读法、分类口径与置信度

**分类口径**（每行只能落一类）：

| 分类 | 含义 |
| --- | --- |
| `文本输入` | `input` / `textarea` 上的 `fill` / `keyboard.type` / `press_sequentially` |
| `富文本输入` | `contenteditable`（含 Lexical / Draft.js / UEditor）上的输入 |
| `可坐标点击` | 可见、可命中的按钮/选项/开关/弹层关闭；可用 `Humanizer.click` |
| `导航或跳转点击` | 点击会改变 URL、打开新 tab、或提交表单（含发布按钮） |
| `文件选择触发` | 点击动作只用于打开文件选择器（`expect_file_chooser` 内的 click、`input[type=file]` 的 click） |
| `隐藏或不可命中元素` | `force=True`、`el.click()`、`display:none` / 零尺寸 / `pointer-events:none` 的硬点 |
| `非交互（滚动、读取、等待）` | 只为聚焦/失焦/滚动/读回而点，或纯等待 |

**处置口径**：

- `改 Humanizer`：换成 `Humanizer.click` / `press` / `type_text`，并按需加 `before_submit` / `after_type` / `after_navigate`。
- `保持原生`：不在本次移植范围，或有明确理由不能坐标点击（文件选择器、登录路径、纯失焦动作）。
- `待定（原因）`：需要 ticket 02/03 或真机才能定（`force=True` 白名单、搜索型输入、动画/浮层目标）。

**置信度**：本文件所有「行号 / 调用 / 分类 / 目标元素」均为 `[code]`（逐行读源码）。「打开时是否已有默认值」和「处置」中的非显然判断逐条带 `[inferred]` / `[needs-live]`，并写推断依据。默认值列的 `[inferred]` 默认依据是：选择器是 placeholder/空态文案、代码里没有清空动作也没有“沿用页面值”注释。`[needs-live]` = 需要真机打开页面确认（草稿恢复、文件名预填、账号级默认值）。

**两个全局事实（影响所有平台）**：

1. `Humanizer.click` 的前置检查 `utils/dom.py:check(..., "interactive")` 要求 **locator 的 `count()` 恰好为 1**（`utils/dom.py:484-486`），否则返回 `ambiguous:N` 并抛 `_not_dispatched`。现网大量调用点用裸 `get_by_role(...)` 而非 `.first`，移植时必须先收窄到唯一元素。`[code]`
2. `_HIT_TEST_JS`（`utils/dom.py:175-191`）在**元素所在 frame** 内用 `getBoundingClientRect` 计算落点，因此 dayu 正文 iframe、TikTok `frame_locator` 内的目标在 `stillOn` 复核上是成立的；`page.mouse` 用主 frame 坐标，Playwright `bounding_box()` 也返回主 frame 坐标，两者一致。`[code]`

---

## 1. 支付宝生活号 `uploader/alipay_uploader/main.py`

- 入口：`main.py:125`（登录）/ `main.py:824`（Multilogin 发布）各 `context.new_page()` 一次；**单 page**，无 popup、无新 tab。
- 发布页跳转：首页卡片 → `page.wait_for_url("**/content-creation/publish/short-video**")`（`main.py:438`）。
- 交互点共 14：`fill` 2、`click` 12（另有 `set_input_files` 2，见 §18）。

| 行号 | 调用 | 分类 | 字段语义 | 目标元素 | 打开时是否已有默认值 | 建议处置 |
| --- | --- | --- | --- | --- | --- | --- |
| 450 | `title_field.fill(value)` | 文本输入 | 标题 + `#话题`（`format_title_with_tags`，≤30 字） | `get_by_placeholder("一个好的标题，能获得更多人的喜欢哦")` → 单行 `input` | 否 `[inferred]`（placeholder 是空态文案，代码无“沿用页面值”） | 改 Humanizer（清空：全选；发布前 `before_submit`） |
| 457 | `desc_field.fill(self.desc)` | 文本输入 | 作品描述 | `get_by_placeholder("填写作品描述，让你的作品更容易被看到")` → `textarea` | 否 `[inferred]`（同上） | 改 Humanizer（清空：全选） |
| 204 | `...li[data-status='show_qr'].first.click(timeout=5000)` | 可坐标点击 | 登录：切到扫码 tab | `iframe[title="login"]` 内 `#J-loginMethod-tabs li` | — | 保持原生（登录路径，不在发布流程；且目标在 iframe 内） |
| 433 | `publish_entry.click()` | 导航或跳转点击 | 进发布表单（SPA 路由） | `a:has-text("发布视频推荐分辨率720p及以上…")` | — | 改 Humanizer + `after_navigate` |
| 467 | `cover_el.click(timeout=10000)` | 可坐标点击 | 打开「截取封面」弹窗 | `get_by_text("上传封面", exact=True).first` | — | 改 Humanizer |
| 475 | `inner.click(timeout=8000)` | 可坐标点击 | 弹窗内切到图片上传区 | `.antd5-modal-body` 内 `get_by_text("上传封面").first` | — | 改 Humanizer（外层已有 `count()` 守卫；坐标点击前仍需 `ensure_in_viewport`） |
| 481 | `upload_img_btn.click()` | 文件选择触发 | 展开图片上传区，随后直接 `set_input_files` | `get_by_role("button", name="上传图片").first` | — | 保持原生（与 `set_input_files` 成对；点击本身不是用户可见动作） |
| 495 | `done_btn.click()` | 可坐标点击 | 裁剪弹窗「完 成」 | `get_by_role("button", name="完 成"/"完成").first` | — | 改 Humanizer |
| 513 | `select.click(timeout=8000)` | 可坐标点击 | 打开合集下拉 | `input[id*="_compilationInfo"]` 的 `xpath=../../..` / `.antd5-select` | — | 改 Humanizer（先用 `.first` 收窄，当前有 2 个候选分支） |
| 521 | `target.click(timeout=5000, force=True)` | 隐藏或不可命中元素 | 选合集项（force 首选） | `[role="option"]` 过滤合集名 | — | 待定（force 白名单；去掉 force 失败后才落到 524） |
| 524 | `target.click(timeout=5000)` | 可坐标点击 | 同上（force 失败后滚动重试） | 同上 | — | 改 Humanizer（应合并 521/524 为一次坐标点击） |
| 697 | `btn.click(timeout=3000)` | 可坐标点击 | 质量提示弹窗「继续发布」放行提交 | `.antd5-modal-wrap/.antd5-modal button:has-text("继续发布")` | — | 改 Humanizer（提交语义仍由调用方持有） |
| 712 | `publish_btn.click()` | 导航或跳转点击 | 发布（提交） | 发布按钮（`publish_btn`） | — | 改 Humanizer + `before_submit` |
| 748 | `publish_btn.click()` | 导航或跳转点击 | AIGC 预处理完成后二次确认发布 | 同上 | — | 改 Humanizer + `before_submit`（仅在未观测到提交请求时补点） |

---

## 2. 百家号 `uploader/baijiahao_uploader/main.py`

- 单 page：`main.py:194`（登录）/ `main.py:446`（Multilogin 发布）。无 popup。
- 交互点共 13：`fill` 2、`click` 11（另 `set_input_files` 2，见 §18）。
- **注意**：标题是 `contenteditable`，但当前用 `fill()` 写入，且已有“点标题 → Ctrl+A → Backspace”手写清空（`main.py:503-505`）——这与 Humanizer 的清空策略完全同构，是最容易直接替换的一处。

| 行号 | 调用 | 分类 | 字段语义 | 目标元素 | 打开时是否已有默认值 | 建议处置 |
| --- | --- | --- | --- | --- | --- | --- |
| 506 | `title_field.fill(title)` | 富文本输入 | 标题（<8 字补“ 你不知道的”，截到 `max_title_length`） | `div[class*="contentEditable"]`（首个） | **是**：`[code]` 注释“清空原有内容（可能自动填了文件名）” | 改 Humanizer（保留现有全选清空，改成 `humanizer.press("Control+a")` + `press("Backspace")`） |
| 698 | `search_input.fill(self.collection_name)` | 文本输入 | 合集搜索过滤词 | `.cheetah-select` 内 `input.cheetah-select-selection-search-input` | 否 `[inferred]`（每次点开下拉都是空搜索框） | 待定（搜索型输入：逐字会触发多次过滤/请求；规格决定豁免或加 `after_type` 后只等一次结果） |
| 201 | `login_btn.click(timeout=10000)` | 可坐标点击 | 登录：拉起百度 passport 弹窗 | `get_by_text("登录", exact=True).first` | — | 保持原生（登录路径） |
| 503 | `title_field.click()` | 可坐标点击 | 聚焦标题编辑器（清空前） | 标题 `contenteditable` | — | 改 Humanizer（与 506 合并为一次 click + 清空 + type） |
| 584 | `cover_entry.click(timeout=10000)` | 可坐标点击 | 打开「选择封面」 | `[data-testid="select-cover"]` / `get_by_text("选择封面")` | — | 改 Humanizer |
| 593 | `upload_btn.click(timeout=8000)` | 文件选择触发 | 切到「上传」tab，随后 `set_input_files` | `button:has-text("上传")` / `get_by_text("上传")` | — | 保持原生（与文件输入成对） |
| 615 | `confirm_btn.click(timeout=8000)` | 可坐标点击 | 裁剪弹窗「确定/完成/确认」 | `button:has-text("确定"/"完成"/"确认").first` | — | 改 Humanizer |
| 641 | `trigger.click(force=True, timeout=8000)` | 隐藏或不可命中元素 | 打开「创作声明」弹窗 | `input[placeholder="请选择创作声明"]` | — | 待定（force 白名单：input 被组件覆盖；坐标点击可能点不中） |
| 649 | `ai_option.click(timeout=5000)` | 可坐标点击 | 选「含AI生成内容」 | `.cheetah-modal-wrap :text("含AI生成内容")` | — | 改 Humanizer |
| 657 | `confirm_btn.click(timeout=5000)` | 可坐标点击 | 关闭声明弹窗 | 弹窗内 `button:has-text("确定")` | — | 改 Humanizer |
| 692 | `select_box.click(timeout=8000)` | 可坐标点击 | 打开合集下拉 | `.cheetah-select:has(...合集...)` | — | 改 Humanizer |
| 704 | `option.click(timeout=5000)` | 可坐标点击 | 选合集项 | `[role="option"]` / `.cheetah-select-item` 精确匹配 | — | 改 Humanizer |
| 753 | `publish_btn.click(force=True)` | 隐藏或不可命中元素 | 发布（提交） | `[data-testid="publish-btn"]` / `button:text-is("发布")` | — | 待定（force 白名单：发布按钮是唯一出口，force 是保险；规格须先判定它是否真的被遮挡） |

---

## 3. 大鱼号 `uploader/dayu_uploader/`

文件与交互点：`main.py`（视频表单）、`article.py`（图文）、`schedule.py`（定时）、`publication.py`（发表/预览）。
共 36：`fill` 7、`click` 26、`set_input_files` 3。

- 单主 page（`main.py:239`、`article.py:303`）+ **第二个 tab**：`publication.py:64` 打开 `preview` 页做只读结构核对，`82` 关闭；预览页无点击。
- 视频标题是 `contenteditable`（`main.py:152`），简介是 `textarea`；图文正文在**独立 iframe** 内（`article.py:139` `frame_locator(ARTICLE_BODY)`），正文文字靠剪贴板粘贴，不是逐字输入。

| 行号 | 调用 | 分类 | 字段语义 | 目标元素 | 打开时是否已有默认值 | 建议处置 |
| --- | --- | --- | --- | --- | --- | --- |
| 153 | `title.fill(self.title)` | 富文本输入 | 视频标题（≥5 字） | `[contenteditable="true"][placeholder="视频标题最少5个字"]` | 未知 `[needs-live]`（无清空动作、无 placeholder 空态之外的证据；`fill` 会整体替换） | 改 Humanizer（清空策略前必须先确认是否预填） |
| 157 | `description.fill(self.desc)` | 文本输入 | 视频简介 | `.w-form-field:has(textarea) textarea` | 否 `[inferred]`（textarea 无预填迹象） | 改 Humanizer（清空：全选） |
| 173 | `inputs.nth(index).fill(tag)` | 文本输入 | 标签（第 N 个空槽） | `.article-write_video-tags input`（按槽位） | 否 `[inferred]`（`expect(inputs).to_have_count(index+1)` 证明是新空槽） | 改 Humanizer（逐字 + `press("Enter")`；`after_type` 会与 2s 标签等待叠加，需核算预算） |
| 199 | `original_link.fill(self.source_url)` | 文本输入 | 原文链接（仅转载） | `.source-remark-detail` 内 `label:has-text("原文链接")` 的 `input[type=text]` | 否 `[inferred]`（条件字段，选择“转载”后才出现） | 改 Humanizer（清空：全选） |
| 162 | `category.locator(".widgets-selects_container").click()` | 可坐标点击 | 打开「视频分类」下拉 | `.w-form-field` 内 `.widgets-selects_container` | — | 改 Humanizer |
| 163 | `category.get_by_role("link", name=self.category).click()` | 可坐标点击 | 选分类 | 分类下拉内 `role=link` | — | 改 Humanizer |
| 168 | `tags.click()` | 可坐标点击 | 聚焦标签组件 | `.article-write_video-tags` | — | 改 Humanizer（组件容器，可能零尺寸→需 `check` 失败兜底） |
| 175 | `title.click()` | 非交互（滚动、读取、等待） | 失焦标签组件，触发 Vue 归并 | 视频标题 | — | 保持原生（失焦用途；Humanizer 的落点复核无收益，且会触发编辑器 focus） |
| 185 | `dialog.get_by_role("button", name="保存").click()` | 可坐标点击 | 保存封面裁剪 | `.article-material-image-dialog:visible` 内「保存」 | — | 改 Humanizer |
| 141 | `body.click()` | 可坐标点击 | 聚焦 iframe 内正文（准备粘贴） | `frame_locator(ARTICLE_BODY)` → `body[contenteditable=true]` | — | 改 Humanizer（仅聚焦；粘贴仍走原生 Ctrl+A/Ctrl+V） |
| 147 | `page.locator("#title").click()` | 非交互（滚动、读取、等待） | 失焦正文，等编辑器稳定 | `#title` | — | 保持原生（同上，失焦动作） |
| 171 | `page.locator('.edui-toolbar [datatitle="分隔线"]').click()` | 可坐标点击 | 插入分隔线 | UEditor 工具栏 `datatitle="分隔线"` | — | 改 Humanizer（工具栏按钮小而密集，落点容错需 <1px 抖动） |
| 175 | `page.locator('.edui-toolbar [datatitle="插入图片"]').click()` | 可坐标点击 | 打开插图弹窗 | UEditor 工具栏 `datatitle="插入图片"` | — | 改 Humanizer |
| 186 | `dialog.get_by_role("button", name="确认").click()` | 可坐标点击 | 确认插入图片 | `.article-material-image-dialog:visible` 内「确认」 | — | 改 Humanizer |
| 195 | `page.locator("#title").click()` | 非交互（滚动、读取、等待） | 失焦正文，等插图稳定 | `#title` | — | 保持原生（失焦动作） |
| 200 | `page.locator("#title").click()` | 非交互（滚动、读取、等待） | 失焦正文，等正文规范化 | `#title` | — | 保持原生（失焦动作） |
| 247 | `option.locator(".w-radio").click()` | 可坐标点击 | 选封面模式（横版 N 图） | `.article-write-article-cover_normal-option` 内 `.w-radio` | — | 改 Humanizer（radio 本体常为 0 尺寸，实际点的是 `.w-radio` 装饰层，需真机确认可命中） |
| 253 | `slots.nth(...).locator("...cover-item").click()` | 可坐标点击 | 打开第 N 个封面槽的选图弹窗 | `.article-write-article-cover_normal-item` → `.article-write-article-cover-cover-item` | — | 改 Humanizer |
| 257 | `choices.nth(image_index - 1).click()` | 可坐标点击 | 选正文第 N 张图作封面 | 弹窗内 `.article-material-image_image-choose img` | — | 改 Humanizer |
| 259 | `dialog.get_by_role("button", name="下一步").click()` | 可坐标点击 | 裁剪下一步 | 弹窗内「下一步」 | — | 改 Humanizer |
| 261 | `dialog.get_by_role("button", name="保存").click()` | 可坐标点击 | 保存封面 | 弹窗内「保存」 | — | 改 Humanizer |
| 223 | `page.locator("#title").fill(self.title)` | 文本输入 | 图文标题 | `#title`（`input`） | 未知 `[needs-live]`（图文编辑无“已有草稿”守卫，可能恢复草稿） | 改 Humanizer（清空策略需真机确认；若可能恢复草稿，先读空再写） |
| 226 | `page.locator("#author input").fill(self.author)` | 文本输入 | 作者 | `#author input` | **是**：`[code]` 注释“作者缺省时沿用页面值” | 改 Humanizer，但清空=`none`（保留页面预填，仅当显式传 `author` 才覆盖） |
| 239 | `original.fill(self.source_url)` | 文本输入 | 原文链接（仅转载） | 来源区域 `label:has-text("原文链接")` 的 `input[type=text]` | 否 `[inferred]`（同视频表单） | 改 Humanizer |
| 65 | `toggle.click()` | 可坐标点击 | 关闭已选中的「定时发布」 | `.article-write_radio:visible` 内 `.w-radio` | — | 改 Humanizer（幂等开关，必须有读回校验兜底） |
| 74 | `toggle.click()` | 可坐标点击 | 打开「定时发布」 | 同上 | — | 改 Humanizer |
| 77 | `widget.locator(".widgets-datepicker-m_mask").click()` | 可坐标点击 | 点日期组件遮罩打开日历 | `.widgets-datepicker-m:visible` → `_mask` | — | 改 Humanizer（注释说明 input 被 mask 拦截，必须点 mask） |
| 86 | `days.locator("th.next").click()` | 可坐标点击 | 日历下个月 | `.datetimepicker-days th.next` | — | 改 Humanizer |
| 90 | `day.click()` | 可坐标点击 | 选日 | `.datetimepicker-days td.day:not(.old):not(.new)` | — | 改 Humanizer |
| 93 | `hour.click()` | 可坐标点击 | 选小时 | `.datetimepicker-hours .hour` | — | 改 Humanizer |
| 97 | `minute.click()` | 可坐标点击 | 选分钟 | `.datetimepicker-minutes .minute` | — | 改 Humanizer |
| 42 | `page.get_by_role("button", name="发表").click()` | 导航或跳转点击 | 图文「发表」→ 生成预览草稿 | 表单页「发表」 | — | 改 Humanizer + `before_submit` |
| 101 | `confirm.click()` | 导航或跳转点击 | 「确认发表」（不可逆提交） | 预览页「确认发表」 | — | 改 Humanizer + `before_submit`（且必须保留 `expect_response` 包裹） |

---

## 4. 抖音 `uploader/douyin_uploader/main.py`

- 单 page：`main.py:1099`（视频）/ `main.py:1425`（图文）；登录 `285`。无 popup、无新 tab。
- 交互点共 53：`fill` 5、`keyboard.type` 4、`hover` 1、`click` 38（另 `set_input_files` 5，见 §18）。
- 该文件已有一个**手写的坐标点击 helper** `_native_click`（`main.py:91-130`）：`scroll_into_view` → `bounding_box` → `mouse.move` → `mouse.click` → 再 `elementFromPoint` 派发一整套合成 pointer 事件。它是本平台最大的一处“与 Humanizer 重复实现”，见 §22。

| 行号 | 调用 | 分类 | 字段语义 | 目标元素 | 打开时是否已有默认值 | 建议处置 |
| --- | --- | --- | --- | --- | --- | --- |
| 465 | `title_input.fill(title[:30])` | 文本输入 | 作品标题（≤30） | `input[placeholder*="填写作品标题"].first` | 否 `[inferred]`（placeholder 空态） | 改 Humanizer（清空：全选） |
| 477 | `page.keyboard.type(description.strip())` | 富文本输入 | 作品描述 | `div.zone-container[contenteditable="true"].first` | 未知 `[needs-live]`（前一步已 Ctrl+A+Delete，说明作者预期有内容/占位） | 改 Humanizer（`type_text`；清空已手写，保留） |
| 480 | `page.keyboard.type(" #" + tag)` | 富文本输入 | 话题（`#tag` + Space 触发联想） | 同上 | 否 `[inferred]` | 改 Humanizer（`type_text` + `press("Space")`；逐字会触发联想，需 `after_type` 后再按 Space） |
| 490 | `page.keyboard.type(location)` | 文本输入 | 地理位置（`semi-select` 内可搜索 input） | `div.semi-select span:has-text("输入地理位置")` 所在组件 | 否 `[inferred]`（前一步按 Backspace） | 改 Humanizer（`type_text`，随后等联想列表） |
| 454 | `page.keyboard.type(str(publish_date_hour))` | 文本输入 | 定时日期时间（`YYYY-MM-DD HH:MM`） | `.semi-input[placeholder="日期和时间"]` | 是（点开 picker 后通常预填当前时间）`[needs-live]` | 改 Humanizer（清空：已 Ctrl+A；`type_text` 后 Enter） |
| 503 | `short_title_input.fill(product_title)` | 文本输入 | 商品短标题（≤10） | `input[placeholder="请输入商品短标题"]` | 否 `[inferred]` | 改 Humanizer |
| 539 | `input_field.fill(product_link)` | 文本输入 | 商品链接 | `input[placeholder="粘贴商品链接"]` | 否 `[inferred]` | 改 Humanizer（链接类：逐字会触发输入校验，`type_text` 后需等一次校验结果；见 §22 第 4 条同类问题） |
| 662 | `search_input.fill(bgm_name)` | 文本输入 | 配乐搜索词 | `.semi-sidesheet-content input[placeholder="搜索音乐"]` | 否 `[inferred]`（每次打开侧栏都是空） | 待定（搜索型输入：逐字发请求；规格决定豁免或 `after_type` 只等一次） |
| 839 | `sms_input.fill(code)` | 文本输入 | 短信验证码 | `input[placeholder*="验证码"/"短信"]` | 否 `[inferred]` | 保持原生（二次验证路径，不在正常发布流；且验证码有 60s 窗口） |
| 935 | `cover_area.hover(force=True)` | 可坐标点击（hover） | 揭出「编辑封面/选择封面」入口 | `[class*="cover-"]:has(img)` | — | 改 Humanizer（`Humanizer.hover`，去掉 force；注释说明封面入口 hover 后才渲染） |
| 105 | `locator.click(timeout=8000)` | 隐藏或不可命中元素 | `_native_click` 无 bounding_box 时的兜底 | 调用方传入的任意 locator | — | 待定（与 Humanizer 冲突：无 box 直接坐标点击必然失败；规格应删除此分支） |
| 114 | `page.mouse.click(x, y)` | 可坐标点击 | `_native_click` 的坐标点击本体 | 同上（box 中心） | — | 待定（已手写坐标点击但缺 stillOn；应整体替换为 `Humanizer.click`，并删掉后面的合成事件派发） |
| 337 | `expired_box.click()` | 可坐标点击 | 登录：二维码失效刷新 | `get_by_text("二维码失效", exact=True)` 的父节点 | — | 保持原生（登录路径） |
| 447 | `label_element.click()` | 可坐标点击 | 切「定时发布」 | `[class^='radio']:has-text('定时发布')` | — | 改 Humanizer |
| 452 | `...placeholder="日期和时间"].click()` | 可坐标点击 | 打开日期时间 picker | `.semi-input[placeholder="日期和时间"]` | — | 改 Humanizer |
| 471 | `description_editor.click()` | 可坐标点击 | 聚焦描述编辑器（准备清空） | `div.zone-container[contenteditable="true"]` | — | 改 Humanizer（与 477 合并为一次 click + 清空 + type） |
| 487 | `...span:has-text("输入地理位置")].click()` | 可坐标点击 | 打开地点下拉 | `div.semi-select span:has-text("输入地理位置")` | — | 改 Humanizer |
| 492 | `[role="listbox"] [role="option"].first.click()` | 可坐标点击 | 选地点候选 | 联想列表首项 | — | 改 Humanizer（首项选择：坐标点击会引入“点错候选”风险，需 stillOn 前后都校验文本） |
| 508 | `finish_button.click()` | 可坐标点击 | 商品弹窗「完成编辑」 | `button:has-text("完成编辑")` | — | 改 Humanizer |
| 516 | `cancel_button.click()` | 可坐标点击 | 商品弹窗「取消」 | `button:has-text("取消")` | — | 改 Humanizer |
| 519 | `close_button.click()` | 可坐标点击 | 商品弹窗右上关闭 | `.semi-modal-close` | — | 改 Humanizer |
| 532 | `dropdown.click()` | 可坐标点击 | 打开「添加标签」下拉 | 文本「添加标签」上溯 3 层的 `.semi-select` | — | 改 Humanizer |
| 534 | `[role="option"]:has-text("购物车").click()` | 可坐标点击 | 选「购物车」 | `role=option` | — | 改 Humanizer |
| 547 | `add_button.click()` | 可坐标点击 | 「添加链接」 | `span:has-text("添加链接")` | — | 改 Humanizer（需先读 class 判定 disabled，保持现有前置校验） |
| 554 | `confirm_button.click()` | 可坐标点击 | 无效商品提示「确定」 | `button:has-text("确定")` | — | 改 Humanizer |
| 598 | `entry.click(timeout=6000)` | 可坐标点击 | 打开「自主声明」弹窗 | `get_by_text` 命中「请选择自主声明/声明类型/…」 | — | 改 Humanizer（5 个候选文案，需先收敛为唯一 locator） |
| 620 | `option.click(timeout=6000)` | 可坐标点击 | 选声明类型 | 弹窗内 `label.semi-radio` 过滤文案 | — | 改 Humanizer |
| 624 | `...first.click(timeout=6000, force=True)` | 隐藏或不可命中元素 | 声明文案兜底（`option.count()==0` 时） | 弹窗内 `get_by_text(declaration)` | — | 待定（force 白名单；正常分支 620 已覆盖，此分支只在 DOM 变异时触发） |
| 634 | `confirm_btn.click(timeout=6000)` | 可坐标点击 | 声明弹窗「确定」 | `button.semi-button-primary:has-text("确定")` | — | 改 Humanizer |
| 655 | `music_entry.click()` | 可坐标点击 | 打开「选择音乐」侧边栏 | `text="选择音乐"` | — | 改 Humanizer |
| 686 | `apply_btn.evaluate("el => el.click()")` | 隐藏或不可命中元素 | 应用 BGM（按钮 `visibility:hidden`） | `.apply-btn-LUPP0D` | — | 待定（禁令：不得 `el.click()`；注释说明按钮 hidden，规格须找可点父级或保留原生例外并登记） |
| 708 | `close_btn.click()` | 可坐标点击 | 关闭音乐侧边栏 | `.semi-sidesheet-close` | — | 改 Humanizer |
| 806 | `selection.click(timeout=5000)` | 可坐标点击 | 打开合集下拉 | `[class*="select-collection-"] .semi-select-selection` | — | 改 Humanizer |
| 824 | `option.first.click(timeout=5000)` | 可坐标点击 | 选合集项 | `.semi-select-option.collection-option` 精确标题 | — | 改 Humanizer |
| 838 | `sms_input.click()` | 可坐标点击 | 聚焦验证码输入 | 验证码 `input` | — | 保持原生（二次验证路径） |
| 846 | `verify_btn.click(force=True)` | 隐藏或不可命中元素 | 短信「验证」按钮 | `div.uc-ui-verify_sms-verify_button` | — | 待定（force 白名单 + 后面还有 849 JS 兜底，整条链需重设计） |
| 849 | `page.eval_on_selector(..., 'el => el.click()')` | 隐藏或不可命中元素 | 同上（force 失败后 JS 兜底） | 同上 | — | 待定（禁令冲突；见 §16） |
| 854 | `verify_by_text.click(force=True)` | 隐藏或不可命中元素 | 「验证」文案兜底 | `get_by_text("验证", exact=True)` | — | 待定（force 白名单） |
| 890 | `recommend_cover.click()` | 可坐标点击 | 选第一个推荐封面 | `[class^="recommendCover-"]` | — | 改 Humanizer |
| 895 | `page.get_by_role("button", name="确定").click()` | 可坐标点击 | 确认应用封面 | 弹窗「确定」 | — | 改 Humanizer |
| 978 | `cover_locator.get_by_text("设置竖封面").first.click()` | 可坐标点击 | 切到竖封面页 | 封面弹窗内文案 | — | 改 Humanizer |
| 987 | `cover_locator.get_by_text("设置横封面").first.click()` | 可坐标点击 | 切到横封面页 | 同上 | — | 改 Humanizer |
| 1020 | `btn.click(timeout=4000)` | 可坐标点击 | 封面弹窗「完成」（循环 4 次） | `cover_locator` 内 `button:has-text("完成")` | — | 待定（循环里普通 click 常“点了没关”，随后 `_native_click`；坐标点击也会遇到同一问题，需保留“点后校验 detach”结构） |
| 1197 | `...locator("input.semi-switch-native-control").click()` | 隐藏或不可命中元素 | 打开第三方同步开关 | `div[class^="info"] … .semi-switch` 内的原生 checkbox | — | 待定（应改为点 `.semi-switch` 可见装饰层；原生 input 通常 0 尺寸） |
| 1227 | `get_code_btn.click()` | 可坐标点击 | 登录/验证：获取验证码 | `get_by_text("获取验证码")` | — | 保持原生（二次验证路径） |
| 1241 | `publish_button.click(force=True)` | 隐藏或不可命中元素 | 视频发布（提交） | `get_by_role("button", name="发布", exact=True)` | — | 待定（force 白名单：发布按钮；规格须先量它是否被浮层覆盖） |
| 1328 | `page.get_by_text("发布图文", exact=True).click()` | 导航或跳转点击 | 切到图文发布页 | 首页「发布图文」 | — | 改 Humanizer + `after_navigate` |
| 1377 | `publish_button.click()` | 导航或跳转点击 | 图文发布（提交） | `get_by_role("button", name="发布", exact=True)` | — | 改 Humanizer + `before_submit` |

---

## 5. 虎扑 `uploader/hupu_uploader/main.py`

- 单 page：`main.py:122`（登录）/ `main.py:175`（prepared context）/ `main.py:483`（Multilogin 发布）。无 popup。
- 交互点共 15 真实调用（另有 2 行注释形式的“录制脚本”也命中 `.click(`，见 §21.1）：`fill` 2、`click` 13。
- 视频上传与封面上传都是 `expect_file_chooser` + `file_chooser.set_files`，不经 `set_input_files`。

| 行号 | 调用 | 分类 | 字段语义 | 目标元素 | 打开时是否已有默认值 | 建议处置 |
| --- | --- | --- | --- | --- | --- | --- |
| 538 | `title_field.fill(title)` | 文本输入 | 标题（4–40 字） | `get_by_placeholder("请输入标题（最少4个字，最多40个字）")` | 否 `[inferred]`（placeholder 空态） | 改 Humanizer（清空：全选） |
| 556 | `desc_field.fill(content)` | 文本输入 | 简介（正文 + `#tag#`） | `get_by_placeholder("请输入简介")` | 否 `[inferred]` | 改 Humanizer（清空：全选） |
| 240 | `qq_btn.click()` | 可坐标点击 | 登录：QQ 登录 | `get_by_role("button", name="qq QQ登录")` | — | 保持原生（登录路径） |
| 520 | `upload_btn.click()` | 文件选择触发 | 视频上传（`expect_file_chooser` 内） | 上传按钮（`_upload_video_file`） | — | 保持原生（与 `file_chooser.set_files` 配对） |
| 537 | `title_field.click()` | 可坐标点击 | 聚焦标题 | 标题 `input` | — | 改 Humanizer（与 538 合并） |
| 555 | `desc_field.click()` | 可坐标点击 | 聚焦简介 | 简介 `input/textarea` | — | 改 Humanizer（与 556 合并） |
| 567 | `cover_span.click()` | 文件选择触发 | 换封面（`expect_file_chooser` 内） | `span` 过滤「更换封面」 | — | 保持原生（与 `file_chooser.set_files` 配对） |
| 582 | `add_zone_btn.click()` | 可坐标点击 | 打开「添加专区」 | `get_by_label("发视频").get_by_text("添加专区")` | — | 改 Humanizer |
| 588 | `step_street.click()` | 可坐标点击 | 选「步行街」 | 专区弹窗内 `div` 精确文本 | — | 改 Humanizer（`div` 内套文本，落点可能命中子节点，`stillOn` 用 `el.contains(hit)` 可过） |
| 593 | `main_road.click()` | 可坐标点击 | 选「步行街主干道」 | `get_by_text("步行街主干道")` | — | 改 Humanizer |
| 598 | `confirm_btn.click()` | 可坐标点击 | 专区「确 定」 | `get_by_role("button", name="确 定")` | — | 改 Humanizer |
| 610 | `declaration_btn.click(timeout=5000)` | 可坐标点击 | 「原创/二创」声明 | `get_by_role("button", name="原创/二创")` | — | 改 Humanizer |
| 620 | `combobox.click(timeout=5000)` | 可坐标点击 | 打开 AI 声明下拉 | `get_by_role("combobox")` | — | 待定（裸 `get_by_role("combobox")` 可能多匹配，`check` 会因 `ambiguous:N` 拒绝） |
| 625 | `ai_option.click(timeout=5000)` | 可坐标点击 | 选「含AI生成内容」 | `get_by_text("含AI生成内容")` | — | 改 Humanizer |
| 645 | `publish_btn.click()` | 导航或跳转点击 | 「确定发布」（提交，跳帖子页） | `get_by_label("发视频").get_by_text("确定发布")` | — | 改 Humanizer + `before_submit` |

---

## 6. 快手 `uploader/ks_uploader/main.py`

- 单 page：`main.py:760`（视频）/ `main.py:1081`（图文）；登录 `209`。无 popup。
- 交互点共 28：`keyboard.type` 4、`click` 21、`set_input_files` 3。
- 两处输入是 `contenteditable`（描述/图文正文），且已有手写清空：`Backspace` → `Control+KeyA` → `Delete`（`main.py:795-797`、`968-970`）。
- 定时日期**不是**键入：`528` 只用点击打开 picker，随后用原生 setter + 冒泡事件直接写 `input.value`（`main.py:530+`）。这是唯一一处“看起来是文本输入、实际绕过交互层”的字段。

| 行号 | 调用 | 分类 | 字段语义 | 目标元素 | 打开时是否已有默认值 | 建议处置 |
| --- | --- | --- | --- | --- | --- | --- |
| 798 | `page.keyboard.type(self.desc or self.title)` | 富文本输入 | 视频描述 | `_focus_desc_editor` 定位的 `div[contenteditable=true]` | 未知 `[needs-live]`（先按 Backspace 再全选删除，作者预期可能有占位残留） | 改 Humanizer（`type_text`；保留现有清空序列） |
| 803 | `page.keyboard.type(f"#{tag} ")` | 富文本输入 | 话题（最多 3 个） | 同上 | 否 `[inferred]` | 改 Humanizer（逐字会触发话题联想，`after_type` 后再输入空格） |
| 971 | `page.keyboard.type(self.note)` | 富文本输入 | 图文正文 | 同上（图文 tab 的描述编辑器） | 未知 `[needs-live]`（同 798） | 改 Humanizer |
| 976 | `page.keyboard.type(f"#{tag} ")` | 富文本输入 | 图文话题 | 同上 | 否 `[inferred]` | 改 Humanizer |
| 110 | `loc.click(force=True)` | 隐藏或不可命中元素 | 聚焦描述编辑器（4 级回退定位） | `_focus_desc_editor` 的候选 locator | — | 待定（force 白名单：回退策略下目标可能零尺寸；正常策略 #0 是可见的） |
| 133 | `primary_button.click(timeout=8000)` | 可坐标点击 | 发布确认弹窗主动作 | `.ant-modal-confirm-centered button.ant-btn-primary` | — | 改 Humanizer |
| 267 | `platform_switch.click()` | 可坐标点击 | 登录：切到二维码登录 | `main#login-form div.platform-switch` | — | 保持原生（登录路径） |
| 272 | `platform_switch.click()` | 可坐标点击 | 同上（异常分支重试） | 同上 | — | 保持原生（登录路径） |
| 443 | `refresh_button.click()` | 可坐标点击 | 登录：二维码刷新 | `p.qrcode-refresh` | — | 保持原生（登录路径） |
| 524 | `...filter(has_text="定时发布").click()` | 可坐标点击 | 切「定时发布」 | `label.ant-radio-wrapper` | — | 改 Humanizer |
| 528 | `input[placeholder="选择日期时间"].click()` | 可坐标点击 | 打开日期时间 picker | `input[placeholder="选择日期时间"]` | — | 改 Humanizer（但后续值由 JS setter 写入，日期本身不进入交互层；见 §22） |
| 582 | `btn.first.click(force=True)` | 隐藏或不可命中元素 | 关 Joyride 引导层 | `div[role="alertdialog"]` 内多个关闭候选 | — | 待定（force 白名单：遮罩层内目标；引导层本身不在用户正常路径） |
| 661 | `trigger.locator(".ant-select-selector").click(timeout=8000)` | 可坐标点击 | 打开「加入合集」下拉 | `label:text-is("加入合集")` 的兄弟 `ant-select` | — | 改 Humanizer |
| 673 | `option.first.click(timeout=8000)` | 可坐标点击 | 选合集项 | `div.ant-select-item-option[label="…"]` | — | 改 Humanizer |
| 703 | `...locator('div').nth(0).click()` | 可坐标点击 | 打开封面设置弹窗 | 「封面设置」label 的下一个兄弟 `div` 的第 0 个子 `div` | — | 待定（`div` 无文本、落点不稳；坐标点击需真机确认命中区域） |
| 710 | `upload_cover_tab.click()` | 可坐标点击 | 切「上传封面」tab | 弹窗内 `get_by_text("上传封面", exact=True)` | — | 改 Humanizer |
| 719 | `confirm_button.click()` | 可坐标点击 | 确认封面 | 弹窗 `get_by_role("button", name="确认")` | — | 改 Humanizer |
| 776 | `upload_button.click()` | 文件选择触发 | 视频上传（`expect_file_chooser` 内） | `button[class^='_upload-btn']` | — | 保持原生（与 `file_chooser.set_files` 配对） |
| 785 | `know_button.click()` | 可坐标点击 | 关「我知道了」弹窗 | `button[type="button"] span:text("我知道了")` | — | 改 Humanizer（notice 类；可考虑直接 `保持原生` 以免增加停顿） |
| 866 | `publish_button.click()` | 导航或跳转点击 | 视频发布（提交） | `get_by_text("发布", exact=True)` | — | 改 Humanizer + `before_submit`（随后还会调 133 确认弹窗） |
| 945 | `...:has-text("图文")].click()` | 导航或跳转点击 | 切到图文 tab | `div[role="tablist"] div[role="tab"]` | — | 改 Humanizer + `after_navigate` |
| 953 | `upload_button.click()` | 文件选择触发 | 图文图片上传（`expect_file_chooser` 内） | `button[class^='_upload-btn']:has-text("上传图片")` | — | 保持原生（与 `file_chooser.set_files` 配对） |
| 960 | `know_button.click()` | 可坐标点击 | 关「我知道了」弹窗 | 同上 | — | 改 Humanizer / 保持原生（同 785） |
| 1026 | `publish_button.click()` | 导航或跳转点击 | 图文发布（提交） | `get_by_text("发布", exact=True)` | — | 改 Humanizer + `before_submit` |
| 1031 | `confirm_button.click()` | 可坐标点击 | 发布后确认弹窗 | 弹窗「确认」 | — | 改 Humanizer |

---

## 7. Facebook（个人主页）`uploader/meta_uploader/facebook_uploader/`

- 单 page：`main.py:96`（登录）/ `main.py:117`（login）/ `main.py:198`（Multilogin 发布）。
- 交互点共 10：`fill` 1、`click` 8、`set_input_files` 1。
- `posts.py` 是**发布后的删除/管理路径**（`trash_facebook_post`、`facebook_post_action`），与发布流分开调用。

| 行号 | 调用 | 分类 | 字段语义 | 目标元素 | 打开时是否已有默认值 | 建议处置 |
| --- | --- | --- | --- | --- | --- | --- |
| 347 | `editor.fill(caption)` | 富文本输入 | 正文（标题 + 描述 + `#tag`，`\n\n` 连接） | `_find_caption_editor(page)` → `[role="dialog"] [contenteditable="true"][role="textbox"]` | 否 `[inferred]`（composer 新建，读回校验 `inner_text()==caption`） | 改 Humanizer（`type_text`；清空：全选） |
| 346 | `editor.click()` | 可坐标点击 | 聚焦正文 | 同上 | — | 改 Humanizer（与 347 合并） |
| 312 | `publish_button.click()` | 导航或跳转点击 | 「发布」（提交） | `_publish_and_verify` 内发布按钮 | — | 改 Humanizer + `before_submit` |
| 100 | `menu_button.click()` | 可坐标点击 | 作品「更多选项」菜单 | `menu_button`（行内 `role=button`） | — | 保持原生（删除路径，破坏性操作；是否纳入由规格定） |
| 103 | `menu.get_by_role("menuitem", ...).click()` | 可坐标点击 | 「移至垃圾箱」 | 菜单项 | — | 保持原生（删除路径） |
| 107 | `dialog.get_by_role("button", name="转移").click()` | 可坐标点击 | 确认转移 | 确认弹窗 | — | 保持原生（删除路径） |
| 175 | `row.get_by_role("button", name=...更多选项).click()` | 可坐标点击 | 行内更多选项 | 行内 `role=button` | — | 保持原生（删除路径） |
| 176 | `page.get_by_role("menu")...menuitem(name="删除").click()` | 可坐标点击 | 删除 | 菜单项 | — | 保持原生（删除路径） |
| 179 | `dialog.get_by_role("button", name="删除").click()` | 可坐标点击 | 确认删除 | 确认弹窗 | — | 保持原生（删除路径） |

---

## 8. Facebook Page / Business Suite `uploader/meta_uploader/facebook_page_uploader/`

- 单 page：`main.py:90`（登录）/ `main.py:131`（login）/ `main.py:200`（Multilogin）/ `main.py:543`（发布）。
- 交互点共 22：`fill` 2、`click` 20（媒体报道上传走 `expect_file_chooser` + `set_files`，没有 `set_input_files`）。
- 定时表单小时/分钟不是 `keyboard.type`，而是 `control.press(digit)` 逐键（`main.py:419`），已是逐字符节奏。

| 行号 | 调用 | 分类 | 字段语义 | 目标元素 | 打开时是否已有默认值 | 建议处置 |
| --- | --- | --- | --- | --- | --- | --- |
| 321 | `reels_title.fill(self.title)` | 文本输入 | Reel 独立标题 | `[data-surface$="bizweb_create_reel:left_panel"] input[type="text"]:not([role]):visible` | 否 `[inferred]`（`separate_title` 分支，页面无预填证据） | 改 Humanizer（清空：全选） |
| 332 | `editor.fill(caption)` | 富文本输入 | 正文（标题/描述/标签） | `[contenteditable="true"]:visible`（向导内唯一） | 否 `[inferred]`（读回校验 `inner_text()`） | 改 Humanizer（`type_text`；清空：全选） |
| 106 | `close.click()` | 可坐标点击 | 关引导说明卡 | `[data-surface$="lib:GeoGuidanceCard"] [role="button"]:not([aria-label]):visible` | — | 改 Humanizer / 保持原生（引导卡；建议保持原生以免每条都加停顿） |
| 275 | `combo.click()` | 可坐标点击 | 打开发布主体下拉 | `role=combobox` + `img[alt="Facebook"]` | — | 改 Humanizer |
| 279 | `option.click()` | 可坐标点击 | 选指定 Page | `get_by_role("option", name=self.page_name)` | — | 改 Humanizer |
| 301 | `trigger.click()` | 文件选择触发 | 打开媒体文件选择器（`expect_file_chooser`） | `media.get_by_role('button').nth(0)` | — | 保持原生（与 `set_files` 配对） |
| 350 | `actions.nth(1).click()` | 导航或跳转点击 | Reel 向导「下一步」×2 | `[data-surface$="…:footer"] [role="button"]:not([aria-label])` 第 2 个 | — | 改 Humanizer |
| 357 | `story.click()` | 可坐标点击 | 关闭「同时发快拍」开关 | `input[role="switch"]`（Page 品牌限定） | **是**：`[code]` 开关默认 checked，代码 `if await story.is_checked(): await story.click()` | 改 Humanizer（幂等：先读状态；`check` 对 input 有效） |
| 365 | `actions.nth(2).click()` | 可坐标点击 | 快拍确认弹窗主动作 | 弹窗 `role=button` 第 3 个 | — | 待定（按序号取按钮；坐标点击放大“点错序号”风险，规格应改为按文本/aria 定位） |
| 381 | `modes.nth(1).click()` | 可坐标点击 | 切「定时」模式 | `[role="button"][aria-pressed]` 第 2 个 | — | 待定（按序号取；同 365） |
| 389 | `date_input.click()` | 可坐标点击 | 打开日期日历 | `input[placeholder]:not([role])`（唯一） | — | 改 Humanizer |
| 406 | `navigation.nth(1 if month_delta > 0 else 0).click()` | 可坐标点击 | 日历上/下月 | `[role="button"][aria-busy]` 两枚 | — | 改 Humanizer |
| 413 | `day.click()` | 可坐标点击 | 选日 | `grid.get_by_role('button')` 精确日号 | — | 改 Humanizer |
| 419 | `control.click()` | 可坐标点击 | 聚焦小时/分钟 spinbutton | `[role="spinbutton"]` | **是**：`[code]` 组件有 `aria-valuenow`，随后 `press(digit)` 覆盖 | 改 Humanizer（click 可人类化；后续 `press` 已逐键） |
| 465 | `button.click()` | 导航或跳转点击 | 「发布/分享」（提交） | `_publish` 的主按钮 | — | 改 Humanizer + `before_submit` |
| 499 | `completion.get_by_role('button').last.click()` | 可坐标点击 | Reel 完成框关闭 | 完成弹窗最后一个按钮 | — | 待定（`.last` 取按钮；坐标点击需先确认唯一） |
| 42 | `title.click()` | 导航或跳转点击 | 列表进入作品详情（URL 变化） | `[role="gridcell"][data-surface$=":TITLE"]` / `[role="button"][aria-pressed]` | — | 保持原生（作品管理路径） |
| 105 | `menu_button.click()` | 可坐标点击 | 详情「更多选项」 | 详情面板内 `role=button[aria-haspopup=menu]` | — | 保持原生（删除路径） |
| 111 | `items.nth(count - 1).click()` | 可坐标点击 | 删除（菜单末项） | `role=menuitem` 末项 | — | 保持原生（删除路径） |
| 115 | `dropdown.click()` | 可坐标点击 | 成效页动作下拉 | `[data-surface$="…HeaderActionDropdown"] [aria-haspopup=menu]` | — | 保持原生（删除路径） |
| 118 | `action.click()` | 可坐标点击 | 删除动作 | `[data-surface$="…DeleteAction"] [role=menuitem]` | — | 保持原生（删除路径） |
| 126 | `actions.nth(1).click()` | 可坐标点击 | 删除确认框主动作 | 确认框 `role=button` 第 2 个 | — | 保持原生（删除路径） |

---

## 9. Instagram `uploader/meta_uploader/insgraph_uploader/`

- 单 page：`main.py:264`（登录）/ `main.py:297`（login）/ `main.py:397`（Multilogin）/ `main.py:946`（发布）。
- grep 命中 22 次 / 20 个唯一行；去掉 4 行注释/文档字符串后为 **16 个调用点**：`fill` 3、`press_sequentially` 1、`click` 8、`evaluate` 2（el.click 兜底）、`set_input_files` 2。
- 该平台已有两个“键盘优先 + JS 兜底”的通用 helper：`controls/_rows.py:activate`（focus+Enter → click → el.click）与 `click_control`（click → focus+Space → el.click）。它们是移植时**最需要先改的公共底座**，否则每个调用点都自带一条 `el.click()` 后路。

| 行号 | 调用 | 分类 | 字段语义 | 目标元素 | 打开时是否已有默认值 | 建议处置 |
| --- | --- | --- | --- | --- | --- | --- |
| 799 | `editor.fill(caption)` | 富文本输入 | 配文（标题 + 描述 + 标签） | `_caption_editor(dialog)` → Lexical `[data-lexical-editor]` / contenteditable | 否 `[inferred]`（读回 `to_have_text(caption)`） | 改 Humanizer（`type_text`；清空：全选；Lexical 对逐字输入敏感，需真机验证） |
| 190 | `entry.fill('')` | 文本输入 | 清空地点输入（仅第 2 次重试） | 地点联想输入框 | — | 保持原生（清空动作，不是用户输入；用 `Humanizer.press("Control+a")`+`Backspace` 亦可） |
| 191 | `entry.press_sequentially(requested, delay=TYPE_DELAY_MS)` | 文本输入 | 地点名（逐字触发联想） | 地点联想输入框 | 否 `[inferred]`（清空后输入） | 改 Humanizer（`type_text` 语义等价；但此处有 debounce 竞态，逐字节奏不能比 `TYPE_DELAY_MS` 更快） |
| 224 | `field.fill(text)` | 文本输入 | 图片 Alt text（逐张，1..1000） | Alt text 输入框 `inputs.nth(index)` | 未知 `[needs-live]`（编辑页可能回填已保存的 alt） | 改 Humanizer（清空：显式全选；注意 226 必须失焦才写入页面状态） |
| 142 | `dismiss_button.click()` | 可坐标点击 | 关可选提示 | `_dismiss_optional_prompt` 传入的按钮 | — | 改 Humanizer（仅 1.5s 窗口内出现；坐标点击会多耗 0.5-1s，需核算） |
| 546 | `entry.click()` | 导航或跳转点击 | 打开「创建」弹窗 | `_create_entry(page)` | — | 改 Humanizer |
| 631 | `action.click()` | 可坐标点击 | 裁剪页「下一步」 | `_primary_action(dialog)` | — | 改 Humanizer |
| 842 | `action.click()` | 导航或跳转点击 | 「分享」（提交） | `_primary_action(dialog)` | — | 改 Humanizer + `before_submit`（必须在 `expect`/响应监听之后） |
| 89 | `menu_button.click()` | 可坐标点击 | 作品「更多选项」 | 行内菜单按钮 | — | 保持原生（管理路径） |
| 106 | `row.click(timeout=...)` | 可坐标点击 | 展开折叠行 | `row` locator | — | 改 Humanizer（但应先走 `press_enter`；坐标点击只作兜底） |
| 121 | `locator.click(timeout=...)` | 可坐标点击 | 开关等控件 | 调用方 locator | — | 改 Humanizer |
| 241 | `node.click(timeout=...)` | 可坐标点击 | 选地点联想候选（ElementHandle） | 联想行元素句柄 | — | 待定（注释实测：联想行只响应真实指针事件，`el.click()` 无效；坐标点击可行但需先把 ElementHandle 换成 Locator） |
| 110 | `row.evaluate("el => el.click()")` | 隐藏或不可命中元素 | 展开行兜底 | 同上 | — | 待定（禁令：不得 `el.click()`；应删除该级兜底） |
| 130 | `locator.evaluate("el => el.click()")` | 隐藏或不可命中元素 | 控件点击兜底 | 同上 | — | 待定（禁令：不得 `el.click()`；应删除该级兜底） |

---

## 10. 视频号 `uploader/tencent_uploader/main.py`

- 单 page：`main.py:162`（登录）/ `main.py:343`（login）/ `main.py:512`（prepared）/ `main.py:1311`、`1445`（Multilogin）。
- 交互点共 34：`fill` 1、`keyboard.type` 4、`click` 27、`set_input_files` 2。
- 三处用 `page.click(selector)` 简写（`671`、`676`、`687`）——`Humanizer.click` 只接受 locator，这三处必须先改写成 `page.locator(selector)`。`[code]`
- 大编辑区 `div.input-editor` 是**视频描述**，真正的「短标题」是 `input[placeholder="填写短标题有机会获得更多流量"]`（`main.py:817` 注释）。这是最容易把字段语义搞混的一处。

| 行号 | 调用 | 分类 | 字段语义 | 目标元素 | 打开时是否已有默认值 | 建议处置 |
| --- | --- | --- | --- | --- | --- | --- |
| 830 | `field.fill(value)` | 文本输入 | 短标题（`format_str_for_short_title`，7–15 字） | `input[placeholder="填写短标题有机会获得更多流量"]` / 「短标题」兄弟 `input[type=text]` | 否 `[inferred]`（placeholder 空态；代码无清空） | 改 Humanizer（清空：全选） |
| 865 | `page.keyboard.type(self.title)` | 富文本输入 | 视频描述（注释：大编辑区其实是“视频描述”） | `div.input-editor` | 未知 `[needs-live]`（无清空动作；上传后可能带文件名/草稿） | 改 Humanizer（`type_text`；先确认是否预填，再定清空策略） |
| 868 | `page.keyboard.type("#" + tag)` | 富文本输入 | 话题 | 同上 | 否 `[inferred]` | 改 Humanizer（`type_text` + `press("Space")`） |
| 874 | `page.keyboard.type(self.desc)` | 富文本输入 | 描述正文（`fill_title_and_tags` 之后追加） | 同上 | 否 `[inferred]`（同一编辑器，前面刚输入标题） | 改 Humanizer |
| 689 | `page.keyboard.type(publish_date.strftime("%H"))` | 文本输入 | 定时小时（两位） | `input[placeholder="请选择时间"]` | 是（picker 打开后带当前时间）`[needs-live]` | 改 Humanizer（清空：已 Ctrl+A；`type_text` 后 Enter） |
| 424 | `refresh_wrap.click()` | 可坐标点击 | 登录：二维码刷新 | `div.login-qrcode-wrap … .refresh-wrap` 多个候选 | — | 保持原生（登录路径） |
| 442 | `refresh_wrap.click()` | 可坐标点击 | 同上（多选择器循环） | 同上 | — | 保持原生（登录路径） |
| 444 | `tip.click()` | 可坐标点击 | 同上（点提示文案） | `p.refresh-tip` | — | 保持原生（登录路径） |
| 451 | `fallback_refresh.click()` | 可坐标点击 | 同上（兜底） | `div.login-qrcode-wrap div.refresh-wrap` | — | 保持原生（登录路径） |
| 670 | `label_element.click()` | 可坐标点击 | 切「定时」 | `label` 过滤「定时」第 2 个 | — | 待定（`.nth(1)` 按序号取 label；坐标点击前应收敛为唯一 locator） |
| 671 | `page.click('input[placeholder="请选择发表时间"]')` | 可坐标点击 | 打开日期面板 | 同 selector | — | 改 Humanizer（需改写为 locator） |
| 676 | `page.click("button.weui-desktop-btn__icon__right")` | 可坐标点击 | 日历下个月 | 同 selector | — | 改 Humanizer（需改写为 locator） |
| 684 | `element.click()` | 可坐标点击 | 选日（从 `query_selector_all` 得到的 ElementHandle） | `table.weui-desktop-picker__table a` | — | 待定（ElementHandle 不是 Locator；坐标点击需换成 locator，且日期格可能受遮挡） |
| 687 | `page.click('input[placeholder="请选择时间"]')` | 可坐标点击 | 打开时间下拉 | 同 selector | — | 改 Humanizer（需改写为 locator） |
| 694 | `div.input-editor.click(timeout=5000)` | 非交互（滚动、读取、等待） | 收起时间浮层（点描述区） | `div.input-editor` | — | 保持原生（仅为收浮层；失败已按 Escape 兜底） |
| 741 | `publish_entry.click()` | 导航或跳转点击 | 首页「发表视频」进入表单 | `publish_entry`（`open_upload_page`） | — | 改 Humanizer + `after_navigate` |
| 794 | `candidate.click(force=True)` | 隐藏或不可命中元素 | 「发表视频」按钮（轮询所有 button 找到的候选） | `get_by_role("button")` 逐个 `inner_text()` 命中 | — | 待定（force 白名单；注释说明 Patchright 按名匹配不稳，已退化为扫描按钮） |
| 843 | `cand.click(timeout=2000)` | 可坐标点击 | 关「切换视频号」弹窗（取消/×） | `.changeAccount-dialog` 内两候选 | — | 改 Humanizer（弹窗类；2s 超时偏短，人类化后需放宽） |
| 858 | `div.input-editor.click(timeout=5000)` | 可坐标点击 | 聚焦描述（4 次重试，成功标志） | `div.input-editor` | — | 改 Humanizer（与 865 合并；注意重试循环语义） |
| 864 | `div.input-editor.click(timeout=8000)` | 可坐标点击 | 同上（4 次都失败后最后一击） | 同上 | — | 改 Humanizer |
| 891 | `dropdown.click(timeout=8000)` | 可坐标点击 | 打开「添加到合集」 | `get_by_text("添加到合集")` 的兄弟 `div` | — | 改 Humanizer |
| 915 | `target.click(timeout=4000)` | 可坐标点击 | 选合集项 | `.option-list-wrap .option-item` 精确 `.name` | — | 改 Humanizer |
| 918 | `target.click(force=True, timeout=4000)` | 隐藏或不可命中元素 | 同上（headless 视口外时的 force） | 同上 | — | 待定（force 白名单；注释已写明 headless 小视口原因） |
| 940 | `entry.click()` | 可坐标点击 | 打开「选择视频标注」 | `get_by_text("选择视频标注", exact=True)` | — | 改 Humanizer |
| 944 | `option.click()` | 可坐标点击 | 选「含AI生成内容」 | `get_by_text(label_text, exact=True)` | — | 改 Humanizer |
| 1074 | `publish_btn.click(timeout=4000)` | 导航或跳转点击 | 发表/存草稿（提交） | `publish_btn`（最多 20 轮重试） | — | 改 Humanizer + `before_submit` |
| 1076 | `publish_btn.evaluate("el => el.click()")` | 隐藏或不可命中元素 | 同上（普通 click 超时后的 JS 兜底） | 同上 | — | 待定（禁令冲突；见 §16） |
| 1162 | `...tag-inner:has-text("删除")].click()` | 可坐标点击 | 重传前删除失败素材 | `div.media-status-content div.tag-inner` | — | 保持原生（错误重传路径） |
| 1163 | `get_by_role("button", name="删除").click()` | 可坐标点击 | 确认删除素材 | 确认按钮 | — | 保持原生（错误重传路径） |
| 1173 | `cover_entry.click()` | 可坐标点击 | 打开封面弹窗 | `selectors` 依次尝试（`open_thumbnail_dialog`） | — | 改 Humanizer |
| 1197 | `crop_confirm_button.click()` | 可坐标点击 | 确认裁剪 | 弹窗底栏主按钮「确定」 | — | 改 Humanizer |
| 1213 | `confirm_button.click()` | 可坐标点击 | 保存封面弹窗 | 弹窗底栏主按钮「确认」 | — | 改 Humanizer |

---

## 11. 微博 `uploader/weibo_uploader/main.py`

- **两个 page**：`main.py:464` 新建首页 page；`_open_video_publish_page` 用 `page.expect_popup()` 点「视频」拿到 `publish_page`（`main.py:503-515`）。后续 2–10 步全部在 `publish_page` 上。
- 交互点共 26：`fill` 3、`click` 19、`set_input_files` 1，另有 3 行注释/文档字符串命中（`505`、`518`、`591`，见 §21.1）。
- **Humanizer 必须建两个**：`Humanizer(page)` 只用于 `508`（首页入口），`Humanizer(publish_page)` 用于其余全部。
- 该平台的发布按钮与合集入口是“中心被空 div/整行空白覆盖”的典型，已用 JS 绕过（`861`、`912`），见 §16。

| 行号 | 调用 | 分类 | 字段语义 | 目标元素 | 打开时是否已有默认值 | 建议处置 |
| --- | --- | --- | --- | --- | --- | --- |
| 583 | `title_field.fill(title)` | 文本输入 | 标题（≤30） | `get_by_placeholder("填写标题（0～30个字）")` | 否 `[inferred]`（placeholder 空态） | 改 Humanizer（清空：全选） |
| 761 | `desc_field.fill(content)` | 文本输入 | 描述（正文 + `#tag#`） | `get_by_placeholder("有什么新鲜事想分享给大家？")` | 否 `[inferred]` | 改 Humanizer（清空：全选） |
| 872 | `new_inp.fill(target[:12])` | 文本输入 | 新建合集名（≤12） | 合集面板内 `input[type="text"]:not([disabled])` | 否 `[inferred]`（新建行才出现，已有行都 disabled） | 改 Humanizer |
| 508 | `video_btn.click()` | 导航或跳转点击 | 首页「视频」→ 打开 popup 发布页 | `span` 过滤「视频」 | — | 改 Humanizer（`Humanizer(page)`）+ `after_navigate` |
| 524 | `upload_btn.click()` | 文件选择触发 | 上传视频（`expect_file_chooser` 内） | `get_by_role("button", name="上传视频")` | — | 保持原生（与 `file_chooser.set_files` 配对） |
| 582 | `title_field.click()` | 可坐标点击 | 聚焦标题 | 标题 `input` | — | 改 Humanizer（与 583 合并） |
| 603 | `upload_link.click()` | 可坐标点击 | 打开「编辑封面」层 | `get_by_role("link", name="上传封面")` / `a:has-text("上传封面")` | — | 改 Humanizer |
| 657 | `finish_btn.click(timeout=3000)` | 可坐标点击 | 封面「完成」（裁切轮询中每 4s 一次） | 封面层内完成按钮 | — | 待定（周期性兜底点击；人类化会把 4s 周期拉长，需改成“点一次 + 等状态”） |
| 682 | `label.click()` | 可坐标点击 | 类型「二创」 | `label.woo-radio-main:has(span:text-is("二创"))` | — | 改 Humanizer |
| 711 | `trigger.click()` | 可坐标点击 | 打开内容声明下拉 | `div[class*="_gap1_nsgmr"] .woo-pop-ctrl` | — | 改 Humanizer |
| 726 | `ai_opt.click()` | 可坐标点击 | 选「含AI生成内容」 | `button:has(span:text-is("含AI生成内容"))` | — | 改 Humanizer |
| 738 | `confirm.click()` | 可坐标点击 | 关闭声明弹层 | 弹层底栏「确定」 | — | 改 Humanizer |
| 760 | `desc_field.click()` | 可坐标点击 | 聚焦描述 | 描述区 | — | 改 Humanizer（与 761 合并） |
| 792 | `sw.click(timeout=6000)` | 可坐标点击 | 打开「合集」开关 | `label.woo-switch-main span[role="switch"]` / label 本体 | — | 改 Humanizer（switch 视觉元素；`check` 对 `span[role=switch]` 走 `interactive` 分支即可） |
| 795 | `sw.click(timeout=4000, force=True)` | 隐藏或不可命中元素 | 同上（普通 click 失败后） | 同上 | — | 待定（force 白名单） |
| 829 | `row.locator('label.woo-checkbox-main').first.click()` | 可坐标点击 | 勾选已有合集 | 合集面板每行 checkbox | — | 改 Humanizer |
| 855 | `add_target.click(timeout=4000)` | 可坐标点击 | 「＋新建合集」文字 | `add_btn.get_by_text("新建合集", exact=True)` | — | 改 Humanizer |
| 858 | `add_target.click(timeout=3000, force=True)` | 隐藏或不可命中元素 | 同上（失败重试） | 同上 | — | 待定（force 白名单；注释说明整行 598px、中心落空） |
| 861 | `add_target.evaluate("el => el.click()")` | 隐藏或不可命中元素 | 同上（force 再失败） | 同上 | — | 待定（禁令冲突；建议改为点内部左侧文字 span，而不是删掉兜底） |
| 871 | `new_inp.click()` | 可坐标点击 | 聚焦新建合集输入 | 新建行 `input[type=text]:not([disabled])` | — | 改 Humanizer（与 872 合并） |
| 912 | `publish_btn.evaluate("el => el.click()")` | 隐藏或不可命中元素 | 「发布」（提交，按钮中心被空 div 覆盖） | `div[class*="_check_2z30i"] button:has(span:text-is("发布"))` | — | 待定（禁令冲突；docstring 已写明原因，规格需给“被覆盖的提交按钮”一条合法路径） |
| 941 | `cb.evaluate("el => el.click()")` | 隐藏或不可命中元素 | 二次确认对话框按钮（确定/继续/仍然发布） | 对话框内 `button:has(span:text-is(name))` | — | 待定（禁令冲突；每轮只点一次） |

---

## 12. TikTok `uploader/tk_uploader/main_chrome.py`

- 单 page：`main_chrome.py:888`（登录）、`982`（upload_local）、`1074`、`1180`。无 popup。
- **可能不是主 frame**：`choose_base_locator`（`2685-2690`）在页面存在 `iframe[data-tt="Upload_index_iframe"]` 时把 `self.locator_base` 设为 `page.frame_locator(...)`；之后大量 locator 都从 `locator_base` 派生。`Humanizer.click(locator)` 对 frame 内 locator 可用（见 §0 第 2 条），但 `Humanizer(page)` 的 `page.mouse` 仍是主 frame 坐标，勿把 `locator_base` 当成 page 传入。`[code]`
- grep 命中 53 次 / 48 个唯一行；去掉 3 行非代码（`1030` docstring、`2898` 注释、`2913` f-string）后为 **45 个调用点**：`fill` 1、`keyboard.insert_text` 2、`click` 41、`set_input_files` 2，另有 1 处跨行的 `evaluate("el => el.click()")`（`2389-2391`，下表中按 `2390` 计）。
- 配文**不是** `keyboard.type`：`fill_caption` 用 `keyboard.insert_text(text)` 一次性灌入（`2441`），所以 grep 的 `keyboard.type` 计数里没有 TikTok 配文。这是本清单最重要的一条计数外事实。
- 该文件有大量“选项控件”抽象（`TiktokOptionControl` / `_set_toggle_option` / `_set_switch_option` / `_set_privacy_option`），修改点集中在少数 helper 上，而不是 41 个独立调用点。

| 行号 | 调用 | 分类 | 字段语义 | 目标元素 | 打开时是否已有默认值 | 建议处置 |
| --- | --- | --- | --- | --- | --- | --- |
| 3242 | `locator.first.fill(self.title, timeout=…)` | 文本输入 | 图片帖 Title（`_PHOTO_TITLE_CANDIDATES` 逐个试） | 图片帖标题输入框 | 否 `[inferred]`（候选选择器都是标题位；无清空） | 改 Humanizer（清空：全选） |
| 2441 | `page.keyboard.insert_text(text)` | 富文本输入 | 视频/图文配文 | `locator_base.locator('div.public-DraftEditor-content')` | **是**：`[code]` 注释 `Control+A alone leaves the old caption on macOS` + 前面显式 End/全选/Delete | 改 Humanizer（`type_text` 取代 `insert_text`；清空保留现有 `ControlOrMeta+A`+`Delete`） |
| 2338 | `page.keyboard.insert_text("#" + tag)` | 富文本输入 | 话题（随后等联想并选精确候选） | 同上 | 否 `[inferred]` | 待定（必须**整段**插入：逐字会让联想列表随光标反复重排，且后续要按精确候选文本匹配） |
| 460 | `target.click(timeout=TIKTOK_OVERLAY_CLICK_TIMEOUT_MS)` | 可坐标点击 | `TiktokOptionControl.click`：单选/开关等 | `_target()`（label 或 input 候选） | — | 改 Humanizer（公共底座；改一处覆盖多个选项） |
| 462 | `target.click(force=True)` | 隐藏或不可命中元素 | 同上（styled label 的 icon 挡住原生 input） | 同上 | — | 待定（force 白名单；注释已写明 icon 拦截） |
| 540 | `target.click()` | 可坐标点击 | 另一组控件抽象的 click | `_target()` | — | 改 Humanizer |
| 673 | `control.click()` | 可坐标点击 | `_set_toggle_option` 开关 | 选项控件 | — | 改 Humanizer |
| 721 | `control.click()` | 可坐标点击 | `_set_switch_option` 开关 | 选项控件 | — | 改 Humanizer |
| 759 | `control.click()` | 可坐标点击 | `_set_privacy_option` 打开可见性菜单 | 隐私下拉触发器 | — | 改 Humanizer |
| 789 | `matched.click()` | 可坐标点击 | 选目标可见性 | 菜单内选项 | — | 改 Humanizer |
| 1219 | `[data-e2e="nav-more-menu"].click()` | 可坐标点击 | 语言切换：More 菜单 | 导航菜单 | — | 保持原生（界面语言初始化，非用户内容） |
| 1220 | `[data-e2e="language-select"].click()` | 可坐标点击 | 语言下拉 | 下拉触发器 | — | 保持原生（同上） |
| 1223 | `#creator-tools-selection-menu-header >> text=English (US)).click()` | 可坐标点击 | 选 English (US) | 菜单项 | — | 保持原生（同上） |
| 1440 | `control.click()` | 可坐标点击 | AIGC 开关 | 选项控件 | — | 改 Humanizer |
| 1479 | `button.click()` | 可坐标点击 | AIGC 打开确认弹窗按钮 | 弹窗按钮 | — | 改 Humanizer |
| 1867 | `show_more.first.click()` | 可坐标点击 | 图片帖无高级设置容器时展开 Show more | `locator_base.get_by_text("Show more")` | — | 改 Humanizer |
| 1883 | `more_btn.first.click()` | 可坐标点击 | 展开高级设置 | `.more-btn` | — | 改 Humanizer |
| 1892 | `show_more.first.click()` | 可坐标点击 | 展开高级设置（文本兜底） | 同上 | — | 改 Humanizer |
| 2003 | `target.locator(selector).first.click(force=True)` | 隐藏或不可命中元素 | 切「定时」radio（3 候选 × 2 scope） | `label:has(input[name=postSchedule…])` 等 | — | 待定（force 白名单；React checked 会陈旧，必须保留“重复点幂等”写法） |
| 2032 | `allow.first.click()` | 可坐标点击 | 首次定时的 Allow 权限弹窗 | `role=dialog` 内 `button[name=/^Allow$/]` | — | 改 Humanizer |
| 2039 | `date_cb.first.click()` | 可坐标点击 | 打开日期选择器 | `get_by_role("combobox", name="Select date")` | — | 改 Humanizer |
| 2061 | `...name="Next month").first.click()` | 可坐标点击 | 日历下月 | 同 selector | — | 改 Humanizer |
| 2065 | `...name="Previous month").first.click()` | 可坐标点击 | 日历上月 | 同 selector | — | 改 Humanizer |
| 2074 | `day_button.first.click()` | 可坐标点击 | 选日（按完整 aria 名称） | `role=button[name="<Month> <day>, <year>"]` | — | 改 Humanizer |
| 2084 | `days.nth(index).click()` | 可坐标点击 | 选日（按文本兜底） | `.DatePicker__day[data-outside=false]:not([disabled])` | — | 改 Humanizer |
| 2100 | `get_by_role("combobox", name="Select time").first.click()` | 可坐标点击 | 打开时间下拉 | 同 selector | — | 改 Humanizer |
| 2104 | `hour_option.first.click()` | 可坐标点击 | 选小时 | `role=option[name="Hours HH"]` | — | 改 Humanizer |
| 2113 | `minute_option.first.click()` | 可坐标点击 | 选分钟（5 分钟粒度） | `role=option[name="Minutes MM"]` | — | 改 Humanizer |
| 2121 | `minutes.nth(index).click()` | 可坐标点击 | 选分钟（文本兜底） | `[aria-label="Minutes"] [role=option]` | — | 改 Humanizer |
| 2254 | `button.first.click(timeout=…)` | 可坐标点击 | 关「automatic content checks」弹窗 | 弹窗内 Cancel/Got it/Close | — | 改 Humanizer / 保持原生（`dismiss_blocking_overlays` 在每次编辑前调用，人类化会让每个动作都多一次停顿；建议保持原生） |
| 2277 | `target.first.click(timeout=…)` | 可坐标点击 | 点 onboarding 遮罩关闭 Joyride | `.react-joyride__overlay` / `#react-joyride-portal` | — | 待定（点遮罩本身；不是正常用户控件） |
| 2294 | `editor_locator.click(timeout=…)` | 可坐标点击 | 聚焦配文编辑器（8 次重试） | `div.public-DraftEditor-content` | — | 改 Humanizer（与 2441 合并；重试结构保留） |
| 2382 | `option.click(timeout=…)` | 可坐标点击 | 选话题联想候选 | `[role="option"]` 精确首行文本 | — | 改 Humanizer（候选经常重排，stillOn 复核很重要） |
| 2387 | `option.click(force=True)` | 隐藏或不可命中元素 | 同上（普通 click 失败） | 同上 | — | 待定（force 白名单） |
| 2390 | `option.evaluate("el => el.click()")`（跨 2389-2391） | 隐藏或不可命中元素 | 同上（click 与 force 都失败） | 同上 | — | 待定（禁令：不得 `el.click()`；注释说明 Enter 才是首选，JS 只应作最后一级） |
| 2586 | `publish_button.click()` | 导航或跳转点击 | 发布（提交） | `_PUBLISH_BUTTON_CANDIDATES` 命中项 | — | 改 Humanizer + `before_submit` |
| 2669 | `button.click()` | 可坐标点击 | 发布后确认弹窗（如“Post now”） | 确认候选按钮 | — | 改 Humanizer（可选兜底，失败不得改变退出码） |
| 2792 | `select_file_button.click()` | 文件选择触发 | 重试视频上传（`expect_file_chooser` 内） | 视频选择入口 | — | 保持原生（与 `file_chooser.set_files` 配对） |
| 2821 | `upload_button.click()` | 文件选择触发 | 首次视频上传（`expect_file_chooser` 内） | 视频选择入口 | — | 保持原生（与 `file_chooser.set_files` 配对） |
| 2856 | `edit_cover.click()` | 可坐标点击 | 打开封面编辑器 | `_COVER_EDIT_CANDIDATES` | — | 改 Humanizer |
| 2866 | `upload_tab.click()` | 可坐标点击 | 切「Upload cover」 | `_COVER_UPLOAD_TAB_CANDIDATES` | — | 改 Humanizer |
| 2904 | `file_input.click(force=True)` | 隐藏或不可命中元素 | `set_input_files` 失败后的 file-chooser 兜底（hidden input） | 封面 file input | — | 待定（force 白名单；注释说明 input hidden） |
| 2973 | `save_button.click()` | 可坐标点击 | 保存封面 | `_COVER_SAVE_CANDIDATES` | — | 改 Humanizer |
| 3186 | `tab.click()` | 导航或跳转点击 | 切「Photos」tab | `role=tab[name=…]` | — | 改 Humanizer + `after_navigate` |
| 3199 | `tab.click()` | 导航或跳转点击 | 同上（文本兜底） | `get_by_text(label, exact=True)` | — | 改 Humanizer |

---

## 13. 雪球 `uploader/xueqiu_uploader/`

- 单 page：`article.py:271`（Multilogin）；登录 `session.py:112`；另 `article.py:335` 开 `check_page` 做发布后只读核对，`verification.py:59` 在**独立 context 的新 page** 上查询作品（只读）。
- 交互点共 13：`fill` 1、`click` 11、`set_input_files` 1。
- 雪球有**显式的“已有草稿就拒绝覆盖”守卫**（`article.py:153`）：`title.input_value()` / `body.inner_text()` 非空即抛错。这是全仓唯一把“打开时是否已有默认值”写成运行时不变量的一处，值得在 spec 里作为清空策略的样板。`[code]`

| 行号 | 调用 | 分类 | 字段语义 | 目标元素 | 打开时是否已有默认值 | 建议处置 |
| --- | --- | --- | --- | --- | --- | --- |
| 155 | `title.fill(self.title)` | 文本输入 | 文章标题 | `get_by_placeholder("请输入标题", exact=True)` → `input` | **否**（有守卫：非空直接拒绝）`[code]` | 改 Humanizer（清空：`none`，因为已保证为空） |
| 101 | `body.click()` | 可坐标点击 | 聚焦正文（准备粘贴 HTML） | `#editor > [contenteditable="true"]` | — | 改 Humanizer（仅聚焦；粘贴保持原生） |
| 104 | `get_by_placeholder("请输入标题").click()` | 非交互（滚动、读取、等待） | 失焦正文，触发保存 | 标题 input | — | 保持原生（失焦动作，配合 142 的正文核对） |
| 127 | `#snb_toolbar [data-tip="上传图片"]).click()` | 可坐标点击 | 工具栏「上传图片」 | 编辑器工具栏按钮 | — | 改 Humanizer |
| 141 | `get_by_placeholder("请输入标题").click()` | 非交互（滚动、读取、等待） | 失焦正文，等自动保存 | 标题 input | — | 保持原生（失焦动作） |
| 173 | `crop.get_by_role("button", name="确认裁剪").click()` | 可坐标点击 | 封面裁剪确认 | 裁剪弹窗按钮 | — | 改 Humanizer |
| 186 | `selected.click()` | 可坐标点击 | 打开「分享范围」/「创作声明」下拉 | `div[class*="index_selectWrap_"]`（按 label 限域） | **是**：`[code]` 页面默认一份可见范围/声明，随后读回校验 | 改 Humanizer |
| 190 | `option.click()` | 可坐标点击 | 选下拉项 | `div[class*="index_optionContainer_"]:visible` 精确文本 | — | 改 Humanizer |
| 194 | `get_by_role("button", name="预览").click()` | 可坐标点击 | 打开预览遮罩 | 「预览」按钮 | — | 改 Humanizer |
| 290 | `...index_preview_ _close_]).click()` | 可坐标点击 | 关闭预览遮罩 | 预览遮罩直接子级关闭控件 | — | 改 Humanizer（注释说明不能删遮罩/强点，坐标点击正合适） |
| 316 | `publish.click()` | 导航或跳转点击 | 「发布」（提交） | `get_by_role("button", name="发布", exact=True)` | — | 改 Humanizer + `before_submit` |
| 59 | `get_by_role("link", name="内容管理").click()` | 导航或跳转点击 | 发布后查询：进内容管理列表 | 首页侧栏链接 | — | 保持原生（独立只读核对 path，不在发布流程） |

---

## 14. YouTube `uploader/youtube_uploader/main.py`

- 单 page：`main.py:103`（登录）/ `126`（login）/ `186`（prepared）/ `363`（Multilogin）。
- 交互点共 8：`fill` 1、`click` 5、`set_input_files` 2。
- 两处已有**逐字输入**：`box.type(text, delay=6)`（`251`，`fill` 的兜底）与 `title_box.type(playlist, delay=6)`（`434`）、`tag_input.type(tags, delay=4)`（`454`）。它们不是 `keyboard.type`，因此不在 12 的计数内，但已经是“逐字符”行为。
- 标题/简介的 `fill` 是**刻意**的：`_fill_editable` docstring 明确说逐字输入会让 `#` 话题自动补全浮层持续跟随，卡住后续按钮。这条注释与本次移植直接冲突，是 spec 必须正面回答的一条（见 §22 风险 1）。

| 行号 | 调用 | 分类 | 字段语义 | 目标元素 | 打开时是否已有默认值 | 建议处置 |
| --- | --- | --- | --- | --- | --- | --- |
| 249 | `box.fill(text)` | 富文本输入 | 标题 / 简介（`_fill_editable` 的 selector 决定） | `contenteditable`（`#title-textarea` / `#description-textarea` 等） | **是**：`[code]` 先 `Control+A`+`Delete`，且 docstring 说“先清空再输入” | 待定（docstring 明确要求一次性 `fill`；若改 `type_text` 必须先解决 `#` 联想浮层，否则会卡死流程） |
| 245 | `box.click()` | 可坐标点击 | 聚焦富文本 | 同上 | — | 改 Humanizer（与 249 配套；单独人类化 click 不改变 `fill` 语义） |
| 260 | `el.click()` | 可坐标点击 | `_click_if_present` 的通用点击（20+ 处调用） | 任意 selector | — | 待定（helper 被大量调用；改成 `Humanizer.click` 需把 page 传进来，且会影响“可缺席”语义） |
| 426 | `existing.click()` | 可坐标点击 | 勾选已有播放列表 | `tp-yt-paper-checkbox:has-text(...)` | 否 `[inferred]` | 改 Humanizer |
| 433 | `title_box.click()` | 可坐标点击 | 聚焦新建播放列表名 | `#create-playlist-form #textbox` | 否 `[inferred]`（新建表单） | 改 Humanizer（与 434 `type(delay=6)` 合并为 `type_text`） |
| 453 | `tag_input.click()` | 可坐标点击 | 聚焦标签输入 | `#tags-container input` | 未知 `[needs-live]`（`fill_editable` 流程可能已写入部分标签） | 改 Humanizer（与 454 `type(delay=4)` 合并） |

---

## 15. 知乎 `uploader/zhihu_uploader/`

- 单 page：`video.py:255` / `article.py:264`（Multilogin）；登录 `session.py:111`。发布后 `video.py:311` 用 `expect_popup()` 打开「查看详情」新 tab（只读）。
- grep 命中 40 行：`fill` 3、`click` 32、`set_input_files` 2、同名本地方法 `select_option` 1 定义 + 2 调用（不是 Playwright API，见 §18.1）；**页面交互调用点 37 个**。
- 视频表单的领域/标记是**点选**（`149-156`），没有原生 `<select>`；小时/分钟也是点选（`schedule.py`）。
- 文章正文用剪贴板粘贴 HTML（`article.py:116`），不是逐字输入。

| 行号 | 调用 | 分类 | 字段语义 | 目标元素 | 打开时是否已有默认值 | 建议处置 |
| --- | --- | --- | --- | --- | --- | --- |
| 173 | `title.fill(self.title)` | 文本输入 | 视频标题 | `form.locator("textarea")`（标题与介绍区内唯一） | 否 `[inferred]`（`to_have_value` 读回） | 改 Humanizer（清空：全选） |
| 177 | `description.fill(self.description)` | 富文本输入 | 视频介绍 | `[contenteditable="true"][role="textbox"]` | 否 `[inferred]` | 改 Humanizer（`type_text`；清空：全选） |
| 103 | `title.fill(self.title)` | 文本输入 | 文章标题 | `textarea[placeholder="请输入标题（最多 100 个字）"]` | **否**（有守卫：非空即拒绝覆盖）`[code]` | 改 Humanizer（清空：`none`） |
| 108 | `control.click()` | 可坐标点击 | 打开「所属领域」下拉 | `field.get_by_role("combobox")` | — | 改 Humanizer |
| 115 | `control.click()` | 可坐标点击 | 关闭「所属领域」下拉（读完候选后） | 同上 | — | 改 Humanizer |
| 117 | `mark_field.get_by_role("button", name="选择视频标记").click()` | 可坐标点击 | 打开「视频标记」弹窗 | 视频标记行按钮 | — | 改 Humanizer |
| 123 | `modal.get_by_role("button", name="取消").click()` | 可坐标点击 | 关闭视频标记弹窗（只看候选） | 弹窗「取消」 | — | 改 Humanizer |
| 149 | `control.click()` | 可坐标点击 | 打开「所属领域」下拉（填写阶段） | 同上 | — | 改 Humanizer |
| 150 | `...get_by_role("option", name=self.category).click()` | 可坐标点击 | 选领域 | `selectList:visible` 内 option | — | 改 Humanizer |
| 153 | `mark_field...「选择视频标记」.click()` | 可坐标点击 | 打开视频标记弹窗 | 视频标记行按钮 | — | 改 Humanizer |
| 155 | `modal.get_by_role("button", name=self.video_mark).click()` | 可坐标点击 | 选标记 | 弹窗内选项按钮 | — | 改 Humanizer |
| 156 | `modal.get_by_role("button", name="确认").click()` | 可坐标点击 | 确认标记 | 弹窗「确认」 | — | 改 Humanizer |
| 191 | `originality.click()` | 可坐标点击 | 原创/转载 checkbox（按状态切换） | 「原创视频」行 `role=checkbox` | **是**：`[code]` 先 `is_checked()` 比较再点 | 改 Humanizer（幂等：先读状态） |
| 302 | `publish.click()` | 导航或跳转点击 | 视频「发布」（提交） | `get_by_role("button", name="发布", exact=True)` | — | 改 Humanizer + `before_submit` |
| 312 | `get_by_text("查看详情").click()` | 导航或跳转点击 | 发布后打开详情 tab（`expect_popup`） | 「查看详情」 | — | 保持原生（结果核对路径） |
| 119 | `body.click()` | 可坐标点击 | 聚焦正文（准备粘贴 HTML） | `div[contenteditable="true"][role="textbox"]` | — | 改 Humanizer（仅聚焦） |
| 121 | `title.click()` | 非交互（滚动、读取、等待） | 失焦正文 | 文章标题 textarea | — | 保持原生（失焦动作） |
| 168 | `title.click()` | 非交互（滚动、读取、等待） | 失焦正文，等图片插入稳定 | 同上 | — | 保持原生（失焦动作） |
| 291 | `publish.click()` | 导航或跳转点击 | 文章「发布」（提交） | `get_by_role("button", name="发布", exact=True)` | — | 改 Humanizer + `before_submit` |
| 36 | `get_by_text("定时发布", exact=True).click()` | 可坐标点击 | 切「定时发布」 | 同文案 | — | 改 Humanizer |
| 45 | `date_button.click()` | 可坐标点击 | 打开日期选择器 | `date_button` | **是**：`[code]` 日期控件默认显示当天 | 改 Humanizer |
| 52 | `.Calendar-topToolButton--nextMonth` | 可坐标点击 | 日历下月 | 日历头按钮 | — | 改 Humanizer |
| 58 | `day.click()` | 可坐标点击 | 选日 | 日历日格 | — | 改 Humanizer |
| 64 | `time_selects.nth(0).click()` | 可坐标点击 | 打开小时下拉 | 时间选择器第 0 个 | — | 改 Humanizer |
| 69 | `hour.click()` | 可坐标点击 | 选小时 | 小时选项 | — | 改 Humanizer |
| 70 | `time_selects.nth(1).click()` | 可坐标点击 | 打开分钟下拉 | 时间选择器第 1 个 | — | 改 Humanizer |
| 75 | `minute.click()` | 可坐标点击 | 选分钟 | 分钟选项 | — | 改 Humanizer |
| 80 | `confirm.click()` | 可坐标点击 | 确认定时 | 确认按钮 | — | 改 Humanizer |
| 102 | `date_button.click()` | 可坐标点击 | 打开日期选择器（视频） | 同 45 | **是** `[code]` | 改 Humanizer |
| 108 | `.Calendar-topToolButton--nextMonth` | 可坐标点击 | 日历下月（视频） | 同 52 | — | 改 Humanizer |
| 114 | `day.click()` | 可坐标点击 | 选日（视频） | 同 58 | — | 改 Humanizer |
| 118 | `time_selects.nth(0).click()` | 可坐标点击 | 打开小时下拉（视频） | 同 64 | — | 改 Humanizer |
| 123 | `hour.click()` | 可坐标点击 | 选小时（视频） | 同 69 | — | 改 Humanizer |
| 124 | `time_selects.nth(1).click()` | 可坐标点击 | 打开分钟下拉（视频） | 同 70 | — | 改 Humanizer |
| 129 | `minute.click()` | 可坐标点击 | 选分钟（视频） | 同 75 | — | 改 Humanizer |

---

# Part B — 横向专题

## 16. 9 处 `evaluate("el => el.click()")`

全仓 `el => el.click()` / `evaluate(...click` 命中 9 行，全部是真实调用（另有 3 行注释/文档字符串提到 `el.click()`，不计入）。逐条如下。

| 位置 | 点什么 | 为什么非要用 JS | 流程阶段 | 移植含义 |
| --- | --- | --- | --- | --- |
| `douyin_uploader/main.py:686` | BGM 卡片上的「使用」按钮 `.apply-btn-LUPP0D` | 注释明写「按钮 visibility:hidden，普通 click 无效」`[code]` | 选配乐，应用 BGM | 禁令与现状直接冲突。规格要么找到可点的可见父级，要么把这一条列为原生例外 |
| `douyin_uploader/main.py:849` | 短信「验证」按钮 `div.uc-ui-verify_sms-verify_button` | 无注释；是 `846 force=True` 失败后的第三级兜底 | 登录二次验证 | 三级兜底链（普通 → force → JS）应整体重设计，不应逐级人类化 |
| `insgraph/controls/_rows.py:110` | `activate()` 里的折叠行 `row` | 前两级（focus+Enter、普通 click）都失败；行可能是带遮挡的 `div`，JS 跳过 actionability | 展开高级设置行 | 公共 helper；删掉这级会改变“展开失败”的语义，需先确认有没有行只能靠 JS 展开 |
| `insgraph/controls/_rows.py:130` | `click_control()` 里的开关控件 | 前两级（click、focus+Space）都失败 | 开关/复选框 | 同上；这是 `Humanizer` 落地后最容易“被 helper 绕过”的一处 |
| `tencent_uploader/main.py:1076` | 「发表」按钮 | 普通 click 4s 超时后的兜底 | 提交（发表/存草稿） | 提交按钮的兜底链，与抖音 1241 / 微博 912 同类 |
| `tk_uploader/main_chrome.py:2390` | 话题联想候选 `option` | 普通 click 与 `force=True` 都失败；注释说明优先用 Enter 接受已聚焦候选 `[code]` | 话题输入 | 正确解法是保留 Enter 首选，JS 仅作最后一级；坐标点击可行但候选会重排 |
| `weibo_uploader/main.py:861` | 「＋新建合集」文字 | 注释明写整行 598px、可点文字在左侧，点几何中心会落到右侧空白 `[code]` | 合集新建 | 这是“目标元素本身可点、但整体行不可点”的典型；Humanizer 点文字 span 即可，不需要 JS |
| `weibo_uploader/main.py:912` | 「发布」按钮 | docstring 明写按钮中心被空 div 覆盖，用 JS 触发按钮自身 click 绕过遮罩 `[code]` | 提交（发布） | 与小红书“发布按钮已知点位”同类；规格必须给出“被覆盖的提交按钮”合法路径（点位/父级/先清浮层） |
| `weibo_uploader/main.py:941` | 二次确认对话框按钮（确定/继续/仍然发布） | 无注释；对话框可能盖住按钮或按钮自身被装饰层覆盖 | 提交后二次确认 | 坐标点击可试；失败时现网直接 JS，规格需明确“确认按钮”是否白名单 |

---

## 17. 19 处 `force=True`（18 个真实参数 + 1 行文档字符串）

`grep force=True` 命中 19 行，其中 `tk_uploader/main_chrome.py:1030` 是 `tiktok_setup` docstring 里的说明文字，不是参数。真实 18 处：

| 位置 | 目标元素 | 现有注释是否解释 | 流程阶段 | 白名单初判 |
| --- | --- | --- | --- | --- |
| `alipay:521` | 合集下拉 `[role="option"]` | 无 | 归集 | 可去掉（524 已是不带 force 的重试，521 应删） |
| `baijiahao:641` | 创作声明 `input[placeholder="请选择创作声明"]` | 无（只 `scroll_into_view`） | AI 声明 | 可去掉，改为点可点容器；需真机确认 input 是否被组件覆盖 |
| `baijiahao:753` | 发布按钮 `[data-testid="publish-btn"]` | 无 | 提交 | 提交出口，倾向保留但必须写明理由 |
| `douyin:624` | 声明文案（`option.count()==0` 分支） | 无 | 自主声明 | 只在 DOM 变异时走，可去掉；正常分支 620 已覆盖 |
| `douyin:846` | 短信验证按钮 | 日志写“(force)” | 二次验证 | 验证码窗口短，建议保留 |
| `douyin:854` | 「验证」文案兜底 | 无 | 二次验证 | 同 846，二者应合并 |
| `douyin:935` | 封面区 `hover(force=True)` | 有：hover 若干次等「编辑封面」浮现 | 封面 | 应改为 `Humanizer.hover`，force 无必要（hover 本身不要求可点） |
| `douyin:1241` | 发布按钮 | 无 | 提交 | 提交出口，倾向保留 |
| `ks:110` | 描述编辑器（4 级回退定位） | 有：回退策略警告 | 描述聚焦 | 策略 #0 可见，可只对回退分支保留 |
| `ks:582` | Joyride 关闭按钮 | 有：遮罩层说明 | 引导层清理 | 引导层非正常路径，可保留 |
| `tencent:794` | 「发表视频」按钮（扫描所有 button 得到） | 有：Patchright 按名匹配不稳 | 打开发布页 | 可去掉（候选已 `is_visible()`），force 是多余保险 |
| `tencent:918` | 合集选项（headless 视口外） | 有：headless 小视口 + 滚动容器 | 合集 | 可去掉，坐标点击前 `ensure_in_viewport` 已解决 |
| `tk:462` | `TiktokOptionControl` 的 label/input | 有：styled label 的 icon 拦住原生 input | 各类开关/单选 | 保留或改为点 label 本体；影响多个选项 |
| `tk:2003` | 定时 radio label | 有：React checked 陈旧、重复点幂等 | 定时 | 保留（改坐标点击需解决 label 覆盖 input） |
| `tk:2387` | 话题联想候选 | 无 | 话题 | 可去掉（2382 普通 click 已是首选） |
| `tk:2904` | 封面 hidden file input | 有：input hidden、`set_input_files` 失败才走 | 封面 | 保留（文件选择器兜底，不在人类化范围） |
| `weibo:795` | 合集开关 `span[role=switch]`/label | 无 | 合集 | 可去掉；坐标点 switch 装饰层即可 |
| `weibo:858` | 「新建合集」文字 | 有：整行 598px、中心落空 | 合集新建 | 可去掉，改成点文字 span（与 861 的结论一致） |

**统计**：18 处中 9 处有明确注释解释（`douyin:935`、`ks:110/582`、`tencent:794/918`、`tk:462/2003/2904`、`weibo:858`），其余 9 处没有。提交按钮占 3 处（`baijiahao:753`、`douyin:1241`、`tk` 无；另有 `weibo` 用 JS 而非 force）。

---

## 18. `select_option`（3）与 `set_input_files`（31）：保持原生

### 18.1 `select_option` — 实际 **0 处 Playwright API**

3 行命中全部在 `uploader/zhihu_uploader/video.py`：

- `129: async def select_option(self, label, value, choices) -> str` —— 本地方法**定义**，做终端交互式选择（`input()`），不碰页面；
- `278`、`279` —— 对上述本地方法的两次调用，读的是本次页面渲染出的候选项。

结论：**全仓没有任何 Playwright `locator.select_option()` 调用**，因此“下拉选择保持原生”这一条没有需要例外的地方。规格里要写清这个同名陷阱，否则实施者按 grep 结果去找 `<select>` 会白跑。`[code]`

### 18.2 `set_input_files` — 31 行命中，28 个真实调用

3 行不是调用：`weibo_uploader/main.py:591`（docstring）、`tk_uploader/main_chrome.py:2898`（注释）、`tk_uploader/main_chrome.py:2913`（f-string `detail=f"set_input_files failed…"`）。

28 个真实调用全部保持原生，逐平台分布：

| 平台 | 行号 | 用途 |
| --- | --- | --- |
| alipay | 443 / 487 | 视频 / 封面 |
| baijiahao | 466 / 602 | 视频 / 封面 |
| dayu | `main.py:181` / `main.py:251` / `article.py:180` | 封面 / 视频 / 正文插图 |
| douyin | 881 / 982 / 991 / 1132 / 1332 | 重传视频 / 竖封面 / 横封面 / 视频 / 图文图片 |
| ks | 693 / 714 / 994 | 重传视频 / 封面 / 图文图片 |
| facebook | 337 | 影音（多文件 list） |
| insgraph | 568 / 601 | 媒体（多文件）/ 封面 |
| tencent | 814 / 1206 | 视频 / 封面 |
| tk | 2899 / 3225 | 封面 / 图文图片（多文件） |
| weibo | 614 | 封面 |
| xueqiu | 164 | 封面 |
| youtube | 385 / 410 | 视频 / 缩略图 |
| zhihu | `video.py:266` / `article.py:159` | 视频 / 正文图片 |

例外与注意点（都不是 `set_input_files` 本身的例外）：

1. **隐藏 input**：`tk:2899` 依赖 “input hidden 但 `set_input_files` 仍可用”；`weibo:614` 必须用 `.first`，`.last` 会命中隐藏面板里 0 尺寸的裁切器。`[code]`
2. **失败后回退到 file chooser**：`tk:2904`（`file_input.click(force=True)` + `expect_file_chooser`）。这是 click 的例外，不是 `set_input_files` 的。
3. **点击按钮打开选择器**：alipay 481、baijiahao 593、hupu 520/567、ks 776/953、facebook_page 301、tk 2792/2821、weibo 524 都是 `expect_file_chooser` 内的可见点击。它们归 `文件选择触发`，同样保持原生（否则“点按钮 + 系统文件对话框”会被人类化停顿拉长）。

---

## 19. 唯一的 `hover()`：`douyin_uploader/main.py:935`

`cover_area.hover(force=True)`，在 5 轮重试中每轮最多 hover 3 次、每次等 600ms，目的是让「编辑封面 / 选择封面 / 设置封面」入口从 0×0 渲染成可见；随后用 `_native_click` 点浮现出来的文字，而不是点封面区本身。`[code]`

移植建议：这是 `Humanizer.hover` 的标准用例（XHS 的视频封面入口同型），应改成 `await humanizer.hover(cover_area)`，并去掉 `force=True` —— hover 不做可点性检查，force 只是让 Playwright 跳过可见性等待。

---

## 20. `page` 生命周期与 `Humanizer(page)` 构造点

| 平台 | page 数 | 关键证据 | `Humanizer(page)` 构造点 |
| --- | --- | --- | --- |
| 支付宝 | 1 | `main.py:824` `session.context.new_page()` | 发布页 `open_upload_page` 之前（`new_page` 后立刻） |
| 百家号 | 1 | `main.py:446` | 同上（`main.py:446` 后） |
| 大鱼号 | 1 主 + 1 只读预览 tab | `main.py:239` 主；`publication.py:64` `preview = page.context.new_page()`，82 关闭 | 主 page 构造一次；预览 tab 只读，不需要 Humanizer |
| 抖音 | 1 | `main.py:1099`（视频）/ `1425`（图文） | `new_page` 后；图文是独立入口，各自构造 |
| 虎扑 | 1 | `main.py:483` | `new_page` 后 |
| 快手 | 1 | `main.py:760`（视频）/ `1081`（图文） | `new_page` 后；两个入口各自构造 |
| Facebook | 1 | `main.py:357` | `new_page` 后 |
| Facebook Page | 1 | `main.py:543` | `new_page` 后 |
| Instagram | 1 | `main.py:946` | `new_page` 后 |
| 视频号 | 1 | `main.py:1311`、`1445` | `new_page` 后 |
| TikTok | 1 | `main.py:888` 等 | `new_page` 后；注意 `locator_base` 可能是 `frame_locator`，**不要把 locator_base 传给 Humanizer** |
| 微博 | **2** | `main.py:464` 首页 page；`503-515` `expect_popup()` 得到 `publish_page` | **两个实例**：`Humanizer(page)` 用于 508；`Humanizer(publish_page)` 用于 524 之后全部 |
| 雪球 | 1 主 + 1 只读核对 tab | `article.py:271`；`335` `check_page = session.context.new_page()`；`verification.py:59` 独立 context | 主 page 构造一次；核对 tab 只读，且 `verification.py` 是独立 context，不共享 |
| YouTube | 1 | `main.py:363` | `new_page` 后 |
| 知乎 | 1 主 + 1 发布后详情 tab | `video.py:255`/`article.py:264`；`video.py:311` `expect_popup()` | 主 page 构造一次；详情 tab 只读，不需要 |

**结论**：15 个平台里只有微博在**发布路径**上有第二个可交互 page（popup），其余多 page 都是只读核对 tab。因此“每 uploader 一个 Humanizer”在 14 个平台成立，微博需要 2 个。`[code]`

---

## 21. 汇总对账

### 21.1 与地图记录的模式计数对账

| 模式 | 地图记录 | grep 命中 | 实际 | 差异说明 |
| --- | --- | --- | --- | --- |
| `.fill(` | 34 | 34 | 34 | 全部是调用；无注释命中 |
| `keyboard.type(` | 12 | 12 | 12 | 全部是调用 |
| `press_sequentially` | 1 | 1 | 1 | `insgraph/controls/location.py:191`；无其他 |
| `.click(` | 303 | 303 | **294** | 303 次命中 = 294 个真实调用 + 8 行注释/文档字符串（hupu 579/634、`_rows.py` 95/117、`location.py` 8/237、weibo 505/518）+ 1 行字符串实参（tk 2390 的 `"el => el.click()"`）。294 个调用中 4 个跨多行（tk 1223/2061/2065/2100，`await` 在上一行） |
| `el => el.click` / `evaluate(...click` | 9 | 9 | 9 | 全部真实；另有 3 行注释提到 `el.click()`（`_rows.py` 95/117、`location.py` 237）不在此模式内 |
| `force=True` | 19 | 19 | **18** | `tk_uploader/main_chrome.py:1030` 是 `tiktok_setup` docstring 里的说明文字 |
| `select_option` | 3 | 3 | **0 个 Playwright API** | 1 个本地方法定义 + 2 次调用（zhihu `video.py:129/278/279`） |
| `set_input_files` | 31 | 31 | **28** | weibo 591（docstring）、tk 2898（注释）、tk 2913（f-string） |
| `.hover(` | 1 | 1 | 1 | douyin 935 |

**为什么模式计数之和 ≠ 唯一行数**：413 个模式命中落在 **386 个唯一行**上，27 行同时命中 2 个模式（绝大多数是 `click(force=True)` 同时算 `.click(` 与 `force=True`；`evaluate("el => el.click()")` 同时算 `.click(` 与 `el => el.click`）。386 行再减去 12 行注释/文档字符串/字符串实参，得到 **374 个真实调用**；其中 zhihu 的 3 行是本地的 `select_option` 方法（1 定义 + 2 调用），所以**页面交互调用点为 371**。

### 21.2 逐平台原始命中

| 平台 | 模式命中 | 唯一命中行 | 页面交互调用点（去掉注释/字符串/本地方法） |
| --- | --- | --- | --- |
| 支付宝 | 17 | 16 | 16 |
| 百家号 | 17 | 15 | 15 |
| 大鱼号 | 36 | 36 | 36 |
| 抖音 | 60 | 53 | 53 |
| 虎扑 | 17 | 17 | 15 |
| 快手 | 30 | 28 | 28 |
| Facebook | 10 | 10 | 10 |
| Facebook Page | 22 | 22 | 22 |
| Instagram | 22 | 20 | 16 |
| 视频号 | 37 | 34 | 34 |
| TikTok | 53 | 48 | 45 |
| 微博 | 31 | 26 | 23 |
| 雪球 | 13 | 13 | 13 |
| YouTube | 8 | 8 | 8 |
| 知乎 | 40 | 40 | 37 |
| **合计** | **413** | **386** | **371** |

说明：Instagram 的 16 = 20 行减 4 行注释/文档字符串；TikTok 的 45 = 48 行减 3 行（`1030` docstring、`2898` 注释、`2913` f-string），其中 `2390` 那行是真实 evaluate 调用；知乎的 37 = 40 行减 3 行本地 `select_option`（`129` 定义、`278/279` 调用）。微博 23 = 26 行减 3 行注释/文档字符串。

---

## 22. 最危险的 5 处（给 spec 的优先级）

1. **YouTube `_fill_editable`（`main.py:237-253`）——与“逐字符”直接冲突。**
   docstring 明写：标题/简介里的 `#`（如 `#Shorts`）会触发话题自动补全浮层，逐字输入会让浮层持续跟随、盖住输入框和后续「继续/发布」，导致流程卡死；所以必须一次性 `fill`。这是本次移植唯一一处“现有注释反对人类化”的地方。spec 必须给出例外或给出“输入后强制 Esc/清浮层”的替代方案。`[code]`

2. **微博发布按钮（`main.py:912`）——禁令与现状硬冲突。**
   按钮中心被空 div 覆盖，现网只能用 `el.click()` 绕过；同一平台 `861`（新建合集）和 `941`（确认框）还有两处 JS 兜底。若规格只说“禁止 `el.click()`”，微博发布流会直接不可用。需要一条“提交按钮被装饰层覆盖”的合法路径（已知点位、点父级、先移除/关闭覆盖层），并明确它是否算白名单。`[code]`

3. **抖音 `_native_click`（`main.py:91-130`，8 处调用）——重复实现 + 合成事件。**
   它已经做了 `mouse.move` + `mouse.click`，但**没有 stillOn 复核**，且在 `mouse.click` 之后又用 `elementFromPoint` 派发一整套 `pointerdown/mousedown/pointerup/mouseup/click`。这既是 Humanizer 的重复实现，也踩到“真实事件”的边界：接 Humanizer 后必须整段删除，否则一次点击可能派发两次。`[code]`

4. **TikTok 配文 `insert_text`（`2441`）与话题 `insert_text`（`2338`）——计数盲区。**
   配文不在 `keyboard.type` 的 12 条里，也不在 `fill` 的 34 条里；它先 `End` → `ControlOrMeta+A` → `Delete` → 整段 `insert_text`。Draft.js 对逐字输入的事件序列敏感（现有注释已经踩过 macOS 全选的坑），spec 若按 grep 计数排期会漏掉 TikTok 最大的一段文本输入。`[code]`

5. **大鱼号 `#author` 预填（`article.py:226`）与 iframe 正文（`article.py:139-141`）。**
   `#author` 的注释明写“作者缺省时沿用页面值”——这是“打开时已有默认值”的实证，若照搬“先全选清空再输入”，会把账号作者名清掉。同文件正文在独立 iframe 内，`body.click()` 与工具栏点击都是 frame 内目标：Humanizer 能用，但任何“只处理主 frame”的实现假设都会在这里失效。`[code]`
