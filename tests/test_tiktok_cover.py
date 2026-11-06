# -*- coding: utf-8 -*-
"""TikTok video cover step (ticket 14).

All tests are in-memory: no browser, no network.  The fakes model just enough
of the Playwright locator surface for ``TiktokVideo.apply_cover`` — a query
returns the registered nodes, and actions are recorded so the test can assert
which candidate actually won.
"""

from __future__ import annotations

import asyncio
import re
import unittest

from uploader.tk_uploader.main_chrome import (
    COVER_EDITOR_SCOPE_SELECTOR,
    TiktokVideo,
)

THUMBNAIL = "/tmp/cover.png"
PAGE_URL = "https://www.tiktok.com/tiktokstudio/upload?lang=en"

EDIT_COVER_TEXT = 'get_by_text("Edit cover", exact=True)'
EDIT_COVER_ROLE = 'get_by_role("button", name="Edit cover")'
UPLOAD_TAB = 'get_by_text("Upload cover", exact=True)'
FILE_ARIA = '[aria-label="Upload cover image"] input[type="file"]'
FILE_ACCEPT = 'input[type="file"][accept*="image/jpeg"]'
PREVIEW = '[aria-label="Uploaded cover image"]'
SAVE = 'get_by_role("button", name=re.compile(r"^(Save|Confirm)$"))'


def _name_matches(expected, label: str) -> bool:
    if expected is None:
        return True
    if hasattr(expected, "search"):
        return bool(expected.search(label))
    return expected == label


class FakeQuery:
    """Result of a locator query; only ``count``/``first`` are exercised."""

    def __init__(self, matches, parent, label: str) -> None:
        self.matches = matches
        self.parent = parent
        self.label = label

    async def count(self) -> int:
        return len(self.matches)

    @property
    def first(self):
        if not self.matches:
            raise AssertionError(f"first accessed on empty query: {self.label}")
        return self.matches[0]


class FakeNode:
    """A single locator node and the subtree it can query."""

    def __init__(
        self,
        name: str,
        *,
        recorder: list,
        count: int = 1,
        enabled: bool = True,
        visible: bool = True,
    ) -> None:
        self.name = name
        self.recorder = recorder
        self.count_value = count
        self.enabled = enabled
        self.visible = visible
        self._texts: list[tuple[str, bool, FakeNode]] = []
        self._roles: list[tuple[str, str, FakeNode]] = []
        self._css: dict[str, FakeNode] = {}

    # -- registration ---------------------------------------------------
    def add_text(self, text, *, exact=True, name=None, count=1, enabled=True):
        node = FakeNode(
            name or f"text:{text}",
            recorder=self.recorder,
            count=count,
            enabled=enabled,
        )
        self._texts.append((text, bool(exact), node))
        return node

    def add_role(self, role, label, *, name=None, count=1, enabled=True):
        node = FakeNode(
            name or f"role:{role}[{label}]",
            recorder=self.recorder,
            count=count,
            enabled=enabled,
        )
        self._roles.append((role, label, node))
        return node

    def add_css(self, selector, *, name=None, count=1, enabled=True):
        node = FakeNode(
            name or f"css:{selector}",
            recorder=self.recorder,
            count=count,
            enabled=enabled,
        )
        self._css[selector] = node
        return node

    def remove_css(self, selector) -> None:
        self._css.pop(selector, None)

    # -- locator surface -------------------------------------------------
    async def count(self) -> int:
        return self.count_value

    @property
    def first(self):
        return self

    def get_by_text(self, text, exact=False):
        self.recorder.append(("query", "text", text))
        matches = [
            node
            for route_text, route_exact, node in self._texts
            if route_text == text
            and route_exact == bool(exact)
            and node.count_value > 0
        ]
        return FakeQuery(matches, self, f"text:{text}")

    def get_by_role(self, role, name=None):
        self.recorder.append(("query", "role", role, repr(name)))
        matches = [
            node
            for route_role, route_label, node in self._roles
            if route_role == role
            and _name_matches(name, route_label)
            and node.count_value > 0
        ]
        return FakeQuery(matches, self, f"role:{role}")

    def locator(self, selector):
        self.recorder.append(("query", "css", selector))
        node = self._css.get(selector)
        return FakeQuery(
            [node] if node is not None and node.count_value > 0 else [],
            self,
            selector,
        )

    # -- actions ---------------------------------------------------------
    async def click(self, **kwargs):
        self.recorder.append(("click", self.name))

    async def set_input_files(self, files, **kwargs):
        self.recorder.append(("set_input_files", self.name, files))

    async def is_enabled(self) -> bool:
        return self.enabled

    async def wait_for(self, **kwargs):
        self.recorder.append(("wait_for", self.name, kwargs))
        if not self.visible:
            raise TimeoutError(f"{self.name} never became visible")


class FakePage:
    def __init__(self, url: str = PAGE_URL) -> None:
        self.url = url
        self.events: list = []
        self.wait_timeouts: list[int] = []

    async def wait_for_timeout(self, ms: int) -> None:
        self.wait_timeouts.append(ms)
        self.events.append(("wait_for_timeout", ms))

    def expect_file_chooser(self):
        raise AssertionError("cover must prefer set_input_files over a file chooser")


