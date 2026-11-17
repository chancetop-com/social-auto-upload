# -*- coding: utf-8 -*-
"""Guard the fixture behavior that could otherwise hide production failures.

Unscripted operations fail loudly, click assertions detect incorrect dispatch
counts, and FakeClock patches restore the original module namespaces.
"""

from __future__ import annotations

import asyncio
import time
import types
import unittest
from tests.fakes_clock import FakeClock
from tests.fakes_xhs_dom import (
    FakeLocator,
    RecordingLocator,
    RecordingPage,
    UnscriptedEvaluationError,
    UnscriptedSelectorError,
)


class FakeLocatorTests(unittest.TestCase):
    def test_unscripted_child_selector_raises(self):
        locator = FakeLocator("container", count=1, children={})

        with self.assertRaisesRegex(UnscriptedSelectorError, "span.missing"):
            locator.locator("span.missing")

    def test_unscripted_get_by_text_raises(self):
        locator = FakeLocator("container", count=1, children={})

        with self.assertRaisesRegex(UnscriptedSelectorError, "登录"):
            locator.get_by_text("登录")

    def test_zero_clicks_is_assertable(self):
        locator = RecordingLocator("publish-button")

        locator.assert_never_clicked()
        with self.assertRaises(AssertionError):
            locator.assert_clicked_once()

    def test_two_clicks_fail_the_exactly_once_assertion(self):
        locator = RecordingLocator("publish-button")
        asyncio.run(locator.click())
        asyncio.run(locator.click())

        self.assertEqual(locator.click_count, 2)
        with self.assertRaises(AssertionError):
            locator.assert_clicked_once()

    def test_click_error_propagates_but_still_records_the_attempt(self):
        locator = RecordingLocator(
            "publish-button", click_error=RuntimeError("dispatch failed")
        )

        with self.assertRaisesRegex(RuntimeError, "dispatch failed"):
            asyncio.run(locator.click())

        # The attempt happened; later tickets must be able to distinguish
        # "never dispatched" from "dispatch raised".
        self.assertEqual(locator.click_count, 1)


class RecordingPageTests(unittest.TestCase):
    def test_unscripted_selector_raises_instead_of_counting_zero(self):
        page = RecordingPage(selectors={})

        with self.assertRaisesRegex(UnscriptedSelectorError, "#publish-btn"):
            page.locator("#publish-btn")

    def test_unscripted_get_by_text_raises(self):
        page = RecordingPage(selectors={})

        with self.assertRaisesRegex(UnscriptedSelectorError, "发布"):
            page.get_by_text("发布")

    def test_unscripted_evaluate_raises(self):
        page = RecordingPage()

        with self.assertRaises(UnscriptedEvaluationError):
            asyncio.run(page.evaluate("() => document.body"))


class FakeClockTests(unittest.TestCase):
    def test_patch_replaces_the_module_time_and_asyncio_names(self):
        module = types.SimpleNamespace(time=time, asyncio=asyncio)
        real_time = module.time
        real_asyncio = module.asyncio
        clock = FakeClock()

        with clock.patch(module):
            self.assertEqual(module.time.monotonic(), 0.0)
            clock.advance(10.0)
            self.assertEqual(module.time.monotonic(), 10.0)
            asyncio.run(module.asyncio.sleep(5))
            self.assertEqual(clock.monotonic(), 15.0)
            self.assertEqual(clock.sleep_calls, [5])
            # Unrelated stdlib functions still work through the proxy.
            self.assertEqual(module.time.strftime("%Y", time.gmtime(0)), "1970")
            self.assertTrue(callable(module.asyncio.run))

        self.assertIs(module.time, real_time)
        self.assertIs(module.asyncio, real_asyncio)
        self.assertNotEqual(module.time.monotonic(), 15.0)

    def test_patch_only_needs_time_when_the_module_has_no_asyncio(self):
        module = types.SimpleNamespace(time=time)
        clock = FakeClock(start=3.0)

        with clock.patch(module):
            self.assertEqual(module.time.monotonic(), 3.0)
            clock.advance(1.0)
            self.assertEqual(module.time.monotonic(), 4.0)

    def test_patch_rejects_a_module_without_time(self):
        clock = FakeClock()

        with self.assertRaises(AssertionError):
            with clock.patch(types.SimpleNamespace()):
                pass

    def test_enter_and_exit_support_the_single_module_form(self):
        module = types.SimpleNamespace(time=time, asyncio=asyncio)
        clock = FakeClock(start=42.0, module=module)

        with clock:
            self.assertEqual(module.time.monotonic(), 42.0)

        self.assertIs(module.time, time)

if __name__ == "__main__":
    unittest.main()
