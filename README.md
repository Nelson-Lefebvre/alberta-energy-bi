# Alberta Energy Operations Intelligence

**End-to-end analytics on the Alberta oil & gas basin** — from raw regulatory filings to
an executive report. 7.2M Petrinex rows, 598,396 wells from the AER register, a star
schema in DuckDB, and a five-page Power BI report.

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![dbt](https://img.shields.io/badge/dbt-1.11-FF694B?logo=dbt&logoColor=white)
![DuckDB](https://img.shields.io/badge/DuckDB-1.10-FFF000?logo=duckdb&logoColor=black)
![Power BI](https://img.shields.io/badge/Power%20BI-PBIP-F2C811?logo=powerbi&logoColor=black)
![Tests](https://img.shields.io/badge/dbt%20build-42%20pass%20%C2%B7%200%20error-2E7D32)
![Status](https://img.shields.io/badge/status-work%20in%20progress-orange)

![Executive summary page of the Power BI report](docs/screenshots/p1_executive.png)

| | |
|---|---|
| **Period** | 24 months · May 2024 → April 2026 |
| **Production** | 3.54 Bn boe · 4.85M boe/day |
| **Wells** | 598,396 on the register · 149,340 producing |
| **Operators** | 3,015 |
| **Estimated revenue** | CAD 137.7 Bn · 73.9 $/boe on liquids |
| **OPEX per barrel** | $17.48 |
| **Scope 1 CO₂** | 194.6 Mt · 0.0550 tCO₂/boe |

> Production, prices and locations are **real**. Costs and emissions are **simulated**
> from those volumes, with factors anchored to the *AER Annual Report 2023* and the
> *NIR 2024*. Every trade-off is listed at the bottom of this page.

---

## What this project demonstrates

| Skill | Where to see it |
|---|---|
| **Raw regulatory ingestion** | ST37 ships as tab-delimited text with no coordinates: parsing, UWI reconstruction, **Dominion Land Survey → latitude/longitude conversion** |
| **Dimensional modelling** | Star schema, 3 facts and 3 dimensions, a conformed `dim_region`, grain stated explicitly per table |
| **Data quality** | 43 dbt tests, four of them **plausibility** tests written after two real regressions |
| **Analytics engineering** | dbt Core on DuckDB, staging → marts, generated lineage |
| **BI and DAX** | 27 measures, ratios kept at one grain, 3-role RLS, a **PBIP** project versioned as TMDL/JSON — reviewable in a pull request, not an opaque binary |
| **Oil & gas domain** | BOE, WCS, DLS, UWI, Scope 1, GWP100, AER well statuses |
| **Analytical debugging** | see below — the most interesting part |

---

## Two bugs, and why they are the best part

The pipeline produced believable numbers and 39 dbt tests were green. Two of those
numbers were wrong anyway.

### 1. A regional spread that did not exist

OPEX per barrel ranged from $4.03 to $14.52 depending on the region. Tempting to read
as a difference in cost structure. In fact:

| Region | Gas share | OPEX/boe |
|---|---|---|
| Nord | 16.9 % | $14.52 |
| Peace River | 76.7 % | $4.08 |
| Central | 76.9 % | $4.03 |

The ratio was a **perfect inverse function of gas share** — the signature of a unit
problem, not a business signal. Petrinex reports gas in 10³m³, not m³. The rescaling
was applied in the production branch of the pipeline but not in the cost branch, so
numerator and denominator were not speaking the same unit.

After the fix, OPEX/boe sits between **$17.38 and $17.61 across all five regions** — the
spread was gone entirely.

### 2. A denominator that did not cover its numerator

Emissions were generated for every Petrinex row, commercialised production or not.
Production excluded fuel gas, flared and vented volumes, and shut-in wells. The result:
**11,943 wells carried 16.1 Mt of CO₂ with no production underneath them**, inflating
carbon intensity from 0.0551 to 0.0597.

### The fix, and the safety net

One cause in both cases: a scope rule applied in one branch of the pipeline but not its
siblings. The definition now lives in a single place
(`scripts/production_universe.py`), imported by both generators and aligned with the
dbt mart.

Then four plausibility tests, because structural tests could not see any of it — the
tables were valid, the keys present, referential integrity intact:

| Test | What it locks down |
|---|---|
| `assert_univers_partages` | costs, emissions and production cover the same (well, month) set |
| `assert_facteur_conversion_boe` | 6.290 boe/m³ for liquids · 5.885 boe/10³m³ for gas |
| `assert_opex_par_boe_plausible` | OPEX/boe within 8–30, **per region** |
| `assert_intensite_carbone_plausible` | intensity within 0.050–0.060, **per region** |

Grain is the whole point of the last two. During the bug the **global** OPEX/boe was
$9.21 — inside the band. An aggregate check would have passed it. Only the per-region
split exposed the defect.

Replayed against the pre-fix database, these tests return **3 regions out of band** on
OPEX, **1 on intensity**, and **413,760 orphaned (well, month) pairs** on scope. They
would have failed the build.

---

## The report

Five pages, one shared conformed region slicer, 3-role row-level security.

### Production & Wells

![Production and wells](docs/screenshots/p2_production.png)

ArcGIS map of geolocated wells — coordinates rebuilt from the DLS — counters for
producing, active and abandoned wells, monthly production against its 3-month moving
average, and per-UWI detail.

> This capture is filtered to **2025**, so totals cover the year rather than the full
> 24 months. The map tiles failed to load at export time.

### Costs & Profitability

![Costs and profitability](docs/screenshots/p3_costs.png)

Revenue, total and per-barrel OPEX, operating margin, and an OPEX waterfall by region.
OPEX/boe sitting flat near $17.5 across all five regions is the visual check that no
unit bias remains between numerator and denominator.

### ESG Performance

![ESG performance](docs/screenshots/p4_esg.png)

Scope 1 CO₂ and CO₂e (CH₄ × 28, GWP100 AR6), carbon intensity, and a gauge against the
Alberta 2030 target of 0.040 tCO₂/boe — a gap of +37.5 %. The conversion can be checked
by hand: 194.6 + 2.21 × 28 = 256.5 Mt.

### Forecast & Trends

![Forecast and trends](docs/screenshots/p5_forecast.png)

Native Power BI forecast, 6 months ahead at 95 % confidence, framed by the year-over-year
trend (+3.4 %) and the coefficient of variation (5.4 %).

---

## Architecture

```
                 Public sources
  ┌────────────┬──────────────┬─────────────────┬───────────────┐
  │ Petrinex   │  AER ST37    │ Petrinex ref.   │ Yahoo Finance │
  │ Volumetric │  Well List   │ (BA / Field)    │ + Bank of Can.│
  └─────┬──────┴──────┬───────┴────────┬────────┴──────┬────────┘
        │             │                │               │
        ▼             ▼                ▼               ▼
 ┌──────────────────────────────────────────────────────────────┐
 │  Python (scripts 01–05) → Parquet in data/processed/          │
 │  pandas · numpy · requests · pyarrow                          │
 └───────────────────────────┬──────────────────────────────────┘
                             ▼
 ┌──────────────────────────────────────────────────────────────┐
 │  dbt Core + DuckDB   (staging → marts, tests, lineage)        │
 │  data/energy.duckdb                                           │
 └───────────────────────────┬──────────────────────────────────┘
                             ▼
 ┌──────────────────────────────────────────────────────────────┐
 │  Power BI Desktop — PBIP  (star · 27 DAX measures · RLS)      │
 └──────────────────────────────────────────────────────────────┘
```

### Sources

| Source | Content | Format |
|---|---|---|
| **Petrinex – Conventional Volumetrics** | Monthly AB production (24 months) | ZIP→CSV |
| **AER ST37 – List of Wells** | Well register (DLS, status, licence) | ZIP→TXT |
| **Petrinex – Business Associate / Field Codes** | Operator and field reference data | CSV |
| **Yahoo Finance – WTI (CL=F)** | Monthly WTI price, basis for WCS | JSON |
| **Bank of Canada – FXUSDCAD** | Monthly USD/CAD exchange rate | JSON |

Full URLs in [`docs/DOCUMENTATION.md`](docs/DOCUMENTATION.md).

### Python pipeline

| Script | Output | Role |
|---|---|---|
| `01_ingest_petrinex.py` | `petrinex24.parquet` | Parallel download, nested unzip, cleaning, BOE conversion |
| `02_ingest_aer_wells.py` | `dim_puits.parquet` | ST37 parsing, UWI reconstruction, **DLS→lat/lon**, reference joins |
| `03_ingest_prices.py` | `dim_prix.parquet` | WTI + USD/CAD → monthly WCS in CAD |
| `04_generate_costs.py` | `fact_couts.parquet` | Simulated OPEX/CAPEX (winter seasonality, incidents) |
| `05_generate_emissions.py` | `fact_emissions.parquet` | Scope 1 CO₂/CH₄/CO₂e (NIR 2024 factors) |

`production_universe.py` holds the **canonical scope** shared by 04 and 05 — the gas
unit correction and the commercialised-production filter, identical to the dbt mart.
That module is the fix for bug #1.

**ST37 ↔ Petrinex UWI coverage: 99.0 %** (1,426 producing wells outside the register,
out of 149,340).

---

## Data model

![Star schema](docs/diagramme_bdd.png)

> The diagram is two changes behind: `dim_region` is missing, and
> `fact_production_enriched` now also carries `opex_cad` and `co2_tonnes`. Grains, keys
> and cardinalities are still accurate.

- **Staging** (views): `stg_petrinex_production`, `stg_aer_wells`, `stg_eia_prices`,
  `stg_costs`, `stg_emissions`
- **Marts** (tables): `dim_date`, `dim_puits`, `dim_region`,
  `fact_production_enriched`, `fact_kpis_mensuels`, `fact_emissions_scope`

**`dim_region` is a conformed dimension.** `dim_puits` and `fact_kpis_mensuels` are not
related to each other, so a slicer placed on a fact's own column would filter that fact
alone. Pages filter `dim_region[region]`, which reaches both branches.

**`fact_production_enriched`** (4,342,506 rows, grain well × month × product) carries
volume, revenue, OPEX and CO₂. The last two are allocated pro rata by volume from the
(well, month) simulation — an **exact** allocation, since the scripts compute
`opex = rate × volume` with the rate constant over a pair. That fine grain is what makes
OPEX and intensity filterable by operator, status, well and product.

`dbt build` → **42 PASS · 1 WARN · 0 ERROR** across 43 nodes. The warning is a
relationship test returning 24 rows: one producing UWI absent from `dim_puits` after
case-insensitive deduplication, with no effect in Power BI, which matches keys the same
way. Full lineage: [`docs/dbt/index.html`](docs/dbt/index.html).

---

## DAX measures

```dax
OPEX par boe =                          -- the headline O&G metric
DIVIDE ( [OPEX Total CAD], [Production BOE] )

OPEX Total CAD =                        -- grain: well × month × product
SUM ( fact_production_enriched[opex_cad] )

Intensité carbone =                     -- ESG: tCO₂ / boe
DIVIDE ( [CO2 Scope 1 (t)], [Production BOE] )

Marge Opérationnelle % =                -- opex-only, NOT a net margin
DIVIDE ( [Revenu Estimé CAD] - [OPEX Total CAD], [Revenu Estimé CAD] )

Tendance YoY % =                        -- last 12 months vs the 12 before
DIVIDE ( [Production 12 derniers mois] - [Production 12 mois précédents],
         [Production 12 mois précédents] )
```

**27 measures** across 5 display folders (Production, Finance, ESG, Time Intelligence,
Wells). **3-role RLS** (Nord / Sud / Admin) on `dim_puits`, `fact_kpis_mensuels`,
`fact_emissions_scope` and `dim_region`.

Every ratio takes numerator and denominator **from the same fact**. A ratio whose two
terms live at different grains freezes silently as soon as someone applies a slicer that
only one of them can reach — the main trap in this model.

---

## Reproducing

```powershell
# 1. Environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Manual raw files in data/raw/ :
#    ST37.zip, ba_codes.csv, field_codes.csv

# 3. Python pipeline (order matters)
python scripts\01_ingest_petrinex.py
python scripts\02_ingest_aer_wells.py
python scripts\03_ingest_prices.py
python scripts\04_generate_costs.py
python scripts\05_generate_emissions.py

# 4. dbt transformation
cd dbt_project\energy_analytics
dbt build --profiles-dir .
dbt docs generate --profiles-dir .

# 5. Open the reporting\ folder in Power BI Desktop, then Refresh
```

**`profiles.yml` is not versioned** (it holds a machine path). Create one in
`dbt_project/energy_analytics/`:

```yaml
energy_analytics:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: "../../data/energy.duckdb"
      threads: 4
```

Two things block a fresh clone: staging views read the Parquet files by **relative
path**, so dbt must be run from `dbt_project/energy_analytics`; and the database path is
**hard-coded** in the semantic model's M partitions, so it needs editing.

The report is a **PBIP** project rather than a `.pbix`: the model is TMDL and the visuals
are JSON, so both are readable and diffable in code review.

---

## Assumed trade-offs

- **Basin view, not operator view.** The data covers all 3,015 operators in the province.
  This is basin analysis of the kind a regulator or a market analyst produces, not the
  control centre of a single company.
- **Gas is not monetised.** WCS is a heavy-oil benchmark; with no AECO price available,
  gas counts toward volumes and emissions but not revenue. Valuing it at the oil price
  would have overstated it four- to fivefold. Margin is therefore computed on
  liquids-only revenue, which makes it **conservative**.
- **Production scope.** Only commercialised production is kept (`PROD`, excluding
  `WATER`): fuel gas, vented and flared volumes, and shut-in wells are excluded. Costs,
  emissions and production share that scope — a model constraint, not a detail.
- **1,426 producing wells outside the AER register** (~1 % of production): present in
  Petrinex, absent from the ST37 extract. Assigned to an explicit bucket rather than
  hidden, so totals stay correct and the gap stays visible.
- **ST37** ships as tab-delimited text with no coordinates or names → coordinates
  converted from the DLS, names restored through the Petrinex reference files.
- **Prices**: EIA and Alpha Vantage require API keys → replaced by Yahoo Finance and the
  Bank of Canada (keyless), with WCS = WTI − $17.50.
- **CAPEX is indicative**: simulated log-normally, it illustrates cost structure and is
  **not calibrated** against real Alberta drilling costs.

---

## Roadmap

The pipeline runs end to end and the report is usable. Still open:

- **CAPEX** — needs recalibrating (~$33k/well against a real $2–8M), then surfacing on
  the Costs page, which currently shows OPEX only.
- **Freshness** — data stops at April 2026; refresh is not automated (`airflow_dags/` is
  a reserved location, not a DAG).
- **Inactive well inventory** — 449,057 wells with no production, 66,984 of them
  abandoned: 75 % of the register. Reclamation liability is a major Alberta topic and the
  data is already here; the dedicated page is still to be built.
- **UWI slicers** — ~598k values on two pages, to be replaced with a search control.
- **Publication** — the report is not yet published to the web.

---

*Data Analyst portfolio project — Calgary 2026.*
