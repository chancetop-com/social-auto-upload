# -*- coding: utf-8 -*-
"""微博：双实例 + 比例落点发布的人类化交互层（工单 11，spec §3.11）。

三块离线证据（spec §6.2）：

1. **事件序列** —— 标题 / 描述 / 新建合集名走 ``sel``（click → ControlOrMeta+A
   → Delete → type_text），逐字（ASCII ``press`` / 非 ASCII ``insert_text``）；
   类型 / 声明 / 合集开关 / 发布 / 二次确认全部走 ``Humanizer.click``，``stillOn``
   hit-test 先于 ``mouse.down``，零原生 ``locator.click``、零 ``force``、零 JS
   ``el.click()``。
2. **字段值读回** —— fake keyboard 持有每个字段的键入缓冲，断言最终值等于预期
   （抓「清空不净导致追加」与 ``#tag#`` 被抹掉）。
3. **静态门** —— ``tests.humanize_gates.assert_clean`` 在微博包上跑 A–E。

另加：首页 page 与 popup 发布 page 各持一个实例（跨页不复用）；发布按钮落点
``(0.65,0.5)`` → ``(0.35,0.5)`` 的单次重试与「已派发 / 可能已派发不重试」；
封面「完成」只点一次；``HUMANIZE=0`` 语义切换。
"""

from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from tests.fakes_xhs_dom import (
    FakeLocator,
    RecordingKeyboard,
    RecordingMouse,
    RecordingPage,
    UnscriptedSelectorError,
)
from tests.humanize_gates import assert_clean
from uploader.weibo_uploader import main as weibo_main
from uploader.weibo_uploader.main import WeiBoVideo
from utils.browser_session import BrowserSession
from utils.dom import ElementUnusableError
from utils.errors import LoginRequiredError, PublishResultUnknownError
from utils.humanize import MAYBE_DISPATCHED, MAYBE_DISPATCHED_VALUE, Humanizer
from uploader.publish_timeout import PublishTimeoutBudget

PACKAGE = Path(__file__).resolve().parent.parent / "uploader" / "weibo_uploader"

TITLE_PLACEHOLDER = "填写标题（0～30个字）"
DESC_PLACEHOLDER = "有什么新鲜事想分享给大家？"

VIDEO_ENTRY = "span"
TYPE_LABEL = 'label.woo-radio-main:has(span.woo-radio-text:text-is("二创"))'
TYPE_CHECKED = TYPE_LABEL + " span.woo-radio-checked"
DECLARATION_TRIGGER = 'div[class*="_gap1_nsgmr"] .woo-pop-ctrl'
DECLARATION_PANEL = 'div[class*="_panel_nsgmr"]'
AI_OPTION = 'button:has(span:text-is("含AI生成内容"))'
AI_CHECK_ACTIVE = '[class*="_checkActive"]'
DECLARATION_CONFIRM = 'div[class*="_footer_nsgmr"] button:has(span:text-is("确定"))'

SWITCH_BLOCK = 'div[class*="_switch_"]:has(div[class*="_tit1_"]:text-is("合集"))'
SWITCH_INPUT = "label.woo-switch-main input.woo-switch-input"
SWITCH_SPAN = 'label.woo-switch-main span[role="switch"]'
SWITCH_LABEL = "label.woo-switch-main"
COLLECTION_PANEL = 'div[class*="_scroll_"]:has(div[class*="_add_"])'
COLLECTION_ROWS = 'div[class*="_top2_"]'
ADD_BUTTON = 'div[class*="_add_"]:has-text("新建合集")'
NEW_COLLECTION_INPUT = 'div[class*="_top2_"] input[type="text"]:not([disabled])'

PUBLISH_BUTTON = 'div[class*="_check_2z30i"] button:has(span:text-is("发布"))'
AGAIN_BUTTON = 'button:has(span:text-is("再发一条视频"))'
SUCCESS_LAYER = 'div[class*="_layer1_9a8j7"]'

