# -*- coding: utf-8 -*-
"""TikTok CLI (Multilogin-only) and uploader seam (ticket 25).

All tests are offline: no browser, no network, no cookie files.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import io
import os
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import sau_cli
from conf import LOCAL_CHROME_PATH
from sau_commands import tiktok as tiktok_command
from tests.fakes import FakeContext, FakePage, FakePlaywright
from uploader.tk_uploader import main_chrome as tk_main
from uploader.tk_uploader.main_chrome import (
    TIKTOK_CONTEXT_KWARGS,
    TIKTOK_INIT_SCRIPT,
    TIKTOK_LAUNCH_KWARGS,
    TIKTOK_LOGIN_CHECK_TIMEOUT_MS,
    TIKTOK_LOGIN_CHECK_URL,
    TIKTOK_PUBLISH_TIMEOUT_SECONDS,
    TIKTOK_UPLOAD_URL,
    TiktokVideo,
    is_logged_in,
)
from utils.browser_session import BrowserSession
from utils.errors import LoginRequiredError

TOKEN = "SENTINEL-MLX-TOKEN-ticket25"


# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------


def _subparser(parser: argparse.ArgumentParser, platform: str, action: str | None = None):
    for item in parser._actions:
        if isinstance(item, argparse._SubParsersAction):
            if platform in item.choices:
                platform_parser = item.choices[platform]
                if action is None:
                    return platform_parser
                for nested in platform_parser._actions:
                    if isinstance(nested, argparse._SubParsersAction):
                        return nested.choices[action]
    raise AssertionError(f"parser not found: {platform}/{action}")


def _action_names(platform: str) -> list[str]:
    platform_parser = _subparser(sau_cli.build_parser(), platform)
    for item in platform_parser._actions:
        if isinstance(item, argparse._SubParsersAction):
            return list(item.choices)
    return []


def _option_strings(parser: argparse.ArgumentParser) -> set[str]:
    return set(parser._option_string_actions)


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


def _run(argv, token=TOKEN):
    environ = {"MLX_API_TOKEN": token}
    with patch.dict(os.environ, environ):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(
            io.StringIO()
        ) as err:
            code = sau_cli.main(argv)
    return code, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# Parser contract
# ---------------------------------------------------------------------------


class TiktokParserTests(unittest.TestCase):
    def test_platform_is_registered(self):
        self.assertIs(sau_cli.PLATFORMS["tiktok"], tiktok_command)

    def test_actions_are_check_upload_video_login_only(self):
        self.assertEqual(
            set(_action_names("tiktok")), {"check", "upload-video", "login"}
        )
        self.assertNotIn("upload-note", _action_names("tiktok"))

    def test_upload_video_parameters_match_repository_naming(self):
        options = _option_strings(_subparser(sau_cli.build_parser(), "tiktok", "upload-video"))
        for expected in (
            "--file",
            "--title",
            "--tags",
            "--schedule",
            "--thumbnail",
            "--account",
            "--headless",
            "--headed",
            "--debug",
            "--folder-id",
            "--profile-id",
        ):
            with self.subTest(option=expected):
                self.assertIn(expected, options)
        self.assertNotIn("--video-file", options)
        self.assertNotIn("--publish-date", options)

    def test_check_accepts_account_runtime_and_multilogin_flags(self):
        options = _option_strings(_subparser(sau_cli.build_parser(), "tiktok", "check"))
        for expected in (
            "--account",
            "--headless",
            "--headed",
            "--debug",
            "--folder-id",
            "--profile-id",
        ):
            with self.subTest(option=expected):
                self.assertIn(expected, options)
        self.assertNotIn("--file", options)

    def test_login_does_not_accept_multilogin_flags(self):
        options = _option_strings(_subparser(sau_cli.build_parser(), "tiktok", "login"))
        self.assertIn("--account", options)
        self.assertNotIn("--folder-id", options)
        self.assertNotIn("--profile-id", options)

    def test_parse_upload_video(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = Path(tmp_dir) / "demo.mp4"
            video.write_bytes(b"video")
            thumb = Path(tmp_dir) / "thumb.png"
            thumb.write_bytes(b"image")

            args = sau_cli.build_parser().parse_args(
                [
                    "tiktok",
                    "upload-video",
                    "--folder-id",
                    "folder",
                    "--profile-id",
                    "profile",
                    "--file",
                    str(video),
                    "--title",
                    "标题",
                    "--tags",
                    "a,b",
                    "--schedule",
                    "2026-11-05 10:30",
                    "--thumbnail",
                    str(thumb),
                ]
            )

        self.assertEqual(args.action, "upload-video")
        self.assertEqual(args.file, video)
        self.assertEqual(args.title, "标题")
        self.assertEqual(args.tags, "a,b")
        self.assertEqual(args.schedule, datetime(2026, 11, 5, 10, 30))
        self.assertEqual(args.thumbnail, thumb)
        self.assertEqual(args.folder_id, "folder")
        self.assertEqual(args.profile_id, "profile")
        self.assertTrue(args.headless)
        self.assertIsNone(args.account)

    def test_unknown_subcommand_still_exits_2(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                sau_cli.main(["tiktok", "upload-note"])
        self.assertEqual(ctx.exception.code, 2)


# ---------------------------------------------------------------------------
# Local mode and login rejection
# ---------------------------------------------------------------------------


class LocalModeRejectionTests(unittest.TestCase):
    def _assert_local_rejection(self, argv, token=""):
        playwright = MagicMock()
        session = MagicMock()
        with (
            patch.object(tiktok_command, "async_playwright", playwright),
            patch.object(tiktok_command, "browser_session", session),
        ):
            code, out, err = _run(argv, token=token)
        self.assertEqual(code, 1)
        self.assertIn("TikTok 仅支持 Multilogin 模式", err)
        self.assertNotIn("submitted", out)
        playwright.assert_not_called()
        session.assert_not_called()

    def test_check_local_exits_1(self):
        self._assert_local_rejection(["tiktok", "check", "--account", "creator"])

    def test_upload_video_local_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = Path(tmp_dir) / "demo.mp4"
            video.write_bytes(b"video")
            self._assert_local_rejection(
                [
                    "tiktok",
                    "upload-video",
                    "--account",
                    "creator",
                    "--file",
                    str(video),
                    "--title",
                    "标题",
                ]
            )

    def test_login_local_exits_1(self):
        self._assert_local_rejection(["tiktok", "login", "--account", "creator"])

    def test_whitespace_token_is_local_mode(self):
        self._assert_local_rejection(
            ["tiktok", "check", "--account", "creator"], token="   "
        )


class MlxLoginRejectionTests(unittest.TestCase):
    def test_login_in_mlx_exits_1_with_placeholder(self):
        # ``login`` deliberately does not register MLX flags, so the CLI can
        # only show the generic profile placeholder.
        playwright = MagicMock()
        with patch.object(tiktok_command, "async_playwright", playwright):
            code, _, err = _run(["tiktok", "login", "--account", "creator"])
        self.assertEqual(code, 1)
        self.assertIn("Multilogin 模式不支持 CLI 登录", err)
        self.assertIn("指定 Profile", err)
        playwright.assert_not_called()


# ---------------------------------------------------------------------------
# is_logged_in
# ---------------------------------------------------------------------------


class _Response:
    def __init__(self, status: int = 200) -> None:
        self.status = status


class _Locator:
    def __init__(self, count: int = 0) -> None:
        self._count = count

    async def count(self) -> int:
        return self._count


class _ProbePage:
    def __init__(
        self,
        *,
        url: str = "about:blank",
        final_url: str = TIKTOK_LOGIN_CHECK_URL,
        status: int | None = 200,
        goto_error: BaseException | None = None,
        upload_entry: bool = True,
        login_form: bool = False,
    ) -> None:
        self.url = url
        self.final_url = final_url
        self.status = status
        self.goto_error = goto_error
        self.upload_entry = upload_entry
        self.login_form = login_form
        self.goto_calls: list[tuple[str, dict]] = []
        self.wait_for_selector_calls: list[tuple[str, dict]] = []
        self.close_calls = 0
        self.closed = False

    async def goto(self, url: str, **kwargs):
        self.goto_calls.append((url, kwargs))
        if self.goto_error is not None:
            raise self.goto_error
        self.url = self.final_url
        return _Response(self.status) if self.status is not None else None

    async def wait_for_selector(self, selector: str, **kwargs):
        self.wait_for_selector_calls.append((selector, kwargs))
        if self.upload_entry:
            return object()
        raise RuntimeError("selector timeout")

    def locator(self, selector: str) -> _Locator:
        if selector == tk_main.TIKTOK_LOGIN_FORM_SELECTOR:
            return _Locator(1 if self.login_form else 0)
        return _Locator(0)

    async def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class _ProbeContext:
    def __init__(
        self,
        pages: list[_ProbePage] | None = None,
        next_page: _ProbePage | None = None,
    ) -> None:
        self.pages = list(pages or [])
        self.next_page = next_page
        self.new_page_calls = 0
        self.created: list[_ProbePage] = []

    async def new_page(self) -> _ProbePage:
        self.new_page_calls += 1
        page = self.next_page if self.next_page is not None else _ProbePage()
        self.pages.append(page)
        self.created.append(page)
        return page


class IsLoggedInTests(unittest.TestCase):
    def test_upload_entry_returns_true_with_one_new_page(self):
        context = _ProbeContext()
        self.assertTrue(asyncio.run(is_logged_in(context)))

        self.assertEqual(context.new_page_calls, 1)
        page = context.created[0]
        self.assertTrue(page.closed)
        self.assertEqual(page.close_calls, 1)
        self.assertEqual(page.goto_calls[0][0], TIKTOK_LOGIN_CHECK_URL)
        kwargs = page.goto_calls[0][1]
        self.assertEqual(kwargs["wait_until"], "domcontentloaded")
        self.assertEqual(kwargs["timeout"], TIKTOK_LOGIN_CHECK_TIMEOUT_MS)

    def test_login_url_returns_false(self):
        context = _ProbeContext(
            next_page=_ProbePage(final_url="https://www.tiktok.com/login?lang=en")
        )
        self.assertFalse(asyncio.run(is_logged_in(context)))

    def test_login_form_returns_false_even_on_upload_url(self):
        context = _ProbeContext(
            next_page=_ProbePage(final_url=TIKTOK_LOGIN_CHECK_URL, login_form=True)
        )
        self.assertFalse(asyncio.run(is_logged_in(context)))

    def test_network_error_propagates_and_closes_owned_page(self):
        context = _ProbeContext()
        page = _ProbePage(goto_error=RuntimeError("net::ERR_CONNECTION_RESET"))
        # Force the probe to own (and therefore close) this page.
        async def new_page():
            context.new_page_calls += 1
            context.pages.append(page)
            return page

        context.new_page = new_page

        with self.assertRaises(RuntimeError):
            asyncio.run(is_logged_in(context))
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(page.close_calls, 1)

    def test_server_error_propagates(self):
        context = _ProbeContext(next_page=_ProbePage(status=503))
        with self.assertRaises(RuntimeError):
            asyncio.run(is_logged_in(context))

    def test_unexpected_structure_propagates(self):
        context = _ProbeContext(
            next_page=_ProbePage(
                final_url=TIKTOK_LOGIN_CHECK_URL, upload_entry=False
            )
        )
        with self.assertRaises(RuntimeError):
            asyncio.run(is_logged_in(context))

    def test_existing_matching_page_is_never_navigated_or_closed(self):
        existing = _ProbePage(url=TIKTOK_LOGIN_CHECK_URL)
        context = _ProbeContext([existing])
        self.assertTrue(asyncio.run(is_logged_in(context)))
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(existing.goto_calls, [])
        self.assertEqual(existing.close_calls, 0)
        self.assertEqual(len(context.created), 1)
        self.assertTrue(context.created[0].closed)

    def test_any_existing_page_is_left_untouched(self):
        existing = _ProbePage()
        context = _ProbeContext([existing])
        self.assertTrue(asyncio.run(is_logged_in(context)))
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(existing.goto_calls, [])
        self.assertEqual(existing.close_calls, 0)
        self.assertTrue(context.created[0].closed)

    def test_budget_constant_is_20_seconds(self):
        self.assertEqual(TIKTOK_LOGIN_CHECK_TIMEOUT_MS, 20_000)


# ---------------------------------------------------------------------------
# Seam / forbidden APIs / local parity
# ---------------------------------------------------------------------------


class UploaderSeamTests(unittest.TestCase):
    def _video(self, account_file=None) -> TiktokVideo:
        return TiktokVideo("标题", "/tmp/demo.mp4", ["tag"], 0, account_file)

    def test_init_positional_order_is_unchanged(self):
        params = list(inspect.signature(TiktokVideo.__init__).parameters)
        self.assertEqual(
            params,
            [
                "self",
                "title",
                "file_path",
                "tags",
                "publish_date",
                "account_file",
                "thumbnail_path",
            ],
        )
        video = self._video(account_file=None)
        self.assertIsNone(video.account_file)

    def test_golden_legacy_browser_constants(self):
        self.assertEqual(
            TIKTOK_LAUNCH_KWARGS, {"executable_path": LOCAL_CHROME_PATH}
        )
        self.assertEqual(TIKTOK_CONTEXT_KWARGS, {})
        self.assertIs(TIKTOK_INIT_SCRIPT, False)

    def test_mlx_upload_only_uses_injected_context(self):
        video = self._video(account_file=None)
        page_ops = AsyncMock()
        video._upload_on_page = page_ops

        context = FakeContext()
        session = BrowserSession(
            browser=MagicMock(), context=context, mode="multilogin"
        )

        with (
            patch.object(tk_main, "async_playwright", MagicMock()) as async_playwright,
            patch.object(tk_main, "set_init_script", AsyncMock()) as init_script,
            patch.object(tk_main.time, "monotonic", return_value=1000.0),
        ):
            asyncio.run(video.upload(None, session=session))

        async_playwright.assert_not_called()
        init_script.assert_not_awaited()
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, [])
        self.assertFalse(context.closed)

        page_ops.assert_awaited_once()
        self.assertTrue(page_ops.await_args.kwargs["multilogin"])
        self.assertEqual(page_ops.await_args.kwargs["deadline"], 1900.0)

    def test_mlx_upload_reuses_an_existing_page(self):
        video = self._video(account_file=None)
        page_ops = AsyncMock()
        video._upload_on_page = page_ops

        page = FakePage()
        context = FakeContext(pages=[page])
        session = BrowserSession(
            browser=MagicMock(), context=context, mode="multilogin"
        )

        asyncio.run(video.upload(None, session=session))

        self.assertEqual(context.new_page_calls, 0)
        page_ops.assert_awaited_once()
        self.assertIs(page_ops.await_args.args[0], page)

    def test_mlx_skips_change_language(self):
        video = self._video(account_file=None)
        video.change_language = AsyncMock()
        video._upload_on_page = AsyncMock()
        session = BrowserSession(
            browser=MagicMock(),
            context=FakeContext(),
            mode="multilogin",
        )

        asyncio.run(video.upload(None, session=session))
        video.change_language.assert_not_awaited()

    def test_legacy_local_path_keeps_golden_launch_context_and_teardown(self):
        video = self._video(account_file="/tmp/couple-cookie.json")
        video.headless = False
        video.change_language = AsyncMock()
        page_ops = AsyncMock()
        video._upload_on_page = page_ops

        playwright = FakePlaywright()
        with (
            patch.object(tk_main, "set_init_script", AsyncMock()) as init_script,
            patch.object(tk_main.asyncio, "sleep", AsyncMock()),
        ):
            asyncio.run(video.upload(playwright))

        self.assertEqual(
            playwright.chromium.launch_calls,
            [{"headless": False, **TIKTOK_LAUNCH_KWARGS}],
        )
        browser = playwright.chromium.launch_browser
        self.assertEqual(
            browser.new_context_calls,
            [{"storage_state": "/tmp/couple-cookie.json", **TIKTOK_CONTEXT_KWARGS}],
        )
        context = browser.contexts[0]
        init_script.assert_not_awaited()
        video.change_language.assert_awaited_once()
        page_ops.assert_awaited_once_with(
            ANY, multilogin=False, deadline=None
        )
        self.assertEqual(
            context.storage_state_calls, ["/tmp/couple-cookie.json"]
        )
        self.assertTrue(context.closed)
        self.assertTrue(browser.closed)

    def test_local_upload_without_playwright_fails_before_browser(self):
        video = self._video(account_file="/tmp/cookie.json")
        with self.assertRaises(ValueError):
            asyncio.run(video.upload(None))

    def test_firefox_main_is_not_wired(self):
        # Importing the Firefox module would require upstream Playwright (the
        # runtime only ships Patchright), so assert on its source instead.
        firefox_main = Path(tk_main.__file__).with_name("main.py")
        source = firefox_main.read_text(encoding="utf-8")
        self.assertNotIn("patchright", source)
        self.assertNotIn("BrowserSession", source)
        self.assertNotIn("browser_session", source)
        self.assertNotIn("upload_in", source)
        self.assertNotIn("is_logged_in", source)
        self.assertIn("playwright.async_api", source)

    def test_cli_never_resolves_a_cookie_file(self):
        self.assertFalse(hasattr(tiktok_command, "resolve_account_file"))
        source = Path(tiktok_command.__file__).read_text(encoding="utf-8")
        self.assertNotIn("cookies", source)
        self.assertNotIn("storage_state", source)

    def test_uploader_builder_passes_none_account_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = Path(tmp_dir) / "demo.mp4"
            video.write_bytes(b"video")
            request = tiktok_command.TiktokVideoUploadRequest(
                account_label="profile",
                video_file=video,
                title="标题",
                tags=["a"],
                publish_date=0,
            )
            app = tiktok_command._build_video_uploader(request)

        self.assertIsNone(app.account_file)
        self.assertEqual(app.thumbnail_path, None)


# ---------------------------------------------------------------------------
# Publish timeout and login mapping
# ---------------------------------------------------------------------------


class PublishLoopTests(unittest.TestCase):
    def _video(self) -> TiktokVideo:
        return TiktokVideo("标题", "/tmp/demo.mp4", [], 0, None)

    def test_publish_timeout_is_15_minutes(self):
        self.assertEqual(TIKTOK_PUBLISH_TIMEOUT_SECONDS, 15 * 60)

    def test_detect_upload_status_stops_at_deadline(self):
        video = self._video()
        page = MagicMock()
        page.url = TIKTOK_UPLOAD_URL
        with (
            patch.object(tk_main.time, "monotonic", return_value=1000.0),
            patch.object(tk_main.asyncio, "sleep", AsyncMock()) as sleep,
        ):
            with self.assertRaises(RuntimeError):
                asyncio.run(
                    video.wait_media_ready(
                        page, deadline=999.0, multilogin=True
                    )
                )
        sleep.assert_not_awaited()

    def test_click_publish_stops_at_deadline(self):
        video = self._video()
        page = MagicMock()
        page.url = TIKTOK_UPLOAD_URL
        video.locator_base = MagicMock()
        with (
            patch.object(tk_main.time, "monotonic", return_value=1000.0),
            patch.object(tk_main.asyncio, "sleep", AsyncMock()) as sleep,
        ):
            with self.assertRaises(RuntimeError):
                asyncio.run(
                    video.click_publish(page, deadline=999.0, multilogin=True)
                )
        sleep.assert_not_awaited()

    def test_login_redirect_mid_upload_raises_login_required(self):
        video = self._video()
        page = MagicMock()
        page.url = "https://www.tiktok.com/login?lang=en"
        with patch.object(tk_main.asyncio, "sleep", AsyncMock()) as sleep:
            with self.assertRaises(LoginRequiredError):
                asyncio.run(
                    video.wait_media_ready(page, multilogin=True)
                )
        sleep.assert_not_awaited()

    def test_captcha_mid_upload_raises_login_required(self):
        video = self._video()
        page = MagicMock()
        page.url = "https://www.tiktok.com/captcha/verify"
        with patch.object(tk_main.asyncio, "sleep", AsyncMock()):
            with self.assertRaises(LoginRequiredError):
                asyncio.run(video.click_publish(page, multilogin=True))

# ---------------------------------------------------------------------------
# CLI check
# ---------------------------------------------------------------------------


class TiktokCheckCliTests(unittest.TestCase):
    def _session(self):
        session = Namespace(context=object())
        session_cm = _AsyncCM(session)
        factory = MagicMock(return_value=session_cm)
        return session, session_cm, factory

    def test_logged_in_returns_0(self):
        session, session_cm, factory = self._session()
        probe = AsyncMock(return_value=True)
        playwright_cm = _AsyncCM(object())

        with (
            patch.object(tiktok_command, "async_playwright", lambda: playwright_cm),
            patch.object(tiktok_command, "browser_session", new=factory),
            patch.object(tiktok_command, "is_logged_in", new=probe),
        ):
            code, out, _ = _run(
                [
                    "tiktok",
                    "check",
                    "--folder-id",
                    "folder",
                    "--profile-id",
                    "profile",
                ]
            )

        self.assertEqual(code, 0)
        self.assertIn("valid", out)
        self.assertEqual(factory.call_args.kwargs["headless"], True)
        self.assertEqual(
            factory.call_args.kwargs["multilogin"].profile_id, "profile"
        )
        probe.assert_awaited_once_with(session.context)
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_headed_flag_is_passed(self):
        session, _, factory = self._session()
        with (
            patch.object(tiktok_command, "async_playwright", lambda: _AsyncCM(object())),
            patch.object(tiktok_command, "browser_session", new=factory),
            patch.object(tiktok_command, "is_logged_in", new=AsyncMock(return_value=True)),
        ):
            code, _, _ = _run(
                [
                    "tiktok",
                    "check",
                    "--folder-id",
                    "folder",
                    "--profile-id",
                    "profile",
                    "--headed",
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(factory.call_args.kwargs["headless"], False)

    def test_logged_out_returns_10(self):
        session, session_cm, factory = self._session()
        with (
            patch.object(tiktok_command, "async_playwright", lambda: _AsyncCM(object())),
            patch.object(tiktok_command, "browser_session", new=factory),
            patch.object(tiktok_command, "is_logged_in", new=AsyncMock(return_value=False)),
        ):
            code, out, err = _run(
                [
                    "tiktok",
                    "check",
                    "--folder-id",
                    "folder",
                    "--profile-id",
                    "profile",
                ]
            )
        self.assertEqual(code, 10)
        self.assertNotIn("valid", out)
        self.assertIn("profile", err)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_probe_error_returns_1_and_session_exits_once(self):
        session, session_cm, factory = self._session()
        with (
            patch.object(tiktok_command, "async_playwright", lambda: _AsyncCM(object())),
            patch.object(tiktok_command, "browser_session", new=factory),
            patch.object(
                tiktok_command,
                "is_logged_in",
                new=AsyncMock(side_effect=RuntimeError("page failed")),
            ),
        ):
            code, _, err = _run(
                [
                    "tiktok",
                    "check",
                    "--folder-id",
                    "folder",
                    "--profile-id",
                    "profile",
                ]
            )
        self.assertEqual(code, 1)
        self.assertIn("page failed", err)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_session_enter_failure_returns_1(self):
        session_cm = _AsyncCM(enter_error=RuntimeError("launcher down"))
        factory = MagicMock(return_value=session_cm)
        with (
            patch.object(tiktok_command, "async_playwright", lambda: _AsyncCM(object())),
            patch.object(tiktok_command, "browser_session", new=factory),
            patch.object(tiktok_command, "is_logged_in", new=AsyncMock(return_value=True)),
        ):
            code, _, err = _run(
                [
                    "tiktok",
                    "check",
                    "--folder-id",
                    "folder",
                    "--profile-id",
                    "profile",
                ]
            )
        self.assertEqual(code, 1)
        self.assertIn("launcher down", err)

    def test_missing_target_exits_2_without_browser(self):
        factory = MagicMock()
        with (
            patch.object(tiktok_command, "async_playwright", MagicMock()),
            patch.object(tiktok_command, "browser_session", new=factory),
        ):
            code, _, err = _run(["tiktok", "check"])
        self.assertEqual(code, 2)
        self.assertIn("--folder-id", err)
        factory.assert_not_called()


# ---------------------------------------------------------------------------
# CLI upload
# ---------------------------------------------------------------------------


class TiktokUploadCliTests(unittest.TestCase):
    def _session(self):
        session = Namespace(context=object())
        session_cm = _AsyncCM(session)
        factory = MagicMock(return_value=session_cm)
        return session, session_cm, factory

    def _fake_app(self):
        app = MagicMock()
        app.upload = AsyncMock()
        return app

    def test_upload_success_returns_0_and_uses_one_session(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = Path(tmp_dir) / "demo.mp4"
            video.write_bytes(b"video")

            session, session_cm, factory = self._session()
            app = self._fake_app()
            builder = MagicMock(return_value=app)
            probe = AsyncMock(return_value=True)
            playwright_cm = _AsyncCM(object())

            with (
                patch.object(tiktok_command, "async_playwright", lambda: playwright_cm),
                patch.object(tiktok_command, "browser_session", new=factory),
                patch.object(tiktok_command, "is_logged_in", new=probe),
                patch.object(tiktok_command, "_build_video_uploader", new=builder),
            ):
                code, out, _ = _run(
                    [
                        "tiktok",
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
                )

        self.assertEqual(code, 0)
        self.assertIn("TikTok video upload submitted", out)
        kwargs = factory.call_args.kwargs
        self.assertIsNone(kwargs["account_file"])
        self.assertEqual(kwargs["launch_kwargs"], TIKTOK_LAUNCH_KWARGS)
        self.assertEqual(kwargs["context_kwargs"], TIKTOK_CONTEXT_KWARGS)
        self.assertEqual(kwargs["init_script"], TIKTOK_INIT_SCRIPT)
        probe.assert_awaited_once_with(session.context)
        app.upload.assert_awaited_once_with(None, session=session)
        request = builder.call_args.args[0]
        self.assertEqual(request.account_label, "profile")
        self.assertIsNone(request.thumbnail_file)
        self.assertEqual(request.publish_date, 0)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_upload_parses_tags_schedule_thumbnail_and_account_label(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = Path(tmp_dir) / "demo.mp4"
            video.write_bytes(b"video")
            thumbnail = Path(tmp_dir) / "thumb.png"
            thumbnail.write_bytes(b"image")

            _, _, factory = self._session()
            app = self._fake_app()
            builder = MagicMock(return_value=app)

            with (
                patch.object(tiktok_command, "async_playwright", lambda: _AsyncCM(object())),
                patch.object(tiktok_command, "browser_session", new=factory),
                patch.object(tiktok_command, "is_logged_in", new=AsyncMock(return_value=True)),
                patch.object(tiktok_command, "_build_video_uploader", new=builder),
            ):
                code, _, _ = _run(
                    [
                        "tiktok",
                        "upload-video",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--account",
                        "creator",
                        "--file",
                        str(video),
                        "--title",
                        "标题",
                        "--tags",
                        "#one, two",
                        "--schedule",
                        "2026-11-05 10:30",
                        "--thumbnail",
                        str(thumbnail),
                    ]
                )

        self.assertEqual(code, 0)
        request = builder.call_args.args[0]
        self.assertEqual(request.account_label, "creator")
        self.assertEqual(request.tags, ["one", "two"])
        self.assertEqual(request.publish_date, datetime(2026, 11, 5, 10, 30))
        self.assertEqual(request.thumbnail_file, thumbnail)

    def test_logged_out_returns_10_and_skips_upload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = Path(tmp_dir) / "demo.mp4"
            video.write_bytes(b"video")

            _, session_cm, factory = self._session()
            app = self._fake_app()

            with (
                patch.object(tiktok_command, "async_playwright", lambda: _AsyncCM(object())),
                patch.object(tiktok_command, "browser_session", new=factory),
                patch.object(tiktok_command, "is_logged_in", new=AsyncMock(return_value=False)),
                patch.object(
                    tiktok_command, "_build_video_uploader", new=MagicMock(return_value=app)
                ),
            ):
                code, out, err = _run(
                    [
                        "tiktok",
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
                )

        self.assertEqual(code, 10)
        self.assertNotIn("submitted", out)
        self.assertIn("profile", err)
        app.upload.assert_not_awaited()
        self.assertEqual(session_cm.exit_calls, 1)

    def test_upload_failure_returns_1_and_session_exits_once(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = Path(tmp_dir) / "demo.mp4"
            video.write_bytes(b"video")

            _, session_cm, factory = self._session()
            app = self._fake_app()
            app.upload = AsyncMock(side_effect=RuntimeError("publish failed"))

            with (
                patch.object(tiktok_command, "async_playwright", lambda: _AsyncCM(object())),
                patch.object(tiktok_command, "browser_session", new=factory),
                patch.object(tiktok_command, "is_logged_in", new=AsyncMock(return_value=True)),
                patch.object(
                    tiktok_command, "_build_video_uploader", new=MagicMock(return_value=app)
                ),
            ):
                code, _, err = _run(
                    [
                        "tiktok",
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
                )

        self.assertEqual(code, 1)
        self.assertIn("publish failed", err)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_login_probe_runs_once_before_upload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = Path(tmp_dir) / "demo.mp4"
            video.write_bytes(b"video")

            order: list[str] = []
            app = self._fake_app()

            async def probe(_context):
                order.append("probe")
                return True

            async def upload(_playwright, *, session):
                order.append("upload")

            app.upload = upload

            with (
                patch.object(tiktok_command, "async_playwright", lambda: _AsyncCM(object())),
                patch.object(tiktok_command, "browser_session", new=MagicMock(return_value=_AsyncCM(Namespace(context=object())))),
                patch.object(tiktok_command, "is_logged_in", new=probe),
                patch.object(
                    tiktok_command, "_build_video_uploader", new=MagicMock(return_value=app)
                ),
            ):
                code, _, _ = _run(
                    [
                        "tiktok",
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
                )

        self.assertEqual(code, 0)
        self.assertEqual(order, ["probe", "upload"])


# ---------------------------------------------------------------------------
# Real browser_session integration: Stop is owned by the seam, exactly once
# ---------------------------------------------------------------------------


class _FakeClient:
    instances: list["_FakeClient"] = []

    def __init__(self, token: str) -> None:
        self.token = token
        self.probe_calls = 0
        self.start_calls: list[tuple[str, str, bool]] = []
        self.stop_calls: list[str] = []
        self.status_calls: list[str] = []
        _FakeClient.instances.append(self)

    def probe(self) -> None:
        self.probe_calls += 1

    def start(self, folder_id: str, profile_id: str, headless: bool) -> str:
        self.start_calls.append((folder_id, profile_id, headless))
        return "9222"

    def status(self, profile_id: str) -> str:
        self.status_calls.append(profile_id)
        return "running"

    def stop(self, profile_id: str) -> None:
        self.stop_calls.append(profile_id)


class StopOwnershipTests(unittest.TestCase):
    def test_stop_is_called_exactly_once_by_browser_session(self):
        _FakeClient.instances.clear()
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = Path(tmp_dir) / "demo.mp4"
            video.write_bytes(b"video")

            playwright = FakePlaywright()
            browser = playwright.chromium.new_browser([FakeContext()])
            playwright.chromium.queue_connect_browser(browser)

            with (
                patch("utils.browser_session.MultiloginClient", _FakeClient),
                patch.object(tiktok_command, "async_playwright", lambda: _AsyncCM(playwright)),
                patch.object(tiktok_command, "is_logged_in", new=AsyncMock(return_value=True)),
                patch.object(TiktokVideo, "upload", new=AsyncMock()) as upload,
            ):
                code, _, err = _run(
                    [
                        "tiktok",
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
                )

        self.assertEqual(code, 0, err)
        client = _FakeClient.instances[0]
        self.assertEqual(client.token, TOKEN)
        self.assertEqual(client.probe_calls, 1)
        self.assertEqual(client.start_calls, [("folder", "profile", True)])
        self.assertEqual(client.stop_calls, ["profile"])
        self.assertEqual(playwright.chromium.connect_calls[0]["url"], "http://127.0.0.1:9222")
        self.assertTrue(browser.closed)
        upload.assert_awaited_once()
        session = upload.await_args.kwargs["session"]
        self.assertEqual(session.mode, "multilogin")
        self.assertFalse(hasattr(session, "stop"))


if __name__ == "__main__":
    unittest.main()
