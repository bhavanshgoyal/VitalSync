# VitalSync — Engineering Log

A record of what was actually built, what broke, how it was diagnosed, and what
the failure taught. Kept because the failures carry more information than the
successes: anyone can read the finished code, but the dead ends are where the
reasoning lives.

Entries are chronological. Each incident follows the same shape:
**symptom → diagnosis → fix → lesson.**

---

## Phase 0 — Taking stock

**Starting point.** A directory containing three markdown documents, a Jupyter
notebook (`VitalSync_25_Percent_PoC.ipynb`), a compiled PDF, and two helper
scripts. No application code of any kind. A prior summary claimed a complete
implementation existed; it did not — the directory had documents describing one.

**Environment probe.** Python 3.13.14, Docker 29.6.1, Node 24, git. **No JDK,
no Maven, no pdflatex.** That shaped everything downstream: all Java work and
all LaTeX work had to run inside containers.

> **Decision.** Rather than install toolchains, run them containerised:
> `maven:3.9-eclipse-temurin-21` for Java, `texlive/texlive` for the paper.
> Real compilation, real test execution, zero host pollution, and the same
> commands work on a reviewer's machine.

---

## Phase 1 — The dataset audit

### Incident 1 — The dataset was there all along

The previous status document stated the Kaggle dataset "was not supplied" and
that a synthetic fallback had been used instead. A probe of the kagglehub cache
found it sitting on disk:

```
~/.cache/kagglehub/datasets/nasirayub2/human-vital-sign-dataset/versions/1/
    human_vital_signs_dataset_2024.csv     200,020 rows x 17 cols, 37 MB
```

**Lesson.** Check the machine before believing a document about the machine.

### Incident 2 — The label is a rule, not a measurement

First look at class-conditional statistics showed something wrong: for SpO2,
both blood pressures, temperature, respiratory rate and MAP, the two classes
agreed **to three decimal places**. Only heart rate and BMI differed.

Narrowing it down took three queries:

1. `HR > 90` → always High Risk, but only 45,087 of 105,115 High rows.
2. On the remainder, BMI mean was 26.6 vs 24.0 → `BMI > 30` captured more.
3. On what was left, High-risk BMI averaged **16.3** — underweight → `BMI < 18.5`.

```
High Risk  ⟺  HR > 90  OR  BMI > 30  OR  BMI < 18.5
```

Exact across all 200,020 rows. Zero mismatches.

Consequences: the dataset is **binary** (no `Normal` class, so the planned
three-class target was unbuildable), every vital sits inside its normal
reference range (no abnormal observation anywhere in 200k rows), and a
vitals-only ablation scores **0.5185** against a majority baseline of
**0.5255** — *below* always guessing the majority class.

> **This reframed the whole project.** The original plan was to train on this
> data and report accuracy. That number would have been ~100% and would have
> meant nothing. The audit became Track A, a contribution in its own right.

**Lesson.** Audit the label before modelling. A depth-3 tree exposes this in
seconds; the standard train-and-report workflow never asks.

---

## Phase 2 — Building a defensible ML experiment

### The circularity problem

Replacing the Kaggle label with NEWS2 does not fix anything by itself: NEWS2 is
*also* a deterministic function of vitals, so a model trained on clean vitals
would just be approximating a known function.

**Resolution** — separate truth from observation:

```
latent physiology x*  --NEWS2-->  y*   (ground truth, never observed)
        |
        +-- sensor noise, quantisation, dropout
        v
observed telemetry x^  ---------> every model, including the rule baseline
```

This creates a falsifiable claim with a built-in negative control: at zero
noise the rule is exact by construction, so the learned model **must not** win.

### Incident 3 — The sanity check failed, and it was right to

The σ=0 identity check returned **0.9838**, not 1.0.

**Diagnosis.** `_corrupt()` applied display quantisation (`np.round`)
unconditionally — even at zero noise. Rounding 38.04 °C to 38.0 moves it across
a NEWS2 boundary, changing the score.

**Fix.** Quantisation is itself a corruption; it now applies only when
`scale > 0`, making σ=0 an exact passthrough.

```
SANITY sigma=0 rule accuracy: 1.0 -> PASS
```

**Lesson.** The sanity check earned its place on the first run. A test that can
only pass is not a test.

### Incident 4 — scikit-learn moved on

`LogisticRegression.__init__() got an unexpected keyword argument 'multi_class'`
— removed in sklearn ≥ 1.7; multinomial is now the default. One-line fix.

