"""
Racine des données, commune aux scripts 00 à 05.

En local, rien ne change : data/ à la racine du projet. Sur Databricks, le Job passe
--data-dir /Volumes/workspace/alberta_bronze/landing et les mêmes scripts lisent et
écrivent dans le Volume Unity Catalog.

--no-csv coupe les exports CSV. Sur Databricks ils doubleraient le temps d'écriture
dans le Volume sans que personne ne les lise : la couche bronze charge les Parquet.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

_DEFAUT = Path(__file__).resolve().parent.parent / "data"

_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument(
    "--data-dir",
    default=os.environ.get("ALBERTA_DATA_DIR", str(_DEFAUT)),
    help="Racine des données : contient raw/ et processed/.",
)
_parser.add_argument("--no-csv", action="store_true", help="N'écrire que les Parquet.")
# parse_known_args : un argument ajouté par la plateforme ne fait pas échouer le script.
_args, _ = _parser.parse_known_args()

DATA_DIR = Path(_args.data_dir)
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
ECRIRE_CSV = not _args.no_csv
