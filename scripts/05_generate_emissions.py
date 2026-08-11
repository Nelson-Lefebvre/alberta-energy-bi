"""05_generate_emissions.py : émissions Scope 1 (FACT_EMISSIONS)

Sortie : data/processed/fact_emissions.parquet

Les émissions ne sont plus dérivées d'un facteur appliqué au volume produit. Elles
viennent de l'activité que les opérateurs déclarent eux-mêmes à Petrinex :

  FUEL   gaz consommé sur site   -> CO2 de combustion, plus un imbrûlé de CH4
  VENT   gaz évacué à l'air      -> CH4 et CO2 selon la composition du gaz
  FLARE  gaz torché              -> CO2 de combustion, plus 2 % d'imbrûlé

Facteurs : Inventaire national des GES du Canada (NIR, annexe 6) et Directive 060
de l'AER. Aucun tirage aléatoire, donc deux exécutions sur le même parquet donnent
le même résultat au bit près.

DEUX GRAINS DANS LA MÊME COLONNE
--------------------------------
Petrinex ne déclare pas tout au puits. La colonne identifiant mélange deux choses :

  16 caractères  UWI de puits          2,1 % du volume émetteur
   7 caractères  code d'installation   97,9 % du volume émetteur

Autrement dit, l'essentiel du gaz consommé l'est dans des batteries et des usines,
pas dans un puits en particulier, et ces codes n'existent pas dans dim_puits. Les
laisser tels quels enverrait 98 % des émissions dans le seau « hors référentiel »
et viderait la ventilation régionale de la page ESG.

Le volume déclaré par une installation est donc réparti sur les puits producteurs
du même opérateur et du même mois, au prorata du volume. C'est la règle déjà
appliquée à l'OPEX et au CO2 dans fact_production_enriched.

Ce que cette répartition préserve, et ce qu'elle ne préserve pas :

  - le total par opérateur est exact, puisque la répartition reste interne à
    l'opérateur. L'intensité carbone par opérateur est donc une mesure, pas une
    estimation ;
  - le total par région est fiable dans la mesure où les puits d'un opérateur se
    situent dans la région où il opère ses installations ;
  - l'intensité d'un puits pris isolément est une allocation, pas une mesure. Elle
    ne doit pas servir à classer des puits entre eux.

PÉRIMÈTRE
---------
Ce script produit les émissions *déclarées*, pas les émissions totales. Petrinex
enregistre le gaz mesuré et rapporté par l'opérateur. Il ne couvre ni les fuites
diffuses, ni les évents de pneumatiques, ni le méthane non déclaré, qui font
l'essentiel de l'écart entre inventaires officiels et campagnes de mesure. Le CH4
sortant d'ici vaut environ un dixième des estimations provinciales amont : ce
n'est pas une erreur de calcul, c'est la différence entre déclaré et réel.

Le gaz est déclaré en 10³m³. Le facteur d'échelle vient de production_universe
pour qu'il n'existe qu'à un seul endroit.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from production_universe import (
    ACTIVITY_TYPE_RETENU,
    FACTEUR_ECHELLE_GAZ,
    PRODUCT_TYPES_EXCLUS,
)

# --------------------------------------------------------------------------- #
# Chemins ancrés sur la racine du projet
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent.parent
PETRINEX_PARQUET = ROOT / "data" / "processed" / "petrinex24.parquet"
OUT_PARQUET = ROOT / "data" / "processed" / "fact_emissions.parquet"
OUT_CSV = ROOT / "data" / "processed" / "fact_emissions.csv"

# --------------------------------------------------------------------------- #
# Facteurs d'émission
#
# Combustion du gaz naturel : NIR annexe 6, tableau A6.1-5, consommation
# industrielle, exprimés par m³ de gaz brûlé.
# --------------------------------------------------------------------------- #
CO2_COMBUSTION_KG_M3 = 1.916      # kg CO2 / m³ brûlé
CH4_COMBUSTION_KG_M3 = 0.000037   # kg CH4 / m³ — imbrûlé de combustion

# Composition du gaz évacué ou torché. Le gaz de solution albertain titre
# couramment 75 à 90 % de méthane ; 80 % est la valeur retenue par la Directive
# 060 de l'AER en l'absence d'analyse au puits.
FRACTION_CH4_GAZ = 0.80
FRACTION_CO2_GAZ = 0.01

# Masses volumiques aux conditions normales AER (15 °C, 101,325 kPa).
DENSITE_CH4_KG_M3 = 0.6784
DENSITE_CO2_KG_M3 = 1.8393

RENDEMENT_TORCHE = 0.98           # Directive 060 de l'AER
CO2EQ_CH4 = 28                    # GWP100 CH4, GIEC AR5 — inchangé
SCOPE = "Scope1"

ACTIVITES_EMETTRICES = ("FUEL", "VENT", "FLARE")
LONGUEUR_UWI = 16                 # au-delà, l'identifiant est une installation
KG_PAR_TONNE = 1_000.0


def _date_key(serie: pd.Series) -> pd.Series:
    date = pd.to_datetime(serie)
    return (date.dt.year * 100 + date.dt.month).astype("int64")


def charger_activite(petrinex_parquet: Path) -> pd.DataFrame:
    """Volumes de gaz FUEL, VENT et FLARE en m³, par identifiant et par mois."""
    df = pd.read_parquet(
        petrinex_parquet,
        columns=[
            "uwi",
            "operator_id",
            "date",
            "product_type",
            "activity_type",
            "volume_brut",
        ],
    )
    df = df.dropna(subset=["uwi", "operator_id"])

    activite = df["activity_type"].astype(str)
    produit = df["product_type"].astype(str)
    df = df[activite.isin(ACTIVITES_EMETTRICES) & (produit == "GAS")].copy()

    df["volume_m3"] = df["volume_brut"].astype("float64") * FACTEUR_ECHELLE_GAZ
    df = df[df["volume_m3"] > 0].copy()

    df["activity_type"] = df["activity_type"].astype(str)
    df["uwi"] = df["uwi"].astype(str)
    df["operator_id"] = df["operator_id"].astype(str)
    df["date_key"] = _date_key(df["date"])
    df["est_installation"] = df["uwi"].str.len() != LONGUEUR_UWI

    return df[
        ["uwi", "operator_id", "date_key", "activity_type", "volume_m3", "est_installation"]
    ]


def charger_production(petrinex_parquet: Path) -> pd.DataFrame:
    """Production commercialisée par puits, mois et opérateur.

    Même périmètre que production_universe, avec l'opérateur en plus : c'est la
    clé de répartition des volumes déclarés au niveau installation.
    """
    df = pd.read_parquet(
        petrinex_parquet,
        columns=[
            "uwi",
            "operator_id",
            "date",
            "product_type",
            "activity_type",
            "volume_boe",
        ],
    )
    df = df.dropna(subset=["uwi", "operator_id"])

    activite = df["activity_type"].astype(str)
    produit = df["product_type"].astype(str)
    df = df[
        (activite == ACTIVITY_TYPE_RETENU) & (~produit.isin(PRODUCT_TYPES_EXCLUS))
    ].copy()

    est_gaz = df["product_type"].astype(str) == "GAS"
    df.loc[est_gaz, "volume_boe"] = df.loc[est_gaz, "volume_boe"] * FACTEUR_ECHELLE_GAZ

    df["uwi"] = df["uwi"].astype(str)
    df["operator_id"] = df["operator_id"].astype(str)
    df["date_key"] = _date_key(df["date"])

    grp = (
        df.groupby(["uwi", "operator_id", "date_key"], observed=True)["volume_boe"]
        .sum()
        .reset_index()
    )
    return grp[grp["volume_boe"] > 0].reset_index(drop=True)


def calculer_emissions(activite: pd.DataFrame) -> pd.DataFrame:
    """CO2 et CH4 en tonnes, ligne à ligne, selon la voie d'émission."""
    volume = activite["volume_m3"].to_numpy(dtype="float64")
    voie = activite["activity_type"].to_numpy()

    co2_kg = np.zeros(len(activite), dtype="float64")
    ch4_kg = np.zeros(len(activite), dtype="float64")

    # Carburant : combustion quasi complète.
    est_fuel = voie == "FUEL"
    co2_kg[est_fuel] = volume[est_fuel] * CO2_COMBUSTION_KG_M3
    ch4_kg[est_fuel] = volume[est_fuel] * CH4_COMBUSTION_KG_M3

    # Évacuation : rien ne brûle, le gaz part tel quel.
    est_vent = voie == "VENT"
    co2_kg[est_vent] = volume[est_vent] * FRACTION_CO2_GAZ * DENSITE_CO2_KG_M3
    ch4_kg[est_vent] = volume[est_vent] * FRACTION_CH4_GAZ * DENSITE_CH4_KG_M3

    # Torchage : la part brûlée devient du CO2, le reste s'échappe en CH4.
    est_flare = voie == "FLARE"
    co2_kg[est_flare] = volume[est_flare] * RENDEMENT_TORCHE * CO2_COMBUSTION_KG_M3
    ch4_kg[est_flare] = (
        volume[est_flare]
        * (1.0 - RENDEMENT_TORCHE)
        * FRACTION_CH4_GAZ
        * DENSITE_CH4_KG_M3
    )

    out = activite.copy()
    out["co2_tonnes"] = co2_kg / KG_PAR_TONNE
    out["ch4_tonnes"] = ch4_kg / KG_PAR_TONNE
    return out


