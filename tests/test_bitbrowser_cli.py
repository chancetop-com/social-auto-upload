# -*- coding: utf-8 -*-
"""BitBrowser activation, CLI contract, base validation and exit codes (ticket 07)."""

from __future__ import annotations

import argparse
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
from sau_commands import facebook as facebook_command
from sau_commands import tiktok as tiktok_command
from sau_commands import youtube as youtube_command
from tests.fakes import (
    FakeBitBrowserClient,
    FakeBrowser,
    FakeContext,
    FakeHttp,
    FakePlaywright,
    FakeResponse,
)
from utils.bitbrowser import BitBrowserClient, BitBrowserProvider, BitBrowserTarget
from utils.errors import (
    ProviderDiagnosticError,
    RateLimitedError,
    StartIncompleteError,
    UsageError,
)
from utils.multilogin import MultiloginProvider

KEY = "SENTINEL-BITBROWSER-KEY-4a7d1c"
PROFILE = "window-ticket07"
WS_URL = "ws://127.0.0.1:9222/devtools/browser/ticket07"
DEFAULT_BASE = "http://127.0.0.1:54345"
CONFLICT_ADSPOWER = (
    "MLX_API_TOKEN 与 ADSPOWER_API_KEY 不能同时设置；请只保留一个。"
)
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
        self.enter_calls = 0
        self.exit_calls = 0

    async def __aenter__(self):
        self.enter_calls += 1
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        self.exit_calls += 1
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


def _subparser(
    parser: argparse.ArgumentParser, platform: str, action: str | None = None
):
    for item in parser._actions:
        if isinstance(item, argparse._SubParsersAction):
            if platform in item.choices:
                platform_parser = item.choices[platform]
                if action is None:
                    return platform_parser
                for nested in platform_parser._actions:
                    if isinstance(nested, argparse._SubParsersAction):
                        return nested.choices[action]
    raise AssertionError(f"parser not found: {platform}/{action}")


def _action_names(platform: str) -> list[str]:
    platform_parser = _subparser(sau_cli.build_parser(), platform)
    for item in platform_parser._actions:
        if isinstance(item, argparse._SubParsersAction):
            return list(item.choices)
    return []


def _option_strings(parser: argparse.ArgumentParser) -> set[str]:
    return set(parser._option_string_actions)


def _real_seam(client, *, logged_in=True):
    """Exercise the real BitBrowser lifecycle through a TikTok check."""
    playwright = FakePlaywright()
    playwright.chromium.queue_connect_browser(
        FakeBrowser([FakeContext()], allow_new_context=False)
    )
    return (
        patch.object(
            tiktok_command, "async_playwright", lambda: _AsyncCM(playwright)
        ),
        patch.object(
            tiktok_command, "is_logged_in", new=AsyncMock(return_value=logged_in)
        ),
        patch.object(
            browser_command, "BitBrowserClient", MagicMock(return_value=client)
        ),
        playwright,
    )


def _platform_check_with_client(
    module, platform, client, *, extra=(), conf_headless=None
):
    """Exercise one platform's real BitBrowser lifecycle through a check."""
    playwright = FakePlaywright()
    playwright.chromium.queue_connect_browser(
        FakeBrowser([FakeContext()], allow_new_context=False)
    )
    with (
        patch.object(module, "async_playwright", lambda: _AsyncCM(playwright)),
        patch.object(module, "is_logged_in", new=AsyncMock(return_value=True)),
        patch.object(
            browser_command, "BitBrowserClient", MagicMock(return_value=client)
        ),
        patch.object(conf, "LOCAL_CHROME_HEADLESS", conf_headless),
    ):
        code, out, err = _run(
            [platform, "check", "--profile-id", PROFILE, *extra],
            env={"BITBROWSER_API_KEY": KEY},
        )
    return code, out, err, client


