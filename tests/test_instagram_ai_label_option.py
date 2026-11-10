"""AI 生成标识（``--ai-generated`` / ``--no-ai-generated``）的 A/B 层回归。

A 层零浏览器：两个上传命令都注册互斥组，同传由 argparse 退出 2，三态
``True / False / None`` 不被压缩。B 层注入 fake 开关驱动 ``_apply_options``，
覆盖 spec §7.2 B1–B7 与“AI 与关闭评论互不影响”。C 层真实 DOM 哨兵在
``tests/test_instagram_uploader.py``。
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sau_cli
from sau_commands import instagram as instagram_command
from uploader.meta_uploader.insgraph_uploader.controls.ai_label import AiLabelControl
from uploader.meta_uploader.insgraph_uploader.main import InstagramUploader
from uploader.meta_uploader.insgraph_uploader.options import (
    ACCOUNT_INELIGIBLE,
    DEFAULT_OFF,
    ENTRY_MISSING,
    MISMATCH,
    NOT_REQUESTED,
    SET,
    UNSUPPORTED,
    InstagramPublishOptions,
)


def _subparser(parser: argparse.ArgumentParser, platform: str, action: str):
    for item in parser._actions:
        if isinstance(item, argparse._SubParsersAction) and platform in item.choices:
            for nested in item.choices[platform]._actions:
                if isinstance(nested, argparse._SubParsersAction):
                    return nested.choices[action]
    raise AssertionError(f"parser not found: {platform}/{action}")


def _option_strings(parser: argparse.ArgumentParser) -> set[str]:
    return set(parser._option_string_actions)


class InstagramAiLabelParserTests(unittest.TestCase):
    """A 层：两个上传命令都注册互斥组，未传保持 None。"""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.image = self.folder / "image.png"
        self.image.touch()
        self.video = self.folder / "video.mp4"
        self.video.touch()

    def _note_argv(self, *extra):
        return [
            "upload-note", "--account", "creator", "--title", "caption",
            "--images", str(self.image), *extra,
        ]

    def _video_argv(self, *extra):
        return [
            "upload-video", "--account", "creator", "--title", "caption",
            "--file", str(self.video), *extra,
        ]

    def _parse(self, argv):
        return sau_cli.build_parser().parse_args(["instagram", *argv])

    def test_both_upload_commands_register_both_flags(self):
        for action in ("upload-video", "upload-note"):
            with self.subTest(action=action):
                options = _option_strings(
                    _subparser(sau_cli.build_parser(), "instagram", action)
                )
                self.assertIn("--ai-generated", options)
                self.assertIn("--no-ai-generated", options)
                # 明确不引入 TikTok 的 --aigc 别名。
                self.assertNotIn("--aigc", options)

    def test_absent_flags_build_no_options(self):
        for argv in (self._note_argv(), self._video_argv()):
            with self.subTest(command=argv[0]):
                args = self._parse(argv)
                self.assertIsNone(args.ai_generated)
                self.assertIsNone(instagram_command._build_publish_options(args))

    def test_ai_generated_flag_maps_to_true(self):
        for argv in (self._note_argv("--ai-generated"), self._video_argv("--ai-generated")):
            with self.subTest(command=argv[0]):
                args = self._parse(argv)
                options = instagram_command._build_publish_options(args)
                self.assertIs(options.ai_generated, True)

    def test_no_ai_generated_flag_maps_to_false(self):
        for argv in (
            self._note_argv("--no-ai-generated"),
            self._video_argv("--no-ai-generated"),
        ):
            with self.subTest(command=argv[0]):
                args = self._parse(argv)
                options = instagram_command._build_publish_options(args)
                # 显式关闭必须保留 False，不能被压缩回 None。
                self.assertIs(options.ai_generated, False)

    def test_both_flags_together_exit_two_and_build_no_uploader(self):
        for argv in (
            self._note_argv("--ai-generated", "--no-ai-generated"),
            self._video_argv("--ai-generated", "--no-ai-generated"),
        ):
            with self.subTest(command=argv[0]):
                with patch.object(instagram_command, "InstagramUploader") as uploader, \
                        patch.object(instagram_command, "upload_instagram_content") as upload, \
                        contextlib.redirect_stderr(io.StringIO()), \
                        self.assertRaises(SystemExit) as ctx:
                    sau_cli.main(["instagram", *argv])
                self.assertEqual(ctx.exception.code, 2)
                uploader.assert_not_called()
                upload.assert_not_called()


class _FakeAiControl:
    """``ai_generated`` 布尔语义的 fake：按顺序回读，记录全部交互。"""

    def __init__(self, values=(), *, presence="present", name="ai_generated"):
        self.values = list(values)
        self.presence = presence
        self.name = name
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


class _ExplodingAiControl:
    """任何交互都失败：验证未请求时零控件交互。"""

    async def resolve(self):
        raise AssertionError("未请求的选项不得读取页面")

    async def read(self):
        raise AssertionError("未请求的选项不得读取页面")

    async def set(self, requested):
        raise AssertionError("未请求的选项不得点击页面")


class InstagramAiLabelPipelineTests(unittest.TestCase):
    """B 层：fake 开关经 ``_apply_options`` 注入，覆盖 spec §7.2 B1–B7。"""

    def _app(self, options, *, folder):
        return InstagramUploader(
            "unused.json", title="caption", video_file="video.mp4",
            options=options, result_file=Path(folder) / "result.json",
        )

    def _apply(self, app, controls):
        # 不抛异常即等价退出码 0（退出码映射由既有 CLI 用例覆盖）。
        return asyncio.run(
            app._apply_options(
                page=None, budget=app.start_publish_budget(), controls=controls
            )
        )

    def test_on_and_missing_entry_is_unsupported_and_raises(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(ai_generated=True), folder=folder)
            control = _FakeAiControl(presence="missing")
            with self.assertRaises(RuntimeError) as ctx:
                self._apply(app, {"ai_generated": control})
            self.assertIn("ai_generated=unsupported(entry_missing)", str(ctx.exception))
            self.assertEqual(control.calls, ["resolve"])
            self.assertEqual(
                app.result["options"]["ai_generated"],
                {
                    "requested": True,
                    "applied": None,
                    "status": UNSUPPORTED,
                    "reason": ENTRY_MISSING,
                },
            )

    def test_on_and_ineligible_account_is_unsupported(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(ai_generated=True), folder=folder)
            control = _FakeAiControl(presence="ineligible")
            with self.assertRaises(RuntimeError) as ctx:
                self._apply(app, {"ai_generated": control})
            self.assertIn(
                "ai_generated=unsupported(account_ineligible)", str(ctx.exception)
            )
            self.assertEqual(control.calls, ["resolve"])
            self.assertEqual(
                app.result["options"]["ai_generated"],
                {
                    "requested": True,
                    "applied": None,
                    "status": UNSUPPORTED,
                    "reason": ACCOUNT_INELIGIBLE,
                },
            )

    def test_on_and_already_on_records_set_without_clicking(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(ai_generated=True), folder=folder)
            control = _FakeAiControl([True])
            self._apply(app, {"ai_generated": control})
            self.assertEqual(control.calls, ["resolve", "read"])
            self.assertEqual(
                app.result["options"]["ai_generated"],
                {"requested": True, "applied": True, "status": SET},
            )

    def test_on_and_currently_off_clicks_once_then_records_set(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(ai_generated=True), folder=folder)
            control = _FakeAiControl([False, True])
            self._apply(app, {"ai_generated": control})
            self.assertEqual(
                control.calls, ["resolve", "read", ("set", True), "read"]
            )
            self.assertEqual(
                app.result["options"]["ai_generated"],
                {"requested": True, "applied": True, "status": SET},
            )

    def test_off_and_missing_entry_is_default_off(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(ai_generated=False), folder=folder)
            control = _FakeAiControl(presence="missing")
            self._apply(app, {"ai_generated": control})
            self.assertEqual(control.calls, ["resolve"])
            self.assertEqual(
                app.result["options"]["ai_generated"],
                {
                    "requested": False,
                    "applied": None,
                    "status": DEFAULT_OFF,
                    "reason": ENTRY_MISSING,
                },
            )

    def test_off_and_already_off_records_default_off_without_clicking(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(ai_generated=False), folder=folder)
            control = _FakeAiControl([False])
            self._apply(app, {"ai_generated": control})
            self.assertEqual(control.calls, ["resolve", "read"])
            self.assertEqual(
                app.result["options"]["ai_generated"],
                {"requested": False, "applied": False, "status": DEFAULT_OFF},
            )

    def test_off_and_currently_on_clicks_once_then_records_set(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(ai_generated=False), folder=folder)
            control = _FakeAiControl([True, False])
            self._apply(app, {"ai_generated": control})
            self.assertEqual(
                control.calls, ["resolve", "read", ("set", False), "read"]
            )
            self.assertEqual(
                app.result["options"]["ai_generated"],
                {"requested": False, "applied": False, "status": SET},
            )

    def test_readback_still_true_after_click_records_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(ai_generated=False), folder=folder)
            control = _FakeAiControl([True, True])
            with self.assertRaises(RuntimeError) as ctx:
                self._apply(app, {"ai_generated": control})
            self.assertIn("ai_generated=mismatch", str(ctx.exception))
            self.assertEqual(
                control.calls, ["resolve", "read", ("set", False), "read"]
            )
            self.assertEqual(
                app.result["options"]["ai_generated"],
                {"requested": False, "applied": True, "status": MISMATCH},
            )

    def test_not_requested_touches_no_control(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(None, folder=folder)
            self._apply(app, {"ai_generated": _ExplodingAiControl()})
            self.assertEqual(
                app.result["options"]["ai_generated"],
                {"requested": None, "applied": None, "status": NOT_REQUESTED},
            )

    def test_ai_and_comments_are_independent_switches(self):
        """两个开关互不互斥：同时请求时各自独立应用，顺序仍为 AI 先于评论。"""
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(
                InstagramPublishOptions(ai_generated=True, comments=False),
                folder=folder,
            )
            order: list[str] = []

            class _OrderedAi(_FakeAiControl):
                async def resolve(self):
                    order.append("ai_generated")
                    return await super().resolve()

            class _OrderedComments(_FakeAiControl):
                async def resolve(self):
                    order.append("comments")
                    return await super().resolve()

            ai = _OrderedAi([False, True])
            comments = _OrderedComments([True, False], name="comments")
            self._apply(app, {"ai_generated": ai, "comments": comments})
            self.assertEqual(order, ["ai_generated", "comments"])
            self.assertEqual(ai.calls, ["resolve", "read", ("set", True), "read"])
            self.assertEqual(
                comments.calls, ["resolve", "read", ("set", False), "read"]
            )
            self.assertEqual(
                app.result["options"]["ai_generated"],
                {"requested": True, "applied": True, "status": SET},
            )
            self.assertEqual(
                app.result["options"]["comments"],
                {"requested": False, "applied": False, "status": SET},
            )


class _FakeSwitch:
    """最小开关替身：行内文案、可见性与 ``aria-checked`` 均可观察。"""

    def __init__(self, *, checked=False, row="Add AI label"):
        self.checked = checked
        self.row = row
        self.clicks = 0

    @property
    def first(self):
        return self

    def nth(self, index):
        return self

    def locator(self, selector):
        return self

    async def count(self):
        return 1

    async def evaluate(self, script):
        return self.row

    async def is_visible(self):
        return True

    async def is_disabled(self):
        return False

    async def get_attribute(self, name):
        return ("true" if self.checked else "false") if name == "aria-checked" else None

    async def is_checked(self):
        return self.checked

    async def click(self):
        self.clicks += 1
        self.checked = not self.checked


class _FakeDialog:
    def __init__(self, switch):
        self.switch = switch

    def locator(self, selector):
        return self.switch

    def get_by_text(self, label, exact=False):
        return self.switch


class _FakePage:
    def __init__(self, switch):
        self.dialog = _FakeDialog(switch)

    def get_by_role(self, role):
        return self.dialog


class AiLabelControlTests(unittest.TestCase):
    """封装层：文案清单固定，且不反转语义（checked = AI 标识已开启）。"""

    def test_control_reads_checked_as_ai_generated(self):
        switch = _FakeSwitch(checked=False)
        control = AiLabelControl(_FakePage(switch))
        self.assertEqual(asyncio.run(control.resolve()), "present")
        self.assertIs(asyncio.run(control.read()), False)
        asyncio.run(control.set(True))
        self.assertEqual(switch.clicks, 1)
        self.assertIs(asyncio.run(control.read()), True)

    def test_control_does_not_match_unrelated_rows(self):
        switch = _FakeSwitch(checked=True, row="Turn off commenting")
        control = AiLabelControl(_FakePage(switch))
        self.assertEqual(asyncio.run(control.resolve()), "missing")


if __name__ == "__main__":
    unittest.main()
