"""instagram 的命令参数与执行逻辑。"""
from __future__ import annotations
import json
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from loguru import logger
from patchright.async_api import async_playwright
from uploader.meta_uploader.insgraph_uploader.main import (
    INSTAGRAM_CONTEXT_KWARGS,
    INSTAGRAM_INIT_SCRIPT,
    INSTAGRAM_LAUNCH_KWARGS,
    INSTAGRAM_PROXY,
    InstagramUploader,
    instagram_cookie_auth,
    instagram_setup,
    is_logged_in,
)
from uploader.meta_uploader.insgraph_uploader.options import (
    InstagramPublishOptions,
    instagram_caption,
    validate_publish_options,
)
from uploader.meta_uploader.insgraph_uploader.posts import instagram_post_action
from sau_commands.arguments import (
    SCHEDULE_FORMAT,
    add_not_before_flag,
    add_runtime_flags,
    existing_file_path,
    parse_image_files,
    parse_tags,
    resolve_account_file,
)
from sau_commands.browser import (
    add_browser_flags,
    identity_unverified_format,
    login_required_error,
    reject_managed_login,
    require_account,
    require_local_account,
    resolve_account_label,
    resolve_managed_provider,
)
from utils.browser_session import browser_session


def register(platform_parsers):
    """声明本平台命令、参数及合法选项。"""
    schedule_help = SCHEDULE_FORMAT.replace("%", "%%")
    instagram_parser = platform_parsers.add_parser("instagram", help="Instagram independent web operations")
    instagram_actions = instagram_parser.add_subparsers(dest="action", required=True)
    for action_name in ("login", "check"):
        action_parser = instagram_actions.add_parser(action_name, help=f"Instagram {action_name}")
        action_parser.add_argument("--account", required=False)
        action_parser.add_argument("--proxy", default=INSTAGRAM_PROXY, help="代理地址；不传时直连")
        if action_name == "login":
            add_runtime_flags(action_parser)
            action_parser.set_defaults(headless=False)
        else:
            add_runtime_flags(action_parser)
            add_browser_flags(action_parser)
    instagram_video = instagram_actions.add_parser("upload-video", help="向 Instagram 发布视频/Reel")
    instagram_video.add_argument("--account", required=False)
    instagram_video.add_argument("--file", required=True, type=existing_file_path)
    instagram_video.add_argument("--thumbnail", type=existing_file_path, help="Reel 自定义封面（JPG/JPEG/PNG）")
    instagram_video.add_argument("--title", required=True)
    instagram_video.add_argument("--desc", default="")
    instagram_video.add_argument("--tags", default="")
    instagram_video.add_argument("--proxy", default=INSTAGRAM_PROXY, help="代理地址；不传时直连")
    instagram_video.add_argument("--result", type=Path)
    add_not_before_flag(instagram_video)
    _add_instagram_option_flags(instagram_video, include_alt_text=False)
    add_runtime_flags(instagram_video)
    add_browser_flags(instagram_video)
    instagram_video.set_defaults(headless=False)
    instagram_note = instagram_actions.add_parser("upload-note", help="向 Instagram 发布图片或轮播")
    instagram_note.add_argument("--account", required=False)
    instagram_note.add_argument("--images", required=True, nargs="+", type=existing_file_path)
    instagram_note.add_argument("--title", required=True)
    instagram_note.add_argument("--note", default="")
    instagram_note.add_argument("--tags", default="")
    instagram_note.add_argument("--proxy", default=INSTAGRAM_PROXY, help="代理地址；不传时直连")
    instagram_note.add_argument("--result", type=Path)
    add_not_before_flag(instagram_note)
    _add_instagram_option_flags(instagram_note, include_alt_text=True)
    add_runtime_flags(instagram_note)
    add_browser_flags(instagram_note)
    instagram_note.set_defaults(headless=False)
    for action_name in ("verify", "delete"):
        action_parser = instagram_actions.add_parser(action_name, help="核对 Instagram 原作品" if action_name == "verify" else "核对后将 Instagram 原作品移至最近删除")
        action_parser.add_argument("--account", required=False)
        action_parser.add_argument("--post-url", required=True)
        action_parser.add_argument("--expected-text", required=True)
        action_parser.add_argument("--proxy", default=INSTAGRAM_PROXY, help="代理地址；不传时直连")
        action_parser.add_argument("--result", type=Path)
        add_runtime_flags(action_parser)
        action_parser.set_defaults(headless=False)


