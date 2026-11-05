# -*- coding: utf-8 -*-
"""Offline contract tests for ``utils.multilogin.MultiloginClient``.

No real network and no ``http.server``: every HTTP call goes through an injected
``http_get`` callable, exactly as specified by ticket 07.
"""

from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from utils.multilogin import (
    LAUNCHER_BASE_URL,
    MultiloginClient,
    MultiloginTarget,
)

FIXTURES = Path(__file__).parent / "fixtures" / "multilogin"
TOKEN = "ticket15-secret-token"
FOLDER_ID = "22222222-2222-4222-8222-222222222222"
PROFILE_ID = "33333333-3333-4333-8333-333333333333"


def load_fixture(name: str) -> dict:
    with (FIXTURES / name).open(encoding="utf-8") as file_obj:
        return json.load(file_obj)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict | None = None,
        *,
        text: str | None = None,
        json_error: BaseException | None = None,
    ) -> None:
        self.status_code = status_code
        self.payload = payload
        self._text = text
        self._json_error = json_error

    def json(self) -> dict:
        if self._json_error is not None:
            raise self._json_error
        return self.payload if self.payload is not None else {}

    @property
    def text(self) -> str:
        if self._text is not None:
            return self._text
        return json.dumps(self.payload or {}, ensure_ascii=False)


