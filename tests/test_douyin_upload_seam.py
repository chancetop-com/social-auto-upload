# -*- coding: utf-8 -*-
"""Douyin video/note uploader seam: legacy local path vs Multilogin path (ticket 17).

The local branch must stay behaviour-equivalent to the pre-seam uploader; the
Multilogin branch must only touch the injected ``BrowserSession`` and never
launch a browser, create a context, inject init scripts, read/write cookies, or
close anything it does not own.
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
from sau_commands import douyin as douyin_command
from tests.fakes import FakePlaywright
from uploader.douyin_uploader import main as douyin_main
from uploader.douyin_uploader.main import (
    DOUYIN_CONTEXT_KWARGS,
    DOUYIN_LAUNCH_KWARGS,
    DOUYIN_UPLOAD_URL,
    DouYinNote,
    DouYinVideo,
)
from utils.browser_session import BrowserSession
from utils.errors import LoginRequiredError

TOKEN = "SENTINEL-MLX-TOKEN-ticket17"


class _RecordingPage:
    """Minimal page double that records navigation and login redirects."""

    def __init__(self, *, final_url: str = DOUYIN_UPLOAD_URL) -> None:
        self.url = "about:blank"
        self.final_url = final_url
        self.goto_calls: list[tuple[str, dict]] = []
        self.wait_for_url_calls: list[tuple[str, dict]] = []
        self.wait_timeout_calls: list[int] = []
        self.closed = False

    async def goto(self, url: str, **kwargs):
        self.goto_calls.append((url, kwargs))
        self.url = self.final_url
        return None

    async def wait_for_url(self, url: str, **kwargs) -> None:
        self.wait_for_url_calls.append((url, kwargs))
        self.url = url

    async def wait_for_timeout(self, ms: int) -> None:
        self.wait_timeout_calls.append(ms)

    async def close(self) -> None:
        self.closed = True


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


def _make_video(tmp_dir: str, account_file=None, **kwargs) -> DouYinVideo:
    video_path = Path(tmp_dir) / "demo.mp4"
    if not video_path.exists():
        video_path.write_bytes(b"video")
    return DouYinVideo(
        "标题",
        str(video_path),
        [],
        0,
        account_file,
        **kwargs,
    )


def _make_note(tmp_dir: str, account_file=None, **kwargs) -> DouYinNote:
    image_path = Path(tmp_dir) / "image.png"
    if not image_path.exists():
        image_path.write_bytes(b"image")
    return DouYinNote(
        image_paths=[str(image_path)],
        title="图文标题",
        note="图文正文",
        tags=[],
        publish_date=0,
        account_file=account_file,
        **kwargs,
    )


class LegacyLocalUploadTests(unittest.TestCase):
    """``session is None`` keeps the historical launch/context/teardown path."""

    def test_video_launch_kwargs_and_init_script_are_golden(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, "/tmp/couple-cookie.json", headless=False)
            video.validate_upload_args = AsyncMock()
            upload_in = AsyncMock()
            video.upload_in = upload_in

            playwright = FakePlaywright()
            init_script = AsyncMock(side_effect=lambda context: context)

            with (
                patch.object(douyin_main, "set_init_script", init_script),
                patch.object(douyin_main.asyncio, "sleep", AsyncMock()),
            ):
                asyncio.run(video.upload(playwright))

        self.assertEqual(
            playwright.chromium.launch_calls,
            [{"headless": False, **DOUYIN_LAUNCH_KWARGS}],
        )
        self.assertEqual(DOUYIN_LAUNCH_KWARGS["channel"], "chromium")
        self.assertEqual(
            DOUYIN_LAUNCH_KWARGS["args"],
            ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )

        browser = playwright.chromium.launch_browser
        self.assertEqual(
            browser.new_context_calls,
            [{"storage_state": "/tmp/couple-cookie.json", **DOUYIN_CONTEXT_KWARGS}],
        )
        self.assertEqual(DOUYIN_CONTEXT_KWARGS, {"permissions": ["geolocation"]})

        context = browser.contexts[0]
        init_script.assert_awaited_once_with(context)
        self.assertTrue(douyin_main.DOUYIN_INIT_SCRIPT)
        upload_in.assert_awaited_once()
        session = upload_in.await_args.args[0]
        self.assertEqual(session.mode, "local")
        self.assertIs(session.context, context)

    def test_video_local_teardown_saves_cookie_then_closes_context_and_browser(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, "/tmp/couple-cookie.json")
            video.validate_upload_args = AsyncMock()
            video.upload_in = AsyncMock()

            playwright = FakePlaywright()
            with (
                patch.object(
                    douyin_main, "set_init_script", AsyncMock(side_effect=lambda c: c)
                ),
                patch.object(douyin_main.asyncio, "sleep", AsyncMock()),
            ):
                asyncio.run(video.upload(playwright))

        browser = playwright.chromium.launch_browser
        context = browser.contexts[0]
        self.assertEqual(context.storage_state_calls, ["/tmp/couple-cookie.json"])
        self.assertTrue(context.closed)
        self.assertTrue(browser.closed)
        self.assertEqual(playwright.events, ["launch", "context.close", "browser.close"])

    def test_note_local_teardown_saves_cookie_and_closes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            note = _make_note(tmp_dir, "/tmp/note-cookie.json")
            note.validate_upload_args = AsyncMock()
            note.upload_in = AsyncMock()

            playwright = FakePlaywright()
            with (
                patch.object(
                    douyin_main, "set_init_script", AsyncMock(side_effect=lambda c: c)
                ),
                patch.object(douyin_main.asyncio, "sleep", AsyncMock()),
            ):
                asyncio.run(note.upload(playwright))

        browser = playwright.chromium.launch_browser
        context = browser.contexts[0]
        self.assertEqual(
            browser.new_context_calls,
            [{"storage_state": "/tmp/note-cookie.json", **DOUYIN_CONTEXT_KWARGS}],
        )
        self.assertEqual(context.storage_state_calls, ["/tmp/note-cookie.json"])
        self.assertTrue(context.closed)
        self.assertTrue(browser.closed)


class MultiloginUploadTests(unittest.TestCase):
    """``session is not None`` is a pure consumer of the injected session."""

    def test_video_upload_in_uses_injected_context_only(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, account_file=None)
            page_ops = AsyncMock()
            video._upload_video_on_page = page_ops

            page = _RecordingPage()
            context = _RecordingContext(page)
            session = BrowserSession(
                browser=MagicMock(), context=context, mode="multilogin"
            )

            with (
                patch.object(
                    douyin_main, "async_playwright", MagicMock()
                ) as async_playwright,
                patch.object(douyin_main, "set_init_script", AsyncMock()) as init_script,
                patch.object(douyin_main.asyncio, "sleep", AsyncMock()),
            ):
                asyncio.run(video.upload(None, session=session))

        async_playwright.assert_not_called()
        init_script.assert_not_awaited()
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, 0)
        self.assertEqual(page.goto_calls[0][0], DOUYIN_UPLOAD_URL)
        page_ops.assert_awaited_once_with(page, multilogin=True)
        self.assertIsNone(video.account_file)

    def test_note_upload_in_uses_injected_context_only(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            note = _make_note(tmp_dir, account_file=None)
            note_content = AsyncMock()
            note.upload_note_content = note_content

            page = _RecordingPage()
            context = _RecordingContext(page)
            session = BrowserSession(
                browser=MagicMock(), context=context, mode="multilogin"
            )

            with patch.object(douyin_main.asyncio, "sleep", AsyncMock()):
                asyncio.run(note.upload(None, session=session))

        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, 0)
        note_content.assert_awaited_once_with(page, multilogin=True)
        self.assertIsNone(note.account_file)

    def test_mlx_validation_skips_cookie_auth(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, account_file=None)
            video.upload_in = AsyncMock()
            cookie_auth = AsyncMock()

            with patch.object(douyin_main, "cookie_auth", cookie_auth):
                asyncio.run(
                    video.upload(
                        None,
                        session=BrowserSession(
                            browser=MagicMock(),
                            context=MagicMock(),
                            mode="multilogin",
                        ),
                    )
                )

        cookie_auth.assert_not_awaited()

    def test_video_login_redirect_mid_upload_raises_login_required(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, account_file=None)
            page_ops = AsyncMock()
            video._upload_video_on_page = page_ops

            page = _RecordingPage(
                final_url="https://creator.douyin.com/login/?redirect=%2Fcreator-micro"
            )
            context = _RecordingContext(page)
            session = BrowserSession(
                browser=MagicMock(), context=context, mode="multilogin"
            )

            with self.assertRaises(LoginRequiredError):
                asyncio.run(video.upload(None, session=session))

        page_ops.assert_not_awaited()

    def test_note_captcha_redirect_mid_upload_raises_login_required(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            note = _make_note(tmp_dir, account_file=None)
            note_content = AsyncMock()
            note.upload_note_content = note_content

            page = _RecordingPage(
                final_url="https://creator.douyin.com/captcha/verify?scene=upload"
            )
            context = _RecordingContext(page)
            session = BrowserSession(
                browser=MagicMock(), context=context, mode="multilogin"
            )

            with self.assertRaises(LoginRequiredError):
                asyncio.run(note.upload(None, session=session))

        note_content.assert_not_awaited()

    def test_wrapper_with_session_does_not_open_a_second_playwright(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, account_file=None)
            video.upload = AsyncMock()
            session = BrowserSession(
                browser=MagicMock(), context=MagicMock(), mode="multilogin"
            )

            with patch.object(
                douyin_main, "async_playwright", MagicMock()
            ) as async_playwright:
                asyncio.run(video.douyin_upload_video(session=session))

        async_playwright.assert_not_called()
        video.upload.assert_awaited_once_with(None, session=session)

    def test_wrapper_without_session_keeps_legacy_playwright(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, "/tmp/cookie.json")
            video.upload = AsyncMock()

            with patch.object(
                douyin_main, "async_playwright", MagicMock()
            ) as async_playwright:
                playwright_cm = _AsyncCM(object())
                async_playwright.return_value = playwright_cm
                asyncio.run(video.douyin_upload_video())

        self.assertEqual(playwright_cm.enter_calls, 1)
        self.assertEqual(playwright_cm.exit_calls, 1)
        video.upload.assert_awaited_once()


class DouyinMlxCliUploadTests(unittest.TestCase):
    def _run(self, argv, token=TOKEN):
        with patch.dict(os.environ, {"MLX_API_TOKEN": token}):
            with redirect_stdout(io.StringIO()) as out, redirect_stderr(
                io.StringIO()
            ) as err:
                code = sau_cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_upload_video_mlx_passes_none_account_and_one_session(self):
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
            fake_app.douyin_upload_video = AsyncMock()
            builder = MagicMock(return_value=fake_app)

            with (
                patch.object(
                    douyin_command, "async_playwright", lambda: playwright_cm
                ),
                patch.object(
                    douyin_command, "browser_session", new=session_factory
                ),
                patch.object(douyin_command, "is_logged_in", new=probe),
                patch.object(
                    douyin_command, "resolve_account_file", new=resolve_account
                ),
                patch.object(douyin_command, "douyin_setup", new=setup),
                patch.object(
                    douyin_command, "_build_video_uploader", new=builder
                ),
            ):
                code, out, _ = self._run(
                    [
                        "douyin",
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
        self.assertIn("Douyin video upload submitted", out)
        from utils.multilogin import MultiloginTarget

        target = MultiloginTarget(folder_id="folder", profile_id="profile")
        session_factory.assert_called_once()
        kwargs = session_factory.call_args.kwargs
        self.assertIsNone(kwargs["account_file"])
        self.assertEqual(kwargs["managed"].target, target)
        self.assertEqual(kwargs["launch_kwargs"], DOUYIN_LAUNCH_KWARGS)
        self.assertEqual(kwargs["context_kwargs"], DOUYIN_CONTEXT_KWARGS)
        self.assertTrue(kwargs["init_script"])
        self.assertEqual(playwright_cm.enter_calls, 1)
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)
        probe.assert_awaited_once_with(session.context)
        fake_app.douyin_upload_video.assert_awaited_once_with(session=session)
        builder.assert_called_once()
        self.assertIsNone(builder.call_args.args[1])
        resolve_account.assert_not_called()
        setup.assert_not_awaited()

    def test_upload_note_mlx_passes_none_account_and_session(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "image.png"
            image_path.write_bytes(b"image")

            playwright_cm = _AsyncCM(object())
            session = Namespace(context=object())
            session_cm = _AsyncCM(session)
            session_factory = MagicMock(return_value=session_cm)
            probe = AsyncMock(return_value=True)
            fake_app = MagicMock()
            fake_app.douyin_upload_note = AsyncMock()
            builder = MagicMock(return_value=fake_app)

            with (
                patch.object(
                    douyin_command, "async_playwright", lambda: playwright_cm
                ),
                patch.object(
                    douyin_command, "browser_session", new=session_factory
                ),
                patch.object(douyin_command, "is_logged_in", new=probe),
                patch.object(
                    douyin_command, "_build_note_uploader", new=builder
                ),
            ):
                code, out, _ = self._run(
                    [
                        "douyin",
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
        self.assertIn("Douyin note upload submitted", out)
        self.assertIsNone(session_factory.call_args.kwargs["account_file"])
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)
        fake_app.douyin_upload_note.assert_awaited_once_with(session=session)
        builder.assert_called_once()
        self.assertIsNone(builder.call_args.args[1])

    def test_upload_mlx_logged_out_returns_10_and_skips_upload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            session = Namespace(context=object())
            session_cm = _AsyncCM(session)
            upload = AsyncMock()

            with (
                patch.object(
                    douyin_command, "async_playwright", lambda: _AsyncCM(object())
                ),
                patch.object(
                    douyin_command,
                    "browser_session",
                    new=MagicMock(return_value=session_cm),
                ),
                patch.object(
                    douyin_command, "is_logged_in", new=AsyncMock(return_value=False)
                ),
                patch.object(DouYinVideo, "douyin_upload_video", new=upload),
            ):
                code, out, _ = self._run(
                    [
                        "douyin",
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
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_upload_mlx_failure_still_exits_session_once(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            session = Namespace(context=object())
            session_cm = _AsyncCM(session)
            upload = AsyncMock(side_effect=RuntimeError("publish failed"))

            with (
                patch.object(
                    douyin_command, "async_playwright", lambda: _AsyncCM(object())
                ),
                patch.object(
                    douyin_command,
                    "browser_session",
                    new=MagicMock(return_value=session_cm),
                ),
                patch.object(
                    douyin_command, "is_logged_in", new=AsyncMock(return_value=True)
                ),
                patch.object(DouYinVideo, "douyin_upload_video", new=upload),
            ):
                code, _, err = self._run(
                    [
                        "douyin",
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
                patch.object(douyin_command, "upload_video", new=legacy_upload),
                patch.object(
                    douyin_command, "browser_session", new=session_factory
                ),
            ):
                code, out, _ = self._run(
                    [
                        "douyin",
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
        self.assertIn("Douyin video upload submitted", out)
        session_factory.assert_not_called()
        request = legacy_upload.await_args.args[0]
        self.assertEqual(request.account_name, "creator")
        self.assertIsNone(legacy_upload.await_args.kwargs.get("target"))

    def test_local_upload_note_stays_on_legacy_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "image.png"
            image_path.write_bytes(b"image")

            legacy_upload = AsyncMock()
            session_factory = MagicMock()

            with (
                patch.object(douyin_command, "upload_note", new=legacy_upload),
                patch.object(
                    douyin_command, "browser_session", new=session_factory
                ),
            ):
                code, out, _ = self._run(
                    [
                        "douyin",
                        "upload-note",
                        "--account",
                        "creator",
                        "--images",
                        str(image_path),
                        "--title",
                        "图文标题",
                    ],
                    token="",
                )

        self.assertEqual(code, 0)
        self.assertIn("Douyin note upload submitted", out)
        session_factory.assert_not_called()
        request = legacy_upload.await_args.args[0]
        self.assertEqual(request.account_name, "creator")
        self.assertIsNone(legacy_upload.await_args.kwargs.get("target"))


if __name__ == "__main__":
    unittest.main()
