# -*- coding: utf-8 -*-
"""Offline contract tests for ``utils.adspower``.

No real network and no ``http.server``: every HTTP call goes through injected
``http_get`` / ``http_post`` callables, exactly as specified by ticket 05.
"""

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import patch

from tests.fakes import FakeHttp, FakeResponse
from utils.adspower import AdspowerClient, AdspowerProvider, AdspowerTarget
from utils.errors import RateLimitedError, StartIncompleteError

KEY = "adspower-ticket12-secret-key"
BASE = "http://127.0.0.1:50325"
PROFILE_ID = "k1abc123"


class ErrorTypeTests(unittest.TestCase):
    def test_start_incomplete_error_is_a_runtime_error(self):
        self.assertTrue(issubclass(StartIncompleteError, RuntimeError))

    def test_rate_limited_error_is_a_runtime_error(self):
        # Existing MLX regression tests assert RuntimeError for HTTP 429; the
        # shared type is a narrow subtype so it can be mapped to exit 11.
        self.assertTrue(issubclass(RateLimitedError, RuntimeError))


class AdspowerClientProbeTests(unittest.TestCase):
    def _client(self, *outcomes: object) -> tuple[AdspowerClient, FakeHttp]:
        http = FakeHttp(get_outcomes=list(outcomes))
        return AdspowerClient(KEY, BASE, http_get=http.get, http_post=http.post), http

    def test_probe_uses_status_endpoint_with_bearer_and_three_second_timeout(self):
        client, http = self._client(FakeResponse(200, {"code": 0}))

        client.probe()

        self.assertEqual(len(http.calls), 1)
        call = http.calls[0]
        self.assertEqual(call["method"], "GET")
        self.assertEqual(call["url"], f"{BASE}/status")
        self.assertEqual(call["headers"], {"Authorization": f"Bearer {KEY}"})
        self.assertEqual(call["timeout"], 3)

    def test_probe_connection_failure_uses_fixed_unreachable_message(self):
        client, _ = self._client(OSError("connection refused"))

        with self.assertRaises(RuntimeError) as caught:
            client.probe()

        message = str(caught.exception)
        self.assertIn("无法连接 AdsPower Local API", message)
        self.assertIn(BASE, message)
        self.assertIn("AdsPower 桌面应用", message)
        self.assertIn("本地 API", message)
        self.assertIn("同一台机器", message)
        self.assertIn("端口", message)
        self.assertNotIn(KEY, message)

    def test_probe_401_mentions_api_key_and_local_api_permissions(self):
        client, _ = self._client(FakeResponse(401, {"code": 401, "msg": "unauthorized"}))

        with self.assertRaises(RuntimeError) as caught:
            client.probe()

        message = str(caught.exception)
        self.assertIn("401", message)
        self.assertIn("ADSPOWER_API_KEY", message)
        self.assertIn("Local API 权限", message)
        self.assertNotIn(KEY, message)

    def test_probe_403_mentions_api_key_and_local_api_permissions(self):
        client, _ = self._client(FakeResponse(403, {"code": 403, "msg": "forbidden"}))

        with self.assertRaises(RuntimeError) as caught:
            client.probe()

        message = str(caught.exception)
        self.assertIn("403", message)
        self.assertIn("ADSPOWER_API_KEY", message)
        self.assertIn("Local API 权限", message)

    def test_probe_404_mentions_outdated_client_or_local_api_off(self):
        client, _ = self._client(FakeResponse(404, {"msg": "not found"}))

        with self.assertRaises(RuntimeError) as caught:
            client.probe()

        message = str(caught.exception)
        self.assertIn("AdsPower 版本过旧或 Local API 未开启", message)

    def test_probe_non_2xx_raises_runtime_error_with_http_status(self):
        client, _ = self._client(FakeResponse(500, {"code": 500, "msg": "down"}))

        with self.assertRaises(RuntimeError) as caught:
            client.probe()

        message = str(caught.exception)
        self.assertIn("500", message)
        self.assertIn("down", message)

    def test_probe_429_raises_rate_limited_error_without_retry_or_sleep(self):
        client, http = self._client(FakeResponse(429, {"msg": "too many requests"}))

        with patch("time.sleep", side_effect=AssertionError("client must not sleep")):
            with self.assertRaises(RateLimitedError) as caught:
                client.probe()

        self.assertIn("429", str(caught.exception))
        self.assertIn("请求过于频繁", str(caught.exception))
        self.assertEqual(len(http.calls), 1)


