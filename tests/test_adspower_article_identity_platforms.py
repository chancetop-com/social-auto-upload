# -*- coding: utf-8 -*-
"""AdsPower parity for article, identity-bound and Meta platforms (ticket 14).

The shared managed seam is already exercised by the video-platform suite; this
module locks the *platform-specific* constraints that must match the MLX
golden behavior while running under an AdsPower Profile:

* article / identity platforms (dayu, zhihu, xueqiu) never read cookies or
  ``.identity.json``, never compare account IDs, never inject a local timezone
  and never grant clipboard permissions;
* Meta platforms (facebook, facebook-page, instagram) never forward
  ``--proxy`` / environment proxies or launch kwargs, and Instagram never reads
  the identity file or compares account IDs;
* ``verify`` / ``delete`` stay local for every platform that defines them;
* identity-unverified logging keeps the MLX wording byte-identical and uses
  AdsPower-specific (never Multilogin) wording under AdsPower;
* bilibili rejects ``login`` / ``check`` / ``upload-video`` under AdsPower.

Everything is offline: provider HTTP is an in-process fake and CDP is a
hand-written ``FakePlaywright``.
"""

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
from sau_commands import bilibili as bilibili_command
from sau_commands import dayu as dayu_command
from sau_commands import facebook as facebook_command
from sau_commands import facebook_page as facebook_page_command
from sau_commands import instagram as instagram_command
from sau_commands import xueqiu as xueqiu_command
from sau_commands import zhihu as zhihu_command
from sau_commands.browser import identity_unverified_format, managed_timezone_hint
from tests.fakes import (
    FakeAdspowerClient,
    FakeBrowser,
    FakeContext,
    FakePlaywright,
)
from uploader.dayu_uploader import article as dayu_article_module
from uploader.dayu_uploader.article import DayuArticle
from uploader.meta_uploader.insgraph_uploader import main as instagram_main
from uploader.meta_uploader.insgraph_uploader.main import (
    INSTAGRAM_HOME_URL,
    InstagramUploader,
)
from uploader.xueqiu_uploader import article as xueqiu_article_module
from uploader.xueqiu_uploader.article import XueqiuArticle
from uploader.zhihu_uploader import article as zhihu_article_module
from uploader.zhihu_uploader.article import ZhihuArticle
from utils.browser_session import BrowserSession

KEY = "SENTINEL-ADSPOWER-KEY-ticket14"
PROFILE = "profile-14"
WS_URL = "ws://127.0.0.1:9222/devtools/browser/ticket14"

