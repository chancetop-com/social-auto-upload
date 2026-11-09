# -*- coding: utf-8 -*-
"""Multilogin X Launcher client.

Only this module knows the HTTP details of Start / Stop / status.  The token is
kept on the client instance and is only ever placed in the ``Authorization``
header; it is never included in reprs, exception messages, or dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote

import requests

from utils.errors import RateLimitedError
from utils.managed_browser import ProviderMode

LAUNCHER_BASE_URL = "https://launcher.mlx.yt:45001"

PROBE_TIMEOUT_SECONDS = 3
REQUEST_TIMEOUT_SECONDS = 30

# Fixed text from spec §10.  Kept verbatim so callers can rely on it.
_LAUNCHER_UNREACHABLE_MESSAGE = (
    "无法连接 Multilogin Launcher（https://launcher.mlx.yt:45001）。\n"
    "请确认：1) Multilogin 桌面应用已启动；2) CLI 与 Multilogin 在同一台机器；\n"
    "3) 45001 端口未被占用或被防火墙拦截。"
)

HttpGet = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class MultiloginTarget:
    """Identity of a Multilogin Profile.

    Deliberately has no token/headless fields: the token lives on the client and
    headless is a per-run switch passed to ``browser_session``.
    """

    folder_id: str
    profile_id: str


class MultiloginClient:
    """Thin synchronous client for the local Multilogin Launcher."""

    __slots__ = ("_token", "_http_get")

    def __init__(self, token: str, http_get: HttpGet | None = None) -> None:
        self._token = token
        self._http_get = http_get or requests.get

    def __repr__(self) -> str:
        return f"{type(self).__name__}(token=<redacted>)"

    # ------------------------------------------------------------------ HTTP
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def _get(
        self,
        path: str,
        *,
        timeout: int,
        authenticated: bool = True,
    ) -> Any:
        kwargs: dict[str, Any] = {"timeout": timeout, "verify": True}
        if authenticated:
            kwargs["headers"] = self._headers()
        return self._http_get(f"{LAUNCHER_BASE_URL}{path}", **kwargs)

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

    def _http_error(self, action: str, response: Any) -> RuntimeError:
        payload = self._parse_json(response) or {}
        status = payload.get("status")
        if not isinstance(status, dict):
            status = {}
        error_code = str(status.get("error_code") or "").strip()
        message = str(status.get("message") or "").strip()

        status_code = getattr(response, "status_code", "?")
        parts = [f"{action}失败：HTTP {status_code}"]
        if error_code:
            parts.append(f"error_code={error_code}")
        if message:
            parts.append(f"message={message}")
        else:
            body = self._response_text(response).strip()
            if body:
                parts.append(body[:500])
        if status_code == 429:
            # Shared rate-limit contract: the CLI maps this to exit code 11.
            return RateLimitedError("；".join(parts))
        return RuntimeError("；".join(parts))

    # ------------------------------------------------------------- Endpoints
    def probe(self) -> None:
        """Health-check the launcher.  Unauthenticated, 3s, fixed base URL."""
        try:
            response = self._get(
                "/api/v1/version",
                timeout=PROBE_TIMEOUT_SECONDS,
                authenticated=False,
            )
        except Exception as exc:
            raise RuntimeError(_LAUNCHER_UNREACHABLE_MESSAGE) from exc

        if getattr(response, "status_code", None) != 200:
            detail = self._http_error("探活 Multilogin Launcher", response)
            raise RuntimeError(f"{_LAUNCHER_UNREACHABLE_MESSAGE}\n{detail}") from None

    def start(self, folder_id: str, profile_id: str, headless: bool) -> str:
        """Start a profile and return the CDP automation port."""
        path = (
            f"/api/v2/profile/f/{quote(str(folder_id), safe='')}"
            f"/p/{quote(str(profile_id), safe='')}"
            f"/start?automation_type=playwright"
            f"&headless_mode={'true' if headless else 'false'}"
        )
        try:
            response = self._get(path, timeout=REQUEST_TIMEOUT_SECONDS)
        except Exception as exc:
            raise RuntimeError(f"启动 Multilogin Profile 失败：{exc}") from exc
        if getattr(response, "status_code", None) != 200:
            raise self._http_error("启动 Multilogin Profile", response)

        payload = self._parse_json(response) or {}
        data = payload.get("data")
        port = data.get("port") if isinstance(data, dict) else None
        if port is None or str(port).strip() == "":
            raise RuntimeError(
                "启动 Multilogin Profile 失败：响应缺少 data.port"
            )
        return str(port).strip()

    def stop(self, profile_id: str) -> None:
        """Stop a profile.  ``profile already stopped`` counts as success."""
        path = f"/api/v1/profile/stop/p/{quote(str(profile_id), safe='')}"
        try:
            response = self._get(path, timeout=REQUEST_TIMEOUT_SECONDS)
        except Exception as exc:
            raise RuntimeError(f"停止 Multilogin Profile 失败：{exc}") from exc
        status_code = getattr(response, "status_code", None)

        if status_code == 200:
            return

        if status_code == 500:
            payload = self._parse_json(response) or {}
            status = payload.get("status")
            if not isinstance(status, dict):
                status = {}
            message = str(status.get("message") or "")
            error_code = str(status.get("error_code") or "")
            body = self._response_text(response)
            haystack = " ".join((message, error_code, body)).lower().replace("_", " ")
            if "profile already stopped" in haystack:
                return

        raise self._http_error("停止 Multilogin Profile", response)

    def status(self, profile_id: str) -> str:
        """Return the launcher's last-known profile status string."""
        path = f"/api/v1/profile/status/p/{quote(str(profile_id), safe='')}"
        try:
            response = self._get(path, timeout=REQUEST_TIMEOUT_SECONDS)
        except Exception as exc:
            raise RuntimeError(f"查询 Multilogin Profile 状态失败：{exc}") from exc
        if getattr(response, "status_code", None) != 200:
            raise self._http_error("查询 Multilogin Profile 状态", response)

        payload = self._parse_json(response) or {}
        data = payload.get("data")
        if not isinstance(data, dict):
            return "unknown"
        value = data.get("status")
        return str(value) if value is not None else "unknown"


class MultiloginProvider:
    """Compose a Multilogin profile identity with its launcher client.

    ``start`` is the only place that normalizes the launcher's raw port into a
    URL that can be handed to ``connect_over_cdp``.
    """

    mode: ProviderMode = "multilogin"

    __slots__ = ("_target", "_client")

    def __init__(self, target: MultiloginTarget, client: MultiloginClient) -> None:
        self._target = target
        self._client = client

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(target={self._target!r}, "
            f"client={self._client!r})"
        )

    @property
    def target(self) -> MultiloginTarget:
        return self._target

    @property
    def folder_id(self) -> str:
        return self._target.folder_id

    @property
    def profile_id(self) -> str:
        return self._target.profile_id

    def probe(self) -> None:
        self._client.probe()

    def start(self, headless: bool) -> str:
        port = self._client.start(
            self._target.folder_id,
            self._target.profile_id,
            headless,
        )
        return f"http://127.0.0.1:{port}"

    def stop(self) -> None:
        self._client.stop(self._target.profile_id)

    def status(self) -> str:
        return self._client.status(self._target.profile_id)


__all__ = [
    "LAUNCHER_BASE_URL",
    "MultiloginClient",
    "MultiloginProvider",
    "MultiloginTarget",
]
