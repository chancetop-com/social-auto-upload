# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import time
import inspect
import tempfile
from datetime import datetime
from pathlib import Path

from patchright.async_api import BrowserContext
from patchright.async_api import Page
from patchright.async_api import Playwright
from patchright.async_api import TimeoutError as PWTimeoutError
from patchright.async_api import async_playwright

import conf
from uploader.base_video import BaseVideoUploader
from utils.local_account import local_account_alias
from utils.browser_cleanup import close_browser_resources
from utils.browser_session import BrowserSession
from utils.browser_time import page_wall_clock
from utils.dom import ElementUnusableError, reject_ambiguous
from utils.errors import LoginRequiredError, UsageError
from utils.local_browser_session import local_browser_session
from utils.humanize import Humanizer
from utils.humanize import maybe_dispatched
from utils.login_qrcode import build_login_qrcode_path
from utils.login_qrcode import decode_qrcode_from_path
from utils.login_qrcode import print_terminal_qrcode
from utils.login_qrcode import remove_qrcode_file
from utils.login_qrcode import save_data_url_image
from utils.log import kuaishou_logger

KUAISHOU_UPLOAD_URL = "https://cp.kuaishou.com/article/publish/video"
KUAISHOU_MANAGE_URL = "https://cp.kuaishou.com/article/manage/video?status=2&from=publish"
KUAISHOU_LOGIN_URL = "https://passport.kuaishou.com/pc/account/login/?sid=kuaishou.web.cp.api&callback=https%3A%2F%2Fcp.kuaishou.com%2Frest%2Finfra%2Fsts%3FfollowUrl%3Dhttps%253A%252F%252Fcp.kuaishou.com%252Farticle%252Fpublish%252Fvideo%26setRootDomain%3Dtrue"
KUAISHOU_UPLOAD_URL_PATTERN = "**/article/publish/video**"
KUAISHOU_MANAGE_URL_PATTERN = "**/article/manage/video?status=2&from=publish**"
KUAISHOU_COOKIE_INVALID_SELECTOR = "div.names div.container div.name:text('机构服务')"
KUAISHOU_PUBLISH_STRATEGY_IMMEDIATE = "immediate"
KUAISHOU_PUBLISH_STRATEGY_SCHEDULED = "scheduled"
KUAISHOU_UPLOAD_TIMEOUT_SECONDS = 480
KUAISHOU_PUBLISH_ATTEMPTS = 3

KUAISHOU_LOGIN_CHECK_URL = KUAISHOU_UPLOAD_URL
KUAISHOU_LOGIN_CHECK_TIMEOUT_MS = 15_000
KUAISHOU_LOGIN_CHECK_SETTLE_MS = 2_000
KUAISHOU_LOGIN_BUTTON_TIMEOUT_MS = 8_000
KUAISHOU_LOGIN_INVALID_TIMEOUT_MS = 3_000

# Cover: the modal already holds the hidden image input.  Probe it briefly and
# write it directly; only a missing input falls back to the 「上传封面」 tab, and
# that click must be consumed by ``expect_file_chooser`` (XHS precedent bbc5361).
KUAISHOU_COVER_INPUT_PROBE_TIMEOUT_MS = 2_000
KUAISHOU_COVER_CHOOSER_TIMEOUT_MS = 10_000

# Preserve the historical ignored-option metadata for managed sessions.
# Local sessions obtain their effective source from resolve_local_browser.
LOCAL_CHROME_PATH = getattr(conf, "LOCAL_CHROME_PATH", "")


def _build_ks_launch_kwargs(executable_path: str | None = None) -> dict:
    executable = LOCAL_CHROME_PATH if executable_path is None else executable_path
    if executable:
        return {"executable_path": executable}
    return {"channel": "chromium"}


KUAISHOU_LAUNCH_KWARGS = _build_ks_launch_kwargs()
KUAISHOU_CONTEXT_KWARGS: dict = {}
KUAISHOU_INIT_SCRIPT = True

_LOGIN_URL_MARKERS = ("login", "captcha", "verify", "two-factor", "2fa")


def _msg(emoji: str, text: str) -> str:
    return f"{emoji} {text}"


def _normalise_text(text: str) -> str:
    """多行正文先 ``\\r\\n`` → ``\\n``；共享层的 ``\\r`` 会被 ``insert_text`` 丢弃。"""
    return str(text).replace("\r\n", "\n").replace("\r", "\n")


async def _dump_page_debug(page, tag: str) -> str:
    """出错时保存整页截图 + 当前 HTML，返回保存目录，便于对照新 DOM 修选择器。"""
    import time
    base = Path("ks_debug")
    base.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    try:
        await page.screenshot(path=str(base / f"{tag}_{ts}.png"), full_page=True)
    except Exception:
        pass
    try:
        (base / f"{tag}_{ts}.html").write_text(await page.content(), encoding="utf-8")
    except Exception:
        pass
    return str(base.resolve())


async def _cover_input_attached(locator) -> bool:
    """Short, read-only probe: is the hidden cover image input already there?

    Never clicks the 「上传封面」 tab to find out: that click opens a real OS file
    chooser which then lingers while ``set_input_files`` injects the file (same
    defect as XHS, bbc5361).
    """
    try:
        if not await locator.count():
            return False
        await locator.wait_for(
            state="attached", timeout=KUAISHOU_COVER_INPUT_PROBE_TIMEOUT_MS
        )
        return True
    except Exception:
        return False


