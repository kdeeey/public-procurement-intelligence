# PMMP — Brief de conception du dashboard

> **À qui s'adresse ce document.** Au concepteur de l'interface. Il décrit le
> produit, les données réellement disponibles, les états à dessiner et les
> contraintes non négociables. Il ne décrit **pas** l'esthétique : couleurs,
> typographie et identité visuelle relèvent de la vision du commanditaire.
>
> **Ce qu'il faut en retenir avant tout** : ce produit affiche des données
> **très incomplètes**, et c'est sa caractéristique principale. Un tiers à deux
> tiers des cellules seront vides selon les colonnes. L'interface doit rendre
> cette incomplétude **lisible et honnête**, jamais la masquer. Un design qui
> suppose des données pleines sera inutilisable ici.
>
> Chiffres relevés le 28/08/2026 sur le corpus réel.

---

## 1. Le produit en une page

| | |
|---|---|
| **Nom** | PMMP — analyse des marchés publics marocains |
| **Nature** | Prototype académique (projet étudiant), non déployé |
| **Utilisateur** | Un analyste qui doit décider **par quels dossiers commencer** |
| **Question à laquelle il répond** | « Quels marchés méritent un examen humain en priorité, et pourquoi ? » |
| **Question à laquelle il NE répond PAS** | « Ce marché est-il frauduleux ? » |
| **Volume** | 454 marchés · 149 acheteurs · 4 années (2023-2026) |
| **Technologie** | Streamlit (Python) — voir §11 pour ce que cela permet et interdit |

### Le parcours à servir

```text
Vue globale          « où en est le corpus ? »
      ↓
Exploration          « quels marchés existent ? »
      ↓
Marchés atypiques    « lesquels regarder en priorité ? »
      ↓
Explication          « pourquoi celui-là ? »
      ↓
Qualité des données  « puis-je m'y fier ? »
      ↓
Décision humaine     l'analyste tranche, jamais le système
```

---

## 2. Contraintes non négociables

Ces règles ne sont pas des préférences de style. Elles engagent la crédibilité
du travail, et une maquette qui les enfreint sera refusée.

### 2.1 Vocabulaire

| ✅ À utiliser | ❌ Interdit |
|---|---|
| marché atypique | fraude détectée |
| signal | corruption détectée |
| red flag | fraude certaine |
| priorité d'analyse | probabilité de corruption |
| qualité des données | réseau de corruption |
| données insuffisantes | entreprise suspecte |
| aide à l'analyse · analyse humaine | entreprise à risque |

Un score élevé signifie **uniquement** : ce marché présente des
caractéristiques inhabituelles par rapport aux autres marchés du corpus.

### 2.2 Une donnée absente n'est jamais un zéro

C'est la règle la plus importante de tout le système, et elle a un coût
visuel : **il faut dessiner l'absence**.

| Situation | Affichage attendu | Jamais |
|---|---|---|
| Montant non extrait du document | « Non disponible » ou cellule vide | `0 DH` · `—` ambigu |
| Aucun soumissionnaire lisible | « Non disponible » | `0` |
| Gagnant non identifié | « Non identifié » | case vide sans explication |
| Règle non applicable | « Non évaluable » | « inactif » ou pastille verte |
| Analyse impossible | « Données insuffisantes » | « Risque faible » |

**Quatre états traversent toute la chaîne** et doivent rester distinguables à
l'œil :

```text
KNOWN           l'information a été lue dans le document
UNKNOWN         le document ne la porte pas — on ne sait pas
INVALID         elle a été lue mais elle est incohérente
NOT_APPLICABLE  elle n'a pas de sens pour ce marché
```

> **« Données insuffisantes » n'est pas un niveau de risque bas.** C'est un
> état distinct. Le confondre visuellement avec « Faible » (même couleur, même
> position dans une échelle) serait l'erreur la plus grave possible : un
> marché dont on ne sait rien apparaîtrait comme rassurant.

### 2.3 Sémantique des couleurs — proposition à valider

