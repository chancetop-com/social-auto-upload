# -*- coding: utf-8 -*-
"""Tencent / 视频号 人类化接线（spec §3.10 / §6.2）。

三块，全部离线：

1. 事件序列 —— 每个改 Humanizer 的点断言原语（``press`` / ``insert_text``）、
   ``after_type`` 次数、``mouse.move* → down → up``、hit-test 先于 ``down``、
   零原生 ``locator.click()``、零 ``force``。
2. 字段值读回 —— fake 键盘把按键写回持有缓冲的 locator，断言最终值与预期
   完全相等（短标题与描述是两个字段；预填的小时 picker 必须整体替换）。
3. 平台静态门 —— 包内跑 spec §4.2–4.5 的 A–E 门。

覆盖 ``HUMANIZE=0`` 快路径。选择器未 scripted 直接抛
:class:`UnscriptedSelectorError`，不用 MagicMock 掩盖选择器漂移。
"""

from __future__ import annotations

import asyncio
import os
import random
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import uploader.tencent_uploader.main as tencent_main
from tests.fakes_xhs_dom import (
    FakeLocator,
    RecordingKeyboard,
    RecordingLocator,
    RecordingMouse,
    RecordingPage,
    UnscriptedSelectorError,
)
from tests.humanize_gates import assert_clean
from utils.humanize import HumanizeProfile, LogNormal

AFTER_TYPE = 5.0
BEFORE_SUBMIT = 7.0