async def _focus_desc_editor(page, humanizer: Humanizer) -> None:
    """定位并聚焦快手发布页的『描述』编辑区。

    快手创作者中心 DOM 时有改版，旧的
        get_by_text("描述").locator("xpath=following-sibling::div")
    一旦结构变化就会干等 30s 超时。这里按多种策略依次尝试（都锚定在「描述」
    标签附近，避免误点到标题框），每种短超时快速失败；全部失败则保存截图/HTML
    供排查后抛出明确错误，而不是无脑超时。

    每次聚焦都是 ``Humanizer.click``：策略 #0 是正常路径，回退分支也不再带
    ``force``——零尺寸 / 被遮挡的目标直接以 ``zero-box`` / ``covered-by:*``
    硬失败，不再伪造「已聚焦」的成功。
    """
    label = page.get_by_text("描述")  # 默认子串匹配，"作品描述" 等也能命中
    strategies = [
        # 旧结构：『描述』相邻 div
        lambda: label.locator("xpath=following-sibling::div"),
        # 新版描述区通常是紧随其后的富文本可编辑区
        lambda: label.locator("xpath=following::div[@contenteditable='true'][1]"),
        # 同容器内的可编辑区
        lambda: label.locator("xpath=ancestor::*[1]//div[@contenteditable='true'][1]"),
        # 兜底：其后第一个任意可编辑元素
        lambda: label.locator("xpath=following::*[@contenteditable='true'][1]"),
    ]
    last_err = None
    for i, make in enumerate(strategies):
        try:
            loc = make().first
            await loc.wait_for(state="visible", timeout=8000)
            await humanizer.click(loc)
            if i > 0:
                kuaishou_logger.warning(_msg(
                    "⚠️", f"描述区改用回退策略#{i}定位成功（快手可能已改版，建议核对选择器）"))
            return
        except ElementUnusableError:
            # 元素存在但不可用：选择器问题，直接失败，不再换策略掩盖。
            raise
        except Exception as e:  # noqa: BLE001
            last_err = e
    dbg = await _dump_page_debug(page, "desc_not_found")
    raise RuntimeError(
        f"未能定位快手『描述』编辑区（疑似发布页改版）。已保存截图/HTML 到 {dbg}，"
        f"请据此更新选择器。最后错误: {last_err}")


async def _click_visible_publish_confirm(page: Page, humanizer: Humanizer) -> bool:
    """Confirm an already-open Ant Design publish dialog before touching the page behind it."""
    modal = page.locator("div.ant-modal-confirm-centered:visible")
    if not await reject_ambiguous(modal, "快手发布确认弹窗"):
        return False

    primary_button = modal.locator("button.ant-btn-primary:visible")
    if not await reject_ambiguous(primary_button, "快手确认发布按钮"):
        raise RuntimeError("快手发布确认弹窗已显示，但未找到可点击的主按钮")

    await humanizer.click(primary_button)
    return True


def _print_ks_qrcode(qrcode_content: str, qrcode_path: Path) -> None:
    try:
        print_terminal_qrcode(qrcode_content, qrcode_path, "快手APP", compact=False, border=2)
    except TypeError as exc:
        if "unexpected keyword argument 'compact'" not in str(exc):
            raise
        kuaishou_logger.warning(_msg("😵", "检测到旧版二维码打印函数，小人切回兼容模式继续登录"))
        print_terminal_qrcode(qrcode_content, qrcode_path, "快手APP")


async def _emit_qrcode_callback(qrcode_callback, payload: dict):
    if not qrcode_callback:
        return

    callback_result = qrcode_callback(payload)
    if inspect.isawaitable(callback_result):
        await callback_result


def _build_login_result(
    success: bool,
    status: str,
    message: str,
    account_file: str,
    qrcode: dict | None = None,
    current_url: str = "",
) -> dict:
    return {
        "success": success,
        "status": status,
        "message": message,
        "account_file": str(account_file),
        "qrcode": qrcode,
        "current_url": current_url,
    }


async def _is_ks_cookie_invalid(page: Page, timeout: int = 5000) -> bool:
    try:
        await page.wait_for_selector(KUAISHOU_COOKIE_INVALID_SELECTOR, timeout=timeout)
        return True
    except Exception:
        return False


def _raise_if_login_required(page: Page, *, publish_attempted: bool = False) -> None:
    """Map a mid-upload login/captcha/2FA redirect to ``LoginRequiredError``.

    Managed branches keep their existing diagnostics. ``publish_attempted`` must be true
    when the redirect is observed after the publish click was dispatched.
    """
    url = str(getattr(page, "url", "") or "").lower()
    if not url:
        return
    if any(marker in url for marker in _LOGIN_URL_MARKERS):
        raise LoginRequiredError(
            "快手上传过程中需要重新登录（登录页/验证码/二次验证）："
            "请在 Multilogin 应用中登录 Profile 后重试。",
            publish_attempted=publish_attempted,
        )


def _raise_if_local_login_required(page, *, publish_attempted=False, verification_only=False):
    url = str(getattr(page, "url", "") or "").lower()
    verification = any(marker in url for marker in ("captcha", "verify", "two-factor", "2fa", "challenge"))
    if not verification and (verification_only or ("passport.kuaishou.com" not in url and "login" not in url)):
        return
    remedy = "请在所选 Profile 完成人机验证 (reason=verification)" if verification else "请运行 sau kuaishou login"
    stage = "；发布可能已提交，请先核查作品，禁止自动重发" if publish_attempted else ""
    raise LoginRequiredError(f"快手需要登录或验证；{remedy}{stage}。",
                             reason="verification" if verification else "login",
                             publish_attempted=publish_attempted)


async def is_logged_in(context: BrowserContext, *, managed=True) -> bool:
    """Probe the current Profile without changing its stored state.

    Local pages belong to their persistent context's bounded lifecycle; managed
    probes retain the historical per-page cleanup and classification.

    Only ``context.new_page()`` / ``goto`` / ``close`` are used.  A clear login
    page, the "立即登录" anchor, or the institution intro page returns ``False``;
    network failures, 5xx responses, timeouts and an unexpected structure raise
    so the CLI can exit 1 instead of treating an outage as "logged out".

    Worst-case budget: 15s navigation + 2s settle + 8s positive-anchor wait +
    3s intro-page check = 28s, inside the 15-30s spec.
    """
    page = await context.new_page()
    try:
        response = await page.goto(
            KUAISHOU_LOGIN_CHECK_URL,
            wait_until="domcontentloaded",
            timeout=KUAISHOU_LOGIN_CHECK_TIMEOUT_MS,
        )
        status = getattr(response, "status", None)
        if isinstance(status, int) and status >= (500 if managed else 400):
            raise RuntimeError(f"快手登录状态检查失败：HTTP {status}")

        wait_for_timeout = getattr(page, "wait_for_timeout", None)
        if wait_for_timeout is not None:
            await wait_for_timeout(KUAISHOU_LOGIN_CHECK_SETTLE_MS)

        if not managed:
            _raise_if_local_login_required(page)
        current_url = str(getattr(page, "url", "") or "")
        if "passport.kuaishou.com" in current_url:
            return False
        if "cp.kuaishou.com" not in current_url:
            raise RuntimeError(
                "快手登录状态检查失败：页面未停留在快手创作者平台"
                f"（url={current_url or '<empty>'}）"
            )

        login_btn = page.get_by_text("立即登录")
        if await login_btn.count() > 0 and (managed or await login_btn.is_visible()):
            return False

        # Positive proof: the upload button exists only for a logged-in session.
        upload_btn = page.locator("button[class^='_upload-btn']")
        try:
            await upload_btn.wait_for(
                state="visible", timeout=KUAISHOU_LOGIN_BUTTON_TIMEOUT_MS
            )
        except Exception as exc:
            if managed:
                invalid = await _is_ks_cookie_invalid(page, timeout=KUAISHOU_LOGIN_INVALID_TIMEOUT_MS)
            else:
                _raise_if_local_login_required(page)
                intro = page.locator(KUAISHOU_COOKIE_INVALID_SELECTOR)
                invalid = await intro.count() > 0 and await intro.is_visible()
            if invalid:
                return False
            raise RuntimeError(
                "快手登录状态检查失败：无法确认登录状态"
                f"（url={current_url}）：{exc}"
            ) from exc

        return True
    except Exception:
        if not managed:
            _raise_if_local_login_required(page)
        raise
    finally:
        if managed:
            await close_browser_resources(page=page)


