# Image d'execution du pipeline analytique (PySpark + IA).
#
# POURQUOI ELLE EXISTE (27/08/2026)
# ---------------------------------
# `bigdata/README.md` decrivait jusqu'ici le pipeline PySpark comme
# "local uniquement", avec deux prerequis a installer a la main sur la
# machine de developpement Windows :
#
#   * POSTGRES_JDBC_JAR — le driver JDBC PostgreSQL, telecharge une fois ;
#   * HADOOP_HOME / winutils.exe — un binaire Windows tiers non signe, sans
#     lequel Spark refuse de demarrer sur Windows ("HADOOP_HOME and
#     hadoop.home.dir are unset", leve dans l'initialiseur statique de
#     org.apache.hadoop.util.Shell, AVANT meme le SparkContext).
#
# Ces deux fichiers avaient disparu de la machine, rendant tout le pipeline
# injouable — et c'est structurel, pas accidentel : une etape qui depend de
# binaires installes a la main hors du depot n'est pas reproductible.
#
# Sous Linux, winutils.exe n'existe simplement pas : le probleme disparait.
# Cette image supprime donc les deux prerequis d'un coup — le JDK vient de
# la distribution, le jar JDBC est telecharge a la construction.
#
# Elle porte AUSSI les dependances des scripts `ai/` (scikit-learn, joblib,
# pandas, pyarrow) pour que la chaine complete
# Spark -> Isolation Forest -> risk_score tourne dans le meme environnement,
# sans repasser par l'hote entre deux etapes.
#
#   docker build -f docker/spark.Dockerfile -t ppi-spark .
#   docker run --rm --network public-procurement-intelligence_default \
#       -v "D:/public-procurement-intelligence:/app" -w /app ppi-spark \
#       python -m bigdata.spark.jobs.build_analytics_dataset
#
# Le service `postgres` est joignable par son nom d'hote sur le reseau
# compose — c'est deja la valeur de DATABASE_URL dans .env
# (postgresql://user:password@postgres:5432/procurement_db), contrairement
# aux scripts lances depuis l'hote qui doivent passer par localhost (voir
# la section "postgres vs localhost" de bigdata/README.md).

FROM python:3.11-slim

# PySpark 4.x exige Java 17+ (le eclipse-temurin:11-jdk present sur la
# machine de dev est trop ancien). JRE headless suffit : on execute du
# bytecode, on n'en compile pas.
#
# Java 21 et non 17 : python:3.11-slim est passe a Debian trixie, dont les
# depots ne proposent plus openjdk-17 ("Package openjdk-17-jre-headless has
# no installation candidate", rencontre a la construction). 21 est la LTS
# qu'ils portent, et Spark 4 la supporte.
RUN apt-get update && apt-get install -y --no-install-recommends \
        openjdk-21-jre-headless \
        curl \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64

# Le driver JDBC, fige a la construction plutot que resolu a l'execution :
# `spark.jars.packages` (resolution Ivy/Maven) avait echoue dans
# l'environnement de developpement malgre un reseau fonctionnel, et un jar
# local rend de toute facon les executions reproductibles sans dependre de
# la disponibilite de Maven Central.
ARG POSTGRES_JDBC_VERSION=42.7.4
RUN curl -fsSL -o /opt/postgresql.jar \
    "https://repo1.maven.org/maven2/org/postgresql/postgresql/${POSTGRES_JDBC_VERSION}/postgresql-${POSTGRES_JDBC_VERSION}.jar"
ENV POSTGRES_JDBC_JAR=/opt/postgresql.jar

WORKDIR /app

# Sous-ensemble deliberement reduit de requirements.txt : ni Tesseract, ni
# scrapy, ni spacy, ni streamlit — cette image ne fait tourner que l'aval
# analytique (bigdata/ et ai/), pas le scraping ni l'OCR.
RUN pip install --no-cache-dir \
        "pyspark>=3.5" \
        pyarrow \
        pandas \
        numpy \
        "sqlalchemy>=2.0" \
        psycopg2-binary \
        scikit-learn \
        joblib \
        python-dotenv

# Le code est monte en volume a l'execution (-v), jamais copie : l'image
# reste valable pendant qu'on itere sur les jobs.
CMD ["python", "-c", "import pyspark, sklearn; print('pyspark', pyspark.__version__, '| sklearn', sklearn.__version__)"]
