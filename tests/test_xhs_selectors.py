# -*- coding: utf-8 -*-
"""XHS selector baseline (spec §3 U4, ticket 33).

The selector matrix is authoritative: structure first, upstream structural
fallback second, Chinese text only as the last resort.  These tests pin the
properties that survive future edits:

1. candidate order — structure wins; the text fallback is only built when the
   structure candidates are absent;
2. file inputs resolve to exactly one element; ambiguity without a narrowing
   container is ``ElementUnusableError`` (never ``.first`` guessing);
3. every resolution logs one hit line — ``debug`` for ``structure`` and one
   extra ``info`` for any non-structure kind (step, kind, selector, URL);
4. the dead anchors stay deleted: the three Chinese publish-button branches,
   ``#publish-container div`` and the two zero-hit cover entries.

Nothing here touches a browser or the network.
"""

from __future__ import annotations

import asyncio
import re
import unittest
from pathlib import Path
from unittest.mock import patch

import uploader.xiaohongshu_uploader.main as xhs_main
from tests.fakes_xhs_dom import FakeLocator, RecordingPage
from utils.dom import Candidate, ElementUnusableError

CJK = re.compile(r"[\u4e00-\u9fff]")
KIND_RANK = {"structure": 0, "upstream": 1, "text-zh": 2}

TITLE_PRIMARY = "div.d-input input"
TITLE_FALLBACK = 'input[placeholder*="填写标题"]'
BODY_PRIMARY = 'div.tiptap[role="textbox"][contenteditable="true"]'
BODY_UPSTREAM = 'div.ProseMirror[contenteditable="true"]'
NOTE_IMAGE_PRIMARY = "div.upload-content input.upload-input"
NOTE_IMAGE_FALLBACK = '.img-list .top input[type="file"][multiple]'
NOTE_URL = "https://creator.xiaohongshu.com/publish/publish?from=homepage&target=image"


def facts(**overrides):
    """A complete computed-style fact dict with per-test overrides."""
    data = {
        "tag": "input",
        "display": "block",
        "visibility": "visible",
        "opacity": 1.0,
        "ariaHidden": None,
        "ancestorAriaHidden": False,
        "disabled": False,
        "disabledClass": False,
        "pointerEvents": "auto",
        "contentEditable": None,
        "readOnly": False,
        "isConnected": True,
    }
    data.update(overrides)
    return data


