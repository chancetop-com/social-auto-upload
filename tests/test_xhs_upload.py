# -*- coding: utf-8 -*-
"""Upload-completion gate (spec §3 U6, ticket 38).

The gate sits between "file dispatched" and ``fill_meta``: metadata may only be
filled once the media is actually ready.

* note (image) — one image at a time; image *i* is complete when the preview
  tile count is at least ``i + 1`` **and** that tile no longer carries
  ``.mask.uploading`` (per-tile, never a global mask count);
* the 2nd image onwards goes through the ``+`` tile → ``expect_file_chooser``
  (fallback: the single ``multiple`` file input), never ``inputs[0]``/``.first``;
* video — the one ARM predicate (``_arm_ready``) is the completion signal,
  1s polling, window ``min(600s, remaining budget)``, with the two structural
  failure states (``div.fail`` / ``.video-container-loading-text``) aborting
  immediately.

Every failure is a plain ``RuntimeError`` (exit 1, definitely not published):
no per-media / per-index exit codes, no keyword scanning, no retry, no
downgrade to fewer images.
"""

from __future__ import annotations

import asyncio
import inspect
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import uploader.publish_timeout as publish_timeout
import uploader.xiaohongshu_uploader.main as xhs_main
from tests.fakes_clock import FakeClock
from tests.fakes_xhs_dom import FakeLocator, RecordingLocator, RecordingPage
from utils import dom
from utils.dom import ElementMissingError, ElementUnusableError
from utils.humanize import DEFAULT_PROFILE, Humanizer

NOTE_INPUT = "div.upload-content input.upload-input"
NOTE_ADD_TILE = ".img-preview-area .entry"
NOTE_ADD_INPUT = '.img-list .top input[type="file"][multiple]'
NOTE_TILES = ".img-preview-area .pr"
NOTE_MASK = ".mask.uploading"
PUBLISH = "xhs-publish-btn"
LOGIN_BOX = xhs_main.XHS_LOGIN_BOX_SELECTOR
VIDEO_FAIL = "div[class='fail']"
VIDEO_LOADING_TEXT = ".video-container-loading-text"
NOTE_URL = "https://creator.xiaohongshu.com/publish/publish?from=homepage&target=image"
VIDEO_URL = "https://creator.xiaohongshu.com/publish/publish?from=homepage&target=video"

