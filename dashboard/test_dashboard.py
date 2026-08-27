"""Dashboard MINIMAL DE VERIFICATION — pas l'Issue 14 (page unique, sans
mise en forme travaillee). Objectif : confirmer visuellement que le
pipeline complet (Issues 8-12) produit des resultats coherents avant de
construire la vraie interface.

Lecture directe PostgreSQL (memes modeles SQLAlchemy que l'API/database/),
pas via l'API HTTP — evite de devoir garder un second process uvicorn
lance pour ce simple controle.

    streamlit run dashboard/test_dashboard.py
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session, joinedload

from database.crud.session import get_engine, get_session_factory
from database.models import Award, Company, Document, Procurement, RiskScore

st.set_page_config(page_title="PMMP — dashboard de verification", layout="wide")

st.title("PMMP — dashboard de verification (Issue 14 pre-check)")
st.caption(
    "Outil de controle interne, pas la version soutenance. Aucune mise en "
    "forme travaillee — le but est de verifier que les donnees calculees "
    "dans les Issues 8-12 s'affichent correctement et de facon coherente."
)
st.warning(
    "Le score de risque est un signal statistique d'orientation pour "
    "analyse humaine, jamais une preuve ou une accusation de fraude."
)


@st.cache_resource
def _get_session_factory():
    return get_session_factory(get_engine())


def _session() -> Session:
    return _get_session_factory()()


# --- 1. Comptages de base -----------------------------------------------
st.header("1. Comptages de base")
with _session() as db:
    counts = {
        "procurements": db.query(Procurement).count(),
        "documents": db.query(Document).count(),
        "awards": db.query(Award).count(),
        "companies": db.query(Company).count(),
    }

expected = {"procurements": 1750, "documents": 390, "awards": 454, "companies": 200}
cols = st.columns(4)
for col, (label, value) in zip(cols, counts.items()):
    col.metric(label, value, delta=None if value == expected[label] else f"attendu {expected[label]}")
    if value != expected[label]:
        st.error(f"{label} : {value} lu, {expected[label]} attendu — verifier le chargement (scripts/load_database.py).")

# --- 2 & 3. Table des entreprises + distribution -------------------------
st.header("2. Entreprises — risk_score, niveau, dominant_driver, red flags")

with _session() as db:
    rows = (
        db.query(Company, RiskScore)
        .join(RiskScore, RiskScore.company_id == Company.id)
        .all()
    )

if not rows:
    st.error(
        "Aucune ligne dans risk_scores — table vide ou pas encore chargee "
        "(voir scripts/load_risk_scores.py)."
    )
else:
    df = pd.DataFrame(
        [
            {
                "company_id": c.id,
                "nom": c.normalized_name,
                "risk_score": round(s.final_score, 2),
                "niveau": s.risk_level.value,
                "dominant_driver": s.dominant_driver,
                "red_flags_actifs": s.active_flags,
                "partiellement_evalue": s.partially_evaluated,
            }
            for c, s in rows
        ]
    ).sort_values("risk_score", ascending=False)

    st.dataframe(df, use_container_width=True, height=500)

    st.subheader("3. Distribution des niveaux de risque")
    order = ["Faible", "Modere", "Eleve", "Critique"]
    dist = df["niveau"].value_counts().reindex(order, fill_value=0)
    st.bar_chart(dist)
    st.caption(f"Faible={dist['Faible']} / Modere={dist['Modere']} / Eleve={dist['Eleve']} / Critique={dist['Critique']}")

# --- 4. Recherche entreprise ---------------------------------------------
st.header("4. Recherche entreprise — detail complet")
query = st.text_input("Nom (ou fragment) — ex: COSTACOM, INNOVATIVE, TECTRA")

if query:
    with _session() as db:
        matches = (
            db.query(Company, RiskScore)
            .join(RiskScore, RiskScore.company_id == Company.id)
            .filter(Company.normalized_name.ilike(f"%{query}%"))
            .all()
        )

    if not matches:
        st.warning(f"Aucune entreprise ne correspond a '{query}'.")

    for company, score in matches:
        with st.expander(f"{company.normalized_name} — score {round(score.final_score, 2)} ({score.risk_level.value})", expanded=True):
            c1, c2, c3 = st.columns(3)
            c1.metric("final_score", round(score.final_score, 2))
            c1.metric("anomaly_score (brut)", round(score.anomaly_score, 4))
            c2.metric("niveau", score.risk_level.value)
            c2.metric("dominant_driver", score.dominant_driver or "—")
            c3.metric("flags actifs", f"{score.n_active_flags}/{score.n_evaluable_flags}")
            c3.metric("partiellement evalue", "oui" if score.partially_evaluated else "non")

            st.write("**Red flags actifs :**", score.active_flags)
            st.write("**Explication :**")
            st.info(score.explanation)

            with _session() as db2:
                awards = (
                    db2.query(Award)
                    .options(joinedload(Award.procurement))
                    .join(Award.companies)
                    .filter(Company.id == company.id)
                    .all()
                )

            if awards:
                awards_df = pd.DataFrame(
                    [
                        {
                            "award_id": a.id,
                            "doc_id": a.doc_id,
                            "statut": a.statut.value,
                            "montant_ht": a.montant_ht,
                            "montant_ttc": a.montant_ttc,
                            "acheteur_public": a.procurement.acheteur_public if a.procurement else None,
                            "objet": a.procurement.objet if a.procurement else None,
                        }
                        for a in awards
                    ]
                )
                st.write(f"**{len(awards)} award(s) associe(s) :**")
                st.dataframe(awards_df, use_container_width=True)
            else:
                st.write("Aucun award associe.")
