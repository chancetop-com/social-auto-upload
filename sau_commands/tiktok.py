"""tiktok 的命令参数与执行逻辑（本地 cookie 模式 / Multilogin 模式）。

未设置 ``MLX_API_TOKEN`` 时使用本地 Chromium 与
``cookies/tiktok_<account>.json``；设置后使用 Multilogin Profile。本地模式会
自动切换页面语言，MLX Profile 仍需 English (US)。
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from patchright.async_api import async_playwright

from sau_commands.arguments import (
    SCHEDULE_HELP,
    add_not_before_flag,
    add_runtime_flags,
    existing_file_path,
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

from uploader.tk_uploader.main_chrome import (
    TIKTOK_CONTEXT_KWARGS,
    TIKTOK_IMAGE_SUFFIXES,
    TIKTOK_INIT_SCRIPT,
    TIKTOK_LAUNCH_KWARGS,
    TIKTOK_MAX_DESCRIPTION_LENGTH,
    TIKTOK_MAX_HASHTAG_COUNT,
    TIKTOK_MAX_IMAGE_BYTES,
    TIKTOK_MAX_IMAGE_COUNT,
    TIKTOK_MAX_TITLE_LENGTH,
    TiktokNote,
    TiktokPublishOptions,
    TiktokVideo,
    is_logged_in,
    tiktok_setup,
)
from utils.browser_session import browser_session
from utils.errors import UsageError

TIKTOK_ACCOUNT_HELP = (
    "TikTok account name; local mode uses cookies/tiktok_<account>.json, "
    "MLX mode uses it as a log label"
)


def _read_note_file(value: str) -> str:
    """Read ``--notef`` (txt/md) at parse time, before any browser work."""
    path = Path(value)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise argparse.ArgumentTypeError(
            f"无法读取文案文件: {value}（{exc}）"
        ) from exc


def _add_publish_option_flags(parser, *, include_reuse: bool) -> None:
    """Register the shared privacy/interaction/AIGC/brand flags."""
    parser.add_argument(
        "--privacy",
        choices=("public", "friends", "followers", "only-me"),
        help=(
            "Set post privacy (public/friends/followers/only-me); "
            "omit to leave the page default"
        ),
    )
    parser.add_argument(
        "--no-comments",
        action="store_true",
        help="Turn off Allow comments; omit to leave the page default",
    )
    if include_reuse:
        parser.add_argument(
            "--disable-reuse",
            action="store_true",
            help=(
                "Turn off Allow reuse of content (also affects Duet, Stitch, "
                "Stickers and Story); omit to leave the page default"
            ),
        )
    aigc_group = parser.add_mutually_exclusive_group()
    aigc_group.add_argument(
        "--aigc",
        dest="aigc",
        action="store_const",
        const=True,
        default=None,
        help=(
            "Turn on AI-generated content labeling; omit to leave the page "
            "default"
        ),
    )
    aigc_group.add_argument(
        "--no-aigc",
        dest="aigc",
        action="store_const",
        const=False,
        help="Turn off AI-generated content labeling",
    )
    parser.add_argument(
        "--your-brand",
        action="store_true",
        default=None,
        help=(
            "Disclose the post as promoting your own brand; opens "
            "Disclose post content automatically"
        ),
    )
    parser.add_argument(
        "--branded-content",
        action="store_true",
        default=None,
        help=(
            "Disclose the post as paid branded content; cannot be combined "
            "with --privacy only-me"
        ),
    )
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="跑到发布就绪点即停止，不点击发布（回归测试用）",
    )


def register(platform_parsers):
    """声明本平台命令、参数及合法选项。"""
    tiktok_parser = platform_parsers.add_parser(
        "tiktok", help="TikTok operations (local or Multilogin mode)"
    )
    tiktok_actions = tiktok_parser.add_subparsers(dest="action", required=True)

    for action_name in ("login", "check"):
        action_parser = tiktok_actions.add_parser(
            action_name, help=f"TikTok {action_name}"
        )
        action_parser.add_argument(
            "--account",
            required=False,
            help=TIKTOK_ACCOUNT_HELP,
        )
        add_runtime_flags(action_parser)
        # Repo-wide contract: ``login`` never accepts Profile flags.  They are
        # only meaningful for check/upload actions.
        if action_name == "check":
            add_browser_flags(action_parser)

    upload_video_parser = tiktok_actions.add_parser(
        "upload-video", help="Upload one video to TikTok"
    )
    upload_video_parser.add_argument(
        "--account",
        required=False,
        help=TIKTOK_ACCOUNT_HELP,
    )
    upload_video_parser.add_argument(
        "--file", required=True, type=existing_file_path, help="Video file path"
    )
    upload_video_parser.add_argument("--title", required=True, help="Video title")
    upload_video_parser.add_argument(
        "--tags", default="", help="Comma-separated tags, such as tag1,tag2"
    )
    upload_video_parser.add_argument(
        "--schedule", type=schedule_value, help=SCHEDULE_HELP
    )
    add_not_before_flag(upload_video_parser)
    upload_video_parser.add_argument(
        "--thumbnail", type=existing_file_path, help="Optional thumbnail path"
    )
    _add_publish_option_flags(upload_video_parser, include_reuse=True)
    add_runtime_flags(upload_video_parser)
    add_browser_flags(upload_video_parser)

    upload_note_parser = tiktok_actions.add_parser(
        "upload-note", help="Upload one photo post to TikTok"
    )
    upload_note_parser.add_argument(
        "--account",
        required=False,
        help=TIKTOK_ACCOUNT_HELP,
    )
    upload_note_parser.add_argument(
        "--images",
        required=True,
        nargs="+",
        type=existing_file_path,
        help="1-35 image file paths, in display order (first is the cover)",
    )
    upload_note_parser.add_argument(
        "--title",
        default=None,
        help="Optional photo Title (up to 90 characters); omit to leave it empty",
    )
    note_group = upload_note_parser.add_mutually_exclusive_group()
    note_group.add_argument(
        "--note",
        default=None,
        help="Photo Description text; omit to leave it empty",
    )
    note_group.add_argument(
        "--notef",
        default=None,
        type=_read_note_file,
        help="Read the Description from a local txt/md file",
    )
    upload_note_parser.add_argument(
        "--tags", default="", help="Comma-separated tags, such as tag1,tag2"
    )
    upload_note_parser.add_argument(
        "--schedule", type=schedule_value, help=SCHEDULE_HELP
    )
    add_not_before_flag(upload_note_parser)
    # Photo posts have no content-reuse control, so ``--disable-reuse`` is not
    # registered here.  The first image is the cover: no thumbnail/cover flag.
    _add_publish_option_flags(upload_note_parser, include_reuse=False)
    add_runtime_flags(upload_note_parser)
    add_browser_flags(upload_note_parser)


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
    account_file: Path | None = None
    publish_not_before: datetime | None = None
    no_publish: bool = False


def _build_publish_options(args) -> TiktokPublishOptions | None:
    """Map CLI flags to the uploader's tri-state options.

    Every ``None`` means "do not touch the page default".  When all six are
    ``None`` the legacy code path stays genuinely untouched (``options=None``).
    Absent brand flags stay ``None``; the uploader normalizes the other brand
    checkbox to an explicit ``False`` only when a brand disclosure is requested.
    """
    privacy = getattr(args, "privacy", None) or None
    allow_comments = False if getattr(args, "no_comments", False) else None
    allow_reuse = False if getattr(args, "disable_reuse", False) else None
    aigc = getattr(args, "aigc", None)
    your_brand = getattr(args, "your_brand", None)
    branded_content = getattr(args, "branded_content", None)
    if (
        privacy is None
        and allow_comments is None
        and allow_reuse is None
        and aigc is None
        and your_brand is None
        and branded_content is None
    ):
        return None
    return TiktokPublishOptions(
        privacy=privacy,
        allow_comments=allow_comments,
        allow_reuse=allow_reuse,
        aigc=aigc,
        your_brand=your_brand,
        branded_content=branded_content,
    )


def _validate_branded_content_privacy(args) -> None:
    """Reject ``--branded-content`` + ``--privacy only-me`` before any browser.

    TikTok Studio disables the ``Branded content`` checkbox for private posts,
    so this is a local usage error (exit 2) rather than an upload failure.
    """
    if getattr(args, "branded_content", None) and (
        getattr(args, "privacy", None) == "only-me"
    ):
        raise UsageError(
            "--branded-content 不能与 --privacy only-me 同时使用："
            "TikTok 要求 Branded content 帖子必须为 Public 或 Friends。"
        )


def _build_video_uploader(request: TiktokVideoUploadRequest) -> TiktokVideo:
    """Build the uploader with the legacy positional order.

    ``request.account_file`` is ``None`` in Multilogin mode and the local cookie
    path in local mode.
    """
    app = TiktokVideo(
        request.title,
        str(request.video_file),
        request.tags,
        request.publish_date,
        str(request.account_file) if request.account_file else None,
        thumbnail_path=(
            str(request.thumbnail_file) if request.thumbnail_file else None
        ),
        options=request.options,
        headless=request.headless,
        no_publish=request.no_publish,
    )
    app.publish_not_before = request.publish_not_before
    return app


@dataclass(slots=True)
class TiktokNoteUploadRequest:
    account_label: str | None
    image_files: list[Path]
    note: str | None
    tags: list[str]
    publish_date: datetime | int
    title: str | None = None
    debug: bool = True
    headless: bool = True
    options: TiktokPublishOptions | None = None
    account_file: Path | None = None
    publish_not_before: datetime | None = None
    no_publish: bool = False


def _note_text(args) -> str | None:
    """Resolve the Description from ``--note`` or ``--notef`` (already read)."""
    note = getattr(args, "note", None)
    if note is not None:
        return note
    return getattr(args, "notef", None)


def _render_description(note: str | None, tags: list[str]) -> str:
    """Text the page will hold after tags are expanded to ``#tag`` chips."""
    text = note or ""
    if not tags:
        return text
    hashtags = " ".join(f"#{tag}" for tag in tags)
    return f"{text}\n{hashtags}" if text else hashtags


