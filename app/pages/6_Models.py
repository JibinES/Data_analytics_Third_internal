import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plotly.express as px
import streamlit as st

import db

st.set_page_config(page_title="Models · PulseIQ", layout="wide")
st.title("Prediction models")
db.require("intent_metrics", "repeat_metrics")

intent_tab, repeat_tab = st.tabs(["Purchase intent (session)", "Repeat purchase (buyer)"])

with intent_tab:
    m = db.ml_metrics("intent_metrics")
    st.caption(
        "Given the first k events of a session (k = 1-10, never past a purchase), will it end in a purchase? "
        f"Trained on {m['train_window']}, tested on {m['test_window']}."
    )
    c = st.columns(4)
    c[0].metric("PR-AUC (LightGBM)", f"{m['lightgbm']['pr_auc']:.3f}")
    c[1].metric("PR-AUC (logistic baseline)", f"{m['logistic_baseline']['pr_auc']:.3f}")
    c[2].metric("Target (3× purchase rate)", f"{m['target_pr_auc']:.3f}")
    c[3].metric("ROC-AUC", f"{m['lightgbm']['roc_auc']:.3f}")
    st.write(f"Test sessions: {m['test_sessions']:,} · purchase rate {m['purchase_rate_test']:.1%} · "
             f"target met: **{'yes' if m['meets_target'] else 'no'}**")

    left, right = st.columns(2)
    with left:
        st.subheader("What drives the score")
        imp = db.ml("intent_importance")
        fig = px.bar(imp.sort_values("gain"), x="gain", y="feature", orientation="h",
                     labels={"gain": "Importance (gain)", "feature": ""})
        fig.update_layout(height=420, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width="stretch")
    with right:
        st.subheader("Accuracy by events seen")
        by_k = db.ml("intent_by_k")
        fig = px.line(by_k, x="k", y="pr_auc", markers=True,
                      labels={"k": "Events seen so far", "pr_auc": "PR-AUC"})
        fig.update_layout(height=420, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width="stretch")

    st.subheader("Highest-scored test sessions")
    scores = db.ml("intent_test_scores").nlargest(25, "score")
    st.dataframe(
        scores[["session_id", "k", "n_products", "max_price", "carted", "prev_purchases", "score", "label", "reasons"]],
        hide_index=True, width="stretch",
        column_config={"score": st.column_config.ProgressColumn("Score", min_value=0, max_value=1, format="%.2f"),
                       "label": st.column_config.CheckboxColumn("Bought"),
                       "reasons": "Top reasons (SHAP)"},
    )

with repeat_tab:
    m = db.ml_metrics("repeat_metrics")
    st.caption(
        f"Will a buyer from {m['observation_window']} buy again in {m['prediction_window']}? "
        "Buyers are split 70/30 at random into train and test."
    )
    c = st.columns(4)
    c[0].metric("ROC-AUC (LightGBM)", f"{m['lightgbm']['roc_auc']:.3f}")
    c[1].metric("ROC-AUC (rule: bought 2+ times)", f"{m['rule_bought_2_plus']['roc_auc']:.3f}")
    c[2].metric("Top-decile lift", f"{m['lightgbm']['top_decile_lift']:.2f}×")
    c[3].metric("Repeat rate", f"{m['repeat_rate']:.1%}")
    st.write(
        f"Flagging the same {m['rule_bought_2_plus']['flagged_users']:,} users as the rule, the model finds "
        f"{m['model_at_same_share']['recall']:.1%} of returning buyers (rule: {m['rule_bought_2_plus']['recall']:.1%}) "
        f"with precision {m['model_at_same_share']['precision']:.1%} (rule: {m['rule_bought_2_plus']['precision']:.1%})."
    )

    deciles = db.ml("repeat_deciles")
    fig = px.bar(deciles, x="decile", y="repeat_rate",
                 labels={"decile": "Score decile (1 = highest)", "repeat_rate": "Bought again"})
    fig.update_yaxes(tickformat=".0%")
    fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, width="stretch")

    cols = ["user_id", "frequency", "monetary", "recency_days", "score"]
    fmt = {"score": st.column_config.ProgressColumn("Chance to return", min_value=0, max_value=1, format="%.2f"),
           "monetary": st.column_config.NumberColumn("Spend ($)", format="%.0f"),
           "recency_days": st.column_config.NumberColumn("Days since last buy", format="%.1f")}
    l, r = st.columns(2)
    l.subheader("Most likely to return")
    l.dataframe(db.ml("repeat_likely")[cols].head(20), hide_index=True, width="stretch", column_config=fmt)
    r.subheader("High spenders at risk")
    r.dataframe(db.ml("repeat_at_risk")[cols].head(20), hide_index=True, width="stretch", column_config=fmt)
