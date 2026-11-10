"""F7: repeat-purchase model. Will a buyer from the observation window buy again afterwards?

October-only fallback from the PRD: observe 1-21 Oct, predict 22-31 Oct. Features use only
events before REPEAT_OBS_END. Users are split 70/30 at random for train and test.
"""
import json
import time

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split

from pulseiq import config, warehouse

FEATURES = [
    "recency_days", "frequency", "monetary", "sessions", "categories_bought",
    "avg_gap_days", "view_to_purchase", "avg_purchase_price", "days_active", "carts",
]


def build_dataset(con) -> pd.DataFrame:
    end = config.REPEAT_OBS_END
    return con.execute(
        f"""
        WITH obs AS (
            SELECT * FROM fct_sessions WHERE started_at < '{end}'
        ),
        buyers AS (
            SELECT user_id,
                   date_diff('second', max(started_at) FILTER (WHERE purchased), TIMESTAMP '{end}') / 86400.0 AS recency_days,
                   count(*) FILTER (WHERE purchased) AS frequency,
                   sum(revenue) AS monetary,
                   count(*) AS sessions,
                   sum(views) AS views,
                   sum(purchases) AS purchases,
                   sum(carts) AS carts,
                   count(DISTINCT session_date) AS days_active,
                   date_diff('second', min(started_at), max(started_at)) / 86400.0 / greatest(count(*) - 1, 1) AS avg_gap_days
            FROM obs GROUP BY user_id
            HAVING count(*) FILTER (WHERE purchased) > 0
        ),
        cats AS (
            SELECT f.user_id, count(DISTINCT p.category_l1) AS categories_bought
            FROM fact_event f JOIN dim_product p USING (product_id)
            WHERE f.event_type = 'purchase' AND f.event_ts < '{end}'
            GROUP BY 1
        ),
        later AS (
            SELECT DISTINCT user_id FROM fct_sessions WHERE started_at >= '{end}' AND purchased
        )
        SELECT b.user_id, b.recency_days, b.frequency, b.monetary, b.sessions,
               coalesce(c.categories_bought, 0) AS categories_bought, b.avg_gap_days,
               b.purchases / greatest(b.views, 1) AS view_to_purchase,
               b.monetary / b.purchases AS avg_purchase_price, b.days_active, b.carts,
               (l.user_id IS NOT NULL)::int AS label
        FROM buyers b
        LEFT JOIN cats c USING (user_id)
        LEFT JOIN later l USING (user_id)
        """
    ).df()


def lift_at(y: np.ndarray, score: np.ndarray, share: float = 0.1) -> float:
    n = max(1, int(len(y) * share))
    top = np.argsort(-score)[:n]
    return float(y[top].mean() / y.mean())


def run() -> dict:
    started = time.time()
    con = warehouse.connect()
    df = build_dataset(con).sort_values("user_id", ignore_index=True)  # stable order -> reproducible split
    con.close()
    train, test = train_test_split(df, test_size=0.3, random_state=config.SEED, stratify=df.label)

    model = lgb.LGBMClassifier(
        n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=200,
        subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=config.SEED, verbose=-1,
    )
    model.fit(train[FEATURES], train.label)
    p = model.predict_proba(test[FEATURES])[:, 1]
    rule = (test.frequency >= 2).astype(float).to_numpy()
    y = test.label.to_numpy()

    # The rule flags a fixed share of users; compare the model at that same share
    flagged = int(rule.sum())
    model_top = np.zeros_like(rule)
    model_top[np.argsort(-p)[:flagged]] = 1

    scored = test.assign(score=p).sort_values("score", ascending=False)
    warehouse.write_parquet(scored.head(2000), "repeat_likely")
    # At risk: high spenders (top quarter by spend) with the lowest chance of returning
    big = scored[scored.monetary >= scored.monetary.quantile(0.75)]
    warehouse.write_parquet(big.sort_values("score").head(2000), "repeat_at_risk")
    deciles = (
        scored.assign(decile=pd.qcut(scored.score.rank(method="first", ascending=False), 10, labels=range(1, 11)))
        .groupby("decile", observed=True).agg(users=("label", "size"), repeat_rate=("label", "mean")).reset_index()
    )
    warehouse.write_parquet(deciles, "repeat_deciles")
    importance = pd.DataFrame({"feature": FEATURES, "gain": model.booster_.feature_importance("gain")})
    warehouse.write_parquet(importance.sort_values("gain", ascending=False), "repeat_importance")

    metrics = {
        "observation_window": f"2019-10-01 to {config.REPEAT_OBS_END} (exclusive)",
        "prediction_window": f"{config.REPEAT_OBS_END} to 2019-10-31",
        "buyers": len(df), "train_users": len(train), "test_users": len(test),
        "repeat_rate": float(y.mean()),
        "lightgbm": {"roc_auc": float(roc_auc_score(y, p)), "pr_auc": float(average_precision_score(y, p)),
                     "top_decile_lift": lift_at(y, p)},
        "rule_bought_2_plus": {"roc_auc": float(roc_auc_score(y, rule)), "flagged_users": flagged,
                               "precision": float(y[rule == 1].mean()), "recall": float(y[rule == 1].sum() / y.sum())},
        "model_at_same_share": {"precision": float(y[model_top == 1].mean()),
                                "recall": float(y[model_top == 1].sum() / y.sum())},
        "seconds": round(time.time() - started, 1),
    }
    metrics["beats_rule"] = metrics["lightgbm"]["roc_auc"] > metrics["rule_bought_2_plus"]["roc_auc"]
    warehouse.write_json(metrics, "repeat_metrics")
    print(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    run()
