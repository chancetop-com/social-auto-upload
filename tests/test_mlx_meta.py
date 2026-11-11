# -*- coding: utf-8 -*-
"""Facebook / Facebook Page / Instagram Multilogin seam (ticket 23).

Covers the three Meta uploaders and their CLI entry points:

* local mode stays byte-equivalent to the pre-seam launch/context/init path;
* Multilogin mode only consumes the injected ``BrowserSession`` — no launch,
  no ``new_context``, no cookie file, no init script, no identity-file read;
* ``is_logged_in`` returns True/False/raises on the documented anchors;
* ``check`` exits 0/10/1, uploads exit 0/10/1 and the session is entered and
  exited exactly once (Stop ownership stays in ``browser_session``).

All tests are offline; page/browser objects are hand-written doubles.
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
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import sau_cli
from sau_commands import facebook as facebook_command
from sau_commands import facebook_page as facebook_page_command
from sau_commands import instagram as instagram_command
from uploader.meta_uploader.facebook_page_uploader import main as facebook_page_main
from uploader.meta_uploader.facebook_page_uploader.main import (
    FACEBOOK_PAGE_CONTEXT_KWARGS,
    FACEBOOK_PAGE_INIT_SCRIPT,
    FACEBOOK_PAGE_LAUNCH_KWARGS,
    META_BUSINESS_URL,
    MetaBusinessUploader,
    is_logged_in as facebook_page_is_logged_in,
)
from uploader.meta_uploader.facebook_uploader import main as facebook_main
from uploader.meta_uploader.facebook_uploader.main import (
    FACEBOOK_CONTEXT_KWARGS,
    FACEBOOK_HOME_URL,
    FACEBOOK_INIT_SCRIPT,
    FACEBOOK_LAUNCH_KWARGS,
    FacebookPost,
    _open_facebook_page,
    facebook_launch_kwargs,
    is_logged_in as facebook_is_logged_in,
)
from uploader.meta_uploader.insgraph_uploader import main as instagram_main
from uploader.meta_uploader.insgraph_uploader.main import (
    INSTAGRAM_CONTEXT_KWARGS,
    INSTAGRAM_HOME_URL,
    INSTAGRAM_INIT_SCRIPT,
    INSTAGRAM_LAUNCH_KWARGS,
    InstagramUploader,
    _open_instagram_page,
    instagram_launch_kwargs,
    is_logged_in as instagram_is_logged_in,
)
from utils.browser_session import BrowserSession
from utils.errors import LoginRequiredError
from utils.multilogin import MultiloginTarget

TOKEN = "SENTINEL-MLX-TOKEN-ticket23"
PROFILE = "profile-23"
FOLDER = "folder-23"


# ---------------------------------------------------------------------------
# Page / browser doubles
# ---------------------------------------------------------------------------


class _Response:
    def __init__(self, status: int = 200) -> None:
        self.status = status


class _LocatorStub:
    """Configurable locator double covering every call the helpers make."""

    def __init__(
        self,
        *,
        count: int = 0,
        visible: bool = False,
        text: str = "",
        attr: str | None = None,
    ) -> None:
        self.count_value = count
        self.visible = visible
        self.text = text
        self.attr = attr
        self.filter_calls: list[dict] = []
        self.wait_calls: list[dict] = []
        self.click_calls = 0
        self.fill_calls: list[str] = []

    async def count(self) -> int:
        return self.count_value

    @property
    def first(self) -> "_LocatorStub":
        return self

    async def is_visible(self) -> bool:
        return self.visible

    def filter(self, **kwargs):
        self.filter_calls.append(kwargs)
        return self

    async def wait_for(self, **kwargs) -> None:
        self.wait_calls.append(kwargs)

    async def click(self) -> None:
        self.click_calls += 1

    async def fill(self, value: str) -> None:
        self.fill_calls.append(value)

    async def inner_text(self) -> str:
        return self.text

    async def get_attribute(self, name: str) -> str | None:
        return self.attr

    async def all(self):
        return []


class _PageStub:
    def __init__(
        self,
        *,
        final_url: str = "about:blank",
        response_status: int = 200,
        goto_error: BaseException | None = None,
    ) -> None:
        self.url = "about:blank"
        self.final_url = final_url
        self.response_status = response_status
        self.goto_error = goto_error
        self.goto_calls: list[tuple[str, dict]] = []
        self.locators: dict[str, _LocatorStub] = {}
        self.default_locator = _LocatorStub()
        self.wait_timeout_calls: list[int] = []
        self.default_timeout_calls: list[int] = []
        self.closed = False
        self.screenshot_calls: list[str] = []

    async def goto(self, url: str, **kwargs):
        self.goto_calls.append((url, kwargs))
        if self.goto_error is not None:
            raise self.goto_error
        self.url = self.final_url
        return _Response(self.response_status)

    def locator(self, selector: str) -> _LocatorStub:
        return self.locators.get(selector, self.default_locator)

    async def wait_for_timeout(self, ms: int) -> None:
        self.wait_timeout_calls.append(ms)

    def set_default_timeout(self, ms: int) -> None:
        self.default_timeout_calls.append(ms)

    async def close(self) -> None:
        self.closed = True

    async def screenshot(self, **kwargs) -> None:
        self.screenshot_calls.append(str(kwargs.get("path")))

    async def content(self) -> str:
        return "<html></html>"


class _StrictBrowser:
    """MLX ownership guard: the uploader must never touch the browser."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def new_context(self, **kwargs):
        self.calls.append("new_context")
        raise AssertionError("browser.new_context is forbidden in Multilogin mode")

    async def new_page(self, **kwargs):
        self.calls.append("new_page")
        raise AssertionError("browser.new_page is forbidden in Multilogin mode")

    async def close(self):
        self.calls.append("close")
        raise AssertionError("the uploader must not close the Multilogin browser")


