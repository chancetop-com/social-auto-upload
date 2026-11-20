# -*- coding: utf-8 -*-
"""Topic insertion & readback (spec §3 U7, ticket 39).

Topics are an enhancement: if a candidate never appears (or the click inserts
nothing) the plain ``#tag`` text stays in the body plus one space and publishing
continues.  If something *is* inserted it must be exactly one node whose
``data-topic.name`` equals the requested tag — otherwise the run aborts before
the publish click (exit 1).

The tests are offline and virtual-time: ``tests.fakes_clock`` patches the
module's ``time``/``asyncio`` and ``tests.fakes_xhs_dom`` scripts the page.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import sau_commands.xiaohongshu as xhs_command
import uploader.publish_timeout as publish_timeout
import uploader.xiaohongshu_uploader.main as xhs_main
from tests.fakes_clock import FakeClock
from tests.fakes_xhs_dom import (
    CaptionBody,
    FakeLocator,
    RecordingKeyboard,
    RecordingLocator,
    RecordingPage,
)
from utils.caption_topics import STATUS_LINKED, STATUS_TEXT
from utils.dom import ElementUnusableError

TOPIC_CONTAINER = "#creator-editor-topic-container"
TOPIC_ITEMS = "#creator-editor-topic-container .item"
TOPIC_READBACK = 'div.tiptap[role="textbox"] a[data-topic]'
BODY_EDITOR = 'div.tiptap[role="textbox"][contenteditable="true"]'

FACTS = {
    "tag": "div",
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


def _fast_humanize():
    """HUMANIZE=0: the behaviour layer's delays are covered by ticket 34."""
    return patch.dict(os.environ, {"HUMANIZE": "0"})


class TopicNode(FakeLocator):
    """One ``a[data-topic]`` node inside the body editor."""

    def __init__(self, raw: str) -> None:
        super().__init__("topic-node", attributes={"data-topic": raw})
        self.raw = raw


class TopicNodes(FakeLocator):
    """The editor-scoped ``a[data-topic]`` collection (mutable between clicks)."""

    def __init__(self, events: list[str] | None = None) -> None:
        super().__init__("topic-nodes", count=0)
        self._items: list[TopicNode] = []
        self.count_calls = 0
        self.fail = False
        self.events = events if events is not None else []

    async def count(self) -> int:
        self.count_calls += 1
        self.events.append("read")
        if self.fail:
            raise RuntimeError("readback probe failed")
        return len(self._items)

    def nth(self, index: int) -> TopicNode:
        return self._items[index]

    async def evaluate_all(self, expression):
        await self.count()  # Preserve scripted failures and read-order recording.
        return [node.raw for node in self._items]

    def add(self, name: str | None = None, *, raw: str | None = None) -> TopicNode:
        if raw is None:
            raw = json.dumps(
                {"id": "1", "link": "", "name": name}, ensure_ascii=False
            )
        node = TopicNode(raw)
        self._items.append(node)
        return node


class MenuItems(FakeLocator):
    """``#creator-editor-topic-container .item`` list; ``count`` can be scripted."""

    def __init__(self) -> None:
        super().__init__("topic-items", count=0)
        self._items: list[TopicItem] = []
        self.count_script: list[int] | None = None
        self.count_calls = 0
        self.available = True

    async def count(self) -> int:
        self.count_calls += 1
        if self.count_script is not None:
            index = min(self.count_calls - 1, len(self.count_script) - 1)
            return self.count_script[index]
        return len(self._items) if self.available else 0

    def nth(self, index: int) -> "TopicItem":
        return self._items[index]

    def set_items(self, items: list["TopicItem"]) -> None:
        self._items = list(items)
        self.available = True
        self.count_script = None

    def clear(self) -> None:
        self._items = []
        self.available = False


class TopicItem(FakeLocator):
    """One rendered candidate; ``.name`` carries the visible (``#``-prefixed) text."""

    def __init__(self, label: str, *, is_new: bool = False) -> None:
        children = {".name": FakeLocator(f"topic-name:{label}", text=label)}
        if is_new:
            children[".newTopic"] = FakeLocator(
                f"topic-new:{label}", text="新建话题"
            )
        super().__init__(
            f"topic-item:{label}",
            children=children,
            evaluate_handler=self._evaluate,
            box={"x": 0.0, "y": 0.0, "width": 200.0, "height": 30.0},
        )
        self.label = label
        self.is_new = is_new
        self.on_click = None

    @staticmethod
    def _evaluate(expression, arg=None):
        # 事实探测（合并进默认值）与落点命中都走同一个 evaluate。
        return {"self": True} if "elementFromPoint" in str(expression) else dict(FACTS)

    async def click(self, **kwargs) -> None:
        await super().click(**kwargs)
        if self.on_click is not None:
            self.on_click(self)