**Lesson.** Pin or probe. Guides written against older versions silently rot.

---

## Phase 3 — The shell kept eating my backslashes

### Incident 5 — Recurring: heredocs mangling content

This cost more time than any single bug, and it recurred in three different
disguises.

| Where | Symptom |
|---|---|
| `datagen.py` | `unexpected EOF while looking for matching ''` — file never written |
| Java repositories | chained heredocs failed mid-way |
| `vitalsync_ieee.tex` | `Table~\ref{...}` became `Table~<CR>ef{...}` |
| TikZ diagrams | `\\$x^{*}$` became `\$x^{*}$`; `\\quantisation` became `\quantisation` |
| `make_tables.py` | every LaTeX command emitted with doubled backslashes |

**Diagnosis.** Passing Python source through a bash heredoc, through the tool
boundary, means two independent layers of escape processing. `\r` is a *known*
Python escape, so `\ref` silently became a carriage return — invisible in a
diff, fatal in LaTeX.

Caught with a byte dump:

```
Table~ = 54 61 62 6c 65 7e   then   0d   <- carriage return, not a backslash
```

**Fix, in order of reliability:**
1. Write files with the file-writer tool, not shell heredocs.
2. For patches, write a `.py` patch file first, then execute it.
3. Where a backslash must be generated, use `chr(92)` and never an escape.

**Lesson.** Any content with backslashes — LaTeX, regex, Windows paths — does
not survive nested shell quoting. Stop fighting it; change tools.

---

## Phase 4 — Backend

### Incident 6 — Test in the wrong package

`init() is not public in JwtService; cannot be accessed from outside package`.
The test sat in `com.vitalsync`, the class in `com.vitalsync.security`.

**Fix.** Moved the test to the matching package rather than widening `init()`
to public. The test should bend to the design, not the reverse.

### Incident 7 — Testcontainers from inside a container

Java tests run in a Maven container but need to start PostgreSQL. Solved with
Docker-outside-of-Docker:

```
-v /var/run/docker.sock:/var/run/docker.sock
--add-host=host.docker.internal:host-gateway
-e TESTCONTAINERS_HOST_OVERRIDE=host.docker.internal
-e TESTCONTAINERS_RYUK_DISABLED=true
```

Containers start as siblings; the override tells Testcontainers how the test
JVM should reach them.

### Incident 8 — The most important test failed, and the test was wrong

`ingestionDoesNotBlockOnASlowMlService` — the test that substantiates the whole
"decoupled" claim — failed. Ingestion took longer than 1500 ms with the ML
service stalled 3 s.

**The temptation** was to assume `@Async` was broken and start changing
executor configuration.

**Actual diagnosis.** The test was measuring the wrong thing:

```java
long start = System.nanoTime();
rest.postForEntity(url, authed(telemetry(...)), String.class);
                        ^^^^^^ this performs an HTTP auth round-trip,
                               inside the timed region
```

`authed()` fetched a JWT, and on first call also paid Spring Security filter
initialisation and JIT warm-up.

**Fix.** Hoist authentication and a warm-up request out of the timed region,
then tighten the bound from 1500 ms to **1000 ms**. Passes comfortably.

> **Lesson, and the most valuable one in this log.** When a test fails, first
> ask whether it measures what it claims. "Fixing" the code here would have
> changed working architecture to satisfy a broken measurement.

### Incident 9 — Resilience experiment reported a false failure

Condition C3 ("triage recovered") reported `ml_available 0%` — apparently the
system did not recover.

**Diagnosis.** `docker compose ps` showed `ml-service: Up 13 seconds` — it came
up *after* the script finished. The readiness poll checked
`localhost:8000/health`, i.e. whether the container was listening from the
*host's* point of view, which is not the question. The question is whether the
**backend** can get a prediction.

**Fix.** `wait_for_ml_recovery()` submits real probe readings until one returns
with `ml_available = true`. C3 then correctly reports 100%.

**Lesson.** Readiness is defined from the consumer's perspective. "The process
is listening" ≠ "the dependency works."

---

## Phase 5 — Metrics that hide things

### Incident 10 — Macro-F1 picked the more dangerous model

Adding asymmetric clinical metrics immediately paid off:

| model | macro-F1 | HIGH recall | missed-HIGH | mean cost |
|---|---|---|---|---|
| random_forest | 0.8267 | 0.9013 | **0.0014** | **0.2074** |
| gradient_boosting | **0.8324** | **0.9199** | 0.0082 | 0.2651 |

