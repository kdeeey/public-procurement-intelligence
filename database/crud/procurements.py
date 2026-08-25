"""
Load Procurement rows from the scraped consultations (data/raw/consultations/
consultations_full.jsonl). HTML-sourced, no OCR involved — data_dictionary.md
§2.

`ref_consultation` is the join key (§1) and is required on every row here;
a record without one cannot be a Procurement in this schema (it would have
no way to ever join to a Document or Award).
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from database.models import CategoriePrincipale, Procurement


def _parse_bool_oui_non(value) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v == "oui":
            return True
        if v == "non":
            return False
    return None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_decimal(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _parse_categorie(value: str | None) -> CategoriePrincipale | None:
    if not value:
        return None
    try:
        return CategoriePrincipale(value)
    except ValueError:
        # Valeur hors des 3 confirmees (data_dictionary.md §2) — laissee
        # None plutot que de planter l'insertion sur une variante non
        # encore vue, a signaler separement si ca arrive en pratique.
        return None


def load_procurements(session: Session, consultations_path: Path) -> dict[str, int]:
    """Insere ou met a jour un Procurement par refConsultation.

    Retourne {"inserted": n, "updated": n, "skipped_no_ref": n}.
    """
    counts = {"inserted": 0, "updated": 0, "skipped_no_ref": 0}

    with consultations_path.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            ref_consultation = rec.get("refConsultation")
            if not ref_consultation:
                counts["skipped_no_ref"] += 1
                continue

            existing = session.query(Procurement).filter_by(
                ref_consultation=ref_consultation).one_or_none()
            target = existing or Procurement(ref_consultation=ref_consultation)

            target.reference = rec.get("reference")
            target.objet = rec.get("objet")
            target.acheteur_public = rec.get("acheteur_public")
            target.type_annonce = rec.get("type_annonce")
            target.mode_passation = rec.get("mode_passation")
            target.categorie_principale = _parse_categorie(rec.get("categorie_principale"))
            target.lieu_execution = rec.get("lieu_execution")
            target.estimation_dhs_ttc = _parse_decimal(rec.get("estimation_dhs_ttc"))
            target.caution_provisoire = _parse_decimal(rec.get("caution_provisoire"))
            target.qualifications = rec.get("qualifications")
            target.domaines_activite = rec.get("domaines_activite")
            target.allotissement = _parse_bool_oui_non(rec.get("allotissement"))
            target.reserve_tpe_pme = _parse_bool_oui_non(rec.get("reserve_tpe_pme"))
            target.date_mise_ligne = _parse_date(rec.get("date_mise_ligne"))
            target.date_limite_remise_plis = _parse_date(rec.get("date_limite_remise_plis"))
            target.lieu_ouverture_plis = rec.get("lieu_ouverture_plis")
            target.dossier_consultation_url = rec.get("dossier_consultation_url")

            if not existing:
                session.add(target)
                counts["inserted"] += 1
            else:
                counts["updated"] += 1

    session.flush()
    return counts
