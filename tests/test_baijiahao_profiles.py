"""Baijiahao CLI → real configuration/Profile/session with external browser fakes."""
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
from sau_commands import baijiahao as command
from tests.fakes import FakeContext, FakePage, FakePlaywright
from tests.fakes_xhs_dom import RecordingLocator, RecordingKeyboard
from uploader.baijiahao_uploader import main as uploader
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
        self.url = self.target_url or uploader.BAIJIAHAO_HOME_URL
        if self.error: raise self.error
        return SimpleNamespace(status=self.status)
    async def wait_for_timeout(self, _): pass
    def locator(self, selector):
        present = (self.anchor and selector in uploader.BAIJIAHAO_BUSINESS_ANCHOR_SELECTORS) or (self.verification and selector == 'text="百度安全验证"')
        return RecordingLocator(selector, count=int(present))
    def get_by_text(self, text, **_):
        return RecordingLocator(text, count=int(self.login and text == uploader.BAIJIAHAO_LOGIN_TEXT))
    async def close(self):
        raise AssertionError('Local pages are owned by the persistent context')


class UploadPage(BackendPage):
    def __init__(self):
        super().__init__()
        self.keyboard = RecordingKeyboard()
        self.progress = iter(['50%', '100%', '100%'])
        self.selectors = {selector: RecordingLocator(selector) for selector in [
            'input[type="file"][accept*="video"], input[type="file"][accept*="mp4"]',
            uploader.TITLE_EDITOR_SELECTOR, uploader.COVER_ENTRY_SELECTOR,
            uploader.COVER_IMAGE_INPUT_SELECTOR, uploader.COVER_CONFIRM_SELECTOR,
            uploader.AI_DECLARATION_TRIGGER_SELECTOR, uploader.AI_DECLARATION_OPTION_SELECTOR,
            uploader.PUBLISH_BUTTON_SELECTOR]}
        self.selectors[uploader.DECLARATION_MODAL_SELECTOR] = RecordingLocator('modal', count=0)
        self.selectors['.cheetah-message-error, .cheetah-message-warning'] = RecordingLocator('toast', count=0)
        self.submit_url = uploader.BAIJIAHAO_SUCCESS_URL_PREFIX
        async def submit(**_):
            self.selectors[uploader.PUBLISH_BUTTON_SELECTOR].click_count += 1
            self.url = self.submit_url
        self.selectors[uploader.PUBLISH_BUTTON_SELECTOR].click = submit
    async def goto(self, url, **kwargs):
        result = await super().goto(url, **kwargs)
        if url == uploader.BAIJIAHAO_PUBLISH_URL: self.url = url
        return result
    async def inner_text(self, _): return next(self.progress, '100%')
    def locator(self, selector):
        return self.selectors[selector] if selector in self.selectors else super().locator(selector)


class BackendContext(FakeContext):
    def __init__(self):
        super().__init__()
        self.next_page = BackendPage()
    async def new_page(self):
        self.pages.append(self.next_page)
        return self.next_page