| Rôle | Usage | Réservé à |
|---|---|---|
| Couleur principale | navigation, titres, éléments structurants | l'identité |
| **Rouge** | **exclusivement** les signaux les plus prioritaires | jamais décoratif |
| **Orange** | signaux intermédiaires | jamais décoratif |
| Vert | états positifs, information présente et valide | |
| **Gris / neutre** | **données insuffisantes, non évaluable** | ne doit ressembler ni au vert ni au rouge |
| Jaune / ambre | avertissement de qualité (donnée incohérente, valeur imputée) | |

Le point crucial : **« données insuffisantes » a besoin d'une couleur qui ne
soit ni rassurante ni alarmante.** Un gris neutre convient ; un vert serait
mensonger, un rouge serait une accusation.

---

## 3. Les données réelles — à lire avant de dessiner

### 3.1 Taux de remplissage mesurés (454 marchés)

| Champ | Rempli | Vide | Conséquence de conception |
|---|---:|---:|---|
| Objet | **100 %** | 0 % | toujours présent, mais **très long** (§3.2) |
| Acheteur | **100 %** | 0 % | toujours présent, long aussi |
| Procédure | **100 %** | 0 % | mais **2 valeurs couvrent 98 %** → un donut sera un cercle plein |
| Secteur | **100 %** | 0 % | 3 valeurs équilibrées → bon candidat pour un graphique |
| Nombre de soumissionnaires | 83 % | **17 %** | prévoir l'état vide |
| Date d'ouverture | 69 % | **31 %** | un filtre par date exclurait un tiers du corpus |
| **Référence** | 86 % | **14 %** | ⚠️ **l'identifiant naturel manque pour 65 marchés** |
| **Montant TTC** | **37 %** | **63 %** | ⚠️ **la colonne sera vide dans deux tiers des lignes** |
| Gagnant (marchés attribués) | 65 % | 35 % | prévoir « Non identifié » |

> **Deux conséquences à prendre au sérieux.**
>
> 1. **La colonne « Montant » est vide 2 fois sur 3.** Une maquette qui la met
>    en évidence donnera l'impression d'un produit cassé. Deux options :
>    l'afficher discrètement avec un état vide soigné, ou la sortir du tableau
>    principal vers la fiche détail.
> 2. **La « Référence » manque pour 14 % des marchés.** Elle ne peut pas être
>    l'unique identifiant visible. Prévoir un repli (`award_id`, un numéro
>    interne) ou une mention « sans référence ».

### 3.2 Longueurs de texte (dimensionnement des colonnes)

| Champ | Médiane | 90ᵉ centile | Maximum |
|---|---:|---:|---:|
| Référence | 11 car. | 15 | 22 |
| Procédure | 21 car. | 31 | 49 |
| Acheteur | **60 car.** | 84 | 118 |
| **Objet** | **124 car.** | **281** | **778** |

> **L'objet ne peut pas tenir dans une colonne de tableau.** 124 caractères de
> médiane. Il faut décider : troncature à ~60 caractères avec info-bulle,
> ou affichage sur deux lignes, ou renvoi vers la fiche détail. **C'est une
> décision de design à prendre explicitement**, pas à subir.

### 3.3 Volumes par état (pour dimensionner les vues)

```text
PRIORITÉ D'ANALYSE            QUALITÉ DES DONNÉES        CONFIANCE
  Très prioritaire     26       Excellent    62            Élevée        163
  Prioritaire          25       Bon         141            Moyenne        82
  À surveiller         61       Moyen       137            Faible         34
  Faible              167       Faible      114            Insuffisante   35
  Données insuff.      35
```

La liste utile à un analyste fait donc **~50 lignes** (Très prioritaire +
Prioritaire), pas 454. La pagination n'est pas un enjeu majeur ; la **lisibilité
des 50 premières lignes**, si.

### 3.4 Ce qui n'existe pas et n'existera pas

