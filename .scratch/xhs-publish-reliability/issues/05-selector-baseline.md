# 05 — 选择器基线矩阵

Status: resolved
Type: grilling
Blocked by: 01, 02
Assignee: wayfinder-session (opencode)

## Question

用 01（上游信号清单）与 02（真机 DOM）的实证，逐环节决定选择器基线：**采用上游 / 保留现状 / 双代并存**。产出“环节 × 现选择器 × 候选 × 中文依赖 × 决策 × 兜底顺序 × 命中日志”矩阵。

必须覆盖：发布按钮、标题、正文、图文上传 input、视频上传 input、话题候选、话题回读、定时开关、定时时间输入、原创开关、原创确认弹窗、内容类型菜单项、封面弹窗、登录二维码、登录态正向锚点。

约束：

- **主发布链路（上传 → 标题 → 正文 → 话题 → 发布）零中文依赖**为默认目标。
- 保留中文的项必须：限定容器 + 精确匹配 + 有结构兜底。
- 双代并存的项必须打命中日志（写明哪一代），便于真机验证后删旧分支。
- 每项给出“找不到/找到但不可用”两种失败文案。

产出：矩阵表 + 每项的兜底顺序 + 何时可以删除旧分支。

## Evidence from 02（真机取证）

- `xhs-publish-btn`（`is-publish`/`submit-disabled`）存在且可用；旧版 `.publish-page-publish-btn button.bg-red` 现网为 **0**。
- 正文为 `div.tiptap[role=textbox]`（ProseMirror），`div.ql-editor` 为 0。
- 标题 `div.d-input input` 与 `input[placeholder*="填写标题"]` 是同一节点。
- 话题候选：`#creator-editor-topic-container .item .name`（单次 50 个）。
- 定点：`.post-time-wrapper .d-switch`、`.d-datepicker-input-filter input.d-text`、`.d-switch-simulator` class 状态均与现有选择器一致。
- 详见 `research/02-live-dom-snapshot.md` §2/§3/§4/§5。

## Answer

### 决议基线（grilling 结论）

1. **发布按钮只保留新版**：`xhs-publish-btn` 是唯一入口；旧版 `.publish-page-publish-btn button.bg-red` 直接删除，不做兜底（现网 0 命中，且上游「新版禁用也不回落旧版」的语义更安全）。
2. **逐项比“现选择器 vs 上游”，取更健壮者**——不是无脑照抄上游。判据顺序：容器限定 + 结构属性（id > 容器 class > 设计系统类）> 元素属性 > 文本。
3. **尽量不用文本**；文本不可省时**只保留中文兜底**（2026-11-11 由 22 修订：`locale=en-US` 下界面仍全中文，英文界面不存在，原「中英双语、英文优先」作废）。
4. **命中日志**：每次解析打 `debug`（环节、命中代次 `structure|upstream|text-zh`、selector、URL）；只有非首选分支命中时额外打 `info`。
5. **旧分支收敛**：新分支在真实发布中稳定命中、旧分支 0 命中，即可删除旧分支；不再等固定次数。文本兜底至少要在目标语言界面验证过一次再删。

### 选择器基线矩阵

> 置信度口径：实机=02 取证（含 `research/raw/` 快照）；代码明确=现有代码；上游=01 的源码事实；仅推断=无实机证据。

