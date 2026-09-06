"""
Parse PMMP consultation listing rows and detail pages into structured dicts.

Fields follow docs/data_dictionary.md §2.

Detail-page structure (confirmed by reconnaissance, and the reason the earlier
table-based parser produced empty records): a consultation detail page contains
**no** label/value `<table><tr>` rows at all — every field lives in a
`<div class="line">` block holding "Label : Value" text.

Real quirks handled below, all observed on live pages:
  * "Référence 01/2026" carries no colon separator.
  * "Estimation (en Dhs TTC) * : 15 000 000,00 @@@@" — trailing marker junk.
  * "Procédure : Appel d'offres ouvert | Sur offre de prix" — mode_passation is
    only the part before the pipe.
  * A lone "-" means *absent*, and must map to None (not False).
  * "Domaines d'activité" appears twice, the second occurrence empty.
  * Dates may carry a time ("04/11/2026 11:00").
  * date_mise_ligne is NOT on the detail page — it only exists in the listing's
    "Publié le" column, so detail-only records legitimately leave it None.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

BASE_URL = "https://www.marchespublics.gov.ma/index.php"
SITE_ROOT = "https://www.marchespublics.gov.ma/"

# Ordered longest-first within each field; matching is prefix-based on the
# normalized label, so neighbouring labels ("Lieu d'exécution" vs
# "Lieu d'ouverture des plis") cannot collide.
FIELD_ALIASES: dict[str, list[str]] = {
    "date_limite_remise_plis": [
        "Date et heure limite de remise des plis",
        "Date limite de remise des plis",
        "Date limite",
    ],
    "reference":            ["Référence de la consultation", "Référence"],
    "objet":                ["Objet de la consultation", "Objet"],
    "acheteur_public":      ["Acheteur public", "Maître d'ouvrage"],
    "type_annonce":         ["Type d'annonce"],
    "mode_passation":       ["Procédure", "Mode de passation", "Type de procédure"],
    "categorie_principale": ["Catégorie principale", "Catégorie"],
    "lieu_execution":       ["Lieu d'exécution"],
    "estimation_dhs_ttc":   ["Estimation (en Dhs TTC)", "Estimation", "Montant estimatif"],
    "caution_provisoire":   ["Caution provisoire", "Cautionnement provisoire"],
    "qualifications":       ["Qualifications"],
    "domaines_activite":    ["Domaines d'activité", "Domaine d'activité"],
    "allotissement":        ["Allotissement"],
    "reserve_tpe_pme":      ["Réservé à la TPE et PME", "Réservé"],
    "lieu_ouverture_plis":  ["Lieu d'ouverture des plis"],
}

# Stable output schema — every record carries every key, so downstream PySpark
# never has to cope with a shifting set of columns. date_mise_ligne is listed
# even though no detail-page label yields it: it stays None here and is filled
# from the listing's "Publié le" column when that pass supplies it.
DETAIL_FIELDS = list(FIELD_ALIASES) + ["dossier_consultation_url", "date_mise_ligne"]

AMOUNT_FIELDS = {"estimation_dhs_ttc", "caution_provisoire"}
BOOL_FIELDS = {"allotissement", "reserve_tpe_pme"}
DATE_FIELDS = {"date_limite_remise_plis"}

_MISSING = {"", "-", "--", "n/a", "néant", "neant"}
_DATE_RE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")


# --------------------------------------------------------------------------- #
# value normalisation
# --------------------------------------------------------------------------- #

def normalize_label(text: str) -> str:
    """Collapse whitespace and drop the footnote asterisk some labels carry."""
    return re.sub(r"\s+", " ", text or "").strip().rstrip("*").strip()


def clean_value(text: str | None) -> str | None:
    """Strip decoration and map the portal's 'absent' markers to None."""
    if text is None:
        return None
    value = re.sub(r"\s+", " ", text).replace(" ", " ").strip()
    value = value.replace("@@@@", "").strip()   # rendering artefact on amounts
    value = value.strip("*").strip()
    return None if value.lower() in _MISSING else value


def parse_amount(text: str | None) -> float | None:
    """Parse a Moroccan-formatted amount ('15 000 000,00 @@@@') into a float."""
    value = clean_value(text)
    if value is None:
        return None
    digits = re.sub(r"[^\d,.\-]", "", value)
    if not digits:
        return None
    if "," in digits and "." in digits:
        # whichever separator comes last is the decimal one
        if digits.rfind(",") > digits.rfind("."):
            digits = digits.replace(".", "").replace(",", ".")
        else:
            digits = digits.replace(",", "")
    elif "," in digits:
        digits = digits.replace(",", ".")
    if digits.count(".") > 1:          # 15.000.000 — dots used as thousands
        digits = digits.replace(".", "")
    try:
        return float(digits)
    except ValueError:
        return None


def parse_date_iso(text: str | None) -> str | None:
    """First DD/MM/YYYY found -> ISO date string. Any trailing time is dropped."""
    if not text:
        return None
    m = _DATE_RE.search(text)
    if not m:
        return None
    try:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date().isoformat()
    except ValueError:
        return None


def parse_oui_non(text: str | None) -> bool | None:
    """Oui/Non -> bool. Anything else (notably '-') stays None, never False."""
    value = clean_value(text)
    if value is None:
        return None
    low = value.lower()
    if low.startswith(("oui", "yes")):
        return True
    if low.startswith(("non", "no")):
        return False
    return None