BUTTON_FACTS = {
    "tag": "button",
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


# ---------------------------------------------------------------------------
# Local doubles
# ---------------------------------------------------------------------------


class _FileInput(FakeLocator):
    """File input double: records every ``set_input_files`` payload."""

    def __init__(self, name: str = "file-input", *, count: int | None = None):
        super().__init__(name, count=count)
        self.files: list[object] = []

    async def set_input_files(self, files, **kwargs) -> None:
        self.files.append(files)


class _FailingFileInput(_FileInput):
    async def set_input_files(self, files, **kwargs) -> None:
        self.files.append(files)
        raise RuntimeError("set_input_files exploded")


class _Sequence(FakeLocator):
    """``count()`` walks a scripted sequence; the last value sticks."""

    def __init__(self, name: str, counts: list[int]) -> None:
        super().__init__(name)
        self.counts = list(counts)
        self.calls = 0

    async def count(self) -> int:
        value = self.counts[min(self.calls, len(self.counts) - 1)]
        self.calls += 1
        return value


class _Tiles(FakeLocator):
    """``.img-preview-area .pr`` double whose ``count()`` moves a timeline."""

    def __init__(self, counts: list[int], tiles: list[FakeLocator]) -> None:
        super().__init__("tiles")
        self._counts = _Sequence("tile-count", counts)
        self._tiles = tiles

    async def count(self) -> int:
        return await self._counts.count()

    def nth(self, index: int) -> FakeLocator:
        return self._tiles[index]


def _tile(mask_counts: list[int] | None) -> FakeLocator:
    if mask_counts is None:
        return FakeLocator("tile", children={NOTE_MASK: FakeLocator("mask", count=0)})
    return FakeLocator(
        "tile", children={NOTE_MASK: _Sequence("mask", mask_counts)}
    )


class _LogRecorder:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    def _record(self, level: str, message, *args, **kwargs) -> None:
        self.lines.append((level, str(message)))

    def debug(self, message, *args, **kwargs):
        self._record("debug", message)

    def info(self, message, *args, **kwargs):
        self._record("info", message)

    def warning(self, message, *args, **kwargs):
        self._record("warning", message)

    def success(self, message, *args, **kwargs):
        self._record("success", message)

    def error(self, message, *args, **kwargs):
        self._record("error", message)

    def warnings(self) -> list[str]:
        return [line for level, line in self.lines if level == "warning"]


class _PublishButton(RecordingLocator):
    def __init__(self, name: str = "publish", *, enabled: bool = True):
        super().__init__(
            name, computed_style=dict(BUTTON_FACTS), enabled=enabled
        )

    async def bounding_box(self):
        return {"x": 0.0, "y": 0.0, "width": 160.0, "height": 40.0}

    async def evaluate(self, expression, arg=None):
        self.evaluate_calls.append((expression, arg))
        if isinstance(expression, str) and "elementFromPoint" in expression:
            return {"self": True, "tag": "button", "className": ""}
        return dict(BUTTON_FACTS)


class _QuietPage(RecordingPage):
    """RecordingPage where ``wait_dom_quiet`` reports "already quiet"."""

    def __init__(self, *, quiet: bool = True, **kwargs):
        kwargs.setdefault(
            "evaluate_handler",
            lambda expression, arg=None: (
                {"since": 10_000} if "performance.now" in str(expression) else True
            ),
        )
        self.quiet = quiet
        super().__init__(**kwargs)

    async def evaluate(self, expression, arg=None):
        if "performance.now" in str(expression) and "state" in str(expression):
            self.evaluate_calls.append((expression, arg))
            return {"since": 10_000 if self.quiet else 0}
        if "Observer" in str(expression):
            self.evaluate_calls.append((expression, arg))
            return True
        return await super().evaluate(expression, arg)


def _humanizer(page: RecordingPage) -> Humanizer:
    return Humanizer(page, profile=replace(DEFAULT_PROFILE, enabled=False))


def _budget() -> publish_timeout.PublishTimeoutBudget:
    return publish_timeout.PublishTimeoutBudget("小红书")


def _note_page(
    *,
    counts: list[int],
    tiles: list[FakeLocator] | None = None,
    image_input: FakeLocator | None = None,
    add_input: FakeLocator | None = None,
    add_tile: FakeLocator | None = None,
    quiet: bool = True,
    chooser=None,
) -> RecordingPage:
    tile_locators = tiles or [_tile(None)]
    return _QuietPage(
        url=NOTE_URL,
        quiet=quiet,
        selectors={
            NOTE_INPUT: image_input or _FileInput("image-input"),
            NOTE_TILES: _Tiles(counts, tile_locators),
            NOTE_ADD_TILE: add_tile or RecordingLocator("add-tile"),
            NOTE_ADD_INPUT: add_input or _FileInput("add-input"),
            LOGIN_BOX: FakeLocator("login-box", count=0),
        },
        file_chooser=chooser,
    )


# ---------------------------------------------------------------------------
# 1. Note dispatch: one image at a time, 2nd+ through the file chooser
# ---------------------------------------------------------------------------


class NoteDispatchTests(unittest.TestCase):
    def test_first_image_uses_the_unique_upload_input(self):
        page = _note_page(counts=[1], tiles=[_tile(None)])
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout, dom):
            asyncio.run(
                xhs_main._note_upload_gate(
                    page,
                    ["a.png"],
                    budget=_budget(),
                    mode="local",
                    humanizer=_humanizer(page),
                )
            )

        self.assertEqual(page.locator(NOTE_INPUT).files, [["a.png"]])

    def test_second_image_goes_through_the_file_chooser(self):
        page = _note_page(
            counts=[1, 2],
            tiles=[_tile(None), _tile(None)],
        )
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout, dom):
            asyncio.run(
                xhs_main._note_upload_gate(
                    page,
                    ["a.png", "b.png"],
                    budget=_budget(),
                    mode="local",
                    humanizer=_humanizer(page),
                )
            )

        # 首张走唯一上传入口；第二张只经「+」瓦片的文件选择器派发。
        self.assertEqual(page.locator(NOTE_INPUT).files, [["a.png"]])
        self.assertEqual(page.file_chooser_files(), [["b.png"]])
        self.assertEqual(page.expect_file_chooser_calls, 1)
        self.assertEqual(page.locator(NOTE_ADD_TILE).click_count, 1)
        self.assertEqual(page.locator(NOTE_ADD_INPUT).files, [])

    def test_second_image_falls_back_when_the_add_tile_is_missing(self):
        page = _note_page(
            counts=[1, 2],
            tiles=[_tile(None), _tile(None)],
            add_tile=FakeLocator("absent-tile", count=0),
        )
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout, dom):
            asyncio.run(
                xhs_main._note_upload_gate(
                    page,
                    ["a.png", "b.png"],
                    budget=_budget(),
                    mode="local",
                    humanizer=_humanizer(page),
                )
            )

        self.assertEqual(page.file_chooser_files(), [])
        self.assertEqual(page.locator(NOTE_ADD_INPUT).files, [["b.png"]])

    def test_second_image_falls_back_to_the_multiple_input_when_no_chooser(self):
        page = _note_page(
            counts=[1, 2],
            tiles=[_tile(None), _tile(None)],
        )
        page.fail_file_chooser = TimeoutError("no chooser")
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout, dom):
            asyncio.run(
                xhs_main._note_upload_gate(
                    page,
                    ["a.png", "b.png"],
                    budget=_budget(),
                    mode="local",
                    humanizer=_humanizer(page),
                )
            )

        self.assertEqual(page.file_chooser_files(), [])
        self.assertEqual(page.locator(NOTE_ADD_INPUT).files, [["b.png"]])

    def test_images_are_dispatched_one_at_a_time_with_a_one_second_gap(self):
        page = _note_page(counts=[1, 2], tiles=[_tile(None), _tile(None)])
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout, dom):
            asyncio.run(
                xhs_main._note_upload_gate(
                    page,
                    ["a.png", "b.png"],
                    budget=_budget(),
                    mode="local",
                    humanizer=_humanizer(page),
                )
            )

        # 从不批量：首张 input 只收到 1 张，第二张另派 1 张。
        self.assertEqual(len(page.locator(NOTE_INPUT).files), 1)
        self.assertEqual(sum(len(batch) for batch in page.file_chooser_files()), 1)
        self.assertIn(1.0, clock.sleep_calls)

    def test_set_input_files_failure_aborts_without_waiting(self):
        page = _note_page(
            counts=[1],
            tiles=[_tile(None)],
            image_input=_FailingFileInput("image-input"),
        )
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout, dom):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(
                    xhs_main._note_upload_gate(
                        page,
                        ["a.png"],
                        budget=_budget(),
                        mode="local",
                        humanizer=_humanizer(page),
                    )
                )

        self.assertIn("未点击发布", str(ctx.exception))
        self.assertEqual(clock.sleep_calls, [])


