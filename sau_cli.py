"""SAU 命令入口；平台参数与执行逻辑位于 sau_commands。"""
from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Sequence

from sau_commands import article, facebook, facebook_page, instagram, rednote, tiktok, xiaohongshu, youtube
from sau_commands.browser import DUAL_CREDENTIALS_MESSAGE, active_mode, credentials_conflict, resolve_multilogin_target
from utils.managed_sharing import managed_command
from utils.errors import (
    LoginRequiredError,
    PublishResultUnknownError,
    RateLimitedError,
    UsageError,
)


PLATFORMS = {
    "article": article,
    "xiaohongshu": xiaohongshu,
    "rednote": rednote,
    "facebook": facebook,
    "facebook-page": facebook_page,
    "instagram": instagram,
    "youtube": youtube,
    "tiktok": tiktok,
}


def build_parser() -> argparse.ArgumentParser:
    """组装平台命令；每个平台维护自己的参数和执行函数。"""
    parser = argparse.ArgumentParser(prog="sau", description="CLI for social-auto-upload.")
    platform_parsers = parser.add_subparsers(dest="platform", required=True)
    for platform in PLATFORMS.values():
        platform.register(platform_parsers)
    return parser


async def dispatch(args: argparse.Namespace) -> int:
    """只按平台分发，不在入口重复平台的业务判断。"""
    # Existing tests build Namespace objects by hand without the new optional
    # attributes; normalise them here so platform ``run`` functions can read
    # them unconditionally.
    if not hasattr(args, "folder_id"):
        args.folder_id = None
    if not hasattr(args, "profile_id"):
        args.profile_id = None
    if not hasattr(args, "account"):
        args.account = None
    if not hasattr(args, "not_before"):
        args.not_before = None

    if args.platform not in PLATFORMS:
        raise RuntimeError(f"Unsupported platform: {args.platform}")
    mode = active_mode()
    if mode is not None and args.action in {"check", "upload-video", "upload-note"} and args.profile_id:
        profile_id = args.profile_id.strip()
        if mode == "multilogin":
            profile_id = resolve_multilogin_target(args).profile_id
        async with managed_command(args.platform, mode, profile_id, getattr(args, "headless", None)):
            return await PLATFORMS[args.platform].run(args)
    return await PLATFORMS[args.platform].run(args)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        # Conflict detection lives after argparse and before dispatch so that
        # ``--help`` / unknown subcommands keep their argparse semantics, while
        # a dual-credential setup wins over command-level rejections.
        if credentials_conflict():
            raise RuntimeError(DUAL_CREDENTIALS_MESSAGE)
        return asyncio.run(dispatch(args))
    except LoginRequiredError as exc:
        print(str(exc), file=sys.stderr)
        # Machine signal: only exit 10 *after* dispatch prints the standalone
        # token line.  No prefix, no timestamp, no leading text.
        if getattr(exc, "publish_attempted", False):
            print("publish_attempted=true", file=sys.stderr)
        return 10
    except RateLimitedError as exc:
        print(str(exc), file=sys.stderr)
        return 11
    except UsageError as exc:
        parser.print_usage(sys.stderr)
        print(str(exc), file=sys.stderr)
        return 2
    except PublishResultUnknownError as exc:
        print(str(exc), file=sys.stderr)
        return 9
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