def _video(thumbnail: str | None = THUMBNAIL) -> TiktokVideo:
    return TiktokVideo("标题", "/tmp/demo.mp4", ["tag"], 0, None, thumbnail)


class CoverTree:
    """Builds a happy-path cover editor tree and records interactions."""

    def __init__(self, *, save_label: str = "Save", save_enabled: bool = True) -> None:
        self.recorder: list = []
        self.base = FakeNode("base", recorder=self.recorder)
        self.edit_text = self.base.add_text(
            "Edit cover", exact=True, name="edit-cover-text", count=0
        )
        self.edit_role = self.base.add_role(
            "button", "Edit cover", name="edit-cover-role"
        )
        self.upload_tab = self.base.add_text(
            "Upload cover", exact=True, name="upload-tab"
        )
        self.editor = self.upload_tab.add_css(
            COVER_EDITOR_SCOPE_SELECTOR, name="cover-editor"
        )
        self.file_input = self.editor.add_css(FILE_ARIA, name="cover-file")
        self.preview = self.editor.add_css(PREVIEW, name="cover-preview")
        self.save = self.editor.add_role(
            "button", save_label, name="cover-save", enabled=save_enabled
        )


class ApplyCoverNoopTests(unittest.TestCase):
    def test_no_thumbnail_has_zero_cover_interactions(self):
        recorder: list = []
        page = FakePage()
        video = _video(thumbnail=None)
        video.locator_base = FakeNode("base", recorder=recorder)

        asyncio.run(video.apply_cover(page))

        self.assertEqual(recorder, [])
        self.assertEqual(page.wait_timeouts, [])


class ApplyCoverCandidateTests(unittest.TestCase):
    def test_edit_cover_falls_back_from_text_to_role(self):
        tree = CoverTree()
        page = FakePage()
        video = _video()
        video.locator_base = tree.base

        asyncio.run(video.apply_cover(page))

        self.assertIn(("click", "edit-cover-role"), tree.recorder)
        self.assertNotIn(("click", "edit-cover-text"), tree.recorder)
        self.assertIn(("click", "upload-tab"), tree.recorder)
        self.assertIn(("set_input_files", "cover-file", THUMBNAIL), tree.recorder)
        self.assertIn(("click", "cover-save"), tree.recorder)

    def test_file_input_falls_back_to_editor_scoped_selector(self):
        tree = CoverTree()
        tree.file_input.count_value = 0
        scoped = tree.editor.add_css(FILE_ACCEPT, name="cover-file-fallback")
        page = FakePage()
        video = _video()
        video.locator_base = tree.base

        asyncio.run(video.apply_cover(page))

        self.assertIn(("set_input_files", "cover-file-fallback", THUMBNAIL), tree.recorder)
        self.assertNotIn(("set_input_files", "cover-file", THUMBNAIL), tree.recorder)

    def test_all_candidates_absent_reports_control_stage_candidates_and_url(self):
        recorder: list = []
        page = FakePage()
        video = _video()
        video.locator_base = FakeNode("base", recorder=recorder)

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(video.apply_cover(page))

        message = str(ctx.exception)
        self.assertIn("Edit cover", message)
        self.assertIn("open cover editor", message)
        self.assertIn(EDIT_COVER_TEXT, message)
        self.assertIn(EDIT_COVER_ROLE, message)
        self.assertIn(PAGE_URL, message)


class ApplyCoverSaveTests(unittest.TestCase):
    def test_save_accepts_save_and_confirm(self):
        for label in ("Save", "Confirm"):
            with self.subTest(label=label):
                tree = CoverTree(save_label=label)
                page = FakePage()
                video = _video()
                video.locator_base = tree.base

                asyncio.run(video.apply_cover(page))

                self.assertIn(("click", "cover-save"), tree.recorder)

    def test_three_second_wait_is_preserved_after_save(self):
        tree = CoverTree()
        page = FakePage()
        video = _video()
        video.locator_base = tree.base

        asyncio.run(video.apply_cover(page))

        self.assertEqual(page.wait_timeouts, [3000])


class ApplyCoverPreviewTests(unittest.TestCase):
    def test_missing_preview_does_not_block_an_enabled_save(self):
        tree = CoverTree()
        tree.editor.remove_css(PREVIEW)
        page = FakePage()
        video = _video()
        video.locator_base = tree.base

        asyncio.run(video.apply_cover(page))

        self.assertIn(("click", "cover-save"), tree.recorder)
        self.assertEqual(page.wait_timeouts, [3000])

    def test_missing_preview_with_disabled_save_reports_the_preview_stage(self):
        tree = CoverTree(save_enabled=False)
        tree.editor.remove_css(PREVIEW)
        page = FakePage()
        video = _video()
        video.locator_base = tree.base

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(video.apply_cover(page))

        message = str(ctx.exception)
        self.assertIn("Uploaded cover image", message)
        self.assertIn("wait for cover preview", message)
        self.assertIn(PREVIEW, message)
        self.assertIn(PAGE_URL, message)
        self.assertNotIn(("click", "cover-save"), tree.recorder)


if __name__ == "__main__":
    unittest.main()
