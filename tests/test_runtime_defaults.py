# -*- coding: utf-8 -*-
"""运行参数契约（ticket 29，规格 §3 U13 ①②）。

两条规则：
- `headless` 默认有头；`--headed` 等价默认，`--headless` 显式无头；
  CLI 参数层不读 `conf.LOCAL_CHROME_HEADLESS`。
- `debug` 默认关，唯一来源是 CLI；配置项（`DEBUG` + `_MODE`）与 uploader
  构造默认值不再与它打架。
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest.mock import patch

import conf
import sau_cli

ROOT = Path(__file__).resolve().parent.parent
DEBUG_TOKEN = "DEBUG" + "_MODE"

# 只扫描会随包发布的代码/文档；规划目录（.scratch）与变更日志保留历史文本。
DEBUG_SCANNED_PATHS = (
    ROOT / "uploader",
    ROOT / "sau_commands",
    ROOT / "conf.example.py",
    ROOT / "docs" / "install.md",
    ROOT / "docs" / "CLI.md",
)
DEBUG_SCANNED_SUFFIXES = {".py", ".md"}

# 已知至少这些构造器带 debug 默认值；下界用于防止 AST 扫描静默失效。
MIN_DEBUG_DEFAULTS = 13


def _iter_scan_files(path: Path):
    if path.is_file():
        yield path
        return
    for child in sorted(path.rglob("*")):
        if "__pycache__" in child.parts:
            continue
        if child.is_file() and child.suffix in DEBUG_SCANNED_SUFFIXES:
            yield child


def _init_debug_defaults(tree: ast.AST):
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != "__init__":
            continue
        args = node.args
        positional = args.posonlyargs + args.args
        paired = list(zip(positional[-len(args.defaults) :], args.defaults))
        paired += [
            (arg, default)
            for arg, default in zip(args.kwonlyargs, args.kw_defaults)
            if default is not None
        ]
        for arg, default in paired:
            if arg.arg == "debug":
                yield node, default


class DebugSingleSourceTests(unittest.TestCase):
    def test_uploader_constructor_debug_defaults_are_false(self):
        defaults = []
        offenders: list[str] = []
        for path in sorted((ROOT / "uploader").rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node, default in _init_debug_defaults(tree):
                defaults.append((path, node.lineno))
                if not (
                    isinstance(default, ast.Constant) and default.value is False
                ):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertGreaterEqual(len(defaults), MIN_DEBUG_DEFAULTS)
        self.assertEqual(offenders, [], "uploader debug 默认值必须为 False")

    def test_debug_config_token_has_no_residue(self):
        offenders: list[str] = []
        for root in DEBUG_SCANNED_PATHS:
            for path in _iter_scan_files(root):
                if DEBUG_TOKEN in path.read_text(encoding="utf-8"):
                    offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [], "配置项 token 只允许留在变更日志历史里")


class CliRuntimeDefaultsTests(unittest.TestCase):
    def test_debug_defaults_off_and_flag_turns_it_on(self):
        parser = sau_cli.build_parser()
        default_args = parser.parse_args(["douyin", "check", "--account", "creator"])
        debug_args = parser.parse_args(
            ["douyin", "check", "--account", "creator", "--debug"]
        )
        self.assertFalse(default_args.debug)
        self.assertTrue(debug_args.debug)

    def test_cli_ignores_local_chrome_headless_config(self):
        parser = sau_cli.build_parser()
        for configured in (True, False):
            with self.subTest(local_chrome_headless=configured):
                with patch.object(
                    conf, "LOCAL_CHROME_HEADLESS", configured, create=True
                ):
                    args = parser.parse_args(
                        ["douyin", "check", "--account", "creator"]
                    )
                self.assertFalse(args.headless)


if __name__ == "__main__":
    unittest.main()
