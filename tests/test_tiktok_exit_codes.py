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

    def __init__(self, *, click_error: BaseException | None = None) -> None:
        self.click_error = click_error
        self.click_calls = 0

    @property
    def first(self):
        return self

    def nth(self, _index: int):
        return self

    async def count(self) -> int:
        return 1

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

    def test_failing_post_now_click_is_attempted_only_once(self):
        button = _CandidateLocator()
        base = _CandidateBase({"[data-e2e=\"post_video_button\"]": button})
        dialog = _CandidateLocator(
            click_error=RuntimeError("dialog click failed")
        )
        page = _PostNowPage(
            dialog,
            # Five timeouts would be five retries if the attempt flag followed
            # the click result instead of the attempt itself.
            wait_outcomes=[("timeout", None)] * 5 + [CONTENT_URL],
        )
        video = _video()
        video.locator_base = base

        with patch.object(tk_main.asyncio, "sleep", AsyncMock()):
            asyncio.run(video.click_publish(page, multilogin=True))

        self.assertEqual(button.click_calls, 1)
        self.assertEqual(dialog.click_calls, 1)

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


if __name__ == "__main__":
    unittest.main()
