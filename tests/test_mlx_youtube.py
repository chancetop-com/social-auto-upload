# -*- coding: utf-8 -*-
"""YouTube uploader seam + Multilogin CLI wiring (ticket 22).

Local mode must stay behaviour-equivalent (channel chrome, proxy from
``YT_PROXY``, init script on).  The Multilogin branch is a pure consumer of the
injected ``BrowserSession``: it never launches, never creates a context, never
injects the init script, never reads/writes cookies, and never closes a browser
it does not own.
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
from sau_commands import youtube as youtube_command
from tests.fakes import FakePlaywright
from uploader.youtube_uploader import main as youtube_main
from uploader.youtube_uploader.main import (
    STUDIO_URL,
    UPLOAD_URL,
    YOUTUBE_CONTEXT_KWARGS,
    YOUTUBE_INIT_SCRIPT,
    YOUTUBE_LAUNCH_KWARGS,
    YouTubeVideo,
    is_logged_in,
)
from utils.browser_session import BrowserSession
from utils.errors import LoginRequiredError

TOKEN = "SENTINEL-MLX-TOKEN-ticket22"


class _Response:
    def __init__(self, status: int = 200) -> None:
        self.status = status


class _LoginPage:
    def __init__(
        self,
        *,
        final_url: str,
        status: int = 200,
        goto_error: BaseException | None = None,
    ) -> None:
        self.url = "about:blank"
        self.final_url = final_url
        self.status = status
        self.goto_error = goto_error
        self.goto_calls: list[tuple[str, dict]] = []
        self.wait_timeouts: list[int] = []
        self.close_calls = 0

    async def goto(self, url: str, **kwargs):
        self.goto_calls.append((url, kwargs))
        if self.goto_error is not None:
            raise self.goto_error
        self.url = self.final_url
        return _Response(self.status)

    async def wait_for_timeout(self, ms: int) -> None:
        self.wait_timeouts.append(ms)

    async def close(self) -> None:
        self.close_calls += 1


class _LoginContext:
    def __init__(self, page: _LoginPage) -> None:
        self.page = page
        self.new_page_calls = 0

    async def new_page(self) -> _LoginPage:
        self.new_page_calls += 1
        return self.page


class IsLoggedInTests(unittest.TestCase):
    def _probe(self, page: _LoginPage) -> bool:
        context = _LoginContext(page)
        result = asyncio.run(is_logged_in(context))
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(page.close_calls, 1)
        return result

    def test_logged_in_uses_studio_anchor_and_channel_path(self):
        page = _LoginPage(final_url="https://studio.youtube.com/channel/UC123/videos?o=U")
        self.assertTrue(self._probe(page))
        self.assertEqual(page.goto_calls[0][0], STUDIO_URL)
        timeout = page.goto_calls[0][1]["timeout"]
        self.assertGreaterEqual(timeout, 15_000)
        self.assertLessEqual(timeout, 30_000)

    def test_explicit_login_consent_and_account_chooser_return_false(self):
        urls = [
            "https://accounts.google.com/v3/signin/identifier?continue=https%3A%2F%2Fstudio.youtube.com",
            "https://consent.youtube.com/m?continue=https%3A%2F%2Fstudio.youtube.com",
            "https://accounts.google.com/gsi/accountchooser?client_id=yt",
            "https://www.youtube.com/signin?action_handle_signin=true",
        ]
        for url in urls:
            with self.subTest(url=url):
                page = _LoginPage(final_url=url)
                self.assertFalse(self._probe(page))

    def test_network_error_propagates(self):
        page = _LoginPage(
            final_url="https://studio.youtube.com/channel/UC123",
            goto_error=RuntimeError("net::ERR_CONNECTION_RESET"),
        )
        with self.assertRaises(RuntimeError):
            self._probe(page)

    def test_timeout_propagates(self):
        page = _LoginPage(
            final_url="https://studio.youtube.com/channel/UC123",
            goto_error=TimeoutError("page.goto: Timeout 20000ms exceeded"),
        )
        with self.assertRaises(TimeoutError):
            self._probe(page)

    def test_server_error_propagates(self):
        page = _LoginPage(
            final_url="https://studio.youtube.com/channel/UC123",
            status=503,
        )
        with self.assertRaises(RuntimeError):
            self._probe(page)

    def test_unexpected_structure_propagates(self):
        urls = [
            "https://studio.youtube.com/",
            "https://example.com/channel/UC123",
            "",
        ]
        for url in urls:
            with self.subTest(url=url):
                page = _LoginPage(final_url=url)
                with self.assertRaises(RuntimeError):
                    self._probe(page)


class _RecordingPage:
    """Minimal page double for the uploader body."""

    def __init__(
        self,
        *,
        final_url: str = UPLOAD_URL,
        transition_url: str | None = None,
    ) -> None:
        self.url = "about:blank"
        self.final_url = final_url
        self.transition_url = transition_url
        self.goto_calls: list[tuple[str, dict]] = []
        self.wait_timeouts: list[int] = []
        self.default_timeout = None
        self.closed = False
        self._file_locator = _FileLocator(self)

    def locator(self, selector: str):
        return self._file_locator

    def set_default_timeout(self, ms: int) -> None:
        self.default_timeout = ms

    async def goto(self, url: str, **kwargs):
        self.goto_calls.append((url, kwargs))
        self.url = self.final_url

    async def wait_for_timeout(self, ms: int) -> None:
        self.wait_timeouts.append(ms)

    async def close(self) -> None:
        self.closed = True


class _FileLocator:
    def __init__(self, page: _RecordingPage) -> None:
        self.page = page
        self.first = self

    async def wait_for(self, *args, **kwargs) -> None:
        return None

    async def set_input_files(self, *args, **kwargs) -> None:
        if self.page.transition_url is not None:
            self.page.url = self.page.transition_url


class _RecordingContext:
    def __init__(self, page: _RecordingPage) -> None:
        self.page = page
        self.new_page_calls = 0
        self.storage_state_calls: list[object] = []
        self.add_init_script_calls = 0

    async def new_page(self) -> _RecordingPage:
        self.new_page_calls += 1
        return self.page

    async def storage_state(self, *, path=None, **kwargs):
        self.storage_state_calls.append(path)
        return {"cookies": []}

    async def add_init_script(self, *args, **kwargs) -> None:
        self.add_init_script_calls += 1


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


def _make_video(tmp_dir: str, account_file=None, **kwargs) -> YouTubeVideo:
    video_path = Path(tmp_dir) / "demo.mp4"
    if not video_path.exists():
        video_path.write_bytes(b"video")
    return YouTubeVideo("标题", str(video_path), [], account_file, **kwargs)


class LegacyLocalUploadTests(unittest.TestCase):
    """``session is None`` keeps the historical launch/context/init path."""

    def test_local_launch_context_and_init_script_are_golden(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, "/tmp/youtube-cookie.json", headless=False)
            page = _RecordingPage()
            upload_in = AsyncMock(return_value=page)
            video.upload_in = upload_in

            playwright = FakePlaywright()
            init_script = AsyncMock(side_effect=lambda context: context)

            with patch.object(youtube_main, "set_init_script", init_script):
                asyncio.run(video.upload(playwright))

        expected_proxy = {"server": youtube_main.YT_PROXY} if youtube_main.YT_PROXY else None
        self.assertEqual(
            YOUTUBE_LAUNCH_KWARGS,
            {"channel": "chrome", "proxy": expected_proxy},
        )
        self.assertEqual(YOUTUBE_CONTEXT_KWARGS, {})
        self.assertTrue(YOUTUBE_INIT_SCRIPT)
        self.assertEqual(
            playwright.chromium.launch_calls,
            [{"headless": False, **YOUTUBE_LAUNCH_KWARGS}],
        )

        browser = playwright.chromium.launch_browser
        self.assertEqual(
            browser.new_context_calls,
            [{"storage_state": "/tmp/youtube-cookie.json", **YOUTUBE_CONTEXT_KWARGS}],
        )

        context = browser.contexts[0]
        init_script.assert_awaited_once_with(context)
        upload_in.assert_awaited_once()
        session = upload_in.await_args.args[0]
        self.assertEqual(session.mode, "local")
        self.assertIs(session.context, context)

    def test_local_teardown_saves_cookie_then_closes_context_and_browser(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, "/tmp/youtube-cookie.json")
            page = _RecordingPage()
            video.upload_in = AsyncMock(return_value=page)

            playwright = FakePlaywright()
            with patch.object(
                youtube_main, "set_init_script", AsyncMock(side_effect=lambda c: c)
            ):
                asyncio.run(video.upload(playwright))

        browser = playwright.chromium.launch_browser
        context = browser.contexts[0]
        self.assertEqual(context.storage_state_calls, ["/tmp/youtube-cookie.json"])
        self.assertTrue(context.closed)
        self.assertTrue(browser.closed)
        self.assertEqual(playwright.events, ["launch", "context.close", "browser.close"])
        self.assertIn(2000, page.wait_timeouts)

    def test_local_upload_in_keeps_legacy_login_runtime_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, "/tmp/youtube-cookie.json")
            page = _RecordingPage(final_url="https://accounts.google.com/signin")
            context = _RecordingContext(page)
            session = BrowserSession(
                browser=MagicMock(), context=context, mode="local"
            )

            with self.assertRaises(RuntimeError) as caught:
                asyncio.run(video.upload_in(session))
            self.assertNotIsInstance(caught.exception, LoginRequiredError)

        self.assertIn("登录态失效", str(caught.exception))


class MultiloginUploadTests(unittest.TestCase):
    """``session is not None`` is a pure consumer of the injected session."""

    def test_mlx_upload_uses_injected_context_only(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, account_file=None)
            page_ops = AsyncMock()
            video._upload_video_on_page = page_ops

            page = _RecordingPage()
            context = _RecordingContext(page)
            browser = MagicMock()
            session = BrowserSession(
                browser=browser, context=context, mode="multilogin"
            )

            with (
                patch.object(youtube_main, "async_playwright", MagicMock()) as async_playwright,
                patch.object(youtube_main, "set_init_script", AsyncMock()) as init_script,
            ):
                asyncio.run(video.upload(None, session=session))

        async_playwright.assert_not_called()
        init_script.assert_not_awaited()
        browser.close.assert_not_called()
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, 0)
        self.assertEqual(page.goto_calls[0][0], UPLOAD_URL)
        page_ops.assert_awaited_once_with(page, multilogin=True)
        self.assertIsNone(video.account_file)

    def test_mlx_mid_upload_login_captcha_and_2fa_raise_login_required(self):
        urls = [
            "https://accounts.google.com/v3/signin/identifier?continue=x",
            "https://www.youtube.com/captcha?next=%2Fupload",
            "https://accounts.google.com/signin/v2/challenge/ipp?x=1",
        ]
        for url in urls:
            with self.subTest(url=url):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    video = _make_video(tmp_dir, account_file=None)
                    page = _RecordingPage(transition_url=url)
                    context = _RecordingContext(page)
                    session = BrowserSession(
                        browser=MagicMock(), context=context, mode="multilogin"
                    )

                    with self.assertRaises(LoginRequiredError):
                        asyncio.run(video.upload(None, session=session))

                self.assertEqual(page.url, url)
                self.assertEqual(context.storage_state_calls, [])

    def test_wrapper_with_session_does_not_open_a_second_playwright(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, account_file=None)
            video.upload = AsyncMock()
            session = BrowserSession(
                browser=MagicMock(), context=MagicMock(), mode="multilogin"
            )

            with patch.object(
                youtube_main, "async_playwright", MagicMock()
            ) as async_playwright:
                asyncio.run(video.main(session=session))

        async_playwright.assert_not_called()
        video.upload.assert_awaited_once_with(None, session=session)

    def test_wrapper_without_session_keeps_legacy_playwright(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, "/tmp/cookie.json")
            video.upload = AsyncMock()

            with patch.object(
                youtube_main, "async_playwright", MagicMock()
            ) as async_playwright:
                playwright_cm = _AsyncCM(object())
                async_playwright.return_value = playwright_cm
                asyncio.run(video.main())

        self.assertEqual(playwright_cm.enter_calls, 1)
        self.assertEqual(playwright_cm.exit_calls, 1)
        video.upload.assert_awaited_once()


class YouTubeMlxCliTests(unittest.TestCase):
    def _run(self, argv, token=TOKEN):
        with patch.dict(os.environ, {"MLX_API_TOKEN": token}):
            with redirect_stdout(io.StringIO()) as out, redirect_stderr(
                io.StringIO()
            ) as err:
                code = sau_cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_check_logged_in_returns_0_and_enters_session_once(self):
        playwright_cm = _AsyncCM(object())
        session = Namespace(context=object())
        session_cm = _AsyncCM(session)
        probe = AsyncMock(return_value=True)

        with (
            patch.object(youtube_command, "async_playwright", lambda: playwright_cm),
            patch.object(
                youtube_command, "browser_session", new=MagicMock(return_value=session_cm)
            ),
            patch.object(youtube_command, "is_logged_in", new=probe),
        ):
            code, out, _ = self._run(
                [
                    "youtube",
                    "check",
                    "--folder-id",
                    "folder",
                    "--profile-id",
                    "profile",
                ]
            )

        self.assertEqual(code, 0)
        self.assertIn("valid", out)
        self.assertEqual(playwright_cm.enter_calls, 1)
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)
        probe.assert_awaited_once_with(session.context)

    def test_check_logged_out_returns_10(self):
        playwright_cm = _AsyncCM(object())
        session_cm = _AsyncCM(Namespace(context=object()))

        with (
            patch.object(youtube_command, "async_playwright", lambda: playwright_cm),
            patch.object(
                youtube_command, "browser_session", new=MagicMock(return_value=session_cm)
            ),
            patch.object(
                youtube_command, "is_logged_in", new=AsyncMock(return_value=False)
            ),
        ):
            code, out, _ = self._run(
                [
                    "youtube",
                    "check",
                    "--folder-id",
                    "folder",
                    "--profile-id",
                    "profile",
                ]
            )

        self.assertEqual(code, 10)
        self.assertNotIn("valid", out)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_check_probe_error_returns_1_and_still_exits_session_once(self):
        playwright_cm = _AsyncCM(object())
        session_cm = _AsyncCM(Namespace(context=object()))

        with (
            patch.object(youtube_command, "async_playwright", lambda: playwright_cm),
            patch.object(
                youtube_command, "browser_session", new=MagicMock(return_value=session_cm)
            ),
            patch.object(
                youtube_command,
                "is_logged_in",
                new=AsyncMock(side_effect=RuntimeError("page failed")),
            ),
        ):
            code, _, _ = self._run(
                [
                    "youtube",
                    "check",
                    "--folder-id",
                    "folder",
                    "--profile-id",
                    "profile",
                ]
            )

        self.assertEqual(code, 1)
        self.assertEqual(session_cm.exit_calls, 1)
        self.assertIsNotNone(session_cm.last_exc[1])

    def test_check_missing_ids_exits_2_without_browser(self):
        session_factory = MagicMock()

        with patch.object(youtube_command, "browser_session", new=session_factory):
            code, _, _ = self._run(["youtube", "check", "--account", "creator"])

        self.assertEqual(code, 2)
        session_factory.assert_not_called()

    def test_local_mode_keeps_legacy_check(self):
        with (
            patch.object(
                youtube_command,
                "check_youtube_account",
                new=AsyncMock(return_value=True),
            ),
            patch.object(youtube_command, "browser_session", new=MagicMock()) as session_factory,
        ):
            code, out, _ = self._run(
                ["youtube", "check", "--account", "creator"], token=""
            )

        self.assertEqual(code, 0)
        self.assertIn("valid", out)
        session_factory.assert_not_called()

    def test_upload_mlx_success_passes_none_account_and_one_session(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            playwright_cm = _AsyncCM(object())
            session = Namespace(context=object())
            session_cm = _AsyncCM(session)
            session_factory = MagicMock(return_value=session_cm)
            probe = AsyncMock(return_value=True)
            resolve_account = MagicMock()
            setup = AsyncMock()
            fake_app = MagicMock()
            fake_app.main = AsyncMock()
            fake_app.set_publish_date = MagicMock()
            builder = MagicMock(return_value=fake_app)

            with (
                patch.object(youtube_command, "async_playwright", lambda: playwright_cm),
                patch.object(youtube_command, "browser_session", new=session_factory),
                patch.object(youtube_command, "is_logged_in", new=probe),
                patch.object(youtube_command, "resolve_account_file", new=resolve_account),
                patch.object(youtube_command, "youtube_setup", new=setup),
                patch.object(youtube_command, "_build_youtube_uploader", new=builder),
            ):
                code, out, _ = self._run(
                    [
                        "youtube",
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
        self.assertIn("YouTube video upload submitted", out)
        from utils.multilogin import MultiloginTarget

        target = MultiloginTarget(folder_id="folder", profile_id="profile")
        session_factory.assert_called_once()
        kwargs = session_factory.call_args.kwargs
        self.assertIsNone(kwargs["account_file"])
        self.assertEqual(kwargs["multilogin"], target)
        self.assertEqual(kwargs["launch_kwargs"], YOUTUBE_LAUNCH_KWARGS)
        self.assertEqual(kwargs["context_kwargs"], YOUTUBE_CONTEXT_KWARGS)
        self.assertTrue(kwargs["init_script"])
        self.assertEqual(playwright_cm.enter_calls, 1)
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)
        probe.assert_awaited_once_with(session.context)
        fake_app.set_publish_date.assert_called_once_with(0)
        fake_app.main.assert_awaited_once_with(session=session)
        builder.assert_called_once()
        self.assertIsNone(builder.call_args.args[1])
        resolve_account.assert_not_called()
        setup.assert_not_awaited()

    def test_upload_mlx_logged_out_returns_10_and_skips_upload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            session = Namespace(context=object())
            session_cm = _AsyncCM(session)
            fake_app = MagicMock()
            fake_app.main = AsyncMock()
            fake_app.set_publish_date = MagicMock()
            builder = MagicMock(return_value=fake_app)

            with (
                patch.object(
                    youtube_command, "async_playwright", lambda: _AsyncCM(object())
                ),
                patch.object(
                    youtube_command,
                    "browser_session",
                    new=MagicMock(return_value=session_cm),
                ),
                patch.object(
                    youtube_command, "is_logged_in", new=AsyncMock(return_value=False)
                ),
                patch.object(youtube_command, "_build_youtube_uploader", new=builder),
            ):
                code, out, err = self._run(
                    [
                        "youtube",
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
        self.assertIn("profile_id=profile", err)
        fake_app.set_publish_date.assert_not_called()
        fake_app.main.assert_not_awaited()
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_upload_mlx_failure_returns_1_and_still_exits_session_once(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            session = Namespace(context=object())
            session_cm = _AsyncCM(session)
            fake_app = MagicMock()
            fake_app.main = AsyncMock(side_effect=RuntimeError("publish failed"))
            fake_app.set_publish_date = MagicMock()
            builder = MagicMock(return_value=fake_app)

            with (
                patch.object(
                    youtube_command, "async_playwright", lambda: _AsyncCM(object())
                ),
                patch.object(
                    youtube_command,
                    "browser_session",
                    new=MagicMock(return_value=session_cm),
                ),
                patch.object(
                    youtube_command, "is_logged_in", new=AsyncMock(return_value=True)
                ),
                patch.object(youtube_command, "_build_youtube_uploader", new=builder),
            ):
                code, _, err = self._run(
                    [
                        "youtube",
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

    def test_local_upload_video_stays_on_legacy_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            legacy_upload = AsyncMock()
            session_factory = MagicMock()

            with (
                patch.object(youtube_command, "upload_youtube_video", new=legacy_upload),
                patch.object(youtube_command, "browser_session", new=session_factory),
            ):
                code, out, _ = self._run(
                    [
                        "youtube",
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

        self.assertEqual(code, 0)
        self.assertIn("YouTube video upload submitted", out)
        session_factory.assert_not_called()
        request = legacy_upload.await_args.args[0]
        self.assertEqual(request.account_name, "creator")
        self.assertIsNone(legacy_upload.await_args.kwargs.get("target"))


if __name__ == "__main__":
    unittest.main()
