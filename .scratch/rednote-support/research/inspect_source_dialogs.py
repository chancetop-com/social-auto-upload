"""Inspect one source dialog without filling, confirming, or publishing it.

Usage: python inspect_source_dialogs.py self-shot|repost
The account and fixture are the local, user-authorized Rednote acceptance setup.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_dry_run import capture, rednote, sau_cli  # noqa: E402


async def inspect_source(self, page, *, humanizer):
    await page.locator(".d-modal:visible").wait_for()
    await capture(page, f"source-{self.content_type}")
    raise RuntimeError("诊断完成：来源弹窗只读取证；没有填写、确认或发布")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"self-shot", "repost"}:
        raise SystemExit("Usage: inspect_source_dialogs.py self-shot|repost")
    kind = sys.argv[1]
    rednote.RednoteBaseUploader._fill_self_shot = inspect_source
    rednote.RednoteBaseUploader._fill_repost_source = inspect_source
    # CLI requires these fields; the diagnostic replacement never types them.
    fields = (
        ["--shoot-location", "Integration check", "--shoot-date", "2026-11-16"]
        if kind == "self-shot"
        else ["--repost-source", "Integration check"]
    )
    raise SystemExit(
        sau_cli.main(
            [
                "rednote",
                "upload-note",
                "--account",
                "rednote",
                "--images",
                ".local/rednote-acceptance/check-1.png",
                "--title",
                "Rednote setup check",
                "--note",
                "Integration check. Draft only.",
                "--content-type",
                kind,
                *fields,
                "--headless",
                "--no-publish",
            ]
        )
    )
