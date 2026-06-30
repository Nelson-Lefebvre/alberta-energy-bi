with src as (
    select * from {{ source('raw', 'dim_puits') }}
)

select
    uwi,
    operator_name,
    area,
    region,
    field,
    well_type,
    status,
    -- Garde-fou : ~5 puits ont un spud_date pré-1900 (ex. 1883-01-01), aberrant pour des
    -- puits produisant en 2024-2026 → NULL (date inconnue) au lieu de polluer l'âge des
    -- puits / la hiérarchie spud. Les vraies dates manquantes (~4116) sont déjà NULL.
    case when cast(spud_date as date) < DATE '1900-01-01'
         then null else cast(spud_date as date) end as spud_date,
    latitude,
    longitude
from src
