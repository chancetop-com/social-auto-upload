# -*- coding: utf-8 -*-
"""YouTube humanize rollout (ticket 07, spec §3.14).

Three blocks, all offline (no browser, no network):

1. **Event sequence** — title/description are typed per character (ASCII ``press``,
   non-ASCII ``insert_text``), a ``#tag`` waits once for the autocomplete and the
   exact candidate is clicked through ``mouse.down/up`` with a ``stillOn`` hit-test
   first; ``_click_if_present`` keeps its "may be absent → ``False``" contract.
2. **Field-value readback** — the fake keyboard owns the focused field's buffer, so
   a clean sequence with a wrong value (clear not clean, appended text, ``#``
   dropped) still fails.
3. **Static gates** — ``tests.humanize_gates.assert_clean`` over the package
   (gates A–E), plus the "no retreat to ``type(delay=)``" residue checks.

``HUMANIZE=0`` is covered once: the shared layer falls back to a single native
``locator.click`` / ``insert_text`` with zero pauses, and the uploader must not
bypass or second-guess that.
"""

from __future__ import annotations

import ast
import asyncio
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from tests.fakes_xhs_dom import (
    FakeLocator,
    RecordingKeyboard,
    RecordingLocator,
    RecordingMouse,
    RecordingPage,
)
from tests.humanize_gates import assert_clean
from uploader.youtube_uploader import main as youtube_main
from uploader.youtube_uploader.main import YouTubeVideo
from utils.dom import ElementUnusableError
from utils.errors import PublishResultUnknownError
from utils.humanize import MAYBE_DISPATCHED, MAYBE_DISPATCHED_VALUE, Humanizer

PACKAGE = Path(__file__).resolve().parent.parent / "uploader" / "youtube_uploader"
TITLE_INPUT = "#title-textarea #textbox"
DESC_INPUT = "#description-textarea #textbox"
AUTOCOMPLETE = youtube_main.HASHTAG_AUTOCOMPLETE
DISMISS_LOCATOR = youtube_main.AUTOCOMPLETE_VISIBLE

#: ``utils/dom.py`` ``_FACTS_JS`` shape; every click target must answer this.
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


class Timeline:
    """Shared ordering log for keyboard/mouse/hit-test/pause events."""

    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def add(self, name: str, value: object = None) -> None:
        self.events.append((name, value))

    async def sleep(self, seconds: float) -> None:
        self.add("sleep", seconds)

    def kinds(self) -> list[str]:
        return [name for name, _value in self.events]

    def count(self, name: str) -> int:
        return self.kinds().count(name)


class BufferKeyboard(RecordingKeyboard):
    """Keyboard double that owns the focused field's value.

    A select-all + ``Delete`` closes the current field; every later keystroke
    belongs to the next field.  ``values`` therefore reads back exactly what each
    field ended up containing — the "sequence right, value wrong" detector.
    """

    def __init__(self, timeline: Timeline | None = None, initial: str = "") -> None:
        super().__init__()
        self._timeline = timeline
        self.current = initial
        self.values: list[str] = []
        self._selected = False
        self._typed = False

    def _record(self, action: tuple) -> None:
        self.actions.append(action)
        if self._timeline is not None:
            self._timeline.add("keyboard", action)

    async def press(self, key: str, **kwargs) -> None:
        self._record(("press", key))
        if key in ("ControlOrMeta+A", "Control+A"):
            self._selected = True
        elif key == "Delete":
            if self._typed:
                self.values.append(self.current)
            self.current = ""
            self._typed = False
            self._selected = False
        elif key == "Enter":
            self.current += "\n"
            self._typed = True
        elif key in ("Escape", "Tab", "Backspace", "End"):
            pass
        elif len(key) == 1:
            self.current += key
            self._typed = True

    async def insert_text(self, text: str, **kwargs) -> None:
        self._record(("insert_text", text))
        self.current += text
        self._typed = True

    async def type(self, text: str, delay: float | None = None, **kwargs) -> None:
        self._record(("type", text, delay))
        self.current += text
        self._typed = True

    def finish(self) -> list[str]:
        if self._typed:
            self.values.append(self.current)
        return self.values


