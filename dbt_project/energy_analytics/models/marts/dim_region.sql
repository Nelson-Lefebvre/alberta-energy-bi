-- Dimension Région conforme : valeurs distinctes présentes dans les DEUX faits
-- non reliés entre eux — dim_puits (côté production/fact_production_enriched) et
-- fact_kpis_mensuels (agrégats région×mois). Sert de dimension partagée pour que
-- le slicer région filtre À LA FOIS Prod/Revenu (via dim_puits→production) ET
-- Intensité/OPEX/CO2 (via fact_kpis). 'union' (pas 'union all') dédoublonne.
select region from {{ ref('dim_puits') }}
union
select region from {{ ref('fact_kpis_mensuels') }}
