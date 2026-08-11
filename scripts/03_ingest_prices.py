"""
03_ingest_prices.py — Dimension prix (DIM_PRIX)

Sortie : data/processed/dim_prix.parquet

SOURCES (publiques, SANS clé API) :
  - WTI et WCS mensuels : Gouvernement de l'Alberta, table OilPrices
                          https://api.economicdata.alberta.ca/data?table=OilPrices
                          Mensuel depuis 2005-01, en $US/bbl.
  - Prix gaz mensuel    : Gouvernement de l'Alberta, table NaturalGasPrices
                          https://api.economicdata.alberta.ca/data?table=NaturalGasPrices
                          Mensuel depuis 1988-01, en $CAD/GJ. Type unique « NatGas ».
  - USD/CAD             : Bank of Canada Valet, série FXUSDCAD (quotidien -> mensuel)
                          https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json

POURQUOI UN PRIX GAZ
--------------------
Sans lui, fact_production_enriched ne valorisait que OIL et COND : le gaz, 47,3 % du
volume en boe, portait un revenu nul. Toutes les mesures construites sur le revenu
divisaient pourtant par la production totale, si bien que le « revenu par baril »
affiché valait le revenu du pétrole étalé sur des barils de gaz, et que la marge
imputait les coûts du gaz au seul revenu pétrolier.

Le prix est publié en $CAD/GJ, alors que la production est en boe. La conversion
appartient au modèle dbt, pas à ce script : 1 boe gaz = 169,9 m³ × 0,0373 GJ/m³
= 6,34 GJ. Ce script ne fait qu'apporter le prix ; il ne convertit rien.

Valoriser le gaz au prix du pétrole aurait été 9,6 fois trop cher sur la fenêtre :
136,9 Md CAD contre 14,3 Md au prix gaz réel.

LE MOIS MANQUANT
----------------
La série gaz s'arrête un mois avant la série pétrole (publication plus tardive). Laisser
ce mois vide ramènerait son revenu gaz à zéro et réintroduirait le défaut corrigé ici.
Le dernier prix connu est donc reporté, et la colonne gaz_prix_reporte marque à True les
mois concernés pour que l'aval puisse les exclure ou les signaler. Report explicite et
traçable plutôt que trou silencieux.

Écart assumé par rapport à la spécification de départ :
  Le §6 prévoyait EIA (WTI) + Alpha Vantage (FX), qui exigent tous deux une clé API.
  Pour un pipeline reproductible sans inscription, on utilise des sources keyless
  équivalentes.

POURQUOI LE WCS N'EST PLUS DÉRIVÉ DU WTI
----------------------------------------
Ce script calculait auparavant le WCS en retranchant un différentiel fixe de 17,50
USD/bbl au WTI. Confronté à la série publiée par l'Alberta sur les 24 mois de la
fenêtre, ce raccourci ne tient pas :

  différentiel réel : 13,30 USD/bbl en moyenne, oscillant entre 9,95 et 18,99
  hypothèse fixe    : 17,50, trop large dans 22 mois sur 24
  erreur moyenne    : 4,20 USD/bbl, jusqu'à 7,55 au pire mois

Le différentiel WCS varie du simple au double selon l'engorgement des pipelines et la
demande des raffineries américaines. Le figer sous-estimait le revenu du bassin de
10,4 %, soit 14,3 Md CAD sur la période.

La même source publiant aussi le WTI, l'appel à Yahoo Finance a disparu : une source
officielle provinciale remplace deux sources dont l'une aux conditions d'utilisation
restrictives.

La fenêtre est alignée sur petrinex24 (24 mois glissants).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from dateutil.relativedelta import relativedelta

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

# --------------------------------------------------------------------------- #
# Chemins ancrés sur la racine du projet
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent.parent
OUT_PARQUET = ROOT / "data" / "processed" / "dim_prix.parquet"
OUT_CSV = ROOT / "data" / "processed" / "dim_prix.csv"
PETRINEX_PARQUET = ROOT / "data" / "processed" / "petrinex24.parquet"

# --------------------------------------------------------------------------- #
# Paramètres métier
# --------------------------------------------------------------------------- #
N_MONTHS = 24
PUBLICATION_LAG = 2          # mois — aligné sur le lag Petrinex

ALBERTA_PRICES_URL = "https://api.economicdata.alberta.ca/data"
BOC_FX_URL = "https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json"
HEADERS = {"User-Agent": "Mozilla/5.0"}
REQUEST_TIMEOUT = 30

# Bornes de vraisemblance du différentiel WCS, en USD/bbl. Larges à dessein : elles
# doivent laisser passer la variation réelle et n'arrêter qu'une inversion de colonnes
# ou un changement de schéma en amont.
DIFFERENTIEL_MIN = 0.0
DIFFERENTIEL_MAX = 45.0

# Bornes de vraisemblance du prix gaz, en $CAD/GJ. Même esprit : la série a touché 0,43
# en 2024 et dépassé 10 en 2022, donc la bande ne juge pas le marché, elle n'arrête
# qu'un changement d'unité ou de schéma en amont.
GAZ_MIN = 0.0
GAZ_MAX = 25.0


def month_window() -> tuple[date, date]:
    """Fenêtre (premier_mois, dernier_mois). Préfère l'alignement sur petrinex24."""
    if PETRINEX_PARQUET.exists():
        d = pd.read_parquet(PETRINEX_PARQUET, columns=["date"])["date"]
        first = d.min().to_pydatetime().date().replace(day=1)
        last = d.max().to_pydatetime().date().replace(day=1)
        return first, last
    today = date.today().replace(day=1)
    last = today - relativedelta(months=PUBLICATION_LAG)
    first = last - relativedelta(months=N_MONTHS - 1)
    return first, last


