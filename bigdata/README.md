# bigdata/ — pipeline PySpark (Issue 9)

## Config locale requise (Windows), trouvée en testant réellement, pas supposée

1. **JDBC** : `spark.jars.packages` (résolution Maven/Ivy) a échoué dans
   l'environnement de développement, alors que `curl` atteignait la même
   URL Maven Central sans problème — un souci côté résolveur Ivy de la
   JVM, pas une vraie coupure réseau. Contournement : télécharger le jar
   une fois et pointer `POSTGRES_JDBC_JAR` dessus.

   ```bash
   curl -o postgresql.jar \
     https://repo1.maven.org/maven2/org/postgresql/postgresql/42.7.4/postgresql-42.7.4.jar
   export POSTGRES_JDBC_JAR=/chemin/vers/postgresql.jar   # ou set/$env: sous Windows
   ```

2. **`HADOOP_HOME` / `winutils.exe`** (Windows uniquement) : Spark en a
   besoin pour ses propres opérations de fichiers locales (distribuer le
   jar JDBC aux executors), **pas** pour parler à un vrai cluster Hadoop —
   sans ça, échec immédiat avec `HADOOP_HOME and hadoop.home.dir are
   unset`, avant même le démarrage du `SparkContext`. Binaires
   téléchargeables depuis <https://github.com/cdarlint/winutils> (choisir
   une version Hadoop proche de celle que `pyspark` embarque — vérifier
   avec `os.listdir(pyspark.__file__/../jars)`, cherché `hadoop-client-api`).

   ```
   HADOOP_HOME/
   └── bin/
       ├── winutils.exe
       └── hadoop.dll
   ```

   Ajouter `HADOOP_HOME` à `.env` et `%HADOOP_HOME%\bin` au `PATH`.

   Aucun des deux n'est nécessaire dans Docker (pas de service `spark`
   dans `docker-compose.yml`, `Dockerfile` sans JVM — le backlog dit
   explicitement "pipeline PySpark local", exécuté sur la machine de dev).

3. **Windows + Git Bash** : passer `HADOOP_HOME`/`POSTGRES_JDBC_JAR` via
   `export` dans Git Bash peut corrompre le chemin (MSYS convertit
   automatiquement les chemins de style Windows) — utiliser PowerShell
   (`$env:HADOOP_HOME = "..."`) pour définir ces variables avant de lancer
   un job Spark.

4. **Un seul appel UDF par SparkSession, sur cette machine** (trouvé en
   faisant tourner `build_statistics.py`, pas supposé) : le premier appel
   UDF d'une session réussit systématiquement, tout appel UDF distinct
   suivant échoue avec un `TimeoutError` de socket côté worker Python —
   reproduit de façon déterministe à travers plusieurs formes de code
   (fonction nommée vs lambda, `.cache()` ou non, `local[1]` vs `local[*]`,
   `spark.python.worker.reuse` à `true`/`false`, avec/sans appel de
   "chauffe"). Une regle simple qui a marche : **restreindre chaque
   SparkSession a au plus un appel UDF**, quitte a redemarrer une session
   entre deux phases qui en ont chacune besoin (voir
   `build_statistics.py::collect_implausible_company_ids()` — sa propre
   session courte, arretee avant que la session principale ne demarre et
   fasse son propre unique appel UDF pour `market_stats`). Une DataFrame
   dont la lignee remonte a un UDF doit aussi etre `.cache()`e des sa
   construction si plusieurs actions la lisent ensuite (validation puis
   ecriture Parquet, par exemple) — sans quoi chaque action re-declenche
   la lignee UDF, ce qui compte comme un nouvel appel.

   `spark.python.worker.reuse=false` reste actif dans `session.py` comme
   filet de securite supplementaire, meme si la cause reelle du
   `TimeoutError` n'a pas ete identifiee avec certitude (suspecte : un
   worker reutilise termine dans un etat casse apres sa premiere tache,
   ou une interference antivirus/pare-feu Windows sur les sockets
   localhost repetes JVM↔Python — non confirme, le contournement
   architectural a suffi). `spark.sql.shuffle.partitions` est aussi reduit
   a 8 (le defaut de 200 suppose un dataset a l'echelle d'un cluster ;
   combine a `worker.reuse=false`, 200 partitions signifiait 200 lancements
   de processus Python pour un corpus de quelques centaines de lignes —
   des minutes de pur overhead de demarrage).

