# Alberta Energy Operations Intelligence

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![dbt](https://img.shields.io/badge/dbt-1.11-FF694B?logo=dbt&logoColor=white)
![DuckDB](https://img.shields.io/badge/DuckDB-1.10-FFF000?logo=duckdb&logoColor=black)
![Power BI](https://img.shields.io/badge/Power%20BI-Desktop-F2C811?logo=powerbi&logoColor=black)

Dashboard analytique end‑to‑end simulant le centre de pilotage d'une opération
**upstream Oil & Gas en Alberta**, à partir de **données réelles et publiques**
(AER / Petrinex) enrichies de modules financiers et ESG.


---

## 1. Contexte métier

Calgary est le cœur du secteur énergétique canadien : la majorité des sièges sociaux
O&G et des postes de Data Analyst du domaine y sont concentrés. Ce projet reproduit
la chaîne analytique type d'un opérateur upstream — de l'ingestion réglementaire
brute jusqu'au tableau de bord exécutif.

Les **volumes de production** proviennent des déclarations mensuelles **Petrinex**
(24 mois glissants, ~7,2 M de lignes), géolocalisées via le registre des puits
**AER ST37**. Les volumes bruts (m³) sont convertis en **BOE** selon les facteurs
standard AER, puis valorisés au prix **WCS** (Western Canadian Select) en dollars
canadiens.

Trois modules d'analyse sont superposés à la production : un module **financier**
(OPEX/CAPEX, OPEX par baril, marge), un module **ESG** (émissions Scope 1, intensité
carbone) et un module de **prévision**. L'ensemble alimente un modèle en étoile
exploité dans Power BI.

---

## 2. Architecture

```
                Sources publiques
  ┌────────────┬──────────────┬─────────────────┬───────────────┐
  │ Petrinex   │  AER ST37    │ Petrinex réf.   │ Yahoo Finance │
  │ Volumetric │  Well List   │ (BA / Field)    │ + Bank of Can.│
  └─────┬──────┴──────┬───────┴────────┬────────┴──────┬────────┘
        │             │                │               │
        ▼             ▼                ▼               ▼
 ┌──────────────────────────────────────────────────────────────┐
 │  Python (scripts 01–05) → Parquet dans data/processed/        │
 │  pandas · numpy · requests · pyarrow                          │
 └───────────────────────────┬──────────────────────────────────┘
                             ▼
 ┌──────────────────────────────────────────────────────────────┐
 │  dbt Core + DuckDB   (staging → marts, tests, lineage)        │
 │  data/energy.duckdb                                           │
 └───────────────────────────┬──────────────────────────────────┘
                             ▼
 ┌──────────────────────────────────────────────────────────────┐
 │  Power BI Desktop  (schéma étoile · 12 mesures DAX · RLS)     │
 └──────────────────────────────────────────────────────────────┘
```

---

## 3. Sources de données

| Source | Contenu | Format | URL |
|---|---|---|---|
| **Petrinex – Conventional Volumetrics** | Production mensuelle AB (24 mois) | ZIP→CSV | `petrinex.gov.ab.ca/publicdata/API/Files/AB/Vol/{YYYY-MM}/CSV` |
| **AER ST37 – List of Wells** | Registre des puits (localisation DLS, statut, licence) | ZIP→TXT | `static.aer.ca/prd/documents/sts/st37/ST37.zip` |
| **Petrinex – Business Associate** | Codes BA → noms d'opérateurs | CSV | `petrinex.gov.ab.ca/bbreports/PRABAIdentifiers.csv` |
| **Petrinex – Field Codes** | Codes champ → noms de champs | CSV | `petrinex.gov.ab.ca/bbreports/PRAFieldCodes.csv` |
| **Yahoo Finance – WTI (CL=F)** | Prix WTI mensuel (base WCS) | JSON | `query1.finance.yahoo.com/v8/finance/chart/CL=F` |
| **Banque du Canada – FXUSDCAD** | Taux de change USD/CAD mensuel | JSON | `bankofcanada.ca/valet/observations/FXUSDCAD/json` |

> Les modules **coûts** (OPEX/CAPEX) et **émissions** sont **simulés** à partir des
> volumes réels, avec des fourchettes calées sur l'*AER Annual Report 2023* et les
> facteurs du *NIR 2024* (documenté dans `scripts/04` et `scripts/05`).

---

## 4. Pipeline Python (`scripts/`)

| Script | Sortie | Rôle |
|---|---|---|
| `01_ingest_petrinex.py` | `petrinex24.parquet` / `.csv` | Téléchargement parallèle, double dézip, nettoyage, conversion BOE |
| `02_ingest_aer_wells.py` | `dim_puits.parquet` | Parsing ST37, reconstruction UWI, **conversion DLS→lat/lon**, jointures BA/Field |
| `03_ingest_prices.py` | `dim_prix.parquet` | WTI (Yahoo) + USD/CAD (BoC) → WCS CAD mensuel |
| `04_generate_costs.py` | `fact_couts.parquet` | OPEX/CAPEX simulés (saisonnalité hiver, incidents) |
| `05_generate_emissions.py` | `fact_emissions.parquet` | CO₂/CH₄/CO₂eq Scope 1 (facteurs NIR 2024) |

**Résultats validés** : couverture UWI ST37 ↔ Petrinex **91,8 %** · OPEX/boe médian
**16,7 $** (cible 8–30) · intensité carbone **0,055 tCO₂/boe**.

---

## 5. Modèle de données (dbt → DuckDB)

Schéma en étoile, matérialisé dans `data/energy.duckdb` :

- **Staging** (vues) : `stg_petrinex_production`, `stg_aer_wells`, `stg_eia_prices`,
  `stg_costs`, `stg_emissions`
- **Marts** (tables) : `dim_date`, `dim_puits`, `fact_production_enriched`,
  `fact_kpis_mensuels`, `fact_emissions_scope`

`dbt build` → **37 PASS / 0 ERROR** (tests `not_null`, `unique`, `accepted_values`,
`relationships`). 📚 Lineage complet : [`docs/dbt/index.html`](docs/dbt/index.html).

---

## 6. Mesures DAX (extraits)

```dax
OPEX par Baril =                       -- métrique phare O&G
DIVIDE([OPEX Total CAD], [Production Nette BOE], 0)

Revenu Estimé CAD =
SUMX(fact_production_enriched,
     fact_production_enriched[volume_boe] * RELATED(dim_prix[wcs_cad]))

Intensité Carbone =                    -- ESG : tCO₂ / boe
DIVIDE(SUM(fact_emissions[co2_tonnes]), [Production Nette BOE], 0)

Variance YTD % =
DIVIDE([Production YTD] - [Production YTD LY], [Production YTD LY], 0)
```

12 mesures au total · paramètre What‑If « Prix WCS hypothétique » · RLS 3 rôles
(Nord / Sud / Admin).

---

## 7. Captures d'écran

| Page | Aperçu |
|---|---|
| P1 — Executive Summary | _`docs/screenshots/p1_executive.png`_ |
| P2 — Production Operations (carte) | _`docs/screenshots/p2_production.png`_ |
| P3 — Cost & Financial | _`docs/screenshots/p3_costs.png`_ |
| P4 — ESG & Carbon | _`docs/screenshots/p4_esg.png`_ |
| P5 — Forecast | _`docs/screenshots/p5_forecast.png`_ |

---

## 8. Reproduire le projet

```powershell
# 1. Environnement
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Données brutes manuelles dans data/raw/ :
#    ST37.zip, ba_codes.csv, field_codes.csv  (URLs section 3)

# 3. Pipeline Python
python scripts\01_ingest_petrinex.py
python scripts\02_ingest_aer_wells.py
python scripts\03_ingest_prices.py
python scripts\04_generate_costs.py
python scripts\05_generate_emissions.py

# 4. Transformation dbt
cd dbt_project\energy_analytics
dbt build --profiles-dir .
dbt docs generate --profiles-dir .

# 5. Ouvrir powerbi\alberta_energy_bi.pbix et rafraîchir
```

> `01_ingest_petrinex.py` télécharge ~13 M de lignes brutes ; les autres scripts
> lisent les Parquet produits en amont. Voir `scripts/0X_*.py` pour les paramètres.

---

## 9. Écarts assumés vs spécification initiale

- **ST37** : publié en TXT tabulé (pas Excel), sans lat/lon ni noms → coordonnées
  **converties depuis le DLS**, noms restitués via les référentiels Petrinex.
- **Prix** : EIA + Alpha Vantage exigent des clés API → remplacés par **Yahoo
  Finance + Banque du Canada** (keyless), WCS = WTI − 17,5 $ conservé.

---

*Projet portfolio Data Analyst — Calgary 2026.*
