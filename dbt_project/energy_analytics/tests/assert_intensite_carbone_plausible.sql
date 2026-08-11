-- L'intensité carbone doit rester physiquement plausible, RÉGION PAR RÉGION.
--
-- Ce test a changé de prémisse en même temps que le script 05. Tant que les émissions
-- étaient un facteur constant appliqué au volume produit, toute région s'écartant de
-- 0,055 signalait une rupture numérateur/dénominateur, puisque le modèle ne contenait
-- aucune différence de performance carbone. La bande était donc serrée à ±10 %.
--
-- Les émissions viennent désormais des volumes FUEL, VENT et FLARE déclarés à
-- Petrinex. L'écart entre régions est maintenant une mesure, pas un symptôme : le Nord
-- ressort à 0,0333 parce que la production in situ brûle beaucoup de gaz combustible,
-- Peace River à 0,0179. Serrer la bande reviendrait à interdire le signal qu'on
-- cherchait à obtenir.
--
-- Ce que le test protège encore, c'est la rupture de périmètre. Elle se manifeste de
-- deux façons, toutes deux couvertes ici :
--
--   1. une région bascule hors de toute plausibilité physique. La combustion déclarée
--      d'une région productrice tient dans [0,005 ; 0,080] tCO2/boe ; en juillet 2026
--      le seau résiduel affichait 0,3589 ;
--   2. la masse part dans le seau « hors référentiel AER ». Ce seau porte légitimement
--      les installations midstream, à 6,8 % du CO2 aujourd'hui, mais il ne doit pas
--      devenir le réceptacle d'une jointure cassée.
--
-- Valeurs de référence au moment de l'écriture : global 0,0271 ; Nord 0,0333 ;
-- Sud 0,0201 ; Central 0,0187 ; Peace River 0,0179 ; résiduel 0,1208.

{% set intensite_min = 0.005 %}
{% set intensite_max = 0.080 %}
{% set part_residuelle_max = 0.10 %}
{% set seau_residuel = 'Puits hors référentiel AER' %}

with par_region as (
    select
        region,
        sum(production_boe) as production_boe,
        sum(co2_tonnes)     as co2_tonnes
    from {{ ref('fact_kpis_mensuels') }}
    group by region
),

hors_bande as (
    select
        region,
        production_boe,
        co2_tonnes,
        co2_tonnes / production_boe as intensite_carbone,
        'intensite hors bande physique' as anomalie
    from par_region
    where region <> '{{ seau_residuel }}'
      and production_boe > 0
      and (
            co2_tonnes / production_boe < {{ intensite_min }}
         or co2_tonnes / production_boe > {{ intensite_max }}
      )
),

residuel as (
    select
        region,
        production_boe,
        co2_tonnes,
        co2_tonnes / nullif(production_boe, 0) as intensite_carbone,
        'seau residuel trop lourd' as anomalie
    from par_region
    where region = '{{ seau_residuel }}'
      and co2_tonnes > {{ part_residuelle_max }} * (select sum(co2_tonnes) from par_region)
)

select * from hors_bande
union all
select * from residuel
