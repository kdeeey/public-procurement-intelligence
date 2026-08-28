# MODULE 4 — IA / DÉTECTION D'ANOMALIES

> **Document de reprise.** Écrit le 28/08/2026, après une session de refonte
> qui a changé l'unité d'analyse du module. Tous les chiffres qui suivent ont
> été relus dans le code ou dans les artefacts au moment de la rédaction.
>
> **Convention de fiabilité utilisée dans tout le document :**
>
> | Label | Signification |
> |---|---|
> | ✅ **Implémenté** | présent dans le code et exécuté avec succès |
> | 🟡 **Partiel** | présent mais limité ou incomplet |
> | 📋 **Prévu** | conçu, pas encore écrit |
> | ⚠️ **Non vérifié** | impossible de confirmer avec les éléments disponibles |
> | ❌ **Impossible** | les données du corpus ne le permettent pas |

---

## ⚠️ AVERTISSEMENT PRÉALABLE — LE SCHÉMA DE RÉFÉRENCE EST PÉRIMÉ

Le schéma d'architecture qui circule encore dans nos notes décrit le Module 4
**tel qu'il était avant le 28/08/2026** : une détection au niveau de
l'**entreprise**, avec les features `market_share`, `number_of_awards`,
`frequency`, `amount_variation`.

**Ce n'est plus ce que fait le module.** L'unité d'analyse est désormais le
**marché**. La section 19 explique pourquoi, avec la mesure qui a motivé le
changement.

Correspondance entre le schéma ancien et la réalité actuelle :

| Élément du schéma de référence | État réel au 28/08/2026 |
|---|---|
| Features `market_share`, `number_of_awards`, `frequency` | ❌ **supprimées** — features entreprise, artefact mesuré |
| Feature `amount_variation` | ❌ **impossible** — estimation absente de 100 % des marchés |
| Red flag « concentration » | 🟡 existe, mais **par acheteur** et hors modèle |
| Red flag « fréquence » / « nombre d'attributions » | ❌ supprimé avec l'étage entreprise |
| `ML → PostgreSQL → FastAPI → Streamlit` | 🟡 **vrai pour l'ancien étage entreprise uniquement.** Les résultats marché vont en **Parquet → Streamlit**, sans passer par PostgreSQL ni l'API |
| Risk Score 0-100 | ✅ implémenté |
| Niveaux Faible/Modéré/Élevé/Critique | ✅ implémenté, seuils mesurés |
| SHAP | ✅ implémenté (créé aujourd'hui, n'existait pas) |

---

## 1. Vue d'ensemble

Le Module 4 répond à une question, et une seule :

> **« Parmi les marchés publics du corpus, lesquels un analyste humain
> devrait-il examiner en priorité, et pourquoi ? »**

Il ne répond pas à « ce marché est-il frauduleux ? ». Cette distinction n'est
pas une précaution de langage : c'est la contrainte de conception qui
structure tout le module. Sans vérité terrain (aucun marché du corpus n'est
connu comme irrégulier), aucune affirmation de fraude n'est vérifiable.

**Ce que le module produit concrètement :**

| Sortie | Grain | Volume |
|---|---|---|
| Score d'anomalie (0-100) | 1 marché | 279 |
| Niveau de risque | 1 marché | 279 + 35 non évaluables |
| Red flags nommés | 1 marché | 314 |
| Explication SHAP | 1 marché | 279 |
| Score de priorité d'analyse | 1 marché | 314 |
| Score de qualité des données | 1 marché | 454 |

---

## 2. Rôle dans l'architecture PMMP

```text
Module 1  SCRAPING            portail PMMP → 390 PDF + 1750 consultations
Module 2  OCR + EXTRACTION    PDF → texte → 454 Award (JSON)
          ↓                   PostgreSQL (procurements, documents, awards, companies)
Module 3  BIG DATA (Spark)    → fact_award_company, market_stats, market_features
          ↓
Module 4  IA / ANOMALIES      ← VOUS ÊTES ICI
          ↓
Module 5  RESTITUTION         Streamlit (+ FastAPI pour l'ancien étage entreprise)
```

**Frontière exacte du Module 4** : il commence à la lecture de
`market_features.parquet` (produit par le Module 3) et s'arrête à l'écriture
des Parquet de résultats. Il ne lit PostgreSQL que pour un contrôle de
volumétrie (`database/crud/counts.py`), jamais pour ses calculs.

---

## 3. Entrées du Module 4

### 3.1 Entrée principale — `market_features.parquet`

| Propriété | Valeur |
|---|---|
| Produit par | `bigdata/spark/jobs/build_market_features.py` (Module 3) |
| Grain | **1 ligne = 1 Award = 1 lot d'un marché** |
| Volume | **454 lignes × 38 colonnes** |
| Format | Parquet |

Le grain est le **lot**, pas le document : un PV multi-lots produit plusieurs
lignes. C'est indispensable — le document `349e44bf` attribue son lot 1 et
déclare les lots 2 et 3 infructueux ; agréger au document inverserait le
statut.

### 3.2 Colonnes réellement consommées

| Colonne | Type | Renseignée | Usage dans le Module 4 |
|---|---|---:|---|
| `award_id` | int | 454 | clé de jointure de toutes les sorties |
| `statut` | str | 454 | sélection de la population (ATTRIBUE) |
| `montant_ttc` | float | **167** | feature + RF03 + qualité |
| `montant_ht` | float | **35** | contexte seulement, jamais dans le modèle |
| `nb_soumissionnaires` | float | **377** | feature + RF01 |
| `nb_concurrents_ecartes` | float | 319 | feature |
| `exclusion_rate` | float | 261 | feature + RF02 |
| `has_amount_data` | int | 454 | feature + qualité |
| `has_competitor_data` | int | 454 | qualité |
| `has_exclusion_data` | int | 454 | feature + qualité |
| `mode_passation` | str | **454** | one-hot + RF05 |
| `categorie_principale` | str | **454** | one-hot + groupes comparables |
| `annee` | int | 454 | groupes comparables + temporel |
| `date_ouverture_plis` | date | 312 | qualité |
| `companies` | list | 205 | affichage du gagnant |
| `acheteur_public`, `objet`, `reference` | str | 454 | affichage |
| `extraction_warning` | int | 454 | avertissement qualité |

### 3.3 Entrée secondaire — `market_stats.parquet`

Fournit `number_of_bidders_filtered` (nombre de soumissionnaires après
filtrage des noms implausibles), déjà intégré dans `market_features`.

---

## 4. Pipeline complet — état réel

```text
market_features.parquet  (454 × 38)                    ← Module 3
        │
        ├──────────────────────────────────────────────┐
        ▼                                              ▼
[A] features/data_quality.py                    [B] ai/train_market_model.py
    4 états par dimension                           sélection ATTRIBUE (314)
    score 0-100                                     porte de complétude (≥2/3)
        │                                           imputation médiane
        ▼                                           contrôle variance + corrélation
market_data_quality.parquet (454)                   Isolation Forest
        │                                           rescale 0-100 + niveaux
        │                                           stabilité 10 graines
        │                                               │
        │                                               ▼
        │                                   market_anomaly_scores.parquet (314)
        │                                               │
        │                       ┌───────────────────────┼───────────────┐
        │                       ▼                       ▼               ▼
        │          [C] market_peer_analysis    [D] market_explain   [E] market_red_flags
        │              cascade de groupes         SHAP + ablation      registre 5 règles
        │                       │                       │               │
        │          market_peer_comparison    market_explanations   market_red_flags
        │              (314)                      (279)                 (314)
        │                       │                       │               │
        └───────────────────────┴───────────┬───────────┴───────────────┘
                                            ▼
                              [F] ai/priority_score.py
                                  0,5 × anomalie + 0,5 × red flags
                                  plafond par la confiance
                                            │
                                            ▼
                              market_priority.parquet (314)
                                            │
                                            ▼
                                 Streamlit (lecture directe)
                                            │
                                            ▼
                                      Analyste humain
```

**Modules annexes, hors chaîne principale** : `ai/market_temporal_analysis.py`
(agrégats annuels), `ai/network_analysis.py` (concentration par acheteur),
`ai/benchmark_rulebased.py` (comparaison à une méthode simple).

---

## 5. Contrôle et préparation des données

**Fichier** : `ai/train_market_model.py` — fonctions `prepare_market_matrix()`,
`drop_constant_features()`, `drop_redundant_features()`.

### 5.1 Contrôles réellement effectués