def fetch_prix_alberta() -> pd.DataFrame:
    """WTI et WCS mensuels en USD/bbl, source Gouvernement de l'Alberta.

    L'API renvoie une ligne par (mois, type). Le nom de champ du type comporte une
    espace finale — « Type » et non « Type » — donc les clés sont normalisées avant
    lecture plutôt que codées en dur.
    """
    params = {"table": "OilPrices", "Type": "WCS;WTI"}
    r = requests.get(
        ALBERTA_PRICES_URL, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT
    )
    r.raise_for_status()

    lignes = []
    for brut in r.json():
        obs = {str(k).strip(): v for k, v in brut.items()}
        if obs.get("Value") is None:
            continue
        lignes.append(
            {
                "date": pd.Timestamp(obs["Date"]).to_period("M").to_timestamp(),
                "type": str(obs["Type"]).strip().upper(),
                "prix_usd": float(obs["Value"]),
            }
        )

    if not lignes:
        raise RuntimeError("Aucun prix exploitable renvoyé par l'API Alberta.")

    large = (
        pd.DataFrame(lignes)
        .pivot_table(index="date", columns="type", values="prix_usd", aggfunc="last")
        .reset_index()
    )

    manquants = {"WTI", "WCS"} - set(large.columns)
    if manquants:
        raise RuntimeError(f"Séries absentes de la réponse Alberta : {sorted(manquants)}")

    return large.rename(columns={"WTI": "wti_usd", "WCS": "wcs_usd"})[
        ["date", "wti_usd", "wcs_usd"]
    ]


def fetch_prix_gaz() -> pd.DataFrame:
    """Prix gaz mensuel en $CAD/GJ, source Gouvernement de l'Alberta.

    Même endpoint et même schéma que les prix pétroliers, à deux différences près : la
    table ne publie qu'un seul type (« NatGas ») et la valeur est déjà en dollars
    canadiens, donc elle ne passe pas par le taux de change.
    """
    params = {"table": "NaturalGasPrices"}
    r = requests.get(
        ALBERTA_PRICES_URL, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT
    )
    r.raise_for_status()

    lignes = []
    for brut in r.json():
        obs = {str(k).strip(): v for k, v in brut.items()}
        if obs.get("Value") is None:
            continue
        unite = str(obs.get("Unit", "")).strip()
        if unite and "GJ" not in unite:
            raise RuntimeError(
                f"Unité inattendue pour le prix gaz : « {unite} », GJ attendu. "
                "La source a changé de barème, la conversion aval serait fausse."
            )
        lignes.append(
            {
                "date": pd.Timestamp(obs["Date"]).to_period("M").to_timestamp(),
                "gaz_cad_gj": float(obs["Value"]),
            }
        )

    if not lignes:
        raise RuntimeError("Aucun prix gaz exploitable renvoyé par l'API Alberta.")

    return (
        pd.DataFrame(lignes)
        .groupby("date", as_index=False)["gaz_cad_gj"]
        .last()
        .sort_values("date")
    )


