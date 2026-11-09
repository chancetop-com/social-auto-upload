# -*- coding: utf-8 -*-
"""Opt-in smoke test for AdsPower browser mode (ticket 16 / ticket 09).

This module is the only place that talks to a real AdsPower installation.  It
validates the browser lifecycle only — no upload, no platform page, no cookie
file, no ``delete_cache`` and no profile mutation::

    probe(/status)
      → start(headless=True)                → data.ws.puppeteer
      → connect_over_cdp(ws)                (the URL is passed verbatim)
      → read current URL/title from contexts[0].pages[0]
      → browser.close()                     (disconnect only)
      → stop()                              (always, after a successful start)

Environment variables
---------------------
``SAU_ADSPOWER_SMOKE=1``
    Required opt-in switch.  Without it this whole case is skipped, so the
    default ``python -m unittest discover -s tests`` stays offline and starts no
    browser.
``ADSPOWER_API_KEY``
    AdsPower Local API key (Bearer).  Never printed; failure reports redact it
    and any ``Authorization`` header.
``ADSPOWER_TEST_PROFILE_ID``
    Profile id to start.  Treated as sensitive (a real account/profile name):
    failure reports never print it.
``ADSPOWER_API_BASE``
    Optional Local API base.  Validated and normalised by the CLI helper
    (``_resolve_adspower_base``); defaults to ``http://127.0.0.1:50325``.

Prerequisites (spec §10)
------------------------
1. AdsPower desktop app running on the same machine as this test (macOS or
   Windows).  Docker and cross-machine setups are not supported by v1.
2. The profile uses the Chromium kernel; Firefox profiles do not support CDP.
3. Local API is enabled and port 50325 (or ``ADSPOWER_API_BASE``) is
   reachable.
4. The profile may be stopped or already running; the API's answer is reported
   as-is, never hidden.
5. No account is required to *collect* this code: leave ``SAU_ADSPOWER_SMOKE``
   unset and the case skips with no network or browser access.  All three
   variables must be non-empty for the case to run.

Safety / evidence rules
-----------------------
* Uploads nothing and reads/writes no cookie file.
* Failure output contains only ``stage``, ``host:port`` and the redacted error
  text (which may include HTTP status/``code``/``msg``).  It never contains the
  API key, an ``Authorization`` header, the profile id, or the full ws path.
* **Execution status: not executed** against a real AdsPower installation as
  of this commit.  Ticket 09 remains ``open``; this module only provides the
  harness and must not be treated as a real smoke result.

Run::

    SAU_ADSPOWER_SMOKE=1 \
    ADSPOWER_API_KEY=... \
    ADSPOWER_TEST_PROFILE_ID=... \
    python -m unittest tests.test_adspower_smoke -v
"""

from __future__ import annotations

import asyncio
import os
import re
import unittest
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit

SMOKE_FLAG = "SAU_ADSPOWER_SMOKE"
KEY_ENV = "ADSPOWER_API_KEY"
PROFILE_ENV = "ADSPOWER_TEST_PROFILE_ID"
REQUIRED_ENV = (KEY_ENV, PROFILE_ENV)

KEY = "adspower-ticket16-secret-key"
PROFILE_ID = "ticket16-test-profile-0001"


class SmokeConfigError(RuntimeError):
    """Configuration is missing even though the smoke test was enabled."""


@dataclass(frozen=True)
class SmokeConfig:
    key: str
    profile_id: str


def smoke_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Opt-in only: exactly ``SAU_ADSPOWER_SMOKE=1`` turns the smoke test on."""
    env = os.environ if environ is None else environ
    return env.get(SMOKE_FLAG, "").strip() == "1"


def smoke_ready(environ: Mapping[str, str] | None = None) -> bool:
    """The smoke case runs only when the flag and both required values exist."""
    env = os.environ if environ is None else environ
    return (
        smoke_enabled(env)
        and bool(env.get(KEY_ENV, "").strip())
        and bool(env.get(PROFILE_ENV, "").strip())
    )


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
        key=env[KEY_ENV].strip(),
        profile_id=env[PROFILE_ENV].strip(),
    )


def _endpoint_of(url: str) -> str:
    """Return ``host:port`` (or ``unknown``) for a diagnostic line."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return "unknown"
    host = parts.hostname
    if not host:
        return "unknown"
    return f"{host}:{port}" if port is not None else host


