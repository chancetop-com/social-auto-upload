ALTER TABLE desktop_package ADD COLUMN defect_reason text;

-- Carry forward confirmed defects, including evidence received after a batch expired.
UPDATE desktop_package p SET defect_reason=r.pause_reason
FROM desktop_release_batch b JOIN desktop_release r USING (release_id)
WHERE r.packages->>b.target=p.sha256 AND r.pause_reason IS NOT NULL AND (
    b.phase='defect' OR EXISTS (SELECT 1 FROM desktop_release_late_report late
        WHERE late.batch_id=b.batch_id AND late.evidence->>'phase'='defect')
);

UPDATE desktop_release r SET pause_reason=bad.defect_reason
FROM desktop_package bad
WHERE bad.defect_reason IS NOT NULL AND r.pause_reason IS NULL
    AND EXISTS (SELECT 1 FROM jsonb_each_text(r.packages) p WHERE p.value=bad.sha256);

UPDATE desktop_release_batch b SET phase='paused'
FROM desktop_release r WHERE r.release_id=b.release_id AND r.pause_reason IS NOT NULL
    AND b.phase IN ('assigned','draining','staging','switched');
