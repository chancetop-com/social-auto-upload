# -*- coding: utf-8 -*-
"""Douyin login probe and the ``sau douyin check`` Multilogin path (ticket 16)."""

from __future__ import annotations

import asyncio
import io
import os
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

import sau_cli
from sau_commands import douyin as douyin_command
from uploader.douyin_uploader import main as douyin_main

TOKEN = "SENTINEL-MLX-TOKEN-douyin"


class _Response:
    def __init__(self, status: int = 200) -> None:
        self.status = status


class _Locator:
    def __init__(self, count: int = 0, visible: bool = False) -> None:
        self._count = count
        self._visible = visible

    @property
    def first(self) -> "_Locator":
        return self

    async def count(self) -> int:
        return self._count

    async def is_visible(self) -> bool:
        return self._visible


class _Page:
    def __init__(
        self,
        *,
        final_url: str,
        status: int = 200,
        goto_error: BaseException | None = None,
        login_visible: bool = False,
    ) -> None:
        self.url = "about:blank"
        self.final_url = final_url
        self.status = status
        self.goto_error = goto_error
        self.login_visible = login_visible
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

    def get_by_text(self, text: str, exact: bool = False) -> _Locator:
        return _Locator(count=1 if self.login_visible else 0, visible=self.login_visible)

    def get_by_role(self, role: str, name: str | None = None) -> _Locator:
        return _Locator(count=0, visible=False)

    async def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class _Context:
    def __init__(self, page: _Page) -> None:
        self.page = page
        self.new_page_calls = 0

    async def new_page(self) -> _Page:
        self.new_page_calls += 1
        return self.page


class IsLoggedInTests(unittest.TestCase):
    def _probe(self, page: _Page) -> bool:
        context = _Context(page)
        result = asyncio.run(douyin_main.is_logged_in(context))
        self.assertEqual(context.new_page_calls, 1)
        self.assertTrue(page.closed)
        self.assertEqual(page.close_calls, 1)
        return result

    def test_logged_in_returns_true_with_one_page(self):
        page = _Page(final_url="https://creator.douyin.com/creator-micro/content/upload")
        self.assertTrue(self._probe(page))
        self.assertEqual(
            page.goto_calls[0][0],
            "https://creator.douyin.com/creator-micro/content/upload",
        )
        timeout = page.goto_calls[0][1]["timeout"]
        self.assertGreaterEqual(timeout, 15_000)
        self.assertLessEqual(timeout, 30_000)

    def test_login_page_returns_false(self):
        page = _Page(final_url="https://creator.douyin.com/")
        self.assertFalse(self._probe(page))

    def test_visible_login_marker_on_creator_micro_returns_false(self):
        page = _Page(
            final_url="https://creator.douyin.com/creator-micro/content/upload",
            login_visible=True,
        )
        self.assertFalse(self._probe(page))

    def test_network_error_propagates(self):
        page = _Page(
            final_url="https://creator.douyin.com/creator-micro/content/upload",
            goto_error=RuntimeError("net::ERR_CONNECTION_RESET"),
        )
        context = _Context(page)
        with self.assertRaises(RuntimeError):
            asyncio.run(douyin_main.is_logged_in(context))
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(page.close_calls, 1)

    def test_server_error_propagates(self):
        page = _Page(
            final_url="https://creator.douyin.com/creator-micro/content/upload",
            status=503,
        )
        context = _Context(page)
        with self.assertRaises(RuntimeError):
            asyncio.run(douyin_main.is_logged_in(context))
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(page.close_calls, 1)

    def test_unexpected_domain_propagates(self):
        page = _Page(final_url="https://example.com/something")
        context = _Context(page)
        with self.assertRaises(RuntimeError):
            asyncio.run(douyin_main.is_logged_in(context))
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(page.close_calls, 1)


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


class DouyinCheckCliTests(unittest.TestCase):
    def _run(self, argv, token=TOKEN):
        with patch.dict(os.environ, {"MLX_API_TOKEN": token}):
            with redirect_stdout(io.StringIO()) as out, redirect_stderr(
                io.StringIO()
            ) as err:
                code = sau_cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_logged_in_returns_0_and_enters_session_once(self):
        playwright_cm = _AsyncCM(object())
        session = Namespace(context=object())
        session_cm = _AsyncCM(session)
        probe = AsyncMock(return_value=True)

        with (
            patch.object(
                douyin_command, "async_playwright", lambda: playwright_cm
            ),
            patch.object(douyin_command, "browser_session", return_value=session_cm),
            patch.object(douyin_command, "is_logged_in", new=probe),
        ):
            code, out, _ = self._run(
                [
                    "douyin",
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

    def test_logged_out_returns_10(self):
        playwright_cm = _AsyncCM(object())
        session_cm = _AsyncCM(Namespace(context=object()))
        probe = AsyncMock(return_value=False)

        with (
            patch.object(
                douyin_command, "async_playwright", lambda: playwright_cm
            ),
            patch.object(douyin_command, "browser_session", return_value=session_cm),
            patch.object(douyin_command, "is_logged_in", new=probe),
        ):
            code, out, _ = self._run(
                [
                    "douyin",
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

    def test_probe_error_returns_1_and_still_exits_session_once(self):
        playwright_cm = _AsyncCM(object())
        session_cm = _AsyncCM(Namespace(context=object()))
        probe = AsyncMock(side_effect=RuntimeError("page failed"))

        with (
            patch.object(
                douyin_command, "async_playwright", lambda: playwright_cm
            ),
            patch.object(douyin_command, "browser_session", return_value=session_cm),
            patch.object(douyin_command, "is_logged_in", new=probe),
        ):
            code, _, _ = self._run(
                [
                    "douyin",
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

    def test_session_enter_failure_returns_1(self):
        playwright_cm = _AsyncCM(object())
        session_cm = _AsyncCM(
            Namespace(context=object()), enter_error=RuntimeError("launcher down")
        )

        with (
            patch.object(
                douyin_command, "async_playwright", lambda: playwright_cm
            ),
            patch.object(douyin_command, "browser_session", return_value=session_cm),
            patch.object(
                douyin_command, "is_logged_in", new=AsyncMock(return_value=True)
            ),
        ):
            code, _, err = self._run(
                [
                    "douyin",
                    "check",
                    "--folder-id",
                    "folder",
                    "--profile-id",
                    "profile",
                ]
            )

        self.assertEqual(code, 1)
        self.assertIn("launcher down", err)

    def test_missing_ids_exits_2_without_browser(self):
        session_factory = MagicMock()

        with patch.object(
            douyin_command, "browser_session", new=session_factory
        ):
            code, _, _ = self._run(["douyin", "check", "--account", "creator"])

        self.assertEqual(code, 2)
        session_factory.assert_not_called()

    def test_local_mode_keeps_legacy_check(self):
        with (
            patch.object(
                douyin_command,
                "check_douyin_account",
                new=AsyncMock(return_value=True),
            ),
            patch.object(
                douyin_command, "browser_session", new=MagicMock()
            ) as session_factory,
        ):
            code, out, _ = self._run(
                ["douyin", "check", "--account", "creator"], token=""
            )

        self.assertEqual(code, 0)
        self.assertIn("valid", out)
        session_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
