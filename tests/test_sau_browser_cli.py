import sau_commands.xiaohongshu
import asyncio
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import sau_cli
from utils.errors import UsageError


class BrowserCliParserTests(unittest.TestCase):
    def test_xiaohongshu_upload_video_defaults_to_headed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            parser = sau_cli.build_parser()
            args = parser.parse_args(
                [
                    "xiaohongshu",
                    "upload-video",
                    "--account",
                    "creator",
                    "--file",
                    str(video_path),
                    "--title",
                    "视频标题",
                ]
            )

        self.assertFalse(args.headless)

    def test_xiaohongshu_upload_video_parses_declaration_flags(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")
            parser = sau_cli.build_parser()
            args = parser.parse_args(
                [
                    "xiaohongshu",
                    "upload-video",
                    "--account",
                    "creator",
                    "--file",
                    str(video_path),
                    "--title",
                    "标题",
                    "--original",
                    "--content-type",
                    "marketing",
                ]
            )
        self.assertTrue(args.original)
        self.assertEqual(args.content_type, "marketing")
        self.assertIsNone(args.repost_source)

    def test_xiaohongshu_declarations_reject_original_and_repost(self):
        args = Namespace(
            original=True,
            content_type="repost",
            repost_source="某媒体",
        )
        with self.assertRaises(UsageError):
            sau_commands.xiaohongshu._validate_declarations(args)

    def test_xiaohongshu_repost_requires_media_name(self):
        args = Namespace(original=None, content_type="repost", repost_source=" ")
        with self.assertRaises(UsageError):
            sau_commands.xiaohongshu._validate_declarations(args)

    def test_xiaohongshu_self_shot_requires_location_and_date(self):
        args = Namespace(
            original=None,
            content_type="self-shot",
            repost_source=None,
            shoot_location="北京",
            shoot_date=None,
        )
        with self.assertRaises(UsageError):
            sau_commands.xiaohongshu._validate_declarations(args)

    def test_xiaohongshu_self_shot_rejects_bad_date(self):
        args = Namespace(
            original=None,
            content_type="self-shot",
            repost_source=None,
            shoot_location="北京",
            shoot_date="2026/11/09",
        )
        with self.assertRaises(UsageError):
            sau_commands.xiaohongshu._validate_declarations(args)

    def test_xiaohongshu_shoot_fields_only_for_self_shot(self):
        args = Namespace(
            original=None,
            content_type="ai",
            repost_source=None,
            shoot_location="北京",
            shoot_date="2026-11-09",
        )
        with self.assertRaises(UsageError):
            sau_commands.xiaohongshu._validate_declarations(args)


class BrowserCliDispatchTests(unittest.TestCase):

    def test_dispatch_xiaohongshu_upload_video_uses_headed_request(self):
        args = Namespace(
            platform="xiaohongshu",
            action="upload-video",
            account="creator",
            file=Path("demo.mp4"),
            title="视频标题",
            desc="视频简介",
            tags="测试,视频",
            schedule=0,
            thumbnail=None,
            debug=False,
            headless=False,
        )
        with patch("sau_commands.xiaohongshu.upload_xiaohongshu_video", new=AsyncMock()) as mock_upload:
            asyncio.run(sau_cli.dispatch(args))

        request = mock_upload.await_args.args[0]
        self.assertEqual(request.title, "视频标题")
        self.assertEqual(request.description, "视频简介")
        self.assertFalse(request.headless)

    def test_dispatch_xiaohongshu_upload_note_uses_headless_request(self):
        args = Namespace(
            platform="xiaohongshu",
            action="upload-note",
            account="creator",
            images=[Path("1.png"), Path("2.png")],
            title="图文标题",
            note="图文正文",
            tags="测试,图文",
            schedule=0,
            debug=False,
            headless=True,
        )
        with patch("sau_commands.xiaohongshu.upload_xiaohongshu_note", new=AsyncMock()) as mock_upload:
            asyncio.run(sau_cli.dispatch(args))

        request = mock_upload.await_args.args[0]
        self.assertEqual(request.title, "图文标题")
        self.assertEqual(request.note, "图文正文")
        self.assertTrue(request.headless)
        self.assertEqual(len(request.image_files), 2)

    def test_dispatch_xiaohongshu_forwards_declaration_fields(self):
        args = Namespace(
            platform="xiaohongshu",
            action="upload-note",
            account="creator",
            images=[Path("1.png")],
            title="图文标题",
            note="图文正文",
            tags="",
            schedule=0,
            debug=False,
            headless=True,
            original=None,
            content_type="repost",
            repost_source="某媒体",
        )
        with patch(
            "sau_commands.xiaohongshu.upload_xiaohongshu_note", new=AsyncMock()
        ) as mock_upload:
            asyncio.run(sau_cli.dispatch(args))

        request = mock_upload.await_args.args[0]
        self.assertIsNone(request.original_declaration)
        self.assertEqual(request.content_type, "repost")
        self.assertEqual(request.repost_source, "某媒体")


if __name__ == "__main__":
    unittest.main()
