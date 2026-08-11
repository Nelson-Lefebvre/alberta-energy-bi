"""
04_generate_costs.py : coûts opératoires simulés (FACT_COUTS)

Sortie : data/processed/fact_couts.parquet

Données SIMULÉES, avec des fourchettes reprises de l'AER Annual Report 2023.
Génère OPEX (forage + maintenance) et CAPEX par puits et par mois, à partir des
volumes BOE réels de petrinex24 et des dates de spud de dim_puits.

Règles de génération :
  - opex_forage      ~ Normal, taux propre au produit, x volume_boe du mois
  - opex_maintenance ~ Normal, taux propre au produit, x volume_boe du mois
  - capex            ~ Log-normal ; puits récents (< 3 ans) -> CAPEX plus élevé
  - saisonnalité     : OPEX x 1.15 en jan/fev/mars (coûts hivernaux canadiens)
  - incidents        : 5 % des puits/mois -> OPEX x 2.0 (arrêt non planifié)
  - devise           : "CAD"

POURQUOI UN TAUX PAR PRODUIT
----------------------------
La version précédente appliquait le même taux, ~16 $/boe, à toutes les molécules. Tant
que le gaz ne portait aucun revenu, l'incohérence restait invisible. Depuis que le prix
gaz albertain est ingéré, le gaz rapporte 1,346 CAD/GJ x 6,34 GJ = 8,53 CAD/boe : un
taux unique le rendait déficitaire à -105 %, ce qui est un artefact du modèle de coût,
pas un résultat.

Un baril équivalent de gaz sec ne coûte pas ce que coûte un baril de pétrole lourd. Les
ordres de grandeur retenus, en $CAD/boe :

  liquides (OIL, COND)  ~20   soit ~20 $/bbl, gamme conventionnelle albertaine
  gaz (GAS)              ~6   soit ~1,00 $/Mcf a 6,01 Mcf/boe

Le grain de génération passe donc de (puits, mois) à (puits, mois, produit). C'est
nécessaire : 68,6 % du volume vient de couples produisant à la fois du gaz et des
liquides, pour lesquels un taux unique aurait été une moyenne et non un coût.

CE QUI RESTE SIMULÉ
-------------------
Tout. Ces taux sont calés sur des ordres de grandeur publics, ils ne sont pas mesurés.
Aucun dépôt public ne donne l'OPEX au grain du puits. Le seul progrès ici est que la
structure de coût cesse de contredire la structure de revenu ; le niveau, lui, reste
une hypothèse.

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

# Taux $/boe par famille de produit. Clé = product_type de Petrinex.
# Les liquides portent le coût de levage, de traitement et de transport routier ;
# le gaz sec, essentiellement de la compression et de la déshydratation.
OPEX_TAUX = {
    "OIL":  {"forage": (15.0, 2.5), "maintenance": (5.0, 1.5)},   # ~20 $/boe
    "COND": {"forage": (15.0, 2.5), "maintenance": (5.0, 1.5)},   # traité comme OIL
    "GAS":  {"forage": (4.5, 1.0),  "maintenance": (1.5, 0.5)},   # ~6 $/boe
}
# Produit inconnu : on retombe sur le profil liquide, plus cher, pour ne pas
# sous-estimer un coût par accident de nomenclature.
OPEX_TAUX_DEFAUT = OPEX_TAUX["OIL"]

CAPEX_LOGNORM_MEAN, CAPEX_LOGNORM_SIGMA = 11.5, 0.6  # log-espace ($CAD)
CAPEX_RECENT_MULT = 2.5                               # puits < 3 ans
CAPEX_RECENT_YEARS = 3

WINTER_MONTHS = (1, 2, 3)
WINTER_MULT = 1.15
INCIDENT_RATE = 0.05
INCIDENT_MULT = 2.0

# Garde-fou $/boe. La distribution est désormais bimodale — ~6 pour le gaz, ~20 pour
# les liquides — donc la bande couvre les deux modes élargis des multiplicateurs
# saisonnier et incident. Elle n'arbitre pas un niveau, elle attrape une dérive.
OPEX_MIN, OPEX_MAX = 2.0, 60.0


def main() -> int:
    print(f"Racine projet : {ROOT}")
    for path in (PETRINEX_PARQUET, DIM_PUITS_PARQUET):
        if not path.exists():
            print(f"[ERREUR] Fichier requis absent : {path}", file=sys.stderr)
            return 1

    rng = np.random.default_rng(RNG_SEED)

    # --- Volumes BOE mensuels par puits (périmètre canonique partagé) ------ #
    grp = charger_volumes_mensuels(PETRINEX_PARQUET, par_produit=True)
    print(f"  Triplets (puits, mois, produit) avec production > 0 : {len(grp):,}")

    df = pd.DataFrame()
    df["uwi"] = grp["uwi"].astype("string")
    df["date"] = pd.to_datetime(grp["date"])
    df["date_key"] = (df["date"].dt.year * 100 + df["date"].dt.month).astype("int64")
    df["product_type"] = grp["product_type"].astype("string")
    volume_boe = grp["volume_boe"].to_numpy(dtype="float64")
    n = len(df)

    # --- OPEX $/boe par produit (tronqué à >= 0 avant multiplicateurs) ----- #
    # Un tirage est fait pour chaque famille sur toute la longueur, puis on ne garde
    # que les lignes du produit concerné. Coûteux en mémoire mais vectorisé, et surtout
    # reproductible : l'ordre de consommation du générateur ne dépend pas du tri.
    produit = df["product_type"].to_numpy(dtype=object)
    forage_rate = np.zeros(n)
    maint_rate = np.zeros(n)

    familles = sorted(set(produit.tolist()))
    for fam in familles:
        taux = OPEX_TAUX.get(fam, OPEX_TAUX_DEFAUT)
        masque = produit == fam
        k = int(masque.sum())
        mu_f, sd_f = taux["forage"]
        mu_m, sd_m = taux["maintenance"]
        forage_rate[masque] = np.clip(rng.normal(mu_f, sd_f, k), 0, None)
        maint_rate[masque] = np.clip(rng.normal(mu_m, sd_m, k), 0, None)
        connu = "" if fam in OPEX_TAUX else "  [profil liquide par défaut]"
        print(f"    {fam:<6} {k:>9,} lignes   ~{mu_f + mu_m:.1f} $/boe{connu}")

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
    # Le CAPEX est un investissement de puits, pas de molécule : depuis le passage au
    # grain produit, une même paire (puits, mois) porterait sinon deux tirages
    # différents et le dédoublonnage aval dépendrait de la ligne retenue.
    df["capex"] = df.groupby(["uwi", "date_key"])["capex"].transform("first")
    df = df.drop(columns=["spud_date"])

    df["devise"] = "CAD"

    # --- Contrôle qualité OPEX/boe ---------------------------------------- #
    opex_total = df["opex_forage"] + df["opex_maintenance"]
    opex_par_boe = np.divide(
        opex_total, volume_boe, out=np.zeros_like(opex_total), where=volume_boe > 0
    )
    p05, p95 = np.percentile(opex_par_boe, [5, 95])
    print(f"  OPEX/boe global — p05={p05:.2f}  médiane={np.median(opex_par_boe):.2f}  "
          f"p95={p95:.2f}  (garde-fou ${OPEX_MIN:.0f}-{OPEX_MAX:.0f})")

    # Le contrôle qui compte désormais est PAR PRODUIT : c'est le mélange des deux
    # profils qui était faux, pas la moyenne globale, laquelle restait plausible.
    for fam in familles:
        m = (df["product_type"] == fam).to_numpy()
        pondere = opex_total[m].sum() / volume_boe[m].sum() if volume_boe[m].sum() else 0
        print(f"    {fam:<6} OPEX/boe pondéré = {pondere:6.2f} $")

    hors_bande = ((opex_par_boe < OPEX_MIN) | (opex_par_boe > OPEX_MAX)).sum()
    if hors_bande:
        print(
            f"[!] ATTENTION : {hors_bande:,} lignes hors [{OPEX_MIN}, {OPEX_MAX}] $/boe.",
            file=sys.stderr,
        )

    df = df[
        ["uwi", "date_key", "product_type", "opex_forage", "opex_maintenance",
         "capex", "devise"]
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
