# -*- coding: utf-8 -*-
"""Risk classification and local/managed parity — tickets 33/35.

Three seams are exercised, all offline:

* ``utils.blocked.classify`` — the generic, rules-as-data classifier (URL path
  only, longest prefix first, visible login box only when the path misses);
* ``uploader.xiaohongshu_uploader.main.classify_blocked`` — the XHS rules
  (``/website-login/captcha`` → verification, ``/website-login`` → login,
  ``/login`` → login, visible ``login-box`` → login);
* the two upload entry points driven with the scripted page doubles from
  ticket 28 — C1 (right after ``goto``) and C2 (every wait-loop round).

The core regression is local mode: a bad/expired cookie lands on the login page
and must produce ``LoginRequiredError(reason="login", publish_attempted=False)``
→ exit ``10``.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import sau_cli
import uploader.xiaohongshu_uploader.main as xhs_main
from tests.fakes_clock import FakeClock
from tests.fakes_xhs_dom import FakeLocator, RecordingPage
from utils import blocked
from utils.errors import LoginRequiredError

LOGIN_URL = "https://creator.xiaohongshu.com/login?redirect=%2Fpublish"
VERIFICATION_URL = (
    "https://creator.xiaohongshu.com/website-login/captcha?redirectPath=%2Fpublish"
)
PUBLISH_URL_VIDEO = (
    "https://creator.xiaohongshu.com/publish/publish?from=homepage&target=video"
)
PUBLISH_URL_NOTE = (
    "https://creator.xiaohongshu.com/publish/publish?from=homepage&target=image"
)
LOGIN_BOX = xhs_main.XHS_LOGIN_BOX_SELECTOR
VIDEO_UPLOAD_INPUT = "div.upload-content input.upload-input"
NOTE_IMAGE_INPUT = "div.upload-content input.upload-input"
TITLE_INPUT = 'input[placeholder*="填写标题"]'
VIDEO_PREVIEW_INPUT = "input.upload-input"

#: 与 utils.dom 的 ``_DEFAULT_FACTS`` 同形的可见元素事实。
VISIBLE_FACTS = {
    "tag": "input",
    "display": "block",
    "visibility": "visible",
    "opacity": 1.0,
    "ariaHidden": None,
    "ancestorAriaHidden": False,
    "disabled": False,
    "disabledClass": False,
    "pointerEvents": "auto",
    "contentEditable": None,
    "readOnly": False,
    "isConnected": True,
}

PUBLISH_ATTEMPTED_SUFFIX = "发布可能已发出：重跑前请先确认该笔记是否存在。"


def _box(*, count: int = 1, visible: bool = True) -> FakeLocator:
    return FakeLocator(
        "login-box",
        count=count,
        visible=visible,
        computed_style=dict(VISIBLE_FACTS),
    )


def _absent_box() -> FakeLocator:
    return _box(count=0, visible=False)


class _FileInput(FakeLocator):
    """File input double that records ``set_input_files``."""

    def __init__(self, name: str = "file-input") -> None:
        super().__init__(name, computed_style=dict(VISIBLE_FACTS))
        self.files: list[object] = []

    async def set_input_files(self, files, **kwargs) -> None:
        self.files.append(files)


def _fast_humanize():
    return patch.dict(os.environ, {"HUMANIZE": "0"})


def _video_app(**overrides):
    values = {
        "title": "标题",
        "file_path": "demo.mp4",
        "tags": [],
        "publish_date": 0,
        "account_file": "account.json",
        "no_publish": True,
    }
    values.update(overrides)
    return xhs_main.XiaoHongShuVideo(**values)


def _note_app(**overrides):
    values = {
        "image_paths": ["a.png"],
        "note": "",
        "tags": [],
        "publish_date": 0,
        "account_file": "account.json",
        "title": "标题",
        "no_publish": True,
    }
    values.update(overrides)
    return xhs_main.XiaoHongShuNote(**values)


# ---------------------------------------------------------------------------
# 1. Generic classifier: path matrix, query strings, DOM fallback, read errors
# ---------------------------------------------------------------------------


class ClassifierPathTests(unittest.TestCase):
    def test_xhs_rules_pin_the_paths_and_the_login_box(self):
        rules = xhs_main.XHS_BLOCKED_RULES
        self.assertEqual(rules.verification_paths, ("/website-login/captcha",))
        self.assertEqual(rules.login_paths, ("/website-login", "/login"))
        self.assertEqual(rules.login_box_selector, LOGIN_BOX)

    def test_path_matrix(self):
        cases = (
            (
                "https://creator.xiaohongshu.com/website-login/captcha?scene=publish",
                "verification",
            ),
            ("https://creator.xiaohongshu.com/website-login", "login"),
            ("https://creator.xiaohongshu.com/website-login/", "login"),
            ("https://creator.xiaohongshu.com/website-login/phone", "login"),
            ("https://creator.xiaohongshu.com/login", "login"),
            ("https://creator.xiaohongshu.com/login/step2", "login"),
            (LOGIN_URL, "login"),
            (VERIFICATION_URL, "verification"),
        )
        for url, expected in cases:
            with self.subTest(url=url):
                # 无 selector 脚本：path 命中时绝不允许查 DOM。
                page = RecordingPage(url=url)
                self.assertEqual(
                    asyncio.run(blocked.classify(page, xhs_main.XHS_BLOCKED_RULES)),
                    expected,
                )

    def test_publish_path_is_not_a_block(self):
        page = RecordingPage(url=PUBLISH_URL_VIDEO, selectors={LOGIN_BOX: _absent_box()})
        self.assertIsNone(
            asyncio.run(blocked.classify(page, xhs_main.XHS_BLOCKED_RULES))
        )

    def test_redirect_path_query_does_not_trigger_login(self):
        url = (
            "https://creator.xiaohongshu.com/publish/publish"
            "?redirectPath=/login&next=/website-login/captcha"
        )
        page = RecordingPage(url=url, selectors={LOGIN_BOX: _absent_box()})
        self.assertIsNone(asyncio.run(xhs_main.classify_blocked(page)))

    def test_path_prefix_needs_a_segment_boundary(self):
        page = RecordingPage(
            url="https://creator.xiaohongshu.com/loginx", selectors={LOGIN_BOX: _absent_box()}
        )
        self.assertIsNone(asyncio.run(xhs_main.classify_blocked(page)))

    def test_longest_prefix_wins(self):
        # /website-login/captcha also matches the shorter /website-login prefix;
        # the longer verification prefix must win.
        page = RecordingPage(url=VERIFICATION_URL)
        self.assertEqual(asyncio.run(xhs_main.classify_blocked(page)), "verification")

    def test_visible_login_box_is_the_dom_fallback(self):
        page = RecordingPage(url=PUBLISH_URL_VIDEO, selectors={LOGIN_BOX: _box()})
        self.assertEqual(asyncio.run(xhs_main.classify_blocked(page)), "login")

    def test_hidden_login_box_is_not_a_block(self):
        page = RecordingPage(
            url=PUBLISH_URL_VIDEO, selectors={LOGIN_BOX: _box(visible=False)}
        )
        self.assertIsNone(asyncio.run(xhs_main.classify_blocked(page)))

    def test_path_hit_short_circuits_the_dom(self):
        # RecordingPage raises UnscriptedSelectorError on any locator() call;
        # a DOM read would be swallowed as "no block" and fail this assertion.
        page = RecordingPage(url=LOGIN_URL)
        self.assertEqual(asyncio.run(xhs_main.classify_blocked(page)), "login")

    def test_main_frame_url_is_the_authority(self):
        page = RecordingPage(url=PUBLISH_URL_VIDEO, main_frame_url=LOGIN_URL)
        self.assertEqual(asyncio.run(xhs_main.classify_blocked(page)), "login")

    def test_url_read_failure_means_no_block(self):
        class BrokenFramePage:
            @property
            def main_frame(self):
                raise RuntimeError("frame detached")

            url = PUBLISH_URL_VIDEO

        class BrokenUrlPage:
            class main_frame:
                @property
                def url(self):
                    raise RuntimeError("navigation in progress")

            @property
            def url(self):
                raise RuntimeError("navigation in progress")

        for page in (BrokenFramePage(), BrokenUrlPage()):
            with self.subTest(page=type(page).__name__):
                self.assertIsNone(
                    asyncio.run(blocked.classify(page, xhs_main.XHS_BLOCKED_RULES))
                )

    def test_dom_read_failure_means_no_block(self):
        class RaisingPage:
            class main_frame:
                url = PUBLISH_URL_VIDEO

            def locator(self, selector):
                raise RuntimeError("page closed")

        self.assertIsNone(
            asyncio.run(blocked.classify(RaisingPage(), xhs_main.XHS_BLOCKED_RULES))
        )

    def test_injected_visibility_check_shapes(self):
        rules = xhs_main.XHS_BLOCKED_RULES
        page = RecordingPage(
            url=PUBLISH_URL_VIDEO, selectors={LOGIN_BOX: _absent_box()}
        )

        async def two_arg(locator, role):
            self.assertEqual(role, "visible")
            return True

        self.assertEqual(
            asyncio.run(
                blocked.classify(page, rules, visibility_check=two_arg)
            ),
            "login",
        )
        self.assertEqual(
            asyncio.run(
                blocked.classify(page, rules, visibility_check=lambda _loc: True)
            ),
            "login",
        )
        self.assertIsNone(
            asyncio.run(
                blocked.classify(page, rules, visibility_check=lambda _loc: False)
            )
        )

    def test_empty_page_url_means_no_block(self):
        class NoUrlPage:
            url = ""
            main_frame = None

        self.assertIsNone(
            asyncio.run(blocked.classify(NoUrlPage(), xhs_main.XHS_BLOCKED_RULES))
        )


# ---------------------------------------------------------------------------
# 2. Message matrix: four messages × two modes, suffix, no profile id
# ---------------------------------------------------------------------------


class BlockedMessageTests(unittest.TestCase):
    def test_local_messages(self):
        self.assertEqual(
            xhs_main._blocked_message("login", "local", publish_attempted=False),
            "小红书登录态无效：请运行 sau xiaohongshu login --account <账号名> "
            "重新扫码后重试。",
        )
        self.assertEqual(
            xhs_main._blocked_message(
                "verification", "local", publish_attempted=False
            ),
            "小红书要求人机验证：请在浏览器中完成验证后重试。",
        )

    def test_managed_login_message_names_the_provider(self):
        for mode, app in (("multilogin", "Multilogin"), ("adspower", "AdsPower")):
            with self.subTest(mode=mode):
                message = xhs_main._blocked_message(
                    "login", mode, publish_attempted=False
                )
                self.assertEqual(
                    message,
                    f"小红书登录态无效：请在 {app} 中登录该 Profile 后重试。",
                )
                self.assertNotIn("profile_id", message)
                self.assertNotIn("<账号名>", message)

    def test_managed_verification_message_names_the_provider(self):
        for mode, app in (("multilogin", "Multilogin"), ("adspower", "AdsPower")):
            with self.subTest(mode=mode):
                message = xhs_main._blocked_message(
                    "verification", mode, publish_attempted=False
                )
                self.assertEqual(
                    message,
                    f"小红书要求人机验证：请在 {app} 中完成该 Profile 的验证后重试。",
                )
                self.assertNotIn("profile_id", message)

    def test_adspower_is_named_and_multilogin_is_not(self):
        for kind in ("login", "verification"):
            with self.subTest(kind=kind):
                message = xhs_main._blocked_message(
                    kind, "adspower", publish_attempted=False
                )
                self.assertIn("AdsPower", message)
                self.assertNotIn("Multilogin", message)

    def test_publish_attempted_appends_the_suffix(self):
        for kind in ("login", "verification"):
            for mode in ("local", "multilogin", "adspower"):
                with self.subTest(kind=kind, mode=mode):
                    base = xhs_main._blocked_message(
                        kind, mode, publish_attempted=False
                    )
                    with_suffix = xhs_main._blocked_message(
                        kind, mode, publish_attempted=True
                    )
                    self.assertEqual(with_suffix, base + PUBLISH_ATTEMPTED_SUFFIX)
                    self.assertNotIn(PUBLISH_ATTEMPTED_SUFFIX, base)


class LoginRequiredErrorFieldTests(unittest.TestCase):
    def test_legacy_positional_message_still_works(self):
        exc = LoginRequiredError("旧文案")
        self.assertEqual(str(exc), "旧文案")
        self.assertEqual(exc.reason, "login")
        self.assertFalse(exc.publish_attempted)

    def test_fields_are_kept(self):
        exc = LoginRequiredError(
            "文案", reason="verification", publish_attempted=True
        )
        self.assertEqual(str(exc), "文案")
        self.assertEqual(exc.reason, "verification")
        self.assertTrue(exc.publish_attempted)


# ---------------------------------------------------------------------------
# 3. C1 / C2 + the core local-mode regression through the real exit mapping
# ---------------------------------------------------------------------------


class _LoginRedirectPage(RecordingPage):
    """Publish navigation that lands on the login page (bad/expired cookie)."""

    async def goto(self, url: str, **kwargs) -> None:
        await super().goto(url, **kwargs)
        self.url = LOGIN_URL
        self.main_frame.url = LOGIN_URL


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        patcher = _fast_humanize()
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_c1_raises_login_required_with_fields(self):
        page = _LoginRedirectPage(url=LOGIN_URL)
        app = _video_app()

        with self.assertRaises(LoginRequiredError) as ctx:
            asyncio.run(app.upload_video_content(page, mode="local"))

        exc = ctx.exception
        self.assertEqual(exc.reason, "login")
        self.assertIs(exc.publish_attempted, False)
        self.assertIn("sau xiaohongshu login --account <账号名>", str(exc))
        # 未派发：连发布按钮都没查，更没有点击。
        self.assertEqual(page.goto_calls[0][0], PUBLISH_URL_VIDEO)

    def test_video_preview_loop_hit_is_not_swallowed(self):
        class _FlipAfterPreviewWait(RecordingPage):
            async def wait_for_selector(self, selector, **kwargs):
                await super().wait_for_selector(selector, **kwargs)
                self.url = LOGIN_URL
                self.main_frame.url = LOGIN_URL
                # 宽 except 的典型异常：轮询这一轮没就绪。
                raise RuntimeError("preview not ready")

        page = _FlipAfterPreviewWait(
            url=PUBLISH_URL_VIDEO,
            selectors={
                VIDEO_UPLOAD_INPUT: _FileInput("video-input"),
                VIDEO_PREVIEW_INPUT: _FileInput("video-preview"),
                LOGIN_BOX: _absent_box(),
            },
        )

        app = _video_app()
        clock = FakeClock()
        with clock.patch(xhs_main):
            with self.assertRaises(LoginRequiredError) as ctx:
                asyncio.run(app.upload_video_content(page, mode="local"))

        self.assertEqual(ctx.exception.reason, "login")
        self.assertIs(ctx.exception.publish_attempted, False)
        self.assertGreaterEqual(clock.sleep_calls, [2.0])

    def test_note_title_wait_hit_is_not_swallowed(self):
        class _FlipAfterTitleWait(FakeLocator):
            def __init__(self, page: RecordingPage) -> None:
                super().__init__("title-input", computed_style=dict(VISIBLE_FACTS))
                self._page = page

            async def wait_for(self, **kwargs) -> None:
                self._page.url = LOGIN_URL
                self._page.main_frame.url = LOGIN_URL
                raise RuntimeError("title not ready")

        page = RecordingPage(url=PUBLISH_URL_NOTE)
        page._selectors[NOTE_IMAGE_INPUT] = _FileInput("note-input")
        page._selectors[TITLE_INPUT] = _FlipAfterTitleWait(page)
        page._selectors[LOGIN_BOX] = _absent_box()

        app = _note_app()
        clock = FakeClock()
        with clock.patch(xhs_main):
            with self.assertRaises(LoginRequiredError) as ctx:
                asyncio.run(app.upload_note_content(page, mode="local"))

        self.assertEqual(ctx.exception.reason, "login")
        self.assertIs(ctx.exception.publish_attempted, False)


class LocalModeExitTests(unittest.TestCase):
    def setUp(self):
        patcher = _fast_humanize()
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_local_bad_cookie_lands_on_login_page_exits_10(self):
        page = _LoginRedirectPage(url=LOGIN_URL)
        app = _video_app()

        async def dispatch(_args):
            await app.upload_video_content(page, mode="local")
            return 0

        import io

        err = io.StringIO()
        with (
            patch.object(sau_cli, "dispatch", new=dispatch),
            patch.object(sau_cli, "credentials_conflict", return_value=False),
            redirect_stderr(err),
        ):
            code = sau_cli.main(["xiaohongshu", "check"])

        stderr = err.getvalue()
        self.assertEqual(code, 10)
        self.assertIn("小红书登录态无效", stderr)
        self.assertIn("sau xiaohongshu login --account <账号名>", stderr)
        self.assertNotIn("publish_attempted=true", stderr)


# ---------------------------------------------------------------------------
# 4. Mode parity static assertions (deleted gates / deleted dead code)
# ---------------------------------------------------------------------------


class DeletedCodeTests(unittest.TestCase):
    def setUp(self):
        self.source = Path(xhs_main.__file__).read_text(encoding="utf-8")

    def test_deleted_symbols_are_gone(self):
        for symbol in (
            "_XHS_PUBLISH_FAILURE_KEYWORDS",
            "XhsPublishRejectedError",
            "_find_publish_failure",
            "XHS_PUBLISH_SUCCESS_URL_PATTERN",
            "_LOGIN_URL_MARKERS",
            "_raise_if_login_required",
            "handle_upload_error",
            "check_original_declaration",
        ):
            with self.subTest(symbol=symbol):
                self.assertNotIn(symbol, self.source)

    def test_no_multilogin_boolean_gate(self):
        self.assertNotIn("if multilogin:", self.source)
        self.assertNotIn("multilogin: bool", self.source)
        self.assertNotIn("multilogin=session.managed", self.source)

    def test_mode_parameter_on_both_entry_points(self):
        self.assertIn(
            "async def upload_video_content(self, page: Page, *, mode: str)",
            self.source,
        )
        self.assertIn(
            "async def upload_note_content(self, page: Page, *, mode: str)",
            self.source,
        )
        self.assertEqual(self.source.count("mode=session.mode"), 2)

    def test_both_entry_points_call_c1_and_c2(self):
        # C1/C2/C3 在两个入口内联；ARM/FIRE/OBSERVE 是共享 helper。
        self.assertEqual(self.source.count("# C3："), 2)
        self.assertEqual(self.source.count("await _wait_for_arm("), 4)
        self.assertEqual(self.source.count("await _fire_publish("), 2)
        self.assertEqual(self.source.count("await _observe_publish("), 2)
        self.assertGreaterEqual(self.source.count("_check_blocked("), 12)


if __name__ == "__main__":
    unittest.main()
