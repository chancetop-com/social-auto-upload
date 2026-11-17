"""雪球当前 Profile 登录；网络故障与明确退出登录分别处理。"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

from patchright.async_api import BrowserContext, Page, async_playwright, expect

from utils.local_browser_session import local_browser_session
from utils.browser_session import BrowserSession
from uploader.xueqiu_uploader.constants import XUEQIU_HOME_URL
from utils.browser_cleanup import close_browser_resources
from utils.errors import LoginRequiredError


XUEQIU_LOGIN_CHECK_TIMEOUT_MS = 20_000
XUEQIU_IDENTITY_PROBE_TIMEOUT_MS = 10_000
_XUEQIU_LOGIN_PATH_PREFIXES = ("/account/login", "/login", "/signin")
_XUEQIU_LOGIN_URL_MARKERS = ("login", "signin", "captcha", "two-factor", "2fa")


class XueqiuAccessError(RuntimeError):
    """An observed access failure must not be reclassified as expired login."""


def is_xueqiu_login_url(url: str) -> bool:
    """Return ``True`` for the known Xueqiu sign-in/captcha/2FA URL shapes."""
    target = urlsplit(url)
    path = target.path.lower()
    if (target.hostname in {"xueqiu.com", "www.xueqiu.com"}
            and path.startswith("/account/login")):
        return True
    return path.startswith(_XUEQIU_LOGIN_PATH_PREFIXES) or any(
        marker in path for marker in _XUEQIU_LOGIN_URL_MARKERS
    )


def raise_if_login_required(page: Page, *, publish_attempted: bool = False, managed=True) -> None:
    """Preserve submission phase when an observed login/verification blocks work."""
    url = str(getattr(page, "url", "") or "")
    if is_xueqiu_login_url(url):
        verification = any(marker in urlsplit(url).path.lower() for marker in ("captcha", "two-factor", "2fa"))
        if managed:
            message = "雪球上传过程中需要重新登录（登录页/验证码/二次验证）：请在 Multilogin 应用中登录 Profile 后重试。"
        elif verification:
            message = "雪球需要完成验证 reason=verification；请运行 sau xueqiu login 在所选 Profile 中完成验证后重试。"
        else:
            message = "雪球未登录；请先运行 sau xueqiu login 恢复所选 Profile。"
        if publish_attempted and not managed:
            message += " 可能已提交，请先核查原作品，勿自动重发。"
        raise LoginRequiredError(message, reason="verification" if verification and not managed else "login",
                                 publish_attempted=publish_attempted)


async def read_xueqiu_identity(page: Page, *, timeout: int = 30000) -> dict:
    """页头 data-id 是当前用户 ID；昵称用于展示，不代替身份比较。"""
    # header-user 是已登录页头固定账号区，data-id 在首页及长文编辑器均可读取。
    user = page.locator("nav .header-user[data-id]")
    await expect(user).to_have_count(1, timeout=timeout)
    await expect(user).to_be_visible(timeout=timeout)
    uid = await user.get_attribute("data-id")
    # 用户区内 span 承载昵称，排除侧栏和正文中可能出现的相同名字。
    name = (await user.locator("span").inner_text()).strip()
    if not re.fullmatch(r"[1-9][0-9]*", uid or "") or not name:
        raise RuntimeError("雪球页头身份缺失，无法核验发布账号")
    return {"uid": uid, "name": name}


def account_alias(account_file=None, account_name=None):
    """Legacy positional paths remain naming hints, never login-state inputs."""
    if account_name is not None:
        return account_name
    if account_file is None:
        raise ValueError("雪球本地模式需要账号别名")
    return Path(account_file).stem.removeprefix("xueqiu_")


async def login_xueqiu_account(account_file=None, expected_name=None, timeout=600, *,
                               account_name=None, headless=None, local_browser=None,
                               session: BrowserSession | None = None) -> dict:
    """Only login guides the user; browser-owned Profile saves the session."""
    if timeout <= 0:
        raise ValueError("登录期限必须大于 0 秒")
    if session is None:
        async with async_playwright() as playwright:
            async with local_browser_session(
                playwright, platform="xueqiu", account=account_alias(account_file, account_name),
                headless=headless, local_browser=local_browser, create=True,
            ) as owned:
                return await login_xueqiu_account(expected_name=expected_name, timeout=timeout, session=owned)
    page = await session.context.new_page()
    response = await page.goto(XUEQIU_HOME_URL, wait_until="domcontentloaded", timeout=45000)
    if response is not None and response.status >= 400:
        raise XueqiuAccessError(f"雪球登录页访问失败，HTTP {response.status}")
    print("请在浏览器中完成雪球登录，然后进入创作者中心；登录态由本地 Profile 保存。", flush=True)
    try:
        await page.locator("nav .header-user[data-id]").wait_for(state="visible", timeout=timeout * 1000)
        identity = await read_xueqiu_identity(page)
    except Exception:
        raise_if_login_required(page, managed=False)
        raise
    if expected_name is not None and identity["name"] != expected_name:
        raise RuntimeError("雪球昵称与 --expected-name 不匹配")
    return {"success": True, "identity": identity}


async def is_logged_in(context: BrowserContext, *, managed=True) -> bool:
    """Probe current header identity without reading old login files.

    Managed calls retain their bool/5xx contract and created-page cleanup.
    Local login/verification raises exit 10; HTTP access or unknown structures
    remain faults. Local operation pages are owned by the persistent context.
    """
    page = await context.new_page()
    try:
        try:
            response = await page.goto(
                XUEQIU_HOME_URL,
                wait_until="domcontentloaded",
                timeout=XUEQIU_LOGIN_CHECK_TIMEOUT_MS,
            )
        except Exception:
            if not managed:
                raise_if_login_required(page, managed=False)
            raise
        status = getattr(response, "status", None)
        if isinstance(status, int) and status >= (500 if managed else 400):
            raise RuntimeError(f"雪球登录状态检查失败：HTTP {status}")

        current_url = str(getattr(page, "url", "") or "")
        target = urlsplit(current_url)
        if target.hostname not in {"mp.xueqiu.com", "xueqiu.com", "www.xueqiu.com"}:
            raise RuntimeError(
                "雪球登录状态检查失败：页面未停留在雪球"
                f"（url={current_url or '<empty>'}）"
            )
        if not managed:
            raise_if_login_required(page, managed=False)
        if is_xueqiu_login_url(current_url):
            return False

        try:
            await read_xueqiu_identity(page, timeout=XUEQIU_IDENTITY_PROBE_TIMEOUT_MS)
        except Exception:
            if not managed:
                raise_if_login_required(page, managed=False)
            raise
        return True
    finally:
        if managed:
            await close_browser_resources(page=page)


async def check_xueqiu_account(account_file=None, headless=None, *, account_name=None,
                                local_browser=None, session: BrowserSession | None = None) -> bool:
    """Probe this Profile; no sidecar binding or interactive login recovery."""
    if session is None:
        async with async_playwright() as playwright:
            async with local_browser_session(
                playwright, platform="xueqiu", account=account_alias(account_file, account_name),
                headless=headless, local_browser=local_browser,
            ) as owned:
                return await check_xueqiu_account(session=owned)
    if not await is_logged_in(session.context, managed=session.managed):
        raise LoginRequiredError("雪球未登录；请先运行 sau xueqiu login 恢复所选 Profile。")
    return True
