#!/usr/bin/env bash
#
# Reproduce every VitalSync result from a clean checkout.
#
# Offline stages (1-5) need only Python and produce every classification,
# calibration and latency number. Online stages (6-8) additionally need Docker
# and measure the running system.
#
# Usage:
#   ./run_all.sh              full run
#   ./run_all.sh --offline    skip the stages that need Docker
#   ./run_all.sh --quick      smaller cohorts, for a fast smoke run

set -euo pipefail
cd "$(dirname "$0")"

OFFLINE=0
PATIENTS=30000
READINGS=4
SWEEP_PATIENTS=8000
SEEDS=3

for arg in "$@"; do
  case "$arg" in
    --offline) OFFLINE=1 ;;
    --quick)   PATIENTS=6000; READINGS=2; SWEEP_PATIENTS=2500; SEEDS=2 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

step() { printf '\n=== %s ===\n' "$1"; }

step "1/8 environment"
python ml-service/capture_environment.py

step "2/8 dataset provenance (Track A input)"
# Track A needs the Kaggle file; Track B does not. A miss here is not fatal.
python ml-service/fetch_dataset.py || \
  echo "  dataset unavailable -- Track A will be skipped, Track B is unaffected"

step "3/8 Track A: dataset audit"
(cd ml-service && python -m vitalsync_ml.kaggle_audit) || \
  echo "  skipped (dataset unavailable)"

step "4/8 Track B: train and select the triage model"
(cd ml-service && python -m vitalsync_ml.train --patients "$PATIENTS" --readings "$READINGS")

step "5/8 Track B: noise sweep, robustness and latency"
(cd ml-service && python -m vitalsync_ml.evaluate \
    --patients "$SWEEP_PATIENTS" --readings 3 --seeds "$SEEDS")

step "6/8 wearable-only deployment ablation"
(cd ml-service && python -m vitalsync_ml.wearable_ablation --patients "$SWEEP_PATIENTS")

step "7/8 notification event counts"
python bench/alert_compression.py --patients 200 --readings 24

step "8/8 unit tests"
(cd ml-service && python -m pytest tests -q)

if [ "$OFFLINE" -eq 1 ]; then
  echo
  echo "Offline stages complete. Skipping the live-system experiments."
else
  step "live system: bringing up the stack"
  docker compose up -d --build
  echo "waiting for the backend to report healthy ..."
  for _ in $(seq 1 60); do
    if curl -sf http://localhost:8080/actuator/health | grep -q '"status":"UP"'; then
      echo "backend is up"; break
    fi
    sleep 5
  done

  step "live: seeding telemetry"
  python simulator/simulate.py --patients P001,P002,P003 --scenario mixed \
      --count 20 --interval 0.1 --quiet

  step "live: ingestion throughput"
  python bench/throughput.py --rates 10,50,100 --seconds 8

  step "live: resilience under dependency failure"
  python bench/resilience.py
fi

step "generating paper tables and figures"
python paper/make_tables.py
python paper/make_figures.py

echo
echo "Done. Artifacts in ml-service/artifacts/, tables in paper/tables/."
