# Rapport de refonte — de l'entreprise au marché (28/08/2026)

> Genere par `scripts/report_refonte.py`. Tous les chiffres sont relus depuis les artefacts, aucun n'est ecrit en dur.

## 1. Unité d'analyse

| | Avant | Après |
|---|---|---|
| Observation | 1 entreprise | 1 marché (Award, = 1 lot) |
| Population | 193 entreprises | 454 marchés dont 314 attribués |
| Observations modélisées | 193 | 279 |

**Pourquoi la bascule** — profondeur du corpus par entreprise :

- 180 entreprises avec 1 marché(s) (93.3 %)
- 13 entreprises avec 2 marché(s) (6.7 %)

Taux de signalement de l'ancien modèle selon cette profondeur :

- 1 marché(s) : 25/180 signalées (13.9 %)
- 2 marché(s) : 13/13 signalées (100.0 %)

Le modèle apprenait la profondeur de présence dans le corpus, un artefact de couverture du scraping.

## 2. Features

- Avant : **9** colonnes d'entrée — `number_of_awards, single_bidder_rate, groupement_rate, concurrents_ecartes_rate, total_amount_ttc, has_ttc_data, single_bidder_rate_trend_slope, number_of_awards_trend_slope, has_trend_data`
- Après : **11** colonnes d'entrée — `log_montant_ttc, nb_soumissionnaires, nb_concurrents_ecartes, exclusion_rate, has_amount_data, has_exclusion_data, mode_ao_ouvert, mode_autre, cat_travaux, cat_fournitures, cat_services`

**Features retirées, et leur support mesuré avant retrait :**

| Feature | Support | Décision |
|---|---|---|
| `single_bidder_rate_trend_slope` | 3/193 renseignés | retirée |
| `number_of_awards_trend_slope` | 3/193 renseignés | retirée |
| `groupement_rate` | 2/193 non nuls | retirée |

`price_ratio` / `price_deviation` n'ont **pas** été créées : `estimation_dhs_ttc` est absente de 100 % des marchés liés à un Award (0/454), alors qu'elle est présente sur 1196/1350 consultations de la Passe B. La page d'un marché déjà attribué ne porte plus son estimation. Aucune valeur n'a été fabriquée.

## 3. Valeurs manquantes — UNKNOWN ≠ ZERO

Taux de renseignement réel, au grain marché :

| Information | Renseignée | Part |
|---|---:|---:|
| Montant TTC | 167/454 | 36.8 % |
| Liste des concurrents | 377/454 | 83.0 % |
| Concurrents écartés | 319/454 | 70.3 % |
| Date d'ouverture | 312/454 | 68.7 % |
| Gagnant identifié | 205/454 | 45.2 % |

**Effet direct du correctif** : 77 marchés sans rubrique concurrents valaient auparavant « 0 soumissionnaire », donc `single_bidder = 1`. Après correctif, ils valent NULL et **200** marchés seulement portent un soumissionnaire unique réellement observé — contre 277 avant.

## 3bis. Data Quality Score (Phase 1)

Mesure **ce que nous savons d'un marché**, jamais ce que ce marché vaut. Affiché à côté du score d'anomalie, jamais additionné avec lui.

- Dimensions notées : `montant`, `concurrents`, `exclusions`, `date`, `gagnant`
- Dimensions écartées car renseignées à 100 % (elles donneraient le même plancher à tous) : `mode_passation`, `categorie_principale`, `annee`, `objet`, `acheteur_public`, `ref_consultation`
- Dimensions impossibles : `estimation` (0/454), `localisation` (absente de la table de faits)

**Quatre états, pas deux** — répartition mesurée :

| Dimension | KNOWN | UNKNOWN | INVALID | N/A |
|---|---:|---:|---:|---:|
| `montant` | 167 | 287 | 0 | 0 |
| `concurrents` | 321 | 77 | 56 | 0 |
| `exclusions` | 301 | 135 | 18 | 0 |
| `date` | 311 | 142 | 1 | 0 |
| `gagnant` | 205 | 109 | 0 | 140 |

**75/454** marchés portent au moins une donnée lue mais incohérente. *Incohérente* n'est pas *manquante* : le document dit quelque chose que l'arithmétique contredit.

**Distribution du score** (valeurs discrètes : 5 dimensions, 4 pour un marché infructueux) :

| Score | Marchés | Niveau |
|---:|---:|---|
| 0 | 53 | Faible |
| 20 | 11 | Faible |
| 25 | 15 | Faible |
| 40 | 35 | Faible |
| 50 | 38 | Moyen |
| 60 | 99 | Moyen |
| 75 | 26 | Bon |
| 80 | 115 | Bon |
| 100 | 62 | Excellent |

| Niveau | Marchés | Part |
|---|---:|---:|
| Bon | 141 | 31.1 % |
| Moyen | 137 | 30.2 % |
| Faible | 114 | 25.1 % |
| Excellent | 62 | 13.7 % |