class TopicEnv:
    """Scripted publish page for one ``fill_tags`` run."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.nodes = TopicNodes(self.events)
        self.menu = MenuItems()
        self.container = FakeLocator("topic-container", count=1)
        self.body = RecordingLocator("body")
        self.page = RecordingPage(
            selectors={
                TOPIC_CONTAINER: self.container,
                TOPIC_ITEMS: self.menu,
                TOPIC_READBACK: self.nodes,
                BODY_EDITOR: self.body,
            },
            evaluate_handler=self._snapshot,
        )
        self.items: list[TopicItem] = []

    @staticmethod
    def _snapshot(expression, arg=None):
        if "items.map" not in expression or arg.get("nameSelector") != ".name":
            raise AssertionError(f"Unexpected page evaluation: {expression}")
        return [{"name": item.label, "attached": True} for item in arg["items"]]

    def set_labels(self, labels: list[str]) -> list[TopicItem]:
        self.items = [TopicItem(label) for label in labels]
        self.menu.set_items(self.items)
        return self.items

    def insert_on_click(self, item: TopicItem) -> None:
        self.events.append("click")
        self.nodes.add(item.label.lstrip("#"))
        self.menu.clear()


class TopicTestBase(unittest.TestCase):
    def app(self, tags, *, desc="海边的日落"):
        return xhs_main.XiaoHongShuVideo(
            title="标题",
            file_path="demo.mp4",
            tags=list(tags),
            publish_date=0,
            account_file="account.json",
            desc=desc,
        )

    def run_fill_tags(self, env: TopicEnv, app, *, budget_seconds=None):
        clock = FakeClock(start=100.0)
        with clock.patch(xhs_main, publish_timeout), _fast_humanize():
            if budget_seconds is not None:
                budget = app.start_publish_budget()
                budget.deadline = clock.now + budget_seconds
            asyncio.run(app.fill_tags(env.page))
        return clock

    def keyboard_actions(self, env: TopicEnv):
        return list(env.page.keyboard.actions)


class InlineKeyboard(RecordingKeyboard):
    """Types into :class:`CaptionBody` and swaps the candidate list on ``#topic``."""

    def __init__(self, env: "InlineTopicEnv") -> None:
        super().__init__()
        self.env = env
        self.query: str | None = None

    async def insert_text(self, text: str, **kwargs) -> None:
        await super().insert_text(text, **kwargs)
        self.env.body.insert_text(text)
        match = re.fullmatch(r"#([^\s#]+)", text)
        if match is None:
            return
        self.query = match.group(1)
        rows = self.env.suggestions.get(self.query)
        if rows is None:
            rows = [{"label": "#" + self.query}]
        items = []
        for row in rows:
            item = TopicItem(
                row["label"], is_new=bool(row.get("new", False))
            )
            item.on_click = lambda clicked, spec=row: self.env.choose(
                clicked, spec
            )
            items.append(item)
        self.env.menu.set_items(items)

    async def press(self, key: str, **kwargs) -> None:
        await super().press(key, **kwargs)
        if key == "Backspace":
            self.env.body.backspace()
        elif key == "Enter":
            self.env.body.insert_text("\n")
        elif key == "Escape":
            self.env.menu.clear()


