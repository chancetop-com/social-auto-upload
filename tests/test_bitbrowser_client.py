# -*- coding: utf-8 -*-
"""Offline contract tests for ``utils.bitbrowser`` (ticket 07).

No real network and no ``http.server``: every HTTP call goes through injected
``http_get`` / ``http_post`` callables.  The BitBrowser Local API envelope is
``{"success": bool, "data": ..., "msg": ...}`` and authentication is the
``x-api-key`` header.
"""

from __future__ import annotations

import traceback
import unittest
from unittest.mock import patch

from tests.fakes import FakeHttp, FakeResponse
from utils.bitbrowser import BitBrowserClient, BitBrowserProvider, BitBrowserTarget
from utils.errors import (
    ProviderDiagnosticError,
    ProviderRequestRejected,
    RateLimitedError,
    StartIncompleteError,
)

KEY = "bitbrowser-ticket07-secret-key"
BASE = "http://127.0.0.1:54345"
WINDOW_ID = "window-1a2b3c4d"
WS_URL = "ws://127.0.0.1:9222/devtools/browser/abc-123"
CDP_WS_URL = (
    "ws://127.0.0.1:9333/devtools/browser/"
    "12345678-1234-4234-8234-123456789abc"
)
CDP_VERSION = {
    "Browser": "Chrome/126.0.6478.126",
    "webSocketDebuggerUrl": CDP_WS_URL,
}


