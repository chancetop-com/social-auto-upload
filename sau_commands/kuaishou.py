"""kuaishou 的命令参数与执行逻辑。"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from patchright.async_api import async_playwright
from uploader.ks_uploader.main import (
    KUAISHOU_CONTEXT_KWARGS,
    KUAISHOU_INIT_SCRIPT,
    KUAISHOU_LAUNCH_KWARGS,
    KUAISHOU_PUBLISH_STRATEGY_IMMEDIATE,
    KUAISHOU_PUBLISH_STRATEGY_SCHEDULED,
    KSNote,
    KSVideo,
    cookie_auth as kuaishou_cookie_auth,
    is_logged_in,
    ks_setup,
)
from sau_commands.arguments import (
    SCHEDULE_FORMAT,
    add_not_before_flag,
    add_runtime_flags,
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
from utils.browser_session import browser_session


def register(platform_parsers):
    """声明本平台命令、参数及合法选项。"""
    schedule_help = SCHEDULE_FORMAT.replace("%", "%%")
    kuaishou_parser = platform_parsers.add_parser("kuaishou", help="Kuaishou operations")
    kuaishou_actions = kuaishou_parser.add_subparsers(dest="action", required=True)

    for action_name in ("login", "check"):
        action_parser = kuaishou_actions.add_parser(action_name, help=f"Kuaishou {action_name}")
        action_parser.add_argument("--account", required=False, help="Kuaishou user-defined account_name")
        add_runtime_flags(action_parser)
        if action_name == "check":
            add_browser_flags(action_parser)

    kuaishou_upload_video_parser = kuaishou_actions.add_parser("upload-video", help="Upload one video to Kuaishou")
    kuaishou_upload_video_parser.add_argument("--account", required=False, help="Kuaishou user-defined account_name")
    kuaishou_upload_video_parser.add_argument("--file", required=True, type=existing_file_path, help="Video file path")
    kuaishou_upload_video_parser.add_argument("--title", required=True, help="Video title")
    kuaishou_upload_video_parser.add_argument("--desc", default="", help="Optional video description")
    kuaishou_upload_video_parser.add_argument("--tags", default="", help="Comma-separated tags, such as tag1,tag2")
    kuaishou_upload_video_parser.add_argument("--schedule", type=schedule_value, help=f"Schedule time in {schedule_help}")
    add_not_before_flag(kuaishou_upload_video_parser)
    kuaishou_upload_video_parser.add_argument("--thumbnail", type=existing_file_path, help="Optional thumbnail path")
    kuaishou_upload_video_parser.add_argument("--collection", default=None, help="Optional collection name to add the work into (must already exist)")
    add_runtime_flags(kuaishou_upload_video_parser)
    add_browser_flags(kuaishou_upload_video_parser)

    kuaishou_upload_note_parser = kuaishou_actions.add_parser("upload-note", help="Upload one note to Kuaishou")
    kuaishou_upload_note_parser.add_argument("--account", required=False, help="Kuaishou user-defined account_name")
    kuaishou_upload_note_parser.add_argument("--images", required=True, nargs="+", type=existing_file_path, help="Image file paths")
    kuaishou_upload_note_parser.add_argument("--title", required=True, help="Note title")
    kuaishou_upload_note_parser.add_argument("--note", default="", help="Optional note content")
    kuaishou_upload_note_parser.add_argument("--tags", default="", help="Comma-separated tags, such as tag1,tag2")
    kuaishou_upload_note_parser.add_argument("--schedule", type=schedule_value, help=f"Schedule time in {schedule_help}")
    add_not_before_flag(kuaishou_upload_note_parser)
    add_runtime_flags(kuaishou_upload_note_parser)
    add_browser_flags(kuaishou_upload_note_parser)


@dataclass(slots=True)
class KuaishouVideoUploadRequest:
    account_name: str
    video_file: Path
    title: str
    description: str
    tags: list[str]
    publish_date: datetime | int
    thumbnail_file: Path | None = None
    publish_strategy: str = KUAISHOU_PUBLISH_STRATEGY_IMMEDIATE
    debug: bool = True
    headless: bool = True
    collection_name: str | None = None
    publish_not_before: datetime | None = None


@dataclass(slots=True)
class KuaishouNoteUploadRequest:
    account_name: str
    image_files: list[Path]
    title: str
    note: str
    tags: list[str]
    publish_date: datetime | int
    publish_strategy: str = KUAISHOU_PUBLISH_STRATEGY_IMMEDIATE
    debug: bool = True
    headless: bool = True
    publish_not_before: datetime | None = None


async def login_kuaishou_account(account_name: str, headless: bool = True) -> dict:
    account_file = resolve_account_file("kuaishou", account_name)
    return await ks_setup(str(account_file), handle=True, return_detail=True, headless=headless)


async def check_kuaishou_account(account_name: str) -> bool:
    account_file = resolve_account_file("kuaishou", account_name)
    if not account_file.exists():
        return False
    return await kuaishou_cookie_auth(str(account_file))


def _build_video_uploader(request: KuaishouVideoUploadRequest, account_file) -> KSVideo:
    app = KSVideo(
        title=request.title,
        file_path=str(request.video_file),
        desc=request.description,
        tags=request.tags,
        publish_date=request.publish_date,
        account_file=account_file,
        thumbnail_path=str(request.thumbnail_file) if request.thumbnail_file else None,
        publish_strategy=request.publish_strategy,
        debug=request.debug,
        headless=request.headless,
        collection_name=request.collection_name,
    )
    app.publish_not_before = request.publish_not_before
    return app


def _build_note_uploader(request: KuaishouNoteUploadRequest, account_file) -> KSNote:
    app = KSNote(
        image_paths=[str(path) for path in request.image_files],
        title=request.title,
        note=request.note,
        tags=request.tags,
        publish_date=request.publish_date,
        account_file=account_file,
        publish_strategy=request.publish_strategy,
        debug=request.debug,
        headless=request.headless,
    )
    app.publish_not_before = request.publish_not_before
    return app


def _raise_login_required(target) -> None:
    raise login_required_error("快手", target.profile_id, mode=target.mode)


async def upload_kuaishou_video(request: KuaishouVideoUploadRequest, *, target=None) -> Path | None:
    if target is not None:
        app = _build_video_uploader(request, None)
        async with async_playwright() as playwright:
            async with browser_session(
                playwright,
                headless=request.headless,
                account_file=None,
                managed=target,
                launch_kwargs=KUAISHOU_LAUNCH_KWARGS,
                context_kwargs=KUAISHOU_CONTEXT_KWARGS,
                init_script=KUAISHOU_INIT_SCRIPT,
            ) as session:
                if not await is_logged_in(session.context):
                    _raise_login_required(target)
                await app.main(session=session)
        return None

    account_file = resolve_account_file("kuaishou", request.account_name)
    is_ready = await ks_setup(str(account_file), handle=False)
    if not is_ready:
        raise RuntimeError(
            f"Kuaishou cookie is missing or expired: {account_file}. Run `sau kuaishou login --account {request.account_name}` first."
        )

    app = _build_video_uploader(request, str(account_file))
    await app.main()
    return account_file


async def upload_kuaishou_note(request: KuaishouNoteUploadRequest, *, target=None) -> Path | None:
    if target is not None:
        app = _build_note_uploader(request, None)
        async with async_playwright() as playwright:
            async with browser_session(
                playwright,
                headless=request.headless,
                account_file=None,
                managed=target,
                launch_kwargs=KUAISHOU_LAUNCH_KWARGS,
                context_kwargs=KUAISHOU_CONTEXT_KWARGS,
                init_script=KUAISHOU_INIT_SCRIPT,
            ) as session:
                if not await is_logged_in(session.context):
                    _raise_login_required(target)
                await app.main(session=session)
        return None

    account_file = resolve_account_file("kuaishou", request.account_name)
    is_ready = await ks_setup(str(account_file), handle=False)
    if not is_ready:
        raise RuntimeError(
            f"Kuaishou cookie is missing or expired: {account_file}. Run `sau kuaishou login --account {request.account_name}` first."
        )

    app = _build_note_uploader(request, str(account_file))
    await app.main()
    return account_file


async def run(args):
    """执行本平台命令；发布结果由平台实现核验。"""
    if args.action == "login":
        reject_managed_login("kuaishou", args)
        require_local_account(args)
        result = await login_kuaishou_account(args.account, headless=args.headless)
        if not result["success"]:
            raise RuntimeError(result["message"])
        print(f"Kuaishou login flow completed: {result['account_file']}")
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

        is_valid = await check_kuaishou_account(account_label)
        print("valid" if is_valid else "invalid")
        return 0 if is_valid else 1

    publish_strategy = KUAISHOU_PUBLISH_STRATEGY_SCHEDULED if args.schedule else KUAISHOU_PUBLISH_STRATEGY_IMMEDIATE

    if args.action == "upload-video":
        request = KuaishouVideoUploadRequest(
            account_name=account_label,
            video_file=args.file,
            title=args.title,
            description=args.desc,
            tags=parse_tags(args.tags),
            publish_date=args.schedule or 0,
            thumbnail_file=args.thumbnail,
            publish_strategy=publish_strategy,
            debug=args.debug,
            headless=args.headless,
            collection_name=args.collection,
            publish_not_before=args.not_before,
        )
        await upload_kuaishou_video(request, target=target)
        print(f"Kuaishou video upload submitted: {request.video_file}")
        return 0

    if args.action == "upload-note":
        request = KuaishouNoteUploadRequest(
            account_name=account_label,
            image_files=parse_image_files(args.images),
            title=args.title,
            note=args.note,
            tags=parse_tags(args.tags),
            publish_date=args.schedule or 0,
            publish_strategy=publish_strategy,
            debug=args.debug,
            headless=args.headless,
            publish_not_before=args.not_before,
        )
        await upload_kuaishou_note(request, target=target)
        print(f"Kuaishou note upload submitted: {len(request.image_files)} images")
        return 0

    raise RuntimeError(f"Unsupported Kuaishou action: {args.action}")
