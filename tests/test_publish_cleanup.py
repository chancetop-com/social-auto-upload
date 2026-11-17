"""Fault injection through actual local upload/session wrappers; no browser/network."""

import asyncio
import importlib
import io
import unittest
from contextlib import ExitStack, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import sau_cli
from utils.browser_session import _local_session
from utils.errors import LoginRequiredError, PublishResultUnknownError

LOCAL_UPLOADS = (
    ("ks", "KSVideo"),
    ("ks", "KSNote"),
    ("tencent", "TencentVideo"),
    ("tencent", "TencentNote"),
    ("alipay", "AlipayVideo"),
    ("weibo", "WeiBoVideo"),
    ("baijiahao", "BaiJiaHaoVideo"),
    ("hupu", "HuPuVideo"),
    ("douyin", "DouYinVideo"),
    ("douyin", "DouYinNote"),
    # YouTube persistent outcomes: test_youtube_profiles.
    # Xiaohongshu persistent outcomes: test_xhs_profile_cli.
    # TikTok persistent-context outcomes are covered by test_tiktok_profile_cli.
)


class LocalFixture:
    def __init__(self, *, context_error=None, browser_error=None, save_error=None):
        self.page = SimpleNamespace(wait_for_timeout=AsyncMock())
        self.context = SimpleNamespace(
            close=AsyncMock(side_effect=context_error),
            storage_state=AsyncMock(side_effect=save_error),
            new_page=AsyncMock(return_value=self.page),
        )
        self.browser = SimpleNamespace(
            new_context=AsyncMock(return_value=self.context),
            close=AsyncMock(side_effect=browser_error),
        )
        self.playwright = SimpleNamespace(
            chromium=SimpleNamespace(launch=AsyncMock(return_value=self.browser))
        )

    async def upload(self, platform, class_name, primary_error=None):
        module = importlib.import_module(
            f"uploader.{platform}_uploader.{'main_chrome' if platform == 'tk' else 'main'}"
        )
        cls = getattr(module, class_name)
        app = cls.__new__(cls)
        app.account_file = Path("/tmp/not-accessed-cookie.json")
        app.headless = True
        app.title = "fixture"
        app.validate_upload_args = AsyncMock()
        app.upload_in = AsyncMock(side_effect=primary_error)
        app._upload_on_page = AsyncMock(side_effect=primary_error)
        app.change_language = AsyncMock()
        # YouTube returns the page for its post-success pause.
        app.upload_in.return_value = self.page
        with ExitStack() as stack:
            for name, value in (
                ("set_init_script", self.context),
                ("_create_stealth_context", self.context),
                ("_new_stealth_page", self.page),
                ("_new_local_context", self.context),
                ("_xhs_user_agent", "fixture"),
            ):
                if hasattr(module, name):
                    stack.enter_context(
                        patch.object(module, name, AsyncMock(return_value=value))
                    )
            if hasattr(module, "save_storage_state_atomic"):
                stack.enter_context(
                    patch.object(
                        module, "save_storage_state_atomic", self.context.storage_state
                    )
                )
            stack.enter_context(patch.object(module.asyncio, "sleep", AsyncMock()))
            await app.upload(self.playwright)
        app.upload_in.assert_awaited_once() if platform != "tk" else app._upload_on_page.assert_awaited_once()


class PublishCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_uploads_preserve_primary_outcome_and_attempt_both_closes(self):
        for platform, cls in LOCAL_UPLOADS:
            for outcome in (
                None,
                PublishResultUnknownError("unknown"),
                LoginRequiredError("login", publish_attempted=True),
                ValueError("primary"),
            ):
                for failing in ("context", "browser", "both"):
                    with self.subTest(
                        platform=platform,
                        uploader=cls,
                        outcome=type(outcome).__name__,
                        failing=failing,
                    ):
                        fixture = LocalFixture(
                            context_error=RuntimeError("context cleanup")
                            if failing != "browser"
                            else None,
                            browser_error=RuntimeError("browser cleanup")
                            if failing != "context"
                            else None,
                        )
                        caught = None
                        try:
                            await fixture.upload(platform, cls, outcome)
                        except Exception as error:  # noqa: BLE001 - assert the exact primary exception
                            caught = error
                        self.assertIs(caught, outcome)
                        fixture.context.close.assert_awaited_once()
                        fixture.browser.close.assert_awaited_once()

    async def test_cookie_writeback_cannot_turn_success_into_a_retryable_failure(self):
        for platform, cls in LOCAL_UPLOADS:
            with self.subTest(platform=platform, uploader=cls):
                fixture = LocalFixture(save_error=OSError("cookie writeback"))
                await fixture.upload(platform, cls)
                fixture.context.close.assert_awaited_once()
                fixture.browser.close.assert_awaited_once()

    async def test_shared_local_session_preserves_result_and_closes_after_writeback_failure(
        self,
    ):
        for outcome in (
            None,
            PublishResultUnknownError("unknown"),
            ValueError("primary"),
        ):
            with self.subTest(outcome=type(outcome).__name__):
                fixture = LocalFixture(
                    context_error=RuntimeError("context cleanup"),
                    browser_error=RuntimeError("browser cleanup"),
                    save_error=OSError("cookie writeback"),
                )
                caught = None
                try:
                    async with _local_session(
                        fixture.playwright,
                        headless=True,
                        account_file="/tmp/not-accessed.json",
                        launch_kwargs={},
                        context_kwargs={},
                        init_script=False,
                        context_setup=None,
                    ):
                        if outcome is not None:
                            raise outcome
                except Exception as error:  # noqa: BLE001 - assert the exact primary exception
                    caught = error
                self.assertIs(caught, outcome)
                fixture.context.close.assert_awaited_once()
                fixture.browser.close.assert_awaited_once()


