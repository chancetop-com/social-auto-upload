from hashlib import sha256
from uuid import uuid4

from fastapi.testclient import TestClient
from sau_gateway.app import create_app

DESKTOP = {"Authorization": "Bearer fixture-desktop"}
INTERNAL = {"Authorization": "Bearer fixture-internal"}
TARGET = "macos-arm64"


def artifact(gateway, revision="1" * 40):
    content = ("verified fixture bytes " + revision).encode()
    digest = sha256(content).hexdigest()
    url = "/internal/releases/packages/" + digest
    gateway.put(url, headers=INTERNAL, content=content).raise_for_status()
    return {"environment": "dev", "revision": revision, "version": "0.1.0", "contractVersion": 1,
            "packages": {TARGET: digest}}


def test_operator_registers_pinned_content_and_finds_same_release_after_restart(gateway):
    body = artifact(gateway)
    assert gateway.post("/internal/releases", headers=DESKTOP, json=body).status_code == 401
    release = gateway.post("/internal/releases", headers=INTERNAL, json=body).json()
    assert release["revision"] == body["revision"]
    assert gateway.post("/internal/releases", headers=INTERNAL, json=body).json()["releaseId"] == release["releaseId"]
    assert gateway.post("/internal/releases", headers=INTERNAL, json={**body, "environment": "uat"}).status_code == 422
    assert gateway.put("/internal/releases/packages/" + "0" * 64, headers=INTERNAL, content=b"wrong").status_code == 422
    with TestClient(create_app()) as restarted:
        status = restarted.get("/internal/releases/" + release["releaseId"], headers=INTERNAL).json()
        assert status["packages"] == body["packages"]
        url = "/session/release/packages/" + body["packages"][TARGET]
        assert restarted.get(url).status_code == 401
        assert restarted.get(url, headers=DESKTOP).content == ("verified fixture bytes " + body["revision"]).encode()


def post(client, path, body):
    res = client.post(path, json=body, headers=DESKTOP)
    res.raise_for_status()
    return res.json()


def poll(client, machine, **current):
    return post(client, "/session/release/discover", {"machineId": machine, "target": TARGET, **current})


def progress(client, machine, assignment, phase, **extra):
    return post(client, "/session/release/progress", {"machineId": machine, "releaseId": assignment["releaseId"],
                "batchId": assignment["batchId"], "phase": phase, **extra})


def session(client, machine, assignment, mode):
    sid = str(uuid4())
    report = {"sessionId": sid, "mode": mode, "release": "0.1.0", "cliRelease": "0.1.0", "preparedStarts": True, "contractVersion": 1,
              "capacity": 1, "freeSlots": 1, "capabilities": [{"platform": "tiktok", "action": "check"}],
              "providers": [{"provider": "local-chrome", "available": True,
                             "profiles": [{"name": "fixture", "profileId": "fixture"}]}],
              "installation": {"machineId": machine, **{k: assignment[k] for k in ("revision", "sha256", "target", "batchId")}}}
    post(client, "/session", report)
    return sid


def validate(client, machine, assignment):
    sid = session(client, machine, assignment, "worker")
    old = progress(client, machine, assignment, "ready", sessionId=sid, checkWorkflowId="missing")
    assert not old["confirmed"]
    check = session(client, machine, assignment, "self-check")
    record = post(client, "/session/" + check + "/self-check",
                  {"provider": "local-chrome", "profileId": "fixture", "platform": "tiktok"})
    claim = post(client, "/publish-task/claim", {"sessionId": check, "waitSeconds": 0})
    assert claim["task"]["workflowId"] == record["workflowId"]
    post(client, "/publish-task/result", {"sessionId": check, "workflowId": record["workflowId"],
         "receipt": {"cloudConnected": True, "cliInvoked": True, "profileVisible": True, "platformLogin": "valid", "exitCode": 0}})
    return {"sessionId": sid, "checkWorkflowId": record["workflowId"]}


