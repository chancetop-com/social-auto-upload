import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import uploader.xiaohongshu_uploader.main as xhs_main

# Decision map (spec U12 F): this legacy-file class mixes decisions, so it keeps
# its name instead of a cosmetic rename. Methods anchor to:
#   Decision03 (ARM/FIRE/OBSERVE deadlines), Decision10 (humanized typing),
#   Decision11 (declarations / title defaults).


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

    async def insert_text(self, text):
        self.actions.append(("insert_text", text))


class RecordingLocator(FakeLocator):
    def __init__(self, name):
        super().__init__(name, count=1)
        self.actions = []

    async def fill(self, value):
        self.actions.append(("fill", value))

    async def click(self):
        self.actions.append(("click",))

    async def focus(self):
        self.actions.append(("focus",))

    async def wait_for(self, **kwargs):
        self.actions.append(("wait_for", kwargs))


class RecordingPage:
    def __init__(self):
        self.keyboard = RecordingKeyboard()
        self.waits: list[float] = []
        self.locators = {
            "div.d-input input": RecordingLocator("title"),
            'div.tiptap[role="textbox"][contenteditable="true"]': RecordingLocator(
                "desc"
            ),
            '#creator-editor-topic-container': RecordingLocator("topic-container"),
            '#creator-editor-topic-container .item': RecordingLocator("topic-item"),
        }

    def locator(self, selector):
        return self.locators[selector]

    async def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)


class XiaohongshuUploaderTests(unittest.TestCase):

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


    def test_video_validate_upload_args_normalizes_video_and_thumbnail(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            assets = Path(tmp_dir) / "assets"
            assets.mkdir()
            video_path = Path(tmp_dir) / "demo.mp4"
            thumbnail_path = Path(tmp_dir) / "demo.png"
            cookie_path = Path(tmp_dir) / "account.json"
            video_path.write_bytes(b"video")
            thumbnail_path.write_bytes(b"image")
            cookie_path.write_text("{}")

            app = xhs_main.XiaoHongShuVideo(
                title="demo",
                file_path=str(assets / ".." / video_path.name),
                tags=["xhs"],
                publish_date=0,
                account_file=str(cookie_path),
                thumbnail_path=str(assets / ".." / thumbnail_path.name),
            )

            asyncio.run(app.validate_upload_args())

            self.assertEqual(app.file_path, str(video_path.resolve()))
            self.assertEqual(app.thumbnail_path, str(thumbnail_path.resolve()))

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

        # HUMANIZE=0：快路径（一次 insert_text / 一次普通 click），这里验证的是
        # 调用点语义（顺序、清理键、话题点击），不是行为层的时延。
        with patch.dict(os.environ, {"HUMANIZE": "0"}):
            asyncio.run(app.fill_meta(page))

        self.assertEqual(
            page.locators["div.d-input input"].actions,
            [("focus",)],
        )
        self.assertEqual(
            page.locators['div.tiptap[role="textbox"][contenteditable="true"]'].actions,
            [("focus",)],
        )
        self.assertEqual(
            page.keyboard.actions,
            [
                ("insert_text", "标题内容"),
                ("press", "Backspace"),
                ("press", "ControlOrMeta+A"),
                ("press", "Delete"),
                ("insert_text", "描述内容"),
                ("press", "Enter"),
                ("insert_text", "#话题1"),
                # 候选没有可读的 .name → 判无候选 → 降级保留纯文本 + 一个空格。
                ("press", "Space"),
            ],
        )
        self.assertEqual(
            page.locators['#creator-editor-topic-container .item'].actions,
            [],
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

        with patch.dict(os.environ, {"HUMANIZE": "0"}):
            asyncio.run(app.fill_meta(page))

        self.assertEqual(
            page.locators['div.tiptap[role="textbox"][contenteditable="true"]'].actions,
            [("focus",)],
        )
        self.assertEqual(
            page.keyboard.actions,
            [
                ("insert_text", "标题内容"),
                ("insert_text", "#话题1"),
                ("press", "Space"),
            ],
        )

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

            async def focus(self, **kwargs):
                return None

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
                self.locator_calls = []
                self.source_input = FakeInput()
                self.confirm = FakeTrigger()
                self.keyboard = RecordingKeyboard()

            def get_by_text(self, text, exact=False):
                return self.trigger

            def locator(self, selector):
                # 每个声明选项用独立 locator，按选择器 + 点击顺序记录。
                option = FakeOption(len(self.options))
                self.options[len(self.options)] = option
                self.locator_calls.append((selector, option))
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

        with patch.dict(os.environ, {"HUMANIZE": "0"}):
            asyncio.run(app.apply_declarations(page))

        self.assertEqual(page.keyboard.actions, [("insert_text", "某媒体")])
        self.assertEqual(page.confirm.clicks, 1)
        # 打开一级菜单 + 点「内容来源声明」+ 点「来源转载」：
        # 触发器与两个选项都走候选层；选项限定 .declaration-drop-down .d-option。
        option_calls = [
            option
            for selector, option in page.locator_calls
            if selector == xhs_main.XHS_DECLARATION_OPTION_SELECTOR
        ]
        self.assertEqual(len(option_calls), 2)
        self.assertTrue(all(option.clicks == 1 for option in option_calls))
        trigger_calls = [
            option
            for selector, option in page.locator_calls
            if selector == '.publish-container [tabindex="1"]'
        ]
        self.assertEqual(len(trigger_calls), 1)
        self.assertEqual(trigger_calls[0].clicks, 1)

if __name__ == "__main__":
    unittest.main()
