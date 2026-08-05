"""
production_universe.py — Définition CANONIQUE du périmètre « production ».

Importé par 04_generate_costs.py et 05_generate_emissions.py pour que les coûts,
les émissions et le mart `fact_production_enriched` partagent EXACTEMENT le même
univers de volumes.

Pourquoi ce module existe : les ratios du dashboard (OPEX/boe, intensité carbone)
divisent un numérateur SIMULÉ par les scripts 04/05 par un dénominateur issu du
MART dbt. Si les deux côtés ne filtrent pas et ne redimensionnent pas les volumes
à l'identique, le ratio est faux sans qu'aucun test ne se déclenche. Cette
divergence s'est produite deux fois (correctif gaz absent de 04 ; filtre PROD
absent de 05) : la logique vit donc désormais à un seul endroit.

Deux règles, à garder synchronisées avec dbt :

  1. Correctif unité gaz (x1000) — cf. models/staging/stg_petrinex_production.sql
     Petrinex déclare le gaz en 10³m³ (e3m³), pas en m³ ; l'ingest 01 a converti
     en boe sans appliquer ce facteur.

  2. Filtre production commercialisée — cf. models/marts/fact_production_enriched.sql
     activity_type == 'PROD' et product_type != 'WATER' : exclut le gaz combustible
     (FUEL), torché/évacué (VENT), les puits fermés (SHUTIN) et l'eau produite.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# Périmètre partagé avec fact_production_enriched.sql — toute modification ici
# doit être répercutée dans le mart (et inversement).
ACTIVITY_TYPE_RETENU = "PROD"
PRODUCT_TYPES_EXCLUS = ("WATER",)
FACTEUR_ECHELLE_GAZ = 1000  # e3m³ -> m³


def charger_volumes_mensuels(petrinex_parquet: Path) -> pd.DataFrame:
    """Volumes BOE agrégés au grain (uwi, mois) sur le périmètre production.

    Retourne les colonnes ``uwi``, ``date``, ``volume_boe`` — gaz remis à
    l'échelle, lignes hors périmètre écartées, volumes nuls ou négatifs exclus.
    """
    prod = pd.read_parquet(
        petrinex_parquet,
        columns=["uwi", "date", "product_type", "activity_type", "volume_boe"],
    )
    prod = prod.dropna(subset=["uwi"])

    activity = prod["activity_type"].astype(str)
    product = prod["product_type"].astype(str)
    prod = prod[
        (activity == ACTIVITY_TYPE_RETENU) & (~product.isin(PRODUCT_TYPES_EXCLUS))
    ].copy()

    is_gas = prod["product_type"].astype(str) == "GAS"
    prod.loc[is_gas, "volume_boe"] = prod.loc[is_gas, "volume_boe"] * FACTEUR_ECHELLE_GAZ

    grp = (
        prod.groupby(["uwi", "date"], observed=True)["volume_boe"]
        .sum()
        .reset_index()
    )
    return grp[grp["volume_boe"] > 0].reset_index(drop=True)
