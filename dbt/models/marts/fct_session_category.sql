-- Grain: one session x top-level category. Funnel flags per category (F1).
-- Cart is optional: most buying sessions in this dataset have no logged cart event,
-- so the funnel page reports viewed -> purchased alongside viewed -> carted -> purchased.
select
    session_id,
    any_value(user_id) as user_id,
    category_l1,
    cast(min(event_ts) as date) as session_date,
    hour(min(event_ts)) as start_hour,
    bool_or(event_type = 'view') as viewed,
    bool_or(event_type = 'cart') as carted,
    bool_or(event_type = 'purchase') as purchased,
    coalesce(sum(price) filter (where event_type = 'purchase'), 0) as revenue
from {{ ref('stg_events') }}
group by session_id, category_l1
