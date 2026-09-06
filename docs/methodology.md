# Méthodologie — décisions techniques et limites mesurées

> Documente les choix qui ne se lisent pas directement dans le code : pourquoi tel paramètre plutôt qu'un autre, quelles limites ont été mesurées plutôt que supposées.
> Complète [`data_dictionary.md`](data_dictionary.md) et [`ideas.md`](ideas.md).

Dernière mise à jour : 22/08/2026

---

## 1. Pipeline OCR (Issue 5)

Architecture : `ocr/pdf_to_image.py` (rendu + détection texte natif) → `ocr/preprocess.py` (orientation, deskew, denoise, binarisation) → `ocr/tesseract_engine.py` (Tesseract + OSD) → `ocr/pipeline.py` (orchestration, `ocr_status`).

### 1.1 `--psm 3` plutôt que `--psm 6`

Mesuré sur un cas réel contenant un tableau (`EXTRAIT DE PV - AOO N°57-2026.pdf`) : `--psm 6` (bloc uniforme) lit la valeur de `classement` comme un tiret cassé (« — ») ; `--psm 3` (segmentation automatique) la lit correctement (« 1 »). Confirmé sans régression sur 6 documents en prose (5 gains de +2,8 à +9,2, 1 régression négligeable de -0,2).

**Piège de configuration rencontré** : un `.env` local portait encore `OCR_PSM=6`, qui écrasait silencieusement ce défaut. La totalité du premier run de validation sur les 390 PV (§1.7) a d'abord tourné sous `--psm 6` sans que cela soit visible dans les logs — seule une relecture du fichier de configuration l'a révélé. Corrigé dans `.env` et `.env.example`. Leçon retenue : un défaut de code changé sans vérifier les surcharges d'environnement locales n'est pas réellement appliqué.

### 1.2 Correction d'orientation par OSD — seuil non-monotone, assumé

Tesseract fournit `image_to_osd()` avec un angle de rotation suggéré et un `orientation_conf`. Un seuil plancher (`OSD_MIN_ORIENTATION_CONF = 1.0`) déclenche la rotation.

**Mesure explicite : ce seuil n'est pas un filtre fin, et ça a été vérifié, pas supposé.** Sur 15 rotations déclenchées à l'échelle des 390 PV :

| Document | `orientation_conf` | Rotation | Verdict (vérifié visuellement) |
|---|---:|---:|---|
| `ddd2c59f...` p4 | 1,01 | 90° | **Correcte** — texte français lisible récupéré (37,7 → 84,4) |
| `e84f3dc6...` p10 | 2,12 | 90° | **Correcte** — texte français lisible récupéré (47,1 → 88,9) |
| `65597f99...` p2 | 7,73 | 180° | **❌ Incorrecte** — a détruit une page déjà lisible (74,7 → 36,3) |

Le cas incorrect (7,73) a une confiance **supérieure** aux deux cas corrects (1,01 et 2,12) et se situe dans la même plage que plusieurs autres cas corrects du corpus (9-22). **Aucun seuil monotone ne sépare les deux catégories sur ces données** — remonter le seuil casserait les cas corrects à faible confiance sans garantir d'écarter le cas incorrect.

**Taux d'erreur mesuré et assumé comme limite connue : 1/15 (6,7 %).** Décision retenue : garder le seuil de 1,0 comme plancher grossier contre le bruit total, pas comme filtre de précision, et documenter le risque résiduel plutôt que de chercher un seuil parfait qui n'existe pas dans ces données.

**Limite additionnelle observée** : l'agrégation de confiance au niveau du document peut masquer un défaut au niveau de la page. Sur `65597f99...`, la page 1 (bonne) et la page 2 (victime du faux positif ci-dessus) donnent une moyenne document de 64,7 — au-dessus du seuil de succès (60) — alors que la page 2 reste individuellement illisible. Le statut `ocr_status` global ne garantit donc pas que *chaque page* d'un document `ocr_success` soit exploitable ; l'inspection doit rester possible au niveau page (`PageResult.confidence`), pas seulement au niveau document.

