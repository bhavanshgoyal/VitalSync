# VitalSync

A decoupled IoMT architecture for vital-sign risk triage and resilient clinical
summarization.

**Research prototype. Not a medical device. Not for clinical use.** Every
output carries that statement. All cohorts are simulated; no real patient data
is used anywhere in this repository.

---

## What this is

Continuous monitoring produces telemetry faster than clinicians can read it.
Language models can summarize it, but they are slow, sometimes unavailable, and
capable of asserting things the data does not support — properties a monitoring
system should not inherit.

VitalSync separates the concerns: ingestion terminates at a durable write, risk
triage is deterministic and millisecond-scale, and generative summarization sits
behind a cascade whose final tier cannot fail. **No language model is required
for the system to work.**

## Three findings

**1. The public dataset this project was built around has a broken label.**
`nasirayub2/human-vital-sign-dataset` labels risk with a deterministic rule:

```
High Risk  ⟺  HR > 90  OR  BMI > 30  OR  BMI < 18.5
```

Exact on all 200,020 rows, zero mismatches. Random forest and gradient boosting
both reach **100.000%** accuracy by recovering that Boolean — not by predicting
anything clinical. A model trained on the remaining vital signs (SpO₂, blood
pressure, temperature, respiratory rate) scores **0.5185** against a
majority-class baseline of **0.5255** — *below chance-level usefulness*. Those
channels carry no label information.

The deployed model therefore does **not** train on this dataset.

**2. A learned model beats a threshold rule only once observations are noisy.**
Ground truth is NEWS2 scored on *latent* physiology; every method — including
the rule baseline — sees only *sensor-corrupted* readings. Macro-F1, 3 seeds,
95% CI on the difference:

| σ | NEWS2 rule | Gradient boosting | Δ | 95% CI |
|---|---|---|---|---|
| 0.0 | 1.0000 | 0.9659 | **−0.0341** | [−0.0381, −0.0300] |
| 1.0 | 0.7976 | 0.8152 | +0.0177 | [+0.0158, +0.0195] |
| 3.0 | 0.5855 | 0.6653 | +0.0798 | [+0.0644, +0.0951] |

At σ=0 the rule *is* the label generator, so the model must lose — and it does.
That negative control is what makes the positive results credible.

**3. Macro-F1 picks the more dangerous model.** Gradient boosting wins on
macro-F1 (0.8324 vs 0.8267) while reporting high-risk observations as low risk
**5.9× more often** (0.0082 vs 0.0014). The pre-registered criterion was kept
and the disagreement reported, rather than switching criteria after seeing
results.

---

## Quick start

```bash
cp .env.example .env          # defaults work; no keys needed
docker compose up -d --build
```

Then:

| | |
|---|---|
| Dashboard | http://localhost:8080/ |
| Backend health | http://localhost:8080/actuator/health |
| Triage service | http://localhost:8000/health |

Credentials are `clinician` / `vitalsync-demo` (override in `.env`).

Drive some telemetry:

```bash
python simulator/simulate.py --patients P001,P002 --scenario mixed --count 20
```

`--scenario` accepts `stable`, `deteriorating`, `recovering`, `septic`, `high`,
`random`, or `mixed` (a different trajectory per patient).

## Reproduce every result

```bash
./run_all.sh              # everything, ~15 min      (run_all.ps1 on Windows)
./run_all.sh --offline    # skip the Docker stages
./run_all.sh --quick      # smaller cohorts, fast smoke run
```

Every experiment writes a JSON artifact to `ml-service/artifacts/`, and every
table in the paper is generated from those artifacts — no number is typed by
hand.

## Enabling a language model tier

Both tiers are off by default and the system is fully functional without them.
To enable, edit `.env`:

```bash
# local
VITALSYNC_OLLAMA_ENABLED=true      # then: ollama pull llama3.1:8b

# or cloud
VITALSYNC_GEMINI_ENABLED=true
GEMINI_API_KEY=your_key_here
```

```bash
docker compose up -d --build
python bench/llm_evaluation.py     # -> artifacts/llm_evaluation.json
python paper/make_tables.py        # -> tables/table_llm.tex
```

That populates Section VII of the paper, which is **currently empty by
design** — see Status below.

---

## Layout

```
VitalSync/
├── ml-service/              Python: NEWS2, cohort generation, training, FastAPI
│   ├── vitalsync_ml/
│   │   ├── news2.py         NEWS2 (RCP 2017) scorer — the clinical labeler
│   │   ├── datagen.py       latent physiology + sensor corruption model
│   │   ├── kaggle_audit.py  Track A: the dataset audit
│   │   ├── train.py         Track B: training, selection, calibration
│   │   ├── evaluate.py      noise sweep with CIs, latency
│   │   ├── metrics.py       clinical cost + calibration metrics
│   │   └── service.py       inference API
│   └── artifacts/           all experiment outputs (JSON)
├── backend/                 Spring Boot 3.5 / Java 21
│   └── .../service/summary/ the cascade + FaithfulnessChecker
├── simulator/               telemetry generator with clinical scenarios
├── bench/                   throughput, resilience, event counts, LLM eval
├── paper/                   IEEE manuscript; tables generated from artifacts
└── docs/
    ├── MASTER_PLAN.md       the authoritative plan
    └── IMPLEMENTATION_STATUS.md   what is verified, and how
```

## Architecture

```
simulator / device
        │  POST /api/v1/telemetry      →  202 Accepted (durable write only)
        ▼
   Spring Boot ──────────────► PostgreSQL 16
        │  bounded executor (async; ingestion never waits)
        ▼
   triage service (FastAPI)  →  band + probabilities + NEWS2 score
        │
        ▼
   summarization cascade:  Ollama → Gemini → deterministic
        │                  (each tier may fail; the last cannot)
        ▼
   faithfulness guard  →  unfaithful output = tier failure, fall through
        │
        ▼
   dashboard (Chart.js)
```

**The decoupling is enforced and tested**: with the triage service stalled for
3 s, ingestion still returns in under 1 s.

**The faithfulness guard** checks that every number in a generated summary
corresponds to a supplied value, and that no condition is named. It is necessary,
not sufficient — it cannot detect a fluent, numerically correct, clinically
wrong reading.

## Measurements

| | |
|---|---|
| Triage latency | mean 2.76 ms, p95 3.72 ms |
| Ingestion | clean to 100 req/s (p95 27–31 ms); saturates ~159 req/s |
| Calibration | ECE 0.0053, Brier 0.1022, over-confidence +0.0014 |
| Resilience | triage stopped → ingest & summaries stay at 100% |
| Tests | 104 Python + 45 Java = **149 passing** |

Timing figures characterize one workstation and are not service-level
objectives.

## Status

Verified by execution, not inspection — see
[docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md).

**Known gap:** no language model tier has been run live. Both are implemented
and exercised against stubs including every failure path, but every summary in
every artifact came from the deterministic tier. The faithfulness guard has
therefore never rejected real model output — only synthetic fabrications in
tests. Section VII of the paper is reserved and empty for this reason.

## Requirements

Docker and Docker Compose for the stack. Python 3.10+ for the ML service and
benchmarks. No local JDK or Maven needed — the backend builds in a container.
Track A additionally needs the Kaggle CSV (`ml-service/fetch_dataset.py` locates
and fingerprints it); Track B needs no external data.

## Licence and data

The audited dataset is not redistributed here; it carries Kaggle's terms.
`fetch_dataset.py` resolves it locally and records its SHA-256 so results can be
tied to a specific file.
