# 10 — 人类化交互的最小可行子集

Status: resolved
Type: grilling
Blocked by: 03
Assignee: wayfinder-session (opencode)

## Question

决定“行为层”做到什么程度，以及它的时间成本上限。需要确认：

1. **覆盖面**：标题逐字输入、正文前 N 字逐字、标签、发布前停顿、鼠标轨迹——各做/不做，给出理由（Profile 的指纹补丁不覆盖行为特征，但这是相关性判断，标注置信度）。
2. **参数**：逐字间隔分布（上游 lognormal μ=-2.12 σ=0.50，min 30ms max 400ms，均值约 120ms）、发布前停顿（400ms–4s）、鼠标步进与抖动（±8px、45–250ms 按压）。
3. **时间预算**：长正文成本如何封顶（前 N 字逐字 + 余下 `insert_text`；或按总长缩放分布）？与 15 分钟预算的关系。
4. **必须避免的写法**：`fill()`（瞬时设值）、`el.click()`（`isTrusted=false`）、固定 `delay=30`。替代方案与不可替代的例外。
5. **可测试性**：随机源/时钟如何注入；测试断言什么（调用次数与取值范围，而非具体毫秒）；如何防止测试变慢。

产出：API 契约（函数签名 + 参数 + 上界）+ 调用点替换清单 + 长文本时间上界的计算示例。

## Answer

**决议（2026-11-11，HITL 逐题裁定）**

1. **覆盖面 = 上游全量**：`humanize` 的 11 个动作全部实现（`Keystroke` / `AfterType` / `AfterNavigate` / `BeforeSubmit` / `PointerSettle` / `ClickHold` / `BeforeClick` / `AfterClick` / `BetweenScroll` / `Reading` / `AfterInteract`）。
2. **接线 = 语义锚点（选项 A）**，不机械垫时延。理由只有一条：有动作 ≠ 像人，均匀垫时延本身就是可测特征（与 charter ① 相反）。上游发布链路本身也是这个形状。
3. **范围 = 共享层**：不是小红书专属。小红书先行验证，其余平台由 **15** 迁移（用户 2026-11-11 明确：其它平台也得改这样）。
4. **打字时间无上限（选项 C）**：不做「超预算改粘贴」的降级；超时按既有语义（点击前 `exit 1`）。长文平台由此暴露的预算冲突见 **25**。
5. **点击全站统一**：曲线 + 抖动落点 + `stillOn` 复核 + 按下保持；**无内部重试**；删除 `el.click()` 兜底。
6. **日期不回读**：按上游逐字键入，回读统一归 **11**。

### 0. 上游事实（作为对照，不作理由）

| 事实 | 内容 | 置信度 |
|---|---|---|
| 动作库 | 11 个动作，全部 LogNormal `exp(μ+σz)`，区间截断 | 代码明确 |
| 发布链路实际接线 | 只有 `Keystroke`、`AfterType`、`AfterNavigate`(一次)、`PointerSettle`、`ClickHold` | 代码明确 |
| `BeforeSubmit` | 发布链路**不用**（仅 `notification_reply.go:82`） | 代码明确 |
| `BeforeClick`/`AfterClick`/`BetweenScroll`/`Reading`/`AfterInteract` | 发布链路不用；具体非发布调用点**未取证** | 定义代码明确；调用点未取证 |
| 打字底层 | 逐 rune `Input.insertText`，**不产生 keydown/keyup** | 代码明确 |
| 点击 | `Click()` 一次成败，**无重试**；`ClickAt` 连 `stillOn` 都没有 | 代码明确 |
| 日期 | `Eval(this.select())` + 逐字键入；**无值回读**；前后各一个固定 `time.Sleep`（800ms / 500ms） | 代码明确（`publish.go:1066-1119`） |

**不照抄的两处**：固定 `Sleep`（可测常量）、`ClickAt` 缺落点复核（03 已明令补上）。

### 1. 打字机制的天花板（本票修正了一个错误认知）

Playwright `keyboard.type` 对**不在 US 键盘布局上的字符只发 `input` 事件**（官方文档明确）。即：

- **ASCII** → `keyboard.press(char)`：keydown + keypress/input + keyup，`isTrusted=true`；
- **中文 / emoji** → `insert_text(char)`：只发 input，**与上游同级**。

要个中文补 keydown 只有两条路：伪造 `KeyboardEvent`（`isTrusted=false`，更假）或走 IME composition（复杂、本身是可识别特征）。**两条都不做**（用户裁定）。

因此实现是「逐字符分派」= Playwright `type()` 的内部逻辑 + 每个字符后采样 `Keystroke`。

### 2. API 契约（`utils/humanize.py`，零平台依赖）

