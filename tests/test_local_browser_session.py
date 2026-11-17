"""Persistent local session public seam: real configuration and Profile ownership."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import conf
from tests.fakes import FakePlaywright
from utils.local_browser_session import local_browser_session


class LocalBrowserSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_uses_default_chrome_native_context_and_reuses_profile(self):
        playwright = FakePlaywright()
        with tempfile.TemporaryDirectory() as root, patch.object(conf, 'LOCAL_CHROME_PATH', ''), patch.object(conf, 'LOCAL_CHROME_HEADLESS', False):
            async with local_browser_session(playwright, platform='tiktok', account='Creator', create=True, profile_root=root) as session:
                self.assertFalse(session.managed)
                self.assertEqual(session.mode, 'local')
                self.assertFalse(session.context.storage_state_calls)
            self.assertTrue(session.context.closed)
            self.assertEqual(session.browser.close_calls, 0)
            async with local_browser_session(playwright, platform='tiktok', account='Creator', headless=True, profile_root=root):
                pass
            calls = playwright.chromium.persistent_calls
            self.assertEqual(calls[0], {'user_data_dir': str(Path(root).resolve() / 'tiktok' / 'Creator' / 'chrome'), 'channel': 'chrome', 'headless': False, 'no_viewport': True})
            self.assertEqual(calls[1]['user_data_dir'], calls[0]['user_data_dir'])
            self.assertTrue(calls[1]['headless'])

    async def test_explicit_configuration_wins_and_chromium_never_uses_shell(self):
        playwright = FakePlaywright()
        with tempfile.TemporaryDirectory() as root, patch.object(conf, 'LOCAL_CHROME_PATH', ''), patch.object(conf, 'LOCAL_BROWSER', 'bad-unused', create=True), patch.object(conf, 'LOCAL_CHROME_HEADLESS', 'bad-unused'):
            async with local_browser_session(playwright, platform='tiktok', account='creator', create=True, profile_root=root, headless=False, local_browser='chromium'):
                pass
        self.assertEqual(playwright.chromium.persistent_calls[0]['channel'], 'chromium')
        self.assertFalse(playwright.chromium.persistent_calls[0]['headless'])

    async def test_custom_product_identity_overrides_invalid_unused_browser_selection(self):
        import plistlib
        playwright = FakePlaywright()
        with tempfile.TemporaryDirectory() as root:
            executable = Path(root) / 'Renamed.app/Contents/MacOS/unhelpful-name'
            executable.parent.mkdir(parents=True)
            executable.write_text('binary fixture')
            executable.chmod(0o755)
            (executable.parent.parent / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'org.chromium.Chromium', 'CFBundleName': 'Chromium', 'CFBundleExecutable': 'unhelpful-name', 'CFBundleShortVersionString': '123.1'}))
            with patch.object(conf, 'LOCAL_CHROME_PATH', str(executable)), patch.object(conf, 'LOCAL_BROWSER', 'unused', create=True), patch('utils.local_browser.sys.platform', 'darwin'):
                async with local_browser_session(playwright, platform='tiktok', account='creator', create=True, profile_root=Path(root) / 'profiles', local_browser='unused', headless=False):
                    pass
            call = playwright.chromium.persistent_calls[0]
            self.assertEqual(call['executable_path'], str(executable.resolve()))
            self.assertNotIn('channel', call)
            self.assertTrue(call['user_data_dir'].endswith('/chromium'))

    async def test_cleanup_failure_preserves_success_and_primary_error_then_releases_lease(self):
        from tests.fakes import FakeContext
        from utils.local_profile import acquire_local_profile
        playwright = FakePlaywright()
        context = FakeContext()
        context.close_error = OSError('close failed')
        playwright.chromium.persistent_context = context
        with tempfile.TemporaryDirectory() as root, patch.object(conf, 'LOCAL_CHROME_PATH', ''):
            async with local_browser_session(playwright, platform='tiktok', account='creator', create=True, profile_root=root):
                pass
            with self.assertRaisesRegex(ValueError, 'primary'):
                async with local_browser_session(playwright, platform='tiktok', account='creator', profile_root=root):
                    raise ValueError('primary')
            with acquire_local_profile('tiktok', 'creator', 'chrome', root=root):
                pass

    async def test_setup_failure_closes_context_and_missing_profile_does_not_launch(self):
        from utils.errors import LoginRequiredError
        playwright = FakePlaywright()
        async def setup(context):
            raise ValueError('setup failed')
        with tempfile.TemporaryDirectory() as root, patch.object(conf, 'LOCAL_CHROME_PATH', ''):
            with self.assertRaises(LoginRequiredError):
                async with local_browser_session(playwright, platform='tiktok', account='missing', profile_root=root):
                    self.fail('missing Profile must require login')
            self.assertFalse(playwright.chromium.persistent_calls)
            with self.assertRaisesRegex(ValueError, 'setup failed'):
                async with local_browser_session(playwright, platform='tiktok', account='creator', create=True, profile_root=root, context_setup=setup):
                    pass
            self.assertIn('context.close', playwright.events)

    async def test_lease_is_held_through_setup_body_and_close_and_cancel_propagates(self):
        import asyncio
        from tests.fakes import FakeContext
        from utils.local_profile import acquire_local_profile
        playwright = FakePlaywright()
        with tempfile.TemporaryDirectory() as root, patch.object(conf, 'LOCAL_CHROME_PATH', ''):
            def assert_occupied():
                with self.assertRaisesRegex(RuntimeError, '占用'):
                    with acquire_local_profile('tiktok', 'creator', 'chrome', root=root): pass
            class Context(FakeContext):
                async def close(inner):
                    assert_occupied()
                    await super(Context, inner).close()
            context = Context()
            playwright.chromium.persistent_context = context
            async def setup(_context): assert_occupied()
            with self.assertRaises(asyncio.CancelledError):
                async with local_browser_session(playwright, platform='tiktok', account='creator', create=True, profile_root=root, context_setup=setup):
                    assert_occupied()
                    raise asyncio.CancelledError()
            self.assertTrue(context.closed)
            with acquire_local_profile('tiktok', 'creator', 'chrome', root=root): pass

    async def test_hung_cleanup_is_bounded_and_cancellation_during_cleanup_is_preserved(self):
        import asyncio
        from tests.fakes import FakeContext
        from utils.local_profile import acquire_local_profile
        playwright = FakePlaywright()
        closing = asyncio.Event()
        class Context(FakeContext):
            async def close(inner):
                closing.set()
                await asyncio.Event().wait()
        playwright.chromium.persistent_context = Context()
        with tempfile.TemporaryDirectory() as root, patch.object(conf, 'LOCAL_CHROME_PATH', ''), patch('utils.local_browser_session.CLOSE_TIMEOUT_SECONDS', 0.02):
            async def operation():
                async with local_browser_session(playwright, platform='tiktok', account='creator', create=True, profile_root=root): pass
            task = asyncio.create_task(operation())
            await closing.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await asyncio.wait_for(task, timeout=1)
            with acquire_local_profile('tiktok', 'creator', 'chrome', root=root): pass

    async def test_unknown_or_conflicting_custom_product_fails_before_profile_creation(self):
        import plistlib
        playwright = FakePlaywright()
        with tempfile.TemporaryDirectory() as root:
            executable = Path(root) / 'chrome.app/Contents/MacOS/Google Chrome'
            executable.parent.mkdir(parents=True)
            executable.write_text('fixture'); executable.chmod(0o755)
            for product, identifier in [('Unknown browser', 'unknown'), ('Google Chrome', 'org.chromium.Chromium')]:
                (executable.parent.parent / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleName':product,'CFBundleExecutable':executable.name,'CFBundleIdentifier':identifier}))
                with patch.object(conf, 'LOCAL_CHROME_PATH', str(executable)), patch('utils.local_browser.sys.platform', 'darwin'):
                    with self.assertRaises(RuntimeError):
                        async with local_browser_session(playwright, platform='tiktok', account='creator', create=True, profile_root=Path(root)/'profiles'): pass
                self.assertFalse((Path(root)/'profiles').exists())
            self.assertFalse(playwright.chromium.persistent_calls)

    async def test_absent_config_defaults_to_headed_chrome(self):
        playwright = FakePlaywright()
        with tempfile.TemporaryDirectory() as root, patch.dict(conf.__dict__):
            for name in ('LOCAL_CHROME_HEADLESS', 'LOCAL_BROWSER', 'LOCAL_CHROME_PATH'):
                conf.__dict__.pop(name, None)
            async with local_browser_session(playwright, platform='tiktok', account='creator', create=True, profile_root=root): pass
        self.assertFalse(playwright.chromium.persistent_calls[0]['headless'])
        self.assertEqual(playwright.chromium.persistent_calls[0]['channel'], 'chrome')