MLX_IDENTITY_FORMAT = "账号一致性未校验：以 Multilogin Profile 为身份（profile_id={}）"
MLX_IDENTITY_FORMAT_DETAILED = (
    MLX_IDENTITY_FORMAT + "，请调度侧确保 profile_id 与目标账号匹配。"
)
MLX_TIMEZONE_HINT = (
    "Multilogin 模式不写入时区；建议在 Profile 设置中将时区设为 Asia/Shanghai"
)
ADSPOWER_IDENTITY_FORMAT = "账号一致性未校验：以 AdsPower Profile 为身份（profile_id={}）"
ADSPOWER_IDENTITY_FORMAT_DETAILED = (
    ADSPOWER_IDENTITY_FORMAT + "，请调度侧确保 profile_id 与目标账号匹配。"
)
ADSPOWER_TIMEZONE_HINT = (
    "AdsPower 模式不写入时区；建议在 Profile 设置中将时区设为 Asia/Shanghai"
)


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
    with patch.dict(os.environ, {"ADSPOWER_API_KEY": KEY}, clear=True):
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
        self.assertIsNone(builder.call_args.args[1])

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
        self.assertIsNone(builder.call_args.args[1])


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
            patch.object(
                module,
                "resolve_account_file",
                new=MagicMock(
                    side_effect=AssertionError(
                        "managed mode must not build a cookie path"
                    )
                ),
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
        self.assertEqual(
            identity_unverified_format(mode="multilogin", detailed=True),
            MLX_IDENTITY_FORMAT_DETAILED,
        )
        self.assertEqual(managed_timezone_hint("multilogin"), MLX_TIMEZONE_HINT)

    def test_adspower_wording_is_provider_specific_and_never_multilogin(self):
        self.assertEqual(
            identity_unverified_format(mode="adspower"), ADSPOWER_IDENTITY_FORMAT
        )
        self.assertEqual(
            identity_unverified_format(mode="adspower", detailed=True),
            ADSPOWER_IDENTITY_FORMAT_DETAILED,
        )
        self.assertEqual(
            managed_timezone_hint("adspower"), ADSPOWER_TIMEZONE_HINT
        )
        for message in (
            ADSPOWER_IDENTITY_FORMAT,
            ADSPOWER_IDENTITY_FORMAT_DETAILED,
            ADSPOWER_TIMEZONE_HINT,
        ):
            self.assertNotIn("Multilogin", message)


class ArticleIdentityCheckTests(_SeamHarness, unittest.TestCase):
    CASES = (
        (dayu_command, "dayu", "dayu_logger", ADSPOWER_IDENTITY_FORMAT),
        (zhihu_command, "zhihu", "logger", ADSPOWER_IDENTITY_FORMAT_DETAILED),
        (xueqiu_command, "xueqiu", "logger", ADSPOWER_IDENTITY_FORMAT_DETAILED),
        (instagram_command, "instagram", "logger", ADSPOWER_IDENTITY_FORMAT),
    )

    def test_adspower_check_uses_profile_for_article_and_identity_platforms(self):
        for module, name, logger_attr, expected_format in self.CASES:
            with self.subTest(platform=name):
                stack, calls, client, playwright, browser, context, logger = (
                    self.start_seam(module, logger_attr=logger_attr)
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
                logger.info.assert_called_once_with(expected_format, PROFILE)
                self.assertNotIn("Multilogin", logger.info.call_args.args[0])


class ArticleIdentityUploadTests(_SeamHarness, unittest.TestCase):
    def _article_file(self, directory: str) -> Path:
        content = Path(directory) / "article.html"
        content.write_text("<p>正文</p>", encoding="utf-8")
        return content

    def test_dayu_upload_article_does_not_inject_timezone_or_read_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = self._article_file(tmp)
            app = MagicMock()
            app.main = AsyncMock(return_value={"success": True})
            builder = MagicMock(return_value=app)
            stack, calls, client, playwright, browser, context, logger = (
                self.start_seam(dayu_command, logger_attr="dayu_logger")
            )
            stack.enter_context(
                patch.object(dayu_command, "DayuArticle", new=builder)
            )
            with stack:
                code, out, err = _run(
                    [
                        "dayu",
                        "upload-article",
                        "--profile-id",
                        PROFILE,
                        "--title",
                        "测试图文标题",
                        "--content-file",
                        str(content),
                        "--source",
                        "无需标注",
                    ]
                )

        self.assertEqual(code, 0, err)
        self.assertIn('"success": true', out)
        self.assertIsNone(builder.call_args.kwargs["account_file"])
        app.main.assert_awaited_once()
        self.assertEqual(app.main.await_args.kwargs["session"].mode, "adspower")
        self.assert_managed_session(calls, client, playwright, browser, context)
        logger.info.assert_any_call(ADSPOWER_IDENTITY_FORMAT, PROFILE)
        logger.info.assert_any_call(ADSPOWER_TIMEZONE_HINT)

    def _upload_article(self, module, name, builder_attr, logger_attr, argv_extra):
        with tempfile.TemporaryDirectory() as tmp:
            content = self._article_file(tmp)
            app = MagicMock()
            app.main = AsyncMock(return_value={"success": True})
            builder = MagicMock(return_value=app)
            stack, calls, client, playwright, browser, context, logger = (
                self.start_seam(module, logger_attr=logger_attr)
            )
            stack.enter_context(
                patch.object(module, builder_attr, new=builder)
            )
            argv = [
                name,
                "upload-article",
                "--profile-id",
                PROFILE,
                "--title",
                "测试文章标题",
                "--content-file",
                str(content),
            ] + argv_extra
            with stack:
                code, out, err = _run(argv)

        self.assertEqual(code, 0, err)
        self.assertIn('"success": true', out)
        self.assertIsNone(builder.call_args.kwargs["account_file"])
        app.main.assert_awaited_once()
        self.assertEqual(app.main.await_args.kwargs["session"].mode, "adspower")
        self.assert_managed_session(calls, client, playwright, browser, context)
        self.assertNotIn("Multilogin", logger.info.call_args.args[0])

    def test_zhihu_upload_article_skips_cookie_and_identity(self):
        self._upload_article(
            zhihu_command, "zhihu", "ZhihuArticle", "logger", []
        )

    def test_xueqiu_upload_article_skips_cookie_and_identity(self):
        self._upload_article(
            xueqiu_command,
            "xueqiu",
            "XueqiuArticle",
            "logger",
            ["--declaration", "不添加创作声明"],
        )


class _ArticlePage:
    def __init__(self, final_url: str) -> None:
        self.url = "about:blank"
        self.final_url = final_url
        self.screenshot_calls: list[str] = []

    async def goto(self, url: str, **kwargs):
        self.url = self.final_url
        return SimpleNamespace(status=200)

    async def screenshot(self, *, path=None, **kwargs) -> None:
        self.screenshot_calls.append(path)

    async def close(self) -> None:
        pass


class _ArticleContext:
    def __init__(self, page: _ArticlePage) -> None:
        self.page = page
        self.new_page_calls = 0
        self.storage_state_calls: list[object] = []
        self.add_init_script_calls = 0
        self.forbidden_calls: list[str] = []

    async def new_page(self) -> _ArticlePage:
        self.new_page_calls += 1
        return self.page

    async def storage_state(self, **kwargs):
        self.storage_state_calls.append(kwargs)
        raise AssertionError("managed mode must not write cookies")

    async def add_init_script(self, *args, **kwargs) -> None:
        self.add_init_script_calls += 1
        raise AssertionError("managed mode must not inject scripts")

    async def grant_permissions(self, *args, **kwargs) -> None:
        self.forbidden_calls.append("grant_permissions")
        raise AssertionError("managed mode must not grant permissions")


class ArticleUploaderBodyTests(unittest.TestCase):
    def _session(self, final_url: str):
        page = _ArticlePage(final_url)
        context = _ArticleContext(page)
        return BrowserSession(
            browser=MagicMock(), context=context, mode="adspower"
        ), page, context

    def test_dayu_article_body_never_reads_identity_or_timezone(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = Path(tmp) / "article.html"
            content.write_text("<p>正文</p>", encoding="utf-8")
            app = DayuArticle(
                title="测试图文标题",
                content_file=content,
                account_file=None,
                source="无需标注",
                prepare_only=True,
            )
            app.document = SimpleNamespace(
                manifest={}, source_format="html", theme=None, images=[]
            )
            app.style_result = {"mode": "native"}
            app.publication_html = None
            session, page, context = self._session(
                "https://mp.dayu.com/dashboard/article/write"
            )
            with (
                patch.object(
                    DayuArticle, "fill_article_form", new=AsyncMock()
                ) as fill_form,
                patch.object(
                    dayu_article_module,
                    "raise_if_login_required",
                    new=AsyncMock(),
                ),
                patch.object(
                    dayu_article_module,
                    "read_dayu_identity",
                    new=AsyncMock(),
                ) as read_identity,
                patch.object(
                    dayu_article_module,
                    "load_dayu_identity",
                    new=MagicMock(),
                ) as load_identity,
                patch.object(dayu_article_module, "dayu_logger", MagicMock()),
            ):
                result = asyncio.run(app.upload_in(session))

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "prepared")
        read_identity.assert_not_awaited()
        load_identity.assert_not_called()
        fill_form.assert_awaited_once_with(page, multilogin=True)
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.forbidden_calls, [])

    def test_zhihu_article_body_never_reads_identity_or_grants_clipboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = Path(tmp) / "article.html"
            content.write_text("<p>正文</p>", encoding="utf-8")
            app = ZhihuArticle(
                "测试文章标题", content, None, prepare_only=True, headless=False
            )
            app.document = SimpleNamespace(manifest={})
            app.uploaded_images = []
            app.images = []
            app.identity = None
            session, page, context = self._session(
                "https://zhuanlan.zhihu.com/write"
            )
            with (
                patch.object(
                    ZhihuArticle, "fill_article_form", new=AsyncMock()
                ) as fill_form,
                patch.object(
                    zhihu_article_module, "read_zhihu_identity", new=AsyncMock()
                ) as read_identity,
                patch.object(
                    zhihu_article_module, "load_zhihu_identity", new=MagicMock()
                ) as load_identity,
            ):
                result = asyncio.run(app.upload_in(session))

        self.assertEqual(result["status"], "prepared")
        read_identity.assert_not_awaited()
        load_identity.assert_not_called()
        fill_form.assert_awaited_once_with(page, multilogin=True)
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.forbidden_calls, [])

    def test_xueqiu_article_body_never_reads_identity_or_grants_clipboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = Path(tmp) / "article.html"
            content.write_text("<p>正文</p>", encoding="utf-8")
            app = XueqiuArticle(
                "雪球标题",
                content,
                None,
                declaration="不添加创作声明",
                prepare_only=True,
            )
            app.document = SimpleNamespace(
                manifest={}, source_format="html", normalizations=[]
            )
            app.uploaded_images = []
            app.cover_url = None
            app.identity = None
            session, page, context = self._session(
                "https://mp.xueqiu.com/writeV2/"
            )
            with (
                patch.object(
                    XueqiuArticle, "fill_article_form", new=AsyncMock()
                ) as fill_form,
                patch.object(
                    xueqiu_article_module,
                    "read_xueqiu_identity",
                    new=AsyncMock(),
                ) as read_identity,
                patch.object(
                    xueqiu_article_module,
                    "load_xueqiu_identity",
                    new=MagicMock(),
                ) as load_identity,
            ):
                result = asyncio.run(app.upload_in(session))

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "prepared")
        read_identity.assert_not_awaited()
        load_identity.assert_not_called()
        fill_form.assert_awaited_once_with(page, multilogin=True)
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(context.storage_state_calls, [])
        self.assertEqual(context.forbidden_calls, [])
        self.assertEqual(len(page.screenshot_calls), 1)

    def test_clipboard_permission_follows_session_managed_for_adspower(self):
        session = BrowserSession(
            browser=MagicMock(), context=FakeContext(), mode="adspower"
        )
        page = SimpleNamespace(context=session.context)

        asyncio.run(
            zhihu_article_module.grant_clipboard_permission(
                page, multilogin=session.managed
            )
        )
        asyncio.run(
            xueqiu_article_module.grant_clipboard_permission(
                page, multilogin=session.managed
            )
        )
        self.assertEqual(session.context.forbidden_calls, [])

        local_context = SimpleNamespace(grant_permissions=AsyncMock())
        local_page = SimpleNamespace(context=local_context)
        asyncio.run(
            zhihu_article_module.grant_clipboard_permission(
                local_page, multilogin=False
            )
        )
        asyncio.run(
            xueqiu_article_module.grant_clipboard_permission(
                local_page, multilogin=False
            )
        )
        self.assertEqual(local_context.grant_permissions.await_count, 2)


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
            expect = MagicMock(
                return_value=SimpleNamespace(
                    not_to_have_count=AsyncMock(return_value=None)
                )
            )

            with (
                patch.object(
                    instagram_main, "instagram_identity", identity_file_reader
                ),
                patch.object(
                    instagram_main, "_multilogin_identity", live_identity
                ),
                patch.object(instagram_main, "expect", expect),
            ):
                asyncio.run(app.upload(session=session))

        identity_file_reader.assert_not_called()
        live_identity.assert_awaited_once()
        self.assertIsNone(app.account_file)
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(context.storage_state_calls, [])
        app._upload_steps.assert_awaited_once()


