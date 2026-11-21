# -*- coding: utf-8 -*-
"""TikTok inline caption topics (ticket 25).

Controlled editor doubles only: no browser, no network.  The fake models the
measured Draft.js behaviour:

* the editor text is the rendered document text;
* selecting a same-name suggestion replaces the typed ``#name`` with a
  ``span.mention[data-testid="mentionText"]`` and appends one U+0020;
* the suggestion list is scoped to the currently typed ``#name``;
* a row may deliberately misbehave to prove the readback gate (wrong mention,
  swallowed text, extra append, hard limit).

Web evidence reused from
``.scratch/publish-metadata-support/research/inline-topics-2026-11-20/tiktok-video.json``,
``tiktok-photos.json`` and
``.scratch/publish-metadata-support/research/created-topic-2026-11-20/tiktok-*.json``.
No live CLI account run was made; the CLI sample remains 未实测.
"""

from __future__ import annotations

import asyncio
import io
import os
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import sau_cli
from sau_commands import tiktok as tiktok_command
from uploader.tk_uploader import main_chrome as tk_main
from uploader.tk_uploader.main_chrome import TiktokNote, TiktokVideo

MENTION_SELECTOR = 'span.mention[data-testid="mentionText"]'
_TOPIC_RE = re.compile(r"#([^\s#，。！？、,.!?;:()\[\]{}]+)$")


class _Empty:
    def filter(self, has_text=None):
        return self

    async def all_inner_texts(self):
        return []

    async def count(self):
        return 0

    async def inner_text(self):
        return ""

    @property
    def first(self):
        return self


class _Body:
    def __init__(self, env):
        self.env = env

    async def count(self):
        return 1

    async def inner_text(self):
        return self.env.body_text

    async def all_inner_texts(self):
        return [self.env.body_text] if self.env.body_text else []


class _MentionNode:
    def __init__(self, text):
        self.text = text

    async def inner_text(self):
        return self.text


class _Mentions:
    def __init__(self, env):
        self.env = env

    async def count(self):
        return len(self.env.mentions)

    def nth(self, index):
        return _MentionNode(self.env.mentions[index])


class _Row:
    """One ``[role=option]`` row.

    ``wrong_mention`` models a platform selecting a different topic;
    ``swallow`` removes that many characters before the mention; ``extra``
    appends text after the platform space; ``transform`` mutates the whole
    buffer to model misplacement.
    """

    def __init__(
        self,
        env,
        name,
        *,
        second_line="Add",
        selected=False,
        wrong_mention=None,
        swallow=0,
        extra="",
        transform=None,
        click_error=None,
    ):
        self.env = env
        self.name = name
        self.second_line = second_line
        self.selected = selected
        self.wrong_mention = wrong_mention
        self.swallow = swallow
        self.extra = extra
        self.transform = transform
        self.click_error = click_error
        self.click_calls = 0
        self.dispose_calls = 0

    async def inner_text(self):
        return f"{self.name}\n{self.second_line}"

    async def get_attribute(self, name):
        if name == "aria-selected" and self.selected:
            return "true"
        return None

    async def hover(self):
        return None

    async def click(self, **kwargs):
        self.click_calls += 1
        if self.click_error is not None:
            raise self.click_error
        self.env.select(self)

    async def dispose(self):
        self.dispose_calls += 1


class _Options:
    def __init__(self, env):
        self.env = env
        self.rows = env.rows_for_token()

    async def count(self):
        return len(self.rows)

    async def element_handles(self):
        return list(self.rows)


class _Editor:
    def __init__(self, env):
        self.env = env

    async def count(self):
        return 1

    @property
    def first(self):
        return self

    def locator(self, selector):
        if selector == MENTION_SELECTOR:
            return _Mentions(self.env)
        return _Empty()

    async def inner_text(self):
        return self.env.buffer

    async def hover(self):
        return None

    async def click(self, **kwargs):
        self.env.keyboard.target = "caption"

    async def wait_for(self, **kwargs):
        return None