WS_URL = "ws://127.0.0.1:9222/devtools/browser/abc-123"


class AdspowerClientStartTests(unittest.TestCase):
    def _client(self, *outcomes: object) -> tuple[AdspowerClient, FakeHttp]:
        http = FakeHttp(post_outcomes=list(outcomes))
        return AdspowerClient(KEY, BASE, http_get=http.get, http_post=http.post), http

    def test_start_posts_v2_endpoint_with_exact_body_and_headers(self):
        client, http = self._client(
            FakeResponse(200, {"code": 0, "data": {"ws": {"puppeteer": WS_URL}}})
        )

        url = client.start(PROFILE_ID, headless=True)

        self.assertEqual(url, WS_URL)
        self.assertEqual(len(http.calls), 1)
        call = http.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], f"{BASE}/api/v2/browser-profile/start")
        self.assertEqual(call["headers"], {"Authorization": f"Bearer {KEY}"})
        self.assertEqual(call["timeout"], 30)
        self.assertEqual(
            call["json"],
            {
                "profile_id": PROFILE_ID,
                "headless": "1",
                "last_opened_tabs": "0",
                "proxy_detection": "0",
                "delete_cache": "0",
                "cdp_mask": "1",
            },
        )

    def test_start_headless_false_encodes_zero(self):
        client, http = self._client(
            FakeResponse(200, {"code": 0, "data": {"ws": {"puppeteer": WS_URL}}})
        )

        client.start(PROFILE_ID, headless=False)

        self.assertEqual(http.calls[0]["json"]["headless"], "0")

    def test_start_returns_ws_verbatim(self):
        verbatim = "  ws://127.0.0.1:9222/devtools/browser/abc-123  "
        client, _ = self._client(
            FakeResponse(200, {"code": 0, "data": {"ws": {"puppeteer": verbatim}}})
        )

        self.assertEqual(client.start(PROFILE_ID, headless=True), verbatim)

    def test_start_fixed_fields_cannot_be_overridden_by_callers(self):
        client, _ = self._client()

        with self.assertRaises(TypeError):
            client.start(  # type: ignore[call-arg]
                PROFILE_ID, headless=True, delete_cache="1"
            )

    def test_start_missing_ws_raises_start_incomplete(self):
        client, _ = self._client(FakeResponse(200, {"code": 0, "data": {}}))

        with self.assertRaises(StartIncompleteError) as caught:
            client.start(PROFILE_ID, headless=True)

        self.assertIn("ws.puppeteer", str(caught.exception))
        self.assertNotIn(KEY, str(caught.exception))

    def test_start_empty_ws_raises_start_incomplete(self):
        client, _ = self._client(
            FakeResponse(200, {"code": 0, "data": {"ws": {"puppeteer": "   "}}})
        )

        with self.assertRaises(StartIncompleteError):
            client.start(PROFILE_ID, headless=True)

    def test_start_invalid_json_raises_start_incomplete(self):
        client, _ = self._client(
            FakeResponse(
                200,
                None,
                text="<html>not json</html>",
                json_error=ValueError("not json"),
            )
        )

        with self.assertRaises(StartIncompleteError) as caught:
            client.start(PROFILE_ID, headless=True)

        self.assertIn("响应", str(caught.exception))

    def test_start_missing_code_raises_start_incomplete(self):
        client, _ = self._client(
            FakeResponse(200, {"data": {"ws": {"puppeteer": WS_URL}}})
        )

        with self.assertRaises(StartIncompleteError) as caught:
            client.start(PROFILE_ID, headless=True)

        self.assertIn("code", str(caught.exception))

    def test_start_business_error_raises_runtime_error_and_is_not_incomplete(self):
        client, _ = self._client(
            FakeResponse(200, {"code": 10001, "msg": "profile not exist"})
        )

        with self.assertRaises(RuntimeError) as caught:
            client.start(PROFILE_ID, headless=True)

        self.assertNotIsInstance(caught.exception, StartIncompleteError)
        message = str(caught.exception)
        self.assertIn("HTTP 200", message)
        self.assertIn("code=10001", message)
        self.assertIn("profile not exist", message)
        self.assertNotIn(KEY, message)

    def test_start_401_mentions_api_key_and_local_api_permissions(self):
        client, _ = self._client(
            FakeResponse(401, {"code": 401, "msg": "unauthorized"})
        )

        with self.assertRaises(RuntimeError) as caught:
            client.start(PROFILE_ID, headless=True)

        message = str(caught.exception)
        self.assertIn("401", message)
        self.assertIn("ADSPOWER_API_KEY", message)
        self.assertIn("Local API 权限", message)

    def test_start_404_mentions_outdated_client(self):
        client, _ = self._client(FakeResponse(404, {"msg": "not found"}))

        with self.assertRaises(RuntimeError) as caught:
            client.start(PROFILE_ID, headless=True)

        self.assertIn("AdsPower 版本过旧或 Local API 未开启", str(caught.exception))

    def test_start_500_raises_runtime_error_with_status_and_body(self):
        client, _ = self._client(
            FakeResponse(500, None, text="upstream exploded", json_error=ValueError())
        )

        with self.assertRaises(RuntimeError) as caught:
            client.start(PROFILE_ID, headless=True)

        message = str(caught.exception)
        self.assertIn("500", message)
        self.assertIn("upstream exploded", message)

    def test_start_429_raises_rate_limited_error_without_retry_or_sleep(self):
        client, http = self._client(FakeResponse(429, {"msg": "too many requests"}))

        with patch("time.sleep", side_effect=AssertionError("client must not sleep")):
            with self.assertRaises(RateLimitedError) as caught:
                client.start(PROFILE_ID, headless=True)

        self.assertIn("429", str(caught.exception))
        self.assertEqual(len(http.calls), 1)

    def test_start_transport_failure_is_wrapped_without_key(self):
        client, _ = self._client(ConnectionError("connection refused"))

        with self.assertRaises(RuntimeError) as caught:
            client.start(PROFILE_ID, headless=True)

        message = str(caught.exception)
        self.assertIn("connection refused", message)
        self.assertNotIn(KEY, message)