| # | 环节 | 现选择器（代码明确） | 主候选（更健壮者） | 兜底顺序 | 中文依赖 | 置信度 |
|---|---|---|---|---|---|---|
| 1 | 发布按钮（即时/定时共用） | `button:has-text("发布")` / `button:has-text("定时发布")` — **实机 0 命中** | `xhs-publish-btn` + `is-publish` + `submit-disabled` | 无（只留新版） | 无 | 即时=实机；定时=**仅推断**（同一元素，需真机确认） |
| 2 | 标题 | `input[placeholder*="填写标题"]` | `div.d-input input`（与现选择器同一节点，编辑器内唯一） | `input[placeholder*="填写标题"]`（中文单语；22 已证无英文界面） | 仅兜底 | 实机 |
| 3 | 正文 | `p[data-placeholder*="输入正文描述"]` | `div.tiptap[role="textbox"][contenteditable="true"]` | `div.ProseMirror[contenteditable="true"]` → `p[data-placeholder*="输入正文描述"]` 上溯 `[contenteditable=true]`（中文单语） | 仅兜底 | 实机 |
| 4 | 图文上传 input | `input[type="file"][accept*=image]`.first；兜底 `div[class^='upload-content'] input.upload-input` | `div.upload-content input.upload-input`（空状态实机命中） | `input[type="file"][accept*=".jpg"]` 等；**count 必须 ==1，否则报多义，禁止 `.first`** | 无 | 单张实机；N 张未验证 |
| 5 | 视频上传 input | `div[class^='upload-content'] input[class='upload-input']`；重试 `div.progress-div [class^="upload-btn-input"]` | `div.upload-content input.upload-input` | `input[type="file"][accept*=".mp4"]` / `[accept*=video]` | 无 | 空状态实机；重试路径代码明确 |
| 6 | 话题候选 | `#creator-editor-topic-container .item` → `.name` | 与现相同（上游同款） | 无 | 无 | 实机（单次 50 项） |
| 7 | 话题回读 | **无** | `div.tiptap[role="textbox"] a[data-topic]`（限定编辑区） | 无 | 无 | 实机（编辑区内每次 +1；整页 +2 是预览镜像，23 已定位） |
| 8 | 定时开关 | `.custom-switch-card` 过滤「定时发布」→ `.d-switch` | `.post-time-wrapper .d-switch` | `.post-time-switch-container .d-switch`（结构；raw 快照命中） | 无 | 实机 |
| 9 | 定时时间输入 | `.d-datepicker-input-filter input.d-text` | 与现相同（更精确、已实机） | `.date-picker-container input`（上游） | 无 | 实机（两者各 1） |
| 10 | 原创开关 | `.custom-switch-card` 过滤「原创声明」→ `.d-switch` | `.original-wrapper .d-switch` | `.custom-switch-card` 内文本 `原创声明`（容器限定 + 精确匹配） | 仅兜底 | 实机（raw HTML） |
| 11 | 原创确认弹窗 | `[role=dialog], .d-modal, .d-dialog` 过滤「声明原创」 | `div.d-modal.creator-modal-style` | 确认按钮 `div.d-modal button.custom-button`（上游）→ 文本 `声明原创` | 仅兜底 | 主=实机但仅 1 样本；`custom-button`=上游、未实机 |
| 12 | 内容类型菜单项 | `get_by_text("添加内容类型声明")` + **`#publish-container div`** | `.publish-container` 内文本 `添加内容类型声明` 的 `[tabindex="1"]` select wrapper | 同文案 `_js_click_by_text`；选项限定 `.declaration-drop-down .d-option` + 精确文案 | **必须**（选项本身是中文枚举） | 实机 DOM（22：无英文界面） |
| 13 | 封面弹窗 | `text=设置封面` / `div.upload-cover`（**22 实测 0 命中**）/ `div.cover-plugin-preview div.default.pointer`（**0 命中**）/ 「上传封面」/ `div.upload-wrapper input[type=file]` / 「确定」 | `.cover-edit-entry`（容器 `.cover-edit-stack`）→ `.d-modal.cover-modal.creator-modal-style.main-cover-editor-modal` | 文本 `编辑封面` → `设置封面`；弹窗内动作按钮 `上传` / `完成`；input 限定弹窗内 `input[type=file]` | 仅兜底 | 实机（22：入口与弹窗结构/文案）；上传与完成动作未执行 |
| 14 | 登录二维码 | `.login-box-container` + 「APP扫一扫登录」+ xpath `following-sibling::div//img`；`img.css-wemwzq` | 登录框内切换图标 `img.css-wemwzq` → 二维码 `img.css-1lhmg90` | 文本 `APP扫一扫登录` 的容器内 `img` | 仅兜底 | 切换图标+二维码=实机（22）；`.login-box-container` / `.qrcode-img` 未单验 |
| 15 | 登录态正向锚点 | `input.upload-input`、`div.progress-div [class^="upload-btn-input"]`、`div[class*='upload-content'] input`、`button:has-text("发布")`(**实机 0**) | 前三条（零文本） | 上游 `.main-container .user .link-wrapper .channel`（首页 check 候选，未验证） | 无 | 实机（空状态） |
| 16 | 登录失效（负向） | `div[class*='login-box']` + URL `/login` 前缀 | URL path 前缀优先（零文本），DOM 仅作佐证 | 上游 `/website-login[/captcha]`（**真机未观察到，不采用为判据**；验证页形态归 07） | 无 | 实机（`/login` + login-box） |

