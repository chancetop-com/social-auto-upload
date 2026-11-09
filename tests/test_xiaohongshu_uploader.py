import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import uploader.xiaohongshu_uploader.main as xhs_main
from utils.errors import PublishResultUnknownError


class FakeLocator:
    def __init__(self, name, count=0, src=None, children=None):
        self.name = name
        self._count = count
        self._src = src
        self._children = children or {}

    @property
    def first(self):
        return self

    def locator(self, selector):
        return self._children.get(selector, FakeLocator(selector))

    def get_by_text(self, text, exact=False):
        return self._children.get(f"text:{text}", FakeLocator(text))

    def filter(self, **kwargs):
        return self

    def nth(self, index):
        return self

    async def count(self):
        return self._count

    async def wait_for(self, **kwargs):
        return None

    async def get_attribute(self, name):
        if name == "src":
            return self._src
        return None

    async def fill(self, value):
        return None

    async def click(self):
        return None


class RecordingKeyboard:
    def __init__(self):
        self.actions = []

    async def press(self, key):
        self.actions.append(("press", key))

    async def type(self, text, delay=None):
        self.actions.append(("type", text, delay))


class RecordingLocator(FakeLocator):
    def __init__(self, name):
        super().__init__(name, count=1)
        self.actions = []

    async def fill(self, value):
        self.actions.append(("fill", value))

    async def click(self):
        self.actions.append(("click",))

    async def wait_for(self, **kwargs):
        self.actions.append(("wait_for", kwargs))


class RecordingPage:
    def __init__(self):
        self.keyboard = RecordingKeyboard()
        self.locators = {
            'input[placeholder*="填写标题"]': RecordingLocator("title"),
            'p[data-placeholder*="输入正文描述"]': RecordingLocator("desc"),
            '#creator-editor-topic-container': RecordingLocator("topic-container"),
            '#creator-editor-topic-container .item': RecordingLocator("topic-item"),
        }

    def locator(self, selector):
        return self.locators[selector]


