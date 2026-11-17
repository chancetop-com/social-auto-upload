"""Formal TikTok dispatch with real config/Profile/session orchestration."""
import asyncio
import io
import os
import tempfile
import unittest
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import conf
import sau_cli
from sau_commands import tiktok
from tests.fakes import FakeContext, FakePlaywright
from tests.test_mlx_tiktok import _AsyncCM
from utils.local_profile import acquire_local_profile


@contextmanager
def terminal_enter():
    """Supply Enter at the OS input boundary used by local manual login."""
    if os.name == 'nt':
        with patch('sys.stdin.isatty', return_value=True), patch('msvcrt.kbhit', return_value=True), patch('msvcrt.getwche', return_value='\r'):
            yield
        return
    reader, writer = os.pipe()
    try:
        os.write(writer, b'\n')
    finally:
        os.close(writer)
    with os.fdopen(reader) as terminal, patch.object(terminal, 'isatty', return_value=True), patch('sys.stdin', terminal):
        yield


class ProbeLocator:
    def __init__(self, count): self.value = count
    @property
    def first(self): return self
    async def count(self): return self.value
    async def is_visible(self): return bool(self.value)
    async def wait_for(self, **kwargs):
        if not self.value: raise RuntimeError('absent')


class ProbePage:
    def __init__(self, state='valid'):
        self.state = state
        self.url = 'about:blank'
        self.closed = False
    async def goto(self, url, **kwargs):
        self.url = ('https://www.tiktok.com/login' if self.state == 'login' else 'https://www.tiktok.com/captcha/verify' if self.state == 'verification' else url)
        if self.state == 'network': raise OSError('network unavailable')
    def locator(self, selector):
        return ProbeLocator(int(self.state == 'valid' and 'select_video' in selector))
    def get_by_text(self, text): return ProbeLocator(0)
    async def wait_for_selector(self, selector, **kwargs):
        if self.state != 'valid': raise RuntimeError('absent')
    async def close(self):
        self.closed = True
        if hasattr(self, "context"):
            self.context.pages.remove(self)


class ProbeContext(FakeContext):
    def __init__(self, state='valid'):
        super().__init__()
        self.state = state
        self.created_pages = []
    async def new_page(self):
        page = ProbePage(self.state)
        page.context = self
        self.pages.append(page)
        self.created_pages.append(page)
        return page


class TikTokProfileCliTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(conf, 'BASE_DIR', self.root))
        self.stack.enter_context(patch.object(conf, 'LOCAL_CHROME_PATH', ''))
        self.stack.enter_context(patch.object(conf, 'LOCAL_CHROME_HEADLESS', True))
        self.stack.enter_context(patch.dict(os.environ, {'MLX_API_TOKEN':'', 'ADSPOWER_API_KEY':''}))
        self.pw = FakePlaywright()
        self.context = ProbeContext()
        self.pw.chromium.persistent_context = self.context
        self.stack.enter_context(patch.object(tiktok, 'async_playwright', lambda: _AsyncCM(self.pw)))
        self.addCleanup(self.stack.close)
    def run_cli(self, *argv):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            code = sau_cli.main(['tiktok', *argv])
        return code, out.getvalue(), err.getvalue()
    def profile(self, kind='chrome'):
        with acquire_local_profile('tiktok', 'creator', kind, create=True): pass

    def test_direct_check_accepts_unprefixed_legacy_json_name(self):
        import asyncio
        from uploader.tk_uploader import main_chrome as uploader
        self.stack.enter_context(patch.object(uploader, 'async_playwright', lambda: _AsyncCM(self.pw)))
        self.profile()
        self.assertTrue(asyncio.run(uploader.cookie_auth('/absent/creator.json')))
        self.assertEqual(Path(self.pw.chromium.persistent_calls[-1]['user_data_dir']).name, 'creator')
        self.assertFalse(self.context.storage_state_calls)

    def test_reappearing_legacy_file_is_untouched_and_login_does_not_restart(self):
        with terminal_enter():
            code, _, err = self.run_cli('login', '--account', 'creator', '--headed')
            self.assertEqual(code, 0, err)
        legacy = self.root / 'cookies/tiktok_creator.json'
        legacy.parent.mkdir(exist_ok=True)
        legacy.write_bytes(b'reappeared broken credentials')
        open_file = Path.open
        def deny_legacy_open(path, *args, **kwargs):
            if path == legacy:
                raise AssertionError('normal commands must never read or rewrite old credentials')
            return open_file(path, *args, **kwargs)
        with patch.object(Path, 'open', deny_legacy_open):
            with terminal_enter():
                code, _, err = self.run_cli('login', '--account', 'creator', '--headed')
                self.assertEqual(code, 0, err)
            code, _, err = self.run_cli('check', '--account', 'creator', '--headed')
            self.assertEqual(code, 0, err)
        self.assertEqual(legacy.read_bytes(), b'reappeared broken credentials')
        self.assertEqual(len(self.pw.chromium.persistent_calls), 3)
        self.assertFalse(self.context.storage_state_calls)

    def test_check_uses_profile_and_config_and_ignores_broken_legacy_json(self):
        self.profile()
        (self.root / 'cookies').mkdir()
        old = self.root / 'cookies/tiktok_creator.json'
        old.write_text('not JSON')
        self.assertEqual(self.run_cli('check', '--account', 'creator')[0], 0)
        call = self.pw.chromium.persistent_calls[0]
        self.assertEqual(call['channel'], 'chrome')
        self.assertTrue(call['headless'])
        self.assertTrue(call['no_viewport'])
        self.assertTrue(all("lang=" not in page.url for page in self.context.created_pages))
        self.assertFalse(self.context.storage_state_calls)
        self.assertEqual(old.read_text(), 'not JSON')
        self.assertTrue(self.context.closed)

    def test_missing_profile_is_login_required_without_launch(self):
        self.assertEqual(self.run_cli('check', '--account', 'creator')[0], 10)
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.assertFalse((self.root / 'cookies').exists())

    def test_check_finishes_when_page_close_would_hang(self):
        self.profile()

        async def hanging_close(page):
            await asyncio.Future()

        async def scenario():
            args = sau_cli.build_parser().parse_args(['tiktok', 'check', '--account', 'creator'])
            task = asyncio.create_task(sau_cli.dispatch(args))
            try:
                done, _ = await asyncio.wait({task}, timeout=0.2)
                self.assertIn(task, done, 'check must reach its owning context cleanup')
                self.assertEqual(await task, 0)
                self.assertTrue(self.context.closed)
                with acquire_local_profile('tiktok', 'creator', 'chrome') as profile:
                    self.assertTrue(profile.exists)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

        with patch.object(ProbePage, 'close', hanging_close):
            asyncio.run(scenario())

    def test_login_finishes_when_page_close_would_hang(self):
        async def hanging_close(page):
            await asyncio.Future()

        async def scenario():
            args = sau_cli.build_parser().parse_args(['tiktok', 'login', '--account', 'creator'])
            task = asyncio.create_task(sau_cli.dispatch(args))
            try:
                done, _ = await asyncio.wait({task}, timeout=0.2)
                self.assertIn(task, done, 'login must reach its owning context cleanup')
                self.assertEqual(await task, 0)
                self.assertTrue(self.context.closed)
                with acquire_local_profile('tiktok', 'creator', 'chrome') as profile:
                    self.assertTrue(profile.exists)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

        with patch.object(ProbePage, 'close', hanging_close), terminal_enter():
            asyncio.run(scenario())

    def test_cancelled_check_and_login_close_context_and_release_profile(self):
        self.profile()

        async def scenario(action):
            navigating = asyncio.Event()

            async def waiting_navigation(page, *args, **kwargs):
                navigating.set()
                await asyncio.Future()

            async def hanging_close(page):
                await asyncio.Future()

            args = sau_cli.build_parser().parse_args(['tiktok', action, '--account', 'creator'])
            with patch.object(ProbePage, 'goto', waiting_navigation), patch.object(ProbePage, 'close', hanging_close):
                task = asyncio.create_task(sau_cli.dispatch(args))
                try:
                    await asyncio.wait_for(navigating.wait(), timeout=1)
                    task.cancel()
                    done, _ = await asyncio.wait({task}, timeout=0.2)
                    self.assertIn(task, done, 'cancellation must reach context cleanup')
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                    self.assertTrue(self.context.closed)
                    with acquire_local_profile('tiktok', 'creator', 'chrome') as profile:
                        self.assertTrue(profile.exists)
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)

        for action in ['check', 'login']:
            with self.subTest(action=action), patch('sys.stdin.isatty', return_value=True):
                self.context.closed = False
                asyncio.run(scenario(action))

    def test_windows_console_input_allows_enter_eof_and_cancellation(self):
        from types import SimpleNamespace

        async def scenario(character):
            reading = asyncio.Event()

            def key_available():
                reading.set()
                return character is not None

            console = SimpleNamespace(kbhit=key_available, getwche=lambda: character)
            args = sau_cli.build_parser().parse_args(['tiktok', 'login', '--account', 'creator'])
            with patch.dict('sys.modules', {'msvcrt': console}), patch('sys.platform', 'win32'), patch('sys.stdin.isatty', return_value=True):
                task = asyncio.create_task(sau_cli.dispatch(args))
                try:
                    await asyncio.wait_for(reading.wait(), timeout=1)
                    if character is None:
                        task.cancel()
                    done, _ = await asyncio.wait({task}, timeout=0.2)
                    self.assertIn(task, done)
                    if character is None:
                        with self.assertRaises(asyncio.CancelledError):
                            await task
                    elif character == '\x1a':
                        with self.assertRaisesRegex(RuntimeError, '无法读取终端输入'):
                            await task
                    else:
                        self.assertEqual(await task, 0)
                    self.assertTrue(self.context.closed)
                    with acquire_local_profile('tiktok', 'creator', 'chrome') as profile:
                        self.assertTrue(profile.exists)
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)

        for character in ['\r', '\x1a', None]:
            with self.subTest(character=character):
                self.context.closed = False
                asyncio.run(scenario(character))

    def test_local_verification_and_network_errors_are_distinct(self):
        self.profile()
        for state, expected in [('login', 10), ('network', 1), ('unknown', 1), ('verification', 10)]:
            with self.subTest(state=state):
                self.context.state = state
                code, out, err = self.run_cli('check', '--account', 'creator', '--headed')
                self.assertEqual(code, expected, err)
                if state == 'verification': self.assertIn('验证', err)

    def test_direct_uploader_explicit_false_uses_same_profile_preflight(self):
        import asyncio
        from uploader.tk_uploader.main_chrome import TiktokVideo
        from utils.errors import LoginRequiredError
        self.profile()
        self.context.state = 'login'
        for headless in [None, False]:
            app = TiktokVideo('Title', 'video.mp4', [], 0, None, account_name='creator', headless=headless)
            with self.assertRaises(LoginRequiredError):
                asyncio.run(app.upload(self.pw))
            self.assertEqual(self.pw.chromium.persistent_calls[-1]['headless'], headless is None)
            self.assertTrue(self.context.closed)

    def test_login_uses_requested_mode_once_and_allows_alias_relogin(self):
        for extra in [[], ['--headed'], ['--headless']]:
            with terminal_enter():
                code, _, err = self.run_cli('login', '--account', 'creator', *extra)
                self.assertEqual(code, 0, err)
        self.assertEqual([c['headless'] for c in self.pw.chromium.persistent_calls], [True, False, True])
        self.assertEqual(len({c['user_data_dir'] for c in self.pw.chromium.persistent_calls}), 1)
        self.assertFalse(self.context.storage_state_calls)
        self.assertFalse((self.root / 'cookies').exists())

    def test_effective_config_validation_and_selected_source_failure_never_fallback(self):
        self.profile()
        with patch.object(conf, 'LOCAL_BROWSER', 'typo', create=True):
            self.assertEqual(self.run_cli('check', '--account', 'creator')[0], 2)
            self.assertEqual(self.run_cli('check', '--account', 'creator', '--local-browser', 'chrome')[0], 0)
        with patch.object(conf, 'LOCAL_CHROME_HEADLESS', 'false'):
            self.assertEqual(self.run_cli('check', '--account', 'creator')[0], 2)
            self.assertEqual(self.run_cli('check', '--account', 'creator', '--headed')[0], 0)
        self.pw.chromium.launch_error = OSError('browser executable missing')
        count = len(self.pw.chromium.persistent_calls)
        code, _, err = self.run_cli('check', '--account', 'creator')
        self.assertEqual(code, 1)
        self.assertIn('channel=chrome', err)
        self.assertEqual(len(self.pw.chromium.persistent_calls), count + 1)
        self.assertFalse(self.pw.chromium.launch_calls)

    def test_managed_ignores_all_local_selection_and_keeps_configured_headless(self):
        from tests.fakes import FakeManagedProvider, FakeBrowser
        for mode in ['multilogin', 'adspower']:
            provider = FakeManagedProvider(mode=mode)
            self.pw.chromium.queue_connect_browser(FakeBrowser([ProbeContext()]))
            with patch.object(tiktok, 'resolve_managed_provider', return_value=provider), patch.object(conf, 'LOCAL_BROWSER', [], create=True), patch.object(conf, 'LOCAL_CHROME_PATH', []):
                code, _, err = self.run_cli('check', '--account', 'creator', '--local-browser', 'ignored')
            self.assertEqual(code, 0, err)
            self.assertEqual(provider.start_calls, [True])
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.assertFalse((self.root / 'browser_profiles').exists())

    def test_real_note_flow_reaches_no_publish_stop_in_one_locked_session(self):
        from tests.test_tiktok_note_cli import _StudioPage
        page = _StudioPage()
        self.context.pages = [page]
        image = self.root / 'image.png'
        image.write_bytes(b'image fixture')
        self.profile()
        with patch.dict(os.environ, {'HUMANIZE': '0'}):
            code, out, err = self.run_cli('upload-note', '--account', 'creator', '--images', str(image), '--title', 'A title', '--note', 'A description', '--no-publish', '--headed')
        self.assertEqual(code, 0, err)
        self.assertIn('素材已上传，发布前检查已通过；已停止，未点击发布按钮。', out)
        self.assertNotIn('prepared (not published)', out)
        self.assertNotIn('upload submitted:', out)
        self.assertEqual(len(self.pw.chromium.persistent_calls), 1)
        self.assertEqual(page.input_files, [str(image)])
        self.assertEqual(page.title_text, 'A title')
        self.assertEqual(page.caption_text, 'A description')
        self.assertFalse(page.publish_clicked)
        self.assertTrue(self.context.closed)

    def test_real_video_flow_reaches_no_publish_stop(self):
        page = self.video_page()
        self.context.pages = [page]
        video = self.root / 'video.mp4'; video.write_bytes(b'video fixture')
        self.profile()
        with patch.dict(os.environ, {'HUMANIZE': '0'}):
            code, out, err = self.run_cli('upload-video', '--account', 'creator', '--file', str(video), '--title', 'Video caption', '--no-publish')
        self.assertEqual(code, 0, err)
        self.assertIn('素材已上传，发布前检查已通过；已停止，未点击发布按钮。', out)
        self.assertNotIn('prepared (not published)', out)
        self.assertNotIn('upload submitted:', out)
        self.assertEqual(page.input_files, [str(video)])
        self.assertEqual(page.caption_text, 'Video caption')
        self.assertEqual(page.publish_clicks, 0)
        self.assertEqual(len(self.pw.chromium.persistent_calls), 1)
        self.assertTrue(self.context.closed)

    def test_no_publish_failures_never_print_success_or_submit(self):
        from tests.fakes import FakeManagedProvider, FakeBrowser
        from tests.fakes_clock import FakeClock
        from tests.test_tiktok_note_cli import _StudioPage, _Locator
        from uploader.tk_uploader import main_chrome as tk_main
        import uploader.publish_timeout as timeout
        self.profile()
        media = self.root / 'media.mp4'; media.write_bytes(b'fixture')
        image = self.root / 'image.png'; image.write_bytes(b'fixture')
        is_enabled = _Locator.is_enabled
        for action, flags in [('upload-video', ['--file', str(media)]), ('upload-note', ['--images', str(image)])]:
            for state, managed, expected in [('unready', False, 1), ('login', False, 10), ('login', True, 10)]:
                with self.subTest(action=action, state=state, managed=managed):
                    page = _StudioPage() if action == 'upload-note' else self.video_page()
                    page.readiness_reads = 0
                    async def becomes_disabled(locator):
                        if locator.selector in ('[data-e2e="post_video_button"]', 'role=button[name=/^Post$/]'):
                            page.readiness_reads += 1
                            return page.readiness_reads == 1
                        return await is_enabled(locator)
                    self.context.pages = [page]
                    self.context.state = 'login' if state == 'login' else 'valid'
                    provider = FakeManagedProvider() if managed else None
                    if managed:
                        self.pw.chromium.queue_connect_browser(FakeBrowser([self.context]))
                    with patch.object(tiktok, 'resolve_managed_provider', return_value=provider), patch.object(_Locator, 'is_enabled', becomes_disabled), patch.dict(os.environ, {'HUMANIZE': '0'}), FakeClock().patch(tk_main, timeout):
                        code, out, err = self.run_cli(action, '--account', 'creator', '--title', 'Title', '--no-publish', *flags)
                    self.assertEqual(code, expected, err)
                    self.assertEqual(out, '')
                    self.assertNotIn('publish_attempted=true', err)
                    self.assertFalse(page.publish_clicked)
                    self.assertEqual(getattr(page, 'publish_clicks', 0), 0)
                    if state == 'unready':
                        self.assertIn('发布就绪超时', err)
                        self.assertGreater(page.readiness_reads, 1)
                    if managed:
                        self.assertEqual(provider.stop_calls, 1)

    def video_page(self, outcome='success'):
        from tests.test_tiktok_note_cli import _StudioPage, _Locator
        from uploader.tk_uploader.main_chrome import TIKTOK_LOGIN_FORM_SELECTOR
        class Locator(_Locator):
            def _spawn(inner, *, count=None):
                return Locator(inner.page, inner.selector, count=inner._count if count is None else count)
            async def inner_text(inner):
                if '/video/' in inner.selector: return 'Video caption'
                return await super(Locator, inner).inner_text()
            async def get_attribute(inner, name):
                if '/video/' in inner.selector and name == 'href': return 'https://www.tiktok.com/@creator/video/1234567890'
                return await super(Locator, inner).get_attribute(name)
            async def click(inner, **kwargs):
                await super(Locator, inner).click(**kwargs)
                if inner.selector == '[data-e2e="post_video_button"]':
                    inner.page.publish_clicks += 1
                    if outcome == 'login': inner.page.url = 'https://www.tiktok.com/login'
                    if outcome == 'verification': inner.page.url = 'https://www.tiktok.com/captcha'
        class Studio(_StudioPage):
            publish_clicks = 0
            def locator(inner, selector):
                result = super(Studio, inner).locator(selector)
                count = 1 if '/video/' in selector else result._count
                if selector == TIKTOK_LOGIN_FORM_SELECTOR and outcome == 'modal': count = 1
                return Locator(inner, selector, count=count)
            def expect_file_chooser(inner):
                class Chooser:
                    async def set_files(chooser, file): inner.input_files = [file]
                class Manager:
                    @property
                    def value(manager):
                        async def result(): return Chooser()
                        return result()
                    async def __aenter__(manager): return manager
                    async def __aexit__(manager, *args): return False
                return Manager()
            async def wait_for_url(inner, url, **kwargs):
                if inner.publish_clicks and outcome == 'unknown': raise OSError('connection lost')
                return await super(Studio, inner).wait_for_url(url, **kwargs)
        return Studio()

    def test_publish_outcome_survives_close_failure_and_never_resubmits(self):
        self.profile()
        video = self.root / 'video.mp4'; video.write_bytes(b'video fixture')
        self.context.close_error = OSError('cleanup failed')
        for outcome, expected in [('success', 0), ('unknown', 9), ('login', 10), ('verification', 10), ('modal', 10)]:
            with self.subTest(outcome=outcome):
                page = self.video_page(outcome)
                self.context.pages = [page]
                with patch.dict(os.environ, {'HUMANIZE': '0'}):
                    code, out, err = self.run_cli('upload-video', '--account', 'creator', '--file', str(video), '--title', 'Video caption')
                if expected == 0:
                    self.assertEqual(out, f'TikTok video upload submitted: {video}\n')
                self.assertEqual(code, expected, err)
                self.assertEqual(page.publish_clicks, 0 if outcome == 'modal' else 1)
                if outcome in ('login','verification'): self.assertIn('publish_attempted=true', err)


    def test_managed_upload_preserves_existing_probe_url_and_ignored_locale_log(self):
        from loguru import logger
        from tests.fakes import FakeManagedProvider, FakeBrowser
        from tests.test_tiktok_note_cli import _StudioPage
        image = self.root / 'image.png'; image.write_bytes(b'image fixture')
        video = self.root / 'video.mp4'; video.write_bytes(b'video fixture')
        for action, flags, mode in [
            ('upload-note', ['--images', str(image)], 'multilogin'),
            ('upload-video', ['--file', str(video)], 'adspower'),
        ]:
            with self.subTest(action=action, mode=mode):
                provider = FakeManagedProvider(mode=mode)
                context = ProbeContext()
                page = _StudioPage() if action == 'upload-note' else self.video_page()
                context.pages = [page]
                browser = FakeBrowser([context])
                self.pw.chromium.queue_connect_browser(browser)
                logs = io.StringIO()
                sink = logger.add(logs, format='{message}')
                try:
                    with patch.object(tiktok, 'resolve_managed_provider', return_value=provider), patch.object(conf, 'LOCAL_CHROME_PATH', []), patch.dict(os.environ, {'HUMANIZE':'0'}):
                        code, out, err = self.run_cli(action, '--account', 'creator', '--title', 'Video caption', '--no-publish', '--local-browser', 'ignored', *flags)
                finally:
                    logger.remove(sink)
                self.assertEqual(code, 0, err)
                self.assertIn('素材已上传，发布前检查已通过；已停止，未点击发布按钮。', out)
                self.assertNotIn('upload submitted:', out)
                self.assertFalse(page.publish_clicked)
                self.assertEqual(getattr(page, 'publish_clicks', 0), 0)
                self.assertEqual(context.created_pages[0].url, 'https://www.tiktok.com/tiktokstudio/upload?lang=en')
                self.assertIn('ignored=context_kwargs', logs.getvalue())
                self.assertNotIn('launch_kwargs', logs.getvalue())
                self.assertEqual(provider.start_calls, [True])
                self.assertEqual(provider.stop_calls, 1)
                self.assertFalse(context.closed)
                self.assertEqual(browser.close_calls, 1)
        self.assertFalse(self.pw.chromium.persistent_calls)
        self.assertFalse((self.root / 'browser_profiles').exists())
