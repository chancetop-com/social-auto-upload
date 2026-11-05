# -*- coding: utf-8 -*-
"""Alipay + Weibo Multilogin seam, login detection and CLI wiring (ticket 20).

Covers:
- golden local launch/context/init-script options for both platforms;
- the Multilogin uploader branch only consuming the injected session;
- no cookie I/O and no forbidden Playwright APIs in Multilogin mode;
- ``is_logged_in`` True / False / raise matrices;
- Weibo publish button scrolling into view before the JS click;
- CLI check ``0/10/1/2`` and upload ``0/10/1`` plus Stop ownership.

Everything is offline: no browser is launched and no network is touched.
"""

from __future__ import annotations

import asyncio
import io
import os
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import sau_cli
from sau_commands import alipay as alipay_command
from sau_commands import weibo as weibo_command
from tests.fakes import FakeContext, FakeMultiloginClient, FakePlaywright
from uploader.alipay_uploader import main as alipay_main
from uploader.alipay_uploader.main import (
    ALIPAY_CONTEXT_KWARGS,
    ALIPAY_INIT_SCRIPT,
    ALIPAY_LAUNCH_KWARGS,
    ALIPAY_LIFE_ACCOUNT_URL,
    AlipayVideo,
)
from uploader.weibo_uploader import main as weibo_main
from uploader.weibo_uploader.main import (
    WEIBO_CONTEXT_KWARGS,
    WEIBO_HOME_URL,
    WEIBO_INIT_SCRIPT,
    WEIBO_LAUNCH_KWARGS,
    WeiBoVideo,
)
from utils.browser_session import BrowserSession
from utils.errors import LoginRequiredError
from utils.multilogin import MultiloginTarget

TOKEN = "SENTINEL-MLX-TOKEN-ticket20"

ALIPAY_AVATAR_SELECTOR = 'a:has-text("发布视频")'
WEIBO_AVATAR_SELECTORS = weibo_main.WEIBO_LOGIN_POSITIVE_SELECTORS
WEIBO_PUBLISH_SELECTOR = 'div[class*="_check_2z30i"] button:has(span:text-is("发布"))'
WEIBO_AGAIN_SELECTOR = 'button:has(span:text-is("再发一条视频"))'


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeKeyboard:
    def __init__(self, page: "_FakePage") -> None:
        self.page = page

    async def press(self, key: str) -> None:
        self.page.events.append(("press", key))


class _FakeResponse:
    def __init__(self, status: int | None) -> None:
        self.status = status


class _FakeLocator:
    def __init__(self, page: "_FakePage", selector: str) -> None:
        self.page = page
        self.selector = selector

    @property
    def first(self) -> "_FakeLocator":
        return self

    @property
    def last(self) -> "_FakeLocator":
        return self

    async def count(self) -> int:
        self.page.events.append(("count", self.selector))
        return int(self.page.counts.get(self.selector, 0))

    async def is_visible(self) -> bool:
        self.page.events.append(("is_visible", self.selector))
        return bool(self.page.visible.get(self.selector, False))

    async def is_disabled(self) -> bool:
        return False

    async def wait_for(self, state: str | None = None, timeout: int | None = None) -> None:
        self.page.events.append(("wait_for", self.selector))

    async def click(self, **kwargs) -> None:
        self.page.events.append(("click", self.selector))

    async def evaluate(self, script: str) -> None:
        self.page.events.append(("evaluate", self.selector))

    async def scroll_into_view_if_needed(self, *args, **kwargs) -> None:
        self.page.events.append(("scroll", self.selector))

    def locator(self, selector: str) -> "_FakeLocator":
        return _FakeLocator(self.page, selector)


class _FakePage:
    def __init__(
        self,
        *,
        final_url: str | None = None,
        status: int | None = None,
        goto_error: BaseException | None = None,
        counts: dict[str, int] | None = None,
        visible: dict[str, bool] | None = None,
    ) -> None:
        self.url = "about:blank"
        self.final_url = final_url
        self.status = status
        self.goto_error = goto_error
        self.counts = dict(counts or {})
        self.visible = dict(visible or {})
        self.goto_calls: list[tuple[str, dict]] = []
        self.events: list[tuple] = []
        self.closed = False
        self.keyboard = _FakeKeyboard(self)

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(self, selector)

    def get_by_text(self, text: str, exact: bool = False) -> _FakeLocator:
        return _FakeLocator(self, f"text:{text}:{exact}")

    def get_by_role(self, role: str, name: str | None = None) -> _FakeLocator:
        return _FakeLocator(self, f"role:{role}:{name}")

    async def goto(self, url: str, **kwargs):
        self.goto_calls.append((url, kwargs))
        if self.goto_error is not None:
            raise self.goto_error
        self.url = self.final_url if self.final_url is not None else url
        if self.status is None:
            return None
        return _FakeResponse(self.status)

    async def wait_for_timeout(self, ms: int) -> None:
        self.events.append(("wait", ms))

    async def wait_for_load_state(self, *args, **kwargs) -> None:
        self.events.append(("load_state", args, kwargs))

    async def wait_for_url(self, url: str, **kwargs) -> None:
        self.events.append(("wait_url", url))
        self.url = url

    async def close(self) -> None:
        self.closed = True


