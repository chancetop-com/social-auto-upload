# -*- coding: utf-8 -*-
"""Ticket 21 — Hupu and Dayu Multilogin seams (local golden + MLX-only paths).

All tests are offline.  They lock the historical local launch/context options and
prove the Multilogin branch never launches a browser, creates a context, writes
cookies, sets the local timezone, injects stealth or reads identity files.
"""

from __future__ import annotations

import asyncio
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import sau_cli
from conf import LOCAL_CHROME_PATH
from sau_commands import dayu as dayu_command
from sau_commands import hupu as hupu_command
from tests.fakes import (
    FakeBrowser,
    FakeContext,
    FakeMultiloginClient,
    FakePlaywright,
)
from uploader.dayu_uploader import article as dayu_article_module
from uploader.dayu_uploader import main as dayu_main_module
from uploader.dayu_uploader import session as dayu_session
from uploader.dayu_uploader.article import DayuArticle
from uploader.dayu_uploader.main import DayuVideo
from uploader.dayu_uploader.session import (
    DAYU_CONTEXT_KWARGS,
    DAYU_INIT_SCRIPT,
    DAYU_LAUNCH_KWARGS,
    is_logged_in as dayu_is_logged_in,
)
from uploader.hupu_uploader import main as hupu_main
from uploader.hupu_uploader.main import (
    HUPU_CONTEXT_KWARGS,
    HUPU_INIT_SCRIPT,
    HUPU_LAUNCH_KWARGS,
    HuPuVideo,
    is_logged_in as hupu_is_logged_in,
    prepare_local_context,
)
from utils.browser_session import BrowserSession, browser_session
from utils.errors import LoginRequiredError
from utils.multilogin import MultiloginProvider, MultiloginTarget

TOKEN = "SENTINEL-MLX-TOKEN-ticket21"
PROFILE = "profile-21"
FOLDER = "folder-21"


class _AsyncCM:
    def __init__(self, value=None, enter_error: BaseException | None = None) -> None:
        self.value = value
        self.enter_error = enter_error
        self.enter_calls = 0
        self.exit_calls = 0

    async def __aenter__(self):
        self.enter_calls += 1
        if self.enter_error is not None:
            raise self.enter_error
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        self.exit_calls += 1
        return False


class _CountLocator:
    def __init__(self, count: int = 0, text: str = "") -> None:
        self._count = count
        self._text = text
        self.files = None
        self.first = self

    async def count(self) -> int:
        return self._count

    async def inner_text(self) -> str:
        return self._text

    async def set_input_files(self, files) -> None:
        self.files = files


class _LoginPage:
    """Page double for ``is_logged_in`` tests."""

    def __init__(
        self,
        *,
        final_url: str,
        status: int = 200,
        upload_count: int = 0,
        user_count: int = 0,
        name_count: int = 0,
        name_text: str = "",
        login_iframe_count: int = 0,
        goto_error: BaseException | None = None,
    ) -> None:
        self.url = "about:blank"
        self.final_url = final_url
        self.status = status
        self.upload_count = upload_count
        self.user_count = user_count
        self.name_count = name_count
        self.name_text = name_text
        self.login_iframe_count = login_iframe_count
        self.goto_error = goto_error
        self.goto_calls: list[tuple[str, dict]] = []
        self.closed = False
        self.settle_calls: list[int] = []

    async def goto(self, url: str, **kwargs):
        self.goto_calls.append((url, kwargs))
        if self.goto_error is not None:
            raise self.goto_error
        self.url = self.final_url
        return SimpleNamespace(status=self.status)

    async def wait_for_timeout(self, ms: int) -> None:
        self.settle_calls.append(ms)

    def get_by_role(self, role: str, name: str | None = None):
        return _CountLocator(self.upload_count)

    def locator(self, selector: str):
        if "uop.dayu.com/cas" in selector:
            return _CountLocator(self.login_iframe_count)
        if selector == ".header-info .name":
            return _CountLocator(self.name_count, self.name_text)
        return _CountLocator(self.user_count)

    async def close(self) -> None:
        self.closed = True


class _LoginContext:
    def __init__(self, page: _LoginPage) -> None:
        self.page = page
        self.new_page_calls = 0

    async def new_page(self) -> _LoginPage:
        self.new_page_calls += 1
        return self.page

    async def storage_state(self, **kwargs):
        raise AssertionError("is_logged_in must not read storage state")


class _RecordingContext:
    """Context double that records only the APIs local setup is allowed to use."""

    def __init__(self, browser=None, state=None) -> None:
        self.browser = browser
        self._state = state
        self.closed = False
        self.storage_state_reads = 0
        self.add_init_script_calls: list[str] = []

    async def storage_state(self, **kwargs):
        self.storage_state_reads += 1
        return self._state

    async def close(self) -> None:
        self.closed = True

    async def add_init_script(self, script: str) -> None:
        self.add_init_script_calls.append(script)


class _ReplacementBrowser:
    def __init__(self) -> None:
        self.new_context_calls: list[dict] = []
        self.replacement = _RecordingContext(state={"cookies": []})

    async def new_context(self, **kwargs):
        self.new_context_calls.append(kwargs)
        return self.replacement


class _GotoPage:
    """Minimal page for mid-upload login redirect tests."""

    def __init__(self, final_url: str) -> None:
        self.url = "about:blank"
        self.final_url = final_url
        self.closed = False

    async def goto(self, url: str, **kwargs):
        self.url = self.final_url
        return SimpleNamespace(status=200)

    async def close(self) -> None:
        self.closed = True


class _GotoContext:
    def __init__(self, page) -> None:
        self.page = page
        self.new_page_calls = 0

    async def new_page(self):
        self.new_page_calls += 1
        return self.page


def _make_video_file(tmp_dir: str) -> Path:
    path = Path(tmp_dir) / "demo.mp4"
    path.write_bytes(b"video")
    return path


def _make_article_file(tmp_dir: str) -> Path:
    path = Path(tmp_dir) / "article.html"
    path.write_text("<p>正文内容</p>", encoding="utf-8")
    return path


