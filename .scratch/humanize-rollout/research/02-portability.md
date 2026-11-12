# 02 — Humanizer 的可移植性边界

> 工单：[`../issues/02-portability.md`](../issues/02-portability.md)
> 范围：只回答「这套交互层要求页面长什么样、在哪里一定做不到」。不设计 spec 字段、不改生产代码。
> 方法：只读工作树 + 逐行读 `.venv` 内 **patchright 1.64.4** 的 Python 层与 `driver/package/lib/coreBundle.js`（Playwright 服务端打包产物，含 `// packages/playwright-core/src/server/...` 源路径注释）。**未启动浏览器、未跑任何平台流程。**
> 置信度：`[code]` 工作树/库源码可读 · `[doc]` 库或标准文档明示 · `[inferred]` 由代码推导 · `[needs-live]` 必须真机确认。

---

## 0. 能力表（能 / 不能 / 有条件）

| # | 问题 | 能力 | 一句话结论 | 决定性前提 / 失败模式 |
| --- | --- | --- | --- | --- |
| 1 | 依赖面（`ensure_in_viewport` + `check(..., "interactive")`） | **有条件** | 要 `Locator`、已导航、`count()==1`、非零 box、落点命中目标自身或其后代、`pointer-events != none`、`opacity >= 0.1` | 任一不满足即 `_not_dispatched(...)`；**内部零重试**，异常就是终局 |
| 2a | 跨 frame（iframe） | **能（坐标自洽）** | `bounding_box()` 与 `page.mouse.*` 都在**主 frame 视口 CSS px**；`stillOn` 的 hit test 在元素所在 frame 内自洽 | frame 被父级裁剪、但主 frame 落点仍在视口内时**不会滚动** → `covered-by:unknown` |
| 2b | shadow DOM | **不能（内部目标）/ 能（host）** | `document.elementFromPoint` 命中 shadow 内元素时返回 **shadow host**，`el.contains(host)` 为假 → `covered-by:<host>` | closed shadow root 连 `Locator` 都造不出来 |
| 3 | 新标签页（popup） | **有条件** | 必须为新 `page` **重建** `Humanizer`；旧实例只能继续操作旧 page | 重建后指针回 `(0,0)`、`_rng` 重新播种；`enabled` 在构造时快照 |
| 4 | 内层滚动容器 | **有条件** | 「是否需要滚」只看主 frame 视口；「滚」这一步走 Playwright，能滚内层容器 | 元素被内层 `overflow` 裁剪但几何仍在视口内 → 判断为「不用滚」→ `covered-by`，且不重试 |
| 5 | 托管模式（`connect_over_cdp(no_defaults=True)`） | **有条件** | mouse/keyboard 的 CDP 路径与本地一致；但 `page.viewport_size is None` → `ensure_in_viewport` **静默按 1280×720** 判断 | 真实窗口任意尺寸都可能判错；`no_defaults` 的 focus emulation 文档与代码不一致 |
| 6 | 无坐标可点类别 | **不能（按设计）** | file input、`<option>`/原生下拉、`visibility:hidden` 的 JS-only 按钮、零尺寸/`display:contents`、closed shadow、原生浏览器 UI | 逐类替代写法见 §6；多数已在 charter 的「保持原生」范围 |
| 7 | 已知退化 | **有条件** | `>1000` 字符整段 `insert_text`、指针从 `(0,0)` 起步、CDP 合成事件无 OS 级指针 | 必须写进 spec，不能当成「效果略差」 |

补充一条**不在工单里但影响最大**的发现（见 §1.4）：

| # | 问题 | 能力 | 结论 |
| --- | --- | --- | --- |
| 1.4 | `:hover` 会改变布局的目标 | **不能** | `stillOn` 用「移动**前**的 box」对比「移动**后**的 box」，容差 ±1px。hover 触发 `transform`/尺寸变化 >1px 就必然 `point-drift`，且不重试 |

---

## 1. 依赖面：`ensure_in_viewport` + `check(..., "interactive")` 要求什么

### 1.1 对 `locator` 的要求

