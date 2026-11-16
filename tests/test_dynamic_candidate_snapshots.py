"""Exercise asynchronous candidate replacement with real, offline Chromium DOM."""

import os
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from patchright.async_api import Locator, async_playwright

from uploader.baijiahao_uploader import main as baijiahao
from uploader.rednote_uploader import main as rednote
from uploader.tk_uploader import main_chrome as tiktok
from uploader.xiaohongshu_uploader import main as xhs
from utils.humanize import Humanizer


class DynamicCandidateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(patch.dict(os.environ, {"HUMANIZE": "0"}))
        playwright = await async_playwright().start()
        self.addAsyncCleanup(playwright.stop)
        browser = await playwright.chromium.launch(headless=True)
        self.addAsyncCleanup(browser.close)
        self.page = await browser.new_page()
        self.page.set_default_timeout(1500)
        await self.page.route("**/*", lambda route: route.abort())
        self.humanizer = Humanizer(self.page)
        self.xhs = xhs.XiaoHongShuVideo("test", "unused.mp4", [], 0, "unused.json")
        self.tiktok = tiktok.TiktokVideo("test", "unused.mp4", [], 0, "unused.json")

    async def topic_editor(self):
        await self.page.set_content('''
          <div class="tiptap" role="textbox" contenteditable="true">#travel</div>
          <div id="creator-editor-topic-container">
            <div class="item"><span class="name">#travel</span></div>
          </div>
          <script>
            document.body.dataset.clicks = '0';
            document.querySelector('#creator-editor-topic-container').onclick = () => {
              document.body.dataset.clicks = Number(document.body.dataset.clicks) + 1;
              const a = document.createElement('a');
              a.setAttribute('data-topic', JSON.stringify({name: 'travel'}));
              a.textContent = '#travel';
              document.querySelector('.tiptap').replaceChildren(a);
              document.querySelector('#creator-editor-topic-container').replaceChildren();
            };
          </script>
        ''')
        await self.page.locator('.tiptap').focus()
        await self.page.keyboard.press("End")

    async def test_replaced_topic_candidate_is_rescanned_or_degraded_within_deadline(self):
        async def no_sleep(_seconds):
            pass

        for module, cls, prefix in (
            (rednote, rednote.RednoteVideo, "REDNOTE"),
            (xhs, xhs.XiaoHongShuVideo, "XHS"),
        ):
            for enabled in ("1", "0"):
                for replace_always in (False, True):
                    with self.subTest(platform=prefix, humanize=enabled, churn=replace_always):
                        await self.topic_editor()
                        app = cls("test", "unused.mp4", [], 0, "unused.json")
                        scan = app._scan_topic_candidate
                        scans = []

                        async def replace_after_scan(page, tag, *, scan=scan, scans=scans, replace_always=replace_always):
                            candidate, count = await scan(page, tag)
                            if candidate is not None and (not scans or replace_always):
                                await candidate.evaluate("el => el.replaceWith(el.cloneNode(true))")
                            scans.append(candidate)
                            return candidate, count

                        started = time.monotonic()
                        with (
                            patch.dict(os.environ, {"HUMANIZE": enabled}),
                            patch.object(module, f"{prefix}_TOPIC_READY_WINDOW_MS", 500),
                            patch.object(module, f"{prefix}_TOPIC_READBACK_WINDOW_MS", 200),
                            patch.object(app, "_scan_topic_candidate", replace_after_scan),
                        ):
                            await app._insert_topic(self.page, "travel", Humanizer(self.page, sleep=no_sleep))
                        self.assertLess(time.monotonic() - started, 2)
                        self.assertGreater(len(scans), 1)
                        self.assertEqual(int(await self.page.get_attribute("body", "data-clicks")), 0 if replace_always else 1)
                        self.assertEqual(await self.page.locator('a[data-topic]').count(), 0 if replace_always else 1)
                        if replace_always:
                            self.assertEqual((await self.page.locator('.tiptap').inner_text()).strip(), "#travel")

    async def test_candidate_replaced_during_humanized_pointer_movement_is_rescanned(self):
        for module, cls in ((rednote, rednote.RednoteVideo), (xhs, xhs.XiaoHongShuVideo)):
            with self.subTest(platform=module.__name__):
                await self.topic_editor()
                replaced = []

                async def replace_during_move(_seconds, *, replaced=replaced):
                    if not replaced:
                        replaced.append(True)
                        await self.page.locator('.item').evaluate("el => el.replaceWith(el.cloneNode(true))")

                with patch.dict(os.environ, {"HUMANIZE": "1"}):
                    app = cls("test", "unused.mp4", [], 0, "unused.json")
                    await app._insert_topic(self.page, "travel", Humanizer(self.page, sleep=replace_during_move))
                self.assertTrue(replaced)
                self.assertEqual(int(await self.page.get_attribute("body", "data-clicks")), 1)
                self.assertEqual(await self.page.locator('a[data-topic]').count(), 1)

    @contextmanager
    def refresh_after_capture(
        self, selector, *, root_selector="#creator-editor-topic-container"
    ):
        refreshed = []

        def wrap(original):
            async def capture(locator, *args, **kwargs):
                result = await original(locator, *args, **kwargs)
                if not refreshed and locator._impl_obj._selector == selector:
                    refreshed.append(True)
                    await self.page.locator(root_selector).evaluate(
                        "root => root.replaceChildren()"
                    )
                return result

            return capture

        with (
            patch.object(Locator, "count", wrap(Locator.count)),
            patch.object(Locator, "element_handles", wrap(Locator.element_handles)),
            patch.object(Locator, "evaluate_all", wrap(Locator.evaluate_all)),
        ):
            yield refreshed

    async def menu(self, labels):
        items = "".join(
            f'<div class="item cheetah-select-item" role="option"><span class="name">{label}</span></div>'
            for label in labels
        )
        await self.page.set_content(
            '<div contenteditable="true" id="editor"></div>'
            f'<div id="creator-editor-topic-container">{items}</div>'
        )
        await self.page.locator("#editor").focus()

    async def test_xhs_refresh_does_not_wait_for_removed_candidates(self):
        await self.menu(["#other-a", "#other-b"])
        started = time.monotonic()
        with self.refresh_after_capture(xhs.XHS_TOPIC_ITEM_SELECTOR) as refreshed:
            candidate, _ = await self.xhs._scan_topic_candidate(self.page, "travel")
        self.assertTrue(refreshed)
        self.assertIsNone(candidate)
        self.assertLess(time.monotonic() - started, 1)

    async def test_baijiahao_refresh_does_not_wait_for_removed_candidates(self):
        await self.menu(["other-a", "other-b"])
        started = time.monotonic()
        with self.refresh_after_capture(
            baijiahao.COLLECTION_OPTION_SELECTOR
        ) as refreshed:
            candidate = await baijiahao._find_exact_option(
                self.page.locator(baijiahao.COLLECTION_OPTION_SELECTOR), "travel"
            )
        self.assertTrue(refreshed)
        self.assertIsNone(candidate)
        self.assertLess(time.monotonic() - started, 1)

    async def test_tiktok_refresh_does_not_overrun_the_suggestion_deadline(self):
        await self.menu(["#other-a", "#other-b"])
        started = time.monotonic()
        with (
            self.refresh_after_capture('[role="option"]') as refreshed,
            patch.object(tiktok, "TIKTOK_HASHTAG_SUGGESTION_TIMEOUT_MS", 0),
            patch.object(tiktok, "TIKTOK_HASHTAG_SETTLE_MS", 0),
        ):
            inserted = await self.tiktok._apply_hashtag(
                self.page, "travel", humanizer=self.humanizer
            )
        self.assertTrue(refreshed)
        self.assertFalse(inserted)
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(
            await self.page.locator("#editor").inner_text(), "#travel\u00a0"
        )

    async def test_selected_candidate_does_not_change_after_reorder(self):
        original_tiktok_click = tiktok._humanized_click
        for platform in ("xhs", "baijiahao", "tiktok"):
            with self.subTest(platform=platform):
                await self.menu(["#travel", "#other"])
                await self.page.locator(".item").evaluate_all("""items => {
                    items.forEach((item, index) => item.onclick = () => {
                        document.body.dataset.chosen = index === 0 ? 'right' : 'wrong';
                        item.parentElement.replaceChildren();
                    });
                }""")

                async def reorder_then_click(humanizer, candidate, *, platform=platform):
                    await self.page.locator("#creator-editor-topic-container").evaluate(
                        "root => root.append(root.firstElementChild)"
                    )
                    if platform == "tiktok":
                        await original_tiktok_click(humanizer, candidate)
                    else:
                        await humanizer.click(candidate)

                if platform == "tiktok":
                    with patch.object(tiktok, "_humanized_click", reorder_then_click):
                        self.assertTrue(
                            await self.tiktok._apply_hashtag(
                                self.page, "travel", humanizer=self.humanizer
                            )
                        )
                else:
                    if platform == "xhs":
                        candidate, _ = await self.xhs._scan_topic_candidate(
                            self.page, "travel"
                        )
                    else:
                        candidate = await baijiahao._find_exact_option(
                            self.page.locator(baijiahao.COLLECTION_OPTION_SELECTOR),
                            "#travel",
                        )
                    self.assertIsNotNone(candidate)
                    try:
                        await reorder_then_click(self.humanizer, candidate)
                    finally:
                        await candidate.dispose()
                self.assertEqual(
                    await self.page.get_attribute("body", "data-chosen"), "right"
                )

    async def test_topic_readback_is_a_snapshot_when_editor_nodes_are_replaced(self):
        for uploader in (
            self.xhs,
            rednote.RednoteVideo("test", "unused.mp4", [], 0, "unused.json"),
        ):
            with self.subTest(platform=type(uploader).__name__):
                await self.page.set_content("""<div class="tiptap" role="textbox">
                  <a data-topic='{"name":"travel"}'></a><a data-topic='{"name":"life"}'></a>
                </div>""")
                selector = 'div.tiptap[role="textbox"] a[data-topic]'
                started = time.monotonic()
                with self.refresh_after_capture(
                    selector, root_selector=".tiptap"
                ) as refreshed:
                    values = await uploader._read_topic_nodes(self.page)
                self.assertTrue(refreshed)
                self.assertLess(time.monotonic() - started, 1)
                self.assertEqual(values, ['{"name":"travel"}', '{"name":"life"}'])
