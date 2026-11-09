# -*- coding: utf-8 -*-
"""Zhihu (article/video) and Xueqiu (article) Multilogin seam (ticket 24).

Covers:
* golden local ``launch_kwargs`` / ``context_kwargs`` / timezone;
* Multilogin ignores those kwargs and never launches/creates contexts/scripts;
* Multilogin never calls the spec §6.2 forbidden APIs, never reads/writes cookie
  files, and never calls the identity reader/binding;
* ``is_logged_in`` returns True/False and raises for outages/unknown structure;
* CLI ``check`` 0/10/1/2 and ``upload-*`` 0/10/1 with exactly one session exit.
"""

from __future__ import annotations

import asyncio
import io
import os
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import sau_cli
from sau_commands import xueqiu as xueqiu_command
from sau_commands import zhihu as zhihu_command
from tests.fakes import FakePlaywright, ForbiddenApiError
from uploader.xueqiu_uploader import article as xueqiu_article
from uploader.xueqiu_uploader import session as xueqiu_session
from uploader.xueqiu_uploader.article import XueqiuArticle
from uploader.xueqiu_uploader.constants import (
    XUEQIU_CONTEXT_KWARGS,
    XUEQIU_HOME_URL,
    XUEQIU_LAUNCH_KWARGS,
)
from uploader.zhihu_uploader import article as zhihu_article
from uploader.zhihu_uploader import session as zhihu_session
from uploader.zhihu_uploader import video as zhihu_video
from uploader.zhihu_uploader.article import ZhihuArticle
from uploader.zhihu_uploader.constants import (
    ZHIHU_ARTICLE_URL,
    ZHIHU_CONTEXT_KWARGS,
    ZHIHU_CREATOR_URL,
    ZHIHU_LAUNCH_KWARGS,
    ZHIHU_VIDEO_URL,
)
from uploader.zhihu_uploader.video import ZhihuVideo
from utils.browser_session import BrowserSession
from utils.errors import LoginRequiredError

TOKEN = "SENTINEL-MLX-TOKEN-ticket24"


class _Response:
    def __init__(self, status: int = 200) -> None:
        self.status = status

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class _RecordingPage:
    def __init__(
        self,
        *,
        final_url: str = "about:blank",
        status: int = 200,
        goto_error: BaseException | None = None,
    ) -> None:
        self.url = "about:blank"
        self.final_url = final_url
        self.status = status
        self.goto_error = goto_error
        self.goto_calls: list[tuple[str, dict]] = []
        self.screenshots: list[tuple[tuple, dict]] = []
        self.closed = False

    async def goto(self, url: str, **kwargs):
        self.goto_calls.append((url, kwargs))
        if self.goto_error is not None:
            raise self.goto_error
        self.url = self.final_url
        return _Response(self.status)

    async def screenshot(self, *args, **kwargs) -> None:
        self.screenshots.append((args, kwargs))

    async def close(self) -> None:
        self.closed = True


class _SeamContext:
    """BrowserContext double: only the allowed MLX APIs are implemented."""

    def __init__(self, page: _RecordingPage) -> None:
        self.page = page
        self.new_page_calls = 0
        self.storage_state_calls: list[object] = []
        self.add_init_script_calls = 0
        self.forbidden_calls: list[str] = []
        self.closed = False

    async def new_page(self) -> _RecordingPage:
        self.new_page_calls += 1
        return self.page

    async def storage_state(self, *, path=None, **kwargs):
        self.storage_state_calls.append(path)
        return {"cookies": []}

    async def add_init_script(self, *args, **kwargs) -> None:
        self.add_init_script_calls += 1

    async def _forbidden(self, name: str, *args, **kwargs) -> None:
        self.forbidden_calls.append(name)
        raise ForbiddenApiError(f"{name} is forbidden in Multilogin mode")

    async def add_cookies(self, *args, **kwargs):
        await self._forbidden("add_cookies", *args, **kwargs)

    async def clear_cookies(self, *args, **kwargs):
        await self._forbidden("clear_cookies", *args, **kwargs)

    async def route(self, *args, **kwargs):
        await self._forbidden("route", *args, **kwargs)

    async def grant_permissions(self, *args, **kwargs):
        await self._forbidden("grant_permissions", *args, **kwargs)

    async def set_geolocation(self, *args, **kwargs):
        await self._forbidden("set_geolocation", *args, **kwargs)

    async def set_extra_http_headers(self, *args, **kwargs):
        await self._forbidden("set_extra_http_headers", *args, **kwargs)

    async def emulate_media(self, *args, **kwargs):
        await self._forbidden("emulate_media", *args, **kwargs)

    async def set_viewport_size(self, *args, **kwargs):
        await self._forbidden("set_viewport_size", *args, **kwargs)

    async def close(self) -> None:
        self.closed = True


class _AsyncCM:
    def __init__(self, value=None) -> None:
        self.value = value
        self.enter_calls = 0
        self.exit_calls = 0

    async def __aenter__(self):
        self.enter_calls += 1
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        self.exit_calls += 1
        return False