| 要求 | 依据 | 不满足时 |
| --- | --- | --- |
| 必须是 **`Locator`**，不能是 `ElementHandle` | `check` 调 `locator.count()`（`utils/dom.py:477`）；`ElementHandle` 有 `bounding_box`/`is_visible`/`is_enabled`/`scroll_into_view_if_needed`，但**没有 `count()`** | `count()` 抛异常 → 只记 `probe-failed` warning 然后继续（会绕过「唯一命中」这道门）；`ensure_in_viewport` 仍可工作 |
| **唯一命中**：`count() == 1` | `dom.py:484-486`（`ambiguous:{count}` 立即阻断） | 抛 `ElementUnusableError(reason="ambiguous:N")`。现网大量 `get_by_role(...)`/`get_by_text(...)` 未 `.first`，移植前必须收窄 |
| 仍在文档里：`isConnected` | `dom.py:490-491` | `not-attached` |
| 有**非零包围盒** | `dom.py:398-399`、`humanize.py:273-274` | `zero-box` |
| 元素自身 `pointer-events != none` | `dom.py:388-390` | `pointer-events-none`（注意：只看**自身**，不看祖先，见 §6.4） |
| 元素自身 `opacity >= 0.1`（祖先 opacity 累乘） | `dom.py:360` | `opacity-zero`（透明但仍可命中的元素会被**误杀**，见 §6.7） |
| 落点处 `elementFromPoint` 命中**自身或其后代** | `dom.py:175-191`、`407-413` | `covered-by:<tag.class|#id|text>` 或 `covered-by:unknown` |
| 元素 `is_enabled()` 不为 `False` | `dom.py:377-381` | `disabled` |

### 1.2 对 page / 视口的要求

- **必须已导航**：`about:blank` 上没有任何元素，`count()==0` → `not-attached`。`bounding_box()` 也返回 `null`。`[inferred]`
- **视口必须非零且已知**：`ensure_in_viewport` 读取 `page.viewport_size`（`dom.py:290-297`）；
  - 返回 dict → 用真实值；
  - 返回 `None` 或抛异常 → **静默回退** `DEFAULT_VIEWPORT_WIDTH/HEIGHT = 1280/720`（`dom.py:249-250`）。
  - `page.viewport_size` 来源于库的 `viewportSize` 初始化字段（`patchright/_impl/_page.py:159`），服务端取值 `page.emulatedSize()?.viewport`（`coreBundle.js` `PageDispatcher`）。**没有 viewport 时它是 `None`，不是 `window.innerWidth`。**
- **`box` 必须在「判断 → 移动 → 复核」期间稳定**：`ensure_in_viewport` 用 `box` 决定要不要滚（`dom.py:298-300`），滚动后调用方重测一次（`humanize.py:263-265`），`stillOn` 再测一次并按 ±1px 比对（`humanize.py:285-287`）。
- **落点必须与鼠标实际落点一致**——这一点**不成立**，见 §1.3。

### 1.3 `stillOn` 校验的是「锚点」，不是「实际点击点」

`Humanizer.click` 的落点是 `_inset_point(...)`：以 `point`（默认 `(0.5,0.5)`）为锚点、在 `min(size*0.15, 8px)` 内随机抖动（`humanize.py:276, 332-356`）。
但 `check(locator, "interactive", point=ratio)` 传的是**锚点比例**（`humanize.py:288`），`_HIT_TEST_JS` 用 `rect.left + rect.width * point[0]` 重新算点（`dom.py:177-179`）。

结论：`check` 通过只证明**锚点**处命中目标；实际 `mouse.down` 的位置可能偏移最多 **8px**（大元素）或 **15% 尺寸**（小元素）。`el.contains(hit)` 的宽容量（`dom.py:184`）能吸收大部分子节点差异，但边缘 8px 内仍可能点到兄弟节点。`[code]` + `[inferred]`

### 1.4 头号风险：`:hover` 会改变包围盒的目标必然失败

顺序是：测 `box` → 贝塞尔移动（这会触发 `:hover`）→ `pointer_settle`（0.2–1.2s）→ 重测 `still` → `_same_box(box, still, tolerance=1.0)`（`humanize.py:258, 278-287`）。

- 元素的 hover 效果是 `transform: translateY(-1px)` 或 `scale(1.02)`（40px 按钮约 0.4px）→ 差值 ≤1px → **通过**。
- hover 效果是 `scale(1.1)`、换字号、显示一行说明、按钮从 `padding` 变大 → 差值 >1px → **`point-drift`，且内部零重试**（模块文档「不存在没有 stillOn 的坐标点击」`humanize.py:24-27`）。

这条不是 XHS 的个案：Instagram/Facebook/TikTok 一类带 ripple/缩放的按钮、以及 hover 才展开的浮层，都属于高危。**规格必须先给「click 目标不得 hover 变形」的硬约束，或明确接受这类目标保持原生。**

### 1.5 其他前置条件

- `type_text` **不负责聚焦**。它直接 `page.keyboard.press/insert_text`（`humanize.py:223-237`），打到「当前焦点元素」。XHS 是显式 `title_container.locator.focus()`（`xiaohongshu_uploader/main.py:1969`）或先 click。**所有移植点必须保持「先 click/focus，再 type」的顺序。**
- `type_text` 不负责**清空**。清空策略逐字段手写（charter 第 5 条）。
- `page.keyboard` 是**页面级**，不是 locator 级。`frame_locator` 里的元素只有在它真的拿到焦点后才会收到字符。`[inferred]`
- `Humanizer.enabled` 在构造时快照（`humanize.py:173`）。运行中再设 `HUMANIZE=0` 对已存在的实例**无效**。

