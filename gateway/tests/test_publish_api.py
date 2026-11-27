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


def register(gateway, actions=("upload-video",), prepared=True):
    session = str(uuid4())
    report = {
        "sessionId": session, "mode": "worker", "release": "0.1.0", "cliRelease": "0.1.0",
        "contractVersion": 1, "preparedStarts": prepared, "capacity": 1, "freeSlots": 1,
        "capabilities": [{"platform": "tiktok", "action": action} for action in actions],
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
            status, data = reply["status"], reply["task"]
            if status == 200 and body.get("preparedMedia") != data["media"]:
                status, data = 412, {"task": data}
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

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


def start_upload(gateway, identity, task):
    return gateway.post("/publish-task/start", headers=DESKTOP, json={**identity, "preparedMedia": task["media"]})


def test_publish_claim_requires_a_desktop_that_can_confirm_prepared_media(gateway):
    task = video("mixed-desktop-releases")
    gateway.post("/internal/occurrences", headers=INTERNAL, json=task).raise_for_status()
    assert claim(gateway, register(gateway, prepared=False)) is None
    assert claim(gateway, register(gateway))["task"] == task


def test_one_start_grants_latest_content_and_settles_original_occurrence(postiz, gateway):
    requests, reply = postiz
    task = video("repeatable/post/one")
    other, owner = register(gateway), register(gateway)
    gateway.post("/internal/occurrences", headers=INTERNAL, json=task).raise_for_status()
    claimed = claim(gateway, owner)
    assert claimed["task"] == task
    reply["task"] = {**task, "caption": "Edited caption", "earliestPublishAt": "2026-11-27T13:00:00Z"}
    start = {"workflowId": task["workflowId"], "sessionId": owner}
    assert start_upload(gateway, {**start, "sessionId": other}, task).status_code == 409
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: start_upload(gateway, start, task), range(2)))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert next(r.json() for r in results if r.is_success) == {"task": reply["task"]}
    assert requests == [("/api/internal/browser-publishing/authorize-start", "Bearer fixture-internal",
                         {"workflowId": task["workflowId"], "postId": "post", "organizationId": "org",
                          "resultDeadlineAt": claimed["resultDeadlineAt"], "preparedMedia": task["media"], "mediaFailed": False})]
    receipt = {"outcome": "published", "cliInvoked": True, "exitCode": 0}
    record = gateway.post("/publish-task/result", headers=DESKTOP, json={**start, "receipt": receipt}).json()
    assert (record["state"], record["receipt"]) == ("succeeded", receipt)
    assert gateway.post("/internal/occurrences", headers=INTERNAL, json=task).json() == record
    assert gateway.get("/internal/occurrences/" + task["workflowId"], headers=INTERNAL).json() == record
    assert start_upload(gateway, start, task).status_code == 409


@pytest.mark.parametrize("supports_images", [True, False])
def test_start_checks_the_latest_media_capability_on_the_original_lease(postiz, gateway, supports_images):
    task = video("edited-media")
    actions = ("upload-video", "upload-note") if supports_images else ("upload-video",)
    session = register(gateway, actions)
    gateway.post("/internal/occurrences", headers=INTERNAL, json=task).raise_for_status()
    claimed = claim(gateway, session)
    latest = {**task, "action": "upload-note", "requiredCapability": "tiktok.upload-note",
              "media": [{"id": "image", "role": "image", "url": "https://media.example/edit.jpg"}]}
    postiz[1]["task"] = latest
    identity = {"sessionId": session, "workflowId": task["workflowId"]}
    response = start_upload(gateway, identity, task)
    if supports_images:
        assert response.json() == {"prepare": latest}
        response = start_upload(gateway, identity, latest)
    record = gateway.get("/internal/occurrences/edited-media", headers=INTERNAL).json()
    assert record["leaseGrantId"] == claimed["leaseGrantId"]
    if supports_images:
        assert response.json() == {"task": latest}
        assert record["state"] == "started"
    else:
        assert response.status_code == 409
        assert record["receipt"]["cliInvoked"] is False
    assert start_upload(gateway, identity, task).status_code == 409


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
    start_upload(gateway, identity, original).raise_for_status()
    assert claim(gateway, other) is None
    receipt = {"outcome": "published", "cliInvoked": True, "exitCode": 0}
    gateway.post("/publish-task/result", json={**identity, "receipt": receipt}, headers=DESKTOP).raise_for_status()
    lease = {**identity, "leaseGrantId": records[index]["leaseGrantId"]}
    assert gateway.post("/publish-task/profile-lease/complete", json=lease, headers=DESKTOP).json() == {"idle": True}
    assert claim(gateway, other) is None
    gateway.post("/publish-task/profile-lease/release", json={**lease, "windowClosed": True}, headers=DESKTOP).raise_for_status()
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
    result = start_upload(gateway, identity, task)
    assert result.status_code in (403, 409, 503) and "task" not in result.json()
    assert start_upload(gateway, identity, task).status_code == 409
    assert len(requests) == (0 if failure in ("inventory", "wrong-cli-release") else 1)
    record = gateway.get("/internal/occurrences/no-start", headers=INTERNAL).json()
    if failure == "unavailable":
        assert record["state"] == "claimed" and record["receipt"] is None
    else:
        assert record["state"] == "failed"
        expected = {"cliInvoked": False, "exitCode": None, "outcome": "failed"}
        if failure in ("revoked", "stale"):
            expected["reason"] = "authorization_declined"
        assert record["receipt"] == expected


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
    start_upload(gateway, identity, task).raise_for_status()
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
        reply = start_upload(gateway, {"workflowId": task["workflowId"], "sessionId": session}, task)
        assert reply.status_code == 503 and not postiz[0]
        assert gateway.get("/internal/occurrences/shutdown-start", headers=INTERNAL).json()["state"] == "claimed"


