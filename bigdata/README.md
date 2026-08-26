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

4. **`postgres` (conteneur) vs `localhost` (hôte) — une seule règle, écrite
   ici, pas une substitution ad hoc par script.** `.env` contient
   `DATABASE_URL=postgresql://user:password@postgres:5432/procurement_db`
   — le hostname `postgres` n'est résolvable QUE depuis le réseau Docker
   interne (`api`/`dashboard` le reçoivent via `env_file: .env` dans
   `docker-compose.yml`, aucun `load_dotenv()` nécessaire côté conteneur).

   **Aucun script exécuté depuis l'hôte** — `scripts/load_database.py`,
   `bigdata/spark/jobs/*.py`, DBCode — **ne doit lire `.env` directement.**
   Ni `database/crud/session.py::get_engine()` ni
   `bigdata/spark/session.py::jdbc_url_and_properties()` n'appellent
   `load_dotenv()` : les deux font `os.getenv("DATABASE_URL", DEFAULT)`,
   et comme `DATABASE_URL` n'est jamais posé dans le shell hôte, ça retombe
   sur le fallback déjà codé en dur dans chaque fichier —
   `DEFAULT_DATABASE_URL = "postgresql://user:password@localhost:5432/procurement_db"`
   (`database/crud/session.py:11`, `bigdata/spark/session.py:37`). C'est
   ce fallback, pas `.env`, qui a fait fonctionner tous les chargements et
   jobs Spark de cette machine jusqu'ici — jamais documenté explicitement
   avant ce paragraphe, ce qui en faisait une coïncidence silencieuse
   plutôt qu'une décision.

   **Règle** : `.env` reste tel quel (`postgres`, usage Docker uniquement,
   ne pas le modifier pour "corriger" ce cas). Tout script/outil lancé
   depuis l'hôte contre le conteneur PostgreSQL persistant doit soit (a)
   ne rien passer et laisser `DEFAULT_DATABASE_URL` (`localhost`)
   s'appliquer — le cas par défaut, déjà correct — soit (b) passer
   explicitement `--database-url postgresql://user:password@localhost:5432/procurement_db`
   quand un remplacement est nécessaire (ex. pointer vers une base de test
   différente). Ne jamais faire `export $(cat .env)`/charger `.env` dans
   un shell hôte pour lancer un de ces scripts — ça écraserait le fallback
   `localhost` par le `postgres` du fichier et casserait la connexion.
   Pour DBCode (ou tout autre client SQL sur l'hôte) : configurer la
   connexion directement avec `localhost:5432` / `user` / `password` /
   `procurement_db` — ne jamais pointer un outil hôte vers `.env`.

5. **Un seul appel UDF par SparkSession, sur cette machine** (trouvé en
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

  **Correctif suivant, sur ce même "(OH TTC)"** : le préfixe parenthèse en
  tête n'était pas propre à COSTACOM — légende de tableau OCR ("Montants
  des actes d'engagement (OH TTC)", "en DH TTC" mal lu), collée à la
  valeur suivante faute d'avoir été reconnue par le filtre de légende
  d'`extraction/fields.py`. Ajout de `LEADING_PARENTHETICAL_RE` dans
  `normalize_company_name()` (root fix, `database/normalization.py`) +
  son miroir Spark natif `_clean_leading_parenthetical_col()` (regexp
  natif, pas de UDF) dans `build_statistics.py`, appliqué dans
  `_flag_implausible_companies` et `_drop_implausible_companies`.

  Ce correctif a exposé un second bug, auto-détecté en revérifiant plutôt
  qu'en supposant le fix propre : `"(PAR TIRAGE AU SORT)"` (company_id 53,
  une justification de choix entière, aucune entreprise) devient une
  chaîne vide une fois le préfixe parenthèse retiré — mais
  `_is_implausible_name()` testait `bool(name) and _looks_implausible(name)`,
  qui court-circuite sur `""` avant que `_looks_implausible("")` (qui
  retourne correctement `True`, liste de mots vide) ne soit jamais appelé.
  `company_id=53` survivait donc silencieusement au filtre malgré un nom
  nettoyé vide. Corrigé en `name is None or _looks_implausible(name)` —
  seul un nom réellement absent (`None`, cas déjà couvert par le filtre
  `company_id IS NOT NULL` en amont) échappe désormais au test, jamais une
  chaîne vide. 218 → 217 `Company` après ce second correctif (voir
  validation ci-dessous, `company_id=53` maintenant dans la liste des
  rejetées, plus de nom commençant par `(` dans `company_stats_global`).

  **Troisième vague de correctifs, sur les 217 restantes** : inspection
  manuelle complète (pas un échantillon) des 217 `company_normalized_name`,
  4 catégories de bruit non couvertes par les règles précédentes, ajoutées
  à `_looks_implausible()` (`database/crud/companies.py`) :
  1. `"NEANT"`/`"NÉANT"` ("- Néant", "du marché : Néant.") — mot de
     formulaire pour "champ vide", jamais en position de tête (contrairement
     à `NOISE_LEADING_WORDS`) donc vérifié n'importe où dans le nom.
  2. Un pattern de date lu comme `concurrent_retenu` ("31/12/2025",
     doc `1a2b0ab1...`) — jamais anticipé avant cette inspection. Réutilise
     le même regex que `ocr/matching.py::date_variants()` plutôt que d'en
     écrire un nouveau (`_looks_like_date()`).
  3. Aucune lettre du tout (`"-"`, `"01"`, `"1/2"`, `"\ 60"`) — un nom
     d'entreprise contient toujours au moins une lettre.
  4. Fragments à 1-2 lettres réelles sans marqueur de forme juridique dans
     le texte **brut** (`"AN"`, `"CT"`, `"TF"`, lettres isolées `"S"`/`"E"`/
     `"Y"`, et par extension `"^LZ"`/`"U 0 E"`/`"__ U"` une fois les
     caractères non-alphabétiques ignorés). Compte les lettres, pas la
     longueur totale de la chaîne — `"^LZ"` a 3 caractères mais seulement 2
     lettres réelles.

     **Vérifié contre le document source avant de trancher** — même
     méthode que pour `"(OH TTC) COSTACOM"` — pour les 3 cas ambigus
     (`AN`/`CT`/`TF`) : dans les 3, le texte extrait juste après
     "Concurrent/Soumissionnaire retenu :" est soit un fragment OCR
     illisible (watermark/tampon arabe garbled), soit une abréviation de
     colonne de tableau (`TF` = Tranche Ferme, `TC/AN` = Tranche
     Conditionnelle, confirmé par le doc `9ff585fd...` où `"TF: 736
     955.00 DH"` est une ligne de tableau à côté du vrai nom
     `"IMS TECHNOLOGY"`) — le vrai nom du vainqueur apparaît toujours
     plusieurs lignes plus bas, dans le tableau des montants par
     concurrent. Même défaut d'extraction que COSTACOM (le label
     "retenu :" est immédiatement suivi d'un fragment de mise en page, pas
     de la vraie valeur), pas trois incidents isolés — un candidat pour
     Issue 7 si le corpus s'élargit, hors scope de ce correctif Company.
     Cette même règle a détecté un 4ᵉ cas non identifié manuellement :
     `"R e |-00 #|"` (doc `53b0229e...`), le même défaut d'extraction
     confirmé par la même vérification.

     Point d'attention architectural : `normalize_company_name()` retire
     déjà un marqueur juridique simple en tête/fin AVANT que ce filtre ne
     s'exécute (`"STE SEN SARL"` → `"SEN"`) — chercher `SARL`/`STE` dans
     le nom déjà normalisé ne le trouve donc presque jamais pour ce cas.
     La règle 4 revérifie le texte **brut** (`raw_name` dans
     `get_or_create_company()`, `company_display_name` dans
     `build_statistics.py` — les deux threadés en paramètre optionnel
     `raw` de `_looks_implausible()`) : `"SEN"`/`"TCN"` (3 lettres) et
     `"BIGC"`/`"SEMH"` (4 lettres) restent acceptées car leur texte brut
     porte `STE`/`SOCIETE`/`SARL`, vérifiées explicitement, pas supposées
     à l'abri par coïncidence de longueur.

  Recompté après ce troisième correctif, pas supposé stable : **217 → 200
  `Company`** (22 rejetées au total par la défense en profondeur — les 5
  précédentes + 17 nouvelles — touchant 27 Award). Nouveau top-20 par
  `total_amount_ttc` revérifié visuellement : `^LZ` (ex-#2, 37 093 666,80
  DH) a disparu, remplacé par `EL6 INNOVATIVE BUILDING SOLUTIONS`
  (31 524 696,30 DH) ; aucun des 17 nouveaux cas n'apparaissait en position
  visible avant ce correctif (aucun n'était dans un top-20 précédent, sauf
  `^LZ`). **Résidu connu, non traité par ce correctif** : `company_id=173`
  ("POUR LE LOT N° 1 LA SOCIETE ZED S AVEC UN MONTANT...", 4 994 508 DH)
  reste dans le top-20 — `SOCIETE` y survit en milieu de chaîne (ni
  préfixe ni suffixe propre, donc jamais retiré par la normalisation),
  ce qui active `has_structure=True` et contourne toutes les règles
  conditionnées sur son absence (longueur, nombre de lettres). Même
  catégorie que le taux résiduel ~20% déjà documenté, pas un nouvel écart
  introduit ici.

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

