# -*- coding: utf-8 -*-
"""YouTube uploader (browser automation via YouTube Studio).

Unlike the other platforms here, YouTube also offers an official Data API. We deliberately
use browser automation instead, because videos uploaded through an *unaudited* API project
are force-locked to private and cannot be made public without passing Google's compliance
audit (which is impractical for personal/single-channel use). Browser automation has no such
restriction and can publish public videos right away, and it matches the cookie-based pattern
used by every other uploader in this project.

Login is interactive (Google account, no QR code): the browser opens, the user signs in, and
the storage_state is saved. Reuse it afterwards for fully unattended uploads.
"""
import asyncio
import re
from pathlib import Path

from patchright.async_api import BrowserContext, Page, Playwright, async_playwright

from uploader.base_video import BaseVideoUploader
from uploader.publish_timeout import PublishTimeoutBudget
from utils.base_social_media import set_init_script
from utils.browser_session import BrowserSession
from utils.errors import LoginRequiredError
from utils.humanize import (
    DEFAULT_PROFILE,
    MAYBE_DISPATCHED,
    MAYBE_DISPATCHED_VALUE,
    Humanizer,
)
from utils.log import youtube_logger

try:
    # 国内直连 youtube.com 会超时，且 patchright 启的 chromium 不吃系统代理。
    # 在 conf.py 设 YT_PROXY = "http://127.0.0.1:7890"（本地代理端口）即可；不设则不走代理。
    from conf import YT_PROXY
except Exception:
    YT_PROXY = None

STUDIO_URL = "https://studio.youtube.com"
UPLOAD_URL = "https://www.youtube.com/upload"
VISIBILITY = {"public": "PUBLIC", "unlisted": "UNLISTED", "private": "PRIVATE"}

YOUTUBE_LOGIN_CHECK_URL = STUDIO_URL
YOUTUBE_LOGIN_CHECK_TIMEOUT_MS = 20_000
YOUTUBE_LOGIN_CHECK_SETTLE_MS = 3_000

#: `# 话题` 补全容器（YouTube Studio 的 hashtag 建议列表）。
HASHTAG_AUTOCOMPLETE = "ytcp-hashtag-autocomplete"
#: 可能处于打开状态的浮层；只用于「确认有浮层」时才按 Escape。
AUTOCOMPLETE_VISIBLE = (
    "tp-yt-iron-dropdown:visible, ytcp-hashtag-autocomplete:visible"
)
#: 候选项等待上限：补全靠网络，等不到就按纯文本继续，不拖住整条发布链。
HASHTAG_CANDIDATE_TIMEOUT_MS = 1500
#: 一段 `#` 话题：`#` 后到空白 / 下一个 `#` 之前。
_HASHTAG_RE = re.compile(r"#[^\s#]+")

# Golden local-mode browser options.  ``sau_commands/youtube.py`` passes the
# same values to ``browser_session`` in Multilogin mode, where they are ignored:
# the Profile decides the exit IP and fingerprint.
YOUTUBE_LAUNCH_KWARGS = {
    "channel": "chrome",
    "proxy": {"server": YT_PROXY} if YT_PROXY else None,
}
YOUTUBE_CONTEXT_KWARGS: dict = {}
YOUTUBE_INIT_SCRIPT = True

_LOGIN_URL_MARKERS = (
    "accounts.google.com",
    "consent.youtube.com",
    "consent.google.com",
    "accountchooser",
    "/signin",
    "signin?",
    "login",
    "captcha",
    "two-factor",
    "2fa",
    "verify",
)


def _msg(emoji: str, text: str) -> str:
    return f"{emoji} {text}"


def _raise_if_login_required(page: Page) -> None:
    """Map a mid-upload login/captcha/2FA redirect to ``LoginRequiredError``.

    Only the Multilogin branch calls this.  Local mode keeps its historical
    ``RuntimeError`` (or timeout) behaviour untouched.
    """
    url = str(getattr(page, "url", "") or "").lower()
    if not url:
        return
    if any(marker in url for marker in _LOGIN_URL_MARKERS):
        raise LoginRequiredError(
            "YouTube 上传过程中需要重新登录（登录页/验证码/二次验证）："
            "请在 Multilogin 应用中登录 Profile 后重试。"
        )


def _build_login_result(success, status, message, account_file, current_url=""):
    return {
        "success": success,
        "status": status,
        "message": message,
        "account_file": str(account_file),
        "current_url": current_url,
    }


