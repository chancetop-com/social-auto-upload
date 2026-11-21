"""Exercise TikTok Studio option selection against offline Chromium controls."""

import os
import unittest
from unittest.mock import patch

from patchright.async_api import async_playwright

from uploader.tk_uploader.main_chrome import TiktokPublishOptions, TiktokVideo


class TikTokSettingsDomTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        playwright = await async_playwright().start()
        self.addAsyncCleanup(playwright.stop)
        browser = await playwright.chromium.launch(headless=True)
        self.addAsyncCleanup(browser.close)
        self.page = await browser.new_page()
        self.page.set_default_timeout(1500)

    async def apply(self, **requested):
        video = TiktokVideo(
            "title", "fixture.mp4", [], 0, None, options=TiktokPublishOptions(**requested)
        )
        video.locator_base = self.page
        with patch.dict(os.environ, {"HUMANIZE": "0"}):
            await video.apply_options(self.page)

    async def test_selects_privacy_from_inline_or_portal_menu(self):
        menu = """
            <div id="menu" hidden>
                <div role="option" onclick="visibilityButton.textContent=this.textContent">Friends</div>
            </div>
        """
        for portal in (False, True):
            with self.subTest(portal=portal):
                await self.page.set_content(f"""
                    {'' if portal else '<div role="option">Friends</div>'}
                    <div data-e2e="video_visibility_container">
                        <button id="visibilityButton" role="combobox"
                                onclick="menu.hidden=false">Everyone</button>
                        {'' if portal else menu}
                    </div>
                    {menu if portal else ''}
                """)
                await self.apply(privacy="friends")
                self.assertEqual(await self.page.get_by_role("combobox").inner_text(), "Friends")

    async def test_sets_reuse_and_brand_choices_on_the_rendered_checkboxes(self):
        await self.page.set_content("""
            <div data-e2e="user_perm_container">
                <label><input id="comments" type="checkbox" checked>Allow comments</label>
                <label><input id="reuse" type="checkbox" checked>Reuse of content</label>
            </div>
            <div data-e2e="disclose_content_container">
                <input type="checkbox" role="switch" aria-label="Content disclosure"
                       onchange="brands.hidden=!this.checked">
            </div>
            <div id="brands" hidden>
                <div class="title-line"><label><input id="own" type="checkbox"></label><span>Your brand</span></div>
                <div class="title-line"><label><input id="branded" type="checkbox" checked></label><span>Branded content</span></div>
            </div>
        """)
        await self.apply(allow_reuse=False, your_brand=True)
        self.assertFalse(await self.page.locator("#reuse").is_checked())
        self.assertTrue(await self.page.locator("#comments").is_checked())
        self.assertTrue(await self.page.locator("#own").is_checked())
        self.assertFalse(await self.page.locator("#branded").is_checked())
