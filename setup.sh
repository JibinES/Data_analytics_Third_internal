#!/usr/bin/env bash
# PulseIQ setup for macOS, Linux or Git Bash on Windows. Needs Docker Desktop, nothing else.
#
#   ./setup.sh                 use the bundled data (15-20 minutes)
#   ./setup.sh --from-scratch  download the raw dataset and rebuild everything (about 45 minutes)
set -euo pipefail
cd "$(dirname "$0")"

URL=http://localhost:8501
FROM_SCRATCH=0
[ "${1:-}" = "--from-scratch" ] && FROM_SCRATCH=1

step() { printf '\n==> %s\n' "$1"; }
fail() { printf '\n%s\n' "$1" >&2; exit 1; }
compose() { docker compose -f docker-compose.yml -f docker-compose.portable.yml "$@"; }

step "Checking Docker"
command -v docker >/dev/null || fail "Docker Desktop is not installed: https://www.docker.com/products/docker-desktop/"
docker info >/dev/null 2>&1 || fail "Docker Desktop is not running. Start it, then run setup again."

step "Building the PulseIQ image (first time: 5-10 minutes)"
compose build

if [ "$FROM_SCRATCH" = 1 ] || [ ! -f data/clean/events.parquet ]; then
    FROM_SCRATCH=1
    step "Downloading the October 2019 dataset (1.74 GB)"
    compose run --rm pulseiq sh -c "mkdir -p data/raw && curl -fL -o data/raw/2019-Oct.csv.gz https://data.rees46.com/datasets/marketplace/2019-Oct.csv.gz"
    step "Cleaning 42 million events (15-20 minutes)"
    compose run --rm -e PULSEIQ_SOURCE=full pulseiq python -m pulseiq.ingest
else
    step "Copying the bundled data into Docker"
    compose run --rm -v "$(pwd)/data:/seed:ro" pulseiq sh -c "mkdir -p /app/data && cp -rn /seed/. /app/data/"
fi

step "Building the warehouse (about 10 minutes)"
compose run --rm pulseiq sh -c "mkdir -p data/warehouse data/tmp && cd dbt && dbt build"

if [ "$FROM_SCRATCH" = 1 ]; then
    step "Training the models (about 15 minutes)"
    for job in segments intent recs repeat abtest; do
        compose run --rm pulseiq python -m "pulseiq.$job"
    done
fi

step "Starting the app"
compose up -d
for _ in $(seq 60); do
    [ "$(curl -s "$URL/_stcore/health" || true)" = ok ] && break
    sleep 2
done
[ "$(curl -s "$URL/_stcore/health" || true)" = ok ] || fail "The app did not start. Check: docker compose -f docker-compose.yml -f docker-compose.portable.yml logs"

printf '\nPulseIQ is running at %s\n' "$URL"
