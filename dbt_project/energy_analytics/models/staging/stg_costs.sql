with src as (
    select * from {{ source('raw', 'fact_couts') }}
)

select
    uwi,
    date_key,
    -- Depuis que le taux $/boe dépend du produit, le coût est généré au grain
    -- (puits, mois, produit) et se joint directement, sans répartition au prorata.
    product_type,
    opex_forage,
    opex_maintenance,
    opex_forage + opex_maintenance as opex_total,
    capex,
    devise
from src
