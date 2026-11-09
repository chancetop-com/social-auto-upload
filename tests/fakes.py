"""Hand-written async test doubles for ``utils.browser_session``.

The fakes deliberately fail loudly (``AssertionError``) when production code
touches an API that the Multilogin branch must never use.  They also record the
calls that *are* allowed so tests can assert exact parameters and ordering.
"""

from __future__ import annotations

import json
from typing import Any


class ForbiddenApiError(AssertionError):
    """Raised when production code calls an API that is forbidden in tests."""


class FakePage:
    def __init__(self, *, events: list[str] | None = None) -> None:
        self.url = "about:blank"
        self.closed = False
        self.events = events if events is not None else []
        self.goto_calls: list[tuple[str, dict[str, Any]]] = []

    async def goto(self, url: str, **kwargs: Any) -> None:
        self.url = url
        self.goto_calls.append((url, kwargs))

    async def close(self) -> None:
        self.closed = True


class FakeContext:
    """Minimal ``BrowserContext`` double.

    ``new_page``, ``storage_state`` and ``add_init_script`` are allowed because
    the local branch legitimately uses them.  Every other API from the MLX
    forbidden list raises :class:`ForbiddenApiError` immediately.
    """

    def __init__(
        self,
        *,
        pages: list[FakePage] | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.pages: list[FakePage] = list(pages or [])
        self.events = events if events is not None else []
        self.closed = False
        self.close_error: BaseException | None = None
        self.storage_state_error: BaseException | None = None
        self.storage_state_calls: list[Any] = []
        self.add_init_script_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.new_page_calls = 0
        self.forbidden_calls: list[str] = []

    async def new_page(self) -> FakePage:
        self.new_page_calls += 1
        page = FakePage(events=self.events)
        self.pages.append(page)
        return page

    async def storage_state(self, *, path: Any = None, **kwargs: Any) -> dict[str, Any]:
        self.storage_state_calls.append(path)
        if self.storage_state_error is not None:
            raise self.storage_state_error
        return {"cookies": [], "origins": []}

    async def add_init_script(self, *args: Any, **kwargs: Any) -> None:
        self.add_init_script_calls.append((args, kwargs))

    async def close(self) -> None:
        if self.close_error is not None:
            raise self.close_error
        self.closed = True
        self.events.append("context.close")

    async def _forbidden(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.forbidden_calls.append(name)
        raise ForbiddenApiError(f"{name} is forbidden in this context")

    async def add_cookies(self, *args: Any, **kwargs: Any) -> None:
        await self._forbidden("add_cookies", *args, **kwargs)

    async def clear_cookies(self, *args: Any, **kwargs: Any) -> None:
        await self._forbidden("clear_cookies", *args, **kwargs)

    async def route(self, *args: Any, **kwargs: Any) -> None:
        await self._forbidden("route", *args, **kwargs)

    async def grant_permissions(self, *args: Any, **kwargs: Any) -> None:
        await self._forbidden("grant_permissions", *args, **kwargs)

    async def set_geolocation(self, *args: Any, **kwargs: Any) -> None:
        await self._forbidden("set_geolocation", *args, **kwargs)

    async def set_extra_http_headers(self, *args: Any, **kwargs: Any) -> None:
        await self._forbidden("set_extra_http_headers", *args, **kwargs)

    async def emulate_media(self, *args: Any, **kwargs: Any) -> None:
        await self._forbidden("emulate_media", *args, **kwargs)

    async def set_viewport_size(self, *args: Any, **kwargs: Any) -> None:
        await self._forbidden("set_viewport_size", *args, **kwargs)


class FakeBrowser:
    """Minimal ``Browser`` double.

    ``new_context`` / ``new_page`` are only enabled when explicitly allowed; the
    default (MLX mode) rejects them with :class:`ForbiddenApiError`.
    """

    def __init__(
        self,
        contexts: list[FakeContext] | None = None,
        *,
        allow_new_context: bool = False,
        events: list[str] | None = None,
    ) -> None:
        self.contexts: list[FakeContext] = list(contexts or [])
        self.events = events if events is not None else []
        self.allow_new_context = allow_new_context
        self.closed = False
        self.close_calls = 0
        self.close_error: BaseException | None = None
        self.new_context_calls: list[dict[str, Any]] = []
        self.forbidden_calls: list[str] = []

    async def new_context(self, **kwargs: Any) -> FakeContext:
        self.new_context_calls.append(kwargs)
        if not self.allow_new_context:
            self.forbidden_calls.append("new_context")
            raise ForbiddenApiError("browser.new_context is forbidden")
        context = FakeContext(events=self.events)
        self.contexts.append(context)
        return context

    async def new_page(self, *args: Any, **kwargs: Any) -> FakePage:
        self.forbidden_calls.append("new_page")
        raise ForbiddenApiError("browser.new_page is forbidden")

    async def close(self) -> None:
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error
        self.closed = True
        self.events.append("browser.close")


class FakeBrowserType:
    """``playwright.chromium`` double for both ``launch`` and ``connect_over_cdp``."""

    def __init__(self, *, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self.launch_calls: list[dict[str, Any]] = []
        self.connect_calls: list[dict[str, Any]] = []
        self.launch_browser: FakeBrowser | None = None
        self.launch_error: BaseException | None = None
        self._connect_outcomes: list[Any] = []

    def new_browser(self, contexts: list[FakeContext] | None = None) -> FakeBrowser:
        return FakeBrowser(
            contexts,
            allow_new_context=True,
            events=self.events,
        )

    def queue_connect_browser(self, browser: FakeBrowser) -> None:
        self._connect_outcomes.append(browser)

    def queue_connect_error(self, error: BaseException) -> None:
        self._connect_outcomes.append(error)

    async def launch(self, **kwargs: Any) -> FakeBrowser:
        self.launch_calls.append(dict(kwargs))
        self.events.append("launch")
        if self.launch_error is not None:
            raise self.launch_error
        if self.launch_browser is None:
            self.launch_browser = self.new_browser()
        return self.launch_browser

    async def connect_over_cdp(self, url: str, **kwargs: Any) -> FakeBrowser:
        self.connect_calls.append({"url": url, **kwargs})
        self.events.append("connect")
        if not self._connect_outcomes:
            raise AssertionError("connect_over_cdp called with no queued outcome")
        outcome = self._connect_outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakePlaywright:
    """``Playwright`` double exposing only ``chromium``."""

    def __init__(self, *, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self.chromium = FakeBrowserType(events=self.events)


class FakeManagedProvider:
    """Duck-typed ``ManagedBrowserProvider`` for lifecycle tests."""

    def __init__(
        self,
        *,
        mode: str = "multilogin",
        profile_id: str = "profile",
        connect_url: str = "http://127.0.0.1:55513",
        probe_error: BaseException | None = None,
        start_error: BaseException | None = None,
        status_error: BaseException | None = None,
        status_value: str = "running",
        stop_error: BaseException | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.mode = mode
        self.profile_id = profile_id
        self.connect_url = connect_url
        self.probe_error = probe_error
        self.start_error = start_error
        self.status_error = status_error
        self.status_value = status_value
        self.stop_error = stop_error
        self.events = events if events is not None else []
        self.probe_calls = 0
        self.start_calls: list[bool] = []
        self.status_calls = 0
        self.stop_calls = 0

    def probe(self) -> None:
        self.probe_calls += 1
        self.events.append("probe")
        if self.probe_error is not None:
            raise self.probe_error

    def start(self, headless: bool) -> str:
        self.start_calls.append(headless)
        self.events.append("start")
        if self.start_error is not None:
            raise self.start_error
        return self.connect_url

    def status(self) -> str:
        self.status_calls += 1
        self.events.append("status")
        if self.status_error is not None:
            raise self.status_error
        return self.status_value

    def stop(self) -> None:
        self.stop_calls += 1
        self.events.append("stop")
        if self.stop_error is not None:
            raise self.stop_error


class FakeAdspowerClient:
    """Synchronous ``AdspowerClient`` double used by AdsPower tests.

    Mirrors the real client's public primitives but never touches HTTP.  Every
    call is recorded in ``calls`` and ``events`` so lifecycle ordering can be
    asserted without reaching into the session template.
    """

    def __init__(
        self,
        *,
        ws_url: str = "ws://127.0.0.1:9222/devtools/browser/ticket13",
        probe_error: BaseException | None = None,
        start_error: BaseException | None = None,
        status_error: BaseException | None = None,
        status_value: str = "Active",
        stop_error: BaseException | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.ws_url = ws_url
        self.probe_error = probe_error
        self.start_error = start_error
        self.status_error = status_error
        self.status_value = status_value
        self.stop_error = stop_error
        self.events = events if events is not None else []
        self.calls: list[str] = []
        self.probe_calls = 0
        self.start_calls: list[tuple[str, bool]] = []
        self.status_calls: list[str] = []
        self.stop_calls: list[str] = []

    def probe(self) -> None:
        self.probe_calls += 1
        self.calls.append("probe")
        self.events.append("probe")
        if self.probe_error is not None:
            raise self.probe_error

    def start(self, profile_id: str, headless: bool) -> str:
        self.calls.append("start")
        self.events.append("start")
        self.start_calls.append((profile_id, headless))
        if self.start_error is not None:
            raise self.start_error
        return self.ws_url

    def status(self, profile_id: str) -> str:
        self.calls.append("status")
        self.events.append("status")
        self.status_calls.append(profile_id)
        if self.status_error is not None:
            raise self.status_error
        return self.status_value

    def stop(self, profile_id: str) -> None:
        self.calls.append("stop")
        self.events.append("stop")
        self.stop_calls.append(profile_id)
        if self.stop_error is not None:
            raise self.stop_error


class FakeMultiloginClient:
    """Synchronous ``MultiloginClient`` double used by browser-session tests."""

    def __init__(
        self,
        *,
        port: str = "55513",
        probe_error: BaseException | None = None,
        start_error: BaseException | None = None,
        status_error: BaseException | None = None,
        status_value: str = "browser_running",
        stop_error: BaseException | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.port = port
        self.probe_error = probe_error
        self.start_error = start_error
        self.status_error = status_error
        self.status_value = status_value
        self.stop_error = stop_error
        self.events = events if events is not None else []
        self.calls: list[str] = []
        self.probe_calls = 0
        self.start_calls: list[tuple[str, str, bool]] = []
        self.status_calls: list[str] = []
        self.stop_calls: list[str] = []

    def probe(self) -> None:
        self.probe_calls += 1
        self.calls.append("probe")
        self.events.append("probe")
        if self.probe_error is not None:
            raise self.probe_error

    def start(self, folder_id: str, profile_id: str, headless: bool) -> str:
        self.calls.append("start")
        self.events.append("start")
        self.start_calls.append((folder_id, profile_id, headless))
        if self.start_error is not None:
            raise self.start_error
        return self.port

    def status(self, profile_id: str) -> str:
        self.calls.append("status")
        self.events.append("status")
        self.status_calls.append(profile_id)
        if self.status_error is not None:
            raise self.status_error
        return self.status_value

    def stop(self, profile_id: str) -> None:
        self.calls.append("stop")
        self.events.append("stop")
        self.stop_calls.append(profile_id)
        if self.stop_error is not None:
            raise self.stop_error


class FakeResponse:
    """Minimal ``requests.Response`` double used by HTTP client tests."""

    def __init__(
        self,
        status_code: int,
        payload: dict | None = None,
        *,
        text: str | None = None,
        json_error: BaseException | None = None,
    ) -> None:
        self.status_code = status_code
        self.payload = payload
        self._text = text
        self._json_error = json_error

    def json(self) -> dict:
        if self._json_error is not None:
            raise self._json_error
        return self.payload if self.payload is not None else {}

    @property
    def text(self) -> str:
        if self._text is not None:
            return self._text
        return json.dumps(self.payload or {}, ensure_ascii=False)


class FakeHttpGet:
    """Legacy GET-only fake retained for the Multilogin client tests."""

    def __init__(self, outcomes: list[object] | None = None) -> None:
        self.outcomes = list(outcomes or [])
        self.calls: list[dict] = []

    def __call__(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if not self.outcomes:
            raise AssertionError("http_get called with no queued outcome")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeHttp:
    """Injectable ``http_get`` / ``http_post`` pair with ordered call recording."""

    def __init__(
        self,
        get_outcomes: list[object] | None = None,
        post_outcomes: list[object] | None = None,
    ) -> None:
        self.get_outcomes = list(get_outcomes or [])
        self.post_outcomes = list(post_outcomes or [])
        self.get_calls: list[dict] = []
        self.post_calls: list[dict] = []
        self.calls: list[dict] = []

    def _pop(self, outcomes: list[object], method: str) -> object:
        if not outcomes:
            raise AssertionError(f"http_{method} called with no queued outcome")
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def get(self, url: str, **kwargs):
        call = {"method": "GET", "url": url, **kwargs}
        self.get_calls.append(call)
        self.calls.append(call)
        return self._pop(self.get_outcomes, "get")

    def post(self, url: str, **kwargs):
        call = {"method": "POST", "url": url, **kwargs}
        self.post_calls.append(call)
        self.calls.append(call)
        return self._pop(self.post_outcomes, "post")
