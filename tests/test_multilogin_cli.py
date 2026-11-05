# -*- coding: utf-8 -*-
"""CLI activation, flags, usage errors and exit-code mapping (ticket 16)."""

from __future__ import annotations

import argparse
import asyncio
import io
import os
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

import sau_cli
from sau_commands import dayu as dayu_command
from sau_commands import douyin as douyin_command
from sau_commands import facebook as facebook_command
from sau_commands import facebook_page as facebook_page_command
from sau_commands import instagram as instagram_command
from sau_commands import multilogin
from sau_commands import xueqiu as xueqiu_command
from sau_commands import zhihu as zhihu_command
from utils.errors import LoginRequiredError, UsageError
from utils.multilogin import MultiloginTarget

SENTINEL_TOKEN = "SENTINEL-MLX-TOKEN-7f34d0"


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


class ActivationTests(unittest.TestCase):
    def test_unset_token_means_local_mode(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MLX_API_TOKEN", None)
            self.assertFalse(multilogin.multilogin_enabled())

    def test_empty_token_means_local_mode(self):
        with patch.dict(os.environ, {"MLX_API_TOKEN": ""}):
            self.assertFalse(multilogin.multilogin_enabled())

    def test_whitespace_token_means_local_mode(self):
        with patch.dict(os.environ, {"MLX_API_TOKEN": "   \t\n"}):
            self.assertFalse(multilogin.multilogin_enabled())

    def test_non_empty_token_means_multilogin_mode(self):
        with patch.dict(os.environ, {"MLX_API_TOKEN": SENTINEL_TOKEN}):
            self.assertTrue(multilogin.multilogin_enabled())


class ParserContractTests(unittest.TestCase):
    def test_check_and_upload_actions_accept_multilogin_flags(self):
        parser = sau_cli.build_parser()
        for platform in sau_cli.PLATFORMS:
            # Bilibili is rejected in MLX mode (no browser context), so it must
            # not advertise Profile flags.
            if platform == "bilibili":
                continue
            for action in _action_names(platform):
                if not (action == "check" or action.startswith("upload-")):
                    continue
                with self.subTest(platform=platform, action=action):
                    options = _option_strings(_subparser(parser, platform, action))
                    self.assertIn("--folder-id", options)
                    self.assertIn("--profile-id", options)

    def test_every_check_accepts_runtime_flags(self):
        parser = sau_cli.build_parser()
        for platform in sau_cli.PLATFORMS:
            if platform == "bilibili":
                continue
            if "check" not in _action_names(platform):
                continue
            with self.subTest(platform=platform):
                options = _option_strings(_subparser(parser, platform, "check"))
                self.assertIn("--headed", options)
                self.assertIn("--headless", options)

    def test_bilibili_actions_do_not_accept_multilogin_flags(self):
        parser = sau_cli.build_parser()
        for action in ("check", "upload-video"):
            with self.subTest(action=action):
                options = _option_strings(_subparser(parser, "bilibili", action))
                self.assertNotIn("--folder-id", options)
                self.assertNotIn("--profile-id", options)

    def test_login_actions_do_not_accept_multilogin_flags(self):
        parser = sau_cli.build_parser()
        for platform in sau_cli.PLATFORMS:
            if "login" not in _action_names(platform):
                continue
            with self.subTest(platform=platform):
                options = _option_strings(_subparser(parser, platform, "login"))
                self.assertNotIn("--folder-id", options)
                self.assertNotIn("--profile-id", options)

    def test_account_is_optional_everywhere(self):
        parser = sau_cli.build_parser()
        for platform in sau_cli.PLATFORMS:
            for action in _action_names(platform):
                action_parser = _subparser(parser, platform, action)
                account_action = action_parser._option_string_actions.get("--account")
                if account_action is None:
                    continue
                with self.subTest(platform=platform, action=action):
                    self.assertFalse(account_action.required)

    def test_parse_check_without_account_keeps_flags(self):
        args = sau_cli.build_parser().parse_args(
            ["douyin", "check", "--folder-id", "folder", "--profile-id", "profile"]
        )
        self.assertIsNone(args.account)
        self.assertEqual(args.folder_id, "folder")
        self.assertEqual(args.profile_id, "profile")
        self.assertTrue(args.headless)

    def test_documented_check_headed_example_parses(self):
        args = sau_cli.build_parser().parse_args(
            [
                "xiaohongshu",
                "check",
                "--folder-id",
                "folder",
                "--profile-id",
                "profile",
                "--headed",
            ]
        )
        self.assertFalse(args.headless)


class HelperTests(unittest.TestCase):
    def test_local_mode_ignores_multilogin_flags(self):
        args = Namespace(folder_id="folder", profile_id="profile", account="creator")
        with patch.dict(os.environ, {"MLX_API_TOKEN": ""}):
            self.assertIsNone(multilogin.resolve_multilogin_target(args))
            self.assertEqual(multilogin.resolve_account_label(args), "creator")
            multilogin.require_local_account(args)
            multilogin.reject_multilogin_login("douyin", args)
            multilogin.reject_multilogin_platform("bilibili", args)

    def test_mlx_missing_folder_or_profile_is_usage_error(self):
        with patch.dict(os.environ, {"MLX_API_TOKEN": SENTINEL_TOKEN}):
            for args in (
                Namespace(folder_id=None, profile_id="p", account=None),
                Namespace(folder_id="f", profile_id=None, account=None),
                Namespace(folder_id=" ", profile_id="p", account=None),
                Namespace(account=None),
            ):
                with self.subTest(args=args):
                    with self.assertRaises(UsageError):
                        multilogin.resolve_multilogin_target(args)

    def test_mlx_target_and_label(self):
        with patch.dict(os.environ, {"MLX_API_TOKEN": SENTINEL_TOKEN}):
            target = multilogin.resolve_multilogin_target(
                Namespace(folder_id="folder", profile_id="profile")
            )
            self.assertEqual(target, MultiloginTarget("folder", "profile"))
            self.assertEqual(
                multilogin.resolve_account_label(
                    Namespace(account=None, profile_id="profile")
                ),
                "profile",
            )
            self.assertEqual(
                multilogin.resolve_account_label(
                    Namespace(account="creator", profile_id="profile")
                ),
                "creator",
            )

    def test_local_missing_account_is_usage_error(self):
        with patch.dict(os.environ, {"MLX_API_TOKEN": ""}):
            with self.assertRaises(UsageError):
                multilogin.require_local_account(Namespace(account=None))
            with self.assertRaises(UsageError):
                multilogin.require_local_account(Namespace(account="  "))

    def test_mlx_missing_account_is_not_a_usage_error(self):
        with patch.dict(os.environ, {"MLX_API_TOKEN": SENTINEL_TOKEN}):
            multilogin.require_local_account(Namespace(account=None))

    def test_require_account_is_strict_even_in_mlx_mode(self):
        with patch.dict(os.environ, {"MLX_API_TOKEN": SENTINEL_TOKEN}):
            multilogin.require_account(Namespace(account="creator"))
            for account in (None, "", "   "):
                with self.subTest(account=account):
                    with self.assertRaises(UsageError):
                        multilogin.require_account(Namespace(account=account))

    def test_login_required_error_message(self):
        error = multilogin.login_required_error("抖音", "profile-1")
        self.assertIsInstance(error, LoginRequiredError)
        self.assertIn("抖音登录态无效：profile_id=profile-1", str(error))
        self.assertIn("Multilogin", str(error))

    def test_login_rejection_message_and_placeholder(self):
        with patch.dict(os.environ, {"MLX_API_TOKEN": SENTINEL_TOKEN}):
            with self.assertRaises(RuntimeError) as with_id:
                multilogin.reject_multilogin_login(
                    "douyin", Namespace(profile_id="profile-1")
                )
            self.assertIn("profile-1", str(with_id.exception))
            self.assertIn("Multilogin 模式不支持 CLI 登录", str(with_id.exception))

            with self.assertRaises(RuntimeError) as without_id:
                multilogin.reject_multilogin_login("douyin", Namespace())
            self.assertIn("指定 Profile", str(without_id.exception))

    def test_platform_rejection(self):
        with patch.dict(os.environ, {"MLX_API_TOKEN": SENTINEL_TOKEN}):
            with self.assertRaises(RuntimeError) as ctx:
                multilogin.reject_multilogin_platform("bilibili", Namespace())
            self.assertIn("bilibili", str(ctx.exception))
            self.assertIn("Multilogin", str(ctx.exception))


class UsageAndExitCodeTests(unittest.TestCase):
    def _run(self, argv, token=""):
        with patch.dict(os.environ, {"MLX_API_TOKEN": token}):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
                code = sau_cli.main(argv)
        return code, err.getvalue()

    def test_local_missing_account_exits_2(self):
        code, err = self._run(["douyin", "check"])
        self.assertEqual(code, 2)
        self.assertIn("--account", err)

    def test_local_missing_account_exits_2_for_every_login_and_check(self):
        for platform in sau_cli.PLATFORMS:
            # Ticket 25: TikTok has no local mode at all, so every action exits
            # 1 before --account is ever considered (covered by test_mlx_tiktok).
            if platform == "tiktok":
                continue
            for action in ("check", "login"):
                if action not in _action_names(platform):
                    continue
                with self.subTest(platform=platform, action=action):
                    code, _ = self._run([platform, action])
                    self.assertEqual(code, 2)

    def test_mlx_missing_folder_or_profile_exits_2(self):
        code, _ = self._run(["douyin", "check", "--account", "creator"], SENTINEL_TOKEN)
        self.assertEqual(code, 2)

    def test_mlx_missing_profile_exits_2(self):
        code, _ = self._run(
            ["douyin", "check", "--folder-id", "folder"], SENTINEL_TOKEN
        )
        self.assertEqual(code, 2)

    def test_unknown_subcommand_exits_2_via_argparse(self):
        with patch.dict(os.environ, {"MLX_API_TOKEN": ""}):
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    sau_cli.main(["not-a-platform"])
        self.assertEqual(ctx.exception.code, 2)

    def test_mlx_login_rejected_exits_1(self):
        platforms = [
            platform
            for platform in sau_cli.PLATFORMS
            if "login" in _action_names(platform)
        ]
        self.assertIn("douyin", platforms)
        for platform in platforms:
            with self.subTest(platform=platform):
                code, err = self._run([platform, "login"], SENTINEL_TOKEN)
                self.assertEqual(code, 1)
                self.assertIn("Multilogin 模式不支持 CLI 登录", err)

    def test_bilibili_in_mlx_exits_1(self):
        code, err = self._run(["bilibili", "check", "--account", "creator"], SENTINEL_TOKEN)
        self.assertEqual(code, 1)
        self.assertIn("bilibili", err)

        code, err = self._run(["bilibili", "login", "--account", "creator"], SENTINEL_TOKEN)
        self.assertEqual(code, 1)
        self.assertIn("Multilogin 模式不支持 CLI 登录", err)

    def test_local_only_actions_still_require_account_in_mlx_mode(self):
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
                    [
                        "facebook-page",
                        "verify",
                        "--page-id",
                        "1",
                        "--page",
                        "Page",
                        "--content-id",
                        "c",
                        "--expected-text",
                        "t",
                    ],
                ),
                (
                    facebook_page_command,
                    [
                        "facebook-page",
                        "delete",
                        "--page-id",
                        "1",
                        "--page",
                        "Page",
                        "--content-id",
                        "c",
                        "--expected-text",
                        "t",
                    ],
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
                        code, err = self._run(argv, SENTINEL_TOKEN)
                    self.assertEqual(code, 2)
                    self.assertIn("--account", err)
                    resolve.assert_not_called()

    def test_exit_code_mapping(self):
        cases = (
            (LoginRequiredError("login"), 10),
            (UsageError("usage"), 2),
            (RuntimeError("boom"), 1),
        )
        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                with patch.dict(os.environ, {"MLX_API_TOKEN": ""}):
                    with patch(
                        "sau_cli.dispatch", new=AsyncMock(side_effect=error)
                    ):
                        with redirect_stdout(io.StringIO()), redirect_stderr(
                            io.StringIO()
                        ):
                            code = sau_cli.main(
                                ["douyin", "check", "--account", "creator"]
                            )
                self.assertEqual(code, expected)

    def test_dispatch_normalizes_missing_multilogin_attributes(self):
        args = Namespace(platform="xiaohongshu", action="check", account="creator")
        with patch.dict(os.environ, {"MLX_API_TOKEN": ""}), patch(
            "sau_commands.xiaohongshu.check_xiaohongshu_account",
            new=AsyncMock(return_value=True),
        ):
            with redirect_stdout(io.StringIO()):
                code = asyncio.run(sau_cli.dispatch(args))
        self.assertEqual(code, 0)
        self.assertIsNone(args.folder_id)
        self.assertIsNone(args.profile_id)

    def test_token_never_appears_in_errors(self):
        scenarios = []

        with patch.dict(os.environ, {"MLX_API_TOKEN": SENTINEL_TOKEN}):
            # Usage error: missing ids.
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
                code = sau_cli.main(["douyin", "check"])
            scenarios.append((code, err.getvalue()))

            # Login rejection.
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
                code = sau_cli.main(["douyin", "login"])
            scenarios.append((code, err.getvalue()))

            # Runtime failure from the session layer.
            with patch.object(
                douyin_command,
                "async_playwright",
                side_effect=RuntimeError("boom"),
            ):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
                    code = sau_cli.main(
                        [
                            "douyin",
                            "check",
                            "--folder-id",
                            "folder",
                            "--profile-id",
                            "profile",
                        ]
                    )
            scenarios.append((code, err.getvalue()))

        for code, output in scenarios:
            self.assertNotIn(SENTINEL_TOKEN, output)
            self.assertNotEqual(code, 0)
        self.assertNotIn(SENTINEL_TOKEN, repr(MultiloginTarget("folder", "profile")))


if __name__ == "__main__":
    unittest.main()