def _add_instagram_option_flags(parser, *, include_alt_text: bool) -> None:
    """注册发布选项参数（spec §3.1）；每个工单只填自己那一项。

    未传任何参数时上传器保持 legacy 路径（零控件交互）；``--alt-text`` 只在
    ``upload-note`` 注册。
    """
    _add_location_flag(parser)
    _add_comments_flag(parser)
    _add_ai_generated_flags(parser)
    if include_alt_text:
        _add_alt_text_flag(parser)


def _add_location_flag(parser) -> None:
    """地点（工单 13）。"""
    parser.add_argument(
        '--location',
        metavar='TEXT',
        default=None,
        help='Instagram 地点名称（按候选精确匹配；不传则不动页面默认）',
    )


def _add_comments_flag(parser) -> None:
    """关闭评论（工单 11）。"""
    parser.add_argument(
        "--no-comments",
        action="store_true",
        help="Turn off commenting; omit to leave the page default",
    )


def _add_ai_generated_flags(parser) -> None:
    """AI 生成标识（工单 12）。"""


def _add_alt_text_flag(parser) -> None:
    """替代文字，仅 upload-note（工单 14）。"""


@dataclass(slots=True)
class InstagramUploadRequest:
    account_name: str
    title: str
    description: str
    tags: list[str]
    video_file: Path | None = None
    image_files: list[Path] | None = None
    thumbnail: Path | None = None
    proxy: str | None = INSTAGRAM_PROXY
    headless: bool = False
    result_file: Path | None = None
    publish_not_before: datetime | None = None
    options: InstagramPublishOptions | None = None


def _build_publish_options(args) -> InstagramPublishOptions | None:
    """把 CLI 三态参数映射为发布选项；全为 None 时保持 legacy 路径。

    与 TikTok 的 ``_build_publish_options`` 同构：``None`` 表示不动页面默认，
    显式 ``False``（``--no-comments`` / ``--no-ai-generated``）不能被压缩。
    本工单尚未注册用户可见 flag，读取到的永远是 ``None``。
    """
    location = getattr(args, "location", None) or None
    alt_texts = getattr(args, "alt_text", None) or None
    comments = False if getattr(args, "no_comments", False) else None
    ai_generated = getattr(args, "ai_generated", None)
    if location is None and alt_texts is None and comments is None and ai_generated is None:
        return None
    return InstagramPublishOptions(
        location=location,
        alt_texts=tuple(alt_texts) if alt_texts is not None else None,
        comments=comments,
        ai_generated=ai_generated,
    )


def validate_instagram_publish_request(request: InstagramUploadRequest) -> None:
    """在启动浏览器 / 托管 Profile 前完成 §3.3 静态校验（失败即退出码 2）。"""
    validate_publish_options(
        request.options,
        image_count=len(request.image_files or []),
        caption=instagram_caption(
            request.title, request.description, request.tags
        ),
        has_video=bool(request.video_file),
        has_thumbnail=bool(request.thumbnail),
    )


async def login_instagram_account(account_name: str, *, headless: bool = False, proxy: str | None = INSTAGRAM_PROXY) -> dict:
    account_file = resolve_account_file("instagram", account_name)
    return await instagram_setup(account_file, handle=True, return_detail=True, headless=headless, proxy=proxy)


async def check_instagram_account(account_name: str, *, proxy: str | None = INSTAGRAM_PROXY) -> bool:
    account_file = resolve_account_file("instagram", account_name)
    return await instagram_cookie_auth(account_file, proxy=proxy)


