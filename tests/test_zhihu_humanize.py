# -*- coding: utf-8 -*-
"""知乎视频 / 文章 / 定时三表单的人类化接线（spec §3.15 / §6.2）。

三块，全部离线：

1. 事件序列 —— 每个改 Humanizer 的点断言原语（``press`` / ``insert_text``）、
   ``after_type`` 次数、``mouse.move* → down → up``、hit-test 先于 ``down``、
   零原生 ``locator.click()``、零 ``force``。
2. 字段值读回 —— fake 键盘把按键写回持有缓冲的 locator，断言最终值与预期
   完全相等（抓「序列对、值错」：标题守卫被清空、介绍残留旧值、CRLF 残留）。
3. 平台静态门 —— 包内跑 spec §4.2–4.5 的 A–E 门。

另外覆盖 ``HUMANIZE=0`` 快路径与「标题守卫拒绝覆盖」的停工点。选择器未
scripted 直接抛 :class:`UnscriptedSelectorError`，不用 MagicMock。
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
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from uploader.zhihu_uploader import article as zhihu_article
from uploader.zhihu_uploader import schedule as zhihu_schedule
from uploader.zhihu_uploader import video as zhihu_video
from uploader.zhihu_uploader.article import ZhihuArticle
from uploader.zhihu_uploader.video import ZhihuVideo
from tests.fakes_xhs_dom import (
    FakeLocator,
    RecordingKeyboard,
    RecordingLocator,
    RecordingMouse,
    RecordingPage,
    UnscriptedSelectorError,
)
from tests.humanize_gates import assert_clean
from uploader.publish_timeout import PublishTimeoutBudget
from utils.dom import ElementUnusableError
from utils.errors import PublishResultUnknownError
from utils.humanize import HumanizeProfile, LogNormal
from utils.humanize import MAYBE_DISPATCHED, MAYBE_DISPATCHED_VALUE

AFTER_TYPE = 5.0
BEFORE_SUBMIT = 7.0

TITLE = "知乎视频标题"
DESCRIPTION = "视频介绍正文"
CATEGORY = "教育"
VIDEO_MARK = "含 AI 生成内容"


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

FORM_ROOT = ".VideoUploadForm-item"
TITLE_TEXTAREA = "textarea"
INTRO_EDITABLE = '[contenteditable="true"][role="textbox"]'
OPTION_LIST = ".VideoUploadForm-selectList:visible"
MARK_MODAL = ".VideoUploadForm-videoTypeModal:visible"
SCHEDULE_ROOT = ".VideoUploadForm-scheduledPublish"
PICKER = ".DateTimePicker"
DATE_BUTTON = ".DatePicker-Button"
CALENDAR = ".Calendar"
MONTH_LABEL = ".Calendar-topToolDate"
NEXT_MONTH = ".Calendar-topToolButton--nextMonth"
DAY_CELL = "td.Calendar-day:not(.is-disabled):not(.is-not-this-month)"
TIME_SELECTS = ".Select-button"
ARTICLE_TITLE = 'textarea[placeholder="请输入标题（最多 100 个字）"]'
ARTICLE_BODY = 'div[contenteditable="true"][role="textbox"]'
ARTICLE_TOGGLE = "text:定时发布:exact"
ARTICLE_PANEL = "text:开启定时发布:exact"


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

    # Playwright 的收窄 API 允许 exact=...；fake 只按精确键查找。
    def get_by_role(self, role: str, name=None, exact: bool = False, **kwargs):
        return super().get_by_role(role, name)

    def get_by_text(self, text: str, exact: bool = False, **kwargs):
        return super().get_by_text(text, exact=exact)

    async def evaluate(self, expression, arg=None):
        self.evaluate_calls.append((expression, arg))
        kind = _expr_kind(expression)
        self._log.append(("evaluate", kind, self.name))
        if kind == "hit-test":
            page = getattr(self, "_page", None)
            if page is not None:
                page.hit_target = self
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
            "contentEditable": "true",
        }

    async def evaluate_all(self, expression, arg=None):
        self.evaluate_calls.append((expression, arg))
        return []

    async def scroll_into_view_if_needed(self, **kwargs) -> None:
        self.actions.append(("scroll",))


class _Checkbox(_Clickable):
    def __init__(self, name: str, *, log: list, checked: bool = False, **kwargs):
        super().__init__(name, log=log, **kwargs)
        self.checked = checked
        self.reads = 0

    async def is_checked(self) -> bool:
        self.reads += 1
        self._log.append(("is_checked", self.name))
        return self.checked

    async def click(self, **kwargs) -> None:
        await super().click(**kwargs)
        self.checked = not self.checked

    async def check(self, **kwargs) -> None:
        self.actions.append(("check",))
        self.checked = True


class _TypingLocator(_Clickable):
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

    async def click(self, **kwargs) -> None:
        await super().click(**kwargs)
        await self.focus()

    async def inner_text(self) -> str:
        return self.buffer

    async def input_value(self) -> str:
        return self.buffer

    async def bounding_box(self):
        # 坐标点击前必然会测量盒模型；落点就在输入框内，因此焦点随之转移。
        if self._page is not None:
            self._page.focused = self
            self._page.selected = False
        return await super().bounding_box()

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
        elif key == "Tab":
            self.buffer += "\t"
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


class _OrderedMouse(RecordingMouse):
    def __init__(self, log: list, page: "_Page | None" = None) -> None:
        super().__init__()
        self._log = log
        self._page = page

    async def move(self, x: float, y: float, **kwargs) -> None:
        self.actions.append(("move", x, y))
        self._log.append(("move", x, y))

    async def down(self, **kwargs) -> None:
        self.actions.append(("down",))
        self.down_count += 1
        self._log.append(("down",))
        target = getattr(self._page, "hit_target", None)
        if isinstance(target, _Checkbox):
            target.checked = not target.checked

    async def up(self, **kwargs) -> None:
        self.actions.append(("up",))
        self.up_count += 1
        self._log.append(("up",))


class _TypingKeyboard(RecordingKeyboard):
    def __init__(self, page: "_Page") -> None:
        super().__init__()
        self._page = page

    async def press(self, key: str, **kwargs) -> None:
        self.actions.append(("press", key))
        self._page.apply_key(key)

    async def insert_text(self, text: str, **kwargs) -> None:
        self.actions.append(("insert_text", text))
        self._page.apply_text(text)


class _Page(RecordingPage):
    """带确定顺序日志、focus 键盘和 exact 参数的 page double。"""

    def __init__(self, *, log: list, **kwargs) -> None:
        self.interactions = log
        super().__init__(**kwargs)
        self.mouse = _OrderedMouse(log, self)
        self.keyboard = _TypingKeyboard(self)
        self.focused = None
        self.selected = False
        self.hit_target = None

    def get_by_role(self, role: str, name=None, exact: bool = False, **kwargs):
        return super().get_by_role(role, name)

    def apply_key(self, key: str) -> None:
        if self.focused is not None:
            self.focused.apply_key(key)

    def apply_text(self, text: str) -> None:
        if self.focused is not None:
            self.focused.apply_text(text)


def _attach(page: _Page, locator: FakeLocator) -> None:
    if isinstance(locator, (_TypingLocator, _Checkbox, _Clickable)):
        locator._page = page
    for item in getattr(locator, "_items", None) or []:
        _attach(page, item)
    for child in locator._children.values():
        _attach(page, child)


def _page(selectors: dict[str, FakeLocator], *, log: list | None = None, **kwargs) -> _Page:
    log = [] if log is None else log
    page = _Page(log=log, selectors=selectors, **kwargs)
    for locator in selectors.values():
        _attach(page, locator)
    return page


class _QuietHumanizer(zhihu_video.Humanizer):
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
    """顺序记录用 expectation double；断言本身由 fake 的调用日志承担。"""

    def __init__(self, actual) -> None:
        self.actual = actual
        self.calls: list[str] = []

    @property
    def not_(self) -> "_Expect":
        return self

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
        patch.object(zhihu_video, "Humanizer", _QuietHumanizer),
        patch.object(zhihu_article, "Humanizer", _QuietHumanizer),
        patch.object(zhihu_video, "expect", _expect),
        patch.object(zhihu_article, "expect", _expect),
        patch.object(zhihu_schedule, "expect", _expect),
    ):
        yield


def _video(tmp: str, **overrides) -> ZhihuVideo:
    values = {
        "title": TITLE,
        "file_path": Path(tmp) / "clip.mp4",
        "account_file": Path(tmp) / "account.json",
        "description": DESCRIPTION,
        "category": CATEGORY,
        "topics": [],
        "video_mark": VIDEO_MARK,
        "originality": "original",
    }
    values.update(overrides)
    return ZhihuVideo(
        values["title"],
        values["file_path"],
        values["account_file"],
        values["description"],
        values["category"],
        values["topics"],
        values["video_mark"],
        values["originality"],
        schedule=values.get("schedule"),
    )


def _article(tmp: str, **overrides) -> ZhihuArticle:
    values = {"title": "知乎文章标题", "content_file": Path(tmp) / "body.md"}
    values.update(overrides)
    app = ZhihuArticle(
        values["title"], values["content_file"], Path(tmp) / "account.json"
    )
    app.document = SimpleNamespace(parts=["正文"], images=[])
    app.check_article_body = AsyncMock()
    return app


def _schedule_target() -> datetime:
    """30 分钟–48 小时窗口内的整分绝对时刻；浏览器时区固定 UTC。"""
    return (datetime.now(timezone.utc) + timedelta(hours=2)).replace(
        second=0, microsecond=0
    )


class _Grant:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def grant_permissions(self, permissions, origin=None) -> None:
        self.calls.append((tuple(permissions), origin))


def _video_form_page(log: list, **overrides):
    """视频表单：标题/介绍 + 所属领域 + 视频标记 + 原创 checkbox。"""
    title = _TypingLocator(
        "video-title", log=log, initial=overrides.get("title_initial", "")
    )
    description = _TypingLocator(
        "video-intro", log=log, initial=overrides.get("intro_initial", "")
    )
    control = _Clickable("domain-control", log=log)
    option = _Clickable("domain-option", log=log)
    mark_button = _Clickable("mark-button", log=log)
    mark_option = _Clickable("mark-option", log=log)
    confirm = _Clickable("mark-confirm", log=log)
    originality = _Checkbox(
        "originality", log=log, checked=overrides.get("originality_checked", False)
    )
    form = _Clickable(
        "video-form",
        log=log,
        children={
            TITLE_TEXTAREA: title,
            INTRO_EDITABLE: description,
            "role:combobox": control,
            "role:button:选择视频标记": mark_button,
            "role:checkbox": originality,
        },
    )
    option_list = _Clickable(
        "domain-list", log=log, children={f"role:option:{CATEGORY}": option}
    )
    modal = _Clickable(
        "mark-modal",
        log=log,
        children={
            f"role:button:{VIDEO_MARK}": mark_option,
            "role:button:确认": confirm,
        },
    )
    page = _page(
        {
            FORM_ROOT: form,
            "text:标题与介绍:exact": FakeLocator("form-label"),
            "text:所属领域:exact": FakeLocator("domain-label"),
            "text:视频标记:exact": FakeLocator("mark-label"),
            "text:原创视频:exact": FakeLocator("originality-label"),
            "text:视频上传失败:exact": FakeLocator("upload-failure", count=0),
            "text:上传成功:exact": FakeLocator("upload-success"),
            OPTION_LIST: option_list,
            MARK_MODAL: modal,
        },
        log=log,
    )
    return page, {
        "title": title,
        "description": description,
        "control": control,
        "option": option,
        "mark_button": mark_button,
        "mark_option": mark_option,
        "confirm": confirm,
        "originality": originality,
    }


# ---------------------------------------------------------------------------
# 1. 事件序列
# ---------------------------------------------------------------------------


class HumanizeEventSequenceTests(unittest.TestCase):
    def test_video_form_types_titles_and_humanizes_every_widget(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _video(tmp, description="视频介绍\r\n第二行")
            log: list = []
            page, parts = _video_form_page(
                log, title_initial="旧标题", intro_initial="旧介绍"
            )

            with _humanized():
                asyncio.run(app.fill_video_form(page))

            # 标题与介绍各自 sel 清空后逐字输入；CRLF 已归一。
            self.assertEqual(
                page.keyboard.actions,
                [
                    ("press", "ControlOrMeta+A"),
                    ("press", "Delete"),
                    *[("insert_text", char) for char in TITLE],
                    ("press", "ControlOrMeta+A"),
                    ("press", "Delete"),
                    ("insert_text", "视"),
                    ("insert_text", "频"),
                    ("insert_text", "介"),
                    ("insert_text", "绍"),
                    ("press", "Enter"),
                    ("insert_text", "第"),
                    ("insert_text", "二"),
                    ("insert_text", "行"),
                ],
            )
            self.assertEqual(parts["title"].buffer, TITLE)
            self.assertEqual(parts["description"].buffer, "视频介绍\n第二行")
            self.assertEqual(app._humanizer_instance.pauses.count(AFTER_TYPE), 2)
            # 领域下拉/选项、标记按钮/选项/确认、原创 checkbox，加两个输入框的聚焦点击。
            self.assertEqual(page.mouse.down_count, 8)
            for name in ("domain-control", "domain-option", "mark-button",
                         "mark-option", "mark-confirm", "originality"):
                self.assertIn(("evaluate", "hit-test", name), log)
            # 原创 checkbox 先读状态。
            self.assertEqual(parts["originality"].reads, 1)
            self.assertEqual(parts["originality"].checked, True)

    def test_video_intro_over_horizon_is_one_bulk_insert_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = "字" * 1001
            app = _video(tmp, description=body)
            log: list = []
            page, parts = _video_form_page(log)

            with _humanized():
                asyncio.run(app.fill_video_form(page))

            inserts = [
                action for action in page.keyboard.actions
                if action[0] == "insert_text" and len(action[1]) > 1
            ]
            self.assertEqual(inserts, [("insert_text", body)])
            self.assertEqual(parts["description"].buffer, body)
            self.assertEqual(app._humanizer_instance.pauses.count(AFTER_TYPE), 2)

    def test_originality_checkbox_is_idempotent_when_already_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _video(tmp, originality="original")
            log: list = []
            page, parts = _video_form_page(log, originality_checked=True)

            with _humanized():
                asyncio.run(app.fill_video_form(page))

            self.assertEqual(parts["originality"].reads, 1)
            self.assertEqual(parts["originality"].checked, True)
            self.assertEqual(parts["originality"].click_count, 0)
            # 只剩领域与标记的 5 次点击 + 两个输入框聚焦。
            self.assertEqual(page.mouse.down_count, 7)

    def test_article_form_keeps_title_guard_and_focus_clicks_native(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _article(tmp, title="知乎文章标题")
            log: list = []
            title = _TypingLocator("article-title", log=log)
            body = _TypingLocator("article-body", log=log)
            body._children["img"] = _Clickable("body-images", log=log, count=0)
            page = _page(
                {ARTICLE_TITLE: title, ARTICLE_BODY: body},
                log=log,
                evaluate_handler=lambda expression, arg: None,
            )
            page.context = _Grant()

            with _humanized():
                asyncio.run(app.fill_article_form(page))

            # 标题只聚焦后逐字输入，零清空键（平台自带非空即拒绝守卫）。
            self.assertEqual(
                page.keyboard.actions,
                [("insert_text", char) for char in "知乎文章标题"],
            )
            self.assertEqual(title.buffer, "知乎文章标题")
            # 正文聚焦是坐标点击；失焦标题的两次点击保持原生。
            self.assertEqual(page.mouse.down_count, 2)
            self.assertEqual(body.click_count, 0)
            self.assertEqual(title.click_count, 2)
            self.assertEqual(page.context.calls[0][0], ("clipboard-read", "clipboard-write"))

    def test_article_publish_waits_before_submit_then_humanizes_click(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _article(tmp)
            log: list = []
            publish = _Clickable("article-publish", log=log)
            page = _page({"role:button:发布": publish}, log=log)

            with _humanized():
                asyncio.run(app._submit(page, publish))

            self.assertEqual(page.mouse.down_count, 1)
            self.assertEqual(publish.click_count, 0)
            self.assertLess(
                log.index(("pause", BEFORE_SUBMIT)), log.index(("down",))
            )
            self.assertLess(
                log.index(("evaluate", "hit-test", "article-publish")),
                log.index(("down",)),
            )

    def test_video_publish_waits_before_submit_then_humanizes_click(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _video(tmp)
            log: list = []
            publish = _Clickable("video-publish", log=log)
            page = _page({"role:button:发布视频": publish}, log=log)

            with _humanized():
                asyncio.run(app._submit(page, publish))

            self.assertEqual(page.mouse.down_count, 1)
            self.assertEqual(publish.click_count, 0)
            self.assertLess(
                log.index(("pause", BEFORE_SUBMIT)), log.index(("down",))
            )
            self.assertLess(
                log.index(("evaluate", "hit-test", "video-publish")),
                log.index(("down",)),
            )

    def test_article_schedule_uses_humanizer_for_all_nine_points(self):
        target = _schedule_target()
        wall = target.astimezone(timezone.utc)
        log: list = []
        toggle = _Clickable("schedule-toggle", log=log)
        panel = FakeLocator("schedule-panel")
        date_button = _Clickable(
            "date-button", log=log, text="2020-01-01"
        )
        month_label = FakeLocator("month-label", text="2019 年 1 月")
        next_month = _Clickable("next-month", log=log)
        day = _Clickable("calendar-day", log=log)
        calendar = _Clickable(
            "calendar",
            log=log,
            children={
                MONTH_LABEL: month_label,
                NEXT_MONTH: next_month,
                DAY_CELL: day,
            },
        )
        hour_select = _Clickable("hour-select", log=log)
        minute_select = _Clickable("minute-select", log=log)
        selects = FakeLocator(
            "time-selects", items=[hour_select, minute_select]
        )
        picker = _Clickable(
            "picker",
            log=log,
            children={
                TIME_SELECTS: selects,
                DATE_BUTTON: date_button,
            },
        )
        hour_option = _Clickable("hour-option", log=log)
        minute_option = _Clickable("minute-option", log=log)
        confirm = _Clickable("schedule-confirm", log=log)
        page = _page(
            {
                ARTICLE_TOGGLE: toggle,
                ARTICLE_PANEL: panel,
                PICKER: picker,
                DATE_BUTTON: date_button,
                CALENDAR: calendar,
                f"role:option:{wall.hour:02d}": hour_option,
                f"role:option:{wall.minute:02d}": minute_option,
                "role:button:确认": confirm,
            },
            log=log,
        )
        humanizer = _QuietHumanizer(page)

        with _humanized():
            asyncio.run(
                zhihu_schedule.fill_zhihu_article_schedule(page, target, humanizer)
            )

        # 定时开关、日期面板、下月、日、时下拉/选项、分下拉/选项、确认。
        self.assertEqual(page.mouse.down_count, 9)
        for locator in (
            toggle, date_button, next_month, day, hour_select, hour_option,
            minute_select, minute_option, confirm,
        ):
            self.assertEqual(locator.click_count, 0)
        self.assertEqual(hour_option.actions, [])
        self.assertIn(("evaluate", "hit-test", "schedule-confirm"), log)

    def test_video_schedule_reads_toggle_then_humanizes_eight_points(self):
        target = _schedule_target()
        wall = target.astimezone(timezone.utc)
        log: list = []
        toggle = _Checkbox("schedule-toggle", log=log, checked=False)
        date_button = _Clickable("date-button", log=log, text="2020-01-01")
        month_label = FakeLocator("month-label", text="2019 年 1 月")
        next_month = _Clickable("next-month", log=log)
        day = _Clickable("calendar-day", log=log)
        calendar = _Clickable(
            "calendar",
            log=log,
            children={
                MONTH_LABEL: month_label,
                NEXT_MONTH: next_month,
                DAY_CELL: day,
            },
        )
        hour_select = _Clickable("hour-select", log=log)
        minute_select = _Clickable("minute-select", log=log)
        selects = FakeLocator(
            "time-selects", items=[hour_select, minute_select]
        )
        picker = _Clickable(
            "picker",
            log=log,
            children={TIME_SELECTS: selects, DATE_BUTTON: date_button},
        )
        schedule_root = _Clickable(
            "schedule-root",
            log=log,
            children={
                'input[type="checkbox"]': toggle,
                PICKER: picker,
            },
        )
        hour_option = _Clickable("hour-option", log=log)
        minute_option = _Clickable("minute-option", log=log)
        page = _page(
            {
                SCHEDULE_ROOT: schedule_root,
                CALENDAR: calendar,
                f"role:option:{wall.hour:02d}": hour_option,
                f"role:option:{wall.minute:02d}": minute_option,
            },
            log=log,
        )
        humanizer = _QuietHumanizer(page)

        with _humanized():
            asyncio.run(
                zhihu_schedule.fill_zhihu_video_schedule(page, target, humanizer)
            )

        # 定时开关（先读状态）、日期面板、下月、日、时下拉/选项、分下拉/选项。
        self.assertEqual(toggle.reads, 1)
        self.assertEqual(toggle.checked, True)
        self.assertEqual(page.mouse.down_count, 8)
        for locator in (
            toggle, date_button, next_month, day, hour_select, hour_option,
            minute_select, minute_option,
        ):
            self.assertEqual(locator.click_count, 0)



# ---------------------------------------------------------------------------
# 1b. 发布点击：可能已派发 → 结果未知，绝不二次派发
# ---------------------------------------------------------------------------


class _PublishFailingHumanizer(_QuietHumanizer):
    """真实点击后注入异常（模拟 ``mouse.down`` 之后的失败）。"""

    def __init__(self, page, *, error: BaseException) -> None:
        super().__init__(page)
        self.error = error
        self.dispatches: list[str] = []

    async def click(self, locator, *, point=None) -> None:
        await super().click(locator, point=point)
        self.dispatches.append(getattr(locator, "name", "?"))
        raise self.error


class PublishDispatchGuardTests(unittest.TestCase):
    def _maybe_error(self) -> RuntimeError:
        exc = RuntimeError("mouse up failed")
        setattr(exc, MAYBE_DISPATCHED, MAYBE_DISPATCHED_VALUE)
        return exc

    def _pre_dispatch_error(self) -> ElementUnusableError:
        return ElementUnusableError(
            what="点击目标",
            role="interactive",
            selector="",
            reason="covered-by:mask",
            publish_clicked=False,
        )

    def _run_submit(self, module, app, page, publish, error) -> None:
        humanizer = _PublishFailingHumanizer(page, error=error)
        app._publish_budget = PublishTimeoutBudget("知乎")
        with patch.object(module, "Humanizer", lambda p, **kw: humanizer):
            asyncio.run(app._submit(page, publish))

    def test_video_publish_after_mouse_down_maps_to_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            log: list = []
            publish = _Clickable("video-publish", log=log)
            page = _page({"role:button:发布视频": publish}, log=log)

            with self.assertRaises(PublishResultUnknownError):
                self._run_submit(
                    zhihu_video, _video(tmp), page, publish, self._maybe_error()
                )

            # 只派发一次；原生 click 零次。
            self.assertEqual(page.mouse.down_count, 1)
            self.assertEqual(publish.click_count, 0)

    def test_video_pre_dispatch_failure_propagates(self):
        with tempfile.TemporaryDirectory() as tmp:
            publish = _Clickable("video-publish", log=[])
            page = _page({}, log=[])
            error = self._pre_dispatch_error()

            with self.assertRaises(ElementUnusableError) as caught:
                self._run_submit(zhihu_video, _video(tmp), page, publish, error)

            self.assertIs(caught.exception, error)

    def test_article_publish_after_mouse_down_maps_to_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            log: list = []
            publish = _Clickable("article-publish", log=log)
            page = _page({"role:button:发布": publish}, log=log)

            with self.assertRaises(PublishResultUnknownError):
                self._run_submit(
                    zhihu_article, _article(tmp), page, publish, self._maybe_error()
                )

            self.assertEqual(page.mouse.down_count, 1)
            self.assertEqual(publish.click_count, 0)

    def test_article_pre_dispatch_failure_propagates(self):
        with tempfile.TemporaryDirectory() as tmp:
            publish = _Clickable("article-publish", log=[])
            page = _page({}, log=[])
            error = self._pre_dispatch_error()

            with self.assertRaises(ElementUnusableError) as caught:
                self._run_submit(
                    zhihu_article, _article(tmp), page, publish, error
                )

            self.assertIs(caught.exception, error)


# ---------------------------------------------------------------------------
# 2. 字段值读回
# ---------------------------------------------------------------------------


class HumanizeFieldReadbackTests(unittest.TestCase):
    def test_video_title_and_intro_replace_prefilled_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _video(tmp, title="新标题", description="新介绍")
            log: list = []
            page, parts = _video_form_page(
                log, title_initial="旧标题", intro_initial="旧介绍"
            )

            with _humanized():
                asyncio.run(app.fill_video_form(page))

            self.assertEqual(parts["title"].buffer, "新标题")
            self.assertEqual(parts["description"].buffer, "新介绍")

    def test_article_title_guard_refuses_to_overwrite_an_existing_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _article(tmp, title="新标题")
            log: list = []
            title = _TypingLocator("article-title", log=log, initial="已有草稿")
            body = _TypingLocator("article-body", log=log)
            page = _page(
                {ARTICLE_TITLE: title, ARTICLE_BODY: body},
                log=log,
                evaluate_handler=lambda expression, arg: None,
            )
            page.context = _Grant()

            with _humanized(), self.assertRaisesRegex(RuntimeError, "已有草稿内容"):
                asyncio.run(app.fill_article_form(page))

            # 守卫在输入前停工：既不清空也不追加。
            self.assertEqual(page.keyboard.actions, [])
            self.assertEqual(page.mouse.down_count, 0)
            self.assertEqual(title.buffer, "已有草稿")


# ---------------------------------------------------------------------------
# HUMANIZE=0 快路径
# ---------------------------------------------------------------------------


class HumanizeDisabledTests(unittest.TestCase):
    def test_video_form_inserts_once_per_field_and_clicks_natively(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _video(tmp, title="新标题", description="新介绍")
            log: list = []
            page, parts = _video_form_page(
                log, title_initial="旧标题", intro_initial="旧介绍"
            )

            with _humanized(), patch.dict(os.environ, {"HUMANIZE": "0"}):
                asyncio.run(app.fill_video_form(page))

            # 清空键保留（共享层 press 不因快路径消失），输入与点击切回原生。
            self.assertEqual(
                page.keyboard.actions,
                [
                    ("press", "ControlOrMeta+A"),
                    ("press", "Delete"),
                    ("insert_text", "新标题"),
                    ("press", "ControlOrMeta+A"),
                    ("press", "Delete"),
                    ("insert_text", "新介绍"),
                ],
            )
            self.assertEqual(app._humanizer_instance.pauses, [])
            self.assertEqual(page.mouse.down_count, 0)
            for name in ("control", "option", "mark_button", "mark_option",
                         "confirm", "originality"):
                self.assertEqual(parts[name].click_count, 1)
            self.assertEqual(parts["title"].buffer, "新标题")
            self.assertEqual(parts["description"].buffer, "新介绍")


# ---------------------------------------------------------------------------
# 3. 平台静态门
# ---------------------------------------------------------------------------


class HumanizeGateTests(unittest.TestCase):
    def test_zhihu_package_passes_gates_a_to_e(self):
        package = (
            Path(__file__).resolve().parent.parent
            / "uploader"
            / "zhihu_uploader"
        )
        assert_clean(package)


if __name__ == "__main__":
    unittest.main()
