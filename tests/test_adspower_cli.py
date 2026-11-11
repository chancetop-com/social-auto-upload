# -*- coding: utf-8 -*-
"""AdsPower activation, CLI contract, base validation and exit codes (ticket 13)."""

from __future__ import annotations

import argparse
import io
import os
import tempfile
import unittest
from argparse import Namespace
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import sau_cli
from sau_commands import browser as browser_command
from sau_commands import dayu as dayu_command
from sau_commands import douyin as douyin_command
from sau_commands import facebook as facebook_command
from sau_commands import facebook_page as facebook_page_command
from sau_commands import instagram as instagram_command
from sau_commands import xueqiu as xueqiu_command
from sau_commands import zhihu as zhihu_command
from tests.fakes import (
    FakeAdspowerClient,
    FakeBrowser,
    FakeContext,
    FakePlaywright,
)
from utils.adspower import AdspowerClient, AdspowerProvider, AdspowerTarget
from utils.errors import (
    PublishResultUnknownError,
    RateLimitedError,
    StartIncompleteError,
    UsageError,
)
from utils.multilogin import MultiloginProvider

KEY = "SENTINEL-ADSPOWER-KEY-9c1f2a"
PROFILE = "profile-ticket13"
WS_URL = "ws://127.0.0.1:9222/devtools/browser/ticket13"
DEFAULT_BASE = "http://127.0.0.1:50325"
CONFLICT_MESSAGE = (
    "MLX_API_TOKEN 与 ADSPOWER_API_KEY 不能同时设置；请只保留一个。"
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
    with _env(**(env or {})):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(
            io.StringIO()
        ) as err:
            code = sau_cli.main(argv)
    return code, out.getvalue(), err.getvalue()


def _subparser(parser: argparse.ArgumentParser, platform: str, action: str | None = None):
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


def _real_seam(fake, *, logged_in=True):
    """Patch a douyin-style check to use the real lifecycle with a fake client."""
    playwright = FakePlaywright()
    playwright.chromium.queue_connect_browser(
        FakeBrowser([FakeContext()], allow_new_context=False)
    )
    return (
        patch.object(
            douyin_command, "async_playwright", lambda: _AsyncCM(playwright)
        ),
        patch.object(
            douyin_command, "is_logged_in", new=AsyncMock(return_value=logged_in)
        ),
        patch.object(browser_command, "AdspowerClient", MagicMock(return_value=fake)),
        playwright,
    )


class ActivationTests(unittest.TestCase):
    def test_activation_truth_table_uses_stripped_values(self):
        cases = (
            ({}, None),
            ({"ADSPOWER_API_KEY": ""}, None),
            ({"ADSPOWER_API_KEY": "   \t\n"}, None),
            ({"ADSPOWER_API_KEY": KEY}, "adspower"),
            ({"ADSPOWER_API_KEY": f"  {KEY}  "}, "adspower"),
        )
        for env, expected in cases:
            with self.subTest(env=env):
                with _env(**env):
                    self.assertEqual(browser_command.active_mode(), expected)
                    self.assertIs(
                        browser_command.managed_enabled(), expected is not None
                    )

    def test_adspower_base_alone_does_not_activate_or_warn(self):
        with _env(ADSPOWER_API_BASE="http://127.0.0.1:9999"):
            with redirect_stderr(io.StringIO()) as err:
                self.assertIsNone(browser_command.active_mode())
                self.assertFalse(browser_command.managed_enabled())
        self.assertEqual(err.getvalue(), "")

    def test_mlx_token_still_takes_priority_in_active_mode(self):
        with _env(MLX_API_TOKEN="mlx-sentinel", ADSPOWER_API_KEY=KEY):
            self.assertEqual(browser_command.active_mode(), "multilogin")


class ConflictTests(unittest.TestCase):
    def test_dual_credentials_exit_1_with_exact_message(self):
        code, _, err = _run(
            ["douyin", "check", "--profile-id", PROFILE],
            env={"MLX_API_TOKEN": "mlx-sentinel", "ADSPOWER_API_KEY": KEY},
        )
        self.assertEqual(code, 1)
        self.assertIn(CONFLICT_MESSAGE, err)

    def test_conflict_takes_precedence_over_login_rejection(self):
        code, _, err = _run(
            ["douyin", "login"],
            env={"MLX_API_TOKEN": "mlx-sentinel", "ADSPOWER_API_KEY": KEY},
        )
        self.assertEqual(code, 1)
        self.assertIn(CONFLICT_MESSAGE, err)
        self.assertNotIn("不支持 CLI 登录", err)

    def test_help_keeps_argparse_semantics_with_both_credentials(self):
        with _env(MLX_API_TOKEN="mlx-sentinel", ADSPOWER_API_KEY=KEY):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    sau_cli.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_unknown_subcommand_keeps_argparse_semantics_with_both_credentials(self):
        with _env(MLX_API_TOKEN="mlx-sentinel", ADSPOWER_API_KEY=KEY):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    sau_cli.main(["not-a-platform"])
        self.assertEqual(ctx.exception.code, 2)

    def test_missing_required_argument_keeps_argparse_semantics(self):
        with _env(MLX_API_TOKEN="mlx-sentinel", ADSPOWER_API_KEY=KEY):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    sau_cli.main(["douyin", "upload-video"])
        self.assertEqual(ctx.exception.code, 2)


class BaseValidationTests(unittest.TestCase):
    def _provider(self, base, *, args=None):
        fake = FakeAdspowerClient()
        client_cls = MagicMock(return_value=fake)
        with _env(ADSPOWER_API_KEY=KEY, ADSPOWER_API_BASE=base):
            with patch.object(
                browser_command, "AdspowerClient", client_cls
            ):
                provider = browser_command.resolve_managed_provider(
                    args or Namespace(profile_id=PROFILE)
                )
        return provider, client_cls

    def test_default_base_is_used_when_env_is_absent(self):
        fake = FakeAdspowerClient()
        client_cls = MagicMock(return_value=fake)
        with _env(ADSPOWER_API_KEY=KEY):
            with patch.object(browser_command, "AdspowerClient", client_cls):
                provider = browser_command.resolve_managed_provider(
                    Namespace(profile_id=PROFILE)
                )
        self.assertEqual(provider.mode, "adspower")
        self.assertEqual(provider.profile_id, PROFILE)
        self.assertEqual(client_cls.call_args.args, (KEY, DEFAULT_BASE))

    def test_valid_bases_are_normalized(self):
        cases = (
            ("http://127.0.0.1:50325/", "http://127.0.0.1:50325"),
            ("https://127.0.0.1:50326", "https://127.0.0.1:50326"),
            (
                "http://local.adspower.net:50325",
                "http://local.adspower.net:50325",
            ),
            ("https://localhost:443/", "https://localhost:443"),
        )
        for raw, expected in cases:
            with self.subTest(base=raw):
                _, client_cls = self._provider(raw)
                self.assertEqual(client_cls.call_args.args, (KEY, expected))

    def test_invalid_bases_exit_2_without_constructing_the_client(self):
        invalid = (
            "ftp://127.0.0.1:50325",
            "127.0.0.1:50325",
            "http://",
            "http:///path",
            "http://user@127.0.0.1:50325",
            "http://user:pass@127.0.0.1:50325",
            "http://127.0.0.1:50325/path",
            "http://127.0.0.1:50325/?query=1",
            "http://127.0.0.1:50325/#fragment",
            "http://127.0.0.1:notaport",
            "http://127.0.0.1:70000",
            "http://127.0.0.1:",
        )
        for base in invalid:
            with self.subTest(base=base):
                client_cls = MagicMock()
                with _env(ADSPOWER_API_KEY=KEY, ADSPOWER_API_BASE=base):
                    with patch.object(
                        browser_command, "AdspowerClient", client_cls
                    ):
                        with self.assertRaises(UsageError):
                            browser_command.resolve_managed_provider(
                                Namespace(profile_id=PROFILE)
                            )
                client_cls.assert_not_called()

    def test_invalid_base_through_cli_exits_2_with_zero_http(self):
        client_cls = MagicMock()
        with patch.object(browser_command, "AdspowerClient", client_cls):
            code, _, _ = _run(
                ["douyin", "check", "--profile-id", PROFILE],
                env={
                    "ADSPOWER_API_KEY": KEY,
                    "ADSPOWER_API_BASE": "http://127.0.0.1:50325/path",
                },
            )
        self.assertEqual(code, 2)
        client_cls.assert_not_called()

    def test_base_is_not_validated_in_local_mode(self):
        with _env(ADSPOWER_API_BASE="http://127.0.0.1:50325/path"):
            self.assertIsNone(
                browser_command.resolve_managed_provider(
                    Namespace(profile_id=PROFILE)
                )
            )

    def test_base_is_not_validated_in_mlx_mode(self):
        with _env(
            MLX_API_TOKEN="mlx-sentinel",
            ADSPOWER_API_BASE="http://127.0.0.1:50325/path",
        ):
            provider = browser_command.resolve_managed_provider(
                Namespace(folder_id="folder", profile_id=PROFILE)
            )
        self.assertIsInstance(provider, MultiloginProvider)
        self.assertEqual(provider.mode, "multilogin")


class ParameterMatrixTests(unittest.TestCase):
    def test_missing_profile_id_is_usage_error(self):
        with _env(ADSPOWER_API_KEY=KEY):
            for args in (Namespace(), Namespace(profile_id=None), Namespace(profile_id="   ")):
                with self.subTest(args=args):
                    with self.assertRaises(UsageError):
                        browser_command.resolve_managed_provider(args)

        code, _, _ = _run(
            ["douyin", "check"], env={"ADSPOWER_API_KEY": KEY}
        )
        self.assertEqual(code, 2)

    def test_folder_id_is_registered_but_silently_ignored(self):
        fake = FakeAdspowerClient()
        with _env(ADSPOWER_API_KEY=KEY):
            with patch.object(
                browser_command, "AdspowerClient", MagicMock(return_value=fake)
            ):
                with redirect_stderr(io.StringIO()) as err:
                    provider = browser_command.resolve_managed_provider(
                        Namespace(profile_id=PROFILE, folder_id="ignored")
                    )
        self.assertEqual(provider.profile_id, PROFILE)
        self.assertEqual(fake.probe_calls, 0)
        self.assertEqual(err.getvalue(), "")

    def test_account_is_optional_and_label_defaults_to_profile(self):
        factory = MagicMock(
            return_value=_AsyncCM(SimpleNamespace(context=object()))
        )
        with (
            patch.object(
                douyin_command, "async_playwright", lambda: _AsyncCM(object())
            ),
            patch.object(douyin_command, "browser_session", new=factory),
            patch.object(
                douyin_command, "is_logged_in", new=AsyncMock(return_value=True)
            ),
        ):
            code, out, _ = _run(
                ["douyin", "check", "--profile-id", PROFILE],
                env={"ADSPOWER_API_KEY": KEY},
            )
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "valid")
        provider = factory.call_args.kwargs["managed"]
        self.assertEqual(provider.profile_id, PROFILE)
        with _env(ADSPOWER_API_KEY=KEY):
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
                "creator",
            )

    def test_headed_maps_to_headless_false_and_default_is_false(self):
        parser = sau_cli.build_parser()
        default_args = parser.parse_args(
            ["douyin", "check", "--profile-id", PROFILE]
        )
        headed_args = parser.parse_args(
            ["douyin", "check", "--profile-id", PROFILE, "--headed"]
        )
        headless_args = parser.parse_args(
            ["douyin", "check", "--profile-id", PROFILE, "--headless"]
        )
        self.assertFalse(default_args.headless)
        self.assertFalse(headed_args.headless)
        self.assertTrue(headless_args.headless)

    def test_headed_is_forwarded_to_provider_start(self):
        fake = FakeAdspowerClient()
        playwright = FakePlaywright()
        playwright.chromium.queue_connect_browser(
            FakeBrowser([FakeContext()], allow_new_context=False)
        )
        with (
            patch.object(
                douyin_command, "async_playwright", lambda: _AsyncCM(playwright)
            ),
            patch.object(
                douyin_command, "is_logged_in", new=AsyncMock(return_value=True)
            ),
            patch.object(
                browser_command, "AdspowerClient", MagicMock(return_value=fake)
            ),
        ):
            code, _, _ = _run(
                ["douyin", "check", "--profile-id", PROFILE, "--headed"],
                env={"ADSPOWER_API_KEY": KEY},
            )
        self.assertEqual(code, 0)
        self.assertEqual(fake.start_calls, [(PROFILE, False)])

    def test_registration_scope_matches_the_shared_matrix(self):
        parser = sau_cli.build_parser()
        for platform in sau_cli.PLATFORMS:
            for action in _action_names(platform):
                options = _option_strings(_subparser(parser, platform, action))
                is_managed_action = action == "check" or action.startswith("upload-")
                with self.subTest(platform=platform, action=action):
                    if platform == "bilibili" or not is_managed_action:
                        self.assertNotIn("--folder-id", options)
                        self.assertNotIn("--profile-id", options)
                    else:
                        self.assertIn("--folder-id", options)
                        self.assertIn("--profile-id", options)

    def test_login_is_rejected_with_adspower_wording_and_placeholder(self):
        platforms = [
            platform
            for platform in sau_cli.PLATFORMS
            if "login" in _action_names(platform)
        ]
        self.assertIn("douyin", platforms)
        for platform in platforms:
            with self.subTest(platform=platform):
                code, _, err = _run(
                    [platform, "login"], env={"ADSPOWER_API_KEY": KEY}
                )
                self.assertEqual(code, 1)
                self.assertIn("AdsPower 模式不支持 CLI 登录", err)
                self.assertIn("指定 Profile", err)

    def test_login_with_explicit_profile_is_an_argparse_error(self):
        with _env(ADSPOWER_API_KEY=KEY):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    sau_cli.main(["douyin", "login", "--profile-id", PROFILE])
        self.assertEqual(ctx.exception.code, 2)

    def test_bilibili_login_check_and_upload_exit_1(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = os.path.join(tmp_dir, "demo.mp4")
            with open(video, "wb") as handle:
                handle.write(b"video")
            cases = (
                ["bilibili", "login", "--account", "creator"],
                ["bilibili", "check", "--account", "creator"],
                [
                    "bilibili",
                    "upload-video",
                    "--account",
                    "creator",
                    "--file",
                    video,
                    "--title",
                    "标题",
                    "--desc",
                    "简介",
                    "--tid",
                    "1",
                ],
            )
            for argv in cases:
                with self.subTest(argv=argv):
                    code, _, err = _run(argv, env={"ADSPOWER_API_KEY": KEY})
                    self.assertEqual(code, 1)
                    self.assertIn("AdsPower", err)

    def test_local_only_actions_still_require_account_in_adspower_mode(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            result_file = os.path.join(tmp_dir, "result.json")
            with open(result_file, "w", encoding="utf-8") as handle:
                handle.write("{}")
            cases = [
                (
                    facebook_command,
                    ["facebook", "verify", "--post-url", "u", "--owner-id", "1", "--expected-text", "t"],
                ),
                (
                    facebook_command,
                    ["facebook", "delete", "--post-url", "u", "--owner-id", "1", "--expected-text", "t"],
                ),
                (
                    facebook_page_command,
                    ["facebook-page", "verify", "--page-id", "1", "--page", "Page", "--content-id", "c", "--expected-text", "t"],
                ),
                (
                    facebook_page_command,
                    ["facebook-page", "delete", "--page-id", "1", "--page", "Page", "--content-id", "c", "--expected-text", "t"],
                ),
                (
                    instagram_command,
                    ["instagram", "verify", "--post-url", "u", "--expected-text", "t"],
                ),
                (
                    instagram_command,
                    ["instagram", "delete", "--post-url", "u", "--expected-text", "t"],
                ),
                (zhihu_command, ["zhihu", "verify", "--result", result_file]),
                (xueqiu_command, ["xueqiu", "verify", "--result", result_file]),
                (dayu_command, ["dayu", "verify", "--content-id", "c"]),
            ]
            for module, argv in cases:
                with self.subTest(argv=argv):
                    resolve = MagicMock(
                        side_effect=AssertionError("cookie path must not be built")
                    )
                    with patch.object(module, "resolve_account_file", new=resolve):
                        code, _, err = _run(argv, env={"ADSPOWER_API_KEY": KEY})
                    self.assertEqual(code, 2)
                    self.assertIn("--account", err)
                    resolve.assert_not_called()

    def test_article_stays_local_and_accepts_no_browser_flags(self):
        parser = sau_cli.build_parser()
        for action in _action_names("article"):
            options = _option_strings(_subparser(parser, "article", action))
            self.assertNotIn("--profile-id", options)
            self.assertNotIn("--folder-id", options)
        code, out, _ = _run(
            ["article", "themes"], env={"ADSPOWER_API_KEY": KEY}
        )
        self.assertEqual(code, 0)
        self.assertIn("default", out)


class CheckAndExitCodeTests(unittest.TestCase):
    def _factory(self, *, logged_in=True):
        factory = MagicMock(
            return_value=_AsyncCM(SimpleNamespace(context=object()))
        )
        playwright_patch = patch.object(
            douyin_command, "async_playwright", lambda: _AsyncCM(object())
        )
        session_patch = patch.object(douyin_command, "browser_session", new=factory)
        login_patch = patch.object(
            douyin_command, "is_logged_in", new=AsyncMock(return_value=logged_in)
        )
        return factory, playwright_patch, session_patch, login_patch

    def test_check_success_prints_only_valid(self):
        factory, pw, session, login = self._factory(logged_in=True)
        with pw, session, login:
            code, out, err = _run(
                ["douyin", "check", "--profile-id", PROFILE],
                env={"ADSPOWER_API_KEY": KEY},
            )
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "valid")
        self.assertEqual(err, "")
        provider = factory.call_args.kwargs["managed"]
        self.assertEqual(provider.mode, "adspower")

    def test_check_not_logged_in_exits_10_with_adspower_wording(self):
        factory, pw, session, login = self._factory(logged_in=False)
        with pw, session, login:
            code, out, err = _run(
                ["douyin", "check", "--profile-id", PROFILE],
                env={"ADSPOWER_API_KEY": KEY},
            )
        self.assertEqual(code, 10)
        self.assertEqual(out, "")
        self.assertIn("抖音登录态无效", err)
        self.assertIn("AdsPower", err)

    def test_rate_limited_error_maps_to_11(self):
        with patch("sau_cli.dispatch", new=AsyncMock(side_effect=RateLimitedError("429"))):
            code, _, err = _run(
                ["douyin", "check", "--profile-id", PROFILE],
                env={"ADSPOWER_API_KEY": KEY},
            )
        self.assertEqual(code, 11)
        self.assertIn("429", err)

    def test_publish_result_unknown_error_maps_to_9(self):
        with patch(
            "sau_cli.dispatch",
            new=AsyncMock(side_effect=PublishResultUnknownError("publish unknown")),
        ):
            code, _, err = _run(
                ["douyin", "check", "--profile-id", PROFILE],
                env={"ADSPOWER_API_KEY": KEY},
            )
        self.assertEqual(code, 9)
        self.assertIn("publish unknown", err)

    def test_keyboard_interrupt_is_not_caught(self):
        with patch("sau_cli.dispatch", new=AsyncMock(side_effect=KeyboardInterrupt)):
            with self.assertRaises(KeyboardInterrupt):
                _run(
                    ["douyin", "check", "--profile-id", PROFILE],
                    env={"ADSPOWER_API_KEY": KEY},
                )

    def test_rate_limited_on_probe_exits_11_without_start_or_stop(self):
        fake = FakeAdspowerClient(probe_error=RateLimitedError("probe 429"))
        pw, login, client, _ = _real_seam(fake)
        with pw, login, client:
            code, _, err = _run(
                ["douyin", "check", "--profile-id", PROFILE],
                env={"ADSPOWER_API_KEY": KEY},
            )
        self.assertEqual(code, 11)
        self.assertIn("429", err)
        self.assertEqual(fake.start_calls, [])
        self.assertEqual(fake.stop_calls, [])

    def test_rate_limited_on_start_exits_11_without_stop(self):
        fake = FakeAdspowerClient(start_error=RateLimitedError("start 429"))
        pw, login, client, _ = _real_seam(fake)
        with pw, login, client:
            code, _, err = _run(
                ["douyin", "check", "--profile-id", PROFILE],
                env={"ADSPOWER_API_KEY": KEY},
            )
        self.assertEqual(code, 11)
        self.assertIn("429", err)
        self.assertEqual(fake.stop_calls, [])

    def test_start_incomplete_stops_profile_then_exits_1(self):
        fake = FakeAdspowerClient(start_error=StartIncompleteError("bad start"))
        pw, login, client, _ = _real_seam(fake)
        with pw, login, client:
            code, _, err = _run(
                ["douyin", "check", "--profile-id", PROFILE],
                env={"ADSPOWER_API_KEY": KEY},
            )
        self.assertEqual(code, 1)
        self.assertIn("bad start", err)
        self.assertEqual(fake.stop_calls, [PROFILE])

    def test_rate_limited_during_stop_keeps_success_exit_code(self):
        fake = FakeAdspowerClient(stop_error=RateLimitedError("stop 429"))
        pw, login, client, _ = _real_seam(fake)
        with pw, login, client:
            code, out, _ = _run(
                ["douyin", "check", "--profile-id", PROFILE],
                env={"ADSPOWER_API_KEY": KEY},
            )
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "valid")
        self.assertEqual(fake.stop_calls, [PROFILE])