### Validation (dernier run réel, après le correctif "(...)" + le bug empty-string)

```
Company rejetees par le filtre de plausibilite (defense en profondeur,
5, touchant 6 Award) :
  id=218 'OFFRE LA PLUS AVANTAGEUSE'
  id=5   'L OFFRE ECONOMIQUEMENT LA PLUS AVANTAGEUSE'
  id=206 'OFFRE ECONOMIQUEMENT PLUS AVANTAGEUSE'
  id=53  ''                              <- nouvellement capture
  id=48  'ECONOMIQUEMENT LA PLUS AVANTAGEUSE'

Award distincts dans fact                     : 454 (attendu 454)
Award distincts avec compagnie (avant filtre) : 237
Award distincts avec compagnie (apres filtre) : 231 (attendu 231)
Company distinctes (company_stats_global)     : 217  (218 - 1)
Company distinctes (by_acheteur, dedup)       : 217
Lignes market_stats                           : 454 (attendu 454)
OK : tous les recoupements confirmes.

company_id=53 present dans company_stats_global : False
Noms commencant par "(" dans company_stats_global : 0
Top 5 par total_amount_ttc :
  1. company_id=18  COSTACOM                                41 189 000.00
  2. company_id=45  ^LZ                                      37 093 666.80
  3. company_id=162 EL6 INNOVATIVE BUILDING SOLUTIONS         31 524 696.30
  4. company_id=77  OBSERVATIONS DU LOT N° 25-62 TAZART...    19 435 184.64
  5. company_id=78  AN                                        15 067 445.00

ALHAYAT/BIRG (collision "avantageuse" potentielle, verifiees conservees) :
  company_id=60 : DONT L OFFRE EST LA PLUS AVANTAGEUSE - SOCIETE ALHAYAT
                  TEC SARL POUR UN MONTANT
  company_id=72 : DONT L OFFRE EST LA PLUS AVANTAGEUSE - SOCIETE BIRG
                  SARL AU POUR UN MONTANT DE
37 tests passent (tests/ + Issue 8/9/10 confondus).
```

