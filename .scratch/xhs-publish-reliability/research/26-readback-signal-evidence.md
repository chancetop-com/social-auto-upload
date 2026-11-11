# 26 — 回读 / 越限信号真机取证（标题 · 正文 · 定时 · 原创 · 声明 · 封面）

- 取证时间：2026-11-11 18:53–19:07（本机，headless Chromium + patchright，同 22 的浏览器环境）
- 账号：`cookies/xiaohongshu_180.json`（页面右上角 `小红薯6AF26ACE`），**全程未点击发布按钮**
- 页面：`/publish/publish?from=homepage&target=image`（Q1–Q6），`...&target=video`（仅 Q6 封面）
- 脚本：
  - `research/probe_readback_signals.py`（第一轮，六问全量；Q2 判据与 Q4 操作有缺陷，结论以二/三/四轮为准）
  - `research/probe_readback_signals_b.py`（正文越限/话题计数、定时开关、原创、声明）
  - `research/probe_readback_signals_c.py`（标题时序、日期真实键入、封面留档）
  - `research/probe_date_typing.py`（日期输入逐动作状态、Enter 行为）
  - `research/probe_publish_btn_text.py`（定时前后发布按钮自述属性）
- 原始数据（本地，勿入 git）：`research/raw/t26*.json|png|log`、`t26b-report.json`、`t26c-report.json`、`t26d-report.json`、`t26e-report.json`
- 置信度口径：**实机** = 本次实际观察到；**仅推断** = 无本次证据；**需进一步取证** = 需要发布级或另一页面才能确认

> 副作用披露：`probe_date_typing.py` 在验证 Enter 行为时，焦点先被 Tab 移到 `xhs-publish-btn`，Enter 触发了**暂存离开**
> （页面提示「保存成功」并跳到「草稿箱」）。账号里因此留下 1 条无标题图文草稿（保存时间 19:06:55，图片为探针图）。
> **没有发布任何笔记**。第一轮 18:54:29 的草稿来自同一原因。请人工确认后删除。

---

## 0. 结论速览

| # | 问题 | 结论 | 置信度 |
|---|---|---|---|
| 1 | 标题越限节点 | `div.title-container` **不存在**；真正信号是 `.input > .suffix` **类名换成 `max_suffix`**，文案 `当前 / 上限`（如 `21 / 20`）。输入事件后 **约 306–344ms** 才出现，立即检查会漏判；失焦后仍保留。 | 实机 |
| 2 | 正文越限节点 | `div.edit-container div.length-error` **真实存在**且可直接用：1000 字 0 命中、1001 字 1 命中；命中节点是 `.editor-length-wrapper` 加 `length-error` 类，文案 `1001\n/1000`（计数变红）。话题**计入**，1 个话题按键面 `#name` 计（实测 7），不含 `[话题]#` 后缀。 | 实机 |
| 3 | 定时开关信号 | 开关状态**可读且可逆**：`.d-switch-simulator` 由 `unchecked` ↔ `checked`，日期输入随开/关出现/消失；发布按钮同一个 `xhs-publish-btn`，仅 `submit-text` 从 `发布` 变 `定时发布`。**没有观察到「点了没开」的失败样本**；若失败，simulator 保持 unchecked、无日期输入。 | 实机（失败样本=未观察到） |
| 4 | 定时时间提交 | 输入框是**受控组件**：合法值 Tab/失焦后保留；**过去日期与不可解析串在失焦后静默回滚**到上一次合法值（无任何错误文案/类）。因此「日期被拒」不是不可观测，而是**只有失焦后才可观测**。 | 实机 |
| 5 | 原创点后状态 | 确认弹窗关闭后 `.original-wrapper .d-switch-simulator` 稳定为 `checked`（900ms / 1600ms / 失焦后三次一致），弹窗计数 0。**稳定可读**。 | 实机 |
| 6 | 声明 / 封面 | 声明入口文本会从 `添加内容类型声明` 变为所选标签（`虚构演绎，仅供娱乐`），可作回读信号。封面：图片页无 `.cover-edit-entry`；视频页 entry **attached 但 invisible**，JS 点击可开 `.main-cover-editor-modal`，`img.src` 无单一稳定「当前封面」节点，Esc 也关不掉。 | 实机（封面=未观察到稳定信号） |

