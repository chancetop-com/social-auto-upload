# -*- coding: utf-8 -*-
"""百家号：contenteditable 清空序列 + 合集候选全等（工单 17，spec §3.2）。

三块离线验收（spec §6.2，缺一不可）：

1. **事件序列** —— 标题保留「点标题 → Ctrl+A → Backspace」清空序列，键改由
   ``Humanizer.press`` 执行、正文逐字；封面 / 声明 / 合集 / 发布全部走
   ``Humanizer.click``（``stillOn`` hit-test 先于 ``mouse.down``），封面弹窗
   「上传」tab 与 ``set_input_files`` 成对保持原生；零 ``fill`` / ``el.click``
   / ``force``。
2. **字段值读回** —— fake 键盘把按键写回持有缓冲的字段，断言标题最终值等于
   预期（页面自动填入的文件名必须被完全替换，不是追加）；合集候选取全等项，
   命中不到时沿用「警告 + Escape」跳过，不选错合集、不中止发布。
3. **平台静态门** —— ``tests.humanize_gates.assert_clean`` 在本包上跑 A–E。

另外覆盖 ``HUMANIZE=0`` 语义切换（一次 ``insert_text`` + 原生 ``locator.click``
+ 零停顿）与「一个 page 一个实例」的缓存语义。

未 scripted 的选择器直接抛 :class:`UnscriptedSelectorError`，不用 MagicMock
掩盖选择器漂移。
"""

from __future__ import annotations

import asyncio
import os
import random
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import uploader.baijiahao_uploader.main as baijiahao_main
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
from uploader.baijiahao_uploader.main import (
    AI_DECLARATION_OPTION_SELECTOR,
    AI_DECLARATION_TRIGGER_SELECTOR,
    BAIJIAHAO_SUCCESS_URL_PREFIX,
    COLLECTION_OPTION_SELECTOR,
    COLLECTION_SEARCH_INPUT_SELECTOR,
    COLLECTION_SELECTOR,
    COVER_CONFIRM_SELECTOR,
    COVER_ENTRY_SELECTOR,
    COVER_IMAGE_INPUT_SELECTOR,
    COVER_UPLOAD_BUTTON_SELECTOR,
    DECLARATION_CONFIRM_SELECTOR,
    DECLARATION_MODAL_SELECTOR,
    PUBLISH_BUTTON_SELECTOR,
    TITLE_EDITOR_SELECTOR,
    BaiJiaHaoVideo,
)
from utils.browser_session import BrowserSession
from utils.dom import ElementUnusableError
from utils.errors import LoginRequiredError, PublishResultUnknownError
from utils.humanize import HumanizeProfile, Humanizer, LogNormal
from utils.humanize import MAYBE_DISPATCHED, MAYBE_DISPATCHED_VALUE

PACKAGE = Path(__file__).resolve().parent.parent / "uploader" / "baijiahao_uploader"

AFTER_TYPE = 5.0
BEFORE_SUBMIT = 7.0

#: 短标题会被补成「测试标题 你不知道的」（≤30 字）
PADDED_TITLE = "测试标题 你不知道的"

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


def _fixed(seconds: float) -> LogNormal:
    return LogNormal(0.0, 0.0, seconds, seconds)


TEST_PROFILE = HumanizeProfile(
    keystroke=_fixed(0.01),
    after_type=_fixed(AFTER_TYPE),
    after_navigate=_fixed(0.02),
    before_submit=_fixed(BEFORE_SUBMIT),
    pointer_settle=_fixed(0.03),
    click_hold=_fixed(0.04),
    before_click=_fixed(0.05),
    after_click=_fixed(0.06),
    between_scroll=_fixed(0.07),
    reading=_fixed(0.08),
    after_interact=_fixed(0.09),
)


def _expression_kind(expression) -> str:
    if not isinstance(expression, str):
        return "unknown"
    if "elementFromPoint" in expression and "childFrame" not in expression:
        return "hit-test"
    if "childFrame" in expression:
        return "geometry"
    return "facts"


class _Clickable(RecordingLocator):
    """可被 ``Humanizer.click`` 坐标点击的 fake：盒模型 + 事实探测 + 命中测试。"""

    def __init__(self, name: str, *, log: list, **kwargs) -> None:
        kwargs.setdefault(
            "box", {"x": 20.0, "y": 40.0, "width": 120.0, "height": 28.0}
        )
        super().__init__(name, **kwargs)
        self._log = log
        self._page = None
        self.on_human_click = None

    async def evaluate(self, expression, arg=None):
        self.evaluate_calls.append((expression, arg))
        kind = _expression_kind(expression)
        self._log.append(("evaluate", kind, self.name))
        if kind == "hit-test":
            if self._page is not None:
                self._page.focused = self
            return {"self": True, "tag": "div", "className": "", "id": "", "text": ""}
        if kind == "geometry":
            return {
                "width": 120.0,
                "height": 28.0,
                "inside": True,
                "clipped": False,
                "childFrame": False,
            }
        return dict(FACTS)


