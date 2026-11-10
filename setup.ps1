# PulseIQ setup for Windows. Needs Docker Desktop, nothing else.
#
#   Double-click setup.bat, or in PowerShell:  .\setup.ps1
#   .\setup.ps1 -FromScratch   downloads the raw dataset and rebuilds everything (about 45 minutes)

param([switch]$FromScratch)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Url = "http://localhost:8501"

function Step($message) { Write-Host "`n==> $message" -ForegroundColor Cyan }
function Fail($message) { Write-Host "`n$message" -ForegroundColor Red; exit 1 }

function Compose {
    & docker compose -f docker-compose.yml -f docker-compose.portable.yml @args
    if ($LASTEXITCODE -ne 0) { Fail "Step failed: docker compose $args" }
}

Step "Checking Docker"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "Docker Desktop is not installed. Install it from https://www.docker.com/products/docker-desktop/ , start it, then run setup again."
}
cmd /c "docker info >nul 2>&1"
if ($LASTEXITCODE -ne 0) {
    Fail "Docker Desktop is not running. Start it, wait until it shows 'Engine running', then run setup again."
}

Step "Building the PulseIQ image (first time: 5-10 minutes)"
Compose build

$bundled = Test-Path (Join-Path $PSScriptRoot "data\clean\events.parquet")
if ($FromScratch -or -not $bundled) {
    Step "Downloading the October 2019 dataset (1.74 GB)"
    Compose run --rm pulseiq sh -c "mkdir -p data/raw && curl -fL -o data/raw/2019-Oct.csv.gz https://data.rees46.com/datasets/marketplace/2019-Oct.csv.gz"
    Step "Cleaning 42 million events (15-20 minutes)"
    Compose run --rm -e PULSEIQ_SOURCE=full pulseiq python -m pulseiq.ingest
} else {
    Step "Copying the bundled data into Docker"
    $seed = Join-Path $PSScriptRoot "data"
    Compose run --rm -v "${seed}:/seed:ro" pulseiq sh -c "mkdir -p /app/data && cp -rn /seed/. /app/data/"
}

Step "Building the warehouse (about 10 minutes)"
Compose run --rm pulseiq sh -c "mkdir -p data/warehouse data/tmp && cd dbt && dbt build"

if ($FromScratch -or -not $bundled) {
    Step "Training the models (about 15 minutes)"
    foreach ($job in "segments", "intent", "recs", "repeat", "abtest") {
        Compose run --rm pulseiq python -m "pulseiq.$job"
    }
}

Step "Starting the app"
Compose up -d
$ready = $false
for ($i = 0; $i -lt 60 -and -not $ready; $i++) {
    Start-Sleep -Seconds 2
    try { $ready = (Invoke-WebRequest -UseBasicParsing "$Url/_stcore/health" -TimeoutSec 2).Content -eq "ok" } catch {}
}
if (-not $ready) { Fail "The app did not start. Check: docker compose -f docker-compose.yml -f docker-compose.portable.yml logs" }

Write-Host "`nPulseIQ is running at $Url" -ForegroundColor Green
Write-Host "Next time, double-click start.bat. To stop it, double-click stop.bat."
Start-Process $Url
