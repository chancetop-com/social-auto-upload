"""xueqiu 的命令参数与执行逻辑。"""
from __future__ import annotations
import json

from loguru import logger
from patchright.async_api import async_playwright

from uploader.xueqiu_uploader.article import XueqiuArticle
from uploader.xueqiu_uploader.constants import (
    XUEQIU_CONTEXT_KWARGS,
    XUEQIU_DECLARATIONS,
    XUEQIU_LAUNCH_KWARGS,
    XUEQIU_VISIBILITY,
)
from uploader.xueqiu_uploader.session import (
    check_xueqiu_account, is_logged_in, login_xueqiu_account,
)
from uploader.xueqiu_uploader.verification import verify_xueqiu_result
from sau_commands.arguments import (
    add_not_before_flag,
    add_local_runtime_flags,
    existing_file_path,
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
from sau_commands.arguments import single_line_value
from utils.browser_session import browser_session
from utils.local_browser import resolve_headless
from sau_commands.local_profile import add_reset_profile_action, run_reset_profile


def _log_identity_unverified(target) -> None:
    logger.info(
        identity_unverified_format(mode=target.mode, detailed=True),
        target.profile_id,
    )


def _raise_login_required(target) -> None:
    raise login_required_error("雪球", target.profile_id, mode=target.mode)


async def _run_multilogin(args, target):
    """Multilogin path: Profile owns identity; no cookies/identity files are read."""
    headless = resolve_headless(args.headless)

    if args.action == "check":
        async with async_playwright() as playwright:
            async with browser_session(
                playwright,
                headless=headless,
                account_file=None,
                managed=target,
            ) as session:
                _log_identity_unverified(target)
                is_valid = await is_logged_in(session.context)
        if not is_valid:
            _raise_login_required(target)
        print("valid")
        return 0

    app = XueqiuArticle(
        title=args.title, content_file=args.content_file, account_file=None,
        visibility=args.visibility, declaration=args.declaration,
        prepare_only=args.prepare_only, headless=headless, debug=args.debug,
        cover=args.cover, publish_not_before=args.not_before,
    )
    async with async_playwright() as playwright:
        async with browser_session(
            playwright,
            headless=headless,
            account_file=None,
            managed=target,
            launch_kwargs=XUEQIU_LAUNCH_KWARGS,
            context_kwargs=XUEQIU_CONTEXT_KWARGS,
        ) as session:
            _log_identity_unverified(target)
            if not await is_logged_in(session.context):
                _raise_login_required(target)
            result = await app.main(session=session)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def register(platform_parsers):
    """声明本平台命令、参数及合法选项。"""
    xueqiu_parser = platform_parsers.add_parser("xueqiu", help="雪球创作者中心图文长文")
    xueqiu_actions = xueqiu_parser.add_subparsers(dest="action", required=True)
    add_reset_profile_action(xueqiu_actions)
    xueqiu_login = xueqiu_actions.add_parser("login", help="登录所选本地浏览器 Profile")
    xueqiu_login.add_argument("--account", required=False, help="本地账号别名")
    xueqiu_login.add_argument("--expected-name", help="期望的雪球昵称")
    xueqiu_login.add_argument("--timeout", type=int, default=600, help="登录等待秒数")
    add_local_runtime_flags(xueqiu_login)
    xueqiu_check = xueqiu_actions.add_parser("check", help="检查当前 Profile 登录状态")
    xueqiu_check.add_argument("--account", required=False)
    add_browser_flags(xueqiu_check)
    add_local_runtime_flags(xueqiu_check)
    xueqiu_verify = xueqiu_actions.add_parser("verify", help="根据结果文件查询原作品，不重复发表")
    xueqiu_verify.add_argument("--account", required=False)
    xueqiu_verify.add_argument("--result", required=True, type=existing_file_path)
    add_local_runtime_flags(xueqiu_verify)
    xueqiu_article = xueqiu_actions.add_parser("upload-article", help="HTML/Markdown/TXT 长文及原位置配图")
    xueqiu_article.add_argument("--account", required=False)
    xueqiu_article.add_argument("--title", type=single_line_value, required=True, help="非空单行标题")
    xueqiu_article.add_argument("--content-file", required=True, type=existing_file_path, help="UTF-8 HTML/Markdown/TXT；图片由原稿位置决定")
    xueqiu_article.add_argument("--cover", type=existing_file_path, help="独立封面；采用平台默认裁剪区域")
    xueqiu_article.add_argument("--visibility", choices=XUEQIU_VISIBILITY, default="公开", help="分享范围")
    xueqiu_article.add_argument("--declaration", choices=XUEQIU_DECLARATIONS, required=True, help="按实际创作方式选择")
    xueqiu_article.add_argument("--prepare-only", action="store_true", help="检查预览后结束；雪球会自动保存远端草稿")
    add_not_before_flag(xueqiu_article)
    add_local_runtime_flags(xueqiu_article)
    add_browser_flags(xueqiu_article)


async def run(args):
    """执行本平台命令；发布结果由平台实现核验。"""
    if args.action == "reset-profile":
        return run_reset_profile(args)
    if args.action == "login":
        reject_managed_login("xueqiu", args)
        require_local_account(args)
        account = args.account
    elif args.action in {"check", "upload-article"}:
        target = resolve_managed_provider(args)
        require_local_account(args)
        account = resolve_account_label(args)
        if target is not None:
            return await _run_multilogin(args, target)
    else:
        require_account(args)
        account = args.account

    if args.action == "login":
        result = await login_xueqiu_account(
            expected_name=args.expected_name, timeout=args.timeout, account_name=account,
            headless=args.headless, local_browser=args.local_browser,
        )
    elif args.action == "check":
        valid = await check_xueqiu_account(
            account_name=account, headless=args.headless, local_browser=args.local_browser,
        )
        print("valid" if valid else "invalid")
        return 0 if valid else 1
    elif args.action == "verify":
        result = await verify_xueqiu_result(
            None, args.result, args.headless, account_name=account, local_browser=args.local_browser,
        )
    else:
        # Preserve the historical result directory; this path is never login state.
        result_location = resolve_account_file("xueqiu", account)
        app = XueqiuArticle(
            title=args.title, content_file=args.content_file, account_file=result_location,
            visibility=args.visibility, declaration=args.declaration,
            prepare_only=args.prepare_only, headless=args.headless, debug=args.debug,
            cover=args.cover, publish_not_before=args.not_before,
            account_name=account, local_browser=args.local_browser,
        )
        result = await app.main()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
