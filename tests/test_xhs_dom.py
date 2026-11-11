# -*- coding: utf-8 -*-
"""Contract tests for ``utils/dom.py`` (ticket 32).

The four roles are cumulative: ``visible`` implies ``attached``,
``interactive`` implies ``visible``, ``editable`` implies ``visible``.  Every
test below pins one boundary of that ladder, plus the two failure channels:

* blocked -> ``(False, reason)`` and the caller raises ``ElementUnusableError``;
* allowed-with-warning -> ``(True, warning_reason)`` (probe far from dispatch).

Fakes come from ticket 28 (``tests/fakes_xhs_dom.py`` / ``fakes_clock.py``),
so nothing here touches a browser or the wall clock.
"""

from __future__ import annotations

import ast
import pathlib
import unittest

from tests.fakes_clock import FakeClock
from tests.fakes_xhs_dom import FakeLocator, RecordingPage

from utils import controls, dom
from utils.dom import (
    Candidate,
    ElementMissingError,
    ElementUnusableError,
    OverlayRule,
    Resolved,
    check,
    clear_overlays,
    resolve,
    wait_dom_quiet,
    wait_resolved,
)

DEFAULT_BOX = {"x": 0.0, "y": 0.0, "width": 100.0, "height": 40.0}


def styles(**overrides):
    """A complete computed-style fact dict, with per-test overrides."""
    data = {
        "tag": "div",
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
    data.update(overrides)
    return data


class StrictLocator(FakeLocator):
    """Locator that fails loudly if the primitive quietly takes ``.first``."""

    @property
    def first(self):  # pragma: no cover - only fails when the bug exists
        raise AssertionError("utils.dom must never silently take .first")

    @property
    def last(self):  # pragma: no cover - only fails when the bug exists
        raise AssertionError("utils.dom must never silently take .last")


def scripted(
    *,
    style=None,
    hit=None,
    hit_error=None,
    box=DEFAULT_BOX,
    name="target",
    **kwargs,
):
    """Build a ``StrictLocator`` with the two DOM probes scripted.

    ``style`` answers the computed-style probe, ``hit`` the ``elementFromPoint``
    probe.  Every probe call is kept on ``loc.probe_calls``.
    """
    calls = []

    def handler(expression, arg):
        calls.append((expression, arg))
        if "elementFromPoint" in expression:
            if hit_error is not None:
                raise hit_error
            return hit
        return style

    loc = StrictLocator(
        name, evaluate_handler=handler, box=dict(box) if box else box, **kwargs
    )
    loc.probe_calls = calls
    return loc


def hit_call_arg(locator):
    for expression, arg in locator.probe_calls:
        if "elementFromPoint" in expression:
            return arg
    raise AssertionError("no hit-test probe ran")


class BrokenCountLocator(StrictLocator):
    async def count(self):
        raise TimeoutError("count() probe failed")


class BrokenVisibleLocator(StrictLocator):
    async def is_visible(self):
        raise TimeoutError("is_visible() probe failed")


class FakeScope:
    """Minimal locator factory for ``resolve``/``wait_resolved``."""

    def __init__(self, locators, texts=None):
        self._locators = dict(locators)
        self._texts = dict(texts or {})

    def locator(self, selector):
        return self._locators[selector]

    def get_by_text(self, text, exact=False):
        return self._texts[(text, exact)]


class SpyBudget:
    """Duck-typed budget: records every default, optionally caps it."""

    def __init__(self, cap_ms=None):
        self.cap_ms = cap_ms
        self.calls = []

    def clamp_ms(self, default_ms):
        self.calls.append(default_ms)
        if self.cap_ms is None:
            return default_ms
        return min(default_ms, self.cap_ms)


# ---------------------------------------------------------------------------
# attached
# ---------------------------------------------------------------------------


class Decision06ReadinessAttachedTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_connected_element_is_attached(self):
        loc = scripted(style=styles())
        self.assertEqual(await check(loc, "attached"), (True, None))

    async def test_absent_element_is_not_attached(self):
        loc = scripted(count=0, style=styles())
        self.assertEqual(await check(loc, "attached"), (False, "not-attached"))

    async def test_multiple_matches_report_ambiguous_without_first(self):
        loc = scripted(count=3, style=styles())
        self.assertEqual(await check(loc, "attached"), (False, "ambiguous:3"))

    async def test_probe_exception_is_allowed_with_warning(self):
        loc = BrokenCountLocator("broken")
        ok, reason = await check(loc, "attached")
        self.assertTrue(ok)
        self.assertEqual(reason, "probe-failed")

    async def test_disconnected_element_is_not_attached(self):
        loc = scripted(style=styles(isConnected=False))
        self.assertEqual(await check(loc, "attached"), (False, "not-attached"))

    async def test_unknown_role_is_a_usage_error(self):
        loc = scripted(style=styles())
        with self.assertRaises(ValueError):
            await check(loc, "clickable")


# ---------------------------------------------------------------------------
# visible
# ---------------------------------------------------------------------------


class Decision06ReadinessVisibleTests(unittest.IsolatedAsyncioTestCase):
    async def test_invisible_element_reports_zero_box(self):
        loc = scripted(visible=False, style=styles())
        self.assertEqual(await check(loc, "visible"), (False, "zero-box"))

    async def test_display_none_reports_zero_box(self):
        loc = scripted(style=styles(display="none"))
        self.assertEqual(await check(loc, "visible"), (False, "zero-box"))

    async def test_visibility_hidden_reports_zero_box(self):
        loc = scripted(style=styles(visibility="hidden"))
        self.assertEqual(await check(loc, "visible"), (False, "zero-box"))

    async def test_opacity_below_threshold_reports_opacity_zero(self):
        loc = scripted(style=styles(opacity=0.05))
        self.assertEqual(await check(loc, "visible"), (False, "opacity-zero"))

    async def test_opacity_at_threshold_is_visible(self):
        loc = scripted(style=styles(opacity=0.1))
        self.assertEqual(await check(loc, "visible"), (True, None))

    async def test_own_aria_hidden_blocks(self):
        loc = scripted(style=styles(ariaHidden="true"))
        self.assertEqual(await check(loc, "visible"), (False, "aria-hidden"))

    async def test_ancestor_aria_hidden_is_warning_only(self):
        loc = scripted(style=styles(ancestorAriaHidden=True))
        ok, reason = await check(loc, "visible")
        self.assertTrue(ok)
        self.assertEqual(reason, "aria-hidden-ancestor")

    async def test_visibility_probe_exception_is_allowed_with_warning(self):
        loc = BrokenVisibleLocator("broken", evaluate_handler=lambda e, a: styles())
        ok, reason = await check(loc, "visible")
        self.assertTrue(ok)
        self.assertEqual(reason, "probe-failed")

    async def test_ambiguous_element_blocks_visible(self):
        loc = scripted(count=2, style=styles())
        self.assertEqual(await check(loc, "visible"), (False, "ambiguous:2"))


# ---------------------------------------------------------------------------
# interactive
# ---------------------------------------------------------------------------


class Decision06ReadinessInteractiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_element_blocks(self):
        loc = scripted(enabled=False, style=styles(), hit={"self": True, "tag": "button"})
        self.assertEqual(await check(loc, "interactive"), (False, "disabled"))

    async def test_aria_disabled_blocks(self):
        loc = scripted(style=styles(disabled=True), hit={"self": True, "tag": "button"})
        self.assertEqual(await check(loc, "interactive"), (False, "disabled"))

    async def test_disabled_class_token_blocks(self):
        loc = scripted(style=styles(disabledClass=True), hit={"self": True, "tag": "button"})
        self.assertEqual(await check(loc, "interactive"), (False, "disabled"))

    async def test_pointer_events_none_blocks(self):
        loc = scripted(style=styles(pointerEvents="none"), hit={"self": True, "tag": "button"})
        self.assertEqual(await check(loc, "interactive"), (False, "pointer-events-none"))

    async def test_hit_test_on_self_passes(self):
        loc = scripted(style=styles(), hit={"self": True, "tag": "button"})
        self.assertEqual(await check(loc, "interactive"), (True, None))

    async def test_hit_test_on_descendant_passes(self):
        loc = scripted(style=styles(), hit={"self": True, "tag": "span"})
        self.assertEqual(await check(loc, "interactive"), (True, None))

    async def test_hit_test_on_other_element_reports_covered_by_class(self):
        loc = scripted(
            style=styles(),
            hit={"self": False, "tag": "div", "className": "mask-layer fade"},
        )
        self.assertEqual(
            await check(loc, "interactive"), (False, "covered-by:div.mask-layer")
        )

    async def test_covered_by_prefers_id_when_no_class(self):
        loc = scripted(style=styles(), hit={"self": False, "tag": "div", "id": "mask"})
        self.assertEqual(
            await check(loc, "interactive"), (False, "covered-by:#mask")
        )

    async def test_covered_by_falls_back_to_text(self):
        loc = scripted(
            style=styles(),
            hit={"self": False, "tag": "div", "text": "图片可以编辑啦，点击查看"},
        )
        self.assertEqual(
            await check(loc, "interactive"),
            (False, "covered-by:图片可以编辑啦，点击查看"),
        )

    async def test_hit_test_exception_blocks_with_probe_failed(self):
        loc = scripted(style=styles(), hit_error=TimeoutError("hit test failed"))
        ok, reason = await check(loc, "interactive")
        self.assertFalse(ok)
        self.assertEqual(reason, "probe-failed")

    async def test_missing_box_reports_zero_box(self):
        loc = scripted(style=styles(), hit={"self": True}, box=None)
        self.assertEqual(await check(loc, "interactive"), (False, "zero-box"))

    async def test_default_point_is_box_centre(self):
        loc = scripted(style=styles(), hit={"self": True})
        self.assertTrue((await check(loc, "interactive"))[0])
        self.assertEqual(hit_call_arg(loc), [0.5, 0.5])

    async def test_publish_point_uses_65_percent_x(self):
        loc = scripted(style=styles(), hit={"self": True})
        self.assertTrue((await check(loc, "interactive", point=(0.65, 0.5)))[0])
        self.assertEqual(hit_call_arg(loc), [0.65, 0.5])

    async def test_out_of_range_point_is_rejected(self):
        loc = scripted(style=styles(), hit={"self": True})
        with self.assertRaises(ValueError):
            await check(loc, "interactive", point=(120.0, 20.0))

    async def test_visibility_failure_short_circuits_before_hit_test(self):
        loc = scripted(style=styles(opacity=0.02), hit={"self": True})
        self.assertEqual(await check(loc, "interactive"), (False, "opacity-zero"))
        with self.assertRaises(AssertionError):
            hit_call_arg(loc)


# ---------------------------------------------------------------------------
# editable
# ---------------------------------------------------------------------------


class Decision06ReadinessEditableTests(unittest.IsolatedAsyncioTestCase):
    async def test_writable_input_is_editable(self):
        loc = scripted(style=styles(tag="input"))
        self.assertEqual(await check(loc, "editable"), (True, None))

    async def test_contenteditable_textbox_is_editable(self):
        loc = scripted(style=styles(contentEditable="true"))
        self.assertEqual(await check(loc, "editable"), (True, None))

    async def test_readonly_attribute_blocks(self):
        loc = scripted(style=styles(tag="input", readOnly=True))
        self.assertEqual(await check(loc, "editable"), (False, "readonly"))

    async def test_readonly_dom_attribute_blocks_without_facts(self):
        loc = scripted(style=None, attributes={"readonly": ""})
        self.assertEqual(await check(loc, "editable"), (False, "readonly"))

    async def test_plain_div_reports_not_contenteditable(self):
        loc = scripted(style=styles(contentEditable=None))
        self.assertEqual(
            await check(loc, "editable"), (False, "not-contenteditable")
        )

    async def test_disabled_editable_blocks(self):
        loc = scripted(style=styles(tag="textarea"), enabled=False)
        self.assertEqual(await check(loc, "editable"), (False, "disabled"))

    async def test_hidden_editable_blocks_with_visibility_reason(self):
        loc = scripted(style=styles(tag="input", display="none"))
        self.assertEqual(await check(loc, "editable"), (False, "zero-box"))


# ---------------------------------------------------------------------------
# resolve / wait_resolved
# ---------------------------------------------------------------------------


class Decision06ReadinessResolveTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_returns_first_candidate_with_kind(self):
        hit = scripted(name="#real")
        scope = FakeScope({"#first": scripted(count=0), "#real": hit})
        resolved = await resolve(scope, ["#first", "#real"])
        self.assertIsInstance(resolved, Resolved)
        self.assertIs(resolved.locator, hit)
        self.assertEqual(resolved.selector, "#real")
        self.assertEqual(resolved.kind, "structure")
        self.assertEqual(resolved.role, "attached")

    async def test_resolve_skips_absent_candidate(self):
        hit = scripted(name="#b")
        scope = FakeScope({"#a": scripted(count=0), "#b": hit})
        resolved = await resolve(scope, ["#a", "#b"], role="visible")
        self.assertEqual(resolved.selector, "#b")
        self.assertEqual(resolved.role, "visible")

    async def test_resolve_text_zh_uses_get_by_text(self):
        zh = scripted(name="发布")
        scope = FakeScope({}, texts={("发布", False): zh})
        resolved = await resolve(
            scope, [Candidate("发布", kind="text-zh")]
        )
        self.assertIs(resolved.locator, zh)
        self.assertEqual(resolved.kind, "text-zh")

    async def test_resolve_upstream_uses_factory(self):
        upstream = scripted(name="upstream")
        seen = []
        scope = FakeScope({})

        def factory(passed_scope):
            seen.append(passed_scope)
            return upstream

        resolved = await resolve(
            scope,
            [Candidate("anchor-row", kind="upstream", factory=factory)],
        )
        self.assertIs(resolved.locator, upstream)
        self.assertEqual(resolved.kind, "upstream")
        self.assertEqual(seen, [scope])

    async def test_resolve_missing_raises_with_tried_order(self):
        scope = FakeScope({"#a": scripted(count=0), "#b": scripted(count=0)})
        with self.assertRaises(ElementMissingError) as ctx:
            await resolve(scope, ["#a", "#b"])
        error = ctx.exception
        self.assertEqual(error.role, "attached")
        self.assertEqual([entry[0] for entry in error.tried], ["#a", "#b"])
        message = str(error)
        self.assertLess(message.index("#a"), message.index("#b"))
        self.assertIn("未点击发布", message)

    async def test_resolve_ambiguous_raises_unusable(self):
        scope = FakeScope({"#a": scripted(count=4)})
        with self.assertRaises(ElementUnusableError) as ctx:
            await resolve(scope, ["#a"])
        self.assertEqual(ctx.exception.reason, "ambiguous:4")
        self.assertEqual(ctx.exception.selector, "#a")

    async def test_resolve_covered_raises_unusable_with_reason(self):
        covered = scripted(
            style=styles(),
            hit={"self": False, "tag": "div", "className": "guide-mask"},
        )
        scope = FakeScope({"#btn": covered})
        with self.assertRaises(ElementUnusableError) as ctx:
            await resolve(scope, ["#btn"], role="interactive")
        self.assertEqual(ctx.exception.reason, "covered-by:div.guide-mask")
        self.assertEqual(ctx.exception.role, "interactive")

    async def test_publish_clicked_wording_changes_only_text(self):
        scope = FakeScope({"#btn": scripted(count=0)})
        with self.assertRaises(ElementMissingError) as ctx:
            await resolve(scope, ["#btn"], publish_clicked=True)
        self.assertTrue(ctx.exception.publish_clicked)
        self.assertIn("发布可能已发出", str(ctx.exception))


class LateLocator(StrictLocator):
    def __init__(self, clock, appear_at, **kwargs):
        super().__init__("late", **kwargs)
        self._clock = clock
        self._appear_at = appear_at

    async def count(self):
        return 1 if self._clock.now >= self._appear_at else 0


class Decision06ReadinessWaitTests(unittest.IsolatedAsyncioTestCase):
    async def test_polls_until_element_appears_on_virtual_clock(self):
        clock = FakeClock(start=100.0)
        scope = FakeScope({"#late": LateLocator(clock, appear_at=101.2)})
        with clock.patch(dom):
            resolved = await wait_resolved(scope, ["#late"], timeout_ms=3000)
        self.assertEqual(resolved.selector, "#late")
        self.assertGreaterEqual(clock.now - 100.0, 1.2)
        self.assertLess(clock.now - 100.0, 1.5)
        self.assertTrue(all(seconds == 0.1 for seconds in clock.sleep_calls))

    async def test_timeout_raises_missing_with_elapsed(self):
        clock = FakeClock()
        scope = FakeScope({"#never": scripted(count=0)})
        with clock.patch(dom):
            with self.assertRaises(ElementMissingError) as ctx:
                await wait_resolved(scope, ["#never"], timeout_ms=500)
        error = ctx.exception
        self.assertGreaterEqual(error.elapsed_ms, 500)
        self.assertLessEqual(clock.now, 0.7)

    async def test_every_wait_is_clamped_by_budget(self):
        clock = FakeClock()
        budget = SpyBudget(cap_ms=260)
        scope = FakeScope({"#never": scripted(count=0)})
        with clock.patch(dom):
            with self.assertRaises(ElementMissingError):
                await wait_resolved(
                    scope, ["#never"], timeout_ms=5000, budget=budget
                )
        self.assertIn(5000, budget.calls)
        self.assertIn(dom.DEFAULT_POLL_MS, budget.calls)
        self.assertLessEqual(clock.now * 1000, 300)


# ---------------------------------------------------------------------------
# DOM quiet gate
# ---------------------------------------------------------------------------


class QuietPage(RecordingPage):
    """RecordingPage whose quiet probes are scripted via ``since`` values."""

    def __init__(self, since_values=None, *, install_error=None, **kwargs):
        super().__init__(**kwargs)
        self._since_values = list(since_values or [])
        self._install_error = install_error
        self.install_calls = 0
        self.read_calls = 0
        self.disconnect_calls = 0

    async def evaluate(self, expression, arg=None):
        self.evaluate_calls.append((expression, arg))
        text = expression if isinstance(expression, str) else ""
        if "MutationObserver" in text:
            self.install_calls += 1
            if self._install_error is not None:
                raise self._install_error
            return True
        if "__sauDomQuietState" in text:
            self.read_calls += 1
            value = self._since_values.pop(0) if self._since_values else 0
            return {"since": value, "count": self.read_calls}
        if "observer.disconnect" in text:
            self.disconnect_calls += 1
            return True
        raise AssertionError(f"un-scripted page.evaluate({text!r})")


class Decision06ReadinessQuietTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_true_after_500ms_without_changes(self):
        clock = FakeClock()
        page = QuietPage([120, 520])
        with clock.patch(dom):
            quiet = await wait_dom_quiet(page)
        self.assertTrue(quiet)
        self.assertEqual(page.install_calls, 1)
        self.assertEqual(page.disconnect_calls, 1)
        self.assertLess(sum(clock.sleep_calls) * 1000, 1000)

    async def test_caps_at_3000ms_and_returns_false(self):
        clock = FakeClock()
        page = QuietPage(since_values=[0] * 100)
        with clock.patch(dom):
            quiet = await wait_dom_quiet(page)
        self.assertFalse(quiet)
        self.assertLessEqual(round(sum(clock.sleep_calls) * 1000), 3000)
        self.assertGreaterEqual(round(sum(clock.sleep_calls) * 1000), 2900)
        self.assertEqual(page.disconnect_calls, 1)

    async def test_install_js_observes_the_required_mutations(self):
        clock = FakeClock()
        page = QuietPage([520])
        with clock.patch(dom):
            await wait_dom_quiet(page)
        install = page.evaluate_calls[0][0]
        for needle in (
            "MutationObserver",
            "childList: true",
            "attributes: true",
            "characterData: true",
            "subtree: true",
            "__sauDomQuietState",
        ):
            self.assertIn(needle, install)

    async def test_install_is_idempotent(self):
        clock = FakeClock()
        page = QuietPage([520])
        with clock.patch(dom):
            await wait_dom_quiet(page)
            await wait_dom_quiet(page)
        install = page.evaluate_calls[0][0]
        self.assertIn("if (window.__sauDomQuietState)", install)

    async def test_budget_clamps_quiet_window_and_cap(self):
        clock = FakeClock()
        budget = SpyBudget(cap_ms=200)
        page = QuietPage([260])
        with clock.patch(dom):
            quiet = await wait_dom_quiet(page, budget=budget)
        # 260ms of silence passes because quiet_ms was clamped to 200ms.
        self.assertTrue(quiet)
        self.assertIn(dom.DEFAULT_QUIET_MS, budget.calls)
        self.assertIn(dom.DEFAULT_QUIET_CAP_MS, budget.calls)

    async def test_cap_is_clamped_to_budget(self):
        clock = FakeClock()
        budget = SpyBudget(cap_ms=700)
        page = QuietPage(since_values=[0] * 100)
        with clock.patch(dom):
            quiet = await wait_dom_quiet(page, budget=budget)
        self.assertFalse(quiet)
        self.assertLessEqual(round(sum(clock.sleep_calls) * 1000), 700)
        self.assertIn(dom.DEFAULT_QUIET_CAP_MS, budget.calls)

    async def test_probe_error_returns_false_without_raising(self):
        clock = FakeClock()
        page = QuietPage(install_error=RuntimeError("navigated away"))
        with clock.patch(dom):
            quiet = await wait_dom_quiet(page)
        self.assertFalse(quiet)


# ---------------------------------------------------------------------------
# overlay clearing
# ---------------------------------------------------------------------------


class Decision06ReadinessOverlayTests(unittest.IsolatedAsyncioTestCase):
    def _page(self, selectors):
        return RecordingPage(selectors=selectors)

    async def test_known_overlay_is_clicked_at_most_two_rounds(self):
        clock = FakeClock()
        guide = scripted(name="guide", count=1, visible=True)
        page = self._page({".feature-guide__btn": guide})
        with clock.patch(dom):
            await clear_overlays(
                page, [OverlayRule(".feature-guide__btn", action="click")]
            )
        self.assertEqual(guide.click_count, 2)
        presses = [a for a in page.keyboard.actions if a[0] == "press"]
        self.assertEqual(presses, [("press", "Escape")])
        self.assertEqual(clock.sleep_calls, [0.2, 0.2, 0.2])

    async def test_dialog_child_is_clicked(self):
        clock = FakeClock()
        confirm = scripted(name="confirm")
        dialog = scripted(
            name="dialog", count=1, visible=True, children={"button.confirm": confirm}
        )
        page = self._page({'div[role="dialog"]': dialog})
        with clock.patch(dom):
            await clear_overlays(
                page,
                [
                    OverlayRule(
                        'div[role="dialog"]',
                        action="click-child",
                        target_selector="button.confirm",
                    )
                ],
            )
        self.assertEqual(confirm.click_count, 2)

    async def test_esc_rule_presses_escape(self):
        clock = FakeClock()
        popover = scripted(name="popover", count=1, visible=True)
        page = self._page({"div.d-popover": popover})
        with clock.patch(dom):
            await clear_overlays(
                page, [OverlayRule("div.d-popover", action="esc")]
            )
        presses = [a for a in page.keyboard.actions if a[0] == "press"]
        self.assertEqual(presses, [("press", "Escape"), ("press", "Escape")])

    async def test_nothing_present_does_nothing(self):
        clock = FakeClock()
        page = self._page({".feature-guide__btn": scripted(count=0)})
        with clock.patch(dom):
            await clear_overlays(
                page, [OverlayRule(".feature-guide__btn", action="click")]
            )
        self.assertEqual(page.keyboard.actions, [])
        self.assertEqual(clock.sleep_calls, [])

    async def test_never_removes_nodes_or_clicks_blank_area(self):
        clock = FakeClock()
        guide = scripted(name="guide", count=1, visible=True)
        page = self._page({".feature-guide__btn": guide})
        with clock.patch(dom):
            await clear_overlays(
                page,
                [
                    OverlayRule(".feature-guide__btn", action="click"),
                    OverlayRule("div.d-popover", action="esc"),
                ],
            )
        # No DOM injection at all: no display:none, no node removal, no blank click.
        self.assertEqual(page.evaluate_calls, [])
        self.assertEqual(page.mouse.down_count, 0)
        self.assertEqual(page.mouse.actions, [])

    async def test_hidden_overlay_is_skipped(self):
        clock = FakeClock()
        guide = scripted(name="guide", count=1, visible=False)
        page = self._page({".feature-guide__btn": guide})
        with clock.patch(dom):
            await clear_overlays(
                page, [OverlayRule(".feature-guide__btn", action="click")]
            )
        self.assertEqual(guide.click_count, 0)
        self.assertEqual(clock.sleep_calls, [])

    async def test_all_overlay_waits_are_clamped(self):
        clock = FakeClock()
        budget = SpyBudget(cap_ms=50)
        guide = scripted(name="guide", count=1, visible=True)
        page = self._page({".feature-guide__btn": guide})
        with clock.patch(dom):
            await clear_overlays(
                page,
                [OverlayRule(".feature-guide__btn", action="click")],
                budget=budget,
            )
        self.assertIn(dom.CLEAR_OVERLAY_SLEEP_MS, budget.calls)
        self.assertIn(dom.CLEAR_OVERLAY_CLICK_TIMEOUT_MS, budget.calls)
        self.assertTrue(all(ms == 0.05 for ms in clock.sleep_calls))
        self.assertEqual(guide.click_calls[0]["timeout"], 50)


# ---------------------------------------------------------------------------
# shared-layer boundaries
# ---------------------------------------------------------------------------


class Decision06ReadinessSharedLayerTests(unittest.TestCase):
    def test_no_platform_imports(self):
        forbidden = ("uploader", "sau_commands", "sau_cli", "conf")
        for module in (dom, controls):
            path = pathlib.Path(module.__file__)
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imported.append(node.module or "")
            for name in imported:
                for prefix in forbidden:
                    self.assertFalse(
                        name == prefix or name.startswith(prefix + "."),
                        f"{path.name} must not import {name}",
                    )

    def test_no_bare_wait_literals(self):
        import re

        source = pathlib.Path(dom.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"asyncio\.sleep\(\s*[0-9.]", source))
        self.assertIsNone(re.search(r"timeout\s*=\s*[0-9]", source))
        self.assertNotIn("wait_for_timeout(", source)

    def test_resolved_shape(self):
        resolved = Resolved(
            locator=object(), selector="#x", kind="text-zh", role="visible"
        )
        self.assertEqual(resolved.kind, "text-zh")
        self.assertEqual(resolved.role, "visible")


if __name__ == "__main__":
    unittest.main()
