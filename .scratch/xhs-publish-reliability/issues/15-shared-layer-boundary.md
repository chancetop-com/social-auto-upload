# 15 — 共享层边界与迁移顺序

Status: resolved
Type: grilling
Blocked by: 10, 11, 12
Assignee: wayfinder-session (opencode)

## Question

用户要求 humanize 等通用防封手段可被其它 15 个平台复用。需要确认：

1. **抽什么**：人类化输入/点击/延迟、可见性判定、上传完成判定、`set-then-readback` helper、风控页分类——逐项判断是否真的跨平台通用（平台 DOM 差异是否会让 helper 变成配置地狱）。
2. **放哪**：`utils/` 还是 `uploader/`；依赖方向（uploader 不得反向依赖 `sau_commands`；`utils` 不得 import 平台常量）。
3. **接口形态**：无状态函数 vs 带注入（随机源、时钟、logger）的类；与现有 `humanize` 概念（上游 Go 包）命名是否冲突。
4. **迁移顺序**：小红书先行验证 → 下一个平台选谁（按风险/收益）→ 如何灰度（默认开/关、按平台开关）。
5. **不迁的**：`biliup` 子进程（无浏览器上下文）等例外如何处理。
6. 与 `PublishTimeoutBudget`（已存在、仅 TikTok 用）的关系：是同一层还是两条线。

产出：模块清单 + 接口草案 + 迁移路线 + 每步的验收信号（如何判断“这个平台迁移后没变差”）。

## Comments

- **2026-11-11 用户裁定（约束本票）**：humanize 不是「可复用」而是**必须全平台落地**——其它平台也要改成这样。10 已产出 `utils/humanize.py` 的契约与小红书接线；本票负责其余平台的迁移顺序、开关与验收，且**每个平台必须先算出「文本上界 → 打字耗时」**（否则长文平台迁移后直接不可用，见 25）。
- 来自 **13**（2026-11-11）：13 只修小红书，**其余 15 个平台的 `if multilogin:` 登录判定门与写死的 “Multilogin” 文案**（`tk_uploader/main_chrome.py:808`、`ks_uploader/main.py:194`、`dayu_uploader/session.py:37`、`youtube/tencent/alipay/meta/zhihu/douyin…` 同类）都留到本票的平台迁移，连同把 `classify_blocked`（07）与 `provider_label(mode)`（`utils/browser_session.py`）抽进共享层一起做。13 的结论：模式从 `session.mode` 取，不用布尔；文案在 raise 点拼，不做模板。
- 来自 **18**（2026-11-11）：共享层接口再 +1 —— 退出 `10` 时的 stderr 行 `publish_attempted=true`（仅点击后检出登录/验证页时）必须与 `classify_blocked` 同源（同一 `publish_attempted` 标志），16 个平台同形。**节流/冷却不迁移**：18 已定其归调用 App，共享层不为它留任何钩子。

## Answer

**决议（2026-11-11，HITL 逐题裁定）**

