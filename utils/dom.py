# -*- coding: utf-8 -*-
"""元素判定原语：四档角色、落点命中、覆盖层清障与 DOM 静默门。

这个模块回答的不是「页面上有没有这个选择器」，而是**它是不是真的存在、
能不能看见、能不能点中、能不能输入**。四档角色是累加关系::

    attached  -> 在 DOM 且 connected，集合基数必须为 1
    visible   -> attached + 自身可见 + 祖先链计算样式 + 自身 aria-hidden
    interactive -> visible + 非禁用 + pointer-events + elementFromPoint 命中自身/后代
    editable  -> visible + 可写（input/textarea 或 contenteditable=true）

**返回值约定**（调用方必须据此区分两种不确定）::

    (True, None)                     通过
    (False, "<reason>")              阻断，调用方抛 ElementUnusableError
    (True, "<warning-reason>")       放行 + warning（探测离派发还远）

探测抛异常的处理是**分档**的：``attached``/``visible`` 的探测失败放行并给出
warning（兜底是 Playwright 自身的 actionability）；``interactive`` 的落点
探测失败**阻断**为 ``probe-failed``，否则会被误记成「可能已发布」。

**反例（必须保留）**：空状态没有标题/发布按钮；视频标题框 t=3s 已在，但按钮
t≈12s 才可点 → 「元素出现」不能作为阶段就绪判据，必须按角色判定。

依赖方向（spec §3 U11 B）：只允许 patchright 类型、stdlib 与
``utils.errors``；不 import ``uploader.*`` / ``sau_commands.*`` / 平台常量。
预算对象按鸭子类型使用（``budget.clamp_ms(default_ms)``），不 import。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal, Sequence

Role = Literal["attached", "visible", "interactive", "editable"]

ROLES: tuple[str, ...] = ("attached", "visible", "interactive", "editable")

#: ``Resolved.kind`` 的取值；ticket 33 的文本兜底用 ``text-zh``。
KINDS: tuple[str, ...] = ("structure", "upstream", "text-zh")

WARNING_PROBE_FAILED = "probe-failed"
WARNING_ANCESTOR_ARIA_HIDDEN = "aria-hidden-ancestor"

DEFAULT_RESOLVE_TIMEOUT_MS = 5000
DEFAULT_POLL_MS = 100
DEFAULT_QUIET_MS = 500
DEFAULT_QUIET_CAP_MS = 3000
CLEAR_OVERLAY_SLEEP_MS = 200
CLEAR_OVERLAY_CLICK_TIMEOUT_MS = 2000
MAX_CLEAR_ROUNDS = 2
MAX_OVERLAY_MATCHES = 2


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------


def _click_note(publish_clicked: bool) -> str:
    if publish_clicked:
        return "发布可能已发出（点击已派发）"
    return "未点击发布"


def _tried_note(tried: Sequence[tuple[str, str | None]]) -> str:
    if not tried:
        return "（无候选）"
    return " → ".join(
        f"{selector}({reason or 'ok'})" for selector, reason in tried
    )


class ElementMissingError(RuntimeError):
    """所有候选都没能命中：元素不存在或从未出现。"""

    def __init__(
        self,
        what: str,
        role: str = "attached",
        tried: Sequence[tuple[str, str | None]] = (),
        elapsed_ms: int = 0,
        publish_clicked: bool = False,
    ) -> None:
        self.what = what
        self.role = role
        self.tried = list(tried)
        self.elapsed_ms = int(elapsed_ms)
        self.publish_clicked = bool(publish_clicked)
        super().__init__(
            f"未找到「{what}」（角色 {role}）："
            f"依次尝试 {_tried_note(self.tried)}，耗时 {self.elapsed_ms}ms；"
            f"{_click_note(self.publish_clicked)}。"
        )


class ElementUnusableError(RuntimeError):
    """元素存在但不可用（多义、被遮挡、禁用、不可写……）。"""

    def __init__(
        self,
        what: str,
        role: str = "attached",
        selector: str = "",
        reason: str = "",
        tried: Sequence[tuple[str, str | None]] = (),
        elapsed_ms: int = 0,
        publish_clicked: bool = False,
    ) -> None:
        self.what = what
        self.role = role
        self.selector = selector
        self.reason = reason
        self.tried = list(tried)
        self.elapsed_ms = int(elapsed_ms)
        self.publish_clicked = bool(publish_clicked)
        super().__init__(
            f"找到「{what}」但不可用（角色 {role}）："
            f"{selector} — {reason}；"
            f"依次尝试 {_tried_note(self.tried)}，耗时 {self.elapsed_ms}ms；"
            f"{_click_note(self.publish_clicked)}。"
        )


# ---------------------------------------------------------------------------
# facts probe (one JS round-trip per role check)
# ---------------------------------------------------------------------------


_FACTS_JS = """
el => {
  const own = getComputedStyle(el);
  let display = own.display;
  let visibility = own.visibility;
  let opacity = 1.0;
  let ancestorAriaHidden = false;
  let node = el.parentElement;
  while (node) {
    const style = getComputedStyle(node);
    if (style.display === 'none') { display = 'none'; }
    if (style.visibility === 'hidden' || style.visibility === 'collapse') {
      visibility = 'hidden';
    }
    const ancestorOpacity = parseFloat(style.opacity);
    if (!Number.isNaN(ancestorOpacity)) { opacity *= ancestorOpacity; }
    if (node.getAttribute && node.getAttribute('aria-hidden') === 'true') {
      ancestorAriaHidden = true;
    }
    node = node.parentElement;
  }
  const ownOpacity = parseFloat(own.opacity);
  if (!Number.isNaN(ownOpacity)) { opacity *= ownOpacity; }
  const classes = el.classList ? Array.from(el.classList) : [];
  const hasAttr = (name) => !!(el.hasAttribute && el.hasAttribute(name));
  return {
    tag: (el.tagName || '').toLowerCase(),
    display: display,
    visibility: visibility,
    opacity: opacity,
    ariaHidden: el.getAttribute ? el.getAttribute('aria-hidden') : null,
    ancestorAriaHidden: ancestorAriaHidden,
    disabled: hasAttr('disabled') ||
      (el.getAttribute && el.getAttribute('aria-disabled') === 'true'),
    disabledClass: classes.indexOf('disabled') !== -1,
    pointerEvents: own.pointerEvents,
    contentEditable: el.getAttribute ? el.getAttribute('contenteditable') : null,
    readOnly: hasAttr('readonly'),
    isConnected: el.isConnected !== false,
  };
}
"""

_HIT_TEST_JS = """
(el, point) => {
  const rect = el.getBoundingClientRect();
  const x = rect.left + rect.width * point[0];
  const y = rect.top + rect.height * point[1];
  const hit = document.elementFromPoint(x, y);
  if (!hit) { return null; }
  const text = (hit.innerText || hit.textContent || '').replace(/\\s+/g, ' ').trim();
  return {
    self: hit === el || (el.contains ? el.contains(hit) : false),
    tag: (hit.tagName || '').toLowerCase(),
    className: typeof hit.className === 'string' ? hit.className : '',
    id: hit.id || '',
    text: text.slice(0, 40),
  };
}
"""

_DEFAULT_FACTS: dict[str, Any] = {
    "tag": "",
    "display": "block",
    "visibility": "visible",
    "opacity": 1.0,
    "ariaHidden": None,
    "ancestorAriaHidden": False,
    "disabled": False,
    "disabledClass": False,
    "pointerEvents": "auto",
    "contentEditable": None,
    "readOnly": False,
    "isConnected": True,
}


async def _probe(locator: Any) -> tuple[dict[str, Any] | None, str | None]:
    """读取计算样式与属性；探测失败返回 ``(None, "probe-failed")``。"""
    try:
        raw = await locator.evaluate(_FACTS_JS)
    except Exception:
        return None, WARNING_PROBE_FAILED
    if not isinstance(raw, dict):
        return None, None
    facts = dict(_DEFAULT_FACTS)
    for key in _DEFAULT_FACTS:
        if key in raw:
            facts[key] = raw[key]
    try:
        facts["opacity"] = float(facts["opacity"])
    except (TypeError, ValueError):
        facts["opacity"] = 1.0
    return facts, None


def normalise_point(point: Any) -> tuple[float, float]:
    """落点用**包围盒内的比例**表示：``(0.5, 0.5)`` 是中心，``(0.65, 0.5)`` 是发布按钮。

    ``None`` 表示默认中心落点。共享层只有一个实现，行为层直接 import。
    """
    if point is None:
        return (0.5, 0.5)
    try:
        raw_x, raw_y = point
    except (TypeError, ValueError) as exc:
        raise ValueError("point must be a (x, y) fractional pair") from exc
    x, y = float(raw_x), float(raw_y)
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise ValueError(
            "point is fractional within the bounding box; use 0.0-1.0, "
            f"got ({x}, {y})"
        )
    return x, y


def _describe(hit: dict[str, Any]) -> str:
    """``covered-by:`` 的标识：tag.class → #id → text[:40]。"""
    tag = str(hit.get("tag") or "").strip().lower()
    class_name = hit.get("className")
    if isinstance(class_name, (list, tuple)):
        class_name = " ".join(str(part) for part in class_name)
    class_name = str(class_name or "").strip()
    if class_name:
        first = class_name.split()[0]
        return f"{tag}.{first}" if tag else f".{first}"
    element_id = str(hit.get("id") or "").strip()
    if element_id:
        return f"#{element_id}"
    text = " ".join(str(hit.get("text") or "").split())
    if text:
        return text[:40]
    return tag or "unknown"


