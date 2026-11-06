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
from unittest.mock import AsyncMock, MagicMock, patch

import sau_cli
from sau_commands import tiktok as tiktok_command
from sau_commands.arguments import existing_file_path
from uploader.tk_uploader import main_chrome as tk_main
from uploader.tk_uploader.main_chrome import TiktokBaseUploader, TiktokNote
from uploader.tk_uploader.tk_config import (
    TIKTOK_IMAGE_SUFFIXES,
    TIKTOK_MAX_IMAGE_BYTES,
    TIKTOK_MAX_IMAGE_COUNT,
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
    session = SimpleNamespace(context=context, mode="multilogin")
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

    async def get_attribute(self, name: str):
        if "text=Post" in self.selector:
            return None if self.page.post_enabled else "disabled"
        if 'item_id=' in self.selector:
            return self.page.item_href
        return None

    async def wait_for(self, **kwargs) -> None:
        return None

    async def set_input_files(self, files) -> None:
        self.page.events.append(("set_input_files", tuple(files)))
        self.page.input_files = list(files)


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


class _StudioPage:
    def __init__(self, *, photo_mode: bool = True, photos_tab: bool = True) -> None:
        self.url = "about:blank"
        self.photo_mode = photo_mode
        self.photos_tab = photos_tab
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

    async def goto(self, url: str, **kwargs):
        self.goto_calls.append((url, kwargs))
        self.url = url
        return SimpleNamespace(status=200)

    async def wait_for_url(self, url: str, **kwargs):
        self.wait_for_url_calls.append((url, kwargs))
        if "tiktokstudio/content" in url:
            self.url = url

    async def wait_for_selector(self, selector: str, **kwargs):
        return object()

    def get_by_text(self, text: str, exact: bool = False):
        if text == "Photos":
            return _TextTab(self)
        return _Locator(self, f"text={text}", count=0)

    def get_by_role(self, role: str, name: str | None = None):
        if role == "tab" and name == "Photos":
            return _TextTab(self)
        return _Locator(self, f"role={role}", count=0)

    def locator(self, selector: str) -> _Locator:
        if selector in (
            'input[placeholder*="catchy"]',
            'input[type="file"][accept*="image"]',
        ):
            return _Locator(self, selector, count=1 if self.photo_mode else 0)
        if selector == 'input[type="file"][multiple]':
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

    def test_metadata_and_cover_options_are_absent(self):
        options = _option_strings(
            _subparser(sau_cli.build_parser(), "tiktok", "upload-note")
        )
        for forbidden in (
            "--title",
            "--note",
            "--notef",
            "--tags",
            "--disable-reuse",
            "--thumbnail",
            "--cover-index",
            "--bgm",
            "--privacy",
            "--no-comments",
            "--aigc",
            "--no-aigc",
            "--your-brand",
            "--branded-content",
        ):
            with self.subTest(option=forbidden):
                self.assertNotIn(forbidden, options)

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
        with (
            patch.object(tiktok_command, "async_playwright", playwright),
            patch.object(tiktok_command, "browser_session", session),
        ):
            code, out, err = _run(argv)
        self.assertEqual(code, 2)
        self.assertNotIn("submitted", out)
        self.assertTrue(err.strip())
        playwright.assert_not_called()
        session.assert_not_called()

    def _argv(self, images: list[str]) -> list[str]:
        return [
            "tiktok",
            "upload-note",
            "--images",
            *images,
        ]

    def test_zero_images_exits_2_without_browser(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = self._images(tmp_dir, 1)
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

    def test_local_mode_exits_1_without_reaching_the_builder(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = self._images(tmp_dir)
            playwright = MagicMock()
            session = MagicMock()
            builder = MagicMock()
            with (
                patch.object(tiktok_command, "async_playwright", playwright),
                patch.object(tiktok_command, "browser_session", session),
                patch.object(
                    tiktok_command, "_build_note_uploader", new=builder
                ),
            ):
                code, out, err = _run(
                    [
                        "tiktok",
                        "upload-note",
                        "--images",
                        *images,
                    ],
                    token="",
                )

        self.assertEqual(code, 1)
        self.assertIn("TikTok 仅支持 Multilogin 模式", err)
        self.assertNotIn("submitted", out)
        playwright.assert_not_called()
        session.assert_not_called()
        builder.assert_not_called()

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
        self.assertIn(f"TikTok note upload submitted: 3 images", out)
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
        with self.assertRaises(RuntimeError):
            asyncio.run(note.read_result(page))

    def test_photo_upload_rejects_local_mode(self):
        note = self._note(["/tmp/cover.png"])
        with self.assertRaises(RuntimeError):
            asyncio.run(note.upload(None))


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class UploadNoteConstantsTests(unittest.TestCase):
    def test_web_ui_limits(self):
        self.assertEqual(TIKTOK_MAX_IMAGE_COUNT, 35)
        self.assertEqual(TIKTOK_MAX_IMAGE_BYTES, 50 * 1024 * 1024)
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
        self.assertEqual(
            tk_main.TIKTOK_IMAGE_SUFFIXES,
            {".jpg", ".jpeg", ".png", ".webp"},
        )


if __name__ == "__main__":
    unittest.main()
