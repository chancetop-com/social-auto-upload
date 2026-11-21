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
<script>
const input = document.querySelector('input.Select__searchInput');
const list = document.getElementById('loc-list');
const button = document.querySelector('button[role="combobox"]');
input.addEventListener('input', () => {
  const show = input.value.toLowerCase().includes('london');
  list.style.display = show ? 'block' : 'none';
  button.setAttribute('aria-expanded', show ? 'true' : 'false');
});
document.getElementById('loc-list').addEventListener('click', () => {
  input.value = 'London Eye';
  list.style.display = 'none';
  button.setAttribute('aria-expanded', 'false');
});
</script>
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

    async def test_empty_location_list_cannot_click_a_privacy_option(self):
        probe = self._probe()
        with patch.object(tk, "TIKTOK_LOCATION_SUGGESTION_TIMEOUT_MS", 100):
            with self.assertRaises(RuntimeError):
                await probe._apply_location_option(self.control, "Public", page=self.page, url="about:blank")
        self.assertEqual(probe.location_outcome.status, "no_match")

    async def test_candidate_keeps_its_address_after_the_list_reorders(self):
        await self.page.locator('#loc-list').evaluate("""list => {
            const second = document.createElement('div');
            second.setAttribute('role', 'option');
            second.innerHTML = '<div>London Eye</div><div>Second address</div>';
            list.append(second);
            list.addEventListener('click', event => list.dataset.clicked =
                event.target.closest('[role="option"]').lastElementChild.textContent);
        }""")
        rows = await self.control.candidate_rows()
        await self.page.locator('#loc-list').evaluate('list => list.prepend(list.lastElementChild)')
        await rows[0].click()
        self.assertEqual(await self.page.locator('#loc-list').get_attribute('data-clicked'), rows[0].address)

    async def test_expanded_reads_the_combobox_button(self):
        self.assertTrue(await self.control._expanded())
        await self._expanded("false")
        self.assertFalse(await self.control._expanded())

    async def test_collapsed_uses_the_combobox_even_when_other_options_are_visible(self):
        await self._expanded("false")

        self.assertTrue(await self.control.wait_collapsed())

    async def test_open_list_is_not_collapsed(self):
        with patch.object(tk, "TIKTOK_LOCATION_COLLAPSE_TIMEOUT_MS", 150):
            self.assertFalse(await self.control.wait_collapsed())

    @staticmethod
    def _probe():
        probe = object.__new__(tk.TiktokBaseUploader)
        probe.location_outcome = None
        probe._record_location_outcome = lambda outcome: setattr(
            probe, "location_outcome", outcome
        )
        return probe

    async def test_apply_location_selects_and_reads_back_through_the_adapter(self):
        probe = self._probe()

        await probe._apply_location_option(
            self.control, "London Eye", page=self.page, url="https://studio"
        )

        outcome = probe.location_outcome
        self.assertEqual(outcome.status, "set")
        self.assertEqual(outcome.candidate_name, "London Eye")
        self.assertEqual(
            outcome.candidate_address,
            "Riverside Building, County Hall, London SE1 7PB, United Kingdom",
        )
        self.assertEqual(outcome.final_value, "London Eye")
        self.assertIsNone(outcome.reason)

    async def test_apply_location_no_match_stops_without_a_selection(self):
        probe = self._probe()

        with self.assertRaises(RuntimeError):
            await probe._apply_location_option(
                self.control, "Nowhere", page=self.page, url="https://studio"
            )

        self.assertEqual(probe.location_outcome.status, "no_match")
        self.assertIsNone(probe.location_outcome.candidate_name)


if __name__ == "__main__":
    unittest.main()
