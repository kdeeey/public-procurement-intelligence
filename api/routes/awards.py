"""GET /awards/{id} — see companies.py's docstring for why
acheteur_public/objet are read from award.procurement, not from Award's
own (never-populated) columns."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from api.dependencies import get_db
from api.schemas import AwardCompany, AwardDetail
from database.models import Award

router = APIRouter(prefix="/awards", tags=["awards"])


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

    procurement = award.procurement
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
    )
