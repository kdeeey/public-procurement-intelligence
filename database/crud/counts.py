"""
Recoupements de volumetrie lus depuis la BASE, jamais figes en constante.

Pourquoi ce module existe (27/08/2026). Les jobs `bigdata/` et les scripts
`ai/` portaient des controles de la forme :

    if n_companies != 200 or n_awards != 210:
        raise RuntimeError("recoupement echoue")

Ces controles sont utiles — ils ont reellement attrape des incoherences
entre etages du pipeline — mais leur valeur attendue etait ecrite en dur au
moment ou la table comptait 200 `Company`. Le correctif de nettoyage des
noms d'entreprise (voir `extraction/company_name.py`) l'a portee a 213 : les
cinq etages de la chaine analytique echouaient alors tous, non pas parce
qu'un recoupement etait faux, mais parce que la reference etait perimee.

La reference correcte est la base elle-meme. Un parquet qui ne correspond
plus au nombre de `Company` en base est effectivement perime et doit etre
rejoue — c'est precisement ce que le controle doit dire, et il le dit
maintenant sans avoir a etre reedite a chaque evolution du corpus.
"""

from __future__ import annotations

from sqlalchemy import func, select

from database.crud.session import get_engine
from database.models import Award, Company, award_companies


def company_count(database_url: str | None = None) -> int:
    """Nombre de `Company` en base — la reference de tous les etages aval."""
    with get_engine(database_url).connect() as conn:
        return int(conn.execute(select(func.count(Company.id))).scalar_one())


def awards_with_company_count(database_url: str | None = None) -> int:
    """Nombre d'`Award` DISTINCTS lies a au moins une `Company`.

    Distinct, pas un `count(*)` sur la table de liaison : un groupement lie
    un seul Award a plusieurs Company (data_dictionary.md Sec 3.1) et
    compterait double sinon.
    """
    with get_engine(database_url).connect() as conn:
        return int(conn.execute(
            select(func.count(func.distinct(award_companies.c.award_id)))
        ).scalar_one())


def award_count(database_url: str | None = None) -> int:
    with get_engine(database_url).connect() as conn:
        return int(conn.execute(select(func.count(Award.id))).scalar_one())


def check_against_database(actual: int, expected: int, label: str,
                           hint: str = "rejouer les jobs bigdata/spark/jobs/") -> None:
    """Compare une volumetrie de parquet au chiffre lu en base, et echoue
    avec un message qui dit quoi faire plutot que "diagnostiquer"."""
    print(f"{label} : {actual} (attendu {expected}, lu depuis la base)")
    if actual != expected:
        raise RuntimeError(
            f"recoupement echoue sur {label} : {actual} en entree contre "
            f"{expected} en base — l'artefact en entree est perime, {hint}")
