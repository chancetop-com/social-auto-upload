# -*- coding: utf-8 -*-
"""快手视频 / 图文发布表单的人类化接线（spec §3.6 / §6.2）。

三块，全部离线：

1. **事件序列** —— 描述/正文的 ``Backspace → Control+A → Delete`` 清空序列
   逐键保留、话题逐字（含 ``#`` 与尾随空格）、每个输入恰一次 ``after_type``；
   描述聚焦、发布、定时、合集、封面全部走 ``Humanizer.click``（``mouse.down``
   之前先有 stillOn 命中测试），只有登录/文件入口/提示条/引导层保持原生。
2. **字段值读回** —— fake 键盘把按键写回聚焦元素的缓冲，断言最终值与预期
   完全相等（抓「序列对、值错」：清空不净、追加、话题超过 3 个）。
3. **平台静态门** —— 包内跑 spec §4.2–4.5 的 A–E 门。

另外覆盖：零尺寸描述目标直接 ``zero-box`` 硬失败（不再用 ``force`` 造假
成功）、定时日期仍由 JS setter 写值、``HUMANIZE=0`` 快路径。

选择器未 scripted 直接抛 :class:`UnscriptedSelectorError`，不用 MagicMock。
"""

from __future__ import annotations

import asyncio
import inspect
import os
import random
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import uploader.ks_uploader.main as ks_main
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
from utils.humanize import HumanizeProfile, LogNormal

AFTER_TYPE = 5.0
BEFORE_SUBMIT = 7.0
AFTER_NAVIGATE = 2.0
PAUSE_NAMES = {
    5.0: "after_type",
    7.0: "before_submit",
    2.0: "after_navigate",
}


def _fixed(seconds: float) -> LogNormal:
    return LogNormal(0.0, 0.0, seconds, seconds)


#: 固定停顿表：5.0s=after_type、7.0=before_submit、2.0=after_navigate，其余小值。
TEST_PROFILE = HumanizeProfile(
    keystroke=_fixed(0.01),
    after_type=_fixed(AFTER_TYPE),
    after_navigate=_fixed(AFTER_NAVIGATE),
    before_submit=_fixed(BEFORE_SUBMIT),
    pointer_settle=_fixed(0.02),
    click_hold=_fixed(0.03),
    before_click=_fixed(0.04),
    after_click=_fixed(0.05),
    between_scroll=_fixed(0.06),
    reading=_fixed(0.07),
    after_interact=_fixed(0.08),
)

DESC_XPATH = "xpath=following-sibling::div"
DESC_LABEL = "text:描述"  # page.get_by_text("描述")
UPLOAD_BTN = "button[class^='_upload-btn']"
NOTICE = 'button[type="button"] span:text("我知道了")'
JOYRIDE_TOOLTIP = 'div[id^="react-joyride-step"] div[role="alertdialog"]'
JOYRIDE_PORTAL = "div#react-joyride-portal"
JOYRIDE_SPOTLIGHT = "div.react-joyride__spotlight"
UPLOADING = "text=上传中"
PUBLISH = "text:发布:exact"  # page.get_by_text("发布", exact=True)
CONFIRM = "text:确认发布"  # page.get_by_text("确认发布")
MODAL = "div.ant-modal-confirm-centered:visible"
MODAL_PRIMARY = "button.ant-btn-primary:visible"
IMAGE_TAB = 'div[role="tablist"] div[role="tab"]:has-text("图文")'
NOTE_UPLOAD = "button[class^='_upload-btn']"

PACKAGE = Path(__file__).resolve().parent.parent / "uploader" / "ks_uploader"


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

    def __init__(self, name: str, *, log: list, box: dict | None = None, **kwargs) -> None:
        kwargs["box"] = (
            box
            if box is not None
            else {"x": 10.0, "y": 20.0, "width": 80.0, "height": 24.0}
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
                "width": self._box["width"],
                "height": self._box["height"],
                "inside": True,
                "clipped": False,
                "childFrame": False,
            }
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
            "contentEditable": "true",
            "readOnly": False,
            "isConnected": True,
        }

    async def scroll_into_view_if_needed(self, **kwargs) -> None:
        self.actions.append(("scroll",))

    def get_by_role(self, role: str, name=None, **kwargs):
        return super().get_by_role(role, name)


