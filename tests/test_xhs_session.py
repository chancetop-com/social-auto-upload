# -*- coding: utf-8 -*-
"""Platform publish-page probe; full Profile/CLI coverage is in test_xhs_profile_cli."""

from __future__ import annotations

import asyncio
import unittest
from uploader.xiaohongshu_uploader import main as xhs_main

LOGIN_URL = "https://creator.xiaohongshu.com/login?redirect=%2Fpublish"
VERIFICATION_URL = (
    "https://creator.xiaohongshu.com/website-login/captcha?redirectPath=%2Fpublish"
)
PUBLISH_URL = (
    "https://creator.xiaohongshu.com/publish/publish?from=homepage&target=video"
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _AsyncCM:
    def __init__(self, value=None, enter_error: BaseException | None = None) -> None:
        self.value = value
        self.enter_error = enter_error
        self.enter_calls = 0
        self.exit_calls = 0
        self.last_exc: tuple | None = None

    async def __aenter__(self):
        self.enter_calls += 1
        if self.enter_error is not None:
            raise self.enter_error
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        self.exit_calls += 1
        self.last_exc = (exc_type, exc, tb)
        return False


class _ProbeFrame:
    def __init__(self, page: "_ProbePage") -> None:
        self._page = page

    @property
    def url(self) -> str:
        return self._page.url


class _ProbeLocator:
    def __init__(self, count: int) -> None:
        self._count = count

    async def count(self) -> int:
        return self._count

    async def is_visible(self) -> bool:
        return self._count > 0


class _Response:
    def __init__(self, status: int = 200) -> None:
        self.status = status


class _ProbePage:
    """Scripted publish page used by ``probe_session`` tests."""

    def __init__(
        self,
        *,
        final_url: str = PUBLISH_URL,
        status: int = 200,
        goto_error: BaseException | None = None,
        anchor_count: int = 1,
        login_box_count: int = 0,
        anchor_ready_after_waits: int | None = None,
    ) -> None:
        self.url = "about:blank"
        self.main_frame = _ProbeFrame(self)
        self.final_url = final_url
        self.status = status
        self.goto_error = goto_error
        self.anchor_count = anchor_count
        self.anchor_ready_after_waits = anchor_ready_after_waits
        self.login_box_count = login_box_count
        self.goto_calls: list[tuple[str, dict]] = []
        self.wait_timeouts: list[float] = []
        self.close_calls = 0
        self.closed = False

    async def goto(self, url: str, **kwargs):
        self.goto_calls.append((url, kwargs))
        if self.goto_error is not None:
            raise self.goto_error
        self.url = self.final_url
        return _Response(self.status)

    async def wait_for_timeout(self, milliseconds: float) -> None:
        self.wait_timeouts.append(milliseconds)
        if (
            self.anchor_ready_after_waits is not None
            and len(self.wait_timeouts) >= self.anchor_ready_after_waits
        ):
            self.anchor_count = 1

    def locator(self, selector: str) -> _ProbeLocator:
        if "login-box" in selector:
            return _ProbeLocator(self.login_box_count)
        if selector in xhs_main.XHS_LOGIN_POSITIVE_SELECTORS:
            return _ProbeLocator(self.anchor_count)
        # Upload anchors are the union of the positive selectors; unknown
        # selectors default to absent so a test must name its anchor.
        return _ProbeLocator(0)

    async def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class _ProbeContext:
    def __init__(self, page: _ProbePage) -> None:
        self.page = page
        self.new_page_calls = 0

    async def new_page(self) -> _ProbePage:
        self.new_page_calls += 1
        return self.page


# ---------------------------------------------------------------------------
# Publish-page observation
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 2. probe_session: navigate publish page once, classify, check anchor
# ---------------------------------------------------------------------------


class Decision12SessionProbeTests(unittest.TestCase):
    def _probe(self, page: _ProbePage):
        context = _ProbeContext(page)
        result = asyncio.run(xhs_main.probe_session(context))
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(page.close_calls, 1)
        return result

    def test_valid_publish_page_with_attached_anchor(self):
        page = _ProbePage(anchor_count=1)
        self.assertEqual(self._probe(page), ("valid", PUBLISH_URL))
        self.assertEqual(page.goto_calls[0][0], PUBLISH_URL)
        kwargs = page.goto_calls[0][1]
        self.assertEqual(kwargs["wait_until"], "domcontentloaded")
        self.assertGreater(kwargs["timeout"], 0)

    def test_login_path_returns_login(self):
        self.assertEqual(
            self._probe(_ProbePage(final_url=LOGIN_URL))[0], "login"
        )

    def test_verification_path_returns_verification(self):
        self.assertEqual(
            self._probe(_ProbePage(final_url=VERIFICATION_URL))[0],
            "verification",
        )

    def test_redirect_path_query_does_not_trigger_login(self):
        url = (
            "https://creator.xiaohongshu.com/publish/publish"
            "?redirectPath=/login&next=/website-login/captcha"
        )
        self.assertEqual(self._probe(_ProbePage(final_url=url))[0], "valid")

    def test_missing_anchor_is_a_structure_error(self):
        page = _ProbePage(anchor_count=0)
        with self.assertRaisesRegex(RuntimeError, "页面结构异常"):
            asyncio.run(xhs_main.probe_session(_ProbeContext(page)))
        self.assertEqual(page.close_calls, 1)

    def test_slow_anchor_mount_is_polled_not_a_structure_error(self):
        # Real device: upload input mounts ~5s after domcontentloaded.
        page = _ProbePage(anchor_count=0, anchor_ready_after_waits=3)
        self.assertEqual(self._probe(page), ("valid", PUBLISH_URL))
        self.assertGreaterEqual(len(page.wait_timeouts), 3)
        self.assertEqual(
            page.wait_timeouts[-1], xhs_main.XHS_PROBE_POLL_MS
        )

    def test_server_error_is_a_probe_failure(self):
        page = _ProbePage(status=503)
        with self.assertRaises(RuntimeError):
            asyncio.run(xhs_main.probe_session(_ProbeContext(page)))
        self.assertEqual(page.close_calls, 1)

    def test_navigation_error_is_a_probe_failure(self):
        page = _ProbePage(goto_error=RuntimeError("net::ERR_TIMED_OUT"))
        with self.assertRaises(RuntimeError):
            asyncio.run(xhs_main.probe_session(_ProbeContext(page)))
        self.assertEqual(page.close_calls, 1)

    def test_leaving_the_creator_domain_is_a_probe_failure(self):
        page = _ProbePage(final_url="https://example.com/elsewhere")
        with self.assertRaises(RuntimeError):
            asyncio.run(xhs_main.probe_session(_ProbeContext(page)))
        self.assertEqual(page.close_calls, 1)


if __name__ == "__main__":
    unittest.main()
