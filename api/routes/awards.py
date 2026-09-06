"""
GET /awards, /awards/ranking, /awards/{id}.

Le score par marche (MarketScore) remplace l'ancien score par entreprise
(RiskScore, retire) — voir docs/refonte_marche.md. `ranking` reprend le
role de l'ancien /companies/ranking, mais trie desormais les MARCHES, pas
les entreprises.

Award.acheteur_public/objet are schema columns extraction/fields.py never
populates (see database/models/award.py's docstring) — the real values
live on the joined Procurement, read from award.procurement here, never
from the Award columns directly.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from api.dependencies import get_db
from api.schemas import (
    AwardCompany,
    AwardDetail,
    AwardSummary,
    MarketScoreDetail,
    MarketScoreSummary,
    RankingResponse,
    _split_active_flags,
)
from database.models import Award, MarketScore

router = APIRouter(prefix="/awards", tags=["awards"])


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


@router.get("", response_model=list[AwardSummary])
def list_awards(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Tous les Award, avec leur score si deja charge (LEFT JOIN) — un
    marche sans score charge (scripts/load_market_scores.py pas encore
    execute) reste visible, `score` vaut alors None, jamais un score
    fabrique a sa place."""
    rows = (
        db.query(Award, MarketScore)
        .options(joinedload(Award.procurement))
        .outerjoin(MarketScore, MarketScore.award_id == Award.id)
        .order_by(Award.id)
        .offset(offset).limit(limit)
        .all()
    )
    return [_to_award_summary(a, s) for a, s in rows]


@router.get("/ranking", response_model=RankingResponse)
def ranking(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Trie par priority_score decroissant (50% anomaly + 50% red flags,
    voir ai/priority_score.py) — seuls les marches SCORABLES et deja
    charges apparaissent ici, un marche sans score n'a pas de rang."""
    query = (
        db.query(Award, MarketScore)
        .options(joinedload(Award.procurement))
        .join(MarketScore, MarketScore.award_id == Award.id)
        .filter(MarketScore.scorable.is_(True))
    )
    total = query.count()
    rows = (
        query.order_by(MarketScore.priority_score.desc(), Award.id)
        .offset(offset).limit(limit)
        .all()
    )
    return RankingResponse(
        limit=limit, offset=offset, total=total,
        items=[_to_award_summary(a, s) for a, s in rows],
    )


@router.get("/{award_id}", response_model=AwardDetail)
def award_detail(award_id: int, db: Session = Depends(get_db)):
    award = (
        db.query(Award)
        .options(joinedload(Award.procurement), joinedload(Award.companies))
        .filter(Award.id == award_id)
        .one_or_none()
    )
    if award is None:
        raise HTTPException(status_code=404, detail="Award introuvable")

    score = db.query(MarketScore).filter(MarketScore.award_id == award_id).one_or_none()
    procurement = award.procurement

    score_detail = None
    if score is not None:
        score_detail = MarketScoreDetail(
            scorable=score.scorable,
            risk_level=score.risk_level,
            anomaly_score_0_100=score.anomaly_score_0_100,
            red_flag_score=score.red_flag_score,
            red_flag_count=score.red_flag_count,
            priority_score=score.priority_score,
            priority_level=score.priority_level,
            confidence_level=score.confidence_level,
            stability_frequency=score.stability_frequency,
            red_flags_evaluable=score.red_flags_evaluable,
            red_flags_triggered=_split_active_flags(score.red_flags_triggered),
            data_quality_score=score.data_quality_score,
            data_quality_level=score.data_quality_level,
            invalid_fields_count=score.invalid_fields_count,
            priority_raw=score.priority_raw,
        )

    return AwardDetail(
        id=award.id,
        doc_id=award.doc_id,
        ref_consultation=award.ref_consultation,
        statut=award.statut.value,
        montant_ht=award.montant_ht,
        montant_ttc=award.montant_ttc,
        montant_base_affichee=award.montant_base_affichee.value if award.montant_base_affichee else None,
        date_ouverture_plis=award.date_ouverture_plis,
        acheteur_public=procurement.acheteur_public if procurement else None,
        objet=procurement.objet if procurement else None,
        concurrent_retenu=award.concurrent_retenu,
        companies=[AwardCompany(id=c.id, normalized_name=c.normalized_name) for c in award.companies],
        score=score_detail,
    )
