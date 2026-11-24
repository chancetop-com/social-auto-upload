"""Instagram 协作者（Collaborators）选项回归（A/B 层，零浏览器部分）。

覆盖三件事：

- 纯逻辑：归一化、静态校验、结果骨架/顺序/状态映射。
- fake 控制件：选项管线按顺序应用、失败保留已确认前缀、预算与结果落盘。
- CLI 边界：两个上传命令注册可重复 ``--collaborator``；``verify`` / ``delete``
  不注册；空值/重复/超过 5 个在启动浏览器前退出 2。

受控 DOM 与 CLI 真页面用例分别在 ``test_instagram_collaborators_dom.py`` /
``test_instagram_collaborators_cli.py``，共享页面夹具在
``tests/instagram_collaborators_fixtures.py``。
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import sau_cli
from sau_commands import instagram as instagram_command
from uploader.meta_uploader.insgraph_uploader.controls.collaborators import (
    CollaboratorsControl,
    collaborator_count_summary,
)
from uploader.meta_uploader.insgraph_uploader.main import InstagramUploader
from uploader.meta_uploader.insgraph_uploader.options import (
    ACCOUNT_INELIGIBLE,
    CONTROL_DISABLED,
    ENTRY_MISSING,
    LIST_NOT_COLLAPSED,
    MISMATCH,
    NO_SAME_USERNAME,
    NOT_REQUESTED,
    OPTION_KEYS,
    PRESENT,
    SET,
    UNSUPPORTED,
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
from tests.instagram_collaborators_fixtures import (
    ExplodingControl,
    FakeCollaboratorControl,
)
from utils.errors import PublishResultUnknownError, UsageError


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

    def test_double_at_is_normalized_only_once_across_cli_validation_and_uploader(
        self,
    ):
        built = instagram_command._build_publish_options(
            SimpleNamespace(collaborator=["@@Alice"])
        )
        self.assertEqual(built.collaborators, ("@alice",))
        self.assertEqual(
            normalize_publish_options(built).collaborators, ("@alice",)
        )
        validate_publish_options(built, image_count=1, caption="caption")
        with tempfile.TemporaryDirectory() as folder:
            app = InstagramUploader(
                "unused.json",
                title="caption",
                image_files=[str(Path(folder) / "image.png")],
                options=built,
                result_file=Path(folder) / "result.json",
            )
            self.assertEqual(app.options.collaborators, ("@alice",))

        at_only = instagram_command._build_publish_options(
            SimpleNamespace(collaborator=["@@"])
        )
        self.assertEqual(at_only.collaborators, ("@",))
        validate_publish_options(at_only, image_count=1, caption="caption")

        distinct = instagram_command._build_publish_options(
            SimpleNamespace(collaborator=["@@alice", "alice"])
        )
        self.assertEqual(distinct.collaborators, ("@alice", "alice"))
        validate_publish_options(distinct, image_count=1, caption="caption")


class InstagramCollaboratorResultTests(unittest.TestCase):
    """A 层：协作者列表的顺序与失败原因。"""

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

    def __init__(self, rows=None, *, error=None, focus_error=None):
        self.rows = rows
        self.error = error
        self.focus_error = focus_error

    async def wait_for(self, *, state, timeout):
        return None

    async def count(self):
        return 1

    async def is_visible(self):
        return True

    async def focus(self, **kwargs):
        if self.focus_error is not None:
            raise self.focus_error
        return None

    async def evaluate(self, script, arg=None, **kwargs):
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

    async def is_visible(self):
        return True


class _FakeReadDialogs:
    def __init__(self, entry):
        self._entry = entry

    async def count(self):
        return 1

    def nth(self, index):
        return _FakeReadDialog(self._entry)


class _FakeReadPage:
    def __init__(self, entry):
        self._entry = entry

    def locator(self, selector):
        return _FakeReadDialogs(self._entry)


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

    async def test_open_panel_browser_error_maps_to_list_not_collapsed(self):
        control = self._control(
            _FakeReadEntry(
                rows=False,
                focus_error=TimeoutError("focus timed out"),
            )
        )
        with self.assertRaises(OptionMismatchError) as ctx:
            await control.set(("alice",))
        error = ctx.exception
        self.assertEqual(error.reason, LIST_NOT_COLLAPSED)
        self.assertIsNone(error.applied)
        self.assertIn("面板未能打开", str(error))
        self.assertIn("focus timed out", str(error))
        self.assertIsNone(error.detail)

    async def test_disappearing_entry_during_set_reports_unsupported_entry_missing(self):
        class _VanishingPage:
            def locator(self, selector):
                return self

            async def count(self):
                return 0

        control = CollaboratorsControl(_VanishingPage(), image_count=1)

        async def _present():
            return PRESENT

        control.resolve = _present  # type: ignore[method-assign]
        with tempfile.TemporaryDirectory() as folder:
            app = InstagramUploader(
                "unused.json",
                title="caption",
                image_files=[str(Path(folder) / "image.png")],
                options=InstagramPublishOptions(collaborators=("alice",)),
                result_file=Path(folder) / "result.json",
            )
            with patch(
                "uploader.meta_uploader.insgraph_uploader.controls.collaborators.ENTRY_TIMEOUT_MS",
                10,
            ), self.assertRaisesRegex(
                RuntimeError, r"collaborators=unsupported\(entry_missing\)"
            ):
                await app._apply_options(
                    page=None,
                    budget=app.start_publish_budget(),
                    controls={"collaborators": control},
                )
            self.assertEqual(
                app.result["options"]["collaborators"],
                {
                    "requested": ["alice"],
                    "applied": None,
                    "status": UNSUPPORTED,
                    "reason": ENTRY_MISSING,
                },
            )
            self.assertFalse(app.publish_clicked)

    async def test_open_panel_browser_error_omits_detail_from_result_json(self):
        control = self._control(
            _FakeReadEntry(
                rows=False,
                focus_error=TimeoutError("focus timed out"),
            )
        )

        async def _present():
            return PRESENT

        control.resolve = _present  # type: ignore[method-assign]
        with tempfile.TemporaryDirectory() as folder:
            app = InstagramUploader(
                "unused.json",
                title="caption",
                video_file=Path(folder) / "video.mp4",
                options=InstagramPublishOptions(collaborators=("alice",)),
                result_file=Path(folder) / "result.json",
            )
            with self.assertRaisesRegex(RuntimeError, "focus timed out"):
                await app._apply_options(
                    page=None,
                    budget=app.start_publish_budget(),
                    controls={"collaborators": control},
                )
            record = app.result["options"]["collaborators"]
            self.assertEqual(
                record,
                {
                    "requested": ["alice"],
                    "applied": None,
                    "status": MISMATCH,
                    "reason": LIST_NOT_COLLAPSED,
                },
            )
            self.assertNotIn("detail", record)

    def test_count_summary_ignores_plain_usernames_and_matches_real_summaries(self):
        for value in ("1person", "0people", "alice_1person", "2people_club", ""):
            with self.subTest(non_summary=value):
                self.assertIsNone(collaborator_count_summary(value, query=value))
                self.assertIsNone(collaborator_count_summary(value))
        for value, expected in (
            ("1 person", 1),
            ("2 people", 2),
            ("5 people", 5),
            ("2 人", 2),
            ("3位用户", 3),
            ("已选 2 人", 2),
        ):
            with self.subTest(summary=value):
                self.assertEqual(collaborator_count_summary(value, query="bob"), expected)

    async def test_wait_panel_closed_retries_an_unreadable_entry_within_budget(self):
        class _RerenderingEntry:
            def __init__(self):
                self.timeouts = []

            async def count(self):
                return 1

            async def evaluate(self, script, arg=None, *, timeout=None):
                self.timeouts.append(timeout)
                if len(self.timeouts) == 1:
                    raise TimeoutError("entry detached mid-evaluate")
                return False

        class _Budget:
            def clamp_ms(self, default_ms):
                return min(default_ms, 500)

            def check_pre_click(self):
                return None

        entry = _RerenderingEntry()
        control = CollaboratorsControl(
            _FakeReadPage(_FakeReadEntry()), image_count=0, budget=_Budget()
        )
        self.assertTrue(await control._wait_panel_closed(entry, "panel-stamp"))
        self.assertGreaterEqual(len(entry.timeouts), 2)
        for timeout in entry.timeouts:
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, 500)

    async def test_locator_calls_clamp_timeout_to_remaining_budget(self):
        class _RecordingEntry(_FakeReadEntry):
            def __init__(self):
                super().__init__(rows=[])
                self.timeouts = []

            async def evaluate(self, script, arg=None, *, timeout=None):
                self.timeouts.append(("evaluate", timeout))
                return []

            async def focus(self, *, timeout=None):
                self.timeouts.append(("focus", timeout))

            async def input_value(self, *, timeout=None):
                self.timeouts.append(("input_value", timeout))
                return ""

        class _Budget:
            def clamp_ms(self, default_ms):
                return min(default_ms, 180)

            def check_pre_click(self):
                return None

        entry = _RecordingEntry()
        control = CollaboratorsControl(
            _FakeReadPage(entry), image_count=0, budget=_Budget()
        )
        self.assertEqual(await control.read(), [])
        await control._limit_refusal(entry, 2, username="bob")
        self.assertTrue(entry.timeouts)
        for kind, timeout in entry.timeouts:
            with self.subTest(kind=kind):
                self.assertIsNotNone(timeout)
                self.assertLessEqual(timeout, 180)




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
            control = FakeCollaboratorControl([[], ["alice", "bob"]])
            self._apply(app, {"collaborators": control})
            expected = {
                "requested": ["alice", "bob"],
                "applied": ["alice", "bob"],
                "status": SET,
            }
            self.assertEqual(app.result["options"]["collaborators"], expected)
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
            control = FakeCollaboratorControl(
                [[]],
                failure=OptionMismatchError(
                    "Instagram 协作者没有同 username 候选：请求「bob」",
                    applied=["alice"],
                    reason=NO_SAME_USERNAME,
                ),
            )
            comments = FakeCollaboratorControl([False])
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
                control = FakeCollaboratorControl([], presence=presence)
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
            control = FakeCollaboratorControl(
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
            control = FakeCollaboratorControl([[]])
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
            control = FakeCollaboratorControl([[]])

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
            control = FakeCollaboratorControl(
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
            controls = {key: ExplodingControl() for key in OPTION_KEYS}
            self._apply(app, controls)
            self.assertEqual(
                app.result["options"]["collaborators"],
                {"requested": None, "applied": None, "status": NOT_REQUESTED},
            )
            self.assertFalse(Path(app.result_file).exists())


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
        for action in ("verify", "delete"):
            argv = [action, "--post-url", "https://www.instagram.com/p/example/", "--expected-text", "caption"]
            with self.subTest(action=action), contextlib.redirect_stderr(io.StringIO()) as err:
                self._parse(argv)
                with self.assertRaises(SystemExit) as rejected:
                    self._parse([*argv, "--collaborator", "alice"])
                self.assertEqual(rejected.exception.code, 2)
                self.assertIn("--collaborator", err.getvalue())

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
