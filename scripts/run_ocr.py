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
import json
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / ".env")

from ocr.pipeline import DocumentOcrResult, process_pdf_safe  # noqa: E402

DEFAULT_DIRS = [REPO / "data/samples/PV", REPO / "data/samples/resultats"]
DEFAULT_OUT_DIR = REPO / "data/processed/ocr"

# Excluded from every OCR run, by filename stem — the files themselves and
# their manifest entry stay in place (corpus counts documented elsewhere:
# etat_de_lart.md, data_dictionary.md, ideas.md — all assume 390 PDF / 400
# manifest lines, 100/year), only the OCR pass skips them.
#   65597f99...cf78 : confirmed OSD false positive (methodology.md §1.2) —
#     page 2 gets rotated 180° incorrectly, destroying an already-legible
#     page. The document-level confidence crosses the success threshold
#     anyway (page 1 improved enough to mask it), so it would pass silently.
#   9d2a5e07...1e1  : its only OCR page is genuinely blank (confirmed:
#     mean luminosity 254.96/255, std 3.1) — no defect, just nothing to
#     extract from that page; page 1 (native) already carries the content.
EXCLUDED_STEMS = {
    "65597f99d131db2a59fabcab9bb39929f9f1f9f1ff518a1ef60e0ccdb0bfcf78",
    "9d2a5e0783702e0198d5bdfe23c3212d72fa6501308724cbb85bf03d2b6d01e1",
}

TABLE_KEYWORDS = ("classement", "concurrent 1", "concurrent 2", "montant par",
                  "liste des concurrents")


def save_text(result: DocumentOcrResult, out_dir: Path) -> None:
    """Persist raw OCR text + per-page metadata to data/processed/ocr/, so
    Issue 6 (text cleaning) has a file to work from instead of re-running OCR
    or digging through a scratchpad log."""
    stem = Path(result.pdf_path).stem
    (out_dir / f"{stem}.txt").write_text(result.text, encoding="utf-8")
    meta = {
        "pdf_path": result.pdf_path,
        "ocr_status": result.ocr_status,
        "mean_confidence": result.mean_confidence,
        "pages": [
            {
                "page_number": p.page_number,
                "source": p.source,
                "confidence": p.confidence,
                "skew_angle_deg": p.skew_angle_deg,
                "deskewed": p.deskewed,
                "orientation_rotate_deg": p.orientation_rotate_deg,
                "orientation_confidence": p.orientation_confidence,
                "error": p.error,
            }
            for p in result.pages
        ],
    }
    (out_dir / f"{stem}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, action="append", default=None,
                    help="directory of PDFs to process; repeatable. Default: data/samples/")
    ap.add_argument("--limit", type=int, default=0, help="0 = no limit")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR,
                    help="where to persist OCR text + metadata; default data/processed/ocr/")
    ap.add_argument("--no-save", action="store_true",
                    help="skip persisting text (console report only)")
    args = ap.parse_args()

    if not args.no_save:
        args.out_dir.mkdir(parents=True, exist_ok=True)

    dirs = args.dir or DEFAULT_DIRS
    all_files = sorted(f for d in dirs for f in Path(d).glob("*.pdf"))
    excluded = [f for f in all_files if f.stem in EXCLUDED_STEMS]
    files = [f for f in all_files if f.stem not in EXCLUDED_STEMS]
    if args.limit:
        files = files[:args.limit]

    if excluded:
        print(f"{len(excluded)} fichier(s) exclu(s) (EXCLUDED_STEMS) :")
        for f in excluded:
            print(f"  - {f.name}")
        print()
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
        if not args.no_save:
            save_text(result, args.out_dir)
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