### 1.3 Langue Tesseract — `fra+ara`, pas `fra` seul

Le corpus contient des PV **partiellement ou totalement rédigés en arabe** — pas seulement des en-têtes bilingues, mais des pages entières. Avec `lang='fra'` seul, ces pages tombaient à une confiance quasi nulle (0,0 à 30,5), non pas parce que le scan était dégradé mais parce que le modèle de langue ne pouvait pas reconnaître le script.

**Décision retenue : gérer nativement via `lang='fra+ara'`, ne jamais exclure ces documents du corpus.** Nécessite `ara.traineddata` dans `TESSDATA_PREFIX`. Sur les 7 documents concernés du run de validation, passage de 0,0-30,5 à 62,7-88,9 de confiance, tous récupérés au-dessus du seuil de succès.

**Même piège de configuration qu'en §1.1** : `.env` portait `OCR_LANGUAGE=fra`, qui écrasait le nouveau défaut `fra+ara` du code. Corrigé au même moment.

### 1.4 Confiance moyenne du document — exclure les pages quasi-vides

Une page blanche ou quasi-vide (ex. page de signature) donne une confiance de 0,0 par absence de texte détecté, pas par mauvaise reconnaissance. Moyennée avec une page par ailleurs excellente, elle fait chuter le document entier en `ocr_low_confidence` à tort (cas mesuré : 88,0 + 0,0 → moyenne 44,0, sous le seuil de 60).

**Décision retenue : exclure du calcul de moyenne les pages sous `OCR_MIN_WORDS_FOR_CONFIDENCE = 3` mots reconnus.** Une page réellement vide ne pèse plus dans la moyenne — mais reste visible individuellement dans `PageResult` pour la traçabilité. Cas limite documenté : si *toutes* les pages OCR d'un document sont quasi-vides, le document est marqué `ocr_low_confidence` (confiance 0,0) plutôt que de planter sur une division par zéro — comportement délibéré, pas un défaut.

### 1.5 Deux documents exclus du pipeline — `EXCLUDED_STEMS`

`scripts/run_ocr.py` exclut explicitement 2 documents (sur 390) de tout run, par `EXCLUDED_STEMS` :

| Document | Raison | Statut avant exclusion |
|---|---|---|
| `65597f99...cf78` | Faux positif OSD confirmé (§1.2) — page 2 rotée à 180° à tort, reste illisible malgré un score document qui passe le seuil (64,7) grâce à la page 1 | `ocr_success` (trompeur) |
| `9d2a5e07...1e1` | Page OCR réellement blanche (luminosité 254,96/255) | `ocr_low_confidence` (justifié) |

**Sur les 10 documents `ocr_low_confidence` du run initial (§1.7), répartition exacte** — corrige une formulation antérieure ambiguë (« 9 récupérés + 2 exclus », qui comptait `65597f99...` deux fois) :

- **8 documents récupérés et conservés** dans le pipeline (langue arabe : 6 cas ; page quasi-vide exclue de la moyenne : 1 cas — `c66cad5f...` ; correction de configuration `--psm` seule : 1 cas — `44b28d32...`, voir §1.6)
- **1 document récupéré numériquement mais exclu** (`65597f99...` — le score document masque un défaut de page réel, voir §1.2)
- **1 document non récupéré et exclu** (`9d2a5e07...` — page blanche, à raison)

Conséquence sur le modèle de données documentée dans `data_dictionary.md` §3.5 : ces deux `reference` ont une `Procurement` collectable mais aucun `Award` exploitable depuis le PV correspondant.

### 1.6 Cas `44b28d32...` — tableaux financiers denses (8 pages)

