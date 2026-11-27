from importlib.resources import files
import os

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import leases, releases
from .models import CheckReceipt, PublishReceipt, PublishTask


class Missing(Exception):
    pass


class Conflict(Exception):
    pass


def migrate(dsn):
    with psycopg.connect(dsn) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(893672101)")
        conn.execute("CREATE TABLE IF NOT EXISTS gateway_migration (name text PRIMARY KEY)")
        applied = {row[0] for row in conn.execute("SELECT name FROM gateway_migration")}
        for script in sorted(files("sau_gateway").joinpath("migrations").iterdir(), key=lambda p: p.name):
            if script.name.endswith(".sql") and script.name not in applied:
                conn.execute(script.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO gateway_migration VALUES (%s)", (script.name,))


RECORD = ('workflow_id AS "workflowId", state, session_id AS "sessionId", task, receipt, '
          'claim_deadline AS "claimDeadlineAt", result_deadline AS "resultDeadlineAt", '
          'claimed_at AS "claimedAt", lease_grant_id AS "leaseGrantId", lease_expires_at AS "leaseExpiresAt", '
          'overdue_at AS "overdueAt", publish_started_at AS "publishStartedAt", receipt_history AS "receiptHistory"')


class Store:
    def __init__(self, dsn):
        self.dsn = dsn
        self.lease_policy = leases.LeasePolicy.from_env()
        self.claim_seconds = int(os.environ.get("GATEWAY_CLAIM_TIMEOUT_SECONDS", 1800))
        self.result_seconds = int(os.environ.get("GATEWAY_RESULT_TIMEOUT_SECONDS", 1800))
        if min(self.claim_seconds, self.result_seconds) <= 0:
            raise ValueError("Occurrence timeouts must be positive")

    def connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=5)

    def ready(self):
        with self.connect() as db:
            db.execute("SELECT 1 FROM desktop_session LIMIT 0")

    def report(self, session):
        with self.connect() as db:
            if session.installation:
                releases.current_lock(db)
            payload = session.model_dump(mode="json")
            if not session.installation:
                payload.pop("installation")
            result = db.execute("""
                INSERT INTO desktop_session(session_id, report) VALUES (%s,%s)
                ON CONFLICT (session_id) DO UPDATE SET report=excluded.report, last_contact_at=clock_timestamp()
                WHERE desktop_session.report->>'mode'=excluded.report->>'mode'
                AND (desktop_session.report->'installation') IS NOT DISTINCT FROM (excluded.report->'installation')
                RETURNING session_id AS "sessionId", last_contact_at AS "lastContactAt"
            """, (session.sessionId, Jsonb(payload))).fetchone()
            if not result:
                raise Conflict()
            if (install := session.installation) and session.mode == "worker":
                releases.observe(db, install.machineId, install.target, install.revision, install.sha256, session.sessionId)
            return result

    def session(self, session_id):
        with self.connect() as db:
            row = db.execute('SELECT report, last_contact_at AS "lastContactAt" FROM desktop_session WHERE session_id=%s',
                             (session_id,)).fetchone()
            if row is None:
                raise Missing()
            return {**row["report"], "lastContactAt": row["lastContactAt"]}

    def enqueue(self, task, target_session=None):
        with self.connect() as db:
            payload = task.model_dump(mode="json", exclude_unset=True)
            db.execute("""
                INSERT INTO occurrence(workflow_id, task, target_session, claim_deadline)
                VALUES (%s,%s,%s,CASE WHEN %s THEN coalesce(%s::timestamptz,
                    coalesce(%s::timestamptz, clock_timestamp()) + %s * interval '1 second') END)
                ON CONFLICT (workflow_id) DO NOTHING
            """, (task.workflowId, Jsonb(payload), target_session, isinstance(task, PublishTask),
                  payload.get("claimDeadlineAt"), payload.get("earliestPublishAt"), self.claim_seconds))
            return self._get(db, task.workflowId)

    def _get(self, db, workflow_id):
        db.execute("""
            UPDATE occurrence SET state='timed_out', completed_at=clock_timestamp()
            WHERE workflow_id=%s AND state='pending' AND claim_deadline <= clock_timestamp()
        """, (workflow_id,))
        db.execute("""
            UPDATE occurrence SET state='unknown', overdue_at=clock_timestamp()
            WHERE workflow_id=%s AND state IN ('claimed','started') AND result_deadline <= clock_timestamp()
              AND task->>'action' <> 'check'
        """, (workflow_id,))
        row = db.execute(f"SELECT {RECORD} FROM occurrence WHERE workflow_id=%s", (workflow_id,)).fetchone()
        if row is None:
            raise Missing()
        return row

    def get(self, workflow_id):
        with self.connect() as db:
            return self._get(db, workflow_id)

    def revoke(self, ref):
        with self.connect() as db:
            row = db.execute("""SELECT state, publish_started_at, receipt FROM occurrence
                WHERE workflow_id=%s AND task->>'organizationId'=%s AND task->>'postId'=%s
                AND task->>'action' <> 'check' FOR UPDATE""",
                (ref.workflowId, ref.organizationId, ref.postId)).fetchone()
            if row is None:
                raise Missing()
            # Postiz serializes binding revocation against its own authorize-start commit.
            # A delayed revocation still supplies definite evidence for an unstarted overdue claim.
            if not row["publish_started_at"] and not row["receipt"] and row["state"] in (
                    "pending", "claimed", "timed_out", "unknown"):
                receipt = Jsonb({"outcome": "failed", "reason": "authorization_declined",
                                 "cliInvoked": False, "exitCode": None})
                db.execute("""UPDATE occurrence SET state='failed', receipt=%s,
                    receipt_history=receipt_history||jsonb_build_array(%s::jsonb), completed_at=clock_timestamp()
                    WHERE workflow_id=%s""", (receipt, receipt, ref.workflowId))
            return self._get(db, ref.workflowId)

    def claim(self, session_id):
        with self.connect() as db:
            row = db.execute("""
                UPDATE desktop_session SET last_contact_at=clock_timestamp() WHERE session_id=%s RETURNING report
            """, (session_id,)).fetchone()
            if row is None:
                raise Missing()
            report = row["report"]
            if not report["freeSlots"] or releases.blocked_claim(db, report):
                return None
            # The session row serializes concurrent polls even if a stale report advertises free slots.
            if leases.occupied_slots(db, session_id) >= report["capacity"]:
                return None
            visible = [{"provider": p["provider"], "profileId": profile["profileId"]}
                       for p in report["providers"] if p["available"] for profile in p["profiles"]]
            row = db.execute(f"""
                SELECT workflow_id, task FROM occurrence AS pending
                WHERE state='pending' AND (claim_deadline IS NULL OR claim_deadline > clock_timestamp())
                AND task->>'release'=%s AND (task->>'contractVersion')::integer=%s
                AND (task->>'action'='check' OR (%s AND task->>'release'=%s))
                AND ((target_session=%s) OR
                    (target_session IS NULL AND %s='worker' AND %s::jsonb @> jsonb_build_array(jsonb_build_object(
                         'provider',task->'provider','profileId',task->'profileId'))))
                AND (target_session=%s OR %s::jsonb @> jsonb_build_array(jsonb_build_object('platform',task->'platform','action',task->'action')))
                AND {leases.ELIGIBLE_PROFILE}
                ORDER BY created_at, workflow_id LIMIT 1 FOR UPDATE SKIP LOCKED
            """, (report["release"], report["contractVersion"], report.get("preparedStarts", False), report.get("cliRelease"), session_id, report["mode"], Jsonb(visible), session_id,
                  Jsonb(report["capabilities"]), session_id)).fetchone()
            if row is None:
                return None
            lease = leases.acquire(db, session_id, row["task"], self.lease_policy)
            if lease is None:
                return None
            claimed = db.execute(f"""
                WITH decision AS MATERIALIZED (SELECT clock_timestamp() AS at)
                UPDATE occurrence SET state='claimed', session_id=%s, claimed_at=decision.at,
                    lease_grant_id=%s, lease_expires_at=%s,
                    result_deadline=CASE WHEN task->>'action' <> 'check' THEN
                        greatest(decision.at, (task->>'earliestPublishAt')::timestamptz)
                        + %s * interval '1 second' END
                FROM decision
                WHERE workflow_id=%s AND state='pending' AND %s > decision.at
                  AND (claim_deadline IS NULL OR claim_deadline > decision.at)
                RETURNING {RECORD}
            """, (session_id, lease["grant_id"], lease["expires_at"], self.result_seconds,
                  row["workflow_id"], lease["expires_at"])).fetchone()
            if claimed is None:
                db.rollback()
                return None
            db.execute("""
                UPDATE desktop_session SET report=jsonb_set(report, '{freeSlots}', to_jsonb((report->>'freeSlots')::int - 1))
                WHERE session_id=%s
            """, (session_id,))
            return {**claimed, "renewAfterSeconds": self.lease_policy.renew_seconds}

    def _can_run(self, db, session_id, task, *, check_action=True):
        report = db.execute("SELECT report FROM desktop_session WHERE session_id=%s FOR UPDATE",
                            (session_id,)).fetchone()["report"]
        capability = {"platform": task["platform"], "action": task["action"]}
        return (report["mode"] == "worker" and report["contractVersion"] == task["contractVersion"]
                and report["release"] == report["cliRelease"] == task["release"]
                and report.get("preparedStarts", False)
                and (not check_action or capability in report["capabilities"])
                and any(p["available"] and p["provider"] == task["provider"]
                        and any(profile["profileId"] == task["profileId"] for profile in p["profiles"])
                        for p in report["providers"]))

    def reserve_start(self, body):
        with self.connect() as db:
            db.execute("SELECT 1 FROM desktop_session WHERE session_id=%s FOR UPDATE", (body.sessionId,))
            row = db.execute("""
                UPDATE occurrence SET start_requested_at=clock_timestamp()
                WHERE workflow_id=%s AND session_id=%s AND state='claimed'
                  AND start_requested_at IS NULL AND result_deadline > clock_timestamp() AND task->>'action' != 'check'
                RETURNING task, result_deadline
            """, (body.workflowId, body.sessionId)).fetchone()
            if row is None:
                raise Conflict()
            if self._can_run(db, body.sessionId, row["task"], check_action=False) and leases.holds(db, body):
                ref = {key: row["task"][key] for key in ("workflowId", "postId", "organizationId")}
                return {**ref, "resultDeadlineAt": row["result_deadline"].isoformat()}
            self._decline(db, body)

    def _decline(self, db, body):
        self._settle(db, body, "claimed", "failed", PublishReceipt(outcome="failed", cliInvoked=False, exitCode=None))

    def deny_start(self, body):
        with self.connect() as db:
            self._settle(db, body, "claimed", "failed", PublishReceipt(
                outcome="failed", cliInvoked=False, exitCode=None, reason="authorization_declined"))

    def start(self, body, latest, refresh=False):
        with self.connect() as db:
            task = latest.model_dump(mode="json", exclude_unset=True)
            previous = self._get(db, body.workflowId)["task"]
            identity = ("workflowId", "postId", "channelId", "organizationId", "bindingId", "provider", "profileId",
                        "platform", "release", "contractVersion")
            if (any(task[key] != previous[key] for key in identity) or not self._can_run(db, body.sessionId, task)
                    or not leases.holds(db, body)):
                self._decline(db, body)
                return None
            if refresh:
                updated = db.execute("""
                    UPDATE occurrence SET start_requested_at=NULL, task=%s
                    WHERE workflow_id=%s AND session_id=%s AND state='claimed' AND start_requested_at IS NOT NULL
                      AND result_deadline > clock_timestamp() RETURNING task
                """, (Jsonb(task), body.workflowId, body.sessionId)).fetchone()
                if updated is None:
                    raise Conflict()
                return updated["task"]
            if body.mediaFailed or body.preparedMedia != latest.media:
                self._decline(db, body)
                return None
            row = db.execute("""
                UPDATE occurrence SET state='started',publish_started_at=clock_timestamp(),task=%s
                WHERE workflow_id=%s AND session_id=%s AND state='claimed' AND start_requested_at IS NOT NULL
                  AND result_deadline > clock_timestamp()
                  AND EXISTS (SELECT 1 FROM profile_lease l WHERE l.grant_id=occurrence.lease_grant_id
                              AND l.expires_at > clock_timestamp())
                RETURNING task
            """, (Jsonb(task), body.workflowId, body.sessionId)).fetchone()
            if row is None:
                raise Conflict()
            return row["task"]

    def _settle(self, db, body, expected, state, receipt):
        stored = Jsonb(receipt.model_dump(exclude_unset=True))
        row = db.execute("""
            UPDATE occurrence SET state=%s, receipt=%s, receipt_history=receipt_history || jsonb_build_array(%s::jsonb),
                overdue_at=coalesce(overdue_at, CASE WHEN state IN ('claimed','started')
                    AND task->>'action'<>'check' AND result_deadline<=clock_timestamp() THEN result_deadline END),
                completed_at=clock_timestamp()
            WHERE workflow_id=%s AND session_id=%s AND state=%s RETURNING workflow_id
        """, (state, stored, stored, body.workflowId, body.sessionId, expected)).fetchone()
        if row is None:
            raise Conflict()
        if expected == "unknown":
            return
        db.execute("""
            UPDATE desktop_session SET last_contact_at=clock_timestamp(), report=jsonb_set(
                report, '{freeSlots}', to_jsonb(least((report->>'capacity')::int, (report->>'freeSlots')::int + 1)))
            WHERE session_id=%s AND EXISTS (
                SELECT 1 FROM occurrence WHERE workflow_id=%s AND lease_grant_id IS NULL)
        """, (body.sessionId, body.workflowId))

    def finish(self, result):
        with self.connect() as db:
            row = db.execute(f"SELECT {RECORD} FROM occurrence WHERE workflow_id=%s FOR UPDATE",
                             (result.workflowId,)).fetchone()
            if row is None:
                raise Missing()
            if row["sessionId"] != result.sessionId:
                raise Conflict()
            receipt = result.receipt
            prior = row["receipt"] or {}
            if row["receipt"] is not None and prior.get("outcome") not in ("unknown", "processing"):
                return row
            if row["task"]["action"] == "check":
                if not isinstance(receipt, CheckReceipt) or row["state"] != "claimed":
                    raise Conflict()
                state = "succeeded" if receipt.platformLogin == "valid" else "failed"
            else:
                if not isinstance(receipt, PublishReceipt) or not row["publishStartedAt"]:
                    raise Conflict()
                if receipt.outcome == "processing":
                    if row["state"] == "started" and not prior:
                        progress = Jsonb(receipt.model_dump(exclude_unset=True))
                        db.execute("""UPDATE occurrence SET receipt=%s, receipt_history=receipt_history || jsonb_build_array(%s::jsonb)
                                      WHERE workflow_id=%s""", (progress, progress, result.workflowId))
                    return self._get(db, result.workflowId)
                if prior.get("outcome") == "unknown" and receipt.outcome == "unknown":
                    return row
                if row["state"] not in ("started", "unknown"):
                    raise Conflict()
                if (receipt.outcome in ("published", "prepared")
                        and row["task"]["noPublish"] != (receipt.outcome == "prepared")):
                    raise Conflict()
                state = "succeeded" if receipt.outcome == "published" else receipt.outcome
            self._settle(db, result, row["state"], state, receipt)
            return self._get(db, result.workflowId)