# ---------------------------------------------------------------------------
# role checks
# ---------------------------------------------------------------------------


async def _visible(
    locator: Any, facts: dict[str, Any] | None
) -> tuple[bool, str | None, dict[str, Any] | None, str | None]:
    warning: str | None = None
    try:
        visible = await locator.is_visible()
    except Exception:
        visible = None
        warning = WARNING_PROBE_FAILED
    if visible is False:
        return False, "zero-box", facts, warning
    if facts is None:
        facts, probe_warning = await _probe(locator)
        warning = warning or probe_warning
    if facts is not None:
        if facts["display"] == "none":
            return False, "zero-box", facts, warning
        if facts["visibility"] in ("hidden", "collapse"):
            return False, "zero-box", facts, warning
        if facts["opacity"] < 0.1:
            return False, "opacity-zero", facts, warning
        if str(facts["ariaHidden"] or "").strip().lower() == "true":
            return False, "aria-hidden", facts, warning
        if facts["ancestorAriaHidden"]:
            # 祖先 aria-hidden 只做警告：XHS 的浮层容器常常整棵子树标记隐藏。
            warning = warning or WARNING_ANCESTOR_ARIA_HIDDEN
    return True, None, facts, warning


async def _interactive(
    locator: Any,
    facts: dict[str, Any] | None,
    point: tuple[float, float] | None,
    warning: str | None,
) -> tuple[bool, str | None]:
    try:
        enabled = await locator.is_enabled()
    except Exception:
        enabled = None
    if enabled is False:
        return False, "disabled"
    if facts is None:
        facts, probe_warning = await _probe(locator)
        warning = warning or probe_warning
    if facts is not None:
        if facts["disabled"] or facts["disabledClass"]:
            return False, "disabled"
        if str(facts["pointerEvents"] or "").strip().lower() == "none":
            # pointer-events:none 的元素收不到点击；不给新错误类型，按不可点处理。
            return False, "pointer-events-none"

    try:
        box = await locator.bounding_box()
    except Exception:
        return False, WARNING_PROBE_FAILED
    if not box:
        return False, "zero-box"
    if float(box.get("width") or 0) <= 0 or float(box.get("height") or 0) <= 0:
        return False, "zero-box"

    ratio_x, ratio_y = point if point is not None else (0.5, 0.5)
    try:
        hit = await locator.evaluate(_HIT_TEST_JS, [ratio_x, ratio_y])
    except Exception:
        # 落点探测失败必须阻断：放行会被误记成「可能已发布」。
        return False, WARNING_PROBE_FAILED
    if isinstance(hit, dict) and hit.get("self"):
        return True, warning
    if hit is None:
        return False, "covered-by:unknown"
    if not isinstance(hit, dict):
        return False, WARNING_PROBE_FAILED
    return False, f"covered-by:{_describe(hit)}"


