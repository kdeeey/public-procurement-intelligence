"""
Orchestration: one document's cleaned OCR text -> one Award per lot (Issue 7).

Combines extraction.lots (per-lot segmentation) with extraction.fields
(per-field extractors), applied to each lot's own text slice so that
concurrent_retenu / montants / statut are read from the segment that
actually concerns that lot, not from the whole document indiscriminately —
this is what makes the confirmed trap document (349e44bf..., lot 1 ATTRIBUE,
lots 2-3 INFRUCTUEUX) resolve correctly instead of collapsing to one status.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from extraction.fields import (
    extract_concurrents,
    extract_concurrent_retenu,
    extract_dates,
    extract_montants,
    extract_reference,
    extract_statut,
)
from extraction.lots import LotSegment, segment_lots


@dataclass
class Award:
    """One lot's worth of attribution data (data_dictionary.md §3.1/§3.2).

    `refConsultation` is intentionally absent — it comes from the scraping
    manifest, not from OCR'd text, and is attached by the caller (Issue 8),
    not derived here.
    """
    doc_id: str
    lot_numero: int | None
    reference: str | None
    concurrent_retenu: str | None
    montant_ht: float | None
    montant_ttc: float | None
    montant_base_affichee: str | None
    date_ouverture_plis: str | None
    date_achevement_commission: str | None
    statut: str
    liste_concurrents: list[str] = field(default_factory=list)
    concurrents_ecartes: list[str] = field(default_factory=list)

    # Traceability, not part of the data_dictionary schema itself: which
    # segmentation rule produced this lot, and any caveat worth surfacing
    # (address false-positive filtered, lot number deduced by complement,
    # multi-lot inferred from numbering alone with no explicit confirmation).
    detection: str = "mono_sans_numero"
    warnings: list[str] = field(default_factory=list)


def _award_from_segment(doc_id: str, segment: LotSegment) -> Award:
    dates = extract_dates(segment.text)
    concurrent_retenu = extract_concurrent_retenu(segment.text)
    montants = extract_montants(segment.text)
    concurrents = extract_concurrents(segment.text)

    return Award(
        doc_id=doc_id,
        lot_numero=segment.numero,
        reference=extract_reference(segment.text),
        concurrent_retenu=concurrent_retenu,
        montant_ht=montants.montant_ht,
        montant_ttc=montants.montant_ttc,
        montant_base_affichee=montants.montant_base_affichee,
        date_ouverture_plis=dates["date_ouverture_plis"],
        date_achevement_commission=dates["date_achevement_commission"],
        statut=extract_statut(segment.text, segment.declared_infructueux,
                              concurrent_retenu),
        liste_concurrents=concurrents.liste_concurrents,
        concurrents_ecartes=concurrents.concurrents_ecartes,
        detection=segment.detection,
        warnings=list(segment.warnings),
    )


def extract_document(doc_id: str, text: str) -> list[Award]:
    """One Award per lot. Always at least one — segment_lots() guarantees
    that, so this function never returns an empty list for non-empty text."""
    return [_award_from_segment(doc_id, segment) for segment in segment_lots(text)]
