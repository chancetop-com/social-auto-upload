# -*- coding: utf-8 -*-
"""YouTube uploader (browser automation via YouTube Studio).

Unlike the other platforms here, YouTube also offers an official Data API. We deliberately
use browser automation instead, because videos uploaded through an *unaudited* API project
are force-locked to private and cannot be made public without passing Google's compliance
audit (which is impractical for personal/single-channel use). Browser automation has no such
restriction and can publish public videos right away.

Login is interactive (Google account, no QR code): the browser opens, the user signs in, and
the dedicated persistent browser Profile retains the session for later uploads.
"""
import asyncio
from pathlib import Path

from patchright.async_api import BrowserContext, Page, Playwright, async_playwright

from uploader.base_video import BaseVideoUploader
from uploader.publish_timeout import PublishTimeoutBudget
from utils.caption_topics import parse_caption_topics
from utils.local_account import local_account_alias
from utils.dom import ElementUnusableError, reject_ambiguous
from utils.browser_cleanup import close_browser_resources
from utils.browser_session import BrowserSession, provider_label
from utils.errors import LoginRequiredError
from utils.local_browser_session import local_browser_session
from utils.humanize import (
    DEFAULT_PROFILE,
    MAYBE_DISPATCHED,
    MAYBE_DISPATCHED_VALUE,
    Humanizer,
    maybe_dispatched,
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

# Studio can show the video's URL while it is still a draft. Only the
# post-submit share dialog (or its dialog controls and link) confirms success.
YOUTUBE_PUBLISH_CONFIRMATION = (
    "ytcp-video-share-dialog:visible, "
    ":is([role=dialog], tp-yt-paper-dialog, ytcp-dialog):visible"
    ":not(:has(#done-button:visible))"
    ":has(a:is([href*='youtu.be/'], [href*='watch?v=']):visible)"
    ":has(#close-button:visible)"
)

#: `# 话题` 补全容器（YouTube Studio 的 hashtag 建议列表）。
HASHTAG_AUTOCOMPLETE = "ytcp-hashtag-autocomplete"
#: 可能处于打开状态的浮层；只用于「确认有浮层」时才按 Escape。
AUTOCOMPLETE_VISIBLE = (
    "tp-yt-iron-dropdown:visible, ytcp-hashtag-autocomplete:visible"
)
#: 候选项等待上限：补全靠网络，等不到就按纯文本继续，不拖住整条发布链。
HASHTAG_CANDIDATE_TIMEOUT_MS = 1500
#: YouTube 简介整帖硬限制（平台文档口径：5000 字符）。
YOUTUBE_DESCRIPTION_MAX_LENGTH = 5000
#: 简介字段附近的整帖错误提示。选择器来自受控页面；真实账号界面未实测。
YOUTUBE_DESCRIPTION_ERROR = (
    "#description-error:visible, "
    "#description-textarea .error:visible, "
    "ytcp-form-input-container:has(#description-textarea) .error-message:visible"
)

# Historical managed-session hints are retained for identical ignored-option logs.
# Local sessions use local_context_kwargs() and the shared native browser resolver.
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


def _raise_if_login_required(page, *, mode="local", publish_attempted=False):
    url = str(getattr(page, "url", "") or "").lower()
    if not any(marker in url for marker in _LOGIN_URL_MARKERS):
        return
    verification = any(marker in url for marker in ("captcha", "challenge", "two-factor", "2fa", "verify"))
    remedy = "请在所选 Profile 完成人机验证 (reason=verification)" if verification else "请运行 sau youtube login"
    if mode != "local":
        action = "完成人机验证 (reason=verification)" if verification else "登录 Profile"
        remedy = f"请在 {provider_label(mode)} 应用中{action}"
    stage = "；发布可能已提交，请先核查作品，禁止自动重发" if publish_attempted else ""
    raise LoginRequiredError(f"YouTube 需要登录或验证；{remedy}{stage}。",
                             reason="verification" if verification else "login",
                             publish_attempted=publish_attempted)


def _account_alias(account_file=None, account_name=None):
    return local_account_alias(account_file, account_name, platform="youtube")


def local_context_kwargs():
    return {"proxy": {"server": YT_PROXY}} if YT_PROXY else {}


async def cookie_auth(account_file=None, *, account_name=None, headless=None, local_browser=None):
    """Compatibility entry point: checks only the selected persistent Profile."""
    return await youtube_setup(account_file, account_name=account_name,
                               headless=headless, local_browser=local_browser)


async def is_logged_in(context: BrowserContext, *, managed=True) -> bool:
    """Check YouTube Studio; persistent local contexts own their operation pages.

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
        if isinstance(status, int) and status >= (500 if managed else 400):
            raise RuntimeError(f"YouTube 登录状态检查失败：HTTP {status}")

        wait_for_timeout = getattr(page, "wait_for_timeout", None)
        if wait_for_timeout is not None:
            await wait_for_timeout(YOUTUBE_LOGIN_CHECK_SETTLE_MS)

        current_url = str(getattr(page, "url", "") or "")
        lowered = current_url.lower()
        if not current_url:
            raise RuntimeError("YouTube 登录状态检查失败：页面 URL 为空")

        if not managed:
            _raise_if_login_required(page)

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
        if managed:
            await close_browser_resources(page=page)


async def youtube_cookie_gen(account_file=None, headless=None, *, account_name=None, local_browser=None):
    """Interactive Google login in the selected persistent Profile."""
    return await youtube_setup(account_file, handle=True, return_detail=True,
                               headless=headless, account_name=account_name,
                               local_browser=local_browser)


async def youtube_setup(account_file=None, handle=False, return_detail=False, headless=None,
                        *, account_name=None, local_browser=None):
    account = _account_alias(account_file, account_name)
    async with async_playwright() as playwright:
        async with local_browser_session(
            playwright, platform="youtube", account=account, create=handle,
            headless=headless, local_browser=local_browser,
            context_kwargs=local_context_kwargs(),
        ) as session:
            if handle:
                page = await session.context.new_page()
                response = await page.goto(STUDIO_URL, wait_until="domcontentloaded",
                                           timeout=YOUTUBE_LOGIN_CHECK_TIMEOUT_MS)
                status = getattr(response, "status", None)
                if isinstance(status, int) and status >= 400:
                    raise RuntimeError(f"YouTube 登录页面失败：HTTP {status}")
                youtube_logger.info("请在浏览器里登录 Google / YouTube 账号；Profile 将保存登录态")
                for _ in range(600):
                    if "studio.youtube.com/channel/" in str(page.url):
                        break
                    await asyncio.sleep(1)
                else:
                    raise LoginRequiredError("YouTube 登录超时；请重新运行 sau youtube login。")
            if not await is_logged_in(session.context, managed=False):
                raise LoginRequiredError("YouTube 登录态失效；请运行 sau youtube login。")
            result = {"success": True, "status": "logged_in", "message": "登录成功",
                      "account_name": account}
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


def _first_difference(expected: str, actual: str) -> int:
    """Return the first differing code-point offset (or the shorter length)."""
    for offset, (want, got) in enumerate(zip(expected, actual)):
        if want != got:
            return offset
    return min(len(expected), len(actual))


def _context(text: str, offset: int, radius: int = 12) -> str:
    return text[max(0, offset - radius):offset + radius]


def _readback_error(label: str, expected: str, actual: str) -> RuntimeError:
    offset = _first_difference(expected, actual)
    return RuntimeError(
        f"YouTube {label}读回不一致：首处差异偏移 {offset}；"
        f"期望 {_context(expected, offset)!r}，实际 {_context(actual, offset)!r}"
        f"（期望长度 {len(expected)}，实际长度 {len(actual)}）；未点击发布"
    )


async def _read_editable(page: Page, selector: str, *, multiline: bool) -> str:
    raw = await page.locator(selector).first.inner_text()
    return _normalise_text(raw, multiline=multiline)


async def _verify_editable(
    page: Page,
    selector: str,
    expected: str,
    *,
    label: str,
    multiline: bool,
) -> None:
    """Compare the typed field's page value with the same normalization as the writer."""
    actual = await _read_editable(page, selector, multiline=multiline)
    if actual != expected:
        raise _readback_error(label, expected, actual)


async def _description_limit_message(page: Page) -> str | None:
    """Return a visible Studio description/post hard-limit message, if any."""
    error = page.locator(YOUTUBE_DESCRIPTION_ERROR)
    if await error.count() == 0:
        return None
    try:
        message = (await error.first.inner_text()).strip()
    except Exception:
        message = ""
    return message or "页面显示简介长度错误"


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
    不设第二个阈值，也不挑 hashtag 候选。视野内时按共享解析器给出的
    ``#话题`` 逐段逐字输入；结尾标点留在话题外，URL 片段不当作话题。每段
    ``#topic`` 后点选全等候选，匹配失败降级为纯文本继续。
    """
    if len(text) > DEFAULT_PROFILE.type_horizon_chars:
        await humanizer.type_text(text)
        return
    topics = parse_caption_topics(text)
    cursor = 0
    for occurrence in topics.occurrences:
        if occurrence.start > cursor:
            await humanizer.type_text(text[cursor:occurrence.start])
        await humanizer.type_text(occurrence.text)
        if not await _select_hashtag_candidate(
            page, humanizer, occurrence.text
        ):
            await _dismiss_autocomplete(page, humanizer, blur=False)
        cursor = occurrence.end
    if cursor == 0:
        # 没有 `#` 话题：一次 type_text。
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
    allow_hashtags: bool = True,
):
    """逐字填 YouTube Studio 的 contenteditable 富文本框（标题/简介）。

    路径（人类化交互层，替代旧的 ``fill()`` / ``type(delay=)`` 结论）：

    1. ``humanizer.click`` 聚焦 → ``ControlOrMeta+A`` → ``Delete`` 清空；
    2. 逐字 ``type_text``：ASCII（含 ``#``）走真实按键，中文/emoji 走
       ``insert_text``；
    3. ``allow_hashtags`` 为真时，每段 ``#tag`` 后等 ``ytcp-hashtag-autocomplete``
       候选项，按文本**全等**点选；等不到 / 没有全等项 / 点选失败 → 保留纯文本、
       Escape 收起浮层，继续输入剩余内容。标题必须传 ``False``：候选点选可能
       改写标题，标题只保留自己的原文；
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
        if allow_hashtags:
            await _type_with_hashtags(page, humanizer, value)
        else:
            await humanizer.type_text(value)
    await page.wait_for_timeout(400)
    await _dismiss_autocomplete(page, humanizer)


async def _click_if_present(
    page: Page,
    selector: str,
    timeout: int = 4000,
    *,
    humanizer: Humanizer,
    unique: bool = False,
) -> bool:
    """目标存在则用人类化指针点它；保留「可缺席」语义：不存在返回 ``False``，不抛。

    ``humanizer`` 必传——每个可见点击都走同一实例。唯一例外是
    ``mouse.down`` 之后才失败的 ``click_dispatched="maybe"``：那时可能已经点到
    页面上，继续返回 ``False`` 会让调用方再点兜底选择器，所以原样上抛。
    """
    try:
        el = page.locator(selector)
        if unique:
            await reject_ambiguous(el, "YouTube 发布按钮")
        else:
            el = el.first
        await el.wait_for(state="visible", timeout=timeout)
        await humanizer.click(el)
        return True
    except Exception as exc:
        if getattr(exc, MAYBE_DISPATCHED, None) == MAYBE_DISPATCHED_VALUE:
            raise
        if unique and isinstance(exc, ElementUnusableError) and exc.reason.startswith("ambiguous:"):
            raise
        return False


async def _wait_upload_complete(
    page: Page,
    *,
    budget: PublishTimeoutBudget,
) -> bool:
    """在剩余发布预算内等到 Studio 显示上传完成、处理或检查状态。"""
    last = ""
    while True:
        budget.check_pre_click()
        txt = ""
        for sel in (".progress-label", "span.progress-label", "ytcp-video-upload-progress"):
            loc = page.locator(sel).first
            try:
                texts = await budget.wait_for_upload(loc.all_inner_texts())
                if texts:
                    txt = texts[0].strip()
                    if txt:
                        break
            except Exception:
                budget.check_pre_click()
        if txt:
            if any(k in txt for k in ("处理", "检查", "上传完成", "已上传", "Processing", "complete", "Checks", "Finished")):
                budget.check_pre_click()
                youtube_logger.info(_msg("✅", f"上传完成: {txt[:40]}"))
                return True
            if txt != last:
                youtube_logger.info(_msg("⏳", f"上传中: {txt[:40]}"))
                last = txt
        await page.wait_for_timeout(budget.clamp_ms(5000))


class YouTubeVideo(BaseVideoUploader):
    publish_platform_label = "YouTube"

    def __init__(self, title, file_path, tags, account_file, *,
                 description="", thumbnail_path=None, playlist=None,
                 visibility="public", debug=False, headless=None,
                 account_name=None, local_browser=None):
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
        self.account_name = account_name
        self.local_browser = local_browser
        self.publish_date = 0

    def set_publish_date(self, publish_date) -> None:
        self.publish_date = self.validate_publish_date(publish_date)

    async def upload(self, playwright: Playwright | None, *, session: BrowserSession | None = None) -> None:
        if session is not None:
            await self.upload_in(session)
            return

        if playwright is None:
            raise ValueError("本地模式需要 Playwright 实例")

        async with local_browser_session(
            playwright, platform="youtube", account=_account_alias(self.account_file, self.account_name),
            headless=self.headless, local_browser=self.local_browser,
            context_kwargs=local_context_kwargs(),
        ) as active:
            if not await is_logged_in(active.context, managed=False):
                raise LoginRequiredError("YouTube 登录态失效；请运行 sau youtube login。")
            await self.upload_in(active)

    async def upload_in(self, session: BrowserSession) -> Page:
        self.start_publish_budget()
        page = await session.context.new_page()
        page.set_default_timeout(60000)
        # 人类化实例在 page 创建后建立：HUMANIZE 在构造时快照，之后不再读 env。
        self._humanizer(page)

        youtube_logger.info(_msg("🎬", f"开始上传: {Path(self.file_path).name}"))
        self._publish_attempted = False
        try:
            response = await page.goto(UPLOAD_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            if not session.managed:
                status = getattr(response, "status", None)
                if isinstance(status, int) and status >= 400:
                    raise RuntimeError(f"YouTube 上传页面失败：HTTP {status}")
            _raise_if_login_required(page, mode=session.mode)
            await self._upload_video_on_page(page, mode=session.mode)
        except LoginRequiredError:
            raise
        except Exception as error:
            _raise_if_login_required(page, mode=session.mode, publish_attempted=self._publish_attempted)
            if self._publish_attempted:
                raise self.publish_budget.timeout_error(True) from error
            raise

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

    async def _upload_video_on_page(self, page: Page, *, mode: str = "local") -> None:
        _raise_if_login_required(page, mode=mode)
        humanizer = self._humanizer(page)

        # 1) 选择视频文件
        file_input = page.locator('input[type="file"]').first
        await file_input.wait_for(state="attached", timeout=60000)
        await file_input.set_input_files(self.file_path, timeout=self.publish_budget.remaining_ms())
        _raise_if_login_required(page, mode=mode)

        # 2) 等详情对话框
        await page.locator("#title-textarea").wait_for(
            state="visible", timeout=self.publish_budget.clamp_ms(120000)
        )

        # 3) 标题：独立字段，绝不走 # 补全（候选点选会改写标题）；写入后回读原文。
        youtube_logger.info(_msg("✍️", "填写标题"))
        title_value = _normalise_text(self.title[:100], multiline=False)
        await _fill_editable(
            page, "#title-textarea #textbox", title_value, humanizer,
            allow_hashtags=False,
        )
        await _verify_editable(
            page, "#title-textarea #textbox", title_value,
            label="标题", multiline=False,
        )

        # 4) 简介：公开配文；话题只从这里识别，标题中的 # 不计入。
        description_value = _normalise_text(self.description, multiline=True)
        if len(description_value) > YOUTUBE_DESCRIPTION_MAX_LENGTH:
            raise RuntimeError(
                f"YouTube 简介超出整帖硬限制（{len(description_value)} > "
                f"{YOUTUBE_DESCRIPTION_MAX_LENGTH} 字符）；未点击发布"
            )
        if description_value.strip():
            youtube_logger.info(_msg("✍️", "填写简介"))
            await _fill_editable(
                page,
                "#description-textarea #textbox",
                description_value,
                humanizer,
                multiline=True,
            )
            await _verify_editable(
                page,
                "#description-textarea #textbox",
                description_value,
                label="简介",
                multiline=True,
            )
        limit_message = await _description_limit_message(page)
        if limit_message:
            raise RuntimeError(
                f"YouTube 简介触及整帖硬限制：{limit_message}；未点击发布"
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
        _raise_if_login_required(page, mode=mode)

        # 11) 发布
        await budget.wait_until_allowed(
            getattr(self, "publish_not_before", None),
            logger=youtube_logger,
            label="YouTube 发布",
        )
        budget.check_pre_click()
        await page.wait_for_timeout(1200)
        await humanizer.before_submit()
        try:
            published = await _click_if_present(
                page, "#done-button", budget.clamp_ms(15000), humanizer=humanizer, unique=True
            )
        except Exception as exc:
            if maybe_dispatched(exc):
                self._publish_attempted = True
                # 发布点击可能已经发出：按结果未知上抛，禁止再次派发。
                raise budget.timeout_error(True) from exc
            raise
        if not published:
            raise RuntimeError("未找到 YouTube 发布按钮，未提交发布")
        else:
            self._publish_attempted = True
            await page.wait_for_timeout(4000)
            _raise_if_login_required(page, mode=mode, publish_attempted=True)
            if mode != "local":
                await page.locator(YOUTUBE_PUBLISH_CONFIRMATION).first.wait_for(
                    state="visible", timeout=budget.post_click_timeout_ms(8000)
                )
            video_url = ""
            try:
                link = page.locator("a[href*='youtu.be'], a[href*='watch?v=']").first
                if await link.count():
                    video_url = await link.get_attribute("href") or ""
            except Exception:
                pass
            try:
                await _click_if_present(page, "ytcp-button:has-text('Close'), ytcp-button:has-text('关闭'), #close-button", 8000,
                                        humanizer=humanizer)
            except Exception as exc:
                # 视频已经发布：关闭按钮只是界面收尾，失败只能记日志，绝不改变发布结果。
                youtube_logger.warning(
                    _msg("⚠️", f"发布完成后的关闭按钮点击失败（不影响发布结果）: {exc}")
                )
            youtube_logger.success(_msg("🥳", f"发布完成（{self.visibility}）{(' ' + video_url) if video_url else ''}"))

    async def main(self, *, session: BrowserSession | None = None):
        if session is not None:
            await self.upload(None, session=session)
            return
        async with async_playwright() as playwright:
            await self.upload(playwright)
