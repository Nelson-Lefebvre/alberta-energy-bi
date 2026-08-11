# ══════════════════════════════════════════════════════════════════
# LIBRARY IMPORTS
# ══════════════════════════════════════════════════════════════════

import pandas as pd
import numpy as np
import requests
import io
import zipfile
from datetime import datetime
from dateutil.relativedelta import relativedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ══════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════

# scripts/01_ingest_petrinex.py → .parent = scripts/ → .parent = racine projet
PROJECT_ROOT  = Path(__file__).resolve().parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_PARQUET = PROCESSED_DIR / "petrinex24.parquet"
OUTPUT_CSV     = PROCESSED_DIR / "petrinex24.csv"

BASE_URL    = "https://www.petrinex.gov.ab.ca/publicdata/API/Files/AB/Vol/{}/CSV"
MONTHS_BACK = 24
PUBLISH_LAG = 2   # Petrinex publie avec environs 2 mois de délai
MAX_WORKERS = 6   # Téléchargements réseau simultanés x6
TIMEOUT     = 30  # Timeout en secondes par requête HTTP

# Étape 3 — Renommage snake_case (appliqué dès le fetch)
COLUMN_MAPPING = {
    "OperatorBAID"       : "operator_id",
    "FromToIDIdentifier" : "uwi",  # identifiant unique du puits selon le système DLS (Dominion Land Survey) canadien. Format type 100/01-23-045-06W4/00 (ici sans les /). Ça encode littéralement la position géographique : section, township, range, méridien. Deux puits ne peuvent pas avoir le même UWI.
    "ProductionMonth"    : "date", # Mois de déclaration (toujours le 1er du mois, c'est une convention). 2024-04-01 = production d'avril 2024.
    "ProductID"          : "product_type",
    "ActivityID"         : "activity_type",
    "Volume"             : "volume_brut",
}

# Filtres métier (identifiés sur les données réelles)
KEEP_PRODUCTS   = {"OIL", "GAS", "WATER", "COND"}
KEEP_ACTIVITIES = {"PROD", "SHUTIN", "FUEL", "VENT", "FLARE"}
#  PROD   → production réelle du puits       ← cœur du dashboard
#  SHUTIN → puits fermé temporairement       ← statut puits
#  FUEL   → consommation carburant sur site  ← module ESG
#  VENT   → émissions atmosphériques         ← module ESG
#  FLARE  → gaz torché                       ← module ESG
# Les trois dernières sont les entrées du script 05, qui calcule les émissions à
# partir des volumes déclarés plutôt qu'à partir d'un facteur appliqué à la
# production. Les retirer vide la page ESG.

# Étape 6 — Facteurs de conversion m³ → BOE (standard AER Alberta)
#  OIL / COND : 1 m³  = 6.2898 BOE
#  GAS        : 1 m³  = 35.31 cf  ->  1 BOE = 6 000 cf  →  1 m³ = 35.31/6 000 BOE
#  WATER      : pas de valeur énergétique -> volume_boe = 0
BOE_LIQUID = 6.29 # 1 m³ ≈ 6.29 barils -> conversion volumétrique pure (1 baril = 158.987 L)
BOE_GAS    = 35.31 / 6_000   # ≈ 0.005885 BOE/m³


# ══════════════════════════════════════════════════════════════════
# ÉTAPE 1-2 — TÉLÉCHARGEMENT PARALLÈLE
# ══════════════════════════════════════════════════════════════════

def build_month_list(months_back: int, lag: int) -> list[str]:
    """
    Génère la liste des YYYY-MM à télécharger.
    Complexité O(n) — remplace la boucle while à double offset de la v1.
    """
    origin = datetime.now().replace(day=1)
    return [
        (origin - relativedelta(months=lag + i)).strftime("%Y-%m")
        for i in range(months_back)
    ]


def fetch_month(month_str: str) -> tuple[str, pd.DataFrame | None, str]:
    """
    Télécharge, dé-zippe (double zip Petrinex) et parse un mois.
    Tout en mémoire — aucune écriture dans data/raw.

    Applique dès ici :
      - Sélection des colonnes utiles
      - Renommage snake_case (COLUMN_MAPPING)
      - Typage minimal (volume → float, date → datetime)

    Retourne : (month_str, DataFrame | None, message_log)
    """
    url = BASE_URL.format(month_str)
    try:
        resp = requests.get(url, timeout=TIMEOUT)
        if resp.status_code != 200:
            return month_str, None, f"HTTP {resp.status_code}"

        # Double dézip natif Petrinex (zip → zip → csv)
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z1:
            with z1.open(z1.namelist()[0]) as inner_bytes:
                with zipfile.ZipFile(io.BytesIO(inner_bytes.read())) as z2:
                    with z2.open(z2.namelist()[0]) as csv_file:
                        df_raw = pd.read_csv(
                            csv_file,
                            encoding="ISO-8859-1",
                            low_memory=False,
                        )

        # Étape 3 — Sélection + renommage snake_case
        cols_present = [c for c in COLUMN_MAPPING if c in df_raw.columns]
        df = df_raw[cols_present].rename(columns=COLUMN_MAPPING)

        # Étape 4 — Typage : dates et volumes (codes typés en category après concat)
        df["volume_brut"] = pd.to_numeric(df["volume_brut"], errors="coerce")
        df["date"]        = pd.to_datetime(df["date"],        errors="coerce")

        return month_str, df, f"OK — {len(df):,} lignes"

    except zipfile.BadZipFile:
        return month_str, None, "BadZipFile (format inattendu)"
    except Exception as exc:
        return month_str, None, str(exc)


