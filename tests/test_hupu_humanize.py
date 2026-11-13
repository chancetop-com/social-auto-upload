# -*- coding: utf-8 -*-
"""虎扑 人类化接线（ticket 18, spec §3.5 / §6.2）。

三块，全部离线：

1. 事件序列 —— 标题/简介逐字（中文 ``insert_text``、ASCII 含 ``#`` 走
   ``press``）、每字段恰一次 ``after_type``、每个可见点击
   ``mouse.move* → down → up`` 且 hit-test 先于 ``down``、发布前
   ``before_submit``、零原生 ``locator.click()``、零 ``force``。
2. 字段值读回 —— fake 键盘持有键入缓冲，断言最终值与预期完全相等
   （专抓「序列对、值错」：清空不净导致追加）；简介 >1000 码点整段
   ``insert_text`` 一次。
3. 平台静态门 —— 包内跑 spec §4.2–4.5 的 A–E 门；登录与两个文件入口
   的原生点击标记仍在。

另覆盖 AI 声明下拉的多义硬错（``ambiguous:N``）与 ``HUMANIZE=0`` 快路径。
选择器未 scripted 直接抛 :class:`UnscriptedSelectorError`，不用 MagicMock
掩盖选择器漂移。
"""

from __future__ import annotations

import ast
import asyncio
import os
import random
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import uploader.hupu_uploader.main as hupu_main
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
from utils.humanize import HumanizeProfile, LogNormal
from utils.humanize import MAYBE_DISPATCHED, MAYBE_DISPATCHED_VALUE

PACKAGE = Path(__file__).resolve().parent.parent / "uploader" / "hupu_uploader"

TITLE_PLACEHOLDER = "请输入标题（最少4个字，最多40个字）"
DESC_PLACEHOLDER = "请输入简介"

AFTER_TYPE = 5.0
BEFORE_SUBMIT = 7.0
AFTER_NAVIGATE = 3.0

#: ``utils/dom.py`` ``_FACTS_JS`` 形状；每个点击目标都要能回答。
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


def _fixed(seconds: float) -> LogNormal:
    return LogNormal(0.0, 0.0, seconds, seconds)


#: 固定停顿表：只有 when_type/7.0s 等确定值进入日志，不读墙钟。
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
            "box", {"x": 10.0, "y": 20.0, "width": 120.0, "height": 32.0}
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
                "width": 120.0,
                "height": 32.0,
                "inside": True,
                "clipped": False,
                "childFrame": False,
            }
        return dict(FACTS)

    async def scroll_into_view_if_needed(self, **kwargs) -> None:
        self.actions.append(("scroll",))

    async def dispatch_event(self, *args, **kwargs) -> None:
        raise AssertionError(
            f"{self.name}: dispatch_event 不允许出现（禁止 JS 合成点击兜底）"
        )


class _OrderedMouse(RecordingMouse):
    """把 move/down/up 同时写进共享顺序日志（证明 hit-test 先于 down）。"""

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


class _BufferKeyboard(RecordingKeyboard):
    """持有键入缓冲的键盘 double：全选 + Delete 关闭当前字段。"""

    def __init__(self, log: list | None = None, initial: str = "") -> None:
        super().__init__()
        self._log = log
        self.current = initial
        self.values: list[str] = []
        self._selected = False
        self._typed = False

    def _record(self, action: tuple) -> None:
        self.actions.append(action)
        if self._log is not None:
            self._log.append(("keyboard", action))

    async def press(self, key: str, **kwargs) -> None:
        self._record(("press", key))
        if key in ("ControlOrMeta+A", "Control+A"):
            self._selected = True
        elif key == "Delete":
            if self._typed:
                self.values.append(self.current)
            self.current = ""
            self._selected = False
            self._typed = False
        elif key == "Enter":
            self.current += "\n"
            self._typed = True
        elif key in ("Escape", "Tab", "Backspace", "End"):
            pass
        elif len(key) == 1:
            self.current = key if self._selected else self.current + key
            self._selected = False
            self._typed = True

    async def insert_text(self, text: str, **kwargs) -> None:
        self._record(("insert_text", text))
        self.current = text if self._selected else self.current + text
        self._selected = False
        self._typed = True

    async def type(self, text: str, delay: float | None = None, **kwargs) -> None:
        self._record(("type", text, delay))
        self.current += text
        self._typed = True

    def finish(self) -> list[str]:
        if self._typed:
            self.values.append(self.current)
        return self.values


