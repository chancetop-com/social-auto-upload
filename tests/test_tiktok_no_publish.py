# -*- coding: utf-8 -*-
"""TikTok ``--no-publish`` dry run: stop at the publish-ready point.

All tests are offline: in-memory page/locator doubles, no browser, no network.
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import sau_cli
from sau_commands.tiktok import (
    TiktokNoteUploadRequest,
    TiktokVideoUploadRequest,
    _build_note_uploader,
    _build_video_uploader,
)
from tests.fakes import FakePlaywright
from uploader.tk_uploader import main_chrome as tk_main
from uploader.tk_uploader.main_chrome import (
    TIKTOK_LAUNCH_KWARGS,
    TiktokNote,
    TiktokVideo,
)

DRY_RUN_LOG = "TikTok 发布就绪，--no-publish 停在发布按钮前（未点击发布）"


class _Button:
    """Publish button double; records every click."""

    def __init__(
        self,
        *,
        count: int = 1,
        enabled: bool = True,
        aria_disabled: str | None = None,
    ) -> None:
        self._count = count
        self._enabled = enabled
        self._aria_disabled = aria_disabled
        self.click_calls = 0

    @property
    def first(self):
        return self

    def nth(self, _index: int):
        return self

    async def count(self) -> int:
        return self._count

    async def is_visible(self) -> bool:
        return True

    async def is_enabled(self) -> bool:
        return self._enabled

    async def get_attribute(self, name: str):
        return self._aria_disabled if name == "aria-disabled" else None

    async def click(self) -> None:
        self.click_calls += 1


class _ButtonBase:
    def __init__(self, button: _Button) -> None:
        self.button = button

    def locator(self, _selector: str) -> _Button:
        return self.button

    def get_by_role(self, _role: str, name=None) -> _Button:
        return self.button


class _AdvancingClock:
    """Every read advances, so the bounded window is reached deterministically."""

    def __init__(self, step: float = 1.0) -> None:
        self.value = 0.0
        self.step = step

    def __call__(self) -> float:
        self.value += self.step
        return self.value


def _video(**kwargs) -> TiktokVideo:
    return TiktokVideo("标题", "/tmp/demo.mp4", [], 0, None, **kwargs)


def _note(**kwargs) -> TiktokNote:
    return TiktokNote(
        ["/tmp/cover.png"], "", [], 0, None, title=None, **kwargs
    )


class NoPublishArgumentTests(unittest.TestCase):
    def test_both_upload_actions_accept_the_flag(self):
        parser = sau_cli.build_parser()
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = Path(tmp_dir) / "demo.mp4"
            video.write_bytes(b"video")
            image = Path(tmp_dir) / "cover.png"
            image.write_bytes(b"image")

            video_args = parser.parse_args(
                [
                    "tiktok",
                    "upload-video",
                    "--file",
                    str(video),
                    "--title",
                    "hello",
                    "--no-publish",
                ]
            )
            note_args = parser.parse_args(
                [
                    "tiktok",
                    "upload-note",
                    "--images",
                    str(image),
                    "--no-publish",
                ]
            )

        self.assertTrue(video_args.no_publish)
        self.assertTrue(note_args.no_publish)

    def test_flag_defaults_to_false(self):
        parser = sau_cli.build_parser()
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = Path(tmp_dir) / "demo.mp4"
            video.write_bytes(b"video")
            args = parser.parse_args(
                [
                    "tiktok",
                    "upload-video",
                    "--file",
                    str(video),
                    "--title",
                    "hello",
                ]
            )
        self.assertFalse(args.no_publish)

    def test_help_text_matches_the_dry_run_contract(self):
        parser = sau_cli.build_parser()
        tiktok = parser._subparsers._group_actions[0].choices["tiktok"]
        action = next(
            choice
            for choice in tiktok._subparsers._group_actions[0].choices.values()
            if choice.prog == "sau tiktok upload-note"
        )
        option = next(
            action
            for action in action._actions
            if "--no-publish" in action.option_strings
        )
        self.assertEqual(
            option.help, "跑到发布就绪点即停止，不点击发布（回归测试用）"
        )


class NoPublishPlumbingTests(unittest.TestCase):
    def test_video_request_value_reaches_the_uploader(self):
        request = TiktokVideoUploadRequest(
            account_label=None,
            video_file=Path("demo.mp4"),
            title="hello",
            tags=[],
            publish_date=0,
            no_publish=True,
        )
        app = _build_video_uploader(request)
        self.assertTrue(app.no_publish)

    def test_note_request_value_reaches_the_uploader(self):
        request = TiktokNoteUploadRequest(
            account_label=None,
            image_files=[Path("cover.png")],
            note="hello",
            tags=[],
            publish_date=0,
            no_publish=True,
        )
        app = _build_note_uploader(request)
        self.assertTrue(app.no_publish)

    def test_uploaders_default_to_publishing(self):
        self.assertFalse(_video().no_publish)
        self.assertFalse(_note().no_publish)


class TiktokDryRunFlowTests(unittest.TestCase):
    def _install_form_hooks(self, app, order):
        def hook(name):
            async def record(*_args, **_kwargs):
                order.append(name)

            return record

        for name in (
            "open_upload_page",
            "attach_media",
            "fill_metadata",
            "wait_media_ready",
            "apply_cover",
            "apply_schedule",
        ):
            setattr(app, name, hook(name))

    def test_dry_run_does_all_form_work_then_stops_before_publish(self):
        order: list[str] = []
        video = _video(no_publish=True)
        video.locator_base = _ButtonBase(_Button())
        video.publish_not_before = datetime.now() + timedelta(hours=1)
        self._install_form_hooks(video, order)

        real_apply_options = video.apply_options

        async def record_apply_options(page):
            order.append("apply_options")
            await real_apply_options(page)

        video.apply_options = record_apply_options
        video.resolve_option_controls = AsyncMock(return_value=None)
        video.click_publish = AsyncMock()
        video.read_result = AsyncMock()

        not_before = AsyncMock(side_effect=AssertionError("dry run must skip"))
        with (
            patch(
                "uploader.publish_timeout.wait_until_publish_allowed",
                new=not_before,
            ),
            patch.object(tk_main.asyncio, "sleep", AsyncMock()),
        ):
            asyncio.run(
                video._upload_on_page(
                    object(), multilogin=False, budget=None
                )
            )

        self.assertEqual(
            order,
            [
                "open_upload_page",
                "attach_media",
                "fill_metadata",
                "wait_media_ready",
                "apply_options",
                "apply_cover",
                "apply_schedule",
            ],
        )
        video.click_publish.assert_not_awaited()
        video.read_result.assert_not_awaited()
        not_before.assert_not_awaited()

    def test_dry_run_logs_one_clear_line(self):
        app = _note(no_publish=True)
        app.locator_base = _ButtonBase(_Button())
        for name in (
            "open_upload_page",
            "attach_media",
            "fill_metadata",
            "wait_media_ready",
            "apply_options",
            "apply_cover",
            "apply_schedule",
        ):
            setattr(app, name, AsyncMock())
        app.click_publish = AsyncMock()
        app.read_result = AsyncMock()

        with (
            patch.object(tk_main.tiktok_logger, "success") as success,
            patch.object(tk_main.asyncio, "sleep", AsyncMock()),
        ):
            asyncio.run(
                app._upload_on_page(object(), multilogin=False, budget=None)
            )

        success.assert_called_once_with(DRY_RUN_LOG)
        app.click_publish.assert_not_awaited()
        app.read_result.assert_not_awaited()

    def test_dry_run_never_clicks_the_publish_button(self):
        video = _video(no_publish=True)
        button = _Button()
        video.locator_base = _ButtonBase(button)
        for name in (
            "open_upload_page",
            "attach_media",
            "fill_metadata",
            "wait_media_ready",
            "apply_options",
            "apply_cover",
            "apply_schedule",
        ):
            setattr(video, name, AsyncMock())

        with patch.object(tk_main.asyncio, "sleep", AsyncMock()):
            asyncio.run(
                video._upload_on_page(
                    object(), multilogin=False, budget=None
                )
            )

        self.assertEqual(button.click_calls, 0)

    def test_publish_still_runs_when_the_flag_is_absent(self):
        order: list[str] = []
        video = _video()
        video.locator_base = _ButtonBase(_Button())
        self._install_form_hooks(video, order)
        video.click_publish = AsyncMock()
        video.read_result = AsyncMock(return_value="123")

        asyncio.run(video._upload_on_page(object(), multilogin=False, budget=None))

        video.click_publish.assert_awaited_once()
        video.read_result.assert_awaited_once()

    def test_post_publish_link_read_failure_does_not_fail_the_run(self):
        # 发布点击已经成功；Content 列表读取失败只能告警，不能退出 1。
        video = _video()
        self._install_form_hooks(video, [])
        video.apply_options = AsyncMock()
        video.click_publish = AsyncMock()
        video.read_result = AsyncMock(
            side_effect=RuntimeError("Content 列表未找到链接")
        )

        with patch.object(tk_main.tiktok_logger, "warning") as warning:
            asyncio.run(
                video._upload_on_page(object(), multilogin=False, budget=None)
            )

        video.click_publish.assert_awaited_once()
        video.read_result.assert_awaited_once()
        self.assertIsNone(video.last_item_id)
        warning.assert_called_once()


class PublishReadyWaitTests(unittest.TestCase):
    def test_ready_button_returns_without_clicking(self):
        video = _video(no_publish=True)
        button = _Button()
        video.locator_base = _ButtonBase(button)

        with patch.object(tk_main.asyncio, "sleep", AsyncMock()) as sleep:
            asyncio.run(
                video.wait_publish_ready(object(), deadline=None, multilogin=False)
            )

        self.assertEqual(button.click_calls, 0)
        sleep.assert_not_awaited()

    def test_disabled_button_is_never_ready(self):
        video = _video(no_publish=True)
        button = _Button(enabled=False)
        video.locator_base = _ButtonBase(button)

        with (
            patch.object(tk_main, "TIKTOK_DRY_RUN_READY_TIMEOUT_MS", 0),
            patch.object(tk_main.asyncio, "sleep", AsyncMock()),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(
                    video.wait_publish_ready(
                        object(), deadline=None, multilogin=False
                    )
                )

        self.assertIn("未点击发布", str(ctx.exception))
        self.assertEqual(button.click_calls, 0)

    def test_aria_disabled_button_is_never_ready(self):
        video = _video(no_publish=True)
        button = _Button(aria_disabled="true")
        video.locator_base = _ButtonBase(button)

        with (
            patch.object(tk_main, "TIKTOK_DRY_RUN_READY_TIMEOUT_MS", 0),
            patch.object(tk_main.asyncio, "sleep", AsyncMock()),
        ):
            with self.assertRaises(RuntimeError):
                asyncio.run(
                    video.wait_publish_ready(
                        object(), deadline=None, multilogin=False
                    )
                )

    def test_missing_button_times_out_with_a_plain_runtime_error(self):
        video = _video(no_publish=True)
        video.locator_base = _ButtonBase(_Button(count=0))

        clock = _AdvancingClock()
        with (
            patch.object(tk_main, "TIKTOK_DRY_RUN_READY_TIMEOUT_MS", 3000),
            patch.object(tk_main, "time") as fake_time,
            patch.object(tk_main.asyncio, "sleep", AsyncMock()),
        ):
            fake_time.monotonic = clock
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(
                    video.wait_publish_ready(
                        object(), deadline=None, multilogin=False
                    )
                )

        message = str(ctx.exception)
        self.assertIn("未点击发布", message)
        self.assertIn("未发布", message)
        # A dedicated type would map to exit 9; this must be a plain failure.
        self.assertIs(type(ctx.exception), RuntimeError)

    def test_ready_gate_returns_the_locator_it_verified(self):
        video = _video(no_publish=True)
        button = _Button()
        video.locator_base = _ButtonBase(button)

        with patch.object(tk_main.asyncio, "sleep", AsyncMock()):
            ready = asyncio.run(
                video.wait_publish_ready(
                    object(), deadline=None, multilogin=False
                )
            )

        self.assertIs(ready, button)
        self.assertEqual(button.click_calls, 0)

    def test_window_is_clamped_by_the_remaining_budget(self):
        video = _video(no_publish=True)
        video.locator_base = _ButtonBase(_Button(count=0))
        budget = tk_main.PublishTimeoutBudget("TikTok")
        budget.deadline = 0.0  # exhausted

        with patch.object(tk_main.asyncio, "sleep", AsyncMock()):
            with self.assertRaises(RuntimeError):
                asyncio.run(
                    video.wait_publish_ready(
                        object(), deadline=budget, multilogin=False
                    )
                )


class DryRunLocalCookieTests(unittest.TestCase):
    def test_dry_run_clean_exit_rewrites_the_cookie(self):
        note = TiktokNote(
            ["/tmp/cover.png"],
            "",
            [],
            0,
            "/tmp/cookie.json",
            title=None,
            no_publish=True,
        )
        note.change_language = AsyncMock()
        note.locator_base = _ButtonBase(_Button())

        async def dry_upload(page, *, multilogin, budget):
            await note.wait_publish_ready(
                page, deadline=budget, multilogin=multilogin
            )

        note._upload_on_page = dry_upload
        playwright = FakePlaywright()

        with (
            patch.object(tk_main.asyncio, "sleep", AsyncMock()),
            patch.object(tk_main.time, "monotonic", return_value=1000.0),
        ):
            asyncio.run(note.upload(playwright))

        context = playwright.chromium.launch_browser.contexts[0]
        self.assertEqual(context.storage_state_calls, ["/tmp/cookie.json"])
        self.assertTrue(context.closed)
        self.assertEqual(
            playwright.chromium.launch_calls,
            [{"headless": True, **TIKTOK_LAUNCH_KWARGS}],
        )



def setUpModule():
    """Legacy TikTok fakes model the pre-humanize DOM seam.

    ``HUMANIZE=0`` is the semantic switch for exactly this: one ``insert_text``
    per text field and one ``locator.click`` per click.  The humanized
    behaviour itself is covered by ``tests/test_tiktok_humanize.py``.
    """
    import os

    os.environ["HUMANIZE"] = "0"


def tearDownModule():
    import os

    os.environ.pop("HUMANIZE", None)

if __name__ == "__main__":
    unittest.main()
