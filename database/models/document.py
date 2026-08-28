"""
Document — one source PDF/PV file, tracked through the OCR pipeline.

`doc_id` (the file's SHA-256 hash, called `file_hash` in the scraping
manifest) is the true identity of a file on disk and the join key back to
`data/processed/ocr/<doc_id>.txt` and `data/processed/extracted/<doc_id>.json`
— distinct from `ref_consultation`, which identifies the *market*, not the
*file*. Kept as its own table rather than folded into Procurement because a
Document can exist with no resolved `ref_consultation` (an isolated PDF with
no source URL, data_dictionary.md §1 — the composite-key fallback case) and,
symmetrically, a Procurement can have zero Documents (no PV published yet).
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base

if TYPE_CHECKING:
    from database.models.procurement import Procurement


class OcrStatus(str, enum.Enum):
    """Confirmed enum, Issue 5/6 (ocr/pdf_to_image.py, methodology.md).

    Les quatre premieres valeurs viennent du pipeline OCR lui-meme. EXCLUDED
    est un cinquieme etat, ajoute le 28/08/2026 : il ne decrit pas un
    resultat d'OCR mais une decision humaine de ne pas traiter le fichier
    (scripts/run_ocr.py::EXCLUDED_STEMS). Avant, ces documents restaient a
    NULL en base — indistinguables d'un document simplement pas encore
    traite. Un statut absent ne doit jamais servir a exprimer une exclusion
    deliberee : la decision doit se lire dans la donnee, pas dans son trou.
    """
    NATIVE = "native"
    OCR_SUCCESS = "ocr_success"
    OCR_LOW_CONFIDENCE = "ocr_low_confidence"
    OCR_FAILED = "ocr_failed"
    EXCLUDED = "excluded"


class JoinStatus(str, enum.Enum):
    """Why `procurement_id` is set or not — distinct from OcrStatus, and
    always set at insertion time (never itself ambiguous), because a null
    `procurement_id` alone conflates two very different situations:

      * RESOLVED — ref_consultation extracted and matched a Procurement.
        Measured 400/400 on the Pass A manifest sample (data_dictionary.md
        §1) — currently the near-universal case, but not guaranteed to stay
        that way once Issue 8 processes the wider Pass B corpus.
      * NO_REF_CONSULTATION — the document carries no extractable
        ref_consultation at all (data_dictionary.md §1's documented
        fallback case: an isolated PDF with no source URL). The join was
        never attempted, by construction — not a failure to investigate.
      * REF_CONSULTATION_NOT_FOUND — a ref_consultation WAS extracted but
        matched no known Procurement row. The join was attempted and
        failed — a genuine anomaly worth investigating (missing scrape,
        data inconsistency), never to be silently treated the same as
        NO_REF_CONSULTATION.

    0 real REF_CONSULTATION_NOT_FOUND instances exist in the current 400-
    document sample (same 100% figure as above) — this value exists for
    the wider corpus this insertion script will eventually process, not
    because a live example has been observed yet.
    """
    RESOLVED = "resolved"
    NO_REF_CONSULTATION = "no_ref_consultation"
    REF_CONSULTATION_NOT_FOUND = "ref_consultation_not_found"


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("doc_id", name="uq_document_doc_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)

    doc_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    # Nullable: a Document's Procurement is not always resolvable — never
    # enforce NOT NULL here, that would silently drop legitimate isolated-
    # PDF documents at insertion time. `join_status` records WHY whenever
    # this is null, so that distinction survives being written to the
    # database instead of collapsing into a single ambiguous NULL — see
    # JoinStatus above.
    procurement_id: Mapped[int | None] = mapped_column(ForeignKey("procurements.id"), index=True)
    ref_consultation: Mapped[str | None] = mapped_column(String(32), index=True)
    join_status: Mapped[JoinStatus] = mapped_column(
        Enum(JoinStatus, name="join_status"), nullable=False)

    local_path: Mapped[str | None] = mapped_column(String(512))
    pdf_url: Mapped[str | None] = mapped_column(String(512))
    year: Mapped[int | None] = mapped_column(Integer)
    scraped_at: Mapped[datetime | None] = mapped_column(DateTime)

    # None until the OCR pipeline has actually run on this file — distinct
    # from every OcrStatus value, which all mean "a decision was taken"
    # (four results + EXCLUDED, a deliberate non-treatment).
    ocr_status: Mapped[OcrStatus | None] = mapped_column(Enum(OcrStatus, name="ocr_status"))

    # Rempli uniquement quand ocr_status vaut EXCLUDED : la raison lue dans
    # scripts/run_ocr.py, pour que l'exclusion soit auditable depuis la base
    # sans avoir a rouvrir le code ou methodology.md Sec 1.5.
    ocr_excluded_reason: Mapped[str | None] = mapped_column(String(255))

    procurement: Mapped["Procurement | None"] = relationship(back_populates="documents")
