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
