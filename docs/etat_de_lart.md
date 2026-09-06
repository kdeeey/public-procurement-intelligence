# État de l'art : Chaîne Big Data, OCR/NLP et détection d'anomalies pour l'analyse des marchés publics marocains

**Établissement** : [À compléter]
**Projet** : Exploitation des marchés publics — Chaîne Big Data, IA d'océrisation et valorisation fiscale
**Type** : Prototype académique
**Équipe** : 2 étudiantes — IA & Big Data
**Date** : 17/08/2026

> **Note méthodologique** : ce document ne cite que des travaux dont les références (auteurs, année, source) sont réelles et vérifiables — trouvés par recherche bibliographique le 17/08/2026 (ScienceDirect, IEEE Xplore, ResearchGate, arXiv, CEUR-WS, Springer). Quelques pistes identifiées mais pas encore lues en détail restent marquées **[Référence à vérifier]** en bibliographie (§9) — à approfondir avant la remise finale.

---

## Résumé

Les portails de marchés publics génèrent un volume important de données hétérogènes — pages web structurées, PDF natifs, documents scannés, formulaires bilingues arabe/français — qui restent en grande partie inexploitables telles quelles pour l'analyse fiscale ou la détection de risques. Cet état de l'art étudie les briques technologiques nécessaires pour construire une chaîne complète allant de la collecte automatisée de données publiques jusqu'à la détection d'anomalies explicable : le web scraping éthique de portails gouvernementaux, la reconnaissance optique de caractères (OCR) appliquée à des documents administratifs multilingues, l'extraction d'information par règles et traitement du langage naturel (NLP), le traitement distribué de données (Big Data), la détection d'anomalies par apprentissage non supervisé, et l'explicabilité des systèmes d'aide à la décision (XAI). Nous passons en revue la littérature existante sur chacun de ces axes, comparons les principales technologies open source disponibles, et proposons une architecture adaptée au contexte d'un prototype portant sur le Portail Marocain des Marchés Publics (PMMP). Une attention particulière est portée aux limites réelles constatées lors de l'exploration du portail (absence d'identifiants fiscaux publics, formulaires d'authentification pour certains téléchargements, variabilité des formats documentaires selon les acheteurs), qui contraignent directement les choix méthodologiques.

**Mots-clés** : web scraping éthique ; OCR ; NLP ; extraction d'information ; PySpark ; détection d'anomalies ; Isolation Forest ; explicabilité ; marchés publics ; corruption risk indicators ; PMMP.

---

## 1. Introduction

La transparence des marchés publics est reconnue comme un levier de bonne gouvernance et de lutte contre la corruption : plusieurs travaux montrent qu'un accès structuré aux données de passation de marchés permet d'identifier des signaux de risque (concentration des attributions, absence de concurrence, écarts de prix) sans nécessiter d'accès à des données confidentielles [Référence à vérifier — littérature sur l'open contracting / OCDS]. Au Maroc, le Portail Marocain des Marchés Publics (PMMP) publie ces informations, mais sous des formats hétérogènes : métadonnées HTML structurées pour les consultations, documents PDF natifs ou scannés pour les procès-verbaux et résultats d'attribution, parfois en arabe et en français dans un même document.

Avant de pouvoir appliquer des méthodes de détection d'anomalies ou de valorisation fiscale, il est donc nécessaire de résoudre un problème préalable, largement documenté dans la littérature sur l'extraction d'information administrative : transformer des documents hétérogènes et partiellement non structurés en données exploitables, fiables et traçables. Ce rapport dresse un état de l'art des méthodes existantes pour chacune des étapes de cette chaîne, et situe nos choix techniques (déjà partiellement validés par une exploration manuelle du portail réel — voir `docs/discovery_notes.md`) par rapport aux pratiques recommandées dans la littérature.

---

## 2. Concepts fondamentaux

**Web scraping éthique.** Collecte automatisée de données publiques par requêtes HTTP, encadrée par des principes de bonne conduite : respect des fichiers `robots.txt`, limitation du débit de requêtes, absence de contournement d'authentification, et conservation de la traçabilité des sources. En l'absence de `robots.txt` ou de conditions d'utilisation explicites sur la réutilisation des données (cas du PMMP, confirmé par notre exploration), ces principes deviennent des règles auto-imposées plutôt que des contraintes légales formelles.

