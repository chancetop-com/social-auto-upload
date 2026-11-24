"""Instagram 协作者受控 DOM 回归（C 层：真实系统 Chrome）。

覆盖图文/轮播 chip 回读、Reels checkbox 回读、兄弟 portal 面板与 Done 收起。
共享页面夹具在 ``tests/instagram_collaborators_fixtures.py``。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from patchright.async_api import async_playwright

from uploader.meta_uploader.insgraph_uploader.controls import (
    collaborators as collaborators_control_module,
)
from uploader.meta_uploader.insgraph_uploader.controls.collaborators import (
    CollaboratorsControl,
)
from uploader.meta_uploader.insgraph_uploader.main import InstagramUploader
from uploader.meta_uploader.insgraph_uploader.options import (
    ACCOUNT_INELIGIBLE,
    CONTROL_DISABLED,
    EDITOR_OBSCURED,
    ENTRY_MISSING,
    FINAL_MISMATCH,
    LIST_NOT_COLLAPSED,
    MISMATCH,
    NO_CANDIDATES,
    NO_SAME_USERNAME,
    PRESENT,
    SELECTION_FAILED,
    SET,
    UNSUPPORTED,
    InstagramPublishOptions,
    OptionMismatchError,
)
from tests.instagram_collaborators_fixtures import (
    collaborator_page_html,
    expire_budget_after_username,
    sibling_panel_page_html,
    timeout_patches,
)
from utils.errors import PublishResultUnknownError


class InstagramCollaboratorControlDomTests(unittest.TestCase):
    """C 层：真实 Chrome + 受控页，验证面板/精确匹配/chip 回读/Done。"""

    def _apply(
        self,
        html,
        *,
        options,
        image_count=1,
        expire_after_selection=None,
        readback_timeout_ms=None,
        page_timeout_ms=None,
    ):
        holder: dict[str, object] = {}

        async def scenario():
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel="chrome", headless=True)
                page = await browser.new_page()
                try:
                    await page.set_content(html)
                    if page_timeout_ms is not None:
                        page.set_default_timeout(page_timeout_ms)
                    with tempfile.TemporaryDirectory() as folder:
                        images = [
                            str(Path(folder) / f"image-{index}.png")
                            for index in range(image_count)
                        ]
                        result_file = Path(folder) / "result.json"
                        app = InstagramUploader(
                            "unused.json",
                            title="caption",
                            image_files=images,
                            options=options,
                            result_file=result_file,
                        )
                        budget = app.start_publish_budget()
                        monitor = None
                        if expire_after_selection is not None:
                            monitor = asyncio.create_task(
                                expire_budget_after_username(
                                    page, budget, expire_after_selection
                                )
                            )
                        error = None
                        try:
                            await app._apply_options(page, budget=budget)
                        except Exception as wrapped:
                            error = wrapped
                        finally:
                            if monitor is not None:
                                monitor.cancel()
                                with contextlib.suppress(asyncio.CancelledError):
                                    await monitor
                        holder["app"] = app
                        holder["error"] = error
                        holder["saved"] = (
                            json.loads(result_file.read_text(encoding="utf-8"))
                            if result_file.exists()
                            else app.result
                        )
                        holder["share_clicks"] = int(
                            await page.locator("[data-share-clicks]")
                            .get_attribute("data-share-clicks") or 0
                        )
                        holder["chips"] = await page.evaluate(
                            """() => [...document.querySelectorAll('#chips > span')]
                                .map(node => {
                                  const name = node.querySelector('span');
                                  return name ? name.textContent : '';
                                }).filter(Boolean)"""
                        )
                        body = page.locator("body")
                        queries = await body.get_attribute("data-queries")
                        holder["queries"] = json.loads(queries) if queries else []
                        holder["entry_clicks"] = int(
                            await body.get_attribute("data-entry-clicks") or 0
                        )
                        holder["row_clicks"] = int(
                            await body.get_attribute("data-row-clicks") or 0
                        )
                        holder["done_clicks"] = int(
                            await body.get_attribute("data-done-clicks") or 0
                        )
                finally:
                    await browser.close()

        patches = list(timeout_patches())
        if readback_timeout_ms is not None:
            patches.append(
                patch.object(
                    collaborators_control_module,
                    "READBACK_TIMEOUT_MS",
                    readback_timeout_ms,
                )
            )
        for item in patches:
            item.start()
        try:
            with patch.dict(os.environ, {"HUMANIZE": "0"}):
                asyncio.run(scenario())
        finally:
            for item in patches:
                item.stop()
        return SimpleNamespace(**holder)

    def test_note_selection_follows_request_order_and_reads_chips(self):
        html = collaborator_page_html(
            [("alice", "Alice A"), ("bob", "Bob B")]
        )
        outcome = self._apply(
            html,
            options=InstagramPublishOptions(collaborators=("alice", "bob")),
        )
        self.assertIsNone(outcome.error)
        expected = {
            "requested": ["alice", "bob"],
            "applied": ["alice", "bob"],
            "status": SET,
        }
        self.assertEqual(outcome.saved["options"]["collaborators"], expected)
        self.assertEqual(outcome.chips, ["alice", "bob"])
        self.assertEqual(outcome.share_clicks, 0)
        self.assertEqual(outcome.done_clicks, 1)
        self.assertEqual(
            [query for query in outcome.queries if query], ["alice", "bob"]
        )

    def test_one_and_five_collaborators_are_supported(self):
        for count in (1, 5):
            with self.subTest(count=count):
                candidates = [
                    (f"user{index}", f"User {index}") for index in range(count)
                ]
                requested = tuple(username for username, _ in candidates)
                outcome = self._apply(
                    collaborator_page_html(candidates),
                    options=InstagramPublishOptions(collaborators=requested),
                )
                self.assertIsNone(outcome.error)
                self.assertEqual(
                    outcome.saved["options"]["collaborators"]["applied"],
                    list(requested),
                )
                self.assertEqual(outcome.chips, list(requested))
                self.assertEqual(outcome.share_clicks, 0)

    def test_nike_never_selects_a_substring_candidate(self):
        html = collaborator_page_html(
            [("_nikeza5", "nikeza"), ("nike", "Nike")]
        )
        outcome = self._apply(
            html,
            options=InstagramPublishOptions(collaborators=("nike",)),
        )
        self.assertIsNone(outcome.error)
        self.assertEqual(
            outcome.saved["options"]["collaborators"]["applied"], ["nike"]
        )
        self.assertEqual(outcome.chips, ["nike"])
        self.assertEqual(outcome.row_clicks, 1)

    def test_english_and_chinese_placeholder_fallbacks(self):
        for entry in ("en", "zh"):
            with self.subTest(entry=entry):
                outcome = self._apply(
                    collaborator_page_html(
                        [("alice", "Alice")], entry=entry
                    ),
                    options=InstagramPublishOptions(collaborators=("alice",)),
                )
                self.assertIsNone(outcome.error)
                self.assertEqual(outcome.chips, ["alice"])

    def test_already_selected_chip_is_not_clicked_again(self):
        html = collaborator_page_html(
            [("alice", "Alice"), ("bob", "Bob")], preselect=("alice",)
        )
        outcome = self._apply(
            html,
            options=InstagramPublishOptions(collaborators=("alice", "bob")),
        )
        self.assertIsNone(outcome.error)
        self.assertEqual(outcome.chips, ["alice", "bob"])
        self.assertEqual(outcome.row_clicks, 1)

    def test_browser_error_after_confirmed_prefix_keeps_applied(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice"), ("bob", "Bob")],
                hide_stamped_after="alice",
            ),
            options=InstagramPublishOptions(collaborators=("alice", "bob")),
            readback_timeout_ms=2_000,
            page_timeout_ms=500,
        )
        self.assertIsNotNone(outcome.error)
        self.assertNotIsInstance(outcome.error, PublishResultUnknownError)
        message = str(outcome.error)
        self.assertIn("已确认", message)
        self.assertIn("alice", message)
        self.assertNotIn("15 分钟", message)
        record = outcome.saved["options"]["collaborators"]
        self.assertEqual(record["requested"], ["alice", "bob"])
        self.assertEqual(record["applied"], ["alice"])
        self.assertEqual(record["status"], MISMATCH)
        self.assertNotIn("reason", record)
        self.assertEqual(outcome.chips, ["alice"])
        self.assertIn("bob", outcome.queries)
        self.assertEqual(outcome.share_clicks, 0)

    def test_panel_that_never_opens_is_list_not_collapsed_before_typing(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice")], panel_opens=False
            ),
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        message = str(outcome.error)
        self.assertIn("collaborators=mismatch(list_not_collapsed)", message)
        self.assertIn("面板未能打开", message)
        record = outcome.saved["options"]["collaborators"]
        self.assertIsNone(record["applied"])
        self.assertEqual(record["reason"], LIST_NOT_COLLAPSED)
        self.assertEqual(outcome.queries, [])
        self.assertEqual(outcome.chips, [])
        self.assertEqual(outcome.row_clicks, 0)
        self.assertEqual(outcome.share_clicks, 0)

    def test_missing_entry_is_unsupported(self):
        outcome = self._apply(
            collaborator_page_html([("alice", "Alice")], entry="missing"),
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        self.assertIn("collaborators=unsupported(entry_missing)", str(outcome.error))
        self.assertEqual(
            outcome.saved["options"]["collaborators"],
            {
                "requested": ["alice"],
                "applied": None,
                "status": UNSUPPORTED,
                "reason": ENTRY_MISSING,
            },
        )
        self.assertEqual(outcome.entry_clicks, 0)

    def test_disabled_entry_is_control_disabled(self):
        outcome = self._apply(
            collaborator_page_html([("alice", "Alice")], entry="disabled"),
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        self.assertIn(
            "collaborators=unsupported(control_disabled)", str(outcome.error)
        )
        self.assertEqual(
            outcome.saved["options"]["collaborators"]["reason"],
            CONTROL_DISABLED,
        )
        self.assertEqual(outcome.entry_clicks, 0)

    def test_no_candidates_stops_before_later_usernames(self):
        outcome = self._apply(
            collaborator_page_html([], row_click="select"),
            options=InstagramPublishOptions(collaborators=("alice", "bob")),
        )
        self.assertIn("collaborators=mismatch(no_candidates)", str(outcome.error))
        self.assertEqual(
            outcome.saved["options"]["collaborators"],
            {
                "requested": ["alice", "bob"],
                "applied": [],
                "status": MISMATCH,
                "reason": NO_CANDIDATES,
            },
        )
        self.assertTrue(outcome.queries)
        self.assertIn("alice", outcome.queries)
        self.assertNotIn("bob", outcome.queries)
        self.assertEqual(outcome.chips, [])
        self.assertEqual(outcome.share_clicks, 0)

    def test_first_username_mismatch_keeps_confirmed_prefix(self):
        html = collaborator_page_html(
            [("alice", "Alice"), ("_bobby", "Bobby")]
        )
        outcome = self._apply(
            html,
            options=InstagramPublishOptions(
                collaborators=("alice", "bob", "carol")
            ),
        )
        self.assertIn(
            "collaborators=mismatch(no_same_username_candidate)",
            str(outcome.error),
        )
        self.assertEqual(
            outcome.saved["options"]["collaborators"],
            {
                "requested": ["alice", "bob", "carol"],
                "applied": ["alice"],
                "status": MISMATCH,
                "reason": NO_SAME_USERNAME,
            },
        )
        self.assertEqual(outcome.chips, ["alice"])
        self.assertNotIn("carol", outcome.queries)
        self.assertEqual(outcome.share_clicks, 0)

    def test_final_mismatch_readback_with_limit_notice_keeps_detail(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice")],
                render_chips=False,
                restriction=(
                    '<div role="alert">'
                    "You can only add up to 2 collaborators."
                    "</div>"
                ),
            ),
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        message = str(outcome.error)
        self.assertIn("collaborators=mismatch(final_mismatch)", message)
        record = outcome.saved["options"]["collaborators"]
        self.assertEqual(record["applied"], [])
        self.assertEqual(record["status"], MISMATCH)
        self.assertEqual(record["reason"], FINAL_MISMATCH)
        self.assertIn("第 1 个", record["detail"])
        self.assertIn("上限", record["detail"])
        self.assertEqual(outcome.row_clicks, 1)
        self.assertEqual(outcome.share_clicks, 0)

    def test_page_limit_refusal_is_final_mismatch_with_detail(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice"), ("bob", "Bob"), ("carol", "Carol")],
                page_limit=2,
                limit_notice=(
                    "You can only add up to 2 collaborators."
                ),
            ),
            options=InstagramPublishOptions(
                collaborators=("alice", "bob", "carol")
            ),
        )
        message = str(outcome.error)
        self.assertIn("collaborators=mismatch(final_mismatch)", message)
        self.assertNotIn("selection_failed", message)
        record = outcome.saved["options"]["collaborators"]
        self.assertEqual(record["requested"], ["alice", "bob", "carol"])
        self.assertEqual(record["applied"], ["alice", "bob"])
        self.assertEqual(record["status"], MISMATCH)
        self.assertEqual(record["reason"], FINAL_MISMATCH)
        self.assertIn("第 3 个", record["detail"])
        self.assertIn("上限", record["detail"])
        self.assertEqual(outcome.chips, ["alice", "bob"])
        self.assertEqual(outcome.done_clicks, 0)
        self.assertEqual(outcome.share_clicks, 0)

    def test_click_without_selection_is_selection_failed(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice")], row_click="ignore"
            ),
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        self.assertIn(
            "collaborators=mismatch(selection_failed)", str(outcome.error)
        )
        record = outcome.saved["options"]["collaborators"]
        self.assertEqual(record["reason"], SELECTION_FAILED)
        self.assertEqual(record["applied"], [])
        self.assertNotIn("detail", record)
        self.assertEqual(outcome.share_clicks, 0)

    def test_missing_chip_readback_is_final_mismatch(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice")], render_chips=False
            ),
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        self.assertIn(
            "collaborators=mismatch(final_mismatch)", str(outcome.error)
        )
        self.assertEqual(
            outcome.saved["options"]["collaborators"]["reason"], FINAL_MISMATCH
        )
        self.assertEqual(outcome.share_clicks, 0)

    def test_unreadable_chip_and_checkbox_readback_is_final_mismatch(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice")], row_click="detach-entry"
            ),
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        self.assertIn(
            "collaborators=mismatch(final_mismatch)", str(outcome.error)
        )
        record = outcome.saved["options"]["collaborators"]
        self.assertIsNone(record["applied"])
        self.assertEqual(record["reason"], FINAL_MISMATCH)
        self.assertEqual(outcome.share_clicks, 0)

    def test_explicit_account_restriction_is_account_ineligible(self):
        notices = (
            '<div role="alert">'
            "Cannot add collaborators to this account."
            "</div>",
            '<div aria-live="polite">'
            "Cannot add collaborators to this account."
            "</div>",
            '<div aria-live="assertive">'
            "Cannot add collaborators to this account."
            "</div>",
        )
        for notice in notices:
            with self.subTest(notice=notice):
                outcome = self._apply(
                    collaborator_page_html(
                        [("alice", "Alice")],
                        entry="missing",
                        restriction=notice,
                    ),
                    options=InstagramPublishOptions(
                        collaborators=("alice",)
                    ),
                )
                self.assertIn(
                    "collaborators=unsupported(account_ineligible)",
                    str(outcome.error),
                )
                record = outcome.saved["options"]["collaborators"]
                self.assertEqual(record["reason"], ACCOUNT_INELIGIBLE)
                self.assertIn("Cannot add collaborators", record["detail"])
                self.assertEqual(outcome.share_clicks, 0)

    def test_missing_done_is_list_not_collapsed_not_entry_missing(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice")], done_label="Fertig"
            ),
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        message = str(outcome.error)
        self.assertIn("collaborators=mismatch(list_not_collapsed)", message)
        self.assertNotIn("entry_missing", message)
        record = outcome.saved["options"]["collaborators"]
        self.assertEqual(record["applied"], ["alice"])
        self.assertEqual(record["reason"], LIST_NOT_COLLAPSED)
        self.assertEqual(outcome.chips, ["alice"])
        self.assertEqual(outcome.share_clicks, 0)

    def test_mid_list_budget_exhaustion_keeps_the_confirmed_prefix(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice"), ("bob", "Bob"), ("carol", "Carol")],
                checkbox_delay_ms=250,
                confirm_delay_ms=400,
            ),
            options=InstagramPublishOptions(
                collaborators=("alice", "bob", "carol")
            ),
            expire_after_selection="alice",
            readback_timeout_ms=2_000,
        )
        self.assertIsNotNone(outcome.error)
        self.assertIn("15 分钟", str(outcome.error))
        self.assertNotIsInstance(outcome.error, PublishResultUnknownError)
        record = outcome.saved["options"]["collaborators"]
        self.assertEqual(record["requested"], ["alice", "bob", "carol"])
        self.assertEqual(record["applied"], ["alice"])
        self.assertEqual(record["status"], MISMATCH)
        self.assertNotIn("reason", record)
        self.assertIn("alice", outcome.queries)
        self.assertNotIn("bob", outcome.queries)
        self.assertNotIn("carol", outcome.queries)
        self.assertEqual(outcome.chips, ["alice"])
        self.assertEqual(outcome.share_clicks, 0)

    def test_done_that_does_not_collapse_is_list_not_collapsed(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice"), ("bob", "Bob")], done_collapses=False
            ),
            options=InstagramPublishOptions(collaborators=("alice", "bob")),
        )
        self.assertIn(
            "collaborators=mismatch(list_not_collapsed)", str(outcome.error)
        )
        self.assertEqual(
            outcome.saved["options"]["collaborators"],
            {
                "requested": ["alice", "bob"],
                "applied": ["alice", "bob"],
                "status": MISMATCH,
                "reason": LIST_NOT_COLLAPSED,
            },
        )
        self.assertEqual(outcome.chips, ["alice", "bob"])
        self.assertEqual(outcome.share_clicks, 0)

    def test_chinese_done_label_collapses_the_panel(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice")], done_label="完成"
            ),
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        self.assertIsNone(outcome.error)
        self.assertEqual(outcome.done_clicks, 1)

    def test_obscured_composer_records_editor_obscured_without_control(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice")], obscured=True
            ),
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        self.assertIn("遮挡", str(outcome.error))
        record = outcome.saved["options"]["collaborators"]
        self.assertEqual(record["requested"], ["alice"])
        self.assertIsNone(record["applied"])
        self.assertEqual(record["status"], MISMATCH)
        self.assertEqual(record["reason"], "editor_obscured")
        self.assertIn("遮挡", record["detail"])
        self.assertEqual(outcome.entry_clicks, 0)
        self.assertEqual(outcome.share_clicks, 0)


class InstagramCollaboratorComposerScopeDomTests(unittest.TestCase):
    """C 层：资格提示只读包含协作者入口的创建弹窗，不读兄弟弹窗。"""

    def _resolve(self, html):
        async def scenario():
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    channel="chrome", headless=True
                )
                page = await browser.new_page()
                try:
                    await page.set_content(html)
                    control = CollaboratorsControl(page, image_count=0)
                    return await control.resolve()
                finally:
                    await browser.close()

        patches = list(timeout_patches())
        for item in patches:
            item.start()
        try:
            with patch.dict(os.environ, {"HUMANIZE": "0"}):
                return asyncio.run(scenario())
        finally:
            for item in patches:
                item.stop()

    def test_sibling_dialog_alert_does_not_make_the_composer_ineligible(self):
        html = collaborator_page_html(
            [("alice", "Alice")], render_chips=False
        ) + (
            '<div role="dialog" id="sibling-alert">'
            '<div role="alert">Cannot add collaborators to this account.'
            "</div></div>"
        )
        self.assertEqual(self._resolve(html), PRESENT)

    def test_unrelated_sibling_dialog_with_button_is_not_the_panel(self):
        # 最近的兄弟 dialog 只有一个普通按钮，没有候选行/Done。它不能被当成
        # 已打开的面板；真正面板从未打开时必须报 list_not_collapsed，而不是
        # 进入输入并因“无候选”报 no_candidates。
        html = collaborator_page_html(
            [("alice", "Alice")], panel_opens=False
        ) + (
            '<div role="dialog" id="unrelated" '
            'style="position: fixed; left: 120px; top: 120px;">'
            "<button>Discard draft</button></div>"
        )
        error, queries = self._set(html)
        self.assertIsNotNone(error)
        self.assertEqual(error.reason, LIST_NOT_COLLAPSED)
        self.assertIsNone(error.applied)
        self.assertIn("面板未能打开", str(error))
        self.assertFalse(queries)

    def _set(self, html):
        async def scenario():
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    channel="chrome", headless=True
                )
                page = await browser.new_page()
                try:
                    await page.set_content(html)
                    control = CollaboratorsControl(page, image_count=1)
                    error = None
                    try:
                        await control.set(("alice",))
                    except OptionMismatchError as raised:
                        error = raised
                    queries = await page.locator("body").get_attribute(
                        "data-queries"
                    )
                    return error, queries
                finally:
                    await browser.close()

        patches = list(timeout_patches())
        for item in patches:
            item.start()
        try:
            with patch.dict(os.environ, {"HUMANIZE": "0"}):
                return asyncio.run(scenario())
        finally:
            for item in patches:
                item.stop()


class InstagramReelsCollaboratorDomTests(unittest.TestCase):
    """C 层（Reels）：真实 Chrome 受控页；``image_count == 0`` 只读面板 checkbox。

    Reels 没有预览图 chip，已选 username 只在面板打开时可读。因此这里刻意
    让 checkbox 延迟生效，并用页面记录的“下一个查询开始时的已勾选集合”证明
    控件在继续下一个 username 前确实等待并回读了上一个 checkbox。
    """

    def _apply(
        self, html, *, options, readback_timeout_ms=None,
        expire_after_selection=None,
    ):
        holder: dict[str, object] = {}

        async def scenario():
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel="chrome", headless=True)
                page = await browser.new_page()
                try:
                    await page.set_content(html)
                    with tempfile.TemporaryDirectory() as folder:
                        video = Path(folder) / "video.mp4"
                        video.touch()
                        result_file = Path(folder) / "result.json"
                        app = InstagramUploader(
                            "unused.json",
                            title="caption",
                            video_file=video,
                            options=options,
                            result_file=result_file,
                        )
                        budget = app.start_publish_budget()
                        monitor = None
                        if expire_after_selection is not None:
                            monitor = asyncio.create_task(
                                expire_budget_after_username(
                                    page, budget, expire_after_selection
                                )
                            )
                        error = None
                        try:
                            await app._apply_options(page, budget=budget)
                        except Exception as wrapped:
                            error = wrapped
                        finally:
                            if monitor is not None:
                                monitor.cancel()
                                with contextlib.suppress(asyncio.CancelledError):
                                    await monitor
                        holder["app"] = app
                        holder["error"] = error
                        holder["saved"] = (
                            json.loads(result_file.read_text(encoding="utf-8"))
                            if result_file.exists()
                            else app.result
                        )
                        holder["share_clicks"] = int(
                            await page.locator("[data-share-clicks]")
                            .get_attribute("data-share-clicks") or 0
                        )
                        body = page.locator("body")

                        async def data(name):
                            return await body.get_attribute(name)

                        queries = await data("data-queries")
                        progress = await data("data-progress")
                        selected = await data("data-selected")
                        states = await data("data-checkbox-states")
                        holder["queries"] = json.loads(queries) if queries else []
                        holder["progress"] = (
                            json.loads(progress) if progress else []
                        )
                        holder["selected"] = (
                            json.loads(selected) if selected else []
                        )
                        holder["checkbox_states"] = (
                            json.loads(states) if states else []
                        )
                        holder["entry_clicks"] = int(
                            await data("data-entry-clicks") or 0
                        )
                        holder["row_clicks"] = int(
                            await data("data-row-clicks") or 0
                        )
                        holder["done_clicks"] = int(
                            await data("data-done-clicks") or 0
                        )
                        holder["clicked_username"] = await data(
                            "data-clicked-username"
                        )
                        holder["clicked_index"] = await data("data-clicked-index")
                        holder["focused_entry"] = await data(
                            "data-focused-entry"
                        )
                        holder["panel_hidden"] = bool(
                            await page.locator("#collab-panel").evaluate(
                                "el => el.hidden"
                            )
                        )
                        holder["chips"] = await page.evaluate(
                            """() => [...document.querySelectorAll('#chips > span')]
                                .map(node => {
                                  const name = node.querySelector('span');
                                  return name ? name.textContent : '';
                                }).filter(Boolean)"""
                        )
                        # Done 后重开面板（清空查询以显示全部行）观察勾选是否保留。
                        await page.evaluate(
                            """() => {
                              const entry = document.getElementById('collab-entry');
                              if (entry) {
                                entry.value = '';
                                entry.dispatchEvent(
                                  new Event('input', {bubbles: true}));
                              }
                              const panel = document.getElementById(
                                'collab-panel');
                              if (panel) panel.hidden = false;
                            }"""
                        )
                        holder["reopened_checked"] = await page.evaluate(
                            """() => [...document.querySelectorAll(
                                 '#collab-results [data-username]')]
                               .filter(row => row.querySelector(
                                 'input[type="checkbox"]').checked)
                               .map(row => row.dataset.username)"""
                        )
                finally:
                    await browser.close()

        patches = list(timeout_patches())
        if readback_timeout_ms is not None:
            patches.append(
                patch.object(
                    collaborators_control_module,
                    "READBACK_TIMEOUT_MS",
                    readback_timeout_ms,
                )
            )
        for item in patches:
            item.start()
        try:
            with patch.dict(os.environ, {"HUMANIZE": "0"}):
                asyncio.run(scenario())
        finally:
            for item in patches:
                item.stop()
        return SimpleNamespace(**holder)

    def test_checkbox_is_read_back_before_the_next_username_is_typed(self):
        html = collaborator_page_html(
            [("alice", "Alice"), ("bob", "Bob"), ("carol", "Carol")],
            render_chips=False,
            checkbox_delay_ms=700,
        )
        outcome = self._apply(
            html,
            options=InstagramPublishOptions(
                collaborators=("alice", "bob", "carol")
            ),
            readback_timeout_ms=2_000,
        )
        self.assertIsNone(outcome.error)
        expected = {
            "requested": ["alice", "bob", "carol"],
            "applied": ["alice", "bob", "carol"],
            "status": SET,
        }
        self.assertEqual(outcome.saved["options"]["collaborators"], expected)
        # 输入下一个 username 时，上一个 checkbox 必须已经勾选（逐个回读）。
        by_query = {
            item["query"]: item["checked"] for item in outcome.progress
        }
        self.assertEqual(by_query.get("alice"), [])
        self.assertEqual(by_query.get("bob"), ["alice"])
        self.assertEqual(by_query.get("carol"), ["alice", "bob"])
        self.assertEqual(
            outcome.checkbox_states,
            [
                {"username": "alice", "checked": True, "aria": "true"},
                {"username": "bob", "checked": True, "aria": "true"},
                {"username": "carol", "checked": True, "aria": "true"},
            ],
        )
        self.assertEqual(outcome.selected, ["alice", "bob", "carol"])
        self.assertEqual(outcome.row_clicks, 3)
        self.assertEqual(outcome.done_clicks, 1)
        self.assertEqual(outcome.share_clicks, 0)
        self.assertEqual(outcome.chips, [])

    def test_one_and_five_collaborators_complete(self):
        for count in (1, 5):
            with self.subTest(count=count):
                candidates = [
                    (f"user{index}", f"User {index}") for index in range(count)
                ]
                requested = tuple(
                    username for username, _display in candidates
                )
                outcome = self._apply(
                    collaborator_page_html(
                        candidates, render_chips=False
                    ),
                    options=InstagramPublishOptions(
                        collaborators=requested
                    ),
                )
                self.assertIsNone(outcome.error)
                self.assertEqual(
                    outcome.saved["options"]["collaborators"],
                    {
                        "requested": list(requested),
                        "applied": list(requested),
                        "status": SET,
                    },
                )
                self.assertEqual(outcome.selected, list(requested))
                self.assertEqual(outcome.row_clicks, count)
                self.assertEqual(outcome.done_clicks, 1)
                self.assertEqual(outcome.share_clicks, 0)
                self.assertEqual(outcome.chips, [])

    def test_english_chinese_and_broad_entry_fallbacks(self):
        for entry in ("en", "zh", "broad"):
            with self.subTest(entry=entry):
                outcome = self._apply(
                    collaborator_page_html(
                        [("alice", "Alice")],
                        entry=entry,
                        render_chips=False,
                    ),
                    options=InstagramPublishOptions(
                        collaborators=("alice",)
                    ),
                )
                self.assertIsNone(outcome.error)
                self.assertEqual(outcome.selected, ["alice"])
                self.assertEqual(outcome.saved["options"]["collaborators"]["applied"], ["alice"])

    def test_structural_entry_wins_over_an_english_placeholder_decoy(self):
        html = collaborator_page_html(
            [("alice", "Alice")], render_chips=False
        ).replace(
            '<input id="collab-entry" name="creation-collaborator-input"',
            '<input id="decoy-entry" placeholder="Add collaborators">'
            '<input id="collab-entry" name="creation-collaborator-input"',
            1,
        )
        outcome = self._apply(
            html,
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        self.assertIsNone(outcome.error)
        self.assertEqual(outcome.focused_entry, "collab-entry")
        self.assertEqual(outcome.selected, ["alice"])

    def test_entry_outside_the_composer_dialog_is_not_used(self):
        html = collaborator_page_html(
            [("alice", "Alice")], entry="missing", render_chips=False
        ).replace(
            "</div>\n<script>",
            '</div>\n<input name="creation-collaborator-input" '
            'placeholder="Add collaborators">\n<script>',
            1,
        )
        outcome = self._apply(
            html,
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        self.assertIn(
            "collaborators=unsupported(entry_missing)", str(outcome.error)
        )
        self.assertEqual(
            outcome.saved["options"]["collaborators"]["reason"], ENTRY_MISSING
        )
        self.assertEqual(outcome.entry_clicks, 0)
        self.assertEqual(outcome.share_clicks, 0)

    def test_hidden_duplicate_entry_dialog_does_not_shadow_the_composer(self):
        # 同页两个 role=dialog 都含协作者入口；第一个入口不可见。控件必须
        # 选中包含可见入口的创建弹窗，而不是 DOM 顺序第一个。
        duplicate = (
            '<div role="dialog" id="empty-compose">'
            '<input name="creation-collaborator-input" '
            'placeholder="Add collaborators" style="display: none">'
            "</div>"
        )
        html = collaborator_page_html(
            [("alice", "Alice")], render_chips=False
        ).replace('<div role="dialog" id="compose">', duplicate + '<div role="dialog" id="compose">', 1)
        outcome = self._apply(
            html,
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        self.assertIsNone(outcome.error)
        self.assertEqual(
            outcome.saved["options"]["collaborators"],
            {"requested": ["alice"], "applied": ["alice"], "status": SET},
        )
        self.assertEqual(outcome.entry_clicks, 0)
        self.assertEqual(outcome.row_clicks, 1)
        self.assertEqual(outcome.share_clicks, 0)

    def test_nike_never_selects_a_substring_candidate(self):
        outcome = self._apply(
            collaborator_page_html(
                [("_nikeza5", "nikeza"), ("nike", "Nike")],
                render_chips=False,
            ),
            options=InstagramPublishOptions(collaborators=("nike",)),
        )
        self.assertIsNone(outcome.error)
        self.assertEqual(
            outcome.saved["options"]["collaborators"]["applied"], ["nike"]
        )
        self.assertEqual(outcome.selected, ["nike"])
        self.assertEqual(outcome.clicked_username, "nike")
        self.assertEqual(outcome.clicked_index, "1")
        self.assertEqual(outcome.row_clicks, 1)
        self.assertEqual(outcome.share_clicks, 0)

    def test_duplicate_identical_rows_choose_the_first(self):
        outcome = self._apply(
            collaborator_page_html(
                [("nike", "Nike One"), ("nike", "Nike Two")],
                render_chips=False,
            ),
            options=InstagramPublishOptions(collaborators=("nike",)),
        )
        self.assertIsNone(outcome.error)
        self.assertEqual(outcome.clicked_index, "0")
        self.assertEqual(outcome.row_clicks, 1)
        self.assertEqual(outcome.selected, ["nike"])
        self.assertEqual(
            outcome.saved["options"]["collaborators"]["applied"], ["nike"]
        )
        self.assertEqual(outcome.share_clicks, 0)

    def test_already_selected_checkbox_is_not_clicked_again(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice"), ("bob", "Bob")],
                preselect=("alice",),
                render_chips=False,
            ),
            options=InstagramPublishOptions(
                collaborators=("alice", "bob")
            ),
        )
        self.assertIsNone(outcome.error)
        self.assertEqual(outcome.selected, ["alice", "bob"])
        self.assertEqual(outcome.row_clicks, 1)
        self.assertEqual(outcome.clicked_username, "bob")
        by_query = {
            item["query"]: item["checked"] for item in outcome.progress
        }
        self.assertEqual(by_query.get("bob"), ["alice"])
        self.assertEqual(outcome.share_clicks, 0)

    def test_done_closes_the_panel_and_preserves_selection(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice"), ("bob", "Bob")],
                render_chips=False,
            ),
            options=InstagramPublishOptions(
                collaborators=("alice", "bob")
            ),
        )
        self.assertIsNone(outcome.error)
        self.assertTrue(outcome.panel_hidden)
        self.assertEqual(outcome.done_clicks, 1)
        self.assertEqual(outcome.selected, ["alice", "bob"])
        self.assertEqual(outcome.reopened_checked, ["alice", "bob"])
        self.assertEqual(outcome.share_clicks, 0)

    def test_no_candidates_stops_before_later_usernames(self):
        outcome = self._apply(
            collaborator_page_html([], render_chips=False),
            options=InstagramPublishOptions(
                collaborators=("alice", "bob")
            ),
        )
        self.assertIn(
            "collaborators=mismatch(no_candidates)", str(outcome.error)
        )
        self.assertEqual(
            outcome.saved["options"]["collaborators"],
            {
                "requested": ["alice", "bob"],
                "applied": [],
                "status": MISMATCH,
                "reason": NO_CANDIDATES,
            },
        )
        self.assertIn("alice", outcome.queries)
        self.assertNotIn("bob", outcome.queries)
        self.assertEqual(outcome.share_clicks, 0)

    def test_no_same_username_keeps_the_confirmed_prefix(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice"), ("_bobby", "Bobby")],
                render_chips=False,
            ),
            options=InstagramPublishOptions(
                collaborators=("alice", "bob", "carol")
            ),
        )
        self.assertIn(
            "collaborators=mismatch(no_same_username_candidate)",
            str(outcome.error),
        )
        self.assertEqual(
            outcome.saved["options"]["collaborators"],
            {
                "requested": ["alice", "bob", "carol"],
                "applied": ["alice"],
                "status": MISMATCH,
                "reason": NO_SAME_USERNAME,
            },
        )
        self.assertEqual(outcome.selected, ["alice"])
        self.assertIn("bob", outcome.queries)
        self.assertNotIn("carol", outcome.queries)
        self.assertEqual(outcome.share_clicks, 0)

    def test_click_without_selection_is_selection_failed(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice")],
                row_click="ignore",
                render_chips=False,
            ),
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        self.assertIn(
            "collaborators=mismatch(selection_failed)", str(outcome.error)
        )
        self.assertEqual(
            outcome.saved["options"]["collaborators"],
            {
                "requested": ["alice"],
                "applied": [],
                "status": MISMATCH,
                "reason": SELECTION_FAILED,
            },
        )
        self.assertEqual(outcome.row_clicks, 1)
        self.assertEqual(outcome.selected, [])
        self.assertEqual(outcome.done_clicks, 0)
        self.assertEqual(outcome.share_clicks, 0)

    def test_first_click_failure_stops_before_the_next_username(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice"), ("bob", "Bob"), ("carol", "Carol")],
                row_click="ignore",
                render_chips=False,
            ),
            options=InstagramPublishOptions(
                collaborators=("alice", "bob", "carol")
            ),
        )
        self.assertIn(
            "collaborators=mismatch(selection_failed)", str(outcome.error)
        )
        self.assertEqual(
            outcome.saved["options"]["collaborators"]["applied"], []
        )
        self.assertIn("alice", outcome.queries)
        self.assertNotIn("bob", outcome.queries)
        self.assertNotIn("carol", outcome.queries)
        self.assertEqual(outcome.row_clicks, 1)
        self.assertEqual(outcome.share_clicks, 0)

    def test_unreadable_checkbox_readback_is_final_mismatch(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice")],
                row_click="detach-entry",
                render_chips=False,
            ),
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        self.assertIn(
            "collaborators=mismatch(final_mismatch)", str(outcome.error)
        )
        record = outcome.saved["options"]["collaborators"]
        self.assertIsNone(record["applied"])
        self.assertEqual(record["reason"], FINAL_MISMATCH)
        self.assertEqual(outcome.share_clicks, 0)

    def test_missing_done_is_list_not_collapsed_not_entry_missing(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice")],
                done_label="Fertig",
                render_chips=False,
            ),
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        message = str(outcome.error)
        self.assertIn("collaborators=mismatch(list_not_collapsed)", message)
        self.assertNotIn("entry_missing", message)
        record = outcome.saved["options"]["collaborators"]
        self.assertEqual(record["applied"], ["alice"])
        self.assertEqual(record["reason"], LIST_NOT_COLLAPSED)
        self.assertEqual(outcome.selected, ["alice"])
        self.assertEqual(outcome.share_clicks, 0)

    def test_mid_list_budget_exhaustion_keeps_the_confirmed_prefix(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice"), ("bob", "Bob"), ("carol", "Carol")],
                render_chips=False,
                checkbox_delay_ms=250,
                confirm_delay_ms=400,
            ),
            options=InstagramPublishOptions(
                collaborators=("alice", "bob", "carol")
            ),
            readback_timeout_ms=2_000,
            expire_after_selection="alice",
        )
        self.assertIsNotNone(outcome.error)
        self.assertIn("15 分钟", str(outcome.error))
        self.assertNotIsInstance(outcome.error, PublishResultUnknownError)
        record = outcome.saved["options"]["collaborators"]
        self.assertEqual(record["requested"], ["alice", "bob", "carol"])
        self.assertEqual(record["applied"], ["alice"])
        self.assertEqual(record["status"], MISMATCH)
        self.assertNotIn("reason", record)
        self.assertIn("alice", outcome.queries)
        self.assertNotIn("bob", outcome.queries)
        self.assertNotIn("carol", outcome.queries)
        self.assertEqual(outcome.selected, ["alice"])
        self.assertEqual(outcome.share_clicks, 0)

    def test_done_that_does_not_collapse_is_list_not_collapsed(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice"), ("bob", "Bob")],
                done_collapses=False,
                render_chips=False,
            ),
            options=InstagramPublishOptions(
                collaborators=("alice", "bob")
            ),
        )
        self.assertIn(
            "collaborators=mismatch(list_not_collapsed)", str(outcome.error)
        )
        self.assertEqual(
            outcome.saved["options"]["collaborators"],
            {
                "requested": ["alice", "bob"],
                "applied": ["alice", "bob"],
                "status": MISMATCH,
                "reason": LIST_NOT_COLLAPSED,
            },
        )
        self.assertEqual(outcome.done_clicks, 1)
        self.assertFalse(outcome.panel_hidden)
        self.assertEqual(outcome.share_clicks, 0)

    def test_chinese_done_label_collapses_the_panel(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice")],
                done_label="完成",
                render_chips=False,
            ),
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        self.assertIsNone(outcome.error)
        self.assertEqual(outcome.done_clicks, 1)
        self.assertTrue(outcome.panel_hidden)

    def test_disabled_entry_is_control_disabled(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice")],
                entry="disabled",
                render_chips=False,
            ),
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        self.assertIn(
            "collaborators=unsupported(control_disabled)", str(outcome.error)
        )
        self.assertEqual(
            outcome.saved["options"]["collaborators"]["reason"],
            CONTROL_DISABLED,
        )
        self.assertEqual(outcome.entry_clicks, 0)
        self.assertEqual(outcome.share_clicks, 0)

    def test_explicit_account_restriction_is_account_ineligible(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice")],
                restriction=(
                    '<div role="alert">'
                    "Cannot add collaborators to this account."
                    "</div>"
                ),
                render_chips=False,
            ),
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        self.assertIn(
            "collaborators=unsupported(account_ineligible)", str(outcome.error)
        )
        record = outcome.saved["options"]["collaborators"]
        self.assertEqual(record["reason"], ACCOUNT_INELIGIBLE)
        self.assertIn("Cannot add collaborators", record["detail"])
        # 入口仍可聚焦，但页面明确说明账号不合格：不得尝试输入。
        self.assertEqual(outcome.entry_clicks, 0)
        self.assertEqual(outcome.share_clicks, 0)

    def test_obscured_composer_records_editor_obscured_without_control(self):
        outcome = self._apply(
            collaborator_page_html(
                [("alice", "Alice")],
                obscured=True,
                render_chips=False,
            ),
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        self.assertIn("遮挡", str(outcome.error))
        record = outcome.saved["options"]["collaborators"]
        self.assertEqual(record["status"], MISMATCH)
        self.assertEqual(record["reason"], EDITOR_OBSCURED)
        self.assertIn("遮挡", record["detail"])
        self.assertEqual(outcome.entry_clicks, 0)
        self.assertEqual(outcome.share_clicks, 0)


class InstagramCollaboratorSiblingPanelDomTests(unittest.TestCase):
    """C 层（真机结构）：协作者面板是创建弹窗之外的兄弟 ``role=dialog``。

    2026-11-24 真机证据：入口在创建弹窗内，候选行与 Done 在独立 portal 的
    兄弟 dialog 里，按钮/username/显示名/checkbox 结构见 fixture。``_apply``
    与既有受控 DOM 用例同构，只把页面观察面扩展到兄弟面板。
    """

    def _apply(
        self,
        html,
        *,
        options,
        image_count=1,
        readback_timeout_ms=None,
    ):
        holder: dict[str, object] = {}

        async def scenario():
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel="chrome", headless=True)
                page = await browser.new_page()
                try:
                    await page.set_content(html)
                    with tempfile.TemporaryDirectory() as folder:
                        images = [
                            str(Path(folder) / f"image-{index}.png")
                            for index in range(image_count)
                        ]
                        video = (
                            None
                            if image_count
                            else Path(folder) / "video.mp4"
                        )
                        if video is not None:
                            video.touch()
                        result_file = Path(folder) / "result.json"
                        app = InstagramUploader(
                            "unused.json",
                            title="caption",
                            image_files=images,
                            video_file=video,
                            options=options,
                            result_file=result_file,
                        )
                        budget = app.start_publish_budget()
                        error = None
                        try:
                            await app._apply_options(page, budget=budget)
                        except Exception as wrapped:
                            error = wrapped
                        holder["app"] = app
                        holder["error"] = error
                        holder["saved"] = (
                            json.loads(result_file.read_text(encoding="utf-8"))
                            if result_file.exists()
                            else app.result
                        )
                        holder["share_clicks"] = int(
                            await page.locator("[data-share-clicks]")
                            .get_attribute("data-share-clicks") or 0
                        )
                        holder["chips"] = await page.evaluate(
                            """() => [...document.querySelectorAll('#chips > span')]
                                .map(node => {
                                  const name = node.querySelector('span');
                                  return name ? name.textContent : '';
                                }).filter(Boolean)"""
                        )
                        body = page.locator("body")

                        async def data(name):
                            return await body.get_attribute(name)

                        queries = await data("data-queries")
                        progress = await data("data-progress")
                        selected = await data("data-selected")
                        states = await data("data-checkbox-states")
                        holder["queries"] = (
                            json.loads(queries) if queries else []
                        )
                        holder["progress"] = (
                            json.loads(progress) if progress else []
                        )
                        holder["selected"] = (
                            json.loads(selected) if selected else []
                        )
                        holder["checkbox_states"] = (
                            json.loads(states) if states else []
                        )
                        holder["entry_clicks"] = int(
                            await data("data-entry-clicks") or 0
                        )
                        holder["row_clicks"] = int(
                            await data("data-row-clicks") or 0
                        )
                        holder["done_clicks"] = int(
                            await data("data-done-clicks") or 0
                        )
                        holder["decoy_row_clicks"] = int(
                            await data("data-decoy-row-clicks") or 0
                        )
                        holder["clicked_username"] = await data(
                            "data-clicked-username"
                        )
                        holder["clicked_index"] = await data("data-clicked-index")
                        holder["panel_hidden"] = bool(
                            await page.locator("#collab-panel").evaluate(
                                "el => el.hidden"
                            )
                        )
                        # Done 收起兄弟面板后清空查询并重开，确认勾选仍在。
                        await page.evaluate(
                            """() => {
                              const entry = document.getElementById('collab-entry');
                              if (entry) {
                                entry.value = '';
                                entry.dispatchEvent(
                                  new Event('input', {bubbles: true}));
                              }
                              const panel = document.getElementById(
                                'collab-panel');
                              if (panel) panel.hidden = false;
                            }"""
                        )
                        holder["reopened_checked"] = await page.evaluate(
                            """() => [...document.querySelectorAll(
                                 '#collab-results [data-username]')]
                               .filter(row => row.querySelector(
                                 'input[type="checkbox"]').checked)
                               .map(row => row.dataset.username)"""
                        )
                finally:
                    await browser.close()

        patches = list(timeout_patches())
        if readback_timeout_ms is not None:
            patches.append(
                patch.object(
                    collaborators_control_module,
                    "READBACK_TIMEOUT_MS",
                    readback_timeout_ms,
                )
            )
        for item in patches:
            item.start()
        try:
            with patch.dict(os.environ, {"HUMANIZE": "0"}):
                asyncio.run(scenario())
        finally:
            for item in patches:
                item.stop()
        return SimpleNamespace(**holder)

    def test_note_sibling_panel_exact_match_chip_readback_and_done(self):
        html = sibling_panel_page_html(
            [
                ("_nikeza5", "nikeza"),
                ("nike", "Nike"),
                ("natgeo", "National Geographic"),
            ]
        )
        outcome = self._apply(
            html,
            options=InstagramPublishOptions(collaborators=("nike",)),
        )
        self.assertIsNone(outcome.error)
        self.assertEqual(
            outcome.saved["options"]["collaborators"],
            {"requested": ["nike"], "applied": ["nike"], "status": SET},
        )
        self.assertEqual(outcome.chips, ["nike"])
        self.assertEqual(outcome.row_clicks, 1)
        self.assertEqual(outcome.clicked_username, "nike")
        self.assertEqual(outcome.clicked_index, "1")
        self.assertEqual(outcome.done_clicks, 1)
        self.assertTrue(outcome.panel_hidden)
        self.assertEqual(outcome.selected, ["nike"])
        self.assertEqual(outcome.share_clicks, 0)

    def test_note_sibling_panel_reads_composer_chips_in_request_order(self):
        outcome = self._apply(
            sibling_panel_page_html(
                [
                    ("alice", "Alice A"),
                    ("bob", "Bob B"),
                    ("carol", "Carol C"),
                ]
            ),
            options=InstagramPublishOptions(
                collaborators=("alice", "carol")
            ),
        )
        self.assertIsNone(outcome.error)
        self.assertEqual(
            outcome.saved["options"]["collaborators"],
            {
                "requested": ["alice", "carol"],
                "applied": ["alice", "carol"],
                "status": SET,
            },
        )
        self.assertEqual(outcome.chips, ["alice", "carol"])
        self.assertEqual(
            [query for query in outcome.queries if query], ["alice", "carol"]
        )
        self.assertEqual(outcome.row_clicks, 2)
        self.assertEqual(outcome.clicked_username, "carol")
        self.assertTrue(outcome.panel_hidden)
        self.assertEqual(outcome.share_clicks, 0)

    def test_reels_sibling_panel_checkbox_is_read_back_before_next_query(self):
        outcome = self._apply(
            sibling_panel_page_html(
                [
                    ("alice", "Alice"),
                    ("bob", "Bob"),
                    ("carol", "Carol"),
                ],
                render_chips=False,
                checkbox_delay_ms=700,
            ),
            image_count=0,
            options=InstagramPublishOptions(
                collaborators=("alice", "bob", "carol")
            ),
            readback_timeout_ms=2_000,
        )
        self.assertIsNone(outcome.error)
        self.assertEqual(
            outcome.saved["options"]["collaborators"],
            {
                "requested": ["alice", "bob", "carol"],
                "applied": ["alice", "bob", "carol"],
                "status": SET,
            },
        )
        by_query = {
            item["query"]: item["checked"] for item in outcome.progress
        }
        self.assertEqual(by_query.get("alice"), [])
        self.assertEqual(by_query.get("bob"), ["alice"])
        self.assertEqual(by_query.get("carol"), ["alice", "bob"])
        self.assertEqual(
            outcome.checkbox_states,
            [
                {"username": "alice", "checked": True, "aria": "true"},
                {"username": "bob", "checked": True, "aria": "true"},
                {"username": "carol", "checked": True, "aria": "true"},
            ],
        )
        self.assertEqual(outcome.selected, ["alice", "bob", "carol"])
        self.assertEqual(outcome.row_clicks, 3)
        self.assertEqual(outcome.done_clicks, 1)
        self.assertTrue(outcome.panel_hidden)
        self.assertEqual(
            outcome.reopened_checked, ["alice", "bob", "carol"]
        )
        self.assertEqual(outcome.chips, [])
        self.assertEqual(outcome.share_clicks, 0)

    def test_switch_and_far_decoy_dialogs_are_not_the_collaborator_panel(self):
        outcome = self._apply(
            sibling_panel_page_html(
                [("alice", "Alice"), ("bob", "Bob")], decoy=True
            ),
            options=InstagramPublishOptions(collaborators=("alice", "bob")),
        )
        self.assertIsNone(outcome.error)
        self.assertEqual(
            outcome.saved["options"]["collaborators"]["applied"],
            ["alice", "bob"],
        )
        self.assertEqual(outcome.chips, ["alice", "bob"])
        self.assertEqual(outcome.row_clicks, 2)
        self.assertEqual(outcome.clicked_username, "bob")
        self.assertEqual(outcome.decoy_row_clicks, 0)
        self.assertEqual(outcome.selected, ["alice", "bob"])
        self.assertEqual(outcome.done_clicks, 1)
        self.assertTrue(outcome.panel_hidden)
        self.assertEqual(outcome.share_clicks, 0)

    def test_sibling_panel_done_that_does_not_collapse_is_list_not_collapsed(self):
        outcome = self._apply(
            sibling_panel_page_html(
                [("alice", "Alice"), ("bob", "Bob")], done_collapses=False
            ),
            options=InstagramPublishOptions(collaborators=("alice", "bob")),
        )
        self.assertIn(
            "collaborators=mismatch(list_not_collapsed)", str(outcome.error)
        )
        self.assertEqual(
            outcome.saved["options"]["collaborators"],
            {
                "requested": ["alice", "bob"],
                "applied": ["alice", "bob"],
                "status": MISMATCH,
                "reason": LIST_NOT_COLLAPSED,
            },
        )
        self.assertEqual(outcome.done_clicks, 1)
        self.assertFalse(outcome.panel_hidden)
        self.assertEqual(outcome.chips, ["alice", "bob"])
        self.assertEqual(outcome.share_clicks, 0)

    def test_sibling_panel_click_without_selection_is_selection_failed(self):
        outcome = self._apply(
            sibling_panel_page_html(
                [("alice", "Alice")], row_click="ignore"
            ),
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        self.assertIn(
            "collaborators=mismatch(selection_failed)", str(outcome.error)
        )
        self.assertEqual(
            outcome.saved["options"]["collaborators"],
            {
                "requested": ["alice"],
                "applied": [],
                "status": MISMATCH,
                "reason": SELECTION_FAILED,
            },
        )
        self.assertEqual(outcome.row_clicks, 1)
        self.assertEqual(outcome.done_clicks, 0)
        self.assertEqual(outcome.share_clicks, 0)

    def test_sibling_panel_unreadable_readback_is_final_mismatch(self):
        outcome = self._apply(
            sibling_panel_page_html(
                [("alice", "Alice")], row_click="detach-entry"
            ),
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        self.assertIn(
            "collaborators=mismatch(final_mismatch)", str(outcome.error)
        )
        record = outcome.saved["options"]["collaborators"]
        self.assertIsNone(record["applied"])
        self.assertEqual(record["reason"], FINAL_MISMATCH)
        self.assertEqual(outcome.share_clicks, 0)


