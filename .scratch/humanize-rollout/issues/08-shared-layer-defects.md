# 08 — 共享层三处前置缺陷：hover 漂移、托管视口、容器裁剪

Status: resolved
Type: grilling
Blocked by: 02

## Question

02 在 `Humanizer` 依赖的两个 dom 函数里查出三处缺陷。它们不是某个平台的问题，而是**15 个平台一起踩**。要定的是：修、绕过，还是接受。

1. **hover 尺寸漂移（02 判定的最大阻断项）**
   `stillOn` 比较的是「移动前」的 box 与「移动后」的 box，容差 ±1 px（`humanize.py:258`、`:285-287`）。但鼠标移到目标上本身就会触发 `:hover`，任何 hover 后尺寸/位置变化 >1 px 的目标都会 `point-drift`，且**不重试**。
   选项：(a) 放宽容差；(b) 移动后重新取 box 再比，只判「目标点仍落在自身内」；(c) 失败进白名单；(d) 给一次重试。
   注意：XHS 没暴露这个问题，说明它的目标 hover 不变形——这是「只在小红书验证过」的直接代价。

2. **托管模式视口缺失**
   `connect_over_cdp` 强制 `noDefaultViewport`（patchright `coreBundle.js:46781`），`page.viewport_size is None`，于是 `ensure_in_viewport` 静默用 1280×720 兜底。真实窗口更小或更大时，视口判断全错：目标被误判「已在视口」→ 不滚动 → `covered-by:unknown`。
   现有测试用本地模式的 1920×1080 / 1280×2000 视口，**恰好把这个缺陷藏住了**。
   选项：(a) `ensure_in_viewport` 改读真实内尺寸（`evaluate` 一次）；(b) 托管会话里显式注入 viewport；(c) 接受并记为已知限制。

3. **裁剪不在滚动决策里**
   `needs_scroll` 只比主 frame 窗口视口，不看内层 `overflow` 容器与 iframe 视口。`bounding_box()` 返回的是**未裁剪**几何，所以被容器裁掉的目标看起来「在视口内」，不滚动，然后命中失败。暴露面：抖音音乐侧滑面板、antd / Facebook 日历、知乎下拉、TikTok 上传 iframe。

4. **边界问题：这属于「改 dom.py」**
   charter 写的是「只搬 humanize，不搬 dom 的其余能力」。但修这三处必须改 `ensure_in_viewport` / `check`。纳入本 effort 会让 XHS 同时受益（同一个函数），但也越过了 charter 的字面边界。
   选项：(a) 纳入，作为 humanize 的前置修复；(b) 不纳入，规格只写「已知限制 + 白名单」；(c) 单独起一个 dom 修复 effort，本规格依赖它。

产出：三处各自「修 / 绕过 / 接受」的决定、对应的 spec 措辞、以及是否修改 charter 的结论。

## Answer

决议 2026-11-12。等级标注沿用 map 的约定：`[code]` / `[doc]` / `[inferred]` / `[needs-live]`。

### 0. 边界结论：纳入，charter 原文不改

三处缺陷全部落在**已决定携带**的 `utils/dom.py::check` / `ensure_in_viewport` 与 `utils/humanize.py::Humanizer.click` 内部，没有一处需要 dom 的其它能力 `[code]`：

- `humanize.py:285-287` 的 `point-drift` 在 `click` 内，`_same_box` 是私有小工具（`:120-128`）；
- `dom.py:289-300` 的 1280×720 兜底与 `needs_scroll` 算术同在 `ensure_in_viewport` 内。

charter 第 1 条**不动**。规格补一句边界澄清：「携带 `check` 与 `ensure_in_viewport` 两个函数＝携带它们正确工作；不引入 dom 的其它能力。」

不选 (b)（只记已知限制 + 白名单）：与 03「真残余白名单 0 条」直接冲突，没有地方安放这些例外。不选 (c)（单开 dom effort）：会给 06 制造一个仓库内不存在、且无法保证先落地的外部依赖。

### 1. hover 尺寸漂移 —— 接受，`click` 一行不改

- **不加重试、不放宽容差（1px 保持）、不改事件序列**，与 XHS [34 — 人类化交互层](../../xhs-publish-reliability/issues/34-humanized-interaction.md) 的「内部零重试」逐字对齐。`point-drift` 仍是「确定未派发」的硬失败。
- 出现 `point-drift` 的平台，用**既有原语**在调用点先 `Humanizer.hover()` 再 `click`（XHS `.cover-edit-entry` 的已验证模式，`uploader/xiaohongshu_uploader/main.py`）`[code]`。
- 规格职责：01 的交互点清单加一列「是否需前置 `hover()`」，默认「否」；真机暴露才在该调用点补，并记进 `.scratch/humanize-rollout/acceptance.md`。
- 已知限制登记（不改判）：hover 触发浮层遮挡会以 `covered-by:*` 失败，不重试、不进白名单。
- 否决理由：放宽（a）让 12px 级图标目标点到界外且使 `stillOn` 名存实亡；只判「落点仍在自身内」（b）不成立——`check` 会**重新取 box** 再在新 box 的 ratio 点做 `elementFromPoint`（`dom.py:392-413`），它验证的不是鼠标所在坐标，元素飘走时仍可能报 self，然后 `mouse.down` 打在旧坐标上 `[code]`；两段式（每次点击先 hover 再量）能零重试但让 371 个交互点全付一次 `pointer_settle`，用全平台固定预算买局部问题。
- 残余 `[needs-live]`：哪些目标 hover 后尺寸会变、hover 是否触发遮挡，只能真机看；处置纪律已定，分布不是决策。