| Contrôle demandé par le schéma | État | Implémentation |
|---|---|---|
| Types | ✅ | `pd.to_numeric(errors="coerce")` sur toute colonne imputée |
| Valeurs manquantes | ✅ | imputation médiane + drapeau, jamais 0 |
| Valeurs infinies | ⚠️ **Non vérifié** | aucun contrôle explicite ; aucun `inf` observé |
| Doublons | ✅ | grain garanti en amont (`dropDuplicates` sur `award_id`, Module 3) |
| Cohérence | ✅ | 3 règles `INVALID` mesurées (section 7.5) |
| Variance nulle | ✅ | `drop_constant_features()` |
| Corrélation | ✅ | `drop_redundant_features()`, seuil 0,95 |
| Cardinalité | ❌ | non implémenté |
| Data leakage | 🟡 | analysé, non automatisé (section 24.6) |

### 5.2 Imputation — valeurs réelles utilisées

Médianes calculées **sur les seuls marchés qui possèdent la donnée** :

```text
log_montant_ttc         → 13,4656   (≈ 704 000 DH, exp(13,4656) − 1)
nb_soumissionnaires     →  1,0
nb_concurrents_ecartes  →  0,0
exclusion_rate          →  0,0
```

**Jamais 0 pour un montant** : un 0 se lit comme une valeur extrême basse par
un détecteur d'anomalies, pas comme un inconnu. Chaque colonne imputée est
accompagnée de son drapeau `has_*_data`, qui reste une observation réelle.

### 5.3 Colonnes retirées automatiquement au dernier run

| Colonne | Motif mesuré |
|---|---|
| `has_competitor_data` | **constante** : vaut 1 pour les 279 marchés scorés |
| `mode_ao_simplifie` | **redondante** : r = 0,971 avec `mode_ao_ouvert` |

Ces retraits sont automatiques et **remesurés à chaque exécution** : si le
corpus change, la liste change.

---

## 6. Population comparable

### 6.1 Population modélisée — 279 marchés sur 454

Deux filtres successifs, chacun justifié par une mesure :

**Filtre 1 — statut `ATTRIBUE`** (454 → 314)

```text
ATTRIBUE     314 marchés — gagnant 205 (65,3 %), montant 142 (45,2 %)
INFRUCTUEUX  140 marchés — gagnant   0 ( 0,0 %), montant  25 (17,9 %)
```

Un marché infructueux n'a **aucun attributaire** — 0/140, sans exception. Les
red flags portent tous sur une attribution ; mélanger les deux populations
apprendrait au modèle à séparer les statuts, une tautologie.

**Filtre 2 — porte de complétude `data_completeness ≥ 2`** (314 → 279)

Mesure qui a imposé ce filtre, faite après une première version du modèle :

```text
0 information connue sur 3 :   7 marchés →  7 signalés (100,0 %)
1 information connue       :  28 marchés →  9 signalés ( 32,1 %)
2 informations             : 151 marchés →  8 signalés (  5,3 %)
3 informations             : 128 marchés →  8 signalés (  6,3 %)
```

Le modèle détectait les **trous d'extraction**, pas les marchés atypiques.
Après la porte, la corrélation entre le score et la complétude passe de
**−0,249 à +0,063**.

**Coût assumé** : 35 marchés (11,1 %) sortent de l'analyse. Ils restent dans
la sortie avec `scorable = False` et **aucun score** — jamais « Faible ».

### 6.2 Population comparable au sens « pairs »

⚠️ **Attention à ne pas confondre** avec ce qui précède. La « population
comparable » du schéma de référence (Services / Travaux / Fournitures) est
implémentée séparément, dans `ai/market_peer_analysis.py`, sous forme de
**cascade** : voir section 7.6.

---

## 7. Construction des Red Flags

**Fichier** : `ai/market_red_flags.py` — architecture de **registre** : chaque
règle est un objet `RedFlag(id, name, description, severity, evaluate, derived)`.

### 7.1 Règle absolue : trois valeurs, jamais deux

Chaque red flag vaut `True` / `False` / **`None` (non évaluable)**. Il ne se
déclenche **jamais** sur une valeur absente, imputée ou incohérente. Dire
« pas de red flag » sur un marché dont on ignore tout serait un faux négatif
présenté comme un contrôle passé.

Toutes les conditions consomment les états de `features/data_quality.py` —
une seule source de vérité.

### 7.2 Red flags réellement implémentés

| ID | Nom | Sévérité | Poids | Condition | Actif | Inactif | Non évaluable |
|---|---|---|---:|---|---:|---:|---:|
| **RF01** | Faible concurrence | élevée | 3 | `nb_soumissionnaires ≤ 1` et dimension `concurrents` = KNOWN | 96 | 148 | 70 |
| **RF02** | Exclusions atypiques | moyenne | 2 | `exclusion_rate ≥ 0,500` | 45 | 163 | 106 |
| **RF03** | Montant atypique | moyenne | 2 | au-dessus du P90 **de ses pairs**, sinon repli quantile corpus | 12 | 130 | 172 |
| **RF05** | Procédure rare | faible | 1 | procédure < 5 % du corpus | 6 | 308 | 0 |
| **RF06** | Signaux multiples | moyenne | 2 | ≥ 2 red flags primaires actifs — **dérivé** | 26 | 263 | 25 |

**RF04 (écart estimation / attribution) — ❌ IMPOSSIBLE.** `estimation_dhs_ttc`
est renseignée sur 1196/1350 consultations de la Passe B mais **0/454** des
marchés liés à un Award : la page d'un marché déjà attribué ne porte plus son
estimation. Sa numérotation est laissée vide pour que l'absence se voie.

### 7.3 Seuils — mesurés, jamais devinés

| Seuil | Valeur | Origine | Base de calcul |
|---|---|---|---|
| RF02 | **0,500** | quantile 0,80 | 208 marchés à état KNOWN |
| RF03 | **11 746 666,13 DH** | quantile 0,95 | 135 marchés à état KNOWN |
| RF05 | **< 5 %** du corpus | 4 modalités | 6 marchés |

> **Piège rencontré** : le quantile 0,90 avait été essayé pour RF02 — il vaut
> **exactement 1,000** sur ce corpus (59,9 % des marchés à 0, puis une queue
> chargée à 1). Un seuil à « 100 % des concurrents écartés » est dégénéré : il
> ne sépare plus rien. 0,80 donne 0,50, soit « au moins la moitié des
> concurrents écartés » — mesuré **et** interprétable.

### 7.4 Score de red flags

```text
red_flag_score = 100 × Σ(poids des flags actifs) / Σ(poids des flags évaluables)
```

Rescalé sur les règles **évaluables pour ce marché précis** : un marché dont
2 règles sur 4 sont inapplicables ne doit pas être mécaniquement plafonné par
notre propre manque de données.

### 7.5 Red flags du schéma de référence — état réel

| Red flag du schéma | État |
|---|---|
| Faible concurrence | ✅ RF01 |
| Montant | ✅ RF03 |
| Concentration | 🟡 existe dans `ai/network_analysis.py`, **par acheteur**, hors modèle et hors red flags |
| Fréquence | ❌ supprimé — feature entreprise |
| Montant total | ❌ supprimé — feature entreprise |
| Variation du montant | ❌ impossible — estimation absente |
| Nombre d'attributions | ❌ supprimé — c'est l'artefact mesuré (section 19.1) |

**Non prévus par le schéma mais implémentés** : RF02 (exclusions), RF05
(procédure rare), RF06 (combinaison).

### 7.6 Comparaison aux pairs — ✅ implémentée, 🟡 couverture limitée

**Fichier** : `ai/market_peer_analysis.py`. Cascade du plus fin au plus
grossier, minimum **10 comparables** (le marché lui-même exclu) :

| Niveau | Clé | Marchés |
|---|---|---:|
| fin | secteur × procédure × année | **255** |
| moyen | secteur × procédure | 53 |
| large | secteur × année | 6 |
| — | `NOT_ENOUGH_PEERS` | **0** |

**Double minimum** : avoir 10 comparables ne suffit pas, il faut 10
comparables portant **la même dimension**. Résultat :

- comparaison de **montant** calculable : **67/314 (21,3 %)**
- comparaison de **concurrence** : **213/314 (67,8 %)**

---

## 8. Features ML

### 8.1 Les 11 features réellement en entrée du modèle

Source : `ai/models/market_feature_columns.json` (généré, pas écrit à la main).

