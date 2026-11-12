# -*- coding: utf-8 -*-
"""Instagram humanize rollout (ticket 02): sequence, readback, gates, fast path.

Everything here is browser-free.  The doubles are local to this module on
purpose: ``tests/fakes_xhs_dom.py`` is read-only for this ticket, and the
Instagram controls need a few shapes the XHS publish chain never touches
(``as_locator``-style suggestion rows, per-image typing buffers, ``blur``).

The three required blocks are:

``InstagramHumanizeEventSequenceTests``
    every changed interaction point uses the humanizer primitive
    (``press`` vs ``insert_text``), pays exactly one ``after_type``, runs
    ``stillOn`` (hit-test) before ``mouse.down``, never dispatches ``force``
    and never calls native ``locator.click``.  The shared nav helper hovers
    before it clicks (Instagram's rail expands on hover — spec §2.5.1).
``InstagramHumanizeFieldReadbackTests``
    the fake fields keep a typing buffer, so a correct key sequence that ends
    with the wrong value (dirty clear, appended text, dropped newline) fails.
``InstagramHumanizeGateTests`` / ``InstagramHumanizeFastPathTests``
    spec §4 gates A–E on the package and the ``HUMANIZE=0`` fast path
    (one ``insert_text`` / one ``locator.click`` / zero pauses).
"""

from __future__ import annotations

import ast
import asyncio
import os
import random
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from uploader.meta_uploader.insgraph_uploader.controls import _rows
from uploader.meta_uploader.insgraph_uploader.controls._rows import (
    activate,
    click_control,
)
from uploader.meta_uploader.insgraph_uploader.controls import (
    resolve_instagram_option_controls,
)
from uploader.meta_uploader.insgraph_uploader.controls.alt_text import AltTextControl
from uploader.meta_uploader.insgraph_uploader.controls.location import (
    ENTRY_SELECTORS,
    TYPE_DELAY_MS,
    LocationControl,
)
from uploader.meta_uploader.insgraph_uploader.controls.toggles import SwitchControl
from uploader.meta_uploader.insgraph_uploader.main import (
    InstagramUploader,
    _dismiss_optional_prompt,
    _click_nav,
    _click_submit,
    _read_back_caption,
    _type_caption,
)
from tests.humanize_gates import assert_clean
from utils.dom import ElementUnusableError
from utils.humanize import Humanizer

PACKAGE = (
    Path(__file__).resolve().parent.parent
    / "uploader"
    / "meta_uploader"
    / "insgraph_uploader"
)

#: Complete facts payload for ``utils.dom`` probes (one JS round-trip each).
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
    "contentEditable": "true",
    "readOnly": False,
    "isConnected": True,
}

_UNSET = object()


class UnscriptedSelectorError(AssertionError):
    """A selector the test never scripted: fail loudly, never return zero."""


class UnscriptedEvaluationError(AssertionError):
    """``evaluate`` without a handler/result: same fail-loud rule."""


async def _no_sleep(seconds: float) -> None:
    return None


class Timeline:
    """Single ordered log shared by page, keyboard, mouse and pauses."""

    def __init__(self) -> None:
        self.events: list[tuple] = []

    def add(self, kind: str, *payload) -> None:
        self.events.append((kind, *payload))

    def kinds(self) -> list[str]:
        return [event[0] for event in self.events]

    def index(self, kind: str) -> int:
        try:
            return self.kinds().index(kind)
        except ValueError as exc:
            raise AssertionError(f"no {kind!r} event in {self.events}") from exc

    def payloads(self, kind: str) -> list[tuple]:
        return [event for event in self.events if event[0] == kind]

    async def sleep(self, seconds: float) -> None:
        self.add("sleep", round(float(seconds), 4))


class TypingKeyboard:
    """Keyboard double that applies keys to the currently focused field."""

    def __init__(self, page: "HumanizePage") -> None:
        self.page = page
        self.target = None
        self.actions: list[tuple] = []
        self._select_all = False

    def focus(self, field) -> None:
        self.target = field

    def _require_target(self):
        if self.target is None:
            raise AssertionError("typed with no focused field")
        return self.target

    async def press(self, key: str, **kwargs) -> None:
        self.actions.append(("press", key))
        self.page.timeline.add("press", key)
        if key in ("ControlOrMeta+A", "Control+A", "Meta+A"):
            self._select_all = True
        elif key in ("Delete", "Backspace"):
            field = self._require_target()
            if self._select_all:
                field.value = ""
                self._select_all = False
            elif field.value:
                field.value = field.value[:-1]
        elif key == "Enter":
            self._require_target().value += "\n"
        elif len(key) == 1:
            self._require_target().value += key

    async def insert_text(self, text: str, **kwargs) -> None:
        self.actions.append(("insert_text", text))
        self.page.timeline.add("insert_text", text)
        self._require_target().value += text

    async def type(self, *args, **kwargs) -> None:  # pragma: no cover - forbidden
        raise AssertionError("native keyboard.type must not be used")

    async def down(self, *args, **kwargs) -> None:  # pragma: no cover
        raise AssertionError("native keyboard.down must not be used")

    async def up(self, *args, **kwargs) -> None:  # pragma: no cover
        raise AssertionError("native keyboard.up must not be used")


class TypingMouse:
    """Mouse double: ``move* → down → up``, and ``up`` lands on the hit test."""

    def __init__(self, page: "HumanizePage") -> None:
        self.page = page
        self.actions: list[tuple] = []

    async def move(self, x: float, y: float, **kwargs) -> None:
        self.actions.append(("move", float(x), float(y)))
        self.page.timeline.add("move", float(x), float(y))

    async def down(self, **kwargs) -> None:
        self.actions.append(("down",))
        self.page.timeline.add("down")

    async def up(self, **kwargs) -> None:
        self.actions.append(("up",))
        self.page.timeline.add("up")
        target = self.page.hit_target
        if target is not None:
            target.receive_click()

    async def click(self, *args, **kwargs) -> None:  # pragma: no cover
        raise AssertionError("native mouse.click must not be used")


