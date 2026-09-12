"""
Verrous sur ai/market_population.py — le filtre ATTRIBUE + la porte de
completude partagee entre ai/market_red_flags.py et
ai/train_market_model.py (refonte "red flags only").

Une seule definition de "scorable" doit exister dans tout le projet ;
ces tests protegent son comportement, pas son emplacement.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

from ai.market_population import MIN_DATA_COMPLETENESS, compute_population  # noqa: E402


def marches() -> pd.DataFrame:
    return pd.DataFrame([
        {"award_id": 1, "statut": "ATTRIBUE", "has_amount_data": 1,
         "has_competitor_data": 1, "has_exclusion_data": 1},
        {"award_id": 2, "statut": "ATTRIBUE", "has_amount_data": 1,
         "has_competitor_data": 0, "has_exclusion_data": 0},
        {"award_id": 3, "statut": "ATTRIBUE", "has_amount_data": 0,
         "has_competitor_data": 1, "has_exclusion_data": 1},
        {"award_id": 4, "statut": "INFRUCTUEUX", "has_amount_data": 1,
         "has_competitor_data": 1, "has_exclusion_data": 1},
    ])


def test_ne_garde_que_les_marches_attribues():
    result = compute_population(marches())
    assert set(result["award_id"]) == {1, 2, 3}
    assert 4 not in set(result["award_id"])


def test_data_completeness_est_la_somme_des_trois_drapeaux():
    result = compute_population(marches()).set_index("award_id")
    assert result.loc[1, "data_completeness"] == 3
    assert result.loc[2, "data_completeness"] == 1
    assert result.loc[3, "data_completeness"] == 2


def test_scorable_suit_min_data_completeness():
    assert MIN_DATA_COMPLETENESS == 2
    result = compute_population(marches()).set_index("award_id")
    assert bool(result.loc[1, "scorable"]) is True   # 3/3
    assert bool(result.loc[2, "scorable"]) is False  # 1/3
    assert bool(result.loc[3, "scorable"]) is True   # 2/3


def test_ne_filtre_pas_sur_scorable():
    """Les marches non scorables restent dans le retour — c'est aux etages
    avals (red flags, entrainement) de decider quoi en faire."""
    result = compute_population(marches())
    assert len(result) == 3
    assert (~result["scorable"]).sum() == 1
