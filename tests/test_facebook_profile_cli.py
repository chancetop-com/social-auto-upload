"""Formal Facebook CLI through real config/Profile/session, with browser boundaries."""
import asyncio
import io
import os
import tempfile
import unittest
from contextlib import ExitStack, chdir, redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import conf
import sau_cli
from sau_commands import facebook
from tests.fakes import FakeContext, FakePlaywright
from tests.fakes_clock import FakeClock
from tests.test_mlx_tiktok import _AsyncCM
from uploader import publish_timeout
from uploader.meta_uploader.facebook_uploader import main, posts
from utils.local_profile import acquire_local_profile


class Locator:
    def __init__(self, count=1): self.value = count
    @property
    def first(self): return self
    async def count(self): return self.value
    async def is_visible(self): return bool(self.value)
    async def wait_for(self, **kwargs):
        if not self.value: raise RuntimeError('missing page anchor')


class Page:
    def __init__(self, context): self.context, self.url = context, 'about:blank'
    async def goto(self, url, **kwargs):
        if self.context.state == 'network': raise OSError('network unavailable')
        self.url = {'login':'https://www.facebook.com/login/', 'verification':'https://www.facebook.com/checkpoint/'}.get(self.context.state, url)
        return SimpleNamespace(status=getattr(self.context, 'status', 200))
    def locator(self, selector):
        if selector == main.FACEBOOK_LOGIN_INPUT: return Locator(int(self.context.state == 'login'))
        if selector == main.FACEBOOK_MEDIA_INPUT: return Locator(int(self.context.state == 'valid'))
        return Locator()
    def set_default_timeout(self, value): pass
    async def wait_for_timeout(self, value): pass
    async def close(self):
        if getattr(self.context, 'hang_page_close', False): await asyncio.Event().wait()


class DelayedComposerPage(Page):
    def locator(self, selector):
        if selector != main.FACEBOOK_MEDIA_INPUT: return super().locator(selector)
        page = self
        class DelayedInput(Locator):
            async def count(self): return int(getattr(page, 'mounted', False))
            async def wait_for(self, **kwargs): page.mounted = True
        return DelayedInput()


class Context(FakeContext):
    def __init__(self):
        super().__init__()
        self.state, self.user_id = 'valid', '42'
    async def new_page(self):
        page = getattr(self, 'page_type', Page)(self)
        self.pages.append(page)
        return page
    async def cookies(self, *args):
        return [{'name':'c_user','value':self.user_id}] if self.user_id else []


class Expect:
    def __init__(self, locator): self.locator = locator
    async def to_have_count(self, count, **kwargs):
        if await self.locator.count() != count: raise RuntimeError('unexpected page structure')
    async def to_be_visible(self, **kwargs):
        if not await self.locator.is_visible(): raise RuntimeError('hidden control')
    async def to_contain_text(self, text, **kwargs):
        if text not in await self.locator.inner_text(): raise RuntimeError('caption mismatch')


class ComposerLocator(Locator):
    def __init__(self, page, kind, count=1):
        super().__init__(count); self.page, self.kind = page, kind
    @property
    def last(self): return self
    def nth(self, index): return self
    def get_by_role(self, role, **kwargs): return ComposerLocator(self.page, 'publish')
    async def is_enabled(self, *, timeout=None): return True
    async def hover(self): pass
    async def click(self):
        if self.kind == 'publish':
            self.page.submit_clicks += 1
            outcome = getattr(self.page.context, 'outcome', 'success')
            if outcome in ('login', 'verification', 'click-login'):
                self.page.url = 'https://www.facebook.com/' + ('checkpoint/' if outcome == 'verification' else 'login/')
                if outcome == 'click-login': raise OSError('response lost after dispatch')
    async def set_input_files(self, files, *, timeout=None): self.page.files = files
    async def inner_text(self, *, timeout=None): return self.page.caption


class ComposerPage(Page):
    def __init__(self, context):
        super().__init__(context)
        self.submit_clicks, self.caption, self.files = 0, '', []
        self.keyboard = self
    def locator(self, selector):
        if self.submit_clicks and getattr(self.context, 'outcome', None) == 'disconnected':
            raise OSError('page disconnected')
        if selector == main.FACEBOOK_LOGIN_INPUT: return super().locator(selector)
        return ComposerLocator(self, 'editor' if 'contenteditable' in selector else 'entry', 0 if '[role="alert"]' in selector else 1)
    def get_by_text(self, text):
        return ComposerLocator(self, 'success', int(self.submit_clicks > 0 and getattr(self.context, 'outcome', 'success') == 'success'))
    async def press(self, key):
        if key == 'Delete': self.caption = ''
    async def insert_text(self, text):
        self.caption += text
        if getattr(self.context, 'expire_during_edit', False): self.url = 'https://www.facebook.com/checkpoint/'
    async def wait_for_timeout(self, value):
        if self.submit_clicks and getattr(self.context, 'outcome', 'success') != 'success':
            raise TimeoutError('platform response lost')