def _check_with_client(
    client, *, extra=(), env=None, logged_in=True, conf_headless=None
):
    pw, login, client_patch, playwright = _real_seam(
        client, logged_in=logged_in
    )
    env = {**(env or {"BITBROWSER_API_KEY": KEY})}
    context = (
        patch.object(conf, "LOCAL_CHROME_HEADLESS", conf_headless)
        if conf_headless is not None
        else nullcontext()
    )
    with context:
        with pw, login, client_patch:
            code, out, err = _run(
                [
                    "tiktok",
                    "check",
                    "--profile-id",
                    PROFILE,
                    *extra,
                ],
                env=env,
            )
    return code, out, err, client, playwright


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

    def test_mlx_token_still_takes_priority_in_active_mode(self):
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

    def test_mlx_and_adspower_keep_the_existing_exact_message(self):
        self._conflict(
            {"MLX_API_TOKEN": "mlx-sentinel", "ADSPOWER_API_KEY": "ads-sentinel"},
            CONFLICT_ADSPOWER,
        )

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
    def _provider(self, base, *, args=None):
        fake = FakeBitBrowserClient()
        client_cls = MagicMock(return_value=fake)
        with _env(BITBROWSER_API_KEY=KEY, BITBROWSER_API_BASE=base):
            with patch.object(
                browser_command, "BitBrowserClient", client_cls
            ):
                provider = browser_command.resolve_managed_provider(
                    args or Namespace(profile_id=PROFILE)
                )
        return provider, client_cls

    def test_default_base_is_used_when_env_is_absent(self):
        fake = FakeBitBrowserClient()
        client_cls = MagicMock(return_value=fake)
        with _env(BITBROWSER_API_KEY=KEY):
            with patch.object(browser_command, "BitBrowserClient", client_cls):
                provider = browser_command.resolve_managed_provider(
                    Namespace(profile_id=PROFILE)
                )
        self.assertEqual(provider.mode, "bitbrowser")
        self.assertEqual(provider.profile_id, PROFILE)
        self.assertEqual(client_cls.call_args.args, (KEY, DEFAULT_BASE))

    def test_blank_base_uses_the_default(self):
        for base in ("", "   ", "\t\n"):
            with self.subTest(base=base):
                _, client_cls = self._provider(base)
                self.assertEqual(client_cls.call_args.args, (KEY, DEFAULT_BASE))

    def test_valid_bases_are_normalized(self):
        cases = (
            ("http://127.0.0.1:54345/", "http://127.0.0.1:54345"),
            ("https://127.0.0.1:54346", "https://127.0.0.1:54346"),
            ("http://localhost:54345", "http://localhost:54345"),
            ("https://localhost:443/", "https://localhost:443"),
            ("  http://127.0.0.1:54399  ", "http://127.0.0.1:54399"),
        )
        for raw, expected in cases:
            with self.subTest(base=raw):
                _, client_cls = self._provider(raw)
                self.assertEqual(client_cls.call_args.args, (KEY, expected))

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

    def test_valid_custom_base_receives_the_real_requests(self):
        custom = "http://127.0.0.1:54399"
        http = FakeHttp(
            post_outcomes=[
                FakeResponse(200, {"success": True, "data": {}}),
                FakeResponse(200, {"success": True, "data": []}),
                FakeResponse(
                    200, {"success": True, "data": {"ws": WS_URL}}
                ),
                FakeResponse(200, {"success": True, "data": {}}),
                FakeResponse(200, {"success": True, "data": []}),
            ]
        )
        real_client = BitBrowserClient(
            KEY, custom, http_get=http.get, http_post=http.post
        )
        code, out, err, _, _ = _check_with_client(real_client)

        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "valid")
        self.assertEqual(len(http.post_calls), 5)
        for call in http.post_calls:
            self.assertTrue(call["url"].startswith(f"{custom}/"), call["url"])

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
        fake = FakeBitBrowserClient()
        with _env(
            ADSPOWER_API_KEY="ads-sentinel",
            BITBROWSER_API_BASE="http://127.0.0.1:54345/path",
        ):
            with patch.object(
                browser_command, "AdspowerClient", MagicMock(return_value=fake)
            ):
                provider = browser_command.resolve_managed_provider(
                    Namespace(profile_id=PROFILE)
                )
        self.assertEqual(provider.mode, "adspower")


