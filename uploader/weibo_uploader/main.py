# -*- coding: utf-8 -*-
"""微博视频上传 + 扫码登录。

功能：
  - weibo_cookie_gen: 持久化 Profile 扫码登录（微博 passport 二维码）
  - cookie_auth: 检查所选 Profile 的当前登录证据
  - weibo_setup: 统一入口（检查/触发登录）
  - WeiBoVideo: 视频上传类

基于 playwright codegen 录制脚本改写。
入口页：https://weibo.com/
发布页：点击首页「视频」入口弹出新窗口（视频发布页）
"""
from __future__ import annotations

import asyncio
import inspect
import re
import time
import tempfile
from urllib.parse import urlsplit
from pathlib import Path

from patchright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PWTimeoutError,
    async_playwright,
)

import conf
from uploader.base_video import BaseVideoUploader
from utils.local_account import local_account_alias
from utils.text_validation import validate_single_line
from utils.browser_cleanup import close_browser_resources
from utils.browser_session import BrowserSession
from utils.dom import ElementUnusableError, reject_ambiguous
from utils.errors import LoginRequiredError, PageCheckError, PublishResultUnknownError
from utils.local_browser import resolve_headless, resolve_local_browser
from utils.local_browser_session import local_browser_session
from utils.humanize import Humanizer, maybe_dispatched
from utils.log import weibo_logger
from utils.login_qrcode import build_login_qrcode_path


WEIBO_HOME_URL = "https://weibo.com/"
LOCAL_CHROME_PATH = getattr(conf, "LOCAL_CHROME_PATH", "")
WEIBO_LOGIN_URL = "https://weibo.com/newlogin?tabtype=weibo&gid=102803&openLoginLayer=0&url=https://weibo.com/"
# 微博 passport 扫码登录页（直接跳这里，绕过首页 popup）
WEIBO_PASSPORT_QR_URL = "https://passport.weibo.com/sso/signin?entry=miniblog&source=miniblog&url=https%3A%2F%2Fweibo.com%2F"

# 微博 passport 二维码选择器（扫码登录页中的二维码图片）
QR_SELECTOR = 'img[src*="qrcode"], img[src*="qr"]'


def _msg(emoji: str, text: str) -> str:
    return f"{emoji} {text}"


def _build_login_result(success: bool, status: str, message: str, account_file: str, qrcode: dict | None = None, current_url: str = "") -> dict:
    return {
        "success": success,
        "status": status,
        "message": message,
        "account_file": str(account_file),
        "qrcode": qrcode,
        "current_url": current_url,
    }


async def _emit_qrcode_callback(qrcode_callback, payload: dict):
    if not qrcode_callback:
        return
    callback_result = qrcode_callback(payload)
    if inspect.isawaitable(callback_result):
        await callback_result


def _build_launch_kwargs(headless: bool | None = None) -> dict:
    launch_kwargs = {}
    if LOCAL_CHROME_PATH:
        launch_kwargs["executable_path"] = LOCAL_CHROME_PATH
    if headless is not None:
        launch_kwargs["headless"] = headless
    return launch_kwargs


# Legacy managed launch options remain unchanged; local sessions use the resolver.
WEIBO_LAUNCH_KWARGS = _build_launch_kwargs()
WEIBO_CONTEXT_KWARGS = {}
WEIBO_INIT_SCRIPT = False

WEIBO_LOGIN_CHECK_TIMEOUT_MS = 25_000
WEIBO_LOGIN_CHECK_SETTLE_MS = 4_000
WEIBO_LOGIN_POSITIVE_SELECTORS = (
    '[class*="Nav_avatar"]',
    '[class*="woo-avatar"]',
    '[class*="Feed_content"]',
    '[class*="Feed_main"]',
)
WEIBO_LOGIN_URL_MARKERS = ("newlogin", "passport", "signin")


def _raise_if_login_required(page, *, publish_attempted: bool = False) -> None:
    """Map a mid-upload login/captcha/2FA redirect to ``LoginRequiredError``.

    Only managed sessions call this; local Profile sessions use their own
    login/verification diagnostics.  ``publish_attempted`` must be true when the
    redirect is observed after the publish click was dispatched.
    """
    url = str(getattr(page, "url", "") or "").lower()
    if not url:
        return
    if any(marker in url for marker in WEIBO_LOGIN_URL_MARKERS):
        raise LoginRequiredError(
            "微博上传过程中需要重新登录（登录页/验证码/二次验证）："
            "请在 Multilogin 应用中登录 Profile 后重试。",
            publish_attempted=publish_attempted,
        )
    if any(marker in url for marker in ("captcha", "verify", "two-factor", "2fa")):
        raise LoginRequiredError(
            "微博上传过程中需要重新登录（登录页/验证码/二次验证）："
            "请在 Multilogin 应用中登录 Profile 后重试。",
            publish_attempted=publish_attempted,
        )


