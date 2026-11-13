# -*- coding: utf-8 -*-
"""Behaviour layer contract tests (spec §3 U5, ticket 34).

``utils/humanize.py`` is the single home of the 11 upstream action parameters
and the only place that dispatches keystrokes and coordinate clicks.  These
tests pin the contract without a browser:

1. the parameter table is the spec table (independent literal source);
2. typing is per character (ASCII ``press`` / non-ASCII ``insert_text``) with a
   ``Keystroke`` sample after each character, and exactly one bulk
   ``insert_text`` past ``type_horizon_chars`` (1000);
3. every text entry ends with one ``after_type``;
4. a click is ``move → PointerSettle → stillOn → down → ClickHold → up`` and a
   failed ``stillOn`` never reaches ``mouse.down``;
5. the same seed reproduces the same delays, and ``HUMANIZE=0`` (or
   ``profile.enabled=False``) is a zero-delay fast path;
6. gates A–E hold for the XHS reference package and for all 15 wired platform
   entry points (spec §4.2), including no ``fill(`` / ``el.click()`` /
   ``force=True`` / bare ``locator.click(`` / ``Control+KeyA``.

The fakes come from ``tests/fakes_xhs_dom.py``; no network, no browser.
"""

from __future__ import annotations

import ast
import asyncio
import os
import random
import re
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from tests.fakes_xhs_dom import (
    RecordingLocator,
    RecordingMouse,
    RecordingPage,
    preview_tiles,
)
from tests.humanize_gates import (
    assert_clean,
    gate_violations,
    mentions_horizon_definition,
)
from utils import humanize
from utils.dom import ElementUnusableError

UPLOADER_DIR = Path(__file__).resolve().parent.parent / "uploader" / "xiaohongshu_uploader"
HUMANIZE_FILE = Path(humanize.__file__)

#: Spec §3 U5 A, transcribed by hand from the table (μ, σ, min_s, max_s).
SPEC_TABLE = {
    "keystroke": (-2.12, 0.50, 0.030, 0.400),
    "after_type": (-0.51, 0.40, 0.200, 3.0),
    "after_navigate": (0.41, 0.45, 0.600, 6.0),
    "before_submit": (0.0, 0.40, 0.400, 4.0),
    "pointer_settle": (-1.20, 0.35, 0.200, 1.200),
    "click_hold": (-2.47, 0.33, 0.045, 0.250),
    "before_click": (-1.61, 0.45, 0.080, 1.0),
    "after_click": (-0.92, 0.35, 0.150, 2.0),
    "between_scroll": (-0.22, 0.40, 0.250, 3.0),
    "reading": (-0.36, 0.40, 0.300, 3.0),
    "after_interact": (0.88, 0.30, 2.0, 3.0),
}

