with src as (
    select * from {{ source('raw', 'dim_prix') }}
)

select
    date_key,
    cast(date as date) as date,
    wti_usd,
    wcs_usd,
    taux_usdcad,
    wcs_cad
from src
