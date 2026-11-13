# -*- coding: utf-8 -*-
"""Facebook Page / Meta Business Suite 人类化接线（spec §3.8 / §6.2）。

三块，全部离线：

1. 事件序列 —— 每个改 Humanizer 的点断言原语（``press`` / ``insert_text``）、
   ``after_type`` 次数、``mouse.move* → down → up``、hit-test 先于 ``down``、
   零原生 ``locator.click()``、零 ``force``。
2. 字段值读回 —— fake 键盘把按键写回持有缓冲的 locator，断言最终值与预期
   完全相等（抓「序列对、值错」：清空不净、追加、CRLF 残留）。
3. 平台静态门 —— 包内跑 spec §4.2–4.5 的 A–E 门。

另外覆盖 ``HUMANIZE=0`` 快路径与收窄后多义硬错（``ambiguous:N``）。
选择器未 scripted 直接抛 :class:`UnscriptedSelectorError`，不用 MagicMock。
"""

from __future__ import annotations

import asyncio
import os
import random
import re
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import uploader.meta_uploader.facebook_page_uploader.main as fb_main
from tests.fakes_xhs_dom import (
    FakeLocator,
    RecordingKeyboard,
    RecordingLocator,
    RecordingMouse,
    RecordingPage,
    UnscriptedSelectorError,
)
from tests.humanize_gates import assert_clean
from utils.dom import ElementUnusableError
from utils.errors import PublishResultUnknownError
from utils.humanize import HumanizeProfile, LogNormal
from utils.humanize import MAYBE_DISPATCHED, MAYBE_DISPATCHED_VALUE

AFTER_TYPE = 5.0
BEFORE_SUBMIT = 7.0


def _fixed(seconds: float) -> LogNormal:
    return LogNormal(0.0, 0.0, seconds, seconds)


#: 固定停顿表：5.0s 只可能是 after_type，7.0s 只可能是 before_submit。
TEST_PROFILE = HumanizeProfile(
    keystroke=_fixed(0.01),
    after_type=_fixed(AFTER_TYPE),
    after_navigate=_fixed(2.0),
    before_submit=_fixed(BEFORE_SUBMIT),
    pointer_settle=_fixed(0.02),
    click_hold=_fixed(0.03),
    before_click=_fixed(0.04),
    after_click=_fixed(0.05),
    between_scroll=_fixed(0.06),
    reading=_fixed(0.07),
    after_interact=_fixed(0.08),
)

REEL_TITLE = (
    '[data-surface$="bizweb_create_reel:left_panel"] input[type="text"]'
    ':not([role]):visible'
)
CAPTION_EDITOR = '[contenteditable="true"]:visible'
REEL_ROOT = '[data-surface$="lib:bizweb_create_reel"]'
REEL_STEPS = '[role="button"][aria-labelledby]:not([aria-haspopup])'
REEL_FOOTER = '[data-surface$="bizweb_create_reel:footer"]'
REEL_STORY = (
    '[data-surface$="bizweb_create_reel:left_panel"] input[role="switch"]'
)
STORY_XPATH = (
    'xpath=self::input[ancestor::div[.//img[@alt="Facebook"] '
    'and count(.//input[@role="switch"])=1]]'
)
REEL_REGION = '[data-surface$="bizweb_create_reel:left_panel"]'
POST_FOOTER = '[data-surface$="lib:bizweb_create_post:footer"]'
POST_PUBLISHING = '[data-surface$="lib:bizweb_create_post:publishing_options"]'
MODES = '[role="button"][aria-pressed]'
MODES_XPATH = 'xpath=self::*[not(ancestor::*[@role="grid"])]'
DATE_INPUT = 'input[placeholder]:not([role])'
GRID = '[role="grid"][aria-labelledby]'
CALENDAR = 'xpath=ancestor::div[.//*[@role="button"][@aria-busy]][1]'
CALENDAR_BUTTONS = '[role="button"][aria-busy]'
HOUR = '[role="spinbutton"][aria-valuemax="23"], [role="spinbutton"][aria-valuemax="12"]'
MINUTE = '[role="spinbutton"][aria-valuemax="59"]'
PERIOD = '[role="spinbutton"][aria-valuemax="1"]'
ONCE = 'input[value="Once"]'


