"""
Tests for extraction/ (Issue 7).

Every fixture below is copied verbatim (or near-verbatim, trimmed for length)
from a real document in data/processed/ocr/ that exposed a genuine bug during
development — not synthesized to make the regex look good. The doc_id in each
test name is the source, so a regression can be traced back to the exact
document that first caught it.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from extraction.extractor import extract_document  # noqa: E402
from extraction.fields import (  # noqa: E402
    extract_concurrent_retenu,
    extract_dates,
    extract_montants,
    extract_reference,
)
from extraction.lots import segment_lots  # noqa: E402


# --------------------------------------------------------------------------- #
# fields.py — reference
# --------------------------------------------------------------------------- #

def test_reference_crosses_newline_after_ouvert():
    # doc 9140a66a...: reference sits on the line after "... OUVERT", not on
    # the same line as the label.
    text = "EXTRAIT DU PROCES VERBAL DE D'APPEL D'OFFRES OUVERT \nN°08/2023/CRIDOE\n"
    assert extract_reference(text) == "08/2023/CRIDOE"


# --------------------------------------------------------------------------- #
# fields.py — dates
# --------------------------------------------------------------------------- #

def test_date_ouverture_clean_date_not_corrupted_by_ocr_tolerance():
    # doc 9140a66a...: the OCR-tolerant separator class must not eat the real
    # "/" and the leading "1" of "12" on a clean, unambiguous date.
    text = "Date et heure d'ouverture des plis : 28/12/2023"
    assert extract_dates(text)["date_ouverture_plis"] == "28/12/2023"


def test_date_ouverture_recovers_ocr_corrupted_separator():
    # The confirmed corrupted case (methodology.md §2.9) the tolerant
    # fallback exists for: "/" misread, producing extra digit characters.
    text = "Date et heure d'ouverture des plis : 13107 /2026"
    assert extract_dates(text)["date_ouverture_plis"] == "13/07/2026"


def test_date_achevement_de_stripped_by_arabic_bleed_removal():
    # doc 2a36f6540d91...: text_cleaning.split_scripts() removes a
    # bidi-wrapped Arabic word that happened to stand in for "de", leaving
    # "des travaux la commission" — the label must still match.
    text = "Date d'achévement des travaux la commission : 31/12/2024"
    assert extract_dates(text)["date_achevement_commission"] == "31/12/2024"


def test_date_achevement_textual_with_ocr_digit_substitution():
    # doc 48f26629ef23...: "l5" for "15" (l/1 OCR confusion) inside a
    # textual, not numeric, date.
    text = "Date d'achèvement des travaux de la commission : Mercredi l5 juillet 2026."
    assert extract_dates(text)["date_achevement_commission"] == "15/07/2026"


# --------------------------------------------------------------------------- #
# fields.py — concurrent_retenu
# --------------------------------------------------------------------------- #

def test_concurrent_retenu_prose_sentence():
    # doc 9140a66a...: the winner's name is embedded in a justification
    # sentence, not standing alone after the label.
    text = (
        "Concurrent retenu :  \n"
        "L'offre économiquement la plus avantageuse est l'offre présentée par "
        "la société TECTRA, pour \nun montant de 721 224.86 Dirhams TTC"
    )
    assert extract_concurrent_retenu(text) == "TECTRA"


def test_concurrent_retenu_groupement_stays_whole():
    # doc 03d5069b...: a consortium must never be split into one company
    # (data_dictionary.md §3.1), and the value sits two lines below the
    # label, past a re-stated table-header line.
    text = (
        "- Concurrent retenu :\n"
        "Concurrent retenu Montant d'acte d'engagement\n"
        "-GROUPEMENT entre la Société DANY D'ESSAIS ET ETUDES SARL,\n"
        "Tanger et la Société Solutions Professionnelles Génie Civil S.A.R.L AU.\n"
    )
    result = extract_concurrent_retenu(text)
    assert result is not None
    assert "GROUPEMENT" in result
    assert "DANY" in result
    assert "Solutions Professionnelles" in result


def test_concurrent_retenu_caption_line_skipped():
    # doc 3a6a7d16...: a table caption ("Montant d'acte d'engagement en Dhs
    # TTC") must not be mistaken for the winner's name.
    text = (
        "- Concurrent retenu :\n\n"
        "Concurrents\n\n"
        "Montant d'acte d'engagement en Dhs TTC\n\n"
        "Société RACHAD ISTITMAR SARL 4 158 240,00\n"
    )
    result = extract_concurrent_retenu(text)
    assert result is not None
    assert "RACHAD ISTITMAR" in result


# --------------------------------------------------------------------------- #
# fields.py — montants
# --------------------------------------------------------------------------- #

def test_montant_ttc_with_spelled_out_currency():
    # doc 9140a66a...: "Dirhams" spelled out, not the "DH"/"MAD" abbreviation.
    text = "un montant de 721 224.86 Dirhams TTC"
    result = extract_montants(text)
    assert result.montant_ttc == 721224.86
    assert result.montant_base_affichee == "TTC"


def test_montant_no_bogus_match_inside_currency_word():
    # doc 9140a66a...: the OCR digit-confusion class (S -> 5) must not treat
    # the literal "s" of "Dhs" as a one-digit amount.
    text = "Montant des actes d'engagement en Dhs T.T.C"
    result = extract_montants(text)
    assert result.montant_ttc is None


def test_montant_header_then_amount_on_next_line():
    # doc 3a6a7d16...: the dominant real layout — a header names the base,
    # the amount sits on the following line next to the bidder's name.
    text = (
        "- Concurrent retenu :\n\n"
        "Concurrents\n\n"
        "Montant d'acte d'engagement en Dhs TTC\n\n"
        "Société RACHAD ISTITMAR SARL 4 158 240,00\n"
    )
    result = extract_montants(text)
    assert result.montant_ttc == 4158240.0


def test_montant_row_index_not_mistaken_for_amount():
    # doc 2a36f6540d91...: a table row prefixed with "01" (the row number)
    # must not be picked up in place of the real amount that follows.
    text = (
        "Concurrent attributaire :\n\n"
        "Concurrent attributaire . Montant TTC | Délai d'exécution |\n\n"
        "01 HYDROLIQUE ET ELECTRIQUE - | 179.400,00 MAD | 1 5 |\n"
    )
    result = extract_montants(text)
    assert result.montant_ttc == 179400.0


def test_montant_ocr_letter_substitution_in_digits():
    # doc 48f26629ef23...: "O" for "0" inside the amount itself, immediately
    # adjacent to its TTC marker.
    text = "La Société BENFORD SARL AU\n949 O92,OO DHS TTC"
    result = extract_montants(text)
    assert result.montant_ttc == 949092.0


def test_montant_absent_marker_stays_none_not_guessed():
    # data_dictionary.md §3.6: a document that never states HT or TTC must
    # leave both fields None rather than assume a base.
    text = "Montant de l'acte d'engagement : 61 632,00 DH"
    result = extract_montants(text)
    assert result.montant_ttc is None
    assert result.montant_ht is None
    assert result.montant_base_affichee is None


# --------------------------------------------------------------------------- #
# lots.py — segmentation (see module docstring for the measured 4-case rule)
# --------------------------------------------------------------------------- #

def test_lots_address_false_positive_ignored():
    text = "SOCIETE ROMATELEC, LOT 27-BD SAAD BOUJAMAA RESIDENCE EL MERS"
    segments = segment_lots(text)
    assert len(segments) == 1
    assert segments[0].numero is None
    assert segments[0].detection == "mono_sans_numero"


def test_lots_mono_numerote_keeps_lot_number():
    text = "Renforcement de l'AEP de la ville de Dakhla - Lot n°2: Conduite (RMC 1000 m3)"
    segments = segment_lots(text)
    assert len(segments) == 1
    assert segments[0].numero == 2
    assert segments[0].detection == "mono_numerote"


def test_lots_multi_declare_reconstructs_awarded_lot_by_complement():
    # The confirmed trap: lot 1 is never printed as "Lot n°1" anywhere, only
    # recoverable via the "(3 LOTS)" total marker and the named infructueux
    # lots' complement.
    text = (
        "Marché (3 LOTS)\n"
        "Liste des lots infructueux : Lot n°02; Lot n°03.\n"
    )
    segments = segment_lots(text)
    numeros = sorted(s.numero for s in segments)
    assert numeros == [1, 2, 3]
    lot1 = next(s for s in segments if s.numero == 1)
    assert not lot1.declared_infructueux
    lot2 = next(s for s in segments if s.numero == 2)
    assert lot2.declared_infructueux


# --------------------------------------------------------------------------- #
# extractor.py — orchestration, per-lot statut
# --------------------------------------------------------------------------- #

def test_extractor_multi_lot_statut_is_per_lot_not_per_document():
    # A document-level keyword search on "infructueux" would incorrectly
    # mark the whole document infructueux, including the awarded lot.
    text = (
        "Marché (2 LOTS)\n"
        "Concurrent retenu : ACME TRAVAUX\n"
        "Liste des lots infructueux : Lot n°02.\n"
    )
    awards = extract_document("test-doc", text)
    by_lot = {a.lot_numero: a for a in awards}
    assert by_lot[2].statut == "INFRUCTUEUX"
