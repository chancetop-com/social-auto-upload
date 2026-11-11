# -*- coding: utf-8 -*-
"""Self-tests for the XHS DOM/clock fixtures (ticket 28).

The fixtures are test infrastructure, so they need their own proof:

* an un-scripted selector must raise instead of pretending "count == 0";
* every interaction the publish chain cares about must be recorded, including
  every ``wait_for_*`` timeout argument;
* a click must be countable so later tickets can assert "exactly once" and
  "zero times";
* :class:`FakeClock` must replace the *module-level* ``time`` / ``asyncio``
  names without production code growing clock or sleep parameters.

Fixtures only — they are shared by every ``Decision03``–``Decision13`` suite
and deliberately carry no decision prefix of their own.

All offline: no browser, no network.
"""

from __future__ import annotations

import asyncio
import time
import types
import unittest
from contextlib import redirect_stderr
from io import StringIO

from tests.fakes_clock import FakeClock
from tests.fakes_xhs_dom import (
    FakeLocator,
    RecordingLocator,
    RecordingPage,
    UnscriptedEvaluationError,
    UnscriptedSelectorError,
)


class FakeLocatorTests(unittest.TestCase):
    def test_reads_every_scripted_surface(self):
        child = FakeLocator("child", count=1, text="子节点")
        locator = FakeLocator(
            "publish-button",
            count=2,
            attributes={"is-publish": "false", "src": "data:image/png;base64,abc"},
            visible=False,
            computed_style={"pointerEvents": "none"},
            text="发布",
            children={"span": child},
        )

        self.assertEqual(asyncio.run(locator.count()), 2)
        self.assertIs(locator.first, locator)
        self.assertEqual(asyncio.run(locator.get_attribute("is-publish")), "false")
        self.assertEqual(
            asyncio.run(locator.get_attribute("src")),
            "data:image/png;base64,abc",
        )
        self.assertIsNone(asyncio.run(locator.get_attribute("missing")))
        self.assertFalse(asyncio.run(locator.is_visible()))
        self.assertEqual(asyncio.run(locator.inner_text()), "发布")
        self.assertEqual(asyncio.run(locator.text_content()), "发布")
        self.assertEqual(
            asyncio.run(locator.evaluate("el => getComputedStyle(el)")),
            {"pointerEvents": "none"},
        )
        self.assertIs(locator.locator("span"), child)

    def test_unscripted_child_selector_raises(self):
        locator = FakeLocator("container", count=1, children={})

        with self.assertRaisesRegex(UnscriptedSelectorError, "span.missing"):
            locator.locator("span.missing")

    def test_unscripted_get_by_text_raises(self):
        locator = FakeLocator("container", count=1, children={})

        with self.assertRaisesRegex(UnscriptedSelectorError, "登录"):
            locator.get_by_text("登录")

    def test_first_last_and_nth_follow_scripted_items(self):
        first = FakeLocator("first", count=1)
        second = FakeLocator("second", count=1)
        locator = FakeLocator("items", items=[first, second])

        self.assertIs(locator.first, first)
        self.assertIs(locator.last, second)
        self.assertIs(locator.nth(0), first)
        self.assertIs(locator.nth(1), second)
        with self.assertRaises(IndexError):
            locator.nth(2)

    def test_records_actions_and_counts_clicks(self):
        locator = RecordingLocator("publish-button")

        asyncio.run(locator.fill("标题"))
        asyncio.run(locator.click())
        asyncio.run(locator.wait_for(state="visible", timeout=4000))

        self.assertEqual(locator.click_count, 1)
        self.assertEqual(
            locator.actions,
            [
                ("fill", "标题"),
                ("click",),
                ("wait_for", {"state": "visible", "timeout": 4000}),
            ],
        )
        locator.assert_clicked_once()

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

    def test_wait_for_records_every_timeout_argument(self):
        locator = RecordingLocator("publish-button")

        asyncio.run(locator.wait_for(state="visible", timeout=1234))

        self.assertEqual(locator.wait_calls[0].method, "wait_for")
        self.assertEqual(locator.wait_calls[0].timeout, 1234)


