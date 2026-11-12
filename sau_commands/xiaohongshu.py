"""xiaohongshu 的命令参数与执行逻辑。"""
from __future__ import annotations
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from patchright.async_api import async_playwright
from uploader.xiaohongshu_uploader.main import (
    XHS_CONTENT_TYPES,
    XHS_CONTEXT_KWARGS,
    XHS_INIT_SCRIPT,
    XHS_LAUNCH_KWARGS,
    XHS_MAX_TAGS,
    XIAOHONGSHU_PUBLISH_STRATEGY_IMMEDIATE,
    XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED,
    XiaoHongShuNote,
    XiaoHongShuVideo,
    _blocked_message,
    _xhs_user_agent as xiaohongshu_user_agent,
    format_tag_cap_warning,
    local_session_preflight,
    probe_session,
    save_storage_state_atomic,
    xiaohongshu_setup,
)
from sau_commands.arguments import (
    SCHEDULE_HELP,
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
    managed_ignored_keys,
    reject_managed_login,
    require_local_account,
    resolve_account_label,
    resolve_managed_provider,
)
from utils.base_social_media import set_init_script
from utils.browser_session import browser_session
from utils.browser_session import log_local_session_ready
from utils.errors import LoginRequiredError, UsageError

CONTENT_TYPE_CHOICES = tuple(XHS_CONTENT_TYPES)
CONTENT_TYPE_HELP = (
    "添加内容类型声明：fiction=虚构演绎，仅供娱乐；ai=笔记含AI合成内容；"
    "marketing=内容包含营销广告；self-shot=内容来源声明/自主拍摄；"
    "repost=内容来源声明/来源转载（需配合 --repost-source）"
)


def _add_declaration_flags(parser) -> None:
    """注册原创声明与内容类型声明；默认两者都不操作页面。"""
    original_group = parser.add_mutually_exclusive_group()
    original_group.add_argument(
        "--original",
        dest="original",
        action="store_const",
        const=True,
        default=None,
        help="开启原创声明；不传则保持平台默认",
    )
    original_group.add_argument(
        "--no-original",
        dest="original",
        action="store_const",
        const=False,
        help="关闭原创声明；不传则保持平台默认",
    )
    parser.add_argument(
        "--content-type",
        choices=CONTENT_TYPE_CHOICES,
        default=None,
        help=CONTENT_TYPE_HELP,
    )
    parser.add_argument(
        "--repost-source",
        default=None,
        help="来源转载的媒体名称；仅在 --content-type repost 时使用",
    )
    parser.add_argument(
        "--shoot-location",
        default=None,
        help="自主拍摄的拍摄地点；仅在 --content-type self-shot 时使用",
    )
    parser.add_argument(
        "--shoot-date",
        default=None,
        help="自主拍摄的拍摄日期，格式 YYYY-MM-DD；仅在 self-shot 时使用",
    )
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="设置完内容和声明后停止，不点击发布（回归测试用）",
    )


def _validate_declarations(
    args,
) -> tuple[bool | None, str | None, str | None, str | None, str | None]:
    """在任何浏览器操作前校验声明参数组合。"""
    original = getattr(args, "original", None)
    content_type = getattr(args, "content_type", None)
    repost_source = (getattr(args, "repost_source", None) or "").strip()
    shoot_location = (getattr(args, "shoot_location", None) or "").strip()
    shoot_date = (getattr(args, "shoot_date", None) or "").strip()

    if content_type == "repost":
        if not repost_source:
            raise UsageError(
                "--content-type repost 需要同时提供 --repost-source <媒体名称>。"
            )
    elif repost_source:
        raise UsageError(
            "--repost-source 仅可与 --content-type repost 一起使用。"
        )

    if content_type == "self-shot":
        if not shoot_location or not shoot_date:
            raise UsageError(
                "--content-type self-shot 需要同时提供 "
                "--shoot-location <地点> 与 --shoot-date <YYYY-MM-DD>。"
            )
        try:
            datetime.strptime(shoot_date, "%Y-%m-%d")
        except ValueError as exc:
            raise UsageError(
                f"--shoot-date 格式错误：{shoot_date}，应为 YYYY-MM-DD。"
            ) from exc
    elif shoot_location or shoot_date:
        raise UsageError(
            "--shoot-location / --shoot-date 仅可与 --content-type self-shot 一起使用。"
        )

    if original is True and content_type == "repost":
        raise UsageError(
            "--original 不能与 --content-type repost 同时使用："
            "原创与来源转载互斥。"
        )
    if original is False and content_type in {"self-shot", "repost"}:
        raise UsageError(
            "--no-original 不能与 --content-type self-shot/repost 同时使用。"
        )

    return (
        original,
        content_type,
        repost_source or None,
        shoot_location or None,
        shoot_date or None,
    )