async def _extract_ks_qrcode_src(page: Page) -> str:
    login_form = page.locator("main#login-form").first
    await login_form.wait_for(state="visible", timeout=30000)

    qrcode_img = login_form.locator('div.qr-login img[alt="qrcode"]').first
    try:
        if not await qrcode_img.count() or not await qrcode_img.is_visible():
            platform_switch = login_form.locator("div.platform-switch").first
            await platform_switch.wait_for(state="visible", timeout=10000)
            await platform_switch.click()  # native-click: login；扫码登录页切换二维码方式
            await asyncio.sleep(1)
    except Exception:
        platform_switch = login_form.locator("div.platform-switch").first
        await platform_switch.wait_for(state="visible", timeout=10000)
        await platform_switch.click()  # native-click: login；扫码登录页切换二维码方式
        await asyncio.sleep(1)

    await qrcode_img.wait_for(state="visible", timeout=15000)

    qrcode_src = await qrcode_img.get_attribute("src")
    if not qrcode_src:
        raise RuntimeError("未获取到快手登录二维码地址")

    return qrcode_src


async def _save_ks_qrcode(page: Page, account_file: str, previous_qrcode_path: Path | None = None, qrcode_callback=None) -> dict:
    qrcode_src = await _extract_ks_qrcode_src(page)
    qrcode_path = save_data_url_image(qrcode_src, build_login_qrcode_path(account_file, suffix="ks_login_qrcode"))

    if previous_qrcode_path and previous_qrcode_path != qrcode_path:
        if remove_qrcode_file(previous_qrcode_path):
            kuaishou_logger.info(_msg("🧹", f"临时二维码文件已清理: {previous_qrcode_path}"))

    kuaishou_logger.info(_msg("🖼️", f"二维码已经准备好啦，已保存到: {qrcode_path}"))
    qrcode_content = decode_qrcode_from_path(qrcode_path)
    if qrcode_content:
        _print_ks_qrcode(qrcode_content, qrcode_path)
    else:
        kuaishou_logger.warning(_msg("😵", f"终端没法完整显示二维码，请打开 {qrcode_path} 扫码"))

    qrcode_info = {
        "image_path": str(qrcode_path),
        "image_data_url": qrcode_src,
    }
    await _emit_qrcode_callback(qrcode_callback, qrcode_info)
    return qrcode_info


async def _is_ks_qrcode_expired(page: Page) -> bool:
    expired_box = page.locator("div.qrcode-status.qrcode-status-timeout").first
    try:
        if not await expired_box.count():
            return False
        return await expired_box.is_visible()
    except Exception:
        return False


async def _is_ks_login_page_gone(page: Page) -> bool:
    try:
        login_form = page.locator("main#login-form").first
        if not await login_form.count():
            return True
        return not await login_form.is_visible()
    except Exception:
        return True


def _account_alias(account_file=None, account_name=None):
    return local_account_alias(account_file, account_name, platform="kuaishou")


async def cookie_auth(account_file=None, *, account_name=None, headless=None, local_browser=None):
    """Check the selected persistent Profile; compatibility name only."""
    account = _account_alias(account_file, account_name)
    async with async_playwright() as playwright:
        async with local_browser_session(playwright, platform="kuaishou", account=account,
                                         headless=headless, local_browser=local_browser) as session:
            if not await is_logged_in(session.context, managed=False):
                raise LoginRequiredError("快手登录态失效；请运行 sau kuaishou login。")
            return True


async def ks_setup(account_file=None, handle=False, return_detail=False, qrcode_callback=None,
                   headless=None, cdp_url=None, *, account_name=None, local_browser=None):
    account = _account_alias(account_file, account_name)
    if cdp_url:
        raise UsageError("快手 login 使用本地 Profile；不支持外部 CDP 登录。")
    async with async_playwright() as playwright:
        async with local_browser_session(playwright, platform="kuaishou", account=account,
                                         create=handle, headless=headless,
                                         local_browser=local_browser) as session:
            login_detail = {}
            if handle:
                login_detail = await _login_in(session, account, qrcode_callback=qrcode_callback)
            if not await is_logged_in(session.context, managed=False):
                raise LoginRequiredError("快手登录态失效；请运行 sau kuaishou login。")
            result = _build_login_result(True, "logged_in", "快手登录成功", account,
                                         login_detail.get("qrcode"), login_detail.get("current_url", ""))
            result["account_name"] = account
            return result if return_detail else True


async def get_ks_cookie(account_file=None, qrcode_callback=None, headless=None,
                        poll_interval=3, max_checks=100, cdp_url=None, *,
                        account_name=None, local_browser=None):
    """Compatibility entry point: interactive login persists only in the Profile."""
    account = _account_alias(account_file, account_name)
    if cdp_url:
        raise UsageError("快手 login 使用本地 Profile；不支持外部 CDP 登录。")
    async with async_playwright() as playwright:
        async with local_browser_session(playwright, platform="kuaishou", account=account,
                                         create=True, headless=headless,
                                         local_browser=local_browser) as session:
            login_detail = await _login_in(session, account, qrcode_callback=qrcode_callback,
                                           poll_interval=poll_interval, max_checks=max_checks)
            if not await is_logged_in(session.context, managed=False):
                raise LoginRequiredError("快手扫码结束但尚未登录；请运行 sau kuaishou login。")
            result = _build_login_result(True, "logged_in", "快手登录成功", account,
                                         login_detail.get("qrcode"), login_detail.get("current_url", ""))
            result["account_name"] = account
            return result