class LocalOnlyActionTests(unittest.TestCase):
    """verify/delete stay local even when AdsPower is active."""

    def _assert_local_helper(self, module, argv, helper_attr):
        helper = AsyncMock(return_value={})
        resolve = MagicMock(return_value=Path("/tmp/local-cookie.json"))
        managed = MagicMock(side_effect=AssertionError("managed provider used"))
        stack = ExitStack()
        stack.enter_context(patch.object(module, helper_attr, new=helper))
        stack.enter_context(
            patch.object(module, "resolve_account_file", new=resolve)
        )
        stack.enter_context(
            patch.object(module, "resolve_managed_provider", new=managed)
        )
        stack.enter_context(
            patch.object(
                module,
                "browser_session",
                new=MagicMock(side_effect=AssertionError("session used")),
            )
        )
        with stack:
            code, out, err = _run(argv)

        self.assertEqual(code, 0, err)
        helper.assert_awaited_once()
        self.assertEqual(helper.await_args.args[0], Path("/tmp/local-cookie.json"))
        resolve.assert_called_once()
        managed.assert_not_called()

    def test_facebook_verify_and_delete_are_local(self):
        base = [
            "--account",
            "creator",
            "--post-url",
            "url",
            "--owner-id",
            "1",
            "--expected-text",
            "text",
        ]
        self._assert_local_helper(
            facebook_command, ["facebook", "verify"] + base, "facebook_post_action"
        )
        self._assert_local_helper(
            facebook_command, ["facebook", "delete"] + base, "facebook_post_action"
        )

    def test_facebook_page_verify_and_delete_are_local(self):
        base = [
            "--account",
            "creator",
            "--page-id",
            "1",
            "--page",
            "Page",
            "--content-id",
            "c",
            "--expected-text",
            "text",
        ]
        self._assert_local_helper(
            facebook_page_command,
            ["facebook-page", "verify"] + base,
            "meta_post_action",
        )
        self._assert_local_helper(
            facebook_page_command,
            ["facebook-page", "delete"] + base,
            "meta_post_action",
        )

    def test_instagram_verify_and_delete_are_local(self):
        base = [
            "--account",
            "creator",
            "--post-url",
            "url",
            "--expected-text",
            "text",
        ]
        self._assert_local_helper(
            instagram_command,
            ["instagram", "verify"] + base,
            "instagram_post_action",
        )
        self._assert_local_helper(
            instagram_command,
            ["instagram", "delete"] + base,
            "instagram_post_action",
        )

    def test_zhihu_and_xueqiu_verify_are_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = Path(tmp) / "result.json"
            result.write_text("{}", encoding="utf-8")
            self._assert_local_helper(
                zhihu_command,
                ["zhihu", "verify", "--account", "creator", "--result", str(result)],
                "verify_zhihu_result",
            )
            self._assert_local_helper(
                xueqiu_command,
                ["xueqiu", "verify", "--account", "creator", "--result", str(result)],
                "verify_xueqiu_result",
            )

    def test_dayu_verify_is_local(self):
        local_identity = MagicMock(
            side_effect=RuntimeError("local dayu identity path")
        )
        resolve = MagicMock(return_value=Path("/tmp/dayu-cookie.json"))
        managed = MagicMock(side_effect=AssertionError("managed provider used"))
        with (
            patch.object(dayu_command, "load_dayu_identity", new=local_identity),
            patch.object(dayu_command, "resolve_account_file", new=resolve),
            patch.object(dayu_command, "resolve_managed_provider", new=managed),
        ):
            code, _, err = _run(
                [
                    "dayu",
                    "verify",
                    "--account",
                    "creator",
                    "--content-id",
                    "c",
                ]
            )

        self.assertEqual(code, 1)
        self.assertIn("local dayu identity path", err)
        local_identity.assert_called_once_with(Path("/tmp/dayu-cookie.json"))
        resolve.assert_called_once()
        managed.assert_not_called()

    def test_all_local_actions_still_require_account_under_adspower(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = Path(tmp) / "result.json"
            result.write_text("{}", encoding="utf-8")
            cases = (
                ["facebook", "verify", "--post-url", "u", "--owner-id", "1", "--expected-text", "t"],
                ["facebook", "delete", "--post-url", "u", "--owner-id", "1", "--expected-text", "t"],
                ["facebook-page", "verify", "--page-id", "1", "--page", "P", "--content-id", "c", "--expected-text", "t"],
                ["facebook-page", "delete", "--page-id", "1", "--page", "P", "--content-id", "c", "--expected-text", "t"],
                ["instagram", "verify", "--post-url", "u", "--expected-text", "t"],
                ["instagram", "delete", "--post-url", "u", "--expected-text", "t"],
                ["zhihu", "verify", "--result", str(result)],
                ["xueqiu", "verify", "--result", str(result)],
                ["dayu", "verify", "--content-id", "c"],
            )
            for argv in cases:
                with self.subTest(argv=argv):
                    code, _, err = _run(argv)
                    self.assertEqual(code, 2)
                    self.assertIn("--account", err)


class BilibiliUnderAdspowerTests(unittest.TestCase):
    def test_bilibili_login_check_upload_all_exit_1_without_biliup(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "demo.mp4"
            video.write_bytes(b"video")
            cases = (
                ["bilibili", "login", "--account", "creator"],
                ["bilibili", "check", "--account", "creator"],
                [
                    "bilibili",
                    "upload-video",
                    "--account",
                    "creator",
                    "--file",
                    str(video),
                    "--title",
                    "标题",
                    "--desc",
                    "简介",
                    "--tid",
                    "1",
                ],
            )
            biliup = MagicMock(side_effect=AssertionError("biliup must not run"))
            with patch.object(
                bilibili_command, "run_biliup_command", new=biliup
            ):
                for argv in cases:
                    with self.subTest(argv=argv):
                        code, _, err = _run(argv)
                        self.assertEqual(code, 1)
                        self.assertIn("AdsPower", err)
            biliup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