**OCR (Optical Character Recognition).** Conversion d'une image de document en texte exploitable. Un pipeline OCR complet comprend généralement : une détection préalable de la présence de texte natif (évitant l'OCR quand il n'est pas nécessaire), un prétraitement d'image (niveaux de gris, redressement, réduction du bruit), puis la reconnaissance proprement dite. La qualité dépend fortement de la résolution source et de l'origine du document (numérisation propre vs photo de téléphone).

**NLP / NER (Named Entity Recognition).** Extraction d'entités nommées (organisations, montants, dates, personnes) à partir de texte libre. Deux familles d'approches coexistent : les méthodes à base de règles (expressions régulières, dictionnaires) efficaces sur des formats semi-structurés et prévisibles, et les méthodes statistiques/neuronales (modèles NER entraînés) plus robustes aux variations mais nécessitant des données annotées.

**Big Data / traitement distribué.** Ensemble de techniques et d'outils (ex. Apache Spark) permettant de traiter des volumes de données dépassant les capacités d'un traitement mémoire unique, via la parallélisation des opérations de nettoyage, transformation et agrégation.

**Détection d'anomalies non supervisée.** Identification d'observations statistiquement atypiques sans étiquette de vérité terrain préexistante (aucun marché n'est étiqueté "frauduleux" a priori). Les méthodes les plus courantes reposent sur l'isolement (Isolation Forest), la densité locale (LOF) ou la reconstruction (autoencodeurs).

**Explicabilité (XAI — eXplainable AI).** Ensemble de méthodes visant à rendre compréhensibles les décisions d'un modèle, essentiel dès lors que le système est destiné à assister une décision humaine à fort enjeu (ici, un signalement fiscal) plutôt qu'à décider seul.

**RBAC (Role-Based Access Control) et sécurité applicative.** Modèle de contrôle d'accès où les permissions sont attribuées à des rôles (ici ADMIN/ANALYST/VIEWER) plutôt qu'individuellement à chaque utilisateur, complété par des pratiques standard de sécurité web (validation des entrées, hachage des mots de passe, audit logging).

---

## 3. Revue des travaux scientifiques

### 3.1 Web scraping et données ouvertes de marchés publics

Le mouvement de l'**Open Contracting Data Standard (OCDS)** structure la publication de données de passation de marchés à l'échelle internationale et illustre l'intérêt de standardiser des données publiées de façon hétérogène par différentes administrations [Référence à vérifier — Open Contracting Partnership]. Sans qu'un tel standard existe pour le PMMP, notre exploration manuelle du portail (voir `docs/discovery_notes.md`) a suivi une démarche comparable : identifier empiriquement la structure réelle des données avant de figer un schéma, plutôt que de supposer une structure a priori.

### 3.2 OCR pour documents administratifs multilingues

Tesseract, moteur OCR open source maintenu par Google, reste une référence pour les cas d'usage académiques et les budgets contraints [Smith, R. (2007). *An Overview of the Tesseract OCR Engine*. ICDAR 2007]. Il supporte nativement le français et l'arabe, mais une revue récente de l'OCR arabe souligne que la morphologie de l'arabe (formation des mots par racines, diacritiques, lettres liées/ligatures) complique spécifiquement la segmentation et la reconnaissance, y compris pour des moteurs modernes ; sur des documents propres et à police homogène, les taux d'erreur caractère (CER) descendent sous les 2%, mais ce chiffre se dégrade fortement sur des documents mixtes ou de qualité de numérisation inégale [Référence à vérifier — *Advancements and Challenges in Arabic Optical Character Recognition: A Comprehensive Survey*, arXiv:2312.11812]. Ce constat correspond exactement à ce que nous avons observé sur des extraits de procès-verbaux du PMMP : le texte français structuré s'extrait proprement, tandis que les en-têtes bilingues arabe/français produisent un texte dégradé nécessitant un nettoyage dédié (voir `docs/discovery_notes.md`, §2.9). Ce point nous donne aussi une cible chiffrée réaliste pour l'évaluation OCR (§6) : viser un CER proche de la littérature sur la partie française structurée, tout en acceptant un taux d'erreur plus élevé et non bloquant sur les en-têtes bilingues, qui ne contiennent pas les champs que nous cherchons à extraire.

### 3.3 Extraction d'information dans des documents administratifs non structurés

La littérature distingue les approches par règles (dictionnaires de correspondance, expressions régulières) — robustes sur des formats prévisibles mais fragiles face aux variations de mise en forme — et les approches contextuelles/statistiques, capables de gérer un ordre des champs variable au prix d'un besoin de données annotées [Référence à vérifier — cf. littérature de normalisation d'adresses de Goldberg et al. (2008), transposable au cas de l'extraction d'informations de marchés]. Notre propre exploration confirme la pertinence de cette distinction : les champs structurés en tableau (référence, montant, concurrent retenu) se prêtent bien à une extraction par règles, tandis que les résultats rédigés en texte libre par certains acheteurs (ex. SDR F.I.A.S.E.T., voir `docs/data_dictionary.md` §3.4) nécessitent une approche plus tolérante aux variations.

