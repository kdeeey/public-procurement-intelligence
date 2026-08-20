"""
CLI for the consultations spider (Issue 2).

    # Pass A — the 400 consultations behind the PVs (guaranteed join, covers 2023)
    python scripts/scrape_consultations.py --mode pv-manifest

    # Pass B — context corpus, 150 per categorie per year
    python scripts/scrape_consultations.py --mode listing --per-year 150

    # Both, resuming an interrupted listing walk
    python scripts/scrape_consultations.py --mode both --resume

    # Smoke test (Issue 2 "done" criterion: 20+ real consultations)
    python scripts/scrape_consultations.py --mode listing --per-year 7 --max-pages 1

Both passes append to the same JSONL file, distinguished by the `source` field.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scraper.pmmp.spiders.consultations_spider import (  # noqa: E402
    ConsultationsSpider,
    RAW_DIR,
    load_pv_index,
)

# The working corpus lives in the repo so both team members can run this;
# override with PV_MANIFEST_PATH in .env if it sits elsewhere.
DEFAULT_MANIFEST = Path(
    os.getenv("PV_MANIFEST_PATH", "data/samples/PVs/manifest.jsonl"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=("pv-manifest", "listing", "both"),
                    default="both")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST,
                    help="PV manifest (join keys for pass A); env PV_MANIFEST_PATH")
    ap.add_argument("--categories", default="1,2,3",
                    help="1=Travaux 2=Fournitures 3=Services")
    ap.add_argument("--years", default="2024,2025,2026",
                    help="pass B only — 2023 is unreachable via the listing")
    ap.add_argument("--per-year", type=int, default=150,
                    help="pass B quota per categorie per year")
    ap.add_argument("--page-size", type=int, default=500)
    ap.add_argument("--max-pages", type=int, default=200)
    ap.add_argument("--limit", type=int, default=0,
                    help="pass A only — cap the number of consultations")
    ap.add_argument("--resume", action="store_true",
                    help="pass B only — continue from the saved checkpoint")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=RAW_DIR)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                        datefmt="%H:%M:%S")
    log = logging.getLogger("scrape_consultations")

    categories = [c.strip() for c in args.categories.split(",") if c.strip()]
    years = [int(y) for y in args.years.split(",") if y.strip()]

    pv_index = None
    if args.manifest.exists():
        pv_index = load_pv_index(args.manifest)
        log.info("PV manifest: %d consultations, %d textual references",
                 len(pv_index["ids"]), len(pv_index["references"]))
    elif args.mode in ("pv-manifest", "both"):
        log.error("PV manifest not found: %s — pass A needs it "
                  "(set --manifest or PV_MANIFEST_PATH)", args.manifest)
        if args.mode == "pv-manifest":
            return 2
        log.warning("continuing with pass B only")

    with ConsultationsSpider(out_dir=args.out_dir, out_path=args.out) as spider:
        log.info("Output: %s", spider.out_path)
        if args.resume:
            # a resumed run appends to the same file; adopt what is already there
            # so the final join report covers the whole collection
            spider.preload()
        try:
            if args.mode in ("pv-manifest", "both") and pv_index is not None:
                spider.run_pv_manifest(args.manifest, limit=args.limit or None)
            if args.mode in ("listing", "both"):
                spider.run_listing(categories=categories, years=years,
                                   per_year=args.per_year, page_size=args.page_size,
                                   max_pages=args.max_pages, resume=args.resume)
        except KeyboardInterrupt:
            log.warning("interrupted — reporting on what was collected so far")

        print("\n" + "=" * 62)
        print(spider.report(pv_index))
        print("=" * 62)

        if spider.errors:
            print(f"\n{len(spider.errors)} non-fatal errors, first 10:")
            for err in spider.errors[:10]:
                print(f"  {err}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
