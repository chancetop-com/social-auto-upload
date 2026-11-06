# -*- coding: utf-8 -*-
"""Opt-in form-level smoke test for TikTok Studio (ticket 18, spec §8.2/§8.4).

This is the only TikTok test that touches a real Multilogin Profile and the real
TikTok Studio page.  It validates selector drift and set-then-readback for the
publish options, but it **never publishes**:

* the video case selects ``videos/demo.mp4``, opens ``Settings`` / ``Show more``,
  sets and reads back privacy / comments / reuse / AIGC / brand, then opens the
  cover editor and verifies the ``Upload cover`` entry is reachable;
* the image case probes the ``Photos`` tab first (a missing tab skips only that
  case), selects ``videos/demo.png``, verifies Title / Description / tags and the
  privacy / comments / AIGC / brand controls (never reuse);
* neither case clicks ``Post`` or ``Schedule``, so no post is published.

Environment variables
---------------------
``SAU_TIKTOK_SMOKE=1``
    Required opt-in switch.  Without it the module gate (``setUpModule``)
    raises ``unittest.SkipTest``; the default
    ``python -m unittest discover -s tests`` stays offline and starts no browser.
``MLX_API_TOKEN``
    Multilogin X API token (Bearer).  It is never printed; failure reports
    redact it and any ``Authorization`` header.
``SAU_MLX_FOLDER_ID``
    Folder (workspace) id that owns the profile.
``SAU_MLX_PROFILE_ID``
    Profile id to start.

A missing variable while the switch is on is a configuration **failure** (not a
skip) and names the missing variable.

Prerequisites (spec §10)
------------------------
1. The Multilogin desktop application is running on the same machine, and the
   launcher port is reachable.
2. The Profile uses the **Mimic** kernel (Stealthfox does not support
   Playwright).
3. The Profile UI language is **English (US)** and it is already logged into a
   public, publishable TikTok account.  The smoke test never logs in itself.
4. **Do not run this in parallel with ``SAU_MLX_SMOKE`` on the same Profile.**
   Multilogin allows only one active session per Profile; run the two smoke
   suites serially.
5. Samples are the committed ``videos/demo.mp4`` and ``videos/demo.png``; the
   test adds no binaries.

Side effects
------------
Nothing is published.  The run may still leave an *unpublished* draft in the
composer; the smoke test does not delete it.  Clean it up manually in TikTok
Studio → Content/Drafts.  Option values are not remembered across forms.

Failure matrix (spec §8.2)
--------------------------
========================================  ==================================
Situation                                 Behaviour
========================================  ==================================
``SAU_TIKTOK_SMOKE`` unset                whole module skipped
switch on, variable missing               fail, names the missing variable
not logged in / login / captcha redirect  fail, "先在 Multilogin 登录"
upload page or control missing            fail, control + candidates + URL
account has no ``Photos`` tab             only the image case is skipped
readback mismatch                         fail, option + requested + actual
========================================  ==================================

Run::

    SAU_TIKTOK_SMOKE=1 \
    MLX_API_TOKEN=... \
    SAU_MLX_FOLDER_ID=... \
    SAU_MLX_PROFILE_ID=... \
    python -m unittest tests.test_tiktok_smoke -v

**Execution status: not executed** against a real Profile/account as of this
commit (no MLX token, launcher, or account in the implementation environment).
Do not mark the matrix as verified until the command above has been run.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

SMOKE_FLAG = "SAU_TIKTOK_SMOKE"
TOKEN_ENV = "MLX_API_TOKEN"
FOLDER_ENV = "SAU_MLX_FOLDER_ID"
PROFILE_ENV = "SAU_MLX_PROFILE_ID"
REQUIRED_ENV = (TOKEN_ENV, FOLDER_ENV, PROFILE_ENV)

REPO_ROOT = Path(__file__).resolve().parent.parent
VIDEO_SAMPLE = REPO_ROOT / "videos" / "demo.mp4"
PHOTO_SAMPLE = REPO_ROOT / "videos" / "demo.png"

VIDEO_TITLE = "TikTok browser smoke — do not publish"
PHOTO_TITLE = "TikTok photo smoke"
PHOTO_NOTE = "TikTok photo smoke — do not publish"
SMOKE_TAGS = ["tiktoksmoke"]

# Safe values: nothing is published, and the least-exposure option is used.
# ``branded_content`` is explicitly requested as ``False`` because TikTok
# disables "Branded content" for private posts; the production brand step
# normalizes it to an explicit unchecked state and the smoke reads it back.
SAFE_PRIVACY = "only-me"
SAFE_OPTIONS = dict(
    privacy=SAFE_PRIVACY,
    allow_comments=False,
    allow_reuse=False,
    aigc=True,
    your_brand=True,
    branded_content=False,
)

# Bounded waits so a drifted selector fails in minutes, not at the 15-minute
# publish budget.  The smoke never waits for a publish at all.
_FORM_TIMEOUT_MS = 30_000
_OPTION_READY_TIMEOUT_MS = 120_000
_COVER_READY_TIMEOUT_MS = 120_000
_PHOTO_PROCESSED_TIMEOUT_MS = 120_000


class SmokeConfigError(RuntimeError):
    """Configuration is missing even though the smoke test was enabled."""


@dataclass(frozen=True)
class SmokeConfig:
    token: str
    folder_id: str
    profile_id: str


def smoke_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Opt-in only: exactly ``SAU_TIKTOK_SMOKE=1`` turns the smoke test on."""
    env = os.environ if environ is None else environ
    return env.get(SMOKE_FLAG, "").strip() == "1"


