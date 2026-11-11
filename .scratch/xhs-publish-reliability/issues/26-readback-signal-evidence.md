# 26 — 回读/越限信号真机取证

Status: resolved
Type: task
Blocked by: —
Assignee: wayfinder-session (opencode)

## Question

为 11 采用的「上游薄口径」补齐真机证据，并判断是否需要重开「定时设置结果校验」。需要取证：

1. **标题越限节点**：`div.title-container div.max_suffix` 是否真实存在；输入超限时出现时机、文案格式（是否 `当前/上限`）。
2. **正文越限节点**：`div.edit-container div.length-error` 是否真实存在；文案格式；话题锚点是否计入。
3. **定时开关未生效的可观测信号**：点击 `.post-time-wrapper .d-switch` 后若未真正开启（或日期被拒），页面留下什么结构/属性/文案信号；是否会导致按即时发布。
4. **定时时间输入框**：写入后 `input.value` 是否已提交（失焦/Enter/Tab 前后的差异），以及被拒时的表现。
5. **原创点击后的开关状态**：`_switch_is_on` 在确认弹窗关闭后是否稳定可读（本轮不读，用于判断未来是否值得补）。
6. **内容类型声明 / 封面的可观测回读信号**：入口文本是否变为已选标签、封面区域 `img.src` 是否变化等（本轮不读，留档）。

产出：`.scratch/xhs-publish-reliability/research/26-readback-signal-evidence.md`（含原始快照/探针 JSON），逐条标注「实机 / 未观察到 / 需进一步取证」。若第 3 条证明「静默立即发布」真实存在，在 26 的 Answer 中建议重开一票补「定时点后单次读」，并指出应挂在 11 的决议之后。

## Answer

### 总判定

六条全部拿到本机实机证据（详见 `research/26-readback-signal-evidence.md` 与 `research/raw/t26*`）。两条关键结论推翻了 11 里的假设：

1. **标题锚点是死的**：`div.title-container` 现网 0 个元素，`div.title-container div.max_suffix` 恒为 0。真实信号是 `.edit-container .suffix` 越限时**改类名为 `max_suffix`**（同一节点，不是新增节点），文案 `当前 / 上限`（`21 / 20`），且**输入事件后 306–344ms 才切换**——立即单次检查会漏判。正文锚点 `div.edit-container div.length-error` 则**有效**（1000 字 0 命中、1001 字 1 命中）。
2. **定时「不可观测」缺口比 11 写的小**：开关状态可读（`.d-switch-simulator` 的 `checked`/`unchecked` + 日期输入出现/消失，三次点击完全可逆）；日期被拒也不是全不可观测——受控组件在**失焦后静默回滚**到上一次合法值（默认 `now+1h`），无错误文案。当前流程不主动失焦、不回读，所以仍会按错误时间发布；一次 `blur()` + 一次 `input.value` 读即可发现。**未观察到「按即时发布」的路径**，因此没有触发「静默立即发布」这一条；但「按错误时间发布」真实存在，故仍新建 27 走决策。

逐条：① 标题越限 = 实机；② 正文越限 = 实机（阈值 1000，话题计入，按 `#name` 计 7，不含 `[话题]#`）；③ 开关信号 = 实机（失败样本未观察到）；④ 时间提交 = 实机（失焦回滚）；⑤ 原创点后状态 = 实机（弹窗关闭后 `checked` 稳定可读）；⑥ 声明文本回读 = 实机；封面 = 未观察到稳定 `img.src` 信号（图片页无封面编辑器；视频页 entry attached 但 invisible，Esc 关不掉弹窗）。

### 对 11 的修订（不推翻决议，只改锚点与等待）

- 标题：删 `div.title-container div.max_suffix` → 改 `.edit-container .max_suffix`（或 `.d-input-wrapper.c-input_max`）；判定「存在即失败」不变；**加 ≥350ms 等待/轮询**（与 11 已有的「单次 `Has`」语义兼容，只改时序）。
- 正文：`div.edit-container div.length-error` **保留原样**；错误文案读 `.editor-length-wrapper` 的 `当前\n/上限`。
- 已知缺口改写为：**定时开关可观测、日期被拒可在失焦后观测；本轮未实现**（是否实现 → 27）。
- 补充：越限时发布按钮 `submit-disabled` 仍为 `false`，平台不拦；正文计数逐字符、话题按 `#name` 计入（标题才是 UTF-16 加权）。

### 对 05 的补充

- 定时发布**复用同一个 `xhs-publish-btn`**：仅 `submit-text` 从 `发布` 变为 `定时发布`，其余属性不变（第 1 行「仅推断」→ 实机）。
- 开关状态读 `.d-switch-simulator` 的 class；日期输入默认 `now+1h`，关闭后整块 `.date-picker-container` 移除。

### 新建并接线

- **27 — 定时设置后的单次回读**（Type: grilling，Blocked by: 11, 26）：决定是否在 FIRE 前补「`blur()` + 单次读」。已同时把 27 加入 17 的 Blocked by。

### 流程约束（→ 10 / 17）

- 定时时间输入流程**禁止 Enter/Tab**：Tab 会把焦点交给 `xhs-publish-btn`，再按 Enter 会执行「暂存离开」并离开编辑器（本次两次复现）。失焦只能用 `blur()`。

## Comments

- 副作用：验证 Enter 行为时页面执行了「暂存离开」，账号里留下 1 条无标题图文草稿（图片为探针图，保存时间 19:06:55；18:54:29 的同因）。**未发布任何笔记**，请人工确认后删除。
