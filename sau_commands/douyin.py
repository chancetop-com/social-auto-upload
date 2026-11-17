"""douyin 的命令参数与执行逻辑。"""
from __future__ import annotations
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from patchright.async_api import async_playwright
from uploader.douyin_uploader.main import (
    DOUYIN_CONTEXT_KWARGS,
    DOUYIN_INIT_SCRIPT,
    DOUYIN_LAUNCH_KWARGS,
    DOUYIN_PUBLISH_STRATEGY_IMMEDIATE,
    DOUYIN_PUBLISH_STRATEGY_SCHEDULED,
    DouYinNote,
    DouYinVideo,
    cookie_auth as douyin_cookie_auth,
    douyin_setup,
    is_logged_in,
)
from sau_commands.arguments import (
    SCHEDULE_HELP,
    add_not_before_flag,
    add_local_runtime_flags,
    existing_file_path,
    parse_image_files,
    parse_tags,
    resolve_account_file,
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
from sau_commands.arguments import single_line_value
from utils.text_validation import validate_single_line
from utils.browser_session import browser_session
from utils.local_browser import resolve_headless
from sau_commands.local_profile import add_reset_profile_action, run_reset_profile


def register(platform_parsers):
    """声明本平台命令、参数及合法选项。"""
    douyin_parser = platform_parsers.add_parser("douyin", help="Douyin operations")
    douyin_actions = douyin_parser.add_subparsers(dest="action", required=True)

    add_reset_profile_action(douyin_actions)

    for action_name in ("login", "check"):
        action_parser = douyin_actions.add_parser(action_name, help=f"Douyin {action_name}")
        action_parser.add_argument("--account", required=False, help="Douyin user-defined account_name")
        add_local_runtime_flags(action_parser)
        if action_name == "check":
            add_browser_flags(action_parser)

    upload_video_parser = douyin_actions.add_parser("upload-video", help="Upload one video to Douyin")
    upload_video_parser.add_argument("--account", required=False, help="Douyin user-defined account_name")
    upload_video_parser.add_argument("--file", required=True, type=existing_file_path, help="Video file path")
    upload_video_parser.add_argument("--title", type=single_line_value, required=True, help="Video title")
    upload_video_parser.add_argument("--desc", default="", help="Optional video description")
    upload_video_parser.add_argument("--tags", default="", help="Comma-separated tags, such as tag1,tag2")
    upload_video_parser.add_argument("--schedule", type=schedule_value, help=SCHEDULE_HELP)
    add_not_before_flag(upload_video_parser)
    upload_video_parser.add_argument("--thumbnail", type=existing_file_path, help="Optional 3:4 portrait thumbnail path")
    upload_video_parser.add_argument("--thumbnail-landscape", type=existing_file_path, help="Optional 4:3 landscape thumbnail path")
    upload_video_parser.add_argument("--thumbnail-portrait", type=existing_file_path, help="Optional 3:4 portrait thumbnail path")
    upload_video_parser.add_argument("--product-link", default="", help="Optional product link")
    upload_video_parser.add_argument("--product-title", type=single_line_value, default="", help="Optional product title")
    upload_video_parser.add_argument(
        "--declaration",
        help="Exact Douyin self-declaration option text; omitted means do not set one",
    )
    upload_video_parser.add_argument("--collection", default=None, help="Optional collection name to add the work into (must already exist)")
    add_local_runtime_flags(upload_video_parser)
    add_browser_flags(upload_video_parser)

    upload_note_parser = douyin_actions.add_parser("upload-note", help="Upload one note to Douyin")
    upload_note_parser.add_argument("--account", required=False, help="Douyin user-defined account_name")
    upload_note_parser.add_argument("--images", required=True, nargs="+", type=existing_file_path, help="Image file paths")
    upload_note_parser.add_argument("--title", type=single_line_value, required=True, help="Note title")
    upload_note_parser.add_argument("--note", default="", help="Optional note content")
    upload_note_parser.add_argument("--notef", default="", help="Read note content from file (txt/md)")
    upload_note_parser.add_argument("--tags", default="", help="Comma-separated tags, such as tag1,tag2")
    upload_note_parser.add_argument("--bgm", default="", help="BGM music name to search and select")
    upload_note_parser.add_argument("--schedule", type=schedule_value, help=SCHEDULE_HELP)
    add_not_before_flag(upload_note_parser)
    add_local_runtime_flags(upload_note_parser)
    add_browser_flags(upload_note_parser)


@dataclass(slots=True)
class DouyinVideoUploadRequest:
    account_name: str
    video_file: Path
    title: str
    description: str
    tags: list[str]
    publish_date: datetime | int
    thumbnail_file: Path | None = None
    thumbnail_landscape_file: Path | None = None
    thumbnail_portrait_file: Path | None = None
    product_link: str = ""
    product_title: str = ""
    publish_strategy: str = DOUYIN_PUBLISH_STRATEGY_IMMEDIATE
    debug: bool = True
    headless: bool | None = None
    declaration: str | None = None
    collection_name: str | None = None
    publish_not_before: datetime | None = None
    local_browser: str | None = None


@dataclass(slots=True)
class DouyinNoteUploadRequest:
    account_name: str
    image_files: list[Path]
    title: str
    note: str
    tags: list[str]
    publish_date: datetime | int
    publish_strategy: str = DOUYIN_PUBLISH_STRATEGY_IMMEDIATE
    debug: bool = True
    headless: bool | None = None
    bgm: str = ""
    publish_not_before: datetime | None = None
    local_browser: str | None = None


async def login_douyin_account(account_name, headless=None, *, local_browser=None):
    return await douyin_setup(account_name=account_name, handle=True, return_detail=True,
                              headless=headless, local_browser=local_browser)


async def check_douyin_account(account_name, headless=None, *, local_browser=None):
    return await douyin_cookie_auth(account_name=account_name, headless=headless, local_browser=local_browser)


def _build_video_uploader(request: DouyinVideoUploadRequest, account_file) -> DouYinVideo:
    app = DouYinVideo(
        request.title,
        str(request.video_file),
        request.tags,
        request.publish_date,
        account_file,
        desc=request.description,
        thumbnail_landscape_path=(
            str(request.thumbnail_landscape_file) if request.thumbnail_landscape_file else None
        ),
        thumbnail_portrait_path=str(
            request.thumbnail_portrait_file or request.thumbnail_file
        ) if request.thumbnail_portrait_file or request.thumbnail_file else None,
        productLink=request.product_link,
        productTitle=request.product_title,
        declaration=request.declaration,
        publish_strategy=request.publish_strategy,
        debug=request.debug,
        headless=request.headless,
        account_name=request.account_name,
        local_browser=request.local_browser,
        collection_name=request.collection_name,
    )
    app.publish_not_before = request.publish_not_before
    return app


def _build_note_uploader(request: DouyinNoteUploadRequest, account_file) -> DouYinNote:
    app = DouYinNote(
        image_paths=[str(path) for path in request.image_files],
        title=request.title,
        note=request.note,
        tags=request.tags,
        publish_date=request.publish_date,
        account_file=account_file,
        publish_strategy=request.publish_strategy,
        debug=request.debug,
        headless=request.headless,
        account_name=request.account_name,
        local_browser=request.local_browser,
        bgm=request.bgm,
    )
    app.publish_not_before = request.publish_not_before
    return app


def _raise_login_required(target) -> None:
    raise login_required_error("抖音", target.profile_id, mode=target.mode)


async def upload_video(request: DouyinVideoUploadRequest, *, target=None) -> Path | None:
    validate_single_line(request.title)
    validate_single_line(request.product_title, label="商品短标题")
    if target is not None:
        app = _build_video_uploader(request, None)
        async with async_playwright() as playwright:
            async with browser_session(
                playwright,
                headless=resolve_headless(request.headless),
                account_file=None,
                managed=target,
                launch_kwargs=DOUYIN_LAUNCH_KWARGS,
                context_kwargs=DOUYIN_CONTEXT_KWARGS,
                init_script=DOUYIN_INIT_SCRIPT,
            ) as session:
                if not await is_logged_in(session.context):
                    _raise_login_required(target)
                await app.douyin_upload_video(session=session)
        return None

    app = _build_video_uploader(request, None)
    await app.douyin_upload_video()
    return None


async def upload_note(request: DouyinNoteUploadRequest, *, target=None) -> Path | None:
    validate_single_line(request.title)
    if target is not None:
        app = _build_note_uploader(request, None)
        async with async_playwright() as playwright:
            async with browser_session(
                playwright,
                headless=resolve_headless(request.headless),
                account_file=None,
                managed=target,
                launch_kwargs=DOUYIN_LAUNCH_KWARGS,
                context_kwargs=DOUYIN_CONTEXT_KWARGS,
                init_script=DOUYIN_INIT_SCRIPT,
            ) as session:
                if not await is_logged_in(session.context):
                    _raise_login_required(target)
                await app.douyin_upload_note(session=session)
        return None

    app = _build_note_uploader(request, None)
    await app.douyin_upload_note()
    return None


async def run(args):
    """执行本平台命令；发布结果由平台实现核验。"""
    if args.action == "reset-profile":
        return run_reset_profile(args)
    if args.action == "login":
        reject_managed_login("douyin", args)
        require_local_account(args)
        result = await login_douyin_account(args.account, headless=args.headless, local_browser=getattr(args, "local_browser", None))
        if not result["success"]:
            raise RuntimeError(result["message"])
        print(f"Douyin Profile login completed: {args.account}")
        return 0

    target = resolve_managed_provider(args)
    require_local_account(args)
    account_label = resolve_account_label(args)

    if args.action == "check":
        if target is not None:
            async with async_playwright() as playwright:
                async with browser_session(
                    playwright,
                    headless=resolve_headless(args.headless),
                    managed=target,
                ) as session:
                    is_valid = await is_logged_in(session.context)
            if not is_valid:
                _raise_login_required(target)
            print("valid")
            return 0

        is_valid = await check_douyin_account(args.account, headless=args.headless, local_browser=getattr(args, "local_browser", None))
        print("valid" if is_valid else "invalid")
        return 0 if is_valid else 1

    publish_strategy = DOUYIN_PUBLISH_STRATEGY_SCHEDULED if args.schedule else DOUYIN_PUBLISH_STRATEGY_IMMEDIATE

    if args.action == "upload-video":
        request = DouyinVideoUploadRequest(
            account_name=account_label,
            video_file=args.file,
            title=args.title,
            description=args.desc,
            tags=parse_tags(args.tags),
            publish_date=args.schedule or 0,
            thumbnail_file=args.thumbnail,
            thumbnail_landscape_file=args.thumbnail_landscape,
            thumbnail_portrait_file=args.thumbnail_portrait,
            product_link=args.product_link,
            product_title=args.product_title,
            declaration=args.declaration,
            publish_strategy=publish_strategy,
            debug=args.debug,
            headless=args.headless,
            local_browser=getattr(args, "local_browser", None),
            collection_name=args.collection,
            publish_not_before=args.not_before,
        )
        await upload_video(request, target=target)
        print(f"Douyin video upload submitted: {request.video_file}")
        return 0

    if args.action == "upload-note":
        # 如果指定了 --notef，读取文件内容作为 note
        note_content = args.note
        if args.notef:
            note_file = Path(args.notef)
            if not note_file.exists():
                print(f"错误：文件不存在: {note_file}", file=sys.stderr)
                return 1
            note_content = note_file.read_text(encoding="utf-8")

        request = DouyinNoteUploadRequest(
            account_name=account_label,
            image_files=parse_image_files(args.images),
            title=args.title,
            note=note_content,
            tags=parse_tags(args.tags),
            publish_date=args.schedule or 0,
            publish_strategy=publish_strategy,
            debug=args.debug,
            headless=args.headless,
            local_browser=getattr(args, "local_browser", None),
            bgm=args.bgm or "",
            publish_not_before=args.not_before,
        )
        await upload_note(request, target=target)
        print(f"Douyin note upload submitted: {len(request.image_files)} images")
        return 0

    raise RuntimeError(f"Unsupported Douyin action: {args.action}")
