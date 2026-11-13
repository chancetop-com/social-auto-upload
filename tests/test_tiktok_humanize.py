# -*- coding: utf-8 -*-
"""TikTok humanized interaction layer (ticket 03).

Three offline blocks, per spec §6.2:

1. **event sequence** — every converted point uses the right primitive
   (``press`` vs ``insert_text``), one ``after_type`` per text field,
   ``stillOn`` hit-test *before* ``mouse.down``, and zero native clicks /
   ``force`` dispatches on the humanized paths.
2. **field-value readback** — a buffer-holding editor double proves the
   Draft.js clear sequence really empties the caption and the hashtag is
   typed character by character, picked by exact first-line text; >1000 code
   points degrade to a single bulk ``insert_text``; ``HUMANIZE=0`` collapses
   typing and clicking to the fast path.
3. **static gate** — ``tests.humanize_gates.assert_clean`` over the shipped
   TikTok module (gates A–E).

The doubles are local to this file, fail loudly on un-scripted selectors and
never need a browser.
"""

from __future__ import annotations

import ast
import os
import re
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from uploader.tk_uploader import main_chrome as tk_main
from uploader.tk_uploader.main_chrome import TiktokNote, TiktokPublishOptions, TiktokVideo
from utils.dom import ElementUnusableError

TK_PACKAGE = Path(__file__).resolve().parent.parent / "uploader" / "tk_uploader"
TK_MAIN_CHROME = TK_PACKAGE / "main_chrome.py"

#: Facts payload ``utils.dom._probe`` expects.  Anything else (visibility,
#: disabled flags) defaults to "interactive".
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

UNSCRIPTED = AssertionError


def _box(x: float, y: float, width: float = 80.0, height: float = 20.0):
    return {"x": x, "y": y, "width": width, "height": height}


class FakeNode:
    """Scripted Playwright locator double.

    ``page`` receives every interaction (``events``).  ``on_down`` fires when
    the pointer is pressed inside this node's box, which lets a test model
    "the click landed on the suggestion" without a real browser.
    """

    def __init__(
        self,
        name: str,
        *,
        page: "FakePage",
        box: dict | None = None,
        text: str = "",
        count: int | None = None,
        visible: bool = True,
        enabled: bool = True,
        children: dict[str, "FakeNode"] | None = None,
        items: list["FakeNode"] | None = None,
        click_error: BaseException | None = None,
        on_down=None,
    ) -> None:
        self.name = name
        self.page = page
        self.box = box if box is not None else _box(10.0, 10.0)
        self.text = text
        self._count = count
        self._visible = visible
        self._enabled = enabled
        self._children = dict(children or {})
        self._items = items
        self.click_error = click_error
        self.on_down = on_down
        self.actions: list[tuple] = []
        self.native_click_calls = 0
        self.fill_calls: list[str] = []
        self.wait_calls: list[dict] = []
        page.nodes.append(self)

    # -- structure ------------------------------------------------------
    def _scripted_count(self) -> int:
        if self._count is not None:
            return self._count
        if self._items is not None:
            return len(self._items)
        return 1

    async def count(self) -> int:
        return self._scripted_count()

    @property
    def first(self) -> "FakeNode":
        return self._items[0] if self._items else self

    @property
    def last(self) -> "FakeNode":
        return self._items[-1] if self._items else self

    def nth(self, index: int) -> "FakeNode":
        if self._items is not None:
            return self._items[index]
        if index == 0:
            return self
        raise IndexError(f"{self.name}: no scripted nth({index})")

    def locator(self, selector: str) -> "FakeNode":
        try:
            return self._children[selector]
        except KeyError as exc:
            raise UNSCRIPTED(
                f"{self.name}: un-scripted child {selector!r}; "
                f"scripted={sorted(self._children)}"
            ) from exc

    def get_by_role(self, role: str, name=None) -> "FakeNode":
        key = f"role:{role}:{name}"
        try:
            return self._children[key]
        except KeyError as exc:
            raise UNSCRIPTED(
                f"{self.name}: un-scripted {key!r}; "
                f"scripted={sorted(self._children)}"
            ) from exc

    def get_by_text(self, text: str, exact: bool = False) -> "FakeNode":
        key = f"text:{text}:exact" if exact else f"text:{text}"
        try:
            return self._children[key]
        except KeyError as exc:
            raise UNSCRIPTED(
                f"{self.name}: un-scripted {key!r}; "
                f"scripted={sorted(self._children)}"
            ) from exc

    def filter(self, has_text=None) -> "FakeNode":
        self.actions.append(("filter", has_text))
        return self

    # -- read state -----------------------------------------------------
    async def get_attribute(self, name: str):
        if name == "aria-disabled":
            return "true" if not self._enabled else "false"
        if name == "class":
            return ""
        if name == "aria-selected":
            return "false"
        return None

    async def is_visible(self) -> bool:
        return self._visible

    async def is_enabled(self) -> bool:
        return self._enabled

    async def is_checked(self) -> bool:
        return False

    async def is_disabled(self) -> bool:
        return not self._enabled

    async def inner_text(self) -> str:
        return self.text

    async def text_content(self) -> str:
        return self.text

    async def bounding_box(self):
        return dict(self.box) if self.box else None

    async def evaluate(self, expression, arg=None):
        self.actions.append(("evaluate", expression, arg))
        text = str(expression)
        self.page.events.append(("evaluate", self.name))
        if "elementFromPoint" in text:
            self.page.events.append(("hit-test", self.name))
            return {
                "self": True,
                "tag": "div",
                "className": "",
                "id": "",
                "text": "",
            }
        if "innerWidth" in text:
            width = float(self.box["width"]) if self.box else 0.0
            height = float(self.box["height"]) if self.box else 0.0
            return {
                "width": width,
                "height": height,
                "inside": bool(width and height),
                "clipped": False,
                "childFrame": False,
            }
        return dict(FACTS)

    # -- actions --------------------------------------------------------
    async def click(self, **kwargs) -> None:
        self.native_click_calls += 1
        self.actions.append(("click", dict(kwargs)))
        self.page.events.append(("native-click", self.name))
        if self.click_error is not None:
            raise self.click_error

    async def fill(self, value: str, **kwargs) -> None:
        self.fill_calls.append(value)
        self.actions.append(("fill", value))

    async def focus(self, **kwargs) -> None:
        self.actions.append(("focus",))

    async def hover(self, **kwargs) -> None:
        self.actions.append(("hover",))

    async def wait_for(self, **kwargs) -> None:
        self.wait_calls.append(dict(kwargs))

    async def scroll_into_view_if_needed(self, **kwargs) -> None:
        self.actions.append(("scroll",))

    async def set_input_files(self, files) -> None:
        self.actions.append(("set_input_files", files))


