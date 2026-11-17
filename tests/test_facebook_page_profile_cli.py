"""Facebook Page CLI with real Profile/config/session and external browser fakes."""
import asyncio
import io
import os
import tempfile
import unittest
from contextlib import ExitStack, chdir, redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import conf
import sau_cli
from sau_commands import facebook_page as command
from tests.fakes import FakeContext, FakePlaywright
from tests.test_mlx_tiktok import _AsyncCM
from uploader.meta_uploader.facebook_page_uploader import main, posts
from utils.local_profile import acquire_local_profile


class Locator:
    def __init__(self, count=1): self.value = count
    @property
    def first(self): return self
    def filter(self, **kwargs): return self
    async def count(self): return self.value
    async def is_visible(self): return bool(self.value)
    async def wait_for(self, **kwargs):
        if not self.value: raise RuntimeError('missing page evidence')


class Page:
    def __init__(self, context): self.context, self.url = context, 'about:blank'
    async def goto(self, url, **kwargs):
        if self.context.state == 'network': raise OSError('network unavailable')
        self.url = {'login':'https://www.facebook.com/login/', 'verification':'https://www.facebook.com/checkpoint/'}.get(self.context.state, url)
        return SimpleNamespace(status=(getattr(self.context,'business_status',getattr(self.context,'status',200)) if len(self.context.pages) > 1 else getattr(self.context,'status',200)))
    def locator(self, selector):
        if 'input[name="email"]' in selector: return Locator(int(self.context.state == 'login'))
        if '/latest/home' in selector: return Locator(int(self.context.state == 'valid'))
        return Locator()
    async def wait_for_timeout(self, ms): pass
    def set_default_timeout(self, ms): pass
    async def close(self):
        if getattr(self.context, 'hanging_page_close', False): await asyncio.Event().wait()


class Context(FakeContext):
    def __init__(self):
        super().__init__()
        self.state = 'valid'
    async def new_page(self):
        page = getattr(self, 'page_type', Page)(self)
        self.pages.append(page)
        return page


