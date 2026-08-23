"""
OCR quality evaluation against the hand-annotated ground truth (Issue 6).

Answers one question: **did the OCR preserve the information?** — not "can we
extract it", which is Issue 7. Concretely: for each field a human read off the
source PDF, is that value findable in the text the pipeline produced?

Reported before and after ocr/text_cleaning.py, so the cleaning step has to
prove it improves recall rather than being taken on faith.

    python scripts/evaluate_ocr.py
    python scripts/evaluate_ocr.py --show-failures

Matching is deliberately field-dependent — a single strategy would be wrong:

  * Short distinctive values (reference, winner) -> substring on the
    normalised text, then fuzzy similarity as a fallback so that a single
    mis-recognised character counts as "approché", not "absent".
  * Dates and amounts -> substring only, across several written forms. A date
    is right or wrong; "approximately 28/12/2023" is meaningless.
  * Free-text fields (acheteur_public, objet) -> token recall. The annotation
    paraphrases these ("ADER-Fès (maître d'ouvrage délégué)" where the PDF
    words it differently), so substring matching would measure the
    annotator's phrasing rather than the OCR.
  * `statut` is excluded: it is a derived label (ATTRIBUE / INFRUCTUEUX), not
    a string that appears verbatim in the document.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ocr.text_cleaning import clean, normalize_for_matching  # noqa: E402

GROUND_TRUTH = REPO / "data/samples/ground_truth.json"
OCR_DIR = REPO / "data/processed/ocr"

EXACT, PARTIAL, MISSING = "exact", "approche", "absent"

FUZZY_THRESHOLD = 0.85       # short values: 1-2 wrong characters still "approché"
TOKEN_RECALL_EXACT = 0.90    # free text: nearly all distinctive words present
TOKEN_RECALL_PARTIAL = 0.60  # free text: the gist is there

# Words carrying no discriminating power in this corpus — every PV contains
# them, so leaving them in would inflate token recall for free-text fields.
STOPWORDS = {
    "de", "du", "des", "la", "le", "les", "l", "d", "et", "en", "au", "aux",
    "pour", "par", "sur", "dans", "a", "the", "of",
    "maitre", "ouvrage", "delegue", "monsieur", "madame", "societe", "ste",
    "sarl", "sa", "au", "president", "directeur", "direction", "service",
    "commune", "province", "prefecture", "royaume", "maroc", "ministere",
}

SHORT_FIELDS = ("reference_pv", "concurrent_retenu")
DATE_FIELDS = ("date_ouverture_plis", "date_achevement_commission")
AMOUNT_FIELDS = ("montant_offre_retenue",)
FREETEXT_FIELDS = ("acheteur_public", "objet")
EVALUATED_FIELDS = SHORT_FIELDS + DATE_FIELDS + AMOUNT_FIELDS + FREETEXT_FIELDS


# French month names, for dates spelled out rather than written in digits.
# Not a theoretical case: one corpus document contains *no numeric date at
# all* — "Date d'ouverture des plis : Le mardi 19 décembre 2023 à 12 heures".
# A first version of date_variants() only generated numeric forms and scored
# that document as an OCR failure, when the OCR had transcribed the date
# perfectly. Third measurement bug of this kind found in Issue 6.
FRENCH_MONTHS = [
    "janvier", "fevrier", "mars", "avril", "mai", "juin",
    "juillet", "aout", "septembre", "octobre", "novembre", "decembre",
]


def date_variants(value: str) -> list[str]:
    """Every written form a date may take: 28/12/2023, 28-12-2023, and
    "28 décembre 2023". Accents are irrelevant — normalize_for_matching
    strips them on both sides."""
    m = re.match(r"\s*(\d{1,2})\D(\d{1,2})\D(\d{4})\s*$", str(value))
    if not m:
        return [str(value)]
    day, month, year = m.group(1).zfill(2), m.group(2).zfill(2), m.group(3)
    variants = [f"{day}/{month}/{year}", f"{day}{month}{year}",
                f"{int(day)}/{int(month)}/{year}"]
    month_index = int(month) - 1
    if 0 <= month_index < 12:
        month_name = FRENCH_MONTHS[month_index]
        variants += [f"{int(day)} {month_name} {year}",
                     f"{day} {month_name} {year}"]
    return variants


# Amounts must NOT go through normalize_for_matching. That helper strips every
# non-alphanumeric character, which destroys the position of the decimal
# separator: "721224.86", "72122.486" and "7212248.6" all collapse to
# "72122486". Three amounts a factor 100 apart would compare equal, so a real
# transcription error could be scored as a match. Amounts are therefore parsed
# to floats and compared numerically.
AMOUNT_TOLERANCE = 0.01  # DH — same cents, whatever the written form

# Space and non-breaking space only - deliberately NOT \s, which also
# matches newlines: a first version using \s merged "1838 00" on one line
# with "183 600,00" on the next into a single token parsing to 183800.0,
# hiding an amount that was actually present. Amounts never span lines.
_AMOUNT_TOKEN_RE = re.compile(r"\d[\d.,  ]{1,}\d")


def parse_amount_string(raw: str) -> float | None:
    """Parse a Moroccan/French written amount into a float.

    Handles space or dot thousands separators and comma or dot decimals:
    "9 269 719,80" / "9.269.719,80" / "9269719.80" all give 9269719.80.
    The rule for an ambiguous single separator is its distance from the end —
    exactly one or two trailing digits means it is decimal, anything else
    means thousands ("1.234.567" is 1234567, not 1.234567).
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
        if s.count(sep) == 1 and len(tail) in (1, 2):
            s = s.replace(sep, ".")      # decimal separator
        else:
            s = s.replace(sep, "")       # thousands separator
    try:
        return float(s)
    except ValueError:
        return None


