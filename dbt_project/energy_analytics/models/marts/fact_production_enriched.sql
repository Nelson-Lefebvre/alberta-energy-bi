-- Fait production enrichi (cf. CLAUDE.md §9.4) : revenu estimé via WCS CAD
-- et production cumulée par puits.
select
    p.date_key,
    p.uwi,
    p.product_type,
    p.activity_type,
    p.volume_boe,
    p.volume_brut,
    prix.wcs_cad,
    -- WCS = benchmark pétrole lourd (liquides). Aucun prix gaz (AECO) dans le modèle :
    -- on ne valorise QUE les liquides (OIL/COND). Sans ça, le gaz corrigé serait
    -- valorisé au prix du pétrole (~×4-5 trop cher).
    case when p.product_type in ('OIL', 'COND')
         then p.volume_boe * prix.wcs_cad
         else 0 end                              as revenu_estime_cad,
    sum(p.volume_boe) over (
        partition by p.uwi
        order by p.date_key
    )                                            as production_cumulative_boe
from {{ ref('stg_petrinex_production') }} p
left join {{ ref('stg_eia_prices') }} prix using (date_key)
-- Production VENDUE uniquement : on exclut le gaz combustible (FUEL), torché/évacué
-- (VENT) et les puits fermés (SHUTIN) — ce n'est pas de la production commercialisée.
-- Effet : retire ~298 M boe de fuel/vent (déclaré au niveau installation, uwi 7 car.)
-- et vide quasi tout l'ancien bucket « Inconnu ».
where p.activity_type = 'PROD'
-- Exclut l'eau produite (WATER) : convertie à ~0 boe, c'était une option morte du
-- slicer produit (0 production, 0 revenu). Pas de la production commercialisable.
  and p.product_type <> 'WATER'
