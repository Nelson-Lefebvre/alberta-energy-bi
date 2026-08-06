# Alberta Energy Operations Intelligence

**Chaîne analytique complète sur le bassin pétrolier albertain** — de l'ingestion des
déclarations réglementaires brutes jusqu'au rapport exécutif. 7,2 M de lignes Petrinex,
598 396 puits du registre AER, un modèle en étoile dans DuckDB, un rapport Power BI de
cinq pages.

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![dbt](https://img.shields.io/badge/dbt-1.11-FF694B?logo=dbt&logoColor=white)
![DuckDB](https://img.shields.io/badge/DuckDB-1.10-FFF000?logo=duckdb&logoColor=black)
![Power BI](https://img.shields.io/badge/Power%20BI-PBIP-F2C811?logo=powerbi&logoColor=black)
![Tests](https://img.shields.io/badge/dbt%20build-42%20pass%20%C2%B7%200%20error-2E7D32)
![Statut](https://img.shields.io/badge/statut-en%20cours%20de%20d%C3%A9veloppement-orange)

![Synthèse exécutive du rapport Power BI](docs/screenshots/p1_executive.png)

| | |
|---|---|
| **Période** | 24 mois · mai 2024 → avril 2026 |
| **Production** | 3,54 Md boe · 4,85 M boe/jour |
| **Puits** | 598 396 au registre · 149 340 producteurs |
| **Opérateurs** | 3 015 |
| **Revenu estimé** | 137,7 Md $ CA · 73,9 $/boe liquides |
| **OPEX par baril** | 17,48 $ |
| **CO₂ Scope 1** | 194,6 Mt · 0,0550 tCO₂/boe |

> Production, prix et localisation sont **réels**. Coûts et émissions sont **simulés** à
> partir de ces volumes, avec des facteurs calés sur l'*AER Annual Report 2023* et le
> *NIR 2024*. Le détail des arbitrages est en fin de page.

---

## Ce que ce projet démontre

| Compétence | Où la voir |
|---|---|
| **Ingestion de données réglementaires brutes** | ST37 en TXT tabulé sans lat/lon : parsing, reconstruction des UWI, **conversion du Dominion Land Survey en coordonnées géographiques** |
| **Modélisation dimensionnelle** | Étoile à 3 faits et 3 dimensions, dimension conforme `dim_region`, grain explicite et documenté par table |
| **Qualité de données** | 43 tests dbt, dont 4 tests de **plausibilité** écrits après deux régressions réelles |
| **Analytics engineering** | dbt Core sur DuckDB, staging → marts, lineage généré |
| **BI et DAX** | 27 mesures, ratios au même grain, RLS 3 rôles, projet **PBIP** versionné en TMDL/JSON — relisible en revue de code, pas un binaire |
| **Domaine O&G** | BOE, WCS, DLS, UWI, Scope 1, GWP100, statuts de puits AER |
| **Débogage analytique** | voir ci-dessous — c'est la partie la plus intéressante |

---

## Deux bugs, et pourquoi ils sont le meilleur du projet

Le pipeline produisait des chiffres crédibles, et 39 tests dbt passaient au vert. Deux
d'entre eux étaient pourtant faux.

### 1. Un écart régional qui n'existait pas

L'OPEX par baril variait de 4,03 $ à 14,52 $ selon la région. Tentant d'y lire une
différence de structure de coûts. En réalité :

| Région | Part de gaz | OPEX/boe |
|---|---|---|
| Nord | 16,9 % | 14,52 $ |
| Peace River | 76,7 % | 4,08 $ |
| Central | 76,9 % | 4,03 $ |

Le ratio était une **fonction inverse parfaite de la part de gaz** — signature d'un
problème d'unité, pas d'un signal métier. Petrinex déclare le gaz en 10³m³ et non en m³.
Le correctif d'échelle était appliqué dans la branche production du pipeline, mais pas
dans la branche coûts : le numérateur et le dénominateur ne parlaient pas la même unité.

Après correction, l'OPEX/boe se tient entre **17,38 et 17,61 $ sur les cinq régions** —
l'écart avait entièrement disparu.

### 2. Un dénominateur qui ne couvrait pas son numérateur

Les émissions étaient générées sur toutes les lignes Petrinex, production commercialisée
ou non. La production, elle, excluait le gaz combustible, torché et les puits fermés.
Résultat : **11 943 puits portaient 16,1 Mt de CO₂ sans aucune production** en face,
gonflant l'intensité carbone de 0,0551 à 0,0597.

### La correction, et le filet

Même cause dans les deux cas : une règle de périmètre appliquée dans une branche du
pipeline mais pas dans ses sœurs. La définition vit désormais à un seul endroit
(`scripts/production_universe.py`), importée par les deux générateurs et alignée sur le
mart dbt.

Puis quatre tests de plausibilité, parce que les tests structurels ne pouvaient rien
voir — les tables étaient valides, les clés présentes, l'intégrité référentielle
intacte :

| Test | Ce qu'il verrouille |
|---|---|
| `assert_univers_partages` | coûts, émissions et production couvrent le même ensemble (puits, mois) |
| `assert_facteur_conversion_boe` | 6,290 boe/m³ liquides · 5,885 boe/10³m³ gaz |
| `assert_opex_par_boe_plausible` | OPEX/boe dans 8–30, **par région** |
| `assert_intensite_carbone_plausible` | intensité dans 0,050–0,060, **par région** |

Le grain fait tout : pendant le bug, l'OPEX/boe **global** valait 9,21 $, donc dans la
bande. Un contrôle agrégé serait passé au vert. Seule la ventilation par région
trahissait le défaut.

Rejoués contre la base d'avant correctif, ces tests renvoient **3 régions hors bande**
sur l'OPEX, **1 sur l'intensité**, et **413 760 couples orphelins** sur les périmètres.
Ils auraient bloqué le build.

---

## Le rapport

Cinq pages, un slicer région conforme partagé, RLS à 3 rôles.

### Production & Puits

![Production et puits](docs/screenshots/p2_production.png)

Carte ArcGIS des puits géolocalisés — coordonnées reconstruites depuis le DLS —
compteurs de puits producteurs, actifs et abandonnés, production mensuelle et sa
moyenne mobile 3 mois.

> Capture filtrée sur **2025** : les totaux portent sur l'année, pas sur les 24 mois.

### Coûts & Rentabilité

![Coûts et rentabilité](docs/screenshots/p3_costs.png)

Revenu, OPEX total et par baril, marge opératoire, waterfall de l'OPEX par région.
L'OPEX/boe plat autour de 17,5 $ sur les cinq régions est le contrôle visuel qu'aucun
biais d'unité ne subsiste.

### Performance ESG

![Performance ESG](docs/screenshots/p4_esg.png)

CO₂ Scope 1 et CO₂eq (CH₄ × 28, GWP100 AR6), intensité carbone, jauge face à la cible
Alberta 2030 de 0,040 tCO₂/boe — soit un écart de +37,5 %. La conversion est
vérifiable à la main : 194,6 + 2,21 × 28 = 256,5 Mt.

### Prévision & Tendances

![Prévision et tendances](docs/screenshots/p5_forecast.png)

Prévision native Power BI à 6 mois, intervalle de confiance 95 %, encadrée par la
tendance annuelle (+3,4 %) et le coefficient de variation (5,4 %).

---

## Architecture

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
 │  Power BI Desktop — PBIP  (étoile · 27 mesures DAX · RLS)     │
 └──────────────────────────────────────────────────────────────┘
```

### Sources

| Source | Contenu | Format |
|---|---|---|
| **Petrinex – Conventional Volumetrics** | Production mensuelle AB (24 mois) | ZIP→CSV |
| **AER ST37 – List of Wells** | Registre des puits (DLS, statut, licence) | ZIP→TXT |
| **Petrinex – Business Associate / Field Codes** | Référentiels opérateurs et champs | CSV |
| **Yahoo Finance – WTI (CL=F)** | Prix WTI mensuel, base du WCS | JSON |
| **Banque du Canada – FXUSDCAD** | Taux de change USD/CAD mensuel | JSON |

URLs complètes dans [`docs/DOCUMENTATION.md`](docs/DOCUMENTATION.md).

### Pipeline Python

| Script | Sortie | Rôle |
|---|---|---|
| `01_ingest_petrinex.py` | `petrinex24.parquet` | Téléchargement parallèle, double dézip, nettoyage, conversion BOE |
| `02_ingest_aer_wells.py` | `dim_puits.parquet` | Parsing ST37, reconstruction UWI, **DLS→lat/lon**, jointures référentielles |
| `03_ingest_prices.py` | `dim_prix.parquet` | WTI + USD/CAD → WCS CAD mensuel |
| `04_generate_costs.py` | `fact_couts.parquet` | OPEX/CAPEX simulés (saisonnalité hivernale, incidents) |
| `05_generate_emissions.py` | `fact_emissions.parquet` | CO₂/CH₄/CO₂eq Scope 1 (facteurs NIR 2024) |

`production_universe.py` porte le **périmètre canonique** partagé par 04 et 05 —
correctif d'unité gaz et filtre production commercialisée, identiques au mart dbt.
C'est la correction du bug n°1.

**Couverture UWI ST37 ↔ Petrinex : 99,0 %** (1 426 puits producteurs hors référentiel
sur 149 340).

---

## Modèle de données

![Schéma en étoile](docs/diagramme_bdd.png)

> Diagramme en retard de deux évolutions : `dim_region` n'y figure pas, et
> `fact_production_enriched` porte désormais aussi `opex_cad` et `co2_tonnes`. Grains,
> clés et cardinalités restent à jour.

- **Staging** (vues) : `stg_petrinex_production`, `stg_aer_wells`, `stg_eia_prices`,
  `stg_costs`, `stg_emissions`
- **Marts** (tables) : `dim_date`, `dim_puits`, `dim_region`,
  `fact_production_enriched`, `fact_kpis_mensuels`, `fact_emissions_scope`

**`dim_region` est une dimension conforme.** `dim_puits` et `fact_kpis_mensuels` ne sont
pas reliés entre eux : un slicer posé sur la colonne d'un fait ne filtrerait que ce fait.
Les pages filtrent `dim_region[region]`, qui atteint les deux branches.

**`fact_production_enriched`** (4 342 506 lignes, grain puits × mois × produit) porte le
volume, le revenu, l'OPEX et le CO₂. Ces deux derniers sont répartis au prorata du volume
depuis la simulation (puits × mois) — répartition **exacte**, puisque les scripts
calculent `opex = taux × volume` à taux constant sur un couple. C'est ce grain fin qui
rend l'OPEX et l'intensité filtrables par opérateur, statut, puits et produit.

`dbt build` → **42 PASS · 1 WARN · 0 ERROR** sur 43 nœuds. Le warning est un test de
relation à 24 lignes : 1 UWI producteur absent de `dim_puits` après déduplication
insensible à la casse, sans effet côté Power BI qui apparie de la même façon.
Lineage complet : [`docs/dbt/index.html`](docs/dbt/index.html).

---

## Mesures DAX

```dax
OPEX par boe =                          -- métrique phare O&G
DIVIDE ( [OPEX Total CAD], [Production BOE] )

OPEX Total CAD =                        -- grain puits × mois × produit
SUM ( fact_production_enriched[opex_cad] )

Intensité carbone =                     -- ESG : tCO₂ / boe
DIVIDE ( [CO2 Scope 1 (t)], [Production BOE] )

Marge Opérationnelle % =                -- opex-only, PAS une marge nette
DIVIDE ( [Revenu Estimé CAD] - [OPEX Total CAD], [Revenu Estimé CAD] )

Tendance YoY % =                        -- 12 derniers mois vs 12 précédents
DIVIDE ( [Production 12 derniers mois] - [Production 12 mois précédents],
         [Production 12 mois précédents] )
```

**27 mesures** en 5 dossiers (Production, Finance, ESG, Time Intelligence, Puits).
**RLS 3 rôles** (Nord / Sud / Admin) sur `dim_puits`, `fact_kpis_mensuels`,
`fact_emissions_scope` et `dim_region`.

Chaque ratio prend numérateur et dénominateur **sur le même fait**. Un ratio dont les
deux termes vivent à des grains différents se fige silencieusement dès qu'on pose un
slicer que l'un des deux n'atteint pas — c'est le principal piège de ce modèle.

---

## Reproduire

```powershell
# 1. Environnement
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Données brutes manuelles dans data/raw/ :
#    ST37.zip, ba_codes.csv, field_codes.csv

# 3. Pipeline Python (ordre imposé)
python scripts\01_ingest_petrinex.py
python scripts\02_ingest_aer_wells.py
python scripts\03_ingest_prices.py
python scripts\04_generate_costs.py
python scripts\05_generate_emissions.py

# 4. Transformation dbt
cd dbt_project\energy_analytics
dbt build --profiles-dir .
dbt docs generate --profiles-dir .

# 5. Ouvrir le dossier reporting\ dans Power BI Desktop, puis Actualiser
```

**`profiles.yml` n'est pas versionné** (chemin machine). En créer un dans
`dbt_project/energy_analytics/` :

```yaml
energy_analytics:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: "../../data/energy.duckdb"
      threads: 4
```

Deux points bloquants après un clone : les vues de staging lisent les Parquet en chemin
**relatif**, donc lancer dbt depuis `dbt_project/energy_analytics` ; et le chemin de la
base est **codé en dur** dans les partitions M du modèle sémantique, à adapter.

Le rapport est un projet **PBIP**, pas un `.pbix` : modèle en TMDL, visuels en JSON,
donc lisibles et diffables en revue de code.

---

## Arbitrages assumés

- **Vue bassin, pas vue opérateur.** Les données couvrent les 3 015 opérateurs de la
  province. C'est une analyse de bassin, du type de celle que produit un régulateur ou
  un analyste marché, pas le pilotage d'une société.
- **Gaz non valorisé.** Le WCS est un benchmark pétrole lourd ; faute de prix AECO, le
  gaz compte dans les volumes et les émissions mais pas dans le revenu. Le valoriser au
  prix du pétrole l'aurait surestimé d'un facteur 4 à 5. La marge est donc calculée sur
  un revenu liquides-only, ce qui la rend **conservatrice**.
- **Périmètre de production.** Seule la production commercialisée est retenue (`PROD`,
  hors `WATER`) : gaz combustible, torché et puits fermés sont exclus. Coûts, émissions
  et production partagent ce périmètre — c'est une contrainte du modèle, pas un détail.
- **1 426 puits producteurs hors référentiel AER** (~1 % de la production) : présents
  dans Petrinex, absents de l'extrait ST37. Rattachés à un bucket explicite plutôt que
  masqués, pour que les totaux restent justes et l'écart visible.
- **ST37** publié en TXT tabulé sans lat/lon ni noms → coordonnées converties depuis le
  DLS, noms restitués via les référentiels Petrinex.
- **Prix** : EIA et Alpha Vantage exigent des clés API → remplacés par Yahoo Finance et
  la Banque du Canada (sans clé), avec WCS = WTI − 17,5 $.
- **CAPEX indicatif** : simulé en log-normale, il illustre la structure de coûts et
  n'est **pas calé** sur les coûts de forage réels albertains.

---

## État d'avancement

Le pipeline tourne de bout en bout et le rapport est exploitable. Restent ouverts :

- **CAPEX** — à recalibrer (~33 k$/puits contre 2–8 M$ réels), puis à exposer sur la
  page Coûts qui n'affiche aujourd'hui que de l'OPEX.
- **Fraîcheur** — le jeu s'arrête à avril 2026 ; le rafraîchissement n'est pas automatisé
  (`airflow_dags/` est un emplacement réservé, pas un DAG).
- **Parc inactif** — 449 057 puits sans production dont 66 984 abandonnés, soit 75 % du
  registre. Le passif de remise en état est un sujet majeur en Alberta et la donnée est
  déjà là ; la page dédiée reste à construire.
- **Slicers UWI** — ~598 k valeurs sur deux pages, à remplacer par une recherche.
- **Publication** — le rapport n'est pas encore publié (Publish to Web).

---

*Projet portfolio Data Analyst — Calgary 2026.*
