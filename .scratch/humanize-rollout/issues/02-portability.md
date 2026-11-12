# 02 — Humanizer 的可移植性边界

Status: resolved
Type: research
Blocked by:

## Question

`Humanizer` 现在只为小红书创作者后台写过，落地到另外 15 个平台前，先确定它的技术边界，避免规格承诺做不到的事。

要回答：

1. **依赖面**：`Humanizer.click` 调用 `ensure_in_viewport`（`utils/dom.py:254-313`）与 `check(locator, "interactive", point=...)`（`:132-228` 的 `_FACTS_JS` / `_HIT_TEST_JS`）。这两者对 locator、page、视口各有什么要求？有哪些前置条件（例如必须已导航、必须有非零 viewport）？
2. **跨 frame**：目标元素在 iframe 内时，`bounding_box()` 与 `page.mouse.move` 的坐标系是否仍然对齐？shadow DOM 内的元素呢？
3. **多标签页**：`Humanizer` 绑一个 `page`。平台在点击后打开新 tab（例如 OAuth、素材库）时，实例是否必须重建？重建后指针位置与随机流会重置，这是否可接受。
4. **滚动容器**：`ensure_in_viewport` 只处理窗口级滚动还是也能处理内层滚动容器？哪些平台的长表单（YouTube 详情、知乎编辑器）可能落在内层容器里。
5. **托管模式**：`connect_over_cdp` 附着的页面与本地 `launch` 的页面在这些行为上是否有差异（`no_defaults=True` 是否影响 mouse/keyboard）？
6. **无坐标可点情形**：列出「按设计就无法坐标点击」的元素类别（`opacity:0` 的 file input、`pointer-events:none` 的容器、零尺寸的可点击覆盖层），并给出替代写法。
7. **已知退化**：`>type_horizon_chars` 一次性 `insert_text`、指针从 `(0,0)` 起步、CDP 合成事件无 OS 级指针——这些在规格里要不要写成显式限制。

输出：`.scratch/humanize-rollout/research/02-portability.md`。结构：一张「能 / 不能 / 有条件」的能力表 + 逐条证据 + 一段「规格必须写死的限制」。

置信度：`[code]` / `[doc]`（patchright、Playwright 文档）/ `[inferred]` / `[needs-live]`。

不要改任何生产代码；不要启动浏览器。

## Answer

结论见 [`../research/02-portability.md`](../research/02-portability.md)。摘要：

1. **依赖面**：`click` 要求 `Locator` + 已导航 + `count()==1` + 非零 box + 落点命中自身/后代 + `pointer-events!=none` + `opacity>=0.1`；内部零重试，任一不满足即终局。`type_text` 不聚焦、不清空。
2. **iframe 能**：`bounding_box()` 与 `page.mouse` 都在主 frame 视口 CSS px（`_generated.py:10577-10595`、`:15311-15327`；`coreBundle.js:41727-41743`），hit test 在元素所在 frame 内自洽。真目标：TikTok 上传 iframe、大鱼 UEditor 正文。
3. **shadow DOM 不能**：`elementFromPoint` 回退到 shadow host，`el.contains(host)` 为假 → `covered-by:<host>`。只可点 host + 比例点；closed shadow 选不到 Locator。
4. **新 tab 必须重建实例**：微博 `expect_popup()` 是真实案例（`weibo_uploader/main.py:503-515`）。重建后指针回 `(0,0)`、RNG 重播种（分发不变，仅测试不可复现）；`enabled` 构造时快照。
5. **滚动**：只有落点出主 frame 视口才触发滚动；触发后 Playwright 能滚内层容器。被内层 `overflow`/iframe 裁剪但几何仍在视口内 → 不滚 → `covered-by`，无重试。
6. **托管模式**：mouse/keyboard 路径一致；但 `connect_over_cdp` 强制 `noDefaultViewport`（`coreBundle.js:46781`）→ `page.viewport_size is None` → `ensure_in_viewport` 静默用 1280×720。这是 15 个平台同时踩的公共缺陷。
7. **最重要的一条不在工单内**：`stillOn` 用「移动前的 box」对比「移动后的 box」，容差 ±1px。hover 使布局/`transform` 变化 >1px 的目标必然 `point-drift` 且不重试——这是比 iframe/shadow 更高频的阻断源。
8. **不可坐标点击**：file input、`<option>`、`visibility:hidden` 的 JS-only 按钮、零尺寸/`display:contents`、`opacity:0` 透明层、`<area>`、原生浏览器 UI、closed shadow、拖拽。替代写法与代码证据见研究文件 §6。
9. **显式退化**：`>1000` 码点整段 `insert_text`（按码点非字素）、指针从 `(0,0)` 起步、US 布局、`\r` 走 `insert_text`、`HUMANIZE=0` 是语义切换而非纯计时切换。
10. 规格必须写死的 18 条限制已列在研究文件 §8，可直接搬运；仍需真机的 7 项列在 §9。
