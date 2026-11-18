"""Xiaohongshu Multilogin CLI and uploader session regressions."""

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
from sau_commands import xiaohongshu as xhs_command
from tests.fakes import FakeContext
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
XHS_VIDEO_URL = XHS_LOGIN_CHECK_URL


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
        wait_for_url_error: BaseException | None = None,
    ) -> None:
        self.url = "about:blank"
        self.final_url = final_url
        self.status = status
        self.goto_error = goto_error
        self.xhs_login_visible = xhs_login_visible
        self.xhs_upload_anchor = xhs_upload_anchor
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
        return _Locator()

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
        self.assertEqual(content.await_args.kwargs, {"mode": "multilogin"})
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
        self.assertEqual(content.await_args.kwargs, {"mode": "multilogin"})
        self.assertIsNone(app.account_file)


    def test_wrapper_with_session_does_not_open_playwright(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            xhs_video = _make_xhs_video(tmp_dir, account_file=None)
            xhs_video.upload = AsyncMock()
            session = BrowserSession(
                browser=MagicMock(), context=MagicMock(), mode="multilogin"
            )

            with patch.object(xhs_main, "async_playwright", MagicMock()) as xhs_pw:
                asyncio.run(xhs_video.xiaohongshu_upload_video(session=session))

        xhs_pw.assert_not_called()
        xhs_video.upload.assert_awaited_once_with(None, session=session)

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
        probe = AsyncMock(return_value=("valid", XHS_VIDEO_URL))

        with (
            patch.object(xhs_command, "async_playwright", lambda: playwright_cm),
            session_patch,
            patch.object(xhs_command, "probe_session", new=probe),
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
                xhs_command,
                "probe_session",
                new=AsyncMock(return_value=("login", XHS_LOGIN_REDIRECT)),
            ),
        ):
            code, out, _ = self._run(
                ["xiaohongshu", "check", "--folder-id", "folder", "--profile-id", "profile"]
            )

        self.assertEqual(code, 10)
        self.assertEqual(out.strip(), "invalid")
        self.assertEqual(session_cm.exit_calls, 1)

    def test_check_probe_error_returns_1(self):
        playwright_cm = _AsyncCM(object())
        _, session_cm, _, session_patch = self._session_patch(xhs_command)

        with (
            patch.object(xhs_command, "async_playwright", lambda: playwright_cm),
            session_patch,
            patch.object(
                xhs_command,
                "probe_session",
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
            fake_app = MagicMock()
            fake_app.xiaohongshu_upload_video = AsyncMock()
            builder = MagicMock(return_value=fake_app)

            with (
                patch.object(xhs_command, "async_playwright", lambda: playwright_cm),
                session_patch,
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
        kwargs = factory.call_args.kwargs
        self.assertIsNone(kwargs["account_file"])
        self.assertEqual(kwargs["launch_kwargs"], XHS_LAUNCH_KWARGS)
        self.assertEqual(kwargs["context_kwargs"], XHS_CONTEXT_KWARGS)
        self.assertTrue(kwargs["init_script"])
        fake_app.xiaohongshu_upload_video.assert_awaited_once_with(session=session)
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)
        self.assertEqual(playwright_cm.enter_calls, 1)

    def test_managed_check_without_account_ignores_nothing(self):
        playwright_cm = _AsyncCM(object())
        _, _, factory, session_patch = self._session_patch(xhs_command)

        with (
            patch.object(xhs_command, "async_playwright", lambda: playwright_cm),
            session_patch,
            patch.object(
                xhs_command,
                "probe_session",
                new=AsyncMock(return_value=("valid", XHS_VIDEO_URL)),
            ),
        ):
            code, _, _ = self._run(
                [
                    "xiaohongshu",
                    "check",
                    "--folder-id",
                    "folder",
                    "--profile-id",
                    "profile",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(factory.call_args.kwargs["extra_ignored"], ())

    def test_managed_check_reports_account_as_an_ignored_key(self):
        playwright_cm = _AsyncCM(object())
        _, _, factory, session_patch = self._session_patch(xhs_command)

        with (
            patch.object(xhs_command, "async_playwright", lambda: playwright_cm),
            session_patch,
            patch.object(
                xhs_command,
                "probe_session",
                new=AsyncMock(return_value=("valid", XHS_VIDEO_URL)),
            ),
        ):
            code, _, _ = self._run(
                [
                    "xiaohongshu",
                    "check",
                    "--folder-id",
                    "folder",
                    "--profile-id",
                    "profile",
                    "--account",
                    "creator",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(factory.call_args.kwargs["extra_ignored"], ("account",))

    def test_managed_upload_video_forwards_every_dropped_key(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            _, _, factory, session_patch = self._session_patch(xhs_command)
            fake_app = MagicMock()
            fake_app.xiaohongshu_upload_video = AsyncMock()

            with (
                patch.object(
                    xhs_command, "async_playwright", lambda: _AsyncCM(object())
                ),
                session_patch,
                patch.object(
                    xhs_command,
                    "_build_video_uploader",
                    new=MagicMock(return_value=fake_app),
                ),
            ):
                code, _, _ = self._run(
                    [
                        "xiaohongshu",
                        "upload-video",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--account",
                        "creator",
                        "--file",
                        str(video_path),
                        "--title",
                        "标题",
                    ]
                )

        self.assertEqual(code, 0)
        kwargs = factory.call_args.kwargs
        self.assertEqual(kwargs["extra_ignored"], ("account",))
        self.assertEqual(kwargs["launch_kwargs"], XHS_LAUNCH_KWARGS)
        self.assertEqual(kwargs["context_kwargs"], XHS_CONTEXT_KWARGS)
        self.assertTrue(kwargs["init_script"])

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
        fake_app.xiaohongshu_upload_note.assert_awaited_once_with(session=session)

    def test_upload_mlx_does_not_preflight_login(self):
        # 发布链路的登录探测已删除：托管上传直接进入发布页，由 C1 判定。
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            _, session_cm, _, session_patch = self._session_patch(xhs_command)
            upload = AsyncMock()
            probe = AsyncMock()

            with (
                patch.object(xhs_command, "async_playwright", lambda: _AsyncCM(object())),
                session_patch,
                patch.object(xhs_command, "probe_session", new=probe),
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

        self.assertEqual(code, 0)
        self.assertIn("submitted", out)
        upload.assert_awaited_once()
        probe.assert_not_awaited()
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


if __name__ == "__main__":
    unittest.main()