class _ChooserProbeClickable(_Clickable):
    """封面 tab fake：记录命中测试时的 ``chooser_depth``，可在命中时改 DOM。

    命中测试就是真实鼠标点击的前一步，所以 ``depths`` 正好回答「这一下是不
    是被 ``expect_file_chooser`` 消费了」：深度 1 = 被消费，0 = 裸点击。
    """

    def __init__(self, name: str, *, log: list, **kwargs) -> None:
        super().__init__(name, log=log, **kwargs)
        self.page = None
        self.depths: list[int] = []
        self.on_hit = None

    async def evaluate(self, expression, arg=None):
        result = await super().evaluate(expression, arg)
        if _expr_kind(expression) == "hit-test":
            if self.page is not None:
                self.depths.append(self.page.chooser_depth)
            if self.on_hit is not None:
                self.on_hit()
        return result


class _TypingLocator(_Clickable):
    """持有键入缓冲的 locator；命中测试（=真实点击）把焦点交给它。"""

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

    async def click(self, **kwargs) -> None:
        # HUMANIZE=0 快路径走原生 click；真实点击同样会把焦点交给输入框。
        await super().click(**kwargs)
        if self._page is not None:
            self._page.focused = self
            self._page.selected = False

    async def evaluate(self, expression, arg=None):
        result = await super().evaluate(expression, arg)
        if _expr_kind(expression) == "hit-test" and self._page is not None:
            self._page.focused = self
            self._page.selected = False
        return result

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


class _Keyboard(RecordingKeyboard):
    def __init__(self, page: "_Page", log: list) -> None:
        super().__init__()
        self._page = page
        self._log = log

    async def press(self, key: str, **kwargs) -> None:
        self.actions.append(("press", key))
        self._log.append(("key", ("press", key)))
        self._page.apply_key(key)

    async def insert_text(self, text: str, **kwargs) -> None:
        self.actions.append(("insert_text", text))
        self._log.append(("key", ("insert_text", text)))
        self._page.apply_text(text)

    async def type(self, text: str, delay: float | None = None, **kwargs) -> None:
        self.actions.append(("type", text, delay))
        self._log.append(("key", ("type", text, delay)))
        self._page.apply_text(text)


class _Mouse(RecordingMouse):
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


class _Page(RecordingPage):
    def __init__(self, *, log: list, selectors: dict, **kwargs) -> None:
        super().__init__(selectors=selectors, **kwargs)
        self.log = log
        self.mouse = _Mouse(log)
        self.keyboard = _Keyboard(self, log)
        self.focused = None
        self.selected = False

    def get_by_role(self, role: str, name=None, **kwargs):
        return super().get_by_role(role, name)

    def apply_key(self, key: str) -> None:
        if self.focused is not None:
            self.focused.apply_key(key)

    def apply_text(self, text: str) -> None:
        if self.focused is not None:
            self.focused.apply_text(text)


class _QuietHumanizer(ks_main.Humanizer):
    """真实原语、固定停顿表、零墙钟。"""

    def __init__(self, page, *, log: list | None = None, **kwargs) -> None:
        self.pauses: list[float] = []
        self._log = log

        async def _record(seconds: float) -> None:
            self.pauses.append(round(seconds, 4))
            if log is not None:
                log.append(("pause", round(seconds, 4)))

        super().__init__(
            page, profile=TEST_PROFILE, rng=random.Random(0), sleep=_record
        )


@contextmanager
def _humanized(log: list):
    """把模块里的 ``Humanizer`` 换成固定停顿表的版本（实例仍按 page 缓存）。"""

    def _make(page, **kwargs):
        return _QuietHumanizer(page, log=log)

    with patch.object(ks_main, "Humanizer", _make):
        yield


@contextmanager
def _fast_clock():
    with patch.object(asyncio, "sleep", new=AsyncMock(return_value=None)):
        yield


def _attach(page: _Page, locator: FakeLocator) -> None:
    if isinstance(locator, _TypingLocator):
        locator._page = page
    for child in locator._children.values():
        _attach(page, child)