def _validate_note_metadata(
    title: str | None,
    note: str | None,
    tags: list[str],
    *,
    scheduled: bool = False,
) -> None:
    """Reject over-limit Title/Description/hashtags before any browser work.

    Values are never truncated; each failure is a usage error (exit 2).
    """
    if scheduled and not (title or note):
        raise UsageError(
            "定时图片帖必须提供 --title 或 --note/--notef：仅 tags 无法在 "
            "Content 列表稳定定位该帖，发布后也无法核验定时是否成功。"
        )

    if title is not None and len(title) > TIKTOK_MAX_TITLE_LENGTH:
        raise UsageError(
            f"图片帖 Title 过长：{len(title)} 字符，"
            f"上限 {TIKTOK_MAX_TITLE_LENGTH} 字符（不会截断）。"
        )

    description = _render_description(note, tags)
    if len(description) > TIKTOK_MAX_DESCRIPTION_LENGTH:
        raise UsageError(
            f"图片帖 Description 过长：{len(description)} 字符，"
            f"上限 {TIKTOK_MAX_DESCRIPTION_LENGTH} 字符（不会截断）。"
        )

    if len(tags) > TIKTOK_MAX_HASHTAG_COUNT:
        raise UsageError(
            f"图片帖 hashtag 过多：{len(tags)} 个，"
            f"上限 {TIKTOK_MAX_HASHTAG_COUNT} 个。"
        )



