"""
Offline tests for the consultation parser — no network access.

Every fixture below reproduces a quirk actually observed on live PMMP pages
(see the parser module docstring). Tests against the full saved pages in
data/raw/ are skipped when those files are absent, so the suite stays green on
a fresh clone.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scraper.pmmp.parsers.consultation_parser import (  # noqa: E402
    normalize_reference,
    parse_amount,
    parse_date_iso,
    parse_detail_page,
    parse_listing_rows,
    parse_oui_non,
)

DETAIL_HTML = """
<html><body>
  <div class="line">Date et heure limite de remise des plis : 04/11/2026 11:00</div>
  <div class="line">Référence 01/2026</div>
  <div class="line">Objet : La Gestion Déléguée du Centre d'Enfouissement</div>
  <div class="line">Acheteur public : RTT / GCSPE - GROUPEMENT DE COMMUNES</div>
  <div class="line">Type d'annonce : Annonce de consultation</div>
  <div class="line">Procédure : Appel d'offres ouvert | Sur offre de prix</div>
  <div class="line">Catégorie principale : Services</div>
  <div class="line">Allotissement : -</div>
  <div class="line">Lieu d'exécution : MAROC, TETOUAN</div>
  <div class="line">Estimation (en Dhs TTC) * : 15 000 000,00 @@@@</div>
  <div class="line">Réservé à la TPE et PME installées au Maroc * : Non</div>
  <div class="line">Domaines d'activité : Services / Transport</div>
  <div class="line">Domaines d'activité :</div>
  <div class="line">Lieu d'ouverture des plis : province Tétouan</div>
  <div class="line">Caution provisoire : 0,00 MAD</div>
  <div class="line">Qualifications : -</div>
  <div class="line">Visites des lieux : 12/08/2026 09:30 , siège du GCTSE</div>
  <a href="index.php?page=entreprise.EntrepriseDemandeTelechargementDce&refConsultation=1031023&orgAcronyme=l1f">Dossier</a>
</body></html>
"""

LISTING_HTML = """
<html><body><table>
  <tr>
    <td>AOO Appel d'offres ouvert Travaux 19/08/2026</td>
    <td>TN4131014 - Travaux de construction</td>
    <td>08/10/2026</td>
    <td><a href="?page=entreprise.EntrepriseDetailConsultation&refConsultation=1031023&orgAcronyme=l1f">Détail</a></td>
  </tr>
  <tr>
    <td>AOO Appel d'offres ouvert Travaux 06/08/2026</td>
    <td>04/2026 - Autre marché</td>
    <td>07/10/2026</td>
    <td><a href="?page=entreprise.EntrepriseDetailConsultation&refConsultation=1032889&orgAcronyme=d4q">Détail</a></td>
  </tr>