class _ChooserDepthClickable(_Clickable):
    """封面「上传」tab fake：记录点击时的 ``chooser_depth`` 并可在点击后改 DOM。

    深度 1 = 这一下被 ``expect_file_chooser`` 消费；0 = 裸点击、系统选择器
    会留在屏幕上。``RecordingLocator.click`` 是原生 click，所以这里在
    ``super().click`` 之前取样。
    """

    def __init__(self, name: str, *, log: list, **kwargs) -> None:
        super().__init__(name, log=log, **kwargs)
        self.click_depths: list[int] = []
        self.on_click_effect = None

    async def click(self, **kwargs) -> None:
        if self._page is not None:
            self.click_depths.append(self._page.chooser_depth)
        await super().click(**kwargs)
        if self.on_click_effect is not None:
            self.on_click_effect()


class _TypingField(_Clickable):
    """持有键入缓冲的 locator；键盘事件写回当前 focus 的实例。"""

    def __init__(self, name: str, *, log: list, initial: str = "", **kwargs):
        super().__init__(name, log=log, **kwargs)
        self.buffer = initial

    async def click(self, **kwargs) -> None:
        # HUMANIZE=0 快路径走这里；真实指针路径由 hit-test 设置焦点。
        self.click_count += 1
        self.click_calls.append(dict(kwargs))
        self.actions.append(("click",))
        if self._page is not None:
            self._page.focused = self
        if self._click_error is not None:
            raise self._click_error

    async def inner_text(self) -> str:
        return self.buffer

    async def input_value(self) -> str:
        return self.buffer

    def apply_key(self, key: str) -> None:
        page = self._page
        if page is None or page.focused is not self:
            return
        if key in ("Control+a", "ControlOrMeta+A", "Control+A", "Meta+A"):
            page.selected = True
        elif key in ("Backspace", "Delete"):
            if page.selected:
                self.buffer = ""
            elif key == "Backspace":
                self.buffer = self.buffer[:-1]
            page.selected = False
        elif key == "Escape":
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
    def __init__(self, page: "_BaijiahaoPage") -> None:
        super().__init__()
        self._page = page

    async def press(self, key: str, **kwargs) -> None:
        self.actions.append(("press", key))
        self._page.apply_key(key)

    async def insert_text(self, text: str, **kwargs) -> None:
        self.actions.append(("insert_text", text))
        self._page.apply_text(text)


class _BaijiahaoPage(RecordingPage):
    """带确定顺序日志与 focus 键盘的 page double。"""

    def __init__(self, *, log: list, **kwargs) -> None:
        super().__init__(**kwargs)
        self.interactions = log
        self.mouse = _OrderedMouse(log)
        self.keyboard = _TypingKeyboard(self)
        self.focused = None
        self.selected = False

    def get_by_role(self, role: str, name=None, exact: bool = False, **kwargs):
        key = f"role:{role}" if name is None else f"role:{role}:{name}"
        if key in self._selectors:
            return self._selectors[key]
        raise UnscriptedSelectorError(
            f"page: un-scripted get_by_role({role!r}, name={name!r}, exact={exact}); "
            f"scripted: {sorted(self._selectors)}"
        )

    def apply_key(self, key: str) -> None:
        if self.focused is not None and hasattr(self.focused, "apply_key"):
            self.focused.apply_key(key)

    def apply_text(self, text: str) -> None:
        if self.focused is not None and hasattr(self.focused, "apply_text"):
            self.focused.apply_text(text)


def _attach(page: _BaijiahaoPage, locator) -> None:
    if isinstance(locator, _Clickable):
        locator._page = page
    for child in getattr(locator, "_children", {}).values():
        _attach(page, child)
    for item in getattr(locator, "_items", None) or []:
        _attach(page, item)


def _page(selectors: dict, *, log: list | None = None) -> _BaijiahaoPage:
    log = [] if log is None else log
    page = _BaijiahaoPage(log=log, selectors=selectors)
    for locator in selectors.values():
        _attach(page, locator)
    return page


