-- Record whether a generated summary passed the faithfulness guard.
--
-- The cascade already refuses to return an unfaithful summary from a non-terminal
-- tier, so this column is normally TRUE. It is persisted anyway because the
-- resilience and summarization claims need to be checkable from stored data
-- rather than from application logs, and because a FALSE here is the signal that
-- the deterministic tier itself produced something it could not substantiate.

ALTER TABLE risk_assessments
    ADD COLUMN IF NOT EXISTS summary_faithful BOOLEAN,
    ADD COLUMN IF NOT EXISTS summary_faithfulness_problems TEXT;

CREATE INDEX IF NOT EXISTS idx_assessments_faithful
    ON risk_assessments (summary_faithful)
    WHERE summary_faithful IS NOT TRUE;
