# -*- coding: utf-8 -*-
"""支付宝生活号发布表单的人类化接线（spec §3.1 / §6.2）。

三块，全部离线：

1. **事件序列** —— 标题/描述走 ``ControlOrMeta+A → Delete → type_text``；
   每个输入恰一次 ``after_type``；封面弹窗、合集下拉、质量提示与两处发布
   全部走 ``Humanizer.click``（``mouse.down`` 之前先有 stillOn 命中测试），
   只有扫码 tab 与「上传图片」文件入口保持原生。
2. **字段值读回** —— fake 键盘把按键写回持有缓冲的 locator，断言最终值与
   预期完全相等（抓「序列对、值错」：清空不净、追加、``\\r\\n`` 未归一）。
3. **平台静态门** —— 包内跑 spec §4.2–4.5 的 A–E 门。

另外覆盖：合集两级点击合并为一次（无 ``force``）、>1000 码点整段 bulk、
``HUMANIZE=0`` 快路径。选择器未 scripted 直接抛
:class:`UnscriptedSelectorError`，不用 MagicMock 掩盖选择器漂移。
"""

from __future__ import annotations

import asyncio
import inspect
import os
import random
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import uploader.alipay_uploader.main as alipay_main
from patchright.async_api import TimeoutError as PWTimeoutError
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
from utils.errors import LoginRequiredError, PublishResultUnknownError
from utils.humanize import (
    HumanizeProfile,
    Humanizer,
    LogNormal,
    MAYBE_DISPATCHED,
    MAYBE_DISPATCHED_VALUE,
)

TITLE_PLACEHOLDER = "一个好的标题，能获得更多人的喜欢哦"
DESC_PLACEHOLDER = "填写作品描述，让你的作品更容易被看到"
COVER_TEXT = "text:上传封面:exact"
COVER_MODAL = ".antd5-modal-body"
COVER_UPLOAD_IMAGE = "role:button:上传图片"
COVER_DONE = "role:button:完 成"
COVER_FILE_INPUT = (
    'input[type="file"][accept*="jpg"], input[type="file"][accept*="png"]'
)
COMPILATION_INPUT = 'input[id*="_compilationInfo"]'
COMPILATION_ANCESTOR = "xpath=../../.."
COLLECTION_SELECT = ".antd5-select:has(.antd5-select-selection-placeholder)"
COLLECTION_OPTIONS = '[role="option"]'
PUBLISH_ROLE = "role:button:确认发布"
POSTS_URL = "https://c.alipay.com/page/content-creation/posts"
PUBLISH_URL = "https://c.alipay.com/page/content-creation/publish/short-video?id=1"

PACKAGE = Path(__file__).resolve().parent.parent / "uploader" / "alipay_uploader"


def _fixed(seconds: float) -> LogNormal:
    return LogNormal(0.0, 0.0, seconds, seconds)


#: ``_pause`` 按对象身份归类，所以值只需互不相同。
TEST_PROFILE = HumanizeProfile(
    keystroke=_fixed(0.01),
    after_type=_fixed(0.02),
    after_navigate=_fixed(0.03),
    before_submit=_fixed(0.04),
    pointer_settle=_fixed(0.05),
    click_hold=_fixed(0.06),
    before_click=_fixed(0.07),
    after_click=_fixed(0.08),
    between_scroll=_fixed(0.09),
    reading=_fixed(0.10),
    after_interact=_fixed(0.11),
)

_PAUSE_FIELDS = (
    "keystroke",
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
)

