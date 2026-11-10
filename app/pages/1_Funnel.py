import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plotly.graph_objects as go
import streamlit as st

import db

st.set_page_config(page_title="Funnel · PulseIQ", layout="wide")
st.title("Funnel and drop-off")
st.caption(
    "Counted per session and top-level category. Cart is optional in this dataset: "
    "most buying sessions have no logged cart event, so both paths are shown."
)

if not db.warehouse_ready():
    st.warning("Run `make all` first.")
    st.stop()

bounds = db.query("select min(session_date) d0, max(session_date) d1 from mart_funnel_daily").iloc[0]
categories = db.query("select distinct category_l1 from mart_funnel_daily order by 1").category_l1.tolist()

c1, c2 = st.columns([2, 3])
date_range = c1.date_input("Dates", (bounds.d0, bounds.d1), min_value=bounds.d0, max_value=bounds.d1)
chosen = c2.multiselect("Categories (empty = all)", categories)

if len(date_range) != 2:
    st.stop()
where = f"session_date between '{date_range[0]}' and '{date_range[1]}'"
if chosen:
    quoted = ", ".join("'" + c.replace("'", "''") + "'" for c in chosen)
    where += f" and category_l1 in ({quoted})"

t = db.query(
    f"""
    select sum(viewed) viewed, sum(viewed_carted) carted, sum(viewed_carted_purchased) carted_purchased,
           sum(viewed_purchased_no_cart) purchased_no_cart, sum(purchased) purchased
    from mart_funnel_daily where {where}
    """
).iloc[0]

left, right = st.columns(2)
with left:
    st.subheader("Reached each stage")
    fig = go.Figure(go.Funnel(
        y=["Viewed", "Carted", "Purchased"],
        x=[t.viewed, t.carted, t.purchased],
        textinfo="value+percent initial",
    ))
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=300)
    st.plotly_chart(fig, width="stretch")
with right:
    st.subheader("How buyers got there")
    share_no_cart = t.purchased_no_cart / t.purchased if t.purchased else 0
    st.metric("Purchases with no cart event", f"{share_no_cart:.0%}")
    st.markdown(
        f"""
| Path | Sessions |
| --- | --- |
| View → cart → purchase | {t.carted_purchased:,.0f} |
| View → purchase (no cart) | {t.purchased_no_cart:,.0f} |
| View → cart, no purchase | {t.carted - t.carted_purchased:,.0f} |
"""
    )

st.subheader("Largest drop-off by category")
by_cat = db.query(
    f"""
    select category_l1 as category, sum(viewed) viewed, sum(purchased) purchased,
           100.0 * sum(purchased) / nullif(sum(viewed), 0) as view_to_purchase,
           sum(viewed) - sum(purchased) as lost_sessions, sum(revenue) revenue
    from mart_funnel_daily where {where}
    group by 1 order by lost_sessions desc limit 10
    """
)
st.dataframe(
    by_cat,
    hide_index=True,
    width="stretch",
    column_config={
        "view_to_purchase": st.column_config.NumberColumn("View → purchase", format="%.2f%%"),
        "revenue": st.column_config.NumberColumn("Revenue ($)", format="%.0f"),
    },
)

st.subheader("Conversion by hour of day")
by_hour = db.query(
    f"""
    select start_hour, sum(purchased) / nullif(sum(viewed), 0) as rate
    from mart_funnel_daily where {where} group by 1 order by 1
    """
)
fig = go.Figure(go.Bar(x=by_hour.start_hour, y=by_hour.rate * 100))
fig.update_layout(xaxis_title="Hour (UTC)", yaxis_title="View → purchase (%)", height=300,
                  margin=dict(l=0, r=0, t=10, b=0))
st.plotly_chart(fig, width="stretch")