UPLOAD_LINK = "role:link:上传封面"
COVER_LAYER = 'div.wbpro-layer:has(div:text-is("编辑封面"))'
COVER_INPUT = 'input[type="file"][accept*="jpg"]'
COVER_BLOB = '.cropper-container img[src^="blob:"], .wb_cropper img[src^="blob:"]'
COVER_FINISH = 'div.wbpro-layer-btn button:has(span:text-is("完成"))'
MAIN_FORM = 'div.wbpro-layer[class*="_layer_19x8d"]'

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
    "contentEditable": None,
    "readOnly": False,
    "isConnected": True,
}


class Timeline:
    """Shared ordering log for keyboard / mouse / hit-test events."""

    def __init__(self) -> None:
        self.events: list[str] = []

    def add(self, name: str) -> None:
        self.events.append(name)

    def kinds(self) -> list[str]:
        return list(self.events)

    def count(self, name: str) -> int:
        return self.events.count(name)


class BufferKeyboard(RecordingKeyboard):
    """Owns one typed buffer per field so readback catches wrong values.

    ``RecordingHumanizer.click`` calls :meth:`focus`, which mirrors what a real
    click does: subsequent keystrokes land in that field.
    """

    def __init__(self, timeline: Timeline | None = None) -> None:
        super().__init__()
        self._timeline = timeline
        self.buffers: dict[str, str] = {}
        self.active: str | None = None
        self._selected = False

    def focus(self, name: str) -> None:
        self.active = name
        self.buffers.setdefault(name, "")
        self._selected = False

    def _record(self, action: tuple) -> None:
        self.actions.append(action)
        if self._timeline is not None:
            self._timeline.add("keyboard")

    def _write(self, text: str) -> None:
        if self.active is None:
            return
        if self._selected:
            self.buffers[self.active] = ""
            self._selected = False
        self.buffers[self.active] += text

    async def press(self, key: str, **kwargs) -> None:
        self._record(("press", key))
        if key in ("ControlOrMeta+A", "Control+A"):
            self._selected = True
        elif key == "Delete":
            if self.active is not None and self._selected:
                self.buffers[self.active] = ""
            self._selected = False
        elif key == "Enter":
            self._write("\n")
        elif len(key) == 1:
            self._write(key)

    async def insert_text(self, text: str, **kwargs) -> None:
        self._record(("insert_text", text))
        self._write(text)


class Element(FakeLocator):
    """Clickable locator double: box + geometry facts + scripted hit-tests.

    ``hit_results`` is consumed in order (last value sticks); ``on_human_click``
    lets a test model "clicking this control changes page state".
    """

    def __init__(
        self,
        name: str,
        *,
        timeline: Timeline | None = None,
        box: dict[str, float] | None = None,
        hit_results: list[bool] | None = None,
        on_human_click=None,
        visible: bool | None = True,
        **kwargs,
    ) -> None:
        super().__init__(
            name,
            computed_style=dict(FACTS),
            box=box or {"x": 20.0, "y": 40.0, "width": 160.0, "height": 32.0},
            **kwargs,
        )
        self.timeline = timeline
        self.hit_results = list(hit_results or [True])
        self.on_human_click = on_human_click
        self.visible_flag = visible
        self.hit_points: list[tuple[float, float] | None] = []
        self.scroll_calls = 0

    # -- geometry / hit-test ------------------------------------------------
    async def evaluate(self, expression, arg=None):
        self.evaluate_calls.append((expression, arg))
        text = str(expression)
        if "elementFromPoint" in text:
            point = tuple(arg) if isinstance(arg, (list, tuple)) else None
            self.hit_points.append(point)
            if self.timeline is not None:
                self.timeline.add("hit-test")
            result = (
                self.hit_results.pop(0)
                if len(self.hit_results) > 1
                else self.hit_results[0]
            )
            if result:
                return {"self": True, "tag": "div", "className": "", "id": "", "text": ""}
            return {
                "self": False,
                "tag": "div",
                "className": "cover-mask",
                "id": "",
                "text": "",
            }
        if "getBoundingClientRect" in text:
            return {
                "width": self._box["width"],
                "height": self._box["height"],
                "inside": True,
                "clipped": False,
                "childFrame": False,
            }
        return dict(FACTS)

    async def is_visible(self) -> bool:
        if self.visible_flag is None:
            return await super().is_visible()
        return bool(self.visible_flag)

    async def scroll_into_view_if_needed(self, **kwargs) -> None:
        self.scroll_calls += 1