## Lancer le job

```bash
python -m bigdata.spark.jobs.build_analytics_dataset
python -m bigdata.spark.jobs.build_analytics_dataset --database-url postgresql://...
```

Écrit `data/processed/analytics/fact_award_company/` (Parquet).

## Schéma de sortie

Grain : une ligne par paire `(Award, Company)`. `LEFT JOIN` partout — un
lot `INFRUCTUEUX`/`OFFRE_EXCESSIVE` sans entreprise liée garde sa ligne
(colonnes `company_*` à `NULL`), jamais supprimé silencieusement.

| Colonne | Origine | Note |
|---|---|---|
| `montant_ht`, `montant_ttc` | `Award` | jamais fusionnées, jamais l'une déduite de l'autre |
| `company_normalized_name` | `Company` | déjà normalisé en amont (Issue 8), jamais re-normalisé ici |
| `annee`, `annee_source` | `Procurement` | copiées telles quelles, jamais recalculées depuis une date d'Award |
| `acheteur_public`, `objet` | `Procurement` | `NULL` si la jointure `Award.procurement_id` a échoué (structurellement possible, 0/454 actuellement) |

**`fact_award_company` ne couvre que les documents liés à un PV (Passe A,
388 documents) — toute analyse nécessitant le contexte complet du marché
(dénominateurs par acheteur, volume total par catégorie/année incluant la
Passe B) doit lire `Procurement` directement, pas ce fact table.**
Conséquence directe : `annee_source` n'y prendra jamais la valeur
`"listing"`, puisque `Award` ne peut structurellement exister que pour un
document de la Passe A.

## Statistiques (Issue 10) — `data/processed/analytics/`

Périmètre : marchés **attribués** uniquement (`fact_award_company`, Passe
A). Pas de taux de participation/victoire — ça exigerait un dénominateur
de consultations totales que le corpus ne fournit pas (le PV n'existe que
pour les marchés déjà attribués).

- `company_stats_by_acheteur/` — par `(company_id, acheteur_public)` :
  `number_of_awards`, `total_amount_ht`/`_ttc`, `average_amount_ht`/`_ttc`
  (chacune calculée uniquement sur les lignes où cette base existe,
  `n_with_ht`/`n_with_ttc` donnent le dénominateur réel), `market_share_ht`/
  `_ttc` (part chez cet acheteur précis — signal Fazekas, `ideas.md` §2.6).