def download_parallel(months: list[str]) -> pd.DataFrame | None:
    """
    Lance MAX_WORKERS téléchargements simultanés (ThreadPoolExecutor).

    Complexité réseau : O(n / MAX_WORKERS)  ← ~4× vs séquentiel sur 24 mois
    Complexité CPU    : O(n)                ← parsing inévitable par fichier
    """
    results: dict[str, pd.DataFrame] = {}
    total = len(months)

    print(f"\nTéléchargement de {total} mois ({MAX_WORKERS} workers)...\n")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_month, m): m for m in months}
        for i, future in enumerate(as_completed(futures), start=1):
            month_str, df, msg = future.result()
            icon = "✓" if df is not None else "✗"
            print(f"  [{i:>2}/{total}]  {icon}  {month_str}  —  {msg}")
            if df is not None:
                results[month_str] = df

    if not results:
        print("\n⚠  Aucun mois récupéré.")
        return None

    # Concaténation triée chronologiquement
    frames = [results[m] for m in sorted(results)]
    df = pd.concat(frames, ignore_index=True)

    # Étape 4 (suite) — Codes texte en category après concat (économise ~60% RAM)
    for col in ("operator_id", "uwi", "product_type", "activity_type"):
        if col in df.columns:
            df[col] = df[col].astype("category")

    print(f"\n  Concat terminée : {len(df):,} lignes brutes")
    return df


# ══════════════════════════════════════════════════════════════════
# ÉTAPES 5 — FILTRES QUALITÉ
# ══════════════════════════════════════════════════════════════════

def filter_quality(df: pd.DataFrame) -> pd.DataFrame:
    """
    Étape 5 — 4 filtres appliqués dans l'ordre :
      5a. uwi null       → lignes niveau opérateur/installation (pas de puits)
      5b. product_type   → garder OIL, GAS, WATER, COND uniquement
      5c. activity_type  → garder PROD, SHUTIN, FUEL, VENT uniquement
      5d. volume_brut <0 → corrections rétroactives Petrinex
    """
    n0 = len(df)
    print(f"\n─ Étape 5 : filtres qualité (brut : {n0:,} lignes) ─")

    # 5a — UWI manquant
    df = df[df["uwi"].notna()]
    print(f"  5a uwi non-nul        : {len(df):>12,}  (-{n0 - len(df):,})")

    # 5b — ProductType hors périmètre
    n = len(df)
    df = df[df["product_type"].isin(KEEP_PRODUCTS)]
    print(f"  5b product_type       : {len(df):>12,}  (-{n - len(df):,})")

    # 5c — ActivityType hors périmètre
    n = len(df)
    df = df[df["activity_type"].isin(KEEP_ACTIVITIES)]
    print(f"  5c activity_type      : {len(df):>12,}  (-{n - len(df):,})")

    # 5d — Volumes négatifs
    n = len(df)
    df = df[df["volume_brut"].notna() & (df["volume_brut"] >= 0)]
    print(f"  5d volume_brut >= 0   : {len(df):>12,}  (-{n - len(df):,})")

    pct = (n0 - len(df)) / n0 * 100
    print(f"\n  Supprimé : {n0 - len(df):,} lignes ({pct:.1f}%)  |  "
          f"Conservé : {len(df):,} lignes")

    return df.reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════
# ÉTAPE 6 — CONVERSION m³ → BOE
# ══════════════════════════════════════════════════════════════════