def _build_uploader(request: InstagramUploadRequest, account_file) -> InstagramUploader:
    app = InstagramUploader(
        account_file,
        title=request.title,
        description=request.description,
        tags=request.tags,
        video_file=request.video_file,
        image_files=request.image_files,
        thumbnail=request.thumbnail,
        proxy=request.proxy,
        headless=request.headless,
        result_file=request.result_file,
        options=request.options,
    )
    app.publish_not_before = request.publish_not_before
    return app


def _raise_login_required(target) -> None:
    raise login_required_error("Instagram", target.profile_id, mode=target.mode)


async def upload_instagram_content(
    request: InstagramUploadRequest, *, target=None
) -> dict:
    if target is not None:
        # No cookie path, no .identity.json read, no account-id comparison:
        # the Profile is the identity.  ``--proxy`` / the environment proxy are
        # not forwarded either; the Profile owns the egress IP.
        app = _build_uploader(replace(request, proxy=None), None)
        async with async_playwright() as playwright:
            async with browser_session(
                playwright,
                headless=request.headless,
                account_file=None,
                managed=target,
                launch_kwargs=INSTAGRAM_LAUNCH_KWARGS,
                context_kwargs=INSTAGRAM_CONTEXT_KWARGS,
                init_script=INSTAGRAM_INIT_SCRIPT,
            ) as session:
                if not await is_logged_in(session.context):
                    _raise_login_required(target)
                logger.info(
                    identity_unverified_format(mode=target.mode),
                    target.profile_id,
                )
                return await app.upload(session=session)

    account_file = resolve_account_file("instagram", request.account_name)
    app = _build_uploader(request, account_file)
    return await app.upload()


async def run(args):
    """执行本平台命令；发布结果由平台实现核验。"""
    if args.action == "login":
        reject_managed_login("instagram", args)
        require_local_account(args)
        result = await login_instagram_account(args.account, headless=args.headless, proxy=args.proxy)
        if not result["success"]:
            raise RuntimeError(result.get("message", "Instagram login failed"))
        print(f"Instagram login flow completed: {result['account_file']}")
        return 0

    if args.action in {"verify", "delete"}:
        require_account(args)
        result = await instagram_post_action(
            resolve_account_file("instagram", args.account),
            post_url=args.post_url,
            expected_text=args.expected_text,
            delete=args.action == "delete",
            proxy=args.proxy,
            headless=args.headless,
            result_file=args.result,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
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
                    launch_kwargs=INSTAGRAM_LAUNCH_KWARGS,
                    context_kwargs=INSTAGRAM_CONTEXT_KWARGS,
                    init_script=INSTAGRAM_INIT_SCRIPT,
                ) as session:
                    logger.info(
                        identity_unverified_format(mode=target.mode),
                        target.profile_id,
                    )
                    is_valid = await is_logged_in(session.context)
            if not is_valid:
                _raise_login_required(target)
            print("valid")
            return 0

        is_valid = await check_instagram_account(account_label, proxy=args.proxy)
        print("valid" if is_valid else "invalid")
        return 0 if is_valid else 1

    if args.action in {"upload-video", "upload-note"}:
        request = InstagramUploadRequest(
            account_name=account_label,
            title=args.title,
            description=args.desc if args.action == "upload-video" else args.note,
            tags=parse_tags(args.tags),
            video_file=args.file if args.action == "upload-video" else None,
            image_files=parse_image_files(args.images) if args.action == "upload-note" else None,
            thumbnail=args.thumbnail if args.action == "upload-video" else None,
            proxy=args.proxy,
            headless=args.headless,
            result_file=args.result,
            publish_not_before=args.not_before,
            options=_build_publish_options(args),
        )
        validate_instagram_publish_request(request)
        result = await upload_instagram_content(request, target=target)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    raise RuntimeError(f"Unsupported Instagram action: {args.action}")