class FacebookPageProfileCliTests(unittest.TestCase):
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
        for module in (command, main, posts):
            self.stack.enter_context(patch.object(module, 'async_playwright', lambda: _AsyncCM(self.pw)))
        self.addCleanup(self.stack.close)
    def profile(self, kind='chrome', platform='facebook-page'):
        with acquire_local_profile(platform, 'Creator', kind, create=True) as profile: return profile.path
    def run_cli(self, *argv):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            code = sau_cli.main(['facebook-page', *argv])
        return code, out.getvalue(), err.getvalue()

    def test_check_uses_persistent_profile_without_reading_legacy_json(self):
        self.profile()
        old = self.root / 'cookies/facebook-page_Creator.json'
        old.parent.mkdir(); old.write_text('broken credentials')
        code, _, err = self.run_cli('check', '--account', 'Creator', '--proxy', 'http://localhost:7890')
        self.assertEqual(code, 0, err)
        self.assertEqual(self.pw.chromium.persistent_calls, [{
            'user_data_dir':str(self.root / 'browser_profiles/chrome/facebook-page/Creator'),
            'channel':'chrome', 'headless':True, 'no_viewport':True,
            'proxy':{'server':'http://localhost:7890'},
        }])
        self.assertEqual(old.read_text(), 'broken credentials')
        self.assertFalse(self.context.storage_state_calls)
        self.assertTrue(self.context.closed)

    def test_check_classifies_missing_login_verification_and_page_faults(self):
        self.assertEqual(self.run_cli('check', '--account', 'Creator')[0], 10)
        self.profile()
        for state, expected in [('login',10), ('verification',10), ('network',1), ('unknown',1), ('valid',0)]:
            with self.subTest(state=state):
                self.context.state = state
                code, _, err = self.run_cli('check', '--account', 'Creator')
                self.assertEqual(code, expected, err)
                if state == 'verification': self.assertIn('验证', err)
                self.assertTrue(self.context.closed)
        self.context.status = 503
        code, _, err = self.run_cli('check', '--account', 'Creator')
        self.assertEqual(code, 1, err)
        self.assertIn('503', err)

    def test_login_creates_and_reuses_alias_in_each_browser_without_legacy_files(self):
        for flags in ([], ['--headed'], ['--local-browser','chromium']):
            code, _, err = self.run_cli('login', '--account', 'Creator', *flags)
            self.assertEqual(code, 0, err)
        calls = self.pw.chromium.persistent_calls
        self.assertEqual(len(calls), 3)
        self.assertEqual([c['headless'] for c in calls], [True,False,True])
        self.assertEqual(calls[0]['user_data_dir'], calls[1]['user_data_dir'])
        self.assertTrue(calls[2]['user_data_dir'].endswith('/chromium/facebook-page/Creator'))
        self.assertFalse((self.root / 'cookies').exists())
        self.assertFalse(self.context.storage_state_calls)
        self.assertTrue(self.context.closed)

    def test_video_and_note_publish_to_multiple_pages_with_one_profile_session_each(self):
        self.profile()
        self.context.page_type = ComposerPage
        self.stack.enter_context(patch.object(main, 'expect', Expect))
        self.stack.enter_context(patch.object(posts, 'expect', Expect))
        for action, option, filename, target in [('upload-video','--file','clip.mp4','Page A'), ('upload-note','--images','photo.png','Page B')]:
            media = self.root / filename; media.write_bytes(b'fixture')
            code, out, err = self.run_cli(action, '--account','Creator',option,str(media),'--title','original','--page',target, '--headed')
            self.assertEqual(code, 0, err)
            page = self.context.pages[-1]
            self.assertEqual(page.files, [str(media)])
            self.assertEqual(page.selected_page, target)
            self.assertEqual(page.publish_clicks, 1)
            self.assertIn('processing' if action == 'upload-video' else 'published', out)
        calls = self.pw.chromium.persistent_calls
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]['user_data_dir'], calls[1]['user_data_dir'])
        self.assertFalse(self.context.storage_state_calls)
        self.assertTrue(self.context.closed)

    def test_expiry_and_submission_outcomes_preserve_phase_through_cleanup_failure(self):
        self.profile()
        self.context.page_type = ComposerPage
        self.context.close_error = OSError('close fault')
        self.stack.enter_context(patch.object(main, 'expect', Expect))
        self.stack.enter_context(patch.object(posts, 'expect', Expect))
        media = self.root / 'photo.png'; media.touch()
        for outcome, expected in [('success',0), ('unknown',9), ('login',10), ('verification',10), ('edit',10)]:
            self.context.outcome = outcome
            self.context.expire_during_edit = outcome == 'edit'
            code, out, err = self.run_cli('upload-note', '--account','Creator','--images',str(media),'--title','original')
            self.assertEqual(code, expected, err)
            self.assertEqual(self.context.pages[-1].publish_clicks, int(outcome != 'edit'))
            if expected == 10 and outcome != 'edit':
                self.assertIn('publish_attempted=true', err)
            if outcome == 'edit': self.assertNotIn('publish_attempted=true', err)
            if outcome in ('verification','edit'): self.assertIn('验证',err)
            with acquire_local_profile('facebook-page','Creator','chrome'): pass

    def test_explicit_page_mismatch_stops_before_publishing(self):
        self.profile()
        self.context.page_type, self.context.wrong_target = ComposerPage, True
        self.stack.enter_context(patch.object(main, 'expect', Expect))
        media = self.root / 'photo.png'; media.touch()
        code, _, err = self.run_cli('upload-note','--account','Creator','--images',str(media),'--title','original','--page','Page B')
        self.assertEqual(code, 1, err)
        self.assertEqual(self.context.pages[-1].publish_clicks, 0)

    def test_works_remain_local_with_provider_env_and_keep_original_page_evidence(self):
        self.profile('chromium')
        self.context.page_type = PostPage
        self.stack.enter_context(patch.object(posts, 'expect', Expect))
        for environment in ({'MLX_API_TOKEN':'unused'}, {'ADSPOWER_API_KEY':'unused'}):
            with patch.dict(os.environ, environment):
                for action in ('verify','delete'):
                    code, out, err = self.run_cli(action,'--account','Creator','--local-browser','chromium',
                        '--page-id','123','--page','Page A','--content-id','456','--expected-text','original')
                    self.assertEqual(code, 0, err)
                    self.assertIn('trashed' if action == 'delete' else 'published',out)
                    self.assertEqual(self.context.pages[-1].delete_clicks,int(action == 'delete'))
                    self.assertTrue(self.context.closed)
        self.assertEqual(len(self.pw.chromium.persistent_calls),4)
        self.assertFalse(self.context.storage_state_calls)
        self.context.author_page = 'Different Page'
        code, _, err = self.run_cli('delete','--account','Creator','--local-browser','chromium',
            '--page-id','123','--page','Page A','--content-id','456','--expected-text','original')
        self.assertEqual(code,1,err)
        self.assertEqual(self.context.pages[-1].delete_clicks,0)

    def test_reset_is_exact_requires_no_binary_and_refuses_occupied_profile(self):
        chrome = self.profile(); chromium = self.profile('chromium')
        facebook = self.profile(platform='facebook')
        with acquire_local_profile('facebook-page','Creator','chrome'):
            self.assertEqual(self.run_cli('reset-profile','--account','Creator','--browser-kind','chrome')[0],1)
        with patch.object(conf,'LOCAL_CHROME_PATH','/missing/browser'):
            code, _, err = self.run_cli('reset-profile','--account','Creator','--browser-kind','chrome')
        self.assertEqual(code,0,err)
        self.assertFalse(chrome.exists())
        self.assertTrue(chromium.exists()); self.assertTrue(facebook.exists())
        self.assertFalse(self.pw.chromium.persistent_calls)

    def test_managed_ignores_local_config_and_preserves_provider_ownership_and_logs(self):
        from tests.fakes import FakeManagedProvider, FakeBrowser
        from loguru import logger
        for mode in ('multilogin','adspower'):
            provider = FakeManagedProvider(mode=mode)
            context = Context()
            self.pw.chromium.queue_connect_browser(FakeBrowser([context]))
            logs = []
            sink = logger.add(lambda message: logs.append(str(message)),format='{message}')
            try:
                with patch.object(command,'resolve_managed_provider',return_value=provider), patch.object(conf,'LOCAL_BROWSER',[],create=True), patch.object(conf,'LOCAL_CHROME_PATH',[]):
                    code, _, err = self.run_cli('check','--account','Creator','--local-browser','ignored')
                self.assertEqual(code,0,err)
                self.assertEqual(provider.start_calls,[True])
                self.assertEqual(provider.stop_calls,1)
                self.assertFalse(context.closed)
                self.assertIn('launch_kwargs',''.join(logs))
            finally: logger.remove(sink)
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.assertFalse((self.root/'browser_profiles').exists())

    def test_direct_calls_use_configuration_and_never_close_borrowed_session(self):
        from utils.browser_session import BrowserSession
        self.profile()
        self.assertTrue(asyncio.run(main.meta_cookie_auth('/absent/facebook-page_Creator.json',headless=False)))
        self.assertFalse(self.pw.chromium.persistent_calls[-1]['headless'])
        self.context.page_type = ComposerPage
        self.stack.enter_context(patch.object(main,'expect',Expect))
        self.stack.enter_context(patch.object(posts,'expect',Expect))
        media = self.root/'photo.png'; media.touch()
        app = main.MetaBusinessUploader('facebook-page',account_name='Creator',title='original',image_files=[media])
        self.assertEqual(asyncio.run(app.upload())['status'],'published')
        self.assertTrue(self.pw.chromium.persistent_calls[-1]['headless'])
        self.context.closed = False
        borrowed = BrowserSession(browser=self.context.browser,context=self.context,mode='local')
        self.assertEqual(asyncio.run(app.upload(session=borrowed))['status'],'published')
        self.assertFalse(self.context.closed)
        self.context.page_type = PostPage
        result = asyncio.run(posts.meta_post_action('/absent/facebook-page_Creator.json',page_id='123',
            page_name='Page A',content_id='456',expected_text='original',headless=False))
        self.assertEqual(result['status'],'published')
        self.assertFalse(self.pw.chromium.persistent_calls[-1]['headless'])
        self.assertEqual(len(self.pw.chromium.persistent_calls),3)

    def test_fault_cancel_timeout_and_hanging_page_close_release_profile(self):
        from unittest.mock import AsyncMock
        self.profile()
        self.context.hanging_page_close = True
        self.assertEqual(self.run_cli('check','--account','Creator')[0],0)
        for error in (OSError('page creation fault'), asyncio.CancelledError(), asyncio.TimeoutError('page timeout')):
            self.context.closed = False
            with patch.object(self.context,'new_page',AsyncMock(side_effect=error)):
                if isinstance(error,asyncio.CancelledError):
                    with self.assertRaises(asyncio.CancelledError): self.run_cli('check','--account','Creator')
                else:
                    code, _, err = self.run_cli('check','--account','Creator')
                    self.assertEqual(code,1,err)
            self.assertTrue(self.context.closed)
            with acquire_local_profile('facebook-page','Creator','chrome'): pass
        self.context.close_error = OSError('secondary close failure')
        with patch.object(self.context,'new_page',AsyncMock(side_effect=OSError('primary setup failure'))):
            code, _, err = self.run_cli('check','--account','Creator')
        self.assertEqual(code,1,err)
        self.assertIn('primary setup failure',err)

    def test_custom_product_kind_and_missing_optional_config_do_not_fallback(self):
        import plistlib
        self.profile('chromium')
        executable = self.root/'Renamed.app/Contents/MacOS/browser'
        executable.parent.mkdir(parents=True); executable.write_text('fixture'); executable.chmod(0o755)
        (executable.parent.parent/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'org.chromium.Chromium',
            'CFBundleName':'Chromium','CFBundleExecutable':'browser','CFBundleShortVersionString':'123'}))
        with patch.object(conf,'LOCAL_CHROME_PATH',str(executable)), patch('utils.local_browser.sys.platform','darwin'):
            code, _, err = self.run_cli('check','--account','Creator','--local-browser','irrelevant','--headed')
        self.assertEqual(code,0,err)
        custom = self.pw.chromium.persistent_calls[-1]
        self.assertEqual(custom['executable_path'],str(executable)); self.assertNotIn('channel',custom)
        with patch.object(conf,'LOCAL_BROWSER','typo',create=True):
            self.assertEqual(self.run_cli('check','--account','Creator')[0],2)
            self.assertEqual(self.run_cli('check','--account','Creator','--local-browser','chromium')[0],0)
        self.assertEqual(self.pw.chromium.persistent_calls[-1]['user_data_dir'],custom['user_data_dir'])
        self.profile()
        with patch.dict(conf.__dict__):
            conf.__dict__.pop('LOCAL_BROWSER', None)
            self.assertEqual(self.run_cli('check','--account','Creator')[0],0)
        self.pw.chromium.launch_error = OSError('selected browser unavailable')
        code, _, err = self.run_cli('check','--account','Creator')
        self.assertEqual(code,1,err)
        self.assertIn('未切换来源',err)
        self.assertFalse(self.pw.chromium.launch_calls)

    def test_works_expiry_before_and_after_delete_preserves_phase_and_never_retries(self):
        self.profile()
        self.context.page_type = PostPage
        self.context.close_error = OSError('cleanup fault')
        self.stack.enter_context(patch.object(posts,'expect',Expect))
        for phase in ('list','delete'):
            self.context.works_expiry = phase
            code, _, err = self.run_cli('delete','--account','Creator','--page-id','123','--page','Page A',
                '--content-id','456','--expected-text','original')
            self.assertEqual(code,10,err)
            self.assertIn('验证',err)
            self.assertEqual(self.context.pages[-1].delete_clicks,int(phase == 'delete'))
            if phase == 'delete': self.assertIn('publish_attempted=true',err)
        self.context.works_expiry = None
        code, _, err = self.run_cli('delete','--account','Creator','--page-id','123','--page','Page A',
            '--content-id','999','--expected-text','original')
        self.assertEqual(code,1,err)
        self.assertIn('原作品编号不匹配',err)
        self.assertEqual(self.context.pages[-1].delete_clicks,0)

    def test_business_navigation_failure_stops_after_successful_probe(self):
        self.profile()
        self.context.business_status = 503
        self.stack.enter_context(patch.object(main,'expect',Expect))
        self.stack.enter_context(patch.object(posts,'expect',Expect))
        media = self.root/'photo.png'; media.touch()
        for action, arguments, page_type in [
            ('upload-note',['--images',str(media),'--title','original'],ComposerPage),
            ('delete',['--page-id','123','--page','Page A','--content-id','456','--expected-text','original'],PostPage),
        ]:
            self.context.pages.clear(); self.context.page_type = page_type
            code, _, err = self.run_cli(action,'--account','Creator',*arguments)
            self.assertEqual(code,1,err)
            self.assertIn('503',err)
            self.assertEqual(self.context.pages[-1].publish_clicks,0)
            self.assertEqual(getattr(self.context.pages[-1],'delete_clicks',0),0)

    def test_requested_page_name_cannot_match_a_different_page_by_prefix(self):
        self.profile(); self.context.page_type = ComposerPage
        self.context.initial_page, self.context.wrong_target = 'Page AB', True
        self.stack.enter_context(patch.object(main,'expect',Expect))
        self.stack.enter_context(patch.object(posts,'expect',Expect))
        media = self.root/'photo.png'; media.touch()
        code, _, err = self.run_cli('upload-note','--account','Creator','--images',str(media),'--title','original','--page','Page A')
        self.assertEqual(code,1,err)
        self.assertEqual(self.context.pages[-1].publish_clicks,0)