class EditorNode(FakeNode):
    """Draft.js-like editor double that holds the typed buffer."""

    def __init__(self, name: str, *, page: "FakePage", initial: str = "") -> None:
        super().__init__(name, page=page, box=_box(0.0, 0.0, 300.0, 120.0))
        self.buffer = initial
        self.selected = False


class FakeMouse:
    def __init__(self, page: "FakePage") -> None:
        self.page = page
        self.actions: list[tuple] = []
        self.down_count = 0
        self.up_count = 0
        self.down_error: BaseException | None = None

    async def move(self, x: float, y: float, **kwargs) -> None:
        self.actions.append(("move", x, y))
        self.page.last_point = (x, y)
        self.page.events.append(("move", x, y))

    async def down(self, **kwargs) -> None:
        self.actions.append(("down",))
        self.down_count += 1
        self.page.events.append(("down",))
        if self.down_error is not None:
            raise self.down_error
        self.page.press_at(*self.page.last_point)

    async def up(self, **kwargs) -> None:
        self.actions.append(("up",))
        self.up_count += 1
        self.page.events.append(("up",))

    async def wheel(self, delta_x: float, delta_y: float, **kwargs) -> None:
        self.actions.append(("wheel", delta_x, delta_y))


class FakeKeyboard:
    """Routes real ``press`` / ``insert_text`` into the editor buffer."""

    def __init__(self, page: "FakePage") -> None:
        self.page = page
        self.actions: list[tuple] = []

    async def press(self, key: str, **kwargs) -> None:
        self.actions.append(("press", key))
        self.page.events.append(("press", key))
        editor = self.page.editor
        if editor is None:
            return
        if key == "ControlOrMeta+A":
            editor.selected = True
        elif key == "Delete":
            if editor.selected:
                editor.buffer = ""
                editor.selected = False
        elif key == "Enter":
            editor.buffer += "\n"
        elif key == "Space":
            editor.buffer += " "
        elif len(key) == 1:
            editor.buffer += key

    async def insert_text(self, text: str, **kwargs) -> None:
        self.actions.append(("insert_text", text))
        self.page.events.append(("insert_text", text))
        if self.page.editor is not None:
            self.page.editor.buffer += text

    async def type(self, text: str, delay=None, **kwargs) -> None:
        await self.insert_text(text)


