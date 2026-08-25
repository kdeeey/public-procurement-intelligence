# database/ — modèles SQLAlchemy et insertion (Issue 8)

## Correction à propager : "38 documents multi-lots" → 31 / 37

Le plan Issue 7 (`extraction/lots.py`, non versionné dans ce dossier)
citait "38 documents réels contenant Lot n°X" comme échantillon de
vérification de la règle de segmentation. **Ce chiffre est périmé** — il
a été mesuré avant les correctifs finaux (garde-fou d'adresse,
reconstruction du lot attribué par complément) et n'a jamais été recalculé
depuis sur le pipeline final.

Recalcul sur le corpus extrait actuel (`data/processed/extracted/`,
388 documents), recoupé de deux façons indépendantes :

| | documents | Award |
|---|---:|---:|
| mono-lot (1 Award) | 357 | 357 |
| **multi-lot (>1 Award)** | **31** | 97 |
| total | 388 | **454** |

- Par `lot_detection` : `mono_sans_numero` 351 + `mono_numerote` 6 +
  `multi_implicite` 94 + `multi_declare` 2 + `multi_declare_complement` 1
  = 454.
- Par documents × Award : `{1: 357, 2: 19, 3: 5, 4: 1, 5: 3, 8: 2, 9: 1}`
  → 19+5+1+3+2+1 = **31** documents multi-lot, 357+97 = 454.

Les deux recoupements donnent 454 — cohérent.

**Documents avec au moins une mention de lot réelle (hors faux positifs
d'adresse) : 37**, pas 38 — 6 mono-lot-numérotés (ex. "Lot n°2 :
Conduite", un seul lot d'un marché plus large) + 31 réellement multi-lot.

**À utiliser dans tout rapport final ou présentation : 31 (documents
multi-lot) et 37 (documents avec mention de lot au total) — jamais le
"~38" de la phase de conception, qui ne correspond à aucun état mesuré
du pipeline fini.**

## Structure

```
database/
├── models/          Procurement, Award, Company, Document (SQLAlchemy 2.0)
├── normalization.py normalize_company_name(), split_groupement()
└── crud/            chargement depuis data/raw/, data/samples/, data/processed/
```

## Points de conception validés (Issue 8)

- `Procurement.awards` est **0-à-N**, pas 0-à-1 — jusqu'à 9 Award pour un
  même document (PV multi-lots).
- `montant_ht`/`montant_ttc` : colonnes indépendantes nullables, aucun
  défaut, aucune contrainte reliant les deux (data_dictionary.md §3.6).
- `Award.companies` est many-to-many (`award_companies`) : un groupement
  relie un seul Award à plusieurs `Company`, jamais scindé côté Award.
- `Document.join_status` distingue explicitement "jointure jamais tentée"
  (`NO_REF_CONSULTATION`) de "jointure tentée et échouée"
  (`REF_CONSULTATION_NOT_FOUND`) — un `procurement_id` NULL seul ne le
  permettrait pas.
- `Award.lot_detection` / `extraction_warnings` : traçabilité reprise
  telle quelle depuis `extraction/lots.py`, jamais recalculée ici.

## Chiffres de référence (dernier `scripts/load_database.py` exécuté)

```
Procurement : 1750 insérés, 0 sans refConsultation
Document    : 400 lignes manifeste -> 390 lignes Document (9 doc_id dupliqués
              dans le manifeste, upsert géré correctement) -> 390/390 RESOLVED
Award       : 454 insérés, 0 orphelins (no_matching_document), 238 liens Company
Company     : 222 entités distinctes
```

Vérifié une première fois contre PostgreSQL réel (`docker compose up -d
postgres`, pas seulement SQLite) — 3 écarts trouvés et corrigés, voir le
commit `fix(database): corrige 3 ecarts trouves en testant reellement
contre PostgreSQL` : driver `psycopg2-binary` jamais installé dans cet
environnement, deux colonnes `VARCHAR` trop étroites pour des valeurs
réelles (`lieu_execution` jusqu'à 925 caractères, `lieu_ouverture_plis`
jusqu'à 507 — SQLite n'applique aucune limite de longueur `VARCHAR`, ces
dépassements y étaient invisibles), et un premier filtre de plausibilité
sur `Company` (rejet des noms > 250 caractères).

## Filtre de plausibilité sur `Company` — mesuré, pas supposé fonctionner

Après le premier filtre (rejet des noms > 250 caractères), une mesure a
montré que le bruit d'extraction plus court passait toujours largement :
sur 292 `Company`, 28 % (83) étaient du bruit pur (aucun nom d'entreprise
présent — ex. `"L'offre économiquement la plus avantageuse."`) et 10 % (28)
un nom réel noyé dans du texte parasite (ex. `"Attributaire : * Société
ISOLAB SARL"`) — 38 % de la table affectée d'une façon ou d'une autre.

Deuxième filtre ajouté dans `get_or_create_company()`
(`database/crud/companies.py`), deux règles mesurées sur le corpus réel,
pas devinées :

1. Aucun token de forme juridique (`SARL`/`STE`/`SOCIETE`/`SA`/`SNC`/
   `GROUPEMENT`) **et** longueur ≥ 50 caractères. Seuil choisi par
   inspection : sur la tranche 50-90 caractères des noms sans forme
   juridique, 0 nom d'entreprise réel trouvé (30 valeurs inspectées,
   toutes du bruit) ; la tranche 30-50 est mélangée (de vrais noms comme
   `"CENTRALE MAROCAINE D'ASSURANCES"`, 31 caractères, y coexistent avec
   du bruit), donc non filtrée par ce critère.
2. Premier mot du nom normalisé ∈ {JUSTIFICATION, MONTANT, MONTANTS,
   ATTRIBUTAIRE, CONCURRENT, CONCURRENTS} — position significative : ces
   mots ailleurs dans la chaîne ne déclenchent rien.

**Résultat, mesuré à nouveau après coup (même méthode qu'avant le
filtre), pas supposé** :

| | avant (292 Company) | après (222 Company) |
|---|---:|---:|
| bruit pur | 28 % (83) | 14 % (32) |
| contaminé | 10 % (28) | 6 % (14) |
| propre | 62 % (181) | 79 % (176) |

Bruit combiné 38 % → 20 %, à peu près réduit de moitié. **Taux d'erreur
résiduel connu et non nul** : 32 valeurs de bruit pur et 14 contaminées
passent toujours (ex. `"GROUP SADE-CGTH / CTHM - Offre base"`, `"CLEAN
TECH - Offre de base"` — un token de structure absent mais sous le seuil
de 50 caractères). Le filtre n'a jamais visé l'exhaustivité — voir
`tests/test_normalization.py` pour les cas couverts explicitement.
