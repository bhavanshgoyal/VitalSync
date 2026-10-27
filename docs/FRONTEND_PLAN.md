# VitalSync — Frontend Plan

Date: 2026-10-05
Status: plan, pending build.

---

## 0. What exists, and what this plan does not touch

| Surface | Location | State | This plan |
|---|---|---|---|
| **Project landing page** | `docs/site/` | Built (hero, architecture, findings, demo, results, paper) | **Left alone.** Not my work; no edits planned. |
| **Clinician dashboard** | `backend/src/main/resources/static/` | Deliberately minimal — one view, 3 files, ~28 KB | **Rebuilt.** This is the subject of the plan. |

The landing page sells the project to a reader. The dashboard is the product a
clinician would use. They are different jobs and should not be merged.

### A note on the paper

The manuscript currently says the dashboard is *"deliberately minimal — the
contribution is architectural, and an elaborate UI would invite the reviewer to
evaluate the wrong thing."* That sentence has to change, because it will no
longer be true. The honest revision is that the interface is built to make the
architecture's behaviour **visible** — which tier answered, whether triage was
up, which NEWS2 parameters drove the score — rather than to look impressive.
That is a defensible reason to invest in UI in a systems paper. Section VII of
the paper stays empty regardless; none of this changes a measured result.

---

## 1. Inspiration, and what is actually borrowed

Not "make it look like a SaaS app." Each source contributes one specific idea.

| Source | What it does well | What VitalSync takes |
|---|---|---|
| **Philips IntelliVue / GE CARESCAPE** bedside monitors | Vitals legible across a room: huge numerals, unit subordinate, parameter colour-coded, alarm state unmistakable | Monitor-style value tiles on the patient view. Number dominant, unit small, per-parameter colour constant |
| **Ward whiteboards / Epic patient lists** | One row per patient, sorted by acuity, whole ward scannable in seconds | The Ward Board: default view, sorted by risk, not alphabetically |
| **Grafana / Datadog** | Service health as a first-class view; drill from overview into detail | The System view: cascade tiers, provider mix, faithfulness rate, triage health |
| **Linear / Vercel** | Restrained palette, keyboard-first, instant transitions, dense but calm | Keyboard navigation, no gratuitous motion, muted chrome so data carries the colour |
| **Oura / Whoop** | Direction of travel matters as much as the current value | Trend deltas and sparklines beside every current value |

**Deliberately not borrowed:** consumer-health gamification (streaks, scores,
congratulation states), skeuomorphic gauges, animated waveforms we do not
actually sample, and anything that implies clinical certainty the system does
not have.

---

## 2. Constraints that shape every decision

1. **Zero build step.** No bundler, no `node_modules`, no transpile. Plain
   HTML/CSS/ES modules served straight by Spring Boot. Reason: the repository's
   headline property is reproducibility, and `docker compose up` must stay the
   whole story. A Vite/React frontend would add a build stage to the image, a
   lockfile to audit, and a second toolchain to the tutorial — for a UI of this
   size the trade is not worth it.
2. **Honesty over polish.** Every screen states it is a research prototype.
   Degraded states are shown, never hidden: if triage is down the band reads
   *unavailable*, not `LOW`.
3. **Colour is never the only channel.** Risk bands always carry a glyph and a
   word. Required for the reserved status palette and for colour-vision
   deficiency.
4. **One measure per chart.** No twin y-axes, ever. Heart rate (bpm) and SpO2
   (%) get separate panels.
5. **Accessible by default.** Keyboard reachable, visible focus, ARIA live
   region for risk changes, `prefers-reduced-motion` respected, contrast ≥ 4.5:1
   for text.

---

## 3. Information architecture

Three views, one page, no router library. Hash-based routing (`#/ward`,
`#/patient/P001`, `#/system`) so views are linkable and the back button works.

```
┌─────────────────────────────────────────────────────────────┐
│  VitalSync    [Ward] [System]        ● live    ⟳    ☾/☀     │ top bar
├─────────────────────────────────────────────────────────────┤
│  Research prototype · not a medical device · simulated data  │ persistent
└─────────────────────────────────────────────────────────────┘
```

