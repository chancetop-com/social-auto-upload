# 06 — 页面就绪与元素可用性判定

Status: resolved
Type: grilling
Blocked by: 05
Assignee: wayfinder-session (opencode)

## Question

决定“页面可以开始操作”与“元素确实可用”的判定标准。需要确认：

1. **DOM 就绪等待**：上传前是否加稳定等待（参照上游 `WaitLoad` + `WaitDOMStable(1s, 0.1)` + 2s + 1s），还是用更轻的信号（上传 input 可交互 / 发布按钮出现）。
2. **存在 ≠ 可见**：`is_logged_in` 的正向锚点现只做 `count()`（`main.py:326-328`），隐藏元素也算命中。是否把所有 `count()` 判定改为可见性判定？统一 helper 的契约是什么（`is_visible` + bounding box 非零 + opacity 继承 + `aria-hidden`）。
3. **被遮挡**：是否引入 `elementFromPoint` 等价判定，命中则先清障再点，而不是 `click(force=True)`。
4. **与预算的关系**：就绪等待是否用 `clamp_seconds` 收紧。
5. 每个判定函数的签名与返回（bool / 原因字符串），以及失败文案。

产出：判定 helper 契约 + 全部调用点替换清单 + 与 03 预算的接口。

## Evidence from 02（真机取证）

- 常驻覆盖层：`.feature-guide__btn`「我知道了」在空状态与编辑器全程可见；图文编辑器另有 `role="dialog"` 的「图片可以编辑啦」提示弹窗。二者都可能拦截点击。
- 空状态没有任何标题/正文/发布按钮；只有 `div.upload-content` + 隐藏的 `input.upload-input` → 「页面就绪」不能等这些元素。
- 视频：标题框在 t=3s 就出现，但发布按钮仍 `submit-disabled=true` 到 t≈12s → 「元素出现」不等于「可操作」。

## Answer

**决议**：就绪 = **目标自带信号 + 一次有上限的 DOM 静默**；判定按**元素角色分四档**（不做统一可见性）；遮挡走**已知覆盖层 + Esc**（永不摘节点、永不点空白）；所有等待纳入预算；「不确定」按**离派发远近**分档处理。

### 1. 页面就绪（Q1：选 B，不照搬上游固定睡眠）

- **禁止**上游式 `WaitLoad + WaitDOMStable + 2s + 1s` 的全局盲睡栈（恒定节拍，且不担保水合完成）。
- `page.goto(...)` 统一 `wait_until="domcontentloaded"` + `budget.clamp_ms(...)`；`wait_for_url()` 仅作 URL 守卫，同样 clamp。
- **首次交互前执行一次 DOM 静默门**：`MutationObserver`（`childList` + `attributes` + `characterData`，`subtree`），连续 **500ms 无变更**即通过，**总上限 3s**，整体 `budget.clamp_seconds(3.0)`。
- 到达 3s 上限仍未静默 → **不失败**，打 `warning`（`dom-not-quiet`），继续交给目标判定；目标也没就绪时，错误里附 `dom-not-quiet`。理由：轮播/广告位会持续变更，把“有动画”判成失败是假阴性。
- 静默门**只做一次**，不做“每个动作前都静默”。
- 之后**每个动作等自己的目标**（见下），不再有任何就绪类 `sleep`。
- 与 10 的边界：humanize 的停顿是**防指纹节奏**，不属于就绪等待，不受本条约束；但就绪代码里**不得**再新增固定 `sleep`。

逐环节的首个目标（环节 → 角色 → 信号）：

| 环节 | 角色 | 目标信号 |
|---|---|---|
| 视频上传前 | `ATTACHED` | `.upload-content input.upload-input`（accept 含 video） |
| 图文上传前 | `ATTACHED` | 同上（accept 含 image），必须唯一 |
| 标题 / 正文 | `EDITABLE` | `div.d-input input` / `div.tiptap[role=textbox]` |
| 发布按钮 | `INTERACTIVE` | 03 的 ARM 谓词（存在+可见+`is-publish`+`submit-disabled`），06 只提供 `interactive` |
| 上传完成 | — | 归 **09**；06 只提供判定原语（02：`submit-disabled` 是视频就绪信号） |
| TAB / 开关 / 弹窗按钮 | `INTERACTIVE` | 05 对应锚点 |