def extract_amounts(text: str) -> list[float]:
    """Every number-like token of the text, parsed as a float."""
    values = []
    for token in _AMOUNT_TOKEN_RE.findall(text):
        parsed = parse_amount_string(token)
        if parsed is not None:
            values.append(parsed)
    return values


def distinctive_tokens(value: str) -> list[str]:
    raw = re.split(r"[^A-Za-zÀ-ÿ0-9]+", str(value))
    tokens = []
    for token in raw:
        norm = normalize_for_matching(token)
        if len(norm) >= 3 and norm not in STOPWORDS:
            tokens.append(norm)
    return tokens


def best_fuzzy_ratio(needle: str, haystack: str, step: int = 4) -> float:
    """Best similarity of `needle` against any window of `haystack`."""
    if not needle or not haystack:
        return 0.0
    window = len(needle)
    best = 0.0
    for i in range(0, max(1, len(haystack) - window + 1), step):
        ratio = difflib.SequenceMatcher(None, needle, haystack[i:i + window]).ratio()
        if ratio > best:
            best = ratio
            if best == 1.0:
                break
    return best


def verdict_for(field: str, expected, text_norm: str, text_raw: str) -> str:
    if field in DATE_FIELDS:
        return EXACT if any(normalize_for_matching(v) in text_norm
                            for v in date_variants(expected)) else MISSING

    if field in AMOUNT_FIELDS:
        target = parse_amount_string(expected)
        if target is None:
            return MISSING
        # Numeric comparison against every number in the text — never a string
        # match, see the note on AMOUNT_TOLERANCE.
        return EXACT if any(abs(value - target) < AMOUNT_TOLERANCE
                            for value in extract_amounts(text_raw)) else MISSING

    if field in FREETEXT_FIELDS:
        tokens = distinctive_tokens(expected)
        if not tokens:
            return MISSING
        found = sum(1 for t in tokens if t in text_norm)
        recall = found / len(tokens)
        if recall >= TOKEN_RECALL_EXACT:
            return EXACT
        return PARTIAL if recall >= TOKEN_RECALL_PARTIAL else MISSING

    needle = normalize_for_matching(expected)
    if not needle:
        return MISSING
    if needle in text_norm:
        return EXACT
    return PARTIAL if best_fuzzy_ratio(needle, text_norm) >= FUZZY_THRESHOLD else MISSING


def evaluate(documents: list[dict], use_cleaning: bool) -> tuple[dict, list]:
    results: dict[str, dict[str, int]] = defaultdict(
        lambda: {EXACT: 0, PARTIAL: 0, MISSING: 0})
    failures = []

    for doc in documents:
        txt_path = OCR_DIR / f"{doc['doc_id']}.txt"
        if not txt_path.exists():
            continue
        raw = txt_path.read_text(encoding="utf-8")
        text = clean(raw).text if use_cleaning else raw
        text_norm = normalize_for_matching(text)

        for field in EVALUATED_FIELDS:
            expected = doc["valeurs_attendues"].get(field)
            if expected in (None, ""):
                continue
            verdict = verdict_for(field, expected, text_norm, text)
            results[field][verdict] += 1
            if verdict == MISSING:
                failures.append((doc["doc_id"][:12], field, str(expected)[:55]))

    return results, failures


def print_table(title: str, results: dict) -> tuple[int, int]:
    print(f"\n=== {title} ===")
    print(f"{'champ':<28}{'exact':>7}{'approche':>10}{'absent':>8}{'total':>7}{'trouve':>9}")
    total_found = total_all = 0
    for field in EVALUATED_FIELDS:
        r = results.get(field)
        if not r:
            continue
        n = r[EXACT] + r[PARTIAL] + r[MISSING]
        found = r[EXACT] + r[PARTIAL]
        total_found += found
        total_all += n
        print(f"{field:<28}{r[EXACT]:>7}{r[PARTIAL]:>10}{r[MISSING]:>8}{n:>7}"
              f"{found / n * 100:>8.0f}%")
    if total_all:
        print(f"{'TOTAL':<28}{'':>7}{'':>10}{'':>8}{total_all:>7}"
              f"{total_found / total_all * 100:>8.0f}%")
    return total_found, total_all


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show-failures", action="store_true",
                    help="lister les valeurs introuvables apres nettoyage")
    args = ap.parse_args()

    gt = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    documents = [d for d in gt["documents"]
                 if any(v is not None for v in d["valeurs_attendues"].values())]
    print(f"Verite terrain : {len(documents)} documents annotes")
    print(f"Texte OCR      : {OCR_DIR}")

    before, _ = evaluate(documents, use_cleaning=False)
    after, failures = evaluate(documents, use_cleaning=True)

    found_before, total_before = print_table("AVANT nettoyage (texte OCR brut)", before)
    found_after, total_after = print_table("APRES nettoyage (text_cleaning.py)", after)

    print("\n=== effet du nettoyage ===")
    if total_before and total_after:
        delta = found_after / total_after - found_before / total_before
        print(f"  taux trouve : {found_before / total_before * 100:.1f}%"
              f" -> {found_after / total_after * 100:.1f}%  ({delta * 100:+.1f} points)")
    for field in EVALUATED_FIELDS:
        b, a = before.get(field), after.get(field)
        if not b or not a:
            continue
        diff = (a[EXACT] + a[PARTIAL]) - (b[EXACT] + b[PARTIAL])
        exact_diff = a[EXACT] - b[EXACT]
        if diff or exact_diff:
            print(f"  {field:<28} trouve {diff:+d}   dont exact {exact_diff:+d}")

    if args.show_failures:
        print(f"\n=== valeurs introuvables apres nettoyage ({len(failures)}) ===")
        for doc_id, field, value in failures:
            print(f"  {doc_id}  {field:<26} {value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
