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
list.addEventListener('click', event => {
  const option = event.target.closest('[role="option"]');
  if (!option) return;
  input.value = option.firstElementChild.textContent;
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

    async def test_recycled_row_cannot_click_the_replacement_address(self):
        self.page.set_default_timeout(700)
        await self.page.locator('#loc-list [role="option"]').evaluate("""row => {
            row.onmouseenter = () => row.lastElementChild.textContent = 'Recycled address';
            row.onclick = () => document.body.dataset.clicked = 'yes';
        }""")
        rows = await self.control.candidate_rows()
        with self.assertRaises(tk.PlaywrightTimeoutError):
            await rows[0].click()
        self.assertIsNone(await self.page.locator('body').get_attribute('data-clicked'))

    async def test_switch_without_boolean_evidence_stops(self):
        for html in ('<button role=switch>AI</button>',
                     '<input type=checkbox role=switch><script>document.querySelector("input").indeterminate=true</script>'):
            with self.subTest(html=html):
                await self.page.set_content(f'<div data-e2e="aigc_container">{html}</div>')
                app = tk.TiktokVideo("Caption", "v.mp4", [], 0, None, options=tk.TiktokPublishOptions(aigc=False))
                app.locator_base = self.page.locator('body')
                with self.assertRaises(RuntimeError):
                    await app.apply_options(self.page)
                self.assertEqual(app.ai_outcome.reason, "read_error")
                self.assertIsNone(app.ai_outcome.applied)

    async def test_final_readiness_checks_deferred_caption_errors_inside_iframe(self):
        await self.page.set_content('<iframe id="upload"></iframe><div aria-live="polite">Too many hashtags</div>')
        frame = self.page.frames[1]
        await frame.set_content("""
            <div class="caption-textarea">
                <div contenteditable="true"><span aria-live="polite">Too many hashtags</span></div>
            </div>
            <div aria-live="polite">Too many hashtags</div>
        """)
        app = tk.TiktokVideo("Caption", "v.mp4", [], 0, None)
        app.locator_base = self.page.frame_locator("#upload")
        self.assertFalse(await app._topic_hard_limit_visible(self.page))
        await frame.locator('.caption-textarea').evaluate("""el => {
            el.insertAdjacentHTML('beforeend', '<div aria-live="polite">Too many hashtags</div>');
        }""")
        app.topic_outcomes = [object()]
        with patch.object(app, "_publish_button_ready", return_value=object()):
            with self.assertRaisesRegex(RuntimeError, "硬限制"):
                await app.wait_publish_ready(self.page)

    async def test_iframe_and_legacy_search_use_the_location_list_only(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                await self.page.set_content('<iframe id="upload"></iframe>')
                frame = self.page.frames[1]
                html = HTML.replace('data-e2e="poi_container"', 'class="Select"') if legacy else HTML
                await frame.set_content(html)
                probe = self._probe()
                probe.locator_base = self.page.frame_locator('#upload')
                probe._option_page = self.page
                control = await probe._resolve_single_control("location")
                self.assertIsNotNone(control)
                await probe._apply_location_option(control, "London Eye", page=self.page, url="about:blank")
                self.assertEqual(probe.location_outcome.candidate_address,
                                 "Riverside Building, County Hall, London SE1 7PB, United Kingdom")

    async def test_ai_control_can_mount_after_show_more_disappears(self):
        await self.page.set_content("""
            <div class="public-DraftEditor-content" contenteditable="true">Caption</div>
            <button onclick="this.remove(); setTimeout(mount, 250)">Show more</button>
            <script>function mount() {
                const row = document.createElement('div');
                row.dataset.e2e = 'aigc_container';
                row.innerHTML = '<button role="switch" aria-checked="true" disabled>AI</button>';
                document.body.append(row);
            }</script>
        """)
        app = tk.TiktokVideo("Caption", "v.mp4", [], 0, None, options=tk.TiktokPublishOptions(aigc=False))
        app.locator_base = self.page.locator("body")
        with self.assertRaises(RuntimeError):
            await app.apply_options(self.page)
        self.assertEqual(app.ai_outcome.status, "mismatch")
        self.assertIs(app.ai_outcome.applied, True)

    async def test_unowned_legacy_search_cannot_select_privacy(self):
        await self.page.set_content("""<form>
            <input placeholder="Search locations">
            <button role="combobox" aria-controls="privacy" aria-expanded="true">Privacy</button>
            <div id="privacy"><span role="option">Public</span></div>
        </form>""")
        app = self._probe()
        app.locator_base = self.page.locator('body')
        app._option_page = self.page
        control = await app._resolve_single_control('location')
        self.assertEqual(await control.candidate_rows(), [])

    async def test_hidden_dialog_does_not_obstruct_missing_ai_entry(self):
        await self.page.set_content("""<div role="dialog" aria-modal="true" hidden></div>
            <div class="public-DraftEditor-content" contenteditable="true">Caption</div>""")
        app = tk.TiktokVideo("Caption", "v.mp4", [], 0, None, options=tk.TiktokPublishOptions(aigc=False))
        app.locator_base = self.page.locator('body')
        await app.apply_options(self.page)
        self.assertEqual(app.ai_outcome.reason, "entry_missing")

    async def test_unavailable_settings_cannot_confirm_missing_ai_entry(self):
        for overlay in (False, True):
            with self.subTest(overlay=overlay):
                await self.page.set_content('<iframe id="upload"></iframe><dialog>Confirm</dialog>')
                frame = self.page.frames[1]
                await frame.set_content('<div class="public-DraftEditor-content" contenteditable="true">Caption</div>'
                                        '<div data-e2e="advanced_settings_container" aria-busy="true">Loading</div>')
                if overlay:
                    await frame.locator('[aria-busy]').evaluate("el => el.remove()")
                    await self.page.locator('dialog').evaluate("el => el.showModal()")
                app = tk.TiktokVideo("Caption", "v.mp4", [], 0, None, options=tk.TiktokPublishOptions(aigc=False))
                app.locator_base = self.page.frame_locator("#upload")
                with self.assertRaises(RuntimeError):
                    await app.apply_options(self.page)
                self.assertEqual(app.ai_outcome.reason, "read_error")

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
