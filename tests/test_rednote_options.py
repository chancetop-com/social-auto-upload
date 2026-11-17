"""Rednote option contracts against real Chromium DOM, without external requests."""

from __future__ import annotations

import base64
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from patchright.async_api import Locator, async_playwright

from uploader.rednote_uploader import main as rednote


class RednoteOptionDOMTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(patch.dict(os.environ, {"HUMANIZE": "0"}))
        playwright = await async_playwright().start()
        self.addAsyncCleanup(playwright.stop)
        browser = await playwright.chromium.launch(headless=True, channel="chromium")
        self.addAsyncCleanup(browser.close)
        self.page = await browser.new_page(no_viewport=True)
        self.assertIsNone(self.page.viewport_size)
        await self.page.route("**/*", lambda route: route.abort())
        self.app = rednote.RednoteVideo(
            title="test",
            file_path="unused.mp4",
            tags=[],
            publish_date=0,
            account_file="unused.json",
            no_publish=True,
        )
        self.app.start_publish_budget()
        self.enterContext(patch.object(self.app, "_settle", AsyncMock()))
        self.enterContext(patch.object(rednote, "REDNOTE_ANCHOR_TIMEOUT_MS", 200))
        self.humanizer = self.app._humanizer(self.page)

    async def declaration_page(
        self, labels, *, wrapper='lass="declaration-wrapper"', persist=True
    ):
        options = "".join(f'<div class="d-option">{label}</div>' for label in labels)
        await self.page.set_content(f"""
          <div {wrapper} onclick="document.querySelector('.d-popover').style.display='block'">
            <div class="d-select-content"><div class="d-select-description">unset</div></div>
          </div>
          <div class="d-popover d-dropdown declaration-drop-down" style="display:none">{options}</div>
          <script>
          document.querySelectorAll('.d-option').forEach(option => option.onclick = () => {{
            document.body.dataset.selected = option.textContent;
            if ({str(persist).lower()}) document.querySelector('.d-select-description').textContent = option.textContent;
            document.querySelector('.d-popover').style.display = 'none';
          }});
          </script>
        """)

    async def test_declaration_uses_the_observed_structure_and_value(self):
        await self.declaration_page(["笔记含AI合成内容"])
        self.app.content_type = "ai"
        await self.app.apply_declarations(self.page, humanizer=self.humanizer)
        self.assertEqual(
            await self.page.get_attribute("body", "data-selected"), "笔记含AI合成内容"
        )

    async def test_unverified_english_label_is_not_guessed(self):
        await self.declaration_page(["Contains AI-generated content"])
        self.app.content_type = "ai"
        with self.assertRaisesRegex(RuntimeError, "尚未点击发布"):
            await self.app.apply_declarations(self.page, humanizer=self.humanizer)
        self.assertIsNone(await self.page.get_attribute("body", "data-selected"))

    async def test_matching_menu_text_cannot_pass_a_failed_selection(self):
        await self.declaration_page(["笔记含AI合成内容"], persist=False)
        self.app.content_type = "ai"
        with self.assertRaisesRegex(RuntimeError, "回读不符"):
            await self.app.apply_declarations(self.page, humanizer=self.humanizer)

    async def test_unknown_declaration_fails_without_clicking(self):
        await self.declaration_page(["Unknown content"])
        self.app.content_type = "unknown"
        with self.assertRaises(ValueError):
            await self.app.apply_declarations(self.page, humanizer=self.humanizer)
        self.assertIsNone(await self.page.get_attribute("body", "data-selected"))

    async def cover_page(self, label, *, close=True, update=True):
        await self.page.set_content(f"""
          <style>.default {{width:120px;height:100px;background-image:linear-gradient(red, blue)}}
          .d-modal {{position:fixed;inset:10px;background:white}} button,.d-tabs-header {{padding:15px}}</style>
          <div class="cover-plugin-preview"><div class="cover"><div class="default">
            <div class="cover-edit-stack"><button class="cover-edit-entry"
              onclick="document.querySelector('.d-modal').style.display='block'">any language</button></div>
          </div></div></div>
          <div class="d-modal" style="display:none">
            <div class="d-tabs"><button class="d-tabs-header" id="upload-tab">{label}</button></div>
            <div id="upload-slot"></div>
            <div class="d-modal-footer"><button class="btn-confirm" id="save">unrelated label</button></div>
          </div>
          <template id="upload-template"><div class="upload-wrapper"><input type="file" accept="image/*"></div></template>
          <script>
          document.querySelector('#upload-tab').onclick = () => {{
            document.querySelector('#upload-slot').append(document.querySelector('#upload-template').content.cloneNode(true));
          }};
          document.querySelector('#save').onclick = () => {{
            const input = document.querySelector('input');
            window.fileName = input.files[0]?.name;
            if (!window.fileName) return;
            if ({str(update).lower()}) document.querySelector('.default').style.backgroundImage = `url('${{URL.createObjectURL(input.files[0])}}')`;
            if ({str(close).lower()}) document.querySelector('.d-modal').style.display = 'none';
          }};
          </script>
        """)

    async def set_cover(self):
        with tempfile.TemporaryDirectory() as tmp:
            cover = Path(tmp) / "cover.png"
            cover.write_bytes(
                base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6k9sAAAAASUVORK5CYII="
                )
            )
            with (
                patch.object(rednote, "REDNOTE_COVER_INPUT_PROBE_TIMEOUT_MS", 100),
                patch.object(rednote, "REDNOTE_COVER_TAB_TIMEOUT_MS", 300),
                patch.object(rednote, "REDNOTE_COVER_MODAL_CLOSE_TIMEOUT_MS", 200),
            ):
                await self.app.set_thumbnail(
                    self.page, str(cover), humanizer=self.humanizer
                )

    async def test_cover_uses_rednote_modal_and_observed_upload_tab(self):
        for label in ("上传封面",):
            with self.subTest(label=label):
                await self.cover_page(label)
                await self.set_cover()
                self.assertEqual(
                    await self.page.locator("input").evaluate(
                        "element => element.files[0]?.name"
                    ),
                    "cover.png",
                )
                self.assertFalse(await self.page.locator(".d-modal").is_visible())

    async def test_cover_requires_close_and_changed_preview(self):
        for close, update in ((False, True), (True, False)):
            with self.subTest(close=close, update=update):
                await self.cover_page("上传封面", close=close, update=update)
                with self.assertRaisesRegex(RuntimeError, "尚未点击发布"):
                    await self.set_cover()

    async def test_original_state_must_be_known_and_match_after_change(self):
        self.app.original_declaration = False
        for states, clicks, fails in (
            ([False], 0, False),
            ([None], 0, True),
            ([True, True], 1, True),
            ([True, False], 1, False),
        ):
            with self.subTest(states=states):
                await self.page.set_content(
                    '<button class="original-wrapper"><span class="d-switch">any language</span></button>'
                )
                humanizer = SimpleNamespace(click=AsyncMock())
                with patch.object(
                    self.app,
                    "_read_original_switch_state",
                    AsyncMock(side_effect=states),
                ):
                    if fails:
                        with self.assertRaises(RuntimeError):
                            await self.app.apply_declarations(
                                self.page, humanizer=humanizer
                            )
                    else:
                        await self.app.apply_declarations(
                            self.page, humanizer=humanizer
                        )
                self.assertEqual(humanizer.click.await_count, clicks)

    async def test_new_topic_is_not_an_existing_topic_candidate(self):
        await self.page.set_content("""<div id="creator-editor-topic-container">
          <div class="item"><span class="name">#travel</span><span class="newTopic">New topic</span></div>
        </div>""")
        candidate, count = await self.app._scan_topic_candidate(self.page, "travel")
        self.assertIsNone(candidate)
        self.assertEqual(count, 1)
        await self.page.locator(".newTopic").evaluate("(element) => element.remove()")
        candidate, count = await self.app._scan_topic_candidate(self.page, "travel")
        self.assertIsNotNone(candidate)

    async def test_topic_list_refresh_does_not_wait_for_a_removed_position(self):
        self.page.set_default_timeout(1500)
        await self.page.set_content("""<div id="creator-editor-topic-container">
          <div class="item"><span class="name">#REDeats</span></div>
          <div class="item"><span class="name">#REDSkill</span></div>
        </div>""")
        refreshed = False

        # 在真实浏览器取到集合后立即刷新 DOM；保留实际读取与自动等待行为。
        # 同时覆盖按数量遍历和按节点快照读取两种集合获取方式。
        def refresh_after_capture(original):
            async def capture(locator, *args, **kwargs):
                nonlocal refreshed
                result = await original(locator, *args, **kwargs)
                if (
                    not refreshed
                    and locator._impl_obj._selector
                    == rednote.REDNOTE_TOPIC_ITEM_SELECTOR
                ):
                    refreshed = True
                    await self.page.locator("#creator-editor-topic-container").evaluate(
                        """root => {
                          root.innerHTML = '<div class="item"><span class="name">#小红书</span><span class="newTopic">新建话题</span></div>';
                        }"""
                    )
                return result

            return capture

        started = time.monotonic()
        with (
            patch.object(Locator, "count", refresh_after_capture(Locator.count)),
            patch.object(
                Locator,
                "element_handles",
                refresh_after_capture(Locator.element_handles),
            ),
        ):
            candidate, _ = await self.app._scan_topic_candidate(self.page, "小红书")
        elapsed = time.monotonic() - started
        self.assertTrue(refreshed)
        self.assertIsNone(candidate)
        self.assertLess(elapsed, 1.0, "候选刷新后仍在等待已经消失的旧位置")

    async def test_topic_candidate_keeps_its_identity_when_the_list_reorders(self):
        for enabled in ("0", "1"):
            with (
                self.subTest(humanize=enabled),
                patch.dict(os.environ, {"HUMANIZE": enabled}),
            ):
                await self.page.set_content("""<div id="creator-editor-topic-container">
                  <div class="item" onclick="document.body.dataset.chosen='right'"><span class="name">#travel</span></div>
                  <div class="item" onclick="document.body.dataset.chosen='wrong'"><span class="name">#other</span></div>
                </div>""")
                candidate, _ = await self.app._scan_topic_candidate(self.page, "travel")
                self.assertIsNotNone(candidate)
                await self.page.locator("#creator-editor-topic-container").evaluate(
                    "root => root.append(root.firstElementChild)"
                )
                try:
                    await rednote.Humanizer(self.page).click(candidate)
                    self.assertEqual(
                        await self.page.get_attribute("body", "data-chosen"), "right"
                    )
                finally:
                    await candidate.dispose()

    async def test_original_disabled_stops_without_accepting_an_agreement(self):
        await self.page.set_content("""<div class="original-wrapper">
          <button class="d-switch" role="switch" aria-checked="false" disabled>Original</button>
        </div>""")
        self.app.original_declaration = True
        with patch.object(
            self.app, "_confirm_original_declaration", AsyncMock()
        ) as confirm:
            with self.assertRaisesRegex(RuntimeError, "平台禁用"):
                await self.app.apply_declarations(self.page, humanizer=self.humanizer)
        confirm.assert_not_awaited()

    async def test_original_toggle_avoids_fixed_footer_and_confirms_state(self):
        await self.page.set_content("""<style>
          body { margin:0; padding-top:900px; padding-bottom:900px; }
          .d-modal { position:fixed; top:100px; left:100px; z-index:20; background:white; padding:30px; }
          xhs-publish-btn { position:fixed; bottom:0; left:0; width:100%; height:200px; z-index:10; background:gray; }
        </style>
        <div class="original-wrapper"><button class="d-switch" role="switch" aria-checked="false"
          onclick="if(this.getAttribute('aria-checked')==='true'){this.setAttribute('aria-checked','false')}else{document.querySelector('.d-modal').style.display='block'}">Original</button></div>
        <xhs-publish-btn>Publish</xhs-publish-btn>
        <div class="d-modal creator-modal-style" style="display:none">
          <label class="d-checkbox"><input type="checkbox" onchange="document.querySelector('.custom-button').disabled=!this.checked">Agreement</label>
          <button class="custom-button" disabled onclick="document.querySelector('.d-switch').setAttribute('aria-checked','true');document.querySelector('.d-modal').style.display='none'">Confirm</button>
        </div>""")
        switch = self.page.locator(".original-wrapper .d-switch")
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                await switch.evaluate(
                    "element => element.scrollIntoView({block:'end'})"
                )
                self.app.original_declaration = enabled
                await self.app.apply_declarations(self.page, humanizer=self.humanizer)
                self.assertEqual(
                    await self.app._read_original_switch_state(switch), enabled
                )
                self.assertFalse(await self.page.locator(".d-modal").is_visible())

    async def test_plain_topic_fallback_closes_suggestions_before_space(self):
        humanizer = SimpleNamespace(press=AsyncMock())
        await self.app._degrade_topic("travel", humanizer, attempts=0)
        self.assertEqual(
            [call.args[0] for call in humanizer.press.await_args_list],
            ["Escape", "Space"],
        )

    async def test_source_confirmation_avoids_the_cancel_button_with_same_base_class(
        self,
    ):
        await self.page.set_content("""<div class="d-modal self-shooting-contain">
          <input type="text">
          <div class="dialog-footer">
            <button class="custom-button" onclick="document.body.dataset.choice='cancel'">Cancel</button>
            <button class="custom-button bg-red" onclick="document.body.dataset.choice='confirm';document.querySelector('.d-modal').style.display='none'">Confirm</button>
          </div>
        </div>""")
        self.app.repost_source = "Fixture source"
        await self.app._fill_repost_source(self.page, humanizer=self.humanizer)
        self.assertEqual(
            await self.page.get_attribute("body", "data-choice"), "confirm"
        )

    async def test_auto_converted_topic_is_verified_without_a_candidate_click(self):
        for inserted_name in ("travel", "wrong"):
            with self.subTest(inserted_name=inserted_name):
                await self.page.set_content("""<div class="tiptap" role="textbox" contenteditable="true">#travel</div>
                  <script>document.querySelector('.tiptap').onkeydown = event => {
                    if (event.key !== ' ') return;
                    event.preventDefault();
                    const anchor = document.createElement('a');
                    anchor.className = 'tiptap-topic';
                    anchor.dataset.topic = JSON.stringify({id:'topic-id', name:document.body.dataset.topicName});
                    event.target.replaceChildren(anchor);
                  };</script>""")
                await self.page.locator("body").evaluate(
                    "(element, name) => element.dataset.topicName = name", inserted_name
                )
                await self.page.locator(".tiptap").focus()
                with (
                    patch.object(
                        self.app,
                        "_scan_topic_candidate",
                        AsyncMock(return_value=(None, 1)),
                    ),
                    patch.object(rednote, "REDNOTE_TOPIC_READBACK_WINDOW_MS", 100),
                    patch.object(rednote.rednote_logger, "warning") as warning,
                ):
                    if inserted_name == "wrong":
                        with self.assertRaises(rednote.ElementUnusableError):
                            await self.app._insert_topic(
                                self.page, "travel", self.humanizer, baseline=[]
                            )
                    else:
                        await self.app._insert_topic(
                            self.page, "travel", self.humanizer, baseline=[]
                        )
                    warning.assert_not_called()

    async def test_source_type_alone_cannot_hide_missing_or_wrong_details(self):
        self.app.repost_source = "Fixture source"
        self.app.shoot_date = "2026-11-16"
        self.app.shoot_location = "人民公园"
        for kind, expected in (
            ("repost", "信息转载于Fixture source"),
            ("self-shot", "拍摄于2026-11-16，人民公园"),
        ):
            self.app.content_type = kind
            for actual in (expected, "wrong details", ""):
                with self.subTest(kind=kind, actual=actual):
                    await self.page.set_content(f"""
                      <div class="notation">{expected}</div>
                      <div class="wrapper">
                        <div lass="declaration-wrapper"><div class="d-select-description">来源类型已选</div></div>
                        <div class="notation">{actual}</div>
                      </div>
                    """)
                    if actual == expected:
                        await self.app._verify_source_details(self.page)
                    else:
                        with self.assertRaises(
                            (
                                RuntimeError,
                                rednote.ElementMissingError,
                                rednote.ElementUnusableError,
                            )
                        ):
                            await self.app._verify_source_details(self.page)

    async def self_shot_page(self, *, duplicate=False):
        extra = (
            '<li id="duplicate"><div class="name">人民公园</div><div class="subname">另一座城市</div></li>'
            if duplicate
            else ""
        )
        await self.page.set_content(f"""
          <div class="d-modal self-shooting-contain">
            <div class="address-input"><input></div>
            <div class="date-picker"><input onclick="document.querySelector('.d-datepicker-input-filter').style.display='block'"></div>
            <div class="dialog-footer"><button class="bg-red" onclick="document.querySelector('.d-modal').style.display='none'">确认</button></div>
          </div>
          <div class="el-autocomplete-suggestion"><ul>
            <li id="address-match"><div class="name">公园旁的商店</div><div class="subname">人民公园路1号</div></li>
            <li id="name-prefix"><div class="name">人民公园-北门</div><div class="subname">公园北侧</div></li>
            <li id="exact"><div class="name">人民公园</div><div class="subname">市中心</div></li>
            {extra}
          </ul></div>
          <div class="d-datepicker-input-filter" style="display:none"><input></div>
          <script>
          document.querySelectorAll('li').forEach(item => item.onclick = () => {{
            document.body.dataset.location = item.id;
            document.querySelector('.address-input input').value = item.querySelector('.name').textContent;
            document.querySelector('.el-autocomplete-suggestion').style.display = 'none';
          }});
          document.querySelector('.d-datepicker-input-filter input').onkeydown = event => {{
            if (event.key !== 'Enter') return;
            document.querySelector('.date-picker input').value = event.target.value;
            document.querySelector('.d-datepicker-input-filter').style.display = 'none';
          }};
          </script>
        """)
        self.app.shoot_location = "人民公园"
        self.app.shoot_date = "2026-11-16"

    async def test_self_shot_selects_exact_name_not_address_or_name_prefix(self):
        await self.self_shot_page()
        await self.app._fill_self_shot(self.page, humanizer=self.humanizer)
        self.assertEqual(
            await self.page.get_attribute("body", "data-location"), "exact"
        )
        self.assertEqual(
            await self.page.locator(".date-picker input").input_value(), "2026-11-16"
        )

    async def test_self_shot_does_not_guess_between_duplicate_names(self):
        await self.self_shot_page(duplicate=True)
        with self.assertRaisesRegex(RuntimeError, "候选不唯一"):
            await self.app._fill_self_shot(self.page, humanizer=self.humanizer)
        self.assertIsNone(await self.page.get_attribute("body", "data-location"))


if __name__ == "__main__":
    unittest.main()
