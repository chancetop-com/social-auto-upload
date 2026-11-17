"""YouTube CLI → real Profile/config/session; only browser/platform edges are fake."""
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
from sau_commands import youtube as command
from tests.fakes import FakeContext, FakePage, FakePlaywright
from tests.fakes_xhs_dom import RecordingLocator, RecordingKeyboard
from uploader.youtube_uploader import main as uploader
from utils.local_profile import acquire_local_profile


class PlaywrightCM:
    def __init__(self, playwright): self.playwright = playwright
    async def __aenter__(self): return self.playwright
    async def __aexit__(self, *_): pass


class StudioPage(FakePage):
    def __init__(self, url='https://studio.youtube.com/channel/current', error=None, status=200):
        super().__init__()
        self.target_url, self.error, self.status = url, error, status
    async def goto(self, url, **kwargs):
        await super().goto(url, **kwargs)
        if self.error: raise self.error
        self.url = self.target_url
        return SimpleNamespace(status=self.status)
    def set_default_timeout(self, _): pass
    async def wait_for_timeout(self, _): pass
    async def close(self):
        raise AssertionError('Local operation pages belong to the persistent context')


class UploadPage(StudioPage):
    def __init__(self):
        super().__init__()
        self.keyboard = RecordingKeyboard()
        self.selectors = {}
        for selector in ['input[type="file"]', '#title-textarea', '#title-textarea #textbox',
                         '#description-textarea #textbox',
                         "tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK']",
                         "tp-yt-paper-radio-button[name='PUBLIC']",
                         "tp-yt-paper-radio-button[name='UNLISTED']", '#done-button']:
            self.selectors[selector] = RecordingLocator(selector)
        self.selectors[uploader.AUTOCOMPLETE_VISIBLE] = RecordingLocator('dropdown', count=0)
        self.selectors['.progress-label'] = RecordingLocator('progress', text='Checks complete')
        self.selectors["a[href*='youtu.be'], a[href*='watch?v=']"] = RecordingLocator('link', attributes={'href': 'https://youtu.be/example'})
        self.selectors["ytcp-button:has-text('Close'), ytcp-button:has-text('关闭'), #close-button"] = RecordingLocator('close')
    def locator(self, selector):
        return self.selectors[selector]


class StudioContext(FakeContext):
    def __init__(self):
        super().__init__()
        self.next_page = StudioPage()
    async def new_page(self):
        self.pages.append(self.next_page)
        return self.next_page


class YouTubeProfilesTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.playwright = FakePlaywright()
        async def forbid_temporary_browser(**kwargs):
            raise AssertionError("YouTube must use its persistent Profile")
        self.playwright.chromium.launch = forbid_temporary_browser
        self.context = StudioContext()
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
            code = sau_cli.main(['youtube', *args])
        return code, out.getvalue(), err.getvalue()
    def profile(self, kind='chrome'):
        with acquire_local_profile('youtube', 'Creator', kind, create=True) as profile:
            return profile.path
    def test_login_then_check_reuses_profile_without_reading_legacy_cookie(self):
        cookies = self.root / 'cookies'
        cookies.mkdir()
        legacy = cookies / 'youtube_Creator.json'
        legacy.write_text('invalid old JSON')
        self.assertEqual(self.cli('login', '--account', 'Creator')[0], 0)
        self.context.next_page = StudioPage('https://studio.youtube.com/channel/another-account')
        self.assertEqual(self.cli('check', '--account', 'Creator')[0], 0)
        calls = self.playwright.chromium.persistent_calls
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], {'user_data_dir': str(self.root / 'browser_profiles/chrome/youtube/Creator'), 'channel': 'chrome', 'headless': False, 'no_viewport': True})
        self.assertEqual(calls[0], calls[1])
        self.assertTrue(self.context.closed)
        self.assertFalse(self.context.storage_state_calls)
        self.assertFalse(self.context.add_init_script_calls)
        self.assertEqual(legacy.read_text(), 'invalid old JSON')

    def test_upload_reuses_one_selected_profile_and_preserves_visibility_and_description(self):
        self.profile('chromium')
        page = UploadPage()
        self.context.next_page = page
        result = self.cli('upload-video', '--account', 'Creator', '--file', str(self.video),
                          '--title', 'Title', '--desc', 'Description', '--visibility', 'unlisted',
                          '--local-browser', 'chromium', '--headless')
        self.assertEqual(result[0], 0, result)
        self.assertEqual(page.selectors['#done-button'].click_count, 1)
        self.assertEqual(page.selectors["tp-yt-paper-radio-button[name='UNLISTED']"].click_count, 1)
        self.assertIn(('insert_text', 'Description'), page.keyboard.actions)
        self.assertEqual(len(self.playwright.chromium.persistent_calls), 1)
        self.assertTrue(self.playwright.chromium.persistent_calls[0]['headless'])
        self.assertEqual(self.playwright.chromium.persistent_calls[0]['channel'], 'chromium')
        self.assertFalse(self.context.storage_state_calls)
        self.assertFalse(self.context.add_init_script_calls)

    def test_checks_distinguish_missing_login_verification_and_probe_faults(self):
        self.assertEqual(self.cli('check', '--account', 'Creator')[0], 10)
        self.assertFalse(self.playwright.chromium.persistent_calls)
        self.profile()
        for url, status, expected in [
            ('https://accounts.google.com/signin', 200, 10),
            ('https://accounts.google.com/challenge/recaptcha', 200, 10),
            ('https://studio.youtube.com/channel/id', 403, 1),
            ('https://studio.youtube.com/channel/id', 503, 1),
            ('https://studio.youtube.com/', 200, 1),
        ]:
            with self.subTest(url=url, status=status):
                self.context.next_page = StudioPage(url, status=status)
                result = self.cli('check', '--account', 'Creator')
                self.assertEqual(result[0], expected, result)
                if 'recaptcha' in url:
                    self.assertIn('verification', result[2])
        self.context.next_page = StudioPage(error=TimeoutError('network timeout'))
        self.assertEqual(self.cli('check', '--account', 'Creator')[0], 1)

    def test_upload_login_redirect_after_submit_preserves_stage_and_never_retries(self):
        self.profile()
        page = UploadPage()
        submit = page.selectors['#done-button']
        async def click(**_):
            submit.click_count += 1
            page.url = 'https://accounts.google.com/challenge/recaptcha'
        submit.click = click
        self.context.next_page = page
        self.context.close_error = OSError('close failure')
        result = self.cli('upload-video', '--account', 'Creator', '--file', str(self.video), '--title', 'Title')
        self.assertEqual(result[0], 10, result)
        self.assertIn('publish_attempted=true', result[2])
        self.assertIn('verification', result[2])
        self.assertEqual(submit.click_count, 1)

    def test_headless_defaults_explicit_overrides_proxy_and_browser_isolation(self):
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', True), patch.object(uploader, 'YT_PROXY', 'http://localhost:7890'):
            self.assertEqual(self.cli('login', '--account', 'Creator', '--headed')[0], 0)
            self.assertEqual(self.cli('check', '--account', 'Creator')[0], 0)
            self.assertEqual(self.cli('check', '--account', 'Creator', '--local-browser', 'chromium')[0], 10)
            self.assertEqual(self.cli('login', '--account', 'Creator', '--local-browser', 'chromium')[0], 0)
        calls = self.playwright.chromium.persistent_calls
        self.assertEqual([call['headless'] for call in calls], [False, True, True])
        self.assertEqual(calls[0]['user_data_dir'], calls[1]['user_data_dir'])
        self.assertNotEqual(calls[1]['user_data_dir'], calls[2]['user_data_dir'])
        self.assertTrue(all(call['proxy'] == {'server': 'http://localhost:7890'} for call in calls))

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
        self.assertTrue(all(call['user_data_dir'].endswith('/chromium/youtube/Creator') for call in self.playwright.chromium.persistent_calls))

    def test_reset_is_exact_and_requires_no_browser_and_rejects_active_profile(self):
        chrome, chromium = self.profile(), self.profile('chromium')
        history = self.root / 'result.json'
        history.write_text('history')
        with patch.object(conf, 'LOCAL_CHROME_PATH', '/does/not/exist'):
            with acquire_local_profile('youtube', 'Creator', 'chrome'):
                self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')[0], 1)
            self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')[0], 0)
            self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')[0], 0)
        self.assertFalse(chrome.exists())
        self.assertTrue(chromium.exists())
        self.assertEqual(history.read_text(), 'history')
        self.assertFalse(self.playwright.chromium.persistent_calls)

    def test_direct_setup_and_uploader_use_same_alias_profile_and_explicit_false(self):
        self.context.next_page = UploadPage()
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', True):
            asyncio.run(uploader.youtube_setup(account_name='Creator', handle=True))
            app = uploader.YouTubeVideo('Title', self.video, [], self.root / 'cookies/youtube_Creator.json', headless=False)
            asyncio.run(app.main())
        calls = self.playwright.chromium.persistent_calls
        self.assertEqual([call['headless'] for call in calls], [True, False])
        self.assertEqual(calls[0]['user_data_dir'], calls[1]['user_data_dir'])

    def test_cancellation_and_hung_page_close_do_not_leak_profile_lease(self):
        self.profile()
        self.context.next_page = StudioPage(error=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            self.cli('check', '--account', 'Creator')
        self.assertTrue(self.context.closed)
        with acquire_local_profile('youtube', 'Creator', 'chrome'):
            pass
        async def hang(): await asyncio.Event().wait()
        self.context.next_page = StudioPage()
        self.context.next_page.close = hang
        with patch('utils.local_browser_session.CLOSE_TIMEOUT_SECONDS', 0.02):
            self.context.close = hang
            args = sau_cli.build_parser().parse_args(['youtube', 'check', '--account', 'Creator'])
            self.assertEqual(asyncio.run(asyncio.wait_for(sau_cli.dispatch(args), 1)), 0)
        with acquire_local_profile('youtube', 'Creator', 'chrome'):
            pass

    def test_unknown_submit_result_remains_9_on_cleanup_failure(self):
        self.profile()
        page = UploadPage()
        page.selectors['#done-button']._click_error = RuntimeError('possibly dispatched')
        self.context.next_page = page
        self.context.close_error = OSError('close failed')
        result = self.cli('upload-video', '--account', 'Creator', '--file', str(self.video), '--title', 'Title')
        self.assertEqual(result[0], 9, result)
        self.assertEqual(page.selectors['#done-button'].click_count, 1)

    def test_schedule_still_rejected_before_launch(self):
        result = self.cli('upload-video', '--account', 'Creator', '--file', str(self.video), '--title', 'Title', '--schedule', '2027-01-01T12:00:00Z')
        self.assertEqual(result[0], 2, result)
        self.assertFalse(self.playwright.chromium.persistent_calls)

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
                    self.context.next_page = StudioPage()
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

    def test_confirmed_success_and_pre_submit_error_survive_cleanup_failure(self):
        self.profile()
        for error, expected in [(None, 0), (ValueError('file upload failed'), 1)]:
            page = UploadPage()
            if error:
                async def fail(*_, **__): raise error
                page.selectors['input[type="file"]'].set_input_files = fail
            self.context.next_page = page
            self.context.close_error = OSError('close failure')
            result = self.cli('upload-video', '--account', 'Creator', '--file', str(self.video), '--title', 'Title')
            self.assertEqual(result[0], expected, result)
            self.assertEqual(page.selectors['#done-button'].click_count, 0 if error else 1)
            with acquire_local_profile('youtube', 'Creator', 'chrome'):
                pass

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
        self.context.next_page = StudioPage(error=RuntimeError('navigation failed'))
        for action in ['login', 'check', 'upload-video']:
            args = ['--file', str(self.video), '--title', 'Title'] if action == 'upload-video' else []
            result = self.cli(action, '--account', 'Creator', *args)
            self.assertEqual(result[0], 1, result)
            self.assertIn('navigation failed', result[2])
            self.assertTrue(self.context.closed)
            with acquire_local_profile('youtube', 'Creator', 'chrome'):
                pass

    def test_injected_local_session_is_not_reopened_or_closed(self):
        from utils.browser_session import BrowserSession
        page = UploadPage()
        self.context.next_page = page
        app = uploader.YouTubeVideo('Title', self.video, [], None, account_name='Creator')
        asyncio.run(app.main(session=BrowserSession(browser=None, context=self.context, mode='local')))
        self.assertEqual(page.selectors['#done-button'].click_count, 1)
        self.assertFalse(self.context.closed)
        self.assertFalse(self.playwright.chromium.persistent_calls)

    def test_not_before_defers_only_submit_and_keeps_profile_locked(self):
        from datetime import datetime, timedelta, timezone
        target = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=2)
        self.profile()
        page = UploadPage()
        submitted = []
        async def submit(**_):
            submitted.append(datetime.now(timezone.utc))
            with self.assertRaisesRegex(RuntimeError, '占用'):
                with acquire_local_profile('youtube', 'Creator', 'chrome'):
                    pass
        page.selectors['#done-button'].click = submit
        self.context.next_page = page
        result = self.cli('upload-video', '--account', 'Creator', '--file', str(self.video), '--title', 'Title', '--not-before', target.isoformat().replace('+00:00', 'Z'))
        self.assertEqual(result[0], 0, result)
        self.assertEqual(len(submitted), 1)
        self.assertGreaterEqual(submitted[0], target)

    def test_failed_dispatch_followed_by_login_retains_possible_submission(self):
        self.profile()
        page = UploadPage()
        submit = page.selectors['#done-button']
        async def click(**_):
            submit.click_count += 1
            page.url = 'https://accounts.google.com/signin'
            raise TimeoutError('click may have reached YouTube')
        submit.click = click
        self.context.next_page = page
        result = self.cli('upload-video', '--account', 'Creator', '--file', str(self.video), '--title', 'Title')
        self.assertEqual(result[0], 10, result)
        self.assertIn('publish_attempted=true', result[2])
        self.assertEqual(submit.click_count, 1)

    def test_login_timeout_requires_login_without_deleting_profile(self):
        from unittest.mock import AsyncMock
        self.context.next_page = StudioPage('https://accounts.google.com/signin')
        with patch('uploader.youtube_uploader.main.asyncio.sleep', new=AsyncMock()):
            result = self.cli('login', '--account', 'Creator')
        self.assertEqual(result[0], 10, result)
        self.assertIn('登录超时', result[2])
        self.assertTrue(self.context.closed)
        with acquire_local_profile('youtube', 'Creator', 'chrome') as profile:
            self.assertTrue(profile.exists)

    def test_invalid_effective_config_and_aliases_fail_before_launch(self):
        for args in [('--local-browser', 'firefox'), ('--account', '../escape')]:
            result = self.cli('login', '--account', 'Creator', *args)
            self.assertEqual(result[0], 2, result)
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', 'false'):
            self.assertEqual(self.cli('check', '--account', 'Creator')[0], 2)
        self.assertFalse(self.playwright.chromium.persistent_calls)
        self.assertFalse((self.root / 'browser_profiles').exists())

    def test_upload_navigation_login_redirect_is_not_a_network_failure(self):
        self.profile()
        page = UploadPage()
        original_goto = page.goto
        async def redirect(url, **kwargs):
            if url == uploader.UPLOAD_URL:
                page.url = 'https://accounts.google.com/signin'
                raise TimeoutError('navigation timed out after redirect')
            return await original_goto(url, **kwargs)
        page.goto = redirect
        self.context.next_page = page
        result = self.cli('upload-video', '--account', 'Creator', '--file', str(self.video), '--title', 'Title')
        self.assertEqual(result[0], 10, result)
        self.assertNotIn('publish_attempted=true', result[2])
        self.assertEqual(page.selectors['#done-button'].click_count, 0)
