"""
Définition unique du périmètre de production.

Les scripts 04 et 05 importent ce module pour que les coûts, les émissions et le
mart fact_production_enriched travaillent sur exactement les mêmes volumes.

L'enjeu : OPEX/boe et intensité carbone divisent un numérateur simulé ici par un
dénominateur qui vient du mart dbt. Si un côté filtre ou redimensionne les volumes
autrement que l'autre, le ratio est faux et rien ne le signale, parce que les tables
restent parfaitement valides. C'est arrivé deux fois, une par règle ci-dessous.

Ces deux règles doivent rester alignées sur leurs équivalents dbt :

  1. Échelle du gaz (x1000), cf. models/staging/stg_petrinex_production.sql
     Petrinex déclare le gaz en 10³m³, pas en m³. Le script 01 convertit en boe
     sans appliquer ce facteur.

  2. Production commercialisée, cf. models/marts/fact_production_enriched.sql
     activity_type == 'PROD' et product_type != 'WATER'. Exclut le gaz combustible
     (FUEL), le gaz torché ou évacué (VENT), les puits fermés (SHUTIN) et l'eau.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# Ces trois constantes ont un miroir dans fact_production_enriched.sql.
# Changer l'une sans l'autre casse silencieusement les ratios du rapport.
ACTIVITY_TYPE_RETENU = "PROD"
PRODUCT_TYPES_EXCLUS = ("WATER",)
FACTEUR_ECHELLE_GAZ = 1000  # e3m³ vers m³


def charger_volumes_mensuels(
    petrinex_parquet: Path, par_produit: bool = False
) -> pd.DataFrame:
    """Volumes BOE agrégés par puits et par mois, sur le périmètre production.

    Renvoie uwi, date et volume_boe : gaz remis à l'échelle, lignes hors périmètre
    écartées, volumes nuls ou négatifs exclus.

    Avec par_produit=True, product_type entre dans les clés d'agrégation. Le script 04
    en a besoin : un baril de gaz et un baril de pétrole n'ont pas le même coût
    opératoire, et 68,6 % du volume vient de couples (puits, mois) qui produisent les
    deux. Un taux unique par puits-mois y serait un mélange, pas un coût.
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

    cles = ["uwi", "date", "product_type"] if par_produit else ["uwi", "date"]
    grp = (
        prod.groupby(cles, observed=True)["volume_boe"]
        .sum()
        .reset_index()
    )
    return grp[grp["volume_boe"] > 0].reset_index(drop=True)
