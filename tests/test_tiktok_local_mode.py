# -*- coding: utf-8 -*-
"""TikTok local (non-Multilogin) cookie helpers.

All tests are offline: browser launches are mocked and no network is touched.
"""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from conf import BASE_DIR
from sau_commands.arguments import resolve_account_file
from uploader.tk_uploader import main_chrome as tk_main
from uploader.tk_uploader.tk_config import TIKTOK_LOCAL_ENTRY_WAIT_MS
from utils.files_times import get_absolute_path


class AccountFileTests(unittest.TestCase):
    def test_local_entry_wait_allows_client_rendered_studio(self):
        self.assertEqual(TIKTOK_LOCAL_ENTRY_WAIT_MS, 20_000)

    def test_local_cookie_name_is_platform_and_account(self):
        path = resolve_account_file("tiktok", "creator")
        self.assertEqual(path.name, "tiktok_creator.json")
        self.assertEqual(path.parent.name, "cookies")


class AbsolutePathTests(unittest.TestCase):
    def test_absolute_path_is_preserved(self):
        path = "/tmp/tiktok_creator.json"
        self.assertEqual(get_absolute_path(path, "tk_uploader"), path)

    def test_relative_path_still_joins_base_dir(self):
        expected = str(Path(BASE_DIR) / "tk_uploader" / "account.json")
        self.assertEqual(
            get_absolute_path("account.json", "tk_uploader"), expected
        )


class _AsyncCM:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _BoomChromium:
    async def launch(self, **kwargs):
        raise OSError("no browser binary")


class _BoomPlaywright:
    def __init__(self, chromium):
        self.chromium = chromium


class _UnreadableCookieBrowser:
    async def new_context(self, **kwargs):
        raise ValueError("malformed storage state")

    async def close(self):
        pass


class _UnreadableCookieChromium:
    async def launch(self, **kwargs):
        return _UnreadableCookieBrowser()


class _BoomCM:
    async def __aenter__(self):
        raise OSError("playwright driver missing")

    async def __aexit__(self, exc_type, exc, tb):
        return False


class CookieAuthTests(unittest.TestCase):
    def test_playwright_start_failure_returns_false(self):
        with patch.object(tk_main, "async_playwright", lambda: _BoomCM()):
            self.assertFalse(
                asyncio.run(tk_main.cookie_auth("/tmp/tiktok_creator.json"))
            )

    def test_launch_failure_returns_false(self):
        playwright = _BoomPlaywright(_BoomChromium())
        with patch.object(
            tk_main, "async_playwright", lambda: _AsyncCM(playwright)
        ):
            self.assertFalse(
                asyncio.run(tk_main.cookie_auth("/tmp/tiktok_creator.json"))
            )

    def test_unreadable_cookie_returns_false(self):
        playwright = _BoomPlaywright(_UnreadableCookieChromium())
        with patch.object(
            tk_main, "async_playwright", lambda: _AsyncCM(playwright)
        ):
            self.assertFalse(
                asyncio.run(tk_main.cookie_auth("/tmp/tiktok_creator.json"))
            )


class TiktokSetupTests(unittest.TestCase):
    def test_missing_cookie_without_handle_skips_auth(self):
        with (
            patch.object(tk_main.os.path, "exists", return_value=False),
            patch.object(tk_main, "cookie_auth", AsyncMock()) as auth,
        ):
            result = asyncio.run(
                tk_main.tiktok_setup("/tmp/missing.json", handle=False)
            )
        self.assertFalse(result)
        auth.assert_not_awaited()

    def test_invalid_cookie_without_handle_returns_false(self):
        with (
            patch.object(tk_main.os.path, "exists", return_value=True),
            patch.object(
                tk_main, "cookie_auth", AsyncMock(return_value=False)
            ) as auth,
            patch.object(tk_main, "get_tiktok_cookie", AsyncMock()) as login,
        ):
            result = asyncio.run(
                tk_main.tiktok_setup(
                    "/tmp/tiktok_creator.json",
                    handle=False,
                    headless=False,
                )
            )
        self.assertFalse(result)
        login.assert_not_awaited()
        auth.assert_awaited_once_with(
            "/tmp/tiktok_creator.json", headless=False
        )

    def test_handle_runs_login_then_revalidates(self):
        auth = AsyncMock(side_effect=[False, True])
        login = AsyncMock(return_value="/tmp/tiktok_creator.json")
        with (
            patch.object(tk_main.os.path, "exists", return_value=True),
            patch.object(tk_main, "cookie_auth", auth),
            patch.object(tk_main, "get_tiktok_cookie", login),
        ):
            result = asyncio.run(
                tk_main.tiktok_setup(
                    "/tmp/tiktok_creator.json", handle=True, headless=False
                )
            )
        self.assertTrue(result)
        login.assert_awaited_once_with("/tmp/tiktok_creator.json")
        self.assertEqual(auth.await_count, 2)

    def test_valid_cookie_without_force_does_not_open_login(self):
        auth = AsyncMock(return_value=True)
        login = AsyncMock()
        with (
            patch.object(tk_main.os.path, "exists", return_value=True),
            patch.object(tk_main, "cookie_auth", auth),
            patch.object(tk_main, "get_tiktok_cookie", login),
        ):
            result = asyncio.run(
                tk_main.tiktok_setup("/tmp/tiktok_creator.json", handle=True)
            )
        self.assertTrue(result)
        login.assert_not_awaited()

    def test_force_login_opens_browser_even_when_cookie_valid(self):
        auth = AsyncMock(return_value=True)
        login = AsyncMock(return_value="/tmp/tiktok_creator.json")
        with (
            patch.object(tk_main.os.path, "exists", return_value=True),
            patch.object(tk_main, "cookie_auth", auth),
            patch.object(tk_main, "get_tiktok_cookie", login),
        ):
            result = asyncio.run(
                tk_main.tiktok_setup(
                    "/tmp/tiktok_creator.json",
                    handle=True,
                    headless=False,
                    force=True,
                )
            )
        self.assertTrue(result)
        login.assert_awaited_once_with("/tmp/tiktok_creator.json")
        self.assertEqual(auth.await_count, 1)

    def test_get_cookie_rejects_non_interactive_terminal(self):
        with patch.object(tk_main.sys.stdin, "isatty", return_value=False):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(
                    tk_main.get_tiktok_cookie("/tmp/tiktok_creator.json")
                )
        self.assertIn("交互式终端", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
