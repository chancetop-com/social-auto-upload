"""Instagram ``--no-publish`` 干跑回归（ARM → 停止，不点击 Share）。

A 层：两个上传命令都注册参数，默认 ``False``，请求一路传到上传器。
B 层：真实 Chrome 配文页驱动 ``_publish``，证明选项仍被应用、Share 零点击、
不进入结果观察循环、跳过 ``--not-before``、结果文件标记 ``prepared``。
就绪等待超时必须抛普通 ``RuntimeError``（退出 1，绝不退出 9）。
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from loguru import logger
from patchright.async_api import async_playwright

import sau_cli
from sau_commands import instagram as instagram_command
from uploader.meta_uploader.insgraph_uploader.main import InstagramUploader
from uploader.meta_uploader.insgraph_uploader.options import (
    SET,
    InstagramPublishOptions,
)
from utils.errors import PublishResultUnknownError

NO_PUBLISH_HELP = "跑到发布就绪点即停止，不点击发布（回归测试用）"
DRY_RUN_LOG = "Instagram 发布就绪，--no-publish 停在 Share 前（未点击发布）"
_PUBLISHED_KEYS = ("content_id", "post_id", "post_url", "schedule", "media_count")


def _subparser(parser: argparse.ArgumentParser, platform: str, action: str):
    for item in parser._actions:
        if isinstance(item, argparse._SubParsersAction) and platform in item.choices:
            for nested in item.choices[platform]._actions:
                if isinstance(nested, argparse._SubParsersAction):
                    return nested.choices[action]
    raise AssertionError(f"parser not found: {platform}/{action}")


class InstagramNoPublishParserTests(unittest.TestCase):
    """两个上传命令都接受 ``--no-publish``，未传时默认 ``False``。"""

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

    def test_both_upload_commands_register_the_flag_with_the_documented_help(self):
        for action in ("upload-video", "upload-note"):
            with self.subTest(action=action):
                parser = _subparser(sau_cli.build_parser(), "instagram", action)
                flag = parser._option_string_actions["--no-publish"]
                self.assertIn(NO_PUBLISH_HELP, flag.help)

    def test_flag_defaults_to_false_and_parses_true_for_both_actions(self):
        for make_argv in (self._note_argv, self._video_argv):
            with self.subTest(command=make_argv()):
                self.assertIs(self._parse(make_argv()).no_publish, False)
                self.assertIs(
                    self._parse(make_argv("--no-publish")).no_publish, True
                )

    def test_dry_run_does_not_require_or_touch_publish_options(self):
        args = self._parse(self._video_argv("--no-publish"))
        self.assertIsNone(instagram_command._build_publish_options(args))


class InstagramNoPublishPlumbingTests(unittest.TestCase):
    """请求数据类默认 ``False``，并经 ``upload_instagram_content`` 传到上传器。"""

    def test_request_defaults_to_false(self):
        request = instagram_command.InstagramUploadRequest(
            "creator", "caption", "", [], image_files=[Path("image.png")]
        )
        self.assertIs(request.no_publish, False)

    def test_request_forwards_no_publish_to_uploader(self):
        request = instagram_command.InstagramUploadRequest(
            "creator", "caption", "", [], image_files=[Path("image.png")],
            no_publish=True,
        )
        with patch.object(instagram_command, "InstagramUploader") as constructor:
            constructor.return_value.upload = AsyncMock(
                return_value={"status": "prepared"}
            )
            asyncio.run(instagram_command.upload_instagram_content(request))
        self.assertIs(constructor.call_args.kwargs["no_publish"], True)


# 配文页：AI 开关 + Lexical 配文框 + Share。Share 的 onclick 只记录点击次数，
# 用来证明干跑没有进入 FIRE/OBSERVE。
_DRY_RUN_DIALOG_HTML = """
<div role="dialog" id="compose">
  <div data-share-clicks="0"></div>
  <div class="row" id="ai-row">
    <div><div><span dir="auto">Add AI label</span></div></div>
    <div><div><div><div>
      <input id="ai-switch" role="switch" type="checkbox" aria-checked="false">
    </div></div></div></div>
  </div>
  <div role="textbox" contenteditable="true" data-lexical-editor="true"></div>
  <div role="button" id="share"
       onclick="const holder=document.querySelector('[data-share-clicks]');
                holder.dataset.shareClicks=String(Number(holder.dataset.shareClicks||0)+1);
                fetch('/api/v1/media/configure_to_clips/', {method:'POST'})">Share</div>
</div>
<script>
  const aiSwitch = document.getElementById('ai-switch');
  aiSwitch.addEventListener('click', () => {
    aiSwitch.setAttribute('aria-checked', String(aiSwitch.checked));
  });