class XiaohongshuUploaderTests(unittest.TestCase):
    def test_headless_user_agent_drops_headless_marker(self):
        class ProbePage:
            async def evaluate(self, script):
                return (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "HeadlessChrome/156.0.0.0 Safari/537.36"
                )

        class ProbeContext:
            def __init__(self):
                self.closed = False

            async def new_page(self):
                return ProbePage()

            async def close(self):
                self.closed = True

        class FakeBrowser:
            def __init__(self):
                self.contexts = []

            async def new_context(self):
                context = ProbeContext()
                self.contexts.append(context)
                return context

        browser = FakeBrowser()
        user_agent = asyncio.run(xhs_main._xhs_user_agent(browser))

        self.assertNotIn("HeadlessChrome", user_agent)
        self.assertIn("Chrome/156.0.0.0", user_agent)
        self.assertTrue(browser.contexts[0].closed)

    def test_creator_urls_keep_xiaohongshu_domain_by_default(self):
        with patch.dict(os.environ, {"SAU_XHS_CREATOR_BASE_URL": ""}):
            self.assertEqual(
                xhs_main._build_xhs_creator_url("/login"),
                "https://creator.xiaohongshu.com/login",
            )

    def test_creator_urls_use_configured_rednote_domain(self):
        with patch.dict(
            os.environ,
            {"SAU_XHS_CREATOR_BASE_URL": "https://creator.rednote.com/"},
        ):
            self.assertEqual(
                xhs_main._build_xhs_creator_url("/login"),
                "https://creator.rednote.com/login",
            )
            self.assertEqual(
                xhs_main._build_xhs_creator_url(
                    "/publish/publish?from=homepage&target=video"
                ),
                "https://creator.rednote.com/publish/publish?from=homepage&target=video",
            )

    def test_find_xhs_qrcode_locator_prefers_scan_sibling_inside_login_box(self):
        qrcode_locator = FakeLocator("qrcode", count=1, src="data:image/png;base64,abc")
        scan_text_locator = FakeLocator(
            "scan-text",
            count=1,
            children={
                "xpath=..//following-sibling::div//img": qrcode_locator,
            },
        )
        login_box_locator = FakeLocator(
            "login-box",
            count=1,
            children={
                "div:has-text('扫一扫')": scan_text_locator,
                "text:APP扫一扫登录": scan_text_locator,
            },
        )
        page = FakeLocator(
            "page",
            children={
                "div[class*='login-box']": login_box_locator,
                ".login-box-container": login_box_locator,
            },
        )

        locator = asyncio.run(xhs_main._find_xhs_qrcode_locator(page))
        self.assertIs(locator, qrcode_locator)

    def test_setup_returns_detail_when_cookie_invalid_without_handle(self):
        with patch("uploader.xiaohongshu_uploader.main.os.path.exists", return_value=False):
            result = asyncio.run(
                xhs_main.xiaohongshu_setup(
                    "missing.json",
                    handle=False,
                    return_detail=True,
                )
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "cookie_invalid")

    def test_setup_uses_login_flow_when_handle_is_true(self):
        login_result = {
            "success": True,
            "status": "success",
            "message": "ok",
            "account_file": "account.json",
            "qrcode": {"image_path": "qrcode.png"},
            "current_url": "https://creator.xiaohongshu.com/",
        }
        with patch("uploader.xiaohongshu_uploader.main.os.path.exists", return_value=False):
            with patch(
                "uploader.xiaohongshu_uploader.main.xiaohongshu_cookie_gen",
                new=AsyncMock(return_value=login_result),
            ) as mock_login:
                result = asyncio.run(
                    xhs_main.xiaohongshu_setup(
                        "account.json",
                        handle=True,
                        return_detail=True,
                    )
                )
        self.assertTrue(result["success"])
        mock_login.assert_awaited_once()

    def test_video_validate_upload_args_normalizes_video_and_thumbnail(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            thumbnail_path = Path(tmp_dir) / "demo.png"
            cookie_path = Path(tmp_dir) / "account.json"
            video_path.write_bytes(b"video")
            thumbnail_path.write_bytes(b"image")
            cookie_path.write_text("{}")

            app = xhs_main.XiaoHongShuVideo(
                title="demo",
                file_path=str(video_path),
                tags=["xhs"],
                publish_date=0,
                account_file=str(cookie_path),
                thumbnail_path=str(thumbnail_path),
            )

            with patch(
                "uploader.xiaohongshu_uploader.main.cookie_auth",
                new=AsyncMock(return_value=True),
            ):
                asyncio.run(app.validate_upload_args())

        self.assertTrue(app.file_path.endswith("demo.mp4"))
        self.assertTrue(app.thumbnail_path.endswith("demo.png"))

    def test_note_uploader_exists_and_validates_required_fields(self):
        note_cls = getattr(xhs_main, "XiaoHongShuNote")
        app = note_cls(
            image_paths=[],
            note="",
            tags=[],
            publish_date=0,
            account_file="account.json",
        )

        with patch.object(app, "validate_base_args", new=AsyncMock(return_value=None)):
            with self.assertRaises(ValueError):
                asyncio.run(app.validate_upload_args())

    def test_video_fill_meta_uses_desc_then_first_tag(self):
        app = xhs_main.XiaoHongShuVideo(
            title="标题内容",
            file_path="demo.mp4",
            tags=["话题1"],
            publish_date=0,
            account_file="account.json",
            desc="描述内容",
        )
        page = RecordingPage()

        asyncio.run(app.fill_meta(page))

        self.assertEqual(
            page.locators['input[placeholder*="填写标题"]'].actions,
            [("fill", "标题内容")],
        )
        self.assertEqual(
            page.locators['p[data-placeholder*="输入正文描述"]'].actions,
            [("click",)],
        )
        self.assertIn(("type", "描述内容", None), page.keyboard.actions)
        self.assertIn(("type", "#话题1", 30), page.keyboard.actions)
        self.assertEqual(
            page.locators['#creator-editor-topic-container .item'].actions,
            [("wait_for", {"state": "visible", "timeout": 4000}), ("click",)],
        )

    def test_video_fill_meta_can_fill_first_tag_without_desc(self):
        app = xhs_main.XiaoHongShuVideo(
            title="标题内容",
            file_path="demo.mp4",
            tags=["话题1"],
            publish_date=0,
            account_file="account.json",
        )
        page = RecordingPage()

        asyncio.run(app.fill_meta(page))

        self.assertEqual(
            page.locators['p[data-placeholder*="输入正文描述"]'].actions,
            [("click",)],
        )
        self.assertNotIn(("type", "", None), page.keyboard.actions)
        self.assertIn(("type", "#话题1", 30), page.keyboard.actions)

    def test_publish_deadline_raises_before_publish_click(self):
        app = xhs_main.XiaoHongShuVideo(
            title="标题",
            file_path="demo.mp4",
            tags=[],
            publish_date=0,
            account_file="account.json",
        )

        with self.assertRaises(RuntimeError) as ctx:
            app._check_publish_deadline(time.monotonic() - 1)

        self.assertIn("15 分钟", str(ctx.exception))
        self.assertIn("尚未点击发布", str(ctx.exception))

    def test_publish_timeout_error_distinguishes_click_state(self):
        app = xhs_main.XiaoHongShuVideo(
            title="标题",
            file_path="demo.mp4",
            tags=[],
            publish_date=0,
            account_file="account.json",
        )

        before = app._publish_timeout_error(False)
        after = app._publish_timeout_error(True)

        self.assertIsInstance(before, RuntimeError)
        self.assertNotIsInstance(before, PublishResultUnknownError)
        self.assertIsInstance(after, PublishResultUnknownError)
        self.assertIn("禁止自动重发", str(after))

    def test_apply_declarations_is_noop_when_nothing_is_configured(self):
        app = xhs_main.XiaoHongShuVideo(
            title="标题",
            file_path="demo.mp4",
            tags=[],
            publish_date=0,
            account_file="account.json",
        )
        page = AsyncMock()

        asyncio.run(app.apply_declarations(page))

        page.locator.assert_not_called()
        page.get_by_text.assert_not_called()

    def test_apply_declarations_enables_original_switch(self):
        class FakeSwitch:
            def __init__(self):
                self.checked = False
                self.clicks = 0

            @property
            def first(self):
                return self

            async def count(self):
                return 1

            async def get_attribute(self, name):
                if name == "aria-checked":
                    return "true" if self.checked else "false"
                return "d-switch"

            async def click(self):
                self.checked = not self.checked
                self.clicks += 1

        class FakeCard:
            def __init__(self, switch):
                self.switch = switch

            @property
            def first(self):
                return self

            async def count(self):
                return 1

            def filter(self, **kwargs):
                return self

            def locator(self, selector):
                return self.switch

        class FakePage:
            def __init__(self, switch):
                self.card = FakeCard(switch)

            def locator(self, selector):
                return self.card

            async def wait_for_timeout(self, timeout):
                return None

        switch = FakeSwitch()
        app = xhs_main.XiaoHongShuVideo(
            title="标题",
            file_path="demo.mp4",
            tags=[],
            publish_date=0,
            account_file="account.json",
            original_declaration=True,
        )

        asyncio.run(app.apply_declarations(FakePage(switch)))

        self.assertTrue(switch.checked)
        self.assertEqual(switch.clicks, 1)

    def test_apply_declarations_keeps_original_off_without_click(self):
        class FakeSwitch:
            def __init__(self):
                self.checked = False
                self.clicks = 0

            @property
            def first(self):
                return self

            async def count(self):
                return 1

            async def get_attribute(self, name):
                if name == "aria-checked":
                    return "false"
                return "d-switch"

            async def click(self):
                self.clicks += 1

        class FakeCard:
            def __init__(self, switch):
                self.switch = switch

            @property
            def first(self):
                return self

            async def count(self):
                return 1

            def filter(self, **kwargs):
                return self

            def locator(self, selector):
                return self.switch

        class FakePage:
            def __init__(self, switch):
                self.card = FakeCard(switch)

            def locator(self, selector):
                return self.card

            async def wait_for_timeout(self, timeout):
                return None

        switch = FakeSwitch()
        app = xhs_main.XiaoHongShuVideo(
            title="标题",
            file_path="demo.mp4",
            tags=[],
            publish_date=0,
            account_file="account.json",
            original_declaration=False,
        )

        asyncio.run(app.apply_declarations(FakePage(switch)))

        self.assertFalse(switch.checked)
        self.assertEqual(switch.clicks, 0)

    def test_apply_declarations_repost_fills_media_name(self):
        class FakeTrigger:
            def __init__(self):
                self.clicks = 0

            @property
            def first(self):
                return self

            async def count(self):
                return 1

            async def scroll_into_view_if_needed(self, timeout=None):
                return None

            async def wait_for(self, **kwargs):
                return None

            async def click(self, force=False):
                self.clicks += 1

        class FakeOption(FakeTrigger):
            def __init__(self, name):
                super().__init__()
                self.name = name

            @property
            def last(self):
                return self

            def filter(self, **kwargs):
                return self

        class FakeInput(FakeTrigger):
            def __init__(self):
                super().__init__()
                self.filled = None

            async def wait_for(self, **kwargs):
                return None

            async def fill(self, value):
                self.filled = value

        class FakePage:
            def __init__(self):
                self.trigger = FakeTrigger()
                self.options = {}
                self.source_input = FakeInput()
                self.confirm = FakeTrigger()

            def get_by_text(self, text, exact=False):
                return self.trigger

            def locator(self, selector):
                # 每个声明选项用独立 locator，按点击顺序记录到 options。
                key = len(self.options)
                option = FakeOption(key)
                self.options[key] = option
                return option

            def get_by_placeholder(self, placeholder):
                return self.source_input

            def get_by_role(self, role, name=None):
                return self.confirm

            async def wait_for_timeout(self, timeout):
                return None

        page = FakePage()
        app = xhs_main.XiaoHongShuVideo(
            title="标题",
            file_path="demo.mp4",
            tags=[],
            publish_date=0,
            account_file="account.json",
            content_type="repost",
            repost_source=" 某媒体 ",
        )

        asyncio.run(app.apply_declarations(page))

        self.assertEqual(page.source_input.filled, "某媒体")
        self.assertEqual(page.confirm.clicks, 1)
        # 打开一级菜单 + 点「内容来源声明」+ 点「来源转载」
        self.assertEqual(len(page.options), 2)

    def test_note_title_defaults_do_not_override_explicit_title(self):
        app = xhs_main.XiaoHongShuNote(
            image_paths=["a.png"],
            note="正文",
            tags=[],
            publish_date=0,
            account_file="account.json",
            title="显式标题",
            desc="图文正文",
        )

        self.assertEqual(app.title, "显式标题")
        self.assertEqual(app.desc, "图文正文")


if __name__ == "__main__":
    unittest.main()
