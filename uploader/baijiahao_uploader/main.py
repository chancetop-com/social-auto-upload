# -*- coding: utf-8 -*-
"""百家号（百度百家号）视频上传 + 扫码登录。

功能：
  - baijiahao_cookie_gen: headless 扫码登录（百度 passport 二维码）
  - cookie_auth: 验证 cookie 是否有效
  - baijiahao_setup: 统一入口（检查/触发登录）
  - BaiJiaHaoVideo: 视频上传类
"""
from __future__ import annotations

import asyncio
import inspect
import json as _json
import os
import time
from pathlib import Path

from patchright.async_api import BrowserContext, Page, Playwright, TimeoutError as PWTimeoutError, async_playwright

from conf import BASE_DIR, LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH
from uploader.base_video import BaseVideoUploader
from utils.browser_session import BrowserSession
from utils.dom import ElementUnusableError
from utils.errors import LoginRequiredError
from utils.humanize import Humanizer
from utils.humanize import maybe_dispatched
from utils.log import baijiahao_logger
from utils.login_qrcode import build_login_qrcode_path, decode_qrcode_from_path, print_terminal_qrcode, remove_qrcode_file


BAIJIAHAO_LOGIN_URL = "https://baijiahao.baidu.com/builder/theme/bjh/login"
BAIJIAHAO_HOME_URL = "https://baijiahao.baidu.com/builder/rc/home"
BAIJIAHAO_PUBLISH_URL = "https://baijiahao.baidu.com/builder/rc/edit?type=videoV2"
# 发布成功后跳转到的 URL 前缀
BAIJIAHAO_SUCCESS_URL_PREFIX = "https://baijiahao.baidu.com/builder/rc/clue"

# 标题是 contenteditable；页面可能把上传文件名自动填进来。
TITLE_EDITOR_SELECTOR = 'div[class*="contentEditable"]'

# 创作声明：点组件本体（antd 装饰层会拦截 placeholder input 的落点，不再用 force）。
AI_DECLARATION_TRIGGER_SELECTOR = '.cheetah-select:has(input[placeholder="请选择创作声明"])'
AI_DECLARATION_TRIGGER_FALLBACK = 'input[placeholder="请选择创作声明"]'
AI_DECLARATION_OPTION_SELECTOR = '.cheetah-modal-wrap :text("含AI生成内容")'
AI_DECLARATION_OPTION_FALLBACK = 'text="含AI生成内容"'
DECLARATION_MODAL_SELECTOR = '.cheetah-modal-wrap:visible'
DECLARATION_CONFIRM_SELECTOR = 'button:has-text("确定")'

# 合集：cheetah-select 下拉，搜索框逐字输入后按候选文本全等点选。
COLLECTION_SELECTOR = '.cheetah-select:has(.cheetah-select-selection-placeholder:has-text("选择同主题的合集"))'
COLLECTION_PLACEHOLDER_SELECTOR = '.cheetah-select-selection-placeholder:has-text("合集")'
COLLECTION_SEARCH_INPUT_SELECTOR = 'input.cheetah-select-selection-search-input'
COLLECTION_OPTION_SELECTOR = '.cheetah-select-item, [role="option"]'
COLLECTION_OPTION_TIMEOUT_MS = 8000

# 封面
COVER_ENTRY_SELECTOR = '[data-testid="select-cover"]'
COVER_UPLOAD_BUTTON_SELECTOR = 'button:has-text("上传"), div:has-text("上传"):not(:has(*)):visible'
COVER_IMAGE_INPUT_SELECTOR = 'input[type="file"][accept*="image"], input[type="file"][accept*="jpg"], input[type="file"][accept*="png"]'
COVER_CONFIRM_SELECTOR = 'button:has-text("确定"), button:has-text("完成"), button:has-text("确认")'
# 封面弹窗里已有隐藏图片 input。先短探测直接写；只有 input 缺失才点「上传」
# tab，且那一下必须由 expect_file_chooser 消费（先例：小红书 bbc5361）。
COVER_INPUT_PROBE_TIMEOUT_MS = 2_000
COVER_CHOOSER_TIMEOUT_MS = 10_000

# 发布
PUBLISH_BUTTON_SELECTOR = '[data-testid="publish-btn"]'
PUBLISH_BUTTON_TEXT_SELECTOR = 'button:text-is("发布")'
PUBLISH_BUTTON_CONTAINS_SELECTOR = 'button:has-text("发布")'

# 百度 passport 二维码图片选择器
QR_SELECTOR = 'img[src^="https://passport.baidu.com/v2/api/qrcode"]'

BAIJIAHAO_LOGIN_CHECK_TIMEOUT_MS = 20_000
BAIJIAHAO_LOGIN_CHECK_SETTLE_MS = 5_000
BAIJIAHAO_LOGIN_TEXT = "注册/登录百家号"
BAIJIAHAO_LOGIN_URL_MARKERS = ("login", "passport.baidu.com")