def fetch_usdcad(first: date) -> pd.DataFrame:
    """USD/CAD mensuel (moyenne des taux quotidiens) depuis la Banque du Canada."""
    params = {"start_date": (first - relativedelta(months=1)).strftime("%Y-%m-01")}
    r = requests.get(BOC_FX_URL, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    obs = r.json()["observations"]
    rows = [
        {"date": pd.Timestamp(o["d"]).to_period("M").to_timestamp(),
         "taux_usdcad": float(o["FXUSDCAD"]["v"])}
        for o in obs if o.get("FXUSDCAD", {}).get("v")
    ]
    df = pd.DataFrame(rows)
    return df.groupby("date", as_index=False)["taux_usdcad"].mean()


def main() -> int:
    print(f"Racine projet : {ROOT}")
    first, last = month_window()
    print(f"Fenêtre : {first:%Y-%m} -> {last:%Y-%m}")

    print("Téléchargement WTI et WCS (Gouvernement de l'Alberta)...")
    prix = fetch_prix_alberta()
    print(f"  {len(prix)} mois reçus, de {prix['date'].min():%Y-%m} à {prix['date'].max():%Y-%m}")

    print("Téléchargement du prix gaz (Gouvernement de l'Alberta)...")
    gaz = fetch_prix_gaz()
    print(f"  {len(gaz)} mois reçus, de {gaz['date'].min():%Y-%m} à {gaz['date'].max():%Y-%m}")

    print("Téléchargement USD/CAD (Banque du Canada)...")
    fx = fetch_usdcad(first)
    print(f"  {len(fx)} mois FX reçus")

    # --- Grille mensuelle complète sur la fenêtre --------------------------- #
    grid = pd.DataFrame({"date": pd.date_range(first, last, freq="MS")})
    df = (
        grid.merge(prix, on="date", how="left")
        .merge(gaz, on="date", how="left")
        .merge(fx, on="date", how="left")
    )

    # Le drapeau se pose AVANT le report : une fois la série comblée, plus rien ne
    # distingue un prix publié d'un prix recopié.
    df["gaz_prix_reporte"] = df["gaz_cad_gj"].isna()

    # Comble les éventuels trous (séries peu volatiles).
    df["wti_usd"] = df["wti_usd"].interpolate().ffill().bfill()
    df["wcs_usd"] = df["wcs_usd"].interpolate().ffill().bfill()
    df["taux_usdcad"] = df["taux_usdcad"].ffill().bfill()
    df["gaz_cad_gj"] = df["gaz_cad_gj"].ffill().bfill()

    df["wcs_cad"] = df["wcs_usd"] * df["taux_usdcad"]
    df["date_key"] = (df["date"].dt.year * 100 + df["date"].dt.month).astype("int64")

    df = df[
        [
            "date_key", "date", "wti_usd", "wcs_usd", "taux_usdcad", "wcs_cad",
            "gaz_cad_gj", "gaz_prix_reporte",
        ]
    ]

    # --- Validation ---------------------------------------------------------- #
    if (df["wcs_usd"] <= 0).any():
        print("[!] ATTENTION : WCS USD <= 0 détecté.", file=sys.stderr)

    differentiel = df["wti_usd"] - df["wcs_usd"]
    hors_diff = df[~differentiel.between(DIFFERENTIEL_MIN, DIFFERENTIEL_MAX)]
    if not hors_diff.empty:
        print(
            f"[!] ATTENTION : {len(hors_diff)} mois où l'écart WTI-WCS sort de "
            f"[{DIFFERENTIEL_MIN}, {DIFFERENTIEL_MAX}] USD/bbl. Colonnes inversées ?",
            file=sys.stderr,
        )

    hors = df[~df["taux_usdcad"].between(1.20, 1.50)]
    if not hors.empty:
        print(f"[!] ATTENTION : {len(hors)} taux USD/CAD hors [1.20, 1.50].", file=sys.stderr)

    hors_gaz = df[~df["gaz_cad_gj"].between(GAZ_MIN, GAZ_MAX)]
    if not hors_gaz.empty:
        print(
            f"[!] ATTENTION : {len(hors_gaz)} mois où le prix gaz sort de "
            f"[{GAZ_MIN}, {GAZ_MAX}] CAD/GJ. Changement d'unité en amont ?",
            file=sys.stderr,
        )

    n_reporte = int(df["gaz_prix_reporte"].sum())
    if n_reporte:
        mois = ", ".join(df.loc[df["gaz_prix_reporte"], "date"].dt.strftime("%Y-%m"))
        print(
            f"[i] Prix gaz reporté sur {n_reporte} mois ({mois}) : la série gaz est "
            "publiée plus tard que la série pétrole. Colonne gaz_prix_reporte à True."
        )

    if df.isna().any().any():
        print("[!] ATTENTION : nulls résiduels dans dim_prix.", file=sys.stderr)

    print(
        f"  Différentiel WTI-WCS observé : moyenne {differentiel.mean():.2f}, "
        f"min {differentiel.min():.2f}, max {differentiel.max():.2f} USD/bbl"
    )
    print(
        f"  Prix gaz observé : moyenne {df['gaz_cad_gj'].mean():.3f}, "
        f"min {df['gaz_cad_gj'].min():.2f}, max {df['gaz_cad_gj'].max():.2f} CAD/GJ"
    )

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PARQUET, index=False)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8")
    print(f"\nÉcrit : {OUT_PARQUET}  ({len(df)} mois)")
    print(f"Écrit : {OUT_CSV}")
    print(df.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
