import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


@unittest.skipUnless(os.name == "nt", "requires Windows filesystem security")
class WindowsProfileSecurityTests(unittest.TestCase):
    def test_private_directory_protects_records_under_a_readable_parent(self):
        import win32security
        from utils.windows_profile_security import check_private, private_mkdir

        with tempfile.TemporaryDirectory() as temp:
            subprocess.run(
                ["icacls", temp, "/grant", "*S-1-1-0:(OI)(CI)R"],
                capture_output=True, check=True,
            )
            path = Path(temp, "managed")
            private_mkdir(path)
            private_mkdir(path)
            record = path / "record"
            record.write_bytes(b"new")
            for item in (path, record):
                check_private(item)
                descriptor = win32security.GetNamedSecurityInfo(
                    str(item), win32security.SE_FILE_OBJECT,
                    win32security.DACL_SECURITY_INFORMATION,
                )
                acl = descriptor.GetSecurityDescriptorDacl()
                self.assertIsNotNone(acl)
                self.assertGreater(acl.GetAceCount(), 0)
                for index in range(acl.GetAceCount()):
                    trustee = win32security.ConvertSidToStringSid(acl.GetAce(index)[-1])
                    self.assertNotEqual(trustee, "S-1-1-0")

    def test_existing_directory_and_records_reject_public_or_null_dacls(self):
        import win32security
        from utils.windows_profile_security import check_private, private_mkdir

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp, "private")
            private_mkdir(path)
            record = path / "record"
            record.touch()
            win32security.SetNamedSecurityInfo(
                str(record), win32security.SE_FILE_OBJECT,
                win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
                None, None, None, None,
            )
            with self.assertRaises(PermissionError):
                check_private(record)
            subprocess.run(
                ["icacls", str(path), "/grant", "*S-1-1-0:R"],
                capture_output=True, check=True,
            )
            with self.assertRaises(PermissionError):
                private_mkdir(path)

    def test_reparse_point_is_refused_even_when_target_is_private(self):
        from utils.windows_profile_security import check_private, private_mkdir

        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp, "target")
            private_mkdir(target)
            link = Path(temp, "link")
            subprocess.run(
                ["cmd", "/d", "/c", "mklink", "/J", "link", "target"], cwd=temp,
                capture_output=True, check=True,
            )
            with self.assertRaises(PermissionError):
                check_private(link)

    def test_processes_contend_on_empty_file_and_release_after_exit(self):
        from utils.windows_profile_security import try_lock

        probe = """
import os, sys
from utils.windows_profile_security import try_lock
fd = os.open(sys.argv[1], os.O_RDWR)
os._exit(0 if try_lock(fd) else 7)
"""
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp, "platform.lock")
            command = [sys.executable, "-c", probe, str(path)]
            with path.open("w+b") as owner:
                self.assertTrue(try_lock(owner.fileno()))
                self.assertEqual(subprocess.run(command, timeout=10).returncode, 7)
            # The kernel can finish releasing byte-range locks after a handle closes.
            deadline = time.monotonic() + 10
            while True:
                result = subprocess.run(command, timeout=10).returncode
                if result == 0:
                    break
                self.assertEqual(result, 7)
                self.assertLess(time.monotonic(), deadline)
            with path.open("r+b") as successor:
                deadline = time.monotonic() + 10
                while not try_lock(successor.fileno()):
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.01)

    def test_unusable_handle_reports_an_error(self):
        from utils.windows_profile_security import try_lock

        reader, writer = os.pipe()
        try:
            with self.assertRaises(OSError):
                try_lock(writer)
        finally:
            os.close(reader)
            os.close(writer)
