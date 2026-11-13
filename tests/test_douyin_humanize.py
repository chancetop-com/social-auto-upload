# -*- coding: utf-8 -*-
"""抖音人类化接线（spec §3.4 / §6.2）。

三块离线验收（缺一不可）：

1. 事件序列 —— 每个改 Humanizer 的点断言原语（``press`` / ``insert_text``）、
   ``after_type`` 次数、``mouse.move* → down → up``、hit-test 先于 ``down``、
   零原生 ``locator.click()``、零 ``force``、零 ``el.click``。
2. 字段值读回 —— fake 键盘把按键写回持有缓冲的 locator，断言最终值与预期
   完全相等（抓「序列对、值错」：清空不净、追加、预填未覆盖）。
3. 平台静态门 —— 抖音包内跑 spec §4.2–4.5 的 A–E 门。

另外覆盖 ``HUMANIZE=0`` 快路径与「``click_dispatched='maybe'`` 不再二次派发」。
未 scripted 的选择器直接抛 :class:`UnscriptedSelectorError`，不用 MagicMock。
"""

from __future__ import annotations

import asyncio
import os
import random
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import uploader.douyin_uploader.main as douyin_main
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
AFTER_NAVIGATE = 2.0
BEFORE_SUBMIT = 7.0

TITLE_SELECTOR = 'input[placeholder*="填写作品标题"]'
DESCRIPTION_SELECTOR = 'div.zone-container[contenteditable="true"]'


def _fixed(seconds: float) -> LogNormal:
    return LogNormal(0.0, 0.0, seconds, seconds)