### 实机取证顺带发现的两处现存 bug

1. **`#publish-container` 不存在**：DOM 里是 **class** `.publish-container`（`research/raw/editor-image.html`）。当前 `_click_declaration_option` 的主路径 `#publish-container div` 恒为 0，实际一直靠 `_js_click_by_text` 兜底。
2. **发布按钮的三条中文 `button:has-text(...)` 现网全 0**：视频/图文两条发布循环每次点击都会等到超时才抛错，然后重试到 15 分钟预算耗尽；`XHS_LOGIN_POSITIVE_SELECTORS` 里的 `button:has-text("发布")` 同样是死锚点。

### 失败文案约定

统一两类错误（`缺失` / `找到但不可用`），文案必须带「已尝试顺序」与「是否已点击发布」，供 03 的 ARM/FIRE 与退出码使用。

| # | 环节 | 找不到（missing） | 找到但不可用（unusable） |
|---|---|---|---|
| 1 | 发布按钮 | 发布按钮缺失：未找到 `<xhs-publish-btn>`（已尝试：`xhs-publish-btn`）。可能是登录页/非发布页/结构变更；**未点击发布，未发布任何内容**。 | 发布按钮不可用：命中 `xhs-publish-btn`，但 `is-publish=<v>`、`submit-disabled=<v>`（仍在处理或表单未就绪）。**未点击发布**。 |
| 2 | 标题 | 标题输入框缺失：已尝试 `div.d-input input` → 中文 placeholder；**未填写标题，未点击发布**。 | 标题输入框不可用：命中 `<candidate>` 但不可见/只读/被覆盖层遮挡；**未点击发布**。 |
| 3 | 正文 | 正文编辑器缺失：已尝试 tiptap 结构 → ProseMirror 结构 → 中文 placeholder 上溯；**未填写正文**。 | 正文编辑器不可用：命中 `<candidate>` 但 `contenteditable=false`/不可见/被遮挡。 |
| 4 | 图文上传 | 图文上传输入框缺失：已尝试 `.upload-content input.upload-input` → `accept` 过滤；**未上传任何图片**。 | 图文上传输入框不可用：命中 `<candidate>` 但未 attached / `accept` 不匹配 / 命中 N 个文件输入无法唯一确定（拒绝 `.first` 猜测）。 |
| 5 | 视频上传 | 视频上传输入框缺失：已尝试 `.upload-content input.upload-input` → `accept` 过滤；**未上传视频**。 | 视频上传输入框不可用：命中 `<candidate>` 但未 attached / 多义 N 个。 |
| 6 | 话题候选 | 话题候选容器缺失：未找到 `#creator-editor-topic-container`（联想接口未返回或超时）。 | 话题候选不可用：容器存在但 deadline 内 `.item` 始终为 0（容器空壳可见 ≠ 候选就绪，见 23）。 |
| 7 | 话题回读 | 话题未落盘：点击候选后 1s 内编辑区内未出现任何 `a[data-topic]`。 | 话题回读不符：编辑区内新增节点不等于 1，或 name 不匹配（期望 `<tag>`，实际 `<names>`）。 |
| 8 | 定时开关 | 定时开关缺失：已尝试 `.post-time-wrapper .d-switch` → `.post-time-switch-container .d-switch`。 | 定时开关不可用：命中 `<candidate>` 但不可见/disabled/点击后未展开。 |
| 9 | 定时时间 | 定时时间输入框缺失：已尝试 `.d-datepicker-input-filter input.d-text` → `.date-picker-container input`。 | 定时时间输入框不可用：命中 `<candidate>` 但不可编辑，或值未生效（回读归 11）。 |
| 10 | 原创开关 | 原创声明开关缺失：已尝试 `.original-wrapper .d-switch` → 中文文本卡片；**该项为增强能力，跳过继续**。 | 原创声明开关不可用：命中 `<candidate>` 但状态不可读/disabled；**跳过继续（不盲点）**。 |
| 11 | 原创确认弹窗 | 原创确认弹窗未出现：点击开关后未见 `.d-modal.creator-modal-style`；按「无需确认」继续。 | 原创确认弹窗不可用：弹窗存在但未找到 `.d-checkbox` 或确认按钮 `声明原创`；跳过原创声明。 |
| 12 | 内容类型 | 内容类型声明入口缺失：`.publish-container` 内未找到 `添加内容类型声明`；跳过该声明。 | 内容类型声明不可用：入口存在但下拉未展开，或选项 `<label>` 未命中；跳过该声明。 |
| 13 | 封面 | 封面入口缺失：未找到 `.cover-edit-entry`（旧 `div.upload-cover` 现网 0 命中）；跳过封面（用首帧）。 | 封面流程不可用：弹窗已开（`.main-cover-editor-modal`）但 `上传`/`完成` 或图片 input 缺失；跳过封面。 |
| 14 | 登录二维码 | 登录二维码缺失：未找到 `.login-box-container img` / `.qrcode-img[src]`；请重新登录。 | 登录二维码不可用：节点存在但无 `src`/不可见；请重新登录。 |
| 15 | 登录态正向 | 未登录：发布页未出现任何登录态锚点（`input.upload-input` / `.progress-div [class^=upload-btn-input]` / `.upload-content input`）。 | 登录态不确定：锚点存在但不可见（可能仍在加载/被覆盖层遮挡）。 |
| 16 | 登录失效负向 | —（不作为正向选择器；URL 未命中 `/login` 即不判失效） | URL 含 `login/captcha` 但未找到 `login-box`；**仍按登录失效处理**（URL 优先）。 |

