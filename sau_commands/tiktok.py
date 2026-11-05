"""tiktok 的命令参数与执行逻辑（仅 Multilogin 模式）。

TikTok 没有本地浏览器路径。MLX 分支跳过 ``change_language``，因此部署前提是
Multilogin Profile 的界面语言必须为 English (US)。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from patchright.async_api import async_playwright

from sau_commands.arguments import (
    SCHEDULE_FORMAT,
    add_runtime_flags,
    existing_file_path,
    parse_tags,
    schedule_value,
)
from sau_commands.multilogin import (
    add_multilogin_flags,
    login_required_error,
    multilogin_enabled,
    reject_multilogin_login,
    resolve_account_label,
    resolve_multilogin_target,
)
from uploader.tk_uploader.main_chrome import (
    TIKTOK_CONTEXT_KWARGS,
    TIKTOK_INIT_SCRIPT,
    TIKTOK_LAUNCH_KWARGS,
    TiktokVideo,
    is_logged_in,
)
from utils.browser_session import browser_session

# Ticket 13 §5: local mode is rejected at the run() entry so no browser code
# (and no cookie path) is ever reached.
TIKTOK_LOCAL_MODE_MESSAGE = (
    "TikTok 仅支持 Multilogin 模式：请设置 MLX_API_TOKEN，"
    "并提供 --folder-id / --profile-id。"
)
TIKTOK_LOGIN_REJECTED_MESSAGE = (
    "Multilogin 模式不支持 CLI 登录；"
    "请在 Multilogin 应用中登录 Profile 后重试。"
)


def register(platform_parsers):
    """声明本平台命令、参数及合法选项。"""
    schedule_help = SCHEDULE_FORMAT.replace("%", "%%")
    tiktok_parser = platform_parsers.add_parser(
        "tiktok", help="TikTok operations (Multilogin mode only)"
    )
    tiktok_actions = tiktok_parser.add_subparsers(dest="action", required=True)

    for action_name in ("login", "check"):
        action_parser = tiktok_actions.add_parser(
            action_name, help=f"TikTok {action_name}"
        )
        action_parser.add_argument(
            "--account",
            required=False,
            help="TikTok user-defined account_name (log label only)",
        )
        add_runtime_flags(action_parser)
        if action_name == "check":
            add_multilogin_flags(action_parser)

    upload_video_parser = tiktok_actions.add_parser(
        "upload-video", help="Upload one video to TikTok"
    )
    upload_video_parser.add_argument(
        "--account",
        required=False,
        help="TikTok user-defined account_name (log label only)",
    )
    upload_video_parser.add_argument(
        "--file", required=True, type=existing_file_path, help="Video file path"
    )
    upload_video_parser.add_argument("--title", required=True, help="Video title")
    upload_video_parser.add_argument(
        "--tags", default="", help="Comma-separated tags, such as tag1,tag2"
    )
    upload_video_parser.add_argument(
        "--schedule", type=schedule_value, help=f"Schedule time in {schedule_help}"
    )
    upload_video_parser.add_argument(
        "--thumbnail", type=existing_file_path, help="Optional thumbnail path"
    )
    add_runtime_flags(upload_video_parser)
    add_multilogin_flags(upload_video_parser)


@dataclass(slots=True)
class TiktokVideoUploadRequest:
    account_label: str | None
    video_file: Path
    title: str
    tags: list[str]
    publish_date: datetime | int
    thumbnail_file: Path | None = None
    debug: bool = True
    headless: bool = True


def _build_video_uploader(request: TiktokVideoUploadRequest) -> TiktokVideo:
    """Build the uploader with the legacy positional order and no cookie file."""
    return TiktokVideo(
        request.title,
        str(request.video_file),
        request.tags,
        request.publish_date,
        None,
        thumbnail_path=(
            str(request.thumbnail_file) if request.thumbnail_file else None
        ),
    )


def _raise_login_required(target) -> None:
    raise login_required_error("TikTok", target.profile_id)


async def run(args):
    """执行本平台命令；TikTok 没有本地浏览器路径。"""
    if not multilogin_enabled():
        raise RuntimeError(TIKTOK_LOCAL_MODE_MESSAGE)

    if args.action == "login":
        reject_multilogin_login("tiktok", args)
        raise RuntimeError(TIKTOK_LOGIN_REJECTED_MESSAGE)

    target = resolve_multilogin_target(args)
    account_label = resolve_account_label(args)

    if args.action == "check":
        async with async_playwright() as playwright:
            async with browser_session(
                playwright,
                headless=args.headless,
                multilogin=target,
            ) as session:
                is_valid = await is_logged_in(session.context)
        if not is_valid:
            _raise_login_required(target)
        print("valid")
        return 0

    if args.action == "upload-video":
        request = TiktokVideoUploadRequest(
            account_label=account_label,
            video_file=args.file,
            title=args.title,
            tags=parse_tags(args.tags),
            publish_date=args.schedule or 0,
            thumbnail_file=args.thumbnail,
            debug=args.debug,
            headless=args.headless,
        )
        app = _build_video_uploader(request)

        async with async_playwright() as playwright:
            async with browser_session(
                playwright,
                headless=request.headless,
                account_file=None,
                multilogin=target,
                launch_kwargs=TIKTOK_LAUNCH_KWARGS,
                context_kwargs=TIKTOK_CONTEXT_KWARGS,
                init_script=TIKTOK_INIT_SCRIPT,
            ) as session:
                if not await is_logged_in(session.context):
                    _raise_login_required(target)
                await app.upload(None, session=session)

        print(f"TikTok video upload submitted: {request.video_file}")
        return 0

    raise RuntimeError(f"Unsupported TikTok action: {args.action}")
