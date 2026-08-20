# Dictionnaire de données — PMMP

> Référence définitive des champs, sources et modèles de données du projet.
> Basé sur l'exploration manuelle réelle du site (voir [`discovery_notes.md`](discovery_notes.md)) et 25+ documents réels collectés (consultations, PV, résultats définitifs) auprès de plus de 15 acheteurs publics différents.
> Remplace les hypothèses initiales du README (§6, §12, §33) là où elles ont été corrigées par l'exploration réelle.

Dernière mise à jour : 17/08/2026

---

## 1. Vue d'ensemble des sources

Trois types de pages/documents alimentent le pipeline, tous rattachés à un même marché, identifié par **`refConsultation`** :

```text
                 refConsultation (clé fiable)
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
  CONSULTATIONS      EXTRAIT DE PV    RESULTATS DEFINITIFS
  (page HTML)         (PDF)              (PDF)
        │                 │                 │
   métadonnées      liste complète      gagnant + montant
   du marché        des concurrents      uniquement
   (pas d'OCR)       + montants de
                      chacun + gagnant
```

- **Consultations** (recherche/listing + détail) → métadonnées du marché, disponibles en HTML, sans OCR.
- **Extrait de PV** (icône grise "pv", menu "Tous les extraits de PV") → source la plus riche pour l'attribution : liste tous les concurrents et leurs montants, pas seulement le gagnant.
- **Résultats définitifs** (icône rouge) → source plus simple, ne donne que le gagnant et son montant. Sert de source de secours si le PV n'est pas disponible pour un marché donné.

### ⚠️ Clé de jointure — `reference` seule ne suffit pas

> **Correction (20/08/2026)** : ce document affirmait auparavant que `reference` était la « clé commune » des trois sources. C'est **faux**, et mesuré comme tel sur le corpus réel.

`reference` est un **numéro de séquence interne à chaque acheteur**, pas un identifiant global. Deux marchés sans aucun rapport, chez deux acheteurs différents, portent couramment la même référence.

**Preuve mesurée** — la référence `04/2026` désigne simultanément quatre acheteurs distincts :

```text
04/2026 → RTAH  / CRBF - Commune rurale de BNI FRASSEN
04/2026 → RTT   / CRL  - Commune LAAOUAMA
04/2026 → RSMD  / CUAI - Commune urbaine de AIT IAAZA
04/2026 → RO    / CRT  - COMMUNE DE TAFOGHALT
```

Le même phénomène touche `01/2026`, `11/2026` et toutes les références courtes de type `NN/AAAA`. Sur la collecte de 1 350 consultations de contexte, 44 « correspondances » par référence textuelle avec le corpus PV se sont révélées être **100 % des faux positifs** entre acheteurs différents.

| Clé | Fiabilité | Usage |
|---|---|---|
| **`refConsultation`** | ✅ Identifiant interne du portail, globalement unique | **Clé de jointure à utiliser.** A produit 400/400 (100 %) de jointure lors de la collecte |
| (`acheteur_public`, `reference`) | ✅ Clé composite acceptable | Repli quand `refConsultation` est absent (ex. document PDF isolé sans URL source) |
| `reference` seule | ❌ **Ambiguë entre acheteurs** | Ne jamais l'utiliser seule comme clé — uniquement comme attribut d'affichage |

`refConsultation` est extractible de toute URL du portail (`...&refConsultation=1034020&orgAcronyme=f9f`) et doit être conservé sur chaque entité pour garantir la traçabilité (README §55).

**Sources écartées ou secondaires** :
- "Listes des marchés attribués" — dépôt de fichiers non structuré et incohérent, secondaire uniquement.
- "Annonce de synthèse de rapport d'audit" — bonus, donne des `(reference, objet, montant)` groupés par acheteur mais sans nom de gagnant.

---

## 2. Entité `Procurement` (Consultation)

Champs confirmés réels, capturés depuis la page de détail d'une consultation (HTML, pas d'OCR nécessaire) :

