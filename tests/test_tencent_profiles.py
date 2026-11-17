"""Tencent CLI through real configuration/Profile ownership and browser boundaries."""
import asyncio
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import conf
import sau_cli
from sau_commands import tencent as command
from uploader.tencent_uploader import main as uploader
from tests.fakes import FakeContext, FakePage, FakePlaywright
from tests.fakes_xhs_dom import RecordingLocator, RecordingKeyboard
from utils.local_profile import acquire_local_profile

class PlaywrightCM:
    def __init__(self, playwright): self.playwright = playwright
    async def __aenter__(self): return self.playwright
    async def __aexit__(self, *_): pass

class ChannelsPage(FakePage):
    def __init__(self, *, url=None, status=200, error=None, positive=True):
        super().__init__()
        self.target_url, self.status, self.error = url, status, error
        self.positive = positive
        self.frames = []
    async def goto(self, url, **kwargs):
        await super().goto(url, **kwargs)
        self.url = self.target_url or url
        if self.error: raise self.error
        return SimpleNamespace(status=self.status)
    async def wait_for_timeout(self, _): pass
    def locator(self, selector, **kwargs):
        return RecordingLocator(selector, count=int(self.positive and selector == 'button:has-text("发表")'))
    async def close(self):
        raise AssertionError('The persistent context owns local operation pages')

class UploadPage(ChannelsPage):
    def __init__(self):
        super().__init__()
        self.keyboard = RecordingKeyboard()
        self.frames = [self]
        self.selectors = {selector: RecordingLocator(selector) for selector in (
            'button:has-text("发表")', 'button.weui-desktop-btn', 'input[type="file"]',
            'div.input-editor', 'div.form-btns button:has-text("发表"):visible',
            'input[placeholder="填写短标题有机会获得更多流量"]')}
        async def enabled(): return False
        self.selectors['div.form-btns button:has-text("发表"):visible'].is_disabled = enabled
        self.submit = RecordingLocator('submit')
        async def submit(**kwargs):
            self.submit.click_count += 1
            self.url = uploader.TENCENT_MANAGE_URL
        self.submit.click = submit
        async def entry(**kwargs): self.url = uploader.TENCENT_UPLOAD_URL
        self.selectors['button.weui-desktop-btn'].click = entry
    def locator(self, selector, **kwargs):
        return self.selectors.get(selector, RecordingLocator(selector, count=0))
    def get_by_text(self, text, **kwargs): return RecordingLocator(text, count=0)
    def get_by_role(self, role, **kwargs): return self.submit
    async def wait_for_url(self, url, **kwargs):
        if 'login.html' in url: raise TimeoutError('not a login page')
    async def wait_for_load_state(self, *_, **__): pass

class ChannelsContext(FakeContext):
    def __init__(self):
        super().__init__()
        self.next_page = ChannelsPage()
    async def new_page(self):
        self.pages.append(self.next_page)
        return self.next_page

class TencentProfilesTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.playwright = FakePlaywright()
        async def forbid_launch(**_): raise AssertionError('Must use persistent Profile')
        self.playwright.chromium.launch = forbid_launch
        self.context = ChannelsContext()
        self.playwright.chromium.persistent_context = self.context
        for key, value in {'BASE_DIR': self.root, 'LOCAL_CHROME_PATH': '', 'LOCAL_CHROME_HEADLESS': False, 'LOCAL_BROWSER': 'chrome'}.items():
            self.stack.enter_context(patch.object(conf, key, value, create=True))
        self.stack.enter_context(patch.dict(os.environ, {'MLX_API_TOKEN': '', 'ADSPOWER_API_KEY': '', 'HUMANIZE': '0'}))
        for module in (command, uploader):
            self.stack.enter_context(patch.object(module, 'async_playwright', lambda: PlaywrightCM(self.playwright)))
        self.video = self.root / 'video.mp4'
        self.video.write_bytes(b'fixture')
    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = sau_cli.main(['tencent', *args])
        return code, out.getvalue(), err.getvalue()
    def profile(self, kind='chrome'):
        with acquire_local_profile('tencent', 'Creator', kind, create=True) as profile:
            return profile.path
    def test_login_and_check_reuse_one_profile_per_action_without_legacy_json(self):
        cookies = self.root / 'cookies'
        cookies.mkdir()
        legacy = cookies / 'tencent_Creator.json'
        legacy.write_text('invalid old JSON')
        result = self.cli('login', '--account', 'Creator')
        self.assertEqual(result[0], 0, result)
        self.context.next_page = ChannelsPage(url=uploader.TENCENT_UPLOAD_URL + '?account=changed')
        self.assertEqual(self.cli('check', '--account', 'Creator')[0], 0)
        calls = self.playwright.chromium.persistent_calls
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], {'user_data_dir': str(self.root / 'browser_profiles/tencent/Creator/chrome'), 'channel': 'chrome', 'headless': False, 'no_viewport': True})
        self.assertEqual(calls[0], calls[1])
        self.assertTrue(self.context.closed)
        self.assertEqual(self.context.browser.close_calls, 0)
        self.assertFalse(self.context.storage_state_calls)
        self.assertFalse(self.context.add_init_script_calls)
        self.assertEqual(legacy.read_text(), 'invalid old JSON')

    def test_check_distinguishes_missing_expired_verification_and_probe_failures(self):
        result = self.cli('check', '--account', 'Creator')
        self.assertEqual(result[0], 10, result)
        self.assertFalse(self.playwright.chromium.persistent_calls)
        self.profile()
        for url, status, positive, expected in [
            (uploader.TENCENT_UPLOAD_URL, 200, False, 1),
            (uploader.TENCENT_UPLOAD_URL, 403, True, 1),
            (uploader.TENCENT_UPLOAD_URL, 503, True, 1),
            ('https://channels.weixin.qq.com/login.html', 200, False, 10),
            ('https://channels.weixin.qq.com/captcha', 200, False, 10),
        ]:
            with self.subTest(url=url, status=status):
                self.context.next_page = ChannelsPage(url=url, status=status, positive=positive)
                result = self.cli('check', '--account', 'Creator')
                self.assertEqual(result[0], expected, result)
                if 'captcha' in url: self.assertIn('verification', result[2])
        self.context.next_page = ChannelsPage(error=TimeoutError('network timeout'))
        self.assertEqual(self.cli('check', '--account', 'Creator')[0], 1)
        self.context.next_page = ChannelsPage(positive=False)
        self.context.next_page.frames = [SimpleNamespace(url='https://open.weixin.qq.com/connect/qrconnect')]
        self.assertEqual(self.cli('check', '--account', 'Creator')[0], 10)

    def test_upload_uses_one_profile_for_preflight_and_video_with_options(self):
        self.profile('chromium')
        page = UploadPage()
        self.context.next_page = page
        result = self.cli('upload-video', '--account', 'Creator', '--file', str(self.video),
                          '--title', 'My video title', '--desc', 'Description', '--tags', 'one,two',
                          '--short-title', 'Short title', '--local-browser', 'chromium', '--headless')
        self.assertEqual(result[0], 0, result)
        self.assertEqual(page.submit.click_count, 1)
        self.assertEqual(page.selectors['input[type="file"]'].files, [str(self.video)])
        self.assertIn(('insert_text', 'Description'), page.keyboard.actions)
        self.assertIn(('insert_text', '#one'), page.keyboard.actions)
        self.assertIn(('insert_text', 'Shorttitle'), page.keyboard.actions)
        calls = self.playwright.chromium.persistent_calls
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['channel'], 'chromium')
        self.assertTrue(calls[0]['headless'])
        self.assertTrue(calls[0]['no_viewport'])
        self.assertFalse(self.context.storage_state_calls)
        self.assertFalse(self.context.add_init_script_calls)

    def test_submit_login_or_verification_preserves_stage_and_is_not_success(self):
        self.profile()
        for url in ('https://channels.weixin.qq.com/login.html', 'https://channels.weixin.qq.com/captcha'):
            for failed_click in (False, True):
                with self.subTest(url=url, failed_click=failed_click):
                    page = UploadPage()
                    async def submit(**_):
                        page.submit.click_count += 1
                        page.url = url
                        if failed_click: raise TimeoutError('click may have reached server')
                    page.submit.click = submit
                    self.context.next_page = page
                    self.context.close_error = OSError('close failure')
                    result = self.cli('upload-video', '--account', 'Creator', '--file', str(self.video), '--title', 'Title')
                    self.assertEqual(result[0], 10, result)
                    self.assertIn('publish_attempted=true', result[2])
                    if 'captcha' in url: self.assertIn('verification', result[2])
                    self.assertEqual(page.submit.click_count, 1)


    def test_headless_defaults_explicit_overrides_browser_isolation(self):
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', True):
            self.assertEqual(self.cli('login', '--account', 'Creator', '--headed')[0], 0)
            self.assertEqual(self.cli('check', '--account', 'Creator')[0], 0)
            self.assertEqual(self.cli('check', '--account', 'Creator', '--local-browser', 'chromium')[0], 10)
            self.assertEqual(self.cli('login', '--account', 'Creator', '--local-browser', 'chromium')[0], 0)
        calls = self.playwright.chromium.persistent_calls
        self.assertEqual([call['headless'] for call in calls], [False, True, True])
        self.assertEqual(calls[0]['user_data_dir'], calls[1]['user_data_dir'])
        self.assertNotEqual(calls[1]['user_data_dir'], calls[2]['user_data_dir'])

    def test_custom_executable_product_wins_and_launch_failure_has_no_fallback(self):
        import plistlib
        executable = self.root / 'Renamed.app/Contents/MacOS/browser'
        executable.parent.mkdir(parents=True)
        executable.write_text('fixture')
        executable.chmod(0o755)
        (executable.parent.parent / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleName': 'Chromium', 'CFBundleIdentifier': 'org.chromium.Chromium', 'CFBundleExecutable': 'browser', 'CFBundleShortVersionString': '123.1'}))
        with patch('utils.local_browser.sys.platform', 'darwin'), patch.object(conf, 'LOCAL_CHROME_PATH', str(executable)):
            self.assertEqual(self.cli('login', '--account', 'Creator', '--local-browser', 'chrome')[0], 0)
            self.playwright.chromium.launch_error = RuntimeError('external browser lock')
            result = self.cli('check', '--account', 'Creator')
        self.assertEqual(result[0], 1, result)
        self.assertIn('executable_path=', result[2])
        self.assertEqual(len(self.playwright.chromium.persistent_calls), 2)
        self.assertTrue(all(call['user_data_dir'].endswith('/chromium') for call in self.playwright.chromium.persistent_calls))

    def test_reset_is_exact_and_requires_no_browser_and_rejects_active_profile(self):
        chrome, chromium = self.profile(), self.profile('chromium')
        history = self.root / 'result.json'
        history.write_text('history')
        with patch.object(conf, 'LOCAL_CHROME_PATH', '/does/not/exist'):
            with acquire_local_profile('tencent', 'Creator', 'chrome'):
                self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')[0], 1)
            self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')[0], 0)
            self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')[0], 0)
        self.assertFalse(chrome.exists())
        self.assertTrue(chromium.exists())
        self.assertEqual(history.read_text(), 'history')
        self.assertFalse(self.playwright.chromium.persistent_calls)

    def test_cancellation_and_hung_page_close_do_not_leak_profile_lease(self):
        self.profile()
        self.context.next_page = ChannelsPage(error=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            self.cli('check', '--account', 'Creator')
        self.assertTrue(self.context.closed)
        with acquire_local_profile('tencent', 'Creator', 'chrome'):
            pass
        async def hang(): await asyncio.Event().wait()
        self.context.next_page = ChannelsPage()
        self.context.next_page.close = hang
        with patch('utils.local_browser_session.CLOSE_TIMEOUT_SECONDS', 0.02):
            self.context.close = hang
            args = sau_cli.build_parser().parse_args(['tencent', 'check', '--account', 'Creator'])
            self.assertEqual(asyncio.run(asyncio.wait_for(sau_cli.dispatch(args), 1)), 0)
        with acquire_local_profile('tencent', 'Creator', 'chrome'):
            pass

    def test_managed_providers_use_headless_config_without_local_resolution(self):
        from tests.fakes import FakeAdspowerClient, FakeMultiloginClient, FakeBrowser
        for client_type, token_name, client_symbol in [
            (FakeAdspowerClient, 'ADSPOWER_API_KEY', 'AdspowerClient'),
            (FakeMultiloginClient, 'MLX_API_TOKEN', 'MultiloginClient'),
        ]:
            for flags, expected in [([], True), (['--headed'], False)]:
                with self.subTest(provider=token_name, flags=flags):
                    client = client_type()
                    browser = FakeBrowser([self.context])
                    self.playwright.chromium.queue_connect_browser(browser)
                    self.context.next_page = ChannelsPage()
                    self.context.next_page.close = FakePage.close.__get__(self.context.next_page)
                    with patch.dict(os.environ, {token_name: 'test-only-token'}), patch.object(conf, 'LOCAL_CHROME_HEADLESS', True), patch.object(conf, 'LOCAL_CHROME_PATH', '/invalid/unused'), patch.object(conf, 'LOCAL_BROWSER', 'unused-invalid', create=True), patch('sau_commands.browser.' + client_symbol, return_value=client):
                        result = self.cli('check', '--profile-id', 'profile', '--folder-id', 'folder', '--local-browser', 'chromium', *flags)
                    self.assertEqual(result[0], 0, result)
                    self.assertEqual(client.start_calls[0][-1], expected)
                    self.assertEqual(client.stop_calls, ['profile'])
                    self.assertFalse(self.context.closed)
                    self.assertEqual(browser.close_calls, 1)
        self.assertFalse(self.playwright.chromium.persistent_calls)
        self.assertFalse((self.root / 'browser_profiles').exists())

    def test_managed_login_reset_rejected_and_rate_limit_keeps_11(self):
        from tests.fakes import FakeAdspowerClient
        from utils.errors import RateLimitedError
        client = FakeAdspowerClient(start_error=RateLimitedError('429 no retry'))
        with patch.dict(os.environ, {'ADSPOWER_API_KEY': 'test-only-token'}), patch('sau_commands.browser.AdspowerClient', return_value=client):
            self.assertEqual(self.cli('login', '--account', 'Creator')[0], 1)
            self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')[0], 2)
            self.assertFalse(client.calls)
            self.assertEqual(self.cli('check', '--profile-id', 'profile')[0], 11)
        self.assertEqual(len(client.start_calls), 1)
        self.assertFalse(client.stop_calls)
        self.assertFalse(self.playwright.chromium.persistent_calls)

    def test_absent_optional_settings_keep_headed_chrome(self):
        with patch.dict(conf.__dict__):
            for name in ['LOCAL_BROWSER', 'LOCAL_CHROME_HEADLESS', 'LOCAL_CHROME_PATH']:
                conf.__dict__.pop(name, None)
            self.assertEqual(self.cli('login', '--account', 'Creator')[0], 0)
        call = self.playwright.chromium.persistent_calls[0]
        self.assertEqual(call['channel'], 'chrome')
        self.assertFalse(call['headless'])

    def test_login_and_upload_initialization_faults_close_and_release_profile(self):
        self.profile()
        self.context.next_page = ChannelsPage(error=RuntimeError('navigation failed'))
        for action in ['login', 'check', 'upload-video']:
            args = ['--file', str(self.video), '--title', 'Title'] if action == 'upload-video' else []
            result = self.cli(action, '--account', 'Creator', *args)
            self.assertEqual(result[0], 1, result)
            self.assertIn('navigation failed', result[2])
            self.assertTrue(self.context.closed)
            with acquire_local_profile('tencent', 'Creator', 'chrome'):
                pass

    def test_invalid_effective_config_and_aliases_fail_before_launch(self):
        for args in [('--local-browser', 'firefox'), ('--account', '../escape')]:
            result = self.cli('login', '--account', 'Creator', *args)
            self.assertEqual(result[0], 2, result)
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', 'false'):
            self.assertEqual(self.cli('check', '--account', 'Creator')[0], 2)
        self.assertFalse(self.playwright.chromium.persistent_calls)
        self.assertFalse((self.root / 'browser_profiles').exists())

    def test_direct_setup_probe_and_video_use_alias_and_config_without_legacy_file(self):
        from utils.browser_session import BrowserSession
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', True):
            asyncio.run(uploader.weixin_setup(account_name='Creator', handle=True))
            self.assertTrue(asyncio.run(uploader.cookie_auth(self.root / 'cookies/tencent_Creator.json', headless=False)))
            page = UploadPage()
            self.context.next_page = page
            app = uploader.TencentVideo('Title', self.video, [], 0, self.root / 'cookies/tencent_Creator.json', headless=False)
            asyncio.run(app.tencent_upload_video())
            self.context.closed = False
            asyncio.run(app.tencent_upload_video(session=BrowserSession(browser=None, context=self.context, mode='local')))
        self.assertEqual(page.submit.click_count, 2)
        self.assertFalse(self.context.closed)
        calls = self.playwright.chromium.persistent_calls
        self.assertEqual([call['headless'] for call in calls], [True, False, False])
        self.assertEqual(len({call['user_data_dir'] for call in calls}), 1)
        self.assertFalse(self.context.storage_state_calls)

    def test_success_error_and_unknown_result_survive_cleanup_failure(self):
        from unittest.mock import AsyncMock
        self.profile()
        for outcome, expected in [('success', 0), ('upload_error', 1), ('unknown', 9)]:
            with self.subTest(outcome=outcome):
                page = UploadPage()
                if outcome == 'upload_error':
                    async def fail(*_, **__): raise ValueError('upload failed')
                    page.selectors['input[type="file"]'].set_input_files = fail
                elif outcome == 'unknown':
                    async def submit(**_): page.submit.click_count += 1
                    page.submit.click = submit
                self.context.next_page = page
                self.context.close_error = OSError('close failure')
                with patch.object(uploader.asyncio, 'sleep', new=AsyncMock()):
                    result = self.cli('upload-video', '--account', 'Creator', '--file', str(self.video), '--title', 'Title')
                self.assertEqual(result[0], expected, result)
                self.assertEqual(page.submit.click_count, 0 if expected == 1 else 1)
                with acquire_local_profile('tencent', 'Creator', 'chrome'): pass

    def test_business_verification_and_navigation_redirect_end_upload(self):
        self.profile()
        for scenario in ('verification', 'redirect'):
            page = UploadPage()
            original_goto = page.goto
            async def goto(url, **kwargs):
                result = await original_goto(url, **kwargs)
                if url == uploader.TENCENT_HOME_URL:
                    if scenario == 'redirect':
                        page.url = 'https://channels.weixin.qq.com/login.html'
                        raise TimeoutError('navigation timed out')
                    page.selectors['div.weui-desktop-dialog__wrp:visible'] = RecordingLocator('实名验证')
                return result
            page.goto = goto
            self.context.next_page = page
            result = self.cli('upload-video', '--account', 'Creator', '--file', str(self.video), '--title', 'Title')
            self.assertEqual(result[0], 10, result)
            self.assertNotIn('publish_attempted=true', result[2])
            if scenario == 'verification': self.assertIn('verification', result[2])
            self.assertEqual(page.submit.click_count, 0)

    def test_qr_iframe_callback_completes_login_in_same_context_and_cleans_artifact(self):
        # A real PNG is saved/removed; the remote QR image and scan are browser boundaries.
        page = ChannelsPage(url='https://channels.weixin.qq.com/login.html', positive=False)
        data = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1kAAAAASUVORK5CYII='
        frame = RecordingLocator('login iframe', children={'div#app img.qrcode': RecordingLocator('qr', attributes={'src': data})})
        page.frame_locator = lambda _: frame
        self.context.next_page = page
        seen = []
        async def scanned(payload):
            seen.append(payload)
            self.assertTrue(Path(payload['image_path']).exists())
            page.target_url = None
            page.url = uploader.TENCENT_UPLOAD_URL
            page.positive = True
            with self.assertRaisesRegex(RuntimeError, '占用'):
                with acquire_local_profile('tencent', 'Creator', 'chrome'): pass
        result = asyncio.run(uploader.tencent_cookie_gen(account_name='Creator', qrcode_callback=scanned, poll_interval=0, max_checks=1))
        self.assertTrue(result['success'])
        self.assertEqual(len(seen), 1)
        self.assertFalse(Path(seen[0]['image_path']).exists())
        self.assertEqual(len(self.playwright.chromium.persistent_calls), 1)
        self.assertTrue(self.context.closed)
        self.assertFalse(self.context.storage_state_calls)

    def test_page_failure_after_submit_is_unknown_not_retryable(self):
        self.profile()
        page = UploadPage()
        async def submit(**_):
            page.submit.click_count += 1
            def unavailable(*_, **__): raise RuntimeError('page disconnected')
            page.locator = unavailable
        page.submit.click = submit
        self.context.next_page = page
        self.context.close_error = OSError('close failure')
        result = self.cli('upload-video', '--account', 'Creator', '--file', str(self.video), '--title', 'Title')
        self.assertEqual(result[0], 9, result)
        self.assertEqual(page.submit.click_count, 1)

    def test_qr_callback_cancellation_releases_profile_and_removes_saved_image(self):
        page = ChannelsPage(url='https://channels.weixin.qq.com/login.html', positive=False)
        data = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1kAAAAASUVORK5CYII='
        frame = RecordingLocator('login iframe', children={'div#app img.qrcode': RecordingLocator('qr', attributes={'src': data})})
        page.frame_locator = lambda _: frame
        self.context.next_page = page
        seen = []
        async def cancel(payload):
            seen.append(payload)
            raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(uploader.tencent_cookie_gen(account_name='Creator', qrcode_callback=cancel))
        self.assertTrue(self.context.closed)
        self.assertFalse(Path(seen[0]['image_path']).exists())
        with acquire_local_profile('tencent', 'Creator', 'chrome'): pass

    def test_schedule_draft_and_not_before_reach_controls_in_selected_profile(self):
        from datetime import datetime, timedelta, timezone
        self.profile()
        scheduled = (datetime.now(timezone.utc) + timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
        page = UploadPage()
        toggle = RecordingLocator('schedule toggle')
        day = RecordingLocator('day', text=str(scheduled.day))
        page.selectors.update({
            'label': RecordingLocator('labels', items=[RecordingLocator('label text'), toggle]),
            'input[placeholder="请选择发表时间"]': RecordingLocator('date'),
            'input[placeholder="请选择时间"]': RecordingLocator('time'),
            'table.weui-desktop-picker__table a': RecordingLocator('days', items=[day]),
        })
        async def month(_): return scheduled.strftime('%m月')
        page.inner_text = month
        original_evaluate = page.evaluate
        async def evaluate(expression, *args, **kwargs):
            if expression == 'Intl.DateTimeFormat().resolvedOptions().timeZone': return 'UTC'
            return await original_evaluate(expression, *args, **kwargs)
        page.evaluate = evaluate
        self.context.next_page = page
        result = self.cli('upload-video', '--account', 'Creator', '--file', str(self.video), '--title', 'Title',
                          '--schedule', scheduled.isoformat().replace('+00:00', 'Z'), '--draft')
        self.assertEqual(result[0], 0, result)
        self.assertEqual(toggle.click_count, 1)
        self.assertEqual(day.click_count, 1)
        self.assertIn(('insert_text', scheduled.strftime('%H')), page.keyboard.actions)
        self.assertEqual(page.submit.click_count, 1)
        page = UploadPage()
        self.context.next_page = page
        target = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=2)
        submitted = []
        async def submit(**_):
            page.submit.click_count += 1
            submitted.append(datetime.now(timezone.utc))
            with self.assertRaisesRegex(RuntimeError, '占用'):
                with acquire_local_profile('tencent', 'Creator', 'chrome'): pass
            page.url = uploader.TENCENT_MANAGE_URL
        page.submit.click = submit
        result = self.cli('upload-video', '--account', 'Creator', '--file', str(self.video), '--title', 'Title',
                          '--not-before', target.isoformat().replace('+00:00', 'Z'))
        self.assertEqual(result[0], 0, result)
        self.assertEqual(len(submitted), 1)
        self.assertGreaterEqual(submitted[0], target)
        self.assertEqual(len(self.playwright.chromium.persistent_calls), 2)
        self.assertFalse(self.context.storage_state_calls)

    def test_login_timeout_remains_login_required_and_keeps_profile(self):
        from unittest.mock import AsyncMock
        self.context.next_page = ChannelsPage(url='https://channels.weixin.qq.com/login.html', positive=False)
        with patch.object(uploader.asyncio, 'sleep', new=AsyncMock()):
            result = self.cli('login', '--account', 'Creator')
        self.assertEqual(result[0], 10, result)
        self.assertIn('登录超时', result[2])
        with acquire_local_profile('tencent', 'Creator', 'chrome') as profile:
            self.assertTrue(profile.exists)
        self.assertTrue(self.context.closed)

    def test_refreshed_qr_uses_same_artifact_directory_and_callback(self):
        from unittest.mock import AsyncMock
        page = ChannelsPage(url='https://channels.weixin.qq.com/login.html', positive=False)
        data = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1kAAAAASUVORK5CYII='
        frame = RecordingLocator('login iframe', children={'div#app img.qrcode': RecordingLocator('qr', attributes={'src': data})})
        page.frame_locator = lambda _: frame
        locator = page.locator
        refresh = RecordingLocator('refresh')
        def locate(selector, **kwargs):
            if 'refresh-tip' in selector or 'div.mask.show div.refresh-wrap' in selector: return refresh
            return locator(selector, **kwargs)
        page.locator = locate
        self.context.next_page = page
        seen = []
        async def scanned(payload):
            seen.append(Path(payload['image_path']))
            if len(seen) == 2:
                page.target_url = None
                page.url = uploader.TENCENT_UPLOAD_URL
                page.positive = True
        with patch.object(uploader.asyncio, 'sleep', new=AsyncMock()):
            result = asyncio.run(uploader.tencent_cookie_gen(account_name='Creator', qrcode_callback=scanned, poll_interval=0, max_checks=2))
        self.assertTrue(result['success'])
        self.assertEqual(len(seen), 2)
        self.assertEqual(refresh.click_count, 1)
        self.assertEqual({path.parent for path in seen}, {self.root / 'qr'})
        self.assertTrue(all(not path.exists() for path in seen))