class CheckableInput(FakeLocator):
    """Switch/checkbox input double backed by a mutable state dict."""

    def __init__(self, name: str, state: dict) -> None:
        super().__init__(name)
        self.state = state

    async def is_checked(self) -> bool:
        return bool(self.state["checked"])


class PopupInfo:
    """``page.expect_popup()`` async context manager double."""

    def __init__(self, page) -> None:
        self._page = page

    async def __aenter__(self) -> "PopupInfo":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    @property
    def value(self):
        async def _resolve():
            return self._page

        return _resolve()


class WeiboPage(RecordingPage):
    """RecordingPage with the two extra lookups the Weibo flow needs."""

    def __init__(self, *, selectors=None, **kwargs) -> None:
        super().__init__(selectors=selectors, **kwargs)
        self.popup_page = None
        self.keyboard = BufferKeyboard()
        self.mouse = RecordingMouse()

    def get_by_placeholder(self, text: str) -> FakeLocator:
        key = f"placeholder:{text}"
        try:
            return self._selectors[key]
        except KeyError as exc:
            raise UnscriptedSelectorError(
                f"page: un-scripted get_by_placeholder({text!r}); "
                f"scripted: {sorted(self._selectors)}"
            ) from exc

    def expect_popup(self, *, timeout: float | int | None = None):
        self._record_wait("expect_popup", timeout)
        return PopupInfo(self.popup_page)


class RecordingHumanizer(Humanizer):
    """Real sequencing, zero wall-clock pauses, records click targets/points."""

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

    def __init__(self, page, **kwargs) -> None:
        super().__init__(page, **kwargs)
        self.pauses: list[str] = []
        self.clicks: list[str] = []
        self.points: list[tuple[float, float] | None] = []

    async def _pause(self, action) -> None:
        if not self.enabled:
            return
        for name in self._PROFILE_PAUSES:
            if action is getattr(self.profile, name):
                self.pauses.append(name)
                return

    async def click(self, locator, *, point=None) -> None:
        self.clicks.append(locator.name)
        self.points.append(point)
        keyboard = self.page.keyboard
        focus = getattr(keyboard, "focus", None)
        if focus is not None:
            focus(locator.name)
        hook = getattr(locator, "on_human_click", None)
        if hook is not None:
            hook()
        await super().click(locator, point=point)

    def pause_count(self, name: str) -> int:
        return self.pauses.count(name)


class ExplodingMouse(RecordingMouse):
    """``mouse.down`` raises: the click may already be dispatched."""

    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error

    async def down(self, **kwargs) -> None:
        await super().down(**kwargs)
        raise self.error


def _video(**kwargs) -> WeiBoVideo:
    params = {
        "title": "标题一",
        "file_path": "demo.mp4",
        "tags": [],
        "account_file": None,
        "thumbnail_path": "cover.jpg",
    }
    params.update(kwargs)
    return WeiBoVideo(**params)


def _publish_page(*, hit_results=None) -> tuple[WeiboPage, Element]:
    publish = Element("publish", hit_results=hit_results)
    page = WeiboPage(
        selectors={
            PUBLISH_BUTTON: publish,
            AGAIN_BUTTON: FakeLocator("again", visible=True),
            SUCCESS_LAYER: FakeLocator("success-layer", visible=False),
        }
    )
    return page, publish