async def is_logged_in(context: BrowserContext, *, managed=True, account=None) -> bool:
    """Check current page-level login evidence; preserve managed probe semantics.

    Requires a page-level positive signal: the avatar/feed marker.  Explicit
    login URLs and a visible「登录」button mean logged out; network errors,
    timeouts, 5xx, unexpected domains and a page with no positive signal raise
    (exit 1).

    Only ``context.new_page()`` / ``goto`` / ``close`` are used.
    """
    page = await context.new_page()
    try:
        response = await page.goto(
            WEIBO_HOME_URL,
            wait_until="domcontentloaded",
            timeout=WEIBO_LOGIN_CHECK_TIMEOUT_MS,
        )
        if not managed:
            _check_local_response(response)
        status = getattr(response, "status", None)
        if isinstance(status, int) and status >= 500:
            raise RuntimeError(f"微博登录状态检查失败：HTTP {status}")

        wait_for_timeout = getattr(page, "wait_for_timeout", None)
        if wait_for_timeout is not None:
            await wait_for_timeout(WEIBO_LOGIN_CHECK_SETTLE_MS)

        if not managed:
            return await _local_page_authenticated(page, account=account)
        current_url = str(getattr(page, "url", "") or "")
        lowered = current_url.lower()
        if any(marker in lowered for marker in WEIBO_LOGIN_URL_MARKERS):
            return False

        if "weibo.com" not in lowered:
            raise RuntimeError(
                "微博登录状态检查失败：页面未停留在微博"
                f"（url={current_url or '<empty>'}）"
            )

        for selector in WEIBO_LOGIN_POSITIVE_SELECTORS:
            locator = page.locator(selector).first
            if not await locator.count():
                continue
            try:
                if await locator.is_visible():
                    return True
            except Exception:
                continue

        login_btn = page.get_by_text("登录", exact=True).first
        if await login_btn.count() and await login_btn.is_visible():
            return False

        raise RuntimeError(
            "微博登录状态检查失败：未找到头像/feed 等已登录信号（页面结构异常）"
        )
    except PageCheckError:
        raise
    except Exception:
        if not managed:
            try:
                await _raise_local_login_required(page, account=account)
            except LoginRequiredError:
                raise
            except Exception:
                pass  # Keep the original network/page failure if diagnosis also fails.
        raise
    finally:
        if managed:
            await close_browser_resources(page=page)


def _account_alias(account_file=None, account_name=None):
    return local_account_alias(account_file, account_name, platform="weibo")


async def _grab_qr(page: Page, account_file: str) -> dict:
    """截取微博 passport 扫码登录二维码。

    微博 passport 登录页的二维码可能是 img 或 canvas，尝试多种选择器。
    """
    # 多种可能的二维码选择器（passport 页面结构可能变化）
    selectors = [
        'img[src*="qrcode"]',
        'img[src*="qr"]',
        'img[node-type="qrcode_img"]',
        '.qrcode img',
        'canvas',  # 部分版本用 canvas 绘制二维码
    ]

    qr = None
    for sel in selectors:
        loc = page.locator(sel).first
        if await loc.count():
            qr = loc
            weibo_logger.info(_msg("🔍", f"找到二维码元素: {sel}"))
            break

    if not qr:
        # 最后兜底：截取整个页面中心区域
        weibo_logger.warning(_msg("⚠️", "未找到二维码元素，截取页面截图"))
        qrcode_path = build_login_qrcode_path(account_file)
        qrcode_path.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(qrcode_path))
        weibo_logger.info(_msg("🖼️", f"页面截图已保存到: {qrcode_path}"))
        return {"image_path": str(qrcode_path), "image_data_url": ""}

    await qr.wait_for(state="visible", timeout=30000)

    qrcode_path = build_login_qrcode_path(account_file)
    qrcode_path.parent.mkdir(parents=True, exist_ok=True)

    # 优先直接下载高清图片 URL（img 元素）
    tag = await qr.evaluate("el => el.tagName.toLowerCase()")
    if tag == "img":
        src = await qr.get_attribute("src")
        if src and src.startswith("http"):
            try:
                resp = await page.context.request.get(src)
                qrcode_path.write_bytes(await resp.body())
            except Exception:
                await qr.screenshot(path=str(qrcode_path))
        else:
            await qr.screenshot(path=str(qrcode_path))
    else:
        # canvas 或其他元素：直接截图
        await qr.screenshot(path=str(qrcode_path))

    weibo_logger.info(_msg("🖼️", f"二维码已保存到: {qrcode_path}"))
    # 终端不渲染二维码，只给出文件位置，用微博APP打开图片扫码
    print(f"请打开 {qrcode_path}，用微博APP扫描该二维码登录")
    return {"image_path": str(qrcode_path), "image_data_url": ""}


def _check_local_response(response):
    status = getattr(response, "status", None)
    if isinstance(status, int) and status >= 400:
        raise PageCheckError(f"微博登录状态检查失败：HTTP {status}")


async def _local_visible(locator):
    return await locator.count() > 0 and await locator.is_visible()


async def _local_login_reason(page):
    url = str(page.url).lower()
    host = urlsplit(url).hostname or ""
    if host != "weibo.com" and not host.endswith(".weibo.com"):
        return None
    if any(marker in url for marker in ("captcha", "verify", "two-factor", "2fa")):
        return "verification"
    login_url = any(marker in url for marker in WEIBO_LOGIN_URL_MARKERS)
    try:
        if await _local_visible(page.locator('text="安全验证"').first):
            return "verification"
    except Exception:
        if not login_url:
            raise
    if login_url or await _local_visible(page.get_by_text("登录", exact=True).first):
        return "login"
    return None


def _local_login_error(account=None, *, reason="login", publish_attempted=False):
    action = "完成人机验证" if reason == "verification" else "完成登录"
    return LoginRequiredError(
        f"微博需要{action}（reason={reason}）；请运行 sau weibo login --account {account or '<account>'!r}，"
        "使用相同本地浏览器选择。提交后请先核对作品，不要自动重发。",
        reason=reason, publish_attempted=publish_attempted)


async def _raise_local_login_required(page, *, account=None, publish_attempted=False):
    reason = await _local_login_reason(page)
    if reason:
        raise _local_login_error(account, reason=reason, publish_attempted=publish_attempted)


