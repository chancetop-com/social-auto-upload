# -*- coding: utf-8 -*-
"""BitBrowser activation, CLI contract, base validation and exit codes (ticket 07)."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from argparse import Namespace
from contextlib import contextmanager, nullcontext, redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import conf
import sau_cli
from sau_commands import browser as browser_command
from sau_commands import youtube as youtube_command
from tests.fakes import (
    FakeBitBrowserClient,
    FakeBrowser,
    FakeContext,
    FakeHttp,
    FakePlaywright,
    FakeResponse,
)
from utils.base_social_media import get_supported_social_media
from utils.bitbrowser import BitBrowserClient
from utils.errors import StartIncompleteError, UsageError
from utils.multilogin import MultiloginProvider

KEY = "SENTINEL-BITBROWSER-KEY-4a7d1c"
PROFILE = "window-ticket07"
DEFAULT_BASE = "http://127.0.0.1:54345"
CONFLICT_BITBROWSER_ADSPOWER = (
    "ADSPOWER_API_KEY 与 BITBROWSER_API_KEY 不能同时设置；请只保留一个。"
)
CONFLICT_MLX_BITBROWSER = (
    "MLX_API_TOKEN 与 BITBROWSER_API_KEY 不能同时设置；请只保留一个。"
)
CONFLICT_ALL = (
    "MLX_API_TOKEN、ADSPOWER_API_KEY 与 BITBROWSER_API_KEY 不能同时设置；"
    "请只保留一个。"
)


class _AsyncCM:
    def __init__(self, value=None) -> None:
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False


@contextmanager
def _env(**values):
    with patch.dict(os.environ, values, clear=True):
        yield


def _run(argv, *, env=None):
    with tempfile.TemporaryDirectory() as home, _env(
        HOME=home, USERPROFILE=home, **(env or {})
    ):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(
            io.StringIO()
        ) as err:
            code = sau_cli.main(argv)
    return code, out.getvalue(), err.getvalue()


def _check_with_client(client, *, platform="tiktok", extra=(), conf_headless=None):
    """Exercise one platform's real BitBrowser lifecycle through a check."""
    playwright = FakePlaywright()
    playwright.chromium.queue_connect_browser(
        FakeBrowser([FakeContext()], allow_new_context=False)
    )
    module = sau_cli.PLATFORMS[platform]
    with (
        patch.object(module, "async_playwright", lambda: _AsyncCM(playwright)),
        patch.object(module, "is_logged_in", new=AsyncMock(return_value=True)),
        patch.object(
            browser_command, "BitBrowserClient", MagicMock(return_value=client)
        ),
        patch.object(conf, "LOCAL_CHROME_HEADLESS", conf_headless)
        if conf_headless is not None else nullcontext(),
    ):
        code, out, err = _run(
            [platform, "check", "--profile-id", PROFILE, *extra],
            env={"BITBROWSER_API_KEY": KEY},
        )
    return code, out, err, playwright


class ActivationTests(unittest.TestCase):
    def test_activation_truth_table_uses_stripped_values(self):
        cases = (
            ({}, None),
            ({"BITBROWSER_API_KEY": ""}, None),
            ({"BITBROWSER_API_KEY": "   \t\n"}, None),
            ({"BITBROWSER_API_KEY": KEY}, "bitbrowser"),
            ({"BITBROWSER_API_KEY": f"  {KEY}  "}, "bitbrowser"),
        )
        for env, expected in cases:
            with self.subTest(env=env):
                with _env(**env):
                    self.assertEqual(browser_command.active_mode(), expected)
                    self.assertIs(
                        browser_command.managed_enabled(), expected is not None
                    )

    def test_each_single_credential_selects_its_provider(self):
        cases = (
            ({"BITBROWSER_API_KEY": KEY}, "bitbrowser"),
            ({"ADSPOWER_API_KEY": "adspower-key"}, "adspower"),
            ({"MLX_API_TOKEN": "mlx-token"}, "multilogin"),
        )
        for env, expected in cases:
            with self.subTest(env=env):
                with _env(**env):
                    self.assertEqual(browser_command.active_mode(), expected)

    def test_bitbrowser_base_alone_does_not_activate_or_warn(self):
        with _env(BITBROWSER_API_BASE="http://127.0.0.1:9999"):
            with redirect_stderr(io.StringIO()) as err:
                self.assertIsNone(browser_command.active_mode())
                self.assertFalse(browser_command.managed_enabled())
        self.assertEqual(err.getvalue(), "")

    def test_direct_mode_lookup_prefers_existing_providers_on_conflict(self):
        with _env(MLX_API_TOKEN="mlx-sentinel", BITBROWSER_API_KEY=KEY):
            self.assertEqual(browser_command.active_mode(), "multilogin")
        with _env(ADSPOWER_API_KEY="ads-sentinel", BITBROWSER_API_KEY=KEY):
            self.assertEqual(browser_command.active_mode(), "adspower")


