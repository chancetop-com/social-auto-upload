# -*- coding: utf-8 -*-
import re
import time
from dataclasses import dataclass, replace
from datetime import datetime

# Multilogin runs on the same Patchright client as every other uploader.
# ``main.py`` (Firefox) intentionally stays on upstream Playwright and is not
# wired into the CLI.
from patchright.async_api import Playwright, async_playwright
from patchright.async_api import TimeoutError as PlaywrightTimeoutError
import os
import asyncio

from conf import LOCAL_CHROME_PATH, LOCAL_CHROME_HEADLESS
from uploader.base_video import BaseVideoUploader
from uploader.tk_uploader.tk_config import (
    TIKTOK_ENTRY_WAIT_MS,
    TIKTOK_IMAGE_SUFFIXES,
    TIKTOK_LOGIN_CHECK_TIMEOUT_MS,
    TIKTOK_LOGIN_CHECK_URL,
    TIKTOK_LOGIN_FORM_SELECTOR,
    TIKTOK_MAX_DESCRIPTION_LENGTH,
    TIKTOK_MAX_HASHTAG_COUNT,
    TIKTOK_MAX_IMAGE_BYTES,
    TIKTOK_MAX_IMAGE_COUNT,
    TIKTOK_MAX_TITLE_LENGTH,
    TIKTOK_PHOTO_UPLOAD_URL,
    TIKTOK_PUBLISH_TIMEOUT_SECONDS,
    TIKTOK_UPLOAD_ENTRY_SELECTOR,
    TIKTOK_UPLOAD_URL,
    Tk_Locator,
)
from utils.base_social_media import set_init_script
from utils.browser_session import BrowserSession
from utils.errors import LoginRequiredError, PublishResultUnknownError
from utils.files_times import get_absolute_path
from utils.log import tiktok_logger

# Multilogin deployment prerequisite: the Profile UI must already be English
# (US).  The MLX branch deliberately skips ``change_language`` so it never
# rewrites the Profile preference.

# Golden local-mode browser options.  The Multilogin branch ignores them, but
# locking them here keeps the legacy Chromium path byte-equivalent.
TIKTOK_LAUNCH_KWARGS = {"executable_path": LOCAL_CHROME_PATH}
TIKTOK_CONTEXT_KWARGS: dict = {}
TIKTOK_INIT_SCRIPT = False

_LOGIN_URL_MARKERS = ("/login", "captcha", "verify", "two-factor", "2fa")

# ---------------------------------------------------------------------------
# Ordered selector candidates (spec §5.5)
#
# Each step keeps its own ordered list, the first candidate whose locator
# count is non-zero wins, and the winning index is logged.  There is no
# cross-step fuzzy fallback.
# ---------------------------------------------------------------------------

# The cover editor is the nearest ancestor of the "Upload cover" tab that
# actually contains a file input.  Used to scope the broad file-input
# fallback so it can never reach the main video upload input.
COVER_EDITOR_SCOPE_SELECTOR = "xpath=ancestor::*[.//input[@type='file']][1]"
_COVER_PREVIEW_TIMEOUT_MS = 10_000

_COVER_EDIT_CANDIDATES = (
    ('get_by_text("Edit cover", exact=True)',
     lambda scope: scope.get_by_text("Edit cover", exact=True)),
    ('get_by_role("button", name="Edit cover")',
     lambda scope: scope.get_by_role("button", name="Edit cover")),
)

_COVER_UPLOAD_TAB_CANDIDATES = (
    ('get_by_text("Upload cover", exact=True)',
     lambda scope: scope.get_by_text("Upload cover", exact=True)),
)

_COVER_FILE_ARIA_SELECTOR = '[aria-label="Upload cover image"] input[type="file"]'
_COVER_FILE_ACCEPT_SELECTOR = 'input[type="file"][accept*="image/jpeg"]'

_COVER_PREVIEW_CANDIDATES = (
    ('[aria-label="Uploaded cover image"]',
     lambda scope: scope.locator('[aria-label="Uploaded cover image"]')),
)

_COVER_SAVE_CANDIDATES = (
    ('get_by_role("button", name=re.compile(r"^(Save|Confirm)$"))',
     lambda scope: scope.get_by_role(
         "button", name=re.compile(r"^(Save|Confirm)$")
     )),
)

# First-run AIGC guidance dialog.  It is top-level (outside the upload iframe),
# so these candidates run against ``page`` rather than ``locator_base``.
_AIGC_TURN_ON_CANDIDATES = (
    ('get_by_role("button", name="Turn on")',
     lambda page: page.get_by_role("button", name="Turn on")),
    ('[role="dialog"] button:has-text("Turn on")',
     lambda page: page.locator('[role="dialog"] button:has-text("Turn on")')),
    ('.TUXModal button:has-text("Turn on")',
     lambda page: page.locator('.TUXModal button:has-text("Turn on")')),
)
_AIGC_DIALOG_TIMEOUT_MS = 5_000


async def _find_candidate(scope, candidates):
    """Return ``(locator, index, description)`` for the first present candidate."""
    for index, (description, factory) in enumerate(candidates):
        try:
            locator = factory(scope)
            if await locator.count():
                return locator.first, index, description
        except Exception:
            # A detached frame/closed page makes ``count`` throw; treat it as
            # this candidate being absent and try the next one.
            continue
    return None


def _cover_error(control, stage, candidates, page, detail=None):
    tried = [description for description, _ in candidates]
    current_url = str(getattr(page, "url", "") or "<unknown>")
    suffix = f" | detail={detail}" if detail else ""
    return RuntimeError(
        f"TikTok 封面设置失败 | control={control} | stage={stage} | "
        f"tried={tried} | url={current_url}{suffix}"
    )


async def _resolve_candidate(scope, candidates, *, control, stage, page):
    found = await _find_candidate(scope, candidates)
    if found is None:
        raise _cover_error(control, stage, candidates, page)
    locator, index, description = found
    tiktok_logger.info(
        f"[+] cover {stage}: {control} candidate {index + 1}/{len(candidates)}"
        f" matched ({description})"
    )
    return locator


_PUBLISH_RESULT_UNKNOWN_MESSAGE = (
    "TikTok 发布结果未知：发布点击已发出，但未观察到成功页，"
    "也未命中登录/验证码跳转；帖子可能已经发布。"
)

_PRE_PUBLISH_TIMEOUT_MESSAGE = (
    "TikTok 发布超时（15 分钟）：尚未点击发布，未发布任何内容。"
)


@dataclass(frozen=True, slots=True)
class TiktokPublishOptions:
    """Tri-state publish options requested by the caller.

    ``None`` means "leave the page default untouched" and must never be
    replaced with a local default.  Ticket 13 extends this dataclass with the
    AIGC and brand-disclosure fields.
    """

    privacy: str | None = None          # public / friends / followers / only-me
    allow_comments: bool | None = None
    allow_reuse: bool | None = None
    aigc: bool | None = None
    your_brand: bool | None = None
    branded_content: bool | None = None


# Page copy -> CLI/API semantic value.  ``Only you`` and ``Private`` are the
# same option in two A/B variants; ``Everyone`` and ``Public`` likewise.
_PRIVACY_LABELS = {
    "everyone": "public",
    "public": "public",
    "friends": "friends",
    "followers": "followers",
    "only you": "only-me",
    "private": "only-me",
}


