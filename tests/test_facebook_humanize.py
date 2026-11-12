# -*- coding: utf-8 -*-
"""Facebook 个人主页：发布流的人类化交互层（工单 08，spec §3.7）。

三块离线证据（spec §6.2）：

1. **事件序列** —— 正文清空 → 逐字（ASCII ``press`` / 非 ASCII
   ``insert_text`` / 换行 ``Enter``）→ 恰一次 ``after_type``；发布点
   ``before_submit`` 在 ``mouse.down`` 之前；``stillOn`` hit-test 先于
   ``down``；零原生 ``locator.click``、零 ``force``。
2. **字段值读回** —— fake 编辑器持有键入缓冲，断言最终值与 ``_caption()``
   一致（抓「清空不净导致追加」），并覆盖 >1000 码点整段 ``insert_text``
   与 ``\r`` 归一。
3. **静态门** —— ``tests.humanize_gates.assert_clean`` 在 Facebook 包上跑
   A–E。

另加 ``HUMANIZE=0`` 语义切换用例：一次 ``insert_text``、两次原生
``locator.click``、零停顿。夹具按票据约定局部实现，不改共享 fakes；未
scripted 的选择器仍然抛错。
"""

from __future__ import annotations

import asyncio
import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.fakes_xhs_dom import FakeLocator, RecordingKeyboard, RecordingMouse, RecordingPage
from tests.humanize_gates import assert_clean
from uploader.meta_uploader.facebook_uploader import main as facebook_main
from utils.humanize import Humanizer

PACKAGE = (
    Path(__file__).resolve().parent.parent
    / "uploader"
    / "meta_uploader"
    / "facebook_uploader"
)

#: 徽章账号文件不必存在：只测 ``_publish_on_page``，不走 ``_validate_media``。
ACCOUNT = "account.json"