def _mlx_session(page: _RecordingPage) -> tuple[BrowserSession, _SeamContext]:
    context = _SeamContext(page)
    return BrowserSession(browser=MagicMock(), context=context, mode="multilogin"), context


def _make_zhihu_article(folder: str, *, account_file=None, prepare_only=True) -> tuple[ZhihuArticle, Path]:
    root = Path(folder)
    content = root / "article.html"
    if not content.exists():
        content.write_text("<p>正文</p>", encoding="utf-8")
    app = ZhihuArticle(
        "文章标题", content, account_file,
        prepare_only=prepare_only, headless=False,
    )
    app.document = SimpleNamespace(manifest={"structure_sha256": "x"})
    app.uploaded_images = []
    app.images = []
    app.identity = None
    return app, content


def _make_zhihu_video(
    folder: str, *, account_file=None, prepare_only=True
) -> tuple[ZhihuVideo, Path]:
    root = Path(folder)
    video = root / "video.mp4"
    if not video.exists():
        video.write_bytes(b"video")
    app = ZhihuVideo(
        "视频标题示例", video, account_file, "", None, [], None, "original",
        headless=False, prepare_only=prepare_only,
    )
    app.identity = None
    return app, video


def _make_xueqiu_article(folder: str, *, account_file=None, prepare_only=True) -> tuple[XueqiuArticle, Path]:
    root = Path(folder)
    content = root / "article.html"
    if not content.exists():
        content.write_text("<p>正文</p>", encoding="utf-8")
    app = XueqiuArticle(
        "雪球标题", content, account_file, declaration="不添加创作声明",
        prepare_only=prepare_only, headless=False,
    )
    app.document = SimpleNamespace(
        manifest={"structure_sha256": "x"}, source_format="html", normalizations=[],
    )
    app.uploaded_images = []
    app.cover_url = None
    app.identity = None
    return app, content


# ---------------------------------------------------------------------------
# is_logged_in
# ---------------------------------------------------------------------------


class ZhihuIsLoggedInTests(unittest.IsolatedAsyncioTestCase):
    async def test_logged_in_uses_profile_header_as_positive_signal(self):
        page = _RecordingPage(final_url=ZHIHU_CREATOR_URL)
        context = _SeamContext(page)
        reader = AsyncMock(return_value={"name": "n", "avatar_path": "/a"})
        with patch.object(zhihu_session, "read_zhihu_identity", reader):
            valid = await zhihu_session.is_logged_in(context)

        self.assertTrue(valid)
        reader.assert_awaited_once_with(page, timeout=zhihu_session.ZHIHU_IDENTITY_PROBE_TIMEOUT_MS)
        self.assertEqual(page.goto_calls[0][0], ZHIHU_CREATOR_URL)
        self.assertEqual(
            page.goto_calls[0][1]["timeout"],
            zhihu_session.ZHIHU_LOGIN_CHECK_TIMEOUT_MS,
        )
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, 0)
        self.assertTrue(page.closed)

    async def test_explicit_signin_page_returns_false_without_identity_read(self):
        page = _RecordingPage(final_url="https://www.zhihu.com/signin?next=%2Fcreator")
        context = _SeamContext(page)
        reader = AsyncMock()
        with patch.object(zhihu_session, "read_zhihu_identity", reader):
            valid = await zhihu_session.is_logged_in(context)

        self.assertFalse(valid)
        reader.assert_not_awaited()
        self.assertTrue(page.closed)

    async def test_5xx_raises(self):
        page = _RecordingPage(final_url=ZHIHU_CREATOR_URL, status=503)
        with self.assertRaises(RuntimeError):
            await zhihu_session.is_logged_in(_SeamContext(page))
        self.assertTrue(page.closed)

    async def test_network_error_raises(self):
        page = _RecordingPage(goto_error=RuntimeError("connection reset"))
        with self.assertRaises(RuntimeError):
            await zhihu_session.is_logged_in(_SeamContext(page))
        self.assertTrue(page.closed)

    async def test_unexpected_structure_raises(self):
        page = _RecordingPage(final_url=ZHIHU_CREATOR_URL)
        reader = AsyncMock(side_effect=RuntimeError("profile header missing"))
        with patch.object(zhihu_session, "read_zhihu_identity", reader):
            with self.assertRaises(RuntimeError):
                await zhihu_session.is_logged_in(_SeamContext(page))
        self.assertTrue(page.closed)

    async def test_unexpected_domain_raises(self):
        page = _RecordingPage(final_url="https://example.com/creator")
        with self.assertRaises(RuntimeError):
            await zhihu_session.is_logged_in(_SeamContext(page))