async def _editable(
    locator: Any,
    facts: dict[str, Any] | None,
    warning: str | None,
) -> tuple[bool, str | None]:
    try:
        enabled = await locator.is_enabled()
    except Exception:
        enabled = None
    if enabled is False:
        return False, "disabled"
    if facts is None:
        facts, probe_warning = await _probe(locator)
        warning = warning or probe_warning
    if facts is not None and facts["disabled"]:
        return False, "disabled"

    read_only = bool(facts and facts["readOnly"])
    if not read_only:
        try:
            read_only = (await locator.get_attribute("readonly")) is not None
        except Exception:
            read_only = False
    if read_only:
        return False, "readonly"

    tag = str((facts or {}).get("tag") or "").strip().lower()
    if tag in ("input", "textarea"):
        return True, warning

    content_editable = (facts or {}).get("contentEditable")
    if content_editable is None:
        try:
            content_editable = await locator.get_attribute("contenteditable")
        except Exception:
            content_editable = None
    if str(content_editable or "").strip().lower() == "true":
        return True, warning

    if facts is None:
        # 探测失败：放行 + warning（与 visible 同档，离派发还远）。
        return True, warning or WARNING_PROBE_FAILED
    return False, "not-contenteditable"


async def check(
    locator: Any,
    role: Role | str,
    *,
    point: tuple[float, float] | None = None,
) -> tuple[bool, str | None]:
    """判定 ``locator`` 是否满足 ``role``；见模块文档的返回值约定。"""
    if role not in ROLES:
        raise ValueError(f"unknown role: {role!r}; expected one of {ROLES}")
    normalised_point = normalise_point(point)

    warning: str | None = None
    facts: dict[str, Any] | None = None

    # -- attached（所有角色的底座：基数、connected）----------------------
    try:
        count = await locator.count()
    except Exception:
        count = None
    if count is None:
        warning = WARNING_PROBE_FAILED
    elif count == 0:
        return False, "not-attached"
    elif count != 1:
        # 多义永不静默取 .first：调用方必须收窄选择器。
        return False, f"ambiguous:{count}"
    else:
        facts, probe_warning = await _probe(locator)
        warning = warning or probe_warning
        if facts is not None and facts["isConnected"] is False:
            return False, "not-attached"

    if role == "attached":
        return True, warning

    # -- visible ---------------------------------------------------------
    visible, visible_reason, facts, visible_warning = await _visible(locator, facts)
    warning = warning or visible_warning
    if not visible:
        return False, visible_reason
    if role == "visible":
        return True, warning

    # -- interactive / editable -----------------------------------------
    if role == "interactive":
        return await _interactive(locator, facts, normalised_point, warning)
    return await _editable(locator, facts, warning)