class _HupuPage(RecordingPage):
    """``RecordingPage`` + 虎扑用到的 ``get_by_placeholder`` / ``get_by_label``。"""

    def __init__(self, *, log: list, selectors: dict[str, FakeLocator], keyboard=None,
                 url: str = "about:blank") -> None:
        super().__init__(selectors=selectors, url=url)
        self.interactions = log
        self.mouse = _OrderedMouse(log)
        self.keyboard = keyboard if keyboard is not None else _BufferKeyboard(log)

    def get_by_placeholder(self, text: str) -> FakeLocator:
        key = f"placeholder:{text}"
        try:
            return self._selectors[key]
        except KeyError as exc:
            raise UnscriptedSelectorError(
                f"page: un-scripted get_by_placeholder({text!r}); "
                f"scripted: {sorted(self._selectors)}"
            ) from exc

    def get_by_label(self, text: str) -> FakeLocator:
        key = f"label:{text}"
        try:
            return self._selectors[key]
        except KeyError as exc:
            raise UnscriptedSelectorError(
                f"page: un-scripted get_by_label({text!r}); "
                f"scripted: {sorted(self._selectors)}"
            ) from exc


class _QuietHumanizer(hupu_main.Humanizer):
    """真实原语、固定停顿表、零墙钟；停顿写进共享日志。"""

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
    return patch.object(hupu_main, "Humanizer", _QuietHumanizer)


def _app(**overrides) -> hupu_main.HuPuVideo:
    values = {
        "title": "虎扑测试标题",
        "file_path": "clip.mp4",
        "tags": ["标签一", "标签二"],
        "account_file": "/tmp/hupu-account.json",
        "desc": "正文内容",
    }
    values.update(overrides)
    return hupu_main.HuPuVideo(**values)


def _page(selectors: dict[str, FakeLocator], *, log: list,
          keyboard=None, url: str = "about:blank") -> _HupuPage:
    return _HupuPage(log=log, selectors=selectors, keyboard=keyboard, url=url)


def _typing_page(*, keyboard: _BufferKeyboard, log: list,
                 title: FakeLocator | None = None,
                 desc: FakeLocator | None = None) -> _HupuPage:
    return _page(
        {
            f"placeholder:{TITLE_PLACEHOLDER}": title or _Clickable("title", log=log),
            f"placeholder:{DESC_PLACEHOLDER}": desc or _Clickable("description", log=log),
        },
        log=log,
        keyboard=keyboard,
    )


def _publish_page(log: list) -> tuple[_HupuPage, dict[str, _Clickable]]:
    """专区 → 原创/二创 → AI 声明 → 发布，全链路 scripted。"""
    targets = {
        "add-zone": _Clickable("add-zone", log=log),
        "step-street": _Clickable("step-street", log=log),
        "main-road": _Clickable("main-road", log=log),
        "zone-confirm": _Clickable("zone-confirm", log=log),
        "declaration": _Clickable("declaration", log=log),
        "combobox": _Clickable("combobox", log=log),
        "ai-option": _Clickable("ai-option", log=log),
        "publish": _Clickable("publish", log=log),
    }
    selectors = {
        "label:发视频": FakeLocator(
            "publish-label",
            children={
                "text:添加专区": targets["add-zone"],
                "text:确定发布": targets["publish"],
            },
        ),
        "label:添加专区": FakeLocator(
            "zone-dialog", children={"div": targets["step-street"]}
        ),
        "text:步行街主干道": targets["main-road"],
        "role:button:确 定": targets["zone-confirm"],
        "role:button:原创/二创": targets["declaration"],
        "role:combobox": targets["combobox"],
        "text:含AI生成内容": targets["ai-option"],
    }
    # 发布成功后 URL 立即匹配帖子页，循环退出（否则要等满 15 分钟预算）。
    return (
        _page(selectors, log=log, url="https://bbs.hupu.com/123456.html"),
        targets,
    )


def _index(log: list, marker: tuple) -> int:
    return log.index(marker)


# ---------------------------------------------------------------------------
# 1. 事件序列
# ---------------------------------------------------------------------------