class _Title:
    def __init__(self, env):
        self.env = env

    async def count(self):
        return 1

    @property
    def first(self):
        return self

    async def hover(self):
        return None

    async def click(self, **kwargs):
        self.env.keyboard.target = "title"

    async def wait_for(self, **kwargs):
        return None


class _Base:
    def __init__(self, env):
        self.env = env

    def locator(self, selector):
        if selector == '[role="option"]':
            return _Options(self.env)
        if selector.endswith("div.public-DraftEditor-content"):
            return self.env.editor
        if "catchy" in selector:
            return self.env.title if self.env.photo_mode else _Empty()
        return _Empty()


class _Page:
    url = "https://www.tiktok.com/tiktokstudio/upload"

    def __init__(self, env):
        self.env = env
        self.keyboard = env.keyboard

    def locator(self, selector):
        if selector == "body":
            return self.env.editor
        if '[role="alert"]' in selector:
            return _Body(self.env)
        if selector == '[role="option"]':
            return _Options(self.env)
        if selector in ('[role="dialog"]', "#react-joyride-portal"):
            return _Empty()
        return _Empty()

    async def wait_for_timeout(self, milliseconds):
        self.env.waits.append(milliseconds)

    def get_by_text(self, text, exact=False):
        return _Empty()

    def get_by_role(self, role, name=None):
        return _Empty()


class _Keyboard:
    def __init__(self, env):
        self.env = env
        self.target = "caption"
        self.selected = False

    def _buffer(self):
        return self.env.buffer if self.target == "caption" else self.env.title_text

    def _set_buffer(self, value):
        if self.target == "caption":
            self.env.buffer = value
        else:
            self.env.title_text = value

    def _refresh_token(self):
        if self.target != "caption":
            self.env.open_token = None
            return
        match = _TOPIC_RE.search(self.env.buffer)
        self.env.open_token = match.group(1) if match else None

    async def insert_text(self, text):
        self.env.inserts.append((self.target, text))
        self._set_buffer(self._buffer() + text)
        self._refresh_token()

    async def press(self, key):
        self.env.presses.append(key)
        if key == "ControlOrMeta+A":
            self.selected = True
            return
        if key == "Delete":
            if self.selected:
                self._set_buffer("")
                if self.target == "caption":
                    self.env.mentions.clear()
                self.selected = False
            return
        if key == "Backspace":
            self.env.backspace_calls += 1
            self._set_buffer(self._buffer()[:-1])
            self._refresh_token()
            return
        if key == "Enter":
            self._set_buffer(self._buffer() + "\n")
            self.env.open_token = None
            return
        if key == "Escape":
            self.env.escape_calls += 1
            self.env.open_token = None
            return
        if key == "End":
            return
        if key == "Space":
            self._set_buffer(self._buffer() + " ")
            self.env.open_token = None
            return
        if len(key) == 1:
            self._set_buffer(self._buffer() + key)
            self._refresh_token()
            return

    async def type(self, text, delay=None, **kwargs):
        await self.insert_text(text)


class TopicEnv:
    """Controlled TikTok caption editor and suggestion list."""

    def __init__(self, *, photo_mode=False):
        self.suggestions = {}
        self.photo_mode = photo_mode
        self.buffer = ""
        self.title_text = ""
        self.mentions: list[str] = []
        self.open_token = None
        self.body_text = ""
        self.waits: list[int] = []
        self.presses: list[str] = []
        self.inserts: list[tuple[str, str]] = []
        self.backspace_calls = 0
        self.escape_calls = 0
        self.rows: list[_Row] = []
        self.keyboard = _Keyboard(self)
        self.editor = _Editor(self)
        self.title = _Title(self)
        self.base = _Base(self)
        self.page = _Page(self)

    def add_suggestion(self, token, name=None, **kwargs):
        row = _Row(self, name or f"#{token}", **kwargs)
        self.suggestions.setdefault(token, []).append(row)
        self.rows.append(row)
        return row

    def rows_for_token(self):
        if not self.open_token:
            return []
        return list(self.suggestions.get(self.open_token, ()))

    def select(self, row):
        # The typed ``#name`` is already the tail of the buffer.
        index = self.buffer.rfind("#")
        if index >= 0:
            self.buffer = self.buffer[:index]
        if row.swallow:
            self.buffer = self.buffer[: -row.swallow]
        mention = row.wrong_mention or row.name
        self.buffer += mention
        self.mentions.append(mention)
        self.buffer += " "
        self.buffer += row.extra
        if row.transform is not None:
            row.transform(self)
        self.open_token = None


