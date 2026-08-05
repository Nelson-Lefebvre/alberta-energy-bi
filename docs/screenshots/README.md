# Captures d'écran du rapport

Le README principal intègre cinq images depuis ce dossier. Les noms de fichiers sont
imposés — le README pointe dessus en dur :

> Les captures actuelles ont été produites par export PDF puis conversion
> (`pdftoppm -png -r 120`), soit 1 660 × 960 px. Elles reflètent le modèle **après** la
> correction du facteur d'échelle gaz et de l'assiette des émissions : OPEX/boe 17,48 $
> et intensité 0,055. Toute capture antérieure affichant 9,21 $ ou 0,060 est périmée.

| Fichier attendu | Page du rapport |
|---|---|
| `p1_executive.png` | P1 — Executive Summary |
| `p2_production.png` | P2 — Production Operations |
| `p3_costs.png` | P3 — Cost & Financial |
| `p4_esg.png` | P4 — ESG & Carbon |
| `p5_forecast.png` | P5 — Production Forecast |

## Procédure

1. Ouvrir `reporting/` dans Power BI Desktop (projet **PBIP**, pas un `.pbix` — voir §8
   du README principal) et laisser le modèle se rafraîchir depuis `data/energy.duckdb`.
2. Se placer sur la page, **retirer toute sélection de slicer** (les captures doivent
   montrer l'état non filtré, sinon les KPI de la capture ne correspondent plus aux
   chiffres annoncés dans le README).
3. Exporter la page : `Fichier ▸ Exporter ▸ PDF`, puis convertir en PNG ; ou capture
   d'écran de la zone de rapport seule (sans le ruban ni le volet Données).
4. Enregistrer sous le nom exact du tableau ci-dessus, dans ce dossier.

## Conseils

- **Largeur ~1 600 px**, format 16:9 — c'est le ratio du canevas des pages.
- Vérifier qu'aucun visuel n'affiche encore un état de chargement.
- Le mode sombre du thème Power BI passe mal sur un README GitHub consulté en clair :
  garder le thème par défaut du rapport.
- Éviter d'y faire figurer des noms d'opérateurs si le rapport est publié ailleurs —
  ici les données sont publiques (Petrinex / AER), donc aucun enjeu de confidentialité.

## Poids

Ces PNG sont versionnés. Les garder sous ~500 Ko chacun (`pngquant`, `oxipng` ou un
export à 1 600 px suffisent) pour ne pas alourdir le dépôt.
