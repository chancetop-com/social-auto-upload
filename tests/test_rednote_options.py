"""Rednote option contracts against real Chromium DOM, without external requests."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from patchright.async_api import Locator, async_playwright

from sau_commands import rednote as rednote_command
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
        self,
        labels,
        *,
        wrapper='lass="declaration-wrapper"',
        persist=True,
        close=True,
        selected=None,
    ):
        options = "".join(f'<div class="d-option">{label}</div>' for label in labels)
        selected_js = (
            "document.querySelector('.d-select-description').textContent = "
            f"{json.dumps(selected)};"
            if selected is not None
            else "document.querySelector('.d-select-description').textContent = option.textContent;"
        )
        await self.page.set_content(f"""
          <div {wrapper} onclick="document.querySelector('.d-popover').style.display='block'">
            <div class="d-select-content"><div class="d-select-description">unset</div></div>
          </div>
          <div class="d-popover d-dropdown declaration-drop-down" style="display:none">{options}</div>
          <script>
          document.querySelectorAll('.d-option').forEach(option => option.onclick = () => {{
            document.body.dataset.selected = option.textContent;
            if ({str(persist).lower()}) {selected_js}
            if ({str(close).lower()}) document.querySelector('.d-popover').style.display = 'none';
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
        self.assertEqual(
            self.app.declaration_report,
            {
                "requested": "ai",
                "requested_label": "笔记含AI合成内容",
                "observed": "笔记含AI合成内容",
                "status": "set",
            },
        )

    async def test_declaration_menu_must_collapse_before_readback(self):
        await self.declaration_page(["笔记含AI合成内容"], close=False)
        self.app.content_type = "ai"
        with self.assertRaisesRegex(RuntimeError, "菜单未收起.*尚未点击发布"):
            await self.app.apply_declarations(self.page, humanizer=self.humanizer)

    async def test_empty_selected_value_is_a_pre_publish_failure(self):
        await self.declaration_page(["笔记含AI合成内容"], selected="")
        self.app.content_type = "ai"
        with self.assertRaises(RuntimeError) as ctx:
            await self.app.apply_declarations(self.page, humanizer=self.humanizer)
        message = str(ctx.exception)
        self.assertIn("请求=ai", message)
        self.assertIn("终值=（空）", message)
        self.assertIn("选中的内容类型为空", message)
        self.assertIn("尚未点击发布", message)

    async def test_other_selected_value_is_a_pre_publish_failure(self):
        await self.declaration_page(
            ["笔记含AI合成内容"], selected="内容包含营销广告"
        )
        self.app.content_type = "ai"
        with self.assertRaises(RuntimeError) as ctx:
            await self.app.apply_declarations(self.page, humanizer=self.humanizer)
        message = str(ctx.exception)
        self.assertIn("请求=ai", message)
        self.assertIn("终值=内容包含营销广告", message)
        self.assertIn("回读不符", message)
        self.assertIn("尚未点击发布", message)

    async def test_missing_declaration_entry_reports_request_and_reason(self):
        await self.declaration_page(["笔记含AI合成内容"], wrapper='class="other"')
        self.app.content_type = "ai"
        original = rednote.wait_resolved

        async def fast(*args, **kwargs):
            kwargs["timeout_ms"] = 0
            return await original(*args, **kwargs)

        with patch.object(rednote, "wait_resolved", fast):
            with self.assertRaises(RuntimeError) as ctx:
                await self.app.apply_declarations(
                    self.page, humanizer=self.humanizer
                )
        message = str(ctx.exception)
        self.assertIn("请求=ai", message)
        self.assertIn("终值=未读到", message)
        self.assertIn("未找到内容类型声明入口", message)
        self.assertIn("尚未点击发布", message)

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

    async def test_omitted_content_type_keeps_the_page_preset(self):
        await self.page.set_content("""
          <div lass="declaration-wrapper">
            <div class="d-select-description">笔记含AI合成内容</div>
          </div>
        """)
        self.app.content_type = None
        await self.app.apply_declarations(self.page, humanizer=self.humanizer)
        self.assertEqual(
            await self.page.locator(".d-select-description").inner_text(),
            "笔记含AI合成内容",
        )
        self.assertIsNone(self.app.declaration_report)

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

    async def test_original_and_ai_are_combinable(self):
        await self.declaration_page(["笔记含AI合成内容"])
        await self.page.evaluate(
            """() => document.body.insertAdjacentHTML(
              'afterbegin',
              '<div class="original-wrapper"><button class="d-switch" role="switch" aria-checked="true">Original</button></div>'
            )"""
        )
        self.app.original_declaration = True
        self.app.content_type = "ai"
        await self.app.apply_declarations(self.page, humanizer=self.humanizer)
        self.assertEqual(
            self.app.declaration_report["observed"], "笔记含AI合成内容"
        )

    async def test_same_name_new_topic_is_a_clickable_candidate(self):
        await self.page.set_content("""<div id="creator-editor-topic-container">
          <div class="item"><span class="name">#travel</span><span class="newTopic">新建话题</span></div>
        </div>""")
        candidate, count = await self.app._scan_topic_candidate(self.page, "travel")
        self.assertIsNotNone(candidate)
        self.assertEqual(count, 1)
        await candidate.dispose()

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

    async def inline_topic_page(self, rows, *, hard_limit=False):
        data = json.dumps(rows, ensure_ascii=False)
        limit = (
            '<div class="edit-container"><div class="length-error">超限</div></div>'
            if hard_limit
            else ""
        )
        await self.page.set_content(f"""
          <style>
            .tiptap {{ min-height: 40px; padding: 8px; border: 1px solid #ccc; white-space: pre-wrap; }}
            #creator-editor-topic-container {{ position:absolute; top:120px; left:0; z-index:9; }}
            #creator-editor-topic-container .item {{ display:block; padding:4px 8px; background:#fff; cursor:pointer; }}
          </style>
          <div class="tiptap" role="textbox" contenteditable="true"></div>
          <div id="creator-editor-topic-container"></div>
          {limit}
          <button id="publish-btn" style="position:fixed;bottom:0;left:0">发布</button>
          <script>
            document.body.dataset.publishDowns = '0';
            document.addEventListener('mousedown', (event) => {{
              if (event.target && event.target.id === 'publish-btn') {{
                const current = Number(document.body.dataset.publishDowns || '0');
                document.body.dataset.publishDowns = String(current + 1);
              }}
            }}, true);
          </script>
          <script>
            (() => {{
            window.topicMap = {data};
            const editor = document.querySelector('.tiptap');
            const container = document.querySelector('#creator-editor-topic-container');
            let lastQuery = null;
            function lastTextNode() {{
              const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT);
              let node, last = null;
              while ((node = walker.nextNode())) last = node;
              return last;
            }}
            function trailingQuery() {{
              const node = lastTextNode();
              if (!node) return null;
              const match = node.nodeValue.match(/#([^\\s#]+)$/);
              return match ? match[1] : null;
            }}
            function choose(row) {{
              const node = lastTextNode();
              if (!node || !lastQuery) return;
              const token = '#' + lastQuery;
              if (!node.nodeValue.endsWith(token)) return;
              node.nodeValue = node.nodeValue.slice(0, -token.length);
              const anchor = document.createElement('a');
              anchor.className = 'tiptap-topic';
              anchor.contentEditable = 'false';
              const name = row.name || lastQuery;
              anchor.dataset.topic = JSON.stringify({{id: 'id-' + name, link: '', name: name}});
              anchor.textContent = '#' + name;
              const hidden = document.createElement('span');
              hidden.className = 'content-hide';
              hidden.textContent = '[话题]#';
              anchor.appendChild(hidden);
              if (row.mode === 'swallow') node.nodeValue = node.nodeValue.slice(0, -2);
              if (row.mode === 'misplace' && editor.firstChild) {{
                editor.insertBefore(anchor, editor.firstChild);
              }} else {{
                node.parentNode.insertBefore(anchor, node.nextSibling);
              }}
              const space = document.createTextNode('\\u00a0');
              node.parentNode.insertBefore(space, anchor.nextSibling);
              if (row.mode === 'extra') {{
                node.parentNode.insertBefore(document.createTextNode('EXTRA'), space.nextSibling);
              }}
              editor.focus();
              const range = document.createRange();
              range.setStart(space, 1);
              range.collapse(true);
              const selection = window.getSelection();
              selection.removeAllRanges();
              selection.addRange(range);
              container.innerHTML = '';
            }}
            function render() {{
              const query = trailingQuery();
              lastQuery = query;
              container.innerHTML = '';
              if (!query || !(query in window.topicMap)) return;
              for (const row of window.topicMap[query]) {{
                const item = document.createElement('div');
                item.className = 'item';
                const label = document.createElement('span');
                label.className = 'name';
                label.textContent = row.label;
                item.appendChild(label);
                if (row.new) {{
                  const fresh = document.createElement('span');
                  fresh.className = 'newTopic';
                  fresh.textContent = '新建话题';
                  item.appendChild(fresh);
                }}
                item.onclick = () => choose(row);
                container.appendChild(item);
              }}
            }}
            editor.addEventListener('input', render);
            document.addEventListener('keydown', (event) => {{
              if (event.key === 'Escape') container.innerHTML = '';
            }});
            }})();
          </script>
        """)

    def inline_app(self, action: str, caption: str):
        if action == "upload-note":
            app = rednote.RednoteNote(
                image_paths=["a.png"],
                note=caption,
                title="标题",
                tags=[],
                publish_date=0,
                account_file="unused.json",
                no_publish=True,
            )
        else:
            app = rednote.RednoteVideo(
                title="标题",
                file_path="unused.mp4",
                tags=[],
                publish_date=0,
                account_file="unused.json",
                desc=caption,
                no_publish=True,
            )
        app.start_publish_budget()
        self.enterContext(patch.object(app, "_settle", AsyncMock()))
        return app

    async def run_inline_caption(self, app, caption: str):
        app.desc = caption
        with (
            patch.object(rednote, "REDNOTE_TOPIC_READY_WINDOW_MS", 300),
            patch.object(rednote, "REDNOTE_TOPIC_READBACK_WINDOW_MS", 150),
        ):
            await app.fill_desc(self.page, humanizer=self.humanizer)
        return app

    async def editor_anchor_names(self):
        nodes = self.page.locator('div.tiptap[role="textbox"] a[data-topic]')
        raw = await nodes.evaluate_all(
            "nodes => nodes.map(node => node.getAttribute('data-topic'))"
        )
        return [json.loads(item)["name"] for item in raw]

    async def test_inline_topic_links_ordinary_and_new_topic_in_place(self):
        for action in ("upload-video", "upload-note"):
            with self.subTest(action=action):
                caption = "Today #coffee, then #qzx974631sau."
                await self.inline_topic_page(
                    {
                        "coffee": [
                            {"label": "#coffeecreamer"},
                            {"label": "#coffee探店"},
                            {"label": "#coffee"},
                        ],
                        "qzx974631sau": [
                            {"label": "#qzx974631sau-latte"},
                            {"label": "#qzx974631sau", "new": True},
                        ],
                    }
                )
                app = self.inline_app(action, caption)

                await self.run_inline_caption(app, caption)

                self.assertEqual(app.caption_readback, caption)
                self.assertEqual(
                    [item["status"] for item in app.topic_results],
                    ["linked", "linked"],
                )
                self.assertEqual(
                    await self.editor_anchor_names(),
                    ["coffee", "qzx974631sau"],
                )
                body = await self.page.locator(".tiptap").inner_text()
                self.assertNotIn("\u00a0", body)

    async def test_inline_caption_preserves_duplicates_links_punctuation_and_newlines(
        self,
    ):
        caption = (
            "第一行 #咖啡，紧邻。#咖啡！\n"
            "链接 https://example.com/#片段 保留\n"
            "Mixed #Coffee_2 end"
        )
        await self.inline_topic_page(
            {
                "咖啡": [{"label": "#咖啡"}],
                "Coffee_2": [{"label": "#Coffee_2"}],
            }
        )
        app = self.inline_app("upload-video", caption)

        await self.run_inline_caption(app, caption)

        self.assertEqual(app.caption_readback, caption)
        self.assertEqual(
            [(item["index"], item["text"]) for item in app.topic_results],
            [(1, "#咖啡"), (2, "#咖啡"), (3, "#Coffee_2")],
        )
        self.assertEqual(
            await self.editor_anchor_names(), ["咖啡", "咖啡", "Coffee_2"]
        )
        body = await self.page.locator(".tiptap").inner_text()
        self.assertNotIn("\u00a0", body)
        self.assertIn("https://example.com/#片段", body)

    async def test_inline_auto_nbsp_is_removed_and_author_nbsp_is_kept(self):
        caption = "A #coffee, B #tea\u00a0end"
        await self.inline_topic_page(
            {
                "coffee": [{"label": "#coffee"}],
                "tea": [{"label": "#tea"}],
            }
        )
        app = self.inline_app("upload-note", caption)

        await self.run_inline_caption(app, caption)

        self.assertEqual(app.caption_readback, caption)
        self.assertEqual(await self.editor_anchor_names(), ["coffee", "tea"])
        body = await self.page.locator(".tiptap").inner_text()
        # 逗号前是作者自己的半角逗号；第二个话题后是作者自己的 U+00A0。
        self.assertIn(", B", body)
        self.assertIn("\u00a0end", body)
        self.assertEqual(body.count("\u00a0"), 1)

    async def test_approximate_only_keeps_the_text(self):
        caption = "今天 #coffee，结束"
        await self.inline_topic_page(
            {"coffee": [{"label": "#coffeecreamer"}]}
        )
        app = self.inline_app("upload-video", caption)

        await self.run_inline_caption(app, caption)

        self.assertEqual(app.caption_readback, caption)
        self.assertEqual(await self.editor_anchor_names(), [])
        self.assertEqual(
            app.topic_results,
            [
                {
                    "index": 1,
                    "name": "coffee",
                    "text": "#coffee",
                    "status": "text",
                    "reason": "无同名候选",
                }
            ],
        )

    async def test_eleventh_topic_stays_text_and_remains_readable(self):
        caption = " ".join(f"#tag{i}" for i in range(12))
        await self.inline_topic_page(
            {f"tag{i}": [{"label": f"#tag{i}"}] for i in range(12)}
        )
        app = self.inline_app("upload-note", caption)

        await self.run_inline_caption(app, caption)

        self.assertEqual(app.caption_readback, caption)
        self.assertEqual(
            await self.editor_anchor_names(), [f"tag{i}" for i in range(10)]
        )
        self.assertEqual(
            [item["status"] for item in app.topic_results],
            ["linked"] * 10 + ["text"] * 2,
        )
        self.assertEqual(
            [item["reason"] for item in app.topic_results[-2:]],
            ["已达可关联上限 10", "已达可关联上限 10"],
        )
        body = await self.page.locator(".tiptap").inner_text()
        self.assertIn("#tag10", body)
        self.assertIn("#tag11", body)

    async def _assert_inline_failure(self, row: dict, expected: str):
        caption = "今天 #coffee，结束"
        await self.inline_topic_page({"coffee": [{"label": "#coffee", **row}]})
        app = self.inline_app("upload-video", caption)
        with self.assertRaises(rednote.ElementUnusableError) as ctx:
            await self.run_inline_caption(app, caption)
        self.assertFalse(ctx.exception.publish_clicked)
        self.assertIn("未点击发布", str(ctx.exception))
        self.assertIn(expected, ctx.exception.reason)
        return ctx.exception

    async def test_wrong_topic_selection_stops_before_publish(self):
        error = await self._assert_inline_failure(
            {"name": "coffeecreamer"}, "选中的话题与原词不符"
        )
        self.assertIn("实际「#coffeecreamer」", error.reason)

    async def test_swallowed_text_stops_before_publish(self):
        await self._assert_inline_failure({"mode": "swallow"}, "个字符不同")

    async def test_misplaced_topic_stops_before_publish(self):
        await self._assert_inline_failure({"mode": "misplace"}, "个字符不同")

    async def test_extra_append_stops_before_publish(self):
        error = await self._assert_inline_failure({"mode": "extra"}, "个字符不同")
        self.assertIn("EXTRA", error.reason)

    async def test_no_publish_stops_after_topic_readback_and_before_any_click(self):
        caption = "Today #coffee, then done."
        await self.inline_topic_page(
            {"coffee": [{"label": "#coffee", "new": True}]}
        )
        app = self.inline_app("upload-note", caption)
        app.no_publish = True

        with (
            patch.object(self.page, "goto", AsyncMock()),
            patch.object(self.page, "wait_for_url", AsyncMock()),
            patch.object(rednote, "_run_dom_quiet_gate", AsyncMock()),
            patch.object(rednote, "_clear_known_overlays", AsyncMock()),
            patch.object(rednote, "_note_upload_gate", AsyncMock()),
            patch.object(rednote, "_check_blocked", AsyncMock()),
            patch.object(rednote, "_wait_for_arm", AsyncMock()),
            patch.object(app, "fill_title", AsyncMock()),
            patch.object(app, "_verify_schedule_before_fire", AsyncMock()),
        ):
            await app.upload_note_content(self.page, mode="local")

        self.assertEqual(app.caption_readback, caption)
        self.assertEqual(
            [item["status"] for item in app.topic_results], ["linked"]
        )
        self.assertEqual(
            await self.page.evaluate("document.body.dataset.publishDowns"), "0"
        )

    async def test_omitted_and_topicless_captions_keep_the_existing_path(self):
        await self.inline_topic_page({"coffee": [{"label": "#coffee"}]})
        empty = self.inline_app("upload-video", "")
        await empty.fill_desc(self.page, humanizer=self.humanizer)
        self.assertEqual(await self.page.locator(".tiptap").inner_text(), "")
        self.assertIsNone(empty.topic_results)

        caption = "今天喝了咖啡，配上栗子蛋糕。"
        plain = self.inline_app("upload-video", caption)
        await plain.fill_desc(self.page, humanizer=self.humanizer)
        self.assertIsNone(plain.topic_results)
        self.assertEqual(
            await self.page.locator(".tiptap").inner_text(),
            caption + "\n\n",
        )

    async def test_whole_post_hard_limit_stops_before_publish(self):
        caption = "今天 #coffee，结束"
        await self.inline_topic_page(
            {"coffee": [{"label": "#coffee"}]}, hard_limit=True
        )
        app = self.inline_app("upload-note", caption)

        await self.run_inline_caption(app, caption)
        with self.assertRaises(rednote.ElementUnusableError) as ctx:
            await app._assert_body_not_over_limit(self.page)

        self.assertEqual(
            ctx.exception.reason, "正文超出平台长度上限（长度错误节点存在）"
        )
        self.assertFalse(ctx.exception.publish_clicked)

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



class RednoteInlineTopicCliTests(unittest.TestCase):
    def _args(self, action: str = "upload-video"):
        return SimpleNamespace(
            action=action,
            file="demo.mp4",
            images=["a.png"],
            title="标题",
            desc="今天 #咖啡，重复 #咖啡。",
            note="今天 #咖啡，重复 #咖啡。",
            schedule=None,
            thumbnail=None,
            debug=False,
            headless=True,
            not_before=None,
            account="acct",
            location=None,
            original=None,
            content_type=None,
            repost_source=None,
            shoot_location=None,
            shoot_date=None,
            no_publish=True,
        )

    def test_topic_lines_keep_duplicates_and_the_success_summary(self):
        for action, upload_name in (
            ("upload-video", "upload_rednote_video"),
            ("upload-note", "upload_rednote_note"),
        ):
            with self.subTest(action=action):
                args = self._args(action)

                async def fake_upload(request, **_kwargs):
                    request.topic_results = [
                        {
                            "index": 1,
                            "name": "咖啡",
                            "text": "#咖啡",
                            "status": "linked",
                            "reason": None,
                        },
                        {
                            "index": 2,
                            "name": "咖啡",
                            "text": "#咖啡",
                            "status": "text",
                            "reason": "无同名候选",
                        },
                    ]

                with patch.object(
                    rednote_command,
                    "_validate_declarations",
                    return_value=(None, None, None, None, None),
                ), patch.object(
                    rednote_command, "resolve_managed_provider", return_value=None
                ), patch.object(
                    rednote_command, "require_local_account"
                ), patch.object(
                    rednote_command, "resolve_account_label", return_value="acct"
                ), patch.object(
                    rednote_command, "managed_ignored_keys", return_value=()
                ), patch.object(
                    rednote_command, upload_name, new=fake_upload
                ), redirect_stdout(
                    io.StringIO()
                ) as out, redirect_stderr(
                    io.StringIO()
                ):
                    code = asyncio.run(rednote_command.run(args))

                self.assertEqual(code, 0)
                lines = out.getvalue().splitlines()
                self.assertEqual(
                    [line for line in lines if "配文话题" in line],
                    [
                        "Rednote 配文话题 1/2：#咖啡 已关联",
                        "Rednote 配文话题 2/2：#咖啡 保留文字，无同名候选",
                    ],
                )
                self.assertIn(
                    "素材已上传，发布前检查已通过；已停止，未点击发布按钮。",
                    lines,
                )


if __name__ == "__main__":
    unittest.main()