# Authenticated backend anchors.  A URL under ``/builder/rc/`` alone is not
# enough: an empty/error shell also lives there, so require at least one visible
# business control before declaring the profile logged in.
BAIJIAHAO_BUSINESS_ANCHOR_SELECTORS = (
    'a[href*="/builder/rc/edit"]',
    '[data-testid="publish-btn"]',
    '.cheetah-layout-sider',
    '[class*="user-info"]',
    '[class*="avatar"]',
)

_BAIJIAHAO_LOGIN_HINTS = (
    "login",
    "passport.baidu.com",
    "captcha",
    "verify",
    "two-factor",
    "2fa",
)


async def _cover_input_attached(locator) -> bool:
    """Short, read-only probe: is the hidden cover image input already there?

    Never clicks the 「上传」 tab/button to find out: that click opens a real OS
    file chooser which then lingers while ``set_input_files`` injects the file
    (same defect as XHS, bbc5361).
    """
    try:
        if not await locator.count():
            return False
        await locator.wait_for(
            state="attached", timeout=COVER_INPUT_PROBE_TIMEOUT_MS
        )
        return True
    except Exception:
        return False


def _raise_if_login_required(page: Page, *, publish_attempted: bool = False) -> None:
    """Map a mid-upload login/captcha/2FA redirect to ``LoginRequiredError``.

    Only the Multilogin branch calls this; the local branch keeps its historical
    retry-until-timeout behaviour.  ``publish_attempted`` must be true when the
    redirect is observed after the publish click was dispatched, so exit 10
    never claims "not published".
    """
    url = str(getattr(page, "url", "") or "").lower()
    if not url:
        return
    if any(marker in url for marker in _BAIJIAHAO_LOGIN_HINTS):
        raise LoginRequiredError(
            "百家号上传过程中需要重新登录（登录页/验证码/二次验证）："
            "请在 Multilogin 应用中登录 Profile 后重试。",
            publish_attempted=publish_attempted,
        )


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


def _build_launch_kwargs(headless: bool) -> dict:
    launch_kwargs = {"headless": headless}
    if LOCAL_CHROME_PATH:
        launch_kwargs["executable_path"] = LOCAL_CHROME_PATH
    return launch_kwargs


# Golden local-mode browser options.  ``sau_commands/baijiahao.py`` passes the
# same values to ``browser_session`` in Multilogin mode, so the two paths cannot
# drift.  ``launch_kwargs`` never contains ``headless`` (it is injected by the
# session seam).  Multilogin ignores all three values.
BAIJIAHAO_LAUNCH_KWARGS = {
    key: value
    for key, value in _build_launch_kwargs(headless=False).items()
    if key != "headless"
}
BAIJIAHAO_CONTEXT_KWARGS = {"permissions": ["geolocation"]}
BAIJIAHAO_INIT_SCRIPT = False
# Multilogin ignores ``context_kwargs`` (no ``grant_permissions``).  The publish
# flow never calls ``navigator.geolocation``, so v1 does not depend on the
# permission; ticket 08 acceptance should still confirm this on a real profile.


def _resolve_account_file(account_file: str | Path) -> str:
    path = Path(account_file).expanduser()
    if path.is_absolute():
        return str(path)
    if len(path.parts) == 1:
        return str((Path(BASE_DIR) / "cookies" / "baijiahao_uploader" / path).resolve())
    return str(path.resolve())


async def _grab_qr(page: Page, account_file: str) -> dict:
    """截取百度 passport 扫码登录二维码。

    百家号登录页点「登录」后弹出百度统一登录框，其中二维码是 img[src] 指向
    passport.baidu.com 的图片 URL，可以直接下载或截图。
    """
    qr = page.locator(QR_SELECTOR).first
    await qr.wait_for(state="attached", timeout=60000)

    qrcode_path = build_login_qrcode_path(account_file)
    qrcode_path.parent.mkdir(parents=True, exist_ok=True)

    # 优先直接下载高清图片 URL
    src = await qr.get_attribute("src")
    if src and src.startswith("https://"):
        try:
            resp = await page.context.request.get(src)
            qrcode_path.write_bytes(await resp.body())
        except Exception:
            await qr.screenshot(path=str(qrcode_path))
    else:
        await qr.screenshot(path=str(qrcode_path))

    qrcode_content = decode_qrcode_from_path(qrcode_path)
    baijiahao_logger.info(_msg("🖼️", f"二维码已保存到: {qrcode_path}"))
    if qrcode_content:
        print_terminal_qrcode(qrcode_content, qrcode_path, "百度APP/手机百度")
    else:
        baijiahao_logger.warning(_msg("😵", f"终端没法完整显示二维码，请打开 {qrcode_path} 扫码"))
    return {"image_path": str(qrcode_path), "image_data_url": ""}


async def _is_login_completed(page: Page) -> bool:
    """判断百度登录是否完成：URL 离开 login 页 或 出现 BDUSS cookie。"""
    if "login" in page.url.lower():
        # 还在登录页，检查 cookies
        cookies = await page.context.cookies()
        if any(c.get("name") in ("BDUSS", "STOKEN") for c in cookies):
            return True
        return False
    # 跳走了说明登录成功
    return True