class PostLocator(Locator):
    def __init__(self, page, kind): super().__init__(); self.page, self.kind = page, kind
    async def count(self):
        if self.kind == 'article': return int(not self.page.trashed)
        if self.kind in ('row', 'link'): return int(not self.page.deleted)
        if self.kind == 'dialog': return int(self.page.dialog)
        return 1
    async def all(self): return [self] if await self.count() else []
    def filter(self, **kwargs):
        if 'has_text' in kwargs and self.kind == 'article' and kwargs['has_text'] != 'original caption':
            raise RuntimeError('expected-text mismatch')
        return self
    def locator(self, selector):
        if 'ancestor::div' in selector: return PostLocator(self.page, 'row')
        return self
    def get_by_role(self, role, **kwargs):
        if self.kind == 'dialog': return PostLocator(self.page, 'confirm')
        return PostLocator(self.page, 'menuitem' if role == 'menuitem' else 'menu-button')
    async def evaluate_all(self, expr):
        if self.kind == 'link' and self.page.deleted: return []
        return ['https://www.facebook.com/reel/123/', f'https://www.facebook.com/profile.php?id={getattr(self.page.context, "author_id", "42")}']
    async def get_attribute(self, name): return 'https://www.facebook.com/reel/123/'
    async def inner_text(self): return 'original caption 你删除的内容将无法恢复。'
    async def click(self):
        if self.kind == 'menuitem': self.page.dialog = True
        if self.kind == 'confirm':
            self.page.delete_clicks += 1
            if self.page.trashed: self.page.deleted = True
            else: self.page.trashed = True
            self.page.dialog = False
    async def is_visible(self): return self.page.deleted if self.kind == 'empty' else True


class PostPage(Page):
    def __init__(self, context):
        super().__init__(context)
        self.trashed = getattr(context, 'trashed', False)
        self.deleted = getattr(context, 'deleted', False)
        self.dialog, self.delete_clicks = False, 0
    async def goto(self, url, **kwargs):
        response = await super().goto(url, **kwargs)
        if ('profile.php' in url or 'allactivity' in url) and getattr(self.context, 'works_expiry', False):
            self.url = 'https://www.facebook.com/checkpoint/'
        return response
    def get_by_role(self, role, **kwargs): return PostLocator(self, role)
    def get_by_text(self, text, **kwargs): return PostLocator(self, 'empty' if text.startswith('好冷清') else 'text')


