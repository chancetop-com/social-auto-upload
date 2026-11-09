# -*- coding: utf-8 -*-
"""AdsPower Local API V2 client and managed-browser provider.

Only this module knows the HTTP details of AdsPower ``probe`` / ``start`` /
``stop`` / ``status``.  The API key lives on the client instance and is only
ever placed in the ``Authorization`` header; it never appears in reprs,
exception messages, or logs.

Only V2 is implemented: there is deliberately no V1 fallback, dual-stack
probing, or runtime version detection.  The base URL is validated by the CLI
layer before it reaches this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote

import requests

from utils.errors import RateLimitedError, StartIncompleteError
from utils.managed_browser import ProviderMode

PROBE_TIMEOUT_SECONDS = 3
REQUEST_TIMEOUT_SECONDS = 30

PROBE_ACTION = "探活 AdsPower Local API"
START_ACTION = "启动 AdsPower Profile"
STOP_ACTION = "停止 AdsPower Profile"
STATUS_ACTION = "查询 AdsPower Profile 状态"

_UNAUTHORIZED_HINT = (
    "请检查 ADSPOWER_API_KEY 是否正确，"
    "并确认该账号已在 AdsPower 中开启 Local API 权限。"
)
_OUTDATED_CLIENT_HINT = (
    "AdsPower 版本过旧或 Local API 未开启；"
    "请升级到支持 V2 的最新版本，并确认 Local API 已开启。"
)
_RATE_LIMITED_HINT = "请求过于频繁（HTTP 429），请稍后重试；客户端不会自动重试。"

HttpGet = Callable[..., Any]
HttpPost = Callable[..., Any]


def _unreachable_message(base: str) -> str:
    return (
        f"无法连接 AdsPower Local API（{base}）。\n"
        "请确认：1) AdsPower 桌面应用已启动；"
        "2) 本地 API 已开启；"
        "3) CLI 与 AdsPower 在同一台机器且端口未被占用。"
    )


@dataclass(frozen=True, slots=True)
class AdspowerTarget:
    """Identity of an AdsPower Profile.

    Deliberately has no key/headless fields: the key lives on the client and
    headless is a per-run switch passed to ``browser_session``.
    """

    profile_id: str


class AdspowerClient:
    """Thin synchronous client for the AdsPower Local API V2."""

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
        return {"Authorization": f"Bearer {self._key}"}

    def _get(self, path: str, *, timeout: int) -> Any:
        return self._http_get(
            f"{self._base}{path}",
            timeout=timeout,
            headers=self._headers(),
            verify=True,
        )

    def _post(self, path: str, *, json: dict[str, Any], timeout: int) -> Any:
        return self._http_post(
            f"{self._base}{path}",
            json=json,
            timeout=timeout,
            headers=self._headers(),
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

    @classmethod
    def _http_error(cls, action: str, response: Any) -> RuntimeError:
        payload = cls._parse_json(response) or {}
        code = payload.get("code")
        message = str(payload.get("msg") or "").strip()

        parts = [f"{action}失败：HTTP {cls._status_code(response)}"]
        if code is not None:
            parts.append(f"code={code}")
        if message:
            parts.append(f"msg={message}")
        else:
            body = cls._response_text(response).strip()
            if body:
                parts.append(body[:500])

        status = cls._status_code(response)
        if status in (401, 403):
            parts.append(_UNAUTHORIZED_HINT)
        elif status == 404:
            parts.append(_OUTDATED_CLIENT_HINT)
        return RuntimeError("；".join(parts))

    @staticmethod
    def _rate_limited(action: str) -> RateLimitedError:
        return RateLimitedError(f"{action}失败：{_RATE_LIMITED_HINT}")

    def _raise_if_rate_limited(self, action: str, response: Any) -> None:
        if self._status_code(response) == 429:
            raise self._rate_limited(action)

    @staticmethod
    def _business_error(
        action: str, payload: dict[str, Any], status: Any
    ) -> RuntimeError:
        code = payload.get("code")
        message = str(payload.get("msg") or "").strip()
        parts = [f"{action}失败：HTTP {status}；code={code}"]
        if message:
            parts.append(f"msg={message}")
        return RuntimeError("；".join(parts))

    @staticmethod
    def _is_int_code(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)

    # ------------------------------------------------------------- Endpoints
    def probe(self) -> None:
        """Health-check the local API.  Always authenticated with a 3s timeout."""
        try:
            response = self._get("/status", timeout=PROBE_TIMEOUT_SECONDS)
        except Exception as exc:
            raise RuntimeError(_unreachable_message(self._base)) from exc

        self._raise_if_rate_limited(PROBE_ACTION, response)
        if not self._is_success(response):
            raise self._http_error(PROBE_ACTION, response)

    def start(self, profile_id: str, headless: bool) -> str:
        """Start a profile and return ``data.ws.puppeteer`` verbatim."""
        body = {
            "profile_id": profile_id,
            "headless": "1" if headless else "0",
            "last_opened_tabs": "0",
            "proxy_detection": "0",
            "delete_cache": "0",
            "cdp_mask": "1",
        }
        try:
            response = self._post(
                "/api/v2/browser-profile/start",
                json=body,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            raise RuntimeError(f"{START_ACTION}失败：{exc}") from exc

        self._raise_if_rate_limited(START_ACTION, response)
        if not self._is_success(response):
            raise self._http_error(START_ACTION, response)

        payload = self._parse_json(response)
        if payload is None:
            raise StartIncompleteError(
                f"{START_ACTION}失败：响应不是合法 JSON"
            )
        code = payload.get("code")
        if not self._is_int_code(code):
            raise StartIncompleteError(f"{START_ACTION}失败：响应缺少 code")
        if code != 0:
            raise self._business_error(
                START_ACTION, payload, self._status_code(response)
            )

        data = payload.get("data")
        ws = data.get("ws") if isinstance(data, dict) else None
        ws_url = ws.get("puppeteer") if isinstance(ws, dict) else None
        if not isinstance(ws_url, str) or not ws_url.strip():
            raise StartIncompleteError(
                f"{START_ACTION}失败：响应缺少 data.ws.puppeteer"
            )
        return ws_url

    def stop(self, profile_id: str) -> None:
        """Stop a profile; success requires HTTP 2xx and ``code == 0``."""
        try:
            response = self._post(
                "/api/v2/browser-profile/stop",
                json={"profile_id": profile_id},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            raise RuntimeError(f"{STOP_ACTION}失败：{exc}") from exc

        self._raise_if_rate_limited(STOP_ACTION, response)
        if not self._is_success(response):
            raise self._http_error(STOP_ACTION, response)

        payload = self._parse_json(response)
        if payload is None:
            raise RuntimeError(f"{STOP_ACTION}失败：响应不是合法 JSON")
        code = payload.get("code")
        if not self._is_int_code(code):
            raise RuntimeError(f"{STOP_ACTION}失败：响应缺少 code")
        if code != 0:
            raise self._business_error(
                STOP_ACTION, payload, self._status_code(response)
            )

    def status(self, profile_id: str) -> str:
        """Return the profile's V2 ``/active`` status; diagnostic only."""
        path = (
            "/api/v2/browser-profile/active"
            f"?profile_id={quote(str(profile_id), safe='')}"
        )
        try:
            response = self._get(path, timeout=REQUEST_TIMEOUT_SECONDS)
        except Exception as exc:
            raise RuntimeError(f"{STATUS_ACTION}失败：{exc}") from exc

        self._raise_if_rate_limited(STATUS_ACTION, response)
        if not self._is_success(response):
            raise self._http_error(STATUS_ACTION, response)

        payload = self._parse_json(response)
        if payload is None:
            return "unknown"
        data = payload.get("data")
        if not isinstance(data, dict):
            return "unknown"
        value = data.get("status")
        return str(value) if value is not None else "unknown"


class AdspowerProvider:
    """Compose an AdsPower profile identity with its Local API client."""

    mode: ProviderMode = "adspower"

    __slots__ = ("_target", "_client")

    def __init__(self, target: AdspowerTarget, client: AdspowerClient) -> None:
        self._target = target
        self._client = client

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(target={self._target!r}, "
            f"client={self._client!r})"
        )

    @property
    def target(self) -> AdspowerTarget:
        return self._target

    @property
    def profile_id(self) -> str:
        return self._target.profile_id

    def probe(self) -> None:
        self._client.probe()

    def start(self, headless: bool) -> str:
        return self._client.start(self._target.profile_id, headless)

    def stop(self) -> None:
        self._client.stop(self._target.profile_id)

    def status(self) -> str:
        return self._client.status(self._target.profile_id)


__all__ = [
    "AdspowerClient",
    "AdspowerProvider",
    "AdspowerTarget",
    "PROBE_TIMEOUT_SECONDS",
    "REQUEST_TIMEOUT_SECONDS",
]
