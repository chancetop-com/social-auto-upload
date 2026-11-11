# -*- coding: utf-8 -*-
"""Executable mirror of the exit-code contract (spec §4; ticket 28).

One row = one failure type:

    scenario → exception / fields → expected exit code → stderr assertion

The mirror only exercises scenarios that already work through
``sau_cli.main()``.  Scenarios whose fields or stderr signal are not implemented
yet live in :data:`PENDING`; the meta-tests below fail if a row is neither
covered nor pending, so the ``PENDING`` registry can only shrink as tickets
31–41 land.

This file deliberately does **not** parse ``docs/CLI.md``: that file is a
derived projection and must not define the contract (spec §4).

All tests are offline: ``sau_cli.dispatch`` is replaced with a scripted
outcome, so no browser, network, or platform uploader runs.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from typing import Any, Callable
from unittest.mock import patch

import sau_cli
from sau_commands.browser import DUAL_CREDENTIALS_MESSAGE
from utils.errors import (
    LoginRequiredError,
    PublishResultUnknownError,
    RateLimitedError,
    UsageError,
)

#: The complete set of exit codes the contract may emit (spec §4).
EXIT_CODES = frozenset({0, 1, 2, 9, 10, 11, 130})

#: The complete scenario set, one entry per spec §4 failure type.
#: ``covered | PENDING`` must equal this set (see meta-tests).
FULL_SET = frozenset(
    {
        "publish-success",
        "login-before-dispatch",
        "login-after-dispatch",
        "verification-before-dispatch",
        "verification-after-dispatch",
        "preflight-local-failure",
        "check-logged-out",
        "check-probe-failure",
        "arm-window-exhausted",
        "upload-failure",
        "topic-mismatch",
        "metadata-failure",
        "fire-dispatch-exception",
        "observe-timeout",
        "usage-error",
        "rate-limited",
        "dual-credentials-or-provider-failure",
        "ctrl-c",
    }
)

DEFAULT_ARGV = ("xiaohongshu", "check")


@dataclass(frozen=True)
class ExitRow:
    """One contract row, runnable through ``sau_cli.main()``."""

    scenario: str
    expected_code: int
    outcome: Callable[[], int]
    stderr_contains: tuple[str, ...] = ()
    stderr_excludes: tuple[str, ...] = ()
    stderr_exact: str | None = None
    propagates: type[BaseException] | None = None
    argv: tuple[str, ...] = DEFAULT_ARGV
    dual_credentials: bool = False
    note: str = ""


def _returns(result: int = 0) -> Callable[[], int]:
    def outcome() -> int:
        return result

    return outcome


def _raises(error: BaseException) -> Callable[[], int]:
    def outcome() -> int:
        raise error

    return outcome


ROWS: tuple[ExitRow, ...] = (
    ExitRow(
        scenario="publish-success",
        expected_code=0,
        outcome=_returns(0),
        stderr_exact="",
        note="or --no-publish ready; no machine signal",
    ),
    ExitRow(
        scenario="login-before-dispatch",
        expected_code=10,
        outcome=_raises(LoginRequiredError("登录状态已失效，请重新登录。")),
        stderr_contains=("登录状态已失效",),
        note="pre-dispatch: no publish_attempted line",
    ),
    ExitRow(
        scenario="preflight-local-failure",
        expected_code=10,
        outcome=_raises(LoginRequiredError("账号文件不存在：cookies/xhs.json")),
        stderr_contains=("账号文件不存在",),
        note="local pre-flight: no browser started by design",
    ),
    ExitRow(
        scenario="check-logged-out",
        expected_code=10,
        outcome=_raises(LoginRequiredError("未登录")),
        stderr_contains=("未登录",),
        note="check: certain logged-out",
    ),
    ExitRow(
        scenario="check-probe-failure",
        expected_code=1,
        outcome=_raises(RuntimeError("页面结构异常：找不到登录锚点")),
        stderr_contains=("页面结构异常",),
        note="fault is not invalidation",
    ),
    ExitRow(
        scenario="upload-failure",
        expected_code=1,
        outcome=_raises(RuntimeError("上传失败：找不到素材输入框")),
        stderr_contains=("上传失败",),
    ),
    ExitRow(
        scenario="fire-dispatch-exception",
        expected_code=9,
        outcome=_raises(
            PublishResultUnknownError("发布结果未知：禁止自动重发，请先人工核查。")
        ),
        stderr_contains=("禁止自动重发",),
    ),
    ExitRow(
        scenario="observe-timeout",
        expected_code=9,
        outcome=_raises(
            PublishResultUnknownError("15 秒内未确认发布成功：可能已发布")
        ),
        stderr_contains=("可能已发布",),
    ),
    ExitRow(
        scenario="usage-error",
        expected_code=2,
        outcome=_raises(UsageError("本地模式需要 --account。")),
        stderr_contains=("usage:", "本地模式需要 --account。"),
        note="argparse usage line is printed before the message",
    ),
    ExitRow(
        scenario="rate-limited",
        expected_code=11,
        outcome=_raises(RateLimitedError("429：请求过于频繁")),
        stderr_contains=("429",),
    ),
    ExitRow(
        scenario="dual-credentials-or-provider-failure",
        expected_code=1,
        outcome=_returns(0),
        stderr_contains=(DUAL_CREDENTIALS_MESSAGE,),
        dual_credentials=True,
        note="dual credential check runs before dispatch",
    ),
    ExitRow(
        scenario="ctrl-c",
        expected_code=130,
        outcome=_raises(KeyboardInterrupt()),
        propagates=KeyboardInterrupt,
        stderr_exact="",
        note="main() does not catch KeyboardInterrupt",
    ),
)

#: Scenarios whose mechanism is not implemented yet.  Each entry names the
#: ticket that will move the row into :data:`ROWS`; the meta-test keeps this
#: list honest and it must be empty at ticket 41.
PENDING: dict[str, str] = {
    "login-after-dispatch": (
        "tickets 35/36: LoginRequiredError(reason=..., publish_attempted=True) "
        "plus the standalone stderr line"
    ),
    "verification-before-dispatch": (
        "ticket 35: LoginRequiredError(reason='verification', "
        "publish_attempted=False)"
    ),
    "verification-after-dispatch": (
        "tickets 35/36: reason='verification' with publish_attempted=True and "
        "the stderr line"
    ),
    "arm-window-exhausted": (
        "ticket 36: ARM readiness window exhausted, budget.pre_click_error()"
    ),
    "topic-mismatch": (
        "ticket 39: RuntimeError with reason=topic-mismatch / topic-multi-insert"
    ),
    "metadata-failure": (
        "ticket 40: ValueError / ElementUnusableError metadata failure paths"
    ),
}


@dataclass(frozen=True)
class RunResult:
    code: int
    stderr: str
    stdout: str
    propagated: BaseException | None = field(default=None)


def run_row(row: ExitRow) -> RunResult:
    """Execute one row through the real ``sau_cli.main`` mapping."""

    async def dispatch(_args: Any) -> int:
        return row.outcome()

    out, err = io.StringIO(), io.StringIO()
    code: int | None = None
    propagated: BaseException | None = None
    with (
        patch.object(sau_cli, "dispatch", new=dispatch),
        patch.object(
            sau_cli,
            "credentials_conflict",
            return_value=row.dual_credentials,
        ),
        redirect_stdout(out),
        redirect_stderr(err),
    ):
        try:
            code = sau_cli.main(list(row.argv))
        except BaseException as exc:  # noqa: BLE001 - contract checks 130
            if row.propagates is None or not isinstance(exc, row.propagates):
                raise
            propagated = exc
            code = row.expected_code

    assert code is not None
    return RunResult(
        code=code,
        stderr=err.getvalue(),
        stdout=out.getvalue(),
        propagated=propagated,
    )


class ExitContractMirrorTests(unittest.TestCase):
    """One table-driven test over every covered row."""

    def test_every_covered_row_matches_the_contract(self):
        for row in ROWS:
            with self.subTest(scenario=row.scenario):
                result = run_row(row)

                self.assertEqual(
                    result.code,
                    row.expected_code,
                    f"{row.scenario}: {row.note}",
                )
                for expected in row.stderr_contains:
                    self.assertIn(expected, result.stderr, row.scenario)
                for forbidden in row.stderr_excludes:
                    self.assertNotIn(forbidden, result.stderr, row.scenario)
                if row.stderr_exact is not None:
                    self.assertEqual(result.stderr, row.stderr_exact, row.scenario)

                # Machine signal: only exit 10 *after dispatch* may print the
                # standalone line.  Future rows opt in by listing the token in
                # stderr_contains.
                if "publish_attempted=true" not in row.stderr_contains:
                    self.assertNotIn(
                        "publish_attempted=true", result.stderr, row.scenario
                    )
                self.assertNotIn(
                    "Traceback (most recent call last)", result.stderr, row.scenario
                )

                if row.expected_code == 130:
                    self.assertIsInstance(result.propagated, KeyboardInterrupt)
                else:
                    self.assertIsNone(result.propagated, row.scenario)


class ExitContractRegistryTests(unittest.TestCase):
    """Meta-tests that keep the table honest as later tickets land."""

    def test_every_exit_code_in_the_contract_has_a_covered_row(self):
        covered = {row.expected_code for row in ROWS}
        self.assertEqual(covered, set(EXIT_CODES))

    def test_covered_and_pending_cover_the_full_scenario_set(self):
        covered = {row.scenario for row in ROWS}
        self.assertEqual(
            covered & set(PENDING),
            set(),
            "a scenario cannot be both covered and pending",
        )
        self.assertEqual(
            covered | set(PENDING),
            set(FULL_SET),
            "add the missing scenario to ROWS or PENDING",
        )

    def test_every_pending_entry_names_its_follow_up_ticket(self):
        for scenario, reason in PENDING.items():
            with self.subTest(scenario=scenario):
                self.assertTrue(reason.strip())
                self.assertIn("ticket", reason.lower())

    def test_scenario_names_are_unique(self):
        names = [row.scenario for row in ROWS]
        self.assertEqual(len(names), len(set(names)))

    def test_no_row_is_outside_the_full_set(self):
        self.assertLessEqual({row.scenario for row in ROWS}, set(FULL_SET))


if __name__ == "__main__":
    unittest.main()
