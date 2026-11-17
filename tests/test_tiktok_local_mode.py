"""Direct-call compatibility uses aliases/Profile state, never old JSON."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import conf
from tests.fakes import FakePlaywright
from tests.test_mlx_tiktok import _AsyncCM
from tests.test_tiktok_profile_cli import ProbeContext, terminal_enter
from uploader.tk_uploader import main_chrome as tk_main
from utils.errors import LoginRequiredError
from utils.local_profile import acquire_local_profile


class LocalProfileHelpersTests(unittest.TestCase):
    def test_old_positional_filename_only_names_profile_and_never_reads_file(self):
        pw = FakePlaywright()
        context = ProbeContext()
        pw.chromium.persistent_context = context
        with tempfile.TemporaryDirectory() as root, patch.object(conf, 'BASE_DIR', Path(root)), patch.object(conf, 'LOCAL_CHROME_PATH', ''), patch.object(tk_main, 'async_playwright', lambda: _AsyncCM(pw)):
            with acquire_local_profile('tiktok', 'creator', 'chrome', create=True): pass
            self.assertTrue(asyncio.run(tk_main.cookie_auth('/does-not-exist/tiktok_creator.json', headless=False)))
            self.assertEqual(len(pw.chromium.persistent_calls), 1)
            self.assertTrue(pw.chromium.persistent_calls[0]['user_data_dir'].endswith('/tiktok/creator/chrome'))
            self.assertFalse(context.storage_state_calls)
            self.assertFalse((Path(root) / 'cookies').exists())

    def test_direct_setup_guides_login_once_in_selected_context(self):
        pw = FakePlaywright()
        context = ProbeContext()
        pw.chromium.persistent_context = context
        with tempfile.TemporaryDirectory() as root, patch.object(conf, 'BASE_DIR', Path(root)), patch.object(conf, 'LOCAL_CHROME_PATH', ''), patch.object(tk_main, 'async_playwright', lambda: _AsyncCM(pw)), terminal_enter():
            self.assertTrue(asyncio.run(tk_main.tiktok_setup(account_name='creator', handle=True, headless=True, local_browser='chromium')))
            self.assertEqual(len(pw.chromium.persistent_calls), 1)
            self.assertEqual(pw.chromium.persistent_calls[0]['channel'], 'chromium')
            self.assertTrue(pw.chromium.persistent_calls[0]['headless'])
            self.assertTrue(context.closed)

    def test_direct_driver_failure_propagates_as_fault(self):
        class BrokenDriver:
            async def __aenter__(self): raise OSError('driver missing')
            async def __aexit__(self, *args): pass
        with patch.object(tk_main, 'async_playwright', BrokenDriver):
            with self.assertRaisesRegex(OSError, 'driver missing'):
                asyncio.run(tk_main.cookie_auth(account_name='creator'))
