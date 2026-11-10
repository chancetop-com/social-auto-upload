# -*- coding: utf-8 -*-
"""Xiaohongshu + Kuaishou Multilogin seams (ticket 18).

Covers, for both platforms:

* golden local ``launch`` / ``new_context`` options and init-script flag;
* the Multilogin uploader seam (``session=`` never launches or closes anything);
* the no-cookie-read/write rule and the spec §6.2 forbidden API list;
* ``is_logged_in`` True / False / raise, table driven;
* CLI exit codes 0 / 10 / 1 / 2 and exactly-once session enter/exit.
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
from unittest.mock import AsyncMock, MagicMock, patch

import sau_cli
from conf import LOCAL_CHROME_PATH
from sau_commands import kuaishou as ks_command
from sau_commands import xiaohongshu as xhs_command
from tests.fakes import FakeContext, FakePlaywright
from uploader.ks_uploader import main as ks_main
from uploader.ks_uploader.main import (
    KUAISHOU_CONTEXT_KWARGS,
    KUAISHOU_INIT_SCRIPT,
    KUAISHOU_LAUNCH_KWARGS,
    KUAISHOU_LOGIN_CHECK_URL,
    KUAISHOU_UPLOAD_URL,
    KSNote,
    KSVideo,
    _build_ks_launch_kwargs,
)
from uploader.xiaohongshu_uploader import main as xhs_main
from uploader.xiaohongshu_uploader.main import (
    XHS_CONTEXT_KWARGS,
    XHS_LAUNCH_KWARGS,
    XHS_LOGIN_CHECK_URL,
    XiaoHongShuNote,
    XiaoHongShuVideo,
)
from utils.browser_session import BrowserSession
from utils.errors import LoginRequiredError

TOKEN = "SENTINEL-MLX-TOKEN-ticket18"
XHS_LOGIN_REDIRECT = "https://creator.xiaohongshu.com/login?redirect=%2Fpublish"
KS_LOGIN_REDIRECT = "https://passport.kuaishou.com/pc/account/login/?sid=kuaishou"
XHS_VIDEO_URL = XHS_LOGIN_CHECK_URL
XHS_NOTE_URL = "https://creator.xiaohongshu.com/publish/publish?from=homepage&target=image"


# --------------------------------------------------------------------------- #
# uploader doubles
# --------------------------------------------------------------------------- #
class _Response:
    def __init__(self, status: int = 200) -> None:
        self.status = status


class _Locator:
    def __init__(
        self,
        count: int = 0,
        visible: bool = False,
        wait_error: BaseException | None = None,
    ) -> None:
        self._count = count
        self._visible = visible
        self._wait_error = wait_error

    @property
    def first(self) -> "_Locator":
        return self

    async def count(self) -> int:
        return self._count

    async def is_visible(self) -> bool:
        return self._visible

    async def wait_for(self, state: str | None = None, timeout: int | None = None) -> None:
        if self._wait_error is not None:
            raise self._wait_error


class _UploadPage:
    """Small page double for both uploader bodies and login probes."""

    def __init__(
        self,
        *,
        final_url: str,
        status: int = 200,
        goto_error: BaseException | None = None,
        xhs_login_visible: bool = False,
        xhs_upload_anchor: bool = False,
        ks_login_anchor: bool = False,
        ks_upload_button: bool = False,
        ks_upload_wait_error: BaseException | None = None,
        ks_cookie_invalid: bool = False,
        wait_for_url_error: BaseException | None = None,
    ) -> None:
        self.url = "about:blank"
        self.final_url = final_url
        self.status = status
        self.goto_error = goto_error
        self.xhs_login_visible = xhs_login_visible
        self.xhs_upload_anchor = xhs_upload_anchor
        self.ks_login_anchor = ks_login_anchor
        self.ks_upload_button = ks_upload_button
        self.ks_upload_wait_error = ks_upload_wait_error
        self.ks_cookie_invalid = ks_cookie_invalid
        self.wait_for_url_error = wait_for_url_error
        self.closed = False
        self.close_calls = 0
        self.goto_calls: list[tuple[str, dict]] = []
        self.wait_for_url_calls: list[tuple[str, dict]] = []
        self.wait_timeouts: list[int] = []

    async def goto(self, url: str, **kwargs):
        self.goto_calls.append((url, kwargs))
        if self.goto_error is not None:
            raise self.goto_error
        self.url = self.final_url
        return _Response(self.status)

    async def wait_for_url(self, url: str, **kwargs) -> None:
        self.wait_for_url_calls.append((url, kwargs))
        if self.wait_for_url_error is not None:
            raise self.wait_for_url_error
        self.url = url

    async def wait_for_timeout(self, ms: int) -> None:
        self.wait_timeouts.append(ms)

    def locator(self, selector: str) -> _Locator:
        if selector in xhs_main.XHS_LOGIN_POSITIVE_SELECTORS:
            return _Locator(count=1 if self.xhs_upload_anchor else 0)
        if "login-box" in selector:
            return _Locator(count=1 if self.xhs_login_visible else 0, visible=self.xhs_login_visible)
        if "_upload-btn" in selector:
            return _Locator(
                count=1 if self.ks_upload_button else 0,
                visible=self.ks_upload_button,
                wait_error=self.ks_upload_wait_error,
            )
        if selector == "div.names div.container div.name:text('机构服务')":
            return _Locator(count=1 if self.ks_cookie_invalid else 0)
        return _Locator()

    def get_by_text(self, text: str, exact: bool = False) -> _Locator:
        if text == "立即登录":
            return _Locator(count=1 if self.ks_login_anchor else 0, visible=self.ks_login_anchor)
        return _Locator()

    async def wait_for_selector(self, selector: str, timeout: int | None = None) -> None:
        if self.ks_cookie_invalid:
            return
        raise RuntimeError(f"selector not found: {selector}")

    async def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class _UploadContext:
    def __init__(self, page: _UploadPage) -> None:
        self.page = page
        self.new_page_calls = 0
        self.storage_state_calls: list[object] = []
        self.add_init_script_calls = 0

    async def new_page(self) -> _UploadPage:
        self.new_page_calls += 1
        return self.page

    async def storage_state(self, *, path=None, **kwargs):
        self.storage_state_calls.append(path)
        return {"cookies": []}

    async def add_init_script(self, *args, **kwargs) -> None:
        self.add_init_script_calls += 1


class _ForbiddenRecordingContext(FakeContext):
    """``FakeContext`` with a page whose DOM the login probes can inspect."""

    def __init__(self, page: _UploadPage) -> None:
        super().__init__()
        self._page = page

    async def new_page(self) -> _UploadPage:
        self.new_page_calls += 1
        return self._page


def _make_xhs_video(tmp_dir: str, account_file=None, **kwargs) -> XiaoHongShuVideo:
    video_path = Path(tmp_dir) / "demo.mp4"
    if not video_path.exists():
        video_path.write_bytes(b"video")
    return XiaoHongShuVideo(
        title="标题",
        file_path=str(video_path),
        tags=[],
        publish_date=0,
        account_file=account_file,
        **kwargs,
    )


def _make_xhs_note(tmp_dir: str, account_file=None, **kwargs) -> XiaoHongShuNote:
    image_path = Path(tmp_dir) / "image.png"
    if not image_path.exists():
        image_path.write_bytes(b"image")
    return XiaoHongShuNote(
        image_paths=[str(image_path)],
        note="图文正文",
        tags=[],
        publish_date=0,
        account_file=account_file,
        title="图文标题",
        **kwargs,
    )


def _make_ks_video(tmp_dir: str, account_file=None, **kwargs) -> KSVideo:
    video_path = Path(tmp_dir) / "demo.mp4"
    if not video_path.exists():
        video_path.write_bytes(b"video")
    return KSVideo(
        title="标题",
        file_path=str(video_path),
        tags=[],
        publish_date=0,
        account_file=account_file,
        **kwargs,
    )


def _make_ks_note(tmp_dir: str, account_file=None, **kwargs) -> KSNote:
    image_path = Path(tmp_dir) / "image.png"
    if not image_path.exists():
        image_path.write_bytes(b"image")
    return KSNote(
        image_paths=[str(image_path)],
        note="图文正文",
        tags=[],
        publish_date=0,
        account_file=account_file,
        title="图文标题",
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# local mode golden options
# --------------------------------------------------------------------------- #
class LocalGoldenTests(unittest.TestCase):
    def test_xhs_video_launch_context_and_init_script_are_golden(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = _make_xhs_video(tmp_dir, "/tmp/xhs-cookie.json", headless=False)
            app.validate_upload_args = AsyncMock()
            app.upload_in = AsyncMock()

            playwright = FakePlaywright()
            init_script = AsyncMock(side_effect=lambda context: context)

            with patch.object(xhs_main, "set_init_script", init_script):
                asyncio.run(app.upload(playwright))

        self.assertEqual(
            playwright.chromium.launch_calls,
            [{"headless": False, "channel": "chromium"}],
        )
        browser = playwright.chromium.launch_browser
        # 第一个 context 是 UA 探测用的临时 context，第二个才是真正的上传 context。
        self.assertEqual(
            browser.new_context_calls,
            [
                {},
                {
                    "storage_state": "/tmp/xhs-cookie.json",
                    "user_agent": "Chrome/120.0",
                    "permissions": ["geolocation"],
                    "locale": "zh-CN",
                    "extra_http_headers": {
                        "Accept-Language": "zh-CN,zh;q=0.9"
                    },
                },
            ],
        )
        probe_context, context = browser.contexts
        self.assertTrue(probe_context.closed)
        init_script.assert_awaited_once_with(context)
        app.upload_in.assert_awaited_once()
        session = app.upload_in.await_args.args[0]
        self.assertEqual(session.mode, "local")
        self.assertIs(session.context, context)

    def test_xhs_note_launch_context_and_init_script_are_golden(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = _make_xhs_note(tmp_dir, "/tmp/xhs-note-cookie.json")
            app.validate_upload_args = AsyncMock()
            app.upload_in = AsyncMock()

            playwright = FakePlaywright()
            init_script = AsyncMock(side_effect=lambda context: context)

            with patch.object(xhs_main, "set_init_script", init_script):
                asyncio.run(app.upload(playwright))

        self.assertEqual(
            playwright.chromium.launch_calls,
            [{"headless": True, "channel": "chromium"}],
        )
        browser = playwright.chromium.launch_browser
        self.assertEqual(
            browser.new_context_calls,
            [
                {},
                {
                    "storage_state": "/tmp/xhs-note-cookie.json",
                    "user_agent": "Chrome/120.0",
                    "permissions": ["geolocation"],
                    "locale": "zh-CN",
                    "extra_http_headers": {
                        "Accept-Language": "zh-CN,zh;q=0.9"
                    },
                },
            ],
        )
        probe_context, context = browser.contexts
        self.assertTrue(probe_context.closed)
        init_script.assert_awaited_once_with(context)

    def test_xhs_local_teardown_saves_cookie_then_closes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = _make_xhs_video(tmp_dir, "/tmp/xhs-cookie.json")
            app.validate_upload_args = AsyncMock()
            app.upload_in = AsyncMock()

            playwright = FakePlaywright()
            with patch.object(
                xhs_main, "set_init_script", AsyncMock(side_effect=lambda c: c)
            ):
                asyncio.run(app.upload(playwright))

        browser = playwright.chromium.launch_browser
        probe_context, context = browser.contexts
        self.assertTrue(probe_context.closed)
        self.assertEqual(context.storage_state_calls, ["/tmp/xhs-cookie.json"])
        self.assertTrue(context.closed)
        self.assertTrue(browser.closed)

    def test_ks_launch_kwargs_are_golden_for_both_branches(self):
        expected = (
            {"executable_path": LOCAL_CHROME_PATH}
            if LOCAL_CHROME_PATH
            else {"channel": "chromium"}
        )
        self.assertEqual(KUAISHOU_LAUNCH_KWARGS, expected)
        self.assertEqual(KUAISHOU_CONTEXT_KWARGS, {})
        self.assertTrue(KUAISHOU_INIT_SCRIPT)
        self.assertEqual(
            _build_ks_launch_kwargs("/opt/google/chrome"),
            {"executable_path": "/opt/google/chrome"},
        )
        self.assertEqual(_build_ks_launch_kwargs(""), {"channel": "chromium"})

    def test_ks_video_launch_context_and_init_script_are_golden(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = _make_ks_video(tmp_dir, "/tmp/ks-cookie.json", headless=False)
            app.validate_upload_args = AsyncMock()
            app.upload_in = AsyncMock()

            playwright = FakePlaywright()
            init_script = AsyncMock(side_effect=lambda context: context)

            with patch.object(ks_main, "set_init_script", init_script):
                asyncio.run(app.upload(playwright))

        self.assertEqual(
            playwright.chromium.launch_calls,
            [{"headless": False, **KUAISHOU_LAUNCH_KWARGS}],
        )
        browser = playwright.chromium.launch_browser
        self.assertEqual(
            browser.new_context_calls,
            [{"storage_state": "/tmp/ks-cookie.json", **KUAISHOU_CONTEXT_KWARGS}],
        )
        init_script.assert_awaited_once_with(browser.contexts[0])
        app.upload_in.assert_awaited_once()
        self.assertEqual(app.upload_in.await_args.args[0].mode, "local")

    def test_ks_note_launch_context_and_teardown_are_golden(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = _make_ks_note(tmp_dir, "/tmp/ks-note-cookie.json")
            app.validate_upload_args = AsyncMock()
            app.upload_in = AsyncMock()

            playwright = FakePlaywright()
            with (
                patch.object(
                    ks_main, "set_init_script", AsyncMock(side_effect=lambda c: c)
                ),
                patch.object(ks_main.asyncio, "sleep", AsyncMock()),
            ):
                asyncio.run(app.upload(playwright))

        self.assertEqual(
            playwright.chromium.launch_calls,
            [{"headless": True, **KUAISHOU_LAUNCH_KWARGS}],
        )
        browser = playwright.chromium.launch_browser
        context = browser.contexts[0]
        self.assertEqual(
            browser.new_context_calls,
            [{"storage_state": "/tmp/ks-note-cookie.json", **KUAISHOU_CONTEXT_KWARGS}],
        )
        self.assertEqual(context.storage_state_calls, ["/tmp/ks-note-cookie.json"])
        self.assertTrue(context.closed)
        self.assertTrue(browser.closed)


# --------------------------------------------------------------------------- #
# Multilogin uploader seam
# --------------------------------------------------------------------------- #
class MultiloginSeamTests(unittest.TestCase):
    def test_xhs_video_consumes_injected_session_without_forbidden_api(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = _make_xhs_video(tmp_dir, account_file=None)
            content = AsyncMock()
            app.upload_video_content = content

            context = FakeContext()
            session = BrowserSession(browser=MagicMock(), context=context, mode="multilogin")

            with patch.object(xhs_main, "async_playwright", MagicMock()) as open_pw:
                asyncio.run(app.upload(None, session=session))

        open_pw.assert_not_called()
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, [])
        self.assertEqual(context.forbidden_calls, [])
        content.assert_awaited_once()
        self.assertEqual(content.await_args.kwargs, {"multilogin": True})
        self.assertIsNone(app.account_file)

    def test_xhs_note_consumes_injected_session_without_forbidden_api(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = _make_xhs_note(tmp_dir, account_file=None)
            content = AsyncMock()
            app.upload_note_content = content

            context = FakeContext()
            session = BrowserSession(browser=MagicMock(), context=context, mode="multilogin")

            asyncio.run(app.upload(None, session=session))

        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, [])
        self.assertEqual(context.forbidden_calls, [])
        content.assert_awaited_once()
        self.assertEqual(content.await_args.kwargs, {"multilogin": True})
        self.assertIsNone(app.account_file)

    def test_xhs_mlx_never_reads_cookies(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = _make_xhs_video(tmp_dir, account_file=None)
            app.upload_in = AsyncMock()
            cookie_auth = AsyncMock()

            with (
                patch.object(xhs_main, "cookie_auth", cookie_auth),
                patch.object(xhs_main.os.path, "exists", MagicMock()) as exists,
            ):
                asyncio.run(
                    app.upload(
                        None,
                        session=BrowserSession(
                            browser=MagicMock(), context=MagicMock(), mode="multilogin"
                        ),
                    )
                )

        cookie_auth.assert_not_awaited()
        exists.assert_not_called()
        self.assertIsNone(app.account_file)

    def test_ks_video_consumes_injected_session_without_forbidden_api(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = _make_ks_video(tmp_dir, account_file=None)
            page_ops = AsyncMock()
            app._upload_video_on_page = page_ops

            page = _UploadPage(final_url=KUAISHOU_UPLOAD_URL)
            context = _ForbiddenRecordingContext(page)
            session = BrowserSession(browser=MagicMock(), context=context, mode="multilogin")

            with patch.object(ks_main, "async_playwright", MagicMock()) as open_pw:
                asyncio.run(app.upload(None, session=session))

        open_pw.assert_not_called()
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, [])
        self.assertEqual(context.forbidden_calls, [])
        self.assertEqual(page.goto_calls[0][0], KUAISHOU_UPLOAD_URL)
        page_ops.assert_awaited_once_with(page, multilogin=True)
        self.assertIsNone(app.account_file)

    def test_ks_note_consumes_injected_session_without_forbidden_api(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = _make_ks_note(tmp_dir, account_file=None)
            content = AsyncMock()
            app.upload_note_content = content

            page = _UploadPage(final_url=KUAISHOU_UPLOAD_URL)
            context = _ForbiddenRecordingContext(page)
            session = BrowserSession(browser=MagicMock(), context=context, mode="multilogin")

            asyncio.run(app.upload(None, session=session))

        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, [])
        self.assertEqual(context.forbidden_calls, [])
        content.assert_awaited_once_with(page, multilogin=True)
        self.assertIsNone(app.account_file)

    def test_ks_mlx_never_reads_cookies(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = _make_ks_video(tmp_dir, account_file=None)
            app.upload_in = AsyncMock()
            cookie_auth = AsyncMock()

            with (
                patch.object(ks_main, "cookie_auth", cookie_auth),
                patch.object(ks_main.os.path, "exists", MagicMock()) as exists,
            ):
                asyncio.run(
                    app.upload(
                        None,
                        session=BrowserSession(
                            browser=MagicMock(), context=MagicMock(), mode="multilogin"
                        ),
                    )
                )

        cookie_auth.assert_not_awaited()
        exists.assert_not_called()
        self.assertIsNone(app.account_file)

    def test_wrapper_with_session_does_not_open_playwright(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            xhs_video = _make_xhs_video(tmp_dir, account_file=None)
            xhs_video.upload = AsyncMock()
            ks_video = _make_ks_video(tmp_dir, account_file=None)
            ks_video.upload = AsyncMock()
            session = BrowserSession(
                browser=MagicMock(), context=MagicMock(), mode="multilogin"
            )

            with patch.object(xhs_main, "async_playwright", MagicMock()) as xhs_pw:
                asyncio.run(xhs_video.xiaohongshu_upload_video(session=session))
            with patch.object(ks_main, "async_playwright", MagicMock()) as ks_pw:
                asyncio.run(ks_video.main(session=session))

        xhs_pw.assert_not_called()
        ks_pw.assert_not_called()
        xhs_video.upload.assert_awaited_once_with(None, session=session)
        ks_video.upload.assert_awaited_once_with(None, session=session)

    def test_xhs_video_login_redirect_raises_login_required(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = _make_xhs_video(tmp_dir, account_file=None)
            page = _UploadPage(final_url=XHS_LOGIN_REDIRECT)
            context = _UploadContext(page)
            session = BrowserSession(browser=MagicMock(), context=context, mode="multilogin")

            with self.assertRaises(LoginRequiredError):
                asyncio.run(app.upload(None, session=session))

        self.assertEqual(page.goto_calls[0][0], XHS_VIDEO_URL)
        self.assertEqual(context.storage_state_calls, [])

    def test_xhs_note_captcha_redirect_raises_login_required(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = _make_xhs_note(tmp_dir, account_file=None)
            page = _UploadPage(
                final_url="https://creator.xiaohongshu.com/captcha/verify?scene=publish"
            )
            context = _UploadContext(page)
            session = BrowserSession(browser=MagicMock(), context=context, mode="multilogin")

            with self.assertRaises(LoginRequiredError):
                asyncio.run(app.upload(None, session=session))

        self.assertEqual(page.goto_calls[0][0], XHS_NOTE_URL)
        self.assertEqual(context.storage_state_calls, [])

    def test_ks_video_login_redirect_raises_login_required(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = _make_ks_video(tmp_dir, account_file=None)
            page_ops = AsyncMock()
            app._upload_video_on_page = page_ops

            page = _UploadPage(final_url=KS_LOGIN_REDIRECT)
            context = _UploadContext(page)
            session = BrowserSession(browser=MagicMock(), context=context, mode="multilogin")

            with self.assertRaises(LoginRequiredError):
                asyncio.run(app.upload(None, session=session))

        self.assertEqual(page.goto_calls[0][0], KUAISHOU_UPLOAD_URL)
        page_ops.assert_not_awaited()
        self.assertEqual(context.storage_state_calls, [])

    def test_ks_note_login_redirect_raises_login_required(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = _make_ks_note(tmp_dir, account_file=None)
            content = AsyncMock()
            app.upload_note_content = content

            page = _UploadPage(final_url=KS_LOGIN_REDIRECT)
            context = _UploadContext(page)
            session = BrowserSession(browser=MagicMock(), context=context, mode="multilogin")

            with self.assertRaises(LoginRequiredError):
                asyncio.run(app.upload(None, session=session))

        content.assert_not_awaited()
        self.assertEqual(context.storage_state_calls, [])


# --------------------------------------------------------------------------- #
# is_logged_in
# --------------------------------------------------------------------------- #
    def test_login_markers_mid_upload_raise_login_required(self):
        cases = {
            "login": "https://creator.xiaohongshu.com/login?redirect=%2Fpublish",
            "captcha": "https://cp.kuaishou.com/captcha/verify?scene=publish",
            "two-factor": "https://cp.kuaishou.com/two-factor/challenge",
        }
        for module in (xhs_main, ks_main):
            for label, url in cases.items():
                with self.subTest(module=module.__name__, marker=label):
                    page = _UploadPage(final_url=url)
                    page.url = url
                    with self.assertRaises(LoginRequiredError):
                        module._raise_if_login_required(page)


class LoginProbeTests(unittest.TestCase):
    def _xhs_probe(self, page: _UploadPage) -> bool:
        context = _UploadContext(page)
        try:
            result = asyncio.run(xhs_main.is_logged_in(context))
        finally:
            self.assertEqual(context.new_page_calls, 1)
            self.assertEqual(page.close_calls, 1)
        return result

    def _ks_probe(self, page: _UploadPage) -> bool:
        context = _UploadContext(page)
        try:
            result = asyncio.run(ks_main.is_logged_in(context))
        finally:
            self.assertEqual(context.new_page_calls, 1)
            self.assertEqual(page.close_calls, 1)
        return result

    def test_xhs_logged_in_returns_true_with_positive_upload_anchor(self):
        page = _UploadPage(final_url=XHS_VIDEO_URL, xhs_upload_anchor=True)
        self.assertTrue(self._xhs_probe(page))
        self.assertEqual(page.goto_calls[0][0], XHS_LOGIN_CHECK_URL)
        timeout = page.goto_calls[0][1]["timeout"]
        self.assertGreaterEqual(timeout, 15_000)
        self.assertLessEqual(timeout, 30_000)

    def test_xhs_login_page_and_form_return_false(self):
        cases = {
            "login path": _UploadPage(final_url=XHS_LOGIN_REDIRECT),
            "visible login form": _UploadPage(
                final_url=XHS_VIDEO_URL, xhs_login_visible=True
            ),
        }
        for label, page in cases.items():
            with self.subTest(label):
                self.assertFalse(self._xhs_probe(page))

    def test_xhs_missing_positive_anchor_raises(self):
        page = _UploadPage(final_url=XHS_VIDEO_URL)
        context = _UploadContext(page)
        with self.assertRaisesRegex(RuntimeError, "页面结构异常"):
            asyncio.run(xhs_main.is_logged_in(context))
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(page.close_calls, 1)

    def test_xhs_network_error_server_error_and_unexpected_domain_raise(self):
        cases = {
            "network error": _UploadPage(
                final_url=XHS_VIDEO_URL, goto_error=RuntimeError("net::ERR_RESET")
            ),
            "server error": _UploadPage(final_url=XHS_VIDEO_URL, status=503),
            "unexpected domain": _UploadPage(final_url="https://example.com/elsewhere"),
        }
        for label, page in cases.items():
            with self.subTest(label):
                context = _UploadContext(page)
                with self.assertRaises(RuntimeError):
                    asyncio.run(xhs_main.is_logged_in(context))
                self.assertEqual(context.new_page_calls, 1)
                self.assertEqual(page.close_calls, 1)

    def test_ks_logged_in_returns_true(self):
        page = _UploadPage(final_url=KUAISHOU_UPLOAD_URL, ks_upload_button=True)
        self.assertTrue(self._ks_probe(page))
        self.assertEqual(page.goto_calls[0][0], KUAISHOU_LOGIN_CHECK_URL)

    def test_ks_login_page_anchor_and_invalid_page_return_false(self):
        cases = {
            "passport redirect": _UploadPage(final_url=KS_LOGIN_REDIRECT),
            "login anchor": _UploadPage(
                final_url=KUAISHOU_UPLOAD_URL, ks_login_anchor=True
            ),
            "institution page": _UploadPage(
                final_url=KUAISHOU_UPLOAD_URL,
                ks_cookie_invalid=True,
                ks_upload_wait_error=RuntimeError("no upload button"),
            ),
        }
        for label, page in cases.items():
            with self.subTest(label):
                self.assertFalse(self._ks_probe(page))

    def test_ks_network_error_server_error_and_unexpected_structure_raise(self):
        cases = {
            "network error": _UploadPage(
                final_url=KUAISHOU_UPLOAD_URL, goto_error=RuntimeError("net::ERR_RESET")
            ),
            "server error": _UploadPage(final_url=KUAISHOU_UPLOAD_URL, status=503),
            "unexpected domain": _UploadPage(final_url="https://example.com/elsewhere"),
            "no positive anchor": _UploadPage(
                final_url=KUAISHOU_UPLOAD_URL,
                ks_upload_wait_error=RuntimeError("button missing"),
            ),
        }
        for label, page in cases.items():
            with self.subTest(label):
                context = _UploadContext(page)
                with self.assertRaises(RuntimeError):
                    asyncio.run(ks_main.is_logged_in(context))
                self.assertEqual(context.new_page_calls, 1)
                self.assertEqual(page.close_calls, 1)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
class _AsyncCM:
    def __init__(self, value=None, enter_error: BaseException | None = None) -> None:
        self.value = value
        self.enter_error = enter_error
        self.enter_calls = 0
        self.exit_calls = 0
        self.last_exc: tuple | None = None

    async def __aenter__(self):
        self.enter_calls += 1
        if self.enter_error is not None:
            raise self.enter_error
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        self.exit_calls += 1
        self.last_exc = (exc_type, exc, tb)
        return False


class _CliCase(unittest.TestCase):
    def _run(self, argv, token=TOKEN):
        with patch.dict(os.environ, {"MLX_API_TOKEN": token}):
            with redirect_stdout(io.StringIO()) as out, redirect_stderr(
                io.StringIO()
            ) as err:
                code = sau_cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def _session_patch(self, module):
        session = Namespace(context=object())
        session_cm = _AsyncCM(session)
        factory = MagicMock(return_value=session_cm)
        return session, session_cm, factory, patch.object(module, "browser_session", new=factory)


class XhsCliTests(_CliCase):
    def test_check_logged_in_returns_0_and_enters_session_once(self):
        playwright_cm = _AsyncCM(object())
        session, session_cm, factory, session_patch = self._session_patch(xhs_command)
        probe = AsyncMock(return_value=True)

        with (
            patch.object(xhs_command, "async_playwright", lambda: playwright_cm),
            session_patch,
            patch.object(xhs_command, "is_logged_in", new=probe),
        ):
            code, out, _ = self._run(
                ["xiaohongshu", "check", "--folder-id", "folder", "--profile-id", "profile"]
            )

        self.assertEqual(code, 0)
        self.assertIn("valid", out)
        self.assertEqual(playwright_cm.enter_calls, 1)
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)
        probe.assert_awaited_once_with(session.context)

    def test_check_logged_out_returns_10(self):
        playwright_cm = _AsyncCM(object())
        _, session_cm, _, session_patch = self._session_patch(xhs_command)

        with (
            patch.object(xhs_command, "async_playwright", lambda: playwright_cm),
            session_patch,
            patch.object(
                xhs_command, "is_logged_in", new=AsyncMock(return_value=False)
            ),
        ):
            code, out, _ = self._run(
                ["xiaohongshu", "check", "--folder-id", "folder", "--profile-id", "profile"]
            )

        self.assertEqual(code, 10)
        self.assertNotIn("valid", out)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_check_probe_error_returns_1(self):
        playwright_cm = _AsyncCM(object())
        _, session_cm, _, session_patch = self._session_patch(xhs_command)

        with (
            patch.object(xhs_command, "async_playwright", lambda: playwright_cm),
            session_patch,
            patch.object(
                xhs_command,
                "is_logged_in",
                new=AsyncMock(side_effect=RuntimeError("page failed")),
            ),
        ):
            code, _, err = self._run(
                ["xiaohongshu", "check", "--folder-id", "folder", "--profile-id", "profile"]
            )

        self.assertEqual(code, 1)
        self.assertIn("page failed", err)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_check_missing_ids_returns_2_without_browser(self):
        factory = MagicMock()
        with patch.object(xhs_command, "browser_session", new=factory):
            code, _, _ = self._run(["xiaohongshu", "check", "--account", "creator"])
        self.assertEqual(code, 2)
        factory.assert_not_called()

    def test_upload_video_mlx_passes_none_account_and_session(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            playwright_cm = _AsyncCM(object())
            session, session_cm, factory, session_patch = self._session_patch(xhs_command)
            probe = AsyncMock(return_value=True)
            fake_app = MagicMock()
            fake_app.xiaohongshu_upload_video = AsyncMock()
            builder = MagicMock(return_value=fake_app)

            with (
                patch.object(xhs_command, "async_playwright", lambda: playwright_cm),
                session_patch,
                patch.object(xhs_command, "is_logged_in", new=probe),
                patch.object(xhs_command, "_build_video_uploader", new=builder),
            ):
                code, out, _ = self._run(
                    [
                        "xiaohongshu",
                        "upload-video",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--file",
                        str(video_path),
                        "--title",
                        "标题",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertIn("Xiaohongshu video upload submitted", out)
        builder.assert_called_once()
        self.assertIsNone(builder.call_args.args[1])
        kwargs = factory.call_args.kwargs
        self.assertIsNone(kwargs["account_file"])
        self.assertEqual(kwargs["launch_kwargs"], XHS_LAUNCH_KWARGS)
        self.assertEqual(kwargs["context_kwargs"], XHS_CONTEXT_KWARGS)
        self.assertTrue(kwargs["init_script"])
        probe.assert_awaited_once_with(session.context)
        fake_app.xiaohongshu_upload_video.assert_awaited_once_with(session=session)
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)
        self.assertEqual(playwright_cm.enter_calls, 1)

    def test_upload_note_mlx_passes_none_account_and_session(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "image.png"
            image_path.write_bytes(b"image")

            session, _, _, session_patch = self._session_patch(xhs_command)
            fake_app = MagicMock()
            fake_app.xiaohongshu_upload_note = AsyncMock()
            builder = MagicMock(return_value=fake_app)

            with (
                patch.object(xhs_command, "async_playwright", lambda: _AsyncCM(object())),
                session_patch,
                patch.object(
                    xhs_command, "is_logged_in", new=AsyncMock(return_value=True)
                ),
                patch.object(xhs_command, "_build_note_uploader", new=builder),
            ):
                code, out, _ = self._run(
                    [
                        "xiaohongshu",
                        "upload-note",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--images",
                        str(image_path),
                        "--title",
                        "图文标题",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertIn("Xiaohongshu note upload submitted", out)
        self.assertIsNone(builder.call_args.args[1])
        fake_app.xiaohongshu_upload_note.assert_awaited_once_with(session=session)

    def test_upload_mlx_logged_out_returns_10_and_skips_upload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            _, session_cm, _, session_patch = self._session_patch(xhs_command)
            upload = AsyncMock()

            with (
                patch.object(xhs_command, "async_playwright", lambda: _AsyncCM(object())),
                session_patch,
                patch.object(
                    xhs_command, "is_logged_in", new=AsyncMock(return_value=False)
                ),
                patch.object(XiaoHongShuVideo, "xiaohongshu_upload_video", new=upload),
            ):
                code, out, _ = self._run(
                    [
                        "xiaohongshu",
                        "upload-video",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--file",
                        str(video_path),
                        "--title",
                        "标题",
                    ]
                )

        self.assertEqual(code, 10)
        self.assertNotIn("submitted", out)
        upload.assert_not_awaited()
        self.assertEqual(session_cm.exit_calls, 1)

    def test_upload_mlx_failure_still_exits_session_once(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            _, session_cm, _, session_patch = self._session_patch(xhs_command)
            upload = AsyncMock(side_effect=RuntimeError("publish failed"))

            with (
                patch.object(xhs_command, "async_playwright", lambda: _AsyncCM(object())),
                session_patch,
                patch.object(
                    xhs_command, "is_logged_in", new=AsyncMock(return_value=True)
                ),
                patch.object(XiaoHongShuVideo, "xiaohongshu_upload_video", new=upload),
            ):
                code, _, err = self._run(
                    [
                        "xiaohongshu",
                        "upload-video",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--file",
                        str(video_path),
                        "--title",
                        "标题",
                    ]
                )

        self.assertEqual(code, 1)
        self.assertIn("publish failed", err)
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_local_upload_and_check_stay_on_legacy_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            legacy_upload = AsyncMock()
            legacy_check = AsyncMock(return_value=True)
            factory = MagicMock()

            with (
                patch.object(xhs_command, "upload_xiaohongshu_video", new=legacy_upload),
                patch.object(xhs_command, "check_xiaohongshu_account", new=legacy_check),
                patch.object(xhs_command, "browser_session", new=factory),
            ):
                code, out, _ = self._run(
                    [
                        "xiaohongshu",
                        "upload-video",
                        "--account",
                        "creator",
                        "--file",
                        str(video_path),
                        "--title",
                        "标题",
                    ],
                    token="",
                )
                check_code, check_out, _ = self._run(
                    ["xiaohongshu", "check", "--account", "creator"], token=""
                )

        self.assertEqual(code, 0)
        self.assertIn("Xiaohongshu video upload submitted", out)
        self.assertEqual(check_code, 0)
        self.assertIn("valid", check_out)
        factory.assert_not_called()
        self.assertIsNone(legacy_upload.await_args.kwargs.get("target"))


class KuaishouCliTests(_CliCase):
    def test_check_logged_in_returns_0_and_enters_session_once(self):
        playwright_cm = _AsyncCM(object())
        session, session_cm, factory, session_patch = self._session_patch(ks_command)
        probe = AsyncMock(return_value=True)

        with (
            patch.object(ks_command, "async_playwright", lambda: playwright_cm),
            session_patch,
            patch.object(ks_command, "is_logged_in", new=probe),
        ):
            code, out, _ = self._run(
                ["kuaishou", "check", "--folder-id", "folder", "--profile-id", "profile"]
            )

        self.assertEqual(code, 0)
        self.assertIn("valid", out)
        self.assertEqual(playwright_cm.enter_calls, 1)
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)
        probe.assert_awaited_once_with(session.context)

    def test_check_logged_out_returns_10(self):
        playwright_cm = _AsyncCM(object())
        _, session_cm, _, session_patch = self._session_patch(ks_command)

        with (
            patch.object(ks_command, "async_playwright", lambda: playwright_cm),
            session_patch,
            patch.object(
                ks_command, "is_logged_in", new=AsyncMock(return_value=False)
            ),
        ):
            code, out, _ = self._run(
                ["kuaishou", "check", "--folder-id", "folder", "--profile-id", "profile"]
            )

        self.assertEqual(code, 10)
        self.assertNotIn("valid", out)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_check_probe_error_returns_1(self):
        playwright_cm = _AsyncCM(object())
        _, session_cm, _, session_patch = self._session_patch(ks_command)

        with (
            patch.object(ks_command, "async_playwright", lambda: playwright_cm),
            session_patch,
            patch.object(
                ks_command,
                "is_logged_in",
                new=AsyncMock(side_effect=RuntimeError("page failed")),
            ),
        ):
            code, _, err = self._run(
                ["kuaishou", "check", "--folder-id", "folder", "--profile-id", "profile"]
            )

        self.assertEqual(code, 1)
        self.assertIn("page failed", err)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_check_missing_ids_returns_2_without_browser(self):
        factory = MagicMock()
        with patch.object(ks_command, "browser_session", new=factory):
            code, _, _ = self._run(["kuaishou", "check", "--account", "creator"])
        self.assertEqual(code, 2)
        factory.assert_not_called()

    def test_upload_video_mlx_passes_none_account_and_session(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            playwright_cm = _AsyncCM(object())
            session, session_cm, factory, session_patch = self._session_patch(ks_command)
            probe = AsyncMock(return_value=True)
            fake_app = MagicMock()
            fake_app.main = AsyncMock()
            builder = MagicMock(return_value=fake_app)

            with (
                patch.object(ks_command, "async_playwright", lambda: playwright_cm),
                session_patch,
                patch.object(ks_command, "is_logged_in", new=probe),
                patch.object(ks_command, "_build_video_uploader", new=builder),
            ):
                code, out, _ = self._run(
                    [
                        "kuaishou",
                        "upload-video",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--file",
                        str(video_path),
                        "--title",
                        "标题",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertIn("Kuaishou video upload submitted", out)
        builder.assert_called_once()
        self.assertIsNone(builder.call_args.args[1])
        kwargs = factory.call_args.kwargs
        self.assertIsNone(kwargs["account_file"])
        self.assertEqual(kwargs["launch_kwargs"], KUAISHOU_LAUNCH_KWARGS)
        self.assertEqual(kwargs["context_kwargs"], KUAISHOU_CONTEXT_KWARGS)
        self.assertTrue(kwargs["init_script"])
        probe.assert_awaited_once_with(session.context)
        fake_app.main.assert_awaited_once_with(session=session)
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_upload_note_mlx_passes_none_account_and_session(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "image.png"
            image_path.write_bytes(b"image")

            session, _, _, session_patch = self._session_patch(ks_command)
            fake_app = MagicMock()
            fake_app.main = AsyncMock()
            builder = MagicMock(return_value=fake_app)

            with (
                patch.object(ks_command, "async_playwright", lambda: _AsyncCM(object())),
                session_patch,
                patch.object(
                    ks_command, "is_logged_in", new=AsyncMock(return_value=True)
                ),
                patch.object(ks_command, "_build_note_uploader", new=builder),
            ):
                code, out, _ = self._run(
                    [
                        "kuaishou",
                        "upload-note",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--images",
                        str(image_path),
                        "--title",
                        "图文标题",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertIn("Kuaishou note upload submitted", out)
        self.assertIsNone(builder.call_args.args[1])
        fake_app.main.assert_awaited_once_with(session=session)

    def test_upload_mlx_logged_out_returns_10_and_skips_upload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            _, session_cm, _, session_patch = self._session_patch(ks_command)
            upload = AsyncMock()

            with (
                patch.object(ks_command, "async_playwright", lambda: _AsyncCM(object())),
                session_patch,
                patch.object(
                    ks_command, "is_logged_in", new=AsyncMock(return_value=False)
                ),
                patch.object(KSVideo, "main", new=upload),
            ):
                code, out, _ = self._run(
                    [
                        "kuaishou",
                        "upload-video",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--file",
                        str(video_path),
                        "--title",
                        "标题",
                    ]
                )

        self.assertEqual(code, 10)
        self.assertNotIn("submitted", out)
        upload.assert_not_awaited()
        self.assertEqual(session_cm.exit_calls, 1)

    def test_upload_mlx_failure_still_exits_session_once(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            _, session_cm, _, session_patch = self._session_patch(ks_command)
            upload = AsyncMock(side_effect=RuntimeError("publish failed"))

            with (
                patch.object(ks_command, "async_playwright", lambda: _AsyncCM(object())),
                session_patch,
                patch.object(
                    ks_command, "is_logged_in", new=AsyncMock(return_value=True)
                ),
                patch.object(KSVideo, "main", new=upload),
            ):
                code, _, err = self._run(
                    [
                        "kuaishou",
                        "upload-video",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--file",
                        str(video_path),
                        "--title",
                        "标题",
                    ]
                )

        self.assertEqual(code, 1)
        self.assertIn("publish failed", err)
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_local_upload_and_check_stay_on_legacy_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            legacy_upload = AsyncMock()
            legacy_check = AsyncMock(return_value=True)
            factory = MagicMock()

            with (
                patch.object(ks_command, "upload_kuaishou_video", new=legacy_upload),
                patch.object(ks_command, "check_kuaishou_account", new=legacy_check),
                patch.object(ks_command, "browser_session", new=factory),
            ):
                code, out, _ = self._run(
                    [
                        "kuaishou",
                        "upload-video",
                        "--account",
                        "creator",
                        "--file",
                        str(video_path),
                        "--title",
                        "标题",
                    ],
                    token="",
                )
                check_code, check_out, _ = self._run(
                    ["kuaishou", "check", "--account", "creator"], token=""
                )

        self.assertEqual(code, 0)
        self.assertIn("Kuaishou video upload submitted", out)
        self.assertEqual(check_code, 0)
        self.assertIn("valid", check_out)
        factory.assert_not_called()
        self.assertIsNone(legacy_upload.await_args.kwargs.get("target"))


if __name__ == "__main__":
    unittest.main()