class FakeHttpGet:
    def __init__(self, outcomes: list[object] | None = None) -> None:
        self.outcomes = list(outcomes or [])
        self.calls: list[dict] = []

    def __call__(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if not self.outcomes:
            raise AssertionError("http_get called with no queued outcome")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class MultiloginClientProbeTests(unittest.TestCase):
    def test_probe_uses_fixed_unauthenticated_version_endpoint(self):
        http_get = FakeHttpGet([FakeResponse(200, {"data": {"version": "1.0"}})])
        client = MultiloginClient(TOKEN, http_get=http_get)

        client.probe()

        self.assertEqual(len(http_get.calls), 1)
        call = http_get.calls[0]
        self.assertEqual(call["url"], f"{LAUNCHER_BASE_URL}/api/v1/version")
        self.assertEqual(call["timeout"], 3)
        self.assertIs(call["verify"], True)
        self.assertNotIn("headers", call)

    def test_probe_connection_failure_raises_runtime_error_with_desktop_hint(self):
        http_get = FakeHttpGet([OSError("connection refused")])
        client = MultiloginClient(TOKEN, http_get=http_get)

        with self.assertRaises(RuntimeError) as caught:
            client.probe()

        message = str(caught.exception)
        self.assertIn("无法连接 Multilogin Launcher", message)
        self.assertIn(LAUNCHER_BASE_URL, message)
        self.assertIn("45001", message)
        self.assertNotIn(TOKEN, message)

    def test_probe_non_200_raises_runtime_error(self):
        http_get = FakeHttpGet([FakeResponse(503, {"status": {"message": "down"}})])
        client = MultiloginClient(TOKEN, http_get=http_get)

        with self.assertRaises(RuntimeError) as caught:
            client.probe()

        self.assertIn("503", str(caught.exception))


class MultiloginClientStartTests(unittest.TestCase):
    def _client(self, *outcomes: object) -> tuple[MultiloginClient, FakeHttpGet]:
        http_get = FakeHttpGet(list(outcomes))
        return MultiloginClient(TOKEN, http_get=http_get), http_get

    def test_start_builds_url_bearer_header_and_reads_data_port(self):
        client, http_get = self._client(FakeResponse(200, load_fixture("start_ok.json")))

        port = client.start(FOLDER_ID, PROFILE_ID, headless=True)

        self.assertEqual(port, "55513")
        self.assertEqual(len(http_get.calls), 1)
        call = http_get.calls[0]
        self.assertEqual(
            call["url"],
            f"{LAUNCHER_BASE_URL}/api/v2/profile/f/{FOLDER_ID}/p/{PROFILE_ID}"
            "/start?automation_type=playwright&headless_mode=true",
        )
        self.assertEqual(call["headers"], {"Authorization": f"Bearer {TOKEN}"})
        self.assertIs(call["verify"], True)
        self.assertGreater(call["timeout"], 0)

    def test_start_passes_headless_false(self):
        client, http_get = self._client(FakeResponse(200, load_fixture("start_ok.json")))

        client.start(FOLDER_ID, PROFILE_ID, headless=False)

        self.assertIn("headless_mode=false", http_get.calls[0]["url"])

    def test_start_locked_profile_preserves_mlx_error_and_does_not_leak_token(self):
        client, _ = self._client(FakeResponse(500, load_fixture("start_locked.json")))

        with self.assertRaises(RuntimeError) as caught:
            client.start(FOLDER_ID, PROFILE_ID, headless=True)

        message = str(caught.exception)
        self.assertIn("500", message)
        self.assertIn("INTERNAL_SERVER_ERROR", message)
        self.assertIn("can't lock profile", message)
        self.assertNotIn(TOKEN, message)

    def test_start_unauthorized_preserves_mlx_message(self):
        client, _ = self._client(FakeResponse(401, load_fixture("start_unauthorized.json")))

        with self.assertRaises(RuntimeError) as caught:
            client.start(FOLDER_ID, PROFILE_ID, headless=True)

        message = str(caught.exception)
        self.assertIn("401", message)
        self.assertIn("Authorization error", message)
        self.assertNotIn(TOKEN, message)

    def test_start_429_is_surfaced_without_retry_or_sleep(self):
        client, http_get = self._client(
            FakeResponse(429, {"status": {"error_code": "TOO_MANY_REQUESTS", "message": "rate limited"}})
        )

        with patch("time.sleep", side_effect=AssertionError("client must not sleep")):
            with self.assertRaises(RuntimeError) as caught:
                client.start(FOLDER_ID, PROFILE_ID, headless=True)

        self.assertIn("429", str(caught.exception))
        self.assertEqual(len(http_get.calls), 1)

    def test_start_missing_port_is_contract_error(self):
        client, _ = self._client(FakeResponse(200, {"data": {}, "status": {"http_code": 200}}))

        with self.assertRaises(RuntimeError) as caught:
            client.start(FOLDER_ID, PROFILE_ID, headless=True)

        self.assertIn("port", str(caught.exception).lower())

    def test_start_transport_failure_is_wrapped_without_token(self):
        client, _ = self._client(ConnectionError("connection refused"))

        with self.assertRaises(RuntimeError) as caught:
            client.start(FOLDER_ID, PROFILE_ID, headless=True)

        self.assertIn("connection refused", str(caught.exception))
        self.assertNotIn(TOKEN, str(caught.exception))


class MultiloginClientStopTests(unittest.TestCase):
    def _client(self, *outcomes: object) -> tuple[MultiloginClient, FakeHttpGet]:
        http_get = FakeHttpGet(list(outcomes))
        return MultiloginClient(TOKEN, http_get=http_get), http_get

    def test_stop_uses_profile_endpoint_with_bearer_header(self):
        client, http_get = self._client(FakeResponse(200, load_fixture("stop_ok.json")))

        client.stop(PROFILE_ID)

        self.assertEqual(len(http_get.calls), 1)
        call = http_get.calls[0]
        self.assertEqual(
            call["url"],
            f"{LAUNCHER_BASE_URL}/api/v1/profile/stop/p/{PROFILE_ID}",
        )
        self.assertEqual(call["headers"], {"Authorization": f"Bearer {TOKEN}"})
        self.assertIs(call["verify"], True)
        self.assertGreater(call["timeout"], 0)

    def test_stop_500_already_stopped_is_success(self):
        client, _ = self._client(
            FakeResponse(500, load_fixture("stop_already_stopped.json"))
        )

        client.stop(PROFILE_ID)

    def test_stop_500_already_stopped_in_body_text_is_success(self):
        client, _ = self._client(
            FakeResponse(
                500,
                None,
                text='{"status": {"message": "Profile already stopped"}}',
                json_error=ValueError("not json"),
            )
        )

        client.stop(PROFILE_ID)

    def test_stop_other_500_raises(self):
        client, _ = self._client(
            FakeResponse(500, {"status": {"error_code": "BOOM", "message": "failed"}})
        )

        with self.assertRaises(RuntimeError) as caught:
            client.stop(PROFILE_ID)

        self.assertIn("500", str(caught.exception))
        self.assertIn("failed", str(caught.exception))

    def test_stop_500_error_code_already_stopped_is_success(self):
        client, _ = self._client(
            FakeResponse(500, {"status": {"error_code": "PROFILE_ALREADY_STOPPED"}})
        )

        client.stop(PROFILE_ID)

    def test_stop_transport_failure_is_wrapped(self):
        client, _ = self._client(ConnectionError("connection refused"))

        with self.assertRaises(RuntimeError) as caught:
            client.stop(PROFILE_ID)

        self.assertIn("connection refused", str(caught.exception))

    def test_stop_401_raises(self):
        client, _ = self._client(
            FakeResponse(401, {"status": {"message": "Authorization error"}})
        )

        with self.assertRaises(RuntimeError):
            client.stop(PROFILE_ID)


class MultiloginClientStatusTests(unittest.TestCase):
    def test_status_returns_profile_status(self):
        http_get = FakeHttpGet([FakeResponse(200, load_fixture("status_running.json"))])
        client = MultiloginClient(TOKEN, http_get=http_get)

        status = client.status(PROFILE_ID)

        self.assertEqual(status, "browser_running")
        call = http_get.calls[0]
        self.assertEqual(
            call["url"],
            f"{LAUNCHER_BASE_URL}/api/v1/profile/status/p/{PROFILE_ID}",
        )
        self.assertEqual(call["headers"], {"Authorization": f"Bearer {TOKEN}"})

    def test_status_stopped(self):
        http_get = FakeHttpGet([FakeResponse(200, load_fixture("status_stopped.json"))])
        client = MultiloginClient(TOKEN, http_get=http_get)

        self.assertEqual(client.status(PROFILE_ID), "stopped")

    def test_status_failure_raises_runtime_error(self):
        http_get = FakeHttpGet([FakeResponse(500, {"status": {"message": "agent restarting"}})])
        client = MultiloginClient(TOKEN, http_get=http_get)

        with self.assertRaises(RuntimeError) as caught:
            client.status(PROFILE_ID)

        self.assertIn("agent restarting", str(caught.exception))

    def test_status_transport_failure_is_wrapped(self):
        http_get = FakeHttpGet([ConnectionError("connection refused")])
        client = MultiloginClient(TOKEN, http_get=http_get)

        with self.assertRaises(RuntimeError) as caught:
            client.status(PROFILE_ID)

        self.assertIn("connection refused", str(caught.exception))


class MultiloginSanitisationTests(unittest.TestCase):
    def test_client_repr_never_contains_token(self):
        client = MultiloginClient(TOKEN, http_get=FakeHttpGet([]))

        self.assertNotIn(TOKEN, repr(client))
        self.assertNotIn(TOKEN, str(client))

    def test_target_is_frozen_and_slotted(self):
        target = MultiloginTarget(folder_id=FOLDER_ID, profile_id=PROFILE_ID)

        self.assertEqual(target.folder_id, FOLDER_ID)
        self.assertEqual(target.profile_id, PROFILE_ID)
        self.assertFalse(hasattr(target, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            target.folder_id = "other"  # type: ignore[misc]
        self.assertNotIn(TOKEN, repr(target))


if __name__ == "__main__":
    unittest.main()