async def cookie_auth(account_file) -> bool:
    """登录态是否仍有效：带 cookie 打开 Studio，没被踢到 Google 登录页且进入了频道页即有效。"""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, channel="chrome")
        try:
            context = await browser.new_context(storage_state=account_file)
            context = await set_init_script(context)
            page = await context.new_page()
            await page.goto(STUDIO_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            url = page.url
            if "accounts.google.com" in url or "/signin" in url.lower():
                return False
            return "/channel/" in url
        except Exception:
            return False
        finally:
            await browser.close()


async def is_logged_in(context: BrowserContext) -> bool:
    """Return whether the Multilogin Profile is logged in to YouTube Studio.

    Only ``context.new_page()`` / ``goto`` / ``close`` are used.  Explicit
    sign-in, consent and account-chooser pages return ``False``; network
    failures, 5xx responses, timeouts and unexpected page structure raise so the
    CLI can exit 1 instead of silently treating an outage as "logged out".

    Worst-case budget: 20s navigation + 3s settle, inside the 15-30s spec.
    """
    page = await context.new_page()
    try:
        response = await page.goto(
            YOUTUBE_LOGIN_CHECK_URL,
            wait_until="domcontentloaded",
            timeout=YOUTUBE_LOGIN_CHECK_TIMEOUT_MS,
        )
        status = getattr(response, "status", None)
        if isinstance(status, int) and status >= 500:
            raise RuntimeError(f"YouTube 登录状态检查失败：HTTP {status}")

        wait_for_timeout = getattr(page, "wait_for_timeout", None)
        if wait_for_timeout is not None:
            await wait_for_timeout(YOUTUBE_LOGIN_CHECK_SETTLE_MS)

        current_url = str(getattr(page, "url", "") or "")
        lowered = current_url.lower()
        if not current_url:
            raise RuntimeError("YouTube 登录状态检查失败：页面 URL 为空")

        # Explicit sign-in / consent / account chooser pages.
        if any(
            marker in lowered
            for marker in (
                "accounts.google.com",
                "consent.youtube.com",
                "consent.google.com",
                "accountchooser",
            )
        ):
            return False
        if any(
            marker in lowered
            for marker in ("/signin", "login", "captcha", "two-factor", "2fa")
        ):
            return False

        # Positive studio anchor + the historical channel-page signal.
        if "studio.youtube.com" not in lowered:
            raise RuntimeError(
                "YouTube 登录状态检查失败：页面未停留在 YouTube Studio"
                f"（url={current_url}）"
            )
        if "/channel/" not in lowered:
            raise RuntimeError(
                "YouTube 登录状态检查失败：Studio 页面结构异常"
                f"（url={current_url}）"
            )
        return True
    finally:
        await page.close()


async def youtube_cookie_gen(account_file, headless: bool = False):
    """交互式登录：开浏览器让用户登录 Google/YouTube，进入频道页后保存 storage_state。"""
    async with async_playwright() as playwright:
        # 登录必须显形，让用户输账号密码/二步验证
        browser = await playwright.chromium.launch(headless=False, channel="chrome")
        context = await browser.new_context()
        context = await set_init_script(context)
        page = await context.new_page()
        await page.goto(STUDIO_URL, wait_until="domcontentloaded")
        youtube_logger.info(_msg("🔐", "请在弹出的浏览器里登录 Google / YouTube 账号，登录后会自动保存"))
        ok = False
        for _ in range(600):  # 最多等 10 分钟
            if "/channel/" in page.url:
                await page.wait_for_timeout(2000)  # 让 cookie 落定
                ok = True
                break
            await asyncio.sleep(1)
        if ok:
            await context.storage_state(path=account_file)
            youtube_logger.success(_msg("✅", f"YouTube 登录态已保存: {account_file}"))
        else:
            youtube_logger.error(_msg("😵", "等待登录超时，未保存登录态"))
        await browser.close()
        return _build_login_result(ok, "logged_in" if ok else "timeout",
                                   "登录成功" if ok else "登录超时", account_file, page.url)


async def youtube_setup(account_file, handle: bool = False, return_detail: bool = False, headless: bool = False):
    """校验登录态，失效且 handle=True 时拉起交互式登录。"""
    if not Path(account_file).exists() or not await cookie_auth(account_file):
        if not handle:
            result = _build_login_result(False, "cookie_invalid", "登录态不存在或已失效", account_file)
            return result if return_detail else False
        youtube_logger.info(_msg("🥹", "YouTube 登录态不存在或失效，准备打开浏览器登录"))
        result = await youtube_cookie_gen(account_file, headless=headless)
        return result if return_detail else result["success"]
    result = _build_login_result(True, "cookie_valid", "登录态有效", account_file)
    return result if return_detail else True


async def _dismiss_autocomplete(
    page: Page,
    humanizer: Humanizer,
    *,
    blur: bool = True,
):
    """关掉 # 话题 / @ 提及 自动补全下拉浮层（会挡住后续“继续/发布”按钮）。

    先 blur 失焦；若浮层仍可见再补一次 Escape——仅在检测到浮层时才按，
    避免在没有浮层时误关掉整个上传对话框。

    ``blur=False`` 只按 Escape 收起浮层、保留输入焦点：逐字填充中途遇到
    「候选项全等匹配失败」时用它降级为纯文本，然后继续输入剩余内容。
    """
    if blur:
        try:
            await page.evaluate("() => { const a = document.activeElement; if (a && a.blur) a.blur(); }")
        except Exception:
            pass
    try:
        dropdown = page.locator(AUTOCOMPLETE_VISIBLE)
        if await dropdown.count() > 0:
            await humanizer.press("Escape")
            await page.wait_for_timeout(200)
    except Exception:
        pass


def _normalise_text(text: str, *, multiline: bool) -> str:
    """多行先 ``\\r\\n``→``\\n``；单行字段不得含换行/制表符（会变成 Enter/Tab）。"""
    value = str(text).replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    if multiline:
        return value
    return value.replace("\n", " ")


async def _select_hashtag_candidate(
    page: Page,
    humanizer: Humanizer,
    tag: str,
    timeout: int = HASHTAG_CANDIDATE_TIMEOUT_MS,
) -> bool:
    """在 `#` 话题补全里按文本**全等**点选 ``tag``（含 `#`）。

    返回是否点中。等不到浮层、没有全等项、或点选本身失败都返回 ``False``：
    候选点选是增强，由调用方保留纯文本并收起浮层后继续，不能中止发布。
    点选失败可能是 ``click_dispatched="maybe"``，这里只降级、不重试。
    """
    autocomplete = page.locator(HASHTAG_AUTOCOMPLETE)
    try:
        await autocomplete.first.wait_for(state="visible", timeout=timeout)
    except Exception:
        return False
    try:
        candidate = autocomplete.get_by_text(tag, exact=True)
        if await candidate.count() == 0:
            return False
        await humanizer.click(candidate.first)
    except Exception:
        return False
    return True


async def _type_with_hashtags(page: Page, humanizer: Humanizer, text: str) -> None:
    """超打字视野整段一次 ``insert_text``；否则逐段逐字 + 点选候选。

    阈值先按**整段总长度**判定（spec §2.4 规则 4 / §3.14）：越过共享层视野
    （1000 码点）时由共享层一次性 bulk ``insert_text``，平台不按 ``#`` 切段、
    不设第二个阈值，也不挑 hashtag 候选。视野内时逐段逐字，每段 ``#tag`` 后点选
    全等候选，匹配失败降级为纯文本继续。
    """
    if len(text) > DEFAULT_PROFILE.type_horizon_chars:
        await humanizer.type_text(text)
        return
    cursor = 0
    for match in _HASHTAG_RE.finditer(text):
        if match.start() > cursor:
            await humanizer.type_text(text[cursor:match.start()])
        tag = match.group(0)
        await humanizer.type_text(tag)
        if not await _select_hashtag_candidate(page, humanizer, tag):
            await _dismiss_autocomplete(page, humanizer, blur=False)
        cursor = match.end()
    if cursor == 0:
        # 没有 `#`：一次 type_text。
        await humanizer.type_text(text)
    elif cursor < len(text):
        await humanizer.type_text(text[cursor:])


async def _fill_editable(
    page: Page,
    selector: str,
    text: str,
    humanizer: Humanizer,
    *,
    multiline: bool = False,
):
    """逐字填 YouTube Studio 的 contenteditable 富文本框（标题/简介）。

    路径（人类化交互层，替代旧的 ``fill()`` / ``type(delay=)`` 结论）：

    1. ``humanizer.click`` 聚焦 → ``ControlOrMeta+A`` → ``Delete`` 清空；
    2. 逐字 ``type_text``：ASCII（含 ``#``）走真实按键，中文/emoji 走
       ``insert_text``；
    3. 每段 ``#tag`` 后等 ``ytcp-hashtag-autocomplete`` 候选项，按文本**全等**
       点选；等不到 / 没有全等项 / 点选失败 → 保留纯文本、Escape 收起浮层，
       继续输入剩余内容；
    4. 收尾 ``_dismiss_autocomplete``，避免浮层盖住“继续/发布”。

    旧 docstring 的「``#`` 会让浮层卡死，所以只能一次性 fill」结论**作废**：
    浮层已由候选点选 + 收尾关闭处理。>1000 码点仍由 ``type_text`` 整段
    ``insert_text``，平台不设第二个阈值、也不自己切段。
    """
    value = _normalise_text(text, multiline=multiline)
    box = page.locator(selector).first
    await box.wait_for(state="visible", timeout=30000)
    await humanizer.click(box)
    await humanizer.press("ControlOrMeta+A")
    await humanizer.press("Delete")
    if value:
        await _type_with_hashtags(page, humanizer, value)
    await page.wait_for_timeout(400)
    await _dismiss_autocomplete(page, humanizer)


async def _click_if_present(
    page: Page,
    selector: str,
    timeout: int = 4000,
    *,
    humanizer: Humanizer,
) -> bool:
    """目标存在则用人类化指针点它；保留「可缺席」语义：不存在返回 ``False``，不抛。

    ``humanizer`` 必传——每个可见点击都走同一实例。唯一例外是
    ``mouse.down`` 之后才失败的 ``click_dispatched="maybe"``：那时可能已经点到
    页面上，继续返回 ``False`` 会让调用方再点兜底选择器，所以原样上抛。
    """
    try:
        el = page.locator(selector).first
        await el.wait_for(state="visible", timeout=timeout)
        await humanizer.click(el)
        return True
    except Exception as exc:
        if getattr(exc, MAYBE_DISPATCHED, None) == MAYBE_DISPATCHED_VALUE:
            raise
        return False


async def _wait_upload_complete(
    page: Page,
    max_polls: int = 360,
    *,
    budget: PublishTimeoutBudget | None = None,
) -> bool:
    """等网页上传从 X% 跑到 100% 再发布。浏览器上传靠窗口开着才传得完，
    若上传到一半就点发布并关闭浏览器，上传会被掐断卡在中途（如 76%）。
    出现“处理/检查/上传完成”或不再“正在上传”即视为传完。
    max_polls*5s 是平台上限，实际还受 15 分钟发布总预算约束。"""
    last = ""
    for _ in range(max_polls):
        if budget is not None:
            budget.check_pre_click()
        txt = ""
        for sel in (".progress-label", "span.progress-label", "ytcp-video-upload-progress"):
            loc = page.locator(sel).first
            try:
                if await loc.count():
                    txt = (await loc.inner_text()).strip()
                    if txt:
                        break
            except Exception:
                pass
        if txt:
            if any(k in txt for k in ("处理", "检查", "上传完成", "已上传", "Processing", "complete", "Checks", "Finished")):
                youtube_logger.info(_msg("✅", f"上传完成: {txt[:40]}"))
                return True
            if txt != last:
                youtube_logger.info(_msg("⏳", f"上传中: {txt[:40]}"))
                last = txt
        await page.wait_for_timeout(5000)
    youtube_logger.warning(_msg("⚠️", "等上传超时(30min)，仍尝试发布"))
    return False


class YouTubeVideo(BaseVideoUploader):
    publish_platform_label = "YouTube"

    def __init__(self, title, file_path, tags, account_file, *,
                 description="", thumbnail_path=None, playlist=None,
                 visibility="public", debug=False, headless=False):
        self.title = title
        self.file_path = str(file_path)
        self.tags = tags or []
        self.account_file = str(account_file) if account_file is not None else None
        self.description = description or ""
        self.thumbnail_path = str(thumbnail_path) if thumbnail_path else None
        self.playlist = playlist
        self.visibility = visibility if visibility in VISIBILITY else "public"
        self.debug = debug
        self.headless = headless
        self.publish_date = 0

    def set_publish_date(self, publish_date) -> None:
        self.publish_date = self.validate_publish_date(publish_date)

    async def upload(self, playwright: Playwright | None, *, session: BrowserSession | None = None) -> None:
        if session is not None:
            await self.upload_in(session)
            return

        if playwright is None:
            raise ValueError("本地模式需要 Playwright 实例")

        browser = await playwright.chromium.launch(
            headless=self.headless, **YOUTUBE_LAUNCH_KWARGS
        )
        context = await browser.new_context(
            storage_state=self.account_file,
            **YOUTUBE_CONTEXT_KWARGS,
        )
        context = await set_init_script(context)

        page: Page | None = None
        upload_success = False
        try:
            page = await self.upload_in(
                BrowserSession(browser=browser, context=context, mode="local")
            )
            upload_success = True
        finally:
            if upload_success:
                # 刷新 cookie
                try:
                    await context.storage_state(path=self.account_file)
                except Exception:
                    pass
                if page is not None:
                    await page.wait_for_timeout(2000)
            try:
                await context.close()
            finally:
                await browser.close()

    async def upload_in(self, session: BrowserSession) -> Page:
        self.start_publish_budget()
        page = await session.context.new_page()
        page.set_default_timeout(60000)
        # 人类化实例在 page 创建后建立：HUMANIZE 在构造时快照，之后不再读 env。
        self._humanizer(page)

        youtube_logger.info(_msg("🎬", f"开始上传: {Path(self.file_path).name}"))
        await page.goto(UPLOAD_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        multilogin = session.managed
        if multilogin:
            _raise_if_login_required(page)
        if "accounts.google.com" in page.url or "signin" in page.url.lower():
            raise RuntimeError("YouTube 登录态失效，请重新执行 login")

        await self._upload_video_on_page(page, multilogin=multilogin)
        return page

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
        await asyncio.sleep(min(seconds, remaining))

    async def _fill_playlist_name(self, page: Page, humanizer: Humanizer) -> None:
        """新建播放列表名：全选覆盖后逐字输入（单行）。"""
        title_box = page.locator(
            "ytcp-playlist-metadata-editor #textbox, #create-playlist-form #textbox"
        ).first
        if not await title_box.count():
            return
        await humanizer.click(title_box)
        await humanizer.press("ControlOrMeta+A")
        await humanizer.press("Delete")
        await humanizer.type_text(
            _normalise_text(self.playlist or "", multiline=False)
        )

    async def _fill_tags(self, page: Page, humanizer: Humanizer) -> None:
        """标签输入：全选覆盖后把逗号分隔的标签逐字打完（单行，保留尾逗号）。"""
        tag_input = page.locator(
            "#tags-container #text-input, ytcp-form-input-container#tags-container input"
        ).first
        await humanizer.click(tag_input)
        await humanizer.press("ControlOrMeta+A")
        await humanizer.press("Delete")
        payload = ",".join(str(tag) for tag in self.tags)[:500] + ","
        await humanizer.type_text(_normalise_text(payload, multiline=False))

    async def _upload_video_on_page(self, page: Page, *, multilogin: bool = False) -> None:
        if multilogin:
            _raise_if_login_required(page)
        humanizer = self._humanizer(page)

        # 1) 选择视频文件
        file_input = page.locator('input[type="file"]').first
        await file_input.wait_for(state="attached", timeout=60000)
        await file_input.set_input_files(self.file_path)
        if multilogin:
            _raise_if_login_required(page)

        # 2) 等详情对话框
        await page.locator("#title-textarea").wait_for(
            state="visible", timeout=self.publish_budget.clamp_ms(120000)
        )

        # 3) 标题
        youtube_logger.info(_msg("✍️", "填写标题"))
        await _fill_editable(page, "#title-textarea #textbox", self.title[:100], humanizer)

        # 4) 简介
        if self.description.strip():
            youtube_logger.info(_msg("✍️", "填写简介"))
            await _fill_editable(
                page,
                "#description-textarea #textbox",
                self.description,
                humanizer,
                multiline=True,
            )

        # 5) 封面（处理到一定进度才允许传，失败不致命）
        if self.thumbnail_path and Path(self.thumbnail_path).exists():
            try:
                thumb_input = page.locator(
                    "#file-loader input[type='file'], ytcp-thumbnail-uploader input[type='file']"
                ).first
                await thumb_input.wait_for(state="attached", timeout=20000)
                await thumb_input.set_input_files(self.thumbnail_path)
                await page.wait_for_timeout(2000)
                youtube_logger.info(_msg("🖼️", "封面已上传"))
            except Exception as exc:
                youtube_logger.warning(_msg("⚠️", f"封面上传跳过（不影响发布）: {exc}"))

        # 6) 加入播放列表（连载/系列追更）。弹窗务必关闭，否则挡住后续步骤。
        if self.playlist:
            try:
                await _click_if_present(
                    page, "#basics ytcp-text-dropdown-trigger, ytcp-video-metadata-playlists ytcp-dropdown-trigger", 8000,
                    humanizer=humanizer)
                await page.wait_for_timeout(1200)
                existing = page.locator(
                    f"tp-yt-paper-checkbox:has-text('{self.playlist}'), "
                    f"ytcp-checkbox-group:has-text('{self.playlist}')").first
                if await existing.count():
                    await humanizer.click(existing)
                else:
                    if await _click_if_present(page, "ytcp-button:has-text('New playlist'), ytcp-button:has-text('创建播放列表')", 4000,
                                               humanizer=humanizer):
                        await page.wait_for_timeout(800)
                        await _click_if_present(page, "tp-yt-paper-item:has-text('New playlist'), tp-yt-paper-item:has-text('新建播放列表')", 3000,
                                                humanizer=humanizer)
                        await self._fill_playlist_name(page, humanizer)
                        await _click_if_present(page, "ytcp-button#create-button, tp-yt-paper-dialog ytcp-button:has-text('Create'), tp-yt-paper-dialog ytcp-button:has-text('创建')", 4000,
                                                humanizer=humanizer)
            except Exception as exc:
                youtube_logger.warning(_msg("⚠️", f"播放列表处理跳过（不影响发布）: {exc}"))
            finally:
                await _click_if_present(page, "ytcp-playlist-dialog #save-button, ytcp-button:has-text('Done'), ytcp-button:has-text('完成')", 3000,
                                        humanizer=humanizer)
                await humanizer.press("Escape")
                await page.wait_for_timeout(600)

        # 7) 受众：非儿童向（必填）
        if not await _click_if_present(page, "tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK']", 10000,
                                       humanizer=humanizer):
            await _click_if_present(page, "tp-yt-paper-radio-button:has-text('not made for kids'), tp-yt-paper-radio-button:has-text('不是面向儿童')", 6000,
                                    humanizer=humanizer)

        # 8) 标签（“显示更多”里）
        if self.tags:
            try:
                await _click_if_present(page, "#toggle-button", 6000, humanizer=humanizer)
                await page.wait_for_timeout(800)
                await self._fill_tags(page, humanizer)
            except Exception as exc:
                youtube_logger.warning(_msg("⚠️", f"标签填写跳过（不影响发布）: {exc}"))

        # 9) 连点 Next 到“可见性”步骤
        for _ in range(5):
            vis = page.locator("tp-yt-paper-radio-button[name='PUBLIC']")
            if await vis.count() and await vis.first.is_visible():
                break
            if not await _click_if_present(page, "#next-button", 6000, humanizer=humanizer):
                await page.wait_for_timeout(1200)
            await page.wait_for_timeout(1000)

        # 10) 可见性
        youtube_logger.info(_msg("🌐", f"设置可见性 = {self.visibility}"))
        await _click_if_present(page, f"tp-yt-paper-radio-button[name='{VISIBILITY[self.visibility]}']", 10000,
                                humanizer=humanizer)

        # 10.5) 关键：等上传真正传完再发布。浏览器上传靠窗口开着传，
        #       传到一半就点发布+关浏览器 = 上传被掐断卡在中途（如 76%）。
        budget = self.publish_budget
        youtube_logger.info(_msg("📤", "等待上传完成（传完才发布）…"))
        await _wait_upload_complete(page, budget=budget)
        if multilogin:
            _raise_if_login_required(page)

        # 11) 发布
        await budget.wait_until_allowed(
            getattr(self, "publish_not_before", None),
            logger=youtube_logger,
            label="YouTube 发布",
        )
        budget.check_pre_click()
        await page.wait_for_timeout(1200)
        await humanizer.before_submit()
        if not await _click_if_present(page, "#done-button", budget.clamp_ms(15000), humanizer=humanizer):
            raise RuntimeError("未找到 YouTube 发布按钮，未提交发布")
        else:
            await page.wait_for_timeout(4000)
            video_url = ""
            try:
                link = page.locator("a[href*='youtu.be'], a[href*='watch?v=']").first
                if await link.count():
                    video_url = await link.get_attribute("href") or ""
            except Exception:
                pass
            await _click_if_present(page, "ytcp-button:has-text('Close'), ytcp-button:has-text('关闭'), #close-button", 8000,
                                    humanizer=humanizer)
            youtube_logger.success(_msg("🥳", f"发布完成（{self.visibility}）{(' ' + video_url) if video_url else ''}"))

    async def main(self, *, session: BrowserSession | None = None):
        if session is not None:
            await self.upload(None, session=session)
            return
        async with async_playwright() as playwright:
            await self.upload(playwright)
