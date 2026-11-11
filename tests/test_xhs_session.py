# -*- coding: utf-8 -*-
"""Session preflight, publish-page probe, ``check`` exits and cookie write-back.

Ticket 37 replaces the two publish-chain prechecks with one zero-network local
preflight plus a single authoritative observation: navigate the publish page
once, classify login/verification, then look for the upload anchor.

All tests here are offline.  ``probe_session`` is exercised against a scripted
page, while the CLI tests patch the probe/session seams and assert the exit-code
mapping only.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import tempfile
import time
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import sau_cli
from sau_commands import xiaohongshu as xhs_command
from tests.fakes import FakeBrowser, FakeContext, FakePlaywright
from uploader.xiaohongshu_uploader import main as xhs_main
from utils.browser_session import BrowserSession
from utils.errors import LoginRequiredError

LOGIN_URL = "https://creator.xiaohongshu.com/login?redirect=%2Fpublish"
VERIFICATION_URL = (
    "https://creator.xiaohongshu.com/website-login/captcha?redirectPath=%2Fpublish"
)
PUBLISH_URL = (
    "https://creator.xiaohongshu.com/publish/publish?from=homepage&target=video"
)
LOGIN_COMMAND = "sau xiaohongshu login --account <账号名>"
COOKIE_NAME = "galaxy_creator_session_id"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _write_state(path: Path, *, cookies: list[dict] | None = None) -> None:
    path.write_text(
        json.dumps({"cookies": cookies or [], "origins": []}), encoding="utf-8"
    )


def _cookie(*, expires: float = 0) -> dict:
    return {
        "name": COOKIE_NAME,
        "value": "session-value",
        "domain": ".xiaohongshu.com",
        "path": "/",
        "expires": expires,
    }


class _AsyncCM:
    def __init__(self, value=None, enter_error: BaseException | None = None) -> None:
        self.value = value
        self.enter_error = enter_error
        self.enter_calls = 0
        self.exit_calls = 0
        self.last_exc: tuple | None = None

    async def __aenter__(self):
        self.enter_calls += 1
        if self.enter_error is not None:
            raise self.enter_error
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        self.exit_calls += 1
        self.last_exc = (exc_type, exc, tb)
        return False


class _CliCase(unittest.TestCase):
    def _run(self, argv, *, token="", adspower=""):
        env = {"MLX_API_TOKEN": token, "ADSPOWER_API_KEY": adspower}
        with patch.dict(os.environ, env, clear=False):
            with redirect_stdout(io.StringIO()) as out, redirect_stderr(
                io.StringIO()
            ) as err:
                code = sau_cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def _session_patch(self, module):
        session = Namespace(context=object())
        session_cm = _AsyncCM(session)
        factory = MagicMock(return_value=session_cm)
        return session, session_cm, factory, patch.object(
            module, "browser_session", new=factory
        )


class _ProbeFrame:
    def __init__(self, page: "_ProbePage") -> None:
        self._page = page

    @property
    def url(self) -> str:
        return self._page.url


class _ProbeLocator:
    def __init__(self, count: int) -> None:
        self._count = count

    async def count(self) -> int:
        return self._count

    async def is_visible(self) -> bool:
        return self._count > 0


class _Response:
    def __init__(self, status: int = 200) -> None:
        self.status = status


class _ProbePage:
    """Scripted publish page used by ``probe_session`` tests."""

    def __init__(
        self,
        *,
        final_url: str = PUBLISH_URL,
        status: int = 200,
        goto_error: BaseException | None = None,
        anchor_count: int = 1,
        login_box_count: int = 0,
    ) -> None:
        self.url = "about:blank"
        self.main_frame = _ProbeFrame(self)
        self.final_url = final_url
        self.status = status
        self.goto_error = goto_error
        self.anchor_count = anchor_count
        self.login_box_count = login_box_count
        self.goto_calls: list[tuple[str, dict]] = []
        self.wait_timeouts: list[float] = []
        self.close_calls = 0
        self.closed = False

    async def goto(self, url: str, **kwargs):
        self.goto_calls.append((url, kwargs))
        if self.goto_error is not None:
            raise self.goto_error
        self.url = self.final_url
        return _Response(self.status)

    async def wait_for_timeout(self, milliseconds: float) -> None:
        self.wait_timeouts.append(milliseconds)

    def locator(self, selector: str) -> _ProbeLocator:
        if "login-box" in selector:
            return _ProbeLocator(self.login_box_count)
        if selector in xhs_main.XHS_LOGIN_POSITIVE_SELECTORS:
            return _ProbeLocator(self.anchor_count)
        # Upload anchors are the union of the positive selectors; unknown
        # selectors default to absent so a test must name its anchor.
        return _ProbeLocator(0)

    async def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class _ProbeContext:
    def __init__(self, page: _ProbePage) -> None:
        self.page = page
        self.new_page_calls = 0

    async def new_page(self) -> _ProbePage:
        self.new_page_calls += 1
        return self.page


# ---------------------------------------------------------------------------
# 1. Zero-network local preflight
# ---------------------------------------------------------------------------


class Decision12SessionPreflightTests(unittest.TestCase):
    def test_present_unexpired_cookie_passes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "account.json"
            _write_state(path, cookies=[_cookie(expires=time.time() + 3600)])
            asyncio.run(xhs_main.local_session_preflight(str(path)))

    def test_unknown_expiry_passes(self):
        for expires in (0, -1):
            with self.subTest(expires=expires), tempfile.TemporaryDirectory() as tmp_dir:
                path = Path(tmp_dir) / "account.json"
                _write_state(path, cookies=[_cookie(expires=expires)])
                asyncio.run(xhs_main.local_session_preflight(str(path)))

    def test_missing_account_file_raises_login_required(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "missing.json"
            with self.assertRaises(LoginRequiredError) as ctx:
                asyncio.run(xhs_main.local_session_preflight(str(path)))
        self.assertEqual(ctx.exception.reason, "login")
        self.assertIs(ctx.exception.publish_attempted, False)
        self.assertIn(LOGIN_COMMAND, str(ctx.exception))

    def test_missing_session_cookie_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "account.json"
            _write_state(path, cookies=[{"name": "other", "value": "x"}])
            with self.assertRaises(LoginRequiredError) as ctx:
                asyncio.run(xhs_main.local_session_preflight(str(path)))
        self.assertIn(LOGIN_COMMAND, str(ctx.exception))

    def test_expired_cookie_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "account.json"
            _write_state(path, cookies=[_cookie(expires=time.time() - 60)])
            with self.assertRaises(LoginRequiredError) as ctx:
                asyncio.run(xhs_main.local_session_preflight(str(path)))
        self.assertIn(LOGIN_COMMAND, str(ctx.exception))

    def test_malformed_state_raises_login_required(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "account.json"
            path.write_text("not-json", encoding="utf-8")
            with self.assertRaises(LoginRequiredError):
                asyncio.run(xhs_main.local_session_preflight(str(path)))


# ---------------------------------------------------------------------------
# 2. probe_session: navigate publish page once, classify, check anchor
# ---------------------------------------------------------------------------


class Decision12SessionProbeTests(unittest.TestCase):
    def _probe(self, page: _ProbePage):
        context = _ProbeContext(page)
        result = asyncio.run(xhs_main.probe_session(context))
        self.assertEqual(context.new_page_calls, 1)
        self.assertEqual(page.close_calls, 1)
        return result

    def test_valid_publish_page_with_attached_anchor(self):
        page = _ProbePage(anchor_count=1)
        self.assertEqual(self._probe(page), ("valid", PUBLISH_URL))
        self.assertEqual(page.goto_calls[0][0], PUBLISH_URL)
        kwargs = page.goto_calls[0][1]
        self.assertEqual(kwargs["wait_until"], "domcontentloaded")
        self.assertGreater(kwargs["timeout"], 0)

    def test_login_path_returns_login(self):
        self.assertEqual(
            self._probe(_ProbePage(final_url=LOGIN_URL))[0], "login"
        )

    def test_verification_path_returns_verification(self):
        self.assertEqual(
            self._probe(_ProbePage(final_url=VERIFICATION_URL))[0],
            "verification",
        )

    def test_redirect_path_query_does_not_trigger_login(self):
        url = (
            "https://creator.xiaohongshu.com/publish/publish"
            "?redirectPath=/login&next=/website-login/captcha"
        )
        self.assertEqual(self._probe(_ProbePage(final_url=url))[0], "valid")

    def test_missing_anchor_is_a_structure_error(self):
        page = _ProbePage(anchor_count=0)
        with self.assertRaisesRegex(RuntimeError, "页面结构异常"):
            asyncio.run(xhs_main.probe_session(_ProbeContext(page)))
        self.assertEqual(page.close_calls, 1)

    def test_server_error_is_a_probe_failure(self):
        page = _ProbePage(status=503)
        with self.assertRaises(RuntimeError):
            asyncio.run(xhs_main.probe_session(_ProbeContext(page)))
        self.assertEqual(page.close_calls, 1)

    def test_navigation_error_is_a_probe_failure(self):
        page = _ProbePage(goto_error=RuntimeError("net::ERR_TIMED_OUT"))
        with self.assertRaises(RuntimeError):
            asyncio.run(xhs_main.probe_session(_ProbeContext(page)))
        self.assertEqual(page.close_calls, 1)

    def test_leaving_the_creator_domain_is_a_probe_failure(self):
        page = _ProbePage(final_url="https://example.com/elsewhere")
        with self.assertRaises(RuntimeError):
            asyncio.run(xhs_main.probe_session(_ProbeContext(page)))
        self.assertEqual(page.close_calls, 1)


# ---------------------------------------------------------------------------
# 3. check exits (local: 0 / 10 / 1 and no browser on preflight failure)
# ---------------------------------------------------------------------------


class Decision12SessionCheckLocalTests(_CliCase):
    def setUp(self):
        self.playwright_cm = _AsyncCM(FakePlaywright())
        self.entries = (
            patch.object(
                xhs_command, "async_playwright", lambda: self.playwright_cm
            ),
        )

    def test_preflight_failure_prints_invalid_exits_10_without_browser(self):
        with (
            self.entries[0],
            patch.object(
                xhs_command,
                "local_session_preflight",
                side_effect=LoginRequiredError(
                    f"小红书登录态无效：请运行 {LOGIN_COMMAND} 重新扫码后重试。"
                ),
            ),
        ):
            code, out, err = self._run(
                ["xiaohongshu", "check", "--account", "creator"]
            )

        self.assertEqual(code, 10)
        self.assertEqual(out.strip(), "invalid")
        self.assertIn(LOGIN_COMMAND, err)
        self.assertEqual(self.playwright_cm.enter_calls, 0)

    def test_valid_probe_prints_valid_exits_0_and_writes_back(self):
        fake_playwright = FakePlaywright()
        self.playwright_cm.value = fake_playwright
        save = AsyncMock()
        with (
            self.entries[0],
            patch.object(xhs_command, "local_session_preflight", return_value=None),
            patch.object(
                xhs_command,
                "probe_session",
                new=AsyncMock(return_value=("valid", PUBLISH_URL)),
            ),
            patch.object(
                xhs_command, "save_storage_state_atomic", new=save
            ),
        ):
            code, out, err = self._run(
                ["xiaohongshu", "check", "--account", "creator"]
            )

        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "valid")
        self.assertEqual(err, "")
        save.assert_awaited_once()
        self.assertEqual(len(fake_playwright.chromium.launch_calls), 1)

    def test_classification_hit_prints_invalid_exits_10_and_does_not_write(self):
        self.playwright_cm.value = FakePlaywright()
        save = AsyncMock()
        with (
            self.entries[0],
            patch.object(xhs_command, "local_session_preflight", return_value=None),
            patch.object(
                xhs_command,
                "probe_session",
                new=AsyncMock(return_value=("login", LOGIN_URL)),
            ),
            patch.object(xhs_command, "save_storage_state_atomic", new=save),
        ):
            code, out, err = self._run(
                ["xiaohongshu", "check", "--account", "creator"]
            )

        self.assertEqual(code, 10)
        self.assertEqual(out.strip(), "invalid")
        self.assertIn("小红书登录态无效", err)
        self.assertIn(LOGIN_COMMAND, err)
        self.assertNotIn("publish_attempted=true", err)
        save.assert_not_awaited()

    def test_probe_failure_prints_invalid_exits_1(self):
        self.playwright_cm.value = FakePlaywright()
        with (
            self.entries[0],
            patch.object(xhs_command, "local_session_preflight", return_value=None),
            patch.object(
                xhs_command,
                "probe_session",
                new=AsyncMock(side_effect=RuntimeError("页面结构异常")),
            ),
        ):
            code, out, err = self._run(
                ["xiaohongshu", "check", "--account", "creator"]
            )

        self.assertEqual(code, 1)
        self.assertEqual(out.strip(), "invalid")
        self.assertIn("页面结构异常", err)


class Decision12SessionCheckManagedTests(_CliCase):
    def test_valid_probe_prints_valid_and_never_touches_cookies(self):
        _, _, _, session_patch = self._session_patch(xhs_command)
        save = AsyncMock()
        with (
            patch.object(
                xhs_command, "async_playwright", lambda: _AsyncCM(object())
            ),
            session_patch,
            patch.object(
                xhs_command,
                "probe_session",
                new=AsyncMock(return_value=("valid", PUBLISH_URL)),
            ),
            patch.object(xhs_command, "save_storage_state_atomic", new=save),
            patch.object(
                xhs_command,
                "resolve_account_file",
                new=MagicMock(side_effect=AssertionError("no cookie path")),
            ),
        ):
            code, out, _ = self._run(
                [
                    "xiaohongshu",
                    "check",
                    "--folder-id",
                    "folder",
                    "--profile-id",
                    "profile",
                ],
                token="token",
            )

        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "valid")
        save.assert_not_awaited()

    def test_classification_hit_exits_10(self):
        _, _, _, session_patch = self._session_patch(xhs_command)
        with (
            patch.object(
                xhs_command, "async_playwright", lambda: _AsyncCM(object())
            ),
            session_patch,
            patch.object(
                xhs_command,
                "probe_session",
                new=AsyncMock(return_value=("verification", VERIFICATION_URL)),
            ),
        ):
            code, out, err = self._run(
                [
                    "xiaohongshu",
                    "check",
                    "--folder-id",
                    "folder",
                    "--profile-id",
                    "profile",
                ],
                token="token",
            )

        self.assertEqual(code, 10)
        self.assertEqual(out.strip(), "invalid")
        self.assertIn("人机验证", err)

    def test_probe_failure_exits_1(self):
        _, _, _, session_patch = self._session_patch(xhs_command)
        with (
            patch.object(
                xhs_command, "async_playwright", lambda: _AsyncCM(object())
            ),
            session_patch,
            patch.object(
                xhs_command,
                "probe_session",
                new=AsyncMock(side_effect=RuntimeError("页面结构异常")),
            ),
        ):
            code, out, err = self._run(
                [
                    "xiaohongshu",
                    "check",
                    "--folder-id",
                    "folder",
                    "--profile-id",
                    "profile",
                ],
                token="token",
            )

        self.assertEqual(code, 1)
        self.assertEqual(out.strip(), "invalid")
        self.assertIn("页面结构异常", err)


# ---------------------------------------------------------------------------
# 4. Cookie write-back matrix (by result code)
# ---------------------------------------------------------------------------


class Decision12SessionWriteBackTests(unittest.TestCase):
    def _app(self, tmp_dir: str, *, account_file: str | None) -> xhs_main.XiaoHongShuVideo:
        video = Path(tmp_dir) / "demo.mp4"
        video.write_bytes(b"video")
        return xhs_main.XiaoHongShuVideo(
            title="标题",
            file_path=str(video),
            tags=[],
            publish_date=0,
            account_file=account_file,
        )

    def _run_local(self, app, outcome):
        playwright = FakePlaywright()
        app.validate_upload_args = AsyncMock()
        app.upload_in = AsyncMock(side_effect=outcome)
        save = AsyncMock()
        with (
            patch.object(xhs_main, "_xhs_user_agent", new=AsyncMock(return_value="UA")),
            patch.object(xhs_main, "set_init_script", new=AsyncMock(side_effect=lambda c: c)),
            patch.object(xhs_main, "save_storage_state_atomic", new=save),
        ):
            try:
                asyncio.run(app.upload(playwright))
            except BaseException:
                pass
        return save, playwright

    def test_success_writes_once(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            save, playwright = self._run_local(
                self._app(tmp_dir, account_file="account.json"), None
            )
        save.assert_awaited_once()
        self.assertEqual(len(playwright.chromium.launch_calls), 1)

    def test_runtime_failure_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            save, _ = self._run_local(
                self._app(tmp_dir, account_file="account.json"),
                RuntimeError("publish failed"),
            )
        save.assert_not_awaited()

    def test_result_unknown_does_not_write(self):
        from utils.errors import PublishResultUnknownError

        with tempfile.TemporaryDirectory() as tmp_dir:
            save, _ = self._run_local(
                self._app(tmp_dir, account_file="account.json"),
                PublishResultUnknownError("unknown"),
            )
        save.assert_not_awaited()

    def test_login_required_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            save, _ = self._run_local(
                self._app(tmp_dir, account_file="account.json"),
                LoginRequiredError("login"),
            )
        save.assert_not_awaited()

    def test_managed_session_never_reads_or_writes_cookies(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._app(tmp_dir, account_file=None)
            app.validate_upload_args = AsyncMock()
            app.upload_in = AsyncMock()
            save = AsyncMock()
            preflight = MagicMock()
            with (
                patch.object(xhs_main, "save_storage_state_atomic", new=save),
                patch.object(xhs_main, "local_session_preflight", new=preflight),
            ):
                asyncio.run(
                    app.upload(
                        None,
                        session=BrowserSession(
                            browser=MagicMock(),
                            context=MagicMock(),
                            mode="multilogin",
                        ),
                    )
                )
        save.assert_not_awaited()
        preflight.assert_not_called()


class Decision12SessionAtomicStateTests(unittest.TestCase):
    def test_writes_via_temp_file_and_replace(self):
        class Context:
            async def storage_state(self):
                return {"cookies": [_cookie()], "origins": []}

        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "account.json"
            with patch.object(
                xhs_main.os, "replace", wraps=xhs_main.os.replace
            ) as replace:
                asyncio.run(
                    xhs_main.save_storage_state_atomic(Context(), str(target))
                )
            self.assertEqual(replace.call_count, 1)
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8"))["cookies"][0][
                    "name"
                ],
                COOKIE_NAME,
            )
            self.assertEqual(
                [p.name for p in Path(tmp_dir).iterdir()], ["account.json"]
            )


# ---------------------------------------------------------------------------
# 5. Login recheck: same context, one publish-page probe, atomic write
# ---------------------------------------------------------------------------


class Decision12SessionLoginRecheckTests(unittest.TestCase):
    def _context(self, page):
        class Context:
            def __init__(self):
                self.new_page_calls = 0

            async def new_page(self):
                self.new_page_calls += 1
                return page

            async def storage_state(self):
                return {"cookies": [], "origins": []}

            async def close(self):
                pass

        return Context()

    def _playwright(self, context):
        browser = MagicMock()
        browser.new_context = AsyncMock(return_value=context)
        browser.close = AsyncMock()
        chromium = MagicMock()
        chromium.launch = AsyncMock(return_value=browser)
        return MagicMock(chromium=chromium)

    def test_success_uses_one_browser_and_the_same_context(self):
        page = MagicMock()
        page.url = "https://creator.xiaohongshu.com/login"
        page.goto = AsyncMock()
        context = self._context(page)
        playwright = self._playwright(context)
        probe = AsyncMock(return_value=("valid", PUBLISH_URL))
        save = AsyncMock()

        with tempfile.TemporaryDirectory() as tmp_dir:
            account = str(Path(tmp_dir) / "account.json")
            with (
                patch.object(
                    xhs_main, "async_playwright", lambda: _AsyncCM(playwright)
                ),
                patch.object(
                    xhs_main, "_xhs_user_agent", new=AsyncMock(return_value="UA")
                ),
                patch.object(
                    xhs_main, "set_init_script", new=AsyncMock(side_effect=lambda c: c)
                ),
                patch.object(
                    xhs_main,
                    "_save_xhs_qrcode",
                    new=AsyncMock(return_value={"image_path": str(Path(tmp_dir) / "qr.png")}),
                ),
                patch.object(
                    xhs_main,
                    "classify_blocked",
                    new=AsyncMock(side_effect=["login", None]),
                ),
                patch.object(xhs_main.asyncio, "sleep", new=AsyncMock()),
                patch.object(xhs_main, "probe_session", new=probe),
                patch.object(xhs_main, "save_storage_state_atomic", new=save),
            ):
                result = asyncio.run(
                    xhs_main.xiaohongshu_cookie_gen(
                        account, max_checks=2, poll_interval=0
                    )
                )

        self.assertTrue(result["success"])
        self.assertEqual(playwright.chromium.launch.await_count, 1)
        probe.assert_awaited_once_with(context)
        save.assert_awaited_once_with(context, account)
        self.assertEqual(context.new_page_calls, 1)  # QR page only; probe is mocked

    def test_failed_recheck_is_a_plain_failure_and_does_not_write(self):
        page = MagicMock()
        page.url = "https://creator.xiaohongshu.com/login"
        page.goto = AsyncMock()
        context = self._context(page)
        playwright = self._playwright(context)
        probe = AsyncMock(return_value=("login", LOGIN_URL))
        save = AsyncMock()

        with tempfile.TemporaryDirectory() as tmp_dir:
            account = str(Path(tmp_dir) / "account.json")
            with (
                patch.object(
                    xhs_main, "async_playwright", lambda: _AsyncCM(playwright)
                ),
                patch.object(
                    xhs_main, "_xhs_user_agent", new=AsyncMock(return_value="UA")
                ),
                patch.object(
                    xhs_main, "set_init_script", new=AsyncMock(side_effect=lambda c: c)
                ),
                patch.object(
                    xhs_main,
                    "_save_xhs_qrcode",
                    new=AsyncMock(return_value={"image_path": str(Path(tmp_dir) / "qr.png")}),
                ),
                patch.object(
                    xhs_main,
                    "classify_blocked",
                    new=AsyncMock(side_effect=["login", None]),
                ),
                patch.object(xhs_main.asyncio, "sleep", new=AsyncMock()),
                patch.object(xhs_main, "probe_session", new=probe),
                patch.object(xhs_main, "save_storage_state_atomic", new=save),
            ):
                result = asyncio.run(
                    xhs_main.xiaohongshu_cookie_gen(
                        account, max_checks=2, poll_interval=0
                    )
                )

        self.assertFalse(result["success"])
        save.assert_not_awaited()


# ---------------------------------------------------------------------------
# 6. Static: the two old prechecks are gone
# ---------------------------------------------------------------------------


class Decision13LocalStartupLogTests(_CliCase):
    """Local runs that launch Chromium directly still emit the shared line."""

    def test_local_check_logs_one_local_session_line(self):
        playwright_cm = _AsyncCM(FakePlaywright())
        with (
            patch.object(
                xhs_command, "async_playwright", lambda: playwright_cm
            ),
            patch.object(xhs_command, "local_session_preflight", return_value=None),
            patch.object(
                xhs_command,
                "probe_session",
                new=AsyncMock(return_value=("valid", PUBLISH_URL)),
            ),
            patch.object(
                xhs_command, "save_storage_state_atomic", new=AsyncMock()
            ),
            patch.object(xhs_command, "log_local_session_ready") as log,
        ):
            code, _out, _err = self._run(
                ["xiaohongshu", "check", "--account", "creator"]
            )

        self.assertEqual(code, 0)
        log.assert_called_once()
        self.assertIs(log.call_args.kwargs["headless"], False)
        self.assertTrue(
            str(log.call_args.kwargs["account_file"]).endswith("creator.json")
        )

    def _app(self, kind):
        if kind == "note":
            return xhs_main.XiaoHongShuNote(
                image_paths=["a.png"],
                note="",
                tags=[],
                publish_date=0,
                account_file="/tmp/creator.json",
                title="标题",
            )
        return xhs_main.XiaoHongShuVideo(
            title="标题",
            file_path="demo.mp4",
            tags=[],
            publish_date=0,
            account_file="/tmp/creator.json",
        )

    def test_local_upload_logs_once_for_video_and_note(self):
        for kind in ("video", "note"):
            with self.subTest(kind=kind):
                app = self._app(kind)
                app.validate_upload_args = AsyncMock()
                app.upload_in = AsyncMock()
                with (
                    patch.object(
                        xhs_main, "save_storage_state_atomic", new=AsyncMock()
                    ),
                    patch.object(xhs_main, "log_local_session_ready") as log,
                ):
                    asyncio.run(app.upload(FakePlaywright()))

                log.assert_called_once()
                self.assertEqual(
                    log.call_args.kwargs["account_file"], "/tmp/creator.json"
                )

    def test_managed_upload_never_emits_the_local_line(self):
        app = self._app("video")
        app.validate_upload_args = AsyncMock()
        app.upload_in = AsyncMock()
        session = BrowserSession(
            browser=object(), context=object(), mode="multilogin"
        )

        with patch.object(xhs_main, "log_local_session_ready") as log:
            asyncio.run(app.upload(None, session=session))

        log.assert_not_called()


class Decision12SessionDeletedPrecheckTests(unittest.TestCase):
    def setUp(self):
        self.main_source = Path(xhs_main.__file__).read_text(encoding="utf-8")
        self.command_source = Path(xhs_command.__file__).read_text(encoding="utf-8")

    def test_old_precheck_symbols_are_gone(self):
        for symbol in ("async def cookie_auth", "async def is_logged_in", "_is_xhs_login_completed"):
            with self.subTest(symbol=symbol):
                self.assertNotIn(symbol, self.main_source)

    def test_publish_chain_does_not_reference_old_prechecks(self):
        for symbol in ("cookie_auth", "is_logged_in"):
            with self.subTest(symbol=symbol):
                self.assertNotIn(symbol, self.command_source)


if __name__ == "__main__":
    unittest.main()
