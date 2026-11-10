"""F6: purchase-intent model. Given the first k events of a session, will it end in a purchase?

Leakage rule: features only see events 1..k of the session, and k is always chosen so that
no purchase falls inside events 1..k. `prefix_features` is shared with the live replay (F9).
"""
import json
import time

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from pulseiq import config, warehouse

MAX_K = 10
SAMPLE_SHARE = 0.15
FEATURES = [
    "k", "n_products", "n_categories", "max_price", "avg_price", "carted", "n_carts",
    "duration_s", "start_hour", "weekday", "repeat_views", "prev_sessions", "prev_purchases",
]
LABELS = {
    "k": "events so far", "n_products": "distinct products", "n_categories": "distinct categories",
    "max_price": "highest price viewed", "avg_price": "average price viewed", "carted": "added to cart",
    "n_carts": "cart adds", "duration_s": "session length", "start_hour": "hour of day",
    "weekday": "weekday", "repeat_views": "repeat views of a product", "prev_sessions": "past sessions",
    "prev_purchases": "past purchases",
}

# Event order inside a session. Ties on timestamp put purchase last, so a prefix never
# includes a purchase that happened in the same second as its last event.
ORDER = "event_ts, case event_type when 'view' then 0 when 'cart' then 1 else 2 end, product_id"

PREFIX_FEATURES_SQL = f"""
with ranked as (
    select ev.*, row_number() over (partition by session_id order by {ORDER}) as rn
    from ev
),
prefix as (
    select ranked.* from ranked join cut using (session_id) where rn <= cut.k
)
select
    session_id,
    count(*) as k,
    count(distinct product_id) as n_products,
    count(distinct category_id) as n_categories,
    max(price) as max_price,
    avg(price) as avg_price,
    max((event_type = 'cart')::int) as carted,
    count(*) filter (where event_type = 'cart') as n_carts,
    epoch(max(event_ts) - min(event_ts)) as duration_s,
    hour(min(event_ts)) as start_hour,
    isodow(min(event_ts)) as weekday,
    count(*) - count(distinct product_id) as repeat_views,
    count(*) filter (where event_type = 'purchase') as leaked_purchases
from prefix
group by session_id
"""


def prefix_features(con) -> pd.DataFrame:
    """Features from the first k events of each session.

    Expects tables/views in `con`: ev(session_id, event_ts, event_type, product_id, category_id, price)
    and cut(session_id, k). Raises if any prefix contains a purchase.
    """
    df = con.execute(PREFIX_FEATURES_SQL).df()
    if (df.leaked_purchases > 0).any():
        raise ValueError("Leakage: a prefix contains a purchase event")
    return df.drop(columns="leaked_purchases")


def build_dataset(con, date_from: str, date_to: str) -> pd.DataFrame:
    """Sample sessions in [date_from, date_to), pick a random safe cut-off k, compute features + label.

    Sampling and k use hashes of the session id rather than random(), so runs are reproducible.
    """
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE s AS
        SELECT session_id, user_id, started_at, purchased
        FROM fct_sessions
        WHERE started_at >= '{date_from}' AND started_at < '{date_to}' AND hash(session_id || ':sample') % 10000 < {int(SAMPLE_SHARE * 10000)}
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE ev AS
        SELECT f.session_id, f.event_ts, f.event_type, f.product_id, p.category_id, f.price
        FROM fact_event f
        JOIN s USING (session_id)
        JOIN dim_product p USING (product_id)
        """
    )
    # Largest safe k = events before the first purchase (or all events), capped at MAX_K
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE cut AS
        WITH ranked AS (
            SELECT session_id, event_type, row_number() OVER (PARTITION BY session_id ORDER BY {ORDER}) AS rn
            FROM ev
        ),
        bounds AS (
            SELECT session_id,
                   coalesce(min(rn) FILTER (WHERE event_type = 'purchase') - 1, count(*)) AS safe_k
            FROM ranked GROUP BY session_id
        )
        SELECT session_id, 1 + (hash(session_id || ':k') % least(safe_k, {MAX_K}))::int AS k
        FROM bounds WHERE safe_k > 0
        """
    )
    feats = prefix_features(con)
    hist = con.execute(
        """
        WITH h AS (
            SELECT session_id,
                   count(*) OVER w AS prev_sessions,
                   coalesce(sum(purchased::int) OVER w, 0) AS prev_purchases
            FROM fct_sessions
            WINDOW w AS (PARTITION BY user_id ORDER BY started_at ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
        )
        SELECT s.session_id, s.purchased::int AS label, s.started_at, h.prev_sessions, h.prev_purchases
        FROM s JOIN h USING (session_id)
        """
    ).df()
    return feats.merge(hist, on="session_id").sort_values("session_id", ignore_index=True)