class ConflictTests(unittest.TestCase):
    def _conflict(self, env, expected):
        dispatch = AsyncMock(return_value=0)
        client_cls = MagicMock()
        with (
            patch.object(sau_cli, "dispatch", new=dispatch),
            patch.object(browser_command, "BitBrowserClient", client_cls),
        ):
            code, out, err = _run(
                ["tiktok", "check", "--profile-id", PROFILE], env=env
            )
        self.assertEqual(code, 1)
        self.assertIn(expected, err)
        self.assertEqual(out, "")
        dispatch.assert_not_awaited()
        client_cls.assert_not_called()
        return err

    def test_bitbrowser_and_adspower_conflict_names_both_variables(self):
        err = self._conflict(
            {
                "ADSPOWER_API_KEY": "ads-sentinel",
                "BITBROWSER_API_KEY": KEY,
            },
            CONFLICT_BITBROWSER_ADSPOWER,
        )
        self.assertNotIn("MLX_API_TOKEN", err)
        self.assertNotIn("ads-sentinel", err)
        self.assertNotIn(KEY, err)

    def test_mlx_and_bitbrowser_conflict_names_both_variables(self):
        err = self._conflict(
            {"MLX_API_TOKEN": "mlx-sentinel", "BITBROWSER_API_KEY": KEY},
            CONFLICT_MLX_BITBROWSER,
        )
        self.assertNotIn("ADSPOWER_API_KEY", err)
        self.assertNotIn("mlx-sentinel", err)
        self.assertNotIn(KEY, err)

    def test_all_three_credentials_conflict_names_all_variables(self):
        err = self._conflict(
            {
                "MLX_API_TOKEN": "mlx-sentinel",
                "ADSPOWER_API_KEY": "ads-sentinel",
                "BITBROWSER_API_KEY": KEY,
            },
            CONFLICT_ALL,
        )
        self.assertNotIn("mlx-sentinel", err)
        self.assertNotIn("ads-sentinel", err)
        self.assertNotIn(KEY, err)

    def test_blank_or_whitespace_credentials_do_not_conflict(self):
        with _env(
            MLX_API_TOKEN="   ",
            ADSPOWER_API_KEY="\t",
            BITBROWSER_API_KEY=f"  {KEY}  ",
        ):
            self.assertFalse(browser_command.credentials_conflict())
            self.assertEqual(browser_command.active_mode(), "bitbrowser")

    def test_conflict_takes_precedence_over_login_rejection(self):
        code, _, err = _run(
            ["youtube", "login"],
            env={
                "ADSPOWER_API_KEY": "ads-sentinel",
                "BITBROWSER_API_KEY": KEY,
            },
        )
        self.assertEqual(code, 1)
        self.assertIn(CONFLICT_BITBROWSER_ADSPOWER, err)
        self.assertNotIn("不支持 CLI 登录", err)

    def test_help_keeps_argparse_semantics_with_conflicting_credentials(self):
        with _env(
            ADSPOWER_API_KEY="ads-sentinel", BITBROWSER_API_KEY=KEY
        ):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    sau_cli.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_unknown_subcommand_keeps_argparse_semantics_with_conflict(self):
        with _env(
            ADSPOWER_API_KEY="ads-sentinel", BITBROWSER_API_KEY=KEY
        ):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    sau_cli.main(["not-a-platform"])
        self.assertEqual(ctx.exception.code, 2)

    def test_missing_required_argument_keeps_argparse_semantics_with_conflict(self):
        with _env(
            ADSPOWER_API_KEY="ads-sentinel", BITBROWSER_API_KEY=KEY
        ):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    sau_cli.main(["youtube", "upload-video"])
        self.assertEqual(ctx.exception.code, 2)


