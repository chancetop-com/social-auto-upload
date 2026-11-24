"""Instagram 协作者（Collaborators）选项回归（A/B 层，零浏览器部分）。

覆盖三件事：

- 纯逻辑：归一化、静态校验、结果骨架/顺序/状态映射。
- fake 控制件：选项管线按顺序应用、失败保留已确认前缀、预算与结果落盘。
- CLI 边界：两个上传命令注册可重复 ``--collaborator``；``verify`` / ``delete``
  不注册；空值/重复/超过 5 个在启动浏览器前退出 2。

受控 DOM 与 CLI 真页面用例在同文件的后续测试类中；它们会启动系统 Chrome。
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from patchright.async_api import async_playwright

import sau_cli
from sau_commands import instagram as instagram_command
from uploader.meta_uploader.insgraph_uploader.controls import (
    collaborators as collaborators_control_module,
)
from uploader.meta_uploader.insgraph_uploader.controls.collaborators import (
    CollaboratorsControl,
)
from uploader.meta_uploader.insgraph_uploader.main import InstagramUploader
from uploader.meta_uploader.insgraph_uploader.options import (
    ACCOUNT_INELIGIBLE,
    APPLY_ORDER,
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
    OPTION_KEYS,
    PRESENT,
    SELECTION_FAILED,
    SET,
    UNSUPPORTED,
    UNAVAILABLE,
    InstagramPublishOptions,
    OptionMismatchError,
    empty_option_record,
    normalize_collaborator_name,
    normalize_collaborators,
    normalize_publish_options,
    option_failures,
    option_status,
    validate_publish_options,
)
from utils.errors import PublishResultUnknownError, UsageError


def _subparser(parser: argparse.ArgumentParser, platform: str, action: str):
    for item in parser._actions:
        if isinstance(item, argparse._SubParsersAction) and platform in item.choices:
            for nested in item.choices[platform]._actions:
                if isinstance(nested, argparse._SubParsersAction):
                    return nested.choices[action]
    raise AssertionError(f"parser not found: {platform}/{action}")


class InstagramCollaboratorNormalizationTests(unittest.TestCase):
    """A 层：trim、一个前导 @、小写；空值/重复/超过 5 个是 UsageError。"""

    def test_normalizes_trim_one_leading_at_and_lowercase(self):
        self.assertIsNone(normalize_collaborators(None))
        self.assertEqual(
            normalize_collaborators(("  @Alice ", "BOB", "@carol")),
            ("alice", "bob", "carol"),
        )
        # 直接构造上传器时误传裸字符串也按一个 username 处理，绝不拆成字符。
        self.assertEqual(normalize_collaborators(" @Alice "), ("alice",))
        self.assertEqual(normalize_collaborator_name("@Alice"), "alice")
        # 只去掉一个前导 @；第二个 @ 交给页面搜索，静态阶段不额外校验字符集。
        self.assertEqual(normalize_collaborator_name("@@Alice"), "@alice")
        self.assertEqual(normalize_collaborator_name("  Alice  "), "alice")

    def test_empty_values_are_usage_errors(self):
        for values in (("",), ("   ",), ("@",), ("alice", "\t")):
            with self.subTest(values=values), self.assertRaises(UsageError) as ctx:
                normalize_collaborators(values)
            self.assertIn("不能为空", str(ctx.exception))

    def test_normalized_duplicates_are_usage_errors_not_deduped(self):
        for values in (
            ("alice", "@Alice"),
            ("bob", "  BOB  "),
            ("alice", "bob", "@ALICE"),
        ):
            with self.subTest(values=values), self.assertRaises(UsageError) as ctx:
                normalize_collaborators(values)
            self.assertIn("重复", str(ctx.exception))
        self.assertEqual(
            normalize_collaborators(("Alice", "alice_2")), ("alice", "alice_2")
        )

    def test_more_than_five_is_a_usage_error(self):
        five = tuple(f"user{index}" for index in range(5))
        self.assertEqual(normalize_collaborators(five), five)
        with self.assertRaises(UsageError) as ctx:
            normalize_collaborators((*five, "user5"))
        message = str(ctx.exception)
        self.assertIn("5", message)
        self.assertIn("6", message)

    def test_normalize_publish_options_returns_a_normalized_copy(self):
        raw = InstagramPublishOptions(collaborators=(" @Alice ", "Bob"))
        normalized = normalize_publish_options(raw)
        self.assertEqual(normalized.collaborators, ("alice", "bob"))
        self.assertEqual(raw.collaborators, (" @Alice ", "Bob"))
        self.assertIsNone(normalize_publish_options(None))
        untouched = InstagramPublishOptions(location="Shanghai")
        self.assertIs(normalize_publish_options(untouched), untouched)


class InstagramCollaboratorResultTests(unittest.TestCase):
    """A 层：第五个键、requested/applied 形状与状态映射。"""

    def test_options_have_exactly_five_keys_in_stable_order(self):
        record = empty_option_record(None)
        self.assertEqual(
            OPTION_KEYS,
            ("location", "alt_text", "comments", "ai_generated", "collaborators"),
        )
        self.assertEqual(tuple(record), OPTION_KEYS)
        self.assertEqual(
            APPLY_ORDER,
            ("alt_text", "location", "collaborators", "ai_generated", "comments"),
        )
        for key in OPTION_KEYS:
            self.assertEqual(
                record[key],
                {"requested": None, "applied": None, "status": NOT_REQUESTED},
            )

    def test_requested_collaborators_are_a_normalized_list(self):
        record = empty_option_record(
            InstagramPublishOptions(
                collaborators=("alice", "bob"),
                location="Shanghai",
            )
        )
        self.assertEqual(record["collaborators"]["requested"], ["alice", "bob"])
        self.assertEqual(record["location"]["requested"], "Shanghai")

    def test_status_requires_the_full_ordered_sequence(self):
        cases = (
            (["alice", "bob"], ["alice", "bob"], SET),
            (["alice", "bob"], ["alice"], MISMATCH),
            (["alice"], [], MISMATCH),
            (["alice"], None, MISMATCH),
            (("alice", "bob"), ["bob", "alice"], MISMATCH),
        )
        for requested, applied, expected in cases:
            with self.subTest(requested=requested, applied=applied):
                status, reason = option_status(
                    requested, applied, kind="value"
                )
                self.assertEqual(status, expected)
                self.assertIsNone(reason)

    def test_presence_failures_map_to_unsupported_reasons(self):
        cases = (
            (ENTRY_MISSING, "missing"),
            (ACCOUNT_INELIGIBLE, "ineligible"),
            (CONTROL_DISABLED, UNAVAILABLE),
        )
        for reason, presence in cases:
            with self.subTest(reason=reason):
                status, observed = option_status(
                    ["alice"], None, kind="value", presence=presence
                )
                self.assertEqual(status, UNSUPPORTED)
                self.assertEqual(observed, reason)

    def test_failure_list_uses_the_new_username_reason(self):
        record = empty_option_record(
            InstagramPublishOptions(collaborators=("alice", "bob"))
        )
        record["collaborators"].update(
            status=MISMATCH, reason=NO_SAME_USERNAME, applied=["alice"]
        )
        self.assertEqual(
            option_failures(record),
            ["collaborators=mismatch(no_same_username_candidate)"],
        )


class InstagramCollaboratorValidationTests(unittest.TestCase):
    """A 层：静态校验与直接构造上传器都复用同一归一化实现。"""

    def test_validate_publish_options_rejects_empty_and_duplicate_values(self):
        for collaborators in (("",), ("alice", "@Alice"), ("a", "b", "c", "d", "e", "f")):
            with self.subTest(collaborators=collaborators), self.assertRaises(UsageError):
                validate_publish_options(
                    InstagramPublishOptions(collaborators=collaborators),
                    image_count=1,
                    caption="caption",
                )
        validate_publish_options(
            InstagramPublishOptions(collaborators=("alice",)),
            image_count=1,
            caption="caption",
        )

    def test_direct_uploader_construction_normalizes_collaborators(self):
        with tempfile.TemporaryDirectory() as folder:
            app = InstagramUploader(
                "unused.json",
                title="caption",
                image_files=[str(Path(folder) / "image.png")],
                options=InstagramPublishOptions(
                    collaborators=(" @Alice ", "BOB")
                ),
                result_file=Path(folder) / "result.json",
            )
        self.assertEqual(app.options.collaborators, ("alice", "bob"))
        self.assertEqual(
            app.result["options"]["collaborators"],
            {
                "requested": ["alice", "bob"],
                "applied": None,
                "status": NOT_REQUESTED,
            },
        )

    def test_direct_uploader_construction_rejects_invalid_collaborators(self):
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(UsageError):
            InstagramUploader(
                "unused.json",
                title="caption",
                image_files=[str(Path(folder) / "image.png")],
                options=InstagramPublishOptions(collaborators=("@alice", "alice")),
                result_file=Path(folder) / "result.json",
            )


class _FakeReadEntry:
    """最小入口 locator：只回答 ``read()`` 的探测需要。"""

    def __init__(self, rows=None, *, error=None):
        self.rows = rows
        self.error = error

    async def wait_for(self, *, state, timeout):
        return None

    async def count(self):
        return 1

    async def is_visible(self):
        return True

    async def evaluate(self, script, arg=None):
        if self.error is not None:
            raise self.error
        return self.rows


class _FakeReadLocator:
    def __init__(self, entry):
        self._entry = entry

    @property
    def first(self):
        return self._entry


class _FakeReadDialog:
    def __init__(self, entry):
        self._entry = entry

    def locator(self, selector):
        return _FakeReadLocator(self._entry)


class _FakeReadPage:
    def __init__(self, entry):
        self._entry = entry

    def get_by_role(self, role):
        return _FakeReadDialog(self._entry)


class InstagramCollaboratorControlReadTests(unittest.IsolatedAsyncioTestCase):
    """Reels 的 ``read()`` 必须区分“可读且为空”和“读不到”。"""

    def _control(self, entry):
        return CollaboratorsControl(_FakeReadPage(entry), image_count=0)

    async def test_unreadable_checkbox_state_is_none_not_an_empty_list(self):
        control = self._control(
            _FakeReadEntry(error=RuntimeError("checkbox query failed"))
        )
        self.assertIsNone(await control.read())

    async def test_readable_panel_without_selected_rows_is_an_empty_list(self):
        control = self._control(_FakeReadEntry(rows=[]))
        self.assertEqual(await control.read(), [])


class _FakeCollaboratorControl:
    """最小协作者控制件替身：预置 read 序列，可选在 set 时抛错。"""

    def __init__(self, read_values, *, presence=PRESENT, failure=None):
        self._values = list(read_values)
        self.presence = presence
        self.failure = failure
        self.interactions = []

    async def resolve(self):
        self.interactions.append("resolve")
        return self.presence

    async def read(self):
        self.interactions.append("read")
        if not self._values:
            return None
        return self._values.pop(0) if len(self._values) > 1 else self._values[0]

    async def set(self, requested):
        self.interactions.append(("set", list(requested)))
        if self.failure is not None:
            raise self.failure


class _ExplodingControl:
    async def resolve(self):
        raise AssertionError("未请求的选项不应被 resolve")

    async def read(self):
        raise AssertionError("未请求的选项不应被 read")

    async def set(self, requested):
        raise AssertionError("未请求的选项不应被 set")


class InstagramCollaboratorPipelineTests(unittest.TestCase):
    """B 层：复用 ``_apply_options(controls=...)``，不引入新接缝。"""

    def _app(self, options, *, folder):
        return InstagramUploader(
            "unused.json",
            title="caption",
            image_files=[str(Path(folder) / "image.png")],
            options=options,
            result_file=Path(folder) / "result.json",
        )

    def _apply(self, app, controls, *, budget=None):
        return asyncio.run(
            app._apply_options(
                page=None,
                budget=budget or app.start_publish_budget(),
                controls=controls,
            )
        )

    def test_success_records_applied_usernames_in_request_order(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(
                InstagramPublishOptions(collaborators=("alice", "bob")),
                folder=folder,
            )
            control = _FakeCollaboratorControl([[], ["alice", "bob"]])
            self._apply(app, {"collaborators": control})
            expected = {
                "requested": ["alice", "bob"],
                "applied": ["alice", "bob"],
                "status": SET,
            }
            self.assertEqual(app.result["options"]["collaborators"], expected)
            self.assertEqual(
                control.interactions,
                ["resolve", "read", ("set", ["alice", "bob"]), "read"],
            )
            saved = json.loads(Path(app.result_file).read_text(encoding="utf-8"))
            self.assertEqual(saved["options"]["collaborators"], expected)
            self.assertEqual(tuple(saved["options"]), OPTION_KEYS)

    def test_declared_mismatch_keeps_the_confirmed_prefix(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(
                InstagramPublishOptions(
                    collaborators=("alice", "bob", "carol"), comments=False
                ),
                folder=folder,
            )
            control = _FakeCollaboratorControl(
                [[]],
                failure=OptionMismatchError(
                    "Instagram 协作者没有同 username 候选：请求「bob」",
                    applied=["alice"],
                    reason=NO_SAME_USERNAME,
                ),
            )
            comments = _FakeCollaboratorControl([False])
            with self.assertRaises(RuntimeError) as ctx:
                self._apply(
                    app, {"collaborators": control, "comments": comments}
                )
            message = str(ctx.exception)
            self.assertIn("collaborators=mismatch(no_same_username_candidate)", message)
            self.assertEqual(
                app.result["options"]["collaborators"],
                {
                    "requested": ["alice", "bob", "carol"],
                    "applied": ["alice"],
                    "status": MISMATCH,
                    "reason": NO_SAME_USERNAME,
                },
            )
            # 协作者失败不阻止后续选项按键继续尝试，但最终聚合错误阻止 Share。
            self.assertEqual(comments.interactions, ["resolve", "read"])

    def test_missing_and_disabled_entries_are_unsupported(self):
        cases = (
            ("missing", ENTRY_MISSING),
            ("ineligible", ACCOUNT_INELIGIBLE),
            ("unavailable", CONTROL_DISABLED),
        )
        for presence, reason in cases:
            with self.subTest(presence=presence), tempfile.TemporaryDirectory() as folder:
                app = self._app(
                    InstagramPublishOptions(collaborators=("alice",)),
                    folder=folder,
                )
                control = _FakeCollaboratorControl([], presence=presence)
                with self.assertRaisesRegex(
                    RuntimeError, rf"collaborators=unsupported\({reason}\)"
                ):
                    self._apply(app, {"collaborators": control})
                self.assertEqual(control.interactions, ["resolve"])
                self.assertEqual(
                    app.result["options"]["collaborators"],
                    {
                        "requested": ["alice"],
                        "applied": None,
                        "status": UNSUPPORTED,
                        "reason": reason,
                    },
                )

    def test_panel_collapse_failure_keeps_all_confirmed_names(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(
                InstagramPublishOptions(collaborators=("alice", "bob")),
                folder=folder,
            )
            control = _FakeCollaboratorControl(
                [[]],
                failure=OptionMismatchError(
                    "Instagram 协作者面板未收起",
                    applied=["alice", "bob"],
                    reason=LIST_NOT_COLLAPSED,
                ),
            )
            with self.assertRaisesRegex(
                RuntimeError, "collaborators=mismatch\\(list_not_collapsed\\)"
            ):
                self._apply(app, {"collaborators": control})
            self.assertEqual(
                app.result["options"]["collaborators"]["applied"],
                ["alice", "bob"],
            )

    def test_spent_budget_aborts_before_touching_collaborators(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(
                InstagramPublishOptions(collaborators=("alice",)),
                folder=folder,
            )
            budget = app.start_publish_budget()
            budget.deadline = time.monotonic() - 1
            control = _FakeCollaboratorControl([[]])
            with self.assertRaisesRegex(RuntimeError, "15 分钟"):
                asyncio.run(
                    app._apply_options(
                        page=None, budget=budget,
                        controls={"collaborators": control},
                    )
                )
            self.assertEqual(control.interactions, [])
            self.assertFalse(app.publish_clicked)

    def test_mid_list_budget_exhaustion_persists_the_confirmed_prefix(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(
                InstagramPublishOptions(collaborators=("alice", "bob")),
                folder=folder,
            )
            budget = app.start_publish_budget()
            control = _FakeCollaboratorControl([[]])

            async def set_then_exhaust(requested):
                # 控件在确认 alice 后耗尽预算：此刻必须保留已确认前缀。
                budget.deadline = time.monotonic() - 1
                raise OptionMismatchError(
                    "Instagram 协作者在添加「bob」前中止："
                    f"{budget.pre_click_error()}",
                    applied=["alice"],
                )

            control.set = set_then_exhaust
            with self.assertRaises(RuntimeError) as ctx:
                self._apply(app, {"collaborators": control}, budget=budget)
            self.assertNotIsInstance(ctx.exception, PublishResultUnknownError)
            self.assertIn("15 分钟", str(ctx.exception))
            saved = json.loads(
                Path(app.result_file).read_text(encoding="utf-8")
            )
            self.assertEqual(
                saved["options"]["collaborators"],
                {
                    "requested": ["alice", "bob"],
                    "applied": ["alice"],
                    "status": MISMATCH,
                },
            )
            self.assertFalse(app.publish_clicked)

    def test_result_unknown_during_set_is_converted_to_plain_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(
                InstagramPublishOptions(collaborators=("alice",)),
                folder=folder,
            )
            control = _FakeCollaboratorControl(
                [[]],
                failure=PublishResultUnknownError("模拟点击前未知"),
            )
            with self.assertRaises(RuntimeError) as ctx:
                self._apply(app, {"collaborators": control})
            self.assertNotIsInstance(ctx.exception, PublishResultUnknownError)
            self.assertIn("collaborators", str(ctx.exception))
            self.assertFalse(app.publish_clicked)

    def test_not_requested_collaborators_touch_no_control(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(None, folder=folder)
            controls = {key: _ExplodingControl() for key in OPTION_KEYS}
            self._apply(app, controls)
            self.assertEqual(
                app.result["options"]["collaborators"],
                {"requested": None, "applied": None, "status": NOT_REQUESTED},
            )
            self.assertFalse(Path(app.result_file).exists())


class InstagramReelsCollaboratorPipelineTests(unittest.TestCase):
    """B 层（Reels/视频）：选项管线记录逐个回读结果、失败前缀且不点 Share。"""

    def _app(self, options, *, folder):
        video = Path(folder) / "video.mp4"
        video.touch()
        return InstagramUploader(
            "unused.json",
            title="caption",
            video_file=video,
            options=options,
            result_file=Path(folder) / "result.json",
        )

    def _apply(self, app, control, *, budget=None):
        return asyncio.run(
            app._apply_options(
                page=None,
                budget=budget or app.start_publish_budget(),
                controls={"collaborators": control},
            )
        )

    def test_reels_checkbox_readback_list_is_recorded_in_request_order(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(
                InstagramPublishOptions(collaborators=("alice", "bob")),
                folder=folder,
            )
            control = _FakeCollaboratorControl([[], ["alice", "bob"]])
            self._apply(app, control)
            self.assertEqual(
                app.result["options"]["collaborators"],
                {
                    "requested": ["alice", "bob"],
                    "applied": ["alice", "bob"],
                    "status": SET,
                },
            )
            self.assertEqual(
                control.interactions,
                ["resolve", "read", ("set", ["alice", "bob"]), "read"],
            )
            saved = json.loads(
                Path(app.result_file).read_text(encoding="utf-8")
            )
            self.assertEqual(saved["options"]["collaborators"]["applied"],
                             ["alice", "bob"])
            self.assertFalse(app.publish_clicked)

    def test_reels_selection_failure_stops_and_preserves_the_prefix(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(
                InstagramPublishOptions(
                    collaborators=("alice", "bob", "carol")
                ),
                folder=folder,
            )
            control = _FakeCollaboratorControl(
                [[]],
                failure=OptionMismatchError(
                    "Instagram 协作者点击后未选中：请求「bob」",
                    applied=["alice"],
                    reason=SELECTION_FAILED,
                ),
            )
            with self.assertRaises(RuntimeError) as ctx:
                self._apply(app, control)
            self.assertIn(
                "collaborators=mismatch(selection_failed)",
                str(ctx.exception),
            )
            self.assertEqual(
                app.result["options"]["collaborators"],
                {
                    "requested": ["alice", "bob", "carol"],
                    "applied": ["alice"],
                    "status": MISMATCH,
                    "reason": SELECTION_FAILED,
                },
            )
            self.assertEqual(
                control.interactions,
                ["resolve", "read", ("set", ["alice", "bob", "carol"])],
            )
            self.assertFalse(app.publish_clicked)

    def test_reels_unreadable_readback_records_final_mismatch_with_null_applied(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(
                InstagramPublishOptions(collaborators=("alice",)),
                folder=folder,
            )
            control = _FakeCollaboratorControl(
                [[]],
                failure=OptionMismatchError(
                    "Instagram 协作者回读不一致：请求「alice」",
                    applied=None,
                    reason=FINAL_MISMATCH,
                ),
            )
            with self.assertRaisesRegex(
                RuntimeError, "collaborators=mismatch\\(final_mismatch\\)"
            ):
                self._apply(app, control)
            self.assertEqual(
                app.result["options"]["collaborators"],
                {
                    "requested": ["alice"],
                    "applied": None,
                    "status": MISMATCH,
                    "reason": FINAL_MISMATCH,
                },
            )
            self.assertFalse(app.publish_clicked)

    def test_reels_done_failure_keeps_all_confirmed_names(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(
                InstagramPublishOptions(collaborators=("alice", "bob")),
                folder=folder,
            )
            control = _FakeCollaboratorControl(
                [[]],
                failure=OptionMismatchError(
                    "Instagram 协作者面板未收起",
                    applied=["alice", "bob"],
                    reason=LIST_NOT_COLLAPSED,
                ),
            )
            with self.assertRaisesRegex(
                RuntimeError, "collaborators=mismatch\\(list_not_collapsed\\)"
            ):
                self._apply(app, control)
            self.assertEqual(
                app.result["options"]["collaborators"]["applied"],
                ["alice", "bob"],
            )
            self.assertFalse(app.publish_clicked)

    def test_reels_budget_exhausted_before_the_option_touches_no_control(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self._app(
                InstagramPublishOptions(collaborators=("alice",)),
                folder=folder,
            )
            budget = app.start_publish_budget()
            budget.deadline = time.monotonic() - 1
            control = _FakeCollaboratorControl([[]])
            with self.assertRaisesRegex(RuntimeError, "15 分钟"):
                self._apply(app, control, budget=budget)
            self.assertEqual(control.interactions, [])
            self.assertFalse(app.publish_clicked)


class InstagramCollaboratorParserTests(unittest.TestCase):
    """CLI：两个上传命令都可重复注册；核对/删除命令不暴露该参数。"""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.video = self.folder / "video.mp4"
        self.video.touch()
        self.image = self.folder / "image.png"
        self.image.touch()

    def _parse(self, argv):
        return sau_cli.build_parser().parse_args(["instagram", *argv])

    def test_both_upload_commands_register_repeatable_flag(self):
        for action, media in (
            ("upload-video", ("--file", str(self.video))),
            ("upload-note", ("--images", str(self.image))),
        ):
            with self.subTest(action=action):
                args = self._parse(
                    [action, "--title", "caption", *media,
                     "--collaborator", "alice", "--collaborator", "@Bob"]
                )
                self.assertEqual(args.collaborator, ["alice", "@Bob"])
                args = self._parse(
                    [action, "--title", "caption", *media]
                )
                self.assertIsNone(args.collaborator)

    def test_verify_and_delete_do_not_register_the_flag(self):
        parser = sau_cli.build_parser()
        for action in ("verify", "delete"):
            with self.subTest(action=action):
                action_parser = _subparser(parser, "instagram", action)
                self.assertNotIn(
                    "--collaborator", action_parser._option_string_actions
                )

    def test_build_publish_options_normalizes_and_preserves_absence(self):
        args = SimpleNamespace(collaborator=[" @Alice ", "BOB"])
        self.assertEqual(
            instagram_command._build_publish_options(args),
            InstagramPublishOptions(collaborators=("alice", "bob")),
        )
        self.assertIsNone(
            instagram_command._build_publish_options(SimpleNamespace())
        )


class InstagramCollaboratorStaticErrorCliTests(unittest.TestCase):
    """CLI：空值/重复/超过 5 个在浏览器和上传启动前退出 2。"""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.video = self.folder / "video.mp4"
        self.video.touch()
        self.image = self.folder / "image.png"
        self.image.touch()

    def test_invalid_collaborator_lists_exit_2_without_upload(self):
        cases = (
            ("empty", ["--collaborator", ""]),
            ("duplicate", ["--collaborator", "alice", "--collaborator", "@Alice"]),
            (
                "six",
                ["--collaborator", "a", "--collaborator", "b",
                 "--collaborator", "c", "--collaborator", "d",
                 "--collaborator", "e", "--collaborator", "f"],
            ),
        )
        upload = AsyncMock()
        for action, media in (
            ("upload-video", ["--file", str(self.video)]),
            ("upload-note", ["--images", str(self.image)]),
        ):
            for case, collaborator_args in cases:
                with self.subTest(action=action, case=case), patch.object(
                    instagram_command, "upload_instagram_content", upload
                ), contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(io.StringIO()):
                    code = sau_cli.main([
                        "instagram", action, "--account", "creator",
                        "--title", "caption", *media, *collaborator_args,
                    ])
                    self.assertEqual(code, 2)
        upload.assert_not_awaited()

    def test_collaborator_absent_keeps_legacy_options_path(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as media:
            args = sau_cli.build_parser().parse_args([
                "instagram", "upload-note", "--images", media.name,
                "--title", "caption",
            ])
        self.assertIsNone(instagram_command._build_publish_options(args))


_COLLABORATOR_PAGE = """
<div role="dialog" id="compose">
  <div role="heading" aria-level="1">Create new post</div>
  <div data-share-clicks="0"></div>
  __ENTRY__
  __RESTRICTION__
  <div id="chips"></div>
  <div id="collab-panel" hidden>
    <div id="collab-results"></div>
    <div role="button" id="collab-done">__DONE_LABEL__</div>
  </div>
  <div role="textbox" contenteditable="true" data-lexical-editor="true"></div>
  <div role="button" id="share"
       onclick="const holder=document.querySelector('[data-share-clicks]');
                holder.dataset.shareClicks=String(Number(holder.dataset.shareClicks||0)+1);">Share</div>