| Demandé souvent | Réalité |
|---|---|
| Estimation administrative / écart au prix estimé | **0 marché sur 454** — la page d'un marché attribué ne la porte plus |
| Localisation géographique exploitable | absente de la table analytique · pas de carte possible |
| Identifiant fiscal (ICE/RC) des entreprises | non publié sur le portail |
| Historique d'une entreprise | 93 % des entreprises n'ont **qu'un seul marché** |
| Taux de détection / précision du modèle | **aucune vérité terrain** — aucun marché n'est étiqueté |

⚠️ **Ne pas prévoir de carte, de graphe d'entreprises, ni d'indicateur de
performance du modèle.** Les données ne les permettent pas.

---

## 4. Architecture — 5 pages

```text
┌──────────────┬──────────────────────────────────────────┐
│              │                                          │
│  [ Logo ]    │   TITRE DE LA PAGE                       │
│              │   sous-titre court                       │
│  Vue         │                                          │
│  générale    │   ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐   │
│              │   │KPI │ │KPI │ │KPI │ │KPI │ │KPI │   │
│  Marchés     │   └────┘ └────┘ └────┘ └────┘ └────┘   │
│  publics     │                                          │
│              │   ┌──────────────┐ ┌──────────────┐     │
│  Anomalies   │   │  graphique   │ │  graphique   │     │
│              │   └──────────────┘ └──────────────┘     │
│  XAI         │                                          │
│              │                                          │
│  Importation │                                          │
│              │                                          │
│  ──────────  │                                          │
│  Prototype   │                                          │
│  académique  │                                          │
└──────────────┴──────────────────────────────────────────┘
```

**Sidebar** : 5 entrées de navigation. Pas de « Paramètres » ni de
« Déconnexion » — **aucune authentification n'existe** dans le projet, ces
entrées mentiraient sur les capacités du produit.

---

## 5. PAGE 1 — Vue générale

**Objectif** : comprendre l'état du corpus en 10 secondes. Page exécutive,
aucun détail technique.

### Éléments

**En-tête** : titre « Vue générale » · sous-titre « Synthèse du corpus et des
signaux d'analyse » · période couverte (2023-2026, avec mention que la
dernière année est incomplète).

**5 cartes KPI** — valeurs réelles actuelles :

| Carte | Valeur | Précision à afficher |
|---|---:|---|
| Total marchés | **454** | dont 314 attribués, 140 infructueux |
| Marchés analysés | **279** | ceux que le modèle peut scorer |
| Marchés atypiques | **28** | signalés pour analyse humaine |
| Données insuffisantes | **35** | analyse non fiable — **état distinct** |
| Qualité moyenne des données | **69/100** | avec le libellé (« Bon ») |

> La carte « Marchés atypiques » ne doit **jamais** être stylée comme une
> alerte de sécurité (rouge vif, icône de danger). C'est une charge de travail,
> pas un incident.

**2 à 3 graphiques maximum :**

1. **Marchés par année** — barres. 4 points (68 · 80 · 86 · 80). ⚠️ La dernière
   année est **tronquée** : elle doit être visuellement distinguée (hachures,
   opacité réduite) et annotée.
2. **Répartition par secteur** — 3 modalités équilibrées (Travaux, Services,
   Fournitures). Bon candidat pour un donut.
   ⚠️ **Ne pas faire de donut sur la procédure** : 2 valeurs couvrent 98 %, le
   graphique serait un cercle plein. Utiliser des barres horizontales.
3. **Répartition des priorités** — 5 catégories, dont « Données insuffisantes »
   qui doit être visuellement **hors de l'échelle de gravité**, pas à
   l'extrémité basse.

### Ne pas mettre sur cette page

SHAP · détails du modèle · pipeline technique · features · PostgreSQL · OCR ·
benchmark · réseau d'entreprises.

### Suggestions

- Une phrase d'accroche sous les KPI : *« 28 marchés sur 279 analysés
  présentent des caractéristiques atypiques »* — plus parlant que des chiffres
  isolés.
- Un lien direct « Voir les marchés prioritaires » vers la page 3.
- L'avertissement méthodologique en pied de page, discret mais présent.

