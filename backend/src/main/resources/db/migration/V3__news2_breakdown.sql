-- Per-parameter NEWS2 contributions.
--
-- "NEWS2 = 7" is opaque; "respiratory rate 3, SpO2 2, pulse 2" is actionable
-- and can be checked by hand against the chart. The triage service already
-- computes this; it was simply being discarded at the backend boundary.
--
-- JSONB rather than seven columns: the parameter set belongs to the NEWS2
-- specification, not to this schema, and a future Scale 2 variant should not
-- require a migration here.

ALTER TABLE risk_assessments
    ADD COLUMN IF NOT EXISTS news2_per_parameter JSONB;

COMMENT ON COLUMN risk_assessments.news2_per_parameter IS
    'Per-parameter NEWS2 points, e.g. {"pulse":2,"spo2":1,...}. NULL when the '
    'triage service was unavailable, since the score could not be computed.';
