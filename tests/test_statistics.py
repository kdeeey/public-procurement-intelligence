"""
Tests for bigdata/spark/jobs/build_statistics.py's pure-Python helpers
(Issue 10). The Spark aggregation logic itself (groupBy/join/window) is
validated by the job's own built-in cross-checks against known counts
(454 Award, 237 with company, 455 fact rows) when run for real against
PostgreSQL — same pattern as run_extraction.py/validate_extraction.py in
Issue 7 and build_analytics_dataset.py in Issue 9, not a separate pytest
suite for the DataFrame logic.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from bigdata.spark.jobs.build_statistics import _plausible_names  # noqa: E402


def test_plausible_names_dedups_case_and_accent_variants():
    # Meme entreprise, deux graphies — doit compter comme 1 seul soumissionnaire.
    result = _plausible_names(["STE TP HORIZON SARL", "Sté TP HORIZON SARL"])
    assert result == ["TP HORIZON"]


def test_plausible_names_distinguishes_unknown_from_zero():
    """UNKNOWN != ZERO, verrouille le 28/08/2026.

    Ce test affirmait l'inverse jusqu'ici (`_plausible_names(None) == []`) :
    il encodait le defaut, pas le contrat. Une rubrique concurrents absente
    du document devenait une liste vide, donc "0 soumissionnaire", donc un
    marche a soumissionnaire unique — sur 107/454 Award (23,6 % du corpus).

    Les trois etats doivent rester distincts de bout en bout :
      None -> None  : le document ne dit rien, on ne sait pas.
      []   -> []    : le document liste ses concurrents, il n'y en a aucun.
      bruit-> []    : le document liste quelque chose qui n'est pas un nom,
                      ce qui reste une observation (la rubrique existe).
    """
    assert _plausible_names(None) is None, "l'inconnu ne doit jamais devenir un zero"
    assert _plausible_names([]) == []
    assert _plausible_names(["Justification du choix de l'attributaire"]) == []


def test_plausible_names_keeps_distinct_real_names():
    result = _plausible_names(["TECTRA", "IBECOM", "ELESI"])
    assert result == ["ELESI", "IBECOM", "TECTRA"]
