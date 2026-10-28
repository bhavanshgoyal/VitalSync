# Start VitalSync: Docker Desktop, Ollama (models on D:), then the stack.
# Usage:  .\start_vitalsync.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "[1/3] Docker Desktop ..." -ForegroundColor Cyan
if (-not (docker info 2>$null)) {
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    $n = 0
    while (-not (docker info 2>$null)) {
        Start-Sleep -Seconds 3; $n++
        if ($n -gt 40) { throw "Docker engine did not start within 2 minutes." }
    }
}
Write-Host "      engine ready" -ForegroundColor Green

function Get-OllamaModels {
    try { return (Invoke-RestMethod "http://localhost:11434/api/tags" -TimeoutSec 4).models.name }
    catch { return $null }
}

Write-Host "[2/3] Ollama ..." -ForegroundColor Cyan

# A server already serving the model is left alone. Only a missing or
# model-blind instance is replaced: the tray app Windows auto-starts ignores
# OLLAMA_MODELS and looks in C:\Users\<you>\.ollama, where the model is not.
$models = Get-OllamaModels
if ($models) {
    Write-Host "      already serving: $($models -join ', ')" -ForegroundColor Green
} else {
    Get-Process ollama,'ollama app' -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 3
    $env:OLLAMA_MODELS     = "D:\OllamaModels"
    $env:OLLAMA_KEEP_ALIVE = "-1"
    Start-Process "D:\Ollama\ollama.exe" -ArgumentList "serve" -WindowStyle Hidden

    # First boot scans the model directory on D: and can take well over a
    # minute, so this waits generously rather than failing early.
    $n = 0
    do {
        Start-Sleep -Seconds 3; $n++
        $models = Get-OllamaModels
        if (-not $models -and ($n % 10 -eq 0)) {
            Write-Host "      still waiting ($($n * 3)s) ..." -ForegroundColor DarkGray
        }
    } while (-not $models -and $n -lt 60)

    if (-not $models) {
        throw "Ollama did not report any model within 3 minutes. Check that D:\OllamaModels exists and OLLAMA_MODELS points at it."
    }
    Write-Host "      serving: $($models -join ', ')" -ForegroundColor Green
}

Write-Host "[3/3] Stack ..." -ForegroundColor Cyan
Push-Location $root
docker compose up -d | Out-Null
Pop-Location

$n = 0
do {
    Start-Sleep -Seconds 3; $n++
    $health = try { (Invoke-RestMethod "http://localhost:8080/actuator/health" -TimeoutSec 3).status } catch { $null }
} while ($health -ne "UP" -and $n -lt 30)
if ($health -ne "UP") { throw "Backend did not become healthy. Try: docker compose logs backend" }

Write-Host "      backend UP" -ForegroundColor Green
Write-Host ""
Write-Host "  Dashboard : http://localhost:8080/" -ForegroundColor Yellow
Write-Host "  Login     : clinician / vitalsync-demo" -ForegroundColor Yellow
Write-Host ""
Start-Process "http://localhost:8080/"
