# -*- coding: utf-8 -*-
"""Post-location selection on both XHS and Rednote (ticket 18).

The controlled page models the DOM observed for both platforms on 2026-11-20:

* entry ``.address-card-wrapper .address-card-select``;
* candidate rows ``.option-item`` with ``.option-name`` and ``.option-subname``;
* collapsed control ``.address-card-select .d-select-description`` showing only
  the name.

Matching compares the full candidate name (trim + collapse whitespace +
casefold).  The first same-name row in page order wins; approximate names such
as ``房山人民公园`` are skipped.  A selection only succeeds when the list has
collapsed *and* the control reads back the requested name.
"""

from __future__ import annotations

import html
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from patchright.async_api import async_playwright

from uploader.rednote_uploader import main as rednote
from uploader.xiaohongshu_uploader import main as xhs
from utils.humanize import Humanizer
from utils.post_location import normalise_location_name


def _apps() -> dict[str, object]:
    common = {"tags": [], "publish_date": 0, "no_publish": True}
    return {
        "xiaohongshu-video": xhs.XiaoHongShuVideo(
            title="标题", file_path="demo.mp4", account_file="a.json", **common
        ),
        "xiaohongshu-note": xhs.XiaoHongShuNote(
            image_paths=["a.png"],
            note="",
            title="标题",
            account_file="a.json",
            **common,
        ),
        "rednote-video": rednote.RednoteVideo(
            title="标题", file_path="demo.mp4", account_file="a.json", **common
        ),
        "rednote-note": rednote.RednoteNote(
            image_paths=["a.png"],
            note="",
            title="标题",
            account_file="a.json",
            **common,
        ),
    }


class LocationNormalisationTests(unittest.TestCase):
    def test_old_positional_no_publish_still_stops_all_four_uploaders(self):
        for cls, first, rest in (
            (xhs.XiaoHongShuVideo, ("title", "v.mp4"), (None, None)),
            (rednote.RednoteVideo, ("title", "v.mp4"), (None, None)),
            (xhs.XiaoHongShuNote, (["i.png"], "note"), ("title", None)),
            (rednote.RednoteNote, (["i.png"], "note"), ("title", None)),
        ):
            with self.subTest(uploader=cls.__name__):
                app = cls(*first, [], 0, None, *rest, "immediate", False, None,
                          None, None, None, None, None, True)
                self.assertIs(app.no_publish, True)
                self.assertIsNone(app.location)

    def test_names_are_trimmed_collapsed_and_casefolded(self):
        for raw, expected in (
            ("  人民公园  ", "人民公园"),
            (" People   Park ", "people park"),
            ("PEOPLE\tPARK", "people park"),
            ("人民公园\u3000西门", "人民公园 西门"),
            ("", ""),
            (None, ""),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalise_location_name(raw), expected)


class LocationErrorContractTests(unittest.TestCase):
    def test_shared_leaf_error_keeps_its_fields_and_message(self):
        from utils.errors import LocationVerificationError

        error = LocationVerificationError(
            requested="人民公园",
            clicked_name="人民公园",
            address="上海市黄浦区南京西路231号",
            final_name="人民公园",
            reason="终值不符",
        )

        self.assertEqual(error.requested, "人民公园")
        self.assertEqual(error.clicked_name, "人民公园")
        self.assertEqual(error.address, "上海市黄浦区南京西路231号")
        self.assertEqual(error.final_name, "人民公园")
        self.assertEqual(error.reason, "终值不符")
        self.assertEqual(
            str(error),
            "帖子地点设置失败：请求=人民公园，"
            "所点行=人民公园 · 上海市黄浦区南京西路231号，"
            "终值=人民公园，原因=终值不符；尚未点击发布。",
        )


class LocationDomTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(patch.dict(os.environ, {"HUMANIZE": "0"}))
        playwright = await async_playwright().start()
        self.addAsyncCleanup(playwright.stop)
        browser = await playwright.chromium.launch(headless=True, channel="chromium")
        self.addAsyncCleanup(browser.close)
        self.page = await browser.new_page(no_viewport=True)
        self.page.set_default_timeout(1_500)
        await self.page.route("**/*", lambda route: route.abort())
        self.humanizer = Humanizer(self.page)
        self.apps = _apps()
        for module, prefix in ((xhs, "XHS"), (rednote, "REDNOTE")):
            self.enterContext(
                patch.object(module, f"{prefix}_LOCATION_INPUT_TIMEOUT_MS", 200)
            )
            self.enterContext(
                patch.object(module, f"{prefix}_LOCATION_OPTION_TIMEOUT_MS", 400)
            )
            self.enterContext(
                patch.object(module, f"{prefix}_LOCATION_COLLAPSE_TIMEOUT_MS", 300)
            )
        for app in self.apps.values():
            app.start_publish_budget()
            self.enterContext(patch.object(app, "_settle", AsyncMock()))

    async def test_caption_readback_distinguishes_authored_and_editor_breaks(self):
        await self.page.set_content('<div id="editor"></div>')
        editor = self.page.locator('#editor')
        for markup, expected in (
            ('<p>Caption<br></p>', "Caption\n"),
            ('<p>Caption<br class="ProseMirror-trailingBreak"></p>', "Caption"),
            ('<p>Caption</p><p><br class="ProseMirror-trailingBreak"></p>', "Caption\n"),
        ):
            await editor.evaluate('(el, html) => el.innerHTML = html', markup)
            for reader in (xhs.XHS_CAPTION_READBACK_JS, rednote.REDNOTE_CAPTION_READBACK_JS):
                self.assertEqual(await editor.evaluate(reader), expected)

    async def render(
        self,
        rows,
        *,
        entry=True,
        notice: str | None = None,
        collapse=True,
        final: str = "match",
    ):
        """Build the location control and its candidate list in real Chromium."""
        row_html = "".join(
            '<div class="option-item" data-name="{name}" data-address="{address}">'
            '<div class="option-name">{name}</div>{subname}</div>'.format(
                name=html.escape(row["name"], quote=True),
                address=html.escape(row.get("address") or "", quote=True),
                subname=(
                    '<div class="option-subname">{}</div>'.format(
                        html.escape(row["address"], quote=False)
                    )
                    if row.get("address")
                    else ""
                ),
            )
            for row in rows
        )
        entry_html = (
            '<div class="address-card-select" id="location-entry">'
            '<div class="d-text d-select-placeholder">添加地点</div>'
            '<div class="d-select-description"></div>'
            '<input id="location-search">'
            "</div>"
            if entry
            else ""
        )
        await self.page.set_content(
            f"""
          <div class="address-card-wrapper">
            {('<div class="location-notice">' + html.escape(notice) + "</div>") if notice else ""}
            {entry_html}
          </div>
          <div class="d-popover d-dropdown" id="location-list" style="display:none">
            {row_html}
          </div>
          <script>
          (() => {{
            const list = document.querySelector('#location-list');
            const description = document.querySelector('.d-select-description');
            const finalMode = {json.dumps(final)};
            const entry = document.querySelector('#location-entry');
            if (entry) entry.addEventListener('click', () => {{
              list.style.display = 'block';
              document.querySelector('#location-search').focus();
            }});
            document.querySelectorAll('.option-item').forEach(row => {{
              row.addEventListener('click', () => {{
                const name = row.dataset.name;
                document.body.dataset.clicked =
                  name + '|' + (row.dataset.address || '');
                if (finalMode === 'empty') {{
                  description.textContent = '';
                }} else if (finalMode === 'wrong') {{
                  description.textContent = 'Other Place';
                }} else {{
                  description.textContent = name;
                }}
                document.querySelector('#location-search').value = '';
                if ({str(collapse).lower()}) list.style.display = 'none';
              }});
            }});
          }})();
          </script>
        """
        )

    async def select(self, app, requested: str):
        app.location = requested
        return await app.set_location(
            self.page, requested, humanizer=self.humanizer
        )

    async def test_same_name_rows_keep_their_identity_across_reordering(self):
        for name, app in self.apps.items():
            with self.subTest(uploader=name):
                await self.render([{"name": "Park", "address": "A"}, {"name": "Park", "address": "B"}])
                click = self.humanizer.click
                async def reorder_before_click(target):
                    if await self.page.locator('#location-list').is_visible():
                        await self.page.locator('.option-item').first.evaluate('row => row.parentNode.append(row)')
                    await click(target)
                with patch.object(self.humanizer, "click", reorder_before_click):
                    report = await self.select(app, "Park")
                self.assertEqual(report.address, "A")
                self.assertEqual(await self.page.locator("body").get_attribute("data-clicked"), "Park|A")

    async def test_first_same_name_wins_and_address_is_reported(self):
        rows = [
            {"name": "房山人民公园", "address": "北京市房山区"},
            {"name": " People   Park ", "address": "上海市黄浦区南京西路231号"},
            {"name": "people park", "address": "成都市青羊区"},
            {"name": "PEOPLE PARK"},
        ]
        for name, app in self.apps.items():
            with self.subTest(uploader=name):
                await self.render(rows)
                report = await self.select(app, "  people   park ")
                self.assertEqual(report.requested, "people   park")
                self.assertEqual(report.clicked_name, "People   Park")
                self.assertEqual(report.address, "上海市黄浦区南京西路231号")
                self.assertEqual(report.final_name, "People Park")
                self.assertEqual(report.status, "set")
                self.assertEqual(
                    app.location_report,
                    {
                        "requested": "people   park",
                        "clicked_name": "People   Park",
                        "address": "上海市黄浦区南京西路231号",
                        "final_name": "People Park",
                        "status": "set",
                    },
                )
                self.assertEqual(
                    await self.page.get_attribute("body", "data-clicked"),
                    " People   Park |上海市黄浦区南京西路231号",
                )

    async def test_name_only_candidate_reports_no_address(self):
        for name, app in self.apps.items():
            with self.subTest(uploader=name):
                await self.render([{"name": "人民公园"}])
                report = await self.select(app, "人民公园")
                self.assertEqual(report.clicked_name, "人民公园")
                self.assertIsNone(report.address)
                self.assertEqual(report.final_name, "人民公园")

    async def test_approximate_only_rows_are_no_match(self):
        for name, app in self.apps.items():
            with self.subTest(uploader=name):
                await self.render(
                    [
                        {"name": "房山人民公园", "address": "北京市房山区"},
                        {"name": "人民公园北门", "address": "某市"},
                    ]
                )
                with self.assertRaises(RuntimeError) as ctx:
                    await self.select(app, "人民公园")
                message = str(ctx.exception)
                self.assertIn("无同名候选", message)
                self.assertIn("房山人民公园", message)
                self.assertIn("尚未点击发布", message)
                self.assertIsNone(
                    await self.page.get_attribute("body", "data-clicked")
                )

    async def test_empty_candidate_list_is_no_match(self):
        for name, app in self.apps.items():
            with self.subTest(uploader=name):
                await self.render([])
                with self.assertRaisesRegex(RuntimeError, "候选列表为空"):
                    await self.select(app, "人民公园")

    async def test_missing_entry_has_its_own_reason(self):
        for name, app in self.apps.items():
            with self.subTest(uploader=name):
                await self.render([], entry=False)
                with self.assertRaisesRegex(RuntimeError, "未找到地点入口"):
                    await self.select(app, "人民公园")

    async def test_explicit_eligibility_notice_uses_account_unavailable_wording(self):
        for name, app in self.apps.items():
            with self.subTest(uploader=name):
                await self.render(
                    [], entry=False, notice="当前账号暂不支持添加地点"
                )
                with self.assertRaises(RuntimeError) as ctx:
                    await self.select(app, "人民公园")
                message = str(ctx.exception)
                self.assertIn("账号不可用", message)
                self.assertIn("暂不支持添加地点", message)
                self.assertNotIn("未找到地点入口", message)

    async def test_list_must_collapse(self):
        for name, app in self.apps.items():
            with self.subTest(uploader=name):
                await self.render(
                    [{"name": "人民公园", "address": "上海市黄浦区"}],
                    collapse=False,
                )
                with self.assertRaisesRegex(RuntimeError, "候选列表未收起"):
                    await self.select(app, "人民公园")

    async def test_empty_final_value_is_reported_and_stops(self):
        for name, app in self.apps.items():
            with self.subTest(uploader=name):
                await self.render(
                    [{"name": "人民公园", "address": "上海市黄浦区"}], final="empty"
                )
                with self.assertRaises(RuntimeError) as ctx:
                    await self.select(app, "人民公园")
                message = str(ctx.exception)
                self.assertIn("终值=（空）", message)
                self.assertIn("终值为空", message)
                self.assertIn("尚未点击发布", message)

    async def test_different_final_value_is_reported_and_stops(self):
        for name, app in self.apps.items():
            with self.subTest(uploader=name):
                await self.render(
                    [{"name": "人民公园", "address": "上海市黄浦区"}], final="wrong"
                )
                with self.assertRaises(RuntimeError) as ctx:
                    await self.select(app, "人民公园")
                message = str(ctx.exception)
                self.assertIn("终值=Other Place", message)
                self.assertIn("终值与请求不符", message)
                self.assertIn("尚未点击发布", message)

    async def test_omitted_location_never_touches_the_post_location_control(self):
        for name, app in self.apps.items():
            with self.subTest(uploader=name):
                await self.page.set_content(
                    '<div class="address-card-wrapper"><div class="address-card-select">'
                    '<div class="d-select-description">人民公园</div></div></div>'
                )
                app.location = None
                result = await app.apply_location(
                    self.page, humanizer=self.humanizer
                )
                self.assertIsNone(result)
                self.assertIsNone(app.location_report)
                self.assertEqual(
                    await self.page.locator(".d-select-description").inner_text(),
                    "人民公园",
                )

    async def test_self_shot_location_does_not_write_the_post_location(self):
        """``--shoot-location`` belongs to the declaration modal, not this control."""
        await self.page.set_content("""
          <div class="address-card-wrapper"><div class="address-card-select">
            <div class="d-select-description">人民公园</div>
          </div></div>
          <div class="d-modal self-shooting-contain">
            <div class="address-input"><input></div>
            <div class="date-picker"><input></div>
            <div class="dialog-footer"><button class="bg-red">确认</button></div>
          </div>
          <div class="el-autocomplete-suggestion"><ul>
            <li><div class="name">北京</div><div class="subname">北京市</div></li>
          </ul></div>
          <div class="d-datepicker-input-filter"><input></div>
          <script>
          document.querySelector('.el-autocomplete-suggestion li').onclick = () => {
            document.querySelector('.address-input input').value = '北京';
          };
          document.querySelector('.d-datepicker-input-filter input')
            .addEventListener('keydown', event => {
              if (event.key !== 'Enter') return;
              document.querySelector('.date-picker input').value =
                event.target.value;
            });
          document.querySelector('.dialog-footer button').onclick = () => {
            document.querySelector('.d-modal').style.display = 'none';
          };
          </script>
        """)
        app = self.apps["rednote-note"]
        app.shoot_location = "北京"
        app.shoot_date = "2026-11-20"
        with patch.object(app, "_settle", AsyncMock()):
            await app._fill_self_shot(self.page, humanizer=self.humanizer)
        self.assertEqual(
            await self.page.locator(".address-input input").input_value(), "北京"
        )
        self.assertEqual(
            await self.page.locator(".d-select-description").inner_text(),
            "人民公园",
        )


if __name__ == "__main__":
    unittest.main()