---

## 2. 跨 frame 与 shadow DOM

### 2.1 iframe：坐标系是对齐的 `[doc]` `[code]`

- `Locator.bounding_box()` 文档原文：「calculated relative to the **main frame viewport**」「Elements from child frames return the bounding box **relative to the main frame**」（`patchright/async_api/_generated.py:10577-10595`）。
- `Mouse.move(x, y)` 文档原文：「X/Y coordinate relative to the **main frame's viewport** in CSS pixels」（`_generated.py:15311-15327`）。
- Chromium 实现：`DOM.getBoxModel` 拿 frame 内坐标，再叠加 `_framePosition()` 的 iframe 偏移（`coreBundle.js:41727-41743`）；OOPIF 用各自的 session 与 target 计算偏移，因此**同进程 iframe 与跨域 iframe 都返回主 frame 坐标**。
- `_HIT_TEST_JS` 用 `document.elementFromPoint`（`dom.py:180`），而 `locator.evaluate` 在**元素所属 frame** 内执行 → 用的是该 frame 的 `getBoundingClientRect()` 与视口，**自洽**。

已确认的真实 iframe 目标：`tk_uploader/main_chrome.py:2688`（TikTok 上传表单整个在 `iframe[data-tt="Upload_index_iframe"]` 内，`locator_base` 全部派生自它）、`dayu_uploader/article.py:139`（UEditor 正文 `body[contenteditable=true]`）、`tencent_uploader/main.py:192`（登录二维码 iframe，登录路径不在范围）。

### 2.2 iframe 的真缺口：父级裁剪不在「是否需要滚」的判断里

`ensure_in_viewport` 只在**主 frame 视口**上比较落点（`dom.py:298-300`）。示例：

- iframe 位于主 frame `y=0,h=400`，内部元素 local `y=800` → 主 frame `y≈800`；窗口高 900 → 判定「在视口内，不滚」。
- 但 iframe 自己的可视区只有 400 → 子 frame 的 `elementFromPoint(…, 800)` 返回 `null`（MDN：坐标超出文档可视范围返回 `null`）→ `covered-by:unknown`。
- 若窗口高 700，主 frame 落点 `y=800 > 700` → 才会 `scroll_into_view_if_needed`，Blink 的 scroll-into-view 会连带滚动子 frame 的内部滚动容器 → 恢复正常。

**同一个元素，窗口高度不同，结果不同。** 这是可解释、但不可预测的行为，spec 必须承认。

### 2.3 shadow DOM：内部目标不行，host 行 `[doc]` `[inferred]` `[needs-live]`

- `document.elementFromPoint` 对 shadow 树内的命中**按 Blink 实现会回退（retarget）到 shadow host**（这也是 `ShadowRoot.elementFromPoint` 存在的理由；CSSOM View 把 hit testing 细节留给实现，见 <https://drafts.csswg.org/cssom-view/#dom-document-elementfrompoint> 的 note）。**本仓库未真机验证**；若实测返回内层元素，本条结论翻转为「能」。`[inferred]` `[needs-live]`
- 于是：Playwright 的 CSS 选择器**能穿透 open shadow root** 拿到内部元素的 `Locator`，`bounding_box()` 也正常；但 `check` 里 `hit === host`，`el.contains(host)` 为 **false** → `covered-by:<host>` → 阻断。
- 只有把 locator 指向 **host 本身**，`self` 才成立。这时可以用 **host + 比例点** 曲线救国：`click(host, point=(fx, fy))`，`fx/fy` 由内部元素的 box 相对 host box 折算。
- **closed shadow root**：Playwright 的 `locator()` 根本选不到内部节点（只有 `evaluateHandle` 能拿 `ElementHandle`，而 `check` 不认 `ElementHandle`）→ 该目标**不做改造**。
- 另有一处 shadow 相关缺陷：`_FACTS_JS` 的祖先遍历用 `el.parentElement`（`dom.py:138-151`），到 shadow root 顶层就 `null` 停了，**看不到 host 的 `opacity/aria-hidden`**。若 host 是 `opacity:0`，子元素会被判「可见」，`mouse.down` 打在不可见位置 → **假阳性**。

平台侧风险：YouTube Studio 的 `ytcp-*` / `tp-yt-paper-*` 组件是否走 native shadow 需要真机确认（若是 ShadyDOM 则无影响）；Instagram 的 Lexical 编辑器是普通 DOM，无此问题。`[needs-live]`

---

## 3. 新标签页：必须重建实例

### 3.1 结论

`Humanizer` 绑定 `self.page`（`humanize.py:171`），用于 `page.keyboard` / `page.mouse`（`:214, 241, 280, 292-296`）以及 `ensure_in_viewport` 的 `viewport_size`（`dom.py:290`）。
**点击打开新 tab 后必须 `Humanizer(new_page)`**，理由有三：