class BaseValidationTests(unittest.TestCase):
    def test_health_request_uses_the_configured_or_default_base(self):
        cases = (
            (None, DEFAULT_BASE),
            ("", DEFAULT_BASE),
            (" \t\n", DEFAULT_BASE),
            ("http://127.0.0.1:54345/", "http://127.0.0.1:54345"),
            ("https://127.0.0.1:54346", "https://127.0.0.1:54346"),
            ("http://localhost:54345", "http://localhost:54345"),
            ("https://localhost:443/", "https://localhost:443"),
            ("  http://127.0.0.1:54399  ", "http://127.0.0.1:54399"),
        )
        for raw, expected in cases:
            with self.subTest(base=raw):
                env = {"BITBROWSER_API_KEY": KEY}
                if raw is not None:
                    env["BITBROWSER_API_BASE"] = raw
                http = FakeHttp(post_outcomes=[FakeResponse(200, {"success": True})])
                with _env(**env), patch("utils.bitbrowser.requests.post", http.post):
                    provider = browser_command.resolve_managed_provider(Namespace(profile_id=PROFILE))
                    provider.probe()
                request, = http.post_calls
                self.assertEqual(request["url"], f"{expected}/health")
                self.assertEqual(request["headers"]["x-api-key"], KEY)

    def test_invalid_bases_exit_2_without_constructing_the_client(self):
        invalid = (
            "ftp://127.0.0.1:54345",
            "127.0.0.1:54345",
            "http://",
            "http:///path",
            "http://user@127.0.0.1:54345",
            "http://user:pass@127.0.0.1:54345",
            "http://127.0.0.1:54345/path",
            "http://127.0.0.1:54345/?query=1",
            "http://127.0.0.1:54345/#fragment",
            "http://127.0.0.1:notaport",
            "http://127.0.0.1:70000",
            "http://127.0.0.1:",
        )
        for base in invalid:
            with self.subTest(base=base):
                client_cls = MagicMock()
                with _env(BITBROWSER_API_KEY=KEY, BITBROWSER_API_BASE=base):
                    with patch.object(
                        browser_command, "BitBrowserClient", client_cls
                    ):
                        with self.assertRaises(UsageError):
                            browser_command.resolve_managed_provider(
                                Namespace(profile_id=PROFILE)
                            )
                client_cls.assert_not_called()

    def test_invalid_base_through_cli_exits_2_with_zero_http(self):
        client_cls = MagicMock()
        with patch.object(browser_command, "BitBrowserClient", client_cls):
            code, _, err = _run(
                ["tiktok", "check", "--profile-id", PROFILE],
                env={
                    "BITBROWSER_API_KEY": KEY,
                    "BITBROWSER_API_BASE": "http://127.0.0.1:54345/path",
                },
            )
        self.assertEqual(code, 2)
        self.assertIn("BITBROWSER_API_BASE", err)
        client_cls.assert_not_called()

    def test_base_is_not_validated_in_local_mode(self):
        with _env(BITBROWSER_API_BASE="http://127.0.0.1:54345/path"):
            self.assertIsNone(
                browser_command.resolve_managed_provider(
                    Namespace(profile_id=PROFILE)
                )
            )

    def test_base_is_not_validated_in_mlx_mode(self):
        with _env(
            MLX_API_TOKEN="mlx-sentinel",
            BITBROWSER_API_BASE="http://127.0.0.1:54345/path",
        ):
            provider = browser_command.resolve_managed_provider(
                Namespace(folder_id="folder", profile_id=PROFILE)
            )
        self.assertIsInstance(provider, MultiloginProvider)
        self.assertEqual(provider.mode, "multilogin")

    def test_base_is_not_validated_in_adspower_mode(self):
        with _env(
            ADSPOWER_API_KEY="ads-sentinel",
            BITBROWSER_API_BASE="http://127.0.0.1:54345/path",
        ):
            provider = browser_command.resolve_managed_provider(
                Namespace(profile_id=PROFILE)
            )
        self.assertEqual(provider.mode, "adspower")