class Field:
    """Scripted locator double with a real text buffer and fail-loud selectors."""

    def __init__(
        self,
        name: str,
        *,
        page: "HumanizePage | None" = None,
        value: str = "",
        text: str | None = None,
        box: dict[str, float] | None = None,
        count: int = 1,
        items: list["Field"] | None = None,
        children: dict[str, "Field"] | None = None,
        locator_handler=None,
        attributes: dict[str, str] | None = None,
        visible: bool = True,
        enabled: bool = True,
        evaluate_handler=None,
        evaluate_result=_UNSET,
    ) -> None:
        self.name = name
        self.page = page
        self.value = value
        self._text = text if text is not None else value
        self._box = box if box is not None else {
            "x": 40.0,
            "y": 40.0,
            "width": 120.0,
            "height": 32.0,
        }
        self._count = count
        self._items = items
        self._children = dict(children or {})
        self._locator_handler = locator_handler
        self._attributes = dict(attributes or {})
        self._visible = visible
        self._enabled = enabled
        self._evaluate_handler = evaluate_handler
        self._evaluate_result = evaluate_result

        self.blurs = 0
        self.hovers = 0
        self.click_count = 0
        self.native_clicks: list[dict] = []
        self.presses: list[str] = []
        self.fills: list[str] = []
        self.evaluate_calls: list[tuple] = []
        self.focus_calls = 0
        self.detached = False
        self.on_real_click = None

    # -- structure ---------------------------------------------------------
    @property
    def first(self) -> "Field":
        return self._items[0] if self._items else self

    @property
    def last(self) -> "Field":
        return self._items[-1] if self._items else self

    def nth(self, index: int) -> "Field":
        if self._items is not None:
            return self._items[index]
        return self

    def locator(self, selector: str) -> "Field":
        if selector in self._children:
            return self._children[selector]
        if self._locator_handler is not None:
            return self._locator_handler(selector)
        raise UnscriptedSelectorError(
            f"{self.name}: un-scripted child selector {selector!r}; "
            f"scripted: {sorted(self._children)}"
        )

    def get_by_role(self, role: str, name=None) -> "Field":
        key = f"role:{role}" if name is None else f"role:{role}:{name}"
        return self._child(key)

    def get_by_text(self, text: str, exact: bool = False) -> "Field":
        key = f"text:{text}:exact" if exact else f"text:{text}"
        return self._child(key)

    def _child(self, key: str) -> "Field":
        if key in self._children:
            return self._children[key]
        raise UnscriptedSelectorError(
            f"{self.name}: un-scripted {key!r}; scripted: {sorted(self._children)}"
        )

    def filter(self, **kwargs) -> "Field":
        return self

    # -- read state --------------------------------------------------------
    async def count(self) -> int:
        return self._count

    async def is_visible(self) -> bool:
        return self._visible

    async def is_enabled(self) -> bool:
        return self._enabled

    async def get_attribute(self, name: str):
        return self._attributes.get(name)

    async def inner_text(self) -> str:
        return self._text

    async def text_content(self) -> str:
        return self._text

    async def input_value(self) -> str:
        return self.value

    async def bounding_box(self):
        return dict(self._box) if self._box else None

    # -- interactions ------------------------------------------------------
    async def wait_for(self, **kwargs) -> None:
        self.page.timeline.add("wait_for", self.name, kwargs.get("state"))

    async def scroll_into_view_if_needed(self, **kwargs) -> None:
        self.page.timeline.add("scroll", self.name)

    async def focus(self, **kwargs) -> None:
        self.focus_calls += 1
        self.page.timeline.add("focus", self.name)
        self.page.keyboard.focus(self)

    async def press(self, key: str, **kwargs) -> None:
        self.presses.append(key)
        await self.page.keyboard.press(key)

    async def fill(self, value: str, **kwargs) -> None:
        self.fills.append(value)
        self.value = value
        self.page.timeline.add("fill", self.name, value)

    async def hover(self, **kwargs) -> None:
        # ``HUMANIZE=0`` 的 ``Humanizer.hover`` 直通 ``locator.hover``。
        self.hovers += 1
        self.page.timeline.add("locator.hover", self.name)

    async def click(self, **kwargs) -> None:
        self.click_count += 1
        self.native_clicks.append(dict(kwargs))
        self.page.timeline.add("locator.click", self.name)
        self.receive_click()

    def receive_click(self) -> None:
        self.page.keyboard.focus(self)
        if self.on_real_click is not None:
            self.on_real_click()

    async def evaluate(self, expression, arg=None):
        self.evaluate_calls.append((expression, arg))
        if isinstance(expression, str):
            if "elementFromPoint" in expression:
                self.page.timeline.add("hit-test", self.name)
                self.page.hit_target = self
                return {"self": True, "tag": "div", "className": "", "id": "", "text": ""}
            if "ancestorAriaHidden" in expression:
                return dict(FACTS)
            if "childFrame" in expression:
                return {
                    "width": self._box["width"] if self._box else 0.0,
                    "height": self._box["height"] if self._box else 0.0,
                    "inside": True,
                    "clipped": False,
                    "childFrame": False,
                }
            if "isConnected" in expression:
                return self.detached
            if "blur()" in expression:
                self.blurs += 1
                return None
        if self._evaluate_handler is not None:
            return self._evaluate_handler(self, expression, arg)
        if self._evaluate_result is not _UNSET:
            return self._evaluate_result
        raise UnscriptedEvaluationError(
            f"{self.name}: un-scripted evaluate({expression!r})"
        )


class HumanizePage:
    """Page double wiring locators, keyboard, mouse and the shared timeline."""

    def __init__(self) -> None:
        self.timeline = Timeline()
        self.keyboard = TypingKeyboard(self)
        self.mouse = TypingMouse(self)
        self.hit_target = None
        self.selectors: dict[str, Field] = {}
        self.locator_handler = None
        self.wait_calls: list[float] = []
        self.url = "https://www.instagram.com/"
        self.content_type = "text/html"
        self.listeners: list[str] = []
        self.viewport_size = None

    def add(self, key: str, field: Field) -> Field:
        self.selectors[key] = field
        return field

    def locator(self, selector: str) -> Field:
        if selector in self.selectors:
            return self.selectors[selector]
        if self.locator_handler is not None:
            return self.locator_handler(selector)
        raise UnscriptedSelectorError(
            f"page: un-scripted selector {selector!r}; scripted: {sorted(self.selectors)}"
        )

    def get_by_role(self, role: str, name=None) -> Field:
        key = f"role:{role}" if name is None else f"role:{role}:{name}"
        return self.locator(key)

    def get_by_text(self, text: str, exact: bool = False) -> Field:
        key = f"text:{text}:exact" if exact else f"text:{text}"
        return self.locator(key)

    async def wait_for_timeout(self, milliseconds: float) -> None:
        self.wait_calls.append(milliseconds)
        self.timeline.add("wait_for_timeout", milliseconds)

    async def evaluate(self, expression, arg=None):
        raise UnscriptedEvaluationError(f"page.evaluate({expression!r}) not scripted")

    def on(self, event: str, callback) -> None:
        self.listeners.append(event)

    def remove_listener(self, event: str, callback) -> None:
        if event in self.listeners:
            self.listeners.remove(event)