---

## 6. PAGE 2 — Marchés publics

**Objectif** : catalogue explorable de tous les marchés.

### Éléments

**Barre de recherche** : « Rechercher un marché, un objet, un organisme… »
(recherche sur référence, objet, acheteur).

**Filtres** — uniquement ceux dont les données existent :

| Filtre | Modalités réelles | Remarque |
|---|---|---|
| Année | 4 (2023-2026) | |
| Procédure | 8, dont 2 dominantes | prévoir « Autres » |
| Secteur | 3 | équilibré |
| Acheteur | **149** | ⚠️ trop pour une liste déroulante plate — prévoir un champ de recherche |
| Priorité | 5 | |
| Qualité des données | 4 niveaux ou curseur | |

Bouton **Réinitialiser**.

**Tableau — 8 colonnes maximum.** Proposition :

```text
Référence │ Objet │ Acheteur │ Procédure │ Montant │ Priorité │ Qualité │ Red flags
```

Contraintes rappelées : objet à tronquer (124 car. de médiane), montant vide
63 % du temps, référence absente 14 % du temps.

**Sélection d'une ligne** → panneau de détail **sous** le tableau, ou lien vers
la page XAI. **Pas de panneau latéral permanent** qui écraserait le tableau.

### Suggestions

- Tri par défaut : priorité décroissante (pas par référence).
- Un compteur « X marchés affichés sur 454 » sous les filtres.
- Les lignes « Données insuffisantes » : visuellement en retrait (texte
  atténué), **jamais masquées** — les cacher reviendrait à dissimuler une
  limite du système.
- Une info-bulle sur l'objet tronqué plutôt qu'un retour à la ligne, qui
  déséquilibrerait les hauteurs de ligne.

---

## 7. PAGE 3 — Anomalies

**Objectif** : les marchés signalés. **Techniquement, c'est la page 2 avec un
filtre préréglé** — même tableau, même composant. À dessiner comme une variante,
pas comme une page indépendante.

### Éléments

**Titre** : « Marchés atypiques »
**Sous-titre** : « Marchés présentant des caractéristiques atypiques selon le
modèle »

**Avertissement, discret mais visible** :

> *Les signaux présentés sont des indicateurs statistiques destinés à aider
> l'analyse humaine. Ils ne constituent pas une preuve de fraude ou de
> corruption.*

**4 cartes KPI** : marchés signalés (28) · très prioritaires (26) ·
prioritaires (25) · données insuffisantes (35).

**Le même tableau que la page 2**, filtré, avec deux colonnes en plus :
**stabilité** (n/10) et **red flags** (badges).

**Badges de red flags** — élément à concevoir avec soin :

```text
RF01  RF03        ← actifs, colorés
RF02              ← non évaluable, gris, distinct visuellement
```

Chaque badge porte une info-bulle : nom complet + description + sévérité.

### Suggestions

- Un filtre « red flag actif » (RF01 à RF05).
- Un filtre « stabilité ≥ 8/10 » : les signaux robustes d'abord.
- Un indicateur de stabilité compact et lisible (par exemple 10 points dont
  n remplis) plutôt qu'un texte « 9/10 ».

---

## 8. PAGE 4 — XAI · Explicabilité

**La page la plus importante.** C'est elle qui justifie le produit : elle
répond à *pourquoi ce marché*.

**Sélecteur de marché** en haut, trié par priorité décroissante.

### 8 blocs, dans cet ordre

**Bloc 1 — Résumé** · 4 indicateurs

```text
PRIORITÉ            SCORE D'ANOMALIE      QUALITÉ DONNÉES     STABILITÉ
Très prioritaire    89,8 / 100            60 / 100            10 / 10
```

**Bloc 2 — Le marché** · référence, objet, acheteur, procédure, secteur, date,
montant, gagnant, nombre de soumissionnaires, exclusions.
→ Toute valeur absente affiche **« Non disponible »**.

**Bloc 3 — Red flags** · une ligne par règle :