class InlineTopicEnv:
    """Caption editor + suggestion feed that replaces the typed word with a chip."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.nodes = TopicNodes(self.events)
        self.menu = MenuItems()
        self.container = FakeLocator("topic-container", count=1)
        self.body = CaptionBody()
        self.suggestions: dict[str, list[dict]] = {}
        self.page = RecordingPage(
            selectors={
                TOPIC_CONTAINER: self.container,
                TOPIC_ITEMS: self.menu,
                TOPIC_READBACK: self.nodes,
                BODY_EDITOR: self.body,
                ".feature-guide__btn": FakeLocator("guide", count=0),
            },
            evaluate_handler=self._snapshot,
        )
        self.keyboard = InlineKeyboard(self)
        self.page.keyboard = self.keyboard
        self.items: list[TopicItem] = []

    @staticmethod
    def _snapshot(expression, arg=None):
        if "items.map" not in expression or arg.get("nameSelector") != ".name":
            raise AssertionError(f"Unexpected page evaluation: {expression}")
        return [{"name": item.label, "attached": True} for item in arg["items"]]

    def choose(self, item: TopicItem, spec: dict) -> None:
        self.events.append("click")
        self.body.choose(self.keyboard.query or "", spec.get("behaviour", {}))
        self.nodes.add(
            spec.get("behaviour", {}).get("name", self.keyboard.query) or ""
        )
        self.menu.clear()


class InlineTopicTestBase(TopicTestBase):
    def app_for(self, action: str, caption: str):
        if action == "upload-note":
            return xhs_main.XiaoHongShuNote(
                image_paths=["a.png"],
                note=caption,
                tags=[],
                publish_date=0,
                account_file="account.json",
                title="标题",
            )
        return xhs_main.XiaoHongShuVideo(
            title="标题",
            file_path="demo.mp4",
            tags=[],
            publish_date=0,
            account_file="account.json",
            desc=caption,
        )

    def run_fill_desc(self, env: InlineTopicEnv, app, *, budget_seconds=None):
        clock = FakeClock(start=100.0)
        with clock.patch(xhs_main, publish_timeout), _fast_humanize():
            if budget_seconds is not None:
                budget = app.start_publish_budget()
                budget.deadline = clock.now + budget_seconds
            asyncio.run(app.fill_desc(env.page))
        return clock

    def assert_linked(self, app, env, caption: str, names: list[str]) -> None:
        self.assertEqual(env.body.readbacks[-1], caption)
        self.assertEqual(env.body.text, caption + "\n")
        self.assertEqual(env.body.anchor_names, names)
        self.assertEqual(
            [item["status"] for item in app.topic_results or []],
            [STATUS_LINKED] * len(names),
        )
        self.assertEqual(app.topic_results[0]["text"], "#" + names[0])


# ---------------------------------------------------------------------------
# 1. Candidate matching: full-equal name only, scan all rendered items
# ---------------------------------------------------------------------------


class Decision08TopicCandidateMatchTests(TopicTestBase):
    def _click_matching_position(self, position: int, total: int):
        env = TopicEnv()
        labels = [f"#热门{i}" for i in range(total)]
        labels[position] = "#旅行"
        items = env.set_labels(labels)
        for item in items:
            item.on_click = env.insert_on_click

        self.run_fill_tags(env, self.app(["旅行"]))

        clicked = [item for item in items if item.click_count]
        self.assertEqual(
            [item.label for item in clicked],
            ["#旅行"],
            f"only the full-equal item may be clicked (position {position})",
        )
        self.assertEqual(clicked[0].click_count, 1)

    def test_exact_match_is_clicked_when_first(self):
        self._click_matching_position(0, 3)

    def test_exact_match_is_clicked_when_fourth(self):
        self._click_matching_position(3, 8)

    def test_exact_match_is_clicked_when_fiftieth(self):
        self._click_matching_position(49, 50)

    def test_prefix_candidate_is_not_a_match(self):
        env = TopicEnv()
        items = env.set_labels(["#旅行pov", "#旅行日常"])
        for item in items:
            item.on_click = env.insert_on_click

        self.run_fill_tags(env, self.app(["旅行"]))

        self.assertEqual(sum(item.click_count for item in items), 0)
        self.assertIn(
            ("press", "Space"), self.keyboard_actions(env),
            "no full-equal candidate must degrade to '#旅行 '",
        )

    def test_name_normalisation_ignores_hash_whitespace_and_case(self):
        env = TopicEnv()
        items = env.set_labels(["#  旅   行  "])
        items[0].on_click = env.insert_on_click

        self.run_fill_tags(env, self.app(["旅 行"]))

        self.assertEqual(items[0].click_count, 1)

    def test_name_casefold_matches_latin_tags(self):
        env = TopicEnv()
        items = env.set_labels(["#Travel"])
        items[0].on_click = env.insert_on_click

        self.run_fill_tags(env, self.app(["TRAVEL"]))

        self.assertEqual(items[0].click_count, 1)


class Decision08TopicReadinessTests(TopicTestBase):
    def test_zero_item_shell_is_not_treated_as_ready(self):
        env = TopicEnv()
        items = env.set_labels(["#旅行"])
        items[0].on_click = env.insert_on_click
        # 容器先以 0 项空壳出现，约 430–570ms 后才渲染候选。
        env.menu.count_script = [0, 0, 1]

        clock = self.run_fill_tags(env, self.app(["旅行"]))

        self.assertEqual(items[0].click_count, 1)
        self.assertGreaterEqual(env.menu.count_calls, 3)
        self.assertEqual(clock.sleep_calls[:2], [0.2, 0.2])


# ---------------------------------------------------------------------------
# 2. Missing candidate: degrade, never fail, never press Backspace
# ---------------------------------------------------------------------------


class Decision08TopicDegradeTests(TopicTestBase):
    def test_no_candidate_keeps_plain_text_plus_one_space(self):
        env = TopicEnv()
        items = env.set_labels(["#旅行pov", "#旅行日常"])
        recorder = _LogRecorder()

        with patch.object(xhs_main, "xiaohongshu_logger", recorder):
            self.run_fill_tags(env, self.app(["旅行"]))

        self.assertEqual(sum(item.click_count for item in items), 0)
        self.assertEqual(
            self.keyboard_actions(env),
            [("insert_text", "#旅行"), ("press", "Space")],
        )
        self.assertNotIn(("press", "Backspace"), self.keyboard_actions(env))
        self.assertTrue(recorder.only("warning"), "degrade must log a warning")

    def test_missing_container_degrades(self):
        env = TopicEnv()
        env.menu.clear()
        env.container = FakeLocator("topic-container", count=0)
        env.page._selectors[TOPIC_CONTAINER] = env.container

        clock = self.run_fill_tags(env, self.app(["旅行"]), budget_seconds=None)

        self.assertEqual(
            self.keyboard_actions(env),
            [("insert_text", "#旅行"), ("press", "Space")],
        )
        self.assertAlmostEqual(sum(clock.sleep_calls), 5.0, places=6)


class InlineCaptionSelectionTests(InlineTopicTestBase):
    def _run(self, action: str):
        caption = "Today #coffee, then #qzx974631sau."
        env = InlineTopicEnv()
        env.suggestions = {
            "coffee": [{"label": "#coffee"}],
            "qzx974631sau": [{"label": "#qzx974631sau", "new": True}],
        }
        app = self.app_for(action, caption)

        self.run_fill_desc(env, app)

        self.assert_linked(
            app, env, caption, ["coffee", "qzx974631sau"]
        )
        self.assertNotIn("\u00a0", env.body.text)
        self.assertEqual(
            [item["reason"] for item in app.topic_results], [None, None]
        )
        actions = env.page.keyboard.actions
        self.assertEqual(
            [action for action in actions if action[0] == "press"],
            [
                ("press", "Backspace"),
                ("press", "ControlOrMeta+A"),
                ("press", "Delete"),
                ("press", "Backspace"),
                ("press", "Backspace"),
                ("press", "Enter"),
            ],
        )
        self.assertEqual(env.body.readback_calls >= 1, True)

    def test_video_links_ordinary_and_new_topic_candidates_in_place(self):
        self._run("upload-video")

    def test_note_links_ordinary_and_new_topic_candidates_in_place(self):
        self._run("upload-note")


class InlineCaptionPreservationTests(InlineTopicTestBase):
    def test_duplicates_punctuation_newlines_and_url_fragments_stay_verbatim(self):
        caption = (
            "第一行 #咖啡，紧邻。#咖啡！\n"
            "链接 https://example.com/#片段 保留\n"
            "Mixed #Coffee_2 end"
        )
        env = InlineTopicEnv()
        env.suggestions = {
            "咖啡": [{"label": "#咖啡"}],
            "Coffee_2": [{"label": "#Coffee_2"}],
        }
        app = self.app_for("upload-video", caption)

        self.run_fill_desc(env, app)

        self.assertEqual(env.body.readbacks[-1], caption)
        self.assertEqual(env.body.text, caption + "\n")
        self.assertEqual(env.body.anchor_names, ["咖啡", "咖啡", "Coffee_2"])
        self.assertEqual(
            [(item["index"], item["text"]) for item in app.topic_results],
            [(1, "#咖啡"), (2, "#咖啡"), (3, "#Coffee_2")],
        )
        self.assertNotIn("\u00a0", env.body.text)
        self.assertIn("https://example.com/#片段", env.body.text)
        typed = [
            action[1]
            for action in env.page.keyboard.actions
            if action[0] == "insert_text"
        ]
        self.assertTrue(
            any("https://example.com/#片段 保留" in value for value in typed)
        )
        self.assertTrue(any("Mixed " in value for value in typed))
        presses = [
            action[1]
            for action in env.page.keyboard.actions
            if action[0] == "press"
        ]
        self.assertEqual(presses.count("Enter"), 3)  # two authored newlines + final

    def test_author_authored_nbsp_survives_the_auto_space_handling(self):
        caption = "#coffee\u00a0next"
        env = InlineTopicEnv()
        env.suggestions = {"coffee": [{"label": "#coffee"}]}
        app = self.app_for("upload-note", caption)

        self.run_fill_desc(env, app)

        self.assertEqual(env.body.readbacks[-1], caption)
        self.assertEqual(env.body.text, caption + "\n")
        self.assertEqual(env.body.text.count("\u00a0"), 1)
        self.assertEqual(env.body.anchor_names, ["coffee"])
        self.assertEqual(
            [item["status"] for item in app.topic_results], [STATUS_LINKED]
        )


class InlineCaptionFallbackTests(InlineTopicTestBase):
    def test_approximate_only_keeps_the_word_in_place_and_continues(self):
        caption = "今天 #coffee，结束"
        env = InlineTopicEnv()
        env.suggestions = {"coffee": [{"label": "#coffeecreamer"}]}
        app = self.app_for("upload-video", caption)

        self.run_fill_desc(env, app)

        self.assertEqual(env.body.readbacks[-1], caption)
        self.assertEqual(env.body.text, caption + "\n")
        self.assertEqual(env.body.anchor_names, [])
        self.assertEqual(
            app.topic_results,
            [
                {
                    "index": 1,
                    "name": "coffee",
                    "text": "#coffee",
                    "status": STATUS_TEXT,
                    "reason": "无同名候选",
                }
            ],
        )
        self.assertEqual(env.events.count("click"), 0)
        self.assertIn(("press", "Escape"), env.page.keyboard.actions)
        self.assertNotIn(("press", "Space"), env.page.keyboard.actions)

    def test_eleventh_inline_topic_stays_fully_readable_while_ten_link(self):
        caption = " ".join(f"#tag{i}" for i in range(12))
        env = InlineTopicEnv()
        env.suggestions = {
            f"tag{i}": [{"label": f"#tag{i}"}] for i in range(12)
        }
        app = self.app_for("upload-note", caption)

        self.run_fill_desc(env, app)

        self.assertEqual(env.body.readbacks[-1], caption)
        self.assertEqual(env.body.text, caption + "\n")
        self.assertEqual(env.body.anchor_names, [f"tag{i}" for i in range(10)])
        self.assertEqual(env.events.count("click"), 10)
        statuses = [item["status"] for item in app.topic_results]
        self.assertEqual(statuses, [STATUS_LINKED] * 10 + [STATUS_TEXT] * 2)
        self.assertEqual(
            [item["reason"] for item in app.topic_results[-2:]],
            ["已达可关联上限 10", "已达可关联上限 10"],
        )
        # 第 11、12 个词仍在正文里，没有被截断或丢弃。
        self.assertIn("#tag10", env.body.text)
        self.assertIn("#tag11", env.body.text)
        self.assertEqual(len(app.topic_results), 12)


class InlineCaptionFailureTests(InlineTopicTestBase):
    def _run_failure(self, behaviour: dict, *, caption="今天 #coffee，结束"):
        env = InlineTopicEnv()
        env.suggestions = {
            "coffee": [{"label": "#coffee", "behaviour": behaviour}]
        }
        app = self.app_for("upload-video", caption)
        with self.assertRaises(ElementUnusableError) as ctx:
            self.run_fill_desc(env, app)
        error = ctx.exception
        self.assertFalse(error.publish_clicked)
        self.assertIn("未点击发布", str(error))
        return error, env

    def test_wrong_topic_selection_stops_with_the_observed_name(self):
        error, _env = self._run_failure({"name": "coffeecreamer"})
        self.assertIn("选中的话题与原词不符", error.reason)
        self.assertIn("期望「#coffee」", error.reason)
        self.assertIn("实际「#coffeecreamer」", error.reason)

    def test_swallowed_text_stops_with_the_first_difference(self):
        error, _env = self._run_failure({"mode": "swallow"})
        self.assertIn("个字符不同", error.reason)
        self.assertIn("期望全文", error.reason)

    def test_misplaced_topic_stops_with_the_first_difference(self):
        error, _env = self._run_failure({"mode": "misplace"})
        self.assertIn("个字符不同", error.reason)

    def test_extra_text_after_selection_stops_with_the_first_difference(self):
        error, _env = self._run_failure({"mode": "extra"})
        self.assertIn("个字符不同", error.reason)
        self.assertIn("EXTRA", error.reason)

    def test_whole_post_hard_limit_stops_before_publish(self):
        caption = "今天 #coffee，结束"
        env = InlineTopicEnv()
        env.suggestions = {"coffee": [{"label": "#coffee"}]}
        env.page._selectors[xhs_main.XHS_BODY_LENGTH_ERROR_SELECTOR] = FakeLocator(
            "body-error", count=1
        )
        app = self.app_for("upload-note", caption)

        with self.assertRaises(ElementUnusableError) as ctx:
            self.run_fill_and_limit(env, app)

        self.assertEqual(
            ctx.exception.reason, "正文超出平台长度上限（长度错误节点存在）"
        )
        self.assertFalse(ctx.exception.publish_clicked)
        self.assertEqual(env.body.readbacks[-1], caption)
        self.assertEqual(env.body.anchor_names, ["coffee"])

    def run_fill_and_limit(self, env: InlineTopicEnv, app):
        clock = FakeClock(start=100.0)
        with clock.patch(xhs_main, publish_timeout), _fast_humanize():
            app.start_publish_budget()
            asyncio.run(app.fill_desc(env.page))
            asyncio.run(app._assert_body_not_over_limit(env.page))
        return clock

    def test_publish_chain_stops_at_the_topic_failure_and_never_arms(self):
        caption = "今天 #coffee，结束"
        env = InlineTopicEnv()
        env.suggestions = {
            "coffee": [{"label": "#coffee", "behaviour": {"mode": "swallow"}}]
        }
        app = self.app_for("upload-note", caption)
        wait_for_arm = AsyncMock()

        async def run():
            with (
                patch.object(xhs_main, "_run_dom_quiet_gate", AsyncMock()),
                patch.object(xhs_main, "_clear_known_overlays", AsyncMock()),
                patch.object(xhs_main, "_note_upload_gate", AsyncMock()),
                patch.object(xhs_main, "_check_blocked", AsyncMock()),
                patch.object(xhs_main, "_wait_for_arm", wait_for_arm),
                patch.object(app, "fill_title", AsyncMock()),
                patch.object(
                    app, "_verify_schedule_before_fire", AsyncMock()
                ),
            ):
                await app.upload_note_content(env.page, mode="local")

        with FakeClock(start=100.0).patch(
            xhs_main, publish_timeout
        ), _fast_humanize(), self.assertRaises(ElementUnusableError) as ctx:
            asyncio.run(run())

        self.assertIn("个字符不同", ctx.exception.reason)
        self.assertFalse(ctx.exception.publish_clicked)
        wait_for_arm.assert_not_awaited()
        self.assertEqual(env.page.mouse.down_count, 0)
        self.assertEqual(env.page.mouse.up_count, 0)


class InlineCaptionLegacyTagIsolationTests(InlineTopicTestBase):
    def test_legacy_tag_cap_never_touches_the_caption(self):
        caption = " ".join(f"#topic{i}" for i in range(12))
        tags = [f"tag{i}" for i in range(12)]
        app = self.app_for("upload-video", caption)
        app.tags = list(tags)

        with patch.object(
            xhs_main, "_cap_tags", wraps=xhs_main._cap_tags
        ) as cap:
            asyncio.run(app.validate_base_args(check_cookie=False))

        self.assertEqual(app.desc, caption)
        self.assertEqual(app.tags, tags[:10])
        self.assertEqual(cap.call_args_list[0].args[0], tags)
        self.assertEqual(cap.call_count, 1)


class InlineCaptionEmptyTests(InlineTopicTestBase):
    def test_omitted_caption_does_not_touch_the_editor(self):
        env = InlineTopicEnv()
        app = self.app_for("upload-video", "")

        self.run_fill_desc(env, app)

        self.assertEqual(env.page.keyboard.actions, [])
        self.assertEqual(env.body.readbacks, [])
        self.assertIsNone(app.topic_results)

    def test_caption_without_topics_keeps_the_existing_typing_path(self):
        caption = "今天喝了咖啡，配上栗子蛋糕。"
        env = InlineTopicEnv()
        app = self.app_for("upload-note", caption)

        self.run_fill_desc(env, app)

        self.assertEqual(
            [action for action in env.page.keyboard.actions if action[0] == "insert_text"],
            [("insert_text", caption)],
        )
        self.assertEqual(env.body.readbacks, [])
        self.assertIsNone(app.topic_results)
        self.assertEqual(env.body.text, caption + "\n")


class InlineCaptionNoPublishTests(InlineTopicTestBase):
    def test_no_publish_stops_after_topic_readback_and_before_any_click(self):
        caption = "Today #coffee, then done."
        env = InlineTopicEnv()
        env.suggestions = {"coffee": [{"label": "#coffee", "new": True}]}
        app = self.app_for("upload-note", caption)
        app.no_publish = True

        async def run():
            with (
                patch.object(xhs_main, "_run_dom_quiet_gate", AsyncMock()),
                patch.object(xhs_main, "_clear_known_overlays", AsyncMock()),
                patch.object(xhs_main, "_note_upload_gate", AsyncMock()),
                patch.object(xhs_main, "_check_blocked", AsyncMock()),
                patch.object(xhs_main, "_wait_for_arm", AsyncMock()),
                patch.object(app, "fill_title", AsyncMock()),
                patch.object(
                    app, "_verify_schedule_before_fire", AsyncMock()
                ),
            ):
                await app.upload_note_content(env.page, mode="local")

        with FakeClock(start=100.0).patch(
            xhs_main, publish_timeout
        ), _fast_humanize():
            asyncio.run(run())

        self.assertEqual(env.body.readbacks[-1], caption)
        self.assertEqual(env.body.anchor_names, ["coffee"])
        self.assertEqual(
            [item["status"] for item in app.topic_results], [STATUS_LINKED]
        )
        self.assertEqual(env.page.mouse.down_count, 0)
        self.assertEqual(env.page.mouse.up_count, 0)


class Decision08TopicOutcomeTests(TopicTestBase):
    def _click_that_inserts(self, env: TopicEnv, *names: str):
        env.set_labels(["#旅行"])

        def _on_click(_item):
            env.events.append("click")
            for name in names:
                env.nodes.add(name)
            env.menu.clear()

        env.items[0].on_click = _on_click

    def test_mismatched_topic_name_aborts_before_publish(self):
        env = TopicEnv()
        self._click_that_inserts(env, "旅行pov")

        with self.assertRaises(ElementUnusableError) as ctx:
            self.run_fill_tags(env, self.app(["旅行"]))

        error = ctx.exception
        self.assertEqual(error.reason, "topic-mismatch")
        self.assertFalse(error.publish_clicked)
        self.assertEqual(error.tag, "旅行")
        self.assertEqual(error.observed_names, ["旅行pov"])
        self.assertEqual(len(error.new_nodes), 1)
        self.assertEqual(error.attempts, 1)

    def test_unparseable_topic_payload_is_a_mismatch(self):
        env = TopicEnv()
        env.set_labels(["#旅行"])

        def _on_click(_item):
            env.events.append("click")
            env.nodes.add(raw="not-json")
            env.menu.clear()

        env.items[0].on_click = _on_click

        with self.assertRaises(ElementUnusableError) as ctx:
            self.run_fill_tags(env, self.app(["旅行"]))

        self.assertEqual(ctx.exception.reason, "topic-mismatch")
        self.assertEqual(ctx.exception.observed_names, [None])

    def test_two_new_nodes_abort_as_multi_insert(self):
        env = TopicEnv()
        self._click_that_inserts(env, "旅行", "旅行")

        with self.assertRaises(ElementUnusableError) as ctx:
            self.run_fill_tags(env, self.app(["旅行"]))

        error = ctx.exception
        self.assertEqual(error.reason, "topic-multi-insert")
        self.assertFalse(error.publish_clicked)
        self.assertEqual(len(error.new_nodes), 2)
        self.assertEqual(error.attempts, 1)

    def test_exactly_one_full_equal_node_succeeds(self):
        env = TopicEnv()
        self._click_that_inserts(env, "旅行")
        recorder = _LogRecorder()

        with patch.object(xhs_main, "xiaohongshu_logger", recorder):
            self.run_fill_tags(env, self.app(["旅行"]))

        self.assertEqual(recorder.only("warning"), [])
        self.assertNotIn(("press", "Space"), self.keyboard_actions(env))

    def test_baseline_is_fixed_per_tag_and_not_refreshed_on_retry(self):
        env = TopicEnv()
        env.set_labels(["#旅行"])
        clicks = {"count": 0}

        def _on_click(_item):
            clicks["count"] += 1
            env.events.append("click")
            if clicks["count"] == 1:
                # 第 1 次插入了错误话题；下拉未关，允许第 2 次点击。
                env.nodes.add("旅行pov")
            else:
                env.menu.clear()

        env.items[0].on_click = _on_click

        with self.assertRaises(ElementUnusableError) as ctx:
            self.run_fill_tags(env, self.app(["旅行"]))

        self.assertEqual(clicks["count"], 2)
        self.assertEqual(ctx.exception.reason, "topic-mismatch")
        self.assertEqual(ctx.exception.attempts, 2)
        self.assertEqual(ctx.exception.observed_names, ["旅行pov"])

    def test_readback_runs_once_after_all_clicks(self):
        env = TopicEnv()
        env.set_labels(["#旅行"])

        def _on_click(_item):
            env.events.append("click")
            env.nodes.add("旅行")

        env.items[0].on_click = _on_click

        with self.assertRaises(ElementUnusableError) as ctx:
            self.run_fill_tags(env, self.app(["旅行"]))

        # 下拉一直不关 → 3 次点击 → 3 个新增 → 多插中止。
        self.assertEqual(ctx.exception.reason, "topic-multi-insert")
        self.assertEqual(ctx.exception.attempts, 3)
        click_indices = [
            index for index, event in enumerate(env.events) if event == "click"
        ]
        self.assertEqual(len(click_indices), 3)
        self.assertNotIn(
            "read",
            env.events[click_indices[0] : click_indices[-1]],
            "readback must not run inside the click loop",
        )
        self.assertIn("read", env.events[click_indices[-1] + 1 :])


class TagKeyboard(RecordingKeyboard):
    """Typing ``#tag`` swaps the scripted candidate list (real suggestion feed)."""

    def __init__(self, menu: MenuItems, suggestions: dict[str, list[str]]) -> None:
        super().__init__()
        self.menu = menu
        self.suggestions = suggestions

    async def insert_text(self, text: str, **kwargs) -> None:
        await super().insert_text(text, **kwargs)
        if text.startswith("#"):
            tag = text[1:].strip()
            labels = self.suggestions.get(tag, [])
            self.menu.set_items([TopicItem(label) for label in labels])


