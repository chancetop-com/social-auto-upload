"""Hupu public CLI with real Profile orchestration and external browser fakes."""
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
from sau_commands import hupu as command
from tests.fakes import FakeContext, FakePage, FakePlaywright
from tests.fakes_xhs_dom import RecordingLocator, RecordingKeyboard
from uploader.hupu_uploader import main as uploader
from utils.local_profile import acquire_local_profile


def upload_page():
    from tests.test_hupu_humanize import _publish_page, TITLE_PLACEHOLDER, DESC_PLACEHOLDER
    from tests.fakes_xhs_dom import FakeFileChooser
    page, targets = _publish_page([])
    page._selectors.update({
        'role:button:上传视频': RecordingLocator('upload'),
        f'placeholder:{TITLE_PLACEHOLDER}': RecordingLocator('title'),
        f'placeholder:{DESC_PLACEHOLDER}': RecordingLocator('description'),
        'span': RecordingLocator('cover'),
    })
    page.file_chooser = FakeFileChooser()
    async def submit(**_):
        targets['publish'].click_count += 1
        page.url = 'https://bbs.hupu.com/123456.html'
    targets['publish'].click = submit
    page.targets = targets
    return page


class PlaywrightCM:
    def __init__(self, playwright): self.playwright = playwright
    async def __aenter__(self): return self.playwright
    async def __aexit__(self, *_): pass


class BackendPage(FakePage):
    def __init__(self, *, url=None, status=200, error=None, anchor=True):
        super().__init__()
        self.target_url, self.status, self.error, self.anchor = url, status, error, anchor
    async def goto(self, url, **kwargs):
        await super().goto(url, **kwargs)
        self.url = self.target_url or url
        if self.error: raise self.error
        return SimpleNamespace(status=self.status)
    async def wait_for_timeout(self, _): pass
    def locator(self, selector): return RecordingLocator(selector, count=0)
    def get_by_role(self, role, name=None):
        return RecordingLocator(name or role, count=int(self.anchor and name == '上传视频'))
    async def close(self):
        raise AssertionError('The persistent context owns local pages')


class BackendContext(FakeContext):
    def __init__(self):
        super().__init__()
        self.next_page = BackendPage()
    async def new_page(self):
        self.pages.append(self.next_page)
        return self.next_page


