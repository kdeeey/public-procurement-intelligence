"""
Award — one lot's attribution record, from extraction/extractor.py's output
(data_dictionary.md §3.1/§3.2/§3.3).

One Procurement produces 0-to-MANY Awards, one per lot (see procurement.py's
docstring — up to 9 confirmed on the real corpus). `statut` is inferred
per-lot, never per-document (the confirmed 349e44bf trap: lot 1 ATTRIBUE,
lots 2-3 INFRUCTUEUX on the same PV — a document-level read would invert it).
"""

from __future__ import annotations

import enum
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    ARRAY, Date, Enum, ForeignKey, Integer, JSON, Numeric, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base
from database.models.company import award_companies

if TYPE_CHECKING:
    from database.models.company import Company
    from database.models.procurement import Procurement


class Statut(str, enum.Enum):
    """Enum ferme, data_dictionary.md §3.3 — 3 valeurs, jamais un booleen
    gagne/perdu (au moins 3 statuts distincts observes en pratique)."""
    ATTRIBUE = "ATTRIBUE"
    INFRUCTUEUX = "INFRUCTUEUX"
    OFFRE_EXCESSIVE = "OFFRE_EXCESSIVE"


class MontantBaseAffichee(str, enum.Enum):
    HT = "HT"
    TTC = "TTC"


class Award(Base):
    __tablename__ = "awards"

    id: Mapped[int] = mapped_column(primary_key=True)

    procurement_id: Mapped[int | None] = mapped_column(
        ForeignKey("procurements.id"), index=True)
    # Duplique procurement.ref_consultation ici a dessein — README §55 /
    # data_dictionary.md §1 : la tracabilite doit survivre meme si le join
    # applicatif n'est pas fait, pas seulement via la FK.
    ref_consultation: Mapped[str | None] = mapped_column(String(32), index=True)
    doc_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    # Nullable — present seulement si Procurement.allotissement = Oui
    # (data_dictionary.md §3.1).
    lot_numero: Mapped[int | None] = mapped_column(Integer)

    # Attribut d'affichage, jamais une cle (data_dictionary.md §3.1, meme
    # regle que Procurement.reference).
    reference: Mapped[str | None] = mapped_column(String(64))

    objet: Mapped[str | None] = mapped_column(Text)
    acheteur_public: Mapped[str | None] = mapped_column(String(255))
    date_ouverture_plis: Mapped[date | None] = mapped_column(Date)
    date_achevement_travaux_commission: Mapped[date | None] = mapped_column(Date)

    # Texte brut tel qu'imprime — "jamais deduit par calcul, toujours lu
    # explicitement" (data_dictionary.md §3.1). La resolution vers Company
    # (normalisation, Issue 8) vit dans le lien many-to-many `companies` ci-
    # dessous, pas dans ce champ, qui reste la source de verite textuelle.
    concurrent_retenu: Mapped[str | None] = mapped_column(Text)

    # Colonnes independantes et nullables, JAMAIS l'une deduite de l'autre
    # par un taux de TVA suppose (data_dictionary.md §3.6, decision
    # explicitement validee) — aucun default, aucun server_default, aucune
    # contrainte CHECK reliant les deux.
    montant_ht: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    montant_ttc: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    montant_base_affichee: Mapped[MontantBaseAffichee | None] = mapped_column(
        Enum(MontantBaseAffichee, name="montant_base_affichee"))

    statut: Mapped[Statut] = mapped_column(Enum(Statut, name="statut"), nullable=False)

    delai_execution: Mapped[str | None] = mapped_column(String(64))
    president_commission: Mapped[str | None] = mapped_column(String(255))
    lieu_ouverture_plis: Mapped[str | None] = mapped_column(String(255))
    justification_choix: Mapped[str | None] = mapped_column(Text)

    # PV riche uniquement (§3.2) — extraits par decision explicite du plan
    # Issue 7 mais NON VALIDES contre une verite terrain (aucun champ
    # equivalent dans ground_truth.json). A ne jamais presenter comme aussi
    # fiables que les champs mesures ci-dessus.
    #
    # .with_variant(JSON, "sqlite") : le type reste ARRAY (TEXT[]) sur
    # PostgreSQL, la cible reelle — la variante SQLite existe uniquement
    # pour que database/crud/ soit testable en local sans Docker (le daemon
    # n'etait pas disponible dans cet environnement au moment d'ecrire ce
    # module), jamais utilisee en production.
    liste_concurrents: Mapped[list[str] | None] = mapped_column(ARRAY(Text).with_variant(JSON, "sqlite"))
    concurrents_ecartes: Mapped[list[str] | None] = mapped_column(ARRAY(Text).with_variant(JSON, "sqlite"))
    montant_par_concurrent: Mapped[dict | None] = mapped_column(JSON)
    classement: Mapped[dict | None] = mapped_column(JSON)

    # Tracabilite/confiance (Issue 8, option validee : colonnes detaillees
    # plutot qu'un booleen resume) — reprend tel quel ce qu'extraction/
    # lots.py calcule deja (LotSegment.detection / .warnings), jamais
    # recalcule ici.
    lot_detection: Mapped[str | None] = mapped_column(String(32))
    extraction_warnings: Mapped[list[str] | None] = mapped_column(ARRAY(Text).with_variant(JSON, "sqlite"))

    procurement: Mapped["Procurement | None"] = relationship(back_populates="awards")
    companies: Mapped[list["Company"]] = relationship(
        secondary=award_companies, back_populates="awards")
