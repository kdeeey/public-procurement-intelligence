"""
GET /companies, /companies/{id}.

Une Company n'a plus de score propre depuis la refonte du 28/08/2026
(docs/refonte_marche.md) : l'unite d'analyse est le marche (Award), pas
l'entreprise. Le classement/scoring vit desormais dans api/routes/awards.py
(MarketScore) — cette route expose seulement l'identite d'une entreprise
et la liste de ses marches, chacun portant son propre score.

Award.acheteur_public/objet are schema columns extraction/fields.py never
populates (see database/models/award.py's docstring) — the real values
live on the joined Procurement, read from award.procurement here, never
from the Award columns directly.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from api.dependencies import get_db
from api.schemas import AwardSummary, CompanyDetail, CompanySummary, MarketScoreSummary
from database.models import Award, Company, MarketScore

router = APIRouter(prefix="/companies", tags=["companies"])


def _to_award_summary(award: Award, score: MarketScore | None) -> AwardSummary:
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
        score=MarketScoreSummary.model_validate(score) if score else None,
    )


@router.get("", response_model=list[CompanySummary])
def list_companies(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    companies = db.query(Company).order_by(Company.id).offset(offset).limit(limit).all()
    return [CompanySummary.model_validate(c) for c in companies]


@router.get("/{company_id}", response_model=CompanyDetail)
def company_detail(company_id: int, db: Session = Depends(get_db)):
    company = db.query(Company).filter(Company.id == company_id).one_or_none()
    if company is None:
        raise HTTPException(status_code=404, detail="Company introuvable")

    rows = (
        db.query(Award, MarketScore)
        .options(joinedload(Award.procurement))
        .join(Award.companies)
        .outerjoin(MarketScore, MarketScore.award_id == Award.id)
        .filter(Company.id == company_id)
        .all()
    )

    return CompanyDetail(
        id=company.id,
        normalized_name=company.normalized_name,
        awards=[_to_award_summary(a, s) for a, s in rows],
    )
