# -*- coding: utf-8 -*-
"""TikTok exit-code contract for the publish stage (ticket 11).

All tests are offline: in-memory page/locator doubles, no browser, no network.
"""

from __future__ import annotations

import asyncio
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import AsyncMock, patch

from patchright.async_api import TimeoutError as PlaywrightTimeoutError

import sau_cli
from uploader.tk_uploader import main_chrome as tk_main
from uploader.tk_uploader.main_chrome import TiktokVideo
from utils.errors import LoginRequiredError, PublishResultUnknownError

CONTENT_URL = "https://www.tiktok.com/tiktokstudio/content"
UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload"
LOGIN_URL = "https://www.tiktok.com/login?lang=en"


class _FakeLocator:
    """The publish button; ``nth`` keeps pointing at the same fake button."""

    def __init__(
        self,
        *,
        click_error: BaseException | None = None,
        hover_error: BaseException | None = None,
    ) -> None:
        self.click_error = click_error
        self.hover_error = hover_error
        self.click_calls = 0

    @property
    def first(self):
        return self

    def nth(self, _index: int):
        return self

    async def count(self) -> int:
        return 1

    async def hover(self) -> None:
        """Platform click entry hovers before clicking (spec §2.5.1)."""
        if self.hover_error is not None:
            raise self.hover_error

    async def click(self) -> None:
        self.click_calls += 1
        if self.click_error is not None:
            raise self.click_error


class _FakeLocatorBase:
    def __init__(self, button: _FakeLocator) -> None:
        self.button = button

    def locator(self, _selector: str) -> _FakeLocator:
        return self.button


class _CandidateLocator:
    """Locator double that can be present/absent and record clicks."""

    def __init__(
        self,
        *,
        count: int = 1,
        visible: bool = True,
        click_error: BaseException | None = None,
    ) -> None:
        self._count = count
        self._visible = visible
        self.click_error = click_error
        self.click_calls = 0

    @property
    def first(self):
        return self

    @property
    def last(self):
        return self

    def nth(self, _index: int):
        return self

    async def count(self) -> int:
        return self._count

    async def is_visible(self) -> bool:
        return self._visible

    async def is_enabled(self) -> bool:
        return True

    async def hover(self) -> None:
        """Platform click entry hovers before clicking (spec §2.5.1)."""
        return None

    async def click(self) -> None:
        self.click_calls += 1
        if self.click_error is not None:
            raise self.click_error


class _CandidateBase:
    def __init__(
        self,
        by_selector: dict[str, _CandidateLocator],
        by_role: dict[str, _CandidateLocator] | None = None,
    ) -> None:
        self._by_selector = by_selector
        self._by_role = by_role or {}

    def locator(self, selector: str) -> _CandidateLocator:
        return self._by_selector.get(selector, _CandidateLocator(count=0))

    def get_by_role(self, role: str, name=None) -> _CandidateLocator:
        key = getattr(name, "pattern", name)
        return self._by_role.get(
            f"{role}:{key}", _CandidateLocator(count=0)
        )


class _Clock:
    """Mutable monotonic clock so async internals cannot consume the values."""

    def __init__(self, value: float = 500.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def expire(self) -> None:
        self.value = 1000.0


class _FakePage:
    """Scripted ``wait_for_url``; each outcome is consumed in order.

    ``"<url>"`` / ``None``  → success (optionally changing ``page.url``).
    ``("timeout", url)``   → raise the Playwright timeout.
    ``BaseException``      → raise it as a page/context failure.
    """

    def __init__(
        self, *, url: str = UPLOAD_URL, wait_outcomes=(), on_timeout=None
    ) -> None:
        self.url = url
        self.wait_calls = 0
        self.wait_timeouts: list[int] = []
        self.on_timeout = on_timeout
        self._outcomes = list(wait_outcomes)

    async def wait_for_url(self, _url: str, timeout: int | None = None) -> None:
        self.wait_calls += 1
        self.wait_timeouts.append(timeout)
        outcome = (
            self._outcomes.pop(0) if self._outcomes else ("timeout", None)
        )
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, tuple) and outcome[0] == "timeout":
            if outcome[1] is not None:
                self.url = outcome[1]
            if self.on_timeout is not None:
                self.on_timeout()
            raise PlaywrightTimeoutError("wait_for_url timed out")
        if isinstance(outcome, str):
            self.url = outcome