class FakePage:
    def __init__(self) -> None:
        self.url = "https://www.tiktok.com/tiktokstudio/upload?lang=en"
        self.events: list[tuple] = []
        self.nodes: list[FakeNode] = []
        self.selectors: dict[str, FakeNode] = {}
        self.roles: dict[str, FakeNode] = {}
        self.texts: dict[str, FakeNode] = {}
        self.editor: EditorNode | None = None
        self.last_point: tuple[float, float] = (0.0, 0.0)
        self.waits: list[float] = []
        self.mouse = FakeMouse(self)
        self.keyboard = FakeKeyboard(self)
        self.pressed: list[FakeNode] = []
        self.wait_for_url_error: BaseException | None = None
        self.wait_for_url_calls = 0
        self.expect_file_chooser_calls = 0

    def expect_file_chooser(self, *, timeout=None):
        # Counted before refusing so a wrongly-opened chooser is still visible
        # in ``expect_file_chooser_calls`` after the code swallows the error.
        self.expect_file_chooser_calls += 1
        raise AssertionError(
            "TikTok cover must write the existing hidden input directly"
        )

    # -- selector maps ---------------------------------------------------
    def locator(self, selector: str) -> FakeNode:
        try:
            return self.selectors[selector]
        except KeyError as exc:
            raise UNSCRIPTED(
                f"page: un-scripted selector {selector!r}; "
                f"scripted={sorted(self.selectors)}"
            ) from exc

    def get_by_role(self, role: str, name=None) -> FakeNode:
        key = f"{role}:{name}"
        try:
            return self.roles[key]
        except KeyError as exc:
            raise UNSCRIPTED(
                f"page: un-scripted role {key!r}; scripted={sorted(self.roles)}"
            ) from exc

    def get_by_text(self, text: str, exact: bool = False) -> FakeNode:
        key = f"{text}:{exact}"
        try:
            return self.texts[key]
        except KeyError as exc:
            raise UNSCRIPTED(
                f"page: un-scripted text {key!r}; scripted={sorted(self.texts)}"
            ) from exc

    # -- humanizer plumbing ---------------------------------------------
    def press_at(self, x: float, y: float) -> None:
        self.last_point = (x, y)
        for node in self.nodes:
            if node.box is None:
                continue
            left = float(node.box["x"])
            top = float(node.box["y"])
            right = left + float(node.box["width"])
            bottom = top + float(node.box["height"])
            if left <= x <= right and top <= y <= bottom:
                node.actions.append(("pointer-down", x, y))
                self.pressed.append(node)
                if node.on_down is not None:
                    node.on_down()

    async def wait_for_timeout(self, milliseconds: float) -> None:
        self.waits.append(milliseconds)

    async def wait_for_url(self, *args, **kwargs) -> None:
        self.wait_for_url_calls += 1
        if self.wait_for_url_error is not None:
            raise self.wait_for_url_error


def _video(**kwargs) -> TiktokVideo:
    options = kwargs.pop("options", TiktokPublishOptions())
    return TiktokVideo(
        "caption", "/tmp/demo.mp4", [], 0, None, options=options, **kwargs
    )


@contextmanager
def _silent_humanizer_sleep():
    """Swallow the platform's budget-clamped sleeps (they are wall-clock)."""

    async def _sleep(_seconds: float) -> None:
        return None

    with patch.object(tk_main.asyncio, "sleep", _sleep):
        yield


def _pause_recorder(video, page):
    """Humanizer whose pauses are appended to ``page.events``.

    The pause tail of the hover burst is otherwise invisible: it is a platform
    sleep, not a pointer event.
    """
    pauses: list[float] = []

    async def _pause(seconds: float) -> None:
        pauses.append(seconds)
        page.events.append(("pause", seconds))

    video._humanize_pause = _pause  # type: ignore[assignment]
    return video._humanizer(page), pauses


def _pointer_call_spy(humanizer):
    """Record ``hover``/``click`` in call order, then delegate."""
    calls: list[tuple[str, object]] = []
    hover = humanizer.hover
    click = humanizer.click

    async def _hover(locator, **kwargs):
        calls.append(("hover", locator))
        await hover(locator, **kwargs)

    async def _click(locator, **kwargs):
        calls.append(("click", locator))
        await click(locator, **kwargs)

    humanizer.hover = _hover  # type: ignore[assignment]
    humanizer.click = _click  # type: ignore[assignment]
    return calls


def _assert_hover_burst_precedes_the_press(case, page) -> None:
    """The hover burst/settle must close before the click's own burst."""
    names = [event[0] for event in page.events]
    case.assertEqual(names.count("down"), 1)
    case.assertEqual(page.mouse.down_count, 1)
    down = names.index("down")
    moves = [index for index, name in enumerate(names) if name == "move"]
    settles = [
        index
        for index, event in enumerate(page.events)
        if event[0] == "pause" and event[1] >= 0.1
    ]
    hover_settle = next(
        index
        for index in settles
        if index < down and any(move < index for move in moves)
    )
    case.assertTrue([index for index in moves if index < hover_settle], names)
    case.assertTrue(
        [index for index in moves if hover_settle < index < down], names
    )
    click_settle = next(
        index for index in settles if hover_settle < index < down
    )
    case.assertGreater(
        click_settle, max(index for index in moves if index < down)
    )


def _hashtag_page(*, option_texts=()) -> tuple[FakePage, FakeNode]:
    page = FakePage()
    page.editor = EditorNode("editor", page=page)
    base = FakeNode("base", page=page, children={"div.public-DraftEditor-content": page.editor})

    options: list[FakeNode] = []
    for position, text in enumerate(option_texts):
        node = FakeNode(
            f"option::{text.splitlines()[0]}",
            page=page,
            text=text,
            box=_box(400.0, 300.0 + 30.0 * position, 200.0, 24.0),
        )
        if text.startswith("#"):
            node.on_down = lambda node=node: page.pressed.append(node)
        options.append(node)
    option_list = FakeNode("options", page=page, items=options)
    page.selectors['[role="option"]'] = option_list
    base._children['[role="option"]'] = FakeNode(
        "base-options", page=page, count=0, items=[]
    )
    # ``_wait_for_no_options`` polls until the suggestion list closes.
    def _close() -> None:
        for node in options:
            if node in option_list._items:
                option_list._items.remove(node)
                break

    for node in options:
        node.on_down = _close
    page.selectors['[role="dialog"]'] = FakeNode(
        "dialogs", page=page, count=0
    )
    page.selectors["#react-joyride-portal"] = FakeNode(
        "joyride", page=page, count=0
    )
    return page, base


class CaptionSequenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_caption_clear_sequence_and_per_character_typing(self):
        page, base = _hashtag_page()
        video = _video()
        video.locator_base = base
        humanizer = video._humanizer(page)

        with _silent_humanizer_sleep():
            await video.fill_caption(page, "Hi", [])

        # The platform's own sequence is preserved; every key is humanized.
        presses = [action[1] for action in page.keyboard.actions if action[0] == "press"]
        self.assertEqual(
            presses[:4], ["End", "ControlOrMeta+A", "Delete", "End"], presses
        )
        self.assertEqual(presses[4:6], ["H", "i"], presses)
        self.assertNotIn(("insert_text", "Hi"), page.keyboard.actions)
        # ASCII goes through real key presses, not insert_text.
        self.assertNotIn(("insert_text", "H"), page.keyboard.actions)
        # Editor click is a coordinate click (stillOn hit-test before down).
        self.assertEqual(page.mouse.down_count, 1)
        self.assertEqual(page.editor.native_click_calls, 0)
        names = [event[0] for event in page.events]
        self.assertLess(names.index("hit-test"), names.index("down"))
        # One cached instance per page.
        self.assertIs(video._humanizer(page), humanizer)

    async def test_long_caption_is_one_bulk_insert(self):
        page, base = _hashtag_page()
        video = _video()
        video.locator_base = base

        text = "a" * 1001
        with _silent_humanizer_sleep():
            await video.fill_caption(page, text, [])

        inserts = [action for action in page.keyboard.actions if action[0] == "insert_text"]
        self.assertEqual(inserts, [("insert_text", text)])
        presses = [action[1] for action in page.keyboard.actions if action[0] == "press"]
        self.assertNotIn("a", presses)
        self.assertEqual(page.editor.buffer, text + "\n")

    async def test_hashtag_exact_candidate_is_clicked_without_native_click(self):
        page, base = _hashtag_page(
            option_texts=["#tiktok\n2.0B posts", "#tiktokshop\n175.4M posts"]
        )
        video = _video()
        video.locator_base = base

        with _silent_humanizer_sleep():
            self.assertTrue(await video._apply_hashtag(page, "tiktok"))

        # Character-by-character typing, no bulk insert.
        self.assertEqual(
            [action for action in page.keyboard.actions if action[0] == "press"],
            [("press", char) for char in "#tiktok"],
        )
        self.assertEqual(
            [action for action in page.keyboard.actions if action[0] == "insert_text"],
            [],
        )
        option = page.nodes[2]
        self.assertIn(option, page.pressed)
        self.assertEqual(option.native_click_calls, 0)
        self.assertNotIn(("press", "Space"), page.keyboard.actions)
        # stillOn runs before the pointer is pressed.
        names = [event[0] for event in page.events]
        self.assertLess(names.index("hit-test"), names.index("down"))

    async def test_hashtag_miss_keeps_plain_text_and_does_not_abort(self):
        page, base = _hashtag_page(option_texts=[])
        video = _video()
        video.locator_base = base

        with patch.object(tk_main, "TIKTOK_HASHTAG_SUGGESTION_TIMEOUT_MS", 0), \
                patch.object(tk_main, "TIKTOK_HASHTAG_SETTLE_MS", 0), \
                _silent_humanizer_sleep():
            self.assertFalse(await video._apply_hashtag(page, "tiktok"))

        self.assertIn(("press", "Space"), page.keyboard.actions)
        self.assertEqual(page.editor.buffer, "#tiktok ")
        self.assertEqual(page.mouse.down_count, 0)

    async def test_photos_tab_switch_pays_after_navigate(self):
        page = FakePage()
        note = TiktokNote(["/tmp/a.png"], "note", [], 0, None)
        calls: list[str] = []

        photo_input = FakeNode("photo-input", page=page, count=0)
        page.selectors['input[type="file"][accept*="image"]'] = photo_input
        tab = FakeNode("photos-tab", page=page, text="Photos")
        tab.on_down = lambda: (
            setattr(photo_input, "_count", 1),
            calls.append("tab-down"),
        )
        page.roles["tab:Photos"] = tab

        humanizer = note._humanizer(page)
        original = humanizer.after_navigate

        async def _after_navigate() -> None:
            calls.append("after_navigate")
            await original()

        humanizer.after_navigate = _after_navigate  # type: ignore[assignment]
        with _silent_humanizer_sleep():
            await note.ensure_mode(page)

        self.assertEqual(calls, ["tab-down", "after_navigate"])
        self.assertEqual(tab.native_click_calls, 0)

    async def test_option_control_base_clicks_label_body_not_hidden_input(self):
        page = FakePage()
        label = FakeNode("label-body", page=page, box=_box(40.0, 40.0, 120.0, 24.0))
        checkbox = FakeNode(
            "checkbox",
            page=page,
            count=1,
            children={"xpath=ancestor-or-self::label[1]": label},
        )
        video = _video()
        humanizer = video._humanizer(page)
        control = tk_main._LocatorControl(checkbox, humanizer=humanizer)

        with _silent_humanizer_sleep():
            await control.click()

        self.assertEqual(page.mouse.down_count, 1)
        self.assertIn(label, page.pressed)
        self.assertNotIn(checkbox, page.pressed)
        self.assertEqual(checkbox.native_click_calls, 0)
        self.assertEqual(label.native_click_calls, 0)

    async def test_publish_click_pays_before_submit_then_still_on(self):
        page = FakePage()
        button = FakeNode("publish", page=page)
        base = FakeNode(
            "base",
            page=page,
            children={'[data-e2e="post_video_button"]': button},
        )
        video = _video()
        video.locator_base = base
        page.wait_for_url_error = RuntimeError("navigation failed")

        humanizer = video._humanizer(page)
        order: list[str] = []
        original_click = humanizer.click
        original_before = humanizer.before_submit

        async def _before_submit() -> None:
            order.append("before_submit")
            await original_before()

        async def _click(locator, **kwargs):
            order.append("click")
            await original_click(locator, **kwargs)

        humanizer.before_submit = _before_submit  # type: ignore[assignment]
        humanizer.click = _click  # type: ignore[assignment]

        with _silent_humanizer_sleep():
            with self.assertRaises(tk_main.PublishResultUnknownError):
                await video.click_publish(page)

        self.assertEqual(order, ["before_submit", "click"])
        self.assertEqual(page.mouse.down_count, 1)
        self.assertEqual(button.native_click_calls, 0)

    async def test_maybe_dispatched_publish_is_never_redispatched(self):
        page = FakePage()
        button = FakeNode("publish", page=page)
        base = FakeNode(
            "base",
            page=page,
            children={'[data-e2e="post_video_button"]': button},
        )
        video = _video()
        video.locator_base = base
        page.mouse.down_error = RuntimeError("pointer lost after down")
        page.wait_for_url_error = RuntimeError("navigation failed")

        with _silent_humanizer_sleep():
            with self.assertRaises(tk_main.PublishResultUnknownError):
                await video.click_publish(page)

        self.assertEqual(page.mouse.down_count, 1)
        self.assertEqual(button.native_click_calls, 0)


