"""Ticket 26: ``--tags`` is retired from every media publish command.

The old flag must disappear from the parser (help included) and stop old
scripts at argument parsing time, before any browser work or uploader call.
"""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
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
        for platform, action in COMMANDS:
            with self.subTest(platform=platform, action=action):
                with redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as ctx:
                    sau_cli.main([platform, action, "--help"])
                self.assertEqual(ctx.exception.code, 0)
                help_text = out.getvalue()
                self.assertIn("--file" if action == "upload-video" else "--images", help_text)
                self.assertNotIn("--tags", help_text)

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
                self.assertIn("unrecognized arguments: --tags", stderr.getvalue())
                dispatch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
