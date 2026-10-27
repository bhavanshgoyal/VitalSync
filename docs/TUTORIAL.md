# VitalSync — The Actual Tutorial

**Read time if you read everything: ~40 min. Time to first working thing: 4 min.**

This is written for a brain that bails on walls of text. So:

- Every section is short and does **one** thing.
- Commands are in boxes. Copy, paste, run, move on.
- **🔴 IF IT BREAKS** boxes are inline, right where it breaks. Not in an appendix.
- **✅ CHECKPOINT** tells you if you're still on the rails.
- You may skip any section marked *(optional depth)*. Nothing later breaks.

You do **not** need to understand the whole system to run it. Run it first.
Understanding is Part 2.

---

# PART 0 — Get something on screen (4 minutes)

## Step 1. Do you have Docker?

```bash
docker --version
```

See a version number? Good. Skip to Step 2.

> **🔴 IF IT BREAKS — "command not found"**
> Install Docker Desktop, open it, wait for the whale icon to stop animating.
> That's it. Come back.
>
> **🔴 IF IT BREAKS — "cannot connect to the Docker daemon"**
> Docker is installed but not *running*. Open Docker Desktop. Wait ~30 seconds.

## Step 2. Start everything

```bash
cd VitalSync
cp .env.example .env
docker compose up -d --build
```

