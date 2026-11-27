from importlib.resources import files
import os

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

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
          'overdue_at AS "overdueAt", publish_started_at AS "publishStartedAt", receipt_history AS "receiptHistory"')


class Store:
    def __init__(self, dsn):
        self.dsn = dsn
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
            return db.execute("""
                INSERT INTO desktop_session(session_id, report) VALUES (%s,%s)
                ON CONFLICT (session_id) DO UPDATE SET report=excluded.report, last_contact_at=clock_timestamp()
                RETURNING session_id AS "sessionId", last_contact_at AS "lastContactAt"
            """, (session.sessionId, Jsonb(session.model_dump(mode="json")))).fetchone()

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

    def claim(self, session_id):
        with self.connect() as db:
            row = db.execute("""
                UPDATE desktop_session SET last_contact_at=clock_timestamp() WHERE session_id=%s RETURNING report
            """, (session_id,)).fetchone()
            if row is None:
                raise Missing()
            report = row["report"]
            if not report["freeSlots"]:
                return None
            # The session row serializes concurrent polls even if a stale report advertises free slots.
            active = db.execute("SELECT count(*) AS n FROM occurrence WHERE session_id=%s AND state IN ('claimed','started')",
                                (session_id,)).fetchone()["n"]
            if active >= report["capacity"]:
                return None
            visible = [{"provider": p["provider"], "profileId": profile["profileId"]}
                       for p in report["providers"] if p["available"] for profile in p["profiles"]]
            row = db.execute("""
                SELECT workflow_id, task FROM occurrence AS pending
                WHERE state='pending' AND (claim_deadline IS NULL OR claim_deadline > clock_timestamp())
                AND task->>'release'=%s AND (task->>'contractVersion')::integer=%s
                AND (task->>'action'='check' OR task->>'release'=%s)
                AND ((target_session=%s) OR
                    (target_session IS NULL AND %s='worker' AND %s::jsonb @> jsonb_build_array(jsonb_build_object(
                         'provider',task->'provider','profileId',task->'profileId'))))
                AND (target_session=%s OR %s::jsonb @> jsonb_build_array(jsonb_build_object('platform',task->'platform','action',task->'action')))
                AND NOT EXISTS (
                    SELECT 1 FROM occurrence busy WHERE busy.state IN ('claimed','started')
                    AND busy.task->>'provider'=pending.task->>'provider'
                    AND busy.task->>'profileId'=pending.task->>'profileId'
                    AND busy.task->>'platform'=pending.task->>'platform'
                )
                ORDER BY created_at, workflow_id LIMIT 1 FOR UPDATE SKIP LOCKED
            """, (report["release"], report["contractVersion"], report.get("cliRelease"), session_id, report["mode"], Jsonb(visible), session_id,
                  Jsonb(report["capabilities"]))).fetchone()
            if row is None:
                return None
            target = [row["task"][key] for key in ("provider", "profileId", "platform")]
            # Two polls may select different pending posts for the same physical target.
            # Take its transaction lock, then check committed occupancy using a new snapshot.
            locked = db.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s::text, 0)) AS held",
                                (Jsonb(target),)).fetchone()
            if not locked["held"] or db.execute("""
                SELECT 1 FROM occurrence WHERE state IN ('claimed','started')
                AND task->>'provider'=%s AND task->>'profileId'=%s AND task->>'platform'=%s
            """, target).fetchone():
                return None
            claimed = db.execute(f"""
                UPDATE occurrence SET state='claimed', session_id=%s, claimed_at=clock_timestamp(),
                    result_deadline=CASE WHEN task->>'action' <> 'check' THEN
                        greatest(clock_timestamp(), (task->>'earliestPublishAt')::timestamptz)
                        + %s * interval '1 second' END
                WHERE workflow_id=%s AND state='pending'
                  AND (claim_deadline IS NULL OR claim_deadline > clock_timestamp())
                RETURNING {RECORD}
            """, (session_id, self.result_seconds, row["workflow_id"])).fetchone()
            if claimed is None:
                db.rollback()
                return None
            db.execute("""
                UPDATE desktop_session SET report=jsonb_set(report, '{freeSlots}', to_jsonb((report->>'freeSlots')::int - 1))
                WHERE session_id=%s
            """, (session_id,))
            return claimed

    def _can_run(self, db, session_id, task):
        report = db.execute("SELECT report FROM desktop_session WHERE session_id=%s FOR UPDATE",
                            (session_id,)).fetchone()["report"]
        capability = {"platform": task["platform"], "action": task["action"]}
        return (report["mode"] == "worker" and report["contractVersion"] == task["contractVersion"]
                and report["release"] == report["cliRelease"] == task["release"]
                and capability in report["capabilities"]
                and any(p["available"] and p["provider"] == task["provider"]
                        and any(profile["profileId"] == task["profileId"] for profile in p["profiles"])
                        for p in report["providers"]))

    def reserve_start(self, body):
        with self.connect() as db:
            row = db.execute("""
                UPDATE occurrence SET start_requested_at=clock_timestamp()
                WHERE workflow_id=%s AND session_id=%s AND state='claimed'
                  AND start_requested_at IS NULL AND result_deadline > clock_timestamp() AND task->>'action' != 'check'
                RETURNING task, result_deadline
            """, (body.workflowId, body.sessionId)).fetchone()
            if row is None:
                raise Conflict()
            if self._can_run(db, body.sessionId, row["task"]):
                ref = {key: row["task"][key] for key in ("workflowId", "postId", "organizationId")}
                return {**ref, "resultDeadlineAt": row["result_deadline"].isoformat()}
            self._decline(db, body)

    def _decline(self, db, body):
        self._settle(db, body, "claimed", "failed", PublishReceipt(outcome="failed", cliInvoked=False, exitCode=None))

    def deny_start(self, body):
        with self.connect() as db:
            self._decline(db, body)

    def start(self, body, latest):
        with self.connect() as db:
            task = latest.model_dump(mode="json", exclude_unset=True)
            previous = self._get(db, body.workflowId)["task"]
            identity = ("workflowId", "postId", "channelId", "organizationId", "bindingId", "provider", "profileId",
                        "platform", "action", "requiredCapability", "release", "contractVersion")
            if any(task[key] != previous[key] for key in identity) or not self._can_run(db, body.sessionId, task):
                self._decline(db, body)
                return None
            row = db.execute("""
                UPDATE occurrence SET state='started',publish_started_at=clock_timestamp(),task=%s
                WHERE workflow_id=%s AND session_id=%s AND state='claimed' AND start_requested_at IS NOT NULL AND result_deadline > clock_timestamp()
                RETURNING task
            """, (Jsonb(task), body.workflowId, body.sessionId)).fetchone()
            if row is None:
                raise Conflict()
            return row["task"]

    def _settle(self, db, body, expected, state, receipt):
        stored = Jsonb(receipt.model_dump(exclude_unset=True))
        row = db.execute("""
            UPDATE occurrence SET state=%s, receipt=%s, receipt_history=receipt_history || jsonb_build_array(%s::jsonb),
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
            WHERE session_id=%s
        """, (body.sessionId,))

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