class _LoginContext:
    def __init__(self, page: _FakePage, *, cookies: list[dict] | None = None) -> None:
        self.page = page
        self.cookies_list = list(cookies or [])
        self.new_page_calls = 0
        self.cookies_calls = 0

    async def new_page(self) -> _FakePage:
        self.new_page_calls += 1
        return self.page

    async def cookies(self) -> list[dict]:
        self.cookies_calls += 1
        return list(self.cookies_list)


class _RecordingContext:
    """Injected MLX context: records the allowed calls, fails on forbidden ones."""

    def __init__(self, page: _FakePage) -> None:
        self.page = page
        self.new_page_calls = 0
        self.storage_state_calls: list[object] = []
        self.add_init_script_calls = 0
        self.forbidden_calls: list[str] = []

    async def new_page(self) -> _FakePage:
        self.new_page_calls += 1
        return self.page

    async def storage_state(self, *, path=None, **kwargs):
        self.storage_state_calls.append(path)
        return {"cookies": []}

    async def add_init_script(self, *args, **kwargs) -> None:
        self.add_init_script_calls += 1

    async def add_cookies(self, *args, **kwargs) -> None:
        self.forbidden_calls.append("add_cookies")
        raise AssertionError("add_cookies is forbidden")

    async def clear_cookies(self, *args, **kwargs) -> None:
        self.forbidden_calls.append("clear_cookies")
        raise AssertionError("clear_cookies is forbidden")

    async def grant_permissions(self, *args, **kwargs) -> None:
        self.forbidden_calls.append("grant_permissions")
        raise AssertionError("grant_permissions is forbidden")

    async def set_geolocation(self, *args, **kwargs) -> None:
        self.forbidden_calls.append("set_geolocation")
        raise AssertionError("set_geolocation is forbidden")

    async def set_viewport_size(self, *args, **kwargs) -> None:
        self.forbidden_calls.append("set_viewport_size")
        raise AssertionError("set_viewport_size is forbidden")

    async def route(self, *args, **kwargs) -> None:
        self.forbidden_calls.append("route")
        raise AssertionError("route is forbidden")

    async def new_context(self, *args, **kwargs) -> None:
        self.forbidden_calls.append("new_context")
        raise AssertionError("new_context is forbidden")


class _AsyncCM:
    def __init__(self, value=None, enter_error: BaseException | None = None) -> None:
        self.value = value
        self.enter_error = enter_error
        self.enter_calls = 0
        self.exit_calls = 0

    async def __aenter__(self):
        self.enter_calls += 1
        if self.enter_error is not None:
            raise self.enter_error
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        self.exit_calls += 1
        return False


def _make_video(tmp_dir: str, *, platform: str, account_file=None, **kwargs):
    video_path = Path(tmp_dir) / "demo.mp4"
    if not video_path.exists():
        video_path.write_bytes(b"video")
    if platform == "alipay":
        return AlipayVideo(
            title="标题",
            file_path=str(video_path),
            tags=[],
            account_file=account_file,
            **kwargs,
        )
    thumb_path = Path(tmp_dir) / "cover.jpg"
    if not thumb_path.exists():
        thumb_path.write_bytes(b"image")
    return WeiBoVideo(
        title="标题",
        file_path=str(video_path),
        tags=[],
        account_file=account_file,
        thumbnail_path=str(thumb_path),
        **kwargs,
    )


def _run_cli(argv, *, token=TOKEN):
    with patch.dict(os.environ, {"MLX_API_TOKEN": token}):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(
            io.StringIO()
        ) as err:
            code = sau_cli.main(argv)
    return code, out.getvalue(), err.getvalue()


def _target() -> MultiloginTarget:
    return MultiloginTarget(folder_id="folder", profile_id="profile")


# ---------------------------------------------------------------------------
# Alipay — local golden path
# ---------------------------------------------------------------------------


