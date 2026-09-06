# Backlog — Issues GitHub

> Découpage du planning (README §50) en tâches concrètes, basées sur les champs et sources confirmés dans [`data_dictionary.md`](data_dictionary.md).
> À créer manuellement dans l'onglet **Issues** du repo (pas de `gh` CLI installé) — copier titre + description pour chaque issue ci-dessous.

---

## Issue 1 — Architecture, environnement, modèle de données ✅ (déjà fait)
**Statut** : essentiellement terminé pendant l'exploration (repo, workflow Git, `docker-compose.yml`, `requirements.txt`, `data_dictionary.md`). Créer l'issue quand même pour la traçabilité, et la fermer directement en la liant aux commits déjà faits.

---

## Issue 2 — Spider Consultations
**Labels** : `feature/scraping`, `module-1`
**Description** : Développer le spider qui collecte les métadonnées des consultations (recherche + page de détail), en HTML, sans OCR.
**Critères de "done"** :
- [ ] Récupère `reference`, `objet`, `acheteur_public`, `mode_passation`, `categorie_principale`, `lieu_execution`, `estimation_dhs_ttc`, `date_mise_ligne`, `date_limite_remise_plis`
- [ ] Utilise `requests.Session()` pour gérer les cookies
- [ ] Respecte un rate limit configurable (`.env` : `SCRAPER_RATE_LIMIT_SECONDS`)
- [ ] Gère la pagination des résultats
- [ ] Ne tente jamais de remplir le formulaire d'identification pour le téléchargement de dossier (marque `is_publicly_downloadable=False` si bloqué)
- [ ] Teste sur au moins 20 consultations réelles sans erreur

---

## Issue 3 — Spider Résultats définitifs / PV
**Labels** : `feature/scraping`, `module-1`
**Description** : Développer le(s) spider(s) qui collectent les documents d'attribution (PV en priorité, Résultats définitifs en secours), joints par `reference`.
**Critères de "done"** :
- [ ] Télécharge les PDF depuis "Tous les extraits de PV" et "Tous les résultats définitifs"
- [ ] Associe chaque document à sa `reference` de consultation
- [ ] Gère les cas multi-lots (un document, plusieurs lots)
- [ ] Journalise les téléchargements (URL source, hash, date)
- [ ] Teste sur au moins 20 documents réels sans erreur

---

## Issue 4 — Stockage documentaire et déduplication
**Labels** : `module-1`
**Description** : Stocker les documents téléchargés dans MinIO, calculer les hashes, éviter les doublons, enregistrer les métadonnées en base.
**Critères de "done"** :
- [ ] Upload automatique vers MinIO (`storage_path` retourné et enregistré)
- [ ] `file_hash` calculé et vérifié avant re-téléchargement (déduplication)
- [ ] Métadonnées `Document` enregistrées en PostgreSQL (voir modèle `data_dictionary.md` §4)
- [ ] Classification basique par `document_type` (CONSULTATION / PV / RESULTAT_DEFINITIF / RAPPORT / AUTRE)

---

## Issue 5 — Pipeline OCR
**Labels** : `module-2`
**Description** : Pipeline PDF→image→OCR, avec détection automatique "texte natif vs scanné" (voir `data_dictionary.md` §4).
**Critères de "done"** :
- [ ] Tente l'extraction native (PyMuPDF) en premier
- [ ] Fallback OCR (Tesseract, `OCR_LANGUAGE=fra`) si texte natif vide/illisible
- [ ] Prétraitement OpenCV (grayscale, deskew, contraste) pour les scans (ex: fichiers CamScanner)
- [ ] Marque `ocr_status` sur chaque document
- [ ] Testé sur au moins 1 exemple natif ET 1 exemple scanné réel de `data/samples/`

---

## Issue 6 — Nettoyage de texte et évaluation OCR
**Labels** : `module-2`
**Description** : Nettoyer le texte extrait (isoler/ignorer les en-têtes bilingues arabe/français), évaluer la qualité OCR sur l'échantillon de validation.
**Critères de "done"** :
- [ ] `text_cleaning.py` supprime le bruit d'en-tête (logos, texte arabe mal encodé)
- [ ] Calcul d'un taux d'erreur approximatif (comparaison avec les valeurs attendues notées dans `data/samples/`)

---

