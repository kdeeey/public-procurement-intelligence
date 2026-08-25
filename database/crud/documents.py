"""
Load Document rows from the PV manifest (data/samples/PVs/manifest.jsonl).

`ref_consultation` is not a native field in this manifest — it is embedded
in `pdf_url` ("...&refConsultation=1034020&orgAcronyme=..."), the same
convention scripts/enrich_pv_manifest.py already relies on
(detail_url_from()). Extracted here with the identical regex rather than a
new one, so the two never silently disagree on what counts as "found".
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from database.models import Document, JoinStatus, OcrStatus, Procurement

REF_CONSULTATION_RE = re.compile(r"refConsultation=(\d+)")
OCR_DIR = Path("data/processed/ocr")


def _read_ocr_status(doc_id: str) -> OcrStatus | None:
    """data/processed/ocr/<doc_id>.json's own "ocr_status" field (Issue 5/6,
    ocr/pdf_to_image.py) — None both when OCR was never run on this file
    (EXCLUDED_STEMS, data_dictionary.md §3.5) and when the sidecar is simply
    absent; those two cases are not distinguished here, only surfaced as
    "we don't have a status" either way."""
    sidecar = OCR_DIR / f"{doc_id}.json"
    if not sidecar.exists():
        return None
    try:
        raw = json.loads(sidecar.read_text(encoding="utf-8")).get("ocr_status")
        return OcrStatus(raw) if raw else None
    except (ValueError, json.JSONDecodeError):
        return None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def load_documents(session: Session, manifest_path: Path) -> dict[str, int]:
    """Insere ou met a jour un Document par doc_id (file_hash).

    join_status distingue explicitement "jamais tente" de "tente et
    echoue" (voir database/models/document.py::JoinStatus) plutot que de
    laisser un procurement_id NULL parler de lui-meme.

    Le manifeste contient des doc_id (file_hash) dupliques — 9 sur 400
    lignes mesures reellement (8 avec 2 occurrences, 1 avec 3), le meme
    fichier ayant ete re-scrape sans dedup en amont. Les compteurs
    retournes comptent des LIGNES Document finales en base (une par
    doc_id distinct, dernier ecrit gagnant), jamais des evenements de
    ligne manifeste traitee — sinon "resolved" compterait 400 la ou la
    base n'a que 390 lignes, une contradiction confirmee lors de la revue
    de ce module.
    """
    # doc_id -> statut retenu pour CETTE ligne ; la derniere ligne du
    # manifeste pour un doc_id donne gagne, comme pour les autres colonnes.
    final_status: dict[str, JoinStatus] = {}
    inserted = updated = 0

    with manifest_path.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            doc_id = rec.get("file_hash")
            if not doc_id:
                continue

            match = REF_CONSULTATION_RE.search(rec.get("pdf_url") or "")
            ref_consultation = match.group(1) if match else None

            procurement = None
            if ref_consultation is None:
                join_status = JoinStatus.NO_REF_CONSULTATION
            else:
                procurement = session.query(Procurement).filter_by(
                    ref_consultation=ref_consultation).one_or_none()
                join_status = (JoinStatus.RESOLVED if procurement
                               else JoinStatus.REF_CONSULTATION_NOT_FOUND)
            final_status[doc_id] = join_status

            existing = session.query(Document).filter_by(doc_id=doc_id).one_or_none()
            target = existing or Document(doc_id=doc_id)

            target.procurement_id = procurement.id if procurement else None
            target.ref_consultation = ref_consultation
            target.join_status = join_status
            target.local_path = rec.get("local_path")
            target.pdf_url = rec.get("pdf_url")
            target.year = rec.get("year")
            target.scraped_at = _parse_date(rec.get("scraped_at"))
            target.ocr_status = _read_ocr_status(doc_id)

            if not existing:
                session.add(target)
                inserted += 1
            else:
                updated += 1

    session.flush()

    status_counts = {"resolved": 0, "no_ref_consultation": 0, "ref_consultation_not_found": 0}
    for status in final_status.values():
        status_counts[status.value] += 1

    return {
        "manifest_lines": inserted + updated,   # lignes lues, avant dedup
        "document_rows": len(final_status),     # lignes Document reelles en base
        "inserted": inserted,
        "updated": updated,
        **status_counts,                        # comptes par join_status, sur document_rows
    }
