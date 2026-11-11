# -*- coding: utf-8 -*-
"""Submit semantics: ARM → FIRE → OBSERVE (spec §3 U2, ticket 36).

Offline, virtual-time tests over the scripted doubles from ticket 28.  The
three phases are tested at their seams:

* ``_arm_ready`` — the one readiness predicate (button + ``interactive`` +
  ``is-publish`` + ``submit-disabled``);
* ``_wait_for_arm`` — 1s polling, window ``min(60s, budget)``, keep waiting
  until every condition is true, then return without touching the button;
* ``_fire_publish`` — one ``mouse.down`` at most; exceptions before the press
  are definitely-not-dispatched (exit 1), exceptions after it are
  possibly-dispatched (10 + ``publish_attempted`` on a blocked page, else 9);
* ``_observe_publish`` — URL-only success, C4 classification first, 500ms
  polling, 15s window (exit 9 when the page never leaves).

The zero-text-scanning gate is a static assertion: the helpers never look at
``inner_text`` / toast / rate-limit keyword tables.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import io
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import AsyncMock, patch

import sau_cli
import uploader.publish_timeout as publish_timeout
import uploader.xiaohongshu_uploader.main as xhs_main
from tests.fakes_clock import FakeClock
from tests.fakes_xhs_dom import FakeLocator, RecordingLocator, RecordingMouse, RecordingPage, preview_tiles
from utils.errors import LoginRequiredError, PublishResultUnknownError
from utils.humanize import Humanizer

PUBLISH_SELECTOR = "xhs-publish-btn"
LOGIN_BOX = xhs_main.XHS_LOGIN_BOX_SELECTOR
PUBLISH_URL = (
    "https://creator.xiaohongshu.com/publish/publish?from=homepage&target=image"
)
SUCCESS_URL = "https://creator.xiaohongshu.com/publish/success?target=image"
NOTE_TILES_SELECTOR = ".img-preview-area .pr"
LOGIN_URL = "https://creator.xiaohongshu.com/login?redirect=%2Fpublish"
VERIFICATION_URL = (
    "https://creator.xiaohongshu.com/website-login/captcha?redirectPath=%2Fpublish"
)

BUTTON_FACTS = {
    "tag": "button",
    "display": "block",
    "visibility": "visible",
    "opacity": 1.0,
    "ariaHidden": None,
    "ancestorAriaHidden": False,
    "disabled": False,
    "disabledClass": False,
    "pointerEvents": "auto",
    "contentEditable": None,
    "readOnly": False,
    "isConnected": True,
}
INPUT_FACTS = dict(BUTTON_FACTS, tag="input")
ABSENT_FACTS = dict(BUTTON_FACTS, display="none")


class _PublishButton(RecordingLocator):
    """Interactive publish button: box, facts and a passing hit-test."""

    def __init__(
        self,
        name: str = "publish",
        *,
        attributes: dict | None = None,
        facts: dict | None = None,
        box: dict | None = None,
        enabled: bool = True,
        count: int | None = None,
    ) -> None:
        super().__init__(
            name,
            count=count,
            attributes=attributes or {},
            computed_style=dict(facts or BUTTON_FACTS),
            enabled=enabled,
        )
        self.box = box or {"x": 10.0, "y": 20.0, "width": 160.0, "height": 40.0}
        self.box_calls = 0

    async def bounding_box(self):
        self.box_calls += 1
        return dict(self.box)

    async def evaluate(self, expression, arg=None):
        self.evaluate_calls.append((expression, arg))
        if isinstance(expression, str) and "elementFromPoint" in expression:
            return {
                "self": True,
                "tag": "button",
                "className": "",
                "id": "",
                "text": "",
            }
        return dict(self._computed_style or BUTTON_FACTS)


class _FileInput(FakeLocator):
    def __init__(self, name: str = "file-input") -> None:
        super().__init__(name, computed_style=dict(INPUT_FACTS))
        self.files: list[object] = []

    async def set_input_files(self, files, **kwargs) -> None:
        self.files.append(files)


class _CyclingPage(RecordingPage):
    """Publish-button page that hands out a fresh locator on every resolve."""

    def __init__(self, buttons, **kwargs) -> None:
        super().__init__(**kwargs)
        self._buttons = list(buttons)
        self.publish_locator_calls = 0

    def locator(self, selector: str):
        if selector == PUBLISH_SELECTOR:
            index = min(self.publish_locator_calls, len(self._buttons) - 1)
            self.publish_locator_calls += 1
            return self._buttons[index]
        return super().locator(selector)


def _button_page(button=None, *, url: str = PUBLISH_URL) -> RecordingPage:
    return RecordingPage(
        url=url,
        selectors={
            PUBLISH_SELECTOR: button if button is not None else _PublishButton(),
            LOGIN_BOX: FakeLocator("login-box", count=0),
        },
    )


async def _noop_async_sleep(_seconds: float) -> None:
    return None


def _humanizer(page: RecordingPage) -> Humanizer:
    return Humanizer(page, sleep=_noop_async_sleep)


def _note_app(**overrides):
    values = {
        "image_paths": ["a.png"],
        "note": "",
        "tags": [],
        "publish_date": 0,
        "account_file": "account.json",
        "title": "标题",
        "no_publish": True,
    }
    values.update(overrides)
    return xhs_main.XiaoHongShuNote(**values)


def _note_page(button=None, *, url: str = PUBLISH_URL) -> RecordingPage:
    return RecordingPage(
        url=url,
        selectors={
            "div.upload-content input.upload-input": _FileInput("image-input"),
            NOTE_TILES_SELECTOR: preview_tiles(1),
            'input[placeholder*="填写标题"]': FakeLocator(
                "title-zh", computed_style=dict(INPUT_FACTS)
            ),
            "div.d-input input": FakeLocator(
                "title", computed_style=dict(INPUT_FACTS)
            ),
            PUBLISH_SELECTOR: button if button is not None else _PublishButton(),
            LOGIN_BOX: FakeLocator("login-box", count=0),
        },
    )


# ---------------------------------------------------------------------------
# 1. ARM: the single readiness predicate
# ---------------------------------------------------------------------------


class ArmReadyTests(unittest.TestCase):
    def test_missing_button_is_not_ready(self):
        page = _button_page(FakeLocator("absent", count=0))
        ready, reason = asyncio.run(
            xhs_main._arm_ready(page, budget=None)
        )
        self.assertFalse(ready)
        self.assertEqual(reason, "not-attached")

    def test_disabled_button_is_not_ready(self):
        page = _button_page(_PublishButton("disabled", enabled=False))
        ready, reason = asyncio.run(xhs_main._arm_ready(page, budget=None))
        self.assertFalse(ready)
        self.assertEqual(reason, "disabled")

    def test_is_publish_false_is_not_ready(self):
        page = _button_page(
            _PublishButton("is-publish", attributes={"is-publish": "false"})
        )
        ready, reason = asyncio.run(xhs_main._arm_ready(page, budget=None))
        self.assertFalse(ready)
        self.assertEqual(reason, "is-publish-false")

    def test_submit_disabled_true_is_not_ready(self):
        page = _button_page(
            _PublishButton("submit-disabled", attributes={"submit-disabled": "true"})
        )
        ready, reason = asyncio.run(xhs_main._arm_ready(page, budget=None))
        self.assertFalse(ready)
        self.assertEqual(reason, "submit-disabled-true")

    def test_missing_optional_attributes_pass(self):
        page = _button_page()
        ready, reason = asyncio.run(xhs_main._arm_ready(page, budget=None))
        self.assertTrue(ready)
        self.assertIsNone(reason)

    def test_other_values_for_optional_attributes_pass(self):
        page = _button_page(
            _PublishButton(
                "truthy",
                attributes={"is-publish": "true", "submit-disabled": "false"},
            )
        )
        ready, _reason = asyncio.run(xhs_main._arm_ready(page, budget=None))
        self.assertTrue(ready)


class ArmWaitTests(unittest.TestCase):
    def test_each_failing_condition_keeps_waiting_then_resolves(self):
        # Every poll re-resolves the button; an old (disabled) element must
        # never be reused.  First round fails, second round is ready.
        disabled = _PublishButton("round-1", attributes={"is-publish": "false"})
        ready = _PublishButton("round-2")
        page = _CyclingPage(
            [disabled, ready],
            url=PUBLISH_URL,
            selectors={LOGIN_BOX: FakeLocator("login-box", count=0)},
        )
        clock = FakeClock()

        with clock.patch(xhs_main, publish_timeout):
            budget = publish_timeout.PublishTimeoutBudget("小红书")
            asyncio.run(
                xhs_main._wait_for_arm(
                    page, budget=budget, mode="local", publish_clicked=False
                )
            )

        self.assertEqual(page.publish_locator_calls, 2)
        self.assertEqual(clock.sleep_calls, [1.0])
        self.assertEqual(ready.click_count, 0)
        self.assertEqual(page.mouse.down_count, 0)

    def test_window_exhaustion_is_a_definite_non_publish(self):
        page = _button_page(FakeLocator("absent", count=0))
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout):
            budget = publish_timeout.PublishTimeoutBudget("小红书")
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(
                    xhs_main._wait_for_arm(
                        page, budget=budget, mode="local", publish_clicked=False
                    )
                )

        self.assertIn("尚未点击发布", str(ctx.exception))
        self.assertNotIsInstance(ctx.exception, PublishResultUnknownError)
        self.assertAlmostEqual(sum(clock.sleep_calls), 60.0)
        self.assertEqual(page.mouse.down_count, 0)

    def test_budget_exhaustion_during_arm_is_a_definite_non_publish(self):
        page = _button_page(FakeLocator("absent", count=0))
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout):
            budget = publish_timeout.PublishTimeoutBudget("小红书")
            budget.deadline = clock.monotonic() + 3.0
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(
                    xhs_main._wait_for_arm(
                        page, budget=budget, mode="local", publish_clicked=False
                    )
                )

        self.assertIn("尚未点击发布", str(ctx.exception))
        self.assertNotIsInstance(ctx.exception, PublishResultUnknownError)
        self.assertAlmostEqual(sum(clock.sleep_calls), 3.0)
        self.assertEqual(page.mouse.down_count, 0)

    def test_login_hit_during_arm_exits_10_without_dispatch(self):
        page = _button_page(FakeLocator("absent", count=0), url=LOGIN_URL)
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout):
            budget = publish_timeout.PublishTimeoutBudget("小红书")
            with self.assertRaises(LoginRequiredError) as ctx:
                asyncio.run(
                    xhs_main._wait_for_arm(
                        page, budget=budget, mode="local", publish_clicked=False
                    )
                )

        self.assertEqual(ctx.exception.reason, "login")
        self.assertIs(ctx.exception.publish_attempted, False)
        self.assertEqual(clock.sleep_calls, [])
        self.assertEqual(page.mouse.down_count, 0)

    def test_ready_button_cannot_bypass_an_exhausted_budget(self):
        page = _button_page()
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout):
            budget = publish_timeout.PublishTimeoutBudget("小红书")
            budget.deadline = clock.monotonic() - 1
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(
                    xhs_main._wait_for_arm(
                        page, budget=budget, mode="local", publish_clicked=False
                    )
                )

        self.assertIn("尚未点击发布", str(ctx.exception))
        self.assertNotIsInstance(ctx.exception, PublishResultUnknownError)
        self.assertEqual(page.mouse.down_count, 0)


# ---------------------------------------------------------------------------
# 2. FIRE: at most one dispatch, definite/possible split
# ---------------------------------------------------------------------------


class _FailUpMouse(RecordingMouse):
    """Mouse whose release raises after the press landed (maybe-dispatched)."""

    def __init__(self, page: RecordingPage, *, url: str | None = None) -> None:
        super().__init__()
        self._page = page
        self._url = url

    async def up(self, **kwargs) -> None:
        await super().up(**kwargs)
        if self._url is not None:
            self._page.url = self._url
            self._page.main_frame.url = self._url
        raise RuntimeError("dispatch channel lost after down")


class _FailBeforeSubmit(Humanizer):
    async def before_submit(self) -> None:
        raise RuntimeError("pre-submit pause failed")


class FireTests(unittest.TestCase):
    def _budget(self) -> publish_timeout.PublishTimeoutBudget:
        return publish_timeout.PublishTimeoutBudget("小红书")

    def test_ready_button_dispatches_exactly_once(self):
        page = _button_page()
        humanizer = _humanizer(page)

        asyncio.run(
            xhs_main._fire_publish(
                page, budget=self._budget(), humanizer=humanizer, mode="local"
            )
        )

        self.assertEqual(page.mouse.down_count, 1)
        self.assertEqual(page.mouse.up_count, 1)
        # 人类化点击走坐标，不调用 locator.click()。
        self.assertEqual(page.locator(PUBLISH_SELECTOR).click_count, 0)

    def test_pre_dispatch_failure_is_definitely_not_dispatched(self):
        page = _button_page()
        humanizer = _FailBeforeSubmit(page, sleep=_noop_async_sleep)

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(
                xhs_main._fire_publish(
                    page, budget=self._budget(), humanizer=humanizer, mode="local"
                )
            )

        self.assertNotIsInstance(ctx.exception, PublishResultUnknownError)
        self.assertEqual(page.mouse.down_count, 0)

    def test_not_ready_at_fire_time_is_exit_1(self):
        page = _button_page(_PublishButton("disabled", enabled=False))
        humanizer = _humanizer(page)

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(
                xhs_main._fire_publish(
                    page, budget=self._budget(), humanizer=humanizer, mode="local"
                )
            )

        self.assertNotIsInstance(ctx.exception, PublishResultUnknownError)
        self.assertEqual(page.mouse.down_count, 0)

    def test_post_down_failure_is_result_unknown_with_no_second_click(self):
        page = _button_page()
        page.mouse = _FailUpMouse(page)
        humanizer = _humanizer(page)

        with self.assertRaises(PublishResultUnknownError):
            asyncio.run(
                xhs_main._fire_publish(
                    page, budget=self._budget(), humanizer=humanizer, mode="local"
                )
            )

        self.assertEqual(page.mouse.down_count, 1)
        self.assertEqual(page.locator(PUBLISH_SELECTOR).click_count, 0)

    def test_post_down_login_hit_is_10_with_publish_attempted(self):
        page = _button_page()
        page.mouse = _FailUpMouse(page, url=LOGIN_URL)
        humanizer = _humanizer(page)

        with self.assertRaises(LoginRequiredError) as ctx:
            asyncio.run(
                xhs_main._fire_publish(
                    page, budget=self._budget(), humanizer=humanizer, mode="local"
                )
            )

        self.assertEqual(ctx.exception.reason, "login")
        self.assertIs(ctx.exception.publish_attempted, True)
        self.assertEqual(page.mouse.down_count, 1)

    def test_post_down_verification_hit_is_10_with_reason(self):
        page = _button_page()
        page.mouse = _FailUpMouse(page, url=VERIFICATION_URL)
        humanizer = _humanizer(page)

        with self.assertRaises(LoginRequiredError) as ctx:
            asyncio.run(
                xhs_main._fire_publish(
                    page, budget=self._budget(), humanizer=humanizer, mode="local"
                )
            )

        self.assertEqual(ctx.exception.reason, "verification")
        self.assertIs(ctx.exception.publish_attempted, True)

    def test_pre_dispatch_failure_on_login_page_stays_exit_1(self):
        # 未派发的异常不能被页面分类抬成 10：C1/C2/C3 才是派发前的检查点。
        page = _button_page(url=LOGIN_URL)
        humanizer = _FailBeforeSubmit(page, sleep=_noop_async_sleep)

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(
                xhs_main._fire_publish(
                    page, budget=self._budget(), humanizer=humanizer, mode="local"
                )
            )

        self.assertNotIsInstance(ctx.exception, LoginRequiredError)
        self.assertEqual(page.mouse.down_count, 0)

    def test_budget_expiring_during_before_submit_blocks_the_dispatch(self):
        page = _button_page()
        clock = FakeClock()

        class _Expiring(Humanizer):
            async def before_submit(self) -> None:
                clock.advance(901)

        with clock.patch(xhs_main, publish_timeout):
            budget = publish_timeout.PublishTimeoutBudget("小红书")
            humanizer = _Expiring(page, sleep=_noop_async_sleep)
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(
                    xhs_main._fire_publish(
                        page, budget=budget, humanizer=humanizer, mode="local"
                    )
                )

        self.assertIn("尚未点击发布", str(ctx.exception))
        self.assertNotIsInstance(ctx.exception, PublishResultUnknownError)
        self.assertEqual(page.mouse.down_count, 0)


# ---------------------------------------------------------------------------
# 3. OBSERVE: URL-only result, C4 first, 15s window
# ---------------------------------------------------------------------------


class ObserveTests(unittest.TestCase):
    def _budget(self):
        return publish_timeout.PublishTimeoutBudget("小红书")

    def test_leaving_the_publish_path_is_success(self):
        page = RecordingPage(url=SUCCESS_URL)
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout):
            asyncio.run(
                xhs_main._observe_publish(
                    page,
                    budget=self._budget(),
                    publish_clicked=True,
                    mode="local",
                )
            )

        self.assertEqual(clock.sleep_calls, [])

    def test_query_strings_do_not_decide_the_result(self):
        # 只读 path：query 里带着 /publish/publish 也算成功离开。
        page = RecordingPage(
            url=f"{SUCCESS_URL}?next=/publish/publish"
        )
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout):
            asyncio.run(
                xhs_main._observe_publish(
                    page,
                    budget=self._budget(),
                    publish_clicked=True,
                    mode="local",
                )
            )

        self.assertEqual(clock.sleep_calls, [])

    def test_fifteen_seconds_on_the_page_is_result_unknown(self):
        page = RecordingPage(url=PUBLISH_URL)
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout):
            with self.assertRaises(PublishResultUnknownError):
                asyncio.run(
                    xhs_main._observe_publish(
                        page,
                        budget=self._budget(),
                        publish_clicked=True,
                        mode="local",
                    )
                )

        self.assertAlmostEqual(sum(clock.sleep_calls), 15.0)
        self.assertTrue(all(delay == 0.5 for delay in clock.sleep_calls))

    def test_login_page_is_10_with_publish_attempted(self):
        page = RecordingPage(url=LOGIN_URL)
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout):
            with self.assertRaises(LoginRequiredError) as ctx:
                asyncio.run(
                    xhs_main._observe_publish(
                        page,
                        budget=self._budget(),
                        publish_clicked=True,
                        mode="local",
                    )
                )

        self.assertEqual(ctx.exception.reason, "login")
        self.assertIs(ctx.exception.publish_attempted, True)
        self.assertEqual(clock.sleep_calls, [])

    def test_verification_page_is_10_with_publish_attempted(self):
        page = RecordingPage(url=VERIFICATION_URL)
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout):
            with self.assertRaises(LoginRequiredError) as ctx:
                asyncio.run(
                    xhs_main._observe_publish(
                        page,
                        budget=self._budget(),
                        publish_clicked=True,
                        mode="local",
                    )
                )

        self.assertEqual(ctx.exception.reason, "verification")
        self.assertIs(ctx.exception.publish_attempted, True)

    def test_classification_wins_even_with_an_exhausted_budget(self):
        page = RecordingPage(url=LOGIN_URL)
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout):
            budget = publish_timeout.PublishTimeoutBudget("小红书")
            budget.deadline = clock.monotonic() - 1
            with self.assertRaises(LoginRequiredError) as ctx:
                asyncio.run(
                    xhs_main._observe_publish(
                        page,
                        budget=budget,
                        publish_clicked=True,
                        mode="local",
                    )
                )

        self.assertEqual(ctx.exception.reason, "login")
        self.assertIs(ctx.exception.publish_attempted, True)

    def test_budget_exhaustion_after_dispatch_is_9(self):
        page = RecordingPage(url=PUBLISH_URL)
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout):
            budget = publish_timeout.PublishTimeoutBudget("小红书")
            budget.deadline = clock.monotonic() - 1
            with self.assertRaises(PublishResultUnknownError):
                asyncio.run(
                    xhs_main._observe_publish(
                        page,
                        budget=budget,
                        publish_clicked=True,
                        mode="local",
                    )
                )

        self.assertEqual(clock.sleep_calls, [])

    def test_url_read_failure_is_never_reported_as_success(self):
        class BrokenUrlPage:
            main_frame = None

            @property
            def url(self):
                raise RuntimeError("navigation in progress")

        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout):
            with self.assertRaises(PublishResultUnknownError):
                asyncio.run(
                    xhs_main._observe_publish(
                        BrokenUrlPage(),
                        budget=publish_timeout.PublishTimeoutBudget("小红书"),
                        publish_clicked=True,
                        mode="local",
                    )
                )

        self.assertAlmostEqual(sum(clock.sleep_calls), 15.0)


# ---------------------------------------------------------------------------
# 4. Entry points: --no-publish, C3 and the success exit
# ---------------------------------------------------------------------------


class _QuietHumanizer(Humanizer):
    """Behaviour layer with real sequencing but no wall-clock pauses."""

    def __init__(self, page, *, profile=None, rng=None, sleep=None):
        kwargs = {"sleep": _noop_async_sleep}
        if profile is not None:
            kwargs["profile"] = profile
        if rng is not None:
            kwargs["rng"] = rng
        super().__init__(page, **kwargs)


class _SuccessMouse(RecordingMouse):
    def __init__(self, page: RecordingPage) -> None:
        super().__init__()
        self._page = page

    async def up(self, **kwargs) -> None:
        await super().up(**kwargs)
        self._page.url = SUCCESS_URL
        self._page.main_frame.url = SUCCESS_URL


class SubmitEntryPointTests(unittest.TestCase):
    def test_no_publish_runs_to_arm_and_skips_not_before(self):
        button = _PublishButton()
        page = _note_page(button)
        app = _note_app(no_publish=True)
        app.publish_not_before = "2030-01-01T00:00:00"

        not_before = AsyncMock(side_effect=AssertionError("dry run must skip"))
        with (
            patch.object(xhs_main, "Humanizer", _QuietHumanizer),
            patch.object(
                publish_timeout, "wait_until_publish_allowed", new=not_before
            ),
        ):
            asyncio.run(app.upload_note_content(page, mode="local"))

        not_before.assert_not_awaited()
        self.assertGreaterEqual(button.box_calls, 1)
        self.assertEqual(page.mouse.down_count, 0)
        self.assertEqual(button.click_count, 0)

    def test_no_publish_arm_not_ready_is_exit_1(self):
        page = _note_page(_PublishButton("disabled", enabled=False))
        app = _note_app(no_publish=True)
        clock = FakeClock()

        with (
            patch.object(xhs_main, "Humanizer", _QuietHumanizer),
            clock.patch(xhs_main, publish_timeout),
            self.assertRaises(RuntimeError) as ctx,
        ):
            asyncio.run(app.upload_note_content(page, mode="local"))

        self.assertIn("尚未点击发布", str(ctx.exception))
        self.assertAlmostEqual(sum(clock.sleep_calls), 60.0)
        self.assertEqual(page.mouse.down_count, 0)

    def test_c3_runs_after_not_before_and_before_arm(self):
        button = _PublishButton()
        page = _note_page(button)
        app = _note_app(no_publish=False)

        async def expire_session(*_args, **_kwargs):
            page.url = LOGIN_URL
            page.main_frame.url = LOGIN_URL

        with (
            patch.object(xhs_main, "Humanizer", _QuietHumanizer),
            patch.object(
                publish_timeout,
                "wait_until_publish_allowed",
                new=expire_session,
            ),
            self.assertRaises(LoginRequiredError) as ctx,
        ):
            asyncio.run(app.upload_note_content(page, mode="local"))

        self.assertEqual(ctx.exception.reason, "login")
        self.assertIs(ctx.exception.publish_attempted, False)
        # C3 在 ARM 之前：按钮从未被解析/命中。
        self.assertEqual(button.box_calls, 0)
        self.assertEqual(page.mouse.down_count, 0)

    def test_successful_publish_returns_after_exactly_one_dispatch(self):
        button = _PublishButton()
        page = _note_page(button)
        page.mouse = _SuccessMouse(page)
        app = _note_app(no_publish=False)

        async def fake_wait(*_args, **_kwargs):
            return None

        with (
            patch.object(xhs_main, "Humanizer", _QuietHumanizer),
            patch.object(
                publish_timeout, "wait_until_publish_allowed", new=fake_wait
            ),
        ):
            asyncio.run(app.upload_note_content(page, mode="local"))

        self.assertEqual(page.mouse.down_count, 1)
        self.assertEqual(page.mouse.up_count, 1)
        self.assertEqual(button.click_count, 0)


# ---------------------------------------------------------------------------
# 5. Zero text scanning in the submit phases
# ---------------------------------------------------------------------------


class NoTextScanningTests(unittest.TestCase):
    HELPERS = (
        xhs_main._arm_ready,
        xhs_main._wait_for_arm,
        xhs_main._fire_publish,
        xhs_main._observe_publish,
    )
    FORBIDDEN = (
        "inner_text",
        "text_content",
        "get_by_text",
        "toast",
        "限流",
        "拒绝",
        "关键词",
        "publish/success",
        "_XHS_PUBLISH_FAILURE_KEYWORDS",
    )

    def test_submit_helpers_never_scan_copy(self):
        for helper in self.HELPERS:
            source = inspect.getsource(helper)
            for needle in self.FORBIDDEN:
                with self.subTest(helper=helper.__name__, needle=needle):
                    self.assertNotIn(needle, source)

    def test_module_has_no_publish_keyword_tables(self):
        source = Path(xhs_main.__file__).read_text(encoding="utf-8")
        names = {
            node.targets[0].id
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
        }
        for forbidden in (
            "_XHS_PUBLISH_FAILURE_KEYWORDS",
            "_XHS_RATE_LIMIT_KEYWORDS",
            "_XHS_TOAST_SELECTORS",
        ):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, names)


# ---------------------------------------------------------------------------
# 6. stderr machine signal (only exit 10 after dispatch)
# ---------------------------------------------------------------------------


class CliPublishAttemptedSignalTests(unittest.TestCase):
    def _run(self, error: BaseException) -> tuple[int, str]:
        async def dispatch(_args):
            raise error

        stderr = io.StringIO()
        with (
            patch.object(sau_cli, "dispatch", new=dispatch),
            patch.object(sau_cli, "credentials_conflict", return_value=False),
            redirect_stderr(stderr),
        ):
            code = sau_cli.main(["xiaohongshu", "check"])
        return code, stderr.getvalue()

    def test_after_dispatch_prints_a_standalone_fixed_token(self):
        code, stderr = self._run(
            LoginRequiredError(
                "小红书登录态无效：请重新扫码后重试。",
                reason="login",
                publish_attempted=True,
            )
        )

        self.assertEqual(code, 10)
        lines = stderr.rstrip("\n").splitlines()
        self.assertEqual(lines[-1], "publish_attempted=true")
        self.assertIn("登录态无效", lines[0])

    def test_before_dispatch_prints_nothing_extra(self):
        code, stderr = self._run(
            LoginRequiredError("登录状态已失效。", publish_attempted=False)
        )

        self.assertEqual(code, 10)
        self.assertNotIn("publish_attempted=true", stderr)
        self.assertEqual(stderr.count("\n"), 1)


if __name__ == "__main__":
    unittest.main()
