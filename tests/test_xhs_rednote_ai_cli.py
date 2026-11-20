# -*- coding: utf-8 -*-
"""All four XHS/Rednote commands report the AI declaration request and readback.

Ticket 15: the existing success summary stays, and one extra clear line records
the requested content type, the page's final value, and whether the run could
continue.
"""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

import sau_cli
from sau_commands import rednote as rednote_command
from sau_commands import xiaohongshu as xhs_command

AI_LABEL = "笔记含AI合成内容"
FAILURE = (
    "内容类型声明失败：请求=ai（笔记含AI合成内容），"
    "终值=未读到，原因=未找到内容类型声明入口；尚未点击发布。"
)


class AiDeclarationCliReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.media = self.tmp / "media.png"
        self.media.write_bytes(b"media")

    def argv(self, platform, action, *extra):
        if action == "upload-video":
            media = ["--file", str(self.media)]
        else:
            media = ["--images", str(self.media)]
        return [
            platform,
            action,
            "--account",
            "creator",
            "--title",
            "标题",
            *media,
            "--no-publish",
            *extra,
        ]

    def command(self, platform, action):
        module = xhs_command if platform == "xiaohongshu" else rednote_command
        name = (
            f"upload_{'xiaohongshu' if platform == 'xiaohongshu' else 'rednote'}"
            f"_{'video' if action == 'upload-video' else 'note'}"
        )
        return module, name

    def run_cli(self, platform, action, *, extra=(), upload=None):
        module, name = self.command(platform, action)
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.object(module, name, new=upload or AsyncMock()),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = sau_cli.main(self.argv(platform, action, *extra))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_omitted_content_type_is_reported_as_not_requested(self):
        for platform in ("xiaohongshu", "rednote"):
            for action in ("upload-video", "upload-note"):
                with self.subTest(platform=platform, action=action):
                    code, out, err = self.run_cli(platform, action)
                    self.assertEqual(code, 0, err)
                    self.assertIn("AI 声明：未请求（保留页面当前值）", out)
                    self.assertIn("素材已上传，发布前检查已通过", out)

    def test_explicit_ai_reports_request_and_final_value(self):
        async def upload(request, **kwargs):
            request.declaration_report = {
                "requested": "ai",
                "requested_label": AI_LABEL,
                "observed": AI_LABEL,
                "status": "set",
            }

        for platform in ("xiaohongshu", "rednote"):
            for action in ("upload-video", "upload-note"):
                with self.subTest(platform=platform, action=action):
                    code, out, err = self.run_cli(
                        platform, action, extra=("--content-type", "ai"), upload=upload
                    )
                    self.assertEqual(code, 0, err)
                    self.assertIn("AI 声明：请求=ai（笔记含AI合成内容）", out)
                    self.assertIn("终值=笔记含AI合成内容", out)
                    self.assertIn("结果=已设置", out)
                    self.assertIn("素材已上传，发布前检查已通过", out)

    def test_declaration_failure_exits_1_without_success_summary(self):
        async def upload(request, **kwargs):
            raise RuntimeError(FAILURE)

        for platform in ("xiaohongshu", "rednote"):
            for action in ("upload-video", "upload-note"):
                with self.subTest(platform=platform, action=action):
                    code, out, err = self.run_cli(
                        platform, action, extra=("--content-type", "ai"), upload=upload
                    )
                    self.assertEqual(code, 1)
                    self.assertEqual(out, "")
                    self.assertIn("请求=ai", err)
                    self.assertIn("终值=未读到", err)
                    self.assertIn("未找到内容类型声明入口", err)
                    self.assertIn("尚未点击发布", err)
                    self.assertNotIn("素材已上传", out)

    def test_conflicting_content_types_exit_2_before_upload(self):
        for platform in ("xiaohongshu", "rednote"):
            for action in ("upload-video", "upload-note"):
                with self.subTest(platform=platform, action=action):
                    module, name = self.command(platform, action)
                    upload = AsyncMock()
                    stderr = io.StringIO()
                    argv = self.argv(
                        platform,
                        action,
                        "--content-type",
                        "ai",
                        "--content-type",
                        "marketing",
                    )
                    with (
                        patch.object(module, name, new=upload),
                        redirect_stderr(stderr),
                        self.assertRaises(SystemExit) as ctx,
                    ):
                        sau_cli.main(argv)
                    self.assertEqual(ctx.exception.code, 2)
                    self.assertIn("--content-type", stderr.getvalue())
                    upload.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