async def baijiahao_cookie_gen(account_file, qrcode_callback=None, poll_interval: int = 3, max_checks: int = 120, headless: bool = LOCAL_CHROME_HEADLESS):
    """无头/有头扫码登录百家号，保存 cookie。

    流程：打开登录页 → 点「登录」按钮弹出百度 passport 登录框 → 截取二维码 → 等待扫码完成 → 保存 storage_state。
    返回标准 login result dict。
    """
    account_file = _resolve_account_file(account_file)
    Path(account_file).parent.mkdir(parents=True, exist_ok=True)
    qrcode_path = None
    result = _build_login_result(False, "failed", "百家号登录失败", account_file)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**_build_launch_kwargs(headless=headless))
        context = await browser.new_context()
        try:
            page = await context.new_page()
            await page.goto(BAIJIAHAO_LOGIN_URL, timeout=60000, wait_until="domcontentloaded")
            await page.wait_for_timeout(4000)

            # 点击「登录」按钮触发百度 passport 弹窗
            login_btn = page.get_by_text("登录", exact=True).first
            try:
                await login_btn.click(timeout=10000)  # native-click: login；百度 passport 二维码弹窗属登录路径，非用户内容交互
            except Exception:
                # 有些情况直接就在登录状态
                pass
            await page.wait_for_timeout(4000)

            if headless:
                baijiahao_logger.info(_msg("🧍", "无头登录中：二维码已存为图片，请用百度APP扫码"))
            else:
                baijiahao_logger.info(_msg("🧍", "请在打开的浏览器中扫码登录百家号"))

            # 截取二维码
            qrcode_info = await _grab_qr(page, account_file)
            qrcode_path = Path(qrcode_info["image_path"]) if qrcode_info.get("image_path") else None
            await _emit_qrcode_callback(qrcode_callback, qrcode_info)

            baijiahao_logger.info(_msg("🧍", "请扫码，正在耐心等待登录完成"))

            # 轮询等待登录完成
            for _ in range(max_checks):
                if await _is_login_completed(page):
                    baijiahao_logger.info(_msg("🥳", f"扫码成功，当前页面: {page.url}"))
                    result = _build_login_result(True, "success", "百家号扫码登录成功", account_file, qrcode_info, page.url)
                    break
                await page.wait_for_timeout(poll_interval * 1000)
            else:
                result = _build_login_result(False, "timeout", "等待百家号扫码登录超时", account_file, qrcode_info, page.url)

            if result["success"]:
                await asyncio.sleep(2)
                await context.storage_state(path=account_file)
                baijiahao_logger.success(_msg("🥳", f"cookie 已保存: {account_file}"))
        except Exception as exc:
            result = _build_login_result(False, "failed", str(exc), account_file, current_url=page.url if "page" in locals() else "")
        finally:
            if remove_qrcode_file(qrcode_path):
                baijiahao_logger.info(_msg("🧹", f"临时二维码文件已清理: {qrcode_path}"))
            if not result["success"]:
                baijiahao_logger.error(_msg("😢", f"登录失败: {result['message']}"))
            await context.close()
            await browser.close()
    return result


async def _is_locator_visible(locator) -> bool:
    try:
        if not await locator.count():
            return False
        return bool(await locator.is_visible())
    except Exception:
        return False


async def _has_baijiahao_login_marker(page: Page) -> bool:
    try:
        if await _is_locator_visible(page.get_by_text(BAIJIAHAO_LOGIN_TEXT).first):
            return True
    except Exception:
        pass
    try:
        if await _is_locator_visible(page.locator(QR_SELECTOR).first):
            return True
    except Exception:
        pass
    return False


async def _has_baijiahao_business_anchor(page: Page) -> bool:
    for selector in BAIJIAHAO_BUSINESS_ANCHOR_SELECTORS:
        try:
            if await _is_locator_visible(page.locator(selector).first):
                return True
        except Exception:
            continue
    return False


async def is_logged_in(context: BrowserContext) -> bool:
    """Return whether the Multilogin Profile is logged in to Baijiahao.

    Only ``context.new_page()`` / ``goto`` / ``close`` are used.  Explicit login
    URLs, the "注册/登录百家号" entry and the Baidu passport QR return ``False``;
    network failures, 5xx responses, timeouts, unexpected domains and an
    authenticated shell without any business anchor raise so the CLI exits 1.

    Worst-case budget: 20s navigation + 5s settle, inside the 15-30s spec.
    """
    page = await context.new_page()
    try:
        response = await page.goto(
            BAIJIAHAO_HOME_URL,
            wait_until="domcontentloaded",
            timeout=BAIJIAHAO_LOGIN_CHECK_TIMEOUT_MS,
        )
        status = getattr(response, "status", None)
        if isinstance(status, int) and status >= 500:
            raise RuntimeError(f"百家号登录状态检查失败：HTTP {status}")

        wait_for_timeout = getattr(page, "wait_for_timeout", None)
        if wait_for_timeout is not None:
            await wait_for_timeout(BAIJIAHAO_LOGIN_CHECK_SETTLE_MS)

        current_url = str(getattr(page, "url", "") or "")
        lowered_url = current_url.lower()
        if any(marker in lowered_url for marker in BAIJIAHAO_LOGIN_URL_MARKERS):
            return False
        if await _has_baijiahao_login_marker(page):
            return False
        if await _has_baijiahao_business_anchor(page):
            return True

        if "baijiahao.baidu.com" not in current_url:
            raise RuntimeError(
                "百家号登录状态检查失败：页面未停留在百家号后台"
                f"（url={current_url or '<empty>'}）"
            )
        raise RuntimeError(
            "百家号登录状态检查失败：未找到账号/发布控件等已登录标记"
            "（页面结构异常）"
        )
    finally:
        await page.close()


