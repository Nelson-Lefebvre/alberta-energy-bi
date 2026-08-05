-- Fait production enrichi (cf. CLAUDE.md §9.4) : revenu estimé via WCS CAD,
-- production cumulée par puits, et OPEX / CO2 ramenés au grain de la ligne.
--
-- Pourquoi l'OPEX et le CO2 vivent ICI et plus seulement dans fact_kpis_mensuels :
-- ce dernier est agrégé au grain (mois x région). Aucun filtre plus fin — opérateur,
-- statut, uwi, type de produit — ne peut l'atteindre, car dim_puits est du côté
-- « plusieurs » de dim_region et ne propage donc rien vers les agrégats. Sur la page
-- P1, sélectionner un opérateur faisait bouger Production et Revenu mais laissait
-- « OPEX par boe » et « Intensité carbone » à leur valeur globale, sans aucun signal
-- visuel. Porter ces deux mesures sur ce fait-ci les rend filtrables comme le reste.
with production as (
    select
        p.date_key,
        p.uwi,
        p.product_type,
        p.activity_type,
        p.volume_boe,
        p.volume_brut
    from {{ ref('stg_petrinex_production') }} p
    -- Production VENDUE uniquement : on exclut le gaz combustible (FUEL), torché/évacué
    -- (VENT) et les puits fermés (SHUTIN) — ce n'est pas de la production commercialisée.
    -- Effet : retire ~298 M boe de fuel/vent (déclaré au niveau installation, uwi 7 car.)
    -- et vide quasi tout l'ancien bucket « Inconnu ».
    where p.activity_type = 'PROD'
    -- Exclut l'eau produite (WATER) : convertie à ~0 boe, c'était une option morte du
    -- slicer produit (0 production, 0 revenu). Pas de la production commercialisable.
      and p.product_type <> 'WATER'
),

-- Poids de chaque ligne (un produit) dans le total du couple (puits, mois), qui est
-- le grain auquel les scripts 04/05 simulent les coûts et les émissions.
repartition as (
    select
        *,
        sum(volume_boe) over (partition by uwi, date_key) as volume_boe_puits_mois
    from production
),

couts as (
    select date_key, uwi, sum(opex_total) as opex_total
    from {{ ref('stg_costs') }}
    group by 1, 2
),

emissions as (
    select date_key, uwi, sum(co2_tonnes) as co2_tonnes
    from {{ ref('stg_emissions') }}
    group by 1, 2
)

select
    r.date_key,
    r.uwi,
    r.product_type,
    r.activity_type,
    r.volume_boe,
    r.volume_brut,
    prix.wcs_cad,
    -- WCS = benchmark pétrole lourd (liquides). Aucun prix gaz (AECO) dans le modèle :
    -- on ne valorise QUE les liquides (OIL/COND). Sans ça, le gaz corrigé serait
    -- valorisé au prix du pétrole (~×4-5 trop cher).
    case when r.product_type in ('OIL', 'COND')
         then r.volume_boe * prix.wcs_cad
         else 0 end                              as revenu_estime_cad,
    -- Répartition au prorata du volume. Elle est EXACTE, pas approchée : les scripts
    -- 04/05 calculent opex = taux x volume et co2 = facteur x volume, avec un taux et
    -- un facteur constants sur le couple (puits, mois). Redistribuer proportionnellement
    -- au volume reconstitue donc la valeur par produit à l'identique.
    coalesce(
        c.opex_total * r.volume_boe / nullif(r.volume_boe_puits_mois, 0), 0
    )                                            as opex_cad,
    coalesce(
        e.co2_tonnes * r.volume_boe / nullif(r.volume_boe_puits_mois, 0), 0
    )                                            as co2_tonnes,
    sum(r.volume_boe) over (
        partition by r.uwi
        order by r.date_key
    )                                            as production_cumulative_boe
from repartition r
left join {{ ref('stg_eia_prices') }} prix using (date_key)
left join couts c using (date_key, uwi)
left join emissions e using (date_key, uwi)