class RecordingHumanizer(Humanizer):
    """Humanizer that names every pause point in the shared timeline.

    ``type_text`` pays its ``after_type`` through ``_pause`` (not through the
    public method), so the recorder hooks ``_pause`` and matches the profile
    action by identity — that is what proves "exactly one ``after_type``".
    """

    _NAMES = (
        "keystroke",
        "after_type",
        "after_navigate",
        "before_submit",
        "pointer_settle",
        "click_hold",
        "between_scroll",
    )

    def __init__(self, page: HumanizePage, timeline: Timeline) -> None:
        super().__init__(page, rng=random.Random(20261112), sleep=timeline.sleep)
        self.timeline = timeline
        self._actions = {
            id(getattr(self.profile, name)): name for name in self._NAMES
        }

    async def _pause(self, action) -> None:
        if self.enabled:
            self.timeline.add("pause", self._actions.get(id(action), "pause"))
        await super()._pause(action)


class StubBudget:
    """Duck-typed budget: clamp every wait to ``ms`` milliseconds."""

    def __init__(self, ms: int = 1) -> None:
        self.ms = ms

    def clamp_ms(self, default_ms: int) -> int:
        return min(default_ms, self.ms)

    def remaining_seconds(self) -> float:
        return 60.0


def _page() -> HumanizePage:
    return HumanizePage()


# ---------------------------------------------------------------------------
# 1. Event sequence: every changed interaction point
# ---------------------------------------------------------------------------