class _DialogNode:
    def __init__(self, dialog: _CandidateLocator) -> None:
        self.dialog = dialog

    async def is_visible(self) -> bool:
        return await self.dialog.is_visible()

    def get_by_role(self, role: str, name=None):
        if role == "button":
            return self.dialog
        return _CandidateLocator(count=0)


class _DialogList:
    def __init__(self, nodes) -> None:
        self.nodes = nodes

    async def count(self) -> int:
        return len(self.nodes)

    def nth(self, index: int):
        return self.nodes[index]

    async def is_visible(self) -> bool:
        return True


class _DialogScope:
    def __init__(self, dialog: _CandidateLocator) -> None:
        self.dialog = dialog

    async def count(self) -> int:
        return await self.dialog.count()

    def nth(self, _index: int):
        return _DialogNode(self.dialog)

    async def is_visible(self) -> bool:
        return await self.dialog.is_visible()

    def get_by_role(self, role: str, name=None):
        if role == "button":
            return self.dialog
        return _CandidateLocator(count=0)


class _MultiDialogPage(_FakePage):
    def __init__(self, nodes, **kwargs) -> None:
        super().__init__(**kwargs)
        self.nodes = nodes

    def locator(self, selector: str):
        if selector == '[role="dialog"]':
            return _DialogList(self.nodes)
        return _CandidateLocator(count=0)


class _LateDialogLocator(_CandidateLocator):
    """Confirmation dialog that only appears after the first poll attempt.

    TikTok renders the ``Post now`` dialog a beat after the publish click, so
    the first ``wait_for_url`` timeout can legitimately see no dialog at all.
    """

    def __init__(self, *, absent_count_calls: int) -> None:
        super().__init__(count=0)
        self._absent_count_calls = absent_count_calls
        self.count_calls = 0

    async def count(self) -> int:
        self.count_calls += 1
        return 0 if self.count_calls <= self._absent_count_calls else 1


class _FlakyDialogLocator(_CandidateLocator):
    """Dialog whose confirmation click fails a fixed number of times."""

    def __init__(self, *, failures: int) -> None:
        super().__init__()
        self.remaining_failures = failures

    async def click(self) -> None:
        self.click_calls += 1
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            raise RuntimeError("dialog click failed")


class _LateButtonLocator(_CandidateLocator):
    """Dialog that is visible at once; its exact-name button renders later."""

    def __init__(self, *, absent_count_calls: int) -> None:
        super().__init__()
        self._absent_count_calls = absent_count_calls
        self.count_calls = 0

    async def count(self) -> int:
        self.count_calls += 1
        return 0 if self.count_calls <= self._absent_count_calls else 1


class _PostNowPage(_FakePage):
    """Publish page whose success URL arrives after a ``Post now`` dialog."""

    def __init__(self, dialog: _CandidateLocator, **kwargs) -> None:
        super().__init__(**kwargs)
        self.dialog = dialog

    def locator(self, selector: str):
        if selector == '[role="dialog"]':
            return _DialogScope(self.dialog)
        return _CandidateLocator(count=0)

    def get_by_role(self, _role: str, name=None):
        return _CandidateLocator(count=0)


class _LateButtonDialogNode(_DialogNode):
    """A dialog that is visible immediately while its button appears later."""

    def __init__(self, dialog: _CandidateLocator, button: _CandidateLocator) -> None:
        super().__init__(dialog)
        self.button = button

    def get_by_role(self, role: str, name=None):
        if role == "button":
            return self.button
        return _CandidateLocator(count=0)