class HupuLocalGoldenTests(unittest.TestCase):
    def test_golden_constants_match_legacy_launch_and_empty_context(self):
        legacy = hupu_main._build_launch_kwargs(headless=False)
        expected = {k: v for k, v in legacy.items() if k != "headless"}
        self.assertEqual(HUPU_LAUNCH_KWARGS, expected)
        self.assertEqual(HUPU_CONTEXT_KWARGS, {})
        self.assertFalse(HUPU_INIT_SCRIPT)
        self.assertTrue(callable(prepare_local_context))

    def test_local_upload_launch_context_and_teardown_are_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            account = Path(tmp_dir) / "hupu_account.json"
            account.write_text("{}", encoding="utf-8")
            video = _make_video_file(tmp_dir)
            app = HuPuVideo("测试标题", str(video), [], str(account), headless=False)
            app.validate_upload_args = AsyncMock()
            app.upload_in = AsyncMock()
            page = MagicMock()

            playwright = FakePlaywright()
            with (
                patch.object(hupu_main, "_new_stealth_page", AsyncMock(return_value=page)),
                patch.object(hupu_main, "hupu_logger", MagicMock()),
            ):
                asyncio.run(app.upload(playwright))

        self.assertEqual(
            playwright.chromium.launch_calls,
            [hupu_main._build_launch_kwargs(headless=False)],
        )
        browser = playwright.chromium.launch_browser
        self.assertEqual(
            browser.new_context_calls,
            [
                {
                    "user_agent": hupu_main._CHROME_UA,
                    "viewport": {"width": 1920, "height": 1080},
                    "storage_state": str(account),
                }
            ],
        )
        context = browser.contexts[0]
        self.assertEqual(context.storage_state_calls, [str(account)])
        self.assertTrue(context.closed)
        self.assertTrue(browser.closed)
        app.upload_in.assert_awaited_once()
        session = app.upload_in.await_args.args[0]
        self.assertEqual(session.mode, "local")
        self.assertIs(session.context, context)
        self.assertIs(app.upload_in.await_args.kwargs["page"], page)


class HupuPrepareLocalContextTests(unittest.TestCase):
    def test_prepare_replaces_context_with_ua_viewport_and_stealth(self):
        browser = _ReplacementBrowser()
        original = _RecordingContext(browser=browser, state={"cookies": [{"name": "u"}]})

        prepared = asyncio.run(prepare_local_context(original))

        self.assertTrue(original.closed)
        self.assertEqual(original.storage_state_reads, 1)
        self.assertEqual(
            browser.new_context_calls,
            [
                {
                    "user_agent": hupu_main._CHROME_UA,
                    "viewport": {"width": 1920, "height": 1080},
                    "storage_state": {"cookies": [{"name": "u"}]},
                }
            ],
        )
        self.assertIs(prepared, browser.replacement)
        self.assertEqual(
            browser.replacement.add_init_script_calls, [hupu_main._STEALTH_SCRIPT]
        )


class HupuLoginDetectionTests(unittest.TestCase):
    def test_positive_upload_button_returns_true(self):
        page = _LoginPage(
            final_url="https://bbs.hupu.com/newpost?tabkey=2", upload_count=1
        )
        context = _LoginContext(page)
        self.assertTrue(asyncio.run(hupu_is_logged_in(context)))
        self.assertEqual(page.goto_calls[0][0], hupu_main.HUPU_LOGIN_CHECK_URL)
        self.assertEqual(page.settle_calls, [hupu_main.HUPU_LOGIN_CHECK_SETTLE_MS])
        self.assertTrue(page.closed)

    def test_positive_user_menu_returns_true(self):
        page = _LoginPage(
            final_url="https://bbs.hupu.com/newpost?tabkey=2", user_count=1
        )
        self.assertTrue(asyncio.run(hupu_is_logged_in(_LoginContext(page))))

    def test_login_redirect_returns_false(self):
        page = _LoginPage(final_url="https://passport.hupu.com/v2/login?pcPhone=1")
        self.assertFalse(asyncio.run(hupu_is_logged_in(_LoginContext(page))))
        self.assertTrue(page.closed)

    def test_no_positive_signal_raises(self):
        page = _LoginPage(final_url="https://bbs.hupu.com/newpost?tabkey=2")
        with self.assertRaisesRegex(RuntimeError, "页面结构异常"):
            asyncio.run(hupu_is_logged_in(_LoginContext(page)))
        self.assertTrue(page.closed)

    def test_http_5xx_raises(self):
        page = _LoginPage(
            final_url="https://bbs.hupu.com/newpost?tabkey=2", status=503
        )
        with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
            asyncio.run(hupu_is_logged_in(_LoginContext(page)))

    def test_unexpected_host_raises(self):
        page = _LoginPage(final_url="https://example.com/")
        with self.assertRaisesRegex(RuntimeError, "虎扑"):
            asyncio.run(hupu_is_logged_in(_LoginContext(page)))

    def test_navigation_error_raises(self):
        page = _LoginPage(
            final_url="https://bbs.hupu.com/newpost?tabkey=2",
            goto_error=TimeoutError("nav timeout"),
        )
        with self.assertRaises(TimeoutError):
            asyncio.run(hupu_is_logged_in(_LoginContext(page)))


