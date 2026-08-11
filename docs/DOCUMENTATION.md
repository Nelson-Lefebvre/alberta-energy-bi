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

Prices need no manual file: WTI **and WCS** from the Government of Alberta
(`api.economicdata.alberta.ca/data?table=OilPrices&Type=WCS;WTI`, monthly since 2005),
USD/CAD from the Bank of Canada Valet API (series `FXUSDCAD`). Note the response field is
named `"Type "`, with a trailing space; script 03 strips keys rather than hard-coding it.

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
| `DIFFERENTIEL_MIN` / `MAX` | 0 / 45 | plausibility bounds on WTI − WCS, USD/bbl | 03 |

Kept products: `OIL`, `GAS`, `WATER`, `COND`. Kept activities: `PROD`, `SHUTIN`, `FUEL`,
`VENT`. The marts narrow this further to `PROD` excluding `WATER` — see
[ARCHITECTURE, assumed trade-offs](ARCHITECTURE.md#assumed-trade-offs).

The gas factor is the one that bit. Petrinex reports gas in 10³m³, not m³, and the two
figures above differ by exactly that factor of 1000.

## 3. Simulation parameters

> **Costs** are **simulated** from real BOE volumes, with ranges anchored on the *AER Annual
> Report 2023*. They are not measured data.
>
> **Emissions are not simulated.** Since script 05 was rewritten they come from the FUEL,
> VENT and FLARE volumes operators declare to Petrinex, converted with *National Inventory
> Report* and AER *Directive 060* factors. See 3.2.

### 3.1 Costs — script 04

| Constant | Value | Effect |
|---|---|---|
| `RNG_SEED` | 42 | reproducible numpy generator |
| `OPEX_TAUX['OIL' / 'COND']` | 15 / 2.5 + 5 / 1.5 | ~20 $/boe, drilling + maintenance, Normal |
| `OPEX_TAUX['GAS']` | 4.5 / 1 + 1.5 / 0.5 | ~6 $/boe, i.e. ~$1.00/Mcf at 6.01 Mcf/boe |
| `CAPEX_LOGNORM_MEAN / SIGMA` | 11.5 / 0.6 | CAPEX, log-normal, CAD |
| `CAPEX_RECENT_MULT` | 2.5 | uplift for wells under 3 years old |
| `WINTER_MULT` | 1.15 | OPEX × 1.15 in Jan/Feb/Mar |
| `INCIDENT_RATE / MULT` | 0.05 / 2.0 | 5 % of (well, month) pairs → OPEX × 2 |

Rates are drawn per (well, month, **product**) and truncated at zero, then multiplied by
real volume, so `opex = rate × volume`.

The product grain is not cosmetic. A single rate applied to every molecule was invisible
while gas carried no revenue; once the Alberta gas reference price was ingested, gas
earned $8.72/boe against a flat $17.47 of cost and the report showed it losing money at
−105 %. That was an artefact of the cost model, not a finding. Splitting the rate by
product also required moving generation to the triple, because 68.6 % of the volume comes
from (well, month) pairs producing both gas and liquids, where one rate would have been
an average rather than a cost.

Resulting volume-weighted OPEX/boe: **$6.56 for gas, $21.81 for oil, $21.74 for
condensate**. $14.59 overall.

**CAPEX is illustrative and not calibrated.** It lands near $33k per well against a real
$2 to 8 million. It is not surfaced in the report.

### 3.2 Emissions — script 05

**Emissions are not simulated.** Script 05 reads the FUEL, VENT and FLARE gas volumes
operators report to Petrinex and converts them with published factors. There is no random
draw, so two runs on the same parquet are byte-identical.

| Constant | Value | Meaning |
|---|---|---|
| `CO2_COMBUSTION_KG_M3` | 1.916 | kg CO₂ per m³ burned — NIR Annex 6, table A6.1-5 |
| `CH4_COMBUSTION_KG_M3` | 0.000037 | kg CH₄ per m³ — unburned slip |
| `FRACTION_CH4_GAZ` | 0.80 | methane volume fraction of vented gas, AER Directive 060 |
| `FRACTION_CO2_GAZ` | 0.01 | CO₂ volume fraction of vented gas |
| `DENSITE_CH4_KG_M3` | 0.6784 | CH₄ density at 15 °C, 101.325 kPa |
| `DENSITE_CO2_KG_M3` | 1.8393 | CO₂ density, same conditions |
| `RENDEMENT_TORCHE` | 0.98 | flare combustion efficiency, AER Directive 060 |
| `CO2EQ_CH4` | 28 | CH₄ GWP100, IPCC AR5 |
| `SCOPE` | `Scope1` | direct upstream emissions |

**Two grains in one column.** Petrinex does not report everything per well. Sixteen-character
identifiers are well UWIs; seven-character ones are facility codes, and facilities carry
**97.9%** of the emitting volume while existing nowhere in `dim_puits`. Facility volumes are
therefore allocated to the producing wells of the same operator in the same month, pro rata
by volume — the rule already applied to OPEX. Because the allocation never crosses an
operator boundary, the total per operator stays exact and operator carbon intensity is a
measurement. A single well's intensity is an allocation, not a measurement, and should not
be used to rank wells against each other.

**Declared, not total.** Petrinex records the gas an operator measures and reports. It does
not cover fugitives, pneumatic vents or undeclared methane. The CH₄ produced here is roughly
a tenth of provincial upstream estimates. That is the gap between declared and real, not a
calculation error, and the report should say so.

**Facilities without production.** 4.8% of CO₂eq belongs to operators running facilities but
producing nothing that month — processing plants and midstream. Allocating it to a third
party's wells would be wrong, so those rows keep their facility code and land in the
"outside AER register" bucket, where they belong.

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
| WTI, WCS and FX | EIA + Alpha Vantage | Government of Alberta + Bank of Canada | both originals require API keys; Alberta publishes WCS measured, so it is no longer derived from WTI |
| relationship test | blocking | `warn` | residual is 24 rows, one UWI lost to case-insensitive dedup, against 99.0 % coverage |

Held to throughout: real public data for volumes, prices and wells; the standard AER BOE
conversion; WTI and WCS both taken measured from the province; emissions derived from
volumes declared to Petrinex; costs simulated but anchored on official references; no
hard-coded absolute paths; numpy vectorisation.

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

Les prix ne demandent aucun fichier manuel : WTI **et WCS** depuis le Gouvernement de
l'Alberta (`api.economicdata.alberta.ca/data?table=OilPrices&Type=WCS;WTI`, mensuel
depuis 2005), USD/CAD depuis l'API Valet de la Banque du Canada (série `FXUSDCAD`).
Attention, le champ de la réponse s'appelle `"Type "`, avec une espace finale : le
script 03 normalise les clés plutôt que de coder ce détail en dur.

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
| `DIFFERENTIEL_MIN` / `MAX` | 0 / 45 | bornes de vraisemblance de l'écart WTI − WCS, USD/bbl | 03 |

