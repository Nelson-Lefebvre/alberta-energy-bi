with src as (
    select * from {{ source('raw', 'petrinex24') }}
)

select
    operator_id,
    uwi,
    cast(date as date)                                          as date,
    (extract(year from date) * 100 + extract(month from date))::int as date_key,
    product_type,
    activity_type,
    volume_brut,
    -- Correctif unité gaz : Petrinex déclare le gaz en 10³m³ (e3m³), pas en m³.
    -- L'ingest a calculé boe = volume_brut / 169.9 (facteur m³→boe) sans appliquer
    -- le facteur e3m³→m³ (×1000) : le gaz était sous-estimé d'un facteur 1000.
    -- On rétablit l'échelle UNIQUEMENT pour le gaz ; OIL/COND/WATER inchangés.
    case when product_type = 'GAS' then volume_boe * 1000 else volume_boe end as volume_boe
from src
