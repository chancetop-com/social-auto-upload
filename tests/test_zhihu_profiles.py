"""Zhihu CLI through real configuration/Profile/session; only browser boundaries fake."""
import asyncio
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import conf
import sau_cli
from sau_commands import zhihu as command
from tests.fakes import FakeContext, FakePage, FakePlaywright
from tests.fakes_xhs_dom import RecordingLocator
from uploader.zhihu_uploader import session, article, video, verification
from utils.local_profile import acquire_local_profile


class PlaywrightCM:
    def __init__(self, playwright): self.playwright = playwright
    async def __aenter__(self): return self.playwright
    async def __aexit__(self, *_): pass


class Expect:
    def __init__(self, locator): self.locator = locator
    async def to_have_count(self, value, **_):
        if await self.locator.count() != value: raise AssertionError('missing current identity')
    async def to_be_visible(self, **_):
        if not await self.locator.is_visible(): raise AssertionError('missing current identity')
    async def to_contain_text(self, text, **_):
        actual = await self.locator.inner_text()
        if not (text.search(actual) if hasattr(text, 'search') else text in actual): raise AssertionError('text missing')
    async def to_have_value(self, text, **_):
        if text != await self.locator.input_value(): raise AssertionError('value differs')
    async def to_be_enabled(self, **_):
        if not await self.locator.is_enabled(): raise AssertionError('disabled')
    async def to_be_hidden(self, **_):
        if await self.locator.is_visible(): raise AssertionError('still visible')
    async def to_be_checked(self, **_):
        if not await self.locator.is_checked(): raise AssertionError('unchecked')


class BackendPage(FakePage):
    def __init__(self, *, name='First', avatar='https://pic.zhimg.com/first.jpg', url=None, status=200, error=None, present=True, wait_error=None):
        super().__init__()
        self.target_url, self.status, self.error = url, status, error
        self.name, self.avatar, self.present = name, avatar, present
        self.wait_error = wait_error
        self.title = 'Original title'
    async def goto(self, url, **kwargs):
        await super().goto(url, **kwargs)
        self.url = self.target_url or url
        if self.error: raise self.error
        return SimpleNamespace(status=self.status)
    def locator(self, selector):
        if selector == session.PROFILE_IMAGE:
            return RecordingLocator(selector, count=int(self.present), wait_error=self.wait_error, attributes={
                'alt': f'点击打开{self.name}的主页', 'src': self.avatar})
        if selector == 'main': return RecordingLocator(selector, text=self.title)
        raise AssertionError(f'unexpected selector {selector}')
    async def close(self): raise AssertionError('local page belongs to context owner')


class BackendContext(FakeContext):
    def __init__(self):
        super().__init__()
        self.next_page = BackendPage()
        self.permissions = []
    async def new_page(self):
        self.pages.append(self.next_page)
        self.next_page.context = self
        return self.next_page
    async def grant_permissions(self, permissions, **kwargs):
        self.permissions.append((permissions, kwargs))


class EditorField(RecordingLocator):
    def __init__(self, name, page, **kwargs):
        super().__init__(name, **kwargs)
        self.owner = self.page = page
        self.value = ''
    async def click(self, **kwargs):
        await super().click(**kwargs)
        self.owner.focused = self
    async def inner_text(self): return self.value
    async def input_value(self): return self.value
    async def press(self, key, **_):
        if key in ('Meta+V', 'Control+V'):
            self.value = self.owner.clipboard
    async def evaluate_all(self, *_): return []
    async def evaluate(self, expression, *_):
        if 'sequence' in expression:
            return {'sequence': '正文', 'formats': dict.fromkeys(['h1','h2','h3','h4','h5','h6','strong','em','ul','ol','blockquote','pre'], 0), 'links': []}
        return None


class ArticlePage(BackendPage):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.focused, self.clipboard = None, None
        self.title_field = EditorField('title', self)
        self.body = EditorField('body', self, children={'img': EditorField('images', self, count=0)})
        self.publish = RecordingLocator('publish')
        async def insert(text): self.focused.value += text
        self.keyboard = SimpleNamespace(insert_text=insert)
    def locator(self, selector):
        if selector == 'textarea[placeholder="请输入标题（最多 100 个字）"]': return self.title_field
        if selector == 'div[contenteditable="true"][role="textbox"]': return self.body
        return super().locator(selector)
    async def evaluate(self, expression, *args, **kwargs):
        await super().evaluate(expression, *args, **kwargs)
        if 'ClipboardItem' in expression: self.clipboard = args[0]
        if 'template' in expression: return []
    def get_by_role(self, role, name=None, **_):
        if role == 'button' and name == '发布': return self.publish
        if role == 'article': return SimpleNamespace(get_by_role=lambda *_, **__: RecordingLocator('published heading'))
        raise AssertionError((role, name))
    async def wait_for_url(self, *_, **__): self.url = 'https://zhuanlan.zhihu.com/p/123'


