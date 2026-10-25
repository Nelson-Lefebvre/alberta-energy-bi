-- sql/load_bronze.sql
-- Couche bronze : une table Delta par Parquet produit par les scripts 01 à 05.
--
-- CREATE OR REPLACE remplace la table en une seule transaction Delta. Pendant le
-- chargement, dbt et Power BI lisent la version précédente : ils ne voient jamais
-- une table à moitié écrite. Les versions passées restent lisibles avec
-- DESCRIBE HISTORY et SELECT ... VERSION AS OF n.
--
-- schemaEvolutionMode => 'none' : pas de colonne _rescued_data, le schéma vient
-- des Parquet que les scripts typent déjà.
-- datetimeRebaseMode => 'CORRECTED' : pyarrow écrit les dates en calendrier
-- grégorien proleptique ; inutile de les « rebaser » depuis le calendrier julien.

CREATE OR REPLACE TABLE workspace.alberta_bronze.petrinex24 AS
SELECT * FROM read_files(
  '/Volumes/workspace/alberta_bronze/landing/processed/petrinex24.parquet',
  format => 'parquet',
  schemaEvolutionMode => 'none',
  datetimeRebaseMode => 'CORRECTED'
);

CREATE OR REPLACE TABLE workspace.alberta_bronze.dim_puits AS
SELECT * FROM read_files(
  '/Volumes/workspace/alberta_bronze/landing/processed/dim_puits.parquet',
  format => 'parquet',
  schemaEvolutionMode => 'none',
  datetimeRebaseMode => 'CORRECTED'
);

CREATE OR REPLACE TABLE workspace.alberta_bronze.dim_prix AS
SELECT * FROM read_files(
  '/Volumes/workspace/alberta_bronze/landing/processed/dim_prix.parquet',
  format => 'parquet',
  schemaEvolutionMode => 'none',
  datetimeRebaseMode => 'CORRECTED'
);

CREATE OR REPLACE TABLE workspace.alberta_bronze.fact_couts AS
SELECT * FROM read_files(
  '/Volumes/workspace/alberta_bronze/landing/processed/fact_couts.parquet',
  format => 'parquet',
  schemaEvolutionMode => 'none',
  datetimeRebaseMode => 'CORRECTED'
);

CREATE OR REPLACE TABLE workspace.alberta_bronze.fact_emissions AS
SELECT * FROM read_files(
  '/Volumes/workspace/alberta_bronze/landing/processed/fact_emissions.parquet',
  format => 'parquet',
  schemaEvolutionMode => 'none',
  datetimeRebaseMode => 'CORRECTED'
);
