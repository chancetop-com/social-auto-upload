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
    # Kuaishou persistent outcomes: test_kuaishou_profiles.
    # TencentVideo persistent outcomes: test_tencent_profiles.
    ("tencent", "TencentNote"),
    # Alipay persistent outcomes: test_alipay_profiles.
    # Weibo persistent outcomes: test_weibo_profiles.
    # Baijiahao persistent outcomes: test_baijiahao_profiles.
    # Hupu persistent outcomes: test_hupu_profiles.
    # Douyin persistent outcomes: test_douyin_profile_cli.
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
