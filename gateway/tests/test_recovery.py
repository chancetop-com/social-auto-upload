"""Long-poll and claim recovery through the HTTP API with disposable PostgreSQL/Redis."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import os
import threading
from uuid import uuid4

import pytest
import redis
import httpx
import time

import psycopg
from fastapi.testclient import TestClient
from sau_gateway.app import create_app
from test_publish_api import DESKTOP, INTERNAL, claim, register, video


def db_now(dsn):
    with psycopg.connect(dsn) as conn:
        return conn.execute("SELECT clock_timestamp()").fetchone()[0]


def enqueue(client, workflow, cutoff):
    task = {**video(workflow), "earliestPublishAt": None, "claimDeadlineAt": cutoff.isoformat()}
    reply = client.post("/internal/occurrences", headers=INTERNAL, json=task)
    reply.raise_for_status()
    return reply.json()


def lookup(client, workflow):
    return client.get("/internal/occurrences/" + workflow, headers=INTERNAL).json()


def test_original_cutoff_wins_when_a_claim_is_blocked_until_expiry(gateway_env, gateway):
    session = register(gateway)
    cutoff = db_now(gateway_env) + timedelta(seconds=1)
    pending = enqueue(gateway, "late-worker", cutoff)
    assert pending["state"] == "pending"
    with ThreadPoolExecutor(2) as pool:
        with psycopg.connect(gateway_env) as db:
            db.execute("SELECT session_id FROM desktop_session WHERE session_id=%s FOR UPDATE", (session,))
            waiting = pool.submit(claim, gateway, session)
            # Let database time, independently of either application clock, pass the cutoff.
            db.execute("SELECT pg_sleep(greatest(0, extract(epoch from %s::timestamptz-clock_timestamp())))", (cutoff,))
            expiry = pool.submit(lookup, gateway, "late-worker")
        assert waiting.result() is None
        assert expiry.result()["state"] == "timed_out"
    retry = enqueue(gateway, "late-worker", cutoff + timedelta(hours=1))
    assert retry["claimDeadlineAt"] == pending["claimDeadlineAt"]
    assert retry["sessionId"] is None and retry["state"] == "timed_out"


def test_redis_wakeup_during_first_check_survives_duplicate_notifications(gateway_env, monkeypatch):
    from sau_gateway.database import Store

    url = os.environ.get("GATEWAY_TEST_REDIS_URL")
    if not url:
        pytest.skip("set GATEWAY_TEST_REDIS_URL for Redis recovery")
    channel = "test:social-media-web-api:" + uuid4().hex
    monkeypatch.setenv("GATEWAY_REDIS_URL", url)
    monkeypatch.setenv("GATEWAY_REDIS_CHANNEL", channel)
    monkeypatch.setenv("GATEWAY_RECHECK_SECONDS", "15")
    tag = uuid4().hex
    monkeypatch.setenv("PGAPPNAME", tag)
    with redis.Redis.from_url(url) as observer, TestClient(create_app()) as waiting_gateway:
        until = time.monotonic() + 2
        while observer.pubsub_numsub(channel)[0][1] == 0 and time.monotonic() < until:
            time.sleep(.02)
        assert observer.pubsub_numsub(channel)[0][1] == 1
        # Another Gateway process commits the work. Only Redis connects these waiters.
        with TestClient(create_app()) as publisher:
            session = register(waiting_gateway)
            original = Store.claim
            first = threading.Event()
            resume = threading.Event()

            def delayed_check(store, session_id):
                record = original(store, session_id)
                if not first.is_set():
                    first.set()
                    assert resume.wait(4)
                return record

            monkeypatch.setattr(Store, "claim", delayed_check)
            with ThreadPoolExecutor() as pool, observer.pubsub() as messages:
                messages.subscribe(channel)
                assert messages.get_message(timeout=2)["type"] == "subscribe"
                response = pool.submit(waiting_gateway.post, "/publish-task/claim", headers=DESKTOP,
                                       json={"sessionId": session, "waitSeconds": 10})
                try:
                    assert first.wait(2)
                    enqueue(publisher, "in-flight-check", db_now(gateway_env) + timedelta(minutes=1))
                    assert messages.get_message(timeout=2)["type"] == "message"
                    assert lookup(publisher, "in-flight-check")["state"] == "pending"
                    observer.publish(channel, "duplicate")
                    # The paused request owns no connection after its first empty query.
                    with psycopg.connect(gateway_env, application_name="observer") as db:
                        assert db.execute("SELECT count(*) FROM pg_stat_activity WHERE application_name=%s",
                                          (tag,)).fetchone()[0] == 0
                finally:
                    resume.set()
                assert response.result(timeout=2).json()["task"]["workflowId"] == "in-flight-check"
                assert claim(waiting_gateway, session) is None


@pytest.mark.parametrize("resubscribe", [True, False], ids=["resubscription", "redis-unavailable"])
def test_silent_commit_discovered_on_resubscribe_or_bounded_recheck(gateway_env, monkeypatch, resubscribe):
    from sau_gateway.database import Store
    redis_url = os.environ.get("GATEWAY_TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("set GATEWAY_TEST_REDIS_URL for Redis recovery")
    tag = uuid4().hex
    first = threading.Event()
    original = Store.claim

    def checked(store, session_id):
        record = original(store, session_id)
        first.set()
        return record

    monkeypatch.setattr(Store, "claim", checked)
    monkeypatch.setenv("GATEWAY_REDIS_CHANNEL", "test:social-media-web-api:" + tag)
    monkeypatch.setenv("GATEWAY_REDIS_URL", redis_url + "?client_name=" + tag if resubscribe
                       else "redis://127.0.0.1:1/15")
    monkeypatch.setenv("GATEWAY_RECHECK_SECONDS", "25" if resubscribe else "1")
    with TestClient(create_app()) as subscriber, redis.Redis.from_url(redis_url) as observer:
        monkeypatch.delenv("GATEWAY_REDIS_URL")
        with TestClient(create_app()) as publisher, ThreadPoolExecutor() as pool:
            # Publisher's local wakeups do not reach this subscriber.
            session = register(subscriber)
            if resubscribe:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    connections = [c["id"] for c in observer.client_list("pubsub") if c["name"] == tag]
                    if connections:
                        break
                    time.sleep(.02)
                assert len(connections) == 1
            response = pool.submit(subscriber.post, "/publish-task/claim", headers=DESKTOP,
                                   json={"sessionId": session, "waitSeconds": 10})
            assert first.wait(2)
            enqueue(publisher, "silent", db_now(gateway_env) + timedelta(minutes=2))
            if resubscribe:
                assert observer.client_kill_filter(_id=connections[0]) == 1
            assert response.result(timeout=5).json()["task"]["workflowId"] == "silent"


@pytest.mark.asyncio
async def test_worker_losing_claim_reply_cannot_redispatch_after_reconnect_or_gateway_restart(gateway_env, monkeypatch):
    from sau_worker.worker import Settings, Worker
    from test_desktop_publish import live_gateway

    monkeypatch.setenv("GATEWAY_RESULT_TIMEOUT_SECONDS", "120")
    with live_gateway() as url, httpx.Client(base_url=url, trust_env=False) as api:
        task = {**video("lost-claim"), "earliestPublishAt": None,
                "claimDeadlineAt": (db_now(gateway_env) + timedelta(seconds=2)).isoformat()}
        api.post("/internal/occurrences", json=task, headers=INTERNAL).raise_for_status()
        config = Settings.from_env({"SAU_GATEWAY_URL": url, "SAU_DESKTOP_TOKEN": "fixture-desktop",
                                    "SAU_DEV_CHROME_ALIASES": "operator-approved"})

        async with httpx.AsyncClient(trust_env=False) as wire:
            async def drop_after_commit(request):
                response = await wire.send(request)
                if request.url.path == "/publish-task/claim":
                    assert response.json()["task"]["state"] == "claimed"
                    raise httpx.ReadError("connection lost before client observed the claim")
                return response

            async with httpx.AsyncClient(transport=httpx.MockTransport(drop_after_commit)) as faulty:
                worker = Worker(config, faulty)
                worker.cli_release = "0.1.0"
                await worker.report()
                before = db_now(gateway_env)
                with pytest.raises(httpx.ReadError):
                    await worker.claim(0)
                original = lookup(api, "lost-claim")
                assert original["sessionId"] == worker.session_id and original["receipt"] is None
                deadline = datetime.fromisoformat(original["resultDeadlineAt"].replace("Z", "+00:00"))
                assert before + timedelta(seconds=120) <= deadline <= db_now(gateway_env) + timedelta(seconds=120)
    monkeypatch.setenv("GATEWAY_RESULT_TIMEOUT_SECONDS", "1800")
    with live_gateway() as restarted, httpx.Client(base_url=restarted, trust_env=False) as api:
        await wait_until_cutoff(gateway_env, task["claimDeadlineAt"])
        config.gateway = restarted
        async with httpx.AsyncClient(trust_env=False) as reconnected:
            worker.client = reconnected
            await worker.report()
            assert await worker.claim(0) is None
            peer = Worker(config, reconnected)
            peer.cli_release = "0.1.0"
            await peer.report()
            assert await peer.claim(0) is None
        replay = api.post("/internal/occurrences", json=task, headers=INTERNAL).json()
        assert replay == original


async def wait_until_cutoff(dsn, cutoff):
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute("SELECT pg_sleep(greatest(0, extract(epoch from %s::timestamptz-clock_timestamp())))", (cutoff,))
