"""
ORM models. Import order matters here: every model module must be imported
before SQLAlchemy resolves the string-based forward references used in
relationship() (e.g. Mapped[list["Award"]] on Procurement) — otherwise the
mapper configuration fails with "expression ... failed to locate a name".
"""

from database.models.base import Base
from database.models.company import Company, award_companies
from database.models.document import Document, JoinStatus, OcrStatus
from database.models.procurement import AnneeSource, CategoriePrincipale, Procurement
from database.models.award import Award, MontantBaseAffichee, Statut
from database.models.risk_score import RiskLevel, RiskScore

__all__ = [
    "Base",
    "Procurement",
    "CategoriePrincipale",
    "AnneeSource",
    "Award",
    "Statut",
    "MontantBaseAffichee",
    "Company",
    "award_companies",
    "Document",
    "OcrStatus",
    "JoinStatus",
    "RiskScore",
    "RiskLevel",
]
