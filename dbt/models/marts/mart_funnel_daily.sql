-- Grain: day x category x start hour. Pre-aggregated funnel counts for the funnel page (F1).
select
    session_date,
    category_l1,
    start_hour,
    count(*) as sessions,
    count(*) filter (where viewed) as viewed,
    count(*) filter (where carted) as carted,
    count(*) filter (where purchased) as purchased,
    count(*) filter (where viewed and carted) as viewed_carted,
    count(*) filter (where viewed and carted and purchased) as viewed_carted_purchased,
    count(*) filter (where viewed and purchased and not carted) as viewed_purchased_no_cart,
    sum(revenue) as revenue
from {{ ref('fct_session_category') }}
group by 1, 2, 3