def repartir_installations(
    emissions: pd.DataFrame, production: pd.DataFrame
) -> tuple[pd.DataFrame, float]:
    """Redescend les émissions d'installation sur les puits du même opérateur.

    La clé est (opérateur, mois) et le prorata se fait sur le volume produit.
    Renvoie les émissions au grain puits, et la part de CO2eq qui n'a pu être
    répartie faute de production en face.
    """
    directes = emissions[~emissions["est_installation"]].copy()
    installations = emissions[emissions["est_installation"]].copy()

    directes = (
        directes.groupby(["uwi", "date_key"], observed=True)[["co2_tonnes", "ch4_tonnes"]]
        .sum()
        .reset_index()
    )
    directes["origine"] = "puits"

    if installations.empty:
        directes["co2eq"] = directes["co2_tonnes"] + directes["ch4_tonnes"] * CO2EQ_CH4
        return directes, 0.0

    par_operateur = (
        installations.groupby(["operator_id", "date_key"], observed=True)[
            ["co2_tonnes", "ch4_tonnes"]
        ]
        .sum()
        .reset_index()
    )

    # Poids de chaque puits dans la production de son opérateur, ce mois-là.
    production = production.copy()
    total = production.groupby(["operator_id", "date_key"], observed=True)[
        "volume_boe"
    ].transform("sum")
    production["poids"] = production["volume_boe"] / total

    reparties = production.merge(par_operateur, on=["operator_id", "date_key"], how="inner")
    reparties["co2_tonnes"] = reparties["co2_tonnes"] * reparties["poids"]
    reparties["ch4_tonnes"] = reparties["ch4_tonnes"] * reparties["poids"]
    reparties = reparties[["uwi", "date_key", "co2_tonnes", "ch4_tonnes"]]
    reparties["origine"] = "installation répartie"

    # Certaines installations appartiennent à un opérateur qui ne produit rien ce
    # mois-là : usines de traitement, opérateurs intermédiaires. Les répartir sur
    # les puits d'un producteur tiers serait faux. Elles restent donc à leur code
    # installation, ce qui préserve le total et les isole dans le seau « hors
    # référentiel AER » côté mart, où elles sont à leur place.
    couples_produisants = production[["operator_id", "date_key"]].drop_duplicates()
    orphelines = installations.merge(
        couples_produisants, on=["operator_id", "date_key"], how="left", indicator=True
    )
    orphelines = orphelines[orphelines["_merge"] == "left_only"]
    orphelines = (
        orphelines.groupby(["uwi", "date_key"], observed=True)[
            ["co2_tonnes", "ch4_tonnes"]
        ]
        .sum()
        .reset_index()
    )
    orphelines["origine"] = "installation non répartie"
    co2eq_orphelin = float(
        (orphelines["co2_tonnes"] + orphelines["ch4_tonnes"] * CO2EQ_CH4).sum()
    )

    tout = pd.concat([directes, reparties, orphelines], ignore_index=True)
    tout["co2eq"] = tout["co2_tonnes"] + tout["ch4_tonnes"] * CO2EQ_CH4
    return tout, co2eq_orphelin