class ParameterMatrixTests(unittest.TestCase):
    def test_missing_profile_id_through_cli_exits_2_without_http(self):
        for argv in (
            ["tiktok", "check"],
            ["tiktok", "check", "--profile-id", "   "],
        ):
            with self.subTest(argv=argv):
                client_cls = MagicMock()
                with patch.object(
                    browser_command, "BitBrowserClient", client_cls
                ):
                    code, _, err = _run(argv, env={"BITBROWSER_API_KEY": KEY})
                self.assertEqual(code, 2)
                self.assertIn("--profile-id", err)
                client_cls.assert_not_called()

    def test_profile_id_is_kept_as_the_copied_string(self):
        copied = "  AbC-123_xYz  "
        with _env(BITBROWSER_API_KEY=KEY):
            provider = browser_command.resolve_managed_provider(Namespace(profile_id=copied))
        self.assertEqual(provider.profile_id, "AbC-123_xYz")

    def test_folder_id_is_registered_but_silently_ignored(self):
        fake = FakeBitBrowserClient()
        with _env(BITBROWSER_API_KEY=KEY):
            with patch.object(
                browser_command, "BitBrowserClient", MagicMock(return_value=fake)
            ):
                with redirect_stderr(io.StringIO()) as err:
                    provider = browser_command.resolve_managed_provider(
                        Namespace(profile_id=PROFILE, folder_id="ignored")
                    )
        self.assertEqual(provider.profile_id, PROFILE)
        self.assertEqual(fake.probe_calls, 0)
        self.assertEqual(err.getvalue(), "")

    def test_account_is_optional_and_ignored_in_favour_of_profile(self):
        factory = MagicMock(
            return_value=_AsyncCM(SimpleNamespace(context=object()))
        )
        with (
            patch.object(
                youtube_command, "async_playwright", lambda: _AsyncCM(object())
            ),
            patch.object(youtube_command, "browser_session", new=factory),
            patch.object(
                youtube_command, "is_logged_in", new=AsyncMock(return_value=True)
            ),
        ):
            code, out, _ = _run(
                ["youtube", "check", "--profile-id", PROFILE],
                env={"BITBROWSER_API_KEY": KEY},
            )
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "valid")
        provider = factory.call_args.kwargs["managed"]
        self.assertEqual(provider.profile_id, PROFILE)
        with _env(BITBROWSER_API_KEY=KEY):
            self.assertEqual(
                browser_command.resolve_account_label(
                    Namespace(profile_id=PROFILE, account=None)
                ),
                PROFILE,
            )
            self.assertEqual(
                browser_command.resolve_account_label(
                    Namespace(profile_id=PROFILE, account="creator")
                ),
                PROFILE,
            )

    def test_managed_account_is_reported_as_an_ignored_key(self):
        with _env(BITBROWSER_API_KEY=KEY):
            self.assertEqual(
                browser_command.managed_ignored_keys(
                    Namespace(profile_id=PROFILE, account="creator")
                ),
                ("account",),
            )
            self.assertEqual(
                browser_command.managed_ignored_keys(
                    Namespace(profile_id=PROFILE, account=None)
                ),
                (),
            )
            self.assertEqual(
                browser_command.managed_ignored_keys(
                    Namespace(profile_id=PROFILE, account="  ")
                ),
                (),
            )
        with _env():
            self.assertEqual(
                browser_command.managed_ignored_keys(
                    Namespace(account="creator")
                ),
                (),
            )

    def test_cold_start_forwards_headed_and_headless_requests(self):
        cases = (
            (("--headed",), False),
            (("--headless",), True),
        )
        for extra, expected in cases:
            with self.subTest(extra=extra):
                client = FakeBitBrowserClient()
                code, out, err, _ = _check_with_client(
                    client, extra=extra
                )
                self.assertEqual(code, 0, err)
                self.assertEqual(out.strip(), "valid")
                self.assertEqual(client.start_calls, [(PROFILE, expected)])

    def test_omitted_switch_reads_local_chrome_headless(self):
        cases = ((False, False), (True, True))
        for configured, expected in cases:
            with self.subTest(configured=configured):
                client = FakeBitBrowserClient()
                code, out, err, _ = _check_with_client(
                    client, conf_headless=configured
                )
                self.assertEqual(code, 0, err)
                self.assertEqual(out.strip(), "valid")
                self.assertEqual(client.start_calls, [(PROFILE, expected)])

    def test_facebook_and_youtube_omitted_switch_read_local_chrome_headless(self):
        for configured, expected in ((False, False), (True, True)):
            for platform in ("facebook", "youtube"):
                with self.subTest(configured=configured, platform=platform):
                    client = FakeBitBrowserClient()
                    code, out, err, _ = _check_with_client(
                        client, platform=platform,
                        conf_headless=configured,
                    )
                    self.assertEqual(code, 0, err)
                    self.assertEqual(out.strip(), "valid")
                    self.assertEqual(
                        client.start_calls, [(PROFILE, expected)]
                    )

    def test_startup_log_records_the_requested_mode(self):
        client = FakeBitBrowserClient()
        with patch("utils.browser_session.logger.info") as info:
            code, _, err, _ = _check_with_client(
                client, extra=("--headless",)
            )
        self.assertEqual(code, 0, err)
        rendered = " ".join(str(call) for call in info.call_args_list)
        self.assertIn("mode=bitbrowser", rendered)
        self.assertIn("headless=headless", rendered)
        self.assertIn(f"identity=profile:{PROFILE}", rendered)

    def test_help_mentions_bitbrowser(self):
        with redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit) as exit_:
            sau_cli.main(["tiktok", "check", "--help"])
        self.assertEqual(exit_.exception.code, 0)
        help_text = output.getvalue()
        self.assertIn("比特浏览器", help_text)
        self.assertIn("--profile-id", help_text)
        self.assertIn("--folder-id", help_text)

    def test_login_is_rejected_with_bitbrowser_wording(self):
        for platform in get_supported_social_media():
            with self.subTest(platform=platform):
                code, _, err = _run(
                    [platform, "login"], env={"BITBROWSER_API_KEY": KEY}
                )
                self.assertEqual(code, 1)
                self.assertIn("比特浏览器模式不支持 CLI 登录", err)
                self.assertIn("指定 Profile", err)

    def test_login_with_explicit_profile_is_an_argparse_error(self):
        with _env(BITBROWSER_API_KEY=KEY):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    sau_cli.main(["youtube", "login", "--profile-id", PROFILE])
        self.assertEqual(ctx.exception.code, 2)

    def test_local_only_actions_still_require_account(self):
        platforms = {
            "facebook": ["--post-url", "u", "--owner-id", "1", "--expected-text", "t"],
            "facebook-page": [
                "--page-id", "1", "--page", "Page", "--content-id", "c",
                "--expected-text", "t",
            ],
            "instagram": ["--post-url", "u", "--expected-text", "t"],
        }
        for platform, arguments in platforms.items():
            for action in ("verify", "delete"):
                with self.subTest(platform=platform, action=action):
                    code, _, err = _run(
                        [platform, action, *arguments],
                        env={"BITBROWSER_API_KEY": KEY},
                    )
                    self.assertEqual(code, 2)
                    self.assertIn("--account", err)

    def test_article_themes_stays_local_with_bitbrowser_credentials(self):
        code, out, _ = _run(
            ["article", "themes"], env={"BITBROWSER_API_KEY": KEY}
        )
        self.assertEqual(code, 0)
        self.assertIn("default", out)


