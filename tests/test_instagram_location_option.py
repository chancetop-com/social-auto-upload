"""Instagram 地点选项的 A/B 层回归（零浏览器）。

A 层：两个上传命令都注册 ``--location``、未传保持 legacy、空白值在启动浏览器
前退出 2。B 层：通过注入 fake 地点控件验证通用选项管线的精确匹配、候选失败、
同名取第一个、入口缺失/不合格与回读不一致的记录。
真实 DOM（输入 → 联想 → 选中 → 回读）在 ``tests/test_instagram_uploader.py``。
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import sau_cli
from sau_commands import instagram as instagram_command
from uploader.meta_uploader.insgraph_uploader.main import InstagramUploader
from uploader.meta_uploader.insgraph_uploader.options import (
    ACCOUNT_INELIGIBLE,
    ENTRY_MISSING,
    MISMATCH,
    SET,
    UNSUPPORTED,
    InstagramPublishOptions,
    OptionMismatchError,
    normalize_text,
)
from utils.errors import UsageError


class _FakeLocationControl:
    """按候选列表模拟 Instagram 地点联想；只点规范化精确相等的第一个候选。"""

    def __init__(self, candidates, *, presence='present', readback=None):
        self.candidates = list(candidates)
        self.presence = presence
        # 预置回读值用于模拟“页面把选中值改成了别的东西”。
        self.readback = readback
        self.set_calls = []
        self.read_calls = []
        self.clicked = []
        self.clicked_indices = []
        self._selected = None

    async def resolve(self):
        return self.presence

    async def read(self):
        self.read_calls.append(True)
        if self.readback is not None:
            return self.readback
        return self._selected

    async def set(self, requested):
        self.set_calls.append(requested)
        wanted = normalize_text(requested)
        for index, label in enumerate(self.candidates):
            if normalize_text(label) == wanted:
                self.clicked.append(label)
                self.clicked_indices.append(index)
                self._selected = label
                return
        observed = '、'.join(f'「{label}」' for label in self.candidates[:10])
        raise OptionMismatchError(
            f'Instagram 地点没有精确匹配：请求「{requested}」；观察到的候选：'
            f'{observed or "（未出现任何候选）"}',
            applied=None,
        )


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

    def test_absent_location_keeps_legacy_options(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'image.png'
            image.touch()
            args = self._parse(
                'upload-note', '--account', 'creator',
                '--images', str(image), '--title', 'caption',
            )
        self.assertIsNone(args.location)
        self.assertIsNone(instagram_command._build_publish_options(args))

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


class InstagramLocationPipelineTests(unittest.TestCase):
    """B 层：注入 fake 地点控件，验证管线的记录与失败语义（spec §5.2、§7.2）。"""

    def _app(self, location, *, folder):
        image = Path(folder) / 'image.png'
        image.touch()
        return InstagramUploader(
            'unused.json', title='caption', image_files=[str(image)],
            options=InstagramPublishOptions(location=location),
            result_file=Path(folder) / 'result.json',
        )

    def _apply(self, app, control):
        return asyncio.run(
            app._apply_options(
                page=None,
                budget=app.start_publish_budget(),
                controls={'location': control},
            )
        )

    def test_exact_match_is_case_and_whitespace_insensitive(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app('  SHANG  hai ', folder=folder)
            control = _FakeLocationControl(
                ['Shanghai, China', 'Hangzhou', 'Shang hai']
            )
            self._apply(app, control)
            self.assertEqual(control.set_calls, ['  SHANG  hai '])
            self.assertEqual(control.clicked, ['Shang hai'])
            self.assertEqual(
                app.result['options']['location'],
                {'requested': '  SHANG  hai ', 'applied': 'Shang hai', 'status': SET},
            )

    def test_no_exact_match_lists_candidates_and_never_clicks(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app('Shanghai', folder=folder)
            control = _FakeLocationControl(
                ['Shanghai, China', 'Shanghai World Financial Center']
            )
            with self.assertRaises(RuntimeError) as ctx:
                self._apply(app, control)
            message = str(ctx.exception)
            self.assertIn('location=mismatch', message)
            self.assertIn('Shanghai, China', message)
            self.assertIn('Shanghai World Financial Center', message)
            self.assertEqual(control.clicked, [])
            self.assertEqual(
                app.result['options']['location'],
                {'requested': 'Shanghai', 'applied': None, 'status': MISMATCH},
            )

    def test_duplicate_candidates_take_the_first_without_ambiguity(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app('shanghai', folder=folder)
            control = _FakeLocationControl(['Shanghai', 'Shanghai'])
            self._apply(app, control)
            # 同名候选只点第一个，且只调用一次 set，不额外报歧义。
            self.assertEqual(control.set_calls, ['shanghai'])
            self.assertEqual(control.clicked, ['Shanghai'])
            self.assertEqual(control.clicked_indices, [0])
            self.assertEqual(app.result['options']['location']['status'], SET)

    def test_missing_entry_is_unsupported_entry_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app('Shanghai', folder=folder)
            control = _FakeLocationControl([], presence='missing')
            with self.assertRaisesRegex(
                RuntimeError, r'location=unsupported\(entry_missing\)'
            ):
                self._apply(app, control)
            record = app.result['options']['location']
            self.assertEqual(record['status'], UNSUPPORTED)
            self.assertEqual(record['reason'], ENTRY_MISSING)
            # 请求值 + 不可用：applied 必须为 null，且不读取/不点击页面。
            self.assertIsNone(record['applied'])
            self.assertEqual(control.read_calls, [])
            self.assertEqual(control.set_calls, [])

    def test_ineligible_entry_is_unsupported_account_ineligible(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app('Shanghai', folder=folder)
            control = _FakeLocationControl([], presence='ineligible')
            with self.assertRaisesRegex(
                RuntimeError, r'location=unsupported\(account_ineligible\)'
            ):
                self._apply(app, control)
            record = app.result['options']['location']
            self.assertEqual(record['status'], UNSUPPORTED)
            self.assertEqual(record['reason'], ACCOUNT_INELIGIBLE)
            # 请求值 + 不可用：applied 必须为 null，且不读取/不点击页面。
            self.assertIsNone(record['applied'])
            self.assertEqual(control.read_calls, [])
            self.assertEqual(control.set_calls, [])

    def test_readback_differing_from_clicked_candidate_is_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app('Shanghai', folder=folder)
            control = _FakeLocationControl(['Shanghai'], readback='Beijing')
            with self.assertRaisesRegex(RuntimeError, 'location=mismatch'):
                self._apply(app, control)
            self.assertEqual(control.clicked, ['Shanghai'])
            self.assertEqual(
                app.result['options']['location'],
                {'requested': 'Shanghai', 'applied': 'Beijing', 'status': MISMATCH},
            )


if __name__ == '__main__':
    unittest.main()