# ---------------------------------------------------------------------------
# 1. Event sequence
# ---------------------------------------------------------------------------


class WeiboEventSequenceTests(unittest.TestCase):
    def test_title_and_description_use_sel_clear_then_per_character_typing(self):
        timeline = Timeline()
        title = Element("title", timeline=timeline)
        desc = Element("description", timeline=timeline)
        page = WeiboPage(
            selectors={
                f"placeholder:{TITLE_PLACEHOLDER}": title,
                f"placeholder:{DESC_PLACEHOLDER}": desc,
            }
        )

        with patch.object(weibo_main, "Humanizer", RecordingHumanizer):
            app = _video(desc="正文", tags=["a"])
            humanizer = app._humanizer(page)
            asyncio.run(app._fill_title(page, humanizer))
            asyncio.run(app._fill_description(page, humanizer))

        # sel form: ControlOrMeta+A → Delete immediately before the first glyph.
        self.assertEqual(
            page.keyboard.actions[:2],
            [("press", "ControlOrMeta+A"), ("press", "Delete")],
        )
        # Non-ASCII goes through insert_text; no fill()/type() retreat.
        self.assertIn(("insert_text", "标"), page.keyboard.actions)
        self.assertIn(("insert_text", "题"), page.keyboard.actions)
        self.assertIn(("insert_text", "一"), page.keyboard.actions)
        self.assertEqual(
            [a for a in title.actions if a[0] == "fill"], []
        )
        self.assertEqual([a for a in page.keyboard.actions if a[0] == "type"], [])
        # Exactly one after_type per field, and no native focus click.
        self.assertEqual(humanizer.pause_count("after_type"), 2)
        self.assertEqual(title.click_count, 0)
        self.assertEqual(desc.click_count, 0)
        self.assertEqual(page.mouse.down_count, 2)

    def test_type_and_declaration_are_coordinate_clicks_with_hit_test_first(self):
        timeline = Timeline()
        ai_option = Element(
            "ai-option", timeline=timeline, children={AI_CHECK_ACTIVE: FakeLocator("active")}
        )
        panel = Element(
            "declaration-panel",
            timeline=timeline,
            children={
                AI_OPTION: ai_option,
                DECLARATION_CONFIRM: Element("declaration-confirm", timeline=timeline),
            },
        )
        page = WeiboPage(
            selectors={
                TYPE_LABEL: Element("type-label", timeline=timeline),
                TYPE_CHECKED: FakeLocator("type-checked"),
                DECLARATION_TRIGGER: Element("declaration-trigger", timeline=timeline),
                DECLARATION_PANEL: panel,
            }
        )

        with patch.object(weibo_main, "Humanizer", RecordingHumanizer):
            app = _video()
            humanizer = app._humanizer(page)
            asyncio.run(app._select_type(page, humanizer))
            asyncio.run(app._select_declaration(page, humanizer))

        self.assertEqual(
            humanizer.clicks,
            [
                "type-label",
                "declaration-trigger",
                "ai-option",
                "declaration-confirm",
            ],
        )
        self.assertEqual(page.mouse.down_count, 4)
        self.assertEqual(page.mouse.up_count, 4)
        # Every dispatch was preceded by its own stillOn hit-test.
        self.assertEqual(timeline.count("hit-test"), 4)
        # Zero native clicks and zero force on the humanized path.
        for name, locator in page._selectors.items():
            self.assertEqual(locator.click_count, 0, name)
            self.assertFalse(
                any("force" in call for call in locator.click_calls), name
            )

    def test_cover_finish_is_clicked_exactly_once_then_state_is_awaited(self):
        cover_layer = Element("cover-layer", visible=True)
        finish = Element(
            "cover-finish",
            on_human_click=lambda: setattr(cover_layer, "visible_flag", False),
        )
        cover_layer._children[COVER_FINISH] = finish
        page = WeiboPage(
            selectors={
                UPLOAD_LINK: Element("upload-link"),
                COVER_LAYER: cover_layer,
                COVER_INPUT: FakeLocator("cover-input"),
                COVER_BLOB: FakeLocator("cover-blob"),
                MAIN_FORM: FakeLocator("main-form"),
            }
        )

        with patch.object(weibo_main, "Humanizer", RecordingHumanizer):
            app = _video()
            humanizer = app._humanizer(page)
            asyncio.run(app._upload_thumbnail(page, humanizer))

        self.assertEqual(humanizer.clicks, ["upload-link", "cover-finish"])
        self.assertFalse(cover_layer.visible_flag)
        # Never repeated: one click, no periodic re-clicks while waiting.
        self.assertEqual(finish.click_count, 0)


