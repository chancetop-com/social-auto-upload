"""Observe managed command cleanup in a shared Chromium context."""
import unittest

from patchright.async_api import async_playwright

from utils.managed_pages import managed_pages


class ManagedPageCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_failing_editor_closes_its_popup_and_leaves_peer_editable(self):
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(channel="chrome", headless=True)
            context = await browser.new_context()
            desktop = await context.new_page()
            async with managed_pages(context) as peer:
                draft = await peer.new_page()
                await draft.set_content('<textarea>peer draft</textarea>')
                with self.assertRaisesRegex(RuntimeError, "editor failed"):
                    async with managed_pages(context) as command:
                        editor = await command.new_page()
                        async with editor.expect_popup() as popup:
                            await editor.evaluate("window.open('about:blank')")
                        preview = await popup.value
                        raise RuntimeError("editor failed")
                self.assertTrue(editor.is_closed())
                self.assertTrue(preview.is_closed())
                self.assertEqual(await draft.locator("textarea").input_value(), "peer draft")
                await draft.locator("textarea").fill("continued editing")
            self.assertTrue(draft.is_closed())
            self.assertEqual(context.pages, [desktop])
            await browser.close()