</div>
<script>
  const candidates = __CANDIDATES__;
  const selected = __PRESELECT__;
  const rowClick = __ROW_CLICK__;
  const doneCollapses = __DONE_COLLAPSES__;
  const renderChipNodes = __RENDER_CHIPS__;
  const valueAfterFive = __VALUE_AFTER_FIVE__;
  const checkboxDelayMs = __CHECKBOX_DELAY_MS__;
  const entry = document.getElementById('collab-entry');
  const panel = document.getElementById('collab-panel');
  const results = document.getElementById('collab-results');
  const chips = document.getElementById('chips');
  const done = document.getElementById('collab-done');
  function checkedNames() {
    const names = [];
    for (const candidate of candidates) {
      if (selected.includes(candidate.username) &&
          !names.includes(candidate.username)) {
        names.push(candidate.username);
      }
    }
    return names;
  }
  function recordSelection() {
    document.body.dataset.selected = JSON.stringify(selected);
  }
  function openPanel() {
    if (!panel) return;
    panel.hidden = false;
    renderResults();
  }
  function renderChips() {
    if (!chips) return;
    chips.innerHTML = '';
    if (!renderChipNodes) return;
    for (const username of selected) {
      const outer = document.createElement('span');
      const name = document.createElement('span');
      name.textContent = username;
      const closeWrap = document.createElement('div');
      const close = document.createElement('div');
      close.setAttribute('role', 'button');
      close.innerHTML = '<svg aria-label="Close" width="10" height="10"></svg>';
      closeWrap.appendChild(close);
      outer.appendChild(name);
      outer.appendChild(closeWrap);
      chips.appendChild(outer);
    }
  }
  function renderResults() {
    if (!results) return;
    results.innerHTML = '';
    const query = String(entry && entry.value || '').trim().toLowerCase();
    for (const candidate of candidates) {
      if (!candidate.username.toLowerCase().includes(query)) continue;
      const row = document.createElement('div');
      row.setAttribute('role', 'button');
      row.dataset.username = candidate.username;
      row.style.cssText = 'display:flex;height:48px;width:300px;align-items:center;gap:8px';
      const username = document.createElement('span');
      username.textContent = candidate.username;
      const display = document.createElement('span');
      display.textContent = candidate.display;
      const box = document.createElement('input');
      box.type = 'checkbox';
      box.checked = selected.includes(candidate.username);
      box.setAttribute('aria-checked', String(box.checked));
      row.appendChild(username);
      row.appendChild(display);
      row.appendChild(box);
      row.addEventListener('click', () => {
        document.body.dataset.rowClicks = String(
          Number(document.body.dataset.rowClicks || 0) + 1);
        document.body.dataset.clickedUsername = candidate.username;
        document.body.dataset.clickedIndex = String(candidates.indexOf(candidate));
        if (rowClick === 'detach-entry') {
          // 模拟点击后回读通道消失：输入框被摘除，后续 evaluate 无法解析。
          if (entry) entry.remove();
          return;
        }
        if (rowClick !== 'select') return;
        const toggle = () => {
          const index = selected.indexOf(candidate.username);
          if (index >= 0) {
            selected.splice(index, 1);
          } else if (selected.length < 5) {
            selected.push(candidate.username);
          }
          box.checked = selected.includes(candidate.username);
          box.setAttribute('aria-checked', String(box.checked));
          document.body.dataset.checkedRowCount = String(
            results.querySelectorAll('input[type="checkbox"]:checked').length);
          const states = JSON.parse(
            document.body.dataset.checkboxStates || '[]');
          states.push({
            username: candidate.username,
            checked: box.checked,
            aria: box.getAttribute('aria-checked'),
          });
          document.body.dataset.checkboxStates = JSON.stringify(states);
          renderChips();
          recordSelection();
          if (selected.length >= 5 && entry) entry.value = valueAfterFive;
        };
        if (checkboxDelayMs > 0) {
          setTimeout(toggle, checkboxDelayMs);
        } else {
          toggle();
        }
      });
      results.appendChild(row);
    }
  }
  document.addEventListener('focusin', (event) => {
    if (event.target && event.target.id) {
      document.body.dataset.focusedEntry = event.target.id;
    }
  });
  if (entry) {
    entry.addEventListener('click', () => {
      document.body.dataset.entryClicks = String(
        Number(document.body.dataset.entryClicks || 0) + 1);
      openPanel();
    });
    entry.addEventListener('focus', openPanel);
    entry.addEventListener('input', () => {
      const progress = JSON.parse(document.body.dataset.progress || '[]');
      if (!progress.length ||
          progress[progress.length - 1].query !== entry.value) {
        progress.push({query: entry.value, checked: checkedNames()});
        document.body.dataset.progress = JSON.stringify(progress);
      }
      const queries = JSON.parse(document.body.dataset.queries || '[]');
      queries.push(entry.value);
      document.body.dataset.queries = JSON.stringify(queries);
      renderResults();
    });
  }
  if (done) {
    done.addEventListener('click', () => {
      document.body.dataset.doneClicks = String(
        Number(document.body.dataset.doneClicks || 0) + 1);
      if (doneCollapses) panel.hidden = true;
    });
  }
  renderChips();
  recordSelection();