| Feature | Définition | Calcul | Pourquoi | Signal visé |
|---|---|---|---|---|
| `log_montant_ttc` | log du montant TTC | `log1p(montant_ttc)` | les montants s'étalent sur 4 ordres de grandeur (22 200 → 95 836 800 DH) ; sans compression une poignée de gros marchés écrase toute la variance | marché disproportionné |
| `nb_soumissionnaires` | nombre de concurrents plausibles | `number_of_bidders_filtered` | indicateur le mieux établi de la littérature | concurrence faible |
| `nb_concurrents_ecartes` | nombre d'exclus plausibles | filtre de plausibilité | une exclusion est une décision motivée | sélection restrictive |
| `exclusion_rate` | écartés / soumissionnaires | ratio, NULL si dénominateur invalide | relativise le nombre brut | sélection restrictive |
| `has_amount_data` | montant réellement lu | booléen | permet au modèle de savoir qu'une valeur est imputée | — (qualité) |
| `has_exclusion_data` | exclusions réellement lues | booléen | idem | — (qualité) |
| `mode_ao_ouvert` | procédure = AO ouvert | one-hot | 100 % de couverture, procédure = contexte de concurrence | contexte |
| `mode_autre` | procédure hors 2 dominantes | one-hot groupé | évite 6 colonnes quasi constantes | contexte |
| `cat_travaux` | secteur Travaux | one-hot | 100 % de couverture | contexte |
| `cat_fournitures` | secteur Fournitures | one-hot | idem | contexte |
| `cat_services` | secteur Services | one-hot | idem | contexte |

**Encodage** : one-hot explicite. Aucun encodage ordinal — `ouverte = 1,
restreinte = 2` introduirait un faux ordre numérique.

### 8.2 Features du schéma de référence — état réel

| Feature du schéma | État | Raison |
|---|---|---|
| `amount` | ✅ → `log_montant_ttc` | conservée, transformée |
| `number_of_bidders` | ✅ → `nb_soumissionnaires` | conservée |
| `number_of_awards` | ❌ **supprimée** | feature entreprise — c'est l'artefact (section 19.1) |
| `total_amount` | ❌ supprimée | feature entreprise |
| `market_share` | ❌ supprimée | feature entreprise ; r = **1,000** avec `total_amount` |
| `frequency` | ❌ jamais implémentée | feature entreprise |
| `amount_variation` | ❌ **impossible** | exige l'estimation : 0/454 |

### 8.3 Feature explicitement écartée du modèle

`single_bidder` (booléen dérivé de `nb_soumissionnaires`) est **calculé mais
non fourni au modèle** : entièrement redondant, et l'imputer forcerait à
choisir 0 ou 1 pour un marché dont on ignore le nombre de soumissionnaires.
Il sert uniquement à RF01, qui, lui, est conditionné à l'état KNOWN.

---

## 9. Préparation de la matrice X

**Fonction** : `prepare_market_matrix(pdf) → (matrix, medians)`

```text
market_features.parquet (454 × 38)
        ↓ filtre statut == ATTRIBUE
    (314 lignes)
        ↓ calcul data_completeness = has_amount + has_competitor + has_exclusion
        ↓ filtre data_completeness >= 2
    (279 lignes)
        ↓ pd.to_numeric(errors="coerce") sur les 4 colonnes imputables
        ↓ fillna(médiane des marchés AYANT la donnée)
        ↓ colonnes complètes → astype(int)
        ↓ assert : aucun NaN résiduel
    X = matrix[features].to_numpy(dtype=float)
        ↓ retrait des constantes et des redondances
    X final : 279 lignes × 11 colonnes
```

**Aucune normalisation / standardisation.** C'est volontaire : Isolation
Forest partitionne par seuils sur chaque axe, il est insensible à l'échelle.
Une standardisation n'apporterait rien et rendrait les valeurs illisibles
dans SHAP.

---

## 10. Isolation Forest

### 10.1 Niveau simple — pour comprendre le principe

**Apprentissage non supervisé.** Nous n'avons **aucun label** : aucun marché
du corpus n'est étiqueté « irrégulier ». Le modèle ne peut donc pas apprendre
à reconnaître une fraude — il ne l'a jamais vue.

**Ce qu'il fait à la place** : il cherche les observations **faciles à
isoler**. L'algorithme découpe les données au hasard (choisir une colonne au
hasard, un seuil au hasard, couper, recommencer). Une observation banale,
entourée de beaucoup d'autres qui lui ressemblent, exige beaucoup de coupes
avant de se retrouver seule. Une observation atypique se retrouve isolée en
quelques coupes.

```text
Marché ordinaire        Marché atypique
(entouré de pairs)      (loin de tout)

  ●●●●●●●●                        ●
  ●●●●●●●●
  ●●●●●●●●              ← 3 coupes suffisent
   ↑
   12 coupes nécessaires
```

**Anomalie ≠ fraude.** Un marché isolé est un marché **différent des autres du
corpus**. Il peut l'être pour des raisons parfaitement régulières : marché
très spécialisé, opérateur unique qualifié, prestation sur mesure. Le modèle
mesure une **rareté statistique**, jamais une irrégularité.

### 10.2 Niveau technique — notre implémentation

**Fichier** : `ai/train_market_model.py`

```python
model = IsolationForest(
    n_estimators=200,      # 200 arbres
    contamination=0.10,    # choisi après comparaison, voir 10.3
    random_state=42,       # reproductibilité
)
model.fit(X)                            # X : 279 × 11
scores = model.decision_function(X)     # plus bas = plus isolé
labels = model.predict(X)               # -1 = anomalie, 1 = normal
```

Tous les autres paramètres sont les défauts scikit-learn (`max_samples="auto"`,
`max_features=1.0`, `bootstrap=False`).

**Sauvegarde** : `joblib.dump(model, "ai/models/isolation_forest_market.joblib")`
et l'ordre des colonnes dans `ai/models/market_feature_columns.json` — sans cet
ordre, un rechargement du modèle appliquerait les seuils aux mauvaises colonnes.

### 10.3 Le paramètre `contamination` — étudié, pas subi

`contamination` **ne mesure rien dans les données** : c'est un curseur qui fixe
combien d'observations seront étiquetées anormales.

| Valeur | Marchés signalés | Part |
|---|---:|---:|
| 0,05 | 13 | 4,7 % |
| **0,10 ← retenu** | **28** | **10,0 %** |
| 0,15 | 42 | 15,1 % |
| `"auto"` | 62 | 22,2 % |

**Pourquoi 0,10** : `"auto"` ne répond à aucune question métier et sortait
22,2 %, un chiffre qu'aucune mesure ne soutient et qui se lirait à tort comme
« 22 % des marchés sont suspects ». 0,10 fixe une **charge de travail
d'analyse** (~28 dossiers sur 279), pas un taux d'irrégularité. Le faire
varier change la longueur de la liste, **jamais l'ordre**.

### 10.4 Stabilité — ✅ implémentée

`measure_stability()` réentraîne le modèle avec **10 graines** (`random_state`
0 à 9) et compare les **Top 20** :

```text
recouvrement moyen entre deux Top 20 (Jaccard) : 0,81
marchés présents dans les 10/10 classements    : 14
marchés présents dans 1 seul classement        :  1
```

`stability_frequency` (0 à 10) est écrit pour chaque marché. Un score instable
ne se lit pas comme un score stable, et le dashboard le signale.

---

## 11. Anomaly Score

**Sortie brute** : `model.decision_function(X)`, **plus la valeur est basse,
plus le marché est isolé**.

Plage réellement observée sur nos 279 marchés :

```text
min = −0,0998   (le plus atypique)
max = +0,1725   (le plus banal)
```

Ce nombre n'est pas interprétable par un analyste : ni borné a priori, ni
orienté dans le sens intuitif, ni comparable d'un entraînement à l'autre.
D'où la transformation de la section 12.

---

## 12. Risk Score 0-100

### 12.1 Formule réellement utilisée

```python
lo, hi = scores.min(), scores.max()
anomaly_score_0_100 = 100 * (hi - scores) / (hi - lo)
```

Rescale **linéaire min-max**, avec **inversion du sens** : plus haut = plus
atypique.

### 12.2 Pourquoi linéaire et non un rang

Un rang (percentile) répartirait mécaniquement les marchés de 0 à 100 de façon
uniforme et **aplatirait la forme réelle de la distribution** — or celle-ci est
très asymétrique : une grande masse de marchés banals, une queue courte
d'atypiques. Le rescale linéaire conserve les écarts réels.

### 12.3 Exemple numérique — valeurs réelles du corpus

```text
Marché le plus atypique :
  anomaly_score = −0,0998
  → 100 × (0,1725 − (−0,0998)) / (0,1725 − (−0,0998))
  → 100 × 0,2723 / 0,2723 = 100,0

Marché le plus banal :
  anomaly_score = +0,1725
  → 100 × (0,1725 − 0,1725) / 0,2723 = 0,0
```

