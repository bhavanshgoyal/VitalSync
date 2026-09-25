# VitalSync — Master Implementation & Research Plan

Status: authoritative plan. Supersedes `COMPLETE_IMPLEMENTATION_PLAN.md` (retained as `legacy/`).
Date: 2026-09-24

---

## 0. Why this plan differs from the previous one

The previous plan was written without access to the Kaggle dataset and therefore
specified a synthetic fallback and a three-class `LOW/NORMAL/HIGH` target. Both
assumptions are now known to be wrong in ways that matter for publication.

### Finding 1 — the dataset is present

`nasirayub2/human-vital-sign-dataset` v1 is cached locally:

```
~/.cache/kagglehub/datasets/nasirayub2/human-vital-sign-dataset/versions/1/
    human_vital_signs_dataset_2024.csv        200,020 rows x 17 cols, 37 MB
```

Zero nulls, zero duplicate rows.

### Finding 2 — the dataset's label is a deterministic function of two variables

Recovered rule, verified against all 200,020 rows with **zero mismatches**:

```
Risk Category = "High Risk"   if   (Heart Rate > 90)
                               or  (Derived_BMI > 30)
                               or  (Derived_BMI < 18.5)
              = "Low Risk"    otherwise
```

Consequences:

* There is no `Normal` class. The dataset is binary. The three-class
  `LOW/NORMAL/HIGH` design in the milestone cannot be trained from this data.
* Every vital sign lies inside the normal reference range:
  HR 60–99, SpO2 95.0–100.0, SBP 110–139, DBP 70–89, temp 36.0–37.5, RR 12–19.
  The dataset contains **no physiologically abnormal observation**.
* Class-conditional means for SpO2, SBP, DBP, temperature, respiratory rate and
  MAP are equal to three decimal places. Those six variables carry no label
  information whatsoever.
* The only discriminative variables are `Heart Rate` and `Derived_BMI`
  (and `Height`/`Weight`, through BMI).
* Therefore any classifier's headline accuracy on this dataset is a measurement
  of **Boolean rule recovery**, bounded above by 100%, and is not evidence of
  clinical predictive capability.

A reviewer who runs a decision tree on this dataset reproduces the rule in
seconds. Reporting "99% accuracy at patient risk prediction" without this
disclosure is the single largest reviewer risk in the project.

### Finding 3 — turning the finding into the contribution

The audit is not a setback; it is the most defensible novel content available.
The plan below therefore restructures the research around **two tracks**:

* **Track A — dataset audit.** Reproduce the RF/GB experiment faithfully, then
  publish the recovered rule and show that a 3-clause rule attains 100% where the
  learned models attain ~99%. Framed as a caution about label provenance in
  public physiological datasets.
* **Track B — the deployable triage model.** Because Track A's label is unusable
  clinically, the model actually served by the system is trained against
  **NEWS2** (Royal College of Physicians National Early Warning Score 2), a
  published, peer-reviewed clinical escalation standard, over a simulated cohort
  that spans the full physiological range including deterioration.

Track B raises an obvious objection — NEWS2 is itself a deterministic function
of vitals, so training a model on NEWS2 labels reproduces the leakage problem of
Track A. Section 3 resolves this; the resolution is the paper's actual
experimental claim.

---

## 1. Frozen research claims

### Central claim

> A decoupled IoMT architecture can isolate continuous telemetry ingestion and
> deterministic low-latency risk triage from slower, less reliable generative
> summarization, remaining fully available through a provider cascade that
> terminates in a deterministic fallback.

### Secondary claim (Track A)

> The risk label in a widely-downloaded public vital-signs dataset is a
> deterministic three-clause rule over heart rate and BMI. High reported
> classification scores on this dataset are an artifact of label construction.

### Tertiary claim (Track B)

> Under realistic IoMT sensor noise and dropout, a learned triage model recovers
> the clean-signal NEWS2 escalation band more reliably than the NEWS2 rule
> applied directly to the corrupted observations.

### Claims explicitly out of scope

