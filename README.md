# PulseIQ

Product analytics and intelligence on the REES46 e-commerce clickstream. It covers funnels, cohort retention,
RFM segments, an A/B test simulator, a recommender, purchase-intent and repeat-purchase models, and a
live stream replay.

Built for the course 23EC2001 Introduction to Data Analytics, Karunya Institute of Technology and Sciences.

## Team

| Name | Register number |
| --- | --- |
| Jibin E S | URK23EC3002 |
| Soumya Vatsyayan | URK23EC6033 |
| Jefris Saju Dani | URK23EC6012 |
| Aben M Philip | URK23EC6001 |

Guided by Dr. P. Malin Bruntha, Department of ECE.

## Requirements

Everything runs in Docker. You only need Docker Desktop and `make`.
On Windows, see [WINDOWS-SETUP.md](WINDOWS-SETUP.md): double-click `setup.bat`, or run `./setup.sh` on Mac/Linux.
The dataset is not stored in git; `make download` or the setup scripts fetch it.

## Quick start

```bash
git clone https://github.com/JibinES/Data_analytics_Third_internal.git
cd Data_analytics_Third_internal
make build                 # build the image
make download              # full October file, 1.74 GB
make all SOURCE=full       # ingest + dbt + all models (about 40 min on a laptop)
make app                   # open http://localhost:8501
```

`make ingest dbt` without `SOURCE=full` runs on a 2M-row dev sample at `data/sample/2019-Oct-sample.csv`
(not in git; take the first 2M rows of the raw file), which is handy for quick changes.
The model jobs use fixed October date windows, so they need the full file.

## What each page shows

| Page | What it answers |
| --- | --- |
| Home | Headline KPIs, events per day, data-quality report |
| Funnel | Where sessions drop off, by category and hour; cart vs no-cart paths |
| Cohorts | Weekly retention heatmap (any activity or purchases) |
| Segments | RFM scores, k-means clusters with persona names |
| A/B test | Significance calculator, plus a labelled simulation on real users |
| Recommender | "Viewed together" recommendations, evaluated against popularity |
| Models | Purchase-intent and repeat-purchase models vs baselines |
| Live | Replays a real day at up to 600× with live intent scores |

## Layout

| Path | What it holds |
| --- | --- |
| `pulseiq/ingest.py` | Raw CSV → cleaned Parquet + data-quality report |
| `pulseiq/segments.py`, `intent.py`, `recs.py`, `repeat.py`, `abtest.py` | Model jobs; write to `data/ml/` and `data/models/` |
| `pulseiq/replay.py` | Stream replay; writes live state to `data/live/` |
| `dbt/` | Star schema (`fact_event`, `dim_*`) and analytics models, with tests |
| `app/` | Streamlit app |
| `tests/` | pytest unit tests |
| `data/` | Raw, cleaned and warehouse files (not in git) |

## Other commands

```bash
make test             # pytest (unit tests + page smoke tests)
make dbt              # rebuild models and run dbt tests only
make ml               # rerun all model jobs
make intent           # or one job: segments, intent, recs, repeat, abtest
make replay-check     # replay a day and compare KPIs with the warehouse
make shell            # bash inside the container
```

## Data source

[eCommerce behavior data from multi category store](https://www.kaggle.com/datasets/mkechinov/ecommerce-behavior-data-from-multi-category-store),
by REES46 Marketing Platform (https://rees46.com).
