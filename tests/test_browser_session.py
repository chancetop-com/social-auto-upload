# -*- coding: utf-8 -*-
"""Offline lifecycle tests for ``utils.browser_session``.

The local branch must stay behaviour-equivalent to the existing uploaders; the
MLX branch must follow spec §5.4/§5.5 exactly.  All fakes are hand-written so
that touching a forbidden Playwright API fails loudly.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from tests.fakes import (
    FakeBrowser,
    FakeContext,
    FakeManagedProvider,
    FakeMultiloginClient,
    FakePlaywright,
    ForbiddenApiError,
)
from utils.browser_session import (
    BrowserSession,
    browser_session,
    log_local_session_ready,
    provider_label,
)
from utils.multilogin import MultiloginProvider, MultiloginTarget

TOKEN = "ticket15-secret-token"
FOLDER_ID = "22222222-2222-4222-8222-222222222222"
PROFILE_ID = "33333333-3333-4333-8333-333333333333"


def run(coro):
    return asyncio.run(coro)


class ProviderLabelTests(unittest.TestCase):
    def test_each_mode_has_its_own_product_label(self):
        # AdsPower must never be presented as Multilogin: the label is the only
        # product name several error/warning lines show to the user.
        self.assertEqual(provider_label("multilogin"), "Multilogin")
        self.assertEqual(provider_label("adspower"), "AdsPower")
        self.assertEqual(provider_label("local"), "local")

    def test_provider_label_is_public_and_has_no_private_alias(self):
        module = importlib.import_module("utils.browser_session")
        self.assertIn("provider_label", module.__all__)
        self.assertFalse(hasattr(module, "_provider_label"))


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
        context_setup = Mock()

        async def scenario():
            async with browser_session(
                playwright,
                headless=True,
                account_file="/tmp/must-not-be-read.json",
                managed=MultiloginProvider(self.target, client),
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

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=MultiloginProvider(self.target, client)
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

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=MultiloginProvider(self.target, client)
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

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=MultiloginProvider(self.target, client)
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

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=MultiloginProvider(self.target, client)
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

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=MultiloginProvider(self.target, client)
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

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=MultiloginProvider(self.target, client)
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

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=MultiloginProvider(self.target, client)
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

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=MultiloginProvider(self.target, client)
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

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=MultiloginProvider(self.target, client)
            ):
                raise ValueError("original failure")

        with patch("utils.browser_session.logger.warning") as warning:
            with self.assertRaisesRegex(ValueError, "original failure"):
                run(scenario())

        warning.assert_called_once()
        self.assertEqual(client.stop_calls, [PROFILE_ID])

    def test_start_log_matches_single_startup_line(self):
        events: list[str] = []
        client = FakeMultiloginClient(events=events)
        playwright = FakePlaywright(events=events)
        browser = self._browser(events)
        playwright.chromium.queue_connect_browser(browser)

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=MultiloginProvider(self.target, client)
            ):
                pass

        with patch("utils.browser_session.logger.info") as info:
            run(scenario())

        startup = [
            call
            for call in info.call_args_list
            if str(call.args[0]).startswith("browser session ready: ")
        ]
        self.assertEqual(len(startup), 1)
        self.assertEqual(
            startup[0].args[0],
            "browser session ready: mode=multilogin, headless=headless, "
            f"identity=profile:{PROFILE_ID}, ignored=-, "
            f"folder_id={FOLDER_ID}, port=55513",
        )

    def test_contexts_error_matches_legacy_mlx_wording(self):
        events: list[str] = []
        client = FakeMultiloginClient(events=events)
        playwright = FakePlaywright(events=events)
        browser = self._browser(events, [])
        playwright.chromium.queue_connect_browser(browser)

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=MultiloginProvider(self.target, client)
            ):
                pass

        with self.assertRaises(RuntimeError) as caught:
            run(scenario())

        self.assertEqual(
            str(caught.exception),
            "Multilogin Profile 的浏览器上下文数量异常"
            f"（期望 1，实际 0）：profile_id={PROFILE_ID}",
        )

    def test_cdp_failure_matches_legacy_mlx_wording_and_port(self):
        events: list[str] = []
        client = FakeMultiloginClient(events=events, status_value="download_core_error")
        playwright = FakePlaywright(events=events)
        for _ in range(3):
            playwright.chromium.queue_connect_error(ConnectionError("refused"))

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=MultiloginProvider(self.target, client)
            ):
                pass

        with patch("utils.browser_session.asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(RuntimeError) as caught:
                run(scenario())

        self.assertEqual(
            str(caught.exception),
            "无法通过 CDP 连接 Multilogin Profile"
            f"（profile_id={PROFILE_ID}，port=55513，"
            "已尝试 3 次）：refused；"
            "Profile 状态：download_core_error。"
            "若你使用 Docker launcher，CDP 端口默认未映射到宿主机；"
            "v1 请改用 Multilogin 桌面应用。",
        )

    def test_disconnect_warning_matches_legacy_mlx_wording(self):
        events: list[str] = []
        client = FakeMultiloginClient(events=events)
        playwright = FakePlaywright(events=events)
        browser = self._browser(events)
        browser.close_error = RuntimeError("disconnect failed")
        playwright.chromium.queue_connect_browser(browser)

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=MultiloginProvider(self.target, client)
            ):
                pass

        with patch("utils.browser_session.logger.warning") as warning:
            run(scenario())

        self.assertEqual(
            warning.call_args.args[0],
            "断开 Multilogin 浏览器连接失败：{}；已上传结果不受影响。",
        )
        self.assertEqual(str(warning.call_args.args[1]), "disconnect failed")

    def test_stop_log_matches_legacy_mlx_wording(self):
        events: list[str] = []
        client = FakeMultiloginClient(events=events)
        playwright = FakePlaywright(events=events)
        browser = self._browser(events)
        playwright.chromium.queue_connect_browser(browser)

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=MultiloginProvider(self.target, client)
            ):
                pass

        with patch("utils.browser_session.logger.info") as info:
            run(scenario())

        stop_calls = [
            call
            for call in info.call_args_list
            if call.args[0] == "正在停止 Multilogin Profile：profile_id={}"
        ]
        self.assertEqual(len(stop_calls), 1)
        self.assertEqual(stop_calls[0].args[1], PROFILE_ID)

    def test_browser_close_failure_warns_and_still_stops(self):
        events: list[str] = []
        client = FakeMultiloginClient(events=events)
        playwright = FakePlaywright(events=events)
        browser = self._browser(events)
        browser.close_error = RuntimeError("disconnect failed")
        playwright.chromium.queue_connect_browser(browser)

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=MultiloginProvider(self.target, client)
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

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=MultiloginProvider(self.target, client)
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

    def test_injected_provider_runs_without_reading_token_environment(self):
        events: list[str] = []
        client = FakeMultiloginClient(events=events)
        playwright = FakePlaywright(events=events)
        browser = self._browser(events)
        playwright.chromium.queue_connect_browser(browser)

        async def scenario():
            async with browser_session(
                playwright,
                headless=True,
                managed=MultiloginProvider(self.target, client),
            ) as session:
                self.assertEqual(session.mode, "multilogin")

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MLX_API_TOKEN", None)
            run(scenario())

        self.assertEqual(client.probe_calls, 1)
        self.assertEqual(client.start_calls, [(FOLDER_ID, PROFILE_ID, True)])
        self.assertEqual(client.stop_calls, [PROFILE_ID])

    def test_forbidden_apis_raise_loudly_if_mlx_touches_them(self):
        context = FakeContext()

        with self.assertRaises(ForbiddenApiError):
            asyncio.run(context.add_cookies([]))
        with self.assertRaises(ForbiddenApiError):
            asyncio.run(FakeBrowser().new_context())


class ManagedSessionSeamTests(unittest.TestCase):
    def test_managed_property_truth_table(self):
        for mode, expected in (
            ("local", False),
            ("multilogin", True),
            ("adspower", True),
        ):
            with self.subTest(mode=mode):
                session = BrowserSession(browser=object(), context=object(), mode=mode)
                self.assertIs(session.managed, expected)

    def test_generic_provider_endpoint_is_passed_to_connect_over_cdp_verbatim(self):
        ws_url = "ws://127.0.0.1:9222/devtools/browser/abc"
        events: list[str] = []
        provider = FakeManagedProvider(
            mode="adspower", profile_id="profile-1", connect_url=ws_url, events=events
        )
        playwright = FakePlaywright(events=events)
        browser = FakeBrowser(
            [FakeContext(events=events)], allow_new_context=False, events=events
        )
        playwright.chromium.queue_connect_browser(browser)

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=provider
            ) as session:
                self.assertEqual(session.mode, "adspower")
                self.assertIs(session.managed, True)

        run(scenario())

        self.assertEqual(playwright.chromium.connect_calls[0]["url"], ws_url)
        self.assertEqual(
            events,
            ["probe", "start", "connect", "browser.close", "stop"],
        )
        self.assertEqual(provider.start_calls, [True])
        self.assertEqual(provider.stop_calls, 1)


class ManagedIgnoredKeysTests(unittest.TestCase):
    """Managed mode drops local browser options; the user must be told once."""

    FULL_WARNING = (
        "托管模式忽略本地浏览器参数：launch_kwargs, context_kwargs, init_script"
        "；Profile 负责指纹与界面语言，语言/UA/时区请在 Profile 内设置"
    )

    def _run_managed(self, **kwargs):
        events: list[str] = []
        provider = FakeManagedProvider(
            mode="adspower", profile_id="profile-1", events=events
        )
        playwright = FakePlaywright(events=events)
        playwright.chromium.queue_connect_browser(
            FakeBrowser(
                [FakeContext(events=events)],
                allow_new_context=False,
                events=events,
            )
        )

        async def scenario():
            async with browser_session(
                playwright, headless=True, managed=provider, **kwargs
            ):
                pass

        run(scenario())

    def test_non_empty_managed_options_warn_once_with_key_names_only(self):
        with patch("utils.browser_session.logger.warning") as warning:
            self._run_managed(
                launch_kwargs={"channel": "chromium"},
                context_kwargs={"locale": "zh-CN"},
                init_script=True,
            )

        warning.assert_called_once()
        message = warning.call_args.args[0]
        self.assertEqual(message, self.FULL_WARNING)
        # Key names only: no option values ever reach the log.
        self.assertNotIn("chromium", message)
        self.assertNotIn("zh-CN", message)

    def test_empty_values_do_not_count_as_ignored(self):
        with patch("utils.browser_session.logger.warning") as warning:
            self._run_managed(
                launch_kwargs={},
                context_kwargs=None,
                init_script=False,
                context_setup=None,
            )

        warning.assert_not_called()

    def test_context_setup_counts_as_an_ignored_key(self):
        async def context_setup(context):
            return context

        with patch("utils.browser_session.logger.warning") as warning:
            self._run_managed(context_setup=context_setup)

        warning.assert_called_once()
        self.assertEqual(
            warning.call_args.args[0],
            "托管模式忽略本地浏览器参数：context_setup"
            "；Profile 负责指纹与界面语言，语言/UA/时区请在 Profile 内设置",
        )

    def test_extra_ignored_keys_join_the_single_warning_and_startup_log(self):
        with (
            patch("utils.browser_session.logger.warning") as warning,
            patch("utils.browser_session.logger.info") as info,
        ):
            self._run_managed(
                launch_kwargs={"channel": "chromium"},
                extra_ignored=("account",),
            )

        warning.assert_called_once()
        self.assertEqual(
            warning.call_args.args[0],
            "托管模式忽略本地浏览器参数：launch_kwargs, account"
            "；Profile 负责指纹与界面语言，语言/UA/时区请在 Profile 内设置",
        )
        startup = [
            call
            for call in info.call_args_list
            if str(call.args[0]).startswith("browser session ready: ")
        ]
        self.assertEqual(len(startup), 1)
        self.assertIn("ignored=launch_kwargs, account,", startup[0].args[0])

    def test_local_mode_with_the_same_options_never_warns(self):
        playwright = FakePlaywright()

        async def scenario():
            async with browser_session(
                playwright,
                headless=True,
                account_file="/tmp/cookie.json",
                launch_kwargs={"channel": "chromium"},
                context_kwargs={"locale": "zh-CN"},
                init_script=True,
            ):
                pass

        with (
            patch("utils.browser_session.logger.warning") as warning,
            patch(
                "utils.browser_session.set_init_script",
                new=AsyncMock(side_effect=lambda ctx: ctx),
            ),
        ):
            run(scenario())

        warning.assert_not_called()


class StartupLogTests(unittest.TestCase):
    """Exactly one startup line per run, in both modes, with fixed fields."""

    STARTUP_PREFIX = "browser session ready: "

    def _startup_calls(self, info):
        return [
            call
            for call in info.call_args_list
            if str(call.args[0]).startswith(self.STARTUP_PREFIX)
        ]

    def _run_local(self, *, headless=True, account_file="/tmp/cookie.json"):
        playwright = FakePlaywright()

        async def scenario():
            async with browser_session(
                playwright, headless=headless, account_file=account_file
            ):
                pass

        run(scenario())

    def test_local_startup_log_has_mode_headless_identity_and_ignored(self):
        with patch("utils.browser_session.logger.info") as info:
            self._run_local(headless=False)

        startup = self._startup_calls(info)
        self.assertEqual(len(startup), 1)
        self.assertEqual(
            startup[0].args[0],
            "browser session ready: mode=local, headless=headed, "
            "identity=account_file:/tmp/cookie.json, ignored=-",
        )

    def test_local_helper_emits_the_same_single_line(self):
        with patch("utils.browser_session.logger.info") as info:
            log_local_session_ready(
                headless=False, account_file="/tmp/cookie.json"
            )

        startup = self._startup_calls(info)
        self.assertEqual(len(startup), 1)
        self.assertEqual(
            startup[0].args[0],
            "browser session ready: mode=local, headless=headed, "
            "identity=account_file:/tmp/cookie.json, ignored=-",
        )

    def test_local_headless_labelling(self):
        with patch("utils.browser_session.logger.info") as info:
            self._run_local(headless=True)

        startup = self._startup_calls(info)
        self.assertEqual(len(startup), 1)
        self.assertIn("headless=headless,", startup[0].args[0])

    def test_local_without_account_file_still_reports_identity(self):
        with patch("utils.browser_session.logger.info") as info:
            self._run_local(headless=True, account_file=None)

        startup = self._startup_calls(info)
        self.assertEqual(len(startup), 1)
        self.assertIn("identity=account_file:-", startup[0].args[0])

    def test_mlx_startup_log_folds_the_legacy_profile_line(self):
        events: list[str] = []
        provider = MultiloginProvider(
            MultiloginTarget(folder_id=FOLDER_ID, profile_id=PROFILE_ID),
            FakeMultiloginClient(events=events),
        )
        playwright = FakePlaywright(events=events)
        playwright.chromium.queue_connect_browser(
            FakeBrowser(
                [FakeContext(events=events)],
                allow_new_context=False,
                events=events,
            )
        )

        async def scenario():
            async with browser_session(
                playwright,
                headless=False,
                managed=provider,
                launch_kwargs={"channel": "chromium"},
                context_kwargs={"locale": "zh-CN"},
                init_script=True,
            ):
                pass

        with patch("utils.browser_session.logger.info") as info:
            run(scenario())

        startup = self._startup_calls(info)
        self.assertEqual(len(startup), 1)
        self.assertEqual(
            startup[0].args[0],
            "browser session ready: mode=multilogin, headless=headed, "
            f"identity=profile:{PROFILE_ID}, "
            "ignored=launch_kwargs, context_kwargs, init_script, "
            f"folder_id={FOLDER_ID}, port=55513",
        )
        self.assertFalse(
            any("Profile 已启动" in str(call) for call in info.call_args_list)
        )

    def test_adspower_startup_log_reports_endpoint_and_ignored_dash(self):
        ws_url = "ws://127.0.0.1:9222/devtools/browser/abc"
        events: list[str] = []
        provider = FakeManagedProvider(
            mode="adspower",
            profile_id="profile-1",
            connect_url=ws_url,
            events=events,
        )
        playwright = FakePlaywright(events=events)
        playwright.chromium.queue_connect_browser(
            FakeBrowser(
                [FakeContext(events=events)],
                allow_new_context=False,
                events=events,
            )
        )

        async def scenario():
            async with browser_session(
                playwright, headless=False, managed=provider
            ):
                pass

        with patch("utils.browser_session.logger.info") as info:
            run(scenario())

        startup = self._startup_calls(info)
        self.assertEqual(len(startup), 1)
        self.assertEqual(
            startup[0].args[0],
            "browser session ready: mode=adspower, headless=headed, "
            "identity=profile:profile-1, ignored=-, endpoint=127.0.0.1:9222",
        )


if __name__ == "__main__":
    unittest.main()