def test_one_at_a_time_requires_new_observed_worker_and_check_receipt(gateway):
    manifest = artifact(gateway)
    release = gateway.post("/internal/releases", headers=INTERNAL, json=manifest).json()
    a, b = str(uuid4()), str(uuid4())
    old = {"revision": "0" * 40, "sha256": "0" * 64}
    first = poll(gateway, a, **old)["assignment"]
    assert first["sha256"] == manifest["packages"][TARGET]
    assert poll(gateway, b, **old)["assignment"] is None
    for phase in ("draining", "staging", "switched"):
        assert progress(gateway, a, first, phase)["active"]
    evidence = validate(gateway, a, first)
    assert progress(gateway, a, first, "ready", **evidence)["confirmed"]
    assert progress(gateway, a, first, "ready", **evidence)["confirmed"]
    second = poll(gateway, b, **old)["assignment"]
    assert second["batchId"] != first["batchId"]
    fresh = poll(gateway, str(uuid4()))
    assert fresh["assignment"] is None and fresh["approved"]["sha256"] == first["sha256"]
    info = gateway.get("/internal/releases/" + release["releaseId"], headers=INTERNAL).json()
    assert info["batches"][0]["phase"] == "ready" and not info["onlineReady"]


def test_disconnect_replacement_late_observation_and_package_defect(gateway, monkeypatch):
    import time
    monkeypatch.setenv("GATEWAY_RELEASE_DISCONNECT_SECONDS", "1")
    manifest = artifact(gateway)
    release = gateway.post("/internal/releases", headers=INTERNAL, json=manifest).json()
    path = "/internal/releases/" + release["releaseId"]
    a, b = str(uuid4()), str(uuid4())
    old = {"revision": "0" * 40, "sha256": "0" * 64}
    first = poll(gateway, a, **old)["assignment"]
    assert poll(gateway, b, **old)["assignment"] is None
    assert gateway.get(path, headers=INTERNAL).json()["batches"][0]["validationDeadline"]
    time.sleep(1.05)
    second = poll(gateway, b, **old)["assignment"]
    assert second["batchId"] != first["batchId"]
    # A later ready report cannot grant B's validation; a confirmed late package
    # defect must still pause this revision while B is preparing to switch.
    assert progress(gateway, a, first, "ready") == {"active": False, "confirmed": False}
    info = gateway.get(path, headers=INTERNAL).json()
    assert info["batches"][1]["replacementFor"] == first["batchId"]
    assert info["batches"][0]["latePhase"] == "ready" and not info["onlineReady"]
    assert progress(gateway, b, second, "draining")["active"]
    progress(gateway, a, first, "defect", reason="paired CLI missing")
    info = gateway.get(path, headers=INTERNAL).json()
    assert info["pauseReason"] == "paired CLI missing"
    assert poll(gateway, b, **old)["assignment"] is None
    assert not progress(gateway, b, second, "staging")["active"]
    repair = gateway.post("/internal/releases", headers=INTERNAL, json=artifact(gateway, "2" * 40)).json()
    poll(gateway, a, **old)
    assert not gateway.get("/internal/releases/" + repair["releaseId"], headers=INTERNAL).json()["pauseReason"]


def test_first_install_online_completion_and_returning_offline_node(gateway, monkeypatch):
    import time
    monkeypatch.setenv("GATEWAY_RELEASE_ONLINE_SECONDS", "1")
    release = gateway.post("/internal/releases", headers=INTERNAL, json=artifact(gateway)).json()
    path = "/internal/releases/" + release["releaseId"]
    offline, a = str(uuid4()), str(uuid4())
    # The first bootstrap can acquire the canary before there is any approved package.
    discovery = poll(gateway, a)
    first = discovery["assignment"]
    assert discovery["approved"] is None
    old = {"revision": "0" * 40, "sha256": "0" * 64}
    assert poll(gateway, offline, **old)["assignment"] is None
    for phase in ("draining", "staging", "switched"):
        progress(gateway, a, first, phase)
    time.sleep(1.05)
    evidence = validate(gateway, a, first)
    assert progress(gateway, a, first, "ready", **evidence)["confirmed"]
    status = gateway.get(path, headers=INTERNAL).json()
    assert status["onlineReady"]
    assert next(x for x in status["nodes"] if x["machineId"] == offline)["online"] is False
    returning = poll(gateway, offline, **old)
    assert returning["approved"]["revision"] == returning["assignment"]["revision"] == first["revision"]
    assert not gateway.get(path, headers=INTERNAL).json()["onlineReady"]