class FacebookProfileCliTests(unittest.TestCase):
    def test_managed_upload_classifies_verification_and_login(self):
        app = main.FacebookPost('title', 'video.mp4', '', [])
        for path, reason in (('/captcha/', 'verification'), ('/two_step_verification/', 'verification'),
                             ('/checkpoint/', 'verification'), ('/login/', 'login')):
            with self.subTest(path=path):
                page = ComposerPage(Context())
                page.url = 'https://www.facebook.com' + path
                with self.assertRaises(main.LoginRequiredError) as caught:
                    asyncio.run(app._wait_until_publishable(page, app._ensure_publish_budget()))
                self.assertEqual(caught.exception.reason, reason)
                self.assertFalse(caught.exception.publish_attempted)

    def test_remounted_publish_button_is_retried_within_the_same_budget(self):
        page = ComposerPage(Context())
        app = main.FacebookPost('title', 'video.mp4', '', [])
        clock = FakeClock()
        probes = []

        async def enabled(button, *, timeout):
            probes.append(timeout)
            if len(probes) == 1:
                clock.advance(timeout / 1000)
                raise main.BrowserTimeoutError('button detached')
            return True

        page.wait_for_timeout = AsyncMock(side_effect=lambda ms: clock.advance(ms / 1000))
        with clock.patch(publish_timeout), patch.object(ComposerLocator, 'is_enabled', enabled):
            budget = app._ensure_publish_budget()
            clock.advance(897.5)
            asyncio.run(app._wait_until_publishable(page, budget))
        self.assertEqual(probes, [1000, 500])
        self.assertEqual(clock.now, 899.5)
        self.assertEqual(page.submit_clicks, 0)

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
        for module in (main, posts, facebook):
            self.stack.enter_context(patch.object(module, 'async_playwright', lambda: _AsyncCM(self.pw)))
        self.addCleanup(self.stack.close)
    def run_cli(self, *argv):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            code = sau_cli.main(['facebook', *argv])
        return code, out.getvalue(), err.getvalue()
    def profile(self, kind='chrome', platform='facebook'):
        with acquire_local_profile(platform, 'Creator', kind, create=True): pass

    def test_check_uses_selected_profile_config_and_ignores_legacy_json(self):
        self.profile()
        (self.root / 'cookies').mkdir()
        old = self.root / 'cookies/facebook_Creator.json'
        old.write_text('broken old credentials')
        code, _, err = self.run_cli('check', '--account', 'Creator', '--proxy', 'http://localhost:7890')
        self.assertEqual(code, 0, err)
        self.assertEqual(self.pw.chromium.persistent_calls, [{
            'user_data_dir': str(self.root / 'browser_profiles/chrome/facebook/Creator'),
            'channel':'chrome', 'headless':True, 'no_viewport':True,
            'proxy':{'server':'http://localhost:7890'},
        }])
        self.assertEqual(old.read_text(), 'broken old credentials')
        self.assertFalse(self.context.storage_state_calls)
        self.assertTrue(self.context.closed)

    def test_login_reuses_alias_allows_new_user_and_separates_browser_and_page(self):
        self.profile(platform='facebook-page')
        for user_id, flags in [('42', []), ('77', ['--headed']), ('91', ['--local-browser', 'chromium'])]:
            self.context.user_id = user_id
            code, _, err = self.run_cli('login', '--account', 'Creator', *flags)
            self.assertEqual(code, 0, err)
        calls = self.pw.chromium.persistent_calls
        self.assertEqual(len(calls), 3)
        self.assertEqual([c['headless'] for c in calls], [True, False, True])
        self.assertEqual(calls[0]['user_data_dir'], calls[1]['user_data_dir'])
        self.assertTrue(calls[2]['user_data_dir'].endswith('/chromium/facebook/Creator'))
        self.assertFalse(self.context.storage_state_calls)
        self.assertFalse((self.root / 'cookies').exists())
        code, _, err = self.run_cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')
        self.assertEqual(code, 0, err)
        self.assertFalse((self.root / 'browser_profiles/chrome/facebook/Creator').exists())
        self.assertTrue((self.root / 'browser_profiles/chromium/facebook/Creator').exists())
        self.assertTrue((self.root / 'browser_profiles/chrome/facebook-page/Creator').exists())

    def test_check_classifies_missing_login_verification_and_page_failures(self):
        self.assertEqual(self.run_cli('check', '--account', 'Creator')[0], 10)
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.profile()
        for state, code in [('login',10), ('verification',10), ('network',1), ('unknown',1), ('valid',0)]:
            with self.subTest(state=state):
                self.context.state = state
                actual, _, err = self.run_cli('check', '--account', 'Creator')
                self.assertEqual(actual, code, err)
                if state == 'verification': self.assertIn('验证', err)
        self.context.status = 503
        code, _, err = self.run_cli('check', '--account', 'Creator')
        self.assertEqual(code, 1, err)
        self.assertIn('503', err)

    def test_check_waits_for_the_homepage_composer_to_mount(self):
        self.profile()
        self.context.page_type = DelayedComposerPage
        code, _, err = self.run_cli('check','--account','Creator')
        self.assertEqual(code, 0, err)

    def test_video_and_note_publish_once_in_one_profile_without_legacy_files(self):
        self.profile()
        self.context.page_type = ComposerPage
        self.stack.enter_context(patch.object(main, 'expect', Expect))
        for action, option, filename in [('upload-video','--file','video.mp4'), ('upload-note','--images','photo.png')]:
            with self.subTest(action=action):
                path = self.root / filename; path.touch()
                code, _, err = self.run_cli(action, '--account', 'Creator', option, str(path), '--title', 'caption', '--headed')
                self.assertEqual(code, 0, err)
                page = self.context.pages[-1]
                self.assertEqual(page.files, [str(path)])
                self.assertEqual(page.caption, 'caption')
                self.assertEqual(page.submit_clicks, 1)
                self.assertTrue(self.context.closed)
                self.assertFalse(self.context.storage_state_calls)
        self.assertEqual(len(self.pw.chromium.persistent_calls), 2)
        self.assertFalse(self.pw.chromium.launch_calls)

    def test_expiry_before_and_after_submit_preserves_phase_through_cleanup_failure(self):
        self.profile()
        self.context.page_type = ComposerPage
        self.context.close_error = OSError('cleanup failed')
        self.stack.enter_context(patch.object(main, 'expect', Expect))
        path = self.root / 'photo.png'; path.touch()
        argv = ('upload-note', '--account', 'Creator', '--images', str(path), '--title', 'caption')
        self.context.expire_during_edit = True
        code, _, err = self.run_cli(*argv)
        self.assertEqual(code, 10, err)
        self.assertIn('验证', err)
        self.assertEqual(self.context.pages[-1].submit_clicks, 0)
        self.context.expire_during_edit = False
        for outcome, expected in [('success',0), ('unknown',9), ('disconnected',9), ('login',10), ('verification',10), ('click-login',10)]:
            with self.subTest(outcome=outcome):
                self.context.outcome = outcome
                code, _, err = self.run_cli(*argv)
                self.assertEqual(code, expected, err)
                self.assertEqual(self.context.pages[-1].submit_clicks, 1)
                if expected == 10: self.assertIn('publish_attempted=true', err)
                with acquire_local_profile('facebook', 'Creator', 'chrome'): pass

    def test_works_remain_local_with_provider_env_and_keep_historical_evidence(self):
        self.profile('chromium')
        self.context.page_type = PostPage
        self.stack.enter_context(patch.object(posts, 'expect', Expect))
        argv = ('--account','Creator','--local-browser','chromium','--post-url','https://www.facebook.com/reel/123/',
                '--owner-id','42','--expected-text','original caption')
        for provider in ({'MLX_API_TOKEN':'unused'}, {'ADSPOWER_API_KEY':'unused'}):
            with patch.dict(os.environ, provider):
                for action in ('verify', 'delete'):
                    code, out, err = self.run_cli(action, *argv)
                    self.assertEqual(code, 0, err)
                    self.assertIn('trashed' if action == 'delete' else 'found', out)
                    self.assertEqual(self.context.pages[-1].delete_clicks, int(action == 'delete'))
                self.assertEqual(self.run_cli('verify', *argv[2:])[0], 2)
        self.assertFalse(self.context.storage_state_calls)
        self.assertEqual(len(self.pw.chromium.persistent_calls), 4)
        self.assertTrue(all(c['user_data_dir'].endswith('/chromium/facebook/Creator') for c in self.pw.chromium.persistent_calls))
        self.context.user_id = '77'
        self.assertEqual(self.run_cli('delete', *argv)[0], 1)
        self.assertEqual(self.context.pages[-1].delete_clicks, 0)

        self.context.user_id, self.context.author_id = '42', '77'
        self.assertEqual(self.run_cli('delete', *argv)[0], 1)
        self.assertEqual(self.context.pages[-1].delete_clicks, 0)

    def test_trash_permanent_deleted_and_expiry_preserve_action_semantics(self):
        self.profile()
        self.context.page_type = PostPage
        self.stack.enter_context(patch.object(posts, 'expect', Expect))
        argv = ('--account','Creator','--post-url','https://www.facebook.com/reel/123/',
                '--owner-id','42','--expected-text','original caption')
        for action, flags, trashed, deleted, expected, clicks in [
            ('verify',['--from-trash'],True,False,'trashed',0),
            ('delete',['--from-trash','--permanent'],True,False,'deleted',1),
            ('delete',['--permanent'],False,False,'deleted',2),
            ('verify',['--deleted'],True,True,'absent_from_trash',0),
        ]:
            with self.subTest(action=action, flags=flags):
                self.context.trashed, self.context.deleted = trashed, deleted
                code, out, err = self.run_cli(action, *argv, *flags, '--result', str(self.root/'result.json'))
                self.assertEqual(code, 0, err)
                self.assertIn(expected, out)
                self.assertEqual(self.context.pages[-1].delete_clicks, clicks)
        self.context.works_expiry = True
        self.context.close_error = OSError('cleanup unavailable')
        code, _, err = self.run_cli('delete', *argv)
        self.assertEqual(code, 10, err)
        self.assertIn('验证', err)
        self.assertEqual(self.context.pages[-1].delete_clicks, 0)

    def test_direct_calls_use_defaults_explicit_false_and_borrow_session(self):
        from utils.browser_session import BrowserSession
        self.profile()
        self.assertTrue(asyncio.run(main.facebook_cookie_auth('/not/read/facebook_Creator.json', headless=False)))
        self.assertFalse(self.pw.chromium.persistent_calls[-1]['headless'])
        self.context.page_type = ComposerPage
        self.stack.enter_context(patch.object(main, 'expect', Expect))
        path = self.root / 'video.mp4'; path.touch()
        app = main.FacebookVideo('caption', path, '', [], account_name='Creator')
        asyncio.run(app.main())
        self.assertTrue(self.pw.chromium.persistent_calls[-1]['headless'])
        self.context.closed = False
        session = BrowserSession(browser=self.context.browser, context=self.context, mode='local')
        asyncio.run(app.main(session=session))
        self.assertFalse(self.context.closed)
        self.assertEqual(len(self.pw.chromium.persistent_calls), 2)
        self.context.page_type = PostPage
        self.stack.enter_context(patch.object(posts, 'expect', Expect))
        result = asyncio.run(posts.facebook_post_action('/not/read/facebook_Creator.json',
            post_url='https://www.facebook.com/reel/123/', owner_id='42', expected_text='original caption', session=session))
        self.assertEqual(result['status'], 'found')
        self.assertFalse(self.context.closed)

    def test_setup_fault_cancel_and_hanging_page_close_release_owned_session(self):
        from unittest.mock import AsyncMock
        self.profile()
        for error in (OSError('new page failed'), asyncio.CancelledError()):
            self.context.closed = False
            with patch.object(self.context, 'new_page', AsyncMock(side_effect=error)):
                if isinstance(error, asyncio.CancelledError):
                    with self.assertRaises(asyncio.CancelledError): self.run_cli('check', '--account', 'Creator')
                else:
                    code, _, err = self.run_cli('check', '--account', 'Creator')
                    self.assertEqual(code, 1, err)
                    self.assertIn('new page failed', err)
            self.assertTrue(self.context.closed)
            with acquire_local_profile('facebook', 'Creator', 'chrome'): pass
        self.context.hang_page_close = True
        self.assertEqual(self.run_cli('check', '--account', 'Creator')[0], 0)
        async def hung_close(): await asyncio.Event().wait()
        with patch.object(self.context, 'close', hung_close), patch('utils.local_browser_session.CLOSE_TIMEOUT_SECONDS', .01):
            self.assertEqual(self.run_cli('check', '--account', 'Creator')[0], 0)
        with acquire_local_profile('facebook', 'Creator', 'chrome'): pass

    def test_managed_ignores_local_settings_preserves_logs_and_ownership(self):
        from tests.fakes import FakeManagedProvider, FakeBrowser
        from loguru import logger
        for mode in ('multilogin', 'adspower'):
            provider, context = FakeManagedProvider(mode=mode), Context()
            self.pw.chromium.queue_connect_browser(FakeBrowser([context]))
            logs = []
            sink = logger.add(lambda message: logs.append(str(message)), format='{message}')
            try:
                with patch.object(facebook, 'resolve_managed_provider', return_value=provider), patch.object(conf, 'LOCAL_BROWSER', [], create=True), patch.object(conf, 'LOCAL_CHROME_PATH', []):
                    code, _, err = self.run_cli('check', '--account', 'Creator', '--local-browser', 'ignored')
                self.assertEqual(code, 0, err)
                self.assertEqual(provider.start_calls, [True])
                self.assertEqual(provider.stop_calls, 1)
                self.assertFalse(context.closed)
                self.assertIn('launch_kwargs', ''.join(logs))
                self.assertIn('identity=profile:profile', ''.join(logs))
            finally: logger.remove(sink)
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.assertFalse((self.root / 'browser_profiles').exists())

    def test_managed_checkpoint_during_upload_exits_ten_before_submission(self):
        from tests.fakes import FakeBrowser, FakeManagedProvider
        self.stack.enter_context(patch.object(main, 'expect', Expect))
        path = self.root / 'video.mp4'
        path.touch()
        for mode in ('multilogin', 'adspower'):
            with self.subTest(mode=mode):
                context = Context()
                context.page_type = ComposerPage
                context.expire_during_edit = True
                provider = FakeManagedProvider(mode=mode)
                self.pw.chromium.queue_connect_browser(FakeBrowser([context]))
                with patch.object(facebook, 'resolve_managed_provider', return_value=provider):
                    code, _, err = self.run_cli('upload-video', '--account', 'Creator', '--file', str(path), '--title', 'caption')
                self.assertEqual(code, 10, err)
                self.assertEqual(context.pages[-1].submit_clicks, 0)
                self.assertNotIn('publish_attempted=true', err)

    def test_managed_uploads_borrow_provider_context_and_ignore_local_sources(self):
        from tests.fakes import FakeManagedProvider, FakeBrowser
        self.stack.enter_context(patch.object(main, 'expect', Expect))
        for mode in ('multilogin','adspower'):
            for action, option, filename in [('upload-video','--file','video.mp4'), ('upload-note','--images','photo.png')]:
                with self.subTest(mode=mode, action=action):
                    path = self.root / filename; path.touch()
                    context, provider = Context(), FakeManagedProvider(mode=mode)
                    context.page_type = ComposerPage
                    browser = FakeBrowser([context])
                    self.pw.chromium.queue_connect_browser(browser)
                    with patch.object(facebook,'resolve_managed_provider',return_value=provider), patch.object(conf,'LOCAL_CHROME_PATH',[]), patch.object(conf,'LOCAL_BROWSER',[],create=True):
                        code, _, err = self.run_cli(action,'--account','Creator',option,str(path),'--title','caption','--headed','--local-browser','ignored')
                    self.assertEqual(code,0,err)
                    self.assertEqual(provider.start_calls,[False])
                    self.assertEqual(provider.stop_calls,1)
                    self.assertEqual(context.pages[-1].submit_clicks,1)
                    self.assertFalse(context.closed)
                    self.assertFalse(context.storage_state_calls)
                    self.assertFalse(browser.new_context_calls)
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.assertFalse(self.pw.chromium.launch_calls)
        self.assertFalse((self.root/'browser_profiles').exists())

    def test_configuration_selection_failure_occupancy_and_reset_without_binary(self):
        self.profile()
        self.profile('chromium')
        with patch.object(conf, 'LOCAL_BROWSER', 'bad', create=True):
            self.assertEqual(self.run_cli('check','--account','Creator')[0], 2)
            self.assertEqual(self.run_cli('check','--account','Creator','--local-browser','chromium')[0], 0)
        self.pw.chromium.launch_error = OSError('browser missing')
        code, _, err = self.run_cli('check','--account','Creator','--headed')
        self.assertEqual(code, 1, err)
        self.assertIn('channel=chrome', err)
        self.assertFalse(self.pw.chromium.launch_calls)
        calls = len(self.pw.chromium.persistent_calls)
        with acquire_local_profile('facebook','Creator','chrome'):
            self.assertEqual(self.run_cli('check','--account','Creator')[0], 1)
            self.assertEqual(self.run_cli('reset-profile','--account','Creator','--browser-kind','chrome')[0], 1)
        with patch.object(conf,'LOCAL_CHROME_PATH','/nonexistent'):
            self.assertEqual(self.run_cli('reset-profile','--account','Creator','--browser-kind','chrome')[0], 0)
        self.assertEqual(len(self.pw.chromium.persistent_calls), calls)

    def test_custom_product_kind_wins_and_missing_optional_setting_defaults_to_chrome(self):
        import plistlib
        self.profile(); self.profile('chromium')
        if hasattr(conf, 'LOCAL_BROWSER'):
            value = conf.LOCAL_BROWSER
            del conf.LOCAL_BROWSER
            self.addCleanup(setattr, conf, 'LOCAL_BROWSER', value)
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', False):
            code, _, err = self.run_cli('check', '--account', 'Creator')
        self.assertEqual(code, 0, err)
        self.assertFalse(self.pw.chromium.persistent_calls[-1]['headless'])
        executable = self.root / 'Renamed.app/Contents/MacOS/browser'
        executable.parent.mkdir(parents=True); executable.write_text('fixture'); executable.chmod(0o755)
        (executable.parent.parent / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'org.chromium.Chromium', 'CFBundleName':'Chromium','CFBundleExecutable':'browser','CFBundleShortVersionString':'123'}))
        with patch.object(conf,'LOCAL_CHROME_PATH',str(executable)), patch('utils.local_browser.sys.platform','darwin'):
            code, _, err = self.run_cli('check','--account','Creator','--local-browser','ignored','--headed')
        self.assertEqual(code, 0, err)
        custom = self.pw.chromium.persistent_calls[-1]
        self.assertEqual(custom['executable_path'],str(executable)); self.assertNotIn('channel',custom)
        self.assertEqual(self.run_cli('check','--account','Creator','--local-browser','chromium')[0],0)
        self.assertEqual(custom['user_data_dir'],self.pw.chromium.persistent_calls[-1]['user_data_dir'])