class _RecordingHumanizer(Humanizer):
    """真实原语、调度顺序，零墙钟；记录点击目标与停顿名。"""

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

    def __init__(self, page, *, profile=TEST_PROFILE, rng=None, sleep=None) -> None:
        self.pauses: list[str] = []
        self.clicks: list[str] = []
        log = getattr(page, "interactions", None)
        self._log = log
        super().__init__(
            page, profile=profile, rng=random.Random(0), sleep=sleep or _noop
        )

    async def _pause(self, action) -> None:
        if not self.enabled:
            return
        for name in self._PROFILE_PAUSES:
            if action == getattr(self.profile, name):
                self.pauses.append(name)
                if self._log is not None:
                    self._log.append(("pause", name))
                return
        raise AssertionError("unknown pause action")

    async def click(self, locator, *, point=None) -> None:
        self.clicks.append(getattr(locator, "name", "?"))
        await super().click(locator, point=point)
        if getattr(locator, "on_human_click", None) is not None:
            locator.on_human_click()


async def _noop(seconds: float) -> None:
    return None


def _downs_after(log: list, marker) -> int:
    """``marker`` 之后第一次 ``mouse.down`` 的下标（证明 stillOn 先于派发）。"""
    start = log.index(marker)
    for index in range(start + 1, len(log)):
        if log[index] == ("down",):
            return index
    raise AssertionError(f"no mouse.down after {marker!r}")


def _video(**overrides) -> BaiJiaHaoVideo:
    values = {
        "title": "测试标题",
        "file_path": "demo.mp4",
        "tags": [],
        "account_file": "cookies/baijiahao_uploader/account.json",
        "thumbnail_path": "cover.png",
    }
    values.update(overrides)
    return BaiJiaHaoVideo(**values)


# ---------------------------------------------------------------------------
# 1. 事件序列
# ---------------------------------------------------------------------------


