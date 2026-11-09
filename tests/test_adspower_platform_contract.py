# -*- coding: utf-8 -*-
"""Static migration guards for the shared managed-browser seam (ticket 13).

Platform and uploader code must branch on ``session.managed`` (or the provider
protocol), never on a provider product name.  These guards are intentionally
source-level: a missed migration silently falls back to the local branch (real
``launch`` / ``new_context`` / cookie files) in a way runtime doubles cannot
observe.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCANNED_PACKAGES = ("uploader", "sau_commands")

PLATFORM_MODULES = (
    "alipay",
    "baijiahao",
    "dayu",
    "douyin",
    "facebook",
    "facebook_page",
    "hupu",
    "instagram",
    "kuaishou",
    "tencent",
    "tiktok",
    "weibo",
    "xiaohongshu",
    "xueqiu",
    "youtube",
    "zhihu",
)

MODE_BRANCH_PATTERN = re.compile(
    r"""\.mode\s*[=!]=\s*["']multilogin["']"""
)


def _python_files(package: str):
    for path in sorted((ROOT / package).rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class NoProviderNameBranchesTests(unittest.TestCase):
    def test_no_mode_equals_multilogin_branch_remains(self):
        offenders: list[str] = []
        for package in SCANNED_PACKAGES:
            for path in _python_files(package):
                for number, line in enumerate(
                    _source(path).splitlines(), start=1
                ):
                    if MODE_BRANCH_PATTERN.search(line):
                        rel = path.relative_to(ROOT)
                        offenders.append(f"{rel}:{number}: {line.strip()}")
        self.assertEqual(
            offenders,
            [],
            "provider-name branch(es) must use session.managed instead:\n"
            + "\n".join(offenders),
        )

    def test_no_browser_session_call_passes_multilogin_keyword(self):
        offenders: list[str] = []
        for package in SCANNED_PACKAGES:
            for path in _python_files(package):
                tree = ast.parse(_source(path), filename=str(path))
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    func = node.func
                    name = (
                        func.id
                        if isinstance(func, ast.Name)
                        else getattr(func, "attr", None)
                    )
                    if name != "browser_session":
                        continue
                    keywords = {kw.arg for kw in node.keywords}
                    if "multilogin" in keywords:
                        rel = path.relative_to(ROOT)
                        offenders.append(f"{rel}:{node.lineno}")
        self.assertEqual(
            offenders,
            [],
            "browser_session() still receives multilogin=:\n"
            + "\n".join(offenders),
        )


class PlatformWiringTests(unittest.TestCase):
    def test_every_browser_platform_uses_resolve_managed_provider(self):
        offenders = []
        for module in PLATFORM_MODULES:
            source = _source(ROOT / "sau_commands" / f"{module}.py")
            if "resolve_managed_provider" not in source:
                offenders.append(module)
        self.assertEqual(offenders, [])

    def test_every_browser_platform_uses_managed_rejections(self):
        offenders = []
        for module in PLATFORM_MODULES:
            source = _source(ROOT / "sau_commands" / f"{module}.py")
            if "reject_managed_login" not in source:
                offenders.append(module)
            if "reject_multilogin_login" in source:
                offenders.append(module)
        self.assertEqual(offenders, [])

    def test_bilibili_uses_managed_rejections(self):
        source = _source(ROOT / "sau_commands" / "bilibili.py")
        self.assertIn("reject_managed_login", source)
        self.assertIn("reject_managed_platform", source)
        self.assertNotIn("reject_multilogin_login", source)
        self.assertNotIn("reject_multilogin_platform", source)

    def test_shim_keeps_legacy_multilogin_names(self):
        source = _source(ROOT / "sau_commands" / "multilogin.py")
        for name in (
            "add_multilogin_flags",
            "login_required_error",
            "multilogin_enabled",
            "reject_multilogin_login",
            "reject_multilogin_platform",
            "require_account",
            "require_local_account",
            "resolve_account_label",
            "resolve_multilogin_target",
        ):
            with self.subTest(name=name):
                self.assertIn(name, source)


if __name__ == "__main__":
    unittest.main()
