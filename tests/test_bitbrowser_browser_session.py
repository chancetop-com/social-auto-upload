# -*- coding: utf-8 -*-
"""BitBrowser connections and diagnostics outside a managed CLI command."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from tests.fakes import (
    FakeBitBrowserClient,
    FakeBrowser,
    FakeContext,
    FakePlaywright,
)
from utils.bitbrowser import BitBrowserProvider, BitBrowserTarget
from utils.browser_session import browser_session

PROFILE = "window-ticket07"
WS_URL = "ws://127.0.0.1:9222/devtools/browser/ticket07-abc"


def run(coro):
    return asyncio.run(coro)


def _provider(client: FakeBitBrowserClient) -> BitBrowserProvider:
    return BitBrowserProvider(BitBrowserTarget(PROFILE), client)


class BitBrowserLifecycleTests(unittest.TestCase):
    def test_happy_path_order_and_ws_endpoint_is_verbatim(self):
        events: list[str] = []
        client = FakeBitBrowserClient(ws_url=WS_URL, events=events)
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
                self.assertEqual(session.mode, "bitbrowser")
                self.assertIs(session.managed, True)
                self.assertIs(session.browser, browser)
                self.assertIs(session.context, context)

        with patch("utils.browser_session.logger.info") as info:
            run(scenario())

        self.assertEqual(
            events, ["probe", "start", "connect", "browser.close", "stop"]
        )
        self.assertEqual(client.probe_calls, 1)
        self.assertEqual(client.start_calls, [(PROFILE, True)])
        self.assertEqual(client.stop_calls, [PROFILE])
        self.assertEqual(playwright.chromium.launch_calls, [])
        self.assertEqual(browser.new_context_calls, [])

        connect = playwright.chromium.connect_calls[0]
        self.assertEqual(connect["url"], WS_URL)
        self.assertEqual(connect["timeout"], 10000)
        self.assertIs(connect["no_defaults"], True)

        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, [])
        context_setup.assert_not_called()

        rendered = " ".join(str(call) for call in info.call_args_list)
        self.assertIn(PROFILE, rendered)
        self.assertIn("127.0.0.1:9222", rendered)
        self.assertIn("mode=bitbrowser", rendered)
        self.assertNotIn("/devtools/browser", rendered)
        self.assertNotIn("Multilogin", rendered)

    def test_connect_retries_three_times_then_queries_status_and_stops(self):
        events: list[str] = []
        client = FakeBitBrowserClient(events=events)
        playwright = FakePlaywright(events=events)
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
        self.assertIn("bitbrowser", message)
        self.assertIn(PROFILE, message)
        self.assertIn("127.0.0.1:9222", message)
        self.assertIn("已尝试 3 次", message)
        self.assertIn("running", message)
        self.assertIn("比特浏览器", message)
        self.assertIn("BITBROWSER_API_BASE", message)
        self.assertNotIn("Docker", message)

        self.assertEqual(len(playwright.chromium.connect_calls), 3)
        self.assertEqual(
            [call.args[0] for call in sleep.await_args_list], [2, 4]
        )
        self.assertEqual(client.status_calls, [PROFILE])
        self.assertEqual(client.stop_calls, [PROFILE])
        self.assertEqual(events[-1], "stop")


if __name__ == "__main__":
    unittest.main()
