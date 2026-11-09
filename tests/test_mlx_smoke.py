# -*- coding: utf-8 -*-
"""Opt-in smoke test for Multilogin X browser mode (ticket 27 / ticket 08).

This module is the only place that talks to a real Multilogin installation.  It
validates the lifecycle only — no upload, no platform page, no cookie file::

    probe(/api/v1/version)
      → start(folder, profile, headless=True)
      → connect_over_cdp("http://127.0.0.1:{port}", no_defaults=True)
      → assert exactly 1 browser context
      → browser.close()            (disconnect only; does not close the profile)
      → stop(profile)              (exactly once)
      → stop(profile) again        (already-stopped must count as success)

Environment variables
---------------------
``SAU_MLX_SMOKE=1``
    Required opt-in switch.  Without it this whole case is skipped, so the
    default ``python -m unittest discover -s tests`` stays offline and starts no
    browser.
``MLX_API_TOKEN``
    Multilogin X API token (Bearer).  Never printed; failure reports redact it
    and any ``Authorization`` header.
``SAU_MLX_FOLDER_ID``
    Folder (workspace) id that owns the profile.
``SAU_MLX_PROFILE_ID``
    Profile id to start.  It is the profile's identity; the smoke test does not
    log in or check platform accounts.

Prerequisites (spec §10)
------------------------
1. Multilogin desktop app running on the same machine as this test (macOS or
   Windows).  Docker launcher and cross-machine setups are not supported in v1.
2. The profile uses the **Mimic** kernel (Stealthfox does not support
   Playwright).
3. Launcher port 45001 is free/unblocked.
4. The profile may be stopped or already running; a running profile makes
   ``start`` fail with the launcher's lock error, which is reported as-is.
5. No account is required to *collect* this code: when no Multilogin account is
   available, leave ``SAU_MLX_SMOKE`` unset and the case skips.  Enabling the
   switch with missing variables is an actionable configuration error rather
   than a silent skip.

Safety / evidence rules
-----------------------
* Uploads nothing and reads/writes no cookie file (``account_file`` is never
  passed; the Multilogin branch of ``utils.browser_session`` is used).
* Failure output contains ``profile_id``, ``folder_id``, ``port`` and the
  launcher ``error_code``; it never contains the token or an ``Authorization``
  header.
* ``no_defaults=True`` is passed exactly as production does.  **Execution
  status: not executed** against a real account as of this commit, so
  ``no_defaults=True`` with the current patchright/Mimic combination remains
  unverified (spec §12/§16).  If a real run fails to attach with
  ``no_defaults=True``, record the fallback conclusion (drop ``no_defaults``)
  here and in the spec risk table, and change the production default only after
  that evidence — do not silently remove it.

Run::

    SAU_MLX_SMOKE=1 \
    MLX_API_TOKEN=... \
    SAU_MLX_FOLDER_ID=... \
    SAU_MLX_PROFILE_ID=... \
    python -m unittest tests.test_mlx_smoke -v
"""


from __future__ import annotations

import asyncio
import os
import re
import unittest
from dataclasses import dataclass
from typing import Mapping

SMOKE_FLAG = "SAU_MLX_SMOKE"
TOKEN_ENV = "MLX_API_TOKEN"
FOLDER_ENV = "SAU_MLX_FOLDER_ID"
PROFILE_ENV = "SAU_MLX_PROFILE_ID"
REQUIRED_ENV = (TOKEN_ENV, FOLDER_ENV, PROFILE_ENV)

TOKEN = "ticket27-secret-token"
FOLDER_ID = "11111111-1111-4111-8111-111111111111"
PROFILE_ID = "22222222-2222-4222-8222-222222222222"


class SmokeConfigError(RuntimeError):
    """Configuration is missing even though the smoke test was enabled."""


@dataclass(frozen=True)
class SmokeConfig:
    token: str
    folder_id: str
    profile_id: str


