import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import conf
from utils.local_profile import acquire_local_profile
from migration import migrate

class Context:
    def __init__(self, backend): self.backend = backend; self.browser = SimpleNamespace(version='fixture')
    async def close(self): self.backend.events.append('close')

class Backend:
    def __init__(self): self.events = []; self.calls = []; self.chromium = self
    async def launch_persistent_context(self, **kwargs):
        self.calls.append(kwargs); self.events.append('launch'); return Context(self)
    async def login(self, session): self.events.append('login'); return True
    async def probe(self, session): self.events.append('probe'); return True

class MigrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); (self.root/'cookies').mkdir()
        self.pw = Backend()
    async def run_migration(self, platform='tiktok', account='creator', **kwargs):
        with patch.object(conf, 'LOCAL_CHROME_PATH', ''), patch.object(conf, 'LOCAL_BROWSER', 'chrome', create=True):
            return await migrate(self.pw, platform=platform, account=account, base=self.root,
                                 login=self.pw.login, probe=self.pw.probe, **kwargs)
    async def test_two_positive_stages_and_strict_closes_delete_only_selected_file(self):
        target = self.root/'cookies/tiktok_creator.json'; target.write_bytes(b'broken legacy')
        other = self.root/'cookies/tiktok_other.json'; other.write_bytes(b'untouched')
        await self.run_migration()
        self.assertFalse(target.exists()); self.assertEqual(other.read_bytes(), b'untouched')
        self.assertEqual(self.pw.events, ['launch','login','close','launch','probe','close'])
        self.assertEqual(self.pw.calls[0], self.pw.calls[1])
        self.assertEqual(self.pw.calls[0]['headless'], False)
        self.assertTrue((self.root/'browser_profiles/tiktok/creator/chrome').is_dir())
    async def test_missing_corrupt_other_identity_and_sidecar_only_never_import_state(self):
        for contents in (None, b'not json', b'{"user_id":"unrelated"}'):
            with self.subTest(contents=contents):
                target = self.root/'cookies/tiktok_creator.json'
                if contents is not None: target.write_bytes(contents)
                await self.run_migration()
                self.assertFalse(target.exists())
        sidecar = self.root/'cookies/dayu_creator.identity.json'; sidecar.write_bytes(b'old binding')
        await self.run_migration(platform='dayu')
        self.assertFalse(sidecar.exists())
    async def test_unsafe_or_ambiguous_targets_fail_before_browser_launch(self):
        outside = self.root/'outside.json'; outside.write_bytes(b'preserve')
        target = self.root/'cookies/tiktok_creator.json'; target.symlink_to(outside)
        with self.assertRaises(RuntimeError): await self.run_migration()
        self.assertEqual(self.pw.events, []); self.assertEqual(outside.read_bytes(), b'preserve')
        target.unlink(); target.mkdir()
        with self.assertRaises(RuntimeError): await self.run_migration()
        self.assertEqual(self.pw.events, [])
        target.rmdir(); (self.root/'cookies/tiktok_Creator.json').write_bytes(b'ambiguous')
        with self.assertRaises(RuntimeError): await self.run_migration()
        self.assertEqual(self.pw.events, [])
    async def test_traversal_alias_cannot_target_file(self):
        with self.assertRaises(Exception): await self.run_migration(account='../escape')
        self.assertEqual(self.pw.events, [])
    async def test_negative_login_or_reopen_preserves_target_and_profile(self):
        target = self.root/'cookies/tiktok_creator.json'
        for failing in ('login', 'probe'):
            target.write_bytes(b'preserve')
            old = getattr(self.pw, failing)
            async def negative(session): return False
            setattr(self.pw, failing, negative)
            with self.assertRaises(RuntimeError): await self.run_migration()
            self.assertEqual(target.read_bytes(), b'preserve')
            self.assertTrue((self.root/'browser_profiles/tiktok/creator/chrome').is_dir())
            setattr(self.pw, failing, old)
    async def test_close_failure_on_either_stage_vetoes_delete(self):
        target = self.root/'cookies/tiktok_creator.json'
        for fail_at in (1, 2):
            target.write_bytes(b'preserve'); closes = 0
            async def close(context):
                nonlocal closes
                closes += 1
                if closes == fail_at: raise OSError('close failed')
            with patch.object(Context, 'close', close):
                with self.assertRaises(OSError): await self.run_migration()
            self.assertTrue(target.exists())
    async def test_cancellation_during_login_and_close_preserves_files(self):
        target = self.root/'cookies/tiktok_creator.json'; target.write_bytes(b'preserve')
        async def cancel(session): raise asyncio.CancelledError()
        self.pw.login = cancel
        with self.assertRaises(asyncio.CancelledError): await self.run_migration()
        self.assertTrue(target.exists())
        self.pw.login = Backend.login.__get__(self.pw)
        with patch.object(Context, 'close', cancel):
            with self.assertRaises(asyncio.CancelledError): await self.run_migration()
        self.assertTrue(target.exists())
    async def test_close_timeout_is_bounded_even_when_browser_swallows_cancellation(self):
        target = self.root/'cookies/tiktok_creator.json'; target.write_bytes(b'preserve')
        release = asyncio.Event()
        async def hanging_close(context):
            try: await release.wait()
            except asyncio.CancelledError: await release.wait()
        with patch.object(Context, 'close', hanging_close):
            task = asyncio.create_task(self.run_migration(close_timeout=0.01))
            try:
                done, _ = await asyncio.wait({task}, timeout=.15)
                self.assertIn(task, done)
                with self.assertRaises(TimeoutError): task.result()
                self.assertTrue(target.exists())
            finally:
                release.set()
                if not task.done():
                    try: await task
                    except BaseException: pass
    async def test_lease_covers_both_launches_probes_and_closes(self):
        def assert_busy():
            with self.assertRaises(Exception):
                with acquire_local_profile('tiktok', 'creator', 'chrome', root=self.root/'browser_profiles'): pass
        launch = self.pw.launch_persistent_context
        async def checked_launch(**kwargs): assert_busy(); return await launch(**kwargs)
        async def checked_probe(session): assert_busy(); return True
        async def checked_close(context): assert_busy()
        self.pw.launch_persistent_context = checked_launch
        self.pw.login = self.pw.probe = checked_probe
        with patch.object(Context, 'close', checked_close): await self.run_migration()
    async def test_partial_delete_reports_remaining_and_retry_converges(self):
        cookie = self.root/'cookies/dayu_creator.json'; cookie.write_bytes(b'cookie')
        sidecar = cookie.with_suffix('.identity.json'); sidecar.write_bytes(b'identity')
        unlink = Path.unlink
        def fail_sidecar(path, *args, **kwargs):
            if path == sidecar: raise PermissionError('denied')
            return unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', fail_sidecar):
            with self.assertRaisesRegex(RuntimeError, str(sidecar)):
                await self.run_migration(platform='dayu')
        self.assertFalse(cookie.exists()); self.assertTrue(sidecar.exists())
        await self.run_migration(platform='dayu')
        self.assertFalse(sidecar.exists())
        await self.run_migration(platform='dayu')
    async def test_platform_proxy_configuration_is_identical_on_reopen(self):
        await self.run_migration(platform='instagram', context_kwargs={'proxy': {'server': 'http://localhost:7890'}})
        self.assertEqual(self.pw.calls[0]['proxy'], {'server': 'http://localhost:7890'})
        self.assertEqual(self.pw.calls[0], self.pw.calls[1])