class _ContextStub:
    def __init__(self, page: _PageStub | None = None, *, cookies=None) -> None:
        self.page = page or _PageStub()
        self.cookies_value = list(cookies or [])
        self.new_page_calls = 0
        self.storage_state_calls: list[object] = []
        self.add_init_script_calls = 0
        self.cookies_calls: list[str] = []
        self.close_calls = 0
        self.pages = [self.page]

    async def new_page(self) -> _PageStub:
        self.new_page_calls += 1
        return self.page

    async def storage_state(self, *, path=None, **kwargs):
        self.storage_state_calls.append(path)
        return {"cookies": [], "origins": []}

    async def add_init_script(self, *args, **kwargs) -> None:
        self.add_init_script_calls += 1
        raise AssertionError("add_init_script is forbidden in Multilogin mode")

    async def cookies(self, *args, **kwargs):
        self.cookies_calls.append(str(args[0] if args else ""))
        return self.cookies_value

    async def close(self) -> None:
        self.close_calls += 1


class _LaunchBrowser:
    def __init__(self, context: _ContextStub, page: _PageStub) -> None:
        self.context = context
        self.page = page
        self.new_context_calls: list[dict] = []
        self.closed = False

    async def new_context(self, **kwargs) -> _ContextStub:
        self.new_context_calls.append(dict(kwargs))
        return self.context

    async def close(self) -> None:
        self.closed = True


class _ChromiumStub:
    def __init__(self, browser: _LaunchBrowser) -> None:
        self.browser = browser
        self.launch_calls: list[dict] = []

    async def launch(self, **kwargs) -> _LaunchBrowser:
        self.launch_calls.append(dict(kwargs))
        return self.browser


class _AsyncCM:
    def __init__(self, value=None) -> None:
        self.value = value
        self.enter_calls = 0
        self.exit_calls = 0

    async def __aenter__(self):
        self.enter_calls += 1
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        self.exit_calls += 1
        return False


def _local_launcher(page: _PageStub) -> tuple[_ChromiumStub, _ContextStub, _LaunchBrowser]:
    context = _ContextStub(page)
    browser = _LaunchBrowser(context, page)
    return _ChromiumStub(browser), context, browser


def _session(context: _ContextStub) -> BrowserSession:
    return BrowserSession(browser=_StrictBrowser(), context=context, mode="multilogin")


def _write_media(directory: str, name: str = "clip.mp4") -> Path:
    path = Path(directory) / name
    path.write_bytes(b"media")
    return path


# ---------------------------------------------------------------------------
# Local golden behaviour
# ---------------------------------------------------------------------------


class LocalGoldenTests(unittest.TestCase):
    def test_facebook_local_launch_and_context_are_golden(self):
        page = _PageStub()
        chromium, context, browser = _local_launcher(page)
        playwright = SimpleNamespace(chromium=chromium)

        asyncio.run(
            _open_facebook_page(
                playwright,
                Path("/tmp/facebook-cookie.json"),
                proxy="http://proxy.example:8080",
                headless=False,
            )
        )

        self.assertEqual(
            chromium.launch_calls,
            [
                {
                    "headless": False,
                    "channel": "chrome",
                    "proxy": {"server": "http://proxy.example:8080"},
                }
            ],
        )
        self.assertEqual(
            browser.new_context_calls,
            [{"storage_state": "/tmp/facebook-cookie.json"}],
        )
        self.assertEqual(FACEBOOK_LAUNCH_KWARGS, {"channel": "chrome"})
        self.assertEqual(FACEBOOK_CONTEXT_KWARGS, {})
        self.assertFalse(FACEBOOK_INIT_SCRIPT)
        self.assertEqual(
            facebook_launch_kwargs(None), {"channel": "chrome", "proxy": None}
        )

    def test_facebook_local_upload_saves_cookie_then_closes(self):
        with tempfile.TemporaryDirectory() as directory:
            media = _write_media(directory)
            cookie = Path(directory) / "facebook.json"
            cookie.write_text("{}", encoding="utf-8")
            page = _PageStub()
            context = _ContextStub(page)
            browser = _LaunchBrowser(context, page)
            app = FacebookPost("标题", media, "", [], cookie, proxy=None, headless=True)
            app._publish_on_page = AsyncMock()

            with patch.object(
                facebook_main,
                "_open_facebook_page",
                AsyncMock(return_value=(browser, context, page)),
            ), patch.object(
                facebook_main, "_is_logged_out", AsyncMock(return_value=False)
            ):
                asyncio.run(app.upload(SimpleNamespace()))

        self.assertEqual(context.storage_state_calls, [str(cookie)])
        self.assertTrue(browser.closed)

    def test_facebook_page_local_launch_and_context_are_golden(self):
        page = _PageStub()
        chromium, context, browser = _local_launcher(page)
        playwright = SimpleNamespace(chromium=chromium)

        asyncio.run(
            facebook_page_main._open_business_page(
                playwright,
                Path("/tmp/page-cookie.json"),
                proxy="http://proxy.example:8080",
                headless=True,
            )
        )

        self.assertEqual(
            chromium.launch_calls,
            [
                {
                    "headless": True,
                    "channel": "chrome",
                    "proxy": {"server": "http://proxy.example:8080"},
                }
            ],
        )
        self.assertEqual(
            browser.new_context_calls,
            [{"storage_state": "/tmp/page-cookie.json"}],
        )
        self.assertEqual(FACEBOOK_PAGE_LAUNCH_KWARGS, {"channel": "chrome"})
        self.assertEqual(FACEBOOK_PAGE_CONTEXT_KWARGS, {})
        self.assertFalse(FACEBOOK_PAGE_INIT_SCRIPT)

    def test_facebook_page_local_upload_saves_cookie_then_closes(self):
        with tempfile.TemporaryDirectory() as directory:
            media = _write_media(directory)
            cookie = Path(directory) / "page.json"
            cookie.write_text("{}", encoding="utf-8")
            result_file = Path(directory) / "result.json"
            page = _PageStub()
            context = _ContextStub(page)
            browser = _LaunchBrowser(context, page)
            app = MetaBusinessUploader(
                "facebook-page",
                cookie,
                title="标题",
                video_file=media,
                result_file=result_file,
            )
            app._publish_on_page = AsyncMock()

            with patch.object(
                facebook_page_main,
                "_open_business_page",
                AsyncMock(return_value=(browser, context, page)),
            ), patch.object(
                facebook_page_main,
                "_is_business_logged_out",
                AsyncMock(return_value=False),
            ):
                result = asyncio.run(app.upload())

            self.assertTrue(result_file.is_file())

        self.assertEqual(result["platform"], "facebook-page")
        self.assertEqual(context.storage_state_calls, [str(cookie)])
        self.assertTrue(browser.closed)

    def test_instagram_local_launch_and_context_are_golden(self):
        page = _PageStub()
        chromium, context, browser = _local_launcher(page)
        playwright = SimpleNamespace(chromium=chromium)

        asyncio.run(
            _open_instagram_page(
                playwright,
                Path("/tmp/instagram-cookie.json"),
                proxy="http://proxy.example:8080",
                headless=False,
            )
        )

        self.assertEqual(
            chromium.launch_calls,
            [
                {
                    "headless": False,
                    "channel": "chrome",
                    "proxy": {"server": "http://proxy.example:8080"},
                }
            ],
        )
        self.assertEqual(
            browser.new_context_calls,
            [
                {
                    "storage_state": "/tmp/instagram-cookie.json",
                    "locale": "en-US",
                    "extra_http_headers": {"Accept-Language": "en-US,en;q=0.9"},
                }
            ],
        )
        self.assertEqual(INSTAGRAM_LAUNCH_KWARGS, {"channel": "chrome"})
        # 本地模式固定英文界面（spec §4.4）；托管模式由 Profile 自己保持英文。
        self.assertEqual(INSTAGRAM_CONTEXT_KWARGS["locale"], "en-US")
        self.assertEqual(
            INSTAGRAM_CONTEXT_KWARGS["extra_http_headers"],
            {"Accept-Language": "en-US,en;q=0.9"},
        )
        self.assertFalse(INSTAGRAM_INIT_SCRIPT)
        self.assertEqual(
            instagram_launch_kwargs(None), {"channel": "chrome", "proxy": None}
        )

    def test_instagram_local_upload_keeps_identity_check_and_cookie_write(self):
        with tempfile.TemporaryDirectory() as directory:
            media = _write_media(directory)
            cookie = Path(directory) / "instagram.json"
            cookie.write_text("{}", encoding="utf-8")
            page = _PageStub()
            context = _ContextStub(page)
            browser = _LaunchBrowser(context, page)
            app = InstagramUploader(
                cookie,
                title="caption",
                video_file=media,
                result_file=Path(directory) / "result.json",
            )
            identity = AsyncMock(return_value={"user_id": "42", "username": "creator"})
            app._upload_steps = AsyncMock(return_value=app.result)

            with patch.object(
                instagram_main,
                "_open_instagram_page",
                AsyncMock(return_value=(browser, context, page)),
            ), patch.object(instagram_main, "instagram_identity", identity):
                asyncio.run(app.upload())

        identity.assert_awaited_once()
        self.assertEqual(context.storage_state_calls, [str(cookie)])
        self.assertTrue(browser.closed)