def register(platform_parsers):
    """声明本平台命令、参数及合法选项。"""
    xiaohongshu_parser = platform_parsers.add_parser("xiaohongshu", help="Xiaohongshu operations")
    xiaohongshu_actions = xiaohongshu_parser.add_subparsers(dest="action", required=True)

    for action_name in ("login", "check"):
        action_parser = xiaohongshu_actions.add_parser(action_name, help=f"Xiaohongshu {action_name}")
        action_parser.add_argument("--account", required=False, help="Xiaohongshu user-defined account_name")
        add_runtime_flags(action_parser)
        if action_name == "check":
            add_browser_flags(action_parser)

    xiaohongshu_upload_video_parser = xiaohongshu_actions.add_parser("upload-video", help="Upload one video to Xiaohongshu")
    xiaohongshu_upload_video_parser.add_argument("--account", required=False, help="Xiaohongshu user-defined account_name")
    xiaohongshu_upload_video_parser.add_argument("--file", required=True, type=existing_file_path, help="Video file path")
    xiaohongshu_upload_video_parser.add_argument("--title", required=True, help="Video title")
    xiaohongshu_upload_video_parser.add_argument("--desc", default="", help="Optional video description")
    xiaohongshu_upload_video_parser.add_argument("--tags", default="", help="Comma-separated tags, such as tag1,tag2")
    xiaohongshu_upload_video_parser.add_argument("--schedule", type=schedule_value, help=SCHEDULE_HELP)
    add_not_before_flag(xiaohongshu_upload_video_parser)
    xiaohongshu_upload_video_parser.add_argument("--thumbnail", type=existing_file_path, help="Optional thumbnail path")
    _add_declaration_flags(xiaohongshu_upload_video_parser)
    add_runtime_flags(xiaohongshu_upload_video_parser)
    add_browser_flags(xiaohongshu_upload_video_parser)

    xiaohongshu_upload_note_parser = xiaohongshu_actions.add_parser("upload-note", help="Upload one note to Xiaohongshu")
    xiaohongshu_upload_note_parser.add_argument("--account", required=False, help="Xiaohongshu user-defined account_name")
    xiaohongshu_upload_note_parser.add_argument("--images", required=True, nargs="+", type=existing_file_path, help="Image file paths")
    xiaohongshu_upload_note_parser.add_argument("--title", required=True, help="Note title")
    xiaohongshu_upload_note_parser.add_argument("--note", default="", help="Optional note content")
    xiaohongshu_upload_note_parser.add_argument("--tags", default="", help="Comma-separated tags, such as tag1,tag2")
    xiaohongshu_upload_note_parser.add_argument("--schedule", type=schedule_value, help=SCHEDULE_HELP)
    add_not_before_flag(xiaohongshu_upload_note_parser)
    _add_declaration_flags(xiaohongshu_upload_note_parser)
    add_runtime_flags(xiaohongshu_upload_note_parser)
    add_browser_flags(xiaohongshu_upload_note_parser)


@dataclass(slots=True)
class XiaohongshuVideoUploadRequest:
    account_name: str
    video_file: Path
    title: str
    description: str
    tags: list[str]
    publish_date: datetime | int
    thumbnail_file: Path | None = None
    publish_strategy: str = XIAOHONGSHU_PUBLISH_STRATEGY_IMMEDIATE
    debug: bool = False
    headless: bool = False
    original_declaration: bool | None = None
    content_type: str | None = None
    repost_source: str | None = None
    shoot_location: str | None = None
    shoot_date: str | None = None
    no_publish: bool = False
    publish_not_before: datetime | None = None


@dataclass(slots=True)
class XiaohongshuNoteUploadRequest:
    account_name: str
    image_files: list[Path]
    title: str
    note: str
    tags: list[str]
    publish_date: datetime | int
    publish_strategy: str = XIAOHONGSHU_PUBLISH_STRATEGY_IMMEDIATE
    debug: bool = False
    headless: bool = False
    original_declaration: bool | None = None
    content_type: str | None = None
    repost_source: str | None = None
    shoot_location: str | None = None
    shoot_date: str | None = None
    no_publish: bool = False
    publish_not_before: datetime | None = None