### 2. 托管视口缺失 —— 谓词化，尺寸彻底退出判定（B2）

- `ensure_in_viewport` 不再读 `page.viewport_size`，改为在**元素自己的 frame** 内求谓词「该比例落点是否几何可见」；`DEFAULT_VIEWPORT_WIDTH/HEIGHT` 与 `page.viewport_size is None → 1280×720` 的静默兜底一并**删除**。`[code]`（`dom.py:290-300`）
- 求值异常 → 保守判「需滚动」，不再猜视口。
- 依据：托管 Profile 拥有尺寸（[14](../../xhs-publish-reliability/issues/14-managed-defaults.md)：`viewport` 属「托管下本来就该丢」的默认项），但**不可观测**；`connect_over_cdp` 的 `noDefaultViewport` 使 `viewport_size` 为 `None`。而 `elementFromPoint` 只认**真实布局视口**，谁选的尺寸无关 `[doc]`。
- 机制可行性证据：`locator.evaluate` 的 JS 在元素自身 frame 内执行，`dom.py:175-191` 的 `_HIT_TEST_JS` 已在每次 `check` 里用同一套 `getBoundingClientRect` + `document.elementFromPoint` 工作，跨 iframe 由 02 的真机结论背书 `[code]` + `[needs-live]`。
- 否决：注入视口（b）越身份层且 `noDefaultViewport` 下不生效；接受（c）让 15 个平台托管运行永久带着错误判定；「hit-test 失败再滚一次」把重试塞回 `click`，与第 1 条冲突，且把「被浮层遮挡」与「在视口外」混成同一信号。
- 测试：`tests/test_xhs_dom.py:756-790` 三条视口算术用例改写为谓词用例；新增 `viewport_size=None` 仍正确决策的反例（现有 1920×1080 / 1280×2000 用例恰好把缺陷藏住了）。托管路径**只做离线验证**，规格标「托管未真机验证」。

### 3. 容器裁剪 —— 修，同一谓词两级应用

- **同一 frame**：视口内 + 逐层 `overflow != visible` 祖先 rect 包含判断（被祖先裁掉时 `elementFromPoint` 不返回 `null`，只靠第 2 条的谓词判不出来）`[code]`。
- **子 frame**：落点投影到主 frame 后，在主 frame 问同一谓词（只对 iframe 目标多一次往返）。frame 内谓词看不见父视口裁剪。
- `false` → `scroll_into_view_if_needed`（Playwright 负责滚祖先容器与 frame 链）；`true` → 不动。
- 覆盖 exposure：抖音音乐侧滑面板、antd / Facebook 日历、知乎下拉、TikTok 上传 iframe。`hover()` 与 `click()` 共用该谓词（`hover` 现也调 `ensure_in_viewport`，缺陷同源）。
- **切分原则（规格必须写）**：可见性是几何问题，可以修（滚）；可点性是命中问题，不修（不重试、不猜）。overlay 仍由 `check` 报 `covered-by:*` 硬失败。这条原则让第 1 条的「不重试」自然成立。
- 否决「绕」：四处都是通用容器行为，不是平台特例；逐点补滚动会把同一段逻辑抄进 4 个调用点，且 03 表明白名单没有余量。否决「接受」：这是「目标在页面上可见却点不到」的硬失败，05 的每平台验收都过不去。

### 4. 两个按默认处理的点

1. **不新增失败 reason**：谓词修正后 `elementFromPoint` 返回 `null` 应已罕见；`covered-by:unknown` 字符串保留，新增诊断只进 DEBUG 日志。理由：该文案是 XHS [13](../../xhs-publish-reliability/issues/13-failure-semantics-parity.md) 契约的派生面，不归本 effort 改。
2. **不缓存可见性结果**：每次点击现问；窗口尺寸与滚动位置随时变，缓存只会把 bug 藏起来。

### 5. 规格要素（06 照抄清单）

1. 边界澄清句（§0），charter 不改。
2. 可见性谓词定义：几何可见 = 视口内 ∧ 未被同 frame 祖先裁剪 ∧ 未被父 frame 裁剪；`false` → 滚；求值异常 → 保守滚；无尺寸常量、无缓存。
3. `point-drift` 处置纪律：默认不 hover；真机出现即在调用点前置 `hover()`，记入 `acceptance.md`；不重试、不放宽容差。
4. 01 清单新增「是否需前置 `hover()`」列（默认否）。
5. 测试要求：谓词单测（本地 / 无 `viewport_size` / 祖先裁剪 / 跨 frame）+ 改写现有三条算术用例；托管只离线验证。
6. 已知限制：hover 触发遮挡 → `covered-by:*` 硬失败；托管路径未真机验证。

### 6. 对路线图的影响

08 resolved 后，**06 — 汇总实施规格** 的唯一阻塞（08）解除，成为下一个 frontier。新增真机观察项（hover 变形分布、哪些裁剪容器滚得动、父 frame 裁剪实例）并入 05 的 `acceptance.md`，不新开 ticket。`[needs-live]`
