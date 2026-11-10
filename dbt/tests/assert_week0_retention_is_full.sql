-- F2 acceptance: every user is active in their own cohort week. Returns cohorts that break this.
select cohort_week, active_share
from {{ ref('mart_cohort_retention') }}
where week_number = 0 and active_share <> 1
