-- Grain: one event type, with its funnel position.
select * from (
    values
        ('view', 1, 'Viewed a product'),
        ('cart', 2, 'Added to cart'),
        ('remove_from_cart', 2, 'Removed from cart'),
        ('purchase', 3, 'Purchased')
) as t(event_type, funnel_stage, description)