def _video(env, title):
    uploader = TiktokVideo(title, "/tmp/demo.mp4", [], 0, None)
    uploader.locator_base = env.base
    return uploader


def _note(env, note, *, title=None, tags=()):
    uploader = TiktokNote(
        ["/tmp/cover.png"], note, list(tags), 0, None, title=title
    )
    uploader.locator_base = env.base
    return uploader


def _fill_video(env, title):
    uploader = _video(env, title)
    out = io.StringIO()
    with patch.dict(os.environ, {"HUMANIZE": "0"}), redirect_stdout(out):
        asyncio.run(
            uploader.fill_caption(env.page, title, [], editor=env.editor)
        )
    return uploader, out.getvalue()


class _AsyncCM:
    def __init__(self, value=None):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _run_cli(argv):
    with tempfile.TemporaryDirectory() as home, patch.dict(
        os.environ, {"MLX_API_TOKEN": "token", "HOME": home}
    ):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out):
            from contextlib import redirect_stderr

            with redirect_stderr(err):
                code = sau_cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class TiktokInlineTopicTests(unittest.TestCase):
    def test_video_links_same_name_row_and_add_row_in_place(self):
        env = TopicEnv()
        coffee = env.add_suggestion("coffee", second_line="24.5M posts")
        tea = env.add_suggestion("tea", second_line="Add")
        title = "Today #coffee, then #tea!"

        uploader, out = _fill_video(env, title)

        self.assertEqual(env.buffer, title)
        self.assertEqual(env.mentions, ["#coffee", "#tea"])
        self.assertEqual(coffee.click_calls, 1)
        self.assertEqual(tea.click_calls, 1)
        self.assertEqual(env.backspace_calls, 2)
        self.assertIn(
            "TikTok 配文话题: index=1 text='#coffee' status=linked "
            "reason=- continue=yes",
            out,
        )
        self.assertIn(
            "TikTok 配文话题: index=2 text='#tea' status=linked "
            "reason=- continue=yes",
            out,
        )
        self.assertIn("result=已关联", out)
        self.assertEqual(
            [outcome.occurrence.index for outcome in uploader.topic_outcomes],
            [1, 2],
        )

    def test_photos_body_links_add_row_and_title_keeps_its_own_topic(self):
        env = TopicEnv(photo_mode=True)
        coffee = env.add_suggestion("coffee", second_line="24.5M posts")
        fieldstudy = env.add_suggestion("fieldstudy", second_line="Add")
        title = "My #titleTopic title"
        note = "Field notes #coffee, then #fieldstudy, after rain."

        uploader = _note(env, note, title=title)
        out = io.StringIO()
        with patch.dict(os.environ, {"HUMANIZE": "0"}), redirect_stdout(out):
            asyncio.run(uploader.fill_metadata(env.page))

        self.assertEqual(env.title_text, title)
        self.assertEqual(env.buffer, note)
        self.assertEqual(env.mentions, ["#coffee", "#fieldstudy"])
        self.assertEqual(coffee.click_calls, 1)
        self.assertEqual(fieldstudy.click_calls, 1)
        lines = [line for line in out.getvalue().splitlines() if line]
        self.assertEqual(len(lines), 2)
        self.assertIn("text='#coffee'", lines[0])
        self.assertIn("status=linked", lines[0])
        self.assertIn("text='#fieldstudy'", lines[1])
        self.assertIn("status=linked", lines[1])
        self.assertNotIn("#titleTopic", out.getvalue())

    def test_duplicates_url_fragment_punctuation_newlines_and_mixed_text(self):
        env = TopicEnv()
        env.add_suggestion("咖啡", second_line="1.2M posts")
        env.add_suggestion("coffee", second_line="24.5M posts")
        env.add_suggestion("Tea", second_line="Add")
        caption = (
            "今天 #咖啡，喝 #coffee https://x.com/a#frag #咖啡\n"
            "第二行 #Tea!下午"
        )

        uploader, out = _fill_video(env, caption)

        self.assertEqual(env.buffer, caption)
        self.assertEqual(
            env.mentions, ["#咖啡", "#coffee", "#咖啡", "#Tea"]
        )
        # The URL fragment is text, not an occurrence.
        self.assertNotIn("#frag", out)
        lines = [line for line in out.splitlines() if line]
        self.assertEqual(len(lines), 4)
        self.assertIn("index=3 text='#咖啡'", lines[2])
        # Author spaces are consumed from the platform auto-space; punctuation
        # and the newline are preserved by removing the extra U+0020.
        self.assertEqual(env.buffer, caption)
        self.assertEqual(env.backspace_calls, 3)

    def test_approximate_only_keeps_text_and_reports_no_same_name(self):
        env = TopicEnv()
        env.add_suggestion(
            "coffee", name="#coffeecreamer", second_line="49.5K posts"
        )
        caption = "Today #coffee, then #qzx."

        with patch.object(
            tk_main, "TIKTOK_HASHTAG_SUGGESTION_TIMEOUT_MS", 0
        ), patch.object(tk_main, "TIKTOK_HASHTAG_SETTLE_MS", 0):
            uploader, out = _fill_video(env, caption)

        self.assertEqual(env.buffer, caption)
        self.assertEqual(env.mentions, [])
        lines = [line for line in out.splitlines() if line]
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertIn("status=text", line)
            self.assertIn("reason=no_same_name_candidate", line)
            self.assertIn("continue=yes", line)
            self.assertIn("result=保留文字，无同名候选", line)
        self.assertEqual(
            [outcome.status for outcome in uploader.topic_outcomes],
            ["text", "text"],
        )

    def test_fifty_first_topic_stays_text_and_is_reported(self):
        env = TopicEnv()
        rows = [env.add_suggestion(f"t{index}") for index in range(1, 52)]
        caption = " ".join(f"#t{index}" for index in range(1, 52))

        uploader, out = _fill_video(env, caption)

        self.assertEqual(env.buffer, caption)
        self.assertEqual(env.mentions, [f"#t{index}" for index in range(1, 51)])
        self.assertEqual(rows[50].click_calls, 0)
        lines = [line for line in out.splitlines() if line]
        self.assertEqual(len(lines), 51)
        self.assertIn("index=50 text='#t50' status=linked", lines[49])
        self.assertIn("index=51 text='#t51' status=text", lines[50])
        self.assertIn("reason=association_limit", lines[50])
        self.assertIn("continue=yes", lines[50])
        self.assertIn("result=保留文字，已达可关联上限", lines[50])
        self.assertEqual(len(uploader.topic_outcomes), 51)

    def test_wrong_topic_selection_fails_with_readback_evidence(self):
        env = TopicEnv()
        env.add_suggestion("coffee", wrong_mention="#coffeecreamer")
        caption = "Today #coffee,"

        out = io.StringIO()
        with patch.dict(os.environ, {"HUMANIZE": "0"}), redirect_stdout(out):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(
                    _video(env, caption).fill_caption(
                        env.page, caption, [], editor=env.editor
                    )
                )

        self.assertIn("stage=mention-readback", str(ctx.exception))
        self.assertIn("status=mismatch", out.getvalue())
        self.assertIn("reason=wrong_topic", out.getvalue())
        self.assertIn("continue=no", out.getvalue())
        self.assertIn("#coffeecreamer", str(ctx.exception))

    def test_swallowed_text_fails_before_any_publish(self):
        env = TopicEnv()
        env.add_suggestion("coffee", swallow=2)
        caption = "Today #coffee,"
        out = io.StringIO()

        with patch.dict(os.environ, {"HUMANIZE": "0"}), redirect_stdout(out):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(
                    _video(env, caption).fill_caption(
                        env.page, caption, [], editor=env.editor
                    )
                )

        self.assertIn("stage=caption-readback", str(ctx.exception))
        self.assertIn("status=mismatch", out.getvalue())
        self.assertIn("reason=caption_mismatch", out.getvalue())

    def test_misplacement_fails_before_any_publish(self):
        env = TopicEnv()

        def move(_env):
            _env.buffer = _env.buffer.replace("Today ", "", 1) + "Today "

        env.add_suggestion("coffee", transform=move)
        caption = "Today #coffee,"
        out = io.StringIO()

        with patch.dict(os.environ, {"HUMANIZE": "0"}), redirect_stdout(out):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(
                    _video(env, caption).fill_caption(
                        env.page, caption, [], editor=env.editor
                    )
                )

        self.assertIn("stage=caption-readback", str(ctx.exception))
        self.assertIn("status=mismatch", out.getvalue())

    def test_extra_append_fails_before_any_publish(self):
        env = TopicEnv()
        env.add_suggestion("coffee", extra=" #extra")
        caption = "Today #coffee,"
        out = io.StringIO()

        with patch.dict(os.environ, {"HUMANIZE": "0"}), redirect_stdout(out):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(
                    _video(env, caption).fill_caption(
                        env.page, caption, [], editor=env.editor
                    )
                )

        self.assertIn("stage=caption-readback", str(ctx.exception))
        self.assertIn("status=mismatch", out.getvalue())

    def test_author_limit_words_are_not_platform_errors(self):
        env = TopicEnv()
        caption = "Too many hashtags " + " ".join(f"#t{i}" for i in range(50))
        for i in range(50):
            env.add_suggestion(f"t{i}")
        _fill_video(env, caption)
        self.assertEqual(env.buffer, caption)

    def test_final_text_only_topic_can_trigger_the_post_limit(self):
        env = TopicEnv()
        for i in range(50):
            env.add_suggestion(f"t{i}")
        caption = " ".join(f"#t{i}" for i in range(51))
        original = env.keyboard.insert_text
        async def insert(text):
            await original(text)
            if env.buffer == caption:
                env.body_text = "Too many hashtags"
        env.keyboard.insert_text = insert
        with self.assertRaisesRegex(RuntimeError, "硬限制"):
            _fill_video(env, caption)

    def test_python_photo_tags_are_appended_even_without_a_note(self):
        env = TopicEnv(photo_mode=True)
        env.add_suggestion("coffee")
        app = _note(env, "", tags=["coffee"])
        with patch.dict(os.environ, {"HUMANIZE": "0"}):
            asyncio.run(app.fill_metadata(env.page))
        self.assertEqual(env.buffer, "#coffee")
        self.assertEqual(env.mentions, ["#coffee"])

    def test_hard_limit_stops_without_publishing(self):
        env = TopicEnv(photo_mode=True)
        rows = [env.add_suggestion(f"t{index}") for index in range(1, 52)]

        def show_limit(_env):
            _env.body_text = (
                "You've reached the maximum number of hashtags for this post."
            )

        rows[49].transform = show_limit
        caption = " ".join(f"#t{index}" for index in range(1, 52))
        uploader = _note(env, caption)
        uploader.no_publish = True
        uploader.click_publish = AsyncMock()
        for name in (
            "open_upload_page",
            "attach_media",
            "wait_media_ready",
            "apply_options",
            "apply_cover",
            "apply_schedule",
            "wait_publish_ready",
        ):
            setattr(uploader, name, AsyncMock())

        out = io.StringIO()
        with (
            patch.dict(os.environ, {"HUMANIZE": "0"}),
            redirect_stdout(out),
            patch.object(tk_main.tiktok_logger, "success") as success,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(
                    uploader._upload_on_page(
                        env.page, managed=False, budget=None
                    )
                )

        self.assertIn("硬限制", str(ctx.exception))
        self.assertIn("reason=hard_limit", out.getvalue())
        self.assertIn("continue=no", out.getvalue())
        self.assertIn("result=保留文字，整帖硬限制", out.getvalue())
        success.assert_not_called()
        uploader.click_publish.assert_not_awaited()

    def test_caption_damage_never_reaches_the_publish_step(self):
        cases = {
            "swallowed": {"swallow": 2},
            "extra": {"extra": " #extra"},
            "misplaced": {
                "transform": lambda env: setattr(
                    env, "buffer", env.buffer.replace("Today ", "", 1) + "Today "
                )
            },
            "wrong-topic": {"wrong_mention": "#coffeecreamer"},
        }
        for label, kwargs in cases.items():
            with self.subTest(case=label):
                env = TopicEnv()
                env.add_suggestion("coffee", **kwargs)
                caption = "Today #coffee,"
                app = _video(env, caption)
                app.click_publish = AsyncMock()
                for name in (
                    "open_upload_page",
                    "attach_media",
                    "wait_media_ready",
                    "apply_options",
                    "apply_cover",
                    "apply_schedule",
                ):
                    setattr(app, name, AsyncMock())

                with patch.dict(os.environ, {"HUMANIZE": "0"}), redirect_stdout(
                    io.StringIO()
                ):
                    with self.assertRaises(RuntimeError):
                        asyncio.run(
                            app._upload_on_page(
                                env.page, managed=False, budget=None
                            )
                        )

                app.click_publish.assert_not_awaited()

    def test_no_publish_stops_after_topic_readback(self):
        env = TopicEnv()
        env.add_suggestion("coffee")
        caption = "Today #coffee, then rain."
        uploader = _video(env, caption)
        uploader.no_publish = True
        uploader.click_publish = AsyncMock()
        for name in (
            "open_upload_page",
            "attach_media",
            "wait_media_ready",
            "apply_options",
            "apply_cover",
            "apply_schedule",
            "wait_publish_ready",
        ):
            setattr(uploader, name, AsyncMock())

        out = io.StringIO()
        with (
            patch.dict(os.environ, {"HUMANIZE": "0"}),
            redirect_stdout(out),
            patch.object(tk_main.tiktok_logger, "success") as success,
        ):
            asyncio.run(
                uploader._upload_on_page(env.page, managed=False, budget=None)
            )

        self.assertEqual(env.buffer, caption)
        self.assertIn("status=linked", out.getvalue())
        success.assert_called_once_with(tk_main.TIKTOK_DRY_RUN_READY_MESSAGE)
        uploader.click_publish.assert_not_awaited()

    def test_photos_no_publish_stops_after_topic_readback(self):
        env = TopicEnv(photo_mode=True)
        env.add_suggestion("coffee")
        note = "Field notes #coffee, after rain."
        title = "My #titleTopic title"
        uploader = _note(env, note, title=title)
        uploader.no_publish = True
        uploader.click_publish = AsyncMock()
        for name in (
            "open_upload_page",
            "attach_media",
            "wait_media_ready",
            "apply_options",
            "apply_cover",
            "apply_schedule",
            "wait_publish_ready",
        ):
            setattr(uploader, name, AsyncMock())

        out = io.StringIO()
        with (
            patch.dict(os.environ, {"HUMANIZE": "0"}),
            redirect_stdout(out),
            patch.object(tk_main.tiktok_logger, "success") as success,
        ):
            asyncio.run(
                uploader._upload_on_page(env.page, managed=False, budget=None)
            )

        self.assertEqual(env.title_text, title)
        self.assertEqual(env.buffer, note)
        self.assertEqual(env.mentions, ["#coffee"])
        self.assertIn("status=linked", out.getvalue())
        self.assertNotIn("#titleTopic", out.getvalue())
        success.assert_called_once_with(tk_main.TIKTOK_DRY_RUN_READY_MESSAGE)
        uploader.click_publish.assert_not_awaited()

    def test_empty_video_caption_clears_without_a_topic_readback(self):
        env = TopicEnv()

        uploader, out = _fill_video(env, "")

        self.assertEqual(env.buffer, "")
        self.assertEqual(out, "")
        self.assertEqual(uploader.topic_outcomes, [])

    def test_local_cli_prints_per_word_topic_lines_before_the_summary(self):
        env = TopicEnv()
        env.add_suggestion("coffee")
        caption = "Today #coffee,"
        app = _video(env, caption)
        app.no_publish = True
        app.click_publish = AsyncMock()
        for name in (
            "open_upload_page",
            "attach_media",
            "wait_media_ready",
            "apply_options",
            "apply_cover",
            "apply_schedule",
            "wait_publish_ready",
        ):
            setattr(app, name, AsyncMock())

        async def upload(_playwright=None, session=None):
            await app._upload_on_page(env.page, managed=False, budget=None)

        app.upload = upload
        builder = MagicMock(return_value=app)
        session_cm = _AsyncCM(SimpleNamespace(context=object()))

        with tempfile.TemporaryDirectory() as tmp_dir:
            video = Path(tmp_dir) / "demo.mp4"
            video.write_bytes(b"video")
            with (
                patch.dict(
                    os.environ,
                    {
                        "HOME": tmp_dir,
                        "HUMANIZE": "0",
                        "MLX_API_TOKEN": "",
                        "ADSPOWER_API_KEY": "",
                    },
                ),
                patch.object(
                    tiktok_command,
                    "async_playwright",
                    lambda: _AsyncCM(object()),
                ),
                patch.object(
                    tiktok_command,
                    "local_browser_session",
                    new=MagicMock(return_value=session_cm),
                ),
                patch.object(
                    tiktok_command,
                    "is_logged_in",
                    new=AsyncMock(return_value=True),
                ),
                patch.object(
                    tiktok_command, "_build_video_uploader", new=builder
                ),
            ):
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out):
                    from contextlib import redirect_stderr

                    with redirect_stderr(err):
                        code = sau_cli.main(
                            [
                                "tiktok",
                                "upload-video",
                                "--account",
                                "creator",
                                "--file",
                                str(video),
                                "--title",
                                caption,
                                "--no-publish",
                            ]
                        )
                out = out.getvalue()
                err = err.getvalue()

        self.assertEqual(code, 0, err)
        self.assertIn(
            "TikTok 配文话题: index=1 text='#coffee' status=linked "
            "reason=- continue=yes",
            out,
        )
        self.assertIn(
            "素材已上传，发布前检查已通过；已停止，未点击发布按钮。", out
        )
        app.click_publish.assert_not_awaited()

    def test_cli_topic_mismatch_exits_1_with_zero_publish_clicks(self):
        env = TopicEnv()
        env.add_suggestion("coffee", wrong_mention="#coffeecreamer")
        caption = "Today #coffee,"
        app = _video(env, caption)
        app.no_publish = True
        app.click_publish = AsyncMock()
        for name in (
            "open_upload_page",
            "attach_media",
            "wait_media_ready",
            "apply_options",
            "apply_cover",
            "apply_schedule",
            "wait_publish_ready",
        ):
            setattr(app, name, AsyncMock())

        async def upload(_playwright=None, session=None):
            await app._upload_on_page(env.page, managed=False, budget=None)

        app.upload = upload
        builder = MagicMock(return_value=app)
        session_cm = _AsyncCM(SimpleNamespace(context=object()))
        factory = MagicMock(return_value=session_cm)

        with tempfile.TemporaryDirectory() as tmp_dir:
            video = Path(tmp_dir) / "demo.mp4"
            video.write_bytes(b"video")
            with (
                patch.dict(os.environ, {"HUMANIZE": "0"}),
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
                    tiktok_command, "_build_video_uploader", new=builder
                ),
            ):
                code, out, err = _run_cli(
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
                        caption,
                        "--no-publish",
                    ]
                )

        self.assertEqual(code, 1)
        self.assertIn("reason=wrong_topic", out)
        self.assertIn("TikTok 配文话题", out)
        self.assertNotIn("TikTok video upload submitted", out)
        self.assertTrue(err.strip())
        app.click_publish.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
