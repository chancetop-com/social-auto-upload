"""Publish protocol as seen by Postiz and two independent desktops."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from uuid import uuid4

import pytest

INTERNAL = {"Authorization": "Bearer fixture-internal"}
DESKTOP = {"Authorization": "Bearer fixture-desktop"}


def video(workflow):
    return {
        "workflowId": workflow, "contractVersion": 1, "release": "0.1.0",
        "requiredCapability": "tiktok.upload-video", "platform": "tiktok", "action": "upload-video",
        "organizationId": "org", "bindingId": "binding", "postId": "post", "channelId": "channel",
        "provider": "local-chrome", "profileId": "operator-approved", "caption": "Old caption", "settings": {},
        "media": [{"id": "v", "url": "https://media.example/first.mp4", "role": "video"}],
        "earliestPublishAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "noPublish": False,
    }


def register(gateway):
    session = str(uuid4())
    report = {
        "sessionId": session, "mode": "worker", "release": "0.1.0", "cliRelease": "0.1.0",
        "contractVersion": 1, "capacity": 1, "freeSlots": 1,
        "capabilities": [{"platform": "tiktok", "action": "upload-video"}],
        "providers": [{"provider": "local-chrome", "available": True,
                       "profiles": [{"profileId": "operator-approved", "name": "operator-approved"}]}],
    }
    gateway.post("/session", json=report, headers=DESKTOP).raise_for_status()
    return session


@pytest.fixture
def postiz(monkeypatch):
    requests = []
    reply = {"status": 200, "task": None}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, self.headers.get("Authorization"), body))
            self.send_response(reply["status"])
            self.end_headers()
            self.wfile.write(json.dumps(reply["task"]).encode())

        def log_message(self, *_):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        monkeypatch.setenv("POSTIZ_INTERNAL_URL", f"http://127.0.0.1:{server.server_port}/api")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield requests, reply
        finally:
            server.shutdown()
            thread.join()


def claim(gateway, session):
    return gateway.post("/publish-task/claim", headers=DESKTOP,
                        json={"sessionId": session, "waitSeconds": 0}).json()["task"]


def test_one_start_grants_latest_content_and_settles_original_occurrence(postiz, gateway):
    requests, reply = postiz
    task = video("repeatable/post/one")
    other, owner = register(gateway), register(gateway)
    gateway.post("/internal/occurrences", headers=INTERNAL, json=task).raise_for_status()
    assert claim(gateway, owner)["task"] == task
    reply["task"] = {**task, "caption": "Edited caption", "earliestPublishAt": "2026-11-27T13:00:00Z"}
    start = {"workflowId": task["workflowId"], "sessionId": owner}
    assert gateway.post("/publish-task/start", headers=DESKTOP, json={**start, "sessionId": other}).status_code == 409
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: gateway.post("/publish-task/start", headers=DESKTOP, json=start), range(2)))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert next(r.json() for r in results if r.is_success) == {"task": reply["task"]}
    assert requests == [("/api/internal/browser-publishing/authorize-start", "Bearer fixture-internal",
                         {"workflowId": task["workflowId"], "postId": "post", "organizationId": "org"})]
    receipt = {"outcome": "published", "cliInvoked": True, "exitCode": 0}
    record = gateway.post("/publish-task/result", headers=DESKTOP, json={**start, "receipt": receipt}).json()
    assert (record["state"], record["receipt"]) == ("succeeded", receipt)
    assert gateway.post("/internal/occurrences", headers=INTERNAL, json=task).json() == record
    assert gateway.get("/internal/occurrences/" + task["workflowId"], headers=INTERNAL).json() == record
    assert gateway.post("/publish-task/start", headers=DESKTOP, json=start).status_code == 409


def test_competing_desktops_serialize_a_profile_platform_until_settlement(postiz, gateway):
    first, second = video("one"), video("two")
    for task in first, second:
        gateway.post("/internal/occurrences", headers=INTERNAL, json=task).raise_for_status()
    sessions = [register(gateway), register(gateway)]
    with ThreadPoolExecutor(2) as pool:
        records = list(pool.map(lambda session: claim(gateway, session), sessions))
    assert sum(record is not None for record in records) == 1
    index = next(i for i, record in enumerate(records) if record)
    owner, other = sessions[index], sessions[1-index]
    original = records[index]["task"]
    assert claim(gateway, other) is None
    postiz[1]["task"] = original
    identity = {"workflowId": original["workflowId"], "sessionId": owner}
    gateway.post("/publish-task/start", json=identity, headers=DESKTOP).raise_for_status()
    assert claim(gateway, other) is None
    receipt = {"outcome": "published", "cliInvoked": True, "exitCode": 0}
    gateway.post("/publish-task/result", json={**identity, "receipt": receipt}, headers=DESKTOP).raise_for_status()
    lease = {**identity, "leaseGrantId": records[index]["leaseGrantId"]}
    assert gateway.post("/profile-lease/complete", json=lease, headers=DESKTOP).json() == {"idle": True}
    assert claim(gateway, other) is None
    gateway.post("/profile-lease/release", json={**lease, "windowClosed": True}, headers=DESKTOP).raise_for_status()
    following = claim(gateway, other)
    assert following["workflowId"] != original["workflowId"]
    assert following["task"]["postId"] == original["postId"]


@pytest.mark.parametrize("failure", ["inventory", "wrong-cli-release", "revoked", "stale", "unavailable", "changed-target"])
def test_unavailable_start_never_grants_a_task_or_permits_replay(postiz, gateway, failure):
    requests, reply = postiz
    task = video("no-start")
    session = register(gateway)
    gateway.post("/internal/occurrences", headers=INTERNAL, json=task).raise_for_status()
    assert claim(gateway, session)["task"] == task
    if failure in ("inventory", "wrong-cli-release"):
        report = gateway.get("/internal/sessions/" + session, headers=INTERNAL).json()
        del report["lastContactAt"]
        if failure == "inventory":
            report["providers"][0].update(available=False, profiles=[])
        else:
            report["cliRelease"] = "incompatible"
        gateway.post("/session", json=report, headers=DESKTOP).raise_for_status()
    reply["status"] = {"revoked": 403, "stale": 409, "unavailable": 503}.get(failure, 200)
    reply["task"] = {**task, "profileId": "other"} if failure == "changed-target" else task
    identity = {"workflowId": task["workflowId"], "sessionId": session}
    result = gateway.post("/publish-task/start", headers=DESKTOP, json=identity)
    assert result.status_code in (403, 409, 503) and "task" not in result.json()
    assert gateway.post("/publish-task/start", headers=DESKTOP, json=identity).status_code == 409
    assert len(requests) == (0 if failure in ("inventory", "wrong-cli-release") else 1)
    record = gateway.get("/internal/occurrences/no-start", headers=INTERNAL).json()
    if failure == "unavailable":
        assert record["state"] == "claimed" and record["receipt"] is None
    else:
        assert record["state"] == "failed"
        assert record["receipt"] == {"cliInvoked": False, "exitCode": None, "outcome": "failed"}


def test_only_original_owner_can_settle_authorized_mode_once(postiz, gateway):
    task = {**video("preparation"), "noPublish": True, "earliestPublishAt": None}
    session = register(gateway)
    gateway.post("/internal/occurrences", headers=INTERNAL, json=task).raise_for_status()
    assert claim(gateway, session)["task"] == task
    identity = {"sessionId": session, "workflowId": task["workflowId"]}
    prepared = {"outcome": "prepared", "cliInvoked": True, "exitCode": 0}
    def finish(receipt, **overrides):
        return gateway.post("/publish-task/result", headers=DESKTOP, json={**identity, "receipt": receipt, **overrides})
    assert finish(prepared).status_code == 409
    postiz[1]["task"] = task
    gateway.post("/publish-task/start", json=identity, headers=DESKTOP).raise_for_status()
    assert finish(prepared, sessionId=str(uuid4())).status_code == 409
    assert finish({**prepared, "outcome": "published"}).status_code == 409
    assert finish(prepared).json()["state"] == "prepared"
    assert finish({"outcome": "unknown", "cliInvoked": True, "exitCode": 9}).json()["receipt"] == prepared


def test_shutdown_drains_existing_work_without_granting_new_starts(postiz, gateway_env):
    import asyncio
    from fastapi.testclient import TestClient
    from sau_gateway.app import create_app

    stopping = asyncio.Event()
    with TestClient(create_app(stopping)) as gateway:
        session = register(gateway)
        task = video("shutdown-start")
        gateway.post("/internal/occurrences", headers=INTERNAL, json=task).raise_for_status()
        assert claim(gateway, session)["task"] == task
        postiz[1]["task"] = task
        stopping.set()
        reply = gateway.post("/publish-task/start", headers=DESKTOP,
                             json={"workflowId": task["workflowId"], "sessionId": session})
        assert reply.status_code == 503 and not postiz[0]
        assert gateway.get("/internal/occurrences/shutdown-start", headers=INTERNAL).json()["state"] == "claimed"
