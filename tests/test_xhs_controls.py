# -*- coding: utf-8 -*-
"""Contract tests for ``utils/controls.py`` (ticket 32).

The one public function answers "is this switch on?" without knowing any
platform: ``aria-checked`` first, ``is_checked()`` second, ``None`` when the
state genuinely cannot be read.  ``None`` is the readback contract for tickets
39/40 -- it must never be collapsed into ``False``.
"""

from __future__ import annotations

import ast
import pathlib
import unittest

from utils import controls
from utils.controls import read_switch_state

_UNSET = object()


class SwitchLocator:
    """Fail-loudly switch double: only the two documented probes exist."""

    def __init__(
        self,
        *,
        attributes=None,
        attribute_error=None,
        checked=_UNSET,
        checked_error=None,
    ):
        self._attributes = dict(attributes or {})
        self._attribute_error = attribute_error
        self._checked = checked
        self._checked_error = checked_error
        self.attribute_calls = 0
        self.checked_calls = 0

    async def get_attribute(self, name):
        self.attribute_calls += 1
        if self._attribute_error is not None:
            raise self._attribute_error
        return self._attributes.get(name)

    async def is_checked(self):
        self.checked_calls += 1
        if self._checked_error is not None:
            raise self._checked_error
        if self._checked is _UNSET:
            raise AssertionError("read_switch_state called is_checked unscripted")
        return self._checked


class ReadSwitchStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_aria_checked_true_wins(self):
        loc = SwitchLocator(attributes={"aria-checked": "true"}, checked=False)
        self.assertIs(await read_switch_state(loc), True)
        self.assertEqual(loc.checked_calls, 0)

    async def test_aria_checked_false_wins(self):
        loc = SwitchLocator(attributes={"aria-checked": "false"}, checked=True)
        self.assertIs(await read_switch_state(loc), False)

    async def test_aria_checked_is_trimmed_and_case_insensitive(self):
        loc = SwitchLocator(attributes={"aria-checked": " TRUE "})
        self.assertIs(await read_switch_state(loc), True)

    async def test_falls_back_to_is_checked(self):
        loc = SwitchLocator(checked=True)
        self.assertIs(await read_switch_state(loc), True)
        self.assertEqual(loc.attribute_calls, 1)

    async def test_mixed_aria_checked_falls_back_to_is_checked(self):
        loc = SwitchLocator(attributes={"aria-checked": "mixed"}, checked=True)
        self.assertIs(await read_switch_state(loc), True)

    async def test_is_checked_false_is_false_not_none(self):
        loc = SwitchLocator(attributes={"aria-checked": "false"})
        result = await read_switch_state(loc)
        self.assertIs(result, False)

    async def test_attribute_probe_error_falls_back(self):
        loc = SwitchLocator(
            attribute_error=RuntimeError("detached"), checked=True
        )
        self.assertIs(await read_switch_state(loc), True)

    async def test_both_probes_failing_returns_none(self):
        loc = SwitchLocator(
            attribute_error=RuntimeError("detached"),
            checked_error=RuntimeError("not a checkbox"),
        )
        self.assertIsNone(await read_switch_state(loc))

    async def test_missing_is_checked_returns_none(self):
        class NoCheckedMethod:
            async def get_attribute(self, name):
                return None

        self.assertIsNone(await read_switch_state(NoCheckedMethod()))

    async def test_none_is_not_false(self):
        loc = SwitchLocator(checked_error=RuntimeError("unknown"))
        self.assertIsNot(await read_switch_state(loc), False)


class ControlsBoundaryTests(unittest.TestCase):
    def test_module_has_no_runtime_imports(self):
        tree = ast.parse(pathlib.Path(controls.__file__).read_text(encoding="utf-8"))
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
        self.assertEqual(modules, ["__future__"])

    def test_public_surface_is_one_function(self):
        public = {
            name
            for name in dir(controls)
            if not name.startswith("_") and callable(getattr(controls, name))
        }
        self.assertEqual(public, {"read_switch_state"})


if __name__ == "__main__":
    unittest.main()
