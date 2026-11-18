# -*- coding: utf-8 -*-
"""CLI 默认关闭 debug，并在执行时解析未显式提供的 headless 配置。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import conf
import sau_cli


class CliRuntimeDefaultsTests(unittest.TestCase):
    def test_debug_defaults_off_and_flag_turns_it_on(self):
        parser = sau_cli.build_parser()
        default_args = parser.parse_args(["xiaohongshu", "check", "--account", "creator"])
        debug_args = parser.parse_args(
            ["xiaohongshu", "check", "--account", "creator", "--debug"]
        )
        self.assertFalse(default_args.debug)
        self.assertTrue(debug_args.debug)

    def test_cli_ignores_local_chrome_headless_config(self):
        parser = sau_cli.build_parser()
        for configured in (True, False):
            with self.subTest(local_chrome_headless=configured):
                with patch.object(
                    conf, "LOCAL_CHROME_HEADLESS", configured, create=True
                ):
                    args = parser.parse_args(
                        ["xiaohongshu", "check", "--account", "creator"]
                    )
                self.assertIsNone(args.headless)  # Resolve migrated platform config at execution time.


if __name__ == "__main__":
    unittest.main()