1. 旧实例的 `page.mouse` 操作旧 page；新 tab 的内容根本不在旧 page 的坐标空间里。
2. `ensure_in_viewport` 会用**旧 page 的 `viewport_size`** 去判断新 page 上的 locator（`dom.py:290-297`），两者可能不同（旧 page 有 viewport、新 tab 以 `window.open` 继承父窗口尺寸）。
3. 旧 tab 若被平台关闭（OAuth 回调、`window.close()`），旧实例的所有调用都会抛「target closed」。

### 3.2 重建后什么被重置、是否要紧

| 状态 | 位置 | 重置后果 | 是否要紧 |
| --- | --- | --- | --- |
| `_pointer` | `humanize.py:176` | 下一段贝塞尔从 `(0,0)` 起步（`:277`） | 不要紧，但**首段路径会横穿整个视口**，可能沿途触发 hover 浮层。属于保真度问题，不是正确性问题 |
| `_rng` | `humanize.py:174` | 重新用系统熵播种，分布不变 | 不要紧；**唯一影响是测试不可复现**——需要固定随机流时应在构造时显式传 `rng=` |
| `enabled` | `humanize.py:173` | 重新读 `HUMANIZE` | 反而是好事；但意味着「运行中改环境变量」只在重建后生效 |
| 时间预算 | 外部 `PublishTimeoutBudget` | 不变 | 不要紧 |

### 3.3 已在代码里发生的真实案例 `[code]`

- **微博**：`main.py:503-515` 用 `page.expect_popup()` 点「视频」拿到 `publish_page`，后续 2–10 步全部在新 page 上 → 必须两个实例（`Humanizer(page)` 只给入口那一次点击，`Humanizer(publish_page)` 给其余）。
- **知乎**：`video.py:311` 发布后用 `expect_popup()` 开「查看详情」，只读核对 → 不改造。
- **大鱼**：`publication.py:64` / `verification.py` 用 `context.new_page()` 做公开页核对 → 不改造。

规格约束：**「一个 page 一个实例」是硬规则；跨 page 复用同一实例一律算错误。**

---

## 4. 滚动容器：判断只看窗口，动作能滚内层

### 4.1 精确语义

- **判断**：`needs_scroll = not (0 <= target_x <= vw and 0 <= target_y <= vh)`（`dom.py:298-300`）。只比主 frame 视口，**完全不看祖先 `overflow`、不看 iframe 自身可视区、不看 `clip-path`**。
- **动作**：`locator.scroll_into_view_if_needed(timeout=2000)`（`dom.py:304-313`）→ Playwright `ElementHandle.scrollIntoViewIfNeeded` → `_waitAndScrollIntoViewIfNeeded(..., frameVisible=true)`（`coreBundle.js`，`_scrollRectIntoViewIfNeeded`）→ Chromium `Page.scrollIntoViewIfNeeded`。按 Blink 的 scroll-into-view 语义，它会滚**所有祖先滚动容器**，跨 frame 时再上报父 frame。`[inferred]`（Playwright 的 iframe 点击依赖此行为，但本仓库未真机验证跨 frame 传播）`[needs-live]`
- **吞噬异常**：`ensure_in_viewport` 把「不需要滚」「滚失败」「locator 没这方法」都归成 `False`（`dom.py:302-313`），调用方无法区分 → 失败只能表现为后面的 `covered-by:*` / `point-drift`。

### 4.2 内层滚动容器的失败条件（必须写进 spec）

只有当**元素几何落点已经在主 frame 视口之外**时才会去滚。因此「内层容器裁剪、但几何位置仍在视口内」的目标：

- `bounding_box()` 照常返回（裁剪不改变 layout 几何）；
- `needs_scroll=False` → 不滚；
- `elementFromPoint` 在裁剪区外返回覆盖者或 `null` → `covered-by:<other>` / `covered-by:unknown`；
- 无内部重试 → 直接失败。

同一个元素，只要容器恰好被滚到可见位置，就能点。**行为依赖上一次操作后的滚动残留。**

### 4.3 平台侧候选（按风险排序）

| 平台 | 内层滚动载体 | 依据 |
| --- | --- | --- |
| 抖音 | 选音乐 `.semi-sidesheet-content` 侧栏、商品/合集下拉 | `douyin_uploader/main.py:658-667`（sidesheet 内 `input.semi-input`、`.card-container-*`）`[code]` |
| 快手 | antd `Select` 下拉（rc-virtual-list，虚拟滚动 + 只在打开时渲染） | `ks_uploader/main.py:661-674`；`option.count()==0` 已被当成「未找到」`[code]` |
| 视频号 | 合集 `.option-list-wrap`（自定义列表） | `tencent_uploader/main.py:891-918`，其中 `918` 已有 `force=True` 兜底，注释写明 headless 小视口 `[code]` |
| 知乎 | 领域/标记下拉 `selectList:visible`、日历浮层 | `zhihu_uploader/video.py:109-156`、`schedule.py:45-75` `[code]` |
| Facebook Page | 日期日历网格、按钮序号取项 | `facebook_page_uploader/main.py:409-426` `[code]` |
| 微博 | 合集面板（已用 JS 绕过中心被覆盖） | `weibo_uploader/main.py:855-861` `[code]` |
| YouTube | 详情页长表单在**窗口**级滚动（`#description-textarea`），不是内层容器；风险低 | `youtube_uploader/main.py:390-401` `[inferred]` |

