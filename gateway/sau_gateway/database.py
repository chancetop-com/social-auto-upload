from importlib.resources import files

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


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


RECORD = 'workflow_id AS "workflowId", state, session_id AS "sessionId", task, receipt'


class Store:
    def __init__(self, dsn):
        self.dsn = dsn

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
            db.execute("""
                INSERT INTO occurrence(workflow_id, task, target_session) VALUES (%s,%s,%s)
                ON CONFLICT (workflow_id) DO NOTHING
            """, (task.workflowId, Jsonb(task.model_dump(mode="json")), target_session))
            return self._get(db, task.workflowId)

    def _get(self, db, workflow_id):
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
            active = db.execute("SELECT count(*) AS n FROM occurrence WHERE session_id=%s AND state='claimed'",
                                (session_id,)).fetchone()["n"]
            if active >= report["capacity"]:
                return None
            visible = [{"provider": p["provider"], "profileId": profile["profileId"]}
                       for p in report["providers"] if p["available"] for profile in p["profiles"]]
            row = db.execute("""
                SELECT workflow_id FROM occurrence
                WHERE state='pending' AND task->>'release'=%s AND (task->>'contractVersion')::integer=%s
                AND ((target_session=%s) OR
                    (target_session IS NULL AND %s='worker' AND %s::jsonb @> jsonb_build_array(jsonb_build_object(
                         'provider',task->'provider','profileId',task->'profileId'))))
                AND (target_session=%s OR %s::jsonb @> jsonb_build_array(jsonb_build_object('platform',task->'platform','action',task->'action')))
                ORDER BY created_at, workflow_id LIMIT 1 FOR UPDATE SKIP LOCKED
            """, (report["release"], report["contractVersion"], session_id, report["mode"], Jsonb(visible), session_id,
                  Jsonb(report["capabilities"]))).fetchone()
            if row is None:
                return None
            db.execute("""
                UPDATE desktop_session SET report=jsonb_set(report, '{freeSlots}', to_jsonb((report->>'freeSlots')::int - 1))
                WHERE session_id=%s
            """, (session_id,))
            return db.execute(f"""
                UPDATE occurrence SET state='claimed',session_id=%s,claimed_at=clock_timestamp()
                WHERE workflow_id=%s RETURNING {RECORD}
            """, (session_id, row["workflow_id"])).fetchone()

    def finish(self, result):
        with self.connect() as db:
            row = db.execute("SELECT state,session_id FROM occurrence WHERE workflow_id=%s FOR UPDATE",
                             (result.workflowId,)).fetchone()
            if row is None:
                raise Missing()
            if row["session_id"] != result.sessionId:
                raise Conflict()
            if row["state"] == "claimed":
                db.execute("""
                    UPDATE desktop_session SET last_contact_at=clock_timestamp(), report=jsonb_set(
                        report, '{freeSlots}', to_jsonb(least((report->>'capacity')::int, (report->>'freeSlots')::int + 1)))
                    WHERE session_id=%s
                """, (result.sessionId,))
                state = "succeeded" if result.receipt.platformLogin == "valid" else "failed"
                db.execute("""
                    UPDATE occurrence SET state=%s, receipt=%s, completed_at=clock_timestamp() WHERE workflow_id=%s
                """, (state, Jsonb(result.receipt.model_dump()), result.workflowId))
            return self._get(db, result.workflowId)
