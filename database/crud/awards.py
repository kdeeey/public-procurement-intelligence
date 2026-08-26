"""
Load Award rows from data/processed/extracted/<doc_id>.json (Issue 7's
output — extraction/extractor.py's Award dataclass, one entry per lot).

A Document must already exist (database/crud/documents.py run first) for
this Award's `procurement_id`/`ref_consultation` to resolve — an Award
whose doc_id has no matching Document is inserted anyway (doc_id is always
known, extraction ran on the file regardless of the Procurement join
outcome), just with both left None, exactly like Document's own
NO_REF_CONSULTATION/REF_CONSULTATION_NOT_FOUND cases.

Fields the schema has but extraction/fields.py never populates
(acheteur_public, objet, delai_execution, president_commission,
lieu_ouverture_plis, justification_choix, montant_par_concurrent,
classement) are left None here rather than fabricated — Issue 7's own
report already lists these as not implemented / not validated.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from database.crud.companies import resolve_companies
from database.models import Award, Document, MontantBaseAffichee, Statut


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d/%m/%Y").date()
    except ValueError:
        return None


def _parse_decimal(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def load_awards(session: Session, extracted_dir: Path) -> dict[str, int]:
    counts = {"inserted": 0, "updated": 0, "no_matching_document": 0,
              "companies_linked": 0}

    for path in sorted(extracted_dir.glob("*.json")):
        doc_id = path.stem
        awards_raw = json.loads(path.read_text(encoding="utf-8"))

        document = session.query(Document).filter_by(doc_id=doc_id).one_or_none()
        if document is None:
            counts["no_matching_document"] += 1
        procurement_id = document.procurement_id if document else None
        ref_consultation = document.ref_consultation if document else None

        for raw in awards_raw:
            existing = session.query(Award).filter_by(
                doc_id=doc_id, lot_numero=raw.get("lot_numero")).one_or_none()
            target = existing or Award(doc_id=doc_id, lot_numero=raw.get("lot_numero"))

            target.procurement_id = procurement_id
            target.ref_consultation = ref_consultation
            target.reference = raw.get("reference")
            target.concurrent_retenu = raw.get("concurrent_retenu")
            target.montant_ht = _parse_decimal(raw.get("montant_ht"))
            target.montant_ttc = _parse_decimal(raw.get("montant_ttc"))
            base = raw.get("montant_base_affichee")
            target.montant_base_affichee = MontantBaseAffichee(base) if base else None
            target.date_ouverture_plis = _parse_date(raw.get("date_ouverture_plis"))
            target.date_achevement_travaux_commission = _parse_date(
                raw.get("date_achevement_commission"))
            target.statut = Statut(raw["statut"])
            target.liste_concurrents = raw.get("liste_concurrents") or None
            target.concurrents_ecartes = raw.get("concurrents_ecartes") or None
            target.lot_detection = raw.get("detection")
            target.extraction_warnings = raw.get("warnings") or None

            target.companies = resolve_companies(session, raw.get("concurrent_retenu"))
            counts["companies_linked"] += len(target.companies)

            if not existing:
                session.add(target)
                counts["inserted"] += 1
            else:
                counts["updated"] += 1

    session.flush()
    return counts
