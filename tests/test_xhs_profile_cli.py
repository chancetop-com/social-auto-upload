"""Xiaohongshu CLI through real config, Profile and session ownership."""
import io
import os
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

import conf
import sau_cli
from sau_commands import xiaohongshu as command
from uploader.xiaohongshu_uploader import main as xhs
from tests.fakes import FakeContext, FakePlaywright
from tests.test_xhs_session import _AsyncCM, _ProbePage
from utils.local_profile import acquire_local_profile


class ProfileContext(FakeContext):
    def __init__(self):
        super().__init__()
        self.page_factory = _ProbePage
        self.created_pages = []
    async def new_page(self):
        page = self.page_factory()
        self.pages.append(page)
        self.created_pages.append(page)
        return page


class XiaohongshuProfileCliTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        for name, value in [('BASE_DIR', self.root), ('LOCAL_CHROME_PATH', ''), ('LOCAL_BROWSER', 'chrome'), ('LOCAL_CHROME_HEADLESS', True)]:
            self.stack.enter_context(patch.object(conf, name, value, create=True))
        self.stack.enter_context(patch.dict(os.environ, {'MLX_API_TOKEN': '', 'ADSPOWER_API_KEY': '', 'HUMANIZE': '0'}))
        self.pw = FakePlaywright()
        self.context = ProfileContext()
        self.pw.chromium.persistent_context = self.context
        for module in (command, xhs):
            self.stack.enter_context(patch.object(module, 'async_playwright', lambda: _AsyncCM(self.pw)))
    def cli(self, *argv):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            code = sau_cli.main(['xiaohongshu', *argv])
        return code, out.getvalue(), err.getvalue()
    def profile(self, kind='chrome'):
        with acquire_local_profile('xiaohongshu', 'creator', kind, create=True) as profile:
            return profile.path

    def test_reappearing_legacy_file_is_untouched_and_login_does_not_restart(self):
        from tests.fakes_clock import FakeClock
        self.context.page_factory = LoginPage
        with FakeClock().patch(xhs):
            code, _, err = self.cli('login', '--account', 'creator', '--headed')
            self.assertEqual(code, 0, err)
        legacy = self.root / 'cookies/xiaohongshu_creator.json'
        legacy.parent.mkdir(exist_ok=True)
        legacy.write_bytes(b'reappeared broken credentials')
        open_file = Path.open
        def deny_legacy_open(path, *args, **kwargs):
            if path == legacy:
                raise AssertionError('normal commands must never read or rewrite old credentials')
            return open_file(path, *args, **kwargs)
        with patch.object(Path, 'open', deny_legacy_open):
            with FakeClock().patch(xhs):
                code, _, err = self.cli('login', '--account', 'creator', '--headed')
                self.assertEqual(code, 0, err)
            code, _, err = self.cli('check', '--account', 'creator', '--headed')
            self.assertEqual(code, 0, err)
        self.assertEqual(legacy.read_bytes(), b'reappeared broken credentials')
        self.assertEqual(len(self.pw.chromium.persistent_calls), 3)
        self.assertFalse(self.context.storage_state_calls)

    def test_check_uses_selected_profile_and_ignores_legacy_state(self):
        self.profile()
        legacy = self.root / 'cookies/xiaohongshu_creator.json'
        legacy.parent.mkdir()
        legacy.write_text('broken JSON from another account')
        code, out, err = self.cli('check', '--account', 'creator')
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), 'valid')
        self.assertEqual(self.pw.chromium.persistent_calls, [{
            'user_data_dir': str(self.root / 'browser_profiles/xiaohongshu/creator/chrome'),
            'channel': 'chrome', 'headless': True, 'no_viewport': True}])
        self.assertTrue(self.context.closed)
        self.assertFalse(self.context.storage_state_calls)
        self.assertFalse(self.context.add_init_script_calls)
        self.assertEqual(legacy.read_text(), 'broken JSON from another account')

    def test_login_reuses_alias_profile_and_selected_browser_once_per_action(self):
        from tests.fakes_clock import FakeClock
        self.context.page_factory = LoginPage
        with FakeClock().patch(xhs):
            for flags, kind, headless in [([], 'chrome', True), (['--headed'], 'chrome', False), (['--local-browser', 'chromium'], 'chromium', True)]:
                code, out, err = self.cli('login', '--account', 'creator', *flags)
                self.assertEqual(code, 0, err)
                call = self.pw.chromium.persistent_calls[-1]
                self.assertEqual(call['channel'], kind)
                self.assertEqual(call['headless'], headless)
                self.assertTrue(call['user_data_dir'].endswith('/creator/' + kind))
        self.assertEqual(len(self.pw.chromium.persistent_calls), 3)
        self.assertFalse(self.pw.chromium.launch_calls)
        self.assertFalse(self.context.storage_state_calls)
        self.assertFalse((self.root / 'cookies').exists())
        self.assertEqual(list(self.root.rglob('*.png')), [])

    def test_login_accepts_existing_authenticated_redirect_without_a_qr_box(self):
        from tests.fakes_clock import FakeClock
        self.profile()
        # The real creator site redirects an authenticated /login navigation
        # straight to its workspace, so there is no login box to wait for.
        class AuthenticatedPage(_ProbePage):
            def locator(self, selector):
                if selector == xhs.XHS_LOGIN_BOX_SELECTOR:
                    return FakeLocator('absent login box', count=0,
                        wait_error=TimeoutError('login box is absent after authenticated redirect'))
                return super().locator(selector)
        self.context.page_factory = AuthenticatedPage
        with FakeClock().patch(xhs):
            code, _, err = self.cli('login', '--account', 'creator', '--headed')
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.pw.chromium.persistent_calls), 1)
        self.assertTrue(self.context.closed)
        self.assertEqual(list(self.root.rglob('*.png')), [])

    def test_login_without_qr_still_requires_positive_evidence_and_classifies_verification(self):
        from tests.fakes_clock import FakeClock
        for url, code, diagnostic in [
            ('https://creator.xiaohongshu.com/home', 1, '页面结构异常'),
            ('https://creator.xiaohongshu.com/website-login/captcha', 10, '验证'),
        ]:
            with self.subTest(url=url):
                self.context.page_factory = lambda: _ProbePage(final_url=url, anchor_count=0)
                with FakeClock().patch(xhs), patch.object(xhs, 'XHS_PROBE_ANCHOR_WINDOW_SECONDS', 0):
                    actual, _, err = self.cli('login', '--account', 'creator', '--headed')
                self.assertEqual(actual, code, err)
                self.assertIn(diagnostic, err)
                self.assertTrue(self.context.closed)

    def test_video_and_note_no_publish_reach_actual_arm_in_one_owned_session(self):
        from tests.fakes_clock import FakeClock
        import uploader.publish_timeout as timeout
        from utils import dom
        from tests.test_xhs_submit import _note_page
        self.profile()
        media = self.root / 'media.mp4'
        image = self.root / 'image.png'
        media.write_bytes(b'media')
        image.write_bytes(b'image')
        for action, flags, file in [('upload-video', ['--file', str(media)], media), ('upload-note', ['--images', str(image)], image)]:
            with self.subTest(action=action):
                page = _note_page()
                page._evaluate_handler = lambda expression, arg: {'since': 10_000} if 'performance.now' in str(expression) else True
                self.context.page_factory = lambda: page
                before = len(self.pw.chromium.persistent_calls)
                with FakeClock().patch(xhs, timeout, dom):
                    code, out, err = self.cli(action, '--account', 'creator', '--title', 'Title', '--headed', '--no-publish', *flags)
                self.assertEqual(code, 0, err)
                self.assertIn('素材已上传，发布前检查已通过；已停止，未点击发布按钮。', out)
                self.assertNotIn('prepared (not published)', out)
                self.assertNotIn('upload submitted:', out)
                self.assertEqual(len(self.pw.chromium.persistent_calls) - before, 1)
                self.assertFalse(self.pw.chromium.persistent_calls[-1]['headless'])
                self.assertEqual(page.locator(xhs.XHS_UPLOAD_INPUT_SELECTOR).files, [str(file)] if action == 'upload-video' else [[str(file)]])
                self.assertIn(('insert_text', 'Title'), page.keyboard.actions)
                self.assertGreater(len(page.locator('xhs-publish-btn').evaluate_calls), 0)
                self.assertEqual(page.locator('xhs-publish-btn').click_count, 0)
                self.assertEqual(page.mouse.down_count, 0)
                self.assertTrue(self.context.closed)
                self.assertFalse(self.context.storage_state_calls)

    def test_no_publish_failures_never_print_success_or_submit(self):
        from tests.fakes import FakeManagedProvider, FakeBrowser
        from tests.fakes_clock import FakeClock
        from tests.test_xhs_submit import _note_page, _PublishButton
        from tests.test_xhs_session import LOGIN_URL
        from utils import dom
        import uploader.publish_timeout as timeout
        self.profile()
        media = self.root / 'media.mp4'; media.write_bytes(b'fixture')
        image = self.root / 'image.png'; image.write_bytes(b'fixture')
        for action, flags in [('upload-video', ['--file', str(media)]), ('upload-note', ['--images', str(image)])]:
            for state, managed, expected in [('unready', False, 1), ('login', False, 10), ('login', True, 10)]:
                with self.subTest(action=action, state=state, managed=managed):
                    page = _note_page(_PublishButton(enabled=False))
                    page._evaluate_handler = lambda expression, arg: {'since': 10_000} if 'performance.now' in str(expression) else True
                    self.context.page_factory = lambda: page
                    if state == 'login':
                        navigate = page.goto
                        async def login_redirect(url, **kwargs):
                            await navigate(url, **kwargs)
                            page.url = page.main_frame.url = LOGIN_URL
                        page.goto = login_redirect
                    provider = FakeManagedProvider() if managed else None
                    if managed:
                        self.pw.chromium.queue_connect_browser(FakeBrowser([self.context]))
                    with patch.object(command, 'resolve_managed_provider', return_value=provider), FakeClock().patch(xhs, timeout, dom):
                        code, out, err = self.cli(action, '--account', 'creator', '--title', 'Title', '--no-publish', *flags)
                    self.assertEqual(code, expected, err)
                    self.assertEqual(out, '')
                    self.assertNotIn('publish_attempted=true', err)
                    self.assertEqual(page.locator('xhs-publish-btn').click_count, 0)
                    self.assertEqual(page.mouse.down_count, 0)
                    if state == 'unready':
                        self.assertGreater(len(page.locator('xhs-publish-btn').evaluate_calls), 0)
                    if managed:
                        self.assertEqual(provider.stop_calls, 1)

    def test_missing_profile_and_platform_failures_have_distinct_exits(self):
        self.assertEqual(self.cli('check', '--account', 'creator')[0], 10)
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.profile()
        from tests.test_xhs_session import LOGIN_URL, VERIFICATION_URL
        for options, expected in [({'final_url': LOGIN_URL}, 10), ({'final_url': VERIFICATION_URL}, 10), ({'status': 503}, 1), ({'goto_error': OSError('offline')}, 1)]:
            with self.subTest(options=options):
                self.context.page_factory = lambda: _ProbePage(**options)
                self.context.close_error = OSError('cleanup failure')
                code, out, err = self.cli('check', '--account', 'creator')
                self.assertEqual(code, expected, err)
                self.assertEqual(out.strip(), 'invalid')
                if options.get('final_url') == VERIFICATION_URL:
                    self.assertIn('人机验证', err)
        self.assertFalse((self.root / 'cookies').exists())

    def test_launch_failure_does_not_fallback_and_releases_profile(self):
        self.profile('chromium')
        self.pw.chromium.launch_error = OSError('missing selected browser')
        code, out, err = self.cli('check', '--account', 'creator', '--local-browser', 'chromium', '--headed')
        self.assertEqual(code, 1)
        self.assertIn('channel=chromium', err)
        self.assertEqual(len(self.pw.chromium.persistent_calls), 1)
        self.assertFalse(self.pw.chromium.launch_calls)
        with acquire_local_profile('xiaohongshu', 'creator', 'chromium') as profile:
            self.assertTrue(profile.exists)

    def test_direct_setup_and_uploader_aliases_never_read_old_filename(self):
        import asyncio
        from utils.errors import LoginRequiredError
        self.profile()
        self.assertTrue(asyncio.run(xhs.xiaohongshu_setup('/missing/xiaohongshu_creator.json', headless=False)))
        self.assertFalse(self.pw.chromium.persistent_calls[-1]['headless'])
        media = self.root / 'video.mp4'
        media.write_bytes(b'video')
        from tests.test_xhs_session import LOGIN_URL
        self.context.page_factory = lambda: _ProbePage(final_url=LOGIN_URL)
        for headless, expected in [(None, True), (False, False)]:
            app = xhs.XiaoHongShuVideo('Title', media, [], 0, '/missing/xiaohongshu_creator.json', headless=headless)
            with self.assertRaises(LoginRequiredError):
                asyncio.run(app.upload(self.pw))
            self.assertEqual(self.pw.chromium.persistent_calls[-1]['headless'], expected)
            self.assertTrue(self.context.closed)
        self.assertFalse(self.context.storage_state_calls)

    def test_business_cancellation_releases_profile_and_preserves_cancellation(self):
        import asyncio
        self.profile()
        self.context.page_factory = lambda: _ProbePage(goto_error=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            self.cli('check', '--account', 'creator')
        self.assertTrue(self.context.closed)
        with acquire_local_profile('xiaohongshu', 'creator', 'chrome') as profile:
            self.assertTrue(profile.exists)

    def test_reset_is_exact_and_requires_no_browser_installation(self):
        chrome = self.profile()
        chromium = self.profile('chromium')
        with patch.object(conf, 'LOCAL_CHROME_PATH', '/missing/binary'):
            code, out, err = self.cli('reset-profile', '--account', 'creator', '--browser-kind', 'chrome')
        self.assertEqual(code, 0, err)
        self.assertFalse(chrome.exists())
        self.assertTrue(chromium.exists())
        self.assertFalse(self.pw.chromium.persistent_calls)

    def test_publish_outcomes_survive_close_failure_without_resubmit(self):
        from tests.fakes_clock import FakeClock
        from tests.test_xhs_submit import _note_page
        import uploader.publish_timeout as timeout
        from utils import dom
        self.profile()
        image = self.root / 'image.png'
        image.write_bytes(b'image')
        self.context.close_error = OSError('close failed')
        for outcome, expected in [('success', 0), ('unknown', 9), ('login', 10), ('verification', 10)]:
            page = _note_page()
            page._evaluate_handler = lambda expression, arg: {'since': 10_000} if 'performance.now' in str(expression) else True
            button = page.locator('xhs-publish-btn')
            async def publish(**kwargs):
                button.click_count += 1
                if outcome != 'unknown':
                    page.url = 'https://creator.xiaohongshu.com/' + {'success': 'publish/success', 'login': 'login', 'verification': 'website-login/captcha'}[outcome]
                    page.main_frame.url = page.url
            button.click = publish
            self.context.page_factory = lambda: page
            with FakeClock().patch(xhs, timeout, dom):
                code, out, err = self.cli('upload-note', '--account', 'creator', '--title', 'Title', '--images', str(image))
            self.assertEqual(code, expected, err)
            if expected == 0:
                self.assertEqual(out, 'Xiaohongshu note upload submitted: 1 images\n')
            self.assertEqual(button.click_count, 1)
            if expected == 10: self.assertIn('publish_attempted=true', err)

    def test_managed_boundaries_ignore_local_config_and_preserve_ownership(self):
        from tests.fakes import FakeManagedProvider, FakeBrowser
        from loguru import logger
        for mode, env in [('mlx', {'MLX_API_TOKEN': 'test'}), ('adspower', {'ADSPOWER_API_KEY': 'test'})]:
            provider = FakeManagedProvider(mode=mode)
            context = ProfileContext()
            browser = FakeBrowser([context])
            self.pw.chromium.queue_connect_browser(browser)
            logs = io.StringIO()
            sink = logger.add(logs, format='{message}')
            try:
                with patch.object(command, 'resolve_managed_provider', return_value=provider), patch.dict(os.environ, env), patch.object(conf, 'LOCAL_CHROME_PATH', []):
                    code, out, err = self.cli('check', '--profile-id', 'profile', '--local-browser', 'invalid')
            finally:
                logger.remove(sink)
            self.assertEqual(code, 0, err)
            self.assertEqual(provider.start_calls, [True])
            self.assertEqual(provider.stop_calls, 1)
            self.assertFalse(context.closed)
            self.assertFalse(context.storage_state_calls)
            self.assertFalse(context.forbidden_calls)
            self.assertNotIn('local-browser', logs.getvalue())
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.assertFalse((self.root / 'browser_profiles').exists())

    def test_login_callback_failure_cleans_qr_and_releases_owned_profile(self):
        import asyncio
        self.context.page_factory = LoginPage
        def callback(info):
            self.assertTrue(Path(info['image_path']).exists())
            raise ValueError('QR delivery failed')
        with self.assertRaisesRegex(ValueError, 'QR delivery failed'):
            asyncio.run(xhs.xiaohongshu_setup(account_name='creator', handle=True, qrcode_callback=callback))
        self.assertTrue(self.context.closed)
        self.assertFalse(list(self.root.rglob('*.png')))
        with acquire_local_profile('xiaohongshu', 'creator', 'chrome') as profile:
            self.assertTrue(profile.exists)

    def test_custom_executable_overrides_invalid_channel_by_actual_product_kind(self):
        import plistlib
        import sys
        self.profile()
        executable = self.root / 'Custom.app/Contents/MacOS/Chrome'
        executable.parent.mkdir(parents=True)
        executable.write_text('#!/bin/sh\nexit 0\n')
        executable.chmod(0o755)
        with (executable.parent.parent / 'Info.plist').open('wb') as target:
            plistlib.dump({'CFBundleExecutable': 'Chrome', 'CFBundleName': 'Google Chrome', 'CFBundleIdentifier': 'com.google.Chrome', 'CFBundleShortVersionString': '999.1'}, target)
        with patch.object(sys, 'platform', 'darwin'), patch.object(conf, 'LOCAL_CHROME_PATH', str(executable)), patch.object(conf, 'LOCAL_BROWSER', 'invalid'):
            code, out, err = self.cli('check', '--account', 'creator', '--local-browser', 'also-invalid', '--headless')
        self.assertEqual(code, 0, err)
        call = self.pw.chromium.persistent_calls[0]
        self.assertEqual(call['executable_path'], str(executable))
        self.assertNotIn('channel', call)
        self.assertTrue(call['user_data_dir'].endswith('/creator/chrome'))

    def test_managed_video_and_note_preserve_ignored_options_and_no_publish(self):
        from tests.fakes import FakeManagedProvider, FakeBrowser
        from tests.test_xhs_submit import _note_page
        from tests.fakes_clock import FakeClock
        from loguru import logger
        import uploader.publish_timeout as timeout
        from utils import dom
        media = self.root / 'video.mp4'
        media.write_bytes(b'video')
        image = self.root / 'image.png'
        image.write_bytes(b'image')
        for action, flags, mode in [('upload-video', ['--file', str(media)], 'mlx'), ('upload-note', ['--images', str(image)], 'adspower')]:
            provider = FakeManagedProvider(mode=mode)
            page = _note_page()
            page._evaluate_handler = lambda expression, arg: {'since': 10_000} if 'performance.now' in str(expression) else True
            context = ProfileContext()
            context.page_factory = lambda: page
            browser = FakeBrowser([context])
            self.pw.chromium.queue_connect_browser(browser)
            logs = io.StringIO()
            sink = logger.add(logs, format='{message}')
            try:
                with patch.object(command, 'resolve_managed_provider', return_value=provider), patch.object(conf, 'LOCAL_CHROME_PATH', []), patch.dict(os.environ, {'MLX_API_TOKEN': 'token'} if mode == 'mlx' else {'ADSPOWER_API_KEY': 'key'}), FakeClock().patch(xhs, timeout, dom):
                    code, out, err = self.cli(action, '--account', 'ignored', '--profile-id', 'profile', '--local-browser', 'ignored', '--headed', '--title', 'Title', '--no-publish', *flags)
            finally:
                logger.remove(sink)
            self.assertEqual(code, 0, err)
            self.assertIn('素材已上传，发布前检查已通过；已停止，未点击发布按钮。', out)
            self.assertNotIn('upload submitted:', out)
            self.assertEqual(provider.start_calls, [False])
            self.assertEqual(provider.stop_calls, 1)
            self.assertFalse(context.closed)
            self.assertFalse(context.forbidden_calls)
            self.assertEqual(page.locator('xhs-publish-btn').click_count, 0)
            for key in ('account', 'context_kwargs', 'init_script', 'launch_kwargs'):
                self.assertIn(key, logs.getvalue())
            self.assertNotIn('local-browser', logs.getvalue())
        self.assertFalse((self.root / 'browser_profiles').exists())
        self.assertFalse((self.root / 'cookies').exists())

    def test_qr_cleanup_failure_does_not_overwrite_success_or_callback_error(self):
        import asyncio
        from tests.fakes_clock import FakeClock
        self.context.page_factory = LoginPage
        def callback(info):
            raise ValueError('QR delivery failed')
        with patch.object(Path, 'unlink', side_effect=OSError('cleanup denied')), FakeClock().patch(xhs):
            self.assertTrue(asyncio.run(xhs.xiaohongshu_setup(account_name='creator', handle=True)))
            with self.assertRaisesRegex(ValueError, 'QR delivery failed'):
                asyncio.run(xhs.xiaohongshu_setup(account_name='creator', handle=True, qrcode_callback=callback))
        self.assertTrue(self.context.closed)

    def test_local_probe_cleanup_uses_bounded_context_owner(self):
        import asyncio
        self.profile()
        page = _ProbePage()
        async def hanging_close():
            await asyncio.sleep(10)
        page.close = hanging_close
        self.context.page_factory = lambda: page
        args = sau_cli.build_parser().parse_args(['xiaohongshu', 'check', '--account', 'creator'])
        async def check():
            return await asyncio.wait_for(sau_cli.dispatch(args), timeout=0.05)
        self.assertEqual(asyncio.run(check()), 0)
        self.assertTrue(self.context.closed)


from tests.fakes_xhs_dom import FakeLocator, RecordingPage
from tests.test_xhs_submit import BUTTON_FACTS

class LoginPage(RecordingPage):
    def __init__(self):
        super().__init__()
        self.scanned = False
        self.qr = FakeLocator('QR', computed_style=BUTTON_FACTS,
            attributes={'src': 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR4nGP4DwABAQEAsTj2FAAAAABJRU5ErkJggg=='})
        self.box = FakeLocator('login', children={"div:has-text('扫一扫')": FakeLocator('scan')})
    def locator(self, selector):
        if selector == 'img.css-1lhmg90':
            self.scanned = True
            self.url = 'https://creator.xiaohongshu.com/home'
            self.main_frame.url = self.url
            return self.qr
        if selector == xhs.XHS_LOGIN_BOX_SELECTOR:
            if self.scanned or '/publish/' in self.url: return FakeLocator('absent', count=0, children=self.box._children)
            return self.box
        if selector in xhs.XHS_LOGIN_POSITIVE_SELECTORS: return FakeLocator('upload')
        return FakeLocator('absent', count=0)
