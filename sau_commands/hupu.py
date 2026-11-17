"""hupu 的命令参数与执行逻辑。"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from patchright.async_api import async_playwright
from uploader.hupu_uploader.main import (
    HUPU_CONTEXT_KWARGS,
    HUPU_INIT_SCRIPT,
    HUPU_LAUNCH_KWARGS,
    HuPuVideo,
    cookie_auth as hupu_cookie_auth,
    hupu_setup,
    is_logged_in,
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
from utils.browser_session import browser_session
from utils.local_browser import resolve_headless
from sau_commands.local_profile import add_reset_profile_action, run_reset_profile


def register(platform_parsers):
    """声明本平台命令、参数及合法选项。"""
    hupu_parser = platform_parsers.add_parser("hupu", help="Hupu (虎扑) operations")
    hupu_actions = hupu_parser.add_subparsers(dest="action", required=True)

    add_reset_profile_action(hupu_actions)

    for action_name in ("login", "check"):
        action_parser = hupu_actions.add_parser(action_name, help=f"Hupu {action_name}")
        action_parser.add_argument("--account", required=False, help="Hupu user-defined account_name")
        add_local_runtime_flags(action_parser)
        if action_name == "check":
            add_browser_flags(action_parser)

    hupu_upload_video_parser = hupu_actions.add_parser("upload-video", help="Upload one video to Hupu")
    hupu_upload_video_parser.add_argument("--account", required=False, help="Hupu user-defined account_name")
    hupu_upload_video_parser.add_argument("--file", required=True, type=existing_file_path, help="Video file path")
    hupu_upload_video_parser.add_argument("--title", required=True, help="Video title (4-40 chars)")
    hupu_upload_video_parser.add_argument("--desc", default="", help="Optional video description")
    hupu_upload_video_parser.add_argument("--tags", default="", help="Comma-separated tags, such as tag1,tag2")
    hupu_upload_video_parser.add_argument("--thumbnail", type=existing_file_path, help="Optional cover image path")
    add_not_before_flag(hupu_upload_video_parser)
    add_local_runtime_flags(hupu_upload_video_parser)
    add_browser_flags(hupu_upload_video_parser)


@dataclass(slots=True)
class HupuVideoUploadRequest:
    account_name: str
    video_file: Path
    title: str
    description: str
    tags: list[str]
    thumbnail_file: Path | None = None
    debug: bool = True
    headless: bool | None = None
    publish_not_before: datetime | None = None
    local_browser: str | None = None


async def login_hupu_account(account_name, headless=None, qrcode_callback=None, *, local_browser=None):
    return await hupu_setup(account_name=account_name, handle=True, return_detail=True,
                            headless=headless, qrcode_callback=qrcode_callback, local_browser=local_browser)


async def check_hupu_account(account_name, headless=None, *, local_browser=None):
    return await hupu_cookie_auth(account_name=account_name, headless=headless, local_browser=local_browser)


def _build_uploader(request: HupuVideoUploadRequest) -> HuPuVideo:
    app = HuPuVideo(
        title=request.title,
        file_path=str(request.video_file),
        tags=request.tags,
        account_file=None,
        desc=request.description,
        thumbnail_path=str(request.thumbnail_file) if request.thumbnail_file else None,
        debug=request.debug,
        headless=request.headless,
        account_name=request.account_name,
        local_browser=request.local_browser,
    )
    app.publish_not_before = request.publish_not_before
    return app


def _raise_login_required(target) -> None:
    raise login_required_error("虎扑", target.profile_id, mode=target.mode)


async def upload_hupu_video(request: HupuVideoUploadRequest, *, target=None) -> None:
    if target is not None:
        app = _build_uploader(request)
        async with async_playwright() as playwright:
            async with browser_session(
                playwright,
                headless=resolve_headless(request.headless),
                account_file=None,
                managed=target,
                launch_kwargs=HUPU_LAUNCH_KWARGS,
                context_kwargs=HUPU_CONTEXT_KWARGS,
                init_script=HUPU_INIT_SCRIPT,
                extra_ignored=("context_setup",),
            ) as session:
                if not await is_logged_in(session.context):
                    _raise_login_required(target)
                await app.upload(session=session)
        return None

    app = _build_uploader(request)
    await app.main()
    return None


async def run(args):
    """执行本平台命令；发布结果由平台实现核验。"""
    if args.action == "reset-profile":
        return run_reset_profile(args)
    args.headless = resolve_headless(getattr(args, "headless", None))
    local_browser = getattr(args, "local_browser", None)
    if args.action == "login":
        reject_managed_login("hupu", args)
        require_local_account(args)
        result = await login_hupu_account(args.account, headless=args.headless, local_browser=local_browser)
        if not result["success"]:
            raise RuntimeError(result["message"])
        print(f"Hupu login flow completed: {result['account_name']}")
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

        is_valid = await check_hupu_account(args.account, headless=args.headless, local_browser=local_browser)
        print("valid" if is_valid else "invalid")
        return 0 if is_valid else 1

    if args.action == "upload-video":
        request = HupuVideoUploadRequest(
            account_name=account_label,
            video_file=args.file,
            title=args.title,
            description=args.desc,
            tags=parse_tags(args.tags),
            thumbnail_file=args.thumbnail,
            debug=args.debug,
            headless=args.headless,
            publish_not_before=args.not_before,
            local_browser=local_browser,
        )
        await upload_hupu_video(request, target=target)
        print(f"Hupu video upload submitted: {request.video_file}")
        return 0

    raise RuntimeError(f"Unsupported Hupu action: {args.action}")