class XueqiuIsLoggedInTests(unittest.IsolatedAsyncioTestCase):
    async def test_logged_in_uses_profile_header_as_positive_signal(self):
        page = _RecordingPage(final_url=XUEQIU_HOME_URL)
        context = _SeamContext(page)
        reader = AsyncMock(return_value={"uid": "123", "name": "n"})
        with patch.object(xueqiu_session, "read_xueqiu_identity", reader):
            valid = await xueqiu_session.is_logged_in(context)

        self.assertTrue(valid)
        reader.assert_awaited_once_with(page, timeout=xueqiu_session.XUEQIU_IDENTITY_PROBE_TIMEOUT_MS)
        self.assertEqual(page.goto_calls[0][0], XUEQIU_HOME_URL)
        self.assertEqual(
            page.goto_calls[0][1]["timeout"],
            xueqiu_session.XUEQIU_LOGIN_CHECK_TIMEOUT_MS,
        )
        self.assertTrue(page.closed)

    async def test_explicit_login_page_returns_false_without_identity_read(self):
        page = _RecordingPage(final_url="https://xueqiu.com/account/login")
        reader = AsyncMock()
        with patch.object(xueqiu_session, "read_xueqiu_identity", reader):
            valid = await xueqiu_session.is_logged_in(_SeamContext(page))

        self.assertFalse(valid)
        reader.assert_not_awaited()
        self.assertTrue(page.closed)

    async def test_5xx_raises(self):
        page = _RecordingPage(final_url=XUEQIU_HOME_URL, status=500)
        with self.assertRaises(RuntimeError):
            await xueqiu_session.is_logged_in(_SeamContext(page))

    async def test_unexpected_structure_raises(self):
        page = _RecordingPage(final_url=XUEQIU_HOME_URL)
        reader = AsyncMock(side_effect=RuntimeError("header missing"))
        with patch.object(xueqiu_session, "read_xueqiu_identity", reader):
            with self.assertRaises(RuntimeError):
                await xueqiu_session.is_logged_in(_SeamContext(page))


# ---------------------------------------------------------------------------
# Uploader seam: local golden vs Multilogin
# ---------------------------------------------------------------------------


class ZhihuLocalGoldenTests(unittest.TestCase):
    def _assert_common(self, playwright, account_file):
        self.assertEqual(
            playwright.chromium.launch_calls,
            [{"headless": False, **ZHIHU_LAUNCH_KWARGS}],
        )
        browser = playwright.chromium.launch_browser
        self.assertEqual(
            browser.new_context_calls,
            [{"storage_state": str(account_file.resolve()), **ZHIHU_CONTEXT_KWARGS}],
        )
        self.assertTrue(browser.closed)

    def test_article_local_launch_context_and_timezone_are_golden(self):
        with tempfile.TemporaryDirectory() as folder:
            account_file = Path(folder) / "account.json"
            app, _ = _make_zhihu_article(folder, account_file=account_file)
            app.validate_upload_args = MagicMock()
            upload_in = AsyncMock(return_value={"success": True})
            app.upload_in = upload_in

            playwright = FakePlaywright()
            with patch.object(
                zhihu_article, "async_playwright", MagicMock(return_value=_AsyncCM(playwright))
            ):
                result = asyncio.run(app.main())

        self.assertEqual(result, {"success": True})
        self._assert_common(playwright, account_file)
        session = upload_in.await_args.args[0]
        self.assertEqual(session.mode, "local")
        self.assertEqual(ZHIHU_CONTEXT_KWARGS, {"timezone_id": "Asia/Shanghai"})
        self.assertEqual(ZHIHU_LAUNCH_KWARGS["channel"], "chrome")

    def test_video_local_launch_context_and_timezone_are_golden(self):
        with tempfile.TemporaryDirectory() as folder:
            account_file = Path(folder) / "account.json"
            app, _ = _make_zhihu_video(folder, account_file=account_file)
            app.validate_upload_args = MagicMock()
            upload_in = AsyncMock(return_value={"success": True})
            app.upload_in = upload_in

            playwright = FakePlaywright()
            with patch.object(
                zhihu_video, "async_playwright", MagicMock(return_value=_AsyncCM(playwright))
            ):
                result = asyncio.run(app.main())

        self.assertEqual(result, {"success": True})
        self._assert_common(playwright, account_file)
        self.assertEqual(upload_in.await_args.args[0].mode, "local")

    def test_xueqiu_local_launch_context_are_golden(self):
        with tempfile.TemporaryDirectory() as folder:
            account_file = Path(folder) / "account.json"
            app, _ = _make_xueqiu_article(folder, account_file=account_file)
            app.validate_upload_args = MagicMock()
            upload_in = AsyncMock(return_value={"success": True})
            app.upload_in = upload_in

            playwright = FakePlaywright()
            with patch.object(
                xueqiu_article, "async_playwright", MagicMock(return_value=_AsyncCM(playwright))
            ):
                result = asyncio.run(app.main())

        self.assertEqual(result, {"success": True})
        self.assertEqual(
            playwright.chromium.launch_calls,
            [{"headless": False, **XUEQIU_LAUNCH_KWARGS}],
        )
        browser = playwright.chromium.launch_browser
        self.assertEqual(
            browser.new_context_calls,
            [{"storage_state": str(account_file.resolve()), **XUEQIU_CONTEXT_KWARGS}],
        )
        self.assertTrue(browser.closed)
        self.assertEqual(XUEQIU_CONTEXT_KWARGS, {})
        self.assertEqual(XUEQIU_LAUNCH_KWARGS["channel"], "chrome")


