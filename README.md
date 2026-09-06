# PMMP — Analyse des marchés publics marocains

> **Projet académique — prototype en 15 jours.** Non déployé, à but pédagogique.

Chaîne Big Data + IA qui collecte, structure et analyse des données publiques du
[Portail Marocain des Marchés Publics (PMMP)](https://www.marchespublics.gov.ma/)
pour aider un analyste à repérer, parmi les marchés attribués, ceux qui méritent
un examen humain en priorité — sans jamais affirmer qu'un marché est frauduleux.

L'unité d'analyse est le **marché** (un lot attribué), pas l'entreprise — voir
[`docs/refonte_marche.md`](docs/refonte_marche.md) pour l'historique de cette
bascule et pourquoi l'ancienne approche par entreprise était biaisée.

## Pipeline

```
Portail PMMP
   │  scripts/download_extraits_pv.py, scrape_consultations.py
   ▼
Documents (PDF)              data/samples/PVs/
   │  ocr/ (Tesseract, detection natif/scanne, fra+ara)
   ▼
Texte OCR                    data/processed/ocr/
   │  extraction/ (regex, dictionnaire de champs)
   ▼
Champs structures
   │  scripts/load_database.py
   ▼
PostgreSQL                   database/
   │  features/ (controle qualite), bigdata/ (PySpark)
   ▼
Features par marche
   │  ai/ (Isolation Forest, red flags, analyses pairs/temporelles)
   ▼
Scores + explications SHAP   ai/market_explain.py
   │
   ├── api/        FastAPI, lecture seule (awards, companies, stats)
   └── dashboard/   Streamlit — vue generale, vue marche, anomalies/priorites, XAI
```

Le detail commande-par-commande pour tout reproduire depuis un dépôt cloné est
dans [`docs/onboarding.md`](docs/onboarding.md).

## Démarrer

```bash
cp .env.example .env
pip install -r requirements.txt
```

Tesseract (binaire + packs `fra` et `ara`) s'installe séparément — voir
`docs/onboarding.md` §0. Le pack arabe est obligatoire, pas optionnel.

Avec Docker (PostgreSQL, API, dashboard) :

```bash
docker compose up
```

- API : http://localhost:8000
- Dashboard : http://localhost:8501

Sans Docker, chaque étape du pipeline se lance individuellement via les
scripts de `scripts/` (voir `docs/onboarding.md` pour la séquence complète,
du scraping au chargement en base).

## État du projet

| Domaine | État |
|---|---|
| Scraping, OCR, extraction, base de données | ✅ implémentés et documentés |
| Scoring (Isolation Forest), red flags, SHAP | ✅ implémentés |
| API FastAPI (lecture seule) | ✅ implémentée |
| Dashboard Streamlit | ✅ implémenté (vue générale, vue marché, anomalies/priorités, XAI) |
| Authentification API (JWT) | ⏳ scaffoldée, non implémentée — hors scope du prototype 15 jours |
| Stockage documentaire MinIO | ⏳ prévu (backlog Issue 4), pas encore intégré |

Le détail par Issue est dans [`docs/issues_backlog.md`](docs/issues_backlog.md).

## Structure du dépôt

```
scraper/      Collecte PMMP (requests + BeautifulSoup)
ocr/          Pipeline OCR Tesseract
extraction/   Extraction de champs structurés depuis le texte OCR
database/     Modèles SQLAlchemy, CRUD
bigdata/      Session et jobs PySpark
features/     Contrôle qualité des données
ai/           Isolation Forest, red flags, SHAP, analyses pairs/temporelles
api/          FastAPI (lecture seule)
dashboard/    Application Streamlit
scripts/      CLI de chaque étape du pipeline
data/         Corpus, données traitées, échantillons annotés
docs/         Documentation (onboarding, méthodologie, backlog, dictionnaire de données)
tests/        Tests pytest
```

## Documentation

- [`docs/onboarding.md`](docs/onboarding.md) — reproduire le pipeline pas à pas
- [`docs/methodology.md`](docs/methodology.md) — choix méthodologiques
- [`docs/data_dictionary.md`](docs/data_dictionary.md) — schéma des données
- [`docs/dashboard.md`](docs/dashboard.md) — brief de conception du dashboard
- [`docs/issues_backlog.md`](docs/issues_backlog.md) — suivi par Issue
- [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) — conventions de contribution

## Avertissement

Les scores produits sont des signaux statistiques destinés à orienter une
analyse humaine. Ils ne constituent ni une preuve ni une accusation de fraude.
