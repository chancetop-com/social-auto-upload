"""Instagram formal CLI with real configuration, Profile and session ownership."""
import io
import os
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout, chdir
from pathlib import Path
from unittest.mock import patch

import conf
import sau_cli
from sau_commands import instagram
from tests.fakes import FakeContext, FakePlaywright
from tests.test_mlx_tiktok import _AsyncCM
from uploader.meta_uploader.insgraph_uploader import main, posts
from utils.local_profile import acquire_local_profile


class Locator:
    def __init__(self, count=1, attr=None): self.value, self.attr = count, attr
    @property
    def first(self): return self
    async def count(self): return self.value
    async def wait_for(self, **kwargs):
        if not self.value: raise RuntimeError('page outcome unavailable')
    def filter(self, **kwargs): return self
    async def get_attribute(self, name): return self.attr


class Expect:
    def __init__(self, locator): self.locator = locator
    async def to_have_count(self, count, **kwargs):
        if await self.locator.count() != count: raise RuntimeError('unexpected page structure')
    async def not_to_have_count(self, count, **kwargs):
        if await self.locator.count() == count: raise RuntimeError('unknown page outcome')

    async def to_contain_text(self, text, **kwargs):
        if text not in await self.locator.inner_text(): raise RuntimeError('caption mismatch')
    async def to_be_enabled(self, **kwargs):
        if not await self.locator.is_enabled(): raise RuntimeError('disabled')
    async def not_to_have_text(self, text, **kwargs):
        if await self.locator.inner_text() == text: raise RuntimeError('editor did not advance')


class Page:
    def __init__(self, context): self.context, self.url = context, 'about:blank'
    async def goto(self, url, **kwargs):
        if self.context.state == 'network': raise OSError('network unavailable')
        self.url = {'login':'https://www.instagram.com/accounts/login/', 'verification':'https://www.instagram.com/challenge/'}.get(self.context.state, 'https://www.instagram.com/' if self.context.state == 'valid' else url)
        from types import SimpleNamespace
        return SimpleNamespace(status=getattr(self.context, 'response_status', 200))
    def set_default_timeout(self, value): pass
    def locator(self, selector):
        if 'direct/inbox' in selector:
            return Locator(int(self.context.state == 'valid' or (',' in selector and self.context.state == 'login')))
        if selector == 'a[href]': return Locator(attr='/creator/')
        return Locator()
    async def close(self): pass


class Context(FakeContext):
    def __init__(self):
        super().__init__()
        self.state, self.user_id = 'valid', '42'
    async def new_page(self):
        page = getattr(self, 'page_type', Page)(self)
        self.pages.append(page)
        return page
    async def cookies(self, *args):
        return [{'name':'ds_user_id', 'value':self.user_id, 'domain':'.instagram.com'}] if self.user_id is not None else []


class InstagramProfileCliTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.stack.enter_context(chdir(self.root))
        self.stack.enter_context(patch.object(conf, 'BASE_DIR', self.root))
        self.stack.enter_context(patch.object(conf, 'LOCAL_CHROME_PATH', ''))
        self.stack.enter_context(patch.object(conf, 'LOCAL_CHROME_HEADLESS', True))
        self.stack.enter_context(patch.dict(os.environ, {'MLX_API_TOKEN':'', 'ADSPOWER_API_KEY':'', 'HUMANIZE':'0'}))
        self.pw, self.context = FakePlaywright(), Context()
        self.pw.chromium.persistent_context = self.context
        for module in (main, posts, instagram):
            self.stack.enter_context(patch.object(module, 'async_playwright', lambda: _AsyncCM(self.pw)))
        self.stack.enter_context(patch.object(main, 'expect', Expect))
        async def dom_login_outcome(page):
            return {'valid': False, 'login': True}.get(page.context.state)
        self.stack.enter_context(patch.object(main, '_instagram_dom_login_outcome', dom_login_outcome))
        self.stack.enter_context(patch.object(main, 'INSTAGRAM_LOGIN_OUTCOME_TIMEOUT_MS', 200))
        self.addCleanup(self.stack.close)
    def run_cli(self, *argv):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            code = sau_cli.main(['instagram', *argv])
        return code, out.getvalue(), err.getvalue()
    def profile(self, kind='chrome'):
        with acquire_local_profile('instagram', 'Creator', kind, create=True): pass

    def test_reappearing_legacy_file_is_untouched_and_login_does_not_restart(self):
        with ExitStack():
            code, _, err = self.run_cli('login', '--account', 'Creator', '--headed')
            self.assertEqual(code, 0, err)
        legacy = self.root / 'cookies/instagram_Creator.json'
        legacy.parent.mkdir(exist_ok=True)
        legacy.write_bytes(b'reappeared broken credentials')
        open_file = Path.open
        def deny_legacy_open(path, *args, **kwargs):
            if path == legacy:
                raise AssertionError('normal commands must never read or rewrite old credentials')
            return open_file(path, *args, **kwargs)
        with patch.object(Path, 'open', deny_legacy_open):
            with ExitStack():
                code, _, err = self.run_cli('login', '--account', 'Creator', '--headed')
                self.assertEqual(code, 0, err)
            code, _, err = self.run_cli('check', '--account', 'Creator', '--headed')
            self.assertEqual(code, 0, err)
        self.assertEqual(legacy.read_bytes(), b'reappeared broken credentials')
        self.assertEqual(len(self.pw.chromium.persistent_calls), 3)
        self.assertFalse(self.context.storage_state_calls)

    def test_check_uses_configured_persistent_profile_without_legacy_json(self):
        self.profile()
        (self.root / 'cookies').mkdir()
        old = self.root / 'cookies/instagram_Creator.json'
        old.write_text('broken legacy credentials')
        code, _, err = self.run_cli('check', '--account', 'Creator', '--proxy', 'http://localhost:7890')
        self.assertEqual(code, 0, err)
        self.assertEqual(self.pw.chromium.persistent_calls, [{
            'user_data_dir': str(self.root / 'browser_profiles/chrome/instagram/Creator'),
            'channel':'chrome', 'headless':True, 'no_viewport':True,
            'proxy':{'server':'http://localhost:7890'},
        }])
        self.assertEqual(old.read_text(), 'broken legacy credentials')
        self.assertFalse(self.context.storage_state_calls)
        self.assertTrue(self.context.closed)

    def test_login_reuses_profile_allows_new_user_and_never_exports_candidates(self):
        for user_id, flags in [('42', []), ('77', ['--headed']), ('91', ['--local-browser', 'chromium'])]:
            self.context.user_id = user_id
            code, _, err = self.run_cli('login', '--account', 'Creator', *flags)
            self.assertEqual(code, 0, err)
        calls = self.pw.chromium.persistent_calls
        self.assertEqual(len(calls), 3)
        self.assertEqual([c['headless'] for c in calls], [True, False, True])
        self.assertEqual(calls[0]['user_data_dir'], calls[1]['user_data_dir'])
        self.assertTrue(calls[2]['user_data_dir'].endswith('/chromium/instagram/Creator'))
        self.assertFalse(self.context.storage_state_calls)
        self.assertFalse((self.root / 'cookies').exists())

    def test_login_classification_and_required_current_id(self):
        self.assertEqual(self.run_cli('check', '--account', 'Creator')[0], 10)
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.profile()
        for state, user_id, code in [('login','42',10), ('verification','42',10), ('network','42',1), ('unknown','42',1), ('valid',None,1), ('valid','not-numeric',1), ('valid','77',0)]:
            with self.subTest(state=state, user_id=user_id):
                self.context.state, self.context.user_id = state, user_id
                actual, _, err = self.run_cli('check', '--account', 'Creator')
                self.assertEqual(actual, code, err)
                if state == 'verification': self.assertIn('验证', err)
                self.assertTrue(self.context.closed)

    def test_video_and_note_reach_actual_no_publish_stop_in_one_session(self):
        for action, option, filename in [('upload-video','--file','video.mp4'), ('upload-note','--images','photo.png')]:
            with self.subTest(action=action):
                self.profile()
                path = self.root / filename
                path.write_bytes(b'media fixture')
                self.context.page_type = ComposerPage
                code, out, err = self.run_cli(action, '--account', 'Creator', option, str(path), '--title', 'Original caption', '--no-publish', '--headed')
                self.assertEqual(code, 0, err)
                page = self.context.pages[-1]
                self.assertEqual(page.files, [str(path)])
                self.assertEqual(page.caption, 'Original caption')
                self.assertEqual(page.share_clicks, 0)
                self.assertIn('prepared', out)
                self.assertTrue(self.context.closed)
                self.assertFalse(self.context.storage_state_calls)
        self.assertEqual(len(self.pw.chromium.persistent_calls), 2)
        self.assertFalse(self.pw.chromium.launch_calls)

    def test_local_video_and_note_choose_observed_post_submenu_before_upload(self):
        from tests.fakes_clock import FakeClock
        import uploader.publish_timeout as timeout
        clock = FakeClock()
        class MenuLocator(ComposerLocator):
            async def click(self):
                if self.kind == 'post-menu':
                    self.page.post_clicks += 1
                    self.page.composer_open = True
                else:
                    await super().click()
        class MenuPage(ComposerPage):
            def __init__(self, context):
                super().__init__(context)
                self.composer_open, self.post_clicks = False, 0
            def locator(self, selector):
                if 'svg[aria-label="帖子"]' in selector:
                    return MenuLocator(self, 'post-menu', int(not self.composer_open))
                if 'input[type="file"]' in selector:
                    return ComposerLocator(self, 'media-input', int(self.composer_open))
                return super().locator(selector)
            async def wait_for_timeout(self, milliseconds): clock.advance(milliseconds / 1000)
        self.context.page_type = MenuPage
        self.profile()
        for action, option, filename in [('upload-video', '--file', 'video.mp4'), ('upload-note', '--images', 'image.png')]:
            with self.subTest(action=action):
                path = self.root / filename
                path.write_bytes(b'media fixture')
                with clock.patch(main, timeout):
                    code, out, err = self.run_cli(action, '--account', 'Creator', option, str(path), '--title', 'caption', '--no-publish', '--headed')
                self.assertEqual(code, 0, err)
                page = self.context.pages[-1]
                self.assertEqual(page.files, [str(path)])
                self.assertEqual(page.post_clicks, 1)
                self.assertEqual(page.share_clicks, 0)
                self.assertIn('prepared', out)
                self.assertTrue(self.context.closed)

    def test_injected_local_and_managed_creator_sessions_stop_before_share(self):
        import asyncio
        from tests.fakes_clock import FakeClock
        import uploader.publish_timeout as timeout
        from utils.browser_session import BrowserSession
        clock = FakeClock()
        class MenuLocator(ComposerLocator):
            async def click(self):
                if self.kind == 'post-menu':
                    self.page.post_clicks += 1
                    self.page.composer_open = True
                else:
                    await super().click()
        class MenuPage(ComposerPage):
            def __init__(self, context):
                super().__init__(context)
                self.composer_open, self.post_clicks = False, 0
            def locator(self, selector):
                if 'svg[aria-label="帖子"]' in selector:
                    return MenuLocator(self, 'post-menu', int(not self.composer_open))
                if 'input[type="file"]' in selector:
                    return ComposerLocator(self, 'media-input', int(self.composer_open))
                return super().locator(selector)
            async def wait_for_timeout(self, milliseconds):
                clock.advance(milliseconds / 1000)
        self.context.page_type = MenuPage
        for mode in ('local', 'multilogin', 'adspower'):
            for video in (False, True):
                with self.subTest(mode=mode, video=video):
                    path = self.root / ('video.mp4' if video else 'image.png')
                    path.write_bytes(b'media fixture')
                    app = main.InstagramUploader(account_name='Creator', title='caption',
                        video_file=path if video else None, image_files=[] if video else [path],
                        no_publish=True, result_file=self.root/'result.json')
                    session = BrowserSession(browser=None, context=self.context, mode=mode)
                    with clock.patch(main, timeout):
                        result = asyncio.run(app.upload(session=session))
                    page = self.context.pages[-1]
                    self.assertEqual(result['status'], 'prepared')
                    self.assertEqual(page.files, [str(path)])
                    self.assertEqual(page.post_clicks, 1)
                    self.assertEqual(page.share_clicks, 0)
                    self.assertFalse(self.context.closed)
                    self.assertFalse(self.pw.chromium.persistent_calls)

    def test_editor_rejects_early_share_without_dispatching_it(self):
        class EarlyShareLocator(ComposerLocator):
            def get_by_role(self, role, **kwargs):
                if role == 'button' and 'name' in kwargs:
                    return EarlyShareLocator(self.page, 'action', int(bool(kwargs['name'].fullmatch('Share'))))
                return super().get_by_role(role, **kwargs)
            async def click(self):
                if self.kind == 'action':
                    self.page.share_clicks += 1
                else:
                    await super().click()
        class EarlySharePage(ComposerPage):
            def get_by_role(self, role, **kwargs):
                return EarlyShareLocator(self, role)
        self.profile()
        self.context.page_type = EarlySharePage
        for action, option, filename in [('upload-video', '--file', 'video.mp4'), ('upload-note', '--images', 'image.png')]:
            with self.subTest(action=action):
                path = self.root / filename
                path.write_bytes(b'media fixture')
                code, _, err = self.run_cli(action, '--account', 'Creator', option, str(path), '--title', 'caption', '--no-publish')
                self.assertEqual(code, 1, err)
                self.assertEqual(self.context.pages[-1].share_clicks, 0)

    def test_local_composer_uses_observed_continue_label_before_share(self):
        class ChineseLocator(ComposerLocator):
            def get_by_role(self, role, **kwargs):
                if role == 'button' and 'name' in kwargs:
                    label = '继续' if self.page.step < 2 else '分享'
                    return ComposerLocator(self.page, 'action', int(bool(kwargs['name'].fullmatch(label))))
                return super().get_by_role(role, **kwargs)
        class ChinesePage(ComposerPage):
            def get_by_role(self, role, **kwargs): return ChineseLocator(self, role)
        self.context.page_type = ChinesePage
        self.profile()
        for action, option, filename in [('upload-video', '--file', 'video.mp4'), ('upload-note', '--images', 'image.png')]:
            with self.subTest(action=action):
                path = self.root / filename
                path.write_bytes(b'media fixture')
                code, out, err = self.run_cli(action, '--account', 'Creator', option, str(path), '--title', 'caption', '--no-publish', '--headed')
                self.assertEqual(code, 0, err)
                page = self.context.pages[-1]
                self.assertEqual(page.step, 2)
                self.assertEqual(page.share_clicks, 0)
                self.assertEqual(page.caption, 'caption')
                self.assertIn('prepared', out)

    def test_works_stay_local_with_provider_env_and_use_current_author(self):
        self.profile('chromium')
        self.context.page_type = PostPage
        self.stack.enter_context(patch.object(posts, 'expect', Expect))
        for provider_env in ({'MLX_API_TOKEN':'unused'}, {'ADSPOWER_API_KEY':'unused'}):
            with patch.dict(os.environ, provider_env):
                for action in ('verify', 'delete'):
                    code, out, err = self.run_cli(action, '--account', 'Creator', '--local-browser', 'chromium', '--post-url', 'https://www.instagram.com/p/ABC/', '--expected-text', 'original caption', '--proxy', 'http://localhost:7890')
                    self.assertEqual(code, 0, err)
                    self.assertIn('deleted' if action == 'delete' else 'published', out)
                    self.assertEqual(self.context.pages[-1].delete_clicks, int(action == 'delete'))
                    self.assertTrue(self.context.closed)
                self.assertEqual(self.run_cli('verify', '--post-url', 'https://www.instagram.com/p/ABC/', '--expected-text', 'original caption')[0], 2)
        self.assertEqual(len(self.pw.chromium.persistent_calls), 4)
        for call in self.pw.chromium.persistent_calls:
            self.assertTrue(call['user_data_dir'].endswith('/chromium/instagram/Creator'))
            self.assertEqual(call['proxy'], {'server':'http://localhost:7890'})
        self.assertFalse(self.context.storage_state_calls)
        self.assertFalse((self.root / 'cookies').exists())
        self.context.user_id = '77'
        code, _, err = self.run_cli('verify', '--account', 'Creator', '--local-browser', 'chromium', '--post-url', 'https://www.instagram.com/p/ABC/', '--expected-text', 'original caption')
        self.assertEqual(code, 1)
        self.assertIn('原作品作者', err)

    def test_expiry_during_edit_stops_before_no_publish_and_preserves_verification(self):
        self.profile()
        path = self.root / 'photo.png'
        path.touch()
        self.context.page_type = ComposerPage
        self.context.expire_during_edit = True
        code, out, err = self.run_cli('upload-note', '--account', 'Creator', '--images', str(path), '--title', 'caption', '--no-publish')
        self.assertEqual(code, 10, err)
        self.assertIn('验证', err)
        self.assertNotIn('prepared', out)
        self.assertEqual(self.context.pages[-1].share_clicks, 0)

    def test_submit_success_unknown_and_login_phase_survive_cleanup_and_capture_failure(self):
        self.profile()
        self.context.page_type = ComposerPage
        self.context.close_error = OSError('close fault')
        path = self.root / 'photo.png'
        path.touch()
        for outcome, expected in [('success',0), ('unknown',9), ('login',10), ('verification',10), ('click-login',10)]:
            with self.subTest(outcome=outcome):
                self.context.outcome = outcome
                code, out, err = self.run_cli('upload-note', '--account', 'Creator', '--images', str(path), '--title', 'caption', '--result', str(self.root / 'result.json'))
                self.assertEqual(code, expected, err)
                self.assertEqual(self.context.pages[-1].share_clicks, 1)
                if expected == 10:
                    self.assertIn('publish_attempted=true', err)
                    import json
                    self.assertEqual(json.loads((self.root / 'result.json').read_text())['stage'], 'publish')
                if expected == 0: self.assertIn('published', out)
                with acquire_local_profile('instagram', 'Creator', 'chrome'): pass
        self.assertFalse(self.context.storage_state_calls)

    def test_managed_ignores_local_config_and_preserves_provider_ownership_and_logs(self):
        from tests.fakes import FakeManagedProvider, FakeBrowser
        from loguru import logger
        for mode in ('multilogin', 'adspower'):
            provider = FakeManagedProvider(mode=mode)
            context = Context()
            browser = FakeBrowser([context])
            self.pw.chromium.queue_connect_browser(browser)
            logs = []
            sink = logger.add(lambda message: logs.append(str(message)), format='{message}')
            try:
                with patch.object(instagram, 'resolve_managed_provider', return_value=provider), patch.object(conf, 'LOCAL_BROWSER', [] , create=True), patch.object(conf, 'LOCAL_CHROME_PATH', []):
                    code, _, err = self.run_cli('check', '--account', 'Creator', '--local-browser', 'ignored')
                self.assertEqual(code, 0, err)
                self.assertEqual(provider.start_calls, [True])
                self.assertEqual(provider.stop_calls, 1)
                self.assertFalse(context.closed)
                self.assertIn('context_kwargs', ''.join(logs))
                self.assertIn('身份', ''.join(logs))
            finally: logger.remove(sink)
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.assertFalse((self.root / 'browser_profiles').exists())

    def test_direct_calls_share_alias_config_and_injected_session_is_borrowed(self):
        import asyncio
        from utils.browser_session import BrowserSession
        self.profile()
        self.assertTrue(asyncio.run(main.instagram_cookie_auth('/absent/instagram_Creator.json', headless=False)))
        self.assertFalse(self.pw.chromium.persistent_calls[-1]['headless'])
        self.context.page_type = ComposerPage
        path = self.root / 'photo.png'; path.touch()
        app = main.InstagramUploader(account_name='Creator', title='caption', image_files=[path], no_publish=True)
        self.assertEqual(asyncio.run(app.upload())['status'], 'prepared')
        self.assertTrue(self.pw.chromium.persistent_calls[-1]['headless'])
        self.context.closed = False
        session = BrowserSession(browser=self.context.browser, context=self.context, mode='local')
        self.assertEqual(asyncio.run(app.upload(session=session))['status'], 'prepared')
        self.assertFalse(self.context.closed)
        self.assertEqual(len(self.pw.chromium.persistent_calls), 2)

    def test_works_expiry_preserves_login_exception_even_when_evidence_fails(self):
        self.profile()
        self.context.page_type = PostPage
        self.context.works_expiry = True
        self.stack.enter_context(patch.object(posts, 'expect', Expect))
        code, _, err = self.run_cli('delete', '--account', 'Creator', '--post-url', 'https://www.instagram.com/p/ABC/', '--expected-text', 'original caption')
        self.assertEqual(code, 10, err)
        self.assertIn('验证', err)
        self.assertEqual(self.context.pages[-1].delete_clicks, 0)
        self.assertTrue(self.context.closed)

    def test_setup_fault_and_cancel_release_owned_context_and_lease(self):
        import asyncio
        from unittest.mock import AsyncMock
        self.profile()
        for error in (OSError('page failed'), asyncio.CancelledError()):
            self.context.closed = False
            with patch.object(self.context, 'new_page', AsyncMock(side_effect=error)):
                if isinstance(error, asyncio.CancelledError):
                    with self.assertRaises(asyncio.CancelledError): self.run_cli('check', '--account', 'Creator')
                else:
                    code, _, err = self.run_cli('check', '--account', 'Creator')
                    self.assertEqual(code, 1, err)
                    self.assertIn('page failed', err)
            self.assertTrue(self.context.closed)
            with acquire_local_profile('instagram', 'Creator', 'chrome'): pass

    def test_config_errors_source_failure_and_reset_do_not_fallback(self):
        self.profile()
        self.profile('chromium')
        with patch.object(conf, 'LOCAL_BROWSER', 'typo', create=True):
            self.assertEqual(self.run_cli('check', '--account', 'Creator')[0], 2)
            self.assertEqual(self.run_cli('check', '--account', 'Creator', '--local-browser', 'chromium')[0], 0)
        self.pw.chromium.launch_error = OSError('browser missing')
        code, _, err = self.run_cli('check', '--account', 'Creator', '--headed')
        self.assertEqual(code, 1, err)
        self.assertIn('channel=chrome', err)
        self.assertFalse(self.pw.chromium.launch_calls)
        calls = len(self.pw.chromium.persistent_calls)
        with patch.object(conf, 'LOCAL_CHROME_PATH', '/nonexistent'):
            code, _, err = self.run_cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.pw.chromium.persistent_calls), calls)
        self.assertTrue((self.root / 'browser_profiles/chromium/instagram/Creator').exists())
        self.assertFalse((self.root / 'browser_profiles/chrome/instagram/Creator').exists())

    def test_http_failure_is_not_a_valid_login_even_with_residual_navigation(self):
        self.profile()
        self.context.response_status = 503
        code, _, err = self.run_cli('check', '--account', 'Creator')
        self.assertEqual(code, 1, err)
        self.assertIn('503', err)

    def test_custom_product_kind_wins_and_same_kind_reuses_profile(self):
        import plistlib
        self.profile('chromium')
        executable = self.root / 'Renamed.app/Contents/MacOS/browser'
        executable.parent.mkdir(parents=True)
        executable.write_text('fixture'); executable.chmod(0o755)
        (executable.parent.parent / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'org.chromium.Chromium','CFBundleName':'Chromium','CFBundleExecutable':'browser','CFBundleShortVersionString':'123'}))
        with patch.object(conf, 'LOCAL_CHROME_PATH', str(executable)), patch('utils.local_browser.sys.platform', 'darwin'):
            code, _, err = self.run_cli('check', '--account', 'Creator', '--local-browser', 'irrelevant', '--headed')
        self.assertEqual(code, 0, err)
        custom = self.pw.chromium.persistent_calls[-1]
        self.assertEqual(custom['executable_path'], str(executable))
        self.assertNotIn('channel', custom)
        code, _, err = self.run_cli('check', '--account', 'Creator', '--local-browser', 'chromium')
        self.assertEqual(code, 0, err)
        self.assertEqual(self.pw.chromium.persistent_calls[-1]['user_data_dir'], custom['user_data_dir'])