Not claimed anywhere in code, docs or paper: clinical accuracy, diagnosis,
outcome improvement, admission reduction, alert-burden reduction in practice,
production readiness, regulatory clearance.

---

## 2. Track A — dataset audit (`ml-service/vitalsync_ml/kaggle_audit.py`)

| Step | Action | Output |
|---|---|---|
| A1 | Load CSV, assert shape 200020x17, log nulls/dups | `audit.json` |
| A2 | Per-class descriptive stats for every numeric column | `audit.json` |
| A3 | Mutual information of each feature w.r.t. label | ranked table |
| A4 | Fit depth-3 decision tree on raw features; export rule text | tree rule |
| A5 | Assert candidate rule `HR>90 or BMI>30 or BMI<18.5` reproduces label exactly | pass/fail |
| A6 | Train RF(100) and GB(100) as the milestone specified; report acc / macro-F1 / per-class | `audit.json` |
| A7 | Ablation: train on the six non-discriminative vitals only; show collapse to chance | `audit.json` |

A7 is the decisive evidence: if a model trained on SpO2/BP/temp/RR alone scores
at the base rate (~0.5255), the vitals demonstrably carry no label signal.

The audit is a hard gate — A5 failing means the rule statement in the paper is
wrong and must be corrected before anything downstream is trusted.

---

## 3. Track B — deployable triage model

### 3.1 Labeler: NEWS2

Implemented in `news2.py` from the RCP 2017 specification. Per-parameter scores:

| Parameter | 3 | 2 | 1 | 0 | 1 | 2 | 3 |
|---|---|---|---|---|---|---|---|
| Resp rate /min | ≤8 | | 9–11 | 12–20 | | 21–24 | ≥25 |
| SpO2 % (Scale 1) | ≤91 | 92–93 | 94–95 | ≥96 | | | |
| Supplemental O2 | | Yes | | Air | | | |
| Systolic BP mmHg | ≤90 | 91–100 | 101–110 | 111–219 | | | ≥220 |
| Pulse /min | ≤40 | | 41–50 | 51–90 | 91–110 | 111–130 | ≥131 |
| Consciousness | | | | Alert | | | CVPU |
| Temperature °C | ≤35.0 | | 35.1–36.0 | 36.1–38.0 | 38.1–39.0 | ≥39.1 | |

