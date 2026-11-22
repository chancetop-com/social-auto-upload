# -*- coding: utf-8 -*-
"""Formal ``sau <platform> check`` runs for all seven BitBrowser platforms.

The tests exercise ``sau_cli.main`` end to end against a loopback BitBrowser
Local API and controlled platform pages served from one real Chromium context.
They reuse the shared process-test page/bootstrap helpers and fixture HTML
instead of introducing provider-specific browser doubles.
"""

from __future__ import annotations

import io
import json
import os
import socket
import sys
import threading
import time
from collections import defaultdict, deque
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

import pytest
from loguru import logger
from patchright.sync_api import sync_playwright

import sau_cli
from tests.test_shared_adspower_process import Handler, OfflineProfile, serve

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX Chromium harness",
)

FIXTURES = Path(__file__).with_name("fixtures")
WINDOW_ID = "bitbrowser-window-08"
KEY = "SENTINEL-BITBROWSER-08-KEY"

PLATFORMS = (
    "xiaohongshu",
    "rednote",
    "tiktok",
    "instagram",
    "facebook",
    "facebook-page",
    "youtube",
)
HOSTS = {
    "xiaohongshu": "creator.xiaohongshu.com",
    "rednote": "creator.rednote.com",
    "tiktok": "www.tiktok.com",
    "instagram": "www.instagram.com",
    "facebook": "www.facebook.com",
    "facebook-page": "business.facebook.com",
    "youtube": "studio.youtube.com",
}
DOCUMENT_PATHS = {
    "xiaohongshu": ("/publish/publish",),
    "rednote": ("/publish/publish",),
    "tiktok": ("/tiktokstudio/upload",),
    "instagram": ("/",),
    "facebook": ("/",),
    "facebook-page": ("/latest/composer/",),
    "youtube": ("/",),
}
LOGIN_PATHS = {
    "xiaohongshu": "/website-login",
    "rednote": "/website-login",
    "tiktok": "/login",
    "instagram": "/accounts/login/",
    "facebook": "/login/",
    "facebook-page": "/login/",
    "youtube": "/signin",
}
VERIFICATION_PATHS = {
    "xiaohongshu": "/website-login/captcha",
    "rednote": "/website-login/captcha",
    "tiktok": "/verify",
}
LOGIN_REASONS = {
    "xiaohongshu": "小红书登录态无效",
    "rednote": "Rednote登录态无效",
    "tiktok": "TikTok登录态无效",
    "instagram": "Instagram登录态无效",
    "facebook": "Facebook登录态无效",
    "facebook-page": "facebook-page 登录态无效",
    "youtube": "YouTube登录态无效",
}
VERIFICATION_REASONS = {
    "xiaohongshu": "小红书要求人机验证",
    "rednote": "Rednote要求人机验证",
    "tiktok": "TikTok 上传过程中需要重新登录",
}


def _respond(
    handler: BaseHTTPRequestHandler,
    data: bytes,
    content_type: str,
    status: int = 200,
):
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    try:
        handler.wfile.write(data)
    except OSError:
        pass


