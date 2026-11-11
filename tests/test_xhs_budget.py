# -*- coding: utf-8 -*-
"""Budget (deadline) wiring for the XHS publish chain — ticket 31.

The whole publish run shares one ``PublishTimeoutBudget``.  These tests pin the
three properties the ticket asks for:

1. no bare numeric ``timeout=`` / ``asyncio.sleep(<number>)`` literal survives in
   ``uploader/xiaohongshu_uploader/`` (static assertion);
2. every wait's timeout is derived from the budget and shrinks with what is
   left of the 15-minute deadline;
3. the two budget exits are the only source of the two failure messages —
   ``budget.pre_click_error()`` (exit 1) before dispatch and
   ``budget.timeout_error(publish_clicked=True)`` (exit 9) after dispatch.

Everything is offline and virtual-time: ``tests.fakes_clock`` patches the
module's ``time``/``asyncio`` names and ``tests.fakes_xhs_dom`` records every
``wait_for_*`` call with the exact timeout it received.
"""

from __future__ import annotations

import asyncio
import re
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import uploader.publish_timeout as publish_timeout
import uploader.xiaohongshu_uploader.main as xhs_main
from tests.fakes_clock import FakeClock
from tests.fakes_xhs_dom import FakeLocator, RecordingLocator, RecordingPage
from utils.errors import PublishResultUnknownError

#: The exact wording required by ticket 31 (§3 U1).  The platform prefix
#: ("小红书…") may stay in front of it.
REQUIRED_PRE_CLICK_WORDING = "发布超时（15 分钟）：尚未点击发布，未发布任何内容"

UPLOADER_DIR = Path(xhs_main.__file__).parent

VIDEO_UPLOAD_SELECTOR = "input.upload-input"
VIDEO_FILE_INPUT_SELECTOR = "div[class^='upload-content'] input[class='upload-input']"
TITLE_SELECTOR = 'input[placeholder*="填写标题"]'
NOTE_IMAGE_INPUT_SELECTOR = 'input[type="file"][accept*="image"]'
PUBLISH_BUTTON_SELECTOR = 'button:has-text("发布")'


# ---------------------------------------------------------------------------
# Local doubles (the shared fixtures stay untouched; ticket 28 owns them)
# ---------------------------------------------------------------------------


class _FileInput(FakeLocator):
    """File input double: records every ``set_input_files`` call."""

    def __init__(self, name: str = "file-input", *, page: RecordingPage | None = None):
        super().__init__(name)
        self.files: list[object] = []
        self._page = page

    async def set_input_files(self, files, **kwargs):
        self.files.append(files)


class _UploadInput(_FileInput):
    """``input.upload-input`` double that reports a finished video upload."""

    def __init__(self, *, preview_text: str = "上传成功 分辨率 1080P"):
        super().__init__("upload-input")
        self._preview = FakeLocator("preview", text=preview_text)

    async def query_selector(self, selector):
        return self._preview


class _AdvancingPage(RecordingPage):
    """RecordingPage that burns virtual time on navigation."""

    def __init__(self, clock: FakeClock, *, advance_on_goto: float = 0.0, **kwargs):
        super().__init__(**kwargs)
        self.clock = clock
        self.advance_on_goto = advance_on_goto

    async def goto(self, url: str, **kwargs):
        await super().goto(url, **kwargs)
        self.clock.advance(self.advance_on_goto)


class _AdvancingClickLocator(RecordingLocator):
    """Publish button double: the dispatch itself burns virtual time."""

    def __init__(self, name: str, clock: FakeClock, *, advance: float = 0.0):
        super().__init__(name)
        self.clock = clock
        self.advance = advance

    async def click(self, **kwargs):
        await super().click(**kwargs)
        self.clock.advance(self.advance)


class _SuccessClickLocator(RecordingLocator):
    """Publish button double: the dispatch navigates to the success URL."""

    def __init__(self, name: str, page: RecordingPage):
        super().__init__(name)
        self._page = page

    async def click(self, **kwargs):
        await super().click(**kwargs)
        self._page.url = "https://creator.xiaohongshu.com/publish/success?target=video"


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


# ---------------------------------------------------------------------------
# 1. Static assertion: no bare numeric waits in the XHS publish chain
# ---------------------------------------------------------------------------