</script>
"""

_ENTRY_HTML = {
    "structural": (
        '<input id="collab-entry" name="creation-collaborator-input" '
        'placeholder="Add collaborators" autocomplete="off">'
    ),
    "en": (
        '<input id="collab-entry" placeholder="Add collaborators" '
        'autocomplete="off">'
    ),
    "zh": (
        '<input id="collab-entry" placeholder="添加合作者" '
        'autocomplete="off">'
    ),
    "broad": (
        '<input id="collab-entry" placeholder="Search for collaborators" '
        'autocomplete="off">'
    ),
    "disabled": (
        '<input id="collab-entry" name="creation-collaborator-input" '
        'placeholder="Add collaborators" autocomplete="off" disabled>'
    ),
    "missing": "",
}


def _collaborator_page_html(
    candidates=(),
    *,
    preselect=(),
    entry="structural",
    done_label="Done",
    done_collapses=True,
    row_click="select",
    render_chips=True,
    value_after_five="5 people",
    checkbox_delay_ms=0,
    restriction="",
    obscured=False,
) -> str:
    """受控配文页：结构/中英文入口、勾选面板、预览 chip、Done 与 Share 计数。"""
    html = (
        _COLLABORATOR_PAGE
        .replace("__ENTRY__", _ENTRY_HTML[entry])
        .replace("__RESTRICTION__", restriction)
        .replace(
            "__CANDIDATES__",
            json.dumps(
                [
                    {"username": username, "display": display}
                    for username, display in candidates
                ],
                ensure_ascii=False,
            ),
        )
        .replace("__PRESELECT__", json.dumps(list(preselect)))
        .replace("__ROW_CLICK__", json.dumps(row_click))
        .replace("__DONE_COLLAPSES__", "true" if done_collapses else "false")
        .replace("__RENDER_CHIPS__", "true" if render_chips else "false")
        .replace("__VALUE_AFTER_FIVE__", json.dumps(value_after_five))
        .replace("__CHECKBOX_DELAY_MS__", str(int(checkbox_delay_ms)))
        .replace("__DONE_LABEL__", done_label)
    )
    if not obscured:
        return html
    return (
        f'<div aria-hidden="true">{html}</div>'
        '<div role="dialog" id="discard">'
        '<div>放弃帖子？</div>'
        '<div>如果退出，你所做的编辑不会保存。</div>'
        '<div role="button">放弃</div>'
        '<div role="button">取消</div>'
        '</div>'
    )


def _timeout_patches():
    """把控件等待收紧到测试尺度；不改变生产默认值。"""
    return (
        patch.object(collaborators_control_module, "ENTRY_TIMEOUT_MS", 300),
        patch.object(collaborators_control_module, "PANEL_TIMEOUT_MS", 600),
        patch.object(collaborators_control_module, "SUGGESTION_TIMEOUT_MS", 250),
        patch.object(collaborators_control_module, "SUGGESTION_SETTLE_MS", 20),
        patch.object(collaborators_control_module, "READBACK_TIMEOUT_MS", 400),
        patch.object(collaborators_control_module, "DONE_TIMEOUT_MS", 300),
    )


async def _expire_budget_after_username(page, budget, username):
    """页面确认 ``username`` 后把发布预算推到过去，制造“列表中途耗尽”。

    触发条件是页面可见的已选集合（chip / checkbox 同源），不是控件私有调用
    次数；这样测试观察的就是真实的中途预算耗尽，而不是实现细节。
    """
    await page.wait_for_function(
        """(username) => {
          try {
            return JSON.parse(document.body.dataset.selected || '[]')
              .includes(username);
          } catch (error) {
            return false;
          }
        }""",
        arg=username,
    )
    budget.deadline = time.monotonic() - 1


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
                                _expire_budget_after_username(
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

        patches = list(_timeout_patches())
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
        html = _collaborator_page_html(
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
                    _collaborator_page_html(candidates),
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
        html = _collaborator_page_html(
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
                    _collaborator_page_html(
                        [("alice", "Alice")], entry=entry
                    ),
                    options=InstagramPublishOptions(collaborators=("alice",)),
                )
                self.assertIsNone(outcome.error)
                self.assertEqual(outcome.chips, ["alice"])

    def test_already_selected_chip_is_not_clicked_again(self):
        html = _collaborator_page_html(
            [("alice", "Alice"), ("bob", "Bob")], preselect=("alice",)
        )
        outcome = self._apply(
            html,
            options=InstagramPublishOptions(collaborators=("alice", "bob")),
        )
        self.assertIsNone(outcome.error)
        self.assertEqual(outcome.chips, ["alice", "bob"])
        self.assertEqual(outcome.row_clicks, 1)

    def test_missing_entry_is_unsupported(self):
        outcome = self._apply(
            _collaborator_page_html([("alice", "Alice")], entry="missing"),
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
            _collaborator_page_html([("alice", "Alice")], entry="disabled"),
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
            _collaborator_page_html([], row_click="select"),
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
        html = _collaborator_page_html(
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

    def test_click_without_selection_is_selection_failed(self):
        outcome = self._apply(
            _collaborator_page_html(
                [("alice", "Alice")], row_click="ignore"
            ),
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        self.assertIn(
            "collaborators=mismatch(selection_failed)", str(outcome.error)
        )
        self.assertEqual(
            outcome.saved["options"]["collaborators"]["reason"],
            SELECTION_FAILED,
        )
        self.assertEqual(outcome.saved["options"]["collaborators"]["applied"], [])
        self.assertEqual(outcome.share_clicks, 0)

    def test_missing_chip_readback_is_final_mismatch(self):
        outcome = self._apply(
            _collaborator_page_html(
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
            _collaborator_page_html(
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
        outcome = self._apply(
            _collaborator_page_html(
                [("alice", "Alice")],
                entry="missing",
                restriction=(
                    '<div id="collaborator-restriction" role="alert">'
                    "Cannot add collaborators to this account."
                    "</div>"
                ),
            ),
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        self.assertIn(
            "collaborators=unsupported(account_ineligible)", str(outcome.error)
        )
        record = outcome.saved["options"]["collaborators"]
        self.assertEqual(record["reason"], ACCOUNT_INELIGIBLE)
        self.assertIn("Cannot add collaborators", record["detail"])
        self.assertEqual(outcome.share_clicks, 0)

    def test_missing_done_is_list_not_collapsed_not_entry_missing(self):
        outcome = self._apply(
            _collaborator_page_html(
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
            _collaborator_page_html(
                [("alice", "Alice"), ("bob", "Bob"), ("carol", "Carol")],
                checkbox_delay_ms=250,
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
            _collaborator_page_html(
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
            _collaborator_page_html(
                [("alice", "Alice")], done_label="完成"
            ),
            options=InstagramPublishOptions(collaborators=("alice",)),
        )
        self.assertIsNone(outcome.error)
        self.assertEqual(outcome.done_clicks, 1)

    def test_obscured_composer_records_editor_obscured_without_control(self):
        outcome = self._apply(
            _collaborator_page_html(
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
                                _expire_budget_after_username(
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

        patches = list(_timeout_patches())
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
        html = _collaborator_page_html(
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
                    _collaborator_page_html(
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
                    _collaborator_page_html(
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
        html = _collaborator_page_html(
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
        html = _collaborator_page_html(
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

    def test_nike_never_selects_a_substring_candidate(self):
        outcome = self._apply(
            _collaborator_page_html(
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
            _collaborator_page_html(
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
            _collaborator_page_html(
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
            _collaborator_page_html(
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
            _collaborator_page_html([], render_chips=False),
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
            _collaborator_page_html(
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
            _collaborator_page_html(
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
            _collaborator_page_html(
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
            _collaborator_page_html(
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
            _collaborator_page_html(
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
            _collaborator_page_html(
                [("alice", "Alice"), ("bob", "Bob"), ("carol", "Carol")],
                render_chips=False,
                checkbox_delay_ms=250,
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
            _collaborator_page_html(
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
            _collaborator_page_html(
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
            _collaborator_page_html(
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
            _collaborator_page_html(
                [("alice", "Alice")],
                restriction=(
                    '<div id="collaborator-restriction" role="alert">'
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
            _collaborator_page_html(
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
                            _expire_budget_after_username(
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
        patches = _timeout_patches()
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
        html = _collaborator_page_html(
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
        html = _collaborator_page_html([("_nikeza5", "nikeza")])
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
        html = _collaborator_page_html([("alice", "Alice")])
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
        html = _collaborator_page_html(
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
        html = _collaborator_page_html(
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
        html = _collaborator_page_html(
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
        html = _collaborator_page_html(
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
                html=_collaborator_page_html(
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
                html=_collaborator_page_html(
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
                html=_collaborator_page_html(
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
                html=_collaborator_page_html([]),
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
                html=_collaborator_page_html(
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
                html=_collaborator_page_html(
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
                html=_collaborator_page_html(
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
                html=_collaborator_page_html(
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
                html=_collaborator_page_html(
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
                html=_collaborator_page_html(
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
                html = _collaborator_page_html(
                    [("alice", "Alice"), ("bob", "Bob"), ("carol", "Carol")],
                    checkbox_delay_ms=250,
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
                        "collaborators": _FakeCollaboratorControl(
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
            html=_collaborator_page_html([("_nikeza5", "nikeza")]),
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