class AdspowerClientStopTests(unittest.TestCase):
    def _client(self, *outcomes: object) -> tuple[AdspowerClient, FakeHttp]:
        http = FakeHttp(post_outcomes=list(outcomes))
        return AdspowerClient(KEY, BASE, http_get=http.get, http_post=http.post), http

    def test_stop_posts_v2_endpoint_with_profile_body_and_headers(self):
        client, http = self._client(FakeResponse(200, {"code": 0}))

        client.stop(PROFILE_ID)

        self.assertEqual(len(http.calls), 1)
        call = http.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], f"{BASE}/api/v2/browser-profile/stop")
        self.assertEqual(call["headers"], {"Authorization": f"Bearer {KEY}"})
        self.assertEqual(call["timeout"], 30)
        self.assertEqual(call["json"], {"profile_id": PROFILE_ID})

    def test_stop_success_response_may_omit_data(self):
        client, _ = self._client(FakeResponse(200, {"code": 0, "msg": "success"}))

        client.stop(PROFILE_ID)

    def test_stop_business_error_raises_runtime_error(self):
        client, _ = self._client(
            FakeResponse(200, {"code": 10002, "msg": "profile not running"})
        )

        with self.assertRaises(RuntimeError) as caught:
            client.stop(PROFILE_ID)

        message = str(caught.exception)
        self.assertIn("code=10002", message)
        self.assertIn("profile not running", message)
        self.assertNotIn(KEY, message)

    def test_stop_non_2xx_raises_runtime_error(self):
        client, _ = self._client(
            FakeResponse(500, {"code": 500, "msg": "internal error"})
        )

        with self.assertRaises(RuntimeError) as caught:
            client.stop(PROFILE_ID)

        self.assertIn("500", str(caught.exception))
        self.assertIn("internal error", str(caught.exception))

    def test_stop_429_raises_rate_limited_error_without_retry_or_sleep(self):
        client, http = self._client(FakeResponse(429, {"msg": "too many requests"}))

        with patch("time.sleep", side_effect=AssertionError("client must not sleep")):
            with self.assertRaises(RateLimitedError):
                client.stop(PROFILE_ID)

        self.assertEqual(len(http.calls), 1)

    def test_stop_invalid_json_raises_runtime_error_not_start_incomplete(self):
        client, _ = self._client(
            FakeResponse(200, None, text="not json", json_error=ValueError())
        )

        with self.assertRaises(RuntimeError) as caught:
            client.stop(PROFILE_ID)

        self.assertNotIsInstance(caught.exception, StartIncompleteError)

    def test_stop_missing_code_raises_runtime_error(self):
        client, _ = self._client(FakeResponse(200, {"msg": "ok"}))

        with self.assertRaises(RuntimeError) as caught:
            client.stop(PROFILE_ID)

        self.assertIn("code", str(caught.exception))

    def test_stop_transport_failure_is_wrapped_without_key(self):
        client, _ = self._client(ConnectionError("connection reset"))

        with self.assertRaises(RuntimeError) as caught:
            client.stop(PROFILE_ID)

        message = str(caught.exception)
        self.assertIn("connection reset", message)
        self.assertNotIn(KEY, message)