class InstagramHumanizeEventSequenceTests(unittest.IsolatedAsyncioTestCase):
    """Keyboard-first row activation, humanized clicks, one pause per text."""

    async def test_activate_is_keyboard_first_and_falls_back_to_humanizer(self):
        page = _page()
        humanizer = RecordingHumanizer(page, page.timeline)
        opened = {"value": False}

        def flip() -> None:
            opened["value"] = True

        row = page.add("row", Field("row", page=page))
        row.on_real_click = flip

        async def is_open() -> bool:
            return opened["value"]

        self.assertTrue(await activate(page, row, is_open=is_open, humanizer=humanizer))

        kinds = page.timeline.kinds()
        self.assertIn("press", kinds)
        self.assertEqual(page.keyboard.actions[0], ("press", "Enter"))
        # Keyboard ran first; the coordinate click is the fallback, not the opener.
        self.assertLess(kinds.index("press"), kinds.index("down"))
        self.assertEqual(kinds.count("down"), 1)
        self.assertEqual(kinds.count("up"), 1)
        # No JS click, no native locator click.
        self.assertEqual(row.click_count, 0)
        self.assertLess(kinds.index("hit-test"), kinds.index("down"))

    async def test_activate_does_not_click_when_keyboard_already_opened(self):
        page = _page()
        humanizer = RecordingHumanizer(page, page.timeline)
        row = page.add("row", Field("row", page=page))

        async def is_open() -> bool:
            return True

        self.assertTrue(await activate(page, row, is_open=is_open, humanizer=humanizer))
        self.assertNotIn("down", page.timeline.kinds())
        self.assertEqual(row.presses, [])

    async def test_click_control_uses_the_humanizer_not_a_native_click(self):
        page = _page()
        humanizer = RecordingHumanizer(page, page.timeline)
        control = page.add("switch", Field("switch", page=page))

        await click_control(page, control, humanizer=humanizer)

        kinds = page.timeline.kinds()
        self.assertEqual(control.click_count, 0)
        self.assertEqual(kinds.count("down"), 1)
        self.assertEqual(kinds.count("up"), 1)
        self.assertLess(kinds.index("hit-test"), kinds.index("down"))

    async def test_caption_clears_with_select_all_and_pays_one_after_type(self):
        page = _page()
        humanizer = RecordingHumanizer(page, page.timeline)
        editor = page.add("editor", Field("editor", page=page, value="旧配文"))

        await _type_caption(editor, "标题\n正文", humanizer)

        actions = page.keyboard.actions
        self.assertEqual(actions[0], ("press", "ControlOrMeta+A"))
        self.assertEqual(actions[1], ("press", "Delete"))
        self.assertIn(("insert_text", "标"), actions)
        self.assertIn(("insert_text", "题"), actions)
        self.assertIn(("press", "Enter"), actions)
        self.assertEqual(page.timeline.payloads("pause").count(("pause", "after_type")), 1)
        self.assertEqual(editor.fills, [])
        self.assertEqual(editor.click_count, 0)

    async def test_caption_is_narrowed_before_typing(self):
        page = _page()
        humanizer = RecordingHumanizer(page, page.timeline)
        editor = page.add("editor", Field("editor", page=page, count=2))

        with self.assertRaises(ElementUnusableError) as ctx:
            await _type_caption(editor, "配文", humanizer)
        self.assertIn("ambiguous:2", str(ctx.exception))
        self.assertEqual(page.keyboard.actions, [])

    async def test_create_entry_and_crop_next_pause_after_navigation(self):
        page = _page()
        humanizer = RecordingHumanizer(page, page.timeline)
        entry = page.add("entry", Field("entry", page=page))

        await _click_nav(entry, humanizer)

        events = page.timeline.events
        self.assertLess(events.index(("down",)), events.index(("pause", "after_navigate")))
        self.assertEqual(
            page.timeline.payloads("pause").count(("pause", "after_navigate")), 1
        )
        self.assertEqual(entry.click_count, 0)

    async def test_nav_helper_hovers_before_its_own_move_and_mouse_down(self):
        """真机 Instagram 左栏 hover 展开使包围盒漂移：先 ``hover`` 再 ``click``。

        spec §2.5.1 只在调用点加一次前置 hover，``Humanizer.click`` 内部零改动。
        两次 ``pointer_settle`` 把事件切成两段：hover 的移动爆发在前，click 自己
        的移动爆发与 ``down`` 在后。
        """
        page = _page()
        humanizer = RecordingHumanizer(page, page.timeline)
        entry = page.add("entry", Field("entry", page=page))

        await _click_nav(entry, humanizer)

        events = page.timeline.events
        moves = [index for index, event in enumerate(events) if event[0] == "move"]
        settles = [
            index
            for index, event in enumerate(events)
            if event == ("pause", "pointer_settle")
        ]
        down = page.timeline.kinds().index("down")
        # hover 一次 + click 一次；少于两次说明调用点没有前置 hover。
        self.assertEqual(len(settles), 2)
        self.assertTrue([index for index in moves if index < settles[0]])
        self.assertTrue([index for index in moves if settles[0] < index < settles[1]])
        self.assertLess(settles[1], down)
        self.assertEqual(page.timeline.kinds().count("down"), 1)
        self.assertEqual(entry.click_count, 0)

    async def test_share_waits_before_submit_before_dispatching(self):
        page = _page()
        humanizer = RecordingHumanizer(page, page.timeline)
        share = page.add("share", Field("share", page=page))

        await _click_submit(share, humanizer)

        events = page.timeline.events
        self.assertLess(
            events.index(("pause", "before_submit")), events.index(("hit-test", "share"))
        )
        self.assertLess(
            events.index(("hit-test", "share")), events.index(("down",))
        )
        self.assertEqual(
            page.timeline.payloads("pause").count(("pause", "before_submit")), 1
        )
        self.assertEqual(share.click_count, 0)

    async def test_optional_prompt_dismiss_goes_through_the_humanizer(self):
        page = _page()
        humanizer = RecordingHumanizer(page, page.timeline)
        guide = page.add("guide", Field("guide", page=page))
        dismiss = page.add("dismiss", Field("dismiss", page=page))

        class _Expectation:
            async def to_have_count(self, count: int, timeout=None) -> None:
                page.timeline.add("expect-count", count)

        with patch(
            "uploader.meta_uploader.insgraph_uploader.main.expect",
            lambda locator: _Expectation(),
        ):
            self.assertTrue(
                await _dismiss_optional_prompt(guide, dismiss, humanizer=humanizer)
            )

        kinds = page.timeline.kinds()
        self.assertLess(kinds.index("expect-count"), kinds.index("down"))
        self.assertEqual(dismiss.click_count, 0)
        self.assertEqual(kinds.count("down"), 1)

    async def test_location_typing_is_per_character_with_one_after_type(self):
        page = _page()
        humanizer = RecordingHumanizer(page, page.timeline)
        control = LocationControl(
            page, budget=StubBudget(1000), humanizer=humanizer
        )
        entry, candidate = _location_scene(page, "Shang hai")

        await control.set("Shang hai")

        presses = [action for action in page.keyboard.actions if action[0] == "press"]
        # Every character is its own key event; no ``press_sequentially``/``type``.
        self.assertEqual(len(presses), len("Shang hai"))
        self.assertEqual(
            page.timeline.payloads("pause").count(("pause", "after_type")), 1
        )
        self.assertEqual(entry.fills, [])
        self.assertEqual(candidate.click_count, 0)
        self.assertEqual(page.timeline.kinds().count("down"), 1)

    async def test_location_retry_clears_with_select_all_and_backspace(self):
        page = _page()
        humanizer = RecordingHumanizer(page, page.timeline)
        control = LocationControl(page, budget=StubBudget(0), humanizer=humanizer)
        entry, candidate = _location_scene(page, "Shanghai", suggestions_after=2)

        await control.set("Shanghai")

        actions = page.keyboard.actions
        self.assertEqual(actions[0], ("press", "S"))
        self.assertIn(("press", "ControlOrMeta+A"), actions)
        self.assertIn(("press", "Backspace"), actions)
        self.assertLess(
            actions.index(("press", "ControlOrMeta+A")),
            actions.index(("press", "Backspace")),
        )
        self.assertEqual(entry.value, "Shanghai")
        self.assertEqual(entry.fills, [])

    async def test_alt_text_clears_each_field_explicitly(self):
        page = _page()
        humanizer = RecordingHumanizer(page, page.timeline)
        first = Field("alt-1", page=page, value="旧一")
        second = Field("alt-2", page=page, value="旧二")
        control = _open_alt_control(page, humanizer, [first, second], image_count=2)

        await control.set(["第一张", "第二张"])

        for field, expected in ((first, "第一张"), (second, "第二张")):
            self.assertEqual(field.value, expected)
            self.assertEqual(field.focus_calls, 1)
            self.assertEqual(field.blurs, 1)
            self.assertEqual(field.fills, [])
        self.assertEqual(
            sum(1 for action in page.keyboard.actions if action == ("press", "ControlOrMeta+A")),
            2,
        )
        self.assertEqual(
            page.timeline.payloads("pause").count(("pause", "after_type")), 2
        )


# ---------------------------------------------------------------------------
# 2. Field-value readback
# ---------------------------------------------------------------------------