Classe la plus chargée : **31.1 %** du corpus — les seuils séparent réellement la population (le contrôle échoue au-delà de 60 %).

**Recoupement avec la porte de scorabilité du modèle** — les deux mesures vont dans le même sens sans être redondantes (`data_completeness` décide qui est scoré, `data_quality_score` informe l'analyste) :

| `data_completeness` | Marchés | Qualité moyenne |
|---:|---:|---:|
| 0/3 | 7 | 11.4 |
| 1/3 | 28 | 46.4 |
| 2/3 | 151 | 64.0 |
| 3/3 | 128 | 83.8 |

## 4. Marchés scorés, non scorés, signalés

- Marchés attribués : **314**
- Scorés : **279**
- Non scorables (moins de 2 informations sur 3) : **35** — comptés et affichés, jamais notés « Faible »
- Signalés atypiques : **28** (10.0 % des scorés)

**Étude de `contamination`** (le paramètre fixe la charge d'analyse, il ne mesure aucun taux d'irrégularité) :

| contamination | marchés signalés | part |
|---|---:|---:|
| 0.05 | 13 | 4.7 % |
| 0.1 ← retenu | 28 | 10.0 % |
| 0.15 | 42 | 15.1 % |
| auto | 62 | 22.2 % |

**Niveaux de risque** (seuils mesurés, jamais 25/50/75) :

- Faible : 251
- Non evaluable : 35
- Modere : 10
- Eleve : 9
- Critique : 9

## 5. Stabilité du modèle

10 réentraînements (`random_state` 0 à 9), Top 20 comparés :

- Marchés apparaissant dans les **10/10** classements : 14
- Dans 8 ou 9 : 3
- Dans 1 seul : 1 — score dépendant du tirage, signalé comme tel dans le dashboard

## 6. Red flags

Registre de règles nommées, **distinct des features du modèle**. Chaque règle porte un identifiant, un nom, une description, une sévérité, et peut valoir `True` / `False` / *non évaluable*.

| ID | Nom | Sévérité | Poids | Dérivé |
|---|---|---|---:|---|
| `RF01` | Faible concurrence | elevee | 3 | non |
| `RF02` | Exclusions atypiques | moyenne | 2 | non |
| `RF03` | Montant atypique | moyenne | 2 | non |
| `RF05` | Procedure rare | faible | 1 | non |
| `RF06` | Signaux multiples | moyenne | 2 | oui |

Les sévérités traduisent une priorité de lecture issue de la littérature, **pas un effet mesuré** — sans vérité terrain, aucun effet n'est estimable sur ce corpus.

**Seuils mesurés sur la distribution du corpus :**

- RF02 : `exclusion_rate >= 0.500` (quantile 0.8, calculé sur les 208 marchés dont la donnée est `KNOWN`)
- RF03 : `montant_ttc >= 11,746,666.13 DH` (quantile 0.95, 135 marchés `KNOWN`)
- RF05 : procédures représentant moins de 5% du corpus — 4 modalités, 6 marchés :
  - Appel d'offres avec préselection - Phase 2
  - Concours Architectural
  - Consultation architecturale ouverte
  - Marché négocié avec publicité préalable - Phase 1
- RF04 : **non implémenté**, estimation indisponible (0/454)

| Red flag | actif | inactif | non évaluable |
|---|---:|---:|---:|
| `RF01` Faible concurrence | 96 | 148 | 70 |
| `RF02` Exclusions atypiques | 45 | 163 | 106 |
| `RF03` Montant atypique | 12 | 130 | 172 |
| `RF05` Procedure rare | 6 | 308 | 0 |
| `RF06` Signaux multiples | 26 | 263 | 25 |

**Correctif de la Phase 2 sur RF01.** L'ancienne règle était `nb_soumissionnaires <= 1`, or `0 <= 1` : sur 152 déclenchements, **56 (37 %)** venaient d'un marché attribué où aucun nom n'avait pu être lu — dont 35 où des noms figuraient dans le document mais avaient tous été rejetés par le filtre de plausibilité. Un marché ne peut pas être attribué à personne : ce zéro est un défaut d'extraction, pas une absence de concurrence. RF01 lit désormais l'état `KNOWN` de la dimension `concurrents` et vaut *non évaluable* dans ce cas — il passe à **96** déclenchements. Perte de signal apparent, gain d'exactitude.

## 6bis. Comparaison à des marchés comparables (Phase 3)

Remplace la question « ce marché est-il gros ? » par « ce marché est-il gros **pour ce qu'il est** ? ». Un marché de travaux et une prestation de services au même montant ne sont pas comparables.

Cascade, du plus fin au plus grossier, minimum **10 comparables** (le marché lui-même exclu) :

| Niveau | Clé de regroupement | Marchés |
|---|---|---:|
| fin | `categorie_principale × mode_passation × annee` | 255 |
| moyen | `categorie_principale × mode_passation` | 53 |
| large | `categorie_principale × annee` | 6 |
| tres_large | `categorie_principale` | 0 |
| — | aucun groupe atteignant le minimum | 0 |

**Deux minimums, pas un.** Avoir 10 comparables ne suffit pas : il faut 10 comparables portant **la même dimension**. Un groupe de 40 marchés dont 3 seulement ont un montant ne peut pas fournir une médiane crédible.

- Comparaisons de montant calculables : **67/314** (21.3 %)
- Comparaisons de concurrence calculables : **213/314** (67.8 %)

Parmi les marchés comparables sur le montant : **10** dépassent le P90 de leur groupe ; ratio médian au médian des pairs **1.11**.

**RF03 est désormais adossé aux comparables** quand ils existent, sinon il retombe sur le quantile du corpus — le repli est tracé marché par marché :

- `non evaluable` : 172 marchés
- `corpus` : 75 marchés
- `pairs` : 67 marchés

## 7. Explicabilité

- SHAP (TreeExplainer) calculé sur 279 marchés
- Contrôle par ablation : recouvrement moyen du Top 3 = **0.61**, accord parfait sur 91/279 marchés
- Explications reposant sur au moins une valeur imputée : **0/279**

  Ce zéro a été vérifié plutôt que supposé : une valeur imputée vaut la médiane du corpus, donc elle ne distingue le marché de personne et ne peut pas remonter dans les principales contributions. C'est un contrôle qui passe, pas un calcul manquant — et c'est le comportement recherché, puisqu'une explication ne doit jamais reposer sur une valeur que le document ne portait pas. Le dashboard affiche l'avertissement si le cas se présente sur un corpus futur.

**Importance moyenne des features (|SHAP|)** :

- `mode_ao_ouvert` : 0.57707
- `nb_concurrents_ecartes` : 0.5008
- `exclusion_rate` : 0.44642
- `nb_soumissionnaires` : 0.4416
- `log_montant_ttc` : 0.28161
- `cat_fournitures` : 0.22601
- `has_exclusion_data` : 0.19129
- `cat_services` : 0.1607
- `cat_travaux` : 0.11697
- `has_amount_data` : 0.11131
- `mode_autre` : 0.0781

## 7bis. Priority Score (Phases 6-7)

Repond a « quels marches examiner en premier ? », jamais a « quels marches sont irreguliers ? ».

```
priority_raw = 0.5 x anomaly_score  +  0.5 x red_flag_score
```

**Deux composantes seulement.** La comparaison aux pairs n'est pas un troisieme terme : elle alimente deja RF03, donc `red_flag_score` — l'ajouter compterait deux fois le meme signal. La qualite des donnees n'y entre pas non plus : elle **plafonne** le niveau au lieu de gonfler le score.

| Ponderation | rho de Spearman vs 50/50 | Top 20 communs |
|---|---:|---:|
| `equilibre_50_50` | +1.000 | 20/20 |
| `anomalie_dominante_70_30` | +0.933 | 15/20 |
| `red_flags_dominants_30_70` | +0.969 | 14/20 |

Aucune n'est « meilleure » : sans verite terrain on ne mesure que leur accord. Le 50/50 est retenu faute de mesure justifiant d'avantager une composante.

| Niveau de priorite | Marches |
|---|---:|
| Tres prioritaire | 26 |
| Prioritaire | 25 |
| A surveiller | 61 |
| Faible | 167 |
| Donnees insuffisantes | 35 |

| Confiance | Marches |
|---|---:|
| Elevee | 163 |
| Moyenne | 82 |
| Insuffisante | 35 |
| Faible | 34 |

**Le garde-fou sert reellement** : 5 marches auraient ete classes prioritaires sur leur seul score, mais leur confiance est faible — ils sont ramenes a « A surveiller », visibles et avec leur score, presentes pour ce qu'ils sont : un signal sur peu de donnees.

## 8. Ce que cette refonte ne corrige pas

- **Le montant reste absent de 63 % des marchés.** L'imputation médiane est signalée (`amount_imputed`), jamais présentée comme une lecture.
- **L'estimation administrative est hors d'atteinte** sur ce corpus : aucun écart estimation/attribution n'est calculable.
- **Aucune vérité terrain au niveau marché.** La qualité d'extraction est mesurée sur 20 documents annotés ; le modèle, lui, n'a aucun label — sa stabilité est mesurée, sa justesse ne peut pas l'être.
- **35 marchés attribués restent non analysables** faute de données extraites. Ils sont comptés, pas masqués.
- **Le bruit résiduel sur les noms d'entreprise subsiste** (audit du 27/08/2026) ; il n'affecte plus le modèle, qui n'utilise plus l'entreprise comme unité, mais il affecte encore l'affichage du gagnant.
