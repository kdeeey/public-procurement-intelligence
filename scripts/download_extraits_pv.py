"""
Standalone script: download public "Extrait de PV" PDFs from the PMMP portal,
filed into per-year folders.

Portal behaviour established by inspecting saved HTML in data/raw/:

  * `&page_courante=N` in the URL is IGNORED — every page returns page 1.
    Real pagination is a PRADO postback: POST the whole form back with
    PRADO_POSTBACK_TARGET set to the pager's "next page" control, carrying the
    PRADO_PAGESTATE returned by the previous response.
  * The advanced-search date filter (dateMiseEnLigneCalculeStart/End) is also
    ignored server-side — even a one-day window returns the full 94 806 hits.
    So years are selected client-side while walking the (date-descending)
    result set, not by asking the server.
  * annonceType=5 IS honoured and restricts results to "Annonce d'extrait de PV".
  * The PV icon in a listing row is only a badge; the download link lives on the
    consultation detail page as:
        ?page=entreprise.EntrepriseDownloadAvisJAL&refConsultation=..&orgAcronyme=..&idAvis=..
  * PDFs are served as application/octet-stream, so PDF-ness is decided by the
    %PDF magic bytes (handled inside PMPPDownloader.download_pdf).

Usage:
    python scripts/download_extraits_pv.py --per-year 300 --min-year 2023
    python scripts/download_extraits_pv.py --per-year 5 --max-pages 2   # smoke test
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from bs4 import BeautifulSoup  # noqa: E402

from scraper.pmmp.utils.downloader import PMPPDownloader  # noqa: E402
from scraper.pmmp.utils.prado import PradoSearch  # noqa: E402

BASE = "https://www.marchespublics.gov.ma/index.php"
SEARCH_URL = BASE + "?page=entreprise.EntrepriseAdvancedSearch&AvisExtraitPV"

ANNONCE_TYPE_PV = "5"

DEFAULT_OUT = Path(os.getenv("PV_CORPUS_PATH", "data/samples/PVs"))
DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")


# --------------------------------------------------------------------------- #
# parsing helpers
# --------------------------------------------------------------------------- #

def parse_date(text: str) -> date | None:
    m = DATE_RE.search(text or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%d/%m/%Y").date()
    except ValueError:
        return None


def parse_listing(html: str) -> list[dict]:
    """One dict per result row: reference, publication date, detail URL."""
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "EntrepriseDetailConsultation" not in href:
            continue
        ref_m = re.search(r"refConsultation=(\d+)", href)
        org_m = re.search(r"orgAcronyme=([^&]+)", href)
        if not (ref_m and org_m):
            continue
        key = (ref_m.group(1), org_m.group(1))
        if key in seen:                      # the page renders duplicate links
            continue
        seen.add(key)

        tr = a.find_parent("tr")
        if tr is None:
            continue
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]

        pub = next((parse_date(td) for td in tds if parse_date(td)), None)
        reference = ""
        for td in tds:
            m = re.match(r"^\s*(\S+)\s+-", td)
            if m and not DATE_RE.match(m.group(1)):
                reference = m.group(1)
                break

        rows.append({
            "reference": reference,
            "date_publication": pub.strftime("%d/%m/%Y") if pub else "",
            "_date": pub,
            "detail_url": urljoin(BASE, href),
        })
    return rows


def find_pv_url(detail_html: str) -> str | None:
    """The EntrepriseDownloadAvisJAL link carrying a real idAvis."""
    soup = BeautifulSoup(detail_html, "html.parser")
    for a in soup.find_all("a", href=True):
        if "EntrepriseDownloadAvisJAL" in a["href"] and re.search(r"idAvis=(\d+)", a["href"]):
            return urljoin(BASE, a["href"])
    return None


def is_pv_annonce(detail_html: str) -> bool:
    text = BeautifulSoup(detail_html, "html.parser").get_text(" ", strip=True).lower()
    return "extrait de pv" in text or "extrait du pv" in text


# --------------------------------------------------------------------------- #
# PRADO-driven listing walker
# --------------------------------------------------------------------------- #

class PVSearch:
    """Walks the PV result set page by page.

    The PRADO postback plumbing lives in scraper/pmmp/utils/prado.py, shared
    with the consultations spider; this class only adds the PV-specific search
    field and row parsing.
    """

    def __init__(self, dl: PMPPDownloader, page_size: int = 500):
        self.search = PradoSearch(dl, SEARCH_URL, page_size=page_size)

    @property
    def html(self) -> str:
        return self.search.html

    def start(self) -> list[dict]:
        """Run the search restricted to annonce type = extrait de PV."""
        self.search.start({"annonceType": ANNONCE_TYPE_PV})
        return parse_listing(self.search.html)

    def next_page(self) -> list[dict]:
        return parse_listing(self.search.next_page())

    def total_results(self) -> str:
        total = self.search.total_results()
        return str(total) if total is not None else "?"


# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--per-year", type=int, default=100,
                    help="max PDFs to keep per year (0 = unlimited)")
    ap.add_argument("--min-year", type=int, default=2023)
    ap.add_argument("--max-year", type=int, default=2026)
    ap.add_argument("--page-size", type=int, default=500)
    ap.add_argument("--max-pages", type=int, default=500)
    args = ap.parse_args()

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_dir / "manifest.jsonl"

    # resume: remember what we already have, and how full each year is
    done: set[str] = set()
    per_year: dict[int, int] = defaultdict(int)
    if manifest.exists():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            done.add(rec.get("pdf_url", ""))
            y = rec.get("year") or parse_date(rec.get("date_publication", ""))
            if isinstance(y, date):
                y = y.year
            if y:
                per_year[int(y)] += 1
    if done:
        print(f"[resume] {len(done)} already downloaded — "
              f"{dict(sorted(per_year.items()))}\n")

    cap = args.per_year or float("inf")
    years = set(range(args.min_year, args.max_year + 1))

    dl = PMPPDownloader()
    search = PVSearch(dl, page_size=args.page_size)
    stats = {"ok": 0, "skip": 0, "err": 0}

    print("running PV search (annonceType=5)...")
    rows = search.start()
    print(f"total PV results on portal: {search.total_results()}")
    print(f"targets: {sorted(years)}, cap {args.per_year or 'unlimited'}/year\n")

    with manifest.open("a", encoding="utf-8") as mf:
        page = 1
        while page <= args.max_pages:
            if not rows:
                print("empty page — stopping")
                break

            dates = [r["_date"] for r in rows if r["_date"]]
            span = (f"{min(dates).strftime('%d/%m/%Y')}..{max(dates).strftime('%d/%m/%Y')}"
                    if dates else "no dates")
            filled = {y: per_year[y] for y in sorted(years)}
            print(f"\n=== page {page} ({len(rows)} rows, {span}) {filled} ===")

            for r in rows:
                ref, pub = r["reference"] or "?", r["_date"]
                if pub is None:
                    print(f"SKIP (no date) {ref}")
                    stats["skip"] += 1
                    continue
                if pub.year not in years:
                    stats["skip"] += 1
                    continue
                if per_year[pub.year] >= cap:
                    stats["skip"] += 1
                    continue

                try:
                    detail_html = dl.get(r["detail_url"]).text
                except Exception as e:
                    print(f"ERR  {ref}: detail fetch: {e}")
                    stats["err"] += 1
                    continue

                if not is_pv_annonce(detail_html):
                    print(f"SKIP (not a PV annonce) {ref}")
                    stats["skip"] += 1
                    continue

                pdf_url = find_pv_url(detail_html)
                if not pdf_url:
                    print(f"SKIP (no public PV link — form or missing) {ref}")
                    stats["skip"] += 1
                    continue
                if pdf_url in done:
                    stats["skip"] += 1
                    continue

                try:
                    path = dl.download_pdf(pdf_url, out_dir / str(pub.year))
                except Exception as e:
                    print(f"ERR  {ref}: download: {e}")
                    stats["err"] += 1
                    continue
                if path is None:
                    print(f"SKIP (not a PDF — form/HTML returned) {ref}")
                    stats["skip"] += 1
                    continue

                mf.write(json.dumps({
                    "reference": r["reference"],
                    "date_publication": r["date_publication"],
                    "year": pub.year,
                    "pdf_url": pdf_url,
                    "local_path": str(path),
                    "file_hash": path.stem,
                    "scraped_at": datetime.now().isoformat(timespec="seconds"),
                }, ensure_ascii=False) + "\n")
                mf.flush()
                done.add(pdf_url)
                per_year[pub.year] += 1
                stats["ok"] += 1
                print(f"OK   {ref} {r['date_publication']} -> "
                      f"{pub.year}/{path.name[:16]}… ({path.stat().st_size // 1024} KB)")

            # every targeted year full?
            if all(per_year[y] >= cap for y in years):
                print("\nall year quotas filled — stopping")
                break
            # walked past the oldest year we care about?
            if dates and max(dates).year < args.min_year:
                print(f"\npast {args.min_year} — stopping")
                break

            try:
                rows = search.next_page()
            except Exception as e:
                print(f"ERR  pagination: {e}")
                stats["err"] += 1
                break
            page += 1

    print(f"\n=== done: {stats['ok']} OK, {stats['skip']} SKIP, {stats['err']} ERR ===")
    for y in sorted(per_year):
        d = out_dir / str(y)
        if d.exists():
            pdfs = list(d.glob("*.pdf"))
            mb = sum(p.stat().st_size for p in pdfs) / 1024 / 1024
            print(f"  {y}/ : {len(pdfs)} PDFs, {mb:.1f} MB")
    print(f"manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
