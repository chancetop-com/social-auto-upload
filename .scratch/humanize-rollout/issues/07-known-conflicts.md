# 07 — 已知会坏的站点：例外规则与改造顺序

Status: resolved
Type: grilling
Blocked by: 01, 02

## Question

01 的清单里有 45 处「待定」，其中一部分不是 `force=True` 问题（那是 03），而是**这个站点当前的写法本身就与人类化冲突**。要定的是例外规则——哪些可以豁免、豁免长什么样、改造顺序怎么排。

已知冲突出现在四处：

1. **微博发布按钮**（`weibo_uploader/main.py:912`，另见 `:861` / `:941`）——按钮中心被一个空的 `div` 覆盖，注释明确写着当前只有 `el.click()` 能点成功。这与 charter 的「无 `el.click()`」禁令直接冲突。选项：找出可点的偏移点（按钮左/右缘）？允许这一处保留 `el.click()`？还是接受该平台本轮不做？
2. **YouTube `_fill_editable`**（`youtube_uploader/main.py:237-253`）——docstring 明写「不要逐字输入」：`#` 会触发自动补全浮层并卡住流程。这是仓库里唯一一处**既有设计主动拒绝人类化**的地方。选项：整段保持批量 `insert_text`？只对人类化非 `#` 文本？还是改写话题输入路径后再人类化？
3. **搜索型输入**（如百家号合集搜索框 `:698`、抖音地点 `:490`）——逐字输入会逐字触发联想请求与列表刷新，可能变慢或错选。选项：豁免（保持 `fill`）？逐字但每字符后不等待？改成「输入完整词再等一次结果」？
4. **抖音 `_native_click`**（`douyin_uploader/main.py:91-130`，8 个调用点）——手写坐标点击 + `elementFromPoint` 合成指针重放。与 `Humanizer.click` 集成时必须**删掉**它，否则一次点击会派发两次。这是删除项还是改造项？

另外三个全局问题：

5. **裸 locator**：`check(...,"interactive")` 要求 `count()==1`，但现网大量 `get_by_role(...)` 没加 `.first`。规格要统一要求「先收窄到唯一元素」吗？还是让 `Humanizer.click` 内部 `count()` 校验失败即报错（当前行为）？
6. **豁免的记录形式**：四处豁免分别写在代码注释、平台常量表、还是 `docs/` 的一张表里？是否需要一个静态门把豁免清单锁住？
7. **顺序**：先做没有冲突的平台、把冲突平台留到最后，还是先攻冲突平台（因为它们最需要验证）？

产出：每处冲突的处置决定 + 豁免记录格式 + 改造顺序。

## Answer

### 0. 总判据

四处冲突全部按**「先改点、再判是否原生路径、最后才是真不可能」**过了一遍（03 的顺序），结论是：**没有一处需要保留 `el.click()` 或新增豁免**。07 的产出因此不是豁免清单，而是四条具体改法 + 三条全局口径 + 顺序。

### 1. 微博发布按钮：比例落点，零 `el.click`

`[code]` `:912` 的覆盖问题不等于「人类化不可能」：

- `Humanizer.click` 接受 `point=(比例)`，落点在锚点 ±`min(宽/高×15%, 8px)` 内抖动（`utils/humanize.py:332-356`）。
- XHS 已有同型先例：`XHS_PUBLISH_BUTTON_POINT = (0.65, 0.5)`（`uploader/xiaohongshu_uploader/main.py:202`），注释写明「`(0.65, 0.5)` 是发布按钮」。
- `covered-by` / `point-drift` 都在 `mouse.down` **之前**抛出（`utils/humanize.py:285-290`），确定未派发，**可以安全重试一次**。

决定：

- `:912` → `await humanizer.click(publish_btn, point=(0.65, 0.5))`；若失败原因是 `covered-by:*` 或 `point-drift`（未派发），换 `(0.35, 0.5)` 再试一次；仍失败按「页面问题」抛 `ElementUnusableError`，**不退回 JS 点击、不加 force**。
- `:941` 对话框确认（确定/确认/继续/仍然发布/发布）**无任何遮挡证据**，直接 `humanizer.click`。
- `:861` 新建合集按 03 已定：改点行内文字 `span`，本票不重复裁决。
- 微博不留任何 `el.click()`；charter 的禁令在该平台**零例外**。

`[needs-live]`：覆盖按钮中心的空 `div` 实际几何（是否只盖中心、`0.65` 与 `0.35` 是否有一个可命中）本机无法验证。

