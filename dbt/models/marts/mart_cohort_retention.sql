-- Grain: cohort week x weeks since first seen (F2).
-- active_users = any event that week; buyers = at least one purchase that week.
with activity as (
    select
        e.user_id,
        u.cohort_week,
        cast(date_diff('day', u.cohort_week, cast(date_trunc('week', e.event_ts) as date)) / 7 as integer) as week_number,
        bool_or(e.event_type = 'purchase') as bought
    from {{ ref('stg_events') }} e
    join {{ ref('dim_user') }} u using (user_id)
    group by 1, 2, 3
),
cohort_size as (
    select cohort_week, count(*) as cohort_users
    from {{ ref('dim_user') }}
    group by 1
)
select
    a.cohort_week,
    a.week_number,
    c.cohort_users,
    count(*) as active_users,
    count(*) filter (where a.bought) as buyers,
    count(*) / c.cohort_users as active_share,
    count(*) filter (where a.bought) / c.cohort_users as buyer_share
from activity a
join cohort_size c using (cohort_week)
group by 1, 2, 3