class MultiloginUploaderSeamTests(unittest.TestCase):
    def test_article_main_with_session_skips_playwright_and_local_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            app, _ = _make_zhihu_article(folder, account_file=None)
            validate = MagicMock()
            upload_in = AsyncMock(return_value={"success": True})
            app.validate_upload_args = validate
            app.upload_in = upload_in
            session, _ = _mlx_session(_RecordingPage(final_url=ZHIHU_ARTICLE_URL))

            with patch.object(zhihu_article, "async_playwright", MagicMock()) as playwright:
                result = asyncio.run(app.main(session=session))

        self.assertEqual(result, {"success": True})
        playwright.assert_not_called()
        validate.assert_called_once_with(check_cookie=False)
        upload_in.assert_awaited_once_with(session)

    def test_video_main_with_session_skips_playwright_and_local_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            app, _ = _make_zhihu_video(folder, account_file=None)
            validate = MagicMock()
            upload_in = AsyncMock(return_value={"success": True})
            app.validate_upload_args = validate
            app.upload_in = upload_in
            session, _ = _mlx_session(_RecordingPage(final_url=ZHIHU_VIDEO_URL))

            with patch.object(zhihu_video, "async_playwright", MagicMock()) as playwright:
                result = asyncio.run(app.main(session=session))

        self.assertEqual(result, {"success": True})
        playwright.assert_not_called()
        validate.assert_called_once_with(check_cookie=False)
        upload_in.assert_awaited_once_with(session)

    def test_xueqiu_main_with_session_skips_playwright_and_local_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            app, _ = _make_xueqiu_article(folder, account_file=None)
            validate = MagicMock()
            upload_in = AsyncMock(return_value={"success": True})
            app.validate_upload_args = validate
            app.upload_in = upload_in
            session, _ = _mlx_session(_RecordingPage(final_url="https://mp.xueqiu.com/writeV2/"))

            with patch.object(xueqiu_article, "async_playwright", MagicMock()) as playwright:
                result = asyncio.run(app.main(session=session))

        self.assertEqual(result, {"success": True})
        playwright.assert_not_called()
        validate.assert_called_once_with(check_cookie=False)
        upload_in.assert_awaited_once_with(session)

    def test_article_mlx_body_never_touches_cookies_identity_or_forbidden_apis(self):
        with tempfile.TemporaryDirectory() as folder:
            app, _ = _make_zhihu_article(folder, account_file=None, prepare_only=True)
            app.fill_article_form = AsyncMock()
            page = _RecordingPage(final_url=ZHIHU_ARTICLE_URL)
            session, context = _mlx_session(page)

            with (
                patch.object(
                    zhihu_article, "read_zhihu_identity", AsyncMock(side_effect=AssertionError("identity read"))
                ) as reader,
                patch.object(
                    zhihu_article, "load_zhihu_identity", MagicMock(side_effect=AssertionError("identity binding"))
                ) as binding,
            ):
                result = asyncio.run(app.upload_in(session))

        self.assertEqual(result["status"], "prepared")
        reader.assert_not_awaited()
        binding.assert_not_called()
        app.fill_article_form.assert_awaited_once_with(page, multilogin=True)
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, 0)
        self.assertEqual(context.forbidden_calls, [])
        self.assertIsNone(app.account_file)

    def test_xueqiu_mlx_body_never_touches_cookies_identity_or_forbidden_apis(self):
        with tempfile.TemporaryDirectory() as folder:
            app, _ = _make_xueqiu_article(folder, account_file=None, prepare_only=True)
            app.fill_article_form = AsyncMock()
            page = _RecordingPage(final_url="https://mp.xueqiu.com/writeV2/")
            session, context = _mlx_session(page)

            with (
                patch.object(
                    xueqiu_article, "read_xueqiu_identity", AsyncMock(side_effect=AssertionError("identity read"))
                ) as reader,
                patch.object(
                    xueqiu_article, "load_xueqiu_identity", MagicMock(side_effect=AssertionError("identity binding"))
                ) as binding,
            ):
                result = asyncio.run(app.upload_in(session))

        self.assertTrue(result["success"])
        reader.assert_not_awaited()
        binding.assert_not_called()
        app.fill_article_form.assert_awaited_once_with(page, multilogin=True)
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, 0)
        self.assertEqual(context.forbidden_calls, [])
        self.assertIsNone(app.account_file)

    def test_mlx_validation_does_not_read_cookie_or_identity_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            article, _ = _make_zhihu_article(folder, account_file=None)
            xueqiu, _ = _make_xueqiu_article(folder, account_file=None)
            with (
                patch.object(zhihu_article, "load_zhihu_identity", MagicMock(side_effect=AssertionError)),
                patch.object(xueqiu_article, "load_xueqiu_identity", MagicMock(side_effect=AssertionError)),
            ):
                article.validate_upload_args(check_cookie=False)
                xueqiu.validate_upload_args(check_cookie=False)

        self.assertIsNone(article.identity)
        self.assertIsNone(xueqiu.identity)

    def test_mid_upload_login_redirect_maps_to_login_required(self):
        cases = [
            (zhihu_article, _make_zhihu_article, ZHIHU_ARTICLE_URL,
             "https://www.zhihu.com/signin?next=%2Fwrite"),
            (zhihu_video, _make_zhihu_video, ZHIHU_VIDEO_URL,
             "https://www.zhihu.com/signin?next=%2Fupload-video"),
            (xueqiu_article, _make_xueqiu_article, "https://mp.xueqiu.com/writeV2/",
             "https://xueqiu.com/account/login"),
        ]
        for module, factory, start_url, login_url in cases:
            with self.subTest(module=module.__name__):
                with tempfile.TemporaryDirectory() as folder:
                    app, _ = factory(folder, account_file=None, prepare_only=True)
                    page = _RecordingPage(final_url=login_url)
                    session, context = _mlx_session(page)
                    with (
                        patch.object(module, "read_zhihu_identity", AsyncMock(), create=True),
                        patch.object(module, "read_xueqiu_identity", AsyncMock(), create=True),
                    ):
                        with self.assertRaises(LoginRequiredError):
                            asyncio.run(app.upload_in(session))
                self.assertEqual(page.goto_calls[0][0], start_url)
                self.assertEqual(context.storage_state_calls, [])
                self.assertEqual(context.forbidden_calls, [])
                self.assertTrue(page.closed is False)

    def test_clipboard_permission_is_skipped_only_in_multilogin_mode(self):
        page = _RecordingPage(final_url=ZHIHU_ARTICLE_URL)
        session, context = _mlx_session(page)
        asyncio.run(zhihu_article.grant_clipboard_permission(page, multilogin=True))
        self.assertEqual(context.forbidden_calls, [])

        page2 = _RecordingPage(final_url=ZHIHU_ARTICLE_URL)
        page2.context = SimpleNamespace(grant_permissions=AsyncMock())
        asyncio.run(zhihu_article.grant_clipboard_permission(page2, multilogin=False))
        page2.context.grant_permissions.assert_awaited_once_with(
            ["clipboard-read", "clipboard-write"], origin="https://zhuanlan.zhihu.com"
        )

        page3 = _RecordingPage(final_url=XUEQIU_HOME_URL)
        page3.context = SimpleNamespace(grant_permissions=AsyncMock())
        asyncio.run(xueqiu_article.grant_clipboard_permission(page3, multilogin=False))
        page3.context.grant_permissions.assert_awaited_once_with(
            ["clipboard-read", "clipboard-write"], origin="https://mp.xueqiu.com"
        )


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


