"""F3: RFM scores + k-means clusters with persona names, for every buyer."""
import json
import time

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from pulseiq import config, warehouse

K_RANGE = range(3, 9)
SILHOUETTE_SAMPLE = 50_000


def load_buyers(con) -> pd.DataFrame:
    """Recency (days), frequency (purchase sessions) and monetary (spend) per buyer."""
    return con.execute(
        """
        with ref as (select max(ended_at) + interval 1 second as ref_ts from fct_sessions)
        select
            user_id,
            date_diff('second', max(started_at) filter (where purchased), any_value(ref.ref_ts)) / 86400.0 as recency_days,
            count(*) filter (where purchased) as frequency,
            sum(revenue) as monetary
        from fct_sessions, ref
        group by user_id
        having count(*) filter (where purchased) > 0
        """
    ).df()


def frequency_score(f: pd.Series) -> pd.Series:
    # Most buyers buy once, so quintiles would split ties arbitrarily; use fixed bands instead.
    return pd.cut(f, bins=[0, 1, 2, 3, 5, np.inf], labels=[1, 2, 3, 4, 5]).astype(int)


def score_rfm(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # 5 = best: recent, frequent, high spend
    df["r_score"] = 6 - pd.qcut(df.recency_days.rank(method="first"), 5, labels=False).add(1)
    df["f_score"] = frequency_score(df.frequency)
    df["m_score"] = pd.qcut(df.monetary.rank(method="first"), 5, labels=False).add(1)
    return df


def features(df: pd.DataFrame) -> np.ndarray:
    x = np.column_stack([np.log1p(df.recency_days), np.log1p(df.frequency), np.log1p(df.monetary)])
    return StandardScaler().fit_transform(x)


def choose_k(x: np.ndarray, rng: np.random.Generator) -> tuple[int, dict]:
    idx = rng.choice(len(x), size=min(SILHOUETTE_SAMPLE, len(x)), replace=False)
    scores = {}
    for k in K_RANGE:
        labels = KMeans(n_clusters=k, n_init=4, random_state=config.SEED).fit_predict(x[idx])
        scores[k] = float(silhouette_score(x[idx], labels))
    return max(scores, key=scores.get), scores


def persona(r: float, f: float, m: float) -> str:
    """Name a cluster from its mean R/F/M scores (1-5, 5 = best)."""
    if f >= 3.5 and m >= 3.5 and r >= 3.5:
        return "Champions"
    if f >= 3 and r < 3:
        return "At risk"
    if f >= 3:
        return "Loyal"
    if r >= 3.5 and m >= 3.5:
        return "New big spenders"
    if r >= 3.5:
        return "New buyers"
    if m >= 3.5:
        return "Lapsed big spenders"
    return "Lapsed one-timers"


def name_clusters(df: pd.DataFrame) -> dict[int, str]:
    means = df.groupby("cluster")[["r_score", "f_score", "m_score"]].mean()
    names, used = {}, {}
    for c, row in means.sort_values("m_score", ascending=False).iterrows():
        name = persona(row.r_score, row.f_score, row.m_score)
        used[name] = used.get(name, 0) + 1
        names[c] = name if used[name] == 1 else f"{name} {used[name]}"
    return names


def top_categories(con, segments: pd.DataFrame) -> pd.DataFrame:
    con.register("seg", segments[["user_id", "segment"]])
    return con.execute(
        """
        select segment, category_l1, count(*) as purchases
        from fact_event f
        join seg using (user_id)
        join dim_product p using (product_id)
        where f.event_type = 'purchase'
        group by 1, 2
        qualify row_number() over (partition by segment order by count(*) desc) <= 3
        order by segment, purchases desc
        """
    ).df()


def run() -> dict:
    started = time.time()
    rng = np.random.default_rng(config.SEED)
    con = warehouse.connect()
    buyers = score_rfm(load_buyers(con))
    x = features(buyers)
    k, silhouettes = choose_k(x, rng)
    buyers["cluster"] = KMeans(n_clusters=k, n_init=4, random_state=config.SEED).fit_predict(x)
    names = name_clusters(buyers)
    buyers["segment"] = buyers.cluster.map(names)

    total_rev = buyers.monetary.sum()
    summary = (
        buyers.groupby("segment")
        .agg(buyers=("user_id", "size"), revenue=("monetary", "sum"),
             avg_recency_days=("recency_days", "mean"), avg_frequency=("frequency", "mean"),
             avg_spend=("monetary", "mean"), r_score=("r_score", "mean"),
             f_score=("f_score", "mean"), m_score=("m_score", "mean"))
        .reset_index()
        .assign(buyer_share=lambda d: d.buyers / len(buyers), revenue_share=lambda d: d.revenue / total_rev)
        .sort_values("revenue", ascending=False)
    )
    cats = top_categories(con, buyers)
    con.close()

    warehouse.write_parquet(buyers, "user_segments")
    warehouse.write_parquet(summary, "segment_summary")
    warehouse.write_parquet(cats, "segment_categories")
    metrics = {
        "buyers": len(buyers),
        "chosen_k": k,
        "silhouette_by_k": silhouettes,
        "silhouette": silhouettes[k],
        "segments": summary[["segment", "buyers", "revenue_share"]].to_dict("records"),
        "sizes_add_up": int(summary.buyers.sum()) == len(buyers),
        "seconds": round(time.time() - started, 1),
    }
    warehouse.write_json(metrics, "segments_metrics")
    print(json.dumps(metrics, indent=2, default=str))
    return metrics


if __name__ == "__main__":
    run()
