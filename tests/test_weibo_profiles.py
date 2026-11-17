"""Weibo CLI → real configuration/Profile/session with external browser fakes."""
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
from sau_commands import weibo as command
from tests.fakes import FakeContext, FakePage, FakePlaywright
from tests.fakes_xhs_dom import RecordingLocator, RecordingKeyboard
from uploader.weibo_uploader import main as uploader
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
        self.url = self.target_url or uploader.WEIBO_HOME_URL
        if self.error: raise self.error
        return SimpleNamespace(status=self.status)
    async def wait_for_timeout(self, _): pass
    def locator(self, selector):
        present = (self.anchor and selector in uploader.WEIBO_LOGIN_POSITIVE_SELECTORS) or (self.verification and selector == 'text="安全验证"')
        return RecordingLocator(selector, count=int(present))
    def get_by_text(self, text, **_):
        return RecordingLocator(text, count=int(self.login and text == '登录'))
    async def close(self):
        raise AssertionError('Local pages are owned by the persistent context')


class PopupInfo:
    def __init__(self, value): self.result = value
    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass
    @property
    def value(self):
        async def resolve(): return self.result
        return resolve()


class UploadPage(BackendPage):
    def __init__(self):
        super().__init__()
        from tests import test_weibo_humanize as dom
        self.keyboard = RecordingKeyboard()
        self.selectors = {selector: RecordingLocator(selector) for selector in (
            'span', 'role:button:上传视频', dom.TYPE_LABEL, dom.TYPE_CHECKED,
            dom.DECLARATION_TRIGGER, dom.COVER_INPUT, dom.COVER_BLOB, dom.MAIN_FORM,
            dom.PUBLISH_BUTTON, 'placeholder:' + dom.TITLE_PLACEHOLDER,
            'placeholder:' + dom.DESC_PLACEHOLDER)}
        self.selectors['span:text-is("上传中")'] = RecordingLocator('uploading', count=0)
        self.selectors['div:has(> i.woo-font--check) span:text-is("上传完成")'] = RecordingLocator('done')
        self.selectors[dom.AGAIN_BUTTON] = RecordingLocator('again', visible=False)
        self.selectors[dom.SUCCESS_LAYER] = RecordingLocator('success', visible=False)
        self.selectors['.woo-dialog-main, .woo-modal-wrap, [class*="Dialog"]'] = RecordingLocator('dialog', count=0)
        finish = RecordingLocator('finish')
        cover = RecordingLocator('cover', children={dom.COVER_FINISH: finish})
        self.selectors[dom.COVER_LAYER] = cover
        async def finish_click(**_):
            finish.click_count += 1
            cover._visible = False
        finish.click = finish_click
        self.selectors['role:link:上传封面'] = RecordingLocator('cover-link')
        self.selectors[dom.DECLARATION_PANEL] = RecordingLocator('declaration', children={
            dom.AI_OPTION: RecordingLocator('ai', children={dom.AI_CHECK_ACTIVE: RecordingLocator('active')}),
            dom.DECLARATION_CONFIRM: RecordingLocator('confirm')})
        self.submit = self.selectors[dom.PUBLISH_BUTTON]
        self.submit.scroll_into_view_if_needed = AsyncMock()
        async def submit(**_):
            self.submit.click_count += 1
            self.selectors[dom.AGAIN_BUTTON]._visible = True
        self.submit.click = submit
        self.video_files = []
    def locator(self, selector):
        return self.selectors[selector] if selector in self.selectors else super().locator(selector)
    def get_by_role(self, role, name=None): return self.locator(f'role:{role}:{name}')
    def get_by_placeholder(self, text): return self.locator('placeholder:' + text)
    def expect_popup(self, **_): return PopupInfo(self)
    def expect_file_chooser(self, **_): return PopupInfo(self)
    async def set_files(self, path): self.video_files.append(path)
    async def inner_text(self, _): return '上传完成'


class BackendContext(FakeContext):
    def __init__(self):
        super().__init__()
        self.next_page = BackendPage()
    async def new_page(self):
        self.pages.append(self.next_page)
        return self.next_page


