"""Rednote CLI through real configuration, Profile ownership and sessions."""
import io
import os
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import conf
import sau_cli
from sau_commands import rednote as command
from uploader.rednote_uploader import main as rednote
from tests.fakes import FakeContext, FakePlaywright
from tests.test_mlx_tiktok import _AsyncCM
from tests.test_tiktok_profile_cli import ProbeLocator
from utils.local_profile import acquire_local_profile


class ProbePage:
    def __init__(self, context):
        self.context = context
        self.url = 'about:blank'
        self.closed = False
    async def goto(self, url, **kwargs):
        state = self.context.state
        if state == 'network':
            raise OSError('network unavailable')
        self.url = {'login': 'https://creator.rednote.com/login',
                    'verification': 'https://creator.rednote.com/website-login/captcha'}.get(state, url.replace('/login', '/home'))
    def locator(self, selector):
        return ProbeLocator(int(self.context.state == 'valid' and selector == 'input.upload-input'))
    async def wait_for_timeout(self, milliseconds): pass
    async def close(self): self.closed = True


class ProfileContext(FakeContext):
    def __init__(self, state='valid'):
        super().__init__()
        self.state = state
        self.created_pages = []
    async def new_page(self):
        if hasattr(self, "login_page") and not self.created_pages:
            self.created_pages.append(self.login_page)
            return self.login_page
        if hasattr(self, "editor") and self.created_pages:
            return self.editor
        page = ProbePage(self)
        self.created_pages.append(page)
        return page


class RednoteProfileCliTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(conf, 'BASE_DIR', self.root))
        self.stack.enter_context(patch.object(conf, 'LOCAL_CHROME_PATH', ''))
        self.stack.enter_context(patch.object(conf, 'LOCAL_CHROME_HEADLESS', True))
        self.stack.enter_context(patch.dict(os.environ, {'MLX_API_TOKEN': '', 'ADSPOWER_API_KEY': '', 'SAU_REDNOTE_CREATOR_BASE_URL': '', 'HUMANIZE': '0'}))
        self.pw = FakePlaywright()
        self.context = ProfileContext()
        self.pw.chromium.persistent_context = self.context
        for module in (command, rednote):
            self.stack.enter_context(patch.object(module, 'async_playwright', lambda: _AsyncCM(self.pw)))
        self.addCleanup(self.stack.close)
    def cli(self, *argv):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            code = sau_cli.main(['rednote', *argv])
        return code, out.getvalue(), err.getvalue()
    def profile(self, kind='chrome'):
        with acquire_local_profile('rednote', 'creator', kind, create=True) as profile:
            return profile.path

    def test_check_uses_profile_and_config_without_legacy_json(self):
        profile = self.profile()
        (self.root / 'cookies').mkdir()
        old = self.root / 'cookies/rednote_creator.json'
        old.write_text('broken legacy state')
        code, out, err = self.cli('check', '--account', 'creator')
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), 'valid')
        self.assertEqual(self.pw.chromium.persistent_calls, [dict(user_data_dir=str(profile), channel='chrome', headless=True, no_viewport=True)])
        self.assertEqual(old.read_text(), 'broken legacy state')
        self.assertFalse(self.context.storage_state_calls)
        self.assertFalse(self.context.add_init_script_calls)
        self.assertFalse(self.pw.chromium.launch_calls)
        self.assertEqual(self.context.browser.new_context_calls, [])
        self.assertTrue(self.context.closed)

    def test_login_reuses_alias_and_separates_browser_kinds_without_cookie_files(self):
        with patch.object(rednote.asyncio, 'sleep', new=self.no_sleep):
            for kind in ('chrome', 'chrome', 'chromium'):
                code, _, err = self.cli('login', '--account', 'creator', '--headed', '--local-browser', kind)
                self.assertEqual(code, 0, err)
        calls = self.pw.chromium.persistent_calls
        self.assertEqual([call['channel'] for call in calls], ['chrome', 'chrome', 'chromium'])
        self.assertEqual(calls[0]['user_data_dir'], calls[1]['user_data_dir'])
        self.assertNotEqual(calls[0]['user_data_dir'], calls[2]['user_data_dir'])
        self.assertTrue(all(call['headless'] is False for call in calls))
        self.assertFalse(self.context.storage_state_calls)
        self.assertFalse((self.root / 'cookies').exists())
        self.assertTrue(self.context.closed)

    @staticmethod
    async def no_sleep(*args): pass

    def test_video_cli_uploads_and_edits_then_stops_before_submit(self):
        from tests.test_xhs_submit import _video_page, INPUT_FACTS
        from tests.fakes_xhs_dom import FakeLocator
        page = _video_page()
        page._selectors['div.tiptap[role="textbox"][contenteditable="true"]'] = FakeLocator('body', computed_style=dict(INPUT_FACTS))
        self.prepare_editor(page)
        media = self.root / 'video.mp4'
        media.write_bytes(b'video fixture')
        code, out, err = self.cli('upload-video', '--account', 'creator', '--file', str(media), '--title', 'Profile video', '--desc', 'Video body', '--no-publish', '--headed')
        self.assertEqual(code, 0, err)
        self.assert_editor_stopped(page, media, 'Profile video', 'Video body', out)

    def prepare_editor(self, page):
        from tests.fakes_xhs_dom import FakeLocator
        self.profile()
        page._selectors['input.upload-input'] = FakeLocator('positive upload anchor')
        for selector in rednote.REDNOTE_TITLE_MAX_SUFFIX_SELECTORS:
            page._selectors[selector] = FakeLocator('no title error', count=0)
        for overlay in rednote.REDNOTE_OVERLAY_RULES:
            page._selectors[overlay.selector] = FakeLocator('no overlay', count=0)
        page._selectors[rednote.REDNOTE_VIDEO_FAIL_SELECTOR] = FakeLocator('no upload failure', count=0)
        page._evaluate_handler = lambda expression, arg: {'since': 1000}
        self.context.editor = page

    def assert_editor_stopped(self, page, media, title, body, stdout):
        files = page._selectors[rednote.REDNOTE_UPLOAD_INPUT_SELECTOR].files
        self.assertIn(str(media), str(files))
        self.assertIn(('insert_text', title), page.keyboard.actions)
        self.assertIn(('insert_text', body), page.keyboard.actions)
        button = page._selectors['xhs-publish-btn']
        self.assertGreater(button.box_calls, 0)
        self.assertEqual(button.click_count, 0)
        self.assertEqual(page.mouse.down_count, 0)
        self.assertIn('not published', stdout)
        self.assertEqual(len(self.pw.chromium.persistent_calls), 1)
        self.assertFalse(self.pw.chromium.launch_calls)
        self.assertFalse(self.context.browser.new_context_calls)
        self.assertFalse(self.context.storage_state_calls)
        self.assertTrue(self.context.closed)

    def test_note_cli_uploads_and_edits_then_stops_before_submit(self):
        from tests.test_xhs_submit import _note_page
        page = _note_page()
        self.prepare_editor(page)
        media = self.root / 'image.png'
        media.write_bytes(b'image fixture')
        code, out, err = self.cli('upload-note', '--account', 'creator', '--images', str(media), '--title', 'Profile note', '--note', 'Note body', '--no-publish')
        self.assertEqual(code, 0, err)
        self.assert_editor_stopped(page, media, 'Profile note', 'Note body', out)

    def test_check_distinguishes_missing_login_verification_and_probe_failures(self):
        code, _, err = self.cli('check', '--account', 'creator')
        self.assertEqual(code, 10, err)
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.profile()
        for state, expected in [('login', 10), ('verification', 10), ('network', 1), ('unknown', 1)]:
            with self.subTest(state=state), patch.object(rednote, 'REDNOTE_PROBE_ANCHOR_WINDOW_SECONDS', 0):
                self.context.state = state
                code, out, err = self.cli('check', '--account', 'creator')
                self.assertEqual(code, expected, err)
                self.assertEqual(out.strip(), 'invalid' if expected == 10 else '')
                if state == 'verification': self.assertIn('验证', err)
                self.assertTrue(self.context.closed)

    def test_config_selection_explicit_flags_and_launch_failure_do_not_fallback(self):
        chrome = self.profile()
        chromium = self.profile('chromium')
        with patch.object(conf, 'LOCAL_BROWSER', 'chromium'):
            self.assertEqual(self.cli('check', '--account', 'creator', '--headed')[0], 0)
            self.assertEqual(self.pw.chromium.persistent_calls[-1]['user_data_dir'], str(chromium))
            self.assertFalse(self.pw.chromium.persistent_calls[-1]['headless'])
            self.assertEqual(self.cli('check', '--account', 'creator', '--local-browser', 'chrome', '--headless')[0], 0)
            self.assertEqual(self.pw.chromium.persistent_calls[-1]['user_data_dir'], str(chrome))
            self.assertTrue(self.pw.chromium.persistent_calls[-1]['headless'])
        with patch.object(conf, 'LOCAL_BROWSER', 'invalid'):
            self.assertEqual(self.cli('check', '--account', 'creator')[0], 2)
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', 'false'):
            self.assertEqual(self.cli('check', '--account', 'creator')[0], 2)
            self.assertEqual(self.cli('check', '--account', 'creator', '--headed')[0], 0)
        self.pw.chromium.launch_error = OSError('selected binary unavailable')
        before = len(self.pw.chromium.persistent_calls)
        code, _, err = self.cli('check', '--account', 'creator')
        self.assertEqual(code, 1)
        self.assertIn('channel=chrome', err)
        self.assertEqual(len(self.pw.chromium.persistent_calls), before + 1)
        self.assertFalse(self.pw.chromium.launch_calls)

    def test_custom_path_wins_and_reuses_same_kind_profile(self):
        import plistlib
        chrome = self.profile()
        binary = self.root / 'Custom.app/Contents/MacOS/browser'
        binary.parent.mkdir(parents=True)
        binary.write_text('fixture')
        binary.chmod(0o755)
        with (binary.parent.parent / 'Info.plist').open('wb') as target:
            plistlib.dump({'CFBundleName': 'Google Chrome', 'CFBundleExecutable': 'browser', 'CFBundleIdentifier': 'com.google.Chrome', 'CFBundleShortVersionString': '1.2.3'}, target)
        with patch('utils.local_browser.sys.platform', 'darwin'), patch.object(conf, 'LOCAL_CHROME_PATH', str(binary)):
            code, _, err = self.cli('check', '--account', 'creator', '--local-browser', 'irrelevant')
        self.assertEqual(code, 0, err)
        call = self.pw.chromium.persistent_calls[-1]
        self.assertEqual(call['user_data_dir'], str(chrome))
        self.assertEqual(call['executable_path'], str(binary.resolve()))
        self.assertNotIn('channel', call)

    def test_reset_requires_no_binary_and_only_removes_selected_profile(self):
        chrome = self.profile()
        chromium = self.profile('chromium')
        (chrome / 'browser data').write_text('chrome state')
        (chromium / 'browser data').write_text('chromium state')
        with patch.object(conf, 'LOCAL_CHROME_PATH', '/missing/browser'):
            with acquire_local_profile('rednote', 'creator', 'chrome'):
                self.assertEqual(self.cli('reset-profile', '--account', 'creator', '--browser-kind', 'chrome')[0], 1)
            self.assertEqual(self.cli('reset-profile', '--account', 'creator', '--browser-kind', 'chrome')[0], 0)
            self.assertEqual(self.cli('reset-profile', '--account', 'creator', '--browser-kind', 'chrome')[0], 0)
        self.assertFalse(chrome.exists())
        self.assertEqual((chromium / 'browser data').read_text(), 'chromium state')
        self.assertEqual(self.cli('check', '--account', 'creator')[0], 10)
        self.assertFalse(self.pw.chromium.persistent_calls)

    def test_check_cleanup_failure_keeps_login_and_probe_outcomes(self):
        self.profile()
        self.context.close_error = OSError('context close failed')
        for state, expected in [('valid', 0), ('login', 10), ('verification', 10), ('network', 1)]:
            self.context.state = state
            code, _, err = self.cli('check', '--account', 'creator')
            self.assertEqual(code, expected, err)
        self.assertEqual(self.context.browser.close_calls, 0)
        with acquire_local_profile('rednote', 'creator', 'chrome') as profile:
            self.assertTrue(profile.exists)

    def test_direct_setup_and_uploaders_preserve_runtime_and_injected_ownership(self):
        import asyncio
        from utils.browser_session import BrowserSession
        from utils.errors import LoginRequiredError
        self.profile()
        self.context.state = 'login'
        media = self.root / 'video.mp4'; media.write_bytes(b'fixture')
        image = self.root / 'image.png'; image.write_bytes(b'fixture')
        for headless in (None, False):
            for run in (
                lambda: rednote.rednote_setup(account_name='creator', headless=headless),
                lambda: rednote.RednoteVideo('Title', str(media), [], 0, None, account_name='creator', headless=headless).upload(self.pw),
                lambda: rednote.RednoteNote([str(image)], '', [], 0, None, title='Title', account_name='creator', headless=headless).upload(self.pw),
            ):
                with self.assertRaises(LoginRequiredError): asyncio.run(run())
                self.assertEqual(self.pw.chromium.persistent_calls[-1]['headless'], headless is None)
        self.context.closed = False
        active = BrowserSession(browser=self.context.browser, context=self.context, mode='local')
        before = len(self.pw.chromium.persistent_calls)
        with self.assertRaises(LoginRequiredError):
            asyncio.run(rednote.rednote_setup(account_name='creator', session=active))
        self.assertFalse(self.context.closed)
        self.assertEqual(len(self.pw.chromium.persistent_calls), before)

    def test_managed_check_ignores_local_settings_and_keeps_provider_ownership(self):
        from tests.fakes import FakeAdspowerClient, FakeMultiloginClient, FakeBrowser
        from sau_commands import browser
        for provider_name, env_name, client_type in [('AdspowerClient', 'ADSPOWER_API_KEY', FakeAdspowerClient), ('MultiloginClient', 'MLX_API_TOKEN', FakeMultiloginClient)]:
            for flags, expected in [([], True), (['--headed'], False)]:
                client = client_type()
                context = ProfileContext()
                connected = FakeBrowser([context])
                self.pw.chromium.queue_connect_browser(connected)
                with patch.dict(os.environ, {env_name: 'test'}), patch.object(browser, provider_name, return_value=client), patch.object(conf, 'LOCAL_CHROME_PATH', []), patch.object(conf, 'LOCAL_BROWSER', []):
                    code, _, err = self.cli('check', '--folder-id', 'folder', '--profile-id', 'profile', '--local-browser', 'ignored', *flags)
                self.assertEqual(code, 0, err)
                self.assertEqual(client.start_calls[-1][-1], expected)
                self.assertEqual(client.stop_calls, ['profile'])
                self.assertFalse(context.closed)
                self.assertEqual(connected.close_calls, 1)
                self.assertFalse(context.storage_state_calls)
                self.assertFalse(context.add_init_script_calls)
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.assertFalse((self.root / 'browser_profiles').exists())

    def test_post_submit_outcomes_survive_cleanup_failure_without_resubmitting(self):
        from tests.test_xhs_submit import _note_page, _PublishButton
        media = self.root / 'image.png'; media.write_bytes(b'fixture')
        for outcome, expected in [('success', 0), ('unknown', 9), ('login', 10), ('verification', 10)]:
            with self.subTest(outcome=outcome):
                class Button(_PublishButton):
                    async def click(inner, **kwargs):
                        await super().click(**kwargs)
                        suffix = {'success': '/publish/success', 'unknown': '/publish/publish', 'login': '/login', 'verification': '/website-login/captcha'}[outcome]
                        page.url = page.main_frame.url = 'https://creator.rednote.com' + suffix
                page = _note_page(Button())
                self.prepare_editor(page)
                self.context.created_pages = []
                self.context.close_error = OSError('cleanup failed')
                with patch.object(rednote, 'REDNOTE_OBSERVE_WINDOW_SECONDS', 0):
                    code, _, err = self.cli('upload-note', '--account', 'creator', '--images', str(media), '--title', 'Title')
                self.assertEqual(code, expected, err)
                self.assertEqual(page._selectors['xhs-publish-btn'].click_count, 1)
                self.assertEqual('publish_attempted=true' in err, outcome in ('login', 'verification'))
                self.assertEqual(self.context.browser.close_calls, 0)

    def test_cancellation_and_page_failure_release_profile_without_relaunch(self):
        import asyncio
        from tests.test_xhs_submit import _video_page
        for error in (asyncio.CancelledError(), OSError('editor navigation failed')):
            page = _video_page()
            self.prepare_editor(page)
            self.context.created_pages = []
            self.context.closed = False
            async def navigate(url, **kwargs):
                with self.assertRaisesRegex(RuntimeError, '占用'):
                    with acquire_local_profile('rednote', 'creator', 'chrome'): pass
                raise error
            page.goto = navigate
            media = self.root / 'video.mp4'; media.write_bytes(b'fixture')
            args = sau_cli.build_parser().parse_args(['rednote', 'upload-video', '--account', 'creator', '--file', str(media), '--title', 'Title', '--no-publish'])
            with self.assertRaises(type(error)) as caught:
                asyncio.run(sau_cli.dispatch(args))
            self.assertIs(caught.exception, error)
            self.assertTrue(self.context.closed)
            self.assertEqual(page._selectors['xhs-publish-btn'].click_count, 0)
            with acquire_local_profile('rednote', 'creator', 'chrome') as profile:
                self.assertTrue(profile.exists)

    def test_managed_upload_keeps_ignored_option_logs_and_never_touches_local_profiles(self):
        from loguru import logger
        from sau_commands import browser
        from tests.fakes import FakeAdspowerClient, FakeBrowser
        from tests.test_xhs_submit import _note_page
        page = _note_page()
        # This setup only scripts the remote page; remove its local seed before dispatch.
        self.prepare_editor(page)
        import shutil
        shutil.rmtree(self.root / 'browser_profiles')
        self.context.created_pages = [object()]
        connected = FakeBrowser([self.context])
        self.pw.chromium.queue_connect_browser(connected)
        client = FakeAdspowerClient()
        media = self.root / 'image.png'; media.write_bytes(b'fixture')
        logs = io.StringIO(); sink = logger.add(logs, format='{message}')
        try:
            with patch.dict(os.environ, {'ADSPOWER_API_KEY': 'test'}), patch.object(browser, 'AdspowerClient', return_value=client), patch.object(conf, 'LOCAL_CHROME_PATH', []):
                code, _, err = self.cli('upload-note', '--profile-id', 'profile', '--account', 'ignored', '--images', str(media), '--title', 'Title', '--no-publish', '--local-browser', 'ignored')
        finally:
            logger.remove(sink)
        self.assertEqual(code, 0, err)
        self.assertIn('ignored=launch_kwargs, context_kwargs, init_script, account', logs.getvalue())
        self.assertEqual(client.start_calls, [('profile', True)])
        self.assertEqual(client.stop_calls, ['profile'])
        self.assertFalse(self.context.closed)
        self.assertEqual(connected.close_calls, 1)
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.assertFalse((self.root / 'browser_profiles').exists())

    def test_headless_login_uses_qr_in_the_main_profile_context(self):
        import asyncio
        import segno
        from tests.fakes_xhs_dom import FakeLocator
        from tests.test_xhs_submit import BUTTON_FACTS
        context = self.context
        class QrPage(ProbePage):
            async def goto(inner, url, **kwargs): inner.url = url
            def locator(inner, selector):
                if selector == rednote.REDNOTE_LOGIN_BOX_SELECTOR: return login_box
                if selector == 'img.css-1lhmg90': return qr
                return super().locator(selector)
        page = QrPage(context)
        class Qr(FakeLocator):
            async def get_attribute(inner, name):
                # The external platform redirects after the user scans.
                page.url = 'https://creator.rednote.com/home'
                login_box._count = 0
                return segno.make('https://rednote.test/fixture-login').png_data_uri(scale=4)
        qr = Qr('qr', computed_style=dict(BUTTON_FACTS))
        login_box = FakeLocator('login', children={'img.css-1lhmg90': qr})
        context.login_page = page
        observed = []
        def callback(info):
            observed.append(Path(info['image_path']).is_file())
        with patch.object(rednote.asyncio, 'sleep', new=self.no_sleep), redirect_stdout(io.StringIO()):
            result = asyncio.run(rednote.rednote_cookie_gen(account_name='creator', qrcode_callback=callback))
        self.assertTrue(result['success'])
        self.assertEqual(observed, [True])
        self.assertFalse(Path(result['qrcode']['image_path']).exists())
        self.assertTrue(self.pw.chromium.persistent_calls[0]['headless'])
        self.assertEqual(len(self.pw.chromium.persistent_calls), 1)
        self.assertFalse(context.browser.new_context_calls)
        self.assertFalse(context.storage_state_calls)
        self.assertTrue(context.closed)

    def test_managed_login_reset_and_rate_limit_keep_existing_contracts(self):
        from sau_commands import browser
        from tests.fakes import FakeAdspowerClient
        from utils.errors import RateLimitedError
        client = FakeAdspowerClient(probe_error=RateLimitedError('provider rate limited'))
        with patch.dict(os.environ, {'ADSPOWER_API_KEY': 'test'}), patch.object(browser, 'AdspowerClient', return_value=client):
            self.assertEqual(self.cli('login', '--account', 'creator')[0], 1)
            self.assertEqual(self.cli('reset-profile', '--account', 'creator', '--browser-kind', 'chrome')[0], 2)
            self.assertEqual(self.cli('check', '--profile-id', 'profile')[0], 11)
        self.assertEqual(client.probe_calls, 1)
        self.assertEqual(client.start_calls, [])
        self.assertEqual(client.stop_calls, [])
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.assertFalse((self.root / 'browser_profiles').exists())

    def test_headless_login_accepts_an_existing_session_without_demanding_a_qr(self):
        self.profile()
        with patch.object(rednote.asyncio, 'sleep', new=self.no_sleep):
            code, _, err = self.cli('login', '--account', 'creator')
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.pw.chromium.persistent_calls), 1)
        self.assertTrue(self.pw.chromium.persistent_calls[0]['headless'])
        self.assertFalse(self.context.storage_state_calls)

    def test_headless_login_verification_preserves_the_remedy(self):
        self.context.state = 'verification'
        code, _, err = self.cli('login', '--account', 'creator')
        self.assertEqual(code, 10, err)
        self.assertIn('验证', err)
        self.assertTrue(self.context.closed)

    def test_local_probe_cleanup_is_owned_by_the_bounded_context_close(self):
        import asyncio
        self.profile()
        page = ProbePage(self.context)
        async def blocked_page_close():
            await asyncio.sleep(10)
        page.close = blocked_page_close
        async def new_page(): return page
        self.context.new_page = new_page
        args = sau_cli.build_parser().parse_args(['rednote', 'check', '--account', 'creator'])
        async def dispatch():
            return await asyncio.wait_for(sau_cli.dispatch(args), timeout=0.05)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(asyncio.run(dispatch()), 0)
        self.assertTrue(self.context.closed)

    def test_both_upload_commands_require_a_profile_without_guiding_login(self):
        media = self.root / 'video.mp4'; media.write_bytes(b'fixture')
        image = self.root / 'image.png'; image.write_bytes(b'fixture')
        for action, flag, path in [('upload-video', '--file', media), ('upload-note', '--images', image)]:
            code, _, err = self.cli(action, '--account', 'creator', flag, str(path), '--title', 'Title', '--no-publish')
            self.assertEqual(code, 10, err)
            self.assertIn('login', err)
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.assertFalse(self.pw.chromium.launch_calls)
        self.assertFalse((self.root / 'cookies').exists())
