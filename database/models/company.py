"""
Company — deduplicated entity behind `Award.concurrent_retenu`.

`normalized_name` is the dedup key produced by normalize_company_name()
(casse/accents/prefixe "Societe"/"STE"/"La"/suffixe "SARL"/"SARL AU"
retires, ponctuation collapsee — see the Issue 8 discussion for the exact
rule and what it does and does not merge). `display_name` keeps the first
raw form seen, for readability — the normalized key is for joining/
deduplication, not for display.

Award<->Company is many-to-many, not a single nullable FK on Award: a
groupement is one winning Award backed by 2+ companies at once
(data_dictionary.md §3.1 — "jamais deduit par calcul, jamais scinde"), and
a single FK could not represent that without either dropping members or
duplicating the Award row, both wrong.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Column, ForeignKey, String, Table, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base

if TYPE_CHECKING:
    from database.models.award import Award

award_companies = Table(
    "award_companies",
    Base.metadata,
    Column("award_id", ForeignKey("awards.id"), primary_key=True),
    Column("company_id", ForeignKey("companies.id"), primary_key=True),
)


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("normalized_name", name="uq_company_normalized_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    normalized_name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)

    awards: Mapped[list["Award"]] = relationship(
        secondary=award_companies, back_populates="companies")