class CheckSite:
    """Controlled platform pages served on the hostnames Chromium maps offline."""

    def __init__(self) -> None:
        self.outcome = {platform: "valid" for platform in PLATFORMS}
        self.requests: list[tuple[str, str, str]] = []
        self.documents: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def handler(self, platform: str):
        site = self

        class Site(Handler):
            def do_GET(self):
                path = urlsplit(self.path).path
                with site._lock:
                    site.requests.append((self.headers.get("Host", ""), platform, path))
                site._serve(platform, path, self)

        return Site

    def _serve(self, platform, path, handler):
        if path == "/favicon.ico":
            _respond(handler, b"", "image/x-icon")
            return
        if path == "/ready.js":
            _respond(handler, b"", "application/javascript")
            return
        if not any(path == prefix for prefix in DOCUMENT_PATHS[platform]):
            self._serve_secondary(platform, path, handler)
            return

        with self._lock:
            self.documents.append((platform, path))
        outcome = self.outcome[platform]
        if outcome == "timeout":
            # Longer than every platform navigation timeout in use (20-30s).
            time.sleep(25)
            _respond(handler, b"", "text/html")
            return
        if outcome == "server-error":
            handler.send_error(503)
            return
        if outcome == "structure":
            _respond(
                handler,
                b"<html><body><p>no known login or editor anchor</p></body></html>",
                "text/html; charset=utf-8",
            )
            return
        if outcome == "login":
            self._send_redirect(handler, LOGIN_PATHS[platform])
            return
        if outcome == "verification":
            self._send_redirect(handler, VERIFICATION_PATHS[platform])
            return

        if platform in ("xiaohongshu", "rednote"):
            body = (FIXTURES / "xhs_creator.html").read_bytes()
            _respond(handler, body, "text/html; charset=utf-8")
        elif platform == "tiktok":
            body = (FIXTURES / "tiktok_composer.html").read_bytes()
            _respond(handler, body, "text/html; charset=utf-8")
        elif platform == "instagram":
            body = (FIXTURES / "instagram_composer.html").read_bytes()
            _respond(handler, body, "text/html; charset=utf-8")
        elif platform == "facebook":
            body = (FIXTURES / "facebook" / "personal.html").read_bytes()
            _respond(handler, body, "text/html; charset=utf-8")
        elif platform == "facebook-page":
            body = (FIXTURES / "facebook" / "business.html").read_bytes()
            _respond(handler, body, "text/html; charset=utf-8")
        elif platform == "youtube":
            self._send_redirect(handler, "/channel/offline")

    def _serve_secondary(self, platform, path, handler):
        if platform == "youtube" and path.startswith("/channel/"):
            _respond(handler, b"<html><body>Offline Studio</body></html>", "text/html")
            return
        _respond(handler, b"<html><body>offline</body></html>", "text/html")

    @staticmethod
    def _send_redirect(handler, location):
        handler.send_response(302)
        handler.send_header("Location", location)
        handler.send_header("Content-Length", "0")
        handler.end_headers()


class BitBrowserAPI:
    """Loopback BitBrowser Local API with per-endpoint response queues."""

    def __init__(self, profile: OfflineProfile) -> None:
        self.profile = profile
        self.active = False
        self.port = urlsplit(profile.endpoint).port
        self.calls: list[dict] = []
        self.queues: dict[str, deque[dict]] = defaultdict(deque)
        self._lock = threading.Lock()

    def queue(self, path: str, *, status: int = 200, payload=None, delay: float = 0.0):
        self.queues[path].append(
            {"status": status, "payload": payload, "delay": delay}
        )

    def paths(self) -> list[str]:
        return [call["path"] for call in self.calls]

    def _default(self, path: str) -> dict:
        if path == "/health":
            return {"success": True, "data": {}}
        if path == "/browser/pids/alive":
            return {
                "success": True,
                "data": [WINDOW_ID] if self.active else [],
            }
        if path == "/browser/ports":
            data = {WINDOW_ID: str(self.port)} if self.active else {}
            return {"success": True, "data": data}
        if path == "/browser/open":
            return {"success": True, "data": {"ws": self.profile.endpoint}}
        if path == "/browser/close":
            return {"success": True, "data": {}}
        return None

    def _handle(self, handler: BaseHTTPRequestHandler):
        path = urlsplit(handler.path).path
        length = int(handler.headers.get("Content-Length") or 0)
        raw = handler.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            body = None
        with self._lock:
            self.calls.append(
                {
                    "path": path,
                    "body": body,
                    "key": handler.headers.get("x-api-key"),
                }
            )
            queued = self.queues[path].popleft() if self.queues[path] else None

        if queued is not None and queued["delay"]:
            time.sleep(queued["delay"])

        default = self._default(path)
        payload = queued["payload"] if queued and queued["payload"] is not None else default
        status = queued["status"] if queued else 200

        if path == "/browser/open" and status == 200 and isinstance(payload, dict):
            if payload.get("success") is True:
                self.active = True
        if path == "/browser/close" and status == 200 and isinstance(payload, dict):
            if payload.get("success") is True:
                self.active = False

        if payload is None:
            handler.send_error(404)
            return
        _respond(
            handler,
            json.dumps(payload).encode("utf-8"),
            "application/json; charset=utf-8",
            status=status,
        )

    def handler(self):
        api = self

        class Provider(Handler):
            def do_POST(self):
                api._handle(self)

        return Provider


