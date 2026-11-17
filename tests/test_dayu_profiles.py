"""Dayu CLI through real configuration/Profile/session; browser and platform boundaries only."""
import asyncio
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import conf
import sau_cli
from sau_commands import dayu as command
from tests.fakes import FakeContext, FakePage, FakePlaywright
from tests.fakes_xhs_dom import RecordingLocator
from uploader.dayu_uploader import session, article, main, verification
from utils.local_profile import acquire_local_profile


class PlaywrightCM:
    def __init__(self, playwright): self.playwright = playwright
    async def __aenter__(self): return self.playwright
    async def __aexit__(self, *_): pass


class Expect:
    def __init__(self, locator): self.locator = locator
    async def to_have_count(self, count, **_): assert await self.locator.count() == count
    async def to_be_visible(self, **_): assert await self.locator.is_visible()
    async def to_have_text(self, text, **_): assert await self.locator.inner_text() == text
    async def not_to_be_empty(self, **_): assert await self.locator.inner_text()


class BackendPage(FakePage):
    def __init__(self, *, url=None, status=200, error=None, name='Creator One', wmid='a' * 32, login=False):
        super().__init__()
        self.target_url, self.status, self.error = url, status, error
        self.name, self.wmid, self.login = name, wmid, login
    async def goto(self, url, **kwargs):
        await super().goto(url, **kwargs)
        self.url = self.target_url or session.DAYU_HOME_URL
        if self.error: raise self.error
        return SimpleNamespace(status=self.status)
    async def wait_for_timeout(self, _): pass
    async def wait_for_url(self, *_, **__): self.url = self.target_url or session.DAYU_HOME_URL
    def locator(self, selector):
        if selector == '.header-info .name': return RecordingLocator(selector, text=self.name, count=int(bool(self.name)))
        if selector == 'script:not([src])':
            return SimpleNamespace(all_text_contents=AsyncMock(return_value=[f'var data = {{"wmid":"{self.wmid}"}}']))
        return RecordingLocator(selector, count=int(self.login and selector == session._LOGIN_IFRAME))
    async def close(self): raise AssertionError('Local page is owned by its context')


class BackendContext(FakeContext):
    def __init__(self):
        super().__init__()
        self.next_page = BackendPage()
    async def new_page(self):
        self.pages.append(self.next_page)
        self.next_page.context = self
        return self.next_page


class DayuProfilesTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.stack.enter_context(patch('sau_commands.arguments.BASE_DIR', self.root))
        self.pw = FakePlaywright()
        async def forbid_launch(**_): raise AssertionError('Use the persistent Profile')
        self.pw.chromium.launch = forbid_launch
        self.context = BackendContext(); self.pw.chromium.persistent_context = self.context
        for key, value in {'BASE_DIR': self.root, 'LOCAL_CHROME_PATH': '', 'LOCAL_CHROME_HEADLESS': False, 'LOCAL_BROWSER': 'chrome'}.items():
            self.stack.enter_context(patch.object(conf, key, value, create=True))
        self.stack.enter_context(patch.dict(os.environ, {'MLX_API_TOKEN':'', 'ADSPOWER_API_KEY':'', 'HUMANIZE':'0'}))
        for module in (command, session, article, main):
            self.stack.enter_context(patch.object(module, 'async_playwright', lambda: PlaywrightCM(self.pw)))
        for module in (session, verification): self.stack.enter_context(patch.object(module, 'expect', Expect))
    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try: code = sau_cli.main(['dayu', *args])
            except SystemExit as error: code = error.code
        return code, out.getvalue(), err.getvalue()
    def profile(self, kind='chrome', account='Creator'):
        with acquire_local_profile('dayu', account, kind, create=True) as profile: return profile.path

    def test_login_and_check_share_profile_ignore_old_state_and_allow_new_identity(self):
        old = self.root / 'cookies/dayu_Creator.json'; old.parent.mkdir()
        old.write_text('invalid cookie'); old.with_suffix('.identity.json').write_text('invalid identity')
        result = self.cli('login', '--account', 'Creator')
        self.assertEqual(result[0], 0, result)
        self.context.next_page = BackendPage(name='Different account', wmid='b' * 32)
        self.assertEqual(self.cli('login', '--account', 'Creator')[0], 0)
        self.assertEqual(self.cli('check', '--account', 'Creator')[0], 0)
        self.assertEqual(self.pw.chromium.persistent_calls, [dict(user_data_dir=str(self.root / 'browser_profiles/chrome/dayu/Creator'), channel='chrome', headless=False, no_viewport=True)] * 3)
        self.assertFalse(self.context.storage_state_calls)
        self.assertFalse(self.context.add_init_script_calls)
        self.assertEqual(old.read_text(), 'invalid cookie')
        self.assertEqual(old.with_suffix('.identity.json').read_text(), 'invalid identity')

    def test_profile_authentication_and_faults_have_distinct_cli_results(self):
        self.assertEqual(self.cli('check', '--account', 'Creator')[0], 10)
        self.profile()
        for page, code in [
            (BackendPage(login=True), 10), (BackendPage(url='https://uop.dayu.com/cas/login'), 10),
            (BackendPage(url='https://mp.dayu.com/verify'), 10),
            (BackendPage(status=403, login=True), 1), (BackendPage(status=503), 1),
            (BackendPage(name=''), 1), (BackendPage(error=OSError('network failure')), 1),
            (BackendPage(url='https://mp.dayu.com.attacker.invalid/dashboard'), 1),
            (BackendPage(url='https://uop.dayu.com/cas/login', error=TimeoutError('interrupted')), 10),
        ]:
            with self.subTest(url=page.target_url, code=code, status=page.status):
                self.context.next_page = page
                result = self.cli('check', '--account', 'Creator')
                self.assertEqual(result[0], code, result)
                if 'verify' in str(page.target_url): self.assertIn('reason=verification', result[2])
        self.context.next_page = BackendPage(wmid='invalid')
        result = self.cli('login', '--account', 'Creator')
        self.assertEqual(result[0], 1, result)
        self.context.next_page = BackendPage()
        result = self.cli('login', '--account', 'Creator', '--expected-name', 'Explicit different name')
        self.assertEqual(result[0], 1, result)
        self.assertIn('登录主体不匹配', result[2])

    def upload_args(self, kind):
        base = ['upload-' + kind, '--account', 'Creator', '--title', '大鱼号持久资料测试标题', '--source', '无需标注']
        if kind == 'video':
            import cv2
            import numpy as np
            video = self.root / 'six-seconds.mp4'
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'mp4v'), 25, (32, 32))
            for _ in range(150): writer.write(np.zeros((32, 32, 3), dtype=np.uint8))
            writer.release()
            return base + ['--file', str(video), '--thumbnail', str(Path(__file__).resolve().parents[1] / 'videos/demo.png'), '--category', '科技']
        body = self.root / 'article.txt'; body.write_text('完整文章正文')
        return base + ['--content-file', str(body)]

    def test_registered_uploads_use_current_profile_identity_without_old_files(self):
        self.profile('chromium')
        for kind in ('video', 'article'):
            page = BackendPage(name='Replacement', wmid='b' * 32)
            original = page.locator
            def locator(selector, original=original):
                if selector in ('input[type="file"][name="file"]', '#title'):
                    raise PermissionError('material boundary failure')
                return original(selector)
            page.locator = locator
            self.context.next_page = page
            self.context.grant_permissions = AsyncMock(side_effect=PermissionError('material boundary failure'))
            result = self.cli(*self.upload_args(kind), '--local-browser', 'chromium', '--headless')
            self.assertEqual(result[0], 1, result)
            self.assertIn('material boundary failure', result[2])
            records = list((self.root / 'cookies/dayu_results').glob('*.json'))
            saved = json.loads(max(records, key=lambda p:p.stat().st_mtime_ns).read_text())
            self.assertEqual(saved['identity'], {'wmid':'b' * 32, 'name':'Replacement'})
            self.assertTrue(self.context.closed)
            if kind == 'article':
                self.context.grant_permissions.assert_awaited_once_with(['clipboard-read', 'clipboard-write'], origin='https://mp.dayu.com')
        self.assertEqual(len(self.pw.chromium.persistent_calls), 2)
        self.assertTrue(all(call['channel']=='chromium' and call['headless'] and call['no_viewport'] for call in self.pw.chromium.persistent_calls))

    def backend_record(self):
        record = dict(content_id='work-1', origin_id='b'*32, title='Original title', status=1,
                      ucUrl='https://mparticle.uc.cn/video.html?wm_id='+'a'*32+'&wm_aid='+'b'*32)
        self.context.request = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(
            ok=True, json=AsyncMock(return_value={'dataList':{'data':[record], 'totalPage':1}}))))
        return record

    def public_browser(self, *, failure=None, close_failure=None):
        from tests.fakes import FakeBrowser
        main_context = self.context
        public = FakeContext()
        public_page = FakePage()
        async def goto(url, **_):
            public_page.url = url
            if failure: raise failure
        public_page.goto = goto
        public_page.wait_for_function = AsyncMock()
        async def evaluate(script, *_):
            return {'duration':6, 'current_time':1, 'ready_state':4}
        video = RecordingLocator('video'); video.evaluate = evaluate
        body = RecordingLocator('body', text='Article text', children={'img':RecordingLocator('images', count=0)})
        article_locator = RecordingLocator('article', children={':scope > h1':RecordingLocator('title', text='Original title'),
            '[class^="article-userInfoName-"]':RecordingLocator('author', text='Creator One'), '[class^="index-articleSummary-"]':body})
        public_page.locator = lambda selector: {'video':video, '[class^="pc-videoContent-"]':RecordingLocator('title', text='Original title'),
            '[class^="pc-userInfoContainer-"] > span':RecordingLocator('author', text='Creator One'), '[class^="index-articleContainer-"]':article_locator}[selector]
        public.new_page = AsyncMock(return_value=public_page)
        browser = FakeBrowser([main_context])
        async def new_context(**kwargs):
            self.assertTrue(main_context.request.get.await_count, 'backend lookup must finish first')
            self.assertFalse(main_context.closed)
            browser.new_context_calls.append(kwargs)
            return public
        browser.new_context = new_context
        async def close():
            self.assertFalse(main_context.closed)
            with self.assertRaises(RuntimeError):
                with acquire_local_profile('dayu', 'Creator', 'chrome'): pass
            public.closed = True
            if close_failure: raise close_failure
        public.close = close
        self.pw.chromium.launch_browser = browser
        return browser, public

    def test_verify_uses_backend_before_optional_anonymous_selected_browser(self):
        self.profile()
        for kind in ('video', 'article'):
            for anonymous in (False, True):
                with self.subTest(kind=kind, anonymous=anonymous):
                    self.context.closed = False
                    self.backend_record()
                    browser, public = self.public_browser()
                    result = self.cli('verify', '--account', 'Creator', '--content-id', 'work-1', '--type', kind, *(['--public'] if anonymous else []))
                    self.assertEqual(result[0], 0, result)
                    self.assertEqual(browser.new_context_calls, [{'no_viewport':True}] if anonymous else [])
                    self.assertEqual(public.closed, anonymous)
                    self.assertEqual(browser.close_calls, 0)
                    self.assertTrue(self.context.closed)
        self.assertEqual(len(self.pw.chromium.persistent_calls), 4)

    def test_verify_history_rejects_new_account_without_rewriting_result(self):
        self.profile(); self.backend_record()
        history = self.root / 'result.json'
        history.write_text(json.dumps(dict(type='video', content_id='work-1', identity={'wmid':'b'*32, 'name':'Previous account'})))
        original = history.read_bytes()
        result = self.cli('verify', '--account', 'Creator', '--result', str(history))
        self.assertEqual(result[0], 1, result)
        self.assertIn('主体不一致', result[2])
        self.assertEqual(history.read_bytes(), original)
        self.context.request.get.assert_not_awaited()

    def test_public_failures_and_cancellation_only_close_owned_resources(self):
        self.profile()
        for failure in (OSError('public fetch failed'), asyncio.CancelledError()):
            self.context.closed = False; self.backend_record()
            browser, public = self.public_browser(failure=failure, close_failure=OSError('anonymous close failed'))
            if isinstance(failure, asyncio.CancelledError):
                with self.assertRaises(asyncio.CancelledError): self.cli('verify', '--account','Creator','--content-id','work-1','--public')
            else:
                result = self.cli('verify','--account','Creator','--content-id','work-1','--public')
                self.assertEqual(result[0], 1, result)
                self.assertIn('public fetch failed', result[2])
            self.assertTrue(public.closed)
            self.assertTrue(self.context.closed)
            self.assertEqual(browser.close_calls, 0)
            with acquire_local_profile('dayu', 'Creator', 'chrome'): pass

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
        self.assertTrue(all(call['user_data_dir'].endswith('/chromium/dayu/Creator') for call in self.pw.chromium.persistent_calls))

    def test_reset_exact_profile_without_binary_and_protects_lease_history_and_old_state(self):
        chrome, chromium = self.profile(), self.profile('chromium')
        old = self.root / 'old.json'; old.write_text('old login state')
        history = self.root / 'result.json'; history.write_text('historical work')
        with patch.object(conf, 'LOCAL_CHROME_PATH', '/missing/binary'):
            with acquire_local_profile('dayu', 'Creator', 'chrome'):
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
        args = sau_cli.build_parser().parse_args(['dayu', 'check', '--account', 'Creator'])
        with patch('utils.local_browser_session.CLOSE_TIMEOUT_SECONDS', 0.02):
            self.assertEqual(asyncio.run(asyncio.wait_for(sau_cli.dispatch(args), 1)), 0)
        with acquire_local_profile('dayu', 'Creator', 'chrome'):
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

    def video_page(self, outcome='success'):
        from tests.test_dayu_humanize import _video_selectors, _page, _Clickable, _expect
        from tests.test_dayu_article import _FakeResponse, _FakeResponseContext
        from uploader.dayu_uploader import publication, schedule
        log = []; selectors, *_ = _video_selectors(log)
        selectors['input[type="file"][name="file"]'] = RecordingLocator('video-input')
        selectors['.article-write_video-container'] = RecordingLocator('progress', text='视频上传成功，处理完成', children={
            '.article-write_video-container-result-desc p span':RecordingLocator('filename', text='six-seconds.mp4')})
        selectors['.article-write_video-container'].inner_text = AsyncMock(return_value='视频上传成功，处理完成')
        buttons = {name:_Clickable(name, log=log) for name in ('发表','确认发表')}
        selectors.update({'role:button:'+name:button for name,button in buttons.items()})
        page = _page(selectors, log=log)
        page.get_by_role = lambda role, name=None, **_: buttons[name]
        backend = BackendPage()
        old_locator = page.locator
        page.locator = lambda selector: backend.locator(selector) if selector in (session._LOGIN_IFRAME, '.header-info .name', 'script:not([src])') else old_locator(selector)
        async def goto(url, **_): page.url = url; return SimpleNamespace(status=200)
        page.goto = goto
        response = _FakeResponse({'data':{'content_id':'published-1'}} if outcome != 'unknown' else {})
        if outcome=='after-api-login': response.url = 'https://uop.dayu.com/cas/login'
        responses = [_FakeResponse({'data':{'_id':'draft-1'}}), response]
        page.expect_response = lambda *_, **__: _FakeResponseContext(responses.pop(0))
        if outcome in ('before-login','after-login','after-verification'):
            async def redirect(**_):
                page.url = 'https://mp.dayu.com/verify' if outcome=='after-verification' else 'https://uop.dayu.com/cas/login'
                if outcome=='before-login': raise TimeoutError('navigation interrupted')
                buttons['确认发表'].click_count += 1
            if outcome=='before-login':
                async def upload(*_, **__): await redirect()
                selectors['input[type="file"][name="file"]'].set_input_files = upload
            else: buttons['确认发表'].click = redirect
        self.context.next_page = page
        self.context.request = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(ok=True, json=AsyncMock(return_value={'draft_id':'draft-1','is_timed_release':False}))))
        for module in (main, publication, schedule): self.stack.enter_context(patch.object(module, 'expect', _expect))
        return page, buttons, selectors

    def test_full_video_submission_preserves_result_and_authentication_phase(self):
        self.profile()
        for outcome, code, attempted in [('success',0,True),('unknown',9,True),('before-login',10,False),('after-login',10,True),('after-verification',10,True),('after-api-login',10,True)]:
            with self.subTest(outcome=outcome):
                page, buttons, selectors = self.video_page(outcome)
                self.context.close_error = OSError('cleanup failed')
                result = self.cli(*self.upload_args('video'), '--source','转载','--source-url','https://example.com/source')
                self.assertEqual(result[0],code,result)
                self.assertEqual(buttons['确认发表'].click_count, int(attempted))
                if code==10: self.assertEqual('publish_attempted=true' in result[2],attempted)
                if outcome=='after-verification': self.assertIn('reason=verification',result[2])
                if outcome=='success':
                    self.assertEqual(json.loads(result[1])['content_id'],'published-1')
                    self.assertEqual(selectors['[contenteditable="true"][placeholder="视频标题最少5个字"]'].buffer, '大鱼号持久资料测试标题')

    def test_login_access_fault_and_verify_api_auth_redirect_remain_distinct(self):
        self.context.next_page = BackendPage(status=403)
        result = self.cli('login','--account','Creator')
        self.assertEqual(result[0],1,result)
        self.assertIn('HTTP 403',result[2])
        self.context.next_page = BackendPage()
        self.context.request = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(
            ok=True, url='https://uop.dayu.com/cas/login', json=AsyncMock(return_value={}))))
        result = self.cli('verify','--account','Creator','--content-id','work-1')
        self.assertEqual(result[0],10,result)

    def test_direct_login_check_upload_and_injected_session_keep_ownership(self):
        from utils.browser_session import BrowserSession
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', True):
            asyncio.run(session.login_dayu_account(self.root/'dayu_Creator.json'))
            self.assertTrue(asyncio.run(session.check_dayu_account(self.root/'dayu_Creator.json', headless=False)))
        args = sau_cli.build_parser().parse_args(['dayu', *self.upload_args('video'), '--source','转载','--source-url','https://example.com/source'])
        app = main.DayuVideo(args.title, args.file, [], self.root/'dayu_Creator.json', args.thumbnail, args.category, args.source,
                             source_url=args.source_url, headless=False)
        page, buttons, _ = self.video_page()
        result = asyncio.run(app.main())
        self.assertEqual(result['content_id'],'published-1')
        self.assertEqual([c['headless'] for c in self.pw.chromium.persistent_calls],[True,False,False])
        self.context.closed = False
        self.video_page()
        result = asyncio.run(app.main(session=BrowserSession(browser=None,context=self.context,mode='local')))
        self.assertEqual(result['content_id'],'published-1')
        self.assertFalse(self.context.closed)
        self.assertEqual(len(self.pw.chromium.persistent_calls),3)

    def test_verify_keeps_raw_local_alias_under_provider_environment(self):
        self.profile(account=' Creator '); self.backend_record()
        with patch.dict(os.environ,{'ADSPOWER_API_KEY':'test-only-token'}):
            result = self.cli('verify','--account',' Creator ','--content-id','work-1')
        self.assertEqual(result[0],0,result)
        self.assertTrue(self.pw.chromium.persistent_calls[-1]['user_data_dir'].endswith('/chrome/dayu/ Creator '))
        self.assertFalse(self.pw.chromium.connect_calls)

    def test_anonymous_hung_close_cannot_hang_outer_session(self):
        self.profile(); self.backend_record()
        browser, public = self.public_browser()
        async def hang(): await asyncio.Event().wait()
        public.close = hang
        args = sau_cli.build_parser().parse_args(['dayu','verify','--account','Creator','--content-id','work-1','--public'])
        with patch('utils.local_browser_session.CLOSE_TIMEOUT_SECONDS',0.02):
            self.assertEqual(asyncio.run(asyncio.wait_for(sau_cli.dispatch(args),1)),0)
        self.assertTrue(self.context.closed)
        self.assertEqual(browser.close_calls,0)
        with acquire_local_profile('dayu','Creator','chrome'): pass

    def test_upload_api_auth_redirect_before_confirmation_is_not_a_field_fault(self):
        self.profile()
        page, buttons, _ = self.video_page()
        self.context.request.get.return_value.url = 'https://uop.dayu.com/cas/login'
        self.context.request.get.return_value.json = AsyncMock(return_value={})
        result = self.cli(*self.upload_args('video'),'--source','转载','--source-url','https://example.com/source')
        self.assertEqual(result[0],10,result)
        self.assertNotIn('publish_attempted=true',result[2])
        self.assertEqual(buttons['确认发表'].click_count,0)

    def test_direct_article_injected_context_keeps_origin_permission_and_owner(self):
        from utils.browser_session import BrowserSession
        body = self.root/'article.txt'; body.write_text('正文内容')
        app = article.DayuArticle('完整文章测试标题',body,self.root/'dayu_Creator.json','无需标注')
        self.profile('chromium')
        app.local_browser = 'chromium'
        self.context.grant_permissions = AsyncMock(side_effect=PermissionError('clipboard denied'))
        with self.assertRaisesRegex(PermissionError,'clipboard denied'): asyncio.run(app.main())
        self.assertTrue(self.context.closed)
        self.assertEqual(len(self.pw.chromium.persistent_calls),1)
        self.context.closed = False
        self.context.grant_permissions.reset_mock()
        with self.assertRaisesRegex(PermissionError,'clipboard denied'):
            asyncio.run(app.main(session=BrowserSession(browser=None,context=self.context,mode='local')))
        self.context.grant_permissions.assert_awaited_once_with(['clipboard-read','clipboard-write'],origin='https://mp.dayu.com')
        self.assertFalse(self.context.closed)
        self.assertEqual(len(self.pw.chromium.persistent_calls),1)

    def test_check_classifies_auth_redirect_while_waiting_for_login_anchor(self):
        self.profile()
        page = BackendPage()
        original = page.locator
        name = original('.header-info .name')
        async def hidden():
            page.url = 'https://uop.dayu.com/cas/login'
            raise TimeoutError('header did not become visible')
        name.is_visible = hidden
        page.locator = lambda selector: name if selector=='.header-info .name' else original(selector)
        self.context.next_page=page
        result=self.cli('check','--account','Creator')
        self.assertEqual(result[0],10,result)