**对 11 的直接修订**：标题检查的锚点 `div.title-container div.max_suffix` **是死选择器**（现网 0 命中，`div.title-container` 本身为 0）；正文锚点 `div.edit-container div.length-error` **有效**，可原样保留。标题检查还必须加 **≥350ms 的等待/轮询**，否则单次检查会漏。

**对「定时设置结果校验」的判断**：不存在「开关没开却继续」的静默路径（状态可读）；真实缺口是**日期回滚**——写入非法时间时页面不报错，失焦后回退到上次合法值（默认 `now+1h`）。当前 11 的流程写完不回读、也不主动失焦，因此会**按错误时间（默认值）发布**；这是可检测的，代价是「主动 blur 一次 + 读一次 `input.value`」。→ 建议重开一票（已建 **27**）。

---

## 1. 标题越限（Q1）

### 1.1 结构事实

| 查询 | 计数 | 说明 |
|---|---|---|
| `div.title-container` | **0** | 整页不存在（HTML 里只有同名 CSS 规则，没有元素） |
| `div.title-container div.max_suffix` | **0** | 11 的锚点恒为 0，**死选择器** |
| `div.edit-container .input > .suffix` | 1 | 标题计数器容器（聚焦时出现） |
| `.max_suffix`（越限后） | 1 | **同一节点** `suffix` → `max_suffix` 类名切换 |
| `.d-input-wrapper.c-input_max` | 1 | 越限时父容器加 `c-input_max` |

越限后的实际 DOM（`raw/t26-q1-title-overflow-cjk.json`）：

```html
<div class="d-input-wrapper d-inline-block c-input_inner c-input_max">
  <div class="d-input ...">
    <input class="d-text" type="text" placeholder="填写标题会有更多赞哦" value="测…（21 字）">
  </div>
  <div class="max_suffix"><div class="count-tip">21 / 20</div></div>
</div>
```

### 1.2 出现时机

- 输入 21 个中文后，MutationObserver 记录到 `suffix`→`max_suffix` 的类名切换发生在 input 事件之后 **306ms**（第二轮样本）与 **344ms**（第一轮样本）。
- 不是插入新节点，而是**同一个 `.suffix` 节点改类名**；因此只监听 `childList` 的 DOM 差异会漏掉。
- 失焦后 `max_suffix` **仍存在**（`count=1`），只有清空到 ≤20 才恢复为 `suffix`。

### 1.3 文案格式与口径

| 输入 | 计数器文本 | 说明 |
|---|---|---|
| 空（聚焦） | `0 / 20` | 常规态 `.suffix > .count-tip` |
| 21 个中文 | `21 / 20` | 越限态 `.max_suffix > .count-tip` |
| 41 个 ASCII `a` | `21 / 20` | 41×0.5=20.5 → 21，**与 11 的 UTF-16 加权公式一致** |

`input` 元素**没有 `maxlength` 属性**（不会截断，只会报计数）。

### 1.4 对 11 的修订

- 锚点改为 `.edit-container .max_suffix`（或 `.d-input-wrapper.c-input_max`）；**不要再用 `div.title-container`**。
- 检查时机：`fill` 后等待/轮询到稳定（建议 500ms 上限或 50ms 轮询到 `.max_suffix` 出现/超时），再判定「存在即失败」。
- 错误消息可直接读 `.max_suffix .count-tip` 的 `a / b`。

---

## 2. 正文越限（Q2）

### 2.1 节点真实存在

| 状态 | 计数器 | `div.length-error` | `.editor-length-wrapper` 类 | `.max-length` 颜色 |
|---|---|---|---|---|
| 0 字 | `0\n/1000` | 0 | `editor-length-wrapper` | `rgb(192, 196, 204)` |
| 1000 字 | `1000\n/1000` | **0** | `editor-length-wrapper` | 灰 |
| 1001 字 | `1001\n/1000` | **1** | `editor-length-wrapper length-error` | `rgb(255, 82, 93)` |
| 1040 字 | `1040\n/1000` | 1 | `editor-length-wrapper length-error` | 红 |

