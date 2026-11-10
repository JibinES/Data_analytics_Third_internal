# Every target runs inside the pulseiq Docker container.
# Use SOURCE=full to run on the full raw file instead of the 2M-row sample.
# The model jobs (make ml) use fixed October windows, so they need SOURCE=full data.
SOURCE ?= sample
DAY ?= 2019-10-15
RUN = docker compose run --rm -e PULSEIQ_SOURCE=$(SOURCE) pulseiq

.PHONY: build download ingest dbt ml segments intent recs repeat abtest replay-check test all app shell

build:
	docker compose build

download:
	mkdir -p data/raw
	curl -L -o data/raw/2019-Oct.csv.gz https://data.rees46.com/datasets/marketplace/2019-Oct.csv.gz

ingest:
	$(RUN) python -m pulseiq.ingest

dbt:
	mkdir -p data/warehouse data/tmp
	$(RUN) sh -c "cd dbt && dbt build"

segments:
	$(RUN) python -m pulseiq.segments

intent:
	$(RUN) python -m pulseiq.intent

recs:
	$(RUN) python -m pulseiq.recs

repeat:
	$(RUN) python -m pulseiq.repeat

abtest:
	$(RUN) python -m pulseiq.abtest

ml: segments intent recs repeat abtest

# F9 acceptance: replay one day as fast as possible and compare KPIs with the warehouse
replay-check:
	$(RUN) python -m pulseiq.replay --day $(DAY) --speed 0 --check

test:
	$(RUN) pytest -q

all: ingest dbt ml

app:
	docker compose up pulseiq

shell:
	$(RUN) bash