def _expr_kind(expression) -> str:
    if not isinstance(expression, str):
        return "unknown"
    if "elementFromPoint" in expression and "childFrame" not in expression:
        return "hit-test"
    if "childFrame" in expression:
        return "geometry"
    if "getComputedStyle" in expression:
        return "facts"
    return "unknown"


class _Clickable(RecordingLocator):
    """可被 ``Humanizer.click`` 坐标点击的 fake：盒模型 + 事实探测 + 命中测试。"""

    def __init__(self, name: str, *, log: list, **kwargs) -> None:
        kwargs.setdefault(
            "box", {"x": 10.0, "y": 20.0, "width": 60.0, "height": 24.0}
        )
        super().__init__(name, **kwargs)
        self._log = log

    async def evaluate(self, expression, arg=None):
        self.evaluate_calls.append((expression, arg))
        kind = _expr_kind(expression)
        self._log.append(("evaluate", kind, self.name))
        if kind == "hit-test":
            return {"self": True, "tag": "div", "className": "", "id": "", "text": ""}
        if kind == "geometry":
            return {
                "width": 60.0,
                "height": 24.0,
                "inside": True,
                "clipped": False,
                "childFrame": False,
            }
        return {
            "tag": "div",
            "display": "block",
            "visibility": "visible",
            "opacity": 1.0,
            "disabled": False,
            "isConnected": True,
        }

    async def scroll_into_view_if_needed(self, **kwargs) -> None:
        self.actions.append(("scroll",))


class _RegexLocator(_Clickable):
    """支持 ``get_by_role(..., name=re.Pattern)`` 的可访问名称收窄。"""

    def get_by_role(self, role: str, name=None, **kwargs):
        if isinstance(name, re.Pattern):
            for key, child in self._children.items():
                match = re.fullmatch(fr"role:{re.escape(role)}:(.*)", key)
                if match is not None and name.search(match.group(1)):
                    return child
            raise UnscriptedSelectorError(
                f"{self.name}: no role={role!r} child matches {name!r}; "
                f"scripted children: {sorted(self._children)}"
            )
        return super().get_by_role(role, name)


class _TypingLocator(_RegexLocator):
    """持有键入缓冲的 locator；键盘事件写回当前 focus 的实例。"""

    def __init__(self, name: str, *, log: list, initial: str = "", **kwargs):
        super().__init__(name, log=log, **kwargs)
        self.buffer = initial
        self._page = None

    async def focus(self, **kwargs) -> None:
        self.actions.append(("focus",))
        if self._page is not None:
            self._page.focused = self
            self._page.selected = False

    async def inner_text(self) -> str:
        return self.buffer

    async def input_value(self) -> str:
        return self.buffer

    def apply_key(self, key: str) -> None:
        page = self._page
        if page is None or page.focused is not self:
            return
        if key in ("ControlOrMeta+A", "Control+A", "Meta+A"):
            page.selected = True
        elif key in ("Delete", "Backspace"):
            if page.selected:
                self.buffer = ""
            elif key == "Backspace":
                self.buffer = self.buffer[:-1]
            page.selected = False
        elif key == "Enter":
            self.buffer += "\n"
        elif len(key) == 1:
            if page.selected:
                self.buffer = key
                page.selected = False
            else:
                self.buffer += key

    def apply_text(self, text: str) -> None:
        page = self._page
        if page is None or page.focused is not self:
            return
        if page.selected:
            self.buffer = text
            page.selected = False
        else:
            self.buffer += text


class _Switch(_RegexLocator):
    def __init__(self, name: str, *, log: list, checked: bool, **kwargs) -> None:
        super().__init__(name, log=log, **kwargs)
        self.checked = checked
        self.reads = 0

    async def is_checked(self) -> bool:
        self.reads += 1
        self._log.append(("is_checked", self.name))
        return self.checked


class _Checkable(FakeLocator):
    """``input[type=radio]`` / ``role=switch`` 的原生 check()。"""

    def __init__(self, name: str, **kwargs) -> None:
        super().__init__(name, **kwargs)
        self.checked = False

    async def check(self, **kwargs) -> None:
        self.checked = True
        self.actions.append(("check",))


