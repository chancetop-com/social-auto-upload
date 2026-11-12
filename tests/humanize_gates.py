# -*- coding: utf-8 -*-
"""Executable form of spec §4 gates A–E (humanize rollout).

The gates are AST-based and deliberately **content-read-free**: they look at
calls, receivers and the comment inside the call's span, never at formatted
strings.  Every later platform ticket wires its own package in with::

    from tests.humanize_gates import assert_clean
    assert_clean(Path(__file__).resolve().parent.parent / "uploader" / "xhs")

Gate A
    No ``evaluate`` / ``eval_on_selector`` call with a constant string argument
    containing ``el.click`` or ``.click()``.

Gate B
    Every native ``.click(...)`` (receiver name without ``humanizer``) carries
    ``# native-click: <class>；<reason>`` inside its ``[lineno, end_lineno]``.
    Allowed classes: login / file / focus / manage / read / verify / chrome /
    language.

Gate C
    Every ``force=True`` call carries
    ``# humanize-impossible: <failure>；<code|inferred|needs-live>；<excluded>``
    inside its span.  The gate intentionally does not assert a count or an
    allowlist.

Gate D
    Every ``.fill(...)`` call carries ``# native-fill: <reason>`` inside its
    span.

Gate E
    ``type_horizon_chars`` appears only in ``utils/humanize.py``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

NATIVE_CLICK_CLASSES = frozenset(
    {"login", "file", "focus", "manage", "read", "verify", "chrome", "language"}
)

_NATIVE_CLICK_RE = re.compile(r"#\s*native-click:\s*([A-Za-z]+)\s*；")
_IMPOSSIBLE_RE = re.compile(
    r"#\s*humanize-impossible:\s*[^；#\n]+?；\s*"
    r"(?P<evidence>code|inferred|needs-live)\s*；\s*[^；#\n]+"
)
_NATIVE_FILL_RE = re.compile(r"#\s*native-fill:\s*[^#\n]+")

_JS_CLICK_ATTRS = frozenset({"evaluate", "eval_on_selector"})
_HORIZON = "type_horizon_chars"


def _discover_root(package: Path) -> Path:
    resolved = package.resolve()
    for candidate in (resolved, *resolved.parents):
        if (candidate / "utils" / "humanize.py").is_file():
            return candidate
    return resolved.parent


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _python_files(package: Path) -> list[Path]:
    if package.is_file():
        return [package] if package.suffix == ".py" else []
    return sorted(path for path in package.rglob("*.py") if path.is_file())


def _span(lines: list[str], node: ast.AST) -> str:
    start = max(0, node.lineno - 1)
    end = max(start + 1, getattr(node, "end_lineno", node.lineno))
    return "\n".join(lines[start:end])


def _receiver_name(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - ast.unparse is available on 3.9+
        return ""


def _constant_strings(node: ast.Call) -> list[str]:
    values: list[str] = []
    nodes = list(node.args) + [keyword.value for keyword in node.keywords]
    for argument in nodes:
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            values.append(argument.value)
    return values


def _scan_gate_a(tree: ast.AST, lines: list[str]) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in _JS_CLICK_ATTRS:
            continue
        for text in _constant_strings(node):
            if "el.click" in text or ".click()" in text:
                found.append(
                    (node.lineno, f"gate A: JS click via {func.attr}(): {text!r}")
                )
                break
    return found


def _scan_gate_b(tree: ast.AST, lines: list[str]) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "click":
            continue
        receiver = _receiver_name(func.value)
        if "humanizer" in receiver.lower():
            continue
        match = _NATIVE_CLICK_RE.search(_span(lines, node))
        if match is None:
            found.append(
                (
                    node.lineno,
                    f"gate B: native click on {receiver!r} has no "
                    "# native-click: <class>；<reason>",
                )
            )
        elif match.group(1).lower() not in NATIVE_CLICK_CLASSES:
            found.append(
                (
                    node.lineno,
                    f"gate B: unknown native-click class {match.group(1)!r}; "
                    f"allowed: {sorted(NATIVE_CLICK_CLASSES)}",
                )
            )
    return found


def _scan_gate_c(tree: ast.AST, lines: list[str]) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        forced = any(
            keyword.arg == "force"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in node.keywords
        )
        if forced and _IMPOSSIBLE_RE.search(_span(lines, node)) is None:
            found.append(
                (
                    node.lineno,
                    "gate C: force=True without "
                    "# humanize-impossible: <failure>；<code|inferred|needs-live>；"
                    "<excluded>",
                )
            )
    return found


def _scan_gate_d(tree: ast.AST, lines: list[str]) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "fill":
            continue
        if _NATIVE_FILL_RE.search(_span(lines, node)) is None:
            found.append(
                (
                    node.lineno,
                    "gate D: fill() without # native-fill: <reason>",
                )
            )
    return found


def _scan_gate_e(root: Path) -> list[str]:
    humanize_file = (root / "utils" / "humanize.py").resolve()
    found: list[str] = []
    for folder in ("utils", "uploader", "sau_commands"):
        base = root / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if path.resolve() == humanize_file:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for number, line in enumerate(lines, start=1):
                if _HORIZON in line:
                    found.append(
                        f"{_relative(path, root)}:{number}: "
                        f"gate E: {_HORIZON} outside utils/humanize.py"
                    )
    return found


def _scan(package: Path, root: Path) -> list[str]:
    violations: list[str] = []
    for path in _python_files(package):
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            violations.append(
                f"{_relative(path, root)}:{exc.lineno or 1}: "
                f"gate: cannot parse: {exc.msg}"
            )
            continue
        lines = source.splitlines()
        display = _relative(path, root)
        for scanner in (_scan_gate_a, _scan_gate_b, _scan_gate_c, _scan_gate_d):
            for lineno, detail in scanner(tree, lines):
                violations.append(f"{display}:{lineno}: {detail}")
    violations.extend(_scan_gate_e(root))
    return violations


def gate_violations(package: Path) -> list[str]:
    """Return every gate A–E violation for ``package`` (``path:line: detail``)."""
    package = Path(package)
    root = _discover_root(package)
    return _scan(package, root)


def assert_clean(package: Path, *, root: Path | None = None) -> None:
    """Raise ``AssertionError`` listing every violation, joined by newlines."""
    package = Path(package)
    resolved_root = Path(root) if root is not None else _discover_root(package)
    violations = _scan(package, resolved_root)
    if violations:
        raise AssertionError("\n".join(violations))


__all__ = ["NATIVE_CLICK_CLASSES", "assert_clean", "gate_violations"]