class ParameterMatrixTests(unittest.TestCase):
    def test_missing_or_blank_profile_id_is_a_usage_error(self):
        for args in (
            Namespace(),
            Namespace(profile_id=None),
            Namespace(profile_id="   "),
        ):
            with self.subTest(args=args):
                with _env(BITBROWSER_API_KEY=KEY):
                    with self.assertRaises(UsageError) as caught:
                        browser_command.resolve_managed_provider(args)
                self.assertIn("--profile-id", str(caught.exception))

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
        fake = FakeBitBrowserClient()
        with _env(BITBROWSER_API_KEY=KEY):
            with patch.object(
                browser_command, "BitBrowserClient", MagicMock(return_value=fake)
            ):
                provider = browser_command.resolve_managed_provider(
                    Namespace(profile_id=copied)
                )
        self.assertEqual(provider.profile_id, copied.strip())
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

    def test_headed_maps_to_headless_false_and_default_is_none(self):
        parser = sau_cli.build_parser()
        default_args = parser.parse_args(
            ["tiktok", "check", "--profile-id", PROFILE]
        )
        headed_args = parser.parse_args(
            ["tiktok", "check", "--profile-id", PROFILE, "--headed"]
        )
        headless_args = parser.parse_args(
            ["tiktok", "check", "--profile-id", PROFILE, "--headless"]
        )
        self.assertIsNone(default_args.headless)
        self.assertFalse(headed_args.headless)
        self.assertTrue(headless_args.headless)

    def test_cold_start_forwards_headed_and_headless_requests(self):
        cases = (
            (("--headed",), False),
            (("--headless",), True),
        )
        for extra, expected in cases:
            with self.subTest(extra=extra):
                client = FakeBitBrowserClient()
                code, out, err, client, _ = _check_with_client(
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
                code, out, err, client, _ = _check_with_client(
                    client, conf_headless=configured
                )
                self.assertEqual(code, 0, err)
                self.assertEqual(out.strip(), "valid")
                self.assertEqual(client.start_calls, [(PROFILE, expected)])

    def test_facebook_and_youtube_omitted_switch_read_local_chrome_headless(self):
        platforms = (
            (facebook_command, "facebook"),
            (youtube_command, "youtube"),
        )
        for configured, expected in ((False, False), (True, True)):
            for module, platform in platforms:
                with self.subTest(configured=configured, platform=platform):
                    client = FakeBitBrowserClient()
                    code, out, err, client = _platform_check_with_client(
                        module,
                        platform,
                        client,
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
            code, _, err, _, _ = _check_with_client(
                client, extra=("--headless",)
            )
        self.assertEqual(code, 0, err)
        rendered = " ".join(str(call) for call in info.call_args_list)
        self.assertIn("mode=bitbrowser", rendered)
        self.assertIn("headless=headless", rendered)
        self.assertIn(f"identity=profile:{PROFILE}", rendered)

    def test_debug_is_accepted_and_not_sent_to_the_api(self):
        parser = sau_cli.build_parser()
        args = parser.parse_args(
            ["tiktok", "check", "--profile-id", PROFILE, "--debug"]
        )
        self.assertTrue(args.debug)
        client = FakeBitBrowserClient()
        code, out, err, client, _ = _check_with_client(
            client, extra=("--debug",)
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "valid")
        self.assertEqual(client.start_calls, [(PROFILE, False)])

    def test_registration_scope_matches_the_shared_matrix(self):
        parser = sau_cli.build_parser()
        for platform in sau_cli.PLATFORMS:
            for action in _action_names(platform):
                options = _option_strings(_subparser(parser, platform, action))
                is_managed_action = action == "check" or action.startswith("upload-")
                with self.subTest(platform=platform, action=action):
                    if not is_managed_action:
                        self.assertNotIn("--folder-id", options)
                        self.assertNotIn("--profile-id", options)
                    else:
                        self.assertIn("--folder-id", options)
                        self.assertIn("--profile-id", options)

    def test_help_mentions_bitbrowser(self):
        platform_parser = _subparser(sau_cli.build_parser(), "tiktok", "check")
        help_text = platform_parser.format_help()
        self.assertIn("比特浏览器", help_text)
        self.assertIn("--profile-id", help_text)
        self.assertIn("--folder-id", help_text)

    def test_login_is_rejected_with_bitbrowser_wording(self):
        platforms = [
            platform
            for platform in sau_cli.PLATFORMS
            if "login" in _action_names(platform)
        ]
        self.assertIn("youtube", platforms)
        for platform in platforms:
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

    def test_article_stays_local_and_accepts_no_browser_flags(self):
        parser = sau_cli.build_parser()
        for action in _action_names("article"):
            options = _option_strings(_subparser(parser, "article", action))
            self.assertNotIn("--profile-id", options)
            self.assertNotIn("--folder-id", options)
        code, out, _ = _run(
            ["article", "themes"], env={"BITBROWSER_API_KEY": KEY}
        )
        self.assertEqual(code, 0)
        self.assertIn("default", out)


class CheckAndExitCodeTests(unittest.TestCase):
    def test_check_success_prints_only_valid_and_opens_once(self):
        client = FakeBitBrowserClient(ws_url=WS_URL)
        code, out, err, client, playwright = _check_with_client(client)

        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "valid")
        self.assertEqual(out, "valid\n")
        self.assertEqual(err, "")
        self.assertEqual(client.probe_calls, 1)
        self.assertEqual(client.start_calls, [(PROFILE, False)])
        self.assertEqual(client.stop_calls, [PROFILE])

        connect = playwright.chromium.connect_calls[0]
        self.assertEqual(connect["url"], WS_URL)
        self.assertEqual(connect["timeout"], 10000)
        self.assertIs(connect["no_defaults"], True)
        self.assertEqual(playwright.chromium.launch_calls, [])

    def test_formal_check_path_opens_and_closes_once_with_the_api_key(self):
        http = FakeHttp(
            post_outcomes=[
                FakeResponse(200, {"success": True, "data": {}}),
                FakeResponse(200, {"success": True, "data": []}),
                FakeResponse(
                    200, {"success": True, "data": {"ws": WS_URL}}
                ),
                FakeResponse(200, {"success": True, "data": {}}),
                FakeResponse(200, {"success": True, "data": []}),
            ]
        )
        real_client = BitBrowserClient(
            KEY, DEFAULT_BASE, http_get=http.get, http_post=http.post
        )
        code, out, err, _, playwright = _check_with_client(real_client)

        self.assertEqual(code, 0, err)
        self.assertEqual(out, "valid\n")
        self.assertEqual(
            [call["url"] for call in http.post_calls],
            [
                f"{DEFAULT_BASE}/health",
                f"{DEFAULT_BASE}/browser/pids/alive",
                f"{DEFAULT_BASE}/browser/open",
                f"{DEFAULT_BASE}/browser/close",
                f"{DEFAULT_BASE}/browser/pids/alive",
            ],
        )
        for call in http.post_calls:
            self.assertEqual(call["headers"], {"x-api-key": KEY})
        self.assertEqual(http.post_calls[2]["json"], {"id": PROFILE})
        self.assertEqual(http.post_calls[3]["json"], {"id": PROFILE})
        self.assertEqual(
            playwright.chromium.connect_calls[0]["url"], WS_URL
        )
        self.assertEqual(playwright.chromium.launch_calls, [])

    def test_check_works_on_a_new_page_in_the_single_existing_context(self):
        playwright = FakePlaywright()
        context = FakeContext()
        playwright.chromium.queue_connect_browser(
            FakeBrowser([context], allow_new_context=False)
        )

        async def probe(session_context):
            await session_context.new_page()
            return True

        with (
            patch.object(
                tiktok_command,
                "async_playwright",
                lambda: _AsyncCM(playwright),
            ),
            patch.object(
                tiktok_command,
                "is_logged_in",
                new=AsyncMock(side_effect=probe),
            ),
            patch.object(
                browser_command,
                "BitBrowserClient",
                MagicMock(return_value=FakeBitBrowserClient(ws_url=WS_URL)),
            ),
        ):
            code, out, err = _run(
                ["tiktok", "check", "--profile-id", PROFILE],
                env={"BITBROWSER_API_KEY": KEY},
            )

        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "valid")
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(len(context.pages), 1)
        self.assertTrue(context.pages[0].closed)
        self.assertEqual(len(playwright.chromium.connect_calls), 1)

    def test_check_joins_an_already_open_window_without_opening(self):
        client = FakeBitBrowserClient(ws_url=WS_URL, active=True)
        code, out, err, client, playwright = _check_with_client(client)

        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "valid")
        self.assertEqual(client.start_calls, [])
        self.assertEqual(client.observe_calls, [PROFILE, PROFILE])
        self.assertEqual(client.stop_calls, [PROFILE])
        self.assertEqual(
            playwright.chromium.connect_calls[0]["url"], WS_URL
        )

    def test_check_not_logged_in_exits_10_with_bitbrowser_wording(self):
        client = FakeBitBrowserClient()
        code, out, err, _, _ = _check_with_client(client, logged_in=False)

        self.assertEqual(code, 10)
        self.assertEqual(out, "")
        self.assertIn("TikTok登录态无效", err)
        self.assertIn("比特浏览器", err)
        self.assertNotIn(KEY, err)

    def test_rate_limited_on_probe_exits_11_without_start_or_stop(self):
        client = FakeBitBrowserClient(
            probe_error=RateLimitedError("probe 429")
        )
        code, _, err, client, playwright = _check_with_client(client)

        self.assertEqual(code, 11)
        self.assertIn("429", err)
        self.assertEqual(client.start_calls, [])
        self.assertEqual(client.stop_calls, [])
        self.assertEqual(playwright.chromium.connect_calls, [])

    def test_rate_limited_on_start_exits_11_without_stop(self):
        client = FakeBitBrowserClient(
            start_error=RateLimitedError("start 429")
        )
        code, _, err, client, _ = _check_with_client(client)

        self.assertEqual(code, 11)
        self.assertIn("429", err)
        self.assertEqual(client.stop_calls, [])

    def test_rate_limited_on_observe_exits_11_without_start_or_stop(self):
        client = FakeBitBrowserClient(
            observe_error=RateLimitedError("observe 429")
        )
        code, _, err, client, playwright = _check_with_client(client)

        self.assertEqual(code, 11)
        self.assertIn("429", err)
        self.assertEqual(client.start_calls, [])
        self.assertEqual(client.stop_calls, [])
        self.assertEqual(playwright.chromium.connect_calls, [])

    def test_port_404_diagnostic_survives_the_shared_wrapper(self):
        message = (
            "查询比特浏览器窗口调试端口失败：HTTP 404；msg=not found；"
            "请检查 BITBROWSER_API_BASE 是否指向本机比特浏览器客户端，"
            "并确认客户端版本支持按窗口 ID 查询进程与调试端口。"
        )
        client = FakeBitBrowserClient(
            observe_error=ProviderDiagnosticError(message)
        )
        code, _, err, client, playwright = _check_with_client(client)

        self.assertEqual(code, 1)
        self.assertIn("查询比特浏览器窗口调试端口失败", err)
        self.assertIn("HTTP 404", err)
        self.assertIn("BITBROWSER_API_BASE", err)
        self.assertNotIn("无法确认 Profile 当前状态或连接", err)
        self.assertNotIn(KEY, err)
        self.assertEqual(client.start_calls, [])
        self.assertEqual(client.stop_calls, [])
        self.assertEqual(playwright.chromium.connect_calls, [])

    def test_business_failure_is_exit_1_and_not_429_or_11(self):
        http = FakeHttp(
            post_outcomes=[
                FakeResponse(200, {"success": True, "data": {}}),
                FakeResponse(
                    200,
                    {"success": False, "msg": "请求频繁，请稍后再试"},
                ),
            ]
        )
        real_client = BitBrowserClient(
            KEY, DEFAULT_BASE, http_get=http.get, http_post=http.post
        )
        code, _, err, _, playwright = _check_with_client(real_client)

        self.assertEqual(code, 1)
        self.assertIn("请求频繁，请稍后再试", err)
        self.assertIn("HTTP 200", err)
        self.assertNotIn(KEY, err)
        self.assertEqual(
            [call["url"] for call in http.post_calls],
            [f"{DEFAULT_BASE}/health", f"{DEFAULT_BASE}/browser/pids/alive"],
        )
        self.assertEqual(playwright.chromium.connect_calls, [])

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
        code, _, err, _, playwright = _check_with_client(real_client)

        self.assertEqual(code, 1)
        self.assertIn("success", err)
        self.assertNotIn(KEY, err)
        self.assertEqual(len(http.post_calls), 2)
        self.assertEqual(playwright.chromium.connect_calls, [])

    def test_shared_cli_leaves_incomplete_start_for_recovery(self):
        client = FakeBitBrowserClient(
            start_error=StartIncompleteError("bad start")
        )
        code, _, err, client, _ = _check_with_client(client)

        self.assertEqual(code, 1)
        self.assertIn("start", err)
        self.assertNotIn("bad start", err)
        self.assertEqual(client.stop_calls, [])

    def test_rate_limited_during_stop_keeps_success_exit_code(self):
        client = FakeBitBrowserClient(
            stop_error=RateLimitedError("stop 429")
        )
        code, out, err, client, _ = _check_with_client(client)

        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "valid")
        self.assertEqual(client.stop_calls, [PROFILE])