class StaticBudgetLiteralTests(unittest.TestCase):
    """The acceptance gate from the ticket: ``rg "timeout=[0-9]"`` must be empty."""

    def _find(self, pattern: str) -> list[str]:
        regex = re.compile(pattern)
        offenders: list[str] = []
        for path in sorted(UPLOADER_DIR.glob("*.py")):
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if regex.search(line):
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
        return offenders

    def test_no_bare_numeric_timeout_literal(self):
        offenders = self._find(r"timeout\s*=\s*\d")

        self.assertEqual(
            offenders,
            [],
            "every timeout must come from PublishTimeoutBudget.clamp_ms(); "
            "replace the numeric literal with a named constant + clamp",
        )

    def test_no_bare_numeric_asyncio_sleep(self):
        offenders = self._find(r"asyncio\.sleep\(\s*\d")

        self.assertEqual(
            offenders,
            [],
            "wait loops must sleep a named interval clamped by the budget",
        )

    def test_no_business_code_processing_timeout_message(self):
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(UPLOADER_DIR.glob("*.py"))
        )

        self.assertNotIn(
            "处理超时",
            source,
            "the only timeout exits are PublishTimeoutBudget.pre_click_error() "
            "and timeout_error(publish_clicked=True)",
        )


# ---------------------------------------------------------------------------
# 2. Clamp shrinks with the remaining budget
# ---------------------------------------------------------------------------


class WaitTimeoutShrinkTests(unittest.TestCase):
    def test_wait_timeout_shrinks_with_remaining_budget(self):
        app = _video_app()
        clock = FakeClock(start=1_000.0)

        with clock.patch(xhs_main, publish_timeout):
            app.start_publish_budget()  # 15 分钟 = 900 秒
            self.assertEqual(app._wait_ms(900_000), 900_000)

            clock.advance(600)
            self.assertEqual(app._wait_ms(900_000), 300_000)

            clock.advance(299)
            self.assertEqual(app._wait_ms(900_000), 1_000)

    def test_exhausted_budget_surfaces_budget_pre_click_error(self):
        app = _video_app()
        clock = FakeClock(start=0.0)

        with clock.patch(xhs_main, publish_timeout):
            budget = app.start_publish_budget()
            clock.advance(901)

            with self.assertRaises(RuntimeError) as ctx:
                app._wait_ms(30_000)

        self.assertEqual(str(ctx.exception), str(budget.pre_click_error()))
        self.assertIn(REQUIRED_PRE_CLICK_WORDING, str(ctx.exception))
        self.assertNotIsInstance(ctx.exception, PublishResultUnknownError)

    def test_post_click_budget_never_raises_pre_click_error(self):
        app = _video_app()
        clock = FakeClock(start=0.0)

        with clock.patch(xhs_main, publish_timeout):
            app.start_publish_budget()
            clock.advance(901)

            # 点击后预算耗尽不能变成 exit 1：外层发布循环据剩余预算映射 9。
            self.assertEqual(app._wait_ms(3_000, publish_clicked=True), 1)


# ---------------------------------------------------------------------------
# 3. Video chain: navigation, upload and observation come from the budget
# ---------------------------------------------------------------------------


def _video_page(clock: FakeClock, *, advance_on_goto: float = 0.0, **overrides):
    upload_input = overrides.pop("upload_input", _UploadInput())
    selectors = {
        VIDEO_UPLOAD_SELECTOR: upload_input,
        VIDEO_FILE_INPUT_SELECTOR: _FileInput("video-file"),
        TITLE_SELECTOR: RecordingLocator("title"),
    }
    selectors.update(overrides.pop("selectors", {}))
    page = _AdvancingPage(
        clock,
        advance_on_goto=advance_on_goto,
        url="about:blank",
        selectors=selectors,
        **overrides,
    )
    return page, upload_input


