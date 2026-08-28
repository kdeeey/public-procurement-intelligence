"""
Verrous sur le Priority Score (Phases 6-7, 28/08/2026).

Ce que ces tests protegent :

  1. La qualite des donnees ne RECOMPENSE jamais : elle n'entre pas dans le
     score, elle plafonne le niveau. Un marche tres atypique dont on ne
     sait presque rien ne doit pas remonter en tete.
  2. La comparaison aux pairs n'est pas comptee deux fois (elle alimente
     deja RF03, donc red_flag_score).
  3. Une composante absente est REPONDEREE, jamais remplacee par un zero.
  4. "Donnees insuffisantes" n'est pas un niveau bas : c'est un etat.
  5. Une stabilite de 0 ne penalise pas un marche jamais entre dans un
     Top 20 — bug mesure et corrige (264/314 marches tombaient a tort en
     confiance faible).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

from ai.priority_score import (  # noqa: E402
    CAPPED_LEVEL, LEVEL_ORDER, W_ANOMALY, W_RED_FLAGS, assign_level,
    compute_confidence, compute_priority_raw,
)

SEUILS = {"p60": 25.0, "p80": 40.0, "p90": 55.0}


def marche(**kwargs) -> pd.Series:
    base = {"scorable": True, "anomaly_score_0_100": 80.0, "red_flag_score": 60.0,
            "data_quality_score": 100.0, "stability_frequency": 10.0}
    base.update(kwargs)
    return pd.Series(base)


def test_formule_a_deux_composantes_ponderees():
    raw = compute_priority_raw(marche(anomaly_score_0_100=80.0, red_flag_score=60.0))
    assert raw == W_ANOMALY * 80.0 + W_RED_FLAGS * 60.0


def test_la_comparaison_aux_pairs_n_est_pas_un_terme_separe():
    """Elle alimente deja RF03 : l'ajouter compterait deux fois le meme
    signal — le piege deja rencontre au niveau entreprise (r=1,000 entre
    market_share et total_amount)."""
    sans = compute_priority_raw(marche())
    avec = compute_priority_raw(marche(amount_vs_peer_median=500.0,
                                       amount_above_peer_p90=True))
    assert sans == avec, "aucune colonne de comparaison ne doit entrer dans le score"


def test_composante_absente_est_reponderee_pas_mise_a_zero():
    """Un marche dont aucune regle n'est evaluable ne doit pas voir sa
    priorite divisee par deux par notre propre manque de donnees."""
    raw = compute_priority_raw(marche(red_flag_score=None))
    assert raw == 80.0
    assert raw != W_ANOMALY * 80.0


def test_qualite_des_donnees_ne_gonfle_jamais_le_score():
    faible = compute_priority_raw(marche(data_quality_score=20.0))
    forte = compute_priority_raw(marche(data_quality_score=100.0))
    assert faible == forte, "la qualite ne doit pas entrer dans le score"


def test_confiance_faible_plafonne_le_niveau():
    """LE garde-fou du cahier des charges : anomalie elevee + donnees
    faibles ne doit pas donner 'Tres prioritaire'."""
    assert assign_level(90.0, "Elevee", SEUILS) == "Tres prioritaire"
    assert assign_level(90.0, "Faible", SEUILS) == CAPPED_LEVEL
    assert assign_level(45.0, "Faible", SEUILS) == CAPPED_LEVEL


def test_plafond_ne_remonte_jamais_un_niveau_bas():
    """Le plafond abaisse, il ne rehausse pas : un marche a faible priorite
    reste faible, quelle que soit sa confiance."""
    assert assign_level(10.0, "Faible", SEUILS) == "Faible"
    assert assign_level(10.0, "Elevee", SEUILS) == "Faible"


def test_donnees_insuffisantes_est_un_etat_pas_un_niveau_bas():
    assert assign_level(None, "Insuffisante", SEUILS) == "Donnees insuffisantes"
    assert compute_confidence(marche(scorable=False)) == "Insuffisante"
    # L'etat existe dans l'ordre des niveaux, distinct de "Faible".
    assert "Donnees insuffisantes" in LEVEL_ORDER
    assert LEVEL_ORDER.index("Donnees insuffisantes") != LEVEL_ORDER.index("Faible")


def test_stabilite_nulle_ne_penalise_pas_un_marche_hors_top20():
    """Bug corrige : `stability_frequency == 0` signifie 'jamais entre dans
    un Top 20', pas 'instable'. Le traiter comme une instabilite faisait
    tomber 264/314 marches (84 %) en confiance faible, et le plafond
    s'appliquait alors presque partout."""
    assert compute_confidence(marche(stability_frequency=0.0)) == "Elevee"
    assert compute_confidence(marche(stability_frequency=None)) == "Elevee"
    # En revanche, une stabilite mesuree ET basse penalise bien.
    assert compute_confidence(marche(stability_frequency=2.0)) == "Faible"


def test_confiance_suit_la_qualite_des_donnees():
    assert compute_confidence(marche(data_quality_score=100.0)) == "Elevee"
    assert compute_confidence(marche(data_quality_score=60.0)) == "Moyenne"
    assert compute_confidence(marche(data_quality_score=20.0)) == "Faible"