async def _local_page_authenticated(page, *, account=None):
    reason = await _local_login_reason(page)
    if reason == "verification":
        raise _local_login_error(account, reason=reason)
    if reason == "login":
        return False
    if urlsplit(str(page.url)).hostname not in ("weibo.com", "www.weibo.com"):
        raise PageCheckError(f"微博登录检查失败：意外页面 {page.url}")
    for selector in WEIBO_LOGIN_POSITIVE_SELECTORS:
        if await _local_visible(page.locator(selector).first):
            return True
    raise PageCheckError("微博登录检查失败：缺少已登录头像/feed 信号（页面结构异常）")


async def weibo_cookie_gen(account_file=None, qrcode_callback=None, poll_interval=3,
                           max_checks=120, headless=None, *, account_name=None,
                           local_browser=None):
    """Guide login into the selected Profile; no Cookie JSON is read or written."""
    return await weibo_setup(account_file, handle=True, return_detail=True,
                             qrcode_callback=qrcode_callback, headless=headless,
                             account_name=account_name, local_browser=local_browser,
                             poll_interval=poll_interval, max_checks=max_checks)


async def cookie_auth(account_file=None, *, account_name=None, headless=None, local_browser=None):
    """Compatibility entry: check the selected persistent Profile only."""
    return await weibo_setup(account_file, account_name=account_name,
                             headless=headless, local_browser=local_browser)


async def weibo_setup(account_file=None, handle=False, return_detail=False,
                       qrcode_callback=None, headless=None, *, account_name=None,
                       local_browser=None, poll_interval=3, max_checks=120, session=None):
    account = _account_alias(account_file, account_name)
    if session is not None:
        if not await is_logged_in(session.context, managed=session.managed, account=account):
            raise _local_login_error(account)
        return True
    configuration = resolve_local_browser(headless=headless, local_browser=local_browser)
    async with async_playwright() as playwright:
        async with local_browser_session(playwright, platform="weibo", account=account,
                                         configuration=configuration, create=handle) as session:
            qrcode_info = None
            current_url = ""
            if not handle:
                if not await is_logged_in(session.context, managed=False, account=account):
                    raise _local_login_error(account)
            else:
                page = await session.context.new_page()
                response = await page.goto(WEIBO_HOME_URL, timeout=60000, wait_until="domcontentloaded")
                _check_local_response(response)
                await page.wait_for_timeout(WEIBO_LOGIN_CHECK_SETTLE_MS)
                reason = await _local_login_reason(page)
                if reason:
                    weibo_logger.info("请在所选浏览器完成微博登录/验证；无头模式可用 --headed 重开同一 Profile。")
                    with tempfile.TemporaryDirectory(prefix="sau-weibo-qr-", ignore_cleanup_errors=True) as qr_dir:
                        if reason == "login":
                            response = await page.goto(WEIBO_PASSPORT_QR_URL, timeout=60000, wait_until="domcontentloaded")
                            _check_local_response(response)
                            await page.wait_for_timeout(5000)
                            if await _local_login_reason(page) == "login":
                                qrcode_info = await _grab_qr(page, str(Path(qr_dir) / "login.png"))
                                await _emit_qrcode_callback(qrcode_callback, qrcode_info)
                        for _ in range(max_checks):
                            await page.wait_for_timeout(poll_interval * 1000)
                            reason = await _local_login_reason(page)
                            if not reason and await _local_page_authenticated(page, account=account):
                                break
                        else:
                            raise _local_login_error(account, reason=reason or "login")
                else:
                    await _local_page_authenticated(page, account=account)
                current_url = page.url
            result = _build_login_result(True, "profile_valid", "微博 Profile 登录有效", account,
                                         qrcode=qrcode_info, current_url=current_url)
            result["account_name"] = account
            return result if return_detail else True


