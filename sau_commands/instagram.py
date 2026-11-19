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
from sau_commands.local_profile import add_reset_profile_action, run_reset_profile
from sau_commands.publish_media import add_task_id, media_source
from sau_commands.arguments import (
    add_not_before_flag,
    add_local_runtime_flags,
    parse_image_files,
    parse_tags,
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
from utils.local_browser import resolve_headless


def register(platform_parsers):
    """声明本平台命令、参数及合法选项。"""
    instagram_parser = platform_parsers.add_parser("instagram", help="Instagram independent web operations")
    instagram_actions = instagram_parser.add_subparsers(dest="action", required=True)
    add_reset_profile_action(instagram_actions)
    for action_name in ("login", "check"):
        action_parser = instagram_actions.add_parser(action_name, help=f"Instagram {action_name}")
        action_parser.add_argument("--account", required=False)
        action_parser.add_argument("--proxy", default=INSTAGRAM_PROXY, help="代理地址；不传时直连")
        if action_name == "login":
            add_local_runtime_flags(action_parser)
        else:
            add_local_runtime_flags(action_parser)
            add_browser_flags(action_parser)
    instagram_video = instagram_actions.add_parser("upload-video", help="向 Instagram 发布视频/Reel")
    instagram_video.add_argument("--account", required=False)
    add_task_id(instagram_video)
    instagram_video.add_argument(
        "--file", required=True, type=media_source, help="Local video path or HTTP(S) URL"
    )
    instagram_video.add_argument(
        "--thumbnail", type=media_source, help="Reel 自定义封面（JPG/JPEG/PNG），支持本地路径或 HTTP(S) URL"
    )
    instagram_video.add_argument("--title", required=True)
    instagram_video.add_argument("--desc", default="")
    instagram_video.add_argument("--tags", default="")
    instagram_video.add_argument("--proxy", default=INSTAGRAM_PROXY, help="代理地址；不传时直连")
    instagram_video.add_argument("--result", type=Path)
    add_not_before_flag(instagram_video)
    _add_no_publish_flag(instagram_video)
    _add_instagram_option_flags(instagram_video, include_alt_text=False)
    add_local_runtime_flags(instagram_video)
    add_browser_flags(instagram_video)
    instagram_note = instagram_actions.add_parser("upload-note", help="向 Instagram 发布图片或轮播")
    instagram_note.add_argument("--account", required=False)
    add_task_id(instagram_note)
    instagram_note.add_argument(
        "--images", required=True, nargs="+", type=media_source, help="Local image paths or HTTP(S) URLs in post order"
    )
    instagram_note.add_argument("--title", required=True)
    instagram_note.add_argument("--note", default="")
    instagram_note.add_argument("--tags", default="")
    instagram_note.add_argument("--proxy", default=INSTAGRAM_PROXY, help="代理地址；不传时直连")
    instagram_note.add_argument("--result", type=Path)
    add_not_before_flag(instagram_note)
    _add_no_publish_flag(instagram_note)
    _add_instagram_option_flags(instagram_note, include_alt_text=True)
    add_local_runtime_flags(instagram_note)
    add_browser_flags(instagram_note)
    for action_name in ("verify", "delete"):
        action_parser = instagram_actions.add_parser(action_name, help="核对 Instagram 原作品" if action_name == "verify" else "核对后将 Instagram 原作品移至最近删除")
        action_parser.add_argument("--account", required=False)
        action_parser.add_argument("--post-url", required=True)
        action_parser.add_argument("--expected-text", required=True)
        action_parser.add_argument("--proxy", default=INSTAGRAM_PROXY, help="代理地址；不传时直连")
        action_parser.add_argument("--result", type=Path)
        add_local_runtime_flags(action_parser)


def _add_no_publish_flag(parser) -> None:
    """干跑：跑到发布就绪点即停止，不点击发布（与小红书同语义）。"""
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="跑到发布就绪点即停止，不点击发布（回归测试用）",
    )


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
        help="请求关闭评论（Turn off commenting）；不传则不动页面默认",
    )