class InstagramHumanizeFieldReadbackTests(unittest.IsolatedAsyncioTestCase):
    """A correct sequence that ends with a dirty field must still fail."""

    async def test_caption_value_is_exactly_the_caption_and_crlf_is_normalised(self):
        page = _page()
        humanizer = RecordingHumanizer(page, page.timeline)
        editor = page.add("editor", Field("editor", page=page, value="旧配文"))

        await _type_caption(editor, "标题\r\n正文", humanizer)

        self.assertEqual(editor.value, "标题\n正文")

    async def test_caption_readback_accepts_br_rendered_inner_text(self):
        """Lexical 插 ``<br><br>``：``innerText`` 保留换行，``textContent`` 不保留。"""
        page = _page()
        caption = (
            "人类化回归 Reel 1113\n\n人类化交互层回归干跑。\n\n#回归测试 #自动化"
        )
        editor = Field("editor", page=page, text=caption)

        await _read_back_caption(
            editor, caption, page=page, budget=StubBudget(30_000)
        )

        # 首次采样即相等：不付任何轮询等待。
        self.assertEqual(page.wait_calls, [])

    async def test_caption_readback_polls_until_the_editor_catches_up(self):
        """单次采样不够：Lexical 落字可能晚一拍，回读必须轮询到相等或超时。"""
        page = _page()
        caption = "标题\n正文"

        class _CatchingUpEditor:
            """前两次探测还是旧值，第三次才与键入一致。"""

            def __init__(self) -> None:
                self.probes = 0

            async def inner_text(self) -> str:
                self.probes += 1
                return "标题" if self.probes < 3 else caption

        editor = _CatchingUpEditor()

        await _read_back_caption(
            editor, caption, page=page, budget=StubBudget(30_000)
        )

        self.assertEqual(editor.probes, 3)
        # 两次失败采样之间各付一次短轮询，而不是固定长眠。
        self.assertEqual(page.wait_calls, [200, 200])

    async def test_caption_readback_fails_loudly_when_the_probe_errors(self):
        """探测失败不得静默通过：异常向上抛，绝不把读不到的配文当成一致。"""
        page = _page()

        class _BrokenEditor:
            async def inner_text(self) -> str:
                raise RuntimeError("probe failed")

        with self.assertRaises(RuntimeError):
            await _read_back_caption(
                _BrokenEditor(), "标题", page=page, budget=StubBudget(30_000)
            )


    async def test_caption_readback_fails_on_a_single_missing_character(self):
        """丢一个字符也必须失败：只比较前缀或只比较开头会放过这种情况。"""
        page = _page()
        caption = "人类化回归 Reel 1113"
        editor = Field("editor", page=page, text="人类化回归 Reel 111")

        with self.assertRaises(AssertionError) as raised:
            await _read_back_caption(
                editor, caption, page=page, budget=StubBudget(1)
            )

        message = str(raised.exception)
        self.assertIn(repr(caption), message)
        self.assertIn(repr("人类化回归 Reel 111"), message)

    async def test_long_caption_is_one_bulk_insert(self):
        page = _page()
        humanizer = RecordingHumanizer(page, page.timeline)
        editor = page.add("editor", Field("editor", page=page, value="旧配文"))
        caption = "长" * 1001

        await _type_caption(editor, caption, humanizer)

        self.assertEqual(editor.value, caption)
        inserts = [
            action for action in page.keyboard.actions
            if action[0] == "insert_text"
        ]
        self.assertEqual(inserts, [("insert_text", caption)])
        self.assertNotIn(("press", "长"), page.keyboard.actions)

    async def test_long_alt_text_is_one_bulk_insert(self):
        page = _page()
        humanizer = RecordingHumanizer(page, page.timeline)
        field = Field("alt-1", page=page, value="旧值")
        control = _open_alt_control(page, humanizer, [field], image_count=1)
        text = "x" * 1001

        await control.set([text])

        self.assertEqual(field.value, text)
        inserts = [
            action for action in page.keyboard.actions
            if action[0] == "insert_text"
        ]
        self.assertEqual(inserts, [("insert_text", text)])

    async def test_location_readback_is_the_selected_candidate(self):
        page = _page()
        humanizer = RecordingHumanizer(page, page.timeline)
        control = LocationControl(page, budget=StubBudget(1000), humanizer=humanizer)
        entry, _candidate = _location_scene(page, "Shang hai")

        await control.set("Shang hai")

        self.assertEqual(entry.value, "Shang hai")
        self.assertEqual(await control.read(), "Shang hai")
        # The requested string was typed, not a normalised copy.
        self.assertEqual(
            "".join(
                action[1] for action in page.keyboard.actions
                if action[0] == "press" and len(action[1]) == 1
            ),
            "Shang hai",
        )

    async def test_location_typing_is_not_faster_than_the_type_delay_floor(self):
        page = _page()
        humanizer = RecordingHumanizer(page, page.timeline)
        control = LocationControl(page, budget=StubBudget(1000), humanizer=humanizer)
        requested = "Shang hai"
        _entry, _candidate = _location_scene(page, requested)

        await control.set(requested)

        sleeps = [value for _kind, value in page.timeline.payloads("sleep")]
        self.assertGreaterEqual(sum(sleeps), len(requested) * TYPE_DELAY_MS / 1000)

    async def test_alt_text_values_keep_image_order(self):
        page = _page()
        humanizer = RecordingHumanizer(page, page.timeline)
        first = Field("alt-1", page=page)
        second = Field("alt-2", page=page)
        control = _open_alt_control(page, humanizer, [first, second], image_count=2)

        await control.set(["第一张", "第二张"])

        self.assertEqual((first.value, second.value), ("第一张", "第二张"))


# ---------------------------------------------------------------------------
# 3. Switch click target: Instagram paints the switch in the input's parent
# ---------------------------------------------------------------------------

#: Instagram's real switch is an ``input[role=switch]`` styled ``opacity: 0``;
#: the visible track/thumb is its immediate parent.  Spec §2.6: click the
#: visible parent, never JS, never ``force``, never a keyboard fallback.
_SWITCH_SELECTOR = '[role="switch"], [role="checkbox"]'
_SWITCH_HOLDER_XPATH = (
    'xpath=ancestor-or-self::*'
    '[descendant-or-self::*[@role="switch"] or '
    'descendant-or-self::*[@role="checkbox"]][1]'
)
_PARENT_XPATH = "xpath=.."

_COMMENTS_LABELS = ("Turn off commenting", "关闭评论")
_AI_LABELS = ("Add AI label", "AI label", "AI 标签", "添加 AI 标签")


