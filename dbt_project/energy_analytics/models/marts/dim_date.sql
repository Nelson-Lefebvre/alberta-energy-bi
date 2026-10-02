-- Dimension date au grain mensuel, alignée sur la fenêtre des prix (24 mois).
-- Grain mensuel car toutes les clés date_key des faits sont en YYYYMM.
with bornes as (
    select min(date) as date_min, max(date) as date_max
    from {{ ref('stg_eia_prices') }}
),

-- Databricks SQL : sequence() construit le tableau des mois, explode() en fait des
-- lignes. Équivalent de unnest(generate_series(...)) en DuckDB.
mois as (
    select explode(sequence(date_min, date_max, interval 1 month)) as date
    from bornes
)

select
    (extract(year from date) * 100 + extract(month from date))::int as date_key,
    cast(date as date)                  as date,
    extract(year from date)::int        as annee,
    extract(quarter from date)::int     as trimestre,
    extract(month from date)::int       as mois,
    date_format(date, 'MMMM')           as mois_nom,
    extract(month from date) in (1, 2, 3) as is_hiver
from mois
