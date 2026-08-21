# Méthodologie — décisions techniques et limites mesurées

> Documente les choix qui ne se lisent pas directement dans le code : pourquoi tel paramètre plutôt qu'un autre, quelles limites ont été mesurées plutôt que supposées.
> Complète [`data_dictionary.md`](data_dictionary.md), [`discovery_notes.md`](discovery_notes.md) et [`ideas.md`](ideas.md).

Dernière mise à jour : 21/08/2026

---

## 1. Pipeline OCR (Issue 5)

Architecture : `ocr/pdf_to_image.py` (rendu + détection texte natif) → `ocr/preprocess.py` (orientation, deskew, denoise, binarisation) → `ocr/tesseract_engine.py` (Tesseract + OSD) → `ocr/pipeline.py` (orchestration, `ocr_status`).

### 1.1 `--psm 3` plutôt que `--psm 6`

Mesuré sur un cas réel contenant un tableau (`EXTRAIT DE PV - AOO N°57-2026.pdf`) : `--psm 6` (bloc uniforme) lit la valeur de `classement` comme un tiret cassé (« — ») ; `--psm 3` (segmentation automatique) la lit correctement (« 1 »). Confirmé sans régression sur 6 documents en prose (5 gains de +2,8 à +9,2, 1 régression négligeable de -0,2).

**Piège de configuration rencontré** : un `.env` local portait encore `OCR_PSM=6`, qui écrasait silencieusement ce défaut. La totalité du run de validation sur les 390 PV (§1.4) a d'abord tourné sous `--psm 6` sans que cela soit visible dans les logs — seule une relecture du fichier de configuration l'a révélé. Corrigé dans `.env` et `.env.example`. Leçon retenue : un défaut de code changé sans vérifier les surcharges d'environnement locales n'est pas réellement appliqué.

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

### 1.5 Cas `44b28d32...` — tableaux financiers denses (8 pages)

Ce document (tableau de montants par lot et par concurrent, listes d'entreprises répétées sur plusieurs colonnes) avait été classé *réellement dégradé* lors d'une première inspection réalisée sous `--psm 6` (avant la découverte du piège de configuration §1.1). Une fois `--psm 3` réellement appliqué, il passe à `ocr_success` (confiance 84,9 sur 8 pages). Les répétitions de noms d'entreprise observées dans le texte (ex. « NS MEDICAL » sur plusieurs lignes) correspondent à la structure réelle du tableau (une entreprise peut remporter plusieurs lots), pas à un artefact de reconnaissance — confirmé par une confiance homogène et élevée (76-89) sur chacune de ses pages.

**Conclusion : ce cas n'est plus un exemple de limite connue.** Il illustre plutôt à quel point une mauvaise configuration silencieuse (§1.1) peut faire passer un document parfaitement récupérable pour un cas dégradé — leçon méthodologique à retenir pour l'évaluation d'Issue 6/7 : toujours vérifier la configuration effective avant de conclure qu'un document est irrécupérable.

### 1.6 Distribution finale mesurée (390 PV réels, après les corrections ci-dessus)

Run de validation initial (avant correctifs langue/pages-vides, mais déjà sous le piège `--psm 6`) :

| Statut | n | % |
|---|---:|---:|
| `native` | 113 | 29,0 % |
| `ocr_success` | 267 | 68,5 % |
| `ocr_low_confidence` | 10 | 2,6 % |
| `ocr_failed` | 0 | 0 % |

Sur les 10 documents `ocr_low_confidence`, reclassés après les correctifs §1.3/§1.4 et l'application effective de `--psm 3` :

- **9/10 récupérés** en `ocr_success` (langue arabe : 6 cas ; page quasi-vide exclue de la moyenne : 1 cas ; correction de configuration `--psm` seule : 1 cas — `44b28d32...` ; combinaison langue + config : 1 cas)
- **1/10 reste `ocr_low_confidence`** (`9d2a5e07...`) — **à raison** : son unique page OCR est une page réellement blanche (luminosité mesurée 254,96/255, écart-type 3,1), confirmée visuellement. Le contenu utile du document (page 1, texte natif) est déjà disponible indépendamment de ce statut.

Le run complet sur les 390 PV n'a pas été rejoué avec les correctifs §1.3/§1.4 appliqués à l'échelle — seuls les 10 cas concernés l'ont été, par choix explicite pour limiter le temps de calcul. La distribution finale attendue à l'échelle serait donc légèrement meilleure que le tableau ci-dessus (≈ 276 `ocr_success`, ≈ 1 `ocr_low_confidence` justifié).

### 1.7 Temps de traitement

Run de 390 documents : 179 min au total, mais fortement affecté par une contention machine externe (applications tierces lourdes actives pendant une partie du run). Rythme observé une fois la machine libérée : ~12-13 s/document. À dimensionner sur cette base pour Issue 6/7, pas sur la moyenne brute de 27,5 s/document du run contentionné.
