"""youtube 的命令参数与执行逻辑。"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from patchright.async_api import async_playwright
from uploader.youtube_uploader.main import (
    YOUTUBE_CONTEXT_KWARGS,
    YOUTUBE_INIT_SCRIPT,
    YOUTUBE_LAUNCH_KWARGS,
    YouTubeVideo,
    is_logged_in,
    youtube_setup,
)
from sau_commands.publish_media import add_task_id, media_source
from sau_commands.arguments import (
    add_not_before_flag,
    add_local_runtime_flags,
    parse_tags,
    schedule_value,
)
from sau_commands.browser import (
    add_browser_flags,
    login_required_error,
    reject_managed_login,
    require_local_account,
    resolve_account_label,
    resolve_managed_provider,
)
from utils.browser_session import browser_session
from utils.caption_topics import parse_caption_topics, text_results
from utils.errors import UsageError
from utils.local_browser import resolve_headless
from sau_commands.local_profile import add_reset_profile_action, run_reset_profile


def register(platform_parsers):
    """声明本平台命令、参数及合法选项。"""
    youtube_parser = platform_parsers.add_parser("youtube", help="YouTube operations")
    youtube_actions = youtube_parser.add_subparsers(dest="action", required=True)
    add_reset_profile_action(youtube_actions)

    for action_name in ("login", "check"):
        action_parser = youtube_actions.add_parser(action_name, help=f"YouTube {action_name}")
        action_parser.add_argument("--account", required=False, help="YouTube user-defined account_name")
        add_local_runtime_flags(action_parser)
        if action_name == "check":
            add_browser_flags(action_parser)

    youtube_upload_video_parser = youtube_actions.add_parser("upload-video", help="Upload one video to YouTube")
    youtube_upload_video_parser.add_argument("--account", required=False, help="YouTube user-defined account_name")
    add_task_id(youtube_upload_video_parser)
    youtube_upload_video_parser.add_argument(
        "--file", required=True, type=media_source, help="Local video path or HTTP(S) URL"
    )
    youtube_upload_video_parser.add_argument("--title", required=True, help="Video title (<=100 chars)")
    youtube_upload_video_parser.add_argument("--desc", default="", help="Optional video description")
    youtube_upload_video_parser.add_argument("--tags", default="", help="Comma-separated tags, such as tag1,tag2")
    youtube_upload_video_parser.add_argument(
        "--thumbnail", type=media_source, help="Local thumbnail path or HTTP(S) URL"
    )
    youtube_upload_video_parser.add_argument("--playlist", help="Optional playlist name to add the video to (for series)")
    youtube_upload_video_parser.add_argument(
        "--visibility", default="public", choices=["public", "unlisted", "private"], help="Video visibility")
    youtube_upload_video_parser.add_argument(
        "--schedule",
        type=schedule_value,
        help="Not supported yet; omit to publish immediately",
    )
    add_not_before_flag(youtube_upload_video_parser)
    add_local_runtime_flags(youtube_upload_video_parser)
    add_browser_flags(youtube_upload_video_parser)


@dataclass(slots=True)
class YouTubeVideoUploadRequest:
    account_name: str
    video_file: Path
    title: str
    description: str
    tags: list[str]
    thumbnail_file: Path | None = None
    playlist: str | None = None
    visibility: str = "public"
    schedule: datetime | int = 0
    debug: bool = True
    headless: bool | None = None
    publish_not_before: datetime | None = None
    local_browser: str | None = None


async def login_youtube_account(account_name, headless=None, *, local_browser=None):
    return await youtube_setup(account_name=account_name, handle=True, return_detail=True,
                               headless=headless, local_browser=local_browser)


async def check_youtube_account(account_name, headless=None, *, local_browser=None):
    return await youtube_setup(account_name=account_name, headless=headless, local_browser=local_browser)


def _report_description_topics(description: str) -> None:
    """Print one text-level result per description topic, in caption order."""
    topics = parse_caption_topics(description)
    results = text_results(topics, reason="简介全文逐字回读一致")
    total = len(results)
    for result in results:
        print(
            f"YouTube 简介话题 {result.occurrence.index}/{total}："
            f"{result.occurrence.text} 保留文字（{result.reason}）"
        )


def _build_youtube_uploader(request: YouTubeVideoUploadRequest) -> YouTubeVideo:
    app = YouTubeVideo(
        request.title,
        str(request.video_file),
        request.tags,
        None,
        description=request.description,
        thumbnail_path=str(request.thumbnail_file) if request.thumbnail_file else None,
        playlist=request.playlist,
        visibility=request.visibility,
        debug=request.debug,
        headless=request.headless,
        account_name=request.account_name,
        local_browser=request.local_browser,
    )
    app.publish_not_before = request.publish_not_before
    return app


def _raise_login_required(target) -> None:
    raise login_required_error("YouTube", target.profile_id, mode=target.mode)


async def upload_youtube_video(request: YouTubeVideoUploadRequest, *, target=None) -> None:
    if target is not None:
        app = _build_youtube_uploader(request)
        async with async_playwright() as playwright:
            async with browser_session(
                playwright,
                headless=resolve_headless(request.headless),
                account_file=None,
                managed=target,
                launch_kwargs=YOUTUBE_LAUNCH_KWARGS,
                context_kwargs=YOUTUBE_CONTEXT_KWARGS,
                init_script=YOUTUBE_INIT_SCRIPT,
            ) as session:
                if not await is_logged_in(session.context):
                    _raise_login_required(target)
                app.set_publish_date(request.schedule)
                await app.main(session=session)
        return None

    app = _build_youtube_uploader(request)
    app.set_publish_date(request.schedule)
    await app.main()
    return None


async def run(args):
    """执行本平台命令；发布结果由平台实现核验。"""
    if args.action == "reset-profile":
        return run_reset_profile(args)
    args.headless = resolve_headless(getattr(args, "headless", None))
    local_browser = getattr(args, "local_browser", None)
    if args.action == "login":
        reject_managed_login("youtube", args)
        require_local_account(args)
        result = await login_youtube_account(args.account, headless=args.headless, local_browser=local_browser)
        if not result["success"]:
            raise RuntimeError(result["message"])
        print(f"YouTube login flow completed: {result['account_name']}")
        return 0

    if args.action == "upload-video" and args.schedule:
        raise UsageError("YouTube 定时发布尚未实现；请省略 --schedule 立即发布。")

    target = resolve_managed_provider(args)
    require_local_account(args)
    account_label = resolve_account_label(args)

    if args.action == "check":
        if target is not None:
            async with async_playwright() as playwright:
                async with browser_session(
                    playwright,
                    headless=args.headless,
                    managed=target,
                ) as session:
                    is_valid = await is_logged_in(session.context)
            if not is_valid:
                _raise_login_required(target)
            print("valid")
            return 0

        is_valid = await check_youtube_account(args.account, headless=args.headless, local_browser=local_browser)
        print("valid" if is_valid else "invalid")
        return 0 if is_valid else 1

    if args.action == "upload-video":
        request = YouTubeVideoUploadRequest(
            account_name=account_label,
            video_file=args.file,
            title=args.title,
            description=args.desc,
            tags=parse_tags(args.tags),
            thumbnail_file=args.thumbnail,
            playlist=args.playlist,
            visibility=args.visibility,
            schedule=args.schedule or 0,
            debug=args.debug,
            headless=args.headless,
            publish_not_before=args.not_before,
            local_browser=local_browser,
        )
        await upload_youtube_video(request, target=target)
        _report_description_topics(request.description)
        print(f"YouTube video upload submitted: {request.video_file}")
        args.post_published = True
        return 0

    raise RuntimeError(f"Unsupported YouTube action: {args.action}")