class TextOptions(RecordingLocator):
    async def all_inner_texts(self):
        return [await item.inner_text() for item in self._items]


def video_page():
    from tests.test_zhihu_humanize import _video_form_page, _Clickable, CATEGORY, VIDEO_MARK, FORM_ROOT, OPTION_LIST, MARK_MODAL
    page, fields = _video_form_page([])
    page._selectors[session.PROFILE_IMAGE] = RecordingLocator('current', attributes={
        'alt': '点击打开Current account的主页', 'src': 'https://pic.zhimg.com/current.jpg'})
    page._selectors['input.VideoUploadButton-fileInput[type=file]'] = RecordingLocator('video-input')
    fields['control']._text = CATEGORY
    menu = page._selectors[OPTION_LIST]
    menu._text = CATEGORY
    menu._children['role:option'] = TextOptions('categories', items=[RecordingLocator('category', text=CATEGORY)])
    modal = page._selectors[MARK_MODAL]
    modal._children['.VideoUploadForm-videoTypeModalOption'] = TextOptions('marks', items=[RecordingLocator('mark', text=VIDEO_MARK)])
    cancel = _Clickable('cancel', log=[])
    modal._children['role:button:取消'] = cancel
    async def hide(**_): modal._visible = False
    async def show(**_): modal._visible = True
    cancel.click = fields['confirm'].click = hide
    fields['mark_button'].click = show
    page._selectors['role:button:发布视频'] = RecordingLocator('publish')
    return page, fields


class ZhihuProfilesTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.pw = FakePlaywright()
        async def forbid_launch(**_): raise AssertionError('use persistent Profile')
        self.pw.chromium.launch = forbid_launch
        self.context = BackendContext()
        self.pw.chromium.persistent_context = self.context
        for key, value in {'BASE_DIR': self.root, 'LOCAL_CHROME_PATH': '', 'LOCAL_CHROME_HEADLESS': False, 'LOCAL_BROWSER': 'chrome'}.items():
            self.stack.enter_context(patch.object(conf, key, value, create=True))
        self.stack.enter_context(patch.dict(os.environ, {'MLX_API_TOKEN': '', 'ADSPOWER_API_KEY': '', 'HUMANIZE': '0'}))
        for module in (command, session, article, video, verification):
            self.stack.enter_context(patch.object(module, 'async_playwright', lambda: PlaywrightCM(self.pw)))
        for module in (session, verification, article, video):
            self.stack.enter_context(patch.object(module, 'expect', Expect))
    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try: code = sau_cli.main(['zhihu', *args])
            except SystemExit as error: code = error.code
        return code, out.getvalue(), err.getvalue()
    def profile(self, kind='chrome', account='Creator'):
        with acquire_local_profile('zhihu', account, kind, create=True) as profile:
            return profile.path

    def test_login_and_check_allow_alias_to_change_account_without_old_files(self):
        old = self.root / 'cookies/zhihu_Creator.identity.json'
        old.parent.mkdir()
        old.write_text('invalid legacy identity')
        first = self.cli('login', '--account', 'Creator')
        self.assertEqual(first[0], 0, first)
        self.context.next_page = BackendPage(name='Second', avatar='https://pic.zhimg.com/second.jpg')
        second = self.cli('login', '--account', 'Creator')
        self.assertEqual(second[0], 0, second)
        self.assertIn('Second', second[1])
        self.assertEqual(self.cli('check', '--account', 'Creator')[0], 0)
        calls = self.pw.chromium.persistent_calls
        self.assertEqual(calls, [dict(user_data_dir=str(self.root / 'browser_profiles/chrome/zhihu/Creator'), channel='chrome', headless=False, no_viewport=True)] * 3)
        self.assertTrue(self.context.closed)
        self.assertFalse(self.context.storage_state_calls)
        self.assertFalse(self.context.add_init_script_calls)
        self.assertEqual(old.read_text(), 'invalid legacy identity')

    def test_login_evidence_is_distinct_from_browser_page_and_identity_faults(self):
        self.assertEqual(self.cli('check', '--account', 'Creator')[0], 10)
        self.profile()
        for page, code in [
            (BackendPage(url='https://www.zhihu.com/signin'), 10),
            (BackendPage(url='https://www.zhihu.com/account/captcha'), 10),
            (BackendPage(status=403), 1), (BackendPage(status=503), 1),
            (BackendPage(present=False), 1), (BackendPage(name=''), 1),
            (BackendPage(avatar='https://pic.zhimg.com'), 1),
            (BackendPage(error=OSError('network failure')), 1),
            (BackendPage(url='https://unrelated.invalid'), 1),
            (BackendPage(url='https://www.zhihu.com/signin', error=TimeoutError('navigation interrupted')), 10),
        ]:
            with self.subTest(url=page.target_url, status=page.status, name=page.name):
                self.context.next_page = page
                result = self.cli('check', '--account', 'Creator')
                self.assertEqual(result[0], code, result)
                if 'captcha' in str(page.target_url): self.assertIn('reason=verification', result[2])

    def test_article_preflight_and_editor_share_one_profile_and_current_identity(self):
        self.profile('chromium')
        content = self.root / 'article.html'
        content.write_text('<p>正文</p>')
        page = ArticlePage(name='Current account', avatar='https://pic.zhimg.com/current.jpg')
        self.context.next_page = page
        result = self.cli('upload-article', '--account', 'Creator', '--title', 'Article title',
            '--content-file', str(content), '--prepare-only', '--headless', '--local-browser', 'chromium')
        self.assertEqual(result[0], 0, result)
        payload = json.loads(result[1])
        self.assertEqual(payload['status'], 'prepared')
        self.assertEqual(payload['identity'], {'name': 'Current account', 'avatar_path': '/current.jpg'})
        self.assertEqual(Path(payload['result_file']).parent, self.root / 'cookies/zhihu_results')
        self.assertEqual(len(self.pw.chromium.persistent_calls), 1)
        self.assertEqual(self.pw.chromium.persistent_calls[0]['channel'], 'chromium')
        self.assertTrue(self.pw.chromium.persistent_calls[0]['headless'])
        self.assertEqual(page.title_field.value, 'Article title')
        self.assertEqual(page.clipboard, '<p>正文</p>')
        self.assertEqual(self.context.permissions, [(['clipboard-read', 'clipboard-write'], {'origin': 'https://zhuanlan.zhihu.com'})])
        self.assertEqual(page.publish.click_count, 0)

    def test_verify_keeps_historical_subject_and_title_evidence_after_alias_switch(self):
        self.profile()
        history = self.root / 'result.json'
        original = dict(identity={'name': 'First', 'avatar_path': '/first.jpg'},
            title='Original title', url='https://www.zhihu.com/pin/123', status='submission_unknown')
        history.write_text(json.dumps(original))
        self.context.next_page = BackendPage(name='Second', avatar='https://pic.zhimg.com/second.jpg')
        before = history.read_bytes()
        result = self.cli('verify', '--account', 'Creator', '--result', str(history))
        self.assertEqual(result[0], 1, result)
        self.assertIn('原作品', result[2])
        self.assertEqual(history.read_bytes(), before)
        self.context.next_page = BackendPage()
        with patch.dict(os.environ, {'ADSPOWER_API_KEY': 'present'}):
            result = self.cli('verify', '--account', 'Creator', '--result', str(history))
        self.assertEqual(result[0], 0, result)
        self.assertTrue(json.loads(history.read_text())['verified'])
        self.assertEqual(json.loads(history.read_text())['identity'], original['identity'])
        self.assertEqual(len(self.pw.chromium.persistent_calls), 2)
        self.assertFalse(self.pw.chromium.connect_calls)

    def test_video_uses_current_profile_for_upload_and_form_without_identity_file(self):
        self.profile()
        media = self.root / 'video.mp4'
        media.write_bytes(b'x' * 102401)
        page, fields = video_page()
        self.context.next_page = page
        capture = SimpleNamespace(get=lambda _: 30, release=lambda: None)
        with patch.object(video.cv2, 'VideoCapture', return_value=capture):
            result = self.cli('upload-video', '--account', 'Creator', '--file', str(media),
                '--title', 'Video title', '--originality', 'original', '--category', '教育',
                '--video-mark', '含 AI 生成内容', '--prepare-only')
        self.assertEqual(result[0], 0, result)
        payload = json.loads(result[1])
        self.assertEqual(payload['status'], 'prepared')
        self.assertEqual(payload['identity'], {'name': 'Current account', 'avatar_path': '/current.jpg'})
        self.assertEqual(fields['title'].buffer, 'Video title')
        self.assertTrue(fields['originality'].checked)
        self.assertEqual(len(self.pw.chromium.persistent_calls), 1)
        self.assertEqual(page._selectors['input.VideoUploadButton-fileInput[type=file]'].files, [str(media)])
        self.assertEqual(page._selectors['role:button:发布视频'].click_count, 0)

    def test_defaults_explicit_modes_and_reset_preserve_other_profile_and_history(self):
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', True):
            self.assertEqual(self.cli('login', '--account', 'Creator', '--headed')[0], 0)
            self.assertEqual(self.cli('check', '--account', 'Creator')[0], 0)
            self.assertEqual(self.cli('check', '--account', 'Creator', '--local-browser', 'chromium')[0], 10)
            self.assertEqual(self.cli('login', '--account', 'Creator', '--local-browser', 'chromium')[0], 0)
        calls = self.pw.chromium.persistent_calls
        self.assertEqual([call['headless'] for call in calls], [False, True, True])
        self.assertNotEqual(calls[1]['user_data_dir'], calls[2]['user_data_dir'])
        with patch.dict(conf.__dict__):
            for key in ('LOCAL_BROWSER', 'LOCAL_CHROME_PATH', 'LOCAL_CHROME_HEADLESS'):
                conf.__dict__.pop(key, None)
            self.assertEqual(self.cli('check', '--account', 'Creator')[0], 0)
        self.assertFalse(calls[-1]['headless'])
        history = self.root / 'historical.json'; history.write_text('untouched')
        with patch.object(conf, 'LOCAL_CHROME_PATH', '/missing/binary'):
            with acquire_local_profile('zhihu', 'Creator', 'chrome'):
                self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')[0], 1)
            self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')[0], 0)
            self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')[0], 0)
        self.assertFalse(Path(calls[0]['user_data_dir']).exists())
        self.assertTrue(Path(calls[2]['user_data_dir']).exists())
        self.assertEqual(history.read_text(), 'untouched')

    def test_managed_headless_uses_config_and_ignores_local_options(self):
        from tests.fakes import FakeAdspowerClient, FakeMultiloginClient, FakeBrowser
        for token, symbol, klass in [('ADSPOWER_API_KEY', 'AdspowerClient', FakeAdspowerClient),
                                     ('MLX_API_TOKEN', 'MultiloginClient', FakeMultiloginClient)]:
            for flags, headless in [((), True), (('--headed',), False)]:
                client = klass()
                self.context.closed = False
                page = BackendPage()
                async def close(): page.closed = True
                page.close = close
                self.context.next_page = page
                browser = FakeBrowser([self.context])
                self.pw.chromium.queue_connect_browser(browser)
                with patch.dict(os.environ, {token:'test-only-token'}), patch.object(conf, 'LOCAL_CHROME_PATH', '/unused/missing'), patch.object(conf, 'LOCAL_BROWSER', 'unused-invalid', create=True), patch.object(conf, 'LOCAL_CHROME_HEADLESS', True), patch('sau_commands.browser.' + symbol, return_value=client):
                    result = self.cli('check', '--profile-id', 'profile', '--folder-id', 'folder', '--local-browser', 'invalid', *flags)
                self.assertEqual(result[0], 0, result)
                self.assertEqual(client.start_calls[0][-1], headless)
                self.assertEqual(client.stop_calls, ['profile'])
                self.assertFalse(self.context.closed)
                self.assertEqual(browser.close_calls, 1)
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.assertFalse((self.root / 'browser_profiles').exists())

    def test_login_requires_current_evidence_and_reports_explicit_login_timeout(self):
        self.context.next_page = BackendPage(url='https://www.zhihu.com/signin', wait_error=article.BrowserTimeoutError('login timeout'))
        result = self.cli('login', '--account', 'Creator')
        self.assertEqual(result[0], 10, result)
        self.assertTrue(self.context.closed)
        self.context.next_page = BackendPage(avatar='not-a-url')
        result = self.cli('login', '--account', 'Creator')
        self.assertEqual(result[0], 1, result)

    def test_article_pre_and_post_submit_login_and_unknown_preserve_phase_through_cleanup(self):
        self.profile()
        content = self.root / 'article.html'; content.write_text('<p>正文</p>')
        for phase, expected in [('before', 10), ('after', 10), ('click-error', 10), ('unknown', 9), ('success', 0)]:
            with self.subTest(phase=phase):
                page = ArticlePage()
                self.context.next_page = page
                self.context.close_error = OSError('cleanup fault')
                async def redirected(*_, **__):
                    page.url = 'https://www.zhihu.com/account/captcha'
                    if phase == 'click-error': page.publish.click_count += 1
                    raise article.BrowserTimeoutError('interrupted')
                if phase == 'before': page.body.press = redirected
                elif phase == 'after': page.wait_for_url = redirected
                elif phase == 'click-error': page.publish.click = redirected
                elif phase == 'unknown':
                    async def unknown(*_, **__): raise article.BrowserTimeoutError('no result')
                    page.wait_for_url = unknown
                result = self.cli('upload-article', '--account', 'Creator', '--title', 'Article title', '--content-file', str(content))
                self.assertEqual(result[0], expected, result)
                self.assertEqual(page.publish.click_count, int(phase != 'before'))
                if expected == 10:
                    self.assertIn('reason=verification', result[2])
                    self.assertEqual('publish_attempted=true' in result[2], phase != 'before')
                manifests = sorted((self.root / 'cookies/zhihu_results').glob('*.json'), key=lambda p: p.stat().st_mtime_ns)
                state = json.loads(manifests[-1].read_text())
                self.assertEqual(state['status'], 'published' if phase == 'success' else 'failed_before_submit' if phase == 'before' else 'submission_unknown')

    def test_cancellation_and_hung_cleanup_release_profile_without_local_page_close(self):
        self.profile()
        self.context.next_page = BackendPage(error=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError): self.cli('check', '--account', 'Creator')
        self.assertTrue(self.context.closed)
        async def hang(): await asyncio.Event().wait()
        self.context.next_page = BackendPage()
        self.context.next_page.close = hang
        self.context.close = hang
        args = sau_cli.build_parser().parse_args(['zhihu', 'check', '--account', 'Creator'])
        with patch('utils.local_browser_session.CLOSE_TIMEOUT_SECONDS', 0.02):
            self.assertEqual(asyncio.run(asyncio.wait_for(sau_cli.dispatch(args), 1)), 0)
        with acquire_local_profile('zhihu', 'Creator', 'chrome'): pass

    def test_direct_defaults_legacy_alias_hint_and_borrowed_session_ownership(self):
        from utils.browser_session import BrowserSession
        content = self.root / 'article.html'; content.write_text('<p>正文</p>')
        legacy = self.root / 'old/zhihu_Creator.json'
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', True):
            asyncio.run(session.login_zhihu_account(account_name='Creator'))
            self.assertTrue(asyncio.run(session.check_zhihu_account(legacy, headless=False)))
            self.context.next_page = ArticlePage()
            app = article.ZhihuArticle('Title', content, legacy, prepare_only=True, headless=False)
            result = asyncio.run(app.main())
        self.assertEqual(Path(result['result_file']).parent, legacy.parent / 'zhihu_results')
        self.assertEqual([call['headless'] for call in self.pw.chromium.persistent_calls], [True, False, False])
        self.assertEqual(len({call['user_data_dir'] for call in self.pw.chromium.persistent_calls}), 1)
        self.context.closed = False
        self.context.next_page = ArticlePage()
        app = article.ZhihuArticle('Title', content, account_name='Creator', prepare_only=True)
        asyncio.run(app.main(session=BrowserSession(browser=None, context=self.context, mode='local')))
        self.assertFalse(self.context.closed)
        self.assertEqual(len(self.pw.chromium.persistent_calls), 3)

    def test_custom_binary_kind_overrides_selection_without_fallback(self):
        import plistlib
        binary = self.root / 'Chosen.app/Contents/MacOS/chosen'
        binary.parent.mkdir(parents=True)
        binary.write_text('fixture'); binary.chmod(0o755)
        (binary.parent.parent / 'Info.plist').write_bytes(plistlib.dumps(dict(
            CFBundleName='Chromium', CFBundleIdentifier='org.chromium.Chromium',
            CFBundleExecutable='chosen', CFBundleShortVersionString='123.0')))
        with patch('utils.local_browser.sys.platform', 'darwin'), patch.object(conf, 'LOCAL_CHROME_PATH', str(binary)):
            self.assertEqual(self.cli('login', '--account', 'Creator', '--local-browser', 'invalid')[0], 0)
            self.pw.chromium.launch_error = PermissionError('browser denied')
            result = self.cli('check', '--account', 'Creator')
        self.assertEqual(result[0], 1, result)
        self.assertIn('executable_path=', result[2])
        self.assertEqual(len(self.pw.chromium.persistent_calls), 2)
        self.assertTrue(all(call['user_data_dir'].endswith('/chromium/zhihu/Creator') for call in self.pw.chromium.persistent_calls))

    def test_managed_login_reset_and_rate_limit_keep_existing_routes(self):
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
        self.assertFalse(self.pw.chromium.persistent_calls)

    def test_video_outcomes_keep_one_submission_and_confirmed_success(self):
        self.profile()
        media = self.root / 'video.mp4'; media.write_bytes(b'x' * 102401)
        capture = SimpleNamespace(get=lambda _: 30, release=lambda: None)
        for phase, code in [('before', 10), ('after', 10), ('unknown', 9), ('success', 0)]:
            with self.subTest(phase=phase):
                page, _ = video_page()
                self.context.next_page = page
                self.context.close_error = OSError('cleanup fault')
                publish = page._selectors['role:button:发布视频']
                async def redirect(*_, **__):
                    page.url = 'https://www.zhihu.com/signin'
                    if phase == 'after': publish.click_count += 1
                    raise TimeoutError('login redirect')
                if phase == 'before': page._selectors['input.VideoUploadButton-fileInput[type=file]'].set_input_files = redirect
                elif phase == 'after': publish.click = redirect
                elif phase == 'success':
                    page._selectors['text:发布成功:exact'] = RecordingLocator('confirmed')
                    # Detail popup failure is deliberately left unscripted: known success stays success.
                with patch.object(video.cv2, 'VideoCapture', return_value=capture):
                    result = self.cli('upload-video', '--account', 'Creator', '--file', str(media),
                        '--title', 'Video title', '--originality', 'original', '--category', '教育', '--video-mark', '含 AI 生成内容')
                self.assertEqual(result[0], code, result)
                self.assertEqual(publish.click_count, int(phase != 'before'))
                if phase == 'after': self.assertIn('publish_attempted=true', result[2])
                if phase == 'before': self.assertNotIn('publish_attempted=true', result[2])
                if phase == 'success': self.assertEqual(json.loads(result[1])['status'], 'published')

    def test_preflight_failure_stops_upload_and_keeps_profile_for_recovery(self):
        path = self.profile()
        content = self.root / 'article.html'; content.write_text('<p>正文</p>')
        self.context.next_page = BackendPage(error=OSError('network failure'))
        result = self.cli('upload-article', '--account', 'Creator', '--title', 'Title', '--content-file', str(content))
        self.assertEqual(result[0], 1, result)
        self.assertIn('network failure', result[2])
        self.assertEqual(len(self.context.pages), 1)
        self.assertTrue(path.exists())
        self.assertTrue(self.context.closed)
        self.assertFalse((self.root / 'cookies/zhihu_results').exists())

    def test_verify_mid_read_login_keeps_history_unchanged(self):
        self.profile()
        history = self.root / 'result.json'
        history.write_text(json.dumps(dict(identity={'name': 'First', 'avatar_path': '/first.jpg'},
            title='Original title', url='https://www.zhihu.com/pin/123', status='submission_unknown')))
        before = history.read_bytes()
        page = self.context.next_page
        class RedirectedExpect(Expect):
            async def to_contain_text(self, *_args, **_kwargs):
                page.url = 'https://www.zhihu.com/account/captcha'
                raise AssertionError('redirected while reading original title')
        with patch.object(verification, 'expect', RedirectedExpect):
            result = self.cli('verify', '--account', 'Creator', '--result', str(history))
        self.assertEqual(result[0], 10, result)
        self.assertIn('reason=verification', result[2])
        self.assertEqual(history.read_bytes(), before)
