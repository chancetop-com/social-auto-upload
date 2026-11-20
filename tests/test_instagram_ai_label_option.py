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
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from patchright.async_api import async_playwright

import sau_cli
from sau_commands import instagram as instagram_command
from uploader.meta_uploader.insgraph_uploader.controls.ai_label import (
    AI_LABEL_TEXTS,
    ai_label_control,
)
from uploader.meta_uploader.insgraph_uploader.controls.toggles import SwitchControl
from uploader.meta_uploader.insgraph_uploader.main import InstagramUploader
from uploader.meta_uploader.insgraph_uploader.options import (
    ACCOUNT_INELIGIBLE,
    DEFAULT_OFF,
    EDITOR_OBSCURED,
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
            # 入口缺失时无从回读，只允许一次 resolve。
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
            # 请求开启时 applied 必须是 null，也不应触发控件读取。
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

    def test_off_and_ineligible_but_already_off_is_default_off(self):
        """可见但禁用的开关已经关闭：读回确认后可继续。"""
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(ai_generated=False), folder=folder)
            control = _FakeAiControl([False], presence="ineligible")
            self._apply(app, {"ai_generated": control})
            self.assertEqual(control.calls, ["resolve", "read"])
            self.assertEqual(
                app.result["options"]["ai_generated"],
                {
                    "requested": False,
                    "applied": False,
                    "status": DEFAULT_OFF,
                    "reason": ACCOUNT_INELIGIBLE,
                },
            )

    def test_off_and_ineligible_still_on_is_mismatch_and_blocks(self):
        """可见但禁用且仍为开：不能记 default_off，必须停在 Share 前。"""
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(ai_generated=False), folder=folder)
            control = _FakeAiControl([True], presence="ineligible")
            with self.assertRaises(RuntimeError) as ctx:
                self._apply(app, {"ai_generated": control})
            self.assertIn("ai_generated=mismatch", str(ctx.exception))
            # 不能点击禁用的开关；只允许 resolve + read。
            self.assertEqual(control.calls, ["resolve", "read"])
            self.assertEqual(
                app.result["options"]["ai_generated"],
                {
                    "requested": False,
                    "applied": True,
                    "status": MISMATCH,
                    "reason": ACCOUNT_INELIGIBLE,
                },
            )

    def test_off_and_ineligible_read_error_is_mismatch_and_blocks(self):
        """可见但禁用且无法回读：同样按 mismatch 停止，不能猜测为已关。"""
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(ai_generated=False), folder=folder)

            class _Unreadable(_FakeAiControl):
                async def read(self):
                    self.calls.append("read")
                    raise RuntimeError("switch read failed")

            control = _Unreadable(presence="ineligible")
            with self.assertRaises(RuntimeError) as ctx:
                self._apply(app, {"ai_generated": control})
            self.assertIn("ai_generated=mismatch", str(ctx.exception))
            self.assertEqual(control.calls, ["resolve", "read"])
            self.assertEqual(
                app.result["options"]["ai_generated"],
                {
                    "requested": False,
                    "applied": None,
                    "status": MISMATCH,
                    "reason": ACCOUNT_INELIGIBLE,
                },
            )

    def test_off_and_visible_but_unreadable_does_not_click_and_blocks(self):
        """可见开关读不出值时不盲点：直接 mismatch，Share 不会发生。"""
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(ai_generated=False), folder=folder)
            control = _FakeAiControl([], presence="present")
            with self.assertRaises(RuntimeError) as ctx:
                self._apply(app, {"ai_generated": control})
            self.assertIn("ai_generated=mismatch", str(ctx.exception))
            self.assertEqual(control.calls, ["resolve", "read"])
            self.assertEqual(
                app.result["options"]["ai_generated"],
                {"requested": False, "applied": None, "status": MISMATCH},
            )

    def test_omitted_ai_generated_never_touches_the_control(self):
        """省略 AI 声明：保留页面当前值，零 resolve / read / click。"""
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(None, folder=folder)
            control = _FakeAiControl([True])
            self._apply(app, {"ai_generated": control})
            self.assertEqual(control.calls, [])
            self.assertEqual(
                app.result["options"]["ai_generated"],
                {"requested": None, "applied": None, "status": NOT_REQUESTED},
            )

    def test_default_result_file_preserves_status_and_ai_option(self):
        """默认结果文件仍保存顶层状态与既有 options 形状。"""
        app = InstagramUploader(
            "unused.json", title="caption", video_file="video.mp4",
            options=InstagramPublishOptions(ai_generated=False),
        )
        self.addCleanup(lambda: app.result_file.unlink(missing_ok=True))
        self.assertEqual(app.result_file.parent, Path(".local/instagram-results"))
        control = _FakeAiControl([False])
        self._apply(app, {"ai_generated": control})
        saved = json.loads(app.result_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "not_submitted")
        self.assertEqual(saved["platform"], "instagram")
        self.assertEqual(
            saved["options"]["ai_generated"],
            {"requested": False, "applied": False, "status": DEFAULT_OFF},
        )
        self.assertEqual(
            saved["options"]["location"],
            {"requested": None, "applied": None, "status": NOT_REQUESTED},
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


class _StubAiLabelControl(SwitchControl):
    """替换页面定位：直接返回一个内存开关，验证语义与幂等。"""

    def __init__(self, switch):
        super().__init__(
            _FakePage(), labels=("Add AI label",), humanizer=_FakeHumanizer()
        )
        self.switch = switch

    async def _locate(self):
        return self.switch


class AiLabelControlTests(unittest.TestCase):
    """封装层：文案清单固定，且不反转语义（checked = AI 标识已开启）。"""

    def test_control_reads_checked_as_ai_generated(self):
        switch = _FakeSwitch(checked=False)
        control = _StubAiLabelControl(switch)
        self.assertEqual(asyncio.run(control.resolve()), "present")
        self.assertIs(asyncio.run(control.read()), False)
        asyncio.run(control.set(True))
        self.assertEqual(switch.clicks, 1)
        self.assertIs(asyncio.run(control.read()), True)

    def test_control_does_not_fold_ai_label_into_comments(self):
        """AI 文案不声明折叠入口：开关缺席就是 missing，不会去点高级设置。"""
        control = _StubAiLabelControl(None)
        self.assertEqual(asyncio.run(control.resolve()), "missing")
        self.assertFalse(control._panel_labels)

    def test_factory_keeps_labels_and_never_inverts(self):
        control = ai_label_control(_FakePage())
        self.assertEqual(control._labels, tuple(AI_LABEL_TEXTS))
        self.assertFalse(control._invert)
        self.assertFalse(control._panel_labels)


_AI_SWITCH_HTML = {
    "already_off": (
        '<input id="ai-switch" role="switch" type="checkbox" aria-checked="false">'
    ),
    "currently_on": (
        '<input id="ai-switch" role="switch" type="checkbox" '
        'aria-checked="true" checked>'
    ),
    "missing": "",
    # 遮挡场景：开关本身已关，但创建页被前台确认框盖住，不能核对。
    "obscured": (
        '<input id="ai-switch" role="switch" type="checkbox" aria-checked="false">'
    ),
    "disabled_on": (
        '<input id="ai-switch" role="switch" type="checkbox" '
        'aria-checked="true" checked disabled>'
    ),
}


def _composer_html(switch_html: str, *, obscured: bool = False) -> str:
    """受控配文页：唯一创建弹窗 + Lexical 编辑器 + Share 点击计数器。"""
    row = "" if not switch_html else f"""
  <div class="row" id="ai-row">
    <div><div><span dir="auto">Add AI label</span></div></div>
    <div><div><div><div>{switch_html}</div></div></div></div>
  </div>"""
    composer = f"""
<div role="dialog" id="compose">
  <div role="heading" aria-level="1">Create new post</div>
  <div data-share-clicks="0"></div>{row}
  <div role="textbox" contenteditable="true" data-lexical-editor="true"></div>
  <div role="button" id="share"
       onclick="const holder=document.querySelector('[data-share-clicks]');
                holder.dataset.shareClicks=String(Number(holder.dataset.shareClicks||0)+1);">Share</div>
</div>
<script>
  const aiSwitch = document.getElementById('ai-switch');
  if (aiSwitch && aiSwitch.tagName === 'INPUT') {{
    aiSwitch.addEventListener('click', () => {{
      aiSwitch.dataset.clicks = String(Number(aiSwitch.dataset.clicks || 0) + 1);
      aiSwitch.setAttribute('aria-checked', String(aiSwitch.checked));
    }});
  }}
</script>"""
    if not obscured:
        return composer
    # 前台「放弃帖子？」确认框 + aria-hidden 的创建页：开关仍在 DOM，但不可核对。
    return f'<div aria-hidden="true">{composer}</div>' + """
<div role="dialog" id="discard">
  <div>放弃帖子？</div>
  <div>如果退出，你所做的编辑不会保存。</div>
  <div role="button">放弃</div>
  <div role="button">取消</div>
</div>"""


class InstagramAiControlledCliTests(unittest.TestCase):
    """真实 Chrome 受控页 + CLI：只传 ``--no-ai-generated``，不传地点。"""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.video = self.folder / "video.mp4"
        self.video.touch()
        self.image = self.folder / "image.png"
        self.image.touch()

    def _run(self, *, action: str, html: str, ai_args=("--no-ai-generated",)):
        """经 ``sau`` CLI 跑完整发布前流程，返回可观察结果。"""
        holder: dict[str, object] = {}
        result_file = self.folder / f"result-{uuid4().hex}.json"

        async def fake_upload(request, *, target=None):
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel="chrome", headless=True)
                page = await browser.new_page()
                try:
                    await page.set_content(html)
                    app = InstagramUploader(
                        "unused.json",
                        title=request.title,
                        description=request.description,
                        tags=request.tags,
                        video_file=request.video_file,
                        image_files=[
                            str(path) for path in (request.image_files or [])
                        ],
                        options=request.options,
                        no_publish=request.no_publish,
                        result_file=request.result_file,
                    )
                    budget = app.start_publish_budget()
                    try:
                        await app._publish(
                            page,
                            {"user_id": "42", "username": "creator"},
                            budget=budget,
                        )
                    except Exception as error:
                        holder["error"] = error
                        raise
                    finally:
                        holder["result"] = app.result
                        holder["share_clicks"] = int(
                            await page.locator("[data-share-clicks]")
                            .get_attribute("data-share-clicks") or 0
                        )
                        switch = page.locator("#ai-switch")
                        count = await switch.count()
                        holder["ai_clicks"] = (
                            int(await switch.get_attribute("data-clicks") or 0)
                            if count else 0
                        )
                        holder["ai_checked"] = (
                            await switch.get_attribute("aria-checked")
                            if count else None
                        )
                finally:
                    await browser.close()
            return holder["result"]

        media = (
            ["--file", str(self.video)]
            if action == "upload-video"
            else ["--images", str(self.image)]
        )
        argv = [
            "instagram", action, "--account", "creator", "--title", "caption",
            *media, "--no-publish", "--result", str(result_file), *ai_args,
        ]
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(
            instagram_command, "upload_instagram_content", fake_upload
        ), patch.dict(
            os.environ,
            {
                "HUMANIZE": "0",
                "ADSPOWER_API_KEY": "",
                "MLX_API_TOKEN": "",
            },
        ), contextlib.redirect_stdout(
            stdout
        ), contextlib.redirect_stderr(stderr):
            code = sau_cli.main(argv)
        saved = json.loads(result_file.read_text(encoding="utf-8"))
        return code, saved, holder, stdout.getvalue(), stderr.getvalue()

    def test_explicit_off_states_for_video_and_note(self):
        cases = (
            # case, expected exit, expected AI record, expected switch checked
            (
                "already_off", 0,
                {"requested": False, "applied": False, "status": DEFAULT_OFF},
                "false", 0,
            ),
            (
                "currently_on", 0,
                {"requested": False, "applied": False, "status": SET},
                "false", 1,
            ),
            (
                "missing", 0,
                {
                    "requested": False,
                    "applied": None,
                    "status": DEFAULT_OFF,
                    "reason": ENTRY_MISSING,
                },
                None, 0,
            ),
            (
                "obscured", 1,
                {
                    "requested": False,
                    "applied": None,
                    "status": MISMATCH,
                    "reason": EDITOR_OBSCURED,
                },
                "false", 0,
            ),
            (
                "disabled_on", 1,
                {
                    "requested": False,
                    "applied": True,
                    "status": MISMATCH,
                    "reason": ACCOUNT_INELIGIBLE,
                },
                "true", 0,
            ),
        )
        for action in ("upload-video", "upload-note"):
            for case, expected_code, expected_ai, checked, clicks in cases:
                with self.subTest(action=action, case=case):
                    html = _composer_html(
                        _AI_SWITCH_HTML[case], obscured=case == "obscured"
                    )
                    code, saved, holder, stdout, stderr = self._run(
                        action=action, html=html
                    )
                    self.assertEqual(code, expected_code, stderr)
                    self.assertEqual(holder["share_clicks"], 0, "Share 必须零点击")
                    self.assertEqual(
                        saved["status"],
                        "prepared" if expected_code == 0 else "not_submitted",
                    )
                    if expected_code == 0:
                        # 成功时 CLI 仍把同一份结果 JSON 打到 stdout。
                        printed = json.loads(stdout)
                        self.assertEqual(printed["status"], "prepared")
                        self.assertEqual(
                            {
                                key: value
                                for key, value in printed["options"][
                                    "ai_generated"
                                ].items()
                                if key != "detail"
                            },
                            expected_ai,
                        )
                    else:
                        self.assertEqual(stdout, "")
                    record = saved["options"]["ai_generated"]
                    if case == "obscured":
                        detail = record.pop("detail", "")
                        self.assertIn("遮挡", detail)
                        self.assertIn("放弃帖子？", detail)
                        self.assertIn("放弃帖子？", stderr)
                        self.assertIn("遮挡", stderr)
                    self.assertEqual(record, expected_ai)
                    self.assertEqual(holder["ai_checked"], checked)
                    self.assertEqual(holder["ai_clicks"], clicks)

    def test_visible_but_unreadable_ai_blocks_share_for_video_and_note(self):
        """可见但读不出状态：CLI 退出 1，AI 记 mismatch，Share 零点击。"""
        for action in ("upload-video", "upload-note"):
            with self.subTest(action=action):
                control = _FakeAiControl([], presence="present")
                with patch(
                    "uploader.meta_uploader.insgraph_uploader.main."
                    "resolve_instagram_option_controls",
                    lambda *args, **kwargs: {"ai_generated": control},
                ):
                    code, saved, holder, _, stderr = self._run(
                        action=action,
                        html=_composer_html(_AI_SWITCH_HTML["already_off"]),
                    )
                self.assertEqual(code, 1, stderr)
                self.assertEqual(saved["status"], "not_submitted")
                self.assertEqual(
                    saved["options"]["ai_generated"],
                    {"requested": False, "applied": None, "status": MISMATCH},
                )
                # 不盲点可见开关：只允许 resolve + read。
                self.assertEqual(control.calls, ["resolve", "read"])
                self.assertEqual(holder["share_clicks"], 0)

    def test_omitted_ai_generated_preserves_current_page_value(self):
        for action in ("upload-video", "upload-note"):
            with self.subTest(action=action):
                code, saved, holder, stdout, stderr = self._run(
                    action=action,
                    html=_composer_html(_AI_SWITCH_HTML["currently_on"]),
                    ai_args=(),
                )
                self.assertEqual(code, 0, stderr)
                self.assertEqual(holder["share_clicks"], 0)
                self.assertEqual(saved["status"], "prepared")
                printed = json.loads(stdout)
                self.assertEqual(printed["status"], "prepared")
                self.assertEqual(
                    printed["options"]["ai_generated"],
                    {
                        "requested": None,
                        "applied": None,
                        "status": NOT_REQUESTED,
                    },
                )
                self.assertEqual(
                    saved["options"]["ai_generated"],
                    {
                        "requested": None,
                        "applied": None,
                        "status": NOT_REQUESTED,
                    },
                )
                # 页面原值保持开启，零点击、零回读副作用。
                self.assertEqual(holder["ai_checked"], "true")
                self.assertEqual(holder["ai_clicks"], 0)


if __name__ == "__main__":
    unittest.main()