def load_smoke_config(environ: Mapping[str, str] | None = None) -> SmokeConfig:
    """Read the required smoke-test variables without ever echoing values."""
    env = os.environ if environ is None else environ
    missing = [name for name in REQUIRED_ENV if not env.get(name, "").strip()]
    if missing:
        raise SmokeConfigError(
            f"{SMOKE_FLAG}=1 但缺少环境变量：{', '.join(missing)}；"
            "未执行任何浏览器请求。请设置后重试。"
        )

    return SmokeConfig(
        token=env[TOKEN_ENV].strip(),
        folder_id=env[FOLDER_ENV].strip(),
        profile_id=env[PROFILE_ENV].strip(),
    )


_AUTHORIZATION_RE = re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?\S+")


def _redact(text: str, token: str) -> str:
    """Remove the token and Authorization headers from diagnostic text."""
    cleaned = _AUTHORIZATION_RE.sub(r"\1<redacted>", text)
    if token:
        cleaned = cleaned.replace(token, "<redacted>")
    return cleaned


def describe_failure(
    *,
    stage: str,
    control: str,
    candidates,
    page_url: str,
    detail,
    token: str,
) -> str:
    """Build a diagnosable failure report without leaking the token."""
    tried = list(candidates or ())
    return _redact(
        "TikTok smoke failed | "
        f"stage={stage} | control={control} | tried={tried!r} | "
        f"url={page_url or '<unknown>'!r} | detail={detail}",
        token,
    )


def _login_failure(
    *, stage: str, page_url: str, token: str, detail: str = ""
) -> str:
    suffix = f" | detail={detail}" if detail else ""
    return _redact(
        "TikTok 冒烟失败 | "
        f"stage={stage} | 当前未登录或遇到登录/验证码跳转："
        "请先在 Multilogin 应用中登录 Profile（English (US)）后重试。"
        f" | url={page_url or '<unknown>'!r}{suffix}",
        token,
    )


# ---------------------------------------------------------------------------
# Opt-in gate: ``setUpModule`` raises ``unittest.SkipTest`` so both
# ``unittest discover`` and an explicit ``python -m unittest
# tests.test_tiktok_smoke`` record one module-level skip.  The production
# browser stack is imported only when the switch is on, so the default offline
# suite never even loads patchright for this module.
# ---------------------------------------------------------------------------

SMOKE_ENABLED = smoke_enabled()

