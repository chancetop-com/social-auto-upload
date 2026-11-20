"""关闭评论选项的 A/B 层回归（parser 接线、fake 控制件、展开幂等）。

C 层真实 DOM 哨兵在 ``tests/test_instagram_uploader.py``；本文件不启动浏览器。
"""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

import sau_cli
from sau_commands import instagram as instagram_command
from uploader.meta_uploader.insgraph_uploader.controls.toggles import SwitchControl
from uploader.meta_uploader.insgraph_uploader.main import InstagramUploader
from uploader.meta_uploader.insgraph_uploader.options import (
    ACCOUNT_INELIGIBLE,
    DEFAULT_OFF,
    ENTRY_MISSING,
    MISMATCH,
    NOT_REQUESTED,
    SET,
    InstagramPublishOptions,
)
from utils.errors import PublishResultUnknownError


class InstagramCommentsParserTests(unittest.TestCase):
    """A 层：两个上传命令都注册 ``--no-comments``，并保持 None/False 三态。"""

    def test_present_flag_maps_to_comments_false(self):
        parser = sau_cli.build_parser()
        commands = (("upload-note", "--images", ".png"), ("upload-video", "--file", ".mp4"))
        for action, flag, suffix in commands:
            with self.subTest(action=action), tempfile.NamedTemporaryFile(suffix=suffix) as media:
                args = parser.parse_args([
                    "instagram", action, flag, media.name, "--title", "caption", "--no-comments",
                ])
                options = instagram_command._build_publish_options(args)
                self.assertEqual(options, InstagramPublishOptions(comments=False))
                self.assertIs(options.comments, False)


class _FakeCommentsControl:
    """``comments_enabled`` 语义的 fake：按顺序回读，记录全部交互。"""

    def __init__(self, values=(), *, presence="present"):
        self.values = list(values)
        self.presence = presence
        self.calls: list[object] = []

    async def resolve(self):
        self.calls.append("resolve")
        return self.presence

    async def read(self):
        self.calls.append("read")
        if not self.values:
            return None
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]

    async def set(self, requested):
        self.calls.append(("set", requested))


class InstagramCommentsPipelineTests(unittest.TestCase):
    """B 层：fake 控制件经 ``_apply_options`` 注入，覆盖 §7.2 B1–B7。"""

    def _app(self, options, *, folder):
        image = Path(folder) / "image.png"
        return InstagramUploader(
            "unused.json", title="caption", image_files=[image],
            options=options, result_file=Path(folder) / "result.json",
        )

    def _apply(self, app, controls):
        # 不抛异常即等价退出码 0（退出码映射由既有 CLI 用例覆盖）。
        return asyncio.run(
            app._apply_options(
                page=None, budget=app.start_publish_budget(), controls=controls
            )
        )

    def test_set_then_matching_readback_records_set(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(comments=False), folder=folder)
            control = _FakeCommentsControl([True, False])
            self._apply(app, {"comments": control})
            self.assertEqual(
                control.calls, ["resolve", "read", ("set", False), "read"]
            )
            self.assertEqual(
                app.result["options"]["comments"],
                {"requested": False, "applied": False, "status": SET},
            )

    def test_mismatched_readback_records_mismatch_and_raises(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(comments=False), folder=folder)
            control = _FakeCommentsControl([True, True])
            with self.assertRaises(RuntimeError) as ctx:
                self._apply(app, {"comments": control})
            # 选项失败发生在点击 Share 前，必须是一般失败而非“结果未知”。
            self.assertNotIsInstance(ctx.exception, PublishResultUnknownError)
            self.assertIn("comments=mismatch", str(ctx.exception))
            self.assertEqual(
                app.result["options"]["comments"],
                {"requested": False, "applied": True, "status": MISMATCH},
            )

    def test_missing_entry_with_off_request_is_default_off(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(comments=False), folder=folder)
            control = _FakeCommentsControl(presence="missing")
            self._apply(app, {"comments": control})
            self.assertEqual(
                app.result["options"]["comments"],
                {
                    "requested": False,
                    "applied": None,
                    "status": DEFAULT_OFF,
                    "reason": ENTRY_MISSING,
                },
            )
            self.assertEqual(control.calls, ["resolve"])
            self.assertEqual(app.result["options"]["ai_generated"]["status"], NOT_REQUESTED)

    def test_ineligible_off_request_stays_default_off_without_reading(self):
        """评论关闭请求不读禁用开关：沿用入口缺失的 default_off 语义。"""
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(comments=False), folder=folder)
            control = _FakeCommentsControl(presence="ineligible", values=[False])
            self._apply(app, {"comments": control})
            self.assertEqual(control.calls, ["resolve"])
            record = app.result["options"]["comments"]
            self.assertEqual(record["status"], DEFAULT_OFF)
            self.assertEqual(record["reason"], ACCOUNT_INELIGIBLE)
            self.assertIsNone(record["applied"])

    def test_ineligible_but_still_on_stays_default_off(self):
        """禁用且仍为开的评论开关不按 AI 声明的严格规则失败。"""
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(comments=False), folder=folder)
            control = _FakeCommentsControl(presence="ineligible", values=[True])
            self._apply(app, {"comments": control})
            self.assertEqual(control.calls, ["resolve"])
            self.assertEqual(
                app.result["options"]["comments"],
                {
                    "requested": False,
                    "applied": None,
                    "status": DEFAULT_OFF,
                    "reason": ACCOUNT_INELIGIBLE,
                },
            )
            self.assertEqual(app.result["options"]["ai_generated"]["status"], NOT_REQUESTED)

    def test_visible_but_unreadable_stays_default_off_without_clicking(self):
        """评论关闭请求读不到状态时沿用旧行为，不盲点开关。"""
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(comments=False), folder=folder)
            control = _FakeCommentsControl([], presence="present")
            self._apply(app, {"comments": control})
            self.assertEqual(control.calls, ["resolve", "read"])
            self.assertEqual(
                app.result["options"]["comments"],
                {"requested": False, "applied": None, "status": DEFAULT_OFF},
            )


