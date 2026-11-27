"""Content-addressed desktop packages and serialized, durable rollout decisions."""
import hashlib
import os
from typing import Annotated, Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from psycopg.types.json import Jsonb
from pydantic import Field, model_validator

from .models import WireModel, Identifier, ReleaseSha as Sha, PackageDigest as Digest, DesktopTarget as Target

RELEASE_LOCK = 138904038
CHUNK = 512 * 1024


class NewRelease(WireModel):
    environment: Literal["dev"]
    revision: Sha
    version: Identifier
    contractVersion: Literal[1]
    packages: Annotated[dict[Target, Digest], Field(min_length=1)]


def current_lock(db):
    db.execute("SELECT pg_advisory_xact_lock(%s)", (RELEASE_LOCK,))


ACTIVE = ("assigned", "draining", "staging", "switched")


class Discovery(WireModel):
    machineId: UUID
    target: Target
    revision: Sha | None = None
    sha256: Digest | None = None
    sessionId: UUID | None = None

    @model_validator(mode="after")
    def pins_together(self):
        if bool(self.revision) != bool(self.sha256):
            raise ValueError("Send both installed package pins")
        return self


class Progress(WireModel):
    releaseId: UUID
    machineId: UUID
    batchId: UUID
    phase: Literal["draining", "staging", "switched", "ready", "defect"]
    reason: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    sessionId: UUID | None = None
    checkWorkflowId: Identifier | None = None


def disconnect_seconds():
    return max(1, int(os.environ.get("GATEWAY_RELEASE_DISCONNECT_SECONDS", 300)))


def online_seconds():
    return max(1, int(os.environ.get("GATEWAY_RELEASE_ONLINE_SECONDS", 90)))


def expire(db):
    db.execute("""UPDATE desktop_release_batch SET phase='expired'
        WHERE phase=ANY(%s) AND deadline<=clock_timestamp()""", (list(ACTIVE),))


def observe(db, machine_id, target, revision, digest, session_id=None):
    db.execute("""INSERT INTO desktop_installation (machine_id,target,revision,sha256,worker_session)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT(machine_id) DO UPDATE SET last_seen=clock_timestamp(),target=excluded.target,
        revision=excluded.revision,sha256=excluded.sha256,
        worker_session=coalesce(excluded.worker_session,desktop_installation.worker_session)""",
        (machine_id, target, revision, digest, session_id))
    db.execute("""UPDATE desktop_release_batch SET deadline=clock_timestamp()+make_interval(secs=>%s)
        WHERE machine_id=%s AND phase=ANY(%s) AND deadline>clock_timestamp()""",
        (disconnect_seconds(), machine_id, list(ACTIVE)))


def package(row, target):
    digest = row["packages"][target]
    return {"releaseId": row["release_id"], "revision": row["revision"], "target": target, "sha256": digest,
            "url": "/session/release/packages/" + digest}


def approved_release(db, target):
    # Approve each native package only after it passed on its own target.
    return db.execute("""SELECT r.* FROM desktop_release r JOIN desktop_release_batch b USING (release_id)
        WHERE b.target=%s AND b.phase='ready' AND r.pause_reason IS NULL
        ORDER BY r.created_at DESC LIMIT 1""", (target,)).fetchone()


def next_batch(db, release):
    # Reserve an online candidate even if a different desktop happened to poll first.
    # Prefer idle and untried nodes. Once it is the last node a busy machine still wins.
    candidate = db.execute("""SELECT m.*
        FROM desktop_installation m
        LEFT JOIN desktop_session s ON s.session_id=m.worker_session
        LEFT JOIN LATERAL (SELECT b.batch_id,b.phase FROM desktop_release_batch b
            WHERE b.release_id=%s AND b.machine_id=m.machine_id ORDER BY b.created_at DESC LIMIT 1) last_try ON true
        WHERE m.last_seen>clock_timestamp()-make_interval(secs=>%s) AND %s::jsonb ? m.target
        AND NOT (coalesce(last_try.phase='ready',false) AND m.revision=%s AND m.sha256=%s::jsonb->>m.target)
        AND (m.revision IS NOT NULL OR NOT EXISTS (SELECT 1 FROM desktop_release_batch b
            JOIN desktop_release r USING (release_id) WHERE b.target=m.target AND b.phase='ready' AND r.pause_reason IS NULL))
        ORDER BY last_try.batch_id IS NOT NULL,
            coalesce((s.report->>'freeSlots')::int < (s.report->>'capacity')::int,false),
            m.last_seen DESC, m.machine_id LIMIT 1""", (release["release_id"], online_seconds(),
            Jsonb(release["packages"]), release["revision"], Jsonb(release["packages"]))).fetchone()
    if not candidate:
        return None
    return assign(db, release, candidate)