class BitBrowserClientProbeTests(unittest.TestCase):
    def _client(self, *outcomes: object) -> tuple[BitBrowserClient, FakeHttp]:
        http = FakeHttp(post_outcomes=list(outcomes))
        return BitBrowserClient(KEY, BASE, http_get=http.get, http_post=http.post), http

    def test_probe_posts_health_with_api_key_and_three_second_timeout(self):
        client, http = self._client(FakeResponse(200, {"success": True, "data": {}}))

        client.probe()

        self.assertEqual(len(http.calls), 1)
        call = http.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], f"{BASE}/health")
        self.assertEqual(call["headers"], {"x-api-key": KEY})
        self.assertEqual(call["timeout"], 3)
        self.assertEqual(call["json"], {})

    def test_authenticated_post_stops_at_redirect(self):
        client, http = self._client(FakeResponse(307, None))
        with self.assertRaisesRegex(ProviderDiagnosticError, "HTTP 307"):
            client.probe()
        self.assertEqual(len(http.post_calls), 1)
        self.assertIs(http.post_calls[0]["allow_redirects"], False)

    def test_probe_connection_failure_uses_fixed_unreachable_message(self):
        client, _ = self._client(OSError("connection refused"))

        with self.assertRaises(RuntimeError) as caught:
            client.probe()

        message = str(caught.exception)
        self.assertIn("无法连接比特浏览器 Local API", message)
        self.assertIn(BASE, message)
        self.assertIn("比特浏览器桌面应用", message)
        self.assertIn("Local API", message)
        self.assertIn("同一台机器", message)
        self.assertIn("端口", message)
        self.assertNotIn(KEY, message)

    def test_probe_401_mentions_api_key_and_token_authentication(self):
        client, _ = self._client(
            FakeResponse(401, {"success": False, "msg": "unauthorized"})
        )

        with self.assertRaises(ProviderDiagnosticError) as caught:
            client.probe()

        message = str(caught.exception)
        self.assertIn("401", message)
        self.assertIn("BITBROWSER_API_KEY", message)
        self.assertIn("Token 鉴权", message)
        self.assertNotIn(KEY, message)

    def test_probe_403_mentions_api_key_and_token_authentication(self):
        client, _ = self._client(
            FakeResponse(403, {"success": False, "msg": "forbidden"})
        )

        with self.assertRaises(ProviderDiagnosticError) as caught:
            client.probe()

        message = str(caught.exception)
        self.assertIn("403", message)
        self.assertIn("BITBROWSER_API_KEY", message)
        self.assertIn("Token 鉴权", message)

    def test_probe_404_mentions_local_api_address_and_client_support(self):
        client, _ = self._client(
            FakeResponse(404, {"success": False, "msg": "not found"})
        )

        with self.assertRaises(ProviderDiagnosticError) as caught:
            client.probe()

        message = str(caught.exception)
        self.assertIn("404", message)
        self.assertIn("BITBROWSER_API_BASE", message)
        self.assertIn("版本", message)

    def test_probe_non_2xx_reports_operation_status_and_msg(self):
        client, _ = self._client(
            FakeResponse(500, {"success": False, "msg": "upstream down"})
        )

        with self.assertRaises(ProviderDiagnosticError) as caught:
            client.probe()

        message = str(caught.exception)
        self.assertIn("探活比特浏览器 Local API", message)
        self.assertIn("HTTP 500", message)
        self.assertIn("upstream down", message)

    def test_probe_business_failure_is_a_runtime_error_not_rate_limited(self):
        client, _ = self._client(
            FakeResponse(
                200,
                {"success": False, "msg": "请求频繁，请稍后再试"},
            )
        )

        with self.assertRaises(ProviderDiagnosticError) as caught:
            client.probe()

        self.assertNotIsInstance(caught.exception, RateLimitedError)
        self.assertIn("HTTP 200", str(caught.exception))
        self.assertIn("请求频繁", str(caught.exception))
        self.assertNotIn(KEY, str(caught.exception))

    def test_probe_malformed_envelope_is_a_runtime_error(self):
        for payload in ({}, {"success": "true"}, {"success": 1}):
            with self.subTest(payload=payload):
                client, _ = self._client(FakeResponse(200, payload))
                with self.assertRaises(RuntimeError) as caught:
                    client.probe()
                self.assertIn("success", str(caught.exception))
                self.assertNotIn(KEY, str(caught.exception))

    def test_probe_invalid_json_is_a_runtime_error(self):
        client, _ = self._client(
            FakeResponse(
                200,
                None,
                text="<html>not json</html>",
                json_error=ValueError("not json"),
            )
        )

        with self.assertRaises(RuntimeError) as caught:
            client.probe()

        self.assertIn("JSON", str(caught.exception))

    def test_probe_429_raises_rate_limited_error_without_retry_or_sleep(self):
        client, http = self._client(
            FakeResponse(429, {"success": False, "msg": "too many requests"})
        )

        with patch("time.sleep", side_effect=AssertionError("client must not sleep")):
            with self.assertRaises(RateLimitedError) as caught:
                client.probe()

        self.assertIn("429", str(caught.exception))
        self.assertIn("请求过于频繁", str(caught.exception))
        self.assertEqual(len(http.calls), 1)


