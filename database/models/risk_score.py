"""
RiskScore — le score final explicable d'Issue 12 (ai/risk_score.py),
rechargé en base pour que l'API (Issue 13) et DBCode puissent le lire
directement, plutôt que de dépendre d'un fichier Parquet régénéré par un
job Spark/Python indépendant.

Une ligne par Company (`company_id` unique) — écrasée en bloc à chaque
rechargement (voir database/crud/risk_scores.py::load_risk_scores()),
jamais mise à jour incrémentalement : ce score est recalculé en entier à
chaque run de ai/risk_score.py (un ré-entraînement d'Isolation Forest
change potentiellement tous les scores, pas seulement celui d'une
entreprise), donc un upsert partiel ligne par ligne serait trompeur —
plus proche en pratique d'un TRUNCATE + reload complet, comme
`companies`/`awards` (scripts/load_database.py).
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base

if TYPE_CHECKING:
    from database.models.company import Company


class RiskLevel(str, enum.Enum):
    """Seuils mesurés sur la distribution réelle des 200 Company, pas
    25/50/75 arbitraires — voir ai/risk_score.py::_measure_thresholds()."""
    FAIBLE = "Faible"
    MODERE = "Modere"
    ELEVE = "Eleve"
    CRITIQUE = "Critique"


class RiskScore(Base):
    __tablename__ = "risk_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id"), unique=True, nullable=False, index=True)

    # Sortie brute d'Isolation Forest (plus bas = plus anormal) et sa
    # version rescalee 0-100 (plus haut = plus anormal) — les deux
    # gardees, jamais une seule presentee comme "le" score (le rescale
    # est une transformation, pas une mesure independante).
    anomaly_score: Mapped[float] = mapped_column(Float, nullable=False)
    final_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_level: Mapped[RiskLevel] = mapped_column(Enum(RiskLevel, native_enum=False), nullable=False)

    # Couche d'explication (ai/scoring.py) — jamais fusionnee
    # arithmetiquement avec anomaly_score/final_score, voir
    # ai/risk_score.py docstring pour l'articulation des deux scores.
    n_active_flags: Mapped[int] = mapped_column(Integer, nullable=False)
    n_evaluable_flags: Mapped[int] = mapped_column(Integer, nullable=False)
    active_flags: Mapped[str] = mapped_column(Text, nullable=False)
    partially_evaluated: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # "surtout_montant" / "comportement_et_montant" — voir
    # ai/risk_score.py::_compute_dominant_driver(). Nullable : ce champ
    # n'a de sens que pour une entreprise dont has_ttc_data existe assez
    # de points pour l'ablation ; en pratique toujours rempli aujourd'hui,
    # mais pas garanti par construction.
    dominant_driver: Mapped[str | None] = mapped_column(Text)

    explanation: Mapped[str] = mapped_column(Text, nullable=False)

    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    company: Mapped["Company"] = relationship()