class _CliMixin:
    def _run(self, argv, token=TOKEN):
        with patch.dict(os.environ, {"MLX_API_TOKEN": token}):
            with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
                code = sau_cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def _patch_session(self, session):
        session_cm = _AsyncCM(session)
        factory = MagicMock(return_value=session_cm)
        return factory, session_cm

    def _base_patches(self, module, factory, session):
        return (
            patch.object(module, "async_playwright", lambda: _AsyncCM(object())),
            patch.object(module, "browser_session", new=factory),
        )


class ZhihuMlxCliCheckTests(_CliMixin, unittest.TestCase):
    def test_check_true_returns_0_and_logs_identity_not_verified(self):
        session = Namespace(context=object())
        factory, session_cm = self._patch_session(session)
        probe = AsyncMock(return_value=True)
        resolve_account = MagicMock(side_effect=AssertionError("cookie path used"))
        logger = MagicMock()
        with (
            patch.object(zhihu_command, "async_playwright", lambda: _AsyncCM(object())),
            patch.object(zhihu_command, "browser_session", new=factory),
            patch.object(zhihu_command, "is_logged_in", new=probe),
            patch.object(zhihu_command, "resolve_account_file", new=resolve_account),
            patch.object(zhihu_command, "logger", new=logger),
        ):
            code, out, _ = self._run(
                ["zhihu", "check", "--folder-id", "folder", "--profile-id", "profile"]
            )

        self.assertEqual(code, 0)
        self.assertIn("valid", out)
        factory.assert_called_once()
        self.assertIsNone(factory.call_args.kwargs["account_file"])
        self.assertEqual(factory.call_args.kwargs["managed"].target.profile_id, "profile")
        probe.assert_awaited_once_with(session.context)
        resolve_account.assert_not_called()
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)
        logger.info.assert_called_once()
        self.assertIn("profile", str(logger.info.call_args.args))

    def test_check_false_returns_10(self):
        session = Namespace(context=object())
        factory, session_cm = self._patch_session(session)
        with (
            patch.object(zhihu_command, "async_playwright", lambda: _AsyncCM(object())),
            patch.object(zhihu_command, "browser_session", new=factory),
            patch.object(zhihu_command, "is_logged_in", new=AsyncMock(return_value=False)),
        ):
            code, out, err = self._run(
                ["zhihu", "check", "--folder-id", "folder", "--profile-id", "profile"]
            )

        self.assertEqual(code, 10)
        self.assertNotIn("valid", out)
        self.assertIn("登录态无效", err)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_check_error_returns_1(self):
        session = Namespace(context=object())
        factory, session_cm = self._patch_session(session)
        with (
            patch.object(zhihu_command, "async_playwright", lambda: _AsyncCM(object())),
            patch.object(zhihu_command, "browser_session", new=factory),
            patch.object(
                zhihu_command,
                "is_logged_in",
                new=AsyncMock(side_effect=RuntimeError("launcher down")),
            ),
        ):
            code, _, err = self._run(
                ["zhihu", "check", "--folder-id", "folder", "--profile-id", "profile"]
            )

        self.assertEqual(code, 1)
        self.assertIn("launcher down", err)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_check_missing_profile_returns_2_without_session(self):
        factory = MagicMock()
        with patch.object(zhihu_command, "browser_session", new=factory):
            code, _, err = self._run(["zhihu", "check", "--folder-id", "folder"])

        self.assertEqual(code, 2)
        self.assertIn("--profile-id", err)
        factory.assert_not_called()

    def test_local_check_stays_on_legacy_path(self):
        factory = MagicMock()
        account_file = Path("/tmp/zhihu_local.json")
        with (
            patch.object(zhihu_command, "browser_session", new=factory),
            patch.object(zhihu_command, "resolve_account_file", MagicMock(return_value=account_file)),
            patch.object(zhihu_command, "check_zhihu_account", new=AsyncMock(return_value=True)) as check,
        ):
            code, out, _ = self._run(
                ["zhihu", "check", "--account", "creator"], token=""
            )

        self.assertEqual(code, 0)
        self.assertIn("valid", out)
        factory.assert_not_called()
        check.assert_awaited_once_with(account_file, False)


