# -*- coding: utf-8 -*-
"""XHS explicit content-type declaration: read back the selected label (ticket 15).

The controlled page models the two facts the real page shows after the
declaration menu collapses:

* the selected label is rendered in the declaration wrapper's
  ``.d-select-description``; the placeholder node itself is cleared;
* the option menu is hidden.

Every failure must stop before the publish step with the requested value, the
observed value (or ``未读到``) and a reason.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

import uploader.xiaohongshu_uploader.main as xhs_main
from tests.fakes_xhs_dom import FakeLocator, RecordingPage
from tests.test_xhs_metadata import VISIBLE_FACTS, _original_page

AI_LABEL = "笔记含AI合成内容"
MARKETING_LABEL = "内容包含营销广告"
TRIGGER_SELECTOR = ".publish-container [tabindex=\"1\"]"
FALLBACK_KEY = "text:添加内容类型声明:exact"
OPTION_SELECTOR = xhs_main.XHS_DECLARATION_OPTION_SELECTOR


def _video_app(**overrides):
    values = {
        "title": "标题",
        "file_path": "demo.mp4",
        "tags": [],
        "publish_date": 0,
        "account_file": "account.json",
        "no_publish": True,
    }
    values.update(overrides)
    return xhs_main.XiaoHongShuVideo(**values)


def _note_app(**overrides):
    values = {
        "image_paths": ["a.png"],
        "note": "",
        "tags": [],
        "publish_date": 0,
        "account_file": "account.json",
        "title": "标题",
        "no_publish": True,
    }
    values.update(overrides)
    return xhs_main.XiaoHongShuNote(**values)


def _declaration_selectors(
    *,
    entry: bool = True,
    final_text: str = AI_LABEL,
    menu_error: BaseException | None = None,
) -> tuple[dict[str, FakeLocator], FakeLocator, FakeLocator]:
    menu = FakeLocator("declaration-menu", wait_error=menu_error)
    option = FakeLocator(
        "declaration-option",
        computed_style=dict(VISIBLE_FACTS),
        children={xhs_main.XHS_DECLARATION_MENU_XPATH: menu},
    )
    trigger = FakeLocator(
        "declaration-trigger",
        count=1 if entry else 0,
        computed_style=dict(VISIBLE_FACTS),
        text="添加内容类型声明",
    )
    wrapper = FakeLocator(
        "declaration-wrapper",
        count=1 if entry else 0,
        children={
            ".d-select-description": FakeLocator(
                "declaration-description", text=final_text
            )
        },
    )
    selectors = {
        TRIGGER_SELECTOR: trigger,
        xhs_main.XHS_DECLARATION_WRAPPER_SELECTOR: wrapper,
        FALLBACK_KEY: FakeLocator("declaration-text-fallback", count=0),
        OPTION_SELECTOR: option,
    }
    return selectors, trigger, option


def _page(*, entry: bool = True, final_text: str = AI_LABEL, menu_error=None):
    selectors, trigger, option = _declaration_selectors(
        entry=entry, final_text=final_text, menu_error=menu_error
    )
    return RecordingPage(selectors=selectors), trigger, option


def _fast_missing_anchor():
    """Collapse the 5 s anchor window to one attempt for a missing entry."""
    original = xhs_main.wait_resolved

    async def fast(*args, **kwargs):
        kwargs["timeout_ms"] = 0
        return await original(*args, **kwargs)

    return patch.object(xhs_main, "wait_resolved", fast)


class XhsAiDeclarationReadbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(patch.dict(os.environ, {"HUMANIZE": "0"}))

    async def apply(self, app, page):
        with patch.object(app, "_settle", AsyncMock()):
            return await app.apply_declarations(page)

    async def test_ai_success_reads_back_the_collapsed_selected_label(self):
        for app in (_video_app(content_type="ai"), _note_app(content_type="ai")):
            with self.subTest(post_type=type(app).__name__):
                page, _trigger, option = _page()
                await self.apply(app, page)

                self.assertEqual(option.click_count, 1)
                self.assertEqual(
                    app.declaration_report,
                    {
                        "requested": "ai",
                        "requested_label": AI_LABEL,
                        "observed": AI_LABEL,
                        "status": "set",
                    },
                )
                menu = option.locator(xhs_main.XHS_DECLARATION_MENU_XPATH)
                self.assertEqual(menu.wait_calls[-1].kwargs["state"], "hidden")

    async def test_missing_declaration_entry_reports_request_and_reason(self):
        page, _trigger, _option = _page(entry=False)
        app = _video_app(content_type="ai")
        with _fast_missing_anchor(), self.assertRaises(RuntimeError) as ctx:
            await self.apply(app, page)
        message = str(ctx.exception)
        self.assertIn("请求=ai", message)
        self.assertIn(AI_LABEL, message)
        self.assertIn("终值=未读到", message)
        self.assertIn("未找到内容类型声明入口", message)
        self.assertIn("尚未点击发布", message)

    async def test_empty_final_value_stops_before_publish(self):
        page, _trigger, option = _page(final_text="")
        app = _note_app(content_type="ai")
        with self.assertRaises(RuntimeError) as ctx:
            await self.apply(app, page)
        message = str(ctx.exception)
        self.assertIn("请求=ai", message)
        self.assertIn("终值=（空）", message)
        self.assertIn("选中的内容类型为空", message)
        self.assertIn("尚未点击发布", message)
        self.assertEqual(option.click_count, 1)

    async def test_different_selected_value_is_reported_and_stops(self):
        page, _trigger, _option = _page(final_text=MARKETING_LABEL)
        app = _video_app(content_type="ai")
        with self.assertRaises(RuntimeError) as ctx:
            await self.apply(app, page)
        message = str(ctx.exception)
        self.assertIn("请求=ai", message)
        self.assertIn(f"终值={MARKETING_LABEL}", message)
        self.assertIn("与请求不符", message)
        self.assertIn("尚未点击发布", message)

    async def test_menu_that_does_not_collapse_stops_before_publish(self):
        page, _trigger, _option = _page(menu_error=TimeoutError("menu still open"))
        app = _video_app(content_type="ai")
        with self.assertRaises(RuntimeError) as ctx:
            await self.apply(app, page)
        self.assertIn("声明菜单未收起", str(ctx.exception))
        self.assertIn("尚未点击发布", str(ctx.exception))

    async def test_omitted_content_type_never_touches_the_declaration_control(self):
        for app in (_video_app(), _note_app()):
            with self.subTest(post_type=type(app).__name__):
                page = RecordingPage(selectors={})
                await self.apply(app, page)
                self.assertIsNone(app.declaration_report)

    async def test_original_and_ai_are_combinable(self):
        page = _original_page(checked=False)
        selectors, _trigger, option = _declaration_selectors()
        page._selectors.update(selectors)
        app = _video_app(original_declaration=True, content_type="ai")
        await self.apply(app, page)

        switch = page.locator(xhs_main.XHS_ORIGINAL_SWITCH_CANDIDATES[0].selector)
        self.assertEqual(switch.click_count, 1)
        self.assertEqual(option.click_count, 1)
        self.assertEqual(
            app.declaration_report["observed"], AI_LABEL
        )


if __name__ == "__main__":
    unittest.main()
