"""Pydantic response models. Read-only API — no request/input models for
mutating data, only query parameters (pagination) on the router side.

L'unite d'analyse est le MARCHE (Award), pas l'entreprise, depuis la
refonte du 28/08/2026 (voir docs/refonte_marche.md) — MarketScore
remplace l'ancien RiskScore par entreprise. Une Company n'a plus de score
propre : elle expose son identite et la liste de ses marches, chacun
portant son propre score."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

RISK_DISCLAIMER = (
    "Le score de risque est un signal statistique d'orientation pour "
    "analyse humaine, jamais une preuve ou une accusation de fraude."
)


def _split_active_flags(triggered: str | None) -> list[str]:
    """MarketScore.red_flags_triggered is stored as one comma-joined
    string (ai/market_red_flags.py's format) — vide ou None signifie
    aucun red flag actif, une liste vide ici, jamais un 1-item avec une
    chaine vide."""
    if not triggered:
        return []
    return [f.strip() for f in triggered.split(",") if f.strip()]


class MarketScoreSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    scorable: bool
    risk_level: str
    anomaly_score_0_100: float | None
    red_flag_score: float | None
    red_flag_count: int | None
    priority_score: float | None
    priority_level: str
    confidence_level: str | None


class MarketScoreDetail(MarketScoreSummary):
    stability_frequency: float | None
    red_flags_evaluable: int | None
    red_flags_triggered: list[str]
    data_quality_score: float | None
    data_quality_level: str | None
    invalid_fields_count: int | None
    priority_raw: float | None


class CompanySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    normalized_name: str


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
    score: MarketScoreSummary | None = Field(
        default=None, description="None si le marche n'a pas encore de score charge")


class CompanyDetail(BaseModel):
    id: int
    normalized_name: str
    awards: list[AwardSummary]


class RankingResponse(BaseModel):
    limit: int
    offset: int
    total: int
    items: list[AwardSummary]


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
    score: MarketScoreDetail | None = Field(
        default=None, description="None si le marche n'a pas encore de score charge")


class StatsCounts(BaseModel):
    procurements: int
    documents: int
    awards: int
    companies: int


class StatsSummary(BaseModel):
    counts: StatsCounts
    risk_level_distribution: dict[str, int] = Field(
        description="Faible/Modere/Eleve/Critique/Non evaluable -> nombre d'Award")
    disclaimer: str = RISK_DISCLAIMER