class LogRecorder:
    """Capture ``xiaohongshu_logger`` calls as ``(level, message)`` pairs."""

    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    def _record(self, level: str, message: object, *args, **kwargs) -> None:
        self.lines.append((level, str(message)))

    def debug(self, message, *args, **kwargs):
        self._record("debug", message, *args, **kwargs)

    def info(self, message, *args, **kwargs):
        self._record("info", message, *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        self._record("warning", message, *args, **kwargs)

    def success(self, message, *args, **kwargs):
        self._record("success", message, *args, **kwargs)

    def error(self, message, *args, **kwargs):
        self._record("error", message, *args, **kwargs)

    def levels(self) -> list[str]:
        return [level for level, _line in self.lines]

    def only(self, level: str) -> list[str]:
        return [line for name, line in self.lines if name == level]


class NoFirstLocator(FakeLocator):
    """File-input double that fails if production code guesses ``.first``."""

    @property
    def first(self) -> "NoFirstLocator":
        raise AssertionError("文件输入类禁止 .first 猜测；多义必须判为不可用")

    @property
    def last(self) -> "NoFirstLocator":
        raise AssertionError("文件输入类禁止 .last 猜测；多义必须判为不可用")


def resolve_anchor(page, step, candidates, **kwargs):
    """Run one resolution call and return ``(resolved, recorder)``."""
    recorder = LogRecorder()
    with patch.object(xhs_main, "xiaohongshu_logger", recorder):
        resolved = asyncio.run(
            xhs_main._resolve_anchor(page, step, candidates, **kwargs)
        )
    return resolved, recorder


# ---------------------------------------------------------------------------
# 1. Candidate order: structure first, text only when structure is absent
# ---------------------------------------------------------------------------


class CandidateOrderTests(unittest.TestCase):
    def test_structure_candidate_wins_over_text_fallback(self):
        page = RecordingPage(
            url=NOTE_URL,
            selectors={
                TITLE_PRIMARY: FakeLocator(
                    "title", computed_style=facts(tag="input")
                ),
                TITLE_FALLBACK: FakeLocator(
                    "title-zh", computed_style=facts(tag="input")
                ),
            },
        )

        resolved, recorder = resolve_anchor(
            page, "标题", xhs_main.XHS_TITLE_CANDIDATES, role="attached"
        )

        self.assertEqual(resolved.selector, TITLE_PRIMARY)
        self.assertEqual(resolved.kind, "structure")
        self.assertEqual(recorder.levels(), ["debug"])
        line = recorder.only("debug")[0]
        for fragment in ("标题", "structure", TITLE_PRIMARY, NOTE_URL):
            self.assertIn(fragment, line)

    def test_text_fallback_only_when_structure_is_absent(self):
        page = RecordingPage(
            url=NOTE_URL,
            selectors={
                TITLE_PRIMARY: FakeLocator(
                    "title-absent", count=0, computed_style=facts()
                ),
                TITLE_FALLBACK: FakeLocator(
                    "title-zh", computed_style=facts(tag="input")
                ),
            },
        )

        resolved, recorder = resolve_anchor(
            page, "标题", xhs_main.XHS_TITLE_CANDIDATES, role="attached"
        )

        self.assertEqual(resolved.selector, TITLE_FALLBACK)
        self.assertEqual(resolved.kind, "text-zh")
        # 首选仍是 debug，且非结构分支额外打一条 info（同一条命中日志）。
        self.assertEqual(recorder.levels(), ["debug", "info"])
        debug_line = recorder.only("debug")[0]
        info_line = recorder.only("info")[0]
        for fragment in ("标题", "text-zh", TITLE_FALLBACK, NOTE_URL):
            self.assertIn(fragment, debug_line)
            self.assertIn(fragment, info_line)

    def test_upstream_structural_fallback_logs_info(self):
        page = RecordingPage(
            url=NOTE_URL,
            selectors={
                BODY_PRIMARY: FakeLocator(
                    "body", count=0, computed_style=facts(tag="div")
                ),
                BODY_UPSTREAM: FakeLocator(
                    "body-upstream", computed_style=facts(tag="div")
                ),
            },
        )

        resolved, recorder = resolve_anchor(
            page, "正文", xhs_main.XHS_BODY_CANDIDATES, role="attached"
        )

        self.assertEqual(resolved.selector, BODY_UPSTREAM)
        self.assertEqual(resolved.kind, "upstream")
        self.assertEqual(recorder.levels(), ["debug", "info"])

    def test_candidate_tuples_are_ordered_structure_upstream_text(self):
        names = [name for name in dir(xhs_main) if name.endswith("_CANDIDATES")]
        self.assertTrue(names, "expected module-level candidate tuples")

        for name in names:
            candidates = getattr(xhs_main, name)
            self.assertIsInstance(candidates, tuple, name)
            self.assertTrue(candidates, name)
            kinds = [candidate.kind for candidate in candidates]
            self.assertEqual(
                kinds,
                sorted(kinds, key=KIND_RANK.__getitem__),
                f"{name} 必须按 结构 → 上游 → 中文文本 排序: {kinds}",
            )

    def test_structure_candidates_carry_no_chinese_text(self):
        names = [name for name in dir(xhs_main) if name.endswith("_CANDIDATES")]

        for name in names:
            for candidate in getattr(xhs_main, name):
                if candidate.kind != "structure":
                    continue
                self.assertIsNone(
                    CJK.search(candidate.selector),
                    f"{name} 的结构候选不能依赖中文文案: {candidate.selector}",
                )

    def test_publish_button_has_exactly_one_structural_candidate(self):
        self.assertEqual(xhs_main.XHS_PUBLISH_BUTTON_SELECTOR, "xhs-publish-btn")
        self.assertEqual(
            xhs_main.XHS_PUBLISH_BUTTON_CANDIDATES,
            (Candidate("xhs-publish-btn"),),
        )
        self.assertNotIn(
            "button:has-text",
            xhs_main.XHS_PUBLISH_BUTTON_CANDIDATES[0].selector,
        )


# ---------------------------------------------------------------------------
# 2. File inputs: exactly one match, never ``.first``
# ---------------------------------------------------------------------------


class FileInputUniquenessTests(unittest.TestCase):
    def test_ambiguous_image_input_is_unusable(self):
        page = RecordingPage(
            url=NOTE_URL,
            selectors={
                NOTE_IMAGE_PRIMARY: NoFirstLocator("image-inputs", count=2),
                NOTE_IMAGE_FALLBACK: NoFirstLocator(
                    "image-inputs-fallback", count=2
                ),
            },
        )

        with self.assertRaises(ElementUnusableError) as ctx:
            resolve_anchor(
                page,
                "图文上传输入",
                xhs_main.XHS_NOTE_IMAGE_CANDIDATES,
                role="attached",
                timeout_ms=150,
            )

        self.assertEqual(ctx.exception.reason, "ambiguous:2")
        self.assertIn("ambiguous:2", str(ctx.exception))

    def test_ambiguity_narrowed_by_container_falls_back(self):
        page = RecordingPage(
            url=NOTE_URL,
            selectors={
                NOTE_IMAGE_PRIMARY: NoFirstLocator("image-inputs", count=2),
                NOTE_IMAGE_FALLBACK: NoFirstLocator("image-input-unique", count=1),
            },
        )

        resolved, recorder = resolve_anchor(
            page,
            "图文上传输入",
            xhs_main.XHS_NOTE_IMAGE_CANDIDATES,
            role="attached",
        )

        self.assertEqual(resolved.selector, NOTE_IMAGE_FALLBACK)
        self.assertEqual(resolved.kind, "upstream")
        self.assertEqual(recorder.levels(), ["debug", "info"])

    def test_ambiguous_video_input_is_unusable(self):
        page = RecordingPage(
            url="https://creator.xiaohongshu.com/publish/publish?target=video",
            selectors={
                NOTE_IMAGE_PRIMARY: NoFirstLocator("video-inputs", count=3),
                'input[type="file"][accept*=".mp4"]': NoFirstLocator(
                    "video-mp4", count=0
                ),
                'input[type="file"][accept*="video"]': NoFirstLocator(
                    "video-accept", count=0
                ),
            },
        )

        with self.assertRaises(ElementUnusableError) as ctx:
            resolve_anchor(
                page,
                "视频上传输入",
                xhs_main.XHS_VIDEO_FILE_CANDIDATES,
                role="attached",
                timeout_ms=150,
            )

        self.assertEqual(ctx.exception.reason, "ambiguous:3")

    def test_note_upload_raises_before_guessing_when_input_is_ambiguous(self):
        app = xhs_main.XiaoHongShuNote(
            image_paths=["a.png"],
            note="",
            tags=[],
            publish_date=0,
            account_file="account.json",
            title="标题",
            no_publish=True,
        )
        page = RecordingPage(
            url=NOTE_URL,
            selectors={
                NOTE_IMAGE_PRIMARY: NoFirstLocator("image-inputs", count=2),
                NOTE_IMAGE_FALLBACK: NoFirstLocator(
                    "image-inputs-fallback", count=2
                ),
            },
        )

        with patch.object(
            xhs_main, "XHS_NOTE_UPLOAD_INPUT_TIMEOUT_MS", 150
        ), self.assertRaises(ElementUnusableError):
            asyncio.run(app.upload_note_content(page, multilogin=False))


# ---------------------------------------------------------------------------
# 3. Call-site wiring: the structural anchor is the one that gets used
# ---------------------------------------------------------------------------


class CallSiteAnchorTests(unittest.TestCase):
    def test_fill_title_uses_the_structural_anchor(self):
        app = xhs_main.XiaoHongShuVideo(
            title="标题内容",
            file_path="demo.mp4",
            tags=[],
            publish_date=0,
            account_file="account.json",
        )
        primary = FakeLocator(
            "title", computed_style=facts(tag="input"), visible=True, enabled=True
        )
        fallback = FakeLocator(
            "title-zh", computed_style=facts(tag="input"), visible=True, enabled=True
        )
        page = RecordingPage(
            url=NOTE_URL,
            selectors={TITLE_PRIMARY: primary, TITLE_FALLBACK: fallback},
        )

        asyncio.run(app.fill_title(page))

        self.assertEqual(primary.actions, [("fill", "标题内容")])
        self.assertEqual(fallback.actions, [])


# ---------------------------------------------------------------------------
# 4. Static deletion: dead anchors stay deleted
# ---------------------------------------------------------------------------


class DeadAnchorDeletionTests(unittest.TestCase):
    DEAD_ANCHORS = (
        'button:has-text("发布")',
        'button:has-text("定时发布")',
        "#publish-container div",
        "div.upload-cover",
        "div.cover-plugin-preview div.default.pointer",
    )

    def test_dead_anchors_are_gone_from_the_uploader(self):
        source = Path(xhs_main.__file__).read_text(encoding="utf-8")

        for anchor in self.DEAD_ANCHORS:
            self.assertNotIn(anchor, source, f"死锚点必须删除: {anchor}")

    def test_login_positive_anchors_are_text_free(self):
        for selector in xhs_main.XHS_LOGIN_POSITIVE_SELECTORS:
            self.assertNotIn("has-text", selector)
            self.assertIsNone(CJK.search(selector))

    def test_declaration_container_is_the_real_class(self):
        self.assertEqual(
            xhs_main.XHS_DECLARATION_CONTAINER_SELECTOR, ".publish-container"
        )
        self.assertNotIn(
            "#publish-container",
            xhs_main.XHS_DECLARATION_CONTAINER_SELECTOR,
        )


if __name__ == "__main__":
    unittest.main()
