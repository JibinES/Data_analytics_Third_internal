-- Grain: one user. Built from sessions, which is much cheaper than rescanning events.
-- rfm_cluster is added later by the segmentation module (F3).
select
    user_id,
    min(started_at) as first_seen,
    max(ended_at) as last_seen,
    cast(date_trunc('week', min(started_at)) as date) as cohort_week,
    count(*) as sessions,
    sum(purchases) as purchases,
    sum(revenue) as revenue
from {{ ref('fct_sessions') }}
group by user_id
