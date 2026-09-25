-- VitalSync schema.
--
-- Derived features (shock index, pulse pressure, MAP) are persisted rather than
-- recomputed on read. The dashboard and the benchmarks both need them, and
-- recomputing in SQL would create a second definition that can drift away from
-- the Python one in ml-service/vitalsync_ml/features.py.

CREATE TABLE IF NOT EXISTS patients (
    patient_id   VARCHAR(64) PRIMARY KEY,
    display_name VARCHAR(128) NOT NULL,
    age          INTEGER,
    sex          VARCHAR(16),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS vital_readings (
    id                BIGSERIAL PRIMARY KEY,
    patient_id        VARCHAR(64) NOT NULL REFERENCES patients(patient_id) ON DELETE CASCADE,
    observed_at       TIMESTAMPTZ NOT NULL,
    recorded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    heart_rate        DOUBLE PRECISION NOT NULL,
    spo2              DOUBLE PRECISION NOT NULL,
    temperature_c     DOUBLE PRECISION NOT NULL,
    respiratory_rate  DOUBLE PRECISION NOT NULL,
    systolic_bp       DOUBLE PRECISION NOT NULL,
    diastolic_bp      DOUBLE PRECISION NOT NULL,
    glucose_mgdl      DOUBLE PRECISION,

    on_oxygen         BOOLEAN NOT NULL DEFAULT FALSE,
    alert             BOOLEAN NOT NULL DEFAULT TRUE,

    shock_index       DOUBLE PRECISION,
    pulse_pressure    DOUBLE PRECISION,
    map_mmhg          DOUBLE PRECISION
);

-- Telemetry retrieval is always "latest N for one patient".
CREATE INDEX IF NOT EXISTS idx_readings_patient_observed
    ON vital_readings (patient_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS risk_assessments (
    id                  BIGSERIAL PRIMARY KEY,
    patient_id          VARCHAR(64) NOT NULL REFERENCES patients(patient_id) ON DELETE CASCADE,
    reading_id          BIGINT REFERENCES vital_readings(id) ON DELETE CASCADE,

    risk_band           VARCHAR(16) NOT NULL,
    confidence          DOUBLE PRECISION,
    prob_low            DOUBLE PRECISION,
    prob_medium         DOUBLE PRECISION,
    prob_high           DOUBLE PRECISION,

    -- Deterministic score stored next to the model output so the two can be
    -- compared after the fact without re-running inference.
    news2_total         INTEGER,
    news2_band          VARCHAR(16),

    model_version       VARCHAR(64),
    ml_latency_ms       DOUBLE PRECISION,
    ml_available        BOOLEAN NOT NULL DEFAULT TRUE,

    summary_text        TEXT,
    summary_provider    VARCHAR(32),
    summary_latency_ms  DOUBLE PRECISION,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_assessments_patient_created
    ON risk_assessments (patient_id, created_at DESC);

-- Which tier answered is a measured result, not a log line: the resilience
-- experiment reads it straight out of this column.
CREATE INDEX IF NOT EXISTS idx_assessments_provider
    ON risk_assessments (summary_provider);

INSERT INTO patients (patient_id, display_name, age, sex) VALUES
    ('P001', 'Simulated Patient 001', 67, 'F'),
    ('P002', 'Simulated Patient 002', 54, 'M'),
    ('P003', 'Simulated Patient 003', 78, 'F'),
    ('P004', 'Simulated Patient 004', 41, 'M')
ON CONFLICT (patient_id) DO NOTHING;
