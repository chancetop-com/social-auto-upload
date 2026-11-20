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
    format_tag_cap_warning,
    probe_session,
    xiaohongshu_setup,
)
from sau_commands.output import report_ai_declaration, report_upload_success
from sau_commands.local_profile import add_reset_profile_action, run_reset_profile
from sau_commands.publish_media import add_task_id, media_source
from sau_commands.arguments import (
    SCHEDULE_HELP,
    ContentTypeAction,
    add_not_before_flag,
    add_local_runtime_flags,
    parse_image_files,
    parse_tags,
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
from sau_commands.arguments import single_line_value
from utils.text_validation import validate_single_line
from utils.browser_session import browser_session
from utils.local_browser_session import local_browser_session
from utils.local_browser import resolve_headless
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
        action=ContentTypeAction,
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
    add_reset_profile_action(xiaohongshu_actions)

    for action_name in ("login", "check"):
        action_parser = xiaohongshu_actions.add_parser(action_name, help=f"Xiaohongshu {action_name}")
        action_parser.add_argument("--account", required=False, help="Xiaohongshu user-defined account_name")
        add_local_runtime_flags(action_parser)
        if action_name == "check":
            add_browser_flags(action_parser)

    xiaohongshu_upload_video_parser = xiaohongshu_actions.add_parser("upload-video", help="Upload one video to Xiaohongshu")
    xiaohongshu_upload_video_parser.add_argument("--account", required=False, help="Xiaohongshu user-defined account_name")
    add_task_id(xiaohongshu_upload_video_parser)
    xiaohongshu_upload_video_parser.add_argument(
        "--file", required=True, type=media_source, help="Local video path or HTTP(S) URL"
    )
    xiaohongshu_upload_video_parser.add_argument("--title", type=single_line_value, required=True, help="Video title")
    xiaohongshu_upload_video_parser.add_argument("--desc", default="", help="Optional video description")
    xiaohongshu_upload_video_parser.add_argument("--tags", default="", help="Comma-separated tags, such as tag1,tag2")
    xiaohongshu_upload_video_parser.add_argument("--schedule", type=schedule_value, help=SCHEDULE_HELP)
    add_not_before_flag(xiaohongshu_upload_video_parser)
    xiaohongshu_upload_video_parser.add_argument(
        "--thumbnail", type=media_source, help="Local thumbnail path or HTTP(S) URL"
    )
    _add_declaration_flags(xiaohongshu_upload_video_parser)
    add_local_runtime_flags(xiaohongshu_upload_video_parser)
    add_browser_flags(xiaohongshu_upload_video_parser)

    xiaohongshu_upload_note_parser = xiaohongshu_actions.add_parser("upload-note", help="Upload one note to Xiaohongshu")
    xiaohongshu_upload_note_parser.add_argument("--account", required=False, help="Xiaohongshu user-defined account_name")
    add_task_id(xiaohongshu_upload_note_parser)
    xiaohongshu_upload_note_parser.add_argument(
        "--images", required=True, nargs="+", type=media_source, help="Local image paths or HTTP(S) URLs in post order"
    )
    xiaohongshu_upload_note_parser.add_argument("--title", type=single_line_value, required=True, help="Note title")
    xiaohongshu_upload_note_parser.add_argument("--note", default="", help="Optional note content")
    xiaohongshu_upload_note_parser.add_argument("--tags", default="", help="Comma-separated tags, such as tag1,tag2")
    xiaohongshu_upload_note_parser.add_argument("--schedule", type=schedule_value, help=SCHEDULE_HELP)
    add_not_before_flag(xiaohongshu_upload_note_parser)
    _add_declaration_flags(xiaohongshu_upload_note_parser)
    add_local_runtime_flags(xiaohongshu_upload_note_parser)
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
    headless: bool | None = None
    original_declaration: bool | None = None
    content_type: str | None = None
    repost_source: str | None = None
    shoot_location: str | None = None
    shoot_date: str | None = None
    no_publish: bool = False
    publish_not_before: datetime | None = None
    local_browser: str | None = None
    declaration_report: dict[str, str | None] | None = None


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
    headless: bool | None = None
    original_declaration: bool | None = None
    content_type: str | None = None
    repost_source: str | None = None
    shoot_location: str | None = None
    shoot_date: str | None = None
    no_publish: bool = False
    publish_not_before: datetime | None = None
    local_browser: str | None = None
    declaration_report: dict[str, str | None] | None = None


async def login_xiaohongshu_account(account_name: str, headless=None, local_browser=None) -> dict:
    return await xiaohongshu_setup(account_name=account_name, handle=True,
                                  return_detail=True, headless=headless,
                                  local_browser=local_browser)


async def check_xiaohongshu_account(
    account_name: str, *, headless=None, local_browser=None
) -> bool:
    """Observe the publishing page in the selected persistent Profile."""
    async with async_playwright() as playwright:
        async with local_browser_session(
            playwright, platform="xiaohongshu", account=account_name,
            headless=headless, local_browser=local_browser,
        ) as session:
            kind, _evidence = await probe_session(session.context, close_page=False)
            if kind != "valid":
                raise _probe_login_error(kind, "local")
            return True


def _build_video_uploader(request: XiaohongshuVideoUploadRequest) -> XiaoHongShuVideo:
    app = XiaoHongShuVideo(
        title=request.title,
        file_path=str(request.video_file),
        desc=request.description,
        tags=request.tags,
        publish_date=request.publish_date,
        account_file=None,
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
        account_name=request.account_name,
        local_browser=request.local_browser,
    )
    app.publish_not_before = request.publish_not_before
    return app


def _build_note_uploader(request: XiaohongshuNoteUploadRequest) -> XiaoHongShuNote:
    app = XiaoHongShuNote(
        image_paths=[str(path) for path in request.image_files],
        title=request.title,
        desc=request.note,
        note=request.note,
        tags=request.tags,
        publish_date=request.publish_date,
        account_file=None,
        publish_strategy=request.publish_strategy,
        debug=request.debug,
        headless=request.headless,
        original_declaration=request.original_declaration,
        content_type=request.content_type,
        repost_source=request.repost_source,
        shoot_location=request.shoot_location,
        shoot_date=request.shoot_date,
        no_publish=request.no_publish,
        account_name=request.account_name,
        local_browser=request.local_browser,
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
    validate_single_line(request.title)
    if target is not None:
        app = _build_video_uploader(request)
        async with async_playwright() as playwright:
            async with browser_session(
                playwright,
                headless=resolve_headless(request.headless),
                account_file=None,
                managed=target,
                launch_kwargs=XHS_LAUNCH_KWARGS,
                context_kwargs=XHS_CONTEXT_KWARGS,
                init_script=XHS_INIT_SCRIPT,
                extra_ignored=ignored_keys,
            ) as session:
                await app.xiaohongshu_upload_video(session=session)
        request.declaration_report = getattr(app, "declaration_report", None)
        return None

    app = _build_video_uploader(request)
    await app.main()
    request.declaration_report = getattr(app, "declaration_report", None)
    return None


async def upload_xiaohongshu_note(
    request: XiaohongshuNoteUploadRequest,
    *,
    target=None,
    ignored_keys: tuple[str, ...] = (),
) -> Path | None:
    validate_single_line(request.title)
    if target is not None:
        app = _build_note_uploader(request)
        async with async_playwright() as playwright:
            async with browser_session(
                playwright,
                headless=resolve_headless(request.headless),
                account_file=None,
                managed=target,
                launch_kwargs=XHS_LAUNCH_KWARGS,
                context_kwargs=XHS_CONTEXT_KWARGS,
                init_script=XHS_INIT_SCRIPT,
                extra_ignored=ignored_keys,
            ) as session:
                await app.xiaohongshu_upload_note(session=session)
        request.declaration_report = getattr(app, "declaration_report", None)
        return None

    app = _build_note_uploader(request)
    await app.main()
    request.declaration_report = getattr(app, "declaration_report", None)
    return None


async def run(args):
    """执行本平台命令；发布结果由平台实现核验。"""
    if args.action == "reset-profile":
        return run_reset_profile(args)
    if args.action == "login":
        reject_managed_login("xiaohongshu", args)
        require_local_account(args)
        result = await login_xiaohongshu_account(args.account, headless=args.headless, local_browser=getattr(args, "local_browser", None))
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
                    headless=resolve_headless(getattr(args, "headless", None)),
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
                headless=getattr(args, "headless", None),
                local_browser=getattr(args, "local_browser", None),
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
            local_browser=getattr(args, "local_browser", None),
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
        report_ai_declaration(request)
        args.post_published = report_upload_success(request, "Xiaohongshu video", request.video_file)
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
            local_browser=getattr(args, "local_browser", None),
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
        report_ai_declaration(request)
        args.post_published = report_upload_success(request, "Xiaohongshu note", f"{len(request.image_files)} images")
        return 0

    raise RuntimeError(f"Unsupported Xiaohongshu action: {args.action}")