> 微博本地模式给了 `viewport=1280×2000`（`weibo_uploader/main.py:84`），虎扑是 `1920×1080`（`hupu_uploader/main.py:144`）——**大视口会把 §4.2 的缺口藏起来**，离线测试通过不代表托管模式（真实窗口）能过。

---

## 5. 托管模式：`connect_over_cdp(..., no_defaults=True)`

### 5.1 一样的部分 `[code]`

`page.mouse` / `page.keyboard` 最终都是 `Input.dispatchMouseEvent` / `Input.dispatchKeyEvent` / `Input.insertText`（`coreBundle.js:21433-21480`、`:38880`），与 page 是 `launch` 来的还是 `connect_over_cdp` 来的**无关**。`Humanizer` 不需要为托管模式换实现。

### 5.2 不一样的部分

| 差异 | 依据 | 后果 |
| --- | --- | --- |
| **`page.viewport_size is None`** | `_connectOverCDPImpl` 无条件设 `persistent = { noDefaultViewport: true }`（`coreBundle.js:46781-46783`）；`_updateViewport()` 在 `emulatedSize()` 为空时直接 return（`..._updateViewport` / `emulatedSize()`）；Python 侧 `_viewport_size = initializer.get("viewportSize")`（`_page.py:159`）→ `None` | `ensure_in_viewport` 回退 **1280×720**（`dom.py:293-297`）。**发布主力模式就是托管模式**（`utils/browser_session.py:389-393`）→ 真实窗口若小于 1280×720，视口外目标会被判「在视口内」，不滚，然后 `covered-by:unknown` |
| `no_defaults=True` 跳过默认媒体/下载覆写 | 文档 `async_api/_generated.py:3944-3949`；代码 `coreBundle.js:41166,41183`（`skipDefaultOverrides` 只用于 `_updateEmulateMedia`） | 与 mouse/keyboard 无关 |
| focus 仿真 | 文档说 `no_defaults` 时「focus emulation is not enabled」（`_generated.py:3946`）；但本构建代码是 `if (isMainFrame && !options.focusControl)` 就发 `Emulation.setFocusEmulationEnabled`（`coreBundle.js:41169`），`focusControl` 默认 `false` | **文档与代码不一致**。若真机上面 `document.hasFocus()` 为 false，某些编辑器会表现为「点了不聚焦」。`[needs-live]` |
| 页面可能是后台 tab / 窗口未聚焦 | — | CDP 注入的事件仍会进 renderer；但依赖 `document.hasFocus()`、`visibilityState` 的组件行为会不同。建议在点击前 `page.bring_to_front()`，但这超出 `Humanizer` 现有职责，spec 应显式规定 `[inferred]` |
| 浏览器缩放 / DevTools 停靠 | — | `bounding_box` 与 CDP 坐标都以 CSS px 计，缩放本身一致；但 DevTools 停靠会改变可视宽高，而 `viewport_size` 又是 `None` → 更容易判错 `[inferred]` |
| 指针初始位置 | 新 page 的 `Mouse._x/_y = 0`（`coreBundle.js:21433`） | 与本地一致；第一段路径从左上角出发 |

### 5.3 结论

托管模式**不需要**换实现，但必须在规格里规定：`ensure_in_viewport` 的视口必须来自 `page.evaluate("({w:innerWidth,h:innerHeight})")` 或等价手段，**不能依赖 `page.viewport_size`**（这是唯一会让 15 个平台同时踩坑的公共缺陷）。`[inferred]`（修法可选，现状是 `[code]`）

---

## 6. 无坐标可点类别（按设计不可点）

