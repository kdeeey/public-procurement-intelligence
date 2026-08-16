# Exploitation des marchés publics
## Chaîne Big Data, IA d'océrisation et valorisation fiscale

> **Projet académique — Prototype en 15 jours**

---

## 1. Présentation du projet

Ce projet consiste à développer un prototype de plateforme intelligente permettant de collecter, traiter, structurer et analyser des données relatives aux marchés publics marocains.

Le système exploite des **données accessibles publiquement sur le Portail Marocain des Marchés Publics (PMMP)** afin de construire une chaîne complète allant du Web Scraping jusqu'à l'analyse intelligente des marchés.

[Portail Marocain des Marchés Publics (PMMP)](https://www.marchespublics.gov.ma/?utm_source=chatgpt.com)

La plateforme combine plusieurs technologies :

- Web Scraping
- Gestion documentaire
- OCR
- Traitement du langage naturel
- Extraction d'informations
- Data Engineering
- Big Data
- Machine Learning
- Détection d'anomalies
- Valorisation fiscale
- Cybersécurité
- API REST
- Dashboard interactif

L'objectif est de transformer des documents et informations non structurés en **données structurées, analysables et traçables**, puis d'identifier des **signaux de risque et anomalies** pouvant aider à l'analyse fiscale.

---

# 2. Problématique

Les marchés publics génèrent un grand volume d'informations réparties dans différents formats :

- pages Web ;
- annonces ;
- résultats ;
- PDF ;
- documents scannés ;
- tableaux ;
- procès-verbaux ;
- documents administratifs.

Une partie importante de ces données n'est pas directement exploitable par une machine.

La problématique du projet est donc :

> **Comment concevoir une chaîne Big Data et IA capable de collecter automatiquement des informations publiques relatives aux marchés publics, d'extraire les informations contenues dans les documents grâce à l'OCR et au NLP, de structurer ces données, de détecter des anomalies et de produire des indicateurs de risque fiscal, tout en sécurisant l'ensemble de la chaîne ?**

---

# 3. Objectif général

Développer un prototype **end-to-end** permettant de passer de :

```text
Donnée publique
      ↓
Scraping
      ↓
Document
      ↓
OCR
      ↓
Extraction
      ↓
Donnée structurée
      ↓
Big Data
      ↓
IA / Anomaly Detection
      ↓
Indicateurs de risque
      ↓
Dashboard sécurisé
```

---

# 4. Objectifs spécifiques

## 4.1 Collecte des données

- Scraper les informations publiques du PMMP.
- Récupérer les métadonnées des marchés.
- Télécharger les documents accessibles publiquement.
- Conserver les URLs sources.
- Éviter les doublons.
- Gérer les erreurs de collecte.

## 4.2 Gestion documentaire

- Stocker les PDF et images.
- Classifier les documents.
- Calculer des hashes.
- Assurer la traçabilité.
- Rechercher les documents.

## 4.3 OCR

- Identifier les documents scannés.
- Convertir les documents en images si nécessaire.
- Prétraiter les images.
- Effectuer l'OCR.
- Nettoyer le texte.

## 4.4 Extraction

Extraire automatiquement :

- référence du marché ;
- objet ;
- acheteur public ;
- entreprise ;
- montant ;
- date ;
- lieu ;
- secteur ;
- catégorie ;
- type de procédure ;
- lots ;
- ICE lorsqu'il est présent publiquement ;
- autres entités pertinentes.

## 4.5 Big Data

- Nettoyer les données.
- Normaliser les informations.
- Structurer les données.
- Effectuer des agrégations.
- Calculer des statistiques.
- Produire des datasets analytiques.

## 4.6 IA

- Identifier des valeurs atypiques.
- Détecter des comportements inhabituels.
- Calculer des indicateurs.
- Produire un score de risque.
- Fournir une explication du score.

## 4.7 Cybersécurité

- Authentification.
- Autorisation.
- RBAC.
- Protection de l'API.
- Gestion sécurisée des mots de passe.
- Audit.
- Logs.
- Protection des documents.
- Analyse des risques.

---

# 5. Source principale des données

La source principale du projet est :

[Portail Marocain des Marchés Publics](https://www.marchespublics.gov.ma/?utm_source=chatgpt.com)

Le projet se concentre sur les informations publiquement accessibles concernant les marchés publics.

Selon les informations disponibles sur le portail, les données pertinentes peuvent notamment concerner :

- appels d'offres ;
- consultations ;
- résultats définitifs ;
- informations d'attribution ;
- extraits de PV ;
- informations relatives aux marchés ;
- documents associés.

---

# 6. Stratégie de scraping

Le scraper ne cherchera pas à aspirer l'intégralité du portail.

Pour un prototype de 15 jours, l'objectif est de construire une collecte contrôlée sur un **échantillon représentatif**.

### Exemple

```text
PMMP
 │
 ├── Recherche / Listings
 │
 ├── Informations du marché
 │
 ├── Résultats
 │
 └── Documents accessibles
```

Le scraper récupère :

```text
Reference
Object
Buyer
Category
Sector
Publication date
Deadline
Location
Procedure type
Document URLs
Source URL
```

Lorsque des résultats d'attribution sont disponibles :

```text
Winning company
Award amount
Award date
```

---

# 7. Principes du scraping

Le scraper doit :

- respecter les règles applicables au site ;
- limiter la fréquence des requêtes ;
- éviter de surcharger le serveur ;
- ne pas contourner une authentification ;
- ne pas récupérer de données privées ;
- gérer les erreurs réseau ;
- conserver les URLs sources ;
- identifier les doublons ;
- journaliser les opérations importantes.

### Architecture du scraper

```text
PMMP
 │
 ▼
HTTP Client
 │
 ▼
HTML
 │
 ▼
Parser
 │
 ├── Market metadata
 │
 ├── Results
 │
 └── Document URLs
        │
        ▼
   Downloader
        │
        ▼
    Raw Storage
```

---

# 8. Architecture générale

```text
                         ┌──────────────────────┐
                         │       PMMP           │
                         │ Public Data Sources  │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │       SCRAPER        │
                         │ Requests / BS4       │
                         │ Scrapy / Playwright  │
                         └──────────┬───────────┘
                                    │
                   ┌────────────────┴────────────────┐
                   ▼                                 ▼
          ┌─────────────────┐               ┌─────────────────┐
          │   METADATA      │               │    DOCUMENTS    │
          │                 │               │                 │
          │ JSON / CSV      │               │ PDF / Images    │
          └────────┬────────┘               └────────┬────────┘
                   │                                 │
                   ▼                                 ▼
          ┌─────────────────┐               ┌─────────────────┐
          │   PostgreSQL    │               │      MinIO      │
          └────────┬────────┘               └────────┬────────┘
                   │                                 │
                   │                                 ▼
                   │                        ┌─────────────────┐
                   │                        │       OCR       │
                   │                        │ Tesseract/OpenCV│
                   │                        └────────┬────────┘
                   │                                 │
                   │                                 ▼
                   │                        ┌─────────────────┐
                   │                        │ TEXT CLEANING   │
                   │                        └────────┬────────┘
                   │                                 │
                   └────────────────┬────────────────┘
                                    ▼
                         ┌──────────────────────┐
                         │ INFORMATION          │
                         │ EXTRACTION           │
                         │                      │
                         │ Regex + spaCy        │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │ STRUCTURED DATA      │
                         │ PostgreSQL / Parquet │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │       PYSPARK        │
                         │                      │
                         │ Cleaning             │
                         │ Transformations      │
                         │ Aggregations         │
                         │ Statistics           │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │       IA / ML        │
                         │                      │
                         │ Features             │
                         │ Anomalies            │
                         │ Risk Score            │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │       FASTAPI        │
                         │                      │
                         │ REST API             │
                         │ Authentication       │
                         │ RBAC                 │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │      STREAMLIT       │
                         │                      │
                         │ Dashboard            │
                         │ Search               │
                         │ Analytics            │
                         │ Risk Analysis        │
                         └──────────────────────┘

                         ┌──────────────────────┐
                         │   SECURITY LAYER     │
                         │                      │
                         │ JWT                  │
                         │ RBAC                 │
                         │ HTTPS                │
                         │ Audit Logs           │
                         └──────────────────────┘
```

---

# 9. Architecture des modules

Le projet est organisé en cinq modules principaux.

```text
Module 1 → Gestion documentaire
Module 2 → OCR & Extraction
Module 3 → Big Data
Module 4 → IA & Valorisation
Module 5 → Cybersécurité
```

Les modules sont interconnectés et ne fonctionnent pas comme cinq projets indépendants.

---

# 10. Module 1 — Gestion documentaire

## Fonctionnalités

- récupération des documents ;
- import PDF/images ;
- archivage ;
- classification ;
- métadonnées ;
- recherche ;
- déduplication ;
- traçabilité.

### Types de documents

```text
AVIS_APPEL_OFFRES
CONSULTATION
RESULTAT_DEFINITIF
PV
RAPPORT
CPS
AUTRE
```

### Métadonnées

```text
document_id
filename
document_type
source_url
file_hash
mime_type
file_size
created_at
scraped_at
ocr_status
```

---

# 11. Module 2 — OCR & Extraction

## Pipeline

```text
PDF / Image
     ↓
Document Analysis
     ↓
Text available?
     │
 ┌───┴────┐
 │        │
YES      NO
 │        │
 ▼        ▼
Extract  OCR
Text     │
 │       ▼
 └───→ Cleaning
          ↓
       Extraction
          ↓
       Entities
```

## Technologies

### Tesseract

Moteur OCR open source.

### OpenCV

Pour le prétraitement :

- grayscale ;
- thresholding ;
- noise removal ;
- deskew ;
- contrast enhancement ;
- resizing.

### PyMuPDF

Pour :

- lecture des PDF ;
- extraction de texte ;
- conversion des pages ;
- récupération des métadonnées.

### spaCy

Pour l'extraction d'entités.

### Regex

Pour les informations structurées.

---

# 12. Extraction des informations

Les informations seront classées en plusieurs catégories.

## Informations du marché

```text
reference
object
buyer
category
sector
procedure_type
location
publication_date
deadline
```

## Informations financières

```text
estimated_amount
awarded_amount
currency
lot_amount
```

## Entreprises

```text
company_name
ICE
RC
```

Uniquement lorsqu'elles sont publiquement disponibles.

## Documents

```text
document_type
source_url
document_date
```

---

# 13. Exemple de donnée extraite

Document :

```text
AVIS D'APPEL D'OFFRES

Référence : 12/2026
Objet : Acquisition de matériel informatique
Acheteur : Organisme X
Montant estimatif : 2 500 000 DH
Date : 12/05/2026
```

Résultat :

```json
{
  "reference": "12/2026",
  "object": "Acquisition de matériel informatique",
  "buyer": "Organisme X",
  "estimated_amount": 2500000,
  "currency": "MAD",
  "date": "2026-05-12"
}
```

---

# 14. Module 3 — Big Data

## Objectif

Transformer les données collectées en données analytiques.

```text
Raw Data
   ↓
Cleaning
   ↓
Normalization
   ↓
Transformation
   ↓
Aggregation
   ↓
Analytics
```

## Technologies

### PostgreSQL

Pour :

- métadonnées ;
- marchés ;
- entreprises ;
- utilisateurs ;
- anomalies ;
- logs.

### MinIO

Pour :

- PDF ;
- images ;
- documents OCR ;
- fichiers bruts.

### Parquet

Pour les datasets analytiques.

### PySpark

Pour :

- traitement distribué ;
- transformations ;
- agrégations ;
- statistiques ;
- préparation des données ML.

---

# 15. Pourquoi PySpark ?

Même si le volume du prototype est limité, PySpark permet de démontrer une architecture orientée Big Data.

Le projet peut fonctionner localement avec Spark.

L'objectif n'est pas de prétendre traiter plusieurs téraoctets pendant les 15 jours.

L'objectif est de construire une pipeline pouvant évoluer :

```text
Prototype
    ↓
Local PySpark
    ↓
Dataset plus important
    ↓
Spark Cluster
```

---

# 16. Module 4 — IA & valorisation

## Objectif

Analyser les marchés et identifier des signaux inhabituels.

Le système ne décide pas qu'une entreprise est frauduleuse.

Il fournit :

> **un score et des indicateurs de risque destinés à aider l'analyste humain.**

---

# 17. Analyse descriptive

Le dashboard permettra d'analyser :

### Marchés

- nombre de marchés ;
- montant total ;
- montant moyen ;
- évolution temporelle ;
- répartition par catégorie ;
- répartition par secteur.

### Organismes

- nombre de marchés ;
- montant total ;
- entreprises attributaires ;
- concentration.

### Entreprises

- nombre de marchés ;
- montant cumulé ;
- part de marché ;
- évolution dans le temps.

---

# 18. Détection d'anomalies

Plusieurs indicateurs seront combinés.

## 18.1 Montant atypique

Comparer le montant d'un marché avec des marchés similaires.

```text
Marché
  ↓
Même catégorie
  ↓
Même secteur
  ↓
Distribution des montants
  ↓
Valeur atypique ?
```

---

## 18.2 Concentration des marchés

Identifier une entreprise qui reçoit une part particulièrement élevée des marchés d'un organisme.

```text
Organisme X

Entreprise A → 10 marchés
Entreprise B → 2 marchés
Entreprise C → 1 marché
```

Cela peut générer un signal de concentration.

---

## 18.3 Fréquence

Analyser le nombre de marchés remportés par entreprise sur une période.

---

## 18.4 Variations inhabituelles

Analyser les variations importantes des montants ou fréquences.

---

# 19. Machine Learning

Un modèle simple d'**Isolation Forest** peut être utilisé pour détecter les observations atypiques.

### Features possibles

```text
amount
number_of_awards
total_amount
market_share
average_amount
amount_variation
frequency
```

Pipeline :

```text
Structured Data
      ↓
Feature Engineering
      ↓
Feature Matrix
      ↓
Isolation Forest
      ↓
Anomaly Score
      ↓
Risk Score
```

---

# 20. Risk Score

Le système produit un score indicatif entre 0 et 100.

Exemple :

```text
0 – 29     Faible
30 – 59    Modéré
60 – 79    Élevé
80 – 100   Critique
```

Ces seuils sont **définis pour le prototype** et ne représentent pas des seuils officiels de la DGI.

### Exemple de calcul

```text
Montant atypique       +25
Concentration élevée   +25
Fréquence élevée       +20
Autres anomalies       +10

Total                   80
```

Résultat :

```text
Risk Score = 80
Level = CRITICAL
```

---

# 21. Explicabilité

Le système ne doit pas afficher uniquement :

```text
Risk Score = 80
```

Il doit expliquer pourquoi.

Exemple :

```text
Risk Score : 80 / 100

Facteurs :

✓ Montant supérieur à la moyenne du groupe
✓ Forte concentration des marchés
✓ Nombre élevé de marchés remportés
```

L'objectif est d'avoir un système **explainable**.

---

# 22. Valorisation fiscale

## Problème

Le projet ne dispose pas des données internes de la DGI.

Il est donc impossible de réaliser une comparaison fiscale réelle avec les déclarations internes des entreprises.

## Solution

Créer un **référentiel fiscal synthétique** uniquement pour démontrer le fonctionnement de la chaîne.

Exemple :

```text
ICE
Company
Sector
Declared_Revenue
Declared_Tax
```

---

# 23. Exemple de croisement

```text
               MARCHÉS PUBLICS
                     │
                     ▼
             Entreprise A
                     │
            Total marchés
             15 000 000 MAD
                     │
                     │
                     ▼
          Référentiel synthétique
                     │
                     ▼
          CA déclaré simulé
             8 000 000 MAD
                     │
                     ▼
               Comparaison
                     │
                     ▼
             Signal d'écart
```

Ce résultat ne signifie pas :

> « L'entreprise est fraudeuse ».

Il signifie :

> « Un écart ou signal nécessitant une analyse supplémentaire a été détecté ».

---

# 24. Module 5 — Cybersécurité

La sécurité est intégrée dans l'ensemble de la plateforme.

```text
Utilisateur
     ↓
Authentication
     ↓
JWT
     ↓
RBAC
     ↓
FastAPI
     ↓
Database / Storage
     ↓
Audit Logs
```

---

# 25. Authentication

Technologies :

```text
FastAPI
JWT
bcrypt
```

Les mots de passe ne sont jamais stockés en clair.

```text
Password
   ↓
bcrypt
   ↓
Password Hash
   ↓
Database
```

---

# 26. RBAC

Trois rôles :

```text
ADMIN
ANALYST
VIEWER
```

| Action | ADMIN | ANALYST | VIEWER |
|---|---:|---:|---:|
| Consulter | ✓ | ✓ | ✓ |
| Rechercher | ✓ | ✓ | ✓ |
| Importer | ✓ | ✓ | ✗ |
| OCR | ✓ | ✓ | ✗ |
| Analyse | ✓ | ✓ | ✓ |
| Modifier | ✓ | ✓ | ✗ |
| Supprimer | ✓ | ✗ | ✗ |
| Logs | ✓ | ✗ | ✗ |
| Utilisateurs | ✓ | ✗ | ✗ |

---

# 27. API Security

L'API doit intégrer :

- JWT ;
- RBAC ;
- validation des entrées ;
- gestion des erreurs ;
- rate limiting ;
- CORS configuré ;
- HTTPS/TLS en environnement de déploiement ;
- protection contre les accès non autorisés.

---

# 28. Protection des documents

Les documents doivent être contrôlés lors de l'import.

Vérifications :

```text
File extension
MIME type
File size
File hash
Storage path
```

Exemple :

```text
PDF
 ↓
Validation
 ↓
Hash
 ↓
Malicious file checks
 ↓
Storage
```

---

# 29. Audit Logs

Les opérations importantes sont enregistrées.

Exemple :

```text
timestamp
user_id
role
action
resource
resource_id
status
ip_address
```

Exemple :

```text
2026-08-16 14:32:10

user       = analyst01
role       = ANALYST
action     = VIEW_DOCUMENT
resource   = DOCUMENT
resource_id = DOC-00124
status     = SUCCESS
```

---

# 30. Analyse de risques cybersécurité

| Risque | Niveau | Mesure |
|---|---|---|
| SQL Injection | Élevé | ORM + validation |
| Broken Access Control | Élevé | RBAC |
| Brute Force | Élevé | Rate limiting |
| Upload malveillant | Élevé | Validation fichiers |
| Vol de JWT | Élevé | HTTPS + expiration |
| Secrets exposés | Élevé | `.env` |
| Fuite de documents | Élevé | Access control |
| Modification non autorisée | Élevé | Authorization |
| Suppression non autorisée | Élevé | RBAC |
| Absence de traçabilité | Moyen | Audit logs |

---

# 31. Technologies utilisées

## Programming

```text
Python 3.11+
```

## Scraping

```text
Requests
BeautifulSoup
Scrapy
Playwright — uniquement si nécessaire
```

## PDF / Documents

```text
PyMuPDF
Pillow
```

## OCR

```text
Tesseract OCR
pytesseract
OpenCV
```

## NLP

```text
spaCy
Regex
```

## Data Engineering

```text
Pandas
NumPy
PySpark
Apache Parquet
```

## Database

```text
PostgreSQL
SQLAlchemy
```

## Object Storage

```text
MinIO
```

## Machine Learning

```text
Scikit-learn
Isolation Forest
```

## Backend

```text
FastAPI
Uvicorn
Pydantic
```

## Security

```text
JWT
bcrypt
RBAC
HTTPS/TLS
Audit Logs
```

## Dashboard

```text
Streamlit
Plotly
```

## DevOps

```text
Git
GitHub
Docker
Docker Compose
```

## Testing

```text
Pytest
```

---

# 32. Repository Structure

```text
public-procurement-ai/
│
├── README.md
├── LICENSE
├── .gitignore
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── pyproject.toml
│
├── docs/
│   ├── architecture.md
│   ├── data_dictionary.md
│   ├── methodology.md
│   ├── security.md
│   ├── risk_model.md
│   └── api.md
│
├── data/
│   │
│   ├── raw/
│   │   ├── html/
│   │   ├── pdf/
│   │   └── images/
│   │
│   ├── processed/
│   │   ├── ocr/
│   │   ├── cleaned/
│   │   └── extracted/
│   │
│   ├── synthetic/
│   │   └── fiscal_reference.csv
│   │
│   └── samples/
│       └── README.md
│
├── scraper/
│   │
│   ├── __init__.py
│   │
│   ├── pmmp/
│   │   ├── __init__.py
│   │   ├── client.py
│   │   ├── config.py
│   │   │
│   │   ├── spiders/
│   │   │   ├── consultations.py
│   │   │   ├── results.py
│   │   │   └── documents.py
│   │   │
│   │   ├── parsers/
│   │   │   ├── consultation_parser.py
│   │   │   ├── result_parser.py
│   │   │   └── document_parser.py
│   │   │
│   │   └── utils/
│   │       ├── downloader.py
│   │       ├── deduplication.py
│   │       ├── rate_limiter.py
│   │       └── logger.py
│   │
│   ├── pipelines/
│   │   ├── validation.py
│   │   ├── normalization.py
│   │   └── storage.py
│   │
│   └── tests/
│       └── test_pmmp.py
│
├── ocr/
│   ├── __init__.py
│   ├── pdf_to_image.py
│   ├── preprocess.py
│   ├── tesseract_engine.py
│   ├── text_cleaning.py
│   ├── quality_check.py
│   └── pipeline.py
│
├── extraction/
│   ├── __init__.py
│   ├── regex_patterns.py
│   ├── entity_extraction.py
│   ├── amount_extraction.py
│   ├── date_extraction.py
│   ├── company_extraction.py
│   ├── procurement_extraction.py
│   └── pipeline.py
│
├── bigdata/
│   ├── spark/
│   │   ├── cleaning.py
│   │   ├── transformations.py
│   │   ├── aggregations.py
│   │   └── jobs/
│   │       └── procurement_analysis.py
│   │
│   └── schemas/
│       └── procurement_schema.py
│
├── ai/
│   ├── preprocessing.py
│   ├── features.py
│   ├── anomaly_detection.py
│   ├── risk_score.py
│   ├── explanations.py
│   └── models/
│       └── isolation_forest.pkl
│
├── database/
│   ├── database.py
│   │
│   ├── models/
│   │   ├── user.py
│   │   ├── document.py
│   │   ├── procurement.py
│   │   ├── company.py
│   │   ├── award.py
│   │   ├── anomaly.py
│   │   └── audit_log.py
│   │
│   ├── schemas/
│   │   ├── user.py
│   │   ├── document.py
│   │   ├── procurement.py
│   │   └── anomaly.py
│   │
│   └── crud/
│       ├── documents.py
│       ├── procurements.py
│       ├── companies.py
│       └── anomalies.py
│
├── api/
│   ├── main.py
│   │
│   ├── routes/
│   │   ├── auth.py
│   │   ├── documents.py
│   │   ├── procurements.py
│   │   ├── companies.py
│   │   ├── analytics.py
│   │   ├── anomalies.py
│   │   └── users.py
│   │
│   ├── auth/
│   │   ├── jwt.py
│   │   ├── password.py
│   │   ├── dependencies.py
│   │   └── permissions.py
│   │
│   └── middleware/
│       ├── logging.py
│       └── security.py
│
├── dashboard/
│   ├── app.py
│   │
│   ├── pages/
│   │   ├── overview.py
│   │   ├── documents.py
│   │   ├── procurements.py
│   │   ├── companies.py
│   │   ├── anomalies.py
│   │   └── audit.py
│   │
│   ├── components/
│   └── utils/
│
├── scripts/
│   ├── scrape.py
│   ├── run_ocr.py
│   ├── run_extraction.py
│   ├── run_spark.py
│   ├── train_model.py
│   └── seed_database.py
│
├── tests/
│   ├── test_scraper.py
│   ├── test_ocr.py
│   ├── test_extraction.py
│   ├── test_bigdata.py
│   ├── test_ai.py
│   ├── test_auth.py
│   └── test_api.py
│
└── notebooks/
    ├── 01_data_exploration.ipynb
    ├── 02_ocr_evaluation.ipynb
    ├── 03_extraction_evaluation.ipynb
    └── 04_anomaly_analysis.ipynb
```

---

# 33. Data Model

## Document

```text
Document
--------
id
source_url
filename
document_type
file_hash
mime_type
file_size
storage_path
ocr_status
scraped_at
created_at
```

## Procurement

```text
Procurement
-----------
id
reference
object
buyer
category
sector
procedure_type
publication_date
deadline
location
estimated_amount
source_url
document_id
```

## Company

```text
Company
-------
id
name
ice
registration_number
sector
```

## Award

```text
Award
-----
id
procurement_id
company_id
amount
award_date
```

## Extracted Entity

```text
ExtractedEntity
---------------
id
document_id
entity_type
entity_value
confidence
page_number
```

## Anomaly

```text
Anomaly
-------
id
procurement_id
company_id
anomaly_type
score
severity
explanation
created_at
```

## User

```text
User
----
id
username
password_hash
role
is_active
created_at
```

## Audit Log

```text
AuditLog
--------
id
user_id
action
resource
resource_id
ip_address
status
timestamp
```

---

# 34. Database Relations

```text
                    ┌──────────────┐
                    │  DOCUMENT    │
                    └──────┬───────┘
                           │
                           │
                    ┌──────▼───────┐
                    │ PROCUREMENT  │
                    └──────┬───────┘
                           │
                  ┌────────┴────────┐
                  │                 │
                  ▼                 ▼
             ┌─────────┐       ┌─────────┐
             │ COMPANY │       │  AWARD  │
             └─────────┘       └─────────┘
                  │
                  │
                  ▼
             ┌───────────┐
             │ ANOMALIES │
             └───────────┘
```

---

# 35. API Architecture

## Authentication

```http
POST /auth/login
POST /auth/refresh
GET  /auth/me
```

## Documents

```http
GET    /documents
GET    /documents/{id}
POST   /documents
DELETE /documents/{id}
POST   /documents/{id}/ocr
```

## Procurement

```http
GET /procurements
GET /procurements/{id}
GET /procurements/search
```

## Companies

```http
GET /companies
GET /companies/{id}
GET /companies/{id}/procurements
```

## Analytics

```http
GET /analytics/overview
GET /analytics/companies
GET /analytics/categories
GET /analytics/amounts
```

## Anomalies

```http
GET /anomalies
GET /anomalies/{id}
GET /anomalies/high-risk
```

## Audit

```http
GET /audit/logs
```

---

# 36. Dashboard

Le dashboard sera développé avec Streamlit et Plotly.

## Page 1 — Overview

Afficher :

```text
Total marchés
Total entreprises
Montant total
Documents collectés
Documents OCR
Anomalies détectées
Risques élevés
```

---

## Page 2 — Marchés

Filtres :

```text
Référence
Entreprise
Organisme
Secteur
Catégorie
Date
Montant
Région
```

---

## Page 3 — Documents

Afficher :

```text
Document
Type
Source
Date
OCR status
```

Possibilité de consulter :

```text
PDF
↓
Texte OCR
↓
Informations extraites
```

---

## Page 4 — Entreprises

Afficher :

```text
Entreprise
Nombre de marchés
Montant total
Part de marché
Montant moyen
Risk Score
```

---

## Page 5 — Anomalies

Afficher :

```text
Marché
Entreprise
Type d'anomalie
Score
Sévérité
Explication
```

---

## Page 6 — Audit

Accessible uniquement à l'administrateur.

Afficher :

```text
Utilisateur
Action
Ressource
Date
IP
Status
```

---

# 37. Exemple de scénario utilisateur

```text
Utilisateur
     ↓
Login
     ↓
JWT
     ↓
Dashboard
     ↓
Recherche "matériel informatique"
     ↓
Liste des marchés
     ↓
Sélection d'un marché
     ↓
Document
     ↓
OCR
     ↓
Texte extrait
     ↓
Informations structurées
     ↓
Entreprise
     ↓
Statistiques
     ↓
Anomalies
     ↓
Risk Score
     ↓
Explication
     ↓
Audit Log
```

---

# 38. Pipeline complète

Le pipeline principal du projet est :

```text
                    PMMP
                     │
                     ▼
                 SCRAPING
                     │
                     ▼
               RAW DOCUMENTS
                     │
                     ▼
              DOCUMENT STORAGE
                     │
                     ▼
                   OCR
                     │
                     ▼
              TEXT CLEANING
                     │
                     ▼
           INFORMATION EXTRACTION
                     │
                     ▼
             DATA VALIDATION
                     │
                     ▼
             POSTGRESQL / PARQUET
                     │
                     ▼
                 PYSPARK
                     │
                     ▼
             FEATURE ENGINEERING
                     │
                     ▼
             ANOMALY DETECTION
                     │
                     ▼
                 RISK SCORE
                     │
                     ▼
                  FASTAPI
                     │
                     ▼
                STREAMLIT
                     │
                     ▼
                ANALYST
```

---

# 39. Git Workflow

Le projet sera développé avec Git.

## Branches

```text
main
develop

feature/scraping
feature/ocr
feature/extraction
feature/bigdata
feature/ai
feature/security
feature/dashboard
```

Même si nous travaillons en binôme sur toutes les étapes, les branches servent à éviter de casser le projet principal.

---

# 40. Convention des commits

Utiliser des commits explicites :

```text
feat: add PMMP scraper
feat: add document downloader
feat: implement OCR pipeline
feat: add company extraction
data: add procurement schema
feat: implement PySpark processing
feat: add anomaly detection
security: implement JWT authentication
security: add RBAC
feat: add Streamlit dashboard
test: add OCR tests
fix: handle invalid PDF
docs: update architecture
```

---

# 41. Configuration

Créer :

```text
.env
```

Ne jamais mettre `.env` dans GitHub.

Créer :

```text
.env.example
```

Exemple :

```env
DATABASE_URL=postgresql://user:password@postgres:5432/procurement_db

JWT_SECRET_KEY=change_me
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30

MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=change_me
MINIO_BUCKET=documents

OCR_LANGUAGE=fra

MAX_FILE_SIZE_MB=20
```

---

# 42. Docker

Architecture :

```text
Docker Compose
      │
      ├── FastAPI
      │
      ├── Streamlit
      │
      ├── PostgreSQL
      │
      ├── MinIO
      │
      └── Spark
```

L'objectif est de permettre à chaque membre du binôme de lancer le même environnement.

---

# 43. Installation

## Clone

```bash
git clone https://github.com/USERNAME/public-procurement-ai.git

cd public-procurement-ai
```

## Environnement virtuel

Windows :

```bash
python -m venv .venv
.venv\Scripts\activate
```

Linux/macOS :

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

```bash
copy .env.example .env
```

ou Linux/macOS :

```bash
cp .env.example .env
```

---

# 44. Docker

```bash
docker compose up --build
```

Services :

```text
FastAPI
http://localhost:8000

Swagger
http://localhost:8000/docs

Streamlit
http://localhost:8501

MinIO
http://localhost:9001
```

---

# 45. Exécution de la pipeline

## 1. Scraping

```bash
python scripts/scrape.py
```

## 2. OCR

```bash
python scripts/run_ocr.py
```

## 3. Extraction

```bash
python scripts/run_extraction.py
```

## 4. Big Data

```bash
python scripts/run_spark.py
```

## 5. Machine Learning

```bash
python scripts/train_model.py
```

## 6. API

```bash
uvicorn api.main:app --reload
```

## 7. Dashboard

```bash
streamlit run dashboard/app.py
```

---

# 46. Tests

Lancer :

```bash
pytest
```

Tests prévus :

```text
Scraper
OCR
Extraction
Database
PySpark
Machine Learning
Authentication
RBAC
API
```

---

# 47. Évaluation

## OCR

Mesures possibles :

```text
Character Error Rate
Word Error Rate
```

## Extraction

```text
Precision
Recall
F1-score
```

## Anomaly Detection

```text
Precision
Recall
F1-score
```

Les performances doivent être évaluées sur un petit jeu de documents annotés manuellement.

---

# 48. Dataset de validation

Avant de lancer un scraping massif, créer un petit dataset de référence :

```text
data/samples/
```

Exemple :

```text
10–20 documents
```

Pour chaque document :

```text
Expected Reference
Expected Company
Expected Amount
Expected Date
Expected Buyer
```

Cela permettra de mesurer la qualité de l'OCR et de l'extraction.

---

# 49. Stratégie de développement

Le projet sera développé progressivement.

## Étape 1 — Prototype minimal

Faire fonctionner :

```text
1 page PMMP
     ↓
1 marché
     ↓
1 document
     ↓
OCR
     ↓
Extraction
     ↓
Database
```

## Étape 2

Passer à :

```text
10 documents
```

## Étape 3

Passer à :

```text
50–100+ documents
```

## Étape 4

Ajouter :

```text
PySpark
Anomaly Detection
Dashboard
Security
```

Cette stratégie évite de perdre plusieurs jours à construire une infrastructure avant d'avoir une pipeline fonctionnelle.

---

# 50. Planning — 15 jours

## Jour 1

```text
Architecture
GitHub
Environment
PMMP analysis
Database design
```

## Jour 2

```text
Scraper prototype
PMMP parser
Data model
```

## Jour 3

```text
Scraping
Metadata extraction
Document URLs
```

## Jour 4

```text
Document downloader
Deduplication
Storage
```

## Jour 5

```text
OCR
PDF processing
OpenCV preprocessing
```

## Jour 6

```text
OCR improvement
Text cleaning
OCR evaluation
```

## Jour 7

```text
Information extraction
Regex
Dates
Amounts
References
```

## Jour 8

```text
NER
Companies
Organizations
Locations
PostgreSQL integration
```

## Jour 9

```text
PySpark
Cleaning
Transformation
Parquet
```

## Jour 10

```text
Statistics
Aggregations
Company analysis
Market analysis
```

## Jour 11

```text
Feature engineering
Anomaly detection
Isolation Forest
```

## Jour 12

```text
Risk Score
Explanations
Synthetic fiscal reference
```

## Jour 13

```text
FastAPI
JWT
RBAC
Audit logs
```

## Jour 14

```text
Streamlit
Plotly
Dashboard
Full integration
```

## Jour 15

```text
Testing
Bug fixing
Documentation
Demo
Presentation
```

---

# 51. MVP

## Obligatoire

- [x] PMMP scraper
- [x] Document downloader
- [x] Document storage
- [x] OCR
- [x] Text cleaning
- [x] Information extraction
- [x] PostgreSQL
- [x] PySpark
- [x] Statistical analysis
- [x] Anomaly detection
- [x] Risk Score
- [x] FastAPI
- [x] JWT
- [x] RBAC
- [x] Audit logs
- [x] Streamlit dashboard

---

# 52. Fonctionnalités bonus

Uniquement si le MVP est terminé :

- [ ] Classification automatique des documents
- [ ] NER avancé
- [ ] Recherche sémantique
- [ ] OCR spécialisé
- [ ] Elasticsearch
- [ ] Modèle NLP avancé
- [ ] CI/CD
- [ ] Monitoring
- [ ] Docker production
- [ ] Recherche full-text avancée

Ces fonctionnalités ne doivent pas compromettre le MVP.

---

# 53. Limitations

Le projet présente plusieurs limites.

### Données fiscales

Les données fiscales internes de la DGI ne sont pas accessibles.

Le référentiel fiscal utilisé pour la démonstration peut donc être synthétique.

### Volume

Le volume collecté pendant les 15 jours est limité.

### OCR

La qualité dépend fortement de la qualité des documents.

### Extraction

Les documents administratifs peuvent avoir des structures différentes.

### IA

Un modèle d'anomaly detection identifie des observations atypiques mais ne prouve pas une fraude.

### Risque fiscal

Les indicateurs proposés sont des outils d'aide à l'analyse et ne constituent pas des règles fiscales officielles.

---

# 54. Human-in-the-loop

Le système suit le principe :

```text
Data
 ↓
AI
 ↓
Signal
 ↓
Explanation
 ↓
Human Analyst
 ↓
Decision
```

L'IA ne prend pas seule une décision fiscale.

Elle fournit des éléments permettant à l'analyste d'effectuer une investigation plus approfondie.

---

# 55. Data Provenance

Chaque information doit rester traçable jusqu'à sa source.

Exemple :

```text
Risk Score
    ↓
Anomaly
    ↓
Company
    ↓
Procurement
    ↓
Extracted Data
    ↓
OCR
    ↓
Document
    ↓
Source URL
    ↓
PMMP
```

C'est essentiel pour la fiabilité du système.

---

# 56. Architecture de sécurité

```text
                       USER
                         │
                         ▼
                    HTTPS/TLS
                         │
                         ▼
                  AUTHENTICATION
                         │
                         ▼
                       JWT
                         │
                         ▼
                       RBAC
                         │
                         ▼
                     FASTAPI
                         │
                ┌────────┴────────┐
                ▼                 ▼
           PostgreSQL            MinIO
                │                 │
                └────────┬────────┘
                         ▼
                    AUDIT LOGS
```

---

# 57. Architecture Big Data

```text
                  PMMP
                   │
                   ▼
                Scraper
                   │
                   ▼
                Raw Data
                   │
          ┌────────┴────────┐
          ▼                 ▼
      Documents          Metadata
          │                 │
          ▼                 ▼
        MinIO           PostgreSQL
          │                 │
          └────────┬────────┘
                   ▼
               PySpark
                   │
                   ▼
             Data Cleaning
                   │
                   ▼
             Transformation
                   │
                   ▼
              Aggregation
                   │
                   ▼
                Parquet
                   │
                   ▼
             ML / Analytics
```

---

# 58. Architecture IA

```text
Structured Data
      │
      ▼
Feature Engineering
      │
      ├── Amount
      ├── Frequency
      ├── Concentration
      ├── Market Share
      └── Historical Behavior
      │
      ▼
Isolation Forest
      │
      ▼
Anomaly Score
      │
      ▼
Risk Engine
      │
      ▼
Risk Score 0–100
      │
      ▼
Explanation
```

---

# 59. Résultat attendu

À la fin des 15 jours, l'utilisateur doit pouvoir :

```text
1. Se connecter
       ↓
2. Ouvrir le dashboard
       ↓
3. Rechercher un marché
       ↓
4. Consulter ses informations
       ↓
5. Ouvrir le document source
       ↓
6. Voir le texte OCR
       ↓
7. Voir les informations extraites
       ↓
8. Consulter l'entreprise
       ↓
9. Consulter les statistiques
       ↓
10. Voir les anomalies
       ↓
11. Voir le Risk Score
       ↓
12. Voir pourquoi le score a été attribué
       ↓
13. L'action est enregistrée dans les logs
```

---

# 60. Démonstration finale

La démonstration sera basée sur un cas réel provenant d'une source publique.

### Exemple

```text
PMMP
 ↓
Marché public
 ↓
Document PDF
 ↓
OCR
 ↓
Extraction
```

Le système extrait :

```text
Référence
Objet
Organisme
Entreprise
Montant
Date
Catégorie
```

Puis :

```text
PostgreSQL
 ↓
PySpark
 ↓
Analyse
 ↓
Anomaly Detection
 ↓
Risk Score
```

Dashboard :

```text
┌─────────────────────────────────────────────┐
│           PROCUREMENT ANALYTICS             │
├─────────────┬─────────────┬─────────────────┤
│ 1,250       │ 320         │ 45              │
│ Marchés     │ Entreprises │ Anomalies       │
├─────────────┴─────────────┴─────────────────┤
│                                             │
│      Evolution des montants                 │
│                                             │
├─────────────────────────────────────────────┤
│ Entreprise X                                │
│                                             │
│ Marchés : 32                                │
│ Montant : 15.2M MAD                        │
│ Risk Score : 78/100                         │
│                                             │
│ ⚠ Montant atypique                          │
│ ⚠ Concentration élevée                      │
│ ⚠ Fréquence élevée                          │
└─────────────────────────────────────────────┘
```

---

# 61. Architecture future

Le prototype peut évoluer vers une architecture industrielle.

```text
                    DATA SOURCES
                         │
                         ▼
                    DATA INGESTION
                         │
                         ▼
                      KAFKA
                         │
                         ▼
                    DATA LAKE
                         │
                         ▼
                DISTRIBUTED SPARK
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
         DATA WAREHOUSE          ML PLATFORM
              │                     │
              └──────────┬──────────┘
                         ▼
                    SECURE API
                         │
                         ▼
                     DASHBOARD
```

Cette architecture est une évolution future et n'est pas nécessaire pour le prototype de 15 jours.

---

# 62. Principes du projet

## 1. Data Provenance

Chaque donnée doit être reliée à sa source.

## 2. Explainability

Chaque anomalie doit être accompagnée d'une explication.

## 3. Security by Design

La sécurité est intégrée dès la conception.

## 4. Scalability

La pipeline doit pouvoir évoluer vers un volume plus important.

## 5. Human in the Loop

L'IA assiste l'analyste mais ne remplace pas la décision humaine.

## 6. Reproducibility

Le projet doit pouvoir être installé et exécuté dans un environnement contrôlé.

---

# 63. Résumé de l'architecture technologique

| Couche | Technologie |
|---|---|
| Source | PMMP |
| Scraping | Requests / BeautifulSoup / Scrapy |
| Dynamic scraping | Playwright si nécessaire |
| Language | Python |
| PDF | PyMuPDF |
| OCR | Tesseract |
| Image processing | OpenCV |
| NLP | spaCy |
| Extraction | Regex + NLP |
| Database | PostgreSQL |
| Object Storage | MinIO |
| Data Processing | Pandas + PySpark |
| Data Format | Parquet |
| Machine Learning | Scikit-learn |
| Anomaly Detection | Isolation Forest |
| Backend | FastAPI |
| Authentication | JWT |
| Authorization | RBAC |
| Password Security | bcrypt |
| Logs | Python logging + Audit DB |
| Dashboard | Streamlit |
| Visualization | Plotly |
| Containerization | Docker |
| Orchestration locale | Docker Compose |
| Version Control | Git / GitHub |
| Testing | Pytest |

---

# 64. Conclusion

Ce projet propose un prototype complet d'exploitation intelligente des marchés publics marocains.

La chaîne développée permet de passer de :

```text
DONNÉES PUBLIQUES
       ↓
SCRAPING
       ↓
DOCUMENTS
       ↓
OCR
       ↓
NLP / EXTRACTION
       ↓
BIG DATA
       ↓
ANALYSE
       ↓
IA
       ↓
ANOMALIES
       ↓
INDICATEURS DE RISQUE
       ↓
API SÉCURISÉE
       ↓
DASHBOARD
```

Le projet démontre l'intégration de :

**Big Data + IA + OCR + NLP + Data Engineering + Cybersécurité.**

Il constitue un **prototype d'aide à l'analyse des risques**, et non un système officiel de détection ou de qualification de fraude fiscale.

L'absence d'accès aux données internes de la DGI est prise en compte dans l'architecture : les données publiques du PMMP sont utilisées pour les marchés publics et un référentiel fiscal synthétique peut être utilisé uniquement pour démontrer le mécanisme de croisement fiscal.

La plateforme est conçue pour être évolutive vers une architecture plus importante lorsque des volumes de données et des sources supplémentaires seront disponibles.

---

## Source de données principale

[Portail Marocain des Marchés Publics](https://www.marchespublics.gov.ma/?utm_source=chatgpt.com)

## Documentation OCR

[Tesseract OCR Documentation](https://tesseract-ocr.github.io/tessdoc/?utm_source=chatgpt.com)

---

**Projet : Exploitation des marchés publics — Chaîne Big Data, IA d'océrisation et valorisation fiscale**

**Type : Prototype académique**

**Durée : 15 jours**

**Équipe : 2 étudiantes — IA & Big Data**