class WeiboPublishPointTests(unittest.TestCase):
    def test_publish_retries_once_from_065_to_035_after_a_not_dispatched_failure(self):
        page, publish = _publish_page(hit_results=[False, True])

        with patch.object(weibo_main, "Humanizer", RecordingHumanizer):
            app = _video()
            humanizer = app._humanizer(page)
            asyncio.run(app._submit_publish(page, humanizer=humanizer))

        self.assertEqual(humanizer.points, [(0.65, 0.5), (0.35, 0.5)])
        self.assertEqual(publish.hit_points, [(0.65, 0.5), (0.35, 0.5)])
        # Only the second attempt actually dispatched; before_submit ran once.
        self.assertEqual(page.mouse.down_count, 1)
        self.assertEqual(page.mouse.up_count, 1)
        self.assertEqual(humanizer.pause_count("before_submit"), 1)
        self.assertEqual(publish.click_count, 0)

    def test_publish_is_not_retried_after_the_mouse_went_down(self):
        # 原始异常类型是普通 RuntimeError（Playwright 不会抛 ElementUnusableError）：
        # mouse.down 之后失败仍必须映射为结果未知，不能落回 (0.35,0.5) 重试。
        page, publish = _publish_page()
        page.mouse = ExplodingMouse(RuntimeError("mouse up failed"))

        with patch.object(weibo_main, "Humanizer", RecordingHumanizer):
            app = _video()
            humanizer = app._humanizer(page)
            with self.assertRaises(PublishResultUnknownError):
                asyncio.run(app._submit_publish(page, humanizer=humanizer))

        self.assertEqual(humanizer.points, [(0.65, 0.5)])
        self.assertEqual(page.mouse.down_count, 1)
        self.assertEqual(publish.click_count, 0)

    def test_publish_is_not_retried_when_the_error_says_publish_clicked(self):
        page, publish = _publish_page()

        class Refusing(RecordingHumanizer):
            async def click(self, locator, *, point=None) -> None:
                self.clicks.append(locator.name)
                self.points.append(point)
                raise ElementUnusableError(
                    what="发布",
                    role="interactive",
                    selector=PUBLISH_BUTTON,
                    reason="covered-by:cover-mask",
                    publish_clicked=True,
                )

        with patch.object(weibo_main, "Humanizer", Refusing):
            app = _video()
            humanizer = app._humanizer(page)
            with self.assertRaises(ElementUnusableError) as caught:
                asyncio.run(app._submit_publish(page, humanizer=humanizer))

        self.assertTrue(caught.exception.publish_clicked)
        self.assertEqual(humanizer.points, [(0.65, 0.5)])
        self.assertEqual(publish.click_count, 0)


CONFIRM_DIALOG = '.woo-dialog-main, .woo-modal-wrap, [class*="Dialog"]'