class ZhihuMlxCliUploadTests(_CliMixin, unittest.TestCase):
    def _article_argv(self, content: Path) -> list[str]:
        return [
            "zhihu", "upload-article", "--folder-id", "folder", "--profile-id", "profile",
            "--title", "文章标题", "--content-file", str(content),
        ]

    def _video_argv(self, video: Path) -> list[str]:
        return [
            "zhihu", "upload-video", "--folder-id", "folder", "--profile-id", "profile",
            "--file", str(video), "--title", "视频标题示例", "--originality", "original",
        ]

    def test_upload_article_success_uses_none_account_and_one_session(self):
        with tempfile.TemporaryDirectory() as folder:
            content = Path(folder) / "article.html"
            content.write_text("<p>正文</p>", encoding="utf-8")
            session = Namespace(context=object())
            factory, session_cm = self._patch_session(session)
            app = MagicMock()
            app.main = AsyncMock(return_value={"success": True})
            builder = MagicMock(return_value=app)
            probe = AsyncMock(return_value=True)
            resolve_account = MagicMock(side_effect=AssertionError("cookie path used"))

            with (
                patch.object(zhihu_command, "async_playwright", lambda: _AsyncCM(object())),
                patch.object(zhihu_command, "browser_session", new=factory),
                patch.object(zhihu_command, "is_logged_in", new=probe),
                patch.object(zhihu_command, "ZhihuArticle", new=builder),
                patch.object(zhihu_command, "resolve_account_file", new=resolve_account),
            ):
                code, out, _ = self._run(self._article_argv(content))

        self.assertEqual(code, 0)
        self.assertIn('"success": true', out)
        self.assertIsNone(builder.call_args.kwargs["account_file"])
        self.assertEqual(factory.call_args.kwargs["launch_kwargs"], ZHIHU_LAUNCH_KWARGS)
        self.assertEqual(factory.call_args.kwargs["context_kwargs"], ZHIHU_CONTEXT_KWARGS)
        self.assertIsNone(factory.call_args.kwargs["account_file"])
        probe.assert_awaited_once_with(session.context)
        app.main.assert_awaited_once_with(session=session)
        self.assertEqual(session_cm.exit_calls, 1)
        resolve_account.assert_not_called()

    def test_upload_article_logged_out_returns_10_and_skips_upload(self):
        with tempfile.TemporaryDirectory() as folder:
            content = Path(folder) / "article.html"
            content.write_text("<p>正文</p>", encoding="utf-8")
            session = Namespace(context=object())
            factory, session_cm = self._patch_session(session)
            app = MagicMock()
            app.main = AsyncMock()
            with (
                patch.object(zhihu_command, "async_playwright", lambda: _AsyncCM(object())),
                patch.object(zhihu_command, "browser_session", new=factory),
                patch.object(zhihu_command, "is_logged_in", new=AsyncMock(return_value=False)),
                patch.object(zhihu_command, "ZhihuArticle", new=MagicMock(return_value=app)),
            ):
                code, _, err = self._run(self._article_argv(content))

        self.assertEqual(code, 10)
        self.assertIn("登录态无效", err)
        app.main.assert_not_awaited()
        self.assertEqual(session_cm.exit_calls, 1)

    def test_upload_article_failure_returns_1_and_still_exits_session_once(self):
        with tempfile.TemporaryDirectory() as folder:
            content = Path(folder) / "article.html"
            content.write_text("<p>正文</p>", encoding="utf-8")
            session = Namespace(context=object())
            factory, session_cm = self._patch_session(session)
            app = MagicMock()
            app.main = AsyncMock(side_effect=RuntimeError("publish failed"))
            with (
                patch.object(zhihu_command, "async_playwright", lambda: _AsyncCM(object())),
                patch.object(zhihu_command, "browser_session", new=factory),
                patch.object(zhihu_command, "is_logged_in", new=AsyncMock(return_value=True)),
                patch.object(zhihu_command, "ZhihuArticle", new=MagicMock(return_value=app)),
            ):
                code, _, err = self._run(self._article_argv(content))

        self.assertEqual(code, 1)
        self.assertIn("publish failed", err)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_upload_video_success_uses_none_account_and_session(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / "video.mp4"
            video.write_bytes(b"video")
            session = Namespace(context=object())
            factory, session_cm = self._patch_session(session)
            app = MagicMock()
            app.main = AsyncMock(return_value={"success": True})
            builder = MagicMock(return_value=app)
            probe = AsyncMock(return_value=True)
            with (
                patch.object(zhihu_command, "async_playwright", lambda: _AsyncCM(object())),
                patch.object(zhihu_command, "browser_session", new=factory),
                patch.object(zhihu_command, "is_logged_in", new=probe),
                patch.object(zhihu_command, "ZhihuVideo", new=builder),
            ):
                code, out, _ = self._run(self._video_argv(video))

        self.assertEqual(code, 0)
        self.assertIn('"success": true', out)
        self.assertIsNone(builder.call_args.kwargs["account_file"])
        probe.assert_awaited_once_with(session.context)
        app.main.assert_awaited_once_with(session=session)
        self.assertEqual(session_cm.exit_calls, 1)


class XueqiuMlxCliTests(_CliMixin, unittest.TestCase):
    def _article_argv(self, content: Path) -> list[str]:
        return [
            "xueqiu", "upload-article", "--folder-id", "folder", "--profile-id", "profile",
            "--title", "雪球标题", "--content-file", str(content),
            "--declaration", "不添加创作声明",
        ]

    def test_check_true_returns_0_and_logs_identity_not_verified(self):
        session = Namespace(context=object())
        factory, session_cm = self._patch_session(session)
        logger = MagicMock()
        probe = AsyncMock(return_value=True)
        with (
            patch.object(xueqiu_command, "async_playwright", lambda: _AsyncCM(object())),
            patch.object(xueqiu_command, "browser_session", new=factory),
            patch.object(xueqiu_command, "is_logged_in", new=probe),
            patch.object(xueqiu_command, "logger", new=logger),
        ):
            code, out, _ = self._run(
                ["xueqiu", "check", "--folder-id", "folder", "--profile-id", "profile"]
            )

        self.assertEqual(code, 0)
        self.assertIn("valid", out)
        probe.assert_awaited_once_with(session.context)
        self.assertEqual(session_cm.exit_calls, 1)
        logger.info.assert_called_once()

    def test_check_false_returns_10(self):
        session = Namespace(context=object())
        factory, session_cm = self._patch_session(session)
        with (
            patch.object(xueqiu_command, "async_playwright", lambda: _AsyncCM(object())),
            patch.object(xueqiu_command, "browser_session", new=factory),
            patch.object(xueqiu_command, "is_logged_in", new=AsyncMock(return_value=False)),
        ):
            code, _, err = self._run(
                ["xueqiu", "check", "--folder-id", "folder", "--profile-id", "profile"]
            )

        self.assertEqual(code, 10)
        self.assertIn("登录态无效", err)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_check_error_returns_1(self):
        session = Namespace(context=object())
        factory, session_cm = self._patch_session(session)
        with (
            patch.object(xueqiu_command, "async_playwright", lambda: _AsyncCM(object())),
            patch.object(xueqiu_command, "browser_session", new=factory),
            patch.object(
                xueqiu_command, "is_logged_in",
                new=AsyncMock(side_effect=RuntimeError("launcher down")),
            ),
        ):
            code, _, err = self._run(
                ["xueqiu", "check", "--folder-id", "folder", "--profile-id", "profile"]
            )

        self.assertEqual(code, 1)
        self.assertIn("launcher down", err)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_upload_article_success_uses_none_account_and_one_session(self):
        with tempfile.TemporaryDirectory() as folder:
            content = Path(folder) / "article.html"
            content.write_text("<p>正文</p>", encoding="utf-8")
            session = Namespace(context=object())
            factory, session_cm = self._patch_session(session)
            app = MagicMock()
            app.main = AsyncMock(return_value={"success": True})
            builder = MagicMock(return_value=app)
            probe = AsyncMock(return_value=True)
            resolve_account = MagicMock(side_effect=AssertionError("cookie path used"))
            with (
                patch.object(xueqiu_command, "async_playwright", lambda: _AsyncCM(object())),
                patch.object(xueqiu_command, "browser_session", new=factory),
                patch.object(xueqiu_command, "is_logged_in", new=probe),
                patch.object(xueqiu_command, "XueqiuArticle", new=builder),
                patch.object(xueqiu_command, "resolve_account_file", new=resolve_account),
            ):
                code, out, _ = self._run(self._article_argv(content))

        self.assertEqual(code, 0)
        self.assertIn('"success": true', out)
        self.assertIsNone(builder.call_args.kwargs["account_file"])
        self.assertEqual(factory.call_args.kwargs["launch_kwargs"], XUEQIU_LAUNCH_KWARGS)
        self.assertEqual(factory.call_args.kwargs["context_kwargs"], XUEQIU_CONTEXT_KWARGS)
        probe.assert_awaited_once_with(session.context)
        app.main.assert_awaited_once_with(session=session)
        self.assertEqual(session_cm.exit_calls, 1)
        resolve_account.assert_not_called()

    def test_upload_article_logged_out_returns_10(self):
        with tempfile.TemporaryDirectory() as folder:
            content = Path(folder) / "article.html"
            content.write_text("<p>正文</p>", encoding="utf-8")
            session = Namespace(context=object())
            factory, session_cm = self._patch_session(session)
            app = MagicMock()
            app.main = AsyncMock()
            with (
                patch.object(xueqiu_command, "async_playwright", lambda: _AsyncCM(object())),
                patch.object(xueqiu_command, "browser_session", new=factory),
                patch.object(xueqiu_command, "is_logged_in", new=AsyncMock(return_value=False)),
                patch.object(xueqiu_command, "XueqiuArticle", new=MagicMock(return_value=app)),
            ):
                code, _, err = self._run(self._article_argv(content))

        self.assertEqual(code, 10)
        self.assertIn("登录态无效", err)
        app.main.assert_not_awaited()
        self.assertEqual(session_cm.exit_calls, 1)

    def test_upload_article_failure_returns_1(self):
        with tempfile.TemporaryDirectory() as folder:
            content = Path(folder) / "article.html"
            content.write_text("<p>正文</p>", encoding="utf-8")
            session = Namespace(context=object())
            factory, session_cm = self._patch_session(session)
            app = MagicMock()
            app.main = AsyncMock(side_effect=RuntimeError("publish failed"))
            with (
                patch.object(xueqiu_command, "async_playwright", lambda: _AsyncCM(object())),
                patch.object(xueqiu_command, "browser_session", new=factory),
                patch.object(xueqiu_command, "is_logged_in", new=AsyncMock(return_value=True)),
                patch.object(xueqiu_command, "XueqiuArticle", new=MagicMock(return_value=app)),
            ):
                code, _, err = self._run(self._article_argv(content))

        self.assertEqual(code, 1)
        self.assertIn("publish failed", err)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_local_upload_article_stays_on_legacy_path(self):
        with tempfile.TemporaryDirectory() as folder:
            content = Path(folder) / "article.html"
            content.write_text("<p>正文</p>", encoding="utf-8")
            factory = MagicMock()
            app = MagicMock()
            app.main = AsyncMock(return_value={"success": True})
            builder = MagicMock(return_value=app)
            with (
                patch.object(xueqiu_command, "browser_session", new=factory),
                patch.object(xueqiu_command, "XueqiuArticle", new=builder),
                patch.object(
                    xueqiu_command, "resolve_account_file",
                    MagicMock(return_value=Path("/tmp/xueqiu_creator.json")),
                ),
            ):
                code, out, _ = self._run(
                    ["xueqiu", "upload-article", "--account", "creator",
                     "--title", "雪球标题", "--content-file", str(content),
                     "--declaration", "不添加创作声明"],
                    token="",
                )

        self.assertEqual(code, 0)
        self.assertIn('"success": true', out)
        factory.assert_not_called()
        app.main.assert_awaited_once_with()
        self.assertEqual(
            builder.call_args.kwargs["account_file"], Path("/tmp/xueqiu_creator.json")
        )


if __name__ == "__main__":
    unittest.main()
