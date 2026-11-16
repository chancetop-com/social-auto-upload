"""Exercise real declaration variants in one authorized, non-publishing draft."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_dry_run import capture, rednote, sau_cli  # noqa: E402

apply_declarations = rednote.RednoteBaseUploader.apply_declarations


async def verify_variants(self, page, *, humanizer=None):
    original_type = self.content_type
    try:
        for kind in ("fiction", "marketing", "repost"):
            self.content_type = kind
            try:
                await apply_declarations(self, page, humanizer=humanizer)
            finally:
                await capture(page, f"variant-{kind}")
    finally:
        self.content_type = original_type


if __name__ == "__main__":
    rednote.RednoteBaseUploader.apply_declarations = verify_variants
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
                "repost",
                "--repost-source",
                "Rednote integration fixture",
                "--headless",
                "--no-publish",
            ]
        )
    )
