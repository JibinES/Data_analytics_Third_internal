"""Leakage guard for the purchase-intent features (PRD F6)."""
import duckdb
import pandas as pd
import pytest

from pulseiq import intent

T0 = pd.Timestamp("2019-10-01 10:00:00")


def session_events(with_tail: bool) -> pd.DataFrame:
    rows = [
        ("s1", T0, "view", 1, 10, 100.0),
        ("s1", T0 + pd.Timedelta(seconds=30), "view", 2, 10, 120.0),
        ("s1", T0 + pd.Timedelta(seconds=60), "cart", 2, 10, 120.0),
    ]
    if with_tail:  # events after the cut-off, including the purchase
        rows += [
            ("s1", T0 + pd.Timedelta(seconds=90), "purchase", 2, 10, 120.0),
            ("s1", T0 + pd.Timedelta(seconds=120), "view", 3, 20, 999.0),
        ]
    return pd.DataFrame(rows, columns=["session_id", "event_ts", "event_type", "product_id", "category_id", "price"])


def features(events: pd.DataFrame, k: int) -> pd.DataFrame:
    con = duckdb.connect()
    con.register("ev", events)
    con.register("cut", pd.DataFrame({"session_id": ["s1"], "k": [k]}))
    return intent.prefix_features(con)


def test_features_ignore_events_after_cutoff():
    assert features(session_events(False), 3).equals(features(session_events(True), 3))


def test_prefix_with_purchase_is_rejected():
    with pytest.raises(ValueError, match="Leakage"):
        features(session_events(True), 4)


def test_same_second_purchase_sorts_after_view():
    events = pd.DataFrame(
        [("s1", T0, "purchase", 1, 10, 50.0), ("s1", T0, "view", 1, 10, 50.0)],
        columns=["session_id", "event_ts", "event_type", "product_id", "category_id", "price"],
    )
    assert features(events, 1).k.iloc[0] == 1