class AlipayLocalGoldenTests(unittest.TestCase):
    def test_constants_are_golden(self):
        expected_launch = alipay_main._build_launch_kwargs(headless=False)
        expected_without_headless = {
            key: value for key, value in expected_launch.items() if key != "headless"
        }
        self.assertEqual(ALIPAY_LAUNCH_KWARGS, expected_without_headless)
        self.assertNotIn("headless", ALIPAY_LAUNCH_KWARGS)
        self.assertEqual(ALIPAY_CONTEXT_KWARGS, {"permissions": ["geolocation"]})
        self.assertFalse(ALIPAY_INIT_SCRIPT)

    def test_local_upload_keeps_launch_context_and_teardown(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(
                tmp_dir, platform="alipay", account_file="/tmp/alipay-cookie.json", headless=False
            )
            video.validate_upload_args = AsyncMock()
            upload_in = AsyncMock()
            video.upload_in = upload_in

            playwright = FakePlaywright()
            init_script = AsyncMock()
            with patch.object(alipay_main, "set_init_script", init_script):
                asyncio.run(video.upload(playwright))

        expected_launch = alipay_main._build_launch_kwargs(headless=False)
        self.assertEqual(playwright.chromium.launch_calls, [expected_launch])

        browser = playwright.chromium.launch_browser
        self.assertEqual(
            browser.new_context_calls,
            [{"storage_state": "/tmp/alipay-cookie.json", **ALIPAY_CONTEXT_KWARGS}],
        )
        init_script.assert_not_awaited()
        upload_in.assert_awaited_once()
        session = upload_in.await_args.args[0]
        self.assertEqual(session.mode, "local")

        context = browser.contexts[0]
        # FakeContext forbids grant_permissions; reaching here proves it was not called.
        self.assertEqual(context.forbidden_calls, [])
        self.assertEqual(context.storage_state_calls, ["/tmp/alipay-cookie.json"])
        self.assertTrue(context.closed)
        self.assertTrue(browser.closed)
        self.assertEqual(
            playwright.events, ["launch", "context.close", "browser.close"]
        )


# ---------------------------------------------------------------------------
# Alipay — Multilogin path
# ---------------------------------------------------------------------------


class AlipayMultiloginTests(unittest.TestCase):
    def test_upload_in_consumes_injected_context_only(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, platform="alipay", account_file=None)
            page = _FakePage()
            context = _RecordingContext(page)
            video.open_upload_page = AsyncMock()
            video.upload_video_file = AsyncMock()
            video.fill_title_and_tags = AsyncMock()
            video.fill_description = AsyncMock()
            video.upload_thumbnail = AsyncMock()
            video.apply_collection = AsyncMock()
            video.check_ai_label = AsyncMock()
            video.wait_for_upload_complete = AsyncMock()
            video.submit_publish = AsyncMock()
            session = BrowserSession(
                browser=MagicMock(), context=context, mode="multilogin"
            )

            with patch.object(alipay_main, "async_playwright", MagicMock()) as pw:
                asyncio.run(video.upload(None, session=session))

        pw.assert_not_called()
        self.assertIsNone(video.account_file)
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, 0)
        self.assertEqual(context.forbidden_calls, [])
        video.open_upload_page.assert_awaited_once_with(page, multilogin=True)
        video.submit_publish.assert_awaited_once_with(page, multilogin=True)

    def test_mlx_validation_skips_cookie_auth_and_cookie_existence(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, platform="alipay", account_file=None)
            video.upload_in = AsyncMock()
            cookie_auth = AsyncMock()
            session = BrowserSession(
                browser=MagicMock(), context=_FakePage(), mode="multilogin"
            )

            with patch.object(alipay_main, "cookie_auth", cookie_auth):
                asyncio.run(video.upload(None, session=session))

        cookie_auth.assert_not_awaited()

    def test_open_upload_page_login_redirect_raises_login_required(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, platform="alipay", account_file=None)
            page = _FakePage(final_url="https://auth.alipay.com/login/index.htm")
            video.upload_video_file = AsyncMock()
            session = BrowserSession(
                browser=MagicMock(), context=_RecordingContext(page), mode="multilogin"
            )

            with self.assertRaises(LoginRequiredError):
                asyncio.run(video.upload(None, session=session))

        video.upload_video_file.assert_not_awaited()

    def test_captcha_redirect_raises_login_required(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, platform="alipay", account_file=None)
            page = _FakePage(
                final_url="https://captcha.alipay.com/api/v1/captcha/verify?x=1"
            )
            video.upload_video_file = AsyncMock()
            session = BrowserSession(
                browser=MagicMock(), context=_RecordingContext(page), mode="multilogin"
            )

            with self.assertRaises(LoginRequiredError):
                asyncio.run(video.upload(None, session=session))

        video.upload_video_file.assert_not_awaited()

    def test_local_upload_never_calls_login_required_helper(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, platform="alipay", account_file="/tmp/a.json")
            video.validate_upload_args = AsyncMock()
            video.upload_in = AsyncMock()
            guard = MagicMock()

            with patch.object(alipay_main, "_raise_if_login_required", guard):
                asyncio.run(video.upload(FakePlaywright()))

        guard.assert_not_called()

    def test_wrapper_with_session_does_not_open_a_second_playwright(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, platform="alipay", account_file=None)
            video.upload = AsyncMock()
            session = BrowserSession(
                browser=MagicMock(), context=MagicMock(), mode="multilogin"
            )

            with patch.object(alipay_main, "async_playwright", MagicMock()) as pw:
                asyncio.run(video.alipay_upload_video(session=session))

        pw.assert_not_called()
        video.upload.assert_awaited_once_with(None, session=session)

    def test_wrapper_without_session_keeps_legacy_playwright(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, platform="alipay", account_file="/tmp/a.json")
            video.upload = AsyncMock()
            playwright_cm = _AsyncCM(object())

            with patch.object(
                alipay_main, "async_playwright", MagicMock(return_value=playwright_cm)
            ):
                asyncio.run(video.alipay_upload_video())

        self.assertEqual(playwright_cm.enter_calls, 1)
        self.assertEqual(playwright_cm.exit_calls, 1)
        video.upload.assert_awaited_once()


# ---------------------------------------------------------------------------
# Alipay — is_logged_in
# ---------------------------------------------------------------------------


