"""通过 Meta Business Suite 发布 Facebook Page 内容。"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from loguru import logger
from patchright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
    expect,
    TimeoutError as BrowserTimeoutError,
)

from uploader.base_video import BaseVideoUploader
from utils.browser_session import BrowserSession
from utils.browser_time import page_wall_clock
from utils.dom import ElementMissingError, ElementUnusableError
from utils.errors import LoginRequiredError
from utils.humanize import Humanizer


META_BUSINESS_URL = "https://business.facebook.com/latest/composer/"
META_PLATFORMS = {"facebook-page"}
# 未配置环境变量或 --proxy 时使用系统直连。
FACEBOOK_PAGE_PROXY = os.environ.get("SAU_FACEBOOK_PAGE_PROXY")

META_BUSINESS_LOGIN_CHECK_TIMEOUT_MS = 25_000
META_BUSINESS_LOGIN_CHECK_SETTLE_MS = 2_500

# Golden local-mode browser options.  Multilogin mode reuses the same values
# only so the call sites stay symmetric; ``browser_session`` ignores them.
FACEBOOK_PAGE_LAUNCH_KWARGS: dict[str, object] = {"channel": "chrome"}
FACEBOOK_PAGE_CONTEXT_KWARGS: dict[str, object] = {}
FACEBOOK_PAGE_INIT_SCRIPT = False

_META_LOGIN_URL_MARKERS = (
    "/login",
    "checkpoint",
    "two_step_verification",
    "/authentication/",
)

# 收窄后的目标必须唯一：多义（count > 1）立即硬错，绝不静默取 .first。
_UNIQUE_TIMEOUT_MS = 30_000
_UNIQUE_POLL_SECONDS = 0.1

# 页面只保留中/英/日三种实测语言；这些文案只用于把同角色的多个按钮收窄到
# 唯一一个，区域已按 data-surface 限定，匹配不到或多于一个都硬错。
_REEL_NEXT_NAMES = re.compile(r"^(Next|下一步|次へ|Continue|继续)$", re.IGNORECASE)
_STORY_CONFIRM_NAMES = re.compile(
    r"^(Publish|Done|OK|Share|发布|完成|確定|分享|公開|投稿)$", re.IGNORECASE
)
_SCHEDULE_MODE_NAMES = re.compile(r"^(Schedule|定时|預約|予約|スケジュール)$", re.IGNORECASE)
_CALENDAR_PREV_NAMES = re.compile(
    r"(Previous month|上个月|上一月|前月|前の月)", re.IGNORECASE
)
_CALENDAR_NEXT_NAMES = re.compile(
    r"(Next month|下个月|下一月|翌月|次の月|来月)", re.IGNORECASE
)
_POST_PUBLISH_NAMES = re.compile(
    r"^(Publish|Post|Share|发布|发帖|分享|公開|投稿)$", re.IGNORECASE
)
_COMPLETION_CLOSE_NAMES = re.compile(
    r"^(Done|完成|完了|確定)$", re.IGNORECASE
)


async def _unique(locator, what: str, *, timeout_ms: int = _UNIQUE_TIMEOUT_MS):
    """把 ``locator`` 收窄到唯一匹配；多义硬错 ``ambiguous:N``，不取 .first。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_ms / 1000
    while True:
        count = await locator.count()
        if count > 1:
            raise ElementUnusableError(
                what,
                role="interactive",
                reason=f"ambiguous:{count}",
                publish_clicked=False,
            )
        if count == 1:
            return locator
        if loop.time() >= deadline:
            raise ElementMissingError(what, role="interactive", publish_clicked=False)
        await asyncio.sleep(_UNIQUE_POLL_SECONDS)



def facebook_page_launch_kwargs(proxy: str | None = None) -> dict[str, object]:
    """Exact local launch options; ``proxy`` is dropped in Multilogin mode."""
    return {**FACEBOOK_PAGE_LAUNCH_KWARGS, "proxy": _proxy_options(proxy)}


def _raise_if_login_required(page: Page) -> None:
    """Map a mid-upload login/captcha/2FA redirect to ``LoginRequiredError``."""
    current_url = str(getattr(page, "url", "") or "").lower()
    if any(marker in current_url for marker in _META_LOGIN_URL_MARKERS):
        raise LoginRequiredError(
            "Facebook Page 上传过程中需要重新登录（登录页/验证码/二次验证）："
            "请在 Multilogin 应用中登录 Profile 后重试。"
        )


