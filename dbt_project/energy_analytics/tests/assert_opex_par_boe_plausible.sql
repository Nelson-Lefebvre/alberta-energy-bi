-- L'OPEX par baril doit rester dans la fourchette de simulation, RÉGION PAR RÉGION.
--
-- Le grain compte, et c'est tout l'enseignement du bug de juillet 2026. Le ratio
-- GLOBAL valait alors 9,21 $ — à l'intérieur de la bande 8–30, donc invisible pour un
-- contrôle agrégé. C'est la ventilation par région qui trahissait le défaut :
--
--     Nord         16,9 % de gaz   ->  14,52 $
--     Peace River  76,7 % de gaz   ->   4,08 $
--     Central      76,9 % de gaz   ->   4,03 $
--
-- L'OPEX/boe était une fonction inverse parfaite de la part de gaz, parce que le
-- numérateur était calculé sur des volumes gaz non redimensionnés et le dénominateur
-- sur des volumes corrigés. Trois régions sous le plancher de 8 $ : ce test-ci
-- l'aurait arrêté net.
--
-- Bornes : cf. OPEX_MIN / OPEX_MAX dans scripts/04_generate_costs.py.

{% set opex_min = 8.0 %}
{% set opex_max = 30.0 %}

select
    region,
    sum(production_boe)                          as production_boe,
    sum(opex_total_cad)                          as opex_total_cad,
    sum(opex_total_cad) / sum(production_boe)    as opex_par_boe
from {{ ref('fact_kpis_mensuels') }}
group by region
having sum(production_boe) > 0
   and (
        sum(opex_total_cad) / sum(production_boe) < {{ opex_min }}
     or sum(opex_total_cad) / sum(production_boe) > {{ opex_max }}
   )
