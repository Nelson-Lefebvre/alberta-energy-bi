-- KPIs mensuels agrégés au grain (date_key x région) :
-- production, revenu, OPEX, CAPEX, CO2 + ratios phares (OPEX/boe, intensité carbone).
with prod as (
    select date_key, uwi,
           sum(volume_boe)        as volume_boe,
           sum(revenu_estime_cad) as revenu_estime_cad
    from {{ ref('fact_production_enriched') }}
    group by 1, 2
),

-- OPEX = coût d'exploitation récurrent -> conservé au grain mensuel.
opex as (
    select date_key, uwi, sum(opex_total) as opex_total
    from {{ ref('stg_costs') }}
    group by 1, 2
),

-- CAPEX = investissement PONCTUEL. La source génère une valeur capex pour chaque
-- couple (puits x mois) ; sommée telle quelle, elle gonflait le total à ~237 $/boe
-- (≈13x l'OPEX). On ne retient donc qu'UNE valeur par puits, rattachée à son
-- premier mois observé, pour ne la compter qu'une seule fois.
capex_unique as (
    select date_key, uwi, capex
    from (
        select date_key, uwi, capex,
               row_number() over (partition by uwi order by date_key) as rn
        from {{ ref('stg_costs') }}
    )
    where rn = 1
),

-- Production / OPEX / CAPEX agrégés au grain (date_key x région).
prod_region as (
    select
        p.date_key,
        -- Résidu non rattaché : ~1453 UWI (16 car.) qui produisent mais sont absents de
        -- dim_puits (extrait AER ST37 incomplet) → ~53 M boe (~1.4%). Aucune géo/région.
        coalesce(w.region, 'Puits hors référentiel AER') as region,
        sum(p.volume_boe)              as production_boe,
        sum(p.revenu_estime_cad)       as revenu_estime_cad,
        sum(coalesce(o.opex_total, 0)) as opex_total_cad,
        sum(coalesce(cx.capex, 0))     as capex_total_cad
    from prod p
    left join {{ ref('dim_puits') }} w using (uwi)
    left join opex o using (date_key, uwi)
    left join capex_unique cx using (date_key, uwi)
    group by 1, 2
),

-- CO2 au MÊME grain (date_key x région) et MÊME logique que fact_emissions_scope :
-- agrégé DIRECTEMENT depuis stg_emissions (pas via la production filtrée PROD), pour que
-- le total kpis (carte CO2 Scope 1) == total emissions_scope (barres ESG).
emissions_region as (
    select
        e.date_key,
        coalesce(w.region, 'Puits hors référentiel AER') as region,
        sum(e.co2_tonnes) as co2_tonnes
    from {{ ref('stg_emissions') }} e
    left join {{ ref('dim_puits') }} w using (uwi)
    group by 1, 2
)

select
    pr.date_key,
    pr.region,
    pr.production_boe,
    pr.revenu_estime_cad,
    pr.opex_total_cad,
    pr.capex_total_cad,
    coalesce(em.co2_tonnes, 0) as co2_tonnes,
    case when pr.production_boe > 0
         then pr.opex_total_cad / pr.production_boe end as opex_par_boe,
    case when pr.production_boe > 0
         then coalesce(em.co2_tonnes, 0) / pr.production_boe end as intensite_carbone
from prod_region pr
left join emissions_region em using (date_key, region)