async def _login_in(session, account, *, qrcode_callback=None, poll_interval=3, max_checks=100):
    page = await session.context.new_page()
    try:
        return await _login_on_page(page, qrcode_callback=qrcode_callback,
                             poll_interval=poll_interval, max_checks=max_checks)
    except Exception:
        _raise_if_local_login_required(page, verification_only=True)
        raise


async def _login_on_page(page, *, qrcode_callback, poll_interval, max_checks):
    response = await page.goto(KUAISHOU_LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
    status = getattr(response, "status", None)
    if isinstance(status, int) and status >= 400:
        raise RuntimeError(f"快手登录页面失败：HTTP {status}")
    if page.url.startswith(KUAISHOU_UPLOAD_URL):
        return {"qrcode": None, "current_url": page.url}
    kuaishou_logger.info("请在浏览器里扫码登录快手；登录态将保存到所选本地 Profile。")
    # QR artifacts are temporary UI assistance, never a second identity store.
    with tempfile.TemporaryDirectory(prefix="sau-kuaishou-login-", ignore_cleanup_errors=True) as directory:
        qrcode_target = str(Path(directory) / "login.png")
        qrcode_info = await _save_ks_qrcode(page, qrcode_target, qrcode_callback=qrcode_callback)
        qrcode_path = Path(qrcode_info["image_path"])
        for _ in range(max_checks):
            if page.url.startswith(KUAISHOU_UPLOAD_URL) or await _is_ks_login_page_gone(page):
                return {"qrcode": qrcode_info, "current_url": page.url}
            if await _is_ks_qrcode_expired(page):
                refresh_button = page.locator("p.qrcode-refresh").first
                if await refresh_button.count():
                    await refresh_button.click()  # native-click: login；二维码过期刷新
                    await asyncio.sleep(1)
                qrcode_info = await _save_ks_qrcode(page, qrcode_target, qrcode_path,
                                                  qrcode_callback=qrcode_callback)
                qrcode_path = Path(qrcode_info["image_path"])
            await asyncio.sleep(poll_interval)
        raise LoginRequiredError("等待快手扫码登录超时；请重新运行 sau kuaishou login。")


class KSBaseUploader(BaseVideoUploader):
    def __init__(
        self,
        publish_date: datetime | int,
        account_file,
        publish_strategy: str | None = None,
        debug: bool = False,
        headless: bool | None = None,
        *, account_name=None, local_browser=None,
    ):
        self.publish_date = publish_date
        self.account_file = None if account_file is None else str(account_file)
        self.publish_strategy = publish_strategy
        self.debug = debug
        self.headless = headless
        self.account_name = account_name
        self.local_browser = local_browser

    async def validate_base_args(self, *, check_cookie: bool = True):
        if self.publish_strategy is None:
            self.publish_strategy = (
                KUAISHOU_PUBLISH_STRATEGY_SCHEDULED
                if self.publish_date != 0
                else KUAISHOU_PUBLISH_STRATEGY_IMMEDIATE
            )

        if self.publish_strategy not in {
            KUAISHOU_PUBLISH_STRATEGY_IMMEDIATE,
            KUAISHOU_PUBLISH_STRATEGY_SCHEDULED,
        }:
            raise ValueError(f"不支持的发布策略: {self.publish_strategy}")

        if self.publish_strategy == KUAISHOU_PUBLISH_STRATEGY_SCHEDULED:
            self.publish_date = self.validate_publish_date(self.publish_date)
        else:
            self.publish_date = 0

    def _humanizer(self, page: Page) -> Humanizer:
        """发布链路的唯一行为层实例：指针位置与随机流保持连续。"""
        cached = getattr(self, "_humanizer_instance", None)
        if cached is None or cached.page is not page:
            cached = Humanizer(page, sleep=self._humanize_pause)
            self._humanizer_instance = cached
        return cached

    async def _humanize_pause(self, seconds: float) -> None:
        """行为层时延只吃预算上限，从不自己抛超时。"""
        remaining = max(0.0, self.publish_budget.remaining_seconds())
        if seconds > remaining and not getattr(self, "_pause_warned", False):
            kuaishou_logger.warning(_msg(
                "⚠️", f"人类化停顿被预算裁剪: {round(seconds, 2)}s > {round(remaining, 2)}s"))
            self._pause_warned = True
        await asyncio.sleep(min(seconds, remaining))

    async def set_schedule_time(
        self, page: Page, publish_date: datetime, humanizer: Humanizer
    ):
        publish_date = await page_wall_clock(page, publish_date)
        kuaishou_logger.info(_msg("🕒", "小人准备设置定时发布时间"))
        publish_date_str = publish_date.strftime("%Y-%m-%d %H:%M:%S")

        # 1. 切换到"定时发布"radio (用文本匹配更稳)
        schedule_radio = page.locator('label.ant-radio-wrapper').filter(has_text="定时发布")
        await humanizer.click(schedule_radio)
        await asyncio.sleep(2)

        # 2. 点击 picker 打开下拉面板
        date_input = page.locator('input[placeholder="选择日期时间"]')
        await humanizer.click(date_input)
        await asyncio.sleep(1)

        # 3. 用 React 兼容的方式直接设置 input 的 value
        #    (ant-design DatePicker 是 controlled component, 必须用 native setter + bubbling event)
        js_code = """
        (newValue) => {
            const input = document.querySelector('input[placeholder="选择日期时间"]');
            if (!input) return false;
            const nativeSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            nativeSetter.call(input, newValue);
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        }
        """
        ok = await page.evaluate(js_code, publish_date_str)
        if not ok:
            kuaishou_logger.error("❌ 找不到时间选择器输入框")
            return

        await asyncio.sleep(1)
        # 4. 按 Enter 确认
        await humanizer.press("Enter")
        await asyncio.sleep(2)
        kuaishou_logger.info(f"✅ 定时发布时间已设置为 {publish_date_str}")

    async def close_guide_overlay(self, page: Page) -> bool:
        """关闭快手创作者平台的 Joyride 引导遮罩。

        Joyride 有两个关键元素：
        1. tooltip (alertdialog) — 引导提示框，有关闭按钮
        2. spotlight (react-joyride__spotlight) — 聚光灯遮罩层，拦截点击事件
        两者可能独立存在。必须都关掉才能正常操作页面。
        """
        closed = False

        # 方式1：点击 tooltip 的关闭/跳过按钮
        joyride_tooltip = page.locator('div[id^="react-joyride-step"] div[role="alertdialog"]')
        if await joyride_tooltip.count() > 0 and await joyride_tooltip.first.is_visible():
            print("检测到 Joyride 引导遮罩，正在关闭...")
            # 尝试多种关闭按钮 selector
            close_selectors = [
                '[aria-label="Skip"], [data-action="skip"], button[title="Skip"]',
                'button:text("跳过")',
                'button:text("我知道了")',
                'button:text("关闭")',
                'button:text("下一步")',  # 有时需要多步跳过
            ]
            for sel in close_selectors:
                btn = page.locator('div[role="alertdialog"]').locator(sel)
                if await btn.count() > 0:
                    await btn.first.click(  # native-click: chrome；Joyride 引导层是非正常路径的遮罩清理
                        force=True,  # humanize-impossible: 遮罩拦截指针；needs-live；已排除坐标点击与 hover 显形
                    )
                    await asyncio.sleep(0.5)
                    break
            closed = True

        # 方式2：直接移除 Joyride portal（兜底，确保 spotlight 不再拦截）
        joyride_portal = page.locator('div#react-joyride-portal')
        if await joyride_portal.count() > 0:
            try:
                await page.evaluate("document.getElementById('react-joyride-portal')?.remove()")
                print("✅ 已移除 Joyride portal 遮罩")
                closed = True
            except Exception:
                pass

        # 方式3：移除 spotlight 元素
        spotlight = page.locator('div.react-joyride__spotlight')
        if await spotlight.count() > 0:
            try:
                await page.evaluate("document.querySelectorAll('.react-joyride__spotlight').forEach(e => e.remove())")
                print("✅ 已移除 Joyride spotlight")
                closed = True
            except Exception:
                pass

        if not closed:
            print("未检测到 Joyride 遮罩，继续执行")
        else:
            await asyncio.sleep(0.5)


class KSVideo(KSBaseUploader):
    publish_platform_label = "快手"

    def __init__(
        self,
        title,
        file_path,
        tags,
        publish_date: datetime | int,
        account_file,
        publish_strategy: str | None = None,
        debug: bool = False,
        headless: bool | None = None,
        thumbnail_path=None,
        desc: str | None = None,
        collection_name: str | None = None,
        *, account_name=None, local_browser=None,
    ):
        super().__init__(
            publish_date=publish_date,
            account_file=account_file,
            publish_strategy=publish_strategy,
            debug=debug,
            headless=headless,
            account_name=account_name,
            local_browser=local_browser,
        )
        self.title = title
        self.file_path = file_path
        self.tags = tags or []
        self.thumbnail_path = thumbnail_path
        self.desc = desc or ""
        self.collection_name = collection_name

    async def apply_collection(self, page: Page, humanizer: Humanizer) -> None:
        """在发布表单页选择"加入合集"下拉框（Ant Design Select，label 属性=合集名）。

        锚点用 label 文字"加入合集"精确定位紧邻的 ant-select 容器，避免误选页面上
        其它下拉框（服务类型/关联热点/作者声明/添加地点，同页面还有好几个 ant-select）。
        找不到匹配名字的合集选项时按 Escape 收起下拉，保持未选状态直接发布（界面允许留空，
        不阻断主发布流程）。
        """
        if not self.collection_name:
            return
        try:
            trigger = page.locator(
                'label:text-is("加入合集")'
            ).locator("xpath=following-sibling::div[contains(@class,'ant-select')]").first
            if await trigger.count() == 0:
                kuaishou_logger.warning(_msg("😵", "未找到\"加入合集\"下拉框，跳过归集"))
                return
            await humanizer.click(trigger.locator(".ant-select-selector"))
            await page.wait_for_timeout(800)

            option = page.locator(f'div.ant-select-item-option[label="{self.collection_name}"]')
            if await option.count() == 0:
                kuaishou_logger.warning(
                    _msg("😵", f"合集下拉框未找到「{self.collection_name}」，跳过归集，保持未选状态")
                )
                await humanizer.press("Escape")
                await page.wait_for_timeout(300)
                return

            await humanizer.click(option.first)
            await page.wait_for_timeout(500)
            kuaishou_logger.success(_msg("🥳", f"已选择合集：{self.collection_name}"))
        except Exception as exc:
            kuaishou_logger.warning(_msg("😵", f"选择合集失败，跳过归集继续发布: {exc}"))
            try:
                await humanizer.press("Escape")
            except Exception:
                pass

    async def validate_upload_args(self, *, check_cookie: bool = True):
        await self.validate_base_args(check_cookie=check_cookie)
        if not self.title or not str(self.title).strip():
            raise ValueError("快手视频上传时，title 是必须的")
        self.file_path = str(self.validate_video_file(self.file_path))
        if self.thumbnail_path:
            self.thumbnail_path = str(self.validate_image_file(self.thumbnail_path))

    async def handle_upload_error(self, page: Page):
        kuaishou_logger.warning(_msg("😵", "视频上传摔了一跤，小人马上重新上传"))
        await page.locator('div.progress-div [class^="upload-btn-input"]').set_input_files(self.file_path)

    async def set_thumbnail(self, page: Page, humanizer: Humanizer):
        if not self.thumbnail_path:
            return

        kuaishou_logger.info(_msg("🖼️", "小人准备设置封面"))

        cover_label = page.locator("span").filter(has_text="封面设置")
        await cover_label.wait_for(state="visible", timeout=30000)
        # 「封面设置」右侧是无文本 div：先收窄到该容器内第一个可见 div（具体可点
        # 元素），不再按 nth(0) 猜坐标。真机命中区仍待 acceptance 确认（§9 残留）。
        cover_entry = (
            cover_label.locator("xpath=../following-sibling::div[1]")
            .locator("div:visible")
            .first
        )
        await humanizer.click(cover_entry)

        modal = page.locator('div[role="document"].ant-modal')
        await modal.wait_for(state="visible", timeout=30000)

        # 封面图片 input 在弹窗里已经存在：优先直接写 input。禁止先点「上传封面」
        # tab——那一下会真的拉起系统文件选择器，随后 set_input_files 把文件塞进
        # 去，选择器会留在屏幕上（2026-11-12 TikTok 复现；先例小红书 bbc5361）。
        # tab 只在 input 缺失时兜底，且那一下必须由 expect_file_chooser 消费。
        file_input = modal.locator('input[type="file"]')
        if await _cover_input_attached(file_input):
            await file_input.set_input_files(self.thumbnail_path)
        else:
            await self._set_thumbnail_via_chooser(page, humanizer, modal)
        await asyncio.sleep(1)

        confirm_button = modal.get_by_role("button", name="确认", exact=True)
        await confirm_button.wait_for(state="visible", timeout=10000)
        await humanizer.click(confirm_button)

        await modal.wait_for(state="hidden", timeout=30000)
        kuaishou_logger.success(_msg("🥳", "封面已经设置完成"))

    async def _set_thumbnail_via_chooser(
        self, page: Page, humanizer: Humanizer, modal
    ) -> None:
        """兜底：input 缺失时才点「上传封面」，点击必须被 chooser 消费。

        chooser 事件没到也不能裸点第二次：点击可能已经把 input 渲染出来，
        这里改为重新解析 input 再直接写。
        """
        upload_cover_tab = modal.get_by_text("上传封面", exact=True)
        await upload_cover_tab.wait_for(state="visible", timeout=10000)
        chooser = None
        try:
            async with page.expect_file_chooser(
                timeout=KUAISHOU_COVER_CHOOSER_TIMEOUT_MS
            ) as chooser_info:
                await humanizer.click(upload_cover_tab)
            chooser = await chooser_info.value
        except PWTimeoutError:
            # 只有「选择器事件没到」才降级；人类化点击错误必须上抛
            # （spec §4.1-7：人类化失败不得自动降级）。
            chooser = None
        if chooser is not None:
            await chooser.set_files(self.thumbnail_path)
            return
        file_input = modal.locator('input[type="file"]')
        await file_input.wait_for(state="attached", timeout=30000)
        await file_input.set_input_files(self.thumbnail_path)

    async def upload(self, playwright: Playwright | None, *, session: BrowserSession | None = None) -> None:
        if session is not None:
            await self.validate_upload_args(check_cookie=False)
            await self.upload_in(session)
            return

        if playwright is None:
            raise ValueError("本地模式需要 Playwright 实例")

        await self.validate_upload_args(check_cookie=False)
        async with local_browser_session(
            playwright, platform="kuaishou", account=_account_alias(self.account_file, self.account_name),
            headless=self.headless, local_browser=self.local_browser,
        ) as local_session:
            if not await is_logged_in(local_session.context, managed=False):
                raise LoginRequiredError("快手登录态失效；请运行 sau kuaishou login。")
            await self.upload_in(local_session)

    async def upload_in(self, session: BrowserSession) -> None:
        self.start_publish_budget()
        self._publish_attempted = False
        page = await session.context.new_page()
        # 人类化实例在 page 创建后建立：HUMANIZE 在构造时快照，之后不再读 env。
        self._humanizer(page)
        try:
            response = await page.goto(KUAISHOU_UPLOAD_URL)
        except Exception:
            if not session.managed:
                _raise_if_local_login_required(page)
            raise
        if session.managed:
            _raise_if_login_required(page)
        else:
            _raise_if_local_login_required(page)
            status = getattr(response, "status", None)
            if isinstance(status, int) and status >= 400:
                raise RuntimeError(f"快手发布页面失败：HTTP {status}")
        kuaishou_logger.info(_msg("🏃", f"小人开始搬运视频: {self.title}.mp4"))
        kuaishou_logger.info(_msg("🧭", "小人正在赶往快手上传主页"))
        try:
            await page.wait_for_url(KUAISHOU_UPLOAD_URL_PATTERN)
            await self._upload_video_on_page(page, multilogin=session.managed)
        except Exception as exc:
            if not session.managed and not isinstance(exc, LoginRequiredError):
                _raise_if_local_login_required(page, publish_attempted=getattr(self, "_publish_attempted", False))
            raise

    async def _upload_video_on_page(self, page: Page, *, multilogin: bool = False) -> None:
        check_login = _raise_if_login_required if multilogin else _raise_if_local_login_required
        humanizer = self._humanizer(page)
        upload_button = page.locator("button[class^='_upload-btn']")
        await upload_button.wait_for(state="visible", timeout=10000)

        async with page.expect_file_chooser() as fc_info:
            await upload_button.click()  # native-click: file；文件选择器必须由原生点击派发
        file_chooser = await fc_info.value
        await file_chooser.set_files(self.file_path)

        await asyncio.sleep(2)

        know_button = page.locator('button[type="button"] span:text("我知道了")').first
        try:
            if await know_button.count() and await know_button.is_visible():
                await know_button.click()  # native-click: chrome；平台一次性「我知道了」提示条
        except Exception:
            pass

        await self.close_guide_overlay(page)

        kuaishou_logger.info(_msg("✍️", "小人开始填描述和话题"))
        # 再次检查并关闭 Joyride（可能在文件上传后才弹出）
        await self.close_guide_overlay(page)
        await _focus_desc_editor(page, humanizer)
        await humanizer.press("Backspace")
        await humanizer.press("Control+A")
        await humanizer.press("Delete")
        await humanizer.type_text(_normalise_text(self.desc or self.title))
        await humanizer.press("Enter")

        for index, tag in enumerate(self.tags[:3], start=1):
            kuaishou_logger.info(_msg("🏷️", f"小人正在添加第 {index} 个话题: #{tag}"))
            await humanizer.type_text(f"#{tag} ")
            await asyncio.sleep(2)

        budget = self.publish_budget
        upload_deadline = min(
            time.monotonic() + KUAISHOU_UPLOAD_TIMEOUT_SECONDS, budget.deadline
        )
        retry_count = 0
        while time.monotonic() < upload_deadline:
            if not multilogin:
                check_login(page)
            budget.check_pre_click()
            try:
                number = await page.locator("text=上传中").count()
                if number == 0:
                    kuaishou_logger.success(_msg("🥳", "视频已经传完啦"))
                    break

                if retry_count % 5 == 0:
                    kuaishou_logger.info(_msg("🏃", "小人正在努力上传视频"))

                if await page.locator("text=上传失败").count():
                    await self.handle_upload_error(page)

                await asyncio.sleep(2)
            except Exception as exc:
                check_login(page)
                kuaishou_logger.warning(_msg("😵", f"检查上传状态时出错，小人继续重试: {exc}"))
                await asyncio.sleep(2)
            retry_count += 1
        else:
            if budget.remaining_seconds() <= 0:
                raise budget.pre_click_error()
            raise TimeoutError(
                f"等待快手视频上传完成超时（>{KUAISHOU_UPLOAD_TIMEOUT_SECONDS}秒），已停止发布"
            )

        await self.set_thumbnail(page, humanizer)

        await self.apply_collection(page, humanizer)

        if self.publish_strategy == KUAISHOU_PUBLISH_STRATEGY_SCHEDULED and self.publish_date != 0:
            await self.set_schedule_time(page, self.publish_date, humanizer)

        await budget.wait_until_allowed(
            getattr(self, "publish_not_before", None),
            logger=kuaishou_logger,
            label="快手视频发布",
        )

        publish_clicked = False
        last_publish_error = None
        for attempt in range(1, KUAISHOU_PUBLISH_ATTEMPTS + 1):
            if not multilogin:
                check_login(page, publish_attempted=publish_clicked)
            if budget.remaining_seconds() <= 0:
                check_login(page, publish_attempted=publish_clicked)
                raise budget.timeout_error(publish_clicked)
            try:
                if not publish_clicked:
                    await humanizer.before_submit()
                    confirmed = await _click_visible_publish_confirm(page, humanizer)
                    if not confirmed:
                        publish_button = page.get_by_text("发布", exact=True)
                        if await reject_ambiguous(publish_button, "快手发布按钮") == 0:
                            raise RuntimeError("未找到快手发布按钮")
                        await humanizer.click(publish_button)
                        publish_clicked = True
                        self._publish_attempted = True
                        await asyncio.sleep(1)
                        await _click_visible_publish_confirm(page, humanizer)
                    publish_clicked = True
                    self._publish_attempted = True

                await page.wait_for_url(KUAISHOU_MANAGE_URL_PATTERN, timeout=5000)
                kuaishou_logger.success(_msg("🥳", "视频发布成功，小人开心收工"))
                break
            except Exception as exc:
                if not multilogin:
                    check_login(page, publish_attempted=publish_clicked or maybe_dispatched(exc))
                if maybe_dispatched(exc):
                    self._publish_attempted = True
                    # The publish/confirm click may already have landed:
                    # re-dispatching could publish twice.
                    raise budget.timeout_error(True) from exc
                if (isinstance(exc, ElementUnusableError)
                        and exc.reason.startswith("ambiguous:")):
                    if publish_clicked:
                        raise budget.timeout_error(True) from exc
                    raise
                check_login(page, publish_attempted=publish_clicked)
                last_publish_error = exc
                kuaishou_logger.info(_msg(
                    "🏃", f"小人正在冲刺发布视频（{attempt}/{KUAISHOU_PUBLISH_ATTEMPTS}）: {exc}"
                ))
                if self.debug:
                    await page.screenshot(full_page=True)
                await asyncio.sleep(1)
        else:
            if publish_clicked:
                raise budget.timeout_error(True)
            raise RuntimeError(
                f"快手发布连续失败 {KUAISHOU_PUBLISH_ATTEMPTS} 次，已停止重试: {last_publish_error}"
            )

    async def main(self, *, session: BrowserSession | None = None):
        if session is not None:
            await self.upload(None, session=session)
            return
        async with async_playwright() as playwright:
            await self.upload(playwright)


class KSNote(KSBaseUploader):
    publish_platform_label = "快手"

    def __init__(
        self,
        image_paths,
        note,
        tags,
        publish_date: datetime | int,
        account_file,
        title: str | None = None,
        publish_strategy: str | None = None,
        debug: bool = False,
        headless: bool | None = None,
        *, account_name=None, local_browser=None,
    ):
        super().__init__(
            publish_date=publish_date,
            account_file=account_file,
            publish_strategy=publish_strategy,
            debug=debug,
            headless=headless,
            account_name=account_name,
            local_browser=local_browser,
        )
        self.image_paths = image_paths
        self.note = note or ""
        self.title = title or (self.note[:20] if self.note else "")
        self.tags = tags or []

    async def validate_upload_args(self, *, check_cookie: bool = True):
        await self.validate_base_args(check_cookie=check_cookie)
        if not self.title or not str(self.title).strip():
            raise ValueError("快手图文上传时，title 是必须的")
        if not self.image_paths:
            raise ValueError("快手图文上传时，图片是必须的")

        if isinstance(self.image_paths, (str, Path)):
            self.image_paths = [self.image_paths]

        normalized_image_paths = []
        for image_path in self.image_paths:
            normalized_image_paths.append(str(self.validate_image_file(image_path)))
        self.image_paths = normalized_image_paths

    async def upload_note_content(self, page: Page, *, multilogin: bool = False) -> None:
        check_login = _raise_if_login_required if multilogin else _raise_if_local_login_required
        humanizer = self._humanizer(page)
        budget = self.publish_budget
        kuaishou_logger.info(_msg("🏃", f"小人开始搬运图文，共 {len(self.image_paths)} 张图片"))
        kuaishou_logger.info(_msg("🔀", "小人正在切换到图文发布"))
        image_tab = page.locator('div[role="tablist"] div[role="tab"]:has-text("图文")')
        await humanizer.click(image_tab)
        await humanizer.after_navigate()
        await page.wait_for_timeout(1000)

        kuaishou_logger.info(_msg("📤", "小人正在上传图片"))
        upload_button = page.locator("button[class^='_upload-btn']").filter(has_text="上传图片")
        await upload_button.wait_for(state="visible", timeout=10000)

        async with page.expect_file_chooser() as fc_info:
            await upload_button.click()  # native-click: file；文件选择器必须由原生点击派发
        file_chooser = await fc_info.value
        await file_chooser.set_files(self.image_paths)

        know_button = page.locator('button[type="button"] span:text("我知道了")').first
        try:
            if await know_button.count() and await know_button.is_visible():
                await know_button.click()  # native-click: chrome；平台一次性「我知道了」提示条
        except Exception:
            pass

        await self.close_guide_overlay(page)

        kuaishou_logger.info(_msg("✍️", "小人开始填写图文内容和话题"))
        await _focus_desc_editor(page, humanizer)
        await humanizer.press("Backspace")
        await humanizer.press("Control+A")
        await humanizer.press("Delete")
        await humanizer.type_text(_normalise_text(self.note))
        await humanizer.press("Enter")

        for index, tag in enumerate(self.tags[:3], start=1):
            kuaishou_logger.info(_msg("🏷️", f"小人正在添加第 {index} 个话题: #{tag}"))
            await humanizer.type_text(f"#{tag} ")
            await asyncio.sleep(2)

        max_retries = 60
        retry_count = 0
        while retry_count < max_retries:
            if not multilogin:
                check_login(page)
            budget.check_pre_click()
            try:
                number = await page.locator("text=上传中").count()
                if number == 0:
                    kuaishou_logger.success(_msg("🥳", "图文素材已经传完啦"))
                    break

                if retry_count % 5 == 0:
                    kuaishou_logger.info(_msg("🏃", "小人正在努力上传图文素材"))

                if await page.locator("text=上传失败").count():
                    kuaishou_logger.warning(_msg("😵", "图文素材上传摔了一跤，小人马上重新上传"))
                    await page.locator('div.progress-div [class^="upload-btn-input"]').set_input_files(self.image_paths)

                await asyncio.sleep(2)
            except Exception as exc:
                check_login(page)
                kuaishou_logger.warning(_msg("😵", f"检查图文上传状态时出错，小人继续重试: {exc}"))
                await asyncio.sleep(2)
            retry_count += 1

        if retry_count == max_retries:
            kuaishou_logger.warning(_msg("😵", "超过最大重试次数，图文上传可能未完成"))

        if self.publish_strategy == KUAISHOU_PUBLISH_STRATEGY_SCHEDULED and self.publish_date != 0:
            await self.set_schedule_time(page, self.publish_date, humanizer)

        await budget.wait_until_allowed(
            getattr(self, "publish_not_before", None),
            logger=kuaishou_logger,
            label="快手图文发布",
        )

        publish_clicked = False
        while True:
            if not multilogin:
                check_login(page, publish_attempted=publish_clicked)
            if budget.remaining_seconds() <= 0:
                check_login(page, publish_attempted=publish_clicked)
                raise budget.timeout_error(publish_clicked)
            try:
                if not publish_clicked:
                    await humanizer.before_submit()
                    publish_button = page.get_by_text("发布", exact=True)
                    if await reject_ambiguous(publish_button, "快手发布按钮") > 0:
                        await humanizer.click(publish_button)
                        publish_clicked = True
                        self._publish_attempted = True

                    await asyncio.sleep(1)
                    confirm_button = page.get_by_text("确认发布")
                    if await reject_ambiguous(confirm_button, "快手确认发布按钮") > 0:
                        await humanizer.click(confirm_button)
                    publish_clicked = True
                    self._publish_attempted = True

                await page.wait_for_url(KUAISHOU_MANAGE_URL_PATTERN, timeout=5000)
                kuaishou_logger.success(_msg("🥳", "图文发布成功，小人开心收工"))
                break
            except Exception as exc:
                if not multilogin:
                    check_login(page, publish_attempted=publish_clicked or maybe_dispatched(exc))
                if maybe_dispatched(exc):
                    self._publish_attempted = True
                    # 图文发布/确认发布可能已经点出去：绝不二次派发。
                    raise budget.timeout_error(True) from exc
                if (isinstance(exc, ElementUnusableError)
                        and exc.reason.startswith("ambiguous:")):
                    if publish_clicked:
                        raise budget.timeout_error(True) from exc
                    raise
                check_login(page, publish_attempted=publish_clicked)
                kuaishou_logger.info(_msg("🏃", f"小人正在冲刺发布图文: {exc}"))
                if self.debug:
                    await page.screenshot(full_page=True)
                await asyncio.sleep(1)

    async def upload(self, playwright: Playwright | None, *, session: BrowserSession | None = None) -> None:
        if session is not None:
            await self.validate_upload_args(check_cookie=False)
            await self.upload_in(session)
            return

        if playwright is None:
            raise ValueError("本地模式需要 Playwright 实例")

        await self.validate_upload_args(check_cookie=False)
        async with local_browser_session(
            playwright, platform="kuaishou", account=_account_alias(self.account_file, self.account_name),
            headless=self.headless, local_browser=self.local_browser,
        ) as local_session:
            if not await is_logged_in(local_session.context, managed=False):
                raise LoginRequiredError("快手登录态失效；请运行 sau kuaishou login。")
            await self.upload_in(local_session)

    async def upload_in(self, session: BrowserSession) -> None:
        self.start_publish_budget()
        self._publish_attempted = False
        page = await session.context.new_page()
        # 人类化实例在 page 创建后建立：HUMANIZE 在构造时快照，之后不再读 env。
        self._humanizer(page)
        try:
            response = await page.goto(KUAISHOU_UPLOAD_URL)
        except Exception:
            if not session.managed:
                _raise_if_local_login_required(page)
            raise
        if session.managed:
            _raise_if_login_required(page)
        else:
            _raise_if_local_login_required(page)
            status = getattr(response, "status", None)
            if isinstance(status, int) and status >= 400:
                raise RuntimeError(f"快手发布页面失败：HTTP {status}")
        kuaishou_logger.info(_msg("🧭", "小人正在赶往快手图文发布页"))
        try:
            await page.wait_for_url(KUAISHOU_UPLOAD_URL_PATTERN)
            await self.upload_note_content(page, multilogin=session.managed)
        except Exception as exc:
            if not session.managed and not isinstance(exc, LoginRequiredError):
                _raise_if_local_login_required(page, publish_attempted=getattr(self, "_publish_attempted", False))
            raise

    async def main(self, *, session: BrowserSession | None = None):
        if session is not None:
            await self.upload(None, session=session)
            return
        async with async_playwright() as playwright:
            await self.upload(playwright)
