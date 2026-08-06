"""
03_ingest_prices.py — Dimension prix (DIM_PRIX)

Sortie : data/processed/dim_prix.parquet

SOURCES (publiques, SANS clé API) :
  - WTI mensuel   : Yahoo Finance, contrat WTI Crude (CL=F)
                    https://query1.finance.yahoo.com/v8/finance/chart/CL=F
  - USD/CAD       : Bank of Canada Valet, série FXUSDCAD (taux quotidien -> mensuel)
                    https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json

Écart assumé par rapport à la spécification de départ :
  Le §6 prévoyait EIA (WTI) + Alpha Vantage (FX), qui exigent tous deux une clé API.
  Pour un pipeline reproductible sans inscription, on utilise des sources keyless
  équivalentes (Yahoo Finance + Banque du Canada). WCS reste dérivé du WTI via le
  discount historique moyen (-17.5 USD/bbl), conformément au §6.

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
WCS_DISCOUNT_USD = 17.5      # discount WCS historique moyen vs WTI (USD/bbl)

YAHOO_WTI_URL = "https://query1.finance.yahoo.com/v8/finance/chart/CL=F"
BOC_FX_URL = "https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json"
HEADERS = {"User-Agent": "Mozilla/5.0"}
REQUEST_TIMEOUT = 30


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


def fetch_wti() -> pd.DataFrame:
    """WTI mensuel (clôture) depuis Yahoo Finance CL=F."""
    params = {"interval": "1mo", "range": "5y"}
    r = requests.get(YAHOO_WTI_URL, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_localize(None)
    close = res["indicators"]["quote"][0]["close"]
    df = pd.DataFrame({"date": ts.to_period("M").to_timestamp(), "wti_usd": close})
    return df.dropna(subset=["wti_usd"]).drop_duplicates("date")


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

    print("Téléchargement WTI (Yahoo Finance CL=F)...")
    wti = fetch_wti()
    print(f"  {len(wti)} mois WTI reçus")

    print("Téléchargement USD/CAD (Banque du Canada)...")
    fx = fetch_usdcad(first)
    print(f"  {len(fx)} mois FX reçus")

    # --- Grille mensuelle complète sur la fenêtre --------------------------- #
    grid = pd.DataFrame({"date": pd.date_range(first, last, freq="MS")})
    df = grid.merge(wti, on="date", how="left").merge(fx, on="date", how="left")

    # Comble les éventuels trous (séries peu volatiles).
    df["wti_usd"] = df["wti_usd"].interpolate().ffill().bfill()
    df["taux_usdcad"] = df["taux_usdcad"].ffill().bfill()

    df["wcs_usd"] = df["wti_usd"] - WCS_DISCOUNT_USD
    df["wcs_cad"] = df["wcs_usd"] * df["taux_usdcad"]
    df["date_key"] = (df["date"].dt.year * 100 + df["date"].dt.month).astype("int64")

    df = df[["date_key", "date", "wti_usd", "wcs_usd", "taux_usdcad", "wcs_cad"]]

    # --- Validation ---------------------------------------------------------- #
    if (df["wcs_usd"] <= 0).any():
        print("[!] ATTENTION : WCS USD <= 0 détecté.", file=sys.stderr)
    hors = df[~df["taux_usdcad"].between(1.20, 1.50)]
    if not hors.empty:
        print(f"[!] ATTENTION : {len(hors)} taux USD/CAD hors [1.20, 1.50].", file=sys.stderr)
    if df.isna().any().any():
        print("[!] ATTENTION : nulls résiduels dans dim_prix.", file=sys.stderr)

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PARQUET, index=False)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8")
    print(f"\nÉcrit : {OUT_PARQUET}  ({len(df)} mois)")
    print(f"Écrit : {OUT_CSV}")
    print(df.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