def meta_account_file(platform: str, account_name: str) -> Path:
    if platform not in META_PLATFORMS:
        raise ValueError(f"不支持的 Meta Business 平台: {platform}")
    return Path("cookies") / f"{platform}_{account_name}.json"


def _proxy_options(proxy: str | None) -> dict[str, str] | None:
    address = (FACEBOOK_PAGE_PROXY if proxy is None else proxy) or ""
    address = address.strip()
    return {"server": address} if address else None


async def _open_business_page(
    playwright: Playwright,
    account_file: Path,
    *,
    proxy: str | None,
    headless: bool,
):
    browser = await playwright.chromium.launch(
        headless=headless, **facebook_page_launch_kwargs(proxy)
    )
    try:
        context = await browser.new_context(storage_state=str(account_file))
        page = await context.new_page()
        page.set_default_timeout(30_000)
        await page.goto(META_BUSINESS_URL, wait_until="domcontentloaded", timeout=120_000)
        await page.locator("body").wait_for(state="visible", timeout=30_000)
        return browser, context, page
    except Exception:
        await browser.close()
        raise


async def dismiss_guidance_cards(page: Page) -> None:
    """关闭带明确 GeoGuidanceCard 业务标识的说明卡，不处理未知弹窗。"""
    # 中英日卡片中关闭按钮无 aria-label，了解更多带 aria-label；不用 Close/关闭/閉じる 文案。
    close_buttons = page.locator('[data-surface$="lib:GeoGuidanceCard"] [role="button"]:not([aria-label]):visible')
    # data-surface 可能同时出现在包裹节点和日志节点上；直接选其后代按钮，由 CSS 去重。
    for close in await close_buttons.all():
        await close.click()  # native-click: chrome；关闭 Business Suite 引导说明卡，非内容交互
        await expect(close).to_be_hidden()


async def _is_business_logged_out(page: Page) -> bool:
    url = page.url.lower()
    if "/login" in url or "checkpoint" in url or "two_step_verification" in url:
        return True
    if await page.locator('input[name="email"]').count() and await page.locator('input[name="email"]').first.is_visible():
        return True
    # 导航 href 与页面业务 surface 均独立于显示语言；空白页不能作为已登录证据。
    navigation = page.locator('a[href*="/latest/home"]')
    return not await navigation.filter(visible=True).count()



async def is_logged_in(context: BrowserContext) -> bool:
    """Return whether the Multilogin Profile is logged in to Meta Business Suite.

    Only ``context.new_page()`` / ``goto`` / ``close`` are used.  Explicit login,
    checkpoint and 2FA pages return ``False``; network failures, 5xx responses,
    timeouts and unexpected redirects raise.

    Worst-case budget: 25s navigation + 2.5s settle, inside the 15-30s spec.
    """
    page = await context.new_page()
    try:
        response = await page.goto(
            META_BUSINESS_URL,
            wait_until="domcontentloaded",
            timeout=META_BUSINESS_LOGIN_CHECK_TIMEOUT_MS,
        )
        status = getattr(response, "status", None)
        if isinstance(status, int) and status >= 500:
            raise RuntimeError(
                f"Facebook Page 登录状态检查失败：HTTP {status}"
            )

        current_url = str(getattr(page, "url", "") or "")
        if "business.facebook.com" not in current_url.lower():
            raise RuntimeError(
                "Facebook Page 登录状态检查失败：页面未停留在 business.facebook.com"
                f"（url={current_url or '<empty>'}）"
            )
        if any(marker in current_url.lower() for marker in _META_LOGIN_URL_MARKERS):
            return False

        wait_for_timeout = getattr(page, "wait_for_timeout", None)
        if wait_for_timeout is not None:
            await wait_for_timeout(META_BUSINESS_LOGIN_CHECK_SETTLE_MS)
        return not await _is_business_logged_out(page)
    finally:
        await page.close()