class BaijiahaoEventSequenceTests(unittest.TestCase):
    def test_title_keeps_the_clearing_sequence_then_types_per_character(self):
        log: list = []
        title = _TypingField("title-editor", log=log, initial="旧文件名.mp4")
        page = _page({TITLE_EDITOR_SELECTOR: title}, log=log)

        with patch.object(baijiahao_main, "Humanizer", _RecordingHumanizer):
            app = _video()
            humanizer = app._humanizer(page)
            asyncio.run(app._fill_title(page, humanizer))

        # 保留的手写清空序列：Ctrl+A → Backspace（只把键换成 humanizer.press）。
        self.assertEqual(
            page.keyboard.actions[:2],
            [("press", "Control+a"), ("press", "Backspace")],
        )
        # 非 ASCII 逐字 insert_text；空格是 ASCII 可打印字符，走真实按键。
        self.assertIn(("insert_text", "测"), page.keyboard.actions)
        self.assertIn(("insert_text", "的"), page.keyboard.actions)
        self.assertIn(("press", " "), page.keyboard.actions)
        # 零 fill / type / 剪贴板。
        self.assertEqual([a for a in title.actions if a[0] == "fill"], [])
        self.assertEqual([a for a in page.keyboard.actions if a[0] == "type"], [])
        # 标题只有一次 after_type。
        self.assertEqual(humanizer.pauses.count("after_type"), 1)
        # 聚焦标题是一次坐标点击：hit-test 先于 down，且零原生 click。
        self.assertEqual(title.click_count, 0)
        self.assertEqual(page.mouse.down_count, 1)
        hit = ("evaluate", "hit-test", "title-editor")
        self.assertLess(log.index(hit), _downs_after(log, hit))

    def test_cover_entry_and_crop_confirm_click_through_the_pointer(self):
        log: list = []
        cover_entry = _Clickable("cover-entry", log=log)
        upload_tab = _Clickable("cover-upload-tab", log=log)
        image_input = FakeLocator("cover-image-input")
        confirm = _Clickable("cover-confirm", log=log)
        page = _page(
            {
                COVER_ENTRY_SELECTOR: cover_entry,
                COVER_UPLOAD_BUTTON_SELECTOR: upload_tab,
                COVER_IMAGE_INPUT_SELECTOR: image_input,
                COVER_CONFIRM_SELECTOR: confirm,
            },
            log=log,
        )

        with patch.object(baijiahao_main, "Humanizer", _RecordingHumanizer):
            app = _video()
            humanizer = app._humanizer(page)
            asyncio.run(app._upload_thumbnail(page, humanizer))

        # 「选择封面」与裁剪确认是坐标点击；弹窗里已有隐藏 input，直接写，
        # 既不点「上传」tab，也不拉起系统文件选择器（先例：小红书 bbc5361）。
        self.assertEqual(cover_entry.click_count, 0)
        self.assertEqual(confirm.click_count, 0)
        self.assertEqual(upload_tab.click_count, 0)
        self.assertEqual(page.expect_file_chooser_calls, 0)
        self.assertEqual(image_input.files, ["cover.png"])
        self.assertEqual(page.mouse.down_count, 2)
        # 两次坐标点击都先过 stillOn。
        hit_tests = [event for event in log if event[:2] == ("evaluate", "hit-test")]
        self.assertEqual(len(hit_tests), 2)
        self.assertLess(log.index(hit_tests[0]), _downs_after(log, hit_tests[0]))
        self.assertLess(log.index(hit_tests[1]), _downs_after(log, hit_tests[1]))
        for target in (cover_entry, confirm):
            for call in target.click_calls:
                self.assertNotIn("force", call)

    def test_cover_upload_tab_is_clicked_inside_the_file_chooser(self):
        log: list = []
        cover_entry = _Clickable("cover-entry", log=log)
        upload_tab = _ChooserDepthClickable("cover-upload-tab", log=log)
        image_input = FakeLocator("cover-image-input", count=0)
        confirm = _Clickable("cover-confirm", log=log)
        page = _page(
            {
                COVER_ENTRY_SELECTOR: cover_entry,
                COVER_UPLOAD_BUTTON_SELECTOR: upload_tab,
                COVER_IMAGE_INPUT_SELECTOR: image_input,
                COVER_CONFIRM_SELECTOR: confirm,
            },
            log=log,
        )
        upload_tab._page = page

        with patch.object(baijiahao_main, "Humanizer", _RecordingHumanizer):
            app = _video()
            humanizer = app._humanizer(page)
            asyncio.run(app._upload_thumbnail(page, humanizer))

        # input 缺失才点「上传」tab，且这一下必须被 expect_file_chooser 消费
        # （深度 1），不是裸点击（深度 0）。
        self.assertEqual(page.expect_file_chooser_calls, 1)
        self.assertEqual(upload_tab.click_depths, [1])
        self.assertIsNone(upload_tab.click_calls[0].get("force"))
        self.assertEqual(page.file_chooser_files(), ["cover.png"])
        self.assertEqual(page.chooser_depth, 0)
        self.assertNotIn("set_input_files", [a[0] for a in image_input.actions])

    def test_cover_input_is_written_when_no_file_chooser_arrives(self):
        log: list = []
        cover_entry = _Clickable("cover-entry", log=log)
        upload_tab = _ChooserDepthClickable("cover-upload-tab", log=log)
        image_input = FakeLocator("cover-image-input", count=0)
        confirm = _Clickable("cover-confirm", log=log)
        page = _page(
            {
                COVER_ENTRY_SELECTOR: cover_entry,
                COVER_UPLOAD_BUTTON_SELECTOR: upload_tab,
                COVER_IMAGE_INPUT_SELECTOR: image_input,
                COVER_CONFIRM_SELECTOR: confirm,
            },
            log=log,
        )
        upload_tab._page = page
        page.fail_file_chooser = PWTimeoutError("no file chooser")
        upload_tab.on_click_effect = lambda: setattr(image_input, "_count", 1)

        with patch.object(baijiahao_main, "Humanizer", _RecordingHumanizer):
            app = _video()
            humanizer = app._humanizer(page)
            asyncio.run(app._upload_thumbnail(page, humanizer))

        self.assertEqual(page.expect_file_chooser_calls, 1)
        self.assertEqual(page.file_chooser_files(), [])
        self.assertEqual(image_input.files, ["cover.png"])

    def test_declaration_clicks_the_component_body_without_force(self):
        log: list = []
        component = _Clickable("declaration-component", log=log)
        antd_layer = FakeLocator("antd-decorative-input")
        ai_option = _Clickable("ai-option", log=log)
        confirm = _Clickable("declaration-confirm", log=log)
        modal = FakeLocator(
            "declaration-modal",
            children={DECLARATION_CONFIRM_SELECTOR: confirm},
        )
        page = _page(
            {
                AI_DECLARATION_TRIGGER_SELECTOR: component,
                'input[placeholder="请选择创作声明"]': antd_layer,
                AI_DECLARATION_OPTION_SELECTOR: ai_option,
                DECLARATION_MODAL_SELECTOR: modal,
            },
            log=log,
        )

        with patch.object(baijiahao_main, "Humanizer", _RecordingHumanizer):
            app = _video()
            humanizer = app._humanizer(page)
            asyncio.run(app._check_ai_declaration(page, humanizer))

        # 点组件本体，装饰层 input 一次都没被点。
        self.assertEqual(component.click_count, 0)
        self.assertEqual(antd_layer.click_count, 0)
        self.assertEqual(ai_option.click_count, 0)
        self.assertEqual(confirm.click_count, 0)
        self.assertEqual(page.mouse.down_count, 3)
        for target in (component, ai_option, confirm):
            for call in target.click_calls:
                self.assertNotIn("force", call)

    def test_collection_typing_then_exact_option_click(self):
        log: list = []
        search = _TypingField("collection-search", log=log)
        select_box = _Clickable(
            "collection-select",
            log=log,
            children={COLLECTION_SEARCH_INPUT_SELECTOR: search},
        )
        exact = _Clickable("collection-exact", log=log, text="我的合集")
        other = _Clickable("collection-other", log=log, text="我的合集二期")
        options = FakeLocator("collection-options", items=[exact, other])
        page = _page(
            {COLLECTION_SELECTOR: select_box, COLLECTION_OPTION_SELECTOR: options},
            log=log,
        )

        with patch.object(baijiahao_main, "Humanizer", _RecordingHumanizer):
            app = _video(collection_name="我的合集")
            humanizer = app._humanizer(page)
            asyncio.run(app._apply_collection(page, humanizer))

        # 逐字输入（4 个非 ASCII 字符 → 4 次 insert_text，一次 after_type）。
        inserts = [a for a in page.keyboard.actions if a[0] == "insert_text"]
        self.assertEqual(
            inserts,
            [
                ("insert_text", "我"),
                ("insert_text", "的"),
                ("insert_text", "合"),
                ("insert_text", "集"),
            ],
        )
        self.assertEqual(humanizer.pauses.count("after_type"), 1)
        # 全等命中项是唯一被坐标点击的候选；子串命中的「我的合集二期」未触碰。
        self.assertEqual(page.mouse.down_count, 3)  # 开下拉 + 聚焦搜索框 + 候选项
        self.assertTrue(exact.evaluate_calls)
        self.assertEqual(other.evaluate_calls, [])
        self.assertEqual(exact.click_count, 0)
        self.assertEqual(other.click_count, 0)

    def test_publish_waits_before_submit_and_never_forces(self):
        log: list = []
        publish_btn = _Clickable("publish-button", log=log)

        page = _page(
            {
                PUBLISH_BUTTON_SELECTOR: publish_btn,
                DECLARATION_MODAL_SELECTOR: FakeLocator("modal", count=0),
            },
            log=log,
        )
        page.url = "https://baijiahao.baidu.com/builder/rc/edit?type=videoV2"

        def _after_publish() -> None:
            page.url = BAIJIAHAO_SUCCESS_URL_PREFIX + "/list"

        publish_btn.on_human_click = _after_publish

        with patch.object(baijiahao_main, "Humanizer", _RecordingHumanizer):
            app = _video()
            app.start_publish_budget()
            humanizer = app._humanizer(page)
            asyncio.run(app._submit_publish(page, humanizer=humanizer))

        self.assertEqual(publish_btn.click_count, 0)
        self.assertEqual(page.mouse.down_count, 1)
        self.assertIn("before_submit", humanizer.pauses)
        self.assertLess(
            log.index(("pause", "before_submit")), log.index(("down",))
        )
        for call in publish_btn.click_calls:
            self.assertNotIn("force", call)


