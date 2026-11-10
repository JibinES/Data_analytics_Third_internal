-- Grain: one cleaned event.
select
    event_ts,
    event_date as date_key,
    event_type,
    user_id,
    product_id,
    session_id,
    price
from {{ ref('stg_events') }}