class _FakeSwitch:
    """最小开关替身：``aria-checked``、禁用状态与点击次数均可观察。"""

    def __init__(self, *, checked=False, disabled=False):
        self.checked = checked
        self.disabled = disabled
        self.clicks = 0

    async def is_disabled(self):
        return self.disabled

    async def get_attribute(self, name):
        return ("true" if self.checked else "false") if name == "aria-checked" else None

    async def is_checked(self):
        return self.checked

    async def is_visible(self):
        """真实开关在面板收起时不可见；替身默认可见，缺席由 ``_locate`` 表达。"""
        return True

    async def scroll_into_view_if_needed(self):
        return None

    async def focus(self):
        return None

    async def click(self, timeout=None):
        self.clicks += 1
        self.checked = not self.checked


class _FakeKeyboard:
    async def press(self, key):
        return None


class _FakePage:
    def __init__(self):
        self.keyboard = _FakeKeyboard()


class _FakeHumanizer:
    """行为层替身：语义测试只关心“点了一次开关”，点击机制另由平台人类化用例覆盖。"""

    enabled = True

    async def click(self, locator):
        await locator.click()


class _StubCommentsControl(SwitchControl):
    """替换页面定位：``hidden=True`` 模拟高级设置未展开时的开关缺席。"""

    def __init__(self, switch, *, hidden=False):
        super().__init__(
            _FakePage(),
            labels=("Turn off commenting",),
            panel_labels=("Advanced settings",),
            invert=True,
            humanizer=_FakeHumanizer(),
        )
        self.switch = switch
        self.hidden = hidden
        self.expands = 0

    async def _locate(self):
        return None if self.hidden else self.switch

    async def _expand_panel(self):
        self.expands += 1
        self.hidden = False


class InstagramCommentsSwitchControlTests(unittest.TestCase):
    """B10：折叠面板按实例只展开一次，开关读取按 invert 反转。"""

    def test_panel_expands_at_most_once_per_instance(self):
        control = _StubCommentsControl(_FakeSwitch(checked=False), hidden=True)
        self.assertEqual(asyncio.run(control.resolve()), "present")
        self.assertEqual(asyncio.run(control.resolve()), "present")
        self.assertIs(asyncio.run(control.read()), True)
        self.assertEqual(control.expands, 1)
        self.assertEqual(control.switch.clicks, 0)

    def test_visible_switch_skips_panel(self):
        control = _StubCommentsControl(_FakeSwitch(checked=False), hidden=False)
        self.assertEqual(asyncio.run(control.resolve()), "present")
        self.assertEqual(control.expands, 0)

    def test_missing_switch_after_expand_is_missing(self):
        control = _StubCommentsControl(_FakeSwitch(), hidden=True)

        async def expand_only():
            control.expands += 1

        control._expand_panel = expand_only
        self.assertEqual(asyncio.run(control.resolve()), "missing")
        self.assertEqual(control.expands, 1)

    def test_read_inverts_checked_into_comments_enabled(self):
        control = _StubCommentsControl(_FakeSwitch(checked=False))
        self.assertIs(asyncio.run(control.read()), True)
        control = _StubCommentsControl(_FakeSwitch(checked=True))
        self.assertIs(asyncio.run(control.read()), False)

    def test_set_clicks_once_and_waits_for_readback(self):
        switch = _FakeSwitch(checked=False)
        control = _StubCommentsControl(switch)
        asyncio.run(control.set(False))
        self.assertEqual(switch.clicks, 1)
        self.assertIs(asyncio.run(control.read()), False)

    def test_set_is_a_no_op_when_already_satisfied(self):
        switch = _FakeSwitch(checked=True)
        asyncio.run(_StubCommentsControl(switch).set(False))
        self.assertEqual(switch.clicks, 0)

    def test_disabled_switch_resolves_ineligible(self):
        control = _StubCommentsControl(_FakeSwitch(disabled=True))
        self.assertEqual(asyncio.run(control.resolve()), "ineligible")


if __name__ == "__main__":
    unittest.main()
