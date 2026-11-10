import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

import db

st.set_page_config(page_title="Recommender · PulseIQ", layout="wide")
st.title("Product recommender")
st.caption(
    "Co-occurrence: products viewed in the same session, scored by cosine similarity. "
    "Popularity: most-purchased products in the same category (the baseline). "
    "Hybrid: co-occurrence, topped up with popularity when it has fewer than 10 items."
)
db.require("recs_metrics")

m = db.ml_metrics("recs_metrics")
evaluation = db.ml("recs_eval")
cooc = db.ml("recs_cooc")
popular = db.ml("recs_popular")

st.subheader("Offline evaluation")
st.write(
    f"Built on events {m['train_window']}; tested on {m['test_window']}. For each of "
    f"{m['evaluated_users']:,} users, the query is the last product they viewed before the cut-off, "
    "and a hit is any other product they later carted or bought."
)
st.dataframe(
    evaluation, hide_index=True, width="stretch",
    column_config={
        "users": st.column_config.NumberColumn("Users", format="%d"),
        "hit_rate_at_10": st.column_config.NumberColumn("HitRate@10", format="%.4f"),
        "precision_at_10": st.column_config.NumberColumn("Precision@10", format="%.4f"),
        "coverage": st.column_config.NumberColumn("Catalogue coverage", format="%.3f"),
    },
)

st.subheader("Try it")
examples = cooc.groupby("product_id").sessions_together.sum().nlargest(20).index.tolist()
c1, c2 = st.columns([1, 2])
pick = c1.selectbox("Popular product IDs", examples)
typed = c2.text_input("…or type a product ID", "")
pid = int(typed) if typed.strip().isdigit() else int(pick)

info = db.query(f"select category_code, brand, round(avg_price, 2) as avg_price from dim_product where product_id = {pid}")
if info.empty:
    st.warning("Unknown product ID.")
    st.stop()
st.write(f"**{pid}** · {info.category_code[0]} · {info.brand[0]} · ${info.avg_price[0]}")

recs = cooc[cooc.product_id == pid].sort_values("rank")
recs = recs.assign(reason=recs.sessions_together.map(lambda n: f"viewed together in {n:,} sessions"))
if len(recs) < 10:
    cat = db.query(f"select category_id from dim_product where product_id = {pid}").category_id[0]
    fill = popular[(popular.category_id == cat) & (popular.rec_product_id != pid)
                   & (~popular.rec_product_id.isin(recs.rec_product_id))].sort_values("rank")
    fill = fill.head(10 - len(recs)).assign(reason="popular in this category")
    recs = pd.concat([recs, fill], ignore_index=True)
st.dataframe(
    recs[["rec_product_id", "category_code", "brand", "avg_price", "reason"]].head(10),
    hide_index=True, width="stretch",
    column_config={"rec_product_id": st.column_config.NumberColumn("Product", format="%d"),
                   "avg_price": st.column_config.NumberColumn("Avg price ($)", format="%.2f")},
)
