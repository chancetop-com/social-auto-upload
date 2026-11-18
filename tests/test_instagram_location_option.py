"""Instagram 地点参数校验与候选匹配。"""
from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import sau_cli
from sau_commands import instagram as instagram_command
from uploader.meta_uploader.insgraph_uploader.controls.location import LocationControl
from uploader.meta_uploader.insgraph_uploader.main import InstagramUploader
from uploader.meta_uploader.insgraph_uploader.options import (
    InstagramPublishOptions,
    OptionMismatchError,
)
from utils.errors import UsageError


class InstagramLocationFlagTests(unittest.TestCase):
    """A 层：两个命令都注册 ``--location``，未传不动页面，空白值退出 2。"""

    def _parse(self, *args):
        return sau_cli.build_parser().parse_args(['instagram', *args])

    def test_both_upload_commands_register_location(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / 'video.mp4'
            image = Path(folder) / 'image.png'
            video.touch()
            image.touch()
            for action, media in (
                ('upload-video', ['--file', str(video)]),
                ('upload-note', ['--images', str(image)]),
            ):
                with self.subTest(action=action):
                    args = self._parse(
                        action, '--account', 'creator', *media,
                        '--title', 'caption', '--location', 'Shanghai',
                    )
                    self.assertEqual(args.location, 'Shanghai')

    def test_blank_location_exits_2_before_any_uploader(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'image.png'
            image.touch()
            request = instagram_command.InstagramUploadRequest(
                'creator', 'caption', '', [], image_files=[image],
                options=InstagramPublishOptions(location='  '),
            )
            with self.assertRaisesRegex(UsageError, '地点不能为空'):
                instagram_command.validate_instagram_publish_request(request)
            upload = AsyncMock()
            with patch.object(
                instagram_command, 'upload_instagram_content', upload
            ), patch.object(InstagramUploader, 'upload', AsyncMock()), \
                    contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    sau_cli.main([
                        'instagram', 'upload-note', '--account', 'creator',
                        '--images', str(image), '--title', 'caption',
                        '--location', ' ',
                    ]),
                    2,
                )
            upload.assert_not_awaited()

    def test_empty_location_string_also_exits_2(self):
        """``--location ""`` 不能被折叠成“未请求”，必须是静态输入错误。"""
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'image.png'
            image.touch()
            args = self._parse(
                'upload-note', '--account', 'creator',
                '--images', str(image), '--title', 'caption',
                '--location', '',
            )
            options = instagram_command._build_publish_options(args)
            self.assertIsNotNone(options)
            self.assertEqual(options.location, '')
            upload = AsyncMock()
            with patch.object(
                instagram_command, 'upload_instagram_content', upload
            ), contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    sau_cli.main([
                        'instagram', 'upload-note', '--account', 'creator',
                        '--images', str(image), '--title', 'caption',
                        '--location', '',
                    ]),
                    2,
                )
            upload.assert_not_awaited()


class InstagramLocationControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_exact_match_reports_candidates_without_clicking(self):
        control = LocationControl(page=None)
        candidates = [(0, 'Shanghai, China'), (1, 'Shanghai World Financial Center')]
        with (
            patch.object(control, '_entry', new=AsyncMock(return_value=object())),
            patch.object(control, '_type_and_wait', new=AsyncMock(return_value=candidates)),
            patch.object(control, '_click_entry', new_callable=AsyncMock) as click,
        ):
            with self.assertRaises(OptionMismatchError) as caught:
                await control.set('Shanghai')
        click.assert_not_awaited()
        for _, label in candidates:
            self.assertIn(label, str(caught.exception))
        self.assertIsNone(caught.exception.applied)


if __name__ == '__main__':
    unittest.main()
