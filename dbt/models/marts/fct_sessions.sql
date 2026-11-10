-- Grain: one session. Base table for the funnel (F1) and purchase-intent model (F6).
select
    session_id,
    any_value(user_id) as user_id,
    min(event_ts) as started_at,
    max(event_ts) as ended_at,
    cast(min(event_ts) as date) as session_date,
    count(*) as events,
    count(*) filter (where event_type = 'view') as views,
    count(*) filter (where event_type = 'cart') as carts,
    count(*) filter (where event_type = 'purchase') as purchases,
    count(distinct product_id) as products,
    coalesce(sum(price) filter (where event_type = 'purchase'), 0) as revenue,
    bool_or(event_type = 'view') as viewed,
    bool_or(event_type = 'cart') as carted,
    bool_or(event_type = 'purchase') as purchased
from {{ ref('stg_events') }}
group by session_id
