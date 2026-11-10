"""Read-only access to the warehouse and model outputs for Streamlit pages."""
import json

import duckdb
import pandas as pd
import streamlit as st

from pulseiq import config


@st.cache_data(ttl=600)
def query(sql: str) -> pd.DataFrame:
    # Short-lived read-only connection, so `make all` can rebuild the warehouse while the app runs
    with duckdb.connect(str(config.WAREHOUSE), read_only=True) as con:
        return con.execute(sql).df()


@st.cache_data(ttl=600)
def ml(name: str) -> pd.DataFrame | None:
    """A model output table from data/ml, or None if that job has not run."""
    path = config.ML_DIR / f"{name}.parquet"
    return pd.read_parquet(path) if path.exists() else None


@st.cache_data(ttl=600)
def ml_metrics(name: str) -> dict | None:
    path = config.ML_DIR / f"{name}.json"
    return json.loads(path.read_text()) if path.exists() else None


def quality_report() -> dict | None:
    path = config.REPORTS_DIR / "data_quality.json"
    return json.loads(path.read_text()) if path.exists() else None


def warehouse_ready() -> bool:
    return config.WAREHOUSE.exists()


def require(*names: str) -> None:
    """Stop the page with a hint if the warehouse or a model output is missing."""
    if not warehouse_ready():
        st.warning("The warehouse has not been built yet. Run `make all` first.")
        st.stop()
    missing = [n for n in names if not (config.ML_DIR / f"{n}.json").exists()]
    if missing:
        st.warning(f"Model outputs missing ({', '.join(missing)}). Run `make ml` first.")
        st.stop()
