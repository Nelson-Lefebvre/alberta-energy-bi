-- Le CO2eq alloué doit rester cohérent avec le CO2 alloué, sur la même base.
--
-- La page ESG affiche « CO2 Scope 1 » et « CO2 eq total » côte à côte, en invitant à
-- vérifier la conversion de tête : CO2eq = CO2 + CH4 x 28. Cette lecture n'était pas
-- possible, parce que les deux cartes ne lisaient pas le même fait — Scope 1 venait de
-- fact_production_enriched, après allocation aux puits producteurs, et CO2 eq de
-- fact_emissions_scope, avant allocation. 91,2 Mt contre 103,5 Mt : l'écart n'était pas
-- du méthane, c'étaient 5,0 Mt déclarées par des installations dont l'opérateur n'avait
-- aucun puits producteur ce mois-là et que l'allocation ne pouvait poser nulle part.
--
-- Les deux mesures lisent désormais le fait alloué. Ce test verrouille la relation :
-- le CO2eq doit dépasser le CO2 (le méthane ne peut qu'ajouter) sans le dépasser
-- absurdement (le CH4 pèse quelques pourcents du total en Alberta, la borne haute est
-- large à dessein et n'attrape qu'une erreur de facteur ou une inversion de colonnes).

{% set ratio_min = 1.0 %}
{% set ratio_max = 1.5 %}

with controle as (
    select
        sum(co2_tonnes)   as co2_tonnes,
        sum(co2eq_tonnes) as co2eq_tonnes,
        sum(co2eq_tonnes) / nullif(sum(co2_tonnes), 0) as ratio
    from {{ ref('fact_production_enriched') }}
)

select *
from controle
where co2_tonnes > 0
  and (ratio < {{ ratio_min }} or ratio > {{ ratio_max }})