class Expect:
    def __init__(self, locator): self.locator = locator
    async def to_have_count(self, expected, **kwargs):
        if await self.locator.count() != expected: raise AssertionError('count mismatch')
    async def to_contain_text(self, expected, **kwargs):
        if expected not in await self.locator.inner_text(): raise AssertionError('Page or caption mismatch')
    async def to_have_attribute(self, name, expected, **kwargs):
        if await self.locator.get_attribute(name) != expected: raise AssertionError('attribute mismatch')
    async def to_be_enabled(self, **kwargs): pass
    async def not_to_have_count(self, expected, **kwargs):
        if await self.locator.count() == expected: raise AssertionError('unexpected empty list')


class ComposerLocator(Locator):
    def __init__(self, page, kind, count=1, name=None):
        super().__init__(count); self.page, self.kind, self.name = page, kind, name
    def locator(self, selector):
        if self.kind == 'media' and selector == 'img': return ComposerLocator(self.page, 'image', len(self.page.files))
        if 'footer' in self.kind: return ComposerLocator(self.page, 'button', 2 if self.page.video else 3)
        if 'lib:bizweb_create_reel' in self.kind: return ComposerLocator(self.page, 'step', 3)
        if self.kind == 'row': return ComposerLocator(self.page, 'detail')
        return ComposerLocator(self.page, selector)
    def get_by_role(self, role, name=None, **kwargs):
        if self.kind == 'media': return ComposerLocator(self.page, 'file')
        if 'footer' in self.kind:
            return ComposerLocator(self.page, 'next' if name.search('Next') else 'publish')
        if self.kind == 'completion': return ComposerLocator(self.page, 'close' if name else role, 1 if name or role == 'heading' else 2)
        return ComposerLocator(self.page, role, name=name)
    def get_by_text(self, *args, **kwargs): return ComposerLocator(self.page, 'dimensions', len(self.page.files))
    def nth(self, n): return ComposerLocator(self.page, self.kind, name=n)
    async def all(self): return []
    async def is_checked(self): return False
    async def inner_text(self):
        if self.kind == 'combo': return self.page.selected_page
        if self.kind == 'caption': return self.page.caption
        if self.kind == 'row': return self.page.context.author_page + ' original'
        return 'original'
    async def get_attribute(self, name): return 'step' if self.name == self.page.step else None
    async def focus(self): self.page.focused = self.kind
    async def click(self, **kwargs):
        if self.kind == 'option' and not getattr(self.page.context, 'wrong_target', False):
            self.page.selected_page = self.name
            self.page.context.author_page = self.name
        if self.kind == 'next': self.page.step += 1
        if self.kind == 'publish':
            self.page.publish_clicks += 1
            if getattr(self.page.context, 'outcome', '') in ('login','verification'):
                self.page.url = 'https://www.facebook.com/' + ('login/' if self.page.context.outcome == 'login' else 'checkpoint/')
        if self.kind == 'detail': self.page.url = 'https://business.facebook.com/latest/object_insights/?asset_id=123&content_id=456'
        if self.kind == 'close': self.page.completion = False


