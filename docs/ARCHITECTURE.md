# Architecture and implementation

Technical detail behind [the project README](../README.md).

## Pipeline

```
                 Public sources
  ┌────────────┬──────────────┬─────────────────┬───────────────┐
  │ Petrinex   │  AER ST37    │ Petrinex ref.   │ Alberta Gov.  │
  │ Volumetric │  Well List   │ (BA / Field)    │ + Bank of Can.│
  └─────┬──────┴──────┬───────┴────────┬────────┴──────┬────────┘
        │             │                │               │
        ▼             ▼                ▼               ▼
 ┌──────────────────────────────────────────────────────────────┐
 │  Python (scripts 00 to 05), serverless job tasks              │
 │  → Unity Catalog volume  /Volumes/workspace/alberta_bronze/   │
 │    landing/{raw,processed}                                    │
 └───────────────────────────┬──────────────────────────────────┘
                             ▼  read_files(), SQL task
 ┌──────────────────────────────────────────────────────────────┐
 │  Bronze: 5 Delta tables, workspace.alberta_bronze             │
 └───────────────────────────┬──────────────────────────────────┘
                             ▼  dbt build, SQL warehouse
 ┌──────────────────────────────────────────────────────────────┐
 │  dbt Core + dbt-databricks   (staging → marts, tests)         │
 │  Silver: views, workspace.alberta_silver                      │
 │  Gold:   tables, workspace.alberta_gold                       │
 └───────────────────────────┬──────────────────────────────────┘
                             ▼  Databricks connector, PAT
 ┌──────────────────────────────────────────────────────────────┐
 │  Power BI, PBIP  (star, 27 DAX measures, RLS)                 │
 └──────────────────────────────────────────────────────────────┘
```

