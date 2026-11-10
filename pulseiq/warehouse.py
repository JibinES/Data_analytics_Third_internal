"""Connections and output helpers shared by the model jobs."""
import json
from pathlib import Path

import duckdb
import pandas as pd

from pulseiq import config


def connect(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(config.WAREHOUSE), read_only=read_only)
    con.execute(f"SET memory_limit = '{config.MEMORY_LIMIT}'")
    con.execute(f"SET threads = {config.THREADS}")
    con.execute("SET preserve_insertion_order = false")
    return con


def write_parquet(df: pd.DataFrame, name: str) -> Path:
    config.ML_DIR.mkdir(parents=True, exist_ok=True)
    path = config.ML_DIR / f"{name}.parquet"
    tmp = path.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)
    return path


def write_json(obj: dict, name: str) -> Path:
    config.ML_DIR.mkdir(parents=True, exist_ok=True)
    path = config.ML_DIR / f"{name}.json"
    path.write_text(json.dumps(obj, indent=2, default=str))
    return path
