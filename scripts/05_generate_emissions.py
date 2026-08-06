"""
05_generate_emissions.py : émissions Scope 1 (FACT_EMISSIONS)

Sortie : data/processed/fact_emissions.parquet

Facteurs issus de l'Inventaire national des GES du Canada (NIR 2024).
Calcule CO2, CH4 et CO2eq par puits et par mois à partir des volumes BOE réels de
petrinex24, avec une variance inter-puits de +/-10 %.

Les volumes viennent de production_universe : PROD, hors WATER, gaz remis à
l'échelle. Le facteur NIR exprime des tonnes de CO2 par boe produit, donc son
assiette doit être la production commercialisée, celle-là même qui sert de
dénominateur à l'intensité carbone affichée dans le rapport.

Les émissions ont d'abord été générées sur toutes les lignes, FUEL et VENT et
SHUTIN et WATER compris. Ça donnait 11 943 puits porteurs de 16,1 Mt de CO2 sans la
moindre production en face, et une intensité globale à 0,0597 au lieu de 0,0551.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from production_universe import charger_volumes_mensuels

# --------------------------------------------------------------------------- #
# Chemins ancrés sur la racine du projet
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent.parent
PETRINEX_PARQUET = ROOT / "data" / "processed" / "petrinex24.parquet"
OUT_PARQUET = ROOT / "data" / "processed" / "fact_emissions.parquet"
OUT_CSV = ROOT / "data" / "processed" / "fact_emissions.csv"

# --------------------------------------------------------------------------- #
# Facteurs d'émission, NIR 2024
# --------------------------------------------------------------------------- #
RNG_SEED = 42
FACTEUR_CO2_BOE = 0.055      # t CO2 / BOE — upstream O&G Alberta (NIR 2024).
                             # Total basin ~105 Mt CO2/an : cohérent avec
                             # l'intensité combustion+procédé amont publiée.
# FACTEUR_CH4 calibré pour reconstituer le méthane amont O&G de l'Alberta
# ~1,2 Mt CH4/an — réf. ligne de base NIR/AER 2014 (~31,4 Mt CO2e ÷ 25 ≈ 1,26
# Mt CH4). L'ancienne valeur 0,004 donnait ~7,7 Mt CH4/an (~6× trop) et poussait
# le CO2eq (~297 Mt/an) au-delà du total O&G provincial. Aucune donnée méthane par
# puits n'existe : on calibre donc le facteur sur le total publié (pas d'invention).
FACTEUR_CH4_BOE = 0.000625   # t CH4 / BOE  (-> ~1,2 Mt CH4/an sur le périmètre puits)
CO2EQ_CH4 = 28               # GWP100 CH4 (GIEC AR6 ; ~AR5). Standard reporting national.
VARIANCE_PUITS = 0.10        # +/-10 % variance inter-puits
SCOPE = "Scope1"


def main() -> int:
    print(f"Racine projet : {ROOT}")
    if not PETRINEX_PARQUET.exists():
        print(f"[ERREUR] Fichier requis absent : {PETRINEX_PARQUET}", file=sys.stderr)
        return 1

    rng = np.random.default_rng(RNG_SEED)

    # --- Volumes BOE mensuels par puits (périmètre canonique partagé) ------ #
    grp = charger_volumes_mensuels(PETRINEX_PARQUET)
    print(f"  Couples (puits, mois) avec production > 0 : {len(grp):,}")

    df = pd.DataFrame()
    df["uwi"] = grp["uwi"].astype("string")
    date = pd.to_datetime(grp["date"])
    df["date_key"] = (date.dt.year * 100 + date.dt.month).astype("int64")
    volume_boe = grp["volume_boe"].to_numpy(dtype="float64")
    n = len(df)

    # Variance inter-puits : facteur multiplicatif dans [1-v, 1+v].
    variance = 1.0 + rng.uniform(-VARIANCE_PUITS, VARIANCE_PUITS, n)

    df["co2_tonnes"] = volume_boe * FACTEUR_CO2_BOE * variance
    df["ch4_tonnes"] = volume_boe * FACTEUR_CH4_BOE * variance
    df["co2eq_total"] = df["co2_tonnes"] + df["ch4_tonnes"] * CO2EQ_CH4
    df["scope"] = SCOPE

    df = df[
        ["uwi", "date_key", "co2_tonnes", "ch4_tonnes", "co2eq_total", "scope"]
    ].reset_index(drop=True)

    # --- Contrôle qualité : intensité carbone ~ 0.055 tCO2/boe ------------ #
    total_co2 = df["co2_tonnes"].sum()
    total_boe = volume_boe.sum()
    intensite = total_co2 / total_boe if total_boe else 0.0
    print(f"  Intensité CO2 globale : {intensite:.4f} tCO2/boe  "
          f"(cible ~{FACTEUR_CO2_BOE})")

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PARQUET, index=False)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8")
    print(f"\nÉcrit : {OUT_PARQUET}  ({len(df):,} lignes)")
    print(f"Écrit : {OUT_CSV}")
    print(df.head().to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