class _ConfirmFailingHumanizer(RecordingHumanizer):
    """二次确认按钮派发时抛可能已派发的异常；记录尝试次数。"""

    def __init__(self, page, *, target: str, error: BaseException) -> None:
        super().__init__(page)
        self.target = target
        self.error = error
        self.confirm_attempts = 0

    async def click(self, locator, *, point=None) -> None:
        if getattr(locator, "name", "") == self.target:
            self.confirm_attempts += 1
            self.clicks.append(self.target)
            raise self.error
        await super().click(locator, point=point)


class WeiboConfirmDialogTests(unittest.TestCase):
    """二次确认：派发即落锁；可能已派发的失败 → 结果未知且绝不再点。"""

    def _page(self):
        publish = Element("publish")
        confirm = Element("confirm")
        dialog = FakeLocator(
            "dialog",
            children={'button:has(span:text-is("确定"))': confirm},
        )
        page = WeiboPage(
            selectors={
                PUBLISH_BUTTON: publish,
                AGAIN_BUTTON: FakeLocator("again", visible=False),
                SUCCESS_LAYER: FakeLocator("success-layer", visible=False),
                CONFIRM_DIALOG: dialog,
            }
        )
        return page, confirm

    def test_a_maybe_dispatched_confirm_is_result_unknown_and_never_repeated(self):
        page, confirm = self._page()
        error = RuntimeError("confirm click failed")
        setattr(error, MAYBE_DISPATCHED, MAYBE_DISPATCHED_VALUE)

        with patch.object(weibo_main, "Humanizer", RecordingHumanizer):
            app = _video()
            app._publish_budget = PublishTimeoutBudget("微博", timeout_seconds=1.0)
            humanizer = _ConfirmFailingHumanizer(
                page, target="confirm", error=error
            )
            with self.assertRaises(PublishResultUnknownError):
                asyncio.run(app._submit_publish(page, humanizer=humanizer))

        self.assertEqual(humanizer.confirm_attempts, 1)
        self.assertEqual(confirm.click_count, 0)


class LoginRedirectPublishAttemptTests(unittest.TestCase):
    """发布点击之后的登录跳转必须带 ``publish_attempted=True``。"""

    def test_pre_click_redirect_is_not_marked_as_dispatched(self):
        page = SimpleNamespace(url="https://passport.weibo.com/sso/signin")

        with self.assertRaises(LoginRequiredError) as caught:
            weibo_main._raise_if_login_required(page)

        self.assertFalse(caught.exception.publish_attempted)

    def test_post_click_poll_marks_the_redirect_as_dispatched(self):
        page, publish = _publish_page()
        publish.on_human_click = lambda: setattr(
            page, "url", "https://passport.weibo.com/sso/signin"
        )

        with patch.object(weibo_main, "Humanizer", RecordingHumanizer):
            app = _video()
            humanizer = app._humanizer(page)
            with self.assertRaises(LoginRequiredError) as caught:
                asyncio.run(
                    app._submit_publish(page, multilogin=True, humanizer=humanizer)
                )

        self.assertTrue(caught.exception.publish_attempted)


# ---------------------------------------------------------------------------
# 2. Field-value readback
# ---------------------------------------------------------------------------