if SMOKE_ENABLED:
    from patchright.async_api import async_playwright  # noqa: E402

    from uploader.tk_uploader.main_chrome import (  # noqa: E402
        TiktokNote,
        TiktokPublishOptions,
        TiktokVideo,
        _COVER_EDIT_CANDIDATES,
        _COVER_UPLOAD_TAB_CANDIDATES,
        _find_candidate,
        _page_url,
        _raise_if_login_required,
        _read_switch_state,
        _read_toggle_state,
        _resolve_candidate,
        _select_probe_page,
        _set_privacy_option,
        _set_toggle_option,
        _upload_entry_present,
        is_logged_in,
        normalize_privacy_label,
    )
    from uploader.tk_uploader.tk_config import (  # noqa: E402
        TIKTOK_ENTRY_WAIT_MS,
        TIKTOK_PHOTO_UPLOAD_URL,
        TIKTOK_UPLOAD_ENTRY_SELECTOR,
        TIKTOK_UPLOAD_URL,
    )
    from utils.browser_session import browser_session  # noqa: E402
    from utils.errors import LoginRequiredError  # noqa: E402
    from utils.log import tiktok_logger  # noqa: E402
    from utils.multilogin import MultiloginTarget  # noqa: E402

    def _warn_if_parallel_smoke() -> None:
        """Remind the operator that both smoke suites use the Profile serially."""
        if os.environ.get("SAU_MLX_SMOKE", "").strip() == "1":
            tiktok_logger.warning(
                "SAU_MLX_SMOKE=1 同时存在：严禁与 MLX smoke 并行使用同一 "
                "Multilogin Profile；请串行运行。"
            )


def setUpModule() -> None:
    if not SMOKE_ENABLED:
        raise unittest.SkipTest(
            "TikTok smoke test is opt-in: set SAU_TIKTOK_SMOKE=1 "
            "(see module header)."
        )
    _warn_if_parallel_smoke()


class TiktokSmokeGuardTests(unittest.TestCase):
    """Offline guards for the opt-in switch and the redaction helpers.

    These run only when ``SAU_TIKTOK_SMOKE=1`` (the module gate above), but
    they need no Multilogin credentials, so a misconfigured invocation can still
    prove the guard logic before the real cases fail.
    """

    TOKEN = "ticket18-secret-token"
    FOLDER_ID = "11111111-1111-4111-8111-111111111111"
    PROFILE_ID = "22222222-2222-4222-8222-222222222222"

    def test_smoke_is_disabled_when_flag_is_absent(self):
        self.assertFalse(smoke_enabled({}))

    def test_smoke_is_enabled_only_by_exact_one(self):
        self.assertTrue(smoke_enabled({"SAU_TIKTOK_SMOKE": "1"}))
        self.assertFalse(smoke_enabled({"SAU_TIKTOK_SMOKE": "0"}))
        self.assertFalse(smoke_enabled({"SAU_TIKTOK_SMOKE": "true"}))
        self.assertFalse(smoke_enabled({"SAU_TIKTOK_SMOKE": ""}))

    def test_missing_environment_names_every_required_variable(self):
        with self.assertRaises(SmokeConfigError) as raised:
            load_smoke_config({"SAU_TIKTOK_SMOKE": "1"})

        message = str(raised.exception)
        for name in REQUIRED_ENV:
            self.assertIn(name, message)
        self.assertIn("未执行任何浏览器请求", message)
        self.assertNotIn(self.TOKEN, message)

    def test_partial_environment_reports_only_the_missing_names(self):
        env = {
            "SAU_TIKTOK_SMOKE": "1",
            "MLX_API_TOKEN": self.TOKEN,
            "SAU_MLX_FOLDER_ID": self.FOLDER_ID,
        }
        with self.assertRaises(SmokeConfigError) as raised:
            load_smoke_config(env)

        message = str(raised.exception)
        self.assertIn("SAU_MLX_PROFILE_ID", message)
        self.assertNotIn("SAU_MLX_FOLDER_ID", message)
        self.assertNotIn(self.TOKEN, message)

    def test_complete_environment_loads_values(self):
        env = {
            "SAU_TIKTOK_SMOKE": "1",
            "MLX_API_TOKEN": self.TOKEN,
            "SAU_MLX_FOLDER_ID": self.FOLDER_ID,
            "SAU_MLX_PROFILE_ID": self.PROFILE_ID,
        }
        config = load_smoke_config(env)

        self.assertEqual(config.token, self.TOKEN)
        self.assertEqual(config.folder_id, self.FOLDER_ID)
        self.assertEqual(config.profile_id, self.PROFILE_ID)

    def test_failure_report_has_diagnostics_but_never_the_token(self):
        report = describe_failure(
            stage="resolve",
            control="privacy",
            candidates=('data-e2e=video_visibility_container', "role=combobox"),
            page_url="https://www.tiktok.com/tiktokstudio/upload",
            detail=(
                f"boom Authorization: Bearer {self.TOKEN} and token={self.TOKEN}"
            ),
            token=self.TOKEN,
        )

        self.assertIn("stage=resolve", report)
        self.assertIn("control=privacy", report)
        self.assertIn("role=combobox", report)
        self.assertIn("tiktokstudio/upload", report)
        self.assertNotIn(self.TOKEN, report)
        self.assertNotIn("Bearer " + self.TOKEN, report)
        self.assertIn("<redacted>", report)