class _OrderedMouse(RecordingMouse):
    def __init__(self, log: list) -> None:
        super().__init__()
        self._log = log

    async def move(self, x: float, y: float, **kwargs) -> None:
        self.actions.append(("move", x, y))
        self._log.append(("move", x, y))

    async def down(self, **kwargs) -> None:
        self.actions.append(("down",))
        self.down_count += 1
        self._log.append(("down",))

    async def up(self, **kwargs) -> None:
        self.actions.append(("up",))
        self.up_count += 1
        self._log.append(("up",))


class _TypingKeyboard(RecordingKeyboard):
    def __init__(self, page: "_RegexPage") -> None:
        super().__init__()
        self._page = page

    async def press(self, key: str, **kwargs) -> None:
        self.actions.append(("press", key))
        self._page.apply_key(key)

    async def insert_text(self, text: str, **kwargs) -> None:
        self.actions.append(("insert_text", text))
        self._page.apply_text(text)


class _RegexPage(RecordingPage):
    """带确定顺序日志、正则角色匹配和 focus 键盘的 page double。"""

    def __init__(self, *, log: list, **kwargs) -> None:
        self.interactions = log
        super().__init__(**kwargs)
        self.mouse = _OrderedMouse(log)
        self.keyboard = _TypingKeyboard(self)
        self.focused = None
        self.selected = False

    def get_by_role(self, role: str, name=None, **kwargs):
        if isinstance(name, re.Pattern):
            for key, child in self._selectors.items():
                match = re.fullmatch(fr"role:{re.escape(role)}:(.*)", key)
                if match is not None and name.search(match.group(1)):
                    return child
            raise UnscriptedSelectorError(
                f"page: no role={role!r} matching {name!r}; "
                f"scripted: {sorted(self._selectors)}"
            )
        return super().get_by_role(role, name)

    def apply_key(self, key: str) -> None:
        if self.focused is not None:
            self.focused.apply_key(key)

    def apply_text(self, text: str) -> None:
        if self.focused is not None:
            self.focused.apply_text(text)


def _attach(page: _RegexPage, locator: FakeLocator) -> None:
    if isinstance(locator, _TypingLocator):
        locator._page = page
    for child in locator._children.values():
        _attach(page, child)


def _page(selectors: dict[str, FakeLocator], *, log: list | None = None) -> _RegexPage:
    log = [] if log is None else log
    page = _RegexPage(log=log, selectors=selectors)
    for locator in selectors.values():
        _attach(page, locator)
    return page


class _QuietHumanizer(fb_main.Humanizer):
    """真实原语、固定停顿表、零墙钟。"""

    def __init__(self, page, *, profile=None, rng=None, sleep=None) -> None:
        self.pauses: list[float] = []
        log = getattr(page, "interactions", None)

        async def _record(seconds: float) -> None:
            self.pauses.append(round(seconds, 4))
            if log is not None:
                log.append(("pause", round(seconds, 4)))

        super().__init__(
            page, profile=TEST_PROFILE, rng=random.Random(0), sleep=_record
        )


class _Expect:
    """顺序记录用 expectation double；计数由 ``_unique`` / fake 断言负责。"""

    def __init__(self, actual, *, negated: bool = False) -> None:
        self.actual = actual
        self.negated = negated
        self.calls: list[str] = []

    @property
    def not_(self) -> "_Expect":
        return _Expect(self.actual, negated=True)

    def __getattr__(self, name):
        async def _record(*args, **kwargs):
            self.calls.append(name)
            return None

        return _record


def _expect(actual) -> _Expect:
    return _Expect(actual)


@contextmanager
def _humanized():
    with (
        patch.object(fb_main, "Humanizer", _QuietHumanizer),
        patch.object(fb_main, "expect", _expect),
    ):
        yield


class _Response:
    url = "https://business.facebook.com/api/graphql"

    class _Request:
        post_data = "fb_api_req_friendly_name=BusinessComposerStoryCreationMutation"

    request = _Request()

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def json(self) -> dict:
        return self._payload


class _ResponseContext:
    def __init__(self, response: _Response) -> None:
        self._response = response

    async def __aenter__(self) -> "_ResponseContext":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    @property
    def value(self):
        async def _resolve() -> _Response:
            return self._response

        return _resolve()


def _app(tmp: str, **overrides) -> fb_main.MetaBusinessUploader:
    values = {
        "platform": "facebook-page",
        "account_file": Path(tmp) / "account.json",
        "title": "Title",
        "description": "Body",
        "result_file": Path(tmp) / "result.json",
    }
    values.update(overrides)
    return fb_main.MetaBusinessUploader(**values)


