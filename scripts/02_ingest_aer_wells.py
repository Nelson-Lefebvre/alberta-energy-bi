"""
02_ingest_aer_wells.py — Dimension puits (DIM_PUITS)

Sortie : data/processed/dim_puits.parquet

SOURCES (toutes publiques, déposées dans data/raw/ par le script de récupération) :
  - data/raw/ST37.zip          AER ST37 « List of Wells in Alberta » (TXT tabulé,
                               24 colonnes, localisation DLS, ~record 322).
                               https://static.aer.ca/prd/documents/sts/st37/ST37.zip
  - data/raw/ba_codes.csv      Petrinex Business Associate : BACode -> BAName
                               https://www.petrinex.gov.ab.ca/bbreports/PRABAIdentifiers.csv
  - data/raw/field_codes.csv   Petrinex Field Codes : FieldCode -> FieldName
                               https://www.petrinex.gov.ab.ca/bbreports/PRAFieldCodes.csv

Écart assumé par rapport à la spécification de départ :
  Le ST37 réel n'est PAS un Excel et ne contient ni latitude/longitude, ni noms
  d'opérateur/champ (uniquement des codes), ni champ « area ». On reconstruit donc :
    - uwi             : clé Petrinex 16 car. reconstruite depuis le DLS (UWI display)
    - latitude/long.  : converties (approximation grille DLS Alberta, ~niveau section)
    - operator_name   : LICENSEE-CODE[:4] joint au référentiel BA
    - field           : FIELD-CODE joint au référentiel Field
    - region / area   : dérivées du township + méridien (le ST37 n'a pas d'area)
    - well_type       : TYPE_SHORT_DESCRIPTION (usage du puits)
    - status          : MODE_SHORT_DESCRIPTION mappé ACTIVE/SUSPENDED/ABANDONED
    - spud_date       : FIN-DRL-DATE (libération du rig ≈ forage)
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

# Console Windows (cp1252) : éviter les UnicodeEncodeError sur ∩, é, etc.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

# --------------------------------------------------------------------------- #
# Chemins ancrés sur la racine du projet
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent.parent
ST37_ZIP = ROOT / "data" / "raw" / "ST37.zip"
BA_CSV = ROOT / "data" / "raw" / "ba_codes.csv"
FIELD_CSV = ROOT / "data" / "raw" / "field_codes.csv"
OUT_PARQUET = ROOT / "data" / "processed" / "dim_puits.parquet"
OUT_CSV = ROOT / "data" / "processed" / "dim_puits.csv"
PETRINEX_PARQUET = ROOT / "data" / "processed" / "petrinex24.parquet"

FINAL_COLUMNS = [
    "uwi", "operator_name", "area", "region", "field",
    "well_type", "status", "spud_date", "latitude", "longitude",
]

# Colonnes du WellList.txt (tabulé) — ordre exact du layout ST37 (oct. 2022)
ST37_COLUMNS = [
    "uwi_display", "uwi_id", "update_flag", "well_name", "field_code",
    "pool_code", "os_area_code", "os_dep_code", "license_no", "licence_status",
    "license_issue_date", "licensee_code", "agent_code", "operator_code",
    "fin_drl_date", "well_total_depth", "well_stat_code", "well_stat_date",
    "fluid_short_desc", "mode_short_desc", "type_short_desc",
    "structure_short_desc", "scheme_type", "scheme_sub_type",
]

# UWI display AER : "EE/LL-SS-TTT-RR<MER>/E"  (ex. "00/06-06-001-01W4/0")
UWI_DISPLAY_RE = (
    r"^(?P<exc>\d{2})/(?P<lsd>\d{2})-(?P<sec>\d{2})-(?P<twp>\d{3})-"
    r"(?P<rge>\d{2})(?P<mer>[WE]\d)/(?P<event>\d+)$"
)

# Méridien -> longitude de base (degrés). Alberta : surtout W4/W5/W6.
MER_BASE_LON = {"W2": -102.0, "W3": -106.0, "W4": -110.0, "W5": -114.0, "W6": -118.0}
TWP_HEIGHT_DEG = 6.0 / 69.0857            # ~0.08685° de latitude par township (6 mi)

# MODE_SHORT_DESCRIPTION (Appendix 2) -> statut normalisé (§5)
STATUS_MAP = {
    "FLOW": "ACTIVE", "PUMP": "ACTIVE", "GASLFT": "ACTIVE",
    "SUSP": "SUSPENDED",
    "ABD": "ABANDONED", "ABZONE": "ABANDONED", "ABRENT": "ABANDONED",
    "ABDWHP": "ABANDONED", "J&A": "ABANDONED",
}


# --------------------------------------------------------------------------- #
# Conversion DLS -> latitude / longitude (approximation grille Alberta)
# --------------------------------------------------------------------------- #
def _boustrophedon_col_from_west(idx: np.ndarray, n: int) -> np.ndarray:
    """
    Position ouest (0=bord ouest .. n-1=bord est) d'une cellule numérotée en
    serpentin (sections 1-36, LSD 1-16) : rangée paire numérotée E->O, impaire O->E.
    `idx` est 0-based ; les rangées font n cellules.
    """
    row = idx // n
    pos = idx % n
    return np.where(row % 2 == 0, (n - 1) - pos, pos)


def dls_to_latlon(twp, rge, mer, sec, lsd) -> tuple[np.ndarray, np.ndarray]:
    """
    Convertit les composantes DLS en lat/lon approximatives (centroïde de LSD).
    Vectorisé. Renvoie (lat, lon) avec NaN si le méridien est inconnu.
    """
    twp = twp.astype("float64"); rge = rge.astype("float64")
    sec0 = (sec - 1).astype("int64"); lsd0 = (lsd - 1).astype("int64")

    # Fraction nord/ouest de la section dans le township (grille 6x6)
    sec_row = sec0 // 6
    sec_colw = _boustrophedon_col_from_west(sec0, 6)
    # Raffinement LSD dans la section (grille 4x4)
    lsd_row = lsd0 // 4
    lsd_colw = _boustrophedon_col_from_west(lsd0, 4)

    north_frac = (sec_row + (lsd_row + 0.5) / 4) / 6        # 0=sud .. 1=nord
    west_frac = (sec_colw + (lsd_colw + 0.5) / 4) / 6       # 0=est .. 1=ouest

    lat = 49.0 + ((twp - 1) + north_frac) * TWP_HEIGHT_DEG

    base_lon = pd.Series(mer).map(MER_BASE_LON).to_numpy(dtype="float64")
    # Largeur d'un range en degrés de longitude à cette latitude (~6 mi).
    rng_width_deg = 6.0 / (69.172 * np.cos(np.radians(lat)))
    lon = base_lon - ((rge - 1) + west_frac) * rng_width_deg
    return lat, lon


# --------------------------------------------------------------------------- #
# Lecture des sources
# --------------------------------------------------------------------------- #
def read_st37() -> pd.DataFrame:
    with zipfile.ZipFile(ST37_ZIP) as z:
        name = z.namelist()[0]
        with z.open(name) as fh:
            df = pd.read_csv(
                fh, sep="\t", header=None, names=ST37_COLUMNS,
                dtype=str, encoding="latin-1",
                keep_default_na=False, na_filter=False,
                quoting=3,  # csv.QUOTE_NONE
                on_bad_lines="skip",
            )
    # Nettoyage générique des espaces de remplissage
    for c in df.columns:
        df[c] = df[c].str.strip()
    return df


def main() -> int:
    print(f"Racine projet : {ROOT}")
    for path in (ST37_ZIP, BA_CSV, FIELD_CSV):
        if not path.exists():
            print(f"[ERREUR] Source absente : {path}", file=sys.stderr)
            return 1

    print(f"Lecture ST37 : {ST37_ZIP}")
    raw = read_st37()
    print(f"  Lignes brutes : {len(raw):,}")

    # --- Parsing du DLS depuis l'UWI display --------------------------------- #
    parts = raw["uwi_display"].str.extract(UWI_DISPLAY_RE)
    ok = parts["twp"].notna()
    print(f"  UWI display DLS parsés : {ok.sum():,}  (rejetés non-DLS : {(~ok).sum():,})")
    raw = raw[ok].reset_index(drop=True)
    parts = parts[ok].reset_index(drop=True)

    # Clé Petrinex 16 car. : 1 + exc + lsd + sec + twp + rge + mer + event(2)
    uwi = (
        "1" + parts["exc"] + parts["lsd"] + parts["sec"] + parts["twp"]
        + parts["rge"] + parts["mer"] + parts["event"].str.zfill(2)
    )

    twp = parts["twp"].astype("int64").to_numpy()
    rge = parts["rge"].astype("int64").to_numpy()
    sec = parts["sec"].astype("int64").to_numpy()
    lsd = parts["lsd"].astype("int64").to_numpy()
    mer = parts["mer"].to_numpy()

    # --- Référentiels (codes -> noms) ---------------------------------------- #
    ba = pd.read_csv(BA_CSV, dtype=str)
    ba["BACode"] = ba["BACode"].str.strip()
    ba["BAName"] = ba["BAName"].str.strip()
    ba_map = dict(zip(ba["BACode"], ba["BAName"]))

    fld = pd.read_csv(FIELD_CSV, dtype=str)
    fld["FieldCode"] = fld["FieldCode"].str.strip().str.zfill(4)
    fld["FieldName"] = fld["FieldName"].str.strip()
    field_map = dict(zip(fld["FieldCode"], fld["FieldName"]))

    # LICENSEE-CODE / OPERATOR-CODE : 4 premiers car. = code BA (5e = suffixe)
    licensee4 = raw["licensee_code"].str[:4]
    operator4 = raw["operator_code"].str[:4].where(raw["operator_code"].str.len() >= 4, "")
    operator_name = operator4.map(ba_map).fillna(licensee4.map(ba_map))

    field_name = raw["field_code"].str.zfill(4).map(field_map)

    # --- Conversion coordonnées --------------------------------------------- #
    lat, lon = dls_to_latlon(twp, rge, mer, sec, lsd)

    # --- Région / area (le ST37 n'a pas d'area : dérivé township + méridien) -- #
    # Region : 4 buckets (§5). Peace River = NW (W6, ou W5 township élevé).
    region = np.select(
        condlist=[
            (mer == "W6") | ((mer == "W5") & (twp >= 78)),   # Peace River (NW)
            twp >= 56,                                        # Nord
            twp >= 31,                                        # Central
        ],
        choicelist=["Peace River", "Nord", "Central"],
        default="Sud",
    )
    # Area : descripteur géographique plus fin (méridien) — distinct de region.
    area = pd.Series(mer).map(
        {"W2": "Est (W2)", "W3": "Est (W3)", "W4": "Plaines (W4)",
         "W5": "Contreforts (W5)", "W6": "Nord-Ouest (W6)"}
    ).fillna("Inconnu").to_numpy()

    # --- Statut / type / spud ------------------------------------------------ #
    status = raw["mode_short_desc"].map(STATUS_MAP).fillna(
        raw["mode_short_desc"].where(raw["mode_short_desc"].ne("N/A"), other=pd.NA)
    )
    well_type = raw["type_short_desc"].where(raw["type_short_desc"].ne("N/A"), other=pd.NA)
    spud_date = pd.to_datetime(raw["fin_drl_date"], format="%Y%m%d", errors="coerce")

    # --- Assemblage ---------------------------------------------------------- #
    df = pd.DataFrame({
        "uwi": uwi,
        "operator_name": operator_name,
        "area": area,
        "region": region,
        "field": field_name,
        "well_type": well_type,
        "status": status,
        "spud_date": spud_date,
        "latitude": lat,
        "longitude": lon,
    })

    # --- Nettoyage qualité --------------------------------------------------- #
    avant = len(df)
    df = df[df["uwi"].str.fullmatch(r"1[A-Z0-9]{15}")]
    df = df[df["latitude"].between(48.9, 60.1) & df["longitude"].between(-120.2, -109.8)]
    df = df.drop_duplicates(subset="uwi", keep="last").reset_index(drop=True)
    print(f"  Lignes après nettoyage : {len(df):,}  (retirées : {avant - len(df):,})")

    # str/object avant Parquet (compat PyArrow, §3.3)
    for col in ("uwi", "operator_name", "area", "region", "field", "well_type", "status"):
        df[col] = df[col].astype("object").where(df[col].notna(), None)

    df = df[FINAL_COLUMNS]
    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PARQUET, index=False)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8")
    print(f"\nÉcrit : {OUT_PARQUET}  ({len(df):,} puits)")
    print(f"Écrit : {OUT_CSV}")

    # --- Rapport qualité ----------------------------------------------------- #
    print("\nRépartition par région :")
    print(df["region"].value_counts(dropna=False).to_string())
    print(f"\noperator_name renseigné : {df['operator_name'].notna().mean()*100:5.1f} %")
    print(f"field renseigné         : {df['field'].notna().mean()*100:5.1f} %")
    print(f"status renseigné        : {df['status'].notna().mean()*100:5.1f} %")
    print(f"spud_date renseigné     : {df['spud_date'].notna().mean()*100:5.1f} %")
    print(f"spud_date : {df['spud_date'].min()} -> {df['spud_date'].max()}")
    print(f"lat : {df['latitude'].min():.3f}..{df['latitude'].max():.3f}  "
          f"lon : {df['longitude'].min():.3f}..{df['longitude'].max():.3f}")

    report_uwi_coverage(df)
    return 0


def report_uwi_coverage(dim: pd.DataFrame) -> None:
    """Taux de couverture UWI dim_puits ∩ petrinex24 (cible > 70 %, §13)."""
    if not PETRINEX_PARQUET.exists():
        print(f"\n  [!] {PETRINEX_PARQUET} absent — couverture non calculée.")
        return
    pet = set(
        pd.read_parquet(PETRINEX_PARQUET, columns=["uwi"])["uwi"]
        .dropna().astype(str).unique()
    )
    dim_uwi = set(dim["uwi"].dropna())
    commun = pet & dim_uwi
    taux = len(commun) / len(pet) * 100 if pet else 0.0
    print("\n  Couverture UWI (dim_puits ∩ petrinex24) :")
    print(f"    UWI petrinex24 uniques : {len(pet):>8,}")
    print(f"    UWI dim_puits uniques  : {len(dim_uwi):>8,}")
    print(f"    UWI communs            : {len(commun):>8,}")
    print(f"    >>> Taux de couverture : {taux:6.2f} %  (cible > 70 %)")
    if taux < 70:
        print("    [!] Couverture < 70 % — vérifier la reconstruction de la clé UWI.")


if __name__ == "__main__":
    raise SystemExit(main())
