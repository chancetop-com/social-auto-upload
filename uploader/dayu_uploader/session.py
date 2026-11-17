"""大鱼号登录状态和发布主体核验，不把网络超时当作登录失效。"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from patchright.async_api import Page, async_playwright, expect

import conf
from utils.local_browser_session import local_browser_session
from utils.browser_cleanup import close_browser_resources
from utils.errors import LoginRequiredError

DAYU_HOME_URL = "https://mp.dayu.com/dashboard/index"
DAYU_VIDEO_URL = "https://mp.dayu.com/dashboard/video/write"

# Retained for managed startup options/logging; local sessions use the resolver.
# Managed browser_session ignores these options because the provider owns them.
DAYU_LAUNCH_KWARGS = {"executable_path": getattr(conf, "LOCAL_CHROME_PATH", "") or None, "channel": "chrome"}
DAYU_INIT_SCRIPT = False

# MLX 登录检测只打开一个页面；总预算 20s 导航 + 2.5s 稳定。
DAYU_LOGIN_CHECK_TIMEOUT_MS = 20_000
DAYU_LOGIN_CHECK_SETTLE_MS = 2_500
_LOGIN_URL_MARKERS = ("uop.dayu.com/cas", "/login", "captcha", "verify", "two-factor", "2fa")
_LOGIN_IFRAME = 'iframe[src*="uop.dayu.com/cas/"]'

# 没有本地账号文件时（MLX）结果文件落到临时目录，不触碰 cookies 目录。
def dayu_results_dir(account_file: str | Path | None) -> Path:
    base = Path(account_file).parent if account_file else Path(tempfile.gettempdir())
    return base / "dayu_results"


def _login_required_message() -> str:
    return "大鱼号上传过程中需要重新登录（登录页/验证码/二次验证）：请在 Multilogin 应用中登录 Profile 后重试。"


async def raise_if_login_required(page: Page | None, *, managed=True, publish_attempted=False) -> None:
    """Map a mid-upload login/captcha/2FA page to ``LoginRequiredError``."""
    url = str(getattr(page, "url", "") or "").lower()
    known_auth_origin = urlsplit(url).hostname in ("mp.dayu.com", "uop.dayu.com")
    if (managed or known_auth_origin) and any(marker in url for marker in _LOGIN_URL_MARKERS):
        if managed:
            raise LoginRequiredError(_login_required_message(), publish_attempted=publish_attempted)
        reason = "verification" if any(marker in url for marker in ("captcha", "verify", "two-factor", "2fa")) else "login"
        remedy = "请在所选浏览器 Profile 完成人机验证" if reason == "verification" else "请先运行 sau dayu login 恢复登录"
        if publish_attempted:
            remedy += "；帖子可能已提交，请先核查原作品，勿重新发布"
        raise LoginRequiredError(f"大鱼号 reason={reason}：{remedy}", reason=reason, publish_attempted=publish_attempted)
    try:
        if await page.locator(_LOGIN_IFRAME).count():
            message = _login_required_message() if managed else "大鱼号需要登录：请先运行 sau dayu login 恢复登录"
            if publish_attempted:
                message += "；帖子可能已提交，请先核查原作品，勿重新发布"
            raise LoginRequiredError(message, publish_attempted=publish_attempted)
    except LoginRequiredError:
        raise
    except Exception:
        # Locator failures must not hide the real upload error.
        return


async def is_logged_in(context, *, managed=True) -> bool:
    """Check current login evidence; local failures raise without closing owned pages.

    Managed mode keeps its existing bool probe and created-page cleanup.
    Local mode waits for the header account signal and maps explicit login or
    verification to LoginRequiredError; all other probe faults propagate.
    """
    page = await context.new_page()
    if not managed:
        await goto_local_dayu(page, DAYU_HOME_URL)
        name = page.locator(".header-info .name")
        try:
            await expect(name).to_have_count(1)
            await expect(name).to_be_visible()
            if (await name.inner_text()).strip():
                return True
            raise RuntimeError("大鱼号登录状态检查失败：后台页头账号名称为空")
        except Exception:
            await raise_if_login_required(page, managed=False)
            raise
    try:
        response = await page.goto(
            DAYU_HOME_URL,
            wait_until="domcontentloaded",
            timeout=DAYU_LOGIN_CHECK_TIMEOUT_MS,
        )
        status = getattr(response, "status", None)
        if isinstance(status, int) and status >= 500:
            raise RuntimeError(f"大鱼号登录状态检查失败：HTTP {status}")

        wait_for_timeout = getattr(page, "wait_for_timeout", None)
        if wait_for_timeout is not None:
            await wait_for_timeout(DAYU_LOGIN_CHECK_SETTLE_MS)

        current_url = str(getattr(page, "url", "") or "")
        if "mp.dayu.com" not in current_url:
            raise RuntimeError(
                "大鱼号登录状态检查失败：页面未停留在大鱼号后台"
                f"（url={current_url or '<empty>'}）"
            )
        if any(marker in current_url.lower() for marker in _LOGIN_URL_MARKERS):
            return False
        if await page.locator(_LOGIN_IFRAME).count():
            return False

        # 正向信号：后台页头账号名称存在且有内容。只判断已登录，不比较 wmid。
        name = page.locator(".header-info .name")
        if await name.count():
            try:
                text = (await name.first.inner_text()).strip()
            except Exception:
                text = ""
            if text:
                return True
        raise RuntimeError(
            "大鱼号登录状态检查失败：未找到后台页头账号名称（页面结构异常）"
        )
    finally:
        await close_browser_resources(page=page)


async def goto_local_dayu(page, url):
    """Preserve explicit auth evidence; transport/permissions remain faults."""
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception:
        await raise_if_login_required(page, managed=False)
        raise
    status = getattr(response, "status", None)
    if isinstance(status, int) and status >= 400:
        raise RuntimeError(f"大鱼号页面访问失败：HTTP {status}")
    await raise_if_login_required(page, managed=False)
    if urlsplit(str(page.url)).hostname != "mp.dayu.com":
        raise RuntimeError("大鱼号页面未停留在创作后台")


async def read_dayu_identity(page: Page) -> dict:
    """从后台页头及服务端注入的 wmid 读取当前主体，拒绝缺失或歧义。"""
    await raise_if_login_required(page, managed=False)
    # 页头账号区表达当前发布主体，限定 header-info 排除正文作者和作品列表里的同名文字。
    name = page.locator(".header-info .name")
    await expect(name).to_have_count(1)
    await expect(name).to_be_visible()
    scripts = "\n".join(await page.locator("script:not([src])").all_text_contents())
    ids = set(re.findall(r'''["']?wmid["']?\s*:\s*["']([a-f0-9]{32})["']''', scripts))
    if len(ids) != 1:
        raise RuntimeError("无法唯一识别大鱼号主体 wmid；请检查登录状态或页面结构")
    account_name = (await name.inner_text()).strip()
    if not account_name:
        raise RuntimeError("大鱼号页头账号名称为空")
    return {"wmid": ids.pop(), "name": account_name}


def dayu_account_alias(account_file=None, account_name=None):
    """Keep raw CLI aliases; legacy file arguments supply a label, never state."""
    if account_name is not None:
        return account_name
    if account_file is None:
        raise ValueError("需要大鱼号账号别名")
    return Path(account_file).stem.removeprefix("dayu_")


async def login_dayu_account(account_file=None, expected_name=None, timeout=600, *,
                             account_name=None, headless=None, local_browser=None) -> dict:
    """Only login guides the user; the selected Profile persists the identity."""
    account = dayu_account_alias(account_file, account_name)
    async with async_playwright() as playwright:
        async with local_browser_session(playwright, platform="dayu", account=account,
                                         headless=headless, local_browser=local_browser, create=True) as owned:
            page = await owned.context.new_page()
            response = await page.goto("https://mp.dayu.com/", wait_until="domcontentloaded", timeout=45000)
            status = getattr(response, "status", None)
            if isinstance(status, int) and status >= 400:
                raise RuntimeError(f"大鱼号登录页面访问失败：HTTP {status}")
            print("请在所选浏览器中完成大鱼号登录；账号密码及验证码直接在网页中输入。", flush=True)
            try:
                await page.wait_for_url("https://mp.dayu.com/dashboard/**", timeout=timeout * 1000)
            except Exception:
                await raise_if_login_required(page, managed=False)
                raise
            identity = await read_dayu_identity(page)
            if expected_name is not None and identity["name"] != expected_name:
                raise RuntimeError(f"登录主体不匹配，期望 {expected_name}，实际 {identity['name']}")
            return {"success": True, "account": account, "identity": identity}


async def check_dayu_account(account_file=None, *, account_name=None, headless=None, local_browser=None) -> bool:
    """Use positive login evidence in the selected Profile, without identity binding."""
    async with async_playwright() as playwright:
        async with local_browser_session(playwright, platform="dayu",
                                         account=dayu_account_alias(account_file, account_name),
                                         headless=headless, local_browser=local_browser) as owned:
            return await is_logged_in(owned.context, managed=False)
