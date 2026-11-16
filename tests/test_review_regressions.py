"""Regression coverage for the committed Rednote review, without remote access."""

import asyncio
import importlib
import inspect
import io
import os
import unittest
from contextlib import asynccontextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import sau_cli
from utils.browser_cleanup import close_browser_resources
from utils.dom import ElementUnusableError
from utils.humanize import MAYBE_DISPATCHED, MAYBE_DISPATCHED_VALUE
from utils.topic_candidates import click_topic_candidate


class AccountCheckCleanupTests(unittest.TestCase):
    def test_check_preserves_exit_code_and_output_after_cleanup_failure(self):
        for platform in ("rednote", "xiaohongshu"):
            command = importlib.import_module(f"sau_commands.{platform}")
            module = importlib.import_module(f"uploader.{platform}_uploader.main")
            for probe, expected in (("valid", 0), ("login", 10), ("verification", 10)):
                for failure in ("page", "context", "browser", "both", "save"):
                    with self.subTest(platform=platform, probe=probe, failure=failure):
                        page = SimpleNamespace(
                            url=f"https://creator.{platform}.com/publish/publish",
                            goto=AsyncMock(return_value=SimpleNamespace(status=200)),
                            wait_for_timeout=AsyncMock(),
                            locator=lambda selector: SimpleNamespace(count=AsyncMock(return_value=1)),
                            close=AsyncMock(side_effect=RuntimeError("page close") if failure == "page" else None),
                        )
                        context = SimpleNamespace(
                            new_page=AsyncMock(return_value=page),
                            close=AsyncMock(side_effect=RuntimeError("context close")
                                            if failure in {"context", "both", "save"} else None),
                        )
                        browser = SimpleNamespace(
                            new_context=AsyncMock(return_value=context),
                            close=AsyncMock(side_effect=RuntimeError("browser close")
                                            if failure in {"browser", "both", "save"} else None),
                        )

                        @asynccontextmanager
                        async def playwright(browser=browser):
                            yield SimpleNamespace(chromium=SimpleNamespace(
                                launch=AsyncMock(return_value=browser),
                            ))

                        output = io.StringIO()
                        save = AsyncMock(side_effect=OSError("save failed") if failure == "save" else None)
                        with (
                            patch.dict(os.environ, {"MLX_API_TOKEN": "", "ADSPOWER_API_KEY": ""}),
                            patch.object(command, "async_playwright", playwright),
                            patch.object(command, "resolve_account_file", return_value="unused.json"),
                            patch.object(command, "local_session_preflight", AsyncMock()),
                            patch.object(command, f"{platform}_user_agent", AsyncMock(return_value="test")),
                            patch.object(command, "set_init_script", AsyncMock(return_value=context)),
                            patch.object(command, "log_local_session_ready"),
                            patch.object(module, "classify_blocked", AsyncMock(return_value=None if probe == "valid" else probe)),
                            patch.object(command, "save_storage_state_atomic", save),
                            redirect_stdout(output), redirect_stderr(io.StringIO()),
                        ):
                            code = sau_cli.main([platform, "check", "--account", "test"])
                        wanted = 1 if failure == "save" and probe == "valid" else expected
                        self.assertEqual(code, wanted)
                        self.assertEqual(output.getvalue().strip(), "valid" if wanted == 0 else "invalid")
                        context.close.assert_awaited_once()
                        browser.close.assert_awaited_once()
                        page.close.assert_awaited_once()
                        self.assertEqual(save.await_count, int(probe == "valid"))

    def test_cli_rejects_single_line_controls_before_dispatch(self):
        actions = {
            "rednote": ("upload-video", "upload-note"),
            "xiaohongshu": ("upload-video", "upload-note"),
            "douyin": ("upload-video", "upload-note"),
            "alipay": ("upload-video",), "baijiahao": ("upload-video",),
            "weibo": ("upload-video",), "dayu": ("upload-video", "upload-article"),
            "zhihu": ("upload-video", "upload-article"), "xueqiu": ("upload-article",),
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
    async def test_meta_openers_keep_setup_error_when_cleanup_also_fails(self):
        for platform, name in (("facebook_uploader", "_open_facebook_page"),
                               ("facebook_page_uploader", "_open_business_page"),
                               ("insgraph_uploader", "_open_instagram_page")):
            with self.subTest(platform=platform):
                module = importlib.import_module(f"uploader.meta_uploader.{platform}.main")
                original = ValueError("invalid storage state")
                browser = SimpleNamespace(new_context=AsyncMock(side_effect=original),
                                          close=AsyncMock(side_effect=RuntimeError("close failed")))
                playwright = SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)))
                with self.assertRaises(ValueError) as caught:
                    await getattr(module, name)(playwright, Path("unused.json"), proxy=None, headless=True)
                self.assertIs(caught.exception, original)
                browser.close.assert_awaited_once()

    async def test_user_agent_probe_preserves_value_and_original_error(self):
        for platform, function in (("rednote", "_rednote_user_agent"), ("xiaohongshu", "_xhs_user_agent")):
            module = importlib.import_module(f"uploader.{platform}_uploader.main")
            for original in (None, ValueError("UA unavailable")):
                with self.subTest(platform=platform, failing=bool(original)):
                    page = SimpleNamespace(evaluate=AsyncMock(return_value="HeadlessChrome/test", side_effect=original))
                    context = SimpleNamespace(new_page=AsyncMock(return_value=page), close=AsyncMock(side_effect=RuntimeError("close failed")))
                    browser = SimpleNamespace(new_context=AsyncMock(return_value=context))
                    if original:
                        with self.assertRaises(ValueError) as caught:
                            await getattr(module, function)(browser)
                        self.assertIs(caught.exception, original)
                    else:
                        self.assertEqual(await getattr(module, function)(browser), "Chrome/test")
                    context.close.assert_awaited_once()

    async def test_alipay_tags_and_douyin_product_title_cannot_send_navigation_keys(self):
        from sau_commands.alipay import upload_alipay_video
        from uploader.alipay_uploader.main import format_title_with_tags
        from uploader.douyin_uploader.main import DouYinVideo

        for control in ("\n", "\r", "\t"):
            with self.subTest(control=repr(control)):
                request = SimpleNamespace(title="Title", tags=[f"a{control}b"])
                with self.assertRaisesRegex(ValueError, "单行"):
                    await upload_alipay_video(request)
                with self.assertRaisesRegex(ValueError, "单行"):
                    format_title_with_tags(request.title, request.tags)
                with self.assertRaisesRegex(ValueError, "单行"):
                    DouYinVideo("Title", "unused.mp4", [], 0, "unused.json", productTitle=f"a{control}b")

    async def test_tencent_title_parameter_remains_a_multiline_description(self):
        from uploader.tencent_uploader.main import TencentVideo

        caption = "first line\nsecond line"
        app = TencentVideo(caption, "unused.mp4", [], 0, "unused.json")
        with patch.object(app, "validate_video_file", return_value=Path("unused.mp4")):
            await app.validate_upload_args(check_cookie=False)
        self.assertEqual(app.title, caption)
    async def test_all_login_probes_keep_the_original_error_when_page_close_fails(self):
        modules = (
            "alipay_uploader.main", "baijiahao_uploader.main", "dayu_uploader.session",
            "douyin_uploader.main", "hupu_uploader.main", "ks_uploader.main",
            "meta_uploader.facebook_page_uploader.main", "meta_uploader.facebook_uploader.main",
            "meta_uploader.insgraph_uploader.main", "tencent_uploader.main",
            "tk_uploader.main_chrome", "weibo_uploader.main", "xueqiu_uploader.session",
            "youtube_uploader.main", "zhihu_uploader.session",
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
            "alipay_uploader.main": ("AlipayVideo",),
            "baijiahao_uploader.main": ("BaiJiaHaoVideo",),
            "weibo_uploader.main": ("WeiBoVideo",),
            "douyin_uploader.main": ("DouYinVideo", "DouYinNote"),
            "dayu_uploader.main": ("DayuVideo",),
            "dayu_uploader.article": ("DayuArticle",),
            "zhihu_uploader.article": ("ZhihuArticle",),
            "zhihu_uploader.video": ("ZhihuVideo",),
            "xueqiu_uploader.article": ("XueqiuArticle",),
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
        for platform, prefix in (("rednote", "Rednote"), ("xiaohongshu", "XiaoHongShu"),
                                 ("douyin", "DouYin")):
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