class WeiboFieldValueTests(unittest.TestCase):
    def test_title_value_replaces_the_previous_content(self):
        timeline = Timeline()
        title = Element("title", timeline=timeline)
        page = WeiboPage(selectors={f"placeholder:{TITLE_PLACEHOLDER}": title})
        page.keyboard.buffers["title"] = "旧标题"

        with patch.object(weibo_main, "Humanizer", RecordingHumanizer):
            app = _video()
            humanizer = app._humanizer(page)
            asyncio.run(app._fill_title(page, humanizer))

        self.assertEqual(page.keyboard.buffers["title"], "标题一")

    def test_description_value_keeps_text_tags_and_newlines(self):
        desc = Element("description")
        page = WeiboPage(selectors={f"placeholder:{DESC_PLACEHOLDER}": desc})

        with patch.object(weibo_main, "Humanizer", RecordingHumanizer):
            app = _video(desc="第一行\r\n第二行", tags=["a", "b"])
            humanizer = app._humanizer(page)
            asyncio.run(app._fill_description(page, humanizer))

        self.assertEqual(
            page.keyboard.buffers["description"], "第一行\n第二行\n#a# #b#"
        )
        for action in page.keyboard.actions:
            self.assertNotIn("\r", str(action))

    def test_over_horizon_description_is_one_bulk_insert(self):
        desc = Element("description")
        page = WeiboPage(selectors={f"placeholder:{DESC_PLACEHOLDER}": desc})
        long_desc = "长" * 1001

        with patch.object(weibo_main, "Humanizer", RecordingHumanizer):
            app = _video(desc=long_desc)
            humanizer = app._humanizer(page)
            asyncio.run(app._fill_description(page, humanizer))

        self.assertEqual(page.keyboard.buffers["description"], long_desc)
        self.assertEqual(
            [a for a in page.keyboard.actions if a[0] == "insert_text"],
            [("insert_text", long_desc)],
        )
        self.assertEqual(humanizer.pause_count("after_type"), 1)

    def test_new_collection_name_is_cleared_and_typed_verbatim(self):
        state = {"checked": False}
        ready = {"value": False}
        add_text = Element(
            "add-text", on_human_click=lambda: ready.__setitem__("value", True)
        )
        add_button = FakeLocator("add-button", children={"text:新建合集:exact": add_text})
        new_input = Element("new-collection", visible=False)

        # The row only appears after the + click: visibility is dynamic.
        async def _row_ready() -> bool:
            return ready["value"]

        new_input.is_visible = _row_ready  # type: ignore[assignment]
        panel = FakeLocator(
            "collection-panel",
            children={
                COLLECTION_ROWS: FakeLocator("rows", count=0),
                ADD_BUTTON: add_button,
                NEW_COLLECTION_INPUT: new_input,
            },
        )
        block = FakeLocator(
            "switch-block",
            children={
                SWITCH_INPUT: CheckableInput("switch-input", state),
                SWITCH_SPAN: Element(
                    "switch-span",
                    on_human_click=lambda: state.__setitem__("checked", True),
                ),
                SWITCH_LABEL: Element("switch-label"),
            },
        )
        page = WeiboPage(
            selectors={SWITCH_BLOCK: block, COLLECTION_PANEL: panel}
        )
        target = "合集名超过十二个字"

        with patch.object(weibo_main, "Humanizer", RecordingHumanizer):
            app = _video(collection_name=target)
            humanizer = app._humanizer(page)
            asyncio.run(app._apply_collection(page, humanizer))

        self.assertEqual(page.keyboard.buffers["new-collection"], target[:12])
        self.assertEqual(
            humanizer.clicks, ["switch-span", "add-text", "new-collection"]
        )
        self.assertTrue(state["checked"])


# ---------------------------------------------------------------------------
# 3. Two instances (homepage vs popup)
# ---------------------------------------------------------------------------


