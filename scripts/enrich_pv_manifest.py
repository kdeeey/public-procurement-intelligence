"""
Enrich the PV manifest with the consultation metadata that the listing walk did
not record: categorie_principale, mode_passation, acheteur_public, objet.

The detail page is re-fetched once per document (rate-limited by PMPPDownloader)
and the manifest is rewritten in place with the extra fields.

Usage:
    python scripts/enrich_pv_manifest.py --limit 40     # quick sample
    python scripts/enrich_pv_manifest.py               # all records
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from bs4 import BeautifulSoup  # noqa: E402

from scraper.pmmp.utils.downloader import PMPPDownloader  # noqa: E402

BASE = "https://www.marchespublics.gov.ma/index.php"
DEFAULT_MANIFEST = Path(
    os.getenv("PV_MANIFEST_PATH", "data/samples/PVs/manifest.jsonl"))

LABELS = {
    "categorie_principale": ["Catégorie principale", "Catégorie"],
    "mode_passation": ["Procédure", "Mode de passation", "Type de procédure"],
    "acheteur_public": ["Acheteur public", "Maître d'ouvrage"],
    "objet": ["Objet"],
}


def detail_url_from(rec: dict) -> str | None:
    """Rebuild the consultation detail URL from the stored PDF URL."""
    m = re.search(r"refConsultation=(\d+)", rec.get("pdf_url", ""))
    o = re.search(r"orgAcronyme=([^&]+)", rec.get("pdf_url", ""))
    if not (m and o):
        return None
    return (f"{BASE}?page=entreprise.EntrepriseDetailConsultation"
            f"&refConsultation={m.group(1)}&orgAcronyme={o.group(1)}")


def parse_meta(html: str) -> dict:
    """Pull the labelled fields out of the detail page's <div class="line"> blocks."""
    soup = BeautifulSoup(html, "html.parser")
    text_blocks = []
    for div in soup.find_all("div", class_="line"):
        t = re.sub(r"\s+", " ", div.get_text(" ", strip=True))
        if t:
            text_blocks.append(t)
    blob = " || ".join(text_blocks)

    out: dict[str, str] = {}
    for field, labels in LABELS.items():
        for lab in labels:
            m = re.search(rf"{re.escape(lab)}\s*:\s*([^|]{{1,180}})", blob)
            if m:
                val = m.group(1).strip(" :")
                # the category cell sometimes trails into the next label
                val = re.split(r"\s{2,}|Procédure|Acheteur public", val)[0].strip()
                if val:
                    out[field] = val
                    break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--limit", type=int, default=0, help="0 = all records")
    args = ap.parse_args()

    records = [json.loads(l) for l in
               args.manifest.read_text(encoding="utf-8").splitlines() if l.strip()]
    todo = [r for r in records if "categorie_principale" not in r]
    if args.limit:
        todo = todo[:args.limit]

    print(f"{len(records)} records, {len(todo)} to enrich\n")
    dl = PMPPDownloader()
    cats: Counter = Counter()
    modes: Counter = Counter()
    done = 0

    for rec in todo:
        url = detail_url_from(rec)
        if not url:
            continue
        try:
            meta = parse_meta(dl.get(url).text)
        except Exception as e:
            print(f"ERR {rec.get('reference')}: {e}")
            continue
        rec.update(meta)
        cats[meta.get("categorie_principale", "?")] += 1
        modes[meta.get("mode_passation", "?")] += 1
        done += 1
        if done % 20 == 0:
            print(f"  {done}/{len(todo)} — {dict(cats)}")

        args.manifest.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
            encoding="utf-8")

    print(f"\n=== enriched {done} records ===")
    print("\ncategorie_principale:")
    for k, v in cats.most_common():
        print(f"  {v:4d}  ({v/max(done,1)*100:5.1f}%)  {k}")
    print("\nmode_passation:")
    for k, v in modes.most_common(10):
        print(f"  {v:4d}  ({v/max(done,1)*100:5.1f}%)  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