# ---------------------------------------------------------------------------
# 2. Note completion: tile count + that tile's mask, nothing else
# ---------------------------------------------------------------------------


class NoteCompletionTests(unittest.TestCase):
    def test_tile_count_and_mask_disappearance_complete_the_image(self):
        tile = _tile([1, 1, 0])
        page = _note_page(counts=[0, 1, 1], tiles=[tile])
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout, dom):
            asyncio.run(
                xhs_main._note_upload_gate(
                    page,
                    ["a.png"],
                    budget=_budget(),
                    mode="local",
                    humanizer=_humanizer(page),
                )
            )

        # 0 → 等一个 500ms 轮询；1 + 遮罩仍在 → 再等；遮罩消失 → 完成。
        self.assertEqual(clock.sleep_calls[:2], [0.5, 0.5])

    def test_completion_is_per_tile_not_a_global_mask_count(self):
        # 第 1 张已完成（无遮罩）；第 2 张仍在上传 → 第 2 张不能算完成。
        tiles = [_tile(None), _tile([1, 0])]
        page = _note_page(counts=[1, 2, 2, 2], tiles=tiles)

        async def ready(index: int) -> bool:
            return await xhs_main._note_image_ready(page, index)

        with FakeClock().patch(xhs_main, publish_timeout, dom):
            self.assertFalse(asyncio.run(ready(1)))  # 瓦片数不足
            self.assertFalse(asyncio.run(ready(1)))  # 瓦片 2 的遮罩还在
            self.assertTrue(asyncio.run(ready(1)))  # 遮罩消失

    def test_abort_window_is_sixty_seconds_and_names_the_image(self):
        page = _note_page(counts=[0], tiles=[_tile(None)])
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout, dom):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(
                    xhs_main._note_upload_gate(
                        page,
                        ["a.png"],
                        budget=_budget(),
                        mode="local",
                        humanizer=_humanizer(page),
                    )
                )

        self.assertIn("第 1 张 / 共 1 张", str(ctx.exception))
        self.assertIn("未点击发布", str(ctx.exception))
        self.assertAlmostEqual(sum(clock.sleep_calls), 60.0)
        self.assertTrue(all(delay == 0.5 for delay in clock.sleep_calls))


# ---------------------------------------------------------------------------
# 3. Note closing recheck: one quiet gate, then recount
# ---------------------------------------------------------------------------