# ---------------------------------------------------------------------------
# 1b. 发布点击：可能已派发 → 结果未知，绝不二次派发
# ---------------------------------------------------------------------------


class _PublishFailingHumanizer(_RecordingHumanizer):
    """真实点击后按 locator 名注入异常（模拟 ``mouse.down`` 之后的失败）。"""

    def __init__(self, page, *, error: BaseException, target: str = "publish-button") -> None:
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

    def _page(self):
        log: list = []
        publish_btn = _Clickable("publish-button", log=log)
        page = _page(
            {
                PUBLISH_BUTTON_SELECTOR: publish_btn,
                DECLARATION_MODAL_SELECTOR: FakeLocator("modal", count=0),
            },
            log=log,
        )
        page.url = "https://baijiahao.baidu.com/builder/rc/edit?type=videoV2"
        return page, publish_btn

    def test_publish_after_mouse_down_maps_to_unknown(self):
        page, publish_btn = self._page()
        app = _video()
        app.start_publish_budget()
        humanizer = _PublishFailingHumanizer(page, error=self._maybe_error())

        with self.assertRaises(PublishResultUnknownError):
            asyncio.run(app._submit_publish(page, humanizer=humanizer))

        self.assertEqual(humanizer.dispatches, ["publish-button"])
        self.assertEqual(publish_btn.click_count, 0)

    def test_pre_dispatch_publish_failure_propagates(self):
        page, publish_btn = self._page()
        app = _video()
        app.start_publish_budget()
        error = ElementUnusableError(
            what="点击目标",
            role="interactive",
            selector="",
            reason="covered-by:mask",
            publish_clicked=False,
        )
        humanizer = _PublishFailingHumanizer(page, error=error)

        with self.assertRaises(ElementUnusableError) as caught:
            asyncio.run(app._submit_publish(page, humanizer=humanizer))

        self.assertIs(caught.exception, error)
        self.assertEqual(publish_btn.click_count, 0)


