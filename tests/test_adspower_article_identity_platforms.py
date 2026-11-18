# -*- coding: utf-8 -*-
"""AdsPower Profile handling for Meta uploads, login checks and identity logs."""

from __future__ import annotations

import asyncio
import io
import os
import tempfile
import unittest
from contextlib import ExitStack, asynccontextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import sau_cli
from sau_commands import facebook as facebook_command
from sau_commands import facebook_page as facebook_page_command
from sau_commands import instagram as instagram_command
from sau_commands.browser import identity_unverified_format
from tests.fakes import (
    FakeAdspowerClient,
    FakeBrowser,
    FakeContext,
    FakePlaywright,
)
from uploader.meta_uploader.insgraph_uploader import main as instagram_main
from uploader.meta_uploader.insgraph_uploader.main import (
    INSTAGRAM_HOME_URL,
    InstagramUploader,
)
from utils.browser_session import BrowserSession

KEY = "SENTINEL-ADSPOWER-KEY-ticket14"
PROFILE = "profile-14"
WS_URL = "ws://127.0.0.1:9222/devtools/browser/ticket14"

MLX_IDENTITY_FORMAT = "账号一致性未校验：以 Multilogin Profile 为身份（profile_id={}）"
ADSPOWER_IDENTITY_FORMAT = "账号一致性未校验：以 AdsPower Profile 为身份（profile_id={}）"


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