### 2. YouTube `_fill_editable`：对齐 XHS，逐字 + 主动点选 `#` 候选

按 XHS 的同构做法，而不是「批量灌入躲浮层」：

- XHS 正文/标题逐字 `type_text`；话题也是逐字 `type_text("#" + tag)`，再由 `_insert_topic` 按 `name` **全等**点选候选项，候选失败降级纯文本（`uploader/xiaohongshu_uploader/main.py:2038`、`:2064`、`:2061`）。
- YouTube 现状只是 `_dismiss_autocomplete` 关浮层，没有点选段；本次补上这一段。

决定：

1. 清空沿用 XHS 形态：`humanizer.press("Control+A")` → `humanizer.press("Delete")`，不再用 `fill`。
2. 标题/简介**全部** `humanizer.type_text` 逐字（含 `#` 字符本身）。
3. 每写完一个 `#tag` 段：等 `tp-yt-iron-dropdown` 候选出现（有界、受 `PublishTimeoutBudget` clamp），在 `ytcp-hashtag-autocomplete`（或等价容器）内按**文本全等**匹配候选项 → `humanizer.click`。
4. 匹配不到：保留已输入的纯文本，调 `_dismiss_autocomplete(page)` 收尾，继续流程（与 XHS 话题降级同语义：增强项失败不中止发布）。
5. `_fill_editable` 的 docstring 改写：原文「不要逐字输入」的结论作废，改为记录新路径与降级条件。
6. 多个 `#tag` 逐个处理，不整段批量插入。

`[needs-live]`：`tp-yt-iron-dropdown` 的候选结构、条目是否为可坐标点击的真实元素、全等匹配是否可行。若真机证明候选不可点，**回退到「整段批量 + 关闭浮层」的字段级豁免**需另开决策，不得现场加 force/JS 点击。

### 3. 搜索型 / 过滤型输入：同 XHS 口径，逐字 + 候选全等，不设豁免

`[code]` XHS 两处样本：

- 位置（`:1891-1939`）：`humanizer.click` 展开 → `humanizer.type_text(location)` → 有界等下拉（失败只 warning）→ XPath **`text()="{location}"` 全等** → `humanizer.click`。
- 拍摄地点（`:2524-2544`）：`focus()` → `type_text` → 候选项先精确 `has_text` 收窄，`.first` 只作降级。

决定：

- **百家号合集**（`uploader/baijiahao_uploader/main.py:696-704`）：`search_input.fill(...)` → `humanizer.type_text(...)`；固定 `wait_for_timeout(1500)` 换成有界 `wait_for` 候选容器（受预算 clamp）；候选项由 `.first` 改为按合集名**精确匹配**，`.first` 只在匹配失败时作降级。
- **抖音地点**（`uploader/douyin_uploader/main.py:487-492`）：`keyboard.type` → `humanizer.type_text`；`keyboard.press("Backspace")` → `humanizer.press("Backspace")`；`wait_for_selector` 保留；选项选择改精确匹配。
- 两个字段都是增强项：候选选不到时仍按现有策略跳过，不中止发布。
- **不设「过滤型输入保持原生」的车规**——逐字不会增加错选风险，错选风险来自 `.first` 的包含匹配，已由精确匹配消除。

`[needs-live]`：百家号 `.cheetah-select` 候选的实际文本形态（是否带前后缀，影响全等判定）。

### 4. 抖音 `_native_click`：删除（含合成事件重放）

`[code]` 事实：

- 8 个调用点全部是**普通控件**（声明弹窗、合集下拉、封面入口/完成/二次确认），没有一处是 `uc_verification_component`；验证码路径在 `:846/:854` 用 `force=True`，03 已判「原生路径、保持不动」。
- `_native_click` 先 `page.mouse.move` + `page.mouse.click`，再在 `evaluate` 里补发一整套 pointer/mouse 合成事件——**真实点击之后再注入一次**，即重复派发。
- `Humanizer.click` 本身就是真实指针移动 + `mouse.down/hold/up`；可靠性由现场已有的「点后校验弹窗/弹层状态 → 重试 / 降级 / Esc」循环承担（`:919-960`、`:1012-1050`）。

决定：