Gradient boosting wins on macro-F1 while reporting high-risk observations as
low risk **5.9× more often**. It catches more HIGHs overall, but when it is
wrong it drops them to LOW rather than MEDIUM — the catastrophic direction.

**Decision.** Keep macro-F1 as the *pre-registered* criterion and report the
disagreement as a finding. Switching criteria after seeing results is exactly
the post-hoc selection that makes a number untrustworthy. `--select-by
mean_cost` exists for anyone who wants the other choice.

### Incident 11 — Calibration worry was unfounded, and now it is measured

Live responses showed confidence values of 0.998, which looked like classic
tree-ensemble over-confidence. Measuring it: **ECE 0.0053, over-confidence
+0.0014**. The numbers mean roughly what they say.

**Lesson.** The point was not that the suspicion was right. It was that the
system previously displayed a number nobody had checked.

### Incident 12 — Single-seed results had no error bars

Every sweep number came from one seed. Re-ran across three independent cohort
seeds with 95% intervals; every cell now resolves, and the σ=0 negative result
is significant at **−0.0341 [−0.0381, −0.0300]**.

---

## Phase 6 — Faithfulness

### Incident 13 — The guard let a fabrication through

Test `rejectsAnInventedLabValueNeverSupplied` — a summary inventing "lactate
4.7 mmol/L" — **passed the faithfulness check**.

**Diagnosis.** Absolute tolerance was ±1.0. The NEWS2 total was 5. |4.7 − 5| =
0.3, within tolerance, so the fabricated lab value matched an unrelated score.

**Fix.** Tolerance cut to **0.05**. Legitimate rounding is already handled by
enumerating every rounded form of each source value, so a wide tolerance bought
nothing and cost correctness. Also stripped trailing digits from measurement
names so the "2" in `SpO2` is not read as a claimed value.

**Lesson.** A tolerance tuned for large values is a hole at small ones. ±1 on a
heart rate of 118 is 0.8%; on a score of 5 it is 20%.

### Incident 14 — Java read `\b` as a backspace

`Pattern.compile("(?i)\b(spo|news)2\b")` — written through a shell heredoc, so
one backslash survived. Java reads `"\b"` as backspace, not a word boundary.
Fixed by constructing the string with `chr(92)*2`.

---

## Phase 7 — The paper

Seven defects, **none of which were visible from a successful compile.** They
only appeared after rendering pages to images and looking at them.

| # | Defect | Cause |
|---|---|---|
| 1 | **Fatal, no PDF** | A table row starting `[0.3, 0.4]` parsed as `\\[length]` |
| 2 | "Table eftab:latency" | `\ref` → carriage return (Incident 5) |
| 3 | `a tier\'s` | `\'` is a LaTeX accent command |
| 4 | Labels collided into "full observationilent mismatch" | figure sized wider than the column, squished |
| 5 | Table VII overflowed into the next column | policy descriptions too long |
| 6 | Architecture zone labels overlapped boxes | labels placed on the frame |
| 7 | Section VII cited Section VII as evidence for itself | self-referential `\ref` |

**Lesson.** "It compiles" is not "it is correct." Render it and look at it.
This lesson transferred directly to the frontend and caught two more bugs there.

---

## Phase 8 — Frontend

### Incident 15 — Off-by-one in the SQL insert

Adding the NEWS2 breakdown column broke four integration tests:

```
PSQLException: The column index is out of range: 18, number of columns: 17.
```

**Diagnosis.** I added a column to the `INSERT` list (18) but the placeholder
list still had 17 — and the `::jsonb` cast landed on position 9 when the new
column is position 10.

**Fix.** Corrected to 18 placeholders with the cast in the right slot, plus an
assertion in the patch script that counts columns and placeholders and compares
them. All four tests were the same root cause.

### Incident 16 — The whole UI rendered unstyled

Screenshots came back as bare HTML with console errors:

```
Refused to apply style from '/css/tokens.css' because its MIME type ('')
is not a supported stylesheet MIME type
Failed to load resource: the server responded with a status of 401
```

**Diagnosis.** The MIME error was a symptom, not the cause. I had restructured
flat `app.js`/`styles.css` into `css/` and `js/` directories, but
`SecurityConfig` still whitelisted the **old flat filenames**. Every asset
returned 401; the browser received an error page where CSS should be and
complained about its content type.