def assign(db, release, candidate):
    return db.execute("""INSERT INTO desktop_release_batch
        (batch_id,release_id,machine_id,target,prior_session,phase,deadline,replacement_for)
        VALUES (%s,%s,%s,%s,%s,'assigned',clock_timestamp()+make_interval(secs=>%s),
            (SELECT CASE WHEN phase='expired' THEN batch_id END FROM desktop_release_batch WHERE release_id=%s ORDER BY created_at DESC LIMIT 1)
        ) RETURNING *""", (uuid4(), release["release_id"], candidate["machine_id"], candidate["target"],
            candidate["worker_session"], disconnect_seconds(), release["release_id"])).fetchone()


def evidence(db, batch, release, body):
    expected = {"machineId": str(batch["machine_id"]), "target": batch["target"], "batchId": str(batch["batch_id"]),
                "revision": release["revision"], "sha256": release["packages"][batch["target"]]}
    # Bind both observations to this batch. Include the immutable session birth and
    # occurrence creation time, so an earlier session/receipt cannot certify a switch.
    return db.execute("""SELECT o.workflow_id FROM desktop_session worker
        JOIN occurrence o ON o.workflow_id=%s
        JOIN desktop_session probe ON probe.session_id=o.target_session AND probe.session_id=o.session_id
        WHERE worker.session_id=%s AND worker.session_id IS DISTINCT FROM %s AND worker.session_id<>probe.session_id
        AND worker.first_seen_at>=%s AND probe.first_seen_at>=%s AND o.created_at>=%s
        AND worker.last_contact_at>clock_timestamp()-make_interval(secs=>%s)
        AND worker.report->>'mode'='worker' AND probe.report->>'mode'='self-check'
        AND worker.report->'installation'=%s AND probe.report->'installation'=%s
        AND worker.report->>'release'=%s AND worker.report->>'cliRelease'=%s
        AND probe.report->>'release'=%s AND probe.report->>'cliRelease'=%s
        AND (worker.report->>'contractVersion')::int=%s AND (probe.report->>'contractVersion')::int=%s
        AND EXISTS (SELECT 1 FROM desktop_installation m WHERE m.machine_id=%s AND m.worker_session=worker.session_id)
        AND worker.report @> '{"preparedStarts":true}'
        AND worker.report->'capabilities' @> jsonb_build_array(
            jsonb_build_object('platform',o.task->'platform','action','check'),
            jsonb_build_object('platform',o.task->'platform','action','upload-video'),
            jsonb_build_object('platform',o.task->'platform','action','upload-note'))
        AND worker.report->'providers' @> jsonb_build_array(jsonb_build_object(
            'provider',o.task->'provider','available',true,'profiles',jsonb_build_array(
            jsonb_build_object('profileId',o.task->'profileId'))))
        AND o.task->>'action'='check' AND o.state='succeeded'
        AND o.receipt @> '{"platformLogin":"valid","cliInvoked":true,"profileVisible":true,"cloudConnected":true,"exitCode":0}'
        """, (body.checkWorkflowId, body.sessionId, batch["prior_session"], batch["created_at"],
        batch["switched_at"], batch["switched_at"], online_seconds(), Jsonb(expected), Jsonb(expected),
        release["version"], release["version"], release["version"], release["version"],
        release["contract_version"], release["contract_version"], batch["machine_id"])).fetchone()


