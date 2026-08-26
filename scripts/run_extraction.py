"""
Structured extraction over the full OCR corpus (Issue 7).

Reads data/processed/ocr/<doc_id>.txt, runs it through ocr/text_cleaning.py
(the same cleaning step measured to improve OCR recall in Issue 6, so
extraction sees the same text quality that evaluate_ocr.py was validated
against) and extraction/extractor.py, and writes one JSON file per document
to data/processed/extracted/ — a list of Awards, one per lot.

    python scripts/run_extraction.py
    python scripts/run_extraction.py --limit 20
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from extraction.extractor import extract_document  # noqa: E402
from ocr.text_cleaning import clean  # noqa: E402

OCR_DIR = REPO / "data/processed/ocr"
OUT_DIR = REPO / "data/processed/extracted"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="ne traiter que les N premiers documents (debug)")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    txt_files = sorted(OCR_DIR.glob("*.txt"))
    if args.limit:
        txt_files = txt_files[:args.limit]

    total_awards = 0
    detection_counts: dict[str, int] = {}

    for txt_path in txt_files:
        doc_id = txt_path.stem
        raw = txt_path.read_text(encoding="utf-8")
        text = clean(raw).text_fr

        awards = extract_document(doc_id, text)
        total_awards += len(awards)
        for a in awards:
            detection_counts[a.detection] = detection_counts.get(a.detection, 0) + 1

        out_path = OUT_DIR / f"{doc_id}.json"
        out_path.write_text(
            json.dumps([asdict(a) for a in awards], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(f"{len(txt_files)} documents traites -> {OUT_DIR}")
    print(f"{total_awards} Award(s) au total")
    print("Repartition par mode de detection de lot :")
    for detection, count in sorted(detection_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {detection:<28} {count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
