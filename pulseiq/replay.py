"""F9: stream replay. Feeds one real day of events in time order and keeps live KPIs and
purchase-intent scores for open sessions up to date.

State is written as small files in data/live/ (atomic renames), so the Streamlit page can read
them while this process writes, without database locks. Historical tables are never changed.

    python -m pulseiq.replay --day 2019-10-15 --speed 600
    python -m pulseiq.replay --day 2019-10-15 --speed 0 --check   # as fast as possible + compare to batch
"""
import argparse
import json
import os
import time
from datetime import datetime, timedelta

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd

from pulseiq import config, intent, warehouse

TICK_SECONDS = 1.0          # wall-clock time between updates
OPEN_SESSION_MINUTES = 30   # a session with no event for this long counts as closed
TOP_SESSIONS = 50
CONTROL = config.LIVE_DIR / "control.json"
STATE = config.LIVE_DIR / "state.json"


def write_json_atomic(path, obj) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, default=str))
    tmp.replace(path)


def write_parquet_atomic(df: pd.DataFrame, name: str) -> None:
    path = config.LIVE_DIR / f"{name}.parquet"
    tmp = path.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)


def read_control() -> dict:
    try:
        return json.loads(CONTROL.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def load_day(day: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Events for the day, in order, plus each user's history before the day."""
    nxt = (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()
    con = duckdb.connect()
    con.execute(f"SET memory_limit = '{config.MEMORY_LIMIT}'")
    events = con.execute(
        f"""
        SELECT event_ts, event_type, product_id, category_id, price, user_id,
               user_session || ':' || user_id AS session_id
        FROM read_parquet('{config.CLEAN_DIR / "events.parquet"}')
        WHERE event_ts >= '{day}' AND event_ts < '{nxt}'
        ORDER BY {intent.ORDER}
        """
    ).df()
    con.close()
    wh = warehouse.connect()
    wh.register("day_users", events[["user_id"]].drop_duplicates())
    history = wh.execute(
        f"""
        SELECT user_id, count(*) AS hist_sessions, sum(purchased::int) AS hist_purchases
        FROM fct_sessions JOIN day_users USING (user_id)
        WHERE started_at < '{day}'
        GROUP BY user_id
        """
    ).df()
    wh.close()
    return events, history


class Replay:
    def __init__(self, day: str, speed: float):
        self.day, self.speed = day, speed
        self.events, history = load_day(day)
        self.ts = self.events.event_ts.to_numpy()
        self.pos = 0
        self.sim_now = pd.Timestamp(day)
        self.end = self.sim_now + pd.Timedelta(days=1)
        self.con = duckdb.connect()
        self.con.execute(f"SET threads = {config.THREADS}")
        self.con.register("history", history)
        self.con.register("schema_src", self.events.head(0))
        self.con.execute("CREATE TABLE live AS SELECT * FROM schema_src")
        self.model = lgb.Booster(model_file=str(config.MODELS_DIR / "intent.txt"))
        self.max_tick_seconds = 0.0

    def advance(self, sim_seconds: float) -> None:
        self.sim_now = min(self.end, self.sim_now + pd.Timedelta(seconds=sim_seconds))
        new_pos = int(np.searchsorted(self.ts, np.datetime64(self.sim_now), side="left"))
        if self.sim_now >= self.end:
            new_pos = len(self.ts)
        if new_pos > self.pos:
            self.con.register("batch", self.events.iloc[self.pos:new_pos])
            self.con.execute("INSERT INTO live SELECT * FROM batch")
            self.con.unregister("batch")
            self.pos = new_pos

    def kpis(self) -> dict:
        row = self.con.execute(
            """
            SELECT count(*), count(DISTINCT session_id), count(DISTINCT user_id),
                   count(*) FILTER (WHERE event_type = 'purchase'),
                   coalesce(sum(price) FILTER (WHERE event_type = 'purchase'), 0)
            FROM live
            """
        ).fetchone()
        funnel = self.con.execute(
            """
            SELECT count(*) FILTER (WHERE v), count(*) FILTER (WHERE c), count(*) FILTER (WHERE p)
            FROM (SELECT bool_or(event_type = 'view') v, bool_or(event_type = 'cart') c,
                         bool_or(event_type = 'purchase') p FROM live GROUP BY session_id)
            """
        ).fetchone()
        return {
            "events": row[0], "sessions": row[1], "users": row[2], "purchases": row[3], "revenue": row[4],
            "funnel": {"viewed": funnel[0], "carted": funnel[1], "purchased": funnel[2]},
        }

    def score_open_sessions(self) -> tuple[int, pd.DataFrame]:
        cutoff = self.sim_now - pd.Timedelta(minutes=OPEN_SESSION_MINUTES)
        self.con.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE open_s AS
            SELECT session_id, any_value(user_id) AS user_id, count(*) AS events,
                   min(event_ts) AS started_at, max(event_ts) AS last_event
            FROM live GROUP BY session_id
            HAVING max(event_ts) >= '{cutoff}' AND NOT bool_or(event_type = 'purchase')
            """
        )
        n_open = self.con.execute("SELECT count(*) FROM open_s").fetchone()[0]
        if n_open == 0:
            return 0, pd.DataFrame()
        self.con.execute("CREATE OR REPLACE TEMP VIEW ev AS SELECT l.* FROM live l JOIN open_s USING (session_id)")
        self.con.execute(f"CREATE OR REPLACE TEMP TABLE cut AS SELECT session_id, least(events, {intent.MAX_K}) AS k FROM open_s")
        feats = intent.prefix_features(self.con)
        # History = sessions before the day + this user's earlier sessions today
        hist = self.con.execute(
            """
            WITH today AS (
                SELECT session_id, user_id, min(event_ts) AS started_at,
                       bool_or(event_type = 'purchase') AS purchased
                FROM live GROUP BY session_id, user_id
            ),
            ranked AS (
                SELECT session_id, user_id,
                       count(*) OVER w AS prev_today,
                       coalesce(sum(purchased::int) OVER w, 0) AS prev_purchases_today
                FROM today
                WINDOW w AS (PARTITION BY user_id ORDER BY started_at ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
            )
            SELECT o.session_id, o.user_id, o.events, o.last_event,
                   coalesce(h.hist_sessions, 0) + r.prev_today AS prev_sessions,
                   coalesce(h.hist_purchases, 0) + r.prev_purchases_today AS prev_purchases
            FROM open_s o JOIN ranked r USING (session_id) LEFT JOIN history h ON h.user_id = o.user_id
            """
        ).df()
        df = feats.merge(hist, on="session_id")
        x = df[intent.FEATURES]
        df["score"] = self.model.predict(x)
        top = df.nlargest(TOP_SESSIONS, "score").copy()
        top["reasons"] = intent.top_reasons(self.model, top[intent.FEATURES])
        return n_open, top[["session_id", "user_id", "events", "last_event", "max_price", "carted", "score", "reasons"]]

    def per_minute(self) -> pd.DataFrame:
        return self.con.execute(
            """
            SELECT date_trunc('minute', event_ts) AS minute, count(*) AS events,
                   count(*) FILTER (WHERE event_type = 'purchase') AS purchases
            FROM live WHERE event_ts >= (SELECT max(event_ts) - INTERVAL 2 HOUR FROM live)
            GROUP BY 1 ORDER BY 1
            """
        ).df()

    def publish(self, status: str) -> dict:
        t0 = time.time()
        kpi = self.kpis()
        n_open, top = self.score_open_sessions()
        write_parquet_atomic(top, "top_sessions")
        write_parquet_atomic(self.per_minute(), "per_minute")
        state = {
            "status": status, "day": self.day, "speed": self.speed, "sim_time": self.sim_now,
            "progress": self.pos / max(len(self.ts), 1), "open_sessions": n_open, "pid": os.getpid(),
            "max_tick_seconds": round(self.max_tick_seconds, 3), "updated": datetime.now(), **kpi,
        }
        write_json_atomic(STATE, state)
        self.max_tick_seconds = max(self.max_tick_seconds, time.time() - t0)
        return state


def batch_kpis(day: str) -> dict:
    """The same KPIs computed from the warehouse, for the acceptance check."""
    con = warehouse.connect()
    row = con.execute(
        f"""
        SELECT count(*), count(DISTINCT session_id), count(DISTINCT user_id),
               count(*) FILTER (WHERE event_type = 'purchase'),
               coalesce(sum(price) FILTER (WHERE event_type = 'purchase'), 0)
        FROM fact_event WHERE date_key = '{day}'
        """
    ).fetchone()
    con.close()
    return {"events": row[0], "sessions": row[1], "users": row[2], "purchases": row[3], "revenue": row[4]}


def run(day: str, speed: float, check: bool = False) -> dict:
    config.LIVE_DIR.mkdir(parents=True, exist_ok=True)
    write_json_atomic(CONTROL, {"paused": False, "stop": False, "speed": speed})
    write_json_atomic(STATE, {"status": "loading", "day": day, "speed": speed, "pid": os.getpid()})
    started = time.time()
    replay = Replay(day, speed)
    print(f"Loaded {len(replay.ts):,} events for {day} in {time.time() - started:.1f}s")
    state = replay.publish("running")
    wall_start = time.time()

    while replay.pos < len(replay.ts):
        ctl = read_control()
        if ctl.get("stop"):
            return replay.publish("stopped")
        replay.speed = ctl.get("speed", replay.speed)
        if ctl.get("paused"):
            replay.publish("paused")
            time.sleep(TICK_SECONDS)
            continue
        tick_start = time.time()
        if replay.speed <= 0:
            replay.advance(3600)  # as fast as possible: one simulated hour per tick
        else:
            replay.advance(replay.speed * TICK_SECONDS)
        state = replay.publish("running")
        if replay.speed > 0:
            time.sleep(max(0.0, TICK_SECONDS - (time.time() - tick_start)))

    state = replay.publish("done")
    state["wall_seconds"] = round(time.time() - wall_start, 1)
    if check:
        batch = batch_kpis(day)
        live = {k: state[k] for k in batch}
        state["check"] = {
            "batch": batch, "live": live,
            "match": all(np.isclose(live[k], batch[k]) for k in batch),
        }
        print(json.dumps(state["check"], indent=2, default=str))
    write_json_atomic(STATE, state)
    print(f"Replay finished in {state['wall_seconds']}s, slowest update {state['max_tick_seconds']}s")
    return state


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--day", default="2019-10-15")
    p.add_argument("--speed", type=float, default=600, help="simulated seconds per real second; 0 = max")
    p.add_argument("--check", action="store_true", help="compare final KPIs with the warehouse")
    a = p.parse_args()
    state = run(a.day, a.speed, a.check)
    if a.check and not state["check"]["match"]:
        raise SystemExit("Replay KPIs do not match the warehouse")


if __name__ == "__main__":
    main()