class _HiddenSwitch(Field):
    """The native switch: ``opacity: 0`` but still "visible" to Playwright.

    ``is_visible()`` ignores opacity, so the find step accepts the input — the
    live run then failed inside ``Humanizer.click`` at the ``interactive``
    probe with ``reason="opacity-zero"``.  ``utils.dom`` facts are overridden
    here so the double reproduces exactly that state.
    """

    def __init__(self, name: str, **kwargs) -> None:
        super().__init__(name, **kwargs)
        self.attributes_read: list[str] = []

    async def evaluate(self, expression, arg=None):
        if isinstance(expression, str) and "ancestorAriaHidden" in expression:
            self.evaluate_calls.append((expression, arg))
            return {**FACTS, "tag": "input", "opacity": 0.0}
        return await super().evaluate(expression, arg)

    async def get_attribute(self, name: str):
        self.attributes_read.append(name)
        return await super().get_attribute(name)


def _switch_chain(
    page: HumanizePage,
    name: str,
    *,
    checked: str = "false",
    ancestor_visible: bool = True,
    opacity_zero: bool = True,
) -> tuple[Field, Field, list[Field]]:
    """Wire ``input`` plus four ancestors; returns ``(switch, parent, chain)``.

    ``parent`` is the immediate wrapper (the visible track).  ``chain`` runs
    parent → great-great-grandparent so the four-level walk can be scripted
    invisible end to end.  Clicking the parent flips the input's
    ``aria-checked`` — readback must observe that on the input, not the wrapper.
    ``opacity_zero=False`` models a plain switch that is itself clickable (the
    pre-2026-11-13 fixtures and every non-IG toggle shape).
    """
    ancestors: list[Field] = []
    deeper: Field | None = None
    for level in range(4, 0, -1):
        parent = Field(
            f"{name}-ancestor-{level}",
            page=page,
            visible=ancestor_visible and level == 1,
            children={_PARENT_XPATH: deeper} if deeper is not None else None,
        )
        ancestors.insert(0, parent)
        deeper = parent
    attributes = {"role": "switch", "aria-checked": checked}
    switch: Field = (
        _HiddenSwitch(
            f"{name}-switch",
            page=page,
            attributes=attributes,
            children={_PARENT_XPATH: ancestors[0]},
        )
        if opacity_zero
        else Field(
            f"{name}-switch",
            page=page,
            attributes=attributes,
            children={_PARENT_XPATH: ancestors[0]},
        )
    )

    def flip() -> None:
        current = switch._attributes.get("aria-checked")
        switch._attributes["aria-checked"] = (
            "false" if current == "true" else "true"
        )

    ancestors[0].on_real_click = flip
    switch.on_real_click = flip
    return switch, ancestors[0], ancestors


def _dialog_with(
    page: HumanizePage,
    rows: dict[str, tuple[Field, Field, list[Field]]],
    *,
    labels: tuple[str, ...],
) -> Field:
    """Dialog double: every declared label resolves to its row, others empty."""
    children: dict[str, Field] = {}
    for label in labels:
        if label in rows:
            switch = rows[label][0]
            holder = Field(
                f"{label}-holder",
                page=page,
                children={
                    _SWITCH_SELECTOR: Field(
                        f"{label}-switches",
                        page=page,
                        items=[switch],
                        count=1,
                    )
                },
            )
            children[f"text:{label}:exact"] = Field(
                f"{label}-nodes",
                page=page,
                items=[
                    Field(
                        f"{label}-text",
                        page=page,
                        children={_SWITCH_HOLDER_XPATH: holder},
                    )
                ],
                count=1,
            )
        else:
            children[f"text:{label}:exact"] = Field(
                f"{label}-absent", page=page, count=0
            )
    # Structural fallback: no extra switches live directly under the dialog.
    children[_SWITCH_SELECTOR] = Field("dialog-switches", page=page, count=0)
    return Field("dialog", page=page, children=children)


def _comments_toggle(page: HumanizePage, humanizer: Humanizer) -> SwitchControl:
    return SwitchControl(
        page,
        labels=_COMMENTS_LABELS,
        panel_labels=("Advanced settings", "高级设置"),
        invert=True,
        humanizer=humanizer,
    )