class AlipayIsLoggedInTests(unittest.TestCase):
    def _check(self, page: _FakePage, *, cookies=None) -> bool:
        context = _LoginContext(page, cookies=cookies)
        result = asyncio.run(alipay_main.is_logged_in(context))
        self.assertEqual(context.new_page_calls, 1)
        self.assertTrue(page.closed)
        return result

    def test_positive_anchor_is_logged_in(self):
        page = _FakePage(
            final_url=ALIPAY_LIFE_ACCOUNT_URL,
            counts={ALIPAY_AVATAR_SELECTOR: 1},
        )
        self.assertTrue(self._check(page))

    def test_explicit_login_url_is_not_logged_in(self):
        page = _FakePage(final_url="https://auth.alipay.com/login/index.htm")
        self.assertFalse(self._check(page))

    def test_login_iframe_is_not_logged_in(self):
        page = _FakePage(
            final_url=ALIPAY_LIFE_ACCOUNT_URL,
            counts={'iframe[title="login"]': 1},
        )
        self.assertFalse(self._check(page))

    def test_http_5xx_raises(self):
        page = _FakePage(final_url=ALIPAY_LIFE_ACCOUNT_URL, status=503)
        with self.assertRaises(RuntimeError):
            self._check(page)

    def test_missing_positive_anchor_raises(self):
        page = _FakePage(final_url=ALIPAY_LIFE_ACCOUNT_URL)
        with self.assertRaises(RuntimeError):
            self._check(page)

    def test_unexpected_domain_raises(self):
        page = _FakePage(final_url="https://example.com/")
        with self.assertRaises(RuntimeError):
            self._check(page)

    def test_navigation_timeout_propagates(self):
        page = _FakePage(goto_error=TimeoutError("navigation timeout"))
        with self.assertRaises(Exception):
            self._check(page)


# ---------------------------------------------------------------------------
# Weibo — local golden path
# ---------------------------------------------------------------------------


