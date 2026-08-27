"""
Per-field extractors (Issue 7).

Each function takes one lot's text (extraction.lots.LotSegment.text) and
returns the best value it can find, or None. None means "not found", never
"assumed absent" — a downstream consumer must not treat a missing value as a
confirmed negative (see extract_montants for why this matters for HT/TTC).

Reuses the tolerant patterns of extraction/patterns.py and the parsing
already validated in ocr/matching.py (parse_amount_string, date_variants) —
rewriting either would reintroduce the three Issue 6 measurement bugs
(lost decimal separator, newline-swallowing regex, unrecognised textual
dates).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field

from ocr.matching import parse_amount_string
from extraction.company_name import clean_company_candidate
from extraction.patterns import (
    AMOUNT_HT_RE,
    AMOUNT_RE,
    AMOUNT_TTC_RE,
    DATE_NUMERIC_STRICT_RE,
    DATE_NUMERIC_TOLERANT_RE,
    DATE_TEXTUAL_RE,
    GROUPEMENT_RE,
    HEADER_HT_RE,
    HEADER_TTC_RE,
    JUSTIFICATION_PRIX_RE,
    LABEL_CONCURRENT_RETENU,
    LABEL_DATE_ACHEVEMENT,
    LABEL_DATE_OUVERTURE,
    LABEL_ECARTES,
    LABEL_LISTE_CONCURRENTS,
    LABEL_REFERENCE,
    NEANT_RE,
    NEW_SECTION_RE,
    OFFRE_EXCESSIVE_RE,
    PRESENTE_PAR_RE,
    REFERENCE_VALUE,
    SOCIETE_NAME_RE,
    _CAPTION_WORDS,
)

MONTHS_FR = ("janvier", "fevrier", "mars", "avril", "mai", "juin",
             "juillet", "aout", "septembre", "octobre", "novembre", "decembre")


# OCR digit confusions (methodology.md §2.9): O/o/Q -> 0, l/I -> 1, S -> 5.
# Shared between dates and amounts, since both are parsed from DIGIT-class
# regex captures that can contain these substituted letters. Applied right
# before handing text to ocr/matching.parse_amount_string, which expects
# real digits and silently returns None otherwise — confirmed on doc
# 48f26629ef23...: "949 O92,OO DHS TTC" matched AMOUNT_TTC_RE correctly, but
# parse_amount_string("949 O92,OO") returned None because it never went
# through this translation.
_OCR_DIGIT_TRANSLATION = str.maketrans("OoQlIS", "001155")


def _parse_ocr_amount(raw: str) -> float | None:
    return parse_amount_string(raw.translate(_OCR_DIGIT_TRANSLATION))


def _month_index(name: str) -> int | None:
    name = name.lower().replace("é", "e").replace("û", "u")
    for i, m in enumerate(MONTHS_FR):
        if m == name:
            return i + 1
    return None


def _first_labelled(label_re: re.Pattern, value_re: re.Pattern, text: str,
                    window: int = 80) -> str | None:
    """Find `label_re`, then look for `value_re` in the text right after it.

    A labelled match is always preferred over a loose one elsewhere in the
    document — the label is what makes the value trustworthy.
    """
    m = label_re.search(text)
    if not m:
        return None
    tail = text[m.end():m.end() + window]
    v = value_re.search(tail)
    return v.group(0).strip() if v else None


# --------------------------------------------------------------------------- #
# reference
# --------------------------------------------------------------------------- #

def extract_reference(text: str) -> str | None:
    """The market reference as printed in the document.

    Not a join key (data_dictionary.md §1 — reference is ambiguous across
    buyers, refConsultation is), only a display attribute recorded for
    traceability and cross-checking against the manifest.
    """
    return _first_labelled(LABEL_REFERENCE, REFERENCE_VALUE, text, window=40)


# --------------------------------------------------------------------------- #
# dates
# --------------------------------------------------------------------------- #

def _parse_date_match(match: re.Match, textual: bool) -> str | None:
    try:
        if textual:
            day, month_name, year = match.group(1), match.group(2), match.group(3)
            day = day.translate(_OCR_DIGIT_TRANSLATION)
            month = _month_index(month_name)
            if month is None:
                return None
        else:
            day, month, year = match.group(1), match.group(2), match.group(3)
            day = day.translate(_OCR_DIGIT_TRANSLATION)
            month = month.translate(_OCR_DIGIT_TRANSLATION)
        day_i, month_i, year_i = int(day), int(month), int(year)
        if not (1 <= day_i <= 31 and 1 <= month_i <= 12 and 1900 <= year_i <= 2100):
            return None
        return f"{day_i:02d}/{month_i:02d}/{year_i}"
    except (ValueError, TypeError):
        return None


def _find_date_near_label(label_re: re.Pattern, text: str,
                          window: int = 100) -> str | None:
    m = label_re.search(text)
    if not m:
        return None
    tail = text[m.end():m.end() + window]
    textual = DATE_TEXTUAL_RE.search(tail)
    if textual:
        parsed = _parse_date_match(textual, textual=True)
        if parsed:
            return parsed
    # Both passes run, and whichever match starts EARLIEST (closest to the
    # label) wins, strict breaking ties. Picking "strict if it finds
    # anything, tolerant only otherwise" (the earlier version) was wrong:
    # confirmed on doc f2b79a276ec5..., tail " le 24/11//2022.\n\nFait à
    # Casablanca, le : 26/09/2022" — the real date "24/11//2022" (a doubled
    # "/") only matches the tolerant pattern, but the strict pattern still
    # finds *a* match further down ("26/09/2022", an unrelated signature
    # date) and that was enough to skip the tolerant pass entirely, so the
    # wrong, more distant date won by default. Strict still exists so a
    # clean date is never put at risk by the tolerant class (see
    # DATE_SEP_STRICT/DATE_SEP_TOLERANT above) — it just no longer gets
    # priority over a closer, correct, tolerant-only match.
    strict = DATE_NUMERIC_STRICT_RE.search(tail)
    tolerant = DATE_NUMERIC_TOLERANT_RE.search(tail)
    if strict and tolerant:
        numeric = strict if strict.start() <= tolerant.start() else tolerant
    else:
        numeric = strict or tolerant
    return _parse_date_match(numeric, textual=False) if numeric else None


def extract_dates(text: str) -> dict[str, str | None]:
    return {
        "date_ouverture_plis": _find_date_near_label(LABEL_DATE_OUVERTURE, text),
        "date_achevement_commission": _find_date_near_label(LABEL_DATE_ACHEVEMENT, text),
    }


# --------------------------------------------------------------------------- #
# concurrent_retenu — keeps a consortium whole, never splits it
# --------------------------------------------------------------------------- #

def _fold_accents(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


def _is_caption_line(line: str) -> bool:
    """True when `line` only restates the label / a table caption instead of
    carrying a value — "Concurrent retenu Montant d'acte d'engagement" is a
    re-stated column header, not a winner's name (confirmed on doc
    03d5069b..., where the real value sits two lines further down)."""
    # Apostrophes split into separate tokens ("l'acte" -> "l", "acte")
    # rather than staying attached — "l'acte" as one token never matches
    # _CAPTION_WORDS even though both "l" and "acte" are in it, which let
    # captions like "Montant de l'acte d'engagement" slip through unfiltered.
    # Accents are folded before comparison: _CAPTION_WORDS is written
    # unaccented, but the source text is not ("financières") — confirmed on
    # doc 551178cf065f..., where "Offres financières en DH TTC" survived the
    # filter only because "financières" (accented) never matched the
    # unaccented "financieres" entry.
    normalized = _fold_accents(line.lower()).replace("’", " ").replace("'", " ")
    words = re.findall(r"[a-z]+", normalized)
    if not words:
        return False
    return all(w in _CAPTION_WORDS for w in words)


def _collect_value_block(text: str, start: int, window: int = 400,
                         max_lines: int = 6) -> str:
    """Lines following `start`, skipping blank lines and caption lines,
    stopping at the first blank line once real content has begun, or at the
    first line that starts a different section (the next label, "Fait à...",
    a signature) or contains a real amount.

    The label and its value are not always on the same line — confirmed on
    both doc 9140a66a... ("Concurrent retenu :" alone on its line, the actual
    sentence one line below) and doc 03d5069b... (label, then a re-stated
    header line, then the value two lines below). And the value line itself
    does not always end where the value does — confirmed on 9 of 16
    ground-truth documents (e.g. ea9b61ee0d2b...: "BET SG CONCEPT
    708 000.00", 4eac1e85166e...: "ENTREPRISE OUENZAR 1 455 960,00"), where
    the winner's name and its amount sit on the very same line with nothing
    but a space between them, so a per-line stop can't separate them —
    only stopping mid-line at the amount can.
    """
    chunk = text[start:start + window]
    collected: list[str] = []
    for raw_line in chunk.splitlines():
        line = raw_line.strip(" :\t‎‏")
        if not line:
            if collected:
                break
            continue
        if _is_caption_line(line):
            continue
        if collected and NEW_SECTION_RE.search(line):
            break
        # A bare row index / ranking number ("1", "01") is neither a caption
        # nor the value — confirmed on doc 672bb02cd03c...: a "1" line sits
        # between the table header and "Société MAIRAV", and without this
        # check the (now-removed) naive amount-stop below treated "1" itself
        # as a plausible amount and stopped collection before ever reaching
        # the real name.
        if _PURE_INDEX_RE.match(line):
            continue
        # Only a *plausible* amount (>= MIN_PLAUSIBLE_AMOUNT, same floor as
        # the montant extractors) marks where the value ends — confirmed on
        # doc 2a36f6540d91...: "01 HYDROLIQUE ET ELECTRIQUE - | 179.400,00
        # MAD | 1 5 |" has the row index "01" as the very first amount-shaped
        # token; splitting there instead of at the real 179 400,00 would
        # have dropped the company name entirely.
        plausible = None
        for candidate in AMOUNT_RE.finditer(line):
            if not _has_real_digit(candidate.group(0)):
                continue
            value = _parse_ocr_amount(candidate.group(0))
            if value is not None and value >= MIN_PLAUSIBLE_AMOUNT:
                plausible = candidate
                break
        if plausible:
            prefix = line[:plausible.start()].strip()
            # Drop a leading row index that precedes the real name on the
            # same line ("01 HYDROLIQUE ET ELECTRIQUE" -> "HYDROLIQUE ET
            # ELECTRIQUE"), also confirmed on doc 2a36f6540d91....
            prefix = re.sub(r"^\d{1,2}\s+", "", prefix)
            if prefix:
                collected.append(prefix)
            break
        collected.append(line)
        if len(collected) >= max_lines:
            break
    return " ".join(collected)


_PURE_INDEX_RE = re.compile(r"^[0-9OoQlIS.,\s]{1,6}$")


def extract_concurrent_retenu_brut(text: str) -> str | None:
    """The raw text block following the "concurrent retenu" label, exactly as
    `_collect_value_block()` returns it — column headers, justification
    sentence, address and all.

    Kept as its own function (and persisted as `Award.concurrent_retenu_brut`)
    because `extract_concurrent_retenu()` now cleans its output: the
    traceability the project relies on — being able to show what the document
    actually said — must not be lost by the cleaning step. `extract_statut()`
    reads THIS value, not the cleaned one (see extraction/company_name.py)."""
    m = LABEL_CONCURRENT_RETENU.search(text)
    if not m:
        return None
    candidate = _collect_value_block(text, m.end())
    if not candidate or NEANT_RE.match(candidate):
        return None
    candidate = re.sub(r"\s+", " ", candidate)

    # A groupement must stay whole — never truncate to the first company
    # named inside it (data_dictionary.md §3.1).
    if GROUPEMENT_RE.search(candidate):
        return candidate or None

    # The name is sometimes embedded in a justification sentence rather than
    # standing alone — confirmed on doc 9140a66a...: "L'offre economiquement
    # la plus avantageuse est l'offre presentee par la societe TECTRA, pour
    # un montant de...". Only strip "societe" when that specific prose
    # pattern is actually present ("presentee/presente par"): a plain table
    # listing like "Societe MAIRAV" or "La Societe BENFORD SARL AU" is the
    # printed value verbatim, "Societe" included — confirmed on 4 ground-
    # truth documents (672bb02cd03c, 3a6a7d163182, 5ed398a32d63,
    # 48f26629ef23) where stripping it unconditionally dropped a word the
    # ground truth keeps.
    if PRESENTE_PAR_RE.search(candidate):
        societe = SOCIETE_NAME_RE.search(candidate)
        if societe:
            return societe.group(1).strip() or None
    return candidate or None


def extract_concurrent_retenu(text: str) -> str | None:
    """The winner's name alone, or the full consortium wording if it is a
    groupement (data_dictionary.md §3.1 — never split into separate
    companies).

    Isolates the name inside the raw block via
    extraction/company_name.py::clean_company_candidate() — see that module
    for the measured reason (107/200 Company affected by adjacent-line
    capture before this step existed).

    EXCEPTION groupement : la formulation consortium est renvoyee ENTIERE,
    sans nettoyage. Nettoyer ici couperait sur "ENTRE" ("GROUPEMENT entre la
    Societe X et la Societe Y") et ferait perdre le mot GROUPEMENT lui-meme,
    dont database/crud/companies.py::resolve_companies() a besoin pour
    declencher split_groupement(). Chaque membre est nettoye
    individuellement apres decoupage, la ou c'est correct de le faire."""
    brut = extract_concurrent_retenu_brut(text)
    if brut and GROUPEMENT_RE.search(brut):
        return brut
    return clean_company_candidate(brut)


# --------------------------------------------------------------------------- #
# montants — montant_ht and montant_ttc extracted independently
# --------------------------------------------------------------------------- #

@dataclass
class AmountResult:
    montant_ht: float | None = None
    montant_ttc: float | None = None
    montant_base_affichee: str | None = None  # "HT" | "TTC" | None


def _has_real_digit(s: str) -> bool:
    """At least one true 0-9 numeral, not purely OCR-confusable letters.

    Every confirmed corrupted-amount case in this corpus (methodology.md
    §2.9: "6163200", "13107 /2026", "3 322 992,OO") still has genuine digits
    mixed in with the substituted letters — none is a *pure* letter run.
    Without this check, DIGIT's tolerance for O/o/Q/l/I/S turns plain prose
    into a false amount: confirmed on doc 3a6a7d16..., where AMOUNT_RE
    matched "So" (from "Societe") as a bogus 2-digit number right after a
    table header, and even "s" alone (from "Dhs") as a 1-digit "5" before the
    the (?<!\\w) boundary guard was added. Requiring a real digit keeps the
    OCR-tolerance intact for the cases it exists for while refusing pure
    letter noise.
    """
    return any(ch.isdigit() for ch in s)


def _last_match(pattern: re.Pattern, text: str) -> re.Match | None:
    matches = [m for m in pattern.finditer(text)
               if _has_real_digit(m.group(1))
               and (v := _parse_ocr_amount(m.group(1))) is not None
               and v >= MIN_PLAUSIBLE_AMOUNT]
    return matches[-1] if matches else None


MIN_PLAUSIBLE_AMOUNT = 1000.0


def _first_amount_in(text: str, start: int, window: int) -> re.Match | None:
    """First amount-shaped match in the window that is actually plausible
    as a contract amount, not a row index or a delay-in-days figure.

    Confirmed on doc 2a36f6540d91...: a table row prefixed "01 HYDROLIQUE ET
    ELECTRIQUE - | 179.400,00 MAD | 1 5 |" made the naive first match "01"
    (the row number), not the real 179 400,00. Every montant in this corpus
    is a public-works contract value — well above a row index or a days
    count — so a floor at 1000 filters the false hit without needing to
    understand the table structure.
    """
    tail = text[start:start + window]
    for candidate in AMOUNT_RE.finditer(tail):
        raw = candidate.group(0)
        if not _has_real_digit(raw):
            continue
        value = _parse_ocr_amount(raw)
        if value is not None and value >= MIN_PLAUSIBLE_AMOUNT:
            return candidate
    return None


def _amount_near_winner(text: str, window: int = 300) -> re.Match | None:
    """The winner's own declared amount, scoped to the "Concurrent retenu"
    section rather than the whole document.

    A document with several bidders prints one amount per bidder in a table
    *before* naming the winner — confirmed on doc ea9b61ee0d2b..., where a
    plain "first amount after the last TTC header" fallback picked up "56"
    out of an unrelated bidder row ("BET 56 CONCEPT") instead of the winner's
    708 000.00. The "Concurrent retenu" section itself restates the winning
    company with its amount right next to it (also confirmed on doc
    3a6a7d16...), so scoping the search there avoids the other rows entirely.
    """
    m = LABEL_CONCURRENT_RETENU.search(text)
    if not m:
        return None
    return _first_amount_in(text, m.end(), window)


def _amount_after_header(header_re: re.Pattern, text: str,
                         window: int = 250) -> re.Match | None:
    """Last-resort fallback for the dominant table layout: a header names
    the base ("... en Dhs TTC") and the amount sits on the next line, next
    to the bidder's name, not immediately before the marker — confirmed on
    doc 3a6a7d16..., where AMOUNT_TTC_RE never matches anywhere in the text.

    Only reached when _amount_near_winner also fails (no "Concurrent
    retenu" section, or nothing found there) — it has no way to tell one
    bidder's row from another's, so it is a weaker signal.

    Uses the LAST header occurrence: documents commonly print the same
    table twice ("avant verification" / "apres verification"), and the
    second, post-audit figure is the authoritative one.
    """
    matches = list(header_re.finditer(text))
    if not matches:
        return None
    return _first_amount_in(text, matches[-1].end(), window)


def extract_montants(text: str) -> AmountResult:
    """montant_ht and montant_ttc, extracted independently.

    data_dictionary.md §3.6, applied literally: NEVER derive one from the
    other via an assumed VAT rate. A document giving only one base leaves
    the other field None — that is the correct, honest result, not a bug to
    "fix" with arithmetic.
    """
    # LAST match preferred: same "apres verification is authoritative"
    # reasoning as _amount_after_header, and it costs nothing when there is
    # only one occurrence (the common case).
    ttc_match = _last_match(AMOUNT_TTC_RE, text)
    ht_match = _last_match(AMOUNT_HT_RE, text)

    has_ttc_marker = ttc_match is not None or HEADER_TTC_RE.search(text) is not None
    has_ht_marker = ht_match is not None or HEADER_HT_RE.search(text) is not None

    # _amount_near_winner can't itself tell TTC from HT — it just finds the
    # number next to the winner's name. Only trust it when the document's
    # base is unambiguous (exactly one marker kind present); when both
    # appear, assigning the same nearby number to both fields would be a
    # guess dressed up as an extraction, so fall through to the weaker
    # header-scoped search instead, which at least stays anchored to its
    # own marker.
    result = AmountResult()
    if ttc_match:
        result.montant_ttc = _parse_ocr_amount(ttc_match.group(1))
    elif has_ttc_marker:
        fallback = ((_amount_near_winner(text) if not has_ht_marker else None)
                    or _amount_after_header(HEADER_TTC_RE, text))
        if fallback:
            result.montant_ttc = _parse_ocr_amount(fallback.group(0))

    if ht_match:
        result.montant_ht = _parse_ocr_amount(ht_match.group(1))
    elif has_ht_marker:
        fallback = ((_amount_near_winner(text) if not has_ttc_marker else None)
                    or _amount_after_header(HEADER_HT_RE, text))
        if fallback:
            result.montant_ht = _parse_ocr_amount(fallback.group(0))

    if result.montant_ttc is not None and result.montant_ht is None:
        result.montant_base_affichee = "TTC"
    elif result.montant_ht is not None and result.montant_ttc is None:
        result.montant_base_affichee = "HT"
    elif result.montant_ttc is not None and result.montant_ht is not None:
        # Both printed: base_affichee records whichever the document leads
        # with. Compares the immediate-adjacency matches when both came from
        # that path; when either came from the header fallback instead,
        # there is no single comparable position worth defending, so TTC
        # wins by convention (it is the far more common base in this corpus
        # — 166/388 documents vs. 39/388 for HT, methodology.md §2.9).
        if ttc_match and ht_match:
            result.montant_base_affichee = "TTC" if ttc_match.start() < ht_match.start() else "HT"
        else:
            result.montant_base_affichee = "TTC"

    return result


# --------------------------------------------------------------------------- #
# concurrents — only meaningful on the richer "extrait de PV" documents
# --------------------------------------------------------------------------- #

@dataclass
class ConcurrentsResult:
    liste_concurrents: list[str] = dc_field(default_factory=list)
    concurrents_ecartes: list[str] = dc_field(default_factory=list)

    @property
    def number_of_bidders(self) -> int:
        return len(self.liste_concurrents)


def _bulleted_names(text: str, label_re: re.Pattern, window: int = 600) -> list[str]:
    m = label_re.search(text)
    if not m:
        return []
    block = text[m.end():m.end() + window]
    # Bullets survive text_cleaning.py as "•"; a bare line starting with a
    # company-shaped token also counts, since not every list is bulleted.
    lines = [re.sub(r"^[•\-*o]\s*", "", ln).strip() for ln in block.splitlines()]
    names = []
    for ln in lines:
        if not ln or len(ln) < 3:
            if names:  # blank line after we've started collecting -> list ended
                break
            continue
        if NEANT_RE.match(ln):
            break
        if re.match(r"^(liste|concurrent|montant|date|lieu)\b", ln, re.IGNORECASE):
            break  # next section header
        names.append(ln)
        if len(names) >= 30:  # sanity cap
            break
    return names


def extract_concurrents(text: str) -> ConcurrentsResult:
    """Not validated against ground truth (no annotated field for it) —
    extracted anyway per the Issue 7 plan, since it feeds number_of_bidders,
    the best-established red flag of ideas.md §2.6. Report this limitation
    explicitly wherever this field's accuracy is discussed.
    """
    return ConcurrentsResult(
        liste_concurrents=_bulleted_names(text, LABEL_LISTE_CONCURRENTS),
        concurrents_ecartes=_bulleted_names(text, LABEL_ECARTES),
    )


# --------------------------------------------------------------------------- #
# statut — per-lot, never per-document (extraction.lots handles the split)
# --------------------------------------------------------------------------- #

ATTRIBUE, INFRUCTUEUX, OFFRE_EXCESSIVE = "ATTRIBUE", "INFRUCTUEUX", "OFFRE_EXCESSIVE"


def extract_statut(lot_text: str, declared_infructueux: bool,
                   concurrent_retenu: str | None) -> str:
    """Infer this lot's statut from the indices documented in
    ocr/matching.py's infer_statut_indices() — not a fresh set of rules.

    `declared_infructueux` comes from extraction.lots' authoritative "liste
    des lots infructueux" parsing, which is more reliable than any in-text
    search on this segment alone (that is precisely the trap document
    349e44bf: a keyword search on the wrong scope would misclassify it).
    """
    if declared_infructueux:
        return INFRUCTUEUX

    if OFFRE_EXCESSIVE_RE.search(lot_text) and not JUSTIFICATION_PRIX_RE.search(lot_text):
        return OFFRE_EXCESSIVE

    if concurrent_retenu:
        return ATTRIBUE

    # No named winner: fall back to an in-segment "infructueux" mention,
    # guarded against the justification-rubric false friend the same way.
    if re.search(r"infructueu", lot_text, re.IGNORECASE):
        return INFRUCTUEUX

    return ATTRIBUE if concurrent_retenu else INFRUCTUEUX
