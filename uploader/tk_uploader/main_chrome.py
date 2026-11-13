# -*- coding: utf-8 -*-
import re
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime

# Multilogin runs on the same Patchright client as every other uploader.
# ``main.py`` (Firefox) intentionally stays on upstream Playwright and is not
# wired into the CLI.
from patchright.async_api import Error as PlaywrightError
from patchright.async_api import Playwright, async_playwright
from patchright.async_api import TimeoutError as PlaywrightTimeoutError
import os
import asyncio

from conf import LOCAL_CHROME_PATH, LOCAL_CHROME_HEADLESS
from uploader.base_video import BaseVideoUploader
from uploader.publish_timeout import PublishTimeoutBudget
from uploader.tk_uploader.tk_config import (
    TIKTOK_ENTRY_WAIT_MS,
    TIKTOK_IMAGE_SUFFIXES,
    TIKTOK_LOCAL_ENTRY_WAIT_MS,
    TIKTOK_OVERLAY_CLICK_TIMEOUT_MS,
    TIKTOK_LOGIN_CHECK_TIMEOUT_MS,
    TIKTOK_LOGIN_CHECK_URL,
    TIKTOK_LOGIN_FORM_SELECTOR,
    TIKTOK_MAX_DESCRIPTION_LENGTH,
    TIKTOK_MAX_HASHTAG_COUNT,
    TIKTOK_MAX_IMAGE_BYTES,
    TIKTOK_MAX_IMAGE_COUNT,
    TIKTOK_MAX_TITLE_LENGTH,
    TIKTOK_PHOTO_UPLOAD_URL,
    TIKTOK_UPLOAD_ENTRY_SELECTOR,
    TIKTOK_UPLOAD_URL,
    Tk_Locator,
)
from utils.base_social_media import set_init_script
from utils.browser_session import BrowserSession
from uploader.tk_uploader.schedule import prepare_schedule
from utils.errors import LoginRequiredError, PublishResultUnknownError
from utils.files_times import get_absolute_path
from utils.humanize import DEFAULT_PROFILE
from utils.humanize import MAYBE_DISPATCHED
from utils.humanize import MAYBE_DISPATCHED_VALUE
from utils.humanize import Humanizer
from utils.log import tiktok_logger

# Multilogin deployment prerequisite: the Profile UI must already be English
# (US).  The MLX branch deliberately skips ``change_language`` so it never
# rewrites the Profile preference.

# Golden local-mode browser options.  The Multilogin branch ignores them, but
# locking them here keeps the legacy Chromium path byte-equivalent.
# An empty LOCAL_CHROME_PATH means "use the Chromium bundled with Patchright";
# passing executable_path="" makes Playwright try to spawn ``.`` and fail.
TIKTOK_LAUNCH_KWARGS = (
    {"executable_path": LOCAL_CHROME_PATH} if LOCAL_CHROME_PATH else {}
)
# Local mode should not depend on the operator's OS language.  MLX ignores
# these kwargs and uses the Profile's own English (US) configuration.
TIKTOK_CONTEXT_KWARGS: dict = {"locale": "en-US"}
TIKTOK_INIT_SCRIPT = False

_LOGIN_URL_MARKERS = ("/login", "captcha", "verify", "two-factor", "2fa")
TIKTOK_RESULT_READ_TIMEOUT_MS = 30_000
TIKTOK_HASHTAG_SUGGESTION_TIMEOUT_MS = 3_000
TIKTOK_HASHTAG_SETTLE_MS = 600
#: ``--no-publish`` dry run: upper bound for the publish-ready wait.  It is
#: also clamped by whatever remains of the shared publish budget.
TIKTOK_DRY_RUN_READY_TIMEOUT_MS = 60_000
TIKTOK_DRY_RUN_POLL_MS = 500
TIKTOK_DRY_RUN_READY_MESSAGE = (
    "TikTok 发布就绪，--no-publish 停在发布按钮前（未点击发布）"
)

#: 发布点击循环的硬上限：预算之外的第二道闸。正常路径由 15 分钟预算终止；
#: 结果轮询的硬上限：只在 sleep 被吞掉（测试替身）时兜底，避免全速空转。
TIKTOK_PUBLISH_MAX_LOOP_ITERATIONS = 2000

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
#: Short, read-only probe for an already-attached cover image input.  The tab
#: click (and its consumed file chooser) is the fallback, never the first move.
_COVER_INPUT_PROBE_TIMEOUT_MS = 2_000
#: Bound for the tab click's file-chooser event, and the settle that lets the
#: click reveal the input when no chooser arrives.
_COVER_CHOOSER_TIMEOUT_MS = 10_000
_COVER_TAB_SETTLE_MS = 1_500

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
    ('[role="dialog"] role=button[name=/^Turn on$/]',
     lambda page: page.locator('[role="dialog"]').get_by_role(
         "button", name=re.compile(r"^Turn on$")
     )),
    ('.TUXModal role=button[name=/^Turn on$/]',
     lambda page: page.locator('.TUXModal').get_by_role(
         "button", name=re.compile(r"^Turn on$")
     )),
)
_AIGC_DIALOG_TIMEOUT_MS = 5_000


def _maybe_dispatched(exc: BaseException) -> bool:
    """Whether a click may already have reached the page (spec §2.1)."""
    return getattr(exc, MAYBE_DISPATCHED, None) == MAYBE_DISPATCHED_VALUE


def _offline_humanizer() -> Humanizer:
    """Fast-path humanizer for controls built without a page (test seams).

    Production always passes the page-backed instance; this branch exists only
    so a control constructed directly in an offline test can still be
    activated without emitting an unmarked native ``click``.

    Disabling goes through the documented profile rule (a derived
    ``DEFAULT_PROFILE``), never a post-construction ``enabled = False``:
    ``Humanizer`` snapshots ``enabled`` in ``__init__``.
    """
    return Humanizer(None, profile=replace(DEFAULT_PROFILE, enabled=False))


async def _humanized_click(humanizer: Humanizer | None, target) -> None:
    """The module's only click entry: hover the target, then click it (§2.5.1).

    TikTok Studio animates/hover-expands most controls (option rows, dialogs,
    date pickers, the cover editor, tabs), so this is the platform-wide policy,
    not just the option adapters.

    Two 2026-11-13 real-device ``--no-publish`` runs failed inside
    ``Humanizer.click`` with ``ElementUnusableError(reason="point-drift")``:
    first on the first option applied (privacy), then on the AIGC first-run
    dialog's ``Turn on`` button.  Hovering the call site's target first settles
    the pointer before the click's own move/stillOn check.  The click primitive
    keeps zero retries and its ±1px tolerance; the fast path still passes
    ``hover`` through to ``locator.hover()``.
    """
    if humanizer is None:
        humanizer = _offline_humanizer()
    await humanizer.hover(target)
    await humanizer.click(target)


async def _label_body(target):
    """Click the wrapping label (the real pointer target) when one exists."""
    try:
        query = target.locator("xpath=ancestor-or-self::label[1]")
        if await query.count():
            return query.first
    except Exception:
        pass
    return target


def _find_scheduled_row_marker(
    body: str, values: tuple[str, ...]
) -> str | None:
    """Return the first title/note value that appears in the Content list.

    Verification is timezone-agnostic on purpose: Studio may render the
    scheduled time in PST/EST/GMT or another account timezone, so the row is
    identified by title/note only.  The schedule value itself was already
    read back from the picker before the publish click.
    """
    for value in values:
        if value in body:
            return value
    return None


async def _find_candidate(scope, candidates, *, visible: bool = False):
    """Return ``(locator, index, description)`` for the first present candidate.

    When ``visible`` is true every match is checked, not just ``.first``: a
    hidden duplicate earlier in the list must not mask the visible control.
    A locator double that does not implement ``is_visible`` is treated as
    visible so the pure in-memory tests stay minimal.
    """
    for index, (description, factory) in enumerate(candidates):
        try:
            locator = factory(scope)
            count = await locator.count()
            if not count:
                continue
            if visible:
                nth = getattr(locator, "nth", None)
                if callable(nth):
                    for position in range(count):
                        candidate = nth(position)
                        is_visible = getattr(candidate, "is_visible", None)
                        if not callable(is_visible):
                            return candidate, index, description
                        try:
                            if await is_visible():
                                return candidate, index, description
                        except Exception:
                            continue
                    continue
                first = getattr(locator, "first", locator)
                is_visible = getattr(first, "is_visible", None)
                if callable(is_visible):
                    try:
                        if not await is_visible():
                            continue
                    except Exception:
                        continue
                return first, index, description
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


async def _resolve_candidate(
    scope, candidates, *, control, stage, page, visible: bool = False
):
    found = await _find_candidate(scope, candidates, visible=visible)
    if found is None:
        raise _cover_error(control, stage, candidates, page)
    locator, index, description = found
    tiktok_logger.info(
        f"[+] cover {stage}: {control} candidate {index + 1}/{len(candidates)}"
        f" matched ({description})"
    )
    return locator


async def _probe_cover_file_input(scope, candidates):
    """Return the cover image input when it is already attached, else ``None``.

    Read-only by design: it never clicks the upload tab, because that click
    opens a real OS file chooser that then lingers while ``set_input_files``
    injects the file (XHS precedent, bbc5361).  Candidates are tried in order,
    so a later-scoped selector still proves the input is attached.
    """
    found = await _find_candidate(scope, candidates)
    if found is None:
        return None
    locator, index, description = found
    try:
        await locator.wait_for(
            state="attached", timeout=_COVER_INPUT_PROBE_TIMEOUT_MS
        )
    except Exception:
        return None
    tiktok_logger.info(
        "[+] cover probe cover file: Upload cover file input candidate "
        f"{index + 1}/{len(candidates)} matched ({description})"
    )
    return locator


_PUBLISH_RESULT_UNKNOWN_MESSAGE = (
    "TikTok 发布结果未知：发布点击已发出，但未观察到成功页，"
    "也未命中登录/验证码跳转；帖子可能已经发布。\n"
    "禁止自动重发。请先人工核验：TikTok Studio → Content/Posts，"
    "按标题与发布时间核对；已存在则不要重发，不存在才可人工重试。"
)

_PRE_PUBLISH_TIMEOUT_MESSAGE = (
    "TikTok 发布超时（15 分钟）：尚未点击发布，未发布任何内容。"
)

# Publish button candidates, in spec §5.2/§5.3 order.  The legacy
# ``button:has-text("Post").last`` / ``button-group nth(0)`` candidates were
# removed: substring matching also hits ``Post now``/``Posts`` and the first
# button-group entry can be Discard, which latched ``publish_clicked`` and
# ended in a false exit 9.
_PUBLISH_BUTTON_CANDIDATES = (
    (
        'data-e2e=post_video_button',
        lambda base: base.locator('[data-e2e="post_video_button"]'),
    ),
    (
        'role=button[name=/^(Post|Schedule)$/]',
        lambda base: base.get_by_role(
            "button", name=re.compile(r"^(Post|Schedule)$")
        ),
    ),
)


def _confirmation_names(publish_date) -> tuple[str, ...]:
    """Exact confirmation button names, in priority order.

    Current Studio uses a generic ``Post now`` confirm button even when the
    post is scheduled (the schedule radio keeps its value).  A bare
    ``Confirm`` is deliberately not accepted: an unrelated dialog's Confirm
    must never be treated as the publish confirmation.
    """
    if not publish_date:
        return ("Post now",)
    return ("Schedule", "Post now")