class Decision08TopicBodyFormTests(TopicTestBase):
    def test_spec_example_body_keeps_text_then_adds_topic_chip(self):
        env = TopicEnv()
        env.page.keyboard = TagKeyboard(
            env.menu,
            {
                "旅行": ["#旅行pov", "#旅行日常"],
                "治愈": ["#治愈壁纸", "#治愈"],
            },
        )
        original_set_items = env.menu.set_items

        def _set_items(items):
            original_set_items(items)
            for item in items:
                item.on_click = env.insert_on_click

        env.menu.set_items = _set_items

        self.run_fill_tags(env, self.app(["旅行", "治愈"]))

        self.assertEqual(
            self.keyboard_actions(env),
            [
                ("insert_text", "#旅行"),
                ("press", "Space"),
                ("insert_text", "#治愈"),
            ],
        )
        pressed = [
            action[1]
            for action in self.keyboard_actions(env)
            if action[0] == "press"
        ]
        for forbidden in ("Backspace", "ArrowDown", "Enter"):
            self.assertNotIn(forbidden, pressed)

        # 正文形态：desc + 换行 + '#旅行 ' + '#治愈[话题]#'
        rendered = "海边的日落\n"
        for tag in ("旅行", "治愈"):
            rendered += "#" + tag
            rendered += "[话题]#" if tag == "治愈" else " "
        self.assertEqual(rendered, "海边的日落\n#旅行 #治愈[话题]#")