# ---------------------------------------------------------------------------
# candidate resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """一个候选锚点：选择器 + 来源类别 + 可选的角色/落点覆盖。

    ``factory`` 用来表达无法用单条 CSS 描述的定位（例如从相邻锚点向上/向下
    遍历）；``upstream`` 就是这种结构兜底，``text-zh`` 走可见文本。
    """

    selector: str
    kind: str = "structure"
    role: Role | str | None = None
    exact: bool = False
    point: tuple[float, float] | None = None
    factory: Callable[[Any], Any] | None = None

    def build(self, scope: Any) -> Any:
        if self.factory is not None:
            return self.factory(scope)
        if self.kind == "text-zh":
            return scope.get_by_text(self.selector, exact=self.exact)
        return scope.locator(self.selector)


@dataclass(frozen=True)
class Resolved:
    """命中的候选：locator 本体 + 选择器 + 来源类别 + 判定角色。"""

    locator: Any
    selector: str
    kind: str
    role: str


def _as_candidates(candidates: Sequence[Any]) -> list[Candidate]:
    result: list[Candidate] = []
    for item in candidates:
        if isinstance(item, Candidate):
            candidate = item
        elif isinstance(item, str):
            candidate = Candidate(item)
        else:
            raise TypeError(f"candidate must be str or Candidate, got {item!r}")
        if candidate.kind not in KINDS:
            raise ValueError(
                f"unknown candidate kind: {candidate.kind!r}; expected {KINDS}"
            )
        result.append(candidate)
    return result


def _clamp_ms(default_ms: int, budget: Any | None) -> int:
    if budget is None:
        return int(default_ms)
    clamp = getattr(budget, "clamp_ms", None)
    if clamp is None:
        raise TypeError("budget must expose clamp_ms(default_ms)")
    return int(clamp(int(default_ms)))


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


async def _attempt(
    candidates: Sequence[Candidate],
    scope: Any,
    role: str,
    point: tuple[float, float] | None,
    publish_clicked: bool,
    started: float,
    limit_ms: int | None,
) -> tuple[Resolved | None, list[tuple[str, str | None]], tuple[str, str] | None]:
    tried: list[tuple[str, str | None]] = []
    blocking: tuple[str, str] | None = None
    for candidate in candidates:
        if limit_ms is not None and tried and _elapsed_ms(started) >= limit_ms:
            break
        locator = candidate.build(scope)
        effective_role = candidate.role or role
        candidate_point = candidate.point if candidate.point is not None else point
        ok, reason = await check(
            locator,
            effective_role,
            point=candidate_point,
        )
        tried.append((candidate.selector, reason))
        if ok:
            return (
                Resolved(
                    locator=locator,
                    selector=candidate.selector,
                    kind=candidate.kind,
                    role=str(effective_role),
                ),
                tried,
                None,
            )
        if reason != "not-attached" and blocking is None:
            blocking = (candidate.selector, reason or "")
    return None, tried, blocking


def _resolve_error(
    scope_candidates: Sequence[Candidate],
    role: str,
    tried: list[tuple[str, str | None]],
    blocking: tuple[str, str] | None,
    elapsed_ms: int,
    publish_clicked: bool,
) -> RuntimeError:
    what = " | ".join(candidate.selector for candidate in scope_candidates)
    if blocking is not None:
        selector, reason = blocking
        return ElementUnusableError(
            what=what,
            role=role,
            selector=selector,
            reason=reason,
            tried=tried,
            elapsed_ms=elapsed_ms,
            publish_clicked=publish_clicked,
        )
    return ElementMissingError(
        what=what,
        role=role,
        tried=tried,
        elapsed_ms=elapsed_ms,
        publish_clicked=publish_clicked,
    )


async def resolve(
    scope: Any,
    candidates: Sequence[Any],
    *,
    role: Role | str = "attached",
    timeout_ms: int = DEFAULT_RESOLVE_TIMEOUT_MS,
    budget: Any | None = None,
    point: tuple[float, float] | None = None,
    publish_clicked: bool = False,
) -> Resolved:
    """单趟解析：按候选顺序取第一个满足 ``role`` 的命中，不等待。"""
    if role not in ROLES:
        raise ValueError(f"unknown role: {role!r}; expected one of {ROLES}")
    prepared = _as_candidates(candidates)
    started = time.monotonic()
    limit_ms = _clamp_ms(timeout_ms, budget)
    resolved, tried, blocking = await _attempt(
        prepared, scope, str(role), point, publish_clicked, started, limit_ms
    )
    if resolved is not None:
        return resolved
    raise _resolve_error(
        prepared, str(role), tried, blocking, _elapsed_ms(started), publish_clicked
    )


async def wait_resolved(
    scope: Any,
    candidates: Sequence[Any],
    *,
    role: Role | str = "attached",
    timeout_ms: int = DEFAULT_RESOLVE_TIMEOUT_MS,
    budget: Any | None = None,
    poll_ms: int = DEFAULT_POLL_MS,
    point: tuple[float, float] | None = None,
    publish_clicked: bool = False,
) -> Resolved:
    """轮询解析：在 ``timeout_ms`` 内等待任一候选首次满足 ``role``。"""
    if role not in ROLES:
        raise ValueError(f"unknown role: {role!r}; expected one of {ROLES}")
    prepared = _as_candidates(candidates)
    limit_ms = _clamp_ms(timeout_ms, budget)
    started = time.monotonic()
    last_tried: list[tuple[str, str | None]] = []
    last_blocking: tuple[str, str] | None = None
    while True:
        resolved, tried, blocking = await _attempt(
            prepared, scope, str(role), point, publish_clicked, started, None
        )
        last_tried = tried
        if resolved is not None:
            return resolved
        if blocking is not None:
            last_blocking = blocking
        elapsed_ms = _elapsed_ms(started)
        remaining_ms = limit_ms - elapsed_ms
        if remaining_ms <= 0:
            raise _resolve_error(
                prepared,
                str(role),
                last_tried,
                last_blocking,
                elapsed_ms,
                publish_clicked,
            )
        sleep_ms = _clamp_ms(int(min(poll_ms, remaining_ms)), budget)
        await asyncio.sleep(sleep_ms / 1000.0)


# ---------------------------------------------------------------------------
# DOM quiet gate
# ---------------------------------------------------------------------------


_INSTALL_QUIET_JS = """
() => {
  if (window.__sauDomQuietState) { return true; }
  const state = { last: performance.now(), count: 0 };
  window.__sauDomQuietState = state;
  const root = document.documentElement || document;
  const observer = new MutationObserver(() => {
    state.last = performance.now();
    state.count += 1;
  });
  observer.observe(root, {
    childList: true,
    attributes: true,
    characterData: true,
    subtree: true,
  });
  window.__sauDomQuietObserver = observer;
  return true;
}
"""

_READ_QUIET_JS = """
() => {
  const state = window.__sauDomQuietState;
  if (!state) { return null; }
  return { since: performance.now() - state.last, count: state.count };
}
"""

_DISCONNECT_QUIET_JS = """
() => {
  const observer = window.__sauDomQuietObserver;
  if (observer) { observer.disconnect(); }
  window.__sauDomQuietObserver = null;
  return true;
}
"""


async def wait_dom_quiet(
    page: Any,
    *,
    quiet_ms: int = DEFAULT_QUIET_MS,
    cap_ms: int = DEFAULT_QUIET_CAP_MS,
    budget: Any | None = None,
) -> bool:
    """一次性 DOM 静默门：连续 ``quiet_ms`` 无变更 → True。

    总上限 ``cap_ms``；未静默返回 False（调用方只记 ``dom-not-quiet`` warning，
    不失败）。安装用 ``MutationObserver``（childList + attributes +
    characterData，subtree），本函数只负责一次判定，不做重试。
    """
    quiet_ms = _clamp_ms(quiet_ms, budget)
    cap_ms = _clamp_ms(cap_ms, budget)
    started = time.monotonic()
    try:
        await page.evaluate(_INSTALL_QUIET_JS)
    except Exception:
        return False
    try:
        while True:
            try:
                state = await page.evaluate(_READ_QUIET_JS)
            except Exception:
                return False
            if isinstance(state, dict):
                since = state.get("since")
                if isinstance(since, (int, float)) and since >= quiet_ms:
                    return True
            elapsed_ms = _elapsed_ms(started)
            if elapsed_ms >= cap_ms:
                return False
            remaining_ms = cap_ms - elapsed_ms
            sleep_ms = _clamp_ms(int(min(DEFAULT_POLL_MS, remaining_ms)), budget)
            await asyncio.sleep(sleep_ms / 1000.0)
    finally:
        try:
            await page.evaluate(_DISCONNECT_QUIET_JS)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# overlay clearing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OverlayRule:
    """已知覆盖层：数据驱动，模块本身不含任何平台选择器。

    ``action``:

    * ``click``       —— 点覆盖层自身（例如「我知道了」引导按钮）；
    * ``click-child`` —— 点覆盖层内部的目标（弹窗确认/关闭），失败退化为 Esc；
    * ``esc``         —— 按 Esc 关闭（popover）。
    """

    selector: str
    action: str = "click"
    target_selector: str | None = None
    label: str = ""

    def __post_init__(self) -> None:
        if self.action not in ("click", "click-child", "esc"):
            raise ValueError(
                f"unknown overlay action: {self.action!r}; "
                "expected 'click', 'click-child' or 'esc'"
            )


def _locate(page: Any, selector: str) -> Any | None:
    try:
        return page.locator(selector)
    except Exception:
        return None


async def _is_visible(node: Any) -> bool:
    try:
        return bool(await node.is_visible())
    except Exception:
        return False


async def _press_escape(page: Any) -> bool:
    keyboard = getattr(page, "keyboard", None)
    if keyboard is None:
        return False
    try:
        await keyboard.press("Escape")
        return True
    except Exception:
        return False


async def _safe_click(locator: Any, budget: Any | None) -> bool:
    try:
        await locator.click(
            timeout=_clamp_ms(CLEAR_OVERLAY_CLICK_TIMEOUT_MS, budget)
        )
        return True
    except Exception:
        return False


async def _apply_overlay_rule(
    page: Any, node: Any, rule: OverlayRule, budget: Any | None
) -> bool:
    if rule.action == "esc":
        return await _press_escape(page)
    if rule.action == "click-child" and rule.target_selector:
        try:
            child = node.locator(rule.target_selector)
            if await child.count() > 0:
                return await _safe_click(child, budget)
        except Exception:
            pass
        return await _press_escape(page)
    return await _safe_click(node, budget)


async def _clear_round(
    page: Any, known: Sequence[OverlayRule], budget: Any | None
) -> tuple[bool, bool]:
    acted = False
    pressed_escape = False
    for rule in known:
        locator = _locate(page, rule.selector)
        if locator is None:
            continue
        try:
            count = await locator.count()
        except Exception:
            continue
        if count <= 0:
            continue
        matches = min(int(count), MAX_OVERLAY_MATCHES)
        for index in range(matches):
            node = locator if count == 1 else locator.nth(index)
            if not await _is_visible(node):
                continue
            if not await _apply_overlay_rule(page, node, rule, budget):
                continue
            acted = True
            if rule.action == "esc":
                pressed_escape = True
            await asyncio.sleep(
                _clamp_ms(CLEAR_OVERLAY_SLEEP_MS, budget) / 1000.0
            )
    return acted, pressed_escape


async def clear_overlays(
    page: Any,
    known: Sequence[OverlayRule],
    *,
    budget: Any | None = None,
) -> None:
    """按已知覆盖层注册表清障，最多 2 轮，轮间按 Esc。

    只做「点击已知节点 / 按 Esc」两件事：**永不**摘节点、**永不**注入
    ``display:none``、**永不**点空白区域。调用方在每次调用后重新落点判定，
    仍未通过则报 ``ElementUnusableError(reason="covered-by:…")``。
    """
    for round_index in range(MAX_CLEAR_ROUNDS):
        acted, pressed_escape = await _clear_round(page, known, budget)
        if not acted:
            return
        if round_index + 1 >= MAX_CLEAR_ROUNDS:
            return
        if not pressed_escape:
            await _press_escape(page)
            await asyncio.sleep(
                _clamp_ms(CLEAR_OVERLAY_SLEEP_MS, budget) / 1000.0
            )


__all__ = [
    "Candidate",
    "CLEAR_OVERLAY_CLICK_TIMEOUT_MS",
    "CLEAR_OVERLAY_SLEEP_MS",
    "DEFAULT_POLL_MS",
    "DEFAULT_QUIET_CAP_MS",
    "DEFAULT_QUIET_MS",
    "DEFAULT_RESOLVE_TIMEOUT_MS",
    "ElementMissingError",
    "ElementUnusableError",
    "KINDS",
    "MAX_CLEAR_ROUNDS",
    "OverlayRule",
    "Resolved",
    "ROLES",
    "Role",
    "check",
    "clear_overlays",
    "normalise_point",
    "resolve",
    "wait_dom_quiet",
    "wait_resolved",
]
