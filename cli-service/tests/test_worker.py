"""Worker configuration and full outbound snapshots, using Local API wire fixtures."""
import json
from pathlib import Path
import sys

import httpx
import pytest

from sau_worker.worker import Settings, Worker


def test_desktop_defaults_and_local_override():
    defaults = Settings.from_env({"SAU_DESKTOP_TOKEN": "fixture"})
    assert defaults.gateway == "https://social-media-web-api.connexup-dev.net"
    assert defaults.capacity == 1
    assert Path(defaults.cli[0]).is_absolute()
    local = Settings.from_env({"SAU_DESKTOP_TOKEN": "fixture", "SAU_GATEWAY_URL": "http://127.0.0.1:8080",
                               "WORKER_MAX_CONCURRENCY": "3", "SAU_CLI_PATH": sys.executable})
    assert (local.gateway, local.capacity, local.cli) == ("http://127.0.0.1:8080", 3, (sys.executable,))
    with pytest.raises(ValueError):
        Settings.from_env({"SAU_DESKTOP_TOKEN": "fixture", "SAU_GATEWAY_URL": "http://example.com"})


@pytest.mark.asyncio
async def test_reconnect_reports_pages_additions_removals_and_one_provider_offline(tmp_path):
    snapshots = []
    changed = False
    def endpoint(request):
        body = json.loads(request.content)
        if request.url.host == "gateway.test":
            assert request.headers["Authorization"] == "Bearer desk"
            assert "local-token" not in request.content.decode()
            snapshots.append(body)
            return httpx.Response(200, json={"lastContactAt": "2026-01-01T00:00:00Z"})
        page = body["page"]
        if request.url.path == "/browser/list":
            assert request.headers["x-api-key"] == "local-token-bit"
            assert "authorization" not in request.headers
            size = body["pageSize"]
            if changed:
                return httpx.Response(503)
            ids = [str(i) for i in range(size)] if page == 0 else ["last"]
            return httpx.Response(200, json={"success": True, "data": {"list": [{"id": i, "name": i} for i in ids]}})
        assert request.url.path == "/api/v2/browser-profile/list"
        assert request.headers["Authorization"] == "Bearer local-token-ads"
        size = body["limit"]
        ids = [str(i) for i in range(size)] if page == 1 else ["added" if changed else "removed"]
        return httpx.Response(200, json={"code": 0, "data": {"list": [
            {"profile_id": i, "name": i, "password": "must-remain-local"} for i in ids]}})
    config = Settings.from_env({"SAU_GATEWAY_URL": "https://gateway.test", "SAU_CLI_PATH": str(tmp_path / "uninstalled-sau"),
                                "SAU_DESKTOP_TOKEN": "desk",
                                "BITBROWSER_API_KEY": "local-token-bit", "ADSPOWER_API_KEY": "local-token-ads"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as client:
        worker = Worker(config, client)
        await worker.report()
        changed = True
        await worker.report()
        other = Worker(config, client)
        await other.report()
    assert snapshots[0]["sessionId"] == snapshots[1]["sessionId"] != snapshots[2]["sessionId"]
    providers = {p["provider"]: p for p in snapshots[0]["providers"]}
    assert {"profileId": "last", "name": "last"} in providers["bitbrowser"]["profiles"]
    updated = {p["provider"]: p for p in snapshots[1]["providers"]}
    assert updated["bitbrowser"] == {"provider": "bitbrowser", "available": False, "profiles": []}
    assert updated["adspower"]["profiles"][-1] == {"profileId": "added", "name": "added"}
    assert all(p["profileId"] != "removed" for p in updated["adspower"]["profiles"])
    assert "must-remain-local" not in str(snapshots)


@pytest.mark.asyncio
async def test_run_resends_full_session_after_connection_loss(tmp_path):
    reports = []
    class ObservedReconnect(Exception):
        pass

    def gateway(request):
        assert request.url.path == "/session"
        reports.append(json.loads(request.content))
        if len(reports) == 1:
            raise httpx.ConnectError("fixture offline", request=request)
        raise ObservedReconnect()

    config = Settings.from_env({"SAU_GATEWAY_URL": "https://gateway.test", "SAU_CLI_PATH": str(tmp_path / "uninstalled-sau"),
                                "SAU_DESKTOP_TOKEN": "desk"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as client:
        with pytest.raises(ObservedReconnect):
            await Worker(config, client).run()
    assert reports[0]["sessionId"] == reports[1]["sessionId"]
    assert reports[1]["providers"] == []
    assert reports[1]["capacity"] == reports[1]["freeSlots"] == 1
    assert "cliRelease" in reports[1]
