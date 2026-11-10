"""Paths and settings shared by the pipeline, models and app."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW_DIR = DATA / "raw"
SAMPLE_DIR = DATA / "sample"
CLEAN_DIR = DATA / "clean"
WAREHOUSE = DATA / "warehouse" / "pulseiq.duckdb"
REPORTS_DIR = DATA / "reports"
ML_DIR = DATA / "ml"          # model outputs (Parquet / JSON) read by the app
MODELS_DIR = DATA / "models"  # trained model files
LIVE_DIR = DATA / "live"      # stream replay state

# October-only time windows (PRD fallback: November is not downloaded)
INTENT_TRAIN_END = "2019-10-22"   # intent model trains on sessions before this day, tests on and after
RECS_TRAIN_END = "2019-10-25"     # recommender built before this day, evaluated on and after
REPEAT_OBS_END = "2019-10-22"     # repeat-purchase: observe before this day, predict on and after
SEED = 42

SOURCE = os.environ.get("PULSEIQ_SOURCE", "sample")
MEMORY_LIMIT = os.environ.get("PULSEIQ_MEMORY_LIMIT", "2GB")
THREADS = int(os.environ.get("PULSEIQ_THREADS", "4"))


def raw_files() -> list[Path]:
    """Raw event files for the selected source, oldest month first."""
    if SOURCE == "sample":
        files = sorted(SAMPLE_DIR.glob("*.csv"))
    elif SOURCE == "full":
        files = sorted(RAW_DIR.glob("2019-*.csv.gz"))
    else:
        raise ValueError(f"PULSEIQ_SOURCE must be 'sample' or 'full', got {SOURCE!r}")
    if not files:
        raise FileNotFoundError(f"No raw files found for source {SOURCE!r}")
    return files
