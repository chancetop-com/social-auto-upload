"""Xueqiu CLI through real configuration, Profile ownership and session orchestration."""
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
from sau_commands import arguments, xueqiu as command
from tests.fakes import FakeContext, FakePage, FakePlaywright
from tests.fakes_xhs_dom import RecordingLocator
from uploader.xueqiu_uploader import article, session, verification
from utils.local_profile import acquire_local_profile


class PlaywrightCM:
    def __init__(self, pw): self.pw = pw
    async def __aenter__(self): return self.pw
    async def __aexit__(self, *_): pass


class Expect:
    def __init__(self, locator): self.locator = locator
    async def to_have_count(self, count, **_):
        if await self.locator.count() != count: raise RuntimeError('required header missing')
    async def to_be_visible(self, **_):
        if not await self.locator.is_visible(): raise RuntimeError('required header hidden')


class BackendPage(FakePage):
    def __init__(self, *, uid='123', name='First', final_url=None, status=200, error=None):
        super().__init__()
        self.uid, self.name = uid, name
        self.final_url, self.status, self.error = final_url, status, error
    async def goto(self, url, **kwargs):
        await super().goto(url, **kwargs)
        self.url = self.final_url or url
        if self.error: raise self.error
        return SimpleNamespace(status=self.status)
    def locator(self, selector):
        if selector != 'nav .header-user[data-id]': raise AssertionError(selector)
        user = RecordingLocator(selector, attributes={'data-id': self.uid})
        user._children['span'] = RecordingLocator('name', text=self.name)
        return user
    async def close(self): raise AssertionError('persistent context owns local pages')


class BackendContext(FakeContext):
    def __init__(self):
        super().__init__()
        self.next_page = BackendPage()
    async def new_page(self):
        self.new_page_calls += 1
        self.pages.append(self.next_page)
        self.next_page.context = self
        return self.next_page


class XueqiuProfilesTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.pw = FakePlaywright(); self.context = BackendContext()
        self.pw.chromium.persistent_context = self.context
        async def forbidden(**_): raise AssertionError('temporary browser forbidden')
        self.pw.chromium.launch = forbidden
        for key, value in dict(BASE_DIR=self.root, LOCAL_CHROME_PATH='', LOCAL_BROWSER='chrome', LOCAL_CHROME_HEADLESS=False).items():
            self.stack.enter_context(patch.object(conf, key, value, create=True))
        self.stack.enter_context(patch.object(arguments, 'BASE_DIR', self.root))
        self.stack.enter_context(patch.dict(os.environ, {'MLX_API_TOKEN': '', 'ADSPOWER_API_KEY': '', 'HUMANIZE': '0'}))
        for module in (command, article, session, verification):
            self.stack.enter_context(patch.object(module, 'async_playwright', lambda: PlaywrightCM(self.pw)))
        self.stack.enter_context(patch.object(session, 'expect', Expect))
    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try: code = sau_cli.main(['xueqiu', *args])
            except SystemExit as exc: code = exc.code
        return code, out.getvalue(), err.getvalue()
    def profile(self, kind='chrome', account='Creator'):
        with acquire_local_profile('xueqiu', account, kind, create=True) as profile: return profile.path

    def test_login_check_reuse_profile_and_allow_alias_to_change_account(self):
        old = self.root / 'cookies/xueqiu_Creator.json'; old.parent.mkdir()
        old.write_text('broken old cookies'); identity = old.with_suffix('.identity.json'); identity.write_text('broken binding')
        result = self.cli('login', '--account', 'Creator', '--expected-name', 'First')
        self.assertEqual(result[0], 0, result)
        self.context.next_page = BackendPage(uid='456', name='Second')
        result = self.cli('login', '--account', 'Creator', '--expected-name', 'Second')
        self.assertEqual(result[0], 0, result)
        self.assertEqual(self.cli('check', '--account', 'Creator')[0], 0)
        self.assertEqual(self.pw.chromium.persistent_calls, [dict(user_data_dir=str(self.root / 'browser_profiles/xueqiu/Creator/chrome'), channel='chrome', headless=False, no_viewport=True)] * 3)
        self.assertFalse(self.context.storage_state_calls)
        self.assertEqual(old.read_text(), 'broken old cookies')
        self.assertEqual(identity.read_text(), 'broken binding')
        self.assertTrue(self.context.closed)

    def test_login_status_and_required_identity_fields_are_classified(self):
        self.assertEqual(self.cli('check', '--account', 'Creator')[0], 10)
        self.profile()
        for page, code in [
            (BackendPage(final_url='https://xueqiu.com/account/login'), 10),
            (BackendPage(final_url='https://mp.xueqiu.com/captcha'), 10),
            (BackendPage(status=403), 1), (BackendPage(status=503), 1),
            (BackendPage(uid=''), 1), (BackendPage(uid='0'), 1), (BackendPage(name=''), 1),
            (BackendPage(error=OSError('offline')), 1),
            (BackendPage(final_url='https://unexpected.invalid'), 1),
            (BackendPage(final_url='https://mp.xueqiu.com/captcha', error=TimeoutError('navigation interrupted')), 10),
        ]:
            with self.subTest(page=page.__dict__, code=code):
                self.context.next_page = page
                result = self.cli('check', '--account', 'Creator')
                self.assertEqual(result[0], code, result)
                if 'captcha' in str(page.final_url): self.assertIn('reason=verification', result[2])
        self.context.next_page = BackendPage()
        self.assertEqual(self.cli('login', '--account', 'Creator', '--expected-name', 'Other')[0], 1)

    def article_page(self):
        from tests.test_xueqiu_humanize import _form_page, _expect, PREVIEW_CONTENT
        from unittest.mock import AsyncMock
        page, parts = _form_page([], declaration_text='不添加创作声明')
        page._selectors['nav .header-user[data-id]'] = BackendPage(uid='456', name='Second').locator('nav .header-user[data-id]')
        async def content(expression, arg=None):
            return dict(sequence='正文', headings=0, bold=0, italic=0, links=[], expectedLinks=[])
        parts['body'].evaluate = content
        preview = page._selectors[PREVIEW_CONTENT]._children['div[class*="index_content-text_"] > div']
        preview.evaluate = content
        preview._children['img'] = RecordingLocator('no-images', count=0)
        self.stack.enter_context(patch.object(article, 'expect', _expect))
        self.stack.enter_context(patch.object(verification, 'expect', _expect))
        self.context.grant_permissions = AsyncMock()
        self.context.next_page = page
        self.content = self.root / 'article.html'; self.content.write_text('<p>正文</p>')
        return page, parts

    def upload(self, *args):
        return self.cli('upload-article', '--account', 'Creator', '--title', 'A title', '--content-file', str(self.content), '--declaration', '不添加创作声明', *args)

    def test_article_uses_current_identity_and_one_profile_for_complete_prepare_flow(self):
        self.profile('chromium')
        page, parts = self.article_page()
        result = self.upload('--prepare-only', '--local-browser', 'chromium', '--headless')
        self.assertEqual(result[0], 0, result)
        self.assertEqual(len(self.pw.chromium.persistent_calls), 1)
        self.assertEqual(self.pw.chromium.persistent_calls[0]['channel'], 'chromium')
        self.assertTrue(self.pw.chromium.persistent_calls[0]['headless'])
        self.assertEqual(parts['title'].buffer, 'A title')
        self.context.grant_permissions.assert_awaited_once_with(['clipboard-read', 'clipboard-write'], origin='https://mp.xueqiu.com')
        self.assertTrue(any('ClipboardItem' in script for script, _ in page.evaluate_calls))
        manifest = next((self.root / 'cookies/xueqiu_results').glob('*.json'))
        self.assertEqual(json.loads(manifest.read_text())['identity'], {'uid': '456', 'name': 'Second'})
        self.assertFalse(self.context.storage_state_calls)
        self.assertTrue(self.context.closed)

    def test_verify_uses_current_profile_and_preserves_historical_author(self):
        from unittest.mock import AsyncMock
        self.profile()
        result_file = self.root / 'historic.json'
        original = json.dumps(dict(identity={'uid': '123', 'name': 'First'}, content_id='789', title='Original', visibility='私人'))
        result_file.write_text(original)
        page = BackendPage(uid='456', name='Second'); self.context.next_page = page
        result = self.cli('verify', '--account', 'Creator', '--result', str(result_file))
        self.assertEqual(result[0], 1, result)
        self.assertIn('主体', result[2])
        self.assertEqual(result_file.read_text(), original)
        page = BackendPage(); self.context.next_page = page
        payload = dict(page=2, maxPage=2, list=[dict(id=789, user_id=123, title='Original', is_private=True)])
        response = SimpleNamespace(ok=True, status=200, url='https://mp.xueqiu.com/xq/query/v1/search/long?page=2', json=AsyncMock(return_value=payload), request=SimpleNamespace(all_headers=AsyncMock(return_value={})))
        class ResponseCM:
            async def __aenter__(self): return self
            async def __aexit__(self, *_): pass
            @property
            def value(self):
                async def resolve(): return response
                return resolve()
        page.expect_response = lambda *_, **__: ResponseCM()
        page.get_by_role = lambda *_, **__: RecordingLocator('content-management')
        page.screenshot = AsyncMock()
        result = self.cli('verify', '--account', 'Creator', '--result', str(result_file))
        self.assertEqual(result[0], 0, result)
        saved = json.loads(result_file.read_text())
        self.assertEqual(saved['identity'], {'uid': '123', 'name': 'First'})
        self.assertEqual(saved['url'], 'https://xueqiu.com/123/789')
        before_mismatch = result_file.read_text()
        payload['list'][0]['user_id'] = 456
        result = self.cli('verify', '--account', 'Creator', '--result', str(result_file))
        self.assertEqual(result[0], 1, result)
        self.assertIn('原作品的主体', result[2])
        self.assertEqual(result_file.read_text(), before_mismatch)
        self.assertEqual(len(self.pw.chromium.persistent_calls), 3)
        self.assertFalse(self.context.storage_state_calls)

    def test_config_precedence_kind_isolation_optional_fields_and_direct_entry(self):
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', True):
            self.assertEqual(self.cli('login', '--account', 'Creator', '--headed')[0], 0)
            self.assertEqual(self.cli('check', '--account', 'Creator')[0], 0)
            self.assertEqual(self.cli('check', '--account', 'Creator', '--local-browser', 'chromium')[0], 10)
            self.assertEqual(self.cli('login', '--account', 'Creator', '--local-browser', 'chromium')[0], 0)
            self.assertTrue(asyncio.run(session.check_xueqiu_account(self.root / 'xueqiu_Creator.json', False)))
        calls = self.pw.chromium.persistent_calls
        self.assertEqual([c['headless'] for c in calls], [False, True, True, False])
        self.assertEqual(calls[0]['user_data_dir'], calls[1]['user_data_dir'])
        self.assertNotEqual(calls[1]['user_data_dir'], calls[2]['user_data_dir'])
        with patch.dict(conf.__dict__):
            for field in ('LOCAL_BROWSER', 'LOCAL_CHROME_HEADLESS', 'LOCAL_CHROME_PATH'): conf.__dict__.pop(field, None)
            self.assertEqual(self.cli('check', '--account', 'Creator')[0], 0)
        self.assertEqual(calls[-1]['channel'], 'chrome')
        self.assertFalse(calls[-1]['headless'])

    def test_reset_protects_lease_and_history_without_resolving_binary(self):
        chrome, chromium = self.profile(), self.profile('chromium')
        history = self.root / 'history.json'; history.write_text('untouched')
        with patch.object(conf, 'LOCAL_CHROME_PATH', '/missing/browser'):
            with acquire_local_profile('xueqiu', 'Creator', 'chrome'):
                self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')[0], 1)
            self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')[0], 0)
            self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chrome')[0], 0)
        self.assertFalse(chrome.exists()); self.assertTrue(chromium.exists())
        self.assertEqual(history.read_text(), 'untouched')
        self.assertFalse(self.pw.chromium.persistent_calls)
        with patch.dict(os.environ, {'ADSPOWER_API_KEY': 'fixture'}):
            self.assertEqual(self.cli('reset-profile', '--account', 'Creator', '--browser-kind', 'chromium')[0], 2)

    def test_custom_binary_and_launch_failure_never_switch_profile(self):
        import plistlib
        binary = self.root / 'Chosen.app/Contents/MacOS/chosen'
        binary.parent.mkdir(parents=True); binary.write_text('fixture'); binary.chmod(0o755)
        (binary.parent.parent / 'Info.plist').write_bytes(plistlib.dumps(dict(CFBundleName='Chromium', CFBundleIdentifier='org.chromium.Chromium', CFBundleExecutable='chosen', CFBundleShortVersionString='123.0')))
        with patch('utils.local_browser.sys.platform', 'darwin'), patch.object(conf, 'LOCAL_CHROME_PATH', str(binary)):
            result = self.cli('login', '--account', 'Creator', '--local-browser', 'chrome')
            self.assertEqual(result[0], 0, result)
            self.pw.chromium.launch_error = PermissionError('launch denied')
            result = self.cli('check', '--account', 'Creator')
        self.assertEqual(result[0], 1, result)
        self.assertIn('executable_path=', result[2])
        self.assertEqual(len(self.pw.chromium.persistent_calls), 2)
        self.assertTrue(all(c['user_data_dir'].endswith('/chromium') for c in self.pw.chromium.persistent_calls))

    def test_verify_remains_local_under_provider_environment(self):
        self.profile()
        result_file = self.root / 'result.json'; result_file.write_text(json.dumps(dict(content_id='789', identity={'uid': '123'})))
        self.context.next_page = BackendPage(final_url='https://xueqiu.com/account/login')
        with patch.dict(os.environ, {'ADSPOWER_API_KEY': 'fixture', 'ADSPOWER_PROFILE_ID': 'other-account'}):
            result = self.cli('verify', '--account', 'Creator', '--result', str(result_file))
        self.assertEqual(result[0], 10, result)
        self.assertTrue(self.pw.chromium.persistent_calls[0]['user_data_dir'].endswith('/Creator/chrome'))

    def publish_page(self, *, payload=None, redirect=None, response_error=None):
        from tests.test_xueqiu_humanize import PREVIEW_CLOSE, PUBLISH_BUTTON, _Clickable
        from unittest.mock import AsyncMock
        page, parts = self.article_page()
        publish = _Clickable('publish', log=[])
        page._selectors[PREVIEW_CLOSE] = _Clickable('preview-close', log=[])
        page._selectors[PUBLISH_BUTTON] = publish
        async def clicked(**_):
            publish.click_count += 1
            if redirect: page.url = redirect
        publish.click = clicked
        page.set_content = AsyncMock()
        page._selectors['body'] = parts['body']
        parts['body']._children['img'].evaluate_all = AsyncMock(return_value=[])
        page.get_by_role_original = page.get_by_role
        page.get_by_role = lambda role, name=None, **kw: RecordingLocator('management') if role == 'link' else page.get_by_role_original(role, name=name, **kw)
        post = dict(id=789, user_id=456, title='A title', is_private=False, text='<p>正文</p>') if payload is None else payload
        responses = [
            SimpleNamespace(ok=True, status=200, json=AsyncMock(return_value=post, side_effect=response_error)),
            SimpleNamespace(ok=True, status=200, json=AsyncMock(return_value=dict(page=2, maxPage=2, list=[post])), url='https://mp.xueqiu.com/xq/query/v1/search/long?page=2', request=SimpleNamespace(all_headers=AsyncMock(return_value={}))),
        ]
        class ResponseCM:
            def __init__(self): self.response = responses.pop(0)
            async def __aenter__(self): return self
            async def __aexit__(self, *_): pass
            @property
            def value(self):
                async def resolve(): return self.response
                return resolve()
        page.expect_response = lambda *_, **__: ResponseCM()
        return page, publish

    def test_submission_success_unknown_and_login_keep_outcome_when_cleanup_fails(self):
        from patchright.async_api import TimeoutError as BrowserTimeout
        self.profile()
        cases = [({}, 0), ({'payload': {'error': 'unknown'}}, 9),
                 ({'redirect': 'https://xueqiu.com/account/login', 'response_error': BrowserTimeout('lost response')}, 10),
                 ({'redirect': 'https://mp.xueqiu.com/captcha', 'response_error': BrowserTimeout('lost response')}, 10)]
        for setup, expected in cases:
            with self.subTest(setup=setup, expected=expected):
                page, publish = self.publish_page(**setup)
                self.context.close_error = OSError('context close failed')
                result = self.upload()
                self.assertEqual(result[0], expected, result)
                self.assertEqual(publish.click_count, 1)
                if expected == 10: self.assertIn('publish_attempted=true', result[2])
                if setup.get('redirect', '').endswith('/captcha'): self.assertIn('reason=verification', result[2])
                self.assertFalse(self.context.storage_state_calls)
                with acquire_local_profile('xueqiu', 'Creator', 'chrome'): pass

    def test_cancellation_and_hanging_context_close_release_profile(self):
        from unittest.mock import AsyncMock
        self.profile()
        self.context.next_page = BackendPage(error=asyncio.CancelledError())
        async def hang(): await asyncio.Future()
        self.context.close = hang
        with patch('utils.local_browser_session.CLOSE_TIMEOUT_SECONDS', 0.01):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(sau_cli.dispatch(sau_cli.build_parser().parse_args(['xueqiu', 'check', '--account', 'Creator'])))
        with acquire_local_profile('xueqiu', 'Creator', 'chrome'): pass
        self.context.next_page = BackendPage()
        with patch('utils.local_browser_session.CLOSE_TIMEOUT_SECONDS', 0.01):
            result = self.cli('check', '--account', 'Creator')
        self.assertEqual(result[0], 0, result)

    def test_injected_article_session_is_not_reopened_or_closed(self):
        from utils.browser_session import BrowserSession
        page, parts = self.article_page()
        app = article.XueqiuArticle('A title', self.content, self.root / 'xueqiu_Creator.json', prepare_only=True)
        result = asyncio.run(app.main(session=BrowserSession(browser=object(), context=self.context, mode='local')))
        self.assertEqual(result['status'], 'prepared')
        self.assertFalse(self.context.closed)
        self.assertFalse(self.pw.chromium.persistent_calls)

    def test_http_access_failure_is_not_hidden_by_login_url_and_login_timeout_is_classified(self):
        from unittest.mock import AsyncMock
        self.profile()
        self.content = self.root / 'article.html'; self.content.write_text('<p>正文</p>')
        result_file = self.root / 'result.json'; result_file.write_text(json.dumps(dict(content_id='789', identity={'uid': '123'})))
        for args in [('check', '--account', 'Creator'), ('verify', '--account', 'Creator', '--result', str(result_file))]:
            self.context.next_page = BackendPage(final_url='https://xueqiu.com/account/login', status=403)
            result = self.cli(*args)
            self.assertEqual(result[0], 1, result)
            self.assertIn('HTTP 403', result[2])
        self.context.next_page = BackendPage(final_url='https://xueqiu.com/account/login', status=403)
        result = self.upload('--prepare-only')
        self.assertEqual(result[0], 1, result)
        page = BackendPage(final_url='https://mp.xueqiu.com/captcha')
        user = page.locator('nav .header-user[data-id]')
        user.wait_for = AsyncMock(side_effect=TimeoutError('login deadline'))
        page.locator = lambda _: user
        self.context.next_page = page
        result = self.cli('login', '--account', 'Creator', '--timeout', '1')
        self.assertEqual(result[0], 10, result)
        self.assertIn('reason=verification', result[2])

    def test_login_check_and_verify_do_not_locate_legacy_account_files(self):
        result_file = self.root / 'history.json'; result_file.write_text(json.dumps(dict(content_id='789', identity={'uid': '999'})))
        with patch.object(command, 'resolve_account_file', side_effect=AssertionError('legacy path resolved')):
            self.assertEqual(self.cli('login', '--account', 'Creator')[0], 0)
            self.assertEqual(self.cli('check', '--account', 'Creator')[0], 0)
            result = self.cli('verify', '--account', 'Creator', '--result', str(result_file))
        self.assertEqual(result[0], 1, result)
        self.assertIn('原作品作者', result[2])
        self.assertFalse((self.root / 'cookies').exists())

from tests.test_adspower_article_identity_platforms import _SeamHarness, _run, PROFILE


class XueqiuManagedProfilesTests(_SeamHarness, unittest.TestCase):
    def test_managed_headless_config_and_explicit_false_ignore_local_configuration(self):
        for flags, expected in [([], True), (['--headed'], False)]:
            with self.subTest(flags=flags):
                stack, calls, client, pw, browser, context, _ = self.start_seam(command)
                with stack, patch.object(conf, 'LOCAL_CHROME_HEADLESS', True), patch.object(conf, 'LOCAL_BROWSER', 'invalid', create=True), patch.object(conf, 'LOCAL_CHROME_PATH', '/does/not/exist'):
                    result = _run(['xueqiu', 'check', '--profile-id', PROFILE, '--local-browser', 'chromium', *flags])
                self.assertEqual(result[0], 0, result)
                self.assertEqual(calls[0]['headless'], expected)
                self.assertFalse(pw.chromium.persistent_calls)
                self.assert_managed_session(calls, client, pw, browser, context)