class VideoChainBudgetTests(unittest.TestCase):
    def test_navigation_upload_and_url_guard_are_clamped(self):
        clock = FakeClock(start=0.0)
        with clock.patch(xhs_main, publish_timeout):
            page, _upload_input = _video_page(clock, advance_on_goto=880.0)
            asyncio.run(_video_app().upload_video_content(page, multilogin=False))

        _url, goto_kwargs = page.goto_calls[0]
        self.assertEqual(goto_kwargs["wait_until"], "domcontentloaded")
        self.assertEqual(goto_kwargs["timeout"], xhs_main.XHS_NAVIGATION_TIMEOUT_MS)

        # goto 花掉 880 秒后只剩 20 秒：URL 守卫必须收缩到这个剩余量。
        self.assertEqual(page.timeouts("wait_for_url"), [20_000])
        self.assertEqual(page.timeouts("wait_for_selector"), [3_000])
        self.assertTrue(
            all(isinstance(value, int) for value in page.timeouts()),
            f"all waits must be budget-derived ints: {page.wait_calls}",
        )

    def test_pre_click_budget_exhaustion_exits_through_budget_error(self):
        clock = FakeClock(start=0.0)
        with clock.patch(xhs_main, publish_timeout):
            page, _upload_input = _video_page(clock, advance_on_goto=901.0)
            app = _video_app()
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(app.upload_video_content(page, multilogin=False))

        self.assertIn(REQUIRED_PRE_CLICK_WORDING, str(ctx.exception))
        self.assertEqual(str(ctx.exception), str(app._publish_budget.pre_click_error()))
        self.assertNotIsInstance(ctx.exception, PublishResultUnknownError)
        # 预算在导航后的 URL 守卫处就耗尽，没有走到点击。
        self.assertEqual(page.goto_calls[0][1]["timeout"], 30_000)

    def test_post_click_budget_exhaustion_is_result_unknown(self):
        clock = FakeClock(start=0.0)
        publish = _AdvancingClickLocator("publish", clock, advance=901.0)
        with clock.patch(xhs_main, publish_timeout):
            page, _upload_input = _video_page(
                clock,
                selectors={PUBLISH_BUTTON_SELECTOR: publish},
            )
            app = _video_app(no_publish=False)
            with self.assertRaises(PublishResultUnknownError) as ctx:
                asyncio.run(app.upload_video_content(page, multilogin=False))

        self.assertEqual(str(ctx.exception), str(app._publish_budget.timeout_error(True)))
        self.assertIn("禁止自动重发", str(ctx.exception))
        publish.assert_clicked_once()


# ---------------------------------------------------------------------------
# 4. Note chain: the same clamp for the image upload and the ready wait
# ---------------------------------------------------------------------------


class NoteChainBudgetTests(unittest.TestCase):
    def test_note_upload_waits_are_clamped(self):
        clock = FakeClock(start=0.0)
        image_input = _FileInput("image-input")
        title = RecordingLocator("title")
        with clock.patch(xhs_main, publish_timeout):
            page = _AdvancingPage(
                clock,
                advance_on_goto=890.0,
                url="about:blank",
                selectors={
                    NOTE_IMAGE_INPUT_SELECTOR: image_input,
                    TITLE_SELECTOR: title,
                },
            )
            asyncio.run(_note_app().upload_note_content(page, multilogin=False))

        # goto 剩余 10 秒：附件 input 的 30 秒上限收缩到 10 秒。
        self.assertEqual(image_input.wait_calls[0].timeout, 10_000)
        self.assertEqual(title.wait_calls[0].timeout, 3_000)
        _url, goto_kwargs = page.goto_calls[0]
        self.assertEqual(goto_kwargs["wait_until"], "domcontentloaded")


# ---------------------------------------------------------------------------
# 5. --not-before wait is excluded from the publish budget
# ---------------------------------------------------------------------------


class NotBeforeBudgetTests(unittest.TestCase):
    def test_not_before_wait_does_not_consume_the_publish_budget(self):
        clock = FakeClock(start=500.0)
        with clock.patch(xhs_main, publish_timeout):
            page, _upload_input = _video_page(clock, advance_on_goto=300.0)
            publish = _SuccessClickLocator("publish", page)
            page._selectors[PUBLISH_BUTTON_SELECTOR] = publish
            app = _video_app(no_publish=False)
            app.publish_not_before = datetime.now() + timedelta(hours=1)

            async def fake_not_before_wait(*_args, **_kwargs):
                # 真正等待的 120 秒不计入 15 分钟预算。
                clock.advance(120)

            with patch.object(
                publish_timeout,
                "wait_until_publish_allowed",
                fake_not_before_wait,
            ):
                asyncio.run(app.upload_video_content(page, multilogin=False))

            # 900 秒预算 - 300 秒导航 = 600 秒；--not-before 的 120 秒已顺延。
            remaining = app._publish_budget.remaining_seconds()

        self.assertAlmostEqual(remaining, 600.0)
        publish.assert_clicked_once()


if __name__ == "__main__":
    unittest.main()
