import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plotly.express as px
import streamlit as st

import db

st.set_page_config(page_title="Cohorts · PulseIQ", layout="wide")
st.title("Cohort retention")
st.caption("A cohort is the week of a user's first event. Each cell is the share of that cohort active in a later week.")

if not db.warehouse_ready():
    st.warning("Run `make all` first.")
    st.stop()

measure = st.radio("Count a user as retained when they…", ["had any activity", "made a purchase"], horizontal=True)
col = "active_share" if measure == "had any activity" else "buyer_share"

df = db.query(f"select cohort_week, week_number, cohort_users, {col} as share from mart_cohort_retention order by 1, 2")
if df.empty:
    st.info("No cohort data.")
    st.stop()

grid = df.pivot(index="cohort_week", columns="week_number", values="share")
grid.index = [f"{d:%d %b} ({n:,} users)" for d, n in
              df.drop_duplicates("cohort_week").set_index("cohort_week").cohort_users.items()]

fig = px.imshow(
    grid * 100,
    text_auto=".1f",
    color_continuous_scale="Blues",
    labels={"x": "Weeks since first seen", "y": "Cohort", "color": "% of cohort"},
    aspect="auto",
)
fig.update_layout(height=120 + 40 * len(grid), margin=dict(l=0, r=0, t=10, b=0))
st.plotly_chart(fig, width="stretch")

if len(grid.columns) < 3:
    st.info("This source covers only a few days. Run on the full month (`make all SOURCE=full`) for weekly retention.")