⚠️ **Limite du rescale min-max** : les bornes 0 et 100 sont **relatives au
corpus**. Elles se déplacent si le corpus change. Un score de 100 signifie
« le plus atypique de CE corpus », pas « atypique dans l'absolu ».

---

## 13. Classification du risque

### 13.1 Seuils — mesurés, jamais 25/50/75

```text
Faible    : score ≤ 63,3          ← frontière que le modèle choisit lui-même
                                     (max des marchés non signalés)
Modéré    : 63,3 < score ≤ 73,8   ← 1er tercile du sous-groupe signalé
Élevé     : 73,8 < score ≤ 86,5   ← 2e tercile
Critique  : score > 86,5
```

La frontière du niveau « Faible » n'est pas choisie : c'est exactement la
limite que `contamination` a fixée. Le sous-groupe signalé est ensuite coupé
en **terciles mesurés de sa propre distribution**.

### 13.2 Distribution obtenue

| Niveau | Marchés |
|---|---:|
| Faible | 251 |
| Modéré | 10 |
| Élevé | 9 |
| Critique | 9 |
| **Non évaluable** | **35** |

**« Non évaluable » n'est PAS un niveau bas.** C'est un état distinct, attribué
aux marchés non scorables. Un marché dont on ne sait rien ne doit jamais
apparaître comme rassurant.

### 13.3 Score de priorité — la couche au-dessus (✅ nouveau)

**Fichier** : `ai/priority_score.py`

```text
priority_raw = 0,5 × anomaly_score_0_100  +  0,5 × red_flag_score
```

**Deux composantes seulement**, et c'est délibéré :

- La comparaison aux pairs **n'est pas un troisième terme** : elle alimente
  déjà RF03, donc `red_flag_score`. L'ajouter compterait deux fois le même
  signal.
- La qualité des données **n'entre pas dans le score** : elle **plafonne** le
  niveau. Sinon un marché bien documenté serait récompensé d'être bien
  documenté.

**Poids égaux, justifiés par une mesure** : la corrélation entre
`anomaly_score` et le nombre de red flags actifs vaut **+0,195** — les deux
signaux sont largement indépendants, donc tous deux informatifs, et aucun
n'est démontrablement supérieur.

Trois pondérations ont été comparées :

| Pondération | ρ de Spearman vs 50/50 | Top 20 communs |
|---|---:|---:|
| 50/50 (retenu) | 1,000 | 20/20 |
| 70/30 anomalie | 0,933 | 15/20 |
| 30/70 red flags | 0,969 | 14/20 |

Le classement est **robuste au choix du poids** — ce qui justifie de ne pas
sur-argumenter ce choix.

**Seuils de priorité** (quantiles mesurés) : P60 = 25,6 · P80 = 39,0 · P90 = 54,4

| Niveau de priorité | Marchés |
|---|---:|
| Très prioritaire | 26 |
| Prioritaire | 25 |
| À surveiller | 61 |
| Faible | 167 |
| Données insuffisantes | 35 |

**Le garde-fou** : une confiance faible interdit les deux niveaux hauts.
**5 marchés** auraient été classés prioritaires sur leur seul score mais sont
ramenés à « À surveiller ». Ils restent visibles avec leur score.

---

## 14. SHAP et explicabilité

> **État : ✅ implémenté aujourd'hui.** SHAP **n'existait pas** dans le projet
> avant le 28/08/2026 — ni import, ni dépendance. Le paquet `shap` (0.51.0) a
> été ajouté à `requirements.txt` et à `docker/spark.Dockerfile`.

**Fichier** : `ai/market_explain.py`

### 14.1 Implémentation

```python
import shap
explainer = shap.TreeExplainer(model)
values = explainer.shap_values(X, check_additivity=False)
return -np.asarray(values)   # inversion de signe
```

**Pourquoi l'inversion de signe** : la grandeur expliquée est la sortie brute
d'Isolation Forest, où **plus bas = plus anormal**. Sans inversion, une
contribution négative pousserait vers l'anomalie — l'inverse de la convention
du reste du projet. Après inversion, « plus haut = pousse vers l'atypique »
partout.

### 14.2 Ce que SHAP explique — et ce qu'il n'explique pas

| SHAP dit | SHAP ne dit pas |
|---|---|
| quelle feature fait que ce marché est isolé | que le marché est irrégulier |
| une **profondeur d'isolement** | une probabilité |
| le comportement du **modèle** | la réalité du marché |

Une feature mal extraite produira une explication SHAP parfaitement cohérente
d'un score parfaitement faux.

### 14.3 Contrôle par ablation — méthode indépendante

En plus de SHAP, le module neutralise chaque feature à la médiane de
population et remesure `decision_function`. Deux chemins indépendants pour la
même question.

**Accord mesuré sur le Top 3** : **0,607** de recouvrement moyen, accord
parfait sur **91/279** marchés. Un désaccord n'invalide ni l'une ni l'autre —
il signale un marché à lire avant de le commenter, et le dashboard l'affiche.

### 14.4 Importance moyenne des features (|SHAP| moyen)

| Feature | SHAP | Ablation |
|---|---:|---:|
| `mode_ao_ouvert` | 0,577 | 0,0096 |
| `nb_concurrents_ecartes` | 0,501 | 0,0098 |
| `exclusion_rate` | 0,446 | 0,0074 |
| `nb_soumissionnaires` | 0,442 | **0,0131** |
| `log_montant_ttc` | 0,282 | 0,0068 |
| `cat_fournitures` | 0,226 | 0,0054 |
| `has_exclusion_data` | 0,191 | — |
| `cat_services` | 0,161 | — |
| `cat_travaux` | 0,117 | 0,0056 |
| `has_amount_data` | 0,111 | 0,0065 |
| `mode_autre` | 0,078 | — |