class NoteQuietRecheckTests(unittest.TestCase):
    def _run(self, page):
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout, dom):
            asyncio.run(
                xhs_main._note_upload_gate(
                    page,
                    ["a.png"],
                    budget=_budget(),
                    mode="local",
                    humanizer=_humanizer(page),
                )
            )
        return clock

    def test_at_least_n_proceeds_to_metadata(self):
        page = _note_page(counts=[1], tiles=[_tile(None)])
        recorder = _LogRecorder()
        with patch.object(xhs_main, "xiaohongshu_logger", recorder):
            self._run(page)

        self.assertEqual(page.locator(NOTE_INPUT).files, [["a.png"]])
        self.assertEqual(recorder.warnings(), [])

    def test_more_than_n_warns_and_continues(self):
        page = _note_page(counts=[2], tiles=[_tile(None), _tile(None)])
        recorder = _LogRecorder()
        with patch.object(xhs_main, "xiaohongshu_logger", recorder):
            self._run(page)

        self.assertTrue(
            any("多于" in line for line in recorder.warnings()),
            recorder.lines,
        )

    def test_fewer_than_n_keeps_waiting_to_the_window_then_aborts(self):
        page = _note_page(counts=[1, 0], tiles=[_tile(None)])
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout, dom):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(
                    xhs_main._note_upload_gate(
                        page,
                        ["a.png"],
                        budget=_budget(),
                        mode="local",
                        humanizer=_humanizer(page),
                    )
                )

        self.assertIn("第 1 张 / 共 1 张", str(ctx.exception))
        self.assertIn("未点击发布", str(ctx.exception))
        self.assertAlmostEqual(sum(clock.sleep_calls), 60.0)

    def test_dom_not_quiet_only_warns(self):
        page = _note_page(counts=[1], tiles=[_tile(None)], quiet=False)
        recorder = _LogRecorder()
        with patch.object(xhs_main, "xiaohongshu_logger", recorder):
            self._run(page)

        self.assertTrue(
            any("静默" in line for line in recorder.warnings()),
            recorder.warnings(),
        )
        self.assertEqual(page.locator(NOTE_INPUT).files, [["a.png"]])


# ---------------------------------------------------------------------------
# 4. Note input errors abort immediately (no 60s wait)
# ---------------------------------------------------------------------------


class NoteInputErrorTests(unittest.TestCase):
    def test_ambiguous_input_aborts_without_upload_polling(self):
        page = _note_page(
            counts=[0],
            image_input=_FileInput("image-input", count=2),
            add_input=_FileInput("add-input", count=2),
        )
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout, dom):
            with self.assertRaises(ElementUnusableError):
                asyncio.run(
                    xhs_main._note_upload_gate(
                        page,
                        ["a.png"],
                        budget=_budget(),
                        mode="local",
                        humanizer=_humanizer(page),
                    )
                )

        self.assertEqual(clock.sleep_calls, [])
        self.assertEqual(page.locator(NOTE_INPUT).files, [])

    def test_missing_input_aborts_without_upload_polling(self):
        page = _note_page(
            counts=[0],
            image_input=FakeLocator("absent", count=0),
            add_input=FakeLocator("absent-add", count=0),
        )
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout, dom):
            with self.assertRaises(ElementMissingError):
                asyncio.run(
                    xhs_main._note_upload_gate(
                        page,
                        ["a.png"],
                        budget=_budget(),
                        mode="local",
                        humanizer=_humanizer(page),
                    )
                )

        # 只有输入解析的短等待，没有进入 60s 上传窗口。
        self.assertLess(sum(clock.sleep_calls), 1.0)

    def test_budget_exhaustion_uses_the_budget_pre_click_message(self):
        page = _note_page(counts=[0], tiles=[_tile(None)])
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout, dom):
            budget = _budget()
            budget.deadline = clock.monotonic() + 3.0
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(
                    xhs_main._note_upload_gate(
                        page,
                        ["a.png"],
                        budget=budget,
                        mode="local",
                        humanizer=_humanizer(page),
                    )
                )

        self.assertEqual(str(ctx.exception), str(budget.pre_click_error()))
        self.assertIn("尚未点击发布", str(ctx.exception))
        self.assertIn("小红书发布超时", str(ctx.exception))


# ---------------------------------------------------------------------------
# 5. Video: the ARM predicate is the only completion signal
# ---------------------------------------------------------------------------