def normalize_privacy_label(text: str | None) -> str | None:
    """Normalize a visibility label to ``public/friends/followers/only-me``.

    The first line is used because the ``Friends`` option renders its subtitle
    (``Followers you follow back``) on the following line.  Unknown copy
    returns ``None`` so callers can fail strictly instead of guessing.
    """
    if not text:
        return None
    first_line = text.strip().splitlines()[0].strip()
    return _PRIVACY_LABELS.get(first_line.casefold())


class TiktokOptionControl:
    """Small async seam used by the publish-option steps.

    Tests drive the steps with in-memory implementations; production code uses
    the locator adapters below.  Keeping the steps on this interface means the
    option logic never contains DOM/CSS assertions.
    """

    candidates: tuple[str, ...] = ()
    candidate_index: int | None = None

    async def is_checked(self) -> bool:
        raise NotImplementedError

    async def is_disabled(self) -> bool:
        raise NotImplementedError

    async def click(self) -> None:
        raise NotImplementedError

    async def get_attribute(self, name: str) -> str | None:
        raise NotImplementedError

    async def read_text(self) -> str:
        raise NotImplementedError

    async def options(self) -> list["TiktokOptionControl"]:
        return []

    async def count(self) -> int:
        raise NotImplementedError


class _LocatorControl(TiktokOptionControl):
    """Checkbox/option adapter over a Patchright locator."""

    def __init__(self, locator, *, candidates: tuple[str, ...] = ()) -> None:
        self._locator = locator
        self.candidates = candidates

    async def is_checked(self) -> bool:
        return bool(await self._locator.is_checked())

    async def is_disabled(self) -> bool:
        try:
            if await self._locator.is_disabled():
                return True
        except Exception:
            pass
        aria = await self._locator.get_attribute("aria-disabled")
        if str(aria).lower() == "true":
            return True
        classes = (await self._locator.get_attribute("class")) or ""
        return "disabled" in classes.casefold()

    async def click(self) -> None:
        await self._locator.click()

    async def get_attribute(self, name: str) -> str | None:
        return await self._locator.get_attribute(name)

    async def read_text(self) -> str:
        return (await self._locator.inner_text()).strip()

    async def count(self) -> int:
        return await self._locator.count()


class _LocatorPrivacyControl(TiktokOptionControl):
    """Visibility combobox adapter: trigger text plus its option list."""

    def __init__(
        self, trigger, option_scope, *, candidates: tuple[str, ...] = ()
    ) -> None:
        self._trigger = trigger
        self._option_scope = option_scope
        self.candidates = candidates

    async def is_checked(self) -> bool:
        return False

    async def is_disabled(self) -> bool:
        try:
            if await self._trigger.is_disabled():
                return True
        except Exception:
            pass
        classes = (await self._trigger.get_attribute("class")) or ""
        return "disabled" in classes.casefold()

    async def click(self) -> None:
        await self._trigger.click()

    async def get_attribute(self, name: str) -> str | None:
        return await self._trigger.get_attribute(name)

    async def read_text(self) -> str:
        return (await self._trigger.inner_text()).strip()

    async def options(self) -> list[TiktokOptionControl]:
        locator = self._option_scope.locator('li[role="option"]')
        count = await locator.count()
        return [_LocatorControl(locator.nth(i)) for i in range(count)]

    async def count(self) -> int:
        return await self._trigger.count()


@dataclass(frozen=True, slots=True)
class TiktokSettingsControls:
    """Resolved controls for one ``apply_options`` run."""

    privacy: TiktokOptionControl | None = None
    comments: TiktokOptionControl | None = None
    reuse: TiktokOptionControl | None = None
    aigc: TiktokOptionControl | None = None
    brand_switch: TiktokOptionControl | None = None
    your_brand: TiktokOptionControl | None = None
    branded_content: TiktokOptionControl | None = None


def _page_url(page) -> str:
    return str(getattr(page, "url", "") or "")


def _option_error(
    *,
    option: str,
    stage: str,
    requested,
    actual,
    control,
    url: str,
) -> RuntimeError:
    candidates = tuple(getattr(control, "candidates", ()) or ())
    return RuntimeError(
        "TikTok 发布选项设置失败："
        f"option={option} stage={stage} requested={requested!r} "
        f"actual={actual!r} candidates={candidates!r} url={url!r}"
    )


async def _read_toggle_state(control: TiktokOptionControl) -> bool:
    try:
        return bool(await control.is_checked())
    except Exception:
        aria = await control.get_attribute("aria-checked")
        if aria is None:
            raise
        return str(aria).lower() == "true"


async def _read_switch_state(control: TiktokOptionControl) -> bool:
    """Read an ARIA switch state (``aria-checked``) with a native fallback."""
    aria = await control.get_attribute("aria-checked")
    if aria is not None:
        return str(aria).lower() == "true"
    return bool(await control.is_checked())


async def _set_toggle_option(
    control: TiktokOptionControl,
    requested: bool,
    *,
    option: str,
    url: str,
) -> None:
    current = await _read_toggle_state(control)
    if current == requested:
        # Already satisfied, even when the account-level setting disabled the
        # control: this is success and must not require a click.
        return
    if await control.is_disabled():
        raise _option_error(
            option=option,
            stage="disabled",
            requested=requested,
            actual=current,
            control=control,
            url=url,
        )
    await control.click()
    actual = await _read_toggle_state(control)
    if actual != requested:
        raise _option_error(
            option=option,
            stage="readback",
            requested=requested,
            actual=actual,
            control=control,
            url=url,
        )


async def _set_switch_option(
    control: TiktokOptionControl,
    requested: bool,
    *,
    option: str,
    url: str,
) -> None:
    """Set an ARIA switch via ``aria-checked`` readback."""
    current = await _read_switch_state(control)
    if current == requested:
        # Already satisfied, even when the platform disabled the switch.
        return
    if await control.is_disabled():
        raise _option_error(
            option=option,
            stage="disabled",
            requested=requested,
            actual=current,
            control=control,
            url=url,
        )
    await control.click()
    actual = await _read_switch_state(control)
    if actual != requested:
        raise _option_error(
            option=option,
            stage="readback",
            requested=requested,
            actual=actual,
            control=control,
            url=url,
        )


async def _set_privacy_option(
    control: TiktokOptionControl, requested: str, *, url: str
) -> None:
    current_label = await control.read_text()
    if normalize_privacy_label(current_label) == requested:
        # Already satisfied; do not require a click on a possibly disabled
        # combobox.
        return
    if await control.is_disabled():
        raise _option_error(
            option="privacy",
            stage="disabled",
            requested=requested,
            actual=current_label,
            control=control,
            url=url,
        )

    await control.click()
    matched: TiktokOptionControl | None = None
    for option in await control.options():
        if normalize_privacy_label(await option.read_text()) == requested:
            matched = option
            break

    if matched is None:
        # Strict: the requested level is not rendered for this account.  Never
        # fall back or rename the option.
        raise _option_error(
            option="privacy",
            stage="select",
            requested=requested,
            actual=current_label,
            control=control,
            url=url,
        )

    matched_label = await matched.read_text()
    if await matched.is_disabled():
        raise _option_error(
            option="privacy",
            stage="select-disabled",
            requested=requested,
            actual=matched_label,
            control=matched,
            url=url,
        )

    await matched.click()
    actual_label = await control.read_text()
    if normalize_privacy_label(actual_label) != requested:
        raise _option_error(
            option="privacy",
            stage="readback",
            requested=requested,
            actual=actual_label,
            control=control,
            url=url,
        )