#: 固定停顿表：5.0s 只可能是 after_type，7.0s 只可能是 before_submit。
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
            "box", {"x": 10.0, "y": 20.0, "width": 80.0, "height": 24.0}
        )
        super().__init__(name, **kwargs)
        self._log = log
        self._page = None

    async def evaluate(self, expression, arg=None):
        self.evaluate_calls.append((expression, arg))
        kind = _expr_kind(expression)
        self._log.append(("evaluate", kind, self.name))
        if kind == "hit-test":
            if self._page is not None:
                self._page.focused = self
            return {"self": True, "tag": "div", "className": "", "id": "", "text": ""}
        if kind == "geometry":
            return {
                "width": 80.0,
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


class _TypingClickable(_Clickable):
    """持有键入缓冲的 locator；键盘事件写回当前 focus 的实例。"""

    def __init__(self, name: str, *, log: list, initial: str = "", **kwargs):
        self.multiline = kwargs.pop("multiline", True)
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
        if key in ("ControlOrMeta+A", "Control+A", "Control+KeyA", "Meta+A"):
            page.selected = True
        elif key in ("Delete", "Backspace"):
            if page.selected:
                self.buffer = ""
            elif key == "Backspace":
                self.buffer = self.buffer[:-1]
            page.selected = False
        elif key == "Enter":
            if self.multiline:
                self.buffer += "\n"
        elif key == "Space":
            if page.selected:
                self.buffer = " "
                page.selected = False
            else:
                self.buffer += " "
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
        self.fail_down = None

    async def move(self, x: float, y: float, **kwargs) -> None:
        self.actions.append(("move", x, y))
        self._log.append(("move", x, y))

    async def down(self, **kwargs) -> None:
        self.actions.append(("down",))
        self.down_count += 1
        self._log.append(("down",))
        if self.fail_down is not None:
            error, self.fail_down = self.fail_down, None
            raise error

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
    """带确定顺序日志与 focus 键盘的 page double。"""

    def __init__(self, *, log: list, **kwargs) -> None:
        self.interactions = log
        super().__init__(**kwargs)
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


def _attach(page: _RegexPage, locator: FakeLocator) -> None:
    if isinstance(locator, _Clickable):
        locator._page = page
    for child in locator._children.values():
        _attach(page, child)


def _page(selectors: dict[str, FakeLocator], *, log: list | None = None) -> _RegexPage:
    log = [] if log is None else log
    page = _RegexPage(log=log, selectors=selectors)
    for locator in selectors.values():
        _attach(page, locator)
    return page


class _QuietHumanizer(douyin_main.Humanizer):
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


@contextmanager
def _humanized():
    with patch.object(douyin_main, "Humanizer", _QuietHumanizer):
        yield


def _video(tmp: str, **overrides) -> douyin_main.DouYinVideo:
    values = {
        "title": "标题",
        "file_path": str(Path(tmp) / "clip.mp4"),
        "tags": [],
        "publish_date": 0,
        "account_file": str(Path(tmp) / "account.json"),
    }
    values.update(overrides)
    return douyin_main.DouYinVideo(**values)


def _note(tmp: str, **overrides) -> douyin_main.DouYinNote:
    values = {
        "image_paths": [str(Path(tmp) / "a.png")],
        "note": "正文",
        "tags": [],
        "publish_date": 0,
        "account_file": str(Path(tmp) / "account.json"),
    }
    values.update(overrides)
    return douyin_main.DouYinNote(**values)


def _down_after(log: list, marker) -> int:
    """``marker`` 之后第一次 ``mouse.down`` 的下标（证明 stillOn 先于派发）。"""
    start = log.index(marker)
    for index in range(start + 1, len(log)):
        if log[index] == ("down",):
            return index
    raise AssertionError(f"no mouse.down after {marker!r}")


# ---------------------------------------------------------------------------
# 1. 事件序列
# ---------------------------------------------------------------------------


class HumanizeEventSequenceTests(unittest.TestCase):
    def test_title_description_and_topic_use_real_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _video(tmp, title="标题", desc="正文", tags=["话题"])
            log: list = []
            title = _TypingClickable("title", log=log)
            editor = _TypingClickable("editor", log=log, initial="旧正文")
            page = _page(
                {TITLE_SELECTOR: title, DESCRIPTION_SELECTOR: editor}, log=log
            )

            with _humanized():
                asyncio.run(
                    app.fill_title_and_description(page, "标题", "正文", ["话题"])
                )

            humanizer = app._humanizer_instance
            # 标题：sel（全选 + Delete）后逐字；描述：seq 键序不变，全选键
            # 必须是 macOS 也生效的 ControlOrMeta+A。
            self.assertEqual(
                page.keyboard.actions[:8],
                [
                    ("press", "ControlOrMeta+A"),
                    ("press", "Delete"),
                    ("insert_text", "标"),
                    ("insert_text", "题"),
                    ("press", "ControlOrMeta+A"),
                    ("press", "Delete"),
                    ("insert_text", "正"),
                    ("insert_text", "文"),
                ],
            )
            # 话题：逐字 " #话题" 后再按 Space（不做整段插入）。
            self.assertEqual(
                page.keyboard.actions[-6:],
                [
                    ("press", " "),
                    ("press", "#"),
                    ("insert_text", "话"),
                    ("insert_text", "题"),
                    ("press", "Space"),
                    ("press", "Escape"),
                ],
            )
            # 每个文本点恰一次 after_type：标题、描述、话题。
            self.assertEqual(humanizer.pauses.count(AFTER_TYPE), 3)
            # 两个文本点都是坐标点击，零原生 locator.click。
            self.assertEqual(title.click_count, 0)
            self.assertEqual(editor.click_count, 0)
            self.assertEqual(page.mouse.down_count, 2)
            for name in ("title", "editor"):
                marker = ("evaluate", "hit-test", name)
                self.assertIn(marker, log)
                self.assertLess(log.index(marker), _down_after(log, marker))

    def test_schedule_time_selects_all_then_enters(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _video(tmp)
            log: list = []
            label = _Clickable("schedule-label", log=log)
            picker = _TypingClickable(
                "picker", log=log, initial="2026-01-01 00:00", multiline=False
            )
            page = _page(
                {
                    "[class^='radio']:has-text('定时发布')": label,
                    '.semi-input[placeholder="日期和时间"]': picker,
                },
                log=log,
            )
            when = datetime(2026, 11, 15, 10, 30, tzinfo=timezone.utc)

            with _humanized():
                asyncio.run(app.set_schedule_time_douyin(page, when))

            self.assertEqual(
                page.keyboard.actions,
                [
                    ("press", "ControlOrMeta+A"),
                    ("press", "2"),
                    ("press", "0"),
                    ("press", "2"),
                    ("press", "6"),
                    ("press", "-"),
                    ("press", "1"),
                    ("press", "1"),
                    ("press", "-"),
                    ("press", "1"),
                    ("press", "5"),
                    ("press", " "),
                    ("press", "1"),
                    ("press", "0"),
                    ("press", ":"),
                    ("press", "3"),
                    ("press", "0"),
                    ("press", "Enter"),
                ],
            )
            # picker 预填值被全选覆盖，没有残留。
            self.assertEqual(picker.buffer, "2026-11-15 10:30")
            self.assertEqual(label.click_count, 0)
            self.assertEqual(picker.click_count, 0)
            self.assertEqual(page.mouse.down_count, 2)

    def test_location_types_then_clicks_exact_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _video(tmp)
            log: list = []
            trigger = _Clickable("location-trigger", log=log)
            wrong = _Clickable("location-wrong", log=log)
            exact = _Clickable("location-exact", log=log)
            options = FakeLocator(
                "options", count=2, children={"text:上海:exact": exact}
            )
            page = _page(
                {
                    'div.semi-select span:has-text("输入地理位置")': trigger,
                    'div[role="listbox"] [role="option"]': options,
                },
                log=log,
            )

            with _humanized():
                asyncio.run(app.set_location(page, "上海"))

            self.assertEqual(
                page.keyboard.actions,
                [
                    ("press", "Backspace"),
                    ("insert_text", "上"),
                    ("insert_text", "海"),
                ],
            )
            self.assertEqual(page.mouse.down_count, 2)
            self.assertEqual(trigger.click_count, 0)
            self.assertEqual(exact.click_count, 0)
            self.assertEqual(wrong.click_count, 0)

    def test_declaration_entry_option_and_confirm_are_humanized(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _video(tmp, declaration="内容由AI生成")
            log: list = []
            entry = _Clickable("declaration-entry", log=log)
            option = _Clickable("declaration-option", log=log)
            confirm = _Clickable("declaration-confirm", log=log)
            dialog = _Clickable(
                "declaration-dialog",
                log=log,
                children={
                    "label.semi-radio": option,
                    "button.semi-button-primary": confirm,
                },
            )
            page = _page(
                {
                    "text:请选择自主声明": entry,
                    ".semi-modal-content": dialog,
                    '.semi-radio-addon:text-is("内容由AI生成")': FakeLocator(
                        "declaration-radio-addon"
                    ),
                },
                log=log,
            )

            with _humanized():
                ok = asyncio.run(app.set_self_declaration(page, "内容由AI生成"))

            self.assertTrue(ok)
            self.assertEqual(page.mouse.down_count, 3)
            self.assertEqual(entry.click_count, 0)
            self.assertEqual(option.click_count, 0)
            self.assertEqual(confirm.click_count, 0)
            self.assertEqual(
                [event for event in log if event == ("down",)],
                [("down",), ("down",), ("down",)],
            )

    def test_bgm_hovers_card_before_clicking_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _note(tmp)
            log: list = []
            entry = _Clickable("music-entry", log=log)
            search = _TypingClickable("music-search", log=log)
            card = _Clickable("music-card", log=log)
            song = FakeLocator("song-name", count=0)
            apply_btn = _Clickable("music-apply", log=log)
            sidesheet = _Clickable(
                "sidesheet",
                log=log,
                children={
                    'input.semi-input[placeholder="搜索音乐"]': search,
                    ".card-container-tmocjc": card,
                },
            )
            card._children[".song-name-oRge4d"] = song
            card._children[".apply-btn-LUPP0D"] = apply_btn
            entry_list = FakeLocator(
                "music-entries", items=[FakeLocator("hidden", count=0), entry]
            )
            # items 里第一个用缺席 entry 模拟 nth(1) 命中可见按钮。
            page = _page(
                {
                    'text="选择音乐"': entry_list,
                    ".semi-sidesheet-content": sidesheet,
                },
                log=log,
            )

            with _humanized():
                ok = asyncio.run(app.select_bgm(page, "轻音乐"))

            self.assertTrue(ok)
            # 卡片只 hover、不点击；「使用」按钮才派发 down。
            self.assertEqual(card.click_count, 0)
            self.assertEqual(apply_btn.click_count, 0)
            self.assertEqual(page.mouse.down_count, 3)  # 入口 + 搜索框 + 使用
            hit = ("evaluate", "hit-test", "music-apply")
            self.assertIn(hit, log)
            self.assertLess(log.index(hit), _down_after(log, hit))
            # hover 卡片发生在「使用」点击之前（同一 mouse 日志里先有移动）。
            self.assertIn(("move",), [event[:1] for event in log])
            self.assertEqual(
                [key for key in page.keyboard.actions if key[0] == "insert_text"],
                [("insert_text", "轻"), ("insert_text", "音"), ("insert_text", "乐")],
            )

    def test_bgm_hidden_after_hover_raises_instead_of_js_click(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _note(tmp)
            log: list = []
            entry = _Clickable("music-entry", log=log)
            search = _TypingClickable("music-search", log=log)
            card = _Clickable("music-card", log=log)
            hidden_apply = FakeLocator(
                "music-apply-hidden",
                visible=False,
                box={"x": 10.0, "y": 20.0, "width": 80.0, "height": 24.0},
            )
            sidesheet = _Clickable(
                "sidesheet",
                log=log,
                children={
                    'input.semi-input[placeholder="搜索音乐"]': search,
                    ".card-container-tmocjc": card,
                },
            )
            card._children[".apply-btn-LUPP0D"] = hidden_apply
            page = _page(
                {
                    'text="选择音乐"': FakeLocator(
                        "music-entries",
                        items=[FakeLocator("hidden", count=0), entry],
                    ),
                    ".semi-sidesheet-content": sidesheet,
                },
                log=log,
            )

            with _humanized(), self.assertRaises(ElementUnusableError) as ctx:
                asyncio.run(app.select_bgm(page, "轻音乐"))

            self.assertEqual(ctx.exception.reason, "hidden-after-hover")
            self.assertEqual(hidden_apply.click_count, 0)
            # 卡片仍只 hover；「使用」按钮没有派发 down（入口 + 搜索框各一次）。
            self.assertEqual(card.click_count, 0)
            self.assertEqual(page.mouse.down_count, 2)

    def test_image_publish_waits_before_submit(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _note(tmp, note="正文")
            log: list = []
            tab = _Clickable("image-tab", log=log)
            upload = FakeLocator("image-input")
            publish = _Clickable("publish", log=log)
            page = _page(
                {
                    "text:发布图文:exact": tab,
                    "div[class^='container'] input[accept*='image']": upload,
                    "role:button:发布": publish,
                },
                log=log,
            )
            app.fill_title_and_description = AsyncMock()

            with _humanized():
                asyncio.run(app.upload_note_content(page))

            self.assertEqual(tab.click_count, 0)
            self.assertEqual(publish.click_count, 0)
            self.assertEqual(page.mouse.down_count, 2)
            # 导航后停顿 + 提交前停顿各一次。
            pause_events = [event for event in log if event[0] == "pause"]
            self.assertIn(("pause", AFTER_NAVIGATE), pause_events)
            before = log.index(("pause", BEFORE_SUBMIT))
            self.assertLess(before, _down_after(log, ("pause", BEFORE_SUBMIT)))
            self.assertLess(
                log.index(("evaluate", "hit-test", "publish")),
                _down_after(log, ("evaluate", "hit-test", "publish")),
            )
            self.assertEqual(app._humanizer_instance.pauses.count(BEFORE_SUBMIT), 1)


# ---------------------------------------------------------------------------
# 2. 字段值读回
# ---------------------------------------------------------------------------


class HumanizeFieldReadbackTests(unittest.TestCase):
    def test_existing_values_are_cleared_before_typing(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _video(tmp)
            log: list = []
            title = _TypingClickable("title", log=log, initial="旧标题")
            editor = _TypingClickable("editor", log=log, initial="旧正文")
            page = _page(
                {TITLE_SELECTOR: title, DESCRIPTION_SELECTOR: editor}, log=log
            )

            with _humanized():
                asyncio.run(
                    app.fill_title_and_description(page, "新标题", "新正文", [])
                )

            self.assertEqual(title.buffer, "新标题")
            self.assertEqual(editor.buffer, "新正文")
            self.assertNotIn("旧", editor.buffer)

    def test_topic_input_appends_after_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _video(tmp)
            log: list = []
            title = _TypingClickable("title", log=log)
            editor = _TypingClickable("editor", log=log, initial="旧正文")
            page = _page(
                {TITLE_SELECTOR: title, DESCRIPTION_SELECTOR: editor}, log=log
            )

            with _humanized():
                asyncio.run(
                    app.fill_title_and_description(page, "标题", "正文", ["话题"])
                )

            self.assertEqual(editor.buffer, "正文 #话题 ")


# ---------------------------------------------------------------------------
# 「maybe 已派发」→ 不再二次派发
# ---------------------------------------------------------------------------


class HumanizeMaybeDispatchedTests(unittest.TestCase):
    def test_maybe_dispatched_does_not_click_collection_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _video(tmp, collection_name="合集A")
            log: list = []
            selection = _Clickable("collection-selection", log=log)
            trigger = _Clickable(
                "collection-trigger",
                log=log,
                children={".semi-select-selection": selection},
            )
            option = _Clickable("collection-option", log=log)
            page = _page(
                {
                    '[class*="select-collection-"]': trigger,
                    ".semi-select-option.collection-option": option,
                },
                log=log,
            )
            page.mouse.fail_down = RuntimeError("down exploded")

            with _humanized():
                asyncio.run(app.apply_collection(page))

            # mouse.down 已发生一次 → 异常带 “maybe”；集合选择不得补点。
            self.assertEqual(page.mouse.down_count, 1)
            self.assertEqual(selection.click_count, 0)
            self.assertEqual(option.click_count, 0)


# ---------------------------------------------------------------------------
# HUMANIZE=0 快路径
# ---------------------------------------------------------------------------


class HumanizeDisabledTests(unittest.TestCase):
    def test_text_is_one_insert_per_field_and_no_pauses(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _video(tmp)
            log: list = []
            title = _TypingClickable("title", log=log, initial="旧标题")
            editor = _TypingClickable("editor", log=log, initial="旧正文")
            page = _page(
                {TITLE_SELECTOR: title, DESCRIPTION_SELECTOR: editor}, log=log
            )

            with _humanized(), patch.dict(os.environ, {"HUMANIZE": "0"}):
                asyncio.run(
                    app.fill_title_and_description(page, "新标题", "新正文", [])
                )

            self.assertEqual(
                [action for action in page.keyboard.actions if action[0] == "insert_text"],
                [("insert_text", "新标题"), ("insert_text", "新正文")],
            )
            self.assertEqual(app._humanizer_instance.pauses, [])
            self.assertEqual(page.mouse.down_count, 0)
            self.assertEqual(title.click_count, 1)
            self.assertEqual(editor.click_count, 1)
            self.assertEqual(title.buffer, "新标题")
            self.assertEqual(editor.buffer, "新正文")


# ---------------------------------------------------------------------------
# 3. 平台静态门
# ---------------------------------------------------------------------------


class HumanizeGateTests(unittest.TestCase):
    def test_douyin_package_passes_gates_a_to_e(self):
        package = (
            Path(__file__).resolve().parent.parent
            / "uploader"
            / "douyin_uploader"
        )
        assert_clean(package)

    def test_select_all_never_uses_the_windows_only_shortcut(self):
        # spec §2.4：``Control+KeyA`` 在 macOS 上不清空预填字段（仓库
        # ``tk_uploader/main_chrome.py`` 已记录该坑）。抖音的 ``sel``（定时
        # picker）与 ``seq``（描述编辑器）都必须用 ``ControlOrMeta+A``。
        package = (
            Path(__file__).resolve().parent.parent
            / "uploader"
            / "douyin_uploader"
        )
        offenders: list[str] = []
        for path in sorted(package.rglob("*.py")):
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if "Control+KeyA" in line:
                    offenders.append(
                        f"{path.relative_to(package)}:{number}: {line.strip()}"
                    )
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
