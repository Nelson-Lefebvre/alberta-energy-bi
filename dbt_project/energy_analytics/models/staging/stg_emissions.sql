with src as (
    select * from {{ source('raw', 'fact_emissions') }}
)

select
    uwi,
    date_key,
    co2_tonnes,
    ch4_tonnes,
    co2eq_total,
    scope
from src