class RecordingPageTests(unittest.TestCase):
    def test_unscripted_selector_raises_instead_of_counting_zero(self):
        page = RecordingPage(selectors={})

        with self.assertRaisesRegex(UnscriptedSelectorError, "#publish-btn"):
            page.locator("#publish-btn")

    def test_unscripted_get_by_text_raises(self):
        page = RecordingPage(selectors={})

        with self.assertRaisesRegex(UnscriptedSelectorError, "发布"):
            page.get_by_text("发布")

    def test_url_and_main_frame_url_are_writable(self):
        page = RecordingPage(url="https://creator.xiaohongshu.com/login")

        page.url = "https://creator.xiaohongshu.com/publish/publish"
        page.main_frame.url = "https://creator.xiaohongshu.com/publish/publish"

        self.assertEqual(
            page.url, "https://creator.xiaohongshu.com/publish/publish"
        )
        self.assertEqual(
            page.main_frame.url,
            "https://creator.xiaohongshu.com/publish/publish",
        )

    def test_goto_updates_url_and_records_arguments(self):
        page = RecordingPage()

        asyncio.run(
            page.goto(
                "https://creator.xiaohongshu.com/publish/publish",
                wait_until="domcontentloaded",
                timeout=15000,
            )
        )

        self.assertEqual(
            page.goto_calls,
            [
                (
                    "https://creator.xiaohongshu.com/publish/publish",
                    {"wait_until": "domcontentloaded", "timeout": 15000},
                )
            ],
        )
        self.assertEqual(
            page.url, "https://creator.xiaohongshu.com/publish/publish"
        )
        self.assertEqual(page.main_frame.url, page.url)

    def test_evaluate_records_calls_and_returns_scripted_results(self):
        page = RecordingPage(evaluate_results=["first-result", {"ok": True}])

        self.assertEqual(asyncio.run(page.evaluate("1 + 1")), "first-result")
        self.assertEqual(asyncio.run(page.evaluate("() => 2 / 1")), {"ok": True})
        self.assertEqual(
            page.evaluate_calls,
            [("1 + 1", None), ("() => 2 / 1", None)],
        )

    def test_element_from_point_returns_scripted_hit_target_and_is_recorded(self):
        page = RecordingPage(hit_test_target="publish-button")

        result = asyncio.run(
            page.evaluate(
                "(point) => { const el = document.elementFromPoint("
                "point.x, point.y); return el && el.id; }",
                {"x": 10, "y": 20},
            )
        )

        self.assertEqual(result, "publish-button")
        expression, arg = page.evaluate_calls[0]
        self.assertIn("elementFromPoint", expression)
        self.assertEqual(arg, {"x": 10, "y": 20})

    def test_unscripted_evaluate_raises(self):
        page = RecordingPage()

        with self.assertRaises(UnscriptedEvaluationError):
            asyncio.run(page.evaluate("() => document.body"))

    def test_mouse_records_every_action_and_counts_downs(self):
        page = RecordingPage()

        asyncio.run(page.mouse.move(10, 20))
        asyncio.run(page.mouse.down())
        asyncio.run(page.mouse.up())
        asyncio.run(page.mouse.click(30, 40))

        self.assertEqual(
            page.mouse.actions,
            [
                ("move", 10, 20),
                ("down",),
                ("up",),
                ("click", 30, 40),
            ],
        )
        self.assertEqual(page.mouse.down_count, 1)

    def test_keyboard_records_every_action(self):
        page = RecordingPage()

        asyncio.run(page.keyboard.press("Backspace"))
        asyncio.run(page.keyboard.type("描述内容", delay=30))
        asyncio.run(page.keyboard.insert_text("#话题"))

        self.assertEqual(
            page.keyboard.actions,
            [
                ("press", "Backspace"),
                ("type", "描述内容", 30),
                ("insert_text", "#话题"),
            ],
        )

    def test_screenshot_is_recorded(self):
        page = RecordingPage()

        asyncio.run(page.screenshot(path="failure.png", full_page=True))

        self.assertEqual(
            page.screenshot_calls,
            [{"path": "failure.png", "full_page": True}],
        )

    def test_every_wait_for_star_records_its_timeout_argument(self):
        locator = RecordingLocator(".scripted", count=1)
        page = RecordingPage(selectors={".scripted": locator})

        asyncio.run(page.wait_for_timeout(1500))
        asyncio.run(
            page.wait_for_selector(".scripted", state="visible", timeout=2000)
        )
        asyncio.run(
            page.wait_for_url("**/publish/success", timeout=3000)
        )
        asyncio.run(page.wait_for_load_state("domcontentloaded", timeout=4000))
        asyncio.run(page.wait_for_function("() => true", timeout=5000))
        asyncio.run(page.wait_for_event("response", timeout=6000))
        asyncio.run(locator.wait_for(state="visible", timeout=7000))

        self.assertEqual(
            [(call.method, call.timeout) for call in page.wait_calls],
            [
                ("wait_for_timeout", 1500),
                ("wait_for_selector", 2000),
                ("wait_for_url", 3000),
                ("wait_for_load_state", 4000),
                ("wait_for_function", 5000),
                ("wait_for_event", 6000),
            ],
        )
        self.assertEqual(locator.wait_calls[0].timeout, 7000)

    def test_wait_for_selector_returns_the_scripted_locator(self):
        locator = RecordingLocator(".scripted", count=1)
        page = RecordingPage(selectors={".scripted": locator})

        self.assertIs(
            asyncio.run(page.wait_for_selector(".scripted")), locator
        )

    def test_wait_timeouts_can_be_filtered_by_method(self):
        page = RecordingPage()

        asyncio.run(page.wait_for_timeout(100))
        asyncio.run(page.wait_for_timeout(250))

        self.assertEqual(
            page.timeouts("wait_for_timeout"), [100, 250]
        )


class FakeClockTests(unittest.TestCase):
    def test_monotonic_starts_at_zero_and_advance_moves_it(self):
        clock = FakeClock()

        self.assertEqual(clock.monotonic(), 0.0)
        clock.advance(12.5)
        self.assertEqual(clock.monotonic(), 12.5)

    def test_sleep_advances_the_clock_and_records_the_request(self):
        clock = FakeClock(start=100.0)

        asyncio.run(clock.sleep(2.5))

        self.assertEqual(clock.sleep_calls, [2.5])
        self.assertEqual(clock.monotonic(), 102.5)

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

    def test_patching_does_not_need_stderr_or_production_parameters(self):
        """The fixture patches the module namespace, not a call signature."""
        module = types.SimpleNamespace(time=time, asyncio=asyncio)
        clock = FakeClock()

        with redirect_stderr(StringIO()):
            with clock.patch(module):
                pass


if __name__ == "__main__":
    unittest.main()
