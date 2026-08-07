# Reference — Alberta Energy Operations Intelligence

Constants, factors, sources and vocabulary behind the pipeline.

Pipeline shape, data model, tests, DAX and run instructions live in
[`ARCHITECTURE.md`](ARCHITECTURE.md); the findings live in [the README](../README.md).
This file holds only what neither of those repeats: the numbers baked into the code and
where the data comes from.

**English first, French below.** → [Version française](#référence--alberta-energy-operations-intelligence)

---

## 1. Sources and raw files

Dropped into `data/raw/`, gitignored, all public.

| File | Source | Used by |
|---|---|---|
| `Vol_YYYY-MM-AB.*` | `petrinex.gov.ab.ca/publicdata/API/Files/AB/Vol/{YYYY-MM}/CSV` | script 01 |
| `ST37.zip` (`WellList.txt`) | `static.aer.ca/.../st37/ST37.zip` | script 02 |
| `St37-layout.pdf` | AER | TXT format spec (field positions, codes) |
| `ba_codes.csv` | `petrinex.gov.ab.ca/bbreports/PRABAIdentifiers.csv` | BA code → operator name |
| `field_codes.csv` | `petrinex.gov.ab.ca/bbreports/PRAFieldCodes.csv` | field code → name |

Prices need no manual file: WTI from Yahoo Finance (`CL=F`, `/v8/finance/chart/CL=F`),
USD/CAD from the Bank of Canada Valet API (series `FXUSDCAD`).

**ST37 TXT layout.** 24 tab-delimited columns, including `UWI-DISPLAY-FORMAT`, DLS
location (Township / Meridian / Range / Section / LSD), `WELL-NAME`, `FIELD-CODE`,
`LICENSEE-CODE`, `OPERATOR-CODE`, `FIN-DRL-DATE`, `MODE_SHORT_DESCRIPTION` (status),
`TYPE_SHORT_DESCRIPTION` (use). No latitude or longitude, which is why script 02 converts
from DLS.

## 2. Ingestion constants

| Constant | Value | Meaning | Script |
|---|---|---|---|
| `MONTHS_BACK` | 24 | rolling window length | 01 |
| `PUBLISH_LAG` | 2 | Petrinex publishes ~2 months behind | 01 |
| `MAX_WORKERS` | 6 | concurrent downloads | 01 |
| `BOE_LIQUID` | 6.29 | 1 m³ liquid = 6.29 boe | 01 |
| `BOE_GAS` | 35.31 / 6000 | ≈ 0.005885 boe/m³, so 5.885 boe per 10³m³ | 01 |
| `WCS_DISCOUNT_USD` | 17.5 | mean historical WCS discount to WTI, USD/bbl | 03 |

Kept products: `OIL`, `GAS`, `WATER`, `COND`. Kept activities: `PROD`, `SHUTIN`, `FUEL`,
`VENT`. The marts narrow this further to `PROD` excluding `WATER` — see
[ARCHITECTURE, assumed trade-offs](ARCHITECTURE.md#assumed-trade-offs).

The gas factor is the one that bit. Petrinex reports gas in 10³m³, not m³, and the two
figures above differ by exactly that factor of 1000.

## 3. Simulation parameters

> Costs and emissions are **simulated** from real BOE volumes. Ranges are anchored on the
> *AER Annual Report 2023* and Canada's *National Inventory Report 2024*. They are not
> measured data.

### 3.1 Costs — script 04

| Constant | Value | Effect |
|---|---|---|
| `RNG_SEED` | 42 | reproducible numpy generator |
| `OPEX_FORAGE_MU / SIGMA` | 12 / 2 | drilling rate $/boe, Normal |
| `OPEX_MAINT_MU / SIGMA` | 4 / 1.5 | maintenance rate $/boe, Normal |
| `CAPEX_LOGNORM_MEAN / SIGMA` | 11.5 / 0.6 | CAPEX, log-normal, CAD |
| `CAPEX_RECENT_MULT` | 2.5 | uplift for wells under 3 years old |
| `WINTER_MULT` | 1.15 | OPEX × 1.15 in Jan/Feb/Mar |
| `INCIDENT_RATE / MULT` | 0.05 / 2.0 | 5 % of (well, month) pairs → OPEX × 2 |

Rates are drawn per (well, month) and truncated at zero, then multiplied by real volume,
so `opex = rate × volume`. Holding the rate constant over a pair is what makes the pro
rata reallocation onto well × month × product exact rather than approximate.

Resulting OPEX/boe: p05 12.2, median 16.7, p95 24.9.

**CAPEX is illustrative and not calibrated.** It lands near $33k per well against a real
$2 to 8 million. It is not surfaced in the report.

### 3.2 Emissions — script 05

| Constant | Value | Meaning |
|---|---|---|
| `FACTEUR_CO2_BOE` | 0.055 | t CO₂ / boe, Alberta upstream O&G |
| `FACTEUR_CH4_BOE` | 0.000625 | t CH₄ / boe, calibrated |
| `CO2EQ_CH4` | 28 | CH₄ GWP100, IPCC AR6 (≈ AR5) |
| `VARIANCE_PUITS` | 0.10 | ±10 % inter-well variance |
| `SCOPE` | `Scope1` | direct upstream emissions |

**Calibration.** Factors were adjusted against published provincial totals rather than
by inventing per-well data. The methane factor was 0.004, roughly six times too high,
which put CH₄ at 7.7 Mt/yr and CO₂e at 297 Mt/yr — above Alberta's entire provincial
total. Recalibrated against the NIR/AER 2014 baseline of ~31.4 Mt CO₂e ÷ 25, it now
gives ~1.2 Mt CH₄/yr.

**Scope is Petrinex wells.** Mined oil sands bitumen, roughly 1.3 Mbbl/d and not reported
per well, is out of scope by construction. That is a boundary, not an undercount.

**Operating margin is OPEX-only**, excluding royalties, transport and G&A, none of which
are available per well. Read it as operating margin, not net profitability.

## 4. Code conventions

- **Path anchoring.** All five scripts compute `ROOT = Path(__file__).resolve().parent.parent`.
  No hard-coded absolute paths; they run from any working directory.
- **`data/raw/`** holds manual, gitignored source files. Scripts never write there.
- **`data/processed/`** holds generated output, as Parquet for analysis and CSV for
  inspection. Gitignored.
- **snake_case** throughout, Python and SQL alike.
- **Vectorisation.** Conditional transforms use `numpy.select()` rather than `apply()`,
  to stay O(n) — scripts 01, 02 and 04.
- **PyArrow compatibility.** Categorical columns are cast to `str` before Parquet export.
- **Console encoding.** Scripts 02 and 03 force `sys.stdout.reconfigure(encoding="utf-8")`,
  without which a Windows cp1252 console raises `UnicodeEncodeError` on characters such as
  `∩` or `é`.

## 5. Deviations from the initial specification

| Point | Originally specified | Built instead | Why |
|---|---|---|---|
| ST37 source | Excel `aer_wells.xlsx` | tab-delimited TXT in `ST37.zip` | the AER publishes no Excel |
| latitude / longitude | columns of ST37 | converted from DLS | absent from the TXT; avoids a geopandas dependency |
| `operator_name`, `field` | names in ST37 | joins to Petrinex reference files | ST37 carries codes only |
| WTI and FX | EIA + Alpha Vantage | Yahoo Finance + Bank of Canada | both originals require API keys |
| relationship test | blocking | `warn` | residual is 24 rows, one UWI lost to case-insensitive dedup, against 99.0 % coverage |

Held to throughout: real public data for volumes, prices and wells; the standard AER BOE
conversion; WCS = WTI − 17.5; costs and emissions simulated but anchored on official
references; no hard-coded absolute paths; numpy vectorisation.

## 6. Glossary

| Term | Definition |
|---|---|
| **BOE** | Barrel of oil equivalent — common energy unit across liquids and gas. |
| **UWI** | Unique Well Identifier — normalised identifier for a well event. |
| **DLS** | Dominion Land Survey — Prairie location grid (Township / Range / Meridian / Section / LSD). |
| **WTI** | West Texas Intermediate — North American crude benchmark. |
| **WCS** | Western Canadian Select — Alberta heavy crude, sold at a discount to WTI. |
| **OPEX / CAPEX** | Operating / capital expenditure. |
| **Scope 1** | Direct greenhouse gas emissions from a facility. |
| **Upstream** | Exploration and production segment, as opposed to midstream and downstream. |
| **AER** | Alberta Energy Regulator — the provincial regulator. |
| **Petrinex** | Petroleum registry system (AB / SK / BC / MB). |
| **ST37** | AER report "List of Wells in Alberta". |
| **Spud** | The start of drilling a well. |

---
---

# Référence — Alberta Energy Operations Intelligence

Constantes, facteurs, sources et vocabulaire du pipeline.

L'architecture, le modèle de données, les tests, le DAX et les instructions d'exécution
sont dans [`ARCHITECTURE.md`](ARCHITECTURE.md) ; les résultats sont dans
[le README](../README.md). Ce fichier ne contient que ce qu'aucun des deux ne répète :
les valeurs codées en dur et la provenance des données.

## 1. Sources et fichiers bruts

Déposés dans `data/raw/`, gitignorés, tous publics.

| Fichier | Source | Utilisé par |
|---|---|---|
| `Vol_YYYY-MM-AB.*` | `petrinex.gov.ab.ca/publicdata/API/Files/AB/Vol/{YYYY-MM}/CSV` | script 01 |
| `ST37.zip` (`WellList.txt`) | `static.aer.ca/.../st37/ST37.zip` | script 02 |
| `St37-layout.pdf` | AER | spécification du format TXT (positions, codes) |
| `ba_codes.csv` | `petrinex.gov.ab.ca/bbreports/PRABAIdentifiers.csv` | code BA → nom opérateur |
| `field_codes.csv` | `petrinex.gov.ab.ca/bbreports/PRAFieldCodes.csv` | code champ → nom |

Les prix ne demandent aucun fichier manuel : WTI depuis Yahoo Finance (`CL=F`,
`/v8/finance/chart/CL=F`), USD/CAD depuis l'API Valet de la Banque du Canada (série
`FXUSDCAD`).

**Format du ST37 TXT.** 24 colonnes tabulées, dont `UWI-DISPLAY-FORMAT`, la localisation
DLS (Township / Méridien / Range / Section / LSD), `WELL-NAME`, `FIELD-CODE`,
`LICENSEE-CODE`, `OPERATOR-CODE`, `FIN-DRL-DATE`, `MODE_SHORT_DESCRIPTION` (statut),
`TYPE_SHORT_DESCRIPTION` (usage). Ni latitude ni longitude, d'où la conversion DLS du
script 02.

## 2. Constantes d'ingestion

| Constante | Valeur | Signification | Script |
|---|---|---|---|
| `MONTHS_BACK` | 24 | longueur de la fenêtre glissante | 01 |
| `PUBLISH_LAG` | 2 | Petrinex publie avec ~2 mois de retard | 01 |
| `MAX_WORKERS` | 6 | téléchargements simultanés | 01 |
| `BOE_LIQUID` | 6.29 | 1 m³ liquide = 6,29 boe | 01 |
| `BOE_GAS` | 35.31 / 6000 | ≈ 0,005885 boe/m³, soit 5,885 boe par 10³m³ | 01 |
| `WCS_DISCOUNT_USD` | 17.5 | décote historique moyenne WCS vs WTI, USD/bbl | 03 |

Produits conservés : `OIL`, `GAS`, `WATER`, `COND`. Activités conservées : `PROD`,
`SHUTIN`, `FUEL`, `VENT`. Les marts resserrent ensuite à `PROD` hors `WATER` — voir
[ARCHITECTURE, assumed trade-offs](ARCHITECTURE.md#assumed-trade-offs).

C'est le facteur gaz qui a mordu. Petrinex déclare le gaz en 10³m³, pas en m³, et les deux
chiffres ci-dessus diffèrent exactement de ce facteur 1000.

## 3. Paramètres de simulation

> Les coûts et les émissions sont **simulés** à partir de volumes BOE réels. Les
> fourchettes sont calées sur l'*AER Annual Report 2023* et l'*Inventaire national des GES
> du Canada 2024*. Ce ne sont pas des données mesurées.

### 3.1 Coûts — script 04

| Constante | Valeur | Effet |
|---|---|---|
| `RNG_SEED` | 42 | générateur numpy reproductible |
| `OPEX_FORAGE_MU / SIGMA` | 12 / 2 | tarif forage $/boe, loi Normale |
| `OPEX_MAINT_MU / SIGMA` | 4 / 1.5 | tarif maintenance $/boe, loi Normale |
| `CAPEX_LOGNORM_MEAN / SIGMA` | 11.5 / 0.6 | CAPEX, log-normale, CAD |
| `CAPEX_RECENT_MULT` | 2.5 | majoration des puits de moins de 3 ans |
| `WINTER_MULT` | 1.15 | OPEX × 1,15 en janvier, février, mars |
| `INCIDENT_RATE / MULT` | 0.05 / 2.0 | 5 % des couples (puits, mois) → OPEX × 2 |

Les tarifs sont tirés par couple (puits, mois) et tronqués à zéro, puis multipliés par le
volume réel : `opex = tarif × volume`. C'est parce que le tarif reste constant sur un
couple que la réallocation au prorata sur puits × mois × produit est exacte et non
approchée.

OPEX/boe obtenu : p05 12,2, médiane 16,7, p95 24,9.

**Le CAPEX est illustratif et non calibré.** Il tombe autour de 33 k$ par puits contre 2 à
8 M$ réels. Il n'apparaît nulle part dans le rapport.

### 3.2 Émissions — script 05

| Constante | Valeur | Signification |
|---|---|---|
| `FACTEUR_CO2_BOE` | 0.055 | t CO₂ / boe, amont O&G Alberta |
| `FACTEUR_CH4_BOE` | 0.000625 | t CH₄ / boe, calibré |
| `CO2EQ_CH4` | 28 | PRG100 du CH₄, GIEC AR6 (≈ AR5) |
| `VARIANCE_PUITS` | 0.10 | variance inter-puits ±10 % |
| `SCOPE` | `Scope1` | émissions directes amont |

**Calage.** Les facteurs ont été ajustés sur des totaux provinciaux publiés, sans inventer
de donnée par puits. Le facteur méthane valait 0,004, environ six fois trop, ce qui plaçait
le CH₄ à 7,7 Mt/an et le CO₂e à 297 Mt/an, au-dessus du total provincial albertain.
Recalé sur la base NIR/AER 2014 de ~31,4 Mt CO₂e ÷ 25, il donne ~1,2 Mt CH₄/an.

**Le périmètre, ce sont les puits Petrinex.** Le bitume miné des sables, environ
1,3 Mbbl/j et non déclaré par puits, en est exclu par construction. C'est une frontière,
pas un sous-comptage.

**La marge opérationnelle est opex-only**, hors redevances, transport et G&A, indisponibles
par puits. À lire comme une marge opératoire, pas comme une rentabilité nette.

## 4. Conventions de code

- **Ancrage des chemins.** Les cinq scripts calculent
  `ROOT = Path(__file__).resolve().parent.parent`. Aucun chemin absolu en dur ; ils
  fonctionnent quel que soit le répertoire de lancement.
- **`data/raw/`** contient les fichiers sources manuels, gitignorés. Les scripts n'y
  écrivent jamais.
- **`data/processed/`** contient les sorties générées, en Parquet pour l'analyse et en CSV
  pour l'inspection. Gitignorés.
- **snake_case** partout, Python comme SQL.
- **Vectorisation.** Les transformations conditionnelles utilisent `numpy.select()` plutôt
  qu'`apply()`, pour rester en O(n) — scripts 01, 02 et 04.
- **Compatibilité PyArrow.** Les colonnes catégorielles sont converties en `str` avant
  l'export Parquet.
- **Encodage console.** Les scripts 02 et 03 forcent
  `sys.stdout.reconfigure(encoding="utf-8")`, sans quoi une console Windows en cp1252 lève
  un `UnicodeEncodeError` sur des caractères comme `∩` ou `é`.

## 5. Écarts par rapport à la spécification initiale

| Point | Spécifié à l'origine | Réalisé | Pourquoi |
|---|---|---|---|
| Source ST37 | Excel `aer_wells.xlsx` | TXT tabulé dans `ST37.zip` | l'AER ne publie pas d'Excel |
| latitude / longitude | colonnes du ST37 | converties depuis le DLS | absentes du TXT ; évite une dépendance geopandas |
| `operator_name`, `field` | noms dans le ST37 | jointures aux référentiels Petrinex | le ST37 ne porte que des codes |
| WTI et change | EIA + Alpha Vantage | Yahoo Finance + Banque du Canada | les deux sources d'origine exigent des clés API |
| test relationnel | bloquant | `warn` | reliquat de 24 lignes, un UWI perdu à la déduplication insensible à la casse, pour 99,0 % de couverture |

Tenu d'un bout à l'autre : données publiques réelles pour les volumes, les prix et les
puits ; conversion BOE standard AER ; WCS = WTI − 17,5 ; coûts et émissions simulés mais
calés sur des références officielles ; aucun chemin absolu en dur ; vectorisation numpy.

## 6. Glossaire

| Terme | Définition |
|---|---|
| **BOE** | Baril équivalent pétrole — unité d'énergie commune aux liquides et au gaz. |
| **UWI** | Unique Well Identifier — identifiant normalisé d'un événement de puits. |
| **DLS** | Dominion Land Survey — grille de localisation des Prairies (Township / Range / Méridien / Section / LSD). |
| **WTI** | West Texas Intermediate — prix de référence du brut nord-américain. |
| **WCS** | Western Canadian Select — brut lourd albertain, vendu avec décote vs WTI. |
| **OPEX / CAPEX** | Coûts d'exploitation / d'investissement. |
| **Scope 1** | Émissions directes de gaz à effet de serre d'une installation. |
| **Upstream** | Segment exploration-production, par opposition au midstream et au downstream. |
| **AER** | Alberta Energy Regulator — le régulateur provincial. |
| **Petrinex** | Système d'enregistrement pétrolier (AB / SK / BC / MB). |
| **ST37** | Rapport AER « List of Wells in Alberta ». |
| **Spud** | Démarrage du forage d'un puits. |