## Issue 7 — Extraction d'informations (regex)
**Labels** : `module-2`
**Description** : Extraire les champs structurés du texte nettoyé : référence, dates, montants, concurrent retenu.
**Critères de "done"** :
- [ ] Regex robustes aux variantes de libellés confirmées (`data_dictionary.md` §3.4 : "Montant MAX", texte libre, etc.)
- [ ] Extrait `concurrent_retenu` explicitement (jamais déduit par calcul de minimum)
- [ ] Gère les 3 statuts d'attribution (`ATTRIBUE` / `INFRUCTUEUX` / `OFFRE_EXCESSIVE`)
- [ ] Gère les groupements (plusieurs entreprises pour un seul `concurrent_retenu`)
- [ ] Testé et validé contre `data/samples/` (référence, montant, entreprise corrects sur au moins 80% des échantillons)

---

## Issue 8 — NER entreprises/organismes + intégration PostgreSQL
**Labels** : `module-2`
**Description** : Extraction d'entités nommées (spaCy) pour compléter la regex, puis intégration des données structurées en base.
**Critères de "done"** :
- [ ] Modèles SQLAlchemy créés (`Procurement`, `Award`, `Company`, `Document` — voir `data_dictionary.md`)
- [ ] Script d'insertion depuis les données extraites
- [ ] Normalisation basique des noms d'entreprise (casse, préfixes/suffixes)

---

## Issue 9 — PySpark : nettoyage, transformation, Parquet
**Labels** : `module-3`
**Description** : Pipeline PySpark local pour transformer les données PostgreSQL en dataset analytique Parquet.
**Critères de "done"** :
- [ ] Lecture depuis PostgreSQL, écriture Parquet dans `data/processed/`
- [ ] Nettoyage/normalisation (montants, dates, noms d'entreprise)

---

## Issue 10 — Statistiques et agrégations
**Labels** : `module-3`
**Description** : Calculer les statistiques par entreprise/marché/organisme.
**Critères de "done"** :
- [ ] `number_of_awards`, `total_amount`, `average_amount`, `market_share` par entreprise
- [ ] `number_of_bidders` par marché (depuis les PV, voir `data_dictionary.md` §3.2)

---

## Issue 11 — Feature engineering + détection d'anomalies
**Labels** : `module-4`
**Description** : Construire la matrice de features et entraîner Isolation Forest.
**Critères de "done"** :
- [ ] Features : `amount`, `number_of_awards`, `total_amount`, `market_share`, `amount_variation`, `frequency`, `number_of_bidders`
- [ ] Modèle Isolation Forest entraîné et sauvegardé (`ai/models/`)

---

## Issue 12 — Risk score, explications, référentiel fiscal synthétique
**Labels** : `module-4`
**Description** : Calculer un score de risque explicable (0-100) et créer le référentiel fiscal synthétique.
**Critères de "done"** :
- [ ] Score 0-100 avec seuils (Faible/Modéré/Élevé/Critique, README §20)
- [ ] Chaque anomalie a une explication textuelle (facteurs contributifs)
- [ ] `data/synthetic/fiscal_reference.csv` créé et documenté comme synthétique (pas des vraies données DGI)

---

## Issue 13 — API sécurisée (FastAPI, JWT, RBAC, audit logs)
**Labels** : `module-5`
**Description** : Construire l'API REST avec authentification et autorisation.
**Critères de "done"** :
- [ ] JWT + bcrypt pour l'authentification
- [ ] RBAC à 3 rôles (ADMIN/ANALYST/VIEWER) selon la matrice README §26
- [ ] Audit logs sur les actions sensibles
- [ ] Endpoints de base fonctionnels (`/auth`, `/documents`, `/procurements`, `/companies`, `/analytics`, `/anomalies`)

---

## Issue 14 — Dashboard Streamlit
**Labels** : `module-5`
**Description** : Construire le dashboard interactif (6 pages, README §36).
**Critères de "done"** :
- [ ] Pages Overview, Marchés, Documents, Entreprises, Anomalies, Audit (admin uniquement)
- [ ] Connecté à l'API, pas directement à la base

---

## Issue 15 — Tests, corrections, documentation, démo finale
**Labels** : `final`
**Description** : Stabilisation avant la présentation.
**Critères de "done"** :
- [ ] Suite de tests `pytest` passe sur les modules critiques
- [ ] `docs/methodology.md` et `docs/architecture.md` rédigés
- [ ] Scénario de démo préparé (README §37, §60)