_AUTHORIZATION_RE = re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?\S+")
_URL_RE = re.compile(r"(?i)\b(?:https?|wss?)://[^\s\"'<>]+")
_PROFILE_ID_RE = re.compile(r"(?i)(profile_id\s*[:=]\s*)\S+")


def _redact_url(match: re.Match[str]) -> str:
    """Keep only ``scheme://host:port``; drop userinfo, path, query, fragment."""
    raw = match.group(0)
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        return "<redacted-url>"

    scheme = parts.scheme or "http"
    host = parts.hostname
    if not host:
        return f"{scheme}://<redacted>"
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    authority = f"{host}:{port}" if port is not None else host
    has_suffix = (
        bool(parts.path and parts.path != "/")
        or bool(parts.query)
        or bool(parts.fragment)
    )
    suffix = "/<redacted>" if has_suffix else ""
    return f"{scheme}://{authority}{suffix}"


def _redact(text: str, *, key: str, profile_id: str) -> str:
    """Remove credentials, profile identity and full ws paths from diagnostics."""
    cleaned = _AUTHORIZATION_RE.sub(r"\1<redacted>", text)
    cleaned = _URL_RE.sub(_redact_url, cleaned)
    cleaned = _PROFILE_ID_RE.sub(r"\1<redacted>", cleaned)
    if profile_id:
        cleaned = cleaned.replace(profile_id, "<redacted>")
    if key:
        cleaned = cleaned.replace(key, "<redacted>")
    return cleaned


def describe_failure(
    *,
    stage: str,
    endpoint: str,
    error: BaseException,
    key: str,
    profile_id: str,
) -> str:
    """Build a redacted, diagnosable failure report for the smoke test."""
    lines = [
        "AdsPower smoke test failed.",
        f"stage={stage}",
        f"endpoint={endpoint or 'unknown'}",
        f"error={_redact(str(error), key=key, profile_id=profile_id)}",
    ]
    return "\n".join(lines)


class SmokeGuardTests(unittest.TestCase):
    """Offline tests for the enable switch, guards and redaction."""

    def test_smoke_requires_flag_key_and_profile(self):
        base = {
            SMOKE_FLAG: "1",
            KEY_ENV: KEY,
            PROFILE_ENV: PROFILE_ID,
        }
        self.assertTrue(smoke_ready(base))
        for name in base:
            env = dict(base)
            env.pop(name)
            self.assertFalse(smoke_ready(env))
        self.assertFalse(smoke_ready({**base, SMOKE_FLAG: "true"}))
        self.assertFalse(smoke_ready({**base, KEY_ENV: "   "}))

    def test_missing_environment_names_every_required_variable(self):
        with self.assertRaises(SmokeConfigError) as raised:
            load_smoke_config({SMOKE_FLAG: "1"})

        message = str(raised.exception)
        self.assertIn(KEY_ENV, message)
        self.assertIn(PROFILE_ENV, message)
        self.assertNotIn(KEY, message)

    def test_complete_environment_loads_values(self):
        config = load_smoke_config(
            {
                SMOKE_FLAG: "1",
                KEY_ENV: KEY,
                PROFILE_ENV: PROFILE_ID,
            }
        )

        self.assertEqual(config.key, KEY)
        self.assertEqual(config.profile_id, PROFILE_ID)

    def test_failure_report_never_contains_secrets_or_ws_path(self):
        error = RuntimeError(
            f"connect failed ws://127.0.0.1:9222/devtools/browser/abcdef "
            f"Authorization: Bearer {KEY} profile_id={PROFILE_ID}"
        )
        report = describe_failure(
            stage="connect",
            endpoint="127.0.0.1:9222",
            error=error,
            key=KEY,
            profile_id=PROFILE_ID,
        )

        self.assertIn("127.0.0.1:9222", report)
        self.assertIn("<redacted>", report)
        self.assertNotIn(KEY, report)
        self.assertNotIn(PROFILE_ID, report)
        self.assertNotIn("/devtools/browser/abcdef", report)

    def test_endpoint_helper_keeps_only_host_and_port(self):
        self.assertEqual(
            _endpoint_of("ws://127.0.0.1:9222/devtools/browser/abcdef"),
            "127.0.0.1:9222",
        )
        self.assertEqual(_endpoint_of("http://127.0.0.1:50325"), "127.0.0.1:50325")
        self.assertEqual(_endpoint_of("not a url"), "unknown")


