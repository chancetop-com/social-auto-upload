CREATE TABLE profile_lease (
    provider text NOT NULL,
    profile_id text NOT NULL,
    grant_id uuid NOT NULL UNIQUE,
    session_id uuid NOT NULL REFERENCES desktop_session,
    expires_at timestamptz NOT NULL,
    idle_after text,
    PRIMARY KEY (provider, profile_id)
);

ALTER TABLE occurrence ADD COLUMN lease_grant_id uuid,
                       ADD COLUMN lease_expires_at timestamptz,
                       ADD COLUMN command_ended_at timestamptz;

CREATE INDEX occurrence_live_grant ON occurrence (lease_grant_id, (task->>'platform'))
    WHERE lease_grant_id IS NOT NULL AND command_ended_at IS NULL;

-- In-flight commands from the previous protocol can finish with their original receipt.
UPDATE occurrence SET lease_expires_at = clock_timestamp() + interval '15 minutes'
WHERE state IN ('claimed', 'started');
