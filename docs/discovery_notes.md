# Discovery Notes — État d'avancement

> Document de suivi : ce qu'on a fait, ce qu'on a trouvé, ce qu'il reste à faire.
> À mettre à jour au fur et à mesure — sert de référence commune pour l'équipe.

Dernière mise à jour : 17/08/2026

---

## 1. Ce qu'on a fait jusqu'à présent

### 1.1 Mise en place du dépôt
- Connexion du dossier local au dépôt GitHub (`kdeeey/public-procurement-intelligence`).
- Mise en place du workflow Git : `main` (stable) → `develop` (intégration) → `feature/*` (par module), fusion via Pull Request.
- Rédaction de [`CONTRIBUTING.md`](../CONTRIBUTING.md) expliquant ce workflow pour l'équipe.

### 1.2 Phase 1 — Exploration manuelle du site PMMP réel
Objectif : vérifier les hypothèses du README (§6, §12) contre la structure réelle du site avant d'écrire le scraper.

Pages explorées :
- Page d'accueil (`marchespublics.gov.ma/pmmp/`)
- Recherche avancée / Consultations en cours
- Page de détail d'une consultation
- Recherche avancée "Annonces" (tous types d'annonces confondus)
- Documents "Résultats définitifs" (PDF, identifiés via l'icône ruban rouge)
- "Listes des marchés attribués" (dépôt de fichiers par acheteur)
- "Annonce de synthèse de rapport d'audit" (dépôt de rapports PDF)

### 1.3 Phase 2 — Vérification légale / conditions de scraping
- Vérifié `robots.txt` → n'existe pas (redirection vers l'accueil).
- Vérifié "Conditions d'utilisation" → uniquement des prérequis techniques pour répondre aux appels d'offres, pas une politique de réutilisation des données.
- Vérifié "Mentions légales" → lien trouvé mais non fonctionnel (cassé).

---

## 2. Ce qu'on a trouvé (résultats concrets)

### 2.1 Architecture technique du site
- Site en PHP orienté session (`index.php?page=...`), pas de HTML statique simple. Le scraper devra utiliser `requests.Session()` pour conserver les cookies.
- Accès public confirmé sans authentification pour les consultations ouvertes ("Vous n'êtes pas authentifié" visible en naviguant).
- Les procédures restreintes nécessitent un code d'accès (Acheteur + Référence + Code d'accès) → hors périmètre, non public.

### 2.2 Deux sources de données confirmées (remplace l'hypothèse unique du README)

**Source 1 — Consultations (recherche/listing + page de détail)**
Donne les métadonnées structurées du marché, directement en HTML, sans OCR :
```text
reference
objet
acheteur_public (maître d'ouvrage)
categorie
mode_passation (type de procédure)
lieu_execution
date_publication
date_limite_remise_plis
dossier_consultation_url (bundle ZIP/RAR, pas des fichiers séparés)
```

**Source 2 — Documents "Résultats définitifs" (icône ruban rouge)**
Donne les données d'attribution, liées à la même `reference` :
```text
maitre_d_ouvrage
objet_de_l_appel_d_offres
date_ouverture_plis
date_achevement_travaux_commission
concurrent_retenu       (nom de l'entreprise gagnante, ou "INFRUCTUEUX" si aucun gagnant)
montant_de_l_offre_retenue  (présent uniquement si un gagnant existe)
```
Confirmé avec 2 exemples réels : un cas `INFRUCTUEUX` (sans montant) et un cas avec gagnant (`La Société GT-RIF SARL`, `758 640,00 DH TTC`).

### 2.3 Source écartée comme source principale
**"Listes des marchés attribués"** — dépôt de fichiers non structuré, uploadé manuellement par chaque acheteur : noms de fichiers incohérents, décisions d'annulation mélangées avec des listes réelles, fichiers scannés (CamScanner), certains en arabe. Gardée uniquement comme source secondaire/bonus.

### 2.4 Champ ICE / RC — non disponibles publiquement
Vérifié sur les documents "Résultats définitifs" : seul le nom de l'entreprise apparaît (`concurrent_retenu`), jamais l'ICE ni le RC. Confirme l'hypothèse conditionnelle du README (§4.4 : "ICE lorsqu'il est présent publiquement").