EDITOR_FACTS = {
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

HIT = {"self": True, "tag": "div", "className": "", "id": "", "text": ""}


class _Expect:
    """``expect(locator).to_have_count(n)`` 的立即判定替身。

    真实 Playwright 的 ``expect`` 需要真 locator；这里保留它的语义（一次
    判定、不符就抛），好让「多义必须硬失败」在离线可测。
    """

    def __init__(self, locator) -> None:
        self.locator = locator

    async def to_have_count(self, count: int) -> None:
        actual = await self.locator.count()
        if actual != count:
            raise AssertionError(
                f"{self.locator!r}: expected {count} matches, got {actual}"
            )

    async def to_be_visible(self) -> None:
        if not await self.locator.is_visible():
            raise AssertionError(f"{self.locator!r}: expected visible")


class _ComposerEditor(FakeLocator):
    """contenteditable 正文：持有键入缓冲，模拟全选删除与逐字输入。"""

    def __init__(
        self,
        name: str = "editor",
        *,
        draft: str = "",
        count: int = 1,
        events: list,
    ) -> None:
        super().__init__(
            name,
            count=count,
            computed_style=dict(EDITOR_FACTS),
            attributes={"contenteditable": "true"},
        )
        self.buffer = draft
        self.selected = False
        self.box = {"x": 40.0, "y": 60.0, "width": 320.0, "height": 120.0}
        self.events = events

    async def bounding_box(self):
        return dict(self.box)

    async def inner_text(self) -> str:
        return self.buffer

    async def click(self, **kwargs) -> None:
        # HUMANIZE=0 的快速路径；HUMANIZE=1 不允许走到这里。
        self.click_count += 1
        self.click_calls.append(dict(kwargs))

    async def evaluate(self, expression, arg=None):
        self.evaluate_calls.append((expression, arg))
        text = str(expression)
        if "elementFromPoint" in text:
            self.events.append(("hit-test", self.name))
            return dict(HIT)
        if "getBoundingClientRect" in text:
            return {
                "width": self.box["width"],
                "height": self.box["height"],
                "inside": True,
                "clipped": False,
                "childFrame": False,
            }
        return dict(EDITOR_FACTS)

    # -- 键盘模型：只实现正文需要的键 --------------------------------
    def _drop_selection(self) -> None:
        if self.selected:
            self.buffer = ""
            self.selected = False

    def apply_key(self, key: str) -> None:
        if key == "ControlOrMeta+A":
            self.selected = True
        elif key == "Delete":
            self._drop_selection()
        elif key == "Enter":
            self._drop_selection()
            self.buffer += "\n"
        elif len(key) == 1:
            self._drop_selection()
            self.buffer += key
        # 其余具名键（Backspace 等）对缓冲无影响。

    def apply_insert(self, text: str) -> None:
        self._drop_selection()
        self.buffer += text


class _ComposerKeyboard(RecordingKeyboard):
    """把按键/插入真正写进正文缓冲，并记录事件顺序。"""

    def __init__(self, events: list, target: _ComposerEditor) -> None:
        super().__init__()
        self.events = events
        self.target = target

    async def press(self, key: str, **kwargs) -> None:
        self.actions.append(("press", key))
        self.events.append(("press", key))
        self.target.apply_key(key)

    async def insert_text(self, text: str, **kwargs) -> None:
        self.actions.append(("insert_text", text))
        self.events.append(("insert_text", text))
        self.target.apply_insert(text)


class _ComposerMouse(RecordingMouse):
    """按下即视为已派发：``up`` 之后页面开始出现成功文案。"""

    def __init__(self, events: list, state: dict) -> None:
        super().__init__()
        self.events = events
        self.state = state

    async def down(self, **kwargs) -> None:
        await super().down(**kwargs)
        self.events.append(("down",))

    async def up(self, **kwargs) -> None:
        await super().up(**kwargs)
        # 只有落在发布按钮上的按下才算提交；正文的坐标点击不会产生成功文案。
        if self.state.get("armed"):
            self.state["published"] = True
        self.events.append(("up",))


class _PublishButton(FakeLocator):
    def __init__(self, name: str = "publish", *, state: dict, events: list) -> None:
        super().__init__(name, computed_style=dict(EDITOR_FACTS))
        self.box = {"x": 200.0, "y": 400.0, "width": 160.0, "height": 40.0}
        self.state = state
        self.events = events

    async def bounding_box(self):
        return dict(self.box)

    async def click(self, **kwargs) -> None:
        # HUMANIZE=0 的快速路径（一次原生点击）。
        await super().click(**kwargs)
        self.state["published"] = True

    async def evaluate(self, expression, arg=None):
        self.evaluate_calls.append((expression, arg))
        text = str(expression)
        if "elementFromPoint" in text:
            self.events.append(("hit-test", self.name))
            self.state["armed"] = True
            return dict(HIT)
        if "getBoundingClientRect" in text:
            return {
                "width": self.box["width"],
                "height": self.box["height"],
                "inside": True,
                "clipped": False,
                "childFrame": False,
            }
        return dict(EDITOR_FACTS)


class _SuccessText(FakeLocator):
    """发布成功文案：只在 ``mouse.up`` / 原生点击之后出现。"""

    def __init__(self, state: dict) -> None:
        super().__init__("success-text")
        self.state = state

    async def count(self) -> int:
        return 1 if self.state["published"] else 0

    async def is_visible(self) -> bool:
        return bool(self.state["published"])


class _FileInput(FakeLocator):
    def __init__(self) -> None:
        super().__init__("media-input", computed_style=dict(EDITOR_FACTS))


class _FacebookPage(RecordingPage):
    def __init__(self, *, selectors: dict, events: list, state: dict, editor) -> None:
        super().__init__(url="https://www.facebook.com/", selectors=selectors)
        self.events = events
        self.state = state
        self.keyboard = _ComposerKeyboard(events, editor)
        self.mouse = _ComposerMouse(events, state)
        self.success = _SuccessText(state)

    def get_by_text(self, text, exact: bool = False):
        if isinstance(text, re.Pattern):
            return self.success
        return super().get_by_text(text, exact=exact)


class _RecordingHumanizer(Humanizer):
    """真实 sequencing，零墙钟停顿：``_pause`` 只记账。"""

    def __init__(self, page, **kwargs) -> None:
        super().__init__(page, **kwargs)
        self.sleep_arg = kwargs.get("sleep")
        self.pauses: list = []

    async def _pause(self, action) -> None:
        if not self.enabled:
            return
        self.pauses.append(action)

    async def before_submit(self) -> None:
        if self.enabled:
            self.page.events.append(("before_submit",))
        await super().before_submit()

    def pause_count(self, action) -> int:
        return sum(1 for candidate in self.pauses if candidate is action)


def _paper(
    *,
    title: str = "标题",
    description: str = "正文",
    tags: list[str] | None = None,
    draft: str = "旧草稿",
    editor_count: int = 1,
):
    """构造一次 ``_publish_on_page`` 所需的 fake 页面与上传器。"""
    events: list = []
    state = {"published": False}
    editor = _ComposerEditor("editor", draft=draft, count=editor_count, events=events)
    publish = _PublishButton(state=state, events=events)
    form = FakeLocator(
        "form",
        children={
            "role:button": FakeLocator(
                "form-buttons",
                items=[FakeLocator("close"), FakeLocator("privacy"), publish],
            )
        },
    )
    page = _FacebookPage(
        selectors={
            facebook_main.FACEBOOK_MEDIA_INPUT: _FileInput(),
            facebook_main.FACEBOOK_COMPOSER_READY: editor,
            facebook_main.FACEBOOK_COMPOSER_EDITOR: editor,
            facebook_main.FACEBOOK_PUBLISH_FORM: form,
            '[role="dialog"] [role="alert"]': FakeLocator("alert", count=0),
        },
        events=events,
        state=state,
        editor=editor,
    )
    app = facebook_main.FacebookPost(
        title=title,
        file_path="video.mp4",
        description=description,
        tags=tags or [],
        account_file=ACCOUNT,
    )
    return page, editor, publish, app


def _run(app, page):
    with (
        patch.object(facebook_main, "Humanizer", _RecordingHumanizer),
        patch.object(facebook_main, "expect", _Expect),
    ):
        asyncio.run(app._publish_on_page(page))


def _typed_keyboard_actions(page, caption_keys=("ControlOrMeta+A", "Delete")):
    """清空键之外的键盘动作（即正文输入）。"""
    actions = list(page.keyboard.actions)
    for key in caption_keys:
        assert actions and actions[0] == ("press", key), actions[:2]
        actions.pop(0)
    return actions


class FacebookComposerEventSequenceTests(unittest.TestCase):
    def test_event_sequence_types_with_keys_and_clicks_once(self):
        page, editor, publish, app = _paper(
            title="标题一", description="hello", tags=["a"]
        )

        _run(app, page)

        caption = "标题一\n\nhello\n\n#a"
        humanizer = app._humanizer_instance
        # 两次坐标点击（正文聚焦 + 发布），每次都先走贝塞尔路径。
        moves = [action for action in page.mouse.actions if action[0] == "move"]
        self.assertGreaterEqual(len(moves), 20)
        self.assertEqual(page.mouse.down_count, 2)
        self.assertEqual(page.mouse.up_count, 2)

        # stillOn hit-test 先于对应 mouse.down；before_submit 在发布那一次之前。
        order = [event[0] for event in page.events]
        downs = [index for index, name in enumerate(order) if name == "down"]
        self.assertEqual(len(downs), 2)
        editor_hit = page.events.index(("hit-test", "editor"))
        publish_hit = page.events.index(("hit-test", "publish"))
        submit = order.index("before_submit")
        self.assertLess(editor_hit, downs[0])
        self.assertLess(downs[0], submit)
        self.assertLess(submit, downs[1])
        self.assertLess(publish_hit, downs[1])

        # 输入原语：ASCII press、非 ASCII insert_text、换行 Enter。
        typed = _typed_keyboard_actions(page)
        self.assertEqual(typed[:3], [("insert_text", "标"), ("insert_text", "题"), ("insert_text", "一")])
        self.assertIn(("press", "Enter"), typed)
        self.assertIn(("press", "h"), typed)
        self.assertIn(("press", "#"), typed)
        self.assertNotIn(("press", "\r"), typed)
        # 恰一次 after_type；清空与逐字各采样 keystroke。
        self.assertEqual(humanizer.pause_count(humanizer.profile.after_type), 1)
        self.assertEqual(humanizer.pause_count(humanizer.profile.before_submit), 1)
        # 人类化点击走坐标：原生 locator.click 零次，force 零次。
        self.assertEqual(editor.click_count, 0)
        self.assertEqual(publish.click_count, 0)
        self.assertFalse(any("force" in call for call in publish.click_calls))

    def test_ambiguous_composer_body_fails_before_typing(self):
        page, editor, publish, app = _paper(editor_count=2)

        with (
            patch.object(facebook_main, "Humanizer", _RecordingHumanizer),
            patch.object(facebook_main, "expect", _Expect),
        ):
            with self.assertRaises(AssertionError):
                asyncio.run(app._publish_on_page(page))

        self.assertEqual(page.keyboard.actions, [])
        self.assertEqual(page.mouse.down_count, 0)


class FacebookComposerReadbackTests(unittest.TestCase):
    def test_field_value_readback_replaces_draft_and_normalises_crlf(self):
        page, editor, publish, app = _paper(
            title="标题", description="第一行\r\n第二行", tags=[]
        )

        _run(app, page)

        expected = "标题\n\n第一行\n第二行"
        self.assertEqual(editor.buffer, expected)
        self.assertNotIn("\r", editor.buffer)
        for action in page.keyboard.actions:
            self.assertNotIn("\r", str(action))

    def test_over_horizon_body_is_one_bulk_insert_with_single_after_type(self):
        long_description = "长" * 1001
        page, editor, publish, app = _paper(
            title="标题", description=long_description, tags=[]
        )

        _run(app, page)

        expected = f"标题\n\n{long_description}"
        self.assertGreater(len(expected), 1000)
        self.assertEqual(editor.buffer, expected)
        inserts = [a for a in page.keyboard.actions if a[0] == "insert_text"]
        self.assertEqual(inserts, [("insert_text", expected)])
        # >1000 走整段 insert_text：除清空的两键外零按键。
        self.assertEqual(
            [a for a in page.keyboard.actions if a[0] == "press"],
            [("press", "ControlOrMeta+A"), ("press", "Delete")],
        )
        humanizer = app._humanizer_instance
        self.assertEqual(humanizer.pause_count(humanizer.profile.after_type), 1)


class FacebookHumanizeDisabledTests(unittest.TestCase):
    def test_humanize_zero_switches_to_single_insert_and_native_clicks(self):
        with patch.dict(os.environ, {"HUMANIZE": "0"}):
            page, editor, publish, app = _paper(
                title="标题", description="正文", tags=["a"]
            )
            _run(app, page)

        caption = "标题\n\n正文\n\n#a"
        self.assertEqual(editor.buffer, caption)
        # 语义切换：文本一次 insert_text，点击一次 locator.click，零停顿。
        self.assertEqual(
            [a for a in page.keyboard.actions if a[0] == "insert_text"],
            [("insert_text", caption)],
        )
        self.assertEqual(
            [a for a in page.keyboard.actions if a[0] == "press"],
            [("press", "ControlOrMeta+A"), ("press", "Delete")],
        )
        self.assertEqual(editor.click_count, 1)
        self.assertEqual(publish.click_count, 1)
        self.assertEqual(page.mouse.down_count, 0)
        self.assertEqual(app._humanizer_instance.pauses, [])
        self.assertTrue(page.state["published"])


class FacebookStaticGateTests(unittest.TestCase):
    def test_facebook_package_passes_gates_a_to_e(self):
        assert_clean(PACKAGE)


if __name__ == "__main__":
    unittest.main()