```python
@dataclass(frozen=True)
class LogNormal:
    mu: float
    sigma: float
    min_s: float
    max_s: float
    def sample(self, rng: random.Random) -> float: ...

@dataclass(frozen=True)
class HumanizeProfile:
    keystroke: LogNormal
    after_type: LogNormal
    after_navigate: LogNormal
    before_submit: LogNormal
    pointer_settle: LogNormal
    click_hold: LogNormal
    before_click: LogNormal
    after_click: LogNormal
    between_scroll: LogNormal
    reading: LogNormal
    after_interact: LogNormal
    enabled: bool = True

DEFAULT_PROFILE = HumanizeProfile(...)   # 见 §3，原样采用上游参数

class Humanizer:
    def __init__(self, page: Page, *, profile: HumanizeProfile = DEFAULT_PROFILE,
                 rng: random.Random | None = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None: ...

    async def type_text(self, target: Locator, text: str) -> None
    async def click(self, target: Locator) -> None
    async def after_type(self) -> None
    async def before_submit(self) -> None
    async def after_navigate(self) -> None
    async def between_scroll(self) -> None
    async def reading(self) -> None
    async def after_interact(self) -> None
    async def before_click(self) -> None       # 只在有语义锚点时调
    async def after_click(self) -> None        # 只在有语义锚点时调
```

约束：

- 单例参数表：任何平台不得复制第二份参数；平台差异用 `dataclasses.replace(DEFAULT_PROFILE, ...)`。
- 注入 `rng` / `sleep`：离线可测、可复现。
- 总开关：`profile.enabled=False` 或环境变量 `HUMANIZE=0` → 零时延快路径（文本一次 `insert_text`，点击一次 `locator.click`），用于排障与对照。
- 不 import `uploader.*` / 平台常量（依赖方向同 15）。

### 3. 默认参数（原样采用上游，μ/σ/min/max；均值为 `exp(μ+σ²/2)`）

| 动作 | μ | σ | min | max | 均值 | 发布链路接线 |
|---|---|---|---|---|---|---|
| `Keystroke` | -2.12 | 0.50 | 30ms | 400ms | 136ms | 是（每字符） |
| `AfterType` | -0.51 | 0.40 | 200ms | 3s | 0.65s | 是（每次输入完） |
| `AfterNavigate` | 0.41 | 0.45 | 600ms | 6s | 1.67s | 是（goto 后） |
| `BeforeSubmit` | 0.0 | 0.40 | 400ms | 4s | 1.08s | 是（FIRE 前；超出上游） |
| `PointerSettle` | -1.20 | 0.35 | 200ms | 1200ms | 0.32s | 是（每次点击） |
| `ClickHold` | -2.47 | 0.33 | 45ms | 250ms | 89ms | 是（每次点击） |
| `BeforeClick` | -1.61 | 0.45 | 80ms | 1s | 0.22s | 不默认接 |
| `AfterClick` | -0.92 | 0.35 | 150ms | 2s | 0.42s | 不默认接 |
| `BetweenScroll` | -0.22 | 0.40 | 250ms | 3s | 0.87s | 需要滚动时接 |
| `Reading` | -0.36 | 0.40 | 300ms | 3s | 0.76s | 天然等待点可选 |
| `AfterInteract` | 0.88 | 0.30 | 2s | 3s | 2.52s | 不默认接 |

参数无权威性（上游手调），采用只因用户裁定「全量采纳」；后续调参不改变契约。

### 4. 点击语义

`humanized_click(target)`：

1. `target.bounding_box()`；不可得 → 抛「确定未派发」错误。
2. 抖动落点：内缩 `min(size*0.15, 8px)` 后取随机点（X/Y 各一次）。
3. 曲线移动：距离 <6px 直连；否则三次贝塞尔，`steps = clamp(round(dist/10), 10, 40)`，控制点沿法线偏移 `dist*(0.05+0.10*rand)`，每步 `5+rand(0..4)` ms，`easeInOut`。
4. `sleep(PointerSettle)`。
5. `stillOn` 复核：落点元素仍是目标、位置 ±1px、按 06 的 `interactive` 档 hit-test；不符 → 抛「确定未派发」错误（**不重试**）。
6. `mouse.down` → `sleep(ClickHold)` → `mouse.up`。
7. `mouse.down` 之后任何异常 → 标记「可能已派发」，向上抛。

不变量：

- **内部零重试**；重试只发生在 03 的 ARM 循环（点击前）。
- **不存在无 `stillOn` 的坐标点击**；若将来需要坐标点击（如 `ClickAt` 场景），必须复用第 5 步。
- `force=True` 一律移除：它绕过可操作性检查，与 `stillOn` 语义冲突。

### 5. 接线表（小红书发布链路）

| 时点 | 动作 | 备注 |
|---|---|---|
| `page.goto` 后 | `after_navigate` | 与上游一致 |
| 每次点击 | `click()`（内含 settle + stillOn + hold） | 与上游一致 |
| 每次文本输入完 | `type_text` + `after_type` | 与上游一致（标题/正文/话题/日期/地点/来源） |
| FIRE 前一次 | `before_submit` | **超出上游**；charter ① 的提交前停顿 |
| 真实需要滚动处 | `scroll_into_view_if_needed` + `between_scroll` | 按需 |
| `Reading` / `AfterInteract` / `BeforeClick` / `AfterClick` | **不接**（API 保留） | 无语义锚点，接了只是均匀垫时延 |