def blocked_claim(db, session):
    installation = session.get("installation")
    if not installation or session["mode"] == "self-check":
        return False
    # An old in-flight long poll must not race the drain. The caller already holds
    # the session row. New work becomes eligible after validation; old claims keep
    # using their original start, lease and result paths.
    if db.execute("""SELECT 1 FROM desktop_package WHERE sha256=%s AND defect_reason IS NOT NULL""",
                  (installation["sha256"],)).fetchone():
        return True
    if installation.get("batchId"):
        ready = db.execute("""SELECT 1 FROM desktop_release_batch b JOIN desktop_release r USING (release_id)
            WHERE b.batch_id=%s AND b.machine_id=%s AND b.phase='ready'
            AND r.revision=%s AND r.packages->>%s=%s""",
            (installation["batchId"], installation["machineId"], installation["revision"],
             installation["target"], installation["sha256"])).fetchone()
        if not ready:
            return True
    return db.execute("""SELECT 1 FROM desktop_release_batch b
        WHERE b.machine_id=%s AND b.phase=ANY(%s) LIMIT 1""",
        (installation["machineId"], list(ACTIVE))).fetchone() is not None


def details(db, release_id):
    release = db.execute("""SELECT release_id AS "releaseId", environment, revision, version,
            packages, pause_reason AS "pauseReason", superseded FROM desktop_release
            WHERE release_id=%s""", (release_id,)).fetchone()
    if not release:
        raise HTTPException(404, "Unknown desktop release")
    release["batches"] = db.execute("""SELECT batch_id AS "batchId",machine_id AS "machineId",target,
        phase,deadline AS "validationDeadline",replacement_for AS "replacementFor",late_phase AS "latePhase",
        late_at AS "lateAt",late_reason AS "lateReason",check_workflow AS "checkWorkflowId"
        FROM desktop_release_batch WHERE release_id=%s ORDER BY created_at""", (release_id,)).fetchall()
    release["nodes"] = db.execute("""SELECT m.machine_id AS "machineId",m.target,m.revision,m.sha256,
        m.last_seen AS "lastContactAt", m.last_seen>clock_timestamp()-make_interval(secs=>%s) AS online,
        s.report->'capabilities' AS capabilities,s.report->>'release' AS version,
        coalesce(m.revision=%s AND m.sha256=%s::jsonb->>m.target AND b.phase='ready',false) AS ready
        FROM desktop_installation m LEFT JOIN desktop_session s ON s.session_id=m.worker_session
        LEFT JOIN LATERAL (SELECT phase FROM desktop_release_batch WHERE release_id=%s AND machine_id=m.machine_id
            ORDER BY created_at DESC LIMIT 1) b ON true ORDER BY m.machine_id""",
        (online_seconds(),release["revision"],Jsonb(release["packages"]),release_id)).fetchall()
    online = [node for node in release["nodes"] if node["online"]]
    release["onlineReady"] = bool(online and not release["pauseReason"] and all(n["ready"] for n in online))
    return release


