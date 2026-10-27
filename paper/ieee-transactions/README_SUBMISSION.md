# IEEE Transactions submission package

Manuscript: **VitalSync: A Decoupled IoMT Architecture for Risk Triage and
Resilient Clinical Summarization**

Formatted with the IEEE Transactions template bundle supplied for this
assignment: `IEEEtran.cls` **v1.8b (2015/08/26)**, options `[lettersize,journal]`,
per `New_IEEEtran_how-to.pdf`.

Current state: **14 pages**, **37 references**, 10 figures, 7 tables.
`check_manuscript.py` passes.

---

## Before you submit

### 1. Fill the author placeholders

These are the only placeholders left. They are deliberate — they are your
details, not mine to invent:

| Placeholder | Where | What to put |
|---|---|---|
| `[Journal Name]` | `markboth` | the actual target, e.g. *IEEE Journal of Biomedical and Health Informatics* |
| `[Department]`, `[Institution]`, `[City]`, `[Country]`, `[e-mail address]` | `thanks` footnote | your affiliation |

Run `python check_manuscript.py` after editing; it lists any that remain.

### 2. Section X is intentionally empty

"Live Language Model Evaluation" is reserved. No language model has been run, so
every summary reported came from the deterministic tier. The section says this
in its own words, and the Limitations repeats it. Either run the evaluation
(`bench/llm_evaluation.py`), uncomment `\input{tables/table_llm}` and write the
results, or leave it as a declared gap. What you must not do is delete the
section and leave the availability argument resting on untested tiers.

### 3. References: 37 entries, all journals

Every entry is a journal article, a standards document or a dataset. There are
no conference papers, per the submission rule. Each carries authors and at
least one of volume, pages or DOI, and each was checked against the live
literature.

Nine conference papers were replaced to meet that rule: SIGKDD, ICML (two),
IJCAI, ACL, EMNLP, NeurIPS (two) and IEEE CBMS. Their journal substitutes cover
the same claims -- calibration, cost-sensitive learning, gradient boosting,
hallucination, retrieval augmentation, FHIR and ML operations.

One entry is worth a second look: `dean2013` is in *Communications of the ACM*,
which is a magazine rather than a journal. It is peer-reviewed and standard in
its field, but confirm it is acceptable.

The checker enforces the verifiable-entry shape, so a new reference pasted in
without authors and an identifier fails the run rather than reaching a
reviewer.

---

## Files

```
ieee-transactions/
├── vitalsync_transactions.tex   the manuscript
├── vitalsync_transactions.pdf   compiled output, 14 pages
├── IEEEtran.cls                 v1.8b, exactly as supplied
├── figures/
│   ├── fig_audit.pdf            Track A ablation
│   ├── fig_cost_matrix.pdf      asymmetric clinical cost
│   ├── fig_noise_sweep.pdf      macro-F1 vs noise, with CIs
│   ├── fig_confusion.pdf        rule baseline vs selected model
│   ├── fig_per_class.pdf        per-band F1 — where the aggregate hides things
│   ├── fig_missed_high.pdf      missed-HIGH rate across the sweep
│   ├── fig_calibration.pdf      reliability diagram
│   ├── fig_wearable.pdf         sensor-only ablation
│   ├── fig_throughput.pdf       offered vs achieved load
│   ├── fig_events.pdf           notification volume under three policies
│   ├── tikz_design.tex          latent/observed experimental design
│   ├── tikz_architecture.tex    services and the sync/async boundary
│   ├── tikz_sequence.tex        timing of one reading
│   ├── tikz_states.tex          degraded-mode state machine
│   ├── tikz_schema.tex          persistence schema with provenance columns
│   └── tikz_cascade.tex         summarization cascade with the faithfulness gate
├── tables/                      7 tables, generated from experiment artifacts
├── check_manuscript.py          pre-submission checks
└── README_SUBMISSION.md         this file
```

Everything needed to compile is in this directory. References are embedded in
the `.tex` as a `thebibliography` environment, so there is no `.bib` to supply
(the how-to requires a `.bib` only when you use BibTeX).

## Build

```bash
pdflatex vitalsync_transactions
pdflatex vitalsync_transactions
pdflatex vitalsync_transactions
```

Three passes: the first resolves references, the later ones settle float and
biography placement. No BibTeX run.

## Check before submitting

```bash
python check_manuscript.py
```

It verifies that every reference is cited and every citation defined, that all
graphics and `\input` files exist, that no cross-reference dangles, that the
journal front matter is present (class options, running heads, drop cap, index
terms, biography, `thanks`), and that every reference entry is verifiable. It
then reports layout overflow, remaining placeholders and the page count.

The checker strips LaTeX comments first. It did not always: an earlier version
failed on a commented-out `\input` for a table that does not exist yet.

## Where the numbers come from

Tables and figures are generated from the experiment artifacts in
`ml-service/artifacts/` by `../make_tables.py`, `../make_figures.py` and
`../make_figures_extra.py`. No number in the manuscript is typed by hand. If a
result changes, rerun those and recompile — do not edit a table.

The manuscript itself is written directly. The earlier arrangement generated it
from the conference version via `../make_transactions.py`; that stopped once the
journal version grew sections the conference version does not have.

## What changed from the conference version

| | Conference | Transactions (this package) |
|---|---|---|
| Class | `[conference]{IEEEtran}` | `[lettersize,journal]{IEEEtran}` |
| Length | 8 pages | 14 pages |
| References | 19 | 37, each verified |
| Author block | placeholder names | single author with `thanks` footnotes |
| Running heads | none | `markboth{journal info}{author: short title}` |
| Opening | plain paragraph | `IEEEPARstart` drop cap |
| End matter | none | `IEEEbiographynophoto` |
| Added sections | — | Problem Formulation (F1–F5, R1–R6), Faithfulness-Verified Summarization with Algorithm 1, Implementation, Ethics, Reproducibility, Appendices A–C |
| Added figures | — | 6 (cost matrix, confusion, per-class F1, missed-HIGH, sequence, state machine, schema) |
