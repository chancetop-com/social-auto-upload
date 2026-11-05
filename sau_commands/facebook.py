"""facebook 的命令参数与执行逻辑。"""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from patchright.async_api import async_playwright
from uploader.base_video import BaseVideoUploader
from uploader.meta_uploader.facebook_uploader.main import (
    FACEBOOK_CONTEXT_KWARGS,
    FACEBOOK_INIT_SCRIPT,
    FACEBOOK_LAUNCH_KWARGS,
    FACEBOOK_PROXY,
    FacebookVideo,
    FacebookPost,
    facebook_cookie_auth,
    facebook_setup,
    is_logged_in,
)
from uploader.meta_uploader.facebook_uploader.posts import facebook_post_action
from sau_commands.arguments import (
    SCHEDULE_FORMAT,
    add_runtime_flags,
    existing_file_path,
    parse_tags,
    resolve_account_file,
)
from sau_commands.multilogin import (
    add_multilogin_flags,
    reject_multilogin_login,
    require_local_account,
    resolve_account_label,
    resolve_multilogin_target,
)
from utils.browser_session import browser_session
from utils.errors import LoginRequiredError


def register(platform_parsers):
    """声明本平台命令、参数及合法选项。"""
    schedule_help = SCHEDULE_FORMAT.replace("%", "%%")
    facebook_parser = platform_parsers.add_parser("facebook", help="Facebook personal post operations")
    facebook_actions = facebook_parser.add_subparsers(dest="action", required=True)

    for action in ("verify", "delete"):
        post_parser = facebook_actions.add_parser(action, help="核对原作品" if action == "verify" else "核对原作品后移至垃圾箱（30 天后平台删除）")
        post_parser.add_argument("--account", required=False)
        post_parser.add_argument("--post-url", required=True, help="原作品的 Facebook 链接")
        post_parser.add_argument("--owner-id", required=True, help="原作品所属个人主页的数字 ID")
        post_parser.add_argument("--expected-text", required=True, help="原作品中用于交叉核验的正文")
        post_parser.add_argument("--result", type=Path, help="保存查询或删除结果 JSON")
        post_parser.add_argument("--from-trash", action="store_true", help="原作品已在垃圾箱，从垃圾箱核验")
        if action == "delete":
            post_parser.add_argument("--permanent", action="store_true", help="将核实的原作品从垃圾箱永久删除（无法恢复）")
        else:
            post_parser.add_argument("--deleted", action="store_true", help="只查询垃圾箱原 ID 是否已删除，不执行删除")
        post_parser.add_argument("--proxy", default=FACEBOOK_PROXY, help="代理地址；不传时直连")
        add_runtime_flags(post_parser)
        post_parser.set_defaults(headless=False)

    for action_name in ("login", "check"):
        action_parser = facebook_actions.add_parser(action_name, help=f"Facebook {action_name}")
        action_parser.add_argument("--account", required=False, help="Facebook user-defined account_name")
        action_parser.add_argument(
            "--proxy",
            default=FACEBOOK_PROXY,
            help="浏览器代理地址；不传时直连，传空字符串可覆盖环境变量并直连",
        )
        if action_name == "login":
            add_runtime_flags(action_parser)
            # Facebook 登录必须在可见 Chrome 中完成，避免无头模式下用户看不到登录挑战。
            action_parser.set_defaults(headless=False)
        else:
            add_multilogin_flags(action_parser)

    facebook_upload_video_parser = facebook_actions.add_parser(
        "upload-video", help="Upload one video to a Facebook personal post"
    )
    facebook_upload_video_parser.add_argument("--account", required=False, help="Facebook user-defined account_name")
    facebook_upload_video_parser.add_argument("--file", required=True, type=existing_file_path, help="Video file path")
    facebook_upload_video_parser.add_argument("--title", required=True, help="Post title, merged into Facebook caption")
    facebook_upload_video_parser.add_argument("--desc", default="", help="Optional post description")
    facebook_upload_video_parser.add_argument("--tags", default="", help="Comma-separated tags, such as tag1,tag2")
    facebook_upload_video_parser.add_argument(
        "--proxy",
        default=FACEBOOK_PROXY,
        help="浏览器代理地址；不传时直连，传空字符串可覆盖环境变量并直连",
    )
    add_runtime_flags(facebook_upload_video_parser)
    add_multilogin_flags(facebook_upload_video_parser)

    facebook_note = facebook_actions.add_parser("upload-note", help="向个人主页发布图片及正文")
    facebook_note.add_argument("--account", required=False)
    facebook_note.add_argument("--images", required=True, nargs="+", type=existing_file_path)
    facebook_note.add_argument("--title", required=True)
    facebook_note.add_argument("--note", default="")
    facebook_note.add_argument("--tags", default="")
    facebook_note.add_argument("--proxy", default=FACEBOOK_PROXY, help="代理地址；不传时直连")
    add_runtime_flags(facebook_note)
    add_multilogin_flags(facebook_note)
    facebook_note.set_defaults(headless=False)


@dataclass(slots=True)
class FacebookVideoUploadRequest:
    account_name: str
    video_file: Path
    title: str
    description: str
    tags: list[str]
    proxy: str | None = FACEBOOK_PROXY
    debug: bool = True
    headless: bool = True


async def login_facebook_account(
    account_name: str, *, headless: bool = False, proxy: str | None = FACEBOOK_PROXY
) -> dict:
    account_file = resolve_account_file("facebook", account_name)
    return await facebook_setup(
        account_file,
        handle=True,
        return_detail=True,
        headless=headless,
        proxy=proxy,
    )


