# Reproduce every VitalSync result from a clean checkout (Windows).
#
# Offline stages (1-8) need only Python and produce every classification,
# calibration and latency number. The live stages additionally need Docker.
#
# Usage:
#   .\run_all.ps1              full run
#   .\run_all.ps1 -Offline     skip the stages that need Docker
#   .\run_all.ps1 -Quick       smaller cohorts, for a fast smoke run

param(
    [switch]$Offline,
    [switch]$Quick
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$Patients = 30000
$Readings = 4
$SweepPatients = 8000
$Seeds = 3

if ($Quick) {
    $Patients = 6000
    $Readings = 2
    $SweepPatients = 2500
    $Seeds = 2
}

function Step($message) {
    Write-Host ""
    Write-Host "=== $message ===" -ForegroundColor Cyan
}

Step "1/8 environment"
python ml-service/capture_environment.py

Step "2/8 dataset provenance (Track A input)"
# Track A needs the Kaggle file; Track B does not. A miss here is not fatal.
try { python ml-service/fetch_dataset.py }
catch { Write-Host "  dataset unavailable -- Track A will be skipped, Track B is unaffected" }

Step "3/8 Track A: dataset audit"
Push-Location ml-service
try { python -m vitalsync_ml.kaggle_audit }
catch { Write-Host "  skipped (dataset unavailable)" }
Pop-Location

Step "4/8 Track B: train and select the triage model"
Push-Location ml-service
python -m vitalsync_ml.train --patients $Patients --readings $Readings
Pop-Location

Step "5/8 Track B: noise sweep, robustness and latency"
Push-Location ml-service
python -m vitalsync_ml.evaluate --patients $SweepPatients --readings 3 --seeds $Seeds
Pop-Location

Step "6/8 wearable-only deployment ablation"
Push-Location ml-service
python -m vitalsync_ml.wearable_ablation --patients $SweepPatients
Pop-Location

Step "7/8 notification event counts"
python bench/alert_compression.py --patients 200 --readings 24

Step "8/8 unit tests"
Push-Location ml-service
python -m pytest tests -q
Pop-Location

if ($Offline) {
    Write-Host ""
    Write-Host "Offline stages complete. Skipping the live-system experiments."
} else {
    Step "live system: bringing up the stack"
    docker compose up -d --build

    Write-Host "waiting for the backend to report healthy ..."
    foreach ($i in 1..60) {
        try {
            $health = Invoke-RestMethod -Uri 'http://localhost:8080/actuator/health' -TimeoutSec 5
            if ($health.status -eq 'UP') { Write-Host "backend is up"; break }
        } catch { }
        Start-Sleep -Seconds 5
    }

    Step "live: seeding telemetry"
    python simulator/simulate.py --patients P001,P002,P003 --scenario mixed --count 20 --interval 0.1 --quiet

    Step "live: ingestion throughput"
    python bench/throughput.py --rates 10,50,100 --seconds 8

    Step "live: resilience under dependency failure"
    python bench/resilience.py
}

Step "generating paper tables and figures"
python paper/make_tables.py
python paper/make_figures.py

Write-Host ""
Write-Host "Done. Artifacts in ml-service/artifacts/, tables in paper/tables/."
