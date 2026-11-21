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
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import sau_cli
from sau_commands import tiktok as tiktok_command
from uploader.tk_uploader import main_chrome as tk_main
from uploader.tk_uploader.main_chrome import (
    TIKTOK_LAUNCH_KWARGS,
    TiktokBaseUploader,
    TiktokNote,
    TiktokPublishOptions,
)
from uploader.tk_uploader.tk_config import (
    TIKTOK_IMAGE_SUFFIXES,
    TIKTOK_PHOTO_UPLOAD_URL,
    TIKTOK_UPLOAD_URL,
)
from utils.dom import ElementUnusableError

TOKEN = "SENTINEL-MLX-TOKEN-ticket15"
ITEM_ID = "7412345678901234567"


# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------


def _subparser(parser: argparse.ArgumentParser, platform: str, action: str):
    for item in parser._actions:
        if isinstance(item, argparse._SubParsersAction):
            if platform in item.choices:
                platform_parser = item.choices[platform]
                for nested in platform_parser._actions:
                    if isinstance(nested, argparse._SubParsersAction):
                        return nested.choices[action]
    raise AssertionError(f"parser not found: {platform}/{action}")


def _option_strings(parser: argparse.ArgumentParser) -> set[str]:
    return set(parser._option_string_actions)


def _run(argv, token=TOKEN):
    with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"MLX_API_TOKEN": token, "HOME": home}):
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

    async def hover(self, **kwargs) -> None:
        # 平台点击入口先 hover 再 click；这里保持事件流不变。
        return None

    async def click(self, **kwargs) -> None:
        self.page.events.append(("click", self.selector))
        if "button-group" in self.selector:
            self.page.publish_clicked = True
        if "catchy" in self.selector:
            self.page.keyboard_target = "title"
        elif "DraftEditor" in self.selector or "caption" in self.selector:
            self.page.keyboard_target = "caption"

    async def inner_text(self) -> str:
        if self.selector == "body":
            return self.page.body_text
        if 'item_id=' in self.selector:
            return self.page.caption_text or self.page.title_text or ""
        if self.selector.endswith("div.public-DraftEditor-content"):
            return self.page.caption_text
        return ""

    async def all_inner_texts(self) -> list[str]:
        if '[data-e2e="poi_container"]' in self.selector and self.page.location_notice:
            return [self.page.location_notice]
        return []

    async def get_attribute(self, name: str, *, timeout=None):
        if "text=Post" in self.selector:
            return None if self.page.post_enabled else "disabled"
        if 'item_id=' in self.selector:
            return self.page.item_href
        return None

    async def is_visible(self) -> bool:
        return self._count > 0

    async def is_enabled(self, *, timeout=None) -> bool:
        if "text=Post" in self.selector or "role=button" in self.selector:
            return self.page.post_enabled
        return True

    async def wait_for(self, **kwargs) -> None:
        return None

    async def set_input_files(self, files, *, timeout=None) -> None:
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
        if self.page.keyboard_target == "title":
            self.page.title_text += text
        else:
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

    async def hover(self, **kwargs) -> None:
        # 平台点击入口先 hover 再 click；这里保持事件流不变。
        return None

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
        self.body_text = ""
        self.location_notice = None
        self.keyboard_target = "caption"
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
        if selector == '[data-e2e="post_video_button"]':
            # 真实 Studio 的发布按钮锚点；单次派发要求 fake 也暴露它。
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
    def test_images_accepts_multiple_local_files_and_direct_urls(self):
        parser = _subparser(sau_cli.build_parser(), "tiktok", "upload-note")
        action = parser._option_string_actions["--images"]
        self.assertTrue(action.required)
        self.assertEqual(action.nargs, "+")
        url = "https://cdn.example/photo?signature=1"
        args = parser.parse_args(["--images", __file__, url, __file__])
        self.assertEqual(args.images, [Path(__file__), url, Path(__file__)])

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
        self.assertFalse(args.headless)
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
                tiktok_command, "resolve_managed_provider", target
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
            images = self._images(tmp_dir, 36)
            tiktok_command._validate_note_images([Path(path) for path in images[:35]])
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
                handle.truncate(50 * 1024 * 1024)
                tiktok_command._validate_note_images([huge])
                handle.truncate(50 * 1024 * 1024 + 1)
            self._assert_exit_2_without_browser(self._argv([str(huge)]))

    def test_title_over_90_characters_exits_2_without_browser(self):
        tiktok_command._validate_note_metadata("x" * 90, None)
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = self._images(tmp_dir, 1)
            self._assert_exit_2_without_browser(
                self._argv(images, "--title", "x" * 91)
            )

    def test_description_over_4000_characters_exits_2_without_browser(self):
        tiktok_command._validate_note_metadata(None, "x" * 4000)
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
                    "2026-11-06T10:15:00Z",
                )
            )

    def test_description_length_counts_inline_topics(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = self._images(tmp_dir, 1)
            self._assert_exit_2_without_browser(
                self._argv(images, "--note", "x" * 3996 + " #tag")
            )

    def test_inline_topics_over_50_are_not_statically_rejected(self):
        # Inline occurrences are associations, not camera-ready text: the
        # uploader keeps the 51st word and reports the per-post limit.
        caption = " ".join(f"#tag{index}" for index in range(51))
        tiktok_command._validate_note_metadata(None, caption)

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

    def test_blank_location_exits_2_without_browser(self):
        for value in ("", "   ", "\t \n"):
            with self.subTest(value=repr(value)):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    images = self._images(tmp_dir, 1)
                    self._assert_exit_2_without_browser(
                        self._argv(images, "--location", value)
                    )


# ---------------------------------------------------------------------------
# Mapping and builder
# ---------------------------------------------------------------------------


class UploadNoteBuilderTests(unittest.TestCase):
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
                        "--debug",
                        "--headless",
                        "--images",
                        *images,
                        "--title",
                        "Photo title",
                        "--note",
                        "Photo body #one #two",
                        "--privacy",
                        "friends",
                        "--no-comments",
                        "--no-aigc",
                        "--your-brand",
                        "--location",
                        "  London   Eye ",
                    ]
                )

        self.assertEqual(code, 0, err)
        request = builder.call_args.args[0]
        self.assertEqual(request.title, "Photo title")
        self.assertEqual(request.note, "Photo body #one #two")
        self.assertEqual(request.tags, [])
        self.assertTrue(request.debug)
        self.assertTrue(request.headless)
        self.assertEqual(
            request.options,
            TiktokPublishOptions(
                privacy="friends",
                allow_comments=False,
                allow_reuse=None,
                aigc=False,
                your_brand=True,
                branded_content=None,
                location="  London   Eye ",
            ),
        )
        self.assertIsNone(request.options.allow_reuse)

    def test_cli_notef_reads_the_file_as_description(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = self._images(tmp_dir)
            note_file = Path(tmp_dir) / "note.md"
            note_file.write_text("from a markdown file #fromfile", encoding="utf-8")
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
        self.assertEqual(request.note, "from a markdown file #fromfile")
        self.assertEqual(request.tags, [])

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
        self.assertEqual(page.goto_calls[0][0], "https://www.tiktok.com/tiktokstudio/upload?tab=photo")
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
            any(event[0] == "fill" for event in page.events)
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

    def test_inline_topics_follow_the_note_text(self):
        page = self._page()
        note = self._note(note="hello world #one #two")
        note.locator_base = page.locator("body")

        asyncio.run(note.fill_metadata(page))

        self.assertTrue(page.caption_text.startswith("hello world"))
        self.assertIn("#one", page.caption_text)
        self.assertIn("#two", page.caption_text)
        self.assertLess(
            page.caption_text.index("#one"), page.caption_text.index("#two")
        )

    def test_python_tags_alone_fill_the_caption(self):
        page = self._page()
        note = self._note(tags=("only",))
        note.locator_base = page.locator("body")

        asyncio.run(note.fill_metadata(page))

        self.assertEqual(page.caption_text, "#only")

    def test_no_note_makes_zero_editor_interactions(self):
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
        note = self._note(title="T", note="hello #one")
        note.locator_base = page.locator("body")

        asyncio.run(note.fill_metadata(page))

        self.assertFalse(
            any(event[0] == "set_input_files" for event in page.events)
        )


# ---------------------------------------------------------------------------
# Photo publish options (reuse the shared ticket 12/13 steps)
# ---------------------------------------------------------------------------


class _FakeToggle:
    def __init__(
        self,
        checked: bool,
        *,
        click_toggles: bool = True,
        disabled: bool = False,
        unreadable: bool = False,
    ) -> None:
        self.checked = checked
        self.click_toggles = click_toggles
        self.disabled = disabled
        self.unreadable = unreadable
        self.checked_reads = 0
        self.disabled_reads = 0
        self.click_calls = 0
        self.candidates = ("fake-toggle",)

    async def is_checked(self) -> bool:
        self.checked_reads += 1
        if self.unreadable:
            raise RuntimeError("locator detached while reading the state")
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
            if self.unreadable:
                return None
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
    location=None,
):
    return tk_main.TiktokSettingsControls(
        privacy=privacy,
        comments=comments,
        reuse=reuse,
        aigc=aigc,
        brand_switch=brand_switch,
        your_brand=your_brand,
        branded_content=branded_content,
        location=location,
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

    def _run_option_cli(self, page, controls, extra_args):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image = Path(tmp_dir) / "cover.png"
            image.write_bytes(b"x")
            session, session_cm, factory = _fake_session(_StudioContext(page))
            with (
                patch.object(
                    tk_main, "TIKTOK_HASHTAG_SUGGESTION_TIMEOUT_MS", 0
                ),
                patch.object(
                    tiktok_command,
                    "async_playwright",
                    lambda: _AsyncCM(object()),
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
                    new=AsyncMock(return_value=controls),
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
                        *extra_args,
                    ]
                )
        return code, out, err, page, session_cm

    def test_cli_no_aigc_missing_entry_reaches_no_publish_stop(self):
        page = _StudioPage()

        code, out, err, page, session_cm = self._run_option_cli(
            page,
            _note_controls(aigc=None),
            ["--no-aigc", "--no-publish"],
        )

        self.assertEqual(code, 0, err)
        self.assertIn("requested=false", out)
        self.assertIn("applied=null", out)
        self.assertIn("status=default_off", out)
        self.assertIn("reason=entry_missing", out)
        self.assertIn("continue=yes", out)
        self.assertIn("素材已上传，发布前检查已通过；已停止，未点击发布按钮。", out)
        self.assertFalse(page.publish_clicked)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_cli_no_aigc_disabled_and_still_on_exits_1_without_publish(self):
        page = _StudioPage()

        code, out, err, page, session_cm = self._run_option_cli(
            page,
            _note_controls(aigc=_FakeToggle(True, disabled=True)),
            ["--no-aigc", "--no-publish"],
        )

        self.assertEqual(code, 1)
        self.assertIn("applied=true", out)
        self.assertIn("status=mismatch", out)
        self.assertIn("continue=no", out)
        self.assertIn("aigc", err)
        self.assertIn("stage=disabled", err)
        self.assertFalse(page.publish_clicked)
        self.assertNotIn("素材已上传", out)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_cli_no_aigc_visible_but_unreadable_exits_1_without_publish(self):
        page = _StudioPage()

        code, out, err, page, session_cm = self._run_option_cli(
            page,
            _note_controls(aigc=_FakeToggle(False, unreadable=True)),
            ["--no-aigc", "--no-publish"],
        )

        self.assertEqual(code, 1)
        self.assertIn("applied=null", out)
        self.assertIn("status=mismatch", out)
        self.assertIn("reason=read_error", out)
        self.assertIn("continue=no", out)
        self.assertIn("aigc", err)
        self.assertIn("stage=read", err)
        self.assertFalse(page.publish_clicked)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_cli_no_aigc_on_to_off_reports_set_and_stops_before_publish(self):
        page = _StudioPage()
        aigc = _FakeToggle(True)

        code, out, err, page, session_cm = self._run_option_cli(
            page,
            _note_controls(aigc=aigc),
            ["--no-aigc", "--no-publish"],
        )

        self.assertEqual(code, 0, err)
        self.assertFalse(aigc.checked)
        self.assertEqual(aigc.click_calls, 1)
        self.assertIn("requested=false", out)
        self.assertIn("applied=false", out)
        self.assertIn("status=set", out)
        self.assertIn("continue=yes", out)
        self.assertIn("素材已上传，发布前检查已通过；已停止，未点击发布按钮。", out)
        self.assertFalse(page.publish_clicked)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_aigc_omitted_preserves_preset_and_reports_not_requested(self):
        aigc = _FakeToggle(True)
        note = self._note(TiktokPublishOptions(allow_comments=False))
        self._install(
            note,
            _note_controls(comments=_FakeToggle(True), aigc=aigc),
        )

        out = io.StringIO()
        with redirect_stdout(out):
            asyncio.run(note.apply_options(_StudioPage()))

        self.assertTrue(aigc.checked)
        self.assertEqual(aigc.checked_reads, 0)
        self.assertEqual(aigc.disabled_reads, 0)
        self.assertEqual(aigc.click_calls, 0)
        self.assertIsNone(note.ai_outcome.requested)
        self.assertEqual(note.ai_outcome.status, "not_requested")
        self.assertEqual(out.getvalue(), "")

    def test_no_aigc_missing_entry_continues_as_default_off(self):
        note = self._note(TiktokPublishOptions(aigc=False))
        self._install(note, _note_controls(aigc=None))

        out = io.StringIO()
        with redirect_stdout(out):
            asyncio.run(note.apply_options(_StudioPage()))

        self.assertEqual(note.ai_outcome.requested, False)
        self.assertIsNone(note.ai_outcome.applied)
        self.assertEqual(note.ai_outcome.status, "default_off")
        self.assertEqual(note.ai_outcome.reason, "entry_missing")
        line = out.getvalue()
        self.assertIn("requested=false", line)
        self.assertIn("applied=null", line)
        self.assertIn("status=default_off", line)
        self.assertIn("reason=entry_missing", line)
        self.assertIn("continue=yes", line)

    def test_no_aigc_already_off_reports_default_off_without_click(self):
        aigc = _FakeToggle(False)
        note = self._note(TiktokPublishOptions(aigc=False))
        self._install(note, _note_controls(aigc=aigc))

        out = io.StringIO()
        with redirect_stdout(out):
            asyncio.run(note.apply_options(_StudioPage()))

        self.assertFalse(aigc.checked)
        self.assertEqual(aigc.click_calls, 0)
        self.assertEqual(note.ai_outcome.applied, False)
        self.assertEqual(note.ai_outcome.status, "default_off")
        self.assertIsNone(note.ai_outcome.reason)
        line = out.getvalue()
        self.assertIn("applied=false", line)
        self.assertIn("status=default_off", line)
        self.assertIn("continue=yes", line)

    def test_no_aigc_on_to_off_reports_set(self):
        aigc = _FakeToggle(True)
        note = self._note(TiktokPublishOptions(aigc=False))
        self._install(note, _note_controls(aigc=aigc))

        out = io.StringIO()
        with redirect_stdout(out):
            asyncio.run(note.apply_options(_StudioPage()))

        self.assertFalse(aigc.checked)
        self.assertEqual(aigc.click_calls, 1)
        self.assertEqual(note.ai_outcome.applied, False)
        self.assertEqual(note.ai_outcome.status, "set")
        line = out.getvalue()
        self.assertIn("requested=false", line)
        self.assertIn("applied=false", line)
        self.assertIn("status=set", line)
        self.assertIn("continue=yes", line)

    def test_no_aigc_readback_still_on_fails_mismatch(self):
        aigc = _FakeToggle(True, click_toggles=False)
        note = self._note(TiktokPublishOptions(aigc=False))
        self._install(note, _note_controls(aigc=aigc))

        out = io.StringIO()
        with redirect_stdout(out):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(note.apply_options(_StudioPage()))

        self.assertIn("stage=readback", str(ctx.exception))
        self.assertEqual(aigc.click_calls, 1)
        self.assertEqual(note.ai_outcome.applied, True)
        self.assertEqual(note.ai_outcome.status, "mismatch")
        self.assertIn("continue=no", out.getvalue())

    def test_no_aigc_disabled_and_still_on_fails_mismatch(self):
        aigc = _FakeToggle(True, disabled=True)
        note = self._note(TiktokPublishOptions(aigc=False))
        self._install(note, _note_controls(aigc=aigc))

        out = io.StringIO()
        with redirect_stdout(out):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(note.apply_options(_StudioPage()))

        self.assertIn("stage=disabled", str(ctx.exception))
        self.assertEqual(aigc.click_calls, 0)
        self.assertEqual(note.ai_outcome.applied, True)
        self.assertEqual(note.ai_outcome.status, "mismatch")
        line = out.getvalue()
        self.assertIn("applied=true", line)
        self.assertIn("status=mismatch", line)
        self.assertIn("continue=no", line)

    def test_no_aigc_visible_but_unreadable_fails_mismatch(self):
        aigc = _FakeToggle(False, unreadable=True)
        note = self._note(TiktokPublishOptions(aigc=False))
        self._install(note, _note_controls(aigc=aigc))

        out = io.StringIO()
        with redirect_stdout(out):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(note.apply_options(_StudioPage()))

        self.assertIn("stage=read", str(ctx.exception))
        self.assertEqual(aigc.click_calls, 0)
        self.assertIsNone(note.ai_outcome.applied)
        self.assertEqual(note.ai_outcome.status, "mismatch")
        self.assertEqual(note.ai_outcome.reason, "read_error")
        line = out.getvalue()
        self.assertIn("applied=null", line)
        self.assertIn("status=mismatch", line)
        self.assertIn("reason=read_error", line)
        self.assertIn("continue=no", line)

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
        self.assertIn("requested=true", out)
        self.assertIn("applied=null", out)
        self.assertIn("status=unsupported", out)
        self.assertIn("reason=entry_missing", out)
        self.assertIn("continue=no", out)
        self.assertEqual(session_cm.exit_calls, 1)


class _FakeLocationCandidate:
    def __init__(self, name: str, address: str | None = None) -> None:
        self.name = name
        self.address = address
        self.click_calls = 0
        self.on_click = None

    async def click(self) -> None:
        self.click_calls += 1
        if self.on_click is not None:
            self.on_click(self)


class _FakeLocation:
    def __init__(
        self,
        rows=(),
        *,
        collapsed: bool = True,
        final_value: str | None = None,
    ) -> None:
        self.rows = []
        for item in rows:
            candidate = (
                item
                if isinstance(item, _FakeLocationCandidate)
                else _FakeLocationCandidate(*item)
            )
            candidate.on_click = self._select
            self.rows.append(candidate)
        self.collapsed = collapsed
        self.final_value = final_value
        self.candidates = ("fake-location",)
        self.search_calls = 0
        self.searches: list[str] = []
        self.selected: str | None = None
        self.collapse_reads = 0
        self.value_reads = 0

    def _select(self, candidate: _FakeLocationCandidate) -> None:
        self.selected = candidate.name

    async def search(self, text: str) -> None:
        self.search_calls += 1
        self.searches.append(text)

    async def candidate_rows(self):
        return list(self.rows)

    async def wait_collapsed(self) -> bool:
        self.collapse_reads += 1
        return self.collapsed

    async def read_value(self) -> str:
        self.value_reads += 1
        if self.final_value is not None:
            return self.final_value
        return self.selected or ""

    async def is_disabled(self) -> bool:
        return False

    async def is_visible(self) -> bool:
        return True

    async def count(self) -> int:
        return 1


class UploadNoteLocationTests(unittest.TestCase):
    def _run_cli(self, page, controls, location="London Eye", extra=()):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image = Path(tmp_dir) / "cover.png"
            image.write_bytes(b"x")
            session, session_cm, factory = _fake_session(_StudioContext(page))
            with (
                patch.object(
                    tiktok_command,
                    "async_playwright",
                    lambda: _AsyncCM(object()),
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
                    new=AsyncMock(return_value=controls),
                ),
            ):
                argv = [
                    "tiktok",
                    "upload-note",
                    "--folder-id",
                    "folder",
                    "--profile-id",
                    "profile",
                    "--images",
                    str(image),
                ]
                if location is not None:
                    argv += ["--location", location]
                argv += ["--no-publish", *extra]
                code, out, err = _run(argv)
        return code, out, err, page, session_cm

    def test_cli_success_reports_clicked_row_and_final_value(self):
        rows = [
            ("London Eye Afternoon Tea", "Riverside building, London"),
            ("London Eye", "Riverside Building, County Hall, London, UK"),
            ("London Eye", "Dolgoprudnyy, Moscow, Russia"),
        ]
        location = _FakeLocation(rows)
        page = _StudioPage()

        code, out, err, page, session_cm = self._run_cli(
            page,
            _note_controls(location=location),
            location="  london   EYE ",
        )

        self.assertEqual(code, 0, err)
        self.assertEqual(location.searches, ["london EYE"])
        self.assertEqual(location.rows[1].click_calls, 1)
        self.assertEqual(location.rows[0].click_calls, 0)
        self.assertEqual(location.rows[2].click_calls, 0)
        self.assertIn("requested='london EYE'", out)
        self.assertIn("candidate='London Eye'", out)
        self.assertIn(
            "address='Riverside Building, County Hall, London, UK'", out
        )
        self.assertIn("final='London Eye'", out)
        self.assertIn("status=set", out)
        self.assertIn("TikTok note upload: 1 images", out)
        self.assertIn("已停止，未点击发布按钮。", out)
        self.assertFalse(page.publish_clicked)
        self.assertEqual(session_cm.exit_calls, 1)

    def _assert_failure(self, controls, reason, *, page=None):
        page = page or _StudioPage()
        code, out, err, page, session_cm = self._run_cli(page, controls)
        self.assertEqual(code, 1)
        self.assertIn(f"reason={reason}", out)
        self.assertIn("continue=no", out)
        self.assertIn("option=location", err)
        self.assertNotIn("TikTok note upload:", out)
        self.assertFalse(page.publish_clicked)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_cli_approximate_only_exits_1_without_publish(self):
        self._assert_failure(
            _note_controls(
                location=_FakeLocation(
                    [
                        ("London Eye Afternoon Tea", "London, UK"),
                        ("London", "Greater London, United Kingdom"),
                    ]
                )
            ),
            "no_same_name_candidate",
        )

    def test_cli_name_only_row_succeeds_without_address(self):
        location = _FakeLocation([("人民公园", None)])
        page = _StudioPage()

        code, out, err, page, session_cm = self._run_cli(
            page,
            _note_controls(location=location),
            location="人民公园",
        )

        self.assertEqual(code, 0, err)
        self.assertEqual(location.rows[0].click_calls, 1)
        self.assertIn("candidate='人民公园'", out)
        self.assertIn("address=null", out)
        self.assertIn("final='人民公园'", out)
        self.assertIn("status=set", out)
        self.assertFalse(page.publish_clicked)
        self.assertEqual(session_cm.exit_calls, 1)

    def test_cli_empty_candidate_list_exits_1_without_publish(self):
        self._assert_failure(
            _note_controls(location=_FakeLocation([])),
            "no_same_name_candidate",
        )

    def test_cli_entry_missing_exits_1_without_publish(self):
        self._assert_failure(
            _note_controls(location=None), "entry_missing"
        )

    def test_cli_explicit_account_prompt_exits_1_without_publish(self):
        page = _StudioPage()
        page.location_notice = "Location isn't available for this account."
        self._assert_failure(
            _note_controls(location=None),
            "account_ineligible",
            page=page,
        )

    def test_cli_list_not_collapsed_exits_1_without_publish(self):
        self._assert_failure(
            _note_controls(
                location=_FakeLocation(
                    [("London Eye", "London, UK")], collapsed=False
                )
            ),
            "list_not_collapsed",
        )

    def test_cli_empty_final_value_exits_1_without_publish(self):
        self._assert_failure(
            _note_controls(
                location=_FakeLocation(
                    [("London Eye", "London, UK")], final_value=""
                )
            ),
            "final_empty",
        )

    def test_cli_wrong_final_value_exits_1_without_publish(self):
        self._assert_failure(
            _note_controls(
                location=_FakeLocation(
                    [("London Eye", "London, UK")], final_value="London"
                )
            ),
            "final_mismatch",
        )

    def test_cli_omitted_location_makes_zero_location_calls(self):
        location = _FakeLocation(
            [("London Eye", "London, UK")], final_value="London Eye"
        )
        page = _StudioPage()

        code, out, err, page, session_cm = self._run_cli(
            page,
            _note_controls(comments=_FakeToggle(True), location=location),
            location=None,
            extra=("--no-comments",),
        )

        self.assertEqual(code, 0, err)
        self.assertEqual(location.search_calls, 0)
        self.assertEqual(location.collapse_reads, 0)
        self.assertEqual(location.value_reads, 0)
        for candidate in location.rows:
            self.assertEqual(candidate.click_calls, 0)
        self.assertNotIn("TikTok 帖子地点", out)
        self.assertIn("TikTok note upload: 1 images", out)
        self.assertFalse(page.publish_clicked)

    def test_photos_tab_gap_keeps_its_own_diagnostic_with_location(self):
        page = _StudioPage(photo_mode=False, photos_tab=False)

        code, out, err, page, session_cm = self._run_cli(
            page, _note_controls(location=_FakeLocation([]))
        )

        self.assertEqual(code, 1)
        self.assertIn("Photos", err)
        self.assertIn("未覆盖", err)
        self.assertNotIn("TikTok 帖子地点", out)
        self.assertNotIn("account_ineligible", out)
        self.assertNotIn("entry_missing", out)
        self.assertFalse(page.publish_clicked)
        self.assertEqual(session_cm.exit_calls, 1)


class PhotoTitleStructuralErrorTests(unittest.TestCase):
    """Only a real ``ElementUnusableError(reason="ambiguous:N")`` is structural."""

    def _note(self, error) -> TiktokNote:
        note = TiktokNote(
            ["/tmp/cover.png"], "", [], 0, None, title="标题"
        )
        note.locator_base = _TitleScope(error)
        return note

    def test_ambiguous_reason_raises_before_the_retry_loop(self):
        error = ElementUnusableError(
            what="Title", role="interactive", reason="ambiguous:2"
        )
        note = self._note(error)
        page = SimpleNamespace(wait_for_timeout=AsyncMock())

        with patch.object(note, "dismiss_blocking_overlays", AsyncMock()):
            with self.assertRaises(ElementUnusableError) as ctx:
                asyncio.run(note._fill_title(page))

        self.assertEqual(ctx.exception.reason, "ambiguous:2")
        page.wait_for_timeout.assert_not_awaited()

    def test_a_message_that_merely_mentions_ambiguous_is_retried(self):
        note = self._note(RuntimeError("selector note: ambiguous: not a reason"))
        page = SimpleNamespace(wait_for_timeout=AsyncMock())

        with patch.object(note, "dismiss_blocking_overlays", AsyncMock()):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(note._fill_title(page))

        self.assertIn("未找到", str(ctx.exception))
        self.assertEqual(page.wait_for_timeout.await_count, 20)


class _TitleScope:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def locator(self, _selector: str) -> "_TitleField":
        return _TitleField(self.error)


class _TitleField:
    """The title input; the humanized hover is where the structural error hits."""

    def __init__(self, error: BaseException) -> None:
        self.error = error

    @property
    def first(self) -> "_TitleField":
        return self

    async def count(self) -> int:
        return 1

    async def hover(self) -> None:
        raise self.error

    async def click(self) -> None:  # pragma: no cover - hover fails first
        raise AssertionError("click must not run after a failing hover")


def setUpModule():
    """Legacy TikTok fakes model the pre-humanize DOM seam.

    ``HUMANIZE=0`` is the semantic switch for exactly this: one ``insert_text``
    per text field and one ``locator.click`` per click.  The humanized
    behaviour itself is covered by ``tests/test_tiktok_humanize.py``.
    """
    import os

    global _HUMANIZE_BEFORE
    _HUMANIZE_BEFORE = os.environ.get("HUMANIZE")
    os.environ["HUMANIZE"] = "0"


def tearDownModule():
    import os

    if _HUMANIZE_BEFORE is None:
        os.environ.pop("HUMANIZE", None)
    else:
        os.environ["HUMANIZE"] = _HUMANIZE_BEFORE


if __name__ == "__main__":
    unittest.main()
