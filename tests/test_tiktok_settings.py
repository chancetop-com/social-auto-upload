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


class PrivacyOptionLocatorTests(unittest.TestCase):
    def test_options_are_matched_by_role_not_li_tag(self):
        class _Options:
            async def count(self):
                return 3

            def nth(self, index):
                return object()

        class _Scope:
            def __init__(self):
                self.selector = None

            def locator(self, selector):
                self.selector = selector
                return _Options()

        scope = _Scope()
        control = tk_main._LocatorPrivacyControl(object(), scope)

        options = asyncio.run(control.options())

        self.assertEqual(scope.selector, '[role="option"]')
        self.assertEqual(len(options), 3)

    def test_options_fall_back_to_the_page_scope_for_portals(self):
        class _Options:
            def __init__(self, count):
                self._count = count

            async def count(self):
                return self._count

            def nth(self, index):
                return object()

        class _Scope:
            def __init__(self, count):
                self.count = count
                self.selector = None

            def locator(self, selector):
                self.selector = selector
                return _Options(self.count)

        container = _Scope(0)
        page = _Scope(3)
        control = tk_main._LocatorPrivacyControl(
            object(), container, fallback_scope=page
        )

        options = asyncio.run(control.options())

        self.assertEqual(container.selector, '[role="option"]')
        self.assertEqual(page.selector, '[role="option"]')
        self.assertEqual(len(options), 3)


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

    def test_upload_video_registers_aigc_and_brand_flags(self):
        options = _option_strings(
            _subparser(sau_cli.build_parser(), "tiktok", "upload-video")
        )
        for flag in (
            "--aigc",
            "--no-aigc",
            "--your-brand",
            "--branded-content",
        ):
            with self.subTest(flag=flag):
                self.assertIn(flag, options)

    def test_aigc_flags_are_mutually_exclusive(self):
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
                            "--aigc",
                            "--no-aigc",
                        ]
                    )
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("not allowed with", err.getvalue())

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
            "aigc": None,
            "your_brand": None,
            "branded_content": None,
        }
        values.update(overrides)
        return Namespace(**values)

    def test_all_flags_unset_maps_to_none(self):
        self.assertIsNone(tiktok_command._build_publish_options(self._args()))

    def test_aigc_true_and_false_stay_tri_state(self):
        enabled = tiktok_command._build_publish_options(self._args(aigc=True))
        disabled = tiktok_command._build_publish_options(
            self._args(aigc=False)
        )
        self.assertIsNotNone(enabled)
        self.assertIs(enabled.aigc, True)
        self.assertIsNotNone(disabled)
        self.assertIs(disabled.aigc, False)

    def test_brand_flags_default_to_none_and_preserve_true(self):
        absent = tiktok_command._build_publish_options(self._args())
        self.assertIsNone(absent)

        your_brand = tiktok_command._build_publish_options(
            self._args(your_brand=True)
        )
        self.assertIsNotNone(your_brand)
        self.assertIs(your_brand.your_brand, True)
        self.assertIsNone(your_brand.branded_content)

        branded = tiktok_command._build_publish_options(
            self._args(branded_content=True)
        )
        self.assertIsNotNone(branded)
        self.assertIsNone(branded.your_brand)
        self.assertIs(branded.branded_content, True)

    def test_absent_brand_flags_are_not_coerced_to_false(self):
        options = tiktok_command._build_publish_options(
            self._args(privacy="public")
        )
        self.assertIsNotNone(options)
        self.assertIsNone(options.your_brand)
        self.assertIsNone(options.branded_content)
        self.assertIsNone(options.aigc)

    def test_all_six_fields_can_be_combined(self):
        options = tiktok_command._build_publish_options(
            self._args(
                privacy="public",
                no_comments=True,
                disable_reuse=True,
                aigc=True,
                your_brand=True,
                branded_content=True,
            )
        )
        self.assertEqual(
            options,
            TiktokPublishOptions(
                privacy="public",
                allow_comments=False,
                allow_reuse=False,
                aigc=True,
                your_brand=True,
                branded_content=True,
            ),
        )

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
# Local pre-browser validation
# ---------------------------------------------------------------------------


