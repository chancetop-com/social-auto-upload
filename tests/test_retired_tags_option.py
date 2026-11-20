"""Ticket 26: ``--tags`` is retired from every media publish command.

The old flag must disappear from the parser (help included) and stop old
scripts at argument parsing time, before any browser work or uploader call.
"""

from __future__ import annotations

import argparse
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import sau_cli


COMMANDS = (
    ("xiaohongshu", "upload-video"),
    ("xiaohongshu", "upload-note"),
    ("rednote", "upload-video"),
    ("rednote", "upload-note"),
    ("tiktok", "upload-video"),
    ("tiktok", "upload-note"),
    ("instagram", "upload-video"),
    ("instagram", "upload-note"),
    ("facebook", "upload-video"),
    ("facebook", "upload-note"),
    ("facebook-page", "upload-video"),
    ("facebook-page", "upload-note"),
    ("youtube", "upload-video"),
)


def _subparser(parser: argparse.ArgumentParser, platform: str, action: str):
    for item in parser._actions:
        if isinstance(item, argparse._SubParsersAction) and platform in item.choices:
            platform_parser = item.choices[platform]
            for nested in platform_parser._actions:
                if isinstance(nested, argparse._SubParsersAction):
                    return nested.choices[action]
    raise AssertionError(f"parser not found: {platform}/{action}")


def _option_strings(parser: argparse.ArgumentParser) -> set[str]:
    return set(parser._option_string_actions)


class RetiredTagsParserTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.video = self.root / "demo.mp4"
        self.video.write_bytes(b"video")
        self.image = self.root / "demo.png"
        self.image.write_bytes(b"image")

    def _argv(self, platform: str, action: str) -> list[str]:
        media = (
            ["--file", str(self.video)]
            if action == "upload-video"
            else ["--images", str(self.image)]
        )
        return [platform, action, *media, "--title", "标题"]

    def test_help_no_longer_lists_tags(self):
        parser = sau_cli.build_parser()
        for platform, action in COMMANDS:
            with self.subTest(platform=platform, action=action):
                command = _subparser(parser, platform, action)
                self.assertNotIn("--tags", _option_strings(command))
                self.assertNotIn("--tags", command.format_help())

    def test_old_flag_exits_2_before_any_dispatch(self):
        for platform, action in COMMANDS:
            with self.subTest(platform=platform, action=action):
                with (
                    patch("sau_cli.dispatch") as dispatch,
                    redirect_stderr(io.StringIO()) as stderr,
                ):
                    with self.assertRaises(SystemExit) as ctx:
                        sau_cli.main(
                            [*self._argv(platform, action), "--tags", "a,b"]
                        )
                self.assertEqual(ctx.exception.code, 2)
                self.assertIn("--tags", stderr.getvalue())
                dispatch.assert_not_called()

    def test_inline_topics_need_no_old_flag(self):
        parser = sau_cli.build_parser()
        for platform, action in COMMANDS:
            with self.subTest(platform=platform, action=action):
                argv = self._argv(platform, action)
                if platform == "tiktok" and action == "upload-video":
                    text_flag = "--title"
                else:
                    text_flag = "--desc" if action == "upload-video" else "--note"
                argv += [text_flag, "今天喝了 #咖啡，配上 #栗子蛋糕。"]
                args = parser.parse_args(argv)
                self.assertEqual(args.action, action)


if __name__ == "__main__":
    unittest.main()