def _page(selectors: dict[str, FakeLocator], *, log: list | None = None) -> _Page:
    log = [] if log is None else log
    page = _Page(log=log, selectors=selectors)
    for locator in selectors.values():
        _attach(page, locator)
    return page


def _video_app(tmp: str, **overrides) -> ks_main.KSVideo:
    values = {
        "title": "标题",
        "file_path": Path(tmp) / "clip.mp4",
        "tags": [],
        "publish_date": 0,
        "account_file": Path(tmp) / "account.json",
        "publish_strategy": "immediate",
    }
    values.update(overrides)
    return ks_main.KSVideo(**values)


def _note_app(tmp: str, **overrides) -> ks_main.KSNote:
    values = {
        "image_paths": [Path(tmp) / "a.png"],
        "note": "图文正文",
        "tags": [],
        "publish_date": 0,
        "account_file": Path(tmp) / "account.json",
        "publish_strategy": "immediate",
    }
    values.update(overrides)
    return ks_main.KSNote(**values)


def _video_selectors(log: list, editor: _TypingLocator, **overrides) -> dict:
    selectors = {
        UPLOAD_BTN: _Clickable("upload", log=log),
        NOTICE: FakeLocator("notice", count=0),
        JOYRIDE_TOOLTIP: FakeLocator("joyride-tooltip", count=0),
        JOYRIDE_PORTAL: FakeLocator("joyride-portal", count=0),
        JOYRIDE_SPOTLIGHT: FakeLocator("joyride-spotlight", count=0),
        DESC_LABEL: FakeLocator("desc-label", children={DESC_XPATH: editor}),
        UPLOADING: FakeLocator("uploading", count=0),
        PUBLISH: _Clickable("publish", log=log),
        MODAL: FakeLocator("confirm-modal", count=0),
    }
    selectors.update(overrides)
    return selectors


def _note_selectors(log: list, editor: _TypingLocator, **overrides) -> dict:
    selectors = {
        IMAGE_TAB: _Clickable("image-tab", log=log),
        NOTE_UPLOAD: _Clickable("upload-images", log=log),
        NOTICE: FakeLocator("notice", count=0),
        JOYRIDE_TOOLTIP: FakeLocator("joyride-tooltip", count=0),
        JOYRIDE_PORTAL: FakeLocator("joyride-portal", count=0),
        JOYRIDE_SPOTLIGHT: FakeLocator("joyride-spotlight", count=0),
        DESC_LABEL: FakeLocator("desc-label", children={DESC_XPATH: editor}),
        UPLOADING: FakeLocator("uploading", count=0),
        PUBLISH: _Clickable("publish", log=log),
        CONFIRM: _Clickable("confirm", log=log),
    }
    selectors.update(overrides)
    return selectors


def _after_type_count(humanizer: _QuietHumanizer) -> int:
    return humanizer.pauses.count(AFTER_TYPE)


# ---------------------------------------------------------------------------
# 1. 事件序列
# ---------------------------------------------------------------------------


