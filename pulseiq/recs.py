"""F5 + F8: item-to-item recommender and its offline evaluation.

Methods
- popularity: most-purchased products in the query product's category (baseline)
- co-occurrence: products viewed in the same session, scored by cosine similarity
- hybrid: co-occurrence, topped up with popularity when it has fewer than 10 items

Evaluation (time split): built on events before RECS_TRAIN_END. For each user, the query is the
last product they viewed before the cut-off; the targets are the other products they carted
or purchased after it. Metrics: HitRate@10, Precision@10, catalogue coverage.
"""
import json
import time

import pandas as pd

from pulseiq import config, warehouse

TOP_N = 10
KEEP_N = 20
MAX_PRODUCTS_PER_SESSION = 20
MIN_PAIR_SESSIONS = 2


def build(con) -> None:
    cut = config.RECS_TRAIN_END
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE sp AS
        WITH v AS (
            SELECT DISTINCT session_id, product_id FROM fact_event
            WHERE event_type = 'view' AND event_ts < '{cut}'
        ),
        sized AS (SELECT session_id FROM v GROUP BY 1 HAVING count(*) BETWEEN 2 AND {MAX_PRODUCTS_PER_SESSION})
        SELECT v.* FROM v JOIN sized USING (session_id)
        """
    )
    con.execute("CREATE OR REPLACE TEMP TABLE pcount AS SELECT product_id, count(*) AS n FROM sp GROUP BY 1")
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE pairs AS
        SELECT a.product_id AS src, b.product_id AS dst, count(*) AS co
        FROM sp a JOIN sp b ON a.session_id = b.session_id AND a.product_id < b.product_id
        GROUP BY 1, 2
        HAVING count(*) >= {MIN_PAIR_SESSIONS}
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE cooc AS
        WITH both_ways AS (
            SELECT src, dst, co FROM pairs UNION ALL SELECT dst, src, co FROM pairs
        ),
        scored AS (
            SELECT b.src, b.dst, b.co, b.co / sqrt(ps.n * pd.n) AS score
            FROM both_ways b JOIN pcount ps ON ps.product_id = b.src JOIN pcount pd ON pd.product_id = b.dst
        )
        SELECT *, row_number() OVER (PARTITION BY src ORDER BY score DESC, co DESC, dst) AS rank
        FROM scored
        QUALIFY rank <= {KEEP_N}
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE pop AS
        WITH counts AS (
            SELECT p.category_id, f.product_id,
                   count(*) FILTER (WHERE f.event_type = 'purchase') AS purchases, count(*) AS events
            FROM fact_event f JOIN dim_product p USING (product_id)
            WHERE f.event_ts < '{cut}'
            GROUP BY 1, 2
        )
        SELECT *, row_number() OVER (PARTITION BY category_id ORDER BY purchases DESC, events DESC, product_id) AS rank
        FROM counts
        QUALIFY rank <= {KEEP_N + 1}
        """
    )