SHORT_TITLE_SELECTOR = 'input[placeholder="填写短标题有机会获得更多流量"]'
EDITOR_SELECTOR = "div.input-editor"
DATE_SELECTOR = 'input[placeholder="请选择发表时间"]'
TIME_SELECTOR = 'input[placeholder="请选择时间"]'
MONTH_LABEL_SELECTOR = 'span.weui-desktop-picker__panel__label:has-text("月")'
NEXT_MONTH_SELECTOR = "button.weui-desktop-btn__icon__right"
CELLS_SELECTOR = "table.weui-desktop-picker__table a"
COLLECTION_TRIGGER = "text:添加到合集"
COLLECTION_DROPDOWN_XPATH = "xpath=following-sibling::div"
COLLECTION_ITEMS = ".option-list-wrap .option-item"


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
            "box", {"x": 10.0, "y": 20.0, "width": 120.0, "height": 32.0}
        )
        super().__init__(name, **kwargs)
        self._log = log
        self._page = None

    async def evaluate(self, expression, arg=None):
        self.evaluate_calls.append((expression, arg))
        kind = _expr_kind(expression)
        self._log.append(("evaluate", kind, self.name))
        if kind == "hit-test":
            # 真实浏览器里点击落点会聚焦可输入元素；stillOn 命中即等价于此。
            if self._page is not None:
                self._page.last_hit = self
            return {"self": True, "tag": "div", "className": "", "id": "", "text": ""}
        if kind == "geometry":
            return {
                "width": 120.0,
                "height": 32.0,
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

    async def dispatch_event(self, *args, **kwargs) -> None:
        raise AssertionError(
            f"{self.name}: dispatch_event 不允许出现（禁止 JS 合成点击兜底）"
        )


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

    async def inner_text(self) -> str:
        return self.buffer

    async def input_value(self) -> str:
        return self.buffer

    async def click(self, **kwargs) -> None:
        await super().click(**kwargs)
        if self._page is not None:
            self._page.focused = self
            self._page.selected = False

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
        elif key == "Space":
            self.buffer += " "
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


class _PickerLocator(_TypingLocator):
    """时间 picker 的输入框：Enter 只确认下拉，不改写输入值。"""

    def apply_key(self, key: str) -> None:
        if key == "Enter":
            return
        super().apply_key(key)


class _OrderedMouse(RecordingMouse):
    def __init__(self, log: list, page: "_TencentPage | None" = None) -> None:
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
        page = self._page
        if page is not None and page.last_hit is not None:
            page.focused = page.last_hit
            page.selected = False

    async def up(self, **kwargs) -> None:
        self.actions.append(("up",))
        self.up_count += 1
        self._log.append(("up",))
        page = self._page
        if page is not None and page.url_after_first_up:
            page.url = page.url_after_first_up
            page.main_frame.url = page.url_after_first_up
            page.url_after_first_up = None


class _TypingKeyboard(RecordingKeyboard):
    def __init__(self, page: "_TencentPage") -> None:
        super().__init__()
        self._page = page

    async def press(self, key: str, **kwargs) -> None:
        self.actions.append(("press", key))
        self._page.apply_key(key)

    async def insert_text(self, text: str, **kwargs) -> None:
        self.actions.append(("insert_text", text))
        self._page.apply_text(text)


class _TencentPage(RecordingPage):
    """带确定顺序日志与 focus 键盘的 page double。"""

    def __init__(self, *, log: list, **kwargs) -> None:
        self.interactions = log
        super().__init__(**kwargs)
        self.last_hit = None
        self.url_after_first_up = None
        self.mouse = _OrderedMouse(log, self)
        self.keyboard = _TypingKeyboard(self)
        self.focused = None
        self.selected = False
        self.inner_texts: dict[str, str] = {}

    async def inner_text(self, selector: str) -> str:
        try:
            return self.inner_texts[selector]
        except KeyError as exc:
            raise UnscriptedSelectorError(
                f"page: un-scripted inner_text({selector!r}); "
                f"scripted: {sorted(self.inner_texts)}"
            ) from exc

    def get_by_role(self, role: str, name=None, exact: bool = False):
        return super().get_by_role(role, name)

    def apply_key(self, key: str) -> None:
        if self.focused is not None:
            self.focused.apply_key(key)

    def apply_text(self, text: str) -> None:
        if self.focused is not None:
            self.focused.apply_text(text)


def _attach(page: _TencentPage, locator: FakeLocator) -> None:
    if isinstance(locator, _Clickable):
        locator._page = page
    for child in locator._children.values():
        _attach(page, child)


def _page(
    selectors: dict[str, FakeLocator], *, log: list | None = None
) -> _TencentPage:
    log = [] if log is None else log
    page = _TencentPage(log=log, selectors=selectors)
    for locator in selectors.values():
        _attach(page, locator)
    return page


class _QuietHumanizer(tencent_main.Humanizer):
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


def _humanized():
    return patch.object(tencent_main, "Humanizer", _QuietHumanizer)


def _video(**overrides) -> tencent_main.TencentVideo:
    values = {
        "title": "测试短标题内容",
        "file_path": "clip.mp4",
        "tags": ["标签一"],
        "publish_date": 0,
        "account_file": "/tmp/tencent-account.json",
        "desc": "正文内容",
    }
    values.update(overrides)
    return tencent_main.TencentVideo(**values)


def _downs_before(log: list, marker: tuple) -> int:
    """``marker`` 之前出现过多少次 mouse.down（用于证明 stillOn 先于派发）。"""

    index = log.index(marker)
    return sum(1 for event in log[:index] if event == ("down",))


# ---------------------------------------------------------------------------
# 1. 事件序列
# ---------------------------------------------------------------------------


class HumanizeEventSequenceTests(unittest.TestCase):
    def test_description_typing_is_humanized_with_one_after_type_per_write(self):
        app = _video()
        log: list = []
        editor = _TypingLocator("description", log=log, initial="平台预填描述")
        page = _page({EDITOR_SELECTOR: editor}, log=log)

        with _humanized():
            asyncio.run(app.fill_title_and_tags(page))
            asyncio.run(app.fill_description(page))

        humanizer = app._humanizer_instance
        # 标题 / 话题 / 正文各一次 after_type；press 不付 after_type。
        self.assertEqual(
            humanizer.pauses.count(AFTER_TYPE), 1 + len(app.tags) + 1
        )
        # 标题与话题走真实按键；中文逐字 insert_text。
        self.assertIn(("press", "#"), page.keyboard.actions)
        self.assertIn(("insert_text", "测"), page.keyboard.actions)
        self.assertIn(("press", "Space"), page.keyboard.actions)
        # 描述区是坐标点击：移动 → down → up，stillOn 命中测试先于 down。
        self.assertEqual(page.mouse.down_count, 1)
        self.assertEqual(editor.click_count, 0)
        self.assertLess(
            log.index(("evaluate", "hit-test", "description")),
            log.index(("down",)),
        )
        self.assertEqual(_downs_before(log, ("evaluate", "hit-test", "description")), 0)

    def test_schedule_controls_are_humanized_and_hour_is_replaced(self):
        app = _video()
        log: list = []
        toggle_a = _Clickable("toggle-a", log=log)
        toggle_b = _Clickable("schedule-toggle", log=log)
        labels = FakeLocator("labels", items=[toggle_a, toggle_b])
        date_field = _Clickable("date-field", log=log)
        next_month = _Clickable("next-month", log=log)
        day = _Clickable("day", log=log, text="15")
        cells = FakeLocator("cells", items=[day])
        time_field = _PickerLocator("time-field", log=log, initial="09")
        overlay_target = _Clickable("overlay-target", log=log)
        page = _page(
            {
                "label": labels,
                DATE_SELECTOR: date_field,
                NEXT_MONTH_SELECTOR: next_month,
                CELLS_SELECTOR: cells,
                TIME_SELECTOR: time_field,
                EDITOR_SELECTOR: overlay_target,
            },
            log=log,
        )
        # 日历停在目标月份前一个月，强制走一次「下月」人类化点击；日格 15 可选。
        page.inner_texts[MONTH_LABEL_SELECTOR] = "11月"
        schedule = datetime(2026, 12, 15, 8, 30, tzinfo=timezone.utc)

        with _humanized():
            asyncio.run(app.set_schedule_time_tencent(page, schedule))

        # 定时开关 / 日期面板 / 时间下拉 / 日 / 收起浮层的焦点点击。
        self.assertEqual(page.mouse.down_count, 5)
        for locator in (toggle_b, date_field, next_month, day, time_field):
            self.assertEqual(locator.click_count, 0)
        # 焦点点击必须保持原生（不是 Humanizer）。
        self.assertEqual(overlay_target.click_count, 1)
        self.assertEqual(overlay_target.click_calls[0].get("timeout"), 5000)
        # 预填小时整体替换：全选 → 删除 → 逐字输入 → Enter 确认。
        prefix = page.keyboard.actions[:3]
        self.assertEqual(
            prefix,
            [
                ("press", "ControlOrMeta+A"),
                ("press", "Delete"),
                ("press", "0"),
            ],
        )
        self.assertIn(("press", "8"), page.keyboard.actions)
        self.assertIn(("press", "Enter"), page.keyboard.actions)
        self.assertEqual(time_field.buffer, "08")

    def test_collection_uses_exact_name_and_never_forces(self):
        app = _video(collection_name="我的合集")
        log: list = []
        dropdown = _Clickable("collection-dropdown", log=log)
        item = _Clickable("collection-item", log=log)
        trigger = FakeLocator(
            "collection-trigger", children={COLLECTION_DROPDOWN_XPATH: dropdown}
        )
        dropdown._children[COLLECTION_ITEMS] = item
        page = _page(
            {
                COLLECTION_TRIGGER: trigger,
                '.name:text-is("我的合集")': FakeLocator("name"),
            },
            log=log,
        )

        with _humanized():
            asyncio.run(app.apply_collection(page))

        # 下拉 + 合集项两次坐标点击；零原生 click，零 force。
        self.assertEqual(page.mouse.down_count, 2)
        self.assertEqual(dropdown.click_count, 0)
        self.assertEqual(item.click_count, 0)
        self.assertEqual(item.click_calls, [])
        # 合集项按精确 `.name` 过滤（不是随机第一项）。
        self.assertEqual(len(item.filter_calls), 1)
        self.assertIn("has", item.filter_calls[0])

    def test_publish_waits_before_submit_then_clicks_without_js_fallback(self):
        app = _video()
        log: list = []
        publish = _Clickable("publish", log=log)
        page = _page(
            {
                "role:button:发表": publish,
                '.changeAccount-dialog button:has-text("取消")': FakeLocator(
                    "switch-cancel", count=0
                ),
                ".changeAccount-dialog .weui-desktop-dialog__close-btn": FakeLocator(
                    "switch-close", count=0
                ),
            },
            log=log,
        )
        page.url = "https://channels.weixin.qq.com/platform/post/create"
        page.url_after_first_up = (
            "https://channels.weixin.qq.com/platform/post/list"
        )
        app.publish_not_before = None
        app._publish_budget = app.start_publish_budget()

        with _humanized():
            asyncio.run(app.submit_publish(page))

        self.assertEqual(page.mouse.down_count, 1)
        self.assertEqual(publish.click_count, 0)
        self.assertLess(
            log.index(("pause", BEFORE_SUBMIT)), log.index(("down",))
        )
        self.assertLess(
            log.index(("evaluate", "hit-test", "publish")),
            log.index(("down",)),
        )
        # 发布按钮的 JS 兜底已删除：evaluate 里不得出现任何 click 合成。
        for expression, _arg in page.evaluate_calls:
            self.assertNotIn("click", str(expression))
            self.assertNotIn("el =>", str(expression))


# ---------------------------------------------------------------------------
# 2. 字段值读回
# ---------------------------------------------------------------------------


class HumanizeFieldReadbackTests(unittest.TestCase):
    def test_short_title_and_description_are_distinct_fields(self):
        app = _video()
        log: list = []
        short_title = _TypingLocator(
            "short-title", log=log, initial="旧的短标题"
        )
        editor = _TypingLocator("description", log=log, initial="平台默认描述")
        page = _page(
            {SHORT_TITLE_SELECTOR: short_title, EDITOR_SELECTOR: editor},
            log=log,
        )

        with _humanized():
            asyncio.run(app.set_short_title(page, app.title, None))
            asyncio.run(app.fill_title_and_tags(page))
            asyncio.run(app.fill_description(page))

        # 短标题是独立 input：7–15 字，且不含描述正文。
        self.assertEqual(short_title.buffer, "测试短标题内容")
        # 大编辑区是视频描述：预填值被 guard 清掉，标题 + 话题 + 正文追加。
        self.assertEqual(
            editor.buffer, "测试短标题内容\n#标签一 \n正文内容"
        )
        self.assertNotEqual(short_title.buffer, editor.buffer)

    def test_prefilled_description_is_cleared_before_typing(self):
        app = _video(tags=[], desc="")
        log: list = []
        editor = _TypingLocator("description", log=log, initial="平台预填描述")
        page = _page({EDITOR_SELECTOR: editor}, log=log)

        with _humanized():
            asyncio.run(app.fill_title_and_tags(page))

        self.assertEqual(editor.buffer, "测试短标题内容\n")
        self.assertNotIn("平台预填描述", editor.buffer)

    def test_ambiguous_description_fails_before_any_dispatch(self):
        app = _video()
        log: list = []
        editor = _TypingLocator("description", log=log, count=2)
        page = _page({EDITOR_SELECTOR: editor}, log=log)

        with _humanized(), self.assertRaises(Exception) as ctx:
            asyncio.run(app.fill_title_and_tags(page))

        self.assertEqual(getattr(ctx.exception, "reason", None), "ambiguous:2")
        self.assertEqual(page.mouse.down_count, 0)


# ---------------------------------------------------------------------------
# HUMANIZE=0 快路径
# ---------------------------------------------------------------------------


class HumanizeDisabledTests(unittest.TestCase):
    def test_text_is_one_insert_and_clicks_are_native(self):
        app = _video()
        log: list = []
        short_title = _TypingLocator("short-title", log=log)
        editor = _TypingLocator("description", log=log)
        page = _page(
            {SHORT_TITLE_SELECTOR: short_title, EDITOR_SELECTOR: editor},
            log=log,
        )

        with _humanized(), patch.dict(os.environ, {"HUMANIZE": "0"}):
            asyncio.run(app.set_short_title(page, app.title, None))
            asyncio.run(app.fill_title_and_tags(page))
            asyncio.run(app.fill_description(page))

        inserts = [
            action for action in page.keyboard.actions
            if action[0] == "insert_text"
        ]
        self.assertEqual(
            inserts,
            [
                ("insert_text", "测试短标题内容"),
                ("insert_text", "测试短标题内容"),
                ("insert_text", "#标签一"),
                ("insert_text", "正文内容"),
            ],
        )
        # 点击退回原生 locator.click()，零指针轨迹。
        self.assertEqual(short_title.click_count, 1)
        self.assertEqual(editor.click_count, 1)
        self.assertEqual(page.mouse.down_count, 0)
        self.assertEqual(app._humanizer_instance.pauses, [])


# ---------------------------------------------------------------------------
# 3. 平台静态门
# ---------------------------------------------------------------------------


class HumanizeGateTests(unittest.TestCase):
    def test_tencent_package_passes_gates_a_to_e(self):
        package = (
            Path(__file__).resolve().parent.parent
            / "uploader"
            / "tencent_uploader"
        )
        assert_clean(package)


if __name__ == "__main__":
    unittest.main()