class LoginRedirectPublishAttemptTests(unittest.TestCase):
    """发布点击之后的登录跳转必须带 ``publish_attempted=True``（退出 10 不撒谎）。"""

    def test_pre_click_redirect_is_not_marked_as_dispatched(self):
        page = SimpleNamespace(url="https://passport.baidu.com/v2/?login")

        with self.assertRaises(LoginRequiredError) as caught:
            baijiahao_main._raise_if_login_required(page)

        self.assertFalse(caught.exception.publish_attempted)

    def test_post_click_poll_marks_the_redirect_as_dispatched(self):
        log: list = []
        publish_btn = _Clickable("publish-button", log=log)
        page = _page(
            {
                PUBLISH_BUTTON_SELECTOR: publish_btn,
                DECLARATION_MODAL_SELECTOR: FakeLocator("modal", count=0),
            },
            log=log,
        )
        page.url = "https://baijiahao.baidu.com/builder/rc/edit?type=videoV2"

        class _Redirecting(_RecordingHumanizer):
            async def click(self, locator, *, point=None) -> None:
                await super().click(locator, point=point)
                page.url = "https://passport.baidu.com/v2/?login"

        with patch.object(baijiahao_main, "Humanizer", _Redirecting):
            app = _video()
            app.start_publish_budget()
            humanizer = app._humanizer(page)
            with self.assertRaises(LoginRequiredError) as caught:
                asyncio.run(
                    app._submit_publish(page, multilogin=True, humanizer=humanizer)
                )

        self.assertTrue(caught.exception.publish_attempted)


class SecurityVerificationAfterPublishTests(unittest.TestCase):
    """发布点击之后的「百度安全验证」不得落回「未发布」的失败路径。"""

    def _page(self):
        log: list = []
        publish_btn = _Clickable("publish-button", log=log)
        page = _page(
            {
                PUBLISH_BUTTON_SELECTOR: publish_btn,
                DECLARATION_MODAL_SELECTOR: FakeLocator("modal", count=0),
                'text="百度安全验证"': FakeLocator("security-check", count=1),
            },
            log=log,
        )
        page.url = "https://baijiahao.baidu.com/builder/rc/edit?type=videoV2"
        return page

    def test_security_verification_after_publish_is_marked_as_dispatched(self):
        page = self._page()

        with patch.object(baijiahao_main, "Humanizer", _RecordingHumanizer):
            app = _video()
            app.start_publish_budget()
            humanizer = app._humanizer(page)
            with self.assertRaises(LoginRequiredError) as caught:
                asyncio.run(
                    app._submit_publish(page, multilogin=True, humanizer=humanizer)
                )

        self.assertTrue(caught.exception.publish_attempted)

    def test_local_security_verification_after_publish_is_result_unknown(self):
        page = self._page()

        with patch.object(baijiahao_main, "Humanizer", _RecordingHumanizer):
            app = _video()
            app.start_publish_budget()
            humanizer = app._humanizer(page)
            with self.assertRaises(PublishResultUnknownError):
                asyncio.run(app._submit_publish(page, humanizer=humanizer))


# ---------------------------------------------------------------------------
# 1b. 封面兜底：chooser 超时才降级，人类化点击失败必须上抛
# ---------------------------------------------------------------------------


