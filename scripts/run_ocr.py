"""
Run the OCR pipeline (Issue 5) over a directory of PDFs and report results.

Loads .env with an explicit repo-relative path rather than a bare
load_dotenv() — plain load_dotenv() calls find_dotenv(), which searches
upward from the *calling file's* directory, not the current working
directory. A script invoked from outside the repo (or moved without care)
would then silently load no configuration at all — this is exactly what
happened during Issue 5 testing (see the note in ocr/tesseract_engine.py)
and is worth avoiding for good in the one script meant to be run for real.

Usage:
    python scripts/run_ocr.py                                # data/samples/
    python scripts/run_ocr.py --dir data/samples/PVs/2023     # one year of the real corpus
    python scripts/run_ocr.py --limit 20                      # smoke test
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / ".env")

from ocr.pipeline import process_pdf_safe  # noqa: E402

DEFAULT_DIRS = [REPO / "data/samples/PV", REPO / "data/samples/resultats"]

TABLE_KEYWORDS = ("classement", "concurrent 1", "concurrent 2", "montant par",
                  "liste des concurrents")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, action="append", default=None,
                    help="directory of PDFs to process; repeatable. Default: data/samples/")
    ap.add_argument("--limit", type=int, default=0, help="0 = no limit")
    args = ap.parse_args()

    dirs = args.dir or DEFAULT_DIRS
    files = sorted(f for d in dirs for f in Path(d).glob("*.pdf"))
    if args.limit:
        files = files[:args.limit]

    print(f"{len(files)} fichiers\n")
    print(f"{'status':<20}{'conf':>7}{'pages':>7}  {'temps':>6}  fichier")

    status_counts: Counter = Counter()
    table_example = None
    rotations: list[tuple[str, int, float]] = []  # (filename, rotate_deg, orientation_conf)
    run_t0 = time.time()

    for f in files:
        t0 = time.time()
        result = process_pdf_safe(f)
        dt = time.time() - t0
        status_counts[result.ocr_status] += 1
        conf = f"{result.mean_confidence:.1f}" if result.mean_confidence is not None else "-"
        print(f"{result.ocr_status:<20}{conf:>7}{len(result.pages):>7}  {dt:5.1f}s  {f.name[:48]}")

        for page in result.pages:
            if page.error:
                print(f"      ERROR page {page.page_number}: {page.error[:250]}")
            if page.orientation_rotate_deg:
                rotations.append((f"{f.name} p{page.page_number}",
                                  page.orientation_rotate_deg, page.orientation_confidence))
                print(f"      ORIENTATION page {page.page_number}: rotate="
                     f"{page.orientation_rotate_deg}°  orientation_conf="
                     f"{page.orientation_confidence:.2f}")

        if result.ocr_status != "native" and table_example is None:
            if any(k in result.text.lower() for k in TABLE_KEYWORDS):
                table_example = f

    run_dt = time.time() - run_t0
    total = len(files) or 1
    print(f"\n=== distribution ocr_status ({len(files)} documents) ===")
    for status in ("native", "ocr_success", "ocr_low_confidence", "ocr_failed"):
        n = status_counts.get(status, 0)
        print(f"  {status:<20} {n:4d}  ({n / total * 100:5.1f}%)")

    print(f"\n=== rotations OSD declenchees : {len(rotations)} page(s) ===")
    if rotations:
        confs = [c for _, _, c in rotations]
        print(f"  orientation_conf : min={min(confs):.2f}  max={max(confs):.2f}  "
             f"moyenne={sum(confs)/len(confs):.2f}")
        near_threshold = [(name, deg, c) for name, deg, c in rotations if c < 3.0]
        print(f"  proches du seuil 1.0 (conf < 3.0) : {len(near_threshold)}")
        for name, deg, c in sorted(rotations, key=lambda r: r[2]):
            flag = "  <-- PROCHE DU SEUIL" if c < 3.0 else ""
            print(f"    {name:<55} rotate={deg:>4}°  conf={c:6.2f}{flag}")

    print("\nexemple avec structure tabulaire detectee:",
         table_example or "aucun trouve par mots-cles")
    print(f"\ntemps total : {run_dt:.1f}s ({run_dt/60:.1f} min) sur {len(files)} documents"
         f"  ({run_dt/total:.2f}s/document en moyenne)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