class ComposerLocator(Locator):
    def __init__(self, page, kind, count=1):
        super().__init__(count)
        self.page, self.kind = page, kind
    @property
    def last(self): return self
    def filter(self, **kwargs):
        if 'has' in kwargs and getattr(kwargs['has'], 'kind', None) == 'absent':
            return ComposerLocator(self.page, 'absent', 0)
        return self
    def get_by_role(self, role, **kwargs):
        return ComposerLocator(self.page, {'heading':'heading', 'button':'action'}.get(role, role), self.value)
    def locator(self, selector): return self.page.locator(selector)
    async def wait_for(self, **kwargs):
        if not self.value: raise main.BrowserTimeoutError('absent prompt')
    async def is_enabled(self, **kwargs): return True
    async def is_visible(self): return True
    async def bounding_box(self): return {'x':0, 'y':0, 'width':80, 'height':30}
    async def evaluate(self, script, *args):
        # DOM facts and hit-test boundary used by publish readiness.
        return {'isConnected':True, 'disabled':False, 'self':True}
    async def hover(self): pass
    async def click(self):
        if self.kind == 'action':
            if self.page.step < 2:
                self.page.step += 1
                if self.page.step == 2 and getattr(self.page.context, 'expire_during_edit', False):
                    self.page.url = 'https://www.instagram.com/challenge/'
            else:
                self.page.share_clicks += 1
                self.page.submit_response()
                if getattr(self.page.context, 'outcome', None) == 'click-login':
                    self.page.url = 'https://www.instagram.com/accounts/login/'
                    raise OSError('click response lost after dispatch')
    async def set_input_files(self, files): self.page.files = files
    async def inner_text(self): return str(self.page.step) if self.kind == 'heading' else self.page.caption
    async def focus(self): pass