class HumanizeEventSequenceTests(unittest.TestCase):
    def test_video_clears_with_seq_types_topics_per_character_and_humanizes_publish(self):
        with self.subTest("video"), _temp_dir() as tmp:
            log: list = []
            editor = _TypingLocator("desc-editor", log=log, initial="旧描述")
            page = _page(_video_selectors(log, editor), log=log)
            app = _video_app(tmp, desc="新描述", tags=["话题一", "tag二"])

            with _humanized(log), _fast_clock():
                asyncio.run(app._upload_video_on_page(page))

            keyboard = page.keyboard.actions
            # 清空序列逐键保留，且发生在聚焦点击的命中测试之后。
            self.assertEqual(
                keyboard[:3],
                [
                    ("press", "Backspace"),
                    ("press", "Control+A"),
                    ("press", "Delete"),
                ],
            )
            focus_hit = log.index(("evaluate", "hit-test", "desc-editor"))
            self.assertLess(focus_hit, log.index(("key", keyboard[0])))

            # 非 ASCII 逐字 insert_text；话题的 `#` 与尾随空格是真按键。
            self.assertEqual(
                [action for action in keyboard if action[0] == "insert_text"],
                [
                    ("insert_text", "新"),
                    ("insert_text", "描"),
                    ("insert_text", "述"),
                    ("insert_text", "话"),
                    ("insert_text", "题"),
                    ("insert_text", "一"),
                    ("insert_text", "二"),
                ],
            )
            self.assertIn(("press", "#"), keyboard)
            self.assertIn(("press", " "), keyboard)
            self.assertIn(("press", "t"), keyboard)
            self.assertIn(("press", "a"), keyboard)
            self.assertIn(("press", "g"), keyboard)
            self.assertEqual([a for a in keyboard if a[0] == "type"], [])
            self.assertEqual(editor.buffer, "新描述\n#话题一 #tag二 ")

            # 描述 + 两个话题：每个输入恰一次 after_type。
            self.assertEqual(_after_type_count(app._humanizer_instance), 3)

            # 描述聚焦 + 发布：两次人类化点击；上传入口保持原生 file 点击。
            upload = page.locator(UPLOAD_BTN)
            publish = page.locator(PUBLISH)
            self.assertEqual(upload.click_count, 1)
            self.assertEqual(upload.click_calls[0].get("force"), None)
            self.assertEqual(publish.click_count, 0)
            self.assertEqual(page.mouse.down_count, 2)

            # stillOn 命中测试先于每一次 down。
            hits = [i for i, event in enumerate(log) if event[:2] == ("evaluate", "hit-test")]
            downs = [i for i, event in enumerate(log) if event == ("down",)]
            self.assertEqual(len(downs), 2)
            self.assertLess(hits[0], downs[0])
            self.assertLess(hits[1], downs[1])

            # 发布前恰一次 before_submit，且在发布点击之前。
            pause = log.index(("pause", BEFORE_SUBMIT))
            publish_hit = log.index(("evaluate", "hit-test", "publish"))
            self.assertLess(pause, publish_hit)
            self.assertLess(pause, downs[1])

    def test_note_body_and_at_most_three_topics(self):
        with _temp_dir() as tmp:
            log: list = []
            editor = _TypingLocator("note-editor", log=log, initial="旧正文")
            page = _page(_note_selectors(log, editor), log=log)
            app = _note_app(tmp, note="图文正文", tags=["a", "b", "c", "d", "e"])

            with _humanized(log), _fast_clock():
                asyncio.run(app.upload_note_content(page))

            keyboard = page.keyboard.actions
            self.assertEqual(
                keyboard[:3],
                [
                    ("press", "Backspace"),
                    ("press", "Control+A"),
                    ("press", "Delete"),
                ],
            )
            self.assertEqual(editor.buffer, "图文正文\n#a #b #c ")
            # 只输入前 3 个话题（每话题一个 `#`）。
            self.assertEqual(
                sum(1 for action in keyboard if action == ("press", "#")), 3
            )
            # 正文 + 3 个话题。
            self.assertEqual(_after_type_count(app._humanizer_instance), 4)

            # 切图文 tab：人类化点击后付一次 after_navigate。
            tab = page.locator(IMAGE_TAB)
            self.assertEqual(tab.click_count, 0)
            tab_hit = log.index(("evaluate", "hit-test", "image-tab"))
            nav = log.index(("pause", AFTER_NAVIGATE))
            self.assertLess(tab_hit, nav)
            self.assertLess(log.index(("down",)), nav)

            # 切 tab + 正文 + 发布 + 确认发布：四次人类化点击。
            self.assertEqual(page.mouse.down_count, 4)
            self.assertEqual(page.locator(PUBLISH).click_count, 0)
            self.assertEqual(page.locator(CONFIRM).click_count, 0)

    def test_over_horizon_description_is_one_bulk_insert_text(self):
        with _temp_dir() as tmp:
            log: list = []
            body = "字" * 1001
            editor = _TypingLocator("desc-editor", log=log)
            page = _page(_video_selectors(log, editor), log=log)
            app = _video_app(tmp, desc=body, tags=[])

            with _humanized(log), _fast_clock():
                asyncio.run(app._upload_video_on_page(page))

            inserts = [
                action
                for action in page.keyboard.actions
                if action[0] == "insert_text"
            ]
            self.assertEqual(inserts, [("insert_text", body)])
            self.assertEqual(editor.buffer, body + "\n")
            self.assertEqual(_after_type_count(app._humanizer_instance), 1)

    def test_publish_confirm_dialog_primary_action_is_humanized(self):
        log: list = []
        primary = _Clickable("confirm-primary", log=log)
        modal = FakeLocator(
            "confirm-modal", children={MODAL_PRIMARY: primary}
        )
        page = _page({MODAL: modal}, log=log)
        humanizer = _QuietHumanizer(page, log=log)

        with _fast_clock():
            confirmed = asyncio.run(
                ks_main._click_visible_publish_confirm(page, humanizer)
            )

        self.assertTrue(confirmed)
        self.assertEqual(primary.click_count, 0)
        self.assertEqual(page.mouse.down_count, 1)
        self.assertIn(("evaluate", "hit-test", "confirm-primary"), log)

    def test_schedule_toggle_and_picker_are_humanized_but_value_stays_js(self):
        with _temp_dir() as tmp:
            log: list = []
            schedule_radio = _Clickable("schedule-radio", log=log)
            date_input = _Clickable("date-input", log=log)
            page = _page(
                {
                    "label.ant-radio-wrapper": schedule_radio,
                    'input[placeholder="选择日期时间"]': date_input,
                },
                log=log,
            )
            page._evaluate_results.append(True)
            app = _video_app(tmp)
            humanizer = _QuietHumanizer(page, log=log)
            target = datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

            with _fast_clock():
                asyncio.run(app.set_schedule_time(page, target, humanizer))

            self.assertEqual(schedule_radio.click_count, 0)
            self.assertEqual(date_input.click_count, 0)
            self.assertEqual(page.mouse.down_count, 2)
            # 日期值仍由 JS setter 写入，Enter 是真实具名键。
            setter_args = [
                arg
                for expression, arg in page.evaluate_calls
                if isinstance(expression, str) and "nativeSetter" in expression
            ]
            self.assertEqual(setter_args, ["2030-01-02 03:04:05"])
            self.assertIn(("press", "Enter"), page.keyboard.actions)

    def test_collection_dropdown_and_option_are_humanized(self):
        log: list = []
        selector = _Clickable("collection-selector", log=log)
        option = _Clickable("collection-option", log=log)
        ant_select = FakeLocator(
            "collection-ant-select",
            children={".ant-select-selector": selector},
        )
        trigger = FakeLocator(
            "collection-trigger",
            children={"xpath=following-sibling::div[contains(@class,'ant-select')]": ant_select},
        )
        page = _page(
            {
                'label:text-is("加入合集")': trigger,
                'div.ant-select-item-option[label="合集A"]': option,
            },
            log=log,
        )
        app = _video_app("/tmp", collection_name="合集A")
        humanizer = _QuietHumanizer(page, log=log)

        with _fast_clock():
            asyncio.run(app.apply_collection(page, humanizer))

        self.assertEqual(selector.click_count, 0)
        self.assertEqual(option.click_count, 0)
        self.assertEqual(page.mouse.down_count, 2)
        self.assertIn(("evaluate", "hit-test", "collection-option"), log)

    def test_cover_settings_use_a_narrowed_visible_div(self):
        with _temp_dir() as tmp:
            log: list = []
            cover_entry = _Clickable("cover-entry", log=log)
            container = FakeLocator(
                "cover-container", children={"div:visible": cover_entry}
            )
            cover_label = FakeLocator(
                "cover-label",
                children={"xpath=../following-sibling::div[1]": container},
            )
            upload_tab = _Clickable("cover-tab", log=log)
            confirm = _Clickable("cover-confirm", log=log)
            modal = _Clickable(
                "cover-modal",
                log=log,
                children={
                    "text:上传封面:exact": upload_tab,
                    'input[type="file"]': FakeLocator("cover-file"),
                    "role:button:确认": confirm,
                },
            )
            page = _page(
                {
                    "span": cover_label,
                    'div[role="document"].ant-modal': modal,
                },
                log=log,
            )
            app = _video_app(
                tmp, thumbnail_path=Path(tmp) / "cover.jpg"
            )
            humanizer = _QuietHumanizer(page, log=log)

            with _fast_clock():
                asyncio.run(app.set_thumbnail(page, humanizer))

            self.assertEqual(cover_entry.click_count, 0)
            self.assertEqual(upload_tab.click_count, 0)
            self.assertEqual(confirm.click_count, 0)
            self.assertEqual(page.mouse.down_count, 2)
            cover_file = modal.locator('input[type="file"]')
            self.assertEqual(cover_file.files, [Path(tmp) / "cover.jpg"])
            # 弹窗里已有隐藏 input：直接写，不点「上传封面」tab，所以也从不
            # 拉起系统文件选择器（先例：小红书 bbc5361）。
            self.assertEqual(page.expect_file_chooser_calls, 0)

    def test_cover_tab_is_clicked_only_inside_the_file_chooser(self):
        with _temp_dir() as tmp:
            log: list = []
            cover_entry = _Clickable("cover-entry", log=log)
            container = FakeLocator(
                "cover-container", children={"div:visible": cover_entry}
            )
            cover_label = FakeLocator(
                "cover-label",
                children={"xpath=../following-sibling::div[1]": container},
            )
            upload_tab = _ChooserProbeClickable("cover-tab", log=log)
            confirm = _Clickable("cover-confirm", log=log)
            cover_file = FakeLocator("cover-file", count=0)
            modal = _Clickable(
                "cover-modal",
                log=log,
                children={
                    "text:上传封面:exact": upload_tab,
                    'input[type="file"]': cover_file,
                    "role:button:确认": confirm,
                },
            )
            page = _page(
                {
                    "span": cover_label,
                    'div[role="document"].ant-modal': modal,
                },
                log=log,
            )
            upload_tab.page = page
            app = _video_app(tmp, thumbnail_path=Path(tmp) / "cover.jpg")
            humanizer = _QuietHumanizer(page, log=log)

            with _fast_clock():
                asyncio.run(app.set_thumbnail(page, humanizer))

            # 只有 input 缺失时才点 tab，且这一下必须被 expect_file_chooser
            # 消费：命中测试看到的 chooser 深度是 1，不是 0（裸点击）。
            self.assertEqual(page.expect_file_chooser_calls, 1)
            self.assertEqual(upload_tab.depths, [1])
            self.assertEqual(page.chooser_depth, 0)
            self.assertEqual(page.file_chooser_files(), [Path(tmp) / "cover.jpg"])
            self.assertEqual(page.mouse.down_count, 3)
            self.assertNotIn("set_input_files", [a[0] for a in cover_file.actions])

    def test_cover_input_is_written_when_no_file_chooser_arrives(self):
        with _temp_dir() as tmp:
            log: list = []
            cover_entry = _Clickable("cover-entry", log=log)
            container = FakeLocator(
                "cover-container", children={"div:visible": cover_entry}
            )
            cover_label = FakeLocator(
                "cover-label",
                children={"xpath=../following-sibling::div[1]": container},
            )
            upload_tab = _ChooserProbeClickable("cover-tab", log=log)
            confirm = _Clickable("cover-confirm", log=log)
            cover_file = FakeLocator("cover-file", count=0)
            modal = _Clickable(
                "cover-modal",
                log=log,
                children={
                    "text:上传封面:exact": upload_tab,
                    'input[type="file"]': cover_file,
                    "role:button:确认": confirm,
                },
            )
            page = _page(
                {
                    "span": cover_label,
                    'div[role="document"].ant-modal': modal,
                },
                log=log,
            )
            page.fail_file_chooser = PWTimeoutError("no file chooser")
            upload_tab.on_hit = lambda: setattr(cover_file, "_count", 1)
            app = _video_app(tmp, thumbnail_path=Path(tmp) / "cover.jpg")
            humanizer = _QuietHumanizer(page, log=log)

            with _fast_clock():
                asyncio.run(app.set_thumbnail(page, humanizer))

            self.assertEqual(page.expect_file_chooser_calls, 1)
            self.assertEqual(page.file_chooser_files(), [])
            self.assertEqual(cover_file.files, [Path(tmp) / "cover.jpg"])
            self.assertEqual(page.mouse.down_count, 3)

    def test_humanize_failure_during_the_cover_tab_click_propagates(self):
        with _temp_dir() as tmp:
            log: list = []
            cover_entry = _Clickable("cover-entry", log=log)
            container = FakeLocator(
                "cover-container", children={"div:visible": cover_entry}
            )
            cover_label = FakeLocator(
                "cover-label",
                children={"xpath=../following-sibling::div[1]": container},
            )
            upload_tab = _ChooserProbeClickable("cover-tab", log=log, box={})
            confirm = _Clickable("cover-confirm", log=log)
            cover_file = FakeLocator("cover-file", count=0)
            modal = _Clickable(
                "cover-modal",
                log=log,
                children={
                    "text:上传封面:exact": upload_tab,
                    'input[type="file"]': cover_file,
                    "role:button:确认": confirm,
                },
            )
            page = _page(
                {
                    "span": cover_label,
                    'div[role="document"].ant-modal': modal,
                },
                log=log,
            )
            upload_tab.page = page

            app = _video_app(tmp, thumbnail_path=Path(tmp) / "cover.jpg")
            humanizer = _QuietHumanizer(page, log=log)

            with _fast_clock():
                with self.assertRaises(ElementUnusableError):
                    asyncio.run(app.set_thumbnail(page, humanizer))

            # 人类化失败必须上抛，不能被吞成「chooser 没到 → 直接写 input」。
            self.assertEqual(page.file_chooser_files(), [])
            self.assertNotIn("set_input_files", [a[0] for a in cover_file.actions])