class HupuProfilesTests(unittest.TestCase):
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
            try: code = sau_cli.main(['hupu', *args])
            except SystemExit as error: code = error.code
        return code, out.getvalue(), err.getvalue()
    def profile(self, kind='chrome', account='Creator'):
        with acquire_local_profile('hupu', account, kind, create=True) as profile:
            return profile.path
    def upload(self, *args):
        return self.cli('upload-video', '--account', 'Creator', '--file', str(self.video), '--title', 'A video title', '--thumbnail', str(self.cover), *args)

    def test_login_check_reuse_profile_without_cookie_or_context_replacement(self):
        legacy = self.root / 'cookies/hupu_Creator.json'
        legacy.parent.mkdir()
        legacy.write_text('malformed legacy state')
        result = self.cli('login', '--account', 'Creator')
        self.assertEqual(result[0], 0, result)
        self.assertEqual(self.cli('check', '--account', 'Creator')[0], 0)
        self.assertEqual(self.pw.chromium.persistent_calls, [dict(
            user_data_dir=str(self.root / 'browser_profiles/chrome/hupu/Creator'),
            channel='chrome', headless=False, no_viewport=True)] * 2)
        self.assertTrue(self.context.closed)
        self.assertFalse(self.context.storage_state_calls)

        self.assertFalse(self.context.add_init_script_calls)
        self.assertEqual(legacy.read_text(), 'malformed legacy state')

    def test_login_verification_and_faults_keep_distinct_exit_codes(self):
        self.assertEqual(self.cli('check', '--account', 'Creator')[0], 10)
        self.profile()
        for page, code in [
            (BackendPage(url='https://passport.hupu.com/v2/login'), 10),
            (BackendPage(url='https://passport.hupu.com/verify'), 10),
            (BackendPage(status=403), 1), (BackendPage(status=503), 1),
            (BackendPage(anchor=False), 1), (BackendPage(error=OSError('network failed')), 1),
            (BackendPage(url='https://not-hupu.com', anchor=True), 1),
            (BackendPage(url='https://hupu.com.attacker.invalid', anchor=True), 1),
            (BackendPage(url='https://passport.hupu.com/login', error=TimeoutError('redirect')), 10),
        ]:
            with self.subTest(page=vars(page)):
                self.context.next_page = page
                result = self.cli('check', '--account', 'Creator')
                self.assertEqual(result[0], code, result)
                if 'verify' in str(page.target_url):
                    self.assertIn('reason=verification', result[2])

    def test_video_preflight_and_business_share_selected_profile_and_file_choosers(self):
        self.profile('chromium')
        page = upload_page()
        self.context.next_page = page
        result = self.upload('--local-browser', 'chromium', '--headless')
        self.assertEqual(result[0], 0, result)
        self.assertEqual(len(self.pw.chromium.persistent_calls), 1)
        self.assertEqual(self.pw.chromium.persistent_calls[0]['channel'], 'chromium')
        self.assertEqual(page.file_chooser.files, [str(self.video), str(self.cover)])
        self.assertEqual(page.targets['publish'].click_count, 1)
        self.assertTrue(self.context.closed)
        self.assertFalse(self.context.storage_state_calls)

    def test_qq_popup_login_proves_business_state_and_cleans_temporary_qr(self):
        import base64
        page = BackendPage(url=uploader.HUPU_LOGIN_URL, anchor=False)
        popup = BackendPage(url='https://graph.qq.com/oauth2.0/authorize')
        popup.url = popup.target_url
        qr = RecordingLocator('QR')
        qr.get_attribute = AsyncMock(return_value='https://qq.invalid/qr.png')
        popup.frames = [SimpleNamespace(url='https://xui.ptlogin2.qq.com/', locator=lambda _: qr)]
        qq = RecordingLocator('QQ')
        async def open_popup(**_): self.context.pages.append(popup)
        qq.click = open_popup
        page.get_by_role = lambda role, name=None: qq if name == 'qq QQ登录' else RecordingLocator(name or role, count=int(page.anchor))
        self.context.next_page = page
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
        self.context.request = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(body=AsyncMock(return_value=png))))
        paths = []
        def scan(payload):
            paths.append(Path(payload['image_path']))
            self.assertTrue(paths[-1].exists())
            popup.url = uploader.HUPU_HOME_URL
            page.target_url, page.anchor = uploader.HUPU_PUBLISH_URL, True
        with patch.object(uploader.asyncio, 'sleep', new=AsyncMock()):
            result = asyncio.run(command.login_hupu_account('Creator', qrcode_callback=scan))
        self.assertTrue(result['success'])
        self.assertEqual(len(self.pw.chromium.persistent_calls), 1)
        self.assertTrue(paths)
        self.assertFalse(paths[0].exists())
        self.assertFalse(self.context.storage_state_calls)
        self.assertTrue(self.context.closed)

    def test_redirects_before_and_after_submit_keep_stage_and_verification(self):
        from tests.test_hupu_humanize import TITLE_PLACEHOLDER
        self.profile()
        for phase in ('before', 'click', 'after'):
            with self.subTest(phase=phase):
                page = upload_page()
                self.context.next_page = page
                submit = page.targets['publish']
                async def redirect(*_, **__):
                    page.url = 'https://passport.hupu.com/verify'
                    if phase != 'before': submit.click_count += 1
                    if phase != 'after': raise TimeoutError('redirect during browser action')
                if phase == 'before':
                    page._selectors[f'placeholder:{TITLE_PLACEHOLDER}'].wait_for = redirect
                else:
                    submit.click = redirect
                original_wait = page.wait_for_timeout
                async def bounded_wait(ms):
                    if '/verify' in page.url:
                        raise TimeoutError('verification observation')
                    await original_wait(ms)
                page.wait_for_timeout = bounded_wait
                self.context.close_error = OSError('close failed')
                result = self.upload()
                self.assertEqual(result[0], 10, result)
                self.assertIn('reason=verification', result[2])
                self.assertEqual('publish_attempted=true' in result[2], phase != 'before')
                self.assertEqual(submit.click_count, int(phase != 'before'))

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
        self.assertTrue(all(call['user_data_dir'].endswith('/chromium/hupu/Creator') for call in self.pw.chromium.persistent_calls))


    def test_reset_exact_profile_without_binary_and_protects_lease_history_and_old_state(self):
        chrome, chromium = self.profile(), self.profile('chromium')
        old = self.root / 'old.json'; old.write_text('old login state')
        history = self.root / 'result.json'; history.write_text('historical work')
        with patch.object(conf, 'LOCAL_CHROME_PATH', '/missing/binary'):
            with acquire_local_profile('hupu', 'Creator', 'chrome'):
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
        args = sau_cli.build_parser().parse_args(['hupu', 'check', '--account', 'Creator'])
        with patch('utils.local_browser_session.CLOSE_TIMEOUT_SECONDS', 0.02):
            self.assertEqual(asyncio.run(asyncio.wait_for(sau_cli.dispatch(args), 1)), 0)
        with acquire_local_profile('hupu', 'Creator', 'chrome'):
            pass


    def test_initialization_failures_remain_faults_and_release_owned_context(self):
        self.profile()
        for action in ('login', 'check', 'upload-video'):
            self.context.next_page = BackendPage(error=OSError('navigation failed'))
            result = self.upload() if action == 'upload-video' else self.cli(action, '--account', 'Creator')
            self.assertEqual(result[0], 1, result)
            self.assertIn('navigation failed', result[2])
            self.assertTrue(self.context.closed)
            with acquire_local_profile('hupu', 'Creator', 'chrome'):
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

    def test_requested_cover_fault_stops_before_publish(self):
        self.profile()
        page = upload_page()
        self.context.next_page = page
        original = page.file_chooser.set_files
        async def set_files(path, **kwargs):
            if str(path).endswith('.png'): raise PermissionError('cover unreadable')
            await original(path, **kwargs)
        page.file_chooser.set_files = set_files
        result = self.upload()
        self.assertEqual(result[0], 1, result)
        self.assertIn('cover unreadable', result[2])
        self.assertEqual(page.targets['publish'].click_count, 0)

    def test_direct_setup_probe_and_upload_use_alias_and_explicit_false(self):
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', True):
            self.assertTrue(asyncio.run(uploader.hupu_setup(account_name='Creator', handle=True)))
            self.assertTrue(asyncio.run(uploader.cookie_auth('/missing/hupu_Creator.json', headless=False)))
            self.context.next_page = upload_page()
            app = uploader.HuPuVideo('Video title', self.video, [], account_name='Creator', headless=False)
            asyncio.run(app.main())
        calls = self.pw.chromium.persistent_calls
        self.assertEqual([call['headless'] for call in calls], [True, False, False])
        self.assertEqual(len({call['user_data_dir'] for call in calls}), 1)
        self.assertFalse((self.root / 'cookies').exists())

    def test_injected_local_session_preserves_context_ownership(self):
        from utils.browser_session import BrowserSession
        page = upload_page()
        self.context.next_page = page
        app = uploader.HuPuVideo('Video title', self.video, [], None)
        asyncio.run(app.main(session=BrowserSession(browser=None, context=self.context, mode='local')))
        self.assertEqual(page.targets['publish'].click_count, 1)
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.assertFalse(self.context.closed)

    def test_budget_unknown_and_success_survive_cleanup_failure(self):
        import time
        import uploader.publish_timeout as timeout_module
        self.profile()
        for phase, expected in [('before',1), ('after',9), ('click-error',9), ('success',0)]:
            with self.subTest(phase=phase):
                page = upload_page()
                self.context.next_page = page
                self.context.close_error = OSError('close failed')
                clock = SimpleNamespace(offset=0)
                fake_time = SimpleNamespace(monotonic=lambda: time.monotonic() + clock.offset)
                submit = page.targets['publish']
                async def click(**_):
                    submit.click_count += 1
                    if phase == 'click-error': raise TimeoutError('click may have been dispatched')
                    if phase == 'success': page.url = 'https://bbs.hupu.com/123456.html'
                    else: clock.offset = 1000
                submit.click = click
                original_goto = page.goto
                async def goto(url, **kwargs):
                    response = await original_goto(url, **kwargs)
                    if phase == 'before' and len(page.goto_calls) > 1: clock.offset = 1000
                    return response
                page.goto = goto
                with patch.object(timeout_module, 'time', fake_time):
                    result = self.upload()
                self.assertEqual(result[0], expected, result)
                self.assertEqual(submit.click_count, int(phase != 'before'))

    def test_not_before_holds_profile_until_one_submission(self):
        from datetime import datetime, timedelta, timezone
        self.profile()
        page = upload_page()
        self.context.next_page = page
        target = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=2)
        observed = []
        async def submit(**_):
            observed.append(datetime.now(timezone.utc))
            with self.assertRaisesRegex(RuntimeError, '占用'):
                with acquire_local_profile('hupu', 'Creator', 'chrome'): pass
            page.url = 'https://bbs.hupu.com/123456.html'
        page.targets['publish'].click = submit
        result = self.upload('--not-before', target.isoformat().replace('+00:00','Z'))
        self.assertEqual(result[0], 0, result)
        self.assertEqual(len(observed), 1)
        self.assertGreaterEqual(observed[0], target)

    def test_relogin_same_alias_accepts_new_business_identity_without_legacy_binding(self):
        for identity in ('account-a', 'account-b'):
            page = BackendPage()
            page.identity = identity
            self.context.next_page = page
            result = self.cli('login', '--account', 'Creator')
            self.assertEqual(result[0], 0, result)
        calls = self.pw.chromium.persistent_calls
        self.assertEqual(calls[0]['user_data_dir'], calls[1]['user_data_dir'])
        self.assertFalse(self.context.storage_state_calls)

    def test_managed_upload_retains_ignored_option_log_and_provider_ownership(self):
        from loguru import logger
        from tests.fakes import FakeAdspowerClient, FakeBrowser
        page = upload_page()
        self.context.next_page = page
        client = FakeAdspowerClient()
        browser = FakeBrowser([self.context], allow_new_context=False)
        self.pw.chromium.queue_connect_browser(browser)
        messages = []
        sink = logger.add(lambda message: messages.append(str(message)))
        try:
            with patch.dict(os.environ, {'ADSPOWER_API_KEY':'test-only-token'}), patch.object(conf, 'LOCAL_CHROME_PATH','/missing/ignored'), patch.object(conf, 'LOCAL_BROWSER','invalid-ignored',create=True), patch('sau_commands.browser.AdspowerClient', return_value=client):
                result = self.upload('--profile-id','profile','--headed','--local-browser','chromium')
        finally:
            logger.remove(sink)
        self.assertEqual(result[0],0,result)
        self.assertEqual(page.targets['publish'].click_count,1)
        self.assertEqual(client.stop_calls,['profile'])
        self.assertEqual(browser.close_calls,1)
        self.assertFalse(self.context.closed)
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.assertFalse((self.root/'browser_profiles').exists())
        self.assertTrue(any('ignored=launch_kwargs, context_setup' in line for line in messages), messages)