@unittest.skipUnless(
    smoke_ready(),
    "AdsPower smoke test is opt-in: set SAU_ADSPOWER_SMOKE=1, "
    "ADSPOWER_API_KEY and ADSPOWER_TEST_PROFILE_ID (see module header).",
)
class AdspowerSmokeTests(unittest.TestCase):
    """Real-stack lifecycle check.  Never uploads and never mutates the profile."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_smoke_config()

    def test_lifecycle_probe_start_connect_read_stop(self) -> None:
        asyncio.run(self._run())

    async def _run(self) -> None:
        from patchright.async_api import async_playwright

        from sau_commands.browser import _resolve_adspower_base
        from utils.adspower import (
            AdspowerClient,
            AdspowerProvider,
            AdspowerTarget,
        )
        from utils.errors import StartIncompleteError

        config = self.config
        stage = "config"
        endpoint = "unknown"
        failure: BaseException | None = None
        started = False
        browser = None

        try:
            base = _resolve_adspower_base()
            endpoint = _endpoint_of(base)
            provider = AdspowerProvider(
                AdspowerTarget(config.profile_id),
                AdspowerClient(config.key, base),
            )

            stage = "probe"
            await asyncio.to_thread(provider.probe)

            stage = "start"
            try:
                ws_url = await asyncio.to_thread(provider.start, headless=True)
            except StartIncompleteError:
                # 2xx with an unusable payload: the profile probably started.
                started = True
                raise
            started = True
            endpoint = _endpoint_of(ws_url) or endpoint
            self.assertIsInstance(ws_url, str)
            self.assertTrue(ws_url.strip())

            stage = "connect"
            async with async_playwright() as playwright:
                browser = await playwright.chromium.connect_over_cdp(ws_url)

                stage = "read"
                contexts = browser.contexts
                if not contexts:
                    raise AssertionError("AdsPower 浏览器未返回任何 context")
                context = contexts[0]
                pages = context.pages
                page = pages[0] if pages else await context.new_page()
                url = page.url
                title = await page.title()
                self.assertIsInstance(url, str)
                self.assertIsInstance(title, str)

                stage = "disconnect"
                await browser.close()
                browser = None
        except Exception as exc:
            failure = exc
        finally:
            # Disconnect first, then stop; a stop failure must not mask the
            # original assertion, but must fail the run when nothing else did.
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass
            if started:
                try:
                    await asyncio.to_thread(provider.stop)
                except Exception as stop_exc:
                    if failure is None:
                        failure = stop_exc
                        stage = "stop"

        if failure is not None:
            raise AssertionError(
                describe_failure(
                    stage=stage,
                    endpoint=endpoint,
                    error=failure,
                    key=config.key,
                    profile_id=config.profile_id,
                )
            ) from None


@unittest.skipIf(
    smoke_ready(),
    "skip assertion is only meaningful when the smoke test is disabled",
)
class DefaultDiscoveryTests(unittest.TestCase):
    def test_smoke_case_is_skipped_by_default(self) -> None:
        self.assertTrue(
            getattr(AdspowerSmokeTests, "__unittest_skip__", False),
            "AdspowerSmokeTests must be skipped unless the smoke env is complete",
        )