class AdspowerClientStatusTests(unittest.TestCase):
    def _client(self, *outcomes: object) -> tuple[AdspowerClient, FakeHttp]:
        http = FakeHttp(get_outcomes=list(outcomes))
        return AdspowerClient(KEY, BASE, http_get=http.get, http_post=http.post), http

    def test_status_uses_active_endpoint_with_encoded_profile_and_headers(self):
        client, http = self._client(
            FakeResponse(200, {"code": 0, "data": {"status": "Active"}})
        )

        status = client.status("profile with/slash")

        self.assertEqual(status, "Active")
        call = http.calls[0]
        self.assertEqual(call["method"], "GET")
        self.assertEqual(
            call["url"],
            f"{BASE}/api/v2/browser-profile/active?profile_id=profile%20with%2Fslash",
        )
        self.assertEqual(call["headers"], {"Authorization": f"Bearer {KEY}"})
        self.assertEqual(call["timeout"], 30)

    def test_status_returns_inactive(self):
        client, _ = self._client(
            FakeResponse(200, {"code": 0, "data": {"status": "Inactive"}})
        )

        self.assertEqual(client.status(PROFILE_ID), "Inactive")

    def test_status_missing_data_returns_unknown(self):
        client, _ = self._client(FakeResponse(200, {"code": 0}))

        self.assertEqual(client.status(PROFILE_ID), "unknown")

    def test_status_non_dict_data_returns_unknown(self):
        client, _ = self._client(FakeResponse(200, {"code": 0, "data": []}))

        self.assertEqual(client.status(PROFILE_ID), "unknown")

    def test_status_missing_field_returns_unknown(self):
        client, _ = self._client(FakeResponse(200, {"code": 0, "data": {}}))

        self.assertEqual(client.status(PROFILE_ID), "unknown")

    def test_status_invalid_json_returns_unknown(self):
        client, _ = self._client(
            FakeResponse(200, None, text="not json", json_error=ValueError())
        )

        self.assertEqual(client.status(PROFILE_ID), "unknown")

    def test_status_non_2xx_raises_runtime_error(self):
        client, _ = self._client(
            FakeResponse(500, {"code": 500, "msg": "agent restarting"})
        )

        with self.assertRaises(RuntimeError) as caught:
            client.status(PROFILE_ID)

        message = str(caught.exception)
        self.assertIn("500", message)
        self.assertIn("agent restarting", message)

    def test_status_429_raises_rate_limited_error(self):
        client, _ = self._client(FakeResponse(429, {"msg": "too many requests"}))

        with self.assertRaises(RateLimitedError):
            client.status(PROFILE_ID)

    def test_status_transport_failure_is_wrapped_without_key(self):
        client, _ = self._client(TimeoutError("timed out"))

        with self.assertRaises(RuntimeError) as caught:
            client.status(PROFILE_ID)

        message = str(caught.exception)
        self.assertIn("timed out", message)
        self.assertNotIn(KEY, message)