async def meta_cookie_auth(account_file: str | Path, *, proxy: str | None = None) -> bool:
    account_file = Path(account_file)
    if not account_file.is_file():
        return False
    async with async_playwright() as playwright:
        browser, context, page = await _open_business_page(
            playwright, account_file, proxy=proxy, headless=True
        )
        try:
            return not await _is_business_logged_out(page)
        finally:
            await browser.close()


async def meta_setup(
    account_file: str | Path,
    *,
    handle: bool = False,
    proxy: str | None = None,
    headless: bool = False,
    return_detail: bool = False,
):
    account_file = Path(account_file)
    account_file.parent.mkdir(parents=True, exist_ok=True)
    if await meta_cookie_auth(account_file, proxy=proxy):
        result = {"success": True, "status": "cookie_valid", "account_file": str(account_file)}
        return result if return_detail else True
    if not handle:
        result = {"success": False, "status": "cookie_invalid", "account_file": str(account_file)}
        return result if return_detail else False

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=headless, **facebook_page_launch_kwargs(proxy)
        )
        try:
            # 已有 Facebook 登录态可作为 Business Suite 的初始 Cookie，避免重复登录。
            source = account_file
            context = await browser.new_context(storage_state=str(source) if source.is_file() else None)
            page = await context.new_page()
            page.set_default_timeout(30_000)
            await page.goto(META_BUSINESS_URL, wait_until="domcontentloaded", timeout=120_000)
            deadline = asyncio.get_running_loop().time() + 600
            while asyncio.get_running_loop().time() < deadline:
                if not await _is_business_logged_out(page):
                    await context.storage_state(path=str(account_file))
                    result = {
                        "success": True,
                        "status": "logged_in",
                        "account_file": str(account_file),
                        "current_url": page.url,
                    }
                    return result if return_detail else True
                await page.wait_for_timeout(1000)
            result = {"success": False, "status": "timeout", "account_file": str(account_file)}
            return result if return_detail else False
        finally:
            await browser.close()