- `company_stats_global/` — même forme sans `acheteur_public`. **Pas un
  vrai chiffre de part de marché** : 388 documents PV sont un échantillon,
  pas le marché marocain réel. Utile seulement comme classement interne au
  corpus, jamais à présenter comme "X% du marché".

  **Un tri "top entreprise par montant" n'est pas protégé du bruit
  résiduel de `Company` par le seul filtre appliqué à l'insertion** —
  trouvé en vérifiant : la ligne n°1 par `total_amount_ttc` était
  `"ECONOMIQUEMENT LA PLUS AVANTAGEUSE"` (company_id 48, 96 128 952 DH),
  un fragment de la formule standard "l'offre économiquement la plus
  avantageuse" (source : doc 37526643f298..., `concurrent_retenu` brut
  `"economiquement la Plus avantageuse."`), pas une entreprise. Corrigé à
  deux niveaux, pas seulement documenté :
  1. `_looks_implausible()` (`database/crud/companies.py`) étendu avec
     `NOISE_WORDS_WHEN_NO_STRUCTURE` — "avantageuse"/"économiquement"
     rejetés n'importe où dans le nom (pas seulement en tête, la phrase se
     tronque à des endroits différents selon le document), mais seulement
     quand aucun token de structure n'est present — 2 entrées réelles
     mesurées dans le corpus contiennent "avantageuse" dans leur phrase
     environnante tout en portant un vrai nom SARL, et doivent rester
     récupérables.
  2. Défense en profondeur dans `build_statistics.py`
     (`_flag_implausible_companies`/`_drop_implausible_companies`) : reteste
     `_looks_implausible()` sur chaque `company_normalized_name` avant toute
     agrégation, pour que ce job reste correct même contre une base
     PostgreSQL pas encore rechargée depuis une amélioration du filtre —
     4 `Company` rejetées ainsi (`OFFRE LA PLUS AVANTAGEUSE`, `L OFFRE
     ECONOMIQUEMENT LA PLUS AVANTAGEUSE`, `OFFRE ECONOMIQUEMENT PLUS
     AVANTAGEUSE`, `ECONOMIQUEMENT LA PLUS AVANTAGEUSE`), touchant 5 Award
     (`company_id` 48 à elle seule en couvrait 2).

  Revérifié après coup, pas supposé corrigé : la ligne n°1 est maintenant
  `"(OH TTC) COSTACOM"` (41 189 000 DH) — confirmé réel en remontant au
  document source (`COSTACOM` apparaît a plusieurs reprises dans les
  listes de concurrents du PV, aux côtés d'autres entreprises clairement
  réelles ; `"(OH TTC)"` est du bruit OCR adjacent, pas le nom lui-même).
  222 → 218 `Company` après ce correctif.

  Ne jamais afficher un classement `company_stats_global`/
  `company_stats_by_acheteur` sans vérification visuelle des premières
  lignes — le filtre reste mesuré, pas exhaustif (voir le taux résiduel
  ~20% documenté plus haut ; ce correctif retire des cas précis mesurés,
  il ne garantit pas l'absence de tout bruit futur).
- `market_stats/` — par `award_id` : `number_of_bidders_raw` (compte brut
  de `liste_concurrents`) et `number_of_bidders_filtered` (même filtre de
  plausibilité que `Company`, + déduplication par `normalize_company_name`
  — mesuré : 93% des entrées passent, 7% rejetées, nettement plus propre
  que `concurrent_retenu` avant filtre car `_bulleted_names()` fait déjà
  son propre nettoyage de légende/néant en amont).

  **`number_of_bidders_filtered` fait foi pour le red flag "soumissionnaire
  unique" d'Issue 11, pas `_raw`.** Un signal de fraude doit minimiser les
  faux positifs venant du bruit d'extraction (accuser à tort un marché
  réellement concurrentiel) plutôt que d'accepter le bruit non caractérisé
  de `_raw` — `_filtered` est le signal conservateur, avec un taux d'erreur
  déjà mesuré (7%) plutôt qu'inconnu. `_raw` reste dans la sortie pour
  traçabilité/debug, jamais pour déclencher un signal.

- **Groupements** : crédit plein à chaque membre — un marché gagné par un
  groupement de 2 entreprises compte `+1 number_of_awards` et le montant
  **complet** pour CHACUNE des 2, pas une part divisée (aucune donnée sur
  la répartition interne du groupement n'existe dans le corpus, la deviner
  serait fabriquer une information). Mesure ceci comme "valeur des marchés
  auxquels cette entreprise a été partie prenante", pas "argent perçu par
  cette entreprise". `groupement_size` expose la taille du groupement par
  ligne (`1` pour une entreprise seule, `2`+ pour un groupement, `NULL`
  quand aucune entreprise n'est identifiée — jamais `0` fabriqué) pour
  qu'une analyse future puisse pondérer différemment si besoin. Impact
  mesuré minime dans le corpus actuel : 1 seul Award groupement sur 237
  Award ayant une entreprise liée.

## Validation (dernier run réel contre PostgreSQL)

```
Award (base)                    : 454
liens award_companies (base)    : 238
Award avec >=1 compagnie        : 237
Award sans compagnie            : 217
lignes attendues (LEFT JOIN)    : 455
lignes réelles en sortie        : 455   OK

Entreprises distinctes : 222 (~20% de bruit résiduel, voir database/README.md
— ne jamais présenter ce chiffre comme un compte exact d'entreprises réelles)
Lignes sans Procurement résolu (acheteur_public NULL) : 0 (nullable par
construction, Document.join_status — pas une erreur)
```

### Validation (dernier run réel `build_statistics.py`, après le correctif du bruit "avantageuse")

```
Repartition groupement_size : None 222 / 1 231 / 2 2   (222+231+2 = 455 OK)
Company rejetees (defense en profondeur) : 4, touchant 5 Award
Award avec compagnie avant filtre : 237 -> apres filtre : 232 (attendu 232) OK
Company distinctes (company_stats_global) : 218  (222 - 4 rejetees)
Lignes market_stats : 454 (attendu 454) OK
TECTRA : 1 award, 721224.86 TTC, M6/CRIRDOE — coherent avec la valeur
verifiee depuis Issue 7
```
