# -*- coding: utf-8 -*-
"""TikTok privacy / interaction option contract (ticket 12).

All tests are offline: no browser, no network, no cookie files.  The uploader
option steps are driven through the small async control seam in
``uploader.tk_uploader.main_chrome``; no test asserts on DOM/CSS.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import os
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import sau_cli
from sau_commands import tiktok as tiktok_command
from uploader.tk_uploader import main_chrome as tk_main
from uploader.tk_uploader.main_chrome import (
    TiktokPublishOptions,
    TiktokVideo,
)

TOKEN = "SENTINEL-MLX-TOKEN-ticket12"


def _subparser(parser: argparse.ArgumentParser, platform: str, action: str | None = None):
    for item in parser._actions:
        if isinstance(item, argparse._SubParsersAction):
            if platform in item.choices:
                platform_parser = item.choices[platform]
                if action is None:
                    return platform_parser
                for nested in platform_parser._actions:
                    if isinstance(nested, argparse._SubParsersAction):
                        return nested.choices[action]
    raise AssertionError(f"parser not found: {platform}/{action}")


def _option_strings(parser: argparse.ArgumentParser) -> set[str]:
    return set(parser._option_string_actions)


def _run(argv, token=TOKEN):
    environ = {"MLX_API_TOKEN": token}
    with patch.dict(os.environ, environ):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(
            io.StringIO()
        ) as err:
            code = sau_cli.main(argv)
    return code, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# Parser contract
# ---------------------------------------------------------------------------


class TiktokOptionsParserTests(unittest.TestCase):
    def test_upload_video_registers_three_option_flags(self):
        options = _option_strings(
            _subparser(sau_cli.build_parser(), "tiktok", "upload-video")
        )
        self.assertIn("--privacy", options)
        self.assertIn("--no-comments", options)
        self.assertIn("--disable-reuse", options)

    def test_privacy_accepts_only_four_choices(self):
        parser = _subparser(sau_cli.build_parser(), "tiktok", "upload-video")
        action = parser._option_string_actions["--privacy"]
        self.assertEqual(
            set(action.choices), {"public", "friends", "followers", "only-me"}
        )

    def test_privacy_rejects_bad_value_before_browser(self):
        playwright = MagicMock()
        session = MagicMock()
        with (
            patch.object(tiktok_command, "async_playwright", playwright),
            patch.object(tiktok_command, "browser_session", session),
        ):
            with tempfile.TemporaryDirectory() as tmp_dir:
                video = Path(tmp_dir) / "demo.mp4"
                video.write_bytes(b"video")
                with redirect_stderr(io.StringIO()) as err:
                    with self.assertRaises(SystemExit) as ctx:
                        sau_cli.main(
                            [
                                "tiktok",
                                "upload-video",
                                "--folder-id",
                                "folder",
                                "--profile-id",
                                "profile",
                                "--file",
                                str(video),
                                "--title",
                                "标题",
                                "--privacy",
                                "everyone",
                            ]
                        )
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("--privacy", err.getvalue())
        playwright.assert_not_called()
        session.assert_not_called()

    def test_disable_reuse_help_names_every_affected_feature(self):
        parser = _subparser(sau_cli.build_parser(), "tiktok", "upload-video")
        help_text = parser._option_string_actions["--disable-reuse"].help or ""
        for feature in ("Duet", "Stitch", "Stickers", "Story"):
            with self.subTest(feature=feature):
                self.assertIn(feature, help_text)


# ---------------------------------------------------------------------------
# CLI -> request -> uploader mapping (strictly tri-state)
# ---------------------------------------------------------------------------


class TiktokOptionsMappingTests(unittest.TestCase):
    def _args(self, **overrides) -> Namespace:
        values = {
            "privacy": None,
            "no_comments": False,
            "disable_reuse": False,
        }
        values.update(overrides)
        return Namespace(**values)

    def test_all_flags_unset_maps_to_none(self):
        self.assertIsNone(tiktok_command._build_publish_options(self._args()))

    def test_public_privacy_maps_to_a_tri_state_option(self):
        options = tiktok_command._build_publish_options(
            self._args(privacy="public")
        )
        self.assertIsNotNone(options)
        self.assertEqual(options.privacy, "public")
        self.assertIsNone(options.allow_comments)
        self.assertIsNone(options.allow_reuse)

    def test_no_comments_maps_to_false(self):
        options = tiktok_command._build_publish_options(
            self._args(no_comments=True)
        )
        self.assertIsNotNone(options)
        self.assertIsNone(options.privacy)
        self.assertIs(options.allow_comments, False)
        self.assertIsNone(options.allow_reuse)

    def test_disable_reuse_is_one_switch_mapped_to_false(self):
        options = tiktok_command._build_publish_options(
            self._args(disable_reuse=True)
        )
        self.assertIsNotNone(options)
        self.assertIsNone(options.privacy)
        self.assertIsNone(options.allow_comments)
        self.assertIs(options.allow_reuse, False)

    def test_combined_flags_keep_every_value(self):
        options = tiktok_command._build_publish_options(
            self._args(
                privacy="only-me", no_comments=True, disable_reuse=True
            )
        )
        self.assertEqual(
            options,
            TiktokPublishOptions(
                privacy="only-me", allow_comments=False, allow_reuse=False
            ),
        )

    def test_request_defaults_to_none_options(self):
        request = tiktok_command.TiktokVideoUploadRequest(
            account_label="profile",
            video_file=Path("/tmp/demo.mp4"),
            title="标题",
            tags=[],
            publish_date=0,
        )
        self.assertIsNone(request.options)

    def test_builder_passes_options_keyword_only(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = Path(tmp_dir) / "demo.mp4"
            video.write_bytes(b"video")
            options = TiktokPublishOptions(privacy="friends")
            request = tiktok_command.TiktokVideoUploadRequest(
                account_label="profile",
                video_file=video,
                title="标题",
                tags=[],
                publish_date=0,
                options=options,
            )
            app = tiktok_command._build_video_uploader(request)

        self.assertIs(app.options, options)


# ---------------------------------------------------------------------------
# In-memory async controls (the production control seam)
# ---------------------------------------------------------------------------


class FakeToggleControl:
    """Checkbox-shaped control: tracks reads, clicks and the current state."""

    def __init__(
        self,
        checked: bool,
        *,
        disabled: bool = False,
        click_toggles: bool = True,
        candidates: tuple[str, ...] = ("fake-toggle",),
    ) -> None:
        self.checked = checked
        self.disabled = disabled
        self.click_toggles = click_toggles
        self.candidates = candidates
        self.checked_reads = 0
        self.disabled_reads = 0
        self.click_calls = 0
        self.text_reads = 0

    async def is_checked(self) -> bool:
        self.checked_reads += 1
        return self.checked

    async def is_disabled(self) -> bool:
        self.disabled_reads += 1
        return self.disabled

    async def click(self) -> None:
        self.click_calls += 1
        if self.click_toggles:
            self.checked = not self.checked

    async def get_attribute(self, name: str) -> str | None:
        if name == "aria-checked":
            return "true" if self.checked else "false"
        return None

    async def read_text(self) -> str:
        self.text_reads += 1
        return "checked" if self.checked else "unchecked"

    async def options(self):
        return []


class FakePrivacyOption:
    def __init__(
        self, label: str, *, disabled: bool = False
    ) -> None:
        self.label = label
        self.disabled = disabled
        self.click_calls = 0
        self.on_click = None

    async def read_text(self) -> str:
        return self.label

    async def is_disabled(self) -> bool:
        return self.disabled

    async def click(self) -> None:
        self.click_calls += 1
        if self.on_click is not None:
            self.on_click(self)

    async def get_attribute(self, name: str) -> str | None:
        return "true" if name == "aria-selected" else None

    async def is_checked(self) -> bool:
        return False


class FakePrivacyControl:
    """Combobox-shaped control with a fixed option list."""

    def __init__(
        self,
        label: str,
        options=(),
        *,
        disabled: bool = False,
        candidates: tuple[str, ...] = ("fake-privacy",),
    ) -> None:
        self.label = label
        self.disabled = disabled
        self.candidates = candidates
        self.open_calls = 0
        self.text_reads = 0
        self.options_reads = 0
        self._options = []
        for item in options:
            option = (
                item
                if isinstance(item, FakePrivacyOption)
                else FakePrivacyOption(item)
            )
            option.on_click = self._select
            self._options.append(option)

    def _select(self, option: FakePrivacyOption) -> None:
        self.label = option.label

    async def read_text(self) -> str:
        self.text_reads += 1
        return self.label

    async def is_disabled(self) -> bool:
        return self.disabled

    async def click(self) -> None:
        self.open_calls += 1

    async def options(self):
        self.options_reads += 1
        return list(self._options)

    async def is_checked(self) -> bool:
        return False

    async def get_attribute(self, name: str) -> str | None:
        return None


class _OptionPage:
    url = "https://www.tiktok.com/tiktokstudio/upload"


def _uploader(options):
    return TiktokVideo(
        "标题", "/tmp/demo.mp4", [], 0, None, options=options
    )


def _controls(*, privacy=None, comments=None, reuse=None):
    return tk_main.TiktokSettingsControls(
        privacy=privacy, comments=comments, reuse=reuse
    )


def _install(video, controls):
    resolver = AsyncMock(return_value=controls)
    video.resolve_option_controls = resolver
    return resolver


class TiktokOptionStepTests(unittest.TestCase):
    def test_no_request_performs_zero_control_interactions(self):
        for options in (None, TiktokPublishOptions()):
            with self.subTest(options=options):
                controls = _controls(
                    privacy=FakePrivacyControl("Everyone", ["Everyone"]),
                    comments=FakeToggleControl(True),
                    reuse=FakeToggleControl(True),
                )
                video = _uploader(options)
                resolver = _install(video, controls)

                asyncio.run(video.apply_options(_OptionPage()))

                resolver.assert_not_awaited()
                self.assertEqual(controls.privacy.text_reads, 0)
                self.assertEqual(controls.privacy.open_calls, 0)
                self.assertEqual(controls.privacy.options_reads, 0)
                self.assertEqual(controls.comments.checked_reads, 0)
                self.assertEqual(controls.comments.click_calls, 0)
                self.assertEqual(controls.reuse.checked_reads, 0)
                self.assertEqual(controls.reuse.click_calls, 0)

    def test_privacy_explicit_set_then_readback(self):
        privacy = FakePrivacyControl(
            "Everyone", ["Everyone", "Friends", "Only you"]
        )
        video = _uploader(TiktokPublishOptions(privacy="friends"))
        _install(video, _controls(privacy=privacy))

        asyncio.run(video.apply_options(_OptionPage()))

        self.assertEqual(privacy.label, "Friends")
        self.assertEqual(privacy.open_calls, 1)
        self.assertEqual(privacy.options_reads, 1)
        self.assertGreaterEqual(privacy.text_reads, 2)
        self.assertEqual(privacy._options[1].click_calls, 1)

    def test_privacy_current_normalized_match_skips_click(self):
        privacy = FakePrivacyControl(
            "Public", ["Everyone", "Friends", "Only you"]
        )
        video = _uploader(TiktokPublishOptions(privacy="public"))
        _install(video, _controls(privacy=privacy))

        asyncio.run(video.apply_options(_OptionPage()))

        self.assertEqual(privacy.open_calls, 0)
        self.assertEqual(privacy.options_reads, 0)

    def test_privacy_label_normalization_all_variants(self):
        cases = {
            "Everyone": "public",
            "Public": "public",
            "  EVERYONE  ": "public",
            "Friends": "friends",
            "Friends\nFollowers you follow back": "friends",
            "Followers": "followers",
            "Only you": "only-me",
            "Private": "only-me",
            "Only you\nSome hint": "only-me",
        }
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(
                    tk_main.normalize_privacy_label(label), expected
                )
        self.assertIsNone(tk_main.normalize_privacy_label("nonsense"))

    def test_privacy_disabled_but_already_satisfied_succeeds(self):
        privacy = FakePrivacyControl(
            "Only you", ["Everyone", "Friends", "Only you"], disabled=True
        )
        video = _uploader(TiktokPublishOptions(privacy="only-me"))
        _install(video, _controls(privacy=privacy))

        asyncio.run(video.apply_options(_OptionPage()))

        self.assertEqual(privacy.open_calls, 0)
        self.assertEqual(privacy.options_reads, 0)

    def test_privacy_requested_level_not_rendered_fails_strictly(self):
        privacy = FakePrivacyControl(
            "Everyone", ["Everyone", "Friends", "Only you"]
        )
        video = _uploader(TiktokPublishOptions(privacy="followers"))
        _install(video, _controls(privacy=privacy))

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(video.apply_options(_OptionPage()))

        message = str(ctx.exception)
        self.assertIn("privacy", message)
        self.assertIn("followers", message)
        self.assertIn("Everyone", message)
        self.assertIn(_OptionPage.url, message)
        self.assertEqual(privacy._options[0].click_calls, 0)
        self.assertEqual(privacy._options[1].click_calls, 0)
        self.assertEqual(privacy._options[2].click_calls, 0)

    def test_privacy_disabled_option_fails(self):
        privacy = FakePrivacyControl(
            "Everyone",
            [
                FakePrivacyOption("Everyone"),
                FakePrivacyOption("Friends"),
                FakePrivacyOption("Only you", disabled=True),
            ],
        )
        video = _uploader(TiktokPublishOptions(privacy="only-me"))
        _install(video, _controls(privacy=privacy))

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(video.apply_options(_OptionPage()))

        message = str(ctx.exception)
        self.assertIn("privacy", message)
        self.assertIn("only-me", message)
        self.assertIn("Only you", message)

    def test_toggle_explicit_set_then_readback(self):
        comments = FakeToggleControl(False)
        video = _uploader(TiktokPublishOptions(allow_comments=True))
        _install(video, _controls(comments=comments))

        asyncio.run(video.apply_options(_OptionPage()))

        self.assertTrue(comments.checked)
        self.assertEqual(comments.click_calls, 1)
        self.assertGreaterEqual(comments.checked_reads, 2)

    def test_toggle_mismatch_fails_with_name_requested_actual(self):
        comments = FakeToggleControl(False, click_toggles=False)
        video = _uploader(TiktokPublishOptions(allow_comments=True))
        _install(video, _controls(comments=comments))

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(video.apply_options(_OptionPage()))

        message = str(ctx.exception)
        self.assertIn("allow_comments", message)
        self.assertIn("True", message)
        self.assertIn("False", message)
        self.assertIn(_OptionPage.url, message)
        self.assertEqual(comments.click_calls, 1)

    def test_toggle_disabled_but_already_satisfied_succeeds(self):
        comments = FakeToggleControl(True, disabled=True)
        video = _uploader(TiktokPublishOptions(allow_comments=True))
        _install(video, _controls(comments=comments))

        asyncio.run(video.apply_options(_OptionPage()))

        self.assertTrue(comments.checked)
        self.assertEqual(comments.click_calls, 0)

    def test_toggle_disabled_and_not_satisfied_fails_without_click(self):
        comments = FakeToggleControl(False, disabled=True)
        video = _uploader(TiktokPublishOptions(allow_comments=True))
        _install(video, _controls(comments=comments))

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(video.apply_options(_OptionPage()))

        self.assertIn("allow_comments", str(ctx.exception))
        self.assertEqual(comments.click_calls, 0)

    def test_disable_reuse_touches_only_the_single_reuse_switch(self):
        comments = FakeToggleControl(True)
        reuse = FakeToggleControl(True)
        video = _uploader(TiktokPublishOptions(allow_reuse=False))
        _install(video, _controls(comments=comments, reuse=reuse))

        asyncio.run(video.apply_options(_OptionPage()))

        self.assertFalse(reuse.checked)
        self.assertEqual(reuse.click_calls, 1)
        self.assertEqual(comments.checked_reads, 0)
        self.assertEqual(comments.click_calls, 0)

    def test_apply_options_runs_privacy_before_toggles(self):
        order: list[str] = []

        class RecordingPrivacy(FakePrivacyControl):
            async def click(self) -> None:
                order.append("privacy")
                await super().click()

        class RecordingToggle(FakeToggleControl):
            async def click(self) -> None:
                order.append("comments")
                await super().click()

        privacy = RecordingPrivacy(
            "Everyone", ["Everyone", "Friends", "Only you"]
        )
        comments = RecordingToggle(True)
        video = _uploader(
            TiktokPublishOptions(privacy="friends", allow_comments=False)
        )
        _install(video, _controls(privacy=privacy, comments=comments))

        asyncio.run(video.apply_options(_OptionPage()))

        self.assertEqual(order, ["privacy", "comments"])


class _AsyncCM:
    def __init__(self, value=None) -> None:
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False


class TiktokOptionFlowTests(unittest.TestCase):
    def _install_hooks(self, video, order, *, read_result="123"):
        def hook(name):
            async def record(*args, **kwargs):
                order.append(name)
                return read_result if name == "read_result" else None

            return record

        for name in (
            "open_upload_page",
            "attach_media",
            "fill_metadata",
            "wait_media_ready",
            "apply_cover",
            "apply_schedule",
            "click_publish",
            "read_result",
        ):
            setattr(video, name, hook(name))

        real_apply_options = video.apply_options

        async def record_apply_options(page):
            order.append("apply_options")
            await real_apply_options(page)

        video.apply_options = record_apply_options

    def test_options_run_before_publish(self):
        order: list[str] = []
        privacy = FakePrivacyControl(
            "Everyone", ["Everyone", "Friends", "Only you"]
        )
        video = _uploader(TiktokPublishOptions(privacy="friends"))
        self._install_hooks(video, order)
        resolver = _install(video, _controls(privacy=privacy))

        asyncio.run(
            video._upload_on_page(_OptionPage(), multilogin=False, deadline=None)
        )

        resolver.assert_awaited_once()
        self.assertLess(
            order.index("apply_options"), order.index("click_publish")
        )
        self.assertEqual(privacy.label, "Friends")

    def test_legacy_upload_video_without_flags_makes_no_option_calls(self):
        order: list[str] = []
        video = _uploader(None)
        self._install_hooks(video, order)
        resolver = AsyncMock()
        video.resolve_option_controls = resolver

        asyncio.run(
            video._upload_on_page(_OptionPage(), multilogin=False, deadline=None)
        )

        resolver.assert_not_awaited()
        self.assertLess(
            order.index("apply_options"), order.index("click_publish")
        )
        self.assertEqual(
            order,
            [
                "open_upload_page",
                "attach_media",
                "fill_metadata",
                "wait_media_ready",
                "apply_options",
                "apply_cover",
                "apply_schedule",
                "click_publish",
                "read_result",
            ],
        )


class TiktokOptionCliFlowTests(unittest.TestCase):
    def _run_upload(self, extra_args):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video = Path(tmp_dir) / "demo.mp4"
            video.write_bytes(b"video")
            session_cm = _AsyncCM(Namespace(context=object()))
            factory = MagicMock(return_value=session_cm)
            app = MagicMock()
            app.upload = AsyncMock()
            builder = MagicMock(return_value=app)

            with (
                patch.object(
                    tiktok_command, "async_playwright", lambda: _AsyncCM(object())
                ),
                patch.object(tiktok_command, "browser_session", new=factory),
                patch.object(
                    tiktok_command,
                    "is_logged_in",
                    new=AsyncMock(return_value=True),
                ),
                patch.object(
                    tiktok_command, "_build_video_uploader", new=builder
                ),
            ):
                code, out, err = _run(
                    [
                        "tiktok",
                        "upload-video",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--file",
                        str(video),
                        "--title",
                        "标题",
                        *extra_args,
                    ]
                )
        return code, out, err, builder

    def test_cli_without_flags_keeps_options_none(self):
        code, out, _, builder = self._run_upload([])
        self.assertEqual(code, 0)
        self.assertIn("TikTok video upload submitted", out)
        request = builder.call_args.args[0]
        self.assertIsNone(request.options)

    def test_cli_flags_reach_the_request_tri_state(self):
        code, _, _, builder = self._run_upload(
            ["--privacy", "followers", "--no-comments", "--disable-reuse"]
        )
        self.assertEqual(code, 0)
        request = builder.call_args.args[0]
        self.assertEqual(
            request.options,
            TiktokPublishOptions(
                privacy="followers",
                allow_comments=False,
                allow_reuse=False,
            ),
        )


if __name__ == "__main__":
    unittest.main()