class Decision08TopicAmbiguityTests(TopicTestBase):
    def test_multiple_full_equal_candidates_choose_first_and_log_info(self):
        env = TopicEnv()
        items = env.set_labels(["#旅行", "#旅行"])
        recorder = _LogRecorder()
        items[0].on_click = env.insert_on_click

        with patch.object(xhs_main, "xiaohongshu_logger", recorder):
            self.run_fill_tags(env, self.app(["旅行"]))

        self.assertEqual([item.click_count for item in items], [1, 0])
        self.assertTrue(
            any("topic-ambiguous:2" in line for line in recorder.only("info"))
        )


class Decision08TopicBudgetTests(TopicTestBase):
    def test_ready_window_is_clamped_to_remaining_budget(self):
        env = TopicEnv()
        env.menu.clear()

        clock = self.run_fill_tags(
            env, self.app(["旅行"]), budget_seconds=0.25
        )

        self.assertAlmostEqual(
            sum(clock.sleep_calls), 0.25, delta=0.002
        )
        self.assertLessEqual(max(clock.sleep_calls), 0.2)

    def test_readback_window_is_clamped_to_remaining_budget(self):
        env = TopicEnv()
        env.set_labels(["#旅行"])

        def _on_click(_item):
            env.events.append("click")
            env.menu.clear()

        env.items[0].on_click = _on_click

        clock = self.run_fill_tags(
            env, self.app(["旅行"]), budget_seconds=0.5
        )

        self.assertAlmostEqual(sum(clock.sleep_calls), 0.5, delta=0.002)
        self.assertEqual(clock.sleep_calls[0], 0.2)
        self.assertAlmostEqual(clock.sleep_calls[-1], 0.05, delta=0.002)

    def test_budget_exhaustion_between_tags_raises_pre_click_error(self):
        # Exhaustion must surface the budget exit (exit 1), not a silent
        # 0-window topic loop that keeps degrading tags.
        env = TopicEnv()
        env.menu.clear()
        app = self.app(["旅行", "治愈"])
        clock = FakeClock(start=100.0)

        class _SpaceAdvancingKeyboard(RecordingKeyboard):
            """Advance virtual time when the first tag degrades."""

            async def press(self, key: str, **kwargs) -> None:
                await super().press(key, **kwargs)
                if key == "Space":
                    clock.advance(0.05)

        env.page.keyboard = _SpaceAdvancingKeyboard()

        with clock.patch(xhs_main, publish_timeout), _fast_humanize():
            budget = app.start_publish_budget()
            budget.deadline = clock.now + 0.1
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(app.fill_tags(env.page))

        self.assertEqual(str(ctx.exception), str(budget.pre_click_error()))
        space = [a for a in env.page.keyboard.actions if a == ("press", "Space")]
        self.assertEqual(len(space), 1, "only the first tag may degrade")

    def test_topic_window_raises_when_budget_is_exhausted(self):
        env = TopicEnv()
        app = self.app(["旅行"])
        clock = FakeClock(start=100.0)

        with clock.patch(xhs_main):
            app.start_publish_budget()
            app.publish_budget.deadline = clock.now
            with self.assertRaises(RuntimeError) as ctx:
                app._topic_window_ms(5_000)

        self.assertEqual(
            str(ctx.exception), str(app.publish_budget.pre_click_error())
        )