### 3.1 Ward Board — `#/ward` (default)

The triage question: *who needs attention first?*

* One card per patient, **sorted by risk band then NEWS2 total descending**.
  Never alphabetical — sorting by name is how a deteriorating patient ends up
  below the fold.
* Each card: patient id/name, risk badge (glyph + word + colour), NEWS2 total,
  the four headline vitals, a heart-rate sparkline, time since last reading,
  and which tier wrote the summary.
* **Staleness is shown.** A patient whose last reading is older than the
  expected interval gets a muted "no recent data" state. A monitoring system
  that silently shows old numbers as current is dangerous.
* Click / Enter → patient detail.

### 3.2 Patient Detail — `#/patient/{id}`

The clinical question: *what is happening, and why does the system say so?*

* **Vitals row** — monitor-style tiles: HR, SpO2, BP, temperature, respiratory
  rate, shock index. Large value, small unit, per-parameter colour, trend arrow
  with the delta over the window.
* **Risk panel** — model band + confidence, beside the deterministic NEWS2
  total. Both, always, because one is auditable and the other is not.
* **NEWS2 breakdown** — *new capability*: a per-parameter bar showing which
  parameters contributed which points. This is the single most useful thing the
  UI can add. "NEWS2 = 7" is opaque; "respiratory rate 3, SpO2 2, pulse 2" is
  actionable and checkable by hand.
* **Summary** — three bullets, with the producing tier, its latency, and a
  faithfulness indicator.
* **Trends** — four separate charts (HR, SpO2, BP as two same-unit series, RR).
* **Reading table** — toggleable, the raw numbers, because a clinician should
  always be able to get at them.

### 3.3 System — `#/system`

The engineering question: *is the architecture doing what it claims?*

* Service health: backend, triage service, database.
* Cascade: which tiers are live, how many assessments each answered, mean
  latency per tier.
* Faithfulness pass-rate per provider (reads the data added in V2).
* Degraded-mode counter: assessments recorded with `ml_available = false`.
* Model card: version, selected estimator, macro-F1, ECE, artifact hash.

This view is not decoration. It is the resilience claim, rendered.

---

## 4. Backend work required

The dashboard needs one thing the API does not currently expose.

### 4.1 NEWS2 per-parameter breakdown

The triage service already returns `news2.per_parameter`. The backend drops it:
`MlClient.News2Block` captures only `total`, `band`, `max_single`, and the
column does not exist.

**Plan:**

1. Migration `V3__news2_breakdown.sql` — add `news2_per_parameter JSONB` to
   `risk_assessments`.
2. `MlClient.News2Block` — add `Map<String,Integer> per_parameter`.
3. Persist as JSON; expose on `RiskView`.
4. Tests: round-trip through Postgres; absent breakdown handled (older rows and
   degraded mode both legitimately have none).

**Rejected alternative:** compute NEWS2 in JavaScript from the vitals. That
would create a *third* implementation of the scorer (Python, Java-side display,
JS) with no test coupling between them, and the first time one drifted the UI
would confidently show a score the backend never produced.

### 4.2 Ward roster efficiency

`GET /api/v1/patients` currently issues per-patient queries in a loop
(`countForPatient` + `latestForPatient` per row). Fine for four patients;
wrong shape for a ward board that polls. Replace with a single query joining
latest assessment per patient (`DISTINCT ON`, which is the PostgreSQL-idiomatic
form). Add the sparkline series in one grouped query rather than N requests.

### 4.3 Endpoints added

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/ward` | roster + latest risk + recent HR series, one round trip |
| GET | `/api/v1/system/health` | aggregate service + model health for the System view |

Existing endpoints stay; nothing is removed.

---

## 5. Visual system

### 5.1 Palette

Reuses the validated palette already used for the paper figures, so screen and
print agree.

| Role | Light | Dark |
|---|---|---|
| Series 1 (blue) | `#2a78d6` | `#3987e5` |
| Series 2 (orange) | `#eb6834` | `#d95926` |
| Series 3 (aqua) | `#1baf7a` | `#199e70` |

