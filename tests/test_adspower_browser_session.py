# -*- coding: utf-8 -*-
"""Offline AdsPower provider/session composition tests (ticket 13).

The generic ``_managed_session`` template is exercised in
``test_browser_session.py``; this file only covers the AdsPower composition and
normalisation rules: the ws endpoint is forwarded verbatim, ``StartIncompleteError``
triggers a best-effort stop while other start failures never do, cancellation
still stops the profile, and stop failures stay warnings.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from tests.fakes import (
    FakeAdspowerClient,
    FakeBrowser,
    FakeContext,
    FakePlaywright,
)
from utils.adspower import AdspowerProvider, AdspowerTarget
from utils.browser_session import browser_session
from utils.errors import RateLimitedError, StartIncompleteError

PROFILE = "profile-ticket13"
WS_URL = "ws://127.0.0.1:9222/devtools/browser/ticket13-abc"


def run(coro):
    return asyncio.run(coro)


def _provider(client: FakeAdspowerClient) -> AdspowerProvider:
    return AdspowerProvider(AdspowerTarget(PROFILE), client)


class AdspowerLifecycleTests(unittest.TestCase):
    def test_happy_path_order_and_ws_endpoint_is_verbatim(self):
        events: list[str] = []
        client = FakeAdspowerClient(ws_url=WS_URL, events=events)
        playwright = FakePlaywright(events=events)
        context = FakeContext(events=events)
        browser = FakeBrowser([context], allow_new_context=False, events=events)
        playwright.chromium.queue_connect_browser(browser)
        context_setup = Mock()

        async def scenario():
            async with browser_session(
                playwright,
                headless=True,
                account_file="/tmp/must-not-be-read.json",
                managed=_provider(client),
                launch_kwargs={"channel": "chromium"},
                context_kwargs={"permissions": ["geolocation"]},
                init_script=True,
                context_setup=context_setup,
            ) as session:
                self.assertEqual(session.mode, "adspower")
                self.assertIs(session.managed, True)
                self.assertIs(session.browser, browser)
                self.assertIs(session.context, context)

        with patch("utils.browser_session.logger.info") as info:
            run(scenario())

        self.assertEqual(events, ["probe", "start", "connect", "browser.close", "stop"])
        self.assertEqual(client.probe_calls, 1)
        self.assertEqual(client.start_calls, [(PROFILE, True)])
        self.assertEqual(client.stop_calls, [PROFILE])
        self.assertEqual(playwright.chromium.launch_calls, [])
        self.assertEqual(browser.new_context_calls, [])

        connect = playwright.chromium.connect_calls[0]
        self.assertEqual(connect["url"], WS_URL)
        self.assertFalse(connect["url"].startswith("http"))
        self.assertEqual(connect["timeout"], 10000)
        self.assertIs(connect["no_defaults"], True)

        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, [])
        context_setup.assert_not_called()

        rendered = " ".join(str(call) for call in info.call_args_list)
        self.assertIn(PROFILE, rendered)
        self.assertIn("127.0.0.1:9222", rendered)
        self.assertNotIn("/devtools/browser", rendered)
        self.assertNotIn("Multilogin", rendered)

    def test_start_incomplete_stops_profile_before_reraising(self):
        events: list[str] = []
        client = FakeAdspowerClient(
            events=events, start_error=StartIncompleteError("缺少 data.ws.puppeteer")
        )
        playwright = FakePlaywright(events=events)

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=_provider(client)
            ):
                pass

        with self.assertRaisesRegex(StartIncompleteError, "data.ws.puppeteer"):
            run(scenario())

        self.assertEqual(events, ["probe", "start", "stop"])
        self.assertEqual(client.stop_calls, [PROFILE])
        self.assertEqual(playwright.chromium.connect_calls, [])

    def test_start_incomplete_stop_failure_only_warns(self):
        events: list[str] = []
        client = FakeAdspowerClient(
            events=events,
            start_error=StartIncompleteError("bad start"),
            stop_error=RuntimeError("stop boom"),
        )
        playwright = FakePlaywright(events=events)

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=_provider(client)
            ):
                pass

        with patch("utils.browser_session.logger.warning") as warning:
            with self.assertRaisesRegex(StartIncompleteError, "bad start"):
                run(scenario())

        warning.assert_called_once()
        self.assertIn("stop boom", str(warning.call_args))
        self.assertEqual(client.stop_calls, [PROFILE])

    def test_rate_limited_on_probe_does_not_start_or_stop(self):
        events: list[str] = []
        client = FakeAdspowerClient(
            events=events, probe_error=RateLimitedError("probe 429")
        )
        playwright = FakePlaywright(events=events)

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=_provider(client)
            ):
                pass

        with self.assertRaisesRegex(RateLimitedError, "429"):
            run(scenario())

        self.assertEqual(events, ["probe"])
        self.assertEqual(client.stop_calls, [])

    def test_rate_limited_on_start_does_not_stop(self):
        events: list[str] = []
        client = FakeAdspowerClient(
            events=events, start_error=RateLimitedError("start 429")
        )
        playwright = FakePlaywright(events=events)

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=_provider(client)
            ):
                pass

        with self.assertRaisesRegex(RateLimitedError, "429"):
            run(scenario())

        self.assertEqual(events, ["probe", "start"])
        self.assertEqual(client.stop_calls, [])
        self.assertEqual(playwright.chromium.connect_calls, [])

    def test_zero_contexts_fails_fast_after_connect_and_still_stops(self):
        events: list[str] = []
        client = FakeAdspowerClient(events=events)
        playwright = FakePlaywright(events=events)
        browser = FakeBrowser([], allow_new_context=False, events=events)
        playwright.chromium.queue_connect_browser(browser)

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=_provider(client)
            ):
                pass

        with self.assertRaisesRegex(RuntimeError, "上下文数量"):
            run(scenario())

        self.assertEqual(browser.close_calls, 1)
        self.assertEqual(client.stop_calls, [PROFILE])

    def test_multiple_contexts_fail_fast_and_still_stop(self):
        events: list[str] = []
        client = FakeAdspowerClient(events=events)
        playwright = FakePlaywright(events=events)
        browser = FakeBrowser(
            [FakeContext(events=events), FakeContext(events=events)],
            allow_new_context=False,
            events=events,
        )
        playwright.chromium.queue_connect_browser(browser)

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=_provider(client)
            ):
                pass

        with self.assertRaisesRegex(RuntimeError, "上下文数量"):
            run(scenario())

        self.assertEqual(client.stop_calls, [PROFILE])

    def test_connect_retries_three_times_then_queries_status_and_stops(self):
        events: list[str] = []
        client = FakeAdspowerClient(events=events, status_value="Active")
        playwright = FakePlaywright(events=events)
        # AdsPower's connect URL is a ws:// endpoint, not an http port.
        for _ in range(3):
            playwright.chromium.queue_connect_error(ConnectionError("refused"))

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=_provider(client)
            ):
                pass

        with patch("utils.browser_session.asyncio.sleep", new=AsyncMock()) as sleep:
            with self.assertRaises(RuntimeError) as caught:
                run(scenario())

        message = str(caught.exception)
        self.assertIn("adspower", message.lower())
        self.assertIn(PROFILE, message)
        self.assertIn("127.0.0.1:9222", message)
        self.assertIn("已尝试 3 次", message)
        self.assertIn("Active", message)
        self.assertNotIn("Docker", message)

        self.assertEqual(len(playwright.chromium.connect_calls), 3)
        self.assertEqual(
            [call.args[0] for call in sleep.await_args_list], [2, 4]
        )
        self.assertEqual(client.status_calls, [PROFILE])
        self.assertEqual(client.stop_calls, [PROFILE])
        self.assertEqual(events[-1], "stop")

    def test_connect_failure_status_query_failure_degrades_to_query_failed(self):
        events: list[str] = []
        client = FakeAdspowerClient(
            events=events, status_error=RuntimeError("status boom")
        )
        playwright = FakePlaywright(events=events)
        for _ in range(3):
            playwright.chromium.queue_connect_error(ConnectionError("refused"))

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=_provider(client)
            ):
                pass

        with patch("utils.browser_session.asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(RuntimeError) as caught:
                run(scenario())

        message = str(caught.exception)
        self.assertIn("查询失败", message)
        self.assertIn("status boom", message)
        self.assertIn("adspower", message.lower())
        self.assertNotIn("Multilogin", message)
        self.assertEqual(client.stop_calls, [PROFILE])

    def test_stop_failure_after_success_only_warns(self):
        events: list[str] = []
        client = FakeAdspowerClient(
            events=events, stop_error=RuntimeError("stop boom")
        )
        playwright = FakePlaywright(events=events)
        browser = FakeBrowser([FakeContext(events=events)], allow_new_context=False)
        playwright.chromium.queue_connect_browser(browser)

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=_provider(client)
            ):
                pass

        with patch("utils.browser_session.logger.warning") as warning:
            run(scenario())

        warning.assert_called_once()
        self.assertIn("stop boom", str(warning.call_args))
        self.assertEqual(client.stop_calls, [PROFILE])

    def test_stop_rate_limited_does_not_change_the_observed_result(self):
        events: list[str] = []
        client = FakeAdspowerClient(
            events=events, stop_error=RateLimitedError("stop 429")
        )
        playwright = FakePlaywright(events=events)
        browser = FakeBrowser([FakeContext(events=events)], allow_new_context=False)
        playwright.chromium.queue_connect_browser(browser)
        result: list[str] = []

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=_provider(client)
            ):
                result.append("ok")

        with patch("utils.browser_session.logger.warning") as warning:
            run(scenario())

        self.assertEqual(result, ["ok"])
        warning.assert_called_once()
        self.assertEqual(client.stop_calls, [PROFILE])

    def test_stop_failure_does_not_mask_the_body_exception(self):
        events: list[str] = []
        client = FakeAdspowerClient(
            events=events, stop_error=RuntimeError("stop boom")
        )
        playwright = FakePlaywright(events=events)
        browser = FakeBrowser([FakeContext(events=events)], allow_new_context=False)
        playwright.chromium.queue_connect_browser(browser)

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=_provider(client)
            ):
                raise ValueError("original failure")

        with patch("utils.browser_session.logger.warning"):
            with self.assertRaisesRegex(ValueError, "original failure"):
                run(scenario())

        self.assertEqual(client.stop_calls, [PROFILE])

    def test_disconnect_failure_only_warns_and_still_stops(self):
        events: list[str] = []
        client = FakeAdspowerClient(events=events)
        playwright = FakePlaywright(events=events)
        browser = FakeBrowser([FakeContext(events=events)], allow_new_context=False)
        browser.close_error = RuntimeError("disconnect failed")
        playwright.chromium.queue_connect_browser(browser)

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=_provider(client)
            ):
                pass

        with patch("utils.browser_session.logger.warning") as warning:
            run(scenario())

        warning.assert_called_once()
        self.assertIn("disconnect failed", str(warning.call_args))
        self.assertEqual(client.stop_calls, [PROFILE])

    def test_cancellation_still_stops_under_shield(self):
        events: list[str] = []
        client = FakeAdspowerClient(events=events)
        playwright = FakePlaywright(events=events)
        browser = FakeBrowser([FakeContext(events=events)], allow_new_context=False)
        playwright.chromium.queue_connect_browser(browser)
        entered = asyncio.Event()

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=_provider(client)
            ):
                entered.set()
                await asyncio.sleep(60)

        async def main():
            task = asyncio.ensure_future(scenario())
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        with patch(
            "utils.browser_session.asyncio.shield", wraps=asyncio.shield
        ) as shield:
            asyncio.run(main())

        shield.assert_called_once()
        self.assertEqual(client.stop_calls, [PROFILE])


if __name__ == "__main__":
    unittest.main()
