import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from pulseiq import config

st.set_page_config(page_title="Live · PulseIQ", layout="wide")
st.title("Live stream replay")
st.caption(
    "Replays one real October day in time order. KPIs update every 2 seconds, and open sessions are "
    "scored by the purchase-intent model as events arrive. Historical tables are never changed."
)

STATE = config.LIVE_DIR / "state.json"
CONTROL = config.LIVE_DIR / "control.json"


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def running(state: dict) -> bool:
    pid = state.get("pid")
    if not pid or state.get("status") in ("done", "stopped"):
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def control(**changes) -> None:
    ctl = read_json(CONTROL) | changes
    CONTROL.write_text(json.dumps(ctl))


if not (config.MODELS_DIR / "intent.txt").exists():
    st.warning("The intent model is missing. Run `make ml` first.")
    st.stop()

state = read_json(STATE)
is_running = running(state)

c1, c2, c3, c4, c5 = st.columns([2, 2, 1, 1, 1])
day = c1.selectbox("Day", [f"2019-10-{d:02d}" for d in range(1, 32)], index=14, disabled=is_running)
speed = c2.select_slider("Speed (× real time)", [60, 120, 300, 600], value=600)
if c3.button("Start", type="primary", disabled=is_running):
    config.LIVE_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [sys.executable, "-m", "pulseiq.replay", "--day", day, "--speed", str(speed)],
        cwd=config.ROOT, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    st.rerun()
paused = state.get("status") == "paused"
if c4.button("Resume" if paused else "Pause", disabled=not is_running):
    control(paused=not paused)
if c5.button("Stop", disabled=not is_running):
    control(stop=True)
if is_running and speed != state.get("speed"):
    control(speed=speed)


@st.fragment(run_every=2)
def live_view():
    s = read_json(STATE)
    if not s:
        st.info("Pick a day and press Start.")
        return
    if s.get("status") == "loading":
        st.info(f"Loading {s['day']}…")
        return
    st.progress(min(s.get("progress", 0), 1.0),
                text=f"{s['status'].capitalize()} · {s['day']} · simulated time {str(s['sim_time'])[11:19]} · {s['speed']:.0f}×")
    k = st.columns(6)
    k[0].metric("Events", f"{s['events']:,}")
    k[1].metric("Sessions", f"{s['sessions']:,}")
    k[2].metric("Open sessions", f"{s['open_sessions']:,}")
    k[3].metric("Purchases", f"{s['purchases']:,}")
    k[4].metric("Revenue", f"${s['revenue']:,.0f}")
    f = s["funnel"]
    k[5].metric("Sessions that buy", f"{f['purchased'] / max(f['viewed'], 1):.1%}")

    left, right = st.columns([3, 2])
    pm_path = config.LIVE_DIR / "per_minute.parquet"
    if pm_path.exists():
        pm = pd.read_parquet(pm_path)
        fig = go.Figure(go.Scatter(x=pm.minute, y=pm.events, mode="lines", name="Events"))
        fig.update_layout(title="Events per minute (last 2 simulated hours)", height=300,
                          margin=dict(l=0, r=0, t=40, b=0), yaxis_title="Events")
        left.plotly_chart(fig, width="stretch")
    fig = go.Figure(go.Funnel(y=["Viewed", "Carted", "Purchased"],
                              x=[f["viewed"], f["carted"], f["purchased"]], textinfo="value+percent initial"))
    fig.update_layout(title="Live funnel (sessions)", height=300, margin=dict(l=0, r=0, t=40, b=0))
    right.plotly_chart(fig, width="stretch")

    top_path = config.LIVE_DIR / "top_sessions.parquet"
    if top_path.exists():
        top = pd.read_parquet(top_path)
        st.subheader("Open sessions most likely to buy")
        if top.empty:
            st.write("No open sessions right now.")
        else:
            st.dataframe(
                top.head(20), hide_index=True, width="stretch",
                column_config={
                    "score": st.column_config.ProgressColumn("Intent", min_value=0, max_value=1, format="%.2f"),
                    "max_price": st.column_config.NumberColumn("Top price ($)", format="%.2f"),
                    "carted": st.column_config.CheckboxColumn("Carted"),
                    "reasons": "Why (top reasons)",
                },
            )


live_view()
