# Idées méthodologiques — Analyse temporelle & Red Flags

> Complète `docs/data_dictionary.md` (§2-3) et `docs/issues_backlog.md`.
> Base scientifique pour les modules 3 et 4 (statistiques, feature engineering, détection d'anomalies).
> Sources : article Big Data/IA & fiscalité (rapprochement, ratios, scoring — voir `docs/etat_de_lart.md`) + Fazekas, Tóth & King (2016), *"An Objective Corruption Risk Index Using Public Procurement Data"*.

Dernière mise à jour : 19/08/2026

---

## 2.5 Analyse temporelle — pas un instantané, une trajectoire

L'idée centrale : ne jamais évaluer une entreprise sur un seul marché isolé. L'évaluer sur son **historique par année**, sur la période scrapée (2023-2026, alignée sur nos 390 PV).

### Pourquoi ça change tout

Une phrase comme *"Entreprise X a un taux élevé de marchés à soumissionnaire unique"* est une observation statique — elle peut être vraie depuis toujours pour des raisons non suspectes (marché de niche, peu de concurrents qualifiés).

Une phrase comme *"les indicateurs de risque associés à l'Entreprise X ont fortement augmenté au cours du temps"* est un **signal dynamique** — beaucoup plus difficile à expliquer par des raisons bénignes, et beaucoup plus proche de ce qu'un analyste humain veut voir en premier.

### Exemple concret (valeurs illustratives, pas des vraies données)

| Année | Marchés remportés | Marchés à soumissionnaire unique | Concentration (part de marché chez ses acheteurs) |
|---|---|---|---|
| 2023 | 10 | 2 (20%) | 20% |
| 2024 | 15 | 7 (47%) | 45% |
| 2025 | 21 | 16 (76%) | 72% |

→ Ce n'est plus "cette entreprise a un taux élevé de X" mais **"la trajectoire de l'entreprise X converge vers un profil à risque"**.

### Indicateurs temporels à calculer (module 3 — PySpark, groupby entreprise × année)

- `number_of_awards_by_year`
- `total_amount_by_year`
- `average_amount_by_year`
- `win_rate_by_year` (si on a le nombre de participations, pas seulement de victoires — dépend de `liste_concurrents` du PV)
- `single_bidder_rate_by_year` = marchés à 1 soumissionnaire / total marchés de l'année
- `concentration_by_year` = montant remporté chez un acheteur / montant total des marchés de cet acheteur cette année-là
- `yoy_growth` (croissance annuelle) = valeur année N / valeur année N-1, pour chacun des indicateurs ci-dessus

**Caveat confirmé sur le corpus réel (400 PV enrichis)** : la répartition par catégorie est globalement stable d'une année à l'autre (2024-2026), sauf 2023 qui penche vers Services (46 documents) au détriment de Fournitures (seulement 20). Pas bloquant, mais un `yoy_growth` calculé pour la catégorie Fournitures avec 2023 comme point de départ sera plus bruité que pour les autres catégories/années — à mentionner en caveat dans le rapport final plutôt qu'à ignorer silencieusement.

**Caveat critique — 2026 est une année tronquée** : le projet démarre en août 2026, donc 2026 ne contient qu'environ 8 mois de données sur 12. Tous les indicateurs `*_by_year` seront mécaniquement plus bas pour 2026 que pour une année complète, pour quasiment toutes les entreprises — pas parce que leur activité a baissé, mais par simple effet de troncature temporelle. Sans correction, ça produit un faux signal du type *"chute d'activité en 2026"* sur l'ensemble du corpus.

Décision retenue : **exclure 2026 des calculs de tendance** (`yoy_growth`, pente de régression linéaire utilisée comme feature Isolation Forest). 2026 reste utile en statistique descriptive brute (compter les marchés en cours), mais ne doit jamais entrer dans un calcul de croissance ou de trajectoire — la seule série temporelle exploitable pour la détection d'anomalie est **2023→2024→2025** (3 points complets). Alternative écartée : annualiser 2026 (extrapoler ×12/8) — rejetée car ça suppose une activité linéaire sur l'année, hypothèse fragile dans les marchés publics où l'attribution est souvent concentrée en fin d'exercice budgétaire.

**Caveat critique — le « 2024 » de la Passe B est en réalité décembre 2024** : la collecte de contexte (spider Consultations, Passe B via le listing paginé) a bien atteint son quota de 450 consultations pour 2024, mais leur répartition mensuelle réelle est totalement déséquilibrée :

| Mois de `date_mise_ligne` | Consultations |
|---|---:|
| juillet 2024 | 1 |
| octobre 2024 | 1 |
| novembre 2024 | 34 |
| **décembre 2024** | **414 (92 %)** |

Ce n'est **pas un défaut de scraping** : c'est la conséquence directe de la fenêtre glissante du portail, qui ne conserve dans sa recherche que ~2 ans d'historique (~sept. 2024 au plus ancien). Le quota s'est donc rempli sur la queue de la fenêtre, pas sur l'année.

**Conséquence** : tout indicateur annuel (`number_of_awards_by_year`, `total_amount_by_year`, `single_bidder_rate_by_year`…) calculé sur ce millésime 2024 de Passe B porterait sur **un mois présenté comme une année** — soit une erreur d'un facteur ~12, dans le sens inverse du biais 2026 décrit ci-dessus. Combiné à un `yoy_growth` 2024→2025, il produirait un faux signal d'explosion d'activité sur l'ensemble du corpus.

**2025 et 2026 ne souffrent pas de ce biais** (répartition étalée sur l'année), et le « 2024 » issu de la **Passe A** — les consultations liées aux PV, datées via `annee_source="pv"` — reste **fiable**, puisqu'il ne dépend pas du listing mais du manifeste PV (100 documents par an, échantillonnés sur toute l'année).

Décision retenue : **exclure le « 2024 » de Passe B de tout calcul annuel** tant qu'il n'est pas rééquilibré. Concrètement, filtrer sur `source == "listing" AND annee == 2024` pour l'écarter des agrégats — d'où l'importance de ne jamais perdre les champs `source` et `annee_source` lors de la fusion des deux passes en PySpark. Le rééquilibrage éventuel passerait par une collecte au fil de l'eau (même limite que celle documentée en §2.6), hors périmètre du sprint.

**Point d'implémentation important** : ces indicateurs doivent être calculés **par année ET cumulés en série temporelle par entreprise**, pas juste agrégés sur toute la période. C'est la variation dans le temps qui est le signal, pas la valeur absolue. Prévoir une structure genre `{company_name: {2023: {...}, 2024: {...}, 2025: {...}}}` avant de la transformer en features pour Isolation Forest (ex: pente de régression linéaire sur `single_bidder_rate` comme feature d'anomalie, pas juste sa valeur 2025). 2026 peut être ajoutée à la structure pour information mais doit être exclue de tout calcul de pente/croissance, comme précisé ci-dessus.

---

## 2.6 Bibliothèque de Red Flags — quoi chercher, pas juste comment analyser

Fazekas et al. (2016) donnent une méthode validée statistiquement (régression logistique + tests de permutation, R² 0,10-0,24, 13 red flags retenus sur 30+ testés) pour transformer des variables de marché public en indicateurs de risque de corruption. On **n'a pas besoin de refaire leur régression** — on peut réutiliser directement leur liste de red flags, adaptée à ce qui est réellement disponible sur le PMMP.

### Principe directeur (à répéter dans le rapport final)

Le système ne répond jamais à *"ce marché est-il frauduleux ?"* mais à *"ce marché présente-t-il plusieurs caractéristiques statistiquement associées à un risque de corruption dans la littérature scientifique ?"*. Risque élevé ≠ corruption prouvée. C'est un signal pour prioriser l'analyse humaine, jamais une accusation automatisée — cohérent avec le principe directeur déjà énoncé dans `rapport_avancement.md` §1.

### Tri des red flags Fazekas par disponibilité réelle sur le PMMP

Reprend la logique déjà validée dans `data_dictionary.md` : ne jamais prétendre avoir une donnée qu'on n'a pas.

**🟢 Directement disponibles (déjà dans notre modèle de données)**

| Red flag (Fazekas) | Champ PMMP correspondant |
|---|---|
| Single bidder | `number_of_bidders` (dérivé de `liste_concurrents`, PV) |
| Procédure non ouverte | `mode_passation` (Consultation) — ⚠️ **variance quasi nulle confirmée sur le corpus réel** : sur l'échantillon de 400 PV enrichis, 97% des marchés se concentrent sur seulement 2 valeurs (Appel d'offres ouvert 72,6% + AO ouvert simplifié 24,7%), 1 seul marché restreint sur 400. Le champ reste disponible et doit être conservé comme feature catégorielle, mais un modèle d'anomalie comme Isolation Forest ne pourra en tirer aucun signal fort — au mieux du bruit. Documenter explicitement cette limite dans `docs/methodology.md` (Issue 15), ne pas présenter ce red flag comme discriminant dans le rapport final. |
| Exclusion de concurrents | `concurrents_ecartes` (PV) |
| Modification de contrat | non confirmé disponible — à vérifier pendant le scraping |

**🟡 Calculables (dérivés de champs bruts)**

| Red flag (Fazekas) | Calcul |
|---|---|
| Concentration du gagnant | `montant remporté par X chez acheteur A / montant total des marchés de A` |
| Part de marché récurrente | `number_of_awards` par entreprise × acheteur, cumulé |

**🔴 Retirés du périmètre — limite structurelle du portail confirmée (19/08/2026)**

| Red flag (Fazekas) | Calcul envisagé | Pourquoi il est retiré |
|---|---|---|
| Délai de soumission court | `date_limite_remise_plis − date_mise_ligne` | Les deux champs sont vides sur toute consultation déjà attribuée |
| Écart de prix (final vs estimé) | `montant_ttc / estimation_dhs_ttc` (champ renommé, voir `data_dictionary.md` §3.6) | ~~**on a les deux champs**, contrairement à Fazekas qui n'avait que le prix final~~ — l'estimation et le montant final ne coexistent jamais sur un même marché |

**Constat mesuré, pas supposé.** Sur une consultation déjà attribuée, le portail rend la page de détail dans le contexte de l'**annonce d'extrait de PV**, pas de l'annonce de consultation d'origine. Dans ce contexte, `estimation_dhs_ttc`, `caution_provisoire`, `date_limite_remise_plis` et `date_mise_ligne` sont **structurellement vides** : les libellés sont bien rendus, mais sans valeur (`Estimation (en Dhs TTC) * : @@@@`, `Caution provisoire :` vide, aucune mention de « remise des plis »).

Ce n'est **pas un défaut de parsing** : il n'existe aucun lien de retour vers l'annonce de consultation d'origine — la page ne porte qu'un seul `idAvis`, celui du PV. Ces champs n'existent que sur les consultations **encore ouvertes**, qui n'ont par définition pas encore de PV. Les deux valeurs nécessaires au ratio prix final / prix estimé ne coexistent donc jamais sur un même marché dans les données publiques.

Mesure sur le corpus réel (spider Consultations, deux passes) :

| Champ | Passe A — consultations liées à un PV | Passe B — consultations encore ouvertes |
|---|---|---|
| `estimation_dhs_ttc` | **0/16** | 9/13 |
| `caution_provisoire` | **0/16** | 9/13 |
| `date_limite_remise_plis` | **0/16** | 13/13 |
| `date_mise_ligne` | **0/16** | 13/13 |
| `reference`, `objet`, `acheteur_public`, `mode_passation`, `categorie_principale` | 16/16 | 13/13 |

**Rattrapage possible mais hors périmètre.** Récupérer ces deux red flags supposerait une **collecte au fil de l'eau** : scraper les consultations pendant qu'elles sont encore ouvertes (l'estimation et les dates y sont disponibles), les stocker, puis les rejoindre aux PV qui paraîtront plus tard. C'est viable pour un système pérenne, mais incompatible avec un sprint de 15 jours — la fenêtre d'observation nécessaire est de plusieurs mois.

**Décision retenue** : retrait du périmètre actif, à documenter comme limite assumée dans `docs/methodology.md` (Issue 15), au même titre que la limite déjà documentée plus haut sur `mode_passation`. Ce que la Passe A apporte de façon fiable sur les 400 marchés attribués — y compris 2023 — reste `acheteur_public`, `categorie_principale`, `mode_passation`, `objet` et `lieu_execution`, c'est-à-dire les variables de contrôle et de regroupement de §2.5.

**🔴 Non disponibles — ne jamais les simuler comme si elles existaient**

- Longueur des critères d'éligibilité (texte libre, pas structuré chez nous)
- Connexions politiques des dirigeants (Fazekas : appariement par nom avec une base de titulaires de postes politiques — aucun équivalent PMMP)
- Enregistrement en paradis fiscal (Fazekas : Financial Secrecy Index)
- Rentabilité de l'entreprise (nécessiterait des données financières hors PMMP)

→ Mentionner ces trois dernières comme **perspectives futures** si accès DGI, jamais comme variables actuelles du système (cohérent avec la limite déjà actée pour le référentiel fiscal synthétique).

### Score de risque composite — s'inspirer de la méthode Fazekas, pas juste du résultat

Fazekas ne choisit pas les poids au hasard : chaque red flag reçoit un poids dérivé de son coefficient de régression (plus un indicateur est prédictif dans leurs modèles, plus il pèse dans l'indice composite CRI). Pour Issue 12 (`risk_score`), deux options à trancher avec l'encadrante :

1. **Poids égaux** (plus simple, plus rapide pour 15 jours) — chaque red flag actif ajoute une valeur fixe au score 0-100.
2. **Poids inspirés de Fazekas** — reprendre leurs poids relatifs (Table 5 de l'article) pour les red flags qu'on a en commun, en documentant explicitement que ce sont des poids importés d'un contexte hongrois, pas ré-estimés sur données marocaines. Plus défendable scientifiquement en soutenance, mais introduit un biais de transfert à assumer.

Recommandation : commencer par l'option 1 pour le prototype, mentionner l'option 2 comme axe d'amélioration dans `docs/methodology.md` (Issue 15).

### Multi-niveaux d'analyse (extension au-delà de Fazekas, à garder simple pour 15 jours)

Fazekas agrège son CRI du contrat → organisation → secteur → région → pays. On peut viser la même hiérarchie mais **seulement 2 niveaux pour le prototype** :

- **Niveau marché** : ce marché est-il inhabituel ? (Isolation Forest sur features de marché)
- **Niveau entreprise** : cette entreprise a-t-elle une trajectoire de risque croissante ? (§2.5, série temporelle)

Le niveau acheteur public et le niveau secteur sont mentionnables comme extensions futures dans le rapport, mais ne pas les coder dans le sprint de 15 jours sauf temps en rab — risque de complexifier le scope pour un gain marginal en démo.

---

## Comment ça retombe sur le backlog existant

- **Issue 10** (Statistiques et agrégations) : ajouter explicitement les indicateurs *by_year* de §2.5, pas seulement les agrégats globaux déjà listés.
- **Issue 11** (Feature engineering) : la liste de features doit inclure les red flags 🟢/🟡 de §2.6, avec la trajectoire temporelle (pente, croissance YoY) comme feature à part entière, pas juste la valeur finale.
- **Issue 12** (Risk score) : trancher poids égaux vs poids Fazekas avant de coder ; chaque explication textuelle du score doit nommer le red flag concerné en langage clair (ex: *"taux de soumissionnaire unique en forte hausse depuis 2023"*), pas juste un score numérique opaque.

## Limite à documenter dans le rapport final

Contrairement à Fazekas (régression sur 53 000+ contrats hongrois pour valider statistiquement chaque red flag), on **importe leur liste sans revalider empiriquement sur données marocaines** — le volume du prototype (15 jours, échantillon filtré) ne le permet pas. C'est une limitation à assumer explicitement, pas à cacher : les red flags sont utilisés comme hypothèses de départ issues de la littérature, pas comme résultats re-démontrés sur le PMMP.