```text
🔴 RF01 — Faible concurrence          ACTIF         sévérité élevée
   Un seul soumissionnaire identifié dans le document.

⚪ RF02 — Exclusions atypiques        NON ÉVALUABLE
   L'information nécessaire n'a pas été lue dans le document.

🟢 RF03 — Montant atypique            INACTIF       sévérité moyenne
```

→ Les trois états doivent être **immédiatement distinguables**. C'est ici que
le gris de « non évaluable » compte le plus.

**Bloc 4 — Comparaison aux marchés comparables**

```text
Groupe de comparaison : Travaux × AO ouvert × 2025
Marchés comparables   : 41
Médiane du groupe     : 620 000 DH
Ce marché             : 14 000 000 DH   (+2 158 %)
Position              : au-dessus de 100 % des comparables
```

⚠️ **N'existe que pour 67 marchés sur 314 (21 %).** Pour les 79 % restants, ne
pas afficher une comparaison vide : soit masquer le bloc, soit afficher une
explication courte. **Ne jamais inventer une médiane.**

**Bloc 5 — SHAP** · barres horizontales, 3 contributions maximum :

```text
Montant du marché              ████████
Nombre de soumissionnaires     █████
Part de concurrents écartés    ███
```

Sous le graphique, une mention obligatoire : *SHAP explique la sortie du
modèle, pas la réalité du marché.*

**Bloc 6 — Explication en langage clair** · une phrase générée.

**Bloc 7 — Qualité des données** · les 5 dimensions avec leur état :

```text
Data Quality : 60 / 100 — Moyen

✓ Montant          lu dans le document
✓ Concurrence      lu dans le document
⚠ Exclusions       lu mais incohérent
? Date             absent du document
✓ Gagnant          lu dans le document
```

**Bloc 8 — Avis de l'analyste** · trois boutons (Pertinent · Faux positif ·
À examiner) + zone de commentaire.
→ Mention : *cet avis ne modifie pas le modèle.*

### Suggestions

- Navigation « marché précédent / suivant » pour enchaîner les examens.
- Si le marché est **plafonné par une confiance faible**, l'expliquer
  visuellement : *« score élevé, mais données faibles — non classé
  prioritaire »*. **C'est le moment le plus convaincant du produit** ; il
  mérite un traitement graphique dédié.
- Un bandeau distinct si le marché est « non scorable » : pas de score, pas de
  SHAP, seulement les informations disponibles et la raison.

---

## 9. PAGE 5 — Importation

⚠️ **À concevoir avec prudence : le pipeline n'accepte pas de CSV.** La chaîne
ingère des **PDF** (scraping → OCR → extraction). Une page qui promettrait
« importez vos données » mentirait sur les capacités du produit.

**Périmètre honnête** : une page de **validation de fichier** — dépôt, contrôle
du format, colonnes reconnues et manquantes, aperçu, **sans chargement en
base**, et qui le dit.

Éléments : zone de dépôt · résultat de validation (nombre de lignes, colonnes
reconnues, colonnes manquantes, erreurs, avertissements) · aperçu · mention
explicite « validation seule, aucune donnée n'est ajoutée au corpus ».

---

## 10. Bibliothèque de composants

| Composant | Où | Points d'attention |
|---|---|---|
| **Carte KPI** | pages 1, 3, 4 | valeur + libellé + info-bulle ; prévoir la valeur « — » |
| **Badge de priorité** | tableaux, fiche | 5 états dont un **hors échelle** |
| **Badge de red flag** | tableau, fiche | 3 états : actif / inactif / **non évaluable** |
| **Indicateur de qualité** | tableaux, fiche | score /100 + niveau + alerte si donnée incohérente |
| **Indicateur de stabilité** | tableau, fiche | n/10, compact |
| **Ligne d'état de dimension** | fiche | icône + libellé + explication (4 états) |
| **Barre de contribution SHAP** | fiche | 3 barres horizontales, valeurs réelles |
| **Bloc comparaison aux pairs** | fiche | **doit avoir un état « indisponible »** |
| **Tableau de marchés** | pages 2, 3 | 8 colonnes, tri, sélection de ligne |
| **Bandeau d'avertissement** | pages 3, 4 | discret, permanent |
| **Bloc d'avis analyste** | fiche | 3 boutons + commentaire + confirmation |