# ---------------------------------------------------------------------------
# Multilogin uploader bodies
# ---------------------------------------------------------------------------


class MultiloginUploaderTests(unittest.TestCase):
    def test_facebook_mlx_upload_only_consumes_the_injected_context(self):
        with tempfile.TemporaryDirectory() as directory:
            media = _write_media(directory)
            page = _PageStub()
            context = _ContextStub(page)
            app = FacebookPost(
                "标题", media, "", [], None, proxy="http://ignored", headless=True
            )
            app._publish_on_page = AsyncMock()

            asyncio.run(app.upload(None, session=_session(context)))

        self.assertIsNone(app.account_file)
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, 0)
        self.assertEqual(page.goto_calls[0][0], FACEBOOK_HOME_URL)
        app._publish_on_page.assert_awaited_once_with(page)

    def test_facebook_mlx_wrapper_does_not_open_async_playwright(self):
        with tempfile.TemporaryDirectory() as directory:
            media = _write_media(directory)
            context = _ContextStub(_PageStub())
            app = FacebookPost("标题", media, "", [], None)
            app.upload = AsyncMock()

            with patch.object(
                facebook_main, "async_playwright", MagicMock()
            ) as async_playwright:
                asyncio.run(app.main(session=_session(context)))

        async_playwright.assert_not_called()
        app.upload.assert_awaited_once_with(None, session=ANY)

    def test_facebook_mlx_mid_upload_login_redirect_raises_login_required(self):
        with tempfile.TemporaryDirectory() as directory:
            media = _write_media(directory)
            page = _PageStub(final_url="https://www.facebook.com/login/?next=/")
            context = _ContextStub(page)
            app = FacebookPost("标题", media, "", [], None)
            app._publish_on_page = AsyncMock()

            with self.assertRaises(Exception) as caught:
                asyncio.run(app.upload(None, session=_session(context)))

        self.assertEqual(type(caught.exception).__name__, "LoginRequiredError")
        app._publish_on_page.assert_not_awaited()

    def test_facebook_page_mlx_upload_only_consumes_the_injected_context(self):
        with tempfile.TemporaryDirectory() as directory:
            media = _write_media(directory)
            result_file = Path(directory) / "result.json"
            page = _PageStub()
            page.locators['a[href*="/latest/home"]'] = _LocatorStub(count=1)
            context = _ContextStub(page)
            app = MetaBusinessUploader(
                "facebook-page",
                None,
                title="标题",
                video_file=media,
                result_file=result_file,
            )
            app._publish_on_page = AsyncMock()

            result = asyncio.run(app.upload(session=_session(context)))
            self.assertTrue(result_file.is_file())

        self.assertEqual(result["platform"], "facebook-page")
        self.assertIsNone(app.account_file)
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, 0)
        self.assertEqual(page.goto_calls[0][0], META_BUSINESS_URL)
        app._publish_on_page.assert_awaited_once_with(page)

    def test_facebook_page_mlx_does_not_open_async_playwright(self):
        with tempfile.TemporaryDirectory() as directory:
            media = _write_media(directory)
            page = _PageStub()
            page.locators['a[href*="/latest/home"]'] = _LocatorStub(count=1)
            context = _ContextStub(page)
            app = MetaBusinessUploader(
                "facebook-page",
                None,
                title="标题",
                video_file=media,
                result_file=Path(directory) / "result.json",
            )
            app._publish_on_page = AsyncMock()

            with patch.object(
                facebook_page_main, "async_playwright", MagicMock()
            ) as async_playwright:
                asyncio.run(app.upload(session=_session(context)))

        async_playwright.assert_not_called()

    def test_facebook_page_mlx_mid_upload_login_redirect_raises_login_required(self):
        with tempfile.TemporaryDirectory() as directory:
            media = _write_media(directory)
            page = _PageStub(final_url="https://business.facebook.com/login/")
            context = _ContextStub(page)
            app = MetaBusinessUploader(
                "facebook-page",
                None,
                title="标题",
                video_file=media,
                result_file=Path(directory) / "result.json",
            )
            app._publish_on_page = AsyncMock()

            with self.assertRaises(Exception) as caught:
                asyncio.run(app.upload(session=_session(context)))

        self.assertEqual(type(caught.exception).__name__, "LoginRequiredError")
        app._publish_on_page.assert_not_awaited()

    def test_instagram_mlx_upload_skips_identity_file_and_cookie_io(self):
        with tempfile.TemporaryDirectory() as directory:
            media = _write_media(directory)
            page = _PageStub()
            page.locators['a[href^="/direct/inbox/"]'] = _LocatorStub(count=1)
            context = _ContextStub(page)
            app = InstagramUploader(
                None,
                title="caption",
                video_file=media,
                result_file=Path(directory) / "result.json",
            )
            identity_reader = MagicMock()
            mlx_identity = AsyncMock(return_value={"user_id": "42", "username": "me"})
            app._upload_steps = AsyncMock(return_value=app.result)

            with patch.object(
                instagram_main, "instagram_identity", identity_reader
            ), patch.object(
                instagram_main, "_multilogin_identity", mlx_identity
            ), patch.object(
                instagram_main,
                "expect",
                MagicMock(
                    return_value=SimpleNamespace(
                        not_to_have_count=AsyncMock(return_value=None)
                    )
                ),
            ):
                asyncio.run(app.upload(session=_session(context)))

        identity_reader.assert_not_called()
        mlx_identity.assert_awaited_once()
        self.assertIsNone(app.account_file)
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, 0)
        self.assertEqual(page.goto_calls[0][0], INSTAGRAM_HOME_URL)
        app._upload_steps.assert_awaited_once()

    def test_instagram_mlx_mid_upload_login_redirect_raises_login_required(self):
        with tempfile.TemporaryDirectory() as directory:
            media = _write_media(directory)
            page = _PageStub(final_url="https://www.instagram.com/accounts/login/")
            context = _ContextStub(page)
            app = InstagramUploader(
                None,
                title="caption",
                video_file=media,
                result_file=Path(directory) / "result.json",
            )
            app._upload_steps = AsyncMock(return_value=app.result)

            with self.assertRaises(Exception) as caught:
                asyncio.run(app.upload(session=_session(context)))

        self.assertEqual(type(caught.exception).__name__, "LoginRequiredError")
        app._upload_steps.assert_not_awaited()


