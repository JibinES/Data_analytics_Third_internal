-- Grain: one product. A product can appear with different brand or category values
-- across events, so the most frequent combination wins.
with combos as (
    select product_id, category_id, category_code, category_l1, category_l2, brand,
           count(*) as n, sum(price) as price_total
    from {{ ref('stg_events') }}
    group by all
),
best as (
    select product_id,
           arg_max({'category_id': category_id, 'category_code': category_code, 'category_l1': category_l1,
                    'category_l2': category_l2, 'brand': brand}, n) as attrs,
           sum(price_total) / sum(n) as avg_price
    from combos
    group by product_id
)
select
    product_id,
    attrs.category_id,
    attrs.category_code,
    attrs.category_l1,
    attrs.category_l2,
    attrs.brand,
    avg_price
from best
