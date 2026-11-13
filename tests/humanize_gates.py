# -*- coding: utf-8 -*-
"""Executable form of spec §4 gates A–E (humanize rollout).

The gates are AST-based: they look at calls, receivers, string constants and
the comment inside the call's span.  Every later platform ticket wires its own
package in with::

    from tests.humanize_gates import assert_clean
    assert_clean(Path(__file__).resolve().parent.parent / "uploader" / "xhs")

Gate A
    No string constant in a wired package contains ``el.click`` or ``.click()``
    (JS click payloads, including ones hoisted into a module constant or built
    as an f-string).  Docstrings are prose and exempt.

Gate B
    Every native ``.click(...)`` (receiver that is not the humanizer) carries
    ``# native-click: <class>；<reason>`` inside its ``[lineno, end_lineno]``.
    Allowed classes: login / file / focus / manage / read / verify / chrome /
    language.  Exempt receivers are exactly ``humanizer``, ``<name>_humanizer``
    and attribute chains ending in ``humanizer`` (``self.humanizer``).

Gate C
    Every ``force=True`` call carries
    ``# humanize-impossible: <failure>；<code|inferred|needs-live>；<excluded>``
    inside its span.  The gate intentionally does not assert a count or an
    allowlist.

Gate D
    Every ``.fill(...)`` call carries ``# native-fill: <reason>`` inside its
    span.

Gate E
    ``type_horizon_chars`` is only defined in ``utils/humanize.py``: any other
    mention fails unless it is an attribute read (``X.type_horizon_chars``),
    which reuses the single definition instead of copying it.
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

_HORIZON = "type_horizon_chars"
#: ``X.type_horizon_chars`` reads the single definition; only bare mentions
#: (assignments, literals, comments) count as a second definition.
_HORIZON_ATTRIBUTE_RE = re.compile(r"\.\s*" + _HORIZON + r"\b")


def mentions_horizon_definition(line: str) -> bool:
    """True when ``line`` mentions ``type_horizon_chars`` other than as an attribute read."""
    if _HORIZON not in line:
        return False
    return _HORIZON in _HORIZON_ATTRIBUTE_RE.sub("", line)


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


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """``id()`` of every docstring constant (module / class / function).

    Docstrings are prose: they may *mention* ``Humanizer.click`` without being
    a JS payload, so gate A ignores them.
    """
    found: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", None) or []
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            found.add(id(first.value))
    return found


def _scan_gate_a(tree: ast.AST, lines: list[str]) -> list[tuple[int, str]]:
    """Every string constant that could be a JS click payload.

    Scanning all constants (not only ``evaluate`` / ``eval_on_selector`` /
    ``eval_on_selector_all`` / ``evaluate_all`` arguments) catches payloads
    hoisted into a module constant or built as an f-string, which the
    call-argument scan could never see.  Docstrings are prose and exempt.
    """
    docstrings = _docstring_nodes(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings:
            continue
        text = node.value
        if "el.click" in text or ".click()" in text:
            found.append(
                (node.lineno, f"gate A: JS click in string constant: {text[:80]!r}")
            )
    return found


def _is_humanizer_name(name: str) -> bool:
    """``humanizer`` or ``<prefix>_humanizer`` — the shared layer's own names."""
    return name == "humanizer" or name.endswith("_humanizer")


def _is_humanizer_receiver(node: ast.AST) -> bool:
    """Only real humanizer receivers are exempt from gate B's marker.

    ``humanizer``, ``<name>_humanizer`` and attribute chains ending in
    ``humanizer`` (``self.humanizer``) are the shared layer, including the
    page-scoped accessor call ``self._humanizer(page)``.  Lookalikes such as
    ``self.humanizer_page`` are still native clicks.
    """
    if isinstance(node, ast.Call):
        return _is_humanizer_receiver(node.func)
    if isinstance(node, ast.Name):
        return _is_humanizer_name(node.id)
    if isinstance(node, ast.Attribute):
        return _is_humanizer_name(node.attr)
    return False


def _scan_gate_b(tree: ast.AST, lines: list[str]) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "click":
            continue
        if _is_humanizer_receiver(func.value):
            continue
        receiver = _receiver_name(func.value)
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
                if mentions_horizon_definition(line):
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


__all__ = [
    "NATIVE_CLICK_CLASSES",
    "assert_clean",
    "gate_violations",
    "mentions_horizon_definition",
]
