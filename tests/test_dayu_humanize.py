# -*- coding: utf-8 -*-
"""大鱼号人类化接线（spec §3.3 / §6.2）。

三块，全部离线：

1. 事件序列 —— 视频标题 / 简介 / 标签 / 原文链接走 ``press`` 或
   ``insert_text``，每个标签恰一次 ``after_type``；分类、标签组件与封面保存
   走坐标点击（``stillOn`` 先于 ``down``），零原生 ``locator.click()``。
   图文正文在 iframe 内：``Humanizer`` 收到 frame 内 ``Locator``，正文粘贴
   仍是原生按键。
2. 字段值读回 —— fake 键盘把按键写回持有缓冲的 locator：标题预填被整体替换，
   ``#author`` 缺省不被抹、显式传入时被覆盖。
3. 平台静态门 —— 包内跑 spec §4.2–4.5 的 A–E 门；另覆盖 ``HUMANIZE=0``。
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from uploader.dayu_uploader import article as dayu_article
from uploader.dayu_uploader import interaction as dayu_interaction
from uploader.dayu_uploader import main as dayu_main
from uploader.dayu_uploader import schedule as dayu_schedule
from tests.fakes_xhs_dom import (
    FakeLocator,
    RecordingKeyboard,
    RecordingLocator,
    RecordingMouse,
    RecordingPage,
    UnscriptedEvaluationError,
    UnscriptedSelectorError,
)
from tests.humanize_gates import assert_clean
from utils.humanize import HumanizeProfile, LogNormal

AFTER_TYPE = 5.0
BEFORE_SUBMIT = 7.0


def _fixed(seconds: float) -> LogNormal:
    return LogNormal(0.0, 0.0, seconds, seconds)


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

TITLE = '[contenteditable="true"][placeholder="视频标题最少5个字"]'
DESC_FIELD = ".w-form-field"
DESC = "textarea"
CATEGORY_CONTAINER = ".widgets-selects_container"
CATEGORY_OPTION = "role:link:科技"
TAGS = ".article-write_video-tags"
TAG_SLOT = "input"
COVER_INPUT = "#coverImg input[type=file]"
COVER_DIALOG = ".article-material-image-dialog:visible"
COVER_SAVE = "role:button:保存"
COVER_IMG = "#coverImg #form_main_cover_img"
VIDEO_SOURCE = 'input[type=radio][value="转载"]'
VIDEO_LINK_FIELD = ".source-remark-detail .article-write_box-form-filed"
VIDEO_LINK = 'input[type="text"]'

ARTICLE_BODY = ".article-write_box-editor .edui-editor-iframeholder iframe"
ARTICLE_TITLE = "#title"
AUTHOR = "#author input"
ARTICLE_SOURCE = '.article-write-source-remark input[value="无需标注"]'
ARTICLE_LINK_FIELD = ".article-write_box-form-filed"
ARTICLE_LINK = 'input[type="text"]'
SCHEDULE_OPTION = ".article-write_radio:visible"
SCHEDULE_TOGGLE = ":scope > .w-radio"
SCHEDULE_WIDGET = ".widgets-datepicker-m:visible"
DIVIDER = '.edui-toolbar [datatitle="分隔线"]'


def _expr_kind(expression) -> str:
    if not isinstance(expression, str):
        return "unknown"
    if "createTreeWalker" in expression:
        return "select"
    if "naturalWidth" in expression:
        return "natural"
    if "elementFromPoint" in expression and "childFrame" not in expression:
        return "hit-test"
    if "childFrame" in expression:
        return "geometry"
    if "getComputedStyle" in expression:
        return "facts"
    return "unknown"


class _Clickable(RecordingLocator):
    """可被 ``Humanizer.click`` 坐标点击的 fake：盒模型 + 事实探测 + 命中测试。"""

    def __init__(self, name: str, *, log: list, child_frame: bool = False, **kwargs) -> None:
        kwargs.setdefault("box", {"x": 10.0, "y": 20.0, "width": 60.0, "height": 24.0})
        super().__init__(name, **kwargs)
        self._log = log
        self._child_frame = child_frame

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
                "childFrame": self._child_frame,
            }
        if kind == "facts":
            return {
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
        if kind in ("select", "natural"):
            return None
        raise UnscriptedEvaluationError(
            f"{self.name}: un-scripted locator.evaluate({expression!r})"
        )

    async def scroll_into_view_if_needed(self, **kwargs) -> None:
        self.actions.append(("scroll",))

    def get_by_role(self, role: str, name=None, exact: bool = False, **kwargs):
        return super().get_by_role(role, name)


class _FrameBody(_Clickable):
    """iframe 内正文：坐标点击仍用主 page 鼠标；粘贴按键记录在 body 上。"""

    def __init__(self, name: str, *, log: list, **kwargs) -> None:
        super().__init__(name, log=log, child_frame=True, **kwargs)
        self.pressed: list[tuple] = []

    async def press(self, key: str, **kwargs) -> None:
        self.pressed.append(("press", key))

    async def dispatch_event(self, event: str, **kwargs) -> None:
        self.actions.append(("dispatch_event", event))

    async def inner_html(self) -> str:
        return "<p>正文</p>"


class _TypingLocator(_Clickable):
    """持有键入缓冲的 locator；键盘事件写回当前 focus 的实例。"""

    def __init__(self, name: str, *, log: list, initial: str = "", **kwargs) -> None:
        super().__init__(name, log=log, **kwargs)
        self.buffer = initial
        self._page = None

    async def focus(self, **kwargs) -> None:
        self.actions.append(("focus",))
        if self._page is not None:
            self._page.focused = self
            self._page.selected = False

    async def click(self, **kwargs) -> None:
        self.click_count += 1
        self.click_calls.append(dict(kwargs))
        self.actions.append(("click",))
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
            # 标签槽是单行输入，Enter 只提交新槽，不写入正文。
            page.selected = False
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


class _Radio(FakeLocator):
    """来源 radio：保留平台既有的 focus + Space / check 路径。"""

    def __init__(self, name: str, **kwargs) -> None:
        super().__init__(name, **kwargs)
        self.checked = False

    async def focus(self, **kwargs) -> None:
        self.actions.append(("focus",))

    async def press(self, key: str, **kwargs) -> None:
        self.actions.append(("press", key))
        if key == "Space":
            self.checked = True

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
    def __init__(self, page: "_DayuPage") -> None:
        super().__init__()
        self._page = page

    async def press(self, key: str, **kwargs) -> None:
        self.actions.append(("press", key))
        self._page.apply_key(key)

    async def insert_text(self, text: str, **kwargs) -> None:
        self.actions.append(("insert_text", text))
        self._page.apply_text(text)

    async def type(self, text: str, delay: float | None = None, **kwargs) -> None:
        self.actions.append(("type", text, delay))
        self._page.apply_text(text)


class _FrameLocator:
    def __init__(self, name: str, body: FakeLocator) -> None:
        self.name = name
        self._body = body

    def locator(self, selector: str) -> FakeLocator:
        if selector == "body[contenteditable=true]":
            return self._body
        raise UnscriptedSelectorError(f"{self.name}: un-scripted frame child {selector!r}")


class _DayuPage(RecordingPage):
    """带 iframe、focus 键盘与确定顺序日志的 page double。"""

    def __init__(self, *, log: list, frame_body: FakeLocator | None = None, **kwargs) -> None:
        self.interactions = log
        kwargs.setdefault("evaluate_handler", self._evaluate)
        super().__init__(**kwargs)
        self.mouse = _OrderedMouse(log)
        self.keyboard = _TypingKeyboard(self)
        self.context = SimpleNamespace(grant_permissions=AsyncMock(return_value=None))
        self._frame_body = frame_body
        self.focused = None
        self.selected = False

    async def _evaluate(self, expression, arg=None):
        if isinstance(expression, str) and "elementFromPoint" in expression:
            return True
        if isinstance(expression, str) and "clipboard" in expression:
            return None
        raise UnscriptedEvaluationError(
            f"page: un-scripted page.evaluate({expression!r})"
        )

    def frame_locator(self, selector: str) -> _FrameLocator:
        if selector == ARTICLE_BODY and self._frame_body is not None:
            return _FrameLocator(selector, self._frame_body)
        raise UnscriptedSelectorError(f"page: un-scripted frame_locator({selector!r})")

    def apply_key(self, key: str) -> None:
        if self.focused is not None:
            self.focused.apply_key(key)

    def apply_text(self, text: str) -> None:
        if self.focused is not None:
            self.focused.apply_text(text)


def _attach(page: _DayuPage, locator: FakeLocator) -> None:
    if isinstance(locator, _TypingLocator):
        locator._page = page
    for child in locator._children.values():
        _attach(page, child)
    for item in locator._items or []:
        _attach(page, item)


def _page(
    selectors: dict[str, FakeLocator],
    *,
    log: list | None = None,
    frame_body: FakeLocator | None = None,
) -> _DayuPage:
    log = [] if log is None else log
    page = _DayuPage(log=log, selectors=selectors, frame_body=frame_body)
    for locator in selectors.values():
        _attach(page, locator)
    if frame_body is not None:
        _attach(page, frame_body)
    return page


class _QuietHumanizer(dayu_interaction.Humanizer):
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
    """顺序记录用 expectation double；值读回由 locator 缓冲负责。"""

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
        patch.object(dayu_interaction, "Humanizer", _QuietHumanizer),
        patch.object(dayu_main, "expect", _expect),
        patch.object(dayu_article, "expect", _expect),
        patch.object(dayu_schedule, "expect", _expect),
    ):
        yield


def _video_app(tmp: str, **overrides) -> dayu_main.DayuVideo:
    values = {
        "title": "Hi标题",
        "file_path": Path(tmp) / "clip.mp4",
        "tags": ["旅行", "美食"],
        "account_file": Path(tmp) / "account.json",
        "thumbnail_path": Path(tmp) / "cover.png",
        "category": "科技",
        "source": "转载",
        "source_url": "https://example.com/a",
        "desc": "Body",
    }
    values.update(overrides)
    return dayu_main.DayuVideo(**values)


def _schedule_selectors(log: list) -> dict[str, FakeLocator]:
    toggle = _Clickable("schedule-toggle", log=log, attributes={"class": ""})
    option = _Clickable(
        "schedule-option",
        log=log,
        children={SCHEDULE_TOGGLE: toggle},
    )
    return {
        SCHEDULE_OPTION: option,
        SCHEDULE_WIDGET: FakeLocator("schedule-widget", count=0),
    }


def _video_selectors(log: list, title_initial: str = "Old video title"):
    title = _TypingLocator("video-title", log=log, initial=title_initial)
    description = _TypingLocator("video-desc", log=log, initial="Old body")
    category_container = _Clickable("category-container", log=log)
    category_option = _Clickable("category-option", log=log)
    tags = _Clickable(
        "tags",
        log=log,
        children={
            TAG_SLOT: FakeLocator(
                "tag-inputs",
                items=[
                    _TypingLocator("tag-0", log=log),
                    _TypingLocator("tag-1", log=log),
                ],
            )
        },
    )
    save = _Clickable("cover-save", log=log)
    link = _TypingLocator("source-link", log=log)
    field = _Clickable(
        "video-form-field",
        log=log,
        children={
            DESC: description,
            CATEGORY_CONTAINER: category_container,
            "role:link:科技": category_option,
            VIDEO_LINK: link,
        },
    )
    dialog = _Clickable(
        "cover-dialog",
        log=log,
        children={COVER_SAVE: save},
    )
    link_field = _Clickable("link-field", log=log, children={VIDEO_LINK: link})
    selectors = {
        TITLE: title,
        DESC_FIELD: field,
        "textarea": FakeLocator("has-textarea"),
        "label": FakeLocator("has-label"),
        TAGS: tags,
        COVER_INPUT: FakeLocator("cover-input"),
        COVER_DIALOG: dialog,
        COVER_IMG: FakeLocator("cover-img", attributes={"src": "https://image.uc.cn/a.png"}),
        VIDEO_SOURCE: _Radio("video-source"),
        VIDEO_LINK_FIELD: link_field,
    }
    selectors.update(_schedule_selectors(log))
    return selectors, title, description, tags, category_container, category_option, save, link


# ---------------------------------------------------------------------------
# 1. 事件序列
# ---------------------------------------------------------------------------


class HumanizeEventSequenceTests(unittest.TestCase):
    def test_video_form_types_then_humanizes_category_tags_and_cover(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _video_app(tmp)
            log: list = []
            (
                selectors,
                title,
                description,
                tags,
                category,
                option,
                save,
                link,
            ) = _video_selectors(log)
            page = _page(selectors, log=log)

            with _humanized():
                asyncio.run(app.fill_video_form(page))

            humanizer = app._humanizer_instance
            self.assertEqual(title.buffer, "Hi标题")
            self.assertEqual(description.buffer, "Body")
            self.assertEqual(
                [slot.buffer for slot in tags.locator(TAG_SLOT)._items],
                ["旅行", "美食"],
            )
            self.assertEqual(link.buffer, "https://example.com/a")
            # 标题、简介、两个标签、原文链接：每个字段恰一次 after_type。
            self.assertEqual(humanizer.pauses.count(AFTER_TYPE), 5)
            # 分类下拉 + 选项 + 标签组件 + 封面保存：四次人类化点击。
            self.assertEqual(page.mouse.down_count, 4)
            for locator in (category, option, tags, save):
                self.assertEqual(locator.click_count, 0)
            # 失焦标签组件仍是登记的 native focus 点击。
            self.assertEqual(title.click_count, 1)
            # 标题含 ASCII 与非 ASCII：press 与 insert_text 都必须出现。
            self.assertIn(("press", "H"), page.keyboard.actions)
            self.assertIn(("insert_text", "标"), page.keyboard.actions)
            # stillOn 命中测试先于对应 down。
            log_index = log.index(("down",))
            self.assertLess(log.index(("evaluate", "hit-test", "category-container")), log_index)

    def test_article_iframe_body_focus_and_divider_are_humanized(self):
        app = dayu_article.DayuArticle(
            "图文标题", Path("unused.md"), Path("unused.json"), "无需标注"
        )
        app.document = SimpleNamespace(
            parts=["Hello", "<hr>"],
            text=["Hello"],
            images=[],
            content_html="<p>Hello</p>",
            manifest={},
        )
        log: list = []
        body = _FrameBody("article-body", log=log)
        title = _TypingLocator("article-title", log=log)
        divider = _Clickable("divider", log=log)
        page = _page(
            {ARTICLE_TITLE: title, DIVIDER: divider},
            log=log,
            frame_body=body,
        )
        shortcut = "Meta" if sys.platform == "darwin" else "Control"

        with (
            patch.object(dayu_article, "wait_dayu_article_body_stable", new=AsyncMock()),
            patch.object(dayu_article, "check_dayu_article_content", new=AsyncMock()),
        ):
            with _humanized():
                asyncio.run(app.fill_article_body(page, multilogin=True))

        # iframe 正文聚焦 + 分隔线：两次人类化点击。
        self.assertEqual(page.mouse.down_count, 2)
        self.assertEqual(body.click_count, 0)
        self.assertEqual(divider.click_count, 0)
        # 正文粘贴保持原生按键，不经过 Humanizer.type_text。
        self.assertEqual(
            body.pressed,
            [("press", f"{shortcut}+A"), ("press", f"{shortcut}+V"), ("press", "Shift")],
        )
        # 正文失焦仍是登记的 native focus 点击（粘贴后与分隔线后各一次）。
        self.assertEqual(title.click_count, 2)
        self.assertLess(
            log.index(("evaluate", "hit-test", "article-body")),
            log.index(("down",)),
        )
        divider_down = [i for i, event in enumerate(log) if event == ("down",)][1]
        self.assertLess(log.index(("evaluate", "hit-test", "divider")), divider_down)


# ---------------------------------------------------------------------------
# 2. 字段值读回
# ---------------------------------------------------------------------------


class HumanizeFieldReadbackTests(unittest.TestCase):
    def test_article_author_kept_when_omitted_and_replaced_when_passed(self):
        for author, expected in ((None, "Page Author"), ("新作者", "新作者")):
            with self.subTest(author=author), tempfile.TemporaryDirectory() as tmp:
                app = dayu_article.DayuArticle(
                    "New Article Title",
                    Path(tmp) / "body.md",
                    Path(tmp) / "account.json",
                    "无需标注",
                    author=author,
                )
                app.document = SimpleNamespace(images=[])
                log: list = []
                title = _TypingLocator("article-title", log=log, initial="Draft title")
                author_input = _TypingLocator(
                    "article-author", log=log, initial="Page Author"
                )
                source = _Radio("article-source")
                original = FakeLocator("article-link", count=0)
                link_field = _Clickable(
                    "article-link-field", log=log, children={ARTICLE_LINK: original}
                )
                selectors = {
                    ARTICLE_TITLE: title,
                    AUTHOR: author_input,
                    ARTICLE_SOURCE: source,
                    ARTICLE_LINK_FIELD: link_field,
                    "label": FakeLocator("has-label"),
                }
                selectors.update(_schedule_selectors(log))
                page = _page(selectors, log=log)

                with patch.object(app, "fill_article_body", new=AsyncMock()):
                    with _humanized():
                        asyncio.run(app.fill_article_form(page, multilogin=True))

                # 标题可能恢复草稿：先读空，再整体替换。
                self.assertEqual(title.buffer, "New Article Title")
                self.assertEqual(author_input.buffer, expected)
                if author is None:
                    self.assertEqual(
                        [action for action in author_input.actions if action[0] == "focus"],
                        [],
                    )
                else:
                    self.assertEqual(
                        [action for action in author_input.actions if action[0] == "focus"],
                        [("focus",)],
                    )


# ---------------------------------------------------------------------------
# HUMANIZE=0 快路径
# ---------------------------------------------------------------------------


class HumanizeDisabledTests(unittest.TestCase):
    def test_video_text_is_one_insert_per_field_and_clicks_are_native_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _video_app(tmp)
            log: list = []
            (
                selectors,
                title,
                description,
                tags,
                category,
                option,
                save,
                link,
            ) = _video_selectors(log)
            page = _page(selectors, log=log)

            with _humanized(), patch.dict(os.environ, {"HUMANIZE": "0"}):
                asyncio.run(app.fill_video_form(page))

            inserts = [
                action for action in page.keyboard.actions if action[0] == "insert_text"
            ]
            self.assertEqual(
                inserts,
                [
                    ("insert_text", "Hi标题"),
                    ("insert_text", "Body"),
                    ("insert_text", "旅行"),
                    ("insert_text", "美食"),
                    ("insert_text", "https://example.com/a"),
                ],
            )
            self.assertEqual(app._humanizer_instance.pauses, [])
            self.assertEqual(page.mouse.down_count, 0)
            for locator in (category, option, tags, save):
                self.assertEqual(locator.click_count, 1)
            self.assertEqual(title.buffer, "Hi标题")
            self.assertEqual(description.buffer, "Body")
            self.assertEqual(link.buffer, "https://example.com/a")


# ---------------------------------------------------------------------------
# 3. 平台静态门
# ---------------------------------------------------------------------------


class HumanizeGateTests(unittest.TestCase):
    def test_dayu_package_passes_gates_a_to_e(self):
        package = Path(__file__).resolve().parent.parent / "uploader" / "dayu_uploader"
        assert_clean(package)


if __name__ == "__main__":
    unittest.main()