def top_reasons(booster: lgb.Booster, x: pd.DataFrame, n: int = 3) -> list[str]:
    """Top-n features pushing each score up, from LightGBM's built-in SHAP values."""
    contrib = booster.predict(x, pred_contrib=True)[:, :-1]
    order = np.argsort(-contrib, axis=1)[:, :n]
    cols = np.array(FEATURES)
    return [", ".join(LABELS[c] for c in cols[row]) for row in order]


def run() -> dict:
    started = time.time()
    con = warehouse.connect()
    train = build_dataset(con, "2019-10-01", config.INTENT_TRAIN_END)
    test = build_dataset(con, config.INTENT_TRAIN_END, "2019-11-01")
    con.close()
    print(f"train {len(train):,} sessions, test {len(test):,} sessions")

    model = lgb.LGBMClassifier(
        n_estimators=400, learning_rate=0.05, num_leaves=63, min_child_samples=100,
        subsample=0.8, subsample_freq=1, colsample_bytree=0.8, is_unbalance=True,
        random_state=config.SEED, deterministic=True, force_col_wise=True, verbose=-1,
    )
    model.fit(train[FEATURES], train.label)
    p = model.predict_proba(test[FEATURES])[:, 1]

    baseline = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced"))
    baseline.fit(np.log1p(train[FEATURES].clip(lower=0)), train.label)
    q = baseline.predict_proba(np.log1p(test[FEATURES].clip(lower=0)))[:, 1]

    prevalence = float(test.label.mean())
    pr_auc = float(average_precision_score(test.label, p))
    by_k = (
        test.assign(score=p).groupby("k")
        .apply(lambda g: pd.Series({
            "sessions": len(g), "purchase_rate": g.label.mean(),
            "pr_auc": average_precision_score(g.label, g.score) if g.label.nunique() > 1 else np.nan,
        }), include_groups=False)
        .reset_index()
    )
    importance = pd.DataFrame({
        "feature": [LABELS[f] for f in FEATURES],
        "gain": model.booster_.feature_importance("gain"),
    }).sort_values("gain", ascending=False)

    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model.booster_.save_model(str(config.MODELS_DIR / "intent.txt"))
    (config.MODELS_DIR / "intent_features.json").write_text(json.dumps(FEATURES))

    sample = test.assign(score=p).sample(n=min(20_000, len(test)), random_state=config.SEED)
    sample["reasons"] = top_reasons(model.booster_, sample[FEATURES])
    warehouse.write_parquet(sample, "intent_test_scores")
    warehouse.write_parquet(by_k, "intent_by_k")
    warehouse.write_parquet(importance, "intent_importance")

    metrics = {
        "train_sessions": len(train), "test_sessions": len(test),
        "train_window": f"2019-10-01 to {config.INTENT_TRAIN_END} (exclusive)",
        "test_window": f"{config.INTENT_TRAIN_END} to 2019-11-01 (exclusive)",
        "purchase_rate_test": prevalence,
        "lightgbm": {"pr_auc": pr_auc, "roc_auc": float(roc_auc_score(test.label, p))},
        "logistic_baseline": {"pr_auc": float(average_precision_score(test.label, q)),
                              "roc_auc": float(roc_auc_score(test.label, q))},
        "target_pr_auc": 3 * prevalence,
        "meets_target": pr_auc >= 3 * prevalence and pr_auc > float(average_precision_score(test.label, q)),
        "seconds": round(time.time() - started, 1),
    }
    warehouse.write_json(metrics, "intent_metrics")
    print(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    run()