class HupuMultiloginUploadTests(unittest.TestCase):
    def test_mlx_upload_only_consumes_session(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = HuPuVideo("测试标题", str(_make_video_file(tmp_dir)), [], None)
            app.validate_upload_args = AsyncMock()
            app.upload_in = AsyncMock()
            context = FakeContext()
            session = BrowserSession(browser=MagicMock(), context=context, mode="multilogin")

            with (
                patch.object(hupu_main, "async_playwright", MagicMock()) as async_playwright,
                patch.object(hupu_main, "cookie_auth", AsyncMock()) as cookie_auth,
                patch.object(hupu_main, "_new_stealth_page", AsyncMock()) as stealth_page,
            ):
                asyncio.run(app.upload(None, session=session))

        async_playwright.assert_not_called()
        cookie_auth.assert_not_awaited()
        stealth_page.assert_not_awaited()
        app.validate_upload_args.assert_awaited_once_with(check_cookie=False)
        app.upload_in.assert_awaited_once_with(session)
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, [])
        self.assertEqual(context.forbidden_calls, [])
        self.assertIsNone(app.account_file)

    def test_mid_upload_login_redirect_raises_login_required(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = HuPuVideo("测试标题", str(_make_video_file(tmp_dir)), [], None)
            page = _GotoPage("https://passport.hupu.com/v2/login")
            context = _GotoContext(page)
            session = BrowserSession(browser=MagicMock(), context=context, mode="multilogin")
            with self.assertRaises(LoginRequiredError):
                asyncio.run(app.upload_in(session))
        self.assertEqual(context.new_page_calls, 1)

    def test_browser_session_mlx_ignores_context_setup_and_local_kwargs(self):
        target = MultiloginTarget(folder_id=FOLDER, profile_id=PROFILE)
        playwright = FakePlaywright()
        context = FakeContext()
        browser = FakeBrowser([context], allow_new_context=False)
        playwright.chromium.queue_connect_browser(browser)
        client = FakeMultiloginClient()
        setup = MagicMock()

        async def scenario():
            async with browser_session(
                playwright,
                headless=True,
                account_file="/tmp/must-not-read.json",
                managed=MultiloginProvider(target, client),
                launch_kwargs=HUPU_LAUNCH_KWARGS,
                context_kwargs=HUPU_CONTEXT_KWARGS,
                init_script=HUPU_INIT_SCRIPT,
                context_setup=setup,
            ) as session:
                self.assertEqual(session.mode, "multilogin")

        with patch.dict(os.environ, {"MLX_API_TOKEN": TOKEN}):
            asyncio.run(scenario())

        setup.assert_not_called()
        self.assertEqual(playwright.chromium.launch_calls, [])
        self.assertEqual(browser.new_context_calls, [])
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, [])
        self.assertEqual(client.stop_calls, [PROFILE])