def test_pending_drain_withdraws_preparation_as_well_as_publication(gateway):
    from datetime import datetime, timedelta, timezone
    from test_publish_api import video

    node, sid = str(uuid4()), str(uuid4())
    old = {"revision": "0" * 40, "sha256": "0" * 64}
    report = {"sessionId": sid, "mode": "worker", "release": "0.1.0", "cliRelease": "0.1.0", "preparedStarts": True, "contractVersion": 1,
              "capacity": 1, "freeSlots": 1, "capabilities": [{"platform": "tiktok", "action": "upload-video"}],
              "providers": [{"provider": "local-chrome", "available": True,
                             "profiles": [{"name": "fixture", "profileId": "operator-approved"}]}],
              "installation": {"machineId": node, "target": TARGET, **old}}
    post(gateway, "/session", report)
    gateway.post("/internal/releases", headers=INTERNAL, json=artifact(gateway)).raise_for_status()
    assignment = poll(gateway, node, sessionId=sid, **old)["assignment"]
    assert progress(gateway, node, assignment, "draining")["active"]
    offer = {"task": video("future-cache"), "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
    gateway.post("/internal/preparations", json=offer, headers=INTERNAL).raise_for_status()
    assert post(gateway, "/publish-task/claim", {"sessionId": sid, "waitSeconds": 0, "acceptPreparation": True})["task"] is None


def test_confirmed_defect_fences_restarted_workers_by_package_digest(gateway):
    from test_publish_api import video

    original = artifact(gateway)
    gateway.post("/internal/releases", headers=INTERNAL, json=original).raise_for_status()
    node = str(uuid4())
    old = {"revision": "0" * 40, "sha256": "0" * 64}
    batch = poll(gateway, node, **old)["assignment"]
    progress(gateway, node, batch, "defect", reason="Paired CLI cannot start")
    task = video("do-not-dispatch-to-defective-runtime")
    gateway.post("/internal/occurrences", headers=INTERNAL, json=task).raise_for_status()
    for revision in (original["revision"], "2" * 40):
        sid = str(uuid4())
        report = {"sessionId": sid, "mode": "worker", "release": "0.1.0", "cliRelease": "0.1.0", "preparedStarts": True,
                  "contractVersion": 1, "capacity": 1, "freeSlots": 1,
                  "capabilities": [{"platform": "tiktok", "action": "upload-video"}],
                  "providers": [{"provider": "local-chrome", "available": True,
                                 "profiles": [{"name": "fixture", "profileId": "operator-approved"}]}],
                  "installation": {"machineId": node, "target": TARGET, "revision": revision, "sha256": batch["sha256"]}}
        post(gateway, "/session", report)
        assert post(gateway, "/publish-task/claim", {"sessionId": sid, "waitSeconds": 0})["task"] is None
    retry = gateway.post("/internal/releases", headers=INTERNAL, json={**original, "revision": "2" * 40})
    assert retry.status_code == 409


def test_late_defect_pauses_a_newer_release_only_when_it_reuses_the_same_bytes(gateway):
    original = artifact(gateway)
    first = gateway.post("/internal/releases", headers=INTERNAL, json=original).json()
    node = str(uuid4())
    old = {"revision": "0" * 40, "sha256": "0" * 64}
    validation = poll(gateway, node, **old)["assignment"]
    second = gateway.post("/internal/releases", headers=INTERNAL, json={**original, "revision": "2" * 40}).json()
    next_batch = poll(gateway, node, **old)["assignment"]
    progress(gateway, node, validation, "defect", reason="Paired runtime cannot start")
    prior = gateway.get("/internal/releases/" + first["releaseId"], headers=INTERNAL).json()
    now = gateway.get("/internal/releases/" + second["releaseId"], headers=INTERNAL).json()
    assert prior["batches"][0]["latePhase"] == "defect" and prior["batches"][0]["phase"] == "superseded"
    assert now["pauseReason"] == "Paired runtime cannot start" and now["batches"][0]["phase"] == "paused"
    assert not progress(gateway, node, next_batch, "draining")["active"]
