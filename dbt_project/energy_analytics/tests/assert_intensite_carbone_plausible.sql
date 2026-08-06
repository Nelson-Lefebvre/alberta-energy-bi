-- L'intensité carbone doit rester au voisinage du facteur NIR, RÉGION PAR RÉGION.
--
-- Le facteur d'émission est constant (0,055 tCO2/boe, cf. FACTEUR_CO2_BOE dans
-- scripts/05_generate_emissions.py) avec ±10 % de variance inter-puits. Toute région
-- qui s'en écarte signale non pas une performance carbone différente — le modèle n'en
-- contient aucune — mais une rupture entre le numérateur et le dénominateur.
--
-- C'est exactement ce qui s'est produit : les émissions étaient générées sur toutes les
-- lignes Petrinex (FUEL, VENT, SHUTIN, WATER inclus) alors que la production ne retient
-- que PROD hors WATER. Le bucket résiduel affichait 0,3589 — six fois la cible — et
-- tirait le global à 0,0597.
--
-- Là encore le grain est décisif : 0,0597 en global serait passé sous une borne large.
-- La bande est donc serrée et appliquée par région.

{% set intensite_min = 0.050 %}
{% set intensite_max = 0.060 %}

select
    region,
    sum(production_boe)                       as production_boe,
    sum(co2_tonnes)                           as co2_tonnes,
    sum(co2_tonnes) / sum(production_boe)     as intensite_carbone
from {{ ref('fact_kpis_mensuels') }}
group by region
having sum(production_boe) > 0
   and (
        sum(co2_tonnes) / sum(production_boe) < {{ intensite_min }}
     or sum(co2_tonnes) / sum(production_boe) > {{ intensite_max }}
   )
