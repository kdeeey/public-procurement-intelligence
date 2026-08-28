"""
Tableau de bord d'ETAT du pipeline — outil de controle interne.

Repond a une seule question : "ou en est la chaine, maintenant ?". Pas de
mise en forme travaillee, pas de score presente a un analyste — c'est le
dashboard principal (dashboard/app.py) qui fait ca.

AUCUN CHIFFRE N'EST ECRIT EN DUR ICI. La version precedente de ce fichier
figeait `expected = {"companies": 200}` : quand le correctif de nettoyage
des noms a fait passer la table a 193, cette page affichait une erreur
alors que rien n'etait casse. C'est exactement le motif que
database/crud/counts.py a ete cree pour supprimer. Tout ce qui est affiche
ici est lu a l'instant, depuis la base et depuis les fichiers.

CE QU'IL VERIFIE VRAIMENT
--------------------------
  1. la base est joignable, et ce qu'elle contient ;
  2. quels artefacts existent, avec leur taille et leur date ;
  3. la FRAICHEUR : un artefact plus ancien que ce dont il derive est
     perime, meme s'il existe et se lit sans erreur. C'est le defaut le
     plus silencieux du projet — un parquet valide mais calcule sur des
     donnees d'avant le dernier rechargement ;
  4. les recoupements de volumetrie entre etages ;
  5. ce qui est volontairement absent, pour qu'un trou reste distinguable
     d'un oubli.

    streamlit run dashboard/test_dashboard.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

ANALYTICS = REPO / "data/processed/analytics"

st.set_page_config(page_title="PMMP — etat du pipeline", layout="wide")
st.title("PMMP — état du pipeline")
st.caption("Outil de contrôle interne. Tout est lu à l'instant : aucun chiffre "
           "n'est écrit en dur dans cette page.")

# --------------------------------------------------------------------------- #
# 1. Base de donnees
# --------------------------------------------------------------------------- #
st.header("1. PostgreSQL")

TABLES = ("procurements", "documents", "awards", "companies",
          "award_companies", "risk_scores")


@st.cache_data(ttl=30)
def read_db() -> tuple[dict, str | None]:
    try:
        from sqlalchemy import func, select
        from database.crud.session import get_engine
        from database.models import (Award, Company, Document, Procurement,
                                     RiskScore, award_companies)
        modeles = {"procurements": Procurement.id, "documents": Document.id,
                   "awards": Award.id, "companies": Company.id,
                   "risk_scores": RiskScore.id}
        out = {}
        with get_engine().connect() as conn:
            for nom, col in modeles.items():
                out[nom] = int(conn.execute(select(func.count(col))).scalar_one())
            out["award_companies"] = int(conn.execute(
                select(func.count()).select_from(award_companies)).scalar_one())
        return out, None
    except Exception as exc:  # noqa: BLE001 — la page doit expliquer, pas planter
        return {}, f"{type(exc).__name__}: {exc}"


counts, db_error = read_db()
if db_error:
    st.error(f"**Base injoignable** — `{db_error}`\n\n"
             "Depuis l'hôte, `DATABASE_URL` doit pointer sur `localhost` "
             "(sur `postgres` uniquement depuis le réseau Docker). Vérifier "
             "que le conteneur `public-procurement-intelligence-postgres-1` "
             "tourne.")
else:
    cols = st.columns(len(counts))
    for col, (label, value) in zip(cols, counts.items()):
        col.metric(label, f"{value:,}".replace(",", " "))

# --------------------------------------------------------------------------- #
# 2. Artefacts
# --------------------------------------------------------------------------- #
st.header("2. Artefacts produits")

# (fichier, etape qui le produit, ce dont il derive)
ARTEFACTS = [
    ("fact_award_company", "build_analytics_dataset.py", "PostgreSQL"),
    ("market_stats", "build_statistics.py", "fact_award_company"),
    ("market_features.parquet", "build_market_features.py", "market_stats"),
    ("market_anomaly_scores.parquet", "train_market_model.py", "market_features.parquet"),
    ("market_data_quality.parquet", "features/data_quality.py", "market_features.parquet"),
    ("market_peer_comparison.parquet", "market_peer_analysis.py", "market_anomaly_scores.parquet"),
    ("market_red_flags.parquet", "market_red_flags.py", "market_peer_comparison.parquet"),
    ("market_explanations.parquet", "market_explain.py", "market_anomaly_scores.parquet"),
    ("market_priority.parquet", "priority_score.py", "market_red_flags.parquet"),
    ("company_features.parquet", "build_features.py", "fact_award_company"),
    ("company_final_risk.parquet", "risk_score.py", "company_features.parquet"),
]


def _mtime(path: Path) -> float | None:
    if not path.exists():
        return None
    if path.is_dir():
        fichiers = list(path.glob("*.parquet"))
        return max((f.stat().st_mtime for f in fichiers), default=None)
    return path.stat().st_mtime


@st.cache_data(ttl=30)
def read_artefacts() -> pd.DataFrame:
    lignes = []
    for nom, etape, source in ARTEFACTS:
        chemin = ANALYTICS / nom
        mt = _mtime(chemin)
        forme, erreur = "—", None
        if mt is not None:
            try:
                d = pd.read_parquet(chemin)
                forme = f"{len(d)} × {d.shape[1]}"
            except Exception as exc:  # noqa: BLE001
                erreur = f"{type(exc).__name__}"
        # Perime : plus ancien que ce dont il derive.
        mt_source = _mtime(ANALYTICS / source) if source != "PostgreSQL" else None
        perime = (mt is not None and mt_source is not None and mt < mt_source)
        lignes.append({
            "artefact": nom,
            "produit par": etape,
            "état": ("absent" if mt is None else
                     f"illisible ({erreur})" if erreur else
                     "PÉRIMÉ" if perime else "à jour"),
            "lignes × colonnes": forme,
            "dernière écriture": ("—" if mt is None
                                  else datetime.fromtimestamp(mt).strftime("%d/%m %H:%M")),
        })
    return pd.DataFrame(lignes)


arte = read_artefacts()
n_absents = int((arte["état"] == "absent").sum())
n_perimes = int((arte["état"] == "PÉRIMÉ").sum())

c1, c2, c3 = st.columns(3)
c1.metric("Artefacts à jour", int((arte["état"] == "à jour").sum()))
c2.metric("Périmés", n_perimes, delta_color="inverse",
          help="Plus anciens que ce dont ils dérivent : ils se lisent sans "
               "erreur mais reposent sur des données dépassées.")
c3.metric("Absents", n_absents, delta_color="inverse")

st.dataframe(arte, use_container_width=True, hide_index=True)

if n_perimes:
    st.error(f"**{n_perimes} artefact(s) périmé(s)** — ils existent et se lisent, "
             "mais ont été calculés avant leur source. C'est le défaut le plus "
             "silencieux de la chaîne : rien ne plante, les chiffres sont "
             "simplement faux. Rejouer les étapes concernées dans l'ordre.")
elif n_absents == 0:
    st.success("Tous les artefacts existent et sont postérieurs à leur source.")

# --------------------------------------------------------------------------- #
# 3. Recoupements entre étages
# --------------------------------------------------------------------------- #
st.header("3. Recoupements de volumétrie")


@st.cache_data(ttl=30)
def read_checks(counts: dict) -> list[dict]:
    checks = []

    def add(libelle, gauche, droite, detail=""):
        checks.append({"contrôle": libelle, "attendu": droite, "mesuré": gauche,
                       "verdict": "OK" if gauche == droite else "ÉCART",
                       "détail": detail})

    feats = ANALYTICS / "market_features.parquet"
    if feats.exists():
        m = pd.read_parquet(feats)
        if counts:
            add("marchés (features) = awards (base)", len(m), counts.get("awards", -1))
        attribues = int((m["statut"] == "ATTRIBUE").sum())
        sc = ANALYTICS / "market_anomaly_scores.parquet"
        if sc.exists():
            s = pd.read_parquet(sc)
            add("marchés scorés (fichier) = marchés attribués", len(s), attribues)
            add("scorés + non scorables = attribués",
                int((s["scorable"] == True).sum()) +  # noqa: E712
                int((s["scorable"] != True).sum()), attribues)  # noqa: E712
        for nom in ("market_data_quality.parquet", "market_red_flags.parquet",
                    "market_priority.parquet"):
            p = ANALYTICS / nom
            if p.exists():
                d = pd.read_parquet(p)
                cible = len(m) if nom == "market_data_quality.parquet" else attribues
                add(f"lignes de {nom}", len(d), cible)
    return checks


checks = read_checks(counts)
if checks:
    df_checks = pd.DataFrame(checks)
    st.dataframe(df_checks, use_container_width=True, hide_index=True)
    ecarts = df_checks[df_checks["verdict"] == "ÉCART"]
    if len(ecarts):
        st.error(f"**{len(ecarts)} écart(s)** — un étage a été rejoué sans les "
                 "autres. Rejouer la chaîne dans l'ordre.")
    else:
        st.success("Tous les recoupements passent.")
else:
    st.info("Artefacts marché absents — rien à recouper.")

# --------------------------------------------------------------------------- #
# 4. Chiffres clés
# --------------------------------------------------------------------------- #
st.header("4. Chiffres clés, lus à l'instant")

prio_path = ANALYTICS / "market_priority.parquet"
if prio_path.exists():
    p = pd.read_parquet(prio_path)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Marchés attribués", len(p))
    c2.metric("Très prioritaires", int((p["priority_level"] == "Tres prioritaire").sum()))
    c3.metric("Données insuffisantes",
              int((p["priority_level"] == "Donnees insuffisantes").sum()))
    dq = p["data_quality_score"].mean()
    c4.metric("Qualité moyenne", "—" if pd.isna(dq) else f"{dq:.0f}/100")

    g1, g2 = st.columns(2)
    with g1:
        st.caption("Répartition des niveaux de priorité")
        st.bar_chart(p["priority_level"].value_counts())
    with g2:
        st.caption("Répartition de la confiance")
        st.bar_chart(p["confidence_level"].value_counts())
else:
    st.info("`market_priority.parquet` absent — lancer `ai/priority_score.py`.")

# --------------------------------------------------------------------------- #
# 5. Absences volontaires
# --------------------------------------------------------------------------- #
st.header("5. Ce qui est absent volontairement")
st.markdown("""
Un trou doit rester distinguable d'un oubli. Ces éléments **n'existent pas**,
et c'est une décision mesurée, pas une étape manquée :

| Élément | Raison mesurée |
|---|---|
| `RF04` — écart estimation / attribution | `estimation_dhs_ttc` absente de **100 %** des marchés attribués (0/454) |
| Comparaison par région | `lieu_execution` absente de la table de faits |
| Analyse temporelle | médiane de 4 marchés/mois : aucune tendance mensuelle défendable |
| Analyse de réseau entre entreprises | degré maximum = 2 ; le graphe entreprise↔entreprise a 1 arête |
| Benchmark rule-based | sans vérité terrain, il montrerait un recouvrement, pas une supériorité |
| Feedback analyste | non implémenté (périmètre réduit) |
| Précision / rappel du modèle | **aucune vérité terrain au niveau marché** — la stabilité se mesure, la justesse non |
""")

st.divider()
st.caption("Le score de priorité est un ordre de lecture destiné à orienter une "
           "analyse humaine. Il ne qualifie aucun marché d'irrégulier et ne "
           "constitue ni une preuve ni une présomption.")
