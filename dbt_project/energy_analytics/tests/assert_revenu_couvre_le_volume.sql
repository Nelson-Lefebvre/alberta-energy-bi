-- Tout produit qui porte du volume doit porter du revenu.
--
-- Ce test existe à cause d'un défaut qui a vécu longtemps sans être vu. Le revenu ne
-- valorisait que les liquides ; le gaz, 47,3 % du volume en boe, recevait zéro. Rien
-- ne signalait l'anomalie : la table était valide, les clés présentes, l'intégrité
-- référentielle intacte, et le total de revenu restait parfaitement plausible.
--
-- Ce qui était faux, c'est le rapport entre numérateur et dénominateur. « Revenu par
-- boe » divisait un revenu couvrant 53 % du volume par une production couvrant 100 %,
-- et affichait 43,00 $ là où le revenu unitaire réellement valorisé valait 81,57 $.
-- La marge, elle, imputait les coûts du gaz au seul revenu pétrolier.
--
-- Un contrôle sur le total n'aurait rien vu. Il faut descendre au produit, comme pour
-- l'OPEX, parce que c'est au produit que la règle de valorisation s'applique.
--
-- WATER est hors périmètre en amont (fact_production_enriched l'exclut), donc aucune
-- exception n'est nécessaire ici : tout ce qui reste doit être valorisé.

select
    product_type,
    sum(volume_boe)          as volume_boe,
    sum(revenu_estime_cad)   as revenu_estime_cad
from {{ ref('fact_production_enriched') }}
group by product_type
having sum(volume_boe) > 0
   and sum(revenu_estime_cad) <= 0
