# bigdata/ — pipeline PySpark (Issue 9)

## Config locale requise (Windows), trouvée en testant réellement, pas supposée

> **⚠️ Périmé depuis le 27/08/2026.** Cette section décrit l'installation
> manuelle des prérequis Windows (`POSTGRES_JDBC_JAR`, `HADOOP_HOME` /
> `winutils.exe`). Ces deux binaires avaient disparu de la machine, rendant
> tout le pipeline injouable. Le chemin recommandé est désormais le
> conteneur `docker/spark.Dockerfile` — voir la section « Le pipeline
> PySpark tourne maintenant dans Docker » en fin de fichier. Le texte
> ci-dessous reste valable si tu veux exécuter en local, mais ce n'est plus
> ce qui a produit les artefacts en place.

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

## Feature engineering (Issue 11) — `bigdata/spark/jobs/build_features.py`

Lit `fact_award_company` + `market_stats` (Issue 9/10), reutilise le
pipeline de filtre de plausibilite et l'agregation de montants de
`build_statistics.py` plutot que de les reimplementer (meme contrainte a
deux sessions Spark, un seul appel UDF pour tout le module — voir
`collect_implausible_company_ids()`). Ecrit deux jeux de donnees :
`company_features.parquet` (une ligne par Company, 200 lignes) et
`company_yearly_trajectory.parquet` ({company_id, annee} → indicateurs).

**`amount_variation` (écart offre retenue vs autres offres / vs
estimation) n'est PAS une feature** — confirmé non calculable avant de
coder, pas juste non implémenté :
- `montant_par_concurrent`/`classement` (Award) : **0/454** peuplés,
  jamais extraits par Issue 7 (`database/crud/awards.py` le documente
  déjà : *"Issue 7's own report already lists these as not implemented /
  not validated"*).
- `estimation_dhs_ttc` pour les Procurement liés à un Award : **0/454** —
  confirme la décision déjà actée et mesurée dans `docs/ideas.md` §2.6
  (0/16 sur la Passe A) : l'estimation et le montant final ne coexistent
  jamais sur un même marché sur ce portail (la page de détail d'une
  consultation déjà attribuée n'affiche que le contexte "extrait de PV",
  jamais celui de l'annonce d'origine). Rattrapage possible seulement via
  une collecte au fil de l'eau, hors périmètre actuel (même doc).

**Trou d'extraction mesuré sur le montant du vainqueur** (trouvé en
vérifiant `amount_variation`, pas anticipé) : parmi les 211 liens (Award,
Company) où un vainqueur est identifié — tous `statut=ATTRIBUE`, donc un
montant *devrait* exister — **98/211 (46%) n'ont NI `montant_ht` NI
`montant_ttc`**. Pas le cas structurel attendu (`INFRUCTUEUX` sans
montant, déjà documenté) : un vrai trou d'extraction sur des marchés
attribués. Conséquence directe : **92/200 Company (46%) ont un montant
total à zéro sur les deux bases**. Traité par imputation médiane (jamais
0, qui ressemblerait à une valeur extrême) + un flag `has_ttc_data`/
`has_ht_data` explicite par Company, jamais silencieux — voir
`ai/train_isolation_forest.py`. TTC est la base retenue comme signal
principal pour le modèle (94/211 liens vs 19/211 pour HT) ; les colonnes
HT restent dans `company_features` pour traçabilité mais n'alimentent pas
le modèle.

**`concurrents_ecartes_rate`** — un 3ᵉ finding en construisant cette
feature : `concurrents_ecartes` (jamais validé contre une vérité terrain
non plus) porte le même bruit d'extraction que `concurrent_retenu` avant
Issue 8/10 (fragments de légende — *"techniques :"*, *"additifs :"*,
*"Concurrents éliminés Motifs des éliminations détaillées"* — plutôt que
de vrais noms). Réutilise `_looks_implausible()`/`normalize_company_name()`
(déjà construits et réglés pour exactement ce type de bruit, pas une
nouvelle règle) pour ne compter que les entrées plausibles : mesuré,
215/454 awards avec une entrée non vide brute, 178/454 avec au moins un
nom plausible.

**Trajectoire temporelle — la pente de régression (2023→2024→2025) n'est
calculable pour AUCUNE des 200 Company**, confirmé avec l'utilisateur
après mesure, pas supposé :

```
number_of_awards par entreprise : 189/200 ont exactement 1 award, 11/200 en ont 2
distinct annee par entreprise   : 200/200 ont TOUTE leur activite concentree sur UNE SEULE annee
has_trend_data (>=2 points 2023-2025) : 0/200
```

Pas un bug — une limite structurelle de l'échelle du corpus : 210 liens
(Award, Company) répartis sur ~200 entreprises distinctes (déjà
dédupliquées par `normalize_company_name`), sur 4 années. Il n'y a pas
assez d'historique répété par entreprise pour observer une trajectoire —
le scénario que Fazekas/`docs/ideas.md` §2.5 anticipe (une entreprise qui
gagne plusieurs marchés par an, sur plusieurs années) ne se présente pas
à cette échelle d'échantillon (388 documents PV). Les colonnes
`single_bidder_rate_trend_slope`/`number_of_awards_trend_slope` restent
dans `company_features` (valeur `None` pour les 200 Company aujourd'hui,
imputées à 0 + flag `has_trend_data` côté modèle) pour quand le corpus
grossira, mais le red flag "tendance croissante" a été retiré du score
composite (`ai/scoring.py`) — il ne s'activerait jamais, pour personne,
tel qu'implémenté aujourd'hui.

```
Company dans la matrice de features : 200 (attendu 200)
Award (avec compagnie) couverts      : 210 (attendu 210)
OK : recoupement confirme contre les totaux Issue 9/10.

Company avec au moins un montant TTC : 96/200
Company avec au moins un montant HT  : 24/200
Company SANS aucun montant (ni HT ni TTC) : 92/200
```

## Isolation Forest + score composite (Issue 11) — `ai/`