class OptionClickHoverTests(unittest.IsolatedAsyncioTestCase):
    """Real-device ``point-drift`` remedy for option controls (spec §2.5.1).

    A 2026-11-13 ``--no-publish`` run failed inside ``Humanizer.click`` with
    ``ElementUnusableError(reason="point-drift")`` while clicking the first
    option (privacy).  The remedy is to hover the call site's target first and
    then click it; ``Humanizer.click`` itself keeps zero retries and the ±1px
    tolerance.
    """

    def _label_control(self, page, *, box=_box(40.0, 40.0, 120.0, 24.0)):
        label = FakeNode("label-body", page=page, box=box)
        checkbox = FakeNode(
            "checkbox",
            page=page,
            count=1,
            children={"xpath=ancestor-or-self::label[1]": label},
        )
        video = _video()
        return video, label, checkbox

    def _recording_humanizer(self, video, page):
        """Humanizer whose pauses are appended to ``page.events``."""
        return _pause_recorder(video, page)

    async def test_option_click_hover_burst_precedes_click_move_and_down(self):
        page = FakePage()
        video, label, checkbox = self._label_control(page)
        humanizer, _pauses = self._recording_humanizer(video, page)
        control = tk_main._LocatorControl(checkbox, humanizer=humanizer)

        await control.click()

        names = [event[0] for event in page.events]
        down = names.index("down")
        # Exactly one press for the whole humanized option click.
        self.assertEqual(page.mouse.down_count, 1)
        self.assertEqual(names.count("down"), 1)
        self.assertEqual(label.native_click_calls, 0)
        self.assertEqual(checkbox.native_click_calls, 0)

        # Two move bursts: the hover burst, then the click's own burst.  Each
        # burst closes with a settle (>= ``pointer_settle``'s 0.2s minimum),
        # far longer than the 5-9ms step delays, so the settles are
        # distinguishable from the per-step pauses.
        moves = [index for index, name in enumerate(names) if name == "move"]
        settles = [
            index
            for index, event in enumerate(page.events)
            if event[0] == "pause" and event[1] >= 0.1
        ]
        hover_settle = next(
            index
            for index in settles
            if index < down and any(move < index for move in moves)
        )
        self.assertTrue([index for index in moves if index < hover_settle], names)
        # The click's own burst only starts after the hover settle.
        self.assertTrue(
            [index for index in moves if hover_settle < index < down], names
        )
        # ...and it closes with its own settle before the single press.
        click_settle = next(
            index for index in settles if hover_settle < index < down
        )
        self.assertGreater(
            click_settle, max(index for index in moves if index < down)
        )

    async def test_locator_control_hovers_then_clicks_the_label_body(self):
        page = FakePage()
        video, label, checkbox = self._label_control(page)
        humanizer = video._humanizer(page)
        control = tk_main._LocatorControl(checkbox, humanizer=humanizer)
        calls = self._spy_pointer_calls(humanizer)

        with _silent_humanizer_sleep():
            await control.click()

        self.assertEqual([name for name, _ in calls], ["hover", "click"])
        self.assertIs(calls[0][1], label)
        self.assertIs(calls[1][1], label)

    async def test_privacy_control_hovers_then_clicks_the_visible_trigger(self):
        page = FakePage()
        trigger = FakeNode(
            "privacy-trigger", page=page, box=_box(200.0, 60.0, 160.0, 24.0)
        )
        video = _video()
        humanizer = video._humanizer(page)
        control = tk_main._LocatorPrivacyControl(
            trigger, page, humanizer=humanizer
        )
        calls = self._spy_pointer_calls(humanizer)

        with _silent_humanizer_sleep():
            await control.click()

        self.assertEqual([name for name, _ in calls], ["hover", "click"])
        self.assertIs(calls[0][1], trigger)
        self.assertIs(calls[1][1], trigger)
        self.assertEqual(page.mouse.down_count, 1)
        self.assertEqual(trigger.native_click_calls, 0)

    async def test_humanize_zero_hovers_then_clicks_with_zero_pauses(self):
        page = FakePage()
        video, label, checkbox = self._label_control(page)
        pauses: list[float] = []

        async def _pause(seconds: float) -> None:
            pauses.append(seconds)

        video._humanize_pause = _pause  # type: ignore[assignment]
        with patch.dict(os.environ, {"HUMANIZE": "0"}):
            humanizer = video._humanizer(page)
            control = tk_main._LocatorControl(checkbox, humanizer=humanizer)
            await control.click()

        self.assertFalse(humanizer.enabled)
        # ``Humanizer.hover`` passes straight through in the fast path; it is
        # not skipped, so the order stays hover → click.
        self.assertEqual(label.actions, [("hover",), ("click", {})])
        self.assertEqual(label.native_click_calls, 1)
        self.assertEqual(page.mouse.down_count, 0)
        self.assertEqual(pauses, [])

    async def test_hover_failure_propagates_without_a_fallback_click(self):
        page = FakePage()
        video, label, checkbox = self._label_control(page, box={})
        humanizer = video._humanizer(page)
        control = tk_main._LocatorControl(checkbox, humanizer=humanizer)
        clicks: list[object] = []

        async def _click(locator, **kwargs):
            clicks.append(locator)

        # A zero-box target makes the real ``Humanizer.hover`` fail.  The tap
        # is replaced so a fallback click cannot pass silently.
        humanizer.click = _click  # type: ignore[assignment]

        with _silent_humanizer_sleep():
            with self.assertRaises(ElementUnusableError) as caught:
                await control.click()

        self.assertEqual(caught.exception.reason, "no-bounding-box")
        self.assertEqual(clicks, [])
        self.assertEqual(page.mouse.down_count, 0)
        self.assertEqual(label.native_click_calls, 0)
        self.assertEqual(checkbox.native_click_calls, 0)

    @staticmethod
    def _spy_pointer_calls(humanizer):
        return _pointer_call_spy(humanizer)


