"""Additional data figures for the extended Transactions manuscript.

Companion to make_figures.py; same palette, same rules. Separated only to keep
each file readable. Everything is read from ml-service/artifacts/, so no number
here is typed by hand.

Run:  python paper/make_figures_extra.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "ml-service" / "artifacts"
OUT = Path(__file__).resolve().parent / "figures"

BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
GOOD, WARNING, CRITICAL = "#0ca30c", "#fab219", "#d03b3b"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#d8d7d2"
COL_W, WIDE_W = 3.45, 7.16


def style() -> None:
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "Nimbus Roman", "DejaVu Serif"],
        "font.size": 8, "axes.titlesize": 8.5, "axes.labelsize": 8,
        "legend.fontsize": 7.2, "xtick.labelsize": 7.2, "ytick.labelsize": 7.2,
        "axes.edgecolor": MUTED, "axes.labelcolor": INK, "text.color": INK,
        "xtick.color": MUTED, "ytick.color": MUTED, "axes.linewidth": 0.6,
        "grid.color": GRID, "grid.linewidth": 0.5,
        "figure.dpi": 200, "savefig.dpi": 400,
        "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
    })


def tidy(ax, ygrid=True):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    if ygrid:
        ax.yaxis.grid(True, linestyle="-", alpha=0.7)
        ax.set_axisbelow(True)
    ax.xaxis.grid(False)


def load(name):
    p = ARTIFACTS / name
    return json.loads(p.read_text()) if p.exists() else None


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / name)
    plt.close(fig)
    print(f"  [ok] {name}")


# ------------------------------------------------------- confusion matrices
def fig_confusion(metrics):
    """Rule baseline against the selected model, row-normalised.

    Row-normalised because the classes are very unbalanced: raw counts would
    make every matrix look like a bright LOW cell and nothing else.
    """
    want = ["news2_rule_on_observed", metrics["selected_model"]]
    rows = [r for name in want for r in metrics["results"] if r["model"] == name]
    labels = rows[0]["confusion_labels"]
    cmap = LinearSegmentedColormap.from_list("blues", ["#ffffff", BLUE])

    fig, axes = plt.subplots(1, 2, figsize=(WIDE_W * 0.70, 2.25))
    for ax, r in zip(axes, rows):
        cm = np.array(r["confusion_matrix"], dtype=float)
        norm = cm / cm.sum(axis=1, keepdims=True)
        ax.imshow(norm, cmap=cmap, vmin=0, vmax=1)
        for i in range(len(labels)):
            for j in range(len(labels)):
                ax.text(j, i, f"{norm[i, j]:.2f}\n({int(cm[i, j]):,})",
                        ha="center", va="center", fontsize=6.0,
                        color="white" if norm[i, j] > 0.55 else INK)
        ax.set_xticks(range(len(labels)), labels, fontsize=7)
        ax.set_yticks(range(len(labels)), labels, fontsize=7)
        ax.set_xlabel("Predicted")
        ax.set_title(r["model"].replace("_", " "), fontsize=7.6, color=MUTED)
        for s in ax.spines.values():
            s.set_visible(False)
    axes[0].set_ylabel("True band")
    fig.subplots_adjust(wspace=0.32)
    save(fig, "fig_confusion.pdf")


# ---------------------------------------------------------- per-class F1
def fig_per_class(metrics):
    """Where the aggregate hides the difference: MEDIUM is the hard class."""
    order = ["news2_rule_on_observed", "threshold_alarms", "logistic_regression",
             "random_forest", "gradient_boosting"]
    rows = [r for name in order for r in metrics["results"] if r["model"] == name]
    bands = ["LOW", "MEDIUM", "HIGH"]
    colours = [GOOD, WARNING, CRITICAL]

    x = np.arange(len(rows))
    width = 0.26
    fig, ax = plt.subplots(figsize=(COL_W, 2.2))
    for k, (band, colour) in enumerate(zip(bands, colours)):
        vals = [r["per_class"][band]["f1-score"] for r in rows]
        ax.bar(x + (k - 1) * width, vals, width, label=band, color=colour, zorder=3)
    ax.set_xticks(x, [r["model"].replace("_", "\n") for r in rows], fontsize=6.0)
    ax.set_ylabel("F1 score")
    ax.set_ylim(0, 1.05)
    ax.legend(frameon=False, ncol=3, fontsize=6.8, loc="upper center",
              bbox_to_anchor=(0.5, 1.16), handlelength=1.2)
    tidy(ax)
    save(fig, "fig_per_class.pdf")


# -------------------------------------------------------------- cost matrix
def fig_cost(metrics):
    """The asymmetric cost assumption, drawn so the asymmetry is obvious.

    Sized to the column at natural scale. An under-sized figure stretched to
    \columnwidth magnifies its own text, which is how the first version ended
    up with 20pt numerals and an annotation outside the axes.
    """
    clin = next(r["clinical"] for r in metrics["results"]
                if r["model"] == metrics["selected_model"])
    C = np.array(clin["cost_matrix"], dtype=float)
    labels = ["LOW", "MEDIUM", "HIGH"]
    cmap = LinearSegmentedColormap.from_list("reds", ["#ffffff", CRITICAL])

    fig, ax = plt.subplots(figsize=(COL_W, 1.75))
    ax.imshow(C, cmap=cmap, vmin=0, vmax=C.max(), aspect="auto")
    for i in range(3):
        for j in range(3):
            ax.text(j, i, f"{C[i, j]:.0f}", ha="center", va="center",
                    fontsize=8, fontweight="bold",
                    color="white" if C[i, j] > C.max() * 0.55 else INK)
    ax.set_xticks(range(3), labels, fontsize=7)
    ax.set_yticks(range(3), labels, fontsize=7)
    ax.set_xlabel("Predicted band", fontsize=7.5)
    ax.set_ylabel("True band", fontsize=7.5)
    for s_ in ax.spines.values():
        s_.set_visible(False)
    # Label the dangerous cell inside the axes; an offset annotation here
    # overflows the column.
    ax.text(0, 2.38, "missed HIGH", ha="center", va="top",
            fontsize=6.2, color=CRITICAL)
    save(fig, "fig_cost_matrix.pdf")


# ------------------------------------------------- missed-HIGH across noise
def fig_missed_high(bench):
    """Safety, not accuracy, across the noise sweep."""
    sweep = bench.get("noise_sweep")
    if not sweep:
        return
    model = bench["sweep_model"]
    cells = sweep["matched_train_test_noise"]
    x = [c["noise_scale"] for c in cells]

    def series(key, metric):
        return [c[key][metric]["mean"] if isinstance(c[key][metric], dict)
                else c[key][metric] for c in cells]

    fig, ax = plt.subplots(figsize=(COL_W, 2.1))
    ax.plot(x, series("news2_rule_on_observed", "missed_high_rate"),
            color=ORANGE, marker="s", markersize=3.4, linewidth=1.5,
            linestyle="--", label="NEWS2 rule on observed")
    ax.plot(x, series(model, "missed_high_rate"),
            color=BLUE, marker="o", markersize=3.4, linewidth=1.5,
            label="Learned model")
    ax.set_xlabel(r"Sensor-noise scale $\sigma$")
    ax.set_ylabel("Missed-HIGH rate")
    ax.legend(frameon=False, loc="upper left", handlelength=2.1)
    tidy(ax)
    save(fig, "fig_missed_high.pdf")


# --------------------------------------------------------- event comparison
def fig_events(events):
    """Notification volume under three policies. Log scale: the span is wide."""
    p = events["policies"]
    keys = ["A_per_parameter_thresholds", "B_aggregate_band", "C_band_transition"]
    labels = ["A\nper-parameter\nthresholds", "B\naggregate\nband", "C\nband\ntransition"]
    vals = [p[k]["events"] for k in keys]

    fig, ax = plt.subplots(figsize=(COL_W, 2.0))
    bars = ax.bar(labels, vals, color=[CRITICAL, WARNING, GOOD], width=0.6, zorder=3)
    for bar, v in zip(bars, vals):
        ax.annotate(f"{v:,}", xy=(bar.get_x() + bar.get_width() / 2, v),
                    xytext=(0, 2), textcoords="offset points",
                    ha="center", fontsize=6.6)
    ax.set_yscale("log")
    ax.set_ylabel("Events (log scale)")
    ax.set_ylim(100, max(vals) * 2.2)
    tidy(ax)
    save(fig, "fig_events.pdf")


def main():
    style()
    metrics = load("metrics.json")
    bench = load("benchmark.json")
    events = load("alert_compression.json")

    if metrics:
        fig_confusion(metrics)
        fig_per_class(metrics)
        fig_cost(metrics)
    if bench:
        fig_missed_high(bench)
    if events:
        fig_events(events)

    print(f"\nextra figures written to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
