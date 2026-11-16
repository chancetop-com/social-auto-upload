"""Rednote routing, session isolation and inherited publish safety contracts."""

from __future__ import annotations

import asyncio
import io
import json
import os
import tempfile
import time
import unittest
from contextlib import ExitStack, asynccontextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import sau_cli
from sau_commands import rednote as command
from uploader.rednote_uploader import main as rednote
from uploader.xiaohongshu_uploader import main as xhs
from tests.test_xhs_submit import _note_page, _video_page, _humanizer
from utils.errors import LoginRequiredError, PublishResultUnknownError


class RednoteCliTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "MLX_API_TOKEN": "",
                "ADSPOWER_API_KEY": "",
                "SAU_REDNOTE_CREATOR_BASE_URL": "",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_four_commands_and_english_local_defaults(self):
        parser = sau_cli.build_parser()
        with tempfile.NamedTemporaryFile(suffix=".png") as media:
            for action, flags in (
                ("login", []),
                ("check", []),
                ("upload-video", ["--file", media.name, "--title", "Hello"]),
                ("upload-note", ["--images", media.name, "--title", "Hello"]),
            ):
                with self.subTest(action=action):
                    args = parser.parse_args(
                        ["rednote", action, "--account", "a", *flags]
                    )
                    self.assertEqual(args.platform, "rednote")
                    self.assertFalse(args.headless)
        self.assertEqual(rednote.REDNOTE_CONTEXT_KWARGS["locale"], "en-US")
        self.assertEqual(
            rednote.REDNOTE_CONTEXT_KWARGS["extra_http_headers"]["Accept-Language"],
            "en-US,en;q=0.9",
        )
        self.assertEqual(xhs.XHS_CONTEXT_KWARGS["locale"], "zh-CN")

    def test_login_uses_an_independent_account_file(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("sau_commands.arguments.BASE_DIR", Path(tmp)),
            patch.object(
                command, "rednote_setup", AsyncMock(return_value={"success": True})
            ) as setup,
        ):
            asyncio.run(command.login_rednote_account("same-label", headless=False))
            account = Path(setup.call_args.args[0])
            self.assertEqual(account, Path(tmp) / "cookies/rednote_same-label.json")
            self.assertEqual(setup.call_args.kwargs["headless"], False)
            self.assertFalse(
                (Path(tmp) / "cookies/xiaohongshu_same-label.json").exists()
            )

    def test_no_cookie_check_exits_10_without_starting_browser(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("sau_commands.arguments.BASE_DIR", Path(tmp)),
            patch.object(command, "async_playwright") as browser,
            redirect_stdout(io.StringIO()) as stdout,
            redirect_stderr(io.StringIO()) as stderr,
        ):
            code = sau_cli.main(["rednote", "check", "--account", "missing"])
        self.assertEqual(code, 10)
        self.assertEqual(stdout.getvalue().strip(), "invalid")
        self.assertIn("sau rednote login", stderr.getvalue())
        self.assertNotIn("sau xiaohongshu", stderr.getvalue())
        browser.assert_not_called()

    def test_upload_cli_passes_metadata_and_dry_run_does_not_claim_submission(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as media:
            for action, flags, upload_name in (
                (
                    "upload-video",
                    ["--file", media.name, "--desc", "English body"],
                    "upload_rednote_video",
                ),
                (
                    "upload-note",
                    ["--images", media.name, "--note", "English body"],
                    "upload_rednote_note",
                ),
            ):
                with (
                    self.subTest(action=action),
                    patch.object(command, upload_name, AsyncMock()) as upload,
                    redirect_stdout(io.StringIO()) as stdout,
                ):
                    code = sau_cli.main(
                        [
                            "rednote",
                            action,
                            "--account",
                            "a",
                            "--title",
                            "Hello",
                            "--tags",
                            "travel,life",
                            "--no-publish",
                            *flags,
                        ]
                    )
                self.assertEqual(code, 0)
                request = upload.call_args.args[0]
                self.assertEqual(request.account_name, "a")
                self.assertEqual(request.tags, ["travel", "life"])
                self.assertTrue(request.no_publish)
                self.assertIn("not published", stdout.getvalue())
                self.assertNotIn("submitted", stdout.getvalue())

    def test_managed_check_uses_provider_without_cookie_access(self):
        for env, flags, mode in (
            (
                {"MLX_API_TOKEN": "test-token"},
                ["--folder-id", "folder", "--profile-id", "profile"],
                "multilogin",
            ),
            ({"ADSPOWER_API_KEY": "test-key"}, ["--profile-id", "profile"], "adspower"),
        ):
            with (
                self.subTest(mode=mode),
                patch.dict(os.environ, env),
                patch.object(command, "_check_managed_rednote", AsyncMock()) as check,
                patch.object(command, "resolve_account_file") as account,
                redirect_stdout(io.StringIO()) as stdout,
            ):
                code = sau_cli.main(["rednote", "check", *flags])
                self.assertEqual(code, 0)
                self.assertEqual(stdout.getvalue().strip(), "valid")
                self.assertEqual(check.call_args.args[0].mode, mode)
                account.assert_not_called()

    def test_managed_login_and_invalid_declarations_fail_before_browser(self):
        with (
            patch.dict(os.environ, {"ADSPOWER_API_KEY": "test-key"}),
            patch.object(command, "login_rednote_account") as login,
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(sau_cli.main(["rednote", "login", "--account", "a"]), 1)
            login.assert_not_called()
        with (
            tempfile.NamedTemporaryFile(suffix=".png") as media,
            patch.object(command, "upload_rednote_note") as upload,
            redirect_stderr(io.StringIO()),
        ):
            code = sau_cli.main(
                [
                    "rednote",
                    "upload-note",
                    "--account",
                    "a",
                    "--images",
                    media.name,
                    "--title",
                    "Hello",
                    "--content-type",
                    "repost",
                ]
            )
            self.assertEqual(code, 2)
            upload.assert_not_called()


class RednoteSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_headed_login_allows_sms_and_saves_only_after_probe(self):
        for probe_result in ("valid", "login"):
            with (
                self.subTest(probe=probe_result),
                tempfile.TemporaryDirectory() as tmp,
                ExitStack() as stack,
            ):
                page = SimpleNamespace(
                    url="https://creator.rednote.com/publish/publish", goto=AsyncMock()
                )
                context = SimpleNamespace(
                    new_page=AsyncMock(return_value=page), close=AsyncMock()
                )
                browser = SimpleNamespace(
                    new_context=AsyncMock(return_value=context), close=AsyncMock()
                )
                launch = AsyncMock(return_value=browser)
                playwright = MagicMock()
                playwright.__aenter__.return_value = SimpleNamespace(
                    chromium=SimpleNamespace(launch=launch)
                )
                stack.enter_context(
                    patch.object(rednote, "async_playwright", return_value=playwright)
                )
                stack.enter_context(
                    patch.object(
                        rednote, "_rednote_user_agent", AsyncMock(return_value="Chrome")
                    )
                )
                stack.enter_context(
                    patch.object(
                        rednote, "set_init_script", AsyncMock(return_value=context)
                    )
                )
                stack.enter_context(
                    patch.object(
                        rednote,
                        "Humanizer",
                        return_value=SimpleNamespace(after_navigate=AsyncMock()),
                    )
                )
                stack.enter_context(
                    patch.object(
                        rednote,
                        "classify_blocked",
                        AsyncMock(side_effect=["login", None]),
                    )
                )
                stack.enter_context(
                    patch.object(
                        rednote,
                        "probe_session",
                        AsyncMock(return_value=(probe_result, page.url)),
                    )
                )
                stack.enter_context(patch.object(rednote.asyncio, "sleep", AsyncMock()))
                qr = stack.enter_context(
                    patch.object(rednote, "_save_rednote_qrcode", AsyncMock())
                )
                save = stack.enter_context(
                    patch.object(rednote, "save_storage_state_atomic", AsyncMock())
                )
                account = str(Path(tmp) / "rednote_a.json")
                result = await rednote.rednote_cookie_gen(account, headless=False)
                self.assertEqual(result["success"], probe_result == "valid")
                self.assertEqual(
                    page.goto.call_args.kwargs["wait_until"], "domcontentloaded"
                )
                self.assertEqual(
                    browser.new_context.call_args.kwargs["locale"], "en-US"
                )
                qr.assert_not_awaited()
                if probe_result == "valid":
                    save.assert_awaited_once_with(context, account)
                else:
                    save.assert_not_awaited()
                context.close.assert_awaited_once()
                browser.close.assert_awaited_once()

    async def test_creator_settings_are_independent_and_checked_at_call_time(self):
        with patch.dict(
            os.environ,
            {
                "SAU_XHS_CREATOR_BASE_URL": "https://xhs.example",
                "SAU_REDNOTE_CREATOR_BASE_URL": "https://rednote.example/",
            },
        ):
            self.assertEqual(
                rednote._build_rednote_creator_url("/login"),
                "https://rednote.example/login",
            )
            self.assertEqual(
                xhs._build_xhs_creator_url("/login"), "https://xhs.example/login"
            )
            page = SimpleNamespace(
                url="https://rednote.example/publish/publish",
                goto=AsyncMock(),
                close=AsyncMock(),
                wait_for_timeout=AsyncMock(),
                locator=MagicMock(
                    return_value=SimpleNamespace(count=AsyncMock(return_value=1))
                ),
            )
            context = SimpleNamespace(new_page=AsyncMock(return_value=page))
            with patch.object(
                rednote, "classify_blocked", AsyncMock(return_value=None)
            ):
                kind, _ = await rednote.probe_session(context)
            self.assertEqual(kind, "valid")
            self.assertTrue(
                page.goto.call_args.args[0].startswith("https://rednote.example/")
            )
            page.close.assert_awaited_once()

    async def test_preflight_accepts_only_live_rednote_session_cookies(self):
        base = {
            "name": "web_session",
            "value": "test",
            "domain": ".rednote.com",
            "expires": time.time() + 3600,
        }
        cases = [
            (base, True),
            ({**base, "name": "galaxy_creator_session_id"}, False),
            ({**base, "domain": "creator.rednote.com", "expires": -1}, True),
            ({**base, "domain": ".xiaohongshu.com"}, False),
            ({**base, "domain": ".rednote.com.invalid"}, False),
            ({**base, "domain": "rednote.com"}, False),
            ({**base, "value": ""}, False),
            ({**base, "expires": time.time() - 1}, False),
        ]
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(os.environ, {"SAU_REDNOTE_CREATOR_BASE_URL": ""}),
        ):
            account = Path(tmp) / "state.json"
            for cookie, valid in cases:
                with self.subTest(cookie=cookie):
                    account.write_text(json.dumps({"cookies": [cookie]}))
                    if valid:
                        await rednote.local_session_preflight(account)
                    else:
                        with self.assertRaises(LoginRequiredError):
                            await rednote.local_session_preflight(account)
            # A stale duplicate must not hide a newer live session cookie.
            account.write_text(json.dumps({"cookies": [{**base, "expires": 1}, base]}))
            await rednote.local_session_preflight(account)

    async def test_probe_rejects_foreign_domain_even_with_upload_anchor(self):
        page = SimpleNamespace(
            url="https://creator.xiaohongshu.com/publish/publish",
            goto=AsyncMock(),
            close=AsyncMock(),
            wait_for_timeout=AsyncMock(),
        )
        context = SimpleNamespace(new_page=AsyncMock(return_value=page))
        with (
            patch.dict(os.environ, {"SAU_REDNOTE_CREATOR_BASE_URL": ""}),
            self.assertRaises(RuntimeError),
        ):
            await rednote.probe_session(context)
        page.close.assert_awaited_once()

    async def test_managed_upload_never_resolves_local_cookie_file(self):
        for kind in ("video", "note"):
            with self.subTest(kind=kind):
                session = SimpleNamespace(context=object(), mode="adspower")

                @asynccontextmanager
                async def open_session(*args, _session=session, **kwargs):
                    self.assertIsNone(kwargs["account_file"])
                    yield _session

                @asynccontextmanager
                async def playwright():
                    yield object()

                uploader = SimpleNamespace(**{f"rednote_upload_{kind}": AsyncMock()})
                request = SimpleNamespace(headless=False)
                with (
                    patch.object(
                        command, f"_build_{kind}_uploader", return_value=uploader
                    ),
                    patch.object(command, "browser_session", open_session),
                    patch.object(command, "async_playwright", playwright),
                    patch.object(command, "resolve_account_file") as account,
                ):
                    result = await getattr(command, f"upload_rednote_{kind}")(
                        request, target=object()
                    )
                self.assertIsNone(result)
                account.assert_not_called()
                getattr(uploader, f"rednote_upload_{kind}").assert_awaited_once_with(
                    session=session
                )

    async def test_qrcode_panel_does_not_require_chinese_text(self):
        qr = SimpleNamespace(
            count=AsyncMock(return_value=1), is_visible=AsyncMock(return_value=True)
        )
        qr.first = qr
        box = SimpleNamespace(wait_for=AsyncMock(), locator=MagicMock(return_value=qr))
        box.first = box
        page = SimpleNamespace(locator=MagicMock(return_value=box))
        await rednote._open_rednote_qrcode_panel(page)
        box.locator.assert_called_once_with("img.css-1lhmg90")


class RednotePublishTests(unittest.IsolatedAsyncioTestCase):
    async def test_dry_run_video_and_note_reach_ready_without_dispatch(self):
        for kind in ("note", "video"):
            with self.subTest(kind=kind), ExitStack() as stack:
                stack.enter_context(
                    patch.dict(
                        os.environ,
                        {"HUMANIZE": "0", "SAU_REDNOTE_CREATOR_BASE_URL": ""},
                    )
                )
                page = _note_page() if kind == "note" else _video_page()
                common = dict(
                    title="English title",
                    tags=[],
                    publish_date=0,
                    account_file=None,
                    no_publish=True,
                )
                if kind == "note":
                    app = rednote.RednoteNote(
                        image_paths=["a.png"], note="English body", **common
                    )
                else:
                    app = rednote.RednoteVideo(
                        file_path="a.mp4", desc="English body", **common
                    )
                stack.enter_context(
                    patch.object(app, "_humanizer", return_value=_humanizer(page))
                )
                stack.enter_context(patch.object(app, "fill_meta", AsyncMock()))
                stack.enter_context(
                    patch.object(app, "_verify_schedule_before_fire", AsyncMock())
                )
                stack.enter_context(
                    patch.object(rednote, "_run_dom_quiet_gate", AsyncMock())
                )
                stack.enter_context(
                    patch.object(rednote, "_clear_known_overlays", AsyncMock())
                )
                fire = stack.enter_context(
                    patch.object(rednote, "_fire_publish", AsyncMock())
                )
                await getattr(app, f"upload_{kind}_content")(page, mode="local")
                self.assertIn("creator.rednote.com", page.url)
                self.assertIn(
                    f"target={'image' if kind == 'note' else 'video'}", page.url
                )
                app.fill_meta.assert_awaited_once()
                fire.assert_not_awaited()
                app._verify_schedule_before_fire.assert_awaited_once()

    async def test_publish_outcome_requires_creator_origin(self):
        for url, succeeds in (
            ("https://creator.rednote.com/publish/success", True),
            ("https://creator.xiaohongshu.com/publish/success", False),
            ("about:blank", False),
        ):
            with (
                self.subTest(url=url),
                patch.dict(os.environ, {"SAU_REDNOTE_CREATOR_BASE_URL": ""}),
                patch.object(rednote, "_check_blocked", AsyncMock()),
            ):
                budget = MagicMock()
                budget.remaining_seconds.return_value = 0
                budget.timeout_error.return_value = PublishResultUnknownError("unknown")
                operation = rednote._observe_publish(
                    SimpleNamespace(url=url),
                    budget=budget,
                    publish_clicked=True,
                    mode="local",
                )
                if succeeds:
                    await operation
                else:
                    with self.assertRaises(PublishResultUnknownError):
                        await operation


if __name__ == "__main__":
    unittest.main()
