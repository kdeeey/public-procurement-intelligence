"""GET /stats/summary — global counts + risk_level distribution.

La distribution porte desormais sur les MARCHES (MarketScore), pas les
entreprises — voir docs/refonte_marche.md. Counts are simple table row
counts (procurements/documents/awards/companies), not a re-derivation of
Issue 10's Spark aggregates — this endpoint is an overview, not a
substitute for company_stats_*.parquet."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.dependencies import get_db
from api.schemas import StatsCounts, StatsSummary
from database.models import Award, Company, Document, MarketScore, Procurement

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/summary", response_model=StatsSummary)
def summary(db: Session = Depends(get_db)):
    counts = StatsCounts(
        procurements=db.query(func.count(Procurement.id)).scalar(),
        documents=db.query(func.count(Document.id)).scalar(),
        awards=db.query(func.count(Award.id)).scalar(),
        companies=db.query(func.count(Company.id)).scalar(),
    )

    # Toutes les valeurs de risk_level presentes dans la table sont
    # incluses meme a 0 — jamais une cle absente silencieusement.
    rows = (
        db.query(MarketScore.risk_level, func.count(MarketScore.id))
        .group_by(MarketScore.risk_level)
        .all()
    )
    counts_by_level = {level: n for level, n in rows}
    distribution = {
        level: counts_by_level.get(level, 0)
        for level in ("Faible", "Modere", "Eleve", "Critique", "Non evaluable")
    }

    return StatsSummary(counts=counts, risk_level_distribution=distribution)
