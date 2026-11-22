# -*- coding: utf-8 -*-
"""BitBrowser Local API client and managed-browser provider.

Only this module knows the HTTP details of BitBrowser ``probe`` / ``start`` /
``stop`` / ``status`` / ``observe``.  The token lives on the client instance and
is only ever placed in the ``x-api-key`` header; it never appears in reprs,
exception messages, or logs.

The window identity is the string copied from the desktop app.  It is passed
verbatim as the API ``id``; display sequence numbers and window names are never
used for lookup.  The base URL is validated by the CLI layer before it reaches
this module.

Only the documented Local API is implemented: there is deliberately no version
probing or fallback to other endpoints.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit

import requests

from utils.errors import (
    ProfileConnectionUnavailableError,
    ProviderDiagnosticError,
    ProviderRequestRejected,
    RateLimitedError,
    StartIncompleteError,
)
from utils.managed_browser import ProfileObservation, ProviderHints, ProviderMode

PROBE_TIMEOUT_SECONDS = 3
REQUEST_TIMEOUT_SECONDS = 30
CDP_TIMEOUT_SECONDS = 3
# The desktop client requires at least 5 seconds after a close acknowledgement
# before the same window ID may be opened again.
STOP_SETTLE_SECONDS = 5.0

PROBE_ACTION = "探活比特浏览器 Local API"
START_ACTION = "启动比特浏览器窗口"
STOP_ACTION = "关闭比特浏览器窗口"
STATUS_ACTION = "查询比特浏览器窗口状态"
ALIVE_ACTION = "查询比特浏览器窗口存活进程"
PORT_ACTION = "查询比特浏览器窗口调试端口"
CDP_ACTION = "读取比特浏览器窗口 CDP 信息"

_UNAUTHORIZED_HINT = (
    "请检查 BITBROWSER_API_KEY 是否正确，"
    "并确认比特浏览器已开启 Local API 与 Token 鉴权。"
)
_CLIENT_CAPABILITY_HINT = (
    "请检查 BITBROWSER_API_BASE 是否指向本机比特浏览器客户端，"
    "并确认客户端版本支持按窗口 ID 查询进程与调试端口。"
)
_RATE_LIMITED_HINT = "请求过于频繁（HTTP 429），请稍后重试；客户端不会自动重试。"

_TIMEOUTS = (TimeoutError, requests.exceptions.Timeout)

HttpGet = Callable[..., Any]
HttpPost = Callable[..., Any]


class _RequestRejected(ProviderDiagnosticError, ProviderRequestRejected):
    """The Local API explicitly rejected this operation."""


class _ConnectionUnavailable(ProviderDiagnosticError, ProfileConnectionUnavailableError):
    """The window is alive but its debugging connection is unavailable."""


def _browser_endpoint(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value.strip())
        if parts.scheme in ("ws", "wss") and parts.hostname and parts.port != 0:
            return value
    except ValueError:
        pass
    return None


def _unreachable_message(base: str) -> str:
    return (
        f"无法连接比特浏览器 Local API（{base}）。\n"
        "请确认：1) 比特浏览器桌面应用已启动；"
        "2) Local API 与 Token 鉴权已开启；"
        "3) CLI 与比特浏览器在同一台机器且端口未被占用。"
    )


def _port_value(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip()
    else:
        return None
    if not re.fullmatch(r"[0-9]{1,5}", text):
        return None
    port = int(text)
    if not 1 <= port <= 65535:
        return None
    return str(port)


@dataclass(frozen=True, slots=True)
class BitBrowserTarget:
    """Identity of a BitBrowser window.

    Deliberately has no key/headless fields: the token lives on the client and
    headless is a per-run switch passed to ``browser_session``.
    """

    profile_id: str


class BitBrowserClient:
    """Thin synchronous client for the BitBrowser Local API."""

    __slots__ = ("_key", "_base", "_http_get", "_http_post")

    def __init__(
        self,
        key: str,
        base: str,
        http_get: HttpGet | None = None,
        http_post: HttpPost | None = None,
    ) -> None:
        self._key = key
        self._base = base.rstrip("/")
        self._http_get = http_get or requests.get
        self._http_post = http_post or requests.post

    def __repr__(self) -> str:
        return f"{type(self).__name__}(token=<redacted>)"

    # ------------------------------------------------------------------ HTTP
    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._key}

    def _get(self, url: str, *, timeout: int) -> Any:
        return self._http_get(url, timeout=timeout, verify=True)

    def _post(self, path: str, *, json: dict[str, Any], timeout: int) -> Any:
        return self._http_post(
            f"{self._base}{path}",
            json=json,
            timeout=timeout,
            headers=self._headers(),
            allow_redirects=False,
            verify=True,
        )

    @staticmethod
    def _status_code(response: Any) -> Any:
        return getattr(response, "status_code", "?")

    @classmethod
    def _is_success(cls, response: Any) -> bool:
        status = cls._status_code(response)
        return isinstance(status, int) and 200 <= status < 300

    @staticmethod
    def _parse_json(response: Any) -> dict[str, Any] | None:
        try:
            payload = response.json()
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _response_text(response: Any) -> str:
        try:
            text = response.text
        except Exception:
            return ""
        return text if isinstance(text, str) else ""

    def _redact(self, text: str) -> str:
        """Remove the API key from any untrusted/raw exception text."""
        return text.replace(self._key, "<redacted>") if self._key else text

    def _http_error(self, action: str, response: Any) -> ProviderDiagnosticError:
        payload = self._parse_json(response) or {}
        message = self._redact(str(payload.get("msg") or "").strip())
        status = self._status_code(response)

        parts = [f"{action}失败：HTTP {status}"]
        if message:
            parts.append(f"msg={message}")
        else:
            body = self._redact(self._response_text(response).strip())
            parts.append(f"msg={body[:500]}" if body else "msg=响应无法识别")
        if status in (401, 403):
            parts.append(_UNAUTHORIZED_HINT)
        elif status == 404:
            parts.append(_CLIENT_CAPABILITY_HINT)
        if status in (400, 401, 403, 404, 405, 422):
            return _RequestRejected("；".join(parts))
        return ProviderDiagnosticError("；".join(parts))

    @staticmethod
    def _rate_limited(action: str) -> RateLimitedError:
        return RateLimitedError(f"{action}失败：{_RATE_LIMITED_HINT}")

    def _raise_if_rate_limited(self, action: str, response: Any) -> None:
        if self._status_code(response) == 429:
            raise self._rate_limited(action)

    def _business_error(
        self, action: str, payload: dict[str, Any], status: Any
    ) -> ProviderDiagnosticError:
        message = (
            self._redact(str(payload.get("msg") or "").strip())
            or "success=false"
        )
        return _RequestRejected(
            f"{action}失败：HTTP {status}；msg={message}"
        )

    def _trusted_payload(
        self,
        action: str,
        response: Any,
        *,
        envelope_error: type[Exception] = ProviderDiagnosticError,
    ) -> dict[str, Any]:
        """Validate status and the success envelope, returning its payload."""
        self._raise_if_rate_limited(action, response)
        if not self._is_success(response):
            raise self._http_error(action, response)

        payload = self._parse_json(response)
        if payload is None:
            raise envelope_error(f"{action}失败：响应不是合法 JSON")
        success = payload.get("success")
        if not isinstance(success, bool):
            raise envelope_error(f"{action}失败：响应缺少 success")
        if not success:
            raise self._business_error(
                action, payload, self._status_code(response)
            )
        return payload

    def _post_json(
        self,
        action: str,
        path: str,
        body: dict[str, Any],
        *,
        timeout: int = REQUEST_TIMEOUT_SECONDS,
    ) -> Any:
        """POST one business call and return ``data`` from a trusted envelope."""
        try:
            response = self._post(path, json=body, timeout=timeout)
        except _TIMEOUTS:
            raise ProviderDiagnosticError(
                f"{action}失败：请求超时（{timeout} 秒）。"
            ) from None
        except Exception as exc:
            raise ProviderDiagnosticError(
                f"{action}失败：{self._redact(str(exc))}"
            ) from None
        return self._trusted_payload(action, response).get("data")

    # ------------------------------------------------------------- Endpoints
    def probe(self) -> None:
        """Health-check the local API with a 3s timeout."""
        try:
            response = self._post(
                "/health",
                json={},
                timeout=PROBE_TIMEOUT_SECONDS,
            )
        except _TIMEOUTS:
            raise ProviderDiagnosticError(
                f"{PROBE_ACTION}失败：请求超时（{PROBE_TIMEOUT_SECONDS} 秒）。"
                f"{_unreachable_message(self._base)}"
            ) from None
        except Exception:
            raise ProviderDiagnosticError(
                f"{PROBE_ACTION}失败：{_unreachable_message(self._base)}"
            ) from None

        self._trusted_payload(PROBE_ACTION, response)

    def start(self, profile_id: str, headless: bool) -> str:
        """Open a window and return ``data.ws`` verbatim."""
        body: dict[str, Any] = {"id": profile_id}
        if headless:
            # Official headless guidance: never pass an initial page; open the
            # needed page after connecting instead.
            body["args"] = ["--headless"]
            body["ignoreDefaultUrls"] = True

        try:
            response = self._post(
                "/browser/open",
                json=body,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            raise RuntimeError(
                f"{START_ACTION}失败：{self._redact(str(exc))}"
            ) from None

        payload = self._trusted_payload(
            START_ACTION,
            response,
            envelope_error=StartIncompleteError,
        )
        data = payload.get("data")
        ws = data.get("ws") if isinstance(data, dict) else None
        endpoint = _browser_endpoint(ws)
        if endpoint is None:
            raise StartIncompleteError(
                f"{START_ACTION}失败：响应缺少可用的 data.ws"
            )
        return endpoint

    def stop(self, profile_id: str) -> None:
        """Close a window by its copied string ID."""
        try:
            response = self._post(
                "/browser/close",
                json={"id": profile_id},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            raise RuntimeError(
                f"{STOP_ACTION}失败：{self._redact(str(exc))}"
            ) from None

        self._trusted_payload(
            STOP_ACTION,
            response,
            envelope_error=RuntimeError,
        )

    @property
    def resource_identity(self) -> str:
        parts = urlsplit(self._base)
        host = (parts.hostname or "").lower().rstrip(".")
        if host in {"localhost", "127.0.0.1", "::1"}:
            host = "localhost"
        port = (
            parts.port
            if parts.port is not None
            else (443 if parts.scheme == "https" else 80)
        )
        return f"{parts.scheme}://[{host}]:{port}"

    # --------------------------------------------------------- Window status
    def _alive_ids(self, action: str, data: Any) -> set[str]:
        if isinstance(data, list):
            ids: set[str] = set()
            for item in data:
                if isinstance(item, bool) or not isinstance(item, (str, int)) or not str(item).strip():
                    raise ProviderDiagnosticError(
                        f"{action}失败：响应包含无法识别的窗口 ID。"
                    )
                ids.add(str(item))
            return ids
        if isinstance(data, dict):
            # The map form associates each live window ID with its PID.
            # An invalid value cannot establish that the window has exited.
            for window_id, pid in data.items():
                if not isinstance(window_id, str) or not window_id.strip():
                    raise ProviderDiagnosticError(f"{action}失败：响应包含无法识别的窗口 ID。")
                if not re.fullmatch(r"[1-9][0-9]*", str(pid)):
                    raise ProviderDiagnosticError(f"{action}失败：响应包含无法识别的进程 ID。")
            return set(data)
        raise ProviderDiagnosticError(
            f"{action}失败：响应缺少可识别的 data。"
        )

    def _alive(self, profile_id: str) -> set[str]:
        data = self._post_json(
            ALIVE_ACTION,
            "/browser/pids/alive",
            {"ids": [profile_id]},
        )
        return self._alive_ids(ALIVE_ACTION, data)

    def status(self, profile_id: str) -> str:
        """Return a diagnostic window state; never used for control flow."""
        alive = self._alive(profile_id)
        return "running" if str(profile_id) in alive else "stopped"

    def _port_for(self, action: str, data: Any, profile_id: str) -> str:
        if not isinstance(data, dict):
            raise ProviderDiagnosticError(
                f"{action}失败：响应缺少可识别的 data。"
            )
        if profile_id not in data:
            raise _ConnectionUnavailable(f"{action}失败：窗口进程存活，但响应未包含该窗口的调试端口。")
        port = _port_value(data[profile_id])
        if port is None:
            raise ProviderDiagnosticError(f"{action}失败：返回的调试端口无效。")
        return port

    def _cdp_endpoint(self, port: str) -> str:
        url = f"http://127.0.0.1:{port}/json/version"
        try:
            response = self._get(url, timeout=CDP_TIMEOUT_SECONDS)
        except _TIMEOUTS:
            raise ProviderDiagnosticError(
                f"{CDP_ACTION}失败：请求超时（{CDP_TIMEOUT_SECONDS} 秒）；"
                f"窗口调试端口 {port} 未响应。"
            ) from None
        except (ConnectionError, requests.exceptions.ConnectionError):
            raise _ConnectionUnavailable(
                f"{CDP_ACTION}失败：窗口调试端口 {port} 不可用。"
            ) from None
        except Exception as exc:
            raise ProviderDiagnosticError(
                f"{CDP_ACTION}失败：{self._redact(str(exc))}；"
                f"窗口调试端口 {port} 不可用。"
            ) from None

        if not self._is_success(response):
            raise ProviderDiagnosticError(
                f"{CDP_ACTION}失败：HTTP {self._status_code(response)}；"
                f"窗口调试端口 {port} 未返回浏览器信息。"
            )

        payload = self._parse_json(response)
        endpoint = (
            payload.get("webSocketDebuggerUrl")
            if isinstance(payload, dict)
            else None
        )
        if not isinstance(endpoint, str):
            raise ProviderDiagnosticError(
                f"{CDP_ACTION}失败：窗口调试端口 {port} 的响应缺少"
                "浏览器级 WebSocket 地址。"
            )

        try:
            parts = urlsplit(endpoint.strip())
            host = (parts.hostname or "").lower()
            valid = (
                parts.scheme == "ws"
                and host in {"127.0.0.1", "localhost", "::1"}
                and parts.port == int(port)
                and parts.username is None
                and parts.password is None
                and not parts.query
                and not parts.fragment
                and re.fullmatch(
                    r"/devtools/browser/[0-9a-fA-F-]{36}", parts.path
                )
                is not None
            )
        except ValueError:
            valid = False
        if not valid:
            raise ProviderDiagnosticError(
                f"{CDP_ACTION}失败：返回的 WebSocket 地址与窗口调试端口"
                f" {port} 不符。"
            )
        return endpoint

    def observe(self, profile_id: str) -> ProfileObservation:
        """Report the current run by process ID, debug port and CDP version.

        ``active=False`` is only returned when the process query says the
        window is not running.  A surviving process with a missing/unreachable
        port or CDP endpoint raises instead, so callers never mistake an
        unclear instance for an exited one.
        """
        alive = self._alive(profile_id)
        if str(profile_id) not in alive:
            return ProfileObservation(False)

        data = self._post_json(
            PORT_ACTION,
            "/browser/ports",
            {},
        )
        port = self._port_for(PORT_ACTION, data, profile_id)
        endpoint = self._cdp_endpoint(port)
        # The Local API does not report the window's headless setting.
        return ProfileObservation(True, endpoint)


class BitBrowserProvider:
    """Compose a BitBrowser window identity with its Local API client."""

    mode: ProviderMode = "bitbrowser"
    asynchronous_stop = True
    stop_settle_seconds = STOP_SETTLE_SECONDS
    hints = ProviderHints(
        stop_settle_hint="请先在比特浏览器桌面端关闭该窗口后重试。",
        stop_unconfirmed_hint=(
            "请检查比特浏览器 Local API 与窗口状态后重试。"
        ),
        start_unconfirmed_hint="上次启动结果未明，无法确认当前实例",
        cdp_connect_hint=(
            "请检查窗口的调试连接：确认窗口仍在运行，"
            "且 Local API 返回的调试端口可从本机访问。"
        ),
    )

    __slots__ = ("_target", "_client")

    def __init__(
        self, target: BitBrowserTarget, client: BitBrowserClient
    ) -> None:
        self._target = target
        self._client = client

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(target={self._target!r}, "
            f"client={self._client!r})"
        )

    @property
    def target(self) -> BitBrowserTarget:
        return self._target

    @property
    def profile_id(self) -> str:
        return self._target.profile_id

    @property
    def resource_identity(self) -> str:
        return self._client.resource_identity

    def observe(self) -> ProfileObservation:
        return self._client.observe(self.profile_id)

    def probe(self) -> None:
        self._client.probe()

    def start(self, headless: bool) -> str:
        return self._client.start(self._target.profile_id, headless)

    def stop(self) -> None:
        self._client.stop(self._target.profile_id)

    def status(self) -> str:
        return self._client.status(self.profile_id)


__all__ = [
    "BitBrowserClient",
    "BitBrowserProvider",
    "BitBrowserTarget",
    "CDP_TIMEOUT_SECONDS",
    "PROBE_TIMEOUT_SECONDS",
    "REQUEST_TIMEOUT_SECONDS",
    "STOP_SETTLE_SECONDS",
]