def match_field(label: str) -> str | None:
    normalized = normalize_label(label).lower()
    for field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if normalized.startswith(alias.lower()):
                return field
    return None


def _absolute(href: str) -> str:
    if href.startswith("http"):
        return href
    if href.startswith("?"):
        return f"{BASE_URL}{href}"
    return f"{SITE_ROOT}{href.lstrip('/')}"


# --------------------------------------------------------------------------- #
# detail page
# --------------------------------------------------------------------------- #

def _split_label_value(block: str) -> tuple[str, str] | None:
    """Split a 'Label : Value' block on its first colon.

    'Référence 01/2026' has no colon at all, so it is special-cased: the label
    is the leading word and the rest is the value.
    """
    label, sep, value = block.partition(":")
    if sep:
        return label, value
    m = re.match(r"^(Référence|Reference)\s+(.+)$", block.strip())
    if m:
        return m.group(1), m.group(2)
    return None


def parse_detail_page(html: str, source_url: str | None = None) -> dict[str, Any]:
    """Parse a consultation detail page into a flat dict with a stable schema."""
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, Any] = {field: None for field in DETAIL_FIELDS}
    result["source_url"] = source_url
    result["is_publicly_downloadable"] = None
    extras: dict[str, str] = {}

    for div in soup.find_all("div", class_="line"):
        block = re.sub(r"\s+", " ", div.get_text(" ", strip=True)).strip()
        if not block:
            continue
        split = _split_label_value(block)
        if split is None:
            continue
        raw_label, raw_value = split
        field = match_field(raw_label)
        value = clean_value(raw_value)

        if field is None:
            label = normalize_label(raw_label)
            if value is not None and label and label not in extras:
                extras[label] = value
            continue

        # First non-empty wins: "Domaines d'activité" is emitted twice, the
        # second time empty, and the same guard protects every other field.
        if result.get(field) is not None or value is None:
            continue

        if field in AMOUNT_FIELDS:
            result[field] = parse_amount(value)
        elif field in BOOL_FIELDS:
            result[field] = parse_oui_non(value)
        elif field in DATE_FIELDS:
            result[field] = parse_date_iso(value)
        elif field == "mode_passation":
            result[field] = value.split("|")[0].strip() or None
        else:
            result[field] = value

    _extract_dossier_link(soup, result)
    result["extras"] = extras
    return result


def _extract_dossier_link(soup: BeautifulSoup, result: dict[str, Any]) -> None:
    """Locate the 'dossier de consultation' link and decide downloadability.

    A link to EntrepriseDemandeTelechargementDce means the file is gated behind
    the identification form. We never fill that form, so the consultation is
    flagged and collection continues.
    """
    gated: str | None = None
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "dce" not in href.lower():
            continue
        if "demandetelechargementdce" in href.lower():
            gated = gated or _absolute(href)
            continue
        result["dossier_consultation_url"] = _absolute(href)
        result["is_publicly_downloadable"] = True
        return
    if gated is not None:
        result["dossier_consultation_url"] = gated
        result["is_publicly_downloadable"] = False


# --------------------------------------------------------------------------- #
# listing page
# --------------------------------------------------------------------------- #

def parse_listing_rows(listing_html: str) -> list[dict[str, Any]]:
    """One dict per result row of a consultations listing.

    The listing is the only place carrying "Publié le" (date_mise_ligne); the
    row's last date is the "Date limite de remise des plis", which is also the
    server's sort key.
    """
    soup = BeautifulSoup(listing_html, "html.parser")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "EntrepriseDetailConsultation" not in href:
            continue
        ref_m = re.search(r"refConsultation=(\d+)", href)
        org_m = re.search(r"orgAcronyme=([^&\"']+)", href)
        if not (ref_m and org_m):
            continue
        key = (ref_m.group(1), org_m.group(1))
        if key in seen:            # the page renders duplicate links per row
            continue

        tr = a.find_parent("tr")
        if tr is None:
            continue
        seen.add(key)

        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        joined = " | ".join(cells)
        dates = _DATE_RE.findall(joined)

        def _iso(idx: int) -> str | None:
            if not dates or idx >= len(dates) or idx < -len(dates):
                return None
            d, m, y = dates[idx]
            return parse_date_iso(f"{d}/{m}/{y}")

        rows.append({
            "refConsultation": key[0],
            "orgAcronyme": key[1],
            "detail_url": _absolute(href),
            "reference": _reference_from_cells(cells),
            "date_mise_ligne": _iso(0) if len(dates) >= 2 else None,
            "date_limite_remise_plis": _iso(-1) if len(dates) >= 2 else None,
        })
    return rows


def _reference_from_cells(cells: list[str]) -> str | None:
    """Reference is rendered as '<ref> - <objet>'; formats vary by buyer."""
    for cell in cells:
        m = re.match(r"^\s*(\S+)\s+-\s", cell)
        if m and not _DATE_RE.match(m.group(1)):
            return m.group(1)
    return None


def normalize_reference(reference: str | None) -> str | None:
    """Loose key for textual reference matching across sources."""
    if not reference:
        return None
    value = re.sub(r"\s+", "", reference).upper().strip("-/.")
    return value or None