class TiktokBrandedContentValidationTests(unittest.TestCase):
    def test_branded_content_with_only_me_exits_2_without_browser(self):
        playwright = MagicMock()
        session = MagicMock()
        with (
            patch.object(tiktok_command, "async_playwright", playwright),
            patch.object(tiktok_command, "browser_session", session),
        ):
            with tempfile.TemporaryDirectory() as tmp_dir:
                video = Path(tmp_dir) / "demo.mp4"
                video.write_bytes(b"video")
                code, _, err = _run(
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
                        "--branded-content",
                        "--privacy",
                        "only-me",
                    ]
                )
        self.assertEqual(code, 2)
        self.assertIn("branded-content", err)
        playwright.assert_not_called()
        session.assert_not_called()


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

    async def wait_for_timeout(self, ms) -> None:
        return None


class FakeDialogButton:
    """Minimal locator for the AIGC ``Turn on`` button."""

    def __init__(self, on_click=None) -> None:
        self._count = 1
        self.click_calls = 0
        self._on_click = on_click

    @property
    def first(self):
        return self

    async def count(self) -> int:
        return self._count

    async def click(self) -> None:
        self.click_calls += 1
        self._count = 0
        if self._on_click is not None:
            self._on_click()

    async def wait_for(self, **kwargs) -> None:
        return None


class _MissingLocator:
    def __init__(self) -> None:
        self.first = self

    async def count(self) -> int:
        return 0

    async def click(self) -> None:
        raise AssertionError("missing locator must never be clicked")

    async def wait_for(self, **kwargs) -> None:
        return None


class _ExplodingDialogButton(FakeDialogButton):
    async def click(self) -> None:
        self.click_calls += 1
        raise RuntimeError("dialog click exploded")


class _FailingReadControl(FakeToggleControl):
    """A control whose state read raises a raw Playwright-like error."""

    def __init__(self) -> None:
        super().__init__(False)
        self.candidates = ("fake-failing-control",)

    async def is_checked(self) -> bool:
        raise RuntimeError("locator detached while reading the state")

    async def get_attribute(self, name: str) -> str | None:
        return None


class _CheckboxQuery:
    def __init__(self, checked: bool) -> None:
        self.checked = checked
        self.first = self

    async def count(self) -> int:
        return 1

    async def is_checked(self) -> bool:
        return self.checked


class _LabelTextLocator:
    """Text/label node: ``is_checked`` fails, nested checkbox carries state."""

    def __init__(self, nested=None, *, aria=None) -> None:
        self._nested = nested
        self._aria = aria

    async def is_checked(self) -> bool:
        raise RuntimeError("not a checkbox")

    def locator(self, _selector: str):
        return self._nested if self._nested is not None else _MissingLocator()

    async def get_attribute(self, name: str) -> str | None:
        if name == "aria-checked":
            return self._aria
        return None

    async def click(self, **kwargs) -> None:
        return None


class _AigcDialogScope:
    def __init__(self, button: FakeDialogButton) -> None:
        self.button = button

    def get_by_role(self, role, name=None):
        if role == "button" and (
            name == "Turn on"
            or (
                hasattr(name, "fullmatch")
                and name.fullmatch("Turn on")
            )
        ):
            return self.button
        return _MissingLocator()


class FakeAigcPage:
    """Top-level page that renders the first-run ``Labeling ...`` dialog."""

    url = _OptionPage.url

    def __init__(self, button: FakeDialogButton) -> None:
        self._button = button

    def get_by_role(self, role, name=None):
        return _MissingLocator()

    def locator(self, selector):
        if selector == '[role="dialog"]':
            return _AigcDialogScope(self._button)
        return _MissingLocator()

    async def wait_for_timeout(self, ms) -> None:
        return None


def _uploader(options):
    return TiktokVideo(
        "标题", "/tmp/demo.mp4", [], 0, None, options=options
    )


