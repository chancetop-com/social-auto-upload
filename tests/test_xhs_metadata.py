# -*- coding: utf-8 -*-
"""Metadata limits and schedule read-back (spec §3 U8, ticket 40).

Covers four groups, all offline and virtual-time where a wait is involved:

* title metric — UTF-16 weighted, ``ceil(weighted / 2)``, limit 20; explicit
  over-limit input fails validation (no truncation), auto-derived notes are
  truncated with a warning, and the post-typing suffix node is an exit-1 gate;
* body metric — 1 per character, topic anchors count as ``#name`` + separator;
  ``div.edit-container div.length-error`` is checked exactly once after body
  and topics are fully typed;
* schedule read-back — C1 (switch checked + date input attached), C2 (blur →
  one read → minute equality), C3 (same, plus still in the future, after ARM
  and before FIRE, also for ``--no-publish``); immediate publish never enters
  any of them;
* other controls — original declaration ``true`` is fatal on failure, ``false``
  is warning-only, ``None`` is a no-op.

The fixtures are ticket 28's scripted doubles: an unscripted selector is an
error, so a missing call cannot be "proven" by a silent zero.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import uploader.publish_timeout as publish_timeout
import uploader.xiaohongshu_uploader.main as xhs_main
from tests.fakes_clock import FakeClock
from tests.fakes_xhs_dom import (
    FakeLocator,
    RecordingLocator,
    RecordingMouse,
    RecordingPage,
    preview_tiles,
)
from utils import dom
from utils.dom import ElementMissingError, ElementUnusableError

NOTE_URL = (
    "https://creator.xiaohongshu.com/publish/publish?from=homepage&target=image"
)
LOGIN_URL = "https://creator.xiaohongshu.com/login?redirect=%2Fpublish"

TITLE_PRIMARY = "div.d-input input"
PUBLISH_SELECTOR = "xhs-publish-btn"
LOGIN_BOX = xhs_main.XHS_LOGIN_BOX_SELECTOR
NOTE_TILES_SELECTOR = ".img-preview-area .pr"
NOTE_IMAGE_INPUT_SELECTOR = "div.upload-content input.upload-input"

SCHEDULE_SWITCH = ".post-time-wrapper .d-switch"
SCHEDULE_INPUT = ".d-datepicker-input-filter input.d-text"
SCHEDULE_DATE_INPUT = ".date-picker-container input"

INPUT_FACTS = {
    "tag": "input",
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
SWITCH_FACTS = dict(INPUT_FACTS, tag="div")
VISIBLE_FACTS = dict(INPUT_FACTS, tag="div")


def _requested(hours: int = 3) -> datetime:
    return (datetime.now() + timedelta(hours=hours)).replace(microsecond=0)


def _text(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")


async def _noop_async_sleep(_seconds: float) -> None:
    return None


def _note_app(**overrides):
    values = {
        "image_paths": ["a.png"],
        "note": "",
        "tags": [],
        "publish_date": 0,
        "account_file": "account.json",
        "title": "标题",
        "no_publish": True,
    }
    values.update(overrides)
    return xhs_main.XiaoHongShuNote(**values)


def _video_app(**overrides):
    values = {
        "title": "标题",
        "file_path": "demo.mp4",
        "tags": [],
        "publish_date": 0,
        "account_file": "account.json",
        "no_publish": True,
    }
    values.update(overrides)
    return xhs_main.XiaoHongShuVideo(**values)


# ---------------------------------------------------------------------------
# Local doubles (shared fixtures stay untouched; ticket 28 owns them)
# ---------------------------------------------------------------------------


class _Interactive(FakeLocator):
    """Element that passes the ``interactive`` role (box + hit-test)."""

    def __init__(
        self,
        name: str,
        *,
        attributes: dict | None = None,
        facts: dict | None = None,
        click_error: BaseException | None = None,
    ) -> None:
        super().__init__(
            name,
            attributes=attributes or {},
            computed_style=dict(facts or SWITCH_FACTS),
            click_error=click_error,
        )
        self.box = {"x": 10.0, "y": 20.0, "width": 80.0, "height": 20.0}

    async def bounding_box(self):
        return dict(self.box)

    async def evaluate(self, expression, arg=None):
        self.evaluate_calls.append((expression, arg))
        if isinstance(expression, str) and "elementFromPoint" in expression:
            return {
                "self": True,
                "tag": "div",
                "className": "",
                "id": "",
                "text": "",
            }
        return dict(self._computed_style or SWITCH_FACTS)


class _ScheduleSwitch(_Interactive):
    """``.post-time-wrapper .d-switch`` with a simulator-class child."""

    def __init__(self, name: str = "schedule-switch", *, checked: bool) -> None:
        super().__init__(name)
        self.checked = checked
        self._simulator = FakeLocator(
            "simulator",
            attributes={
                "class": "d-switch-simulator "
                + ("checked" if checked else "unchecked")
            },
        )

    def locator(self, selector: str):
        if selector == ".d-switch-simulator":
            return self._simulator
        return super().locator(selector)


class _TimeInput(FakeLocator):
    """Date input that returns scripted ``input.value`` reads in order."""

    def __init__(
        self,
        name: str = "schedule-input",
        *,
        values: list[str] | tuple[str, ...] = (),
        read_error: BaseException | None = None,
    ) -> None:
        super().__init__(
            name, computed_style=dict(INPUT_FACTS), attributes={"type": "text"}
        )
        self.values = list(values)
        self.reads = 0
        self.read_error = read_error
        self.blurs = 0

    async def input_value(self):
        self.reads += 1
        if self.read_error is not None:
            raise self.read_error
        if not self.values:
            return ""
        return self.values[min(self.reads - 1, len(self.values) - 1)]

    async def blur(self):
        self.blurs += 1
        self.actions.append(("blur",))


class _CountingLocator(FakeLocator):
    def __init__(self, name: str = "counting", *, count: int = 0) -> None:
        super().__init__(name, count=count)
        self.count_calls = 0

    async def count(self) -> int:
        self.count_calls += 1
        return await super().count()


class _FileInput(FakeLocator):
    def __init__(self, name: str = "file-input") -> None:
        super().__init__(name, computed_style=dict(INPUT_FACTS))
        self.files: list[object] = []

    async def set_input_files(self, files, **kwargs) -> None:
        self.files.append(files)


class _PublishButton(RecordingLocator):
    def __init__(self, name: str = "publish") -> None:
        super().__init__(name, computed_style=dict(SWITCH_FACTS))
        self.box = {"x": 10.0, "y": 20.0, "width": 160.0, "height": 40.0}

    async def bounding_box(self):
        return dict(self.box)

    async def evaluate(self, expression, arg=None):
        self.evaluate_calls.append((expression, arg))
        if isinstance(expression, str) and "elementFromPoint" in expression:
            return {
                "self": True,
                "tag": "button",
                "className": "",
                "id": "",
                "text": "",
            }
        return dict(self._computed_style or SWITCH_FACTS)


class _QuietHumanizer(xhs_main.Humanizer):
    """Real sequencing, zero wall-clock pauses."""

    def __init__(self, page, *, profile=None, rng=None, sleep=None):
        kwargs = {"sleep": _noop_async_sleep}
        if profile is not None:
            kwargs["profile"] = profile
        if rng is not None:
            kwargs["rng"] = rng
        super().__init__(page, **kwargs)


def _meta_selectors(*, title_error: int = 0, body_error: int = 0) -> dict:
    return {
        TITLE_PRIMARY: FakeLocator("title", computed_style=dict(INPUT_FACTS)),
        'div.tiptap[role="textbox"][contenteditable="true"]': FakeLocator(
            "desc", computed_style=dict(INPUT_FACTS)
        ),
        xhs_main.XHS_TITLE_MAX_SUFFIX_SELECTORS[0]: FakeLocator(
            "title-suffix", count=title_error
        ),
        xhs_main.XHS_TITLE_MAX_SUFFIX_SELECTORS[1]: FakeLocator(
            "title-suffix-alt", count=0
        ),
        xhs_main.XHS_BODY_LENGTH_ERROR_SELECTOR: FakeLocator(
            "body-error", count=body_error
        ),
    }


def _schedule_page(
    *,
    switch_checked: bool = True,
    values: list[str] | tuple[str, ...] = (),
    read_error: BaseException | None = None,
) -> RecordingPage:
    selectors = _meta_selectors()
    selectors.update(
        {
            SCHEDULE_SWITCH: _ScheduleSwitch(checked=switch_checked),
            SCHEDULE_INPUT: _TimeInput(values=values, read_error=read_error),
            SCHEDULE_DATE_INPUT: FakeLocator(
                "date-container-input",
                computed_style=dict(INPUT_FACTS),
                attributes={"type": "text"},
            ),
        }
    )
    return RecordingPage(url=NOTE_URL, selectors=selectors)


def _note_chain_page(
    *,
    schedule: bool,
    switch_checked: bool = True,
    values: list[str] | tuple[str, ...] = (),
) -> tuple[RecordingPage, _PublishButton, _ScheduleSwitch | None, _TimeInput | None]:
    button = _PublishButton()
    selectors = _meta_selectors()
    selectors.update(
        {
            NOTE_IMAGE_INPUT_SELECTOR: _FileInput("image-input"),
            NOTE_TILES_SELECTOR: preview_tiles(1),
            PUBLISH_SELECTOR: button,
            LOGIN_BOX: FakeLocator("login-box", count=0),
        }
    )
    switch = None
    time_input = None
    if schedule:
        switch = _ScheduleSwitch(checked=switch_checked)
        time_input = _TimeInput(values=values)
        selectors.update(
            {
                SCHEDULE_SWITCH: switch,
                SCHEDULE_INPUT: time_input,
                SCHEDULE_DATE_INPUT: FakeLocator(
                    "date-container-input",
                    computed_style=dict(INPUT_FACTS),
                    attributes={"type": "text"},
                ),
            }
        )
    return RecordingPage(url=NOTE_URL, selectors=selectors), button, switch, time_input


def _run_meta_fill(app, *, title_error: int = 0, body_error: int = 0):
    page = RecordingPage(url=NOTE_URL, selectors=_meta_selectors(
        title_error=title_error, body_error=body_error
    ))
    with (
        patch.dict(os.environ, {"HUMANIZE": "0"}),
        patch.object(app, "_insert_topic", new=AsyncMock(return_value=None)),
    ):
        asyncio.run(app.fill_meta(page))
    return page


# ---------------------------------------------------------------------------
# 1. Title metric + validation
# ---------------------------------------------------------------------------


class Decision11ReadbackTitleMetricTests(unittest.TestCase):
    def test_ascii_counts_one_per_code_unit(self):
        # 平台口径：两个 ASCII 码元 = 1，向上取整。
        self.assertEqual(xhs_main.xhs_title_length("abcde"), 3)
        self.assertEqual(xhs_main.xhs_title_length("a" * 40), 20)

    def test_cjk_counts_two_per_code_unit(self):
        self.assertEqual(xhs_main.xhs_title_length("你好"), 2)
        self.assertEqual(xhs_main.xhs_title_length("你好世界你好世界你好世界你好"), 14)

    def test_emoji_counts_as_two(self):
        # U+1F600 is a surrogate pair: 2 + 2 weighted → ceil(4 / 2).
        self.assertEqual(xhs_main.xhs_title_length("😀"), 2)

    def test_combining_mark_counts_as_two(self):
        # ASCII base (1) + non-ASCII combining mark (2) → ceil(3 / 2).
        self.assertEqual(xhs_main.xhs_title_length("e\u0301"), 2)

    def test_limit_is_twenty(self):
        self.assertEqual(xhs_main.XHS_TITLE_MAX_LENGTH, 20)

    def test_truncation_never_splits_a_code_point(self):
        # ASCII: 40 units → 20; the 41st would be 21 and is dropped.
        self.assertEqual(xhs_main.xhs_truncate_title("a" * 41), "a" * 40)
        self.assertEqual(xhs_main.xhs_truncate_title("字" * 25), "字" * 20)
        emoji = "😀" * 11
        truncated = xhs_main.xhs_truncate_title(emoji)
        self.assertEqual(truncated, "😀" * 10)
        self.assertLessEqual(xhs_main.xhs_title_length(truncated), 20)


class Decision11ReadbackTitleValidationTests(unittest.TestCase):
    def _note_with_image(self, tmp: str, **overrides):
        image = Path(tmp) / "a.png"
        image.write_bytes(b"image")
        values = {
            "image_paths": [str(image)],
            "note": "正文",
            "tags": [],
            "publish_date": 0,
            "account_file": "account.json",
        }
        values.update(overrides)
        return xhs_main.XiaoHongShuNote(**values)

    def test_auto_title_is_truncated_and_warned(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self._note_with_image(tmp, note="字" * 30)
            fake_logger = Mock()
            with patch.object(xhs_main, "xiaohongshu_logger", fake_logger):
                asyncio.run(app.validate_upload_args(check_cookie=False))
        self.assertEqual(xhs_main.xhs_title_length(app.title), 20)
        self.assertTrue(fake_logger.warning.called)

    def test_explicit_over_limit_fails_without_truncating(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self._note_with_image(tmp, title="字" * 21)
            with self.assertRaises(ValueError) as ctx:
                asyncio.run(app.validate_upload_args(check_cookie=False))
        message = str(ctx.exception)
        self.assertIn("当前 21 / 上限 20", message)
        self.assertIn("UTF-16", message)
        self.assertEqual(app.title, "字" * 21)

    def test_explicit_title_at_limit_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self._note_with_image(tmp, title="字" * 20)
            asyncio.run(app.validate_upload_args(check_cookie=False))
        self.assertEqual(app.title, "字" * 20)


class Decision11ReadbackTitleSuffixTests(unittest.TestCase):
    def test_waits_at_least_350ms_then_polls_to_500ms(self):
        app = _note_app(desc="描述")
        page = RecordingPage(url=NOTE_URL, selectors=_meta_selectors())
        with patch.object(xhs_main, "Humanizer", _QuietHumanizer):
            asyncio.run(app.fill_title(page))

        self.assertEqual(
            page.timeouts("wait_for_timeout"), [350, 50, 50, 50]
        )

    def test_suffix_node_present_fails_before_any_click(self):
        app = _note_app(desc="描述")
        page = RecordingPage(
            url=NOTE_URL, selectors=_meta_selectors(title_error=1)
        )
        with (
            patch.object(xhs_main, "Humanizer", _QuietHumanizer),
            self.assertRaises(ElementUnusableError),
        ):
            asyncio.run(app.fill_title(page))

        self.assertEqual(page.mouse.down_count, 0)
        self.assertEqual(page.mouse.up_count, 0)
        # The mandatory settle still happens before the existence probe.
        self.assertEqual(page.timeouts("wait_for_timeout")[0], 350)

    def test_alternate_suffix_node_is_accepted_as_a_signal(self):
        app = _note_app(desc="描述")
        selectors = _meta_selectors()
        selectors[xhs_main.XHS_TITLE_MAX_SUFFIX_SELECTORS[0]] = FakeLocator(
            "title-suffix", count=0
        )
        selectors[xhs_main.XHS_TITLE_MAX_SUFFIX_SELECTORS[1]] = FakeLocator(
            "title-suffix-alt", count=1
        )
        clock = FakeClock()
        page = RecordingPage(url=NOTE_URL, selectors=selectors)
        with (
            patch.object(xhs_main, "Humanizer", _QuietHumanizer),
            clock.patch(xhs_main),
            self.assertRaises(ElementUnusableError),
        ):
            asyncio.run(app.fill_title(page))

    def test_explicit_title_is_typed_verbatim(self):
        title = "字" * 21
        app = _note_app(desc="描述", title=title)
        page = RecordingPage(url=NOTE_URL, selectors=_meta_selectors())
        with patch.dict(os.environ, {"HUMANIZE": "0"}):
            asyncio.run(app.fill_title(page))
        self.assertIn(("insert_text", title), page.keyboard.actions)


# ---------------------------------------------------------------------------
# 2. Body metric + the single post-type gate
# ---------------------------------------------------------------------------


class Decision11ReadbackBodyMetricTests(unittest.TestCase):
    def test_body_counts_each_character_once(self):
        self.assertEqual(xhs_main.xhs_body_length("你好", []), 2)
        self.assertEqual(xhs_main.xhs_body_length("a" * 1000, []), 1000)

    def test_topic_anchor_counts_as_hash_name(self):
        # `#旅行pov[话题]#` → `#旅行pov` (6) + one separator = 7.
        self.assertEqual(xhs_main.xhs_body_length("", ["旅行pov"]), 7)
        self.assertEqual(xhs_main.xhs_body_length("你好", ["旅行pov"]), 9)

    def test_limit_is_one_thousand(self):
        self.assertEqual(xhs_main.XHS_BODY_MAX_LENGTH, 1000)


class Decision11ReadbackBodyLengthTests(unittest.TestCase):
    def test_length_error_present_after_desc_and_tags_fails(self):
        app = _note_app(desc="正文", tags=["旅行pov"])
        with self.assertRaises(ElementUnusableError):
            _run_meta_fill(app, body_error=1)

    def test_length_error_checked_exactly_once_after_topics(self):
        app = _note_app(desc="正文", tags=["旅行pov"])
        page = RecordingPage(url=NOTE_URL, selectors=_meta_selectors())
        counting = _CountingLocator("length-error", count=0)
        page._selectors[xhs_main.XHS_BODY_LENGTH_ERROR_SELECTOR] = counting
        with (
            patch.dict(os.environ, {"HUMANIZE": "0"}),
            patch.object(app, "_insert_topic", new=AsyncMock(return_value=None)),
        ):
            asyncio.run(app.fill_meta(page))

        self.assertEqual(counting.count_calls, 1)
        # Every topic keystroke happened before the single length check.
        topic_actions = [
            action for action in page.keyboard.actions
            if action[0] == "insert_text" and "旅行pov" in action[1]
        ]
        self.assertTrue(topic_actions)

    def test_absent_length_error_passes(self):
        app = _note_app(desc="正文", tags=["旅行pov"])
        _run_meta_fill(app, body_error=0)


# ---------------------------------------------------------------------------
# 3. Schedule window + wall-clock semantics
# ---------------------------------------------------------------------------


class Decision11ReadbackScheduleWindowTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 12, 10, 0, 0)

    def test_exactly_two_hours_ahead_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            xhs_main.xhs_validate_schedule_time(
                self.now + timedelta(hours=2), now=self.now
            )
        self.assertIn("2 小时", str(ctx.exception))

    def test_just_over_two_hours_is_accepted(self):
        value = self.now + timedelta(hours=2, seconds=1)
        self.assertEqual(
            xhs_main.xhs_validate_schedule_time(value, now=self.now), value
        )

    def test_exactly_fourteen_days_is_accepted(self):
        value = self.now + timedelta(days=14)
        self.assertEqual(
            xhs_main.xhs_validate_schedule_time(value, now=self.now), value
        )

    def test_over_fourteen_days_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            xhs_main.xhs_validate_schedule_time(
                self.now + timedelta(days=14, seconds=1), now=self.now
            )
        self.assertIn("14 天", str(ctx.exception))

    def test_aware_offset_is_ignored_for_validation(self):
        aware = (self.now + timedelta(hours=3)).replace(
            tzinfo=timezone(timedelta(hours=-8))
        )
        result = xhs_main.xhs_validate_schedule_time(aware, now=self.now)
        self.assertIsNone(result.tzinfo)
        self.assertEqual(result, self.now + timedelta(hours=3))

    def test_validate_base_args_normalizes_aware_input_to_wall_time(self):
        aware = (_requested(3)).replace(tzinfo=timezone(timedelta(hours=-8)))
        app = _note_app(
            publish_strategy=xhs_main.XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED,
            publish_date=aware,
        )
        asyncio.run(app.validate_base_args(check_cookie=False))
        self.assertIsNone(app.publish_date.tzinfo)
        self.assertEqual(app.publish_date, aware.replace(tzinfo=None))

    def test_validate_base_args_rejects_over_fourteen_days(self):
        app = _note_app(
            publish_strategy=xhs_main.XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED,
            publish_date=datetime.now() + timedelta(days=15),
        )
        with self.assertRaises(ValueError):
            asyncio.run(app.validate_base_args(check_cookie=False))

    def test_immediate_strategy_stays_zero(self):
        app = _note_app(publish_date=0)
        asyncio.run(app.validate_base_args(check_cookie=False))
        self.assertEqual(app.publish_date, 0)


# ---------------------------------------------------------------------------
# 4. Schedule C1 / C2 (set time) and C3 (before FIRE)
# ---------------------------------------------------------------------------


class Decision11ReadbackScheduleReadbackTests(unittest.TestCase):
    def _app(self, requested: datetime | None = None):
        return _note_app(
            publish_strategy=xhs_main.XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED,
            publish_date=requested or _requested(),
        )

    def _run_set(self, page, requested: datetime):
        app = self._app(requested)
        with patch.dict(os.environ, {"HUMANIZE": "0"}):
            asyncio.run(
                app.set_schedule_time_xiaohongshu(
                    page, requested, humanizer=app._humanizer(page)
                )
            )
        return app

    def test_c1_rejects_an_unchecked_switch(self):
        requested = _requested()
        page = _schedule_page(switch_checked=False, values=[_text(requested)])
        with self.assertRaises(ElementUnusableError):
            self._run_set(page, requested)

    def test_c1_requires_the_date_input_to_be_attached(self):
        requested = _requested()
        page = _schedule_page(values=[_text(requested)])
        page._selectors[SCHEDULE_DATE_INPUT] = FakeLocator(
            "date-container-input", count=0
        )
        with self.assertRaises(ElementUnusableError):
            self._run_set(page, requested)

    def test_c2_blur_only_and_one_read(self):
        requested = _requested()
        page = _schedule_page(values=[_text(requested)])
        self._run_set(page, requested)

        time_input = page.locator(SCHEDULE_INPUT)
        self.assertEqual(time_input.blurs, 1)
        self.assertEqual(time_input.reads, 1)
        # Never Tab/Enter/click-to-blur.
        for action in page.keyboard.actions:
            self.assertNotIn(action, (("press", "Tab"), ("press", "Enter")))
        self.assertNotIn(("click",), time_input.actions)

    def test_c2_parses_and_compares_by_minute(self):
        requested = (_requested()).replace(second=45)
        page = _schedule_page(values=[_text(requested)])
        # Same minute, different seconds → still equal.
        self._run_set(page, requested)

    def test_c2_rollback_is_a_mismatch(self):
        requested = _requested()
        rolled_back = _text(requested - timedelta(hours=1))
        page = _schedule_page(values=[rolled_back])
        with self.assertRaises(ElementUnusableError):
            self._run_set(page, requested)
        # No retry: exactly one read after the blur.
        self.assertEqual(page.locator(SCHEDULE_INPUT).reads, 1)

    def test_c2_read_failure_is_a_mismatch(self):
        requested = _requested()
        page = _schedule_page(
            values=[_text(requested)], read_error=RuntimeError("detached")
        )
        with self.assertRaises(ElementUnusableError):
            self._run_set(page, requested)

    def test_c2_empty_value_is_a_mismatch(self):
        requested = _requested()
        page = _schedule_page(values=[""])
        with self.assertRaises(ElementUnusableError):
            self._run_set(page, requested)

    def test_c2_unparseable_value_is_a_mismatch(self):
        requested = _requested()
        page = _schedule_page(values=["not-a-date"])
        with self.assertRaises(ElementUnusableError):
            self._run_set(page, requested)

    def test_c3_passes_with_matching_value(self):
        requested = _requested()
        page = _schedule_page(values=[_text(requested)])
        app = self._app(requested)
        asyncio.run(app._verify_schedule_before_fire(page))

    def test_c3_late_reset_is_a_mismatch(self):
        requested = _requested()
        page = _schedule_page(values=[_text(requested + timedelta(hours=1))])
        app = self._app(requested)
        with self.assertRaises(ElementUnusableError):
            asyncio.run(app._verify_schedule_before_fire(page))

    def test_c3_expired_request_is_a_mismatch(self):
        requested = _requested()
        page = _schedule_page(values=[_text(requested)])
        app = self._app(requested)

        class _FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return requested + timedelta(minutes=1)

        with patch.object(xhs_main, "datetime", _FrozenDatetime):
            with self.assertRaises(ElementUnusableError):
                asyncio.run(app._verify_schedule_before_fire(page))

    def test_c3_unchecked_switch_is_a_mismatch(self):
        requested = _requested()
        page = _schedule_page(switch_checked=False, values=[_text(requested)])
        app = self._app(requested)
        with self.assertRaises(ElementUnusableError):
            asyncio.run(app._verify_schedule_before_fire(page))

    def test_c3_read_failure_is_a_mismatch(self):
        requested = _requested()
        page = _schedule_page(
            values=[_text(requested)], read_error=RuntimeError("detached")
        )
        app = self._app(requested)
        with self.assertRaises(ElementUnusableError):
            asyncio.run(app._verify_schedule_before_fire(page))
        self.assertEqual(page.locator(SCHEDULE_INPUT).reads, 1)


# ---------------------------------------------------------------------------
# 5. Entry points: --no-publish checks, immediate bypasses everything
# ---------------------------------------------------------------------------


class Decision11ReadbackScheduleEntryTests(unittest.TestCase):
    def test_no_publish_still_runs_c2_and_c3(self):
        requested = _requested()
        page, button, switch, time_input = _note_chain_page(
            schedule=True, values=[_text(requested)]
        )
        app = _note_app(
            publish_strategy=xhs_main.XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED,
            publish_date=requested,
            no_publish=True,
        )
        clock = FakeClock()
        with (
            patch.object(xhs_main, "Humanizer", _QuietHumanizer),
            clock.patch(xhs_main),
        ):
            asyncio.run(app.upload_note_content(page, mode="local"))

        self.assertEqual(time_input.blurs, 1)
        self.assertEqual(time_input.reads, 2)  # C2 + C3, one read each
        # The humanizer dispatches the switch through the mouse; the publish
        # button is never pressed.
        self.assertEqual(page.mouse.down_count, 1)

    def test_no_publish_c3_mismatch_is_exit_1(self):
        requested = _requested()
        wrong = _text(requested + timedelta(hours=1))
        page, _button, _switch, _time_input = _note_chain_page(
            schedule=True, values=[_text(requested), wrong]
        )
        app = _note_app(
            publish_strategy=xhs_main.XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED,
            publish_date=requested,
            no_publish=True,
        )
        clock = FakeClock()
        with (
            patch.object(xhs_main, "Humanizer", _QuietHumanizer),
            clock.patch(xhs_main),
            self.assertRaises(ElementUnusableError),
        ):
            asyncio.run(app.upload_note_content(page, mode="local"))
        # Only the schedule switch was clicked; FIRE never happened.
        self.assertEqual(page.mouse.down_count, 1)

    def test_c3_runs_after_not_before_and_before_fire(self):
        requested = _requested()
        wrong = _text(requested + timedelta(hours=1))
        page, button, _switch, _time_input = _note_chain_page(
            schedule=True, values=[_text(requested), wrong]
        )
        app = _note_app(
            publish_strategy=xhs_main.XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED,
            publish_date=requested,
            no_publish=False,
        )
        not_before = AsyncMock(return_value=None)
        clock = FakeClock()
        with (
            patch.object(xhs_main, "Humanizer", _QuietHumanizer),
            patch.object(
                publish_timeout, "wait_until_publish_allowed", new=not_before
            ),
            clock.patch(xhs_main),
            self.assertRaises(ElementUnusableError),
        ):
            asyncio.run(app.upload_note_content(page, mode="local"))

        not_before.assert_awaited_once()
        self.assertEqual(page.mouse.down_count, 1)
        self.assertEqual(button.click_count, 0)

    def test_immediate_publish_never_touches_the_schedule(self):
        page, _button, _switch, _time_input = _note_chain_page(schedule=False)
        app = _note_app(publish_date=0, no_publish=True)
        clock = FakeClock()
        with (
            patch.object(xhs_main, "Humanizer", _QuietHumanizer),
            clock.patch(xhs_main),
        ):
            asyncio.run(app.upload_note_content(page, mode="local"))

        # An unscripted schedule selector would have raised; nothing was read.
        self.assertEqual(page.mouse.down_count, 0)


# ---------------------------------------------------------------------------
# 6. Original declaration semantics
# ---------------------------------------------------------------------------


def _original_page(
    *, checked: bool, click_error: BaseException | None = None, modal: bool = True
) -> RecordingPage:
    switch = _Interactive(
        "original-switch",
        attributes={"aria-checked": "true" if checked else "false"},
        click_error=click_error,
    )
    selectors = {
        xhs_main.XHS_ORIGINAL_SWITCH_CANDIDATES[0].selector: switch,
    }
    if modal:
        modal_locator = FakeLocator(
            "original-modal",
            computed_style=dict(VISIBLE_FACTS),
            children={
                ".d-checkbox": FakeLocator("checkbox"),
                "button.custom-button": FakeLocator(
                    "confirm", computed_style=dict(VISIBLE_FACTS)
                ),
            },
        )
        selectors[xhs_main.XHS_ORIGINAL_MODAL_CANDIDATES[0].selector] = modal_locator
    else:
        selectors[xhs_main.XHS_ORIGINAL_MODAL_CANDIDATES[0].selector] = FakeLocator(
            "no-modal", count=0
        )
        # 中文兜底候选（get_by_role → filter）也必须可解析为 0 命中。
        selectors["role:dialog"] = FakeLocator("no-dialog", count=0)
    return RecordingPage(url=NOTE_URL, selectors=selectors)


class Decision11ReadbackOriginalTests(unittest.TestCase):
    def _run(self, app, page):
        clock = FakeClock()
        with (
            patch.dict(os.environ, {"HUMANIZE": "0"}),
            clock.patch(xhs_main, dom),
        ):
            asyncio.run(app.apply_declarations(page))

    def test_true_off_clicks_and_confirms(self):
        page = _original_page(checked=False)
        app = _video_app(original_declaration=True)
        self._run(app, page)
        switch = page.locator(xhs_main.XHS_ORIGINAL_SWITCH_CANDIDATES[0].selector)
        self.assertEqual(switch.click_count, 1)

    def test_true_already_on_never_clicks(self):
        page = _original_page(checked=True, modal=False)
        app = _video_app(original_declaration=True)
        self._run(app, page)
        switch = page.locator(xhs_main.XHS_ORIGINAL_SWITCH_CANDIDATES[0].selector)
        self.assertEqual(switch.click_count, 0)

    def test_true_missing_confirmation_is_exit_1(self):
        page = _original_page(checked=False, modal=False)
        app = _video_app(original_declaration=True)
        with self.assertRaises(RuntimeError):
            self._run(app, page)

    def test_true_click_failure_is_exit_1(self):
        page = _original_page(checked=False, click_error=RuntimeError("covered"))
        app = _video_app(original_declaration=True)
        with self.assertRaises(RuntimeError):
            self._run(app, page)

    def test_false_on_clicks_once_to_turn_off(self):
        page = _original_page(checked=True, modal=False)
        app = _video_app(original_declaration=False)
        self._run(app, page)
        switch = page.locator(xhs_main.XHS_ORIGINAL_SWITCH_CANDIDATES[0].selector)
        self.assertEqual(switch.click_count, 1)

    def test_false_missing_control_means_already_off(self):
        card = FakeLocator(
            "card",
            count=0,
            children={".d-switch": FakeLocator("card-switch", count=0)},
        )
        page = RecordingPage(
            url=NOTE_URL,
            selectors={
                **{
                    candidate.selector: FakeLocator("absent", count=0)
                    for candidate in xhs_main.XHS_ORIGINAL_SWITCH_CANDIDATES
                },
                ".custom-switch-card": card,
            },
        )
        app = _video_app(original_declaration=False)
        self._run(app, page)  # no exception

    def test_false_click_failure_is_warning_only(self):
        page = _original_page(checked=True, click_error=RuntimeError("covered"))
        app = _video_app(original_declaration=False)
        self._run(app, page)  # no exception

    def test_none_never_touches_the_page(self):
        page = RecordingPage(url=NOTE_URL, selectors={})
        app = _video_app(original_declaration=None)
        asyncio.run(app.apply_declarations(page))

    def _simulator_page(self, *, checked: bool) -> tuple[RecordingPage, _ScheduleSwitch]:
        switch = _ScheduleSwitch(checked=checked)
        modal_locator = FakeLocator(
            "original-modal",
            computed_style=dict(VISIBLE_FACTS),
            children={
                ".d-checkbox": FakeLocator("checkbox"),
                "button.custom-button": FakeLocator(
                    "confirm", computed_style=dict(VISIBLE_FACTS)
                ),
            },
        )
        page = RecordingPage(
            url=NOTE_URL,
            selectors={
                xhs_main.XHS_ORIGINAL_SWITCH_CANDIDATES[0].selector: switch,
                xhs_main.XHS_ORIGINAL_MODAL_CANDIDATES[0].selector: modal_locator,
            },
        )
        return page, switch

    def test_true_falls_back_to_the_simulator_class(self):
        page, switch = self._simulator_page(checked=True)
        app = _video_app(original_declaration=True)
        self._run(app, page)  # already on: no click, no modal access needed
        self.assertEqual(switch.click_count, 0)

    def test_false_falls_back_to_the_simulator_class(self):
        page, switch = self._simulator_page(checked=True)
        app = _video_app(original_declaration=False)
        self._run(app, page)
        self.assertEqual(switch.click_count, 1)


if __name__ == "__main__":
    unittest.main()