@dataclass(slots=True)
class CheckResult:
    code: int
    out: str
    err: str
    logs: list[str]


class Harness:
    def __init__(self, profile, api, site, api_port):
        self.profile = profile
        self.api = api
        self.site = site
        self.api_port = api_port

    def _environment(self, env=None):
        return {
            "MLX_API_TOKEN": "",
            "ADSPOWER_API_KEY": "",
            "ADSPOWER_API_BASE": "",
            "BITBROWSER_API_KEY": KEY,
            "BITBROWSER_API_BASE": f"http://127.0.0.1:{self.api_port}",
            **(env or {}),
        }

    def reset(self):
        self.api.active = False
        with self.api._lock:
            self.api.calls.clear()
            self.api.queues.clear()
        self.site.outcome = {platform: "valid" for platform in PLATFORMS}
        with self.site._lock:
            self.site.requests.clear()
            self.site.documents.clear()
        pages = list(self.profile.browser.contexts[0].pages)
        for page in pages[1:]:
            if not page.is_closed():
                page.close()
        if not pages:
            self.profile.browser.contexts[0].new_page()

    def run(
        self,
        platform: str,
        *,
        outcome: str | None = None,
        profile_id: str = WINDOW_ID,
        env: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> CheckResult:
        if outcome is not None:
            self.site.outcome[platform] = outcome
        values = self._environment(env)
        out_buffer = io.StringIO()
        err_buffer = io.StringIO()
        logs: list[str] = []
        sink = logger.add(lambda message: logs.append(str(message)), format="{message}")
        state: dict[str, object] = {}

        def call_cli():
            try:
                with patch.dict(os.environ, values, clear=False):
                    with redirect_stdout(out_buffer), redirect_stderr(err_buffer):
                        state["code"] = sau_cli.main(
                            [
                                platform,
                                "check",
                                "--profile-id",
                                profile_id,
                            ]
                        )
            except BaseException as exc:  # pragma: no cover - surfaced below
                state["error"] = exc

        try:
            # ``sync_playwright`` owns this thread's event loop; the CLI must
            # create its own loop in a worker thread.
            worker = threading.Thread(target=call_cli)
            worker.start()
            worker.join(timeout)
            if worker.is_alive():
                raise TimeoutError(f"{platform} check did not finish in {timeout}s")
            if "error" in state:
                raise state["error"]
        finally:
            logger.remove(sink)
        return CheckResult(
            code=state.get("code", 1),
            out=out_buffer.getvalue(),
            err=err_buffer.getvalue(),
            logs=logs,
        )


@pytest.fixture(scope="module")
def browser_harness(tmp_path_factory):
    root = tmp_path_factory.mktemp("bitbrowser-checks")
    with ExitStack() as stack:
        playwright = stack.enter_context(sync_playwright())
        site = CheckSite()
        profile = OfflineProfile(
            root,
            stack,
            [],
            playwright,
            sites={
                HOSTS[platform]: site.handler(platform)
                for platform in PLATFORMS
            },
        )
        api = BitBrowserAPI(profile)
        api_port = stack.enter_context(serve(api.handler()))
        profile.api_port = api_port
        yield Harness(profile, api, site, api_port)


@pytest.fixture
def harness(browser_harness):
    browser_harness.reset()
    return browser_harness


def _page_targets(profile):
    cdp = profile.browser.new_browser_cdp_session()
    try:
        return cdp.send("Target.getTargets")["targetInfos"]
    finally:
        cdp.detach()


def test_seven_platform_checks_each_open_one_new_page_and_close_once(harness):
    profile, api, site = harness.profile, harness.api, harness.site
    base = profile.browser.contexts[0].pages[0]
    base.set_content("<textarea id='desktop'>desktop draft</textarea>")

    created: list[dict] = []
    destroyed: list[str] = []
    cdp = profile.browser.new_browser_cdp_session()
    cdp.on(
        "Target.targetCreated",
        lambda event: created.append(event["targetInfo"]),
    )
    cdp.on(
        "Target.targetDestroyed",
        lambda event: destroyed.append(event["targetId"]),
    )
    cdp.send("Target.setDiscoverTargets", {"discover": True})
    cdp.send("Target.getTargets")
    created.clear()
    destroyed.clear()

    try:
        for platform in PLATFORMS:
            closes_before = len([p for p in api.paths() if p == "/browser/close"])
            opens_before = len([p for p in api.paths() if p == "/browser/open"])
            result = harness.run(platform, profile_id=f"  {WINDOW_ID}  ")
            cdp.send("Target.getTargets")

            assert result.code == 0, (platform, result.err, result.logs)
            assert result.out.splitlines() == ["valid"], (platform, result.out)
            assert any("mode=bitbrowser" in line for line in result.logs), result.logs
            assert KEY not in result.out + result.err + "".join(result.logs)

            assert site.documents[-1][0] == platform
            assert len(site.documents) == PLATFORMS.index(platform) + 1
            platform_hosts = {
                host for host, name, _ in site.requests if name == platform
            }
            assert platform_hosts == {HOSTS[platform]}, platform_hosts

            paths = api.paths()
            assert paths.count("/browser/open") == opens_before + 1
            assert paths.count("/browser/close") == closes_before + 1
            close_bodies = [
                call["body"]
                for call in api.calls
                if call["path"] == "/browser/close"
            ]
            assert close_bodies[-1] == {"id": WINDOW_ID}
            assert all(call["key"] == KEY for call in api.calls)
            assert not any("opened" in path for path in paths)
            assert not any("version" in path for path in paths)

            page_targets = [target for target in created if target["type"] == "page"]
            assert len(page_targets) == 1, (platform, page_targets)
            assert page_targets[0]["targetId"] in destroyed

            pages = profile.browser.contexts[0].pages
            assert len(profile.browser.contexts) == 1
            assert base.locator("textarea").input_value() == "desktop draft"
            assert not any(
                HOSTS[platform] in page.url for page in pages
            ), [page.url for page in pages]

            created.clear()
            destroyed.clear()
    finally:
        cdp.detach()

    assert api.paths().count("/browser/open") == len(PLATFORMS)
    assert api.paths().count("/browser/close") == len(PLATFORMS)
    for call in api.calls:
        if call["path"] == "/browser/pids/alive":
            assert call["body"] == {"ids": [WINDOW_ID]}
        if call["path"] == "/browser/open":
            assert call["body"].get("id") == WINDOW_ID


@pytest.mark.parametrize("platform", PLATFORMS)
def test_platform_login_page_exits_10_without_publish_token(harness, platform):
    result = harness.run(platform, outcome="login")

    assert result.code == 10, (platform, result.err)
    assert LOGIN_REASONS[platform] in result.err
    assert "比特浏览器" in result.err
    assert "publish_attempted=true" not in result.err.splitlines()
    assert KEY not in result.out + result.err + "".join(result.logs)
    if platform in ("xiaohongshu", "rednote"):
        assert result.out.splitlines() == ["invalid"]
    else:
        assert result.out == ""
    # The command joined the window, so its departure closes the window once.
    assert [call["body"] for call in harness.api.calls if call["path"] == "/browser/close"] == [
        {"id": WINDOW_ID}
    ]


@pytest.mark.parametrize("platform", ("xiaohongshu", "rednote", "tiktok"))
def test_platform_verification_page_exits_10_and_preserves_reason(harness, platform):
    result = harness.run(platform, outcome="verification")

    assert result.code == 10, (platform, result.err)
    assert VERIFICATION_REASONS[platform] in result.err
    assert "publish_attempted=true" not in result.err.splitlines()
    assert KEY not in result.out + result.err + "".join(result.logs)
    if platform in ("xiaohongshu", "rednote"):
        assert result.out.splitlines() == ["invalid"]


def test_platform_site_5xx_exits_1(harness):
    result = harness.run("xiaohongshu", outcome="server-error")

    assert result.code == 1, result.err
    assert "HTTP 503" in result.err
    assert "publish_attempted=true" not in result.err.splitlines()
    assert result.out.splitlines() == ["invalid"]


def test_platform_structural_anomaly_exits_1(harness):
    result = harness.run("instagram", outcome="structure")

    assert result.code == 1, result.err
    assert "未出现可确认登录状态的元素" in result.err
    assert "publish_attempted=true" not in result.err.splitlines()


def test_platform_probe_timeout_exits_1(harness):
    result = harness.run("tiktok", outcome="timeout", timeout=45)

    assert result.code == 1, result.err
    assert "timeout" in result.err.lower() or "超时" in result.err
    assert "publish_attempted=true" not in result.err.splitlines()


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_desktop_service_unreachable_exits_1_before_any_page(harness):
    result = harness.run(
        "tiktok",
        env={"BITBROWSER_API_BASE": f"http://127.0.0.1:{_closed_port()}"},
        timeout=20,
    )

    assert result.code == 1, result.err
    assert "探活比特浏览器 Local API" in result.err
    assert "无法连接" in result.err
    assert "同一台机器" in result.err
    assert KEY not in result.out + result.err + "".join(result.logs)
    assert harness.api.calls == []
    assert harness.site.documents == []


def test_token_rejected_401_exits_1_with_actionable_redacted_reason(harness):
    harness.api.queue(
        "/health", status=401, payload={"success": False, "msg": "unauthorized"}
    )

    result = harness.run("tiktok")

    assert result.code == 1, result.err
    assert "探活比特浏览器 Local API" in result.err
    assert "HTTP 401" in result.err
    assert "BITBROWSER_API_KEY" in result.err
    assert "Token" in result.err
    assert KEY not in result.out + result.err + "".join(result.logs)
    assert harness.api.paths() == ["/health"]
    assert harness.site.documents == []


def test_missing_window_exits_1_and_reports_start_operation(harness):
    harness.api.queue(
        "/browser/open",
        payload={"success": False, "msg": "窗口不存在"},
    )

    result = harness.run("tiktok")

    assert result.code == 1, result.err
    assert "启动比特浏览器窗口失败" in result.err
    assert "窗口不存在" in result.err
    assert "停止" not in result.err
    assert KEY not in result.out + result.err + "".join(result.logs)
    assert harness.api.paths().count("/browser/open") == 1
    assert harness.api.paths().count("/browser/close") == 0
    assert harness.site.documents == []


def test_pre_publish_cdp_connect_failure_exits_1_with_actionable_hint(harness):
    harness.api.queue(
        "/browser/open",
        payload={
            "success": True,
            "data": {
                "ws": (
                    "ws://127.0.0.1:"
                    f"{_closed_port()}/devtools/browser/"
                    "00000000-0000-0000-0000-000000000000"
                )
            },
        },
    )

    result = harness.run("tiktok", timeout=30)

    assert result.code == 1, result.err
    assert "CDP" in result.err
    assert "调试" in result.err
    assert KEY not in result.out + result.err + "".join(result.logs)
    assert harness.api.paths().count("/browser/open") == 1
    assert harness.api.paths().count("/browser/close") == 0
    assert harness.site.documents == []


def test_api_probe_timeout_exits_1_with_timeout_diagnostic(harness):
    harness.api.queue("/health", delay=4)

    result = harness.run("tiktok", timeout=20)

    assert result.code == 1, result.err
    assert "探活比特浏览器 Local API" in result.err
    assert "请求超时" in result.err
    assert "3 秒" in result.err
    assert harness.api.paths() == ["/health"]
    assert harness.site.documents == []


@pytest.mark.parametrize(
    ("endpoint", "expected_paths"),
    (
        ("/health", ["/health"]),
        ("/browser/pids/alive", ["/health", "/browser/pids/alive"]),
        (
            "/browser/open",
            ["/health", "/browser/pids/alive", "/browser/open"],
        ),
    ),
    ids=("probe", "query", "start"),
)
def test_http_429_exits_11_without_retry(harness, endpoint, expected_paths):
    harness.api.queue(
        endpoint, status=429, payload={"success": False, "msg": "too many"}
    )

    result = harness.run("tiktok", timeout=20)

    assert result.code == 11, result.err
    assert "429" in result.err
    assert harness.api.paths() == expected_paths
    assert harness.site.documents == []
    assert harness.api.paths().count("/browser/close") == 0


@pytest.mark.parametrize(
    ("endpoint", "expected_paths"),
    (
        ("/health", ["/health"]),
        ("/browser/pids/alive", ["/health", "/browser/pids/alive"]),
        (
            "/browser/open",
            ["/health", "/browser/pids/alive", "/browser/open"],
        ),
    ),
    ids=("probe", "query", "start"),
)
def test_business_frequency_text_is_exit_1_not_429(
    harness, endpoint, expected_paths
):
    harness.api.queue(
        endpoint,
        payload={"success": False, "msg": "请求频繁，请稍后再试"},
    )

    result = harness.run("tiktok", timeout=20)

    assert result.code == 1, result.err
    assert "HTTP 200" in result.err
    assert "请求频繁" in result.err
    assert harness.api.paths() == expected_paths
    assert harness.site.documents == []
    assert harness.api.paths().count("/browser/close") == 0


def test_unrecognized_business_envelope_is_exit_1(harness):
    harness.api.queue("/health", payload={"ok": True})

    result = harness.run("tiktok", timeout=20)

    assert result.code == 1, result.err
    assert "success" in result.err
    assert harness.api.paths() == ["/health"]
    assert harness.site.documents == []


@pytest.mark.parametrize(("data", "diagnostic"), [
    ("nonsense", "data"),
    ({WINDOW_ID: None}, "进程 ID"),
    ({"wrapped": {WINDOW_ID: 123}}, "进程 ID"),
    ([1234], "窗口 ID"),
    ({"different-window": 123}, "与请求不符"),
])
def test_unrecognized_query_data_is_exit_1(harness, data, diagnostic):
    harness.api.queue("/browser/pids/alive", payload={"success": True, "data": data})

    result = harness.run("tiktok", timeout=20)

    assert result.code == 1, result.err
    assert diagnostic in result.err
    assert harness.api.paths() == ["/health", "/browser/pids/alive"]
    assert harness.site.documents == []


def test_ports_404_on_running_window_exits_1_before_opening_page(harness):
    harness.api.active = True
    harness.api.queue(
        "/browser/ports", status=404, payload={"success": False, "msg": "not found"}
    )

    result = harness.run("tiktok", timeout=20)

    assert result.code == 1, result.err
    assert "查询比特浏览器窗口调试端口失败" in result.err
    assert "HTTP 404" in result.err
    assert "BITBROWSER_API_BASE" in result.err
    assert "超时" not in result.err
    assert KEY not in result.out + result.err + "".join(result.logs)
    assert harness.site.documents == []
    assert harness.api.paths().count("/browser/open") == 0
    assert harness.api.paths().count("/browser/close") == 0
    assert harness.api.active is True


def test_ports_timeout_on_running_window_exits_1_before_opening_page(harness):
    harness.api.active = True
    harness.api.queue("/browser/ports", delay=31)

    result = harness.run("tiktok", timeout=45)

    assert result.code == 1, result.err
    assert "查询比特浏览器窗口调试端口失败" in result.err
    assert "请求超时" in result.err
    assert "30 秒" in result.err
    assert "404" not in result.err
    assert KEY not in result.out + result.err + "".join(result.logs)
    assert harness.site.documents == []
    assert harness.api.paths().count("/browser/open") == 0
    assert harness.api.paths().count("/browser/close") == 0
    assert harness.api.active is True


def test_missing_opened_list_and_opened_filter_do_not_matter(harness):
    harness.api.active = True
    harness.api.queue(
        "/browser/opened/ids",
        status=404,
        payload={"success": False, "msg": "not found"},
    )
    harness.api.queue(
        "/browser/list",
        status=404,
        payload={"success": False, "msg": "not found"},
    )

    result = harness.run("tiktok")

    assert result.code == 0, result.err
    assert result.out.splitlines() == ["valid"]
    paths = harness.api.paths()
    assert "/browser/opened/ids" not in paths
    assert "/browser/list" not in paths
    assert not any("opened" in path for path in paths)
    assert not any("version" in path for path in paths)
    assert paths.count("/browser/ports") == 1
    assert paths.count("/browser/close") == 1
