# -*- coding: utf-8 -*-
"""雪球长文的人类化接线（spec §3.13 / §2.4 / §4 / §6.2）。

三块，全部离线：

1. 事件序列 —— 正文聚焦 / 工具栏传图 / 下拉与选项 / 预览与关闭遮罩 / 发布
   各点的原语（``press`` vs ``insert_text``）、``after_type`` 次数、
   ``mouse.move* → down → up``、hit-test 先于 ``down``、零原生 ``locator.click()``、
   零 ``force``。失焦与只读核对保持原生并带登记标记。
2. 字段值读回 —— 标题走 ``T/none``（守卫在 ``article.py:153``，不清空），
   fake 键盘把按键写回持有缓冲的 locator；正文粘贴文本与图片标记不被改写。
3. 平台静态门 —— 包内跑 spec §4.2–4.5 的 A–E 门。

另覆盖 ``HUMANIZE=0`` 快路径与「已有草稿 → 守卫拒绝覆盖」的停工点。选择器未
scripted 直接抛 :class:`UnscriptedSelectorError`，不用 MagicMock。
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from uploader.xueqiu_uploader import article as xueqiu_article
from uploader.xueqiu_uploader.article import XueqiuArticle
from uploader.publish_timeout import PublishTimeoutBudget
from tests.fakes_xhs_dom import (
    FakeFileChooser,
    FakeLocator,
    RecordingKeyboard,
    RecordingLocator,
    RecordingMouse,
    RecordingPage,
    UnscriptedSelectorError,
)
from tests.humanize_gates import assert_clean
from utils.dom import ElementUnusableError
from utils.errors import PublishResultUnknownError
from utils.humanize import (
    MAYBE_DISPATCHED,
    MAYBE_DISPATCHED_VALUE,
    HumanizeProfile,
    LogNormal,
)

AFTER_TYPE = 5.0
BEFORE_SUBMIT = 7.0

TITLE = "雪球文章标题"
VISIBILITY = "公开"
DECLARATION = "本文包含AI生成内容"

TITLE_PLACEHOLDER = "placeholder:请输入标题:exact"
BODY = '#editor > [contenteditable="true"]'
TOOLBAR_UPLOAD = '#snb_toolbar [data-tip="上传图片"]'
CROP_CONFIRM = "role:button:确认裁剪"
PREVIEW_BUTTON = "role:button:预览"
PREVIEW_CLOSE = 'div[class*="index_preview_"] > div[class*="index_close_"]'
PREVIEW_CONTENT = 'div[class*="index_preview-content_"]'
PUBLISH_BUTTON = "role:button:发布"
SECTIONS = 'div[class*="index_sectionFlex_"]'
SELECT_WRAP = 'div[class*="index_selectWrap_"]'
OPTION_CONTAINER = 'div[class*="index_optionContainer_"]:visible'
PUBLISH_STATE = 'div[class*="publish_state_"]'


def _fixed(seconds: float) -> LogNormal:
    return LogNormal(0.0, 0.0, seconds, seconds)


#: 固定停顿表：5.0s 只可能是 after_type，7.0s 只可能是 before_submit。
TEST_PROFILE = HumanizeProfile(
    keystroke=_fixed(0.01),
    after_type=_fixed(AFTER_TYPE),
    after_navigate=_fixed(2.0),
    before_submit=_fixed(BEFORE_SUBMIT),
    pointer_settle=_fixed(0.02),
    click_hold=_fixed(0.03),
    before_click=_fixed(0.04),
    after_click=_fixed(0.05),
    between_scroll=_fixed(0.06),
    reading=_fixed(0.07),
    after_interact=_fixed(0.08),
)


def _expr_kind(expression) -> str:
    if not isinstance(expression, str):
        return "unknown"
    if "elementFromPoint" in expression and "childFrame" not in expression:
        return "hit-test"
    if "childFrame" in expression:
        return "geometry"
    if "getComputedStyle" in expression:
        return "facts"
    return "unknown"


class _Clickable(RecordingLocator):
    """可被 ``Humanizer.click`` 坐标点击的 fake：盒模型 + 事实探测 + 命中测试。"""

    def __init__(self, name: str, *, log: list, **kwargs) -> None:
        kwargs.setdefault(
            "box", {"x": 10.0, "y": 20.0, "width": 60.0, "height": 24.0}
        )
        super().__init__(name, **kwargs)
        self._log = log
        self.reads = 0

    # Playwright 的收窄 API 允许 exact=...；fake 只按精确键查找。
    def get_by_role(self, role: str, name=None, exact: bool = False, **kwargs):
        return super().get_by_role(role, name)

    def get_by_text(self, text: str, exact: bool = False, **kwargs):
        return super().get_by_text(text, exact=exact)

    async def inner_text(self) -> str:
        self.reads += 1
        self._log.append(("inner_text", self.name))
        return await super().inner_text()

    async def evaluate(self, expression, arg=None):
        self.evaluate_calls.append((expression, arg))
        kind = _expr_kind(expression)
        self._log.append(("evaluate", kind, self.name))
        if kind == "hit-test":
            page = getattr(self, "_page", None)
            if page is not None:
                page.hit_target = self
            return {"self": True, "tag": "div", "className": "", "id": "", "text": ""}
        if kind == "geometry":
            return {
                "width": 60.0,
                "height": 24.0,
                "inside": True,
                "clipped": False,
                "childFrame": False,
            }
        if "backgroundImage" in expression:
            return "https://xqimg.imedao.com/cover.png"
        if "naturalWidth" in expression:
            return 64.0
        if ".src" in expression:
            return "https://xqimg.imedao.com/uploaded.png"
        return {
            "tag": "div",
            "display": "block",
            "visibility": "visible",
            "opacity": 1.0,
            "disabled": False,
            "isConnected": True,
            "contentEditable": "true",
        }

    async def evaluate_all(self, expression, arg=None):
        self.evaluate_calls.append((expression, arg))
        return []

    async def scroll_into_view_if_needed(self, **kwargs) -> None:
        self.actions.append(("scroll",))


class _TypingLocator(_Clickable):
    """持有键入缓冲的 locator；键盘事件写回当前 focus 的实例。"""

    def __init__(self, name: str, *, log: list, initial: str = "", **kwargs):
        super().__init__(name, log=log, **kwargs)
        self.buffer = initial
        self._page = None

    async def focus(self, **kwargs) -> None:
        self.actions.append(("focus",))
        if self._page is not None:
            self._page.focused = self
            self._page.selected = False

    async def click(self, **kwargs) -> None:
        await super().click(**kwargs)
        await self.focus()

    async def inner_text(self) -> str:
        self.reads += 1
        return self.buffer

    async def input_value(self) -> str:
        return self.buffer

    async def bounding_box(self):
        # 坐标点击前必然会测量盒模型；落点就在输入框内，因此焦点随之转移。
        if self._page is not None:
            self._page.focused = self
            self._page.selected = False
        return await super().bounding_box()

    def apply_key(self, key: str) -> None:
        page = self._page
        if page is None or page.focused is not self:
            return
        if key in ("ControlOrMeta+A", "Control+A", "Meta+A"):
            page.selected = True
        elif key in ("Delete", "Backspace"):
            if page.selected:
                self.buffer = ""
            elif key == "Backspace":
                self.buffer = self.buffer[:-1]
            page.selected = False
        elif key == "Enter":
            self.buffer += "\n"
        elif len(key) == 1:
            if page.selected:
                self.buffer = key
                page.selected = False
            else:
                self.buffer += key

    def apply_text(self, text: str) -> None:
        page = self._page
        if page is None or page.focused is not self:
            return
        if page.selected:
            self.buffer = text
            page.selected = False
        else:
            self.buffer += text


class _OrderedMouse(RecordingMouse):
    def __init__(self, log: list, page: "_Page | None" = None) -> None:
        super().__init__()
        self._log = log
        self._page = page

    async def move(self, x: float, y: float, **kwargs) -> None:
        self.actions.append(("move", x, y))
        self._log.append(("move", x, y))

    async def down(self, **kwargs) -> None:
        self.actions.append(("down",))
        self.down_count += 1
        self._log.append(("down",))

    async def up(self, **kwargs) -> None:
        self.actions.append(("up",))
        self.up_count += 1
        self._log.append(("up",))


class _TypingKeyboard(RecordingKeyboard):
    def __init__(self, page: "_Page") -> None:
        super().__init__()
        self._page = page

    async def press(self, key: str, **kwargs) -> None:
        self.actions.append(("press", key))
        self._page.apply_key(key)

    async def insert_text(self, text: str, **kwargs) -> None:
        self.actions.append(("insert_text", text))
        self._page.apply_text(text)


class _Page(RecordingPage):
    """带确定顺序日志、focus 键盘和 placeholder 查找的 page double。"""

    def __init__(self, *, log: list, **kwargs) -> None:
        self.interactions = log
        super().__init__(**kwargs)
        self.mouse = _OrderedMouse(log, self)
        self.keyboard = _TypingKeyboard(self)
        self.focused = None
        self.selected = False
        self.hit_target = None

    def get_by_role(self, role: str, name=None, exact: bool = False, **kwargs):
        return super().get_by_role(role, name)

    def get_by_placeholder(self, text: str, exact: bool = False, **kwargs):
        key = f"placeholder:{text}:exact" if exact else f"placeholder:{text}"
        if key in self._selectors:
            return self._selectors[key]
        raise UnscriptedSelectorError(
            f"page: un-scripted get_by_placeholder({text!r}, exact={exact}); "
            f"scripted: {sorted(self._selectors)}"
        )

    def apply_key(self, key: str) -> None:
        if self.focused is not None:
            self.focused.apply_key(key)

    def apply_text(self, text: str) -> None:
        if self.focused is not None:
            self.focused.apply_text(text)


class _Sections(RecordingLocator):
    """``index_sectionFlex_`` 字段行替身：按 ``has`` 的 label 文本返回对应行。"""

    def __init__(self, name: str, *, log: list, rows: dict[str, FakeLocator]) -> None:
        super().__init__(name)
        self._rows = rows
        self._log = log

    def filter(self, **kwargs):
        self.filter_calls.append(dict(kwargs))
        label = getattr(kwargs.get("has"), "name", "")
        self._log.append(("filter", self.name, label))
        row = self._rows.get(label)
        if row is None:
            raise UnscriptedSelectorError(
                f"{self.name}: un-scripted field row {label!r}; "
                f"scripted rows: {sorted(self._rows)}"
            )
        return row


class _Options(RecordingLocator):
    """下拉展开后的选项容器：按精确文本取选项。"""

    def __init__(self, name: str, *, log: list, options: dict[str, FakeLocator]):
        super().__init__(name)
        self._options = options

    def get_by_text(self, text: str, exact: bool = False):
        if exact and text in self._options:
            return self._options[text]
        raise UnscriptedSelectorError(
            f"{self.name}: un-scripted get_by_text({text!r}, exact={exact}); "
            f"scripted: {sorted(self._options)}"
        )


class _Chooser(FakeFileChooser):
    """``set_input_files`` 之外还带 ``element.evaluate`` 清空旧文件的 double。"""

    def __init__(self, name: str = "xueqiu-chooser") -> None:
        super().__init__(name)
        self.element = SimpleNamespace(evaluate=self._reset)

    async def _reset(self, expression, arg=None):
        self.name = f"{self.name} reset"


def _attach(page: _Page, locator: FakeLocator) -> None:
    if isinstance(locator, (_TypingLocator, _Clickable)):
        locator._page = page
    for item in getattr(locator, "_items", None) or []:
        _attach(page, item)
    for child in getattr(locator, "_children", {}).values():
        _attach(page, child)


def _page(selectors: dict[str, FakeLocator], *, log: list | None = None, **kwargs) -> _Page:
    log = [] if log is None else log
    page = _Page(log=log, selectors=selectors, **kwargs)
    for locator in selectors.values():
        _attach(page, locator)
    return page


class _QuietHumanizer(xueqiu_article.Humanizer):
    """真实原语、固定停顿表、零墙钟。"""

    def __init__(self, page, *, profile=None, rng=None, sleep=None) -> None:
        self.pauses: list[float] = []
        log = getattr(page, "interactions", None)

        async def _record(seconds: float) -> None:
            self.pauses.append(round(seconds, 4))
            if log is not None:
                log.append(("pause", round(seconds, 4)))

        super().__init__(
            page, profile=TEST_PROFILE, rng=random.Random(0), sleep=_record
        )


class _Expect:
    """顺序记录用 expectation double；断言本身由 fake 的调用日志承担。"""

    def __init__(self, actual) -> None:
        self.actual = actual
        self.calls: list[str] = []

    @property
    def not_(self) -> "_Expect":
        return self

    def __getattr__(self, name):
        async def _record(*args, **kwargs):
            self.calls.append(name)
            return None

        return _record


def _expect(actual) -> _Expect:
    return _Expect(actual)


@contextmanager
def _humanized():
    with (
        patch.object(xueqiu_article, "Humanizer", _QuietHumanizer),
        patch.object(xueqiu_article, "expect", _expect),
        # 内容核对本身由 tests/test_xueqiu_uploader.py 的真浏览器用例覆盖。
        patch.object(xueqiu_article, "check_xueqiu_article_content", AsyncMock()),
    ):
        yield


def _document(parts, *, text=None):
    return SimpleNamespace(
        parts=parts,
        text=["正文"] if text is None else text,
        images=[],
        content_html="<p>正文</p>",
        manifest={},
        tags={},
        sequence=[],
        source_format="html",
        normalizations=[],
    )


def _article(tmp: str, **overrides) -> XueqiuArticle:
    values = {
        "title": TITLE,
        "content_file": Path(tmp) / "article.md",
        "account_file": Path(tmp) / "account.json",
        "visibility": VISIBILITY,
        "declaration": DECLARATION,
    }
    values.update(overrides)
    app = XueqiuArticle(
        values["title"],
        values["content_file"],
        values["account_file"],
        visibility=values["visibility"],
        declaration=values["declaration"],
        cover=values.get("cover"),
    )
    app.document = values.get("document") or _document(["正文"])
    app.uploaded_images = []
    app.cover_url = None
    return app


def _body_page(log: list, *, image: Path):
    """正文路径：编辑器 + 预览/工具栏/标题失焦 + 文件选择器。"""
    body = _Clickable("body", log=log, text="前文SAU_IMAGE_MARKER")
    inserted = _Clickable("body-image", log=log)
    body._children["img"] = FakeLocator("body-images", items=[inserted])
    toolbar = _Clickable("toolbar-upload", log=log)
    title_blur = _Clickable("title-blur", log=log)
    chooser = _Chooser()
    page = _page(
        {
            BODY: body,
            TOOLBAR_UPLOAD: toolbar,
            TITLE_PLACEHOLDER: title_blur,
        },
        log=log,
        evaluate_handler=lambda expression, arg: None,
        file_chooser=chooser,
    )
    return page, {"body": body, "toolbar": toolbar, "title_blur": title_blur,
                  "chooser": chooser, "inserted": inserted}


def _form_page(log: list, *, declaration_text: str, compact: Path | None = None):
    """填表路径：标题 + 两组下拉 + 预览入口与预览容器（可选封面裁剪）。"""
    title = _TypingLocator("title", log=log)
    body = _Clickable("editor-body", log=log)
    body._children["img"] = FakeLocator("editor-images", count=0)

    visibility_selected = _Clickable(
        "visibility-selected", log=log, text=VISIBILITY
    )
    declaration_selected = _Clickable(
        "declaration-selected", log=log, text="不添加创作声明"
    )
    declaration_option = _Clickable("declaration-option", log=log)

    visibility_row = FakeLocator(
        "visibility-row",
        children={SELECT_WRAP: visibility_selected, OPTION_CONTAINER: _Options(
            "visibility-options", log=log, options={VISIBILITY: _Clickable(
                "visibility-option", log=log)})},
    )
    declaration_row = FakeLocator(
        "declaration-row",
        children={SELECT_WRAP: declaration_selected, OPTION_CONTAINER: _Options(
            "declaration-options", log=log,
            options={declaration_text: declaration_option})},
    )
    rows = {"分享范围：": visibility_row, "创作声明：": declaration_row}
    crop_confirm = _Clickable("crop-confirm", log=log)
    if compact is not None:
        cover_input = _Clickable("cover-input", log=log)
        cover_preview = _Clickable("cover-preview", log=log)
        crop_image = _Clickable("crop-image", log=log)
        crop = _Clickable(
            "crop-modal",
            log=log,
            children={
                'img[alt="Crop"]': crop_image,
                CROP_CONFIRM: crop_confirm,
            },
        )
        rows["封面图片："] = FakeLocator(
            "cover-row",
            children={
                'input[type="file"]': cover_input,
                'div[class*="index_input-cover-pic-btn_"]': cover_preview,
            },
        )
    else:
        cover_input = cover_preview = crop_image = crop = None
    sections = _Sections("field-sections", log=log, rows=rows)
    preview = FakeLocator(
        "preview",
        children={
            "h1": FakeLocator("preview-title"),
            'div[class*="index_content-text_"] > div': FakeLocator("preview-body"),
            'div[class*="index_content-text_"] > div img': FakeLocator(
                "preview-images", count=0
            ),
            'div[class*="index_content-text_"] > img[class*="index_first-pic_"]':
                _Clickable("preview-cover", log=log),
        },
    )
    preview_button = _Clickable("preview-button", log=log)
    page = _page(
        {
            TITLE_PLACEHOLDER: title,
            BODY: body,
            SECTIONS: sections,
            "text:分享范围：:exact": FakeLocator("分享范围："),
            "text:创作声明：:exact": FakeLocator("创作声明："),
            "text:封面图片：:exact": FakeLocator("封面图片："),
            "text:选择封面图片:exact": FakeLocator("选择封面图片"),
            'div[class*="modal_modal-content_"]': _Sections(
                "crop-modals", log=log, rows={"选择封面图片": crop},
            ),
            PUBLISH_STATE: FakeLocator("publish-state"),
            PREVIEW_BUTTON: preview_button,
            PREVIEW_CONTENT: preview,
        },
        log=log,
        evaluate_handler=lambda expression, arg: None,
    )
    return page, {
        "title": title,
        "body": body,
        "visibility_selected": visibility_selected,
        "declaration_selected": declaration_selected,
        "declaration_option": declaration_option,
        "preview_button": preview_button,
        "crop_confirm": crop_confirm,
        "cover_input": cover_input,
        "cover_preview": cover_preview,
        "crop_image": crop_image,
    }


# ---------------------------------------------------------------------------
# 1. 事件序列
# ---------------------------------------------------------------------------


class HumanizeEventSequenceTests(unittest.TestCase):
    def test_body_focus_and_toolbar_upload_are_humanized_while_blur_stays_native(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "shot.png"
            image.write_bytes(b"png")
            app = _article(tmp, document=_document(["前文", image]))
            log: list = []
            page, parts = _body_page(log, image=image)

            with _humanized():
                asyncio.run(app.fill_article_body(page, parts["body"], multilogin=True))

            # 正文聚焦与工具栏「上传图片」走坐标点击；两次失焦标题保持原生。
            self.assertEqual(page.mouse.down_count, 2)
            self.assertEqual(parts["body"].click_count, 0)
            self.assertEqual(parts["toolbar"].click_count, 0)
            self.assertEqual(parts["title_blur"].click_count, 2)
            self.assertIn(("evaluate", "hit-test", "body"), log)
            self.assertIn(("evaluate", "hit-test", "toolbar-upload"), log)
            # 粘贴 HTML 与文件选择仍走原生路径。
            self.assertIn(("press", "Meta+V" if sys.platform == "darwin" else "Control+V"),
                          parts["body"].actions)
            self.assertEqual(page.file_chooser_files(), [str(image)])
            # 正文没有被人为清空或改写：粘贴文本 + 唯一标记仍在缓冲里。
            self.assertIn("SAU_IMAGE", asyncio.run(parts["body"].inner_text()))

    def test_form_reads_dropdown_state_before_clicking_and_humanizes_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _article(tmp)
            app.fill_article_body = AsyncMock()
            log: list = []
            page, parts = _form_page(log, declaration_text=DECLARATION)

            with _humanized():
                asyncio.run(app.fill_article_form(page, multilogin=True))

            # 标题 none 形态：只聚焦后逐字输入，零清空键。
            self.assertEqual(
                page.keyboard.actions,
                [("insert_text", char) for char in TITLE],
            )
            # 分享范围已是目标值：先读状态后跳过，未点下拉也未点选项。
            self.assertEqual(parts["visibility_selected"].reads, 1)
            self.assertEqual(parts["visibility_selected"].click_count, 0)
            # 创作声明不同：读状态 → 点下拉 → 点精确文本选项。
            self.assertEqual(parts["declaration_selected"].reads, 1)
            self.assertIn(("inner_text", "declaration-selected"), log)
            self.assertEqual(parts["declaration_selected"].click_count, 0)
            self.assertEqual(parts["declaration_option"].click_count, 0)
            self.assertEqual(parts["preview_button"].click_count, 0)
            # 标题、声明下拉、声明选项、预览：四次坐标点击。
            self.assertEqual(page.mouse.down_count, 4)
            self.assertIn(("evaluate", "hit-test", "declaration-option"), log)
            self.assertIn(("evaluate", "hit-test", "preview-button"), log)
            self.assertEqual(app._humanizer_instance.pauses.count(AFTER_TYPE), 1)

    def test_cover_crop_confirm_is_humanized_while_selection_stays_native(self):
        with tempfile.TemporaryDirectory() as tmp:
            cover = Path(tmp) / "cover.png"
            cover.write_bytes(b"png")
            app = _article(tmp, cover=cover)
            app.fill_article_body = AsyncMock()
            log: list = []
            page, parts = _form_page(log, declaration_text=DECLARATION, compact=cover)

            with _humanized():
                asyncio.run(app.fill_article_form(page, multilogin=True))

            # 封面文件仍走原生 set_input_files；裁剪确认是坐标点击。
            self.assertEqual(
                parts["cover_input"].actions,
                [("set_input_files", [str(app.cover)])],
            )
            self.assertEqual(parts["crop_confirm"].click_count, 0)
            self.assertIn(("evaluate", "hit-test", "crop-confirm"), log)
            self.assertEqual(app.cover_url, "https://xqimg.imedao.com/cover.png")
            # 标题、裁剪确认、声明下拉、声明选项、预览：五次坐标点击。
            self.assertEqual(page.mouse.down_count, 5)

    def test_preview_overlay_closes_with_a_coordinate_click(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _article(tmp)
            log: list = []
            close = _Clickable("preview-close", log=log)
            page = _page(
                {PREVIEW_CLOSE: close, PREVIEW_CONTENT: FakeLocator("preview-content")},
                log=log,
            )

            with _humanized():
                asyncio.run(app._close_preview(page))

            self.assertEqual(page.mouse.down_count, 1)
            self.assertEqual(close.click_count, 0)
            self.assertIn(("evaluate", "hit-test", "preview-close"), log)
            # 遮罩节点不被删除、不被强点：只有坐标点击 + 隐藏断言。
            self.assertEqual(close.actions, [])

    def test_publish_waits_before_submit_then_humanizes_the_click(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _article(tmp)
            log: list = []
            publish = _Clickable("publish", log=log)
            page = _page({PUBLISH_BUTTON: publish}, log=log)

            with _humanized():
                asyncio.run(app._submit(page, publish))

            self.assertEqual(page.mouse.down_count, 1)
            self.assertEqual(publish.click_count, 0)
            self.assertLess(log.index(("pause", BEFORE_SUBMIT)), log.index(("down",)))
            self.assertLess(
                log.index(("evaluate", "hit-test", "publish")), log.index(("down",))
            )


class SubmitDispatchGuardTests(unittest.TestCase):
    """提交点：``mouse.down`` 之后失败 = 结果未知（退出 9），绝不二次派发。"""

    def _maybe_error(self) -> RuntimeError:
        exc = RuntimeError("mouse up failed")
        setattr(exc, MAYBE_DISPATCHED, MAYBE_DISPATCHED_VALUE)
        return exc

    def _run(self, error: BaseException) -> list:
        """Run the submit point once with a failing click; return the click log."""
        with tempfile.TemporaryDirectory() as tmp:
            app = _article(tmp)
            app._publish_budget = PublishTimeoutBudget("雪球")
            log: list = []
            publish = _Clickable("publish", log=log)
            page = _page({PUBLISH_BUTTON: publish}, log=log)

            class _Failing(_QuietHumanizer):
                async def click(self, locator, *, point=None) -> None:
                    raise error

            with patch.object(xueqiu_article, "Humanizer", _Failing):
                asyncio.run(app._submit(page, publish))
        # The humanizer fake never reaches its own coordinate click: one attempt only.
        return publish.click_calls

    def test_maybe_dispatched_submit_failure_maps_to_result_unknown(self):
        with self.assertRaises(PublishResultUnknownError):
            self._run(self._maybe_error())

    def test_pre_dispatch_submit_failure_propagates(self):
        error = ElementUnusableError(
            what="点击目标",
            role="interactive",
            selector="",
            reason="covered-by:mask",
            publish_clicked=False,
        )

        with self.assertRaises(ElementUnusableError) as caught:
            self._run(error)

        self.assertIs(caught.exception, error)


# ---------------------------------------------------------------------------
# 2. 字段值读回
# ---------------------------------------------------------------------------


class HumanizeFieldReadbackTests(unittest.TestCase):
    def test_title_is_typed_into_the_empty_field_without_clearing(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _article(tmp)
            app.fill_article_body = AsyncMock()
            log: list = []
            page, parts = _form_page(log, declaration_text=DECLARATION)

            with _humanized():
                asyncio.run(app.fill_article_form(page, multilogin=True))

            # 逐字符写入后值完全相等；没有 ControlOrMeta+A / Delete 清空键。
            self.assertEqual(parts["title"].buffer, TITLE)
            self.assertEqual(
                [action for action in page.keyboard.actions
                 if action[0] == "press"],
                [],
            )

    def test_title_guard_refuses_to_overwrite_an_existing_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _article(tmp)
            app.fill_article_body = AsyncMock()
            log: list = []
            page, parts = _form_page(log, declaration_text=DECLARATION)
            parts["title"].buffer = "已有草稿"

            with _humanized(), self.assertRaisesRegex(RuntimeError, "已有内容"):
                asyncio.run(app.fill_article_form(page, multilogin=True))

            # 守卫在输入前停工：既不清空也不追加，也没有任何点击。
            self.assertEqual(page.keyboard.actions, [])
            self.assertEqual(page.mouse.down_count, 0)
            self.assertEqual(parts["title"].click_count, 0)
            self.assertEqual(parts["title"].buffer, "已有草稿")


# ---------------------------------------------------------------------------
# HUMANIZE=0 快路径
# ---------------------------------------------------------------------------


class HumanizeDisabledTests(unittest.TestCase):
    def test_form_inserts_once_per_field_and_clicks_natively(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _article(tmp)
            app.fill_article_body = AsyncMock()
            log: list = []
            page, parts = _form_page(log, declaration_text=DECLARATION)

            with _humanized(), patch.dict(os.environ, {"HUMANIZE": "0"}):
                asyncio.run(app.fill_article_form(page, multilogin=True))

            self.assertEqual(
                page.keyboard.actions, [("insert_text", TITLE)]
            )
            self.assertEqual(app._humanizer_instance.pauses, [])
            self.assertEqual(page.mouse.down_count, 0)
            for name in ("title", "declaration_selected", "declaration_option",
                         "preview_button"):
                self.assertEqual(parts[name].click_count, 1, name)
            self.assertEqual(parts["visibility_selected"].click_count, 0)
            self.assertEqual(parts["title"].buffer, TITLE)

    def test_publish_clicks_once_without_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _article(tmp)
            log: list = []
            publish = _Clickable("publish", log=log)
            page = _page({PUBLISH_BUTTON: publish}, log=log)

            with _humanized(), patch.dict(os.environ, {"HUMANIZE": "0"}):
                asyncio.run(app._submit(page, publish))

            self.assertEqual(publish.click_count, 1)
            self.assertEqual(page.mouse.down_count, 0)
            self.assertEqual(app._humanizer_instance.pauses, [])


# ---------------------------------------------------------------------------
# 3. 平台静态门
# ---------------------------------------------------------------------------


class HumanizeGateTests(unittest.TestCase):
    def test_xueqiu_package_passes_gates_a_to_e(self):
        package = (
            Path(__file__).resolve().parent.parent
            / "uploader"
            / "xueqiu_uploader"
        )
        assert_clean(package)


if __name__ == "__main__":
    unittest.main()
