CREATE TABLE media_preparation (
    workflow_id text PRIMARY KEY,
    task jsonb NOT NULL,
    expires_at timestamptz NOT NULL,
    offered_at timestamptz
);
CREATE INDEX media_preparation_available ON media_preparation (expires_at) WHERE offered_at IS NULL;
