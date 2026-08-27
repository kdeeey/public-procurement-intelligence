"""Pydantic response models. Read-only API — no request/input models for
mutating data, only query parameters (pagination) on the router side."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

RISK_DISCLAIMER = (
    "Le score de risque est un signal statistique d'orientation pour "
    "analyse humaine, jamais une preuve ou une accusation de fraude."
)


def _split_active_flags(active_flags: str) -> list[str]:
    """RiskScore.active_flags is stored as one comma-joined string
    (ai/scoring.py's format) — "aucun" means no flag active, an empty
    list here, never a 1-item list containing the literal word "aucun"."""
    if not active_flags or active_flags == "aucun":
        return []
    return [f.strip() for f in active_flags.split(",")]


class CompanySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    normalized_name: str
    final_score: float
    risk_level: str
    dominant_driver: str | None
    n_active_flags: int


class AwardSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doc_id: str
    statut: str
    montant_ht: Decimal | None
    montant_ttc: Decimal | None
    montant_base_affichee: str | None
    date_ouverture_plis: date | None
    acheteur_public: str | None
    objet: str | None


class CompanyDetail(BaseModel):
    id: int
    normalized_name: str
    final_score: float
    risk_level: str
    dominant_driver: str | None
    n_active_flags: int
    n_evaluable_flags: int
    active_flags: list[str]
    partially_evaluated: bool
    explanation: str
    awards: list[AwardSummary]


class RankingResponse(BaseModel):
    limit: int
    offset: int
    total: int
    items: list[CompanySummary]


class AwardCompany(BaseModel):
    id: int
    normalized_name: str


class AwardDetail(BaseModel):
    id: int
    doc_id: str
    ref_consultation: str | None
    statut: str
    montant_ht: Decimal | None
    montant_ttc: Decimal | None
    montant_base_affichee: str | None
    date_ouverture_plis: date | None
    acheteur_public: str | None
    objet: str | None
    concurrent_retenu: str | None
    companies: list[AwardCompany]


class StatsCounts(BaseModel):
    procurements: int
    documents: int
    awards: int
    companies: int


class StatsSummary(BaseModel):
    counts: StatsCounts
    risk_level_distribution: dict[str, int] = Field(
        description="Faible/Modere/Eleve/Critique -> nombre de Company")
    disclaimer: str = RISK_DISCLAIMER