Note sur le rang #2-#5 : `^LZ`, `AN`, `"OBSERVATIONS DU LOT N° 25-62..."`
restent du bruit résiduel plausible-mais-pas-réel (aucun ne porte de
token de structure ni de longueur/mot suspect couvert par les règles
actuelles) — attendu à ce stade, documenté dans le taux résiduel ~20%
ci-dessus. `^LZ` et `AN` sont couverts par le correctif suivant (voir
juste ci-dessous) ; `"OBSERVATIONS DU LOT N° 25-62..."` reste résiduel.

### Validation (dernier run réel, après le correctif NEANT/date/sans-lettre/fragment-court)

```
Company rejetees par le filtre de plausibilite (defense en profondeur,
22, touchant 27 Award) — les 5 precedentes + 17 nouvelles :
  id=6   '- NEANT'
  id=218 'OFFRE LA PLUS AVANTAGEUSE'
  id=106 'S'
  id=80  '-'
  id=78  'AN'
  id=108 'U 0 E'
  id=22  '31/12/2025'
  id=90  'CT'
  id=149 'TF'
  id=152 '\ 60'
  id=185 '__ U'
  id=5   'L OFFRE ECONOMIQUEMENT LA PLUS AVANTAGEUSE'
  id=206 'OFFRE ECONOMIQUEMENT PLUS AVANTAGEUSE'
  id=217 'Y'
  id=139 'E'
  id=53  ''
  id=76  'R E -00 #'                        <- trouve par la regle, pas dans l'inspection manuelle initiale
  id=45  '^LZ'
  id=48  'ECONOMIQUEMENT LA PLUS AVANTAGEUSE'
  id=137 '1/2'
  id=111 '01'
  id=94  'DU MARCHE NEANT'

Award distincts dans fact                     : 454 (attendu 454)
Award distincts avec compagnie (avant filtre) : 237
Award distincts avec compagnie (apres filtre) : 210 (attendu 210)
Company distinctes (company_stats_global)     : 200  (217 - 17)
Company distinctes (by_acheteur, dedup)       : 200
Lignes market_stats                           : 454 (attendu 454)
OK : tous les recoupements confirmes.

Top 20 par total_amount_ttc (nouveau) :
  1. COSTACOM                                        41 189 000.00
  2. EL6 INNOVATIVE BUILDING SOLUTIONS                31 524 696.30
  3. OBSERVATIONS DU LOT N° 25-62 TAZART - ENNAKHIL   19 435 184.64
  4. VAROSSE                                          13 094 592.00
  5. HOLDING AL BARAKA                                11 168 983.62
  ...
  17. POUR LE LOT N° 1 LA SOCIETE ZED S AVEC UN
      MONTANT DE ... (              4 994 508.00   <- residu connu, voir note ci-dessus

SEN/TCN/BIGC/SEMH (marqueur juridique dans le texte brut, verifiees conservees) :
  id=11 STE SEN SARL -> SEN : garde
  id=30 BIGC SARL -> BIGC   : garde
  id=33 SOCIETE TCN -> TCN  : garde
  id=89 SEMH               : garde
43 tests passent (37 precedents + 6 nouveaux pour les 4 categories de
regles ci-dessus).
```