def main() -> int:
    print(f"Racine projet : {ROOT}")
    if not PETRINEX_PARQUET.exists():
        print(f"[ERREUR] Fichier requis absent : {PETRINEX_PARQUET}", file=sys.stderr)
        return 1

    activite = charger_activite(PETRINEX_PARQUET)
    if activite.empty:
        print(
            "[ERREUR] Aucune ligne FUEL, VENT ou FLARE dans le parquet. Le script 01\n"
            "         doit les conserver via KEEP_ACTIVITIES.",
            file=sys.stderr,
        )
        return 1

    presentes = sorted(activite["activity_type"].unique())
    print(f"  Voies d'émission présentes : {', '.join(presentes)}")
    if "FLARE" not in presentes:
        print(
            "  [INFO] Aucune ligne FLARE. Le torchage est absent de l'extraction\n"
            "         courante ; relancer le script 01 pour l'inclure."
        )

    part_installations = (
        activite.loc[activite["est_installation"], "volume_m3"].sum()
        / activite["volume_m3"].sum()
    )
    print(f"  Volume déclaré au niveau installation : {part_installations:.1%}")

    emissions = calculer_emissions(activite)
    production = charger_production(PETRINEX_PARQUET)
    print(f"  Couples (puits, mois) producteurs : {len(production):,}")

    total_declare = float(
        (emissions["co2_tonnes"] + emissions["ch4_tonnes"] * CO2EQ_CH4).sum()
    )
    reparties, co2eq_orphelin = repartir_installations(emissions, production)

    detail = (
        reparties.pivot_table(
            index=["uwi", "date_key"],
            columns="origine",
            values=["co2_tonnes", "ch4_tonnes", "co2eq"],
            aggfunc="sum",
            fill_value=0.0,
        )
    )
    detail.columns = [
        f"{mesure}__{origine}" for mesure, origine in detail.columns
    ]
    detail = detail.reset_index()

    origines = ("puits", "installation répartie", "installation non répartie")
    for origine in origines:
        for mesure in ("co2_tonnes", "ch4_tonnes", "co2eq"):
            colonne = f"{mesure}__{origine}"
            if colonne not in detail.columns:
                detail[colonne] = 0.0

    df = pd.DataFrame()
    df["uwi"] = detail["uwi"].astype("string")
    df["date_key"] = detail["date_key"].astype("int64")
    df["co2_tonnes"] = sum(detail[f"co2_tonnes__{o}"] for o in origines)
    df["ch4_tonnes"] = sum(detail[f"ch4_tonnes__{o}"] for o in origines)
    df["co2eq_total"] = df["co2_tonnes"] + df["ch4_tonnes"] * CO2EQ_CH4
    df["scope"] = SCOPE

    # Hors contrat dbt : permet de distinguer mesure et allocation dans le rapport.
    df["co2eq_declare_puits"] = detail["co2eq__puits"]
    df["co2eq_reparti_installation"] = detail["co2eq__installation répartie"]
    df["co2eq_hors_puits"] = detail["co2eq__installation non répartie"]

    df = df.reset_index(drop=True)

    # --- Contrôle qualité ------------------------------------------------- #
    total_boe = production["volume_boe"].sum()
    total_co2 = df["co2_tonnes"].sum()
    total_ch4 = df["ch4_tonnes"].sum()
    total_co2eq = df["co2eq_total"].sum()
    conserve = total_co2eq / total_declare if total_declare else 0.0

    print(f"  Puits porteurs d'émissions : {df['uwi'].nunique():,}")
    print(f"  CO2   : {total_co2 / 1e6:8.3f} Mt sur la période")
    print(f"  CH4   : {total_ch4 / 1e6:8.4f} Mt sur la période")
    print(f"  CO2eq : {total_co2eq / 1e6:8.3f} Mt sur la période")
    print(f"  Intensité CO2eq : {total_co2eq / total_boe:.4f} t/boe (mesurée)")
    print(
        f"  Conservation du total déclaré : {conserve:.4%} "
        f"(non réparti : {co2eq_orphelin / 1e6:.4f} Mt)"
    )
    if conserve < 0.95:
        print(
            "  [ALERTE] Plus de 5 % du CO2eq déclaré n'a pas trouvé de puits\n"
            "           producteur en face. Vérifier l'appariement opérateur.",
            file=sys.stderr,
        )

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PARQUET, index=False)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8")
    print(f"\nÉcrit : {OUT_PARQUET}  ({len(df):,} lignes)")
    print(f"Écrit : {OUT_CSV}")
    print(df.head().to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