`ai/train_isolation_forest.py` — pandas/scikit-learn, pas PySpark (200
lignes, aucun besoin de parallélisation ; évite aussi entièrement le
problème d'instabilité UDF documenté plus haut). Colonnes d'entrée du
modèle (`ai/models/feature_columns.json`) : `number_of_awards`,
`single_bidder_rate`, `groupement_rate`, `concurrents_ecartes_rate`,
`total_amount_ttc`/`average_amount_ttc`/`market_share_global_ttc`
(imputés médiane + `has_ttc_data`), les deux pentes de tendance (imputées
à 0 + `has_trend_data` — toujours 0 aujourd'hui, voir ci-dessus). Jamais
HT et TTC comme entrées simultanées du modèle (HT trop clairsemé —
19/211 — pour être informatif une fois imputé).

`ai/scoring.py` — score composite 0-100, **poids égaux** (décision déjà
actée dans `docs/ideas.md`, corpus trop petit pour ré-estimer les poids
Fazekas — axe d'amélioration futur documenté, pas fait ici). 3 red flags
mesurés (pas 4 — le 4ᵉ, tendance, retiré ci-dessus) :

| Red flag | Seuil (mesuré sur les 200 Company) |
|---|---|
| `single_bidder_rate >= 0.5` | bimodal : 103 à 0.0, 91 à 1.0, 6 à 0.5 |
| `market_share_global_ttc >= 0.010952` | quartile supérieur mesuré parmi les 96/200 avec `has_ttc_data` |
| `concurrents_ecartes_rate >= 0.5` | bimodal : 105 à 0.0, 92 à 1.0, 3 à 0.5 |

Le red flag de concentration n'est évaluable que pour les 96/200 Company
avec `has_ttc_data`. **Décision confirmée avec l'utilisateur** : ne
jamais traiter "non évaluable" comme "non déclenché" (ça plafonnerait
mécaniquement le score des 104 Company sans donnée TTC — un biais, pas un
vrai signal de risque plus faible). Le score est plutôt **rescalé sur le
nombre de red flags réellement évaluables** pour cette entreprise (2 au
lieu de 3 quand `has_ttc_data` est faux), avec un flag explicite
`partially_evaluated` — même traitement que le montant manquant (flag
explicite, jamais une valeur silencieuse).

```
Company evaluees partiellement (2/3 red flags, pas de donnee TTC) : 104/200
Company evaluees completement (3/3 red flags)                    : 96/200
```

Comme pour tout classement `company_stats_*` : ~20% de bruit résiduel
dans `Company` peut apparaître en tête du score composite (un nom de
bruit avec `single_bidder_rate=1.0` et pas de montant ressemble à un
profil "à risque" alors que ce n'est pas une entreprise) — vérifier le
nom avant toute interprétation, jamais présenter un score élevé comme
une conclusion en soi.

## Score final explicable + référentiel fiscal synthétique (Issue 12)

**Articulation entre les deux scores existants, confirmée avec
l'utilisateur avant d'écrire `ai/risk_score.py`** — question posée
explicitement avant de coder, pas décidée seule : Isolation Forest est le
**signal principal**, le score composite (`ai/scoring.py`) devient la
**couche d'explication**, jamais fusionnés arithmétiquement en un seul
nombre pondéré. Raison : le score composite est borné par construction à
3 red flags nommés (5 valeurs possibles : 0/33.3/50/66.7/100) — il ne
peut structurellement jamais détecter une combinaison de features
inhabituelle qui ne correspond à aucun red flag nommé individuellement.
Isolation Forest capture ça nativement, un score combiné par pondération
aurait été plus opaque que chacun pris séparément — contraire à
l'objectif "score explicable" de cette Issue.

`ai/risk_score.py` : `anomaly_score` (Isolation Forest, plus bas = plus
anormal) rescalé **linéairement** en `final_score` 0-100 (jamais un
rang/percentile, qui aplatirait artificiellement la vraie forme mesurée
de la distribution — 165/200 très regroupées près du minimum, une queue
longue jusqu'au maximum). Seuils Faible/Modéré/Élevé/Critique **mesurés**,
pas 25/50/75 :

- **Faible** : `final_score` sous la frontière que le modèle a
  lui-même choisie (`is_anomaly == False`, 165/200) — mesuré, pas devine.
- Le reste (35/200, `is_anomaly == True`) coupé en 3 **terciles mesurés**
  de son propre `final_score` : Modéré / Élevé / Critique.

```
Seuils mesures :
  Faible   : final_score <= 26.4
  Modere   : 26.4 < final_score <= 38.8
  Eleve    : 38.8 < final_score <= 57.1
  Critique : final_score > 57.1

Distribution : Faible 165, Modere 12, Eleve 11, Critique 12
```

**Exemple concret, revérifié après coup — pas juste illustré** : COSTACOM
n'a que 1/3 red flags composite actifs (`concentration`, score composite
= 33.3) mais `final_score` = 100.0 (Critique, #1 anomalie Isolation
Forest). Vérifié par ablation (neutraliser un groupe de colonnes à leur
médiane et remesurer `decision_function` — approximatif, mais suffisant
pour trancher) **pourquoi**, plutôt que de deviner une explication
plausible :

```
                    sans cluster montant   sans features comportement
COSTACOM              +0.39 (quasi normal)   +0.0000 (AUCUN effet)
EL6 ...                +0.32 (quasi normal)   +0.018  (effet reel, modeste)
```

**COSTACOM est isolée à 100% par le montant (`total_amount_ttc`,
`average_amount_ttc`, `market_share_global_ttc`, `has_ttc_data` — un seul
groupe fortement corrélé, pas 4 signaux indépendants), 0% par le
comportement** : neutraliser `single_bidder_rate`/`groupement_rate`/
`concurrents_ecartes_rate` ensemble ne change RIEN à son score. **Ce
n'est donc pas un exemple de "combinaison non anticipée de comportements
suspects"** — c'est "un très gros contrat ressort comme statistiquement
rare", un signal bien plus simple qu'il n'y paraissait à la première
lecture (une version antérieure de cette section affirmait le contraire
sans l'avoir vérifié — corrigé ici). Un montant extrême reste un signal
légitime dans la littérature (concentration/taille de marché, Fazekas),
juste pas un exemple de sophistication du modèle.

EL6 INNOVATIVE BUILDING SOLUTIONS est le meilleur exemple de combinaison
réellement disponible dans ce corpus : ses 3 red flags composite sont
actifs ET `final_score` = 93.5, et l'ablation confirme un effet
comportemental réel (+0.018), pas nul comme COSTACOM — même si le
montant y reste dominant aussi. TECTRA : aucun flag actif, `final_score`
= 8.1 (Faible).

**Limite à documenter, pas à cacher** : 4 des 11 colonnes du modèle
(`total_amount_ttc`, `average_amount_ttc`, `market_share_global_ttc`,
`has_ttc_data`) sont fortement corrélées entre elles — pour une
entreprise à un seul award, `total_amount_ttc` et `average_amount_ttc`
sont littéralement identiques, et `market_share_global_ttc` en est un
transform monotone à ce stade du corpus. Isolation Forest, non supervisé,
ne corrige pas cette redondance — un montant extrême pèse donc
mécaniquement plus lourd que n'importe quel red flag comportemental pris
seul. Axe d'amélioration futur documenté, pas corrigé ici : réduire le
cluster montant à une seule colonne (ou le standardiser/rang-transformer
avant entraînement) pour rééquilibrer le poids effectif des features
comportementales.

**Portée mesurée, pas juste les 2 exemples ci-dessus** :
`ai/risk_score.py::_compute_dominant_driver()` applique cette même
ablation (neutraliser le cluster comportemental, remesurer) à toutes les
200 Company, pas seulement à COSTACOM/EL6 — **171/200 (86%) ont un signal
Isolation Forest dont l'isolement s'explique "surtout par le montant"**.
Ce n'est donc pas une bizarrerie isolée sur un seul exemple mal choisi :
c'est le comportement dominant du modèle tel qu'entraîné aujourd'hui.
Ce diagnostic tourne à chaque exécution (pas un one-off d'investigation)
et alimente directement `build_explanation()` : toute entreprise
Élevé/Critique dont le signal est "surtout montant" reçoit une nuance
explicite dans son texte d'explication (`dominant_driver` ==
`"surtout_montant"`), jamais présentée comme un exemple de comportement
combiné sans l'avoir vérifié.

#### Tentative de correctif — corrélation supprimée, dominance INCHANGÉE (mesuré, pas supposé)

**Diagnostic avant correctif** : corrélation mesurée entre les 4 colonnes
montant sur la matrice imputée — `total_amount_ttc` ↔
`market_share_global_ttc` : **r=1.000 exactement** (`market_share_global_ttc`
n'est rien d'autre que `total_amount_ttc` divisé par une constante, le
total du corpus — un rescale linéaire pur, zéro information additionnelle
pour un modèle à base d'arbres) ; `total_amount_ttc` ↔ `average_amount_ttc` :
**r=0.996** (91/96 Company avec `has_ttc_data` n'ont qu'1 seul award,
donc `total == average` exactement pour elles) ; `has_ttc_data` ↔ les
3 autres : seulement **r≈0.26** — pas le moteur de la redondance,
contrairement à ce que suggérait une ablation à une seule feature testée
plus tôt (artefact hors-distribution : `has_ttc_data=0` ne coexiste
jamais avec un montant extrême dans les vraies données, seulement avec
la médiane imputée — l'ablater seul crée une combinaison jamais vue à
l'entraînement).

**Correctif appliqué** : `MODEL_FEATURE_COLUMNS` réduit de 11 à 9
colonnes — `average_amount_ttc` et `market_share_global_ttc` retirées
(gardées dans `company_features.parquet` pour le **reporting**
uniquement : le red flag `concentration` du score composite continue de
lire `market_share_global_ttc`, ce fichier `train_isolation_forest.py`
continue de l'afficher pour contexte — **deux usages distincts, ne pas
les confondre** : colonne de reporting ≠ colonne d'entrée du modèle).

**Résultat mesuré après réentraînement — honnête, pas arrondi à la
hausse** : **170/200 (85%)**, quasiment inchangé par rapport aux
**171/200 (86%)** d'avant le correctif. Aucune amélioration mesurable,
malgré un diagnostic de corrélation correct et un correctif appliqué
comme prévu. Hypothèse de rechange testée avant de conclure — la
dominance venait peut-être de l'ÉCHELLE (`total_amount_ttc` a un
écart-type ≈ 4,26 millions contre < 1 pour toutes les autres colonnes) :
standardisation (`sklearn.StandardScaler`) appliquée avant
réentraînement → **176/200 (88%)**, légèrement PIRE, pas mieux.

**Cause racine réelle, confirmée par élimination** : ni la redondance ni
l'échelle. C'est la **cardinalité**. `total_amount_ttc` prend ~96 valeurs
continues distinctes ; les features comportementales
(`single_bidder_rate`, `groupement_rate`, `concurrents_ecartes_rate`) ne
prennent que **3 valeurs possibles** (0, 0.5, 1 — la quasi-totalité des
Company n'ayant qu'1 seul award). Isolation Forest isole un point via des
coupures aléatoires sur des features aléatoires : une feature continue à
haute cardinalité isole n'importe quel point bien plus efficacement
qu'une feature à 3 valeurs, **indépendamment de son échelle** — ce que la
standardisation ne peut pas corriger, puisqu'elle ne change pas le nombre
de valeurs distinctes.

**Décision, confirmée avec l'utilisateur après ces deux tentatives
mesurées** : garder le correctif de redondance (bonne pratique en soi,
r=1.000/r=0.996 sont de vrais doublons, indépendamment de l'effet sur la
dominance), documenter cette limite plus profonde comme non résolue dans
ce sprint plutôt que de multiplier les tentatives sans garantie de
résultat. Ceci **renforce** le choix d'architecture initial d'Issue 12
(Isolation Forest = signal principal, score composite = couche
d'explication) plutôt que de le remettre en cause : Isolation Forest est
structurellement plus efficace pour détecter les valeurs aberrantes sur
une variable continue (le montant), le score composite à red flags
nommés est structurellement plus efficace pour détecter un comportement
borné/quasi-binaire (soumissionnaire unique, exclusion) — combiner les
deux capture ce qu'aucun des deux ne capture seul, ce n'est pas un
correctif à faire converger vers un seul modèle équilibré.

**Seuils recalculés sur la nouvelle distribution** (9 colonnes) :

```
Faible   : final_score <= 24.9
Modere   : 24.9 < final_score <= 32.9
Eleve    : 32.9 < final_score <= 63.3
Critique : final_score > 63.3

Distribution : Faible 151, Modere 16, Eleve 17, Critique 16
(avant, 11 colonnes : Faible 165, Modere 12, Eleve 11, Critique 12)
```

Exemples revérifiés avec le nouveau modèle :

```
COSTACOM : final_score 100.0 -> 100.0 (inchange, #1 anomalie, toujours "surtout_montant")
EL6      : final_score 93.5  -> 98.9  (toujours 3/3 flags actifs, toujours pas "surtout_montant")
TECTRA   : final_score 8.1   -> 16.3  (toujours Faible, aucun flag actif)
```

Les rangs relatifs et les conclusions qualitatives (COSTACOM = montant
seul, EL6 = vraie combinaison, TECTRA = normal) sont stables d'un modèle
à l'autre malgré le changement de colonnes — cohérent avec le fait que le
correctif n'a pas changé la dynamique dominante, seulement retiré des
doublons inertes.

L'explication textuelle (`build_explanation()`) réutilise `active_flags`
du score composite tel quel, jamais une formulation d'accusation — chaque
texte se termine par *"Ceci est un signal statistique, PAS une preuve de
fraude"* (principe directeur du projet, `docs/ideas.md` Sec 2.6). Les
104/200 Company évaluées partiellement (pas de `has_ttc_data`) portent
cette limite explicitement dans leur texte d'explication — le
`final_score` lui-même reste toujours pleinement défini (Isolation Forest
a été entraîné avec `has_ttc_data` comme feature, contrairement au score
composite qui doit rescaler faute de donnée).

### Référentiel fiscal synthétique — `data/synthetic/fiscal_reference.csv`

**Synthétique par construction, pas par choix** : l'ICE et le RC des
entreprises gagnantes ne sont jamais publiés sur le portail PMMP (vérifié
sur tout l'échantillon — limitation déjà actée). Sans identifiant fiscal
fiable, le seul rapprochement possible est le nom normalisé de
l'entreprise — déjà la clé utilisée partout ailleurs dans ce pipeline.
Décision déjà actée avec l'encadrante : *"le mécanisme de croisement sera
démontré, pas validé sur des données réelles"* —
`scripts/generate_fiscal_reference.py` démontre ce mécanisme, il ne le
valide pas.

**Précaution explicite, appliquée dans le générateur** : les valeurs
fiscales sont générées **aléatoirement** (`np.random.default_rng(42)`),
**indépendamment** de tout score de risque déjà calculé par ce projet.
Coupler un chiffre "fiscal" fabriqué au score de risque d'une entreprise
réellement nommée produirait quelque chose qui ressemble à une
accusation, alors que ce fichier ne prouve rien sur la situation fiscale
réelle de qui que ce soit. Chaque ligne porte une colonne `source =
"SYNTHETIQUE_DEMO_PAS_DGI"`, et le CSV lui-même commence par un
en-tête de commentaires (`#...`) rappelant la même chose avant même la
première ligne de données — lisible même par un outil qui ouvrirait le
fichier sans passer par le script (`pandas.read_csv(..., comment="#")`
pour le reparser proprement).

Le mécanisme de croisement (`_demo_crosscheck_mechanism()`) — ratio
montant de marché réel / chiffre d'affaires déclaré synthétique, un red
flag classique de la littérature (un montant remporté proche ou
supérieur au CA déclaré signale une sous-déclaration potentielle) —
**n'écrit rien sur disque**, imprime seulement à titre d'exemple
technique. Les ratios obtenus (ex. 156x pour COSTACOM) sont mécaniquement
extrêmes parce que le CA synthétique est généré indépendamment du vrai
montant — attendu, ne signifie rien sur une vraie entreprise, jamais à
interpréter ni à persister comme un résultat.

## ⚠️ Correction du 27/08/2026 — le taux de bruit `Company` rapporté était faux

> **Ce qui était écrit plus haut, et qui est faux :**
> ~~« ~20 % de bruit résiduel » / « 217 → 200 Company, bruit ramené à ~15 % »~~
>
> **Le vrai chiffre, recompté exhaustivement le 27/08/2026 : 53,5 %
> (107/200) — 34 bruit pur + 73 noms réels noyés dans du texte parasite.**

L'ancienne affirmation n'est pas barrée pour la forme : elle a servi de base
à trois sections de ce document et à `database/README.md`. La trace de
l'erreur reste visible volontairement, comme pour la correction « 38 → 31/37
documents multi-lots ».

### Pourquoi le chiffre était faux — cause vérifiée, pas supposée

Ni la base ni le code n'étaient périmés. Vérifié par **rejeu du filtre**
alors en place sur `data/processed/extracted/` et comparaison ensembliste
avec l'export réel de la table : 200 produits / 200 en base / 200 identiques,
**0 écart dans les deux sens**. La table était exactement ce que le code
produisait.

Le ~15 % venait d'une **inspection manuelle partielle** après le commit
`fd0aa49`, jamais d'un recomptage des 200 lignes. Trois défauts structurels
du filtre expliquent ce qui passait :

1. **La règle de date était inopérante sur une date incluse.**
   `_looks_implausible()` déléguait à `ocr/matching.py::date_variants()`,
   dont le regex est ancré (`\s*$`) : il ne matche que si la valeur **est**
   une date, jamais si elle en **contient** une.
   `"TANSIFT CONTRACTOR DIRECT 09/12/2025 30/12/2025"` → non détecté.

2. **La règle de longueur était désactivée par la forme juridique.**
   Le garde `if not has_structure:` protégeait à la fois le seuil de 50
   caractères et le vocabulaire de justification. Une phrase administrative
   de 79 caractères contenant `SOCIETE` ou `STE` traversait donc le filtre
   entier — et c'était **délibéré** : le commentaire du code citait
   `"...SOCIETE ALHAYAT TEC SARL..."` comme un cas « à garder récupérable ».
   Le garde-fou avait été calibré sur les cas qu'il laissait passer.

3. **Il n'y a jamais eu de règle « tirage au sort ».** La forme
   `"(PAR TIRAGE AU SORT)"` était traitée par `normalize_company_name()`,
   qui retire un groupe parenthésé **de tête**. Sans parenthèses,
   `"APRES TIRAGE AU SORT"` n'était couvert par rien.
   `NOISE_LEADING_WORDS` ne testait par ailleurs que `words[0]`, et
   l'OCR abîme précisément le premier mot (`CONCARRENT`, `CONEURRENT`,
   `ONCURRENT`, `CENCURRENTS`).

### La leçon de fond : un filtre de rejet ne pouvait pas y arriver

Deux mesures ont commandé la réécriture, pas une préférence de style :

- **73 des 107 cas contiennent un vrai nom.** Les rejeter détruit 73
  entreprises réelles ; les garder casse la déduplication
  (`"TANSIFT CONTRACTOR DIRECT 09/12/2025 30/12/2025"` et
  `"TANSIFT CONTRACTOR DIRECTR•CE"` sont **la même entreprise en deux
  lignes**, dont aucune ne se joint à l'autre). Un filtre qui ne sait que
  rejeter n'a aucune issue sur cette moitié du problème.
- **La longueur ne discrimine rien.** Sur les 11 faux positifs du critère
  « aucune forme juridique ET ≥ 30 caractères », **11/11 sont de vrais
  noms** : `LABORATOIRE GEOTECHNIQUE ET TRAVAUX PUBLICS`, `CENTRALE
  MAROCAINE D ASSURANCES`, `BUREAU MAROCAIN DES ETUDES ET EXPERTISES BMEE`.
  La raison sociale marocaine est fréquemment une longue phrase descriptive
  sans SARL. Ajouter une 5ᵉ règle de mot-clé n'aurait pas touché ce fond.

### Le correctif : en amont, et par span de nom

Le défaut naît dans `extraction/fields.py::_collect_value_block()`, qui
ramasse jusqu'à 6 lignes / 400 caractères après le label et n'y coupe qu'à
un montant plausible — il avale l'en-tête de colonne, la phrase de
justification et l'adresse. La correction est donc appliquée **dans
l'extraction**, pas seulement au chargement :

- `extraction/company_name.py` — nouveau module. Classe chaque token en
  **BREAKER** (libellé de champ, verbe conjugué, préposition de phrase,
  nombre écrit en toutes lettres), **NEUTRE** (articles, conjonctions,
  chiffres isolés) ou **CORE**, puis retient le plus long span contigu sans
  breaker (à égalité : celui qui porte une forme juridique). Aucun span
  avec un token CORE → aucun nom dans la valeur → rejet. **Une règle
  générale remplace les quatre listes de rejet précédentes**, et sait
  *rogner* au lieu de seulement rejeter.
- `extraction/corpus_common_words.json` +
  `scripts/generate_common_words.py` — garde-fou mesuré pour le cas d'un
  nom réduit à un seul mot générique. Séparation nette et **mesurée** :
  les 48 vrais noms d'un seul mot du corpus plafonnent à **1,03 %** de
  fréquence documentaire (NOVEC, SGIAT, SEN), les résidus à rejeter
  démarrent à **3,35 %** (MAROCAINE 3,35 %, GLOBAL 4,38 %, RAPPORT 5,93 %,
  PUBLIC 10,82 %, TECHNIQUE 21,65 %). Seuil à 2 %, entre les deux, avec un
  facteur ~2 de marge de chaque côté.
- `Award.concurrent_retenu_brut` — **nouvelle colonne** : le bloc brut
  d'origine est conservé, le nettoyage amont ne fait perdre aucune
  traçabilité. `extract_statut()` continue de lire le brut, jamais la
  valeur nettoyée (sinon des `ATTRIBUE` basculeraient à tort en
  `INFRUCTUEUX` — vérifié : statut inchangé à 94 %).
- `_looks_implausible()` et ses 4 listes ont été **supprimés**, ainsi que
  leurs 13 tests, réécrits cas pour cas dans
  `tests/test_company_name.py` (18 tests) contre la nouvelle fonction.

### Un bug trouvé en vérifiant les cas de référence, pas en relisant le code

La consigne « revérifier TECTRA, COSTACOM, EL6 après rechargement complet »
a payé : après le premier rechargement, **COSTACOM avait disparu de la
table** — l'entreprise classée n°1 anomalie du corpus.

Cause : sa valeur brute est `"(OH TTC) COSTACOM"`. `TTC` est un breaker, il
coupe la chaîne en deux spans d'un token CORE chacun — `["OH"]` et
`["COSTACOM"]` — aucun ne portant de forme juridique, donc **strictement le
même score**. `max()` conserve le premier élément à égalité : `"OH"`
l'emportait par sa seule position, puis tombait sous
`MIN_REAL_LETTERS_WITHOUT_LEGAL`, et toute l'entreprise était rejetée.

Corrigé en ajoutant le **nombre de lettres** comme troisième critère de
départage (`score()` renvoie `(forme_juridique, nb_tokens, nb_lettres)`).
Effet mesuré au-delà de COSTACOM : le rejet du bruit pur passe de 30/34 à
**32/34** sur le corpus de référence, aucune entreprise réelle perdue.
Non-régression verrouillée par
`tests/test_company_name.py::test_clean_prefers_the_longer_span_when_scores_tie`.

### Résultats mesurés — même méthode de comptage avant et après

Classification manuelle ligne à ligne des 200 puis des 213 noms, pas une
estimation, pas un échantillon.

| | avant (200 Company) | après (215 Company) |
|---|---:|---:|
| propre | 93 (46,5 %) | **180 (83,7 %)** |
| contaminé | 73 (36,5 %) | **16 (7,4 %)** |
| bruit pur | 34 (17,0 %) | **19 (8,8 %)** |
| **total affecté** | **107 (53,5 %)** | **35 (16,3 %)** |

Sur les 454 Award : **255 valeurs `concurrent_retenu` corrigées** (68
devenues NULL = bruit pur éliminé, 187 rognées vers le nom réel), et
**0 statut, 0 montant modifié** — le rayon d'action est resté celui qui
était visé.

Qualité d'extraction contre `ground_truth.json`
(`scripts/validate_extraction.py`), aucune régression :

| champ | avant | après |
|---|---:|---:|
| `concurrent_retenu` | 81 % | **88 %** |
| `reference_pv` | 94 % | 94 % |
| `date_ouverture_plis` | 100 % | 100 % |
| `date_achevement_commission` | 81 % | 81 % |
| `montant_offre_retenue` | 62 % | 62 % |
| `statut` | 94 % | 94 % |
| **TOTAL** | **86 %** | **87 %** |

### Un identifiant de tableau collé au nom — le cas EL6

Signalé après le rechargement : *« EL6 INNOVATIVE BUILDING SOLUTIONS est une
entreprise correcte mais sans EL6 »*. Vérifié dans le document source
(`b0433c6d2fee`) plutôt que supposé — le PV **numérote ses soumissionnaires** :

```
EL 4 : DEVELOPPEMENT INGENIERIE ORGAN
EL5 : SOCIETE IMILCHIL
EL 6 : INNOVATIVE BUILDING SOLUTIONS
EL7 : MESKI DE TRAVAUX DIVERS
```

`EL 6` est un identifiant de ligne de tableau, pas un morceau de raison
sociale. C'est le format `Libellé : valeur` du PV, déjà connu ailleurs dans
le projet. Le **deux-points est donc traité comme un séparateur de span**,
au même titre qu'une date.

Pourquoi un séparateur, et pas « garder ce qui suit le dernier `:` » : sur
les **44 valeurs brutes du corpus** qui contiennent un `:`, le nom est
tantôt **à droite** (`Attributaire : Sté APERAL`, `sans réserve : LABOTEST
et LPEE`), tantôt **à gauche** quand le deux-points termine la ligne
(`IMS TECHNOLOGY TF :`, `ALL MTGI Offre :`). Une règle de position casserait
la moitié des cas ; la sélection du meilleur span tranche dans les deux
sens. Effet mesuré sur la table : `EL6 INNOVATIVE BUILDING SOLUTIONS` →
`INNOVATIVE BUILDING SOLUTIONS`, plus deux fragments de bruit raccourcis.

**La généralisation a été écrite, mesurée, puis REJETÉE.** Une règle
« retirer un sigle de 1-3 lettres en tête quand au moins deux mots
distinctifs suivent » a été appliquée aux 215 noms réels : **3 corrections
pour 9 destructions** —

| nom réel | ce que la règle en aurait fait |
|---|---|
| `ALI OUBANE TRAVAUX` | `OUBANE TRAVAUX` |
| `BCT QUALICONSULT CONSTRUCTION MAROC` | `QUALICONSULT CONSTRUCTION MAROC` |
| `MY GREEN NEGOCE` | `GREEN NEGOCE` |
| `FIX IT SOLUTION` | `IT SOLUTION` |
| `KIT MED SLAOUI ET CIE` | `MED SLAOUI ET CIE` |
| `NET SERVICES INFORMATIQUE & BUREAUTIQUE` | `SERVICES INFORMATIQUE & BUREAUTIQUE` |

Un sigle court en tête est parfaitement ordinaire dans une raison sociale
marocaine ; **rien ne le distingue d'un identifiant de tableau sans le
deux-points qui le suit**. Non-régression verrouillée par
`test_clean_does_not_strip_a_short_leading_token_of_a_real_name`
(`tests/test_company_name.py`).

**Note de lecture** : les sections historiques plus haut dans ce fichier
citent encore `EL6 INNOVATIVE BUILDING SOLUTIONS` — elles décrivent des
exécutions antérieures et sont conservées telles quelles, comme le reste
des traces de ce document. L'entité s'appelle désormais
`INNOVATIVE BUILDING SOLUTIONS`.

### Les seuils recalculés, jamais réutilisés

Le passage de 200 à 215 `Company` change la population sur laquelle les
seuils avaient été mesurés — les réutiliser tels quels aurait fait passer
une valeur périmée pour une valeur mesurée :

| Seuil | avant | après | source |
|---|---:|---:|---|
| `CONCENTRATION_THRESHOLD` (`ai/scoring.py`) | 0,010952 | **0,011191** | Q3 de `market_share_global_ttc` sur les 98/215 Company avec donnée TTC (96/200 avant) |
| Frontière Faible (`ai/risk_score.py`) | — | recalculée | frontière que le modèle choisit lui-même (`is_anomaly`) |
| Modéré / Élevé / Critique | — | recalculés | terciles mesurés du sous-groupe anormal |

Isolation Forest a été **réentraîné** sur les 215 lignes (45 anomalies
signalées). Distribution obtenue : 173 Faible / 14 Modéré / 14 Élevé /
14 Critique.

Les contrôles de volumétrie codés en dur (`if n_companies != 200: raise`,
présents dans `build_features.py` et les trois scripts `ai/`) auraient fait
échouer les cinq étages de la chaîne. Ils lisent désormais la référence
depuis la base — voir `database/crud/counts.py`.

### Vérification des trois cas de référence, après chaîne complète

```
EL6 INNOVATIVE BUILDING SOLUTIONS  94,4  Critique  comportement_et_montant  3 flags
COSTACOM                           94,2  Critique  comportement_et_montant  1 flag
TECTRA                             14,2  Faible    surtout_montant          0 flag
```

Confirmés identiques dans PostgreSQL et via l'API (`GET /stats/summary`,
`GET /companies/ranking`) : 1750 procurements / 390 documents / 454 awards /
215 companies.

### Le bruit qui reste — nommé, pas caché

**19 bruits purs (8,8 %)**, dont aucun n'est rattrapable par une règle
générale : ce sont des fragments OCR indiscernables d'un nom rare par la
fréquence (`TFC` 0,26 %, `DIRNAMS` 0,77 %, `MONFANT` 0,26 %, `TIC` 1,55 %),
des toponymes (`TAZART ENNAKHIL`, `HASSAN II AZILAL`) et des morceaux de
descriptif de lot :

```
2-ZZ-431 DU 0G 0L1IOZS           DUREE MAX            NENAT L IQ
AO00 INTERNATIONAL N 19 2025 KH  ELECI RONIQUE NZE    OONFORMEMEM
AOO N 38-2025 INFRICTUEUX        HASSAN II AZILAL     TAZART ENNAKHIL
CONVENTION                       MARCH E CU LIG       TFC
DIRNAMS                          MAROCAINE            TIC
DUR6E MAX DE 3 NN6E S RESP...    MONFANT              USTIFICATION
NO1 TRAVAUX D AMENAGEMENT DES VOIES ET RUES DE IA VILLE DE MARRAKECH
```

**16 contaminations (7,4 %)** — un vrai nom accompagné d'une adresse, d'une
ville ou d'une liste non scindée :

```
AF TECHNOLOGY 3N SYSTEMS TMAY INFO CT CHRONO TECH   ES STE EL HOURIA HOLDING
ALL MTGI                                            GR- STE GUW ET SASD
ATLAS HANDASSA SARL STE AMICALE DES TRAVAUX...      OCIETE SJ2T
BOURAF TRAVAUX SARL DR IKISS IKNIOUNE TINGHIR       TANSIFT CONTRACTOR DIRECTR
EI GAGEMENT PREMIUM TELECOM CUSTOMER SERVICES       TECHNIQUES X OFFTCE SYSREMS
ELEXPERT SARL DE CASABLANCA                         GRP SEAT E A TRAVAUX MEKNES
ENGAFEMENT SOCIETE O2E ENERGIE TO                   TRAFFITEC- RIFL BIOMETRICS-...
LMS ORGANISATION REMUNERATION DU FONDS HASSAN
LOACFE DTENETEEMENT LA SOCIETE ECLANOUR SARL JUSTIFICATIONDUCHOIXDEL
```

**La règle de lecture ne change pas** : ne jamais afficher un classement
`company_stats_*` sans vérification visuelle des premières lignes. Le
nettoyage est mesuré, il n'est pas exhaustif.

### État de la propagation aval — chaîne complète rejouée

| Étape | État |
|---|---|
| `data/processed/extracted/` (388 JSON, 454 Award) | ✅ régénéré |
| PostgreSQL — `procurements`/`documents`/`awards`/`companies` | ✅ rechargé (TRUNCATE + reload complet, 215 Company) |
| Parquet `fact_award_company`, `company_stats_*`, `market_stats` | ✅ régénérés |
| `company_features`, `company_yearly_trajectory` | ✅ régénérés |
| Isolation Forest (`ai/models/`), seuils, `company_final_risk` | ✅ réentraîné et recalculé |
| Table `risk_scores` | ✅ rechargée (215 lignes, 0 `skipped_no_company`) |
| API (`/stats/summary`, `/companies/ranking`) | ✅ vérifiée contre la base réelle |

## Le pipeline PySpark tourne maintenant dans Docker — `docker/spark.Dockerfile`

> **Ce qui était écrit en tête de ce fichier, et qui n'est plus la
> procédure recommandée :**
> ~~« Config locale requise (Windows) : télécharger `POSTGRES_JDBC_JAR` à la
> main, installer `HADOOP_HOME`/`winutils.exe` depuis un dépôt tiers. »~~

Ces deux prérequis avaient disparu de la machine de développement, rendant
**tout le pipeline injouable** — et c'est structurel, pas accidentel : une
étape qui dépend de binaires installés à la main hors du dépôt n'est pas
reproductible. `build_analytics_dataset` échouait sur `HADOOP_HOME and
hadoop.home.dir are unset`, levé dans l'initialiseur statique de
`org.apache.hadoop.util.Shell`, **avant même le démarrage du
`SparkContext`** — vérifié : même une `SparkSession` nue, sans aucun jar,
échoue de la même façon sous Windows.

Sous Linux, `winutils.exe` n'existe simplement pas. Le conteneur supprime
donc les deux prérequis d'un coup : le JDK vient de la distribution, le jar
JDBC est téléchargé à la construction de l'image.

```bash
docker build -f docker/spark.Dockerfile -t ppi-spark .

docker run --rm --network public-procurement-intelligence_default \
    -v "D:/public-procurement-intelligence:/app" -w /app ppi-spark \
    python -m bigdata.spark.jobs.build_analytics_dataset
```

Points à connaître :

- **Le réseau.** `--network public-procurement-intelligence_default` place
  le conteneur sur le réseau compose, où le service `postgres` répond à son
  nom d'hôte — c'est déjà la valeur de `DATABASE_URL` dans `.env`,
  contrairement aux scripts lancés depuis l'hôte qui doivent passer par
  `localhost` (voir la section « postgres vs localhost » plus haut).
- **Java 21, pas 17.** `python:3.11-slim` est passé à Debian trixie, dont
  les dépôts ne proposent plus `openjdk-17-jre-headless` (`has no
  installation candidate`, rencontré à la construction).
- **Git Bash.** Préfixer la commande de `MSYS_NO_PATHCONV=1`, sinon MSYS
  convertit `/app` en `C:/Program Files/Git/app` et Docker refuse le
  répertoire de travail.
- **Le code est monté, jamais copié** (`-v`) : l'image reste valable
  pendant qu'on itère sur les jobs.
- L'image porte **aussi** scikit-learn et joblib : la chaîne complète
  Spark → Isolation Forest → `risk_score` tourne dans le même
  environnement, sans repasser par l'hôte entre deux étapes.

Le `.venv` du dépôt et l'installation locale de PySpark restent utilisables
si les deux prérequis Windows sont présents — mais ce n'est plus le chemin
documenté, et ce n'est plus celui qui a produit les artefacts en place.

## Sécurité — hors périmètre de ce prototype, décision assumée (Issue 13+)

L'architecture cible prévoit JWT/RBAC/audit logs (`docs/issues_backlog.md`
Issue 13), nécessaires pour un déploiement réel où le système serait
accessible à plusieurs utilisateurs avec des niveaux d'accès différents.
Ce prototype, purement démonstratif et en lecture seule, non
déployé, n'implémente pas cette couche — l'API expose directement les
résultats déjà calculés (`risk_scores`, `company_stats_*`, etc.), sans
authentification, pour la démonstration. Décision assumée de scope, pas
un oubli.

## API FastAPI (Issue 13) — `api/`

Source de données : **PostgreSQL, pas Parquet** — `companies`, `awards`,
`risk_scores` sont déjà chargées et vérifiées en base
(`scripts/load_database.py`, `scripts/load_risk_scores.py`), et le
service `api` de `docker-compose.yml` dépend déjà de `postgres`, pas de
Spark. Lire Parquet directement ajouterait `pyarrow` à un service censé
rester léger, pour dupliquer une source déjà synchronisée.

```
api/
├── main.py           FastAPI(), description OpenAPI avec le rappel du
│                      principe ("signal statistique, jamais une preuve
│                      de fraude"), monte les routers
├── dependencies.py   get_db() — session SQLAlchemy par requete
├── schemas.py         modeles Pydantic de reponse
└── routes/
    ├── companies.py   GET /companies, /companies/{id}, /companies/ranking
    ├── awards.py       GET /awards/{id}
    └── stats.py        GET /stats/summary
```

`api/auth/`/`api/middleware/` restent vides — scaffoldés pour
l'architecture cible, non implémentés (voir la note de scope
sécurité ci-dessus). Aucun `POST`/`PUT`/`DELETE` nulle part dans
`routes/` — lecture seule stricte, imposée par construction, pas
seulement documentée.

Award.acheteur_public/objet ne sont jamais peuplés par
`extraction/fields.py` (voir `database/models/award.py`) — les routes
lisent toujours ces deux champs sur `award.procurement`, jamais sur les
colonnes (toujours `NULL`) d'`Award` lui-même.

**Vérifié contre la base réelle (`uvicorn api.main:app`, requêtes
`curl`)** :

```
GET /stats/summary
  counts: {procurements: 1750, documents: 390, awards: 454, companies: 200}
  risk_level_distribution: {Faible: 151, Modere: 16, Eleve: 17, Critique: 16}
  (identique a scripts/load_risk_scores.py et ai/risk_score.py)

GET /companies/ranking?limit=3
  #1 COSTACOM (final_score=100.0, dominant_driver=surtout_montant)
  #2 EL6 INNOVATIVE BUILDING SOLUTIONS (98.9, comportement_et_montant)
  #3 DANY D ESSAIS ET ETUDES (93.9, comportement_et_montant)

GET /companies/16 (COSTACOM)
  explanation complete avec la nuance "surtout_montant" (Issue 12),
  1 award liste (montant_ttc=41189000.00, acheteur reel via procurement)

GET /awards/27
  concurrent_retenu brut ("(OH TTC) COSTACOM") expose pour la
  tracabilite, companies=[{id:16, normalized_name:"COSTACOM"}]

GET /companies/999999 -> 404 (pas de risk_score, jamais une reponse
  vide silencieuse presentee comme "0 entreprise")
```

43 tests toujours verts (aucune régression — l'API est un nouveau
consommateur en lecture, ne touche à aucune table existante).

## Refonte du 28/08/2026 — l'unite d'analyse passe de l'entreprise au marche

Rapport complet et chiffre : [`docs/refonte_marche.md`](../docs/refonte_marche.md),
regenerable par `python scripts/report_refonte.py --markdown docs/refonte_marche.md`
(aucun chiffre n'y est ecrit en dur).

### Ce qui a change, en une mesure

    entreprises a 1 marche  : 180/193 (93,3 %) ->  25/180 signalees (13,9 %)
    entreprises a 2 marches :  13/193          ->  13/13  signalees (100  %)

L'ancien modele apprenait la profondeur de presence dans le corpus, un
artefact de couverture du scraping. Un "taux" sur une observation unique
n'est pas un taux.

### Ordre d'execution de la chaine

```bash
python scripts/run_extraction.py                     # JSON, grain lot
python scripts/load_database.py --create-schema      # PostgreSQL

# tout le reste dans l'image ppi-spark
D=postgresql://user:password@postgres:5432/procurement_db
R="docker run --rm --network public-procurement-intelligence_default \
     -e DATABASE_URL=$D -v D:/public-procurement-intelligence:/app -w /app ppi-spark"

$R python -m bigdata.spark.jobs.build_analytics_dataset
$R python -m bigdata.spark.jobs.build_statistics
$R python -m bigdata.spark.jobs.build_market_features   # NOUVEAU — grain marche
$R python -m ai.train_market_model                      # NOUVEAU — modele principal
$R python -m ai.market_red_flags                        # NOUVEAU
$R python -m ai.market_explain                          # NOUVEAU — SHAP + ablation

# etage entreprise, desormais DESCRIPTIF
$R python -m bigdata.spark.jobs.build_features
$R python -m ai.train_isolation_forest
$R python -m ai.scoring && $R python -m ai.risk_score
python scripts/load_risk_scores.py                      # depuis l'hote
```

**`-e DATABASE_URL` est obligatoire** et manquait a la commande documentee
plus haut dans ce fichier : le conteneur ne lit pas `.env`, il retombait donc
sur le defaut `localhost`, qui designe le conteneur lui-meme. Symptome :
`FAILED_JDBC.CONNECTION ... Couldn't connect to the database`.

### Trois defauts trouves en verifiant les sorties, pas en relisant le code

1. **Le modele detectait les trous d'extraction.** Premier Top 10 marche :
   les marches les plus "atypiques" etaient ceux dont on ne savait rien.
   Mesure : 7/7 des marches sans aucune information signales (100 %) contre
   ~6 % quand 2 ou 3 informations existent. Corrige par un seuil de
   completude (`MIN_DATA_COMPLETENESS = 2`) ; correlation score/completude
   ramenee de **-0,249 a +0,063**. 35 marches deviennent non scorables et
   sont affiches comme tels, jamais comme "Faible".
2. **Une colonne constante dans le modele.** `has_competitor_data` sortait a
   une importance SHAP exactement nulle : apres le seuil de completude, elle
   vaut 1 pour les 279 marches retenus. La correlation ne peut pas detecter
   une constante (elle vaut NaN) — d'ou un controle de variance distinct.
3. **Un taux d'exclusion arithmetiquement impossible.** 14 marches declarent
   plus de concurrents ecartes que de soumissionnaires (tous a 1 pour 2-3).
   C'est une incoherence entre deux rubriques extraites, pas un taux de
   300 % : RF02 devient non evaluable sur ces marches. Sans ce traitement,
   le quantile 0,90 de `exclusion_rate` valait exactement 1,000 — un seuil
   degenere qui ne separait plus rien.

### Ce que la refonte ne corrige pas

Le montant reste absent de 63 % des marches ; l'estimation administrative
est hors d'atteinte (0/454), donc aucun ecart estimation/attribution n'est
calculable et le red flag RF04 n'existe pas ; il n'y a **aucune verite
terrain au niveau marche**, donc la stabilite du modele est mesuree mais sa
justesse ne peut pas l'etre.