class WeiboLocalGoldenTests(unittest.TestCase):
    def test_constants_are_golden(self):
        expected_launch = weibo_main._build_launch_kwargs(headless=False)
        expected_without_headless = {
            key: value for key, value in expected_launch.items() if key != "headless"
        }
        self.assertEqual(WEIBO_LAUNCH_KWARGS, expected_without_headless)
        self.assertNotIn("headless", WEIBO_LAUNCH_KWARGS)
        self.assertEqual(
            WEIBO_CONTEXT_KWARGS,
            {"viewport": {"width": 1280, "height": 2000}},
        )
        self.assertFalse(WEIBO_INIT_SCRIPT)

    def test_local_upload_keeps_launch_context_and_teardown(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(
                tmp_dir, platform="weibo", account_file="/tmp/weibo-cookie.json", headless=False
            )
            video.validate_upload_args = AsyncMock()
            upload_in = AsyncMock()
            video.upload_in = upload_in

            playwright = FakePlaywright()
            asyncio.run(video.upload(playwright))

        expected_launch = weibo_main._build_launch_kwargs(headless=False)
        self.assertEqual(playwright.chromium.launch_calls, [expected_launch])

        browser = playwright.chromium.launch_browser
        self.assertEqual(
            browser.new_context_calls,
            [{"storage_state": "/tmp/weibo-cookie.json", **WEIBO_CONTEXT_KWARGS}],
        )
        upload_in.assert_awaited_once()
        session = upload_in.await_args.args[0]
        self.assertEqual(session.mode, "local")

        context = browser.contexts[0]
        self.assertEqual(context.forbidden_calls, [])
        self.assertEqual(context.add_init_script_calls, [])
        self.assertEqual(context.storage_state_calls, ["/tmp/weibo-cookie.json"])
        self.assertTrue(context.closed)
        self.assertTrue(browser.closed)
        self.assertEqual(
            playwright.events, ["launch", "context.close", "browser.close"]
        )


# ---------------------------------------------------------------------------
# Weibo — Multilogin path
# ---------------------------------------------------------------------------


class WeiboMultiloginTests(unittest.TestCase):
    def test_upload_in_consumes_injected_context_only(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, platform="weibo", account_file=None)
            page = _FakePage()
            publish_page = _FakePage()
            context = _RecordingContext(page)
            video._open_video_publish_page = AsyncMock(return_value=publish_page)
            video._upload_video_file = AsyncMock()
            video._wait_upload_complete = AsyncMock()
            video._select_type = AsyncMock()
            video._select_declaration = AsyncMock()
            video._fill_title = AsyncMock()
            video._upload_thumbnail = AsyncMock()
            video._apply_collection = AsyncMock()
            video._fill_description = AsyncMock()
            video._submit_publish = AsyncMock()
            session = BrowserSession(
                browser=MagicMock(), context=context, mode="multilogin"
            )

            with patch.object(weibo_main, "async_playwright", MagicMock()) as pw:
                asyncio.run(video.upload(None, session=session))

        pw.assert_not_called()
        self.assertIsNone(video.account_file)
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, 0)
        self.assertEqual(context.forbidden_calls, [])
        self.assertEqual(page.goto_calls[0][0], WEIBO_HOME_URL)
        video._open_video_publish_page.assert_awaited_once_with(page, multilogin=True)
        video._submit_publish.assert_awaited_once_with(
            publish_page, multilogin=True
        )

    def test_mlx_validation_skips_cookie_auth_and_cookie_existence(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, platform="weibo", account_file=None)
            video.upload_in = AsyncMock()
            cookie_auth = AsyncMock()
            session = BrowserSession(
                browser=MagicMock(), context=_FakePage(), mode="multilogin"
            )

            with patch.object(weibo_main, "cookie_auth", cookie_auth):
                asyncio.run(video.upload(None, session=session))

        cookie_auth.assert_not_awaited()

    def test_login_redirect_raises_login_required(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, platform="weibo", account_file=None)
            page = _FakePage(
                final_url="https://passport.weibo.com/sso/signin?entry=miniblog"
            )
            open_publish = AsyncMock()
            video._open_video_publish_page = open_publish
            session = BrowserSession(
                browser=MagicMock(), context=_RecordingContext(page), mode="multilogin"
            )

            with self.assertRaises(LoginRequiredError):
                asyncio.run(video.upload(None, session=session))

        open_publish.assert_not_awaited()

    def test_local_upload_never_calls_login_required_helper(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, platform="weibo", account_file="/tmp/w.json")
            video.validate_upload_args = AsyncMock()
            video.upload_in = AsyncMock()
            guard = MagicMock()

            with patch.object(weibo_main, "_raise_if_login_required", guard):
                asyncio.run(video.upload(FakePlaywright()))

        guard.assert_not_called()

    def test_publish_button_scrolls_into_view_before_js_click(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, platform="weibo", account_file=None)
            page = _FakePage(
                counts={WEIBO_PUBLISH_SELECTOR: 1},
                visible={WEIBO_AGAIN_SELECTOR: True},
            )

            asyncio.run(video._submit_publish(page, multilogin=True))

        publish_events = [
            event for event in page.events if event[1:] and event[1] == WEIBO_PUBLISH_SELECTOR
        ]
        kinds = [event[0] for event in publish_events]
        self.assertIn("scroll", kinds)
        self.assertIn("evaluate", kinds)
        self.assertLess(kinds.index("scroll"), kinds.index("evaluate"))

    def test_local_publish_also_scrolls_into_view(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, platform="weibo", account_file=None)
            page = _FakePage(
                counts={WEIBO_PUBLISH_SELECTOR: 1},
                visible={WEIBO_AGAIN_SELECTOR: True},
            )

            asyncio.run(video._submit_publish(page))

        kinds = [
            event[0]
            for event in page.events
            if event[1:] and event[1] == WEIBO_PUBLISH_SELECTOR
        ]
        self.assertIn("scroll", kinds)

    def test_main_with_session_does_not_open_a_second_playwright(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = _make_video(tmp_dir, platform="weibo", account_file=None)
            video.upload = AsyncMock()
            session = BrowserSession(
                browser=MagicMock(), context=MagicMock(), mode="multilogin"
            )

            with patch.object(weibo_main, "async_playwright", MagicMock()) as pw:
                asyncio.run(video.main(session=session))

        pw.assert_not_called()
        video.upload.assert_awaited_once_with(None, session=session)


# ---------------------------------------------------------------------------
# Weibo — is_logged_in
# ---------------------------------------------------------------------------


class WeiboIsLoggedInTests(unittest.TestCase):
    def _check(self, page: _FakePage, *, cookies=None) -> bool:
        context = _LoginContext(page, cookies=cookies)
        result = asyncio.run(weibo_main.is_logged_in(context))
        self.assertEqual(context.new_page_calls, 1)
        self.assertTrue(page.closed)
        return result

    def test_avatar_is_logged_in(self):
        page = _FakePage(
            final_url=WEIBO_HOME_URL,
            counts={WEIBO_AVATAR_SELECTORS[0]: 1},
            visible={WEIBO_AVATAR_SELECTORS[0]: True},
        )
        self.assertTrue(self._check(page))

    def test_sub_cookie_is_secondary_positive_signal(self):
        page = _FakePage(final_url=WEIBO_HOME_URL)
        self.assertTrue(
            self._check(page, cookies=[{"name": "SUB", "value": "_2A25abc"}])
        )

    def test_login_page_url_is_not_logged_in(self):
        page = _FakePage(final_url="https://weibo.com/newlogin?url=/")
        self.assertFalse(self._check(page))

    def test_visible_login_button_is_not_logged_in(self):
        page = _FakePage(
            final_url=WEIBO_HOME_URL,
            counts={"text:登录:True": 1},
            visible={"text:登录:True": True},
        )
        self.assertFalse(self._check(page))

    def test_http_5xx_raises(self):
        page = _FakePage(final_url=WEIBO_HOME_URL, status=502)
        with self.assertRaises(RuntimeError):
            self._check(page)

    def test_no_positive_signal_raises(self):
        page = _FakePage(final_url=WEIBO_HOME_URL)
        with self.assertRaises(RuntimeError):
            self._check(page)

    def test_unexpected_domain_raises(self):
        page = _FakePage(final_url="https://example.com/")
        with self.assertRaises(RuntimeError):
            self._check(page)

    def test_navigation_timeout_propagates(self):
        page = _FakePage(goto_error=TimeoutError("navigation timeout"))
        with self.assertRaises(Exception):
            self._check(page)


# ---------------------------------------------------------------------------
# CLI — Alipay
# ---------------------------------------------------------------------------


class AlipayCliTests(unittest.TestCase):
    def _check_patches(self, *, logged_in=True, error=None):
        playwright_cm = _AsyncCM(object())
        session = Namespace(context=object())
        session_cm = _AsyncCM(session)
        session_factory = MagicMock(return_value=session_cm)
        probe = AsyncMock(return_value=logged_in)
        if error is not None:
            probe = AsyncMock(side_effect=error)
        return playwright_cm, session, session_cm, session_factory, probe

    def test_check_logged_in_returns_0(self):
        playwright_cm, session, session_cm, factory, probe = self._check_patches()
        with (
            patch.object(alipay_command, "async_playwright", lambda: playwright_cm),
            patch.object(alipay_command, "browser_session", new=factory),
            patch.object(alipay_command, "is_logged_in", new=probe),
        ):
            code, out, _ = _run_cli(
                ["alipay", "check", "--folder-id", "folder", "--profile-id", "profile"]
            )

        self.assertEqual(code, 0)
        self.assertIn("valid", out)
        probe.assert_awaited_once_with(session.context)
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)
        self.assertIsNone(factory.call_args.kwargs.get("account_file"))
        self.assertEqual(factory.call_args.kwargs["multilogin"], _target())

    def test_check_logged_out_returns_10(self):
        playwright_cm, _, _, factory, probe = self._check_patches(logged_in=False)
        with (
            patch.object(alipay_command, "async_playwright", lambda: playwright_cm),
            patch.object(alipay_command, "browser_session", new=factory),
            patch.object(alipay_command, "is_logged_in", new=probe),
        ):
            code, out, err = _run_cli(
                ["alipay", "check", "--folder-id", "folder", "--profile-id", "profile"]
            )

        self.assertEqual(code, 10)
        self.assertNotIn("valid", out)
        self.assertIn("alipay", err.lower() + "alipay")
        self.assertIn("profile", err)

    def test_check_failure_returns_1(self):
        playwright_cm, _, _, factory, probe = self._check_patches(
            error=RuntimeError("launcher down")
        )
        with (
            patch.object(alipay_command, "async_playwright", lambda: playwright_cm),
            patch.object(alipay_command, "browser_session", new=factory),
            patch.object(alipay_command, "is_logged_in", new=probe),
        ):
            code, _, err = _run_cli(
                ["alipay", "check", "--folder-id", "folder", "--profile-id", "profile"]
            )

        self.assertEqual(code, 1)
        self.assertIn("launcher down", err)

    def test_check_missing_target_returns_2(self):
        with patch.object(alipay_command, "async_playwright", MagicMock()) as pw:
            code, _, err = _run_cli(["alipay", "check", "--folder-id", "folder"])

        self.assertEqual(code, 2)
        pw.assert_not_called()

    def test_upload_success_returns_0_and_logs_in_once(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            playwright_cm = _AsyncCM(object())
            session = Namespace(context=object())
            session_cm = _AsyncCM(session)
            factory = MagicMock(return_value=session_cm)
            probe = AsyncMock(return_value=True)
            fake_app = MagicMock()
            fake_app.alipay_upload_video = AsyncMock()
            builder = MagicMock(return_value=fake_app)

            with (
                patch.object(alipay_command, "async_playwright", lambda: playwright_cm),
                patch.object(alipay_command, "browser_session", new=factory),
                patch.object(alipay_command, "is_logged_in", new=probe),
                patch.object(alipay_command, "_build_alipay_uploader", new=builder),
            ):
                code, out, _ = _run_cli(
                    [
                        "alipay",
                        "upload-video",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--file",
                        str(video_path),
                        "--title",
                        "标题",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertIn("Alipay video upload submitted", out)
        kwargs = factory.call_args.kwargs
        self.assertIsNone(kwargs["account_file"])
        self.assertEqual(kwargs["multilogin"], _target())
        self.assertEqual(kwargs["launch_kwargs"], ALIPAY_LAUNCH_KWARGS)
        self.assertIsNone(kwargs["context_kwargs"])
        self.assertFalse(kwargs["init_script"])
        probe.assert_awaited_once_with(session.context)
        fake_app.alipay_upload_video.assert_awaited_once_with(session=session)
        self.assertIsNone(builder.call_args.args[1])
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_upload_logged_out_returns_10_and_skips_upload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            session = Namespace(context=object())
            session_cm = _AsyncCM(session)
            fake_app = MagicMock()
            fake_app.alipay_upload_video = AsyncMock()

            with (
                patch.object(
                    alipay_command, "async_playwright", lambda: _AsyncCM(object())
                ),
                patch.object(
                    alipay_command,
                    "browser_session",
                    new=MagicMock(return_value=session_cm),
                ),
                patch.object(
                    alipay_command, "is_logged_in", new=AsyncMock(return_value=False)
                ),
                patch.object(
                    alipay_command,
                    "_build_alipay_uploader",
                    new=MagicMock(return_value=fake_app),
                ),
            ):
                code, out, _ = _run_cli(
                    [
                        "alipay",
                        "upload-video",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--file",
                        str(video_path),
                        "--title",
                        "标题",
                    ]
                )

        self.assertEqual(code, 10)
        self.assertNotIn("submitted", out)
        fake_app.alipay_upload_video.assert_not_awaited()
        self.assertEqual(session_cm.exit_calls, 1)

    def test_upload_failure_returns_1_and_exits_session(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            session = Namespace(context=object())
            session_cm = _AsyncCM(session)
            fake_app = MagicMock()
            fake_app.alipay_upload_video = AsyncMock(
                side_effect=RuntimeError("publish failed")
            )

            with (
                patch.object(
                    alipay_command, "async_playwright", lambda: _AsyncCM(object())
                ),
                patch.object(
                    alipay_command,
                    "browser_session",
                    new=MagicMock(return_value=session_cm),
                ),
                patch.object(
                    alipay_command, "is_logged_in", new=AsyncMock(return_value=True)
                ),
                patch.object(
                    alipay_command,
                    "_build_alipay_uploader",
                    new=MagicMock(return_value=fake_app),
                ),
            ):
                code, _, err = _run_cli(
                    [
                        "alipay",
                        "upload-video",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--file",
                        str(video_path),
                        "--title",
                        "标题",
                    ]
                )

        self.assertEqual(code, 1)
        self.assertIn("publish failed", err)
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_local_upload_stays_on_legacy_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            legacy_upload = AsyncMock()
            factory = MagicMock()

            with (
                patch.object(alipay_command, "upload_alipay_video", new=legacy_upload),
                patch.object(alipay_command, "browser_session", new=factory),
            ):
                code, out, _ = _run_cli(
                    [
                        "alipay",
                        "upload-video",
                        "--account",
                        "creator",
                        "--file",
                        str(video_path),
                        "--title",
                        "标题",
                    ],
                    token="",
                )

        self.assertEqual(code, 0)
        self.assertIn("Alipay video upload submitted", out)
        factory.assert_not_called()
        self.assertEqual(legacy_upload.await_args.args[0].account_name, "creator")
        self.assertIsNone(legacy_upload.await_args.kwargs.get("target"))

    def test_upload_stops_profile_exactly_once(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            playwright = FakePlaywright()
            browser = playwright.chromium.new_browser([FakeContext()])
            playwright.chromium.queue_connect_browser(browser)
            playwright_cm = _AsyncCM(playwright)
            client = FakeMultiloginClient(port="55513")
            fake_app = MagicMock()
            fake_app.alipay_upload_video = AsyncMock()

            with (
                patch.object(
                    alipay_command, "async_playwright", lambda: playwright_cm
                ),
                patch.object(
                    alipay_command, "is_logged_in", new=AsyncMock(return_value=True)
                ),
                patch.object(
                    alipay_command,
                    "_build_alipay_uploader",
                    new=MagicMock(return_value=fake_app),
                ),
                patch(
                    "utils.browser_session.MultiloginClient",
                    return_value=client,
                ),
            ):
                code, _, _ = _run_cli(
                    [
                        "alipay",
                        "upload-video",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--file",
                        str(video_path),
                        "--title",
                        "标题",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertEqual(client.stop_calls, ["profile"])


# ---------------------------------------------------------------------------
# CLI — Weibo
# ---------------------------------------------------------------------------


class WeiboCliTests(unittest.TestCase):
    def _check_patches(self, *, logged_in=True, error=None):
        playwright_cm = _AsyncCM(object())
        session = Namespace(context=object())
        session_cm = _AsyncCM(session)
        factory = MagicMock(return_value=session_cm)
        probe = AsyncMock(return_value=logged_in)
        if error is not None:
            probe = AsyncMock(side_effect=error)
        return playwright_cm, session, session_cm, factory, probe

    def test_check_logged_in_returns_0(self):
        playwright_cm, session, session_cm, factory, probe = self._check_patches()
        with (
            patch.object(weibo_command, "async_playwright", lambda: playwright_cm),
            patch.object(weibo_command, "browser_session", new=factory),
            patch.object(weibo_command, "is_logged_in", new=probe),
        ):
            code, out, _ = _run_cli(
                ["weibo", "check", "--folder-id", "folder", "--profile-id", "profile"]
            )

        self.assertEqual(code, 0)
        self.assertIn("valid", out)
        probe.assert_awaited_once_with(session.context)
        self.assertIsNone(factory.call_args.kwargs.get("account_file"))
        self.assertEqual(session_cm.exit_calls, 1)

    def test_check_logged_out_returns_10(self):
        playwright_cm, _, _, factory, probe = self._check_patches(logged_in=False)
        with (
            patch.object(weibo_command, "async_playwright", lambda: playwright_cm),
            patch.object(weibo_command, "browser_session", new=factory),
            patch.object(weibo_command, "is_logged_in", new=probe),
        ):
            code, out, err = _run_cli(
                ["weibo", "check", "--folder-id", "folder", "--profile-id", "profile"]
            )

        self.assertEqual(code, 10)
        self.assertNotIn("valid", out)
        self.assertIn("profile", err)

    def test_check_failure_returns_1(self):
        playwright_cm, _, _, factory, probe = self._check_patches(
            error=RuntimeError("launcher down")
        )
        with (
            patch.object(weibo_command, "async_playwright", lambda: playwright_cm),
            patch.object(weibo_command, "browser_session", new=factory),
            patch.object(weibo_command, "is_logged_in", new=probe),
        ):
            code, _, err = _run_cli(
                ["weibo", "check", "--folder-id", "folder", "--profile-id", "profile"]
            )

        self.assertEqual(code, 1)
        self.assertIn("launcher down", err)

    def test_check_missing_target_returns_2(self):
        with patch.object(weibo_command, "async_playwright", MagicMock()) as pw:
            code, _, _ = _run_cli(["weibo", "check", "--folder-id", "folder"])

        self.assertEqual(code, 2)
        pw.assert_not_called()

    def test_upload_success_returns_0_and_no_viewport_in_mlx(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")
            thumb_path = Path(tmp_dir) / "cover.jpg"
            thumb_path.write_bytes(b"image")

            playwright_cm = _AsyncCM(object())
            session = Namespace(context=object())
            session_cm = _AsyncCM(session)
            factory = MagicMock(return_value=session_cm)
            probe = AsyncMock(return_value=True)
            fake_app = MagicMock()
            fake_app.main = AsyncMock()
            builder = MagicMock(return_value=fake_app)

            with (
                patch.object(weibo_command, "async_playwright", lambda: playwright_cm),
                patch.object(weibo_command, "browser_session", new=factory),
                patch.object(weibo_command, "is_logged_in", new=probe),
                patch.object(weibo_command, "_build_weibo_uploader", new=builder),
            ):
                code, out, _ = _run_cli(
                    [
                        "weibo",
                        "upload-video",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--file",
                        str(video_path),
                        "--title",
                        "标题",
                        "--thumbnail",
                        str(thumb_path),
                    ]
                )

        self.assertEqual(code, 0)
        self.assertIn("Weibo video upload submitted", out)
        kwargs = factory.call_args.kwargs
        self.assertIsNone(kwargs["account_file"])
        self.assertEqual(kwargs["multilogin"], _target())
        self.assertEqual(kwargs["launch_kwargs"], WEIBO_LAUNCH_KWARGS)
        self.assertIsNone(kwargs["context_kwargs"])
        self.assertNotIn("viewport", kwargs["context_kwargs"] or {})
        self.assertFalse(kwargs["init_script"])
        probe.assert_awaited_once_with(session.context)
        fake_app.main.assert_awaited_once_with(session=session)
        self.assertIsNone(builder.call_args.args[1])

    def test_upload_logged_out_returns_10_and_skips_upload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")
            thumb_path = Path(tmp_dir) / "cover.jpg"
            thumb_path.write_bytes(b"image")

            session = Namespace(context=object())
            session_cm = _AsyncCM(session)
            fake_app = MagicMock()
            fake_app.main = AsyncMock()

            with (
                patch.object(
                    weibo_command, "async_playwright", lambda: _AsyncCM(object())
                ),
                patch.object(
                    weibo_command,
                    "browser_session",
                    new=MagicMock(return_value=session_cm),
                ),
                patch.object(
                    weibo_command, "is_logged_in", new=AsyncMock(return_value=False)
                ),
                patch.object(
                    weibo_command,
                    "_build_weibo_uploader",
                    new=MagicMock(return_value=fake_app),
                ),
            ):
                code, out, _ = _run_cli(
                    [
                        "weibo",
                        "upload-video",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--file",
                        str(video_path),
                        "--title",
                        "标题",
                        "--thumbnail",
                        str(thumb_path),
                    ]
                )

        self.assertEqual(code, 10)
        self.assertNotIn("submitted", out)
        fake_app.main.assert_not_awaited()

    def test_upload_failure_returns_1_and_exits_session(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")
            thumb_path = Path(tmp_dir) / "cover.jpg"
            thumb_path.write_bytes(b"image")

            session = Namespace(context=object())
            session_cm = _AsyncCM(session)
            fake_app = MagicMock()
            fake_app.main = AsyncMock(side_effect=RuntimeError("publish failed"))

            with (
                patch.object(
                    weibo_command, "async_playwright", lambda: _AsyncCM(object())
                ),
                patch.object(
                    weibo_command,
                    "browser_session",
                    new=MagicMock(return_value=session_cm),
                ),
                patch.object(
                    weibo_command, "is_logged_in", new=AsyncMock(return_value=True)
                ),
                patch.object(
                    weibo_command,
                    "_build_weibo_uploader",
                    new=MagicMock(return_value=fake_app),
                ),
            ):
                code, _, err = _run_cli(
                    [
                        "weibo",
                        "upload-video",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--file",
                        str(video_path),
                        "--title",
                        "标题",
                        "--thumbnail",
                        str(thumb_path),
                    ]
                )

        self.assertEqual(code, 1)
        self.assertIn("publish failed", err)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_local_upload_stays_on_legacy_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")
            thumb_path = Path(tmp_dir) / "cover.jpg"
            thumb_path.write_bytes(b"image")

            legacy_upload = AsyncMock()
            factory = MagicMock()

            with (
                patch.object(weibo_command, "upload_weibo_video", new=legacy_upload),
                patch.object(weibo_command, "browser_session", new=factory),
            ):
                code, out, _ = _run_cli(
                    [
                        "weibo",
                        "upload-video",
                        "--account",
                        "creator",
                        "--file",
                        str(video_path),
                        "--title",
                        "标题",
                        "--thumbnail",
                        str(thumb_path),
                    ],
                    token="",
                )

        self.assertEqual(code, 0)
        self.assertIn("Weibo video upload submitted", out)
        factory.assert_not_called()
        self.assertEqual(legacy_upload.await_args.args[0].account_name, "creator")
        self.assertIsNone(legacy_upload.await_args.kwargs.get("target"))


if __name__ == "__main__":
    unittest.main()