First run takes 3–5 minutes (it's downloading Java, Python, and PostgreSQL).
Go get water. Seriously, don't watch it.

## Step 3. Is it alive?

```bash
docker compose ps
```

You want three lines all saying `healthy`.

> **🔴 IF IT BREAKS — backend says `starting` forever**
> It's waiting on the database. Give it 60 more seconds. Still stuck?
> `docker compose logs backend | tail -30`

## Step 4. 🎉 Open it

**http://localhost:8080**

Log in with `clinician` / `vitalsync-demo` (already filled in — just hit Sign in).

You'll see an empty ward. That's correct. No patients have sent data yet.

## Step 5. Make something happen

New terminal, same folder:

```bash
python simulator/simulate.py --patients P001,P002,P003,P004 --scenario mixed --count 30 --interval 1
```

**Now go look at the browser.** Cards appear. Some go red. The board re-sorts
so the sick ones float to the top.

**✅ CHECKPOINT:** You have a working clinical dashboard with live data.
That's the whole system running. Everything after this is understanding it.

---

# PART 1 — What did I just run?

## The 30-second version

Four things in a line:

```
simulator  →  Spring Boot  →  PostgreSQL
                   ↓
              triage service (Python/ML)
                   ↓
              summary cascade  →  dashboard
```

A fake wearable sends vitals. Java catches them and **immediately** saves them.
Then, *separately*, a Python model scores the risk and something writes a
3-bullet summary.

## The one idea that matters

> **Saving the data and analysing the data are deliberately disconnected.**

Why this is the whole point: the summary step uses an AI language model. Those
are slow (seconds) and sometimes down. The data arriving is fast (milliseconds)
and must never be lost.

If you wired them together, one slow AI call would block incoming patient data.
So we don't. Java saves the reading, says "got it" (`202 Accepted`), and hands
the analysis to a background worker.

**Prove it to yourself later** — there's a test that stalls the AI for 3 seconds
and checks that data ingestion still answers in under 1 second.

---

# PART 2 — Poke it until you understand it

These are quick. Do them in order. Each one teaches one thing.

## Experiment 1 — Make a patient crash

```bash
python simulator/simulate.py --patient-id P001 --scenario deteriorating --count 40 --interval 1
```

Watch P001 in the browser. Heart rate climbs, oxygen drops, the card goes
yellow then red, and it **moves to the front of the board**.

**What you learned:** the board sorts by sickness, not by name. A deteriorating
patient can never hide at the bottom of an alphabetical list.

## Experiment 2 — Find out *why* it said HIGH

Click the red patient. Look at **Score breakdown**.

```
Respiratory rate  ████████  3
SpO₂              ████████  3
Systolic BP       ████████  3
Pulse             ████████  3
Temperature       █████     2
Consciousness               0
```

Add those up. It equals the NEWS2 number next to the badge. Every time.

**What you learned:** the score isn't a black box. It's seven numbers from a
published clinical standard (NEWS2, Royal College of Physicians, 2017), and you
can check the arithmetic by hand. *(That's deliberate — see Part 4.)*

## Experiment 3 — Break the AI on purpose 💥

This is the fun one.

```bash
docker compose stop ml-service
```

Now send more data:

```bash
python simulator/simulate.py --patient-id P002 --count 10 --interval 1
```

Wait ~10 seconds (the backend has to time out waiting for the dead service),
then look. **The data still arrives.** The risk band flips to *unavailable*
instead of guessing. The summaries still appear.

Click **System** in the nav. The "Degraded" counter went up.

Bring it back:

```bash
docker compose start ml-service
```

Within ~30 seconds everything returns to normal. **You didn't restart the
backend.**

**What you learned:** this is the project's main claim, and you just tested it.
The system survives losing its ML service. It degrades honestly — it says
"I don't know" rather than inventing a reassuring `LOW`.

> **🔴 IF IT BREAKS — band stays "unavailable" after restart**
> The container takes ~20s to pass its health check. Wait, then hit refresh (`r`).

## Experiment 4 — Keyboard

Press `1` (ward), `2` (system), `r` (refresh), `Esc` (back from a patient).

**What you learned:** nothing deep. But it's faster and it's nice.

**✅ CHECKPOINT:** You've now seen the architecture's actual behaviour, not a
diagram of it.

---

# PART 3 — The research finding (this is the interesting part)

Stay with me. This is the bit that makes the project more than a CRUD app.

## The setup

The project was supposed to train on a public Kaggle dataset: *Human Vital
Signs*, 200,020 rows. The original notebook did exactly that and got ~99%
accuracy.

**That 99% is meaningless.** Here's why.

## What the audit found

Run it yourself:

```bash
cd ml-service
python -m vitalsync_ml.kaggle_audit
```

The label — the thing the model is supposed to predict — is produced by this:

```
High Risk  ⟺  HR > 90  OR  BMI > 30  OR  BMI < 18.5
```

**Exactly.** All 200,020 rows. Zero exceptions.

## Why that's devastating

Three facts, in increasing order of damage:

**1.** There's no "Normal" class. The dataset is binary. The planned
three-class model was never buildable from it.

**2.** Every vital sign in the dataset is *normal*. Heart rate 60–99. SpO₂
95–100. Temperature 36.0–37.5. There is **not one abnormal reading in 200,000
rows.** It's a dataset of healthy people with a label bolted on.

**3.** The killer: train a model using *only* SpO₂, blood pressure,
temperature, and respiratory rate — no heart rate, no BMI.

```
Accuracy:                  0.5185
Always-guess-majority:     0.5255
```

**It performs worse than guessing.** Those four vital signs contain *zero*
information about the label.

## So what is the 99% measuring?

Memorising a three-line `if` statement. That's it. A decision tree finds it in
about two seconds.

> **If you report that 99% as "my model predicts patient risk from vital
> signs," the first reviewer who runs a decision tree will find this in under a
> minute.** That's not a bad grade, that's a credibility problem.

## The good news

This is a *better* result than a clean 99%. "I audited a popular public dataset
and found its label is a tautology" is a real, checkable, interesting finding.
It's Track A of the paper.

**✅ CHECKPOINT:** You understand why the project has two separate ML tracks.

---

# PART 4 — So what does the real model learn? *(optional depth)*

Skip if you're done. Come back when you need to explain Track B.

## The trap

We can't use the Kaggle label. So we use **NEWS2** — a real clinical scoring
standard.

But here's the trap: **NEWS2 is also just a formula.** Train a model to predict
NEWS2 from clean vitals and you've taught it... a formula you already have.
Circular. Worthless.

## The escape

Split what's *true* from what's *measured*:

```
latent physiology  x*  ──NEWS2──►  y*     ← the truth (nobody sees this)
       │
       ├── sensor noise, dropout, motion artifact
       ▼
observed telemetry x̂   ──────────►  what every model actually sees
```

- **Truth** is scored on the clean signal.
- **Everything** — including the plain NEWS2 rule — only sees the noisy signal.

Real sensors are noisy. A wearable misreads heart rate when you move. A pulse
oximeter reads low on cold fingers. So: *can a learned model see through the
noise better than a fixed threshold rule can?*

## The result

```
σ=0.0   rule 1.0000   model 0.9659   Δ −0.0341   ← model LOSES
σ=1.0   rule 0.7976   model 0.8152   Δ +0.0177
σ=3.0   rule 0.5855   model 0.6653   Δ +0.0798
```

## Why the losing row is the best row

At zero noise, the rule **is** the thing that generated the answer. It must
score 1.0. The model approximating it must do worse.

**It does.** Significantly.

That's the proof the experiment isn't rigged. If the model won everywhere, you
couldn't tell a real result from a leak. A design that *permits* failure and
then doesn't fail is worth something.

As noise grows, the learned model pulls ahead, monotonically, with confidence
intervals that exclude zero.

---

# PART 5 — Run the whole thing yourself

One command regenerates every number in the paper:

```bash
./run_all.sh              # everything, ~15 min
./run_all.sh --offline    # skip Docker stages
./run_all.sh --quick      # small cohorts, fast
```

Windows: `.\run_all.ps1`

Every experiment writes JSON into `ml-service/artifacts/`. Every table and
figure in the paper is **generated from those files** — no number is typed by
hand. Change the data, rerun, the paper updates.

## Run the tests

```bash
cd ml-service && python -m pytest tests -q        # 104 tests
```

Java tests need a container (no JDK required on your machine):

```bash
cd backend
docker run --rm -v "$(pwd):/app" -v vitalsync_m2:/root/.m2 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --add-host=host.docker.internal:host-gateway \
  -e TESTCONTAINERS_HOST_OVERRIDE=host.docker.internal \
  -e TESTCONTAINERS_RYUK_DISABLED=true \
  -w /app maven:3.9-eclipse-temurin-21 mvn test   # 47 tests
```

> **🔴 Windows + Git Bash:** prefix with `MSYS_NO_PATHCONV=1` or Git Bash will
> mangle `/app` into a Windows path and Docker will reject it.

**151 tests total.** They should all pass.

---

# PART 6 — Where everything lives

Only the files you'd actually open:

```
VitalSync/
├── ml-service/vitalsync_ml/
│   ├── news2.py          ← the clinical scorer. Start here.
│   ├── datagen.py        ← latent/observed split (Part 4)
│   ├── kaggle_audit.py   ← the dataset finding (Part 3)
│   ├── train.py          ← trains + picks the model
│   └── service.py        ← the /predict API
│
├── backend/src/main/java/com/vitalsync/
│   ├── service/TelemetryService.java   ← the decoupling lives here
│   └── service/summary/                ← the AI fallback chain
│       └── FaithfulnessChecker.java    ← catches AI hallucinations
│
├── backend/src/main/resources/static/  ← the dashboard
├── paper/                              ← IEEE paper + generators
└── docs/
    ├── MASTER_PLAN.md    ← the plan
    ├── DEVLOG.md         ← every bug and how it got fixed
    └── TUTORIAL.md       ← you are here
```

## The three files worth actually reading

**`news2.py`** — pure functions, no cleverness. Each NEWS2 parameter is one
small function. 104 tests hammer the boundaries.

**`TelemetryService.java`** — find `ingest()` and `analyzeAsync()`. `ingest`
saves and returns. `analyzeAsync` has `@Async`. That one annotation is the
architecture.

**`FaithfulnessChecker.java`** — this one's clever. When an AI writes a
summary, it checks **every number in the text against the numbers it was
given**. Invented a lactate value? Rejected, fall through to the next tier.

> Fun fact from DEVLOG: the first version of this had a bug. Tolerance was
> ±1.0, so a fabricated "lactate 4.7" matched a NEWS2 score of 5 and slipped
> through. A test caught it. Tolerance is now ±0.05.

---

# PART 7 — Turn on a real AI *(optional)*

Right now every summary is written by the **deterministic** tier — a template,
no AI. That's why it works with zero API keys.

Want a real language model?

**Option A — local, free:**

```bash
ollama pull llama3.1:8b
```
Then in `.env`: `VITALSYNC_OLLAMA_ENABLED=true`

**Option B — cloud:**

In `.env`:
```
VITALSYNC_GEMINI_ENABLED=true
GEMINI_API_KEY=your_key_here
```

Then:
```bash
docker compose up -d --build
python bench/llm_evaluation.py
python paper/make_tables.py
```

That fills Section VII of the paper, which is **currently empty on purpose**.

> **Be honest about this in your writeup.** No language model has been run yet.
> The fallback chain is fully tested against fakes, but the hallucination guard
> has never faced a real model. That's stated plainly in the README and the
> paper's Limitations — don't quietly drop it.

---

# PART 8 — Questions you'll get asked

**"Why is your accuracy only 83%? I've seen 99%."**
> Because 99% on that dataset means memorising `HR > 90 OR BMI > 30 OR
> BMI < 18.5`. I audited it and recovered the exact rule. My 83% is against
> noisy sensor data with a published clinical standard as ground truth.

**"Why did your model lose at zero noise?"**
> It should. At zero noise the rule *is* the ground truth. If my model beat it
> there, I'd have a leak. The negative control is what makes the rest credible.

**"Why synthetic data?"**
> Track A uses the real Kaggle dataset — for the audit. It can't train a
> deployable model because it contains no abnormal readings. Track B uses
> simulated data labelled with NEWS2.

**"Is this a medical device?"**
> No, and every screen and API response says so.

**"Why Java *and* Python?"**
> Python has the ML ecosystem. Java handles concurrent ingestion well. Keeping
> them separate is the decoupling — the ML service can die without taking
> ingestion with it. Experiment 3 demonstrates it.

---

# PART 9 — When it breaks

| Symptom | Fix |
|---|---|
| `Cannot connect to the Docker daemon` | Start Docker Desktop |
| Backend stuck `starting` | Wait 60s, then `docker compose logs backend \| tail -30` |
| Dashboard loads but unstyled | Hard refresh (`Ctrl+Shift+R`) |
| `401` on everything | Token expired. Sign out, sign in |
| Simulator: `Connection refused` | Backend isn't up. `docker compose ps` |
| Ward empty | No data yet. Run the simulator |
| Everything is cursed | `docker compose down -v && docker compose up -d --build` ⚠️ wipes the database |

## Full reset

```bash
docker compose down -v
docker compose up -d --build
```

The `-v` deletes the database volume. Fresh start, no patient history.

---

# You're done

You can now:

- run the system
- break it on purpose and watch it survive
- explain why a popular dataset is broken
- explain why a negative result makes the positive ones trustworthy
- regenerate every number in the paper from scratch

**If you only remember three things:**

1. **Ingestion and AI are deliberately disconnected.** That's the architecture.
2. **The Kaggle label is a 3-line rule.** That's the finding.
3. **The model losing at zero noise is a feature.** That's the methodology.

Everything else is detail you can look up.