> 02 的反例必须保留在规格里：空状态没有标题/发布按钮；视频标题框 t=3s 出现但按钮 t≈12s 才可点 → **「元素出现」不可作为阶段就绪判据**。

### 2. 判定契约（Q2：角色分档；Q6：不确定分档）

**四档角色**（`check(locator, role, *, point=None) -> (ok: bool, reason: str)`）：

| 角色 | 判据 | 不满足时 reason |
|---|---|---|
| `ATTACHED` | 节点在 DOM 且 connected；`count()==1`（多义 → `ambiguous:N`，禁止 `.first`）；属性/容器匹配（`accept`、`.upload-content` 等）；**不要求可见** | `not-attached` / `ambiguous:N` |
| `VISIBLE` | `locator.is_visible()` **且** 祖先链 `display/visibility` 非隐藏、`opacity` 连乘 ≥ **0.1**（**计算样式**，不是内联字符串）**且** 自身 `aria-hidden != "true"` | `zero-box` / `opacity-zero` / `aria-hidden` |
| `INTERACTIVE` | `VISIBLE` + 非 `disabled`/`aria-disabled="true"`/class 含 `disabled` 词元 + `pointer-events != none` + **在真实落点上** `elementFromPoint` 命中自己或后代（默认落点=包围盒中心；发布按钮用 65% x，与 03/10 一致） | `disabled` / `covered-by:<tag.class|#id|text[:40]>` / `probe-failed` |
| `EDITABLE` | `VISIBLE` + 非 `readonly`/`disabled` +（`input`/`textarea` 或 `contenteditable="true"`） | `readonly` / `not-contenteditable` / `disabled` |

**不确定时的分档（Q6，按“离派发有多近”）**：

| 不确定来源 | 处理 | 依据 |
|---|---|---|
| `VISIBLE` / `ATTACHED` 的探测抛异常（样式/包围盒读取失败、节点瞬时卸载） | **放行**（视为通过）+ `warning` | 与上游两套实现一致；兜底是点击时 Playwright 的 actionability（`force=True` 已全删），真不可用时在**派发前**报错 |
| `INTERACTIVE` 的 hit-test 探测抛异常（`elementFromPoint` 返回 null、跨域 iframe、节点卸载） | **阻断**：`ElementUnusableError(reason=probe-failed)` | 这是派发前最后一道闸；放行会进入 FIRE，而 03 规定“先置位再派发”，Playwright 报错会被误记为“可能已发布”→ exit 9 |
| 祖先 `aria-hidden="true"`（非自身） | 仅记 `warning`，不判隐藏 | 只对自身 `aria-hidden` 硬判（与上游一致），避免把 React portal 的临时 aria 状态当不可见 |

> `resolve()` 必须知道角色：**唯一性规则内建在 `ATTACHED` 里**，不额外加 `require_unique` 参数。`VISIBLE`/`INTERACTIVE`/`EDITABLE` 允许 `N≥1` 取 `.first`，但多义时打 `info`。

### 3. 遮挡（Q3：选 C：已知覆盖层 + Esc；不摘节点、不点空白）

阶梯（最多 **2 轮**，每轮都打 `info`，每一步后重新 hit-test）：

1. **已知覆盖层注册表**（数据驱动，按 05 锚点）依次尝试：
   - `.feature-guide__btn`「我知道了」→ 点击它；
   - 图文编辑器 `role="dialog"`「图片可以编辑啦」→ 点弹窗内的确认/关闭（选择器待真机确认）；
   - `div.d-popover` → **Esc**（不点击，避免误选选项）。
2. `Esc` → 200ms → 再 hit-test。
3. 仍未通过 → `ElementUnusableError(covered-by:...)`，错误里带遮挡者 `tag.class`/`#id`/文本前 40 字。

硬约束：