class HupuEventSequenceTests(unittest.TestCase):
    def test_title_and_description_are_typed_per_character(self):
        app = _app()
        log: list = []
        keyboard = _BufferKeyboard(log)
        title = _Clickable("title", log=log)
        desc = _Clickable("description", log=log)
        page = _typing_page(keyboard=keyboard, log=log, title=title, desc=desc)

        with _humanized():
            asyncio.run(app._fill_title(page))
            asyncio.run(app._fill_description(page))

        humanizer = app._humanizer_instance
        # 标题 / 简介各一次 after_type；press 不付 after_type。
        self.assertEqual(humanizer.pauses.count(AFTER_TYPE), 2)

        # 清空是 `sel` 形态：全选 → Delete，然后逐字。
        self.assertEqual(
            keyboard.actions[:2],
            [("press", "ControlOrMeta+A"), ("press", "Delete")],
        )
        self.assertIn(("insert_text", "虎"), keyboard.actions)
        self.assertIn(("press", "#"), keyboard.actions)
        self.assertEqual([a for a in keyboard.actions if a[0] == "type"], [])

        # 两个聚焦点击都走人类化指针；零原生 locator.click。
        self.assertEqual(title.click_count, 0)
        self.assertEqual(desc.click_count, 0)
        self.assertEqual(page.mouse.down_count, 2)
        self.assertEqual(page.mouse.up_count, 2)
        # stillOn 命中测试先于 down，且每次点击各一次。
        kinds = [event for event in log if event[0] == "evaluate"]
        self.assertEqual([k[1] for k in kinds].count("hit-test"), 2)
        first_down = _index(log, ("down",))
        self.assertLess(_index(log, ("evaluate", "hit-test", "title")), first_down)

    def test_zone_declarations_and_publish_go_through_the_pointer(self):
        app = _app()
        log: list = []
        page, targets = _publish_page(log)

        with _humanized():
            asyncio.run(app._select_zone(page))
            asyncio.run(app._check_declarations(page))
            asyncio.run(app._submit_publish(page))

        # 专区 4 击 + 原创/二创 + combobox + 含AI生成内容 + 发布 = 8 次坐标点击。
        self.assertEqual(page.mouse.down_count, 8)
        self.assertEqual(page.mouse.up_count, 8)
        for name, target in targets.items():
            self.assertEqual(target.click_count, 0, f"{name} 不应走原生 click")

        # 发布前 before_submit，且早于发布按钮的 hit-test / down。
        before_submit = _index(log, ("pause", BEFORE_SUBMIT))
        publish_hit = log.index(("evaluate", "hit-test", "publish"))
        publish_down = log.index(
            ("down",), log.index(("evaluate", "hit-test", "publish"))
        )
        self.assertLess(before_submit, publish_hit)
        self.assertLess(publish_hit, publish_down)
        # 只有发布点击前付 before_submit；其余点击不付。
        self.assertEqual(
            [event for event in log if event == ("pause", BEFORE_SUBMIT)],
            [("pause", BEFORE_SUBMIT)],
        )


# ---------------------------------------------------------------------------
# 1b. 发布点击：可能已派发 → 结果未知，绝不二次派发
# ---------------------------------------------------------------------------


class _PublishFailingHumanizer(_QuietHumanizer):
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
        app = _app()
        with patch.object(hupu_main, "Humanizer", lambda page, **kwargs: humanizer):
            app._humanizer_instance = humanizer
            asyncio.run(app._submit_publish(page))

    def test_publish_after_mouse_down_maps_to_unknown(self):
        log: list = []
        page, targets = _publish_page(log)
        humanizer = _PublishFailingHumanizer(page, error=self._maybe_error())

        with self.assertRaises(PublishResultUnknownError):
            self._submit(page, humanizer)

        self.assertEqual(humanizer.dispatches, ["publish"])
        self.assertEqual(targets["publish"].click_count, 0)

    def test_pre_dispatch_publish_failure_propagates(self):
        log: list = []
        page, targets = _publish_page(log)
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
        self.assertEqual(targets["publish"].click_count, 0)


class LoginRedirectPublishAttemptTests(unittest.TestCase):
    """发布点击之后的登录跳转必须带 ``publish_attempted=True``。"""

    def test_pre_click_redirect_is_not_marked_as_dispatched(self):
        page = SimpleNamespace(url="https://passport.hupu.com/pc/login")

        with self.assertRaises(LoginRequiredError) as caught:
            hupu_main._raise_if_login_required(page)

        self.assertFalse(caught.exception.publish_attempted)

    def test_post_click_poll_marks_the_redirect_as_dispatched(self):
        log: list = []
        page, targets = _publish_page(log)
        page.url = "https://bbs.hupu.com/publish"

        class _Redirecting(_QuietHumanizer):
            async def click(self, locator, *, point=None) -> None:
                await super().click(locator, point=point)
                if getattr(locator, "name", "") == "publish":
                    page.url = "https://passport.hupu.com/pc/login"

        app = _app()
        humanizer = _Redirecting(page)
        with patch.object(hupu_main, "Humanizer", lambda page, **kwargs: humanizer):
            app._humanizer_instance = humanizer
            with self.assertRaises(LoginRequiredError) as caught:
                asyncio.run(app._submit_publish(page, multilogin=True))

        self.assertTrue(caught.exception.publish_attempted)
        self.assertEqual(targets["publish"].click_count, 0)


# ---------------------------------------------------------------------------
# 2. 字段值读回
# ---------------------------------------------------------------------------


