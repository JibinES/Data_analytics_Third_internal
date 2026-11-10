-- Session-level event counts must add up to the fact table. Returns a row on mismatch.
with s as (select sum(events) as n, sum(purchases) as p from {{ ref('fct_sessions') }}),
     f as (select count(*) as n, count(*) filter (where event_type = 'purchase') as p from {{ ref('fact_event') }})
select s.n, f.n, s.p, f.p
from s, f
where s.n <> f.n or s.p <> f.p
