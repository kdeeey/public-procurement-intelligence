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
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ocr.matching import EXACT, MISSING, PARTIAL, verdict_in_text  # noqa: E402
from ocr.text_cleaning import clean  # noqa: E402

GROUND_TRUTH = REPO / "data/samples/ground_truth.json"
OCR_DIR = REPO / "data/processed/ocr"

# Toute la logique de comparaison vit dans ocr/matching.py, partagee avec la
# validation de l'extraction (Issue 7) : une seule definition, donc les trois
# biais de mesure corriges pendant l'Issue 6 ne peuvent pas reapparaitre dans
# un second comparateur ecrit a la main.
# Les champs de la verite terrain reellement mesurables dans le texte OCR.
# Ecrits explicitement plutot que derives des familles de ocr/matching.py :
# ces familles servent a choisir une REGLE de comparaison, pas a definir ce
# que cette evaluation-ci mesure. `statut` en est absent a dessein (label
# derive, jamais imprime tel quel dans le document).
EVALUATED_FIELDS = (
    "reference_pv",
    "concurrent_retenu",
    "date_ouverture_plis",
    "date_achevement_commission",
    "montant_offre_retenue",
    "acheteur_public",
    "objet",
)


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

        for field in EVALUATED_FIELDS:
            expected = doc["valeurs_attendues"].get(field)
            if expected in (None, ""):
                continue
            verdict = verdict_in_text(field, expected, text)
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