def smoke_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Opt-in only: exactly ``SAU_MLX_SMOKE=1`` turns the smoke test on."""
    env = os.environ if environ is None else environ
    return env.get(SMOKE_FLAG, "").strip() == "1"


def load_smoke_config(environ: Mapping[str, str] | None = None) -> SmokeConfig:
    """Read the required smoke-test variables without ever echoing values."""
    env = os.environ if environ is None else environ
    missing = [name for name in REQUIRED_ENV if not env.get(name, "").strip()]
    if missing:
        raise SmokeConfigError(
            f"{SMOKE_FLAG}=1 但缺少环境变量：{', '.join(missing)}；"
            "未执行任何请求。请设置后重试。"
        )

    return SmokeConfig(
        token=env[TOKEN_ENV].strip(),
        folder_id=env[FOLDER_ENV].strip(),
        profile_id=env[PROFILE_ENV].strip(),
    )


_AUTHORIZATION_RE = re.compile(
    r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?\S+"
)
_ERROR_CODE_RE = re.compile(r"error_code[\"'\s:=]+([A-Za-z0-9_.-]+)")


def _redact(text: str, token: str) -> str:
    """Remove the token and Authorization headers from diagnostic text."""
    cleaned = _AUTHORIZATION_RE.sub(r"\1<redacted>", text)
    if token:
        cleaned = cleaned.replace(token, "<redacted>")
    return cleaned


def _launcher_error_code(error: BaseException) -> str:
    match = _ERROR_CODE_RE.search(str(error))
    return match.group(1) if match else "unknown"


def describe_failure(
    *,
    profile_id: str,
    folder_id: str,
    port: str | None,
    error: BaseException,
    token: str,
) -> str:
    """Build a redacted, diagnosable failure report for the smoke test."""
    lines = [
        "Multilogin X smoke test failed.",
        f"profile_id={profile_id}",
        f"folder_id={folder_id}",
        f"port={port if port else 'unknown'}",
        f"launcher_error_code={_launcher_error_code(error)}",
        f"error={_redact(str(error), token)}",
    ]
    return "\n".join(lines)


class SmokeGuardTests(unittest.TestCase):
    """Offline tests for the enable switch and configuration guards."""

    def test_smoke_is_disabled_when_flag_is_absent(self):
        self.assertFalse(smoke_enabled({}))

    def test_smoke_is_enabled_only_by_exact_one(self):
        self.assertTrue(smoke_enabled({"SAU_MLX_SMOKE": "1"}))
        self.assertFalse(smoke_enabled({"SAU_MLX_SMOKE": "0"}))
        self.assertFalse(smoke_enabled({"SAU_MLX_SMOKE": "true"}))

    def test_missing_environment_names_every_required_variable(self):
        with self.assertRaises(SmokeConfigError) as raised:
            load_smoke_config({"SAU_MLX_SMOKE": "1"})

        message = str(raised.exception)
        self.assertIn("MLX_API_TOKEN", message)
        self.assertIn("SAU_MLX_FOLDER_ID", message)
        self.assertIn("SAU_MLX_PROFILE_ID", message)
        self.assertIn("未执行任何请求", message)
        self.assertNotIn(TOKEN, message)

    def test_partial_environment_reports_only_the_missing_names(self):
        env = {
            "SAU_MLX_SMOKE": "1",
            "MLX_API_TOKEN": TOKEN,
            "SAU_MLX_FOLDER_ID": FOLDER_ID,
        }
        with self.assertRaises(SmokeConfigError) as raised:
            load_smoke_config(env)

        message = str(raised.exception)
        self.assertIn("SAU_MLX_PROFILE_ID", message)
        self.assertNotIn("SAU_MLX_FOLDER_ID", message)
        self.assertNotIn(TOKEN, message)

    def test_complete_environment_loads_values(self):
        env = {
            "SAU_MLX_SMOKE": "1",
            "MLX_API_TOKEN": TOKEN,
            "SAU_MLX_FOLDER_ID": FOLDER_ID,
            "SAU_MLX_PROFILE_ID": PROFILE_ID,
        }
        config = load_smoke_config(env)

        self.assertEqual(config.token, TOKEN)
        self.assertEqual(config.folder_id, FOLDER_ID)
        self.assertEqual(config.profile_id, PROFILE_ID)

    def test_failure_report_has_diagnostics_but_never_the_token(self):
        error = RuntimeError(
            "启动 Multilogin Profile 失败：HTTP 500；"
            "error_code=PROFILE_ALREADY_RUNNING；message=lock failed"
        )
        report = describe_failure(
            profile_id=PROFILE_ID,
            folder_id=FOLDER_ID,
            port="55513",
            error=error,
            token=TOKEN,
        )

        self.assertIn(PROFILE_ID, report)
        self.assertIn(FOLDER_ID, report)
        self.assertIn("55513", report)
        self.assertIn("PROFILE_ALREADY_RUNNING", report)
        self.assertNotIn(TOKEN, report)

    def test_failure_report_redacts_authorization_header_and_bare_token(self):
        error = RuntimeError(
            f"boom Authorization: Bearer {TOKEN} and token={TOKEN}"
        )
        report = describe_failure(
            profile_id=PROFILE_ID,
            folder_id=FOLDER_ID,
            port=None,
            error=error,
            token=TOKEN,
        )

        self.assertNotIn(TOKEN, report)
        self.assertNotIn("Bearer " + TOKEN, report)
        self.assertIn("<redacted>", report)

    def test_failure_report_marks_unknown_port_and_error_code(self):
        report = describe_failure(
            profile_id=PROFILE_ID,
            folder_id=FOLDER_ID,
            port=None,
            error=RuntimeError("connect timed out"),
            token=TOKEN,
        )

        self.assertIn("port=unknown", report)
        self.assertIn("launcher_error_code=unknown", report)


class _RecordingClient:
    """Delegates to a real ``MultiloginClient`` while counting lifecycle calls."""

    def __init__(self, client, events: list[str]) -> None:
        self._client = client
        self.events = events
        self.port: str | None = None
        self.probe_calls = 0
        self.start_calls: list[tuple[str, str, bool]] = []
        self.status_calls: list[str] = []
        self.stop_calls: list[str] = []
        self.stop_errors: list[BaseException] = []

    def probe(self) -> None:
        self.probe_calls += 1
        self.events.append("probe")
        self._client.probe()

    def start(self, folder_id: str, profile_id: str, headless: bool) -> str:
        self.start_calls.append((folder_id, profile_id, headless))
        self.events.append("start")
        self.port = self._client.start(folder_id, profile_id, headless)
        return self.port

    def status(self, profile_id: str) -> str:
        self.status_calls.append(profile_id)
        self.events.append("status")
        return self._client.status(profile_id)

    def stop(self, profile_id: str) -> None:
        self.stop_calls.append(profile_id)
        self.events.append("stop")
        try:
            self._client.stop(profile_id)
        except BaseException as exc:
            self.stop_errors.append(exc)
            raise


class _RecordingBrowser:
    """Pass-through browser that records the disconnect call."""

    def __init__(self, browser, events: list[str]) -> None:
        self._browser = browser
        self._events = events

    @property
    def contexts(self):
        return self._browser.contexts

    def __getattr__(self, name):
        return getattr(self._browser, name)

    async def close(self) -> None:
        self._events.append("browser.close")
        await self._browser.close()


class _RecordingChromium:
    def __init__(self, chromium, events: list[str]) -> None:
        self._chromium = chromium
        self.events = events
        self.connect_calls: list[dict] = []

    async def connect_over_cdp(self, url: str, **kwargs):
        self.connect_calls.append({"url": url, **kwargs})
        self.events.append("connect")
        browser = await self._chromium.connect_over_cdp(url, **kwargs)
        return _RecordingBrowser(browser, self.events)


class _RecordingPlaywright:
    def __init__(self, playwright, events: list[str]) -> None:
        self.chromium = _RecordingChromium(playwright.chromium, events)


@unittest.skipUnless(
    smoke_enabled(),
    "MLX smoke test is opt-in: set SAU_MLX_SMOKE=1 (see module header).",
)
class MultiloginSmokeTests(unittest.TestCase):
    """Real-stack lifecycle check.  Never uploads and never touches cookies."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_smoke_config()

    def test_lifecycle_probe_start_connect_close_stop(self) -> None:
        asyncio.run(self._run())

    async def _run(self) -> None:
        from patchright.async_api import async_playwright

        import utils.browser_session as browser_session_module
        from utils.multilogin import (
            MultiloginClient,
            MultiloginProvider,
            MultiloginTarget,
        )

        config = self.config
        target = MultiloginTarget(
            folder_id=config.folder_id,
            profile_id=config.profile_id,
        )
        events: list[str] = []
        holder: dict[str, _RecordingClient] = {}
        real_client_class = MultiloginClient

        def client_factory(token: str) -> _RecordingClient:
            spy = _RecordingClient(real_client_class(token), events)
            holder["client"] = spy
            return spy

        browser_session_module.MultiloginClient = client_factory
        try:
            async with async_playwright() as playwright:
                recorder = _RecordingPlaywright(playwright, events)
                try:
                    async with browser_session_module.browser_session(
                        recorder,
                        headless=True,
                        managed=MultiloginProvider(
                            target, client_factory(config.token)
                        ),
                    ) as session:
                        self.assertEqual(session.mode, "multilogin")
                        self.assertEqual(len(session.browser.contexts), 1)
                        self.assertIs(
                            session.context,
                            session.browser.contexts[0],
                        )
                except Exception as exc:
                    spy = holder.get("client")
                    raise AssertionError(
                        describe_failure(
                            profile_id=config.profile_id,
                            folder_id=config.folder_id,
                            port=getattr(spy, "port", None),
                            error=exc,
                            token=config.token,
                        )
                    ) from None
        finally:
            browser_session_module.MultiloginClient = real_client_class

        spy = holder["client"]

        # probe → start(headless) → one successful CDP attach.
        self.assertEqual(spy.probe_calls, 1)
        self.assertEqual(
            spy.start_calls,
            [(config.folder_id, config.profile_id, True)],
        )
        self.assertGreaterEqual(len(recorder.chromium.connect_calls), 1)
        connect_call = recorder.chromium.connect_calls[-1]
        self.assertEqual(
            connect_call["url"],
            f"http://127.0.0.1:{spy.port}",
        )
        self.assertIs(connect_call.get("no_defaults"), True)

        # Exactly one Stop on the success path, after probe/start/connect and
        # after the disconnect.  (A transient connect retry is allowed, so only
        # the prefix and the tail are pinned.)
        self.assertEqual(events[:2], ["probe", "start"])
        self.assertEqual(events[-2:], ["browser.close", "stop"])
        self.assertEqual(spy.stop_calls, [config.profile_id])
        self.assertEqual(spy.stop_errors, [])

        # Stopping an already-stopped profile must count as success.
        try:
            await asyncio.to_thread(spy.stop, config.profile_id)
        except Exception as exc:
            raise AssertionError(
                describe_failure(
                    profile_id=config.profile_id,
                    folder_id=config.folder_id,
                    port=spy.port,
                    error=exc,
                    token=config.token,
                )
                + "\n停止已停止的 Profile 必须视为成功。"
            ) from None
        self.assertEqual(spy.stop_calls, [config.profile_id, config.profile_id])


@unittest.skipIf(
    smoke_enabled(),
    "skip assertion is only meaningful when the smoke test is disabled",
)
class DefaultDiscoveryTests(unittest.TestCase):
    def test_smoke_case_is_skipped_by_default(self) -> None:
        self.assertTrue(
            getattr(MultiloginSmokeTests, "__unittest_skip__", False),
            "MultiloginSmokeTests must be skipped unless SAU_MLX_SMOKE=1",
        )