class Decision08TopicTagCapTests(TopicTestBase):
    def test_validation_caps_tags_and_names_dropped_items(self):
        tags = [f"tag{i}" for i in range(12)]
        app = self.app(tags)
        recorder = _LogRecorder()

        with patch.object(xhs_main, "xiaohongshu_logger", recorder):
            asyncio.run(app.validate_base_args(check_cookie=False))

        self.assertEqual(app.tags, tags[:10])
        warnings = "\n".join(recorder.only("warning"))
        self.assertIn("tag10", warnings)
        self.assertIn("tag11", warnings)

    def test_fill_tags_does_not_truncate_at_runtime(self):
        tags = [f"tag{i}" for i in range(12)]
        env = TopicEnv()
        env.menu.clear()
        app = self.app(tags)

        self.run_fill_tags(env, app)

        self.assertEqual(app.tags, tags)
        typed = [
            action[1]
            for action in env.page.keyboard.actions
            if action[0] == "insert_text"
        ]
        self.assertEqual(typed, [f"#{tag}" for tag in tags])


class InlineCaptionCliTests(unittest.TestCase):
    def _args(self, action: str = "upload-video"):
        return SimpleNamespace(
            action=action,
            file="demo.mp4",
            images=["a.png"],
            title="标题",
            desc="今天 #咖啡，重复 #咖啡。",
            note="今天 #咖啡，重复 #咖啡。",
            schedule=None,
            thumbnail=None,
            debug=False,
            headless=True,
            not_before=None,
            account="acct",
            location=None,
            original=None,
            content_type=None,
            repost_source=None,
            shoot_location=None,
            shoot_date=None,
            no_publish=True,
        )

    def test_per_occurrence_lines_are_distinguishable_from_the_success_summary(self):
        for action, upload_name in (
            ("upload-video", "upload_xiaohongshu_video"),
            ("upload-note", "upload_xiaohongshu_note"),
        ):
            with self.subTest(action=action):
                args = self._args(action)

                async def fake_upload(request, **_kwargs):
                    request.topic_results = [
                        {
                            "index": 1,
                            "name": "咖啡",
                            "text": "#咖啡",
                            "status": STATUS_LINKED,
                            "reason": None,
                        },
                        {
                            "index": 2,
                            "name": "咖啡",
                            "text": "#咖啡",
                            "status": STATUS_TEXT,
                            "reason": "无同名候选",
                        },
                    ]

                with patch.object(
                    xhs_command,
                    "_validate_declarations",
                    return_value=(None, None, None, None, None),
                ), patch.object(
                    xhs_command, "resolve_managed_provider", return_value=None
                ), patch.object(
                    xhs_command, "require_local_account"
                ), patch.object(
                    xhs_command, "resolve_account_label", return_value="acct"
                ), patch.object(
                    xhs_command, "managed_ignored_keys", return_value=()
                ), patch.object(
                    xhs_command, upload_name, new=fake_upload
                ), redirect_stdout(
                    io.StringIO()
                ) as out, redirect_stderr(
                    io.StringIO()
                ):
                    code = asyncio.run(xhs_command.run(args))

                self.assertEqual(code, 0)
                lines = out.getvalue().splitlines()
                self.assertEqual(
                    [line for line in lines if "配文话题" in line],
                    [
                        "Xiaohongshu 配文话题 1/2：#咖啡 已关联",
                        "Xiaohongshu 配文话题 2/2：#咖啡 保留文字，无同名候选",
                    ],
                )
                self.assertIn(
                    "素材已上传，发布前检查已通过；已停止，未点击发布按钮。",
                    lines,
                )
                self.assertIn(
                    f"Xiaohongshu {'video' if action == 'upload-video' else 'note'} upload: "
                    f"{'demo.mp4' if action == 'upload-video' else '1 images'}",
                    lines,
                )


class _LogRecorder:
    """Capture ``xiaohongshu_logger`` calls as ``(level, message)`` pairs."""

    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    def _record(self, level: str, message: object, *args, **kwargs) -> None:
        self.lines.append((level, str(message)))

    def debug(self, message, *args, **kwargs):
        self._record("debug", message, *args, **kwargs)

    def info(self, message, *args, **kwargs):
        self._record("info", message, *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        self._record("warning", message, *args, **kwargs)

    def success(self, message, *args, **kwargs):
        self._record("success", message, *args, **kwargs)

    def error(self, message, *args, **kwargs):
        self._record("error", message, *args, **kwargs)

    def only(self, level: str) -> list[str]:
        return [line for name, line in self.lines if name == level]


if __name__ == "__main__":
    unittest.main()