Produits conservés : `OIL`, `GAS`, `WATER`, `COND`. Activités conservées : `PROD`,
`SHUTIN`, `FUEL`, `VENT`. Les marts resserrent ensuite à `PROD` hors `WATER` — voir
[ARCHITECTURE, assumed trade-offs](ARCHITECTURE.md#assumed-trade-offs).

C'est le facteur gaz qui a mordu. Petrinex déclare le gaz en 10³m³, pas en m³, et les deux
chiffres ci-dessus diffèrent exactement de ce facteur 1000.

## 3. Paramètres de simulation

> Les **coûts** sont **simulés** à partir de volumes BOE réels, avec des fourchettes calées
> sur l'*AER Annual Report 2023*. Ce ne sont pas des données mesurées.
>
> **Les émissions ne le sont plus.** Depuis la réécriture du script 05, elles proviennent
> des volumes FUEL, VENT et FLARE déclarés à Petrinex par les opérateurs, convertis avec
> les facteurs de l'*Inventaire national des GES* et de la *Directive 060* de l'AER.
> Voir 3.2.

### 3.1 Coûts — script 04

| Constante | Valeur | Effet |
|---|---|---|
| `RNG_SEED` | 42 | générateur numpy reproductible |
| `OPEX_TAUX['OIL' / 'COND']` | 15 / 2,5 + 5 / 1,5 | ~20 $/boe, forage + maintenance, Normale |
| `OPEX_TAUX['GAS']` | 4,5 / 1 + 1,5 / 0,5 | ~6 $/boe, soit ~1,00 $/Mcf à 6,01 Mcf/boe |
| `CAPEX_LOGNORM_MEAN / SIGMA` | 11.5 / 0.6 | CAPEX, log-normale, CAD |
| `CAPEX_RECENT_MULT` | 2.5 | majoration des puits de moins de 3 ans |
| `WINTER_MULT` | 1.15 | OPEX × 1,15 en janvier, février, mars |
| `INCIDENT_RATE / MULT` | 0.05 / 2.0 | 5 % des couples (puits, mois) → OPEX × 2 |

Les tarifs sont tirés par triplet (puits, mois, **produit**) et tronqués à zéro, puis
multipliés par le volume réel : `opex = tarif × volume`.

Le grain produit n'est pas cosmétique. Un tarif unique pour toutes les molécules restait
invisible tant que le gaz ne portait aucun revenu ; depuis l'ingestion du prix de
référence albertain, le gaz rapporte 8,72 $/boe contre un coût plat de 17,47 $, et le
rapport l'affichait déficitaire à −105 %. C'était un artefact du modèle de coût, pas un
résultat. Le passage au triplet était nécessaire parce que 68,6 % du volume vient de
couples (puits, mois) produisant à la fois du gaz et des liquides, où un tarif unique
aurait été une moyenne et non un coût.

OPEX/boe pondéré obtenu : **6,56 $ pour le gaz, 21,81 $ pour le pétrole, 21,74 $ pour le
condensat**. Au global 14,59 $.

**Le CAPEX est illustratif et non calibré.** Il tombe autour de 33 k$ par puits contre 2 à
8 M$ réels. Il n'apparaît nulle part dans le rapport, et sa mesure DAX a été retirée du
modèle sémantique.

### 3.2 Émissions — script 05

**Les émissions ne sont plus simulées.** Le script 05 lit les volumes de gaz FUEL, VENT et
FLARE que les opérateurs déclarent à Petrinex et les convertit avec des facteurs publiés.
Aucun tirage aléatoire : deux exécutions sur le même parquet donnent le même fichier au
bit près.

| Constante | Valeur | Signification |
|---|---|---|
| `CO2_COMBUSTION_KG_M3` | 1.916 | kg CO₂ par m³ brûlé — NIR annexe 6, tableau A6.1-5 |
| `CH4_COMBUSTION_KG_M3` | 0.000037 | kg CH₄ par m³ — imbrûlé de combustion |
| `FRACTION_CH4_GAZ` | 0.80 | fraction volumique de méthane du gaz évacué, Directive 060 |
| `FRACTION_CO2_GAZ` | 0.01 | fraction volumique de CO₂ du gaz évacué |
| `DENSITE_CH4_KG_M3` | 0.6784 | masse volumique du CH₄ à 15 °C, 101,325 kPa |
| `DENSITE_CO2_KG_M3` | 1.8393 | masse volumique du CO₂, mêmes conditions |
| `RENDEMENT_TORCHE` | 0.98 | rendement de combustion des torches, Directive 060 |
| `CO2EQ_CH4` | 28 | PRG100 du CH₄, GIEC AR5 |
| `SCOPE` | `Scope1` | émissions directes amont |

**Deux grains dans une même colonne.** Petrinex ne déclare pas tout au puits. Les
identifiants de 16 caractères sont des UWI de puits, ceux de 7 caractères des codes
d'installation — et les installations portent **97,9 %** du volume émetteur tout en
n'existant nulle part dans `dim_puits`. Leurs volumes sont donc répartis sur les puits
producteurs du même opérateur et du même mois, au prorata du volume, règle déjà appliquée
à l'OPEX. Comme la répartition ne franchit jamais la frontière d'un opérateur, le total
par opérateur reste exact et l'intensité carbone par opérateur est une mesure. Celle d'un
puits isolé est une allocation, pas une mesure, et ne doit pas servir à classer des puits
entre eux.

**Déclaré, pas total.** Petrinex enregistre le gaz que l'opérateur mesure et rapporte. Ni
les fuites diffuses, ni les évents de pneumatiques, ni le méthane non déclaré n'y figurent.
Le CH₄ obtenu vaut environ un dixième des estimations provinciales amont : c'est l'écart
entre déclaré et réel, pas une erreur de calcul, et le rapport doit le dire.

**Installations sans production.** 4,8 % du CO₂eq revient à des opérateurs qui exploitent
des installations sans rien produire ce mois-là — usines de traitement, intermédiaires. Le
répartir sur les puits d'un tiers serait faux : ces lignes gardent leur code installation
et tombent dans le seau « hors référentiel AER », où elles sont à leur place.

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
| WTI, WCS et change | EIA + Alpha Vantage | Gouvernement de l'Alberta + Banque du Canada | les deux sources d'origine exigent des clés API ; l'Alberta publiant le WCS mesuré, il n'est plus dérivé du WTI |
| test relationnel | bloquant | `warn` | reliquat de 24 lignes, un UWI perdu à la déduplication insensible à la casse, pour 99,0 % de couverture |

Tenu d'un bout à l'autre : données publiques réelles pour les volumes, les prix et les
puits ; conversion BOE standard AER ; WTI et WCS pris mesurés à la source provinciale ;
émissions dérivées des volumes déclarés à Petrinex ; coûts simulés mais calés sur des
références officielles ; aucun chemin absolu en dur ; vectorisation numpy.

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
