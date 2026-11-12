# 08 — 共享层三处前置缺陷：hover 漂移、托管视口、容器裁剪

Status: open
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

（待决议）
