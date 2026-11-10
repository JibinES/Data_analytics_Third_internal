from pulseiq import ingest

HEADER = "event_time,event_type,product_id,category_id,category_code,brand,price,user_id,user_session\n"
ROWS = [
    "2019-10-01 00:00:00 UTC,view,1,10,electronics.smartphone,apple,500.0,100,s1",
    "2019-10-01 00:00:00 UTC,view,1,10,electronics.smartphone,apple,500.0,100,s1",  # exact duplicate
    "2019-10-01 00:01:00 UTC,cart,2,20,,,30.0,100,s1",  # missing category_code and brand
    "2019-10-01 00:02:00 UTC,purchase,3,30,appliances.kitchen,bosch,0,101,s2",  # price 0
    "2019-10-01 00:03:00 UTC,view,4,40,apparel.shoes,nike,80.0,102,",  # missing session
    "2019-10-01 00:04:00 UTC,purchase,2,20,,,30.0,100,s1",
]


def build(tmp_path):
    csv = tmp_path / "events.csv"
    csv.write_text(HEADER + "\n".join(ROWS) + "\n")
    con = ingest.connect(memory_limit="512MB")
    ingest.load_raw(con, [csv])
    ingest.clean(con)
    return con


def test_cleaning_drops_bad_rows(tmp_path):
    con = build(tmp_path)
    assert con.execute("SELECT count(*) FROM clean_events").fetchone()[0] == 3


def test_missing_values_become_unknown(tmp_path):
    con = build(tmp_path)
    row = con.execute(
        "SELECT category_code, brand FROM clean_events WHERE event_type = 'cart'"
    ).fetchone()
    assert row == ("unknown", "unknown")


def test_event_time_parsed_as_utc_timestamp(tmp_path):
    con = build(tmp_path)
    first = con.execute("SELECT min(event_ts)::VARCHAR FROM clean_events").fetchone()[0]
    assert first == "2019-10-01 00:00:00"