class AwaitableValue:
    def __init__(self, value): self.result = value
    def __await__(self):
        async def result(): return self.result
        return result().__await__()


class ComposerPage(Page):
    def __init__(self, context):
        super().__init__(context)
        self.files, self.caption, self.selected_page = [], '', getattr(context,'initial_page','Page A')
        self.publish_clicks, self.step, self.completion = 0, 0, True
        self.focused = None
        context.author_page = getattr(context, 'author_page', 'Page A')
        self.keyboard = SimpleNamespace(press=self.press, insert_text=self.insert_text)
    @property
    def video(self): return bool(self.files and self.files[0].endswith('.mp4'))
    async def press(self, key):
        if key == 'Delete' and self.focused == 'caption': self.caption = ''
    async def insert_text(self, text):
        if self.focused == 'caption': self.caption += text
        if getattr(self.context, 'expire_during_edit', False): self.url = 'https://www.facebook.com/checkpoint/'
    async def goto(self, url, **kwargs):
        response = await super().goto(url, **kwargs)
        if self.context.state == 'valid' and 'composer' in url: self.url = url + '?asset_id=123'
        return response
    def locator(self, selector):
        if 'email' in selector or '/latest/home' in selector: return super().locator(selector)
        if 'combobox' in selector: return ComposerLocator(self, 'combo')
        if 'bizweb_create_post:media' in selector: return ComposerLocator(self, 'media')
        if 'input[type="text"]' in selector: return ComposerLocator(self, 'title')
        if 'contenteditable' in selector: return ComposerLocator(self, 'caption')
        if 'role="dialog"' in selector: return ComposerLocator(self, 'completion', int(self.completion))
        return ComposerLocator(self, selector)
    def get_by_role(self, role, name=None, **kwargs): return ComposerLocator(self, role, name=name)
    def get_by_text(self, text, **kwargs): return ComposerLocator(self, 'text')
    async def wait_for_url(self, *args, **kwargs): pass
    def expect_file_chooser(self):
        return _AsyncCM(SimpleNamespace(value=AwaitableValue(SimpleNamespace(set_files=self.set_files))))
    async def set_files(self, files): self.files = files
    def expect_response(self, *args, **kwargs):
        return _AsyncCM(SimpleNamespace(value=AwaitableValue(SimpleNamespace(json=self.payload))))
    async def payload(self):
        if getattr(self.context, 'outcome', '') == 'unknown': return {}
        return {'data':{'xfamily_content_create':{'items':[{'pending_publish_content_id':'456'}]}}}