def _video_page(
    *,
    button: FakeLocator | None = None,
    fail_count: int = 0,
    loading_count: int = 0,
) -> RecordingPage:
    return RecordingPage(
        url=VIDEO_URL,
        selectors={
            PUBLISH: button if button is not None else _PublishButton(),
            VIDEO_FAIL: FakeLocator("video-fail", count=fail_count),
            VIDEO_LOADING_TEXT: FakeLocator(
                "video-loading-text", count=loading_count
            ),
            LOGIN_BOX: FakeLocator("login-box", count=0),
        },
    )


class VideoGateTests(unittest.TestCase):
    def _run(self, page, *, budget=None):
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout, dom):
            asyncio.run(
                xhs_main._video_upload_gate(
                    page, budget=budget or _budget(), mode="local"
                )
            )
        return clock

    def test_ready_button_completes_without_waiting_or_clicking(self):
        page = _video_page()
        clock = self._run(page)

        self.assertEqual(clock.sleep_calls, [])
        self.assertEqual(page.locator(PUBLISH).click_count, 0)

    def test_div_fail_aborts_immediately(self):
        page = _video_page(fail_count=1)
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout, dom):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(
                    xhs_main._video_upload_gate(
                        page, budget=_budget(), mode="local"
                    )
                )

        self.assertIn("div.fail", str(ctx.exception))
        self.assertIn("未点击发布", str(ctx.exception))
        self.assertEqual(clock.sleep_calls, [])

    def test_loading_text_aborts_immediately(self):
        page = _video_page(loading_count=1)
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout, dom):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(
                    xhs_main._video_upload_gate(
                        page, budget=_budget(), mode="local"
                    )
                )

        self.assertIn("video-container-loading-text", str(ctx.exception))
        self.assertIn("未点击发布", str(ctx.exception))
        self.assertEqual(clock.sleep_calls, [])

    def test_ready_window_is_clamped_to_six_hundred_seconds(self):
        page = _video_page(button=_PublishButton("disabled", enabled=False))
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout, dom):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(
                    xhs_main._video_upload_gate(
                        page, budget=_budget(), mode="local"
                    )
                )

        self.assertIn("600", str(ctx.exception))
        self.assertIn("未点击发布", str(ctx.exception))
        self.assertAlmostEqual(sum(clock.sleep_calls), 600.0)
        self.assertTrue(all(delay == 1.0 for delay in clock.sleep_calls))

    def test_ready_window_is_clamped_by_the_remaining_budget(self):
        page = _video_page(button=_PublishButton("disabled", enabled=False))
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout, dom):
            budget = _budget()
            budget.deadline = clock.monotonic() + 4.0
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(
                    xhs_main._video_upload_gate(
                        page, budget=budget, mode="local"
                    )
                )

        self.assertEqual(str(ctx.exception), str(budget.pre_click_error()))
        self.assertAlmostEqual(sum(clock.sleep_calls), 4.0)

    def test_video_gate_reuses_the_arm_predicate(self):
        # submit-disabled=true 是失败态的常态，不得当作就绪信号；
        # 谓词满足前必须一直等。
        button = _PublishButton("armed", enabled=True)
        button._attributes["submit-disabled"] = "true"
        page = _video_page(button=button)
        clock = FakeClock()
        with clock.patch(xhs_main, publish_timeout, dom):
            with self.assertRaises(RuntimeError):
                asyncio.run(
                    xhs_main._video_upload_gate(
                        page, budget=_budget(), mode="local"
                    )
                )

        self.assertAlmostEqual(sum(clock.sleep_calls), 600.0)


# ---------------------------------------------------------------------------
# 6. Zero keyword scanning / zero dead upload helpers
# ---------------------------------------------------------------------------


class NoKeywordScanningTests(unittest.TestCase):
    KEYWORDS = ("上传成功", "分辨率", "100%", "已上传", "已选择", "重新上传")
    HELPERS = (
        xhs_main._note_upload_gate,
        xhs_main._video_upload_gate,
        xhs_main._video_upload_failure,
        xhs_main._note_image_ready,
    )

    def test_module_has_no_upload_keyword_tables(self):
        source = Path(xhs_main.__file__).read_text(encoding="utf-8")
        for keyword in self.KEYWORDS:
            with self.subTest(keyword=keyword):
                self.assertNotIn(keyword, source)

    def test_gate_helpers_never_read_copy_or_scan_stages(self):
        for helper in self.HELPERS:
            source = inspect.getsource(helper)
            for needle in (
                "inner_text",
                "text_content",
                "query_selector_all",
                "div.stage",
            ):
                with self.subTest(helper=helper.__name__, needle=needle):
                    self.assertNotIn(needle, source)


if __name__ == "__main__":
    unittest.main()
