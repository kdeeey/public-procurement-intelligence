# Méthodologie — décisions techniques et limites mesurées

> Documente les choix qui ne se lisent pas directement dans le code : pourquoi tel paramètre plutôt qu'un autre, quelles limites ont été mesurées plutôt que supposées.
> Complète [`data_dictionary.md`](data_dictionary.md), [`discovery_notes.md`](discovery_notes.md) et [`ideas.md`](ideas.md).

Dernière mise à jour : 21/08/2026

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

### 1.7 Distribution finale mesurée (388 PV réels, correctifs actifs à l'échelle)

Deux runs successifs sur le corpus complet, comparables terme à terme :

| Statut | Run initial (390, `--psm 6` par piège de config, avant §1.3/§1.4) | Run final (388, `fra+ara` + `--psm 3` + exclusion pages vides + `EXCLUDED_STEMS`) |
|---|---:|---:|
| `native` | 113 (29,0 %) | 113 (29,1 %) |
| `ocr_success` | 267 (68,5 %) | **275 (70,9 %)** |
| `ocr_low_confidence` | 10 (2,6 %) | **0 (0,0 %)** |
| `ocr_failed` | 0 (0 %) | 0 (0 %) |

Le run final porte sur 388 documents (390 − 2 `EXCLUDED_STEMS`, voir §1.5). **0 document en faible confiance, 0 échec** — les correctifs tiennent à l'échelle, pas seulement sur les 10 cas ciblés initialement testés. 14 rotations OSD déclenchées sur ce run, plage `orientation_conf` 1,01-22,79 — cohérent avec le sondage précédent, aucune anomalie nouvelle.

### 1.8 Temps de traitement

Run final : 310,6 min (18 634,7 s) sur 388 documents, soit 48,0 s/document en moyenne — mais cette moyenne était tirée par deux facteurs distincts, un seul corrigé depuis :

1. **Contention machine intermittente** (applications tierces lourdes) — cause un ralentissement généralisé et réversible (rythme divisé par ~2 à ~15, revient à la normale dès la fermeture des applications). Non corrigeable côté code, limite d'environnement à connaître.
2. **Un document anormalement lourd** (`c87a91a5...`, 2026) : **7 133,9 s (1h58) à lui seul** dans ce run — 38 % du temps de calcul total pour 1 document sur 388. **Cause identifiée et corrigée** (voir §1.9) : ce n'était pas un vrai scan haute résolution mais un artefact de rendu dû à un `/MediaBox` PDF malformé.

**Rythme représentatif hors contention machine** (documents de résolution normale, fix §1.9 appliqué) : ~11-16 s/document. À dimensionner sur cette base pour Issue 6/7, pas sur la moyenne brute de 48 s/document du run qui a servi à découvrir ces deux problèmes.

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