**Conséquence pour le modèle de données** : la table `Company` doit traiter `ICE` et `RC` comme nullable/optionnels, probablement toujours vides depuis le PMMP. Le regroupement par entreprise se fera par `company_name`, ce qui implique un besoin de normalisation de nom (ex: "La Société GT-RIF SARL" vs "GT-RIF SARL") avant les agrégations statistiques.

### 2.5 Volumétrie réelle
- 3 587 consultations en cours (recherche non filtrée)
- 134 839 annonces au total (tous types, historique complet)
- Confirme la nécessité de filtrer par plage de date pour le prototype de 15 jours, comme prévu au README §6.

### 2.6 Risque identifié — variabilité des formats
Les PDF de résultats sont générés par chaque acheteur individuellement → mise en page probablement différente d'un acheteur à l'autre. L'extraction (regex/NLP) doit être conçue pour être flexible, pas câblée sur un seul format. Confirme le risque déjà noté au README §53.

### 2.7 Liste complète des types de procédure (`mode_passation`)
Récupérée depuis le formulaire de recherche avancée — bien plus riche que prévu :
```text
Appel d'offres ouvert / avec présélection (Phase 1/2)
Concours Architectural / Phase 1
Consultation architecturale (négociée, ouverte, restreinte — plusieurs variantes)
Demande de Cotation Ouverte / Restreinte (Banques Multilatérales de Développement)
Dialogue compétitif (Phase 1/2/3)
Enchère électronique inversée
Marché négocié avec/sans publicité préalable (Phase 1/2)
...
```

### 2.8 Formulaire d'identification requis pour certains téléchargements de dossier

Découverte importante lors de la collecte manuelle des échantillons (phase 3) : pour certaines consultations, cliquer sur "Dossier de consultation" ne télécharge pas directement le fichier — il redirige vers un **formulaire de demande d'identification** (`EntrepriseDemandeTelechargementDce`) demandant :

```text
Nom, Prénom, Adresse électronique, Raison sociale
ICE (auto-déclaré par le demandeur, pas une donnée publiée par le site)
Adresse, Ville, Téléphone, Fax
+ case à cocher : acceptation des conditions générales de la plateforme
```

Raison affichée par le site : pouvoir recontacter le demandeur en cas de modification de la consultation.

**Constat important** : contrairement aux premiers exemples de consultations vus (64/2026/DRPE, 29/AOO/AASLM/2026) où "Dossier de consultation" était un lien de téléchargement direct sans formulaire, certaines consultations imposent ce formulaire — probablement liées aux consultations à "réponse électronique obligatoire" (à confirmer). Le champ ICE vu ici confirme par ailleurs qu'il s'agit d'une donnée auto-déclarée par le demandeur, jamais une donnée publiée par le site — cohérent avec le constat §2.4.

