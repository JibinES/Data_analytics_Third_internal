-- Grain: one calendar day covered by the data.
with bounds as (
    select min(event_date) as d0, max(event_date) as d1 from {{ ref('stg_events') }}
)
select
    cast(d.date_key as date) as date_key,
    dayname(d.date_key) as weekday,
    isodow(d.date_key) as weekday_num,
    cast(date_trunc('week', d.date_key) as date) as week_start,
    strftime(d.date_key, '%Y-%m') as month
from bounds, generate_series(bounds.d0, bounds.d1, interval 1 day) as d(date_key)