### 实现约定（交给 17 汇总进 spec）

- 统一解析器：`resolve(scope, candidates) -> (locator, kind, selector)`；候选按表内顺序尝试，命中即打日志并返回；全部失败抛 `missing`。
- `kind` 取值 `structure|upstream|text-zh`（22 修订：删 `text-en`）；`kind != structure` 额外打 `info`。
- 文件输入类元素（4/5/13）**禁止无条件 `.first`**：count != 1 且无法用容器收窄时，抛 `unusable`（多义），避免把封面 input 当正文图/视频 input。
- 文本候选集中存放，**只保留中文**（22 已证无英文界面，英文词表不再回填）。
- 选择器文案里的 `<candidate>`/`<v>`/`<tag>` 由错误对象字段填充，不拼进业务成功日志。

### 旧分支何时删除

| 环节 | 删除条件 |
|---|---|
| 1 发布按钮 | 旧版选择器与三条中文 `button:has-text` **本次直接删**（无过渡期）。 |
| 2 标题 / 3 正文 | 结构主分支在真实发布中稳定命中后，删中文文本兜底（22 已验目标语言界面）。 |
| 4 图文 / 5 视频 | `.upload-content` 主分支命中后，删 `.first` 猜测分支与 `div[class^=...]` 旧写法。 |
| 8 定时开关 / 10 原创开关 | 新结构主分支稳定命中后，删中文卡片过滤分支。 |
| 9 定时时间 | 两条都是零文本结构，**保留双结构兜底**，不设删除期限。 |
| 11 原创弹窗 | `.creator-modal-style` 在两个不同账号各出现一次后，删 `[role=dialog]` 旧分支。 |
| 12 内容类型 | 修正 `.publish-container` 后，`_js_click_by_text` 仅作兜底；选项路径转 `.declaration-drop-down`。 |
| 13 封面 | 真机跑通一次后，删 `text=设置封面` 滚动锚点。 |
| 14 登录二维码 | 真机确认结构节点后，删文本 xpath 与 `img.css-wemwzq`。 |
| 15 登录态 | 中文 `button:has-text("发布")` **本次直接删**。 |
| 16 登录失效 | 不删；07 决定验证页 path 后再补。 |

### 需真机验证（未定项）

1. **定时发布**是否复用同一个 `xhs-publish-btn`（只改文本/aria），还是换按钮。
2. **英文界面是否真实存在**，以及各文本锚点的英文文案（→ 新工单 22；**已答：不存在**，`locale=en-US` 下仍全中文）。
3. 登录页二维码真实结构（`.qrcode-img[src]` vs `.login-box-container img`）。
4. `.creator-modal-style` 是否稳定用于原创弹窗（当前仅 1 个样本）。
5. `.publish-container` 是否覆盖内容类型声明入口（class 修正后）。
6. N 张图片时 `.img-preview-area .pr` 的计数行为（归 09）。

### 与上游的偏离（按 charter 记录理由）