async def cookie_auth(account_file):
    """验证百家号 cookie 是否有效。访问后台首页，检测是否出现登录提示。"""
    account_file = _resolve_account_file(account_file)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**_build_launch_kwargs(headless=True))
        try:
            context = await browser.new_context(storage_state=account_file)
            page = await context.new_page()
            await page.goto(BAIJIAHAO_HOME_URL, timeout=60000, wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)

            if await page.get_by_text("注册/登录百家号").count():
                baijiahao_logger.info(_msg("🥹", "cookie 已失效"))
                return False
            else:
                baijiahao_logger.success(_msg("🥳", "cookie 有效"))
                return True
        except Exception as exc:
            baijiahao_logger.warning(_msg("😵", f"cookie 校验出错，按失效处理: {exc}"))
            return False
        finally:
            await browser.close()


async def baijiahao_setup(account_file, handle=False, return_detail=False, qrcode_callback=None, headless: bool = LOCAL_CHROME_HEADLESS):
    """统一入口：检查 cookie → 如无效且 handle=True 则触发扫码登录。"""
    account_file = _resolve_account_file(account_file)
    if not os.path.exists(account_file) or not await cookie_auth(account_file):
        if not handle:
            result = _build_login_result(False, "cookie_invalid", "cookie 文件不存在或已失效", account_file)
            return result if return_detail else False
        baijiahao_logger.info(_msg("🥹", "cookie 文件不存在或已失效，自动打开浏览器请扫码登录"))
        result = await baijiahao_cookie_gen(account_file, qrcode_callback=qrcode_callback, headless=headless)
        return result if return_detail else result["success"]

    result = _build_login_result(True, "cookie_valid", "cookie 有效", account_file)
    return result if return_detail else True


async def _require_unique(locator, what: str):
    """收窄到 ``count()==1``：多义直接硬错，不自动 ``.first``。"""
    count = await locator.count()
    if count != 1:
        raise ElementUnusableError(
            what=what,
            role="interactive",
            selector="",
            reason=f"ambiguous:{count}",
        )
    return locator


async def _wait_for_collection_options(options, timeout_ms: int) -> None:
    """有界等待候选渲染（固定 sleep 的替代）。

    候选缺席时只降级为「找不到合集 → 跳过」，不抛出、不中止发布。
    """
    try:
        await options.first.wait_for(state="visible", timeout=timeout_ms)
    except PWTimeoutError:
        pass


async def _find_exact_option(options, name: str):
    """按候选文本**全等**匹配合集名；命中不到返回 ``None``。

    同一合集可能被渲染成多个节点：只有在全等命中集合内部才取第一个
    （``.first`` 仅作降级），绝不对未过滤的候选集取 ``.first``。
    """
    wanted = " ".join(str(name).split())
    try:
        count = await options.count()
    except Exception:
        return None
    for index in range(count):
        option = options.nth(index)
        try:
            text = await option.inner_text()
        except Exception:
            continue
        if " ".join(str(text or "").split()) == wanted:
            return option
    return None