# ---------------------------------------------------------------------------
# is_logged_in: True / False / raise
# ---------------------------------------------------------------------------


class IsLoggedInTests(unittest.TestCase):
    def _facebook_page(self, *, final_url: str | None = None, **kwargs) -> _PageStub:
        page = _PageStub(final_url=final_url or FACEBOOK_HOME_URL, **kwargs)
        page.locators[facebook_main.FACEBOOK_LOGIN_INPUT] = _LocatorStub(
            count=0, visible=False
        )
        page.locators[facebook_main.FACEBOOK_MEDIA_INPUT] = _LocatorStub(count=1)
        return page

    def test_facebook_true_false_and_raise(self):
        context = _ContextStub(self._facebook_page())
        self.assertTrue(asyncio.run(facebook_is_logged_in(context)))
        self.assertEqual(context.new_page_calls, 1)
        self.assertTrue(context.page.closed)

        cases = {
            "login": "https://www.facebook.com/login/?next=/",
            "checkpoint": "https://www.facebook.com/checkpoint/block/",
            "two_step": "https://www.facebook.com/two_step_verification/authentication/",
        }
        for name, url in cases.items():
            with self.subTest(name=name):
                context = _ContextStub(_PageStub(final_url=url))
                self.assertFalse(asyncio.run(facebook_is_logged_in(context)))

        form_page = self._facebook_page()
        form_page.locators[facebook_main.FACEBOOK_LOGIN_INPUT] = _LocatorStub(
            count=1, visible=True
        )
        self.assertFalse(asyncio.run(facebook_is_logged_in(_ContextStub(form_page))))

        blank_page = self._facebook_page()
        blank_page.locators[facebook_main.FACEBOOK_MEDIA_INPUT] = _LocatorStub(count=0)
        self.assertFalse(asyncio.run(facebook_is_logged_in(_ContextStub(blank_page))))

        for name, page in (
            ("network", self._facebook_page(goto_error=TimeoutError("timeout"))),
            ("5xx", self._facebook_page(response_status=503)),
            ("unexpected", self._facebook_page(final_url="https://example.com/")),
        ):
            with self.subTest(name=name), self.assertRaises(Exception):
                asyncio.run(facebook_is_logged_in(_ContextStub(page)))

    def _business_page(self, *, final_url: str | None = None, **kwargs) -> _PageStub:
        page = _PageStub(final_url=final_url or META_BUSINESS_URL, **kwargs)
        page.locators['input[name="email"]'] = _LocatorStub(count=0, visible=False)
        page.locators['a[href*="/latest/home"]'] = _LocatorStub(count=1)
        return page

    def test_facebook_page_true_false_and_raise(self):
        context = _ContextStub(self._business_page())
        self.assertTrue(asyncio.run(facebook_page_is_logged_in(context)))
        self.assertEqual(context.new_page_calls, 1)
        self.assertTrue(context.page.closed)

        for name, url in {
            "login": "https://business.facebook.com/login/",
            "two_step": "https://business.facebook.com/two_step_verification/",
            "checkpoint": "https://business.facebook.com/checkpoint/block/",
        }.items():
            with self.subTest(name=name):
                context = _ContextStub(_PageStub(final_url=url))
                self.assertFalse(asyncio.run(facebook_page_is_logged_in(context)))

        form_page = self._business_page()
        form_page.locators['input[name="email"]'] = _LocatorStub(
            count=1, visible=True
        )
        self.assertFalse(asyncio.run(facebook_page_is_logged_in(_ContextStub(form_page))))

        no_nav = self._business_page()
        no_nav.locators['a[href*="/latest/home"]'] = _LocatorStub(count=0)
        self.assertFalse(asyncio.run(facebook_page_is_logged_in(_ContextStub(no_nav))))

        for name, page in (
            ("network", self._business_page(goto_error=TimeoutError("timeout"))),
            ("5xx", self._business_page(response_status=500)),
            ("unexpected", self._business_page(final_url="https://example.com/")),
        ):
            with self.subTest(name=name), self.assertRaises(Exception):
                asyncio.run(facebook_page_is_logged_in(_ContextStub(page)))

    def _instagram_page(self, *, final_url: str | None = None, **kwargs) -> _PageStub:
        page = _PageStub(final_url=final_url or INSTAGRAM_HOME_URL, **kwargs)
        page.locators['a[href^="/direct/inbox/"]'] = _LocatorStub(count=1)
        return page

    def _instagram_expect(self):
        return MagicMock(
            return_value=SimpleNamespace(
                not_to_have_count=AsyncMock(return_value=None)
            )
        )

    def test_instagram_true_false_and_raise(self):
        context = _ContextStub(self._instagram_page())
        with patch.object(instagram_main, "expect", self._instagram_expect()):
            self.assertTrue(asyncio.run(instagram_is_logged_in(context)))
        self.assertEqual(context.new_page_calls, 1)
        self.assertTrue(context.page.closed)

        for name, url in {
            "login": "https://www.instagram.com/accounts/login/",
            "challenge": "https://www.instagram.com/challenge/",
            "two_step": "https://www.instagram.com/two_step/",
        }.items():
            with self.subTest(name=name):
                context = _ContextStub(_PageStub(final_url=url))
                with patch.object(instagram_main, "expect", self._instagram_expect()):
                    self.assertFalse(asyncio.run(instagram_is_logged_in(context)))

        logged_out = self._instagram_page()
        logged_out.locators['a[href^="/direct/inbox/"]'] = _LocatorStub(count=0)
        with patch.object(instagram_main, "expect", self._instagram_expect()):
            self.assertFalse(
                asyncio.run(instagram_is_logged_in(_ContextStub(logged_out)))
            )

        for name, page in (
            ("network", self._instagram_page(goto_error=TimeoutError("timeout"))),
            ("5xx", self._instagram_page(response_status=502)),
            ("unexpected", self._instagram_page(final_url="https://example.com/")),
        ):
            with self.subTest(name=name), self.assertRaises(Exception):
                with patch.object(instagram_main, "expect", self._instagram_expect()):
                    asyncio.run(instagram_is_logged_in(_ContextStub(page)))