### 3.4 Détection de risques et de fraude dans les marchés publics

Deux grandes familles de travaux se dégagent de la littérature récente.

**Indicateurs de risque à base de règles ("red flags").** Fazekas et Kocsis construisent un indicateur composite de risque de corruption (CRI — *Corruption Risk Indicator*) à partir de signaux objectifs et facilement extractibles des données de passation : taux de soumissionnaire unique ("single bidding"), absence d'appel d'offres publié, procédure restreinte, période d'avis très courte, critères d'évaluation difficiles à quantifier, et durée de délibération de la commission. Leur étude, portant sur 2,8 millions de contrats dans 28 pays européens (2009-2014), montre que ces signaux — combinés en un score équipondéré — constituent une mesure objective et transférable du risque de corruption à grande échelle, validée par corrélation avec des indices de corruption externes [Fazekas, M., & Kocsis, G. (2020). *Uncovering High-Level Corruption: Cross-National Objective Corruption Risk Indicators Using Public Procurement Data*. British Journal of Political Science, 50(1), 155-164]. Ces signaux recoupent directement plusieurs des features déjà retenues dans notre cahier des charges (`docs/data_dictionary.md` §3.2) — en particulier `number_of_bidders` (équivalent direct du "single bidding") — ce qui légitime leur choix par une base scientifique plutôt que par simple intuition.

**Apprentissage non supervisé sur données ouvertes de marchés publics.** Kehler et Paciello appliquent l'algorithme Isolation Forest ainsi que la méthode CRI à des données de marchés publics du Paraguay publiées au format Open Contracting Data Standard (OCDS), afin de produire un score de risque par contrat destiné à orienter un échantillonnage intelligent pour le contrôle gouvernemental. Leurs résultats préliminaires classent plus de 45% du sous-ensemble jugé potentiellement anormal comme effectivement anormal, sans disposer d'étiquettes de fraude confirmées [Kehler, T., & Paciello, J. (2020). *Anomaly Detection in Public Procurements using the Open Contracting Data Standard*. IEEE / CEUR Workshop Proceedings, Vol. 2369]. Cette étude est particulièrement proche de notre propre approche : même algorithme (Isolation Forest), même contrainte (absence de vérité terrain sur la fraude, cf. §3.5), et même finalité (score de risque destiné à un contrôle humain, pas une décision automatique). D'autres travaux récents prolongent cette approche par des architectures hybrides supervisé/non supervisé (ex. clustering k-means combiné à de la détection d'anomalies pour les marchés publics kényans [Référence à vérifier — Science Publishing Group, *Hybrid Machine Learning Model...Kenya*, 2025]) ou par l'analyse de réseaux sociaux d'entreprises attributaires [Référence à vérifier — ScienceDirect, *Data-Driven Transparency: ML and Social Network Analysis...Chile*, 2025].

### 3.5 Détection d'anomalies non supervisée