Ce document (tableau de montants par lot et par concurrent, listes d'entreprises répétées sur plusieurs colonnes) avait été classé *réellement dégradé* lors d'une première inspection réalisée sous `--psm 6` (avant la découverte du piège de configuration §1.1). Une fois `--psm 3` réellement appliqué, il passe à `ocr_success` (confiance 84,9 sur 8 pages). Les répétitions de noms d'entreprise observées dans le texte (ex. « NS MEDICAL » sur plusieurs lignes) correspondent à la structure réelle du tableau (une entreprise peut remporter plusieurs lots), pas à un artefact de reconnaissance — confirmé par une confiance homogène et élevée (76-89) sur chacune de ses pages.

**Conclusion : ce cas n'est plus un exemple de limite connue.** Il illustre plutôt à quel point une mauvaise configuration silencieuse (§1.1) peut faire passer un document parfaitement récupérable pour un cas dégradé — leçon méthodologique à retenir pour l'évaluation d'Issue 6/7 : toujours vérifier la configuration effective avant de conclure qu'un document est irrécupérable.

### 1.7 Distribution finale mesurée (388 PV réels)

Trois runs successifs sur le corpus complet, comparables terme à terme :

| Statut | Run 1 — `--psm 6` par piège de config (390) | Run 2 — `fra+ara` + `--psm 3` + pages vides + `EXCLUDED_STEMS` (388) | Run 3 — **+ détection de couche texte corrompue** (388) |
|---|---:|---:|---:|
| `native` | 113 (29,0 %) | 113 (29,1 %) | **87 (22,4 %)** |
| `ocr_success` | 267 (68,5 %) | 275 (70,9 %) | **301 (77,6 %)** |
| `ocr_low_confidence` | 10 (2,6 %) | **0** | **0** |
| `ocr_failed` | 0 | 0 | **0** |

**Le déplacement de 26 documents entre `native` et `ocr_success` au run 3 est la signature du correctif §1.10** : ces documents avaient une couche texte présente mais inexploitable, et étaient donc classés `native` sans jamais passer par l'OCR. Parmi eux, **12 sont désormais mixtes** — leurs pages saines restent lues en natif, seules les pages corrompues sont océrisées, la décision se prenant page par page et non document par document.

14 rotations OSD déclenchées, plage `orientation_conf` 1,01-22,79 — identique au run précédent, ce qui confirme l'absence de régression sur cette partie.

### 1.8 Temps de traitement

| Run | Durée | Moyenne | Contexte |
|---|---:|---:|---|
| Run 2 | 310,6 min | 48,0 s/doc | Contention machine + le document `/MediaBox` à 1h58 (§1.9) |
| **Run 3** | **124,7 min** | **19,3 s/doc** | Correctif §1.9 actif, malgré 26 documents supplémentaires envoyés à l'OCR |

La division par 2,5 du temps total vient presque entièrement de la suppression du cas `/MediaBox` (§1.9), qui à lui seul représentait 38 % du temps du run 2.

Deux facteurs à connaître pour dimensionner Issue 6/7 :

1. **Contention machine intermittente** (applications tierces lourdes) — ralentissement généralisé et réversible, observé sur les deux runs longs : le rythme passe de ~12 s à ~26 s, voire ~200 s/document, et redevient normal dès la fermeture des applications. Non corrigeable côté code.
2. **La moyenne masque une forte dispersion** : un PDF d'une page en natif se traite en 0,1 s, un scan de 8 pages en plus de 100 s.

**Base de dimensionnement recommandée : ~12-19 s/document** sur une machine non chargée.

### 1.9 `/MediaBox` malformé — cause racine identifiée et corrigée

Diagnostic du document `c87a91a5...` (§1.8) : le `/MediaBox` du PDF déclare une page de **2479×3507 points** (34,4×48,7 pouces — physiquement absurde pour un PV), alors que l'image PNG intégrée à l'intérieur fait exactement **2479×3507 pixels**, la résolution normale d'un scan A4 à 300 dpi identique au reste du corpus. Le PDF a été généré avec des valeurs de `MediaBox` exprimées en pixels au lieu de points PostScript (1/72 pouce) — bug connu de certains outils de numérisation. En rendant « à 300 dpi » contre ce `MediaBox` erroné, PyMuPDF calcule une sortie de 10330×14613 px (151 Mpx), gonflant artificiellement une image source normale par un facteur ~4,17 — sans aucune information supplémentaire, juste des pixels interpolés que `fastNlMeansDenoising` doit ensuite traiter.

**Correctif appliqué** (`ocr/pdf_to_image.py`, `render_page_image`) : le DPI effectif de rendu est recalculé pour plafonner la plus grande dimension de sortie à `MAX_RENDER_DIMENSION_PX = 4000` px, au lieu de faire confiance aveuglément au DPI nominal appliqué à un `MediaBox` qui peut mentir. Un document normal (A4 à 300 dpi ≈ 3507 px de long) n'est pas affecté — la marge de 4000 px reste sous le seuil de déclenchement. Seuls les documents dont le `MediaBox` projette un rendu excessif sont recadrés.

**Résultat vérifié sur `c87a91a5...`** :

| | Avant fix | Après fix |
|---|---:|---:|
| Dimensions rendues | 10330×14613 px (151 Mpx) | 2824×3995 px (11,3 Mpx) |
| Temps de traitement (4 pages) | 7 133,9 s (1h58) | **48,0 s** |
| `ocr_status` | `ocr_success` (73,0) | `ocr_success` (**82,0**, qualité même légèrement meilleure) |

Facteur **~149×** sur le temps, sans perte de qualité — confirmé par une régression sur 35 tests unitaires (`scraper/tests/`, tous passants) et par relecture du texte produit (français lisible, en-tête arabe correctement décodé via `fra+ara`). Document non exclu du pipeline : ce n'était pas une donnée dégradée, seulement une cause corrigée à la source, conformément au principe déjà appliqué en §1.6 pour `44b28d32...` — toujours vérifier la configuration/le rendu effectif avant de conclure qu'un document est irrécupérable ou anormal.

### 1.10 Couche texte présente mais corrompue — le défaut le plus grave trouvé

**Trouvé par l'annotation de vérité terrain, pas par un contrôle automatique.** En annotant les 20 documents de référence (Issue 6), l'annotation a signalé des documents classés `native` dont le texte était en réalité illisible. Vérification faite : c'était exact.

Le PDF porte une couche texte produite avec un **encodage de police cassé**. PyMuPDF l'extrait sans erreur, mais le résultat est de la soupe de caractères :

```text
ROYAI]ME DU i\{AROC              (= ROYAUME DU MAROC)
N4 lNiS'f t lli'l l t)ir t.'      (= MINISTERE DE L'INTERIEUR)
RÛYATIME DLJ MAROC               (= ROYAUME DU MAROC)
```

**Pourquoi c'était le pire défaut possible** : `has_native_text` ne vérifiait que la *longueur* du texte (`> NATIVE_TEXT_MIN_CHARS`), jamais sa *plausibilité*. Ces documents passaient donc pour natifs, **sautaient entièrement l'OCR**, et stockaient du charabia sans qu'aucun indicateur ne le signale — ni `ocr_status`, ni confiance, ni erreur. Ils auraient traversé l'Issue 7 en produisant zéro extraction, et on aurait cherché la cause dans les regex.

**Correctif** (`ocr/pdf_to_image.py`, `text_looks_corrupted()`) : deux seuils combinés par un `OU`, calibrés sur les 113 documents natifs réels du corpus — pas choisis à l'intuition.

| Métrique | Documents sains | Cas confirmés cassés |
|---|---|---|
| `MALFORMED_TOKEN_MAX_RATIO` — part de tokens qui ne sont pas des suites de lettres propres | médiane 19 %, p90 32 % | 27 % et 43 % |
| `NOISE_CHARS_MAX_PER_1000` — densité de `[]{}\|` semés par les polices cassées | médiane 0,0 | 4,8 et 11,7 |

**Il fallait bien les deux** : un cas confirmé est à 27 % de tokens malformés — dans la plage saine — et n'est rattrapé que par le bruit (4,8) ; l'autre est dans la situation inverse. Aucune des deux métriques seule ne sépare les cas confirmés des documents sains.

**Résultat mesuré** : 26 documents sortent du statut `native` (dont 12 en mode mixte), et après régénération complète du corpus **plus aucune page native ne déclenche le détecteur**. Les 6 cas vérifiés à la main sont tous détectés — les 2 signalés par l'annotation, plus 4 autres identifiés en inspectant les scores extrêmes.

**Limite connue, non corrigée.** Une **seconde classe de défaut** échappe à ce contrôle : un PDF dont la couche texte provient d'un OCR tiers de qualité médiocre. Cas confirmé dans le corpus (`Marché n' 19/CS/2026`, `siqnalisation` au lieu de `signalisation`). Ce texte est correct à ~90 %, donc les deux métriques le jugent sain, et il reste classé `native`. Ce choix est délibéré : l'impact est bien moindre (le texte reste exploitable, avec des erreurs de caractères éparses), et un seuil assez agressif pour l'attraper enverrait à l'OCR des dizaines de documents parfaitement sains. **`native` ne garantit donc pas une couche texte parfaite** — à garder en tête lors de l'évaluation d'Issue 6.

### 1.11 Ce que cet épisode dit de la méthode

Ce défaut n'a été trouvé ni par les 35 tests unitaires, ni par les statuts du pipeline, ni par la confiance moyenne — tous étaient au vert. Il a fallu qu'un humain lise un PDF et le compare au texte produit.

C'est l'argument le plus concret en faveur de la vérité terrain : **elle ne sert pas seulement à produire un taux d'erreur en fin de chaîne, elle révèle des défauts qu'aucun indicateur interne ne peut signaler**, parce qu'un pipeline qui se note lui-même ne peut pas détecter qu'il mesure la mauvaise chose.


---

## 2. Nettoyage de texte et évaluation OCR (Issue 6)

Deux livrables : `ocr/text_cleaning.py` (nettoyage) et `scripts/evaluate_ocr.py` (taux de récupération mesuré contre la vérité terrain).

### 2.1 Ce que mesure l'évaluation, et ce qu'elle ne mesure pas

La question posée est **« l'OCR a-t-il préservé l'information ? »**, pas « sait-on l'extraire ? » qui est l'Issue 7. Concrètement : pour chaque valeur qu'un humain a lue sur le PDF source, cette valeur est-elle retrouvable dans le texte produit par le pipeline ?

La comparaison est **volontairement différenciée par type de champ** — une stratégie unique serait fausse :

| Champ | Méthode | Pourquoi |
|---|---|---|
| `reference_pv`, `concurrent_retenu` | sous-chaîne normalisée, puis similarité ≥ 0,85 | valeurs courtes et distinctives ; une lettre mal reconnue doit compter « approché », pas « absent » |
| `date_*` | sous-chaîne exacte, plusieurs formats testés | une date est juste ou fausse ; « approximativement le 28/12/2023 » n'a aucun sens |
| `montant_offre_retenue` | **comparaison numérique** (voir §2.3) | jamais une comparaison de chaîne |
| `acheteur_public`, `objet` | rappel de tokens distinctifs (mots vides écartés) | l'annotation reformule ces champs ; une sous-chaîne mesurerait la fidélité de la reformulation, pas l'OCR |
| `statut` | **exclu** | label dérivé (`ATTRIBUE` / `INFRUCTUEUX`), pas une chaîne présente dans le document |

### 2.2 Résultat mesuré (20 documents annotés, 134 valeurs)

| Champ | Trouvé |
|---|---:|
| `reference_pv` | **20/20 — 100 %** |
| `concurrent_retenu` | **18/18 — 100 %** |
| `objet` | 20/20 — 100 % |
| `acheteur_public` | 20/20 — 100 % |
| `date_ouverture_plis` | 19/20 — 95 % |
| `date_achevement_commission` | 16/18 — 89 % |
| `montant_offre_retenue` | 15/18 — 83 % |
| **TOTAL** | **96 %** |

Les deux champs les plus critiques pour l'Issue 7 — la référence du marché et le nom du concurrent retenu — sont retrouvés à **100 %**.

### 2.3 Les variations du taux global sont des corrections de biais de mesure, pas des dégradations du pipeline

**À ne jamais relire comme des régressions.** Le taux global est passé par 94 %, puis 93 %, puis 96 % au cours de l'Issue 6. **Le pipeline OCR n'a pas changé une seule fois entre ces chiffres** : à chaque étape, c'est l'instrument de mesure qui a été corrigé. Trois biais ont été trouvés et corrigés, chacun en vérifiant un résultat qui paraissait anormal plutôt qu'en l'acceptant.

| Étape | Taux | Ce qui a changé |
|---|---:|---|
| Mesure initiale | 94 % | — |
| Correction n°1 : comparaison numérique des montants | 93 % | 3 faux positifs supprimés, 1 faux négatif récupéré |
| Correction n°2 : regex n'avalant plus les sauts de ligne | 93 % | 1 montant présent cessait d'être masqué |
| Correction n°3 : dates écrites en toutes lettres | **96 %** | 4 dates correctement transcrites cessaient d'être comptées en échec |

La baisse comme la hausse sont donc des assainissements. Le 96 % final est le seul chiffre défendable des quatre.

La première version comparait les montants comme des chaînes, après une normalisation qui supprime tout caractère non alphanumérique. Cette normalisation **détruit la position du séparateur décimal** : `721224.86`, `72122.486` et `7212248.6` se réduisent tous à `72122486`. Trois montants séparés d'un facteur 100 étaient donc comptés identiques.

Correction : les montants sont désormais **parsés en flottants et comparés numériquement** (tolérance 0,01 DH), avec un parseur gérant les séparateurs de milliers (espace, point) et décimaux (virgule, point) réellement rencontrés.

Effet mesuré sur les 18 montants — 4 verdicts modifiés, chacun vérifié dans le texte source :

| Document | Attendu | Avant | Après | Ce que contient réellement le texte |
|---|---|---|---|---|
| `3d46704d` | 61 632,00 | trouvé | **absent** | `6163200` — l'OCR a perdu la virgule décimale |
| `ec81443a` | 922 770,00 | trouvé | **absent** | `922` seul — montant fragmenté sur plusieurs lignes |
| `03d5069b` | 183 600,00 | trouvé | trouvé | présent et correct |
| `0ebc5731` | 3 322 992,00 | absent | **trouvé** | `3 322 992,OO` — décimales écrites avec des lettres O |

Soit **3 faux positifs supprimés et 1 faux négatif récupéré**. Le taux de 83 % sur ce champ est donc plus faible mais **exact**, là où 94 % était flatteur et faux. La qualité réelle de l'OCR est inchangée ; seule sa mesure s'est assainie.

### 2.4 Recollage entre lignes : souhaitable pour le texte, faux pour les nombres

Un second défaut a été trouvé en corrigeant le premier : la regex d'extraction des montants utilisait `\s`, qui matche aussi les sauts de ligne. Elle fusionnait `1838 00` d'une ligne avec `183 600,00` de la suivante en un seul token valant 183 800 — masquant un montant pourtant présent.

La vérification a été étendue aux autres champs, car la normalisation appliquée au document entier supprime elle aussi les sauts de ligne. Résultat : **2 valeurs ne matchent que grâce à ce recollage, et les deux sont légitimes** — `TANSIFT` / `CONTRACTOR` et un nom de groupement, coupés par la mise en page du tableau.

D'où une distinction de principe, pas un compromis :

- **Champs texte** : recoller les lignes est *correct*. Les noms d'entreprises et les libellés sont couramment coupés par la mise en page ; une comparaison ligne par ligne produirait des faux négatifs.
- **Champs numériques** : recoller est *faux*. Un nombre ne s'étale jamais sur deux lignes, donc la fusion fabrique une valeur différente.

Aucune date n'est concernée (0 valeur dépendant d'un recollage). Le défaut était donc bien localisé aux montants, et il est clos.

### 2.5 HT / TTC — décision à prendre AVANT l'Issue 7

**Point ouvert, à trancher, pas seulement à documenter.**

Le champ `montant_offre_retenue` mélange aujourd'hui deux bases de calcul selon ce que le PDF source met en avant :

| Document | Montant retenu | Base |
|---|---|---|
| `aabc5317` (211/2025) | 9 269 719,80 | **TTC** (le PDF donne aussi 7 724 766,50 HT) |
| `ca886572` (205/2025) | 4 910 112,00 | **TTC** (HT correspondant : 4 091 760,00) |
| `07e10b77` (56/2024) | 2 196 000,00 | **HT** (tranche ferme) |
| `ec81443a` (118/2025) | 922 770,00 | **HT** (le PDF ne donne aucun TTC) |

Ce n'est pas un écart d'annotation : les acheteurs n'écrivent pas tous la même base, et certains PV ne donnent qu'une seule des deux valeurs.

**Conséquence si on ne tranche pas** : un écart de l'ordre du taux de TVA entre documents comparables. Toute statistique de l'Issue 10 (`total_amount`, `average_amount`, `market_share`) et tout red flag fondé sur les montants (`ideas.md` §2.6) seraient calculés sur des grandeurs non homogènes — un marché à 1 M HT et un marché à 1 M TTC ne représentent pas la même dépense publique.

**Ce qu'il faut décider avant d'écrire l'extraction (Issue 7)** :

1. L'extraction doit produire **deux champs distincts** — `montant_ht` et `montant_ttc` — plutôt qu'un `montant_offre_retenue` ambigu, et laisser à `None` celui que le document ne donne pas. **Ne jamais déduire l'un de l'autre** en appliquant un taux de TVA supposé : le taux varie selon la nature du marché, et une valeur calculée ne doit pas être stockée comme une valeur lue.
2. `data_dictionary.md` §3.1 doit être mis à jour en conséquence.
3. Les agrégations de l'Issue 10 doivent choisir **une seule base** et écarter explicitement les marchés où elle est absente, plutôt que de mélanger.

Tant que ce point n'est pas tranché, `montant_offre_retenue` de la vérité terrain doit être lu comme « le montant que le PDF met en avant », pas comme une grandeur homogène entre documents.

### 2.6 Le nettoyage n'apporte aucun gain mesurable — et c'est dit tel quel

`ocr/text_cleaning.py` transforme réellement le corpus (mesuré sur les 388 documents) :

| Transformation | Total | Documents touchés |
|---|---:|---:|
| Marques invisibles supprimées (U+200E / U+200F) | 9 267 | 298 |
| Caractères de police symbole restaurés | 439 | 18 |
| Lignes d'en-tête / pied de page répétées retirées | 15 | 7 |
| Arabe **isolé** dans `text_ar` (jamais supprimé) | 37 089 | 321 |

Mais sur la mesure de récupération : **93 % avant nettoyage, 93 % après, soit +0 point**. Testé aussi sur des regex d'extraction typiques de l'Issue 7 : 722 captures dans les deux cas, +0.

L'explication n'avait pas été anticipée : la normalisation de comparaison supprime déjà tout caractère non alphanumérique, donc elle neutralise d'avance exactement le bruit que le nettoyage retire. Les deux se recouvrent.

Le nettoyage garde une utilité non démontrée par cette mesure — lisibilité humaine, séparation de l'arabe pour le NER de l'Issue 8, robustesse si une regex future est moins tolérante — mais **il serait malhonnête de le présenter comme un gain de qualité OCR**. Il est conservé pour ces raisons, pas pour un bénéfice chiffré.

### 2.7 Un bug attrapé par la mesure elle-même

La première version de `strip_page_furniture` supprimait la ligne `Date d'ouverture des plis : Le 27/07/2026 à 12 heures` d'un PV multi-lots : le motif censé repérer les pieds de page `1/2` reconnaissait aussi le `27/07` d'une date, et la ligne se répétait une fois par lot.

L'évaluation l'a détecté comme une valeur de vérité terrain perdue (−0,7 point) **avant** que le nettoyage soit considéré comme acquis. Corrigé par un garde-fou explicite : une ligne portant une date complète n'est jamais traitée comme un pied de page, quoi qu'elle ressemble par ailleurs. Six cas de test couvrent la règle.

C'est l'argument concret en faveur de l'ordre suivi : construire la mesure d'abord, puis le traitement — et non l'inverse.

### 2.8 Correction n°3 — dates écrites en toutes lettres

Le champ `date_ouverture_plis` plafonnait à 80 %, ce qui paraissait bas pour une information aussi structurée. Vérification faite, un document du corpus ne contient **aucune date numérique** :

```text
- Date d'ouverture des plis : Le mardi 19 décembre 2023 à 12 heures.
```

`date_variants()` ne générait que des formes numériques (`19/12/2023`, `19122023`). Une date parfaitement transcrite par l'OCR était donc comptée en échec — troisième biais de mesure de la même famille que les deux précédents.

Correction : génération des formes textuelles françaises (`19 décembre 2023`) en plus des formes numériques. Les accents sont sans effet, la normalisation les supprimant des deux côtés.

**Effet mesuré : 4 dates récupérées.** `date_ouverture_plis` passe de 80 % à 95 %, `date_achevement_commission` de 83 % à 89 %, le taux global de 93 % à 96 %.

### 2.9 Les 6 échecs restants sont de vraies dégradations OCR

Après les trois corrections, chaque échec restant a été vérifié dans le texte source. **Aucun n'est un artefact de mesure** — le 96 % est un plancher réel, pas un plafond d'instrument.

| Document | Champ | Ce que contient le texte | Nature |
|---|---|---|---|
| `0ebc5731` | date achèvement | `tZlL2l2O25` | caractères illisibles (`l` pour `1`, `O` pour `0`) |
| `48f26629` | date ouverture | `13107 /2026` | le `/` lu comme `1` puis `0` |
| `48f26629` | date achèvement | absente | perte réelle |
| `3d46704d` | montant | `6163200` | virgule décimale perdue (facteur 100) |
| `ec81443a` | montant | `922` seul | montant fragmenté sur plusieurs lignes |
| `551178cf` | montant | absent | perte réelle |

Trois échecs sur six concernent des **séparateurs** (virgule décimale, barre de date) — le point faible mesuré de l'OCR sur ce corpus. C'est une information directement exploitable pour l'Issue 7 : les regex d'extraction devront tolérer un séparateur manquant ou mal reconnu, plutôt que d'exiger un format strict.

**Leçon méthodologique de l'Issue 6** : sur quatre chiffres successifs (94 %, 93 %, 93 %, 96 %), trois étaient faux. Aucun des trois biais n'aurait été trouvé sans vérifier dans le document source *pourquoi* un résultat paraissait anormal. Un taux d'erreur qu'on n'a pas cherché à contredire ne vaut rien.
