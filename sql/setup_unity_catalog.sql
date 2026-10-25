-- sql/setup_unity_catalog.sql
-- À exécuter une seule fois, dans le SQL Editor, sur le Serverless Starter Warehouse.
-- Free Edition fournit le catalogue « workspace » : les trois couches y vivent.

CREATE SCHEMA IF NOT EXISTS workspace.alberta_bronze
  COMMENT 'Volume landing (fichiers) et sorties des scripts 01 à 05 en tables Delta';

CREATE SCHEMA IF NOT EXISTS workspace.alberta_silver
  COMMENT 'Vues dbt de staging (stg_*)';

CREATE SCHEMA IF NOT EXISTS workspace.alberta_gold
  COMMENT 'Marts dbt lus par Power BI';

-- Un Volume est un dossier de fichiers gouverné par Unity Catalog.
-- Chemin : /Volumes/workspace/alberta_bronze/landing/{raw,processed}
CREATE VOLUME IF NOT EXISTS workspace.alberta_bronze.landing
  COMMENT 'raw/ : ST37 et référentiels Petrinex ; processed/ : Parquet des scripts';