class BaiJiaHaoVideo(BaseVideoUploader):
    """百家号视频上传。

    流程：打开发布页 → 上传视频文件 → 填标题 → 等待上传/转码完成 → 等封面生成 → 点击发布。
    """
    publish_platform_label = "百家号"

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
        headless: bool = LOCAL_CHROME_HEADLESS,
    ):
        self.title = title
        self.file_path = file_path
        self.tags = tags or []
        self.account_file = (
            _resolve_account_file(account_file) if account_file is not None else None
        )
        self.publish_date = publish_date
        self.desc = desc or ""
        self.thumbnail_path = thumbnail_path
        self.collection_name = collection_name
        self.debug = debug
        self.headless = headless
        self.local_executable_path = LOCAL_CHROME_PATH
        self.max_title_length = 30

    def _humanizer(self, page: Page) -> Humanizer:
        """发布链路的唯一行为层实例：指针位置与随机流保持连续。"""
        cached = getattr(self, "_humanizer_instance", None)
        if cached is None or cached.page is not page:
            cached = Humanizer(page, sleep=self._humanize_pause)
            self._humanizer_instance = cached
        return cached

    async def _humanize_pause(self, seconds: float) -> None:
        """人类化停顿只吃剩余预算，耗尽收缩到 0，不自己抛超时。"""
        remaining = max(0.0, self.publish_budget.remaining_seconds())
        if seconds > remaining and not getattr(self, "_pause_warned", False):
            baijiahao_logger.warning(
                "人类化停顿被预算裁剪: {}s > {}s",
                round(seconds, 2),
                round(remaining, 2),
            )
            self._pause_warned = True
        await asyncio.sleep(min(seconds, remaining))

    async def validate_upload_args(self, *, check_cookie: bool = True):
        if check_cookie:
            if not self.account_file or not os.path.exists(self.account_file):
                raise RuntimeError(f"cookie文件不存在，请先完成百家号登录: {self.account_file}")
            if not await cookie_auth(self.account_file):
                raise RuntimeError(f"cookie文件已失效，请先完成百家号登录: {self.account_file}")
        if not self.title or not str(self.title).strip():
            raise ValueError("视频标题不能为空")
        if not self.thumbnail_path:
            raise ValueError("百家号视频发布必须提供横版封面图（--thumbnail）")
        self.file_path = str(self.validate_video_file(self.file_path))
        self.thumbnail_path = str(self.validate_image_file(self.thumbnail_path))

    async def upload(self, playwright: Playwright | None, *, session: BrowserSession | None = None) -> None:
        if session is not None:
            await self.validate_upload_args(check_cookie=False)
            await self.upload_in(session)
            return

        if playwright is None:
            raise ValueError("本地模式需要 Playwright 实例")

        baijiahao_logger.info(_msg("🧍", "先检查 cookie 和视频文件"))
        await self.validate_upload_args()
        baijiahao_logger.info(_msg("🥳", "上传前检查通过"))

        browser = await playwright.chromium.launch(
            headless=self.headless, **BAIJIAHAO_LAUNCH_KWARGS
        )
        context = await browser.new_context(
            storage_state=self.account_file,
            **BAIJIAHAO_CONTEXT_KWARGS,
        )

        try:
            await self.upload_in(
                BrowserSession(browser=browser, context=context, mode="local")
            )
            await context.storage_state(path=self.account_file)
            baijiahao_logger.success(_msg("🥳", "cookie 更新完毕"))
        finally:
            await context.close()
            await browser.close()

    async def upload_in(self, session: BrowserSession) -> None:
        self.start_publish_budget()
        multilogin = session.managed
        page = await session.context.new_page()
        # 一个 page 一个实例：之后的键入与点击都走同一套指针/随机流。
        humanizer = self._humanizer(page)
        await page.goto(
            BAIJIAHAO_PUBLISH_URL,
            timeout=self.publish_budget.clamp_ms(120000),
            wait_until="domcontentloaded",
        )
        if multilogin:
            _raise_if_login_required(page)
        baijiahao_logger.info(_msg("🏃", f"开始上传视频: {self.title}"))

        # 等待发布页加载
        await page.wait_for_timeout(3000)

        # 1) 上传视频文件
        file_input = page.locator('input[type="file"][accept*="video"], input[type="file"][accept*="mp4"]').first
        if not await file_input.count():
            file_input = page.locator("div[class^='video-main-container'] input[type='file']").first
        if not await file_input.count():
            file_input = page.locator('input[type="file"]').first
        await file_input.wait_for(state="attached", timeout=30000)
        await file_input.set_input_files(self.file_path)
        baijiahao_logger.info(_msg("🏃", f"已选择视频文件: {self.file_path}"))

        # 2) 等待进入表单页面（contenteditable 标题区出现即表单渲染完毕）
        title_editor = page.locator(TITLE_EDITOR_SELECTOR).first
        await title_editor.wait_for(
            state="visible", timeout=self.publish_budget.clamp_ms(180000)
        )
        await page.wait_for_timeout(1000)

        # 3) 填写标题
        await self._fill_title(page, humanizer)

        # 4) 等待视频上传完成
        await self._wait_upload_complete(page, multilogin=multilogin)

        # 5) 上传横版封面（必填）
        await self._upload_thumbnail(page, humanizer)

        # 6) 勾选「含AI生成内容」
        await self._check_ai_declaration(page, humanizer)

        # 7) 选择合集（如有配置）
        await self._apply_collection(page, humanizer)

        # 8) 点击发布
        await self._submit_publish(page, multilogin=multilogin)

    async def _fill_title(self, page: Page, humanizer: Humanizer) -> None:
        title_field = page.locator(TITLE_EDITOR_SELECTOR)
        await title_field.first.wait_for(state="visible", timeout=15000)
        title_field = await _require_unique(title_field, "视频标题")
        title = self.title
        # 百家号标题最少9字
        if len(title) <= 8:
            title += " 你不知道的"
        title = title[: self.max_title_length]
        # 标题是 contenteditable 且页面可能自动填了文件名：保留「点标题 →
        # Ctrl+A → Backspace」清空序列（只把键换成 humanizer.press），再逐字。
        await humanizer.click(title_field)
        await humanizer.press("Control+a")
        await humanizer.press("Backspace")
        await humanizer.type_text(title)
        baijiahao_logger.info(_msg("🏷️", f"标题已填写: {title}"))

    async def _wait_upload_complete(self, page: Page, timeout: int = 600, *, multilogin: bool = False) -> None:
        """等待视频真正上传完成。

        百度真实上传进度是一段百分比文字（9%…99%，上传完成后消失，本文件实测约 35s）。
        旧实现用 'div .cover-overlay:has-text("上传中")' 判断——经实测该元素恒不存在，
        导致选完文件立即误判"上传完毕"（约 4s）。大文件此时其实还在后台上传，随后点
        发布会被百度以"确保视频已经上传完毕"拒绝（产出 0 作品）。改为跟踪百分比进度：
        出现过进度且进度消失/达 100% 才算真正上传完成。
        """
        import re as _re
        budget = self.publish_budget
        timeout = budget.clamp_seconds(timeout)
        start = time.monotonic()
        seen_progress = False
        gone_count = 0
        while True:
            if time.monotonic() - start > timeout:
                budget.check_pre_click()
                baijiahao_logger.warning(_msg("⚠️", f"等待上传超时（>{timeout}s），继续后续步骤"))
                return
            if multilogin:
                _raise_if_login_required(page)

            body = ""
            try:
                body = await page.inner_text("body")
            except Exception:
                pass

            if "上传失败" in body:
                raise RuntimeError("视频上传失败")

            m = _re.search(r'(\d{1,3})\s*%', body)
            pct = int(m.group(1)) if m else None

            if pct is not None and pct < 100:
                seen_progress = True
                gone_count = 0
                baijiahao_logger.info(_msg("🏃", f"上传中 {pct}%"))
                await asyncio.sleep(2)
                continue

            if seen_progress:
                # 进度百分比已消失/到 100%，连续两次确认后判为上传完成
                gone_count += 1
                if gone_count >= 2:
                    baijiahao_logger.success(_msg("🥳", "视频上传完毕"))
                    return
                await asyncio.sleep(2)
                continue

            # 一直没出现过进度：小文件可能秒传完成；给 15s 窗口后放行
            if time.monotonic() - start > 15:
                baijiahao_logger.success(_msg("🥳", "视频上传完毕"))
                return
            await asyncio.sleep(2)

    async def _upload_thumbnail(self, page: Page, humanizer: Humanizer) -> None:
        """上传横版封面（必填）。

        流程：点击「选择封面」→ 弹窗中点「上传」按钮 → 设置图片文件 → 等待上传完成 → 确认。
        如果没有提供 thumbnail_path，等待系统自动生成封面即可。
        """
        if not self.thumbnail_path:
            # 没有自定义封面，等系统自动生成
            await self._wait_cover_ready(page)
            return

        try:
            # 1) 点击「选择封面」入口
            cover_entry = page.locator(COVER_ENTRY_SELECTOR).first
            if not await cover_entry.count():
                # 备选：通过文本定位
                cover_entry = page.get_by_text("选择封面", exact=True).first
            await humanizer.click(cover_entry)
            baijiahao_logger.info(_msg("🏃", "已点击「选择封面」"))
            await page.wait_for_timeout(2000)

            # 2) 封面图片 input 在弹窗里已经存在：优先直接写 input。禁止先点
            #    「上传」tab/按钮——那一下会真的拉起系统文件选择器，随后
            #    set_input_files 把文件塞进去，选择器会留在屏幕上（先例：小红书
            #    bbc5361，2026-11-12 TikTok 复现）。
            img_input = page.locator(COVER_IMAGE_INPUT_SELECTOR).first
            if await _cover_input_attached(img_input):
                await img_input.set_input_files(self.thumbnail_path)
            else:
                await self._upload_cover_via_chooser(page, humanizer)
            baijiahao_logger.info(_msg("🏃", f"已选择封面图片: {self.thumbnail_path}"))

            # 4) 等待并点击确认/完成按钮（如有裁剪弹窗）。
            #    裁剪弹窗渲染有延迟（图片上传+服务端处理），之前用固定 sleep(3s) 后
            #    一次性检查 confirm_btn，弹窗还没渲染出来时会被误判为"无需确认"而跳过点击，
            #    导致封面选择实际未提交，但日志仍打「封面已上传」成功——这是本次线上
            #    百家号视频没有封面、日志却显示成功的根因。改为轮询等待（不放大超时时长本身
            #    不算错误：裁剪弹窗本就是可选的，等不到也可能是流程本身没有该弹窗）。
            confirm_btn = page.locator(COVER_CONFIRM_SELECTOR).first
            confirmed = False
            try:
                await confirm_btn.wait_for(state="visible", timeout=15000)
                await humanizer.click(confirm_btn)
                await page.wait_for_timeout(1000)
                confirmed = True
            except PWTimeoutError:
                baijiahao_logger.debug("封面确认按钮未出现，可能本次流程无需裁剪确认")

            if confirmed:
                baijiahao_logger.success(_msg("🖼️", "封面已上传"))
            else:
                # 没有等到确认按钮：不确定封面是否真正生效，不再冒充成功，
                # 交给下方 except 分支同一套"等待系统自动封面"兜底逻辑核实/兜底。
                raise RuntimeError("封面确认按钮未出现，无法确认封面是否生效")
        except Exception as exc:
            baijiahao_logger.warning(_msg("⚠️", f"封面上传失败: {exc}，尝试等待系统自动封面"))
            # fallback：等系统自动生成
            await self._wait_cover_ready(page)

    async def _check_ai_declaration(self, page: Page, humanizer: Humanizer) -> None:
        """选择「含AI生成内容」创作声明。

        点创作声明**组件本体**（antd 装饰层会吃掉 placeholder input 的落点，
        所以不再 force 强点 input）→ 弹出 modal 弹窗 → 点选「含AI生成内容」
        → 点「确定」。
        """
        try:
            # 点击创作声明组件本体触发弹窗
            trigger = page.locator(AI_DECLARATION_TRIGGER_SELECTOR).first
            if not await trigger.count():
                trigger = page.locator(AI_DECLARATION_TRIGGER_FALLBACK).first
            await humanizer.click(trigger)
            await page.wait_for_timeout(3000)

            # 弹窗内点选「含AI生成内容」
            ai_option = page.locator(AI_DECLARATION_OPTION_SELECTOR).first
            if not await ai_option.count():
                ai_option = page.locator(AI_DECLARATION_OPTION_FALLBACK).first
            await ai_option.wait_for(state="visible", timeout=10000)
            await humanizer.click(ai_option)
            await page.wait_for_timeout(1000)

            # 点「确定」按钮关闭弹窗（弹窗可能在点选后仍存在）
            modal = page.locator(DECLARATION_MODAL_SELECTOR).first
            if await modal.count():
                confirm_btn = modal.locator(DECLARATION_CONFIRM_SELECTOR).first
                if await confirm_btn.count() and await confirm_btn.is_visible():
                    await humanizer.click(confirm_btn)
                    await page.wait_for_timeout(500)
                else:
                    # 确定按钮不可见：只用具名键收起弹窗，不做坐标强点。
                    await humanizer.press("Escape")
                    await page.wait_for_timeout(500)

            baijiahao_logger.success(_msg("🏷️", "已选择「含AI生成内容」"))
        except Exception as exc:
            # 如果失败，尝试关闭可能残留的弹窗
            try:
                await humanizer.press("Escape")
                await page.wait_for_timeout(500)
            except Exception:
                pass
            baijiahao_logger.warning(_msg("⚠️", f"选择 AI 声明失败: {exc}"))

    async def _apply_collection(self, page: Page, humanizer: Humanizer) -> None:
        """选择合集（cheetah-select 下拉搜索框）。

        placeholder: "选择同主题的合集，可获得更多播放机会"
        有 collection_name 时点开下拉 → 逐字输入搜索词 → 有界等待候选 →
        按合集名**全等**点选；候选里没有全等项时沿用「警告 + Escape」跳过，
        不中止发布。
        """
        if not self.collection_name:
            return
        try:
            # 定位合集下拉框（通过 placeholder 文案）
            select_box = page.locator(COLLECTION_SELECTOR).first
            if not await select_box.count():
                select_box = page.locator(COLLECTION_PLACEHOLDER_SELECTOR).locator('xpath=ancestor::div[contains(@class,"cheetah-select")]').first
            if not await select_box.count():
                baijiahao_logger.warning(_msg("⚠️", "未找到合集选择器，跳过"))
                return

            await humanizer.click(select_box)

            # 在搜索框中逐字输入合集名（触发搜索过滤）；搜索框每次都是空的，
            # 因此不清空，只聚焦后输入。
            search_input = select_box.locator(COLLECTION_SEARCH_INPUT_SELECTOR)
            if await search_input.count():
                search_input = await _require_unique(search_input, "合集搜索框")
                await humanizer.click(search_input)
                await humanizer.type_text(str(self.collection_name))

            # 有界等待候选项渲染：固定 sleep 的替代。
            options = page.locator(COLLECTION_OPTION_SELECTOR)
            await _wait_for_collection_options(
                options, self.publish_budget.clamp_ms(COLLECTION_OPTION_TIMEOUT_MS)
            )

            # 从下拉选项中按合集名全等选中目标合集。
            option = await _find_exact_option(options, str(self.collection_name))
            if option is not None:
                await humanizer.click(option)
                await page.wait_for_timeout(500)
                baijiahao_logger.success(_msg("🥳", f"已选择合集：{self.collection_name}"))
            else:
                baijiahao_logger.warning(_msg("⚠️", f"账号中无「{self.collection_name}」合集，跳过"))
                await humanizer.press("Escape")
        except Exception as exc:
            baijiahao_logger.warning(_msg("⚠️", f"选择合集失败，跳过: {exc}"))

    async def _upload_cover_via_chooser(
        self, page: Page, humanizer: Humanizer
    ) -> None:
        """兜底：只有 input 缺失时才点「上传」tab，点击必须被 chooser 消费。

        chooser 事件没到也不能裸点第二次：点击可能已经把 input 渲染出来，
        这里改为重新解析封面专用 input 再直接写。绝不回退到页面级的通用
        ``input[type=file]``——那会绑到页面自己的视频输入框。
        """
        upload_btn = page.locator(COVER_UPLOAD_BUTTON_SELECTOR).first
        if not await upload_btn.count():
            upload_btn = page.get_by_text("上传", exact=True).first
        chooser = None
        try:
            async with page.expect_file_chooser(
                timeout=COVER_CHOOSER_TIMEOUT_MS
            ) as chooser_info:
                await upload_btn.click(timeout=8000)  # native-click: file；封面弹窗「上传」tab 只能由原生点击唤起文件选择器，且必须被 expect_file_chooser 消费
            chooser = await chooser_info.value
        except PWTimeoutError:
            # 只有「选择器事件没到」才降级；人类化/原生点击错误必须上抛
            # （spec §4.1-7：人类化失败不得自动降级）。
            chooser = None
        if chooser is not None:
            await chooser.set_files(self.thumbnail_path)
            return
        await page.wait_for_timeout(1500)
        img_input = page.locator(COVER_IMAGE_INPUT_SELECTOR).first
        if not await img_input.count():
            raise RuntimeError(
                "封面图片 input 未出现：点击「上传」后既没有文件选择器，也没有 "
                f"{COVER_IMAGE_INPUT_SELECTOR}；不绑定页面级 input[type=file]，"
                "避免把视频输入框当成封面"
            )
        await img_input.set_input_files(self.thumbnail_path)

    async def _wait_cover_ready(self, page: Page, timeout: int = 120) -> None:
        """等待百家号自动生成封面图。"""
        budget = self.publish_budget
        timeout = budget.clamp_seconds(timeout)
        start = time.monotonic()
        while True:
            if time.monotonic() - start > timeout:
                budget.check_pre_click()
                baijiahao_logger.warning(_msg("⚠️", "等待封面生成超时，继续发布"))
                return
            if await page.locator("div.cheetah-spin-container img").count():
                baijiahao_logger.info(_msg("🖼️", "封面已生成"))
                return
            baijiahao_logger.info(_msg("🏃", "等待封面生成..."))
            await asyncio.sleep(3)

    async def _submit_publish(
        self,
        page: Page,
        *,
        multilogin: bool = False,
        humanizer: Humanizer | None = None,
    ) -> None:
        """点击发布按钮并确认成功。

        遮挡只走「清浮层」（Escape 收残留 modal），绝不给发布点击加 force。
        """
        budget = self.publish_budget
        humanizer = humanizer or self._humanizer(page)
        # 确保没有残留弹窗遮挡
        modal = page.locator(DECLARATION_MODAL_SELECTOR).first
        if await modal.count():
            await humanizer.press("Escape")
            await page.wait_for_timeout(1000)

        # 百家号发布按钮有 data-testid="publish-btn"
        publish_btn = page.locator(PUBLISH_BUTTON_SELECTOR).first
        if not await publish_btn.count():
            publish_btn = page.locator(PUBLISH_BUTTON_TEXT_SELECTOR).first
        if not await publish_btn.count():
            publish_btn = page.locator(PUBLISH_BUTTON_CONTAINS_SELECTOR).last
        await publish_btn.wait_for(
            state="visible", timeout=budget.clamp_ms(15000)
        )
        await budget.wait_until_allowed(
            getattr(self, "publish_not_before", None),
            logger=baijiahao_logger,
            label="百家号发布",
        )
        budget.check_pre_click()
        await humanizer.before_submit()
        try:
            await humanizer.click(publish_btn)
        except Exception as exc:
            if maybe_dispatched(exc):
                # 发布点击可能已经发出：按结果未知上抛，禁止再次派发。
                raise budget.timeout_error(True) from exc
            raise
        publish_clicked = True
        baijiahao_logger.info(_msg("🏃", "已点击发布按钮"))

        # 发布后共享整条流程的 15 分钟 deadline。
        while budget.remaining_seconds() > 0:
            if multilogin:
                _raise_if_login_required(page, publish_attempted=publish_clicked)
            url = page.url
            # 发布成功跳转
            if BAIJIAHAO_SUCCESS_URL_PREFIX in url or "/rc/content" in url or "/rc/home" in url:
                baijiahao_logger.success(_msg("🥳", "视频发布成功"))
                return
            # 检查是否出现百度安全验证
            if await page.locator('text="百度安全验证"').count():
                # 发布点击已经发出：验证码页面等于结果未知，不能落回「未发布」。
                if multilogin:
                    raise LoginRequiredError(
                        "百家号上传过程中需要人工完成百度安全验证："
                        "请在 Multilogin 应用中登录 Profile 后重试。",
                        publish_attempted=publish_clicked,
                    )
                raise budget.timeout_error(publish_clicked)
            # 检查是否有错误提示阻止发布
            error_toast = page.locator('.cheetah-message-error, .cheetah-message-warning').first
            if await error_toast.count() and await error_toast.is_visible():
                err_text = await error_toast.inner_text()
                baijiahao_logger.warning(_msg("⚠️", f"发布提示: {err_text}"))
            await page.wait_for_timeout(1000)

        # 超时后再检查一次
        if BAIJIAHAO_SUCCESS_URL_PREFIX in page.url or "/rc/content" in page.url:
            baijiahao_logger.success(_msg("🥳", "视频发布成功"))
        else:
            raise budget.timeout_error(publish_clicked)

    async def main(self, *, session: BrowserSession | None = None):
        if session is not None:
            await self.upload(None, session=session)
            return
        async with async_playwright() as playwright:
            await self.upload(playwright)