_FACTS = {
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


class _Timeline:
    """共享事件流：键盘 / 鼠标 / 命中测试 / 停顿都写同一条时间线。"""

    def __init__(self) -> None:
        self.events: list[tuple] = []

    def add(self, *event) -> None:
        self.events.append(event)

    def index(self, event) -> int:
        return self.events.index(event)

    def indexes(self, event) -> list[int]:
        return [i for i, item in enumerate(self.events) if item == event]

    def of_kind(self, first: str, second: str) -> list[int]:
        return [
            i
            for i, item in enumerate(self.events)
            if len(item) > 1 and item[0] == first and item[1] == second
        ]


class Element(RecordingLocator):
    """可被 ``Humanizer.click`` 坐标点击的 fake：盒模型 + 探测 + 命中测试。"""

    def __init__(
        self,
        name: str,
        *,
        timeline: _Timeline | None = None,
        box: dict | None = None,
        **kwargs,
    ) -> None:
        kwargs.setdefault("computed_style", dict(_FACTS))
        kwargs.setdefault(
            "box", box or {"x": 20.0, "y": 40.0, "width": 160.0, "height": 32.0}
        )
        super().__init__(name, **kwargs)
        self.timeline = timeline
        self.on_human_click = None
        self.scroll_calls = 0

    async def evaluate(self, expression, arg=None):
        self.evaluate_calls.append((expression, arg))
        kind = _expr_kind(expression)
        if self.timeline is not None:
            self.timeline.add("evaluate", kind, self.name)
        if kind == "hit-test":
            return {"self": True, "tag": "div", "className": "", "id": "", "text": ""}
        if kind == "geometry":
            return {
                "width": self._box["width"],
                "height": self._box["height"],
                "inside": True,
                "clipped": False,
                "childFrame": False,
            }
        return dict(_FACTS)

    async def is_disabled(self) -> bool:
        return not self._enabled

    async def scroll_into_view_if_needed(self, **kwargs) -> None:
        self.scroll_calls += 1


class _ChooserDepthElement(Element):
    """「上传图片」入口 fake：记录点击时的 ``chooser_depth``，可模拟点击后 DOM。

    深度 1 = 这一下被 ``expect_file_chooser`` 消费；0 = 裸点击、系统选择器
    会留在屏幕上。
    """

    def __init__(self, name: str, *, timeline: _Timeline | None = None, **kwargs) -> None:
        super().__init__(name, timeline=timeline, **kwargs)
        self.page = None
        self.click_depths: list[int] = []
        self.on_click_effect = None

    async def click(self, **kwargs) -> None:
        if self.page is not None:
            self.click_depths.append(self.page.chooser_depth)
        await super().click(**kwargs)
        if self.on_click_effect is not None:
            self.on_click_effect()


class TypingElement(Element):
    """持有键入缓冲的输入框；点击 / 命中测试把焦点交给它。"""

    def __init__(self, name: str, *, initial: str = "", **kwargs) -> None:
        super().__init__(name, **kwargs)
        self.buffer = initial
        self.page = None

    async def evaluate(self, expression, arg=None):
        result = await super().evaluate(expression, arg)
        if _expr_kind(expression) == "hit-test" and self.page is not None:
            self.page.focused = self
            self.page.selected = False
        return result

    async def click(self, **kwargs) -> None:
        # HUMANIZE=0 快路径走原生 click；真实点击也会把焦点交给输入框。
        await super().click(**kwargs)
        if self.page is not None:
            self.page.focused = self
            self.page.selected = False

    async def input_value(self) -> str:
        return self.buffer

    async def inner_text(self) -> str:
        return self.buffer

    def apply_key(self, key: str) -> None:
        page = self.page
        if page is None or page.focused is not self:
            return
        if key in ("ControlOrMeta+A", "Control+A", "Meta+A"):
            page.selected = True
        elif key in ("Delete", "Backspace"):
            if page.selected:
                self.buffer = ""
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
        page = self.page
        if page is None or page.focused is not self:
            return
        if page.selected:
            self.buffer = text
            page.selected = False
        else:
            self.buffer += text


class BufferKeyboard(RecordingKeyboard):
    """把按键写回聚焦输入框，同时记入时间线。"""

    def __init__(self, page: "AlipayPage", timeline: _Timeline) -> None:
        super().__init__()
        self.page = page
        self.timeline = timeline

    async def press(self, key: str, **kwargs) -> None:
        self.actions.append(("press", key))
        self.timeline.add("key", ("press", key))
        self.page.apply_key(key)

    async def insert_text(self, text: str, **kwargs) -> None:
        self.actions.append(("insert_text", text))
        self.timeline.add("key", ("insert_text", text))
        self.page.apply_text(text)

    async def type(self, text: str, delay: float | None = None, **kwargs) -> None:
        self.actions.append(("type", text, delay))
        self.timeline.add("key", ("type", text, delay))
        self.page.apply_text(text)


class TimelineMouse(RecordingMouse):
    def __init__(self, timeline: _Timeline) -> None:
        super().__init__()
        self.timeline = timeline

    async def move(self, x: float, y: float, **kwargs) -> None:
        await super().move(x, y, **kwargs)
        self.timeline.add("move", x, y)

    async def down(self, **kwargs) -> None:
        await super().down(**kwargs)
        self.timeline.add("down")

    async def up(self, **kwargs) -> None:
        await super().up(**kwargs)
        self.timeline.add("up")


class AlipayPage(RecordingPage):
    """RecordingPage + 支付宝用到的额外查找（placeholder / 事件监听）。"""

    def __init__(self, *, selectors=None, timeline=None, **kwargs) -> None:
        kwargs.setdefault("evaluate_handler", lambda expression, arg: {})
        super().__init__(selectors=selectors, **kwargs)
        self.timeline = timeline or _Timeline()
        self.keyboard = BufferKeyboard(self, self.timeline)
        self.mouse = TimelineMouse(self.timeline)
        self.focused = None
        self.selected = False
        self.listeners: dict[str, list] = {}
        self.wait_yields = 0

    def get_by_placeholder(self, text: str) -> FakeLocator:
        key = f"placeholder:{text}"
        try:
            return self._selectors[key]
        except KeyError as exc:
            raise UnscriptedSelectorError(
                f"page: un-scripted get_by_placeholder({text!r}); "
                f"scripted: {sorted(self._selectors)}"
            ) from exc

    def on(self, event: str, handler) -> None:
        self.listeners.setdefault(event, []).append(handler)

    def remove_listener(self, event: str, handler) -> None:
        self.listeners.get(event, []).remove(handler)

    async def wait_for_timeout(self, milliseconds: float) -> None:
        self._record_wait("wait_for_timeout", milliseconds, (milliseconds,))
        # 让 ``_collect_response`` 之类的后台任务有机会跑。
        await asyncio.sleep(0)
        self.wait_yields += 1

    def apply_key(self, key: str) -> None:
        if self.focused is not None:
            self.focused.apply_key(key)

    def apply_text(self, text: str) -> None:
        if self.focused is not None:
            self.focused.apply_text(text)


class QuietHumanizer(Humanizer):
    """真实原语、零墙钟：停顿按身份登记，点击回调到目标上。"""

    def __init__(self, page, **kwargs) -> None:
        kwargs.pop("sleep", None)
        super().__init__(
            page, profile=TEST_PROFILE, rng=random.Random(0), sleep=self._no_sleep
        )
        self.pauses: list[str] = []
        self.clicked: list[str] = []

    async def _no_sleep(self, seconds: float) -> None:  # pragma: no cover
        return None

    async def _pause(self, action) -> None:
        if not self.enabled:
            return
        for name in _PAUSE_FIELDS:
            if action is getattr(self.profile, name):
                self.pauses.append(name)
                timeline = getattr(self.page, "timeline", None)
                if timeline is not None:
                    timeline.add("pause", name)
                return

    async def click(self, locator, *, point=None) -> None:
        self.clicked.append(locator.name)
        hook = getattr(locator, "on_human_click", None)
        if hook is not None:
            hook()
        await super().click(locator, point=point)

    def pause_count(self, name: str) -> int:
        return self.pauses.count(name)


def _attach(page: AlipayPage, locator: FakeLocator) -> None:
    if isinstance(locator, TypingElement):
        locator.page = page
    for child in locator._children.values():
        _attach(page, child)


def _page(
    selectors: dict[str, FakeLocator], timeline: _Timeline | None = None
) -> AlipayPage:
    page = AlipayPage(selectors=dict(selectors), timeline=timeline or _Timeline())
    for locator in page._selectors.values():
        _attach(page, locator)
    return page


def _fail_first_file_chooser(page: AlipayPage, error: BaseException) -> None:
    """Make only the inner 「上传封面」 chooser expectation time out.

    The page fake has one page-level ``fail_file_chooser`` switch; the cover
    fallback now opens two expectations (inner entry, then 「上传图片」), so this
    wrapper fails the first one only.
    """
    original = page.expect_file_chooser
    state = {"calls": 0}

    def _expect(*, timeout: float | int | None = None):
        state["calls"] += 1
        page.fail_file_chooser = error if state["calls"] == 1 else None
        return original(timeout=timeout)

    page.expect_file_chooser = _expect


def _app(tmp: str, **overrides) -> alipay_main.AlipayVideo:
    values = {
        "title": "标题甲",
        "file_path": Path(tmp) / "clip.mp4",
        "tags": [],
        "account_file": Path(tmp) / "account.json",
        "desc": "",
    }
    values.update(overrides)
    return alipay_main.AlipayVideo(**values)


def _humanized():
    """把模块里的 ``Humanizer`` 换成零墙钟版本（实例仍按 page 缓存）。"""

    def _make(page, **kwargs):
        return QuietHumanizer(page)

    return patch.object(alipay_main, "Humanizer", _make)


class _TempDir:
    def __enter__(self) -> str:
        import tempfile

        self._dir = tempfile.TemporaryDirectory()
        return self._dir.name

    def __exit__(self, *exc) -> bool:
        self._dir.cleanup()
        return False


def _publish_selectors(timeline: _Timeline, quality_count: int) -> dict:
    return {
        PUBLISH_ROLE: Element("publish", timeline=timeline),
        alipay_main.ALIPAY_QUALITY_MODAL_BUTTON_SELECTOR: Element(
            "quality-continue", timeline=timeline, count=quality_count
        ),
        alipay_main.ALIPAY_SUCCESS_TOAST_SELECTOR: FakeLocator("success", count=0),
        alipay_main.ALIPAY_FAIL_TOAST_SELECTOR: FakeLocator("fail", count=0),
    }


# ---------------------------------------------------------------------------
# 1. 事件序列
# ---------------------------------------------------------------------------


class HumanizeEventSequenceTests(unittest.TestCase):
    def test_title_and_description_clear_then_type_per_character(self):
        timeline = _Timeline()
        title = TypingElement("title", timeline=timeline, initial="旧标题")
        desc = TypingElement("description", timeline=timeline, initial="旧描述")
        page = _page(
            {
                f"placeholder:{TITLE_PLACEHOLDER}": title,
                f"placeholder:{DESC_PLACEHOLDER}": desc,
            },
            timeline=timeline,
        )
        with _TempDir() as tmp:
            app = _app(tmp, tags=["话题"], desc="第一行\r\n第二行")
            with _humanized():
                humanizer = app._humanizer(page)
                asyncio.run(app.fill_title_and_tags(page))
                asyncio.run(app.fill_description(page))

        keyboard = page.keyboard.actions
        # sel 形态：聚焦点击 → 全选 + 删除，中间不插其它动作。
        self.assertEqual(
            keyboard[:2],
            [("press", "ControlOrMeta+A"), ("press", "Delete")],
        )
        self.assertLess(
            timeline.index(("evaluate", "hit-test", "title")),
            timeline.index(("key", keyboard[0])),
        )
        # 每个输入恰一次 after_type，且没有 fill()/type() 老路。
        self.assertEqual(humanizer.pause_count("after_type"), 2)
        self.assertEqual([a for a in keyboard if a[0] == "type"], [])
        self.assertEqual([a for a in title.actions if a[0] == "fill"], [])
        self.assertEqual([a for a in desc.actions if a[0] == "fill"], [])
        # 中文逐字 insert_text；标题里的 `#` 与空格是真按键。
        self.assertIn(("insert_text", "标"), keyboard)
        self.assertIn(("press", "#"), keyboard)
        self.assertIn(("press", " "), keyboard)
        # 描述里的换行归一后是具名 Enter。
        self.assertIn(("press", "Enter"), keyboard)
        # 两个字段各一次人类化点击；stillOn 命中测试先于 down。
        self.assertEqual(title.click_count, 0)
        self.assertEqual(desc.click_count, 0)
        self.assertEqual(page.mouse.down_count, 2)
        hits = timeline.of_kind("evaluate", "hit-test")
        downs = timeline.indexes(("down",))
        self.assertEqual(len(downs), 2)
        self.assertLess(hits[0], downs[0])
        self.assertLess(hits[1], downs[1])

    def test_cover_dialog_and_done_are_humanized_but_chooser_stays_native(self):
        timeline = _Timeline()
        cover = Element("cover-entry", timeline=timeline)
        inner = Element("cover-tab", timeline=timeline)
        upload_image = Element("cover-chooser", timeline=timeline)
        done = Element("cover-done", timeline=timeline)
        img_input = FakeLocator("cover-file")
        modal = Element(
            "cover-modal",
            timeline=timeline,
            children={
                COVER_TEXT: inner,
                COVER_UPLOAD_IMAGE: upload_image,
            },
        )
        page = _page(
            {
                COVER_TEXT: cover,
                COVER_MODAL: modal,
                COVER_DONE: done,
                COVER_FILE_INPUT: img_input,
            },
            timeline=timeline,
        )
        with _TempDir() as tmp:
            app = _app(tmp, thumbnail_path=Path(tmp) / "cover.jpg")
            with _humanized():
                asyncio.run(app.upload_thumbnail(page))

        for target in (cover, inner, done):
            self.assertEqual(target.click_count, 0, target.name)
        # 弹窗里已有隐藏 input：直接写，既不点内层「上传封面」，也不点「上传
        # 图片」，所以从不拉起系统文件选择器（先例：小红书 bbc5361）。
        self.assertEqual(upload_image.click_count, 0)
        self.assertEqual(page.expect_file_chooser_calls, 0)
        self.assertEqual(img_input.files, [Path(tmp) / "cover.jpg"])
        self.assertEqual(page.mouse.down_count, 2)
        hits = timeline.of_kind("evaluate", "hit-test")
        downs = timeline.indexes(("down",))
        self.assertEqual(len(downs), 2)
        for hit, down in zip(hits, downs):
            self.assertLess(hit, down)

    def test_cover_upload_button_is_clicked_inside_the_file_chooser(self):
        timeline = _Timeline()
        cover = Element("cover-entry", timeline=timeline)
        inner = Element("cover-tab", timeline=timeline)
        inner_depths: list[int] = []
        upload_image = _ChooserDepthElement("cover-chooser", timeline=timeline)
        done = Element("cover-done", timeline=timeline)
        img_input = FakeLocator("cover-file", count=0)
        modal = Element(
            "cover-modal",
            timeline=timeline,
            children={
                COVER_TEXT: inner,
                COVER_UPLOAD_IMAGE: upload_image,
            },
        )
        page = _page(
            {
                COVER_TEXT: cover,
                COVER_MODAL: modal,
                COVER_DONE: done,
                COVER_FILE_INPUT: img_input,
            },
            timeline=timeline,
        )
        inner.on_human_click = lambda: inner_depths.append(page.chooser_depth)
        upload_image.page = page
        _fail_first_file_chooser(page, PWTimeoutError("no file chooser"))
        with _TempDir() as tmp:
            app = _app(tmp, thumbnail_path=Path(tmp) / "cover.jpg")
            with _humanized():
                asyncio.run(app.upload_thumbnail(page))

        # input 缺失才展开上传区；两次 chooser 断言：内层「上传封面」一次（短
        # 超时，防它拉起系统选择器）、「上传图片」一次（深度 1，不是裸点击）。
        self.assertEqual(inner_depths, [1])
        self.assertEqual(page.expect_file_chooser_calls, 2)
        self.assertEqual(
            page.timeouts("expect_file_chooser"),
            [
                alipay_main.ALIPAY_COVER_INNER_CHOOSER_TIMEOUT_MS,
                alipay_main.ALIPAY_COVER_CHOOSER_TIMEOUT_MS,
            ],
        )
        self.assertEqual(upload_image.click_depths, [1])
        self.assertIsNone(upload_image.click_calls[0].get("force"))
        self.assertEqual(page.file_chooser_files(), [Path(tmp) / "cover.jpg"])
        self.assertNotIn("set_input_files", [a[0] for a in img_input.actions])
        self.assertEqual(page.chooser_depth, 0)

    def test_inner_cover_entry_that_opens_a_chooser_is_consumed(self):
        """No bare click on the inner entry: a chooser it opens is consumed."""
        timeline = _Timeline()
        cover = Element("cover-entry", timeline=timeline)
        inner = Element("cover-tab", timeline=timeline)
        inner_depths: list[int] = []
        upload_image = _ChooserDepthElement("cover-chooser", timeline=timeline)
        done = Element("cover-done", timeline=timeline)
        img_input = FakeLocator("cover-file", count=0)
        modal = Element(
            "cover-modal",
            timeline=timeline,
            children={
                COVER_TEXT: inner,
                COVER_UPLOAD_IMAGE: upload_image,
            },
        )
        page = _page(
            {
                COVER_TEXT: cover,
                COVER_MODAL: modal,
                COVER_DONE: done,
                COVER_FILE_INPUT: img_input,
            },
            timeline=timeline,
        )
        inner.on_human_click = lambda: inner_depths.append(page.chooser_depth)
        upload_image.page = page
        with _TempDir() as tmp:
            app = _app(tmp, thumbnail_path=Path(tmp) / "cover.jpg")
            with _humanized():
                asyncio.run(app.upload_thumbnail(page))

        self.assertEqual(inner_depths, [1])
        self.assertEqual(
            page.timeouts("expect_file_chooser"),
            [alipay_main.ALIPAY_COVER_INNER_CHOOSER_TIMEOUT_MS],
        )
        self.assertEqual(page.file_chooser_files(), [Path(tmp) / "cover.jpg"])
        # The inner entry already produced the file: never click 「上传图片」.
        self.assertEqual(upload_image.click_count, 0)
        self.assertNotIn("set_input_files", [a[0] for a in img_input.actions])
        self.assertEqual(page.chooser_depth, 0)

    def test_cover_input_is_written_when_no_file_chooser_arrives(self):
        timeline = _Timeline()
        cover = Element("cover-entry", timeline=timeline)
        inner = Element("cover-tab", timeline=timeline)
        upload_image = _ChooserDepthElement("cover-chooser", timeline=timeline)
        done = Element("cover-done", timeline=timeline)
        img_input = FakeLocator("cover-file", count=0)
        modal = Element(
            "cover-modal",
            timeline=timeline,
            children={
                COVER_TEXT: inner,
                COVER_UPLOAD_IMAGE: upload_image,
            },
        )
        page = _page(
            {
                COVER_TEXT: cover,
                COVER_MODAL: modal,
                COVER_DONE: done,
                COVER_FILE_INPUT: img_input,
            },
            timeline=timeline,
        )
        page.fail_file_chooser = PWTimeoutError("no file chooser")
        upload_image.on_click_effect = lambda: setattr(img_input, "_count", 1)
        with _TempDir() as tmp:
            app = _app(tmp, thumbnail_path=Path(tmp) / "cover.jpg")
            with _humanized():
                asyncio.run(app.upload_thumbnail(page))

        self.assertEqual(page.expect_file_chooser_calls, 2)
        self.assertEqual(page.file_chooser_files(), [])
        self.assertEqual(img_input.files, [Path(tmp) / "cover.jpg"])
        self.assertEqual(done.click_count, 0)

    def test_inner_cover_click_error_is_never_swallowed_by_the_chooser_guard(self):
        timeline = _Timeline()
        inner = Element("cover-tab", timeline=timeline)
        unusable = ElementUnusableError(
            what="上传封面", role="interactive", reason="covered-by:div.mask"
        )

        def _raise() -> None:
            raise unusable

        inner.on_human_click = _raise
        upload_image = _ChooserDepthElement("cover-chooser", timeline=timeline)
        img_input = FakeLocator("cover-file", count=0)
        modal = Element(
            "cover-modal",
            timeline=timeline,
            children={
                COVER_TEXT: inner,
                COVER_UPLOAD_IMAGE: upload_image,
            },
        )
        page = _page(
            {
                COVER_MODAL: modal,
                COVER_FILE_INPUT: img_input,
            },
            timeline=timeline,
        )
        with _TempDir() as tmp:
            app = _app(tmp, thumbnail_path=Path(tmp) / "cover.jpg")
            with _humanized():
                humanizer = app._humanizer(page)
                with self.assertRaises(ElementUnusableError):
                    asyncio.run(
                        app._set_cover_via_chooser(
                            page, humanizer, page.locator(COVER_MODAL)
                        )
                    )

        # A click error is not "the chooser never arrived": no fallback click.
        self.assertEqual(upload_image.click_count, 0)
        self.assertEqual(page.file_chooser_files(), [])

    def test_cover_click_failure_propagates_instead_of_writing_the_input(self):
        timeline = _Timeline()
        inner = Element("cover-tab", timeline=timeline)
        unusable = ElementUnusableError(
            what="上传图片", role="interactive", reason="covered-by:div.mask"
        )
        upload_image = _ChooserDepthElement(
            "cover-chooser", timeline=timeline, click_error=unusable
        )
        img_input = FakeLocator("cover-file", count=0)
        modal = Element(
            "cover-modal",
            timeline=timeline,
            children={
                COVER_TEXT: inner,
                COVER_UPLOAD_IMAGE: upload_image,
            },
        )
        page = _page(
            {
                COVER_MODAL: modal,
                COVER_FILE_INPUT: img_input,
            },
            timeline=timeline,
        )
        _fail_first_file_chooser(page, PWTimeoutError("no file chooser"))
        with _TempDir() as tmp:
            app = _app(tmp, thumbnail_path=Path(tmp) / "cover.jpg")
            with _humanized():
                humanizer = app._humanizer(page)
                with self.assertRaises(ElementUnusableError):
                    asyncio.run(
                        app._set_cover_via_chooser(
                            page, humanizer, page.locator(COVER_MODAL)
                        )
                    )

        # 人类化/原生点击错误不是「chooser 没到」：不得降级成直接写 input。
        self.assertEqual(img_input.actions, [])
        self.assertEqual(page.file_chooser_files(), [])

    def test_collection_dropdown_narrowed_and_option_clicked_once_without_force(self):
        for branch in ("ancestor", "placeholder"):
            with self.subTest(branch=branch):
                timeline = _Timeline()
                option = Element("collection-option", timeline=timeline)
                options = Element(
                    "collection-options", timeline=timeline, items=[option]
                )
                if branch == "ancestor":
                    select = Element("collection-select", timeline=timeline)
                    ancestor = select
                else:
                    select = Element("collection-placeholder", timeline=timeline)
                    ancestor = FakeLocator("collection-ancestor", count=0)
                compilation = Element(
                    "compilation-input",
                    timeline=timeline,
                    children={COMPILATION_ANCESTOR: ancestor},
                )
                page = _page(
                    {
                        COMPILATION_INPUT: compilation,
                        COLLECTION_SELECT: select,
                        COLLECTION_OPTIONS: options,
                    },
                    timeline=timeline,
                )
                with _TempDir() as tmp:
                    app = _app(tmp, collection_name="合集A")
                    with _humanized():
                        asyncio.run(app.apply_collection(page))

                self.assertEqual(option.click_count, 0)
                self.assertEqual(select.click_count, 0)
                self.assertEqual(page.mouse.down_count, 2)
                self.assertIn(
                    ("evaluate", "hit-test", "collection-option"), timeline.events
                )
                self.assertNotIn(
                    "force=", inspect.getsource(alipay_main.AlipayVideo.apply_collection)
                )

    def test_publish_and_quality_continue_carry_before_submit(self):
        timeline = _Timeline()
        page = _page(_publish_selectors(timeline, quality_count=1), timeline=timeline)
        page.url = PUBLISH_URL
        publish = page.locator(PUBLISH_ROLE)
        quality = page.locator(alipay_main.ALIPAY_QUALITY_MODAL_BUTTON_SELECTOR)
        page._selectors[PUBLISH_ROLE].on_human_click = lambda: setattr(
            page, "url", POSTS_URL
        )
        with _TempDir() as tmp:
            app = _app(tmp)
            with _humanized():
                humanizer = app._humanizer(page)
                asyncio.run(app.submit_publish(page))

        self.assertEqual(publish.click_count, 0)
        self.assertEqual(quality.click_count, 0)
        self.assertEqual(page.mouse.down_count, 2)
        self.assertEqual(humanizer.pause_count("before_submit"), 1)
        # before_submit 在发布落点移动/按下之前。
        self.assertLess(
            timeline.index(("pause", "before_submit")),
            timeline.index(("down",)),
        )

    def test_aigc_second_publish_is_humanized_with_its_own_before_submit(self):
        timeline = _Timeline()
        page = _page(_publish_selectors(timeline, quality_count=0), timeline=timeline)
        page.url = PUBLISH_URL
        publish = page.locator(PUBLISH_ROLE)
        clicks = {"count": 0}

        def _after_click() -> None:
            clicks["count"] += 1
            if clicks["count"] >= 2:
                page.url = POSTS_URL

        publish.on_human_click = _after_click

        class _Response:
            status = 200
            headers = {"content-type": "application/json"}
            url = "https://c.alipay.com/api/publish/queryLoopTask"

            class request:
                method = "GET"
                post_data = ""

            async def text(self):
                return '{"done":true}'

        response = _Response()
        original_on = page.on

        def _on(event: str, handler) -> None:
            original_on(event, handler)
            if event == "response":
                handler(response)

        page.on = _on

        with _TempDir() as tmp:
            app = _app(tmp)
            with _humanized():
                humanizer = app._humanizer(page)
                asyncio.run(app.submit_publish(page))

        self.assertEqual(clicks["count"], 2)
        self.assertEqual(publish.click_count, 0)
        self.assertEqual(page.mouse.down_count, 2)
        # 第一次提交点击 + AIGC 后二次点击，各自一次 before_submit。
        self.assertEqual(humanizer.pause_count("before_submit"), 2)


# ---------------------------------------------------------------------------
# 1b. 发布点击：可能已派发 → 结果未知；监听器必须清理
# ---------------------------------------------------------------------------


class _PublishFailingHumanizer(QuietHumanizer):
    """真实点击后按 locator 名注入异常（模拟 ``mouse.down`` 之后的失败）。"""

    def __init__(self, page, *, error: BaseException, target: str = "publish") -> None:
        super().__init__(page)
        self.error = error
        self.target = target
        self.dispatches: list[str] = []

    async def click(self, locator, *, point=None) -> None:
        await super().click(locator, point=point)
        name = getattr(locator, "name", "")
        if name == self.target:
            self.dispatches.append(name)
            raise self.error


class PublishDispatchGuardTests(unittest.TestCase):
    def _maybe_error(self) -> RuntimeError:
        exc = RuntimeError("mouse up failed")
        setattr(exc, MAYBE_DISPATCHED, MAYBE_DISPATCHED_VALUE)
        return exc

    def _submit(self, page, humanizer):
        with patch.object(
            alipay_main, "Humanizer", lambda page, **kwargs: humanizer
        ):
            with _TempDir() as tmp:
                app = _app(tmp)
                app._humanizer_instance = humanizer
                asyncio.run(app.submit_publish(page))

    def test_publish_after_mouse_down_maps_to_unknown_and_removes_listeners(self):
        timeline = _Timeline()
        page = _page(_publish_selectors(timeline, quality_count=0), timeline=timeline)
        page.url = PUBLISH_URL
        publish = page.locator(PUBLISH_ROLE)
        humanizer = _PublishFailingHumanizer(page, error=self._maybe_error())

        with self.assertRaises(PublishResultUnknownError):
            self._submit(page, humanizer)

        self.assertEqual(humanizer.dispatches, ["publish"])
        self.assertEqual(publish.click_count, 0)
        self.assertEqual(page.mouse.down_count, 1)
        self.assertEqual(page.listeners.get("response", []), [])
        self.assertEqual(page.listeners.get("request", []), [])

    def test_aigc_second_click_after_mouse_down_maps_to_unknown(self):
        timeline = _Timeline()
        page = _page(_publish_selectors(timeline, quality_count=0), timeline=timeline)
        page.url = PUBLISH_URL
        publish = page.locator(PUBLISH_ROLE)

        class _AigcResponse:
            status = 200
            headers = {"content-type": "application/json"}
            url = "https://c.alipay.com/api/publish/queryLoopTask"

            class request:
                method = "GET"
                post_data = ""

            async def text(self):
                return '{"done":true}'

        response = _AigcResponse()
        original_on = page.on

        def _on(event: str, handler) -> None:
            original_on(event, handler)
            if event == "response":
                handler(response)

        page.on = _on

        class _SecondClickFailing(_PublishFailingHumanizer):
            def __init__(self, page, *, error) -> None:
                super().__init__(page, error=error)
                self.publish_dispatches = 0

            async def click(self, locator, *, point=None) -> None:
                await Humanizer.click(self, locator, point=point)
                if getattr(locator, "name", "") == "publish":
                    self.publish_dispatches += 1
                    if self.publish_dispatches == 2:
                        raise self.error

        humanizer = _SecondClickFailing(page, error=self._maybe_error())

        with self.assertRaises(PublishResultUnknownError):
            self._submit(page, humanizer)

        # 首次提交 + AIGC 后二次点击各派发一次，绝不出现第三次。
        self.assertEqual(humanizer.publish_dispatches, 2)
        self.assertEqual(publish.click_count, 0)

    def test_pre_dispatch_publish_failure_propagates_and_removes_listeners(self):
        timeline = _Timeline()
        page = _page(_publish_selectors(timeline, quality_count=0), timeline=timeline)
        page.url = PUBLISH_URL
        error = ElementUnusableError(
            what="点击目标",
            role="interactive",
            selector="",
            reason="covered-by:mask",
            publish_clicked=False,
        )
        humanizer = _PublishFailingHumanizer(page, error=error)

        with self.assertRaises(ElementUnusableError) as caught:
            self._submit(page, humanizer)

        self.assertIs(caught.exception, error)
        self.assertEqual(page.listeners.get("response", []), [])
        self.assertEqual(page.listeners.get("request", []), [])


# ---------------------------------------------------------------------------
# 2. 字段值读回
# ---------------------------------------------------------------------------


class LoginRedirectPublishAttemptTests(unittest.TestCase):
    """发布点击之后的登录跳转必须带 ``publish_attempted=True``。"""

    def test_pre_click_redirect_is_not_marked_as_dispatched(self):
        page = SimpleNamespace(url="https://auth.alipay.com/login/index.htm")

        with self.assertRaises(LoginRequiredError) as caught:
            alipay_main._raise_if_login_required(page)

        self.assertFalse(caught.exception.publish_attempted)

    def test_post_click_poll_marks_the_redirect_as_dispatched(self):
        timeline = _Timeline()
        page = _page(_publish_selectors(timeline, quality_count=0), timeline=timeline)
        page.url = PUBLISH_URL
        page.locator(PUBLISH_ROLE).on_human_click = lambda: setattr(
            page, "url", "https://auth.alipay.com/login/index.htm"
        )

        with _TempDir() as tmp:
            app = _app(tmp)
            with _humanized():
                humanizer = app._humanizer(page)
                with self.assertRaises(LoginRequiredError) as caught:
                    asyncio.run(app.submit_publish(page, multilogin=True))

        self.assertTrue(caught.exception.publish_attempted)


class HumanizeReadbackTests(unittest.TestCase):
    def test_readback_clears_and_replaces_title_and_description(self):
        title = TypingElement("title", initial="旧标题旧标题")
        desc = TypingElement("description", initial="旧描述旧描述")
        page = _page(
            {
                f"placeholder:{TITLE_PLACEHOLDER}": title,
                f"placeholder:{DESC_PLACEHOLDER}": desc,
            }
        )
        with _TempDir() as tmp:
            app = _app(
                tmp, title="标题甲", tags=["话题一", "话题二"], desc="第一行\r\n第二行"
            )
            with _humanized():
                asyncio.run(app.fill_title_and_tags(page))
                asyncio.run(app.fill_description(page))

        self.assertEqual(
            title.buffer,
            alipay_main.format_title_with_tags("标题甲", ["话题一", "话题二"]),
        )
        self.assertEqual(desc.buffer, "第一行\n第二行")

    def test_over_horizon_description_is_one_bulk_insert(self):
        body = "字" * 1001
        desc = TypingElement("description")
        page = _page({f"placeholder:{DESC_PLACEHOLDER}": desc})
        with _TempDir() as tmp:
            app = _app(tmp, desc=body)
            with _humanized():
                humanizer = app._humanizer(page)
                asyncio.run(app.fill_description(page))

        inserts = [a for a in page.keyboard.actions if a[0] == "insert_text"]
        self.assertEqual(inserts, [("insert_text", body)])
        self.assertEqual(desc.buffer, body)
        self.assertEqual(humanizer.pause_count("after_type"), 1)


# ---------------------------------------------------------------------------
# 3. HUMANIZE=0 快路径
# ---------------------------------------------------------------------------


class HumanizeDisabledTests(unittest.TestCase):
    def test_text_is_one_bulk_insert_and_clicks_are_native(self):
        title = TypingElement("title", initial="旧标题")
        desc = TypingElement("description", initial="旧描述")
        page = _page(
            {
                f"placeholder:{TITLE_PLACEHOLDER}": title,
                f"placeholder:{DESC_PLACEHOLDER}": desc,
            }
        )
        with _TempDir() as tmp:
            app = _app(tmp, tags=["话题"], desc="正文")
            with _humanized(), patch.dict(os.environ, {"HUMANIZE": "0"}):
                humanizer = app._humanizer(page)
                asyncio.run(app.fill_title_and_tags(page))
                asyncio.run(app.fill_description(page))

        inserts = [a for a in page.keyboard.actions if a[0] == "insert_text"]
        self.assertEqual(
            inserts,
            [("insert_text", "标题甲 #话题"), ("insert_text", "正文")],
        )
        self.assertNotIn(("press", "标"), page.keyboard.actions)
        self.assertEqual(humanizer.pauses, [])
        # 点击走原生 locator.click：一次/目标、零 mouse.down。
        self.assertEqual(title.click_count, 1)
        self.assertEqual(desc.click_count, 1)
        self.assertEqual(page.mouse.down_count, 0)
        self.assertEqual(title.buffer, "标题甲 #话题")
        self.assertEqual(desc.buffer, "正文")


# ---------------------------------------------------------------------------
# 4. 平台静态门
# ---------------------------------------------------------------------------


class HumanizeGateTests(unittest.TestCase):
    def test_alipay_package_passes_gates_a_to_e(self):
        assert_clean(PACKAGE)


if __name__ == "__main__":
    unittest.main()