def _raise_if_login_required(page) -> None:
    """Map a mid-upload login/captcha/2FA redirect to ``LoginRequiredError``.

    Only the Multilogin branch calls this.  Local mode keeps its historical
    retry-until-timeout behaviour.
    """
    url = str(getattr(page, "url", "") or "").lower()
    if not url:
        return
    path = url.split("?", 1)[0]
    if any(marker in path for marker in _LOGIN_URL_MARKERS):
        raise LoginRequiredError(
            "TikTok 上传过程中需要重新登录（登录页/验证码/二次验证）："
            "请在 Multilogin 应用中登录 Profile 后重试。"
        )


async def _select_probe_page(context):
    """Reuse a matching page, else ``pages[0]``, else open exactly one page."""
    pages = list(getattr(context, "pages", []) or [])
    for page in pages:
        if TIKTOK_LOGIN_CHECK_URL in str(getattr(page, "url", "") or ""):
            return page, False
    if pages:
        return pages[0], False
    return await context.new_page(), True


_LOGIN_TEXT_SIGNALS = ("Log in", "登录", "扫码登录")
_UPLOAD_TEXT_SIGNALS = ("Select video", "Upload video")


async def _login_form_present(page) -> bool:
    try:
        if await page.locator(TIKTOK_LOGIN_FORM_SELECTOR).count() > 0:
            return True
    except Exception:
        pass

    get_by_text = getattr(page, "get_by_text", None)
    if callable(get_by_text):
        for text in _LOGIN_TEXT_SIGNALS:
            try:
                if await get_by_text(text).count() > 0:
                    return True
            except Exception:
                continue
    return False


async def _upload_entry_present(page, timeout_ms: int) -> bool:
    try:
        if await page.locator(TIKTOK_UPLOAD_ENTRY_SELECTOR).count() > 0:
            return True
    except Exception:
        pass

    try:
        await page.wait_for_selector(
            TIKTOK_UPLOAD_ENTRY_SELECTOR, timeout=timeout_ms
        )
        return True
    except Exception:
        pass

    get_by_text = getattr(page, "get_by_text", None)
    if callable(get_by_text):
        for text in _UPLOAD_TEXT_SIGNALS:
            try:
                if await get_by_text(text).count() > 0:
                    return True
            except Exception:
                continue
    return False


async def is_logged_in(context) -> bool:
    """Return ``True`` only when TikTok Studio shows the upload entry.

    A login page/form means ``False``; network errors, 5xx, timeouts and
    unrecognised page structures raise so the CLI can exit 1 instead of
    misreporting "logged out".  Exactly one fresh page is opened and always
    closed in ``finally``; existing context pages are left untouched.
    """
    # Always probe on a fresh page: never navigate an injected context's
    # existing page away from whatever the caller is doing.
    page = await context.new_page()
    deadline = time.monotonic() + TIKTOK_LOGIN_CHECK_TIMEOUT_MS / 1000
    try:
        response = await page.goto(
            TIKTOK_LOGIN_CHECK_URL,
            wait_until="domcontentloaded",
            timeout=TIKTOK_LOGIN_CHECK_TIMEOUT_MS,
        )
        status = getattr(response, "status", 200) if response is not None else 200
        if status is not None and int(status) >= 500:
            raise RuntimeError(
                f"TikTok Studio 返回 HTTP {status}，无法判断登录状态。"
            )

        if "/login" in str(page.url).lower():
            return False
        if await _login_form_present(page):
            return False

        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            raise RuntimeError("TikTok 登录检测超时（20s）。")
        if await _upload_entry_present(
            page, min(TIKTOK_ENTRY_WAIT_MS, remaining_ms)
        ):
            return True
        if await _login_form_present(page):
            return False

        raise RuntimeError(
            "无法识别 TikTok Studio 上传页结构（既无上传入口，也无登录表单）。"
        )
    finally:
        await page.close()


async def cookie_auth(account_file):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=LOCAL_CHROME_HEADLESS)
        context = await browser.new_context(storage_state=account_file)
        context = await set_init_script(context)
        # 创建一个新的页面
        page = await context.new_page()
        # 访问指定的 URL
        await page.goto("https://www.tiktok.com/tiktokstudio/upload?lang=en")
        await page.wait_for_load_state('networkidle')
        try:
            # 选择所有的 select 元素
            select_elements = await page.query_selector_all('select')
            for element in select_elements:
                class_name = await element.get_attribute('class')
                # 使用正则表达式匹配特定模式的 class 名称
                if re.match(r'tiktok-.*-SelectFormContainer.*', class_name):
                    tiktok_logger.error("[+] cookie expired")
                    return False
            tiktok_logger.success("[+] cookie valid")
            return True
        except:
            tiktok_logger.success("[+] cookie valid")
            return True


async def tiktok_setup(account_file, handle=False):
    account_file = get_absolute_path(account_file, "tk_uploader")
    if not os.path.exists(account_file) or not await cookie_auth(account_file):
        if not handle:
            return False
        tiktok_logger.info('[+] cookie file is not existed or expired. Now open the browser auto. Please login with your way(gmail phone, whatever, the cookie file will generated after login')
        await get_tiktok_cookie(account_file)
    return True


async def get_tiktok_cookie(account_file):
    async with async_playwright() as playwright:
        options = {
            'args': [
                '--lang en-GB',
            ],
            'headless': LOCAL_CHROME_HEADLESS,  # Set headless option here
        }
        # Make sure to run headed.
        browser = await playwright.chromium.launch(**options)
        # Setup context however you like.
        context = await browser.new_context()  # Pass any options
        context = await set_init_script(context)
        # Pause the page, and start recording manually.
        page = await context.new_page()
        await page.goto("https://www.tiktok.com/login?lang=en")
        await page.pause()
        # 点击调试器的继续，保存cookie
        await context.storage_state(path=account_file)