| # | 类别 | 为什么点不了 | 现有代码证据 | 替代写法 |
| --- | --- | --- | --- | --- |
| 6.1 | `input[type=file]`（常见 `opacity:0` + 绝对定位覆盖） | `opacity < 0.1` → `opacity-zero`；触发的是**原生文件对话框**，不在 DOM 里 | 31 处 `set_input_files`；`dayu_uploader/article.py:178`（弹窗内 `input[type=file]`） | `set_input_files()`；或 `expect_file_chooser()` + `file_chooser.set_files()`（charter：保持原生） |
| 6.2 | 原生 `<select>` 的 `<option>` | `<option>` 没有独立 box（`zero-box`）；展开的列表是**浏览器 UI**，不是 DOM | 3 处 `select_option` | `select_option()`（保持原生）。若平台是自定义下拉（`role=option` 在 DOM 里）则不在本类 |
| 6.3 | `visibility:hidden` / `display:none` 的「JS 专用」按钮 | `_visible` 直接判 `zero-box`（`dom.py:356-359`） | 抖音 BGM「使用」按钮：`douyin_uploader/main.py:686` 用 `el => el.click()`，注释写明 `visibility:hidden` | 先 `hover(卡片)` 让按钮显形再 `click`；若 hover 后仍 hidden → 保持原生并登记例外 |
| 6.4 | 祖先 `pointer-events:none` 的包装层 | 元素自身 `pointerEvents` 是 `auto`，`_FACTS_JS` 看不到（`dom.py:167`）；`elementFromPoint` 跳过整棵子树 → 命中背后的元素 | — | 点 `pointer-events:auto` 的子元素；或点视觉上的真实可点层 |
| 6.5 | 零尺寸覆盖层（`width/height:0`，子元素溢出可见） | `bounding_box()` 为 0 → `zero-box`（`humanize.py:273-274`） | 部分 `force=True` 的目标 | 点溢出的子元素 |
| 6.6 | `display:contents` 容器 | 不生成盒子 → 0 box | — | 点具体子元素 |
| 6.7 | **透明但可命中**的元素（`opacity:0` 点击捕手） | `check` 用 `opacity < 0.1` 主动拒绝（`dom.py:360`），尽管浏览器会派发 | — | 点其可见兄弟/子元素；这是**假阴性**，需在 spec 里说明「透明遮罩不可作为 click 目标」 |
| 6.8 | shadow DOM 内部元素 | 见 §2.3（`elementFromPoint` 回退 host） | — | 点 host + 比例点；closed shadow 保持原生 |
| 6.9 | `<area>`（image map） | 无 box；`elementFromPoint` 返回 `<img>` | — | `click(img, point=(fx,fy))`（仅静态布局） |
| 6.10 | 原生浏览器 UI：日期选择器弹层、自动填充下拉、权限弹窗、打印、右键菜单 | 完全不在 DOM | 视频号/抖音/知乎的日期控件都是**自定义** DOM 弹层，不属此类；`<input type=date>` 的原生 picker 才属此类 | 用 `fill()`/逐键输入写值；不要点日历图标 |
| 6.11 | iframe 元素本身 | `check(iframe)` 在父文档会命中 `<iframe>` → 通过，但点击会**穿透到子文档**，不是「点 iframe」 | — | 子 frame 内目标用 `frame_locator(...).locator(...)`；不要把 `<iframe>` 当点击目标 |
| 6.12 | 需要拖拽（mousedown A / mouseup B）的目标 | `Humanizer` 只在同一落点 `down/up`（`humanize.py:292-296`） | `<body.press("Shift") + dispatch_event("mouseup")`（`dayu_uploader/article.py:166-167`，UEditor 选区） | 不改造；保持原生 |
| 6.13 | closed shadow root 内部控件 | 选不到 `Locator` | — | 不改造 |

> 交叉参考：19 处 `force=True` 与 9 处 `el.click()` 里，相当一部分正落在 6.1/6.3/6.4/6.5/6.7 上。ticket 03 的白名单本质上是「为这些类别开口子」，本表给出的是「能不能靠换目标消掉」的判断依据。

---

## 7. 已知退化（必须显式写进规格）

