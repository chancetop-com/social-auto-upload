"""Live physical profile ownership, independent of an occurrence's result history."""
from dataclasses import dataclass
import os
from uuid import uuid4


@dataclass(frozen=True)
class LeasePolicy:
    renew_seconds: int
    validity_seconds: int

    @classmethod
    def from_env(cls):
        renew = int(os.environ.get("GATEWAY_PROFILE_RENEW_SECONDS", 300))
        validity = int(os.environ.get("GATEWAY_PROFILE_LEASE_SECONDS", 900))
        if not 0 < renew < validity:
            raise ValueError("Profile renewal must be positive and shorter than lease validity")
        return cls(renew, validity)


ELIGIBLE_PROFILE = """
    NOT EXISTS (
        SELECT 1 FROM profile_lease lease
        WHERE lease.provider = pending.task->>'provider' AND lease.profile_id = pending.task->>'profileId'
          AND lease.expires_at > clock_timestamp()
          AND (lease.session_id != %s OR EXISTS (
              SELECT 1 FROM occurrence member WHERE member.lease_grant_id = lease.grant_id
                AND member.command_ended_at IS NULL AND member.task->>'platform' = pending.task->>'platform'
          ))
    ) AND NOT EXISTS (
        SELECT 1 FROM occurrence legacy WHERE legacy.lease_grant_id IS NULL
        AND legacy.lease_expires_at > clock_timestamp() AND legacy.state IN ('claimed','started')
        AND legacy.task->>'provider' = pending.task->>'provider'
        AND legacy.task->>'profileId' = pending.task->>'profileId'
    )
"""


def occupied_slots(db, session_id):
    return db.execute("""
        SELECT count(*) AS n FROM occurrence o LEFT JOIN profile_lease l ON l.grant_id=o.lease_grant_id
        WHERE o.session_id=%s AND o.command_ended_at IS NULL AND (
             l.expires_at > clock_timestamp() OR (o.lease_grant_id IS NULL
             AND o.lease_expires_at > clock_timestamp() AND o.state IN ('claimed','started')))
    """, (session_id,)).fetchone()["n"]


def acquire(db, session_id, task, policy):
    key = (task["provider"], task["profileId"])
    grant = uuid4()
    # The unique physical identity serializes first acquisition and takeover even
    # when the two selected pending rows, merchants and platforms all differ.
    db.execute("""
        INSERT INTO profile_lease (provider, profile_id, grant_id, session_id, expires_at)
        VALUES (%s,%s,%s,%s,clock_timestamp() + %s * interval '1 second')
        ON CONFLICT (provider, profile_id) DO NOTHING
    """, (*key, grant, session_id, policy.validity_seconds))
    lease = db.execute("""
        SELECT grant_id, session_id, expires_at FROM profile_lease
        WHERE provider=%s AND profile_id=%s FOR UPDATE
    """, key).fetchone()
    takeover = db.execute("""
        UPDATE profile_lease SET grant_id=%s, session_id=%s, expires_at=clock_timestamp() + %s * interval '1 second'
        WHERE provider=%s AND profile_id=%s AND expires_at <= clock_timestamp()
        RETURNING grant_id, session_id, expires_at
    """, (grant, session_id, policy.validity_seconds, *key)).fetchone()
    lease = takeover or lease
    if lease["session_id"] != session_id:
        return None
    busy = db.execute("""
        SELECT 1 FROM occurrence WHERE lease_grant_id=%s AND command_ended_at IS NULL AND task->>'platform'=%s
    """, (lease["grant_id"], task["platform"])).fetchone()
    if busy:
        return None
    # A joining command gets a full first-renewal window, even when the
    # previous member is just about to finish and stop its heartbeat.
    return db.execute("""
        UPDATE profile_lease SET idle_after=NULL, expires_at=clock_timestamp() + %s * interval '1 second'
        WHERE grant_id=%s AND expires_at > clock_timestamp()
        RETURNING grant_id, expires_at
    """, (policy.validity_seconds, lease["grant_id"])).fetchone()


def renew(db, body, policy):
    # One row is the authority for every platform. Only a running member
    # can extend it; an expired former owner must never revive its grant.
    db.execute("SELECT 1 FROM profile_lease WHERE grant_id=%s AND session_id=%s FOR UPDATE",
               (body.leaseGrantId, body.sessionId))
    row = db.execute("""
        UPDATE profile_lease l SET expires_at=clock_timestamp() + %s * interval '1 second'
        WHERE l.grant_id=%s AND l.session_id=%s AND l.expires_at > clock_timestamp()
          AND EXISTS (SELECT 1 FROM occurrence o WHERE o.workflow_id=%s
                      AND o.lease_grant_id=l.grant_id AND o.command_ended_at IS NULL)
        RETURNING expires_at
    """, (policy.validity_seconds, body.leaseGrantId, body.sessionId, body.workflowId)).fetchone()
    return row["expires_at"] if row else None


def complete(db, body):
    # Serialize with the claimant's next poll/report before taking the physical lock.
    db.execute("SELECT 1 FROM desktop_session WHERE session_id=%s FOR UPDATE", (body.sessionId,))
    locked = db.execute("""
        SELECT 1 FROM profile_lease WHERE grant_id=%s AND session_id=%s FOR UPDATE
    """, (body.leaseGrantId, body.sessionId)).fetchone()
    if not locked:
        return None
    ended = db.execute("""
        UPDATE occurrence o SET command_ended_at=clock_timestamp() FROM profile_lease l
        WHERE workflow_id=%s AND o.session_id=%s AND o.lease_grant_id=%s AND o.command_ended_at IS NULL
          AND l.grant_id=o.lease_grant_id AND l.expires_at > clock_timestamp()
        RETURNING workflow_id
    """, (body.workflowId, body.sessionId, body.leaseGrantId)).fetchone()
    if not ended:
        return None
    db.execute("""
        UPDATE desktop_session SET last_contact_at=clock_timestamp(), report=jsonb_set(
            report, '{freeSlots}', to_jsonb(least((report->>'capacity')::int, (report->>'freeSlots')::int + 1)))
        WHERE session_id=%s
    """, (body.sessionId,))
    idle = db.execute("""
        UPDATE profile_lease l SET idle_after=%s WHERE l.grant_id=%s AND NOT EXISTS (
            SELECT 1 FROM occurrence o WHERE o.lease_grant_id=l.grant_id AND o.command_ended_at IS NULL)
        RETURNING grant_id
    """, (body.workflowId, body.leaseGrantId)).fetchone()
    return bool(idle)


def release(db, body):
    # idle_after fences a delayed closure observation from an earlier quiet period.
    return db.execute("""
        UPDATE profile_lease SET expires_at=clock_timestamp(), idle_after=NULL
        WHERE grant_id=%s AND session_id=%s AND idle_after=%s AND expires_at > clock_timestamp()
        RETURNING grant_id
    """, (body.leaseGrantId, body.sessionId, body.workflowId)).fetchone()


def holds(db, body):
    row = db.execute("""
        SELECT 1 FROM profile_lease l JOIN occurrence o ON l.grant_id=o.lease_grant_id
        WHERE o.workflow_id=%s AND l.session_id=%s AND o.command_ended_at IS NULL
          AND l.expires_at > clock_timestamp() FOR UPDATE OF l
    """, (body.workflowId, body.sessionId)).fetchone()
    return bool(row)
