"""Instagram 替代文字（alt text）的 A/B 层回归：CLI 静态校验与 fake 控制件。

A 层零浏览器：``--alt-text`` 只在 ``upload-note`` 注册、可重复、条数与长度校验
全部在启动浏览器前以退出码 2 失败（spec §3.1、§3.3）。
B 层通过注入 fake 控制件驱动 ``_apply_options``，验证顺序、回读比较与失败分类。
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import sau_cli
from sau_commands import instagram as instagram_command
from uploader.meta_uploader.insgraph_uploader.controls.alt_text import AltTextControl
from uploader.meta_uploader.insgraph_uploader.main import InstagramUploader
from uploader.meta_uploader.insgraph_uploader.options import (
    ENTRY_MISSING,
    MISMATCH,
    SET,
    UNSUPPORTED,
    InstagramPublishOptions,
    OptionMismatchError,
    validate_publish_options,
)
from utils.errors import UsageError


class InstagramAltTextParserTests(unittest.TestCase):
    """A 层：flag 注册范围、可重复性、未传为 None、条数与长度静态校验。"""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.images = []
        for index in range(2):
            image = self.folder / f'{index}.png'
            image.touch()
            self.images.append(image)
        self.video = self.folder / 'video.mp4'
        self.video.touch()

    def _parse(self, *argv):
        return sau_cli.build_parser().parse_args(['instagram', *argv])

    def _note_args(self, *images, alt_texts=(), title='caption'):
        argv = ['upload-note', '--account', 'creator', '--title', title,
                '--images', *[str(image) for image in images]]
        for text in alt_texts:
            argv.extend(['--alt-text', text])
        return argv

    def test_alt_text_is_repeatable_on_upload_note(self):
        args = self._parse(
            *self._note_args(*self.images, alt_texts=('第一张图的描述', '第二张图的描述'))
        )
        self.assertEqual(args.alt_text, ['第一张图的描述', '第二张图的描述'])

    def test_upload_video_does_not_expose_alt_text(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            self._parse(
                'upload-video', '--account', 'creator', '--file', str(self.video),
                '--title', 'caption', '--alt-text', '不该出现',
            )
        self.assertEqual(ctx.exception.code, 2)
        # 视频命令即使不传该参数也能正常解析，证明只是未注册而非全局禁用。
        args = self._parse(
            'upload-video', '--account', 'creator', '--file', str(self.video),
            '--title', 'caption',
        )
        self.assertIsNone(getattr(args, 'alt_text', None))

    def test_absent_alt_text_keeps_legacy_options_path(self):
        args = self._parse(*self._note_args(*self.images, title='only caption'))
        self.assertIsNone(args.alt_text)
        self.assertIsNone(instagram_command._build_publish_options(args))

    def test_valid_counts_pass_validation_through_cli(self):
        from unittest.mock import AsyncMock, patch

        cases = (
            (self.images[:1], ('单图描述',)),
            (self.images[:2], ('第一张图的描述', '第二张图的描述')),
        )
        for images, alt_texts in cases:
            with self.subTest(alt_texts=alt_texts):
                upload = AsyncMock(return_value={'status': 'published'})
                with patch.object(InstagramUploader, 'upload', upload), \
                        contextlib.redirect_stdout(io.StringIO()):
                    code = sau_cli.main(
                        ['instagram', *self._note_args(*images, alt_texts=alt_texts)]
                    )
                # 条数合法时必须进入发布流程，而不是被静态校验挡住。
                self.assertEqual(code, 0)
                upload.assert_awaited_once()

    def test_invalid_counts_fail_with_exit_2_before_browser(self):
        cases = (
            ('数量不符', self.images, ('只有一条',)),
            ('空串', self.images[:1], ('',)),
            ('超长', self.images[:1], ('x' * 1001,)),
        )
        for label, images, alt_texts in cases:
            with self.subTest(label=label):
                from unittest.mock import AsyncMock, patch

                upload = AsyncMock(return_value={'status': 'published'})
                with patch.object(InstagramUploader, 'upload', upload), \
                        contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(io.StringIO()):
                    code = sau_cli.main(
                        ['instagram', *self._note_args(*images, alt_texts=alt_texts)]
                    )
                self.assertEqual(code, 2)
                upload.assert_not_awaited()


class _FakeAltTextControl:
    """最小替代文字控制件：按预置序列返回回读值，并记录 set 的请求顺序。"""

    def __init__(self, reads=(), *, presence='present'):
        self._reads = list(reads)
        self.presence = presence
        self.calls = []
        self.sets = []

    async def resolve(self):
        self.calls.append('resolve')
        return self.presence

    async def read(self):
        self.calls.append('read')
        if not self._reads:
            return None
        return self._reads.pop(0) if len(self._reads) > 1 else self._reads[0]

    async def set(self, requested):
        self.calls.append('set')
        self.sets.append(list(requested))


    def test_whitespace_only_alt_text_exits_2(self):
        """ticket 14：去空白后长度为 0 同样非法，不能把纯空白填进页面。"""
        with self.assertRaises(UsageError):
            validate_publish_options(
                InstagramPublishOptions(alt_texts=('   ',)),
                image_count=1,
                caption='caption',
            )
        with self.assertRaises(UsageError):
            validate_publish_options(
                InstagramPublishOptions(alt_texts=('ok', '  ')),
                image_count=2,
                caption='caption',
            )


class InstagramAltTextPipelineTests(unittest.TestCase):
    """B 层：fake 控制件经 ``_apply_options`` 覆盖 spec §7.2 B9。"""

    def _app(self, options, *, folder, image_count=1):
        images = [str(Path(folder) / f'{index}.png') for index in range(image_count)]
        return InstagramUploader(
            'unused.json', title='caption', image_files=images, options=options,
            result_file=Path(folder) / 'result.json',
        )

    def _apply(self, app, controls):
        return asyncio.run(
            app._apply_options(
                page=None, budget=app.start_publish_budget(), controls=controls
            )
        )

    def test_single_image_one_alt_text_is_set(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(alt_texts=('单图描述',)), folder=folder)
            control = _FakeAltTextControl([[], ['单图描述']])
            self._apply(app, {'alt_text': control})
            self.assertEqual(control.sets, [['单图描述']])
            self.assertEqual(
                app.result['options']['alt_text'],
                {'requested': ['单图描述'], 'applied': ['单图描述'], 'status': SET},
            )

    def test_carousel_keeps_images_order(self):
        with tempfile.TemporaryDirectory() as folder:
            requested = ('第一张图的描述', '第二张图的描述')
            app = self._app(
                InstagramPublishOptions(alt_texts=requested), folder=folder, image_count=2
            )
            control = _FakeAltTextControl([[], list(requested)])
            self._apply(app, {'alt_text': control})
            # 传给 set 的顺序必须与 --images 顺序一致，不能重排或串行化。
            self.assertEqual(control.sets, [list(requested)])
            self.assertEqual(app.result['options']['alt_text']['applied'], list(requested))
            self.assertEqual(app.result['options']['alt_text']['status'], SET)

    def test_reordered_readback_is_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            requested = ('第一张图的描述', '第二张图的描述')
            app = self._app(
                InstagramPublishOptions(alt_texts=requested), folder=folder, image_count=2
            )
            control = _FakeAltTextControl([[], list(reversed(requested))])
            with self.assertRaisesRegex(RuntimeError, 'alt_text=mismatch'):
                self._apply(app, {'alt_text': control})
            self.assertEqual(
                app.result['options']['alt_text'],
                {
                    'requested': list(requested),
                    'applied': list(reversed(requested)),
                    'status': MISMATCH,
                },
            )

    def test_partial_input_count_records_observed_values(self):
        class _PartialControl(_FakeAltTextControl):
            async def set(self, requested):
                raise OptionMismatchError(
                    'Instagram Alt text 输入框 1 个，图片 2 张', applied=['第一张图的描述']
                )

        with tempfile.TemporaryDirectory() as folder:
            requested = ('第一张图的描述', '第二张图的描述')
            app = self._app(
                InstagramPublishOptions(alt_texts=requested), folder=folder, image_count=2
            )
            with self.assertRaises(RuntimeError) as ctx:
                self._apply(app, {'alt_text': _PartialControl([['第一张图的描述']])})
            self.assertIn('输入框 1 个', str(ctx.exception))
            self.assertEqual(
                app.result['options']['alt_text'],
                {
                    'requested': list(requested),
                    'applied': ['第一张图的描述'],
                    'status': MISMATCH,
                },
            )

    def test_zero_inputs_is_unsupported_entry_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(
                InstagramPublishOptions(alt_texts=('单图描述',)), folder=folder
            )
            # 0 个输入框在真实控件里由 resolve() 归为 missing（spec §5.2）。
            control = _FakeAltTextControl([], presence='missing')
            with self.assertRaisesRegex(
                RuntimeError, r'alt_text=unsupported\(entry_missing\)'
            ):
                self._apply(app, {'alt_text': control})
            self.assertEqual(control.calls, ['resolve'])
            self.assertEqual(
                app.result['options']['alt_text'],
                {'requested': ['单图描述'], 'applied': None, 'status': UNSUPPORTED,
                 'reason': ENTRY_MISSING},
            )


class _FakeInput:
    """``Locator.nth(...)`` 的最小替身：只关心值，不需要真实 DOM。"""

    def __init__(self, value=''):
        self.value = value
        self.fills = []

    async def fill(self, value):
        self.fills.append(value)
        self.value = value

    async def input_value(self):
        return self.value


class _FakeInputs:
    def __init__(self, inputs):
        self.inputs = inputs

    async def count(self):
        return len(self.inputs)

    def nth(self, index):
        return self.inputs[index]


class _StubAltTextControl(AltTextControl):
    """把模态框交互替换成内存替身，直接验证真实控件的数量与顺序决策。"""

    def __init__(self, inputs, *, image_count, close_error=None):
        super().__init__(page=None, image_count=image_count)
        self.inputs = _FakeInputs(inputs)
        self.close_error = close_error
        self.opens = 0
        self.closes = 0

    async def _open_modal(self):
        self.opens += 1
        return object(), True

    async def _input_locator(self, modal):
        return self.inputs

    async def _close_modal(self, modal, *, applied=None):
        self.closes += 1
        if self.close_error is not None:
            raise self.close_error


class AltTextControlUnitTests(unittest.TestCase):
    """真实控件的分支：0 个、1..N-1 个、N 个与关闭失败。"""

    def test_fills_every_input_in_order_without_truncation(self):
        inputs = [_FakeInput(), _FakeInput()]
        control = _StubAltTextControl(inputs, image_count=2)
        long_text = '长' * 1000
        asyncio.run(control.set(['第一张图的描述', long_text]))
        self.assertEqual([item.value for item in inputs], ['第一张图的描述', long_text])
        self.assertEqual(control.closes, 1)

    def test_no_inputs_declares_zero_count_mismatch(self):
        control = _StubAltTextControl([], image_count=2)
        with self.assertRaises(OptionMismatchError) as ctx:
            asyncio.run(control.set(['第一张图的描述', '第二张图的描述']))
        self.assertEqual(ctx.exception.applied, [])
        self.assertIn('0', str(ctx.exception))
        # 已打开过模态框，失败后尽力关闭，避免遮挡后续选项。
        self.assertEqual(control.closes, 1)

    def test_partial_inputs_do_not_fill_and_report_existing_values(self):
        inputs = [_FakeInput('旧的第一张')]
        control = _StubAltTextControl(inputs, image_count=2)
        with self.assertRaises(OptionMismatchError) as ctx:
            asyncio.run(control.set(['第一张图的描述', '第二张图的描述']))
        self.assertEqual(ctx.exception.applied, ['旧的第一张'])
        self.assertIn('1', str(ctx.exception))
        self.assertIn('2', str(ctx.exception))
        # 数量不符时绝不填写，避免张冠李戴。
        self.assertEqual(inputs[0].fills, [])

    def test_missing_close_affordance_is_mismatch(self):
        close_error = OptionMismatchError('未找到关闭按钮', applied=['第一张图的描述'])
        control = _StubAltTextControl(
            [_FakeInput(), _FakeInput()], image_count=2, close_error=close_error
        )
        with self.assertRaisesRegex(OptionMismatchError, '未找到关闭按钮'):
            asyncio.run(control.set(['第一张图的描述', '第二张图的描述']))

    def test_read_always_reopens_and_closes(self):
        inputs = [_FakeInput('一'), _FakeInput('二')]
        control = _StubAltTextControl(inputs, image_count=2)
        self.assertEqual(asyncio.run(control.read()), ['一', '二'])
        self.assertEqual((control.opens, control.closes), (1, 1))


if __name__ == '__main__':
    unittest.main()