def _controls(
    *,
    privacy=None,
    comments=None,
    reuse=None,
    aigc=None,
    brand_switch=None,
    your_brand=None,
    branded_content=None,
):
    return tk_main.TiktokSettingsControls(
        privacy=privacy,
        comments=comments,
        reuse=reuse,
        aigc=aigc,
        brand_switch=brand_switch,
        your_brand=your_brand,
        branded_content=branded_content,
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
                    aigc=FakeToggleControl(False),
                    brand_switch=FakeToggleControl(False),
                    your_brand=FakeToggleControl(False),
                    branded_content=FakeToggleControl(False),
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
                self.assertEqual(controls.aigc.checked_reads, 0)
                self.assertEqual(controls.aigc.click_calls, 0)
                self.assertEqual(controls.brand_switch.checked_reads, 0)
                self.assertEqual(controls.brand_switch.click_calls, 0)
                self.assertEqual(controls.your_brand.checked_reads, 0)
                self.assertEqual(controls.your_brand.click_calls, 0)
                self.assertEqual(controls.branded_content.checked_reads, 0)
                self.assertEqual(controls.branded_content.click_calls, 0)

    def test_apply_options_expands_advanced_settings_first(self):
        video = _uploader(TiktokPublishOptions(privacy="only-me"))
        privacy = FakePrivacyControl(
            "Followers", ["Followers", "Friends", "Only you"]
        )
        _install(video, _controls(privacy=privacy))
        video._expand_advanced_settings = AsyncMock()

        asyncio.run(video.apply_options(_OptionPage()))

        video._expand_advanced_settings.assert_awaited_once()

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

    def test_missing_reuse_control_with_disable_reuse_fails(self):
        video = _uploader(TiktokPublishOptions(allow_reuse=False))
        _install(video, _controls())

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(video.apply_options(_OptionPage()))

        self.assertIn("allow_reuse", str(ctx.exception))
        self.assertIn("control-not-found", str(ctx.exception))

    def test_resolve_fails_when_reuse_control_is_missing(self):
        video = _uploader(TiktokPublishOptions(allow_reuse=False))
        video._resolve_single_control = AsyncMock(return_value=None)
        video._expand_advanced_settings = AsyncMock()

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(video.resolve_option_controls(_OptionPage()))

        self.assertIn("option=reuse", str(ctx.exception))
        self.assertIn("control-not-found", str(ctx.exception))

    def test_reuse_candidates_include_current_studio_label(self):
        video = _uploader(TiktokPublishOptions(allow_reuse=False))
        video.locator_base = MagicMock()
        labels = [
            label
            for label, _ in video._option_candidate_factories("reuse")
        ]
        self.assertTrue(
            any("Reuse of content" in label for label in labels), labels
        )

    def test_brand_candidates_use_semantic_rows_not_scoped_container(self):
        video = _uploader(TiktokPublishOptions(your_brand=True))
        video.locator_base = MagicMock()

        labels = [
            label
            for label, _ in video._option_candidate_factories("your_brand")
        ]

        self.assertEqual(len(labels), 2, labels)
        self.assertIn("title-line", labels[0])
        self.assertIn("preceding label", labels[1])
        self.assertTrue(
            all("disclose" not in label for label in labels), labels
        )

    def test_confirmation_names_prefer_schedule_for_scheduled_posts(self):
        from datetime import datetime

        immediate = tk_main._confirmation_names(0)
        scheduled = tk_main._confirmation_names(
            datetime(2026, 11, 6, 17, 35)
        )

        self.assertEqual(immediate, ("Post now",))
        self.assertEqual(scheduled, ("Schedule", "Post now"))

    def test_scheduled_verification_accepts_row_without_timezone_text(self):
        from datetime import datetime

        class _Page:
            url = "https://www.tiktok.com/tiktokstudio/content"

            def locator(self, selector):
                self.selector = selector
                return self

            async def inner_text(self):
                return (
                    "Posts (Created on) | TB19 scheduled row | "
                    "Nov 6, 5:35 PM | Everyone"
                )

            async def wait_for_timeout(self, _ms):
                return None

        video = TiktokVideo(
            "TB19 scheduled row",
            "/tmp/demo.mp4",
            [],
            datetime(2026, 11, 6, 17, 35),
            None,
        )

        asyncio.run(video._verify_scheduled_post(_Page()))

    def test_scheduled_verification_rejects_missing_row(self):
        from datetime import datetime

        class _Page:
            def __init__(self, body):
                self.body = body
                self.url = "https://www.tiktok.com/tiktokstudio/content"

            def locator(self, _selector):
                return self

            async def inner_text(self):
                return self.body

            async def wait_for_timeout(self, _ms):
                return None

        video = TiktokVideo(
            "TB19 scheduled row",
            "/tmp/demo.mp4",
            [],
            datetime(2026, 11, 6, 17, 35),
            None,
        )

        with self.subTest("row absent"):
            with patch.object(
                tk_main, "TIKTOK_RESULT_READ_TIMEOUT_MS", 1
            ):
                with self.assertRaises(
                    tk_main.PublishResultUnknownError
                ):
                    asyncio.run(
                        video._verify_scheduled_post(
                            _Page("Posts (Created on) | something else")
                        )
                    )

    def test_scheduled_verification_rejects_tags_only(self):
        from datetime import datetime

        class _Page:
            url = "https://www.tiktok.com/tiktokstudio/content"

            def locator(self, _selector):
                return self

            async def inner_text(self):
                return "old scheduled clip | #fyp | Everyone"

            async def wait_for_timeout(self, _ms):
                return None

        video = TiktokVideo(
            "",
            "/tmp/demo.mp4",
            ["fyp"],
            datetime(2026, 11, 6, 17, 35),
            None,
        )

        with self.assertRaises(tk_main.PublishResultUnknownError):
            asyncio.run(video._verify_scheduled_post(_Page()))

    def test_scheduled_row_check_tolerates_truncated_and_wrapped_copy(self):
        body = (
            "TB19 scheduled row that is very long and gets tr… | Everyone"
        )

        self.assertEqual(
            tk_main._find_scheduled_row_marker(
                body,
                ("TB19 scheduled row that is very long",),
            ),
            "TB19 scheduled row that is very long",
        )
        self.assertEqual(
            tk_main._find_scheduled_row_marker(
                "TB19 scheduled\nrow line two | Everyone",
                ("TB19 scheduled",),
            ),
            "TB19 scheduled",
        )
        self.assertIsNone(
            tk_main._find_scheduled_row_marker(
                "something else | Everyone",
                ("TB19 scheduled",),
            )
        )

    def test_label_control_uses_first_visible_duplicate(self):
        class _Node:
            def __init__(self, visible, checked):
                self.visible = visible
                self.checked = checked
                self.click_calls = 0

            async def is_checked(self):
                return self.checked

            async def is_visible(self):
                return self.visible

            async def is_disabled(self):
                return False

            async def get_attribute(self, _name):
                return None

            def locator(self, _selector):
                return _MissingLocator()

            async def click(self, **_kwargs):
                self.click_calls += 1

        hidden = _Node(False, False)
        visible = _Node(True, True)

        class _Multi:
            def __init__(self):
                self.nodes = [hidden, visible]

            async def count(self):
                return len(self.nodes)

            def nth(self, index):
                return self.nodes[index]

            @property
            def first(self):
                return hidden

        control = tk_main._LocatorControl(_Multi())

        self.assertTrue(asyncio.run(control.is_checked()))
        asyncio.run(control.click())
        self.assertEqual(visible.click_calls, 1)
        self.assertEqual(hidden.click_calls, 0)

    def test_find_candidate_skips_hidden_first_match(self):
        class _Node:
            def __init__(self, visible):
                self.visible = visible

            async def is_visible(self):
                return self.visible

        class _Locator:
            def __init__(self):
                self.nodes = [_Node(False), _Node(True)]

            async def count(self):
                return len(self.nodes)

            def nth(self, index):
                return self.nodes[index]

            @property
            def first(self):
                return self.nodes[0]

        found = asyncio.run(
            tk_main._find_candidate(
                object(), (("x", lambda _scope: _Locator()),), visible=True
            )
        )

        self.assertIsNotNone(found)
        self.assertTrue(found[0].visible)

    def test_result_link_prefers_title_over_shared_hashtag(self):
        class _Link:
            def __init__(self, href, text):
                self.href = href
                self.text = text

            async def get_attribute(self, name):
                return self.href if name == "href" else None

            async def inner_text(self):
                return self.text

        class _Links:
            def __init__(self, links):
                self.links = links

            async def count(self):
                return len(self.links)

            def nth(self, index):
                return self.links[index]

        class _Page:
            url = "https://www.tiktok.com/tiktokstudio/content"

            def locator(self, _selector):
                return _Links(
                    [
                        _Link("/video/111", "#fyp"),
                        _Link("/video/222", "TB19 title here"),
                    ]
                )

            async def wait_for_timeout(self, _ms):
                return None

        video = TiktokVideo(
            "TB19 title here", "/tmp/demo.mp4", ["fyp"], 0, None
        )
        href = asyncio.run(
            video._find_result_link(
                _Page(), ('a[href*="/video/"]',), timeout_ms=1
            )
        )

        self.assertEqual(href, "/video/222")

    def test_scheduled_verification_fails_closed_without_text(self):
        from datetime import datetime

        class _Page:
            url = "https://www.tiktok.com/tiktokstudio/content"

            def locator(self, _selector):
                return self

            async def inner_text(self):
                return ""

            async def wait_for_timeout(self, _ms):
                return None

        video = TiktokVideo(
            "",
            "/tmp/demo.mp4",
            [],
            datetime(2026, 11, 6, 17, 35),
            None,
        )

        with self.assertRaises(tk_main.PublishResultUnknownError):
            asyncio.run(video._verify_scheduled_post(_Page()))

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


class TiktokAigcOptionTests(unittest.TestCase):
    def test_aigc_on_clicks_switch_confirms_turn_on_and_reads_back(self):
        aigc = FakeToggleControl(False)

        def turn_on():
            aigc.checked = True

        button = FakeDialogButton(turn_on)
        video = _uploader(TiktokPublishOptions(aigc=True))
        _install(video, _controls(aigc=aigc))

        asyncio.run(video.apply_options(FakeAigcPage(button)))

        self.assertTrue(aigc.checked)
        self.assertEqual(aigc.click_calls, 1)
        self.assertEqual(button.click_calls, 1)

    def test_aigc_on_without_dialog_still_reads_back(self):
        aigc = FakeToggleControl(False)
        video = _uploader(TiktokPublishOptions(aigc=True))
        _install(video, _controls(aigc=aigc))

        asyncio.run(video.apply_options(_OptionPage()))

        self.assertTrue(aigc.checked)
        self.assertEqual(aigc.click_calls, 1)

    def test_aigc_off_clicks_switch_without_dialog(self):
        aigc = FakeToggleControl(True)
        button = FakeDialogButton()
        video = _uploader(TiktokPublishOptions(aigc=False))
        _install(video, _controls(aigc=aigc))

        asyncio.run(video.apply_options(FakeAigcPage(button)))

        self.assertFalse(aigc.checked)
        self.assertEqual(aigc.click_calls, 1)
        self.assertEqual(button.click_calls, 0)

    def test_aigc_missing_control_fails_strictly(self):
        video = _uploader(TiktokPublishOptions(aigc=True))
        _install(video, _controls(aigc=None))

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(video.apply_options(_OptionPage()))

        message = str(ctx.exception)
        self.assertIn("aigc", message)
        self.assertIn("True", message)
        self.assertIn("control-not-found", message)
        self.assertIn(_OptionPage.url, message)

    def test_aigc_already_satisfied_but_disabled_succeeds(self):
        aigc = FakeToggleControl(True, disabled=True)
        video = _uploader(TiktokPublishOptions(aigc=True))
        _install(video, _controls(aigc=aigc))

        asyncio.run(video.apply_options(_OptionPage()))

        self.assertTrue(aigc.checked)
        self.assertEqual(aigc.click_calls, 0)

    def test_aigc_disabled_and_not_satisfied_fails_without_click(self):
        aigc = FakeToggleControl(False, disabled=True)
        video = _uploader(TiktokPublishOptions(aigc=True))
        _install(video, _controls(aigc=aigc))

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(video.apply_options(_OptionPage()))

        self.assertIn("aigc", str(ctx.exception))
        self.assertIn("disabled", str(ctx.exception))
        self.assertEqual(aigc.click_calls, 0)

    def test_aigc_mismatch_names_option_requested_and_actual(self):
        aigc = FakeToggleControl(False, click_toggles=False)
        video = _uploader(TiktokPublishOptions(aigc=True))
        _install(video, _controls(aigc=aigc))

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(video.apply_options(_OptionPage()))

        message = str(ctx.exception)
        self.assertIn("aigc", message)
        self.assertIn("True", message)
        self.assertIn("False", message)
        self.assertIn(_OptionPage.url, message)
        self.assertEqual(aigc.click_calls, 1)

    def test_aigc_dialog_failure_is_not_swallowed(self):
        aigc = FakeToggleControl(False)
        button = _ExplodingDialogButton()
        video = _uploader(TiktokPublishOptions(aigc=True))
        _install(video, _controls(aigc=aigc))

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(video.apply_options(FakeAigcPage(button)))

        message = str(ctx.exception)
        self.assertIn("option=aigc", message)
        self.assertIn("turn-on-dialog", message)
        self.assertIn("dialog click exploded", message)
        self.assertIn("Turn on", message)
        self.assertEqual(button.click_calls, 1)

    def test_brand_checkboxes_are_resolved_after_master_switch(self):
        master = FakeToggleControl(False)
        your_brand = FakeToggleControl(False)
        branded = FakeToggleControl(True)
        video = _uploader(TiktokPublishOptions(your_brand=True))
        _install(video, _controls(brand_switch=master))

        async def resolver(name):
            return {
                "your_brand": your_brand,
                "branded_content": branded,
            }[name]

        video._resolve_single_control = AsyncMock(side_effect=resolver)

        asyncio.run(video.apply_options(_OptionPage()))

        self.assertTrue(master.checked)
        self.assertTrue(your_brand.checked)
        self.assertFalse(branded.checked)
        self.assertEqual(
            [call.args[0] for call in video._resolve_single_control.await_args_list],
            ["your_brand", "branded_content"],
        )

    def test_toggle_read_error_is_wrapped_with_option_context(self):
        comments = _FailingReadControl()
        video = _uploader(TiktokPublishOptions(allow_comments=True))
        _install(video, _controls(comments=comments))

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(video.apply_options(_OptionPage()))

        message = str(ctx.exception)
        self.assertIn("option=allow_comments", message)
        self.assertIn("stage=read", message)
        self.assertIn("read-error", message)
        self.assertIn("locator detached", message)
        self.assertIn("fake-failing-control", message)

    def test_switch_read_error_is_wrapped_with_option_context(self):
        master = _FailingReadControl()
        your_brand = FakeToggleControl(False)
        branded = FakeToggleControl(False)
        video = _uploader(TiktokPublishOptions(your_brand=True))
        _install(
            video,
            _controls(
                brand_switch=master,
                your_brand=your_brand,
                branded_content=branded,
            ),
        )

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(video.apply_options(_OptionPage()))

        message = str(ctx.exception)
        self.assertIn("option=brand_switch", message)
        self.assertIn("stage=read", message)
        self.assertIn("read-error", message)
        self.assertIn("locator detached", message)

    def test_label_control_does_not_treat_disabled_false_class_as_disabled(self):
        class _Locator:
            async def is_disabled(self):
                return False

            async def get_attribute(self, name):
                if name == "class":
                    return (
                        "Checkbox__root Checkbox__root--labelPlacement-end "
                        "Checkbox__root--disabled-false"
                    )
                return "false"

            def locator(self, selector):
                raise AssertionError("no nested checkbox")

        control = tk_main._LocatorControl(_Locator())

        self.assertFalse(asyncio.run(control.is_disabled()))

    def test_privacy_control_does_not_treat_disabled_false_class_as_disabled(self):
        class _Trigger:
            async def is_disabled(self):
                return False

            async def get_attribute(self, name):
                if name == "class":
                    return "TUXSelect TUXSelect--disabled-false"
                return None

        control = tk_main._LocatorPrivacyControl(_Trigger(), None)

        self.assertFalse(asyncio.run(control.is_disabled()))

    def test_privacy_control_detects_disabled_true_class(self):
        class _Trigger:
            async def is_disabled(self):
                return False

            async def get_attribute(self, name):
                if name == "class":
                    return "TUXSelect TUXSelect--disabled-true"
                return None

        control = tk_main._LocatorPrivacyControl(_Trigger(), None)

        self.assertTrue(asyncio.run(control.is_disabled()))

    def test_privacy_label_normalizes_only_me_alias(self):
        self.assertEqual(
            tk_main.normalize_privacy_label("Only me"), "only-me"
        )

    def test_label_control_reads_nested_checkbox_state(self):
        control = tk_main._LocatorControl(
            _LabelTextLocator(_CheckboxQuery(True))
        )

        self.assertTrue(asyncio.run(control.is_checked()))

    def test_label_control_reports_a_read_failure_with_context(self):
        control = tk_main._LocatorControl(_LabelTextLocator())

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(
                tk_main._set_toggle_option(
                    control,
                    True,
                    option="your_brand",
                    url=_OptionPage.url,
                )
            )

        message = str(ctx.exception)
        self.assertIn("option=your_brand", message)
        self.assertIn("stage=read", message)
        self.assertIn("read-error", message)
        self.assertIn("not a checkbox", message)


class TiktokBrandDisclosureTests(unittest.TestCase):
    def test_your_brand_opens_master_and_sets_both_checkboxes(self):
        master = FakeToggleControl(False)
        your_brand = FakeToggleControl(False)
        branded = FakeToggleControl(True)
        video = _uploader(TiktokPublishOptions(your_brand=True))
        _install(
            video,
            _controls(
                brand_switch=master,
                your_brand=your_brand,
                branded_content=branded,
            ),
        )

        asyncio.run(video.apply_options(_OptionPage()))

        self.assertTrue(master.checked)
        self.assertEqual(master.click_calls, 1)
        self.assertTrue(your_brand.checked)
        self.assertEqual(your_brand.click_calls, 1)
        self.assertFalse(branded.checked)
        self.assertEqual(branded.click_calls, 1)

    def test_branded_content_opens_master_and_unchecks_the_other_box(self):
        master = FakeToggleControl(False)
        your_brand = FakeToggleControl(True)
        branded = FakeToggleControl(False)
        video = _uploader(TiktokPublishOptions(branded_content=True))
        _install(
            video,
            _controls(
                brand_switch=master,
                your_brand=your_brand,
                branded_content=branded,
            ),
        )

        asyncio.run(video.apply_options(_OptionPage()))

        self.assertTrue(master.checked)
        self.assertEqual(master.click_calls, 1)
        self.assertFalse(your_brand.checked)
        self.assertEqual(your_brand.click_calls, 1)
        self.assertTrue(branded.checked)
        self.assertEqual(branded.click_calls, 1)

    def test_both_brand_flags_can_be_true(self):
        master = FakeToggleControl(True)
        your_brand = FakeToggleControl(False)
        branded = FakeToggleControl(False)
        video = _uploader(
            TiktokPublishOptions(your_brand=True, branded_content=True)
        )
        _install(
            video,
            _controls(
                brand_switch=master,
                your_brand=your_brand,
                branded_content=branded,
            ),
        )

        asyncio.run(video.apply_options(_OptionPage()))

        self.assertTrue(your_brand.checked)
        self.assertTrue(branded.checked)
        self.assertEqual(master.click_calls, 0)

    def test_brand_readback_mismatch_names_option_values_and_url(self):
        master = FakeToggleControl(False)
        your_brand = FakeToggleControl(False)
        branded = FakeToggleControl(False, click_toggles=False)
        video = _uploader(TiktokPublishOptions(branded_content=True))
        _install(
            video,
            _controls(
                brand_switch=master,
                your_brand=your_brand,
                branded_content=branded,
            ),
        )

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(video.apply_options(_OptionPage()))

        message = str(ctx.exception)
        self.assertIn("branded_content", message)
        self.assertIn("True", message)
        self.assertIn("False", message)
        self.assertIn(_OptionPage.url, message)

    def test_brand_missing_control_fails_strictly(self):
        master = FakeToggleControl(False)
        your_brand = FakeToggleControl(False)
        video = _uploader(TiktokPublishOptions(your_brand=True))
        _install(
            video,
            _controls(
                brand_switch=master,
                your_brand=your_brand,
                branded_content=None,
            ),
        )

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(video.apply_options(_OptionPage()))

        message = str(ctx.exception)
        self.assertIn("branded_content", message)
        self.assertIn("control-not-found", message)
        self.assertIn(_OptionPage.url, message)

    def test_master_switch_mismatch_fails(self):
        master = FakeToggleControl(False, click_toggles=False)
        your_brand = FakeToggleControl(False)
        branded = FakeToggleControl(False)
        video = _uploader(TiktokPublishOptions(your_brand=True))
        _install(
            video,
            _controls(
                brand_switch=master,
                your_brand=your_brand,
                branded_content=branded,
            ),
        )

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(video.apply_options(_OptionPage()))

        message = str(ctx.exception)
        self.assertIn("brand_switch", message)
        self.assertIn("True", message)
        self.assertIn("False", message)
        self.assertIn(_OptionPage.url, message)
        self.assertEqual(your_brand.click_calls, 0)
        self.assertEqual(branded.click_calls, 0)

    def test_explicit_false_brand_flags_do_not_touch_brand_controls(self):
        master = FakeToggleControl(False)
        your_brand = FakeToggleControl(False)
        branded = FakeToggleControl(False)
        video = _uploader(
            TiktokPublishOptions(your_brand=False, branded_content=False)
        )
        resolver = _install(
            video,
            _controls(
                brand_switch=master,
                your_brand=your_brand,
                branded_content=branded,
            ),
        )

        asyncio.run(video.apply_options(_OptionPage()))

        resolver.assert_not_awaited()
        self.assertEqual(master.checked_reads, 0)
        self.assertEqual(master.click_calls, 0)
        self.assertEqual(your_brand.checked_reads, 0)
        self.assertEqual(your_brand.click_calls, 0)
        self.assertEqual(branded.checked_reads, 0)
        self.assertEqual(branded.click_calls, 0)


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
            video._upload_on_page(_OptionPage(), multilogin=False, budget=None)
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
            video._upload_on_page(_OptionPage(), multilogin=False, budget=None)
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

    def test_cli_aigc_and_brand_flags_reach_the_request(self):
        code, _, _, builder = self._run_upload(
            ["--aigc", "--your-brand", "--branded-content"]
        )
        self.assertEqual(code, 0)
        request = builder.call_args.args[0]
        self.assertEqual(
            request.options,
            TiktokPublishOptions(
                aigc=True,
                your_brand=True,
                branded_content=True,
            ),
        )

    def test_cli_no_aigc_reaches_the_request_as_false(self):
        code, _, _, builder = self._run_upload(["--no-aigc"])
        self.assertEqual(code, 0)
        request = builder.call_args.args[0]
        self.assertIs(request.options.aigc, False)
        self.assertIsNone(request.options.your_brand)
        self.assertIsNone(request.options.branded_content)


class HashtagEntityTests(unittest.TestCase):
    class _Option:
        def __init__(self, page, text, selected=False):
            self.page = page
            self.text = text
            self.selected = selected

        async def inner_text(self):
            return self.text

        async def get_attribute(self, name):
            if name == "aria-selected" and self.selected:
                return "true"
            return None

        async def click(self, **_kwargs):
            self.page.clicked.append(self.text)
            if self in self.page.options:
                self.page.options.remove(self)

    class _Options:
        def __init__(self, items):
            self.items = items

        async def count(self):
            return len(self.items)

        def nth(self, index):
            return self.items[index]

    class _Keyboard:
        def __init__(self, page):
            self.page = page
            self.events = []

        async def insert_text(self, text):
            self.events.append(("insert_text", text))

        async def press(self, key):
            self.events.append(("press", key))
            if key == "Enter":
                self.page.options.clear()

    class _Page:
        def __init__(self, option_texts):
            self.keyboard = HashtagEntityTests._Keyboard(self)
            self.clicked = []
            self.options = [
                HashtagEntityTests._Option(self, text)
                for text in option_texts
            ]

        def locator(self, selector):
            if selector == '[role="option"]':
                return HashtagEntityTests._Options(self.options)
            return HashtagEntityTests._Options([])

        async def wait_for_timeout(self, _ms):
            return None

    def test_exact_suggestion_is_clicked_and_becomes_entity(self):
        page = self._Page(
            ["#tiktok\n2.0B posts", "#tiktokshop\n175.4M posts"]
        )
        video = _uploader(TiktokPublishOptions())

        self.assertTrue(asyncio.run(video._apply_hashtag(page, "tiktok")))

        self.assertEqual(page.clicked, ["#tiktok\n2.0B posts"])
        self.assertEqual(
            page.keyboard.events[0], ("insert_text", "#tiktok")
        )
        self.assertNotIn(("press", "Space"), page.keyboard.events)
        self.assertNotIn(("press", "Backspace"), page.keyboard.events)

    def test_selected_suggestion_is_accepted_with_enter(self):
        page = self._Page(["#tiktok\n2.0B posts"])
        page.options[0].selected = True
        video = _uploader(TiktokPublishOptions())

        self.assertTrue(asyncio.run(video._apply_hashtag(page, "tiktok")))

        self.assertIn(("press", "Enter"), page.keyboard.events)
        self.assertEqual(page.clicked, [])

    def test_no_exact_suggestion_falls_back_to_plain_text(self):
        page = self._Page(["#tiktokshop\n175.4M posts"])
        video = _uploader(TiktokPublishOptions())

        with patch.object(tk_main, "TIKTOK_HASHTAG_SETTLE_MS", 0):
            self.assertFalse(
                asyncio.run(video._apply_hashtag(page, "tiktok"))
            )

        self.assertEqual(page.clicked, [])
        self.assertEqual(
            [event for event in page.keyboard.events if event[0] == "press"],
            [("press", "Space")],
        )

    def test_no_suggestions_at_all_falls_back_after_timeout(self):
        page = self._Page([])
        video = _uploader(TiktokPublishOptions())

        with patch.object(
            tk_main, "TIKTOK_HASHTAG_SUGGESTION_TIMEOUT_MS", 0
        ):
            self.assertFalse(
                asyncio.run(video._apply_hashtag(page, "tiktok"))
            )

        self.assertEqual(page.clicked, [])
        self.assertIn(("press", "Space"), page.keyboard.events)

    def test_non_hashtag_option_is_ignored(self):
        page = self._Page(["tiktok", "#other"])
        video = _uploader(TiktokPublishOptions())

        with patch.object(tk_main, "TIKTOK_HASHTAG_SETTLE_MS", 0):
            self.assertFalse(
                asyncio.run(video._apply_hashtag(page, "tiktok"))
            )
        self.assertEqual(page.clicked, [])


if __name__ == "__main__":
    unittest.main()