# ---------------------------------------------------------------------------
# CLI: check 0/10/1 and uploads 0/10/1
# ---------------------------------------------------------------------------


class _CliBase(unittest.TestCase):
    def _run(self, argv, *, token=TOKEN):
        with patch.dict(os.environ, {"MLX_API_TOKEN": token}):
            with redirect_stdout(io.StringIO()) as out, redirect_stderr(
                io.StringIO()
            ) as err:
                code = sau_cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def _session_patches(self, command_module, probe_result):
        playwright_cm = _AsyncCM(object())
        session = Namespace(context=object())
        session_cm = _AsyncCM(session)
        session_factory = MagicMock(return_value=session_cm)
        probe = (
            probe_result
            if isinstance(probe_result, AsyncMock)
            else AsyncMock(return_value=probe_result)
        )
        patches = (
            patch.object(command_module, "async_playwright", lambda: playwright_cm),
            patch.object(command_module, "browser_session", new=session_factory),
            patch.object(command_module, "is_logged_in", new=probe),
        )
        return playwright_cm, session_cm, session_factory, probe, patches

    def _assert_session_once(self, playwright_cm, session_cm):
        self.assertEqual(playwright_cm.enter_calls, 1)
        self.assertEqual(playwright_cm.exit_calls, 1)
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)