| Champ | Exemple réel | Notes |
|---|---|---|
| `reference` | `AON31/2024/SO2300UP` | Formats variables selon acheteur (`22/2026/DAAC/BG`, `10008361`, `AOO/01/G.SF/2026/ANEP`...) |
| `objet` | "Travaux de construction de pistes..." | Texte libre |
| `acheteur_public` | "DPET Khénifra" | = maître d'ouvrage |
| `type_annonce` | "Annonce de consultation" | Voir enum §5.1 |
| `mode_passation` | "Appel d'offres ouvert" | Voir enum §5.2, ~20 valeurs |
| `categorie_principale` | "Travaux" | Enum fermé : Travaux / Fournitures / Services |
| `lieu_execution` | "KHENIFRA" | |
| `estimation_dhs_ttc` | 133 075 758,00 | Montant estimé — confirmé disponible sur au moins un exemple |
| `caution_provisoire` | 2 000 000,00 MAD | Garantie bancaire exigée |
| `qualifications` | "B1;B3;B5;B6, Classe S" | Codes de classification technique |
| `domaines_activite` | "Travaux/Terrassements/..." | Texte hiérarchique |
| `allotissement` | Oui/Non | Si Oui → plusieurs lots, voir `Award` |
| `reserve_tpe_pme` | Oui/Non | |
| `date_mise_ligne` | 04/10/2024 11:26 | |
| `date_limite_remise_plis` | | |
| `lieu_ouverture_plis` | "Bureau des marchés de la D.P.E.T.L. de Khénifra" | |
| `dossier_consultation_url` | | Bundle ZIP/RAR — **pas toujours téléchargeable**, voir §4 |

---

## 3. Entité `Award` (Attribution — depuis PV ou Résultats définitifs)

### 3.1 Champs communs aux deux sources

| Champ | Notes |
|---|---|
| `reference` | Attribut d'affichage — **pas une clé** (ambiguë entre acheteurs, voir §1). Joindre sur `refConsultation`, ou à défaut sur (`acheteur_public`, `reference`) |
| `refConsultation` | **Clé de jointure vers `Procurement`** |
| `objet` | Parfois redondant avec `Procurement.objet`, à dédupliquer |
| `acheteur_public` (maître d'ouvrage) | |
| `date_ouverture_plis` | |
| `date_achevement_travaux_commission` | |
| `lot_numero` | Nullable — présent seulement si `Procurement.allotissement = Oui` |
| `concurrent_retenu` | Nom d'entreprise **ou groupement** (ex: "Groupement ART STAM SARL AU et TECH-LUX SARL AU") — jamais déduit par calcul, toujours lu explicitement |
| `montant_offre_retenue` | Nullable si pas de gagnant |
| `statut` | Voir enum §3.3 |
| `delai_execution` | Nullable — vu sur PV multi-lots uniquement (ex: "8 mois") |
| `president_commission` | Signataire |

### 3.2 Champs additionnels — PV uniquement (source la plus riche)

| Champ | Notes |
|---|---|
| `lieu_ouverture_plis` | |
| `journal_publication` (+ date) | Confirme aussi "Portail des marchés publics" comme canal |
| `liste_concurrents` | Tous les concurrents ayant déposé une offre |
| `montant_par_concurrent` | Montant de chaque concurrent (avant ET après vérification — peuvent différer) |
| `classement` | Parfois présent si plusieurs concurrents |
| `concurrents_ecartes` | Liste + raison (ex: réserve non levée, offre excessive) |
| `justification_choix` | Texte libre expliquant le choix de l'attributaire |
| `number_of_bidders` *(dérivé)* | `COUNT(liste_concurrents)` — feature pour le module IA |
| `amount_variation` *(dérivé)* | Écart entre l'offre retenue et les autres offres — feature IA |

### 3.3 Statuts d'attribution confirmés (`Award.statut`)

```text
ATTRIBUE              → un concurrent retenu, montant présent
INFRUCTUEUX            → aucune offre valable reçue
OFFRE_EXCESSIVE        → offre(s) reçue(s) mais rejetée(s) pour prix jugé trop élevé
```

Ne pas modéliser comme un simple booléen "gagné/perdu" — au moins 3 statuts distincts observés en pratique.

### 3.4 Variabilité de format à anticiper dans l'extraction

- Libellés de colonnes variables : "Montant de l'offre retenue" vs "**Montant MAX** de l'offre retenue" selon l'acheteur.
- Certains acheteurs (ex: SDR F.I.A.S.E.T.) écrivent le résultat en **texte libre** dans une seule cellule plutôt qu'en colonnes structurées — prévoir un fallback regex/NLP en plus du parsing de tableau.
- **Un document peut couvrir plusieurs marchés/lots à la fois** (ex: bulletins consolidés de la SRM-RSK, résultats CRRAR multi-lots) — ne pas supposer "1 PDF = 1 marché".
- Le gagnant n'est **pas toujours le moins-disant** — critère de sélection variable (mieux-disant technique+financier possible), toujours lire `concurrent_retenu` explicitement.

---

## 4. Entité `Document`

| Champ | Notes |
|---|---|
| `document_id` | |
| `reference` | Attribut d'affichage — **pas une clé** (ambiguë entre acheteurs, voir §1) |
| `refConsultation` | **Jointure vers `Procurement`** |
| `document_type` | `CONSULTATION` \| `PV` \| `RESULTAT_DEFINITIF` \| `RAPPORT` \| `AUTRE` |
| `source_url` | |
| `file_hash` | |
| `is_ocr_required` | Déterminé au runtime : `False` si texte natif extractible (PyMuPDF), `True` si scan (ex: fichiers "Scanné avec CamScanner") |
| `is_publicly_downloadable` | `False` si le téléchargement est bloqué par le formulaire d'identification (`EntrepriseDemandeTelechargementDce`) — voir §6 |

### Stratégie OCR confirmée

```text
PDF
 │
 ▼
Tentative d'extraction de texte natif (PyMuPDF)
 │
 ├── Texte présent et propre  → pas d'OCR, extraction directe
 │
 └── Vide / illisible          → Tesseract OCR sur l'image de la page
```

Confirmé sur l'échantillon réel : les deux cas existent en pratique — le pipeline OCR du README (§11) était donc la bonne conception dès le départ, maintenant validée par des preuves réelles.

**Proportion mesurée (390 extraits de PV, 100 par an sur 2023-2026, 18/08/2026)** : **70,8 % de documents scannés** (276/390) contre 29,2 % de PDF natifs. Une première estimation, faite sur ~25 documents, annonçait l'inverse — elle est corrigée ici et dans [`discovery_notes.md`](discovery_notes.md) §2.11. L'OCR est donc le chemin principal du pipeline, pas un cas de repli : `is_ocr_required = True` sera la valeur dominante en base.

---

## 5. Entité `Company`

| Champ | Notes |
|---|---|
| `company_name` | Seul champ fiable — clé de regroupement |
| `ICE` | **Non disponible publiquement dans nos échantillons.** Vu uniquement comme champ auto-déclaré dans le formulaire de téléchargement (non vérifiable), ou comme ICE de l'*acheteur* (pas de l'entreprise gagnante) dans certains en-têtes de document. Toujours nullable. |
| `RC` | Non disponible publiquement. Nullable. |
| `is_groupement` | `True` si `concurrent_retenu` désigne un consortium de plusieurs entreprises |

