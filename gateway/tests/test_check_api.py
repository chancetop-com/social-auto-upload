"""Public API checks against a disposable PostgreSQL schema in the fixture database."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient
from sau_gateway.app import create_app


INTERNAL = {"Authorization": "Bearer fixture-internal"}
DESKTOP = {"Authorization": "Bearer fixture-desktop"}


def test_operator_sees_the_receipt_for_the_original_claim_after_restart(gateway):
    session = str(uuid4())
    task = {"workflowId": str(uuid4()), "contractVersion": 1, "requiredCapability": "tiktok.check",
            "release": "0.1.0", "provider": "bitbrowser", "profileId": "window", "platform": "tiktok", "action": "check"}
    path = "/internal/occurrences/" + task["workflowId"]
    assert gateway.post("/internal/occurrences", json=task, headers=DESKTOP).status_code == 401
    assert gateway.post("/internal/occurrences", json=task, headers=INTERNAL).json()["state"] == "pending"
    report = {"sessionId": session, "release": "0.1.0", "contractVersion": 1, "capacity": 1, "freeSlots": 1,
              "capabilities": [{"platform": "tiktok", "action": "check"}], "providers": [
                  {"provider": "bitbrowser", "available": True, "profiles": [{"profileId": "window", "name": "Shop"}]}]}
    assert gateway.post("/session", json=report, headers=INTERNAL).status_code == 401
    assert gateway.post("/session", json=report, headers=DESKTOP).json()["lastContactAt"]
    claim = {"sessionId": session, "waitSeconds": 0}
    assert gateway.post("/publish-task/claim", json=claim, headers=DESKTOP).json()["task"]["task"] == task
    assert gateway.post("/publish-task/claim", json=claim, headers=DESKTOP).json() == {"task": None}
    receipt = {"cloudConnected": True, "cliInvoked": True, "profileVisible": True, "platformLogin": "valid", "exitCode": 0}
    result = {"sessionId": session, "workflowId": task["workflowId"], "receipt": receipt}
    assert gateway.post("/publish-task/result", json={**result, "sessionId": str(uuid4())}, headers=DESKTOP).status_code == 409
    assert gateway.post("/publish-task/result", json=result, headers=DESKTOP).json()["state"] == "succeeded"
    altered = {**receipt, "platformLogin": "unknown"}
    assert gateway.post("/publish-task/result", json={**result, "receipt": altered}, headers=DESKTOP).json()["receipt"] == receipt
    assert gateway.post("/internal/occurrences", json=task, headers=INTERNAL).json()["receipt"] == receipt
    with TestClient(create_app()) as restarted:
        assert restarted.get(path, headers=INTERNAL).json()["receipt"] == receipt


def test_one_reported_free_slot_bounds_concurrent_claims(gateway):
    session = str(uuid4())
    report = {"sessionId": session, "release": "0.1.0", "contractVersion": 1, "capacity": 3, "freeSlots": 1,
              "capabilities": [{"platform": "tiktok", "action": "check"}], "providers": [
                  {"provider": "adspower", "available": True, "profiles": [{"profileId": "a", "name": "Prep"}]}]}
    gateway.post("/session", json=report, headers=DESKTOP).raise_for_status()
    base = {"contractVersion": 1, "release": "0.1.0", "requiredCapability": "tiktok.check",
            "platform": "tiktok", "action": "check", "provider": "adspower", "profileId": "a"}
    for workflow, change in [("wrong-release", {"release": "other"}), ("wrong-profile", {"profileId": "b"}),
                             ("wrong-platform", {"requiredCapability": "instagram.check", "platform": "instagram"}),
                             ("first", {}), ("second", {})]:
        gateway.post("/internal/occurrences", json={**base, "workflowId": workflow, **change}, headers=INTERNAL).raise_for_status()
    command = {**base, "workflowId": "unknown-command", "action": "shell", "argv": ["test"]}
    assert gateway.post("/internal/occurrences", json=command, headers=INTERNAL).status_code == 422
    claim = {"sessionId": session, "waitSeconds": 0}
    with ThreadPoolExecutor(max_workers=2) as pool:
        requests = [pool.submit(gateway.post, "/publish-task/claim", json=claim, headers=DESKTOP) for _ in range(2)]
        records = [request.result().json()["task"] for request in requests]
    assert [record["workflowId"] for record in records if record] == ["first"]
    assert records.count(None) == 1
