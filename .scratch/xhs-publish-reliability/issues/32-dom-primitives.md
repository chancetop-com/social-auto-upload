# 32 — 判定原语：四档角色、hit-test 与覆盖层清障

**What to build:** 一套共享的元素判定原语，回答的不是"页面上有没有这个选择器"，而是"它是不是真的存在、能不能看见、能不能点中、能不能输入"。被浮层挡住时先按已知覆盖层清障，而不是 `force=True` 硬点或摘掉节点。同时提供"页面已经安静下来"的一次性闸门。

**Blocked by:** 28（虚拟时钟与 DOM 夹具）.

Status: resolved

- [x] 四档角色各有明确判据与 reason：`attached`（在 DOM 且 connected，集合基数必须为 1，多义返回 `ambiguous:N` 且禁止 `.first`）、`visible`（自身可见 + 祖先链 display/visibility/opacity 计算样式 + 自身 `aria-hidden`）、`interactive`（在 visible 之上加非 disabled、`pointer-events != none`、真实落点 `elementFromPoint` 命中自身或后代）、`editable`（在 visible 之上加可写）
- [x] 落点默认取包围盒中心；发布按钮取 65% x 处
- [x] 不确定性分档：`visible`/`attached` 探测抛异常 → 放行 + warning；`interactive` 落点探测抛异常 → 阻断（reason `probe-failed`）
- [x] 覆盖层清障最多 2 轮，每步后重新落点：已知覆盖层注册表（数据驱动）→ `Esc` → 再探测；仍未通过则报 `covered-by:<标识>`
- [x] **永不**摘节点、**永不**注入 `display:none`、**永不**点空白；正文字段输入中不清障（已知引导按钮例外）
- [x] 页面就绪：统一 `domcontentloaded` + clamp；首次交互前执行一次 DOM 静默门（连续 500ms 无变更通过，总上限 3s）；未静默只 warning 不失败，且只做一次
- [x] 之后每个动作只等自己的目标，不再有就绪类固定 sleep
- [x] 共享层依赖方向成立：只依赖 patchright、stdlib 与通用错误类型，不 import 平台或命令层
- [x] 契约单测：四档边界、`ambiguous:N`、`probe-failed` 阻断 vs 可见性探测失败放行、两轮上限、静默门 500ms/3s、所有等待实参可收紧

## Comments

### Public API delivered (`utils/dom.py`, `utils/controls.py`)

```python
Role = Literal["attached", "visible", "interactive", "editable"]
ROLES = ("attached", "visible", "interactive", "editable")
KINDS = ("structure", "upstream", "text-zh")

@dataclass(frozen=True)
class Resolved:            # locator, selector, kind, role

@dataclass(frozen=True)
class Candidate:           # selector, kind="structure", role=None,
                           # exact=False, point=None, factory=None
    def build(self, scope): ...

@dataclass(frozen=True)
class OverlayRule:         # selector, action="click"|"click-child"|"esc",
                           # target_selector=None, label=""

async def check(locator, role, *, point=None, publish_clicked=False) -> tuple[bool, str | None]
async def resolve(scope, candidates, *, role="attached", timeout_ms=5000,
                  budget=None, point=None, publish_clicked=False) -> Resolved
async def wait_resolved(scope, candidates, *, role="attached", timeout_ms=5000,
                        budget=None, poll_ms=100, point=None,
                        publish_clicked=False) -> Resolved
async def wait_dom_quiet(page, *, quiet_ms=500, cap_ms=3000, budget=None) -> bool
async def clear_overlays(page, known, *, budget=None) -> None

async def read_switch_state(locator) -> bool | None
```

Reason enums (all strings, stable):

| role | 阻断 reason |
| --- | --- |
| `attached` | `not-attached`, `ambiguous:N` |
| `visible` | `zero-box`, `opacity-zero`, `aria-hidden`（+ 继承自 attached 的两条） |
| `interactive` | `disabled`, `pointer-events-none`, `covered-by:<tag.class\|#id\|text[:40]>`, `probe-failed`（+ visible 的全部） |
| `editable` | `readonly`, `not-contenteditable`, `disabled`（+ visible 的全部） |

放行 + warning（`ok=True` 且第二项非 `None`）：`probe-failed`（attached/visible
探测失败）与 `aria-hidden-ancestor`（祖先 `aria-hidden` 只警告）。
`point` 是**包围盒内比例** `(x, y)`，默认 `(0.5, 0.5)`；发布按钮用 `(0.65, 0.5)`。

### Additive deviations from `notes/interfaces.md` (non-breaking)

1. `interactive` 多一条 reason `pointer-events-none`：spec 的判据里有
   `pointer-events != none`，但 reason 表只列了三条；这里按判据补一条显式
   reason（`covered-by:*` 语义不同，不能混用）。消费方按字符串透传即可。
2. `resolve`/`wait_resolved` 增加 `point=` 与 `publish_clicked=` 关键字参数
   （均有默认值），因为 ticket 38 需要在解析时直接用 65% 落点、失败文案要带
   「可能已发出」。`Candidate` / `OverlayRule` 为新增数据形状。
3. `Resolved`/`Candidate`/`OverlayRule` 为 frozen dataclass。

未修改 `notes/interfaces.md`（在工作区之外，按“不得编辑 worktree 之外”的约束）；
请父会话把上面三条同步进该文件。

### Implementation notes for tickets 33–40

- 覆盖层注册表是**调用方数据**（`OverlayRule` 元组），`utils/dom.py` 里没有任何
  平台选择器。ticket 33 在 `main.py` 里定义 XHS 的三条规则（`.feature-guide__btn`
  → click；`div[role="dialog"]` → click-child；`div.d-popover` → esc）。
- `check`/`resolve` 不写日志：`(True, "<warning>")` 就是 warning 通道，调用方
  负责记 `probe-failed` / `aria-hidden-ancestor` / `dom-not-quiet`。
- `wait_dom_quiet` 只做一次（JS 安装幂等，`window.__sauDomQuietState` 守卫），
  404/导航异常返回 `False`，调用方不得重试。
- 预算按鸭子类型使用（只调 `budget.clamp_ms`），未 import `uploader.*`。
  预算耗尽时 `clamp_ms` 自己抛错，原样上抛。
- `wait_resolved` 在超时后：任一候选出现过非 `not-attached` 的阻断理由 →
  `ElementUnusableError`，否则 `ElementMissingError`。`ambiguous:N` 视为
  unusable（元素在但契约被破坏）。

### Real-device items

- 真机确认覆盖层实际行为（`.feature-guide__btn`、图文 `role="dialog"`、
  `div.d-popover`，以及 2 轮 + Esc 是否足够）：未验证（无真机环境）。
- 真机 `elementFromPoint` 落点（65% x）在发布按钮上的命中：未验证（无真机环境）。

### Tests

`tests/test_xhs_dom.py`（65 例）、`tests/test_xhs_controls.py`（12 例）；
全量 `python -m unittest discover -s tests -t .` → 1202 tests OK（skipped=2）。

## Comments

- **2026-11-12 真机复测补充**：新增 `ensure_in_viewport(page, locator, *, point=None, box=None)`。首屏外的坐标落点会让 `elementFromPoint` 返回 `null`（误判 `covered-by:unknown`），行为层与 ARM 谓词现在都先滚入视口再判定；这是对上游 `ScrollIntoView → humanize.ClickAt` 的等价对齐。