class BitBrowserClientStartTests(unittest.TestCase):
    def _client(self, *outcomes: object) -> tuple[BitBrowserClient, FakeHttp]:
        http = FakeHttp(post_outcomes=list(outcomes))
        return BitBrowserClient(KEY, BASE, http_get=http.get, http_post=http.post), http

    def test_headed_start_posts_only_the_window_id(self):
        client, http = self._client(
            FakeResponse(200, {"success": True, "data": {"ws": WS_URL}})
        )

        url = client.start(WINDOW_ID, headless=False)

        self.assertEqual(url, WS_URL)
        self.assertEqual(len(http.calls), 1)
        call = http.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], f"{BASE}/browser/open")
        self.assertEqual(call["headers"], {"x-api-key": KEY})
        self.assertEqual(call["timeout"], 30)
        self.assertEqual(call["json"], {"id": WINDOW_ID})

    def test_headless_start_adds_args_and_ignore_default_urls(self):
        client, http = self._client(
            FakeResponse(200, {"success": True, "data": {"ws": WS_URL}})
        )

        client.start(WINDOW_ID, headless=True)

        self.assertEqual(
            http.calls[0]["json"],
            {
                "id": WINDOW_ID,
                "args": ["--headless"],
                "ignoreDefaultUrls": True,
            },
        )

    def test_start_returns_data_ws_verbatim(self):
        verbatim = "  ws://127.0.0.1:9222/devtools/browser/abc-123  "
        client, _ = self._client(
            FakeResponse(200, {"success": True, "data": {"ws": verbatim}})
        )

        self.assertEqual(client.start(WINDOW_ID, headless=False), verbatim)

    def test_start_missing_ws_raises_start_incomplete(self):
        client, _ = self._client(FakeResponse(200, {"success": True, "data": {}}))

        with self.assertRaises(StartIncompleteError) as caught:
            client.start(WINDOW_ID, headless=True)

        self.assertIn("data.ws", str(caught.exception))
        self.assertNotIn(KEY, str(caught.exception))

    def test_start_empty_ws_raises_start_incomplete(self):
        client, _ = self._client(
            FakeResponse(200, {"success": True, "data": {"ws": "   "}})
        )

        with self.assertRaises(StartIncompleteError):
            client.start(WINDOW_ID, headless=True)

    def test_start_invalid_json_raises_start_incomplete(self):
        client, _ = self._client(
            FakeResponse(
                200,
                None,
                text="not json",
                json_error=ValueError("not json"),
            )
        )

        with self.assertRaises(StartIncompleteError) as caught:
            client.start(WINDOW_ID, headless=True)

        self.assertIn("JSON", str(caught.exception))

    def test_start_missing_success_raises_start_incomplete(self):
        client, _ = self._client(
            FakeResponse(200, {"data": {"ws": WS_URL}})
        )

        with self.assertRaises(StartIncompleteError) as caught:
            client.start(WINDOW_ID, headless=True)

        self.assertIn("success", str(caught.exception))

    def test_start_business_error_is_not_incomplete_and_reports_msg(self):
        client, _ = self._client(
            FakeResponse(
                200,
                {"success": False, "msg": "窗口不存在或已被删除"},
            )
        )

        with self.assertRaises(RuntimeError) as caught:
            client.start(WINDOW_ID, headless=True)

        self.assertNotIsInstance(caught.exception, StartIncompleteError)
        self.assertIsInstance(caught.exception, ProviderRequestRejected)
        message = str(caught.exception)
        self.assertIn("HTTP 200", message)
        self.assertIn("窗口不存在或已被删除", message)
        self.assertNotIn(KEY, message)

    def test_start_401_mentions_api_key(self):
        client, _ = self._client(
            FakeResponse(401, {"success": False, "msg": "unauthorized"})
        )

        with self.assertRaises(ProviderDiagnosticError) as caught:
            client.start(WINDOW_ID, headless=True)

        self.assertIn("BITBROWSER_API_KEY", str(caught.exception))

    def test_start_404_mentions_local_api_address_and_version(self):
        client, _ = self._client(
            FakeResponse(404, {"success": False, "msg": "not found"})
        )

        with self.assertRaises(ProviderDiagnosticError) as caught:
            client.start(WINDOW_ID, headless=True)

        message = str(caught.exception)
        self.assertIn("BITBROWSER_API_BASE", message)
        self.assertIn("版本", message)

    def test_start_500_reports_status_and_body(self):
        client, _ = self._client(
            FakeResponse(500, None, text="upstream exploded", json_error=ValueError())
        )

        with self.assertRaises(RuntimeError) as caught:
            client.start(WINDOW_ID, headless=True)

        message = str(caught.exception)
        self.assertIn("500", message)
        self.assertIn("upstream exploded", message)

    def test_start_429_raises_rate_limited_error_without_retry_or_sleep(self):
        client, http = self._client(
            FakeResponse(429, {"success": False, "msg": "too many requests"})
        )

        with patch("time.sleep", side_effect=AssertionError("client must not sleep")):
            with self.assertRaises(RateLimitedError):
                client.start(WINDOW_ID, headless=True)

        self.assertEqual(len(http.calls), 1)

    def test_start_transport_failure_is_wrapped_without_key(self):
        client, _ = self._client(ConnectionError("connection refused"))

        with self.assertRaises(RuntimeError) as caught:
            client.start(WINDOW_ID, headless=True)

        message = str(caught.exception)
        self.assertIn("connection refused", message)
        self.assertNotIn(KEY, message)


