# Alberta Energy Operations Intelligence

I wanted to see how far I could get using only what Alberta publishes: the monthly
production filings every operator has to submit to Petrinex, and the provincial well
register. The result is a Power BI report, but most of the work sits upstream of it.
7.2M rows of production, 598,396 wells, a star schema in DuckDB, five report pages.

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![dbt](https://img.shields.io/badge/dbt-1.11-FF694B?logo=dbt&logoColor=white)
![DuckDB](https://img.shields.io/badge/DuckDB-1.10-FFF000?logo=duckdb&logoColor=black)
![Power BI](https://img.shields.io/badge/Power%20BI-PBIP-F2C811?logo=powerbi&logoColor=black)
![Tests](https://img.shields.io/badge/dbt%20build-42%20pass%20%C2%B7%200%20error-2E7D32)
![Status](https://img.shields.io/badge/status-work%20in%20progress-orange)

![Executive summary page of the Power BI report](docs/screenshots/p1_executive.png)

| | |
|---|---|
| Period | 24 months, May 2024 to April 2026 |
| Production | 3.54 Bn boe, or 4.85M boe/day |
| Wells | 598,396 on the register, 149,340 producing |
| Operators | 3,015 |
| Estimated revenue | CAD 137.7 Bn, 73.9 $/boe on liquids |
| OPEX per barrel | $17.48 |
| Scope 1 CO₂ | 194.6 Mt, 0.0550 tCO₂/boe |

Production volumes, prices and well locations are real. Costs and emissions are
simulated from those volumes using factors from the AER Annual Report 2023 and the
NIR 2024. Everything I had to assume is listed near the bottom.

---

## What's actually in here

The ingestion is the part I'd point at first. ST37, the well register, ships as
tab-delimited text with no coordinates and no operator names. So there's UWI
reconstruction, a Dominion Land Survey to lat/lon conversion, and joins back to the
Petrinex reference files to recover names. That gets 99.0% coverage against the
production data.

Then a star schema in dbt on DuckDB: three facts, three dimensions, one conformed
region dimension, with the grain written down for each table because I got burned by
not doing that. 43 tests, four of which check whether the numbers are plausible rather
than whether the tables are well formed. More on those below.

On the reporting side, 27 DAX measures, row-level security across three roles, and the
whole thing saved as a PBIP project rather than a .pbix. That last choice matters more
than it sounds: the model is TMDL and the visuals are JSON, so a reviewer can read a
diff instead of opening Power BI and clicking around.

---

## The two bugs I'd talk about in an interview

The pipeline produced numbers that looked fine, and 39 dbt tests were green. Two of
those numbers were wrong.

### A regional spread that wasn't real

OPEX per barrel ranged from $4.03 to $14.52 depending on the region. I spent a while
trying to explain that as a difference in cost structure, which in hindsight was the
mistake. Then I lined it up against gas share:

| Region | Gas share | OPEX/boe |
|---|---|---|
| Nord | 16.9 % | $14.52 |
| Peace River | 76.7 % | $4.08 |
| Central | 76.9 % | $4.03 |

An almost perfect inverse relationship. Real cost differences don't behave like that.
Unit errors do.

Petrinex reports gas in 10³m³, not m³. The rescaling was there in the production branch
of the pipeline and missing from the cost branch, so the numerator and the denominator
of the ratio weren't in the same unit. After fixing it, OPEX/boe sits between $17.38 and
$17.61 across all five regions and the spread is gone.

### A denominator that didn't cover its numerator

The emissions script generated a row for every Petrinex record. The production mart
excludes fuel gas, flared and vented volumes, and shut-in wells. Those two scopes were
never reconciled, so 11,943 wells carried 16.1 Mt of CO₂ with nothing underneath them.
Carbon intensity read 0.0597 instead of 0.0551.

### Same root cause, and what I did about it

Both bugs were a scope rule applied in one branch of the pipeline and not its siblings.
The definition now lives in one module, `scripts/production_universe.py`, imported by
both generators and matched to the dbt mart.

Then four plausibility tests, because nothing structural could have caught either bug.
The tables were valid, the keys were there, referential integrity was intact:

| Test | What it checks |
|---|---|
| `assert_univers_partages` | costs, emissions and production cover the same (well, month) set |
| `assert_facteur_conversion_boe` | 6.290 boe/m³ for liquids, 5.885 boe/10³m³ for gas |
| `assert_opex_par_boe_plausible` | OPEX/boe stays within 8 to 30, per region |
| `assert_intensite_carbone_plausible` | intensity stays within 0.050 to 0.060, per region |

The per-region part of the last two is the whole point. While the bug was live, the
global OPEX/boe was $9.21, comfortably inside the band. A test on the total would have
passed and told me nothing. Only the regional split showed the problem.

I checked the tests actually work by pointing them at a copy of the database from before
the fix. They return 3 regions out of band on OPEX, 1 on intensity, and 413,760 orphaned
(well, month) pairs. That build would have failed.

---

## The report

Five pages sharing one region slicer, with row-level security on three roles.

### Production & Wells

![Production and wells](docs/screenshots/p2_production.png)

Map of geolocated wells with coordinates rebuilt from the DLS, counters for producing,
active and abandoned wells, monthly production against a 3-month moving average, and
per-UWI detail underneath.

Two caveats on this capture: it's filtered to 2025, so the totals cover the year rather
than the full 24 months, and the ArcGIS basemap didn't load when I exported it.

### Costs & Profitability

![Costs and profitability](docs/screenshots/p3_costs.png)

Revenue, OPEX in total and per barrel, operating margin, and an OPEX waterfall by
region. The flat $17.5 across all five regions is the check I now look at first, since
that's exactly where the unit bug showed up.

### ESG Performance

![ESG performance](docs/screenshots/p4_esg.png)

Scope 1 CO₂ and CO₂e using CH₄ × 28 (GWP100, AR6), carbon intensity, and a gauge
against Alberta's 2030 target of 0.040 tCO₂/boe, which the current figure misses by
37.5%. The conversion is deliberately checkable by hand: 194.6 + 2.21 × 28 = 256.5 Mt.

### Forecast & Trends

![Forecast and trends](docs/screenshots/p5_forecast.png)

Power BI's built-in forecast, six months out at 95% confidence, with year-over-year
trend at +3.4% and a coefficient of variation of 5.4%. Nothing clever here, but the
input series is clean enough that the native forecast is defensible.

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
 │  Python (scripts 01 to 05) → Parquet in data/processed/       │
 │  pandas · numpy · requests · pyarrow                          │
 └───────────────────────────┬──────────────────────────────────┘
                             ▼
 ┌──────────────────────────────────────────────────────────────┐
 │  dbt Core + DuckDB   (staging → marts, tests, lineage)        │
 │  data/energy.duckdb                                           │
 └───────────────────────────┬──────────────────────────────────┘
                             ▼
 ┌──────────────────────────────────────────────────────────────┐
 │  Power BI Desktop, PBIP  (star, 27 DAX measures, RLS)         │
 └──────────────────────────────────────────────────────────────┘
```

### Sources

| Source | Content | Format |
|---|---|---|
| Petrinex Conventional Volumetrics | Monthly AB production, 24 months | ZIP→CSV |
| AER ST37 List of Wells | Well register: DLS, status, licence | ZIP→TXT |
| Petrinex Business Associate / Field Codes | Operator and field reference data | CSV |
| Yahoo Finance WTI (CL=F) | Monthly WTI price, basis for WCS | JSON |
| Bank of Canada FXUSDCAD | Monthly USD/CAD rate | JSON |

Full URLs are in [`docs/DOCUMENTATION.md`](docs/DOCUMENTATION.md).

### Python pipeline

| Script | Output | What it does |
|---|---|---|
| `01_ingest_petrinex.py` | `petrinex24.parquet` | Parallel download, nested unzip, cleaning, BOE conversion |
| `02_ingest_aer_wells.py` | `dim_puits.parquet` | ST37 parsing, UWI reconstruction, DLS to lat/lon, reference joins |
| `03_ingest_prices.py` | `dim_prix.parquet` | WTI plus USD/CAD into a monthly WCS in CAD |
| `04_generate_costs.py` | `fact_couts.parquet` | Simulated OPEX and CAPEX, winter seasonality, incidents |
| `05_generate_emissions.py` | `fact_emissions.parquet` | Scope 1 CO₂, CH₄ and CO₂e using NIR 2024 factors |

`production_universe.py` holds the scope shared by scripts 04 and 05: the gas unit
correction and the commercialised-production filter, matched to the dbt mart. That
module exists because of the first bug above.

ST37 to Petrinex UWI coverage comes out at 99.0%, with 1,426 producing wells falling
outside the register.

---

## Data model

![Star schema](docs/diagramme_bdd.png)

The diagram is two changes behind: `dim_region` isn't on it, and
`fact_production_enriched` now also carries `opex_cad` and `co2_tonnes`. Grains, keys
and cardinalities are still right.

Staging views: `stg_petrinex_production`, `stg_aer_wells`, `stg_eia_prices`,
`stg_costs`, `stg_emissions`. Marts: `dim_date`, `dim_puits`, `dim_region`,
`fact_production_enriched`, `fact_kpis_mensuels`, `fact_emissions_scope`.

`dim_region` is conformed, and it has to be. `dim_puits` and `fact_kpis_mensuels` aren't
related to each other, so a slicer sitting on one fact's own region column filters that
fact and nothing else. The pages filter `dim_region[region]`, which reaches both sides.

`fact_production_enriched` is 4,342,506 rows at well by month by product, and carries
volume, revenue, OPEX and CO₂. The last two are allocated pro rata by volume from the
(well, month) simulation. The allocation is exact rather than approximate, since the
scripts compute `opex = rate × volume` with the rate held constant over a pair. Keeping
that grain is what lets OPEX and intensity respond to an operator or product filter,
which they didn't before I moved them.

`dbt build` gives 42 pass, 1 warn, 0 error across 43 nodes. The warning is a
relationship test returning 24 rows: one producing UWI that disappears from `dim_puits`
after case-insensitive deduplication. Power BI matches keys the same way, so it doesn't
surface. Lineage is at [`docs/dbt/index.html`](docs/dbt/index.html).

---

## DAX measures

```dax
OPEX par boe =                          -- the metric people actually ask about
DIVIDE ( [OPEX Total CAD], [Production BOE] )

OPEX Total CAD =                        -- grain: well × month × product
SUM ( fact_production_enriched[opex_cad] )

Intensité carbone =                     -- tCO₂ per boe
DIVIDE ( [CO2 Scope 1 (t)], [Production BOE] )

Marge Opérationnelle % =                -- opex only, not a net margin
DIVIDE ( [Revenu Estimé CAD] - [OPEX Total CAD], [Revenu Estimé CAD] )

Tendance YoY % =                        -- last 12 months against the 12 before
DIVIDE ( [Production 12 derniers mois] - [Production 12 mois précédents],
         [Production 12 mois précédents] )
```

27 measures across five display folders, and RLS on three roles (Nord, Sud, Admin)
applied to `dim_puits`, `fact_kpis_mensuels`, `fact_emissions_scope` and `dim_region`.

Every ratio takes its numerator and denominator from the same fact. A ratio whose two
terms sit at different grains will freeze silently the moment someone applies a slicer
only one side can see, and it won't look broken. That's the trap in this model and it's
the reason the OPEX and CO₂ columns moved down to well grain.

---

## Running it

```powershell
# 1. Environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Manual raw files in data/raw/ :
#    ST37.zip, ba_codes.csv, field_codes.csv

# 3. Python pipeline, in this order
python scripts\01_ingest_petrinex.py
python scripts\02_ingest_aer_wells.py
python scripts\03_ingest_prices.py
python scripts\04_generate_costs.py
python scripts\05_generate_emissions.py

# 4. dbt
cd dbt_project\energy_analytics
dbt build --profiles-dir .
dbt docs generate --profiles-dir .

# 5. Open the reporting\ folder in Power BI Desktop, then Refresh
```

`profiles.yml` isn't versioned because it holds a machine path. Create one in
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

Two things will bite you on a fresh clone. The staging views read the Parquet files by
relative path, so dbt has to run from `dbt_project/energy_analytics`. And the database
path is hard-coded in the semantic model's M partitions, so you'll need to edit it.

---

## What I had to assume

This is a basin view, not an operator view. The data covers all 3,015 operators in the
province, which is closer to what a regulator or a market analyst looks at than to a
single company's control room. Worth being clear about, since the two get read very
differently.

Gas isn't monetised. WCS is a heavy oil benchmark and I had no AECO price, so gas counts
toward volumes and emissions but contributes nothing to revenue. Pricing it as oil would
have overstated it by four or five times. Margin therefore sits on liquids-only revenue,
which makes it conservative rather than optimistic, and I'd rather err that way.

Only commercialised production is in scope: `PROD`, excluding `WATER`. Fuel gas, vented
and flared volumes, and shut-in wells are all out. Costs, emissions and production share
that definition, which as the bug section explains is not a detail.

1,426 producing wells sit outside the AER register, roughly 1% of production. They're in
Petrinex but not in the ST37 extract. I put them in a labelled bucket instead of
dropping them, so the totals stay right and the gap stays visible.

ST37 arrives as tab-delimited text with no coordinates and no names, so coordinates come
from a DLS conversion and names from the Petrinex reference files. EIA and Alpha Vantage
both want API keys, so prices come from Yahoo Finance and the Bank of Canada instead,
with WCS set at WTI minus $17.50.

CAPEX is illustrative. It's simulated log-normally to give the cost structure a shape,
and it is not calibrated against real Alberta drilling costs. Don't quote it.

---

## Still open

CAPEX needs recalibrating. It currently lands around $33k per well against a real 2 to 8
million, and it isn't surfaced on the Costs page, which shows OPEX only.

The data stops at April 2026 and refresh isn't automated. `airflow_dags/` is a folder I
reserved, not a DAG.

The inactive well inventory is the piece I most want to build next. 449,057 wells with
no production, 66,984 of them abandoned, which is 75% of the register. Reclamation
liability is a live political and financial issue in Alberta and the data is already
sitting in the model, so it's the one genuinely non-simulated finding here that I
haven't used yet.

Two pages still expose UWI slicers with around 598k values, which is unusable and needs
a search control instead. And the report isn't published to the web yet, so the
screenshots above are the only way to see it.

---

Data Analyst portfolio project, Calgary 2026.