**Décision (voir §4)** : le scraper ne doit pas remplir ce formulaire automatiquement (identité fictive + acceptation de conditions non lues = contournement problématique, similaire à un contournement d'authentification). Pour les consultations concernées, on collecte uniquement les métadonnées disponibles sans formulaire (référence, objet, acheteur, dates) et on marque le dossier comme non téléchargeable publiquement.

### 2.9 Extraits de PV — source potentiellement plus riche que "Résultats définitifs"

Découverte majeure : les documents **"Extrait de procès-verbal"** (icône grise "pv", menu "Tous les extraits de PV") sont beaucoup plus riches que les PDF "Résultats définitifs". Confirmé avec un exemple réel (`05/2026/SR NADOR/S.IMM`, Sûreté Régionale de Nador) :

```text
reference
objet
maitre_d_ouvrage
date_ouverture_plis
lieu_ouverture_plis
journal_publication + date (confirme aussi "Portail des marchés publics" comme canal)

Liste des concurrents ayant déposé une offre, AVEC leurs montants :
  Concurrent A → montant proposé
  Concurrent B → montant proposé
  ...

concurrent_retenu
montant_attribution
justification_choix (texte)
date_achevement_commission
president_commission (signataire)
```

**Différence clé avec "Résultats définitifs"** : le PV liste **tous les concurrents et leurs montants**, pas seulement le gagnant. Cela ouvre de nouvelles features pour le module IA (§19) :

- `number_of_bidders` — nombre de concurrents par marché (signal de concentration/risque : peu de concurrents peut indiquer un problème)
- `amount_variation` entre l'offre retenue et les autres offres

**Décision à prendre plus tard** : le PV pourrait remplacer "Résultats définitifs" comme source principale d'attribution (sur-ensemble des mêmes données), à condition de vérifier que les PV sont publiés aussi systématiquement que les résultats définitifs. En attendant, on collecte des échantillons des deux.

**Point technique** : les documents PV ont un en-tête bilingue arabe/français ; le texte arabe s'extrait mal en brut (encodage), contrairement à la partie française structurée qui s'extrait proprement. Le nettoyage de texte (`text_cleaning.py`) devra ignorer/isoler cet en-tête.

### 2.10 Champs complets d'une page de détail de consultation

Capture complète d'une page de détail (AON31/2024, DPET Khénifra) — beaucoup plus riche que ce qu'on avait noté initialement :

```text
reference, objet, acheteur_public, type_annonce, mode_passation
categorie_principale, lieu_execution
estimation_dhs_ttc        ← montant estimé, confirmé disponible
caution_provisoire        ← montant de la garantie bancaire exigée
qualifications            ← codes de classification technique (ex: B1;B3;B5;B6, Classe S)
domaines_activite
allotissement (Oui/Non)
reserve_tpe_pme (Oui/Non)
date_mise_ligne
lieu_ouverture_plis
prix_acquisition_plans
```

Sur cet exemple précis, "Dossier Intégral de Consultation" était téléchargeable **directement**, sans le formulaire d'identification (§2.8) — confirme que le blocage n'est pas systématique, dépend du marché/acheteur.

### 2.11 Stratégie OCR confirmée : texte natif vs scanné

Sur l'échantillon collecté, deux types de PDF coexistent :

- **PDF natifs** (texte sélectionnable, générés directement) — extraction directe via PyMuPDF, sans OCR.
- **PDF scannés** (ex: `extrait de pv ao 03-2026.pdf`, marqué "Scanné avec CamScanner") — nécessitent Tesseract.

Confirme que le pipeline déjà prévu au README §11 ("Text available ? OUI → Extract / NON → OCR") est la bonne approche : les deux cas existent réellement, la détection automatique est donc indispensable.

> **Correction (18/08/2026) — la proportion initialement annoncée était fausse.**
> Cette section affirmait auparavant que les PDF natifs étaient la « majorité des cas observés » et que l'OCR ne serait nécessaire que « pour une partie des documents, pas tous ». Cette conclusion reposait sur le premier échantillon manuel (~25 documents), trop petit et non représentatif.
>
> Mesure automatisée sur **390 extraits de PV** téléchargés (100 par an sur 2023-2026, via `scripts/download_extraits_pv.py`, classification par extraction PyMuPDF) :
>
> | Type | Documents | Pages |
> |---|---|---|
> | Natif (aucun OCR requis) | 114 (29,2 %) | 281 |
> | **Scanné (OCR requis)** | **276 (70,8 %)** | **554** |
>
> **Le rapport est donc inversé : environ 7 documents sur 10 sont des scans.** L'OCR n'est pas un cas de repli marginal mais le chemin principal du pipeline. La proportion est stable dans le temps (mesurée à 71,1 % sur les 298 premiers documents, 70,8 % sur les 390) et donc représentative, pas un artefact d'une année particulière.
>
> Conséquences à assumer explicitement dans le rapport final :
> - La qualité de l'OCR conditionne directement la précision de l'extraction (§2.6, `data_dictionary.md` §3.4) sur la majorité du corpus, pas sur une minorité.
> - Le budget de traitement doit être dimensionné pour l'OCR : **554 pages à océriser** sur 835 pages au total, soit ~30-45 min en séquentiel (~8-12 min parallélisé) sur une machine portable.
> - L'évaluation OCR (`etat_de_lart.md` §6) porte donc sur la majeure partie du corpus et devient une métrique centrale du projet, pas secondaire.

### 2.12 Enseignements du deuxième lot d'échantillons (25+ documents, PV + résultats définitifs)

- **Un "concurrent retenu" peut être un groupement (consortium) de plusieurs entreprises** (ex: "Groupement ART STAM SARL AU et TECH-LUX SARL AU", SRM-DT n°10009273). Le modèle `Award`/`Company` doit supporter plusieurs entreprises pour un même marché gagné, pas uniquement une relation 1-à-1.
- **Les documents multi-lots avec résultats mixtes** (certains lots infructueux, d'autres attribués à des entreprises différentes, dans le même document) sont fréquents chez plusieurs acheteurs différents (SRM-RSK, CRRAR) — pas un cas isolé.
- **Format en texte libre** : l'acheteur SDR F.I.A.S.E.T. écrit le résultat dans une seule cellule en prose ("Attribué à la société X avec un montant de Y TTC...") au lieu de colonnes séparées "Concurrent retenu"/"Montant" — l'extraction doit prévoir du texte libre en plus des tableaux structurés.
- **Variantes de libellés de colonnes** : "Montant MAX de l'offre retenue" au lieu de "Montant de l'offre retenue" selon l'acheteur — les regex d'extraction doivent tolérer ces variantes.
- **Nouveaux statuts d'attribution confirmés** : en plus de `INFRUCTUEUX` (aucune offre valable), on a observé "offre jugée excessive" (offre rejetée pour prix trop élevé après une seule candidature) — le modèle `Award` doit prévoir plusieurs statuts possibles, pas juste attribué/infructueux.
- **Le gagnant n'est pas toujours le moins-disant** (ex: consultation d'Inezgane où l'attributaire n'avait pas l'offre la plus basse, mais une réserve corrigée) — toujours extraire `concurrent_retenu` explicitement, ne jamais le déduire en calculant le montant minimum.
- **PV multi-lots** : un même appel d'offres avec plusieurs lots peut avoir un PV séparé par lot, chacun avec son propre champ `delai_execution` (ex: "8 mois").
- **Champ `CLASSEMENT`** parfois présent dans les PV (classement des concurrents par montant) quand il y a plusieurs candidats.

### 2.13 Conclusion phase 2 (légal)

Aucune politique écrite ou machine-readable trouvée (ni `robots.txt`, ni CGU pertinentes, ni mentions légales fonctionnelles). Ces données sont par nature des données de transparence publique. En l'absence de restriction explicite, on applique nos propres règles éthiques (README §7) : limitation du débit de requêtes, aucun contournement d'authentification, données publiques uniquement, traçabilité des URLs sources, journalisation.

### 2.14 Composition mesurée du corpus de 400 extraits de PV (19/08/2026)

Collecte réalisée avec `scripts/download_extraits_pv.py`, métadonnées complétées par
`scripts/enrich_pv_manifest.py`. 400 enregistrements au manifeste, 390 fichiers
distincts (10 PV publiés sous deux références différentes, dédupliqués par SHA-256).

**Catégorie × année :**

| Année | Travaux | Services | Fournitures | Total |
|---|---|---|---|---|
| 2023 | 34 | 46 | 20 | 100 |
| 2024 | 32 | 38 | 30 | 100 |
| 2025 | 35 | 30 | 35 | 100 |
| 2026 | 37 | 30 | 31 | 100* |
| **Total** | **134 (36,0 %)** | **135 (36,3 %)** | **101 (27,2 %)** | **400** |

\* dont 2 documents dont la catégorie n'a pas pu être récupérée (voir plus bas).

**Mode de passation** — le corpus est très concentré :

| Mode | Part |
|---|---|
| Appel d'offres ouvert | 72,6 % |
| Appel d'offres ouvert simplifié | 24,7 % |
| Tous les autres (concours, négocié, restreint…) | 2,7 % |

> **Conséquence importante pour le module IA** : le signal « procédure restreinte /
> absence de mise en concurrence » utilisé comme *red flag* par Fazekas & Kocsis
> (cf. `etat_de_lart.md` §3.4) est **inexploitable sur ce corpus** — un seul marché
> en appel d'offres restreint sur 400. `mode_passation` aura une variance quasi nulle
> comme feature. Le signal de concurrence devra donc reposer sur `number_of_bidders`
> extrait des PV (§2.9), qui reste disponible.

**Limite connue** : 2 consultations (référence `13/2026/DPA/36`,
`refConsultation=1033875` et `1033872`) renvoient une page « Request Rejected »
émise par le pare-feu applicatif du portail, de façon reproductible et spécifique à
ces URLs — les autres pages restent accessibles normalement. Leur `categorie_principale`
est donc absente du manifeste. Ce n'est ni un blocage lié à notre débit de requêtes,
ni un défaut d'extraction.

---

## 3. Prochaines étapes (tâches à faire)

- [x] **Phase 3 — Dataset de validation** : plus de 25 documents réels collectés (consultations, PV, résultats définitifs) sur plusieurs acheteurs différents. Largement suffisant comme vérité terrain (README §48).
- [x] **Rédiger `docs/data_dictionary.md`** : voir [`data_dictionary.md`](data_dictionary.md).
- [ ] **Vérification rapide (optionnelle, faible priorité)** : ouvrir les onglets "Dépôt" et "Groupement" d'une page de détail de consultation pour écarter définitivement la présence d'ICE/RC.
- [ ] **Phase 4 — Environnement** : mise en place `venv`/`requirements.txt`, squelette Docker Compose, `.env.example`.
- [ ] **Phase 5 — Découpage en tâches GitHub** : transformer le planning 15 jours (README §50) en Issues/Projects GitHub, un par jour/module, avec critères de "done" définis à l'avance.
- [ ] **Écrire le problème/scope en un paragraphe** dans `docs/methodology.md`, réutilisable pour le rapport final.
- [ ] Une fois tout ça fait : démarrer le prototype minimal (README §49 Étape 1) — 1 consultation, 1 document, OCR, extraction, base de données.

---

## 4. Décisions prises (à ne pas re-débattre sans raison)

- Le scraper utilisera deux spiders distincts : un pour les consultations, un pour les résultats définitifs, joints par `reference`.
- `ICE`/`RC` restent optionnels dans le modèle `Company`, non garantis comme source de vérité.
- "Listes des marchés attribués" n'est pas la source principale d'attribution — seulement un complément éventuel.
- Aucune procédure restreinte (avec code d'accès) ne sera scrapée.
- Le scraper ne remplit jamais le formulaire d'identification demandé pour certains téléchargements de dossier de consultation (voir §2.8) — pas d'identité fictive, pas d'acceptation automatisée de conditions générales. Ces dossiers sont marqués non téléchargeables ; seules les métadonnées de la consultation sont collectées.
- Le modèle `Award` supporte plusieurs entreprises par marché gagné (cas des groupements/consortiums) et plusieurs statuts (attribué / infructueux / offre jugée excessive), pas juste un booléen gagné/perdu.
- L'extraction ne déduit jamais le gagnant en calculant le montant minimum — toujours lire `concurrent_retenu` explicitement dans le document.
- **Le corpus de travail reste les 400 extraits de PV collectés (100 par an, 2023-2026), toutes catégories confondues.** `categorie_principale` est conservée comme **variable de contrôle** dans les analyses et le module IA, plutôt que de restreindre la collecte à une seule catégorie. Décision prise le 19/08/2026 : on ne collecte pas de corpus « Travaux » séparé.
  - Justification : la répartition mesurée est équilibrée (Services 36,3 %, Travaux 36,0 %, Fournitures 27,2 %), soit ~100 à 135 documents par catégorie — suffisant pour des agrégations séparées.
  - Conséquence à respecter : les comparaisons de montants (`amount_variation`, `market_share`, statistiques par entreprise) doivent être calculées **à l'intérieur d'une même catégorie**, jamais entre catégories — les ordres de grandeur ne sont pas comparables entre Travaux et Fournitures.