class TiktokFormSmokeTests(unittest.TestCase):
    """Real-stack form check.  Never clicks ``Post`` or ``Schedule``."""

    config: SmokeConfig | None = None
    config_error: str | None = None

    @classmethod
    def setUpClass(cls) -> None:
        # Missing configuration is a *failure*, not a skip: an enabled smoke
        # test with no variables must not look like "nothing to do".
        try:
            cls.config = load_smoke_config()
        except SmokeConfigError as exc:
            cls.config = None
            cls.config_error = str(exc)

    def setUp(self) -> None:
        if self.config_error:
            self.fail(self.config_error)
        assert self.config is not None  # narrowed for type checkers

        for sample in (VIDEO_SAMPLE, PHOTO_SAMPLE):
            if not sample.is_file():
                self.fail(
                    f"TikTok 冒烟样本缺失：{sample}；"
                    "该文件应随仓库提供，请勿在冒烟测试中新增二进制。"
                )

    # -- shared helpers -----------------------------------------------------

    def _fail(
        self,
        *,
        stage: str,
        control: str,
        candidates=(),
        page=None,
        detail="",
    ) -> None:
        assert self.config is not None
        self.fail(
            describe_failure(
                stage=stage,
                control=control,
                candidates=candidates,
                page_url=_page_url(page) if page is not None else "",
                detail=detail,
                token=self.config.token,
            )
        )

    def _fail_login(self, *, stage: str, page=None, detail="") -> None:
        assert self.config is not None
        self.fail(
            _login_failure(
                stage=stage,
                page_url=_page_url(page) if page is not None else "",
                token=self.config.token,
                detail=detail,
            )
        )

    async def _ensure_logged_in(self, context) -> None:
        try:
            logged_in = await is_logged_in(context)
        except Exception as exc:  # 5xx/timeout/unrecognised structure
            self._fail_login(
                stage="login-check",
                detail=f"登录检测异常，请先在 Multilogin 登录：{exc}",
            )
            return
        if not logged_in:
            self._fail_login(stage="login-check")

    def _check_not_login(self, page, stage: str) -> None:
        try:
            _raise_if_login_required(page)
        except LoginRequiredError:
            self._fail_login(stage=stage, page=page)

    async def _open(self, page, uploader, stage: str) -> None:
        try:
            await uploader.open_upload_page(page, multilogin=True)
        except LoginRequiredError:
            self._fail_login(stage=stage, page=page)
        except Exception as exc:
            self._fail(
                stage=stage,
                control="upload page",
                candidates=(uploader.upload_url,),
                page=page,
                detail=exc,
            )

    async def _assert_upload_entry(self, page, stage: str) -> None:
        if not await _upload_entry_present(page, TIKTOK_ENTRY_WAIT_MS):
            self._fail(
                stage=stage,
                control="upload entry",
                candidates=(TIKTOK_UPLOAD_ENTRY_SELECTOR,),
                page=page,
                detail="上传入口未出现（选择文件前中止）",
            )

    async def _attach(self, page, uploader, stage: str) -> None:
        try:
            await uploader.attach_media(page)
        except Exception as exc:
            self._fail(
                stage=stage,
                control="media file input",
                candidates=('button:has-text("Select video"):visible',),
                page=page,
                detail=exc,
            )
        self._check_not_login(page, f"{stage}-after")

    async def _wait_for_caption_form(self, page, uploader, stage: str) -> None:
        editor = uploader.locator_base.locator(
            "div.public-DraftEditor-content"
        )
        try:
            await editor.first.wait_for(
                state="visible", timeout=_FORM_TIMEOUT_MS
            )
        except Exception as exc:
            self._fail(
                stage=stage,
                control="caption editor",
                candidates=("div.public-DraftEditor-content",),
                page=page,
                detail=exc,
            )

    async def _expand_advanced_settings(self, page, uploader, stage: str) -> None:
        try:
            await uploader._expand_advanced_settings(page)
        except Exception as exc:
            self._fail(
                stage=stage,
                control="Settings / Show more",
                candidates=(
                    '[data-e2e="advanced_settings_container"]',
                    ".more-btn",
                    'text="Show more"',
                ),
                page=page,
                detail=exc,
            )

    async def _wait_for_control(self, uploader, name: str, *, timeout_ms: int):
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            control = await uploader._resolve_single_control(name)
            if control is not None:
                return control
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(1)

    async def _wait_for_candidate(
        self, page, scope, candidates, *, control: str, stage: str, timeout_ms: int
    ):
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            found = await _find_candidate(scope, candidates)
            if found is not None:
                return found[0]
            if time.monotonic() >= deadline:
                self._fail(
                    stage=stage,
                    control=control,
                    candidates=tuple(label for label, _ in candidates),
                    page=page,
                    detail="候选在预算内未出现",
                )
            await asyncio.sleep(1)

    async def _resolve_options(self, page, uploader, stage: str):
        # Wait for the first option to render before the one-shot resolver, so
        # an upload still processing does not look like selector drift.
        await self._wait_for_control(
            uploader, "privacy", timeout_ms=_OPTION_READY_TIMEOUT_MS
        )
        try:
            return await uploader.resolve_option_controls(page)
        except Exception as exc:
            self._fail(
                stage=stage,
                control="publish options",
                candidates=(
                    "see per-option candidates in detail",
                ),
                page=page,
                detail=exc,
            )

    async def _apply_options(self, page, uploader, controls, stage: str) -> None:
        """Set every requested option through the production helpers."""
        url = _page_url(page)
        try:
            if uploader.options.privacy is not None:
                await _set_privacy_option(
                    controls.privacy, uploader.options.privacy, url=url
                )
            if uploader.options.allow_comments is not None:
                await _set_toggle_option(
                    controls.comments,
                    uploader.options.allow_comments,
                    option="allow_comments",
                    url=url,
                )
            if uploader.options.allow_reuse is not None:
                await _set_toggle_option(
                    controls.reuse,
                    uploader.options.allow_reuse,
                    option="allow_reuse",
                    url=url,
                )
            if uploader.options.aigc is not None:
                await uploader._set_aigc_option(
                    controls.aigc,
                    uploader.options.aigc,
                    page=page,
                    url=url,
                )
            if uploader._brand_requested():
                await uploader._apply_brand_options(controls, url=url)
        except AssertionError:
            raise
        except Exception as exc:
            self._fail(
                stage=stage,
                control="publish options",
                candidates=(
                    "see option=... candidates=... in detail",
                ),
                page=page,
                detail=exc,
            )
        self._check_not_login(page, f"{stage}-after")

    async def _assert_readback(
        self, page, controls, *, names, stage: str
    ) -> None:
        """Read the final page state back and report option/requested/actual."""
        assert self.config is not None
        values = {}
        try:
            if "privacy" in names:
                values["privacy"] = normalize_privacy_label(
                    await controls.privacy.read_text()
                )
            if "comments" in names:
                values["comments"] = await _read_toggle_state(controls.comments)
            if "reuse" in names:
                values["reuse"] = await _read_toggle_state(controls.reuse)
            if "aigc" in names:
                values["aigc"] = await _read_switch_state(controls.aigc)
            if "brand_switch" in names:
                values["brand_switch"] = await _read_switch_state(
                    controls.brand_switch
                )
            if "your_brand" in names:
                values["your_brand"] = await _read_toggle_state(
                    controls.your_brand
                )
            if "branded_content" in names:
                values["branded_content"] = await _read_toggle_state(
                    controls.branded_content
                )
        except Exception as exc:
            self._fail(
                stage=stage,
                control="readback",
                page=page,
                detail=exc,
            )
            return

        requested = {
            "privacy": SAFE_PRIVACY,
            "comments": SAFE_OPTIONS["allow_comments"],
            "reuse": SAFE_OPTIONS["allow_reuse"],
            "aigc": SAFE_OPTIONS["aigc"],
            "brand_switch": True,
            "your_brand": SAFE_OPTIONS["your_brand"],
            "branded_content": SAFE_OPTIONS["branded_content"],
        }
        control_lookup = {
            "privacy": controls.privacy,
            "comments": controls.comments,
            "reuse": controls.reuse,
            "aigc": controls.aigc,
            "brand_switch": controls.brand_switch,
            "your_brand": controls.your_brand,
            "branded_content": controls.branded_content,
        }
        for name in names:
            self.assertEqual(
                values.get(name),
                requested[name],
                msg=self._readback_message(
                    name=name,
                    actual=values.get(name),
                    requested=requested[name],
                    control=control_lookup[name],
                    page=page,
                    stage=stage,
                ),
            )

    def _readback_message(
        self,
        *,
        name: str,
        actual,
        requested,
        control,
        page,
        stage: str,
    ) -> str:
        assert self.config is not None
        return _redact(
            "TikTok 回读不一致 | "
            f"option={name} | requested={requested!r} | actual={actual!r} | "
            f"stage={stage} | candidates={tuple(getattr(control, 'candidates', ()) or ())!r} | "
            f"url={_page_url(page)!r}",
            self.config.token,
        )

    def _assert_not_published(self, page) -> None:
        """The smoke must end on the upload page, never the content list."""
        current = _page_url(page).lower()
        self.assertNotIn(
            "/tiktokstudio/content",
            current,
            "TikTok 冒烟测试不允许发布：页面已跳到 Content 列表",
        )
        self.assertIn(
            "/tiktokstudio/upload",
            current,
            "TikTok 冒烟测试必须停留在上传页（未发布）",
        )

    # -- video case ---------------------------------------------------------

    def test_video_form_options_and_cover_entry(self) -> None:
        asyncio.run(self._video_case())

    async def _video_case(self) -> None:
        assert self.config is not None
        target = MultiloginTarget(
            folder_id=self.config.folder_id,
            profile_id=self.config.profile_id,
        )
        uploader = TiktokVideo(
            VIDEO_TITLE,
            str(VIDEO_SAMPLE),
            [],
            0,  # no schedule: apply_schedule is never called
            None,  # Multilogin mode never reads/writes a cookie file
            thumbnail_path=None,  # only the entry is checked; no cover upload
            options=TiktokPublishOptions(**SAFE_OPTIONS),
        )

        async with async_playwright() as playwright:
            async with browser_session(
                playwright,
                headless=True,
                account_file=None,
                multilogin=target,
            ) as session:
                self.assertEqual(session.mode, "multilogin")

                await self._ensure_logged_in(session.context)
                page, _owned = await _select_probe_page(session.context)

                await self._open(page, uploader, stage="video-open")
                self._check_not_login(page, "video-open")

                # 1. The upload entry must be present on the real upload page.
                self.assertEqual(_page_url(page).split("?")[0], TIKTOK_UPLOAD_URL)
                await self._assert_upload_entry(page, "video-upload-entry")

                # 2. Select videos/demo.mp4 through the production path.
                await self._attach(page, uploader, stage="video-attach")

                # 3. Wait until the composer form is rendered.
                await self._wait_for_caption_form(
                    page, uploader, "video-caption-form"
                )

                # 4. Expand Settings / Show more, then resolve every control
                #    from the production ordered candidates.
                await self._expand_advanced_settings(
                    page, uploader, "video-advanced-settings"
                )
                controls = await self._resolve_options(
                    page, uploader, "video-resolve-options"
                )

                # 5. Set a safe value, then read it back.
                await self._apply_options(
                    page, uploader, controls, "video-apply-options"
                )
                await self._assert_readback(
                    page,
                    controls,
                    names=(
                        "privacy",
                        "comments",
                        "reuse",
                        "aigc",
                        "brand_switch",
                        "your_brand",
                        "branded_content",
                    ),
                    stage="video-readback",
                )

                # 6. Open the cover editor and verify "Upload cover" is
                #    reachable.  Never upload a cover, never save, never Post.
                await self._assert_cover_entry(page, uploader)

                # 7. Hard stop: the page must still be the composer.
                self._check_not_login(page, "video-final")
                self._assert_not_published(page)

    async def _assert_cover_entry(self, page, uploader) -> None:
        base = uploader.locator_base
        try:
            edit_cover = await self._wait_for_candidate(
                page,
                base,
                _COVER_EDIT_CANDIDATES,
                control="Edit cover",
                stage="video-cover-open",
                timeout_ms=_COVER_READY_TIMEOUT_MS,
            )
            await edit_cover.click()
            upload_tab = await _resolve_candidate(
                base,
                _COVER_UPLOAD_TAB_CANDIDATES,
                control="Upload cover",
                stage="video-cover-tab",
                page=page,
            )
            if not await upload_tab.is_visible():
                self._fail(
                    stage="video-cover-tab",
                    control="Upload cover",
                    candidates=tuple(
                        label for label, _ in _COVER_UPLOAD_TAB_CANDIDATES
                    ),
                    page=page,
                    detail="Upload cover 入口存在但不可见",
                )
        except AssertionError:
            raise
        except Exception as exc:
            self._fail(
                stage="video-cover-entry",
                control="Edit cover / Upload cover",
                candidates=tuple(
                    label
                    for label, _ in (
                        _COVER_EDIT_CANDIDATES + _COVER_UPLOAD_TAB_CANDIDATES
                    )
                ),
                page=page,
                detail=exc,
            )
        finally:
            # Close the editor without saving.  Leaving it open is harmless
            # (nothing is published), so this is best-effort only.
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass

    # -- image case ---------------------------------------------------------

    def test_photo_form_metadata_and_options(self) -> None:
        asyncio.run(self._photo_case())

    async def _photo_case(self) -> None:
        assert self.config is not None
        target = MultiloginTarget(
            folder_id=self.config.folder_id,
            profile_id=self.config.profile_id,
        )
        photo_options = dict(SAFE_OPTIONS)
        photo_options["allow_reuse"] = None  # photo posts have no reuse control
        uploader = TiktokNote(
            [str(PHOTO_SAMPLE)],
            PHOTO_NOTE,
            list(SMOKE_TAGS),
            0,  # no schedule
            None,  # Multilogin mode
            title=PHOTO_TITLE,
            options=TiktokPublishOptions(**photo_options),
        )

        async with async_playwright() as playwright:
            async with browser_session(
                playwright,
                headless=True,
                account_file=None,
                multilogin=target,
            ) as session:
                self.assertEqual(session.mode, "multilogin")

                await self._ensure_logged_in(session.context)
                page, _owned = await _select_probe_page(session.context)

                # 1. Probe the Photos tab through the production ensure_mode.
                #    Missing = rollout gap, so only *this* case is skipped.
                try:
                    await uploader.open_upload_page(page, multilogin=True)
                except LoginRequiredError:
                    self._fail_login(stage="photo-open", page=page)
                    return
                except RuntimeError as exc:
                    # ``ensure_mode`` conflates "no Photos tab" (rollout) with
                    # "tab exists but the form did not render" (a code/page
                    # failure).  Only the former is a skip.
                    if "Photos tab" in str(exc) and not await self._photos_tab_present(
                        page, uploader
                    ):
                        self.skipTest(
                            "当前账号未被 Photos tab 灰度覆盖，"
                            f"只跳过图片用例（不是代码失败）：{exc}"
                        )
                    self._fail(
                        stage="photo-open",
                        control="photo form",
                        candidates=(
                            TIKTOK_PHOTO_UPLOAD_URL,
                            'text="Photos"',
                            'input[placeholder*="catchy"]',
                            'input[type="file"][accept*="image"]',
                        ),
                        page=page,
                        detail=exc,
                    )
                    return
                except Exception as exc:
                    self._fail(
                        stage="photo-open",
                        control="upload page",
                        candidates=(TIKTOK_PHOTO_UPLOAD_URL,),
                        page=page,
                        detail=exc,
                    )
                    return

                self._check_not_login(page, "photo-open")
                self.assertEqual(
                    _page_url(page).split("?")[0], TIKTOK_PHOTO_UPLOAD_URL.split("?")[0]
                )

                # 2. Select videos/demo.png (the first image is the cover).
                await self._attach(page, uploader, stage="photo-attach")

                # 3. Fill Title / Description / tags through production steps,
                #    then verify the rendered inputs.
                try:
                    await uploader.fill_metadata(page)
                except Exception as exc:
                    self._fail(
                        stage="photo-metadata",
                        control="Title / Description",
                        candidates=tuple(
                            list(uploader._PHOTO_TITLE_CANDIDATES)
                            + list(uploader._PHOTO_CAPTION_CANDIDATES)
                        ),
                        page=page,
                        detail=exc,
                    )
                await self._assert_photo_metadata(page, uploader)

                # 4. First image must be processed and shown as the cover.
                await self._wait_for_photo_processed(page)

                # 5. Expand Settings / Show more and resolve options.  Reuse is
                #    deliberately absent from the requested set.
                self.assertNotIn(
                    "reuse",
                    uploader._requested_option_names(),
                    "图片帖冒烟不得请求或触碰 Allow reuse of content",
                )
                await self._expand_advanced_settings(
                    page, uploader, "photo-advanced-settings"
                )
                controls = await self._resolve_options(
                    page, uploader, "photo-resolve-options"
                )
                await self._apply_options(
                    page, uploader, controls, "photo-apply-options"
                )
                await self._assert_readback(
                    page,
                    controls,
                    names=(
                        "privacy",
                        "comments",
                        "aigc",
                        "brand_switch",
                        "your_brand",
                        "branded_content",
                    ),
                    stage="photo-readback",
                )

                # 6. Hard stop: never Post / Schedule.
                self._check_not_login(page, "photo-final")
                self._assert_not_published(page)

    async def _photos_tab_present(self, page, uploader=None) -> bool:
        """Return ``True`` when the upload page renders a Photos mode entry."""
        scopes = [page]
        base = getattr(uploader, "locator_base", None) if uploader else None
        if base is not None:
            scopes.append(base)
        for scope in scopes:
            try:
                if await scope.get_by_text("Photos", exact=True).count() > 0:
                    return True
            except Exception:
                pass
            try:
                get_by_role = getattr(scope, "get_by_role", None)
                if callable(get_by_role):
                    if await get_by_role("tab", name="Photos").count() > 0:
                        return True
            except Exception:
                pass
        return False

    async def _assert_photo_metadata(self, page, uploader) -> None:
        scope = (
            uploader.locator_base
            if uploader.locator_base is not None
            else page
        )
        title_locator = None
        for selector in uploader._PHOTO_TITLE_CANDIDATES:
            locator = scope.locator(selector)
            try:
                if await locator.count():
                    title_locator = locator.first
                    break
            except Exception:
                continue
        if title_locator is None:
            self._fail(
                stage="photo-metadata",
                control="photo Title",
                candidates=tuple(uploader._PHOTO_TITLE_CANDIDATES),
                page=page,
            )
            return

        actual_title = await title_locator.input_value()
        self.assertEqual(
            actual_title,
            PHOTO_TITLE,
            msg=(
                "TikTok 冒烟失败 | stage=photo-metadata | control=photo Title | "
                f"requested={PHOTO_TITLE!r} | actual={actual_title!r} | "
                f"url={_page_url(page)!r}"
            ),
        )

        caption = None
        for selector in uploader._PHOTO_CAPTION_CANDIDATES:
            locator = scope.locator(selector)
            try:
                if await locator.count():
                    caption = locator.first
                    break
            except Exception:
                continue
        if caption is None:
            self._fail(
                stage="photo-metadata",
                control="photo Description",
                candidates=tuple(uploader._PHOTO_CAPTION_CANDIDATES),
                page=page,
            )
            return

        description = await caption.inner_text()
        self.assertIn(
            PHOTO_NOTE,
            description,
            msg=(
                "TikTok 冒烟失败 | stage=photo-metadata | "
                "control=photo Description | "
                f"requested={PHOTO_NOTE!r} | actual={description!r} | "
                f"url={_page_url(page)!r}"
            ),
        )
        for tag in SMOKE_TAGS:
            self.assertIn(
                tag,
                description,
                msg=(
                    "TikTok 冒烟失败 | stage=photo-metadata | control=tags | "
                    f"requested={tag!r} | actual={description!r} | "
                    f"url={_page_url(page)!r}"
                ),
            )

    async def _wait_for_photo_processed(self, page) -> None:
        """Bounded wait for the production processed/cover signals."""
        deadline = time.monotonic() + _PHOTO_PROCESSED_TIMEOUT_MS / 1000
        while True:
            try:
                if await page.locator("div[data-id]").count() > 0:
                    return
                if await page.get_by_text("Cover", exact=True).count() > 0:
                    return
            except Exception:
                pass

            if time.monotonic() >= deadline:
                self._fail(
                    stage="photo-processed",
                    control="first image / Cover",
                    candidates=(
                        "div[data-id]",
                        'text="Cover"',
                    ),
                    page=page,
                    detail="图片未在预算内完成处理（第 1 张图应为封面）",
                )
                return
            await asyncio.sleep(2)


__all__ = [
    "SmokeConfig",
    "SmokeConfigError",
    "describe_failure",
    "load_smoke_config",
    "smoke_enabled",
]
