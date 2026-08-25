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
Award       : 454 insérés, 0 orphelins (no_matching_document), 318 liens Company
```

Testé avec SQLite (Docker/Postgres indisponible dans l'environnement de
développement au moment de l'écriture) — le schéma cible reste PostgreSQL
(`ARRAY` réel, pas la variante JSON de secours).
