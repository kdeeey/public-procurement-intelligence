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


def test_plausible_names_rejects_noise_and_empty_input():
    assert _plausible_names(None) == []
    assert _plausible_names([]) == []
    assert _plausible_names(["Justification du choix de l'attributaire"]) == []


def test_plausible_names_keeps_distinct_real_names():
    result = _plausible_names(["TECTRA", "IBECOM", "ELESI"])
    assert result == ["ELESI", "IBECOM", "TECTRA"]