class ComposerPage(Page):
    def __init__(self, context):
        super().__init__(context)
        self.step, self.share_clicks, self.caption, self.files = 0, 0, '', []
        self.keyboard = self
        self.listeners = {}
    def get_by_role(self, role, **kwargs): return ComposerLocator(self, role)
    def locator(self, selector):
        if 'direct/inbox' in selector or selector == 'a[href]': return super().locator(selector)
        if 'launcher.png' in selector or 'reels_nux' in selector: return ComposerLocator(self, 'absent', 0)
        if 'svg[aria-label="帖子"]' in selector: return ComposerLocator(self, 'absent', 0)
        return ComposerLocator(self, 'editor' if 'contenteditable' in selector else 'entry')
    async def press(self, key):
        if key == 'Delete': self.caption = ''
    async def insert_text(self, text): self.caption += text
    async def add_locator_handler(self, *args, **kwargs): pass
    async def remove_locator_handler(self, *args): pass
    def on(self, event, callback): self.listeners[event] = callback
    def remove_listener(self, event, callback): self.listeners.pop(event, None)
    def submit_response(self):
        from types import SimpleNamespace
        page = self
        outcome = getattr(self.context, 'outcome', 'success')
        class Response:
            url = 'https://www.instagram.com/api/v1/media/configure/'
            request = SimpleNamespace(method='POST')
            async def text(self):
                if outcome in ('login', 'verification'):
                    page.url = 'https://www.instagram.com/' + ('challenge/' if outcome == 'verification' else 'accounts/login/')
                    raise OSError('response interrupted by login')
                if outcome == 'unknown': return '{}'
                import json
                return json.dumps({'status':'ok','media':{'code':'ABC','id':'123_42','user':{'pk':page.context.user_id},'caption':{'text':page.caption}}})
        self.listeners['response'](Response())
    async def screenshot(self, **kwargs): raise OSError('screenshot unavailable')
    async def content(self): return '<html></html>'