1. **抽什么 = 四块 + 一个小件**：`humanize` 动作库、判定原语（四档 + hit-test + 覆盖层清障）、开关状态读取、风控分类「形状」；另加 13 移交的 `provider_label(mode)`（登录文案用）。**不抽**上传完成循环（09 的信号只有小红书取证）、日期/定时回读（11 已定薄口径）、声明/封面弹窗。
2. **放哪**：行为原语进 `utils/`；`PublishTimeoutBudget` / `publish_gate` **留在 `uploader/`**。依赖只向下：`utils/*` 只依赖 patchright + stdlib + `utils/errors.py`，**不 import** `uploader.*` / `sau_commands.*` / 平台常量。
3. **接口形态**：`dom` / `controls` / `blocked` 是**无状态 async 函数**（配置由调用方传入）；只有 `humanize` 保留带注入的 `Humanizer` 类（10 的契约，不推翻）。命名不与上游 Go 包冲突：不同语言、不同进程，不设别名层。
4. **迁移顺序**：**小红书 → TikTok → Instagram**（用户指定的最优先三档）→ 抖音 → 快手 → 视频号 → YouTube → Meta 其余（facebook / facebook_page）→ 支付宝 / 百家号 / 微博 / 虎扑 → 大鱼 / 知乎 / 雪球（文章流，阻塞于 **25**）。
5. **灰度 = 只有全局开关**：沿用 10 的 `HUMANIZE=0` / `profile.enabled=False` 快路径，默认全开；**不设平台级开关**。灰度靠「每平台一个提交/发布」的粒度，出问题回滚该提交。
6. **不迁也不删**：`bilibili`（biliup 子进程，无浏览器上下文）、`uploader/xhs_uploader/`（CLI 不可达）、`uploader/tk_uploader/main.py`（若 CLI 走 `main_chrome`）。删除属独立清理议题，登记 Out of scope。
7. **与预算的关系 = 两条线、一个方向**：`PublishTimeoutBudget` 是唯一时间权威（发布语义）；行为层不 import、不读 deadline、不自己计时，只吃调用方在语义锚点传下来的 clamp。打字不逐字 check（10 的选项 C），预算耗尽在下个锚点表现为点击前 `exit 1`。
8. **验收 = 四件套，但真机不做真实发布**：真机用 `--no-publish` 干跑到 ARM 就绪后退出。真机**强制**：小红书（已有参数）、TikTok、Instagram（**前置改动：补 `--no-publish`**）；其余平台真机可选。

### 模块清单

| 模块 | 内容 | 平台知识 |
|---|---|---|
| `utils/humanize.py` | 10 的 `LogNormal` / `HumanizeProfile` / `DEFAULT_PROFILE` / `Humanizer`（`type_text` / `click` / 各停顿动作 / `HUMANIZE=0`） | **零** |
| `utils/dom.py` | `Role` 四档、`check` / `resolve` / `wait_resolved`、`Resolved`、`ElementMissingError` / `ElementUnusableError`、覆盖层清障（注册表由调用方传） | **零**（注册表是数据） |
| `utils/controls.py` | `read_switch_state(locator)`：`aria-checked` 优先 → `is_checked()` → `None`（读不到）；消除 tk / meta 的现有重复实现 | **零** |
| `utils/blocked.py` | `BlockedKind`（`login` / `verification`）、`BlockedRules`、`classify(page, rules)`：**path 为主、可见 login-box 补强**，不 `unquote`、不做弹层 | **零**（规则是数据） |
| `utils/browser_session.py` | `provider_label(mode)` 由私有转公开（13 移交）；不再有第二个文案来源 | 模式枚举 |
| 平台侧常量 | 每平台的 `BlockedRules`、覆盖层 `Overlay`、选择器候选（05 已定）**留在平台模块** | 全平台 |

不动的既有共享件：`utils/errors.py`（错误类型）、`uploader/publish_timeout.py` + `uploader/publish_gate.py`（预算与闸门）。

### 接口草案

```python
# utils/dom.py
class Role(str, Enum):
    ATTACHED = "attached"; VISIBLE = "visible"
    INTERACTIVE = "interactive"; EDITABLE = "editable"

@dataclass(frozen=True)
class Overlay:
    selector: str
    dismiss: Literal["click", "escape"]

async def check(locator, role: Role, *, point: tuple[float, float] | None = None) -> tuple[bool, str]
async def resolve(scope, candidates: Sequence[str], *, role: Role, what: str) -> Resolved
async def wait_resolved(scope, candidates, *, role: Role, what: str,
                        default_timeout_ms: int, poll_ms: int = 200,
                        budget: Any | None = None) -> Resolved
async def clear_overlays(page, overlays: Sequence[Overlay], *, hit) -> None  # 最多 2 轮；永不摘节点/点空白

# utils/controls.py
async def read_switch_state(locator) -> bool | None   # None = 读不到；策略由调用方定

# utils/blocked.py
class BlockedKind(str, Enum):
    LOGIN = "login"; VERIFICATION = "verification"

@dataclass(frozen=True)
class BlockedRules:
    path_prefixes: Mapping[BlockedKind, Sequence[str]]   # 长前缀优先（/website-login/captcha 先于 /website-login）
    login_markers: Sequence[str]                          # 按 06 的 VISIBLE 档判定

async def classify(page, rules: BlockedRules) -> BlockedKind | None
```

