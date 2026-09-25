# VitalSync — implementation status

Date: 2026-09-24. Supersedes the earlier status note at the repository root,
which was written before the dataset was located and is wrong on two points: it
states the Kaggle dataset "was not supplied" (it is present and cached), and it
describes a three-class `LOW/NORMAL/HIGH` target (the dataset is binary, and the
deployed model uses NEWS2 bands).

## What is verified, and how

Every row below was checked by running it, not by inspecting code.

| Component | Status | Evidence |
|---|---|---|
| NEWS2 scorer | Done | 104 pytest cases incl. every parameter boundary |
| Cohort generator (latent/observed) | Done | σ=0 identity check is exact (1.000000) |
| Track A dataset audit | Done | `artifacts/audit.json`, rule exact on 200,020/200,020 |
| Track B training + selection | Done | `artifacts/metrics.json` |
| Clinical-cost metrics | Done | 14 pytest cases in `test_metrics.py` |
| Calibration (ECE/MCE/Brier) | Done | `metrics.json → calibration` |
| Noise sweep with 95% CIs | Done | `artifacts/benchmark.json`, 3 seeds/cell |
| Wearable-only ablation | Done | `artifacts/wearable_ablation.json` |
| FastAPI inference service | Done | contract tests + live container |
| Spring Boot backend | Done | 45 JUnit tests, Testcontainers PostgreSQL 16 |
| JWT auth | Done | issue/verify/expire/tamper/short-secret tests |
| Async decoupled ingestion | Done | returns <1s against a 3s stalled ML service |
| Summarization cascade | Done | all tier-failure combinations tested |
| Faithfulness guard | Done | 10 JUnit tests; persisted to DB and queryable |
| PostgreSQL schema + Flyway | Done | V1 + V2 applied in a live container |
| Clinician dashboard | Done | served by Boot, one measure per chart |
| Docker Compose stack | Done | 3 services healthy, end-to-end verified |
| Throughput benchmark | Done | `artifacts/throughput.json` |
| Resilience benchmark | Done | `artifacts/resilience.json` |
| Event-count comparison | Done | `artifacts/alert_compression.json` |
| Reproducibility scripts | Done | `run_all.sh` / `run_all.ps1`, `make_tables.py` |
| Paper tables | Generated | `paper/tables/*.tex`, 7 tables, none hand-typed |
| Live Ollama / Gemini run | **Not done** | no Ollama installed, no API key in this environment |
| Clinical validation | **Not claimed** | out of scope, stated everywhere |

Test totals: **104 Python + 45 Java = 149**, all passing.

## Headline results

**Track A — the public dataset's label is a rule.**
`High Risk ⟺ HR > 90 OR BMI > 30 OR BMI < 18.5`, exact on all 200,020 rows.
RF and GB both reach 1.00000 accuracy because they recover that Boolean, not
because vitals predict risk. A model trained on SpO2/BP/temperature/respiratory
rate alone scores 0.5185 against a 0.5255 majority-class baseline — those
channels carry no label information at all.

**Track B — a learned model beats the rule only once observations are noisy.**
Macro-F1, mean of 3 seeds, 95% CI on the difference:

| σ | NEWS2 rule | Gradient boosting | Δ | 95% CI |
|---|---|---|---|---|
| 0.0 | 1.0000 | 0.9659 | −0.0341 | [−0.0381, −0.0300] |
| 0.5 | 0.8669 | 0.8737 | +0.0067 | [+0.0030, +0.0105] |
| 1.0 | 0.7976 | 0.8152 | +0.0177 | [+0.0158, +0.0195] |
| 2.0 | 0.6819 | 0.7428 | +0.0609 | [+0.0553, +0.0665] |
| 3.0 | 0.5855 | 0.6653 | +0.0798 | [+0.0644, +0.0951] |

At σ=0 the rule *is* the label generator, so the model must lose — and it does,
significantly. That negative result is what makes the positive ones credible.

**Selection criteria disagree, and that is a finding.**
Macro-F1 picks gradient boosting; asymmetric clinical cost and missed-HIGH both
pick random forest, which has 5.9× fewer HIGH observations reported as LOW
(0.0014 vs 0.0082) for 0.006 less macro-F1. The pre-registered criterion was
kept rather than switched retrospectively.

**Calibration is adequate.** ECE 0.0053, Brier 0.1022, over-confidence +0.0014.
The confidence values shown on the dashboard mean roughly what they say.

**Wearable-only deployment costs real safety margin.** Serving the fully-trained
model against a feed with no oxygen/AVPU observation raises missed-HIGH from
0.0051 to 0.0167 — 3.3×. Retraining for the reduced input set recovers most of
it (0.0109) while barely moving macro-F1, another instance of the aggregate
metric hiding the safety-relevant difference.

**Capacity.** Clean at 10/50/100 req/s (p95 27–31 ms). Saturates between 100 and
250: at an offered 250 req/s the system achieves 159 and p95 rises to 4.4 s.
Analysis backlog still drained fully at every rate.

**Resilience.** With the triage service stopped, ingestion and summarization both
stay at 100% and assessments are recorded with `ml_available=false`; the system
resumes automatically when triage returns, with no backend restart.

## Known gaps

1. **Neither LLM tier has been run live.** Ollama is not installed here and no
   Gemini key is configured. Both tiers are exercised against stubs, including
   the failure and fallback paths, but every summary in every artifact was
   produced by the deterministic tier. The faithfulness guard has therefore
   never rejected real model output — only synthetic fabrications in tests.
2. **Faithfulness checking is necessary, not sufficient.** It catches invented
   numbers and named conditions. It cannot detect a fluent, numerically correct,
   clinically wrong interpretation.
3. **The cost matrix is an assumption.** The 25:5:1 weighting encodes a clinical
   intuition, not outcome data.
4. **The cohort is simulated.** Track B results are software evaluation. No
   claim of clinical validity is made anywhere.
5. **Security is prototype-grade.** Single demo credential, no refresh, no
   revocation, no identity provider, no TLS termination in the stack.

## Reproducing

```bash
./run_all.sh              # everything, ~15 min
./run_all.sh --offline    # skip the Docker stages
./run_all.sh --quick      # smaller cohorts, fast smoke run
```

Track A needs the Kaggle CSV (`fetch_dataset.py` locates and fingerprints it).
Track B is fully synthetic and runs without any external data.
