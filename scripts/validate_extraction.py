"""
Extraction quality validation against the hand-annotated ground truth (Issue 7).

Answers: **did the extractor produce the correct value**, not "is the
information present in the OCR text" (that's Issue 6 / evaluate_ocr.py). Uses
verdict_against_value() from ocr/matching.py exclusively — the same shared
comparator evaluate_ocr.py uses, so the three Issue-6 measurement bugs (lost
decimal separator, newline-swallowing regex, unrecognised textual dates)
cannot silently reappear through a second hand-written comparator.

    python scripts/validate_extraction.py
    python scripts/validate_extraction.py --show-failures

Reports two separate tables, deliberately not blended into one rate:

  * MEASURED  — fields with an annotated ground-truth equivalent.
  * NON VALIDE — fields extracted (liste_concurrents, concurrents_ecartes,
    OFFRE_EXCESSIVE) with no ground-truth equivalent to check against.

The OCR information-presence ceiling measured in Issue 6 is 96% — extraction
cannot structurally exceed it. Rates are reported against that ceiling, not
against 100%.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from extraction.patterns import (  # noqa: E402
    AMOUNT_HT_RE, AMOUNT_TTC_RE, HEADER_HT_RE, HEADER_TTC_RE,
)
from ocr.matching import EXACT, MISSING, PARTIAL, verdict_against_value  # noqa: E402
from ocr.text_cleaning import clean  # noqa: E402

GROUND_TRUTH = REPO / "data/samples/ground_truth.json"
EXTRACTED_DIR = REPO / "data/processed/extracted"
OCR_DIR = REPO / "data/processed/ocr"
OCR_CEILING = 0.96


def _has_any_base_marker(doc_id: str) -> bool:
    """Whether the source text states a base (HT/TTC) anywhere at all.

    Distinguishes a genuine extraction gap from data_dictionary.md §3.6's
    "never guess the base" rule doing exactly what it was designed to do:
    diagnosed on the 20-document ground truth (2026), 3 of montant_offre_
    retenue's 6 failures are documents where the amount itself is
    recoverable in the OCR text but no HT/TTC marker is ever printed — the
    extractor is correctly refusing to assign a base that was never stated,
    not missing a pattern it should have matched.
    """
    path = OCR_DIR / f"{doc_id}.txt"
    if not path.exists():
        return True  # unknown -> don't misreport as a schema refusal
    text = clean(path.read_text(encoding="utf-8")).text_fr
    return bool(AMOUNT_TTC_RE.search(text) or AMOUNT_HT_RE.search(text)
                or HEADER_TTC_RE.search(text) or HEADER_HT_RE.search(text))

# Ground-truth key -> Award attribute. montant_offre_retenue and statut need
# special handling (see below) so they are not listed here.
FIELD_MAP = {
    "reference_pv": "reference",
    "concurrent_retenu": "concurrent_retenu",
    "date_ouverture_plis": "date_ouverture_plis",
    "date_achevement_commission": "date_achevement_commission",
}

# acheteur_public and objet are in the ground truth but this extractor never
# claimed them (extraction/fields.py has no extract_acheteur/extract_objet —
# not in the approved plan's function list). Reported separately, not
# silently dropped, so the limitation is visible rather than hidden.
NOT_IMPLEMENTED_FIELDS = ("acheteur_public", "objet")


def _load_awards(doc_id: str) -> list[dict]:
    path = EXTRACTED_DIR / f"{doc_id}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _montant_actual(award: dict) -> float | None:
    # montant_ttc and montant_ht are never both filled with different values
    # by design (data_dictionary.md §3.6) — whichever is present is "the"
    # amount for comparison against the ground truth's single legacy field.
    return award["montant_ttc"] if award["montant_ttc"] is not None else award["montant_ht"]


def evaluate(documents: list[dict]) -> tuple[dict, dict, list, list, list]:
    measured: dict[str, dict[str, int]] = defaultdict(
        lambda: {EXACT: 0, PARTIAL: 0, MISSING: 0})
    not_implemented: dict[str, int] = defaultdict(int)
    failures = []
    montant_schema_refusals: list[str] = []
    montant_regex_gaps: list[str] = []

    for doc in documents:
        awards = _load_awards(doc["doc_id"])
        if not awards:
            continue
        expected = doc["valeurs_attendues"]

        # Awards are indistinguishable from the ground truth's perspective
        # when there is exactly one (mono-lot document, the only case
        # annotated) — multi-lot documents have no per-lot ground truth to
        # validate against, per the plan's explicitly stated limitation.
        award = awards[0] if len(awards) == 1 else None

        for field in NOT_IMPLEMENTED_FIELDS:
            if expected.get(field) not in (None, ""):
                not_implemented[field] += 1

        if award is None:
            continue

        for gt_field, award_field in FIELD_MAP.items():
            exp_value = expected.get(gt_field)
            if exp_value in (None, ""):
                continue
            verdict = verdict_against_value(gt_field, exp_value, award[award_field])
            measured[gt_field][verdict] += 1
            if verdict == MISSING:
                failures.append((doc["doc_id"][:12], gt_field, str(exp_value)[:55],
                                 str(award[award_field])[:55]))

        exp_montant = expected.get("montant_offre_retenue")
        if exp_montant not in (None, ""):
            verdict = verdict_against_value("montant_offre_retenue", exp_montant,
                                            _montant_actual(award))
            measured["montant_offre_retenue"][verdict] += 1
            if verdict == MISSING:
                if _has_any_base_marker(doc["doc_id"]):
                    montant_regex_gaps.append(doc["doc_id"][:12])
                else:
                    montant_schema_refusals.append(doc["doc_id"][:12])
                failures.append((doc["doc_id"][:12], "montant_offre_retenue",
                                 str(exp_montant), str(_montant_actual(award))))

        exp_statut = expected.get("statut")
        if exp_statut not in (None, ""):
            verdict = verdict_against_value("statut", exp_statut, award["statut"])
            measured["statut"][verdict] += 1
            if verdict == MISSING:
                failures.append((doc["doc_id"][:12], "statut", exp_statut, award["statut"]))

    return measured, not_implemented, failures, montant_schema_refusals, montant_regex_gaps


def print_table(results: dict) -> None:
    print(f"\n{'champ':<28}{'exact':>7}{'approche':>10}{'absent':>8}{'total':>7}"
          f"{'trouve':>9}{'vs plafond 96%':>16}")
    total_found = total_all = 0
    for field, r in results.items():
        n = r[EXACT] + r[PARTIAL] + r[MISSING]
        found = r[EXACT] + r[PARTIAL]
        total_found += found
        total_all += n
        rate = found / n if n else 0.0
        gap = rate - OCR_CEILING
        print(f"{field:<28}{r[EXACT]:>7}{r[PARTIAL]:>10}{r[MISSING]:>8}{n:>7}"
              f"{rate * 100:>8.0f}%{gap * 100:>+15.0f} pts")
    if total_all:
        rate = total_found / total_all
        print(f"{'TOTAL':<28}{'':>7}{'':>10}{'':>8}{total_all:>7}"
              f"{rate * 100:>8.0f}%{(rate - OCR_CEILING) * 100:>+15.0f} pts")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show-failures", action="store_true")
    args = ap.parse_args()

    gt = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    documents = [d for d in gt["documents"]
                 if any(v is not None for v in d["valeurs_attendues"].values())]
    print(f"Verite terrain : {len(documents)} documents annotes")
    print(f"Extraction     : {EXTRACTED_DIR}")
    print(f"Plafond OCR mesure (Issue 6) : {OCR_CEILING * 100:.0f}% — "
          "l'ecart au plafond mesure les regex, pas l'OCR.")

    measured, not_implemented, failures, schema_refusals, regex_gaps = evaluate(documents)

    print("\n=== CHAMPS MESURES (verite terrain disponible) ===")
    print_table(measured)

    if schema_refusals or regex_gaps:
        print("\n=== montant_offre_retenue : detail des echecs ===")
        print(f"  refus du schema (§3.6, base HT/TTC jamais affichee dans le "
              f"document — le chiffre est present dans le texte OCR mais "
              f"aucune base n'est extraite plutot que d'en deviner une) : "
              f"{len(schema_refusals)}  {schema_refusals}")
        print(f"  ecart residuel (plafond OCR Issue 6 ou mise en page "
              f"tabulaire eclatee, non couvert par regle) : "
              f"{len(regex_gaps)}  {regex_gaps}")
        n = len(schema_refusals) + len(regex_gaps)
        if n:
            print(f"  -> sur les echecs 'absent', {len(schema_refusals)}/{n} "
                  "sont le schema applique correctement, pas une regex manquante.")

    print("\n=== CHAMPS NON IMPLEMENTES (dans la verite terrain, jamais extraits) ===")
    if not_implemented:
        for field, count in not_implemented.items():
            print(f"  {field:<28} {count} document(s) annote(s) avec une valeur "
                  "attendue, extract_* absent de extraction/fields.py")
    else:
        print("  aucun")

    print("\n=== CHAMPS EXTRAITS MAIS NON VALIDABLES (pas d'equivalent en verite terrain) ===")
    print("  liste_concurrents, concurrents_ecartes, montant_par_concurrent, classement,")
    print("  OFFRE_EXCESSIVE : extraits par decision explicite du plan Issue 7, exactitude")
    print("  non mesuree — voir limites du rapport final.")

    if args.show_failures:
        print(f"\n=== echecs ({len(failures)}) ===")
        for doc_id, field, expected, actual in failures:
            print(f"  {doc_id}  {field:<26} attendu={expected!r:<40} obtenu={actual!r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