def _run(argv):
    with tempfile.TemporaryDirectory() as home, patch.dict(
        os.environ, {"ADSPOWER_API_KEY": KEY, "HOME": home, "USERPROFILE": home}, clear=True
    ):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(
            io.StringIO()
        ) as err:
            code = sau_cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class MetaManagedProxyTests(unittest.TestCase):
    """Meta uploads must let the Profile own egress IP and fingerprint."""

    def _uploader_session_patches(self, module):
        session = SimpleNamespace(context=object())
        return (
            patch.object(module, "async_playwright", lambda: _AsyncCM(object())),
            patch.object(
                module,
                "browser_session",
                new=MagicMock(return_value=_AsyncCM(session)),
            ),
            patch.object(
                module, "is_logged_in", new=AsyncMock(return_value=True)
            ),
        )

    def test_facebook_managed_upload_builds_the_post_without_proxy(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "clip.mp4"
            media.write_bytes(b"media")
            app = MagicMock()
            app.main = AsyncMock()
            builder = MagicMock(return_value=app)
            patches = self._uploader_session_patches(facebook_command)
            with (
                patches[0],
                patches[1],
                patches[2],
                patch.object(
                    facebook_command, "FacebookPost", new=builder
                ),
            ):
                code, _, err = _run(
                    [
                        "facebook",
                        "upload-video",
                        "--profile-id",
                        "profile-14",
                        "--file",
                        str(media),
                        "--title",
                        "标题",
                        "--proxy",
                        "http://cli-proxy:8080",
                    ]
                )

        self.assertEqual(code, 0, err)
        self.assertIsNone(builder.call_args.kwargs["proxy"])
        self.assertIsNone(builder.call_args.kwargs["account_file"])

    def test_facebook_page_managed_upload_does_not_forward_proxy(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "clip.mp4"
            media.write_bytes(b"media")
            app = MagicMock()
            app.upload = AsyncMock(return_value={"status": "published"})
            builder = MagicMock(return_value=app)
            patches = self._uploader_session_patches(facebook_page_command)
            with (
                patches[0],
                patches[1],
                patches[2],
                patch.object(
                    facebook_page_command, "_build_uploader", new=builder
                ),
            ):
                code, _, err = _run(
                    [
                        "facebook-page",
                        "upload-video",
                        "--profile-id",
                        "profile-14",
                        "--file",
                        str(media),
                        "--title",
                        "标题",
                        "--proxy",
                        "http://cli-proxy:8080",
                    ]
                )

        self.assertEqual(code, 0, err)
        request = builder.call_args.args[0]
        self.assertIsNone(request.proxy)

    def test_instagram_managed_upload_does_not_forward_proxy(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "image.png"
            image.write_bytes(b"image")
            app = MagicMock()
            app.upload = AsyncMock(return_value={"status": "published"})
            builder = MagicMock(return_value=app)
            patches = self._uploader_session_patches(instagram_command)
            with (
                patches[0],
                patches[1],
                patches[2],
                patch.object(
                    instagram_command, "_build_uploader", new=builder
                ),
            ):
                code, _, err = _run(
                    [
                        "instagram",
                        "upload-note",
                        "--profile-id",
                        "profile-14",
                        "--images",
                        str(image),
                        "--title",
                        "标题",
                        "--proxy",
                        "http://cli-proxy:8080",
                    ]
                )

        self.assertEqual(code, 0, err)
        request = builder.call_args.args[0]
        self.assertIsNone(request.proxy)


class _SeamHarness:
    """Run a platform command through the real managed lifecycle with fakes."""

    def start_seam(self, module, *, logger_attr=None, logged_in=True):
        client = FakeAdspowerClient(ws_url=WS_URL)
        playwright = FakePlaywright()
        context = FakeContext()
        browser = FakeBrowser([context], allow_new_context=False)
        playwright.chromium.queue_connect_browser(browser)

        calls: list[dict] = []
        real_browser_session = module.browser_session

        @asynccontextmanager
        async def recording_browser_session(*args, **kwargs):
            calls.append(kwargs)
            async with real_browser_session(*args, **kwargs) as session:
                yield session

        stack = ExitStack()
        stack.enter_context(
            patch.object(module, "async_playwright", lambda: _AsyncCM(playwright))
        )
        stack.enter_context(
            patch.object(module, "browser_session", new=recording_browser_session)
        )
        stack.enter_context(
            patch.object(
                module, "is_logged_in", new=AsyncMock(return_value=logged_in)
            )
        )
        stack.enter_context(
            patch(
                "sau_commands.browser.AdspowerClient",
                MagicMock(return_value=client),
            )
        )
        logger = None
        if logger_attr is not None:
            logger = MagicMock()
            stack.enter_context(patch.object(module, logger_attr, new=logger))
        return stack, calls, client, playwright, browser, context, logger

    def assert_managed_session(
        self, calls, client, playwright, browser, context
    ):
        self.assertEqual(len(calls), 1)
        kwargs = calls[0]
        provider = kwargs["managed"]
        self.assertEqual(provider.mode, "adspower")
        self.assertEqual(provider.profile_id, PROFILE)
        self.assertIsNone(kwargs.get("account_file"))
        self.assertNotIn("multilogin", kwargs)
        self.assertEqual([call[0] for call in client.start_calls], [PROFILE])
        self.assertEqual(client.stop_calls, [PROFILE])
        self.assertEqual(playwright.chromium.launch_calls, [])
        self.assertEqual(len(playwright.chromium.connect_calls), 1)
        self.assertEqual(playwright.chromium.connect_calls[0]["url"], WS_URL)
        self.assertEqual(browser.new_context_calls, [])
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.add_init_script_calls, [])
        self.assertEqual(context.forbidden_calls, [])


class IdentityFormatTests(unittest.TestCase):
    def test_mlx_identity_wording_is_byte_identical(self):
        self.assertEqual(identity_unverified_format(mode="multilogin"), MLX_IDENTITY_FORMAT)

    def test_adspower_identity_wording_is_provider_specific(self):
        self.assertEqual(
            identity_unverified_format(mode="adspower"), ADSPOWER_IDENTITY_FORMAT
        )


class InstagramManagedCheckTests(_SeamHarness, unittest.TestCase):
    def test_check_reports_that_the_profile_owns_the_instagram_identity(self):
        stack, calls, client, playwright, browser, context, logger = self.start_seam(
            instagram_command, logger_attr="logger"
        )
        with stack:
            code, out, err = _run(["instagram", "check", "--profile-id", PROFILE])

        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "valid")
        self.assert_managed_session(calls, client, playwright, browser, context)
        logger.info.assert_called_once_with(ADSPOWER_IDENTITY_FORMAT, PROFILE)


class MetaManagedSeamTests(_SeamHarness, unittest.TestCase):
    CASES = (
        (facebook_command, "facebook", "FACEBOOK_LAUNCH_KWARGS"),
        (facebook_page_command, "facebook-page", "FACEBOOK_PAGE_LAUNCH_KWARGS"),
        (instagram_command, "instagram", "INSTAGRAM_LAUNCH_KWARGS"),
    )

    def test_meta_check_uses_adspower_profile_without_launch_or_context(self):
        for module, name, launch_constant in self.CASES:
            with self.subTest(platform=name):
                stack, calls, client, playwright, browser, context, _ = (
                    self.start_seam(module)
                )
                with stack:
                    code, out, err = _run(
                        [name, "check", "--profile-id", PROFILE]
                    )

                self.assertEqual(code, 0, err)
                self.assertEqual(out.strip(), "valid")
                self.assert_managed_session(
                    calls, client, playwright, browser, context
                )
                launch_kwargs = calls[0].get("launch_kwargs")
                if launch_kwargs is not None:
                    self.assertNotIn("proxy", launch_kwargs)
                self.assertEqual(
                    calls[0].get("launch_kwargs"),
                    getattr(module, launch_constant),
                )


class _InstagramLocator:
    def __init__(self, count: int, href: str = "") -> None:
        self._count = count
        self._href = href

    async def count(self) -> int:
        return self._count

    def filter(self, **kwargs):
        return self

    async def get_attribute(self, name: str):
        return self._href


class _InstagramPage:
    def __init__(self) -> None:
        self.url = "about:blank"
        self.closed = False

    def set_default_timeout(self, ms: int) -> None:
        pass

    async def goto(self, url: str, **kwargs):
        self.url = INSTAGRAM_HOME_URL
        return SimpleNamespace(status=200)

    def locator(self, selector: str):
        if selector == 'a[href^="/direct/inbox/"]':
            return _InstagramLocator(1)
        return _InstagramLocator(1, "/creator/")

    async def close(self) -> None:
        self.closed = True


class _InstagramContext:
    def __init__(self, page: _InstagramPage) -> None:
        self.page = page
        self.new_page_calls = 0
        self.storage_state_calls: list[object] = []

    async def new_page(self) -> _InstagramPage:
        self.new_page_calls += 1
        return self.page

    async def cookies(self, *args, **kwargs):
        return [{"name": "ds_user_id", "value": "42"}]

    async def storage_state(self, **kwargs):
        self.storage_state_calls.append(kwargs)
        raise AssertionError("managed mode must not write cookies")


class InstagramUploaderIdentityTests(unittest.TestCase):
    def test_adspower_upload_skips_identity_file_and_account_id_compare(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "clip.mp4"
            media.write_bytes(b"media")
            page = _InstagramPage()
            context = _InstagramContext(page)
            session = BrowserSession(
                browser=MagicMock(), context=context, mode="adspower"
            )
            app = InstagramUploader(
                None,
                title="caption",
                video_file=media,
                result_file=Path(tmp) / "result.json",
            )
            identity_file_reader = MagicMock()
            live_identity = AsyncMock(
                return_value={"user_id": "42", "username": "creator"}
            )
            app._upload_steps = AsyncMock(return_value=app.result)

            with (
                patch.object(
                    instagram_main, "instagram_identity", identity_file_reader
                ),
                patch.object(
                    instagram_main, "_multilogin_identity", live_identity
                ),
                patch.object(instagram_main, "_instagram_dom_login_outcome", AsyncMock(return_value=False)),
            ):
                asyncio.run(app.upload(session=session))

        identity_file_reader.assert_not_called()
        live_identity.assert_awaited_once()
        self.assertIsNone(app.account_file)
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(context.storage_state_calls, [])
        app._upload_steps.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
