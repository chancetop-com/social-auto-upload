CREATE TABLE desktop_session (
    session_id uuid PRIMARY KEY,
    report jsonb NOT NULL,
    last_contact_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE occurrence (
    workflow_id text PRIMARY KEY,
    task jsonb NOT NULL,
    target_session uuid REFERENCES desktop_session,
    state text NOT NULL DEFAULT 'pending',
    session_id uuid REFERENCES desktop_session,
    receipt jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    claimed_at timestamptz,
    completed_at timestamptz
);

CREATE INDEX occurrence_pending ON occurrence (created_at, workflow_id) WHERE state = 'pending';
CREATE INDEX occurrence_claimant ON occurrence (session_id) WHERE state = 'claimed';
