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
    select
        uwi,
        cast(null as varchar)         as operator_name,
        cast(null as varchar)         as area,
        'Puits hors référentiel AER'  as region,
        cast(null as varchar)         as field,
        cast(null as varchar)         as well_type,
        cast(null as varchar)         as status,
        cast(null as date)            as spud_date,
        cast(null as double)          as latitude,
        cast(null as double)          as longitude
    from (
        select
            p.uwi,
            -- Power BI matche les clés en INSENSIBLE à la casse/espaces, alors que le
            -- join DuckDB est sensible. On compare/dédoublonne donc en NORMALISÉ
            -- (upper+trim) pour ne PAS ré-ajouter un uwi déjà dans l'AER sous une casse
            -- différente (ex. ...W400 vs ...w400) -> sinon doublon clé côté PBI.
            row_number() over (partition by upper(trim(p.uwi)) order by p.uwi) as rn
        from {{ ref('stg_petrinex_production') }} p
        where p.activity_type = 'PROD'
          and p.product_type <> 'WATER'
          and upper(trim(p.uwi)) not in (select upper(trim(uwi)) from aer)
    )
    where rn = 1
)

select * from aer
union all
select * from residus
