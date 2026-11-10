import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import plotly.express as px
import streamlit as st

import db

st.set_page_config(page_title="PulseIQ", layout="wide")
st.title("PulseIQ")
st.caption("Product analytics on the REES46 e-commerce clickstream")

if not db.warehouse_ready():
    st.warning("The warehouse has not been built yet. Run `make all` first.")
    st.stop()

kpi = db.query(
    """
    select
        count(*) as sessions,
        count(distinct user_id) as users,
        sum(events) as events,
        sum(purchases) as purchases,
        sum(revenue) as revenue,
        avg(purchased::int) as session_conversion
    from fct_sessions
    """
).iloc[0]

cols = st.columns(6)
cols[0].metric("Events", f"{kpi.events:,.0f}")
cols[1].metric("Users", f"{kpi.users:,.0f}")
cols[2].metric("Sessions", f"{kpi.sessions:,.0f}")
cols[3].metric("Purchases", f"{kpi.purchases:,.0f}")
cols[4].metric("Revenue", f"${kpi.revenue:,.0f}")
cols[5].metric("Sessions that buy", f"{kpi.session_conversion:.1%}")

daily = db.query(
    """
    select date_key, event_type, count(*) as events
    from fact_event
    group by 1, 2
    order by 1
    """
)
st.subheader("Events per day")
st.plotly_chart(
    px.line(daily, x="date_key", y="events", color="event_type", log_y=True,
            labels={"date_key": "Date", "events": "Events (log scale)", "event_type": "Event type"}),
    width="stretch",
)

report = db.quality_report()
if report:
    st.subheader("Data quality")
    left, right = st.columns(2)
    left.markdown(
        f"""
| Step | Rows |
| --- | --- |
| Raw rows | {report['raw_rows']:,} |
| Dropped: price ≤ 0 | {report['dropped_bad_price']:,} |
| Dropped: missing session | {report['dropped_missing_session']:,} |
| Dropped: duplicates | {report['dropped_duplicates']:,} |
| Clean rows | {report['clean_rows']:,} |
"""
    )
    right.markdown(
        f"""
| Field | Value |
| --- | --- |
| Source | `{report['source']}` |
| Time span | {report['first_event']} → {report['last_event']} |
| Missing category_code | {report['missing_category_code_share']:.1%} |
| Missing brand | {report['missing_brand_share']:.1%} |
| Products | {report['products']:,} |
"""
    )