FACTS = {
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


class LogRecorder:
    """Capture ``humanize._log`` calls as ``(level, message)`` pairs."""

    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    def _record(self, level: str, message: object, *args, **kwargs) -> None:
        self.lines.append((level, str(message)))

    def debug(self, message, *args, **kwargs):
        self._record("debug", message, *args, **kwargs)

    def info(self, message, *args, **kwargs):
        self._record("info", message, *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        self._record("warning", message, *args, **kwargs)

    def error(self, message, *args, **kwargs):
        self._record("error", message, *args, **kwargs)


class Timeline:
    """One ordered event log shared by ``sleep``, ``mouse`` and the target."""

    def __init__(self) -> None:
        self.events: list[tuple] = []

    async def sleep(self, seconds: float) -> None:
        self.events.append(("sleep", float(seconds)))

    def add(self, *event) -> None:
        self.events.append(event)

    def kinds(self) -> list[str]:
        return [event[0] for event in self.events]

    def first_index(self, kind: str) -> int:
        return self.kinds().index(kind)

    def of_kind(self, kind: str) -> list[tuple]:
        return [event for event in self.events if event[0] == kind]

    def sleeps(self) -> list[float]:
        return [event[1] for event in self.of_kind("sleep")]


class TimelineMouse(RecordingMouse):
    """``page.mouse`` double that also appends to the shared timeline."""

    def __init__(self, timeline: Timeline) -> None:
        super().__init__()
        self.timeline = timeline

    async def move(self, x: float, y: float, **kwargs) -> None:
        self.timeline.add("move", float(x), float(y))
        await super().move(x, y, **kwargs)

    async def down(self, **kwargs) -> None:
        self.timeline.add("down")
        await super().down(**kwargs)

    async def up(self, **kwargs) -> None:
        self.timeline.add("up")
        await super().up(**kwargs)


class ClickTarget:
    """Element double that satisfies ``utils.dom.check(..., "interactive")``.

    ``box_drift`` moves the box after the first measurement (stillOn position
    check); ``self_hit=False`` makes ``elementFromPoint`` land on a mask.
    """

    def __init__(
        self,
        name: str = "target",
        *,
        box: dict | None = None,
        self_hit: bool = True,
        box_drift: float = 0.0,
        timeline: Timeline | None = None,
    ) -> None:
        self.name = name
        self.box = dict(box or {"x": 100.0, "y": 100.0, "width": 60.0, "height": 30.0})
        self.self_hit = self_hit
        self.box_drift = box_drift
        self.timeline = timeline
        self.box_calls = 0
        self.click_calls = 0

    @property
    def first(self) -> "ClickTarget":
        return self

    async def count(self) -> int:
        return 1

    async def is_visible(self) -> bool:
        return True

    async def is_enabled(self) -> bool:
        return True

    async def bounding_box(self):
        self.box_calls += 1
        if self.box is None:
            return None
        box = dict(self.box)
        if self.box_calls > 1 and self.box_drift:
            box["x"] = float(box["x"]) + self.box_drift
        return box

    async def evaluate(self, expression, arg=None):
        if isinstance(expression, str) and "elementFromPoint" in expression:
            if self.timeline is not None:
                self.timeline.add("hit-test")
            if self.self_hit:
                return {"self": True, "tag": "div", "className": "", "id": "", "text": ""}
            return {
                "self": False,
                "tag": "div",
                "className": "mask",
                "id": "",
                "text": "",
            }
        return dict(FACTS)

    async def click(self, **kwargs) -> None:
        self.click_calls += 1


def _page(timeline: Timeline | None = None, **selectors) -> RecordingPage:
    page = RecordingPage(selectors=dict(selectors))
    if timeline is not None:
        page.mouse = TimelineMouse(timeline)
    return page


# ---------------------------------------------------------------------------
# 1. Parameter table: one definition, taken verbatim from the spec
# ---------------------------------------------------------------------------


class ParameterTableTests(unittest.TestCase):
    def test_profile_holds_the_eleven_spec_actions(self):
        for name, expected in SPEC_TABLE.items():
            with self.subTest(action=name):
                action = getattr(humanize.DEFAULT_PROFILE, name)
                self.assertIsInstance(action, humanize.LogNormal)
                self.assertEqual(
                    (action.mu, action.sigma, action.min_s, action.max_s),
                    expected,
                )

    def test_profile_has_the_typing_horizon_and_enabled_switch(self):
        self.assertEqual(humanize.DEFAULT_PROFILE.type_horizon_chars, 1000)
        self.assertTrue(humanize.DEFAULT_PROFILE.enabled)

    def test_profile_is_frozen_and_replaceable(self):
        with self.assertRaises(Exception):
            humanize.DEFAULT_PROFILE.enabled = False
        derived = replace(humanize.DEFAULT_PROFILE, enabled=False)
        self.assertFalse(derived.enabled)
        self.assertIs(humanize.DEFAULT_PROFILE, humanize.DEFAULT_PROFILE)
        self.assertTrue(humanize.DEFAULT_PROFILE.enabled)

    def test_log_normal_is_clamped_and_reproducible(self):
        action = humanize.LogNormal(-2.12, 0.50, 0.030, 0.400)
        first = [action.sample(random.Random(1)) for _ in range(200)]
        second = [action.sample(random.Random(1)) for _ in range(200)]
        self.assertEqual(first, second)
        self.assertTrue(all(0.030 <= value <= 0.400 for value in first))

    def test_log_normal_mean_matches_the_spec_column(self):
        # exp(μ + σ²/2) = 0.136s for Keystroke (spec §3 U5 A).
        action = humanize.DEFAULT_PROFILE.keystroke
        rng = random.Random(20260101)
        draws = [action.sample(rng) for _ in range(20_000)]
        mean = sum(draws) / len(draws)
        self.assertAlmostEqual(mean, 0.136, delta=0.006)

    def test_short_samples_are_clamped_outside_the_tail(self):
        wide = humanize.LogNormal(5.0, 0.01, 0.010, 0.020)
        rng = random.Random(3)
        self.assertTrue(all(wide.sample(rng) == 0.020 for _ in range(20)))


# ---------------------------------------------------------------------------
# 2/3. Typing: per-character dispatch, 1000/1001 boundary, one after_type
# ---------------------------------------------------------------------------


class TypeTextTests(unittest.IsolatedAsyncioTestCase):
    async def test_ascii_uses_press_and_non_ascii_uses_insert_text(self):
        timeline = Timeline()
        page = _page(timeline)
        humanizer = humanize.Humanizer(
            page, rng=random.Random(7), sleep=timeline.sleep
        )

        await humanizer.type_text("ab中文")

        self.assertEqual(
            page.keyboard.actions,
            [
                ("press", "a"),
                ("press", "b"),
                ("insert_text", "中"),
                ("insert_text", "文"),
            ],
        )
        # one Keystroke sample per character + one AfterType at the end
        self.assertEqual(len(timeline.sleeps()), 5)
        keystroke = humanize.DEFAULT_PROFILE.keystroke
        for delay in timeline.sleeps()[:-1]:
            self.assertGreaterEqual(delay, keystroke.min_s)
            self.assertLessEqual(delay, keystroke.max_s)
        after_type = humanize.DEFAULT_PROFILE.after_type
        self.assertGreaterEqual(timeline.sleeps()[-1], after_type.min_s)
        self.assertLessEqual(timeline.sleeps()[-1], after_type.max_s)

    async def test_newline_is_enter_not_an_unknown_key(self):
        timeline = Timeline()
        page = _page(timeline)
        humanizer = humanize.Humanizer(
            page, rng=random.Random(1), sleep=timeline.sleep
        )

        await humanizer.type_text("a\nb")

        self.assertEqual(
            page.keyboard.actions,
            [("press", "a"), ("press", "Enter"), ("press", "b")],
        )

    async def test_thousand_chars_still_uses_per_character_dispatch(self):
        timeline = Timeline()
        page = _page(timeline)
        humanizer = humanize.Humanizer(
            page, rng=random.Random(2), sleep=timeline.sleep
        )

        await humanizer.type_text("a" * 1000)

        presses = [a for a in page.keyboard.actions if a[0] == "press"]
        inserts = [a for a in page.keyboard.actions if a[0] == "insert_text"]
        self.assertEqual(len(presses), 1000)
        self.assertEqual(inserts, [])
        self.assertEqual(len(timeline.sleeps()), 1001)

    async def test_thousand_and_one_chars_is_one_bulk_insert(self):
        timeline = Timeline()
        page = _page(timeline)
        recorder = LogRecorder()
        humanizer = humanize.Humanizer(
            page, rng=random.Random(2), sleep=timeline.sleep
        )

        with patch.object(humanize, "_log", recorder):
            await humanizer.type_text("b" * 1001)

        self.assertEqual(page.keyboard.actions, [("insert_text", "b" * 1001)])
        # zero Keystroke samples, still exactly one AfterType
        self.assertEqual(len(timeline.sleeps()), 1)
        after_type = humanize.DEFAULT_PROFILE.after_type
        self.assertGreaterEqual(timeline.sleeps()[0], after_type.min_s)
        self.assertLessEqual(timeline.sleeps()[0], after_type.max_s)
        self.assertEqual(
            [line for level, line in recorder.lines if level == "info"],
            ["type_text→bulk insert_text, chars=1001"],
        )

    async def test_short_text_logs_no_bulk_line(self):
        timeline = Timeline()
        page = _page(timeline)
        recorder = LogRecorder()
        humanizer = humanize.Humanizer(
            page, rng=random.Random(4), sleep=timeline.sleep
        )

        with patch.object(humanize, "_log", recorder):
            await humanizer.type_text("标题")

        self.assertEqual(recorder.lines, [])

    async def test_press_samples_a_keystroke(self):
        timeline = Timeline()
        page = _page(timeline)
        humanizer = humanize.Humanizer(
            page, rng=random.Random(5), sleep=timeline.sleep
        )

        await humanizer.press("Backspace")

        self.assertEqual(page.keyboard.actions, [("press", "Backspace")])
        self.assertEqual(len(timeline.sleeps()), 1)
        self.assertGreaterEqual(
            timeline.sleeps()[0], humanize.DEFAULT_PROFILE.keystroke.min_s
        )
        self.assertLessEqual(
            timeline.sleeps()[0], humanize.DEFAULT_PROFILE.keystroke.max_s
        )


# ---------------------------------------------------------------------------
# 4. Click: bezier move → settle → stillOn → down → hold → up
# ---------------------------------------------------------------------------


class ClickTests(unittest.IsolatedAsyncioTestCase):
    async def test_click_dispatches_after_settle_and_still_on(self):
        timeline = Timeline()
        page = _page(timeline)
        target = ClickTarget(timeline=timeline)
        humanizer = humanize.Humanizer(
            page, rng=random.Random(11), sleep=timeline.sleep
        )

        await humanizer.click(target)

        kinds = timeline.kinds()
        self.assertEqual(kinds.count("down"), 1)
        self.assertEqual(kinds.count("up"), 1)
        self.assertEqual(kinds.count("hit-test"), 1)
        self.assertLessEqual(kinds.count("move"), 40)
        self.assertGreaterEqual(kinds.count("move"), 10)
        # stillOn (hit-test) sits between the last move and mouse.down
        last_move = max(i for i, kind in enumerate(kinds) if kind == "move")
        down_index = kinds.index("down")
        up_index = kinds.index("up")
        hit_index = kinds.index("hit-test")
        self.assertLess(last_move, hit_index)
        self.assertLess(hit_index, down_index)
        self.assertLess(down_index, up_index)

        settle_events = [
            event
            for event in timeline.events[last_move + 1 : hit_index]
            if event[0] == "sleep"
        ]
        self.assertEqual(len(settle_events), 1)
        settle = settle_events[0][1]
        self.assertGreaterEqual(settle, humanize.DEFAULT_PROFILE.pointer_settle.min_s)
        self.assertLessEqual(settle, humanize.DEFAULT_PROFILE.pointer_settle.max_s)

        hold_events = [
            event
            for event in timeline.events[down_index + 1 : up_index]
            if event[0] == "sleep"
        ]
        self.assertEqual(len(hold_events), 1)
        hold = hold_events[0][1]
        self.assertGreaterEqual(hold, humanize.DEFAULT_PROFILE.click_hold.min_s)
        self.assertLessEqual(hold, humanize.DEFAULT_PROFILE.click_hold.max_s)

    async def test_every_move_step_sleeps_five_to_nine_ms(self):
        timeline = Timeline()
        page = _page(timeline)
        target = ClickTarget(
            box={"x": 40.0, "y": 40.0, "width": 80.0, "height": 24.0},
            timeline=timeline,
        )
        humanizer = humanize.Humanizer(
            page, rng=random.Random(13), sleep=timeline.sleep
        )

        await humanizer.click(target)

        step_delays = [
            delay for delay in timeline.sleeps() if 0.005 <= delay <= 0.009
        ]
        self.assertGreaterEqual(len(step_delays), 10)
        self.assertLessEqual(len(step_delays), 40)
        for delay in step_delays:
            self.assertGreaterEqual(delay, 0.005)
            self.assertLessEqual(delay, 0.009)

    async def test_click_point_stays_inside_the_inset_box(self):
        timeline = Timeline()
        page = _page(timeline)
        box = {"x": 200.0, "y": 300.0, "width": 120.0, "height": 40.0}
        target = ClickTarget(box=box, timeline=timeline)
        humanizer = humanize.Humanizer(
            page, rng=random.Random(17), sleep=timeline.sleep
        )

        await humanizer.click(target)

        inset_x = min(box["width"] * 0.15, 8.0)
        inset_y = min(box["height"] * 0.15, 8.0)
        _kind, x, y = timeline.of_kind("move")[-1]
        self.assertGreaterEqual(x, box["x"] + inset_x - 1e-6)
        self.assertLessEqual(x, box["x"] + box["width"] - inset_x + 1e-6)
        self.assertGreaterEqual(y, box["y"] + inset_y - 1e-6)
        self.assertLessEqual(y, box["y"] + box["height"] - inset_y + 1e-6)

    async def test_click_point_biases_towards_the_fractional_anchor(self):
        timeline = Timeline()
        page = _page(timeline)
        box = {"x": 0.0, "y": 0.0, "width": 200.0, "height": 40.0}
        target = ClickTarget(box=box, timeline=timeline)
        humanizer = humanize.Humanizer(
            page, rng=random.Random(19), sleep=timeline.sleep
        )

        await humanizer.click(target, point=(0.65, 0.5))

        _kind, x, y = timeline.of_kind("move")[-1]
        self.assertAlmostEqual(x, box["width"] * 0.65, delta=8.0)
        self.assertAlmostEqual(y, box["height"] * 0.5, delta=8.0)

    async def test_still_on_failure_never_presses_the_mouse(self):
        timeline = Timeline()
        page = _page(timeline)
        target = ClickTarget(self_hit=False, timeline=timeline)
        humanizer = humanize.Humanizer(
            page, rng=random.Random(23), sleep=timeline.sleep
        )

        with self.assertRaises(ElementUnusableError) as ctx:
            await humanizer.click(target)

        self.assertEqual(ctx.exception.reason, "covered-by:div.mask")
        self.assertFalse(ctx.exception.publish_clicked)
        self.assertIn("未点击发布", str(ctx.exception))
        self.assertEqual(page.mouse.down_count, 0)
        self.assertEqual(page.mouse.up_count, 0)
        self.assertNotIn("down", timeline.kinds())

    async def test_bounding_box_drift_before_dispatch_is_refused(self):
        timeline = Timeline()
        page = _page(timeline)
        target = ClickTarget(box_drift=3.0, timeline=timeline)
        humanizer = humanize.Humanizer(
            page, rng=random.Random(29), sleep=timeline.sleep
        )

        with self.assertRaises(ElementUnusableError) as ctx:
            await humanizer.click(target)

        self.assertEqual(ctx.exception.reason, "point-drift")
        self.assertEqual(page.mouse.down_count, 0)

    async def test_missing_bounding_box_is_definitely_not_dispatched(self):
        timeline = Timeline()
        page = _page(timeline)
        humanizer = humanize.Humanizer(
            page, rng=random.Random(31), sleep=timeline.sleep
        )
        target = ClickTarget()
        target.box = None

        with self.assertRaises(ElementUnusableError) as ctx:
            await humanizer.click(target)

        self.assertEqual(ctx.exception.reason, "no-bounding-box")
        self.assertFalse(ctx.exception.publish_clicked)
        self.assertEqual(page.mouse.actions, [])

    async def test_failure_after_mouse_down_is_marked_maybe_dispatched(self):
        timeline = Timeline()
        page = _page(timeline)
        target = ClickTarget(timeline=timeline)

        class ExplodingMouse(TimelineMouse):
            async def up(self, **kwargs) -> None:
                self.timeline.add("up-attempt")
                raise RuntimeError("up failed")

        page.mouse = ExplodingMouse(timeline)
        humanizer = humanize.Humanizer(
            page, rng=random.Random(37), sleep=timeline.sleep
        )

        with self.assertRaises(RuntimeError) as ctx:
            await humanizer.click(target)

        self.assertEqual(
            getattr(ctx.exception, humanize.MAYBE_DISPATCHED, "missing"), "maybe"
        )
        self.assertEqual(page.mouse.down_count, 1)


# ---------------------------------------------------------------------------
# 5. Reproducibility and the zero-delay fast path
# ---------------------------------------------------------------------------


class ReproducibilityTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, seed: int) -> tuple[list, list]:
        timeline = Timeline()
        page = _page(timeline)
        humanizer = humanize.Humanizer(
            page, rng=random.Random(seed), sleep=timeline.sleep
        )
        await humanizer.type_text("标题ab")
        await humanizer.click(ClickTarget(timeline=timeline))
        return timeline.sleeps(), timeline.of_kind("move")

    async def test_same_seed_reproduces_the_same_delays_and_path(self):
        self.assertEqual(await self._run(101), await self._run(101))

    async def test_different_seeds_diverge(self):
        self.assertNotEqual(await self._run(101), await self._run(102))


class FastPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_humanize_zero_env_is_zero_delay(self):
        timeline = Timeline()
        page = _page(timeline, **{"#target": RecordingLocator("target")})
        locator = page.locator("#target")

        with patch.dict(os.environ, {"HUMANIZE": "0"}):
            humanizer = humanize.Humanizer(
                page, rng=random.Random(1), sleep=timeline.sleep
            )
            await humanizer.type_text("中文abc")
            await humanizer.click(locator)

        self.assertEqual(page.keyboard.actions, [("insert_text", "中文abc")])
        self.assertEqual(locator.click_count, 1)
        self.assertEqual(page.mouse.actions, [])
        self.assertEqual(timeline.sleeps(), [])

    async def test_profile_disabled_is_zero_delay(self):
        timeline = Timeline()
        page = _page(timeline, **{"#target": RecordingLocator("target")})
        locator = page.locator("#target")
        profile = replace(humanize.DEFAULT_PROFILE, enabled=False)
        humanizer = humanize.Humanizer(
            page, profile=profile, rng=random.Random(1), sleep=timeline.sleep
        )

        await humanizer.type_text("标题")
        await humanizer.click(locator)

        self.assertEqual(page.keyboard.actions, [("insert_text", "标题")])
        self.assertEqual(locator.click_count, 1)
        self.assertEqual(page.mouse.actions, [])
        self.assertEqual(timeline.sleeps(), [])

    async def test_fast_path_press_still_dispatches_the_key(self):
        timeline = Timeline()
        page = _page(timeline)
        with patch.dict(os.environ, {"HUMANIZE": "0"}):
            humanizer = humanize.Humanizer(page, sleep=timeline.sleep)
            await humanizer.press("ControlOrMeta+A")

        self.assertEqual(page.keyboard.actions, [("press", "ControlOrMeta+A")])
        self.assertEqual(timeline.sleeps(), [])

    async def test_fast_path_click_failure_is_marked_maybe_dispatched(self):
        # The fast path delegates to ``locator.click``, which cannot prove the
        # click did not land.  FIRE must therefore treat the throw as
        # "possibly dispatched" instead of "definitely not dispatched".
        timeline = Timeline()
        locator = RecordingLocator(
            "target", click_error=RuntimeError("driver lost mid-click")
        )
        page = _page(timeline, **{"#target": locator})

        with patch.dict(os.environ, {"HUMANIZE": "0"}):
            humanizer = humanize.Humanizer(page, sleep=timeline.sleep)
            with self.assertRaises(RuntimeError) as ctx:
                await humanizer.click(locator)

        self.assertEqual(locator.click_count, 1)
        self.assertEqual(
            getattr(ctx.exception, humanize.MAYBE_DISPATCHED, None),
            humanize.MAYBE_DISPATCHED_VALUE,
        )


# ---------------------------------------------------------------------------
# 6. Shared-layer boundary and the XHS static gates
# ---------------------------------------------------------------------------


def _xhs_sources() -> dict[str, str]:
    """The XHS package's direct ``.py`` files (the reference implementation)."""
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(UPLOADER_DIR.glob("*.py"))
    }


