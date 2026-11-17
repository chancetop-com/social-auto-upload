"""tencent 的命令参数与执行逻辑。"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from patchright.async_api import async_playwright
from uploader.tencent_uploader.main import (
    TENCENT_CONTEXT_KWARGS,
    TENCENT_INIT_SCRIPT,
    TENCENT_LAUNCH_KWARGS,
    TENCENT_PUBLISH_STRATEGY_IMMEDIATE,
    TENCENT_PUBLISH_STRATEGY_SCHEDULED,
    TencentVideo,
    is_logged_in,
    tencent_setup,
)
from sau_commands.arguments import (
    SCHEDULE_HELP,
    add_not_before_flag,
    add_local_runtime_flags,
    existing_file_path,
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
from utils.local_browser import resolve_headless
from sau_commands.local_profile import add_reset_profile_action, run_reset_profile


def register(platform_parsers):
    """声明本平台命令、参数及合法选项。"""
    tencent_parser = platform_parsers.add_parser("tencent", help="Tencent/WeChat Channels operations")
    tencent_actions = tencent_parser.add_subparsers(dest="action", required=True)
    add_reset_profile_action(tencent_actions)

    for action_name in ("login", "check"):
        action_parser = tencent_actions.add_parser(action_name, help=f"Tencent/WeChat Channels {action_name}")
        action_parser.add_argument("--account", required=False, help="Tencent user-defined account_name")
        add_local_runtime_flags(action_parser)
        if action_name == "check":
            add_browser_flags(action_parser)

    tencent_upload_video_parser = tencent_actions.add_parser("upload-video", help="Upload one video to WeChat Channels")
    tencent_upload_video_parser.add_argument("--account", required=False, help="Tencent user-defined account_name")
    tencent_upload_video_parser.add_argument("--file", required=True, type=existing_file_path, help="Video file path")
    tencent_upload_video_parser.add_argument("--title", required=True, help="Video title")
    tencent_upload_video_parser.add_argument("--desc", default="", help="Optional video description")
    tencent_upload_video_parser.add_argument("--tags", default="", help="Comma-separated tags, such as tag1,tag2")
    tencent_upload_video_parser.add_argument("--schedule", type=schedule_value, help=SCHEDULE_HELP)
    add_not_before_flag(tencent_upload_video_parser)
    tencent_upload_video_parser.add_argument("--thumbnail", type=existing_file_path, help="Optional 3:4 portrait thumbnail path")
    tencent_upload_video_parser.add_argument("--thumbnail-landscape", type=existing_file_path, help="Optional 4:3 landscape thumbnail path")
    tencent_upload_video_parser.add_argument("--thumbnail-portrait", type=existing_file_path, help="Optional 3:4 portrait thumbnail path")
    tencent_upload_video_parser.add_argument("--short-title", help="Optional WeChat Channels short title")
    tencent_upload_video_parser.add_argument("--category", help="Optional original content category")
    tencent_upload_video_parser.add_argument("--draft", action="store_true", help="Save as draft instead of publishing")
    tencent_upload_video_parser.add_argument("--collection", default=None, help="Optional collection name to add the work into (must already exist)")
    add_local_runtime_flags(tencent_upload_video_parser)
    add_browser_flags(tencent_upload_video_parser)


@dataclass(slots=True)
class TencentVideoUploadRequest:
    account_name: str
    video_file: Path
    title: str
    description: str
    tags: list[str]
    publish_date: datetime | int
    thumbnail_file: Path | None = None
    thumbnail_landscape_file: Path | None = None
    thumbnail_portrait_file: Path | None = None
    short_title: str | None = None
    category: str | None = None
    is_draft: bool = False
    publish_strategy: str = TENCENT_PUBLISH_STRATEGY_IMMEDIATE
    debug: bool = True
    headless: bool | None = None
    collection_name: str | None = None
    publish_not_before: datetime | None = None
    local_browser: str | None = None


async def login_tencent_account(account_name, headless=None, *, local_browser=None):
    return await tencent_setup(account_name=account_name, handle=True, return_detail=True,
                               headless=headless, local_browser=local_browser)


async def check_tencent_account(account_name, headless=None, *, local_browser=None):
    return await tencent_setup(account_name=account_name, headless=headless, local_browser=local_browser)


async def upload_tencent_video(request: TencentVideoUploadRequest, *, target=None) -> Path | None:
    if target is not None:
        app = TencentVideo(
            title=request.title,
            file_path=str(request.video_file),
            tags=request.tags,
            publish_date=request.publish_date,
            account_file=None,
            category=request.category,
            is_draft=request.is_draft,
            desc=request.description,
            thumbnail_path=str(request.thumbnail_file) if request.thumbnail_file else None,
            thumbnail_landscape_path=(
                str(request.thumbnail_landscape_file) if request.thumbnail_landscape_file else None
            ),
            thumbnail_portrait_path=(
                str(request.thumbnail_portrait_file) if request.thumbnail_portrait_file else None
            ),
            short_title=request.short_title,
            publish_strategy=request.publish_strategy,
            debug=request.debug,
            headless=request.headless,
            collection_name=request.collection_name,
        )
        app.publish_not_before = request.publish_not_before
        async with async_playwright() as playwright:
            async with browser_session(
                playwright,
                headless=resolve_headless(request.headless),
                account_file=None,
                managed=target,
                launch_kwargs=TENCENT_LAUNCH_KWARGS,
                context_kwargs=TENCENT_CONTEXT_KWARGS,
                init_script=TENCENT_INIT_SCRIPT,
            ) as session:
                if not await is_logged_in(session.context):
                    raise login_required_error("视频号", target.profile_id, mode=target.mode)
                await app.tencent_upload_video(session=session)
        return None

    app = TencentVideo(
        title=request.title,
        file_path=str(request.video_file),
        tags=request.tags,
        publish_date=request.publish_date,
        account_file=None,
        account_name=request.account_name,
        local_browser=request.local_browser,
        category=request.category,
        is_draft=request.is_draft,
        desc=request.description,
        thumbnail_path=str(request.thumbnail_file) if request.thumbnail_file else None,
        thumbnail_landscape_path=(
            str(request.thumbnail_landscape_file) if request.thumbnail_landscape_file else None
        ),
        thumbnail_portrait_path=(
            str(request.thumbnail_portrait_file) if request.thumbnail_portrait_file else None
        ),
        short_title=request.short_title,
        publish_strategy=request.publish_strategy,
        debug=request.debug,
        headless=request.headless,
        collection_name=request.collection_name,
    )
    app.publish_not_before = request.publish_not_before
    await app.tencent_upload_video()
    return None


async def run(args):
    """执行本平台命令；发布结果由平台实现核验。"""
    if args.action == "reset-profile":
        return run_reset_profile(args)
    args.headless = resolve_headless(getattr(args, "headless", None))
    local_browser = getattr(args, "local_browser", None)
    if args.action == "login":
        reject_managed_login("tencent", args)
        require_local_account(args)
        result = await login_tencent_account(args.account, headless=args.headless, local_browser=local_browser)
        if not result["success"]:
            raise RuntimeError(result["message"])
        print(f"Tencent/WeChat Channels login flow completed: {result['account_name']}")
        return 0

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
                raise login_required_error("视频号", target.profile_id, mode=target.mode)
            print("valid")
            return 0

        is_valid = await check_tencent_account(args.account, headless=args.headless, local_browser=local_browser)
        print("valid" if is_valid else "invalid")
        return 0 if is_valid else 1

    publish_strategy = TENCENT_PUBLISH_STRATEGY_SCHEDULED if args.schedule else TENCENT_PUBLISH_STRATEGY_IMMEDIATE

    if args.action == "upload-video":
        request = TencentVideoUploadRequest(
            account_name=account_label,
            video_file=args.file,
            title=args.title,
            description=args.desc,
            tags=parse_tags(args.tags),
            publish_date=args.schedule or 0,
            thumbnail_file=args.thumbnail,
            thumbnail_landscape_file=args.thumbnail_landscape,
            thumbnail_portrait_file=args.thumbnail_portrait,
            short_title=args.short_title,
            category=args.category,
            is_draft=args.draft,
            publish_strategy=publish_strategy,
            debug=args.debug,
            headless=args.headless,
            collection_name=args.collection,
            publish_not_before=args.not_before,
            local_browser=local_browser,
        )
        await upload_tencent_video(request, target=target)
        print(f"Tencent/WeChat Channels video upload submitted: {request.video_file}")
        return 0

    raise RuntimeError(f"Unsupported Tencent/WeChat Channels action: {args.action}")
