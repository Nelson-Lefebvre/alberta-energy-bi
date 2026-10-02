"""
00_download_raw.py : fichiers bruts lus par 02_ingest_aer_wells.py

Remplace les trois curl manuels de la documentation. Sur Databricks, aucune commande
ne s'exécute entre deux tâches : le Job doit pouvoir repartir d'un Volume vide.

Sortie : <data-dir>/raw/ST37.zip, ba_codes.csv, field_codes.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

# Databricks lance le fichier sans garantir que son dossier soit dans sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _paths import RAW_DIR  # noqa: E402

SOURCES = {
    "ST37.zip": "https://static.aer.ca/prd/documents/sts/st37/ST37.zip",
    "ba_codes.csv": "https://www.petrinex.gov.ab.ca/bbreports/PRABAIdentifiers.csv",
    "field_codes.csv": "https://www.petrinex.gov.ab.ca/bbreports/PRAFieldCodes.csv",
}
HEADERS = {"User-Agent": "Mozilla/5.0"}
TIMEOUT = 120


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for nom, url in SOURCES.items():
        reponse = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        # Une erreur HTTP fait échouer la tâche : le Job la relance (max_retries).
        reponse.raise_for_status()
        (RAW_DIR / nom).write_bytes(reponse.content)
        print(f"{nom:<16} {len(reponse.content) / 1_048_576:6.1f} Mo  <- {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
