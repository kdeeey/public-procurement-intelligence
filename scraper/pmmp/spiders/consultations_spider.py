"""
Consultations spider — collects PMMP consultation metadata (HTML only, no OCR).

Two complementary passes, forced by a structural limit of the portal:

  PASS A — "pv-manifest" (guaranteed join, priority)
      Fetches the detail page of each consultation behind the 400 already-owned
      PVs, keyed by refConsultation + orgAcronyme taken from the PV manifest.
      Join rate is 100% by construction, and this is the ONLY way to reach 2023.
      date_mise_ligne is absent from detail pages, so `annee` comes from the PV
      publication date and is tagged annee_source="pv".

  PASS B — "listing" (context corpus)
      Walks the consultations search per categorie (1=Travaux, 2=Fournitures,
      3=Services) with a per-category, per-year quota. Supplies the real
      date_mise_ligne ("Publié le" column) and per-buyer denominators.

Structural limit — do not try to widen this away: the search listing only keeps
a ~2-year sliding window (~sept. 2024 onward). Consultations from 2023 and early
2024 are simply not in the listing, though their detail pages remain reachable
by direct URL — which is exactly what Pass A exploits. A full listing crawl of
2023-2026 would be ~100 541 detail pages (~56 h at the configured rate limit).

Listing results are sorted by *date limite de remise des plis* descending, not
by publication date, and the publication→deadline gap reaches 151 days, so
pagination stops only once a whole page falls 180 days past the window.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from scraper.pmmp.parsers.consultation_parser import (
    normalize_reference,
    parse_detail_page,
    parse_listing_rows,
)
from scraper.pmmp.utils.downloader import PMPPDownloader
from scraper.pmmp.utils.prado import PradoSearch

log = logging.getLogger(__name__)

BASE = "https://www.marchespublics.gov.ma/index.php"
CONSULTATIONS_ENTRY = f"{BASE}?page=entreprise.EntrepriseAdvancedSearch&AllCons"
DETAIL_URL = (f"{BASE}?page=entreprise.EntrepriseDetailConsultation"
              "&refConsultation={ref}&orgAcronyme={org}")

RAW_DIR = Path("data/raw/consultations")
CATEGORIES = {"1": "Travaux", "2": "Fournitures", "3": "Services"}
LISTING_SAFETY_MARGIN_DAYS = 180

RECORD_ORDER = [
    "reference", "objet", "acheteur_public", "type_annonce", "mode_passation",
    "categorie_principale", "lieu_execution", "estimation_dhs_ttc",
    "caution_provisoire", "qualifications", "domaines_activite",
    "allotissement", "reserve_tpe_pme", "date_mise_ligne",
    "date_limite_remise_plis", "lieu_ouverture_plis", "dossier_consultation_url",
    # traceability
    "refConsultation", "orgAcronyme", "source", "annee", "annee_source",
    "is_publicly_downloadable", "source_url", "scraped_at", "extras",
]


def detail_url(ref: str, org: str) -> str:
    return DETAIL_URL.format(ref=ref, org=org)


# --------------------------------------------------------------------------- #
# PV manifest
# --------------------------------------------------------------------------- #

def load_pv_index(manifest_path: Path) -> dict[str, Any]:
    """Read the PV manifest into join keys + the Pass A work list.

    Every PV carries refConsultation and orgAcronyme inside its download URL,
    which is what makes the Pass A join exact rather than name-based.
    """
    import re

    targets: dict[str, dict[str, Any]] = {}
    textual: set[str] = set()
    skipped = 0

    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        url = rec.get("pdf_url", "")
        ref_m = re.search(r"refConsultation=(\d+)", url)
        org_m = re.search(r"orgAcronyme=([^&]+)", url)
        if not (ref_m and org_m):
            skipped += 1
            continue
        norm = normalize_reference(rec.get("reference"))
        if norm:
            textual.add(norm)
        targets.setdefault(ref_m.group(1), {
            "refConsultation": ref_m.group(1),
            "orgAcronyme": org_m.group(1),
            "annee": rec.get("year"),
            "reference_pv": rec.get("reference"),
        })

    return {"targets": targets, "ids": set(targets), "references": textual,
            "skipped": skipped}


# --------------------------------------------------------------------------- #
# spider
# --------------------------------------------------------------------------- #

class ConsultationsSpider:
    """Collects consultation records through either pass, into one JSONL file."""

    def __init__(self, downloader: PMPPDownloader | None = None,
                 out_dir: Path = RAW_DIR, out_path: Path | None = None):
        self.dl = downloader or PMPPDownloader()
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.out_path = Path(out_path) if out_path else self.out_dir / f"consultations_{stamp}.jsonl"
        self.checkpoint_path = self.out_dir / "listing_checkpoint.json"
        self._fh = None
        self.records: list[dict[str, Any]] = []
        self.errors: list[dict[str, str]] = []
        self.seen: set[str] = set()

    # -- plumbing ---------------------------------------------------------- #

    def _out(self):
        if self._fh is None:
            self._fh = self.out_path.open("a", encoding="utf-8")
        return self._fh

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "ConsultationsSpider":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def preload(self, path: Path | None = None) -> int:
        """Re-adopt an earlier run's output so a resumed run reports on the whole
        collection, not just the records gathered since the interruption.

        Also seeds `seen`, so an interrupted page is not re-fetched.
        """
        path = Path(path) if path else self.out_path
        if not path.exists():
            return 0
        loaded = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            ref = record.get("refConsultation")
            if ref and str(ref) in self.seen:
                continue
            if ref:
                self.seen.add(str(ref))
            self.records.append(record)
            loaded += 1
        if loaded:
            log.info("preloaded %d records already in %s", loaded, path)
        return loaded

    def _write(self, record: dict[str, Any]) -> None:
        ordered = {k: record.get(k) for k in RECORD_ORDER}
        for key, value in record.items():         # keep anything unexpected
            ordered.setdefault(key, value)
        self._out().write(json.dumps(ordered, ensure_ascii=False) + "\n")
        self._out().flush()
        self.records.append(ordered)

    def fetch_detail(self, ref: str, org: str, *, source: str,
                     annee: int | None, annee_source: str,
                     overrides: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Fetch + parse one consultation. Errors are logged, never raised."""
        if ref in self.seen:
            return None
        url = detail_url(ref, org)
        try:
            html = self.dl.get(url).text
        except Exception as e:                      # noqa: BLE001 - per-item isolation
            log.warning("ERR  fetch refConsultation=%s (%s): %s", ref, org, e)
            self.errors.append({"refConsultation": ref, "stage": "fetch", "error": str(e)})
            return None
        try:
            record = parse_detail_page(html, source_url=url)
        except Exception as e:                      # noqa: BLE001
            log.warning("ERR  parse refConsultation=%s (%s): %s", ref, org, e)
            self.errors.append({"refConsultation": ref, "stage": "parse", "error": str(e)})
            return None

        record.update({
            "refConsultation": ref,
            "orgAcronyme": org,
            "source": source,
            "annee": annee,
            "annee_source": annee_source,
            "scraped_at": datetime.now().isoformat(timespec="seconds"),
        })
        if overrides:
            record.update({k: v for k, v in overrides.items() if v is not None})

        self.seen.add(ref)
        self._write(record)
        return record

    # -- PASS A ------------------------------------------------------------- #

    def run_pv_manifest(self, manifest_path: Path, limit: int | None = None) -> dict[str, Any]:
        """Fetch the consultation behind each PV. 100% join by construction."""
        index = load_pv_index(Path(manifest_path))
        targets = list(index["targets"].values())
        if limit:
            targets = targets[:limit]

        log.info("PASS A — %d consultations from PV manifest (%s)",
                 len(targets), manifest_path)
        if index["skipped"]:
            log.warning("PASS A — %d manifest lines unusable (no refConsultation)",
                        index["skipped"])

        per_year: Counter = Counter()
        ok = 0
        for i, target in enumerate(targets, 1):
            record = self.fetch_detail(
                target["refConsultation"], target["orgAcronyme"],
                source="pv_manifest",
                annee=target["annee"],
                annee_source="pv",
                # date_mise_ligne is not published on detail pages — see module docstring
                overrides={"reference_pv": target["reference_pv"]},
            )
            if record is None:
                continue
            ok += 1
            per_year[target["annee"]] += 1
            if i % 25 == 0 or i == len(targets):
                log.info("PASS A   %d/%d collected (%d ok)", i, len(targets), ok)

        log.info("PASS A done — %d collected, per year: %s",
                 ok, dict(sorted(per_year.items(), key=lambda kv: str(kv[0]))))
        return {"collected": ok, "per_year": dict(per_year), "index": index}

    # -- PASS B ------------------------------------------------------------- #

    def run_listing(self, categories: Iterable[str] = ("1", "2", "3"),
                    years: Iterable[int] = (2024, 2025, 2026),
                    per_year: int = 150, page_size: int = 500,
                    max_pages: int = 200, resume: bool = False) -> dict[str, Any]:
        """Walk the search listing per categorie, with a per-year quota."""
        years = sorted(set(int(y) for y in years))
        stop_before = date(min(years), 1, 1) - timedelta(days=LISTING_SAFETY_MARGIN_DAYS)
        checkpoint = self._load_checkpoint() if resume else {}
        counts: dict[str, Counter] = defaultdict(Counter)

        log.info("PASS B — categories=%s years=%s quota=%d/cat/year",
                 list(categories), years, per_year)
        log.info("PASS B — listing covers ~sept. 2024 onward only; 2023 is "
                 "structurally unreachable here (Pass A covers it)")
        log.info("PASS B — pagination stops past %s (180-day safety margin on "
                 "the deadline sort key)", stop_before.isoformat())

        for categorie in categories:
            label = CATEGORIES.get(categorie, categorie)
            saved = checkpoint.get(categorie, {})
            for year, n in (saved.get("per_year") or {}).items():
                counts[categorie][int(year)] = int(n)
            self.seen.update(saved.get("seen", []))

            try:
                search = PradoSearch(self.dl, CONSULTATIONS_ENTRY, page_size=page_size)
                search.start({"categorie": categorie, "annonceType": "0"},
                             page_size=page_size)
            except Exception as e:                  # noqa: BLE001
                log.error("PASS B — categorie %s (%s): search failed: %s",
                          categorie, label, e)
                self.errors.append({"categorie": categorie, "stage": "search", "error": str(e)})
                continue

            total = search.total_results()
            log.info("PASS B — categorie %s (%s): %s results on portal",
                     categorie, label, total if total is not None else "?")

            page = 1
            resume_to = int(saved.get("page", 1)) if resume else 1
            while resume_to > page:
                log.info("PASS B   categorie %s: skipping to page %d/%d (resume)",
                         categorie, page + 1, resume_to)
                try:
                    search.next_page()
                except Exception as e:              # noqa: BLE001
                    log.error("PASS B   categorie %s: resume pagination failed: %s",
                              categorie, e)
                    break
                page += 1

            while page <= max_pages:
                rows = parse_listing_rows(search.html)
                if not rows:
                    log.info("PASS B   categorie %s: empty page %d — stopping",
                             categorie, page)
                    break

                deadlines = [date.fromisoformat(r["date_limite_remise_plis"])
                             for r in rows if r.get("date_limite_remise_plis")]
                if deadlines and max(deadlines) < stop_before:
                    log.info("PASS B   categorie %s: page %d past the window "
                             "(latest deadline %s) — stopping",
                             categorie, page, max(deadlines).isoformat())
                    break

                kept = self._harvest_page(rows, categorie, years, per_year, counts)
                log.info("PASS B   categorie %s page %d: %d rows, %d kept, quotas %s",
                         categorie, page, len(rows), kept,
                         {y: counts[categorie][y] for y in years})
                self._save_checkpoint(checkpoint, categorie, page, counts[categorie])

                if all(counts[categorie][y] >= per_year for y in years):
                    log.info("PASS B   categorie %s: all quotas filled — stopping",
                             categorie)
                    break

                try:
                    search.next_page()
                except Exception as e:              # noqa: BLE001
                    log.error("PASS B   categorie %s: pagination failed on page "
                              "%d: %s", categorie, page, e)
                    self.errors.append({"categorie": categorie, "stage": "pagination",
                                        "error": str(e)})
                    break
                page += 1

            self._report_quota_shortfall(categorie, label, years, per_year, counts)

        return {"per_category": {c: dict(v) for c, v in counts.items()}}

    def _harvest_page(self, rows: list[dict[str, Any]], categorie: str,
                      years: list[int], per_year: int,
                      counts: dict[str, Counter]) -> int:
        kept = 0
        for row in rows:
            published = row.get("date_mise_ligne")
            if not published:
                continue
            year = int(published[:4])
            if year not in years or counts[categorie][year] >= per_year:
                continue
            if row["refConsultation"] in self.seen:
                continue
            record = self.fetch_detail(
                row["refConsultation"], row["orgAcronyme"],
                source="listing",
                annee=year,
                annee_source="listing",
                overrides={
                    "date_mise_ligne": published,
                    # listing values only fill gaps; the detail page wins
                    "date_limite_remise_plis": row.get("date_limite_remise_plis"),
                    "reference": row.get("reference"),
                },
            )
            if record is not None:
                counts[categorie][year] += 1
                kept += 1
        return kept

    def _report_quota_shortfall(self, categorie: str, label: str, years: list[int],
                                per_year: int, counts: dict[str, Counter]) -> None:
        short = {y: counts[categorie][y] for y in years if counts[categorie][y] < per_year}
        if short:
            log.warning("PASS B — categorie %s (%s): quota not reachable for %s "
                        "(expected on 2024, the listing window is partial) — "
                        "collected what exists, not an error",
                        categorie, label,
                        ", ".join(f"{y}: {n}/{per_year}" for y, n in short.items()))

    # -- checkpoint --------------------------------------------------------- #

    def _load_checkpoint(self) -> dict[str, Any]:
        if not self.checkpoint_path.exists():
            return {}
        try:
            return json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("checkpoint unreadable — starting fresh")
            return {}

    def _save_checkpoint(self, checkpoint: dict[str, Any], categorie: str,
                         page: int, per_year: Counter) -> None:
        checkpoint[categorie] = {
            "page": page,
            "per_year": {str(k): v for k, v in per_year.items()},
            "seen": sorted(self.seen),
        }
        self.checkpoint_path.write_text(
            json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")

    # -- report ------------------------------------------------------------- #

    def report(self, pv_index: dict[str, Any] | None = None) -> str:
        """Join rate per pass AND per categorie, plus collection counts."""
        ids = (pv_index or {}).get("ids", set())
        refs = (pv_index or {}).get("references", set())
        lines: list[str] = []

        lines.append(f"Consultations collected : {len(self.records)}")
        lines.append(f"Errors (non fatal)      : {len(self.errors)}")
        lines.append(f"Output                  : {self.out_path}")

        by_source: dict[str, list[dict]] = defaultdict(list)
        for rec in self.records:
            by_source[rec.get("source") or "?"].append(rec)

        for source in sorted(by_source):
            group = by_source[source]
            pass_name = {"pv_manifest": "PASS A (pv-manifest)",
                         "listing": "PASS B (listing)"}.get(source, source)
            lines.append("")
            lines.append(f"=== {pass_name} — {len(group)} consultations ===")
            if not ids:
                lines.append("  (no PV manifest loaded — join rate unavailable)")

            lines.append(f"  {'categorie':<14}{'n':>5}{'join id':>12}{'join ref':>12}")
            per_cat: dict[str, list[dict]] = defaultdict(list)
            for rec in group:
                per_cat[rec.get("categorie_principale") or "?"].append(rec)

            for categorie in sorted(per_cat):
                items = per_cat[categorie]
                by_id = sum(1 for r in items if str(r.get("refConsultation")) in ids)
                by_ref = sum(1 for r in items
                             if normalize_reference(r.get("reference")) in refs)
                lines.append(f"  {categorie:<14}{len(items):>5}"
                             f"{self._pct(by_id, len(items)):>12}"
                             f"{self._pct(by_ref, len(items)):>12}")

            by_id = sum(1 for r in group if str(r.get("refConsultation")) in ids)
            by_ref = sum(1 for r in group
                         if normalize_reference(r.get("reference")) in refs)
            lines.append(f"  {'TOTAL':<14}{len(group):>5}"
                         f"{self._pct(by_id, len(group)):>12}"
                         f"{self._pct(by_ref, len(group)):>12}")

            years = Counter(r.get("annee") for r in group)
            lines.append(f"  per year: {dict(sorted(years.items(), key=lambda kv: str(kv[0])))}")

        return "\n".join(lines)

    @staticmethod
    def _pct(n: int, total: int) -> str:
        return f"{n} ({n / total * 100:.0f}%)" if total else "-"
