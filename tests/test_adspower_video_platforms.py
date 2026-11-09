# -*- coding: utf-8 -*-
"""Video-platform AdsPower coverage (ticket 13).

Every video command must reach the shared managed seam with an AdsPower
provider, never build a cookie path, never call ``launch`` / ``new_context`` /
``storage_state``, and never touch the network.  The module list mirrors the
ticket's video-platform scope; article/identity/Meta-specific parity is ticket
14.
"""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import asynccontextmanager, redirect_stderr, redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

import sau_cli
from sau_commands import (
    alipay,
    baijiahao,
    douyin,
    hupu,
    kuaishou,
    tencent,
    tiktok,
    weibo,
    xiaohongshu,
    youtube,
)
from tests.fakes import (
    FakeAdspowerClient,
    FakeBrowser,
    FakeContext,
    FakePlaywright,
)

KEY = "SENTINEL-ADSPOWER-KEY-video13"
PROFILE = "profile-video-13"
WS_URL = "ws://127.0.0.1:9222/devtools/browser/video13"

PLATFORMS = (
    ("alipay", alipay, "_build_alipay_uploader", "alipay_upload_video"),
    ("baijiahao", baijiahao, "BaiJiaHaoVideo", "main"),
    ("douyin", douyin, "_build_video_uploader", "douyin_upload_video"),
    ("hupu", hupu, "_build_uploader", "upload"),
    ("kuaishou", kuaishou, "_build_video_uploader", "main"),
    ("tencent", tencent, "TencentVideo", "tencent_upload_video"),
    ("tiktok", tiktok, "_build_video_uploader", "upload"),
    ("weibo", weibo, "_build_weibo_uploader", "main"),
    ("xiaohongshu", xiaohongshu, "_build_video_uploader", "xiaohongshu_upload_video"),
    ("youtube", youtube, "_build_youtube_uploader", "main"),
)


class _AsyncCM:
    def __init__(self, value=None) -> None:
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _run(argv):
    with patch.dict(
        os.environ, {"ADSPOWER_API_KEY": KEY}, clear=True
    ):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(
            io.StringIO()
        ) as err:
            code = sau_cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class VideoPlatformCoverageTests(unittest.TestCase):
    def _patches(self, module, client, playwright):
        calls: list[dict] = []
        browser_session = module.browser_session

        @asynccontextmanager
        async def recording_browser_session(*args, **kwargs):
            calls.append(kwargs)
            async with browser_session(*args, **kwargs) as session:
                yield session

        return calls, (
            patch.object(module, "async_playwright", lambda: _AsyncCM(playwright)),
            patch.object(module, "browser_session", new=recording_browser_session),
            patch.object(module, "is_logged_in", new=AsyncMock(return_value=True)),
            patch.object(
                module,
                "resolve_account_file",
                new=MagicMock(
                    side_effect=AssertionError(
                        "managed mode must not build a cookie path"
                    )
                ),
            ),
            patch(
                "sau_commands.browser.AdspowerClient",
                MagicMock(return_value=client),
            ),
        )

    def _assert_managed_session(self, calls, client, playwright, browser, context):
        self.assertEqual(len(calls), 1)
        kwargs = calls[0]
        provider = kwargs["managed"]
        self.assertEqual(provider.mode, "adspower")
        self.assertEqual(provider.profile_id, PROFILE)
        self.assertIsNone(kwargs.get("account_file"))
        self.assertNotIn("multilogin", kwargs)

        self.assertEqual(client.start_calls, [(PROFILE, True)])
        self.assertEqual(client.stop_calls, [PROFILE])
        self.assertEqual(playwright.chromium.launch_calls, [])
        self.assertEqual(len(playwright.chromium.connect_calls), 1)
        self.assertEqual(
            playwright.chromium.connect_calls[0]["url"], WS_URL
        )
        self.assertEqual(browser.new_context_calls, [])
        self.assertEqual(context.storage_state_calls, [])

    def test_check_uses_the_adspower_profile_for_every_video_platform(self):
        for name, module, _builder, _method in PLATFORMS:
            with self.subTest(platform=name):
                client = FakeAdspowerClient(ws_url=WS_URL)
                playwright = FakePlaywright()
                context = FakeContext()
                browser = FakeBrowser([context], allow_new_context=False)
                playwright.chromium.queue_connect_browser(browser)
                calls, patches = self._patches(module, client, playwright)
                with patches[0], patches[1], patches[2], patches[3], patches[4]:
                    code, out, err = _run(
                        [name, "check", "--profile-id", PROFILE]
                    )
                self.assertEqual(code, 0, err)
                self.assertEqual(out.strip(), "valid")
                self._assert_managed_session(
                    calls, client, playwright, browser, context
                )

    def test_upload_video_uses_the_adspower_profile_for_every_video_platform(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = os.path.join(tmp_dir, "demo.mp4")
            with open(video, "wb") as handle:
                handle.write(b"video")

            for name, module, builder, method in PLATFORMS:
                with self.subTest(platform=name):
                    client = FakeAdspowerClient(ws_url=WS_URL)
                    playwright = FakePlaywright()
                    context = FakeContext()
                    browser = FakeBrowser([context], allow_new_context=False)
                    playwright.chromium.queue_connect_browser(browser)

                    app = MagicMock()
                    setattr(app, method, AsyncMock())

                    calls, patches = self._patches(module, client, playwright)
                    with (
                        patches[0],
                        patches[1],
                        patches[2],
                        patches[3],
                        patches[4],
                        patch.object(module, builder, MagicMock(return_value=app)),
                    ):
                        code, out, err = _run(
                            [
                                name,
                                "upload-video",
                                "--profile-id",
                                PROFILE,
                                "--file",
                                video,
                                "--title",
                                "测试标题",
                            ]
                        )

                    self.assertEqual(code, 0, err)
                    self.assertIn("submitted", out)
                    self._assert_managed_session(
                        calls, client, playwright, browser, context
                    )
                    getattr(app, method).assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
