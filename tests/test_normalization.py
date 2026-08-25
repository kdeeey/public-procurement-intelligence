"""
Tests for database/normalization.py (Issue 8).

Every case here traces back to a real string from data/processed/extracted/
or an explicit requirement raised during the Issue 8 design discussion.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from database.normalization import normalize_company_name, split_groupement  # noqa: E402


def test_normalize_merges_case_and_accent_variants():
    assert (normalize_company_name("STE TP HORIZON SARL")
            == normalize_company_name("Sté TP HORIZON SARL"))


def test_normalize_merges_prefix_and_suffix_variants():
    assert (normalize_company_name("La Société BENFORD SARL AU")
            == normalize_company_name("BENFORD SARL AU"))


def test_normalize_does_not_merge_different_companies_sharing_a_word():
    # 3 vraies entreprises distinctes du corpus, toutes contenant "MAROCAINE"
    names = ["STE MAROCAINE DES", "CENTRALE MAROCAINE D'ASSURANCES",
             "LA MAROCAINE D'ASSAINISSEMENT ET"]
    assert len({normalize_company_name(n) for n in names}) == 3


def test_normalize_does_not_correct_ocr_character_errors():
    # doc aabc5317...: erreur OCR confirmee (S/T), pas une variante de forme
    assert normalize_company_name("SIWERGY MAROC") != normalize_company_name("STWERGY MAROC")


def test_split_groupement_two_members_with_legal_suffixes():
    members = split_groupement("Groupement ART STAM SARL AU et TECH-LUX SARL AU")
    assert members == ["ART STAM SARL AU", "TECH-LUX SARL AU"]
    assert [normalize_company_name(m) for m in members] == ["ART STAM", "TECH-LUX"]


def test_split_groupement_marker_avoids_internal_et_trap():
    # doc 03d5069b...: "D'ESSAIS ET ETUDES" contient un ET interne au nom;
    # un split naif sur ET seul le couperait a tort.
    text = ("-GROUPEMENT entre la Société DANY D'ESSAIS ET ETUDES SARL, Tanger "
            "et la Société Solutions Professionnelles Génie Civil S.A.R.L AU, Beni Mellal ;")
    members = split_groupement(text)
    assert len(members) == 2
    normalized = [normalize_company_name(m) for m in members]
    assert normalized == ["DANY D ESSAIS ET ETUDES", "SOLUTIONS PROFESSIONNELLES GENIE CIVIL"]


def test_split_groupement_single_member_when_unsplittable():
    # Aucun marqueur, aucun "ET" a l'interieur -> un seul membre, texte garde.
    assert split_groupement("Groupement ABC INGENIERIE") == ["ABC INGENIERIE"]