**Fix.** Permit `/css/**` and `/js/**`.

**Lesson.** A confusing error at one layer often means a boring error at the one
below. The MIME message sent me looking at content-type configuration; the
actual problem was an auth rule.

### Incident 17 — Breakdown bars rendered empty

The NEWS2 breakdown showed correct point values (3, 3, 2, 3, 3, 0, 2) beside
completely empty bars.

**Diagnosis.** `.bd-fill` is a `<span>`. Inline elements ignore `width` and
`height`, so `style="width:100%"` did nothing.

**Fix.** `display: block` on both the track and the fill, plus `min-width: 2px`
so a 1-point bar is visible — and explicitly `min-width: 0` at zero points, so
"no contribution" does not render as a sliver that reads as a little bit of risk.

**Lesson.** Same as the paper: screenshots catch what compilation cannot. The
data was right, the API was right, the CSS was wrong, and only looking revealed it.

---

### Incident 18 — Thirteen references could not be resolved

The draft bibliography had 19 entries. Thirteen of them carried a title, a
venue and a year, and nothing else: no authors, no volume, no pages, no DOI.

**Diagnosis.** Two were spot-checked against the live literature. "MealMeter"
exists but under a different title *and* a different venue than cited. "Dynamic
Resource Allocation for Federated Large Language Models in the Internet of
Medical Things" returned nothing at all. The pattern was clear enough that the
remaining eleven did not need individual disproof — an entry with no author and
no identifier is not a citation, it is a description of a paper that might exist.

**Fix.** All thirteen were replaced with web-verified sources, and the
bibliography grew to 37 entries, each with authors and at least one of volume,
pages or DOI. `check_manuscript.py` now fails the build on any entry missing
both an author and an identifier, so this cannot recur silently.

**Lesson.** A citation that cannot be resolved is not a formatting problem. It
is the kind of thing that ends a submission, and the check for it is mechanical
enough to automate — so automate it rather than trusting a proofread.

---

### Incident 19 — Guessed three times at a 61.7pt overfull box

The manuscript reported one overfull hbox of 61.7pt — far past the 20pt
threshold the checker allows. The first three fixes were aimed at the cost
matrix, then the schema diagram, then the sequence diagram. After each one the
box came back at *exactly* 61.7pt.

**Diagnosis.** An unchanged number is information. Three edits that moved
nothing meant none of them had touched the cause. Reading the log properly —
rather than inferring from which figure looked widest — put the warning
immediately after `tikz_states.tex` loaded. That diagram placed two 30mm state
boxes with a 34mm gap between them: about 94mm of content in an ~88mm column.

**Fix.** Stack the two states vertically, with the transition arrows running
between them. The comment at the top of the file now says why, so the next
person to open it does not "improve" it back into the margin.

**Lesson.** Identical symptoms after a fix mean the fix was irrelevant, not
insufficient. Read the log before editing anything. Three wrong guesses cost
more than one careful read would have.

---

## Cross-cutting lessons

1. **Audit inputs before modelling them.** The largest finding in this project
   came from thirty minutes of looking at a CSV.
2. **A test that cannot fail proves nothing.** The σ=0 control and the stalled-
   dependency test both earned their keep by failing first.
3. **When a test fails, check the test.** Incidents 8 and 9 were both broken
   measurements, not broken systems.
4. **Render it and look at it.** Nine defects across the paper and the frontend
   were invisible to compilers and test suites.
5. **Aggregate metrics hide directional error.** Macro-F1 chose the more
   dangerous model twice, under different circumstances.
6. **Don't nest escaping layers.** Write files directly.
7. **An unchanged symptom means the fix was irrelevant.** Not insufficient —
   irrelevant. Read the diagnostic output before editing anything else.
8. **Report the unmeasured thing as unmeasured.** No language model has run
   live; that is stated in the README, the status doc, and the paper rather
   than quietly omitted.

---

## Current state

| | |
|---|---|
| Tests | **151 passing** — 104 Python, 47 Java |
| Services | backend, triage, PostgreSQL — all healthy |
| Migrations | V1 init, V2 faithfulness, V3 NEWS2 breakdown |
| Paper | 7 pages, 7 tables, 8 figures, all generated from artifacts |
| Frontend | 3 views, zero build step, verified at 1440px and 390px |
| Known gap | **No LLM tier has been run live.** Section VII of the paper is reserved and empty. |