class SecretRedactionTests(unittest.TestCase):
    def test_key_never_appears_in_outputs_or_reprs(self):
        scenarios = []

        # Missing profile (usage error).
        code, out, err = _run(
            ["douyin", "check"], env={"ADSPOWER_API_KEY": KEY}
        )
        scenarios.append((code, out + err))

        # Login rejection.
        code, out, err = _run(
            ["douyin", "login"], env={"ADSPOWER_API_KEY": KEY}
        )
        scenarios.append((code, out + err))

        # Invalid base (usage error).
        code, out, err = _run(
            ["douyin", "check", "--profile-id", PROFILE],
            env={
                "ADSPOWER_API_KEY": KEY,
                "ADSPOWER_API_BASE": "http://127.0.0.1:50325/path",
            },
        )
        scenarios.append((code, out + err))

        # Runtime failure from probe.
        fake = FakeAdspowerClient(probe_error=RuntimeError("probe boom"))
        pw, login, client, _ = _real_seam(fake)
        with pw, login, client:
            code, out, err = _run(
                ["douyin", "check", "--profile-id", PROFILE],
                env={"ADSPOWER_API_KEY": KEY},
            )
        scenarios.append((code, out + err))

        for code, output in scenarios:
            self.assertNotEqual(code, 0)
            self.assertNotIn(KEY, output)

        client = AdspowerClient(KEY, DEFAULT_BASE)
        self.assertNotIn(KEY, repr(client))
        provider = AdspowerProvider(AdspowerTarget(PROFILE), client)
        self.assertNotIn(KEY, repr(provider))


if __name__ == "__main__":
    unittest.main()