def _add_ai_generated_flags(parser) -> None:
    """AI 生成标识（工单 12）：互斥组保证同传由 argparse 退出 2。"""
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--ai-generated",
        dest="ai_generated",
        action="store_const",
        const=True,
        help="请求开启 AI 生成标识（Add AI label）；不传则不动页面默认",
    )
    group.add_argument(
        "--no-ai-generated",
        dest="ai_generated",
        action="store_const",
        const=False,
        help="请求关闭 AI 生成标识（--no-ai-generated）；不传则不动页面默认",
    )


def _add_alt_text_flag(parser) -> None:
    """替代文字，仅 upload-note（工单 14）。"""
    parser.add_argument(
        '--alt-text', action='append', metavar='TEXT', default=None,
        help='每张图片一条替代文字（1-1000 字符），可重复；条数必须为 0 或等于图片张数',
    )


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
    headless: bool | None = None
    result_file: Path | None = None
    publish_not_before: datetime | None = None
    options: InstagramPublishOptions | None = None
    no_publish: bool = False
    local_browser: str | None = None


def _build_publish_options(args) -> InstagramPublishOptions | None:
    """把 CLI 三态参数映射为发布选项；全为 None 时保持 legacy 路径。

    与 TikTok 的 ``_build_publish_options`` 同构：``None`` 表示不动页面默认，
    显式 ``False``（``--no-comments`` / ``--no-ai-generated``）不能被压缩。
    四个 flag 全部未传时返回 ``None``，上传器保持 legacy 路径。
    ``--location ""`` 保留空串（不折叠成 ``None``），交给静态校验退出 2。
    """
    location = getattr(args, "location", None)
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


async def login_instagram_account(account_name: str, *, headless=None, proxy=INSTAGRAM_PROXY, local_browser=None) -> dict:
    return await instagram_setup(account_name=account_name, handle=True, return_detail=True,
                                 headless=headless, proxy=proxy, local_browser=local_browser)


async def check_instagram_account(account_name: str, *, proxy: str | None = INSTAGRAM_PROXY, headless=None, local_browser=None) -> bool:
    return await instagram_cookie_auth(account_name=account_name, proxy=proxy, headless=headless, local_browser=local_browser)


def _build_uploader(request: InstagramUploadRequest) -> InstagramUploader:
    app = InstagramUploader(
        None,
        title=request.title,
        description=request.description,
        tags=request.tags,
        video_file=request.video_file,
        image_files=request.image_files,
        thumbnail=request.thumbnail,
        proxy=request.proxy,
        headless=request.headless,
        account_name=request.account_name,
        local_browser=request.local_browser,
        result_file=request.result_file,
        options=request.options,
        no_publish=request.no_publish,
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
        app = _build_uploader(replace(request, proxy=None))
        async with async_playwright() as playwright:
            async with browser_session(
                playwright,
                headless=resolve_headless(request.headless),
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

    app = _build_uploader(request)
    return await app.upload()


async def run(args):
    """执行本平台命令；发布结果由平台实现核验。"""
    if args.action == "reset-profile":
        return run_reset_profile(args)
    if args.action == "login":
        reject_managed_login("instagram", args)
        require_local_account(args)
        result = await login_instagram_account(args.account, headless=args.headless, proxy=args.proxy, local_browser=getattr(args, "local_browser", None))
        if not result["success"]:
            raise RuntimeError(result.get("message", "Instagram login failed"))
        print(f"Instagram login flow completed: Profile {args.account}")
        return 0

    if args.action in {"verify", "delete"}:
        require_account(args)
        result = await instagram_post_action(
            account_name=args.account,
            local_browser=getattr(args, "local_browser", None),
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
                    headless=resolve_headless(args.headless),
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

        is_valid = await check_instagram_account(account_label, proxy=args.proxy, headless=args.headless, local_browser=getattr(args, "local_browser", None))
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
            local_browser=getattr(args, "local_browser", None),
            result_file=args.result,
            publish_not_before=args.not_before,
            options=_build_publish_options(args),
            no_publish=args.no_publish,
        )
        validate_instagram_publish_request(request)
        result = await upload_instagram_content(request, target=target)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        args.post_published = not request.no_publish and result.get("status") == "published"
        return 0

    raise RuntimeError(f"Unsupported Instagram action: {args.action}")