_CONFIRMATION_DIALOG_SELECTORS = ('[role="dialog"]', '.TUXModal')
_COVER_EDITOR_CLOSE_TIMEOUT_MS = 10_000

# Appended to the login-required text only when the publish click was already
# dispatched: retrying then can duplicate the post (mirror of XHS §4 wording).
_TIKTOK_PUBLISH_ATTEMPTED_SUFFIX = (
    "发布点击已发出：请先在作品列表核对是否已发布，再决定是否重试。"
)

# Video file chooser entry, in spec §5.2 step 2 order.
_VIDEO_FILE_WAIT_MS = 30_000
_VIDEO_FILE_CANDIDATES = (
    (
        'data-e2e=select_video_button',
        lambda base: base.locator('[data-e2e="select_video_button"]'),
    ),
    (
        'button:has-text("Select video"):visible',
        lambda base: base.locator('button:has-text("Select video"):visible'),
    ),
    (
        'button[aria-label="Select file"]',
        lambda base: base.locator('button[aria-label="Select file"]'),
    ),
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
    "only me": "only-me",
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


def _classes_mark_disabled(classes: str | None) -> bool:
    """Interpret BEM/TUX disabled classes without the ``--disabled-false`` trap."""
    tokens = (classes or "").casefold().split()
    return any(
        token == "disabled"
        or token.endswith("--disabled")
        or "disabled-true" in token
        for token in tokens
    )


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

    async def is_visible(self) -> bool:
        return True

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

    def __init__(
        self,
        locator,
        *,
        candidates: tuple[str, ...] = (),
        humanizer: Humanizer | None = None,
    ) -> None:
        self._locator = locator
        self.candidates = candidates
        self._humanizer = humanizer

    async def _target(self):
        """Return the first visible element of a possibly-multi locator.

        Option factories no longer append ``.first`` so a hidden responsive
        duplicate cannot mask the visible control.
        """
        locator = self._locator
        total = 0
        count = getattr(locator, "count", None)
        if callable(count):
            try:
                total = await count()
            except Exception:
                total = 0
        if total > 1:
            nth = getattr(locator, "nth", None)
            if callable(nth):
                for index in range(total):
                    node = nth(index)
                    is_visible = getattr(node, "is_visible", None)
                    if not callable(is_visible):
                        return node
                    try:
                        if await is_visible():
                            return node
                    except Exception:
                        continue
        first = getattr(locator, "first", None)
        return first if first is not None else locator

    async def is_checked(self) -> bool:
        target = await self._target()
        try:
            return bool(await target.is_checked())
        except Exception as original:
            # The brand fallback candidate may resolve to the text/label node
            # instead of the checkbox input.  Read the nested checkbox when one
            # exists, then fall back to an ARIA state; otherwise re-raise so the
            # caller can attach option/context data.
            try:
                nested = target.locator('input[type="checkbox"]')
                if await nested.count():
                    return bool(await nested.first.is_checked())
            except Exception:
                pass
            try:
                aria = await target.get_attribute("aria-checked")
                if aria is not None:
                    return str(aria).lower() == "true"
            except Exception:
                pass
            raise original

    async def is_disabled(self) -> bool:
        target = await self._target()
        try:
            if await target.is_disabled():
                return True
        except Exception:
            pass
        # A label candidate wraps the native checkbox; read the input too.
        try:
            nested = target.locator('input[type="checkbox"]')
            if await nested.count():
                if await nested.first.is_disabled():
                    return True
        except Exception:
            pass
        aria = await target.get_attribute("aria-disabled")
        if str(aria).lower() == "true":
            return True
        classes = ((await target.get_attribute("class")) or "").casefold()
        return _classes_mark_disabled(classes)

    async def is_visible(self) -> bool:
        target = await self._target()
        try:
            return bool(await target.is_visible())
        except Exception:
            return True

    async def click(self) -> None:
        # Click the label body, never the often-invisible native checkbox.
        # The old ``force=True`` retry is gone: a stillOn failure is a hard
        # error, not a reason to dispatch a synthetic click.
        target = await _label_body(await self._target())
        await _humanized_click(self._humanizer, target)

    async def get_attribute(self, name: str) -> str | None:
        target = await self._target()
        return await target.get_attribute(name)

    async def read_text(self) -> str:
        target = await self._target()
        return (await target.inner_text()).strip()

    async def count(self) -> int:
        return await self._locator.count()


class _LocatorPrivacyControl(TiktokOptionControl):
    """Visibility combobox adapter: trigger text plus its option list."""

    def __init__(
        self,
        trigger,
        option_scope,
        *,
        candidates: tuple[str, ...] = (),
        fallback_scope=None,
        humanizer: Humanizer | None = None,
    ) -> None:
        self._trigger = trigger
        self._option_scope = option_scope
        self._fallback_scope = fallback_scope
        self.candidates = candidates
        self._humanizer = humanizer

    async def _target(self):
        """First visible trigger of a possibly-multi locator."""
        locator = self._trigger
        total = 0
        count = getattr(locator, "count", None)
        if callable(count):
            try:
                total = await count()
            except Exception:
                total = 0
        if total > 1:
            nth = getattr(locator, "nth", None)
            if callable(nth):
                for index in range(total):
                    node = nth(index)
                    is_visible = getattr(node, "is_visible", None)
                    if not callable(is_visible):
                        return node
                    try:
                        if await is_visible():
                            return node
                    except Exception:
                        continue
        first = getattr(locator, "first", None)
        return first if first is not None else locator

    async def is_checked(self) -> bool:
        return False

    async def is_disabled(self) -> bool:
        target = await self._target()
        try:
            if await target.is_disabled():
                return True
        except Exception:
            pass
        classes = (await target.get_attribute("class")) or ""
        return _classes_mark_disabled(classes)

    async def is_visible(self) -> bool:
        target = await self._target()
        try:
            return bool(await target.is_visible())
        except Exception:
            return True

    async def click(self) -> None:
        await _humanized_click(self._humanizer, await self._target())

    async def get_attribute(self, name: str) -> str | None:
        target = await self._target()
        return await target.get_attribute(name)

    async def read_text(self) -> str:
        target = await self._target()
        return (await target.inner_text()).strip()

    async def options(self) -> list[TiktokOptionControl]:
        # Current Studio renders options as ``div[role="option"]`` in a portal
        # outside the visibility container.  Try the container first, then the
        # page/frame root.  Match by role, not tag.
        locator = self._option_scope.locator('[role="option"]')
        count = await locator.count()
        if count == 0 and self._fallback_scope is not None:
            locator = self._fallback_scope.locator('[role="option"]')
            count = await locator.count()
        return [
            _LocatorControl(locator.nth(i), humanizer=self._humanizer)
            for i in range(count)
        ]

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
    detail: str | None = None,
    candidates: tuple[str, ...] | None = None,
) -> RuntimeError:
    if candidates is None:
        candidates = tuple(getattr(control, "candidates", ()) or ())
    suffix = f" detail={detail}" if detail else ""
    return RuntimeError(
        "TikTok 发布选项设置失败："
        f"option={option} stage={stage} requested={requested!r} "
        f"actual={actual!r} candidates={candidates!r} url={url!r}{suffix}"
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


async def _guarded_state(
    read,
    control: TiktokOptionControl,
    *,
    option: str,
    stage: str,
    requested,
    url: str,
) -> bool:
    """Run a state reader and attach option context to any low-level error."""
    try:
        return await read(control)
    except Exception as exc:
        raise _option_error(
            option=option,
            stage=stage,
            requested=requested,
            actual="read-error",
            control=control,
            url=url,
            detail=str(exc),
        ) from exc


async def _set_toggle_option(
    control: TiktokOptionControl,
    requested: bool,
    *,
    option: str,
    url: str,
) -> None:
    current = await _guarded_state(
        _read_toggle_state,
        control,
        option=option,
        stage="read",
        requested=requested,
        url=url,
    )
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
    await control.click()  # native-click: manage；控件底座内部走 Humanizer
    actual = await _guarded_state(
        _read_toggle_state,
        control,
        option=option,
        stage="readback",
        requested=requested,
        url=url,
    )
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
    current = await _guarded_state(
        _read_switch_state,
        control,
        option=option,
        stage="read",
        requested=requested,
        url=url,
    )
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
    await control.click()  # native-click: manage；控件底座内部走 Humanizer
    actual = await _guarded_state(
        _read_switch_state,
        control,
        option=option,
        stage="readback",
        requested=requested,
        url=url,
    )
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

    await control.click()  # native-click: manage；控件底座内部走 Humanizer
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

    await matched.click()  # native-click: manage；控件底座内部走 Humanizer
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


def _raise_if_login_required(page, *, publish_attempted: bool = False) -> None:
    """Map a mid-upload login/captcha/2FA redirect to ``LoginRequiredError``.

    Only the Multilogin branch calls this. Local mode keeps its historical
    retry-until-timeout behaviour. ``publish_attempted`` must be true when the
    redirect is observed after the publish click was dispatched, so exit 10
    never claims "not published" and the text never invites a blind retry.
    """
    url = str(getattr(page, "url", "") or "").lower()
    if not url:
        return
    path = url.split("?", 1)[0]
    if any(marker in path for marker in _LOGIN_URL_MARKERS):
        message = (
            "TikTok 上传过程中需要重新登录（登录页/验证码/二次验证）："
            "请在 Multilogin 应用中登录 Profile 后重试。"
        )
        if publish_attempted:
            message += _TIKTOK_PUBLISH_ATTEMPTED_SUFFIX
        raise LoginRequiredError(
            message,
            publish_attempted=publish_attempted,
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


async def _new_local_context(browser, *, storage_state, attempts: int = 3):
    """Create a local context, retrying Playwright's storage-state race.

    ``new_context(storage_state=...)`` can transiently fail with
    "Execution context was destroyed" while Playwright restores localStorage.
    """
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            return await browser.new_context(
                storage_state=str(storage_state),
                **TIKTOK_CONTEXT_KWARGS,
            )
        except (PlaywrightError, OSError) as exc:
            last_exc = exc
            tiktok_logger.warning(
                "[+] TikTok local context creation failed "
                f"({attempt}/{attempts}): {exc}"
            )
            await asyncio.sleep(1)
    raise last_exc


async def cookie_auth(account_file, *, headless: bool = LOCAL_CHROME_HEADLESS) -> bool:
    """Validate a local cookie file against TikTok Studio.

    Any Playwright/launch/read error is reported as invalid rather than raised,
    so ``check`` always prints ``invalid`` and exits ``1``.
    """
    try:
        return await _cookie_auth(account_file, headless=headless)
    except (PlaywrightError, OSError, ValueError) as exc:
        tiktok_logger.error(f"[+] cookie check failed: {exc}")
        return False


async def _cookie_auth(account_file, *, headless: bool = LOCAL_CHROME_HEADLESS) -> bool:
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(
                headless=headless, **TIKTOK_LAUNCH_KWARGS
            )
        except (PlaywrightError, OSError) as exc:
            tiktok_logger.error(f"[+] cookie check failed to launch: {exc}")
            return False
        try:
            try:
                context = await _new_local_context(
                    browser, storage_state=account_file
                )
            except (PlaywrightError, OSError, ValueError) as exc:
                tiktok_logger.error(
                    f"[+] cookie check failed: unreadable cookie ({exc})"
                )
                return False
            try:
                if TIKTOK_INIT_SCRIPT:
                    context = await set_init_script(context)
                page = await context.new_page()
                response = await page.goto(
                    "https://www.tiktok.com/tiktokstudio/upload?lang=en",
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
                status = (
                    getattr(response, "status", 200)
                    if response is not None
                    else 200
                )
                if int(status) >= 500:
                    tiktok_logger.error(
                        f"[+] cookie check failed: HTTP {status}"
                    )
                    return False
                if "/login" in str(page.url).lower():
                    tiktok_logger.error("[+] cookie expired")
                    return False
                if await _login_form_present(page):
                    tiktok_logger.error("[+] cookie expired")
                    return False
                if await _upload_entry_present(
                    page, TIKTOK_LOCAL_ENTRY_WAIT_MS
                ):
                    tiktok_logger.success("[+] cookie valid")
                    return True
                tiktok_logger.error("[+] cookie check failed: upload entry not found")
                return False
            except (PlaywrightError, OSError, ValueError) as exc:
                tiktok_logger.error(f"[+] cookie check failed: {exc}")
                return False
            finally:
                await context.close()
        finally:
            await browser.close()


async def tiktok_setup(
    account_file,
    handle: bool = False,
    *,
    headless: bool = LOCAL_CHROME_HEADLESS,
    force: bool = False,
) -> bool:
    """Ensure a local cookie exists and is valid.

    ``handle=True`` opens an interactive headed login when the cookie is missing
    or expired, then re-validates it.  ``force=True`` opens the login even when
    an existing cookie is valid (used by ``sau tiktok login`` so operators can
    always switch accounts).  ``handle=False`` only checks.
    """
    account_file = get_absolute_path(str(account_file), "tk_uploader")
    if force or not os.path.exists(account_file) or not await cookie_auth(
        account_file, headless=headless
    ):
        if not handle:
            return False
        tiktok_logger.info(
            "[+] opening a headed browser for manual TikTok login."
        )
        await get_tiktok_cookie(account_file)
        return await cookie_auth(account_file, headless=headless)
    return True


async def get_tiktok_cookie(account_file) -> str:
    """Open a headed browser and save the cookie after the user logs in.

    TikTok has no reliable QR/deep-link login on the desktop web; the operator
    completes the login in the browser, then presses Enter in the terminal.  A
    non-interactive terminal is rejected explicitly instead of hanging.
    """
    if not sys.stdin.isatty():
        raise RuntimeError(
            "TikTok 本地登录需要交互式终端：请在终端运行 "
            "`sau tiktok login --account <name>`，完成浏览器登录后按 Enter。"
        )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=False,
            # Patchright rejects any arg that does not start with "-"; keep the
            # language as one ``--lang=...`` argument, never two tokens.
            args=["--lang=en-US"],
            **TIKTOK_LAUNCH_KWARGS,
        )
        try:
            context = await browser.new_context(**TIKTOK_CONTEXT_KWARGS)
            try:
                if TIKTOK_INIT_SCRIPT:
                    context = await set_init_script(context)
                page = await context.new_page()
                try:
                    await page.goto(
                        "https://www.tiktok.com/login?lang=en",
                        wait_until="domcontentloaded",
                        timeout=60_000,
                    )
                except Exception as exc:
                    tiktok_logger.warning(
                        f"[+] TikTok login page was slow: {exc}"
                    )
                tiktok_logger.info(
                    "请在打开的浏览器中完成 TikTok 登录；完成后回到终端按 Enter "
                    "保存 cookie。"
                )
                try:
                    await asyncio.to_thread(input, "")
                except EOFError as exc:
                    raise RuntimeError(
                        "无法读取终端输入，TikTok 本地登录已取消。"
                    ) from exc
                await context.storage_state(path=str(account_file))
                tiktok_logger.success(f"[+] cookie saved: {account_file}")
                return str(account_file)
            finally:
                await context.close()
        finally:
            await browser.close()


class TiktokBaseUploader(BaseVideoUploader):
    """Shared TikTok Studio upload skeleton.

    The template in ``_upload_on_page`` runs the nine steps in a fixed order;
    subclasses implement the media-specific hooks.  ``ensure_mode`` and
    ``apply_cover`` are no-ops until later tickets fill them in; publish
    options are applied by ``apply_options`` (ticket 12).
    """

    upload_url = TIKTOK_UPLOAD_URL
    upload_entry_selector = TIKTOK_UPLOAD_ENTRY_SELECTOR

    def start_publish_budget(self) -> PublishTimeoutBudget:
        self._publish_budget = PublishTimeoutBudget(
            "TikTok",
            pre_click_message=_PRE_PUBLISH_TIMEOUT_MESSAGE,
            result_unknown_message=_PUBLISH_RESULT_UNKNOWN_MESSAGE,
        )
        return self._publish_budget

    def _coerce_budget(
        self, deadline: float | PublishTimeoutBudget | None
    ) -> PublishTimeoutBudget:
        """Reuse the live budget; keep legacy float ``deadline`` call sites working."""
        if isinstance(deadline, PublishTimeoutBudget):
            return deadline
        budget = self.publish_budget
        if deadline is not None:
            budget.deadline = deadline
        return budget

    def _humanizer(self, page) -> Humanizer:
        """One instance per page: pointer position and RNG stay continuous.

        ``locator_base`` may be a ``frame_locator``; the humanizer always gets
        the real ``page`` because pointer coordinates are page-level.
        """
        cached = getattr(self, "_humanizer_instance", None)
        if cached is None or cached.page is not page:
            cached = Humanizer(page, sleep=self._humanize_pause)
            self._humanizer_instance = cached
        return cached

    async def _humanize_pause(self, seconds: float) -> None:
        """Clamp humanized pauses to the publish budget; never raise here."""
        remaining = max(0.0, self.publish_budget.remaining_seconds())
        if seconds > remaining and not getattr(self, "_pause_warned", False):
            tiktok_logger.warning(
                "人类化停顿被预算裁剪: {}s > {}s",
                round(seconds, 2),
                round(remaining, 2),
            )
            self._pause_warned = True
        await asyncio.sleep(min(seconds, remaining))

    def _option_humanizer(self) -> Humanizer | None:
        """Humanizer for option controls; ``None`` on the offline test seam."""
        page = getattr(self, "_option_page", None)
        return self._humanizer(page) if page is not None else None

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
        multilogin = session.managed
        budget = self.start_publish_budget()
        await self._upload_on_page(
            page, multilogin=multilogin, budget=budget
        )

    async def upload_local(self, playwright: Playwright | None) -> None:
        """Run the legacy local-browser branch (cookie file, no Multilogin)."""
        if playwright is None:
            raise ValueError("本地模式需要 Playwright 实例")
        if not self.account_file:
            raise ValueError(
                "本地模式需要 cookie 文件；请先运行 "
                "`sau tiktok login --account <name>`。"
            )

        browser = await playwright.chromium.launch(
            headless=self.headless, **TIKTOK_LAUNCH_KWARGS
        )
        try:
            try:
                context = await _new_local_context(
                    browser, storage_state=self.account_file
                )
            except Exception as exc:
                raise RuntimeError(
                    "TikTok 本地 cookie 加载失败，请重新运行 "
                    "`sau tiktok login --account <name>`。"
                ) from exc
            try:
                if TIKTOK_INIT_SCRIPT:
                    context = await set_init_script(context)
                page = await context.new_page()
                # Local mode sets the page language explicitly; Multilogin
                # Profiles must already be English (US) and skip this step.
                await self.change_language(page)
                # Local mode keeps the same total budget as Multilogin so a
                # stuck upload cannot hold the process forever.
                budget = self.start_publish_budget()
                await self._upload_on_page(
                    page, multilogin=False, budget=budget
                )
                await context.storage_state(path=f"{self.account_file}")
                tiktok_logger.info('  [-] update cookie！')
                await asyncio.sleep(2)
            finally:
                await context.close()
        finally:
            await browser.close()

    async def change_language(self, page):
        # Best-effort only: local mode already sets ``locale=en-US``; TikTok's
        # analytics-heavy home page can exceed a ``load`` timeout.
        try:
            await page.goto(
                "https://www.tiktok.com",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            await page.wait_for_selector(
                '[data-e2e="nav-more-menu"]', timeout=10_000
            )
            # 已经设置为英文, 省略这个步骤
            if (
                await page.locator(
                    '[data-e2e="nav-more-menu"]'
                ).text_content()
                == "More"
            ):
                return

            await page.locator('[data-e2e="nav-more-menu"]').click()  # native-click: language；界面语言初始化不是用户内容
            await page.locator('[data-e2e="language-select"]').click()  # native-click: language；界面语言初始化不是用户内容
            await page.locator(
                '#creator-tools-selection-menu-header >> text=English (US)'
            ).click()  # native-click: language；界面语言初始化不是用户内容
        except Exception as exc:
            tiktok_logger.warning(
                f"[+] TikTok language switch skipped: {exc}"
            )

    async def _upload_on_page(
        self,
        page,
        *,
        multilogin: bool,
        budget: PublishTimeoutBudget | None,
    ) -> None:
        # 1. open the upload page and pick the locator base
        await self.open_upload_page(page, multilogin=multilogin)
        # Snapshot HUMANIZE at page creation; never read the env mid-run.
        self._humanizer(page)
        # 2. attach the media file(s)
        await self.attach_media(page)
        # 3. fill the caption/title fields
        await self.fill_metadata(page)
        # 4. wait until the editor finished processing the media
        await self.wait_media_ready(
            page, deadline=budget, multilogin=multilogin
        )
        # 5. publish options (privacy / comments / reuse)
        await self.apply_options(page)
        # 6. custom cover (video only; base is a no-op)
        await self.apply_cover(page)
        # 7. schedule, when requested
        await self.apply_schedule(page)
        # 8. publish (``--no-publish`` stops at the ready point instead)
        if getattr(self, "no_publish", False):
            await self.wait_publish_ready(
                page, deadline=budget, multilogin=multilogin
            )
            tiktok_logger.success(TIKTOK_DRY_RUN_READY_MESSAGE)
            return
        await self.click_publish(
            page, deadline=budget, multilogin=multilogin
        )
        if multilogin:
            # The click already happened; a late redirect must not claim the
            # post was untouched.
            _raise_if_login_required(page, publish_attempted=True)
        # 9. read back the published item
        self.last_item_id = await self.read_result(page)
        tiktok_logger.success(self.result_label(self.last_item_id))

    async def open_upload_page(self, page, *, multilogin: bool) -> None:
        try:
            await page.goto(
                self.upload_url,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
        except Exception as exc:
            if multilogin:
                _raise_if_login_required(page)
            # The Studio app can still render after a slow ``load``; the entry
            # wait below owns the real failure if it did not.
            tiktok_logger.warning(
                f"[+] TikTok upload navigation was slow: {exc}"
            )
        tiktok_logger.info(f'[+]Uploading-------{self.media_label()}')
        if multilogin:
            _raise_if_login_required(page)

        try:
            await page.wait_for_url(
                re.compile(r".*tiktokstudio/upload.*"), timeout=10000
            )
        except Exception as exc:
            if multilogin:
                _raise_if_login_required(page)
            # The Studio app may already be rendering even when the exact URL
            # wait loses a race with a redirect; the entry wait below decides.
            tiktok_logger.warning(
                f"[+] TikTok upload URL wait was slow: {exc}"
            )

        try:
            # The current Studio shell can be the ``Select video`` entry itself,
            # without an iframe or ``div.upload-container``.
            entry_timeout = (
                TIKTOK_LOCAL_ENTRY_WAIT_MS if not multilogin else 10_000
            )
            await page.wait_for_selector(
                self.upload_entry_selector,
                timeout=entry_timeout,
                state="attached",
            )
            tiktok_logger.info("TikTok upload entry appeared.")
        except Exception as e:
            tiktok_logger.error("TikTok upload entry did not appear in time.")
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
        deadline: float | PublishTimeoutBudget | None = None,
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

        # AIGC/brand switches live in the collapsed advanced-settings section.
        # Expand it before resolving controls so they are visible and clickable.
        await self._expand_advanced_settings(page)
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
            self._require_option_control(
                controls.reuse,
                "allow_reuse",
                options.allow_reuse,
                url,
            )
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
            await self._apply_brand_options(controls, page=page, url=url)

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
        current = await _guarded_state(
            _read_switch_state,
            control,
            option="aigc",
            stage="read",
            requested=requested,
            url=url,
        )
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
        await control.click()  # native-click: manage；控件底座内部走 Humanizer
        if requested:
            await self._confirm_aigc_turn_on(page)
        actual = await _guarded_state(
            _read_switch_state,
            control,
            option="aigc",
            stage="readback",
            requested=requested,
            url=url,
        )
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
        found = await _find_candidate(
            page, _AIGC_TURN_ON_CANDIDATES, visible=True
        )
        if found is None:
            return
        button, index, description = found
        tiktok_logger.info(
            f"[+] TikTok options: aigc dialog candidate #{index} "
            f"({description}) matched"
        )
        humanizer = self._humanizer(page)
        try:
            await _humanized_click(humanizer, button)
            await button.wait_for(
                state="detached", timeout=_AIGC_DIALOG_TIMEOUT_MS
            )
        except Exception as exc:
            # A dialog click that fails or never dismisses is a real page
            # failure.  Do not swallow it: the caller must see why the AIGC
            # first-run guidance could not be confirmed.
            raise _option_error(
                option="aigc",
                stage="turn-on-dialog",
                requested=True,
                actual="dialog-error",
                control=None,
                url=_page_url(page),
                detail=str(exc),
                candidates=tuple(
                    label for label, _ in _AIGC_TURN_ON_CANDIDATES
                ),
            ) from exc

    async def _wait_for_brand_labels(
        self, page, *, timeout_ms: int = 3000
    ) -> None:
        """Wait for the brand rows that render only after the master switch.

        A fixed 500 ms sleep raced slower Studio renders; polling the actual
        ``title-line`` row keeps the one-shot resolver from raising early.
        """
        if self.locator_base is None:
            return
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            try:
                shelf = self.locator_base.locator(
                    'xpath=//div[contains(@class,"title-line")]'
                    '[.//span[normalize-space(text())="Your brand"]]'
                )
                if await shelf.count() and await shelf.first.is_visible():
                    return
            except Exception:
                pass
            await page.wait_for_timeout(150)

    async def _apply_brand_options(
        self, controls: TiktokSettingsControls, *, page, url: str
    ) -> None:
        """Open the master switch, then explicitly set both checkboxes.

        The checkbox that was not requested is normalized to ``False`` so a
        stale selection from the page/previous post can never leak through.
        Both may be ``True`` at the same time.  The two checkboxes are only
        resolved *after* the master switch is on, because Studio does not
        render them until then.
        """
        options = self.options
        your_brand = options.your_brand is True
        branded_content = options.branded_content is True
        self._option_page = page

        self._require_option_control(
            controls.brand_switch, "brand_switch", True, url
        )
        await _set_switch_option(
            controls.brand_switch,
            True,
            option="brand_switch",
            url=url,
        )
        await self._wait_for_brand_labels(page)

        your_control = controls.your_brand
        if your_control is None:
            your_control = await self._resolve_single_control("your_brand")
        branded_control = controls.branded_content
        if branded_control is None:
            branded_control = await self._resolve_single_control(
                "branded_content"
            )

        self._require_option_control(
            your_control, "your_brand", your_brand, url
        )
        self._require_option_control(
            branded_control,
            "branded_content",
            branded_content,
            url,
        )
        await _set_toggle_option(
            your_control,
            your_brand,
            option="your_brand",
            url=url,
        )
        await _set_toggle_option(
            branded_control,
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
            # The two checkboxes are resolved after the master switch is on.
            names.append("brand_switch")
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

    def _control(self, locator) -> _LocatorControl:
        return _LocatorControl(locator, humanizer=self._option_humanizer())

    def _privacy_control(
        self, trigger, scope, *, fallback_scope=None
    ) -> _LocatorPrivacyControl:
        return _LocatorPrivacyControl(
            trigger,
            scope,
            fallback_scope=fallback_scope,
            humanizer=self._option_humanizer(),
        )

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
                return self._privacy_control(
                    scope.locator('button[role="combobox"]'),
                    scope,
                    fallback_scope=base,
                )

            def from_role():
                return self._privacy_control(
                    base.get_by_role("combobox"), base
                )

            def from_text():
                trigger = base.locator(
                    'xpath=//div[contains(text(), "Who can see this post")]'
                    '/following::button[@role="combobox"][1]'
                )
                return self._privacy_control(trigger, base)

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
                    lambda: self._control(
                        perm.get_by_role(
                            "checkbox", name="Allow comments"
                        )
                    ),
                ),
                (
                    "data-e2e=user_perm_container+role=Comment",
                    lambda: self._control(
                        perm.get_by_role("checkbox", name="Comment")
                    ),
                ),
                (
                    "data-e2e=user_perm_container+label=Allow comments",
                    lambda: self._control(
                        perm.locator(
                            'label:has-text("Allow comments")'
                        )
                    ),
                ),
                (
                    "data-e2e=user_perm_container+label=Comment",
                    lambda: self._control(
                        perm.locator(
                            'label:has-text("Comment")'
                        )
                    ),
                ),
            )

        if name == "reuse":
            # Current Studio labels the single switch "Reuse of content";
            # older bundles used "Allow reuse of content".
            return (
                (
                    "data-e2e=user_perm_container+role=Reuse of content",
                    lambda: self._control(
                        perm.get_by_role(
                            "checkbox", name="Reuse of content"
                        )
                    ),
                ),
                (
                    "data-e2e=user_perm_container+label=Reuse of content",
                    lambda: self._control(
                        perm.locator(
                            'label:has-text("Reuse of content")'
                        )
                    ),
                ),
                (
                    "data-e2e=user_perm_container+role=Allow reuse of content",
                    lambda: self._control(
                        perm.get_by_role(
                            "checkbox", name="Allow reuse of content"
                        )
                    ),
                ),
                (
                    "data-e2e=user_perm_container+label=Allow reuse of content",
                    lambda: self._control(
                        perm.locator(
                            'label:has-text("Allow reuse of content")'
                        )
                    ),
                ),
            )

        if name == "aigc":
            aigc_container = base.locator(
                '[data-e2e="aigc_container"]'
            )
            return (
                (
                    'data-e2e=aigc_container+.Switch__content',
                    lambda: self._control(
                        aigc_container.locator('.Switch__content')
                    ),
                ),
                (
                    'data-e2e=aigc_container+role=switch',
                    lambda: self._control(
                        aigc_container.locator('[role="switch"]')
                    ),
                ),
            )

        if name == "brand_switch":
            disclose = base.locator(
                '[data-e2e="disclose_content_container"]'
            )
            return (
                (
                    'data-e2e=disclose_content_container+.Switch__content',
                    lambda: self._control(
                        disclose.locator('.Switch__content')
                    ),
                ),
                (
                    'data-e2e=disclose_content_container+role=switch',
                    lambda: self._control(
                        disclose.locator('[role="switch"]')
                    ),
                ),
            )

        if name in ("your_brand", "branded_content"):
            label = (
                "Your brand" if name == "your_brand" else "Branded content"
            )
            # Real DOM: ``disclose_content_container`` only wraps the master
            # switch.  The two checkboxes render in a sibling ``container``
            # after the switch is turned on, so a scoped XPath inside
            # ``disclose`` can never match.  Anchor on the semantic
            # ``title-line`` row first, then fall back to the exact-text
            # span's preceding label.  Both matches are exact-text, so an
            # unrelated duplicate would have to reuse the same copy.
            xpath_title_line = (
                'xpath=//div[contains(@class,"title-line")]'
                f'[.//span[normalize-space(text())="{label}"]]/label[1]'
            )
            xpath_sibling = (
                f'xpath=//span[normalize-space(text())="{label}"]'
                '/preceding-sibling::label[1]'
            )
            return (
                (
                    f'title-line "{label}" -> label',
                    lambda: self._control(
                        base.locator(xpath_title_line)
                    ),
                ),
                (
                    f'span "{label}" -> preceding label',
                    lambda: self._control(
                        base.locator(xpath_sibling)
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
                if await control.count() > 0 and await control.is_visible():
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

    async def _wait_for_settings_surface(
        self, page, *, timeout_ms: int = 3000
    ) -> None:
        """Wait for a collapsed option surface to become visible after expand."""
        if self.locator_base is None:
            return
        selectors = (
            '[data-e2e="user_perm_container"]',
            '[data-e2e="aigc_container"]',
            '[data-e2e="disclose_content_container"]',
        )
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            for selector in selectors:
                try:
                    locator = self.locator_base.locator(selector)
                    if (
                        await locator.count()
                        and await locator.first.is_visible()
                    ):
                        return
                except Exception:
                    continue
            await page.wait_for_timeout(150)

    async def _expand_advanced_settings(self, page) -> None:
        if self.locator_base is None:
            return
        humanizer = self._humanizer(page)
        # Idempotent: a second call must not toggle "Show more" back closed.
        for selector in (
            '[data-e2e="user_perm_container"]',
            '[data-e2e="aigc_container"]',
            '[data-e2e="disclose_content_container"]',
        ):
            try:
                surface = self.locator_base.locator(selector)
                if (
                    await surface.count()
                    and await surface.first.is_visible()
                ):
                    return
            except Exception:
                continue
        container = self.locator_base.locator(
            '[data-e2e="advanced_settings_container"]'
        )
        try:
            if await container.count() == 0:
                # The photo composer has no advanced_settings_container; its
                # comment/AIGC/brand controls live behind a global Show more.
                show_more = self.locator_base.get_by_text(
                    "Show more", exact=True
                )
                if await show_more.count():
                    await _humanized_click(humanizer, show_more.first)
                    await self._wait_for_settings_surface(page)
                    tiktok_logger.info(
                        "[+] expanded photo settings via Show more"
                    )
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
                    await _humanized_click(humanizer, more_btn.first)
                    await self._wait_for_settings_surface(page)
                    return
        except Exception:
            pass

        show_more = container.get_by_text("Show more", exact=True)
        try:
            if await show_more.count():
                await _humanized_click(humanizer, show_more.first)
                await self._wait_for_settings_surface(page)
        except Exception:
            pass

    async def resolve_option_controls(self, page) -> TiktokSettingsControls:
        """Resolve only the requested controls; expand advanced settings once.

        Missing controls are looked up again after a single expansion attempt.
        There is deliberately no whole-page fallback.
        """
        resolved: dict[str, TiktokOptionControl] = {}
        missing: list[str] = []
        self._option_page = page
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
                if details:
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

        publish_date = await prepare_schedule(page, self.publish_date)
        scope = self.locator_base if self.locator_base is not None else page
        humanizer = self._humanizer(page)

        # only-me can disable scheduling on private accounts; fail clearly
        # instead of retrying a disabled radio for tens of seconds.
        schedule_input = scope.locator(
            'input[name="postSchedule"][value="schedule"]'
        )
        schedule_label = scope.locator(
            'label:has(input[name="postSchedule"][value="schedule"])'
        )
        try:
            disabled = await schedule_input.first.is_disabled()
            classes = (
                await schedule_label.first.get_attribute("class")
            ) or ""
            aria_disabled = await schedule_label.first.get_attribute(
                "aria-disabled"
            )
            if (
                disabled
                or str(aria_disabled).lower() == "true"
                or "disabled-true" in classes.casefold()
            ):
                raise RuntimeError(
                    "TikTok 定时发布不可用：当前隐私级别（如 only-me）或"
                    "账号设置禁用了 Schedule；请改用 followers/friends "
                    "或立即发布。"
                )
        except RuntimeError:
            raise
        except Exception:
            pass

        date_cb = page.get_by_role("combobox", name="Select date")
        for _attempt in range(3):
            # Clicking the radio label is idempotent; do not trust the input's
            # DOM ``checked`` property, which React can leave stale.
            for selector in (
                'label:has(input[name="postSchedule"][value="schedule"])',
                'input[name="postSchedule"][value="schedule"]',
                'label:has-text("Schedule")',
            ):
                for target in (scope, page):
                    try:
                        await _humanized_click(humanizer, target.locator(selector).first)
                    except Exception as exc:
                        if _maybe_dispatched(exc):
                            raise

            # The first schedule on an account opens an Allow permission
            # modal; wait for either the date picker or that button.
            for _ in range(12):
                date_count = await date_cb.count()
                date_visible = (
                    bool(date_count) and await date_cb.first.is_visible()
                )
                allow = page.locator('[role="dialog"]').get_by_role(
                    "button", name=re.compile(r"^Allow$")
                )
                if await allow.count() == 0:
                    allow = page.get_by_role(
                        "button", name=re.compile(r"^Allow$")
                    )
                allow_visible = (
                    bool(await allow.count()) and await allow.first.is_visible()
                )
                tiktok_logger.info(
                    "[+] schedule probe: "
                    f"date_count={date_count} date_visible={date_visible} "
                    f"allow_visible={allow_visible}"
                )
                if date_visible:
                    break
                if allow_visible:
                    await _humanized_click(humanizer, allow.first)
                await page.wait_for_timeout(500)
            if await date_cb.count() and await date_cb.first.is_visible():
                break
        await date_cb.first.wait_for(state="visible", timeout=10000)

        # Date picker: navigate months, then click the exact day.
        await _humanized_click(humanizer, date_cb.first)
        await page.wait_for_timeout(500)
        target_month = publish_date.strftime("%B")
        target_year = str(publish_date.year)
        for _ in range(24):
            current_month = (
                await page.locator(".DatePicker__titleMonth").first.inner_text()
            ).strip()
            current_year = (
                await page.locator(".DatePicker__titleYear").first.inner_text()
            ).strip()
            if (current_month, current_year) == (target_month, target_year):
                break
            current_month_no = datetime.strptime(
                current_month, "%B"
            ).month
            if (int(current_year), current_month_no) < (
                publish_date.year,
                publish_date.month,
            ):
                await _humanized_click(
                    humanizer,
                    page.get_by_role("button", name="Next month").first,
                )
            else:
                await _humanized_click(
                    humanizer,
                    page.get_by_role("button", name="Previous month").first,
                )
            await page.wait_for_timeout(250)

        day_pattern = re.compile(
            rf"{target_month} {publish_date.day}"
            rf"(st|nd|rd|th), {target_year}"
        )
        day_button = page.get_by_role("button", name=day_pattern)
        if await day_button.count():
            await _humanized_click(humanizer, day_button.first)
        else:
            days = page.locator(
                '.DatePicker__day[data-outside="false"]:not([disabled])'
            )
            clicked = False
            for index in range(await days.count()):
                if (await days.nth(index).inner_text()).strip() == str(
                    publish_date.day
                ):
                    await _humanized_click(humanizer, days.nth(index))
                    clicked = True
                    break
            if not clicked:
                raise RuntimeError(
                    "TikTok 定时设置失败：日期选择器中找不到 "
                    f"{target_month} {publish_date.day}, {target_year}。"
                )
        await page.wait_for_timeout(300)
        await humanizer.press("Escape")

        # Time picker: 5-minute granularity, matching the Studio picker.
        hour_str = publish_date.strftime("%H")
        minute_str = f"{(publish_date.minute // 5) * 5:02d}"
        await _humanized_click(
            humanizer,
            page.get_by_role("combobox", name="Select time").first,
        )
        await page.wait_for_timeout(500)
        hour_option = page.get_by_role("option", name=f"Hours {hour_str}")
        if await hour_option.count():
            await _humanized_click(humanizer, hour_option.first)
        else:
            raise RuntimeError(
                f"TikTok 定时设置失败：时间选择器中没有 {hour_str} 时。"
            )
        minute_option = page.get_by_role(
            "option", name=f"Minutes {minute_str}"
        )
        if await minute_option.count():
            await _humanized_click(humanizer, minute_option.first)
        else:
            minutes = page.locator(
                '[aria-label="Minutes"] [role="option"]'
            )
            clicked = False
            for index in range(await minutes.count()):
                if (await minutes.nth(index).inner_text()).strip() == minute_str:
                    await _humanized_click(humanizer, minutes.nth(index))
                    clicked = True
                    break
            if not clicked:
                raise RuntimeError(
                    "TikTok 定时设置失败：时间选择器中没有 "
                    f"{minute_str} 分。"
                )
        await page.wait_for_timeout(300)
        await humanizer.press("Escape")

        # Verify the picker values, not just the clicks.
        values = page.locator(
            ".Picker__root.schedule-picker .Picker__value"
        )
        actual_date = (await values.nth(0).inner_text()).strip()
        actual_time = (await values.nth(1).inner_text()).strip()
        expected_date = (
            f"{publish_date.strftime('%b')} {publish_date.day}, "
            f"{publish_date.year}"
        )
        expected_time = f"{hour_str}:{minute_str}"
        if actual_date != expected_date or actual_time != expected_time:
            raise RuntimeError(
                "TikTok 定时设置失败："
                f"requested={publish_date.isoformat()} "
                f"actual_date={actual_date!r} actual_time={actual_time!r}"
            )

    def _result_text_candidates(self) -> tuple[str, ...]:
        values = []
        for value in (
            getattr(self, "title", None),
            getattr(self, "note", None),
        ):
            if value:
                values.append(" ".join(str(value).split()))
        for tag in getattr(self, "tags", None) or []:
            values.append(f"#{tag}")
        # Tolerate truncation in the Content list.
        return tuple(value[:40] for value in values if value)

    async def _find_result_link(
        self,
        page,
        selectors,
        *,
        timeout_ms: int | None = None,
    ) -> str | None:
        """Find the Content link for THIS post, not just the first row.

        The list can put a scheduled post first, so matching by title/note/tags
        avoids returning another post's ID.  Title/note are authoritative; a
        generic hashtag is only consulted when no title/note exists, otherwise
        an older post sharing ``#fyp`` could supply the wrong URL.
        """
        primary = tuple(
            " ".join(str(value).split())[:40]
            for value in (
                getattr(self, "title", None),
                getattr(self, "note", None),
            )
            if value and str(value).strip()
        )
        fallback = tuple(
            f"#{tag}" for tag in (getattr(self, "tags", None) or [])
        )
        timeout = (
            TIKTOK_RESULT_READ_TIMEOUT_MS
            if timeout_ms is None
            else timeout_ms
        )
        deadline = time.monotonic() + timeout / 1000
        if not primary and not fallback:
            # Nothing to identify this post; keep the legacy
            # "first result link" behavior rather than spinning.
            for selector in selectors:
                links = page.locator(selector)
                try:
                    count = await links.count()
                except Exception:
                    continue
                for index in range(min(count, 50)):
                    href = await links.nth(index).get_attribute("href")
                    if href:
                        return href
            return None
        while True:
            for group in (primary, fallback):
                if not group:
                    continue
                for selector in selectors:
                    links = page.locator(selector)
                    try:
                        count = await links.count()
                    except Exception:
                        continue
                    for index in range(min(count, 50)):
                        link = links.nth(index)
                        href = await link.get_attribute("href")
                        if not href:
                            continue
                        if not primary and not fallback:
                            # Nothing to identify this post; keep the legacy
                            # "first result link" behavior rather than spin.
                            return href
                        try:
                            text = (await link.inner_text()).strip()
                        except Exception:
                            text = ""
                        if any(value in text for value in group):
                            return href
            if time.monotonic() >= deadline:
                return None
            await page.wait_for_timeout(1000)

    async def dismiss_blocking_overlays(self, page) -> None:
        """Close TikTok's first-run overlays that intercept pointer events.

        Two independent blockers can appear after the first upload:
        1. ``Turn on automatic content checks?`` modal — dismiss with Cancel.
        2. react-joyride onboarding overlay — clicking the overlay dismisses it.
        Both are first-run UI, not publish options; missing overlays are a no-op.
        """
        try:
            dialogs = page.locator('[role="dialog"]').filter(
                has_text="automatic content checks"
            )
            if await dialogs.count():
                dialog = dialogs.first
                for label in ("Cancel", "Got it", "Close"):
                    button = dialog.get_by_role("button", name=label)
                    if await button.count():
                        await button.first.click(
                            timeout=TIKTOK_OVERLAY_CLICK_TIMEOUT_MS
                        )  # native-click: chrome；首次运行的 automatic content checks 弹窗不是用户内容
                        try:
                            await dialog.wait_for(
                                state="detached", timeout=5_000
                            )
                        except Exception:
                            pass
                        tiktok_logger.info(
                            "[+] dismissed automatic content checks modal"
                        )
                        break
        except Exception as exc:
            tiktok_logger.info(
                f"  [-] automatic content checks modal not dismissed: {exc}"
            )

        try:
            joyride = page.locator("#react-joyride-portal")
            if await joyride.count():
                overlay = page.locator(".react-joyride__overlay")
                target = overlay if await overlay.count() else joyride
                await target.first.click(
                    timeout=TIKTOK_OVERLAY_CLICK_TIMEOUT_MS
                )  # native-click: chrome；react-joyride 引导遮罩不是用户控件
                try:
                    await joyride.wait_for(state="detached", timeout=5_000)
                except Exception:
                    pass
                tiktok_logger.info("[+] dismissed onboarding overlay")
        except Exception as exc:
            tiktok_logger.info(f"  [-] onboarding overlay not dismissed: {exc}")

    async def _click_editor(self, page, editor_locator) -> None:
        """Click the caption editor, clearing first-run overlays as they appear."""
        humanizer = self._humanizer(page)
        last_exc = None
        for _ in range(8):
            await self.dismiss_blocking_overlays(page)
            try:
                await _humanized_click(humanizer, editor_locator)
                return
            except Exception as exc:
                # ``mouse.down`` already happened: never dispatch a second time.
                if _maybe_dispatched(exc):
                    raise
                last_exc = exc
                await page.wait_for_timeout(1000)
        if last_exc is not None:
            raise last_exc

    async def _wait_for_no_options(
        self, scopes, page, *, timeout_ms: int = 1000
    ) -> None:
        """Wait for a previous suggestion dropdown to close."""
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            open_scopes = 0
            for scope in scopes:
                try:
                    if await scope.locator('[role="option"]').count():
                        open_scopes += 1
                except Exception:
                    pass
            if not open_scopes:
                return
            await page.wait_for_timeout(100)

    async def _apply_hashtag(
        self, page, tag: str, *, humanizer: Humanizer | None = None
    ) -> bool:
        """Insert ``#tag`` as a real hashtag entity, like native selection.

        Typing ``#tag`` and pressing **Space** leaves plain text (no
        ``mention`` span).  Clicking the exact suggestion creates the real
        entity.  The suggestion dropdown renders asynchronously, so poll for
        it instead of a single fixed sleep.  Only an exact suggestion is
        accepted: picking the first item blindly could replace the user's tag
        with a different one.
        """
        humanizer = humanizer or self._humanizer(page)
        wanted = f"#{tag}".casefold()
        scopes = []
        if self.locator_base is not None:
            scopes.append(self.locator_base)
        if not any(scope is page for scope in scopes):
            scopes.append(page)

        # Character by character: the dropdown reacts to real key events.
        await humanizer.type_text("#" + tag)
        deadline = (
            time.monotonic() + TIKTOK_HASHTAG_SUGGESTION_TIMEOUT_MS / 1000
        )
        settle_deadline = None
        suggestion_failed = False
        while True:
            rendered = False
            for scope in scopes:
                try:
                    options = scope.locator('[role="option"]')
                    count = await options.count()
                except Exception:
                    continue
                if count:
                    rendered = True
                for index in range(count):
                    option = options.nth(index)
                    try:
                        first_line = (
                            await option.inner_text()
                        ).strip().splitlines()[0].strip()
                    except Exception:
                        continue
                    if not first_line.startswith("#"):
                        continue
                    if first_line.casefold() == wanted:
                        selected = False
                        try:
                            selected = (
                                str(
                                    await option.get_attribute(
                                        "aria-selected"
                                    )
                                ).lower()
                                == "true"
                            )
                        except Exception:
                            selected = False
                        if selected:
                            # The typed tag is already the focused suggestion;
                            # Enter accepts it without viewport/overlay issues.
                            await humanizer.press("Enter")
                        else:
                            try:
                                await _humanized_click(humanizer, option)
                            except Exception as exc:
                                # Keep the plain text and fire the association
                                # suggestion instead of aborting the publish.
                                # A click that may have been dispatched is
                                # never retried (the loop exits below).
                                tiktok_logger.warning(
                                    f"  [-] tag #{tag} suggestion click failed: {exc}"
                                )
                                suggestion_failed = True
                                break
                        await page.wait_for_timeout(300)
                        tiktok_logger.info(
                            f"  [-] tag #{tag} inserted as hashtag entity"
                        )
                        await self._wait_for_no_options(scopes, page)
                        return True
                if suggestion_failed:
                    break

            if suggestion_failed:
                break
            now = time.monotonic()
            if rendered and settle_deadline is None:
                # Let a partially rendered list settle before giving up, but
                # don't wait the full timeout when the dropdown is already up.
                settle_deadline = now + TIKTOK_HASHTAG_SETTLE_MS / 1000
            if settle_deadline is not None and now >= settle_deadline:
                break
            if not rendered and now >= deadline:
                break
            await page.wait_for_timeout(200)

        # No exact suggestion: one Space is enough for a plain-text tag (the
        # old insert/space/backspace dance only produced the same result).
        await humanizer.press("Space")
        await page.wait_for_timeout(300)
        tiktok_logger.info(
            f"  [-] tag #{tag} inserted as plain text (no exact suggestion)"
        )
        return False

    async def fill_caption(self, page, text, tags, *, editor=None) -> None:

        editor_locator = (
            editor
            if editor is not None
            else self.locator_base.locator('div.public-DraftEditor-content')
        )
        humanizer = self._humanizer(page)
        await self._click_editor(page, editor_locator)

        await humanizer.press("End")

        # Playwright maps ControlOrMeta to Cmd on macOS and Ctrl elsewhere;
        # Control+A alone leaves the old caption on macOS.
        await humanizer.press("ControlOrMeta+A")

        await humanizer.press("Delete")

        await humanizer.press("End")

        await page.wait_for_timeout(1000)  # 等待1秒

        await humanizer.type_text(text)
        await page.wait_for_timeout(1000)  # 等待1秒
        await humanizer.press("End")

        await humanizer.press("Enter")

        # tag part
        for index, tag in enumerate(tags, start=1):
            tiktok_logger.info("Setting the %s tag" % index)
            await humanizer.press("End")
            await page.wait_for_timeout(300)
            await self._apply_hashtag(page, tag, humanizer=humanizer)
            await humanizer.press("End")

    async def wait_publish_ready(
        self,
        page,
        *,
        deadline: float | PublishTimeoutBudget | None = None,
        multilogin: bool = False,
    ):
        """Wait until the publish button is present and enabled; never clicks.

        ``--no-publish`` uses this to stop at the publish-ready point.  The
        window is ``min(60s, remaining budget)`` and it is *not* extended by
        ``--not-before``: the dry run skips that wait entirely.  On timeout the
        error is a plain ``RuntimeError`` (exit 1) because no click was sent,
        so the post was definitely not published.

        Returns the locator the gate verified, so ``click_publish`` clicks
        exactly the element that passed the visible + enabled + aria-disabled
        check instead of resolving a third, unverified one.
        """
        budget = self._coerce_budget(deadline)
        window = max(0.0, min(
            TIKTOK_DRY_RUN_READY_TIMEOUT_MS / 1000,
            budget.remaining_seconds(),
        ))
        ready_deadline = time.monotonic() + window
        poll = TIKTOK_DRY_RUN_POLL_MS / 1000
        while True:
            if budget.remaining_seconds() <= 0:
                raise budget.pre_click_error()
            if multilogin:
                _raise_if_login_required(page)
            button = await self._publish_button_ready(
                page, multilogin=multilogin
            )
            if button is not None:
                return button
            remaining = min(
                ready_deadline - time.monotonic(),
                budget.remaining_seconds(),
            )
            if remaining <= 0:
                raise RuntimeError(
                    "TikTok 发布就绪超时（最多 "
                    f"{int(window)} 秒）：发布按钮未出现或仍不可用，"
                    "未点击发布，未发布任何内容。"
                )
            await asyncio.sleep(min(poll, remaining))

    async def _publish_button_ready(self, page, *, multilogin: bool):
        """The first visible + enabled publish locator; never clicks it.

        Returns ``None`` when no candidate is present or the match is
        disabled / ``aria-disabled="true"``.
        """
        if multilogin:
            _raise_if_login_required(page)
        found = await _find_candidate(
            self.locator_base, _PUBLISH_BUTTON_CANDIDATES, visible=True
        )
        if found is None:
            return None
        button, index, description = found
        try:
            enabled = await button.is_enabled()
        except Exception:
            enabled = True
        if enabled:
            get_attribute = getattr(button, "get_attribute", None)
            if callable(get_attribute):
                try:
                    if str(
                        await get_attribute("aria-disabled")
                    ).lower() == "true":
                        enabled = False
                except Exception:
                    pass
        if not enabled:
            return None
        tiktok_logger.info(
            "[+] TikTok publish ready: candidate "
            f"#{index + 1}/{len(_PUBLISH_BUTTON_CANDIDATES)} matched "
            f"({description})"
        )
        return button

    async def click_publish(
        self,
        page,
        *,
        deadline: float | PublishTimeoutBudget | None = None,
        multilogin: bool = False,
    ):
        budget = self._coerce_budget(deadline)
        await budget.wait_until_allowed(
            getattr(self, "publish_not_before", None),
            logger=tiktok_logger,
            label="TikTok 发布",
        )
        budget.check_pre_click()
        humanizer = self._humanizer(page)
        # ``publish_clicked`` means "a click may have reached the page".  It
        # flips after a clean ``click()`` return and also on a ``maybe``
        # dispatch (a raise after ``mouse.down``): spec §2.1 forbids
        # re-dispatching either way, and a later login redirect must be
        # reported as "possibly published".
        publish_clicked = False

        # Phase 1 — readiness only (60s window, min(60s, remaining budget)).
        # The gate returns the exact locator it verified: visible + enabled +
        # no aria-disabled. A missing/disabled button fails here (exit 1)
        # instead of being retried, and the click below never re-resolves.
        publish_button = await self.wait_publish_ready(
            page, deadline=budget, multilogin=multilogin
        )
        if publish_button is None:
            raise RuntimeError(
                "TikTok 发布按钮在就绪检查后消失：未点击发布，未发布任何内容。"
            )

        # Single dispatch. A failure before mouse.down is a hard failure (exit
        # 1) — never re-click. A failure after mouse.down may already have
        # published, so it is treated as sent and never re-dispatched.
        await humanizer.before_submit()
        budget.check_pre_click()
        try:
            await _humanized_click(humanizer, publish_button)
        except Exception as e:
            if multilogin:
                _raise_if_login_required(
                    page, publish_attempted=_maybe_dispatched(e)
                )
            if not _maybe_dispatched(e):
                raise
            publish_clicked = True
            tiktok_logger.warning(
                f"  [-] publish click raised after dispatch: {e}"
            )
        else:
            publish_clicked = True
            tiktok_logger.info("  [-] publish click sent")

        # Phase 2 — result polling only. This loop never re-enters the click
        # path, so a slow or missing success URL cannot publish twice.
        dialog_clicked = False
        poll_iterations = 0
        while True:
            poll_iterations += 1
            if poll_iterations > TIKTOK_PUBLISH_MAX_LOOP_ITERATIONS:
                raise budget.timeout_error(True)
            if multilogin:
                _raise_if_login_required(page, publish_attempted=publish_clicked)
            try:
                budget.check_pre_click()
            except RuntimeError:
                raise budget.timeout_error(True) from None
            try:
                await page.wait_for_url(
                    re.compile(r".*tiktokstudio/content.*"), timeout=3000
                )
            except (PlaywrightTimeoutError, TimeoutError):
                # Photo posts may show a "Post now" confirmation instead of
                # navigating. The dialog can render a beat after the publish
                # click, so only a click that actually landed latches: an
                # absent (or failed) attempt is retried on the next timeout,
                # while a landed click is never repeated.
                if not dialog_clicked:
                    try:
                        if await self._click_post_now(page):
                            dialog_clicked = True
                    except Exception as exc:
                        # The publish click was already dispatched: a dialog
                        # failure is a result-unknown, never a pre-click error.
                        raise budget.timeout_error(True) from exc
                tiktok_logger.info("  [-] video publishing")
                await asyncio.sleep(0.5)
                continue
            except Exception as e:
                if multilogin:
                    _raise_if_login_required(
                        page, publish_attempted=publish_clicked
                    )
                raise budget.timeout_error(True) from e

            tiktok_logger.success("  [-] video published success")
            return

    async def _click_post_now(self, page) -> bool:
        """Click an exact confirmation button inside a visible dialog.

        The click is deliberately dialog-only: a page-level fallback can match
        the primary ``Schedule``/``Post`` button and click it a second time,
        producing a duplicate post.  If no visible dialog exists, do nothing
        and let the success-URL wait own the outcome.
        """
        dialogs = []
        for selector in _CONFIRMATION_DIALOG_SELECTORS:
            try:
                locator = page.locator(selector)
                for position in range(await locator.count()):
                    candidate = locator.nth(position)
                    is_visible = getattr(candidate, "is_visible", None)
                    if not callable(is_visible) or await is_visible():
                        dialogs.append(candidate)
            except Exception:
                continue
        if not dialogs:
            return False

        names = _confirmation_names(self.publish_date)
        for dialog in reversed(dialogs):
            for index, name in enumerate(names, start=1):
                pattern = re.compile(rf"^{re.escape(name)}$")
                found = await _find_candidate(
                    dialog,
                    (
                        (
                            f"dialog role=button[name=/{name}/]",
                            lambda scope, pattern=pattern: scope.get_by_role(
                                "button", name=pattern
                            ),
                        ),
                    ),
                    visible=True,
                )
                if found is None:
                    continue
                button, _, _ = found
                humanizer = self._humanizer(page)
                try:
                    await _humanized_click(humanizer, button)
                except Exception as exc:
                    # Do not turn a failed optional fallback into a different
                    # exit code; the success-URL wait still owns the outcome.
                    tiktok_logger.info(
                        f"  [-] confirmation click failed ({name}): {exc}"
                    )
                    return False
                tiktok_logger.info(
                    "[+] TikTok publish: confirmation candidate "
                    f"#{index}/{len(names)} clicked "
                    f"(dialog role=button[name=/{name}/])"
                )
                return True
        return False

    async def choose_base_locator(self, page):
        # await page.wait_for_selector('div.upload-container')
        if await page.locator('iframe[data-tt="Upload_index_iframe"]').count():
            self.locator_base = page.frame_locator(Tk_Locator.tk_iframe)
        else:
            self.locator_base = page.locator(Tk_Locator.default)

    async def _verify_scheduled_post(self, page) -> None:
        """Confirm the scheduled row is present in the Content list.

        ``read_result`` cannot return a video id before the scheduled time, so
        the row itself (title/note/tags plus a timezone-qualified time) is the
        only proof the schedule was accepted.  Without this check a failed
        schedule still exited 0.
        """
        if not self.publish_date:
            return
        values = tuple(
            " ".join(str(value).split())
            for value in (
                getattr(self, "title", None),
                getattr(self, "note", None),
            )
            if value and str(value).strip()
        )
        if not values:
            raise PublishResultUnknownError(
                "TikTok 定时发布结果未知：帖子没有标题/正文可用于核验，"
                "无法确认定时是否成功；请先人工核验 Content 列表，避免重复发布。"
            )
        # The list truncates long copy and can collapse newlines; try shorter
        # prefixes so a correctly scheduled post is not reported as unknown.
        variants: list[str] = []
        for value in values:
            normalized = " ".join(str(value).split())
            if not normalized:
                continue
            for length in (None, 40, 24, 12):
                candidate = (
                    normalized if length is None else normalized[:length]
                )
                if candidate and candidate not in variants:
                    variants.append(candidate)
        deadline = time.monotonic() + TIKTOK_RESULT_READ_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            try:
                body = await page.locator("body").inner_text()
            except Exception:
                body = ""
            marker = _find_scheduled_row_marker(body, tuple(variants))
            if marker is not None:
                tiktok_logger.info(
                    "[+] scheduled post confirmed in Content list: "
                    f"{marker!r}"
                )
                return
            await page.wait_for_timeout(1000)
        raise PublishResultUnknownError(
            "TikTok 定时发布结果未知：Content 列表未找到匹配日期/时间的定时行；"
            "请先人工核验，避免重复发布。"
            f" expected={values!r} url={_page_url(page)!r}"
        )

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
        headless: bool | None = None,
        no_publish: bool = False,
    ):
        self.title = title
        self.file_path = file_path
        self.tags = tags
        self.publish_date = publish_date
        self.thumbnail_path = thumbnail_path
        self.account_file = account_file
        self.options = options
        self.no_publish = no_publish
        self.local_executable_path = LOCAL_CHROME_PATH
        self.headless = (
            LOCAL_CHROME_HEADLESS if headless is None else headless
        )
        self.locator_base = None

    async def handle_upload_error(self, page):
        tiktok_logger.info("video upload error retrying.")
        found = await _find_candidate(
            self.locator_base, _VIDEO_FILE_CANDIDATES, visible=True
        )
        if found is None:
            raise RuntimeError(
                "TikTok 视频上传重试失败：找不到视频选择入口 "
                f"{tuple(label for label, _ in _VIDEO_FILE_CANDIDATES)!r}"
            )
        select_file_button, _, _ = found
        async with page.expect_file_chooser() as fc_info:
            await select_file_button.click()  # native-click: file；文件选择器只能由原生点击唤起
        file_chooser = await fc_info.value
        await file_chooser.set_files(self.file_path)

    async def upload(self, playwright: Playwright | None, *, session: BrowserSession | None = None) -> None:
        if session is not None:
            await self.upload_in(session)
            return
        await self.upload_local(playwright)

    async def attach_media(self, page) -> None:
        tried = tuple(label for label, _ in _VIDEO_FILE_CANDIDATES)
        last_error = None
        for index, (description, factory) in enumerate(_VIDEO_FILE_CANDIDATES):
            try:
                upload_button = factory(self.locator_base)
                await upload_button.wait_for(
                    state="visible", timeout=_VIDEO_FILE_WAIT_MS
                )
            except Exception as exc:
                last_error = exc
                continue
            tiktok_logger.info(
                "[+] TikTok video file: candidate "
                f"#{index + 1}/{len(_VIDEO_FILE_CANDIDATES)} matched "
                f"({description})"
            )
            try:
                async with page.expect_file_chooser() as fc_info:
                    await upload_button.click()  # native-click: file；文件选择器只能由原生点击唤起
                file_chooser = await fc_info.value
                await file_chooser.set_files(self.file_path)
            except Exception as exc:
                raise RuntimeError(
                    "TikTok 视频文件选择失败 | control=Select video | "
                    "stage=choose file | "
                    f"tried={list(tried)!r} | url={_page_url(page)!r} | "
                    f"detail={exc}"
                ) from exc
            return

        raise RuntimeError(
            "TikTok 视频文件选择失败 | control=Select video | "
            f"stage=wait for button | tried={list(tried)!r} | "
            f"url={_page_url(page)!r} | detail={last_error}"
        )

    async def fill_metadata(self, page) -> None:
        await self.fill_caption(page, self.title, self.tags)

    async def apply_cover(self, page) -> None:
        if not self.thumbnail_path:
            return
        tiktok_logger.info(f'[+] Uploading thumbnail file {self.title}.png')
        base = self.locator_base
        humanizer = self._humanizer(page)

        edit_cover = await _resolve_candidate(
            base,
            _COVER_EDIT_CANDIDATES,
            control="Edit cover",
            stage="open cover editor",
            page=page,
            visible=True,
        )
        await _humanized_click(humanizer, edit_cover)

        # Resolve (never click) the upload tab: its nearest ancestor that holds a
        # file input is the editor scope for the broad fallback selector.  The
        # click itself is a fallback only — see the chooser branch below.
        tab_match = await _find_candidate(
            base, _COVER_UPLOAD_TAB_CANDIDATES, visible=True
        )
        upload_tab = tab_match[0] if tab_match is not None else None

        # Scope the broad fallback input to the cover editor so it cannot hit
        # the main form's video input.  When the ancestor is not found the
        # aria-labelled candidate above is still tried against the base.
        editor_query = (
            upload_tab.locator(COVER_EDITOR_SCOPE_SELECTOR)
            if upload_tab is not None
            else None
        )
        try:
            editor = (
                editor_query.first
                if editor_query is not None and await editor_query.count()
                else None
            )
        except Exception:
            editor = None
        control_scope = editor if editor is not None else base

        file_candidates = (
            (_COVER_FILE_ARIA_SELECTOR,
             lambda scope: scope.locator(_COVER_FILE_ARIA_SELECTOR)),
            # When the cover editor root is unavailable the scoped fallback is
            # left unmatched rather than widening to the whole form.
            (_COVER_FILE_ACCEPT_SELECTOR,
             lambda scope: (
                 scope.locator(_COVER_FILE_ACCEPT_SELECTOR)
                 if editor is not None
                 # No tab ⇒ no editor scope either: ``None`` is swallowed as
                 # "unmatched" by ``_find_candidate``.
                 else editor_query
             )),
        )

        # The editor already exposes the hidden image input.  Write it directly:
        # clicking "Upload cover" first opens a real OS file chooser that then
        # stays on screen while set_input_files injects the file (same defect as
        # XHS, bbc5361).  The tab is a consumed fallback only.
        file_input = await _probe_cover_file_input(
            control_scope, file_candidates
        )
        set_files_error = None
        if file_input is not None:
            try:
                # The input is hidden but ``set_input_files`` works on it directly.
                await file_input.set_input_files(self.thumbnail_path)
            except Exception as exc:
                set_files_error = exc
                file_input = None
        if file_input is None:
            await self._set_cover_file_via_chooser(
                page,
                humanizer,
                upload_tab,
                control_scope,
                file_candidates,
                detail=(
                    f"set_input_files failed: {set_files_error}"
                    if set_files_error is not None
                    else None
                ),
            )

        # The Save button is a page-level header button in the current Studio;
        # older editors kept it inside the editor scope.  Try all scopes.
        save_button = None
        save_error = None
        for scope in (control_scope, base, page):
            try:
                save_button = await _resolve_candidate(
                    scope,
                    _COVER_SAVE_CANDIDATES,
                    control="Save",
                    stage="save cover",
                    page=page,
                    visible=True,
                )
                break
            except RuntimeError as exc:
                save_error = exc
        if save_button is None:
            raise save_error

        # The upload must produce the editor's preview before the save is
        # meaningful.  Waiting for it is the only proof the page accepted the
        # file; an enabled Save button is not an equivalent signal.
        preview = None
        for scope in (control_scope, base, page):
            preview = await _find_candidate(
                scope, _COVER_PREVIEW_CANDIDATES
            )
            if preview is not None:
                break
        preview_error = None
        preview_visible = False
        if preview is not None:
            preview_locator, index, description = preview
            tiktok_logger.info(
                "[+] cover wait for cover preview: Uploaded cover image "
                f"candidate {index + 1}/{len(_COVER_PREVIEW_CANDIDATES)}"
                f" matched ({description})"
            )
            try:
                await preview_locator.wait_for(
                    state="visible", timeout=_COVER_PREVIEW_TIMEOUT_MS
                )
                preview_visible = True
            except Exception as exc:
                preview_error = exc

        if not preview_visible:
            raise _cover_error(
                "Uploaded cover image",
                "wait for cover preview",
                _COVER_PREVIEW_CANDIDATES,
                page,
                detail=str(preview_error),
            )

        try:
            await _humanized_click(humanizer, save_button)
        except Exception as exc:
            raise _cover_error(
                "Save",
                "save cover",
                _COVER_SAVE_CANDIDATES,
                page,
                detail=str(exc),
            ) from exc

        # Saving must close the editor.  Confirm that explicitly instead of
        # assuming the click took effect.
        close_error = None
        editor_closed = False
        if editor is not None:
            try:
                await editor.wait_for(
                    state="detached", timeout=_COVER_EDITOR_CLOSE_TIMEOUT_MS
                )
                editor_closed = True
            except Exception as exc:
                close_error = exc
        if not editor_closed and upload_tab is not None:
            try:
                await upload_tab.wait_for(
                    state="hidden", timeout=_COVER_EDITOR_CLOSE_TIMEOUT_MS
                )
                editor_closed = True
            except Exception as exc:
                close_error = exc

        if not editor_closed:
            raise _cover_error(
                "Upload cover",
                "wait for cover editor close",
                _COVER_UPLOAD_TAB_CANDIDATES,
                page,
                detail=str(close_error),
            )

        await page.wait_for_timeout(3000)  # wait 3s, fix it later

    async def _set_cover_file_via_chooser(
        self,
        page,
        humanizer,
        upload_tab,
        control_scope,
        file_candidates,
        *,
        detail=None,
    ) -> None:
        """Fallback: click "Upload cover" only because the input was absent.

        The click must be consumed by ``expect_file_chooser`` so the OS chooser
        never stays open.  When the event does not arrive, the click may still
        have revealed the hidden input: resolve it and write it directly instead
        of clicking a second time.
        """
        if upload_tab is None:
            raise _cover_error(
                "Upload cover",
                "select upload tab",
                _COVER_UPLOAD_TAB_CANDIDATES,
                page,
                detail=detail,
            )
        chooser = None
        try:
            async with page.expect_file_chooser(
                timeout=_COVER_CHOOSER_TIMEOUT_MS
            ) as fc_info:
                await _humanized_click(humanizer, upload_tab)
            chooser = await fc_info.value
        except PlaywrightTimeoutError:
            # Only "no chooser event" degrades to resolving the input.  A
            # humanize/native click error must propagate (spec §4.1-7).
            chooser = None
        if chooser is not None:
            try:
                await chooser.set_files(self.thumbnail_path)
            except Exception as exc:
                raise _cover_error(
                    "Upload cover file input",
                    "set cover file",
                    file_candidates,
                    page,
                    detail=f"chooser.set_files failed: {exc}",
                ) from exc
            return
        await page.wait_for_timeout(_COVER_TAB_SETTLE_MS)
        try:
            file_input = await _resolve_candidate(
                control_scope,
                file_candidates,
                control="Upload cover file input",
                stage="set cover file",
                page=page,
            )
            await file_input.set_input_files(self.thumbnail_path)
        except Exception as exc:
            raise _cover_error(
                "Upload cover file input",
                "set cover file",
                file_candidates,
                page,
                detail=(
                    f"no file chooser after the upload tab click: {exc}"
                    + (f" | {detail}" if detail else "")
                ),
            ) from exc

    async def read_result(self, page):
        if self.publish_date != 0:
            # A scheduled item has no published video URL yet; the Content
            # row (title + timezone-qualified time) is the acceptance proof.
            await self._verify_scheduled_post(page)
            tiktok_logger.info(
                "[+] scheduled post: published video link is not available yet"
            )
            return None
        href = await self._find_result_link(
            page, ('a[href*="/video/"]',)
        )
        if href:
            match = re.search(r"/video/(\d+)", href)
            if match:
                return match.group(1)
        raise RuntimeError(
            "TikTok 视频发布结果读取失败：Content 列表未找到匹配当前标题的"
            " video 链接；先核查 Content 列表，避免重复发布。"
        )

    async def wait_media_ready(
        self,
        page,
        *,
        deadline: float | PublishTimeoutBudget | None = None,
        multilogin: bool = False,
    ):
        budget = self._coerce_budget(deadline)
        while True:
            if budget is not None:
                budget.check_pre_click()
            if multilogin:
                _raise_if_login_required(page)
            try:
                # Current Studio exposes the publish button via data-e2e; the
                # legacy class+text form remains only as a fallback.
                post = self.locator_base.locator(
                    '[data-e2e="post_video_button"]'
                )
                post = post.first
                enabled = False
                if await post.count() > 0:
                    try:
                        enabled = await post.is_enabled()
                    except Exception:
                        enabled = False
                    if (
                        str(await post.get_attribute("aria-disabled")).lower()
                        == "true"
                    ):
                        enabled = False
                if enabled:
                    tiktok_logger.info("  [-]video uploaded.")
                    break
                else:
                    tiktok_logger.info("  [-] video uploading...")
                    await asyncio.sleep(2)
                    if await self.locator_base.locator(
                            '[data-e2e="select_video_button"]').count():
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
    upload_entry_selector = (
        '[data-e2e="select_photo_button"], '
        'button:has-text("Select photos"), '
        'input[type="file"][accept*="image"]'
    )

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
        debug=False,
        headless=True,
        no_publish=False,
    ):
        self.image_paths = list(image_paths)
        self.note = note
        self.tags = tags
        self.publish_date = publish_date
        self.account_file = account_file
        self.title = title
        self.options = options
        self.no_publish = no_publish
        self.debug = debug
        self.headless = headless
        self.local_executable_path = LOCAL_CHROME_PATH
        self.locator_base = None
        self.last_item_id = None

    def media_label(self) -> str:
        return f"{len(self.image_paths)} images"

    def result_label(self, item_id) -> str:
        return f"photo post id: {item_id}"

    async def _photo_input_present(self, page) -> bool:
        """Return whether the composer currently exposes an image file input.

        The Title input only appears *after* images are selected, so it cannot
        be the pre-selection mode signal.  The image ``accept`` attribute is the
        stable, language-independent way to avoid feeding images into the video
        input.
        """
        try:
            return (
                await page.locator(
                    'input[type="file"][accept*="image"]'
                ).count()
                > 0
            )
        except Exception:
            return False

    async def ensure_mode(self, page) -> None:
        """Require the photo composer *before* any file selection.

        ``?tab=photo`` normally lands straight on the photo composer.  If the
        image input is not rendered yet, click the ``Photos`` tab once and wait
        for it.  A missing image input means the account is outside the rollout:
        fail instead of feeding images into the video input.
        """
        if await self._photo_input_present(page):
            return

        clicked = False
        humanizer = self._humanizer(page)
        get_by_role = getattr(page, "get_by_role", None)
        if callable(get_by_role):
            for label in (self._PHOTOS_TAB, "照片"):
                try:
                    tab = get_by_role("tab", name=label).first
                    if await tab.count() > 0:
                        await _humanized_click(humanizer, tab)
                        await humanizer.after_navigate()
                        clicked = True
                        break
                except Exception:
                    continue

        if not clicked:
            get_by_text = getattr(page, "get_by_text", None)
            if callable(get_by_text):
                for label in (self._PHOTOS_TAB, "照片"):
                    try:
                        tab = get_by_text(label, exact=True).first
                        if await tab.count() > 0:
                            await _humanized_click(humanizer, tab)
                            await humanizer.after_navigate()
                            clicked = True
                            break
                    except Exception:
                        continue

        for _ in range(10):
            if await self._photo_input_present(page):
                return
            await page.wait_for_timeout(500)

        raise RuntimeError(
            "Photos tab 未覆盖当前账号：上传页没有图片发帖入口，"
            "已在选择文件前中止（不会改用视频 input）。"
        )

    async def attach_media(self, page) -> None:
        scope = await self._resolve_photo_scope(page)
        selector = self._PHOTO_INPUT_SELECTOR
        try:
            present = await scope.locator(selector).count()
        except Exception:
            present = 0
        if not present:
            selector = self._MULTI_INPUT_SELECTOR
        # ``image_paths`` order is the display order; the first one is the cover.
        await scope.locator(selector).first.set_input_files(
            list(self.image_paths)
        )

    async def _resolve_photo_scope(self, page):
        return self.locator_base if self.locator_base is not None else page

    async def _fill_title(self, page) -> None:
        scope = await self._resolve_photo_scope(page)
        humanizer = self._humanizer(page)
        last_exc = None
        for _ in range(20):
            await self.dismiss_blocking_overlays(page)
            for selector in self._PHOTO_TITLE_CANDIDATES:
                locator = scope.locator(selector)
                try:
                    if await locator.count() == 0:
                        continue
                    # ``sel`` clear: focus/click → select all → delete → type.
                    await _humanized_click(humanizer, locator)
                    await humanizer.press("ControlOrMeta+A")
                    await humanizer.press("Delete")
                    await humanizer.type_text(self.title)
                    return
                except Exception as exc:
                    # Ambiguous targets are structural errors: never loop on
                    # them (the humanizer's stillOn gate already refused).
                    # ``ElementUnusableError.reason`` is the machine-readable
                    # form; never match substrings of the message.
                    if str(getattr(exc, "reason", "") or "").startswith(
                        "ambiguous:"
                    ):
                        raise
                    if _maybe_dispatched(exc):
                        raise
                    last_exc = exc
            await page.wait_for_timeout(1000)
        raise RuntimeError(
            "TikTok 图片帖 Title 输入框未找到或无法填写："
            f"tried={list(self._PHOTO_TITLE_CANDIDATES)!r} "
            f"url={_page_url(page)!r} error={last_exc!r}"
        )

    async def _resolve_caption_editor(self, page):
        scope = await self._resolve_photo_scope(page)
        for _ in range(20):
            await self.dismiss_blocking_overlays(page)
            for selector in self._PHOTO_CAPTION_CANDIDATES:
                locator = scope.locator(selector)
                try:
                    if await locator.count() > 0:
                        return locator
                except Exception:
                    continue
            await page.wait_for_timeout(1000)
        raise RuntimeError(
            "TikTok 图片帖 Description 编辑器未找到："
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
        deadline: float | PublishTimeoutBudget | None = None,
        multilogin: bool = False,
    ) -> None:
        budget = self._coerce_budget(deadline)
        while True:
            if budget is not None:
                budget.check_pre_click()
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

                found = await _find_candidate(
                    page,
                    (
                        (
                            'role=button[name=/^(Post|Schedule)$/]',
                            lambda scope: scope.get_by_role(
                                "button",
                                name=re.compile(r"^(Post|Schedule)$"),
                            ),
                        ),
                    ),
                    visible=True,
                )
                post = found[0] if found is not None else None
                post_enabled = False
                if post is not None:
                    try:
                        post_enabled = await post.is_enabled()
                    except Exception:
                        post_enabled = False
                    if (
                        str(await post.get_attribute("aria-disabled")).lower()
                        == "true"
                    ):
                        post_enabled = False
                if processed and post_enabled:
                    tiktok_logger.info("  [-] photos uploaded.")
                    return
            except Exception:
                if multilogin:
                    _raise_if_login_required(page)

            tiktok_logger.info("  [-] photos uploading...")
            await asyncio.sleep(2)

    async def read_result(self, page):
        if self.publish_date != 0:
            await self._verify_scheduled_post(page)
            tiktok_logger.info(
                "[+] scheduled post: published photo link is not available yet"
            )
            return None
        combined = 'a[href*="/photo"], a[href*="/video/"]'
        href = await self._find_result_link(
            page, (combined, self._PHOTO_LINK_SELECTOR)
        )
        if href:
            for pattern in (
                r"item_id=(\d+)",
                r"/photo/(\d+)",
                r"/video/(\d+)",
            ):
                match = re.search(pattern, href)
                if match:
                    return match.group(1)

        raise RuntimeError(
            "TikTok 图片帖发布结果读取失败（按现有契约退出 1；先核查 Content 列表，避免重复发布）：未找到 "
            "Content 列表中的图片/视频链接。"
        )

    async def upload(
        self, playwright: Playwright | None, *, session: BrowserSession | None = None
    ) -> None:
        if session is not None:
            await self.upload_in(session)
            return
        await self.upload_local(playwright)