# Rednote cleanup and CLI outcomes now run through real persistent sessions in
# tests.test_rednote_profile_cli.


class OtherPublicationCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_browser_only_local_entries_preserve_success_and_unknown(self):
        from unittest.mock import MagicMock, Mock

        entries = (
            ("uploader.zhihu_uploader.video", "ZhihuVideo", "main", None),
            ("uploader.zhihu_uploader.article", "ZhihuArticle", "main", None),
            ("uploader.xueqiu_uploader.article", "XueqiuArticle", "main", None),
            (
                "uploader.meta_uploader.facebook_uploader.main",
                "FacebookPost",
                "upload",
                "_open_facebook_page",
            ),
        )
        for module_name, cls, entry, opener in entries:
            for outcome in (None, PublishResultUnknownError("primary unknown")):
                with self.subTest(module=module_name, outcome=type(outcome).__name__):
                    fixture = LocalFixture(
                        browser_error=RuntimeError("browser cleanup"),
                        save_error=OSError("cookie writeback"),
                    )
                    module = importlib.import_module(module_name)
                    app = getattr(module, cls).__new__(getattr(module, cls))
                    app.account_file = Path(__file__)
                    app.headless = True
                    app.proxy = None
                    app.result = {"status": "fixture"}
                    app.validate_upload_args = Mock()
                    app._validate_media = Mock()
                    app._humanizer = Mock()
                    app._write_result = Mock(side_effect=OSError("result writeback"))
                    app._capture_failure_safely = AsyncMock()
                    app.upload_in = AsyncMock(
                        side_effect=outcome, return_value=app.result
                    )
                    app._upload_steps = AsyncMock(
                        side_effect=outcome, return_value=app.result
                    )
                    app._publish_on_page = AsyncMock(side_effect=outcome)
                    manager = MagicMock()
                    manager.__aenter__ = AsyncMock(return_value=fixture.playwright)
                    manager.__aexit__ = AsyncMock(return_value=False)
                    with ExitStack() as stack:
                        stack.enter_context(
                            patch.object(
                                module, "async_playwright", return_value=manager
                            )
                        )
                        if opener:
                            stack.enter_context(
                                patch.object(
                                    module,
                                    opener,
                                    AsyncMock(
                                        return_value=(
                                            fixture.browser,
                                            fixture.context,
                                            fixture.page,
                                        )
                                    ),
                                )
                            )
                        for name in (
                            "_is_logged_out",
                            "_is_business_logged_out",
                            "instagram_identity",
                        ):
                            if hasattr(module, name):
                                stack.enter_context(
                                    patch.object(
                                        module, name, AsyncMock(return_value=False)
                                    )
                                )
                        caught = None
                        try:
                            if cls == "FacebookPost":
                                await app.upload(fixture.playwright)
                            else:
                                await getattr(app, entry)()
                        except Exception as error:  # noqa: BLE001 - assert the exact primary exception
                            caught = error
                    self.assertIs(caught, outcome)
                    fixture.browser.close.assert_awaited_once()

    async def test_instagram_handler_cleanup_preserves_publication_outcome(self):
        from uploader.meta_uploader.insgraph_uploader.main import InstagramUploader
        from uploader.publish_timeout import PublishTimeoutBudget

        for outcome in (None, PublishResultUnknownError("unknown")):
            with self.subTest(outcome=type(outcome).__name__):
                app = InstagramUploader.__new__(InstagramUploader)
                app._register_notification_handler = AsyncMock(return_value=object())
                result = {"status": "success"}
                app._upload_flow = AsyncMock(side_effect=outcome, return_value=result)
                page = SimpleNamespace(
                    remove_locator_handler=AsyncMock(
                        side_effect=RuntimeError("page closed")
                    )
                )
                caught = None
                try:
                    self.assertIs(
                        await app._upload_steps(
                            page, {}, budget=PublishTimeoutBudget("fixture")
                        ),
                        result,
                    )
                except Exception as error:  # noqa: BLE001 - assert the exact primary exception
                    caught = error
                self.assertIs(caught, outcome)

    async def test_cleanup_does_not_swallow_cancellation_and_still_closes_browser(self):
        from utils.browser_cleanup import close_browser_resources

        fixture = LocalFixture(context_error=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            await close_browser_resources(
                context=fixture.context, browser=fixture.browser
            )
        fixture.browser.close.assert_awaited_once()