---

## 11. Contraintes techniques — Streamlit

À connaître pour ne pas concevoir l'infaisable.

| Possible | Difficile ou impossible |
|---|---|
| Sidebar, onglets, colonnes | Modales (pas de vraie fenêtre superposée) |
| Cartes KPI (avec CSS) | Animations, transitions |
| Tableaux triables, sélection de ligne | Cellules HTML riches dans un tableau natif |
| Barres, donuts, lignes | Graphiques interactifs complexes sans bibliothèque tierce |
| Info-bulles simples | Info-bulles riches (HTML) |
| Badges colorés (via HTML/CSS limité) | Glisser-déposer, réorganisation de colonnes |
| Boutons, champs, curseurs | Mise à jour partielle : **toute interaction recharge la page** |

> **La plus grosse contrainte** : Streamlit réexécute le script à chaque
> interaction. Un design avec beaucoup d'états interactifs imbriqués sera lent
> et frustrant. **Privilégier peu d'interactions, mais claires.**

---

## 12. Ce qu'il ne faut PAS concevoir

| Élément | Raison |
|---|---|
| Page « Entreprises » ou score par entreprise | 93 % des entreprises n'ont qu'un marché ; ce score a été retiré car il mesurait un artefact |
| Graphe / réseau d'entreprises | degré maximum 2, **une seule arête** possible |
| Carte géographique | pas de localisation exploitable |
| Page « Benchmark » ou « Validation du modèle » | contenu de rapport technique, pas d'interface analyste |
| Page « Pipeline » / OCR / PostgreSQL | démontre l'architecture, pas l'analyse |
| Indicateur de performance du modèle | **aucune vérité terrain** — serait inventé |
| Tendance mensuelle | médiane de 4 marchés/mois — statistiquement vide |
| « Paramètres » / « Déconnexion » | aucune authentification n'existe |

---

## 13. Suggestions par ordre de valeur

**Forte valeur**

1. **Soigner l'état « données insuffisantes ».** 35 marchés, et c'est
   l'argument le plus distinctif du produit. Il doit être visible, neutre, et
   jamais confondu avec un risque faible.
2. **Rendre le plafond de confiance lisible.** Un marché au score élevé mais
   non classé prioritaire, avec l'explication, est la meilleure démonstration
   de la rigueur du système.
3. **Distinguer les trois états de red flag d'un seul coup d'œil.**
   Actif / inactif / non évaluable.
4. **Traiter l'objet long comme un problème de conception**, avec une décision
   explicite (troncature, info-bulle, deux lignes).

**Valeur moyenne**

5. Navigation précédent/suivant dans la fiche marché.
6. Indicateur de stabilité compact (10 points).
7. Lien direct de la vue générale vers les marchés prioritaires.
8. Compteur « X sur 454 » sous les filtres.

**Optionnel**

9. Export CSV de la sélection.
10. Mémoriser les filtres entre les pages.
11. Mode compact / confortable pour le tableau.

---

## 14. Les cinq phrases à retenir

1. **Deux tiers des montants sont absents.** L'interface doit rendre l'absence
   lisible, pas la masquer.
2. **« Données insuffisantes » n'est pas « risque faible ».** Deux états, deux
   traitements visuels.
3. **Le rouge est réservé aux signaux.** Jamais décoratif.
4. **Rien ne doit se lire comme une accusation.** Le système signale, il ne
   conclut pas.
5. **La page XAI est le cœur du produit.** Si une seule page doit être
   parfaite, c'est celle-là.

---

*Document préparé pour la conception de l'interface. Tous les chiffres
proviennent du corpus réel au 28/08/2026 et sont recalculés à chaque exécution
du pipeline — ils évolueront si le corpus change.*