def evaluate(con) -> tuple[dict, pd.DataFrame]:
    cut = config.RECS_TRAIN_END
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE queries AS
        SELECT user_id, arg_max(product_id, event_ts) AS q
        FROM fact_event WHERE event_type = 'view' AND event_ts < '{cut}'
        GROUP BY user_id
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE targets AS
        SELECT DISTINCT f.user_id, f.product_id AS tgt
        FROM fact_event f JOIN queries q USING (user_id)
        WHERE f.event_ts >= '{cut}' AND f.event_type IN ('cart', 'purchase') AND f.product_id <> q.q
        """
    )
    con.execute("CREATE OR REPLACE TEMP TABLE evalq AS SELECT DISTINCT q.user_id, q.q FROM queries q JOIN targets USING (user_id)")
    # Recommendation lists per method for the evaluated query products
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE lists AS
        WITH qs AS (SELECT DISTINCT q FROM evalq),
        pop_l AS (
            SELECT qs.q, pop.product_id AS item,
                   row_number() OVER (PARTITION BY qs.q ORDER BY pop.rank) AS r
            FROM qs JOIN dim_product dp ON dp.product_id = qs.q
            JOIN pop ON pop.category_id = dp.category_id AND pop.product_id <> qs.q
        ),
        co_l AS (SELECT qs.q, c.dst AS item, c.rank AS r FROM qs JOIN cooc c ON c.src = qs.q),
        hy AS (
            SELECT q, item, row_number() OVER (PARTITION BY q ORDER BY src_order, r) AS r
            FROM (
                SELECT q, item, 0 AS src_order, r FROM co_l WHERE r <= {TOP_N}
                UNION ALL
                SELECT p.q, p.item, 1, p.r FROM pop_l p
                WHERE NOT EXISTS (SELECT 1 FROM co_l c WHERE c.q = p.q AND c.item = p.item AND c.r <= {TOP_N})
            )
        )
        SELECT 'popularity' AS method, q, item FROM pop_l WHERE r <= {TOP_N}
        UNION ALL SELECT 'co-occurrence', q, item FROM co_l WHERE r <= {TOP_N}
        UNION ALL SELECT 'hybrid', q, item FROM hy WHERE r <= {TOP_N}
        """
    )
    catalogue = con.execute(
        f"SELECT count(DISTINCT product_id) FROM fact_event WHERE event_ts < '{cut}'"
    ).fetchone()[0]
    table = con.execute(
        f"""
        WITH m AS (SELECT DISTINCT method FROM lists),
        per_user AS (
            SELECT m.method, e.user_id, count(t.tgt) AS hits
            FROM m CROSS JOIN evalq e
            LEFT JOIN lists l ON l.method = m.method AND l.q = e.q
            LEFT JOIN targets t ON t.user_id = e.user_id AND t.tgt = l.item
            GROUP BY 1, 2
        )
        SELECT method,
               count(*) AS users,
               avg((hits > 0)::int) AS hit_rate_at_10,
               avg(hits / {TOP_N}) AS precision_at_10
        FROM per_user GROUP BY method
        """
    ).df()
    coverage = con.execute(
        f"SELECT method, count(DISTINCT item) / {catalogue} AS coverage FROM lists GROUP BY method"
    ).df()
    table = table.merge(coverage, on="method").sort_values("hit_rate_at_10", ascending=False)
    info = {"catalogue_products": catalogue, "evaluated_users": int(table.users.max())}
    return info, table


def export(con) -> None:
    recs = con.execute(
        f"""
        SELECT c.src AS product_id, c.dst AS rec_product_id, c.rank, c.co AS sessions_together, c.score,
               p.category_code, p.brand, p.avg_price
        FROM cooc c JOIN dim_product p ON p.product_id = c.dst
        WHERE c.rank <= {TOP_N}
        """
    ).df()
    pop = con.execute(
        f"""
        SELECT pop.category_id, pop.product_id AS rec_product_id, pop.rank, pop.purchases,
               p.category_code, p.brand, p.avg_price
        FROM pop JOIN dim_product p USING (product_id)
        """
    ).df()
    warehouse.write_parquet(recs, "recs_cooc")
    warehouse.write_parquet(pop, "recs_popular")


def run() -> dict:
    started = time.time()
    con = warehouse.connect()
    con.execute(f"SET temp_directory = '{config.DATA / 'tmp'}'")
    build(con)
    print(f"[{time.time() - started:.0f}s] built co-occurrence and popularity")
    info, table = evaluate(con)
    print(f"[{time.time() - started:.0f}s] evaluated")
    export(con)
    con.close()
    warehouse.write_parquet(table, "recs_eval")
    best = table.set_index("method")
    metrics = {
        **info,
        "train_window": f"before {config.RECS_TRAIN_END}",
        "test_window": f"{config.RECS_TRAIN_END} to 2019-10-31",
        "methods": table.to_dict("records"),
        "cooc_beats_popularity": bool(best.loc["co-occurrence", "hit_rate_at_10"] > best.loc["popularity", "hit_rate_at_10"]),
        "seconds": round(time.time() - started, 1),
    }
    warehouse.write_json(metrics, "recs_metrics")
    print(json.dumps(metrics, indent=2, default=str))
    return metrics


if __name__ == "__main__":
    run()