class PlatformWideClickHoverTests(unittest.IsolatedAsyncioTestCase):
    """Hover-before-click is the whole module's click policy (spec §2.5.1).

    Two 2026-11-13 ``--no-publish`` runs failed inside ``Humanizer.click``
    with ``ElementUnusableError(reason="point-drift")``: first on the privacy
    option, then on the AIGC dialog's ``Turn on`` button, which still used a
    bare ``humanizer.click``.  TikTok Studio animates/hover-expands option
    rows, dialogs, date pickers, the cover editor and tabs, so every click in
    this module goes through ``_humanized_click``.
    """

    def test_module_has_no_bare_humanizer_click_outside_the_helper(self):
        tree = ast.parse(TK_MAIN_CHROME.read_text(encoding="utf-8"))
        helper = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_humanized_click"
        )
        within_helper = set(range(helper.lineno, helper.end_lineno + 1))
        bare = [
            (node.lineno, ast.unparse(node))
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "click"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "humanizer"
            and node.lineno not in within_helper
        ]
        self.assertEqual(bare, [])

        wrapped = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_humanized_click"
        ]
        # Two pre-existing option adapters plus the 25 sites converted here.
        self.assertEqual(len(wrapped), 27, wrapped)

    # -- AIGC first-run dialog ------------------------------------------
    @staticmethod
    def _aigc_page():
        page = FakePage()
        dialog = FakeNode("aigc-dialog", page=page)
        button = FakeNode(
            "aigc-turn-on", page=page, box=_box(360.0, 300.0, 120.0, 32.0)
        )
        page.selectors['[role="dialog"]'] = dialog
        dialog._children[
            f"role:button:{re.compile(r'^Turn on$')}"
        ] = button
        return page, button

    async def test_aigc_turn_on_hover_burst_precedes_the_click(self):
        page, button = self._aigc_page()
        video = _video()
        _pause_recorder(video, page)

        await video._confirm_aigc_turn_on(page)

        _assert_hover_burst_precedes_the_press(self, page)
        self.assertEqual(button.native_click_calls, 0)
        self.assertEqual(button.wait_calls[0]["state"], "detached")

    async def test_aigc_turn_on_fast_path_is_one_hover_then_one_click(self):
        page, button = self._aigc_page()
        video = _video()
        pauses: list[float] = []

        async def _pause(seconds: float) -> None:
            pauses.append(seconds)

        video._humanize_pause = _pause  # type: ignore[assignment]
        with patch.dict(os.environ, {"HUMANIZE": "0"}):
            await video._confirm_aigc_turn_on(page)

        self.assertEqual(button.actions, [("hover",), ("click", {})])
        self.assertEqual(button.native_click_calls, 1)
        self.assertEqual(page.mouse.down_count, 0)
        self.assertEqual(pauses, [])

    # -- schedule picker -------------------------------------------------
    def _schedule_page(self, publish_date):
        page = FakePage()
        base = FakeNode("base", page=page)
        selectors = (
            'label:has(input[name="postSchedule"][value="schedule"])',
            'input[name="postSchedule"][value="schedule"]',
            'label:has-text("Schedule")',
        )
        for selector in selectors:
            node = FakeNode(f"radio::{selector}", page=page)
            base._children[selector] = node
            page.selectors[selector] = node

        page.roles["combobox:Select date"] = FakeNode(
            "date-combobox", page=page
        )
        page.selectors['[role="dialog"]'] = FakeNode(
            "dialogs", page=page, children={
                f"role:button:{re.compile(r'^Allow$')}": FakeNode(
                    "allow-dialog", page=page, count=0
                )
            }
        )
        page.roles[f"button:{re.compile(r'^Allow$')}"] = FakeNode(
            "allow-page", page=page, count=0
        )

        month = publish_date.strftime("%B")
        year = str(publish_date.year)
        page.selectors[".DatePicker__titleMonth"] = FakeNode(
            "title-month", page=page, text=month
        )
        page.selectors[".DatePicker__titleYear"] = FakeNode(
            "title-year", page=page, text=year
        )
        day_pattern = re.compile(
            rf"{month} {publish_date.day}(st|nd|rd|th), {year}"
        )
        day = FakeNode("day", page=page)
        page.roles[f"button:{day_pattern}"] = day

        hour_str = publish_date.strftime("%H")
        minute_str = f"{(publish_date.minute // 5) * 5:02d}"
        page.roles["combobox:Select time"] = FakeNode(
            "time-combobox", page=page
        )
        hour = FakeNode("hour", page=page)
        page.roles[f"option:Hours {hour_str}"] = hour
        minute = FakeNode("minute", page=page)
        page.roles[f"option:Minutes {minute_str}"] = minute
        page.selectors[
            ".Picker__root.schedule-picker .Picker__value"
        ] = FakeNode(
            "picker-values",
            page=page,
            items=[
                FakeNode(
                    "date-value",
                    page=page,
                    text=f"{publish_date.strftime('%b')} "
                    f"{publish_date.day}, {year}",
                ),
                FakeNode(
                    "time-value", page=page, text=f"{hour_str}:{minute_str}"
                ),
            ],
        )
        targets = {
            "date": page.roles["combobox:Select date"],
            "day": day,
            "hour": hour,
            "minute": minute,
        }
        return page, base, targets

    async def test_schedule_day_and_time_options_hover_then_click(self):
        publish_date = datetime(2026, 11, 13, 14, 30)
        page, base, targets = self._schedule_page(publish_date)
        video = TiktokVideo(
            "caption", "/tmp/demo.mp4", [], publish_date, None
        )
        video.locator_base = base
        humanizer, _pauses = _pause_recorder(video, page)
        calls = _pointer_call_spy(humanizer)

        with patch.object(
            tk_main,
            "prepare_schedule",
            AsyncMock(return_value=publish_date),
        ):
            await video.apply_schedule(page)

        # Every schedule target is hovered and then clicked, with no other
        # humanizer call in between (the exact burst is covered by the AIGC
        # event-order test).
        for name, target in targets.items():
            with self.subTest(target=name):
                pairs = [
                    (index, call[0])
                    for index, call in enumerate(calls)
                    if call[1] is target
                ]
                self.assertEqual(
                    [verb for _index, verb in pairs], ["hover", "click"]
                )
                self.assertEqual(
                    pairs[1][0], pairs[0][0] + 1, (name, calls)
                )

    # -- cover editor ----------------------------------------------------
    def _cover_page(self):
        page = FakePage()
        base = FakeNode("base", page=page)
        base._children["text:Edit cover:exact"] = FakeNode(
            "edit-cover-text", page=page, count=0
        )
        edit_cover = FakeNode("edit-cover", page=page)
        base._children["role:button:Edit cover"] = edit_cover
        upload_tab = FakeNode("upload-tab", page=page)
        base._children["text:Upload cover:exact"] = upload_tab
        editor = FakeNode("cover-editor", page=page)
        upload_tab._children[tk_main.COVER_EDITOR_SCOPE_SELECTOR] = editor
        file_input = FakeNode("cover-file", page=page)
        editor._children[tk_main._COVER_FILE_ARIA_SELECTOR] = file_input
        editor._children['[aria-label="Uploaded cover image"]'] = FakeNode(
            "cover-preview", page=page
        )
        save = FakeNode("cover-save", page=page)
        editor._children[
            f"role:button:{re.compile(r'^(Save|Confirm)$')}"
        ] = save
        return page, base, edit_cover, upload_tab, save, file_input

    async def test_cover_edit_upload_and_save_hover_then_click(self):
        page, base, edit_cover, upload_tab, save, file_input = (
            self._cover_page()
        )
        video = TiktokVideo(
            "caption",
            "/tmp/demo.mp4",
            [],
            0,
            None,
            "/tmp/cover.jpg",
        )
        video.locator_base = base
        humanizer, _pauses = _pause_recorder(video, page)
        calls = _pointer_call_spy(humanizer)

        await video.apply_cover(page)

        self.assertEqual(
            [target.name for verb, target in calls if verb == "click"],
            ["edit-cover", "cover-save"],
        )
        # The existing hidden input is written directly: the upload tab is never
        # clicked, so no OS file chooser can be opened.
        self.assertEqual(page.expect_file_chooser_calls, 0)
        for index, (verb, _target) in enumerate(calls):
            self.assertEqual(verb, "hover" if index % 2 == 0 else "click")
            if verb == "click":
                self.assertIs(calls[index - 1][1], calls[index][1])
        self.assertIn(
            ("set_input_files", "/tmp/cover.jpg"), file_input.actions
        )


class FieldValueReadbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_caption_is_cleared_cleanly_before_typing(self):
        page, base = _hashtag_page()
        page.editor.buffer = "OLD CAPTION THAT MUST GO"
        video = _video()
        video.locator_base = base

        with _silent_humanizer_sleep():
            await video.fill_caption(page, "New caption", [])

        self.assertEqual(page.editor.buffer, "New caption\n")
        self.assertNotIn("OLD", page.editor.buffer)

    async def test_hashtag_keeps_typed_text_and_picks_exact_first_line(self):
        page, base = _hashtag_page(
            option_texts=["#tiktokshop\n175.4M posts", "#tiktok\n2.0B posts"]
        )
        video = _video()
        video.locator_base = base

        with _silent_humanizer_sleep():
            self.assertTrue(await video._apply_hashtag(page, "tiktok"))

        self.assertEqual(page.editor.buffer, "#tiktok")
        picked = [
            node for node in page.pressed if node.name.startswith("option::")
        ]
        self.assertEqual([node.name for node in picked], ["option::#tiktok"])
        self.assertEqual(page.keyboard.actions[0][0], "press")

    async def test_thousand_and_one_codepoints_is_one_bulk_insert(self):
        page, base = _hashtag_page()
        video = _video()
        video.locator_base = base
        text = "长" * 1001

        with _silent_humanizer_sleep():
            await video.fill_caption(page, text, [])

        inserts = [
            action[1]
            for action in page.keyboard.actions
            if action[0] == "insert_text"
        ]
        self.assertEqual(inserts, [text])
        self.assertNotIn("长", [action[1] for action in page.keyboard.actions if action[0] == "press"])
        self.assertEqual(page.editor.buffer, text + "\n")

    async def test_humanize_zero_uses_fast_path_for_caption_and_hashtag(self):
        page, base = _hashtag_page(option_texts=["#tiktok\n2.0B posts"])
        video = _video()
        video.locator_base = base
        option = page.nodes[2]

        with patch.dict(os.environ, {"HUMANIZE": "0"}):
            humanizer = video._humanizer(page)
            await video.fill_caption(page, "New caption", ["tiktok"])

        # One bulk insert for the caption, one for the hashtag.
        inserts = [
            action[1]
            for action in page.keyboard.actions
            if action[0] == "insert_text"
        ]
        self.assertEqual(inserts, ["New caption", "#tiktok"])
        # The suggestion is taken through the library's own click (fast path).
        self.assertEqual(option.native_click_calls, 1)
        self.assertEqual(page.mouse.down_count, 0)
        self.assertFalse(humanizer.enabled)


class StaticGateTests(unittest.TestCase):
    def test_shipped_module_passes_gates_a_to_e(self):
        from tests.humanize_gates import assert_clean

        assert_clean(TK_MAIN_CHROME)

    def test_package_violations_are_confined_to_the_unwired_legacy_file(self):
        from tests.humanize_gates import gate_violations

        violations = gate_violations(TK_PACKAGE)
        for violation in violations:
            self.assertTrue(
                violation.startswith("uploader/tk_uploader/main.py:"),
                violation,
            )


if __name__ == "__main__":
    unittest.main()