class InstagramSwitchClickTargetTests(unittest.IsolatedAsyncioTestCase):
    """Spec §2.6: an opacity-zero switch is clicked through its visible parent.

    Readback must keep reading the real input (``aria-checked`` /
    ``is_checked``); only the click target moves.  No JS click, no ``force``,
    no retry — an unreachable switch keeps the original hard error.
    """

    async def test_opacity_zero_switch_clicks_the_visible_parent(self):
        page = _page()
        humanizer = RecordingHumanizer(page, page.timeline)
        switch, parent, _chain = _switch_chain(page, "comments")
        page.add(
            "role:dialog",
            _dialog_with(
                page, {"Turn off commenting": (switch, parent, _chain)},
                labels=_COMMENTS_LABELS,
            ),
        )
        control = _comments_toggle(page, humanizer)

        # invert=True: aria-checked=false means commenting is still enabled, so
        # requesting comments off (set(False)) must click exactly once.
        await control.set(False)

        self.assertEqual(parent.click_count, 0)
        self.assertEqual(switch.click_count, 0)
        # The click was dispatched on the wrapper: its hit-test ran and its
        # real click flipped the input's aria-checked.
        self.assertIn(("hit-test", parent.name), page.timeline.events)
        self.assertNotIn(("hit-test", switch.name), page.timeline.events)
        self.assertEqual(page.timeline.kinds().count("down"), 1)
        self.assertEqual(page.timeline.kinds().count("up"), 1)
        self.assertNotIn("locator.click", page.timeline.kinds())
        # Readback (before and after the click) stayed on the real switch.
        self.assertIn("aria-checked", switch.attributes_read)
        self.assertIs(await control.read(), False)

    async def test_no_visible_ancestor_keeps_the_opacity_zero_hard_error(self):
        page = _page()
        humanizer = RecordingHumanizer(page, page.timeline)
        switch, parent, chain = _switch_chain(
            page, "comments", ancestor_visible=False
        )
        page.add(
            "role:dialog",
            _dialog_with(
                page, {"Turn off commenting": (switch, parent, chain)},
                labels=_COMMENTS_LABELS,
            ),
        )
        control = _comments_toggle(page, humanizer)

        with self.assertRaises(ElementUnusableError) as ctx:
            await control.set(False)

        self.assertEqual(ctx.exception.reason, "opacity-zero")
        self.assertEqual(ctx.exception.role, "interactive")
        self.assertIs(ctx.exception.publish_clicked, False)
        # Fallback target is the switch itself: the error is the original one,
        # and nothing was clicked (no native click, no mouse.down).
        self.assertEqual(switch.click_count, 0)
        for ancestor in chain:
            self.assertEqual(ancestor.click_count, 0)
        self.assertNotIn("down", page.timeline.kinds())

    async def test_comments_and_ai_label_controls_both_click_the_visible_parent(self):
        page = _page()
        humanizer = RecordingHumanizer(page, page.timeline)
        comments = _switch_chain(page, "comments")
        ai = _switch_chain(page, "ai")
        page.add(
            "role:dialog",
            _dialog_with(
                page,
                {
                    "Turn off commenting": comments,
                    "Add AI label": ai,
                },
                labels=_COMMENTS_LABELS + _AI_LABELS,
            ),
        )
        controls = resolve_instagram_option_controls(
            page, image_count=1, humanizer=humanizer
        )

        await controls["comments"].set(False)
        await controls["ai_generated"].set(True)

        for name, (switch, parent, _chain) in (
            ("comments", comments),
            ("ai_generated", ai),
        ):
            with self.subTest(control=name):
                self.assertEqual(parent.click_count, 0)
                self.assertEqual(switch.click_count, 0)
                self.assertIn(("hit-test", parent.name), page.timeline.events)
                self.assertIn("aria-checked", switch.attributes_read)
        self.assertEqual(page.timeline.kinds().count("down"), 2)
        self.assertEqual(page.timeline.kinds().count("up"), 2)
        self.assertNotIn("locator.click", page.timeline.kinds())
        self.assertIs(await controls["comments"].read(), False)
        self.assertIs(await controls["ai_generated"].read(), True)

    async def test_a_visible_switch_is_clicked_directly(self):
        """Only an unusable switch moves the target; every other click is unchanged.

        The shared visibility check accepts a normal switch (opacity 1), so the
        click stays on the switch itself — the same target and coordinates as
        before this ticket.
        """
        page = _page()
        humanizer = RecordingHumanizer(page, page.timeline)
        switch, parent, chain = _switch_chain(
            page, "comments", opacity_zero=False
        )
        page.add(
            "role:dialog",
            _dialog_with(
                page, {"Turn off commenting": (switch, parent, chain)},
                labels=_COMMENTS_LABELS,
            ),
        )
        control = _comments_toggle(page, humanizer)

        await control.set(False)

        self.assertEqual(switch.click_count, 0)  # humanized: no native click
        self.assertEqual(parent.click_count, 0)
        self.assertIn(("hit-test", switch.name), page.timeline.events)
        self.assertNotIn(("hit-test", parent.name), page.timeline.events)
        self.assertEqual(page.timeline.kinds().count("down"), 1)
        self.assertIs(await control.read(), False)

    async def test_fast_path_still_clicks_once_on_the_visible_parent(self):
        """``HUMANIZE=0``: one native click, zero pauses — same target.

        The fast path deliberately resolves the same click target as the
        humanized path, so a mode switch cannot change what gets clicked.  One
        ``locator.click`` lands on the visible parent; there is no
        ``mouse.down`` and no pause at all.
        """
        page = _page()
        switch, parent, chain = _switch_chain(page, "comments")
        page.add(
            "role:dialog",
            _dialog_with(
                page, {"Turn off commenting": (switch, parent, chain)},
                labels=_COMMENTS_LABELS,
            ),
        )
        with patch.dict(os.environ, {"HUMANIZE": "0"}):
            humanizer = Humanizer(page, sleep=page.timeline.sleep)
        self.assertFalse(humanizer.enabled)
        control = _comments_toggle(page, humanizer)

        await control.set(False)

        self.assertEqual(parent.click_count, 1)
        self.assertEqual(switch.click_count, 0)
        self.assertEqual(page.timeline.kinds().count("locator.click"), 1)
        self.assertNotIn("down", page.timeline.kinds())
        self.assertEqual(page.timeline.payloads("pause"), [])
        self.assertIs(await control.read(), False)


# ---------------------------------------------------------------------------
# 4. Package gates A–E
# ---------------------------------------------------------------------------


