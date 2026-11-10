# -*- coding: utf-8 -*-
"""Tencent (视频号) + Baijiahao uploader seam, login probe and CLI (ticket 19).

Local mode must stay byte-equivalent (golden launch/context/init values).  The
Multilogin branch consumes only the injected ``BrowserSession``: it never
launches/navigates a browser context, never reads or writes cookies, never
injects init scripts and never grants permissions.
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
from sau_commands import baijiahao as baijiahao_command
from sau_commands import tencent as tencent_command
from tests.fakes import FakeContext, FakePage, FakePlaywright
from uploader.baijiahao_uploader import main as baijiahao_main
from uploader.baijiahao_uploader.main import (
    BAIJIAHAO_CONTEXT_KWARGS,
    BAIJIAHAO_HOME_URL,
    BAIJIAHAO_LAUNCH_KWARGS,
    BAIJIAHAO_LOGIN_TEXT,
    BAIJIAHAO_PUBLISH_URL,
    QR_SELECTOR,
    BaiJiaHaoVideo,
)
from uploader.tencent_uploader import main as tencent_main
from uploader.tencent_uploader.main import (
    TENCENT_CONTEXT_KWARGS,
    TENCENT_HOME_URL,
    TENCENT_LAUNCH_KWARGS,
    TENCENT_UPLOAD_URL,
    TencentNote,
    TencentVideo,
)
from utils.browser_session import BrowserSession
from utils.errors import LoginRequiredError

TOKEN = "SENTINEL-MLX-TOKEN-ticket19"


# ---------------------------------------------------------------------------
# Shared doubles
# ---------------------------------------------------------------------------


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


class _RecordingPage(FakePage):
    """FakePage plus the page APIs the upload bodies touch."""

    def __init__(self, *, events=None) -> None:
        super().__init__(events=events)
        self.wait_timeouts: list[int] = []
        self.locator_calls: list[str] = []

    async def wait_for_timeout(self, ms: int) -> None:
        self.wait_timeouts.append(ms)

    def locator(self, selector: str):
        self.locator_calls.append(selector)
        return _Locator(count=1, visible=True)

    def get_by_text(self, text: str, exact: bool = False):
        return _Locator(count=0, visible=False)


class _MlxContext(FakeContext):
    """FakeContext whose pages support the upload-body helper calls."""

    def __init__(self, *args, page: _RecordingPage | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._page = page

    async def new_page(self) -> _RecordingPage:
        self.new_page_calls += 1
        page = self._page or _RecordingPage(events=self.events)
        self.pages.append(page)
        return page


class _Locator:
    def __init__(self, *, count: int = 0, visible: bool = False) -> None:
        self._count = count
        self._visible = visible
        self.files: list[str] = []

    @property
    def first(self) -> "_Locator":
        return self

    @property
    def last(self) -> "_Locator":
        return self

    async def count(self) -> int:
        return self._count

    async def is_visible(self) -> bool:
        return self._visible

    async def wait_for(self, *args, **kwargs) -> None:
        return None

    async def set_input_files(self, path) -> None:
        self.files.append(str(path))

    async def click(self, *args, **kwargs) -> None:
        return None

    async def inner_text(self) -> str:
        return ""


class _Response:
    def __init__(self, status: int = 200) -> None:
        self.status = status


class _Frame:
    def __init__(self, url: str) -> None:
        self.url = url


class _LoginPage:
    """Page double for ``is_logged_in`` table tests."""

    def __init__(
        self,
        *,
        final_url: str,
        status: int = 200,
        goto_error: BaseException | None = None,
        visible_selectors=(),
        visible_texts=(),
        frames=(),
    ) -> None:
        self.url = "about:blank"
        self.final_url = final_url
        self.status = status
        self.goto_error = goto_error
        self.visible_selectors = set(visible_selectors)
        self.visible_texts = set(visible_texts)
        self.frames = list(frames)
        self.closed = False
        self.close_calls = 0
        self.goto_calls: list[tuple[str, dict]] = []
        self.wait_timeouts: list[int] = []

    async def goto(self, url: str, **kwargs):
        self.goto_calls.append((url, kwargs))
        if self.goto_error is not None:
            raise self.goto_error
        self.url = self.final_url
        return _Response(self.status)

    async def wait_for_timeout(self, ms: int) -> None:
        self.wait_timeouts.append(ms)

    def locator(self, selector: str) -> _Locator:
        return _Locator(
            count=1 if selector in self.visible_selectors else 0,
            visible=selector in self.visible_selectors,
        )

    def get_by_text(self, text: str, exact: bool = False) -> _Locator:
        return _Locator(
            count=1 if text in self.visible_texts else 0,
            visible=text in self.visible_texts,
        )

    async def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class _LoginContext:
    def __init__(self, page: _LoginPage) -> None:
        self.page = page
        self.new_page_calls = 0

    async def new_page(self) -> _LoginPage:
        self.new_page_calls += 1
        return self.page


def _make_tencent_video(account_file=None) -> TencentVideo:
    return TencentVideo(
        title="标题",
        file_path="/tmp/demo.mp4",
        tags=[],
        publish_date=0,
        account_file=account_file,
    )


def _make_tencent_note(tmp_dir: str, account_file=None) -> TencentNote:
    image_path = Path(tmp_dir) / "image.png"
    image_path.write_bytes(b"image")
    return TencentNote(
        image_paths=[str(image_path)],
        note="图文正文",
        tags=[],
        publish_date=0,
        account_file=account_file,
    )


def _make_baijiahao(account_file=None) -> BaiJiaHaoVideo:
    return BaiJiaHaoVideo(
        title="视频标题",
        file_path="/tmp/demo.mp4",
        tags=[],
        account_file=account_file,
        thumbnail_path="/tmp/cover.png",
    )


# ---------------------------------------------------------------------------
# Local golden values / legacy teardown
# ---------------------------------------------------------------------------


class TencentLocalGoldenTests(unittest.TestCase):
    def test_video_launch_context_and_init_are_golden(self):
        video = _make_tencent_video("/tmp/tencent-cookie.json")
        video.headless = False
        video.validate_upload_args = AsyncMock()
        video.upload_in = AsyncMock()
        playwright = FakePlaywright()

        with (
            patch.object(tencent_main, "set_init_script", AsyncMock()) as init_script,
            patch.object(tencent_main.asyncio, "sleep", AsyncMock()),
        ):
            asyncio.run(video.upload(playwright))

        self.assertEqual(
            playwright.chromium.launch_calls,
            [{"headless": False, **TENCENT_LAUNCH_KWARGS}],
        )
        browser = playwright.chromium.launch_browser
        self.assertEqual(
            browser.new_context_calls,
            [{"storage_state": "/tmp/tencent-cookie.json", **TENCENT_CONTEXT_KWARGS}],
        )
        self.assertEqual(TENCENT_CONTEXT_KWARGS, {})
        init_script.assert_not_awaited()
        self.assertFalse(tencent_main.TENCENT_INIT_SCRIPT)
        context = browser.contexts[0]
        self.assertEqual(context.storage_state_calls, ["/tmp/tencent-cookie.json"])
        self.assertTrue(context.closed)
        self.assertTrue(browser.closed)
        self.assertEqual(playwright.events, ["launch", "context.close", "browser.close"])

    def test_note_keeps_legacy_init_script_and_golden_kwargs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            note = _make_tencent_note(tmp_dir, "/tmp/tencent-note.json")
            note.validate_upload_args = AsyncMock()
            note.upload_in = AsyncMock()
            playwright = FakePlaywright()
            init_script = AsyncMock(side_effect=lambda context: context)

            with (
                patch.object(tencent_main, "set_init_script", init_script),
                patch.object(tencent_main.asyncio, "sleep", AsyncMock()),
            ):
                asyncio.run(note.upload(playwright))

        browser = playwright.chromium.launch_browser
        self.assertEqual(
            playwright.chromium.launch_calls,
            [{"headless": note.headless, **TENCENT_LAUNCH_KWARGS}],
        )
        self.assertEqual(
            browser.new_context_calls,
            [{"storage_state": "/tmp/tencent-note.json", **TENCENT_CONTEXT_KWARGS}],
        )
        init_script.assert_awaited_once_with(browser.contexts[0])
        self.assertTrue(tencent_main.TENCENT_NOTE_INIT_SCRIPT)

    def test_mlx_account_file_none_does_not_crash_constructor(self):
        self.assertIsNone(_make_tencent_video(None).account_file)
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.assertIsNone(_make_tencent_note(tmp_dir, None).account_file)


class BaijiahaoLocalGoldenTests(unittest.TestCase):
    def test_launch_context_and_init_are_golden(self):
        app = _make_baijiahao("/tmp/baijiahao-cookie.json")
        app.headless = False
        app.validate_upload_args = AsyncMock()
        app.upload_in = AsyncMock()
        playwright = FakePlaywright()

        with patch.object(baijiahao_main.asyncio, "sleep", AsyncMock()):
            asyncio.run(app.upload(playwright))

        self.assertEqual(
            playwright.chromium.launch_calls,
            [{"headless": False, **BAIJIAHAO_LAUNCH_KWARGS}],
        )
        self.assertEqual(
            BAIJIAHAO_CONTEXT_KWARGS, {"permissions": ["geolocation"]}
        )
        browser = playwright.chromium.launch_browser
        self.assertEqual(
            browser.new_context_calls,
            [{"storage_state": "/tmp/baijiahao-cookie.json", **BAIJIAHAO_CONTEXT_KWARGS}],
        )
        self.assertFalse(baijiahao_main.BAIJIAHAO_INIT_SCRIPT)
        context = browser.contexts[0]
        self.assertEqual(context.forbidden_calls, [])
        self.assertEqual(context.add_init_script_calls, [])
        self.assertEqual(context.storage_state_calls, ["/tmp/baijiahao-cookie.json"])
        self.assertTrue(context.closed)
        self.assertTrue(browser.closed)

    def test_mlx_account_file_none_does_not_crash_constructor(self):
        self.assertIsNone(_make_baijiahao(None).account_file)


# ---------------------------------------------------------------------------
# Multilogin branches: no forbidden APIs, no cookie I/O, no teardown
# ---------------------------------------------------------------------------


class TencentMultiloginUploadTests(unittest.TestCase):
    def test_video_uses_injected_context_only(self):
        video = _make_tencent_video(None)
        video.validate_upload_args = AsyncMock()
        page = _RecordingPage()
        context = _MlxContext(page=page)
        session = BrowserSession(browser=MagicMock(), context=context, mode="multilogin")

        steps = {
            "open_upload_page": AsyncMock(),
            "upload_video_file": AsyncMock(),
            "prepare_video_for_publish": AsyncMock(),
            "wait_for_upload_complete": AsyncMock(),
            "apply_collection": AsyncMock(),
            "apply_original_statement": AsyncMock(),
            "set_thumbnail": AsyncMock(),
            "set_short_title": AsyncMock(),
            "submit_publish": AsyncMock(),
        }

        with (
            patch.object(tencent_main, "async_playwright", MagicMock()) as async_playwright,
            patch.multiple(video, **steps),
        ):
            asyncio.run(video.upload(None, session=session))

        async_playwright.assert_not_called()
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, [])
        self.assertEqual(context.forbidden_calls, [])
        self.assertFalse(context.closed)
        self.assertIsNone(video.account_file)
        steps["open_upload_page"].assert_awaited_once_with(page, multilogin=True)
        steps["wait_for_upload_complete"].assert_awaited_once_with(
            page, multilogin=True
        )
        steps["submit_publish"].assert_awaited_once_with(page, multilogin=True)

    def test_mlx_skips_cookie_auth(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")
            video = _make_tencent_video(None)
            video.file_path = str(video_path)
            video.upload_in = AsyncMock()
            cookie_auth = AsyncMock()

            with patch.object(tencent_main, "cookie_auth", cookie_auth):
                asyncio.run(
                    video.upload(
                        None,
                        session=BrowserSession(
                            browser=MagicMock(),
                            context=_MlxContext(),
                            mode="multilogin",
                        ),
                    )
                )

        cookie_auth.assert_not_awaited()

    def test_login_redirect_mid_upload_raises_login_required(self):
        video = _make_tencent_video(None)
        video.validate_upload_args = AsyncMock()
        page = _RecordingPage()
        page.url = "https://channels.weixin.qq.com/platform/login.html"
        context = _MlxContext(page=page)
        session = BrowserSession(browser=MagicMock(), context=context, mode="multilogin")
        steps = {
            "open_upload_page": AsyncMock(),
            "upload_video_file": AsyncMock(),
            "submit_publish": AsyncMock(),
        }

        with patch.multiple(video, **steps):
            with self.assertRaises(LoginRequiredError):
                asyncio.run(video.upload(None, session=session))

        steps["upload_video_file"].assert_not_awaited()
        steps["submit_publish"].assert_not_awaited()

    def test_open_upload_page_login_redirect_raises_login_required_only_in_mlx(self):
        class _RedirectPage:
            def __init__(self) -> None:
                self.url = "about:blank"
                self.frames: list = []

            async def goto(self, url, **kwargs):
                self.url = TENCENT_HOME_URL

            async def wait_for_url(self, pattern, **kwargs):
                self.url = "https://channels.weixin.qq.com/platform/login.html"

            async def wait_for_load_state(self, *args, **kwargs):
                return None

            def locator(self, selector):
                return _Locator(count=0)

        video = _make_tencent_video(None)
        page = _RedirectPage()
        with self.assertRaises(LoginRequiredError):
            asyncio.run(video.open_upload_page(page, multilogin=True))

        local_page = _RedirectPage()
        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(video.open_upload_page(local_page, multilogin=False))
        self.assertNotIsInstance(ctx.exception, LoginRequiredError)

    def test_note_mlx_uses_session_and_never_opens_playwright(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            note = _make_tencent_note(tmp_dir, None)
            note.upload = AsyncMock()
            session = BrowserSession(
                browser=MagicMock(), context=MagicMock(), mode="multilogin"
            )

            with patch.object(
                tencent_main, "async_playwright", MagicMock()
            ) as async_playwright:
                asyncio.run(note.tencent_upload_note(session=session))

        async_playwright.assert_not_called()
        note.upload.assert_awaited_once_with(None, session=session)
        self.assertIsNone(note.account_file)


class BaijiahaoMultiloginUploadTests(unittest.TestCase):
    def _session(self, page: _RecordingPage):
        context = _MlxContext(page=page)
        return BrowserSession(browser=MagicMock(), context=context, mode="multilogin"), context

    def test_upload_uses_injected_context_only(self):
        app = _make_baijiahao(None)
        app.validate_upload_args = AsyncMock()
        page = _RecordingPage()
        session, context = self._session(page)

        steps = {
            "_fill_title": AsyncMock(),
            "_wait_upload_complete": AsyncMock(),
            "_upload_thumbnail": AsyncMock(),
            "_check_ai_declaration": AsyncMock(),
            "_apply_collection": AsyncMock(),
            "_submit_publish": AsyncMock(),
        }

        with (
            patch.object(baijiahao_main, "async_playwright", MagicMock()) as async_playwright,
            patch.multiple(app, **steps),
        ):
            asyncio.run(app.upload(None, session=session))

        async_playwright.assert_not_called()
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, [])
        self.assertEqual(context.forbidden_calls, [])
        self.assertFalse(context.closed)
        self.assertIsNone(app.account_file)
        self.assertEqual(page.goto_calls[0][0], BAIJIAHAO_PUBLISH_URL)
        steps["_wait_upload_complete"].assert_awaited_once_with(page, multilogin=True)
        steps["_submit_publish"].assert_awaited_once_with(page, multilogin=True)

    def test_mlx_skips_cookie_auth_and_grant_permissions(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            cover_path = Path(tmp_dir) / "cover.png"
            video_path.write_bytes(b"video")
            cover_path.write_bytes(b"image")
            app = _make_baijiahao(None)
            app.file_path = str(video_path)
            app.thumbnail_path = str(cover_path)
            app.upload_in = AsyncMock()
            cookie_auth = AsyncMock()

            with patch.object(baijiahao_main, "cookie_auth", cookie_auth):
                asyncio.run(
                    app.upload(
                        None,
                        session=BrowserSession(
                            browser=MagicMock(),
                            context=_MlxContext(),
                            mode="multilogin",
                        ),
                    )
                )

        cookie_auth.assert_not_awaited()

    def test_login_redirect_mid_upload_raises_login_required(self):
        app = _make_baijiahao(None)
        app.validate_upload_args = AsyncMock()
        page = _RecordingPage()
        session, _ = self._session(page)

        async def goto_login(url, **kwargs):
            page.url = "https://baijiahao.baidu.com/builder/theme/bjh/login"

        page.goto = goto_login  # type: ignore[method-assign]

        with patch.object(app, "_fill_title", AsyncMock()) as fill_title:
            with self.assertRaises(LoginRequiredError):
                asyncio.run(app.upload(None, session=session))

        fill_title.assert_not_awaited()

    def test_main_with_session_does_not_open_playwright(self):
        app = _make_baijiahao(None)
        app.upload = AsyncMock()
        session = BrowserSession(
            browser=MagicMock(), context=MagicMock(), mode="multilogin"
        )

        with patch.object(
            baijiahao_main, "async_playwright", MagicMock()
        ) as async_playwright:
            asyncio.run(app.main(session=session))

        async_playwright.assert_not_called()
        app.upload.assert_awaited_once_with(None, session=session)


# ---------------------------------------------------------------------------
# is_logged_in: True / False / raise
# ---------------------------------------------------------------------------


class TencentLoginDetectionTests(unittest.TestCase):
    def _probe(self, page: _LoginPage) -> bool:
        context = _LoginContext(page)
        result = asyncio.run(tencent_main.is_logged_in(context))
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(page.close_calls, 1)
        self.assertTrue(page.closed)
        self.assertEqual(page.goto_calls[0][0], TENCENT_UPLOAD_URL)
        return result

    def test_publish_marker_returns_true(self):
        page = _LoginPage(
            final_url=TENCENT_UPLOAD_URL,
            visible_selectors={'button:has-text("保存草稿")'},
        )
        self.assertTrue(self._probe(page))
        timeout = page.goto_calls[0][1]["timeout"]
        self.assertGreaterEqual(timeout, 15_000)
        self.assertLessEqual(timeout, 30_000)
        self.assertLessEqual(
            timeout + sum(page.wait_timeouts), 30_000
        )

    def test_login_url_returns_false(self):
        page = _LoginPage(
            final_url="https://channels.weixin.qq.com/platform/login.html"
        )
        self.assertFalse(self._probe(page))

    def test_qr_iframe_returns_false(self):
        page = _LoginPage(
            final_url=TENCENT_UPLOAD_URL,
            frames=[_Frame("https://open.weixin.qq.com/connect/qrconnect?appid=x")],
        )
        self.assertFalse(self._probe(page))

    def test_visible_qr_marker_returns_false(self):
        page = _LoginPage(
            final_url=TENCENT_UPLOAD_URL,
            visible_selectors={"div.login-qrcode-wrap"},
        )
        self.assertFalse(self._probe(page))

    def test_network_error_propagates(self):
        page = _LoginPage(
            final_url=TENCENT_UPLOAD_URL,
            goto_error=RuntimeError("net::ERR_CONNECTION_RESET"),
        )
        with self.assertRaises(RuntimeError):
            asyncio.run(tencent_main.is_logged_in(_LoginContext(page)))
        self.assertEqual(page.close_calls, 1)

    def test_server_error_propagates(self):
        page = _LoginPage(final_url=TENCENT_UPLOAD_URL, status=503)
        with self.assertRaises(RuntimeError):
            asyncio.run(tencent_main.is_logged_in(_LoginContext(page)))
        self.assertEqual(page.close_calls, 1)

    def test_unexpected_domain_propagates(self):
        page = _LoginPage(final_url="https://example.com/something")
        with self.assertRaises(RuntimeError):
            asyncio.run(tencent_main.is_logged_in(_LoginContext(page)))

    def test_structure_anomaly_propagates(self):
        page = _LoginPage(final_url=TENCENT_HOME_URL)
        with self.assertRaises(RuntimeError):
            asyncio.run(tencent_main.is_logged_in(_LoginContext(page)))


class BaijiahaoLoginDetectionTests(unittest.TestCase):
    def _probe(self, page: _LoginPage) -> bool:
        context = _LoginContext(page)
        result = asyncio.run(baijiahao_main.is_logged_in(context))
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(page.close_calls, 1)
        self.assertTrue(page.closed)
        self.assertEqual(page.goto_calls[0][0], BAIJIAHAO_HOME_URL)
        return result

    def test_business_anchor_returns_true(self):
        page = _LoginPage(
            final_url=BAIJIAHAO_HOME_URL,
            visible_selectors={'a[href*="/builder/rc/edit"]'},
        )
        self.assertTrue(self._probe(page))
        timeout = page.goto_calls[0][1]["timeout"]
        self.assertGreaterEqual(timeout, 15_000)
        self.assertLessEqual(timeout, 30_000)
        self.assertLessEqual(timeout + sum(page.wait_timeouts), 30_000)

    def test_login_url_returns_false(self):
        page = _LoginPage(
            final_url="https://baijiahao.baidu.com/builder/theme/bjh/login"
        )
        self.assertFalse(self._probe(page))

    def test_login_text_returns_false(self):
        page = _LoginPage(
            final_url=BAIJIAHAO_HOME_URL,
            visible_texts={BAIJIAHAO_LOGIN_TEXT},
        )
        self.assertFalse(self._probe(page))

    def test_qr_marker_returns_false(self):
        page = _LoginPage(final_url=BAIJIAHAO_HOME_URL, visible_selectors={QR_SELECTOR})
        self.assertFalse(self._probe(page))

    def test_network_error_propagates(self):
        page = _LoginPage(
            final_url=BAIJIAHAO_HOME_URL,
            goto_error=RuntimeError("net::ERR_CONNECTION_RESET"),
        )
        with self.assertRaises(RuntimeError):
            asyncio.run(baijiahao_main.is_logged_in(_LoginContext(page)))
        self.assertEqual(page.close_calls, 1)

    def test_server_error_propagates(self):
        page = _LoginPage(final_url=BAIJIAHAO_HOME_URL, status=502)
        with self.assertRaises(RuntimeError):
            asyncio.run(baijiahao_main.is_logged_in(_LoginContext(page)))

    def test_unexpected_domain_propagates(self):
        page = _LoginPage(final_url="https://example.com/something")
        with self.assertRaises(RuntimeError):
            asyncio.run(baijiahao_main.is_logged_in(_LoginContext(page)))

    def test_structure_anomaly_propagates(self):
        page = _LoginPage(final_url=BAIJIAHAO_HOME_URL)
        with self.assertRaises(RuntimeError):
            asyncio.run(baijiahao_main.is_logged_in(_LoginContext(page)))


# ---------------------------------------------------------------------------
# CLI check: 0 / 10 / 1 / 2
# ---------------------------------------------------------------------------


class _RunHelpers:
    module = None
    platform = ""

    def _run(self, argv, token=TOKEN):
        with patch.dict(os.environ, {"MLX_API_TOKEN": token}):
            with redirect_stdout(io.StringIO()) as out, redirect_stderr(
                io.StringIO()
            ) as err:
                code = sau_cli.main(argv)
        return code, out.getvalue(), err.getvalue()


class _CheckCliCase(_RunHelpers):
    def _check_args(self):
        return [self.platform, "check", "--folder-id", "folder", "--profile-id", "profile"]

    def test_check_logged_in_returns_0_and_enters_session_once(self):
        playwright_cm = _AsyncCM(object())
        session = Namespace(context=object())
        session_cm = _AsyncCM(session)
        probe = AsyncMock(return_value=True)

        with (
            patch.object(self.module, "async_playwright", lambda: playwright_cm),
            patch.object(self.module, "browser_session", new=MagicMock(return_value=session_cm)),
            patch.object(self.module, "is_logged_in", new=probe),
        ):
            code, out, _ = self._run(self._check_args())

        self.assertEqual(code, 0)
        self.assertIn("valid", out)
        self.assertEqual(playwright_cm.enter_calls, 1)
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)
        probe.assert_awaited_once_with(session.context)

    def test_check_logged_out_returns_10(self):
        session_cm = _AsyncCM(Namespace(context=object()))

        with (
            patch.object(self.module, "async_playwright", lambda: _AsyncCM(object())),
            patch.object(self.module, "browser_session", new=MagicMock(return_value=session_cm)),
            patch.object(self.module, "is_logged_in", new=AsyncMock(return_value=False)),
        ):
            code, out, _ = self._run(self._check_args())

        self.assertEqual(code, 10)
        self.assertNotIn("valid", out)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_check_probe_error_returns_1_and_still_exits_session_once(self):
        session_cm = _AsyncCM(Namespace(context=object()))
        probe = AsyncMock(side_effect=RuntimeError("page failed"))

        with (
            patch.object(self.module, "async_playwright", lambda: _AsyncCM(object())),
            patch.object(self.module, "browser_session", new=MagicMock(return_value=session_cm)),
            patch.object(self.module, "is_logged_in", new=probe),
        ):
            code, _, _ = self._run(self._check_args())

        self.assertEqual(code, 1)
        self.assertEqual(session_cm.exit_calls, 1)
        self.assertIsNotNone(session_cm.last_exc[1])

    def test_check_missing_ids_returns_2_without_browser(self):
        session_factory = MagicMock()

        with patch.object(self.module, "browser_session", new=session_factory):
            code, _, _ = self._run([self.platform, "check", "--account", "creator"])

        self.assertEqual(code, 2)
        session_factory.assert_not_called()

    def test_check_local_mode_keeps_legacy(self):
        with (
            patch.object(
                self.module,
                self._local_check_name,
                new=AsyncMock(return_value=True),
            ),
            patch.object(self.module, "browser_session", new=MagicMock()) as session_factory,
        ):
            code, out, _ = self._run(
                [self.platform, "check", "--account", "creator"], token=""
            )

        self.assertEqual(code, 0)
        self.assertIn("valid", out)
        session_factory.assert_not_called()


class TencentCheckCliTests(_CheckCliCase, unittest.TestCase):
    module = tencent_command
    platform = "tencent"
    _local_check_name = "check_tencent_account"


class BaijiahaoCheckCliTests(_CheckCliCase, unittest.TestCase):
    module = baijiahao_command
    platform = "baijiahao"
    _local_check_name = "check_baijiahao_account"


# ---------------------------------------------------------------------------
# CLI upload: 0 / 10 / 1, Stop/session ownership
# ---------------------------------------------------------------------------


class _UploadCliCase(_RunHelpers):
    entry_name = ""

    def _upload_args(self, tmp_dir):
        video = Path(tmp_dir) / "demo.mp4"
        video.write_bytes(b"video")
        return [
            self.platform,
            "upload-video",
            "--folder-id",
            "folder",
            "--profile-id",
            "profile",
            "--file",
            str(video),
            "--title",
            "标题",
        ]

    def _upload_patches(self, app, probe):
        self.builder_mock = MagicMock(return_value=app)
        self.session_factory = MagicMock(return_value=self.session_cm)
        self.resolve_account_mock = MagicMock()
        self.setup_mock = AsyncMock()
        return (
            patch.object(self.module, "async_playwright", lambda: _AsyncCM(object())),
            patch.object(self.module, "browser_session", new=self.session_factory),
            patch.object(self.module, "is_logged_in", new=probe),
            patch.object(self.module, self.builder_name, new=self.builder_mock),
            patch.object(self.module, "resolve_account_file", new=self.resolve_account_mock),
            patch.object(self.module, self.setup_name, new=self.setup_mock),
        )

    def test_upload_logged_in_returns_0_with_one_session(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            session = Namespace(context=object())
            self.session_cm = _AsyncCM(session)
            app = MagicMock()
            setattr(app, self.entry_name, AsyncMock())
            probe = AsyncMock(return_value=True)
            patches = self._upload_patches(app, probe)

            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                code, out, _ = self._run(self._upload_args(tmp_dir))

        self.assertEqual(code, 0)
        self.assertIn("upload submitted", out)
        getattr(app, self.entry_name).assert_awaited_once_with(session=session)
        self.builder_mock.assert_called_once()
        self.assertIsNone(self.builder_mock.call_args.kwargs.get("account_file"))
        session_factory = self.session_factory
        kwargs = session_factory.call_args.kwargs
        self.assertIsNone(kwargs["account_file"])
        self.assertEqual(kwargs["launch_kwargs"], self.launch_kwargs)
        self.assertEqual(kwargs["context_kwargs"], self.context_kwargs)
        self.assertFalse(kwargs["init_script"])
        probe.assert_awaited_once_with(session.context)
        self.resolve_account_mock.assert_not_called()
        self.setup_mock.assert_not_awaited()
        self.assertEqual(self.session_cm.enter_calls, 1)
        self.assertEqual(self.session_cm.exit_calls, 1)

    def test_upload_logged_out_returns_10_and_skips_upload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.session_cm = _AsyncCM(Namespace(context=object()))
            app = MagicMock()
            setattr(app, self.entry_name, AsyncMock())
            patches = self._upload_patches(app, AsyncMock(return_value=False))

            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                code, out, _ = self._run(self._upload_args(tmp_dir))

        self.assertEqual(code, 10)
        self.assertNotIn("upload submitted", out)
        getattr(app, self.entry_name).assert_not_awaited()
        self.assertEqual(self.session_cm.enter_calls, 1)
        self.assertEqual(self.session_cm.exit_calls, 1)

    def test_upload_failure_returns_1_and_still_exits_session_once(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.session_cm = _AsyncCM(Namespace(context=object()))
            app = MagicMock()
            setattr(app, self.entry_name, AsyncMock(side_effect=RuntimeError("publish failed")))
            patches = self._upload_patches(app, AsyncMock(return_value=True))

            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                code, _, err = self._run(self._upload_args(tmp_dir))

        self.assertEqual(code, 1)
        self.assertIn("publish failed", err)
        self.assertEqual(self.session_cm.enter_calls, 1)
        self.assertEqual(self.session_cm.exit_calls, 1)

    def test_upload_local_mode_keeps_legacy_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            legacy_upload = AsyncMock()
            session_factory = MagicMock()

            with (
                patch.object(self.module, self.local_upload_name, new=legacy_upload),
                patch.object(self.module, "browser_session", new=session_factory),
            ):
                code, out, _ = self._run(
                    [
                        self.platform,
                        "upload-video",
                        "--account",
                        "creator",
                        "--file",
                        self._upload_args(tmp_dir)[7],
                        "--title",
                        "标题",
                    ],
                    token="",
                )

        self.assertEqual(code, 0)
        self.assertIn("upload submitted", out)
        session_factory.assert_not_called()
        self.assertIsNone(legacy_upload.await_args.kwargs.get("target"))


class TencentUploadCliTests(_UploadCliCase, unittest.TestCase):
    module = tencent_command
    platform = "tencent"
    entry_name = "tencent_upload_video"
    builder_name = "TencentVideo"
    setup_name = "tencent_setup"
    local_upload_name = "upload_tencent_video"
    launch_kwargs = TENCENT_LAUNCH_KWARGS
    context_kwargs = TENCENT_CONTEXT_KWARGS
    _local_check_name = "check_tencent_account"


class BaijiahaoUploadCliTests(_UploadCliCase, unittest.TestCase):
    module = baijiahao_command
    platform = "baijiahao"
    entry_name = "main"
    builder_name = "BaiJiaHaoVideo"
    setup_name = "baijiahao_setup"
    local_upload_name = "upload_baijiahao_video"
    launch_kwargs = BAIJIAHAO_LAUNCH_KWARGS
    context_kwargs = BAIJIAHAO_CONTEXT_KWARGS
    _local_check_name = "check_baijiahao_account"


if __name__ == "__main__":
    unittest.main()
