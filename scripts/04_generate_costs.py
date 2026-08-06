"""
04_generate_costs.py : coûts opératoires simulés (FACT_COUTS)

Sortie : data/processed/fact_couts.parquet

Données SIMULÉES, avec des fourchettes reprises de l'AER Annual Report 2023.
Génère OPEX (forage + maintenance) et CAPEX par puits et par mois, à partir des
volumes BOE réels de petrinex24 et des dates de spud de dim_puits.

Règles de génération :
  - opex_forage      ~ Normal(mu=12, sigma=2)   $/boe  x volume_boe du mois
  - opex_maintenance ~ Normal(mu=4,  sigma=1.5) $/boe  x volume_boe du mois
  - capex            ~ Log-normal ; puits récents (< 3 ans) -> CAPEX plus élevé
  - saisonnalité     : OPEX x 1.15 en jan/fev/mars (coûts hivernaux canadiens)
  - incidents        : 5 % des puits/mois -> OPEX x 2.0 (arrêt non planifié)
  - devise           : "CAD"

Les volumes viennent de production_universe, donc du même périmètre que le mart.
Quand ce n'était pas le cas, l'OPEX se calculait sur des volumes gaz 1000 fois trop
petits pendant que le dénominateur du ratio OPEX/boe, lui, était corrigé. Résultat :
4 $/boe dans les régions gazières contre 14,5 $ au Nord, un écart qui ressemblait à
une vraie différence de structure de coûts et n'était qu'un problème d'unité.
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
DIM_PUITS_PARQUET = ROOT / "data" / "processed" / "dim_puits.parquet"
OUT_PARQUET = ROOT / "data" / "processed" / "fact_couts.parquet"
OUT_CSV = ROOT / "data" / "processed" / "fact_couts.csv"

# --------------------------------------------------------------------------- #
# Paramètres de simulation — AER Annual Report 2023
# --------------------------------------------------------------------------- #
RNG_SEED = 42

OPEX_FORAGE_MU, OPEX_FORAGE_SIGMA = 12.0, 2.0        # $/boe
OPEX_MAINT_MU, OPEX_MAINT_SIGMA = 4.0, 1.5           # $/boe

CAPEX_LOGNORM_MEAN, CAPEX_LOGNORM_SIGMA = 11.5, 0.6  # log-espace ($CAD)
CAPEX_RECENT_MULT = 2.5                               # puits < 3 ans
CAPEX_RECENT_YEARS = 3

WINTER_MONTHS = (1, 2, 3)
WINTER_MULT = 1.15
INCIDENT_RATE = 0.05
INCIDENT_MULT = 2.0

OPEX_MIN, OPEX_MAX = 8.0, 30.0  # garde-fou $/boe (checklist §13)


def main() -> int:
    print(f"Racine projet : {ROOT}")
    for path in (PETRINEX_PARQUET, DIM_PUITS_PARQUET):
        if not path.exists():
            print(f"[ERREUR] Fichier requis absent : {path}", file=sys.stderr)
            return 1

    rng = np.random.default_rng(RNG_SEED)

    # --- Volumes BOE mensuels par puits (périmètre canonique partagé) ------ #
    grp = charger_volumes_mensuels(PETRINEX_PARQUET)
    print(f"  Couples (puits, mois) avec production > 0 : {len(grp):,}")

    df = pd.DataFrame()
    df["uwi"] = grp["uwi"].astype("string")
    df["date"] = pd.to_datetime(grp["date"])
    df["date_key"] = (df["date"].dt.year * 100 + df["date"].dt.month).astype("int64")
    volume_boe = grp["volume_boe"].to_numpy(dtype="float64")
    n = len(df)

    # --- OPEX $/boe (tronqué à >= 0 avant multiplicateurs) ---------------- #
    forage_rate = np.clip(rng.normal(OPEX_FORAGE_MU, OPEX_FORAGE_SIGMA, n), 0, None)
    maint_rate = np.clip(rng.normal(OPEX_MAINT_MU, OPEX_MAINT_SIGMA, n), 0, None)

    # Saisonnalité hivernale. np.select plutôt qu'un apply : 3,3 M de lignes.
    month = df["date"].dt.month.to_numpy()
    season_mult = np.select([np.isin(month, WINTER_MONTHS)], [WINTER_MULT], default=1.0)

    # Incidents : 5 % des couples puits/mois.
    incident_mult = np.where(
        rng.random(n) < INCIDENT_RATE, INCIDENT_MULT, 1.0
    )

    total_mult = season_mult * incident_mult
    forage_rate = forage_rate * total_mult
    maint_rate = maint_rate * total_mult

    df["opex_forage"] = forage_rate * volume_boe
    df["opex_maintenance"] = maint_rate * volume_boe

    # --- CAPEX (log-normal, majoré pour les puits récents) ---------------- #
    spud = pd.read_parquet(DIM_PUITS_PARQUET, columns=["uwi", "spud_date"])
    spud["uwi"] = spud["uwi"].astype("string")
    df = df.merge(spud, on="uwi", how="left")

    age_years = (df["date"] - df["spud_date"]).dt.days / 365.25
    recent = (age_years < CAPEX_RECENT_YEARS).fillna(False).to_numpy()

    capex_base = rng.lognormal(CAPEX_LOGNORM_MEAN, CAPEX_LOGNORM_SIGMA, n)
    capex_mult = np.select([recent], [CAPEX_RECENT_MULT], default=1.0)
    df["capex"] = capex_base * capex_mult
    df = df.drop(columns=["spud_date"])

    df["devise"] = "CAD"

    # --- Contrôle qualité OPEX/boe ---------------------------------------- #
    opex_total = df["opex_forage"] + df["opex_maintenance"]
    opex_par_boe = np.divide(
        opex_total, volume_boe, out=np.zeros_like(opex_total), where=volume_boe > 0
    )
    p05, p95 = np.percentile(opex_par_boe, [5, 95])
    print(f"  OPEX/boe — p05={p05:.2f}  médiane={np.median(opex_par_boe):.2f}  "
          f"p95={p95:.2f}  (cible $8-30/boe, hors incidents)")

    df = df[
        ["uwi", "date_key", "opex_forage", "opex_maintenance", "capex", "devise"]
    ].reset_index(drop=True)

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PARQUET, index=False)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8")
    print(f"\nÉcrit : {OUT_PARQUET}  ({len(df):,} lignes)")
    print(f"Écrit : {OUT_CSV}")
    print(df.head().to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