def register(app, store, desktop, internal):
    @app.put("/internal/releases/packages/{digest}", dependencies=internal)
    async def upload(digest: Digest, request: Request):
        # A broken stream or digest mismatch rolls back the whole package. A retry
        # can send the same bytes concurrently without exposing a partial download.
        async with await psycopg.AsyncConnection.connect(store.dsn) as db:
            inserted = await (await db.execute("""INSERT INTO desktop_package (sha256) VALUES (%s)
                ON CONFLICT DO NOTHING RETURNING sha256""", (digest,))).fetchone()
            checksum = hashlib.sha256()
            size = seq = 0
            pending = bytearray()
            async for data in request.stream():
                checksum.update(data)
                size += len(data)
                if inserted:
                    remaining = memoryview(data)
                    while remaining:
                        count = min(CHUNK - len(pending), len(remaining))
                        pending.extend(remaining[:count])
                        remaining = remaining[count:]
                        if len(pending) == CHUNK:
                            await db.execute("INSERT INTO desktop_package_chunk VALUES (%s,%s,%s)",
                                             (digest, seq, bytes(pending)))
                            pending.clear()
                            seq += 1
            if not size or checksum.hexdigest() != digest:
                raise HTTPException(422, "Package SHA-256 mismatch")
            if inserted:
                if pending:
                    await db.execute("INSERT INTO desktop_package_chunk VALUES (%s,%s,%s)", (digest, seq, bytes(pending)))
                await db.execute("UPDATE desktop_package SET size_bytes=%s WHERE sha256=%s", (size, digest))
        return {"sha256": digest, "bytes": size}

    @app.get("/session/release/packages/{digest}", dependencies=desktop)
    def download(digest: Digest):
        with store.connect() as db:
            row = db.execute("""SELECT size_bytes FROM desktop_package WHERE sha256=%s
                AND EXISTS (SELECT 1 FROM desktop_release r, jsonb_each_text(r.packages) p WHERE p.value=%s)""",
                (digest, digest)).fetchone()
            if not row:
                raise HTTPException(404, "Unknown release package")

        def chunks():
            with store.connect() as db, db.cursor(name="package_download") as cursor:
                cursor.itersize = 2
                cursor.execute("SELECT data FROM desktop_package_chunk WHERE sha256=%s ORDER BY seq", (digest,))
                for chunk in cursor:
                    yield chunk["data"]

        return StreamingResponse(chunks(), media_type="application/zip", headers={"Content-Length": str(row["size_bytes"])})

    @app.post("/internal/releases", dependencies=internal)
    def create(release: NewRelease):
        with store.connect() as db:
            current_lock(db)
            installed = db.execute("""SELECT release_id, version, packages, contract_version FROM desktop_release
                WHERE environment=%s AND revision=%s""", (release.environment, release.revision)).fetchone()
            if installed:
                if (installed["packages"] != release.packages or installed["version"] != release.version
                        or installed["contract_version"] != release.contractVersion):
                    raise HTTPException(409, "Revision already pinned to another manifest")
                return details(db, installed["release_id"])
            present = db.execute("SELECT sha256,defect_reason FROM desktop_package WHERE sha256=ANY(%s)",
                                 (list(release.packages.values()),)).fetchall()
            if set(release.packages.values()) != {row["sha256"] for row in present}:
                raise HTTPException(422, "Upload every pinned package before registering the release")
            if any(row["defect_reason"] is not None for row in present):
                raise HTTPException(409, "Release includes a package with a confirmed defect")
            db.execute("""UPDATE desktop_release_batch SET phase='superseded' WHERE phase=ANY(%s)""", (list(ACTIVE),))
            db.execute("UPDATE desktop_release SET superseded=true WHERE NOT superseded")
            release_id = uuid4()
            db.execute("""INSERT INTO desktop_release
                (release_id, environment, revision, version, contract_version, packages)
                VALUES (%s,%s,%s,%s,%s,%s)""", (release_id, release.environment, release.revision,
                release.version, release.contractVersion, Jsonb(release.packages)))
            expire(db)
            return details(db, release_id)

    @app.get("/internal/releases/{release_id}", dependencies=internal)
    def status(release_id: UUID):
        with store.connect() as db:
            current_lock(db)
            expire(db)
            return details(db, release_id)

    @app.post("/session/release/discover", dependencies=desktop)
    def discover(body: Discovery):
        with store.connect() as db:
            current_lock(db)
            expire(db)
            # A bootstrap has no worker session yet. Accept only a live session
            # reporting the same installation as the source of occupancy information.
            session_id = None
            if body.sessionId:
                session = db.execute("""SELECT session_id FROM desktop_session WHERE session_id=%s
                    AND report->>'mode'='worker' AND report->'installation' @> %s
                    AND last_contact_at>clock_timestamp()-make_interval(secs=>%s)""",
                    (body.sessionId, Jsonb({"machineId": str(body.machineId), "target": body.target,
                     "revision": body.revision, "sha256": body.sha256}), online_seconds())).fetchone()
                session_id = session["session_id"] if session else None
            observe(db, body.machineId, body.target, body.revision, body.sha256, session_id)
            approved = approved_release(db, body.target)
            response = {"assignment": None, "approved": package(approved, body.target) if approved else None}
            # Catch-up on a previously approved release shares the rollout slot across all targets.
            batch = db.execute("SELECT * FROM desktop_release_batch WHERE phase=ANY(%s)",
                               (list(ACTIVE),)).fetchone()
            if batch:
                release = db.execute("SELECT * FROM desktop_release WHERE release_id=%s",
                                     (batch["release_id"],)).fetchone()
            else:
                release = db.execute("SELECT * FROM desktop_release WHERE NOT superseded AND pause_reason IS NULL").fetchone()
                if release:
                    batch = next_batch(db, release)
                if not batch and approved and body.revision and body.sha256 != approved["packages"][body.target]:
                    # Legacy installations have no registration. For registered packages, only move forward.
                    newer = db.execute("""SELECT 1 FROM desktop_release WHERE revision=%s
                        AND packages->>%s=%s AND created_at>=%s""",
                        (body.revision, body.target, body.sha256, approved["created_at"])).fetchone()
                    if not newer:
                        release = approved
                        machine = db.execute("SELECT * FROM desktop_installation WHERE machine_id=%s",
                                             (body.machineId,)).fetchone()
                        batch = assign(db, release, machine)
            if batch and batch["machine_id"] == body.machineId:
                response["assignment"] = {**package(release, batch["target"]), "batchId": batch["batch_id"]}
            return response

    @app.post("/session/release/progress", dependencies=desktop)
    def progress(body: Progress):
        with store.connect() as db:
            current_lock(db)
            expire(db)
            batch = db.execute("""SELECT * FROM desktop_release_batch
                WHERE release_id=%s AND batch_id=%s AND machine_id=%s""",
                (body.releaseId, body.batchId, body.machineId)).fetchone()
            if not batch:
                raise HTTPException(404, "Unknown release batch for this installation")
            release = db.execute("SELECT * FROM desktop_release WHERE release_id=%s", (body.releaseId,)).fetchone()
            if body.phase == "defect":
                if not body.reason or not body.reason.strip():
                    raise HTTPException(422, "A package defect requires a reason")
                digest = release["packages"][batch["target"]]
                db.execute("""UPDATE desktop_package SET defect_reason=coalesce(defect_reason,%s) WHERE sha256=%s""",
                           (body.reason, digest))
                # A late defect belongs to its original batch. The same bytes can
                # also have been pinned elsewhere while its report was in flight.
                db.execute("""UPDATE desktop_release r SET pause_reason=coalesce(pause_reason,%s)
                    WHERE EXISTS (SELECT 1 FROM jsonb_each_text(r.packages) p WHERE p.value=%s)""",
                    (body.reason, digest))
                db.execute("""UPDATE desktop_release_batch b SET phase='paused' FROM desktop_release r
                    WHERE b.release_id=r.release_id AND r.pause_reason IS NOT NULL
                    AND b.batch_id<>%s AND b.phase=ANY(%s)""", (body.batchId, list(ACTIVE)))
            if batch["phase"] not in ACTIVE:
                if batch["phase"] == "ready" and body.phase == "ready":
                    return {"active": False, "confirmed": True}
                db.execute("""INSERT INTO desktop_release_late_report (batch_id,evidence) VALUES (%s,%s)
                    ON CONFLICT DO NOTHING""", (body.batchId, Jsonb(body.model_dump(mode="json",exclude_none=True))))
                db.execute("""UPDATE desktop_release_batch SET late_phase=%s,late_at=clock_timestamp(),late_reason=%s
                    WHERE batch_id=%s""", (body.phase, body.reason, body.batchId))
                return {"active": False, "confirmed": False}
            if body.phase == "ready":
                if batch["phase"] != "switched" or not evidence(db, batch, release, body):
                    return {"active": True, "confirmed": False}
                db.execute("""UPDATE desktop_release_batch SET confirmed_session=%s, check_workflow=%s WHERE batch_id=%s""",
                    (body.sessionId, body.checkWorkflowId, body.batchId))
            elif body.phase in ACTIVE and ACTIVE.index(body.phase) > ACTIVE.index(batch["phase"]) + 1:
                raise HTTPException(409, "Desktop must drain, stage and switch in order")
            elif body.phase in ACTIVE and ACTIVE.index(body.phase) < ACTIVE.index(batch["phase"]):
                return {"active": True, "confirmed": False}
            db.execute("""UPDATE desktop_release_batch SET phase=%s,deadline=clock_timestamp()+make_interval(secs=>%s),
                switched_at=CASE WHEN %s='switched' THEN coalesce(switched_at,clock_timestamp()) ELSE switched_at END
                WHERE batch_id=%s""", (body.phase, disconnect_seconds(), body.phase, body.batchId))
            return {"active": body.phase in ACTIVE, "confirmed": body.phase == "ready"}