Aggregate → escalation band (the model's three classes):

| Band | Condition |
|---|---|
| `LOW` | aggregate 0–4 **and** no single parameter scores 3 |
| `MEDIUM` | aggregate 5–6, **or** any single parameter scores 3 |
| `HIGH` | aggregate ≥ 7 |

This replaces `LOW/NORMAL/HIGH`. NEWS2 has no "normal" band; `LOW` *is* the
normal band. The rename is deliberate and documented — it trades cosmetic
continuity with the milestone for a citable clinical grounding.

### 3.2 Resolving the leakage objection

NEWS2 applied to *clean* physiology is deterministic, so learning it from clean
inputs is circular. The experiment therefore separates latent truth from
observation:

```
latent physiology  x*   ──NEWS2──►  y*   (ground-truth band, never observed)
        │
        ├── sensor noise, quantization, dropout, cuff error, motion artifact
        ▼
observed telemetry x̂    ──────────►  model input
```

* Ground truth `y*` is NEWS2 evaluated on the **latent** values `x*`.
* Both the rule baseline and the learned models see only the **corrupted** `x̂`.
* The rule baseline computes NEWS2 on `x̂` — which is what a conventional
  threshold monitor does in practice.
* The learned model is trained on `(x̂, y*)` pairs and can therefore internalise
  the noise distribution, soften band boundaries, and exploit cross-parameter
  redundancy that a per-parameter rule cannot.

This is a real, falsifiable comparison with a possible negative result. Sanity
check: at noise σ = 0 the rule must score exactly 1.0 and the model must not
exceed it. If the rule does not hit 1.0 at σ=0 the generator or scorer is wrong.

### 3.3 Sensor corruption model (`datagen.py`)

Per-channel, calibrated to published device characteristics and kept explicit in
config so a reviewer can change them:

| Channel | Corruption |
|---|---|
| Heart rate | Gaussian σ=2.5 bpm + 1.5% motion-artifact spikes (+15–40 bpm) |
| SpO2 | Gaussian σ=1.5 % + 2% perfusion dropout (reads 3–8% low) |
| Respiratory rate | Gaussian σ=1.5, integer quantization |
| Temperature | Gaussian σ=0.15 °C, 0.1 °C quantization |
| Systolic BP | Gaussian σ=5 mmHg (cuff), integer |
| Diastolic BP | Gaussian σ=4 mmHg, integer |
| Any channel | 3% missing → imputed with cohort median before inference |

### 3.4 Cohort generator

Latent physiology sampled as a mixture so all three NEWS2 bands are populated:

* 60% stable, 25% mild derangement, 15% acute deterioration.
* Correlated channels (tachycardia ↔ tachypnoea ↔ hypotension in the septic
  component) rather than independent marginals, so the model cannot win purely
  through channel independence.
* Fixed seed. Row count configurable, default 120,000.
* Patient-level grouping so the train/test split is **by patient**, not by row —
  prevents the same simulated patient appearing in both splits.

### 3.4a Known limitation: two NEWS2 parameters are not wearable-derived

Supplemental oxygen and consciousness (AVPU) are NEWS2 inputs, but neither is
sensed by a wearable -- both are recorded by staff at the bedside. The cohort
generator makes both vary with latent severity (oxygen probability rises to
0.85, non-alert probability to 0.50 at high severity), so the trained model
learns to use them.

A deployment fed only by wearables would never populate them, and the API
defaults them to the benign case (`on_oxygen=false`, `alert=true`). The model
would then be running on five of seven NEWS2 parameters against a training
distribution where all seven carried signal -- a silent train/serve mismatch
that degrades exactly the HIGH band, because reduced consciousness and oxygen
therapy are both strong severity markers.

Handling:

* The simulator sends real values for both, so the demo is not misleading.
* The API keeps them as explicit, documented inputs rather than hidden defaults.
* The paper must state that reported Track B performance assumes both are
  available, and that a sensor-only deployment is an untested weaker case.

Closing this properly would require either a wearables-only ablation (train and
test with both flags fixed at their defaults) or an explicit "observation
incomplete" state surfaced to the clinician. Neither is implemented.

### 3.5 Models compared

| ID | Model |
|---|---|
| B0 | NEWS2 rule applied to observed `x̂` (primary baseline) |
| B1 | Two-tier per-parameter alarm set: a *warning* breach (HR>100, SpO2<92, SBP<100, T>38.0, RR>20) maps to `MEDIUM`, a *critical* breach (HR>130, SpO2<90, SBP<90, T>39.0, RR>25) maps to `HIGH`, otherwise `LOW` |
| B2 | Logistic regression (multinomial, scaled) |
| B3 | Random Forest, 100 trees |
| B4 | Gradient Boosting, 100 estimators |

Selection metric: **macro-F1** on the held-out patient split, pre-registered
and not changed retrospectively.

Macro-F1 is nonetheless insufficient on its own: it scores a missed HIGH and a
spurious HIGH identically. Every model is therefore also reported with HIGH
recall, missed-HIGH rate (a HIGH observation called LOW) and an asymmetric mean
cost. Where these disagree with macro-F1 the disagreement is recorded as a
result rather than resolved by swapping criteria after seeing the numbers.
`--select-by mean_cost` is available for the cost-optimal choice.

### 3.6 Features

Seven raw channels — HR, SpO2, temperature, respiratory rate, SBP, DBP, plus
optional glucose (absent from Kaggle data; kept nullable in the API contract) —
and derived:

```
Shock Index      SI  = HR / SBP
Pulse Pressure   PP  = SBP - DBP
Mean Arterial P  MAP = (SBP + 2*DBP) / 3
```

Shock Index is retained from the milestone and is genuinely informative here
(unlike in Track A, where HR alone determines half the rule).

### 3.7 Artifacts

```
artifacts/risk_model.joblib     sklearn Pipeline (imputer → scaler → estimator)
artifacts/model_card.json       version, features, classes, training config, hashes
artifacts/metrics.json          all five models, full per-class report
artifacts/benchmark.json        latency distribution
artifacts/audit.json            Track A results
```

Model and scaler ship as one `Pipeline` so the service cannot desynchronize
preprocessing from the estimator — a common source of silent production skew.

---

## 4. ML inference service

FastAPI, stateless, artifact loaded once at startup.

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness + model loaded flag |
| `GET /model` | model card: version, classes, features, metrics summary |
| `POST /predict` | single observation → band, probabilities, derived features |
| `POST /predict/batch` | vectorised, for benchmarking |

Response contract:

```json
{
  "risk": "MEDIUM",
  "probabilities": {"LOW": 0.08, "MEDIUM": 0.79, "HIGH": 0.13},
  "confidence": 0.79,
  "news2": {"total": 5, "per_parameter": {...}, "band": "MEDIUM"},
  "derived": {"shock_index": 0.71, "pulse_pressure": 44, "map": 93.3},
  "model_version": "vitalsync-triage-1.0.0",
  "disclaimer": "Research prototype. Not a medical device. Not for clinical use."
}
```

Returning the deterministic NEWS2 score **alongside** the model output is a
deliberate design choice: it gives the clinician-facing layer an auditable,
explainable number next to the opaque one, and gives the paper a per-request
agreement measurement for free.

Validation rejects physiologically impossible input (HR ≤ 0 or > 300,
SpO2 outside 0–100, etc.) with HTTP 422.

---

## 5. Backend — Spring Boot

Pinned stack (all versions verified against Maven Central on 2026-09-24):

| Component | Version | Note |
|---|---|---|
| Java | 21 (Temurin) | LTS |
| Spring Boot | 3.5.16 | latest stable 3.5; milestone's 3.4.13 is superseded |
| PostgreSQL driver | 42.7.13 | |
| JJWT | 0.13.0 | |
| Flyway | Boot-managed | schema migration |
| LangChain4j | 1.20.0 | `langchain4j-ollama`, `langchain4j-google-ai-gemini` |

LangChain4j is used as **plain `@Bean`s, not the Spring Boot starters**, to avoid
coupling the LLM library's starter to the Boot version. Providers are optional
beans — absent config means the tier is skipped, not a startup failure.

Persistence uses `JdbcTemplate` + Flyway rather than JPA: explicit SQL, no hidden
N+1 or lazy-loading behaviour in a system whose headline claim is about latency.

### Endpoints

| Method | Path | Auth | Behaviour |
|---|---|---|---|
| POST | `/api/v1/auth/token` | none | issue JWT |
| POST | `/api/v1/telemetry` | JWT | validate, persist, enqueue async analysis, **202** |
| GET | `/api/v1/patients` | JWT | roster with latest risk |
| GET | `/api/v1/patients/{id}/vitals?limit=` | JWT | recent readings, newest first |
| GET | `/api/v1/patients/{id}/risk/latest` | JWT | latest assessment |
| POST | `/api/v1/patients/{id}/analyze` | JWT | force synchronous analysis (demo/bench) |
| GET | `/api/v1/system/providers` | JWT | active cascade tiers + per-provider counts |
| GET | `/actuator/health` | none | liveness/readiness |

**Ingestion must never block on the LLM.** `POST /telemetry` returns 202 after
the database write; analysis runs on a bounded `ThreadPoolTaskExecutor`
(core 4, max 8, queue 500, caller-runs rejection). This is the architectural
claim — it has to be true in code, and Section 8's test T-ASYNC proves it.

### Summarization cascade

```
ML triage (independent, always runs)
      │
      ▼
Ollama  ──fail/timeout──►  Gemini  ──fail/timeout──►  Rule-based (never fails)
```

Each tier records which provider answered and the elapsed time; both are
persisted on the assessment row so resilience is measurable from the database
rather than from logs.

Prompt constraints: bounded context (latest reading + trend deltas over the last
N readings + ML band), explicit prohibition on diagnosis and on inventing
findings not present in the numbers, exactly three bullets, output labelled as
clinician-review material.

---

## 6. Database

```sql
patients(patient_id PK, display_name, age, sex, created_at)

vital_readings(id BIGSERIAL PK, patient_id FK, observed_at, recorded_at,
               heart_rate, spo2, temperature_c, respiratory_rate,
               systolic_bp, diastolic_bp, glucose_mgdl NULL,
               on_oxygen, alert,                          -- NEWS2 context flags
               shock_index, pulse_pressure, map_mmhg)

risk_assessments(id BIGSERIAL PK, patient_id FK, reading_id FK,
                 risk_band, confidence, prob_low, prob_medium, prob_high,
                 news2_total, news2_band, model_version,
                 ml_latency_ms, ml_available,              -- false = triage was down
                 summary_text, summary_provider, summary_latency_ms,
                 created_at)
```

`ml_available` is what the degraded-mode test (T-CASCADE-4) and the resilience
benchmark (E5) both key off: it is the durable record that a given assessment
was produced without the triage service, distinguishing "system down" from
"system said LOW."

Indexes: `(patient_id, observed_at DESC)` on readings,
`(patient_id, created_at DESC)` on assessments.

Derived features are persisted, not recomputed on read — the dashboard and the
benchmark both need them and recomputing invites drift between the SQL and the
Python definitions.

Partitioning by `observed_at` range is documented as the scale-out path but not
implemented; at prototype volumes it would be unjustified complexity.

---

## 7. Dashboard

Single static page served by Boot. Chart.js from CDN. Deliberately minimal — the
contribution is architectural, and an elaborate UI would invite the reviewer to
evaluate the wrong thing.

Shows: patient selector, latest HR / SpO2 / temp / BP / RR tiles, NEWS2 total
next to ML band, confidence, the three-bullet summary, **which provider
produced it**, and its latency.

Trends are one measure per chart (HR, SpO2, RR each alone; BP as systolic +
diastolic together, since both are mmHg on a comparable scale). Heart rate and
SpO2 are deliberately **not** plotted on a shared twin-axis chart: they are
different units (bpm vs. %), and dual-axis charts let the two independently
chosen axis ranges manufacture an apparent correlation that isn't in the data.
One axis per figure is a hard rule, not a stylistic choice.

Surfacing the provider in the UI is intentional: the resilience cascade is the
paper's claim, so it should be visible, not buried.

---

## 8. Test plan

### Python (`pytest`)

| ID | Test |
|---|---|
| P-NEWS-1..7 | Each NEWS2 parameter scores correctly at every boundary value |
| P-NEWS-BAND | Band assignment, incl. the "single parameter = 3 ⇒ MEDIUM" rule |
| P-FEAT | Shock index / PP / MAP correctness + divide-by-zero guard |
| P-GEN | Generator produces all three bands; σ=0 ⇒ rule accuracy exactly 1.0 |
| P-SPLIT | No patient id appears in both train and test |
| P-API-OK | `/predict` happy path, schema conformance |
| P-API-422 | Out-of-range input rejected |
| P-API-MISSING | Nullable glucose and missing channels handled |
| P-AUDIT | Kaggle rule reproduces label exactly (skipped if CSV absent) |
| P-COST | Asymmetric cost: under-triage costs more than over-triage; missed-HIGH counted only when a HIGH is called LOW |
| P-CALIB | ECE zero when calibrated, positive gap when over-confident, confidence 1.0 lands in the top bin |

### Java (`JUnit 5` + Testcontainers)

| ID | Test |
|---|---|
| T-JWT | issue/validate/expire/tamper |
| T-AUTH | unauthenticated request → 401 |
| T-VALID | malformed telemetry → 400 with field detail |
| T-PERSIST | POST telemetry → row in Postgres (Testcontainers) |
| T-ASYNC | POST returns 202 while ML client is stalled 3 s — **proves decoupling** |
| T-CASCADE-1 | Ollama up → provider recorded `ollama` |
| T-CASCADE-2 | Ollama down, Gemini up → `gemini` |
| T-CASCADE-3 | both down → `rule-based`, still 3 bullets |
| T-CASCADE-4 | ML service down → assessment degraded but request still 202 |
| T-LATEST | latest-risk endpoint reflects persisted state |
| T-FAITH-1 | Fabricated vital value rejected; cascade falls through |
| T-FAITH-2 | Named condition rejected; descriptive physiology allowed |
| T-FAITH-3 | Deterministic tier output is always faithful |

T-ASYNC is the single most important test in the repository; if it passes with a
stalled ML client, the decoupling claim is substantiated.

### Experiments (`bench/`)

| ID | Experiment | Reported |
|---|---|---|
| E1 | Track A audit | rule verification, RF/GB scores, vitals-only ablation |
| E2 | Track B classification | 5 models × acc/macro-F1/HIGH-recall/missed-HIGH/cost, across noise levels, **mean over 3 seeds with 95% CI** |
| E3 | ML latency, 1000 single predictions | mean, p50, p95, p99, max |
| E4 | Ingestion throughput at 10/50/100/250 req/s | throughput, error rate, p95 |
| E5 | Resilience, 4 provider conditions | success rate, time-to-summary |
| E6 | Notification event counts: thresholds vs band vs band-transition | events per window, **framed as event-count arithmetic, not clinical benefit** |
| E7 | Calibration of the selected model | ECE, MCE, Brier, reliability table |
| E8 | Wearable-only deployment ablation | cost of the silent train/serve mismatch |

E6 carries an explicit caveat in both code and paper: counting downstream events
is not a measurement of clinician alert fatigue.

---

## 9. Reproducibility

* Every experiment writes a JSON artifact; every paper table is generated from
  those JSONs by `paper/make_tables.py`. No number is typed into the LaTeX by
  hand.
* Fixed seeds throughout; seed recorded in each artifact.
* `environment.json` captures Python/Java/OS/library versions at run time.
* `run_all.ps1` / `run_all.sh` reproduce every result from a clean checkout.
* Dataset is *not* vendored (Kaggle licensing); `fetch_dataset.py` retrieves it
  and records the resolved path and SHA-256.

---

## 10. Paper revisions required

1. Retitle the results section to distinguish rule recovery (Track A) from
   triage under noise (Track B).
2. Add a subsection presenting the recovered label rule as a finding, with the
   ablation table.
3. Replace all synthetic-only numbers with generated tables.
4. State the dataset's binary label and absence of abnormal observations in
   Limitations.
5. Keep NIST AI RMF / GenAI Profile and FDA CDS guidance as regulatory framing
   only, never as efficacy evidence.
6. Reproducibility appendix: commands, seeds, artifact list, versions.

---

## 11. Build order

1. `ml-service` package: schema, features, NEWS2, generator — with tests. ✅ gate: pytest green
2. Track A audit; confirm the rule. ✅ gate: A5 passes
3. Track B training + evaluation. ✅ gate: σ=0 sanity check holds
4. FastAPI service + API tests.
5. Database migration + Spring Boot skeleton + security.
6. Telemetry ingestion, async analysis, ML client.
7. Summarization cascade with the three providers.
8. Dashboard.
9. Docker Compose wiring.
10. Java test suite (Testcontainers).
11. Benchmarks E3–E6.
12. Paper table generation + LaTeX update.

Each stage is verified before the next begins; no stage is reported complete on
the basis of code existing.

---

## 12. Known environment constraints

* No local JDK or Maven → the Java build and tests run inside
  `maven:3.9-eclipse-temurin-21`. Real compilation and real test execution, just
  containerised.
* No local `pdflatex` → LaTeX compiles in a `texlive` container; if that image is
  unavailable the `.tex` and generated tables are still delivered and the PDF is
  the user's step.
* Docker Engine 29.6.1 + Compose v5.2.0 present; Maven Central, PyPI and Docker
  Hub all reachable.
* Ollama is not installed here; the Ollama tier is verified by contract tests
  against a stub, and left as a live opt-in for the user.