**Isolation Forest**, introduit par Liu, Ting et Zhou, isole les observations atypiques en construisant des arbres de partitionnement aléatoire : une observation anormale nécessite en moyenne moins de partitions pour être isolée qu'une observation normale, ce qui permet de calculer un score d'anomalie sans modèle de distribution préalable ni données étiquetées [Liu, F. T., Ting, K. M., & Zhou, Z.-H. (2008). *Isolation Forest*. Proceedings of the 8th IEEE International Conference on Data Mining (ICDM), pp. 413-422]. Cette propriété — ne nécessitant pas d'exemples de fraude connus — en fait un choix adapté à notre contexte, où aucun marché n'est étiqueté comme frauduleux a priori (cf. principe README §16 : "Le système ne décide pas qu'une entreprise est frauduleuse"). D'autres méthodes non supervisées existent, notamment le Local Outlier Factor (LOF) fondé sur la densité locale [Référence à vérifier — Breunig et al., LOF] et les autoencodeurs pour la détection d'anomalies par erreur de reconstruction [Référence à vérifier], comparées en section 4.

### 3.6 Explicabilité des systèmes d'aide à la décision

La littérature sur l'apprentissage interprétable insiste sur la nécessité de fournir des explications compréhensibles dès lors qu'un modèle influence une décision à fort enjeu humain, plutôt que de se limiter à un score opaque [Doshi-Velez, F., & Kim, B. (2017). *Towards A Rigorous Science of Interpretable Machine Learning*. arXiv:1702.08608]. Ce principe est directement repris dans notre architecture : chaque score de risque est accompagné des facteurs contributifs identifiés (montant atypique, concentration, fréquence — README §21), conformément au principe *human-in-the-loop* déjà formalisé dans le cahier des charges (README §54).

### 3.7 Traitement distribué des données

Apache Spark, et son API Python PySpark, s'est imposé comme standard pour le traitement distribué de données à grande échelle, en unifiant traitement par lots, requêtage structuré et apprentissage automatique dans un même moteur [Zaharia, M., Xin, R. S., Wendell, P., et al. (2016). *Apache Spark: A Unified Engine for Big Data Processing*. Communications of the ACM, 59(11), 56-65]. Pour un prototype dont le volume reste volontairement limité (README §6, §15), l'intérêt principal n'est pas la performance mais la démonstration d'une architecture capable de monter en charge — position explicitement assumée dans notre cahier des charges plutôt que présentée comme un besoin réel à ce stade.

### 3.8 Synthèse comparative des articles étudiés

Le tableau ci-dessous résume, pour chaque travail directement pertinent identifié, ce qui a été fait exactement, le modèle/la technicalité employée, le type de données, les résultats obtenus et les difficultés rencontrées — afin de comparer ces approches à la nôtre plutôt que de les citer isolément.