### 6. 调用点替换清单（`uploader/xiaohongshu_uploader/main.py`）

| # | 位置 | 现状 | 改为 |
|---|---|---|---|
| 1 | `:590-592` `fill_title` | `fill()` | `type_text` |
| 2 | `:594-604` `fill_desc` | `keyboard.type` + `Backspace`/`Control+KeyA`/`Delete` | `type_text`；清理键保留并走采样；**`Control+KeyA` → `ControlOrMeta+A`**（macOS 下现为无效键，代码缺陷） |
| 3 | `:626` `fill_tags` | `type(delay=30)` | `type_text`（插入逻辑归 08） |
| 4 | `:528` 定时时间 | `fill()` | `type_text`；**回读归 11** |
| 5 | `:857` `:876-884` 地点/日期 | `fill()` | `type_text` |
| 6 | `:902` 转载来源 | `fill()` | `type_text` |
| 7 | 全部点击（约 22 处，含 `force=True` 6 处、登录面板 3 处） | `locator.click()` | `click()` |
| 8 | `:1180-1182` `:1362-1365` 发布 FIRE | `locator.click()` | `click()` + `before_submit` |
| 9 | `:156-173` `_js_click_by_text` | `el.click()`（`isTrusted=false`） | **删除**；声明项改由 05 的结构选择器 + `click()` 接管（`_click_declaration_option` 主路径恒 0 的前提一并修正） |

### 7. 时间上界计算示例（选项 C：无上限）

- `Keystroke` 均值 `exp(-2.12+0.125)=0.136s`
- 标题 20 字：**2.7s**
- 正文 1000 字（小红书上限，**仅推断，需真机确认**）：**136s ≈ 2.3min**
- 10 个标签、约 80 字符：**10.9s**
- `after_type` ×3：**≈2.0s**；`before_submit`：**≈1.1s**；`after_navigate`：**≈1.7s**
- 点击 10 次 ×（320ms + 89ms）：**≈4.1s**
- **合计 ≈2.6min**，15 分钟预算内；小红书场景不会触发任何降级（C 也不降级）。

其它平台的上界（C 的后果）：

| 输入 | 字符 | 逐字耗时 |
|---|---|---|
| TikTok 配文 | 2200（`docs/CLI.md:634`） | ≈5.0min |
| YouTube 描述 | 5000（**仅推断**） | ≈11.3min |
| 知乎/公众号长文 | 数千至上万 | **必然超 15min 预算** → 点击前 `exit 1` |

即：**C 对小红书安全，对长文平台需要单独决定预算口径** → 新票 **25**。

### 8. 测试断言（离线，注入 `rng` / `sleep`）

1. `type_text("ab中文")` → 前 2 字符走 `press`，后 2 字符走 `insert_text`；`sleep` 调用 4 次、每次 ∈ [30,400]ms、顺序与字符一致。
2. `click` 调用序列恰为 `move → sleep(PointerSettle) → stillOn → down → sleep(ClickHold) → up`；落点在 bbox 内缩范围。
3. `stillOn` 失败 → 抛「未派发」且**无** `down`；`down` 后抛错 → 标记「可能已派发」。
4. `uploader/xiaohongshu_uploader/main.py` 中 `fill(` 与 `el.click()` 出现次数为 0（静态断言）。
5. `enabled=False` / `HUMANIZE=0` → 文本一次 `insert_text`、点击一次 `locator.click`、零 `sleep`。
6. 同一 seed → 时延序列完全可复现。

Fake 扩展（归 16）：`RecordingPage` 需记录 `mouse.move/down/up` 与 `insert_text`，并能让 `stillOn` 注入失败。

### 9. 不可离线验证（交 16 真机验收）

- 行为学效果本身：**仅推断**（无平台侧证据，任何「降低封禁率」的断言都不成立，只能标注假设）。
- 曲线移动 + `stillOn` 在真实发布页的通过率（覆盖层、滚动容器）。
- 日期控件逐字输入是否被格式化纠正（11 也会碰）。
- 点击抖动在极小控件（开关、复选框）上的误点率。

### 10. 对其它票的接口

- **03**：FIRE 的单次派发与「确定未派发 / 可能已派发」由 §4 的不变量保证。
- **06**：`stillOn` 复用 `interactive` 档 hit-test 与可见性 helper。
- **08**：话题输入改由 `type_text`；`Backspace` 清理路径的去留归 08。
- **11**：日期/开关/声明的回读统一在此，输入层不破例。
- **15**：本票产出的 `utils/humanize.py` 即共享层第一块；其余平台迁移顺序与开关归 15。
- **16**：§8 断言 + §9 真机项。
- **25**：长文平台在 C 口径下的预算口径。