- `div.edit-container div.length-error` **命中 1**：11 的锚点可以直接用，无需改。
- 命中节点就是常驻的 `.editor-length-wrapper`（在 `.bottom-wrapper` 内），**越限只是加类**；不是新增节点。
- 文案是 `当前\n/上限`（换行分隔），不是 `当前 / 上限` 的单行格式。
- 平台**不会**因为越限禁用发布按钮：`xhs-publish-btn` 的 `submit-disabled` 在 1040 字时仍为 `"false"`。→ 我们点击前的前置检查是唯一闸门。
- 计数器本身（`.editor-length-wrapper` 首行数字）也可读，可直接用于错误文案。

### 2.2 话题是否计入

| 操作 | 计数器 |
|---|---|
| 空正文 | 0 |
| 插入 1 个话题，编辑区锚点 `#旅行pov[话题]#`（innerText 11 字符） | **7** |
| 再输入 1 个中文字 | 8 |

- 话题**计入**，且按 `#name`（`#` + `旅行pov` = 7）计，**不把 `[话题]#` 后缀计入**。
- 计数是**逐字符**（中文 1 字 = 1），不是标题那种 UTF-16 加权；因此正文超限无法用 `innerText.length` 简单等价（锚点 innerText 含 `[话题]#`，会比计数器多 4 字/个话题）。
- 11 的正文检查在「正文 + 话题全部输入完成后」执行是安全的；本次观察到计数器在插入后 ≤300ms 内即为最终值（每 80 字一批、批间 300ms，计数器逐批准确）。

### 2.3 失败时点

- 1000 → 无错误；1001 → 有错误。**边界 = 1000**（与上游/页面 `max-length=/1000` 一致）。
- 从 1040 退回 1000（按 40 次 Backspace）后错误类即被移除；再敲 1 字立刻回来 → 判据是实时的类名，不是一次性。

---

## 3. 定时开关状态（Q3）

| 时点 | `.d-switch-simulator` | 日期输入 | `xhs-publish-btn@submit-text` |
|---|---|---|---|
| 开 | `unchecked --color-bg-fill` | 0（`.date-picker-container` 不存在） | `发布` |
| 点击开关 700ms | `hover checked --color-bg-primary` | 1，值 `2026-11-11 20:07`（默认 `now+1h`） | `定时发布` |
| 再点（关） | `hover unchecked --color-bg-fill` | 0 | （未采样，按同组件推断为 `发布`） |
| 第三次（开） | `hover checked --color-bg-primary` | 1，保留原值 | `定时发布` |

- 三次点击状态**完全可逆且可读**；`aria-checked` / `data-checked` 均为 `null`（只有 class 信号）。
- 「未真正开启」的可观测形态：simulator 保持 `unchecked`，且 `.date-picker-container` / `.date-picker-container input` 不出现。
- **没有观察到**「simulator=checked 但面板未展开」或「点击无反应」的样本；未失败的点击三次都成功。
- 定时发布确实复用同一个 `xhs-publish-btn`（05 第 1 行「仅推断」→ 现为实机）：同一元素，仅 `submit-text` 属性变化，**零文本可判定**；`is-publish`/`submit-disabled` 等属性不变。
- 「是否会导致按即时发布」：未观察到此路径。日期被拒时回滚目标是上一次合法值/默认值（见 §4），不是即时；但未发布，**发布级后果需进一步取证**。

> 注意：Q3 的 `innerText` 采样有一次返回空（组件瞬时重渲染），后续采样正常；状态判定应读属性/子节点，不依赖一次 `innerText`。

---

## 4. 定时时间输入（Q4）

用**真实键盘**（`Control+A` + `insert_text`）写入，记录每个动作后的 `input.value`（`raw/t26d-report.json`）：

