"""Filesystem boundaries for sharing a profile between independent installations."""
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from utils.profile_store import ProfileStore


@unittest.skipIf(os.name == "nt", "POSIX permissions and signals")
class PrivateProfileStoreTests(unittest.TestCase):
    def test_two_processes_contend_until_holder_is_killed(self):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, HOME=home):
            child = subprocess.Popen(
                [sys.executable, "-c",
                 "from utils.profile_store import ProfileStore\n"
                 "import signal\n"
                 "lock = ProfileStore('adspower', 'testing').try_lock('platform-instagram')\n"
                 "assert lock is not None\n"
                 "print('reserved', flush=True)\n"
                 "signal.pause()"],
                stdout=subprocess.PIPE, text=True,
            )
            with child:
                try:
                    self.assertEqual(child.stdout.readline().strip(), "reserved")
                    store = ProfileStore("adspower", "testing")
                    self.assertIsNone(store.try_lock("platform-instagram"))
                    separate = ProfileStore("adspower", "other").try_lock("platform-instagram")
                    self.assertIsNotNone(separate)
                    separate.close()
                finally:
                    child.kill()
                self.assertEqual(child.wait(timeout=10), -signal.SIGKILL)
            recovered = store.try_lock("platform-instagram")
            self.assertIsNotNone(recovered)
            recovered.close()

    def test_reopening_private_record_rejects_unsafe_permissions_and_links(self):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, HOME=home):
            store = ProfileStore("adspower", "../untrusted/id")
            self.assertIsNone(store.read_record())
            store.write_record({"phase":"active"})
            self.assertEqual(store.read_record(), {"phase":"active"})
            record, = (path for path in Path(home).rglob("*") if path.is_file())
            self.assertEqual(stat.S_IMODE(record.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(record.parent.stat().st_mode), 0o700)
            record.chmod(0o644)
            with self.assertRaises((OSError, ValueError, RuntimeError)):
                store.read_record()
            record.chmod(0o600)
            original = record.with_suffix(".original")
            record.rename(original)
            record.symlink_to(original)
            with self.assertRaises((OSError, ValueError, RuntimeError)):
                store.read_record()