| Article | Ce qu'ils ont fait | Modèle / technicalité | Type de données | Résultats | Difficultés rencontrées |
| --- | --- | --- | --- | --- | --- |
| Kehler & Paciello (2020), *Anomaly Detection in Public Procurements using OCDS* | Score de risque par contrat pour orienter le contrôle gouvernemental | Isolation Forest + méthode CRI | Données ouvertes de marchés publics du Paraguay, format OCDS (structuré) | >45% du sous-ensemble jugé "potentiellement anormal" classé comme tel | Aucune étiquette de fraude confirmée disponible pour valider le modèle — même contrainte que la nôtre |
| Fazekas & Kocsis (2020), *Uncovering High-Level Corruption* | Construction d'un indicateur composite de risque (CRI) à partir de signaux observables | Score à base de règles équipondérées (pas de ML) | 2,8 millions de contrats, 28 pays européens, 2009-2014 | Corrélation validée avec des indices de corruption externes | Les signaux (single bidder, procédure restreinte...) sont des proxys, pas une preuve directe de corruption |
| Enquête arXiv:2312.11812, *Arabic OCR Survey* | Revue des méthodes et limites de l'OCR arabe | Comparatif de moteurs OCR (dont Tesseract) | Corpus de documents arabes variés (imprimés, manuscrits, mixtes) | CER < 2% sur documents propres à police homogène ; dégradation forte sur documents mixtes | Morphologie arabe (racines, diacritiques, ligatures), qualité image très variable |
| *(à ajouter)* Hybrid ML Kenya / ML+Social Network Chili (2025) | Modèles hybrides supervisé + non supervisé pour la corruption dans les marchés publics | k-means + détection d'anomalies ; analyse de réseaux sociaux d'entreprises | Contrats publics nationaux (Kenya / Chili) | [Référence à vérifier — détails de résultats à extraire d'une lecture complète] | À approfondir : disponibilité de données labellisées, généralisation inter-pays |

**Comparaison avec la roadmap proposée** : notre approche se situe précisément entre Kehler & Paciello (même algorithme, même absence de vérité terrain, même finalité de score d'aide au contrôle) et Fazekas & Kocsis (mêmes types de signaux — concentration, soumissionnaire unique/`number_of_bidders` — mais implémentés ici comme *features* d'un modèle Isolation Forest plutôt que comme un score de règles fixes). La différence principale de notre roadmap par rapport à ces deux travaux est la nécessité d'un pipeline OCR/NLP en amont : contrairement à Kehler & Paciello (données déjà structurées au format OCDS) ou Fazekas & Kocsis (données de contrats déjà numériques), le PMMP ne publie pas de données structurées d'attribution — elles doivent être extraites de documents PDF (PV, résultats définitifs), ce qui ajoute une étape (OCR + extraction) absente de ces deux références.

---

## 4. Comparaison des technologies

### 4.1 OCR

| Technologie | Avantages | Inconvénients | Pertinence pour le projet |
|---|---|---|---|
| **Tesseract** | Open source, gratuit, support français/arabe natif, intégrable en local | Performances variables sur scans de faible qualité (CamScanner), pas de compréhension de mise en page complexe | ✔ Retenu — cohérent avec un prototype académique sans budget API |
| API cloud (Google Vision, Azure OCR) | Meilleure précision, gestion native de la mise en page | Payant à l'usage, envoi de documents administratifs à un tiers externe (question de confidentialité) | ✘ Écarté pour ce prototype |
| PyMuPDF (extraction native) | Rapide, exact, aucune erreur de reconnaissance | Ne fonctionne que sur PDF contenant déjà du texte sélectionnable | ✔ Utilisé en première étape de détection, mais ne couvre que **29,2 %** des documents mesurés (`docs/data_dictionary.md` §4) — les 70,8 % restants passent par Tesseract |

### 4.2 Extraction d'information / NLP

| Approche | Avantages | Inconvénients | Pertinence pour le projet |
|---|---|---|---|
| Regex / règles lexicales | Rapide à mettre en œuvre, prévisible, pas de données d'entraînement nécessaires | Fragile aux variations de format (confirmé : "Montant MAX" vs "Montant", texte libre chez certains acheteurs) | ✔ Base de l'extraction, avec tolérance aux variantes |
| spaCy (NER statistique) [Référence à vérifier — Honnibal & Montani, spaCy] | Généralise mieux aux formulations non prévues, extraction d'entités (organisations, personnes, lieux) | Nécessite des modèles pré-entraînés en français, moins fiable sur du texte issu d'OCR bruité | ✔ Complément aux règles pour les champs libres (objet, acheteur) |
| LLM / transformers fine-tunés | Très robuste aux formats variés | Coût de calcul, données d'entraînement nécessaires | ✘ Écarté, piste d'évolution future (README §61) |

### 4.3 Détection d'anomalies

| Méthode | Principe | Avantages | Inconvénients | Pertinence |
|---|---|---|---|---|
| **Isolation Forest** | Isolement par partitionnement aléatoire | Rapide, pas besoin d'exemples étiquetés, adapté aux features tabulaires mixtes | Moins interprétable nativement (nécessite un calcul d'explication séparé) | ✔ Retenu (README §19) |
| Local Outlier Factor (LOF) [Référence à vérifier] | Densité locale relative | Bonne détection d'anomalies locales | Sensible au choix du nombre de voisins, coûteux sur gros volumes | Piste de comparaison possible |
| Autoencodeur | Erreur de reconstruction | Capte des relations non linéaires complexes | Nécessite plus de données et de réglage, moins interprétable | ✘ Écarté |

### 4.4 Traitement des données

