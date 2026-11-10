import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plotly.express as px
import streamlit as st

import db

st.set_page_config(page_title="Segments · PulseIQ", layout="wide")
st.title("Customer segments (RFM)")
st.caption(
    "Every buyer is scored on Recency (days since last purchase), Frequency (purchase sessions) and "
    "Monetary value (spend), then grouped with k-means. The number of groups is picked by silhouette score."
)
db.require("segments_metrics")

m = db.ml_metrics("segments_metrics")
summary = db.ml("segment_summary")
cats = db.ml("segment_categories")
users = db.ml("user_segments")

c = st.columns(3)
c[0].metric("Buyers", f"{m['buyers']:,}")
c[1].metric("Segments (k)", m["chosen_k"])
c[2].metric("Silhouette score", f"{m['silhouette']:.2f}")

left, right = st.columns(2)
with left:
    st.subheader("Share of buyers vs share of revenue")
    long = summary.melt(id_vars="segment", value_vars=["buyer_share", "revenue_share"], var_name="measure")
    long["measure"] = long.measure.map({"buyer_share": "Buyers", "revenue_share": "Revenue"})
    fig = px.bar(long, x="segment", y="value", color="measure", barmode="group",
                 labels={"value": "Share (%)", "segment": "", "measure": ""})
    fig.update_yaxes(tickformat=".0%")
    fig.update_layout(height=340, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, width="stretch")
with right:
    st.subheader("Silhouette score by k")
    sil = {int(k): v for k, v in m["silhouette_by_k"].items()}
    fig = px.line(x=list(sil), y=list(sil.values()), markers=True, labels={"x": "k (clusters)", "y": "Silhouette"})
    fig.update_layout(height=340, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, width="stretch")

st.subheader("Segment profiles")
top3 = cats.groupby("segment").category_l1.apply(lambda s: ", ".join(s)).rename("top categories")
table = summary.set_index("segment").join(top3).reset_index()
st.dataframe(
    table[["segment", "buyers", "buyer_share", "revenue_share", "avg_recency_days", "avg_frequency",
           "avg_spend", "r_score", "f_score", "m_score", "top categories"]],
    hide_index=True, width="stretch",
    column_config={
        "buyer_share": st.column_config.ProgressColumn("Buyers %", format="%.2f", min_value=0, max_value=1),
        "revenue_share": st.column_config.ProgressColumn("Revenue %", format="%.2f", min_value=0, max_value=1),
        "avg_recency_days": st.column_config.NumberColumn("Days since last buy", format="%.1f"),
        "avg_frequency": st.column_config.NumberColumn("Purchase sessions", format="%.2f"),
        "avg_spend": st.column_config.NumberColumn("Avg spend ($)", format="%.0f"),
        "r_score": st.column_config.NumberColumn("R", format="%.1f"),
        "f_score": st.column_config.NumberColumn("F", format="%.1f"),
        "m_score": st.column_config.NumberColumn("M", format="%.1f"),
    },
)

st.subheader("Buyers on recency and spend")
sample = users.sample(n=min(5000, len(users)), random_state=1)
fig = px.scatter(sample, x="recency_days", y="monetary", color="segment", log_y=True, opacity=0.5,
                 labels={"recency_days": "Days since last purchase", "monetary": "Spend ($, log)"})
fig.update_layout(height=420, margin=dict(l=0, r=0, t=10, b=0))
st.plotly_chart(fig, width="stretch")
st.caption("A random 5,000 buyers.")

with st.expander("Look up a buyer"):
    uid = st.number_input("User ID", min_value=0, step=1, value=int(users.user_id.iloc[0]))
    row = users[users.user_id == uid]
    st.dataframe(row if not row.empty else None, hide_index=True)