1. **`>type_horizon_chars`（1000）整段一次 `insert_text`**：零 `keydown`/`keyup`、零逐字采样、只打一条 `info`（`humanize.py:217-221`）。阈值按 **Python 码点**算（`len(text)`），不是字素：一个 ZWJ emoji 家族（👨‍👩‍👧‍👦）占 7 个码点，约 143 个这样的 emoji 就会越过 1000 落进 bulk 路径。
2. **`insert_text` 不是按键**：只产生 `beforeinput`/`input`（`Input.insertText`，`coreBundle.js:38880`），中文/emoji 全部走这条路（`humanize.py:236-237`）。没有 IME composition 事件、没有 `keydown`。依赖 `keydown` 计数的编辑器（少数直播/短视频后台）会认为「没输入」。
3. **ASCII 走 US 布局**：`keyboard.press(char)` 的 key 定义来自 USKeyboardLayout（`coreBundle.js` `init_usKeyboardLayout`）。大写字母 `"A"` 命中的是 shifted 条目（`coreBundle.js:21303`），但 `_pressedModifiers` 里没有 Shift → `keydown` 的 `shiftKey=false`。**字符本身插得对、`event.code`（`KeyA`）也对**，只有 `shiftKey`/modifier 位是假的。
4. **指针从 `(0,0)` 起步**：每个新实例/新 page 的第一段路径从左上角出发（`humanize.py:277`、`coreBundle.js:21433`），可能横穿导航栏/浮层并触发 hover。
5. **`_pointer` 会与 Playwright 内部位置发散**：如果同一 page 上混用原生 `locator.click()`（Playwright 自己会 `mouse.move`）和 `Humanizer.click`，Humanizer 的 `_pointer` 不知道这次移动 → 下一段路径从旧位置「瞬移」。规格应禁止混用，或规定「同一 page 只用一种点击方式」。
6. **无 OS 级指针**：CDP 合成的事件 `isTrusted=true`，会正常更新 `:hover`、会派发 pointer 事件、`clickCount=1`（`coreBundle.js:21465`），但**系统光标不动**、没有 `sourceCapabilities`。屏幕录制/摄像头层面没有指针轨迹。任何「检测真实鼠标轨迹」的站点不在此列（本 effort 也不承诺反检测）。
7. **换行/制表符是具名键**：`\n` → `Enter`、`\t` → `Tab`（`humanize.py:230-233`）。在单行 `<input>` 上按 Enter 可能触发表单隐式提交；`\r` 不是可打印字符 → 走 `insert_text("\r")`（可能被丢弃）。规格应要求调用方把 `\r\n` 归一成 `\n`，且单行字段不得传换行。
8. **`HUMANIZE=0` 不是「同一路径去掉停顿」**：它走 `locator.click()` / 单次 `insert_text`（`humanize.py:212-215, 247-255`），语义变成 Playwright 的自动等待/自动滚动/actionability。**关闭人类化会改变成功/失败集合**，回滚验证必须按这个前提设计。
9. **`hover` 没有 `stillOn`**（`humanize.py:302-330`）：它只移动+停顿，不校验落点。hover 揭出的入口是否真的出现，要靠调用方自己的 `wait_for`。
10. **`press()` 不看 `enabled` 但 `_pause` 会短路**（`humanize.py:239-242`）：`HUMANIZE=0` 时仍会按键，只是不睡。属于预期行为，但和「完全原生」不完全等价。
11. **`after_type` 在空串上也照付**：`type_text("")` 仍会 `_pause(after_type)`（`humanize.py:223-226`）。
12. **时间预算**：均值 136ms/字、点击 ≈0.4s/次（`humanize.py:35-38`）。`point-drift` 失败后的重试发生在 ARM 循环（不在本层），一次失败至少多花一次点击成本。

---

## 8. 规格必须写死的限制

以下条目建议**逐字**进入 `spec.md` 的「限制」章节（数字与函数名可直接引用本文件）：

- **只支持 Chromium（patchright）**。`bounding_box` 的 frame 偏移、`elementFromPoint` 的 shadow 回退、`Input.insertText` 的行为均按 Chromium 语义描述；Firefox/WebKit 不在验证范围。
- **点击目标必须是 `Locator`，且 `count() == 1`**。禁止把 `ElementHandle`、裸选择器、`page.click(selector)` 传给 `Humanizer.click`；多匹配必须先收窄（`.first`/`.filter`），否则必然 `ambiguous:N`。
- **点击前页面必须已导航，且目标有非零、稳定的包围盒**。`zero-box` / `no-bounding-box` 不是可重试错误。
- **click 目标在 hover 时不得发生 >1px 的布局或 `transform` 变化**。`stillOn` 的 ±1px 容差会把它判成 `point-drift`，且本层不重试。若平台按钮有 hover 缩放/展开，该目标保持原生或改点不动的父级。
- **`stillOn` 校验的是锚点，不是实际落点**。落点可偏离锚点最多 `min(15%尺寸, 8px)`；对边缘敏感的目标（小图标、相邻可点项）必须显式给 `point=`。
- **`type_text` 不聚焦、不清空**。每个字段必须先 `click`/`focus` 再 `type_text`；清空策略逐字段手写，本层不提供。
- **`type_text` 的文本按 Python 码点计长**；`>1000` 码点会退化为单次 `insert_text`（无按键、无节奏），规格必须声明这是有意降级。
- **单行字段不得包含 `\n` / `\r` / `\t`**；换行会变成 `Enter`（可能提交表单），`\r` 会走 `insert_text`。
- **一个 `page` 一个 `Humanizer` 实例**。任何 `expect_popup()` / `new_page()` 之后必须重建实例；禁止跨 page 复用。重建会重置指针到 `(0,0)` 与随机流（如需可复现，构造时显式传 `rng`）。
- **`enabled` 在构造时快照**；`HUMANIZE` 必须在创建实例前设置，运行中修改只对新建实例生效。
- **禁止在同一 page 上混用原生 `locator.click()` 与 `Humanizer.click`**（`_pointer` 会与库内部位置发散），除非该 page 的人类化已整体关闭。
- **`ensure_in_viewport` 的视口不得依赖 `page.viewport_size`**：`connect_over_cdp` 下它恒为 `None`，会静默按 1280×720 判断。规格应要求改用 `page.evaluate` 读取 `innerWidth/innerHeight`，或至少把该回退写成已知缺陷。
- **内层滚动容器与 iframe 裁剪不在自动滚动判断范围内**：只有落点出主 frame 视口才会滚。目标在侧栏/下拉/iframe 内部时，调用方必须先自己把容器滚到可见，或接受 `covered-by:*` 失败。
- **shadow DOM 内部元素不可坐标点击**：`check` 会把 `elementFromPoint` 的 shadow host 当成覆盖者。只允许点 host（+ 比例点）；closed shadow root 目标不做改造。
- **以下类别按设计不做坐标点击**：`input[type=file]`、原生 `<select>/<option>`、`visibility:hidden` 的 JS-only 按钮、零尺寸/`display:contents`、`opacity:0` 的透明可点层、`<area>`、原生浏览器 UI、closed shadow root、需要拖拽的目标。它们全部保持原生，并在 spec 的例外清单里逐条登记。
- **`HUMANIZE=0` 是语义切换而非纯计时切换**（`locator.click` vs 坐标点击），验收要分别覆盖开/关两条路径。
- **iframe 内目标可用，但前提是落点几何在主 frame 视口内且该 frame 未被父级裁剪**；TikTok 上传 iframe、大鱼 UEditor 正文是必须真机验收的两处。
- **托管模式与本地模式共用同一套 mouse/keyboard 路径**；差异只在视口来源与页面焦点，验收矩阵必须包含「Multilogin/AdsPower 真实窗口」一列。

