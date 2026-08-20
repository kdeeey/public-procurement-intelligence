# Paramètres de recherche PMMP — référence complète

> Relevé exhaustif du formulaire « Recherche avancée » du PMMP, avec **vérification
> empirique de chaque filtre** (19/08/2026). Plusieurs champs du formulaire sont
> silencieusement ignorés par le serveur : les envoyer ne produit aucune erreur mais
> ne restreint pas les résultats.
>
> Sert de base à `scripts/download_extraits_pv.py` et aux futurs spiders (Issues 2 et 3).

---

## 1. Mécanique de la recherche (à connaître avant tout)

Le portail est une application **PRADO** (PHP). Conséquences concrètes :

| Point | Réalité |
|---|---|
| Lancer une recherche | `POST` de **tout** le formulaire vers `index.php?page=entreprise.EntrepriseAdvancedSearch&AllAnn` (l'attribut `action`), avec `...AdvancedSearch$lancerRecherche` renseigné |
| État de session | `PRADO_PAGESTATE` (~16 Ko) doit être relu dans **chaque** réponse et renvoyé dans la requête suivante |
| Pagination | `&page_courante=N` dans l'URL est **ignoré** (toutes les pages renvoient la page 1). La vraie pagination est un postback : `PRADO_POSTBACK_TARGET = ctl0$CONTENU_PAGE$resultSearch$PagerTop$ctl2` |
| ⚠️ Piège | `PagerTop$ctl3` = **dernière page**, pas page suivante |
| Taille de page | `ctl0$CONTENU_PAGE$resultSearch$listePageSizeTop` accepte `10, 20, 50, 100, 500` — utiliser 500 réduit fortement le nombre de requêtes |
| Tri | Résultats triés par date de mise en ligne **décroissante** (le plus récent d'abord) |

Préfixe commun des champs de recherche : `ctl0$CONTENU_PAGE$AdvancedSearch$`
(noté `…$` ci-dessous).

---

## 2. Filtres QUI FONCTIONNENT ✅

Vérifiés par comptage : total sans filtre = **135 000** annonces.

### `…$annonceType` — Type d'annonce

| Valeur | Libellé | Résultats |
|---|---|---|
| `0` | Tous les types | 135 000 |
| `2` | Annonce d'information | |
| `4` | Annonce de résultat définitif | |
| **`5`** | **Annonce d'extrait de PV** | **94 868** |
| `6` | Annonce de rapport d'achèvement | |
| `8` | Annonce de décision de résiliation | |
| `9` | Annonce de rapport de présentation | |

### `…$categorie` — Catégorie principale

| Valeur | Libellé | Résultats (avec `annonceType=5`) |
|---|---|---|
| `0` | Toutes | 94 868 |
| **`1`** | **Travaux** | **34 299** |
| **`2`** | **Fournitures** | **26 600** |
| **`3`** | **Services** | **33 969** |

> Partition exacte : 34 299 + 26 600 + 33 969 = 94 868. Le filtre est donc
> parfaitement appliqué et sans recouvrement.

### `…$procedureType` — Mode de passation

Vérifié : `procedureType=1` + `annonceType=5` → **77 106** résultats.

| Valeur | Libellé |
|---|---|
| `0` | Tous les types de procédure |
| `1` | Appel d'offres ouvert |
| `50` | Appel d'offres ouvert simplifié |
| `2` | Appel d'offres restreint |
| `34` / `35` | Appel d'offres avec présélection — Phase 1 / 2 |
| `56` / `57` | AO avec présélection — Partenariat Public-Privé — Phase 1 / 2 |
| `58` / `59` | AO avec préqualification — Partenariat Public-Privé — Phase 1 / 2 |
| `4` / `47` | Concours Phase 1 / Phase 2 |
| `40` | Concours Architectural |
| `39` / `52` / `51` | Consultation architecturale ouverte / ouverte simplifiée / restreinte |
| `44` / `45` | Consultation architecturale négociée avec publicité — Phase 1 / 2 |
| `46` | Consultation architecturale négociée sans publicité |
| `42` / `43` | Marché négocié avec publicité préalable — Phase 1 / 2 |
| `9` | Marché négocié sans publicité préalable |
| `53` / `54` / `55` | Dialogue compétitif — Phase 1 / 2 / 3 |
| `60` / `61` | Demande de Cotation Ouverte / Restreinte (Banques Multilatérales) |
| `37` | Appel à manifestation d'intérêt |
| `38` | Enchère électronique inversée |

### `…$keywordSearch` — Mots-clés

Cherche dans la référence, l'intitulé et l'objet.
Vérifié : `keywordSearch=travaux` + `annonceType=5` → **37 392** résultats.

### `…$reference` — Référence exacte de la consultation

Champ texte libre. Combinable avec `…$rechercheFloue` (`floue` / `exact`).

### `…$organismesNames` — Entité publique

78 valeurs, codes alphanumériques courts (`b5j` = Administration de la défense
nationale, `w7t` = ANEF, `w6x` = CDG, `z6n` = Cour des comptes…).
La liste complète est dans le `<select>` de la page de recherche.

---

## 3. Filtres IGNORÉS par le serveur ❌

**À ne pas utiliser — ils donnent une fausse impression de filtrage.**

| Champ | Comportement constaté |
|---|---|
| `…$dateMiseEnLigneCalculeStart` / `…End` | **Totalement ignoré.** Une fenêtre d'un seul jour (`17/08/2026`→`18/08/2026`) renvoie les 94 868 résultats, tout comme `01/01/2023`→`18/08/2026`. Valeurs par défaut affichées : 6 derniers mois. |
| `…$classification` | **Ignoré.** `classification=2` (Collectivité locale) renvoie 94 868, soit le total inchangé. Valeurs proposées : `0` Toutes, `1` État, `2` Collectivité locale, `3` Établissement public. |

**Conséquence pratique** : toute sélection par période doit se faire **côté client**,
en parcourant les pages (triées par date décroissante) et en filtrant les lignes —
c'est la stratégie retenue dans `scripts/download_extraits_pv.py`.

---

## 4. Autres champs du formulaire

| Champ | Type | Note |
|---|---|---|
| `…$orgName` | texte | Nom d'entité publique en saisie libre |
| `…$entityPurchaseNames` | select | Acheteur — peuplé dynamiquement selon l'entité |
| `…$qualification$idsQualification` | texte | Codes de qualification technique (popup) |
| `…$agrements$idsSelectedAgrements` | caché | Agréments (popup) |
| `…$idsSelectedGeoN2` / `numSelectedGeoN2` | caché | Lieu d'exécution (popup géographique) |
| `…$domaineActivite$displayDomaine` | texte | Domaines d'activité (popup) |
| `…$considerationsEnvironnementales` | radio | `…EnvOui` / `…EnvNon` / `…EnvIndifferent` |
| `…$type_rechercheEntite` | radio | `floue` / `exact` |
| `…$rechercheFloue` | radio | `…$floue` / `…$exact` |
| `…$choixInclusionDescendancesServices` | radio | `…$entiteSeule` / `…$inclureDescendances` |

### Champs cachés à renvoyer tels quels

```text
PRADO_PAGESTATE            (~16 Ko — obligatoire, change à chaque réponse)
PRADO_POSTBACK_TARGET      (vide, sauf postback de pagination)
PRADO_POSTBACK_PARAMETER
```

---

## 5. Raccourcis d'URL (GET)

Ces drapeaux pré-règlent le formulaire sans POST :

```text
&AllAnn                    recherche avancée, toutes annonces (formulaire seul, 0 résultat)
&AllCons                   toutes les consultations
&searchAnnCons             déclenche l'affichage des résultats
&AvisExtraitPV             extraits de PV
&AvisAttribution           résultats définitifs
&AvisInformation           annonces d'information
&AvisRapportAchevement     rapports d'achèvement
&AvisRapportPresentation   rapports de présentation
&AvisdecisionResiliation   décisions de résiliation
&panierEntreprise          panier
```

⚠️ `&AllAnn` **seul** ne renvoie aucun résultat : il n'affiche que le formulaire.
Il faut soit y ajouter `&searchAnnCons`, soit faire le POST décrit en §1.

---

## 6. Recette recommandée pour un corpus ciblé

Exemple — tous les extraits de PV de la catégorie Travaux :

```python
data[ADV + "annonceType"] = "5"      # extrait de PV
data[ADV + "categorie"]   = "1"      # Travaux
data[ADV + "lancerRecherche"] = "Lancer la recherche"
# -> 34 299 résultats, triés du plus récent au plus ancien
# puis pagination par postback + filtrage des années côté client
```

Restreindre la catégorie **avant** de paginer divise le parcours par ~3 et garantit
un corpus homogène — indispensable pour comparer des montants entre marchés
(cf. `data_dictionary.md` §3.2, features `amount_variation` et `market_share`).
