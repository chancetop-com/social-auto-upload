"""Instagram 协作者 CLI 边界（真实 Chrome 受控页 + ``sau``）。

覆盖解析、静态校验、结果打印/落盘、失败矩阵与退出码。共享页面夹具在
``tests/instagram_collaborators_fixtures.py``。
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from patchright.async_api import async_playwright

import sau_cli
from sau_commands import instagram as instagram_command
from uploader.meta_uploader.insgraph_uploader.main import InstagramUploader
from uploader.meta_uploader.insgraph_uploader.options import (
    ACCOUNT_INELIGIBLE,
    CONTROL_DISABLED,
    DEFAULT_OFF,
    EDITOR_OBSCURED,
    ENTRY_MISSING,
    FINAL_MISMATCH,
    LIST_NOT_COLLAPSED,
    MISMATCH,
    NO_CANDIDATES,
    NO_SAME_USERNAME,
    NOT_REQUESTED,
    SELECTION_FAILED,
    SET,
    UNSUPPORTED,
)
from tests.instagram_collaborators_fixtures import (
    FakeCollaboratorControl,
    collaborator_page_html,
    expire_budget_after_username,
    timeout_patches,
)
from utils.errors import PublishResultUnknownError


class InstagramCollaboratorControlledCliTests(unittest.TestCase):
    """CLI 边界：真实 Chrome 受控页 + ``sau`` 解析/校验/打印/落盘。"""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.image = self.folder / "image.png"
        self.image.touch()
        self.video = self.folder / "video.mp4"
        self.video.touch()

    def _run(
        self,
        *,
        html,
        collaborator_args=(),
        no_publish=True,
        action="upload-note",
        expire_after_selection=None,
        extra_args=(),
    ):
        holder: dict[str, object] = {}
        result_file = self.folder / f"result-{uuid4().hex}.json"

        async def fake_upload(request, *, target=None):
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel="chrome", headless=True)
                page = await browser.new_page()
                try:
                    await page.set_content(html)
                    app = InstagramUploader(
                        "unused.json",
                        title=request.title,
                        description=request.description,
                        tags=request.tags,
                        video_file=request.video_file,
                        image_files=[
                            str(path) for path in (request.image_files or [])
                        ],
                        thumbnail=request.thumbnail,
                        options=request.options,
                        no_publish=request.no_publish,
                        result_file=request.result_file,
                    )
                    budget = app.start_publish_budget()
                    monitor = None
                    if expire_after_selection is not None:
                        monitor = asyncio.create_task(
                            expire_budget_after_username(
                                page, budget, expire_after_selection
                            )
                        )
                    try:
                        await app._publish(
                            page,
                            {"user_id": "42", "username": "creator"},
                            budget=budget,
                        )
                    except Exception as error:
                        holder["error"] = error
                        raise
                    finally:
                        if monitor is not None:
                            monitor.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await monitor
                        holder["result"] = app.result
                        holder["share_clicks"] = int(
                            await page.locator("[data-share-clicks]")
                            .get_attribute("data-share-clicks") or 0
                        )
                        body = page.locator("body")
                        queries = await body.get_attribute("data-queries")
                        holder["queries"] = (
                            json.loads(queries) if queries else []
                        )
                        holder["entry_clicks"] = int(
                            await body.get_attribute("data-entry-clicks") or 0
                        )
                        holder["row_clicks"] = int(
                            await body.get_attribute("data-row-clicks") or 0
                        )
                        holder["done_clicks"] = int(
                            await body.get_attribute("data-done-clicks") or 0
                        )
                        holder["panel_hidden"] = bool(
                            await page.locator("#collab-panel").evaluate(
                                "el => el.hidden"
                            )
                        )
                finally:
                    await browser.close()
            return holder["result"]

        media = (
            ["--file", str(self.video)]
            if action == "upload-video"
            else ["--images", str(self.image)]
        )
        argv = [
            "instagram", action, "--account", "creator",
            "--title", "caption", *media,
            "--result", str(result_file), *collaborator_args,
            *extra_args,
        ]
        if no_publish:
            argv.append("--no-publish")
        stdout, stderr = io.StringIO(), io.StringIO()
        patches = timeout_patches()
        for item in patches:
            item.start()
        try:
            with patch.object(
                instagram_command, "upload_instagram_content", fake_upload
            ), patch.dict(
                os.environ,
                {
                    "HUMANIZE": "0",
                    "ADSPOWER_API_KEY": "",
                    "MLX_API_TOKEN": "",
                },
            ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
                stderr
            ):
                code = sau_cli.main(argv)
        finally:
            for item in patches:
                item.stop()
        saved = (
            json.loads(result_file.read_text(encoding="utf-8"))
            if result_file.exists()
            else None
        )
        return code, saved, holder, stdout.getvalue(), stderr.getvalue()

    def test_no_publish_success_prints_and_saves_the_same_payload(self):
        html = collaborator_page_html(
            [("alice", "Alice"), ("bob", "Bob")]
        )
        code, saved, holder, stdout, stderr = self._run(
            html=html,
            collaborator_args=(
                "--collaborator", "alice", "--collaborator", "@Bob"
            ),
        )
        self.assertEqual(code, 0, stderr)
        expected = {
            "requested": ["alice", "bob"],
            "applied": ["alice", "bob"],
            "status": SET,
        }
        self.assertEqual(saved["status"], "prepared")
        self.assertEqual(saved["options"]["collaborators"], expected)
        self.assertEqual(holder["share_clicks"], 0)
        self.assertEqual(json.loads(stdout), saved)

    def test_controlled_page_failure_exits_1_with_zero_share_clicks(self):
        html = collaborator_page_html([("_nikeza5", "nikeza")])
        code, saved, holder, stdout, stderr = self._run(
            html=html,
            collaborator_args=("--collaborator", "nike"),
            no_publish=False,
        )
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(holder["share_clicks"], 0)
        self.assertEqual(saved["status"], "not_submitted")
        self.assertEqual(
            saved["options"]["collaborators"],
            {
                "requested": ["nike"],
                "applied": [],
                "status": MISMATCH,
                "reason": NO_SAME_USERNAME,
            },
        )
        self.assertIn("no_same_username_candidate", stderr)

    def test_absent_flag_keeps_not_requested_and_never_touches_the_control(self):
        html = collaborator_page_html([("alice", "Alice")])
        code, saved, holder, stdout, stderr = self._run(html=html)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(
            saved["options"]["collaborators"],
            {"requested": None, "applied": None, "status": NOT_REQUESTED},
        )
        self.assertEqual(holder["share_clicks"], 0)
        self.assertEqual(holder["entry_clicks"], 0)
        self.assertEqual(holder["row_clicks"], 0)

    def test_upload_video_no_publish_success_prints_and_saves_the_same_payload(self):
        html = collaborator_page_html(
            [("alice", "Alice"), ("bob", "Bob")], render_chips=False
        )
        code, saved, holder, stdout, stderr = self._run(
            action="upload-video",
            html=html,
            collaborator_args=(
                "--collaborator", "alice", "--collaborator", "@Bob"
            ),
        )
        self.assertEqual(code, 0, stderr)
        expected = {
            "requested": ["alice", "bob"],
            "applied": ["alice", "bob"],
            "status": SET,
        }
        self.assertEqual(saved["status"], "prepared")
        self.assertEqual(saved["options"]["collaborators"], expected)
        self.assertEqual(holder["share_clicks"], 0)
        self.assertEqual(holder["row_clicks"], 2)
        self.assertEqual(holder["done_clicks"], 1)
        self.assertTrue(holder["panel_hidden"])
        self.assertEqual(json.loads(stdout), saved)
        for key in ("content_id", "post_id", "post_url", "schedule", "media_count"):
            self.assertNotIn(key, saved)

    def test_upload_video_controlled_failure_exits_1_with_zero_share_clicks(self):
        html = collaborator_page_html(
            [("_nikeza5", "nikeza")], render_chips=False
        )
        code, saved, holder, stdout, stderr = self._run(
            action="upload-video",
            html=html,
            collaborator_args=("--collaborator", "nike"),
            no_publish=False,
        )
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(holder["share_clicks"], 0)
        self.assertEqual(saved["status"], "not_submitted")
        self.assertEqual(
            saved["options"]["collaborators"],
            {
                "requested": ["nike"],
                "applied": [],
                "status": MISMATCH,
                "reason": NO_SAME_USERNAME,
            },
        )
        self.assertIn("no_same_username_candidate", stderr)

    def test_upload_video_panel_collapse_failure_exits_1_with_zero_share_clicks(self):
        html = collaborator_page_html(
            [("alice", "Alice"), ("bob", "Bob")],
            done_collapses=False,
            render_chips=False,
        )
        code, saved, holder, stdout, stderr = self._run(
            action="upload-video",
            html=html,
            collaborator_args=(
                "--collaborator", "alice", "--collaborator", "bob"
            ),
            no_publish=False,
        )
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(holder["share_clicks"], 0)
        self.assertEqual(saved["status"], "not_submitted")
        self.assertEqual(
            saved["options"]["collaborators"],
            {
                "requested": ["alice", "bob"],
                "applied": ["alice", "bob"],
                "status": MISMATCH,
                "reason": LIST_NOT_COLLAPSED,
            },
        )
        self.assertIn("list_not_collapsed", stderr)

    def test_upload_video_click_without_selection_exits_1_with_zero_share_clicks(self):
        html = collaborator_page_html(
            [("alice", "Alice")],
            row_click="ignore",
            render_chips=False,
        )
        code, saved, holder, stdout, stderr = self._run(
            action="upload-video",
            html=html,
            collaborator_args=("--collaborator", "alice"),
            no_publish=False,
        )
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(holder["share_clicks"], 0)
        self.assertEqual(saved["status"], "not_submitted")
        self.assertEqual(
            saved["options"]["collaborators"],
            {
                "requested": ["alice"],
                "applied": [],
                "status": MISMATCH,
                "reason": SELECTION_FAILED,
            },
        )
        self.assertIn("selection_failed", stderr)

    def test_failure_matrix_exits_1_with_zero_share_clicks(self):
        restricted = (
            '<div id="collaborator-restriction" role="alert">'
            "Cannot add collaborators to this account."
            "</div>"
        )
        cases = (
            dict(
                name="entry_missing",
                html=collaborator_page_html(
                    [("alice", "Alice")], entry="missing"
                ),
                requested=("alice",),
                applied=None,
                status=UNSUPPORTED,
                reason=ENTRY_MISSING,
                present_queries=(),
                absent_queries=("alice",),
                detail=None,
            ),
            dict(
                name="control_disabled",
                html=collaborator_page_html(
                    [("alice", "Alice")], entry="disabled"
                ),
                requested=("alice",),
                applied=None,
                status=UNSUPPORTED,
                reason=CONTROL_DISABLED,
                present_queries=(),
                absent_queries=("alice",),
                detail=None,
            ),
            dict(
                name="account_ineligible",
                html=collaborator_page_html(
                    [("alice", "Alice")], restriction=restricted
                ),
                requested=("alice",),
                applied=None,
                status=UNSUPPORTED,
                reason=ACCOUNT_INELIGIBLE,
                present_queries=(),
                absent_queries=("alice",),
                detail="Cannot add collaborators",
            ),
            dict(
                name="no_candidates",
                html=collaborator_page_html([]),
                requested=("alice", "bob"),
                applied=[],
                status=MISMATCH,
                reason=NO_CANDIDATES,
                present_queries=("alice",),
                absent_queries=("bob",),
                detail=None,
            ),
            dict(
                name="no_same_username_prefix",
                html=collaborator_page_html(
                    [("alice", "Alice"), ("_bobby", "Bobby")]
                ),
                requested=("alice", "bob", "carol"),
                applied=["alice"],
                status=MISMATCH,
                reason=NO_SAME_USERNAME,
                present_queries=("alice", "bob"),
                absent_queries=("carol",),
                detail=None,
            ),
            dict(
                name="selection_failed",
                html=collaborator_page_html(
                    [("alice", "Alice")], row_click="ignore"
                ),
                requested=("alice",),
                applied=[],
                status=MISMATCH,
                reason=SELECTION_FAILED,
                present_queries=("alice",),
                absent_queries=(),
                detail=None,
            ),
            dict(
                name="final_mismatch",
                html=collaborator_page_html(
                    [("alice", "Alice")], row_click="detach-entry"
                ),
                requested=("alice",),
                applied=None,
                status=MISMATCH,
                reason=FINAL_MISMATCH,
                present_queries=("alice",),
                absent_queries=(),
                detail=None,
            ),
            dict(
                name="list_not_collapsed",
                html=collaborator_page_html(
                    [("alice", "Alice"), ("bob", "Bob")],
                    done_collapses=False,
                ),
                requested=("alice", "bob"),
                applied=["alice", "bob"],
                status=MISMATCH,
                reason=LIST_NOT_COLLAPSED,
                present_queries=("alice", "bob"),
                absent_queries=(),
                detail=None,
            ),
            dict(
                name="editor_obscured",
                html=collaborator_page_html(
                    [("alice", "Alice")], obscured=True
                ),
                requested=("alice",),
                applied=None,
                status=MISMATCH,
                reason=EDITOR_OBSCURED,
                present_queries=(),
                absent_queries=("alice",),
                detail="遮挡",
            ),
            dict(
                name="done_missing",
                html=collaborator_page_html(
                    [("alice", "Alice")], done_label="Fertig"
                ),
                requested=("alice",),
                applied=["alice"],
                status=MISMATCH,
                reason=LIST_NOT_COLLAPSED,
                present_queries=("alice",),
                absent_queries=(),
                detail=None,
            ),
        )
        for action in ("upload-note", "upload-video"):
            for case in cases:
                with self.subTest(action=action, case=case["name"]):
                    collaborator_args = tuple(
                        value
                        for username in case["requested"]
                        for value in ("--collaborator", username)
                    )
                    code, saved, holder, stdout, stderr = self._run(
                        action=action,
                        html=case["html"],
                        collaborator_args=collaborator_args,
                        no_publish=False,
                    )
                    self.assertEqual(code, 1, stderr)
                    self.assertEqual(stdout, "")
                    self.assertEqual(holder["share_clicks"], 0)
                    self.assertNotIsInstance(
                        holder.get("error"), PublishResultUnknownError
                    )
                    self.assertEqual(saved["status"], "not_submitted")
                    record = saved["options"]["collaborators"]
                    expected = {
                        "requested": list(case["requested"]),
                        "applied": case["applied"],
                        "status": case["status"],
                        "reason": case["reason"],
                    }
                    for field, value in expected.items():
                        self.assertEqual(record[field], value)
                    # 只允许一个 reason；detail 是额外的取证字段。
                    self.assertEqual(
                        set(record) - set(expected) - {"detail"}, set()
                    )
                    if case["detail"]:
                        self.assertIn(case["detail"], record["detail"])
                    for username in case["present_queries"]:
                        self.assertIn(username, holder["queries"])
                    for username in case["absent_queries"]:
                        self.assertNotIn(username, holder["queries"])
                    for key in ("content_id", "post_id", "post_url"):
                        self.assertNotIn(key, saved)

    def test_mid_list_budget_exhaustion_exits_1_and_keeps_prefix(self):
        for action in ("upload-note", "upload-video"):
            with self.subTest(action=action):
                html = collaborator_page_html(
                    [("alice", "Alice"), ("bob", "Bob"), ("carol", "Carol")],
                    checkbox_delay_ms=250,
                    confirm_delay_ms=150,
                )
                code, saved, holder, stdout, stderr = self._run(
                    action=action,
                    html=html,
                    collaborator_args=(
                        "--collaborator", "alice",
                        "--collaborator", "bob",
                        "--collaborator", "carol",
                    ),
                    no_publish=False,
                    expire_after_selection="alice",
                )
                self.assertEqual(code, 1, stderr)
                self.assertEqual(stdout, "")
                self.assertEqual(holder["share_clicks"], 0)
                self.assertNotIsInstance(
                    holder.get("error"), PublishResultUnknownError
                )
                self.assertIn("15 分钟", stderr)
                self.assertEqual(saved["status"], "not_submitted")
                record = saved["options"]["collaborators"]
                self.assertEqual(
                    record["requested"], ["alice", "bob", "carol"]
                )
                self.assertEqual(record["applied"], ["alice"])
                self.assertEqual(record["status"], MISMATCH)
                self.assertNotIn("reason", record)
                self.assertIn("alice", holder["queries"])
                self.assertNotIn("bob", holder["queries"])
                self.assertNotIn("carol", holder["queries"])

    def test_option_result_unknown_maps_to_exit_1_not_9(self):
        holder: dict[str, object] = {}

        async def fake_upload(request, *, target=None):
            app = InstagramUploader(
                "unused.json",
                title=request.title,
                video_file=request.video_file,
                options=request.options,
                no_publish=request.no_publish,
                result_file=request.result_file,
            )
            try:
                await app._apply_options(
                    page=None,
                    budget=app.start_publish_budget(),
                    controls={
                        "collaborators": FakeCollaboratorControl(
                            [[]],
                            failure=PublishResultUnknownError("点击前不得未知"),
                        )
                    },
                )
            finally:
                holder["result"] = app.result
            return holder["result"]

        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(
            instagram_command, "upload_instagram_content", fake_upload
        ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
            stderr
        ):
            code = sau_cli.main([
                "instagram", "upload-video", "--account", "creator",
                "--title", "caption", "--file", str(self.video),
                "--collaborator", "alice", "--no-publish",
            ])
        self.assertEqual(code, 1)
        self.assertIn("发布选项未生效", stderr.getvalue())
        self.assertNotIn("发布结果未知", stderr.getvalue())

    def test_later_options_run_after_collaborator_failure_without_share_click(self):
        code, saved, holder, stdout, stderr = self._run(
            html=collaborator_page_html([("_nikeza5", "nikeza")]),
            collaborator_args=("--collaborator", "nike"),
            no_publish=False,
            extra_args=("--no-comments",),
        )
        self.assertEqual(code, 1, stderr)
        self.assertEqual(holder["share_clicks"], 0)
        self.assertEqual(saved["options"]["collaborators"]["status"], MISMATCH)
        # 协作者失败后其它键仍会尝试并被记录；聚合失败阻止 Share。
        self.assertEqual(
            saved["options"]["comments"]["status"], DEFAULT_OFF
        )
        self.assertEqual(
            saved["options"]["comments"]["reason"], ENTRY_MISSING
        )

    def test_upload_video_static_errors_exit_2_without_upload(self):
        cases = (
            ("empty", ["--collaborator", ""]),
            (
                "duplicate",
                ["--collaborator", "alice", "--collaborator", "@Alice"],
            ),
            (
                "six",
                ["--collaborator", "a", "--collaborator", "b",
                 "--collaborator", "c", "--collaborator", "d",
                 "--collaborator", "e", "--collaborator", "f"],
            ),
        )
        upload = AsyncMock()
        for case, collaborator_args in cases:
            with self.subTest(case=case), patch.object(
                instagram_command, "upload_instagram_content", upload
            ), contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                code = sau_cli.main([
                    "instagram", "upload-video", "--account", "creator",
                    "--title", "caption", "--file", str(self.video),
                    *collaborator_args,
                ])
                self.assertEqual(code, 2)
        upload.assert_not_awaited()