</script>
"""


class InstagramNoPublishFlowTests(unittest.TestCase):
    """真实 Chrome DOM：干跑停在 Share 前，但表单与选项全部完成。"""

    def _run_publish(self, *, html, no_publish=True, options=None,
                     publish_not_before=None, budget_seconds=None):
        """在真实页面上执行 ``_publish``，返回 (app, saved_result, clicks, log)。"""

        async def scenario():
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel="chrome", headless=True)
                page = await browser.new_page()
                try:
                    await page.set_content(html)
                    with tempfile.TemporaryDirectory() as folder:
                        video = Path(folder) / "video.mp4"
                        video.touch()
                        result_file = Path(folder) / "result.json"
                        app = InstagramUploader(
                            "unused.json", title="caption", video_file=video,
                            options=options, result_file=result_file,
                            no_publish=no_publish,
                        )
                        app.publish_not_before = publish_not_before
                        budget = app.start_publish_budget()
                        if budget_seconds is not None:
                            budget.deadline = time.monotonic() + budget_seconds
                        buffer = io.StringIO()
                        handler_id = logger.add(
                            buffer, level="INFO", format="{message}\n"
                        )
                        try:
                            await app._publish(
                                page,
                                {"user_id": "42", "username": "creator"},
                                budget=budget,
                            )
                        finally:
                            logger.remove(handler_id)
                        holder = page.locator("[data-share-clicks]")
                        clicks = int(
                            await holder.get_attribute("data-share-clicks") or 0
                        )
                        saved = json.loads(
                            result_file.read_text(encoding="utf-8")
                        )
                        return app, saved, clicks, buffer.getvalue()
                finally:
                    await browser.close()

        return asyncio.run(scenario())

    def test_dry_run_applies_options_and_never_clicks_share(self):
        app, saved, clicks, log = self._run_publish(
            html=_DRY_RUN_DIALOG_HTML,
            options=InstagramPublishOptions(ai_generated=True),
        )
        # 选项仍在干跑中生效，且结果文件保留选项记录。
        self.assertEqual(app.result["options"]["ai_generated"]["status"], SET)
        # Share 完全没被点击，也没有发布字段。
        self.assertEqual(clicks, 0)
        self.assertEqual(app.result["status"], "prepared")
        for key in _PUBLISHED_KEYS:
            self.assertNotIn(key, app.result)
        self.assertIn(DRY_RUN_LOG, log)
        self.assertEqual(saved["status"], "prepared")
        for key in _PUBLISHED_KEYS:
            self.assertNotIn(key, saved)

    def test_dry_run_skips_not_before_wait(self):
        # 远未来的 --not-before：正常发布必然被卡住；干跑必须跳过。
        not_before = time.mktime(
            time.strptime("2099-01-01 00:00", "%Y-%m-%d %H:%M")
        )
        with patch(
            "uploader.publish_timeout.PublishTimeoutBudget.wait_until_allowed",
            AsyncMock(),
        ) as wait:
            app, saved, clicks, _ = self._run_publish(
                html=_DRY_RUN_DIALOG_HTML,
                publish_not_before=not_before,
            )
        wait.assert_not_awaited()
        self.assertEqual(app.result["status"], "prepared")
        self.assertEqual(clicks, 0)

    def test_readiness_timeout_is_a_plain_runtime_error_not_result_unknown(self):
        disabled_html = _DRY_RUN_DIALOG_HTML.replace(
            '<div role="button" id="share"',
            '<div role="button" id="share" aria-disabled="true" disabled',
        )
        with self.assertRaises(RuntimeError) as ctx:
            self._run_publish(html=disabled_html, budget_seconds=0.6)
        self.assertNotIsInstance(ctx.exception, PublishResultUnknownError)
        self.assertIn("发布就绪", str(ctx.exception))

    def test_normal_publish_path_still_clicks_share(self):
        """无该参数时行为不变：只为对照，缺省仍是 FIRE。"""
        async def scenario():
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel="chrome", headless=True)
                page = await browser.new_page()
                try:
                    await page.set_content(_DRY_RUN_DIALOG_HTML)
                    with tempfile.TemporaryDirectory() as folder:
                        video = Path(folder) / "video.mp4"
                        video.touch()
                        app = InstagramUploader(
                            "unused.json", title="caption", video_file=video,
                            result_file=Path(folder) / "result.json",
                        )
                        budget = app.start_publish_budget()
                        budget.deadline = time.monotonic() + 1
                        with self.assertRaises(PublishResultUnknownError):
                            await app._publish(
                                page,
                                {"user_id": "42", "username": "creator"},
                                budget=budget,
                            )
                        clicks = int(
                            await page.locator("[data-share-clicks]")
                            .get_attribute("data-share-clicks") or 0
                        )
                        self.assertEqual(clicks, 1)
                finally:
                    await browser.close()

        asyncio.run(scenario())


class InstagramNoPublishExitTests(unittest.TestCase):
    """命令层：干跑结果打印后退出 0，不走异常映射。"""

    def test_prepared_result_exits_zero_and_prints_result(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "image.png"
            image.touch()
            upload = AsyncMock(return_value={"status": "prepared"})
            output = io.StringIO()
            with patch.object(
                instagram_command, "upload_instagram_content", upload
            ), contextlib.redirect_stdout(output), contextlib.redirect_stderr(
                io.StringIO()
            ):
                code = sau_cli.main([
                    "instagram", "upload-note", "--account", "creator",
                    "--images", str(image), "--title", "caption",
                    "--no-publish",
                ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "prepared")
        self.assertIs(upload.await_args.args[0].no_publish, True)


if __name__ == "__main__":
    unittest.main()
