-- Coûts, émissions et production doivent couvrir EXACTEMENT le même ensemble de
-- couples (puits, mois).
--
-- C'est le test de la cause racine. Les deux régressions de juillet 2026 étaient la
-- même erreur : une règle de périmètre appliquée dans une branche du pipeline mais pas
-- dans ses sœurs.
--   * 04_generate_costs.py ne filtrait pas PROD / hors WATER
--   * 05_generate_emissions.py non plus, d'où 11 943 puits porteurs de 16,1 Mt de CO2
--     sans production au dénominateur, et une intensité gonflée à 0,0597
--
-- Aucun test structurel ne pouvait les voir : les tables étaient valides, les clés
-- présentes, l'intégrité référentielle intacte. Seule la comparaison des univers entre
-- eux révèle l'écart. Le périmètre canonique vit dans scripts/production_universe.py.

with production as (
    select distinct uwi, date_key from {{ ref('fact_production_enriched') }}
),

couts as (
    select distinct uwi, date_key from {{ ref('stg_costs') }}
),

emissions as (
    select distinct uwi, date_key from {{ ref('stg_emissions') }}
),

ecarts as (

    select 'cout sans production'      as anomalie, uwi, date_key
    from couts
    except all
    select 'cout sans production', uwi, date_key from production

    union all

    select 'production sans cout', uwi, date_key from production
    except all
    select 'production sans cout', uwi, date_key from couts

    union all

    select 'emission sans production', uwi, date_key from emissions
    except all
    select 'emission sans production', uwi, date_key from production

    union all

    select 'production sans emission', uwi, date_key from production
    except all
    select 'production sans emission', uwi, date_key from emissions

)

select * from ecarts
