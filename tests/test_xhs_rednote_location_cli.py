# -*- coding: utf-8 -*-
"""XHS/Rednote post-location CLI wiring and publish-flow placement (ticket 18).

* all four commands accept ``--location``; omitted is reported as not requested;
* an explicit empty/whitespace value exits ``2`` before the uploader is awaited;
* the success line reports request, clicked row (+ visible address) and final name;
* the location step runs inside all four publish flows before ``--no-publish``
  stops and before any publish click;
* ``--shoot-location`` stays the self-shot declaration field.
"""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

import sau_cli
from sau_commands import rednote as rednote_command
from sau_commands import xiaohongshu as xhs_command
from tests.fakes_xhs_dom import FakeLocator
from tests.test_xhs_metadata import VISIBLE_FACTS
from tests.test_xhs_submit import (
    _QuietHumanizer,
    _note_page,
    _video_page,
)
from uploader.rednote_uploader import main as rednote
from uploader.xiaohongshu_uploader import main as xhs

NOT_REQUESTED = "帖子地点：未请求（保留页面当前值）"
SUCCESS_SUMMARY = "素材已上传，发布前检查已通过"


class LocationCliReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.media = self.tmp / "media.png"
        self.media.write_bytes(b"media")

    def argv(self, platform, action, *extra):
        if action == "upload-video":
            media = ["--file", str(self.media)]
        else:
            media = ["--images", str(self.media)]
        return [
            platform,
            action,
            "--account",
            "creator",
            "--title",
            "标题",
            *media,
            "--no-publish",
            *extra,
        ]

    def command(self, platform, action):
        module = xhs_command if platform == "xiaohongshu" else rednote_command
        prefix = "xiaohongshu" if platform == "xiaohongshu" else "rednote"
        suffix = "video" if action == "upload-video" else "note"
        return module, f"upload_{prefix}_{suffix}"

    def run_cli(self, platform, action, *, extra=(), upload=None):
        module, name = self.command(platform, action)
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.object(module, name, new=upload or AsyncMock()),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = sau_cli.main(self.argv(platform, action, *extra))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_omitted_location_is_not_requested_and_uploader_keeps_none(self):
        for platform in ("xiaohongshu", "rednote"):
            for action in ("upload-video", "upload-note"):
                with self.subTest(platform=platform, action=action):
                    upload = AsyncMock()
                    code, out, err = self.run_cli(platform, action, upload=upload)
                    self.assertEqual(code, 0, err)
                    request = upload.call_args.args[0]
                    self.assertIsNone(request.location)
                    self.assertIn(NOT_REQUESTED, out)
                    self.assertIn(SUCCESS_SUMMARY, out)

    def test_blank_location_exits_2_before_upload(self):
        for platform in ("xiaohongshu", "rednote"):
            for action in ("upload-video", "upload-note"):
                for blank in ("", "   ", "\t\n"):
                    with self.subTest(
                        platform=platform, action=action, blank=repr(blank)
                    ):
                        upload = AsyncMock()
                        code, out, err = self.run_cli(
                            platform,
                            action,
                            extra=("--location", blank),
                            upload=upload,
                        )
                        self.assertEqual(code, 2, err)
                        self.assertIn("--location", err)
                        self.assertEqual(out, "")
                        upload.assert_not_awaited()

    def test_success_reports_request_clicked_row_address_and_final_name(self):
        async def upload(request, **kwargs):
            request.location_report = {
                "requested": "人民公园",
                "clicked_name": "人民公园",
                "address": "上海市黄浦区南京西路231号",
                "final_name": "人民公园",
                "status": "set",
            }

        for platform in ("xiaohongshu", "rednote"):
            for action in ("upload-video", "upload-note"):
                with self.subTest(platform=platform, action=action):
                    code, out, err = self.run_cli(
                        platform,
                        action,
                        extra=("--location", " 人民公园 "),
                        upload=upload,
                    )
                    self.assertEqual(code, 0, err)
                    self.assertIn(
                        "帖子地点：请求=人民公园，"
                        "所点行=人民公园 · 上海市黄浦区南京西路231号，"
                        "终值=人民公园，结果=已设置",
                        out,
                    )
                    self.assertIn(SUCCESS_SUMMARY, out)

    def test_name_only_row_reports_no_address(self):
        async def upload(request, **kwargs):
            request.location_report = {
                "requested": "人民公园",
                "clicked_name": "人民公园",
                "address": None,
                "final_name": "人民公园",
                "status": "set",
            }

        for platform in ("xiaohongshu", "rednote"):
            for action in ("upload-video", "upload-note"):
                with self.subTest(platform=platform, action=action):
                    code, out, err = self.run_cli(
                        platform,
                        action,
                        extra=("--location", "人民公园"),
                        upload=upload,
                    )
                    self.assertEqual(code, 0, err)
                    self.assertIn(
                        "帖子地点：请求=人民公园，"
                        "所点行=人民公园，终值=人民公园，结果=已设置",
                        out,
                    )

    def test_location_failure_exits_1_without_success_summary(self):
        failure = (
            "帖子地点设置失败：请求=人民公园，所点行=人民公园，终值=（空），"
            "原因=终值为空；尚未点击发布。"
        )

        async def upload(request, **kwargs):
            raise RuntimeError(failure)

        for platform in ("xiaohongshu", "rednote"):
            for action in ("upload-video", "upload-note"):
                with self.subTest(platform=platform, action=action):
                    code, out, err = self.run_cli(
                        platform,
                        action,
                        extra=("--location", "人民公园"),
                        upload=upload,
                    )
                    self.assertEqual(code, 1)
                    self.assertEqual(out, "")
                    self.assertIn("请求=人民公园", err)
                    self.assertIn("终值为空", err)
                    self.assertIn("尚未点击发布", err)
                    self.assertNotIn(SUCCESS_SUMMARY, out)

    def test_location_and_shoot_location_stay_separate_in_request_and_uploader(self):
        for platform in ("xiaohongshu", "rednote"):
            for action in ("upload-video", "upload-note"):
                with self.subTest(platform=platform, action=action):
                    upload = AsyncMock()
                    code, out, err = self.run_cli(
                        platform,
                        action,
                        extra=(
                            "--location",
                            "人民公园",
                            "--content-type",
                            "self-shot",
                            "--shoot-location",
                            "北京",
                            "--shoot-date",
                            "2026-11-20",
                        ),
                        upload=upload,
                    )
                    self.assertEqual(code, 0, err)
                    request = upload.call_args.args[0]
                    self.assertEqual(request.location, "人民公园")
                    self.assertEqual(request.shoot_location, "北京")
                    self.assertEqual(request.content_type, "self-shot")
                    command = (
                        xhs_command if platform == "xiaohongshu" else rednote_command
                    )
                    builder = (
                        command._build_video_uploader
                        if action == "upload-video"
                        else command._build_note_uploader
                    )
                    app = builder(request)
                    self.assertEqual(app.location, "人民公园")
                    self.assertEqual(app.shoot_location, "北京")