class MetaBusinessUploader(BaseVideoUploader):
    """Business Suite 中的 Facebook Page 视频和图文发布器。"""

    publish_platform_label = "Facebook Page"

    def __init__(
        self,
        platform: str,
        account_file: str | Path,
        *,
        title: str,
        description: str = "",
        tags: list[str] | None = None,
        video_file: str | Path | None = None,
        image_files: list[str | Path] | None = None,
        schedule: datetime | int = 0,
        page_name: str | None = None,
        proxy: str | None = None,
        headless: bool = False,
        result_file: str | Path | None = None,
    ):
        if platform not in META_PLATFORMS:
            raise ValueError(f"不支持的 Meta Business 平台: {platform}")
        if not title.strip():
            raise ValueError("标题不能为空")
        if bool(video_file) == bool(image_files):
            raise ValueError("必须且只能传入视频或图片文件")
        self.platform = platform
        self.account_file = Path(account_file) if account_file is not None else None
        self.title = title.strip()
        self.description = description.strip()
        self.tags = [tag.strip().lstrip("#") for tag in (tags or []) if tag.strip().lstrip("#")]
        self.video_file = Path(video_file) if video_file else None
        self.image_files = [Path(item) for item in (image_files or [])]
        self.schedule = self.validate_publish_date(schedule)
        self.page_name = page_name.strip() if page_name else None
        self.proxy = proxy
        self.headless = headless
        self.result_file = Path(result_file) if result_file else Path('.local/meta-results') / f'{uuid4().hex}.json'
        self.result = {"platform": platform, "title": self.title, "status": "not_submitted"}

    def _caption(self) -> str:
        parts = [self.title, self.description] if self.description else [self.title]
        if self.tags:
            parts.append(" ".join(f"#{tag}" for tag in self.tags))
        return "\n\n".join(parts)

    def _humanizer(self, page: Page) -> Humanizer:
        """发布链路的唯一行为层实例：指针位置与随机流保持连续。"""
        cached = getattr(self, "_humanizer_instance", None)
        if cached is None or cached.page is not page:
            cached = Humanizer(page, sleep=self._humanize_pause)
            self._humanizer_instance = cached
        return cached

    async def _humanize_pause(self, seconds: float) -> None:
        """人类化停顿只吃剩余预算，耗尽时收缩到 0，不自己抛超时。"""
        remaining = max(0.0, self.publish_budget.remaining_seconds())
        if seconds > remaining and not getattr(self, "_pause_warned", False):
            logger.warning(
                "人类化停顿被预算裁剪: {}s > {}s",
                round(seconds, 2),
                round(remaining, 2),
            )
            self._pause_warned = True
        await asyncio.sleep(min(seconds, remaining))

    async def _select_publish_location(self, page: Page) -> None:
        # 发布位置的可访问名称区别于正文和 CTA 的 combobox，不依赖全页顺序。
        # 发布主体选择器带 Facebook 品牌徽标；CTA 下拉框和正文均没有该徽标。
        # 中英文实际页面均保留此品牌 alt，避免依赖“发布位置/Post to”的翻译。
        humanizer = self._humanizer(page)
        combo = page.locator('[data-surface$="bizweb_create_post:left_panel"] [role="combobox"][aria-haspopup="listbox"]').filter(has=page.locator('img[alt="Facebook"]'))
        await combo.wait_for(state="visible")
        if self.page_name and self.page_name not in await combo.inner_text():
            await humanizer.click(await _unique(combo, "发布主体下拉"))
            option = await _unique(
                page.get_by_role("option", name=self.page_name, exact=True),
                "发布主体选项",
            )
            await humanizer.click(option)
        if self.page_name:
            await expect(combo).to_contain_text(self.page_name)
        else:
            self.page_name = (await combo.inner_text()).replace('\u200b', '').strip()
        assets = parse_qs(urlparse(page.url).query).get('asset_id', [])
        if len(assets) != 1 or not assets[0].isdigit():
            raise RuntimeError("无法核实当前 Page asset_id，未提交")
        self.result.update(page_id=assets[0], page_name=self.page_name, expected_text=self.title)

    async def _upload_files(self, page: Page) -> None:
        # 页面可能保留隐藏的响应式布局；按钮语义及 visible 限定当前实际上传入口。
        # 空媒体区的业务顺序为本地影音上传、可选 AI 生成；中英文实测分别有 1/2 个入口。
        # 仅接受空区这两种结构，上传后生成的编辑/移除动作不能混入；不按翻译或图标路径匹配。
        media = page.locator('[data-surface$="lib:bizweb_create_post:media"]')
        await expect(media.locator('img')).to_have_count(0)
        entries = media.get_by_role('button')
        if await entries.count() not in (1, 2):
            raise RuntimeError('空媒体区结构未识别，未上传')
        trigger = entries.nth(0)
        files = [str(self.video_file)] if self.video_file else [str(path) for path in self.image_files]
        async with page.expect_file_chooser() as chooser_info:
            await trigger.click()  # native-click: file；原生文件选择器必须与 set_files 配对，坐标点击无法携带文件
        await (await chooser_info.value).set_files(files)
        # 视频在新版 Business Suite 会进入“创建 Reels”向导，不渲染 video 标签；
        # 图片则留在原 composer。两种状态都必须等到文件名或向导业务标题出现。
        if self.video_file:
            await page.get_by_text(self.video_file.name, exact=True).wait_for(state="visible", timeout=self.publish_budget.clamp_ms(180_000))
            # 新版 Reel 向导有独立业务 surface；不依赖 Create reel/创建 Reels 标题。
            await page.locator('[data-surface$="lib:bizweb_create_reel"]').wait_for()
            await dismiss_guidance_cards(page)
            await page.get_by_text('100%', exact=True).wait_for(state='visible', timeout=self.publish_budget.clamp_ms(180000))
        else:
            # 上传后媒体区生成服务端预览及像素尺寸；不以中文“移除照片”或正文框代表上传完成。
            await expect(media.locator('img')).to_have_count(len(files), timeout=self.publish_budget.clamp_ms(180000))
            await expect(media.get_by_text(re.compile(r"^\d+ x \d+$")).filter(visible=True)).to_have_count(len(files), timeout=self.publish_budget.clamp_ms(180000))

    async def _fill_caption(self, page: Page) -> None:
        humanizer = self._humanizer(page)
        # Reel 标题为 left_panel 中唯一普通 text input；关键词输入另有 combobox 角色。
        reels_title = page.locator('[data-surface$="bizweb_create_reel:left_panel"] input[type="text"]:not([role]):visible')
        separate_title = bool(self.video_file) and bool(await reels_title.count()) and await reels_title.is_visible()
        if separate_title:
            title_input = await _unique(reels_title, "Reel 独立标题")
            await title_input.focus()
            await humanizer.press("ControlOrMeta+A")
            await humanizer.press("Delete")
            # 单行 input 内换行会变成 Enter；标题字段按单行归一化。
            await humanizer.type_text(re.sub(r"[\r\n\t]+", " ", self.title).strip())
        # 实测同名隐藏 textbox 与可见 combobox 并存；只匹配当前向导可见正文，防止误填旧布局。
        # 当前可见 contenteditable 是正文；隐藏 textbox 属于旧布局，角色会随图文/Reel 改变。
        editor = await _unique(page.locator('[contenteditable="true"]:visible'), "正文")
        await editor.wait_for(state="visible", timeout=30_000)
        caption = self.description if separate_title else self._caption()
        if self.tags and separate_title:
            caption = f"{caption}\n\n{' '.join(f'#{tag}' for tag in self.tags)}" if caption else " ".join(f"#{tag}" for tag in self.tags)
        if not caption and not self.video_file:
            caption = self._caption()
        # 单行标题不得含换行；正文保留平台既有 \n 分段，先归一化 CRLF。
        caption = str(caption).replace("\r\n", "\n").replace("\r", "\n")
        await editor.focus()
        await humanizer.press("ControlOrMeta+A")
        await humanizer.press("Delete")
        await humanizer.type_text(caption)
        if (await editor.inner_text()).strip() != caption:
            raise RuntimeError("Business Suite 正文未读回预期内容")

    async def _advance_reels(self, page: Page) -> None:
        if not self.video_file:
            return
        humanizer = self._humanizer(page)
        root = page.locator('[data-surface$="lib:bizweb_create_reel"]')
        # 向导的三个步骤有 aria-labelledby，当前步骤有 aria-current；缩略图切换没有。
        # 这里只读状态、不点击，序号用于确认“第 i 步正在显示”。
        steps = root.locator('[role="button"][aria-labelledby]:not([aria-haspopup])')
        await expect(steps).to_have_count(3)
        # 两次下一步都来自 footer，不与缩略图的上/下一张混选；带 aria-label 的是反馈入口。
        # 按可访问名称收窄到唯一按钮，布局改版时硬错而不是点错序号。
        footer = page.locator('[data-surface$="bizweb_create_reel:footer"]')
        for index in (0, 1):
            await expect(steps.nth(index)).to_have_attribute('aria-current', 'step')
            next_button = await _unique(
                footer.get_by_role('button', name=_REEL_NEXT_NAMES), "Reel 下一步"
            )
            await expect(next_button).to_be_enabled(timeout=self.publish_budget.clamp_ms(180000))
            await humanizer.click(next_button)
            await expect(steps.nth(index + 1)).to_have_attribute('aria-current', 'step')
        # 快拍开关与当前 Page 的 Facebook 徽标属于同一单开关业务组；其余开关没有品牌图片。
        story = page.locator('[data-surface$="bizweb_create_reel:left_panel"] input[role="switch"]').locator(
            'xpath=self::input[ancestor::div[.//img[@alt="Facebook"] and count(.//input[@role="switch"])=1]]')
        story = await _unique(story, "同时发快拍开关")
        # 先读 checked 再决定是否点：开关默认可能已开启，盲目点击会把它关掉。
        if await story.is_checked():
            await humanizer.click(story)
            # Once 是平台真实选项值，只关闭本条快拍分享；Always 会改变后续默认设置。
            dialog = page.get_by_role('dialog').filter(has=page.locator('input[type="radio"][value="Once"]'))
            await expect(dialog).to_have_count(1)
            await dialog.locator('input[value="Once"]').check()
            # 弹窗内按可访问名称收窄主动作；关闭/取消与确认不再按序号取。
            confirm = await _unique(
                dialog.get_by_role('button', name=_STORY_CONFIRM_NAMES), "快拍弹窗主动作"
            )
            await humanizer.click(confirm)
            await expect(dialog).to_have_count(0)
            await expect(story).not_to_be_checked()

    async def _fill_schedule(self, page: Page) -> None:
        if not self.schedule:
            return
        humanizer = self._humanizer(page)
        # 表单按浏览器时区解释时间；先读取页面时区再换算墙上时间。
        schedule = await page_wall_clock(page, self.schedule)
        if self.video_file:
            region = page.locator('[data-surface$="bizweb_create_reel:left_panel"]')
            # 分享阶段的三种发布模式是立即、定时、草稿；其 aria-pressed 表示模式，非提交。
            modes = region.locator('[role="button"][aria-pressed]').locator('xpath=self::*[not(ancestor::*[@role="grid"])]')
            await expect(modes).to_have_count(3)
            # 按文案收窄到「定时」模式；aria-pressed 顺序会漂，不能按序号点。
            schedule_mode = await _unique(
                region.get_by_role('button', name=_SCHEDULE_MODE_NAMES), "定时发布模式"
            )
            await humanizer.click(schedule_mode)
            await expect(schedule_mode).to_have_attribute('aria-pressed', 'true')
        else:
            region = page.locator('[data-surface$="lib:bizweb_create_post:publishing_options"]')
            await region.locator('input[role="switch"]').check()
        # 日期是定时区唯一有 placeholder 的普通 input；小时/分钟靠语义数值范围区分。
        date_input = await _unique(region.locator('input[placeholder]:not([role])'), "定时日期")
        await humanizer.click(date_input)
        grid = await _unique(region.locator('[role="grid"][aria-labelledby]'), "定时日历")
        # 日历 aria-labelledby 实测含月、年，前缀 js_* 随会话变化，只解析其日期后缀。
        month_id = await grid.get_attribute('aria-labelledby')
        match = re.search(r'-(\d{1,2})-(\d{4})$', month_id or '')
        if not match:
            raise RuntimeError('无法读取日历的月份/年份，未提交')
        month, year = map(int, match.groups())
        month_delta = (schedule.year - year) * 12 + schedule.month - month
        if abs(month_delta) > 12:
            raise ValueError('定时日期超出已验证日历范围')
        # 日历非 grid 内的两个按钮分别为上一月/下一月；日按钮属于 gridcell，排除它们。
        calendar = grid.locator('xpath=ancestor::div[.//*[@role="button"][@aria-busy]][1]')
        await expect(calendar.locator('[role="button"][aria-busy]')).to_have_count(2)
        if month_delta:
            # 上/下一月按可访问名称收窄；方向由当前月与请求月的差值决定。
            navigation = await _unique(
                calendar.get_by_role(
                    'button',
                    name=_CALENDAR_NEXT_NAMES if month_delta > 0 else _CALENDAR_PREV_NAMES,
                ),
                "日历月份切换",
            )
            for _ in range(abs(month_delta)):
                await humanizer.click(navigation)
        await expect(grid).to_have_attribute('aria-labelledby', re.compile(fr'-{schedule.month}-{schedule.year}$'))
        # 已核对日历年月后按日期数字选择，避免依赖 aria-label 的星期/月名翻译。
        day = await _unique(
            grid.get_by_role('button').filter(has_text=re.compile(fr'^{schedule.day}$')),
            "定时日期-日",
        )
        if await day.get_attribute('aria-disabled') == 'true':
            raise ValueError('平台日历不允许选定日期，未提交')
        await humanizer.click(day)
        hour = await _unique(
            region.locator('[role="spinbutton"][aria-valuemax="23"], [role="spinbutton"][aria-valuemax="12"]'),
            "定时-小时",
        )
        minute = await _unique(
            region.locator('[role="spinbutton"][aria-valuemax="59"]'), "定时-分钟"
        )
        twelve_hour = await hour.get_attribute('aria-valuemax') == '12'
        value_hour = (schedule.hour % 12 or 12) if twelve_hour else schedule.hour
        for control, value in ((hour, value_hour), (minute, schedule.minute)):
            # 聚焦点击人类化；打开后的数字键仍走 locator.press，保持逐键覆盖预填值。
            await humanizer.click(control)
            for digit in f'{value:02d}':
                await control.press(digit)
            await control.press('Tab')
            await expect(control).to_have_attribute('aria-valuenow', str(value))
        if twelve_hour:
            # AM/PM 的真实数值是 0/1；按键切换后读回，拒绝只填小时造成 12 小时偏差。
            period = await _unique(
                region.locator('[role="spinbutton"][aria-valuemax="1"]'), "定时-AM/PM"
            )
            target = str(int(schedule.hour >= 12))
            if await period.get_attribute('aria-valuenow') != target:
                await period.press('ArrowUp')
            await expect(period).to_have_attribute('aria-valuenow', target)
        # 日期控件在中英日页面实测读回均包含年月日数字；允许分隔符本地化，不猜月份名称。
        parts = [int(part) for part in re.findall(r'\d+', await date_input.input_value())]
        if parts != [schedule.year, schedule.month, schedule.day]:
            raise RuntimeError(f'日期未读回请求值：{await date_input.input_value()}')

    async def _publish(self, page: Page) -> None:
        # 图文底栏的业务动作固定为取消、存草稿、最终提交；限定 footer 并严格核对三项，
        # 只在已观察的布局中采用此业务顺序，布局变化时停止，禁止用全页同名按钮或猜测翻译。
        humanizer = self._humanizer(page)
        if not self.video_file:
            footer = page.locator('[data-surface$="lib:bizweb_create_post:footer"]')
            await expect(footer.locator('[role="button"]')).to_have_count(3)
        else:
            # 分享阶段仍为返回 + 最终主动作，不能选择顶部 Share 步骤导航。
            footer = page.locator('[data-surface$="bizweb_create_reel:footer"]')
            await expect(footer.locator('[role="button"]:not([aria-label])')).to_have_count(2)
        # 最终提交按可访问名称收窄到唯一按钮，不再用 footer 内的序号。
        button = await _unique(
            footer.get_by_role('button', name=_POST_PUBLISH_NAMES), "发布按钮"
        )
        budget = self.publish_budget
        await expect(button).to_be_enabled(timeout=budget.clamp_ms(30000))
        await budget.wait_until_allowed(
            getattr(self, "publish_not_before", None),
            logger=logger,
            label="Facebook Page 发布",
        )
        budget.check_pre_click()
        self.result['status'] = 'submission_unknown'
        self.result_file.parent.mkdir(parents=True, exist_ok=True)
        self.result_file.write_text(json.dumps(self.result, ensure_ascii=False, indent=2), encoding='utf-8')
        # 只捕获本次点击触发的创建作品响应；上传素材 ID 和广告建议中的 story ID 都不能代替内容编号。
        publish_clicked = False
        try:
            async with page.expect_response(lambda response: '/api/graphql' in response.url and
                    parse_qs(response.request.post_data or '').get('fb_api_req_friendly_name') == ['BusinessComposerStoryCreationMutation'],
                    timeout=budget.clamp_ms(90000)) as response_info:
                await humanizer.before_submit()
                await humanizer.click(button)
                publish_clicked = True
            response = await response_info.value
        except BrowserTimeoutError:
            raise budget.timeout_error(publish_clicked) from None
        payload = await response.json()
        if payload.get('errors'):
            raise RuntimeError('平台创建作品响应包含错误；请查原记录，勿重复提交')
        creation = payload.get('data', {}).get('xfamily_content_create', {})
        if any(creation.get('errors', {}).values()):
            raise RuntimeError('平台返回作品创建错误；请查原记录，勿重复提交')
        items = creation.get('items')
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list) or len(items) != 1:
            raise RuntimeError('已提交但未取得唯一内容编号；结果待查询')
        # 实测 Reels 响应的 pending_publish_content_id 为空，需在成功确认后查原作品详情。
        pending_id = items[0].get('pending_publish_content_id')
        if pending_id:
            self.result['content_id'] = str(pending_id)
        self.result_file.write_text(json.dumps(self.result, ensure_ascii=False, indent=2), encoding='utf-8')
        if self.video_file:
            # 创建响应后页面仍执行后续发布步骤，不能立即导航走；实测完成框带本次标题、
            # 作品预览及关闭/完成两个动作。标题是本次业务参数，非某种语言的成功文案。
            completion = page.locator('[role="dialog"][aria-labelledby][tabindex="-1"]').filter(has_text=self.title)
            try:
                await expect(completion).to_have_count(
                    1, timeout=budget.post_click_timeout_ms(120000)
                )
                await expect(completion.get_by_role('heading')).to_have_count(1)
                await expect(completion.get_by_role('button')).to_have_count(2)
            except (BrowserTimeoutError, AssertionError):
                raise budget.timeout_error(True) from None
            # 完成框两个动作均是关闭/完成；按可访问名称收窄，不再取 .last。
            close_button = await _unique(
                completion.get_by_role('button', name=_COMPLETION_CLOSE_NAMES),
                "Reel 完成框关闭",
            )
            await humanizer.click(close_button)
            await expect(completion).to_have_count(0)
            if not self.schedule:
                # Reel 创建响应实测可能没有 pending_publish_content_id，作品列表也可能在视频处理期间不展示。
                # 完成弹窗和无错误的创建响应已经是“提交成功、正在处理”的业务证据；编号只用于后续核验/删除，不能阻断发布结果。
                self.result['status'] = 'processing'
                self.result['schedule'] = None
                self.result_file.write_text(json.dumps(self.result, ensure_ascii=False, indent=2), encoding='utf-8')
                return
        # 创建响应明确受理后按 Page 和原作品编号查询；不依赖任何语言的成功提示。
        # 定时作品必须读回排期；图文立即发布必须读回原作品；这两类结果不能只凭弹窗判断。
        from uploader.meta_uploader.facebook_page_uploader.posts import open_meta_post
        state = 'scheduled_posts' if self.schedule else 'published_posts'
        list_url = f'https://business.facebook.com/latest/posts/{state}?asset_id={self.result["page_id"]}'
        _, content_id, _ = await open_meta_post(page, list_url=list_url, page_name=self.page_name,
            expected_text=self.title, content_id=self.result.get('content_id'), schedule=self.schedule)
        self.result['content_id'] = content_id
        self.result['status'] = 'scheduled' if self.schedule else ('processing' if self.video_file else 'published')
        self.result['schedule'] = self.schedule.isoformat() if self.schedule else None

    def _validate_media(self) -> None:
        if self.video_file:
            self.validate_video_file(self.video_file)
        for path in self.image_files:
            self.validate_image_file(path)

    def _write_result(self) -> None:
        self.result_file.parent.mkdir(parents=True, exist_ok=True)
        self.result_file.write_text(json.dumps(self.result, ensure_ascii=False, indent=2), encoding='utf-8')

    async def _publish_on_page(self, page: Page) -> None:
        await dismiss_guidance_cards(page)
        await self._select_publish_location(page)
        await self._upload_files(page)
        await self._fill_caption(page)
        await self._advance_reels(page)
        await self._fill_schedule(page)
        await self._publish(page)

    async def upload_in(self, session: BrowserSession) -> dict:
        """Multilogin body: consume the injected context, touch no cookies."""
        self.start_publish_budget()
        page = await session.context.new_page()
        page.set_default_timeout(30_000)
        await page.goto(
            META_BUSINESS_URL,
            wait_until="domcontentloaded",
            timeout=self.publish_budget.clamp_ms(120_000),
        )
        if session.managed:
            _raise_if_login_required(page)
            if await _is_business_logged_out(page):
                raise LoginRequiredError(
                    "Facebook Page 登录态无效：请在 Multilogin 应用中登录 Profile 后重试。"
                )
        try:
            await self._publish_on_page(page)
            if session.managed:
                _raise_if_login_required(page)
            return self.result
        finally:
            self._write_result()

    async def upload(self, *, session: BrowserSession | None = None) -> dict:
        # Media validation is shared; cookie handling stays local-only.
        self._validate_media()
        if session is not None:
            return await self.upload_in(session)

        self.start_publish_budget()
        async with async_playwright() as playwright:
            browser, context, page = await _open_business_page(
                playwright, self.account_file, proxy=self.proxy, headless=self.headless
            )
            try:
                if await _is_business_logged_out(page):
                    raise RuntimeError("Business Suite 登录态失效，请先执行对应平台 login")
                await self._publish_on_page(page)
                await context.storage_state(path=str(self.account_file))
                return self.result
            finally:
                self._write_result()
                await browser.close()
