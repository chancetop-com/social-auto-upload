# -*- coding: utf-8 -*-
"""``sau tiktok upload-note`` core photo-post path (ticket 15).

Everything here is offline: in-memory page/session fakes only.  No browser is
launched, no network is touched, and no DOM/CSS behaviour is modelled — the
fakes expose only the handful of Playwright calls the uploader makes.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import inspect
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import sau_cli
from sau_commands import tiktok as tiktok_command
from sau_commands.arguments import existing_file_path
from uploader.tk_uploader import main_chrome as tk_main
from uploader.tk_uploader.main_chrome import (
    TIKTOK_LAUNCH_KWARGS,
    TiktokBaseUploader,
    TiktokNote,
    TiktokPublishOptions,
)
from uploader.tk_uploader.tk_config import (
    TIKTOK_IMAGE_SUFFIXES,
    TIKTOK_MAX_DESCRIPTION_LENGTH,
    TIKTOK_MAX_HASHTAG_COUNT,
    TIKTOK_MAX_IMAGE_BYTES,
    TIKTOK_MAX_IMAGE_COUNT,
    TIKTOK_MAX_TITLE_LENGTH,
    TIKTOK_PHOTO_UPLOAD_URL,
    TIKTOK_UPLOAD_URL,
)

TOKEN = "SENTINEL-MLX-TOKEN-ticket15"
ITEM_ID = "7412345678901234567"


# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------


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


def _action_names(platform: str) -> list[str]:
    platform_parser = _subparser(sau_cli.build_parser(), platform)
    for item in platform_parser._actions:
        if isinstance(item, argparse._SubParsersAction):
            return list(item.choices)
    return []


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


class _AsyncCM:
    def __init__(self, value=None) -> None:
        self.value = value
        self.enter_calls = 0
        self.exit_calls = 0

    async def __aenter__(self):
        self.enter_calls += 1
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        self.exit_calls += 1
        return False


def _fake_session(context):
    session = SimpleNamespace(context=context, mode="multilogin", managed=True)
    session_cm = _AsyncCM(session)
    factory = MagicMock(return_value=session_cm)
    return session, session_cm, factory


# ---------------------------------------------------------------------------
# In-memory studio page fake
# ---------------------------------------------------------------------------


class _Locator:
    """Only the locator surface the uploader actually calls."""

    def __init__(self, page, selector: str, *, count: int = 0) -> None:
        self.page = page
        self.selector = selector
        self._count = count
        self._index = None

    def _spawn(self, *, count=None):
        return _Locator(
            self.page,
            self.selector,
            count=self._count if count is None else count,
        )

    @property
    def first(self):
        return self

    @property
    def last(self):
        return self

    def nth(self, index: int):
        locator = self._spawn()
        locator._index = index
        return locator

    def locator(self, selector: str):
        return self.page.locator(selector)

    async def count(self) -> int:
        self.page.events.append(("probe", self.selector))
        return self._count

    async def click(self, **kwargs) -> None:
        self.page.events.append(("click", self.selector))
        if "button-group" in self.selector:
            self.page.publish_clicked = True

    async def inner_text(self) -> str:
        if 'item_id=' in self.selector:
            return self.page.caption_text or self.page.title_text or ""
        return ""

    async def get_attribute(self, name: str):
        if "text=Post" in self.selector:
            return None if self.page.post_enabled else "disabled"
        if 'item_id=' in self.selector:
            return self.page.item_href
        return None

    async def is_enabled(self) -> bool:
        if "text=Post" in self.selector or "role=button" in self.selector:
            return self.page.post_enabled
        return True

    async def wait_for(self, **kwargs) -> None:
        return None

    async def set_input_files(self, files) -> None:
        self.page.events.append(("set_input_files", tuple(files)))
        self.page.input_files = list(files)

    async def fill(self, text: str, **kwargs) -> None:
        self.page.events.append(("fill", self.selector, text))
        if "catchy" in self.selector:
            self.page.title_text = text


class _Keyboard:
    """Minimal keyboard double used by the shared Draft.js caption path."""

    def __init__(self, page) -> None:
        self.page = page

    async def insert_text(self, text: str) -> None:
        self.page.events.append(("insert_text", text))
        self.page.caption_text += text

    async def press(self, key: str) -> None:
        self.page.events.append(("press", key))


class _TextTab:
    def __init__(self, page) -> None:
        self.page = page

    @property
    def first(self):
        return self

    async def count(self) -> int:
        return 1 if self.page.photos_tab else 0

    async def click(self, **kwargs) -> None:
        self.page.events.append(("photos_tab_click",))
        self.page.photo_mode = True
        self.page.image_input = True


class _StudioPage:
    def __init__(
        self,
        *,
        photo_mode: bool = True,
        photos_tab: bool = True,
        image_input: bool | None = None,
    ) -> None:
        self.url = "about:blank"
        self.photo_mode = photo_mode
        self.photos_tab = photos_tab
        self.image_input = photo_mode if image_input is None else image_input
        self.events: list = []
        self.goto_calls: list[tuple[str, dict]] = []
        self.wait_for_url_calls: list[tuple[str, dict]] = []
        self.input_files: list[str] | None = None
        self.post_enabled = True
        self.processed = True
        self.item_href = (
            "https://www.tiktok.com/@creator/post/photo"
            f"?item_id={ITEM_ID}&lang=en"
        )
        self.publish_clicked = False
        self.title_text = ""
        self.caption_text = ""
        self.keyboard = _Keyboard(self)

    async def goto(self, url: str, **kwargs):
        self.goto_calls.append((url, kwargs))
        self.url = url
        return SimpleNamespace(status=200)

    async def wait_for_url(self, url: str, **kwargs):
        self.wait_for_url_calls.append((url, kwargs))
        # Production accepts a regex/glob now; the fake simply lands on the
        # content page.
        self.url = "https://www.tiktok.com/tiktokstudio/content"

    async def wait_for_selector(self, selector: str, **kwargs):
        return object()

    async def wait_for_timeout(self, ms: int) -> None:
        return None

    def get_by_text(self, text: str, exact: bool = False):
        if text == "Photos":
            return _TextTab(self)
        return _Locator(self, f"text={text}", count=0)

    def get_by_role(self, role: str, name=None):
        if role == "tab" and name == "Photos":
            return _TextTab(self)
        if (
            role == "button"
            and hasattr(name, "fullmatch")
            and name.fullmatch("Post")
        ):
            return _Locator(self, "role=button[name=/^Post$/]", count=1)
        return _Locator(self, f"role={role}", count=0)

    def locator(self, selector: str) -> _Locator:
        if selector == 'input[placeholder*="catchy"]':
            return _Locator(self, selector, count=1 if self.photo_mode else 0)
        if selector in (
            'input[type="file"][accept*="image"]',
            'input[type="file"][multiple]',
        ):
            return _Locator(
                self, selector, count=1 if self.image_input else 0
            )
        if selector == 'input[placeholder="Add a catchy title"]':
            return _Locator(self, selector, count=1 if self.photo_mode else 0)
        if selector.endswith("div.public-DraftEditor-content"):
            return _Locator(self, selector, count=1 if self.photo_mode else 0)
        if selector == "div[data-id]":
            return _Locator(self, selector, count=1 if self.processed else 0)
        if "text=Post" in selector:
            return _Locator(self, selector, count=1)
        if selector == "div.button-group button":
            return _Locator(self, selector, count=1)
        if selector == "div[data-tt=\"components_PostTable_Container\"]":
            return _Locator(self, selector, count=1)
        if 'item_id=' in selector:
            return _Locator(self, selector, count=1 if self.item_href else 0)
        if selector == "body":
            return _Locator(self, selector, count=1)
        return _Locator(self, selector, count=0)


class _StudioContext:
    def __init__(self, page) -> None:
        self.pages = [page]
        self.new_page_calls = 0

    async def new_page(self):
        self.new_page_calls += 1
        return self.pages[0]


# ---------------------------------------------------------------------------
# Parser contract
# ---------------------------------------------------------------------------


class UploadNoteParserTests(unittest.TestCase):
    def test_upload_note_is_registered(self):
        self.assertIn("upload-note", _action_names("tiktok"))

    def test_images_is_required_multi_value_existing_file(self):
        parser = _subparser(sau_cli.build_parser(), "tiktok", "upload-note")
        action = parser._option_string_actions["--images"]
        self.assertTrue(action.required)
        self.assertEqual(action.nargs, "+")
        self.assertIs(action.type, existing_file_path)

    def test_allowed_options_are_present(self):
        options = _option_strings(
            _subparser(sau_cli.build_parser(), "tiktok", "upload-note")
        )
        for expected in (
            "--account",
            "--images",
            "--schedule",
            "--debug",
            "--headed",
            "--headless",
            "--folder-id",
            "--profile-id",
        ):
            with self.subTest(option=expected):
                self.assertIn(expected, options)

    def test_metadata_and_publish_options_are_present(self):
        options = _option_strings(
            _subparser(sau_cli.build_parser(), "tiktok", "upload-note")
        )
        for expected in (
            "--title",
            "--note",
            "--notef",
            "--tags",
            "--privacy",
            "--no-comments",
            "--aigc",
            "--no-aigc",
            "--your-brand",
            "--branded-content",
        ):
            with self.subTest(option=expected):
                self.assertIn(expected, options)

    def test_cover_and_reuse_options_are_still_absent(self):
        options = _option_strings(
            _subparser(sau_cli.build_parser(), "tiktok", "upload-note")
        )
        for forbidden in (
            "--disable-reuse",
            "--thumbnail",
            "--cover-index",
            "--bgm",
        ):
            with self.subTest(option=forbidden):
                self.assertNotIn(forbidden, options)

    def test_note_and_notef_are_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            note_file = Path(tmp_dir) / "note.txt"
            note_file.write_text("from file", encoding="utf-8")
            image = Path(tmp_dir) / "image.png"
            image.write_bytes(b"x")
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    sau_cli.build_parser().parse_args(
                        [
                            "tiktok",
                            "upload-note",
                            "--images",
                            str(image),
                            "--note",
                            "inline",
                            "--notef",
                            str(note_file),
                        ]
                    )
        self.assertEqual(ctx.exception.code, 2)

    def test_aigc_and_no_aigc_are_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image = Path(tmp_dir) / "image.png"
            image.write_bytes(b"x")
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    sau_cli.build_parser().parse_args(
                        [
                            "tiktok",
                            "upload-note",
                            "--images",
                            str(image),
                            "--aigc",
                            "--no-aigc",
                        ]
                    )
        self.assertEqual(ctx.exception.code, 2)

    def test_metadata_defaults_are_none_not_empty_strings(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image = Path(tmp_dir) / "image.png"
            image.write_bytes(b"x")
            args = sau_cli.build_parser().parse_args(
                [
                    "tiktok",
                    "upload-note",
                    "--images",
                    str(image),
                ]
            )
        self.assertIsNone(args.title)
        self.assertIsNone(args.note)
        self.assertIsNone(args.notef)
        self.assertEqual(args.tags, "")
        self.assertIsNone(args.aigc)
        self.assertIsNone(args.your_brand)
        self.assertIsNone(args.branded_content)
        self.assertIsNone(args.privacy)

    def test_parse_upload_note_keeps_image_order(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            first = Path(tmp_dir) / "first.PNG"
            second = Path(tmp_dir) / "second.webp"
            first.write_bytes(b"one")
            second.write_bytes(b"two")

            args = sau_cli.build_parser().parse_args(
                [
                    "tiktok",
                    "upload-note",
                    "--folder-id",
                    "folder",
                    "--profile-id",
                    "profile",
                    "--images",
                    str(first),
                    str(second),
                ]
            )

        self.assertEqual(args.action, "upload-note")
        self.assertEqual(args.images, [first, second])
        self.assertEqual(args.folder_id, "folder")
        self.assertEqual(args.profile_id, "profile")
        self.assertTrue(args.headless)
        self.assertIsNone(args.account)
        self.assertIsNone(args.schedule)


# ---------------------------------------------------------------------------
# Local validation before any browser work
# ---------------------------------------------------------------------------


class UploadNoteValidationTests(unittest.TestCase):
    def _images(self, tmp_dir: str, count: int) -> list[str]:
        paths = []
        for index in range(count):
            path = Path(tmp_dir) / f"image-{index}.png"
            path.write_bytes(b"x")
            paths.append(str(path))
        return paths

    def _assert_exit_2_without_browser(self, argv):
        playwright = MagicMock()
        session = MagicMock()
        target = MagicMock()
        with (
            patch.object(tiktok_command, "async_playwright", playwright),
            patch.object(tiktok_command, "browser_session", session),
            patch.object(
                tiktok_command, "resolve_multilogin_target", target
            ),
        ):
            code, out, err = _run(argv)
        self.assertEqual(code, 2)
        self.assertNotIn("submitted", out)
        self.assertTrue(err.strip())
        playwright.assert_not_called()
        session.assert_not_called()
        target.assert_not_called()

    def _argv(self, images: list[str], *extra: str) -> list[str]:
        return [
            "tiktok",
            "upload-note",
            "--images",
            *images,
            *extra,
        ]

    def test_zero_images_exits_2_without_browser(self):
        with tempfile.TemporaryDirectory():
            playwright = MagicMock()
            session = MagicMock()
            with (
                patch.object(tiktok_command, "async_playwright", playwright),
                patch.object(tiktok_command, "browser_session", session),
            ):
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as ctx:
                        sau_cli.main(
                            ["tiktok", "upload-note", "--images"]
                        )
        self.assertEqual(ctx.exception.code, 2)
        playwright.assert_not_called()
        session.assert_not_called()

    def test_more_than_35_images_exits_2_without_browser(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = self._images(tmp_dir, TIKTOK_MAX_IMAGE_COUNT + 1)
            self._assert_exit_2_without_browser(self._argv(images))

    def test_missing_file_exits_2_without_browser(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            missing = str(Path(tmp_dir) / "missing.png")
            playwright = MagicMock()
            session = MagicMock()
            with (
                patch.object(tiktok_command, "async_playwright", playwright),
                patch.object(tiktok_command, "browser_session", session),
            ):
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as ctx:
                        sau_cli.main(self._argv([missing]))
        self.assertEqual(ctx.exception.code, 2)
        playwright.assert_not_called()
        session.assert_not_called()

    def test_unsupported_extension_exits_2_without_browser(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            bad = Path(tmp_dir) / "clip.gif"
            bad.write_bytes(b"x")
            self._assert_exit_2_without_browser(self._argv([str(bad)]))

    def test_uppercase_extensions_are_accepted(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = []
            for name in ("a.JPG", "b.JPEG", "c.PnG", "d.WEBP"):
                path = Path(tmp_dir) / name
                path.write_bytes(b"x")
                images.append(str(path))

            request = tiktok_command.TiktokNoteUploadRequest(
                account_label=None,
                image_files=[Path(path) for path in images],
                note="",
                tags=[],
                publish_date=0,
            )
            tiktok_command._validate_note_images(request.image_files)
        self.assertEqual(
            {path.suffix.lower() for path in request.image_files},
            TIKTOK_IMAGE_SUFFIXES,
        )

    def test_file_over_50_mb_exits_2_without_browser(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            huge = Path(tmp_dir) / "huge.png"
            with huge.open("wb") as handle:
                handle.truncate(TIKTOK_MAX_IMAGE_BYTES + 1)
            self._assert_exit_2_without_browser(self._argv([str(huge)]))

    def test_title_over_90_characters_exits_2_without_browser(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = self._images(tmp_dir, 1)
            self._assert_exit_2_without_browser(
                self._argv(images, "--title", "x" * 91)
            )

    def test_description_over_4000_characters_exits_2_without_browser(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = self._images(tmp_dir, 1)
            self._assert_exit_2_without_browser(
                self._argv(images, "--note", "x" * 4001)
            )

    def test_scheduled_note_without_any_text_exits_2_without_browser(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = self._images(tmp_dir, 1)
            self._assert_exit_2_without_browser(
                self._argv(
                    images,
                    "--schedule",
                    "2026-11-06 18:15",
                )
            )

    def test_scheduled_note_with_only_tags_exits_2_without_browser(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = self._images(tmp_dir, 1)
            self._assert_exit_2_without_browser(
                self._argv(
                    images,
                    "--tags",
                    "fyp",
                    "--schedule",
                    "2026-11-06 18:15",
                )
            )

    def test_description_length_includes_expanded_tags(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = self._images(tmp_dir, 1)
            self._assert_exit_2_without_browser(
                self._argv(
                    images,
                    "--note",
                    "x" * 3990,
                    "--tags",
                    "0123456789",
                )
            )

    def test_more_than_50_hashtags_exits_2_without_browser(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = self._images(tmp_dir, 1)
            tags = ",".join(f"tag{index}" for index in range(51))
            self._assert_exit_2_without_browser(
                self._argv(images, "--tags", tags)
            )

    def test_missing_notef_file_exits_2_without_browser(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = self._images(tmp_dir, 1)
            missing = str(Path(tmp_dir) / "missing.txt")
            playwright = MagicMock()
            session = MagicMock()
            with (
                patch.object(tiktok_command, "async_playwright", playwright),
                patch.object(tiktok_command, "browser_session", session),
                redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(SystemExit) as ctx:
                    sau_cli.main(
                        self._argv(images, "--notef", missing)
                    )
        self.assertEqual(ctx.exception.code, 2)
        playwright.assert_not_called()
        session.assert_not_called()

    def test_unreadable_notef_file_exits_2_without_browser(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = self._images(tmp_dir, 1)
            unreadable = Path(tmp_dir) / "notes.txt"
            unreadable.mkdir()
            playwright = MagicMock()
            session = MagicMock()
            with (
                patch.object(tiktok_command, "async_playwright", playwright),
                patch.object(tiktok_command, "browser_session", session),
                redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(SystemExit) as ctx:
                    sau_cli.main(
                        self._argv(images, "--notef", str(unreadable))
                    )
        self.assertEqual(ctx.exception.code, 2)
        playwright.assert_not_called()
        session.assert_not_called()

    def test_branded_content_with_only_me_exits_2_without_browser(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = self._images(tmp_dir, 1)
            self._assert_exit_2_without_browser(
                self._argv(
                    images,
                    "--privacy",
                    "only-me",
                    "--branded-content",
                )
            )


# ---------------------------------------------------------------------------
# Mapping and builder
# ---------------------------------------------------------------------------


class UploadNoteBuilderTests(unittest.TestCase):
    def test_note_init_signature_is_keyword_only_after_account(self):
        params = list(inspect.signature(TiktokNote.__init__).parameters.values())
        self.assertEqual(
            [param.name for param in params],
            [
                "self",
                "image_paths",
                "note",
                "tags",
                "publish_date",
                "account_file",
                "title",
                "options",
                "debug",
                "headless",
            ],
        )
        for param in params[6:]:
            with self.subTest(param=param.name):
                self.assertIs(param.kind, inspect.Parameter.KEYWORD_ONLY)

    def test_builder_preserves_order_and_first_image_is_cover(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            first = Path(tmp_dir) / "first.png"
            second = Path(tmp_dir) / "second.jpg"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            request = tiktok_command.TiktokNoteUploadRequest(
                account_label="profile",
                image_files=[first, second],
                note="",
                tags=[],
                publish_date=0,
            )
            app = tiktok_command._build_note_uploader(request)

        self.assertIsInstance(app, TiktokNote)
        self.assertEqual(app.image_paths, [str(first), str(second)])
        self.assertEqual(app.image_paths[0], str(first))
        self.assertIsNone(app.account_file)
        self.assertIsNone(app.title)
        self.assertIsNone(app.options)
        # The first image is the cover: no cover step is overridden.
        self.assertIs(TiktokNote.apply_cover, TiktokBaseUploader.apply_cover)

    def test_builder_carries_metadata_and_publish_options(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image = Path(tmp_dir) / "first.png"
            image.write_bytes(b"one")
            options = TiktokPublishOptions(
                privacy="friends",
                allow_comments=False,
                aigc=True,
                your_brand=True,
            )
            request = tiktok_command.TiktokNoteUploadRequest(
                account_label="profile",
                image_files=[image],
                note="hello",
                tags=["one", "two"],
                publish_date=0,
                title="My title",
                options=options,
            )
            app = tiktok_command._build_note_uploader(request)

        self.assertEqual(app.title, "My title")
        self.assertEqual(app.note, "hello")
        self.assertEqual(app.tags, ["one", "two"])
        self.assertEqual(app.options, options)
        self.assertIsNone(app.options.allow_reuse)

    def test_note_publish_options_never_request_reuse(self):
        args = SimpleNamespace(
            privacy="followers",
            no_comments=True,
            aigc=False,
            your_brand=True,
            branded_content=None,
        )
        options = tiktok_command._build_publish_options(args)
        self.assertEqual(
            options,
            TiktokPublishOptions(
                privacy="followers",
                allow_comments=False,
                allow_reuse=None,
                aigc=False,
                your_brand=True,
                branded_content=None,
            ),
        )
        self.assertIsNone(options.allow_reuse)

    def test_upload_urls_are_media_specific(self):
        self.assertEqual(TiktokBaseUploader.upload_url, TIKTOK_UPLOAD_URL)
        self.assertEqual(TiktokNote.upload_url, TIKTOK_PHOTO_UPLOAD_URL)


# ---------------------------------------------------------------------------
# CLI happy path / local mode
# ---------------------------------------------------------------------------


class UploadNoteCliTests(unittest.TestCase):
    def _images(self, tmp_dir: str) -> list[str]:
        paths = []
        for name in ("one.png", "two.jpg", "three.webp"):
            path = Path(tmp_dir) / name
            path.write_bytes(b"x")
            paths.append(str(path))
        return paths

    def test_happy_path_prints_image_count_and_uses_one_session(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = self._images(tmp_dir)
            session, session_cm, factory = _fake_session(object())
            app = MagicMock()
            app.upload = AsyncMock()
            builder = MagicMock(return_value=app)

            with (
                patch.object(
                    tiktok_command, "async_playwright", lambda: _AsyncCM(object())
                ),
                patch.object(tiktok_command, "browser_session", new=factory),
                patch.object(
                    tiktok_command, "is_logged_in", new=AsyncMock(return_value=True)
                ) as probe,
                patch.object(
                    tiktok_command, "_build_note_uploader", new=builder
                ),
            ):
                code, out, err = _run(
                    [
                        "tiktok",
                        "upload-note",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--images",
                        *images,
                    ]
                )

        self.assertEqual(code, 0, err)
        self.assertIn(
            f"TikTok note upload submitted: {len(images)} images", out
        )
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(session_cm.enter_calls, 1)
        self.assertEqual(session_cm.exit_calls, 1)
        probe.assert_awaited_once_with(session.context)
        app.upload.assert_awaited_once_with(None, session=session)
        request = builder.call_args.args[0]
        self.assertEqual(
            [str(path) for path in request.image_files], images
        )

    def test_cli_maps_metadata_and_publish_options(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = self._images(tmp_dir)
            _, _, factory = _fake_session(object())
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
                    tiktok_command, "_build_note_uploader", new=builder
                ),
            ):
                code, out, err = _run(
                    [
                        "tiktok",
                        "upload-note",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--images",
                        *images,
                        "--title",
                        "Photo title",
                        "--note",
                        "Photo body",
                        "--tags",
                        "one, two",
                        "--privacy",
                        "friends",
                        "--no-comments",
                        "--aigc",
                        "--your-brand",
                    ]
                )

        self.assertEqual(code, 0, err)
        request = builder.call_args.args[0]
        self.assertEqual(request.title, "Photo title")
        self.assertEqual(request.note, "Photo body")
        self.assertEqual(request.tags, ["one", "two"])
        self.assertEqual(
            request.options,
            TiktokPublishOptions(
                privacy="friends",
                allow_comments=False,
                allow_reuse=None,
                aigc=True,
                your_brand=True,
                branded_content=None,
            ),
        )
        self.assertIsNone(request.options.allow_reuse)

    def test_cli_notef_reads_the_file_as_description(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = self._images(tmp_dir)
            note_file = Path(tmp_dir) / "note.md"
            note_file.write_text("from a markdown file", encoding="utf-8")
            _, _, factory = _fake_session(object())
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
                    tiktok_command, "_build_note_uploader", new=builder
                ),
            ):
                code, out, err = _run(
                    [
                        "tiktok",
                        "upload-note",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--images",
                        *images,
                        "--notef",
                        str(note_file),
                    ]
                )

        self.assertEqual(code, 0, err)
        request = builder.call_args.args[0]
        self.assertEqual(request.note, "from a markdown file")

    def test_cli_without_metadata_keeps_none_and_empty_tags(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = self._images(tmp_dir)
            _, _, factory = _fake_session(object())
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
                    tiktok_command, "_build_note_uploader", new=builder
                ),
            ):
                code, out, err = _run(
                    [
                        "tiktok",
                        "upload-note",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--images",
                        *images,
                    ]
                )

        self.assertEqual(code, 0, err)
        request = builder.call_args.args[0]
        self.assertIsNone(request.title)
        self.assertIsNone(request.note)
        self.assertEqual(request.tags, [])
        self.assertIsNone(request.options)

    def test_local_mode_uses_cookie_and_local_upload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = self._images(tmp_dir)
            account_file = Path(tmp_dir) / "tiktok_creator.json"
            playwright = object()
            app = MagicMock()
            app.upload = AsyncMock()
            builder = MagicMock(return_value=app)
            setup = AsyncMock(return_value=True)
            session = MagicMock()
            with (
                patch.object(
                    tiktok_command,
                    "async_playwright",
                    lambda: _AsyncCM(playwright),
                ),
                patch.object(
                    tiktok_command,
                    "resolve_account_file",
                    return_value=account_file,
                ),
                patch.object(tiktok_command, "tiktok_setup", new=setup),
                patch.object(
                    tiktok_command, "_build_note_uploader", new=builder
                ),
                patch.object(tiktok_command, "browser_session", new=session),
            ):
                code, out, err = _run(
                    [
                        "tiktok",
                        "upload-note",
                        "--account",
                        "creator",
                        "--images",
                        *images,
                    ],
                    token="",
                )

        self.assertEqual(code, 0, err)
        self.assertIn(
            f"TikTok note upload submitted: {len(images)} images", out
        )
        setup.assert_awaited_once_with(
            str(account_file), handle=False, headless=True
        )
        self.assertEqual(builder.call_args.args[0].account_file, account_file)
        app.upload.assert_awaited_once_with(playwright)
        session.assert_not_called()

    def test_logged_out_exits_10(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = self._images(tmp_dir)
            _, session_cm, factory = _fake_session(object())
            app = MagicMock()
            app.upload = AsyncMock()
            with (
                patch.object(
                    tiktok_command, "async_playwright", lambda: _AsyncCM(object())
                ),
                patch.object(tiktok_command, "browser_session", new=factory),
                patch.object(
                    tiktok_command, "is_logged_in", new=AsyncMock(return_value=False)
                ),
                patch.object(
                    tiktok_command,
                    "_build_note_uploader",
                    new=MagicMock(return_value=app),
                ),
            ):
                code, out, _ = _run(
                    [
                        "tiktok",
                        "upload-note",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--images",
                        *images,
                    ]
                )
        self.assertEqual(code, 10)
        self.assertNotIn("submitted", out)
        app.upload.assert_not_awaited()
        self.assertEqual(session_cm.exit_calls, 1)


# ---------------------------------------------------------------------------
# Photo-specific flow (real TiktokNote against the in-memory page)
# ---------------------------------------------------------------------------


class UploadNoteFlowTests(unittest.TestCase):
    def _note(self, images: list[str]) -> TiktokNote:
        return TiktokNote(images, "", [], 0, None, title=None)

    def _run_cli(self, page, images):
        session, session_cm, factory = _fake_session(_StudioContext(page))
        with (
            patch.object(
                tk_main, "TIKTOK_HASHTAG_SUGGESTION_TIMEOUT_MS", 0
            ),
            patch.object(
                tiktok_command, "async_playwright", lambda: _AsyncCM(object())
            ),
            patch.object(tiktok_command, "browser_session", new=factory),
            patch.object(
                tiktok_command, "is_logged_in", new=AsyncMock(return_value=True)
            ),
        ):
            code, out, err = _run(
                [
                    "tiktok",
                    "upload-note",
                    "--folder-id",
                    "folder",
                    "--profile-id",
                    "profile",
                    "--images",
                    *images,
                ]
            )
        return code, out, err, session_cm

    def test_photos_tab_probe_precedes_file_selection_and_order_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = []
            for name in ("cover.png", "second.jpg", "third.webp"):
                path = Path(tmp_dir) / name
                path.write_bytes(b"x")
                images.append(str(path))

            page = _StudioPage(photo_mode=False, photos_tab=True)
            code, out, err, session_cm = self._run_cli(page, images)

        self.assertEqual(code, 0, err)
        self.assertIn("TikTok note upload submitted: 3 images", out)
        self.assertEqual(page.goto_calls[0][0], TIKTOK_PHOTO_UPLOAD_URL)
        self.assertEqual(page.input_files, images)
        self.assertEqual(page.input_files[0], images[0])
        self.assertEqual(session_cm.exit_calls, 1)

        tab_index = page.events.index(("photos_tab_click",))
        select_index = page.events.index(
            ("set_input_files", tuple(images))
        )
        self.assertLess(tab_index, select_index)
        self.assertFalse(page.goto_calls[0][0].endswith("/upload"))

    def test_missing_photos_tab_exits_1_before_selecting_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = []
            for name in ("cover.png", "second.jpg"):
                path = Path(tmp_dir) / name
                path.write_bytes(b"x")
                images.append(str(path))

            page = _StudioPage(photo_mode=False, photos_tab=False)
            code, out, err, session_cm = self._run_cli(page, images)

        self.assertEqual(code, 1)
        self.assertNotIn("submitted", out)
        self.assertIn("Photos", err)
        self.assertIn("未覆盖", err)
        self.assertIsNone(page.input_files)
        self.assertFalse(
            any(event[0] == "set_input_files" for event in page.events)
        )
        self.assertEqual(session_cm.exit_calls, 1)

    def test_image_input_is_the_photo_mode_signal_without_title(self):
        # Real Studio renders the Title input only after images are selected,
        # so the image file input's accept attribute is the pre-selection
        # signal.  Title remains optional.
        with tempfile.TemporaryDirectory() as tmp_dir:
            image = Path(tmp_dir) / "cover.png"
            image.write_bytes(b"x")
            page = _StudioPage(
                photo_mode=False, photos_tab=False, image_input=True
            )
            code, out, err, session_cm = self._run_cli(page, [str(image)])

        self.assertEqual(code, 0, err)
        self.assertIn("TikTok note upload submitted: 1 images", out)
        self.assertEqual(page.input_files, [str(image)])
        self.assertEqual(session_cm.exit_calls, 1)

    def test_no_reuse_duet_or_stitch_controls_are_touched(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image = Path(tmp_dir) / "cover.png"
            image.write_bytes(b"x")
            page = _StudioPage()
            self._run_cli(page, [str(image)])

        touched = " ".join(
            str(event[1] if len(event) > 1 else event) for event in page.events
        ).lower()
        for forbidden in ("reuse", "duet", "stitch"):
            with self.subTest(control=forbidden):
                self.assertNotIn(forbidden, touched)

    def test_read_result_extracts_the_item_id(self):
        note = self._note(["/tmp/cover.png"])
        page = _StudioPage()
        self.assertEqual(asyncio.run(note.read_result(page)), ITEM_ID)

    def test_read_result_without_a_photo_link_raises(self):
        note = self._note(["/tmp/cover.png"])
        page = _StudioPage()
        page.item_href = None
        with patch.object(tk_main, "TIKTOK_RESULT_READ_TIMEOUT_MS", 0):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(note.read_result(page))

        message = str(ctx.exception)
        # Exit 1 read failures must not reuse the reserved exit-9 term.
        self.assertNotIn("发布结果未知", message)
        self.assertIn("发布结果读取失败", message)
        self.assertIn("Content", message)

    def test_photo_upload_local_branch_launches_and_closes(self):
        from tests.fakes import FakePlaywright

        note = TiktokNote(
            ["/tmp/cover.png"], "", [], 0, "/tmp/cookie.json", title=None
        )
        note.change_language = AsyncMock()
        note._upload_on_page = AsyncMock()
        playwright = FakePlaywright()

        with (
            patch.object(tk_main.asyncio, "sleep", AsyncMock()),
            patch.object(tk_main.time, "monotonic", return_value=1000.0),
        ):
            asyncio.run(note.upload(playwright))

        self.assertEqual(
            playwright.chromium.launch_calls,
            [{"headless": True, **TIKTOK_LAUNCH_KWARGS}],
        )
        browser = playwright.chromium.launch_browser
        context = browser.contexts[0]
        note._upload_on_page.assert_awaited_once_with(
            ANY, multilogin=False, deadline=1900.0
        )
        self.assertEqual(context.storage_state_calls, ["/tmp/cookie.json"])
        self.assertTrue(context.closed)
        self.assertTrue(browser.closed)


# ---------------------------------------------------------------------------
# Photo metadata (Title / Description / tags)
# ---------------------------------------------------------------------------


class UploadNoteMetadataTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(
            tk_main, "TIKTOK_HASHTAG_SUGGESTION_TIMEOUT_MS", 0
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _note(
        self,
        *,
        title=None,
        note=None,
        tags=(),
    ) -> TiktokNote:
        return TiktokNote(
            ["/tmp/cover.png"],
            note,
            list(tags),
            0,
            None,
            title=title,
        )

    def _page(self) -> _StudioPage:
        return _StudioPage()

    def test_title_is_filled_only_when_provided(self):
        page = self._page()
        note = self._note(title="My photo title")
        note.locator_base = page.locator("body")

        asyncio.run(note.fill_metadata(page))

        self.assertEqual(page.title_text, "My photo title")
        self.assertEqual(page.caption_text, "")
        self.assertFalse(
            any(event[0] == "insert_text" for event in page.events)
        )

    def test_absent_or_empty_title_never_overwrites_the_page(self):
        for title in (None, ""):
            with self.subTest(title=title):
                page = self._page()
                note = self._note(title=title, note="hello")
                note.locator_base = page.locator("body")

                asyncio.run(note.fill_metadata(page))

                self.assertEqual(page.title_text, "")
                self.assertFalse(
                    any(event[0] == "fill" for event in page.events)
                )

    def test_caption_clear_uses_control_or_meta(self):
        page = self._page()
        note = self._note(note="hello")
        note.locator_base = page.locator("body")

        asyncio.run(note.fill_metadata(page))

        self.assertIn(("press", "ControlOrMeta+A"), page.events)

    def test_description_and_tags_follow_the_note_text(self):
        page = self._page()
        note = self._note(note="hello world", tags=("one", "two"))
        note.locator_base = page.locator("body")

        asyncio.run(note.fill_metadata(page))

        self.assertTrue(page.caption_text.startswith("hello world"))
        self.assertIn("#one", page.caption_text)
        self.assertIn("#two", page.caption_text)
        self.assertLess(
            page.caption_text.index("#one"), page.caption_text.index("#two")
        )

    def test_tags_only_still_reach_the_editor(self):
        page = self._page()
        note = self._note(tags=("only",))
        note.locator_base = page.locator("body")

        asyncio.run(note.fill_metadata(page))

        self.assertIn("#only", page.caption_text)

    def test_no_note_and_no_tags_makes_zero_editor_interactions(self):
        page = self._page()
        note = self._note()
        note.locator_base = page.locator("body")

        asyncio.run(note.fill_metadata(page))

        touched = [
            event
            for event in page.events
            if event[0] in ("fill", "insert_text", "press")
        ]
        self.assertEqual(touched, [])
        self.assertEqual(page.caption_text, "")
        self.assertEqual(page.title_text, "")

    def test_metadata_fill_does_not_touch_images(self):
        page = self._page()
        note = self._note(title="T", note="hello", tags=("one",))
        note.locator_base = page.locator("body")

        asyncio.run(note.fill_metadata(page))

        self.assertFalse(
            any(event[0] == "set_input_files" for event in page.events)
        )


# ---------------------------------------------------------------------------
# Photo publish options (reuse the shared ticket 12/13 steps)
# ---------------------------------------------------------------------------


class _FakeToggle:
    def __init__(self, checked: bool, *, click_toggles: bool = True) -> None:
        self.checked = checked
        self.click_toggles = click_toggles
        self.checked_reads = 0
        self.disabled_reads = 0
        self.click_calls = 0
        self.candidates = ("fake-toggle",)

    async def is_checked(self) -> bool:
        self.checked_reads += 1
        return self.checked

    async def is_disabled(self) -> bool:
        self.disabled_reads += 1
        return False

    async def click(self) -> None:
        self.click_calls += 1
        if self.click_toggles:
            self.checked = not self.checked

    async def get_attribute(self, name: str) -> str | None:
        if name == "aria-checked":
            return "true" if self.checked else "false"
        return None

    async def read_text(self) -> str:
        return "checked" if self.checked else "unchecked"

    async def options(self):
        return []


class _FakePrivacyOption:
    def __init__(self, label: str) -> None:
        self.label = label
        self.on_click = None

    async def read_text(self) -> str:
        return self.label

    async def is_disabled(self) -> bool:
        return False

    async def click(self) -> None:
        if self.on_click is not None:
            self.on_click(self)

    async def get_attribute(self, name: str) -> str | None:
        return "true" if name == "aria-selected" else None


class _FakePrivacy:
    def __init__(self, label: str, labels) -> None:
        self.label = label
        self.open_calls = 0
        self.candidates = ("fake-privacy",)
        self._options = []
        for item in labels:
            option = _FakePrivacyOption(item)
            option.on_click = self._select
            self._options.append(option)

    def _select(self, option: _FakePrivacyOption) -> None:
        self.label = option.label

    async def read_text(self) -> str:
        return self.label

    async def is_disabled(self) -> bool:
        return False

    async def click(self) -> None:
        self.open_calls += 1

    async def options(self):
        return list(self._options)

    async def is_checked(self) -> bool:
        return False

    async def get_attribute(self, name: str) -> str | None:
        return None


def _note_controls(
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


class UploadNoteOptionTests(unittest.TestCase):
    def _note(self, options) -> TiktokNote:
        return TiktokNote(
            ["/tmp/cover.png"],
            None,
            [],
            0,
            None,
            title=None,
            options=options,
        )

    def _install(self, note, controls):
        resolver = AsyncMock(return_value=controls)
        note.resolve_option_controls = resolver
        return resolver

    def test_privacy_comments_aigc_and_brand_are_applied_and_read_back(self):
        privacy = _FakePrivacy("Everyone", ["Everyone", "Friends", "Only you"])
        comments = _FakeToggle(True)
        aigc = _FakeToggle(False)
        master = _FakeToggle(False)
        your_brand = _FakeToggle(False)
        branded = _FakeToggle(False)
        note = self._note(
            TiktokPublishOptions(
                privacy="friends",
                allow_comments=False,
                aigc=True,
                your_brand=True,
                branded_content=True,
            )
        )
        self._install(
            note,
            _note_controls(
                privacy=privacy,
                comments=comments,
                aigc=aigc,
                brand_switch=master,
                your_brand=your_brand,
                branded_content=branded,
            ),
        )

        asyncio.run(note.apply_options(_StudioPage()))

        self.assertEqual(privacy.label, "Friends")
        self.assertFalse(comments.checked)
        self.assertTrue(aigc.checked)
        self.assertTrue(master.checked)
        self.assertTrue(your_brand.checked)
        self.assertTrue(branded.checked)

    def test_reuse_control_is_never_requested_or_touched(self):
        reuse = _FakeToggle(True)
        note = self._note(TiktokPublishOptions(allow_reuse=False))
        resolver = self._install(
            note, _note_controls(reuse=reuse)
        )

        asyncio.run(note.apply_options(_StudioPage()))

        resolver.assert_not_awaited()
        self.assertEqual(reuse.checked_reads, 0)
        self.assertEqual(reuse.disabled_reads, 0)
        self.assertEqual(reuse.click_calls, 0)

    def test_reuse_stays_untouched_even_with_other_options(self):
        reuse = _FakeToggle(True)
        comments = _FakeToggle(True)
        note = self._note(
            TiktokPublishOptions(allow_reuse=True, allow_comments=False)
        )
        self._install(note, _note_controls(reuse=reuse, comments=comments))

        asyncio.run(note.apply_options(_StudioPage()))

        self.assertFalse(comments.checked)
        self.assertEqual(reuse.checked_reads, 0)
        self.assertEqual(reuse.click_calls, 0)

    def test_cli_missing_aigc_control_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image = Path(tmp_dir) / "cover.png"
            image.write_bytes(b"x")
            session, session_cm, factory = _fake_session(
                _StudioContext(_StudioPage())
            )
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
                    TiktokNote,
                    "resolve_option_controls",
                    new=AsyncMock(return_value=_note_controls(aigc=None)),
                ),
            ):
                code, out, err = _run(
                    [
                        "tiktok",
                        "upload-note",
                        "--folder-id",
                        "folder",
                        "--profile-id",
                        "profile",
                        "--images",
                        str(image),
                        "--aigc",
                    ]
                )

        self.assertEqual(code, 1)
        self.assertNotIn("submitted", out)
        self.assertIn("aigc", err)
        self.assertIn("control-not-found", err)
        self.assertEqual(session_cm.exit_calls, 1)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class UploadNoteConstantsTests(unittest.TestCase):
    def test_web_ui_limits(self):
        self.assertEqual(TIKTOK_MAX_IMAGE_COUNT, 35)
        self.assertEqual(TIKTOK_MAX_IMAGE_BYTES, 50 * 1024 * 1024)
        self.assertEqual(TIKTOK_MAX_TITLE_LENGTH, 90)
        self.assertEqual(TIKTOK_MAX_DESCRIPTION_LENGTH, 4000)
        self.assertEqual(TIKTOK_MAX_HASHTAG_COUNT, 50)
        self.assertEqual(
            TIKTOK_IMAGE_SUFFIXES, {".jpg", ".jpeg", ".png", ".webp"}
        )
        self.assertEqual(
            TIKTOK_PHOTO_UPLOAD_URL,
            "https://www.tiktok.com/tiktokstudio/upload?tab=photo",
        )

    def test_constants_are_re_exported_from_main_chrome(self):
        self.assertEqual(
            tk_main.TIKTOK_PHOTO_UPLOAD_URL, TIKTOK_PHOTO_UPLOAD_URL
        )
        self.assertEqual(tk_main.TIKTOK_MAX_IMAGE_COUNT, 35)
        self.assertEqual(
            tk_main.TIKTOK_MAX_IMAGE_BYTES, 50 * 1024 * 1024
        )
        self.assertEqual(tk_main.TIKTOK_MAX_TITLE_LENGTH, 90)
        self.assertEqual(tk_main.TIKTOK_MAX_DESCRIPTION_LENGTH, 4000)
        self.assertEqual(tk_main.TIKTOK_MAX_HASHTAG_COUNT, 50)
        self.assertEqual(
            tk_main.TIKTOK_IMAGE_SUFFIXES,
            {".jpg", ".jpeg", ".png", ".webp"},
        )


if __name__ == "__main__":
    unittest.main()
