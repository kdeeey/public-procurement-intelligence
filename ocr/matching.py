"""
Shared comparison logic for evaluating extracted values against ground truth.

Used by two evaluators asking *different questions with the same rules*:

  * Issue 6 (`scripts/evaluate_ocr.py`) — "is the expected value findable
    anywhere in the OCR text?" -> `verdict_in_text()`
  * Issue 7 (extraction validation) — "did the extractor produce the correct
    value for this field?" -> `verdict_against_value()`

Only the *source of the candidate* differs (a whole document vs. one extracted
field). How two values are compared is identical, and lives here once.

That single-definition rule is not cosmetic. Three measurement bugs were found
and fixed during Issue 6, each of which silently distorted the reported quality
rate; a second hand-written comparison elsewhere would reintroduce them:

  1. Amounts compared as strings, after a normalisation stripping every
     non-alphanumeric character — which destroys the decimal separator, so
     "721224.86", "72122.486" and "7212248.6" all collapsed to "72122486".
     Three amounts a factor 100 apart compared equal. -> parse to float.
  2. A regex using `\\s` to allow spaces inside numbers also matched newlines,
     merging figures from two different lines into one wrong value.
  3. Dates only generated in numeric form, so a document writing
     "Le mardi 19 décembre 2023" scored as an OCR failure when the
     transcription was perfect. -> textual month names too.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

EXACT, PARTIAL, MISSING = "exact", "approche", "absent"

FUZZY_THRESHOLD = 0.85       # short values: 1-2 wrong characters stay "approche"
TOKEN_RECALL_EXACT = 0.90    # free text: nearly all distinctive words present
TOKEN_RECALL_PARTIAL = 0.60  # free text: the gist is there
AMOUNT_TOLERANCE = 0.01      # DH — same cents, whatever the written form

# --------------------------------------------------------------------------- #
# Field families — the comparison rule is chosen from these, never per-field.
# --------------------------------------------------------------------------- #

SHORT_FIELDS = ("reference_pv", "reference", "concurrent_retenu")
DATE_FIELDS = ("date_ouverture_plis", "date_achevement_commission",
               "date_achevement_travaux_commission")

# BOTH amount fields are listed, deliberately in one tuple and handled by one
# branch: montant_ht and montant_ttc get the exact same parsing, tolerance and
# verdict. Neither is a fallback for the other, and neither is preferred when
# both are present — data_dictionary.md §3.6 forbids deriving one from the
# other, so nothing here may quietly favour one base over the other.
# `montant_offre_retenue` is the legacy key still used by the current
# ground_truth.json; it is accepted so past measurements stay reproducible,
# and carries no special treatment either.
AMOUNT_FIELDS = ("montant_ht", "montant_ttc", "montant_offre_retenue")

FREETEXT_FIELDS = ("acheteur_public", "objet")
ENUM_FIELDS = ("statut",)

STOPWORDS = {
    "de", "du", "des", "la", "le", "les", "l", "d", "et", "en", "au", "aux",
    "pour", "par", "sur", "dans", "a", "the", "of",
    "maitre", "ouvrage", "delegue", "monsieur", "madame", "societe", "ste",
    "sarl", "sa", "president", "directeur", "direction", "service",
    "commune", "province", "prefecture", "royaume", "maroc", "ministere",
}

FRENCH_MONTHS = [
    "janvier", "fevrier", "mars", "avril", "mai", "juin",
    "juillet", "aout", "septembre", "octobre", "novembre", "decembre",
]

# Space and non-breaking space only — deliberately NOT \s, which also matches
# newlines (bug 2 above). Amounts never span lines.
_AMOUNT_TOKEN_RE = re.compile(r"\d[\d.,  ]{1,}\d")


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #

def normalize_for_matching(value) -> str:
    """Strip accents, case and every non-alphanumeric character.

    Applied to BOTH sides of a comparison, so "N°08/2023/CRIDOE" and
    "n 08 - 2023 cridoe" compare equal. Never used for amounts — see
    AMOUNT_FIELDS.
    """
    decomposed = unicodedata.normalize("NFD", str(value))
    ascii_only = decomposed.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_only.lower())


def parse_amount_string(raw) -> float | None:
    """Parse a Moroccan/French written amount into a float.

    "9 269 719,80" / "9.269.719,80" / "9269719.80" all give 9269719.80.
    For an ambiguous single separator the rule is its distance from the end:
    one or two trailing digits means decimal, anything else means thousands
    ("1.234.567" is 1234567, not 1.234567) — Moroccan amounts use two decimals.
    """
    s = str(raw).replace(" ", "").replace(" ", "").strip()
    if not s:
        return None
    has_comma, has_dot = "," in s, "." in s
    if has_comma and has_dot:
        decimal_sep = "," if s.rfind(",") > s.rfind(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        s = s.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif has_comma or has_dot:
        sep = "," if has_comma else "."
        tail = s.rsplit(sep, 1)[-1]
        s = s.replace(sep, "." if (s.count(sep) == 1 and len(tail) in (1, 2)) else "")
    try:
        return float(s)
    except ValueError:
        return None


def extract_amounts(text: str) -> list[float]:
    """Every number-like token of a text, parsed as a float."""
    values = []
    for token in _AMOUNT_TOKEN_RE.findall(text):
        parsed = parse_amount_string(token)
        if parsed is not None:
            values.append(parsed)
    return values


def date_variants(value) -> list[str]:
    """Every written form a date may take, numeric and spelled out."""
    m = re.match(r"\s*(\d{1,2})\D(\d{1,2})\D(\d{4})\s*$", str(value))
    if not m:
        return [str(value)]
    day, month, year = m.group(1).zfill(2), m.group(2).zfill(2), m.group(3)
    variants = [f"{day}/{month}/{year}", f"{day}{month}{year}",
                f"{int(day)}/{int(month)}/{year}"]
    index = int(month) - 1
    if 0 <= index < 12:
        variants += [f"{int(day)} {FRENCH_MONTHS[index]} {year}",
                     f"{day} {FRENCH_MONTHS[index]} {year}"]
    return variants


def distinctive_tokens(value) -> list[str]:
    """Words of a free-text value that actually discriminate."""
    tokens = []
    for token in re.split(r"[^A-Za-zÀ-ÿ0-9]+", str(value)):
        norm = normalize_for_matching(token)
        if len(norm) >= 3 and norm not in STOPWORDS:
            tokens.append(norm)
    return tokens


def best_fuzzy_ratio(needle: str, haystack: str, step: int = 4) -> float:
    if not needle or not haystack:
        return 0.0
    window, best = len(needle), 0.0
    for i in range(0, max(1, len(haystack) - window + 1), step):
        ratio = difflib.SequenceMatcher(None, needle, haystack[i:i + window]).ratio()
        if ratio > best:
            best = ratio
            if best == 1.0:
                break
    return best


# --------------------------------------------------------------------------- #
# Entry point 1 — Issue 6: is the value findable in a whole document?
# --------------------------------------------------------------------------- #

def verdict_in_text(field: str, expected, text: str) -> str:
    """Whether `expected` can be found in `text`. Measures OCR preservation."""
    if expected in (None, ""):
        return MISSING

    if field in AMOUNT_FIELDS:
        target = parse_amount_string(expected)
        if target is None:
            return MISSING
        return EXACT if any(abs(v - target) < AMOUNT_TOLERANCE
                            for v in extract_amounts(text)) else MISSING

    text_norm = normalize_for_matching(text)

    if field in DATE_FIELDS:
        return EXACT if any(normalize_for_matching(v) in text_norm
                            for v in date_variants(expected)) else MISSING

    if field in FREETEXT_FIELDS:
        tokens = distinctive_tokens(expected)
        if not tokens:
            return MISSING
        recall = sum(1 for t in tokens if t in text_norm) / len(tokens)
        if recall >= TOKEN_RECALL_EXACT:
            return EXACT
        return PARTIAL if recall >= TOKEN_RECALL_PARTIAL else MISSING

    if field in ENUM_FIELDS:
        # `statut` is a derived label, not a string printed in the document —
        # see the note on infer_statut_indices(). Searching for it in the text
        # is meaningless, so Issue 6 excludes this field entirely.
        return MISSING

    needle = normalize_for_matching(expected)
    if not needle:
        return MISSING
    if needle in text_norm:
        return EXACT
    return PARTIAL if best_fuzzy_ratio(needle, text_norm) >= FUZZY_THRESHOLD else MISSING


# --------------------------------------------------------------------------- #
# Entry point 2 — Issue 7: did the extractor produce the right value?
# --------------------------------------------------------------------------- #

def verdict_against_value(field: str, expected, actual) -> str:
    """Compare one extracted value against the ground truth for the same field.

    Same rules as `verdict_in_text`, applied value-to-value instead of
    value-to-document. An extractor returning None where a value was expected
    is MISSING; returning a value where none was expected is also MISSING
    (a fabricated value is not a success).
    """
    expected_empty = expected in (None, "")
    actual_empty = actual in (None, "")
    if expected_empty and actual_empty:
        return EXACT          # both agree the field is absent
    if expected_empty or actual_empty:
        return MISSING

    if field in AMOUNT_FIELDS:
        target, produced = parse_amount_string(expected), parse_amount_string(actual)
        if target is None or produced is None:
            return MISSING
        return EXACT if abs(produced - target) < AMOUNT_TOLERANCE else MISSING

    if field in ENUM_FIELDS:
        # Strict equality: an enum is right or wrong. Getting INFRUCTUEUX
        # instead of ATTRIBUE is not "approximately correct" — it inverts the
        # meaning of the record.
        return EXACT if str(expected).strip().upper() == str(actual).strip().upper() \
            else MISSING

    if field in DATE_FIELDS:
        expected_forms = {normalize_for_matching(v) for v in date_variants(expected)}
        actual_forms = {normalize_for_matching(v) for v in date_variants(actual)}
        return EXACT if expected_forms & actual_forms else MISSING

    if field in FREETEXT_FIELDS:
        tokens = distinctive_tokens(expected)
        if not tokens:
            return MISSING
        actual_norm = normalize_for_matching(actual)
        recall = sum(1 for t in tokens if t in actual_norm) / len(tokens)
        if recall >= TOKEN_RECALL_EXACT:
            return EXACT
        return PARTIAL if recall >= TOKEN_RECALL_PARTIAL else MISSING

    expected_norm, actual_norm = normalize_for_matching(expected), normalize_for_matching(actual)
    if not expected_norm or not actual_norm:
        return MISSING
    if expected_norm == actual_norm:
        return EXACT
    return PARTIAL if best_fuzzy_ratio(expected_norm, actual_norm) >= FUZZY_THRESHOLD \
        else MISSING


# --------------------------------------------------------------------------- #
# statut — the textual evidence behind each value
# --------------------------------------------------------------------------- #

def infer_statut_indices() -> dict[str, dict]:
    """Documented evidence for deriving `Award.statut`, measured on the corpus.

    `statut` is the most sensitive field of the model: it decides whether a
    market counts as awarded at all, so every downstream statistic depends on
    it. It is also the only field never printed verbatim — it must be inferred.
    This function documents *what the inference may rely on*, so the reasoning
    is auditable rather than buried in a regex.

    Measured on the 388-document corpus (22/08/2026):

      "attributaire"        260 documents
      "concurrent retenu"   214
      "infructueux"          54
      "excessif"              5   <- none of them an OFFRE_EXCESSIVE, see below

    Two traps, both confirmed on real documents:

    1. The word "infructueux" alone does NOT mean the document is INFRUCTUEUX.
       Document 349e44bf... is ATTRIBUE and contains it: a 3-lot PV where lot 1
       was awarded to LINK RAYONNAGE MAROC and lots 2-3 were declared
       infructueux. A document-level keyword search would invert its status.
       Consequence: on multi-lot documents `statut` is a per-lot property, and
       a single document-level value is only valid when the document covers a
       single lot.

    2. "excessif" is a false friend. All 5 corpus occurrences are the rubric
       "Justifier les prix jugés excessifs : Articles 05 et 10" — a per-article
       price justification, never an offer rejected for being too expensive.
       Matching on it would produce 5 false OFFRE_EXCESSIVE.
    """
    return {
        "ATTRIBUE": {
            "indices": [
                "un nom de concurrent retenu / attributaire est present ET non vide",
                "un montant d'acte d'engagement accompagne ce nom",
            ],
            "contre_indices": [
                "le nom retenu vaut 'Neant' (ou une variante OCR : 'NENAT')",
            ],
            "confirme_dans_verite_terrain": 18,
        },
        "INFRUCTUEUX": {
            "indices": [
                "formulation explicite de decision : \"appel d'offres infructueux\"",
                "champ concurrent retenu renseigne a 'Neant'",
                "motif frequent : \"aucun concurrent n'a ete presente\"",
            ],
            "contre_indices": [
                "document multi-lots : le mot peut ne concerner qu'un lot "
                "(cas confirme 349e44bf, ATTRIBUE malgre le mot present)",
            ],
            "confirme_dans_verite_terrain": 2,
        },
        "OFFRE_EXCESSIVE": {
            "indices": [
                "offre recue mais ecartee pour prix juge excessif, avec mention "
                "explicite du rejet - PAS la rubrique de justification de prix",
            ],
            "contre_indices": [
                "\"Justifier les prix juges excessifs : Articles ...\" est une "
                "rubrique de justification par article, pas un rejet (5 faux "
                "amis dans le corpus)",
            ],
            # Statut issu de l'exploration manuelle initiale, mais AUCUN
            # exemple etiquete dans la verite terrain : son extraction ne
            # pourra pas etre validee tant qu'un cas reel n'aura pas ete
            # annote.
            "confirme_dans_verite_terrain": 0,
        },
    }