async def login_xiaohongshu_account(account_name: str, headless: bool = True) -> dict:
    account_file = resolve_account_file("xiaohongshu", account_name)
    return await xiaohongshu_setup(str(account_file), handle=True, return_detail=True, headless=headless)


async def check_xiaohongshu_account(
    account_name: str, *, headless: bool = False
) -> bool:
    """本地 `check`：零网络前置 → 一次发布页观测 → 成功才原子写回。"""
    account_file = resolve_account_file("xiaohongshu", account_name)
    await local_session_preflight(str(account_file))

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=headless, **XHS_LAUNCH_KWARGS
        )
        try:
            context = await browser.new_context(
                storage_state=str(account_file),
                user_agent=await xiaohongshu_user_agent(browser),
                **XHS_CONTEXT_KWARGS,
            )
            if XHS_INIT_SCRIPT:
                context = await set_init_script(context)
            log_local_session_ready(
                headless=headless, account_file=str(account_file)
            )
            try:
                kind, _evidence = await probe_session(context)
                if kind != "valid":
                    raise _probe_login_error(kind, "local")
                await save_storage_state_atomic(context, str(account_file))
                return True
            finally:
                await context.close()
        finally:
            await browser.close()


def _build_video_uploader(request: XiaohongshuVideoUploadRequest, account_file) -> XiaoHongShuVideo:
    app = XiaoHongShuVideo(
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
        original_declaration=request.original_declaration,
        content_type=request.content_type,
        repost_source=request.repost_source,
        shoot_location=request.shoot_location,
        shoot_date=request.shoot_date,
        no_publish=request.no_publish,
    )
    app.publish_not_before = request.publish_not_before
    return app


def _build_note_uploader(request: XiaohongshuNoteUploadRequest, account_file) -> XiaoHongShuNote:
    app = XiaoHongShuNote(
        image_paths=[str(path) for path in request.image_files],
        title=request.title,
        desc=request.note,
        note=request.note,
        tags=request.tags,
        publish_date=request.publish_date,
        account_file=account_file,
        publish_strategy=request.publish_strategy,
        debug=request.debug,
        headless=request.headless,
        original_declaration=request.original_declaration,
        content_type=request.content_type,
        repost_source=request.repost_source,
        shoot_location=request.shoot_location,
        shoot_date=request.shoot_date,
        no_publish=request.no_publish,
    )
    app.publish_not_before = request.publish_not_before
    return app


def _probe_login_error(kind: str, mode: str) -> LoginRequiredError:
    return LoginRequiredError(
        _blocked_message(kind, mode, publish_attempted=False),
        reason=kind,
        publish_attempted=False,
    )


async def _check_managed_xiaohongshu(
    target, *, headless: bool, ignored_keys: tuple[str, ...]
) -> None:
    """托管 `check`：同一 context 里导航一次发布页；不读不写 cookie。"""
    async with async_playwright() as playwright:
        async with browser_session(
            playwright,
            headless=headless,
            account_file=None,
            managed=target,
            extra_ignored=ignored_keys,
        ) as session:
            kind, _evidence = await probe_session(session.context)
    if kind != "valid":
        raise _probe_login_error(kind, target.mode)


async def upload_xiaohongshu_video(
    request: XiaohongshuVideoUploadRequest,
    *,
    target=None,
    ignored_keys: tuple[str, ...] = (),
) -> Path | None:
    if target is not None:
        app = _build_video_uploader(request, None)
        async with async_playwright() as playwright:
            async with browser_session(
                playwright,
                headless=request.headless,
                account_file=None,
                managed=target,
                launch_kwargs=XHS_LAUNCH_KWARGS,
                context_kwargs=XHS_CONTEXT_KWARGS,
                init_script=XHS_INIT_SCRIPT,
                extra_ignored=ignored_keys,
            ) as session:
                await app.xiaohongshu_upload_video(session=session)
        return None

    account_file = resolve_account_file("xiaohongshu", request.account_name)
    app = _build_video_uploader(request, str(account_file))
    await app.main()
    return account_file