class PostLocator(ComposerLocator):
    def filter(self, **kwargs):
        if 'has_text' in kwargs: return PostLocator(self.page, 'confirm-delete' if self.kind == 'confirm-buttons' else 'delete-item')
        return self
    def get_by_role(self, role, **kwargs):
        if role == 'button': return PostLocator(self.page, 'confirm-buttons' if self.kind == 'confirm' else 'menu-buttons', 2 if self.kind == 'confirm' else 9)
        return PostLocator(self.page, role)
    async def get_attribute(self, name):
        return {'canonical':'https://www.instagram.com/p/ABC/', 'owner':'42', 'caption':'original caption', 'deep-link':'instagram://media?id=123'}.get(self.kind)
    async def inner_text(self): return 'original caption'
    async def press(self, key):
        if self.kind == 'confirm-delete': self.page.delete_clicks += 1


class PostPage(ComposerPage):
    async def goto(self, url, **kwargs):
        await super().goto(url, **kwargs)
        if '/p/' in url and getattr(self.context, 'works_expiry', False): self.url = 'https://www.instagram.com/challenge/'
    def __init__(self, context): super().__init__(context); self.delete_clicks = 0
    def locator(self, selector):
        kinds = {'meta[property="og:url"]':'canonical', 'meta[property="instapp:owner_user_id"]':'owner', 'meta[name="description"]':'caption', 'meta[property="al:ios:url"]':'deep-link', '[role="dialog"][aria-modal="true"]':'confirm', 'main':'main'}
        if selector in kinds: return PostLocator(self, kinds[selector])
        if 'aria-haspopup' in selector: return PostLocator(self, 'menu')
        return super().locator(selector)
    def get_by_role(self, role, **kwargs): return PostLocator(self, role)
    def expect_response(self, predicate, **kwargs):
        from types import SimpleNamespace
        class Response:
            url = 'https://www.instagram.com/api/v1/web/create/123_42/delete/'
            request = SimpleNamespace(method='POST')
            async def text(self): return '{"payload":{"did_delete":true}}'
        response = Response()
        assert predicate(response)
        class Event:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            @property
            async def value(self): return response
        return Event()
