"""Regression coverage for the committed Rednote review, without remote access."""

import asyncio
import importlib
import inspect
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import sau_cli
from utils.browser_cleanup import close_browser_resources
from utils.dom import ElementUnusableError
from utils.humanize import MAYBE_DISPATCHED, MAYBE_DISPATCHED_VALUE
from utils.topic_candidates import click_topic_candidate


class AccountCheckCleanupTests(unittest.TestCase):
    def test_cli_rejects_single_line_controls_before_dispatch(self):
        actions = {
            "rednote": ("upload-video", "upload-note"),
            "xiaohongshu": ("upload-video", "upload-note"),
            "tiktok": ("upload-note",),
        }
        for platform, commands in actions.items():
            for action in commands:
                for control in ("\n", "\r", "\t"):
                    with self.subTest(platform=platform, action=action, control=repr(control)):
                        output = io.StringIO()
                        with (
                            patch.object(sau_cli, "dispatch", AsyncMock()) as dispatch,
                            redirect_stderr(output),
                            self.assertRaises(SystemExit) as caught,
                        ):
                            sau_cli.main([platform, action, "--title", f"hello{control}world"])
                        self.assertEqual(caught.exception.code, 2)
                        self.assertIn("单行", output.getvalue())
                        dispatch.assert_not_called()


class InputAndCandidateTests(unittest.IsolatedAsyncioTestCase):

    async def test_all_login_probes_keep_the_original_error_when_page_close_fails(self):
        modules = (
            "meta_uploader.facebook_page_uploader.main", "meta_uploader.facebook_uploader.main",
            "meta_uploader.insgraph_uploader.main",
            "tk_uploader.main_chrome",
            "youtube_uploader.main",
        )
        for name in modules:
            with self.subTest(platform=name):
                module = importlib.import_module(f"uploader.{name}")
                original = RuntimeError("navigation failed")
                page = SimpleNamespace(
                    goto=AsyncMock(side_effect=original),
                    close=AsyncMock(side_effect=RuntimeError("close failed")),
                )
                context = SimpleNamespace(new_page=AsyncMock(return_value=page), pages=[])
                with self.assertRaises(RuntimeError) as caught:
                    await module.is_logged_in(context)
                self.assertIs(caught.exception, original)
                page.close.assert_awaited_once()

    async def test_single_line_titles_fail_before_browser_or_file_validation(self):
        paths = {
            "rednote_uploader.main": ("RednoteVideo", "RednoteNote"),
            "xiaohongshu_uploader.main": ("XiaoHongShuVideo", "XiaoHongShuNote"),
        }
        for path, names in paths.items():
            module = importlib.import_module(f"uploader.{path}")
            for name in names:
                cls = getattr(module, name)
                for control in ("\n", "\r", "\t"):
                    with self.subTest(uploader=name, control=repr(control)):
                        app = cls.__new__(cls)
                        app.title = f"hello{control}world"
                        app.image_paths = ["unused.png"]
                        app.tags = []
                        app.max_title_length = 30
                        app.validate_base_args = AsyncMock()
                        with self.assertRaisesRegex(ValueError, "单行"):
                            result = app.validate_upload_args()
                            if inspect.isawaitable(result):
                                await result

    async def test_derived_titles_keep_multiline_body_and_normalize_only_title(self):
        for platform, prefix in (("rednote", "Rednote"), ("xiaohongshu", "XiaoHongShu")):
            module = importlib.import_module(f"uploader.{platform}_uploader.main")
            cls = getattr(module, prefix + "Note")
            body = "hello\r\nworld\t标题"
            app = cls(["unused.png"], body, [], 0, "unused.json")
            self.assertEqual(app.title, "hello world 标题")
            self.assertEqual(app.note, body)

    async def test_tiktok_photo_title_rejects_controls_but_video_caption_stays_multiline(self):
        from uploader.tk_uploader.main_chrome import TiktokNote, TiktokVideo

        for control in ("\n", "\r", "\t"):
            with self.assertRaisesRegex(ValueError, "单行"):
                TiktokNote([], "body", [], 0, "unused.json", title=f"hello{control}world")
        caption = "line one\nline two"
        self.assertEqual(TiktokVideo(caption, "unused.mp4", [], 0, "unused.json").title, caption)

    async def test_candidate_errors_never_retry_uncertain_clicks_or_structural_errors(self):
        for reason, dispatched in (("point-drift", True), ("ambiguous:2", False),
                                   ("covered-by:div", False)):
            with self.subTest(reason=reason, dispatched=dispatched):
                error = ElementUnusableError("candidate", reason=reason)
                if dispatched:
                    setattr(error, MAYBE_DISPATCHED, MAYBE_DISPATCHED_VALUE)
                candidate = SimpleNamespace(evaluate=AsyncMock(side_effect=[True, False]))
                humanizer = SimpleNamespace(click=AsyncMock(side_effect=error))
                with self.assertRaises(ElementUnusableError) as caught:
                    await click_topic_candidate(candidate, humanizer)
                self.assertIs(caught.exception, error)
                humanizer.click.assert_awaited_once()
                candidate.evaluate.assert_awaited_once()

    async def test_candidate_connection_probe_failure_is_not_treated_as_detachment(self):
        candidate = SimpleNamespace(evaluate=AsyncMock(side_effect=RuntimeError("page closed")))
        humanizer = SimpleNamespace(click=AsyncMock())
        with self.assertRaisesRegex(RuntimeError, "page closed"):
            await click_topic_candidate(candidate, humanizer)
        humanizer.click.assert_not_awaited()

    async def test_connected_drift_requires_positive_style_and_enabled_probes(self):
        for failed_probe in ("style", "enabled"):
            with self.subTest(probe=failed_probe):
                error = ElementUnusableError("candidate", reason="point-drift")
                style = RuntimeError("style unavailable") if failed_probe == "style" else {"isConnected": True}
                candidate = SimpleNamespace(
                    evaluate=AsyncMock(side_effect=[True, True, style, {"self": True}]),
                    is_visible=AsyncMock(return_value=True),
                    is_enabled=AsyncMock(side_effect=RuntimeError("enabled unavailable")),
                    bounding_box=AsyncMock(return_value={"width": 80, "height": 30}),
                )
                humanizer = SimpleNamespace(click=AsyncMock(side_effect=error))
                with self.assertRaises(ElementUnusableError) as caught:
                    await click_topic_candidate(candidate, humanizer, rescan_moved=True)
                self.assertIs(caught.exception, error)
                humanizer.click.assert_awaited_once()

    async def test_page_cleanup_preserves_primary_result_and_cancellation(self):
        for error in (RuntimeError("cleanup"), asyncio.CancelledError()):
            page = SimpleNamespace(close=AsyncMock(side_effect=error))
            context = SimpleNamespace(close=AsyncMock(side_effect=RuntimeError("cleanup")))
            browser = SimpleNamespace(close=AsyncMock())
            if isinstance(error, asyncio.CancelledError):
                with self.assertRaises(asyncio.CancelledError):
                    await close_browser_resources(page=page, context=context, browser=browser)
            else:
                await close_browser_resources(page=page, context=context, browser=browser)
            context.close.assert_awaited_once()
            browser.close.assert_awaited_once()