class WeiboTwoInstanceTests(unittest.TestCase):
    def test_homepage_and_popup_get_distinct_instances_and_publish_uses_the_popup(self):
        home = WeiboPage(selectors={VIDEO_ENTRY: Element("video-entry")})
        publish, _publish_button = _publish_page()
        home.popup_page = publish
        instances: list[Humanizer] = []

        class Factory(RecordingHumanizer):
            def __init__(self, page, **kwargs) -> None:
                super().__init__(page, **kwargs)
                instances.append(self)

        with patch.object(weibo_main, "Humanizer", Factory):
            app = _video()
            opened = asyncio.run(app._open_video_publish_page(home))
            self.assertIs(opened, publish)

            homepage_humanizer = app._humanizer_instance
            self.assertIs(homepage_humanizer.page, home)
            self.assertEqual(homepage_humanizer.clicks, ["video-entry"])
            self.assertEqual(
                homepage_humanizer.pause_count("after_navigate"), 1
            )

            popup_humanizer = app._humanizer(publish)
            self.assertIsNot(popup_humanizer, homepage_humanizer)
            self.assertIs(popup_humanizer.page, publish)

            asyncio.run(app._submit_publish(publish, humanizer=popup_humanizer))

        # Never reused across pages: one instance per page, and the publish page
        # owns every post-popup click.
        self.assertEqual([instance.page for instance in instances], [home, publish])
        self.assertEqual(homepage_humanizer.clicks, ["video-entry"])
        self.assertEqual(popup_humanizer.clicks, ["publish"])
        self.assertIs(app._humanizer_instance, popup_humanizer)

    def test_upload_in_hands_every_post_popup_step_the_popup_instance(self):
        home = WeiboPage()
        publish = WeiboPage()
        session = BrowserSession(
            browser=MagicMock(), context=MagicMock(), mode="local"
        )
        session.context.new_page = AsyncMock(return_value=home)
        app = _video(collection_name="合集")

        step_names = [
            "_upload_video_file",
            "_wait_upload_complete",
            "_select_type",
            "_select_declaration",
            "_fill_title",
            "_upload_thumbnail",
            "_apply_collection",
            "_fill_description",
        ]
        with patch.object(weibo_main, "Humanizer", RecordingHumanizer):
            with patch.object(
                app, "_open_video_publish_page", AsyncMock(return_value=publish)
            ), patch.object(app, "_submit_publish", AsyncMock()) as submit:
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

        popup_humanizer = app._humanizer_instance
        self.assertIs(popup_humanizer.page, publish)
        for name in step_names:
            call = started[name].await_args
            humanizer = (call.kwargs or {}).get("humanizer")
            if humanizer is None:
                self.assertIs(call.args[0], publish, name)
                continue
            self.assertIs(humanizer.page, publish, name)
        self.assertIs(submit.await_args.kwargs["humanizer"].page, publish)


# ---------------------------------------------------------------------------
# 4. HUMANIZE=0 + static gates
# ---------------------------------------------------------------------------


class WeiboHumanizeDisabledTests(unittest.TestCase):
    def test_humanize_zero_uses_one_insert_and_native_clicks(self):
        title = Element("title")
        page, publish = _publish_page()
        page._selectors[f"placeholder:{TITLE_PLACEHOLDER}"] = title

        with patch.dict(os.environ, {"HUMANIZE": "0"}):
            with patch.object(weibo_main, "Humanizer", RecordingHumanizer):
                app = _video()
                humanizer = app._humanizer(page)
                self.assertFalse(humanizer.enabled)
                asyncio.run(app._fill_title(page, humanizer))
                asyncio.run(app._submit_publish(page, humanizer=humanizer))

        # One bulk insert per field; clearing still uses the named keys.
        self.assertEqual(
            [a for a in page.keyboard.actions if a[0] == "insert_text"],
            [("insert_text", "标题一")],
        )
        self.assertEqual(
            [a for a in page.keyboard.actions if a[0] == "press"],
            [("press", "ControlOrMeta+A"), ("press", "Delete"), ("press", "Escape")],
        )
        # Semantic switch: native locator.click, zero pointer movement, zero pauses.
        self.assertEqual(title.click_count, 1)
        self.assertEqual(publish.click_count, 1)
        self.assertEqual(page.mouse.actions, [])
        self.assertEqual(humanizer.pauses, [])


class WeiboStaticGateTests(unittest.TestCase):
    def test_weibo_package_passes_humanize_gates_a_to_e(self):
        assert_clean(PACKAGE)

    def test_no_js_click_or_force_remains_in_the_package(self):
        source = (PACKAGE / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("el.click()", source)
        self.assertNotIn("force=True", source)


if __name__ == "__main__":
    unittest.main()
