with src as (
    select * from {{ source('raw', 'fact_couts') }}
)

select
    uwi,
    date_key,
    opex_forage,
    opex_maintenance,
    opex_forage + opex_maintenance as opex_total,
    capex,
    devise
from src
