# -*- coding: utf-8 -*-
"""Video cover flow: hover the preview first, then click the revealed entry.

Real device 2026-11-12: ``.cover-edit-entry`` is 0x0 until the first-frame
preview block is hovered; clicking the page title ``设置封面`` does nothing.
This test pins the ordering (hover -> entry -> modal -> upload -> 完成) without
a browser.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

import uploader.xiaohongshu_uploader.main as xhs_main


class _Locator:
    def __init__(self, name: str, events: list) -> None:
        self.name = name
        self.events = events

    async def scroll_into_view_if_needed(self, **kwargs) -> None:
        self.events.append(("scroll", self.name))

    async def wait_for(self, **kwargs) -> None:
        self.events.append(("wait_for", self.name, kwargs.get("state")))

    async def set_input_files(self, files) -> None:
        self.events.append(("files", self.name, files))


class _Humanizer:
    def __init__(self, events: list) -> None:
        self.events = events

    async def hover(self, locator) -> None:
        self.events.append(("hover", getattr(locator, "name", "?")))

    async def click(self, locator, **kwargs) -> None:
        self.events.append(("click", getattr(locator, "name", "?")))

    async def between_scroll(self) -> None:
        self.events.append(("between_scroll",))


class _Resolved:
    def __init__(self, locator, selector: str) -> None:
        self.locator = locator
        self.selector = selector
        self.kind = "structure"
        self.role = "visible"


class VideoCoverFlowTests(unittest.TestCase):
    def test_preview_is_hovered_before_the_cover_entry_is_clicked(self):
        events: list = []
        locators = {
            "封面预览区": _Locator("preview", events),
            "封面入口": _Locator("entry", events),
            "封面弹窗": _Locator("modal", events),
            "封面-上传 tab": _Locator("tab", events),
            "封面文件输入": _Locator("file-input", events),
            "封面确定": _Locator("confirm", events),
        }

        async def fake_resolve(page, step, candidates, **kwargs):
            return _Resolved(locators[step], str(step))

        app = xhs_main.XiaoHongShuVideo(
            title="封面",
            file_path="demo.mp4",
            tags=[],
            publish_date=0,
            account_file="account.json",
            thumbnail_path="cover.png",
        )
        app._settle = lambda page, ms: asyncio.sleep(0)
        app._wait_ms = lambda ms: 1
        app._humanizer = lambda page: _Humanizer(events)

        async def no_overlays(*args, **kwargs):
            return None

        with (
            patch.object(xhs_main, "_resolve_anchor", fake_resolve),
            patch.object(xhs_main, "_clear_known_overlays", no_overlays),
        ):
            asyncio.run(
                app.set_thumbnail(object(), "cover.png", humanizer=_Humanizer(events))
            )

        kinds = [event[0] for event in events]
        self.assertIn("hover", kinds)
        hover_index = kinds.index("hover")
        entry_click = next(
            index
            for index, event in enumerate(events)
            if event[0] == "click" and event[1] == "entry"
        )
        self.assertLess(hover_index, entry_click)
        self.assertIn(
            ("files", "file-input", "cover.png"), events
        )
        self.assertIn(("click", "confirm"), events)


if __name__ == "__main__":
    unittest.main()
