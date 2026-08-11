with src as (
    select * from {{ source('raw', 'dim_prix') }}
)

select
    date_key,
    cast(date as date) as date,
    wti_usd,
    wcs_usd,
    taux_usdcad,
    wcs_cad,
    -- Prix gaz en $CAD/GJ. La conversion vers le boe (1 boe gaz = 6,34 GJ) appartient
    -- au mart, pas au staging : ici on ne fait que transporter la valeur publiée.
    gaz_cad_gj,
    -- True quand le mois n'avait pas encore de prix gaz publié et que la dernière
    -- valeur connue a été reportée. Voir scripts/03_ingest_prices.py.
    gaz_prix_reporte
from src