async def upload_xiaohongshu_note(
    request: XiaohongshuNoteUploadRequest,
    *,
    target=None,
    ignored_keys: tuple[str, ...] = (),
) -> Path | None:
    if target is not None:
        app = _build_note_uploader(request, None)
        async with async_playwright() as playwright:
            async with browser_session(
                playwright,
                headless=request.headless,
                account_file=None,
                managed=target,
                launch_kwargs=XHS_LAUNCH_KWARGS,
                context_kwargs=XHS_CONTEXT_KWARGS,
                init_script=XHS_INIT_SCRIPT,
                extra_ignored=ignored_keys,
            ) as session:
                await app.xiaohongshu_upload_note(session=session)
        return None

    account_file = resolve_account_file("xiaohongshu", request.account_name)
    app = _build_note_uploader(request, str(account_file))
    await app.main()
    return account_file


async def run(args):
    """执行本平台命令；发布结果由平台实现核验。"""
    if args.action == "login":
        reject_managed_login("xiaohongshu", args)
        require_local_account(args)
        result = await login_xiaohongshu_account(args.account, headless=args.headless)
        if not result["success"]:
            raise RuntimeError(result["message"])
        print(f"Xiaohongshu login flow completed: {result['account_file']}")
        return 0

    original_declaration = content_type = repost_source = None
    shoot_location = shoot_date = None
    if args.action in {"upload-video", "upload-note"}:
        (
            original_declaration,
            content_type,
            repost_source,
            shoot_location,
            shoot_date,
        ) = _validate_declarations(args)

    target = resolve_managed_provider(args)
    require_local_account(args)
    account_label = resolve_account_label(args)
    # Managed mode cannot honour --account; report it in the session warning.
    ignored_keys = managed_ignored_keys(args)

    if args.action == "check":
        if target is not None:
            try:
                await _check_managed_xiaohongshu(
                    target,
                    headless=getattr(args, "headless", False),
                    ignored_keys=ignored_keys,
                )
            except Exception:
                print("invalid")
                raise
            print("valid")
            return 0

        try:
            is_valid = await check_xiaohongshu_account(
                account_label,
                headless=getattr(args, "headless", False),
            )
        except Exception:
            print("invalid")
            raise
        print("valid" if is_valid else "invalid")
        return 0 if is_valid else 1

    publish_strategy = (
        XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED if args.schedule else XIAOHONGSHU_PUBLISH_STRATEGY_IMMEDIATE
    )

    if args.action == "upload-video":
        parsed_tags = parse_tags(args.tags)
        if len(parsed_tags) > XHS_MAX_TAGS:
            print(f"警告：{format_tag_cap_warning(parsed_tags)}", file=sys.stderr)
        request = XiaohongshuVideoUploadRequest(
            account_name=account_label,
            video_file=args.file,
            title=args.title,
            description=args.desc,
            tags=parsed_tags,
            publish_date=args.schedule or 0,
            thumbnail_file=args.thumbnail,
            publish_strategy=publish_strategy,
            debug=args.debug,
            headless=args.headless,
            original_declaration=original_declaration,
            content_type=content_type,
            repost_source=repost_source,
            shoot_location=shoot_location,
            shoot_date=shoot_date,
            no_publish=getattr(args, "no_publish", False),
            publish_not_before=args.not_before,
        )
        await upload_xiaohongshu_video(
            request, target=target, ignored_keys=ignored_keys
        )
        print(f"Xiaohongshu video upload submitted: {request.video_file}")
        return 0

    if args.action == "upload-note":
        parsed_tags = parse_tags(args.tags)
        if len(parsed_tags) > XHS_MAX_TAGS:
            print(f"警告：{format_tag_cap_warning(parsed_tags)}", file=sys.stderr)
        request = XiaohongshuNoteUploadRequest(
            account_name=account_label,
            image_files=parse_image_files(args.images),
            title=args.title,
            note=args.note,
            tags=parsed_tags,
            publish_date=args.schedule or 0,
            publish_strategy=publish_strategy,
            debug=args.debug,
            headless=args.headless,
            original_declaration=original_declaration,
            content_type=content_type,
            repost_source=repost_source,
            shoot_location=shoot_location,
            shoot_date=shoot_date,
            no_publish=getattr(args, "no_publish", False),
            publish_not_before=args.not_before,
        )
        await upload_xiaohongshu_note(
            request, target=target, ignored_keys=ignored_keys
        )
        print(f"Xiaohongshu note upload submitted: {len(request.image_files)} images")
        return 0

    raise RuntimeError(f"Unsupported Xiaohongshu action: {args.action}")
