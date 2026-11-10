-- P0: the warehouse holds exactly the rows the cleaning step wrote. Returns a row on mismatch.
with f as (select count(*) as n from {{ ref('fact_event') }}),
     c as (select count(*) as n from read_parquet('{{ var("clean_events_path") }}'))
select f.n as fact_rows, c.n as clean_rows
from f, c
where f.n <> c.n
