CREATE TABLE desktop_package (
    sha256 text PRIMARY KEY,
    size_bytes bigint NOT NULL DEFAULT 0
);
CREATE TABLE desktop_package_chunk (
    sha256 text NOT NULL REFERENCES desktop_package,
    seq integer NOT NULL,
    data bytea NOT NULL,
    PRIMARY KEY (sha256, seq)
);
CREATE TABLE desktop_release (
    release_id uuid PRIMARY KEY,
    environment text NOT NULL CHECK (environment = 'dev'),
    revision text NOT NULL,
    version text NOT NULL,
    contract_version integer NOT NULL,
    packages jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    pause_reason text,
    superseded boolean NOT NULL DEFAULT false,
    UNIQUE (environment, revision)
);
CREATE UNIQUE INDEX desktop_release_current ON desktop_release (environment) WHERE NOT superseded;
ALTER TABLE desktop_session ADD COLUMN first_seen_at timestamptz NOT NULL DEFAULT clock_timestamp();
CREATE TABLE desktop_installation (
    machine_id uuid PRIMARY KEY,
    target text NOT NULL,
    revision text,
    sha256 text,
    worker_session uuid REFERENCES desktop_session,
    last_seen timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE desktop_release_batch (
    batch_id uuid PRIMARY KEY,
    release_id uuid NOT NULL REFERENCES desktop_release,
    machine_id uuid NOT NULL REFERENCES desktop_installation,
    target text NOT NULL,
    prior_session uuid,
    phase text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    deadline timestamptz NOT NULL,
    replacement_for uuid REFERENCES desktop_release_batch,
    confirmed_session uuid REFERENCES desktop_session,
    check_workflow text REFERENCES occurrence,
    late_phase text,
    late_reason text,
    late_at timestamptz
);
CREATE UNIQUE INDEX desktop_one_active_batch ON desktop_release_batch (release_id)
WHERE phase IN ('assigned','draining','staging','switched');
CREATE INDEX desktop_machine_batches ON desktop_release_batch (machine_id,release_id,created_at);
CREATE TABLE desktop_release_late_report (
    batch_id uuid NOT NULL REFERENCES desktop_release_batch,
    evidence jsonb NOT NULL,
    received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(batch_id, evidence)
);
ALTER TABLE desktop_release_batch ADD COLUMN switched_at timestamptz;