- **永不** `elem.Remove()`、**永不**注入 `display:none`（上游最后一招，charter ① 下不可接受：改变页面 DOM 是可被页面脚本观测的非人类行为）。
- **永不**点空白位置（上游随机点头部；副作用不可控，且上游的判据本身会误判）。
- 正文字段处于焦点/输入中时不清障（Esc 会丢焦点、折叠话题下拉）；例外：`.feature-guide__btn` 可在任何阶段点击（它就是人类会点的“我知道了”）。

### 4. 与预算的接口（Q4：全部 clamp，无“就绪超时”错误类型）

1. 所有发布链路等待一律 `budget.clamp_ms(default_ms)`：`goto`、`wait_for_url`、`wait_for_selector`、`locator.wait_for`、静默门上限。**禁止**裸 `timeout=30000` 字面量。
2. 不新增“就绪超时”错误类型：
   - 单个等待 default 用尽 → 该环节 `ElementUnusableError`（含元素、耗时）；
   - `clamp` 因预算耗尽返回 ≤0 → `budget.pre_click_error()`（exit 1）。
   - 两者都**不得**变成 exit 9。
3. 轮询循环体先 `check_pre_click()`，再 clamp 本轮等待；禁止“外层 `while True` + 内层 30s 等待”。
4. `goto` 用 `domcontentloaded`（见 §1），不用默认 `load`。
5. 登录预检（`is_logged_in` / `cookie_auth`，现 20s + 3s）**不入 15 分钟预算**；登录语义归 12。

### 5. helper API、错误与替换清单（Q5）

新文件 `uploader/xiaohongshu_uploader/dom.py`（15 决定是否上移 shared）：

```python
class Role(Enum):
    ATTACHED = "attached"
    VISIBLE = "visible"
    INTERACTIVE = "interactive"
    EDITABLE = "editable"

async def check(locator, role, *, point=None) -> tuple[bool, str]
async def resolve(scope, candidates, *, role, what) -> Resolved
async def wait_resolved(scope, candidates, *, role, what,
                        default_timeout_ms, poll_ms=200) -> Resolved

@dataclass(frozen=True)
class Resolved:
    locator: Locator
    selector: str     # 命中的候选原文
    kind: str         # structure | upstream | text-zh
    role: Role

class ElementMissingError(RuntimeError):
    what, role, tried: list[str], elapsed_ms, publish_clicked: bool = False

class ElementUnusableError(RuntimeError):
    what, role, selector, reason, tried, elapsed_ms, publish_clicked: bool = False
```

- `resolve()` **单次、不等待**；等待只发生在 `wait_resolved()`（每轮重新解析，和 03 ARM 同哲学）。
- `reason` 是固定枚举：`not-attached`、`ambiguous:N`、`zero-box`、`opacity-zero`、`aria-hidden`、`disabled`、`readonly`、`not-contenteditable`、`covered-by:...`、`probe-failed`、`dom-not-quiet`。
- 两个错误都映射 **exit 1**；`publish_clicked` 只改文案，不升级为 9。
- 文案模板：`<环节>：<missing|unusable>；已尝试 <a → b → c>；原因 <reason>；耗时 <N.N>s；<未点击发布|发布可能已发出>`；05 已定稿的文案作为填充值。

**调用点替换清单**（`main.py`，28 处 `count()` + 9 处 `force=True`）：

| 行 | 现写法 | 替换 |
|---|---|---|
| 208 / 222 | 二维码面板文字 / 二维码 img | `VISIBLE`（img 另加 `ATTACHED`） |
| 277 / 364 | `login_box.count()` | `VISIBLE` |
| 325 | 登录态正向 4 条 `count()` | `ATTACHED`（`input.upload-input` 本就隐藏）+ 外层容器 `VISIBLE` |
| 670 | `_find_publish_failure` 提示扫描 | **整函数删除**（04） |
| 742 / 745 / 750 | 原创卡 / switch / 文字兜底 | `VISIBLE` → `INTERACTIVE` → `INTERACTIVE` |
| 824 / 837 | 声明入口 / 选项 | `INTERACTIVE` |
| 855 / 863 | 拍摄地点 / 联想项 | `EDITABLE` / `INTERACTIVE` |
| 874 / 880 / 889 | 日期输入 / 过滤器 / 确认 | `EDITABLE` / `EDITABLE` / `INTERACTIVE` |
| 929 / 933 / 938 | 勾选框 / 协议文字 / 按钮 | 全部 `INTERACTIVE` |
| 951 / 962 | switch 状态读取 | **非可见性判定**，统一走 `_switch_is_on` |
| 1055 / 1068 / 1076 | 封面上传区 / 文件 input / 确认 | `INTERACTIVE` / `ATTACHED` / `INTERACTIVE` |
| 1140 | 标题框 `count()+is_visible` | `VISIBLE`（就绪语义归 09） |
| 1317 | 图文文件 input | `ATTACHED` |
| 830/838/857/869/876/893/930/934/1057 | 9 处 `force=True` | **全部删除**，由 `INTERACTIVE` + §3 清障代替 |