Reserved status palette, never reused for a data series:

| Band | Colour | Glyph | Word |
|---|---|---|---|
| LOW | `#0ca30c` | ✓ | Low |
| MEDIUM | `#fab219` | ! | Medium |
| HIGH | `#d03b3b` | ⚠ | High |
| UNKNOWN | grey | ? | Unavailable |

Dark mode is **selected, not inverted** — its own steps validated against the
dark surface.

### 5.2 Type and density

* System font stack; no webfont on the dashboard (it must render instantly on a
  ward tablet and must not depend on a CDN that may be blocked).
  *The landing page's use of Inter is fine — different context, different
  constraints.*
* Tabular numerals everywhere a value appears, so digits do not shift as they
  update.
* Three densities of text only: value, label, note. More hierarchy than that
  becomes noise at a glance.

### 5.3 Motion

Transitions ≤ 150 ms, and only on state change. No entrance animations, no
pulsing alarms. `prefers-reduced-motion: reduce` disables all of it. A UI that
animates while a patient is deteriorating is actively hostile.

---

## 6. File layout

```
backend/src/main/resources/static/
├── index.html           shell, three view containers
├── css/
│   ├── tokens.css       colour, type, spacing, light/dark
│   ├── base.css         reset, layout primitives
│   └── components.css   cards, tiles, badges, tables, charts
└── js/
    ├── api.js           fetch wrapper, auth, error normalisation
    ├── state.js         app state, polling, subscriptions
    ├── router.js        hash routing
    ├── charts.js        Chart.js config shared by every chart
    ├── views/
    │   ├── ward.js
    │   ├── patient.js
    │   └── system.js
    └── main.js          bootstrap
```

ES modules, loaded natively. No bundler.

---

## 7. Build order, each stage verified before the next

| # | Stage | Done when |
|---|---|---|
| 1 | Backend: V3 migration + per-parameter plumbing | Java tests green, breakdown visible in `/risk/latest` |
| 2 | Backend: `/ward` and `/system/health` | returns correct shape; roster is one query |
| 3 | Design tokens + shell + routing | three views navigable, theme toggle works |
| 4 | Ward Board | sorted by risk, staleness shown, live polling |
| 5 | Patient Detail + NEWS2 breakdown | breakdown matches the backend total exactly |
| 6 | System view | reflects a real cascade/degraded state |
| 7 | Accessibility + keyboard pass | keyboard-only traversal, contrast checked |
| 8 | Visual verification | screenshots at desktop and phone width, inspected |
| 9 | Docs: DEVLOG + tutorial | written |

---

## 8. Verification

* **Functional:** drive the simulator through stable → deteriorating and watch
  the board reorder; stop the triage container and confirm the UI shows
  *unavailable* rather than a stale or invented band.
* **Visual:** render with a headless browser at 1440px and 400px and actually
  look at the screenshots. The paper figures taught this lesson — seven defects
  were invisible until rendered.
* **Accessibility:** tab through every interactive element; confirm focus is
  visible; check contrast; verify the risk region announces changes.

---

## 9. Explicit non-goals

* No authentication hardening — still one demo credential. The dashboard does
  not make the security posture better and must not imply it does.
* No real-time push (WebSocket/SSE). Polling at a few seconds is adequate at
  this scale and keeps the backend simple. Documented as a scale-out path.
* No mobile-native app.
* No new clinical claims. A nicer interface changes nothing about what the
  system knows.

---

## 10. Deliverables alongside the build

1. **`docs/DEVLOG.md`** — chronological engineering log: what was attempted,
   what broke, the diagnosis, the fix. Including the failures, because the
   failures are where the information is.
2. **`docs/TUTORIAL.md`** — a hands-on walkthrough written for a reader who
   cannot sit still: short steps, one idea each, a visible win early, explicit
   "if this breaks" branches, and real technical depth rather than a tour.
3. **Git stays untouched** — no `init`, no commit, no push. `.gitignore` is
   already in place.
