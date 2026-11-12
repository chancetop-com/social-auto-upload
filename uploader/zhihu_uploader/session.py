"""知乎登录会话保存与当前页身份核对。"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

from patchright.async_api import BrowserContext, Page, async_playwright, expect

from conf import LOCAL_CHROME_PATH
from uploader.zhihu_uploader.constants import ZHIHU_CREATOR_URL
from utils.errors import LoginRequiredError


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


def raise_if_login_required(page: Page) -> None:
    """Map a mid-upload Zhihu sign-in redirect to ``LoginRequiredError``.

    Only the Multilogin branch calls this; the local branch keeps its historical
    behaviour untouched.
    """
    if is_zhihu_login_url(str(getattr(page, "url", "") or "")):
        raise LoginRequiredError(
            "知乎上传过程中需要重新登录（登录页/验证码/二次验证）："
            "请在 Multilogin 应用中登录 Profile 后重试。"
        )


async def read_zhihu_identity(page: Page, *, timeout: int = 30000) -> dict:
    """从知乎页头已登录头像读取展示名与头像地址，作为本地会话绑定信息。"""
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
    avatar_path = urlsplit(avatar_url).path
    if not avatar_path:
        raise RuntimeError("知乎页头头像缺少稳定路径，无法绑定当前会话")
    return {"name": name, "avatar_path": avatar_path}


def load_zhihu_identity(account_file: str | Path) -> dict:
    """读取登录时记录的知乎页头信息，避免误用另一个本地账号文件。"""
    identity_file = Path(account_file).with_suffix(".identity.json")
    identity = json.loads(identity_file.read_text(encoding="utf-8"))
    if not identity.get("name") or not identity.get("avatar_path"):
        raise ValueError(f"知乎账号绑定不完整，请重新登录: {identity_file}")
    return identity


async def login_zhihu_account(account_file: str | Path, timeout: int = 600) -> dict:
    """在可见 Chrome 完成登录，核对页头账号后保存本地 storage state。"""
    if timeout <= 0:
        raise ValueError("登录期限必须大于 0 秒")
    account_file = Path(account_file).resolve()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path=LOCAL_CHROME_PATH or None, channel="chrome", headless=False,
        )
        try:
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(ZHIHU_CREATOR_URL, wait_until="domcontentloaded", timeout=45000)
            print("请在打开的 Chrome 中完成知乎登录；账号密码和验证码直接在网页输入。", flush=True)
            await page.locator(PROFILE_IMAGE).wait_for(state="visible", timeout=timeout * 1000)
            identity = await read_zhihu_identity(page)
            identity_file = account_file.with_suffix(".identity.json")
            if identity_file.exists() and load_zhihu_identity(account_file) != identity:
                raise RuntimeError("当前知乎页头与已绑定会话不同，请使用新的 --account")
            account_file.parent.mkdir(parents=True, exist_ok=True)
            await context.storage_state(path=str(account_file))
            identity_file.write_text(json.dumps(identity, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"success": True, "account_file": str(account_file), "identity": identity}
        finally:
            await browser.close()


async def is_logged_in(context: BrowserContext) -> bool:
    """Return whether the Multilogin Profile is logged in to Zhihu.

    Only ``context.new_page()`` / ``goto`` / ``close`` are used.  A clear
    sign-in/unlogin URL returns ``False``; network failures, 5xx responses,
    timeouts and unexpected page structures raise so the CLI exits 1 instead of
    misreporting an outage as "logged out".

    The profile header identity is reused only as a positive login signal; no
    ``.identity.json`` binding is read or compared in this path.

    Worst-case budget: 20s navigation + 10s identity probe, inside 15-30s.
    """
    page = await context.new_page()
    try:
        response = await page.goto(
            ZHIHU_CREATOR_URL,
            wait_until="domcontentloaded",
            timeout=ZHIHU_LOGIN_CHECK_TIMEOUT_MS,
        )
        status = getattr(response, "status", None)
        if isinstance(status, int) and status >= 500:
            raise RuntimeError(f"知乎登录状态检查失败：HTTP {status}")

        current_url = str(getattr(page, "url", "") or "")
        target = urlsplit(current_url)
        if target.hostname not in {"www.zhihu.com", "zhihu.com"}:
            raise RuntimeError(
                "知乎登录状态检查失败：页面未停留在知乎"
                f"（url={current_url or '<empty>'}）"
            )
        if is_zhihu_login_url(current_url):
            return False

        await read_zhihu_identity(page, timeout=ZHIHU_IDENTITY_PROBE_TIMEOUT_MS)
        return True
    finally:
        await page.close()


async def check_zhihu_account(account_file: str | Path, headless: bool = True) -> bool:
    """仅明确回到登录路径时返回失效；网络错误或身份不一致直接报告。"""
    account_file = Path(account_file)
    if not account_file.is_file():
        return False
    expected = load_zhihu_identity(account_file)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path=LOCAL_CHROME_PATH or None, channel="chrome", headless=headless,
        )
        try:
            context = await browser.new_context(storage_state=str(account_file))
            page = await context.new_page()
            response = await page.goto(ZHIHU_CREATOR_URL, wait_until="domcontentloaded", timeout=45000)
            if response is not None and response.status >= 400:
                raise RuntimeError(f"知乎创作中心访问失败，HTTP {response.status}")
            target = urlsplit(page.url)
            if target.path.startswith(("/signin", "/account/unlogin")):
                return False
            actual = await read_zhihu_identity(page)
            if actual != expected:
                raise RuntimeError("知乎当前页头与本地账号绑定不一致")
            return True
        finally:
            await browser.close()