def _validate_note_images(image_files: list[Path]) -> None:
    """Reject bad photo-post input before any browser/session work.

    Errors are reported verbatim (never truncated) and map to exit code 2.
    Extension matching is case-insensitive.
    """
    count = len(image_files)
    if count < 1:
        raise UsageError(
            f"图片帖至少需要 1 张图片，当前 {count} 张。"
        )
    if count > TIKTOK_MAX_IMAGE_COUNT:
        raise UsageError(
            f"图片帖最多 {TIKTOK_MAX_IMAGE_COUNT} 张图片，当前 {count} 张。"
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
    app = TiktokNote(
        [str(path) for path in request.image_files],
        request.note,
        request.tags,
        request.publish_date,
        str(request.account_file) if request.account_file else None,
        title=request.title,
        options=request.options,
        debug=request.debug,
        headless=request.headless,
        no_publish=request.no_publish,
    )
    app.publish_not_before = request.publish_not_before
    return app


async def _require_local_cookie(account_file, account_label: str, headless: bool) -> None:
    """Fail with a human-actionable message when the local cookie is invalid."""
    ready = await tiktok_setup(str(account_file), handle=False, headless=headless)
    if not ready:
        raise RuntimeError(
            f"TikTok cookie 不存在或已失效：{account_file}。"
            f"请先运行 `sau tiktok login --account {account_label}`。"
        )


async def _prepare_account_file(args, target, account_label):
    """Resolve and validate the local cookie; ``None`` in MLX mode."""
    if target is not None:
        return None
    account_file = resolve_account_file("tiktok", args.account)
    await _require_local_cookie(account_file, account_label, args.headless)
    return account_file


async def _upload_media(request, target, builder) -> None:
    """Run any TikTok upload in MLX (session) or local (own browser) mode."""
    app = builder(request)
    if target is not None:
        async with async_playwright() as playwright:
            async with browser_session(
                playwright,
                headless=request.headless,
                account_file=None,
                managed=target,
                launch_kwargs=TIKTOK_LAUNCH_KWARGS,
                context_kwargs=TIKTOK_CONTEXT_KWARGS,
                init_script=TIKTOK_INIT_SCRIPT,
            ) as session:
                if not await is_logged_in(session.context):
                    _raise_login_required(target)
                await app.upload(None, session=session)
        return

    async with async_playwright() as playwright:
        await app.upload(playwright)


async def _upload_note(request: TiktokNoteUploadRequest, target) -> None:
    await _upload_media(request, target, _build_note_uploader)


async def _upload_video(request: TiktokVideoUploadRequest, target) -> None:
    await _upload_media(request, target, _build_video_uploader)


def _raise_login_required(target) -> None:
    raise login_required_error("TikTok", target.profile_id, mode=target.mode)


async def run(args):
    """执行本平台命令；本地 cookie 模式与 Multilogin 模式共用上传器。"""
    # Reject impossible option combinations before resolving the Profile or
    # touching any browser/session state (exit 2).
    _validate_branded_content_privacy(args)

    note_inputs = None
    if args.action == "upload-note":
        # Validate the whole photo-post input before resolving the Profile or
        # touching any browser state so bad input never opens a session.
        image_files = [Path(path) for path in args.images]
        title = getattr(args, "title", None)
        note = _note_text(args)
        tags = parse_tags(getattr(args, "tags", ""))
        _validate_note_images(image_files)
        _validate_note_metadata(
            title, note, tags, scheduled=bool(args.schedule)
        )
        note_inputs = (image_files, title, note, tags)

    if args.action == "login":
        # Multilogin profiles are logged in through the Multilogin app.
        reject_managed_login("tiktok", args)
        require_local_account(args)
        account_file = resolve_account_file("tiktok", args.account)
        ready = await tiktok_setup(
            str(account_file), handle=True, headless=False, force=True
        )
        if not ready:
            raise RuntimeError(
                f"TikTok 登录未完成或 cookie 仍无效：{account_file}。"
            )
        print(f"TikTok login flow completed: {account_file}")
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

        account_file = resolve_account_file("tiktok", args.account)
        is_valid = await tiktok_setup(
            str(account_file), handle=False, headless=args.headless
        )
        print("valid" if is_valid else "invalid")
        return 0 if is_valid else 1

    if args.action == "upload-note":
        image_files, title, note, tags = note_inputs
        account_file = await _prepare_account_file(
            args, target, account_label
        )
        request = TiktokNoteUploadRequest(
            account_label=account_label,
            image_files=image_files,
            note=note,
            tags=tags,
            publish_date=args.schedule or 0,
            title=title,
            debug=args.debug,
            headless=args.headless,
            options=_build_publish_options(args),
            account_file=account_file,
            publish_not_before=args.not_before,
            no_publish=getattr(args, "no_publish", False),
        )
        await _upload_note(request, target)
        print(
            f"TikTok note upload submitted: {len(request.image_files)} images"
        )
        return 0

    if args.action == "upload-video":
        account_file = await _prepare_account_file(
            args, target, account_label
        )
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
            account_file=account_file,
            publish_not_before=args.not_before,
            no_publish=getattr(args, "no_publish", False),
        )
        await _upload_video(request, target)
        print(f"TikTok video upload submitted: {request.video_file}")
        return 0

    raise RuntimeError(f"Unsupported TikTok action: {args.action}")