Everything inside the volume and the three schemas runs on Databricks Free Edition, as a
single job: `alberta_energy_refresh`, on the 15th of each month at 6 a.m., Edmonton time.
The first version of the project ran the same chain on a laptop with DuckDB; the
[Databricks section](#databricks) below covers what changed and what deliberately did
not.

## Sources

| Source | Content | Format |
|---|---|---|
| Petrinex Conventional Volumetrics | Monthly AB production, 24 months | ZIP→CSV |
| AER ST37 List of Wells | Well register: DLS location, status, licence | ZIP→TXT |
| Petrinex Business Associate / Field Codes | Operator and field reference data | CSV |
| Government of Alberta `OilPrices` | Monthly WTI **and WCS**, USD/bbl, since 2005 | JSON |
| Bank of Canada FXUSDCAD | Monthly USD/CAD rate | JSON |

Full URLs, ingestion constants, simulation parameters and a glossary are in
[`DOCUMENTATION.md`](DOCUMENTATION.md).

### Terms

No source data is redistributed here. Every raw and derived file is gitignored and the
pipeline fetches its own inputs, so cloning this repository gives you the code and the
report definition, never the datasets.

Rights in the underlying data stay with their publishers: Petrinex and the Government of
Alberta for volumetrics, reference codes and oil prices, the Alberta Energy Regulator for
the ST37 register, and the Bank of Canada for the exchange rate. Check each publisher's
own terms before reusing their data, particularly for anything commercial.

Every source is now a government or regulator publication. The pipeline previously pulled
WTI from Yahoo Finance, whose terms were the most restrictive of the set; moving prices to
the province's own `OilPrices` table removed that dependency.

The MIT licence on this repository covers the code, the dbt models and the report
definition. It does not grant any right over the source data.

## Python pipeline

| Script | Output | What it does |
|---|---|---|
| `00_download_raw.py` | `raw/` files | ST37 register and the two Petrinex reference files |
| `01_ingest_petrinex.py` | `petrinex24.parquet` | Parallel download, nested unzip, cleaning, BOE conversion |
| `02_ingest_aer_wells.py` | `dim_puits.parquet` | ST37 parsing, UWI reconstruction, DLS to lat/lon, reference joins |
| `03_ingest_prices.py` | `dim_prix.parquet` | WTI plus USD/CAD into a monthly WCS in CAD |
| `04_generate_costs.py` | `fact_couts.parquet` | Simulated OPEX and CAPEX, winter seasonality, incidents |
| `05_generate_emissions.py` | `fact_emissions.parquet` | Scope 1 CO₂, CH₄ and CO₂e using NIR 2024 factors |

`production_universe.py` holds the scope shared by scripts 04 and 05: the gas unit
correction and the commercialised-production filter, matched to the dbt mart.

`_paths.py` resolves the data root for every script. By default it is `data/` in the
repository; `--data-dir` points it elsewhere, which is how the job sends the same files
to the Unity Catalog volume. `--no-csv` skips the CSV copies, which nothing reads on
Databricks.

ST37 to Petrinex UWI coverage is **99.0%**, with 1,443 producing wells falling outside
the register.

## Data model

The star schema is rendered from source in [the README](../README.md#how-its-built) so
it cannot drift out of date the way an exported image does. Column list per table:

| Table | Grain | Columns |
|---|---|---|
| `dim_date` | month | `date_key` PK, `date`, `annee`, `trimestre`, `mois`, `mois_nom`, `is_hiver` |
| `dim_region` | region | `region` PK |
| `dim_puits` | well | `uwi` PK, `region` FK, `operator_name`, `area`, `field`, `well_type`, `status`, `spud_date`, `latitude`, `longitude` |
| `fact_production_enriched` | well × month × product | `date_key` FK, `uwi` FK, `product_type`, `activity_type`, `volume_boe`, `volume_brut`, `wcs_cad`, `gaz_cad_gj`, `revenu_estime_cad`, `opex_cad`, `co2_tonnes`, `co2eq_tonnes`, `production_cumulative_boe` |
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

**`fact_production_enriched`** is 4,338,069 rows at well × month × product, carrying
volume, revenue, OPEX and CO₂. The last two are allocated pro rata by volume from the
(well, month) simulation. The allocation is exact rather than approximate: the scripts
compute `opex = rate × volume` with the rate held constant over a pair, so redistributing
by volume reproduces the per-product value. Keeping that grain is what lets OPEX and
carbon intensity respond to an operator, status or product filter.

## Tests

`dbt build` returns **46 pass, 1 warn, 0 error** across 47 nodes — 11 models and 36 tests.
`dbt test` alone returns 35 pass, 1 warn, 0 error. The result is the same on Databricks SQL
as it was on DuckDB, warning included.

Beyond the 28 structural tests (`not_null`, `unique`, `accepted_values`, `relationships`),
eight singular tests check whether the numbers can be true:

| Test | What it checks |
|---|---|
| `assert_univers_partages` | costs, emissions and production cover the same (well, month) set |
| `assert_facteur_conversion_boe` | 6.290 boe/m³ for liquids, 5.885 boe/10³m³ for gas |
| `assert_opex_par_boe_plausible` | OPEX/boe within 15–30 for liquids, 4–10 for gas, **per product** |
| `assert_intensite_carbone_plausible` | carbon intensity within 0.005 to 0.080, per region |
| `assert_emissions_perimetre` | emissions and production share one scope rule |
| `assert_revenu_couvre_le_volume` | every product carrying volume also carries revenue |
| `assert_prix_gaz_exploitable` | gas price present, within 0–25 CAD/GJ, at most 3 carried-forward months |
| `assert_co2eq_coherent` | CO₂e / CO₂ ratio between 1.0 and 1.5 on the allocated fact |

Replayed against a copy of the database from before the fixes, they return 3 regions out
of band on OPEX, 1 on intensity, and 413,760 orphaned (well, month) pairs.

`assert_opex_par_boe_plausible` moved from region to product when operating rates were
split by product. Regional OPEX/boe now varies legitimately with gas share — $10.05 in
Central at 76.9 % gas against $19.22 in Nord at 17.1 % — so a tight regional band would
reject a correct result. The band belongs at the grain where the rate is defined.

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

## Databricks

The project runs on Databricks Free Edition, which shapes several choices: serverless
compute only, a single 2X-Small SQL warehouse, a daily usage quota, and outbound internet
limited to a list of trusted domains that Databricks does not publish.

| Layer | Unity Catalog object | Written by |
|---|---|---|
| Files | volume `workspace.alberta_bronze.landing` (`raw/`, `processed/`) | scripts 00 to 05 |
| Bronze | 5 Delta tables in `workspace.alberta_bronze` | `sql/load_bronze.sql` (`read_files`) |
| Silver | 5 `stg_*` views in `workspace.alberta_silver` | dbt staging |
| Gold | 6 Delta tables in `workspace.alberta_gold` | dbt marts |

**The job.** `resources/alberta_energy.job.yml` declares eight tasks with the dependencies
the scripts already had: `download_raw` and `ingest_petrinex` first, then the wells, prices
and emissions, then costs, then `load_bronze` and `dbt_build`. Only the three tasks that
download are retried, twice, five minutes apart: a network error clears on retry, a data
error or a failing test does not. `max_concurrent_runs: 1` stops two runs writing to the
same volume. A failure sends an email; the address lives in a gitignored
`.databricks/bundle/<target>/variable-overrides.json`, not in the repository.

**Pinned environments.** Serverless environment 5 ships pandas 2.2.3. The job pins pandas
3.0.3, numpy 2.4.6 and pyarrow 24.0.0, the versions that produced the published figures,
and pins `dbt-core` 1.11.11 next to `dbt-databricks` 1.12.5. Without the `dbt-core` pin,
pip resolves 1.12 in the job while the local build runs 1.11.

**Failure semantics.** Every bronze table and every mart is written with
`CREATE OR REPLACE`, which Delta commits atomically. A run that fails part-way leaves the
previous version of each table readable, so Power BI never sees a half-built month. Older
versions stay queryable with `DESCRIBE HISTORY` and `VERSION AS OF`.

**What the dialect cost.** Four changes, all in the marts: `sequence`/`explode` in
place of `generate_series`/`unnest` in `dim_date`, `date_format(date, 'MMMM')` in place of
`monthname`, `string` in place of `varchar` in `dim_puits`, and explicit aliases on two
subqueries. `macros/generate_schema_name.sql` keeps the `+schema` names as declared,
instead of dbt's default `alberta_gold_alberta_silver`. The SQL warehouse runs in ANSI
mode, where a division by zero raises an error; every ratio was already guarded with
`nullif` or a `case`.

**Proof of equivalence.** The first bronze load used the Parquet files that had fed DuckDB,
not a fresh download. A fingerprint query, with row counts and control totals for the six
marts, then returned identical figures on both engines.

## Running it

Prerequisites: a Databricks workspace (Free Edition is enough), the Databricks CLI
(`winget install Databricks.DatabricksCLI`), a personal access token, and Python 3.11
with `requirements.txt` for local runs.

The CLI and dbt read the same three environment variables. Set them in each session; the
token comes from the clipboard, so it never appears on screen or in a file:

```powershell
$env:DATABRICKS_HOST      = "https://<workspace>.cloud.databricks.com"
$env:DATABRICKS_HTTP_PATH = "/sql/1.0/warehouses/<warehouse-id>"
$env:DATABRICKS_TOKEN     = (Get-Clipboard -Raw).Trim()   # token copied beforehand
databricks current-user me
```

```powershell
# 1. Unity Catalog, once: run sql/setup_unity_catalog.sql in the SQL editor

# 2. Deploy the job, then run it (the schedule takes over afterwards)
databricks bundle validate -t prod
databricks bundle deploy -t prod
databricks bundle run -t prod alberta_energy_refresh

# 3. Power BI: open reporting\ in Power BI Desktop, set the DatabricksHost and
#    DatabricksHttpPath parameters, sign in with "Personal access token", Refresh
```

`databricks.yml` holds the workspace host and finds the warehouse by its name, `Serverless
Starter Warehouse`, so no warehouse ID is hard-coded in the bundle.

For local work, the scripts still run on a laptop and write to `data/`. dbt runs against
the SQL warehouse with a profile that is not versioned. Create it in
`dbt_project/energy_analytics/`:

```yaml
energy_analytics:
  target: databricks
  outputs:
    databricks:
      type: databricks
      catalog: workspace
      schema: alberta_gold
      host: "{{ env_var('DATABRICKS_HOST') | replace('https://', '') }}"
      http_path: "{{ env_var('DATABRICKS_HTTP_PATH') }}"
      token: "{{ env_var('DATABRICKS_TOKEN') }}"
      threads: 4
```

```powershell
cd dbt_project\energy_analytics
dbt build --profiles-dir .
```

The project started on DuckDB, and `dbt-duckdb` stays in `requirements.txt` for that
reason: a second `dev` output with `type: duckdb` and `path: ../../data/energy.duckdb`
builds the same models offline, without spending the Free Edition quota. It is a local
test bench only; the published figures come from Databricks.

Two things bite on a fresh workspace. The catalog has to be `workspace`, the one Free
Edition creates; any other name has to change in `sources.yml`, `sql/` and the job. And if
the job's download tasks cannot reach a source, which is how the trusted-domain list shows
up, run scripts 00 to 05 locally with `--no-csv`, upload `data/processed/*.parquet` to the
volume with `databricks fs cp`, then run `sql/load_bronze.sql` and `dbt build`.

Power BI Desktop writes parameter values back into `expressions.tmdl` on save, so the
workspace host and HTTP path are committed. Neither is a secret: without a token they give
access to nothing.

## Simulated figures

Production volumes, prices and well locations come from Petrinex and the AER register.

**Emissions no longer belong here.** Script 05 derives them from the FUEL, VENT and FLARE
gas volumes operators declare to Petrinex, converted with NIR and AER Directive 060
factors. Those are declared figures rather than total ones — fugitives and undeclared
methane are outside Petrinex — but they are measured activity, not a draw, and carbon
intensity now varies about eighteen-fold between operators where the simulated version
had them all within 1% of each other.

**Costs remain simulated.** OPEX and CAPEX exist in no public filing at well grain, so
script 04 generates them from real volumes. The consequence is worth stating plainly:
because the OPEX rate is drawn independently of the well, OPEX per boe is statistically
identical across operators, and any ranking built on it sorts noise. The report carries a
caveat on every page showing a modelled number, because operators are named there and the
figures are not theirs.

Parameters for both are listed in [`DOCUMENTATION.md`](DOCUMENTATION.md).

## Assumed trade-offs

**Basin view, not operator view.** The data covers all 3,016 operators in the province,
which is closer to what a regulator or a market analyst looks at than to a single
company's control room.

**Gas is not monetised.** WCS is a heavy oil benchmark and no AECO price was available,
so gas counts toward volumes and emissions but contributes nothing to revenue. Pricing
it as oil would have overstated it four to five times. Margin therefore sits on
liquids-only revenue, which makes it conservative rather than optimistic.

**Only commercialised production is in scope**: `PROD`, excluding `WATER`. Fuel gas,
vented and flared volumes, and shut-in wells are out. Costs, emissions and production
share that definition.

**1,443 producing wells sit outside the AER register**, 1.5% of production. They
are in Petrinex but not in the ST37 extract, and go into a labelled bucket rather than
being dropped, so totals stay right and the gap stays visible.

**Source substitutions.** ST37 arrives as tab-delimited text with no coordinates and no
names, so coordinates come from a DLS conversion and names from the Petrinex reference
files. EIA and Alpha Vantage both require API keys, so prices come from the Government
of Alberta's `OilPrices` table and the Bank of Canada instead.

WCS used to be derived as WTI minus a fixed $17.50. Checked against the published
Alberta series it does not hold: the real differential averages $13.30 and swings
between $9.95 and $18.99 over the window, so the fixed figure was too wide in 22 months
out of 24 and understated basin revenue by 10.4%, or $14.3B. Both series now come
measured from the same provincial source, which also removed the Yahoo Finance
dependency.

**CAPEX is illustrative.** It is simulated log-normally to give the cost structure a
shape and is not calibrated against real Alberta drilling costs.
