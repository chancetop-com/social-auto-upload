"""Profile ownership and reset through the public CLI/resource boundaries."""
from __future__ import annotations

import io
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import time
import unicodedata
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import conf
import sau_cli


PROFILE_PROCESS = """
import sys
from utils.local_profile import acquire_local_profile
try:
    with acquire_local_profile('tiktok', sys.argv[2], sys.argv[3], root=sys.argv[1], create=True) as profile:
        print('acquired', flush=True)
        if sys.argv[4] == 'hold':
            sys.stdin.readline()
except Exception as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(1)
"""


class LocalProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "browser_profiles"
        self.config = patch.object(conf, "BASE_DIR", self.base)
        self.config.start()
        self.addCleanup(self.config.stop)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_reset(self, platform="tiktok", account="Creator 名", kind="chrome", extra=()):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            try:
                code = sau_cli.main([platform, "reset-profile", "--account", account,
                                     "--browser-kind", kind, *extra])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_missing_profile_reset_needs_no_browser_and_does_not_create_profile(self):
        with patch.object(conf, "LOCAL_CHROME_PATH", "/missing/browser"), \
             patch.object(conf, "LOCAL_BROWSER", "invalid-unused-value", create=True):
            code, out, err = self.run_reset()
        self.assertEqual((code, err), (0, ""))
        self.assertIn(str(self.root / "tiktok" / "Creator 名" / "chrome"), out)
        self.assertIn("login", out)
        self.assertFalse((self.root / "tiktok" / "Creator 名" / "chrome").exists())

    def test_reset_removes_only_selected_browser_and_preserves_readable_alias(self):
        from utils.local_profile import acquire_local_profile
        account = "  Creator 名  "
        for platform, label, kind in (("tiktok", account, "chrome"),
                                      ("tiktok", account, "chromium"),
                                      ("tiktok", "Other", "chrome"),
                                      ("rednote", account, "chrome")):
            with acquire_local_profile(platform, label, kind, create=True) as profile:
                self.assertEqual(profile.path, self.root / platform / label / kind)
                (profile.path / "session-data").write_text("browser state")
        legacy = self.base / "cookies" / "tiktok_old.json"
        legacy.parent.mkdir()
        legacy.write_text("legacy")
        result = self.base / "result.json"
        result.write_text("historical work")
        code, out, err = self.run_reset(account=account)
        self.assertEqual((code, err), (0, ""))
        self.assertFalse((self.root / "tiktok" / account / "chrome").exists())
        for platform, label, kind in (("tiktok", account, "chromium"),
                                      ("tiktok", "Other", "chrome"),
                                      ("rednote", account, "chrome")):
            with acquire_local_profile(platform, label, kind) as profile:
                self.assertTrue(profile.exists)
                self.assertEqual((profile.path / "session-data").read_text(), "browser state")
        self.assertEqual(legacy.read_text(), "legacy")
        self.assertEqual(result.read_text(), "historical work")
        with acquire_local_profile("tiktok", account, "chrome") as profile:
            self.assertFalse(profile.exists)

    def test_reset_rejects_unsafe_aliases_and_unknown_kind_before_filesystem_work(self):
        for alias in ("", "  ", ".", "..", "../outside", "nested/name", "nested\\name", "bad\x00name"):
            with self.subTest(alias=alias):
                code, out, err = self.run_reset(account=alias)
                self.assertEqual(code, 2, err)
                self.assertFalse(self.root.exists())
        self.assertEqual(self.run_reset(kind="unknown")[0], 2)
        self.assertFalse(self.root.exists())

    def test_reset_refuses_unowned_directory_without_deleting_contents(self):
        target = self.root / "tiktok" / "Creator 名" / "chrome"
        target.mkdir(parents=True)
        (target / "untouched").write_text("unknown owner")
        code, out, err = self.run_reset()
        self.assertEqual(code, 1, err)
        self.assertIn("归属", err)
        self.assertEqual((target / "untouched").read_text(), "unknown owner")

    def test_profile_path_never_follows_symlinks_outside_dedicated_root(self):
        from utils.local_profile import acquire_local_profile
        with acquire_local_profile("tiktok", "Creator 名", "chrome", create=True) as profile:
            (profile.path / "state").write_text("preserve")
        for relative in ("", "tiktok", "tiktok/Creator 名", "tiktok/Creator 名/chrome"):
            target = self.root / relative
            outside = self.base / "outside"
            target.rename(outside)
            target.symlink_to(outside, target_is_directory=True)
            try:
                code, out, err = self.run_reset()
                self.assertEqual(code, 1, err)
                self.assertIn("路径", err)
                with self.assertRaises(RuntimeError):
                    with acquire_local_profile("tiktok", "Creator 名", "chrome"):
                        self.fail("symlink must not be followed")
            finally:
                target.unlink()
                outside.rename(target)
        self.assertEqual((profile.path / "state").read_text(), "preserve")

    def child_command(self, account="Creator 名", kind="chrome", mode="hold"):
        return [sys.executable, "-c", PROFILE_PROCESS, str(self.root), account, kind, mode]

    def start_holder(self, account="Creator 名", kind="chrome"):
        child = subprocess.Popen(self.child_command(account, kind), stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 cwd=Path(__file__).resolve().parents[1])
        def cleanup():
            if child.poll() is None:
                child.terminate()
            child.communicate(timeout=5)
        self.addCleanup(cleanup)
        self.assertEqual(child.stdout.readline().strip(), "acquired")
        return child

    def test_two_real_processes_cannot_use_or_reset_one_profile_until_release(self):
        first = self.start_holder()
        start = time.monotonic()
        second = subprocess.run(self.child_command(mode="once"), capture_output=True,
                                text=True, timeout=3, cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(second.returncode, 1, second.stdout)
        self.assertIn("占用", second.stderr)
        self.assertLess(time.monotonic() - start, 2)
        self.assertEqual(self.run_reset()[0], 1)
        first.communicate("release\n", timeout=5)
        self.assertEqual(first.returncode, 0)
        released = subprocess.run(self.child_command(mode="once"), capture_output=True,
                                  text=True, timeout=3, cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(released.returncode, 0, released.stderr)
        self.assertEqual(self.run_reset()[0], 0)

    def test_partial_reset_blocks_session_until_explicit_reset_finishes(self):
        from utils.local_profile import acquire_local_profile
        with acquire_local_profile("tiktok", "Creator 名", "chrome", create=True) as profile:
            (profile.path / "state").write_text("partially removed")
        def partial_delete(path):
            for child in Path(path).iterdir():
                child.unlink()
            raise PermissionError("synthetic filesystem denial")
        with patch("shutil.rmtree", side_effect=partial_delete):
            code, out, err = self.run_reset()
        self.assertEqual(code, 1)
        self.assertIn("未完成", err)
        for create in (False, True):
            with self.assertRaisesRegex(RuntimeError, "未完成"):
                with acquire_local_profile("tiktok", "Creator 名", "chrome", create=create):
                    self.fail("partial Profile cannot be reused")
        self.assertEqual(self.run_reset()[0], 0)
        self.assertFalse(profile.path.exists())
        with acquire_local_profile("tiktok", "Creator 名", "chrome", create=True) as rebuilt:
            self.assertTrue(rebuilt.exists)

    def test_external_browser_singleton_evidence_prevents_acquire_and_reset(self):
        from utils.local_profile import acquire_local_profile
        with acquire_local_profile("tiktok", "Creator 名", "chrome", create=True) as profile:
            (profile.path / "state").write_text("keep external browser data")
        singleton = profile.path / "SingletonLock"
        singleton.symlink_to(f"unknown-host-{os.getpid()}")
        code, out, err = self.run_reset()
        self.assertEqual(code, 1)
        self.assertIn("浏览器", err)
        self.assertTrue(singleton.is_symlink())
        self.assertEqual((profile.path / "state").read_text(), "keep external browser data")
        with self.assertRaisesRegex(RuntimeError, "浏览器"):
            with acquire_local_profile("tiktok", "Creator 名", "chrome"):
                self.fail("must not take over browser Profile")

    def test_public_acquisition_rejects_nonplatform_paths_before_creating_root(self):
        from utils.local_profile import acquire_local_profile
        from utils.errors import UsageError
        for platform in ("../outside", str(self.base / "outside"), "bilibili", "article", "unknown"):
            with self.subTest(platform=platform):
                with self.assertRaises(UsageError):
                    with acquire_local_profile(platform, "Creator", "chrome", create=True):
                        self.fail("not a formal browser platform")
                self.assertFalse(self.root.exists())

    def test_distinct_profiles_run_in_parallel_and_crashed_owner_leaves_no_live_lock(self):
        from utils.local_profile import acquire_local_profile
        first = self.start_holder()
        other_kind = self.start_holder(kind="chromium")
        other_alias = self.start_holder(account="Other")
        self.assertIsNone(first.poll())
        self.assertIsNone(other_kind.poll())
        self.assertIsNone(other_alias.poll())
        # Only our synthetic subprocess is killed; the OS must release ownership.
        first.kill()
        first.communicate(timeout=5)
        with acquire_local_profile("tiktok", "Creator 名", "chrome") as profile:
            self.assertTrue(profile.exists)
        # A diagnostic file remains, but it must not be interpreted as a live lock.
        self.assertTrue(list(profile.path.parent.glob("*.lock")))
        self.assertEqual(self.run_reset()[0], 0)
        self.assertIsNone(other_kind.poll())
        self.assertIsNone(other_alias.poll())

    def test_equivalent_filesystem_aliases_cannot_merge_ownership_or_bypass_active_owner(self):
        from utils.local_profile import acquire_local_profile
        for original, alternate in (("Creator", "creator"), ("Café", unicodedata.normalize("NFD", "Café"))):
            with self.subTest(original=original):
                first = self.start_holder(account=original)
                alias_dir = self.root / "tiktok" / alternate
                if alias_dir.exists():
                    code, out, err = self.run_reset(account=alternate)
                    self.assertEqual(code, 1, err)
                    self.assertIn("归属冲突", err)
                    with self.assertRaisesRegex(RuntimeError, "归属冲突"):
                        with acquire_local_profile("tiktok", alternate, "chrome", create=True):
                            self.fail("filesystem-equivalent labels must not merge")
                else:
                    # A case/normalization-sensitive filesystem keeps distinct aliases.
                    with acquire_local_profile("tiktok", alternate, "chrome", create=True) as profile:
                        self.assertTrue(profile.exists)
                first.communicate("release\n", timeout=5)
                self.assertEqual(first.returncode, 0)

    def test_missing_corrupt_or_conflicting_ownership_is_never_claimed(self):
        from utils.local_profile import acquire_local_profile
        with acquire_local_profile("tiktok", "Creator 名", "chrome", create=True) as profile:
            (profile.path / "state").write_text("preserve")
        for metadata in (self.root / ".tiktok.owner.json", profile.path.parent / ".sau-owner.json",
                         profile.path / ".sau-owner.json"):
            valid = metadata.read_bytes()
            for bad in (None, b"not json", b'{"platform": "wrong"}'):
                with self.subTest(metadata=metadata, bad=bad):
                    if bad is None:
                        metadata.unlink()
                    else:
                        metadata.write_bytes(bad)
                    try:
                        code, out, err = self.run_reset()
                        self.assertEqual(code, 1, err)
                        self.assertIn("归属", err)
                        self.assertEqual((profile.path / "state").read_text(), "preserve")
                    finally:
                        metadata.write_bytes(valid)
        self.assertEqual(self.run_reset()[0], 0)

    def test_reset_is_migrated_platform_only_and_rejects_managed_mode_without_external_calls(self):
        from contextlib import ExitStack
        from sau_commands import browser
        with ExitStack() as stack:
            for platform in ("tiktok", "rednote", "instagram", "xiaohongshu", "youtube", "facebook", "facebook-page", "douyin", "kuaishou", "tencent", "baijiahao", "weibo", "hupu", "alipay", "xueqiu"):
                stack.enter_context(patch(f"sau_commands.{platform.replace('-', '_')}.async_playwright",
                                          side_effect=AssertionError("must not start browser")))
            stack.enter_context(patch.object(browser, "MultiloginClient", side_effect=AssertionError("provider")))
            stack.enter_context(patch.object(browser, "AdspowerClient", side_effect=AssertionError("provider")))
            stack.enter_context(patch("subprocess.run", side_effect=AssertionError("must not inspect browser product")))
            for platform in ("tiktok", "rednote", "instagram", "xiaohongshu", "youtube", "facebook", "facebook-page", "douyin", "kuaishou", "tencent", "baijiahao", "weibo", "hupu", "alipay", "xueqiu"):
                self.assertEqual(self.run_reset(platform=platform)[0], 0)
                for variable in ("MLX_API_TOKEN", "ADSPOWER_API_KEY"):
                    with patch.dict(os.environ, {variable: "test-credential"}):
                        code, out, err = self.run_reset(platform=platform)
                        self.assertEqual(code, 2, err)
                        self.assertIn("仅支持本地模式", err)
            for platform in (
                             "dayu", "zhihu", "bilibili"):
                self.assertEqual(self.run_reset(platform=platform)[0], 2)

    def test_equivalent_root_spelling_cannot_bypass_profile_lock(self):
        from utils.local_profile import acquire_local_profile
        first = self.start_holder()
        equivalent_root = self.root / "tiktok" / ".."
        with self.assertRaisesRegex(RuntimeError, "占用"):
            with acquire_local_profile("tiktok", "Creator 名", "chrome", root=equivalent_root):
                self.fail("resolved directory has an active owner")
        first.communicate("release\n", timeout=5)

    def test_acquisition_releases_ownership_after_cancellation(self):
        from utils.local_profile import acquire_local_profile
        import asyncio
        with self.assertRaises(asyncio.CancelledError):
            with acquire_local_profile("tiktok", "Creator 名", "chrome", create=True):
                raise asyncio.CancelledError()
        with acquire_local_profile("tiktok", "Creator 名", "chrome") as profile:
            self.assertTrue(profile.exists)

    def test_metadata_names_do_not_reserve_otherwise_valid_account_aliases(self):
        from utils.local_profile import acquire_local_profile
        for alias in (".sau-owner.json", ".layout.lock", ".chrome.lock"):
            with acquire_local_profile("tiktok", alias, "chrome", create=True) as profile:
                self.assertEqual(profile.path, self.root / "tiktok" / alias / "chrome")
            self.assertEqual(self.run_reset(account=alias)[0], 0)

    def test_reset_retry_refuses_surviving_conflicting_or_corrupt_leaf_ownership(self):
        from utils.local_profile import acquire_local_profile
        with acquire_local_profile("tiktok", "Creator 名", "chrome", create=True) as profile:
            (profile.path / "state").write_text("preserve conflicting data")
        with patch("shutil.rmtree", side_effect=PermissionError("synthetic denial")):
            self.assertEqual(self.run_reset()[0], 1)
        metadata = profile.path / ".sau-owner.json"
        valid = metadata.read_bytes()
        for bad in (b'{"platform": "other"}', b"corrupt"):
            metadata.write_bytes(bad)
            code, out, err = self.run_reset()
            self.assertEqual(code, 1, err)
            self.assertIn("归属", err)
            self.assertEqual((profile.path / "state").read_text(), "preserve conflicting data")
        metadata.write_bytes(valid)
        self.assertEqual(self.run_reset()[0], 0)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX filesystem fixture")
    def test_nonregular_ownership_metadata_fails_without_waiting_for_a_writer(self):
        from utils.local_profile import acquire_local_profile
        with acquire_local_profile("tiktok", "Creator 名", "chrome", create=True) as profile:
            pass
        metadata = profile.path / ".sau-owner.json"
        metadata.unlink()
        os.mkfifo(metadata)
        child = subprocess.run(self.child_command(mode="once"), capture_output=True, text=True,
                               timeout=3, cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(child.returncode, 1)
        self.assertIn("归属", child.stderr)

    def test_reset_requires_explicit_target_and_has_no_browser_runtime_flags(self):
        for arguments in (("--browser-kind", "chrome"), ("--account", "Creator")):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    sau_cli.main(["tiktok", "reset-profile", *arguments])
            self.assertEqual(caught.exception.code, 2)
        for extra in (("--headed",), ("--local-browser", "chromium"), ("--profile-id", "remote")):
            self.assertEqual(self.run_reset(extra=extra)[0], 2)
        self.assertFalse(self.root.exists())

    def test_filesystem_unsupported_alias_reports_failure_without_shortening_it(self):
        alias = "长" * 256
        code, out, err = self.run_reset(account=alias)
        self.assertEqual(code, 1)
        self.assertIn(alias, err)
        self.assertFalse(any((self.root / "tiktok").iterdir()))


if __name__ == "__main__":
    unittest.main()