class BaijiahaoCoverChooserFallbackTests(unittest.TestCase):
    def _cover_page(
        self,
        *,
        image_count: int = 1,
        generic_count: int = 0,
        upload_click_error: BaseException | None = None,
    ):
        log: list = []
        cover_entry = _Clickable("cover-entry", log=log)
        upload_tab = _ChooserDepthClickable(
            "cover-upload-tab", log=log, click_error=upload_click_error
        )
        image_input = FakeLocator("cover-image-input", count=image_count)
        confirm = _Clickable("cover-confirm", log=log)
        page = _page(
            {
                COVER_ENTRY_SELECTOR: cover_entry,
                COVER_UPLOAD_BUTTON_SELECTOR: upload_tab,
                COVER_IMAGE_INPUT_SELECTOR: image_input,
                COVER_CONFIRM_SELECTOR: confirm,
                'input[type="file"]': FakeLocator(
                    "generic-file", count=generic_count
                ),
            },
            log=log,
        )
        upload_tab._page = page
        return page, upload_tab, image_input, confirm

    def test_cover_entry_never_binds_the_page_wide_file_input(self):
        # A page-scope ``input[type=file]`` exists and is the page's video
        # input: the cover step must never bind it.
        page, upload_tab, image_input, _confirm = self._cover_page(
            image_count=0, generic_count=1
        )
        generic = page.locator('input[type="file"]')

        with patch.object(baijiahao_main, "Humanizer", _RecordingHumanizer):
            app = _video()
            humanizer = app._humanizer(page)
            asyncio.run(app._upload_thumbnail(page, humanizer))

        self.assertEqual(generic.actions, [])
        self.assertEqual(image_input.actions, [])
        self.assertEqual(page.expect_file_chooser_calls, 1)
        self.assertEqual(upload_tab.click_depths, [1])

    def test_missing_cover_input_after_a_chooser_timeout_raises(self):
        page, _upload_tab, image_input, _confirm = self._cover_page(
            image_count=0
        )
        page.fail_file_chooser = PWTimeoutError("no file chooser event")

        with patch.object(baijiahao_main, "Humanizer", _RecordingHumanizer):
            app = _video()
            humanizer = app._humanizer(page)
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(app._upload_cover_via_chooser(page, humanizer))

        self.assertIn("封面图片 input", str(ctx.exception))
        self.assertEqual(image_input.actions, [])
        self.assertEqual(page.file_chooser_files(), [])

    def test_humanize_failure_during_the_tab_click_propagates(self):
        unusable = ElementUnusableError(
            what="上传", role="interactive", reason="covered-by:div.mask"
        )
        page, _upload_tab, image_input, _confirm = self._cover_page(
            upload_click_error=unusable
        )

        with patch.object(baijiahao_main, "Humanizer", _RecordingHumanizer):
            app = _video()
            humanizer = app._humanizer(page)
            with self.assertRaises(ElementUnusableError):
                asyncio.run(app._upload_cover_via_chooser(page, humanizer))

        self.assertEqual(image_input.actions, [])
        self.assertEqual(page.file_chooser_files(), [])


# ---------------------------------------------------------------------------
# 2. 字段值读回
# ---------------------------------------------------------------------------


class BaijiahaoFieldValueTests(unittest.TestCase):
    def test_auto_filled_file_name_is_fully_replaced(self):
        log: list = []
        title = _TypingField("title-editor", log=log, initial="口播视频.mp4")
        page = _page({TITLE_EDITOR_SELECTOR: title}, log=log)

        with patch.object(baijiahao_main, "Humanizer", _RecordingHumanizer):
            app = _video()
            humanizer = app._humanizer(page)
            asyncio.run(app._fill_title(page, humanizer))

        self.assertEqual(title.buffer, PADDED_TITLE)
        self.assertNotIn(".mp4", title.buffer)

    def test_collection_candidate_is_matched_exactly(self):
        log: list = []
        search = _TypingField("collection-search", log=log)
        select_box = _Clickable(
            "collection-select",
            log=log,
            children={COLLECTION_SEARCH_INPUT_SELECTOR: search},
        )
        exact = _Clickable("collection-exact", log=log, text="我的合集")
        verbose = _Clickable("collection-verbose", log=log, text="我的合集 第二季")
        options = FakeLocator("collection-options", items=[exact, verbose])
        page = _page(
            {COLLECTION_SELECTOR: select_box, COLLECTION_OPTION_SELECTOR: options},
            log=log,
        )

        with patch.object(baijiahao_main, "Humanizer", _RecordingHumanizer):
            app = _video(collection_name="我的合集")
            humanizer = app._humanizer(page)
            asyncio.run(app._apply_collection(page, humanizer))

        self.assertEqual(search.buffer, "我的合集")
        self.assertTrue(exact.evaluate_calls)
        self.assertEqual(verbose.evaluate_calls, [])
        self.assertEqual(page.mouse.down_count, 3)

    def test_collection_miss_skips_without_selecting_or_raising(self):
        log: list = []
        search = _TypingField("collection-search", log=log)
        select_box = _Clickable(
            "collection-select",
            log=log,
            children={COLLECTION_SEARCH_INPUT_SELECTOR: search},
        )
        unrelated = _Clickable("collection-unrelated", log=log, text="别人的合集")
        options = FakeLocator("collection-options", items=[unrelated])
        page = _page(
            {COLLECTION_SELECTOR: select_box, COLLECTION_OPTION_SELECTOR: options},
            log=log,
        )

        with patch.object(baijiahao_main, "Humanizer", _RecordingHumanizer):
            app = _video(collection_name="我的合集")
            humanizer = app._humanizer(page)
            # 不抛异常：合集缺失只降级跳过，不中止发布。
            asyncio.run(app._apply_collection(page, humanizer))

        self.assertEqual(unrelated.evaluate_calls, [])
        self.assertEqual(page.mouse.down_count, 2)  # 开下拉 + 聚焦搜索框
        # 跳过策略保留：按 Escape 收起下拉，而不是选中一个不相干的合集。
        self.assertIn(("press", "Escape"), page.keyboard.actions)


