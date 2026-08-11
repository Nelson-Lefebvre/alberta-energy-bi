-- Garde-fou du périmètre des émissions, version bornée.
--
-- Le script 05 dérive les émissions des volumes FUEL, VENT et FLARE déclarés à
-- Petrinex. Deux catégories sortent légitimement du périmètre de production :
--
--   * les codes d'installation, sept caractères, qui ne sont pas des puits et
--     n'existent pas dans dim_puits. Ils portent environ 4,8 % du CO2eq et sont
--     exclus de ce test par construction ;
--   * les puits fermés qui éventent sans produire ce mois-là. Physiquement réels,
--     et marginaux : environ 0,03 % du CO2eq.
--
-- Ce que ce test protège, c'est la régression de juillet 2026 : une règle de
-- périmètre oubliée qui avait mis 16,1 Mt de CO2 sur 11 943 puits sans production,
-- soit 6,3 % du total, et gonflé l'intensité de 0,0551 à 0,0597. Le seuil de 1 %
-- laisse passer le résiduel physique et arrête net ce type d'erreur.
--
-- Une égalité stricte des univers n'a plus de sens ici : elle vaut pour les coûts,
-- toujours simulés depuis la production, et c'est assert_univers_partages qui la
-- tient.

with production as (
    select distinct uwi, date_key from {{ ref('fact_production_enriched') }}
),

emissions as (
    select uwi, date_key, co2eq_total from {{ ref('stg_emissions') }}
),

orphelines as (
    select e.co2eq_total
    from emissions e
    left join production p
        on p.uwi = e.uwi
       and p.date_key = e.date_key
    where p.uwi is null
      and length(e.uwi) = 16
),

bilan as (
    select
        (select coalesce(sum(co2eq_total), 0) from orphelines) as co2eq_hors_production,
        (select sum(co2eq_total) from emissions)               as co2eq_total
)

select
    'emissions au grain puits sans production en face' as anomalie,
    co2eq_hors_production,
    co2eq_total,
    co2eq_hors_production / nullif(co2eq_total, 0) as part
from bilan
where co2eq_hors_production / nullif(co2eq_total, 0) > 0.01