class AdspowerProviderTests(unittest.TestCase):
    def _provider(self, http: FakeHttp) -> AdspowerProvider:
        target = AdspowerTarget(profile_id=PROFILE_ID)
        return AdspowerProvider(
            target,
            AdspowerClient(KEY, BASE, http_get=http.get, http_post=http.post),
        )

    def test_provider_start_returns_ws_verbatim_without_http_conversion(self):
        http = FakeHttp(
            post_outcomes=[
                FakeResponse(200, {"code": 0, "data": {"ws": {"puppeteer": WS_URL}}})
            ]
        )
        provider = self._provider(http)

        url = provider.start(headless=True)

        self.assertEqual(url, WS_URL)
        self.assertEqual(provider.mode, "adspower")
        self.assertEqual(provider.profile_id, PROFILE_ID)
        self.assertEqual(http.post_calls[0]["json"]["profile_id"], PROFILE_ID)

    def test_provider_delegates_probe_status_and_stop_with_its_profile(self):
        http = FakeHttp(
            get_outcomes=[
                FakeResponse(200, {"code": 0}),
                FakeResponse(200, {"code": 0, "data": {"status": "Active"}}),
            ],
            post_outcomes=[FakeResponse(200, {"code": 0})],
        )
        provider = self._provider(http)

        provider.probe()
        self.assertEqual(provider.status(), "Active")
        provider.stop()

        self.assertEqual(http.get_calls[0]["url"], f"{BASE}/status")
        self.assertIn(f"profile_id={PROFILE_ID}", http.get_calls[1]["url"])
        self.assertEqual(
            http.post_calls[0]["url"], f"{BASE}/api/v2/browser-profile/stop"
        )
        self.assertEqual(
            http.post_calls[0]["json"], {"profile_id": PROFILE_ID}
        )


class AdspowerSanitisationTests(unittest.TestCase):
    def test_client_repr_redacts_key(self):
        client = AdspowerClient(KEY, BASE, http_get=FakeHttp().get)

        self.assertEqual(repr(client), "AdspowerClient(token=<redacted>)")
        self.assertNotIn(KEY, repr(client))
        self.assertNotIn(KEY, str(client))

    def test_provider_repr_redacts_key(self):
        target = AdspowerTarget(profile_id=PROFILE_ID)
        client = AdspowerClient(KEY, BASE, http_get=FakeHttp().get)
        provider = AdspowerProvider(target, client)

        self.assertNotIn(KEY, repr(provider))
        self.assertNotIn(KEY, str(provider))

    def test_target_is_frozen_and_slotted(self):
        target = AdspowerTarget(profile_id=PROFILE_ID)

        self.assertEqual(target.profile_id, PROFILE_ID)
        self.assertFalse(hasattr(target, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            target.profile_id = "other"  # type: ignore[misc]

    def test_no_primitive_leaks_key_in_transport_or_http_errors(self):
        scenarios = [
            # (get_outcomes, post_outcomes, callable)
            ([OSError("refused")], [], lambda c: c.probe()),
            ([], [OSError("refused")], lambda c: c.start(PROFILE_ID, True)),
            ([], [FakeResponse(500, {"msg": "boom"})], lambda c: c.stop(PROFILE_ID)),
            ([FakeResponse(403, {"msg": "denied"})], [], lambda c: c.status(PROFILE_ID)),
        ]
        for get_outcomes, post_outcomes, invoke in scenarios:
            with self.subTest(scenario=invoke):
                http = FakeHttp(get_outcomes, post_outcomes)
                client = AdspowerClient(
                    KEY, BASE, http_get=http.get, http_post=http.post
                )
                with self.assertRaises(RuntimeError) as caught:
                    invoke(client)
                self.assertNotIn(KEY, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