class WeiboProfilesTests(unittest.TestCase):
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
                code = sau_cli.main(['weibo', *args])
            except SystemExit as error:
                code = error.code
        return code, out.getvalue(), err.getvalue()
    def profile(self, kind='chrome', account='Creator'):
        with acquire_local_profile('weibo', account, kind, create=True) as profile:
            return profile.path
    def upload(self, *args):
        return self.cli('upload-video', '--account', 'Creator', '--file', str(self.video), '--title', 'A video title', '--thumbnail', str(self.cover), *args)

    def test_login_check_reuse_profile_and_ignore_legacy_json(self):
        legacy = self.root / 'cookies/weibo_Creator.json'
        legacy.parent.mkdir()
        legacy.write_text('malformed old state')
        result = self.cli('login', '--account', 'Creator')
        self.assertEqual(result[0], 0, result)
        self.assertEqual(self.cli('check', '--account', 'Creator')[0], 0)
        calls = self.pw.chromium.persistent_calls
        self.assertEqual(calls, [dict(user_data_dir=str(self.root / 'browser_profiles/chrome/weibo/Creator'), channel='chrome', headless=False, no_viewport=True)] * 2)
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
        self.assertEqual(self.pw.chromium.persistent_calls[0], dict(
            user_data_dir=str(self.root/'browser_profiles/chromium/weibo/Creator'),
            channel='chromium', headless=True, no_viewport=True))
        self.assertEqual(page.submit.click_count, 1)
        self.assertEqual(page.video_files, [str(self.video)])
        self.assertIn(('insert_text', 'A video title'), page.keyboard.actions)
        self.assertFalse(self.context.storage_state_calls)
        self.assertTrue(self.context.closed)

    def test_upload_redirect_during_submit_preserves_attempt_and_cleanup_failure(self):
        self.profile()
        page = UploadPage()
        async def click(**_):
            page.submit.click_count += 1
            page.url = 'https://passport.weibo.com/verify'
            raise TimeoutError('redirect during submit')
        page.submit.click = click
        self.context.next_page = page
        self.context.close_error = OSError('close failure')
        result = self.upload()
        self.assertEqual(result[0], 10, result)
        self.assertIn('publish_attempted=true', result[2])
        self.assertIn('reason=verification', result[2])
        self.assertEqual(page.submit.click_count, 1)

    def test_authentication_faults_and_verification_keep_distinct_exit_codes(self):
        self.assertEqual(self.cli('check', '--account', 'Creator')[0], 10)
        self.profile()
        for page, code in [
            (BackendPage(login=True, anchor=False), 10),
            (BackendPage(url='https://passport.weibo.com/login'), 10),
            (BackendPage(verification=True), 10),
            (BackendPage(url='https://passport.weibo.com/', verification=True), 10),
            (BackendPage(url='https://passport.weibo.com/verify'), 10),
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
        self.context.next_page = BackendPage(error=TimeoutError('redirect during navigation'), url='https://passport.weibo.com/login')
        self.assertEqual(self.cli('check', '--account', 'Creator')[0], 10)

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
        self.assertTrue(all(call['user_data_dir'].endswith('/chromium/weibo/Creator') for call in self.pw.chromium.persistent_calls))

    def test_reset_exact_profile_without_binary_and_protects_lease_history_and_old_state(self):
        chrome, chromium = self.profile(), self.profile('chromium')
        old = self.root / 'old.json'; old.write_text('old login state')
        history = self.root / 'result.json'; history.write_text('historical work')
        with patch.object(conf, 'LOCAL_CHROME_PATH', '/missing/binary'):
            with acquire_local_profile('weibo', 'Creator', 'chrome'):
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
            self.assertTrue(asyncio.run(uploader.weibo_setup(account_name='Creator', handle=True)))
            self.assertTrue(asyncio.run(uploader.cookie_auth('/missing/weibo_Creator.json', headless=False)))
            self.context.next_page = UploadPage()
            app = uploader.WeiBoVideo('Title123456', self.video, [], '/missing/weibo_Creator.json',
                                          thumbnail_path=self.cover, headless=False)
            with patch.object(uploader.asyncio, 'sleep', new=AsyncMock()):
                asyncio.run(app.main())
        calls = self.pw.chromium.persistent_calls
        self.assertEqual([call['headless'] for call in calls], [True, False, False])
        self.assertEqual(len({call['user_data_dir'] for call in calls}), 1)
        self.assertFalse((self.root / 'cookies').exists())

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
        args = sau_cli.build_parser().parse_args(['weibo', 'check', '--account', 'Creator'])
        with patch('utils.local_browser_session.CLOSE_TIMEOUT_SECONDS', 0.02):
            self.assertEqual(asyncio.run(asyncio.wait_for(sau_cli.dispatch(args), 1)), 0)
        with acquire_local_profile('weibo', 'Creator', 'chrome'):
            pass

    def test_initialization_failures_remain_faults_and_release_owned_context(self):
        self.profile()
        for action in ('login', 'check', 'upload-video'):
            self.context.next_page = BackendPage(error=OSError('navigation failed'))
            result = self.upload() if action == 'upload-video' else self.cli(action, '--account', 'Creator')
            self.assertEqual(result[0], 1, result)
            self.assertIn('navigation failed', result[2])
            self.assertTrue(self.context.closed)
            with acquire_local_profile('weibo', 'Creator', 'chrome'):
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

    def test_invalid_effective_settings_and_missing_required_cover_stop_without_browser(self):
        for args in [('--account', '../unsafe'), ('--local-browser', 'firefox')]:
            self.assertEqual(self.cli('login', '--account','Creator', *args)[0], 2)
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', 'false'):
            self.assertEqual(self.cli('check', '--account','Creator')[0], 2)
        result = self.cli('upload-video','--account','Creator','--file',str(self.video),'--title','Title')
        self.assertEqual(result[0], 1, result)
        self.assertIn('--thumbnail', result[2])
        self.assertFalse(self.pw.chromium.persistent_calls)

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

    def test_guided_qr_login_requires_positive_page_and_cleans_temporary_image(self):
        page = BackendPage(login=True, anchor=False)
        self.context.next_page = page
        qr = RecordingLocator('qr', evaluate_result='canvas')
        async def screenshot(path, **_): Path(path).write_bytes(b'fixture image')
        qr.screenshot = screenshot
        old_locator = page.locator
        page.locator = lambda selector: qr if selector == 'img[src*="qrcode"]' else old_locator(selector)
        images = []
        def scanned(payload):
            images.append(Path(payload['image_path']))
            self.assertTrue(images[-1].exists())
            page.url = uploader.WEIBO_HOME_URL
            page.login, page.anchor = False, True
        result = asyncio.run(uploader.weibo_cookie_gen(account_name='Creator', qrcode_callback=scanned))
        self.assertTrue(result['success'])
        self.assertEqual(len(self.pw.chromium.persistent_calls), 1)
        self.assertTrue(self.context.closed)
        self.assertFalse(images[0].exists())
        self.assertFalse(self.context.storage_state_calls)

    def test_injected_session_keeps_ownership_and_uses_current_account_evidence(self):
        from utils.browser_session import BrowserSession
        self.context.next_page = UploadPage()
        app = uploader.WeiBoVideo('Title', self.video, [], None, thumbnail_path=self.cover)
        asyncio.run(app.main(session=BrowserSession(browser=None, context=self.context, mode='local')))
        self.assertEqual(self.context.next_page.submit.click_count, 1)
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.assertFalse(self.context.closed)

    def test_pre_submit_fault_and_success_preserve_result_when_close_fails(self):
        self.profile()
        for error, expected in [(None,0),(PermissionError('title blocked'),1)]:
            page = UploadPage()
            page.get_by_placeholder('填写标题（0～30个字）')._wait_error = error
            self.context.next_page = page
            self.context.close_error = OSError('cleanup failed')
            result = self.upload()
            self.assertEqual(result[0], expected, result)
            self.assertEqual(page.submit.click_count, int(error is None))

    def test_unknown_submission_is_not_retried_and_budget_before_click_is_plain_failure(self):
        import time
        import uploader.publish_timeout as timeout_module
        self.profile()
        for phase, expected in [('before',1),('after',9),('click',9)]:
            page = UploadPage()
            self.context.next_page = page
            self.context.close_error = OSError('cleanup failed')
            clock = SimpleNamespace(offset=0)
            async def click(**_):
                page.submit.click_count += 1
                if phase == 'click': raise TimeoutError('dispatch failed')
                clock.offset = 1000
            page.submit.click = click
            if phase == 'before':
                async def wait(**_): clock.offset = 1000
                page.get_by_placeholder('填写标题（0～30个字）').wait_for = wait
            with patch.object(timeout_module, 'time', SimpleNamespace(monotonic=lambda: time.monotonic()+clock.offset)):
                result = self.upload()
            self.assertEqual(result[0], expected, result)
            self.assertEqual(page.submit.click_count, int(phase != 'before'))

    def test_unrelated_domain_cannot_be_classified_as_login_or_verification(self):
        self.profile()
        for url in ['https://unexpected.invalid/verify', 'https://passport.unrelated.invalid/signin']:
            self.context.next_page = BackendPage(url=url)
            result = self.cli('check', '--account','Creator')
            self.assertEqual(result[0],1,result)

    def test_probe_diagnostic_failure_preserves_original_navigation_fault(self):
        self.profile()
        page = BackendPage(error=OSError('primary navigation failure'))
        page.locator = lambda _: (_ for _ in ()).throw(OSError('secondary DOM failure'))
        self.context.next_page = page
        result = self.cli('check', '--account','Creator')
        self.assertEqual(result[0],1,result)
        self.assertIn('primary navigation failure',result[2])
        self.assertNotIn('secondary DOM failure',result[2])

    def test_upload_missing_or_expired_profile_stops_before_media_without_guiding_login(self):
        self.assertEqual(self.upload()[0],10)
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.profile()
        page=UploadPage();page.login=True;page.anchor=False
        self.context.next_page=page
        result=self.upload()
        self.assertEqual(result[0],10,result)
        self.assertEqual(page.video_files,[])
        self.assertEqual(page.submit.click_count,0)
        self.assertFalse(any('passport' in url for url,_ in page.goto_calls))

    def test_not_before_preserves_profile_ownership_until_single_submission(self):
        from datetime import datetime,timedelta,timezone
        self.profile()
        page=UploadPage();self.context.next_page=page
        target=datetime.now(timezone.utc).replace(microsecond=0)+timedelta(seconds=2)
        original_click=page.submit.click
        times=[]
        async def click(**kwargs):
            times.append(datetime.now(timezone.utc))
            with self.assertRaisesRegex(RuntimeError,'占用'):
                with acquire_local_profile('weibo','Creator','chrome'): pass
            await original_click(**kwargs)
        page.submit.click=click
        result=self.upload('--not-before',target.isoformat().replace('+00:00','Z'))
        self.assertEqual(result[0],0,result)
        self.assertEqual(len(times),1)
        self.assertGreaterEqual(times[0],target)

    def test_managed_video_uses_provider_and_ignores_invalid_local_path(self):
        from tests.fakes import FakeAdspowerClient,FakeMultiloginClient,FakeBrowser
        for cls,token,symbol in [(FakeAdspowerClient,'ADSPOWER_API_KEY','AdspowerClient'),
                                 (FakeMultiloginClient,'MLX_API_TOKEN','MultiloginClient')]:
            client=cls();page=UploadPage();page.close=FakePage.close.__get__(page)
            self.context.next_page=page
            browser=FakeBrowser([self.context]);self.pw.chromium.queue_connect_browser(browser)
            with patch.dict(os.environ,{token:'test-token'}),patch.object(conf,'LOCAL_CHROME_PATH','/unused'),patch('sau_commands.browser.'+symbol,return_value=client):
                result=self.upload('--profile-id','profile','--folder-id','folder','--headless','--local-browser','chromium')
            self.assertEqual(result[0],0,result)
            self.assertTrue(client.start_calls[0][-1])
            self.assertEqual(client.stop_calls,['profile'])
            self.assertEqual(page.submit.click_count,1)
            self.assertFalse(self.context.closed)
            self.assertEqual(browser.close_calls,1)
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.assertFalse((self.root/'browser_profiles').exists())

    def test_alias_can_relogin_and_each_browser_can_hold_different_accounts(self):
        for kind,identity in [('chrome','Account A'),('chrome','Account B'),('chromium','Account C')]:
            page=BackendPage()
            original=page.locator
            page.locator=lambda selector: RecordingLocator(identity) if selector in uploader.WEIBO_LOGIN_POSITIVE_SELECTORS else original(selector)
            self.context.next_page=page
            result=self.cli('login','--account','Creator','--local-browser',kind)
            self.assertEqual(result[0],0,result)
            self.assertEqual(self.cli('check','--account','Creator','--local-browser',kind)[0],0)
        paths=[call['user_data_dir'] for call in self.pw.chromium.persistent_calls]
        self.assertEqual(len(set(paths[:4])),1)
        self.assertNotEqual(paths[0],paths[-1])
        self.assertFalse(self.context.storage_state_calls)

    def test_observation_fault_after_submit_is_unknown_and_never_retried(self):
        self.profile()
        page=UploadPage();self.context.next_page=page
        async def submit(**_): page.submit.click_count+=1
        async def wait(ms):
            if ms==1500: raise OSError('observation disconnected')
        page.submit.click=submit;page.wait_for_timeout=wait
        result=self.upload()
        self.assertEqual(result[0],9,result)
        self.assertEqual(page.submit.click_count,1)