class FacebookCliTests(_CliBase):
    def _check(self, probe_result):
        playwright_cm, session_cm, factory, probe, patches = self._session_patches(
            facebook_command, probe_result
        )
        with patches[0], patches[1], patches[2]:
            code, out, err = self._run(
                [
                    "facebook",
                    "check",
                    "--folder-id",
                    FOLDER,
                    "--profile-id",
                    PROFILE,
                ]
            )
        return code, out, err, playwright_cm, session_cm, factory, probe

    def test_check_mlx_returns_0_10_1(self):
        code, out, _, p_cm, s_cm, factory, probe = self._check(True)
        self.assertEqual(code, 0)
        self.assertIn("valid", out)
        kwargs = factory.call_args.kwargs
        self.assertEqual(kwargs["managed"].target, MultiloginTarget(FOLDER, PROFILE))
        self.assertEqual(kwargs["launch_kwargs"], FACEBOOK_LAUNCH_KWARGS)
        self.assertEqual(kwargs["context_kwargs"], FACEBOOK_CONTEXT_KWARGS)
        self.assertFalse(kwargs["init_script"])
        self.assertNotIn("proxy", kwargs["launch_kwargs"])
        probe.assert_awaited_once()
        self._assert_session_once(p_cm, s_cm)

        code, out, err, p_cm, s_cm, _, _ = self._check(False)
        self.assertEqual(code, 10)
        self.assertIn("profile_id=profile-23", err)
        self.assertNotIn("valid", out)
        self._assert_session_once(p_cm, s_cm)

        code, _, err, p_cm, s_cm, _, _ = self._check(
            AsyncMock(side_effect=RuntimeError("network down"))
        )
        self.assertEqual(code, 1)
        self.assertIn("network down", err)
        self._assert_session_once(p_cm, s_cm)

    def test_upload_video_mlx_uses_none_account_and_one_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            media = _write_media(directory)
            playwright_cm, session_cm, factory, probe, patches = self._session_patches(
                facebook_command, True
            )
            fake_app = MagicMock()
            fake_app.main = AsyncMock()
            builder = MagicMock(return_value=fake_app)
            resolve_account = MagicMock()
            setup = AsyncMock()

            with patches[0], patches[1], patches[2], patch.object(
                facebook_command, "FacebookPost", new=builder
            ), patch.object(
                facebook_command, "resolve_account_file", new=resolve_account
            ), patch.object(facebook_command, "facebook_setup", new=setup):
                code, out, _ = self._run(
                    [
                        "facebook",
                        "upload-video",
                        "--folder-id",
                        FOLDER,
                        "--profile-id",
                        PROFILE,
                        "--file",
                        str(media),
                        "--title",
                        "标题",
                        "--proxy",
                        "http://cli-proxy:8080",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertIn("Facebook video upload submitted", out)
        kwargs = factory.call_args.kwargs
        self.assertIsNone(kwargs["account_file"])
        self.assertEqual(kwargs["launch_kwargs"], FACEBOOK_LAUNCH_KWARGS)
        self.assertNotIn("proxy", kwargs["launch_kwargs"])
        probe.assert_awaited_once_with(session_cm.value.context)
        builder.assert_called_once_with(
            title="标题",
            file_path=[media],
            description="",
            tags=[],
            account_file=None,
            proxy=None,
            headless=False,
        )
        fake_app.main.assert_awaited_once_with(session=session_cm.value)
        resolve_account.assert_not_called()
        setup.assert_not_awaited()
        self._assert_session_once(playwright_cm, session_cm)

    def test_upload_note_mlx_uses_none_account_and_one_session(self):
        with tempfile.TemporaryDirectory() as directory:
            image = _write_media(directory, "image.png")
            playwright_cm, session_cm, factory, probe, patches = self._session_patches(
                facebook_command, True
            )
            fake_app = MagicMock()
            fake_app.main = AsyncMock()
            builder = MagicMock(return_value=fake_app)
            resolve_account = MagicMock()

            with patches[0], patches[1], patches[2], patch.object(
                facebook_command, "FacebookPost", new=builder
            ), patch.object(
                facebook_command, "resolve_account_file", new=resolve_account
            ):
                code, out, _ = self._run(
                    [
                        "facebook",
                        "upload-note",
                        "--folder-id",
                        FOLDER,
                        "--profile-id",
                        PROFILE,
                        "--images",
                        str(image),
                        "--title",
                        "标题",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertIn("Facebook image post submitted", out)
        self.assertIsNone(factory.call_args.kwargs["account_file"])
        builder.assert_called_once()
        self.assertIsNone(builder.call_args.kwargs["account_file"])
        fake_app.main.assert_awaited_once_with(session=session_cm.value)
        probe.assert_awaited_once()
        resolve_account.assert_not_called()
        self._assert_session_once(playwright_cm, session_cm)

    def test_upload_mlx_logged_out_is_10_and_never_publishes(self):
        with tempfile.TemporaryDirectory() as directory:
            media = _write_media(directory)
            fake_app = MagicMock()
            fake_app.main = AsyncMock()
            playwright_cm, session_cm, factory, probe, patches = self._session_patches(
                facebook_command, False
            )

            with patches[0], patches[1], patches[2], patch.object(
                facebook_command, "FacebookPost", new=MagicMock(return_value=fake_app)
            ):
                code, _, err = self._run(
                    [
                        "facebook",
                        "upload-video",
                        "--folder-id",
                        FOLDER,
                        "--profile-id",
                        PROFILE,
                        "--file",
                        str(media),
                        "--title",
                        "标题",
                    ]
                )

        self.assertEqual(code, 10)
        self.assertIn("profile_id=profile-23", err)
        fake_app.main.assert_not_awaited()
        self._assert_session_once(playwright_cm, session_cm)

    def test_upload_mlx_publish_failure_is_1_and_still_exits_session_once(self):
        with tempfile.TemporaryDirectory() as directory:
            media = _write_media(directory)
            fake_app = MagicMock()
            fake_app.main = AsyncMock(side_effect=RuntimeError("publish failed"))
            playwright_cm, session_cm, factory, probe, patches = self._session_patches(
                facebook_command, True
            )

            with patches[0], patches[1], patches[2], patch.object(
                facebook_command, "FacebookPost", new=MagicMock(return_value=fake_app)
            ):
                code, _, err = self._run(
                    [
                        "facebook",
                        "upload-video",
                        "--folder-id",
                        FOLDER,
                        "--profile-id",
                        PROFILE,
                        "--file",
                        str(media),
                        "--title",
                        "标题",
                    ]
                )

        self.assertEqual(code, 1)
        self.assertIn("publish failed", err)
        self._assert_session_once(playwright_cm, session_cm)

    def test_upload_mlx_mid_upload_login_required_maps_to_10(self):
        with tempfile.TemporaryDirectory() as directory:
            media = _write_media(directory)
            fake_app = MagicMock()
            fake_app.main = AsyncMock(
                side_effect=LoginRequiredError("2FA required mid-upload")
            )
            playwright_cm, session_cm, factory, probe, patches = self._session_patches(
                facebook_command, True
            )

            with patches[0], patches[1], patches[2], patch.object(
                facebook_command, "FacebookPost", new=MagicMock(return_value=fake_app)
            ):
                code, _, err = self._run(
                    [
                        "facebook",
                        "upload-video",
                        "--folder-id",
                        FOLDER,
                        "--profile-id",
                        PROFILE,
                        "--file",
                        str(media),
                        "--title",
                        "标题",
                    ]
                )

        self.assertEqual(code, 10)
        self.assertIn("2FA required mid-upload", err)
        self._assert_session_once(playwright_cm, session_cm)

    def test_local_upload_does_not_touch_browser_session(self):
        with tempfile.TemporaryDirectory() as directory:
            media = _write_media(directory)
            legacy = AsyncMock()
            session_factory = MagicMock()

            with patch.object(
                facebook_command, "upload_facebook_video", new=legacy
            ), patch.object(
                facebook_command, "browser_session", new=session_factory
            ):
                code, out, _ = self._run(
                    [
                        "facebook",
                        "upload-video",
                        "--account",
                        "creator",
                        "--file",
                        str(media),
                        "--title",
                        "标题",
                    ],
                    token="",
                )

        self.assertEqual(code, 0)
        self.assertIn("Facebook video upload submitted", out)
        session_factory.assert_not_called()
        self.assertIsNone(legacy.await_args.kwargs.get("target"))


class FacebookPageCliTests(_CliBase):
    def _check(self, probe_result):
        playwright_cm, session_cm, factory, probe, patches = self._session_patches(
            facebook_page_command, probe_result
        )
        with patches[0], patches[1], patches[2]:
            code, out, err = self._run(
                [
                    "facebook-page",
                    "check",
                    "--folder-id",
                    FOLDER,
                    "--profile-id",
                    PROFILE,
                ]
            )
        return code, out, err, playwright_cm, session_cm, factory, probe

    def test_check_mlx_returns_0_10_1(self):
        code, out, _, p_cm, s_cm, factory, probe = self._check(True)
        self.assertEqual(code, 0)
        self.assertIn("valid", out)
        kwargs = factory.call_args.kwargs
        self.assertEqual(kwargs["managed"].target, MultiloginTarget(FOLDER, PROFILE))
        self.assertEqual(kwargs["launch_kwargs"], FACEBOOK_PAGE_LAUNCH_KWARGS)
        self.assertEqual(kwargs["context_kwargs"], FACEBOOK_PAGE_CONTEXT_KWARGS)
        self.assertFalse(kwargs["init_script"])
        probe.assert_awaited_once()
        self._assert_session_once(p_cm, s_cm)

        code, out, err, p_cm, s_cm, _, _ = self._check(False)
        self.assertEqual(code, 10)
        self.assertIn("profile_id=profile-23", err)
        self.assertEqual(out.strip(), "")
        self._assert_session_once(p_cm, s_cm)

        code, _, err, p_cm, s_cm, _, _ = self._check(
            AsyncMock(side_effect=RuntimeError("launcher down"))
        )
        self.assertEqual(code, 1)
        self.assertIn("launcher down", err)
        self._assert_session_once(p_cm, s_cm)

    def _upload(self, action, probe_result, *, publish_error=None):
        with tempfile.TemporaryDirectory() as directory:
            media = _write_media(
                directory, "clip.mp4" if action == "upload-video" else "image.png"
            )
            playwright_cm, session_cm, factory, probe, patches = self._session_patches(
                facebook_page_command, probe_result
            )
            fake_app = MagicMock()
            fake_app.upload = AsyncMock(
                return_value={"status": "published"},
                side_effect=publish_error,
            )
            builder = MagicMock(return_value=fake_app)
            resolve_account = MagicMock()
            cookie_auth = AsyncMock()

            argv = [
                "facebook-page",
                action,
                "--folder-id",
                FOLDER,
                "--profile-id",
                PROFILE,
                "--title",
                "标题",
            ]
            argv += ["--file", str(media)] if action == "upload-video" else [
                "--images",
                str(media),
            ]

            with patches[0], patches[1], patches[2], patch.object(
                facebook_page_command, "_build_uploader", new=builder
            ), patch.object(
                facebook_page_command, "resolve_account_file", new=resolve_account
            ), patch.object(
                facebook_page_command, "meta_cookie_auth", new=cookie_auth
            ):
                code, out, err = self._run(argv)

        return code, out, err, builder, fake_app, factory, playwright_cm, session_cm, resolve_account, cookie_auth, probe

    def test_upload_video_and_note_mlx_use_none_account(self):
        for action in ("upload-video", "upload-note"):
            with self.subTest(action=action):
                (
                    code,
                    out,
                    _,
                    builder,
                    fake_app,
                    factory,
                    p_cm,
                    s_cm,
                    resolve_account,
                    cookie_auth,
                    probe,
                ) = self._upload(action, True)
                self.assertEqual(code, 0)
                self.assertIn('"status": "published"', out)
                self.assertIsNone(factory.call_args.kwargs["account_file"])
                self.assertEqual(
                    factory.call_args.kwargs["launch_kwargs"],
                    FACEBOOK_PAGE_LAUNCH_KWARGS,
                )
                self.assertIsNone(builder.call_args.args[1])
                fake_app.upload.assert_awaited_once_with(session=s_cm.value)
                probe.assert_awaited_once()
                resolve_account.assert_not_called()
                cookie_auth.assert_not_awaited()
                self._assert_session_once(p_cm, s_cm)

    def test_upload_mlx_logged_out_is_10(self):
        code, _, err, builder, fake_app, _, p_cm, s_cm, _, _, probe = self._upload(
            "upload-video", False
        )
        self.assertEqual(code, 10)
        self.assertIn("profile_id=profile-23", err)
        fake_app.upload.assert_not_awaited()
        probe.assert_awaited_once()
        self._assert_session_once(p_cm, s_cm)

    def test_upload_mlx_failure_is_1(self):
        code, _, err, *_rest = self._upload(
            "upload-note", True, publish_error=RuntimeError("composer failed")
        )
        self.assertEqual(code, 1)
        self.assertIn("composer failed", err)
        p_cm, s_cm = _rest[3], _rest[4]
        self._assert_session_once(p_cm, s_cm)

    def test_local_upload_does_not_touch_browser_session(self):
        with tempfile.TemporaryDirectory() as directory:
            media = _write_media(directory)
            legacy = AsyncMock(return_value={})
            session_factory = MagicMock()
            with patch.object(
                facebook_page_command, "upload_meta_content", new=legacy
            ), patch.object(
                facebook_page_command, "browser_session", new=session_factory
            ):
                code, _, _ = self._run(
                    [
                        "facebook-page",
                        "upload-video",
                        "--account",
                        "creator",
                        "--file",
                        str(media),
                        "--title",
                        "标题",
                    ],
                    token="",
                )
        self.assertEqual(code, 0)
        session_factory.assert_not_called()
        self.assertIsNone(legacy.await_args.kwargs.get("target"))


class InstagramCliTests(_CliBase):
    def _check(self, probe_result):
        playwright_cm, session_cm, factory, probe, patches = self._session_patches(
            instagram_command, probe_result
        )
        logger = MagicMock()
        with patches[0], patches[1], patches[2], patch.object(
            instagram_command, "logger", new=logger
        ):
            code, out, err = self._run(
                [
                    "instagram",
                    "check",
                    "--folder-id",
                    FOLDER,
                    "--profile-id",
                    PROFILE,
                ]
            )
        return code, out, err, playwright_cm, session_cm, factory, probe, logger

    def test_check_mlx_returns_0_10_1(self):
        code, out, _, p_cm, s_cm, factory, probe, logger = self._check(True)
        self.assertEqual(code, 0)
        self.assertIn("valid", out)
        kwargs = factory.call_args.kwargs
        self.assertEqual(kwargs["managed"].target, MultiloginTarget(FOLDER, PROFILE))
        self.assertEqual(kwargs["launch_kwargs"], INSTAGRAM_LAUNCH_KWARGS)
        self.assertEqual(kwargs["context_kwargs"], INSTAGRAM_CONTEXT_KWARGS)
        self.assertFalse(kwargs["init_script"])
        probe.assert_awaited_once()
        logger.info.assert_called_once()
        self.assertIn("账号一致性未校验", logger.info.call_args.args[0])
        self.assertIn(PROFILE, logger.info.call_args.args)
        self._assert_session_once(p_cm, s_cm)

        code, out, err, p_cm, s_cm, _, _, logger = self._check(False)
        self.assertEqual(code, 10)
        self.assertIn("profile_id=profile-23", err)
        self.assertEqual(out.strip(), "")
        logger.info.assert_called_once()
        self._assert_session_once(p_cm, s_cm)

        code, _, err, p_cm, s_cm, _, _, logger = self._check(
            AsyncMock(side_effect=RuntimeError("profile busy"))
        )
        self.assertEqual(code, 1)
        self.assertIn("profile busy", err)
        logger.info.assert_called_once()
        self._assert_session_once(p_cm, s_cm)

    def _upload(self, action, probe_result, *, publish_error=None):
        with tempfile.TemporaryDirectory() as directory:
            media = _write_media(
                directory, "clip.mp4" if action == "upload-video" else "image.png"
            )
            playwright_cm, session_cm, factory, probe, patches = self._session_patches(
                instagram_command, probe_result
            )
            fake_app = MagicMock()
            fake_app.upload = AsyncMock(
                return_value={"status": "published"},
                side_effect=publish_error,
            )
            builder = MagicMock(return_value=fake_app)
            resolve_account = MagicMock()
            logger = MagicMock()

            argv = [
                "instagram",
                action,
                "--folder-id",
                FOLDER,
                "--profile-id",
                PROFILE,
                "--title",
                "caption",
            ]
            argv += ["--file", str(media)] if action == "upload-video" else [
                "--images",
                str(media),
            ]

            with patches[0], patches[1], patches[2], patch.object(
                instagram_command, "_build_uploader", new=builder
            ), patch.object(
                instagram_command, "resolve_account_file", new=resolve_account
            ), patch.object(
                instagram_command, "logger", new=logger
            ):
                code, out, err = self._run(argv)

        return (
            code,
            out,
            err,
            builder,
            fake_app,
            factory,
            playwright_cm,
            session_cm,
            resolve_account,
            logger,
            probe,
        )

    def test_upload_video_and_note_mlx_skip_identity_and_cookie_io(self):
        for action in ("upload-video", "upload-note"):
            with self.subTest(action=action):
                (
                    code,
                    out,
                    _,
                    builder,
                    fake_app,
                    factory,
                    p_cm,
                    s_cm,
                    resolve_account,
                    logger,
                    probe,
                ) = self._upload(action, True)
                self.assertEqual(code, 0)
                self.assertIn('"status": "published"', out)
                self.assertIsNone(factory.call_args.kwargs["account_file"])
                self.assertEqual(
                    factory.call_args.kwargs["launch_kwargs"],
                    INSTAGRAM_LAUNCH_KWARGS,
                )
                self.assertIsNone(builder.call_args.args[1])
                fake_app.upload.assert_awaited_once_with(session=s_cm.value)
                probe.assert_awaited_once()
                resolve_account.assert_not_called()
                logger.info.assert_called_once()
                self.assertIn("账号一致性未校验", logger.info.call_args.args[0])
                self.assertIn("profile-23", logger.info.call_args.args)
                self._assert_session_once(p_cm, s_cm)

    def test_upload_mlx_logged_out_is_10_without_identity_log(self):
        code, _, err, builder, fake_app, _, p_cm, s_cm, _, logger, probe = self._upload(
            "upload-video", False
        )
        self.assertEqual(code, 10)
        self.assertIn("profile_id=profile-23", err)
        fake_app.upload.assert_not_awaited()
        probe.assert_awaited_once()
        logger.info.assert_not_called()
        self._assert_session_once(p_cm, s_cm)

    def test_upload_mlx_failure_is_1(self):
        code, _, err, *_rest = self._upload(
            "upload-note", True, publish_error=RuntimeError("publish failed")
        )
        self.assertEqual(code, 1)
        self.assertIn("publish failed", err)
        p_cm, s_cm = _rest[3], _rest[4]
        self._assert_session_once(p_cm, s_cm)

    def test_local_upload_does_not_touch_browser_session(self):
        with tempfile.TemporaryDirectory() as directory:
            media = _write_media(directory)
            legacy = AsyncMock(return_value={})
            session_factory = MagicMock()
            with patch.object(
                instagram_command, "upload_instagram_content", new=legacy
            ), patch.object(
                instagram_command, "browser_session", new=session_factory
            ):
                code, _, _ = self._run(
                    [
                        "instagram",
                        "upload-video",
                        "--account",
                        "creator",
                        "--file",
                        str(media),
                        "--title",
                        "caption",
                    ],
                    token="",
                )
        self.assertEqual(code, 0)
        session_factory.assert_not_called()
        self.assertIsNone(legacy.await_args.kwargs.get("target"))


if __name__ == "__main__":
    unittest.main()
