"""
Verrous sur le Priority Score, refonte "red flags only" — le niveau est
une fonction pure du compte de red flags prioritaires (RF01+RF02+RF03),
jamais du score du modele.

Ce que ces tests protegent :

  1. `priority_level` ne depend QUE de `priority_flag_count` (0-3), jamais
     de `anomaly_score_0_100` : un score de modele eleve ne doit jamais
     faire franchir une tranche de niveau.
  2. `priority_raw` reste un ordre de tri valide a l'interieur d'un meme
     compte (le score du modele depart les egalites) sans jamais depasser
     dans la tranche voisine.
  3. La qualite des donnees ne RECOMPENSE jamais : elle n'entre pas dans
     le score, elle plafonne le niveau.
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
    CAPPED_LEVEL, COUNT_MULTIPLIER, LEVEL_BY_COUNT, LEVEL_ORDER, assign_level,
    compute_confidence, compute_priority_raw,
)


def marche(**kwargs) -> pd.Series:
    base = {"scorable": True, "anomaly_score_0_100": 50.0, "priority_flag_count": 2,
            "data_quality_score": 100.0, "stability_frequency": 10.0}
    base.update(kwargs)
    return pd.Series(base)


def test_priority_raw_est_le_compte_domine_par_le_score_du_modele():
    raw = compute_priority_raw(marche(priority_flag_count=2, anomaly_score_0_100=37.5))
    assert raw == COUNT_MULTIPLIER * 2 + 37.5


def test_le_niveau_ne_depend_que_du_compte_jamais_du_score_du_modele():
    """Le coeur de la refonte : un score de modele au maximum (100) avec
    1 seul flag actif ne doit JAMAIS produire un niveau plus haut qu'un
    score au minimum (0) avec 2 flags actifs."""
    un_flag_score_maximal = compute_priority_raw(
        marche(priority_flag_count=1, anomaly_score_0_100=100.0))
    deux_flags_score_minimal = compute_priority_raw(
        marche(priority_flag_count=2, anomaly_score_0_100=0.0))
    assert un_flag_score_maximal < deux_flags_score_minimal
    assert (assign_level(un_flag_score_maximal, "Elevee")
            == LEVEL_BY_COUNT[1] == "A surveiller")
    assert (assign_level(deux_flags_score_minimal, "Elevee")
            == LEVEL_BY_COUNT[2] == "Prioritaire")


def test_le_score_du_modele_depart_les_egalites_de_compte():
    """A compte egal, le marche que le modele juge le plus rare doit
    ressortir devant — mais toujours dans la meme tranche de niveau."""
    a = compute_priority_raw(marche(priority_flag_count=2, anomaly_score_0_100=80.0))
    b = compute_priority_raw(marche(priority_flag_count=2, anomaly_score_0_100=20.0))
    assert a > b
    assert assign_level(a, "Elevee") == assign_level(b, "Elevee") == "Prioritaire"


def test_tous_les_comptes_sont_representes():
    assert set(LEVEL_BY_COUNT) == {0, 1, 2, 3}
    assert LEVEL_BY_COUNT[0] == "Faible"
    assert LEVEL_BY_COUNT[3] == "Tres prioritaire"


def test_composante_absente_donne_priority_raw_none():
    """Un marche non scorable (priority_flag_count non evaluable) n'a pas
    de cle de tri fabriquee — None, jamais une valeur par defaut."""
    assert compute_priority_raw(marche(priority_flag_count=None)) is None
    assert compute_priority_raw(marche(anomaly_score_0_100=None)) is None


def test_qualite_des_donnees_ne_gonfle_jamais_le_score():
    faible = compute_priority_raw(marche(data_quality_score=20.0))
    forte = compute_priority_raw(marche(data_quality_score=100.0))
    # data_quality_score n'entre meme pas dans le calcul de priority_raw.
    assert faible == forte


def test_confiance_faible_plafonne_le_niveau():
    """LE garde-fou du cahier des charges : 3/3 flags + donnees faibles ne
    doit pas donner 'Tres prioritaire'."""
    trois_flags = compute_priority_raw(marche(priority_flag_count=3, anomaly_score_0_100=90.0))
    assert assign_level(trois_flags, "Elevee") == "Tres prioritaire"
    assert assign_level(trois_flags, "Faible") == CAPPED_LEVEL

    un_flag = compute_priority_raw(marche(priority_flag_count=1, anomaly_score_0_100=45.0))
    assert assign_level(un_flag, "Faible") == "A surveiller"  # deja au plafond, rien a abaisser


def test_plafond_ne_remonte_jamais_un_niveau_bas():
    """Le plafond abaisse, il ne rehausse pas : un marche a faible priorite
    reste faible, quelle que soit sa confiance."""
    zero_flag = compute_priority_raw(marche(priority_flag_count=0, anomaly_score_0_100=10.0))
    assert assign_level(zero_flag, "Faible") == "Faible"
    assert assign_level(zero_flag, "Elevee") == "Faible"


def test_donnees_insuffisantes_est_un_etat_pas_un_niveau_bas():
    assert assign_level(None, "Insuffisante") == "Donnees insuffisantes"
    assert compute_confidence(marche(scorable=False)) == "Insuffisante"
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
