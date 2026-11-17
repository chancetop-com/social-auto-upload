"""weibo 的命令参数与执行逻辑。"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from patchright.async_api import async_playwright

from uploader.weibo_uploader.main import (
    WEIBO_INIT_SCRIPT,
    WEIBO_LAUNCH_KWARGS,
    WeiBoVideo,
    is_logged_in,
    weibo_setup,
    cookie_auth as weibo_cookie_auth,
)
from sau_commands.arguments import (
    add_not_before_flag,
    add_local_runtime_flags,
    existing_file_path,
    parse_tags,
)
from sau_commands.browser import (
    add_browser_flags,
    login_required_error,
    reject_managed_login,
    require_local_account,
    resolve_account_label,
    resolve_managed_provider,
)
from sau_commands.arguments import single_line_value
from utils.text_validation import validate_single_line
from utils.browser_session import browser_session
from utils.local_browser import resolve_headless
from sau_commands.local_profile import add_reset_profile_action, run_reset_profile


def register(platform_parsers):
    """声明本平台命令、参数及合法选项。"""
    weibo_parser = platform_parsers.add_parser("weibo", help="Sina Weibo operations")
    weibo_actions = weibo_parser.add_subparsers(dest="action", required=True)

    add_reset_profile_action(weibo_actions)

    for action_name in ("login", "check"):
        action_parser = weibo_actions.add_parser(action_name, help=f"Weibo {action_name}")
        action_parser.add_argument("--account", required=False, help="Weibo user-defined account_name")
        add_local_runtime_flags(action_parser)
        if action_name == "check":
            add_browser_flags(action_parser)

    weibo_upload_video_parser = weibo_actions.add_parser("upload-video", help="Upload one video to Weibo")
    weibo_upload_video_parser.add_argument("--account", required=False, help="Weibo user-defined account_name")
    weibo_upload_video_parser.add_argument("--file", required=True, type=existing_file_path, help="Video file path")
    weibo_upload_video_parser.add_argument("--title", type=single_line_value, required=True, help="Video title (max 30 chars)")
    weibo_upload_video_parser.add_argument("--desc", default="", help="Optional video description")
    weibo_upload_video_parser.add_argument("--tags", default="", help="Comma-separated tags, such as tag1,tag2")
    weibo_upload_video_parser.add_argument("--thumbnail", type=existing_file_path, help="Required cover image path (<5MB)")
    weibo_upload_video_parser.add_argument("--collection", default=None, help="Optional collection name")
    add_not_before_flag(weibo_upload_video_parser)
    add_local_runtime_flags(weibo_upload_video_parser)
    add_browser_flags(weibo_upload_video_parser)


@dataclass(slots=True)
class WeiboVideoUploadRequest:
    account_name: str
    video_file: Path
    title: str
    description: str
    tags: list[str]
    thumbnail_file: Path | None = None
    collection_name: str | None = None
    debug: bool = True
    headless: bool | None = None
    publish_not_before: datetime | None = None
    local_browser: str | None = None


async def login_weibo_account(account_name, headless=None, qrcode_callback=None, *, local_browser=None):
    return await weibo_setup(account_name=account_name, handle=True, return_detail=True,
                             headless=headless, qrcode_callback=qrcode_callback, local_browser=local_browser)


async def check_weibo_account(account_name, headless=None, *, local_browser=None):
    return await weibo_cookie_auth(account_name=account_name, headless=headless, local_browser=local_browser)


def _build_weibo_uploader(
    request: WeiboVideoUploadRequest, account_file: str | None
) -> WeiBoVideo:
    app = WeiBoVideo(
        title=request.title,
        file_path=str(request.video_file),
        tags=request.tags,
        account_file=account_file,
        account_name=request.account_name,
        local_browser=request.local_browser,
        desc=request.description,
        thumbnail_path=str(request.thumbnail_file) if request.thumbnail_file else None,
        collection_name=request.collection_name,
        debug=request.debug,
        headless=request.headless,
    )
    app.publish_not_before = request.publish_not_before
    return app


def _raise_login_required(target) -> None:
    raise login_required_error("微博", target.profile_id, mode=target.mode)


async def upload_weibo_video(
    request: WeiboVideoUploadRequest, *, target=None
) -> None:
    validate_single_line(request.title)
    if target is not None:
        app = _build_weibo_uploader(request, None)
        async with async_playwright() as playwright:
            async with browser_session(
                playwright,
                headless=resolve_headless(request.headless),
                account_file=None,
                managed=target,
                launch_kwargs=WEIBO_LAUNCH_KWARGS,
                # Managed browser window settings remain provider-owned.
                context_kwargs=None,
                init_script=WEIBO_INIT_SCRIPT,
            ) as session:
                if not await is_logged_in(session.context):
                    _raise_login_required(target)
                await app.main(session=session)
        return None

    app = _build_weibo_uploader(request, None)
    await app.main()
    return None


async def run(args):
    """执行本平台命令；发布结果由平台实现核验。"""
    if args.action == "reset-profile":
        return run_reset_profile(args)
    args.headless = resolve_headless(getattr(args, "headless", None))
    local_browser = getattr(args, "local_browser", None)
    if args.action == "login":
        reject_managed_login("weibo", args)
        require_local_account(args)
        result = await login_weibo_account(args.account, headless=args.headless, local_browser=local_browser)
        if not result["success"]:
            raise RuntimeError(result["message"])
        print(f"Weibo login flow completed: {result['account_name']}")
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
                _raise_login_required(target)
            print("valid")
            return 0

        is_valid = await check_weibo_account(args.account, headless=args.headless, local_browser=local_browser)
        print("valid" if is_valid else "invalid")
        return 0 if is_valid else 1

    if args.action == "upload-video":
        request = WeiboVideoUploadRequest(
            account_name=account_label,
            video_file=args.file,
            title=args.title,
            description=args.desc,
            tags=parse_tags(args.tags),
            thumbnail_file=args.thumbnail,
            collection_name=args.collection,
            debug=args.debug,
            headless=args.headless,
            publish_not_before=args.not_before,
            local_browser=local_browser,
        )
        await upload_weibo_video(request, target=target)
        print(f"Weibo video upload submitted: {request.video_file}")
        return 0

    raise RuntimeError(f"Unsupported Weibo action: {args.action}")
