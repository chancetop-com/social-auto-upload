"""TikTok location adapter against a controlled Studio-shaped DOM."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from patchright.async_api import async_playwright

from uploader.tk_uploader import main_chrome as tk


HTML = """
<div data-e2e="poi_container">
  <button type="button" role="combobox" aria-expanded="true"
          aria-controls="loc-list">Location</button>
  <input role="input" class="Select__searchInput" placeholder="Search locations">
</div>
<div id="loc-list" role="listbox">
  <div role="option"><div>London Eye</div><div>Riverside Building, County Hall, London SE1 7PB, United Kingdom</div></div>
</div>
<div id="privacy-list" role="listbox">
  <div role="option">Public</div>
</div>
"""


class TiktokLocationDomTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        playwright = await async_playwright().start()
        self.addAsyncCleanup(playwright.stop)
        browser = await playwright.chromium.launch(
            headless=True, channel="chromium"
        )
        self.addAsyncCleanup(browser.close)
        self.page = await browser.new_page()
        await self.page.set_content(HTML)
        self.container = self.page.locator('[data-e2e="poi_container"]')
        self.input = self.container.locator("input.Select__searchInput")
        self.control = tk._LocatorLocationControl(
            self.input,
            self.container,
            page=self.page,
            candidates=(),
        )

    async def _expanded(self, value: str) -> None:
        await self.page.locator('button[role="combobox"]').evaluate(
            "(node, value) => node.setAttribute('aria-expanded', value)",
            value,
        )

    async def test_rows_are_scoped_to_the_combobox_listbox(self):
        rows = await self.control.candidate_rows()

        self.assertEqual([row.name for row in rows], ["London Eye"])
        self.assertEqual(
            rows[0].address,
            "Riverside Building, County Hall, London SE1 7PB, United Kingdom",
        )

    async def test_expanded_reads_the_combobox_button(self):
        self.assertTrue(await self.control._expanded())
        await self._expanded("false")
        self.assertFalse(await self.control._expanded())

    async def test_collapsed_uses_the_combobox_and_ignores_other_option_rows(self):
        await self._expanded("false")

        self.assertTrue(await self.control.wait_collapsed())

    async def test_open_list_is_not_collapsed(self):
        with patch.object(tk, "TIKTOK_LOCATION_COLLAPSE_TIMEOUT_MS", 150):
            self.assertFalse(await self.control.wait_collapsed())


if __name__ == "__main__":
    unittest.main()