class TiktokBaseUploader(BaseVideoUploader):
    """Shared TikTok Studio upload skeleton.

    The template in ``_upload_on_page`` runs the nine steps in a fixed order;
    subclasses implement the media-specific hooks.  ``ensure_mode`` and
    ``apply_cover`` are no-ops until later tickets fill them in; publish
    options are applied by ``apply_options`` (ticket 12).
    """

    upload_url = TIKTOK_UPLOAD_URL

    def media_label(self) -> str:
        """Human label used by the upload log; the video text is unchanged."""
        return f"{self.title}.mp4"

    def result_label(self, item_id) -> str:
        """Log line for the published item; the video text is unchanged."""
        return f"video_id: {item_id}"

    async def upload_in(self, session: BrowserSession) -> None:
        """Upload through an injected session without owning its lifecycle."""
        # Ticket 13 §3: reuse a URL-matching page, then pages[0], and only
        # create a page when the context has none.
        page, _owned = await _select_probe_page(session.context)
        multilogin = session.mode == "multilogin"
        deadline = (
            time.monotonic() + TIKTOK_PUBLISH_TIMEOUT_SECONDS
            if multilogin
            else None
        )
        await self._upload_on_page(
            page, multilogin=multilogin, deadline=deadline
        )

    def _check_publish_deadline(self, deadline: float | None) -> None:
        if deadline is not None and time.monotonic() >= deadline:
            raise RuntimeError(
                "TikTok 上传超时（15 分钟），已中止发布。"
            )

    async def _upload_on_page(self, page, *, multilogin: bool, deadline: float | None) -> None:
        # 1. open the upload page and pick the locator base
        await self.open_upload_page(page, multilogin=multilogin)
        # 2. attach the media file(s)
        await self.attach_media(page)
        # 3. fill the caption/title fields
        await self.fill_metadata(page)
        # 4. wait until the editor finished processing the media
        await self.wait_media_ready(
            page, deadline=deadline, multilogin=multilogin
        )
        # 5. publish options (privacy / comments / reuse)
        await self.apply_options(page)
        # 6. custom cover (video only; base is a no-op)
        await self.apply_cover(page)
        # 7. schedule, when requested
        await self.apply_schedule(page)
        # 8. publish
        await self.click_publish(
            page, deadline=deadline, multilogin=multilogin
        )
        if multilogin:
            _raise_if_login_required(page)
        # 9. read back the published item
        self.last_item_id = await self.read_result(page)
        tiktok_logger.success(self.result_label(self.last_item_id))

    async def open_upload_page(self, page, *, multilogin: bool) -> None:
        await page.goto(self.upload_url)
        tiktok_logger.info(f'[+]Uploading-------{self.media_label()}')
        if multilogin:
            _raise_if_login_required(page)

        try:
            await page.wait_for_url(self.upload_url, timeout=10000)
        except Exception:
            if multilogin:
                _raise_if_login_required(page)
            raise

        try:
            await page.wait_for_selector('iframe[data-tt="Upload_index_iframe"], div.upload-container', timeout=10000)
            tiktok_logger.info("Either iframe or div appeared.")
        except Exception as e:
            tiktok_logger.error("Neither iframe nor div appeared within the timeout.")
            if multilogin:
                _raise_if_login_required(page)

        await self.choose_base_locator(page)
        await self.ensure_mode(page)

    async def ensure_mode(self, page) -> None:
        """Confirm the TikTok Studio mode; the default is the video mode."""

    async def attach_media(self, page) -> None:
        raise NotImplementedError

    async def fill_metadata(self, page) -> None:
        raise NotImplementedError

    async def wait_media_ready(
        self,
        page,
        *,
        deadline: float | None = None,
        multilogin: bool = False,
    ) -> None:
        raise NotImplementedError

    async def apply_options(self, page) -> None:
        """Apply the explicitly requested publish options, then read back.

        ``None`` (or all-``None`` options) means the legacy path: not a single
        control interaction, not even a read.
        """
        options = getattr(self, "options", None)
        if options is None:
            return
        if (
            options.privacy is None
            and options.allow_comments is None
            and options.allow_reuse is None
            and options.aigc is None
            and not self._brand_requested()
        ):
            return

        controls = await self.resolve_option_controls(page)
        url = _page_url(page)
        if options.privacy is not None:
            await _set_privacy_option(
                controls.privacy, options.privacy, url=url
            )
        if options.allow_comments is not None:
            await _set_toggle_option(
                controls.comments,
                options.allow_comments,
                option="allow_comments",
                url=url,
            )
        if options.allow_reuse is not None:
            await _set_toggle_option(
                controls.reuse,
                options.allow_reuse,
                option="allow_reuse",
                url=url,
            )
        if options.aigc is not None:
            self._require_option_control(
                controls.aigc, "aigc", options.aigc, url
            )
            await self._set_aigc_option(controls.aigc, options.aigc, page=page, url=url)
        if self._brand_requested():
            await self._apply_brand_options(controls, url=url)

    def _brand_requested(self) -> bool:
        options = getattr(self, "options", None)
        if options is None:
            return False
        return options.your_brand is True or options.branded_content is True

    @staticmethod
    def _require_option_control(control, option, requested, url) -> None:
        if control is None:
            raise _option_error(
                option=option,
                stage="resolve",
                requested=requested,
                actual="control-not-found",
                control=None,
                url=url,
            )

    async def _set_aigc_option(
        self,
        control: TiktokOptionControl,
        requested: bool,
        *,
        page,
        url: str,
    ) -> None:
        current = await _read_switch_state(control)
        if current == requested:
            # Already satisfied, even when the account-level setting disabled
            # the switch: no click and no dialog.
            return
        if await control.is_disabled():
            raise _option_error(
                option="aigc",
                stage="disabled",
                requested=requested,
                actual=current,
                control=control,
                url=url,
            )
        await control.click()
        if requested:
            await self._confirm_aigc_turn_on(page)
        actual = await _read_switch_state(control)
        if actual != requested:
            raise _option_error(
                option="aigc",
                stage="readback",
                requested=requested,
                actual=actual,
                control=control,
                url=url,
            )

    async def _confirm_aigc_turn_on(self, page) -> None:
        """Click the first-run ``Labeling AI-generated content`` -> ``Turn on``.

        The dialog is optional (``localStorage`` remembers it was seen), so a
        missing button is not an error; the caller's readback still decides
        success.
        """
        found = await _find_candidate(page, _AIGC_TURN_ON_CANDIDATES)
        if found is None:
            return
        button, index, description = found
        tiktok_logger.info(
            f"[+] TikTok options: aigc dialog candidate #{index} "
            f"({description}) matched"
        )
        try:
            await button.click()
            await button.wait_for(
                state="detached", timeout=_AIGC_DIALOG_TIMEOUT_MS
            )
        except Exception:
            # Let the explicit aria-checked readback report the real failure.
            return

    async def _apply_brand_options(
        self, controls: TiktokSettingsControls, *, url: str
    ) -> None:
        """Open the master switch, then explicitly set both checkboxes.

        The checkbox that was not requested is normalized to ``False`` so a
        stale selection from the page/previous post can never leak through.
        Both may be ``True`` at the same time.
        """
        options = self.options
        your_brand = options.your_brand is True
        branded_content = options.branded_content is True

        self._require_option_control(
            controls.brand_switch, "brand_switch", True, url
        )
        await _set_switch_option(
            controls.brand_switch,
            True,
            option="brand_switch",
            url=url,
        )

        self._require_option_control(
            controls.your_brand, "your_brand", your_brand, url
        )
        self._require_option_control(
            controls.branded_content,
            "branded_content",
            branded_content,
            url,
        )
        await _set_toggle_option(
            controls.your_brand,
            your_brand,
            option="your_brand",
            url=url,
        )
        await _set_toggle_option(
            controls.branded_content,
            branded_content,
            option="branded_content",
            url=url,
        )

    def _requested_option_names(self) -> list[str]:
        options = getattr(self, "options", None)
        if options is None:
            return []
        names = []
        if options.privacy is not None:
            names.append("privacy")
        if options.allow_comments is not None:
            names.append("comments")
        if options.allow_reuse is not None:
            names.append("reuse")
        if options.aigc is not None:
            names.append("aigc")
        if self._brand_requested():
            names.extend(("brand_switch", "your_brand", "branded_content"))
        return names

    def _option_request_value(self, name: str):
        options = self.options
        if name in ("brand_switch",):
            return True
        if name in ("your_brand", "branded_content"):
            return getattr(options, name) is True
        return {
            "privacy": options.privacy,
            "comments": options.allow_comments,
            "reuse": options.allow_reuse,
            "aigc": options.aigc,
        }[name]

    def _option_candidate_factories(self, name: str):
        """Ordered candidates per spec §5.5: data-e2e, role, then text."""
        base = self.locator_base
        if base is None:
            return ()

        if name == "privacy":
            def from_container():
                scope = base.locator(
                    'div[data-e2e="video_visibility_container"]'
                )
                return _LocatorPrivacyControl(
                    scope.locator('button[role="combobox"]'), scope
                )

            def from_role():
                return _LocatorPrivacyControl(
                    base.get_by_role("combobox").first, base
                )

            def from_text():
                trigger = base.locator(
                    'xpath=//div[contains(text(), "Who can see this post")]'
                    '/following::button[@role="combobox"][1]'
                )
                return _LocatorPrivacyControl(trigger, base)

            return (
                ("data-e2e=video_visibility_container", from_container),
                ("role=combobox", from_role),
                ("text=Who can see this post", from_text),
            )

        perm = base.locator('div[data-e2e="user_perm_container"]')
        if name == "comments":
            return (
                (
                    "data-e2e=user_perm_container+role=Allow comments",
                    lambda: _LocatorControl(
                        perm.get_by_role(
                            "checkbox", name="Allow comments"
                        ).first
                    ),
                ),
                (
                    "data-e2e=user_perm_container+role=Comment",
                    lambda: _LocatorControl(
                        perm.get_by_role("checkbox", name="Comment").first
                    ),
                ),
                (
                    "data-e2e=user_perm_container+label=Allow comments",
                    lambda: _LocatorControl(
                        perm.locator(
                            'label:has-text("Allow comments") '
                            'input[type="checkbox"]'
                        ).first
                    ),
                ),
                (
                    "data-e2e=user_perm_container+label=Comment",
                    lambda: _LocatorControl(
                        perm.locator(
                            'label:has-text("Comment") '
                            'input[type="checkbox"]'
                        ).first
                    ),
                ),
            )

        if name == "reuse":
            return (
                (
                    "data-e2e=user_perm_container+role=Allow reuse of content",
                    lambda: _LocatorControl(
                        perm.get_by_role(
                            "checkbox", name="Allow reuse of content"
                        ).first
                    ),
                ),
                (
                    "data-e2e=user_perm_container+label=Allow reuse of content",
                    lambda: _LocatorControl(
                        perm.locator(
                            'label:has-text("Allow reuse of content") '
                            'input[type="checkbox"]'
                        ).first
                    ),
                ),
            )

        if name == "aigc":
            aigc_container = base.locator(
                '[data-e2e="aigc_container"]'
            )
            return (
                (
                    'data-e2e=aigc_container+role=switch',
                    lambda: _LocatorControl(
                        aigc_container.locator('[role="switch"]').first
                    ),
                ),
                (
                    'data-e2e=aigc_container+.Switch__content',
                    lambda: _LocatorControl(
                        aigc_container.locator('.Switch__content').first
                    ),
                ),
            )

        if name == "brand_switch":
            disclose = base.locator(
                '[data-e2e="disclose_content_container"]'
            )
            return (
                (
                    'data-e2e=disclose_content_container+role=switch',
                    lambda: _LocatorControl(
                        disclose.locator('[role="switch"]').first
                    ),
                ),
                (
                    'data-e2e=disclose_content_container+.Switch__content',
                    lambda: _LocatorControl(
                        disclose.locator('.Switch__content').first
                    ),
                ),
            )

        if name in ("your_brand", "branded_content"):
            label = (
                "Your brand" if name == "your_brand" else "Branded content"
            )
            return (
                (
                    f'role=checkbox[name="{label}"]',
                    lambda: _LocatorControl(
                        base.get_by_role("checkbox", name=label).first
                    ),
                ),
                (
                    f'text="{label}"',
                    lambda: _LocatorControl(
                        base.get_by_text(label, exact=True).first
                    ),
                ),
            )

        return ()

    async def _resolve_single_control(
        self, name: str
    ) -> TiktokOptionControl | None:
        factories = self._option_candidate_factories(name)
        labels = tuple(label for label, _ in factories)
        for index, (label, factory) in enumerate(factories):
            try:
                control = factory()
                if await control.count() > 0:
                    control.candidates = labels
                    control.candidate_index = index
                    tiktok_logger.info(
                        f"[+] TikTok options: {name} resolved by "
                        f"candidate #{index} ({label})"
                    )
                    return control
            except Exception:
                continue
        return None

    async def _expand_advanced_settings(self, page) -> None:
        if self.locator_base is None:
            return
        container = self.locator_base.locator(
            '[data-e2e="advanced_settings_container"]'
        )
        try:
            if await container.count() == 0:
                return
            classes = ((await container.get_attribute("class")) or "").casefold()
        except Exception:
            return
        collapsed = "collapsed" in classes.split()

        more_btn = container.locator(".more-btn")
        try:
            if await more_btn.count():
                text = (await more_btn.first.inner_text()).strip().casefold()
                if collapsed or "show more" in text:
                    await more_btn.first.click()
                    await page.wait_for_timeout(300)
                    return
        except Exception:
            pass

        show_more = container.get_by_text("Show more", exact=True)
        try:
            if await show_more.count():
                await show_more.first.click()
                await page.wait_for_timeout(300)
        except Exception:
            pass

    async def resolve_option_controls(self, page) -> TiktokSettingsControls:
        """Resolve only the requested controls; expand advanced settings once.

        Missing controls are looked up again after a single expansion attempt.
        There is deliberately no whole-page fallback.
        """
        resolved: dict[str, TiktokOptionControl] = {}
        missing: list[str] = []
        for name in self._requested_option_names():
            control = await self._resolve_single_control(name)
            if control is None:
                missing.append(name)
            else:
                resolved[name] = control

        if missing:
            await self._expand_advanced_settings(page)
            still_missing: list[str] = []
            for name in missing:
                control = await self._resolve_single_control(name)
                if control is None:
                    still_missing.append(name)
                else:
                    resolved[name] = control

            if still_missing:
                url = _page_url(page)
                details = []
                for name in still_missing:
                    candidates = tuple(
                        label
                        for label, _ in self._option_candidate_factories(name)
                    )
                    details.append(
                        f"option={name} stage=resolve "
                        f"requested={self._option_request_value(name)!r} "
                        f"actual='control-not-found' "
                        f"candidates={candidates!r} url={url!r}"
                    )
                raise RuntimeError(
                    "TikTok 发布选项设置失败：" + " | ".join(details)
                )

        return TiktokSettingsControls(
            privacy=resolved.get("privacy"),
            comments=resolved.get("comments"),
            reuse=resolved.get("reuse"),
            aigc=resolved.get("aigc"),
            brand_switch=resolved.get("brand_switch"),
            your_brand=resolved.get("your_brand"),
            branded_content=resolved.get("branded_content"),
        )

    async def apply_cover(self, page) -> None:
        """Custom cover; the base has none (photo posts use the first image)."""

    async def apply_schedule(self, page) -> None:
        if self.publish_date == 0:
            return

        publish_date = self.publish_date
        schedule_input_element = self.locator_base.get_by_label('Schedule')
        await schedule_input_element.wait_for(state='visible')  # 确保按钮可见

        await schedule_input_element.click(force=True)
        if await self.locator_base.locator('div.TUXButton-content >> text=Allow').count():
            await self.locator_base.locator('div.TUXButton-content >> text=Allow').click()

        scheduled_picker = self.locator_base.locator('div.scheduled-picker')
        await scheduled_picker.locator('div.TUXInputBox').nth(1).click()

        calendar_month = await self.locator_base.locator(
            'div.calendar-wrapper span.month-title').inner_text()

        n_calendar_month = datetime.strptime(calendar_month, '%B').month

        schedule_month = publish_date.month

        if n_calendar_month != schedule_month:
            if n_calendar_month < schedule_month:
                arrow = self.locator_base.locator('div.calendar-wrapper span.arrow').nth(-1)
            else:
                arrow = self.locator_base.locator('div.calendar-wrapper span.arrow').nth(0)
            await arrow.click()

        # day set
        valid_days_locator = self.locator_base.locator(
            'div.calendar-wrapper span.day.valid')
        valid_days = await valid_days_locator.count()
        for i in range(valid_days):
            day_element = valid_days_locator.nth(i)
            text = await day_element.inner_text()
            if text.strip() == str(publish_date.day):
                await day_element.click()
                break
        # time set
        await scheduled_picker.locator('div.TUXInputBox').nth(0).click()

        hour_str = publish_date.strftime("%H")
        correct_minute = int(publish_date.minute / 5)
        minute_str = f"{correct_minute:02d}"

        hour_selector = f"span.tiktok-timepicker-left:has-text('{hour_str}')"
        minute_selector = f"span.tiktok-timepicker-right:has-text('{minute_str}')"

        # pick hour first
        await page.wait_for_timeout(1000)  # 等待500毫秒
        await self.locator_base.locator(hour_selector).click()
        # click time button again
        await page.wait_for_timeout(1000)  # 等待500毫秒
        # pick minutes after
        await self.locator_base.locator(minute_selector).click()

        # click title to remove the focus.
        # await self.locator_base.locator("h1:has-text('Upload video')").click()

    async def fill_caption(self, page, text, tags, *, editor=None) -> None:

        editor_locator = (
            editor
            if editor is not None
            else self.locator_base.locator('div.public-DraftEditor-content')
        )
        await editor_locator.click()

        await page.keyboard.press("End")

        await page.keyboard.press("Control+A")

        await page.keyboard.press("Delete")

        await page.keyboard.press("End")

        await page.wait_for_timeout(1000)  # 等待1秒

        await page.keyboard.insert_text(text)
        await page.wait_for_timeout(1000)  # 等待1秒
        await page.keyboard.press("End")

        await page.keyboard.press("Enter")

        # tag part
        for index, tag in enumerate(tags, start=1):
            tiktok_logger.info("Setting the %s tag" % index)
            await page.keyboard.press("End")
            await page.wait_for_timeout(1000)  # 等待1秒
            await page.keyboard.insert_text("#" + tag + " ")
            await page.keyboard.press("Space")
            await page.wait_for_timeout(1000)  # 等待1秒

            await page.keyboard.press("Backspace")
            await page.keyboard.press("End")

    async def click_publish(self, page, *, deadline: float | None = None, multilogin: bool = False):
        # ``publish_clicked`` flips only after ``click()`` returns cleanly; a
        # click that raises proves nothing was sent.  Once flipped, the button
        # is never clicked again: a second click could duplicate the post.
        publish_clicked = False
        while True:
            try:
                self._check_publish_deadline(deadline)
            except RuntimeError:
                if publish_clicked:
                    # A login redirect still wins over "result unknown".
                    if multilogin:
                        _raise_if_login_required(page)
                    raise PublishResultUnknownError(
                        _PUBLISH_RESULT_UNKNOWN_MESSAGE
                    ) from None
                raise RuntimeError(_PRE_PUBLISH_TIMEOUT_MESSAGE) from None

            if multilogin:
                _raise_if_login_required(page)

            if not publish_clicked:
                try:
                    publish_button = self.locator_base.locator('div.button-group button').nth(0)
                    if await publish_button.count():
                        await publish_button.click()
                        publish_clicked = True
                except Exception as e:
                    if multilogin:
                        _raise_if_login_required(page)
                    tiktok_logger.exception(f"  [-] Exception: {e}")
                    tiktok_logger.info("  [-] video publishing")
                    await asyncio.sleep(0.5)
                    continue

            try:
                await page.wait_for_url("https://www.tiktok.com/tiktokstudio/content",  timeout=3000)
            except (PlaywrightTimeoutError, TimeoutError):
                tiktok_logger.info("  [-] video publishing")
                await asyncio.sleep(0.5)
                continue
            except Exception as e:
                if multilogin:
                    _raise_if_login_required(page)
                if publish_clicked:
                    # Page/context closed, CDP dropped, or a form error after
                    # the click: stop at once instead of spinning to deadline.
                    raise PublishResultUnknownError(
                        _PUBLISH_RESULT_UNKNOWN_MESSAGE
                    ) from e
                tiktok_logger.exception(f"  [-] Exception: {e}")
                tiktok_logger.info("  [-] video publishing")
                await asyncio.sleep(0.5)
                continue

            tiktok_logger.success("  [-] video published success")
            return

    async def choose_base_locator(self, page):
        # await page.wait_for_selector('div.upload-container')
        if await page.locator('iframe[data-tt="Upload_index_iframe"]').count():
            self.locator_base = page.frame_locator(Tk_Locator.tk_iframe)
        else:
            self.locator_base = page.locator(Tk_Locator.default)

    async def read_result(self, page):
        raise NotImplementedError