`count()` 只保留“集合基数”语义（候选 0 个、预览 N 张、文件 input 多义 N 个）；不再用于存在性判定。

### 6. 需真机验证（未定项）

1. `.feature-guide__btn` 点击后是否真的消失（还是只关一次/会话级常驻）。
2. 图文 `role="dialog"` 的关闭/确认控件选择器（02 只证明弹窗存在）。
3. `div.d-popover` 是否“常驻但隐藏”——我们的 hit-test 不受影响，但注册表要避免对隐藏 popover 按 Esc。
4. 自身 `aria-hidden` 判据是否会误杀真实控件（登录盒/发布按钮）。
5. 发布按钮 65% 落点上的 `elementFromPoint` 是否恒命中 `xhs-publish-btn`（定时态同样）。
6. tiptap 在上传完成前后 `contenteditable` 的取值变化（影响 `EDITABLE` 判定窗口）。

### 7. 与上游的偏离（charter 记录）

| 上游做法 | 我们的做法 | 理由 |
|---|---|---|
| `WaitDOMStable`（1s/0.1）+ 固定 2s + 1s，无超时上限（page 300s） | 静默 500ms，上限 3s，失败放行 | 固定节拍=指纹；无上限=挂死风险；静默只是保险，目标信号才是判据 |
| `isElementVisible` 只读**内联 style** 字符串 | 计算样式 + 祖先 `opacity` 链 | ①不降可靠性：祖先类隐藏的按钮上游判可见 |
| 发布按钮 `ClickAt` 跳过 `stillOn`/遮挡复核 | `INTERACTIVE` 在真实落点 hit-test；10 按下前复核 | 上游最危险的点击最不设防，会把“点空”变成 exit 9 |
| 遮挡兜底 `elem.Remove()` | 永不摘节点 | 非人类 DOM 变更，可被页面脚本观测（①） |
| 探测失败口径不一致（可见性放行、命中测试阻断） | 按“离派发远近”统一分档 | 保留安全边界，同时给出可解释规则 |
| 越限提示用 `page.Has` 存在即失败 | 保留“存在性”语义（`ATTACHED` 不套用可见性） | 上游这里是对的：隐藏但已渲染的提示也应算命中 |

### 8. 给下游工单的输入

- **09**：上传完成用 `submit-disabled`（视频）与 `.img-preview-area .pr`（图文）等硬信号；标题框出现只能当次要信号。
- **10**：FIRE 前必须在**实际落点**复核 `INTERACTIVE`（`stillOn` 等价物）；humanize 的停顿是唯一允许的人工延迟。
- **11**：set-then-readback 用 `EDITABLE` 取控件、用值/状态回读判成功，不用可见性代替。
- **13**：`ElementMissingError` / `ElementUnusableError` 一律 pre-click → exit 1；`probe-failed` 不得触发 FIRE。
- **15**：`dom.py` 是 shared 层候选（predicates + resolver + errors）。
- **16**：`FakeLocator` 需支持四档角色的状态注入与 `elementFromPoint` 假实现；覆盖“隐藏锚点”“多义文件 input”“covered-by”“probe-failed”四类用例。
- **17**：把 §1 的“环节 × 角色 × 目标信号”表与 §5 的错误字段并入 spec 的判定表。