class WeiBoVideo(BaseVideoUploader):
    """微博视频上传。

    流程：打开首页 → 点「视频」入口弹出发布窗口 → 上传视频文件 →
         等待上传完成 → 填标题 → 上传封面 → 勾选二创 + AI声明 →
         填描述 → 点击发布。
    """
    publish_platform_label = "微博"

    def __init__(
        self,
        title,
        file_path,
        tags,
        account_file,
        publish_date=0,
        desc: str | None = None,
        thumbnail_path: str | None = None,
        collection_name: str | None = None,
        debug: bool = False,
        headless: bool | None = None,
        *, account_name=None, local_browser=None,
    ):
        self.title = title
        self.file_path = file_path
        self.tags = tags or []
        self.account_file = (
            str(account_file) if account_file is not None else None
        )
        self.publish_date = publish_date
        self.desc = desc or ""
        self.thumbnail_path = thumbnail_path
        self.collection_name = collection_name
        self.debug = debug
        self.headless = resolve_headless(headless)
        self.account_name = account_name
        self.local_browser = local_browser
        self.max_title_length = 30

    async def validate_upload_args(self, *, check_cookie: bool = True):
        validate_single_line(self.title)
        if not self.title or not str(self.title).strip():
            raise ValueError("视频标题不能为空")
        if not self.thumbnail_path:
            raise ValueError("微博视频发布必须提供封面图（--thumbnail）")
        self.file_path = str(self.validate_video_file(self.file_path))
        self.thumbnail_path = str(self.validate_image_file(self.thumbnail_path))
        # 封面文件 < 5MB
        thumb_size = Path(self.thumbnail_path).stat().st_size
        if thumb_size > 5 * 1024 * 1024:
            raise ValueError(f"封面文件过大（{thumb_size / 1024 / 1024:.1f}MB），微博要求 < 5MB")

    async def upload(self, playwright: Playwright | None, *, session: BrowserSession | None = None) -> None:
        await self.validate_upload_args(check_cookie=False)
        if session is not None:
            if not session.managed and not await is_logged_in(session.context, managed=False, account=self.account_name):
                raise _local_login_error(self.account_name)
            await self.upload_in(session)
            return
        if playwright is None:
            raise ValueError("本地模式需要 Playwright 实例")
        self.account_name = _account_alias(self.account_file, self.account_name)
        async with local_browser_session(playwright, platform="weibo", account=self.account_name,
                                         headless=self.headless, local_browser=self.local_browser) as local_session:
            await self.upload(None, session=local_session)

    async def upload_in(self, session: BrowserSession) -> None:
        self.start_publish_budget()
        self._local_profile_upload = not session.managed
        self._publish_attempted = False
        self._active_page = None
        try:
            await self._upload_session(session)
        except PageCheckError:
            raise
        except Exception as error:
            if self._local_profile_upload and self._active_page is not None:
                try:
                    await _raise_local_login_required(self._active_page, account=self.account_name,
                                                     publish_attempted=self._publish_attempted)
                except LoginRequiredError:
                    raise
                except Exception:
                    pass  # A failed diagnostic must preserve the original operation error.
                if self._publish_attempted and not isinstance(error, (LoginRequiredError, PublishResultUnknownError)):
                    raise self.publish_budget.timeout_error(True) from error
            raise

    async def _upload_session(self, session):
        multilogin = session.managed
        page = await session.context.new_page()
        self._active_page = page
        response = await page.goto(WEIBO_HOME_URL, timeout=60000, wait_until="domcontentloaded")
        if self._local_profile_upload:
            _check_local_response(response)
            await _raise_local_login_required(page, account=self.account_name)
        await page.wait_for_timeout(3000)
        if multilogin:
            _raise_if_login_required(page)
        weibo_logger.info(_msg("🏃", f"开始上传视频: {self.title}"))

        # 1) 点击首页「视频」入口，弹出发布窗口（popup）
        publish_page = await self._open_video_publish_page(page, multilogin=multilogin)
        self._active_page = publish_page
        if self._local_profile_upload:
            await _raise_local_login_required(publish_page, account=self.account_name)

        # 发布页是另一个 page：必须换新实例，首页实例不得跨页复用。
        humanizer = self._humanizer(publish_page)

        # 2) 上传视频文件
        await self._upload_video_file(publish_page)

        # 3) 等待视频真正上传完成（"上传完成"块可见）
        await self._wait_upload_complete(publish_page)

        # 4) 类型 = 二创（必选）
        await self._select_type(publish_page, humanizer)

        # 5) 内容声明 = 含AI生成内容（必选）
        await self._select_declaration(publish_page, humanizer)

        # 6) 填写标题（必填）
        await self._fill_title(publish_page, humanizer)

        # 7) 上传封面（必填）
        await self._upload_thumbnail(publish_page, humanizer)

        # 8) 合集：选已有，没有则新建（配置了 collection_name 时）
        if self.collection_name:
            await self._apply_collection(publish_page, humanizer)

        # 9) 填写描述（包含标签）
        await self._fill_description(publish_page, humanizer)

        # 10) 点击发布并校验真成功
        await self._submit_publish(
            publish_page, multilogin=multilogin, humanizer=humanizer
        )

    def _humanizer(self, page: Page) -> Humanizer:
        """一个 page 一个实例；``cached.page is not page`` 即弃用重建。"""
        cached = getattr(self, "_humanizer_instance", None)
        if cached is None or cached.page is not page:
            cached = Humanizer(page, sleep=self._humanize_pause)
            self._humanizer_instance = cached
        return cached

    async def _humanize_pause(self, seconds: float) -> None:
        """行为层时延只吃预算上限，从不自己抛超时。"""
        remaining = max(0.0, self.publish_budget.remaining_seconds())
        if seconds > remaining and not getattr(self, "_pause_warned", False):
            weibo_logger.warning(
                _msg(
                    "⚠️",
                    "人类化停顿被预算裁剪: "
                    f"{round(seconds, 2)}s > {round(remaining, 2)}s",
                )
            )
            self._pause_warned = True
        await asyncio.sleep(min(seconds, remaining))

    async def _open_video_publish_page(self, page: Page, *, multilogin: bool = False) -> Page:
        """点击首页「视频」入口，等待 popup 视频发布页。"""
        humanizer = self._humanizer(page)
        async with page.expect_popup(timeout=30000) as popup_info:
            # 录制脚本：page.locator("span").filter(has_text="视频").click()
            video_btn = page.locator("span").filter(has_text="视频").first
            await video_btn.wait_for(state="visible", timeout=15000)
            await humanizer.click(video_btn)
            await humanizer.after_navigate()
        publish_page = await popup_info.value
        self._active_page = publish_page
        await publish_page.wait_for_timeout(3000)
        if multilogin:
            _raise_if_login_required(publish_page)
        weibo_logger.info(_msg("🏃", "已打开视频发布页"))
        return publish_page

    async def _upload_video_file(self, page: Page) -> None:
        """点击「上传视频」按钮并设置文件。"""
        # 录制脚本：page2.get_by_role("button", name="上传视频").click()
        upload_btn = page.get_by_role("button", name="上传视频")
        await upload_btn.wait_for(state="visible", timeout=15000)

        # 通过 file chooser 设置文件
        async with page.expect_file_chooser(timeout=10000) as fc_info:
            await upload_btn.click()  # native-click: file；文件选择结果只能由 set_files 传入
        file_chooser = await fc_info.value
        await file_chooser.set_files(self.file_path)
        weibo_logger.info(_msg("🏃", f"已选择视频文件: {self.file_path}"))

    async def _wait_upload_complete(self, page: Page, timeout: int = 900) -> None:
        """等待视频真正上传完成。

        真实 DOM：上传区有三个并列的 `_info` 块（上传中 / 暂停中 / 上传完成），未到的
        状态用 `display:none` 隐藏，只有当前状态那块可见：
          - 上传中：`<span>上传中</span>` + `269.61MB/269.61MB`
          - 上传完成：`<i class="woo-font woo-font--check">` + `<span>上传完成</span>`
        以"上传完成"块**变为可见**作为唯一完成判据（三块文字都恒在 DOM 里，不能用文字存在与否判断）。
        """
        budget = self.publish_budget
        timeout = budget.clamp_seconds(timeout)
        start = time.monotonic()
        done = page.locator('div:has(> i.woo-font--check) span:text-is("上传完成")').first
        uploading = page.locator('span:text-is("上传中")').first
        last_log = 0.0
        while True:
            budget.check_pre_click()
            if getattr(self, "_local_profile_upload", False):
                await _raise_local_login_required(page, account=self.account_name)
            if time.monotonic() - start > timeout:
                raise TimeoutError(f"视频上传超时（>{timeout}s）")

            body = ""
            try:
                body = await page.inner_text("body")
            except Exception:
                pass
            if "上传失败" in body:
                raise RuntimeError("视频上传失败")

            try:
                if await done.is_visible():
                    weibo_logger.success(_msg("🥳", "视频上传完毕（'上传完成' 可见）"))
                    return
            except Exception:
                pass

            if time.monotonic() - last_log > 5:
                try:
                    if await uploading.is_visible():
                        m = re.search(r"上传中[\s\S]{0,60}?([\d.]+)\s*MB\s*/\s*([\d.]+)\s*MB", body)
                        if m:
                            weibo_logger.info(_msg("🏃", f"上传中 {m.group(1)}/{m.group(2)}MB"))
                        else:
                            weibo_logger.info(_msg("🏃", "上传中…"))
                except Exception:
                    pass
                last_log = time.monotonic()
            await asyncio.sleep(2)

    async def _fill_title(self, page: Page, humanizer: Humanizer) -> None:
        """填写标题（最长30字）：聚焦合并进输入序列，全选覆盖后逐字输入。"""
        title_field = page.get_by_placeholder("填写标题（0～30个字）")
        await title_field.wait_for(state="visible", timeout=15000)
        count = await title_field.count()
        if count != 1:
            raise ElementUnusableError(
                what="标题输入框",
                role="editable",
                selector="placeholder:填写标题（0～30个字）",
                reason=f"ambiguous:{count}",
            )
        title = self.title[:self.max_title_length]
        await humanizer.click(title_field)
        await humanizer.press("ControlOrMeta+A")
        await humanizer.press("Delete")
        await humanizer.type_text(title)
        weibo_logger.info(_msg("🏷️", f"标题已填写: {title}"))

    async def _upload_thumbnail(self, page: Page, humanizer: Humanizer) -> None:
        """上传封面（必填）。

        真实 DOM/坑位：
          - 主表单 `<a>上传封面</a>` → 弹出「编辑封面」层 `_layer_1mhd8_153`（层内有
            `input[type=file]._file_1mhd8_65`，可直接 set_input_files）。
          - **关键坑**：选图后封面要走**服务端裁切**，期间层内显示"裁切处理中/处理中请稍后…"，
            "完成"按钮此时点了也不生效；而「编辑封面」层开着时，微博会把**主表单层
            `_layer_19x8d_246` 置为 display:none** → 之后的合集开关/发布按钮全部 0 尺寸点不动。
          - 因此必须：等裁切处理结束(cropper 出 blob 图) → **只点一次**"完成" → 等层关闭
            （不在等待循环里周期重复点），主表单才会恢复可见。
        """
        # 打开「上传封面」
        upload_link = page.get_by_role("link", name="上传封面").first
        if not await upload_link.count():
            upload_link = page.locator('a:has-text("上传封面")').first
        await upload_link.wait_for(state="visible", timeout=20000)
        await humanizer.click(upload_link)
        await page.wait_for_timeout(1200)

        # 「编辑封面」层
        cover_layer = page.locator('div.wbpro-layer:has(div:text-is("编辑封面"))').first
        await cover_layer.wait_for(state="visible", timeout=15000)

        # 塞封面文件（用 .first 命中可见主输入；.last 会命中隐藏面板里 0 尺寸的裁切器，
        # 导致"裁切处理中"永久卡住、发不出 picupload 请求）
        file_input = page.locator('input[type="file"][accept*="jpg"]').first
        await file_input.wait_for(state="attached", timeout=15000)
        # native-click: file；封面文件直接 set_input_files（.last 是隐藏裁切器）
        await file_input.set_input_files(self.thumbnail_path)
        weibo_logger.info(_msg("🏃", f"已选择封面图片: {self.thumbnail_path}"))

        # cropper 本地出图（秒级）
        blob_img = page.locator('.cropper-container img[src^="blob:"], .wb_cropper img[src^="blob:"]').first
        try:
            await blob_img.wait_for(state="attached", timeout=20000)
        except PWTimeoutError:
            weibo_logger.warning(_msg("⚠️", "cropper 未见 blob 图，仍尝试点完成"))
        await page.wait_for_timeout(500)

        # 「完成」只点一次：先等按钮可用（aria-disabled 解除），再走一次人类化点击。
        # 裁切处理中重复点击既无收益也会掩盖真实卡死，因此等待阶段不再周期性点击。
        finish_btn = cover_layer.locator('div.wbpro-layer-btn button:has(span:text-is("完成"))').first
        if not await finish_btn.count():
            finish_btn = cover_layer.locator('button:has(span:text-is("完成"))').first
        for _ in range(15):
            if not await finish_btn.count():
                break
            try:
                if (await finish_btn.get_attribute("aria-disabled")) != "true":
                    break
            except Exception:
                break
            await page.wait_for_timeout(1000)
        clicked_finish = False
        if await finish_btn.count() and await finish_btn.is_visible():
            await humanizer.click(finish_btn)
            clicked_finish = True
        closed = False
        start = time.monotonic()
        while time.monotonic() - start < 300:  # 宽松 5 分钟，且不突破总预算
            self.publish_budget.check_pre_click()
            if getattr(self, "_local_profile_upload", False):
                await _raise_local_login_required(page, account=self.account_name)
            # 结果判定：编辑封面层不再可见 → 成功
            try:
                if not await cover_layer.is_visible():
                    closed = True
                    break
            except Exception:
                closed = True
                break
            # 报错识别（裁切/格式/上传失败）
            try:
                layer_txt = await cover_layer.inner_text()
            except Exception:
                layer_txt = ""
            for err in ("裁切失败", "上传失败", "图片格式", "封面上传失败", "重新上传", "格式不支持"):
                if err in layer_txt:
                    raise RuntimeError(f"封面裁切/上传失败：{err}")
            await asyncio.sleep(2)
        if not closed:
            detail = "" if clicked_finish else "（「完成」按钮未出现）"
            raise RuntimeError(
                f"封面「完成」后编辑封面层长时间(>300s)未关闭{detail}，疑似裁切服务异常"
            )

        # 确认主表单层已恢复可见（display 从 none 变回）
        main_form = page.locator('div.wbpro-layer[class*="_layer_19x8d"]').first
        try:
            await main_form.wait_for(state="visible", timeout=10000)
        except PWTimeoutError:
            weibo_logger.warning(_msg("⚠️", "封面关闭后主表单未确认可见，继续尝试"))
        weibo_logger.success(_msg("🖼️", "封面已上传并完成"))

    async def _select_type(self, page: Page, humanizer: Humanizer) -> None:
        """类型（必选）：选择「二创」。

        真实 DOM：`<div class="_type_1vpmt_29">` 下两个
        `<label class="woo-radio-main"><input type=radio><span class="woo-radio-shadow"><span class="woo-radio-text">二创</span></label>`，
        选中后对应 `woo-radio-shadow` 追加 `woo-radio-checked`。
        """
        label = page.locator('label.woo-radio-main:has(span.woo-radio-text:text-is("二创"))').first
        await label.wait_for(state="visible", timeout=20000)
        await humanizer.click(label)
        await page.wait_for_timeout(500)

        checked_sel = 'label.woo-radio-main:has(span.woo-radio-text:text-is("二创")) span.woo-radio-checked'
        if not await page.locator(checked_sel).count():
            # 兜底：直接勾选 radio input（React 受控 radio 偶发吞掉坐标点击）
            try:
                await label.locator('input.woo-radio-input').check()
                await page.wait_for_timeout(300)
            except Exception:
                pass
        if not await page.locator(checked_sel).count():
            raise RuntimeError("类型「二创」未选中")
        weibo_logger.info(_msg("🏷️", "类型已选：二创"))

    async def _select_declaration(self, page: Page, humanizer: Humanizer) -> None:
        """内容声明（必选）：选择「含AI生成内容」。

        真实 DOM：
          - 触发下拉：`<div class="_gap1_nsgmr_26">` 内 `.woo-pop-ctrl`（带 caretDown 的 wbpro-select）
          - 弹层：`<div class="_panel_nsgmr_114">`，选项 `<button class="_option..."><span class="_optionLabel...">含AI生成内容</span></button>`
          - 选中后该 button 内 `._check_nsgmr_237` 追加 `_checkActive_nsgmr_251`（带 _checkMark）
          - 底部 `._footer_nsgmr_270 button`（"确定"）关闭弹层
        """
        # 打开下拉
        trigger = page.locator('div[class*="_gap1_nsgmr"] .woo-pop-ctrl').first
        if not await trigger.count():
            trigger = page.locator('div:has(> div[class*="_tit1_nsgmr"]) .woo-pop-ctrl').first
        await trigger.wait_for(state="visible", timeout=15000)
        await humanizer.click(trigger)
        await page.wait_for_timeout(1000)

        panel = page.locator('div[class*="_panel_nsgmr"]').first
        if await panel.count():
            try:
                await panel.wait_for(state="visible", timeout=8000)
            except PWTimeoutError:
                panel = None
        else:
            panel = None

        scope = panel if panel is not None else page
        ai_opt = scope.locator('button:has(span:text-is("含AI生成内容"))').first
        await ai_opt.wait_for(state="visible", timeout=8000)
        await humanizer.click(ai_opt)
        await page.wait_for_timeout(500)

        # 校验选中态
        if not await ai_opt.locator('[class*="_checkActive"]').count():
            weibo_logger.warning(_msg("⚠️", "内容声明「含AI生成内容」疑似未激活，仍尝试点确定"))

        # 点确定关闭弹层
        confirm = scope.locator('div[class*="_footer_nsgmr"] button:has(span:text-is("确定"))').first
        if not await confirm.count():
            confirm = scope.locator('button:has(span:text-is("确定"))').last
        if await confirm.count():
            await humanizer.click(confirm)
            await page.wait_for_timeout(500)
        weibo_logger.info(_msg("🏷️", "内容声明已选：含AI生成内容"))

    async def _fill_description(self, page: Page, humanizer: Humanizer) -> None:
        """填写描述区域（正文 + 标签）：全选覆盖后逐字输入。

        微博描述区 placeholder: "有什么新鲜事想分享给大家？"
        标签用 #话题# 格式插入到描述末尾。
        """
        desc_field = page.get_by_placeholder("有什么新鲜事想分享给大家？")
        count = await desc_field.count()
        if not count:
            weibo_logger.warning(_msg("⚠️", "未找到描述输入框"))
            return
        if count != 1:
            raise ElementUnusableError(
                what="描述输入框",
                role="editable",
                selector="placeholder:有什么新鲜事想分享给大家？",
                reason=f"ambiguous:{count}",
            )

        # 组装描述内容：正文 + 标签；多行先 \r\n → \n（\r 走 insert_text 可能被丢弃）。
        content = self.desc.replace("\r\n", "\n").replace("\r", "\n")
        if self.tags:
            tag_str = " ".join(f"#{t}#" for t in self.tags)
            content = f"{content}\n{tag_str}" if content else tag_str

        if content:
            await humanizer.click(desc_field)
            await humanizer.press("ControlOrMeta+A")
            await humanizer.press("Delete")
            await humanizer.type_text(content)
            weibo_logger.info(_msg("📝", f"描述已填写（{len(content)}字）"))

    async def _apply_collection(self, page: Page, humanizer: Humanizer) -> None:
        """合集：选已有，没有则新建。

        真实 DOM：打开「合集」开关后出现合集面板 `._scroll_19x8d_143`——已有合集每行一个
        `woo-checkbox` + 只读 `input value="名字(共N集)"`；末尾 `._add_19x8d_63`（「新建合集」）。
          - 已有：勾选名字匹配（去掉"(共N集)"后缀后）那一行的 checkbox。
          - 没有：点「新建合集」→ 新增一行(自动勾选)且带可编辑 input → 填合集名(≤12)。
        """
        target = (self.collection_name or "").strip()
        if not target:
            return

        # 1) 打开合集开关：点装饰层 `span[role=switch]`，失败不再 force / JS。
        block = page.locator('div[class*="_switch_"]:has(div[class*="_tit1_"]:text-is("合集"))').first
        if not await block.count():
            block = page.locator('div:has(> div:text-is("合集")):has(label.woo-switch-main)').first
        try:
            switch_input = block.locator('label.woo-switch-main input.woo-switch-input').first
            try:
                already = await switch_input.is_checked()
            except Exception:
                already = False
            if not already:
                for sw in (
                    block.locator('label.woo-switch-main span[role="switch"]').first,
                    block.locator('label.woo-switch-main').first,
                ):
                    try:
                        await humanizer.click(sw)
                    except ElementUnusableError:
                        continue
                    await page.wait_for_timeout(1000)
                    try:
                        if await switch_input.is_checked():
                            break
                    except Exception:
                        break
        except Exception as exc:
            weibo_logger.warning(_msg("⚠️", f"打开合集开关异常，仍尝试找面板: {exc}"))

        # 2) 合集面板
        panel = page.locator('div[class*="_scroll_"]:has(div[class*="_add_"])').first
        if not await panel.count():
            panel = page.locator('div:has(> div[class*="_add_"]:has-text("新建合集"))').first
        try:
            await panel.wait_for(state="visible", timeout=8000)
        except PWTimeoutError:
            weibo_logger.warning(_msg("⚠️", "未见合集面板，跳过合集"))
            return

        # 3) 匹配已有合集（去掉"(共N集)"后缀）
        rows = panel.locator('div[class*="_top2_"]')
        n = await rows.count()
        matched = False
        for i in range(n):
            row = rows.nth(i)
            inp = row.locator('input[type="text"]').first
            if not await inp.count():
                continue
            val = (await inp.get_attribute("value")) or ""
            name = re.sub(r"\(共\d+集\)\s*$", "", val).strip()
            if name and name == target:
                await humanizer.click(row.locator('label.woo-checkbox-main').first)
                await page.wait_for_timeout(400)
                matched = True
                weibo_logger.info(_msg("🥳", f"已选已有合集：{target}"))
                break

        # 4) 没有则新建（best-effort：新建失败只跳过合集，绝不中断发布）
        if not matched:
            try:
                add_btn = panel.locator('div[class*="_add_"]:has-text("新建合集")').first
                if not await add_btn.count():
                    add_btn = page.locator('div:has-text("新建合集")').last
                # 「新建合集」整行 598px 宽、可点的"＋新建合集"文字在左侧；点整行几何中心会落到
                # 右侧空白、不触发。改为点内部"新建合集"文字 span（在左侧、必命中 onClick）。
                add_target = add_btn.get_by_text("新建合集", exact=True).first
                if not await add_target.count():
                    add_target = add_btn
                # 新建行的可编辑 input（已有行的 input 都带 disabled，新建行的没有）
                new_inp = panel.locator('div[class*="_top2_"] input[type="text"]:not([disabled])').last
                await humanizer.click(add_target)
                created = False
                for _ in range(5):
                    if await new_inp.count() and await new_inp.is_visible():
                        created = True
                        break
                    await page.wait_for_timeout(800)
                if not created:
                    weibo_logger.warning(_msg("⚠️", f"「新建合集」未出现输入行，跳过合集继续发布：{target[:12]}"))
                    return
                await humanizer.click(new_inp)
                await humanizer.press("ControlOrMeta+A")
                await humanizer.press("Delete")
                await humanizer.type_text(target[:12])
                await page.wait_for_timeout(500)
                weibo_logger.info(_msg("🥳", f"已新建合集：{target[:12]}"))
            except Exception as exc:
                weibo_logger.warning(_msg("⚠️", f"新建合集失败，跳过合集继续发布：{exc}"))
                return

    async def _submit_publish(
        self,
        page: Page,
        *,
        multilogin: bool = False,
        humanizer: Humanizer | None = None,
    ) -> None:
        """点击发布并校验真成功。

        真实 DOM：
          - 发布按钮：`._check_2z30i_81 button`（内容"发布"）。按钮中心可能被空 div 覆盖，
            因此用**比例落点**点击：先 `(0.65, 0.5)`，确认未派发时换 `(0.35, 0.5)` 再试一次；
            仍失败即上抛 ``ElementUnusableError``，不退回 JS、不加 force。
            ``mouse.down`` 之后失败 = 可能已派发（``click_dispatched="maybe"``），不得再次派发。
          - 成功唯一可靠判据：隐藏成功层 `_layer1_9a8j7_2` 由 `display:none` 变**可见**，
            其中含"再发一条视频"按钮 → 用它/该按钮可见判定真成功。
            （"视频已上传成功，将在转码后发布"文字是恒存在的隐藏模板，不能作判据。）
          - 60s 内判不到成功 → 抛错（不再冒充成功），交由上层记失败。
        """
        humanizer = humanizer or self._humanizer(page)
        # 关掉可能残留的下拉/弹层
        try:
            await humanizer.press("Escape")
            await page.wait_for_timeout(300)
        except Exception:
            pass

        budget = self.publish_budget
        publish_btn = page.locator('div[class*="_check_2z30i"] button:has(span:text-is("发布"))')
        if not await reject_ambiguous(publish_btn, "发布按钮"):
            publish_btn = page.get_by_role("button", name="发布")
        await reject_ambiguous(publish_btn, "发布按钮")
        await publish_btn.wait_for(
            state="visible", timeout=budget.clamp_ms(15000)
        )
        # 使用实际窗口：先滚动，再由 Humanizer 校验可交互和落点。
        await publish_btn.scroll_into_view_if_needed()
        await budget.wait_until_allowed(
            getattr(self, "publish_not_before", None),
            logger=weibo_logger,
            label="微博发布",
        )
        budget.check_pre_click()
        await humanizer.before_submit()
        if getattr(self, "_local_profile_upload", False):
            await _raise_local_login_required(page, account=self.account_name)
        try:
            await humanizer.click(publish_btn, point=(0.65, 0.5))
        except Exception as exc:
            # 按下鼠标之后的任何异常（``mouse.down`` 之后的 Playwright/原生报错）
            # 都可能已经触发提交：禁止二次派发，按结果未知上抛。
            if maybe_dispatched(exc):
                self._publish_attempted = True
                raise budget.timeout_error(True) from exc
            if not isinstance(exc, ElementUnusableError):
                raise
            if exc.reason.startswith("ambiguous:"):
                raise
            if getattr(exc, "publish_clicked", False):
                self._publish_attempted = True
                # 确定已派发的异常：原样上抛，不再点第二次。
                raise
            weibo_logger.warning(
                _msg(
                    "⚠️",
                    f"发布按钮 (0.65,0.5) 未派发（{exc.reason or 'unusable'}），"
                    "改用 (0.35,0.5) 再试一次",
                )
            )
            try:
                await humanizer.click(publish_btn, point=(0.35, 0.5))
            except Exception as retry_exc:
                if maybe_dispatched(retry_exc):
                    self._publish_attempted = True
                    raise budget.timeout_error(True) from retry_exc
                raise
        weibo_logger.info(_msg("🏃", "已点击发布按钮"))
        publish_clicked = True
        self._publish_attempted = True

        success_layer = page.locator('div[class*="_layer1_9a8j7"]').first
        again_btn = page.locator('button:has(span:text-is("再发一条视频"))').first
        dialog_confirmed = False
        while budget.remaining_seconds() > 0:
            if getattr(self, "_local_profile_upload", False):
                await _raise_local_login_required(page, account=self.account_name, publish_attempted=True)
            if multilogin:
                _raise_if_login_required(page, publish_attempted=publish_clicked)
            try:
                if await again_btn.is_visible():
                    weibo_logger.success(_msg("🥳", "视频发布成功（出现「再发一条视频」）"))
                    return
            except Exception:
                pass
            try:
                if await success_layer.is_visible():
                    weibo_logger.success(_msg("🥳", "视频发布成功（成功层可见）"))
                    return
            except Exception:
                pass
            # 二次确认对话框只点一次，避免循环里重复提交。
            if not dialog_confirmed:
                # 先只做探测：探测失败沿用旧行为（跳过本轮），不碰确认按钮。
                confirm_button = None
                confirm_name = ""
                try:
                    dialog = page.locator('.woo-dialog-main, .woo-modal-wrap, [class*="Dialog"]').first
                    if await dialog.count() and await dialog.is_visible():
                        for name in ("确定", "确认", "继续", "仍然发布", "发布"):
                            cb = dialog.locator(f'button:has(span:text-is("{name}"))').first
                            if await cb.count() and await cb.is_visible():
                                confirm_button = cb
                                confirm_name = name
                                break
                except Exception:
                    confirm_button = None
                if confirm_button is not None:
                    # 派发前先落锁：即便这一次点击失败（可能已经派发），也绝不第二次点击。
                    dialog_confirmed = True
                    try:
                        await humanizer.click(confirm_button)
                    except Exception as exc:
                        if maybe_dispatched(exc):
                            # 确认点击可能已经发出：帖子可能已提交，按结果未知上抛。
                            raise budget.timeout_error(True) from exc
                        weibo_logger.warning(
                            _msg("⚠️", f"确认对话框点击失败（不重试）: {exc}")
                        )
                    else:
                        weibo_logger.info(_msg("🏃", f"已确认对话框：{confirm_name}"))
            await page.wait_for_timeout(1500)

        raise budget.timeout_error(True)

    async def main(self, *, session: BrowserSession | None = None):
        if session is not None:
            await self.upload(None, session=session)
            return
        async with async_playwright() as playwright:
            await self.upload(playwright)