class BitBrowserClientStopTests(unittest.TestCase):
    def _client(self, *outcomes: object) -> tuple[BitBrowserClient, FakeHttp]:
        http = FakeHttp(post_outcomes=list(outcomes))
        return BitBrowserClient(KEY, BASE, http_get=http.get, http_post=http.post), http

    def test_stop_posts_the_same_window_id(self):
        client, http = self._client(
            FakeResponse(200, {"success": True, "data": {}})
        )

        client.stop(WINDOW_ID)

        self.assertEqual(len(http.calls), 1)
        call = http.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], f"{BASE}/browser/close")
        self.assertEqual(call["headers"], {"x-api-key": KEY})
        self.assertEqual(call["timeout"], 30)
        self.assertEqual(call["json"], {"id": WINDOW_ID})

    def test_stop_success_may_omit_data(self):
        client, _ = self._client(
            FakeResponse(200, {"success": True, "msg": "success"})
        )

        client.stop(WINDOW_ID)

    def test_stop_business_error_reports_msg(self):
        client, _ = self._client(
            FakeResponse(200, {"success": False, "msg": "窗口未运行"})
        )

        with self.assertRaises(RuntimeError) as caught:
            client.stop(WINDOW_ID)

        message = str(caught.exception)
        self.assertIn("HTTP 200", message)
        self.assertIn("窗口未运行", message)
        self.assertNotIn(KEY, message)

    def test_stop_non_2xx_reports_status(self):
        client, _ = self._client(
            FakeResponse(500, {"success": False, "msg": "internal error"})
        )

        with self.assertRaises(RuntimeError) as caught:
            client.stop(WINDOW_ID)

        self.assertIn("500", str(caught.exception))
        self.assertIn("internal error", str(caught.exception))

    def test_stop_429_raises_rate_limited_error(self):
        client, http = self._client(
            FakeResponse(429, {"success": False, "msg": "too many requests"})
        )

        with patch("time.sleep", side_effect=AssertionError("client must not sleep")):
            with self.assertRaises(RateLimitedError):
                client.stop(WINDOW_ID)

        self.assertEqual(len(http.calls), 1)

    def test_stop_malformed_envelope_is_a_runtime_error_not_incomplete(self):
        for payload in (
            {},
            {"success": "false"},
        ):
            with self.subTest(payload=payload):
                client, _ = self._client(FakeResponse(200, payload))
                with self.assertRaises(RuntimeError) as caught:
                    client.stop(WINDOW_ID)
                self.assertNotIsInstance(caught.exception, StartIncompleteError)

    def test_stop_transport_failure_is_wrapped_without_key(self):
        client, _ = self._client(ConnectionError("connection reset"))

        with self.assertRaises(RuntimeError) as caught:
            client.stop(WINDOW_ID)

        message = str(caught.exception)
        self.assertIn("connection reset", message)
        self.assertNotIn(KEY, message)