> Les deux méthodes ne classent pas identiquement (SHAP place
> `mode_ao_ouvert` en tête, l'ablation `nb_soumissionnaires`). C'est attendu :
> elles mesurent des choses différentes.

### 14.5 Résultat notable

**0/279** marchés ont une valeur imputée dans leur Top 3 SHAP. Vérifié plutôt
que supposé : une valeur imputée vaut la médiane, elle ne distingue le marché
de personne et ne peut donc pas remonter dans les contributions principales.
C'est un contrôle qui passe, pas un calcul manquant.

---

## 15. Stockage PostgreSQL

> ### ⚠️ POINT LE PLUS IMPORTANT DE CETTE SECTION
>
> **Les résultats du Module 4 au grain MARCHÉ ne sont PAS en base.**
>
> Le schéma de référence indique `ML → PostgreSQL → FastAPI → Streamlit`.
> C'est vrai **uniquement pour l'ancien étage entreprise**. Les résultats
> marché produits aujourd'hui vont en **Parquet, lus directement par
> Streamlit**.

### 15.1 Tables réellement présentes

```text
procurements | documents | awards | companies | award_companies | risk_scores
```

**Aucune table `market_risk_scores`.** 📋 **Prévu**, pas implémenté.

### 15.2 Table `risk_scores` — grain ENTREPRISE

| Colonne | Type | Contenu |
|---|---|---|
| `id` | int | PK |
| `company_id` | int | FK → `companies.id`, **unique** |
| `anomaly_score` | float | sortie brute Isolation Forest |
| `final_score` | float | 0-100 |
| `risk_level` | enum | Faible / Modere / Eleve / Critique |
| `n_active_flags`, `n_evaluable_flags` | int | red flags entreprise |
| `active_flags` | text | libellés joints |
| `partially_evaluated` | bool | évaluation partielle |
| `dominant_driver` | text | `surtout_montant` / `comportement_et_montant` |
| `explanation` | text | phrase générée |
| `computed_at` | timestamp | horodatage |

**193 lignes, 193 `company_id` distincts.** Écrasée en bloc à chaque
rechargement (`scripts/load_risk_scores.py`).

### 15.3 Sorties Parquet du Module 4 — le vrai stockage

| Fichier | Lignes × colonnes | Produit par |
|---|---|---|
| `market_data_quality.parquet` | 454 × 13 | `features/data_quality.py` |
| `market_anomaly_scores.parquet` | 314 × 49 | `ai/train_market_model.py` |
| `market_peer_comparison.parquet` | 314 × 12 | `ai/market_peer_analysis.py` |
| `market_red_flags.parquet` | 314 × 20 | `ai/market_red_flags.py` |
| `market_explanations.parquet` | 279 × 7 | `ai/market_explain.py` |
| `market_priority.parquet` | 314 × 21 | `ai/priority_score.py` |
| `market_temporal.parquet` | 4 × 14 | `ai/market_temporal_analysis.py` |
| `acheteur_network.parquet` | 128 × 12 | `ai/network_analysis.py` |
| `benchmark_rulebased.parquet` | 279 × 6 | `ai/benchmark_rulebased.py` |

Plus 6 fichiers JSON de paramètres mesurés (`contamination_study.json`,
`red_flag_thresholds.json`, `priority_report.json`, etc.).

Tous joints sur **`award_id`**.

---

## 16. API FastAPI

> **État : 🟡 l'API ne sert QUE l'ancien étage entreprise.** Aucun endpoint ne
> renvoie un résultat au grain marché.

**Fichier** : `api/main.py` — lecture seule stricte, aucun POST/PUT/DELETE.

| Méthode | Endpoint | Grain | Réponse |
|---|---|---|---|
| GET | `/` | — | statut + disclaimer |
| GET | `/companies` | entreprise | liste avec `final_score`, `risk_level` |
| GET | `/companies/ranking?limit&offset` | entreprise | classement paginé |
| GET | `/companies/{id}` | entreprise | détail + attributions |
| GET | `/awards/{id}` | marché | détail d'une attribution (**sans score**) |
| GET | `/stats/summary` | global | comptages + distribution des niveaux |

Sans authentification — décision de périmètre assumée (`api/auth/` est un
dossier vide).

📋 **Prévu** : `GET /markets`, `GET /markets/{award_id}`, `GET /markets/ranking`.

---

## 17. Dashboard Streamlit

**Trois applications distinctes**, toutes en lecture directe des Parquet.

| Fichier | Rôle | État |
|---|---|---|
| `dashboard/validation_app.py` | **Validation-seule** — 3 pages : Vue générale, Marchés publics, Marchés atypiques | ✅ créé aujourd'hui |
| `dashboard/app.py` | Démonstration — 7 onglets, marché + entreprise + analyses | ✅ |
| `dashboard/test_dashboard.py` | État du pipeline — fraîcheur des artefacts, recoupements | ✅ |

Modules de rendu : `market_view.py` (liste + détail), `analyses_view.py`
(temporel, réseau, benchmark, feedback), `feedback.py` (avis analyste).

**Règles d'affichage appliquées partout :**

- une valeur absente affiche « Non disponible », **jamais 0** ;
- un marché non scorable affiche « Données insuffisantes », **jamais Faible** ;
- un red flag non évaluable est distinct d'un red flag inactif ;
- un montant imputé est marqué comme tel.

**Lancement** :

```bash
streamlit run dashboard/validation_app.py     # version de validation
streamlit run dashboard/app.py                # démonstration
streamlit run dashboard/test_dashboard.py     # état du pipeline
```

---

## 18. Exemple complet de bout en bout

> ⚠️ **Valeurs illustratives** — construites pour montrer le mécanisme. Les
> paramètres (seuils, médianes, formules) sont, eux, les vrais.

```text
MARCHÉ FICTIF « M-DEMO » — travaux, AO ouvert, 2025

[1] DONNÉES REÇUES DU MODULE 3
    montant_ttc            = 14 000 000 DH
    nb_soumissionnaires    = 1
    nb_concurrents_ecartes = 2
    exclusion_rate         = 2,0        ← 2 écartés / 1 soumissionnaire
    date_ouverture_plis    = NULL
    companies              = ["ENTREPRISE ALPHA"]

[2] DATA QUALITY — 4 états
    montant      KNOWN     ✓
    concurrents  KNOWN     ✓
    exclusions   INVALID   ⚠  (taux > 1 : arithmétiquement impossible)
    date         UNKNOWN   ?
    gagnant      KNOWN     ✓
    → known=3, unknown=1, invalid=1, dénominateur=5
    → data_quality_score = 100 × 3/5 = 60,0 → niveau « Moyen »

[3] POPULATION
    statut = ATTRIBUE                    ✓ retenu
    data_completeness = 3/3              ✓ ≥ 2 → scorable

[4] FEATURES (11 colonnes)
    log_montant_ttc     = log1p(14 000 000) = 16,45
    nb_soumissionnaires = 1
    nb_concurrents_ecartes = 2
    exclusion_rate      = 2,0
    has_amount_data = 1 · has_exclusion_data = 1
    mode_ao_ouvert = 1 · mode_autre = 0
    cat_travaux = 1 · cat_fournitures = 0 · cat_services = 0

[5] ISOLATION FOREST  (200 arbres, contamination=0,10, random_state=42)
    decision_function → −0,072
    predict           → −1  (signalé)

[6] RISK SCORE
    100 × (0,1725 − (−0,072)) / (0,1725 − (−0,0998)) = 89,8

[7] NIVEAU DE RISQUE
    89,8 > 86,5 → « Critique »

[8] RED FLAGS
    RF01 Faible concurrence   ACTIF        (1 soumissionnaire, état KNOWN)
    RF02 Exclusions           NON ÉVALUABLE (taux 2,0 impossible → INVALID)
    RF03 Montant atypique     ACTIF        (14 M ≥ 11 746 666 DH)
    RF05 Procédure rare       INACTIF      (AO ouvert = 74,5 % du corpus)
    RF06 Signaux multiples    ACTIF        (2 primaires actifs)
    → red_flag_score = 100 × (3+2) / (3+2+1) = 83,3

[9] COMPARAISON AUX PAIRS
    groupe « TRAVAUX × AO ouvert × 2025 », 41 comparables
    médiane des pairs = 620 000 DH → ratio 22,6×, percentile 1,00

[10] PRIORITÉ
    priority_raw = 0,5 × 89,8 + 0,5 × 83,3 = 86,6
    86,6 ≥ P90 (54,4) → « Très prioritaire »
    confiance : DQ 60 → « Moyenne » → PAS de plafond
    → priority_level = « Très prioritaire »

[11] SHAP  (Top 3)
    log_montant_ttc     ████████  +0,31
    nb_soumissionnaires █████     +0,19
    exclusion_rate      ███       +0,11

[12] STOCKAGE
    market_priority.parquet, market_red_flags.parquet, etc.
    ⚠️ PAS en PostgreSQL — pas de table marché

[13] RESTITUTION
    Streamlit lit les Parquet → l'analyste voit :
      « Très prioritaire · score 89,8 · Data Quality 60/100 —
        2 red flags actifs · exclusions non évaluables (donnée incohérente) »
```

---

## 19. CE QUI A CHANGÉ AUJOURD'HUI

### 19.1 Changement structurant — l'unité d'analyse

```text
AVANT
  Les marchés étaient agrégés par entreprise. Le modèle notait 193 entreprises
  avec des features comportementales (single_bidder_rate, number_of_awards,
  market_share, groupement_rate, pentes de tendance).

PROBLÈME MESURÉ
  180 des 193 entreprises (93,3 %) n'ont qu'UN SEUL marché dans le corpus.
  13 en ont deux. AUCUNE n'en a trois.
  Un « taux » sur une observation unique n'est pas un taux :
  single_bidder_rate = 1/1 = 100 % recopie une observation en la déguisant
  en fréquence.

  Et la conséquence était visible dans les sorties :
      entreprises à 1 marché  :  25/180 signalées (13,9 %)
      entreprises à 2 marchés :  13/13  signalées ( 100 %)

  Le modèle apprenait la PROFONDEUR DE PRÉSENCE DANS LE CORPUS — un artefact
  de couverture du scraping (nous avons collecté ~100 PV/an, pas l'historique
  complet d'une entreprise), pas un comportement.

MODIFICATION
  Bascule au grain MARCHÉ. Chaque marché est une observation complète et
  indépendante : montant, soumissionnaires, procédure et exclusions sont lus
  sur UN document.

APRÈS
  279 marchés scorés sur 314 attribués. 11 features, aucune agrégation par
  entreprise. L'information entreprise reste affichée (le gagnant) mais ne
  pilote plus rien.

POURQUOI
  Un modèle qui apprend un artefact de collecte produit des résultats
  indéfendables en soutenance.
```

### 19.2 Correctif de données — UNKNOWN ≠ ZERO

```text
AVANT
  extraction/fields.py::_bulleted_names() renvoyait [] dans DEUX cas
  distincts : rubrique absente du document, et rubrique présente ne nommant
  personne.

PROBLÈME MESURÉ
  77 marchés sans rubrique concurrents étaient comptés « 0 soumissionnaire »,
  donc single_bidder = 1. Un trou d'extraction devenait un signal de risque.
  Même défaut sur les exclusions : 135 marchés.

MODIFICATION — trois endroits en chaîne
  1. extraction/fields.py    : None si la rubrique est absente, [] si vide
  2. database/crud/awards.py : `or None` supprimé — [] n'est plus écrasé
  3. bigdata/.../build_statistics.py : NULL propagé, plus de coalesce(...,0)

APRÈS
  liste_concurrents : 107 « zéros » → 77 inconnus + 30 zéros réellement
  observés. concurrents_ecartes : 239 → 135 + 105.

POURQUOI
  Ne pas savoir et savoir qu'il n'y a rien sont deux informations
  différentes. Les confondre fabrique du signal à partir de nos propres
  lacunes.
```

### 19.3 RF01 comptait des défauts d'extraction

```text
AVANT
  RF01 « faible concurrence » : nb_soumissionnaires <= 1.

PROBLÈME MESURÉ
  Or 0 <= 1. Sur 152 RF01 actifs, 56 (37 %) venaient d'un marché ATTRIBUÉ où
  AUCUN nom n'avait pu être lu — dont 35 où des noms figuraient dans le
  document mais avaient tous été rejetés par le filtre de plausibilité.
  Un marché ne peut pas être attribué à personne.

MODIFICATION
  features/data_quality.py marque ces marchés INVALID sur la dimension
  concurrents. RF01 lit cet état et devient NON ÉVALUABLE.

APRÈS
  RF01 : 152 → 96 actifs, 70 non évaluables. Vérifié : 0 des 56 marchés
  INVALID ne déclenche RF01.

POURQUOI
  Perte de signal apparent, gain d'exactitude.
```

### 19.4 Le modèle marché détectait les trous d'extraction

```text
AVANT (première version du modèle marché, jamais livrée telle quelle)
  Les marchés les plus « atypiques » du Top 10 étaient ceux dont on ne savait
  rien.

PROBLÈME MESURÉ
  0 information connue :   7 marchés →  7 signalés (100 %)
  3 informations       : 128 marchés →  8 signalés (6,3 %)
  Corrélation score / complétude : −0,249.

MODIFICATION
  Porte de complétude MIN_DATA_COMPLETENESS = 2. Les marchés sous ce seuil
  reçoivent scorable=False et AUCUN score.

APRÈS
  Corrélation ramenée à +0,063. 35 marchés sortis de l'analyse, comptés et
  affichés comme « données insuffisantes ».

POURQUOI
  Signaler un marché parce que notre extraction a échoué revient à
  sanctionner un défaut de notre propre chaîne.
```

### 19.5 Autres changements (tableau)

| Élément | Avant | Maintenant | Pourquoi |
|---|---|---|---|
| **SHAP** | ❌ inexistant | `ai/market_explain.py` + ablation | Explicabilité exigée ; SHAP seul n'était pas contrôlable |
| **`contamination`** | `"auto"` (19,7 % au niveau entreprise) | `0.10`, après comparaison de 4 valeurs | `"auto"` ne répond à aucune question métier |
| **Features mortes** | `groupement_rate` (2/193 non nuls), 2 pentes + `has_trend_data` (3/193) | supprimées à la source | Support trop faible ; imputer à 0 affirmait « tendance plate mesurée » pour 98,4 % du corpus |
| **Colonne constante** | non détectée | `drop_constant_features()` | `has_competitor_data` sortait à importance SHAP **exactement 0** |
| **Colonne redondante** | non détectée | `drop_redundant_features()` (r ≥ 0,95) | `mode_ao_simplifie` r = 0,971 avec `mode_ao_ouvert` |
| **Seuil RF02** | quantile 0,90 | quantile 0,80 | q0,90 valait **exactement 1,000** — seuil dégénéré |
| **RF05 / RF06** | RF05 = « signaux multiples » | RF05 = procédure rare, RF06 = signaux multiples | Collision de numérotation |
| **Comptage des flags** | RF « combinaison » se comptait lui-même | flags primaires seulement | Aucun marché n'affichait exactement 2 flags (saut de 1 à 3) |
| **RF03** | quantile du corpus entier | P90 **de ses pairs**, repli corpus tracé | « Gros » n'a de sens que par rapport à des marchés comparables |
| **Statut OCR des exclus** | `ocr_status = NULL` | `EXCLUDED` + raison en base | NULL était indistinguable d'un fichier non traité |
| **`NEANT_RE`** | motif ancré, échouait sur « - Néant » | tolère puce et ponctuation | 2 marchés classés ATTRIBUÉ à tort |
| **Contrôle 454** | `if n_awards != 454: raise` | lecture en base | Constante périmable — le motif que `counts.py` élimine |
| **Priority Score** | ❌ inexistant | 0,5/0,5 + plafond de confiance | Le projet produisait des scores, pas une priorisation |
| **Data Quality** | ❌ inexistant | 5 dimensions × 4 états | Distinguer « on ne sait pas » de « il n'y a rien » |

---

## 20. Pourquoi ces changements ?

### 20.1 Bascule entreprise → marché

```text
Décision       : changer l'unité d'analyse
Problème       : 93,3 % des entreprises n'ont qu'un marché ; le modèle
                 signalait 100 % des entreprises à 2 marchés
Solution       : une observation = un marché
Alternative    : collecter plus de PV pour densifier l'historique entreprise
Pourquoi notre : la collecte représente des semaines de scraping et le portail
  solution       ne garantit pas la profondeur ; le marché est déjà une
                 observation complète
Impact         : 193 observations → 279 ; toutes les features entreprise
                 supprimées ; l'API et la table risk_scores deviennent
                 l'ancien étage
```

### 20.2 Porte de complétude plutôt que score pour tous

```text
Décision       : ne pas scorer 35 marchés
Problème       : le modèle isolait les marchés vides (100 % de signalement)
Solution       : exiger ≥ 2 informations sur 3
Alternatives   : (a) scorer tout et avertir ; (b) imputer davantage
Pourquoi notre : (a) laisse un score faux en tête de liste ; (b) fabrique de
  solution       la donnée. Ne pas scorer est le seul choix qui ne ment pas
Impact         : −11,1 % de couverture, corrélation −0,249 → +0,063
```

### 20.3 Qualité des données en plafond, jamais en bonus

```text
Décision       : la qualité ne rentre pas dans le score
Problème       : un marché très atypique dont on ne sait rien remonterait
                 en tête, porté par ce qu'on ignore
Solution       : confidence_level plafonne le niveau ; le score reste visible
Alternative    : multiplier le score par la qualité
Pourquoi notre : multiplier récompenserait les marchés bien documentés et
  solution       créerait un score inintelligible
Impact         : 5 marchés ramenés de « prioritaire » à « à surveiller »
```

### 20.4 Poids égaux dans le Priority Score

```text
Décision       : 0,5 / 0,5
Problème       : aucune donnée ne justifie d'avantager une composante
Solution       : poids égaux + comparaison de 3 pondérations
Alternative    : pondérer selon la littérature (Fazekas)
Pourquoi notre : le corpus est trop petit pour ré-estimer des poids ; et les
  solution       3 pondérations donnent ρ ≥ 0,93 — le choix change peu
Impact         : décision robuste et défendable, documentée par la mesure
```

---

## 21. Fichiers modifiés / ajoutés

### 21.1 Module 4 — nouveaux

| Fichier | Statut | Rôle |
|---|---|---|
| `features/__init__.py` | Nouveau | paquet de lectures dérivées |
| `features/data_quality.py` | Nouveau | 4 états, score 0-100, 5 dimensions |
| `ai/train_market_model.py` | Nouveau | Isolation Forest marché, stabilité, contamination |
| `ai/market_red_flags.py` | **Réécrit** | registre de 5 règles (était une liste de fonctions) |
| `ai/market_peer_analysis.py` | Nouveau | cascade de groupes comparables |
| `ai/market_explain.py` | Nouveau | SHAP + ablation |
| `ai/priority_score.py` | Nouveau | score de priorité + confiance |
| `ai/market_temporal_analysis.py` | Nouveau | agrégats annuels |
| `ai/network_analysis.py` | Nouveau | concentration par acheteur |
| `ai/benchmark_rulebased.py` | Nouveau | comparaison à une méthode simple |
| `ai/models/market_feature_columns.json` | Nouveau | ordre des colonnes du modèle |

### 21.2 Module 4 — modifiés

| Fichier | Modification |
|---|---|
| `ai/train_isolation_forest.py` | **Déprécié** ; 4 features mortes retirées ; imputation + drapeaux sur les taux |
| `ai/scoring.py`, `ai/risk_score.py` | inchangés — ancien étage entreprise |

### 21.3 Amont (Modules 2 et 3) — modifiés

| Fichier | Modification |
|---|---|
| `extraction/fields.py` | `_bulleted_names()` → tri-état |
| `extraction/extractor.py` | `liste_concurrents`/`concurrents_ecartes` : `None` par défaut |
| `extraction/patterns.py` | `NEANT_RE` tolère puce et ponctuation |
| `database/crud/awards.py` | `or None` supprimé |
| `database/crud/documents.py` | statut `EXCLUDED` + raison |
| `database/models/document.py` | enum `EXCLUDED` + colonne `ocr_excluded_reason` |
| `ocr/exclusions.py` | **Nouveau** — source unique des exclusions |
| `scripts/run_ocr.py` | importe `ocr/exclusions.py` |
| `bigdata/.../build_statistics.py` | tri-état + `has_competitor_data` + retrait du 454 en dur |
| `bigdata/.../build_features.py` | pentes et `groupement_rate` retirés |
| `bigdata/.../build_market_features.py` | **Nouveau** — features marché |

### 21.4 Restitution — nouveaux / modifiés

| Fichier | Statut |
|---|---|
| `dashboard/validation_app.py` | Nouveau — version de validation, 3 pages |
| `dashboard/market_view.py` | Nouveau puis enrichi — liste + détail |
| `dashboard/analyses_view.py` | Nouveau — temporel, réseau, benchmark, feedback |
| `dashboard/feedback.py` | Nouveau — avis analyste (CSV versionné) |
| `dashboard/app.py` | Modifié — onglets marché |
| `dashboard/test_dashboard.py` | **Réécrit** — état du pipeline, fraîcheur des artefacts |
| `scripts/report_refonte.py` | Nouveau — rapport auto-généré |
| `docs/refonte_marche.md` | Nouveau — **aucun chiffre en dur** |
| `requirements.txt`, `docker/spark.Dockerfile` | Modifiés — ajout de `shap` |

### 21.5 Tests — nouveaux

`tests/test_unknown_vs_zero.py` · `test_data_quality.py` ·
`test_market_red_flags.py` (réécrit) · `test_peer_analysis.py` ·
`test_priority_score.py` · `test_feedback.py` ·
`test_temporal_network_benchmark.py`

---

## 22. Paramètres importants

| Paramètre | Valeur | Fichier | Nature |
|---|---|---|---|
| `n_estimators` | 200 | `train_market_model.py` | fixé |
| `contamination` | **0.10** | `train_market_model.py` | choisi après étude |
| `random_state` | 42 | `train_market_model.py` | reproductibilité |
| `MIN_DATA_COMPLETENESS` | **2** | `train_market_model.py` | **mesuré** |
| `STABILITY_SEEDS` | 0-9 | `train_market_model.py` | fixé |
| `STABILITY_TOP_N` | 20 | `train_market_model.py` | fixé |
| seuil de redondance | 0,95 | `train_market_model.py` | fixé |
| `EXCLUSION_RATE_QUANTILE` | **0,80** | `market_red_flags.py` | **mesuré** |
| `MONTANT_QUANTILE` | 0,95 | `market_red_flags.py` | fixé |
| `PROCEDURE_RARE_MAX_SHARE` | 0,05 | `market_red_flags.py` | sans effet (bimodal) |
| poids de sévérité | 3 / 2 / 1 | `market_red_flags.py` | **éditorial**, non mesuré |
| `MIN_PEERS` | 10 | `market_peer_analysis.py` | fixé |
| `MIN_PEERS_PER_DIMENSION` | 10 | `market_peer_analysis.py` | fixé |
| `W_ANOMALY` / `W_RED_FLAGS` | 0,5 / 0,5 | `priority_score.py` | justifié par mesure |
| seuils de priorité | P60/P80/P90 | `priority_score.py` | **mesurés** |
| seuils Data Quality | 90 / 75 / 50 | `data_quality.py` | **vérifiés** sur la distribution |
| `MAX_YEAR_GAP` | 1 an | `data_quality.py` | mesuré (1 cas à 7 ans) |
| `TOP_K` SHAP | 3 | `market_explain.py` | fixé |

---

## 23. Tests et validation

### 23.1 Suite automatisée — ✅ 160 tests passent

```bash
python -m pytest tests scraper/tests -q
# 160 passed
```

| Fichier | Tests | Ce qu'il verrouille |
|---|---:|---|
| `test_company_name.py` | 24 | isolation du nom d'entreprise |
| `test_extraction.py` | 18 | extraction des champs |
| `test_market_red_flags.py` | 18 | tri-état, RF01 corrigé, vocabulaire interdit |
| `test_temporal_network_benchmark.py` | 13 | effectifs, refus du mensuel, refus du volet entreprise |
| `test_data_quality.py` | 11 | 4 états, NOT_APPLICABLE hors dénominateur |
| `test_normalization.py` | 10 | normalisation des noms |
| `test_feedback.py` | 9 | feedback sans boucle de retour |
| `test_priority_score.py` | 9 | plafond de confiance, pas de double comptage |
| `test_peer_analysis.py` | 7 | exclusion de soi, double minimum |
| `test_unknown_vs_zero.py` | 6 | les trois états de bout en bout |
| `test_statistics.py` | 3 | UNKNOWN ≠ ZERO dans Spark |
| `test_consultation_parser.py` | 32 | parser HTML |

### 23.2 Exécutions réelles de la chaîne

| Étape | Résultat |
|---|---|
| `build_analytics_dataset` | 455 lignes, recoupement confirmé |
| `build_statistics` | 454 Award, contrôles OK (**lus en base**) |
| `build_market_features` | 454 marchés, couverture affichée |
| `train_market_model` | 279 scorés, 28 signalés, Jaccard 0,81 |
| `market_peer_analysis` | 314 groupes, 0 `NOT_ENOUGH_PEERS` |
| `market_red_flags` | 314 marchés, seuils mesurés |
| `market_explain` | SHAP 279 × 11, accord 0,607 |
| `priority_score` | 4 niveaux + 35 non évaluables |

### 23.3 Vérifications ciblées

| Vérification | Résultat |
|---|---|
| Cohérence Data Quality ↔ RF01 | 56 marchés INVALID → **0 RF01 actif** ✅ |
| UNKNOWN ≠ ZERO en base | 77 NULL / 30 `[]` / 347 remplis ✅ |
| Non scorable ≠ Faible | les 35 sont tous « Données insuffisantes » ✅ |
| Aucun montant à 0 fabriqué | 172 cellules vides, aucune à 0 ✅ |
| Dashboards headless | 0 exception sur les 3 applications ✅ |
| Corrélation score / complétude | −0,249 → **+0,063** ✅ |

### 23.4 Non vérifié

| Élément | État |
|---|---|
| Sélection de ligne + filtres du dashboard | ⚠️ testés au niveau des fonctions, **pas par clic simulé** |
| Endpoints API après la refonte | ⚠️ **Non vérifié** depuis le rechargement |
| Valeurs infinies dans X | ⚠️ aucun contrôle explicite |
| Marché à ratio 504× la médiane de ses pairs | ⚠️ **jamais ouvert dans le PV source** |
| Pertinence métier des red flags | ⚠️ aucun avis analyste enregistré |

---

## 24. Limites actuelles

**24.1 Anomalie ≠ fraude.** Le modèle mesure une rareté statistique dans CE
corpus. Un marché isolé peut l'être pour des raisons régulières.

**24.2 Aucune vérité terrain.** Aucun marché n'est étiqueté. Nous ne pouvons
mesurer ni précision, ni rappel. **Ne jamais annoncer un taux de détection.**

**24.3 Qualité des données — la limite dominante.**

```text
montant TTC absent          : 287/454  (63,2 %)
gagnant non identifié       : 249/454  (54,8 %)
estimation                  : 454/454  (100 %)
date d'ouverture absente    : 142/454  (31,3 %)
rubrique concurrents absente:  77/454  (17,0 %)
```

**24.4 Faux positifs.** `contamination = 0,10` **impose** 28 marchés signalés,
qu'ils soient atypiques ou non. C'est une charge d'analyse, pas une mesure.

**24.5 Dépendance aux features.** 11 colonnes, dont 5 de contexte (procédure,
secteur). Le signal repose largement sur 4 grandeurs.

**24.6 Data leakage — analysé, non automatisé.** Toutes les features viennent
du PV, donc **postérieures à l'attribution**. Ce n'est pas du leakage pour
notre usage (priorisation rétrospective). Risque plus subtil : `has_amount_data`
et `has_exclusion_data` décrivent la qualité de **notre extraction**, pas le
marché — la porte de complétude en neutralise l'essentiel (+0,063), mais elles
restent des entrées.

**24.7 SHAP explique le modèle, pas le monde.** Une feature mal extraite
produira une explication cohérente d'un score faux.

**24.8 Comparaison aux pairs peu couverte.** 67/314 sur le montant.

**24.9 Bornes du score relatives au corpus.** 0 et 100 se déplacent si le
corpus change.

**24.10 Couverture temporelle.** 4 années, dont **2026 tronquée** (collecte
arrêtée en août). Analyse mensuelle refusée (médiane 4 marchés/mois).

**24.11 Limites du scraping.** ~100 PV/an, pas l'exhaustivité. C'est cette
faible profondeur qui a rendu l'étage entreprise inexploitable.

**24.12 Bruit résiduel sur les noms.** Audit du 27/08 : 8,8 % de bruit pur,
7,4 % de noms contaminés. N'affecte plus le modèle (l'entreprise n'est plus
l'unité) mais affecte l'affichage du gagnant.

**24.13 Le benchmark ne tranche pas.** Isolation Forest et la méthode simple
se recoupent à **Jaccard 0,081** sur le Top 20 (ρ = +0,154) : le choix de la
méthode détermine presque entièrement quels marchés remontent, et rien ne
permet de dire laquelle a raison.

---

## 25. Ce qui reste à faire

| Priorité | Tâche | Détail |
|---|---|---|
| **1** | **Committer** | Rien n'est committé. ~20 fichiers modifiés, ~20 nouveaux, sur `fix/company-name-extraction` |
| 2 | Table `market_risk_scores` | Les résultats marché ne sont pas en base |
| 3 | Endpoints API marché | `/markets`, `/markets/{id}`, `/markets/ranking` |
| 4 | Vérifier le marché à 504× | Ouvrir le PV source |
| 5 | Ablation de features | Seul manque de la validation renforcée |
| 6 | Collecter des avis analystes | Aucun enregistré |
| 7 | Contrôle des valeurs infinies | Absent de `prepare_market_matrix()` |
| 8 | Dashboard final | La version actuelle est une validation |

---

## 26. Résumé pour le binôme

**Si tu ne lis qu'une chose, lis ceci.**

1. **L'unité d'analyse a changé** : le modèle note des **marchés**, plus des
   entreprises. Parce que 93,3 % des entreprises n'ont qu'un seul marché et
   que le modèle apprenait la profondeur du corpus, pas un comportement.

2. **Le module ne dit jamais « fraude »**. Il dit : ce marché est atypique par
   rapport aux autres, voici les signaux nommés, voici ce que nous savons
   vraiment de lui.

3. **Trois chiffres à retenir** : 454 marchés au corpus · 279 scorés ·
   28 signalés.

4. **Une donnée absente n'est jamais un zéro.** Quatre états
   (KNOWN / UNKNOWN / INVALID / NOT_APPLICABLE) traversent toute la chaîne.

5. **« Données insuffisantes » n'est pas « risque faible ».** 35 marchés ne
   sont pas scorés parce que nous n'en savons pas assez.

6. **Les résultats marché ne sont PAS en PostgreSQL.** Parquet → Streamlit.
   L'API et la table `risk_scores` servent l'ancien étage entreprise.

7. **Tous les seuils sont mesurés**, jamais choisis à l'intuition — et
   régénérés à chaque exécution.

8. **160 tests passent.** Ils verrouillent surtout les défauts déjà corrigés,
   pour qu'ils ne reviennent pas.

**Pour reprendre demain** :

```bash
# voir l'état de la chaîne
streamlit run dashboard/test_dashboard.py

# voir les résultats
streamlit run dashboard/validation_app.py

# rejouer le Module 4 (image Docker ppi-spark)
docker run --rm -v "D:/public-procurement-intelligence:/app" -w /app ppi-spark \
  sh -c "python -m features.data_quality && python -m ai.train_market_model && \
         python -m ai.market_peer_analysis && python -m ai.market_red_flags && \
         python -m ai.market_explain && python -m ai.priority_score"

# rapport chiffré auto-généré
python scripts/report_refonte.py --markdown docs/refonte_marche.md
```

---

## CHANGELOG — SESSION DU 28/08/2026

### Ajouté

- `features/data_quality.py` — Data Quality Score, 4 états, 5 dimensions
- `ai/train_market_model.py` — Isolation Forest au grain marché
- `ai/market_peer_analysis.py` — comparaison aux marchés comparables
- `ai/market_explain.py` — **SHAP** (n'existait pas) + contrôle par ablation
- `ai/priority_score.py` — score de priorité + niveaux + confiance
- `ai/market_temporal_analysis.py` — agrégats annuels
- `ai/network_analysis.py` — concentration par acheteur
- `ai/benchmark_rulebased.py` — comparaison à une méthode simple
- `bigdata/spark/jobs/build_market_features.py` — features marché
- `ocr/exclusions.py` — source unique des documents exclus
- `dashboard/validation_app.py`, `market_view.py`, `analyses_view.py`, `feedback.py`
- `scripts/report_refonte.py` + `docs/refonte_marche.md`
- 7 fichiers de tests (+70 tests)
- `shap` dans `requirements.txt` et `docker/spark.Dockerfile`
- RF05 (procédure rare), RF06 (signaux multiples)
- Colonne `ocr_excluded_reason`, valeur d'enum `EXCLUDED`

### Modifié

- `ai/train_isolation_forest.py` — **déprécié**, 4 features mortes retirées
- `ai/market_red_flags.py` — **réécrit** en registre de règles
- `extraction/fields.py`, `extractor.py`, `patterns.py` — tri-état, `NEANT_RE`
- `database/crud/awards.py`, `documents.py`, `models/document.py`
- `bigdata/.../build_statistics.py`, `build_features.py`
- `dashboard/app.py`, `test_dashboard.py` (réécrit)
- `contamination` : `"auto"` → `0.10`
- Seuil RF02 : quantile 0,90 → 0,80

### Supprimé

- `groupement_rate`, `single_bidder_rate_trend_slope`,
  `number_of_awards_trend_slope`, `has_trend_data` — support 2 à 3 sur 193
- Le contrôle `if n_awards_total != 454: raise`
- `has_competitor_data` et `mode_ao_simplifie` du modèle (automatique)

### Corrigé

- **UNKNOWN ≠ ZERO** en trois endroits (77 + 135 marchés concernés)
- **RF01** comptait 56 défauts d'extraction sur 152 déclenchements (37 %)
- **Le modèle détectait les trous d'extraction** (corrélation −0,249 → +0,063)
- **Seuil RF02 dégénéré** (quantile 0,90 = exactement 1,000)
- **RF06 se comptait lui-même** (aucun marché n'affichait 2 flags)
- **2 statuts ATTRIBUÉ à tort** (« - Néant » non reconnu)
- **2 documents à `ocr_status` NULL** → `EXCLUDED` + raison
- **Plafond de confiance trop large** : 264/314 marchés (84 %) plafonnés à
  tort — `stability_frequency == 0` traité comme instabilité alors qu'il
  signifie « jamais entré dans un Top 20 ». Ramené à 5 marchés.
- Plantage du dashboard sur `risk_scores` vide (KeyError)
- `.gitignore` corrompu en UTF-16 par un `>>` PowerShell

### Refactorisé

- Red flags : fonctions dispersées → registre `RedFlag(...)`
- Exclusions OCR : constante dans `scripts/` → `ocr/exclusions.py`
- Dashboard : onglets monolithiques → modules de rendu séparés
- Contrôles de volumétrie : constantes → lecture en base

### Décisions prises

- Marché comme unité d'analyse (mesure : 93,3 % à un seul marché)
- Ne pas scorer les marchés à moins de 2 informations sur 3
- Qualité des données en **plafond**, jamais en bonus
- Poids égaux dans le Priority Score (3 pondérations comparées, ρ ≥ 0,93)
- RF04 non implémenté (estimation 0/454)
- Volet entreprise du réseau refusé (degré max = 2)
- Analyse mensuelle refusée (médiane 4 marchés/mois)
- Feedback analyste sans boucle de retour vers le modèle
- Sévérités des red flags : éditoriales, jamais présentées comme mesurées

### À vérifier

- Sélection de ligne et filtres du dashboard (par clic réel)
- Endpoints API après le rechargement de la base
- Le marché à ratio 504× la médiane de ses pairs (ouvrir le PV)
- Valeurs infinies dans la matrice X

### À faire ensuite

1. **Committer** — rien ne l'est
2. Table `market_risk_scores` + endpoints API marché
3. Ablation de features (validation renforcée)
4. Collecter des avis analystes
5. Dashboard final
