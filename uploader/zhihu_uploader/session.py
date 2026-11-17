"""知乎持久化 Profile 与当次页面身份。"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from patchright.async_api import BrowserContext, Page, async_playwright, expect

from uploader.zhihu_uploader.constants import ZHIHU_CREATOR_URL
from utils.local_account import local_account_alias
from utils.browser_cleanup import close_browser_resources
from utils.errors import LoginRequiredError
from utils.local_browser_session import local_browser_session


PROFILE_IMAGE = "button.AppHeader-profileEntry img[alt^='点击打开'][alt$='的主页']"

ZHIHU_LOGIN_CHECK_TIMEOUT_MS = 20_000
ZHIHU_IDENTITY_PROBE_TIMEOUT_MS = 10_000
_ZHIHU_LOGIN_PATH_PREFIXES = ("/signin", "/account/unlogin", "/login")
_ZHIHU_LOGIN_URL_MARKERS = ("signin", "login", "captcha", "two-factor", "2fa")


def is_zhihu_login_url(url: str) -> bool:
    """Return ``True`` for the known Zhihu sign-in/captcha/2FA URL shapes."""
    path = urlsplit(url).path.lower()
    return path.startswith(_ZHIHU_LOGIN_PATH_PREFIXES) or any(
        marker in path for marker in _ZHIHU_LOGIN_URL_MARKERS
    )


def raise_if_login_required(page: Page, *, publish_attempted: bool = False, managed=True) -> None:
    """Classify explicit login/verification redirects without resuming the operation."""
    url = str(getattr(page, "url", "") or "")
    if not managed and urlsplit(url).hostname not in {"www.zhihu.com", "zhihu.com", "zhuanlan.zhihu.com"}:
        return
    if is_zhihu_login_url(url):
        if managed:
            raise LoginRequiredError(
                "知乎上传过程中需要重新登录（登录页/验证码/二次验证）："
                "请在 Multilogin 应用中登录 Profile 后重试。",
                publish_attempted=publish_attempted,
            )
        reason = "verification" if any(marker in urlsplit(url).path.lower()
            for marker in ("captcha", "two-factor", "2fa")) else "login"
        action = "完成人机验证" if reason == "verification" else "重新登录"
        raise LoginRequiredError(
            f"知乎需要{action}（reason={reason}）；请运行 sau zhihu login --account <账号别名>，"
            "使用相同本地浏览器选择。提交后先核对作品，不要自动重发。",
            reason=reason, publish_attempted=publish_attempted)


async def read_zhihu_identity(page: Page, *, timeout: int = 30000, strict=False) -> dict:
    """从知乎页头已登录头像读取展示名与头像地址，仅用于本次操作和结果证据；不是永久 ID。"""
    # AppHeader-profileEntry 是创作中心与视频页实际共用的当前用户入口。
    profile = page.locator(PROFILE_IMAGE)
    await expect(profile).to_have_count(1, timeout=timeout)
    await expect(profile).to_be_visible(timeout=timeout)
    label = (await profile.get_attribute("alt") or "").strip()
    name = label.removeprefix("点击打开").removesuffix("的主页").strip()
    avatar = profile.get_attribute("src")
    avatar_url = (await avatar or "").strip()
    if not name or not avatar_url:
        raise RuntimeError("知乎页头没有可读取的当前账号信息")
    parsed = urlsplit(avatar_url)
    avatar_path = parsed.path
    if not avatar_path or (strict and (parsed.scheme not in {"https", "http"} or not parsed.hostname or avatar_path == "/")):
        raise RuntimeError("知乎页头头像缺少路径，无法读取当前账号信息")
    return {"name": name, "avatar_path": avatar_path}


def account_alias(account_file=None, account_name=None):
    return local_account_alias(account_file, account_name, platform="zhihu",
                               missing_message='知乎本地模式需要 account_name 账号别名')


async def login_zhihu_account(account_file=None, timeout: int = 600, *,
                              account_name=None, headless=None, local_browser=None) -> dict:
    """Guide login into the selected Profile; names are current display information."""
    if timeout <= 0:
        raise ValueError("登录期限必须大于 0 秒")
    account = account_alias(account_file, account_name)
    async with async_playwright() as playwright:
        async with local_browser_session(playwright, platform="zhihu", account=account,
                headless=headless, local_browser=local_browser, create=True) as session:
            page = await session.context.new_page()
            response = await page.goto(ZHIHU_CREATOR_URL, wait_until="domcontentloaded", timeout=45000)
            if response is not None and response.status >= 400:
                raise RuntimeError(f"知乎创作中心访问失败，HTTP {response.status}")
            print("请在打开的浏览器中完成知乎登录；账号密码和验证码直接在网页输入。", flush=True)
            try:
                await page.locator(PROFILE_IMAGE).wait_for(state="visible", timeout=timeout * 1000)
            except Exception:
                raise_if_login_required(page, managed=False)
                raise
            raise_if_login_required(page, managed=False)
            if urlsplit(page.url).hostname not in {"www.zhihu.com", "zhihu.com"}:
                raise RuntimeError("知乎登录失败：页面未停留在知乎创作站点")
            try:
                identity = await read_zhihu_identity(page, strict=True)
            except Exception:
                raise_if_login_required(page, managed=False)
                raise
            return {"success": True, "account": account, "identity": identity}


async def is_logged_in(context: BrowserContext, *, managed=True) -> bool:
    """Probe login evidence within the supplied context (20s navigation + 10s read).

    Managed callers retain the original boolean and page-cleanup contract.
    Local callers classify login/verification as exit 10 and HTTP/DOM failures
    as faults; the persistent context owner closes their pages.
    """
    page = await context.new_page()
    try:
        try:
            response = await page.goto(
                ZHIHU_CREATOR_URL,
                wait_until="domcontentloaded",
                timeout=ZHIHU_LOGIN_CHECK_TIMEOUT_MS,
            )
        except Exception:
            if not managed:
                raise_if_login_required(page, managed=False)
            raise
        status = getattr(response, "status", None)
        if isinstance(status, int) and status >= (500 if managed else 400):
            raise RuntimeError(f"知乎登录状态检查失败：HTTP {status}")

        current_url = str(getattr(page, "url", "") or "")
        target = urlsplit(current_url)
        if target.hostname not in {"www.zhihu.com", "zhihu.com"}:
            raise RuntimeError(
                "知乎登录状态检查失败：页面未停留在知乎"
                f"（url={current_url or '<empty>'}）"
            )
        if not managed:
            raise_if_login_required(page, managed=False)
        if is_zhihu_login_url(current_url):
            return False

        if managed:
            await read_zhihu_identity(page, timeout=ZHIHU_IDENTITY_PROBE_TIMEOUT_MS)
        else:
            try:
                await read_zhihu_identity(page, timeout=ZHIHU_IDENTITY_PROBE_TIMEOUT_MS, strict=True)
            except Exception:
                raise_if_login_required(page, managed=False)
                raise
        return True
    finally:
        if managed:
            await close_browser_resources(page=page)


async def check_zhihu_account(account_file=None, headless=None, *, account_name=None,
                              local_browser=None, session=None) -> bool:
    """Check the selected Profile without binding the alias to a real account."""
    if session is None:
        async with async_playwright() as playwright:
            async with local_browser_session(playwright, platform="zhihu",
                    account=account_alias(account_file, account_name), headless=headless,
                    local_browser=local_browser) as owned:
                return await check_zhihu_account(session=owned)
    if not await is_logged_in(session.context, managed=session.managed):
        raise LoginRequiredError("知乎未登录；请运行 sau zhihu login --account <账号别名>，使用相同浏览器选择。")
    return True