# ---------------------------------------------------------------------------
# 3. 静态门 + HUMANIZE=0 + 实例缓存
# ---------------------------------------------------------------------------


class BaijiahaoStaticGateTests(unittest.TestCase):
    def test_baijiahao_package_passes_humanize_gates_a_to_e(self):
        assert_clean(PACKAGE)

    def test_no_fill_js_click_or_force_remains_in_the_package(self):
        source = (PACKAGE / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("el.click()", source)
        self.assertNotIn("force=True", source)
        self.assertNotIn(".fill(", source)


class BaijiahaoHumanizeDisabledTests(unittest.TestCase):
    def test_humanize_zero_uses_one_insert_and_native_clicks(self):
        log: list = []
        title = _TypingField("title-editor", log=log, initial="旧文件名.mp4")
        page = _page({TITLE_EDITOR_SELECTOR: title}, log=log)

        def _after_publish() -> None:
            page.url = BAIJIAHAO_SUCCESS_URL_PREFIX + "/list"

        publish_btn = _Clickable("publish-button", log=log)
        publish_btn.on_human_click = _after_publish
        page._selectors[PUBLISH_BUTTON_SELECTOR] = publish_btn
        page._selectors[DECLARATION_MODAL_SELECTOR] = FakeLocator("modal", count=0)
        _attach(page, publish_btn)

        with patch.dict(os.environ, {"HUMANIZE": "0"}):
            with patch.object(baijiahao_main, "Humanizer", _RecordingHumanizer):
                app = _video()
                app.start_publish_budget()
                humanizer = app._humanizer(page)
                self.assertFalse(humanizer.enabled)
                asyncio.run(app._fill_title(page, humanizer))
                asyncio.run(app._submit_publish(page, humanizer=humanizer))

        # 语义切换：文本一次整段 insert_text，点击一次原生 locator.click。
        self.assertEqual(
            [a for a in page.keyboard.actions if a[0] == "insert_text"],
            [("insert_text", PADDED_TITLE)],
        )
        # 清空序列仍按键（press 不看 enabled），但不逐字、不停顿。
        self.assertEqual(
            [a for a in page.keyboard.actions if a[0] == "press"][:2],
            [("press", "Control+a"), ("press", "Backspace")],
        )
        self.assertEqual(title.click_count, 1)
        self.assertEqual(publish_btn.click_count, 1)
        self.assertEqual(page.mouse.actions, [])
        self.assertEqual(humanizer.pauses, [])

    def test_humanizer_is_cached_per_page(self):
        first = _page({})
        second = _page({})
        app = _video()

        with patch.object(baijiahao_main, "Humanizer", _RecordingHumanizer):
            one = app._humanizer(first)
            self.assertIs(one, app._humanizer(first))
            self.assertIsNot(one, app._humanizer(second))

    def test_upload_in_builds_the_humanizer_right_after_the_page(self):
        page = _page(
            {
                'input[type="file"][accept*="video"], '
                'input[type="file"][accept*="mp4"]': FakeLocator("video-input"),
                TITLE_EDITOR_SELECTOR: FakeLocator("title-editor"),
            }
        )
        context = MagicMock()
        context.new_page = AsyncMock(return_value=page)
        session = BrowserSession(
            browser=MagicMock(), context=context, mode="local"
        )
        app = _video()

        step_names = [
            "_fill_title",
            "_wait_upload_complete",
            "_upload_thumbnail",
            "_check_ai_declaration",
            "_apply_collection",
        ]
        with patch.object(baijiahao_main, "Humanizer", _RecordingHumanizer):
            with patch.object(app, "_submit_publish", AsyncMock()) as submit:
                mocks = {
                    name: patch.object(app, name, AsyncMock())
                    for name in step_names
                }
                started = {name: mock.start() for name, mock in mocks.items()}
                try:
                    asyncio.run(app.upload_in(session))
                finally:
                    for mock in mocks.values():
                        mock.stop()

        humanizer = app._humanizer_instance
        self.assertIs(humanizer.page, page)
        for name in step_names:
            call = started[name].await_args
            self.assertIs(call.args[0], page, name)
            if name == "_wait_upload_complete":
                # 只读等待不碰人工交互层。
                self.assertEqual(call.kwargs, {"multilogin": False}, name)
            else:
                self.assertIs(call.args[1], humanizer, name)
        self.assertEqual(
            submit.await_args.kwargs, {"multilogin": False}
        )


if __name__ == "__main__":
    unittest.main()
