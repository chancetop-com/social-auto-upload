# -*- coding: utf-8 -*-
"""Multilogin X Launcher client.

Only this module knows the HTTP details of Start / Stop / status.  The token is
kept on the client instance and is only ever placed in the ``Authorization``
header; it is never included in reprs, exception messages, or dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any, Callable
from urllib.parse import quote, urlsplit
from uuid import UUID

import requests

from utils.errors import (
    ProfileConnectionUnavailableError, ProfileStartingError, ProviderRequestRejected, RateLimitedError,
)
from utils.managed_browser import ProfileObservation, ProviderMode

PROFILE_METAS_URL = "https://api.multilogin.com/profile/metas"
LAUNCHER_BASE_URL = "https://launcher.mlx.yt:45001"

PROBE_TIMEOUT_SECONDS = 3
REQUEST_TIMEOUT_SECONDS = 30

_STARTING_STATES = {
    "download_browser_profile_metadata", "download_browser_profile_data", "download_browser_core",
    "download_finished", "download_meta_finished", "download_data_finished", "download_core_finished",
    "validate_proxy", "start_browser",
}

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


def canonical_id(value: str) -> str:
    """Use the same UUID spelling for local admission and Launcher requests."""
    try:
        return str(UUID(value))
    except ValueError:
        return value


def _successful_data(payload: dict) -> dict:
    status = payload.get("status")
    if (not isinstance(status, dict) or status.get("http_code") != 200
            or status.get("error_code") or not isinstance(payload.get("data"), dict)):
        raise RuntimeError("Multilogin 未返回成功的 Profile 数据。")
    return payload["data"]


def _automation_port(value) -> str:
    # Launcher returns a decimal port. An arbitrary string must never become a URL.
    if not isinstance(value, (str, int)) or not re.fullmatch(r"[0-9]{1,5}", str(value)):
        raise ProfileConnectionUnavailableError("Multilogin Profile 缺少有效的 CDP 端口（port）。")
    port = int(value)
    if not 1 <= port <= 65535:
        raise ProfileConnectionUnavailableError("Multilogin Profile 的 CDP 端口（port）超出范围。")
    return str(port)


def _launch_time(value: str | None) -> int | None:
    if value is None:
        return None
    # Launcher reports UTC and can supply seven fractional digits. Preserve
    # the whole value across Python 3.10–3.12, including sub-microsecond ticks.
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?Z", value)
    if not match:
        raise ValueError("无法确认 Multilogin Profile 的启动时间。")
    second = datetime.strptime(match[1], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    return int(second.timestamp()) * 10**9 + int((match[2] or "").ljust(9, "0"))


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
        if status_code in (401, 403):
            return ProviderRequestRejected("；".join(parts))
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
            if isinstance(detail, RateLimitedError):
                # Shared rate-limit contract: do not bury the 429 inside the
                # unreachable hint, or the CLI cannot map it to exit code 11.
                raise detail
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

        data = _successful_data(self._parse_json(response) or {})
        port = _automation_port(data.get("port"))
        if (data.get("id") != profile_id or data.get("folder_id", folder_id) != folder_id
                or data.get("browser_type") != "mimic" or data.get("is_quick", False) is not False):
            raise RuntimeError("启动 Multilogin Profile 返回的浏览器身份与请求不符。")
        return port

    def stop(self, profile_id: str) -> None:
        """Stop a profile.  ``profile already stopped`` counts as success."""
        path = f"/api/v1/profile/stop/p/{quote(str(profile_id), safe='')}"
        try:
            response = self._get(path, timeout=REQUEST_TIMEOUT_SECONDS)
        except Exception as exc:
            raise RuntimeError(f"停止 Multilogin Profile 失败：{exc}") from exc
        status_code = getattr(response, "status_code", None)

        if status_code == 200:
            status = (self._parse_json(response) or {}).get("status")
            if isinstance(status, dict) and status.get("http_code") == 200 and not status.get("error_code"):
                return
            raise RuntimeError("Multilogin Launcher 未确认停止 Profile。")

        if status_code == 500:
            payload = self._parse_json(response)
            if payload is None:
                try:
                    payload = json.loads(self._response_text(response))
                except ValueError:
                    payload = None
            status = payload.get("status") if isinstance(payload, dict) else None
            if isinstance(status, dict):
                if (str(status.get("message")).strip().lower() == "profile already stopped"
                        or status.get("error_code") == "PROFILE_ALREADY_STOPPED"):
                    return

        raise self._http_error("停止 Multilogin Profile", response)

    def status(self, profile_id: str) -> str:
        """Return the launcher's last-known profile status string."""
        data = self._status_payload(profile_id).get("data")
        if not isinstance(data, dict):
            return "unknown"
        value = data.get("status")
        return str(value) if value is not None else "unknown"

    def _status_payload(self, profile_id: str) -> dict:
        path = f"/api/v1/profile/status/p/{quote(str(profile_id), safe='')}"
        try:
            response = self._get(path, timeout=REQUEST_TIMEOUT_SECONDS)
        except Exception as exc:
            raise RuntimeError(f"查询 Multilogin Profile 状态失败：{exc}") from exc
        if getattr(response, "status_code", None) != 200:
            raise self._http_error("查询 Multilogin Profile 状态", response)
        return self._parse_json(response) or {}

    def observe(self, folder_id: str, profile_id: str) -> ProfileObservation:
        data = _successful_data(self._status_payload(profile_id))
        if data.get("profile_id") != profile_id or data.get("folder_id") != folder_id:
            raise RuntimeError("无法确认 Multilogin Profile 与文件夹。")
        if data.get("browser_type") != "mimic" or data.get("is_quick", False) is not False:
            raise RuntimeError("仅支持 Multilogin Mimic 的已保存 Profile。")
        if data.get("status") == "stopped":
            return ProfileObservation(False)
        if data.get("status") in _STARTING_STATES:
            raise ProfileStartingError("Multilogin Profile 正在启动。")
        if data.get("status") != "browser_running":
            raise RuntimeError("Multilogin Profile 状态未知。")
        port = _automation_port(data.get("message"))
        # Launcher status is last-session history. Verify this credential's current
        # access to the profile before using its locally advertised automation port.
        response = requests.post(
            PROFILE_METAS_URL, headers=self._headers(), json={"ids": [profile_id]},
            timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False,
        )
        if response.status_code != 200:
            raise self._http_error("核对 Multilogin Profile 访问权限", response)
        metadata = _successful_data(self._parse_json(response) or {})
        profiles = metadata.get("profiles")
        if not isinstance(profiles, list) or len(profiles) != 1:
            raise RuntimeError("无法确认 Multilogin Profile 访问权限。")
        item = profiles[0]
        if not isinstance(item, dict) or item.get("id") != profile_id or item.get("folder_id") != folder_id:
            raise RuntimeError("Multilogin Profile 元数据与请求身份不符。")
        try:
            endpoint = self.browser_endpoint(port)
        except (requests.RequestException, RuntimeError, KeyError, ValueError, TypeError):
            raise ProfileConnectionUnavailableError("Multilogin Profile 的当前连接不可用。") from None
        return ProfileObservation(True, endpoint, launched_at_ns=_launch_time(data.get("last_launched_at")))

    def browser_endpoint(self, port: str) -> str:
        """Resolve a Launcher port to the immutable WebSocket for this browser run."""
        host = f"127.0.0.1:{_automation_port(port)}"
        with requests.Session() as local:
            local.trust_env = False
            response = local.get(f"http://{host}/json/version", timeout=PROBE_TIMEOUT_SECONDS, allow_redirects=False)
            if response.status_code != 200:
                raise RuntimeError("无法读取 Multilogin 浏览器实例。")
            url = response.json()["webSocketDebuggerUrl"]
        parts = urlsplit(url)
        if (parts.scheme != "ws" or parts.netloc != host or parts.query or parts.fragment
                or not re.fullmatch(r"/devtools/browser/[0-9a-fA-F-]{36}", parts.path)):
            raise RuntimeError("Multilogin Profile 的 CDP 浏览器实例不符。")
        return url


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


class SharedMultiloginProvider(MultiloginProvider):
    """Command-scoped adapter that identifies a browser run across processes."""

    asynchronous_stop = True

    @property
    def resource_identity(self) -> str:
        return self.folder_id

    def start(self, headless: bool) -> str:
        port = self._client.start(self.folder_id, self.profile_id, headless)
        return self._client.browser_endpoint(port)

    def observe(self) -> ProfileObservation:
        return self._client.observe(self.folder_id, self.profile_id)


__all__ = [
    "LAUNCHER_BASE_URL",
    "MultiloginClient",
    "MultiloginProvider",
    "MultiloginTarget",
    "SharedMultiloginProvider",
]