class HupuCliTests(unittest.TestCase):
    def _run(self, argv, token=TOKEN):
        with patch.dict(os.environ, {"MLX_API_TOKEN": token}):
            with redirect_stdout(io.StringIO()) as out, redirect_stderr(
                io.StringIO()
            ) as err:
                code = sau_cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_check_mlx_returns_0_when_logged_in(self):
        session = SimpleNamespace(context=object())
        factory = MagicMock(return_value=_AsyncCM(session))
        with (
            patch.object(
                hupu_command, "async_playwright", lambda: _AsyncCM(object())
            ),
            patch.object(hupu_command, "browser_session", new=factory),
            patch.object(hupu_command, "is_logged_in", new=AsyncMock(return_value=True)),
        ):
            code, out, _ = self._run(
                ["hupu", "check", "--folder-id", FOLDER, "--profile-id", PROFILE]
            )
        self.assertEqual(code, 0)
        self.assertIn("valid", out)
        self.assertIsNone(factory.call_args.kwargs.get("account_file"))
        self.assertEqual(
            factory.call_args.kwargs["managed"].target,
            MultiloginTarget(folder_id=FOLDER, profile_id=PROFILE),
        )

    def test_check_mlx_returns_10_when_logged_out(self):
        factory = MagicMock(return_value=_AsyncCM(SimpleNamespace(context=object())))
        with (
            patch.object(
                hupu_command, "async_playwright", lambda: _AsyncCM(object())
            ),
            patch.object(hupu_command, "browser_session", new=factory),
            patch.object(hupu_command, "is_logged_in", new=AsyncMock(return_value=False)),
        ):
            code, _, err = self._run(
                ["hupu", "check", "--folder-id", FOLDER, "--profile-id", PROFILE]
            )
        self.assertEqual(code, 10)
        self.assertIn("虎扑登录态无效", err)

    def test_check_mlx_returns_1_on_detection_error(self):
        factory = MagicMock(return_value=_AsyncCM(SimpleNamespace(context=object())))
        with (
            patch.object(
                hupu_command, "async_playwright", lambda: _AsyncCM(object())
            ),
            patch.object(hupu_command, "browser_session", new=factory),
            patch.object(
                hupu_command,
                "is_logged_in",
                new=AsyncMock(side_effect=RuntimeError("launcher down")),
            ),
        ):
            code, _, err = self._run(
                ["hupu", "check", "--folder-id", FOLDER, "--profile-id", PROFILE]
            )
        self.assertEqual(code, 1)
        self.assertIn("launcher down", err)

    def test_check_mlx_missing_flags_returns_2(self):
        code, _, _ = self._run(["hupu", "check"])
        self.assertEqual(code, 2)

    def test_check_local_uses_legacy_cookie_auth(self):
        with (
            patch.object(
                hupu_command, "check_hupu_account", new=AsyncMock(return_value=True)
            ) as legacy,
            patch.object(hupu_command, "browser_session", new=MagicMock()) as factory,
        ):
            code, out, _ = self._run(
                ["hupu", "check", "--account", "creator"], token=""
            )
        self.assertEqual(code, 0)
        self.assertIn("valid", out)
        legacy.assert_awaited_once_with("creator")
        factory.assert_not_called()

    def test_check_local_invalid_returns_1(self):
        with patch.object(
            hupu_command, "check_hupu_account", new=AsyncMock(return_value=False)
        ):
            code, out, _ = self._run(
                ["hupu", "check", "--account", "creator"], token=""
            )
        self.assertEqual(code, 1)
        self.assertIn("invalid", out)

    def test_upload_video_mlx_wires_one_session_and_probes_login_once(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video_file(tmp_dir)
            session = SimpleNamespace(context=object())
            session_cm = _AsyncCM(session)
            factory = MagicMock(return_value=session_cm)
            probe = AsyncMock(return_value=True)
            app = MagicMock()
            app.upload = AsyncMock()
            builder = MagicMock(return_value=app)

            with (
                patch.object(
                    hupu_command, "async_playwright", lambda: _AsyncCM(object())
                ),
                patch.object(hupu_command, "browser_session", new=factory),
                patch.object(hupu_command, "is_logged_in", new=probe),
                patch.object(hupu_command, "_build_uploader", new=builder),
            ):
                code, out, _ = self._run(
                    [
                        "hupu",
                        "upload-video",
                        "--folder-id",
                        FOLDER,
                        "--profile-id",
                        PROFILE,
                        "--file",
                        str(video),
                        "--title",
                        "测试标题",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertIn("Hupu video upload submitted", out)
        kwargs = factory.call_args.kwargs
        self.assertIsNone(kwargs["account_file"])
        self.assertEqual(
            kwargs["managed"].target,
            MultiloginTarget(folder_id=FOLDER, profile_id=PROFILE),
        )
        self.assertEqual(kwargs["launch_kwargs"], HUPU_LAUNCH_KWARGS)
        self.assertEqual(kwargs["context_kwargs"], HUPU_CONTEXT_KWARGS)
        self.assertFalse(kwargs["init_script"])
        self.assertIs(kwargs["context_setup"], prepare_local_context)
        probe.assert_awaited_once_with(session.context)
        app.upload.assert_awaited_once_with(session=session)
        self.assertIsNone(builder.call_args.args[1])
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_upload_video_mlx_logged_out_returns_10_and_skips_upload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video_file(tmp_dir)
            session_cm = _AsyncCM(SimpleNamespace(context=object()))
            with (
                patch.object(
                    hupu_command, "async_playwright", lambda: _AsyncCM(object())
                ),
                patch.object(
                    hupu_command,
                    "browser_session",
                    new=MagicMock(return_value=session_cm),
                ),
                patch.object(hupu_command, "is_logged_in", new=AsyncMock(return_value=False)),
                patch.object(HuPuVideo, "upload", new=AsyncMock()) as upload,
            ):
                code, out, _ = self._run(
                    [
                        "hupu",
                        "upload-video",
                        "--folder-id",
                        FOLDER,
                        "--profile-id",
                        PROFILE,
                        "--file",
                        str(video),
                        "--title",
                        "测试标题",
                    ]
                )
        self.assertEqual(code, 10)
        self.assertNotIn("submitted", out)
        upload.assert_not_awaited()
        self.assertEqual(session_cm.exit_calls, 1)

    def test_upload_video_mlx_failure_returns_1_and_exits_session(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video_file(tmp_dir)
            session_cm = _AsyncCM(SimpleNamespace(context=object()))
            with (
                patch.object(
                    hupu_command, "async_playwright", lambda: _AsyncCM(object())
                ),
                patch.object(
                    hupu_command,
                    "browser_session",
                    new=MagicMock(return_value=session_cm),
                ),
                patch.object(hupu_command, "is_logged_in", new=AsyncMock(return_value=True)),
                patch.object(
                    HuPuVideo, "upload", new=AsyncMock(side_effect=RuntimeError("publish failed"))
                ),
            ):
                code, _, err = self._run(
                    [
                        "hupu",
                        "upload-video",
                        "--folder-id",
                        FOLDER,
                        "--profile-id",
                        PROFILE,
                        "--file",
                        str(video),
                        "--title",
                        "测试标题",
                    ]
                )
        self.assertEqual(code, 1)
        self.assertIn("publish failed", err)
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_upload_video_local_stays_on_legacy_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video_file(tmp_dir)
            legacy = AsyncMock()
            factory = MagicMock()
            with (
                patch.object(hupu_command, "upload_hupu_video", new=legacy),
                patch.object(hupu_command, "browser_session", new=factory),
            ):
                code, out, _ = self._run(
                    [
                        "hupu",
                        "upload-video",
                        "--account",
                        "creator",
                        "--file",
                        str(video),
                        "--title",
                        "测试标题",
                    ],
                    token="",
                )
        self.assertEqual(code, 0)
        self.assertIn("Hupu video upload submitted", out)
        factory.assert_not_called()
        self.assertIsNone(legacy.await_args.kwargs.get("target"))

    def test_local_upload_hupu_video_uses_session_with_local_setup(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video_file(tmp_dir)
            account = Path(tmp_dir) / "cookies" / "hupu_creator.json"
            session = SimpleNamespace(context=object())
            session_cm = _AsyncCM(session)
            factory = MagicMock(return_value=session_cm)
            app = MagicMock()
            app.upload = AsyncMock()
            builder = MagicMock(return_value=app)
            request = hupu_command.HupuVideoUploadRequest(
                account_name="creator",
                video_file=video,
                title="测试标题",
                description="",
                tags=[],
                headless=False,
            )
            with (
                patch.object(
                    hupu_command, "async_playwright", lambda: _AsyncCM(object())
                ),
                patch.object(hupu_command, "browser_session", new=factory),
                patch.object(
                    hupu_command, "hupu_setup", new=AsyncMock(return_value=True)
                ),
                patch.object(
                    hupu_command,
                    "resolve_account_file",
                    new=MagicMock(return_value=account),
                ),
                patch.object(hupu_command, "_build_uploader", new=builder),
            ):
                returned = asyncio.run(hupu_command.upload_hupu_video(request))

        self.assertEqual(returned, account)
        kwargs = factory.call_args.kwargs
        self.assertEqual(kwargs["account_file"], str(account))
        self.assertNotIn("multilogin", kwargs)
        self.assertEqual(kwargs["launch_kwargs"], HUPU_LAUNCH_KWARGS)
        self.assertEqual(kwargs["context_kwargs"], HUPU_CONTEXT_KWARGS)
        self.assertFalse(kwargs["init_script"])
        self.assertIs(kwargs["context_setup"], prepare_local_context)
        app.upload.assert_awaited_once_with(session=session)
        self.assertEqual(builder.call_args.args[1], str(account))

    def test_upload_mlx_stops_profile_exactly_once(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video_file(tmp_dir)
            playwright = FakePlaywright()
            context = FakeContext()
            browser = FakeBrowser([context], allow_new_context=False)
            playwright.chromium.queue_connect_browser(browser)
            client = FakeMultiloginClient()
            app = MagicMock()
            app.upload = AsyncMock()
            with (
                patch.dict(os.environ, {"MLX_API_TOKEN": TOKEN}),
                patch("sau_commands.browser.MultiloginClient", return_value=client),
                patch.object(
                    hupu_command, "async_playwright", lambda: _AsyncCM(playwright)
                ),
                patch.object(hupu_command, "is_logged_in", new=AsyncMock(return_value=True)),
                patch.object(hupu_command, "_build_uploader", new=MagicMock(return_value=app)),
            ):
                code, _, err = self._run(
                    [
                        "hupu",
                        "upload-video",
                        "--folder-id",
                        FOLDER,
                        "--profile-id",
                        PROFILE,
                        "--file",
                        str(video),
                        "--title",
                        "测试标题",
                    ]
                )
        self.assertEqual(code, 0, err)
        self.assertEqual(client.stop_calls, [PROFILE])
        self.assertTrue(browser.closed)


class DayuLocalGoldenTests(unittest.TestCase):
    def test_golden_constants_match_legacy_options(self):
        self.assertEqual(
            DAYU_LAUNCH_KWARGS,
            {"executable_path": LOCAL_CHROME_PATH or None, "channel": "chrome"},
        )
        self.assertEqual(DAYU_CONTEXT_KWARGS, {"timezone_id": "Asia/Shanghai"})
        self.assertFalse(DAYU_INIT_SCRIPT)

    def test_video_local_launch_context_timezone_and_teardown(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            account = Path(tmp_dir) / "dayu_account.json"
            account.write_text("{}", encoding="utf-8")
            app = DayuVideo(
                title="测试标题",
                file_path="demo.mp4",
                tags=[],
                account_file=str(account),
                thumbnail_path="cover.png",
                category="其他",
                source="无需标注",
                headless=False,
            )
            app.validate_upload_args = MagicMock()
            app.upload_in = AsyncMock(return_value={"success": True})
            playwright = FakePlaywright()
            with patch.object(dayu_main_module, "async_playwright", lambda: _AsyncCM(playwright)):
                result = asyncio.run(app.main())

        self.assertEqual(result, {"success": True})
        self.assertEqual(
            playwright.chromium.launch_calls,
            [{"headless": False, **DAYU_LAUNCH_KWARGS}],
        )
        browser = playwright.chromium.launch_browser
        self.assertEqual(
            browser.new_context_calls,
            [{"storage_state": str(account.resolve()), **DAYU_CONTEXT_KWARGS}],
        )
        context = browser.contexts[0]
        self.assertEqual(context.storage_state_calls, [str(account.resolve())])
        self.assertEqual(context.add_init_script_calls, [])
        self.assertTrue(context.closed)
        self.assertTrue(browser.closed)
        session = app.upload_in.await_args.args[0]
        self.assertEqual(session.mode, "local")
        self.assertIs(session.context, context)

    def test_article_local_launch_context_timezone_and_teardown(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            account = Path(tmp_dir) / "dayu_account.json"
            account.write_text("{}", encoding="utf-8")
            article = _make_article_file(tmp_dir)
            app = DayuArticle(
                title="测试图文标题",
                content_file=str(article),
                account_file=str(account),
                source="无需标注",
                headless=True,
            )
            app.validate_upload_args = MagicMock()
            app.upload_in = AsyncMock(return_value={"success": True})
            playwright = FakePlaywright()
            with patch.object(dayu_article_module, "async_playwright", lambda: _AsyncCM(playwright)):
                result = asyncio.run(app.main())

        self.assertEqual(result, {"success": True})
        self.assertEqual(
            playwright.chromium.launch_calls,
            [{"headless": True, **DAYU_LAUNCH_KWARGS}],
        )
        browser = playwright.chromium.launch_browser
        self.assertEqual(
            browser.new_context_calls,
            [{"storage_state": str(account.resolve()), **DAYU_CONTEXT_KWARGS}],
        )
        context = browser.contexts[0]
        self.assertEqual(context.storage_state_calls, [str(account.resolve())])
        self.assertTrue(browser.closed)


class DayuLoginDetectionTests(unittest.TestCase):
    def test_header_name_returns_true(self):
        page = _LoginPage(
            final_url="https://mp.dayu.com/dashboard/index",
            name_count=1,
            name_text="测试账号",
        )
        self.assertTrue(asyncio.run(dayu_is_logged_in(_LoginContext(page))))
        self.assertEqual(page.goto_calls[0][0], dayu_session.DAYU_HOME_URL)
        self.assertEqual(page.settle_calls, [dayu_session.DAYU_LOGIN_CHECK_SETTLE_MS])
        self.assertTrue(page.closed)

    def test_login_iframe_returns_false(self):
        page = _LoginPage(
            final_url="https://mp.dayu.com/dashboard/index",
            login_iframe_count=1,
            name_count=1,
            name_text="测试账号",
        )
        self.assertFalse(asyncio.run(dayu_is_logged_in(_LoginContext(page))))

    def test_login_url_returns_false(self):
        page = _LoginPage(final_url="https://mp.dayu.com/login?redirect=x")
        self.assertFalse(asyncio.run(dayu_is_logged_in(_LoginContext(page))))

    def test_no_positive_signal_raises(self):
        page = _LoginPage(final_url="https://mp.dayu.com/dashboard/index")
        with self.assertRaisesRegex(RuntimeError, "页面结构异常"):
            asyncio.run(dayu_is_logged_in(_LoginContext(page)))
        self.assertTrue(page.closed)

    def test_http_5xx_raises(self):
        page = _LoginPage(
            final_url="https://mp.dayu.com/dashboard/index", status=500
        )
        with self.assertRaisesRegex(RuntimeError, "HTTP 500"):
            asyncio.run(dayu_is_logged_in(_LoginContext(page)))

    def test_unexpected_host_raises(self):
        page = _LoginPage(final_url="https://example.com/login")
        with self.assertRaisesRegex(RuntimeError, "大鱼号"):
            asyncio.run(dayu_is_logged_in(_LoginContext(page)))

    def test_navigation_error_raises(self):
        page = _LoginPage(
            final_url="https://mp.dayu.com/dashboard/index",
            goto_error=TimeoutError("nav timeout"),
        )
        with self.assertRaises(TimeoutError):
            asyncio.run(dayu_is_logged_in(_LoginContext(page)))


class _DayuPage:
    def __init__(self, url: str = "https://mp.dayu.com/dashboard/video/write") -> None:
        self.url = "about:blank"
        self.final_url = url
        self.goto_calls: list[tuple[str, dict]] = []
        self.file_upload = _CountLocator(1)
        self.login_iframe = _CountLocator(0)
        self.screenshots: list[str] = []

    async def goto(self, url: str, **kwargs):
        self.goto_calls.append((url, kwargs))
        self.url = self.final_url
        return SimpleNamespace(status=200)

    def locator(self, selector: str):
        if 'input[type="file"][name="file"]' in selector:
            return self.file_upload
        if "uop.dayu.com/cas" in selector:
            return self.login_iframe
        return _CountLocator(0)

    async def screenshot(self, *, path=None, **kwargs) -> None:
        self.screenshots.append(path)

    async def close(self) -> None:
        pass


class _DayuContext:
    def __init__(self, page: _DayuPage) -> None:
        self.page = page
        self.new_page_calls = 0

    async def new_page(self) -> _DayuPage:
        self.new_page_calls += 1
        return self.page

    async def storage_state(self, **kwargs):
        raise AssertionError("MLX must not write storage state")


class DayuMultiloginUploaderTests(unittest.TestCase):
    def _video_app(self) -> DayuVideo:
        app = DayuVideo(
            title="测试标题",
            file_path="demo.mp4",
            tags=[],
            account_file=None,
            thumbnail_path="cover.png",
            category="其他",
            source="无需标注",
        )
        app.file_path = Path("demo.mp4")
        return app

    def test_video_main_mlx_skips_identity_validation(self):
        app = self._video_app()
        app.validate_upload_args = MagicMock()
        app.upload_in = AsyncMock(return_value={"success": True})
        session = BrowserSession(browser=MagicMock(), context=MagicMock(), mode="multilogin")
        with patch.object(dayu_main_module, "async_playwright", MagicMock()) as async_playwright:
            result = asyncio.run(app.main(session=session))
        self.assertEqual(result, {"success": True})
        async_playwright.assert_not_called()
        app.validate_upload_args.assert_called_once_with(check_identity=False)
        app.upload_in.assert_awaited_once_with(session)

    def test_video_upload_in_mlx_never_reads_identity_or_cookie(self):
        app = self._video_app()
        app.schedule = None
        page = _DayuPage()
        context = _DayuContext(page)
        session = BrowserSession(browser=MagicMock(), context=context, mode="multilogin")

        async def fake_submit(page_, result, result_file, **kwargs):
            result["content_id"] = "123"
            result["success"] = True

        fake_expect = MagicMock()
        fake_expect.return_value.to_have_count = AsyncMock()

        with (
            patch.object(dayu_main_module, "wait_dayu_processing", new=AsyncMock()) as wait,
            patch.object(
                dayu_main_module, "submit_dayu_publication", new=AsyncMock(side_effect=fake_submit)
            ) as submit,
            patch.object(dayu_main_module, "read_dayu_identity", new=AsyncMock()) as read_identity,
            patch.object(dayu_main_module, "load_dayu_identity", new=AsyncMock()) as load_identity,
            patch.object(DayuVideo, "fill_video_form", new=AsyncMock()) as fill_form,
            patch.object(dayu_main_module, "expect", new=fake_expect),
            patch.object(dayu_main_module, "dayu_logger", MagicMock()),
        ):
            result = asyncio.run(app.upload_in(session))

        self.assertTrue(result["success"])
        self.assertEqual(result["content_id"], "123")
        self.assertIsNone(result["identity"])
        read_identity.assert_not_awaited()
        load_identity.assert_not_called()
        wait.assert_awaited()
        fill_form.assert_awaited_once_with(page)
        submit.assert_awaited_once()
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(page.file_upload.files, "demo.mp4")

    def test_video_upload_in_mlx_login_redirect_raises_before_identity(self):
        app = self._video_app()
        app.schedule = None
        page = _DayuPage(url="https://uop.dayu.com/cas/login")
        context = _DayuContext(page)
        session = BrowserSession(browser=MagicMock(), context=context, mode="multilogin")
        with (
            patch.object(dayu_main_module, "read_dayu_identity", new=AsyncMock()) as read_identity,
            patch.object(dayu_main_module, "load_dayu_identity", new=AsyncMock()) as load_identity,
        ):
            with self.assertRaises(LoginRequiredError):
                asyncio.run(app.upload_in(session))
        read_identity.assert_not_awaited()
        load_identity.assert_not_called()

    def test_article_fill_body_skips_grant_permissions_in_mlx(self):
        class _Stop(Exception):
            pass

        class _GrantContext:
            def __init__(self) -> None:
                self.grant_calls = 0

            async def grant_permissions(self, *args, **kwargs):
                self.grant_calls += 1

        class _ArticlePage:
            def __init__(self) -> None:
                self.context = _GrantContext()

            async def evaluate(self, *args, **kwargs):
                raise _Stop

        app = DayuArticle(
            title="测试图文标题",
            content_file="article.html",
            account_file=None,
            source="无需标注",
        )
        app.document = SimpleNamespace(parts=["<p>正文</p>"], text=["正文"], images=[])
        page = _ArticlePage()
        with self.assertRaises(_Stop):
            asyncio.run(app.fill_article_body(page, multilogin=True))
        self.assertEqual(page.context.grant_calls, 0)

        local_page = _ArticlePage()
        with self.assertRaises(_Stop):
            asyncio.run(app.fill_article_body(local_page, multilogin=False))
        self.assertEqual(local_page.context.grant_calls, 1)

    def test_article_upload_in_mlx_skips_identity_and_cookie(self):
        app = DayuArticle(
            title="测试图文标题",
            content_file="article.html",
            account_file=None,
            source="无需标注",
        )
        app.document = SimpleNamespace(
            manifest={}, source_format="html", theme=None, images=[]
        )
        app.style_result = {"mode": "native"}
        app.publication_html = None
        page = _DayuPage(url="https://mp.dayu.com/dashboard/article/write")
        context = _DayuContext(page)
        session = BrowserSession(browser=MagicMock(), context=context, mode="multilogin")

        async def fake_submit(page_, result, result_file, **kwargs):
            result["content_id"] = "456"
            result["success"] = True

        with (
            patch.object(DayuArticle, "fill_article_form", new=AsyncMock()) as fill_form,
            patch.object(
                dayu_article_module, "submit_dayu_publication", new=AsyncMock(side_effect=fake_submit)
            ),
            patch.object(dayu_article_module, "read_dayu_identity", new=AsyncMock()) as read_identity,
            patch.object(dayu_article_module, "load_dayu_identity", new=AsyncMock()) as load_identity,
            patch.object(dayu_article_module, "dayu_logger", MagicMock()),
        ):
            result = asyncio.run(app.upload_in(session))

        self.assertTrue(result["success"])
        self.assertTrue(result["identity"] is None)
        read_identity.assert_not_awaited()
        load_identity.assert_not_called()
        fill_form.assert_awaited_once_with(page, multilogin=True)
        self.assertEqual(context.new_page_calls, 1)


class DayuCliTests(unittest.TestCase):
    def _run(self, argv, token=TOKEN):
        with patch.dict(os.environ, {"MLX_API_TOKEN": token}):
            with redirect_stdout(io.StringIO()) as out, redirect_stderr(
                io.StringIO()
            ) as err:
                code = sau_cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def _fake_app(self):
        app = MagicMock()
        app.main = AsyncMock(return_value={"success": True, "content_id": "123"})
        return app

    def test_check_mlx_returns_0_and_logs_identity_not_verified(self):
        factory = MagicMock(return_value=_AsyncCM(SimpleNamespace(context=object())))
        logger = MagicMock()
        with (
            patch.object(dayu_command, "async_playwright", lambda: _AsyncCM(object())),
            patch.object(dayu_command, "browser_session", new=factory),
            patch.object(dayu_command, "is_logged_in", new=AsyncMock(return_value=True)),
            patch.object(dayu_command, "dayu_logger", new=logger),
        ):
            code, out, _ = self._run(
                ["dayu", "check", "--folder-id", FOLDER, "--profile-id", PROFILE]
            )
        self.assertEqual(code, 0)
        self.assertIn("valid", out)
        self.assertIsNone(factory.call_args.kwargs["account_file"])
        logger.info.assert_called_once_with(
            "账号一致性未校验：以 Multilogin Profile 为身份（profile_id={}）",
            PROFILE,
        )

    def test_check_mlx_returns_10_when_logged_out(self):
        with (
            patch.object(dayu_command, "async_playwright", lambda: _AsyncCM(object())),
            patch.object(
                dayu_command,
                "browser_session",
                new=MagicMock(return_value=_AsyncCM(SimpleNamespace(context=object()))),
            ),
            patch.object(dayu_command, "is_logged_in", new=AsyncMock(return_value=False)),
        ):
            code, _, err = self._run(
                ["dayu", "check", "--folder-id", FOLDER, "--profile-id", PROFILE]
            )
        self.assertEqual(code, 10)
        self.assertIn("大鱼号登录态无效", err)

    def test_check_mlx_returns_1_on_detection_error(self):
        with (
            patch.object(dayu_command, "async_playwright", lambda: _AsyncCM(object())),
            patch.object(
                dayu_command,
                "browser_session",
                new=MagicMock(return_value=_AsyncCM(SimpleNamespace(context=object()))),
            ),
            patch.object(
                dayu_command,
                "is_logged_in",
                new=AsyncMock(side_effect=RuntimeError("launcher down")),
            ),
        ):
            code, _, err = self._run(
                ["dayu", "check", "--folder-id", FOLDER, "--profile-id", PROFILE]
            )
        self.assertEqual(code, 1)
        self.assertIn("launcher down", err)

    def test_check_mlx_missing_flags_returns_2(self):
        code, _, _ = self._run(["dayu", "check"])
        self.assertEqual(code, 2)

    def test_check_local_uses_legacy_account_check(self):
        with (
            patch.object(
                dayu_command, "check_dayu_account", new=AsyncMock(return_value=True)
            ) as legacy,
            patch.object(dayu_command, "browser_session", new=MagicMock()) as factory,
            patch.object(
                dayu_command, "resolve_account_file", new=MagicMock(return_value=Path("/tmp/x"))
            ),
        ):
            code, out, _ = self._run(
                ["dayu", "check", "--account", "creator"], token=""
            )
        self.assertEqual(code, 0)
        self.assertIn("valid", out)
        legacy.assert_awaited_once_with(Path("/tmp/x"))
        factory.assert_not_called()

    def test_check_local_invalid_returns_1(self):
        with (
            patch.object(
                dayu_command, "check_dayu_account", new=AsyncMock(return_value=False)
            ),
            patch.object(
                dayu_command, "resolve_account_file", new=MagicMock(return_value=Path("/tmp/x"))
            ),
        ):
            code, out, _ = self._run(
                ["dayu", "check", "--account", "creator"], token=""
            )
        self.assertEqual(code, 1)
        self.assertIn("invalid", out)

    def test_upload_video_mlx_passes_none_account_session_and_logs_identity(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video_file(tmp_dir)
            session = SimpleNamespace(context=object())
            session_cm = _AsyncCM(session)
            factory = MagicMock(return_value=session_cm)
            probe = AsyncMock(return_value=True)
            app = self._fake_app()
            builder = MagicMock(return_value=app)

            with (
                patch.object(dayu_command, "async_playwright", lambda: _AsyncCM(object())),
                patch.object(dayu_command, "browser_session", new=factory),
                patch.object(dayu_command, "is_logged_in", new=probe),
                patch.object(dayu_command, "DayuVideo", new=builder),
                patch.object(dayu_command, "dayu_logger", MagicMock()) as logger,
            ):
                code, _, err = self._run(
                    [
                        "dayu",
                        "upload-video",
                        "--folder-id",
                        FOLDER,
                        "--profile-id",
                        PROFILE,
                        "--file",
                        str(video),
                        "--title",
                        "测试标题",
                        "--category",
                        "其他",
                        "--source",
                        "无需标注",
                        "--thumbnail",
                        str(video),
                    ]
                )

        self.assertEqual(code, 0, err)
        kwargs = factory.call_args.kwargs
        self.assertIsNone(kwargs["account_file"])
        self.assertEqual(
            kwargs["managed"].target,
            MultiloginTarget(folder_id=FOLDER, profile_id=PROFILE),
        )
        self.assertEqual(kwargs["launch_kwargs"], DAYU_LAUNCH_KWARGS)
        self.assertEqual(kwargs["context_kwargs"], DAYU_CONTEXT_KWARGS)
        self.assertFalse(kwargs["init_script"])
        probe.assert_awaited_once_with(session.context)
        self.assertIsNone(builder.call_args.kwargs["account_file"])
        app.main.assert_awaited_once_with(session=session)
        logger.info.assert_any_call(
            "账号一致性未校验：以 Multilogin Profile 为身份（profile_id={}）",
            PROFILE,
        )
        logger.info.assert_any_call(
            "Multilogin 模式不写入时区；建议在 Profile 设置中将时区设为 Asia/Shanghai"
        )
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_upload_article_mlx_logs_identity_and_skips_local_account(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            article = _make_article_file(tmp_dir)
            session = SimpleNamespace(context=object())
            session_cm = _AsyncCM(session)
            factory = MagicMock(return_value=session_cm)
            app = self._fake_app()
            builder = MagicMock(return_value=app)
            resolve_account = MagicMock()

            with (
                patch.object(dayu_command, "async_playwright", lambda: _AsyncCM(object())),
                patch.object(dayu_command, "browser_session", new=factory),
                patch.object(dayu_command, "is_logged_in", new=AsyncMock(return_value=True)),
                patch.object(dayu_command, "DayuArticle", new=builder),
                patch.object(dayu_command, "resolve_account_file", new=resolve_account),
                patch.object(dayu_command, "dayu_logger", MagicMock()) as logger,
            ):
                code, _, err = self._run(
                    [
                        "dayu",
                        "upload-article",
                        "--folder-id",
                        FOLDER,
                        "--profile-id",
                        PROFILE,
                        "--title",
                        "测试图文标题",
                        "--content-file",
                        str(article),
                        "--source",
                        "无需标注",
                    ]
                )

        self.assertEqual(code, 0, err)
        resolve_account.assert_not_called()
        self.assertIsNone(builder.call_args.kwargs["account_file"])
        app.main.assert_awaited_once_with(session=session)
        logger.info.assert_any_call(
            "账号一致性未校验：以 Multilogin Profile 为身份（profile_id={}）",
            PROFILE,
        )

    def test_upload_video_mlx_logged_out_returns_10_and_skips_upload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video_file(tmp_dir)
            app = self._fake_app()
            session_cm = _AsyncCM(SimpleNamespace(context=object()))
            with (
                patch.object(dayu_command, "async_playwright", lambda: _AsyncCM(object())),
                patch.object(
                    dayu_command, "browser_session", new=MagicMock(return_value=session_cm)
                ),
                patch.object(dayu_command, "is_logged_in", new=AsyncMock(return_value=False)),
                patch.object(dayu_command, "DayuVideo", new=MagicMock(return_value=app)),
            ):
                code, _, err = self._run(
                    [
                        "dayu",
                        "upload-video",
                        "--folder-id",
                        FOLDER,
                        "--profile-id",
                        PROFILE,
                        "--file",
                        str(video),
                        "--title",
                        "测试标题",
                        "--category",
                        "其他",
                        "--source",
                        "无需标注",
                        "--thumbnail",
                        str(video),
                    ]
                )
        self.assertEqual(code, 10)
        self.assertIn("大鱼号登录态无效", err)
        app.main.assert_not_awaited()
        self.assertEqual(session_cm.exit_calls, 1)

    def test_upload_video_mlx_failure_returns_1(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video_file(tmp_dir)
            app = MagicMock()
            app.main = AsyncMock(side_effect=RuntimeError("publish failed"))
            session_cm = _AsyncCM(SimpleNamespace(context=object()))
            with (
                patch.object(dayu_command, "async_playwright", lambda: _AsyncCM(object())),
                patch.object(
                    dayu_command, "browser_session", new=MagicMock(return_value=session_cm)
                ),
                patch.object(dayu_command, "is_logged_in", new=AsyncMock(return_value=True)),
                patch.object(dayu_command, "DayuVideo", new=MagicMock(return_value=app)),
                patch.object(dayu_command, "dayu_logger", MagicMock()),
            ):
                code, _, err = self._run(
                    [
                        "dayu",
                        "upload-video",
                        "--folder-id",
                        FOLDER,
                        "--profile-id",
                        PROFILE,
                        "--file",
                        str(video),
                        "--title",
                        "测试标题",
                        "--category",
                        "其他",
                        "--source",
                        "无需标注",
                        "--thumbnail",
                        str(video),
                    ]
                )
        self.assertEqual(code, 1)
        self.assertIn("publish failed", err)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_upload_video_local_stays_on_legacy_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video_file(tmp_dir)
            app = self._fake_app()
            builder = MagicMock(return_value=app)
            with (
                patch.object(dayu_command, "DayuVideo", new=builder),
                patch.object(dayu_command, "browser_session", new=MagicMock()) as factory,
                patch.object(
                    dayu_command, "resolve_account_file", new=MagicMock(return_value=Path("/tmp/x"))
                ),
            ):
                code, _, err = self._run(
                    [
                        "dayu",
                        "upload-video",
                        "--account",
                        "creator",
                        "--file",
                        str(video),
                        "--title",
                        "测试标题",
                        "--category",
                        "其他",
                        "--source",
                        "无需标注",
                        "--thumbnail",
                        str(video),
                    ],
                    token="",
                )
        self.assertEqual(code, 0, err)
        factory.assert_not_called()
        app.main.assert_awaited_once_with()

    def test_upload_mlx_stops_profile_exactly_once(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video_file(tmp_dir)
            playwright = FakePlaywright()
            context = FakeContext()
            browser = FakeBrowser([context], allow_new_context=False)
            playwright.chromium.queue_connect_browser(browser)
            client = FakeMultiloginClient()
            app = self._fake_app()
            with (
                patch.dict(os.environ, {"MLX_API_TOKEN": TOKEN}),
                patch("sau_commands.browser.MultiloginClient", return_value=client),
                patch.object(
                    dayu_command, "async_playwright", lambda: _AsyncCM(playwright)
                ),
                patch.object(dayu_command, "is_logged_in", new=AsyncMock(return_value=True)),
                patch.object(dayu_command, "DayuVideo", new=MagicMock(return_value=app)),
                patch.object(dayu_command, "dayu_logger", MagicMock()),
            ):
                code, _, err = self._run(
                    [
                        "dayu",
                        "upload-video",
                        "--folder-id",
                        FOLDER,
                        "--profile-id",
                        PROFILE,
                        "--file",
                        str(video),
                        "--title",
                        "测试标题",
                        "--category",
                        "其他",
                        "--source",
                        "无需标注",
                        "--thumbnail",
                        str(video),
                    ]
                )
        self.assertEqual(code, 0, err)
        self.assertEqual(client.stop_calls, [PROFILE])
        self.assertTrue(browser.closed)


if __name__ == "__main__":
    unittest.main()