1. **删除 `_native_click` 整个函数**（含合成事件段），不做轻微包装。
2. 8 处调用点（`:600`、`:622`、`:636`、`:809`、`:826`、`:949`、`:1028`、`:1038`）改 `humanizer.click`；原有的 `try/except` 兜底结构保留，兜底动作从「强点击」改为「按既有循环重试 / 降级跳过」。
3. 保留全部状态谓词（`opened` / `closed` / 弹窗 detach 判定）。「点了但状态没变 → 再点」仍成立；`Humanizer.click` 在 `mouse.down` 之前失败（`covered-by` / `point-drift` / `zero-box`）确定未派发，可安全重试；带 `MAYBE_DISPATCHED` 标记的异常**不得**再派发第二次（照 XHS `:809` 的先例）。
4. 验证码路径 `:846/:854` 保持 `force=True` + 原生，按 03 的三字段注释，不接入 Humanizer。

`[needs-live]`：注释里「普通 click 对抖音自定义组件常静默失效」是否对 `Humanizer.click` 也成立。若真机成立，**按 03 失败即失败**（`ElementUnusable`），不得回退 `_native_click`、不得用 force 掩盖。

### 5. 裸 locator：收窄责任在调用点，多义硬错

`[code]` `check(..., "interactive")` 在 `count != 1` 时返回 `ambiguous:N`（`utils/dom.py:484-486`）；`wait_resolved` 拿到 `ambiguous:` 立即中止（`:700-706`）。XHS 的主链路用候选列表保证唯一，`.first` 只出现在写明理由的降级路径（如 `:2564-2566`）。但 `resolve` / `Candidate` 属 charter 不搬的 dom 能力。

决定：

- `Humanizer` 保持 `count()==1` 严格，**不在内部自动 `.first`**。
- 每个改 `Humanizer.click` 的调用点，实施时必须能说明唯一性：优先容器限定或 `exact=True`；确实要「多个里取第一个」时显式 `.first`，并在同处注释理由。
- `ambiguous:N` 归类为**选择器问题**（改代码），不得当页面问题重试、不得用 `force` 掩盖。
- 不引入 `Candidate` / `resolve` / 候选列表于 15 个平台（charter 边界）。

### 6. 豁免记录：零新增

四处冲突全部判成「改」，本票**没有产生任何豁免**。因此：

- 不建豁免表、不建平台常量表、不在 `docs/` 新增清单页、不新增静态门。
- 记录仍由两处承担：03 的行内三字段标记 `# humanize-impossible: <失败模式>；<依据等级>；已排除替代`（AST 标记门），以及 06 的「每平台实施表」（承载 01 的「保持原生」54 条）。
- 规格里明写一句：**07 未产生新豁免；`el.click()` 归零、`force=True` 仅标记门两处静态门即全部约束**。

### 7. 改造顺序：波不动，热点在波内置顶

05 的五波保持不变（W1 真机三平台 → W2 国外 → W3 国内冲突 → W4 国内主体 → W5 长尾），不因本票重排。仅调整波内顺序：

| 波 | 热点置顶 | 理由 |
| --- | --- | --- |
| W2 | YouTube 先做 | `#` 候选点选最可能推翻本票 §2 的决策 |
| W3 | 抖音、微博先做 | 删除 `_native_click`（§4）与发布按钮落点（§1）风险最高 |
| W5 | 百家号先做 | 搜索型输入改造（§3）的候选全等最未验证 |

W1（IG / TikTok / 小红书）不涉及本票冲突，顺序不变；心跳仍是 05 的「平台完成 = 事件序列 + 字段值读回 + 平台静态门」。

### 8. 未验证清单（本票新增）

- 微博：空 `div` 的实际覆盖范围；`(0.65, 0.5)` / `(0.35, 0.5)` 哪个可命中。
- YouTube：`tp-yt-iron-dropdown` 候选结构与全等点选可行性。
- 抖音：`Humanizer.click` 能否驱动封面/声明/合集这些自定义组件（静默失效是否重现）。
- 百家号：`.cheetah-select` 候选项文本是否可全等匹配。
- 以上全部 **未验证（无真机环境）**，进 06 的集中未验证清单。

### 9. 边界

- 08 的共享层三缺陷（hover 漂移、托管视口、容器裁剪）不在本票裁决范围；本票的抖音封面 hover（`:935` 已由 03 判 `Humanizer.hover`）会受 hover 漂移影响，最终依赖 08。
- 微博托管模式的 `publish_page` 需第二个 `Humanizer`（01 已记），本票不重复。
- 本票不修改 charter；「不搬 dom 其余能力」的边界通过 §5 继续成立。
