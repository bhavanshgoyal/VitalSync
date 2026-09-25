"""Generate every data figure in the paper from the experiment artifacts.

Same rule as the tables: no figure is drawn from numbers typed by hand. Each
plot reads a JSON artifact, so a figure cannot drift from the run that produced
it.

Design constraints, applied throughout:
  * One measure per axis. Never twin y-axes -- two independently chosen ranges
    can manufacture an apparent relationship that is not in the data. Where two
    measures must be compared, they get stacked panels sharing an x-axis.
  * Every series carries a marker and line style as well as a colour, so the
    figures survive greyscale printing and colour-vision deficiency.
  * Recessive grid, no chart junk, no 3-D.

Run::

    python paper/make_figures.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import PercentFormatter  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "ml-service" / "artifacts"
OUT_DIR = Path(__file__).resolve().parent / "figures"

# Categorical slots, fixed order, validated for CVD separation.
BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"

# Reserved status palette -- never reused for a data series.
GOOD = "#0ca30c"
WARNING = "#fab219"
CRITICAL = "#d03b3b"

INK = "#0b0b0b"
MUTED = "#52514e"
GRID = "#d8d7d2"

# IEEE column geometry.
COL_W = 3.45
WIDE_W = 7.16


def style() -> None:
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "Nimbus Roman", "DejaVu Serif"],
        "font.size": 8,
        "axes.titlesize": 8.5,
        "axes.labelsize": 8,
        "legend.fontsize": 7.2,
        "xtick.labelsize": 7.2,
        "ytick.labelsize": 7.2,
        "axes.edgecolor": MUTED,
        "axes.labelcolor": INK,
        "text.color": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "axes.linewidth": 0.6,
        "grid.color": GRID,
        "grid.linewidth": 0.5,
        "figure.dpi": 200,
        "savefig.dpi": 400,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.02,
    })


def tidy(ax, ygrid: bool = True) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    if ygrid:
        ax.yaxis.grid(True, linestyle="-", alpha=0.7)
        ax.set_axisbelow(True)
    ax.xaxis.grid(False)


def load(name: str) -> Optional[Dict]:
    path = ARTIFACTS / name
    if not path.exists():
        print(f"  [skip] {name} not found")
        return None
    return json.loads(path.read_text())


def save(fig, name: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / name
    fig.savefig(out)
    plt.close(fig)
    print(f"  [ok] {name}")


# ---------------------------------------------------------------- Track A

def fig_audit(audit: Dict) -> None:
    """The finding made visual: the vitals carry nothing."""
    rf = audit["milestone_models"]["random_forest"]["accuracy"]
    gb = audit["milestone_models"]["gradient_boosting"]["accuracy"]
    rule = audit["candidate_rule"]["accuracy"]
    abl = audit["ablation_vitals_only"]["accuracy"]
    base = audit["ablation_vitals_only"]["majority_class_baseline"]

    labels = ["Recovered\nrule", "Random\nforest", "Gradient\nboosting",
              "Vitals-only\nablation"]
    values = [rule, rf, gb, abl]
    # Colour by what the bar means, not by rank: the ablation is the finding.
    colours = [MUTED, BLUE, BLUE, CRITICAL]

    fig, ax = plt.subplots(figsize=(COL_W, 2.15))
    bars = ax.bar(labels, values, color=colours, width=0.62, zorder=3)

    ax.axhline(base, color=INK, linestyle="--", linewidth=0.9, zorder=4)
    # Anchored left: at the right edge it collides with the ablation bar label.
    ax.annotate(f"majority-class baseline ({base:.3f})",
                xy=(-0.42, base), xytext=(0, 4), textcoords="offset points",
                ha="left", va="bottom", fontsize=6.4, color=INK)

    for bar, value in zip(bars, values):
        ax.annotate(f"{value:.3f}",
                    xy=(bar.get_x() + bar.get_width() / 2, value),
                    xytext=(0, 2), textcoords="offset points",
                    ha="center", va="bottom", fontsize=6.8, color=INK)

    ax.set_ylabel("Accuracy")
    ax.set_ylim(0, 1.12)
    tidy(ax)
    save(fig, "fig_audit.pdf")


# ---------------------------------------------------------------- Track B

def fig_noise_sweep(bench: Dict) -> None:
    """The central result, with the negative control at sigma = 0 visible."""
    sweep = bench.get("noise_sweep")
    if not sweep:
        return
    model = bench.get("sweep_model", "model")
    cells = sweep["matched_train_test_noise"]

    x = [c["noise_scale"] for c in cells]
    rule = [c["news2_rule_on_observed"]["macro_f1"]["mean"] for c in cells]
    mdl = [c[model]["macro_f1"]["mean"] for c in cells]
    lo = [c[model]["macro_f1"]["ci95_low"] for c in cells]
    hi = [c[model]["macro_f1"]["ci95_high"] for c in cells]
    rlo = [c["news2_rule_on_observed"]["macro_f1"]["ci95_low"] for c in cells]
    rhi = [c["news2_rule_on_observed"]["macro_f1"]["ci95_high"] for c in cells]

    fig, (ax, ax2) = plt.subplots(
        2, 1, figsize=(COL_W, 3.6), sharex=True,
        gridspec_kw={"height_ratios": [2.05, 1], "hspace": 0.16})

    ax.plot(x, rule, color=ORANGE, marker="s", markersize=3.4, linewidth=1.5,
            linestyle="--", label="NEWS2 rule on observed", zorder=3)
    ax.fill_between(x, rlo, rhi, color=ORANGE, alpha=0.16, linewidth=0)

    ax.plot(x, mdl, color=BLUE, marker="o", markersize=3.4, linewidth=1.5,
            linestyle="-", label="Learned model", zorder=4)
    ax.fill_between(x, lo, hi, color=BLUE, alpha=0.16, linewidth=0)

    ax.set_ylabel("Macro-F1")
    ax.legend(loc="upper right", frameon=False, handlelength=2.1)
    tidy(ax)

    # Difference panel: the sign change is the point.
    delta = [c["delta_macro_f1_model_minus_rule"]["mean"] for c in cells]
    dlo = [c["delta_macro_f1_model_minus_rule"]["ci95_low"] for c in cells]
    dhi = [c["delta_macro_f1_model_minus_rule"]["ci95_high"] for c in cells]

    ax2.axhline(0, color=INK, linewidth=0.8, zorder=2)
    ax2.errorbar(x, delta,
                 yerr=[[d - l for d, l in zip(delta, dlo)],
                       [h - d for d, h in zip(delta, dhi)]],
                 color=AQUA, marker="D", markersize=3.2, linewidth=1.4,
                 capsize=2.2, elinewidth=0.9, zorder=3)

    ax2.annotate("model worse", xy=(0.0, delta[0]), xytext=(4, -9),
                 textcoords="offset points", fontsize=6.4, color=CRITICAL)

    ax2.set_xlabel(r"Sensor-noise scale $\sigma$")
    ax2.set_ylabel(r"$\Delta$ Macro-F1")
    tidy(ax2)
    save(fig, "fig_noise_sweep.pdf")


def fig_calibration(metrics: Dict) -> None:
    """Reliability diagram: does a stated confidence mean anything."""
    cal = metrics.get("calibration")
    if not cal:
        return
    bins = [b for b in cal["bins"] if b["count"]]
    centres = [(b["bin_lower"] + b["bin_upper"]) / 2 for b in bins]
    acc = [b["accuracy"] for b in bins]
    counts = [b["count"] for b in bins]
    total = sum(counts)

    fig, (ax, ax2) = plt.subplots(
        2, 1, figsize=(COL_W, 3.1), sharex=True,
        gridspec_kw={"height_ratios": [2.4, 1], "hspace": 0.16})

    ax.plot([0, 1], [0, 1], color=MUTED, linestyle=":", linewidth=1.0,
            label="perfect calibration", zorder=2)
    ax.plot(centres, acc, color=BLUE, marker="o", markersize=3.6,
            linewidth=1.5, label="observed", zorder=3)

    ax.set_ylabel("Observed accuracy")
    ax.set_xlim(0.25, 1.02)
    ax.set_ylim(0.25, 1.02)
    ax.legend(loc="upper left", frameon=False, handlelength=2.1)
    ax.set_title(f"ECE {cal['ece']:.4f}   Brier {cal['brier_score']:.4f}",
                 loc="left", color=MUTED)
    tidy(ax)

    # Support matters: a tiny bin with a big gap is not the same finding.
    ax2.bar(centres, [c / total for c in counts], width=0.085,
            color=AQUA, zorder=3)
    ax2.set_xlabel("Stated confidence")
    ax2.set_ylabel("Share")
    ax2.yaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
    tidy(ax2)
    save(fig, "fig_calibration.pdf")


def fig_wearable(abl: Dict) -> None:
    """Missed-HIGH and HIGH recall across the three deployment configurations.

    Bars are labelled S1/S2/S3 only. Two-line descriptive labels collide at
    single-column width, and the caption is the right place for the prose.
    """
    keys = ["S1_full_observation",
            "S2_trained_full_served_wearable_only",
            "S3_trained_and_served_wearable_only"]
    labels = ["S1", "S2", "S3"]
    missed = [abl["scenarios"][k]["missed_high_rate"] for k in keys]
    recall = [abl["scenarios"][k]["high_recall"] for k in keys]

    # Colour by meaning: S1 is the reported setting, S2 is the hazard, S3 the fix.
    colours = [GOOD, CRITICAL, WARNING]

    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(COL_W, 1.85))

    bars = ax.bar(labels, missed, color=colours, width=0.6, zorder=3)
    for bar, v in zip(bars, missed):
        ax.annotate(f"{v:.4f}", xy=(bar.get_x() + bar.get_width() / 2, v),
                    xytext=(0, 2), textcoords="offset points",
                    ha="center", fontsize=6.4, color=INK)
    ax.set_ylabel("Missed-HIGH rate")
    ax.set_ylim(0, max(missed) * 1.34)
    tidy(ax)

    bars2 = ax2.bar(labels, recall, color=colours, width=0.6, zorder=3)
    for bar, v in zip(bars2, recall):
        ax2.annotate(f"{v:.3f}", xy=(bar.get_x() + bar.get_width() / 2, v),
                     xytext=(0, 2), textcoords="offset points",
                     ha="center", fontsize=6.4, color=INK)
    ax2.set_ylabel("HIGH recall")
    ax2.set_ylim(0, 1.16)
    tidy(ax2)

    fig.subplots_adjust(wspace=0.42)
    save(fig, "fig_wearable.pdf")


# ----------------------------------------------------------------- system

def fig_throughput(tp: Dict) -> None:
    """Offered vs achieved rate, and latency -- stacked, never twin-axis."""
    results = tp["results"]
    offered = [r["target_rate_rps"] for r in results]
    achieved = [r["achieved_rps"] for r in results]
    p50 = [r["ingest_latency_ms"].get("p50") for r in results]
    p95 = [r["ingest_latency_ms"].get("p95") for r in results]

    fig, (ax, ax2) = plt.subplots(
        2, 1, figsize=(COL_W, 3.5), sharex=True,
        gridspec_kw={"height_ratios": [1, 1], "hspace": 0.18})

    ax.plot(offered, offered, color=MUTED, linestyle=":", linewidth=1.0,
            label="ideal (achieved = offered)", zorder=2)
    ax.plot(offered, achieved, color=BLUE, marker="o", markersize=3.6,
            linewidth=1.5, label="achieved", zorder=3)
    ax.set_ylabel("Achieved (req/s)")
    ax.legend(loc="upper left", frameon=False, handlelength=2.1)
    tidy(ax)

    ax2.plot(offered, p50, color=BLUE, marker="o", markersize=3.4,
             linewidth=1.5, linestyle="-", label="p50", zorder=3)
    ax2.plot(offered, p95, color=ORANGE, marker="s", markersize=3.4,
             linewidth=1.5, linestyle="--", label="p95", zorder=4)
    ax2.set_yscale("log")
    ax2.set_xlabel("Offered load (req/s)")
    ax2.set_ylabel("Ingest latency (ms)")
    ax2.legend(loc="upper left", frameon=False, handlelength=2.1)
    tidy(ax2)

    save(fig, "fig_throughput.pdf")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generate paper figures")
    global OUT_DIR
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args(argv)
    OUT_DIR = Path(args.out_dir)
    style()

    audit = load("audit.json")
    metrics = load("metrics.json")
    bench = load("benchmark.json")
    wearable = load("wearable_ablation.json")
    throughput = load("throughput.json")

    if audit:
        fig_audit(audit)
    if bench:
        fig_noise_sweep(bench)
    if metrics:
        fig_calibration(metrics)
    if wearable:
        fig_wearable(wearable)
    if throughput:
        fig_throughput(throughput)

    print(f"\nfigures written to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