class TiktokVideo(TiktokBaseUploader):
    def __init__(
        self,
        title,
        file_path,
        tags,
        publish_date,
        account_file,
        thumbnail_path=None,
        *,
        options: TiktokPublishOptions | None = None,
    ):
        self.title = title
        self.file_path = file_path
        self.tags = tags
        self.publish_date = publish_date
        self.thumbnail_path = thumbnail_path
        self.account_file = account_file
        self.options = options
        self.local_executable_path = LOCAL_CHROME_PATH
        self.headless = LOCAL_CHROME_HEADLESS
        self.locator_base = None

    async def handle_upload_error(self, page):
        tiktok_logger.info("video upload error retrying.")
        select_file_button = self.locator_base.locator('button[aria-label="Select file"]')
        async with page.expect_file_chooser() as fc_info:
            await select_file_button.click()
        file_chooser = await fc_info.value
        await file_chooser.set_files(self.file_path)

    async def upload(self, playwright: Playwright | None, *, session: BrowserSession | None = None) -> None:
        if session is not None:
            await self.upload_in(session)
            return

        if playwright is None:
            raise ValueError("本地模式需要 Playwright 实例")

        browser = await playwright.chromium.launch(headless=self.headless, **TIKTOK_LAUNCH_KWARGS)
        context = await browser.new_context(
            storage_state=f"{self.account_file}",
            **TIKTOK_CONTEXT_KWARGS,
        )
        if TIKTOK_INIT_SCRIPT:
            context = await set_init_script(context)
        page = await context.new_page()

        # change language to eng first (local only; Multilogin Profiles must
        # already be English (US), see the deployment prerequisite above)
        await self.change_language(page)
        await self._upload_on_page(page, multilogin=False, deadline=None)

        await context.storage_state(path=f"{self.account_file}")  # save cookie
        tiktok_logger.info('  [-] update cookie！')
        await asyncio.sleep(2)  # close delay for look the video status
        # close all
        await context.close()
        await browser.close()

    async def attach_media(self, page) -> None:
        upload_button = self.locator_base.locator(
            'button:has-text("Select video"):visible')
        await upload_button.wait_for(state='visible')  # 确保按钮可见

        async with page.expect_file_chooser() as fc_info:
            await upload_button.click()
        file_chooser = await fc_info.value
        await file_chooser.set_files(self.file_path)

    async def fill_metadata(self, page) -> None:
        await self.fill_caption(page, self.title, self.tags)

    async def apply_cover(self, page) -> None:
        if not self.thumbnail_path:
            return
        tiktok_logger.info(f'[+] Uploading thumbnail file {self.title}.png')
        base = self.locator_base

        edit_cover = await _resolve_candidate(
            base,
            _COVER_EDIT_CANDIDATES,
            control="Edit cover",
            stage="open cover editor",
            page=page,
        )
        await edit_cover.click()

        upload_tab = await _resolve_candidate(
            base,
            _COVER_UPLOAD_TAB_CANDIDATES,
            control="Upload cover",
            stage="select upload tab",
            page=page,
        )
        await upload_tab.click()

        # Scope the broad fallback input to the cover editor so it cannot hit
        # the main form's video input.  When the ancestor is not found the
        # aria-labelled candidate above is still tried against the base.
        editor_query = upload_tab.locator(COVER_EDITOR_SCOPE_SELECTOR)
        try:
            editor = editor_query.first if await editor_query.count() else None
        except Exception:
            editor = None
        control_scope = editor if editor is not None else base

        file_candidates = (
            (_COVER_FILE_ARIA_SELECTOR,
             lambda _scope: control_scope.locator(_COVER_FILE_ARIA_SELECTOR)),
            # When the cover editor root is unavailable the scoped fallback is
            # left unmatched rather than widening to the whole form.
            (_COVER_FILE_ACCEPT_SELECTOR,
             lambda _scope: (
                 editor.locator(_COVER_FILE_ACCEPT_SELECTOR)
                 if editor is not None
                 else editor_query
             )),
        )
        file_input = await _resolve_candidate(
            base,
            file_candidates,
            control="Upload cover file input",
            stage="set cover file",
            page=page,
        )
        try:
            # The input is hidden but ``set_input_files`` works on it directly.
            await file_input.set_input_files(self.thumbnail_path)
        except Exception as exc:
            # Last resort: keep the legacy file-chooser pattern.
            try:
                async with page.expect_file_chooser() as fc_info:
                    await file_input.click(force=True)
                file_chooser = await fc_info.value
                await file_chooser.set_files(self.thumbnail_path)
            except Exception:
                raise _cover_error(
                    "Upload cover file input",
                    "set cover file",
                    file_candidates,
                    page,
                    detail=f"set_input_files failed: {exc}",
                ) from exc

        save_button = await _resolve_candidate(
            control_scope,
            _COVER_SAVE_CANDIDATES,
            control="Save",
            stage="save cover",
            page=page,
        )

        preview = await _find_candidate(control_scope, _COVER_PREVIEW_CANDIDATES)
        preview_visible = False
        if preview is not None:
            preview_locator, index, description = preview
            tiktok_logger.info(
                f"[+] cover wait for cover preview: Uploaded cover image "
                f"candidate {index + 1}/{len(_COVER_PREVIEW_CANDIDATES)}"
                f" matched ({description})"
            )
            try:
                await preview_locator.wait_for(
                    state="visible", timeout=_COVER_PREVIEW_TIMEOUT_MS
                )
                preview_visible = True
            except Exception:
                preview_visible = False

        if not preview_visible and not await save_button.is_enabled():
            raise _cover_error(
                "Uploaded cover image",
                "wait for cover preview",
                _COVER_PREVIEW_CANDIDATES,
                page,
            )

        try:
            await save_button.click()
        except Exception as exc:
            raise _cover_error(
                "Save",
                "save cover",
                _COVER_SAVE_CANDIDATES,
                page,
                detail=str(exc),
            ) from exc

        await page.wait_for_timeout(3000)  # wait 3s, fix it later

    async def change_language(self, page):
        # set the language to english
        await page.goto("https://www.tiktok.com")
        await page.wait_for_load_state('domcontentloaded')
        await page.wait_for_selector('[data-e2e="nav-more-menu"]')
        # 已经设置为英文, 省略这个步骤
        if await page.locator('[data-e2e="nav-more-menu"]').text_content() == "More":
            return

        await page.locator('[data-e2e="nav-more-menu"]').click()
        await page.locator('[data-e2e="language-select"]').click()
        await page.locator('#creator-tools-selection-menu-header >> text=English (US)').click()

    async def read_result(self, page):
        await page.wait_for_selector('div[data-tt="components_PostTable_Container"]')
        video_list_locator = self.locator_base.locator('div[data-tt="components_PostTable_Container"] div[data-tt="components_PostInfoCell_Container"] a')
        if await video_list_locator.count():
            first_video_obj = await video_list_locator.nth(0).get_attribute('href')
            video_id = re.search(r'video/(\d+)', first_video_obj).group(1) if first_video_obj else None
            return video_id

    async def wait_media_ready(self, page, *, deadline: float | None = None, multilogin: bool = False):
        while True:
            self._check_publish_deadline(deadline)
            if multilogin:
                _raise_if_login_required(page)
            try:
                # if await self.locator_base.locator('div.btn-post > button').get_attribute("disabled") is None:
                if await self.locator_base.locator(
                        'div.button-group > button >> text=Post').get_attribute("disabled") is None:
                    tiktok_logger.info("  [-]video uploaded.")
                    break
                else:
                    tiktok_logger.info("  [-] video uploading...")
                    await asyncio.sleep(2)
                    if await self.locator_base.locator(
                            'button[aria-label="Select file"]').count():
                        tiktok_logger.info("  [-] found some error while uploading now retry...")
                        await self.handle_upload_error(page)
            except Exception:
                if multilogin:
                    _raise_if_login_required(page)
                tiktok_logger.info("  [-] video uploading...")
                await asyncio.sleep(2)

    async def main(self):
        async with async_playwright() as playwright:
            await self.upload(playwright)


