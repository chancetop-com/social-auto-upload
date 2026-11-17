"""Kuaishou public CLI and uploader seams with real config/Profile/session ownership."""
import asyncio
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import conf
import sau_cli
from sau_commands import kuaishou as command
from tests.fakes import FakeContext, FakePlaywright
from tests.test_mlx_xhs_kuaishou import _UploadPage
from uploader.ks_uploader import main as uploader
from utils.local_profile import acquire_local_profile


class PlaywrightCM:
    def __init__(self, playwright): self.playwright = playwright
    async def __aenter__(self): return self.playwright
    async def __aexit__(self, *_): pass


class ProfileContext(FakeContext):
    def __init__(self):
        super().__init__()
        self.queue = []
        self.next_page = _UploadPage(final_url=uploader.KUAISHOU_UPLOAD_URL, ks_upload_button=True)
    async def new_page(self):
        self.new_page_calls += 1
        page = self.queue.pop(0) if self.queue else self.next_page
        self.pages.append(page)
        return page


class KuaishouProfilesTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.playwright = FakePlaywright()
        async def forbid_temporary_browser(**kwargs):
            raise AssertionError('Kuaishou must use its persistent Profile')
        self.playwright.chromium.launch = forbid_temporary_browser
        self.context = ProfileContext()
        self.playwright.chromium.persistent_context = self.context
        for key, value in {'BASE_DIR': self.root, 'LOCAL_CHROME_PATH': '', 'LOCAL_CHROME_HEADLESS': False, 'LOCAL_BROWSER': 'chrome'}.items():
            self.stack.enter_context(patch.object(conf, key, value, create=True))
        self.stack.enter_context(patch.dict(os.environ, {'MLX_API_TOKEN': '', 'ADSPOWER_API_KEY': '', 'HUMANIZE': '0'}))
        for module in (command, uploader):
            self.stack.enter_context(patch.object(module, 'async_playwright', lambda: PlaywrightCM(self.playwright)))
        self.video = self.root / 'video.mp4'
        self.video.write_bytes(b'fixture')
        self.image = self.root / 'image.png'
        self.image.write_bytes(b'fixture')
    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = sau_cli.main(['kuaishou', *args])
        return code, out.getvalue(), err.getvalue()
    def profile(self, kind='chrome'):
        with acquire_local_profile('kuaishou', 'Creator', kind, create=True) as profile:
            return profile.path
    def test_check_uses_selected_persistent_profile_and_ignores_legacy_json(self):
        profile = self.profile()
        legacy = self.root / 'cookies/kuaishou_Creator.json'
        legacy.parent.mkdir()
        legacy.write_text('broken old JSON')
        result = self.cli('check', '--account', 'Creator')
        self.assertEqual(result[0], 0, result)
        self.assertEqual(self.playwright.chromium.persistent_calls, [{
            'user_data_dir': str(profile), 'channel': 'chrome', 'headless': False, 'no_viewport': True}])
        self.assertTrue(self.context.closed)
        self.assertFalse(self.context.storage_state_calls)
        self.assertFalse(self.context.add_init_script_calls)
        self.assertEqual(legacy.read_text(), 'broken old JSON')

    def test_login_then_check_reuses_config_and_profile_without_identity_binding(self):
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', True), patch.object(conf, 'LOCAL_BROWSER', 'chromium', create=True):
            result = self.cli('login', '--account', 'Creator', '--headed')
            self.assertEqual(result[0], 0, result)
            result = self.cli('check', '--account', 'Creator', '--headed')
            self.assertEqual(result[0], 0, result)
        calls = self.playwright.chromium.persistent_calls
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(calls[0]['channel'], 'chromium')
        self.assertFalse(calls[0]['headless'])
        self.assertFalse((self.root / 'cookies').exists())
        self.assertFalse(self.context.storage_state_calls)

    def business_page(self, action):
        from tests.test_kuaishou_humanize import _page, _video_selectors, _note_selectors, _TypingLocator
        log = []
        editor = _TypingLocator('editor', log=log, initial='old')
        selectors = (_video_selectors if action == 'upload-video' else _note_selectors)(log, editor)
        return _page(selectors, log=log), editor

    def upload_args(self, action):
        return [action, '--account', 'Creator', '--title', 'Title', '--tags', 'one,two',
                *(['--file', str(self.video), '--desc', 'Description'] if action == 'upload-video'
                  else ['--images', str(self.image), '--note', 'Description'])]

    def test_both_media_entrypoints_probe_and_publish_in_one_selected_profile(self):
        from tests.test_kuaishou_humanize import _fast_clock, PUBLISH
        self.profile('chromium')
        for action in ['upload-video', 'upload-note']:
            with self.subTest(action=action), _fast_clock():
                page, editor = self.business_page(action)
                probe = _UploadPage(final_url=uploader.KUAISHOU_UPLOAD_URL, ks_upload_button=True)
                self.context.queue = [probe, page]
                before = len(self.playwright.chromium.persistent_calls)
                result = self.cli(*self.upload_args(action), '--local-browser', 'chromium', '--headless')
                self.assertEqual(result[0], 0, result)
                self.assertEqual(len(self.playwright.chromium.persistent_calls), before + 1)
                call = self.playwright.chromium.persistent_calls[-1]
                self.assertEqual(call['channel'], 'chromium')
                self.assertTrue(call['headless'])
                self.assertEqual(page.get_by_text('发布', exact=True).click_count, 1)
                self.assertEqual(editor.buffer, 'Description\n#one #two ')
                self.assertEqual(len(probe.goto_calls), 1)
                self.assertFalse(probe.closed)
                self.assertTrue(self.context.closed)
                self.assertFalse(self.context.storage_state_calls)

    def test_probe_distinguishes_login_verification_and_faults_across_actions(self):
        self.profile()
        cases = [
            (_UploadPage(final_url='https://passport.kuaishou.com/pc/account/login/'), 10, 'login'),
            (_UploadPage(final_url='https://cp.kuaishou.com/verify/captcha'), 10, 'verification'),
            (_UploadPage(final_url=uploader.KUAISHOU_UPLOAD_URL, ks_login_anchor=True), 10, 'login'),
            (_UploadPage(final_url=uploader.KUAISHOU_UPLOAD_URL, status=403), 1, 'HTTP 403'),
            (_UploadPage(final_url=uploader.KUAISHOU_UPLOAD_URL, status=503), 1, 'HTTP 503'),
            (_UploadPage(final_url=uploader.KUAISHOU_UPLOAD_URL, goto_error=TimeoutError('network')), 1, 'network'),
            (_UploadPage(final_url=uploader.KUAISHOU_UPLOAD_URL, ks_upload_wait_error=TimeoutError('DOM missing')), 1, '无法确认'),
        ]
        for action in ['check', 'upload-video', 'upload-note']:
            for page, expected, diagnostic in cases:
                with self.subTest(action=action, diagnostic=diagnostic):
                    self.context.next_page = page
                    args = ['check', '--account', 'Creator'] if action == 'check' else self.upload_args(action)
                    result = self.cli(*args)
                    self.assertEqual(result[0], expected, result)
                    self.assertIn(diagnostic, result[2])
                    self.assertNotIn('publish_attempted=true', result[2])
                    self.assertTrue(self.context.closed)

    def test_post_submit_login_and_verification_preserve_signal_without_resubmitting(self):
        from tests.test_kuaishou_humanize import _fast_clock
        self.profile()
        for action in ['upload-video', 'upload-note']:
            for target, diagnostic in [('https://passport.kuaishou.com/login/', 'login'), ('https://cp.kuaishou.com/captcha', 'verification')]:
                with self.subTest(action=action, diagnostic=diagnostic), _fast_clock():
                    page, _ = self.business_page(action)
                    clock = [10.0]
                    original_wait = page.wait_for_url
                    async def wait(url, **kwargs):
                        if url == uploader.KUAISHOU_MANAGE_URL_PATTERN:
                            page.url = target
                            clock[0] += 2000
                            raise TimeoutError('redirect after submission')
                        await original_wait(url, **kwargs)
                    page.wait_for_url = wait
                    self.context.queue = [self.context.next_page, page]
                    self.context.close_error = OSError('cleanup failed')
                    with patch('time.monotonic', lambda: clock[0]):
                        result = self.cli(*self.upload_args(action))
                    self.assertEqual(result[0], 10, result)
                    self.assertIn(diagnostic, result[2])
                    self.assertIn('publish_attempted=true', result[2])
                    self.assertEqual(page.get_by_text('发布', exact=True).click_count, 1)

    def test_business_navigation_redirect_after_timeout_is_login_required(self):
        self.profile()
        for action in ['upload-video', 'upload-note']:
            with self.subTest(action=action):
                page, _ = self.business_page(action)
                async def redirect(*_, **__):
                    page.url = 'https://passport.kuaishou.com/login/'
                    raise TimeoutError('redirect while loading')
                page.wait_for_url = redirect
                self.context.queue = [self.context.next_page, page]
                result = self.cli(*self.upload_args(action))
                self.assertEqual(result[0], 10, result)
                self.assertNotIn('publish_attempted=true', result[2])
                self.assertEqual(page.get_by_text('发布', exact=True).click_count, 0)

    def test_missing_profile_never_opens_browser_or_imports_old_json(self):
        legacy = self.root / 'cookies/kuaishou_Creator.json'
        legacy.parent.mkdir()
        legacy.write_text('{"cookies": []}')
        for action in ['check', 'upload-video', 'upload-note']:
            args = ['check', '--account', 'Creator'] if action == 'check' else self.upload_args(action)
            result = self.cli(*args)
            self.assertEqual(result[0], 10, result)
        self.assertFalse(self.playwright.chromium.persistent_calls)
        self.assertEqual(legacy.read_text(), '{"cookies": []}')

    def test_configuration_precedence_isolation_custom_path_and_no_fallback(self):
        import plistlib
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', True):
            self.assertEqual(self.cli('login', '--account', 'Creator', '--headed')[0], 0)
            self.assertEqual(self.cli('check', '--account', 'Creator')[0], 0)
            self.assertEqual(self.cli('check', '--account', 'Creator', '--local-browser', 'chromium')[0], 10)
            self.assertEqual(self.cli('login', '--account', 'Creator', '--local-browser', 'chromium')[0], 0)
        executable = self.root / 'Custom.app/Contents/MacOS/browser'
        executable.parent.mkdir(parents=True)
        executable.write_text('fixture')
        executable.chmod(0o755)
        (executable.parent.parent / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleName': 'Chromium', 'CFBundleIdentifier': 'org.chromium.Chromium', 'CFBundleExecutable': 'browser', 'CFBundleShortVersionString': '123.1'}))
        with patch('utils.local_browser.sys.platform', 'darwin'), patch.object(conf, 'LOCAL_CHROME_PATH', str(executable)):
            self.assertEqual(self.cli('check', '--account', 'Creator', '--local-browser', 'chrome')[0], 0)
            self.playwright.chromium.launch_error = RuntimeError('launch failure')
            result = self.cli('check', '--account', 'Creator')
        self.assertEqual(result[0], 1, result)
        self.assertIn('launch failure', result[2])
        calls = self.playwright.chromium.persistent_calls
        self.assertEqual(len(calls), 5)
        self.assertEqual([x['headless'] for x in calls], [False, True, True, False, False])
        self.assertEqual(calls[0]['user_data_dir'], calls[1]['user_data_dir'])
        self.assertNotEqual(calls[1]['user_data_dir'], calls[2]['user_data_dir'])
        self.assertEqual(calls[2]['user_data_dir'], calls[3]['user_data_dir'])
        self.assertEqual(calls[3]['executable_path'], str(executable))

    def test_optional_missing_config_defaults_to_headed_chrome(self):
        with patch.dict(conf.__dict__):
            for key in ['LOCAL_CHROME_PATH', 'LOCAL_CHROME_HEADLESS', 'LOCAL_BROWSER']:
                conf.__dict__.pop(key, None)
            self.assertEqual(self.cli('login', '--account', 'Creator')[0], 0)
        call = self.playwright.chromium.persistent_calls[0]
        self.assertEqual(call['channel'], 'chrome')
        self.assertFalse(call['headless'])

    def test_reset_is_exact_browser_independent_and_refuses_occupied_profile(self):
        chrome, chromium = self.profile(), self.profile('chromium')
        history = self.root / 'old-result.json'
        history.write_text('original work')
        with patch.object(conf, 'LOCAL_CHROME_PATH', '/missing/binary'):
            with acquire_local_profile('kuaishou', 'Creator', 'chrome'):
                self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')[0], 1)
            self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')[0], 0)
            self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')[0], 0)
        self.assertFalse(chrome.exists())
        self.assertTrue(chromium.exists())
        self.assertEqual(history.read_text(), 'original work')
        self.assertFalse(self.playwright.chromium.persistent_calls)

    def test_setup_cookie_auth_and_direct_uploads_share_alias_and_explicit_false(self):
        from tests.test_kuaishou_humanize import _fast_clock
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', True), _fast_clock():
            self.assertTrue(asyncio.run(uploader.ks_setup(account_name='Creator', handle=True)))
            self.assertTrue(asyncio.run(uploader.cookie_auth(account_name='Creator', headless=False)))
            result = asyncio.run(uploader.get_ks_cookie(account_name='Creator', headless=False))
            self.assertTrue(result['success'])
            for action in ['upload-video', 'upload-note']:
                page, _ = self.business_page(action)
                self.context.queue = [self.context.next_page, page]
                legacy = self.root / 'cookies/kuaishou_Creator.json'
                common = dict(tags=[], publish_date=0, account_file=legacy, headless=False)
                app = (uploader.KSVideo(title='Title', file_path=self.video, **common) if action == 'upload-video'
                       else uploader.KSNote(title='Title', note='Body', image_paths=[self.image], **common))
                asyncio.run(app.main())
                self.assertEqual(page.get_by_text('发布', exact=True).click_count, 1)
        calls = self.playwright.chromium.persistent_calls
        self.assertEqual([x['headless'] for x in calls], [True, False, False, False, False])
        self.assertEqual(len({x['user_data_dir'] for x in calls}), 1)
        self.assertFalse((self.root / 'cookies').exists())

    def test_injected_local_sessions_remain_owned_by_caller(self):
        from tests.test_kuaishou_humanize import _fast_clock
        from utils.browser_session import BrowserSession
        for action in ['upload-video', 'upload-note']:
            with _fast_clock():
                page, _ = self.business_page(action)
                self.context.queue = [page]
                common = dict(tags=[], publish_date=0, account_file=None, account_name='Creator')
                app = (uploader.KSVideo(title='Title', file_path=self.video, **common) if action == 'upload-video'
                       else uploader.KSNote(title='Title', note='Body', image_paths=[self.image], **common))
                asyncio.run(app.main(session=BrowserSession(browser=None, context=self.context, mode='local')))
                self.assertEqual(page.get_by_text('发布', exact=True).click_count, 1)
                self.assertFalse(self.context.closed)
                self.assertFalse(self.playwright.chromium.persistent_calls)

    def test_outcomes_survive_cleanup_failure_and_submit_is_not_retried(self):
        from tests.test_kuaishou_humanize import _fast_clock
        self.profile()
        for action in ['upload-video', 'upload-note']:
            for stage, expected in [('success', 0), ('prepare', 1), ('submit', 9)]:
                with self.subTest(action=action, stage=stage), _fast_clock():
                    page, _ = self.business_page(action)
                    if stage == 'prepare':
                        page.locator("button[class^='_upload-btn']")._click_error = ValueError('upload failed')
                    if stage == 'submit':
                        page.get_by_text('发布', exact=True)._click_error = TimeoutError('possibly submitted')
                    self.context.queue = [self.context.next_page, page]
                    self.context.close_error = OSError('close failed')
                    result = self.cli(*self.upload_args(action))
                    self.assertEqual(result[0], expected, result)
                    self.assertEqual(page.get_by_text('发布', exact=True).click_count, 0 if stage == 'prepare' else 1)
                    with acquire_local_profile('kuaishou', 'Creator', 'chrome'):
                        pass

    def test_initialization_failure_cancellation_and_hung_closes_release_profile(self):
        self.profile()
        for action in ['login', 'check', 'upload-video', 'upload-note']:
            for error in [RuntimeError('navigation failed'), asyncio.CancelledError()]:
                with self.subTest(action=action, error=type(error).__name__):
                    self.context.next_page = _UploadPage(final_url=uploader.KUAISHOU_UPLOAD_URL, goto_error=error)
                    args = [action, '--account', 'Creator'] if action in ['login', 'check'] else self.upload_args(action)
                    if isinstance(error, asyncio.CancelledError):
                        with self.assertRaises(asyncio.CancelledError): self.cli(*args)
                    else:
                        result = self.cli(*args)
                        self.assertEqual(result[0], 1, result)
                    self.assertTrue(self.context.closed)
                    with acquire_local_profile('kuaishou', 'Creator', 'chrome'):
                        pass
        async def hang(): await asyncio.Event().wait()
        self.context.next_page = _UploadPage(final_url=uploader.KUAISHOU_UPLOAD_URL, ks_upload_button=True)
        self.context.next_page.close = hang
        self.context.close = hang
        with patch('utils.local_browser_session.CLOSE_TIMEOUT_SECONDS', 0.02):
            args = sau_cli.build_parser().parse_args(['kuaishou', 'check', '--account', 'Creator'])
            self.assertEqual(asyncio.run(asyncio.wait_for(sau_cli.dispatch(args), 1)), 0)
        with acquire_local_profile('kuaishou', 'Creator', 'chrome'):
            pass

    def test_managed_providers_keep_ownership_and_only_resolve_headless(self):
        from tests.fakes import FakeAdspowerClient, FakeMultiloginClient, FakeBrowser
        from tests.test_kuaishou_humanize import _fast_clock
        for client_type, token_name, client_symbol in [(FakeAdspowerClient, 'ADSPOWER_API_KEY', 'AdspowerClient'), (FakeMultiloginClient, 'MLX_API_TOKEN', 'MultiloginClient')]:
            for action in ['check', 'upload-video', 'upload-note']:
                for flags, expected in [([], True), (['--headed'], False)]:
                    with self.subTest(provider=token_name, action=action, flags=flags), _fast_clock():
                        client = client_type()
                        browser = FakeBrowser([self.context])
                        self.playwright.chromium.queue_connect_browser(browser)
                        probe = _UploadPage(final_url=uploader.KUAISHOU_UPLOAD_URL, ks_upload_button=True)
                        self.context.queue = [probe]
                        if action == 'check': args = ['check']
                        else:
                            page, _ = self.business_page(action)
                            self.context.queue.append(page)
                            args = self.upload_args(action)
                        with patch.dict(os.environ, {token_name: 'test-only-token'}), patch.object(conf, 'LOCAL_CHROME_HEADLESS', True), patch.object(conf, 'LOCAL_CHROME_PATH', '/unused/invalid'), patch.object(conf, 'LOCAL_BROWSER', 'invalid', create=True), patch('sau_commands.browser.' + client_symbol, return_value=client):
                            result = self.cli(*args, '--profile-id', 'profile', '--folder-id', 'folder', '--local-browser', 'invalid', *flags)
                        self.assertEqual(result[0], 0, result)
                        self.assertEqual(client.start_calls[0][-1], expected)
                        self.assertEqual(client.stop_calls, ['profile'])
                        self.assertEqual(browser.close_calls, 1)
                        self.assertFalse(self.context.closed)
        self.assertFalse(self.playwright.chromium.persistent_calls)
        self.assertFalse(self.context.storage_state_calls)
        self.assertFalse((self.root / 'browser_profiles').exists())

    def test_managed_login_reset_and_rate_limit_keep_contract(self):
        from tests.fakes import FakeAdspowerClient
        from utils.errors import RateLimitedError
        client = FakeAdspowerClient(start_error=RateLimitedError('429 no retry'))
        with patch.dict(os.environ, {'ADSPOWER_API_KEY': 'test-token'}), patch('sau_commands.browser.AdspowerClient', return_value=client):
            self.assertEqual(self.cli('login', '--account', 'Creator')[0], 1)
            self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')[0], 2)
            self.assertFalse(client.calls)
            self.assertEqual(self.cli('check', '--profile-id', 'profile')[0], 11)
        self.assertEqual(len(client.start_calls), 1)
        self.assertFalse(client.stop_calls)

    def test_qr_login_refreshes_and_verifies_in_same_profile_then_cleans_artifact(self):
        import base64
        import segno
        from tests.fakes_xhs_dom import RecordingLocator
        from tests.test_kuaishou_humanize import _fast_clock
        image = io.BytesIO()
        segno.make('fixture-login').save(image, kind='png', scale=4)
        data_url = 'data:image/png;base64,' + base64.b64encode(image.getvalue()).decode()
        page = _UploadPage(final_url=uploader.KUAISHOU_LOGIN_URL)
        form = RecordingLocator('form', children={'div.qr-login img[alt="qrcode"]': RecordingLocator('qr', attributes={'src': data_url})})
        refresh = RecordingLocator('refresh')
        selectors = {'main#login-form': form, 'div.qrcode-status.qrcode-status-timeout': RecordingLocator('expired'), 'p.qrcode-refresh': refresh}
        page.locator = lambda selector: selectors[selector]
        self.context.queue = [page, self.context.next_page]
        qr_paths = []
        async def on_qr(payload):
            path = Path(payload['image_path'])
            self.assertTrue(path.exists())
            qr_paths.append(path)
            with self.assertRaisesRegex(RuntimeError, '占用'):
                with acquire_local_profile('kuaishou', 'Creator', 'chrome'): pass
            if len(qr_paths) == 2: page.url = uploader.KUAISHOU_UPLOAD_URL
        with _fast_clock(), redirect_stdout(io.StringIO()):
            result = asyncio.run(uploader.get_ks_cookie(account_name='Creator', qrcode_callback=on_qr, max_checks=3))
        self.assertTrue(result['success'])
        self.assertEqual(result['qrcode']['image_path'], str(qr_paths[-1]))
        self.assertEqual(result['current_url'], uploader.KUAISHOU_UPLOAD_URL)
        self.assertEqual(refresh.click_count, 1)
        self.assertEqual(len(qr_paths), 2)
        self.assertTrue(all(not path.exists() for path in qr_paths))
        self.assertEqual(len(self.playwright.chromium.persistent_calls), 1)
        self.assertFalse(self.context.storage_state_calls)

    def test_login_verification_redirect_with_missing_qr_preserves_reason(self):
        page = _UploadPage(final_url='https://passport.kuaishou.com/captcha')
        def missing(selector): raise RuntimeError('QR unavailable during verification')
        page.locator = missing
        self.context.next_page = page
        result = self.cli('login', '--account', 'Creator')
        self.assertEqual(result[0], 10, result)
        self.assertIn('verification', result[2])
        self.assertTrue(self.context.closed)

    def test_not_before_and_submission_hold_same_profile_until_cleanup(self):
        from datetime import datetime, timedelta, timezone
        from types import SimpleNamespace
        self.profile()
        for action in ['upload-video', 'upload-note']:
            page, _ = self.business_page(action)
            probe = _UploadPage(final_url=uploader.KUAISHOU_UPLOAD_URL, ks_upload_button=True)
            original_goto = probe.goto
            async def probe_locked(*args, **kwargs):
                with self.assertRaisesRegex(RuntimeError, '占用'):
                    with acquire_local_profile('kuaishou', 'Creator', 'chrome'): pass
                return await original_goto(*args, **kwargs)
            probe.goto = probe_locked
            submit = page.get_by_text('发布', exact=True)
            original_click = submit.click
            submitted = []
            async def click(**kwargs):
                with self.assertRaisesRegex(RuntimeError, '占用'):
                    with acquire_local_profile('kuaishou', 'Creator', 'chrome'): pass
                submitted.append(datetime.now(timezone.utc))
                await original_click(**kwargs)
            submit.click = click
            self.context.queue = [probe, page]
            target = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=1)
            async def short_sleep(seconds): await asyncio.sleep(min(seconds, 0.001))
            with patch.object(uploader, 'asyncio', SimpleNamespace(sleep=short_sleep)):
                result = self.cli(*self.upload_args(action), '--not-before', target.isoformat().replace('+00:00', 'Z'))
            self.assertEqual(result[0], 0, result)
            self.assertEqual(len(submitted), 1)
            self.assertGreaterEqual(submitted[0], target)
            with acquire_local_profile('kuaishou', 'Creator', 'chrome'): pass

    def test_invalid_configuration_alias_and_external_cdp_login_fail_without_launch(self):
        from utils.errors import UsageError
        for flag in [('login', '--account', '../escape'), ('check', '--account', 'Creator', '--local-browser', 'invalid')]:
            result = self.cli(*flag)
            self.assertEqual(result[0], 2, result)
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', 'false'):
            self.assertEqual(self.cli('check', '--account', 'Creator')[0], 2)
        with self.assertRaises(UsageError):
            asyncio.run(uploader.get_ks_cookie(account_name='Creator', cdp_url='http://unused'))
        self.assertFalse(self.playwright.chromium.persistent_calls)
        self.assertFalse((self.root / 'browser_profiles').exists())