</table></body></html>
"""


@pytest.fixture(scope="module")
def detail() -> dict:
    return parse_detail_page(DETAIL_HTML, source_url="http://example/detail")


# --------------------------------------------------------------------------- #
# detail page — one test per confirmed quirk
# --------------------------------------------------------------------------- #

def test_reference_without_colon(detail):
    """'Référence 01/2026' carries no colon separator."""
    assert detail["reference"] == "01/2026"


def test_amount_strips_rendering_artefacts(detail):
    """'15 000 000,00 @@@@' with a footnote asterisk in the label."""
    assert detail["estimation_dhs_ttc"] == 15000000.0


def test_mode_passation_keeps_only_part_before_pipe(detail):
    assert detail["mode_passation"] == "Appel d'offres ouvert"


def test_lone_dash_maps_to_none_not_false(detail):
    assert detail["allotissement"] is None
    assert detail["qualifications"] is None


def test_oui_non_still_parses_to_bool(detail):
    assert detail["reserve_tpe_pme"] is False


def test_duplicate_domaines_keeps_first_non_empty(detail):
    assert detail["domaines_activite"] == "Services / Transport"


def test_date_with_time_becomes_iso_date(detail):
    assert detail["date_limite_remise_plis"] == "2026-11-04"


def test_identification_form_marks_not_downloadable(detail):
    """We never fill EntrepriseDemandeTelechargementDce — we flag and move on."""
    assert detail["is_publicly_downloadable"] is False
    assert "EntrepriseDemandeTelechargementDce" in detail["dossier_consultation_url"]


def test_neighbouring_lieu_labels_do_not_collide(detail):
    assert detail["lieu_execution"] == "MAROC, TETOUAN"
    assert detail["lieu_ouverture_plis"] == "province Tétouan"


def test_date_mise_ligne_absent_from_detail_page(detail):
    """Confirmed portal behaviour — it only exists in the listing."""
    assert detail["date_mise_ligne"] is None


def test_unmatched_labels_go_to_extras(detail):
    assert "Visites des lieux" in detail["extras"]


def test_schema_is_stable_even_on_empty_page():
    record = parse_detail_page("<html><body></body></html>")
    for field in ("reference", "objet", "estimation_dhs_ttc", "date_mise_ligne"):
        assert field in record and record[field] is None


# --------------------------------------------------------------------------- #
# listing page
# --------------------------------------------------------------------------- #

def test_listing_rows_carry_publication_and_deadline():
    rows = parse_listing_rows(LISTING_HTML)
    assert len(rows) == 2
    first = rows[0]
    assert first["refConsultation"] == "1031023"
    assert first["orgAcronyme"] == "l1f"
    assert first["date_mise_ligne"] == "2026-08-19"      # "Publié le"
    assert first["date_limite_remise_plis"] == "2026-10-08"
    assert first["reference"] == "TN4131014"


def test_listing_deduplicates_repeated_links():
    doubled = LISTING_HTML.replace("</table>", """
      <tr><td>x</td><td><a href="?page=entreprise.EntrepriseDetailConsultation&refConsultation=1031023&orgAcronyme=l1f">dup</a></td></tr>
    </table>""")
    assert len(parse_listing_rows(doubled)) == 2


# --------------------------------------------------------------------------- #
# normalisers
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("raw,expected", [
    ("15 000 000,00 @@@@", 15000000.0),
    ("133 075 758,00", 133075758.0),
    ("0,00 MAD", 0.0),
    ("758 640,00 DH TTC", 758640.0),
    ("15.000.000", 15000000.0),
    ("-", None),
    ("", None),
    (None, None),
])
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("04/11/2026 11:00", "2026-11-04"),
    ("12/08/2026", "2026-08-12"),
    ("32/01/2026", None),
    ("pas de date", None),
    (None, None),
])
def test_parse_date_iso(raw, expected):
    assert parse_date_iso(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Oui", True), ("non", False), ("-", None), ("", None), (None, None),
])
def test_parse_oui_non(raw, expected):
    assert parse_oui_non(raw) is expected


def test_normalize_reference_tolerates_variable_formats():
    assert normalize_reference(" aon31/2024/so2300up ") == "AON31/2024/SO2300UP"
    assert normalize_reference("22 / 2026 / DAAC") == "22/2026/DAAC"
    assert normalize_reference(None) is None


# --------------------------------------------------------------------------- #
# real saved pages (skipped when absent)
# --------------------------------------------------------------------------- #

REAL_DETAIL = REPO / "data" / "raw" / "debug_detail.html"
REAL_LISTING = REPO / "data" / "raw" / "debug_allcons.html"


@pytest.mark.skipif(not REAL_DETAIL.exists(), reason="saved detail page absent")
def test_real_detail_page_parses():
    record = parse_detail_page(REAL_DETAIL.read_text(encoding="utf-8", errors="replace"))
    assert record["reference"]
    assert record["objet"]
    assert record["acheteur_public"]
    assert record["categorie_principale"] in ("Travaux", "Fournitures", "Services")
    assert record["date_mise_ligne"] is None


@pytest.mark.skipif(not REAL_LISTING.exists(), reason="saved listing page absent")
def test_real_listing_page_parses():
    rows = parse_listing_rows(REAL_LISTING.read_text(encoding="utf-8", errors="replace"))
    assert rows, "no rows parsed from the saved listing"
    assert all(r["refConsultation"].isdigit() for r in rows)
    dated = [r for r in rows if r["date_mise_ligne"]]
    assert dated, "no publication date parsed from the listing"
