"""An expiring cache hint, independent of the durable publish occurrence and profile lease."""
from psycopg.types.json import Jsonb


def enqueue_preparation(store, offer):
    with store.connect() as db:
        db.execute("DELETE FROM media_preparation WHERE expires_at <= clock_timestamp()")
        db.execute("""
            INSERT INTO media_preparation(workflow_id, task, expires_at)
            SELECT %s, %s, %s WHERE %s > clock_timestamp()
            ON CONFLICT (workflow_id) DO NOTHING
        """, (offer.task.workflowId, Jsonb(offer.task.model_dump(mode="json", exclude_unset=True)),
              offer.expiresAt, offer.expiresAt))


def take_preparation(store, session_id):
    with store.connect() as db:
        row = db.execute("""
            SELECT p.workflow_id, p.task FROM media_preparation p JOIN desktop_session s
            ON s.session_id=%s
            WHERE p.offered_at IS NULL AND p.expires_at > clock_timestamp()
              AND s.report->>'mode'='worker' AND (s.report->>'freeSlots')::integer > 0
              AND s.report->'release'=p.task->'release' AND s.report->'cliRelease'=p.task->'release'
              AND s.report->'contractVersion'=p.task->'contractVersion'
              AND (s.report->'capabilities') @> jsonb_build_array(jsonb_build_object(
                   'platform',p.task->'platform', 'action',p.task->'action'))
              AND EXISTS (SELECT 1 FROM jsonb_array_elements(s.report->'providers') provider
                  WHERE provider->'available'='true'::jsonb AND provider->'provider'=p.task->'provider'
                  AND (provider->'profiles') @> jsonb_build_array(jsonb_build_object('profileId',p.task->'profileId')))
              AND NOT EXISTS (SELECT 1 FROM occurrence o WHERE o.workflow_id=p.workflow_id)
            ORDER BY p.expires_at LIMIT 1 FOR UPDATE OF p SKIP LOCKED
        """, (session_id,)).fetchone()
        if row is None or not store._can_run(db, session_id, row["task"]):
            return None
        db.execute("UPDATE media_preparation SET offered_at=clock_timestamp() WHERE workflow_id=%s",
                   (row["workflow_id"],))
        return {"operation": "prepare", "workflowId": row["workflow_id"], "task": row["task"]}