class SharedLayerBoundaryTests(unittest.TestCase):
    def test_humanize_imports_no_platform_module(self):
        tree = ast.parse(HUMANIZE_FILE.read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        offenders = [
            name
            for name in imported
            if name.split(".")[0] in {"uploader", "sau_commands", "sau_cli"}
        ]
        self.assertEqual(offenders, [])

    def test_type_horizon_has_exactly_one_definition(self):
        offenders: list[str] = []
        root = HUMANIZE_FILE.parent.parent
        for folder in ("utils", "uploader", "sau_commands"):
            for path in sorted((root / folder).rglob("*.py")):
                if path == HUMANIZE_FILE:
                    continue
                source = path.read_text(encoding="utf-8")
                if any(
                    mentions_horizon_definition(line)
                    for line in source.splitlines()
                ):
                    offenders.append(str(path.relative_to(root)))
        self.assertEqual(offenders, [])


class HumanizeGateTests(unittest.TestCase):
    """The executable form of spec §4 gates A–E, on synthetic packages."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "utils").mkdir()
        (self.root / "utils" / "humanize.py").write_text(
            "type_horizon_chars = 1000\n", encoding="utf-8"
        )
        self.package = self.root / "uploader" / "demo"
        self.package.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, source: str) -> None:
        (self.package / "main.py").write_text(source, encoding="utf-8")

    def _violations(self) -> list[str]:
        return gate_violations(self.package)

    def _assert_gate(self, gate: str) -> None:
        violations = self._violations()
        self.assertTrue(
            any(gate in violation for violation in violations),
            f"expected {gate} violation, got {violations}",
        )

    def test_gate_a_rejects_js_click(self):
        self._write(
            "async def go(el):\n"
            "    await el.evaluate('el => el.click()')\n"
        )
        self._assert_gate("gate A")

    def test_gate_a_allows_read_only_evaluate(self):
        self._write(
            "async def go(el):\n"
            "    return await el.evaluate('el => el.getBoundingClientRect()')\n"
        )
        self.assertEqual(self._violations(), [])

    def test_gate_a_rejects_a_hoisted_js_click_constant(self):
        self._write(
            "_JS_CLICK = \"const el = document.querySelector(a); el.click();\"\n"
            "async def go(page):\n"
            "    await page.evaluate(_JS_CLICK)\n"
        )
        self._assert_gate("gate A")

    def test_gate_a_rejects_a_js_click_inside_an_fstring(self):
        self._write(
            "async def go(page, selector):\n"
            "    await page.eval_on_selector_all(\n"
            "        f\"{selector} => [...document.querySelectorAll(x)]\"\n"
            "        f\".forEach(e => e.click())\"\n"
            "    )\n"
        )
        self._assert_gate("gate A")

    def test_gate_a_ignores_docstrings_that_mention_click(self):
        self._write(
            '"""Prose: every click goes through ``Humanizer.click``."""\n'
            "async def go(page):\n"
            "    return await page.evaluate('() => document.title')\n"
        )
        self.assertEqual(self._violations(), [])

    def test_gate_b_requires_a_native_click_marker(self):
        self._write(
            "async def go(page):\n"
            "    await page.locator('#shell').click()\n"
        )
        self._assert_gate("gate B")

    def test_gate_b_rejects_a_humanizer_lookalike_receiver(self):
        self._write(
            "async def go(self):\n"
            "    await self.humanizer_page.click()\n"
        )
        self._assert_gate("gate B")

    def test_gate_b_exempts_the_humanizer_and_its_suffixed_holders(self):
        self._write(
            "async def go(self, editor_humanizer):\n"
            "    await humanizer.click(self.a)\n"
            "    await self.humanizer.click(self.b)\n"
            "    await editor_humanizer.click(self.c)\n"
        )
        self.assertEqual(self._violations(), [])

    def test_gate_b_accepts_a_marked_native_click(self):
        self._write(
            "async def go(page):\n"
            "    await page.locator('#shell').click()  "
            "# native-click: chrome；native browser UI\n"
        )
        self.assertEqual(self._violations(), [])

    def test_gate_b_rejects_an_unknown_native_click_class(self):
        self._write(
            "async def go(page):\n"
            "    await page.locator('#shell').click()  "
            "# native-click: magic；unknown class\n"
        )
        self._assert_gate("gate B")

    def test_gate_b_exempts_the_humanizer(self):
        self._write(
            "async def go(humanizer, locator):\n"
            "    await humanizer.click(locator)\n"
        )
        self.assertEqual(self._violations(), [])

    def test_gate_c_requires_the_impossible_marker(self):
        self._write(
            "async def go(locator):\n"
            "    await locator.click(force=True)  "
            "# native-click: chrome；native UI\n"
        )
        self._assert_gate("gate C")

    def test_gate_c_accepts_a_complete_impossible_marker(self):
        self._write(
            "async def go(locator):\n"
            "    await locator.click(force=True)  "
            "# native-click: chrome；native UI "
            "# humanize-impossible: overlay；needs-live；hover-then-retry\n"
        )
        self.assertEqual(self._violations(), [])

    def test_gate_d_requires_the_native_fill_marker(self):
        self._write(
            "async def go(locator):\n"
            "    await locator.fill('123456')\n"
        )
        self._assert_gate("gate D")

    def test_gate_d_accepts_the_two_factor_exception(self):
        self._write(
            "async def go(locator):\n"
            "    await locator.fill('123456')  "
            "# native-fill: 2FA 验证码\n"
        )
        self.assertEqual(self._violations(), [])

    def test_gate_e_rejects_a_second_horizon_definition(self):
        self._write("THRESHOLD = 1000  # type_horizon_chars\n")
        self._assert_gate("gate E")

    def test_gate_e_accepts_a_package_without_the_constant(self):
        self._write("THRESHOLD = 1000\n")
        self.assertEqual(self._violations(), [])

    def test_gate_e_accepts_an_attribute_read_of_the_single_definition(self):
        # Reusing ``DEFAULT_PROFILE.type_horizon_chars`` is not a second
        # definition; only a copied literal/assignment is.
        self._write(
            "from utils.humanize import DEFAULT_PROFILE\n"
            "if len(text) > DEFAULT_PROFILE.type_horizon_chars:\n"
            "    pass\n"
        )
        self.assertEqual(self._violations(), [])


class XhsStaticGateTests(unittest.TestCase):
    def test_xhs_package_passes_humanize_gates_a_to_e(self):
        assert_clean(UPLOADER_DIR)

    def test_no_fill_el_click_or_forced_clicks_remain(self):
        offenders: list[str] = []
        for name, source in _xhs_sources().items():
            for needle in ("fill(", "el.click()", "force=True", "_js_click_by_text"):
                if needle in source:
                    offenders.append(f"{name}: {needle}")
        self.assertEqual(offenders, [])

    def test_every_click_goes_through_the_humanizer(self):
        offenders: list[str] = []
        # `.click(` is allowed only when the receiver is the humanizer.
        pattern = re.compile(r"(?<!humanizer)\.click\(")
        for name, source in _xhs_sources().items():
            for number, line in enumerate(source.splitlines(), start=1):
                if pattern.search(line):
                    offenders.append(f"{name}:{number}: {line.strip()}")
        self.assertEqual(offenders, [])

    def test_select_all_uses_the_macos_compatible_shortcut(self):
        sources = "\n".join(_xhs_sources().values())
        self.assertNotIn("Control+KeyA", sources)
        self.assertIn("ControlOrMeta+A", sources)


#: The 15 wired platforms of spec §4.2.  That is 12 platform packages + 3
#: meta packages = 15 platforms, but 16 scan targets below: TikTok is
#: file-scoped because ``uploader/tk_uploader/`` also ships the legacy,
#: unwired ``main.py``; spec §3.12 only covers ``main_chrome.py``.
WIRED_PLATFORM_PACKAGES = (
    "alipay_uploader",
    "baijiahao_uploader",
    "dayu_uploader",
    "douyin_uploader",
    "hupu_uploader",
    "ks_uploader",
    "tencent_uploader",
    "weibo_uploader",
    "xueqiu_uploader",
    "youtube_uploader",
    "zhihu_uploader",
    "xiaohongshu_uploader",
)
WIRED_META_PACKAGES = (
    "facebook_uploader",
    "facebook_page_uploader",
    "insgraph_uploader",
)


class PlatformWideGateTests(unittest.TestCase):
    """Gates A–E across all 15 wired platforms (spec §4.2, 16 scan targets).

    TikTok is checked file-scoped at ``uploader/tk_uploader/main_chrome.py``:
    the sibling legacy ``uploader/tk_uploader/main.py`` is unwired and out of
    spec §3.12's target, so scanning the whole package would flag dead code.
    """

    def _assert_all_clean(self, packages) -> None:
        failures: list[str] = []
        for label, path in packages:
            try:
                assert_clean(path)
            except AssertionError as exc:
                failures.append(f"[{label}]\n{exc}")
        self.assertEqual(failures, [])

    def test_every_uploader_package_passes_gates_a_to_e(self):
        root = Path(__file__).resolve().parent.parent / "uploader"
        packages = [(name, root / name) for name in WIRED_PLATFORM_PACKAGES]
        packages += [
            (f"meta_uploader/{name}", root / "meta_uploader" / name)
            for name in WIRED_META_PACKAGES
        ]
        packages.append(
            ("tk_uploader/main_chrome.py", root / "tk_uploader" / "main_chrome.py")
        )
        self._assert_all_clean(packages)

    def test_the_wired_platform_list_covers_fifteen_entry_points(self):
        # 12 front-door packages + 3 meta packages = the spec's 15 platforms;
        # TikTok is one of the twelve, scanned as ``main_chrome.py``.
        self.assertEqual(
            len(WIRED_PLATFORM_PACKAGES) + len(WIRED_META_PACKAGES), 15
        )
        root = Path(__file__).resolve().parent.parent / "uploader"
        for name in WIRED_PLATFORM_PACKAGES:
            self.assertTrue((root / name).is_dir(), f"missing wired package: {name}")
        for name in WIRED_META_PACKAGES:
            path = root / "meta_uploader" / name
            self.assertTrue(path.is_dir(), f"missing wired package: {path}")
        self.assertTrue((root / "tk_uploader" / "main_chrome.py").is_file())


# ---------------------------------------------------------------------------
# 7. Wiring: the XHS publish chain really dispatches through the mouse
# ---------------------------------------------------------------------------

NOTE_URL = "https://creator.xiaohongshu.com/publish/publish?from=homepage&target=image"
SUCCESS_URL = "https://creator.xiaohongshu.com/publish/success?target=image"
NOTE_IMAGE_INPUT = "div.upload-content input.upload-input"
NOTE_TILES = ".img-preview-area .pr"
TITLE_INPUT = 'input[placeholder*="填写标题"]'
TITLE_STRUCTURE = "div.d-input input"
PUBLISH_BUTTON = "xhs-publish-btn"


class _FileInput(RecordingLocator):
    def __init__(self, name: str = "file-input") -> None:
        super().__init__(name)
        self.files: list[object] = []

    async def set_input_files(self, files, **kwargs) -> None:
        self.files.append(files)


class _PublishButton(RecordingLocator):
    """Interactive publish button: box + facts + hit-test."""

    timeline: Timeline | None = None

    async def bounding_box(self):
        return {"x": 10.0, "y": 20.0, "width": 160.0, "height": 40.0}

    async def evaluate(self, expression, arg=None):
        self.evaluate_calls.append((expression, arg))
        if isinstance(expression, str) and "elementFromPoint" in expression:
            if self.timeline is not None:
                self.timeline.add("hit-test")
            return {"self": True, "tag": "button", "className": "", "id": "", "text": ""}
        return dict(FACTS)


class _SuccessMouse(TimelineMouse):
    """Mouse that lands on the success page after the press is released."""

    def __init__(self, page: RecordingPage, timeline: Timeline) -> None:
        super().__init__(timeline)
        self._page = page
        self.url_on_up = SUCCESS_URL

    async def up(self, **kwargs) -> None:
        await super().up(**kwargs)
        self._page.url = self.url_on_up


class XhsPublishWiringTests(unittest.TestCase):
    """One dispatch through the behaviour layer, no browser, no real delay."""

    def test_publish_click_dispatches_once_through_the_mouse(self):
        import uploader.xiaohongshu_uploader.main as xhs_main

        image_input = _FileInput("image-input")
        title = RecordingLocator("title")
        title_structure = RecordingLocator("title-structure")
        publish = _PublishButton("publish")
        page = RecordingPage(
            url=NOTE_URL,
            selectors={
                NOTE_IMAGE_INPUT: image_input,
                NOTE_TILES: preview_tiles(1),
                TITLE_INPUT: title,
                TITLE_STRUCTURE: title_structure,
                PUBLISH_BUTTON: publish,
            },
        )
        timeline = Timeline()
        page.mouse = _SuccessMouse(page, timeline)
        publish.timeline = timeline

        class QuietHumanizer(humanize.Humanizer):
            """Same dispatch path; pauses recorded instead of slept."""

            def __init__(self, *args, **kwargs):
                kwargs["sleep"] = timeline.sleep
                super().__init__(*args, **kwargs)

            async def before_submit(self) -> None:
                timeline.add("before_submit")
                await super().before_submit()

        app = xhs_main.XiaoHongShuNote(
            image_paths=["a.png"],
            note="",
            tags=[],
            publish_date=0,
            account_file="account.json",
            title="标题",
            no_publish=False,
        )

        with patch.object(xhs_main, "Humanizer", QuietHumanizer):
            asyncio.run(app.upload_note_content(page, mode="local"))

        # Navigation is followed by exactly one after_navigate pause.
        self.assertEqual(timeline.events[0][0], "sleep")
        navigate = humanize.DEFAULT_PROFILE.after_navigate
        self.assertGreaterEqual(timeline.events[0][1], navigate.min_s)
        self.assertLessEqual(timeline.events[0][1], navigate.max_s)

        # Exactly one human dispatch: mouse down/up, zero locator.click().
        self.assertEqual(page.mouse.down_count, 1)
        self.assertEqual(page.mouse.up_count, 1)
        self.assertEqual(publish.click_count, 0)
        # stillOn ran before the press, and before_submit ran before the click.
        self.assertTrue(publish.evaluate_calls)
        self.assertTrue(
            any(
                isinstance(expression, str) and "elementFromPoint" in expression
                for expression, _arg in publish.evaluate_calls
            )
        )
        kinds = timeline.kinds()
        down_index = kinds.index("down")
        hit_index = kinds.index("hit-test")
        self.assertLess(hit_index, down_index)
        # before_submit sits between the readiness check and the click itself.
        self.assertIn("before_submit", kinds)
        self.assertLess(kinds.index("before_submit"), kinds.index("move"))
        self.assertLess(kinds.index("before_submit"), down_index)
        # Title typed through the behaviour layer (2 CJK chars = 2 inserts).
        self.assertEqual(
            page.keyboard.actions,
            [("insert_text", "标"), ("insert_text", "题")],
        )
        self.assertEqual(image_input.files, [["a.png"]])


if __name__ == "__main__":
    unittest.main()