def _location_selectors(module, *, final="人民公园", collapse=True):
    row = FakeLocator(
        "location-row",
        computed_style=dict(VISIBLE_FACTS),
        wait_error=None if collapse else TimeoutError("candidate list stayed open"),
    )
    rows_locator = FakeLocator("location-rows", items=[row])
    rows_locator.evaluate_all = AsyncMock(
        return_value=[{"name": "人民公园", "address": "上海市黄浦区南京西路231号"}]
    )
    selectors = {
        ".option-name": FakeLocator("location-name"),
        ".option-subname:visible": FakeLocator("location-address"),
        module.XHS_LOCATION_CONTAINER_SELECTOR
        if module is xhs
        else module.REDNOTE_LOCATION_CONTAINER_SELECTOR: FakeLocator(
            "location-container", text=""
        ),
        module.XHS_LOCATION_ENTRY_SELECTOR
        if module is xhs
        else module.REDNOTE_LOCATION_ENTRY_SELECTOR: FakeLocator(
            "location-entry", computed_style=dict(VISIBLE_FACTS)
        ),
        module.XHS_LOCATION_ROW_SELECTOR
        if module is xhs
        else module.REDNOTE_LOCATION_ROW_SELECTOR: rows_locator,
        module.XHS_LOCATION_DISPLAY_SELECTOR
        if module is xhs
        else module.REDNOTE_LOCATION_DISPLAY_SELECTOR: FakeLocator(
            "location-display", text=final
        ),
    }
    return selectors, rows_locator, row


class LocationPublishFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(patch.dict(os.environ, {"HUMANIZE": "0"}))
        self.enterContext(
            patch.object(xhs, "XHS_LOCATION_INPUT_TIMEOUT_MS", 100)
        )
        self.enterContext(
            patch.object(xhs, "XHS_LOCATION_OPTION_TIMEOUT_MS", 100)
        )
        self.enterContext(
            patch.object(rednote, "REDNOTE_LOCATION_INPUT_TIMEOUT_MS", 100)
        )
        self.enterContext(
            patch.object(rednote, "REDNOTE_LOCATION_OPTION_TIMEOUT_MS", 100)
        )

    def _page(self, module, action, *, location=True, collapse=True):
        page = _video_page() if action == "video" else _note_page()
        if location:
            selectors, rows, row = _location_selectors(
                module, collapse=collapse
            )
            page._selectors.update(selectors)
        else:
            rows = row = None
        return page, rows, row

    def _app(self, module, action, **overrides):
        common = {
            "title": "标题",
            "tags": [],
            "publish_date": 0,
            "account_file": "a.json",
            "no_publish": True,
        }
        common.update(overrides)
        if module is xhs:
            if action == "video":
                return xhs.XiaoHongShuVideo(file_path="a.mp4", **common)
            return xhs.XiaoHongShuNote(image_paths=["a.png"], note="", **common)
        if action == "video":
            return rednote.RednoteVideo(file_path="a.mp4", **common)
        return rednote.RednoteNote(image_paths=["a.png"], note="", **common)

    async def _run(self, module, action, app, page, armed_reports):
        gate = "_video_upload_gate" if action == "video" else "_note_upload_gate"

        async def arm(*_args, **_kwargs):
            armed_reports.append(app.location_report)

        with ExitStack() as stack:
            stack.enter_context(
                patch.object(module, "_run_dom_quiet_gate", AsyncMock())
            )
            stack.enter_context(
                patch.object(module, "_clear_known_overlays", AsyncMock())
            )
            stack.enter_context(patch.object(module, gate, AsyncMock()))
            stack.enter_context(patch.object(module, "_wait_for_arm", new=arm))
            stack.enter_context(
                patch.object(
                    module, "_fire_publish", side_effect=AssertionError("unexpected publish")
                )
            )
            stack.enter_context(patch.object(module, "Humanizer", _QuietHumanizer))
            stack.enter_context(patch.object(app, "fill_meta", AsyncMock()))
            stack.enter_context(patch.object(app, "apply_declarations", AsyncMock()))
            if action == "video":
                stack.enter_context(patch.object(app, "set_thumbnail", AsyncMock()))
                await app.upload_video_content(page, mode="local")
            else:
                await app.upload_note_content(page, mode="local")

    async def test_location_runs_before_the_no_publish_stop_in_all_four_flows(self):
        for module, prefix in ((xhs, "xiaohongshu"), (rednote, "rednote")):
            for action in ("video", "note"):
                with self.subTest(platform=prefix, action=action):
                    page, _rows, row = self._page(module, action)
                    app = self._app(module, action, location="人民公园")
                    armed_reports = []
                    await self._run(module, action, app, page, armed_reports)
                    self.assertEqual(
                        app.location_report,
                        {
                            "requested": "人民公园",
                            "clicked_name": "人民公园",
                            "address": "上海市黄浦区南京西路231号",
                            "final_name": "人民公园",
                            "status": "set",
                        },
                    )
                    self.assertEqual(armed_reports, [app.location_report])
                    self.assertEqual(row.click_count, 1)
                    self.assertEqual(page.mouse.down_count, 0)
                    self.assertEqual(
                        page.locator("xhs-publish-btn").click_count, 0
                    )

    async def test_location_failure_stops_before_arm_and_publish_in_all_four_flows(self):
        for module, prefix in ((xhs, "xiaohongshu"), (rednote, "rednote")):
            for action in ("video", "note"):
                with self.subTest(platform=prefix, action=action):
                    page, _rows, row = self._page(module, action)
                    _rows.evaluate_all.return_value = [
                        {"name": "房山人民公园", "address": "北京市房山区"}
                    ]
                    app = self._app(module, action, location="人民公园", no_publish=False)
                    armed_reports = []
                    with self.assertRaisesRegex(RuntimeError, "无同名候选"):
                        await self._run(module, action, app, page, armed_reports)
                    self.assertEqual(armed_reports, [])
                    self.assertEqual(row.click_count, 0)
                    self.assertEqual(page.mouse.down_count, 0)
                    self.assertEqual(page.locator("xhs-publish-btn").click_count, 0)

    async def test_omitted_location_does_not_read_or_click_the_control(self):
        for module, prefix in ((xhs, "xiaohongshu"), (rednote, "rednote")):
            for action in ("video", "note"):
                with self.subTest(platform=prefix, action=action):
                    # The fail-loud fake has no location selector scripted: any
                    # read of the control raises UnscriptedSelectorError.
                    page, _rows, _row = self._page(module, action, location=False)
                    app = self._app(module, action)
                    armed_reports = []
                    await self._run(module, action, app, page, armed_reports)
                    self.assertIsNone(app.location_report)
                    self.assertEqual(armed_reports, [None])
                    self.assertEqual(page.mouse.down_count, 0)


if __name__ == "__main__":
    unittest.main()