def convert_to_boe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Étape 6 — Calcule volume_boe selon le type de produit.

    Formule (guide J2) : boe = m3_oil * 6.29 + m3_gas * 35.31 / 6000

    Implémentation vectorisée via np.select (pas d'apply → O(n) pur).
    """
    print("\n─ Étape 6 : conversion m³ → BOE ─")

    pt = df["product_type"].astype(str)   # sortir de category pour np.select

    df["volume_boe"] = np.select(
        condlist=[
            pt.isin(["OIL", "COND"]),         # liquides
            pt == "GAS",                       # gaz
            pt == "WATER",                     # eau (pas de valeur énergétique)
        ],
        choicelist=[
            df["volume_brut"] * BOE_LIQUID,
            df["volume_brut"] * BOE_GAS,
            0.0,
        ],
        default=np.nan,
    )

    recap = (
        df.groupby("product_type", observed=True)
        .agg(
            lignes       = ("volume_brut", "count"),
            vol_brut_m3  = ("volume_brut", "sum"),
            vol_boe      = ("volume_boe",  "sum"),
        )
        .round(1)
    )
    print(recap.to_string())
    return df


# ══════════════════════════════════════════════════════════════════
# ÉTAPE 7 — SAUVEGARDE PARQUET
# ══════════════════════════════════════════════════════════════════

def save_parquet(df: pd.DataFrame) -> None:
    """
    Étape 7 : sauvegarde en Parquet (Snappy) et en CSV.

    PyArrow ne supporte pas le type pandas 'category' → conversion str avant export.
    dbt Core re-typera les colonnes dans les modèles staging.
    """
    df_out = df.copy()
    for col in df_out.select_dtypes("category").columns:
        df_out[col] = df_out[col].astype(str)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df_out.to_parquet(OUTPUT_PARQUET, engine="pyarrow", index=False, compression="snappy")
    df_out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")

    size_pq = OUTPUT_PARQUET.stat().st_size / 1_048_576
    size_csv = OUTPUT_CSV.stat().st_size / 1_048_576
    print(f"\n✅  Parquet sauvegardé → {OUTPUT_PARQUET}")
    print(f"    {size_pq:.1f} Mo  ·  {len(df_out):,} lignes  ·  Snappy")
    print(f"✅  CSV sauvegardé     → {OUTPUT_CSV}")
    print(f"    {size_csv:.1f} Mo  ·  {len(df_out):,} lignes")


# ══════════════════════════════════════════════════════════════════
# RAPPORT DE QUALITÉ FINAL - TERMINAL
# ══════════════════════════════════════════════════════════════════

def quality_report(df_brut: pd.DataFrame, df_clean: pd.DataFrame) -> None:
    sep = "=" * 60
    print(f"\n{sep}\nRAPPORT DE QUALITÉ — petrinex24.parquet\n{sep}")

    print(f"\n{'Lignes brutes  :':<26} {len(df_brut):>12,}")
    print(f"{'Lignes propres :':<26} {len(df_clean):>12,}")
    print(f"{'Supprimées     :':<26} {len(df_brut) - len(df_clean):>12,}  "
          f"({(1 - len(df_clean)/len(df_brut))*100:.1f}%)")

    print(f"\n{'Plage temporelle :':<26} "
          f"{df_clean['date'].min().date()}  →  {df_clean['date'].max().date()}")
    print(f"{'Mois distincts :':<26} "
          f"{df_clean['date'].dt.to_period('M').nunique()}")
    print(f"{'UWI uniques    :':<26} {df_clean['uwi'].nunique():>12,}")
    print(f"{'Opérateurs     :':<26} {df_clean['operator_id'].nunique():>12,}")

    print("\n─ Volume BOE total par produit ─")
    print(
        df_clean.groupby("product_type", observed=True)["volume_boe"]
        .sum()
        .sort_values(ascending=False)
        .apply(lambda x: f"{x:,.0f} BOE")
        .to_string()
    )

    print("\n─ Top 10 opérateurs (volume PROD) ─")
    print(
        df_clean[df_clean["activity_type"] == "PROD"]
        .groupby("operator_id", observed=True)["volume_boe"]
        .sum()
        .sort_values(ascending=False)
        .head(10)
        .apply(lambda x: f"{x:,.0f} BOE")
        .to_string()
    )

    print("\n─ Contrôle nulls ─")
    nulls = df_clean.isnull().sum()
    null_cols = nulls[nulls > 0]
    print("  Aucune valeur nulle ✓" if null_cols.empty else null_cols.to_string())

    neg = (df_clean["volume_brut"] < 0).sum()
    print(f"\n─ Volumes négatifs ─\n  {neg} ✓" if neg == 0
          else f"\n─ Volumes négatifs ─\n  ⚠ {neg} restants")

    print(f"\n─ Dtypes finaux ─\n{df_clean.dtypes.to_string()}")


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    months = build_month_list(MONTHS_BACK, PUBLISH_LAG)
    print(f"Plage cible : {months[-1]}  →  {months[0]}")

    # Étapes 1-2 : téléchargement parallèle + concat + typage
    df_brut = download_parallel(months)

    if df_brut is not None:
        # Étape 5 : filtres qualité
        df_clean = filter_quality(df_brut)

        # Étape 6 : conversion BOE
        df_clean = convert_to_boe(df_clean)

        # Étape 7 : sauvegarde Parquet
        save_parquet(df_clean)

        # Rapport final
        quality_report(df_brut, df_clean)