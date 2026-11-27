ALTER TABLE occurrence ADD COLUMN start_requested_at timestamptz;
CREATE INDEX occurrence_active_target ON occurrence
    ((task->>'provider'), (task->>'profileId'), (task->>'platform'))
    WHERE state IN ('claimed','started');
