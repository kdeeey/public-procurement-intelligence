"""
Verrous sur le Data Quality Score (Phase 1, 28/08/2026).

Ce que ces tests protegent :

  1. Les QUATRE etats restent distincts. En particulier UNKNOWN (le
     document ne dit rien) et INVALID (le document dit quelque chose
     d'incoherent) ne doivent jamais fusionner — ni entre eux, ni avec un
     KNOWN valant zero.
  2. NOT_APPLICABLE sort du denominateur, UNKNOWN et INVALID y restent.
     Un marche infructueux ne doit pas etre penalise pour un attributaire
     qui ne pouvait pas exister.
  3. Un zero REELLEMENT observe reste un KNOWN. C'est la contrepartie de
     la regle UNKNOWN != ZERO : elle interdit de fabriquer un zero, pas
     d'en lire un.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

from features.data_quality import (  # noqa: E402
    ALWAYS_AVAILABLE, SCORED_DIMENSIONS, State, assess_market, compute_quality,
    quality_level,
)


def marche(**kwargs) -> pd.Series:
    base = {
        "statut": "ATTRIBUE",
        "montant_ttc": 500_000.0,
        "has_competitor_data": 1, "nb_soumissionnaires": 4,
        "has_exclusion_data": 1, "exclusion_rate": 0.25,
        "date_ouverture_plis": pd.Timestamp("2025-03-12"), "annee": 2025,
        "has_winner": 1,
    }
    base.update(kwargs)
    return pd.Series(base)


def test_marche_complet_score_100():
    states = assess_market(marche())
    assert all(s is State.KNOWN for s in states.values())
    assert compute_quality(states)["data_quality_score"] == 100.0


def test_unknown_et_invalid_ne_fusionnent_pas():
    """Le coeur du module : deux facons differentes de ne pas pouvoir
    conclure, qui doivent rester lisibles separement."""
    inconnu = assess_market(marche(has_competitor_data=0, nb_soumissionnaires=None))
    invalide = assess_market(marche(nb_soumissionnaires=0))
    assert inconnu["concurrents"] is State.UNKNOWN
    assert invalide["concurrents"] is State.INVALID

    q_inconnu = compute_quality(inconnu)
    q_invalide = compute_quality(invalide)
    # Meme penalite sur le score (les deux empechent de conclure)...
    assert q_inconnu["data_quality_score"] == q_invalide["data_quality_score"]
    # ...mais des compteurs distincts, pour que la CAUSE reste visible.
    assert q_inconnu["missing_fields_count"] == 1
    assert q_inconnu["invalid_fields_count"] == 0
    assert q_invalide["missing_fields_count"] == 0
    assert q_invalide["invalid_fields_count"] == 1


def test_zero_reellement_observe_reste_known():
    """Aucun concurrent ecarte, lu dans le document : c'est une mesure.
    La regle UNKNOWN != ZERO interdit de FABRIQUER un zero, pas d'en lire
    un — sans quoi elle detruirait l'information qu'elle protege."""
    states = assess_market(marche(exclusion_rate=0.0, has_exclusion_data=1))
    assert states["exclusions"] is State.KNOWN


def test_marche_attribue_sans_soumissionnaire_est_invalide():
    """On ne peut pas attribuer un marche a personne. Mesure : 56 marches
    concernes, dont 35 ou des noms figuraient bien dans le document mais
    ont tous ete rejetes par le filtre de plausibilite — un defaut
    d'extraction, jamais une absence de concurrence."""
    assert assess_market(marche(nb_soumissionnaires=0))["concurrents"] is State.INVALID
    # Sur un marche infructueux, en revanche, 0 soumissionnaire exploitable
    # n'a rien de contradictoire.
    assert assess_market(
        marche(statut="INFRUCTUEUX", nb_soumissionnaires=0))["concurrents"] is State.KNOWN


def test_taux_exclusion_impossible_est_invalide():
    assert assess_market(marche(exclusion_rate=3.0))["exclusions"] is State.INVALID


def test_gagnant_non_applicable_sur_infructueux_et_hors_denominateur():
    """0/140 marches infructueux ont un attributaire, par construction.
    Les noter sur 5 dimensions les penaliserait pour une information qui
    ne pouvait pas exister."""
    states = assess_market(marche(statut="INFRUCTUEUX", has_winner=0))
    assert states["gagnant"] is State.NOT_APPLICABLE
    q = compute_quality(states)
    assert q["evaluable_fields_count"] == 4, "NOT_APPLICABLE doit sortir du denominateur"
    assert q["not_applicable_fields_count"] == 1
    assert q["data_quality_score"] == 100.0, (
        "un marche infructueux dont tout le reste est lu doit pouvoir "
        "atteindre 100, pas etre plafonne a 80")


def test_ecart_annee_tolere_un_an_pas_sept():
    """Une procedure a cheval sur deux annees est ordinaire ; un ecart de
    7 ans est une lecture fausse (1 cas mesure dans le corpus)."""
    assert assess_market(marche(date_ouverture_plis=pd.Timestamp("2024-12-20"),
                                annee=2025))["date"] is State.KNOWN
    assert assess_market(marche(date_ouverture_plis=pd.Timestamp("2018-05-02"),
                                annee=2025))["date"] is State.INVALID


def test_date_absente_est_unknown_pas_invalide():
    assert assess_market(marche(date_ouverture_plis=None))["date"] is State.UNKNOWN


def test_dimensions_toujours_disponibles_sont_hors_score():
    """Six champs sont renseignes a 100 % : les noter donnerait le meme
    plancher a tous les marches et gonflerait le score sans rien
    distinguer."""
    assert not set(SCORED_DIMENSIONS) & set(ALWAYS_AVAILABLE)
    assert "estimation" not in SCORED_DIMENSIONS, "0/454 dans le corpus"
    assert "localisation" not in SCORED_DIMENSIONS, "absente de la table de faits"


def test_niveaux_de_qualite():
    assert quality_level(100.0) == "Excellent"
    assert quality_level(90.0) == "Excellent"
    assert quality_level(80.0) == "Bon"
    # 75 et 50 sont des valeurs REELLEMENT atteignables (26 et 38 marches) :
    # les bornes sont inclusives, ces marches basculent vers le haut.
    assert quality_level(75.0) == "Bon"
    assert quality_level(50.0) == "Moyen"
    assert quality_level(40.0) == "Faible"
    assert quality_level(0.0) == "Faible"
    assert quality_level(None) == "Non evaluable"


def test_score_none_si_aucune_dimension_evaluable():
    """Cas absent du corpus actuel, mais un 0 y serait faux plutot que
    prudent : ne rien pouvoir evaluer n'est pas une qualite nulle."""
    q = compute_quality({d: State.NOT_APPLICABLE for d in SCORED_DIMENSIONS})
    assert q["data_quality_score"] is None
    assert quality_level(q["data_quality_score"]) == "Non evaluable"