class _LateButtonPage(_FakePage):
    """Publish page whose ``Post now`` button renders a beat after its dialog."""

    def __init__(
        self, dialog: _CandidateLocator, button: _CandidateLocator, **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self._node = _LateButtonDialogNode(dialog, button)

    def locator(self, selector: str):
        if selector == '[role="dialog"]':
            return _DialogList([self._node])
        return _CandidateLocator(count=0)

    def get_by_role(self, _role: str, name=None):
        return _CandidateLocator(count=0)


def _video() -> TiktokVideo:
    return TiktokVideo("标题", "/tmp/demo.mp4", [], 0, None)


def _run_cli(dispatch) -> tuple[int, str, str]:
    with patch.object(sau_cli, "dispatch", new=dispatch):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(
            io.StringIO()
        ) as err:
            code = sau_cli.main(["tiktok", "check"])
    return code, out.getvalue(), err.getvalue()


def _returning(result: int = 0):
    async def _dispatch(_args):
        return result

    return _dispatch


def _raising(error: BaseException):
    async def _dispatch(_args):
        raise error

    return _dispatch


class CliExitCodeTests(unittest.TestCase):
    def test_success_maps_to_0(self):
        code, _, _ = _run_cli(_returning(0))
        self.assertEqual(code, 0)

    def test_generic_failure_maps_to_1(self):
        code, _, err = _run_cli(_raising(RuntimeError("boom")))
        self.assertEqual(code, 1)
        self.assertIn("boom", err)

    def test_publish_result_unknown_maps_to_9_and_prints_the_exception_text(self):
        message = "发布结果未知：仅供测试的核验说明。"
        code, _, err = _run_cli(
            _raising(PublishResultUnknownError(message))
        )
        self.assertEqual(code, 9)
        self.assertIn(message, err)

    def test_embedded_captcha_is_not_recognized_and_stays_exit_1(self):
        # Known blind spot (spec §6.4): only URL markers raise 10.  A captcha
        # rendered inside the form leaves the URL unchanged, so it is not a
        # login redirect and a pre-click failure stays a normal exit 1.
        video = _video()
        page = _FakePage(url=UPLOAD_URL)
        tk_main._raise_if_login_required(page)

        async def _dispatch(_args):
            await video.click_publish(page, deadline=999.0, multilogin=True)
            return 0

        with patch.object(tk_main.time, "monotonic", return_value=1000.0):
            code, _, err = _run_cli(_dispatch)

        self.assertEqual(code, 1)
        self.assertNotIn("禁止自动重发", err)

    def test_login_required_maps_to_10(self):
        code, _, _ = _run_cli(_raising(LoginRequiredError("需要登录")))
        self.assertEqual(code, 10)


class LoginRequiredMessageTests(unittest.TestCase):
    def test_post_dispatch_login_message_warns_about_a_duplicate(self):
        page = _FakePage(url=LOGIN_URL)

        with self.assertRaises(LoginRequiredError) as ctx:
            tk_main._raise_if_login_required(page, publish_attempted=True)

        message = str(ctx.exception)
        self.assertIn("请在 Multilogin 应用中登录 Profile 后重试", message)
        self.assertIn("发布点击已发出", message)
        self.assertIn("作品列表", message)
        self.assertIs(ctx.exception.publish_attempted, True)

    def test_pre_dispatch_login_message_has_no_duplicate_warning(self):
        page = _FakePage(url=LOGIN_URL)

        with self.assertRaises(LoginRequiredError) as ctx:
            tk_main._raise_if_login_required(page)

        message = str(ctx.exception)
        self.assertIn("请在 Multilogin 应用中登录 Profile 后重试", message)
        self.assertNotIn("发布点击已发出", message)
        self.assertIs(ctx.exception.publish_attempted, False)


class ClickPublishTests(unittest.TestCase):
    def test_success_returns_normally(self):
        video = _video()
        button = _FakeLocator()
        video.locator_base = _FakeLocatorBase(button)
        page = _FakePage(wait_outcomes=[CONTENT_URL])

        with patch.object(tk_main.asyncio, "sleep", AsyncMock()) as sleep:
            asyncio.run(video.click_publish(page, multilogin=True))

        self.assertEqual(button.click_calls, 1)
        self.assertEqual(page.wait_calls, 1)
        self.assertEqual(page.url, CONTENT_URL)
        sleep.assert_not_awaited()

    def test_click_failure_is_reported_immediately_without_retry(self):
        """A failure before the click is dispatched is a hard failure.

        Publishing is a single dispatch: a humanized click that raises before
        ``mouse.down`` must surface as the original error (exit 1), never be
        retried in a loop.
        """
        video = _video()
        button = _FakeLocator(hover_error=RuntimeError("boom"))
        video.locator_base = _FakeLocatorBase(button)
        page = _FakePage()

        with patch.object(tk_main.asyncio, "sleep", AsyncMock()):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(video.click_publish(page, multilogin=True))

        self.assertEqual(button.click_calls, 0)
        self.assertEqual(page.wait_calls, 0)
        self.assertIn("boom", str(ctx.exception))

    def test_maybe_dispatched_failure_is_not_reclicked(self):
        """``HUMANIZE=0`` marks a click raise as maybe-dispatched.

        The raise may have reached the page, so the loop only waits for the
        success URL and never re-dispatches; the iteration cap ends it.
        """
        video = _video()
        button = _FakeLocator(click_error=RuntimeError("boom"))
        video.locator_base = _FakeLocatorBase(button)
        page = _FakePage()

        with patch.object(tk_main.asyncio, "sleep", AsyncMock()):
            with self.assertRaises(PublishResultUnknownError):
                asyncio.run(video.click_publish(page, multilogin=True))

        self.assertEqual(button.click_calls, 1)
        self.assertLessEqual(
            page.wait_calls, tk_main.TIKTOK_PUBLISH_MAX_LOOP_ITERATIONS + 1
        )

    def test_never_clicked_deadline_is_exit_1_not_9(self):
        video = _video()
        button = _FakeLocator()
        video.locator_base = _FakeLocatorBase(button)
        page = _FakePage()

        async def _dispatch(_args):
            await video.click_publish(page, deadline=999.0, multilogin=True)
            return 0

        with patch.object(tk_main.time, "monotonic", return_value=1000.0):
            code, _, err = _run_cli(_dispatch)

        self.assertEqual(code, 1)
        self.assertNotIn("禁止自动重发", err)
        self.assertIn("未发布", err)
        self.assertEqual(button.click_calls, 0)
        self.assertEqual(page.wait_calls, 0)

    def test_clicked_then_deadline_is_publish_result_unknown_exit_9(self):
        video = _video()
        button = _FakeLocator()
        video.locator_base = _FakeLocatorBase(button)
        clock = _Clock()
        page = _FakePage(
            wait_outcomes=[("timeout", None)], on_timeout=clock.expire
        )

        async def _dispatch(_args):
            await video.click_publish(page, deadline=999.0, multilogin=True)
            return 0

        sleep = AsyncMock()
        with (
            patch.object(tk_main.time, "monotonic", clock),
            patch.object(tk_main.asyncio, "sleep", sleep),
        ):
            code, _, err = _run_cli(_dispatch)

        self.assertEqual(code, 9)
        self.assertIn("禁止自动重发", err)
        self.assertIn("Content/Posts", err)
        self.assertEqual(button.click_calls, 1)
        self.assertEqual(sleep.await_count, 1)

    def test_login_redirect_at_deadline_wins_over_unknown(self):
        video = _video()
        button = _FakeLocator()
        video.locator_base = _FakeLocatorBase(button)
        clock = _Clock()
        page = _FakePage(
            wait_outcomes=[("timeout", LOGIN_URL)], on_timeout=clock.expire
        )

        async def _dispatch(_args):
            await video.click_publish(page, deadline=999.0, multilogin=True)
            return 0

        with (
            patch.object(tk_main.time, "monotonic", clock),
            patch.object(tk_main.asyncio, "sleep", AsyncMock()),
        ):
            code, _, err = _run_cli(_dispatch)

        self.assertEqual(code, 10)
        self.assertNotIn("禁止自动重发", err)
        self.assertEqual(button.click_calls, 1)

    def test_clicked_then_page_closed_is_exit_9_without_spinning(self):
        video = _video()
        button = _FakeLocator()
        video.locator_base = _FakeLocatorBase(button)
        page = _FakePage(
            wait_outcomes=[
                RuntimeError("Target page, context or browser has been closed")
            ]
        )

        async def _dispatch(_args):
            await video.click_publish(page, deadline=999.0, multilogin=True)
            return 0

        sleep = AsyncMock()
        with (
            patch.object(tk_main.time, "monotonic", return_value=500.0),
            patch.object(tk_main.asyncio, "sleep", sleep),
        ):
            code, _, err = _run_cli(_dispatch)

        self.assertEqual(code, 9)
        self.assertIn("禁止自动重发", err)
        self.assertEqual(button.click_calls, 1)
        self.assertEqual(page.wait_calls, 1)
        sleep.assert_not_awaited()

    def test_publish_button_uses_data_e2e_candidate_first(self):
        primary = _CandidateLocator()
        post_last = _CandidateLocator()
        legacy = _CandidateLocator()
        base = _CandidateBase(
            {
                '[data-e2e="post_video_button"]': primary,
                'button:has-text("Post")': post_last,
                "div.button-group button": legacy,
            }
        )
        video = _video()
        video.locator_base = base
        page = _FakePage(wait_outcomes=[CONTENT_URL])

        asyncio.run(video.click_publish(page, multilogin=True))

        self.assertEqual(primary.click_calls, 1)
        self.assertEqual(post_last.click_calls, 0)
        self.assertEqual(legacy.click_calls, 0)

    def test_publish_button_falls_back_to_exact_role(self):
        primary = _CandidateLocator(count=0)
        role_button = _CandidateLocator()
        base = _CandidateBase(
            {'[data-e2e="post_video_button"]': primary},
            {"button:^(Post|Schedule)$": role_button},
        )
        video = _video()
        video.locator_base = base
        page = _FakePage(wait_outcomes=[CONTENT_URL])

        asyncio.run(video.click_publish(page, multilogin=True))

        self.assertEqual(primary.click_calls, 0)
        self.assertEqual(role_button.click_calls, 1)

    def test_publish_candidates_avoid_substring_and_positional_fallbacks(self):
        descriptions = [
            label for label, _ in tk_main._PUBLISH_BUTTON_CANDIDATES
        ]

        self.assertEqual(
            descriptions,
            [
                "data-e2e=post_video_button",
                "role=button[name=/^(Post|Schedule)$/]",
            ],
        )
        joined = " ".join(descriptions)
        self.assertNotIn("has-text", joined)
        self.assertNotIn("nth(", joined)

    def test_post_now_dialog_is_clicked_once_and_post_is_not_reclicked(self):
        button = _CandidateLocator()
        base = _CandidateBase({"[data-e2e=\"post_video_button\"]": button})
        dialog = _CandidateLocator()
        page = _PostNowPage(
            dialog,
            wait_outcomes=[("timeout", None), ("timeout", None), CONTENT_URL],
        )
        video = _video()
        video.locator_base = base

        with patch.object(tk_main.asyncio, "sleep", AsyncMock()):
            asyncio.run(video.click_publish(page, multilogin=True))

        self.assertEqual(button.click_calls, 1)
        self.assertEqual(dialog.click_calls, 1)

    def test_failed_post_now_click_is_not_retried(self):
        """A confirmation click that raised may have dispatched: latch it.

        The first Post-now click fails (pre- or post-dispatch is unknowable),
        so the loop must not click the confirmation again; it only waits for
        the success URL and ends as result-unknown.
        """
        button = _CandidateLocator()
        base = _CandidateBase({"[data-e2e=\"post_video_button\"]": button})
        dialog = _FlakyDialogLocator(failures=1)
        page = _PostNowPage(
            dialog,
            wait_outcomes=[("timeout", None)] * 3 + [CONTENT_URL],
        )
        video = _video()
        video.locator_base = base

        with patch.object(tk_main.asyncio, "sleep", AsyncMock()):
            asyncio.run(video.click_publish(page, multilogin=True))

        self.assertEqual(button.click_calls, 1)
        self.assertEqual(dialog.click_calls, 1)

    def test_post_now_dialog_that_appears_late_is_still_clicked(self):
        button = _CandidateLocator()
        base = _CandidateBase({"[data-e2e=\"post_video_button\"]": button})
        # The fake page only scripts the role=dialog selector, so the first
        # poll attempt sees no dialog and the second one does.
        dialog = _LateDialogLocator(absent_count_calls=1)
        page = _PostNowPage(
            dialog,
            wait_outcomes=[("timeout", None), ("timeout", None), CONTENT_URL],
        )
        video = _video()
        video.locator_base = base

        with patch.object(tk_main.asyncio, "sleep", AsyncMock()):
            asyncio.run(video.click_publish(page, multilogin=True))

        self.assertEqual(button.click_calls, 1)
        self.assertEqual(dialog.click_calls, 1)

    def test_post_now_dialog_with_a_late_button_is_clicked_once(self):
        """A rendered dialog without its button must not latch.

        The dialog exists on the first poll but its exact-name ``Post now``
        button has not rendered yet.  ``_click_post_now`` returns ``None`` so
        the loop polls again; ``False`` stays reserved for a raised click.
        """
        button = _CandidateLocator()
        base = _CandidateBase({"[data-e2e=\"post_video_button\"]": button})
        dialog = _CandidateLocator()
        late_button = _LateButtonLocator(absent_count_calls=1)
        page = _LateButtonPage(
            dialog,
            late_button,
            wait_outcomes=[("timeout", None), ("timeout", None), CONTENT_URL],
        )
        video = _video()
        video.locator_base = base

        with patch.object(tk_main.asyncio, "sleep", AsyncMock()):
            asyncio.run(video.click_publish(page, multilogin=True))

        self.assertEqual(button.click_calls, 1)
        self.assertEqual(late_button.click_calls, 1)

    def test_confirmation_without_visible_dialog_clicks_nothing(self):
        button = _CandidateLocator()
        base = _CandidateBase({"[data-e2e=\"post_video_button\"]": button})
        dialog = _CandidateLocator(count=0)
        page = _PostNowPage(
            dialog,
            wait_outcomes=[("timeout", None), CONTENT_URL],
        )
        video = _video()
        video.locator_base = base

        with patch.object(tk_main.asyncio, "sleep", AsyncMock()):
            asyncio.run(video.click_publish(page, multilogin=True))

        self.assertEqual(button.click_calls, 1)
        self.assertEqual(dialog.click_calls, 0)

    def test_confirmation_skips_unrelated_top_dialog(self):
        real = _CandidateLocator()
        unrelated = _CandidateLocator(count=0)
        page = _MultiDialogPage(
            [_DialogNode(real), _DialogNode(unrelated)]
        )
        video = _video()

        self.assertTrue(asyncio.run(video._click_post_now(page)))

        self.assertEqual(unrelated.click_calls, 0)
        self.assertEqual(real.click_calls, 1)

    def test_publish_clicks_the_locator_the_readiness_gate_returned(self):
        gated = _CandidateLocator()
        re_resolved = _CandidateLocator()
        video = _video()
        video.locator_base = _CandidateBase(
            {'[data-e2e="post_video_button"]': re_resolved}
        )
        page = _FakePage(wait_outcomes=[CONTENT_URL])

        with patch.object(
            video, "wait_publish_ready", AsyncMock(return_value=gated)
        ):
            asyncio.run(video.click_publish(page, multilogin=True))

        self.assertEqual(gated.click_calls, 1)
        self.assertEqual(re_resolved.click_calls, 0)

    def test_missing_locator_from_the_gate_fails_before_clicking(self):
        video = _video()
        video.locator_base = _CandidateBase(
            {'[data-e2e="post_video_button"]': _CandidateLocator()}
        )
        page = _FakePage()

        with patch.object(
            video, "wait_publish_ready", AsyncMock(return_value=None)
        ), patch.object(tk_main.asyncio, "sleep", AsyncMock()):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(video.click_publish(page, multilogin=True))

        self.assertIn("未点击发布", str(ctx.exception))
        self.assertEqual(page.wait_calls, 0)

    def test_pre_publish_media_deadline_is_exit_1(self):
        video = _video()
        page = _FakePage()

        async def _dispatch(_args):
            await video.wait_media_ready(
                page, deadline=999.0, multilogin=True
            )
            return 0

        with patch.object(tk_main.time, "monotonic", return_value=1000.0):
            code, _, err = _run_cli(_dispatch)

        self.assertEqual(code, 1)
        self.assertNotIn("禁止自动重发", err)



_HUMANIZE_BEFORE = None


def setUpModule():
    """Legacy TikTok fakes model the pre-humanize DOM seam.

    ``HUMANIZE=0`` is the semantic switch for exactly this: one ``insert_text``
    per text field and one ``locator.click`` per click.  The humanized
    behaviour itself is covered by ``tests/test_tiktok_humanize.py``.
    """
    import os

    global _HUMANIZE_BEFORE
    _HUMANIZE_BEFORE = os.environ.get("HUMANIZE")
    os.environ["HUMANIZE"] = "0"


def tearDownModule():
    import os

    if _HUMANIZE_BEFORE is None:
        os.environ.pop("HUMANIZE", None)
    else:
        os.environ["HUMANIZE"] = _HUMANIZE_BEFORE

if __name__ == "__main__":
    unittest.main()
