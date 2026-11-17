"""Alipay CLI → real configuration/Profile/session with external browser fakes."""
import asyncio
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import conf
import sau_cli
from sau_commands import alipay as command
from tests.fakes import FakeContext, FakePage, FakePlaywright
from tests.fakes_xhs_dom import RecordingLocator, RecordingKeyboard
from uploader.alipay_uploader import main as uploader
from utils.local_profile import acquire_local_profile


class PlaywrightCM:
    def __init__(self, playwright): self.playwright = playwright
    async def __aenter__(self): return self.playwright
    async def __aexit__(self, *_): pass


class BackendPage(FakePage):
    def __init__(self, *, url=None, status=200, error=None, anchor=True, login=False, verification=False):
        super().__init__()
        self.target_url, self.status, self.error = url, status, error
        self.anchor, self.login, self.verification = anchor, login, verification
    async def goto(self, url, **kwargs):
        await super().goto(url, **kwargs)
        self.url = self.target_url or uploader.ALIPAY_LIFE_ACCOUNT_URL
        if self.error: raise self.error
        return SimpleNamespace(status=self.status)
    async def wait_for_timeout(self, _): pass
    def locator(self, selector):
        present = (self.anchor and selector in uploader.ALIPAY_LOGIN_POSITIVE_SELECTORS) or (self.login and selector == 'iframe[title="login"]')
        return RecordingLocator(selector, count=int(present))
    async def close(self):
        raise AssertionError('Local pages are owned by the persistent context')


class UploadPage(BackendPage):
    def __init__(self):
        super().__init__()
        self.keyboard = RecordingKeyboard()
        self.listeners = {}
        self.selectors = {selector: RecordingLocator(selector) for selector in [
            'input[type="file"]', uploader.ALIPAY_LOGIN_POSITIVE_SELECTORS[0], 'title', 'publish']}
        self.submit_url = uploader.ALIPAY_POSTS_URL
        async def submit(**_):
            self.selectors['publish'].click_count += 1
            self.url = self.submit_url
        self.selectors['publish'].click = submit
        self.selectors['publish'].is_disabled = AsyncMock(return_value=False)
    def locator(self, selector, **_):
        return self.selectors[selector] if selector in self.selectors else super().locator(selector)
    def get_by_placeholder(self, _): return self.selectors['title']
    def get_by_role(self, role, name=None): return self.selectors['publish']
    async def wait_for_load_state(self, *_, **__): pass
    async def wait_for_url(self, *_, **__): self.url = 'https://c.alipay.com/page/content-creation/publish/short-video'
    def on(self, name, callback): self.listeners[name] = callback
    def remove_listener(self, name, callback): self.listeners.pop(name, None)


class BackendContext(FakeContext):
    def __init__(self):
        super().__init__()
        self.next_page = BackendPage()
    async def new_page(self):
        self.pages.append(self.next_page)
        return self.next_page


class AlipayProfilesTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.pw = FakePlaywright()
        async def forbid_launch(**_): raise AssertionError('Use the persistent Profile')
        self.pw.chromium.launch = forbid_launch
        self.context = BackendContext()
        self.pw.chromium.persistent_context = self.context
        for key, value in {'BASE_DIR': self.root, 'LOCAL_CHROME_PATH': '', 'LOCAL_CHROME_HEADLESS': False, 'LOCAL_BROWSER': 'chrome'}.items():
            self.stack.enter_context(patch.object(conf, key, value, create=True))
        self.stack.enter_context(patch.dict(os.environ, {'MLX_API_TOKEN': '', 'ADSPOWER_API_KEY': '', 'HUMANIZE': '0'}))
        for module in (command, uploader):
            self.stack.enter_context(patch.object(module, 'async_playwright', lambda: PlaywrightCM(self.pw)))
        self.video, self.cover = self.root / 'video.mp4', self.root / 'cover.png'
        self.video.write_bytes(b'video')
        self.cover.write_bytes(b'image')
    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = sau_cli.main(['alipay', *args])
            except SystemExit as error:
                code = error.code
        return code, out.getvalue(), err.getvalue()
    def profile(self, kind='chrome', account='Creator'):
        with acquire_local_profile('alipay', account, kind, create=True) as profile:
            return profile.path
    def upload(self, *args):
        return self.cli('upload-video', '--account', 'Creator', '--file', str(self.video), '--title', 'A video title', *args)

    def test_login_check_reuse_profile_and_ignore_legacy_json(self):
        legacy = self.root / 'cookies/alipay_Creator.json'
        legacy.parent.mkdir()
        legacy.write_text('malformed old state')
        result = self.cli('login', '--account', 'Creator')
        self.assertEqual(result[0], 0, result)
        self.assertEqual(self.cli('check', '--account', 'Creator')[0], 0)
        calls = self.pw.chromium.persistent_calls
        self.assertEqual(calls, [dict(user_data_dir=str(self.root / 'browser_profiles/alipay/Creator/chrome'), channel='chrome', headless=False, no_viewport=True)] * 2)
        self.assertTrue(self.context.closed)
        self.assertFalse(self.context.storage_state_calls)
        self.assertFalse(self.context.add_init_script_calls)
        self.assertEqual(legacy.read_text(), 'malformed old state')


    def test_video_uses_one_selected_profile_for_preflight_and_submission(self):
        self.profile('chromium')
        page = UploadPage()
        self.context.next_page = page
        result = self.upload('--local-browser', 'chromium', '--headless')
        self.assertEqual(result[0], 0, result)
        self.assertEqual(len(self.pw.chromium.persistent_calls), 1)
        call = self.pw.chromium.persistent_calls[0]
        self.assertEqual((call['channel'], call['headless']), ('chromium', True))
        self.assertEqual(page.selectors['publish'].click_count, 1)
        self.assertEqual(page.selectors['input[type="file"]'].files, [str(self.video)])
        self.assertIn(('insert_text', 'A video title'), page.keyboard.actions)
        self.assertFalse(self.context.storage_state_calls)
        self.assertTrue(self.context.closed)

    def test_authentication_evidence_is_distinct_from_faults(self):
        self.assertEqual(self.cli('check', '--account', 'Creator')[0], 10)
        self.profile()
        for page, code in [
            (BackendPage(login=True), 10),
            (BackendPage(url='https://auth.alipay.com/login'), 10),
            (BackendPage(url='https://captcha.alipay.com/verify'), 10),
            (BackendPage(status=403, login=True), 1), (BackendPage(status=503), 1),
            (BackendPage(anchor=False), 1), (BackendPage(error=OSError('network failure')), 1),
            (BackendPage(url='https://c.alipay.com.unexpected.invalid'), 1),
            (BackendPage(url='https://auth.alipay.com/login', error=TimeoutError('navigation interrupted')), 10),
        ]:
            with self.subTest(url=page.target_url, code=code, status=page.status):
                self.context.next_page = page
                result = self.cli('check', '--account', 'Creator')
                self.assertEqual(result[0], code, result)
                if 'verify' in str(page.target_url): self.assertIn('reason=verification', result[2])

    def test_pre_and_post_submit_login_iframe_or_verification_keep_phase(self):
        self.profile()
        for phase in ('before', 'after', 'click-error'):
            for verification in (False, True):
                with self.subTest(phase=phase, verification=verification):
                    page = UploadPage()
                    self.context.next_page = page
                    self.context.close_error = OSError('cleanup failed')
                    async def redirect(*_, **__):
                        page.login = not verification
                        if verification: page.url = 'https://captcha.alipay.com/verify'
                        if phase != 'before': page.selectors['publish'].click_count += 1
                        if phase != 'after': raise TimeoutError('navigation interrupted')
                    if phase == 'before': page.selectors['title'].wait_for = redirect
                    else: page.selectors['publish'].click = redirect
                    result = self.upload()
                    self.assertEqual(result[0], 10, result)
                    self.assertEqual('publish_attempted=true' in result[2], phase != 'before')
                    self.assertEqual('reason=verification' in result[2], verification)
                    self.assertEqual(page.selectors['publish'].click_count, int(phase != 'before'))

    def test_explicit_cover_failure_stops_before_publish(self):
        self.profile()
        page = UploadPage()
        self.context.next_page = page
        from tests.test_alipay_humanize import Element
        page.get_by_text = lambda *_, **__: Element('cover')
        page.selectors[uploader.ALIPAY_COVER_IMAGE_INPUT_SELECTOR] = RecordingLocator('image')
        page.selectors[uploader.ALIPAY_COVER_IMAGE_INPUT_SELECTOR].set_input_files = AsyncMock(side_effect=PermissionError('cover upload denied'))
        result = self.upload('--thumbnail', str(self.cover))
        self.assertEqual(result[0], 1, result)
        self.assertIn('cover upload denied', result[2])
        self.assertEqual(page.selectors['publish'].click_count, 0)


    def test_defaults_overrides_browser_isolation_and_absent_optional_settings(self):
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', True):
            self.assertEqual(self.cli('login', '--account', 'Creator', '--headed')[0], 0)
            self.assertEqual(self.cli('check', '--account', 'Creator')[0], 0)
            self.assertEqual(self.cli('check', '--account', 'Creator', '--local-browser', 'chromium')[0], 10)
            self.assertEqual(self.cli('login', '--account', 'Creator', '--local-browser', 'chromium')[0], 0)
        calls = self.pw.chromium.persistent_calls
        self.assertEqual([call['headless'] for call in calls], [False, True, True])
        self.assertEqual(calls[0]['user_data_dir'], calls[1]['user_data_dir'])
        self.assertNotEqual(calls[1]['user_data_dir'], calls[2]['user_data_dir'])
        with patch.dict(conf.__dict__):
            for key in ('LOCAL_CHROME_PATH', 'LOCAL_CHROME_HEADLESS', 'LOCAL_BROWSER'):
                conf.__dict__.pop(key, None)
            self.assertEqual(self.cli('check', '--account', 'Creator')[0], 0)
        self.assertFalse(calls[-1]['headless'])
        self.assertEqual(calls[-1]['channel'], 'chrome')

    def test_custom_binary_kind_overrides_selection_and_never_falls_back(self):
        import plistlib
        binary = self.root / 'Chosen.app/Contents/MacOS/chosen'
        binary.parent.mkdir(parents=True)
        binary.write_text('fixture')
        binary.chmod(0o755)
        (binary.parent.parent / 'Info.plist').write_bytes(plistlib.dumps(dict(
            CFBundleName='Chromium', CFBundleIdentifier='org.chromium.Chromium',
            CFBundleExecutable='chosen', CFBundleShortVersionString='123.0')))
        with patch('utils.local_browser.sys.platform', 'darwin'), patch.object(conf, 'LOCAL_CHROME_PATH', str(binary)):
            self.assertEqual(self.cli('login', '--account', 'Creator', '--local-browser', 'chrome')[0], 0)
            self.pw.chromium.launch_error = PermissionError('browser permission denied')
            result = self.cli('check', '--account', 'Creator')
        self.assertEqual(result[0], 1, result)
        self.assertIn('executable_path=', result[2])
        self.assertEqual(len(self.pw.chromium.persistent_calls), 2)
        self.assertTrue(all(call['user_data_dir'].endswith('/chromium') for call in self.pw.chromium.persistent_calls))

    def test_reset_exact_profile_without_binary_and_protects_lease_history_and_old_state(self):
        chrome, chromium = self.profile(), self.profile('chromium')
        old = self.root / 'old.json'; old.write_text('old login state')
        history = self.root / 'result.json'; history.write_text('historical work')
        with patch.object(conf, 'LOCAL_CHROME_PATH', '/missing/binary'):
            with acquire_local_profile('alipay', 'Creator', 'chrome'):
                result = self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')
                self.assertEqual(result[0], 1, result)
            self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')[0], 0)
            self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')[0], 0)
        self.assertFalse(chrome.exists())
        self.assertTrue(chromium.exists())
        self.assertEqual(old.read_text(), 'old login state')
        self.assertEqual(history.read_text(), 'historical work')
        self.assertFalse(self.pw.chromium.persistent_calls)

    def test_cancellation_and_hung_cleanup_release_profile_without_page_close(self):
        self.profile()
        self.context.next_page = BackendPage(error=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            self.cli('check', '--account', 'Creator')
        self.assertTrue(self.context.closed)
        async def hang(): await asyncio.Event().wait()
        self.context.next_page = BackendPage()
        self.context.next_page.close = hang
        self.context.close = hang
        args = sau_cli.build_parser().parse_args(['alipay', 'check', '--account', 'Creator'])
        with patch('utils.local_browser_session.CLOSE_TIMEOUT_SECONDS', 0.02):
            self.assertEqual(asyncio.run(asyncio.wait_for(sau_cli.dispatch(args), 1)), 0)
        with acquire_local_profile('alipay', 'Creator', 'chrome'):
            pass

    def test_initialization_failures_remain_faults_and_release_owned_context(self):
        self.profile()
        for action in ('login', 'check', 'upload-video'):
            self.context.next_page = BackendPage(error=OSError('navigation failed'))
            result = self.upload() if action == 'upload-video' else self.cli(action, '--account', 'Creator')
            self.assertEqual(result[0], 1, result)
            self.assertIn('navigation failed', result[2])
            self.assertTrue(self.context.closed)
            with acquire_local_profile('alipay', 'Creator', 'chrome'):
                pass

    def test_managed_providers_ignore_local_config_and_use_resolved_headless(self):
        from tests.fakes import FakeAdspowerClient, FakeMultiloginClient, FakeBrowser
        for client_type, token, symbol in [(FakeAdspowerClient, 'ADSPOWER_API_KEY', 'AdspowerClient'),
                                           (FakeMultiloginClient, 'MLX_API_TOKEN', 'MultiloginClient')]:
            for flags, headless in [([], True), (['--headed'], False)]:
                client = client_type()
                browser = FakeBrowser([self.context])
                self.pw.chromium.queue_connect_browser(browser)
                page = BackendPage()
                page.close = FakePage.close.__get__(page)
                self.context.next_page = page
                with patch.dict(os.environ, {token:'test-only-token'}), patch.object(conf, 'LOCAL_CHROME_PATH', '/unused/missing'), patch.object(conf, 'LOCAL_BROWSER', 'unused-invalid', create=True), patch.object(conf, 'LOCAL_CHROME_HEADLESS', True), patch('sau_commands.browser.' + symbol, return_value=client):
                    result = self.cli('check', '--profile-id', 'profile', '--folder-id', 'folder', '--local-browser', 'chromium', *flags)
                self.assertEqual(result[0], 0, result)
                self.assertEqual(client.start_calls[0][-1], headless)
                self.assertEqual(client.stop_calls, ['profile'])
                self.assertFalse(self.context.closed)
                self.assertEqual(browser.close_calls, 1)
        self.assertFalse((self.root / 'browser_profiles').exists())
        self.assertFalse(self.pw.chromium.persistent_calls)

    def test_managed_login_reset_rejection_and_rate_limit_preserve_routing(self):
        from tests.fakes import FakeAdspowerClient
        from utils.errors import RateLimitedError
        client = FakeAdspowerClient(start_error=RateLimitedError('429 no retry'))
        with patch.dict(os.environ, {'ADSPOWER_API_KEY':'test-only-token'}), patch('sau_commands.browser.AdspowerClient', return_value=client):
            self.assertEqual(self.cli('login', '--account', 'Creator')[0], 1)
            self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')[0], 2)
            self.assertFalse(client.calls)
            self.assertEqual(self.cli('check', '--profile-id', 'profile')[0], 11)
        self.assertEqual(len(client.start_calls), 1)
        self.assertFalse(client.stop_calls)
        self.assertFalse(self.pw.chromium.persistent_calls)
    def test_direct_alias_and_injected_session_ownership(self):
        from utils.browser_session import BrowserSession
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', True):
            self.assertTrue(asyncio.run(uploader.alipay_setup(account_name='Creator', handle=True)))
            self.assertTrue(asyncio.run(uploader.cookie_auth('/missing/alipay_Creator.json', headless=False)))
            self.context.next_page = UploadPage()
            app = uploader.AlipayVideo('Title', self.video, [], '/missing/alipay_Creator.json', headless=False)
            asyncio.run(app.main())
        calls = self.pw.chromium.persistent_calls
        self.assertEqual([call['headless'] for call in calls], [True, False, False])
        self.assertEqual(len({call['user_data_dir'] for call in calls}), 1)
        self.assertFalse((self.root / 'cookies').exists())
        self.context.closed = False
        self.context.next_page = UploadPage()
        app = uploader.AlipayVideo('Title', self.video, [], None)
        asyncio.run(app.main(session=BrowserSession(browser=None, context=self.context, mode='local')))
        self.assertFalse(self.context.closed)
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.context.next_page.selectors['publish'].click_count, 1)

    def test_qr_login_callback_requires_content_entry_and_cleans_temporary_image(self):
        page = BackendPage(login=True, anchor=False)
        self.context.next_page = page
        qr = RecordingLocator('QR')
        async def screenshot(path, **_):
            import base64
            Path(path).write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='))
        qr.screenshot = screenshot
        frame = SimpleNamespace(locator=lambda selector: RecordingLocator(selector, count=0) if selector == '#J-login' else qr)
        page.frame_locator = lambda _: frame
        qr_paths = []
        async def scanned(payload):
            qr_paths.append(Path(payload['image_path']))
            self.assertTrue(qr_paths[-1].exists())
            page.login, page.anchor = False, True
        result = asyncio.run(uploader.alipay_cookie_gen(account_name='Creator', qrcode_callback=scanned))
        self.assertTrue(result['success'])
        self.assertEqual(len(self.pw.chromium.persistent_calls), 1)
        self.assertEqual(len(qr_paths), 1)
        self.assertFalse(qr_paths[0].exists())
        self.assertFalse(self.context.storage_state_calls)
        self.assertFalse(self.context.add_init_script_calls)

    def test_unknown_result_budget_and_success_survive_cleanup_failures(self):
        import time
        import uploader.publish_timeout as timeout_module
        self.profile()
        for phase, expected in [('before', 1), ('after', 9), ('success', 0)]:
            with self.subTest(phase=phase):
                page = UploadPage()
                self.context.next_page = page
                self.context.close_error = OSError('cleanup failed')
                clock = SimpleNamespace(offset=0)
                fake_time = SimpleNamespace(monotonic=lambda: time.monotonic() + clock.offset)
                submit = page.selectors['publish']
                async def click(**_):
                    submit.click_count += 1
                    if phase == 'success': page.url = uploader.ALIPAY_POSTS_URL
                    else: clock.offset = 1000
                submit.click = click
                original_wait = page.wait_for_url
                async def wait(*args, **kwargs):
                    await original_wait(*args, **kwargs)
                    if phase == 'before': clock.offset = 1000
                page.wait_for_url = wait
                with patch.object(timeout_module, 'time', fake_time): result = self.upload()
                self.assertEqual(result[0], expected, result)
                self.assertEqual(submit.click_count, int(phase != 'before'))

    def test_upload_page_http_failure_stops_with_fault_even_if_anchor_exists(self):
        self.profile()
        page = UploadPage()
        self.context.next_page = page
        original = page.goto
        async def goto(url, **kwargs):
            response = await original(url, **kwargs)
            if len(page.goto_calls) > 1:
                page.login = True
                return SimpleNamespace(status=503)
            return response
        page.goto = goto
        result = self.upload()
        self.assertEqual(result[0], 1, result)
        self.assertIn('HTTP 503', result[2])
        self.assertEqual(page.selectors['publish'].click_count, 0)

    def test_qr_cleanup_fault_preserves_callback_failure(self):
        page = BackendPage(login=True, anchor=False)
        self.context.next_page = page
        qr = RecordingLocator('QR')
        async def screenshot(path, **_): Path(path).write_bytes(b'fixture-image')
        qr.screenshot = screenshot
        page.frame_locator = lambda _: SimpleNamespace(locator=lambda selector: RecordingLocator(selector, count=0) if selector == '#J-login' else qr)
        paths = []
        def callback(payload):
            paths.append(Path(payload['image_path']))
            raise ValueError('callback failed')
        unlink = Path.unlink
        def failing_unlink(path, *args, **kwargs):
            if path.suffix == '.png': raise PermissionError('QR cleanup failed')
            return unlink(path, *args, **kwargs)
        try:
            with patch.object(Path, 'unlink', failing_unlink):
                with self.assertRaisesRegex(ValueError, 'callback failed'):
                    asyncio.run(uploader.alipay_cookie_gen(account_name='Creator', qrcode_callback=callback))
        finally:
            for path in paths:
                if path.exists(): path.unlink()
        self.assertTrue(self.context.closed)

    def test_local_publication_is_not_retried_after_aigc_preprocessing_signal(self):
        import time
        import uploader.publish_timeout as timeout_module
        self.profile()
        page = UploadPage()
        self.context.next_page = page
        clock = SimpleNamespace(offset=0)
        fake_time = SimpleNamespace(monotonic=lambda: time.monotonic() + clock.offset)
        async def click(**_):
            page.selectors['publish'].click_count += 1
            page.listeners['response'](SimpleNamespace(
                url='https://c.alipay.com/content-creation/querylooptask', status=200,
                request=SimpleNamespace(post_data='', method='POST'),
                headers={'content-type':'application/json'}, text=AsyncMock(return_value='{"done":true}')))
        async def wait(milliseconds):
            await asyncio.sleep(0)
            if milliseconds == 1000: clock.offset = 1000
        page.selectors['publish'].click = click
        page.wait_for_timeout = wait
        with patch.object(timeout_module, 'time', fake_time): result = self.upload()
        self.assertEqual(result[0], 9, result)
        self.assertEqual(page.selectors['publish'].click_count, 1)

    def test_post_dispatch_browser_fault_is_unknown_and_never_retried(self):
        self.profile()
        page = UploadPage()
        self.context.next_page = page
        page.submit_url = 'https://c.alipay.com/page/content-creation/publish/short-video'
        async def wait(_):
            if page.selectors['publish'].click_count: raise OSError('browser observation lost')
        page.wait_for_timeout = wait
        locator = page.locator
        def closed_locator(*args, **kwargs):
            if page.selectors['publish'].click_count: raise OSError('page is closed')
            return locator(*args, **kwargs)
        page.locator = closed_locator
        result = self.upload()
        self.assertEqual(result[0], 9, result)
        self.assertEqual(page.selectors['publish'].click_count, 1)

    def test_quality_overlay_is_released_at_most_once_when_result_remains_unknown(self):
        import time
        import uploader.publish_timeout as timeout_module
        self.profile()
        page = UploadPage()
        self.context.next_page = page
        page.submit_url = 'https://c.alipay.com/page/content-creation/publish/short-video'
        quality = RecordingLocator('quality confirmation')
        page.selectors[uploader.ALIPAY_QUALITY_MODAL_BUTTON_SELECTOR] = quality
        clock = SimpleNamespace(offset=0)
        async def wait(milliseconds):
            if milliseconds == 1000: clock.offset = 1000
        page.wait_for_timeout = wait
        with patch.object(timeout_module, 'time', SimpleNamespace(monotonic=lambda: time.monotonic()+clock.offset)):
            result = self.upload()
        self.assertEqual(result[0], 9, result)
        self.assertEqual(quality.click_count, 1)
        self.assertEqual(page.selectors['publish'].click_count, 1)

    def test_requested_collection_fault_stops_before_publish(self):
        from tests.test_alipay_humanize import Element
        self.profile()
        page = UploadPage()
        self.context.next_page = page
        collection = Element('collection')
        collection.scroll_into_view_if_needed = AsyncMock(side_effect=PermissionError('collection control failed'))
        page.selectors['input[id*="_compilationInfo"]'] = collection
        result = self.upload('--collection', 'Requested collection')
        self.assertEqual(result[0], 1, result)
        self.assertIn('collection control failed', result[2])
        self.assertEqual(page.selectors['publish'].click_count, 0)