# ---------------------------------------------------------------------------
# 2. 字段值读回 / 硬失败
# ---------------------------------------------------------------------------


class HumanizeReadbackTests(unittest.TestCase):
    def test_zero_sized_focus_target_fails_with_zero_box_and_no_dispatch(self):
        log: list = []
        editor = _TypingLocator(
            "desc-editor",
            log=log,
            box={"x": 10.0, "y": 20.0, "width": 0.0, "height": 0.0},
        )
        page = _page(
            {
                DESC_LABEL: FakeLocator("desc-label", children={DESC_XPATH: editor}),
            },
            log=log,
        )
        humanizer = _QuietHumanizer(page, log=log)

        with _fast_clock(), self.assertRaises(ElementUnusableError) as ctx:
            asyncio.run(ks_main._focus_desc_editor(page, humanizer))

        self.assertEqual(ctx.exception.reason, "zero-box")
        self.assertEqual(page.mouse.down_count, 0)
        # 回退分支不再用 force 掩盖不可点目标。
        self.assertNotIn("force=", inspect.getsource(ks_main._focus_desc_editor))


# ---------------------------------------------------------------------------
# HUMANIZE=0 快路径
# ---------------------------------------------------------------------------


class HumanizeDisabledTests(unittest.TestCase):
    def test_text_is_one_insert_per_input_and_clicks_are_native_without_pauses(self):
        with _temp_dir() as tmp:
            log: list = []
            editor = _TypingLocator("desc-editor", log=log, initial="旧描述")
            page = _page(_video_selectors(log, editor), log=log)
            app = _video_app(tmp, desc="新描述", tags=["话题"])

            with _humanized(log), _fast_clock(), patch.dict(
                os.environ, {"HUMANIZE": "0"}
            ):
                asyncio.run(app._upload_video_on_page(page))

            inserts = [
                action
                for action in page.keyboard.actions
                if action[0] == "insert_text"
            ]
            self.assertEqual(
                inserts, [("insert_text", "新描述"), ("insert_text", "#话题 ")]
            )
            # 清空键仍是具名键（press 不看 enabled），但没有逐字按键。
            self.assertNotIn(("press", "新"), page.keyboard.actions)
            self.assertEqual(app._humanizer_instance.pauses, [])
            # 点击走原生 locator.click：一次/目标、零 mouse.down。
            self.assertEqual(editor.click_count, 1)
            self.assertEqual(page.locator(PUBLISH).click_count, 1)
            self.assertEqual(page.mouse.down_count, 0)
            self.assertEqual(editor.buffer, "新描述\n#话题 ")


# ---------------------------------------------------------------------------
# 3. 平台静态门
# ---------------------------------------------------------------------------


class HumanizeGateTests(unittest.TestCase):
    def test_kuaishou_package_passes_gates_a_to_e(self):
        assert_clean(PACKAGE)


@contextmanager
def _temp_dir():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


if __name__ == "__main__":
    unittest.main()