class TimelineMouse(RecordingMouse):
    """``RecordingMouse`` that also writes down/up into the shared timeline."""

    def __init__(self, timeline: Timeline) -> None:
        super().__init__()
        self._timeline = timeline

    async def move(self, x: float, y: float, **kwargs) -> None:
        await super().move(x, y, **kwargs)
        self._timeline.add("move", (x, y))

    async def down(self, **kwargs) -> None:
        await super().down(**kwargs)
        self._timeline.add("down")

    async def up(self, **kwargs) -> None:
        await super().up(**kwargs)
        self._timeline.add("up")


class ClickableLocator(RecordingLocator):
    """Locator double that satisfies ``Humanizer.click`` (box + geometry + facts)."""

    def __init__(
        self,
        name: str,
        *,
        timeline: Timeline | None = None,
        box: dict[str, float] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(name, **kwargs)
        self.timeline = timeline
        self._box = box or {"x": 10.0, "y": 20.0, "width": 120.0, "height": 30.0}

    async def bounding_box(self):
        return dict(self._box)

    async def evaluate(self, expression, arg=None):
        self.evaluate_calls.append((expression, arg))
        if isinstance(expression, str) and "elementFromPoint" in expression:
            if self.timeline is not None:
                self.timeline.add("hit-test")
            return {"self": True, "tag": "div", "className": "", "id": "", "text": ""}
        if isinstance(expression, str) and "getBoundingClientRect" in expression:
            return {
                "width": self._box["width"],
                "height": self._box["height"],
                "inside": True,
                "clipped": False,
                "childFrame": False,
            }
        return dict(FACTS)


class NamedHumanizer(Humanizer):
    """Humanizer that names each pause from the profile instead of sleeping it."""

    _PROFILE_PAUSES = (
        "after_type",
        "after_navigate",
        "before_submit",
        "pointer_settle",
        "click_hold",
        "before_click",
        "after_click",
        "between_scroll",
        "reading",
        "after_interact",
        "keystroke",
    )

    def __init__(self, page, timeline: Timeline) -> None:
        super().__init__(page, sleep=timeline.sleep)
        self.timeline = timeline

    async def _pause(self, action) -> None:
        for name in self._PROFILE_PAUSES:
            if action == getattr(self.profile, name):
                self.timeline.add(name)
                break
        else:  # pragma: no cover - every pause comes from the profile
            self.timeline.add("pause")
        await super()._pause(action)


def _hashtag_page(
    timeline: Timeline,
    keyboard: BufferKeyboard,
    *,
    text_locator: ClickableLocator,
    candidates: dict[str, FakeLocator],
    dropdown_open: bool = True,
) -> RecordingPage:
    autocomplete = FakeLocator("autocomplete", children=candidates)
    page = RecordingPage(
        selectors={
            TITLE_INPUT: text_locator,
            DESC_INPUT: text_locator,
            AUTOCOMPLETE: autocomplete,
            DISMISS_LOCATOR: FakeLocator(
                "dropdown", count=1 if dropdown_open else 0
            ),
        },
        evaluate_handler=lambda expression, arg: None,
    )
    page.keyboard = keyboard
    page.mouse = TimelineMouse(timeline)
    return page


def _plain_page(timeline: Timeline, keyboard: BufferKeyboard, text_locator) -> RecordingPage:
    page = RecordingPage(
        selectors={
            TITLE_INPUT: text_locator,
            DESC_INPUT: text_locator,
            DISMISS_LOCATOR: FakeLocator("dropdown", count=0),
        },
        evaluate_handler=lambda expression, arg: None,
    )
    page.keyboard = keyboard
    page.mouse = TimelineMouse(timeline)
    return page


# ---------------------------------------------------------------------------
# 1. Event sequence
# ---------------------------------------------------------------------------


class YouTubeEventSequenceTests(unittest.TestCase):
    def test_title_is_typed_per_character_and_the_exact_hashtag_is_clicked(self):
        timeline = Timeline()
        keyboard = BufferKeyboard(timeline)
        title_box = ClickableLocator("title", timeline=timeline)
        candidate = ClickableLocator("candidate", timeline=timeline)
        page = _hashtag_page(
            timeline,
            keyboard,
            text_locator=title_box,
            candidates={"text:#Shorts:exact": candidate},
        )
        humanizer = NamedHumanizer(page, timeline)

        asyncio.run(
            youtube_main._fill_editable(page, TITLE_INPUT, "标题 #Shorts", humanizer)
        )

        # Clearing is the `sel` form: click → ControlOrMeta+A → Delete.
        self.assertEqual(
            keyboard.actions[:2],
            [("press", "ControlOrMeta+A"), ("press", "Delete")],
        )
        # Non-ASCII per character, ASCII (including `#`) through real key presses.
        self.assertIn(("insert_text", "标"), keyboard.actions)
        self.assertIn(("insert_text", "题"), keyboard.actions)
        self.assertIn(("press", "#"), keyboard.actions)
        self.assertIn(("press", "S"), keyboard.actions)
        # No `type()` retreat and no fill.
        self.assertEqual([a for a in keyboard.actions if a[0] == "type"], [])
        self.assertEqual([a for a in title_box.actions if a[0] == "fill"], [])

        # Two text blocks ("标题 " + "#Shorts") => two after_type pauses.
        self.assertEqual(timeline.count("after_type"), 2)

        # Candidate picked by exact text through the real pointer, never el.click.
        self.assertEqual(candidate.click_count, 0)
        self.assertEqual(page.mouse.down_count, 2)  # focus + candidate
        self.assertEqual(page.mouse.up_count, 2)
        # stillOn ran before each press.
        kinds = timeline.kinds()
        first_down = kinds.index("down")
        self.assertLess(kinds.index("hit-test"), first_down)
        self.assertEqual(kinds.count("hit-test"), 2)

    def test_hashtag_miss_keeps_plain_text_and_dismisses_the_dropdown(self):
        timeline = Timeline()
        keyboard = BufferKeyboard(timeline)
        title_box = ClickableLocator("title", timeline=timeline)
        page = _hashtag_page(
            timeline,
            keyboard,
            text_locator=title_box,
            candidates={"text:#Missing:exact": FakeLocator("no-match", count=0)},
        )
        humanizer = NamedHumanizer(page, timeline)

        asyncio.run(
            youtube_main._fill_editable(page, TITLE_INPUT, "#Missing 标题", humanizer)
        )

        # Plain text is kept verbatim and Escape closed the autocomplete.
        self.assertEqual(keyboard.finish(), ["#Missing 标题"])
        self.assertIn(("press", "Escape"), keyboard.actions)
        # Only the focus click: no candidate dispatch happened.
        self.assertEqual(page.mouse.down_count, 1)

    def test_description_interleaves_hashtags_and_survives_a_miss(self):
        timeline = Timeline()
        keyboard = BufferKeyboard(timeline)
        desc_box = ClickableLocator("description", timeline=timeline)
        hit = ClickableLocator("candidate", timeline=timeline)
        page = _hashtag_page(
            timeline,
            keyboard,
            text_locator=desc_box,
            candidates={
                "text:#hit:exact": hit,
                "text:#miss:exact": FakeLocator("no-match", count=0),
            },
        )
        humanizer = NamedHumanizer(page, timeline)

        text = "第一行\n#hit 中间 #miss\n末行"
        asyncio.run(
            youtube_main._fill_editable(
                page, DESC_INPUT, text, humanizer, multiline=True
            )
        )

        self.assertEqual(keyboard.finish(), [text])
        self.assertIn(("press", "Enter"), keyboard.actions)
        # One candidate click for #hit; #miss stays plain text.
        self.assertEqual(page.mouse.down_count, 2)
        self.assertEqual(timeline.count("after_type"), 5)

    def test_over_the_horizon_goes_through_exactly_one_bulk_insert(self):
        timeline = Timeline()
        keyboard = BufferKeyboard(timeline)
        desc_box = ClickableLocator("description", timeline=timeline)
        page = _plain_page(timeline, keyboard, desc_box)
        humanizer = NamedHumanizer(page, timeline)
        text = "长" * 1001

        asyncio.run(
            youtube_main._fill_editable(
                page, DESC_INPUT, text, humanizer, multiline=True
            )
        )

        inserts = [action for action in keyboard.actions if action[0] == "insert_text"]
        self.assertEqual(inserts, [("insert_text", text)])
        self.assertEqual(timeline.count("after_type"), 1)

    def test_over_the_horizon_with_hashtags_is_not_segmented(self):
        # spec §2.4 rule 4: past the horizon the whole text goes through one
        # bulk ``insert_text`` — the platform must not split at ``#`` first
        # (that would be a second threshold / a segmented long text).
        timeline = Timeline()
        keyboard = BufferKeyboard(timeline)
        desc_box = ClickableLocator("description", timeline=timeline)
        candidate = ClickableLocator("candidate", timeline=timeline)
        page = _hashtag_page(
            timeline,
            keyboard,
            text_locator=desc_box,
            candidates={"text:#Shorts:exact": candidate},
        )
        humanizer = NamedHumanizer(page, timeline)
        text = "#Shorts " + "长" * 1000
        self.assertGreater(len(text), 1000)

        asyncio.run(
            youtube_main._fill_editable(
                page, DESC_INPUT, text, humanizer, multiline=True
            )
        )

        inserts = [action for action in keyboard.actions if action[0] == "insert_text"]
        self.assertEqual(inserts, [("insert_text", text)])
        self.assertEqual(keyboard.finish(), [text])
        # No candidate flow: only the focus click reached the pointer.
        self.assertEqual(candidate.click_count, 0)
        self.assertEqual(page.mouse.down_count, 1)
        self.assertEqual(timeline.count("after_type"), 1)

    def test_at_the_horizon_with_hashtags_still_picks_the_candidate(self):
        timeline = Timeline()
        keyboard = BufferKeyboard(timeline)
        desc_box = ClickableLocator("description", timeline=timeline)
        candidate = ClickableLocator("candidate", timeline=timeline)
        page = _hashtag_page(
            timeline,
            keyboard,
            text_locator=desc_box,
            candidates={"text:#Shorts:exact": candidate},
        )
        humanizer = NamedHumanizer(page, timeline)
        text = "#Shorts " + "长" * 992  # exactly 1000 code points
        self.assertEqual(len(text), 1000)

        asyncio.run(
            youtube_main._fill_editable(
                page, DESC_INPUT, text, humanizer, multiline=True
            )
        )

        self.assertEqual(keyboard.finish(), [text])
        # Focus + candidate: the ≤1000 candidate flow is untouched.
        self.assertEqual(page.mouse.down_count, 2)
        self.assertEqual(candidate.click_count, 0)
        self.assertEqual(timeline.count("after_type"), 2)

    def test_click_if_present_clicks_through_the_humanizer_when_present(self):
        timeline = Timeline()
        target = ClickableLocator("save", timeline=timeline)
        page = RecordingPage(
            selectors={"ytcp-button:has-text('Done')": target},
            evaluate_handler=lambda expression, arg: None,
        )
        humanizer = NamedHumanizer(page, timeline)

        clicked = asyncio.run(
            youtube_main._click_if_present(
                page,
                "ytcp-button:has-text('Done')",
                3000,
                humanizer=humanizer,
            )
        )

        self.assertTrue(clicked)
        self.assertEqual(target.click_count, 0)
        self.assertEqual(page.mouse.down_count, 1)
        self.assertEqual(timeline.count("hit-test"), 1)

    def test_click_if_present_returns_false_when_the_target_is_absent(self):
        timeline = Timeline()
        absent = FakeLocator("absent", count=0, wait_error=TimeoutError("no node"))
        page = RecordingPage(
            selectors={"#next-button": absent},
            evaluate_handler=lambda expression, arg: None,
        )
        humanizer = NamedHumanizer(page, timeline)

        clicked = asyncio.run(
            youtube_main._click_if_present(
                page, "#next-button", 500, humanizer=humanizer
            )
        )

        self.assertFalse(clicked)
        self.assertEqual(page.mouse.actions, [])

    def test_click_if_present_does_not_swallow_a_maybe_dispatched_click(self):
        timeline = Timeline()
        error = RuntimeError("mouse up failed")
        setattr(error, "click_dispatched", "maybe")
        target = ClickableLocator("save", timeline=timeline, click_error=error)
        page = RecordingPage(
            selectors={"#done-button": target},
            evaluate_handler=lambda expression, arg: None,
        )

        with patch.dict(os.environ, {"HUMANIZE": "0"}):
            humanizer = NamedHumanizer(page, timeline)
            with self.assertRaises(RuntimeError):
                asyncio.run(
                    youtube_main._click_if_present(
                        page, "#done-button", 3000, humanizer=humanizer
                    )
                )

        # The fast path dispatches through the locator exactly once, never twice.
        self.assertEqual(target.click_count, 1)


# ---------------------------------------------------------------------------
# 2. Field-value readback
# ---------------------------------------------------------------------------


class YouTubeFieldValueTests(unittest.TestCase):
    def test_title_clear_replaces_the_previous_value(self):
        timeline = Timeline()
        keyboard = BufferKeyboard(timeline, initial="旧标题")
        title_box = ClickableLocator("title", timeline=timeline)
        page = _hashtag_page(
            timeline,
            keyboard,
            text_locator=title_box,
            candidates={"text:#Shorts:exact": ClickableLocator("candidate", timeline=timeline)},
        )
        humanizer = NamedHumanizer(page, timeline)

        asyncio.run(
            youtube_main._fill_editable(page, TITLE_INPUT, "#Shorts 标题", humanizer)
        )

        self.assertEqual(keyboard.finish(), ["#Shorts 标题"])

    def test_description_value_including_hashtags_matches_the_input(self):
        timeline = Timeline()
        keyboard = BufferKeyboard(timeline, initial="旧简介")
        desc_box = ClickableLocator("description", timeline=timeline)
        page = _hashtag_page(
            timeline,
            keyboard,
            text_locator=desc_box,
            candidates={
                "text:#a:exact": ClickableLocator("a", timeline=timeline),
                "text:#b:exact": ClickableLocator("b", timeline=timeline),
            },
        )
        humanizer = NamedHumanizer(page, timeline)
        text = "正文 #a 与 #b 收尾"

        asyncio.run(
            youtube_main._fill_editable(
                page, DESC_INPUT, text, humanizer, multiline=True
            )
        )

        self.assertEqual(keyboard.finish(), [text])

    def test_playlist_name_is_cleared_and_typed_verbatim(self):
        timeline = Timeline()
        keyboard = BufferKeyboard(timeline, initial="旧合集")
        title_box = ClickableLocator("playlist-name", timeline=timeline)
        page = RecordingPage(
            selectors={
                "ytcp-playlist-metadata-editor #textbox, "
                "#create-playlist-form #textbox": title_box
            },
            evaluate_handler=lambda expression, arg: None,
        )
        page.keyboard = keyboard
        humanizer = NamedHumanizer(page, timeline)
        app = YouTubeVideo("标题", "demo.mp4", [], "account.json", playlist="新合集")

        asyncio.run(app._fill_playlist_name(page, humanizer))

        self.assertEqual(keyboard.finish(), ["新合集"])
        self.assertEqual(title_box.click_count, 0)

    def test_tags_keep_every_value_and_the_trailing_comma(self):
        timeline = Timeline()
        keyboard = BufferKeyboard(timeline, initial="旧标签")
        tag_input = ClickableLocator("tag-input", timeline=timeline)
        page = RecordingPage(
            selectors={
                "#tags-container #text-input, "
                "ytcp-form-input-container#tags-container input": tag_input
            },
            evaluate_handler=lambda expression, arg: None,
        )
        page.keyboard = keyboard
        humanizer = NamedHumanizer(page, timeline)
        app = YouTubeVideo("标题", "demo.mp4", ["a", "b"], "account.json")

        asyncio.run(app._fill_tags(page, humanizer))

        self.assertEqual(keyboard.finish(), ["a,b,"])
        self.assertEqual(tag_input.click_count, 0)


# ---------------------------------------------------------------------------
# 3. Static gates + HUMANIZE=0
# ---------------------------------------------------------------------------


class YouTubeStaticGateTests(unittest.TestCase):
    def test_youtube_package_passes_humanize_gates_a_to_e(self):
        assert_clean(PACKAGE)

    def test_no_fill_el_click_or_delay_retreats_remain(self):
        offenders: list[str] = []
        for path in sorted(PACKAGE.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            if "el.click()" in source or "force=True" in source:
                offenders.append(f"{path.name}: JS click / force")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute):
                    continue
                if func.attr == "fill":
                    offenders.append(f"{path.name}:{node.lineno}: fill()")
                if func.attr == "type":
                    delays = [
                        keyword.value.value
                        for keyword in node.keywords
                        if keyword.arg == "delay"
                        and isinstance(keyword.value, ast.Constant)
                    ]
                    if delays:
                        offenders.append(
                            f"{path.name}:{node.lineno}: type(delay={delays[0]})"
                        )
        self.assertEqual(offenders, [])

    def test_every_click_if_present_call_forwards_the_humanizer(self):
        source = (PACKAGE / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("_click_if_present(page, selector", source)
        self.assertIn("humanizer=humanizer", source)


class YouTubePublishDispatchGuardTests(unittest.TestCase):
    """``#done-button`` 按下之后失败 = 结果未知（退出 9），绝不二次派发。"""

    def _video(self):
        app = YouTubeVideo("标题", "demo.mp4", [], "account.json")
        app.start_publish_budget()
        return app

    def _page(self):
        page = MagicMock()
        locator = MagicMock()
        locator.first = locator
        locator.wait_for = AsyncMock(return_value=True)
        locator.set_input_files = AsyncMock(return_value=None)
        locator.is_visible = AsyncMock(return_value=True)
        locator.count = AsyncMock(return_value=1)
        page.locator.return_value = locator
        page.wait_for_timeout = AsyncMock(return_value=None)
        return page

    def _run(self, error: BaseException) -> list:
        page = self._page()
        app = self._video()
        app._humanizer_instance = SimpleNamespace(page=page, before_submit=AsyncMock())
        dispatches: list[str] = []

        async def _click_if_present(page, selector, timeout=4000, *, humanizer):
            if selector == "#done-button":
                dispatches.append(selector)
                raise error
            return True

        with (
            patch.object(youtube_main, "_click_if_present", _click_if_present),
            patch.object(youtube_main, "_fill_editable", AsyncMock()),
            patch.object(
                youtube_main, "_wait_upload_complete", AsyncMock(return_value=True)
            ),
        ):
            asyncio.run(app._upload_video_on_page(page, multilogin=False))
        return dispatches

    def test_maybe_dispatched_done_click_maps_to_result_unknown(self):
        error = RuntimeError("mouse up failed")
        setattr(error, MAYBE_DISPATCHED, MAYBE_DISPATCHED_VALUE)

        with self.assertRaises(PublishResultUnknownError):
            self._run(error)

    def test_pre_dispatch_done_failure_propagates(self):
        error = ElementUnusableError(
            what="点击目标",
            role="interactive",
            selector="",
            reason="covered-by:mask",
            publish_clicked=False,
        )

        with self.assertRaises(ElementUnusableError) as caught:
            self._run(error)

        self.assertIs(caught.exception, error)


class YouTubeHumanizeDisabledTests(unittest.TestCase):
    def test_humanize_zero_falls_back_to_one_native_click_and_insert(self):
        timeline = Timeline()
        keyboard = BufferKeyboard(timeline)
        title_box = ClickableLocator("title", timeline=timeline)
        page = _plain_page(timeline, keyboard, title_box)

        with patch.dict(os.environ, {"HUMANIZE": "0"}):
            app = YouTubeVideo("标题", "demo.mp4", [], "account.json")
            app._humanize_pause = timeline.sleep
            humanizer = app._humanizer(page)
            self.assertFalse(humanizer.enabled)
            asyncio.run(
                youtube_main._fill_editable(page, TITLE_INPUT, "标题", humanizer)
            )

        # Native locator.click (focus) instead of the human pointer path.
        self.assertEqual(title_box.click_count, 1)
        self.assertEqual(page.mouse.actions, [])
        self.assertEqual([a for a in keyboard.actions if a[0] == "type"], [])
        self.assertEqual(
            [a for a in keyboard.actions if a[0] == "insert_text"],
            [("insert_text", "标题")],
        )
        self.assertEqual(timeline.count("sleep"), 0)

    def test_the_humanizer_is_cached_per_page_and_rebuilt_for_a_new_page(self):
        first = RecordingPage()
        second = RecordingPage()
        app = YouTubeVideo("标题", "demo.mp4", [], "account.json")

        one = app._humanizer(first)
        self.assertIs(one, app._humanizer(first))
        self.assertIsNot(one, app._humanizer(second))


if __name__ == "__main__":
    unittest.main()