class BitBrowserClientObserveTests(unittest.TestCase):
    PORT = "9333"
    CDP_URL = f"http://127.0.0.1:{PORT}/json/version"

    def _client(
        self,
        *,
        post_outcomes: list[object] | None = None,
        get_outcomes: list[object] | None = None,
    ) -> tuple[BitBrowserClient, FakeHttp]:
        http = FakeHttp(
            post_outcomes=list(post_outcomes or []),
            get_outcomes=list(get_outcomes or []),
        )
        return BitBrowserClient(KEY, BASE, http_get=http.get, http_post=http.post), http

    def test_observe_queries_alive_process_port_and_cdp_in_order(self):
        client, http = self._client(
            post_outcomes=[
                FakeResponse(200, {"success": True, "data": [WINDOW_ID]}),
                FakeResponse(200, {"success": True, "data": {WINDOW_ID: self.PORT}}),
            ],
            get_outcomes=[FakeResponse(200, CDP_VERSION)],
        )

        state = client.observe(WINDOW_ID)

        self.assertTrue(state.active)
        self.assertEqual(state.endpoint, CDP_WS_URL)
        self.assertIsNone(state.headless)
        self.assertIsNone(state.launched_at_ns)

        first, second, third = http.calls
        self.assertEqual(first["method"], "POST")
        self.assertEqual(first["url"], f"{BASE}/browser/pids/alive")
        self.assertEqual(first["headers"], {"x-api-key": KEY})
        self.assertEqual(first["timeout"], 30)
        self.assertEqual(first["json"], {"ids": [WINDOW_ID]})

        self.assertEqual(second["method"], "POST")
        self.assertEqual(second["url"], f"{BASE}/browser/ports")
        self.assertEqual(second["headers"], {"x-api-key": KEY})
        self.assertEqual(second["timeout"], 30)
        self.assertEqual(second["json"], {})

        self.assertEqual(third["method"], "GET")
        self.assertEqual(third["url"], self.CDP_URL)
        self.assertEqual(third["timeout"], 3)
        self.assertNotIn("headers", third)

    def test_observe_reports_inactive_when_the_process_is_not_alive(self):
        client, http = self._client(
            post_outcomes=[FakeResponse(200, {"success": True, "data": []})]
        )

        state = client.observe(WINDOW_ID)

        self.assertFalse(state.active)
        self.assertIsNone(state.endpoint)
        self.assertEqual(len(http.calls), 1)

    def test_status_understands_window_to_pid_maps(self):
        for pid in (123, "123"):
            with self.subTest(pid=pid):
                client, _ = self._client(post_outcomes=[
                    FakeResponse(200, {"success": True, "data": {WINDOW_ID: pid}})
                ])
                self.assertEqual(client.status(WINDOW_ID), "running")

    def test_observe_malformed_pids_payload_is_not_reported_as_inactive(self):
        client, _ = self._client(
            post_outcomes=[FakeResponse(200, {"success": True, "data": None})]
        )

        with self.assertRaises(RuntimeError) as caught:
            client.observe(WINDOW_ID)

        self.assertIn("data", str(caught.exception))

    def test_observe_pids_business_failure_is_a_runtime_error(self):
        client, _ = self._client(
            post_outcomes=[
                FakeResponse(200, {"success": False, "msg": "window id invalid"})
            ]
        )

        with self.assertRaises(RuntimeError) as caught:
            client.observe(WINDOW_ID)

        self.assertIn("window id invalid", str(caught.exception))

    def test_ports_404_reports_operation_status_and_capability_hint(self):
        client, _ = self._client(
            post_outcomes=[
                FakeResponse(200, {"success": True, "data": [WINDOW_ID]}),
                FakeResponse(404, {"success": False, "msg": "not found"}),
            ]
        )

        with self.assertRaises(ProviderDiagnosticError) as caught:
            client.observe(WINDOW_ID)

        message = str(caught.exception)
        self.assertIn("查询比特浏览器窗口调试端口", message)
        self.assertIn("HTTP 404", message)
        self.assertIn("BITBROWSER_API_BASE", message)
        self.assertIn("支持", message)
        self.assertNotIn(KEY, message)
        self.assertNotIn(WS_URL, message)

    def test_ports_timeout_names_the_step_and_timeout(self):
        client, _ = self._client(
            post_outcomes=[
                FakeResponse(200, {"success": True, "data": [WINDOW_ID]}),
                TimeoutError("read timed out"),
            ]
        )

        with self.assertRaises(ProviderDiagnosticError) as caught:
            client.observe(WINDOW_ID)

        message = str(caught.exception)
        self.assertIn("查询比特浏览器窗口调试端口", message)
        self.assertIn("超时", message)
        self.assertIn("30", message)
        self.assertNotIn(KEY, message)

    def test_ports_missing_window_keeps_the_window_and_reports_why(self):
        client, _ = self._client(
            post_outcomes=[
                FakeResponse(200, {"success": True, "data": [WINDOW_ID]}),
                FakeResponse(200, {"success": True, "data": {}}),
            ]
        )

        with self.assertRaises(ProviderDiagnosticError) as caught:
            client.observe(WINDOW_ID)

        message = str(caught.exception)
        self.assertIn("调试端口", message)
        self.assertIn("进程", message)

    def test_observe_rejects_a_non_numeric_port_without_contacting_cdp(self):
        client, http = self._client(
            post_outcomes=[
                FakeResponse(200, {"success": True, "data": [WINDOW_ID]}),
                FakeResponse(200, {"success": True, "data": {WINDOW_ID: "abc"}}),
            ]
        )

        with self.assertRaises(ProviderDiagnosticError):
            client.observe(WINDOW_ID)

        self.assertEqual(len(http.calls), 2)

    def test_cdp_non_2xx_reports_the_debug_port_operation(self):
        client, _ = self._client(
            post_outcomes=[
                FakeResponse(200, {"success": True, "data": [WINDOW_ID]}),
                FakeResponse(200, {"success": True, "data": {WINDOW_ID: self.PORT}}),
            ],
            get_outcomes=[FakeResponse(404, None, text="not found")],
        )

        with self.assertRaises(ProviderDiagnosticError) as caught:
            client.observe(WINDOW_ID)

        message = str(caught.exception)
        self.assertIn("CDP", message)
        self.assertIn("404", message)
        self.assertIn(self.PORT, message)
        self.assertNotIn(KEY, message)

    def test_cdp_timeout_names_the_cdp_step(self):
        client, _ = self._client(
            post_outcomes=[
                FakeResponse(200, {"success": True, "data": [WINDOW_ID]}),
                FakeResponse(200, {"success": True, "data": {WINDOW_ID: self.PORT}}),
            ],
            get_outcomes=[TimeoutError("read timed out")],
        )

        with self.assertRaises(ProviderDiagnosticError) as caught:
            client.observe(WINDOW_ID)

        message = str(caught.exception)
        self.assertIn("CDP", message)
        self.assertIn("超时", message)

    def test_cdp_missing_or_mismatched_websocket_is_rejected(self):
        cases = (
            {"Browser": "Chrome/126"},
            {"webSocketDebuggerUrl": "http://127.0.0.1:9333/devtools/browser/abc"},
            {
                "webSocketDebuggerUrl": (
                    "ws://127.0.0.1:9444/devtools/browser/abc-123"
                )
            },
            {"webSocketDebuggerUrl": "ws://127.0.0.1:9333/other/path"},
        )
        for payload in cases:
            with self.subTest(payload=payload):
                client, _ = self._client(
                    post_outcomes=[
                        FakeResponse(
                            200, {"success": True, "data": [WINDOW_ID]}
                        ),
                        FakeResponse(
                            200,
                            {"success": True, "data": {WINDOW_ID: self.PORT}},
                        ),
                    ],
                    get_outcomes=[FakeResponse(200, payload)],
                )
                with self.assertRaises(ProviderDiagnosticError) as caught:
                    client.observe(WINDOW_ID)
                self.assertIn("WebSocket", str(caught.exception))

    def test_observe_429_is_rate_limited(self):
        client, http = self._client(
            post_outcomes=[
                FakeResponse(429, {"success": False, "msg": "too many requests"})
            ]
        )

        with patch("time.sleep", side_effect=AssertionError("client must not sleep")):
            with self.assertRaises(RateLimitedError):
                client.observe(WINDOW_ID)

        self.assertEqual(len(http.calls), 1)

    def test_status_reports_running_and_stopped_from_the_process_query(self):
        running, _ = self._client(
            post_outcomes=[FakeResponse(200, {"success": True, "data": [WINDOW_ID]})]
        )
        stopped, _ = self._client(
            post_outcomes=[FakeResponse(200, {"success": True, "data": []})]
        )

        self.assertEqual(running.status(WINDOW_ID), "running")
        self.assertEqual(stopped.status(WINDOW_ID), "stopped")


