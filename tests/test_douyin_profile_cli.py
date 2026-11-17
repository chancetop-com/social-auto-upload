"""Public Douyin CLI with real config/Profile/session and browser boundary fakes."""
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
from sau_commands import douyin as command
from tests.fakes import FakeContext, FakePlaywright
from tests.test_mlx_tiktok import _AsyncCM
from uploader.douyin_uploader import main
from utils.local_profile import acquire_local_profile
from tests.test_douyin_upload_seam import _LoopNode


class Locator:
    def __init__(self, count=0): self.value = count
    @property
    def first(self): return self
    async def count(self): return self.value
    async def is_visible(self): return bool(self.value)


class Page:
    def __init__(self, context): self.context, self.url = context, 'about:blank'
    async def goto(self, url, **kwargs):
        if self.context.state == 'network': raise OSError('network unavailable')
        self.url = {'login':'https://creator.douyin.com/', 'verification':'https://creator.douyin.com/captcha/verify'}.get(self.context.state, url)
        return SimpleNamespace(status=getattr(self.context,'status',200))
    async def wait_for_timeout(self, ms): pass
    def get_by_text(self, text, **kwargs):
        return Locator(int((text == '发布视频' and self.context.state == 'valid') or
                           (text == '扫码登录' and self.context.state == 'login')))
    def get_by_role(self, role, **kwargs): return Locator()
    def locator(self, selector): return Locator(int('upload' in selector and self.context.state == 'valid'))
    async def close(self):
        if getattr(self.context,'hanging_page_close',False): await asyncio.Event().wait()


class Context(FakeContext):
    def __init__(self): super().__init__(); self.state = 'valid'
    async def new_page(self):
        page = getattr(self, 'page_type', Page)(self)
        if getattr(self,'verify_occupancy',False):
            try:
                with acquire_local_profile('douyin','Creator','chrome'):
                    raise AssertionError('probe/business page escaped Profile ownership')
            except RuntimeError as error:
                if '占用' not in str(error): raise
        self.pages.append(page)
        return page


class ComposerNode(_LoopNode):
    def __init__(self,page,name,count=1): super().__init__(name,count=count); self.page = page
    def filter(self,**kwargs): return self
    def locator(self,selector): return ComposerNode(self.page,selector)
    async def set_input_files(self,files): self.page.files = files
    async def click(self,**kwargs):
        self.page.focused = self.name
        if self.name == 'publish':
            self.page.publish_clicks += 1
            outcome = getattr(self.page.context,'outcome','success')
            if outcome in ('login','verification'):
                self.page.url = 'https://creator.douyin.com/' + ('login/' if outcome == 'login' else 'captcha/verify')
            if outcome == 'disconnect':
                self.page.disconnected = True
                error = OSError('browser disconnected after dispatch')
                setattr(error,main.MAYBE_DISPATCHED,main.MAYBE_DISPATCHED_VALUE)
                raise error
        await super().click(**kwargs)


class ComposerPage(Page):
    def __init__(self,context):
        super().__init__(context); self.files = []; self.publish_clicks = 0; self.focused = ''; self.values = {}
        self.keyboard = SimpleNamespace(press=self.press, insert_text=self.insert_text)
    async def press(self,key):
        if key == 'Delete': self.values[self.focused] = ''
    async def insert_text(self,text):
        self.values[self.focused] = self.values.get(self.focused,'') + text
        if getattr(self.context,'expire_during_edit',False): self.url = 'https://creator.douyin.com/captcha/verify'
    def locator(self,selector):
        count = int(any(s in selector for s in ('upload-btn-input','long-card','填写作品标题','zone-container','semi-modal','input[accept','input[type=','semi-radio')))
        if '短信' in selector: count = int(getattr(self.context,'sms_challenge',False))
        if 'semi-modal' in selector and getattr(self.context,'declaration_missing',False): count = 0
        return ComposerNode(self,selector,count)
    def get_by_text(self,text,**kwargs):
        if getattr(self,'disconnected',False): raise OSError('browser disconnected')
        return ComposerNode(self,text,int(text in ('发布视频','发布图文','请选择自主声明')))
    def get_by_role(self,role,name=None,**kwargs):
        return ComposerNode(self,'publish' if name == '发布' else str(name),int(role == 'button'))
    async def evaluate(self,*args): pass
    async def wait_for_url(self,url,**kwargs):
        if 'manage' in url:
            if getattr(self.context,'outcome','success') != 'success': raise TimeoutError('not confirmed')
            self.url = 'https://creator.douyin.com/creator-micro/content/manage'
    async def screenshot(self,**kwargs): pass


class DouyinProfileCliTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.stack.enter_context(chdir(self.root))
        self.stack.enter_context(patch.object(conf,'BASE_DIR',self.root))
        self.stack.enter_context(patch.object(conf,'LOCAL_CHROME_PATH',''))
        self.stack.enter_context(patch.object(conf,'LOCAL_CHROME_HEADLESS',True))
        self.stack.enter_context(patch.dict(os.environ,{'MLX_API_TOKEN':'','ADSPOWER_API_KEY':'','HUMANIZE':'0'}))
        self.pw, self.context = FakePlaywright(), Context()
        self.pw.chromium.persistent_context = self.context
        for module in (command,main):
            self.stack.enter_context(patch.object(module,'async_playwright',lambda: _AsyncCM(self.pw)))
        self.addCleanup(self.stack.close)
    def profile(self, kind='chrome'):
        with acquire_local_profile('douyin','Creator',kind,create=True) as profile: return profile.path
    def run_cli(self,*args):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            code = sau_cli.main(['douyin',*args])
        return code,out.getvalue(),err.getvalue()
    def test_check_uses_profile_and_config_ignoring_old_json(self):
        self.profile()
        old = self.root/'cookies/douyin_Creator.json'; old.parent.mkdir(); old.write_text('broken')
        code,_,err = self.run_cli('check','--account','Creator')
        self.assertEqual(code,0,err)
        self.assertEqual(self.pw.chromium.persistent_calls,[{
            'user_data_dir':str(self.root/'browser_profiles/chrome/douyin/Creator'),
            'channel':'chrome','headless':True,'no_viewport':True}])
        self.assertEqual(old.read_text(),'broken')
        self.assertFalse(self.context.add_init_script_calls)
        self.assertTrue(self.context.closed)
        self.assertFalse(self.context.storage_state_calls)

    def test_video_and_note_use_one_session_for_probe_and_publish(self):
        from unittest.mock import AsyncMock
        self.profile(); self.context.page_type = ComposerPage
        self.context.verify_occupancy = True
        self.stack.enter_context(patch.object(main.asyncio,'sleep',AsyncMock()))
        for action,option,filename in [('upload-video','--file','clip.mp4'),('upload-note','--images','photo.png')]:
            media = self.root/filename; media.touch()
            code,_,err = self.run_cli(action,'--account','Creator',option,str(media),'--title','original','--headed')
            self.assertEqual(code,0,err)
            page = self.context.pages[-1]
            self.assertEqual(page.publish_clicks,1)
            self.assertEqual(page.values['input[placeholder*="填写作品标题"]'],'original')
            self.assertTrue(self.context.closed)
        self.assertEqual(len(self.pw.chromium.persistent_calls),2)
        self.assertFalse(self.context.storage_state_calls)

    def test_post_submit_outcomes_and_expiry_survive_cleanup_and_never_resubmit(self):
        from unittest.mock import AsyncMock
        self.profile(); self.context.page_type = ComposerPage
        self.context.close_error = OSError('cleanup failed')
        self.stack.enter_context(patch.object(main.asyncio,'sleep',AsyncMock()))
        self.stack.enter_context(patch('uploader.publish_timeout.time',SimpleNamespace(monotonic=lambda:
            1000 if any(getattr(p,'publish_clicks',0) for p in self.context.pages) else 0)))
        for action,option,filename in [('upload-video','--file','clip.mp4'),('upload-note','--images','photo.png')]:
            media = self.root/filename; media.touch()
            for outcome,expected in [('success',0),('unknown',9),('disconnect',9),('login',10),('verification',10),('edit',10)]:
                self.context.pages.clear(); self.context.outcome = outcome
                self.context.expire_during_edit = outcome == 'edit'
                code,_,err = self.run_cli(action,'--account','Creator',option,str(media),'--title','original')
                self.assertEqual(code,expected,(action,outcome,err))
                self.assertEqual(self.context.pages[-1].publish_clicks,int(outcome != 'edit'))
                if expected == 10 and outcome != 'edit': self.assertIn('publish_attempted=true',err)
                if outcome == 'edit': self.assertNotIn('publish_attempted=true',err)
                if outcome in ('verification','edit'): self.assertIn('验证',err)
                with acquire_local_profile('douyin','Creator','chrome'): pass

    def test_check_classifies_missing_login_verification_and_faults(self):
        self.assertEqual(self.run_cli('check','--account','Creator')[0],10)
        self.profile()
        for state, expected in [('login',10),('verification',10),('network',1),('unknown',1),('valid',0)]:
            self.context.state = state
            code,_,err = self.run_cli('check','--account','Creator')
            self.assertEqual(code,expected,(state,err))
            if state == 'verification': self.assertIn('验证',err)
        self.context.status = 403
        code,_,err = self.run_cli('check','--account','Creator')
        self.assertEqual(code,1,err)
        self.assertIn('403',err)

    def test_login_reuses_alias_across_headless_and_isolates_browser_kinds(self):
        for flags in ([],['--headed'],['--local-browser','chromium']):
            code,_,err = self.run_cli('login','--account','Creator',*flags)
            self.assertEqual(code,0,err)
        calls = self.pw.chromium.persistent_calls
        self.assertEqual(len(calls),3)
        self.assertEqual([c['headless'] for c in calls],[True,False,True])
        self.assertEqual(calls[0]['user_data_dir'],calls[1]['user_data_dir'])
        self.assertTrue(calls[2]['user_data_dir'].endswith('/chromium/douyin/Creator'))
        self.assertFalse((self.root/'cookies').exists())
        self.assertFalse(self.context.storage_state_calls)

    def test_reset_is_exact_and_works_without_binary(self):
        chrome, chromium = self.profile(), self.profile('chromium')
        history = self.root/'result.json'; history.write_text('prior post')
        with acquire_local_profile('douyin','Creator','chrome'):
            self.assertEqual(self.run_cli('reset-profile','--account','Creator','--browser-kind','chrome')[0],1)
        with patch.object(conf,'LOCAL_CHROME_PATH','/missing/browser'):
            code,_,err = self.run_cli('reset-profile','--account','Creator','--browser-kind','chrome')
        self.assertEqual(code,0,err)
        self.assertFalse(chrome.exists()); self.assertTrue(chromium.exists())
        self.assertEqual(history.read_text(),'prior post')
        self.assertFalse(self.pw.chromium.persistent_calls)

    def test_direct_setup_uploader_and_borrowed_session_follow_same_contract(self):
        from unittest.mock import AsyncMock
        from utils.browser_session import BrowserSession
        self.profile()
        self.assertTrue(asyncio.run(main.douyin_setup('/missing/douyin_Creator.json',headless=False)))
        self.assertFalse(self.pw.chromium.persistent_calls[-1]['headless'])
        self.context.page_type = ComposerPage
        self.stack.enter_context(patch.object(main.asyncio,'sleep',AsyncMock()))
        media = self.root/'photo.png'; media.touch()
        app = main.DouYinNote([str(media)],'body',[],0,'/missing/douyin_Creator.json',title='original')
        asyncio.run(app.douyin_upload_note())
        self.assertTrue(self.pw.chromium.persistent_calls[-1]['headless'])
        self.context.closed = False
        borrowed = BrowserSession(browser=self.context.browser,context=self.context,mode='local')
        asyncio.run(app.douyin_upload_note(session=borrowed))
        self.assertFalse(self.context.closed)
        self.assertEqual(len(self.pw.chromium.persistent_calls),2)
        self.assertFalse(self.context.storage_state_calls)

    def test_fault_cancel_and_hanging_close_release_profile_without_masking_error(self):
        from unittest.mock import AsyncMock
        self.profile(); self.context.hanging_page_close = True
        self.assertEqual(self.run_cli('check','--account','Creator')[0],0)
        for error in (OSError('page creation failed'),asyncio.CancelledError(),asyncio.TimeoutError('page timeout')):
            self.context.closed = False
            with patch.object(self.context,'new_page',AsyncMock(side_effect=error)):
                if isinstance(error,asyncio.CancelledError):
                    with self.assertRaises(asyncio.CancelledError): self.run_cli('check','--account','Creator')
                else: self.assertEqual(self.run_cli('check','--account','Creator')[0],1)
            self.assertTrue(self.context.closed)
            with acquire_local_profile('douyin','Creator','chrome'): pass
        async def hanging_close(): await asyncio.Event().wait()
        with patch.object(self.context,'close',hanging_close), patch('utils.local_browser_session.CLOSE_TIMEOUT_SECONDS',0.01):
            self.assertEqual(self.run_cli('check','--account','Creator')[0],0)
        with acquire_local_profile('douyin','Creator','chrome'): pass

    def test_managed_ignores_local_config_and_keeps_provider_ownership(self):
        from tests.fakes import FakeManagedProvider, FakeBrowser
        from loguru import logger
        for mode in ('multilogin','adspower'):
            provider = FakeManagedProvider(mode=mode)
            context = Context()
            self.pw.chromium.queue_connect_browser(FakeBrowser([context]))
            logs = []; sink = logger.add(lambda message: logs.append(str(message)),format='{message}')
            try:
                with patch.object(command,'resolve_managed_provider',return_value=provider), patch.object(conf,'LOCAL_BROWSER',[],create=True), patch.object(conf,'LOCAL_CHROME_PATH',[]):
                    code,_,err = self.run_cli('check','--account','Creator','--local-browser','ignored')
                self.assertEqual(code,0,err)
                self.assertEqual(provider.start_calls,[True]); self.assertEqual(provider.stop_calls,1)
                self.assertFalse(context.closed)
                from unittest.mock import AsyncMock
                media = self.root/'photo.png'; media.touch()
                context.page_type = ComposerPage
                upload_provider = FakeManagedProvider(mode=mode)
                self.pw.chromium.queue_connect_browser(FakeBrowser([context]))
                with patch.object(command,'resolve_managed_provider',return_value=upload_provider), patch.object(conf,'LOCAL_BROWSER',[],create=True), patch.object(conf,'LOCAL_CHROME_PATH',[]), patch.object(main.asyncio,'sleep',AsyncMock()):
                    code,_,err = self.run_cli('upload-note','--account','Creator','--images',str(media),'--title','original','--local-browser','ignored','--headed')
                self.assertEqual(code,0,err)
                self.assertEqual(upload_provider.start_calls,[False]); self.assertEqual(upload_provider.stop_calls,1)
                self.assertEqual(context.pages[-1].publish_clicks,1)
                self.assertIn('launch_kwargs',''.join(logs))
                self.assertFalse(context.closed)
            finally: logger.remove(sink)
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.assertFalse((self.root/'browser_profiles').exists())

    def test_custom_product_kind_optional_config_and_no_fallback(self):
        import plistlib
        self.profile('chromium')
        executable = self.root/'Renamed.app/Contents/MacOS/browser'
        executable.parent.mkdir(parents=True); executable.write_text('fixture'); executable.chmod(0o755)
        (executable.parent.parent/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'org.chromium.Chromium','CFBundleName':'Chromium','CFBundleExecutable':'browser','CFBundleShortVersionString':'123'}))
        with patch.object(conf,'LOCAL_CHROME_PATH',str(executable)),patch('utils.local_browser.sys.platform','darwin'):
            code,_,err = self.run_cli('check','--account','Creator','--local-browser','irrelevant','--headed')
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
        code,_,err = self.run_cli('check','--account','Creator')
        self.assertEqual(code,1,err); self.assertIn('未切换来源',err)
        self.assertFalse(self.pw.chromium.launch_calls)

    def test_page_fault_and_sms_challenge_stop_before_submit(self):
        from unittest.mock import AsyncMock
        self.profile(); self.context.page_type = ComposerPage
        self.context.sms_challenge = True
        self.stack.enter_context(patch.object(main.asyncio,'sleep',AsyncMock()))
        media = self.root/'clip.mp4'; media.touch()
        code,_,err = self.run_cli('upload-video','--account','Creator','--file',str(media),'--title','original')
        self.assertEqual(code,10,err); self.assertIn('验证',err)
        self.assertTrue(all(not getattr(p,'publish_clicks',0) for p in self.context.pages))
        self.context.sms_challenge = False
        self.context.status = 503
        self.assertEqual(self.run_cli('upload-video','--account','Creator','--file',str(media),'--title','original')[0],1)

    def test_platform_failure_after_edit_redirect_is_login_required(self):
        from unittest.mock import AsyncMock
        self.profile(); self.context.page_type = ComposerPage
        self.context.expire_during_edit = True
        async def broken_editor(text):
            self.context.pages[-1].url = 'https://creator.douyin.com/captcha/verify'
            raise TimeoutError('editor detached during redirect')
        self.stack.enter_context(patch.object(main.asyncio,'sleep',AsyncMock()))
        self.stack.enter_context(patch.object(ComposerPage,'insert_text',lambda page,text: broken_editor(text)))
        media = self.root/'photo.png'; media.touch()
        code,_,err = self.run_cli('upload-note','--account','Creator','--images',str(media),'--title','original')
        self.assertEqual(code,10,err)
        self.assertEqual(self.context.pages[-1].publish_clicks,0)
        self.assertNotIn('publish_attempted=true',err)

    def test_interactive_login_persists_without_cookie_export_and_qr_cleanup_is_secondary(self):
        import base64
        import segno
        image = io.BytesIO(); segno.make('offline://douyin-fixture').save(image,kind='png',scale=3)
        source = 'data:image/png;base64,' + base64.b64encode(image.getvalue()).decode()
        context = self.context
        class LoginLocator(Locator):
            async def wait_for(self,**kwargs): pass
            async def get_attribute(self,name):
                context.state = 'valid'; context.pages[-1].url = main.DOUYIN_UPLOAD_URL
                return source
        class LoginPage(Page):
            def get_by_text(self,text,**kwargs):
                return LoginLocator(int(text in ('扫码登录','发布视频') and ((text == '发布视频') == (context.state == 'valid'))))
            def locator(self,selector):
                return LoginLocator(int('data:image' in selector))
        self.context.page_type = LoginPage; self.context.state = 'login'
        with patch.object(Path,'unlink',side_effect=OSError('QR cleanup denied')):
            code,_,err = self.run_cli('login','--account','Creator','--headed')
        self.assertEqual(code,0,err)
        self.assertEqual(len(self.pw.chromium.persistent_calls),1)
        self.assertFalse(self.context.storage_state_calls)
        self.assertTrue(self.context.closed)
        self.assertEqual(self.run_cli('check','--account','Creator')[0],0)

    def test_declaration_failure_is_preserved_through_cleanup_failure(self):
        from unittest.mock import AsyncMock
        self.profile(); self.context.page_type = ComposerPage
        self.context.declaration_missing = True
        self.context.close_error = OSError('secondary cleanup')
        self.stack.enter_context(patch.object(main.asyncio,'sleep',AsyncMock()))
        media = self.root/'clip.mp4'; media.touch()
        code,_,err = self.run_cli('upload-video','--account','Creator','--file',str(media),'--title','original')
        self.assertEqual(code,1,err)
        self.assertIn('自主声明',err)
        self.assertEqual(self.context.pages[-1].publish_clicks,0)
        with acquire_local_profile('douyin','Creator','chrome'): pass