| 动作 | 写入值 | `input.value` | 说明 |
|---|---|---|---|
| 开关打开（默认） | — | `2026-11-11 20:07` | 默认 = 打开时刻 + 1h |
| 键入 | `2026-11-14 10:00` | `2026-11-14 10:00` | 已进入 DOM，但仍是未提交态 |
| Tab | — | `2026-11-14 10:00` | 合法 → 保留；焦点移到 `xhs-publish-btn` |
| JS blur | — | `2026-11-14 10:00` | 保留 |
| 键入过去日期 | `2026-01-01 10:00` | `2026-01-01 10:00` | 未失焦时**看不出被拒** |
| Tab（=失焦） | — | **`2026-11-14 10:00`** | **静默回滚**，无错误文案/类 |
| 键入 `abc` | `abc` | `abc` | 同上 |
| JS blur | — | **`2026-11-14 10:00`** | **静默回滚** |

- 组件内部保留「上一次合法值」；非法输入只停留在 DOM，失焦时被模型覆盖回去。
- 全流程**没有**任何可见的错误节点/文案（`/日期|时间|过去|无效|错误|不能/` 扫描 = 0）。
- 因此「日期被拒」的可观测信号只有一个：**失焦后的 `input.value` ≠ 期望串**。
- 当前 11 的实现：`fill` → `sleep(1)` → 继续（无 blur、无回读）。失焦发生在后来点击发布时；此时若被拒，页面已回退到默认 `now+1h`，仍会按定时提交。

### 4.1 Enter / Tab 的行为（重要副作用）

- Tab 从日期输入把焦点交给 `xhs-publish-btn`。
- 在焦点位于该按钮时按 **Enter**，页面执行「**暂存离开**」：提示「保存成功」，跳到上传页并弹出「草稿箱」（本次两次复现：18:54、19:06）。
- 结论：定时时间输入流程中**不要按 Enter/Tab**；`fill` 后保持焦点不动即可（现有代码正是如此）。失焦应显式用 `blur()`，不要靠 Tab（会把焦点送到发布按钮）。

---

## 5. 原创点后状态（Q5）

| 时点 | `.original-wrapper .d-switch-simulator` | 弹窗 |
|---|---|---|
| 点前 | `unchecked --color-bg-fill` | — |
| 点击开关 | （弹窗出现） | `.d-modal.creator-modal-style`，1 个按钮「声明原创」，2 个 `.d-checkbox`/checkbox |
| 勾选 + 点「声明原创」后 900ms | `checked --color-bg-primary` | 0 |
| 1600ms | `checked --color-bg-primary` | 0 |
| 点击正文失焦后 | `checked --color-bg-primary` | 0 |

- `_switch_is_on`（class 含 `checked`）在弹窗关闭后**稳定可读**，无 `aria-checked` 可用。
- 本轮 11 的「点后不读」决定不受影响；若未来需要，补一次读回的代价极低、信号可靠。

---

## 6. 内容类型声明 / 封面（Q6）

### 6.1 内容类型声明（实机）

- 入口：`.publish-container .d-select` 的第 1 项，未选时文本 `添加内容类型声明`（共 4 个 `.d-select`：声明 / 地点 / 群聊 / 引用等）。
- 菜单：`.declaration-drop-down`，选项文本在 `.d-option-content`（`虚构演绎，仅供娱乐` 等）。
- 选择后：**入口自身的 `innerText` 变为所选标签**（`虚构演绎，仅供娱乐`），`class` 不变；无独立「已选」图标被观察到。
- → 可回读信号：读该 `.d-select` 的 `innerText` 与期望标签比较（本轮不实现，留档）。
- 旧代码的 `#publish-container` 仍是 0 命中（05 已记录），回读时不要用它做作用域。

### 6.2 封面（实机，留档）