class BitBrowserProviderTests(unittest.TestCase):
    def _provider(self, http: FakeHttp) -> BitBrowserProvider:
        target = BitBrowserTarget(profile_id=WINDOW_ID)
        return BitBrowserProvider(
            target,
            BitBrowserClient(KEY, BASE, http_get=http.get, http_post=http.post),
        )

    def test_provider_delegates_probe_status_observe_and_stop(self):
        http = FakeHttp(
            post_outcomes=[
                FakeResponse(200, {"success": True}),
                FakeResponse(200, {"success": True, "data": [WINDOW_ID]}),
                FakeResponse(200, {"success": True, "data": []}),
                FakeResponse(200, {"success": True}),
            ]
        )
        provider = self._provider(http)

        provider.probe()
        self.assertEqual(provider.status(), "running")
        self.assertFalse(provider.observe().active)
        provider.stop()

        urls = [call["url"] for call in http.post_calls]
        self.assertEqual(
            urls,
            [
                f"{BASE}/health",
                f"{BASE}/browser/pids/alive",
                f"{BASE}/browser/pids/alive",
                f"{BASE}/browser/close",
            ],
        )
        self.assertEqual(http.post_calls[-1]["json"], {"id": WINDOW_ID})


class BitBrowserSanitisationTests(unittest.TestCase):
    def test_client_repr_redacts_key(self):
        client = BitBrowserClient(KEY, BASE, http_get=FakeHttp().get)

        self.assertNotIn(KEY, repr(client))
        self.assertNotIn(KEY, str(client))

    def test_provider_repr_redacts_key(self):
        target = BitBrowserTarget(profile_id=WINDOW_ID)
        client = BitBrowserClient(KEY, BASE, http_get=FakeHttp().get)
        provider = BitBrowserProvider(target, client)

        self.assertNotIn(KEY, repr(provider))
        self.assertNotIn(KEY, str(provider))

    def test_raw_exception_and_echoed_server_text_redact_key(self):
        scenarios = [
            (TimeoutError(f"timeout with {KEY}"), lambda c: c.probe(), "超时"),
            (RuntimeError(f"transport failed with {KEY}"),
             lambda c: c.start(WINDOW_ID, False), "transport failed"),
            (RuntimeError(f"transport failed with {KEY}"),
             lambda c: c.stop(WINDOW_ID), "transport failed"),
            (RuntimeError(f"transport failed with {KEY}"),
             lambda c: c.status(WINDOW_ID), "transport failed"),
            (FakeResponse(200, {"success": False, "msg": f"echo {KEY}"}),
             lambda c: c.status(WINDOW_ID), "echo"),
            (FakeResponse(403, {"success": False, "msg": f"denied {KEY}"}),
             lambda c: c.status(WINDOW_ID), "HTTP 403"),
            (FakeResponse(500, {"success": False, "msg": f"echo {KEY}"}),
             lambda c: c.status(WINDOW_ID), "echo"),
            (FakeResponse(500, None, text=f"echo {KEY}"),
             lambda c: c.status(WINDOW_ID), "echo"),
        ]
        for outcome, invoke, diagnostic in scenarios:
            with self.subTest(diagnostic=diagnostic, scenario=invoke):
                http = FakeHttp(post_outcomes=[outcome])
                client = BitBrowserClient(
                    KEY, BASE, http_get=http.get, http_post=http.post
                )
                with self.assertRaises(RuntimeError) as caught:
                    invoke(client)
                self.assertIn(diagnostic, str(caught.exception))
                self.assertNotIn(KEY, str(caught.exception))
                self.assertNotIn(KEY, "".join(traceback.format_exception(caught.exception)))


if __name__ == "__main__":
    unittest.main()