def _downs_before(log: list, marker: tuple) -> int:
    """``marker`` 之前出现过多少次 mouse.down（用于证明 stillOn 先于派发）。"""

    index = log.index(marker)
    return sum(1 for event in log[:index] if event == ("down",))


# ---------------------------------------------------------------------------
# 1. 事件序列
# ---------------------------------------------------------------------------


class HumanizeEventSequenceTests(unittest.TestCase):
    def test_caption_types_title_then_body_with_one_after_type_each(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _app(
                tmp,
                title="Title",
                description="Body",
                tags=[],
                video_file=Path(tmp) / "clip.mp4",
            )
            log: list = []
            title = _TypingLocator("reel-title", log=log, initial="Old title")
            editor = _TypingLocator("caption", log=log, initial="Old body")
            page = _page({REEL_TITLE: title, CAPTION_EDITOR: editor}, log=log)

            with _humanized():
                asyncio.run(app._fill_caption(page))

            humanizer = app._humanizer_instance
            self.assertEqual(
                page.keyboard.actions,
                [
                    ("press", "ControlOrMeta+A"),
                    ("press", "Delete"),
                    ("press", "T"),
                    ("press", "i"),
                    ("press", "t"),
                    ("press", "l"),
                    ("press", "e"),
                    ("press", "ControlOrMeta+A"),
                    ("press", "Delete"),
                    ("press", "B"),
                    ("press", "o"),
                    ("press", "d"),
                    ("press", "y"),
                ],
            )
            # 每个字段恰一次 after_type：标题一次，正文一次。
            self.assertEqual(humanizer.pauses.count(AFTER_TYPE), 2)
            self.assertEqual(title.buffer, "Title")
            self.assertEqual(editor.buffer, "Body")

    def test_caption_over_horizon_is_one_bulk_insert_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = "字" * 1001
            app = _app(
                tmp,
                title="Title",
                description=body,
                tags=[],
                video_file=Path(tmp) / "clip.mp4",
            )
            log: list = []
            title = _TypingLocator("reel-title", log=log)
            editor = _TypingLocator("caption", log=log)
            page = _page({REEL_TITLE: title, CAPTION_EDITOR: editor}, log=log)

            with _humanized():
                asyncio.run(app._fill_caption(page))

            inserts = [
                action for action in page.keyboard.actions
                if action[0] == "insert_text"
            ]
            self.assertEqual(inserts, [("insert_text", body)])
            self.assertEqual(editor.buffer, body)
            self.assertEqual(app._humanizer_instance.pauses.count(AFTER_TYPE), 2)

    def test_reel_next_switch_and_dialog_actions_are_humanized(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _app(
                tmp, video_file=Path(tmp) / "clip.mp4", description=""
            )
            log: list = []
            next_button = _Clickable("next", log=log)
            steps = FakeLocator("steps", count=3)
            footer = _RegexLocator(
                "footer", log=log, children={"role:button:Next": next_button}
            )
            story = _Switch("story", log=log, checked=True)
            story_host = _RegexLocator(
                "story-host", log=log, children={STORY_XPATH: story}
            )
            radio = _Checkable("once")
            dialog = _RegexLocator(
                "dialog",
                log=log,
                children={ONCE: radio, "role:button:Publish": _Clickable("confirm", log=log)},
            )
            root = _RegexLocator(
                "root", log=log, children={REEL_STEPS: steps}
            )
            page = _page(
                {
                    REEL_ROOT: root,
                    REEL_FOOTER: footer,
                    REEL_STORY: story_host,
                    "input[type=\"radio\"][value=\"Once\"]": FakeLocator("once-filter"),
                    "role:dialog": dialog,
                },
                log=log,
            )

            with _humanized():
                asyncio.run(app._advance_reels(page))

            # 两次下一步 + 快拍开关 + 弹窗主动作，全部坐标点击，零原生 click。
            self.assertEqual(page.mouse.down_count, 4)
            self.assertEqual(next_button.click_count, 0)
            self.assertEqual(story.click_count, 0)
            self.assertEqual(dialog.get_by_role("button", name="Publish").click_count, 0)
            # 开关先读 checked 再决定点击。
            self.assertEqual(story.reads, 1)
            read_index = log.index(("is_checked", "story"))
            self.assertLess(
                read_index, log.index(("evaluate", "hit-test", "story"))
            )
            # stillOn 命中测试先于 down。
            for name in ("next", "story", "confirm"):
                marker = ("evaluate", "hit-test", name)
                self.assertIn(marker, log)
                self.assertIn(("down",), log[log.index(marker) + 1:])
            self.assertEqual(radio.checked, True)

    def test_schedule_controls_use_humanizer_clicks(self):
        with tempfile.TemporaryDirectory() as tmp:
            schedule = datetime.now(timezone.utc).replace(
                second=0, microsecond=0
            ) + timedelta(days=3)
            # 让日历停在请求月份的前/后一个月，强制走一次月份切换收窄。
            if schedule.month > 1:
                grid_month, grid_year, month_delta = schedule.month - 1, schedule.year, 1
            else:
                grid_month, grid_year, month_delta = 2, schedule.year, -1
            app = _app(
                tmp,
                video_file=Path(tmp) / "clip.mp4",
                schedule=schedule,
            )
            log: list = []
            schedule_mode = _Clickable("schedule-mode", log=log)
            date_input = _Clickable(
                "date",
                log=log,
                attributes={"placeholder": "date"},
            )
            nav = _Clickable("next-month", log=log)
            day = _Clickable("day", log=log)
            hour = _Clickable(
                "hour", log=log, attributes={"aria-valuemax": "23", "aria-valuenow": "0"}
            )
            minute = _Clickable(
                "minute", log=log, attributes={"aria-valuemax": "59", "aria-valuenow": "0"}
            )
            period = _Clickable(
                "period", log=log, attributes={"aria-valuemax": "1", "aria-valuenow": "0"}
            )
            grid = _RegexLocator(
                "grid",
                log=log,
                attributes={
                    "aria-labelledby": (
                        f"js_1-{grid_month:02d}-{grid_year:04d}"
                    )
                },
                children={CALENDAR: None, "role:button": day},
            )
            nav_key = "role:button:Next month" if month_delta > 0 else "role:button:Previous month"
            calendar = _RegexLocator(
                "calendar",
                log=log,
                children={
                    CALENDAR_BUTTONS: FakeLocator("nav-buttons", count=2),
                    nav_key: nav,
                },
            )
            grid._children[CALENDAR] = calendar
            modes_base = FakeLocator("modes", count=3)
            region = _RegexLocator(
                "region",
                log=log,
                children={
                    MODES: modes_base,
                    "role:button:Schedule": schedule_mode,
                    DATE_INPUT: date_input,
                    GRID: grid,
                    HOUR: hour,
                    MINUTE: minute,
                    PERIOD: period,
                },
            )
            modes_base._children[MODES_XPATH] = FakeLocator("modes-xpath", count=3)
            date_value = f"{schedule.year:04d}-{schedule.month:02d}-{schedule.day:02d}"
            date_input.input_value = AsyncMock(return_value=date_value)
            page = _page({REEL_REGION: region}, log=log)

            with _humanized():
                asyncio.run(app._fill_schedule(page))

            # 定时模式、日期、上一月、日、小时、分钟：全部人类化点击。
            self.assertEqual(page.mouse.down_count, 6)
            for locator in (schedule_mode, date_input, nav, day, hour, minute):
                self.assertEqual(locator.click_count, 0)
            # 打开 spinbutton 后数字键仍逐键输入。
            self.assertEqual(
                [action for action in hour.actions if action[0] == "press"],
                [("press", digit) for digit in f"{schedule.hour:02d}"] + [("press", "Tab")],
            )
            self.assertEqual(
                [action for action in minute.actions if action[0] == "press"],
                [("press", digit) for digit in f"{schedule.minute:02d}"] + [("press", "Tab")],
            )

    def test_publish_waits_before_submit_then_humanizes_click(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _app(tmp, image_files=[Path(tmp) / "a.png"])
            app.page_name = "Page"
            app.result["page_id"] = "123"
            app.publish_not_before = None
            app._publish_budget = app.start_publish_budget()
            app._publish_budget.wait_until_allowed = AsyncMock(return_value=None)

            log: list = []
            publish = _Clickable("publish", log=log)
            footer = _RegexLocator(
                "post-footer",
                log=log,
                children={
                    '[role="button"]': FakeLocator("footer-actions", count=3),
                    "role:button:Publish": publish,
                },
            )
            page = _page({POST_FOOTER: footer}, log=log)
            page.expect_response = lambda predicate, timeout=None: _ResponseContext(
                _Response(
                    {
                        "data": {
                            "xfamily_content_create": {
                                "items": [{"pending_publish_content_id": None}]
                            }
                        }
                    }
                )
            )

            with (
                _humanized(),
                patch(
                    "uploader.meta_uploader.facebook_page_uploader.posts.open_meta_post",
                    new=AsyncMock(return_value=(Mock(), "456", False)),
                ),
            ):
                asyncio.run(app._publish(page))

            self.assertEqual(page.mouse.down_count, 1)
            self.assertEqual(publish.click_count, 0)
            pause_index = log.index(("pause", BEFORE_SUBMIT))
            self.assertLess(pause_index, log.index(("down",)))
            self.assertLess(
                log.index(("evaluate", "hit-test", "publish")),
                log.index(("down",)),
            )
            self.assertEqual(app.result["status"], "published")
            self.assertEqual(app.result["content_id"], "456")


# ---------------------------------------------------------------------------
# 1b. 发布点击：可能已派发 → 结果未知，绝不二次派发
# ---------------------------------------------------------------------------


class _PublishFailingHumanizer(_QuietHumanizer):
    """真实点击后注入异常（模拟 ``mouse.down`` 之后的失败）。"""

    def __init__(self, page, *, error: BaseException, **kwargs) -> None:
        super().__init__(page, **kwargs)
        self.error = error

    async def click(self, locator, *, point=None) -> None:
        await super().click(locator, point=point)
        if getattr(locator, "name", "") == "publish":
            raise self.error


class PublishDispatchGuardTests(unittest.TestCase):
    def _maybe_error(self) -> RuntimeError:
        exc = RuntimeError("mouse up failed")
        setattr(exc, MAYBE_DISPATCHED, MAYBE_DISPATCHED_VALUE)
        return exc

    def _page(self):
        log: list = []
        publish = _Clickable("publish", log=log)
        footer = _RegexLocator(
            "post-footer",
            log=log,
            children={
                '[role="button"]': FakeLocator("footer-actions", count=3),
                "role:button:Publish": publish,
            },
        )
        return _page({POST_FOOTER: footer}, log=log), publish

    def _publish(self, page, error) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = _app(tmp, image_files=[Path(tmp) / "a.png"])
            app.page_name = "Page"
            app.result["page_id"] = "123"
            app.publish_not_before = None
            app._publish_budget = app.start_publish_budget()
            app._publish_budget.wait_until_allowed = AsyncMock(return_value=None)
            page.expect_response = lambda predicate, timeout=None: _ResponseContext(
                _Response(
                    {
                        "data": {
                            "xfamily_content_create": {
                                "items": [{"pending_publish_content_id": None}]
                            }
                        }
                    }
                )
            )
            humanizer = _PublishFailingHumanizer(page, error=error)
            with (
                patch.object(fb_main, "Humanizer", lambda p, **kw: humanizer),
                patch.object(fb_main, "expect", _expect),
            ):
                asyncio.run(app._publish(page))

    def test_publish_after_mouse_down_maps_to_unknown(self):
        page, publish = self._page()

        with self.assertRaises(PublishResultUnknownError):
            self._publish(page, self._maybe_error())

        self.assertEqual(page.mouse.down_count, 1)
        self.assertEqual(publish.click_count, 0)

    def test_pre_dispatch_publish_failure_propagates(self):
        page, publish = self._page()
        error = ElementUnusableError(
            what="点击目标",
            role="interactive",
            selector="",
            reason="covered-by:mask",
            publish_clicked=False,
        )

        with self.assertRaises(ElementUnusableError) as caught:
            self._publish(page, error)

        self.assertIs(caught.exception, error)
        self.assertEqual(publish.click_count, 0)


# ---------------------------------------------------------------------------
# 2. 字段值读回
# ---------------------------------------------------------------------------


class HumanizeFieldReadbackTests(unittest.TestCase):
    def test_existing_values_are_cleared_before_typing(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _app(
                tmp,
                title="New title",
                description="New body",
                tags=["tag"],
                video_file=Path(tmp) / "clip.mp4",
            )
            log: list = []
            title = _TypingLocator("reel-title", log=log, initial="Old title")
            editor = _TypingLocator("caption", log=log, initial="Old body")
            page = _page({REEL_TITLE: title, CAPTION_EDITOR: editor}, log=log)

            with _humanized():
                asyncio.run(app._fill_caption(page))

            self.assertEqual(title.buffer, "New title")
            self.assertEqual(editor.buffer, "New body\n\n#tag")

    def test_crlf_body_is_normalized_before_typing(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _app(
                tmp,
                title="Title",
                description="line1\r\nline2",
                tags=[],
                video_file=Path(tmp) / "clip.mp4",
            )
            log: list = []
            title = _TypingLocator("reel-title", log=log)
            editor = _TypingLocator("caption", log=log)
            page = _page({REEL_TITLE: title, CAPTION_EDITOR: editor}, log=log)

            with _humanized():
                asyncio.run(app._fill_caption(page))

            self.assertEqual(editor.buffer, "line1\nline2")
            self.assertNotIn("\r", editor.buffer)

    def test_ambiguous_reel_next_fails_before_any_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _app(tmp, video_file=Path(tmp) / "clip.mp4")
            log: list = []
            ambiguous = _Clickable("next", log=log, count=2)
            footer = _RegexLocator(
                "footer", log=log, children={"role:button:Next": ambiguous}
            )
            root = _RegexLocator(
                "root",
                log=log,
                children={REEL_STEPS: FakeLocator("steps", count=3)},
            )
            page = _page({REEL_ROOT: root, REEL_FOOTER: footer}, log=log)

            with _humanized(), self.assertRaises(ElementUnusableError) as ctx:
                asyncio.run(app._advance_reels(page))

            self.assertEqual(ctx.exception.reason, "ambiguous:2")
            self.assertEqual(page.mouse.down_count, 0)


# ---------------------------------------------------------------------------
# HUMANIZE=0 快路径
# ---------------------------------------------------------------------------


class HumanizeDisabledTests(unittest.TestCase):
    def test_text_is_one_insert_per_field_and_no_pauses(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _app(
                tmp,
                title="Title",
                description="Body",
                tags=[],
                video_file=Path(tmp) / "clip.mp4",
            )
            log: list = []
            title = _TypingLocator("reel-title", log=log, initial="Old title")
            editor = _TypingLocator("caption", log=log, initial="Old body")
            page = _page({REEL_TITLE: title, CAPTION_EDITOR: editor}, log=log)

            with _humanized(), patch.dict(os.environ, {"HUMANIZE": "0"}):
                asyncio.run(app._fill_caption(page))

            self.assertEqual(
                [action for action in page.keyboard.actions
                 if action[0] == "insert_text"],
                [("insert_text", "Title"), ("insert_text", "Body")],
            )
            self.assertEqual(app._humanizer_instance.pauses, [])
            self.assertEqual(title.buffer, "Title")
            self.assertEqual(editor.buffer, "Body")

    def test_click_uses_native_locator_click_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _app(tmp, video_file=Path(tmp) / "clip.mp4", page_name="My Page")
            log: list = []
            combo = _Clickable("combo", log=log, text="Other Page")
            option = _Clickable("option", log=log)
            page = _page(
                {
                    '[data-surface$="bizweb_create_post:left_panel"] '
                    '[role="combobox"][aria-haspopup="listbox"]': combo,
                    'img[alt="Facebook"]': FakeLocator("brand"),
                    "role:option:My Page": option,
                },
                log=log,
            )
            page.url = (
                "https://business.facebook.com/latest/composer/"
                "?asset_id=123"
            )

            with _humanized(), patch.dict(os.environ, {"HUMANIZE": "0"}):
                asyncio.run(app._select_publish_location(page))

            self.assertEqual(combo.click_count, 1)
            self.assertEqual(option.click_count, 1)
            self.assertEqual(page.mouse.down_count, 0)


# ---------------------------------------------------------------------------
# 3. 平台静态门
# ---------------------------------------------------------------------------


class HumanizeGateTests(unittest.TestCase):
    def test_facebook_page_package_passes_gates_a_to_e(self):
        package = (
            Path(__file__).resolve().parent.parent
            / "uploader"
            / "meta_uploader"
            / "facebook_page_uploader"
        )
        assert_clean(package)


if __name__ == "__main__":
    unittest.main()