class HupuFieldValueTests(unittest.TestCase):
    def test_title_and_description_replace_their_previous_values(self):
        app = _app()
        log: list = []
        keyboard = _BufferKeyboard(log, initial="旧内容")
        page = _typing_page(keyboard=keyboard, log=log)

        with _humanized():
            asyncio.run(app._fill_title(page))
            asyncio.run(app._fill_description(page))

        self.assertEqual(
            keyboard.finish(),
            ["虎扑测试标题", "正文内容\n#标签一# #标签二#"],
        )

    def test_description_over_the_horizon_uses_one_bulk_insert(self):
        app = _app(desc="长" * 1001)
        log: list = []
        keyboard = _BufferKeyboard(log)
        page = _typing_page(keyboard=keyboard, log=log)

        with _humanized():
            asyncio.run(app._fill_description(page))

        inserts = [a for a in keyboard.actions if a[0] == "insert_text"]
        self.assertEqual(
            inserts, [("insert_text", "长" * 1001 + "\n#标签一# #标签二#")]
        )
        self.assertEqual(app._humanizer_instance.pauses.count(AFTER_TYPE), 1)


# ---------------------------------------------------------------------------
# 3. AI 声明下拉多义 = 硬错
# ---------------------------------------------------------------------------


class HupuAmbiguousDeclarationTests(unittest.TestCase):
    def test_ambiguous_combobox_is_a_hard_failure(self):
        app = _app()
        log: list = []
        page = _page(
            {
                "role:button:原创/二创": FakeLocator("declaration", count=0),
                "role:combobox": FakeLocator("comboboxes", count=2),
            },
            log=log,
        )

        with _humanized():
            with self.assertRaises(ElementUnusableError) as ctx:
                asyncio.run(app._check_declarations(page))

        self.assertEqual(ctx.exception.reason, "ambiguous:2")
        # 多义在派发前失败：一次鼠标动作都没有，更不能取 .first。
        self.assertEqual(page.mouse.actions, [])
        self.assertEqual(ctx.exception.publish_clicked, False)


# ---------------------------------------------------------------------------
# 4. 静态门 + 原生标记
# ---------------------------------------------------------------------------


class HupuStaticGateTests(unittest.TestCase):
    def test_hupu_package_passes_humanize_gates_a_to_e(self):
        assert_clean(PACKAGE)

    def test_no_fill_el_click_force_or_delay_retreats_remain(self):
        offenders: list[str] = []
        for path in sorted(PACKAGE.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            if "el.click()" in source or "force=True" in source:
                offenders.append(f"{path.name}: JS click / force")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute):
                    continue
                if func.attr == "fill":
                    offenders.append(f"{path.name}:{node.lineno}: fill()")
                if func.attr == "type":
                    delays = [
                        keyword.value.value
                        for keyword in node.keywords
                        if keyword.arg == "delay"
                        and isinstance(keyword.value, ast.Constant)
                    ]
                    if delays:
                        offenders.append(
                            f"{path.name}:{node.lineno}: type(delay={delays[0]})"
                        )
        self.assertEqual(offenders, [])

    def test_login_and_file_entry_keep_native_clicks_with_markers(self):
        source = (PACKAGE / "main.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("# native-click: file"), 2)
        self.assertEqual(source.count("# native-click: login"), 1)


# ---------------------------------------------------------------------------
# 5. HUMANIZE=0 + 实例缓存
# ---------------------------------------------------------------------------


class HupuHumanizeDisabledTests(unittest.TestCase):
    def test_humanize_zero_uses_one_native_click_and_one_insert(self):
        log: list = []
        keyboard = _BufferKeyboard(log)
        title = _Clickable("title", log=log)
        page = _typing_page(keyboard=keyboard, log=log, title=title)
        app = _app()

        async def _no_pause(seconds: float) -> None:
            log.append(("sleep", seconds))

        with patch.dict(os.environ, {"HUMANIZE": "0"}):
            app._humanize_pause = _no_pause
            humanizer = app._humanizer(page)
            self.assertFalse(humanizer.enabled)
            asyncio.run(app._fill_title(page))

        self.assertEqual(title.click_count, 1)
        self.assertEqual(page.mouse.actions, [])
        self.assertEqual(
            [a for a in keyboard.actions if a[0] == "insert_text"],
            [("insert_text", "虎扑测试标题")],
        )
        self.assertEqual([e for e in log if e[0] == "sleep"], [])

    def test_the_humanizer_is_cached_per_page_and_rebuilt_for_a_new_page(self):
        app = _app()
        first = RecordingPage()
        second = RecordingPage()

        self.assertIs(app._humanizer(first), app._humanizer(first))
        self.assertIsNot(app._humanizer(first), app._humanizer(second))


if __name__ == "__main__":
    unittest.main()