契约与边界：

- 06 的 helper **直接落在 `utils/dom.py`**，不再先写 `uploader/xiaohongshu_uploader/dom.py` 再上移（避免一次无谓搬迁）；`ElementMissingError` / `ElementUnusableError` 同址，仍映射 `exit 1`。
- `reason` 枚举沿用 06（`not-attached` / `ambiguous:N` / `zero-box` / `opacity-zero` / `aria-hidden` / `disabled` / `readonly` / `not-contenteditable` / `covered-by:…` / `probe-failed` / `dom-not-quiet`）。
- `budget` 只是**可选透传**（`wait_resolved` 用它 clamp 本轮等待）；`dom` 不读 deadline、不抛预算错误。
- `classify` 只读：不点击、不清障、不写盘；`login_markers` 为空即纯 path 判定（尚未取证的平台不得凭猜测填 marker）。
- `read_switch_state` 返回三态，消除「读不到 = False」的静默默认（xhs 现状 `_switch_is_on` 的语义由调用方按 11 的口径处理）。

### 迁移路线

| 步 | 平台 | 前置 | 主要动作 | 风险注记 |
|---|---|---|---|---|
| 0 | 共享层落库 | 17 的 spec | 四模块 + `provider_label` 公开 + 测试夹具（16） | 小红书先在本地接线验证接口，不先搬代码 |
| 1 | **小红书** | — | `uploader/xiaohongshu_uploader/main.py` 按 10 §6 / 06 §5 替换；`dom` 引用 `utils/` | 已有 `--no-publish`，可直接真机验收 |
| 2 | **TikTok** | 补 `--no-publish`；对齐已有预算底座 | `fill`/`type` → `type_text`；全部 `click` → `click()`；`if multilogin:` 门删除、文案走 `provider_label`；登录/风控改 `classify` | 3627 行、流程最长；先跑 `HUMANIZE=0` 对照再开 |
| 3 | **Instagram** | 补 `--no-publish`；先对齐其自有 controls 层 | 用 `utils/controls` 替换 `insgraph/controls/toggles.py` 的重复实现；补充行为层 | 近期有并行 instagram 改动，需 rebase 后重跑验收 |
| 4 | 抖音 | — | 同构视频流替换 | 1400+ 行，声明/定时环节多 |
| 5 | 快手 | — | 同上 | — |
| 6 | 视频号（tencent） | — | 同上 | — |
| 7 | YouTube | — | 同上 | 平台文案为英文，**不影响**（我们只用结构选择器；文本兜底仅中文的场景不适用此处） |
| 8 | Meta 其余（facebook / facebook_page） | 步 3 的 controls 对齐结论 | 复用步 3 的替换 | 与 Instagram 共享 `meta_uploader` |
| 9 | 支付宝 / 百家号 / 微博 / 虎扑 | — | 同构替换，批量提交 | 长尾，收益低但成本低 |
| 10 | 大鱼 / 知乎 / 雪球（文章流） | **25 必须有结论** | 准入条件：先算出「文本上界 × 136ms」与预算表，再动行为层 | 否则迁移后必然点击前超时 |

**每步只改一个平台**（灰度粒度 = 提交/发布）。**已取证的登录/风控规则不得被空规则替换**：某平台在没有真机证据前，保留其现有登录判定（并把结果映射到 `LoginRequiredError`），不允许「`classify` 恒返回 `None`」把登录失效降级成 `exit 1`。

### 每步验收信号（四件套）

