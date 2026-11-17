"""通过 Patchright 在 Facebook 个人主页发布视频。

这里使用 Facebook 首页的个人/主页发帖 composer。Meta Business Suite 的 Page
发布和定时发布需要另一套已登录主体与权限，不能把它们和个人主页流程混用。
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from patchright.async_api import BrowserContext, Page, Playwright, async_playwright, expect

from uploader.publish_timeout import PublishTimeoutBudget
from utils.local_account import local_account_alias
from utils.browser_cleanup import close_browser_resources
from utils.browser_session import BrowserSession
from utils.errors import LoginRequiredError
from utils.local_browser_session import local_browser_session
from utils.humanize import Humanizer
from utils.humanize import maybe_dispatched
from utils.log import facebook_logger


FACEBOOK_HOME_URL = "https://www.facebook.com/"
# 代理只从显式 CLI 参数或用户自行设置的环境变量读取；未设置时直连。
FACEBOOK_PROXY = os.environ.get("SAU_FACEBOOK_PROXY")
FACEBOOK_LOGIN_INPUT = 'input[name="email"]'
# 首页发帖附件同时接受图片与视频，头像/封面控件不具备这组 MIME 类型。
FACEBOOK_MEDIA_INPUT = 'input[type="file"][accept*="image/"][accept*="video/"]'
# 选择素材后 composer 异步挂载；这里先等到可见的正文编辑器出现。
FACEBOOK_COMPOSER_READY = '[role="dialog"] [contenteditable="true"][role="textbox"]:visible'
# 外层 aria-modal dialog 属于本次发帖表单，排除首页评论框及隐藏模板。
FACEBOOK_COMPOSER_EDITOR = (
    '[role="dialog"][aria-modal="true"] [contenteditable="true"][role="textbox"]'
)
FACEBOOK_PUBLISH_FORM = '[role="dialog"][aria-modal="true"] form'

FACEBOOK_LOGIN_CHECK_TIMEOUT_MS = 20_000
FACEBOOK_LOGIN_CHECK_SETTLE_MS = 2_500

# Retain the managed ignored-option log contract. Local Profiles use the
# selected browser configuration instead of these historical options.
FACEBOOK_LAUNCH_KWARGS: dict[str, object] = {"channel": "chrome"}
FACEBOOK_CONTEXT_KWARGS: dict[str, object] = {}
FACEBOOK_INIT_SCRIPT = False

_FACEBOOK_LOGIN_URL_MARKERS = (
    "/login",
    "checkpoint",
    "two_step_verification",
    "/authentication/",
)


def _raise_if_login_required(page: Page, *, publish_attempted: bool = False) -> None:
    """Map a mid-upload login/captcha/2FA redirect to ``LoginRequiredError``.

    Managed sessions retain their existing redirect contract; local sessions
    use ``_local_login_guard``. ``publish_attempted`` is true when the redirect
    is observed after the publish click was dispatched.
    """
    current_url = str(getattr(page, "url", "") or "").lower()
    if any(marker in current_url for marker in _FACEBOOK_LOGIN_URL_MARKERS):
        raise LoginRequiredError(
            "Facebook 上传过程中需要重新登录（登录页/验证码/二次验证）："
            "请在 Multilogin 应用中登录 Profile 后重试。",
            publish_attempted=publish_attempted,
        )


def _proxy_options(proxy: str | None) -> dict[str, str] | None:
    """未传参数时使用显式环境配置，否则直连；空字符串可覆盖环境配置并直连。"""
    address = (FACEBOOK_PROXY if proxy is None else proxy) or ""
    address = address.strip()
    return {"server": address} if address else None


async def _is_logged_out(page: Page) -> bool:
    """根据登录流程标记和首页发帖业务锚点判断会话是否有效。"""
    current_url = page.url.lower()
    # two_step_verification 是登录流程中的二次验证页，不能误判成已登录首页。
    if any(
        marker in current_url
        for marker in ("/login", "checkpoint", "two_step_verification", "/authentication/")
    ):
        return True
    email_input = page.locator(FACEBOOK_LOGIN_INPUT)
    if await email_input.count() and await email_input.first.is_visible():
        return True
    # 发帖附件控件是首页 composer 已挂载的正向证据，空白页/登录中页面不能当作已登录。
    return await page.locator(FACEBOOK_MEDIA_INPUT).count() != 1


async def is_logged_in(context: BrowserContext) -> bool:
    """Return whether the Multilogin Profile is logged in to Facebook.

    Only ``context.new_page()`` / ``goto`` / ``close`` are used.  Explicit login,
    checkpoint and 2FA pages return ``False``; network failures, 5xx responses,
    timeouts and unexpected redirects raise so the CLI can exit 1 instead of
    treating an outage as "logged out".

    Worst-case budget: 20s navigation + 2.5s settle, inside the 15-30s spec.
    """
    page = await context.new_page()
    try:
        response = await page.goto(
            FACEBOOK_HOME_URL,
            wait_until="domcontentloaded",
            timeout=FACEBOOK_LOGIN_CHECK_TIMEOUT_MS,
        )
        status = getattr(response, "status", None)
        if isinstance(status, int) and status >= 500:
            raise RuntimeError(f"Facebook 登录状态检查失败：HTTP {status}")

        current_url = str(getattr(page, "url", "") or "")
        if "facebook.com" not in current_url.lower():
            raise RuntimeError(
                "Facebook 登录状态检查失败：页面未停留在 facebook.com"
                f"（url={current_url or '<empty>'}）"
            )
        if any(marker in current_url.lower() for marker in _FACEBOOK_LOGIN_URL_MARKERS):
            return False

        wait_for_timeout = getattr(page, "wait_for_timeout", None)
        if wait_for_timeout is not None:
            await wait_for_timeout(FACEBOOK_LOGIN_CHECK_SETTLE_MS)
        return not await _is_logged_out(page)
    finally:
        await close_browser_resources(page=page)


def _account_alias(account_file=None, account_name=None):
    return local_account_alias(account_file, account_name, platform="facebook")


async def _local_login_guard(page, *, publish_attempted=False):
    url = str(page.url).lower()
    verification = any(marker in url for marker in ("checkpoint", "two_step_verification", "/authentication/", "captcha"))
    login = "/login" in url
    if not verification and not login:
        email = page.locator(FACEBOOK_LOGIN_INPUT)
        login = await email.count() and await email.first.is_visible()
    if verification or login:
        raise LoginRequiredError(
            "Facebook 需要完成人机验证；请运行 sau facebook login --account <别名> 完成验证。" if verification else
            "Facebook 未登录；请先运行 sau facebook login --account <别名>。",
            reason="verification" if verification else "login", publish_attempted=publish_attempted,
        )


async def _navigate_local_page(page, *, timeout=FACEBOOK_LOGIN_CHECK_TIMEOUT_MS):
    from urllib.parse import urlsplit
    response = await page.goto(FACEBOOK_HOME_URL, wait_until="domcontentloaded", timeout=timeout)
    status = getattr(response, "status", None)
    if isinstance(status, int) and status >= 400:
        raise RuntimeError(f"Facebook 页面请求失败：HTTP {status}")
    if urlsplit(str(page.url)).hostname not in {"facebook.com", "www.facebook.com"}:
        raise RuntimeError("Facebook 页面未停留在 facebook.com")


async def _require_local_login(page):
    await _local_login_guard(page)
    media = page.locator(FACEBOOK_MEDIA_INPUT)
    try:
        await media.first.wait_for(state="attached", timeout=FACEBOOK_LOGIN_CHECK_TIMEOUT_MS)
    except Exception as error:
        await _local_login_guard(page)
        raise RuntimeError("Facebook 页面结构异常：未找到首页发帖控件") from error
    await _local_login_guard(page)
    if await media.count() != 1:
        raise RuntimeError("Facebook 页面结构异常：未找到唯一首页发帖控件")


async def facebook_cookie_auth(account_file=None, *, account_name=None, proxy=None,
                               headless=None, local_browser=None) -> bool:
    """Check the selected persistent Profile; the legacy filename only supplies an alias."""
    async with async_playwright() as playwright:
        async with local_browser_session(
            playwright, platform="facebook", account=_account_alias(account_file, account_name),
            headless=headless, local_browser=local_browser,
            context_kwargs={"proxy": _proxy_options(proxy)},
        ) as session:
            page = await session.context.new_page()
            await _navigate_local_page(page)
            await _require_local_login(page)
            return True


async def facebook_setup(account_file=None, *, handle=False, return_detail=False,
                         headless=None, proxy=None, timeout_seconds=600,
                         account_name=None, local_browser=None):
    """Only login creates a Profile and waits for interactive authentication."""
    account = _account_alias(account_file, account_name)
    if not handle:
        await facebook_cookie_auth(account_name=account, proxy=proxy,
                                   headless=headless, local_browser=local_browser)
        result = {"success": True, "status": "valid", "account": account}
        return result if return_detail else True
    async with async_playwright() as playwright:
        async with local_browser_session(
            playwright, platform="facebook", account=account, create=True,
            headless=headless, local_browser=local_browser,
            context_kwargs={"proxy": _proxy_options(proxy)},
        ) as session:
            page = await session.context.new_page()
            page.set_default_timeout(30_000)
            await _navigate_local_page(page, timeout=90_000)
            facebook_logger.info("请在打开的 Facebook 浏览器中完成登录；浏览器将保存 Profile 登录态")
            deadline = asyncio.get_running_loop().time() + timeout_seconds
            while asyncio.get_running_loop().time() < deadline:
                if not await _is_logged_out(page):
                    await _require_local_login(page)
                    result = {"success": True, "status": "logged_in", "account": account,
                              "message": "Facebook 登录成功，登录态保存在 Profile", "current_url": page.url}
                    return result if return_detail else True
                await page.wait_for_timeout(1000)
            await _local_login_guard(page)
            raise TimeoutError("等待 Facebook 登录超时，未观察到已登录首页")


def _composer_text(caption: str) -> str:
    """正文只允许 LF：``\r\n`` 与孤立 ``\r`` 一律归一为 ``\n``。

    ``\r`` 不是可打印字符，``type_text`` 会把它交给 ``insert_text``，浏览器
    可能直接丢弃；先统一换行，逐字输入才会与读回值一致。
    """
    return caption.replace("\r\n", "\n").replace("\r", "\n")


class FacebookPost:
    """通过个人主页 composer 发布一个视频或一组图片。"""

    def __init__(
        self,
        title: str,
        file_path: str | Path | list[Path],
        description: str,
        tags: list[str],
        account_file: str | Path | None = None,
        proxy: str | None = None,
        headless: bool | None = None,
        *, account_name=None, local_browser=None,
    ):
        self.title = title.strip()
        self.files = [Path(item) for item in file_path] if isinstance(file_path, list) else [Path(file_path)]
        self.file_path = self.files[0] if self.files else Path()
        self.description = description.strip()
        self.tags = [tag.strip().lstrip("#") for tag in tags if tag.strip().lstrip("#")]
        self.account_file = Path(account_file) if account_file is not None else None
        self.proxy = proxy
        self.headless = headless
        self.account_name = account_name
        self.local_browser = local_browser

    def _caption(self) -> str:
        """Facebook 首页没有独立视频标题字段，按项目统一约定合并为正文。"""
        parts = [part for part in (self.title, self.description) if part]
        if self.tags:
            parts.append(" ".join(f"#{tag}" for tag in self.tags))
        return "\n\n".join(parts)

    def _ensure_publish_budget(self) -> PublishTimeoutBudget:
        budget = getattr(self, "_publish_budget", None)
        if budget is None:
            budget = self._publish_budget = PublishTimeoutBudget("Facebook")
        return budget

    def _humanizer(self, page: Page) -> Humanizer:
        """发布链路的唯一行为层实例：指针与随机流在同一个 page 上保持连续。"""
        cached = getattr(self, "_humanizer_instance", None)
        if cached is None or cached.page is not page:
            cached = Humanizer(page, sleep=self._humanize_pause)
            self._humanizer_instance = cached
        return cached

    async def _humanize_pause(self, seconds: float) -> None:
        """停顿只吃剩余预算：耗尽时收缩到 0，超时判据仍只在发布点击处。"""
        remaining = max(0.0, self._ensure_publish_budget().remaining_seconds())
        if seconds > remaining and not getattr(self, "_pause_warned", False):
            facebook_logger.warning(
                "人类化停顿被预算裁剪: {}s > {}s",
                round(seconds, 2),
                round(remaining, 2),
            )
            self._pause_warned = True
        await asyncio.sleep(min(seconds, remaining))

    async def _find_caption_editor(self, page: Page):
        # 外层 aria-modal dialog 属于本次发帖表单，排除首页评论框及隐藏模板。
        editor = page.locator(FACEBOOK_COMPOSER_EDITOR)
        await expect(editor).to_have_count(1)
        return editor

    async def _find_publish_button(self, page: Page):
        # 发帖 form 的最后一个业务动作是提交，前面的按钮分别为编辑器关闭、隐私及附件编辑。
        # 图文/视频实际 DOM 均已检查；嵌套 dialog 实际是编辑器标题栏，不能把它当提交区域。
        form = page.locator(FACEBOOK_PUBLISH_FORM)
        await expect(form).to_have_count(1)
        button = form.get_by_role('button').last
        await expect(button).to_be_visible()
        return button

    async def _wait_until_publishable(self, page: Page, budget: PublishTimeoutBudget) -> None:
        deadline = asyncio.get_running_loop().time() + budget.clamp_seconds(180)
        while asyncio.get_running_loop().time() < deadline:
            budget.check_pre_click()
            if getattr(self, "_local_mode", False):
                await _local_login_guard(page)
            error = page.locator('[role="dialog"] [role="alert"]')
            if await error.count() and await error.first.is_visible():
                message = (await error.first.inner_text()).strip()
                if message:
                    raise RuntimeError(f"Facebook 视频上传失败: {message}")
            try:
                publish_button = await self._find_publish_button(page)
                if await publish_button.is_enabled():
                    return
            except RuntimeError as exc:
                if "未找到 Facebook 发布按钮" not in str(exc):
                    raise
            await page.wait_for_timeout(1000)
        raise TimeoutError("Facebook 视频上传或处理超时，发布按钮未就绪")

    async def _publish_and_verify(
        self, page: Page, budget: PublishTimeoutBudget
    ) -> None:
        publish_button = await self._find_publish_button(page)
        # 已实测成功提示是完整句子，不能把动态中任意“已发布”文案当成本次成功。
        success_pattern = re.compile(r"^(?:你的帖子已成功分享给.+|你的帖子已发布|Your post has been published[.!]?)$", re.I)
        success_text = page.get_by_text(success_pattern)
        for index in range(await success_text.count()):
            if await success_text.nth(index).is_visible():
                raise RuntimeError("提交前已存在发布成功提示，无法区分本次结果；未提交")
        await budget.wait_until_allowed(
            getattr(self, "publish_not_before", None),
            logger=facebook_logger,
            label="Facebook 发布",
        )
        budget.check_pre_click()
        humanizer = self._humanizer(page)
        # 发布是提交动作：先付一次 before_submit，再走坐标点击（人类化唯一路径）。
        await humanizer.before_submit()
        # 停顿可能吃掉最后的预算：派发前再确认一次（未发布，退出 1）。
        budget.check_pre_click()
        if getattr(self, "_local_mode", False):
            await _local_login_guard(page)
        try:
            await humanizer.click(publish_button)
        except Exception as exc:
            if getattr(self, "_local_mode", False):
                try:
                    await _local_login_guard(page, publish_attempted=maybe_dispatched(exc))
                except LoginRequiredError:
                    raise
                except Exception:
                    pass
            if maybe_dispatched(exc):
                # 发布点击可能已经发出：按结果未知上抛，禁止再次派发。
                raise budget.timeout_error(True) from exc
            raise
        self._publish_attempted = True
        while budget.remaining_seconds() > 0:
            if getattr(self, "_local_mode", False):
                await _local_login_guard(page, publish_attempted=True)
            # 只接受状态提示或成功文案；弹窗消失本身不足以证明服务端已受理。
            success_text = page.get_by_text(success_pattern)
            if await success_text.count():
                for index in range(await success_text.count()):
                    if await success_text.nth(index).is_visible():
                        return
            await page.wait_for_timeout(1000)
        raise budget.timeout_error(True)

    def _validate_media(self) -> None:
        if not self.files:
            raise ValueError("Facebook 发布素材不能为空")
        for file in self.files:
            if not file.is_file():
                raise FileNotFoundError(f"Facebook 素材文件不存在: {file}")
        if not self.title:
            raise ValueError("Facebook 视频标题不能为空")

    async def _publish_on_page(self, page: Page) -> None:
        # 已实测首页的唯一混合影音 input；按 accept 同时支持图片和视频限定，排除头像等控件。
        file_input = page.locator(FACEBOOK_MEDIA_INPUT)
        if await file_input.count() != 1:
            raise RuntimeError("首页发帖影音上传控件不唯一，未上传")
        await file_input.set_input_files([str(file) for file in self.files])

        budget = self._ensure_publish_budget()
        # 选择素材后 composer 异步挂载；不能在同一轮立即检查 count 就判输入框不存在。
        await page.locator(FACEBOOK_COMPOSER_READY).wait_for(
            timeout=budget.clamp_ms(30000)
        )
        editor = await self._find_caption_editor(page)
        # 正文 = 标题 + 正文 + 标签（``\n\n`` 连接）；多行字段只允许 LF。
        caption = _composer_text(self._caption())
        humanizer = self._humanizer(page)
        # sel 形态：坐标点击聚焦 → 全选 → 删除 → 逐字（>1000 码点由
        # ``type_text`` 整段 insert_text），``type_text`` 自带恰一次 after_type。
        await humanizer.click(editor)
        await humanizer.press("ControlOrMeta+A")
        await humanizer.press("Delete")
        await humanizer.type_text(caption)
        if (await editor.inner_text()).strip() != caption:
            raise RuntimeError("Facebook 正文输入框未读回预期内容")

        await self._wait_until_publishable(page, budget)
        await self._publish_and_verify(page, budget)

    async def upload_in(self, session: BrowserSession) -> None:
        """Consume the caller's context; its lifecycle and Profile lock stay borrowed."""
        self._ensure_publish_budget()
        self._local_mode = not session.managed
        self._publish_attempted = False
        page = await session.context.new_page()
        page.set_default_timeout(30_000)
        if session.managed:
            await page.goto(FACEBOOK_HOME_URL, wait_until="domcontentloaded",
                            timeout=self._ensure_publish_budget().clamp_ms(90_000))
            _raise_if_login_required(page)
        else:
            await _navigate_local_page(page, timeout=self._ensure_publish_budget().clamp_ms(90_000))
            await _require_local_login(page)
        try:
            await self._publish_on_page(page)
        except LoginRequiredError:
            raise
        except Exception:
            if not session.managed:
                try:
                    await _local_login_guard(page, publish_attempted=self._publish_attempted)
                except LoginRequiredError:
                    raise
                except Exception:
                    pass  # A disconnected page cannot replace the primary outcome.
                if self._publish_attempted:
                    raise self._ensure_publish_budget().timeout_error(True)
            raise
        if session.managed:
            _raise_if_login_required(page, publish_attempted=True)

    async def upload(self, playwright: Playwright | None, *, session: BrowserSession | None = None) -> None:
        self._validate_media()
        if session is not None:
            await self.upload_in(session)
            return
        if playwright is None:
            raise ValueError("本地模式需要 Playwright 实例")
        async with local_browser_session(
            playwright, platform="facebook", account=_account_alias(self.account_file, self.account_name),
            headless=self.headless, local_browser=self.local_browser,
            context_kwargs={"proxy": _proxy_options(self.proxy)},
        ) as session:
            await self.upload_in(session)

    async def main(self, *, session: BrowserSession | None = None) -> None:
        if session is not None:
            await self.upload(None, session=session)
            return
        async with async_playwright() as playwright:
            await self.upload(playwright)


# 保留原视频调用方的类名；视频和图文实际共用同一发帖表单，无额外包装层。
FacebookVideo = FacebookPost
