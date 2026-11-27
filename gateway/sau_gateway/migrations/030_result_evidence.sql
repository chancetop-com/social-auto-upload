ALTER TABLE occurrence ADD COLUMN publish_started_at timestamptz;
ALTER TABLE occurrence ADD COLUMN overdue_at timestamptz;
ALTER TABLE occurrence ADD COLUMN receipt_history jsonb NOT NULL DEFAULT '[]';
UPDATE occurrence SET publish_started_at = start_requested_at
WHERE state = 'started' OR (start_requested_at IS NOT NULL AND (receipt->>'cliInvoked')::boolean);
UPDATE occurrence SET receipt_history = jsonb_build_array(receipt) WHERE receipt IS NOT NULL;
CREATE INDEX occurrence_result_due ON occurrence(result_deadline) WHERE state IN ('claimed','started');