| Technologie | Avantages | Inconvénients | Pertinence |
|---|---|---|---|
| **PySpark** | Démontre une architecture scalable, API proche de Pandas | Overhead pour de petits volumes, complexité de déploiement local | ✔ Retenu pour la démonstration architecturale (README §15) |
| Pandas seul | Simple, rapide sur petits volumes | Ne démontre pas de capacité Big Data | Alternative de repli si PySpark pose problème en environnement local |

---

## 5. Architecture proposée

L'architecture retenue reprend et affine celle du cahier des charges initial (README §8), validée et corrigée par l'exploration réelle du PMMP (`docs/discovery_notes.md`, `docs/data_dictionary.md`) :

```text
PMMP (Consultations + PV + Résultats définitifs)
        │
        ▼
   Scraper (requests.Session, rate-limited)
        │
   ┌────┴────┐
   ▼         ▼
Métadonnées  Documents (PDF)
(HTML)         │
   │           ▼
   │      Texte natif ? ──NON──▶ OCR (Tesseract)
   │           │OUI                  │
   │           ▼                     ▼
   │      Extraction texte ◀─────────┘
   │           │
   │           ▼
   │      Nettoyage (isolation en-têtes bilingues)
   │           │
   │           ▼
   │      Extraction (regex + spaCy)
   │           │
   └─────┬─────┘
         ▼
   PostgreSQL (structuré) + MinIO (documents bruts)
         │
         ▼
   PySpark (nettoyage, agrégation, features)
         │
         ▼
   Isolation Forest → score d'anomalie → Risk Score explicable
         │
         ▼
   FastAPI (JWT, RBAC, audit logs) → Streamlit Dashboard
```

Cette architecture diffère de l'hypothèse initiale sur un point clé, documenté et justifié par l'exploration réelle : les données d'attribution proviennent de **deux sources complémentaires** (extraits de PV, plus riches, et résultats définitifs, en secours), et non d'une source unique comme envisagé au départ (`docs/data_dictionary.md`, §1).

---

## 6. Évaluation et validation

Conformément aux pratiques standards de la littérature en extraction d'information et en détection d'anomalies, l'évaluation du prototype combinera :

- **OCR** : taux d'erreur caractère (CER) et taux d'erreur mot (WER), mesurés sur l'échantillon de validation constitué manuellement (`data/samples/`, plus de 25 documents réels annotés à la main — README §48). Cette métrique est **centrale et non secondaire** : 70,8 % des extraits de PV collectés sont des documents scannés (mesure sur 390 documents, cf. `docs/discovery_notes.md` §2.11), la qualité de l'OCR conditionne donc la précision de l'ensemble de la chaîne d'extraction.
- **Extraction d'information** : précision, rappel, F1-score par champ (référence, montant, entreprise, date), comparés aux valeurs attendues notées manuellement.
- **Détection d'anomalies** : en l'absence de vérité terrain sur la fraude (limite assumée, cf. §7), l'évaluation restera qualitative — vérification que les cas extrêmes connus (montants très supérieurs à la moyenne du groupe, concentration élevée) sont bien détectés, plutôt qu'une métrique de précision/rappel classique qui supposerait des étiquettes de fraude inexistantes.

---

## 7. Bonnes pratiques, limites et recommandations

- **Scraping éthique** : en l'absence de `robots.txt` ou de conditions d'utilisation opposables sur le PMMP (confirmé, `docs/discovery_notes.md` §2.10/2.13), le projet applique un débit de requêtes limité, ne contourne aucune authentification, et ne remplit jamais le formulaire d'identification requis pour certains téléchargements de dossiers (`docs/data_dictionary.md` §6) — une position plus stricte que ce qu'exige strictement la loi, choisie par prudence académique.
- **Qualité des données sources** : la variabilité de format documentée entre acheteurs (montants exprimés différemment, résultats en texte libre chez certains organismes) impose une extraction tolérante aux variantes plutôt que des règles rigides — confirmé empiriquement, pas seulement anticipé théoriquement.
- **Absence de données fiscales réelles** : comme souligné dans le cahier des charges initial (README §22) et reconfirmé par l'exploration (ICE/RC des entreprises gagnantes non publiés), le référentiel fiscal utilisé pour démontrer le mécanisme de croisement reste nécessairement synthétique.
- **Human-in-the-loop** : conformément à la littérature sur l'explicabilité (§3.6), le système ne doit jamais qualifier une entreprise de frauduleuse ; il fournit un score et des facteurs destinés à l'analyste humain.

