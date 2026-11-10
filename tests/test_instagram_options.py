"""Instagram 发布选项的纯逻辑与 fake 控制件回归（A/B 层，零浏览器）。"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import sau_cli
from sau_commands import instagram as instagram_command
from uploader.meta_uploader.insgraph_uploader.main import InstagramUploader
from uploader.meta_uploader.insgraph_uploader.options import (
    ACCOUNT_INELIGIBLE,
    APPLY_ORDER,
    DEFAULT_OFF,
    ENTRY_MISSING,
    MISMATCH,
    NOT_REQUESTED,
    OPTION_KEYS,
    SET,
    UNSUPPORTED,
    InstagramPublishOptions,
    OptionMismatchError,
    alt_texts_match,
    empty_option_record,
    location_matches,
    normalize_text,
    option_failures,
    option_status,
    validate_publish_options,
)
from utils.errors import UsageError


class _FakeControl:
    """最小控制件替身：只实现 resolve/read/set，按顺序返回预置回读值。"""

    def __init__(self, read_values, *, presence='present', name='control', order=None):
        self._values = list(read_values)
        self.presence = presence
        self.name = name
        # 共享的调用顺序日志，用于验证 §4.2 的应用顺序。
        self.order = order if order is not None else []
        self.interactions = []

    async def resolve(self):
        self.interactions.append('resolve')
        self.order.append(self.name)
        return self.presence

    async def read(self):
        self.interactions.append('read')
        if not self._values:
            return None
        return self._values.pop(0) if len(self._values) > 1 else self._values[0]

    async def set(self, requested):
        self.interactions.append(('set', requested))


class _ExplodingControl:
    """任何交互都失败：证明未请求项连读取都不做。"""

    async def resolve(self):
        raise AssertionError('未请求的选项不应被 resolve')

    async def read(self):
        raise AssertionError('未请求的选项不应被 read')

    async def set(self, requested):
        raise AssertionError('未请求的选项不应被 set')


class InstagramOptionLogicTests(unittest.TestCase):
    """A3/A4/A6：记录骨架、三态保留与 5 个状态映射。"""

    def test_record_has_all_four_keys_and_not_requested_defaults(self):
        record = empty_option_record(None)
        self.assertEqual(tuple(record), OPTION_KEYS)
        self.assertEqual(OPTION_KEYS, ('location', 'alt_text', 'comments', 'ai_generated'))
        self.assertEqual(
            APPLY_ORDER, ('alt_text', 'location', 'ai_generated', 'comments')
        )
        for key in OPTION_KEYS:
            self.assertEqual(
                record[key],
                {'requested': None, 'applied': None, 'status': NOT_REQUESTED},
            )

    def test_requested_values_keep_three_state(self):
        record = empty_option_record(
            InstagramPublishOptions(
                location='Shanghai',
                alt_texts=('第一张', '第二张'),
                comments=False,
                ai_generated=True,
            )
        )
        self.assertEqual(record['location']['requested'], 'Shanghai')
        self.assertEqual(record['alt_text']['requested'], ['第一张', '第二张'])
        # False 不能被压缩成 None，True 也不能被当成默认。
        self.assertIs(record['comments']['requested'], False)
        self.assertIs(record['ai_generated']['requested'], True)
        for key in OPTION_KEYS:
            self.assertEqual(record[key]['status'], NOT_REQUESTED)
            self.assertNotIn('reason', record[key])

    def test_normalize_and_value_matching(self):
        self.assertEqual(normalize_text('  Shang  Hai '), 'shang hai')
        self.assertEqual(normalize_text('İstanbul'), 'i̇stanbul')
        self.assertTrue(location_matches('Shang  Hai', 'shang hai'))
        self.assertFalse(location_matches('Shanghai', 'Beijing'))
        self.assertFalse(location_matches('Shanghai', None))
        self.assertTrue(alt_texts_match(('Dog on mat', 'Cat'), ['dog  on mat', 'cat']))
        self.assertFalse(alt_texts_match(('a', 'b'), ['a']))
        self.assertFalse(alt_texts_match(('a',), None))
        self.assertFalse(alt_texts_match(('a',), 'a'))

    def test_status_mapping_covers_all_five_states(self):
        cases = (
            # requested, applied, kind, presence, acted -> (status, reason)
            (None, None, 'value', 'present', False, (NOT_REQUESTED, None)),
            (None, None, 'toggle', 'missing', False, (NOT_REQUESTED, None)),
            ('Shanghai', None, 'value', 'missing', False, (UNSUPPORTED, ENTRY_MISSING)),
            ('Shanghai', None, 'value', 'ineligible', False, (UNSUPPORTED, ACCOUNT_INELIGIBLE)),
            (True, None, 'toggle', 'missing', False, (UNSUPPORTED, ENTRY_MISSING)),
            (True, None, 'toggle', 'ineligible', False, (UNSUPPORTED, ACCOUNT_INELIGIBLE)),
            (False, None, 'toggle', 'missing', False, (DEFAULT_OFF, ENTRY_MISSING)),
            (False, None, 'toggle', 'ineligible', False, (DEFAULT_OFF, ACCOUNT_INELIGIBLE)),
            # 入口存在但尚未满足时以 mismatch 作为“需要动作”的信号，动作后重新判定。
            (True, False, 'toggle', 'present', False, (MISMATCH, None)),
            (True, True, 'toggle', 'present', False, (SET, None)),
            (False, False, 'toggle', 'present', False, (DEFAULT_OFF, None)),
            (False, False, 'toggle', 'present', True, (SET, None)),
            (True, True, 'toggle', 'present', True, (SET, None)),
            (True, False, 'toggle', 'present', True, (MISMATCH, None)),
            ('Shanghai', 'shanghai', 'value', 'present', False, (SET, None)),
            ('Shanghai', 'Beijing', 'value', 'present', False, (MISMATCH, None)),
            (('a', 'b'), ['A ', 'b'], 'value', 'present', False, (SET, None)),
            (('a', 'b'), ['a'], 'value', 'present', False, (MISMATCH, None)),
            (('a', 'b'), None, 'value', 'present', False, (MISMATCH, None)),
        )
        seen = set()
        for requested, applied, kind, presence, acted, expected in cases:
            with self.subTest(
                requested=requested, applied=applied, kind=kind,
                presence=presence, acted=acted,
            ):
                status, reason = option_status(
                    requested, applied, kind=kind, presence=presence, acted=acted
                )
                self.assertEqual((status, reason), expected)
                seen.add(status)
        self.assertEqual(
            seen, {NOT_REQUESTED, SET, DEFAULT_OFF, UNSUPPORTED, MISMATCH}
        )

    def test_failures_are_human_readable_and_ordered(self):
        record = empty_option_record(
            InstagramPublishOptions(
                location='Shanghai', comments=False, ai_generated=True
            )
        )
        record['location'].update(status=UNSUPPORTED, reason=ENTRY_MISSING)
        record['comments'].update(status=DEFAULT_OFF, reason=ACCOUNT_INELIGIBLE)
        record['ai_generated'].update(status=MISMATCH)
        self.assertEqual(
            option_failures(record),
            ['location=unsupported(entry_missing)', 'ai_generated=mismatch'],
        )


class InstagramOptionValidationTests(unittest.TestCase):
    """A5：§3.3 静态校验全部映射为 UsageError（退出码 2）。"""

    def test_caption_limit(self):
        validate_publish_options(None, image_count=1, caption='x' * 2200)
        with self.assertRaises(UsageError) as ctx:
            validate_publish_options(None, image_count=1, caption='x' * 2201)
        self.assertIn('2200', str(ctx.exception))

    def test_media_selection_errors(self):
        for kwargs in (
            {'image_count': 1, 'has_video': True},
            {'image_count': 0, 'has_video': False},
            {'image_count': 1, 'has_video': False, 'has_thumbnail': True},
        ):
            with self.subTest(**kwargs), self.assertRaises(UsageError):
                validate_publish_options(None, caption='caption', **kwargs)
        # 视频 + 封面、单图、轮播都是合法组合。
        validate_publish_options(
            None, image_count=0, has_video=True, has_thumbnail=True, caption='c'
        )
        validate_publish_options(None, image_count=1, caption='c')
        validate_publish_options(None, image_count=3, caption='c')

    def test_alt_text_count_and_length(self):
        with self.assertRaises(UsageError) as ctx:
            validate_publish_options(
                InstagramPublishOptions(alt_texts=('a',)), image_count=2, caption='c'
            )
        self.assertIn('1', str(ctx.exception))
        self.assertIn('2', str(ctx.exception))
        with self.assertRaises(UsageError) as ctx:
            validate_publish_options(
                InstagramPublishOptions(alt_texts=('a', 'x' * 1001)),
                image_count=2, caption='c',
            )
        self.assertIn('2', str(ctx.exception))
        self.assertIn('1001', str(ctx.exception))
        with self.assertRaises(UsageError):
            validate_publish_options(
                InstagramPublishOptions(alt_texts=('',)), image_count=1, caption='c'
            )
        validate_publish_options(
            InstagramPublishOptions(alt_texts=('a', 'b')), image_count=2, caption='c'
        )

    def test_location_must_not_be_blank(self):
        for blank in ('', '   ', '\n\t'):
            with self.subTest(blank=blank), self.assertRaises(UsageError) as ctx:
                validate_publish_options(
                    InstagramPublishOptions(location=blank), image_count=1, caption='c'
                )
            self.assertIn('地点', str(ctx.exception))
        validate_publish_options(
            InstagramPublishOptions(location=' Shanghai '), image_count=1, caption='c'
        )


class InstagramCommandRequestTests(unittest.TestCase):
    """CLI 接线：三态透传、请求校验先于浏览器 / 托管 Profile。"""

    def test_build_publish_options_returns_none_when_everything_is_none(self):
        args = SimpleNamespace(
            location=None, alt_text=None, no_comments=False, ai_generated=None
        )
        self.assertIsNone(instagram_command._build_publish_options(args))

    def test_build_publish_options_preserves_tri_state(self):
        args = SimpleNamespace(
            location='Shanghai', alt_text=['第一张'], no_comments=True,
            ai_generated=False,
        )
        self.assertEqual(
            instagram_command._build_publish_options(args),
            InstagramPublishOptions(
                location='Shanghai', alt_texts=('第一张',), comments=False,
                ai_generated=False,
            ),
        )
        # 显式 False 与未传 None 必须可区分。
        args = SimpleNamespace(ai_generated=False)
        self.assertEqual(
            instagram_command._build_publish_options(args),
            InstagramPublishOptions(ai_generated=False),
        )

    def test_request_forwards_options_to_uploader(self):
        options = InstagramPublishOptions(comments=False)
        request = instagram_command.InstagramUploadRequest(
            'creator', 'caption', '', [], image_files=[Path('image.png')],
            options=options,
        )
        with patch.object(instagram_command, 'InstagramUploader') as constructor:
            constructor.return_value.upload = AsyncMock(return_value={})
            asyncio.run(instagram_command.upload_instagram_content(request))
        self.assertIs(constructor.call_args.kwargs['options'], options)

    def test_validate_request_uses_shared_caption_rendering(self):
        request = instagram_command.InstagramUploadRequest(
            'creator', 'a' * 2000, 'b' * 300, ['tag'],
            image_files=[Path('image.png')],
        )
        with self.assertRaises(UsageError):
            instagram_command.validate_instagram_publish_request(request)

    def test_oversize_caption_exits_2_before_any_uploader(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'image.png'
            image.touch()
            upload = AsyncMock()
            with patch.object(InstagramUploader, 'upload', upload), \
                    contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    sau_cli.main([
                        'instagram', 'upload-note', '--account', 'creator',
                        '--images', str(image), '--title', 'x' * 2201,
                    ]),
                    2,
                )
            upload.assert_not_awaited()


class InstagramOptionPipelineTests(unittest.TestCase):
    """B 层：通过注入 fake 控制件验证通用选项管线。"""

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

    def test_not_requested_options_touch_no_control(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(None, folder=folder)
            result_file = app.result_file
            controls = {key: _ExplodingControl() for key in OPTION_KEYS}
            self._apply(app, controls)
            self.assertFalse(result_file.exists())
            for key in OPTION_KEYS:
                self.assertEqual(
                    app.result['options'][key],
                    {'requested': None, 'applied': None, 'status': NOT_REQUESTED},
                )

    def test_only_requested_options_are_touched(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(comments=False), folder=folder)
            comments = _FakeControl([False])
            controls = {
                'location': _ExplodingControl(),
                'alt_text': _ExplodingControl(),
                'ai_generated': _ExplodingControl(),
                'comments': comments,
            }
            self._apply(app, controls)
            self.assertEqual(comments.interactions, ['resolve', 'read'])
            record = app.result['options']['comments']
            self.assertEqual(record['status'], DEFAULT_OFF)
            self.assertNotIn('reason', record)

    def test_apply_order_follows_spec(self):
        with tempfile.TemporaryDirectory() as folder:
            order = []
            app = self._app(
                InstagramPublishOptions(
                    location='Shanghai', alt_texts=('a',), comments=False,
                    ai_generated=False,
                ),
                folder=folder,
            )
            controls = {
                'location': _FakeControl(['Shanghai'], name='location', order=order),
                'alt_text': _FakeControl([['a']], name='alt_text', order=order),
                'comments': _FakeControl([False], name='comments', order=order),
                'ai_generated': _FakeControl([False], name='ai_generated', order=order),
            }
            self._apply(app, controls)
            self.assertEqual(tuple(order), APPLY_ORDER)
            for key in OPTION_KEYS:
                self.assertEqual(app.result['options'][key]['status'], SET if key in {
                    'location', 'alt_text'
                } else DEFAULT_OFF)

    def test_missing_entry_is_unsupported_and_blocks_publish(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(
                InstagramPublishOptions(location='Shanghai'), folder=folder
            )
            controls = {'location': _FakeControl([], presence='missing')}
            with self.assertRaisesRegex(
                RuntimeError, r'location=unsupported\(entry_missing\)'
            ):
                self._apply(app, controls)
            record = app.result['options']['location']
            self.assertEqual(record['status'], UNSUPPORTED)
            self.assertEqual(record['reason'], ENTRY_MISSING)
            self.assertIsNone(record['applied'])
            # 其余未请求项保持 not_requested，且结果文件同样保留四项。
            self.assertEqual(
                app.result['options']['comments']['status'], NOT_REQUESTED
            )
            saved = json.loads(Path(app.result_file).read_text(encoding='utf-8'))
            self.assertEqual(set(saved['options']), set(OPTION_KEYS))

    def test_toggle_missing_with_off_request_is_default_off(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(comments=False), folder=folder)
            self._apply(app, {'comments': _FakeControl([], presence='missing')})
            record = app.result['options']['comments']
            self.assertEqual(record['status'], DEFAULT_OFF)
            self.assertEqual(record['reason'], ENTRY_MISSING)
            self.assertIsNone(record['applied'])
            self.assertEqual(app.result['options']['ai_generated']['status'], NOT_REQUESTED)

    def test_toggle_ineligible_but_satisfied_is_default_off(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(comments=False), folder=folder)
            control = _FakeControl([], presence='ineligible')
            self._apply(app, {'comments': control})
            record = app.result['options']['comments']
            self.assertEqual(record['status'], DEFAULT_OFF)
            self.assertEqual(record['reason'], ACCOUNT_INELIGIBLE)
            self.assertEqual(control.interactions, ['resolve'])

    def test_set_then_matching_readback_records_set(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(ai_generated=True), folder=folder)
            control = _FakeControl([False, True])
            self._apply(app, {'ai_generated': control})
            self.assertEqual(
                control.interactions, ['resolve', 'read', ('set', True), 'read']
            )
            self.assertEqual(
                app.result['options']['ai_generated'],
                {'requested': True, 'applied': True, 'status': SET},
            )

    def test_set_then_mismatched_readback_raises(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(ai_generated=True), folder=folder)
            with self.assertRaisesRegex(RuntimeError, 'ai_generated=mismatch'):
                self._apply(app, {'ai_generated': _FakeControl([False, False])})
            self.assertEqual(
                app.result['options']['ai_generated'],
                {'requested': True, 'applied': False, 'status': MISMATCH},
            )

    def test_control_declared_mismatch_keeps_applied_value_and_detail(self):
        """控件判定请求无法表达时，保留它读到的实际值并把文案并入聚合错误。"""
        class _PartialControl(_FakeControl):
            async def set(self, requested):
                raise OptionMismatchError(
                    '替代文字输入框 1 个，图片 2 张', applied=['第一张']
                )

        with tempfile.TemporaryDirectory() as folder:
            app = self._app(
                InstagramPublishOptions(alt_texts=('第一张', '第二张'), comments=False),
                folder=folder,
                image_count=2,
            )
            comments = _FakeControl([False])
            with self.assertRaises(RuntimeError) as ctx:
                self._apply(
                    app, {'alt_text': _PartialControl([['第一张']]), 'comments': comments}
                )
            message = str(ctx.exception)
            self.assertIn('alt_text=mismatch', message)
            self.assertIn('替代文字输入框 1 个', message)
            self.assertEqual(
                app.result['options']['alt_text'],
                {'requested': ['第一张', '第二张'], 'applied': ['第一张'], 'status': MISMATCH},
            )
            # 已声明失败也不能阻止后续选项。
            self.assertEqual(comments.interactions, ['resolve', 'read'])

    def test_multiple_failures_are_aggregated_in_one_error(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(
                InstagramPublishOptions(location='Shanghai', comments=True),
                folder=folder,
            )
            controls = {
                'location': _FakeControl([], presence='missing'),
                'comments': _FakeControl([False, False]),
            }
            with self.assertRaises(RuntimeError) as ctx:
                self._apply(app, controls)
            message = str(ctx.exception)
            self.assertIn('location=unsupported(entry_missing)', message)
            self.assertIn('comments=mismatch', message)

    def test_unexpected_control_error_records_mismatch_and_continues(self):
        class _BrokenControl(_FakeControl):
            async def set(self, requested):
                raise RuntimeError('页面控件点击失败')

        with tempfile.TemporaryDirectory() as folder:
            app = self._app(
                InstagramPublishOptions(location='Shanghai', comments=False),
                folder=folder,
            )
            comments = _FakeControl([False])
            with self.assertRaises(RuntimeError) as ctx:
                self._apply(
                    app, {'location': _BrokenControl([]), 'comments': comments}
                )
            message = str(ctx.exception)
            self.assertIn('页面控件点击失败', message)
            self.assertEqual(app.result['options']['location']['status'], MISMATCH)
            # 单项失败不阻止后续项继续尝试。
            self.assertEqual(comments.interactions, ['resolve', 'read'])

    def test_failure_capture_keeps_options(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(InstagramPublishOptions(location='Shanghai'), folder=folder)
            page = AsyncMock()
            page.content = AsyncMock(return_value='<html></html>')
            asyncio.run(app._capture_failure(page, RuntimeError('boom')))
            saved = json.loads(Path(app.result_file).read_text(encoding='utf-8'))
            self.assertEqual(set(saved['options']), set(OPTION_KEYS))
            self.assertEqual(saved['stage'], 'validation')


if __name__ == '__main__':
    unittest.main()