class CheckAndExitCodeTests(unittest.TestCase):
    def test_malformed_envelope_is_exit_1_without_opening(self):
        http = FakeHttp(
            post_outcomes=[
                FakeResponse(200, {"success": True, "data": {}}),
                FakeResponse(200, {"success": "yes"}),
            ]
        )
        real_client = BitBrowserClient(
            KEY, DEFAULT_BASE, http_get=http.get, http_post=http.post
        )
        code, _, err, playwright = _check_with_client(real_client)

        self.assertEqual(code, 1)
        self.assertIn("success", err)
        self.assertNotIn(KEY, err)
        self.assertEqual(len(http.post_calls), 2)
        self.assertEqual(playwright.chromium.connect_calls, [])

    def test_shared_cli_leaves_incomplete_start_for_recovery(self):
        client = FakeBitBrowserClient(
            start_error=StartIncompleteError("bad start")
        )
        code, _, err, _ = _check_with_client(client)

        self.assertEqual(code, 1)
        self.assertIn("start", err)
        self.assertNotIn("bad start", err)
        self.assertEqual(client.stop_calls, [])


class SecretRedactionTests(unittest.TestCase):
    def test_key_never_appears_in_cli_errors(self):
        scenarios = []

        code, out, err = _run(
            ["tiktok", "check"], env={"BITBROWSER_API_KEY": KEY}
        )
        scenarios.append((code, out + err))

        code, out, err = _run(
            ["youtube", "login"], env={"BITBROWSER_API_KEY": KEY}
        )
        scenarios.append((code, out + err))

        code, out, err = _run(
            ["tiktok", "check", "--profile-id", PROFILE],
            env={
                "BITBROWSER_API_KEY": KEY,
                "BITBROWSER_API_BASE": "http://127.0.0.1:54345/path",
            },
        )
        scenarios.append((code, out + err))

        client = FakeBitBrowserClient(
            probe_error=RuntimeError("probe boom")
        )
        code, out, err, _ = _check_with_client(client)
        scenarios.append((code, out + err))

        for code, output in scenarios:
            self.assertNotEqual(code, 0)
            self.assertNotIn(KEY, output)


if __name__ == "__main__":
    unittest.main()