class BaijiahaoProfilesTests(unittest.TestCase):
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
                code = sau_cli.main(['baijiahao', *args])
            except SystemExit as error:
                code = error.code
        return code, out.getvalue(), err.getvalue()
    def profile(self, kind='chrome', account='Creator'):
        with acquire_local_profile('baijiahao', account, kind, create=True) as profile:
            return profile.path
    def upload(self, *args):
        return self.cli('upload-video', '--account', 'Creator', '--file', str(self.video), '--title', 'A video title', '--thumbnail', str(self.cover), *args)

    def test_login_check_reuse_profile_and_ignore_legacy_json(self):
        legacy = self.root / 'cookies/baijiahao_Creator.json'
        legacy.parent.mkdir()
        legacy.write_text('malformed old state')
        result = self.cli('login', '--account', 'Creator')
        self.assertEqual(result[0], 0, result)
        self.assertEqual(self.cli('check', '--account', 'Creator')[0], 0)
        calls = self.pw.chromium.persistent_calls
        self.assertEqual(calls, [dict(user_data_dir=str(self.root / 'browser_profiles/chrome/baijiahao/Creator'), channel='chrome', headless=False, no_viewport=True)] * 2)
        self.assertTrue(self.context.closed)
        self.assertFalse(self.context.storage_state_calls)
        self.assertFalse(self.context.add_init_script_calls)
        self.assertEqual(legacy.read_text(), 'malformed old state')

    def test_video_uses_one_selected_profile_for_preflight_and_submission(self):
        self.profile('chromium')
        page = UploadPage()
        self.context.next_page = page
        with patch.object(uploader.asyncio, 'sleep', new=AsyncMock()):
            result = self.upload('--local-browser', 'chromium', '--headless')
        self.assertEqual(result[0], 0, result)
        self.assertEqual(len(self.pw.chromium.persistent_calls), 1)
        call = self.pw.chromium.persistent_calls[0]
        self.assertEqual((call['channel'], call['headless']), ('chromium', True))
        self.assertEqual(page.selectors[uploader.PUBLISH_BUTTON_SELECTOR].click_count, 1)
        self.assertEqual(page.selectors[uploader.COVER_IMAGE_INPUT_SELECTOR].files, [str(self.cover)])
        self.assertIn(('insert_text', 'A video title'), page.keyboard.actions)
        self.assertFalse(self.context.storage_state_calls)
        self.assertTrue(self.context.closed)

    def test_authentication_faults_and_verification_keep_distinct_exit_codes(self):
        self.assertEqual(self.cli('check', '--account', 'Creator')[0], 10)
        self.profile()
        for page, code in [
            (BackendPage(login=True, anchor=False), 10),
            (BackendPage(url='https://passport.baidu.com/login'), 10),
            (BackendPage(verification=True), 10),
            (BackendPage(url='https://passport.baidu.com/', verification=True), 10),
            (BackendPage(url='https://passport.baidu.com/verify'), 10),
            (BackendPage(status=403), 1), (BackendPage(status=503), 1),
            (BackendPage(anchor=False), 1), (BackendPage(error=OSError('network failure')), 1),
            (BackendPage(url='https://unexpected.invalid', anchor=True), 1),
        ]:
            with self.subTest(page=vars(page)):
                self.context.next_page = page
                result = self.cli('check', '--account', 'Creator')
                self.assertEqual(result[0], code, result)
                if page.verification or 'verify' in str(page.target_url):
                    self.assertIn('reason=verification', result[2])
        self.context.next_page = BackendPage(error=TimeoutError('redirect during navigation'), url='https://passport.baidu.com/login')
        self.assertEqual(self.cli('check', '--account', 'Creator')[0], 10)

    def test_upload_post_submit_login_preserves_attempt_and_cleanup_failure(self):
        self.profile()
        page = UploadPage()
        submit = page.selectors[uploader.PUBLISH_BUTTON_SELECTOR]
        async def click(**_):
            submit.click_count += 1
            page.url = 'https://passport.baidu.com/verify'
            page.verification = True
        submit.click = click
        self.context.next_page = page
        self.context.close_error = OSError('close failure')
        with patch.object(uploader.asyncio, 'sleep', new=AsyncMock()):
            result = self.upload()
        self.assertEqual(result[0], 10, result)
        self.assertIn('publish_attempted=true', result[2])
        self.assertIn('reason=verification', result[2])
        self.assertEqual(page.selectors[uploader.PUBLISH_BUTTON_SELECTOR].click_count, 1)

    def test_required_cover_fault_is_not_hidden_by_automatic_cover_fallback(self):
        self.profile()
        page = UploadPage()
        page.selectors[uploader.COVER_IMAGE_INPUT_SELECTOR].set_input_files = AsyncMock(side_effect=PermissionError('cover permission denied'))
        page.selectors['div.cheetah-spin-container img'] = RecordingLocator('automatic cover')
        self.context.next_page = page
        with patch.object(uploader.asyncio, 'sleep', new=AsyncMock()):
            result = self.upload()
        self.assertEqual(result[0], 1, result)
        self.assertIn('cover permission denied', result[2])
        self.assertEqual(page.selectors[uploader.PUBLISH_BUTTON_SELECTOR].click_count, 0)

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
        self.assertTrue(all(call['user_data_dir'].endswith('/chromium/baijiahao/Creator') for call in self.pw.chromium.persistent_calls))

    def test_reset_exact_profile_without_binary_and_protects_lease_history_and_old_state(self):
        chrome, chromium = self.profile(), self.profile('chromium')
        old = self.root / 'old.json'; old.write_text('old login state')
        history = self.root / 'result.json'; history.write_text('historical work')
        with patch.object(conf, 'LOCAL_CHROME_PATH', '/missing/binary'):
            with acquire_local_profile('baijiahao', 'Creator', 'chrome'):
                result = self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')
                self.assertEqual(result[0], 1, result)
            self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')[0], 0)
            self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')[0], 0)
        self.assertFalse(chrome.exists())
        self.assertTrue(chromium.exists())
        self.assertEqual(old.read_text(), 'old login state')
        self.assertEqual(history.read_text(), 'historical work')
        self.assertFalse(self.pw.chromium.persistent_calls)

    def test_direct_setup_probe_and_uploader_use_alias_and_explicit_false(self):
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', True):
            self.assertTrue(asyncio.run(uploader.baijiahao_setup(account_name='Creator', handle=True)))
            self.assertTrue(asyncio.run(uploader.cookie_auth('/missing/baijiahao_Creator.json', headless=False)))
            self.context.next_page = UploadPage()
            app = uploader.BaiJiaHaoVideo('Title123456', self.video, [], '/missing/baijiahao_Creator.json',
                                          thumbnail_path=self.cover, headless=False)
            with patch.object(uploader.asyncio, 'sleep', new=AsyncMock()):
                asyncio.run(app.main())
        calls = self.pw.chromium.persistent_calls
        self.assertEqual([call['headless'] for call in calls], [True, False, False])
        self.assertEqual(len({call['user_data_dir'] for call in calls}), 1)
        self.assertFalse((self.root / 'cookies').exists())

    def test_guided_qr_login_uses_positive_business_evidence_and_one_profile(self):
        page = BackendPage(login=True, anchor=False)
        self.context.next_page = page
        qr = RecordingLocator('QR')
        async def screenshot(path, **_):
            import base64
            Path(path).write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='))
        qr.screenshot = screenshot
        original_locator = page.locator
        page.locator = lambda selector: qr if selector == uploader.QR_SELECTOR else original_locator(selector)
        qr_paths = []
        def scanned(payload):
            qr_paths.append(Path(payload['image_path']))
            self.assertTrue(qr_paths[-1].exists())
            page.url = uploader.BAIJIAHAO_HOME_URL
            page.login, page.anchor = False, True
            qr._count = 0
        result = asyncio.run(uploader.baijiahao_cookie_gen(account_name='Creator', qrcode_callback=scanned, headless=False))
        self.assertTrue(result['success'])
        self.assertEqual(len(self.pw.chromium.persistent_calls), 1)
        self.assertTrue(self.context.closed)
        self.assertTrue(qr_paths)
        self.assertFalse(qr_paths[0].exists())
        self.assertFalse(self.context.storage_state_calls)

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
        args = sau_cli.build_parser().parse_args(['baijiahao', 'check', '--account', 'Creator'])
        with patch('utils.local_browser_session.CLOSE_TIMEOUT_SECONDS', 0.02):
            self.assertEqual(asyncio.run(asyncio.wait_for(sau_cli.dispatch(args), 1)), 0)
        with acquire_local_profile('baijiahao', 'Creator', 'chrome'):
            pass

    def test_initialization_failures_remain_faults_and_release_owned_context(self):
        self.profile()
        for action in ('login', 'check', 'upload-video'):
            self.context.next_page = BackendPage(error=OSError('navigation failed'))
            result = self.upload() if action == 'upload-video' else self.cli(action, '--account', 'Creator')
            self.assertEqual(result[0], 1, result)
            self.assertIn('navigation failed', result[2])
            self.assertTrue(self.context.closed)
            with acquire_local_profile('baijiahao', 'Creator', 'chrome'):
                pass

    def test_success_and_pre_submit_failure_survive_cleanup_error(self):
        self.profile()
        for error, expected in ((None, 0), (PermissionError('file inaccessible'), 1)):
            page = UploadPage()
            if error:
                page.selectors[uploader.TITLE_EDITOR_SELECTOR].wait_for = AsyncMock(side_effect=error)
            self.context.next_page = page
            self.context.close_error = OSError('cleanup failed')
            with patch.object(uploader.asyncio, 'sleep', new=AsyncMock()):
                result = self.upload()
            self.assertEqual(result[0], expected, result)
            self.assertEqual(page.selectors[uploader.PUBLISH_BUTTON_SELECTOR].click_count, int(error is None))
            with acquire_local_profile('baijiahao', 'Creator', 'chrome'):
                pass

    def test_injected_local_session_does_not_relaunch_or_close_owner(self):
        from utils.browser_session import BrowserSession
        self.context.next_page = UploadPage()
        app = uploader.BaiJiaHaoVideo('Title123456', self.video, [], None, thumbnail_path=self.cover)
        with patch.object(uploader.asyncio, 'sleep', new=AsyncMock()):
            asyncio.run(app.main(session=BrowserSession(browser=None, context=self.context, mode='local')))
        self.assertEqual(self.context.next_page.selectors[uploader.PUBLISH_BUTTON_SELECTOR].click_count, 1)
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.assertFalse(self.context.closed)

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

    def test_unknown_result_and_budget_exhaustion_do_not_retry_or_get_overwritten(self):
        import time
        import uploader.publish_timeout as timeout_module
        self.profile()
        for phase, expected in [('before',1), ('after',9), ('click-error',9)]:
            with self.subTest(phase=phase):
                page = UploadPage()
                self.context.next_page = page
                self.context.close_error = OSError('close failed')
                clock = SimpleNamespace(offset=0)
                fake_time = SimpleNamespace(monotonic=lambda: time.monotonic() + clock.offset)
                submit = page.selectors[uploader.PUBLISH_BUTTON_SELECTOR]
                async def click(**_):
                    submit.click_count += 1
                    if phase == 'click-error': raise TimeoutError('click may have been dispatched')
                    clock.offset = 1000
                submit.click = click
                original_goto = page.goto
                async def goto(url, **kwargs):
                    response = await original_goto(url, **kwargs)
                    if phase == 'before' and url == uploader.BAIJIAHAO_PUBLISH_URL:
                        clock.offset = 1000
                    return response
                page.goto = goto
                with patch.object(timeout_module, 'time', fake_time), patch.object(uploader.asyncio, 'sleep', new=AsyncMock()):
                    result = self.upload()
                self.assertEqual(result[0], expected, result)
                self.assertEqual(submit.click_count, int(phase != 'before'))

    def test_pre_submit_redirect_and_click_exception_preserve_login_stage(self):
        self.profile()
        for phase in ('before', 'click'):
            with self.subTest(phase=phase):
                page = UploadPage()
                self.context.next_page = page
                submit = page.selectors[uploader.PUBLISH_BUTTON_SELECTOR]
                async def redirect(*_, **__):
                    page.url = 'https://passport.baidu.com/login'
                    if phase == 'click': submit.click_count += 1
                    raise TimeoutError('redirect after browser action')
                if phase == 'before':
                    page.selectors[uploader.TITLE_EDITOR_SELECTOR].wait_for = redirect
                else:
                    submit.click = redirect
                with patch.object(uploader.asyncio, 'sleep', new=AsyncMock()):
                    result = self.upload()
                self.assertEqual(result[0], 10, result)
                self.assertEqual('publish_attempted=true' in result[2], phase == 'click')
                self.assertEqual(submit.click_count, int(phase == 'click'))

    def test_not_before_defers_submission_while_profile_remains_owned(self):
        from datetime import datetime, timedelta, timezone
        self.profile()
        page = UploadPage()
        self.context.next_page = page
        submit = page.selectors[uploader.PUBLISH_BUTTON_SELECTOR]
        target = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=2)
        observed = []
        async def click(**_):
            observed.append(datetime.now(timezone.utc))
            with self.assertRaisesRegex(RuntimeError, '占用'):
                with acquire_local_profile('baijiahao', 'Creator', 'chrome'): pass
            page.url = uploader.BAIJIAHAO_SUCCESS_URL_PREFIX
        submit.click = click
        # Only shorten platform upload-progress polling; the gate clock is real.
        original_sleep = asyncio.sleep
        async def fast_sleep(seconds):
            if seconds != 2: await original_sleep(seconds)
        with patch.object(uploader.asyncio, 'sleep', new=fast_sleep):
            result = self.upload('--not-before', target.isoformat().replace('+00:00', 'Z'))
        self.assertEqual(result[0], 0, result)
        self.assertEqual(len(observed), 1)
        self.assertGreaterEqual(observed[0], target)

    def test_invalid_effective_settings_and_missing_required_cover_stop_without_browser(self):
        for args in [('--account', '../unsafe'), ('--local-browser', 'firefox')]:
            self.assertEqual(self.cli('login', '--account','Creator', *args)[0], 2)
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', 'false'):
            self.assertEqual(self.cli('check', '--account','Creator')[0], 2)
        result = self.cli('upload-video','--account','Creator','--file',str(self.video),'--title','Title')
        self.assertEqual(result[0], 1, result)
        self.assertIn('--thumbnail', result[2])
        self.assertFalse(self.pw.chromium.persistent_calls)

    def test_primary_page_fault_is_preserved_if_followup_login_diagnostic_fails(self):
        self.profile()
        page = UploadPage()
        self.context.next_page = page
        broken = False
        original_locator = page.locator
        def locator(selector):
            if broken: raise OSError('secondary diagnostic failed')
            return original_locator(selector)
        page.locator = locator
        async def fail(**_):
            nonlocal broken
            broken = True
            raise PermissionError('primary title permission error')
        page.selectors[uploader.TITLE_EDITOR_SELECTOR].wait_for = fail
        result = self.upload()
        self.assertEqual(result[0], 1, result)
        self.assertIn('primary title permission error', result[2])
        self.assertNotIn('secondary diagnostic failed', result[2])

    def test_login_allows_manual_verification_in_same_owned_context(self):
        page = BackendPage(verification=True)
        self.context.next_page = page
        waits = []
        async def wait(ms):
            waits.append(ms)
            if len(waits) > 1:
                page.verification = False
        page.wait_for_timeout = wait
        result = self.cli('login', '--account','Creator')
        self.assertEqual(result[0], 0, result)
        self.assertEqual(len(self.pw.chromium.persistent_calls), 1)
        self.assertTrue(self.context.closed)

    def test_upload_progress_read_failure_does_not_become_success(self):
        self.profile()
        page = UploadPage()
        page.inner_text = AsyncMock(side_effect=OSError('progress page disconnected'))
        self.context.next_page = page
        ticks = iter(range(0, 100, 5))
        with patch.object(uploader, 'time', SimpleNamespace(monotonic=lambda: next(ticks))), patch.object(uploader.asyncio, 'sleep', new=AsyncMock()):
            result = self.upload()
        self.assertEqual(result[0], 1, result)
        self.assertIn('progress page disconnected', result[2])
        self.assertEqual(page.selectors[uploader.PUBLISH_BUTTON_SELECTOR].click_count, 0)
