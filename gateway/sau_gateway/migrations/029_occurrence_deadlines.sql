ALTER TABLE occurrence ADD COLUMN claim_deadline timestamptz, ADD COLUMN IF NOT EXISTS result_deadline timestamptz;

-- Pre-upgrade publishers sent only the scheduled click time. Immediate tasks have creation time.
UPDATE occurrence SET claim_deadline =
    coalesce((task->>'earliestPublishAt')::timestamptz, created_at) + interval '30 minutes'
WHERE task->>'action' <> 'check';
UPDATE occurrence SET result_deadline =
    greatest(claimed_at, (task->>'earliestPublishAt')::timestamptz) + interval '30 minutes'
WHERE claimed_at IS NOT NULL AND result_deadline IS NULL AND task->>'action' <> 'check';