---

## 9. 仍需真机确认（`[needs-live]` 汇总）

1. **`document.elementFromPoint` 对 shadow 内元素是否 retarget 到 host**（§2.3 的整个结论押在这一点上；一条 `evaluate` 即可判定）。
2. YouTube Studio 的 `ytcp-*` 是否为 native shadow DOM（决定 YouTube 是否大面积不可点）。
3. `no_defaults=True` 下 `document.hasFocus()` 的真实值，以及相关编辑器是否因此不聚焦。
4. TikTok 上传 iframe 在 1280×720 与真实窗口下，表单底部按钮是否落在「判定不滚」的死区。
5. 各平台按钮的 hover 变形幅度（>1px 即失败）：Instagram 分享、抖音发布、Facebook Page 发布、视频号发布。
6. 抖音 `.apply-btn` 是否 hover 后变可见（决定 6.3 的替代写法是否成立）。
7. 快手 antd 下拉、知乎领域下拉的虚拟滚动是否会让目标 `count()==0`。

---

## 附录：证据索引

| 主题 | 位置 |
| --- | --- |
| 点击主流程 | `utils/humanize.py:245-300` |
| 落点内缩与抖动 | `utils/humanize.py:332-356` |
| `stillOn` ±1px | `utils/humanize.py:285-287` |
| 指针起点 `(0,0)` | `utils/humanize.py:176, 277` |
| 打字/批量阈值 | `utils/humanize.py:209-237` |
| `ensure_in_viewport` | `utils/dom.py:254-314`（视口回退 `:290-297`，判断 `:298-300`，滚动 `:304-313`） |
| `_FACTS_JS`（祖先遍历止于 shadow root） | `utils/dom.py:132-173`（`:138-151`） |
| `_HIT_TEST_JS` | `utils/dom.py:175-191` |
| `check` 唯一命中 / 角色分派 | `utils/dom.py:461-507` |
| `bounding_box` 主 frame 坐标 | `.venv/.../patchright/async_api/_generated.py:10577-10595` |
| `Mouse.move` 主 frame 视口 CSS px | `.venv/.../patchright/async_api/_generated.py:15311-15327` |
| `no_defaults` 文档 | `.venv/.../patchright/async_api/_generated.py:3944-3949` |
| CDP 连接强制 `noDefaultViewport` | `.venv/.../patchright/driver/package/lib/coreBundle.js:46781-46783` |
| `viewportSize = emulatedSize()?.viewport` | 同上，`PageDispatcher` 构造处 |
| focus emulation 实际条件 | 同上 `:41166-41169` |
| Chromium `boundingBox` + frame 偏移 | 同上 `:41727-41743` |
| `Input.insertText` | 同上 `:38880` |
| `Mouse._x/_y = 0` / `clickCount = 1` | 同上 `:21433`、`:21465` |
| 本仓库托管模式入口 | `utils/browser_session.py:389-393`（`no_defaults=True`） |
| 本仓库视口配置 | `weibo_uploader/main.py:84`、`hupu_uploader/main.py:144`、`insgraph_uploader/main.py:395` |