- **图片页**：`.cover-edit-entry` / `.cover-edit-stack` 均为 0（图文以第 1 张图为封面，无封面编辑器）。
- **视频页**：`.cover-edit-stack` 与 `.cover-edit-entry` **attached 但 invisible**（面板折叠状态），文本 `编辑封面`；JS 点击可直接打开弹窗。
- 弹窗：`div.d-modal.d-modal-no-footer.cover-modal.creator-modal-style.main-cover-editor-modal`，文本含 `设置封面 / AI修改 / 裁剪 / 模版 / 贴纸 / 文字 / 滤镜 / 生成封面 / 编辑 / 预览 / 上传 / 获取封面建议 / 完成`。
- `img.src`：弹窗内有多张图（关闭图标/加载图/示例封面/AI 推荐），**没有单一「当前封面」稳定节点**；`coverDetectTag` 为 data-URI 检测图。→ **未观察到可用的封面回读信号**（11 的「封面零回读」维持）。
- `Escape` **不能**关闭该弹窗（按后 modal 计数仍为 1），需点 ×/完成。

---

## 7. 对其它票的具体输入

### 7.1 → 11（修订锚点，不推翻决议）

1. 标题：`div.title-container div.max_suffix` **删除**，改 `.edit-container .max_suffix`（或 `.d-input-wrapper.c-input_max`）；判定「存在即失败」不变。
2. 标题检查需**等 350ms 左右**（或轮询到出现/超时）；上游的 `AfterType` 停顿正是为此。
3. 正文：`div.edit-container div.length-error` **原样保留**（实测 1000/1001 边界准确）；文案取 `.editor-length-wrapper` 的 `当前\n/上限`。
4. 已知缺口「定时设置结果不可观测」需要改写：**开关可观测、日期被拒也可观测（失焦后）**。是否补「失焦 + 单次读」→ 27。

### 7.2 → 05（选择器基线，补充实机）

- 第 1 行「定时发布仅推断」→ **实机**：同一个 `xhs-publish-btn`，仅 `submit-text="定时发布"`；`is-publish`/`submit-disabled` 不变。
- 第 8/9 行：`.post-time-wrapper .d-switch` 与 `.d-datepicker-input-filter input.d-text` 均实机命中；日期输入默认值 `now+1h`，开关关闭后整块 `.date-picker-container` 移除。
- 状态信号优先读 `.d-switch-simulator` 的 class（`checked`/`unchecked`），**无 aria/data 属性**。

### 7.3 → 10 / 17（人化与流程）

- 定时时间流程**禁止 Enter/Tab**：Tab 会把焦点交给 `xhs-publish-btn`，Enter 会触发「暂存离开」并离开编辑器（本次两次复现）。
- 这是行为约束，不是选择器问题；17 的流程规格应写明。

### 7.4 → 27（新建）

新建 `27-schedule-readback.md`：决定是否补「定时开关 + 时间」的失焦后单次读回；`Blocked by: 11, 26`。

---

## 8. 未观察到 / 需进一步取证

- **开关点击失败的样本**：未观察到；只证明了失败时会是什么形态（unchecked + 无日期输入）。
- **日期被拒时的发布级后果**：未发布，无法证明服务端按回滚后的默认时间受理；只能证明页面把值改回默认值。
- **定时提交的真实时刻**：未发布，未核对服务端回执/笔记管理页。
- **正文计数在「发布瞬间」是否会被服务端再次校验**：未发布，未观察到。
- **封面的 `img.src` 回读**：未观察到单一稳定节点。

## 9. 原始快照索引

| 文件 | 内容 |
|---|---|
| `raw/t26-report.json` | 第一轮全量（Q1 有效；Q2 判据误报、Q4 因 Enter 跳页，均以二/三/四轮为准） |
| `raw/t26-q1-title-overflow-cjk.json` / `.png` | 标题 21 中文越限，`max_suffix` HTML |
| `raw/t26-q1-title-overflow-ascii.json` / `.png` | 标题 41 ASCII → `21 / 20` |
| `raw/t26-q2-body-overflow.png`、`t26b-a-body-1001.png` | 正文越限（红计数） |
| `raw/t26b-report.json` | 正文边界/话题计数、定时开关、原创、声明（A/B/C 三轮） |
| `raw/t26c-report.json` | 标题时序 306ms、日期键入、封面弹窗 |
| `raw/t26d-report.json` | 日期逐动作状态 + Enter 触发暂存离开 |
| `raw/t26e-report.json` | 发布按钮 `submit-text` 发布 ↔ 定时发布 |
