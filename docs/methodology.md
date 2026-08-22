# Méthodologie — décisions techniques et limites mesurées

> Documente les choix qui ne se lisent pas directement dans le code : pourquoi tel paramètre plutôt qu'un autre, quelles limites ont été mesurées plutôt que supposées.
> Complète [`data_dictionary.md`](data_dictionary.md), [`discovery_notes.md`](discovery_notes.md) et [`ideas.md`](ideas.md).

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

Le corpus contient des PV **partiellement ou totalement rédigés en arabe** — pas seulement des en-têtes bilingues (déjà documenté dans `discovery_notes.md` §2.9), mais des pages entières. Avec `lang='fra'` seul, ces pages tombaient à une confiance quasi nulle (0,0 à 30,5), non pas parce que le scan était dégradé mais parce que le modèle de langue ne pouvait pas reconnaître le script.

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