---

## 8. Conclusion et perspectives

Cet état de l'art confirme que les choix techniques du projet — Tesseract pour l'OCR avec détection préalable de texte natif, combinaison de règles et de NLP pour l'extraction, Isolation Forest pour la détection d'anomalies non supervisée, et un principe d'explicabilité systématique — s'appuient sur des pratiques éprouvées dans la littérature, tout en étant adaptés aux contraintes réelles constatées sur le PMMP (variabilité des formats, absence d'identifiants fiscaux publics, blocages d'accès partiels). La prochaine étape est le développement du prototype selon l'architecture proposée en §5, avec évaluation sur l'échantillon de validation déjà constitué.

Les pistes d'évolution identifiées (README §61) — passage à un modèle NLP plus avancé, recherche sémantique, monitoring en production — restent hors du périmètre du prototype mais s'inscrivent dans la continuité de cette revue de littérature.

---

## 9. Bibliographie

**Directement sur le sujet (marchés publics / anomalies / corruption) :**

- Kehler, T., & Paciello, J. (2020). *Anomaly Detection in Public Procurements using the Open Contracting Data Standard*. IEEE / CEUR Workshop Proceedings, Vol. 2369. [ceur-ws.org/Vol-2369/short09.pdf](https://ceur-ws.org/Vol-2369/short09.pdf)
- Fazekas, M., & Kocsis, G. (2020). *Uncovering High-Level Corruption: Cross-National Objective Corruption Risk Indicators Using Public Procurement Data*. British Journal of Political Science, 50(1), 155–164.

**OCR / documents multilingues :**

- Smith, R. (2007). *An Overview of the Tesseract OCR Engine*. Proceedings of the Ninth International Conference on Document Analysis and Recognition (ICDAR 2007).
- *Advancements and Challenges in Arabic Optical Character Recognition: A Comprehensive Survey* (2023). arXiv:2312.11812.

**Fondations méthodologiques (ML / Big Data / XAI) :**

- Liu, F. T., Ting, K. M., & Zhou, Z.-H. (2008). *Isolation Forest*. Proceedings of the 8th IEEE International Conference on Data Mining (ICDM), 413–422.
- Zaharia, M., Xin, R. S., Wendell, P., Das, T., Armbrust, M., Dave, A., Meng, X., Rosen, J., Venkataraman, S., Franklin, M. J., Ghodsi, A., Gonzalez, J., Shenker, S., & Stoica, I. (2016). *Apache Spark: A Unified Engine for Big Data Processing*. Communications of the ACM, 59(11), 56–65.
- Doshi-Velez, F., & Kim, B. (2017). *Towards A Rigorous Science of Interpretable Machine Learning*. arXiv:1702.08608.

**À approfondir avant remise finale (piste identifiée, détails/citation exacte à confirmer par une lecture complète) :**

- **[Référence à vérifier]** — *A Hybrid Machine Learning Model for Detecting and Preventing Corruption in Kenya's Public Procurement Contracts*, Machine Learning Research, Science Publishing Group (2025) — modèle hybride k-means + détection d'anomalies, piste de comparaison pour la roadmap.
- **[Référence à vérifier]** — *Data-Driven Transparency: Machine Learning and Social Network Analysis for Corruption Detection in Public Procurement* (Chili), ScienceDirect (2025) — approche par analyse de réseau, complémentaire à la nôtre.
- **[Référence à vérifier]** — Honnibal, M., & Montani, I. — spaCy (bibliothèque NLP utilisée pour l'extraction d'entités).
- **[Référence à vérifier]** — Breunig, M. M. et al. — LOF (Local Outlier Factor), cité en comparaison de méthode en §4.3.

---

*Sources des recherches web effectuées le 17/08/2026 : ScienceDirect, ResearchGate, IEEE Xplore, Springer, arXiv, CEUR-WS. Les 3 références "à approfondir" ont été localisées mais nécessitent une lecture complète (pas seulement le résumé) avant d'être citées avec leurs résultats précis dans le document final.*