class TiktokNote(TiktokBaseUploader):
    """TikTok Studio photo post (1–35 images, first image is the cover).

    Ticket 15 ships the core upload path only.  ``note``/``tags``/``title`` and
    ``options`` are stored now so ticket 16 can fill the metadata and option
    steps without changing the constructor again.
    """

    upload_url = TIKTOK_PHOTO_UPLOAD_URL

    _PHOTO_TITLE_SELECTOR = 'input[placeholder*="catchy"]'
    _PHOTO_TITLE_CANDIDATES = (
        'input[placeholder*="catchy"]',
        'input[placeholder="Add a catchy title"]',
    )
    _PHOTO_CAPTION_CANDIDATES = (
        "div.caption-textarea div.public-DraftEditor-content",
        "div.public-DraftEditor-content",
    )
    _PHOTO_INPUT_SELECTOR = 'input[type="file"][accept*="image"]'
    _MULTI_INPUT_SELECTOR = 'input[type="file"][multiple]'
    _POST_BUTTON_SELECTOR = 'div.button-group > button >> text=Post'
    _CONTENT_CONTAINER_SELECTOR = 'div[data-tt="components_PostTable_Container"]'
    _PHOTO_LINK_SELECTOR = 'a[href*="/post/photo?item_id="]'
    _PHOTOS_TAB = "Photos"

    def __init__(
        self,
        image_paths,
        note,
        tags,
        publish_date,
        account_file,
        *,
        title=None,
        options=None,
        debug=True,
        headless=True,
    ):
        self.image_paths = list(image_paths)
        self.note = note
        self.tags = tags
        self.publish_date = publish_date
        self.account_file = account_file
        self.title = title
        self.options = options
        self.debug = debug
        self.headless = headless
        self.local_executable_path = LOCAL_CHROME_PATH
        self.locator_base = None
        self.last_item_id = None

    def media_label(self) -> str:
        return f"{len(self.image_paths)} images"

    def result_label(self, item_id) -> str:
        return f"photo post id: {item_id}"

    async def _photo_form_present(self, page) -> bool:
        for selector in (
            self._PHOTO_TITLE_SELECTOR,
            self._PHOTO_INPUT_SELECTOR,
        ):
            try:
                if await page.locator(selector).count() > 0:
                    return True
            except Exception:
                continue
        return False

    async def ensure_mode(self, page) -> None:
        """Require the photo form *before* any file selection.

        ``?tab=photo`` normally lands straight on the photo composer.  If the
        form is not rendered yet, click the ``Photos`` tab once and re-check.
        A missing form means the account is outside the rollout: fail instead
        of feeding images into the video input.
        """
        if await self._photo_form_present(page):
            return

        clicked = False
        get_by_text = getattr(page, "get_by_text", None)
        if callable(get_by_text):
            try:
                tab = get_by_text(self._PHOTOS_TAB, exact=True).first
                if await tab.count() > 0:
                    await tab.click()
                    clicked = True
            except Exception:
                pass

        if not clicked:
            get_by_role = getattr(page, "get_by_role", None)
            if callable(get_by_role):
                try:
                    tab = get_by_role("tab", name=self._PHOTOS_TAB).first
                    if await tab.count() > 0:
                        await tab.click()
                        clicked = True
                except Exception:
                    pass

        if clicked and await self._photo_form_present(page):
            return

        raise RuntimeError(
            "Photos tab 未覆盖当前账号：上传页没有图片发帖入口，"
            "已在选择文件前中止（不会改用视频 input）。"
        )

    async def attach_media(self, page) -> None:
        selector = self._PHOTO_INPUT_SELECTOR
        try:
            present = await page.locator(selector).count()
        except Exception:
            present = 0
        if not present:
            selector = self._MULTI_INPUT_SELECTOR
        # ``image_paths`` order is the display order; the first one is the cover.
        await page.locator(selector).first.set_input_files(list(self.image_paths))

    async def _resolve_photo_scope(self, page):
        return self.locator_base if self.locator_base is not None else page

    async def _fill_title(self, page) -> None:
        scope = await self._resolve_photo_scope(page)
        for selector in self._PHOTO_TITLE_CANDIDATES:
            locator = scope.locator(selector)
            try:
                if await locator.count() > 0:
                    await locator.first.fill(self.title)
                    return
            except Exception:
                continue
        raise RuntimeError(
            "TikTok 图文帖 Title 输入框未找到："
            f"tried={list(self._PHOTO_TITLE_CANDIDATES)!r} "
            f"url={_page_url(page)!r}"
        )

    async def _resolve_caption_editor(self, page):
        scope = await self._resolve_photo_scope(page)
        for selector in self._PHOTO_CAPTION_CANDIDATES:
            locator = scope.locator(selector)
            try:
                if await locator.count() > 0:
                    return locator
            except Exception:
                continue
        raise RuntimeError(
            "TikTok 图文帖 Description 编辑器未找到："
            f"tried={list(self._PHOTO_CAPTION_CANDIDATES)!r} "
            f"url={_page_url(page)!r}"
        )

    async def fill_metadata(self, page) -> None:
        """Fill the photo Title and Description; images are never touched here.

        An absent Title/Description is left exactly as the page rendered it: no
        empty-string write and no editor interaction at all.
        """
        if self.title:
            await self._fill_title(page)

        note_text = self.note or ""
        tags = list(self.tags or [])
        if not note_text and not tags:
            return

        editor = await self._resolve_caption_editor(page)
        await self.fill_caption(page, note_text, tags, editor=editor)

    async def apply_options(self, page) -> None:
        """Reuse the shared option steps, minus the content-reuse control.

        Photo posts do not render ``Allow reuse of content``; even a stray
        ``allow_reuse`` value must never resolve, read or click that control.
        """
        options = getattr(self, "options", None)
        if options is None:
            await super().apply_options(page)
            return

        sanitized = replace(options, allow_reuse=None)
        original = self.options
        try:
            self.options = sanitized
            await super().apply_options(page)
        finally:
            self.options = original

    async def wait_media_ready(
        self,
        page,
        *,
        deadline: float | None = None,
        multilogin: bool = False,
    ) -> None:
        while True:
            self._check_publish_deadline(deadline)
            if multilogin:
                _raise_if_login_required(page)
            try:
                processed = await page.locator("div[data-id]").count() > 0
                if not processed:
                    try:
                        processed = (
                            await page.get_by_text(
                                "Cover", exact=True
                            ).count()
                            > 0
                        )
                    except Exception:
                        processed = False

                post_enabled = (
                    await self.locator_base.locator(
                        self._POST_BUTTON_SELECTOR
                    ).get_attribute("disabled")
                    is None
                )
                if processed and post_enabled:
                    tiktok_logger.info("  [-] photos uploaded.")
                    return
            except Exception:
                if multilogin:
                    _raise_if_login_required(page)

            tiktok_logger.info("  [-] photos uploading...")
            await asyncio.sleep(2)

    async def read_result(self, page):
        try:
            await page.wait_for_selector(self._CONTENT_CONTAINER_SELECTOR)
        except Exception as exc:
            raise RuntimeError(
                "TikTok 图文帖发布结果未知：未找到内容列表容器。"
            ) from exc

        photo_links = page.locator(self._PHOTO_LINK_SELECTOR)
        if await photo_links.count():
            href = await photo_links.nth(0).get_attribute("href")
            match = re.search(r"item_id=(\d+)", href or "")
            if match:
                return match.group(1)

        raise RuntimeError(
            "TikTok 图文帖发布结果未知：未找到 "
            '/post/photo?item_id= 链接。'
        )

    async def upload(
        self, playwright: Playwright | None, *, session: BrowserSession | None = None
    ) -> None:
        if session is None:
            raise RuntimeError(
                "TikTok 仅支持 Multilogin 模式：图文帖没有本地浏览器路径。"
            )
        await self.upload_in(session)