class InstagramHumanizeGateTests(unittest.TestCase):
    """Spec §4 executable gates plus the ticket's own forbidden constructs."""

    def test_gates_a_to_e_pass_on_the_instagram_package(self):
        assert_clean(PACKAGE)

    def test_no_fill_press_sequentially_or_forced_clicks_remain(self):
        hits = []
        for path in sorted(PACKAGE.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else ""
                if name in {"fill", "press_sequentially"}:
                    hits.append(f"{path.name}:{node.lineno}: {name}()")
                if any(
                    keyword.arg == "force"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                    for keyword in node.keywords
                ):
                    hits.append(f"{path.name}:{node.lineno}: force=True")
        self.assertEqual(hits, [])

    def test_both_nav_call_sites_go_through_the_hovering_helper(self):
        """创建入口与向导 Next 都走 ``_click_nav``，helper 内 hover 先于 click。

        静态哨兵：任何新增的导航点击若绕过 helper（直接 ``humanizer.click``），
        或 helper 里 hover/click 的顺序被调换，都必须在这里失败。
        """
        source = (PACKAGE / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        helper_calls = sorted(
            (node.lineno, f"{node.func.value.id}.{node.func.attr}")
            for node in ast.walk(functions["_click_nav"])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
        )
        self.assertEqual(
            [call for _line, call in helper_calls],
            ["humanizer.hover", "humanizer.click", "humanizer.after_navigate"],
        )

        nav_sites = []
        for name, function in functions.items():
            for node in ast.walk(function):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "_click_nav"
                ):
                    nav_sites.append((node.lineno, name, ast.unparse(node.args[0])))
        # 创建入口（_upload_files）与向导「Next」（_advance_media_editor）；
        # 新站点若不走 helper 会在这里暴露。
        self.assertEqual(
            [site[1:] for site in sorted(nav_sites)],
            [("_upload_files", "entry"), ("_advance_media_editor", "action")],
        )

        owners = set()
        for name, function in functions.items():
            for node in ast.walk(function):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "click"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "humanizer"
                ):
                    owners.add(name)
        self.assertEqual(
            owners, {"_click_nav", "_click_submit", "_dismiss_optional_prompt"}
        )

    def test_caption_readback_compares_rendered_text_not_to_have_text(self):
        """回归：``to_have_text`` 走 ``textContent``，会丢掉 Lexical 的换行。

        真机 2026-11-13（ticket 05）在 ``_publish`` 的配文回读处失败：逐字输入把
        ``\\n`` 打成 Enter，Lexical 在段间插 ``<br><br>``，``textContent`` 把
        两行粘在一起而 ``innerText`` 保留换行。哨兵：``_publish`` 不得再对配文
        调用 ``to_have_text``，且读回 helper 必须取渲染文本。
        """
        source = (PACKAGE / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        publish_source = ast.unparse(functions["_publish"])
        self.assertNotIn("to_have_text", publish_source)
        self.assertIn("_read_back_caption", publish_source)

        self.assertIn("inner_text()", ast.unparse(functions["_read_back_caption"]))

    def test_native_clicks_are_only_the_management_path(self):
        # Gate B already enforces markers; this pins the *set* of marked sites so
        # a new native click cannot silently join the package.
        marker = re.compile(r"# native-click: ([A-Za-z]+)；")
        classes = []
        for path in sorted(PACKAGE.rglob("*.py")):
            classes.extend(marker.findall(path.read_text(encoding="utf-8")))
        self.assertEqual(sorted(set(classes)), ["file", "manage"])


# ---------------------------------------------------------------------------
# 5. HUMANIZE=0 fast path
# ---------------------------------------------------------------------------


class InstagramHumanizeFastPathTests(unittest.IsolatedAsyncioTestCase):
    """Spec §2.3: one bulk insert, one ``locator.click``, zero pauses."""

    def _uploader(self) -> InstagramUploader:
        return InstagramUploader(
            "unused.json", title="配文", image_files=["image.png"]
        )

    async def test_fast_path_typing_and_clicking(self):
        page = _page()
        editor = page.add("editor", Field("editor", page=page, value="旧配文"))
        entry = page.add("entry", Field("entry", page=page))
        pauses: list[float] = []

        async def record(seconds: float) -> None:
            pauses.append(seconds)

        with patch.dict(os.environ, {"HUMANIZE": "0"}):
            uploader = self._uploader()
            with patch.object(InstagramUploader, "_humanize_pause", record):
                humanizer = uploader._humanizer(page)
            self.assertFalse(humanizer.enabled)

            await _type_caption(editor, "标题\n正文", humanizer)
            await _click_nav(entry, humanizer)

        self.assertEqual(editor.value, "标题\n正文")
        self.assertEqual(
            [action for action in page.keyboard.actions if action[0] == "insert_text"],
            [("insert_text", "标题\n正文")],
        )
        self.assertEqual(
            [action for action in page.keyboard.actions if action[0] == "press"],
            [("press", "ControlOrMeta+A"), ("press", "Delete")],
        )
        self.assertEqual(entry.click_count, 1)
        # 导航入口的 hover 先于 click；关闭人类化时是直通 locator.hover。
        self.assertEqual(entry.hovers, 1)
        self.assertLess(
            page.timeline.kinds().index("locator.hover"),
            page.timeline.kinds().index("locator.click"),
        )
        self.assertEqual(page.timeline.kinds().count("locator.click"), 1)
        self.assertEqual(page.timeline.kinds().count("down"), 0)
        self.assertEqual(pauses, [])
        self.assertEqual(page.timeline.payloads("pause"), [])

    async def test_fast_path_is_a_fresh_snapshot_per_instance(self):
        page = _page()
        with patch.dict(os.environ, {"HUMANIZE": "0"}):
            disabled = self._uploader()._humanizer(page)
        with patch.dict(os.environ, {"HUMANIZE": "1"}):
            enabled = self._uploader()._humanizer(page)
        self.assertFalse(disabled.enabled)
        self.assertTrue(enabled.enabled)


# ---------------------------------------------------------------------------
# scene helpers
# ---------------------------------------------------------------------------


def _open_alt_control(
    page: HumanizePage,
    humanizer: Humanizer,
    fields: list[Field],
    *,
    image_count: int,
) -> AltTextControl:
    """``AltTextControl`` with the accordion replaced by the typed fields."""
    inputs = Field("inputs", page=page, items=fields, count=len(fields))

    class _Control(AltTextControl):
        async def _ensure_open(self):
            return True, True

        async def _inputs(self):
            return inputs

        async def _collapse(self):
            return None

    return _Control(page, image_count=image_count, humanizer=humanizer)


def _location_scene(
    page: HumanizePage,
    requested: str,
    *,
    suggestions_after: int = 1,
) -> tuple[Field, Field]:
    """Wire the location input, its portal list and the exact-match row.

    ``suggestions_after`` models Instagram's debounce: the first N scans return
    an empty list (the list has not rendered yet).
    """
    labels = ["Shanghai, China", requested]
    rows = [{"index": index, "label": label} for index, label in enumerate(labels)]
    entry = Field("location-entry", page=page)
    candidate = Field("suggestion", page=page)
    scans = {"value": 0}

    def candidate_ready() -> bool:
        return scans["value"] >= suggestions_after

    def on_evaluate(field: Field, expression, arg):
        if isinstance(arg, dict) and "stamp" in arg:
            # JS stamps the exact-match row so the caller can click a Locator.
            if not candidate_ready():
                return False
            page.add(f'[data-instagram-suggestion="{arg["stamp"]}"]', candidate)
            return True
        if isinstance(arg, dict):
            return False
        scans["value"] += 1
        return list(rows) if candidate_ready() else []

    entry._evaluate_handler = on_evaluate
    candidate.on_real_click = lambda: (
        setattr(entry, "value", requested),
        setattr(candidate, "detached", True),
    )

    def dialog_locator(selector: str) -> Field:
        if selector in ENTRY_SELECTORS or ", " in selector:
            return entry
        raise UnscriptedSelectorError(f"location: un-scripted selector {selector!r}")

    dialog = Field("dialog", page=page, locator_handler=dialog_locator)
    page.add("role:dialog", dialog)
    for selector in ENTRY_SELECTORS:
        page.add(selector, entry)
    page.add(", ".join(ENTRY_SELECTORS), entry)
    return entry, candidate


if __name__ == "__main__":
    unittest.main()