def test_preparation_can_download_without_claiming_or_authorizing_publication(gateway):
    from datetime import datetime, timedelta, timezone

    task = video("scheduled/@series|occurrence")
    session = register(gateway)
    offer = {"task": task, "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
    publish = {"workflowId": task["workflowId"], "sessionId": session}
    for _ in range(2):
        gateway.post("/internal/preparations", json=offer, headers=INTERNAL).raise_for_status()
    assert claim(gateway, session) is None  # Older desktops never receive maintenance work.
    modern = {"sessionId": session, "waitSeconds": 0, "acceptPreparation": True}
    response = gateway.post("/publish-task/claim", json=modern, headers=DESKTOP)
    assert response.json()["task"] == {"operation": "prepare", "workflowId": task["workflowId"], "task": task}
    assert gateway.post("/publish-task/claim", json=modern, headers=DESKTOP).json()["task"] is None
    assert start_upload(gateway, publish, task).status_code == 409
    assert gateway.get("/internal/occurrences/" + task["workflowId"], headers=INTERNAL).status_code == 404
    changed = {**task, "media": [{"id": "replacement", "role": "video", "url": "https://media.example/new.mp4"}]}
    gateway.post("/internal/occurrences", json=changed, headers=INTERNAL).raise_for_status()
    assert claim(gateway, register(gateway))["task"]["media"] == changed["media"]


@pytest.fixture
def short_deadline_gateway(gateway_env, monkeypatch):
    from fastapi.testclient import TestClient
    from sau_gateway.app import create_app
    monkeypatch.setenv("GATEWAY_RESULT_TIMEOUT_SECONDS", "2")
    with TestClient(create_app()) as client:
        yield client


def test_progress_result_deadline_and_late_receipt_preserve_evidence(postiz, short_deadline_gateway):
    import time
    gateway = short_deadline_gateway
    task = {**video("deadline-review"), "earliestPublishAt": None}
    postiz[1]["task"] = task
    owner = register(gateway)
    path = "/internal/occurrences/" + task["workflowId"]
    gateway.post("/internal/occurrences", headers=INTERNAL, json=task).raise_for_status()
    claimed = claim(gateway, owner)
    deadline = claimed["resultDeadlineAt"]
    identity = {"workflowId": task["workflowId"], "sessionId": owner}
    start_upload(gateway, identity, task).raise_for_status()
    def result(receipt):
        response = gateway.post("/publish-task/result", headers=DESKTOP, json={**identity, "receipt": receipt})
        response.raise_for_status()
        return response.json()
    progress = {"outcome": "processing", "cliInvoked": True, "exitCode": None}
    assert result(progress)["state"] == "started"
    time.sleep(2.01)
    overdue = gateway.get(path, headers=INTERNAL).json()
    assert (overdue["state"], overdue["resultDeadlineAt"], overdue["overdueAt"] is not None) == ("unknown", deadline, True)
    assert claim(gateway, register(gateway)) is None
    final = {"outcome": "published", "cliInvoked": True, "exitCode": 0, "releaseId": "abc"}
    assert result(final)["receipt"] == final
    assert result(progress)["receipt"] == final
    assert result(final)["resultDeadlineAt"] == deadline


@pytest.mark.parametrize("phase", ["pending", "claimed", "started"])
def test_postiz_revocation_settles_original_receipt_only_before_upload(gateway, postiz, phase):
    task = video("original/revoked")
    ref = {key: task[key] for key in ("workflowId", "organizationId", "postId")}
    gateway.post("/internal/occurrences", headers=INTERNAL, json=task).raise_for_status()
    path = "/internal/occurrences/revoke"
    assert gateway.post(path, headers=DESKTOP, json=ref).status_code == 401
    assert gateway.post(path, headers=INTERNAL, json={**ref, "organizationId": "foreign"}).status_code == 404
    session = register(gateway)
    identity = {"workflowId": task["workflowId"], "sessionId": session}
    if phase != "pending":
        assert claim(gateway, session)["workflowId"] == task["workflowId"]
    if phase == "started":
        postiz[1]["task"] = task
        start_upload(gateway, identity, task).raise_for_status()
    for _ in range(2):
        gateway.post(path, headers=INTERNAL, json=ref).raise_for_status()
    record = gateway.get("/internal/occurrences/" + task["workflowId"], headers=INTERNAL).json()
    if phase == "started":
        assert record["state"] == "started" and record["receipt"] is None
    else:
        assert record["state"] == "failed"
        assert record["receipt"] == {"outcome": "failed", "reason": "authorization_declined", "exitCode": None, "cliInvoked": False}
        assert record["receiptHistory"] == [record["receipt"]]
        assert claim(gateway, session) is None
        assert start_upload(gateway, identity, task).status_code == 409