class PostLocator(ComposerLocator):
    async def count(self):
        if self.kind == 'row': return int(not self.page.deleted)
        if self.kind == 'dialog': return int(not self.page.deleted)
        return self.value
    def filter(self, **kwargs):
        if self.kind == 'row' and 'has' in kwargs: return PostLocator(self.page,'loaded')
        return self
    def or_(self, other): return self
    def get_by_role(self, role, **kwargs):
        if self.kind == 'dialog': return PostLocator(self.page,'delete',2)
        return PostLocator(self.page,role)
    def nth(self, n): return PostLocator(self.page,self.kind,name=n)
    async def click(self, **kwargs):
        if self.kind == 'delete':
            self.page.delete_clicks += 1; self.page.deleted = True
            if getattr(self.page.context,'works_expiry',None) == 'delete': self.page.url = 'https://www.facebook.com/checkpoint/'
        else: await super().click(**kwargs)


class PostPage(ComposerPage):
    def __init__(self, context):
        super().__init__(context); self.deleted, self.delete_clicks = False,0
    def get_by_role(self, role, name=None, **kwargs): return PostLocator(self,role,name=name)
    def locator(self, selector):
        if 'role="dialog"' in selector: return PostLocator(self,'dialog')
        return super().locator(selector)
    async def goto(self,url,**kwargs):
        response = await super().goto(url,**kwargs)
        if '/posts/' in url and getattr(self.context,'works_expiry',None) == 'list':
            self.url = 'https://www.facebook.com/checkpoint/'
        return response
    async def screenshot(self, **kwargs): raise OSError('evidence write failed')
