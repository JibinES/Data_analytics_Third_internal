"""Raw REES46 CSV -> cleaned Parquet + data-quality report.

Cleaning rules (PRD, Dataset section):
- drop exact duplicate rows
- drop rows with price <= 0 or a missing session id
- fill missing category_code and brand with 'unknown'
"""
import json
import time
from pathlib import Path

import duckdb

from pulseiq import config

RAW_COLUMNS = {
    "event_time": "VARCHAR",
    "event_type": "VARCHAR",
    "product_id": "BIGINT",
    "category_id": "BIGINT",
    "category_code": "VARCHAR",
    "brand": "VARCHAR",
    "price": "DOUBLE",
    "user_id": "BIGINT",
    "user_session": "VARCHAR",
}


def connect(memory_limit: str = config.MEMORY_LIMIT, path: str = ":memory:") -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(path)
    con.execute(f"SET memory_limit = '{memory_limit}'")
    con.execute(f"SET temp_directory = '{config.DATA / 'tmp'}'")
    con.execute("SET preserve_insertion_order = false")
    con.execute(f"SET threads = {config.THREADS}")
    return con


def load_raw(con: duckdb.DuckDBPyConnection, files: list[Path]) -> None:
    file_list = ", ".join(f"'{f}'" for f in files)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE raw_events AS
        SELECT * FROM read_csv([{file_list}], header = true, columns = {RAW_COLUMNS})
        """
    )


def clean(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE OR REPLACE TABLE clean_events AS
        SELECT DISTINCT
            strptime(replace(event_time, ' UTC', ''), '%Y-%m-%d %H:%M:%S') AS event_ts,
            event_type,
            product_id,
            category_id,
            coalesce(category_code, 'unknown') AS category_code,
            coalesce(brand, 'unknown') AS brand,
            price,
            user_id,
            user_session
        FROM raw_events
        WHERE price > 0 AND user_session IS NOT NULL
        """
    )


def quality_report(con: duckdb.DuckDBPyConnection) -> dict:
    raw = con.execute(
        """
        SELECT
            count(*) AS rows,
            count(*) FILTER (WHERE price <= 0) AS bad_price,
            count(*) FILTER (WHERE user_session IS NULL) AS missing_session,
            count(*) FILTER (WHERE category_code IS NULL) AS missing_category_code,
            count(*) FILTER (WHERE brand IS NULL) AS missing_brand
        FROM raw_events
        """
    ).fetchone()
    valid = con.execute(
        "SELECT count(*) FROM raw_events WHERE price > 0 AND user_session IS NOT NULL"
    ).fetchone()[0]
    clean_stats = con.execute(
        """
        SELECT count(*), min(event_ts), max(event_ts),
               count(DISTINCT user_id), count(DISTINCT user_session), count(DISTINCT product_id)
        FROM clean_events
        """
    ).fetchone()
    by_type = dict(
        con.execute("SELECT event_type, count(*) FROM clean_events GROUP BY 1 ORDER BY 2 DESC").fetchall()
    )
    return {
        "source": config.SOURCE,
        "raw_rows": raw[0],
        "dropped_bad_price": raw[1],
        "dropped_missing_session": raw[2],
        "dropped_duplicates": valid - clean_stats[0],
        "missing_category_code_share": round(raw[3] / raw[0], 4),
        "missing_brand_share": round(raw[4] / raw[0], 4),
        "clean_rows": clean_stats[0],
        "first_event": str(clean_stats[1]),
        "last_event": str(clean_stats[2]),
        "users": clean_stats[3],
        "sessions": clean_stats[4],
        "products": clean_stats[5],
        "events_by_type": by_type,
    }


def run() -> dict:
    started = time.time()
    files = config.raw_files()
    for d in (config.CLEAN_DIR, config.REPORTS_DIR, config.DATA / "tmp"):
        d.mkdir(parents=True, exist_ok=True)

    # Stage working tables on disk so the full month does not have to fit in memory
    staging = config.DATA / "tmp" / "ingest.duckdb"
    staging.unlink(missing_ok=True)
    con = connect(path=str(staging))
    print(f"Loading {len(files)} file(s): {[f.name for f in files]} "
          f"(memory_limit={config.MEMORY_LIMIT}, threads={config.THREADS})")
    load_raw(con, files)
    print(f"[{time.time() - started:.0f}s] raw loaded")
    clean(con)
    print(f"[{time.time() - started:.0f}s] cleaned")
    report = quality_report(con)
    print(f"[{time.time() - started:.0f}s] report built")

    out = config.CLEAN_DIR / "events.parquet"
    con.execute(f"COPY (SELECT * FROM clean_events ORDER BY event_ts) TO '{out}' (FORMAT parquet, COMPRESSION zstd)")
    con.close()
    staging.unlink(missing_ok=True)
    report["seconds"] = round(time.time() - started, 1)
    (config.REPORTS_DIR / "data_quality.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    run()
