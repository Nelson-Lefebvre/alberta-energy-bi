# Architecture and implementation

Technical detail behind [the project README](../README.md).

## Pipeline

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

## Sources

| Source | Content | Format |
|---|---|---|
| Petrinex Conventional Volumetrics | Monthly AB production, 24 months | ZIP→CSV |
| AER ST37 List of Wells | Well register: DLS location, status, licence | ZIP→TXT |
| Petrinex Business Associate / Field Codes | Operator and field reference data | CSV |
| Yahoo Finance WTI (CL=F) | Monthly WTI price, basis for WCS | JSON |
| Bank of Canada FXUSDCAD | Monthly USD/CAD rate | JSON |

Full URLs, ingestion constants, simulation parameters and a glossary are in
[`DOCUMENTATION.md`](DOCUMENTATION.md).

## Python pipeline

| Script | Output | What it does |
|---|---|---|
| `01_ingest_petrinex.py` | `petrinex24.parquet` | Parallel download, nested unzip, cleaning, BOE conversion |
| `02_ingest_aer_wells.py` | `dim_puits.parquet` | ST37 parsing, UWI reconstruction, DLS to lat/lon, reference joins |
| `03_ingest_prices.py` | `dim_prix.parquet` | WTI plus USD/CAD into a monthly WCS in CAD |
| `04_generate_costs.py` | `fact_couts.parquet` | Simulated OPEX and CAPEX, winter seasonality, incidents |
| `05_generate_emissions.py` | `fact_emissions.parquet` | Scope 1 CO₂, CH₄ and CO₂e using NIR 2024 factors |

`production_universe.py` holds the scope shared by scripts 04 and 05: the gas unit
correction and the commercialised-production filter, matched to the dbt mart.

ST37 to Petrinex UWI coverage is **99.0%**, with 1,426 producing wells falling outside
the register.

## Data model

