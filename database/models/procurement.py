"""
Procurement (Consultation) — data_dictionary.md §2.

Sourced from the HTML consultation detail page, no OCR involved. Confirmed
100% join reliability via `ref_consultation` (400/400 during the Issue 5/6
collection) — `reference` alone is NOT a key (data_dictionary.md §1: the
same reference commonly names 4+ unrelated markets across different
buyers) and must never be used as one, only as a display attribute.

`awards` is 0-to-MANY, not 0-to-1 — confirmed on the extracted corpus: 357
documents produce exactly 1 Award, but 19 produce 2, 5 produce 3, up to one
document producing 9 (multi-lot PVs, one Award per lot). A Procurement with
zero Awards is not an edge case here — it is the current majority state:
~1350 of 1750 scraped consultations (Pass B) have no PV published yet, on
top of the 2 documents excluded from OCR entirely (data_dictionary.md §3.5).
Both are the same situation from this model's point of view and need no
special-casing.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base

if TYPE_CHECKING:
    from database.models.award import Award
    from database.models.document import Document


class CategoriePrincipale(str, enum.Enum):
    """Enum ferme confirme (data_dictionary.md §2) — seulement 3 valeurs observees."""
    TRAVAUX = "Travaux"
    FOURNITURES = "Fournitures"
    SERVICES = "Services"


class Procurement(Base):
    __tablename__ = "procurements"
    __table_args__ = (UniqueConstraint("ref_consultation", name="uq_procurement_ref_consultation"),)

    id: Mapped[int] = mapped_column(primary_key=True)

    # Cle de jointure fiable — data_dictionary.md §1. Indexee, unique, pas
    # nullable : c'est la seule cle sur laquelle on peut se reposer.
    ref_consultation: Mapped[str] = mapped_column(String(32), index=True, nullable=False)

    # Attribut d'affichage uniquement — jamais une cle (voir docstring).
    reference: Mapped[str | None] = mapped_column(String(64))

    objet: Mapped[str | None] = mapped_column(Text)
    acheteur_public: Mapped[str | None] = mapped_column(String(255), index=True)

    # ~20 valeurs mesurees pour mode_passation, jamais toutes enumerees a ce
    # stade — String plutot qu'un Enum Python premature. Meme raisonnement
    # pour type_annonce.
    type_annonce: Mapped[str | None] = mapped_column(String(64))
    mode_passation: Mapped[str | None] = mapped_column(String(64))

    categorie_principale: Mapped[CategoriePrincipale | None] = mapped_column(
        Enum(CategoriePrincipale, name="categorie_principale"))

    lieu_execution: Mapped[str | None] = mapped_column(String(128))
    estimation_dhs_ttc: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    caution_provisoire: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    qualifications: Mapped[str | None] = mapped_column(Text)
    domaines_activite: Mapped[str | None] = mapped_column(Text)
    allotissement: Mapped[bool | None] = mapped_column(Boolean)
    reserve_tpe_pme: Mapped[bool | None] = mapped_column(Boolean)
    date_mise_ligne: Mapped[datetime | None] = mapped_column(DateTime)
    date_limite_remise_plis: Mapped[datetime | None] = mapped_column(DateTime)
    lieu_ouverture_plis: Mapped[str | None] = mapped_column(String(255))
    dossier_consultation_url: Mapped[str | None] = mapped_column(String(512))

    # Forward refs as strings, resolved by SQLAlchemy's mapper registry once
    # every model module has been imported (see database/models/__init__.py)
    # — no direct import of Award/Document needed here, which would create
    # an import cycle (award.py imports Procurement back).
    awards: Mapped[list["Award"]] = relationship(back_populates="procurement")
    documents: Mapped[list["Document"]] = relationship(back_populates="procurement")