async def check_facebook_account(
    account_name: str, *, proxy: str | None = FACEBOOK_PROXY
) -> bool:
    account_file = resolve_account_file("facebook", account_name)
    if not account_file.exists():
        return False
    return await facebook_cookie_auth(account_file, proxy=proxy)


def _raise_login_required(target) -> None:
    raise LoginRequiredError(
        f"Facebook 登录态无效：profile_id={target.profile_id}。"
        "请在 Multilogin 应用中登录 Profile 后重试。"
    )


async def _upload_facebook_mlx(
    target, *, title: str, files, description: str, tags: list[str], headless: bool
) -> None:
    """Run one Facebook post through the Multilogin Profile session.

    ``--proxy``/``SAU_FACEBOOK_PROXY`` are not forwarded: the Profile owns the
    egress IP.  No cookie file is resolved or read.
    """
    app = FacebookPost(
        title=title,
        file_path=files,
        description=description,
        tags=tags,
        account_file=None,
        proxy=None,
        headless=headless,
    )
    async with async_playwright() as playwright:
        async with browser_session(
            playwright,
            headless=headless,
            account_file=None,
            multilogin=target,
            launch_kwargs=FACEBOOK_LAUNCH_KWARGS,
            context_kwargs=FACEBOOK_CONTEXT_KWARGS,
            init_script=FACEBOOK_INIT_SCRIPT,
        ) as session:
            if not await is_logged_in(session.context):
                _raise_login_required(target)
            await app.main(session=session)


async def upload_facebook_video(
    request: FacebookVideoUploadRequest, *, target=None
) -> Path | None:
    if target is not None:
        await _upload_facebook_mlx(
            target,
            title=request.title,
            files=[request.video_file],
            description=request.description,
            tags=request.tags,
            headless=request.headless,
        )
        return None

    account_file = resolve_account_file("facebook", request.account_name)
    is_ready = await facebook_setup(
        account_file,
        handle=False,
        proxy=request.proxy,
    )
    if not is_ready:
        raise RuntimeError(
            f"Facebook 登录态不存在或已失效: {account_file}. "
            f"请先执行 `sau facebook login --account {request.account_name}`。"
        )

    app = FacebookVideo(
        title=request.title,
        file_path=request.video_file,
        description=request.description,
        tags=request.tags,
        account_file=account_file,
        proxy=request.proxy,
        headless=request.headless,
    )
    await app.main()
    return account_file


async def run(args):
    """执行本平台命令；发布结果由平台实现核验。"""
    if args.action == "login":
        reject_multilogin_login("facebook", args)
        require_local_account(args)
        result = await login_facebook_account(
            args.account, headless=args.headless, proxy=args.proxy
        )
        if not result["success"]:
            raise RuntimeError(result["message"])
        print(f"Facebook login flow completed: {result['account_file']}")
        return 0

    if args.action in {"verify", "delete"}:
        require_local_account(args)
        result = await facebook_post_action(
            resolve_account_file("facebook", args.account), post_url=args.post_url,
            owner_id=args.owner_id, expected_text=args.expected_text,
            delete=args.action == "delete", proxy=args.proxy, headless=args.headless,
            permanent=getattr(args, "permanent", False), from_trash=args.from_trash,
            deleted=getattr(args, "deleted", False),
        )
        if args.result:
            args.result.parent.mkdir(parents=True, exist_ok=True)
            args.result.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    target = resolve_multilogin_target(args)
    require_local_account(args)
    account_label = resolve_account_label(args)

    if args.action == "check":
        if target is not None:
            async with async_playwright() as playwright:
                async with browser_session(
                    playwright,
                    headless=getattr(args, "headless", True),
                    multilogin=target,
                    launch_kwargs=FACEBOOK_LAUNCH_KWARGS,
                    context_kwargs=FACEBOOK_CONTEXT_KWARGS,
                    init_script=FACEBOOK_INIT_SCRIPT,
                ) as session:
                    is_valid = await is_logged_in(session.context)
            if not is_valid:
                _raise_login_required(target)
            print("valid")
            return 0

        is_valid = await check_facebook_account(account_label, proxy=args.proxy)
        print("valid" if is_valid else "invalid")
        return 0 if is_valid else 1

    if args.action == "upload-note":
        for image in args.images:
            BaseVideoUploader.validate_image_file(image)
        if target is not None:
            await _upload_facebook_mlx(
                target,
                title=args.title,
                files=args.images,
                description=args.note,
                tags=parse_tags(args.tags),
                headless=args.headless,
            )
            print("Facebook image post submitted")
            return 0

        app = FacebookPost(args.title, args.images, args.note, parse_tags(args.tags),
                           resolve_account_file("facebook", account_label), proxy=args.proxy, headless=args.headless)
        await app.main()
        print("Facebook image post submitted")
        return 0

    if args.action == "upload-video":
        request = FacebookVideoUploadRequest(
            account_name=account_label,
            video_file=args.file,
            title=args.title,
            description=args.desc,
            tags=parse_tags(args.tags),
            proxy=args.proxy,
            debug=args.debug,
            headless=args.headless,
        )
        await upload_facebook_video(request, target=target)
        print(f"Facebook video upload submitted: {request.video_file}")
        return 0

    raise RuntimeError(f"Unsupported Facebook action: {args.action}")