1. **离线单测**（细化为 16 的用例）：`humanize` —— 字符分派（ASCII `press` / 中文 `insert_text`）、`sleep` 次数与区间、点击序列 `move → settle → stillOn → down → hold → up`、`stillOn` 失败**无 `down`**、同 seed 可复现、`HUMANIZE=0` 零 sleep；`dom` —— 四档、`ambiguous:N`、`probe-failed` 分档、覆盖层 2 轮上限；`controls` —— `aria-checked` / 原生 checkbox / 读不到三态；`blocked` —— 长前缀优先、`/login` 与 `/website-login` 分流、marker 可见性。
2. **静态断言**：该平台目录内 `fill(` / `el.click()` / `force=True` 计数 = 0；裸 `timeout=` 字面量 = 0（一律 `budget.clamp_*`）；`count()` 只用于「集合基数」。
3. **真机 dry-run（不真实发布）**：`--no-publish` 跑到发布按钮 ARM 就绪 → `exit 0`，保留命中日志与失败截图（截图按 14：`debug` 默认关，验收时显式 `--debug`）。**强制**：小红书 / TikTok / Instagram；其他平台可选。
4. **`HUMANIZE=0` 对照**：同输入再跑一次 dry-run → `exit 0`，并记录两次耗时差（快路径不改变业务结果的证据）。

### 与其它票的接口

- **16**：本票的四件套是测试策略的输入；`humanize` 断言沿用 10 §8，`dom` 需要 `RecordingPage` 支持 `mouse.*` / `insert_text` / `stillOn` 注入失败。
- **13**：`provider_label(mode)` 公开、各平台 `if multilogin:` 门与 “Multilogin” 文案在迁移步内删除（本票不重复决定语义）。
- **03**：`ARM → FIRE → OBSERVE` 的**语义**（先置位再派发、只点一次、点击后不重试）随迁移推广到全平台，但**不抽代码**：ARM 谓词与 OBSERVE 成功判据是平台数据，`Humanizer.click` 的内部零重试是这条语义的执行点。
- **12**：本地会话预检的零网络快路径与 `cookies/*.json` 身份键（`x-user-id-creator`）**不**进共享层，理由是不跨平台通用。
- **25**：文章流平台迁移的硬前置（预算口径 / 文本上界表）。
- **18**：迁移不改变发布节奏与熔断；确定性超时的豁免归 18。
- **17**：把「TikTok / Instagram 补 `--no-publish`」写进 spec 的前置改动清单（它不是 out of scope，是本票验收的依赖）。

### 已知风险

- **收益不可度量**：行为层降低封禁风险是**仅推断**（10 §9），本票不提供任何「迁移后封禁率下降」的断言；验收只证明「没变差」。
- **覆盖层/登录规则的数据缺口**：迁移到新平台时，`BlockedRules` 与 `Overlay` 需真机取证；无证据项留空，**并保留该平台现有实现**，不得用空配置替换（见迁移路线注记）。
- **接口稳定性**：一旦 3 个平台接入，`dom` / `controls` / `blocked` 的签名变更成本变高；步 0 必须先由 16 把 fake 与断言定下来。


## 修订（来自 25，2026-11-11）

- **步 10（大鱼/知乎/雪球）解阻**：25 已决「`Humanizer.type_text` 内部按 1000 字自动分流：≤1000 逐字、>1000 一次 `insert_text`」。文章流前置从「先算出各平台文本上界 × 136ms 与预算表」改为「标题逐字（≤100 字 ≈14s）+ 正文保持现有 HTML 剪贴板粘贴」。**逐平台上界表作废**，改用 25 的「字段 → 路径」分类表。
- **上述 `## Answer` 第 7 条与迁移路线步 10 的「阻塞于 25 / 必须先算文本上界」以此处为准。**
- **静态断言 `fill(` = 0 必须豁免 YouTube `_fill_editable`**（标题与描述都走它，理由见 `youtube_uploader/main.py:238-252`：逐字输入 `#` 会触发话题补全并卡死流程）。豁免形式：唯一 helper + 注释写明原因，16 的断言按白名单核对。
- **文章正文粘贴保持独立**：不与长配文的 `insert_text` 合并成一个 helper（前者为保留富文本结构所必需，后者是行为降级）。

## Comments

- 2026-11-12：`uploader/xhs_uploader/` 已作为独立清理议题删除，同批删除历史 Web（`sau_backend.py`、`sau_frontend/`、`myUtils/` 等）与旧 `examples/` 脚本；记录见 `CHANGELOG.md` 的「移除历史 Web 与旧示例脚本」。`bilibili` 与 `tk_uploader/main.py` 仍按原约定保留。
