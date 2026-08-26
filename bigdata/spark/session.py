"""
Spark session + PostgreSQL JDBC connectivity (Issue 9).

Local-only, per the backlog ("Pipeline PySpark local") — no `spark` service
in docker-compose.yml, Dockerfile has no JVM. Two local requirements this
session setup does NOT install for you, both discovered by actually running
Spark against real PostgreSQL rather than assuming it would just work:

  1. A JVM (Java 17+) on PATH — already true on this dev machine (Java 25).
  2. On Windows specifically: HADOOP_HOME pointing at a directory with
     bin/winutils.exe (+ hadoop.dll) — needed for Spark's own local file
     handling (distributing the JDBC jar to the executor), NOT for talking
     to an actual Hadoop cluster. Missing this fails with
     "HADOOP_HOME and hadoop.home.dir are unset" before SparkContext even
     starts. Document this in bigdata/README.md, same pattern as
     TESSERACT_CMD in .env.example for OCR.

The PostgreSQL JDBC driver is passed as a jar, not spark.jars.packages
(Maven coordinate resolution): Spark's Ivy resolver failed against Maven
Central in the environment this was developed in even though plain HTTP
(curl) reached the exact same URL fine — a JVM-side resolver quirk, not a
real network outage. A local jar sidesteps it entirely and is more
reproducible anyway (no build-time dependency on Maven Central being
reachable). Set POSTGRES_JDBC_JAR to the jar's path; download it once with:

    curl -o postgresql.jar \
      https://repo1.maven.org/maven2/org/postgresql/postgresql/42.7.4/postgresql-42.7.4.jar
"""

from __future__ import annotations

import os
import sys

from pyspark.sql import SparkSession

DEFAULT_DATABASE_URL = "postgresql://user:password@localhost:5432/procurement_db"
JDBC_DRIVER_CLASS = "org.postgresql.Driver"


def get_spark_session(app_name: str = "ppi-analytics") -> SparkSession:
    builder = SparkSession.builder.appName(app_name).master(
        os.getenv("SPARK_MASTER", "local[*]"))

    # Spark defaults its Python worker subprocess to "python3", which is
    # not guaranteed to exist on PATH (confirmed: it doesn't on this dev
    # machine, only a specific python.exe does) — any job using a UDF
    # (e.g. build_statistics.py's plausibility filter) fails with
    # "Cannot run program 'python3': ... file not found" without this.
    # sys.executable is always correct regardless of which Python launched
    # this process, so no environment-specific guessing is needed. Set as
    # the PYSPARK_PYTHON *environment variable*, not just the
    # spark.pyspark.python config key — confirmed by testing both that the
    # config key alone does not reliably reach the local-mode worker
    # subprocess spawn, while the env var does.
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)
    builder = (builder
              .config("spark.pyspark.python", sys.executable)
              .config("spark.pyspark.driver.python", sys.executable)
              # Confirmed on this machine: a UDF-touching action after the
              # first one in a session times out with a socket
              # TimeoutError on local[*] Windows, consistently — a reused
              # worker process appears to end up in a bad state after its
              # first task completes. Forcing a fresh worker per task
              # avoids reuse entirely; costs a bit of startup latency per
              # UDF call, irrelevant at this corpus's scale (hundreds of
              # rows, not millions).
              .config("spark.python.worker.reuse", "false")
              # Spark's default of 200 shuffle partitions assumes a
              # cluster-scale dataset. Combined with worker.reuse=false
              # above (a fresh process per task, not just per stage), 200
              # partitions meant 200 process spawns for a ~230-row corpus —
              # minutes of pure startup overhead for a job that should take
              # seconds. This corpus's scale (hundreds of rows, not
              # millions) never needs more than a handful of partitions.
              .config("spark.sql.shuffle.partitions", "8"))

    jar_path = os.getenv("POSTGRES_JDBC_JAR")
    if jar_path:
        builder = builder.config("spark.jars", jar_path)
    else:
        # Repli Maven — fonctionne hors de l'environnement de developpement
        # ou ce module a ete ecrit, ou le resolveur Ivy a echoue malgre un
        # acces reseau confirme par ailleurs (voir docstring du module).
        builder = builder.config(
            "spark.jars.packages", "org.postgresql:postgresql:42.7.4")

    return builder.getOrCreate()


def jdbc_url_and_properties(database_url: str | None = None) -> tuple[str, dict]:
    """`postgresql://user:pass@host:port/db` (SQLAlchemy-style, same
    DATABASE_URL as database/crud/session.py) -> (JDBC URL, connection
    properties) — one source of truth for the connection string across
    both the SQLAlchemy and Spark sides of this project."""
    from urllib.parse import urlparse

    url = database_url or os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    parsed = urlparse(url.replace("postgresql://", "http://", 1))
    jdbc_url = f"jdbc:postgresql://{parsed.hostname}:{parsed.port or 5432}{parsed.path}"
    properties = {
        "user": parsed.username or "",
        "password": parsed.password or "",
        "driver": JDBC_DRIVER_CLASS,
    }
    return jdbc_url, properties


def read_table(spark: SparkSession, table: str, database_url: str | None = None):
    jdbc_url, properties = jdbc_url_and_properties(database_url)
    return spark.read.jdbc(url=jdbc_url, table=table, properties=properties)
