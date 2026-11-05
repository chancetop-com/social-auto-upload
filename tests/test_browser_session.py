# -*- coding: utf-8 -*-
"""Offline lifecycle tests for ``utils.browser_session``.

The local branch must stay behaviour-equivalent to the existing uploaders; the
MLX branch must follow spec §5.4/§5.5 exactly.  All fakes are hand-written so
that touching a forbidden Playwright API fails loudly.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from tests.fakes import (
    FakeBrowser,
    FakeContext,
    FakeMultiloginClient,
    FakePlaywright,
    ForbiddenApiError,
)
from utils.browser_session import browser_session
from utils.multilogin import MultiloginTarget

TOKEN = "ticket15-secret-token"
FOLDER_ID = "22222222-2222-4222-8222-222222222222"
PROFILE_ID = "33333333-3333-4333-8333-333333333333"


def run(coro):
    return asyncio.run(coro)


class LocalBrowserSessionTests(unittest.TestCase):
    def test_launch_new_context_and_teardown_parameters_are_forwarded(self):
        events: list[str] = []
        playwright = FakePlaywright(events=events)
        account_file = Path("/tmp/ticket15-cookie.json")
        launch_kwargs = {
            "channel": "chromium",
            "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        }
        context_kwargs = {"permissions": ["geolocation"]}
        setup_calls: list[object] = []

        async def context_setup(context):
            setup_calls.append(context)
            return None

        async def scenario():
            async with browser_session(
                playwright,
                headless=True,
                account_file=account_file,
                launch_kwargs=launch_kwargs,
                context_kwargs=context_kwargs,
                init_script=True,
                context_setup=context_setup,
            ) as session:
                self.assertEqual(session.mode, "local")
                self.assertIs(session.browser, playwright.chromium.launch_browser)
                self.assertEqual(len(playwright.chromium.launch_browser.contexts), 1)
                self.assertIs(session.context, playwright.chromium.launch_browser.contexts[0])
                return session.context

        with patch(
            "utils.browser_session.set_init_script", new=AsyncMock(side_effect=lambda ctx: ctx)
        ) as init_script:
            context = run(scenario())

        self.assertEqual(
            playwright.chromium.launch_calls,
            [{"headless": True, **launch_kwargs}],
        )
        browser = playwright.chromium.launch_browser
        self.assertEqual(
            browser.new_context_calls,
            [{"storage_state": account_file, **context_kwargs}],
        )
        init_script.assert_awaited_once_with(context)
        self.assertEqual(setup_calls, [context])
        self.assertEqual(context.storage_state_calls, [account_file])
        self.assertTrue(context.closed)
        self.assertTrue(browser.closed)
        self.assertEqual(events, ["launch", "context.close", "browser.close"])

    def test_local_defaults_skip_init_script_and_context_setup(self):
        playwright = FakePlaywright()

        async def scenario():
            async with browser_session(
                playwright,
                headless=False,
                account_file="/tmp/cookie.json",
            ):
                pass

        with patch("utils.browser_session.set_init_script", new=AsyncMock()) as init_script:
            run(scenario())

        init_script.assert_not_awaited()
        context = playwright.chromium.launch_browser.contexts[0]
        self.assertEqual(context.add_init_script_calls, [])

    def test_local_writes_storage_state_only_on_normal_exit(self):
        playwright = FakePlaywright()
        account_file = "/tmp/cookie.json"

        async def scenario():
            async with browser_session(
                playwright, headless=True, account_file=account_file
            ):
                raise ValueError("upload failed")

        with self.assertRaisesRegex(ValueError, "upload failed"):
            run(scenario())

        context = playwright.chromium.launch_browser.contexts[0]
        self.assertEqual(context.storage_state_calls, [])
        self.assertTrue(context.closed)
        self.assertTrue(playwright.chromium.launch_browser.closed)

    def test_local_without_account_file_does_not_write_storage_state(self):
        playwright = FakePlaywright()

        async def scenario():
            async with browser_session(playwright, headless=True, account_file=None):
                pass

        run(scenario())

        browser = playwright.chromium.launch_browser
        context = browser.contexts[0]
        self.assertEqual(browser.new_context_calls, [{"storage_state": None}])
        self.assertEqual(context.storage_state_calls, [])

    def test_context_setup_return_value_replaces_context(self):
        playwright = FakePlaywright()
        replacement = FakeContext()

        async def context_setup(context):
            self.assertIs(context, playwright.chromium.launch_browser.contexts[0])
            return replacement

        async def scenario():
            async with browser_session(
                playwright,
                headless=True,
                account_file="/tmp/cookie.json",
                context_setup=context_setup,
            ) as session:
                self.assertIs(session.context, replacement)
                return session.context

        run(scenario())

        self.assertEqual(replacement.storage_state_calls, ["/tmp/cookie.json"])
        self.assertTrue(replacement.closed)

    def test_context_setup_runs_after_init_script(self):
        playwright = FakePlaywright()
        order: list[str] = []

        async def fake_init(context):
            order.append("init_script")
            return context

        async def context_setup(context):
            order.append("context_setup")
            return context

        async def scenario():
            async with browser_session(
                playwright,
                headless=True,
                init_script=True,
                context_setup=context_setup,
            ):
                pass

        with patch("utils.browser_session.set_init_script", new=fake_init):
            run(scenario())

        self.assertEqual(order, ["init_script", "context_setup"])

    def test_local_rejects_headless_in_launch_kwargs(self):
        playwright = FakePlaywright()

        async def scenario():
            async with browser_session(
                playwright, headless=True, launch_kwargs={"headless": False}
            ):
                pass

        with self.assertRaisesRegex(ValueError, "headless"):
            run(scenario())

    def test_local_rejects_storage_state_in_context_kwargs(self):
        playwright = FakePlaywright()

        async def scenario():
            async with browser_session(
                playwright,
                headless=True,
                context_kwargs={"storage_state": "cookie.json"},
            ):
                pass

        with self.assertRaisesRegex(ValueError, "storage_state"):
            run(scenario())

    def test_session_does_not_expose_owned_or_stop(self):
        playwright = FakePlaywright()

        async def scenario():
            async with browser_session(playwright, headless=True) as session:
                self.assertFalse(hasattr(session, "owned"))
                self.assertFalse(hasattr(session, "stop"))

        run(scenario())


class MultiloginBrowserSessionTests(unittest.TestCase):
    def setUp(self):
        self.target = MultiloginTarget(folder_id=FOLDER_ID, profile_id=PROFILE_ID)
        self.env = patch.dict(os.environ, {"MLX_API_TOKEN": TOKEN})
        self.env.start()
        self.addCleanup(self.env.stop)

    def _patch_client(self, client):
        patcher = patch("utils.browser_session.MultiloginClient", return_value=client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _browser(self, events, contexts=None):
        browser = FakeBrowser(
            contexts if contexts is not None else [FakeContext(events=events)],
            allow_new_context=False,
            events=events,
        )
        return browser

    def test_happy_path_lifecycle_and_forbidden_local_apis_are_never_used(self):
        events: list[str] = []
        client = FakeMultiloginClient(events=events)
        playwright = FakePlaywright(events=events)
        context = FakeContext(events=events)
        browser = self._browser(events, [context])
        playwright.chromium.queue_connect_browser(browser)
        self._patch_client(client)
        context_setup = Mock()

        async def scenario():
            async with browser_session(
                playwright,
                headless=True,
                account_file="/tmp/must-not-be-read.json",
                multilogin=self.target,
                launch_kwargs={"channel": "chromium"},
                context_kwargs={"permissions": ["geolocation"]},
                init_script=True,
                context_setup=context_setup,
            ) as session:
                self.assertEqual(session.mode, "multilogin")
                self.assertIs(session.browser, browser)
                self.assertIs(session.context, context)

        run(scenario())

        self.assertEqual(events, ["probe", "start", "connect", "browser.close", "stop"])
        self.assertEqual(client.probe_calls, 1)
        self.assertEqual(client.start_calls, [(FOLDER_ID, PROFILE_ID, True)])
        self.assertEqual(len(playwright.chromium.connect_calls), 1)
        connect = playwright.chromium.connect_calls[0]
        self.assertEqual(connect["url"], "http://127.0.0.1:55513")
        self.assertEqual(connect["timeout"], 10000)
        self.assertIs(connect["no_defaults"], True)
        self.assertEqual(client.stop_calls, [PROFILE_ID])
        self.assertEqual(playwright.chromium.launch_calls, [])
        self.assertEqual(browser.new_context_calls, [])
        self.assertEqual(context.add_init_script_calls, [])
        self.assertEqual(context.storage_state_calls, [])
        context_setup.assert_not_called()
        self.assertFalse(context.closed)

    def test_start_failure_does_not_stop_someone_elses_profile(self):
        client = FakeMultiloginClient(start_error=RuntimeError("HTTP 500 can't lock profile"))
        playwright = FakePlaywright()
        self._patch_client(client)

        async def scenario():
            async with browser_session(
                playwright, headless=True, multilogin=self.target
            ):
                pass

        with self.assertRaisesRegex(RuntimeError, "can't lock profile"):
            run(scenario())

        self.assertEqual(client.probe_calls, 1)
        self.assertEqual(client.stop_calls, [])
        self.assertEqual(playwright.chromium.connect_calls, [])

    def test_probe_failure_does_not_start_or_stop(self):
        client = FakeMultiloginClient(probe_error=RuntimeError("launcher unavailable"))
        playwright = FakePlaywright()
        self._patch_client(client)

        async def scenario():
            async with browser_session(
                playwright, headless=True, multilogin=self.target
            ):
                pass

        with self.assertRaisesRegex(RuntimeError, "launcher unavailable"):
            run(scenario())

        self.assertEqual(client.start_calls, [])
        self.assertEqual(client.stop_calls, [])

    def test_connect_retries_three_times_with_two_and_four_second_backoff(self):
        events: list[str] = []
        client = FakeMultiloginClient(events=events)
        playwright = FakePlaywright(events=events)
        browser = self._browser(events)
        playwright.chromium.queue_connect_error(ConnectionError("refused"))
        playwright.chromium.queue_connect_error(TimeoutError("timed out"))
        playwright.chromium.queue_connect_browser(browser)
        self._patch_client(client)

        async def scenario():
            async with browser_session(
                playwright, headless=True, multilogin=self.target
            ):
                pass

        with patch("utils.browser_session.asyncio.sleep", new=AsyncMock()) as sleep:
            run(scenario())

        self.assertEqual(len(playwright.chromium.connect_calls), 3)
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [2, 4])
        self.assertEqual(client.status_calls, [])
        self.assertEqual(client.stop_calls, [PROFILE_ID])

    def test_connect_failure_queries_status_once_enriches_error_and_stops(self):
        events: list[str] = []
        client = FakeMultiloginClient(events=events, status_value="download_core_error")
        playwright = FakePlaywright(events=events)
        for _ in range(3):
            playwright.chromium.queue_connect_error(ConnectionError("refused"))
        self._patch_client(client)

        async def scenario():
            async with browser_session(
                playwright, headless=True, multilogin=self.target
            ):
                pass

        with patch("utils.browser_session.asyncio.sleep", new=AsyncMock()) as sleep:
            with self.assertRaises(RuntimeError) as caught:
                run(scenario())

        message = str(caught.exception)
        self.assertIn("download_core_error", message)
        self.assertIn("Docker launcher", message)
        self.assertNotIn(TOKEN, message)
        self.assertEqual(len(playwright.chromium.connect_calls), 3)
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [2, 4])
        self.assertEqual(client.status_calls, [PROFILE_ID])
        self.assertEqual(client.stop_calls, [PROFILE_ID])
        self.assertEqual(events[-1], "stop")

    def test_zero_contexts_fails_fast_and_still_stops(self):
        events: list[str] = []
        client = FakeMultiloginClient(events=events)
        playwright = FakePlaywright(events=events)
        browser = self._browser(events, [])
        playwright.chromium.queue_connect_browser(browser)
        self._patch_client(client)

        async def scenario():
            async with browser_session(
                playwright, headless=True, multilogin=self.target
            ):
                pass

        with self.assertRaisesRegex(RuntimeError, "上下文数量"):
            run(scenario())

        self.assertEqual(browser.new_context_calls, [])
        self.assertEqual(browser.close_calls, 1)
        self.assertEqual(client.stop_calls, [PROFILE_ID])

    def test_multiple_contexts_fail_fast_and_still_stop(self):
        events: list[str] = []
        client = FakeMultiloginClient(events=events)
        playwright = FakePlaywright(events=events)
        browser = self._browser(
            events, [FakeContext(events=events), FakeContext(events=events)]
        )
        playwright.chromium.queue_connect_browser(browser)
        self._patch_client(client)

        async def scenario():
            async with browser_session(
                playwright, headless=True, multilogin=self.target
            ):
                pass

        with self.assertRaisesRegex(RuntimeError, "上下文数量"):
            run(scenario())

        self.assertEqual(browser.new_context_calls, [])
        self.assertEqual(client.stop_calls, [PROFILE_ID])

    def test_body_exception_is_preserved_and_stop_is_issued(self):
        events: list[str] = []
        client = FakeMultiloginClient(events=events)
        playwright = FakePlaywright(events=events)
        browser = self._browser(events)
        playwright.chromium.queue_connect_browser(browser)
        self._patch_client(client)

        async def scenario():
            async with browser_session(
                playwright, headless=True, multilogin=self.target
            ):
                raise ValueError("upload blew up")

        with self.assertRaisesRegex(ValueError, "upload blew up"):
            run(scenario())

        self.assertEqual(client.stop_calls, [PROFILE_ID])
        self.assertEqual(browser.close_calls, 1)

    def test_stop_failure_after_success_warns_but_does_not_fail(self):
        events: list[str] = []
        client = FakeMultiloginClient(events=events, stop_error=RuntimeError("stop boom"))
        playwright = FakePlaywright(events=events)
        browser = self._browser(events)
        playwright.chromium.queue_connect_browser(browser)
        self._patch_client(client)

        async def scenario():
            async with browser_session(
                playwright, headless=True, multilogin=self.target
            ):
                pass

        with patch("utils.browser_session.logger.warning") as warning:
            run(scenario())

        warning.assert_called_once()
        self.assertIn("stop boom", str(warning.call_args))
        self.assertEqual(client.stop_calls, [PROFILE_ID])

    def test_stop_failure_does_not_mask_original_exception(self):
        events: list[str] = []
        client = FakeMultiloginClient(events=events, stop_error=RuntimeError("stop boom"))
        playwright = FakePlaywright(events=events)
        browser = self._browser(events)
        playwright.chromium.queue_connect_browser(browser)
        self._patch_client(client)

        async def scenario():
            async with browser_session(
                playwright, headless=True, multilogin=self.target
            ):
                raise ValueError("original failure")

        with patch("utils.browser_session.logger.warning") as warning:
            with self.assertRaisesRegex(ValueError, "original failure"):
                run(scenario())

        warning.assert_called_once()
        self.assertEqual(client.stop_calls, [PROFILE_ID])

    def test_browser_close_failure_warns_and_still_stops(self):
        events: list[str] = []
        client = FakeMultiloginClient(events=events)
        playwright = FakePlaywright(events=events)
        browser = self._browser(events)
        browser.close_error = RuntimeError("disconnect failed")
        playwright.chromium.queue_connect_browser(browser)
        self._patch_client(client)

        async def scenario():
            async with browser_session(
                playwright, headless=True, multilogin=self.target
            ):
                pass

        with patch("utils.browser_session.logger.warning") as warning:
            run(scenario())

        warning.assert_called_once()
        self.assertIn("disconnect failed", str(warning.call_args))
        self.assertEqual(client.stop_calls, [PROFILE_ID])

    def test_cancellation_issues_stop_under_shield(self):
        events: list[str] = []
        client = FakeMultiloginClient(events=events)
        playwright = FakePlaywright(events=events)
        browser = self._browser(events)
        playwright.chromium.queue_connect_browser(browser)
        self._patch_client(client)

        async def scenario():
            async with browser_session(
                playwright, headless=True, multilogin=self.target
            ):
                entered.set()
                await asyncio.sleep(60)

        async def main():
            task = asyncio.ensure_future(scenario())
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        entered = asyncio.Event()
        with patch(
            "utils.browser_session.asyncio.shield", wraps=asyncio.shield
        ) as shield:
            asyncio.run(main())

        shield.assert_called_once()
        self.assertEqual(client.stop_calls, [PROFILE_ID])

    def test_missing_token_fails_before_starting_profile(self):
        playwright = FakePlaywright()
        client = FakeMultiloginClient()
        self._patch_client(client)

        async def scenario():
            async with browser_session(
                playwright, headless=True, multilogin=self.target
            ):
                pass

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MLX_API_TOKEN", None)
            with self.assertRaisesRegex(RuntimeError, "MLX_API_TOKEN"):
                run(scenario())

        self.assertEqual(client.probe_calls, 0)
        self.assertEqual(client.start_calls, [])

    def test_forbidden_apis_raise_loudly_if_mlx_touches_them(self):
        context = FakeContext()

        with self.assertRaises(ForbiddenApiError):
            asyncio.run(context.add_cookies([]))
        with self.assertRaises(ForbiddenApiError):
            asyncio.run(FakeBrowser().new_context())


if __name__ == "__main__":
    unittest.main()