The star schema is rendered from source in [the README](../README.md#how-its-built) so
it cannot drift out of date the way an exported image does. Column list per table:

| Table | Grain | Columns |
|---|---|---|
| `dim_date` | month | `date_key` PK, `date`, `annee`, `trimestre`, `mois`, `mois_nom`, `is_hiver` |
| `dim_region` | region | `region` PK |
| `dim_puits` | well | `uwi` PK, `region` FK, `operator_name`, `area`, `field`, `well_type`, `status`, `spud_date`, `latitude`, `longitude` |
| `fact_production_enriched` | well × month × product | `date_key` FK, `uwi` FK, `product_type`, `activity_type`, `volume_boe`, `volume_brut`, `wcs_cad`, `revenu_estime_cad`, `opex_cad`, `co2_tonnes`, `production_cumulative_boe` |
| `fact_kpis_mensuels` | month × region | `date_key` FK, `region` FK, `production_boe`, `revenu_estime_cad`, `opex_total_cad`, `capex_total_cad`, `co2_tonnes`, `opex_par_boe`, `intensite_carbone` |
| `fact_emissions_scope` | month × region × scope | `date_key` FK, `region` FK, `scope`, `co2_tonnes`, `ch4_tonnes`, `co2eq_total` |

Staging views: `stg_petrinex_production`, `stg_aer_wells`, `stg_eia_prices`,
`stg_costs`, `stg_emissions`.

There is no `dim_prix` mart. Price is a monthly scalar with no attributes worth a
dimension, so `stg_eia_prices` is joined during the build and `wcs_cad` lands
denormalised on `fact_production_enriched`.

**`dim_region` is conformed, and it has to be.** `dim_puits` and `fact_kpis_mensuels`
are not related to each other, so a slicer sitting on one fact's own region column
filters that fact and nothing else. Report pages filter `dim_region[region]`, which
reaches both branches.

**`fact_production_enriched`** is 4,342,506 rows at well × month × product, carrying
volume, revenue, OPEX and CO₂. The last two are allocated pro rata by volume from the
(well, month) simulation. The allocation is exact rather than approximate: the scripts
compute `opex = rate × volume` with the rate held constant over a pair, so redistributing
by volume reproduces the per-product value. Keeping that grain is what lets OPEX and
carbon intensity respond to an operator, status or product filter.

## Tests

`dbt build` returns **42 pass, 1 warn, 0 error** across 43 nodes.

Beyond the structural tests (`not_null`, `unique`, `accepted_values`, `relationships`),
four singular tests check whether the numbers can be true:

| Test | What it checks |
|---|---|
| `assert_univers_partages` | costs, emissions and production cover the same (well, month) set |
| `assert_facteur_conversion_boe` | 6.290 boe/m³ for liquids, 5.885 boe/10³m³ for gas |
| `assert_opex_par_boe_plausible` | OPEX/boe within 8 to 30, per region |
| `assert_intensite_carbone_plausible` | carbon intensity within 0.050 to 0.060, per region |

Replayed against a copy of the database from before the fixes, they return 3 regions out
of band on OPEX, 1 on intensity, and 413,760 orphaned (well, month) pairs.

The remaining warning is a relationship test returning 24 rows: one producing UWI that
disappears from `dim_puits` after case-insensitive deduplication. Power BI matches keys
the same way, so it does not surface in the report.

Lineage: [`dbt/index.html`](dbt/index.html).

## DAX

```dax
OPEX par boe =
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

27 measures across five display folders, with RLS on three roles (Nord, Sud, Admin)
applied to `dim_puits`, `fact_kpis_mensuels`, `fact_emissions_scope` and `dim_region`.

Every ratio takes numerator and denominator from the same fact. A ratio whose two terms
sit at different grains freezes silently the moment someone applies a slicer only one
side can see, and it does not look broken while it happens.

## Running it

```powershell
# 1. Environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Raw files script 02 reads. Scripts 01 and 03 fetch their own.
mkdir data\raw
curl -o data\raw\ST37.zip        https://static.aer.ca/prd/documents/sts/st37/ST37.zip
curl -o data\raw\ba_codes.csv    https://www.petrinex.gov.ab.ca/bbreports/PRABAIdentifiers.csv
curl -o data\raw\field_codes.csv https://www.petrinex.gov.ab.ca/bbreports/PRAFieldCodes.csv

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

# 5. Open the reporting\ folder in Power BI Desktop,
#    set the DuckDBPath parameter to your own clone, then Refresh
```

`profiles.yml` is not versioned because it holds a machine path. Create one in
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

Two things bite on a fresh clone. Staging views read the Parquet files by relative path,
so dbt has to run from `dbt_project/energy_analytics`. And the semantic model needs to be
told where the database is: the six M partitions all read one shared parameter,
`DuckDBPath`, declared in `SemanticModel/definition/expressions.tmdl`. Set it once under
**Home > Transform data > Manage parameters**, or edit that one line before opening the
project.

Its default is `C:\alberta-energy-bi\data\energy.duckdb` rather than a path under a home
directory, because Power BI Desktop writes the parameter value back into
`expressions.tmdl` on save. A machine-specific default would land in every commit. On
Windows the cheapest way to make that default true is a directory junction, which needs
no elevation:

```powershell
New-Item -ItemType Junction -Path "C:\alberta-energy-bi" -Target "<your clone>"
```

## Simulated figures

Production volumes, prices and well locations come from Petrinex and the AER register.
Costs, revenue and emissions do not exist in any public filing at well grain, so scripts
04 and 05 generate them from those volumes using AER and NIR 2024 factors. The report
carries that caveat on every page that shows a modelled number, because operators are
named on those pages and the figures are not theirs. Parameters are listed in
[`DOCUMENTATION.md`](DOCUMENTATION.md).

## Assumed trade-offs

**Basin view, not operator view.** The data covers all 3,015 operators in the province,
which is closer to what a regulator or a market analyst looks at than to a single
company's control room.

**Gas is not monetised.** WCS is a heavy oil benchmark and no AECO price was available,
so gas counts toward volumes and emissions but contributes nothing to revenue. Pricing
it as oil would have overstated it four to five times. Margin therefore sits on
liquids-only revenue, which makes it conservative rather than optimistic.

**Only commercialised production is in scope**: `PROD`, excluding `WATER`. Fuel gas,
vented and flared volumes, and shut-in wells are out. Costs, emissions and production
share that definition.

**1,426 producing wells sit outside the AER register**, roughly 1% of production. They
are in Petrinex but not in the ST37 extract, and go into a labelled bucket rather than
being dropped, so totals stay right and the gap stays visible.

**Source substitutions.** ST37 arrives as tab-delimited text with no coordinates and no
names, so coordinates come from a DLS conversion and names from the Petrinex reference
files. EIA and Alpha Vantage both require API keys, so prices come from Yahoo Finance
and the Bank of Canada instead, with WCS set at WTI minus $17.50.

**CAPEX is illustrative.** It is simulated log-normally to give the cost structure a
shape and is not calibrated against real Alberta drilling costs.
