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
    TIKTOK_IMAGE_SUFFIXES,
    TIKTOK_INIT_SCRIPT,
    TIKTOK_LAUNCH_KWARGS,
    TIKTOK_MAX_IMAGE_BYTES,
    TIKTOK_MAX_IMAGE_COUNT,
    TiktokNote,
    TiktokPublishOptions,
    TiktokVideo,
    is_logged_in,
)
from utils.browser_session import browser_session
from utils.errors import UsageError

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
    upload_video_parser.add_argument(
        "--privacy",
        choices=("public", "friends", "followers", "only-me"),
        help=(
            "Set video privacy (public/friends/followers/only-me); "
            "omit to leave the page default"
        ),
    )
    upload_video_parser.add_argument(
        "--no-comments",
        action="store_true",
        help="Turn off Allow comments; omit to leave the page default",
    )
    upload_video_parser.add_argument(
        "--disable-reuse",
        action="store_true",
        help=(
            "Turn off Allow reuse of content (also affects Duet, Stitch, "
            "Stickers and Story); omit to leave the page default"
        ),
    )
    add_runtime_flags(upload_video_parser)
    add_multilogin_flags(upload_video_parser)

    # Ticket 15: core photo post only.  Title/Description/options arrive in
    # ticket 16, so those flags are deliberately absent here.
    upload_note_parser = tiktok_actions.add_parser(
        "upload-note", help="Upload one photo post to TikTok"
    )
    upload_note_parser.add_argument(
        "--account",
        required=False,
        help="TikTok user-defined account_name (log label only)",
    )
    upload_note_parser.add_argument(
        "--images",
        required=True,
        nargs="+",
        type=existing_file_path,
        help="1-35 image file paths, in display order (first is the cover)",
    )
    upload_note_parser.add_argument(
        "--schedule", type=schedule_value, help=f"Schedule time in {schedule_help}"
    )
    add_runtime_flags(upload_note_parser)
    add_multilogin_flags(upload_note_parser)


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
    options: TiktokPublishOptions | None = None


def _build_publish_options(args) -> TiktokPublishOptions | None:
    """Map CLI flags to the uploader's tri-state options.

    Every ``None`` means "do not touch the page default".  When all three are
    ``None`` the legacy code path stays genuinely untouched (``options=None``).
    """
    privacy = getattr(args, "privacy", None) or None
    allow_comments = False if getattr(args, "no_comments", False) else None
    allow_reuse = False if getattr(args, "disable_reuse", False) else None
    if privacy is None and allow_comments is None and allow_reuse is None:
        return None
    return TiktokPublishOptions(
        privacy=privacy,
        allow_comments=allow_comments,
        allow_reuse=allow_reuse,
    )


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
        options=request.options,
    )


@dataclass(slots=True)
class TiktokNoteUploadRequest:
    account_label: str | None
    image_files: list[Path]
    note: str
    tags: list[str]
    publish_date: datetime | int
    title: str | None = None
    debug: bool = True
    headless: bool = True


def _validate_note_images(image_files: list[Path]) -> None:
    """Reject bad photo-post input before any browser/session work.

    Errors are reported verbatim (never truncated) and map to exit code 2.
    Extension matching is case-insensitive.
    """
    count = len(image_files)
    if count < 1:
        raise UsageError(
            f"图文帖至少需要 1 张图片，当前 {count} 张。"
        )
    if count > TIKTOK_MAX_IMAGE_COUNT:
        raise UsageError(
            f"图文帖最多 {TIKTOK_MAX_IMAGE_COUNT} 张图片，当前 {count} 张。"
        )

    for raw_path in image_files:
        path = Path(raw_path)
        suffix = path.suffix.lower()
        if suffix not in TIKTOK_IMAGE_SUFFIXES:
            shown = path.suffix or "<无扩展名>"
            raise UsageError(
                f"不支持的图片格式: {shown}（{path}），"
                "仅支持 JPG/JPEG/PNG/WEBP。"
            )
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise UsageError(
                f"无法读取图片文件: {path}（{exc}）。"
            ) from exc
        if size > TIKTOK_MAX_IMAGE_BYTES:
            raise UsageError(
                f"图片超过 50 MB: {path}"
                f"（{size} 字节，上限 {TIKTOK_MAX_IMAGE_BYTES} 字节）。"
            )


def _build_note_uploader(request: TiktokNoteUploadRequest) -> TiktokNote:
    """Build the photo-post uploader; keyword-only fields stay keyword-only."""
    return TiktokNote(
        [str(path) for path in request.image_files],
        request.note,
        request.tags,
        request.publish_date,
        None,
        title=request.title,
        debug=request.debug,
        headless=request.headless,
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

    if args.action == "upload-note":
        # Validate before resolving the Profile or touching any browser state
        # so bad input never opens a session (exit 2).
        image_files = [Path(path) for path in args.images]
        _validate_note_images(image_files)
        request = TiktokNoteUploadRequest(
            account_label=resolve_account_label(args),
            image_files=image_files,
            note="",
            tags=[],
            publish_date=args.schedule or 0,
            debug=args.debug,
            headless=args.headless,
        )
        app = _build_note_uploader(request)
        target = resolve_multilogin_target(args)

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

        print(
            f"TikTok note upload submitted: {len(request.image_files)} images"
        )
        return 0

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
            options=_build_publish_options(args),
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
