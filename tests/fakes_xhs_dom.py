# -*- coding: utf-8 -*-
"""Scripted DOM doubles for the XHS publish-chain tests (ticket 28).

These fakes are deliberately **fail-loudly**: asking the page (or a locator) for
a selector that the test did not script raises :class:`UnscriptedSelectorError`
instead of silently returning ``count == 0``.  A silent zero would make a real
selector drift look like "the element was not there", which is exactly the
failure mode this effort is trying to make visible.

They are async and ``unittest``-friendly: no new third-party dependency, no
browser, no network.  Every interaction the publish chain (ARM / FIRE /
OBSERVE) cares about is recorded so tests can assert "exactly once", "zero
times", and the exact timeout passed to every ``wait_for_*`` call.

Public API
----------

``FakeLocator`` / ``RecordingLocator``
    Scripted element.  ``count`` / ``first`` / ``last`` / ``nth`` /
    ``get_attribute`` / ``is_visible`` / ``is_enabled`` / ``inner_text`` /
    ``text_content`` / ``evaluate`` (computed style) / ``locator`` (children).
    Interactions are appended to ``actions``; ``click_count`` counts clicks.

``RecordingPage``
    Page double with writable ``url`` and ``main_frame.url``.  Records
    ``goto_calls``, ``evaluate_calls``, ``screenshot_calls`` and every
    ``wait_for_*`` call (with its ``timeout`` argument) in ``wait_calls``.
    ``page.mouse`` and ``page.keyboard`` record their own ``actions``.

Scripting convention::

    page = RecordingPage(
        url="https://creator.xiaohongshu.com/publish/publish",
        selectors={
            "#publish-btn": RecordingLocator("publish"),
            "div.d-input input": FakeLocator("title", attributes={"value": "T"}),
            "text:发布": RecordingLocator("publish-label"),
            "role:button:确认": RecordingLocator("confirm"),
        },
        evaluate_results=[...],       # consumed in order by page.evaluate()
        hit_test_target="publish-btn",  # returned for elementFromPoint calls
    )
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

_UNSET = object()


class UnscriptedSelectorError(AssertionError):
    """Raised when a test asks for a selector it never scripted."""


class UnscriptedEvaluationError(AssertionError):
    """Raised when ``evaluate`` has no scripted result and no handler."""


@dataclass(frozen=True)
class RecordedWait:
    """One ``wait_for_*`` call, with the timeout argument made explicit."""

    method: str
    timeout: float | int | None
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)


class FakeLocator:
    """Scripted Playwright ``Locator`` double.

    ``count`` defaults to 1 for locators a test explicitly scripted; pass
    ``count=0`` for an absent element.  ``items`` backs ``first`` / ``last`` /
    ``nth``; a nested selector must be registered in ``children``.
    """

    def __init__(
        self,
        name: str = "",
        *,
        count: int | None = None,
        attributes: dict[str, Any] | None = None,
        visible: bool = True,
        enabled: bool = True,
        computed_style: dict[str, Any] | None = None,
        text: str = "",
        children: dict[str, "FakeLocator"] | None = None,
        items: list["FakeLocator"] | None = None,
        click_error: BaseException | None = None,
        fill_error: BaseException | None = None,
        wait_error: BaseException | None = None,
        evaluate_result: Any = _UNSET,
        evaluate_handler: Callable[..., Any] | None = None,
        box: dict[str, float] | None = None,
        page: "RecordingPage | None" = None,
    ) -> None:
        self.name = name or "locator"
        self._count = count
        self._attributes = dict(attributes or {})
        self._visible = visible
        self._enabled = enabled
        self._computed_style = computed_style
        self._text = text
        self._children = dict(children or {})
        self._items = items
        self._click_error = click_error
        self._fill_error = fill_error
        self._wait_error = wait_error
        self._evaluate_result = evaluate_result
        self._evaluate_handler = evaluate_handler
        self._box = box
        self._page = page

        self.actions: list[tuple[Any, ...]] = []
        self.click_count = 0
        self.click_calls: list[dict[str, Any]] = []
        self.filter_calls: list[dict[str, Any]] = []
        self.evaluate_calls: list[tuple[Any, Any]] = []
        self.wait_calls: list[RecordedWait] = []
        self.screenshot_calls: list[dict[str, Any]] = []

    # -- structure ---------------------------------------------------------
    @property
    def first(self) -> "FakeLocator":
        if self._items:
            return self._items[0]
        return self

    @property
    def last(self) -> "FakeLocator":
        if self._items:
            return self._items[-1]
        return self

    def nth(self, index: int) -> "FakeLocator":
        if self._items is not None:
            try:
                return self._items[index]
            except IndexError as exc:
                raise IndexError(
                    f"{self.name}: nth({index}) has no scripted item "
                    f"(items={len(self._items)})"
                ) from exc
        if 0 <= index < self._scripted_count():
            return self
        raise IndexError(
            f"{self.name}: nth({index}) has no scripted item "
            f"(count={self._scripted_count()})"
        )

    def locator(self, selector: str) -> "FakeLocator":
        try:
            return self._children[selector]
        except KeyError as exc:
            raise UnscriptedSelectorError(
                f"{self.name}: un-scripted child selector {selector!r}; "
                f"scripted children: {sorted(self._children)}"
            ) from exc

    def get_by_text(self, text: str, exact: bool = False) -> "FakeLocator":
        keys = [f"text:{text}:exact"] if exact else [f"text:{text}"]
        for key in keys:
            if key in self._children:
                return self._children[key]
        raise UnscriptedSelectorError(
            f"{self.name}: un-scripted get_by_text({text!r}, exact={exact}); "
            f"scripted children: {sorted(self._children)}"
        )

    def get_by_role(
        self, role: str, name: str | None = None
    ) -> "FakeLocator":
        key = f"role:{role}" if name is None else f"role:{role}:{name}"
        if key in self._children:
            return self._children[key]
        raise UnscriptedSelectorError(
            f"{self.name}: un-scripted get_by_role({role!r}, name={name!r}); "
            f"scripted children: {sorted(self._children)}"
        )

    def filter(self, **kwargs: Any) -> "FakeLocator":
        self.filter_calls.append(dict(kwargs))
        return self

    # -- read state --------------------------------------------------------
    def _scripted_count(self) -> int:
        if self._count is not None:
            return self._count
        if self._items is not None:
            return len(self._items)
        return 1

    async def count(self) -> int:
        return self._scripted_count()

    async def get_attribute(self, name: str) -> Any:
        return self._attributes.get(name)

    async def is_visible(self) -> bool:
        return self._visible

    async def is_enabled(self) -> bool:
        return self._enabled

    async def inner_text(self) -> str:
        return self._text

    async def text_content(self) -> str:
        return self._text

    async def bounding_box(self) -> dict[str, float] | None:
        return self._box

    async def evaluate(self, expression: Any, arg: Any = None) -> Any:
        self.evaluate_calls.append((expression, arg))
        if self._evaluate_handler is not None:
            result = self._evaluate_handler(expression, arg)
            return await result if inspect.isawaitable(result) else result
        if self._computed_style is not None:
            return self._computed_style
        if self._evaluate_result is not _UNSET:
            return self._evaluate_result
        raise UnscriptedEvaluationError(
            f"{self.name}: un-scripted locator.evaluate({expression!r}); "
            "pass computed_style=..., evaluate_result=... or evaluate_handler=..."
        )

    # -- interactions ------------------------------------------------------
    async def wait_for(self, **kwargs: Any) -> None:
        self.wait_calls.append(
            RecordedWait("wait_for", kwargs.get("timeout"), (), dict(kwargs))
        )
        self.actions.append(("wait_for", dict(kwargs)))
        if self._wait_error is not None:
            raise self._wait_error

    async def fill(self, value: str, **kwargs: Any) -> None:
        self.actions.append(("fill", value))
        if self._fill_error is not None:
            raise self._fill_error

    async def focus(self, **kwargs: Any) -> None:
        self.actions.append(("focus",))

    async def click(self, **kwargs: Any) -> None:
        # Count the attempt *before* dispatch: FIRE must be able to tell
        # "never dispatched" from "dispatch raised" (spec U2).
        self.click_count += 1
        self.click_calls.append(dict(kwargs))
        self.actions.append(("click",))
        if self._click_error is not None:
            raise self._click_error

    async def press(self, key: str, **kwargs: Any) -> None:
        self.actions.append(("press", key))

    async def type(self, text: str, delay: float | None = None, **kwargs: Any) -> None:
        self.actions.append(("type", text, delay))

    async def screenshot(self, **kwargs: Any) -> None:
        self.screenshot_calls.append(dict(kwargs))

    # -- assertions --------------------------------------------------------
    def assert_clicked_once(self) -> None:
        if self.click_count != 1:
            raise AssertionError(
                f"{self.name}: expected exactly 1 click, got {self.click_count}"
            )

    def assert_never_clicked(self) -> None:
        if self.click_count != 0:
            raise AssertionError(
                f"{self.name}: expected zero clicks, got {self.click_count}"
            )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"{type(self).__name__}({self.name!r}, count={self._scripted_count()}, "
            f"clicks={self.click_count})"
        )


class RecordingLocator(FakeLocator):
    """Explicitly named locator double; ``click`` counts attempts."""


def preview_tiles(count: int = 1) -> FakeLocator:
    """A ready ``.img-preview-area .pr`` set (ticket 38 upload gate).

    ``count`` tiles exist and none of them carries ``.mask.uploading``; use
    :func:`preview_tiles_uploading` when one tile must still look in-progress.
    """
    return FakeLocator(
        "preview-tiles",
        items=[
            FakeLocator(
                f"tile-{index}",
                children={".mask.uploading": FakeLocator("mask", count=0)},
            )
            for index in range(count)
        ],
    )


def preview_tiles_uploading(index: int, *, count: int = 1) -> FakeLocator:
    """``preview_tiles`` where tile ``index`` still shows the uploading mask."""
    tiles = preview_tiles(count)
    tiles._items[index]._children[".mask.uploading"] = FakeLocator(
        "mask", count=1
    )
    return tiles


class RecordingMouse:
    """Scripted ``page.mouse``; ``down_count`` proves how many dispatches ran."""

    def __init__(self) -> None:
        self.actions: list[tuple[Any, ...]] = []
        self.down_count = 0
        self.up_count = 0

    async def move(self, x: float, y: float, **kwargs: Any) -> None:
        self.actions.append(("move", x, y))

    async def down(self, **kwargs: Any) -> None:
        self.actions.append(("down",))
        self.down_count += 1

    async def up(self, **kwargs: Any) -> None:
        self.actions.append(("up",))
        self.up_count += 1

    async def click(
        self, x: float | None = None, y: float | None = None, **kwargs: Any
    ) -> None:
        if x is None and y is None:
            self.actions.append(("click",))
        else:
            self.actions.append(("click", x, y))

    async def dblclick(
        self, x: float | None = None, y: float | None = None, **kwargs: Any
    ) -> None:
        self.actions.append(("dblclick", x, y))

    async def wheel(self, delta_x: float, delta_y: float, **kwargs: Any) -> None:
        self.actions.append(("wheel", delta_x, delta_y))


class RecordingKeyboard:
    """Scripted ``page.keyboard`` recording press/type/insert_text ordering."""

    def __init__(self) -> None:
        self.actions: list[tuple[Any, ...]] = []

    async def press(self, key: str, **kwargs: Any) -> None:
        self.actions.append(("press", key))

    async def type(
        self, text: str, delay: float | None = None, **kwargs: Any
    ) -> None:
        self.actions.append(("type", text, delay))

    async def insert_text(self, text: str, **kwargs: Any) -> None:
        self.actions.append(("insert_text", text))

    async def down(self, key: str, **kwargs: Any) -> None:
        self.actions.append(("down", key))

    async def up(self, key: str, **kwargs: Any) -> None:
        self.actions.append(("up", key))


class RecordingFrame:
    """Minimal ``MainFrame`` double with a writable ``url``."""

    def __init__(self, page: "RecordingPage", url: str) -> None:
        self._page = page
        self.url = url

    def locator(self, selector: str) -> FakeLocator:
        return self._page.locator(selector)


class FakeFileChooser:
    """Scripted ``FileChooser``: records every ``set_files`` payload.

    A ``+`` tile click is the only way the publish chain can add an image, so
    ``files`` proves exactly which single path went through the chooser.
    """

    def __init__(self, name: str = "file-chooser") -> None:
        self.name = name
        self.files: list[object] = []
        self.set_files_error: BaseException | None = None

    async def set_files(self, files, **kwargs: Any) -> None:
        self.files.append(files)
        if self.set_files_error is not None:
            raise self.set_files_error


class _FileChooserInfo:
    """``page.expect_file_chooser()`` async context manager double."""

    def __init__(self, page: "RecordingPage") -> None:
        self._page = page

    async def __aenter__(self) -> "_FileChooserInfo":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    @property
    def value(self):
        async def _resolve() -> FakeFileChooser:
            error = self._page.fail_file_chooser
            if error is not None:
                raise error
            chooser = self._page.file_chooser
            if chooser is None:
                raise AssertionError("page: no file chooser scripted")
            return chooser

        return _resolve()


class RecordingPage:
    """Scripted Playwright ``Page`` double that records every interaction."""

    def __init__(
        self,
        *,
        url: str = "about:blank",
        main_frame_url: str | None = None,
        selectors: dict[str, FakeLocator] | None = None,
        evaluate_results: list[Any] | None = None,
        evaluate_handler: Callable[..., Any] | None = None,
        hit_test_target: Any = _UNSET,
        screenshot_error: BaseException | None = None,
        file_chooser: FakeFileChooser | None = None,
    ) -> None:
        self.url = url
        self.main_frame = RecordingFrame(
            self, url if main_frame_url is None else main_frame_url
        )
        self.mouse = RecordingMouse()
        self.keyboard = RecordingKeyboard()
        self._selectors = dict(selectors or {})
        self._evaluate_results = list(evaluate_results or [])
        self._evaluate_handler = evaluate_handler
        self._hit_test_target = hit_test_target
        self._screenshot_error = screenshot_error
        self.file_chooser = file_chooser or FakeFileChooser()
        self.fail_file_chooser: BaseException | None = None
        self.expect_file_chooser_calls = 0

        self.goto_calls: list[tuple[str, dict[str, Any]]] = []
        self.evaluate_calls: list[tuple[Any, Any]] = []
        self.screenshot_calls: list[dict[str, Any]] = []
        self.wait_calls: list[RecordedWait] = []
        self.events: list[tuple[Any, ...]] = []
        self.closed = False

    # -- selectors ---------------------------------------------------------
    def locator(self, selector: str) -> FakeLocator:
        try:
            return self._selectors[selector]
        except KeyError as exc:
            raise UnscriptedSelectorError(
                f"page: un-scripted selector {selector!r}; "
                f"scripted: {sorted(self._selectors)}"
            ) from exc

    def get_by_text(self, text: str, exact: bool = False) -> FakeLocator:
        key = f"text:{text}:exact" if exact else f"text:{text}"
        if key in self._selectors:
            return self._selectors[key]
        raise UnscriptedSelectorError(
            f"page: un-scripted get_by_text({text!r}, exact={exact}); "
            f"scripted: {sorted(self._selectors)}"
        )

    def get_by_role(
        self, role: str, name: str | None = None
    ) -> FakeLocator:
        key = f"role:{role}" if name is None else f"role:{role}:{name}"
        if key in self._selectors:
            return self._selectors[key]
        raise UnscriptedSelectorError(
            f"page: un-scripted get_by_role({role!r}, name={name!r}); "
            f"scripted: {sorted(self._selectors)}"
        )

    # -- navigation / evaluation ------------------------------------------
    async def goto(self, url: str, **kwargs: Any) -> None:
        self.goto_calls.append((url, dict(kwargs)))
        self.events.append(("goto", url))
        self.url = url
        self.main_frame.url = url

    async def evaluate(self, expression: Any, arg: Any = None) -> Any:
        self.evaluate_calls.append((expression, arg))
        self.events.append(("evaluate", expression))
        if self._evaluate_handler is not None:
            result = self._evaluate_handler(expression, arg)
            return await result if inspect.isawaitable(result) else result
        if (
            isinstance(expression, str)
            and "elementFromPoint" in expression
            and self._hit_test_target is not _UNSET
        ):
            return self._hit_test_target
        if self._evaluate_results:
            outcome = self._evaluate_results.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        raise UnscriptedEvaluationError(
            f"page: un-scripted page.evaluate({expression!r}); "
            "queue evaluate_results=..., pass hit_test_target=... or "
            "evaluate_handler=..."
        )

    async def screenshot(self, **kwargs: Any) -> None:
        self.screenshot_calls.append(dict(kwargs))
        self.events.append(("screenshot",))
        if self._screenshot_error is not None:
            raise self._screenshot_error

    async def close(self) -> None:
        self.closed = True
        self.events.append(("close",))

    # -- waits -------------------------------------------------------------
    def _record_wait(
        self,
        method: str,
        timeout: float | int | None,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.wait_calls.append(
            RecordedWait(method, timeout, args, dict(kwargs or {}))
        )
        self.events.append((method, timeout))

    async def wait_for_timeout(self, milliseconds: float) -> None:
        self._record_wait("wait_for_timeout", milliseconds, (milliseconds,))

    async def wait_for_selector(
        self,
        selector: str,
        *,
        state: str | None = None,
        timeout: float | int | None = None,
        **kwargs: Any,
    ) -> FakeLocator:
        self._record_wait(
            "wait_for_selector",
            timeout,
            (selector,),
            {"state": state, **kwargs},
        )
        return self.locator(selector)

    async def wait_for_url(
        self,
        url: Any,
        *,
        timeout: float | int | None = None,
        **kwargs: Any,
    ) -> None:
        self._record_wait("wait_for_url", timeout, (url,), dict(kwargs))

    async def wait_for_load_state(
        self,
        state: str | None = None,
        *,
        timeout: float | int | None = None,
        **kwargs: Any,
    ) -> None:
        self._record_wait(
            "wait_for_load_state", timeout, (state,), dict(kwargs)
        )

    async def wait_for_function(
        self,
        expression: Any,
        arg: Any = None,
        *,
        timeout: float | int | None = None,
        **kwargs: Any,
    ) -> None:
        self._record_wait(
            "wait_for_function", timeout, (expression, arg), dict(kwargs)
        )

    async def wait_for_event(
        self,
        event: str,
        *,
        timeout: float | int | None = None,
        **kwargs: Any,
    ) -> None:
        self._record_wait("wait_for_event", timeout, (event,), dict(kwargs))

    def expect_file_chooser(
        self, *, timeout: float | int | None = None
    ) -> _FileChooserInfo:
        """Return the chooser async-context double for a ``+`` tile click."""
        self.expect_file_chooser_calls += 1
        self._record_wait("expect_file_chooser", timeout, (), {})
        return _FileChooserInfo(self)

    def file_chooser_files(self) -> list[object]:
        """Every payload passed to ``FileChooser.set_files``."""
        return list(self.file_chooser.files)

    def timeouts(self, method: str | None = None) -> list[float | int | None]:
        """Every recorded timeout, optionally filtered by method name."""
        return [
            call.timeout
            for call in self.wait_calls
            if method is None or call.method == method
        ]