**Limitation à documenter dans le rapport final** : sans ICE/RC, le regroupement par entreprise repose uniquement sur `company_name` en texte libre → nécessite une normalisation de nom avant agrégation (casse, suppression de préfixes "STE"/"Société"/suffixes "SARL"/"SARL AU", espaces).

---

## 6. Limite confirmée — formulaire d'identification

Pour certaines consultations, télécharger le "Dossier de consultation" redirige vers un formulaire demandant nom, email, raison sociale, ICE auto-déclaré, et l'acceptation des conditions générales. **Le scraper ne remplit jamais ce formulaire** (voir `discovery_notes.md` §2.8 et §4). Ces documents sont marqués `is_publicly_downloadable = False` ; seules les métadonnées déjà en HTML sont conservées.

---

## 7. Enums confirmés

### 7.1 `type_annonce`
```text
Annonce d'information
Annonce de résultat définitif
Annonce d'extrait de PV
Annonce de rapport d'achèvement
Annonce de décision de résiliation
Annonce de rapport de présentation
```

### 7.2 `mode_passation` (extrait, liste complète ~20 valeurs)
```text
Appel d'offres ouvert / ouvert simplifié / restreint / avec présélection (Phase 1/2)
Concours Architectural / Phase 1/2
Consultation architecturale (négociée, ouverte, restreinte — plusieurs variantes)
Demande de Cotation Ouverte/Restreinte (Banques Multilatérales de Développement)
Dialogue compétitif (Phase 1/2/3)
Enchère électronique inversée
Marché négocié avec/sans publicité préalable (Phase 1/2)
Appel à manifestation d'intérêt
```

### 7.3 `categorie_principale`
```text
Travaux
Fournitures
Services
```

---

## 8. Ce qui reste incertain / à surveiller pendant le développement

- Disponibilité systématique du PV vs Résultats définitifs par marché — pas encore confirmé si tous les marchés ont les deux, un seul, ou aucun.
- Le critère exact de sélection du gagnant (moins-disant strict vs offre économiquement la plus avantageuse) n'est pas toujours explicite dans le document — parfois juste "justification_choix" en texte libre.
- Cohérence de format intra-acheteur dans le temps (probable mais pas vérifié sur plusieurs années pour un même acheteur).
