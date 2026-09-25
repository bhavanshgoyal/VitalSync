"""Experiments E2 and E3: noise sweep, robustness, and inference latency.

E2a (matched)    train and test at the same noise level. Answers: can a learned
                 model internalise a known sensor-noise distribution better than
                 applying the threshold rule to the same corrupted readings?
E2b (mismatched) train once at the reference noise level, test across the sweep.
                 Answers: what happens when deployed noise differs from training
                 noise -- the realistic deployment question.
E3               single-prediction and batch latency distribution.

Run::

    python -m vitalsync_ml.evaluate
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score

from . import MODEL_VERSION
from .datagen import CohortConfig, NoiseConfig, generate_cohort, news2_on_observed
from .features import to_model_matrix
from .news2 import BANDS
from .metrics import clinical_metrics
from .train import build_estimators, split_by_patient, threshold_alarm_baseline

ARTIFACTS = Path(__file__).resolve().parent.parent / "artifacts"

NOISE_LEVELS = [0.0, 0.5, 1.0, 1.5, 2.0, 3.0]


def _score(y_true, y_pred) -> Dict[str, float]:
    clin = clinical_metrics(y_true, y_pred)
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", labels=list(BANDS))),
        "high_recall": clin.get("high_recall"),
        "missed_high_rate": clin.get("missed_high_rate"),
        "mean_cost": clin.get("mean_cost"),
    }


def _aggregate(values: List[float]) -> Dict[str, float]:
    """Mean, sample SD and a normal-approximation 95% interval.

    A single run at one seed cannot distinguish a real effect from seed luck.
    Every sweep cell is therefore repeated across seeds and reported with its
    spread; an interval that straddles zero is reported as straddling zero
    rather than quietly presented as a win.
    """
    clean = [v for v in values if v is not None]
    n = len(clean)
    if n == 0:
        return {}
    mean = statistics.fmean(clean)
    sd = statistics.stdev(clean) if n > 1 else 0.0
    half = 1.96 * sd / math.sqrt(n) if n > 1 else 0.0
    return {
        "mean": mean,
        "sd": sd,
        "n_seeds": n,
        "ci95_low": mean - half,
        "ci95_high": mean + half,
        "values": clean,
    }


def _one_matched_cell(patients, readings, seed, model_name, scale):
    """Train and score one (noise level, seed) cell."""
    cfg = CohortConfig(n_patients=patients, readings_per_patient=readings, seed=seed)
    df = generate_cohort(cfg, NoiseConfig().scaled(scale))
    train_df, test_df = split_by_patient(df, seed)

    X_tr, y_tr = to_model_matrix(train_df), train_df["band_true"].to_numpy()
    X_te, y_te = to_model_matrix(test_df), test_df["band_true"].to_numpy()

    pipe = build_estimators(seed)[model_name]
    pipe.fit(X_tr, y_tr)

    rule = _score(y_te, news2_on_observed(test_df)["band_obs"].to_numpy())
    alarms = _score(y_te, threshold_alarm_baseline(test_df))
    model = _score(y_te, pipe.predict(X_te))
    return rule, alarms, model, pipe


def noise_sweep(patients: int, readings: int, seed: int, model_name: str,
                n_seeds: int = 3) -> Dict:
    """E2a + E2b across NOISE_LEVELS, repeated over independent seeds.

    Each cell is re-run with a different cohort seed so the reported advantage
    carries a spread rather than resting on one draw.
    """
    seeds = [seed + i for i in range(n_seeds)]
    matched: List[Dict] = []
    mismatched: List[Dict] = []
    reference_models = {}

    print(f"   (each cell repeated over {n_seeds} seeds: {seeds})")

    for scale in NOISE_LEVELS:
        rules, alarms, models, deltas = [], [], [], []
        for sd in seeds:
            rule, alarm, model, pipe = _one_matched_cell(
                patients, readings, sd, model_name, scale)
            rules.append(rule)
            alarms.append(alarm)
            models.append(model)
            deltas.append(model["macro_f1"] - rule["macro_f1"])
            if scale == 1.0:
                reference_models[sd] = pipe

        def agg(rows, key):
            return _aggregate([r[key] for r in rows])

        delta_agg = _aggregate(deltas)
        # An interval spanning zero means the advantage is not resolved at this
        # sample size; that is reported rather than smoothed over.
        significant = bool(
            delta_agg.get("ci95_low", 0) > 0 or delta_agg.get("ci95_high", 0) < 0)

        row = {
            "noise_scale": scale,
            "news2_rule_on_observed": {
                k: agg(rules, k)
                for k in ("macro_f1", "accuracy", "high_recall",
                          "missed_high_rate", "mean_cost")
            },
            "threshold_alarms": {k: agg(alarms, k) for k in ("macro_f1", "accuracy")},
            model_name: {
                k: agg(models, k)
                for k in ("macro_f1", "accuracy", "high_recall",
                          "missed_high_rate", "mean_cost")
            },
            "delta_macro_f1_model_minus_rule": delta_agg,
            "delta_excludes_zero": significant,
        }
        matched.append(row)
        print(
            f"   sigma={scale:<4} "
            f"rule={row['news2_rule_on_observed']['macro_f1']['mean']:.4f} "
            f"model={row[model_name]['macro_f1']['mean']:.4f} "
            f"delta={delta_agg['mean']:+.4f} "
            f"[{delta_agg['ci95_low']:+.4f},{delta_agg['ci95_high']:+.4f}] "
            f"{'significant' if significant else 'NOT resolved'}"
        )

    # E2b: models trained at sigma=1.0, evaluated across the sweep on unseen
    # cohorts (seed offset so the test cohorts are not the training ones).
    print("   -- robustness of the sigma=1.0 models across noise levels --")
    for scale in NOISE_LEVELS:
        rule_scores, model_scores, deltas = [], [], []
        for sd in seeds:
            cfg = CohortConfig(
                n_patients=patients, readings_per_patient=readings, seed=sd + 1000)
            df = generate_cohort(cfg, NoiseConfig().scaled(scale))
            _, test_df = split_by_patient(df, sd)
            X_te, y_te = to_model_matrix(test_df), test_df["band_true"].to_numpy()

            rule = _score(y_te, news2_on_observed(test_df)["band_obs"].to_numpy())
            model = _score(y_te, reference_models[sd].predict(X_te))
            rule_scores.append(rule)
            model_scores.append(model)
            deltas.append(model["macro_f1"] - rule["macro_f1"])

        delta_agg = _aggregate(deltas)
        entry = {
            "noise_scale": scale,
            "news2_rule_on_observed": {
                k: _aggregate([r[k] for r in rule_scores])
                for k in ("macro_f1", "missed_high_rate")
            },
            "model_trained_at_sigma_1": {
                k: _aggregate([r[k] for r in model_scores])
                for k in ("macro_f1", "missed_high_rate")
            },
            "delta_macro_f1_model_minus_rule": delta_agg,
            "delta_excludes_zero": bool(
                delta_agg.get("ci95_low", 0) > 0 or delta_agg.get("ci95_high", 0) < 0),
        }
        mismatched.append(entry)
        print(
            f"   sigma={scale:<4} "
            f"rule={entry['news2_rule_on_observed']['macro_f1']['mean']:.4f} "
            f"model={entry['model_trained_at_sigma_1']['macro_f1']['mean']:.4f} "
            f"delta={delta_agg['mean']:+.4f} "
            f"[{delta_agg['ci95_low']:+.4f},{delta_agg['ci95_high']:+.4f}]"
        )

    sanity_mean = matched[0]["news2_rule_on_observed"]["accuracy"]["mean"]
    sanity_ok = abs(sanity_mean - 1.0) < 1e-9
    print(f"   sanity: rule accuracy at sigma=0 is {sanity_mean:.6f} "
          f"-> {'PASS' if sanity_ok else 'FAIL'}")

    return {
        "seeds": seeds,
        "n_seeds": n_seeds,
        "matched_train_test_noise": matched,
        "model_trained_at_sigma_1_tested_across": mismatched,
        "statistics_note": (
            "Each cell is the mean over independent cohort seeds. ci95 is a "
            "normal-approximation interval on that mean. delta_excludes_zero "
            "is false where the model-minus-rule advantage is not resolved at "
            "this number of seeds."
        ),
        "sanity_check": {
            "description": (
                "At noise scale 0 the observation equals the latent signal, so "
                "the NEWS2 rule must reproduce the ground-truth band exactly. "
                "Any value below 1.0 indicates a generator or scorer defect."
            ),
            "rule_accuracy_at_zero_noise": sanity_mean,
            "passed": bool(sanity_ok),
        },
    }


def latency_benchmark(n_single: int = 1000, batch_size: int = 100) -> Dict:
    """E3. Measures the model call only -- not HTTP, serialisation or the network."""
    model_path = ARTIFACTS / "risk_model.joblib"
    if not model_path.exists():
        raise SystemExit("risk_model.joblib missing; run vitalsync_ml.train first")
    pipe = joblib.load(model_path)

    df = generate_cohort(
        CohortConfig(n_patients=max(batch_size, 500), readings_per_patient=1)
    )
    X = to_model_matrix(df)
    one = X.iloc[[0]]

    pipe.predict(one)  # warm up lazily-initialised paths

    singles = np.empty(n_single)
    for i in range(n_single):
        t0 = time.perf_counter()
        pipe.predict(one)
        singles[i] = (time.perf_counter() - t0) * 1000.0

    batch = X.iloc[:batch_size]
    batches = np.empty(50)
    for i in range(50):
        t0 = time.perf_counter()
        pipe.predict(batch)
        batches[i] = (time.perf_counter() - t0) * 1000.0

    return {
        "single_prediction_ms": {
            "n": n_single,
            "mean": float(singles.mean()),
            "p50": float(np.percentile(singles, 50)),
            "p95": float(np.percentile(singles, 95)),
            "p99": float(np.percentile(singles, 99)),
            "max": float(singles.max()),
        },
        "batch_ms": {
            "batch_size": batch_size,
            "n_batches": 50,
            "mean_total": float(batches.mean()),
            "mean_per_row": float(batches.mean() / batch_size),
        },
        "note": (
            "In-process model latency on the benchmark host. Excludes HTTP, "
            "JSON serialisation and network transit. Not a production SLO."
        ),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="VitalSync evaluation experiments")
    ap.add_argument("--patients", type=int, default=12_000)
    ap.add_argument("--readings", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--model", default=None,
        help="estimator for the sweep; defaults to the one selected in training",
    )
    ap.add_argument("--skip-sweep", action="store_true")
    ap.add_argument("--seeds", type=int, default=3,
                    help="independent cohort seeds per sweep cell")
    args = ap.parse_args(argv)

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    model_name = args.model
    if model_name is None:
        metrics_path = ARTIFACTS / "metrics.json"
        model_name = (
            json.loads(metrics_path.read_text())["selected_model"]
            if metrics_path.exists()
            else "random_forest"
        )

    payload: Dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_version": MODEL_VERSION,
        "sweep_model": model_name,
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
    }

    if not args.skip_sweep:
        print(f"[E2] noise sweep using {model_name}")
        payload["noise_sweep"] = noise_sweep(
            args.patients, args.readings, args.seed, model_name, n_seeds=args.seeds
        )

    print("[E3] latency benchmark")
    payload["latency"] = latency_benchmark()
    lat = payload["latency"]["single_prediction_ms"]
    print(f"   mean={lat['mean']:.4f}ms p50={lat['p50']:.4f}ms "
          f"p95={lat['p95']:.4f}ms max={lat['max']:.4f}ms")

    (ARTIFACTS / "benchmark.json").write_text(json.dumps(payload, indent=2))
    print(f"[ok] wrote {ARTIFACTS/'benchmark.json'}")


if __name__ == "__main__":
    main()