class SecretRedactionTests(unittest.TestCase):
    def test_key_never_appears_in_startup_logs_or_warnings(self):
        http = FakeHttp(
            post_outcomes=[
                FakeResponse(200, {"success": True, "data": {}}),
                FakeResponse(200, {"success": True, "data": []}),
                FakeResponse(
                    200, {"success": True, "data": {"ws": WS_URL}}
                ),
                FakeResponse(200, {"success": True, "data": {}}),
                FakeResponse(200, {"success": True, "data": []}),
            ]
        )
        real_client = BitBrowserClient(
            KEY, DEFAULT_BASE, http_get=http.get, http_post=http.post
        )
        with (
            patch("utils.browser_session.logger.info") as info,
            patch("utils.browser_session.logger.warning") as warning,
        ):
            code, out, err, _, _ = _check_with_client(real_client)

        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "valid")
        info.assert_called()
        rendered = " ".join(
            str(call)
            for call in info.call_args_list + warning.call_args_list
        )
        self.assertNotIn(KEY, rendered)
        self.assertIn(PROFILE, rendered)

    def test_key_never_appears_in_outputs_or_reprs(self):
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
        code, out, err, _, _ = _check_with_client(client)
        scenarios.append((code, out + err))

        for code, output in scenarios:
            self.assertNotEqual(code, 0)
            self.assertNotIn(KEY, output)

        client = BitBrowserClient(KEY, DEFAULT_BASE)
        self.assertNotIn(KEY, repr(client))
        provider = BitBrowserProvider(BitBrowserTarget(PROFILE), client)
        self.assertNotIn(KEY, repr(provider))


if __name__ == "__main__":
    unittest.main()