- **话题回读不用整页「严格 +1」**：整页查询一次插入得到 2 个同值 `a[data-topic]`（1 编辑 + 1 预览镜像），上游整页判据会 100% 失败；限定编辑区后每次恰好 +1，改为「编辑区内新增恰好 1 个且 name 全匹配」（23 已证）。
- **登录失效不采用 `/website-login` 前缀**：实机只观察到 `/login?...`；上游路径判据不能照搬（验证页形态留给 07）。
- **发布按钮不留旧版兜底**：上游在「新版存在但禁用」时不回落旧版；我们更进一步，旧版现网 0 命中，直接删。
- **成功判据不采用上游的「URL 不含 /publish/publish」**：03/04 已定（会误把验证页当成功）。

## Comments

- 登录/验证判据已由 **07** 落定（2026-11-11），与本表第 16 行的关系：**URL path 前缀优先、DOM 仅佐证** —— 与本表一致；区别只在于路径集：`/login` 为主判据（本表），另把 `/website-login/captcha` → 验证页、裸 `/website-login` 及未知子路径 → 登录页，作为**兼容常量**纳入（真机未观察到，属上游常量）。本表「不采用 `/website-login`」的准确含义是「不照搬为**唯一**判据」，本票保留 `/login` 为主，故两者不冲突。DOM 佐证改用 06 的 `visible` 档（裸 `is_visible()` 不看 opacity）。
- **第 4 行（图文上传 input）由 09 修订（2026-11-11）**：不再是一次 `set_input_files(全部)`，也不允许 `count != 1` 时 `.first` 猜测。改为**逐张**——首张走空状态唯一 `div.upload-content input.upload-input`（`count == 1`）；第 2 张起点 `.img-preview-area .entry`（「+」瓦片）→ `expect_file_chooser()` → `set_files([1 张])`；备选为 `.img-upload-area` 容器内 `accept` 匹配且 `count == 1` 的 input。上游「`accept` 匹配不上就取 `inputs[0]`」被明确禁止（其 issue #868 自承会误取视频 input）。完成判据归 09（`.pr` 计数 + 静默复检），不在本表。
- **新增环节「添加图片瓦片」**：`.img-preview-area .entry`（`research/raw/editor-image.html` 实机存在，内含 `svg.add-img-icon`），零文本，用于第 2 张起的派发入口。置信度：存在=**实机**；点击触发 file chooser=**仅推断**（→ 24）。
- **第 13 行（封面弹窗）候选已漂移，由 22 实机修正（2026-11-11）**：现网视频页 **没有** `div.upload-cover`（`click()` 30s 超时），也**没有** `.cover-plugin-preview div.default.pointer`；当前结构入口是 **`.cover-edit-entry`**（容器 `.cover-edit-stack`，文案「编辑封面」）。弹窗为 `.d-modal.cover-modal.creator-modal-style.main-cover-editor-modal`，内部动作是 **`上传` / `完成`**，**没有** 本行假设的「上传封面」tab 与「确定」按钮。→ 17 汇总时按此替换第 13 行候选与失败文案；英文兜底一并删除（英文界面不存在，见 22）。证据：`research/22-english-ui-evidence.md` §6、`research/raw/22-en-US-cover-modal.*`。
- **英文兜底全部删除（2026-11-11，22）**：`locale=en-US` + `Accept-Language: en-US` 下所有已采环节仍渲染原中文，图文编辑器 `bodyText` 指纹与 zh-CN 完全相同。本表英文候选不再回填；文本兜底收敛为**中文单语**。
- **第 1 行「定时发布仅推断」已由 26 实机确认（2026-11-11）**：定时发布复用**同一个** `xhs-publish-btn`，`is-publish` / `submit-disabled` / `is-save-draft` 不变，只有 `submit-text` 从 `发布` 变为 `定时发布`（`save-text` 恒为 `暂存离开`）。→ 该环节**零文本可判定**，不需要 `button:has-text("定时发布")`。
- **第 8/9 行补充（26 实机）**：开关状态读 `.post-time-wrapper .d-switch-simulator` 的 `checked`/`unchecked` class（**无** `aria-checked`/`data-checked`）；开启后 `.date-picker-container` 出现且输入框默认值为 `now+1h`，关闭后整块移除。日期输入是受控组件，非法值只在**失焦后**回滚，详见 26/27。
