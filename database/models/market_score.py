"""
MarketScore — le score par MARCHE (refonte du 28/08/2026), rechargé en
base pour que l'API et DBCode puissent le lire directement plutôt que de
dépendre du Parquet régénéré par ai/priority_score.py.

Remplace RiskScore (score par entreprise, Issue 12), retiré : l'unité
d'analyse du projet est désormais le marché (un Award), pas l'entreprise
— voir docs/refonte_marche.md pour la justification complète de cette
bascule.

Une ligne par Award (`award_id` unique), y compris les marchés NON
scorables (`scorable=False`) : ils restent visibles avec un `risk_level`
"Non evaluable" plutôt que de disparaître silencieusement de la table.
Écrasée en bloc à chaque rechargement (voir
database/crud/market_scores.py::load_market_scores()), jamais mise à
jour ligne par ligne, pour la même raison que l'ancien RiskScore : un
ré-entraînement d'Isolation Forest peut changer tous les scores à la
fois, pas un seul.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base

if TYPE_CHECKING:
    from database.models.award import Award


class MarketScore(Base):
    __tablename__ = "market_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    award_id: Mapped[int] = mapped_column(
        ForeignKey("awards.id"), unique=True, nullable=False, index=True)

    # False pour un marche avec moins de 2 informations extraites parmi
    # montant/concurrents/exclusions (ai/train_market_model.py) : reste
    # dans la table, jamais de score fabrique a sa place.
    scorable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    data_completeness: Mapped[int] = mapped_column(Integer, nullable=False)

    # Isolation Forest — nullable : NULL pour un marche non scorable.
    anomaly_score_0_100: Mapped[float | None] = mapped_column(Float)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, nullable=False)
    stability_frequency: Mapped[float | None] = mapped_column(Float)
    # "Faible" / "Modere" / "Eleve" / "Critique" / "Non evaluable" — texte
    # libre plutot qu'un Enum SQL : les seuils sont mesures sur la
    # distribution reelle a chaque entrainement (jamais 25/50/75), la
    # liste de valeurs n'est donc pas un contrat fige.
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False)

    # Red flags metier (ai/market_red_flags.py) — agrege ici, le detail
    # RF01..RF06 par marche reste dans market_red_flags.parquet, lu par
    # le dashboard pour la page XAI.
    red_flag_score: Mapped[float | None] = mapped_column(Float)
    red_flag_count: Mapped[int | None] = mapped_column(Integer)
    red_flags_evaluable: Mapped[int | None] = mapped_column(Integer)
    red_flags_triggered: Mapped[str | None] = mapped_column(Text)

    # Qualite des donnees extraites pour ce marche (features/data_quality.py)
    data_quality_score: Mapped[float | None] = mapped_column(Float)
    data_quality_level: Mapped[str | None] = mapped_column(String(32))
    invalid_fields_count: Mapped[int | None] = mapped_column(Integer)

    # Score de priorite compose (ai/priority_score.py) : 50% anomaly +
    # 50% red flags, plafonne si la confiance est faible.
    confidence_level: Mapped[str | None] = mapped_column(String(32))
    priority_raw: Mapped[float | None] = mapped_column(Float)
    priority_score: Mapped[float | None] = mapped_column(Float)
    priority_level: Mapped[str] = mapped_column(String(32), nullable=False)

    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    award: Mapped["Award"] = relationship()
