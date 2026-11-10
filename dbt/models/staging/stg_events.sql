-- Cleaned events written by pulseiq.ingest; adds category levels and date parts.
-- A raw user_session id can be shared by several users (348 of 9.24M in October),
-- so the session key combines it with user_id.
select
    event_ts,
    cast(event_ts as date) as event_date,
    event_type,
    product_id,
    category_id,
    category_code,
    split_part(category_code, '.', 1) as category_l1,
    case
        when category_code = 'unknown' then 'unknown'
        else coalesce(nullif(split_part(category_code, '.', 2), ''), split_part(category_code, '.', 1))
    end as category_l2,
    brand,
    price,
    user_id,
    user_session || ':' || user_id as session_id
from read_parquet('{{ var("clean_events_path") }}')
