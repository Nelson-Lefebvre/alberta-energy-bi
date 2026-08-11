-- L'OPEX par baril doit rester dans la fourchette de simulation, PRODUIT PAR PRODUIT.
--
-- Ce test a changé de grain, et la raison mérite d'être lue avant de le modifier.
--
-- Version précédente : le contrôle portait sur la RÉGION, et son argument était que
-- l'OPEX/boe devait être plat d'une région à l'autre. C'était vrai tant que le script
-- 04 appliquait un taux unique à toutes les molécules — un écart régional ne pouvait
-- alors venir que d'un défaut, et c'est ainsi que le bug d'unités gaz a été pris.
--
-- Depuis que le taux dépend du produit (~6 $/boe pour le gaz, ~20 $ pour les liquides),
-- l'OPEX/boe régional est devenu une fonction légitime du mix :
--
--     Central      76,9 % de gaz   ->  10,05 $
--     Peace River  76,5 % de gaz   ->  10,13 $
--     Sud          74,9 % de gaz   ->  10,44 $
--     Nord         17,1 % de gaz   ->  19,22 $
--
-- Un test régional serré n'aurait donc plus de sens : il refuserait une variation
-- attendue. Le contrôle remonte au niveau où le taux est effectivement défini, le
-- produit, où la bande peut rester étroite et donc mordante.
--
-- Bornes : cf. OPEX_TAUX dans scripts/04_generate_costs.py. Elles encadrent le taux
-- moyen de chaque famille en laissant passer les multiplicateurs saisonnier (x1,15)
-- et incident (x2,0), qui ne touchent que 5 % des lignes et ne déplacent la moyenne
-- pondérée que de quelques pourcents.

{% set bandes = [
    ('OIL',  15.0, 30.0),
    ('COND', 15.0, 30.0),
    ('GAS',   4.0, 10.0)
] %}

with par_produit as (
    select
        product_type,
        sum(volume_boe)               as volume_boe,
        sum(opex_cad)                 as opex_cad,
        sum(opex_cad) / nullif(sum(volume_boe), 0) as opex_par_boe
    from {{ ref('fact_production_enriched') }}
    group by product_type
)

select product_type, volume_boe, opex_cad, opex_par_boe
from par_produit
where volume_boe > 0
  and (
    {% for produit, mini, maxi in bandes %}
    (product_type = '{{ produit }}'
     and (opex_par_boe < {{ mini }} or opex_par_boe > {{ maxi }}))
    {%- if not loop.last %} or {% endif %}
    {% endfor %}
  )
