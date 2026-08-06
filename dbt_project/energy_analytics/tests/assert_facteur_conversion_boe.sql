-- Le rapport volume_boe / volume_brut doit valoir la constante de conversion du produit.
--
-- Petrinex déclare les liquides en m³ et le gaz en 10³m³ (e3m³). La conversion en BOE
-- doit donc appliquer un facteur d'échelle supplémentaire de 1000 au seul gaz :
--   liquides (OIL, COND) : 1 m³    -> 6,290 boe
--   gaz      (GAS)       : 1 e3m³  -> 5,885 boe   (= 1000 / 169,9)
--
-- Sans le ×1000, le gaz ressortait à 0,005885 boe par unité, soit mille fois trop peu.
-- Ce test verrouille le correctif : si quelqu'un retire le facteur de
-- stg_petrinex_production.sql ou de production_universe.py, le ratio gaz s'effondre et
-- le test échoue immédiatement, au lieu de se propager en silence dans l'OPEX/boe.

with attendu as (
    select 'OIL'  as product_type, 6.290 as ratio union all
    select 'COND',                 6.290           union all
    select 'GAS',                  5.885
),

observe as (
    select
        product_type,
        min(volume_boe / volume_brut) as ratio_min,
        max(volume_boe / volume_brut) as ratio_max
    from {{ ref('fact_production_enriched') }}
    where volume_brut > 0
    group by 1
)

select
    o.product_type,
    o.ratio_min,
    o.ratio_max,
    a.ratio as ratio_attendu
from observe o
join attendu a using (product_type)
-- tolérance large : on cherche une erreur d'échelle (facteur 1000), pas un arrondi
where abs(o.ratio_min - a.ratio) > 0.01
   or abs(o.ratio_max - a.ratio) > 0.01
