-- Dimension puits exposée aux marts.
-- Base = référentiel AER ST37 (stg_aer_wells). On RATTACHE en plus les uwi qui
-- PRODUISENT (PROD, hors WATER) mais sont absents de l'extrait AER (~1453 uwi,
-- ~53 M boe, 1.4%) à un bucket explicite « Puits hors référentiel AER ». Ainsi la
-- région est cohérente des DEUX côtés : production (via la relation dim_puits) ET
-- agrégats fact_kpis (qui coalesçaient déjà null -> ce même libellé). Sans ça, le
-- slicer région montrait ce bucket avec CO2 mais 0 production.
-- Aucune donnée inventée : seules les métadonnées inconnues (opérateur, géo,
-- statut...) sont nulles ; uwi et production restent réels (Petrinex).
with aer as (
    select
        uwi, operator_name, area, region, field,
        well_type, status, spud_date, latitude, longitude
    from {{ ref('stg_aer_wells') }}
),

residus as (
    select distinct
        p.uwi,
        cast(null as varchar)         as operator_name,
        cast(null as varchar)         as area,
        'Puits hors référentiel AER'  as region,
        cast(null as varchar)         as field,
        cast(null as varchar)         as well_type,
        cast(null as varchar)         as status,
        cast(null as date)            as spud_date,
        cast(null as double)          as latitude,
        cast(null as double)          as longitude
    from {{ ref('stg_petrinex_production') }} p
    left join aer using (uwi)
    where aer.uwi is null
      and p.activity_type = 'PROD'
      and p.product_type <> 'WATER'
)

select * from aer
union all
select * from residus
