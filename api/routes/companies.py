"""
GET /companies, /companies/{id}, /companies/ranking.

Award.acheteur_public/objet are schema columns extraction/fields.py never
populates (see database/models/award.py's docstring) — the real values
live on the joined Procurement, read from award.procurement here, never
from the Award columns directly.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from api.dependencies import get_db
from api.schemas import AwardSummary, CompanyDetail, CompanySummary, RankingResponse, _split_active_flags
from database.models import Award, Company, RiskScore

router = APIRouter(prefix="/companies", tags=["companies"])


def _to_award_summary(award: Award) -> AwardSummary:
    procurement = award.procurement
    return AwardSummary(
        id=award.id,
        doc_id=award.doc_id,
        statut=award.statut.value,
        montant_ht=award.montant_ht,
        montant_ttc=award.montant_ttc,
        montant_base_affichee=award.montant_base_affichee.value if award.montant_base_affichee else None,
        date_ouverture_plis=award.date_ouverture_plis,
        acheteur_public=procurement.acheteur_public if procurement else None,
        objet=procurement.objet if procurement else None,
    )


def _to_company_summary(company: Company, score: RiskScore) -> CompanySummary:
    return CompanySummary(
        id=company.id,
        normalized_name=company.normalized_name,
        final_score=score.final_score,
        risk_level=score.risk_level.value,
        dominant_driver=score.dominant_driver,
        n_active_flags=score.n_active_flags,
    )


@router.get("", response_model=list[CompanySummary])
def list_companies(db: Session = Depends(get_db)):
    """Sans risk_score (pas encore rechargee, ai/risk_score.py pas encore
    execute) une Company n'apparait pas ici — jamais un score fabrique a
    la place d'une valeur manquante."""
    rows = db.query(Company, RiskScore).join(RiskScore, RiskScore.company_id == Company.id).all()
    return [_to_company_summary(c, s) for c, s in rows]


@router.get("/ranking", response_model=RankingResponse)
def ranking(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Trie par final_score decroissant (le plus anormal en premier) —
    le signal Isolation Forest fait autorite pour le classement, voir
    ai/risk_score.py pour l'articulation avec le score composite."""
    query = db.query(Company, RiskScore).join(RiskScore, RiskScore.company_id == Company.id)
    total = query.count()
    rows = query.order_by(RiskScore.final_score.desc(), Company.id).offset(offset).limit(limit).all()
    return RankingResponse(
        limit=limit, offset=offset, total=total,
        items=[_to_company_summary(c, s) for c, s in rows],
    )


@router.get("/{company_id}", response_model=CompanyDetail)
def company_detail(company_id: int, db: Session = Depends(get_db)):
    row = (
        db.query(Company, RiskScore)
        .join(RiskScore, RiskScore.company_id == Company.id)
        .filter(Company.id == company_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Company introuvable ou sans risk_score charge (voir scripts/load_risk_scores.py)")
    company, score = row

    awards = (
        db.query(Award)
        .options(joinedload(Award.procurement))
        .join(Award.companies)
        .filter(Company.id == company_id)
        .all()
    )

    return CompanyDetail(
        id=company.id,
        normalized_name=company.normalized_name,
        final_score=score.final_score,
        risk_level=score.risk_level.value,
        dominant_driver=score.dominant_driver,
        n_active_flags=score.n_active_flags,
        n_evaluable_flags=score.n_evaluable_flags,
        active_flags=_split_active_flags(score.active_flags),
        partially_evaluated=score.partially_evaluated,
        explanation=score.explanation,
        awards=[_to_award_summary(a) for a in awards],
    )
