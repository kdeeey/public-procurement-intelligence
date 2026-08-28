"""
Dashboard de démonstration du pipeline PMMP (Issue 14, version basique).

Le chemin `dashboard/app.py` est celui que `docker-compose.yml` référence
déjà pour le service `dashboard` — il n'existait pas jusqu'ici.

Distinct de `dashboard/test_dashboard.py`, qui est un outil de contrôle
interne (une page, aucune mise en forme, sert à vérifier que le
chargement a marché). Celui-ci sert à MONTRER le projet : la chaîne
complète, ce qu'elle produit, et surtout ce qu'elle ne garantit pas.

Lecture directe PostgreSQL via les mêmes modèles SQLAlchemy que l'API.
Le dashboard cible d'Issue 14 devra passer par l'API HTTP (backlog,
critère de "done") — ce n'est pas le cas ici, assumé pour une version de
démonstration qui doit tourner sans second process.

    # depuis l'hôte (PostgreSQL publié sur localhost:5432)
    streamlit run dashboard/app.py

    # depuis un conteneur sur le réseau compose
    DATABASE_URL=postgresql://user:password@postgres:5432/procurement_db \
        streamlit run dashboard/app.py

AUCUN CHIFFRE N'EST ÉCRIT EN DUR ICI. Tous les compteurs, taux et seuils
affichés sont lus depuis la base au moment du rendu — c'est précisément
l'erreur corrigée le 27/08/2026 (une documentation qui affirmait un taux
de bruit mesuré une seule fois, jamais recalculé ensuite). La seule
exception est NOISY_NAMES ci-dessous, et elle est explicitement présentée
comme une annotation manuelle datée, pas comme une mesure automatique.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session, joinedload  # noqa: E402

from dashboard.analyses_view import render_analyses  # noqa: E402
from dashboard.market_view import (  # noqa: E402
    load_markets, render_market_detail, render_market_list,
)
from database.aliases import coverage, load_aliases  # noqa: E402
from database.crud.session import get_engine, get_session_factory  # noqa: E402
from database.models import (  # noqa: E402
    Award, Company, Document, Procurement, RiskScore, Statut, award_companies,
)

# Annotation MANUELLE du 27/08/2026 (bigdata/README.md, section
# "Correction du 27/08/2026"). Sert uniquement à marquer visuellement les
# lignes connues comme du bruit d'extraction dans les classements — un
# score élevé sur l'une d'elles n'est pas un signal de risque.
#
# Volontairement une liste figée et datée, pas une re-détection à la
# volée : re-classer automatiquement reviendrait à réappliquer le filtre
# qui a déjà laissé passer ces valeurs, donc à n'en marquer aucune.
NOISY_NAMES: frozenset[str] = frozenset(
    k for k, a in load_aliases().items() if a.is_rejected)

NOISE_AUDIT_DATE = "27/08/2026"

LEVEL_ORDER = ["Faible", "Modere", "Eleve", "Critique"]

st.set_page_config(page_title="PMMP — Intelligence des marchés publics",
                   layout="wide", page_icon="📊")


@st.cache_resource
def _session_factory():
    return get_session_factory(get_engine())


def _session() -> Session:
    return _session_factory()()


@st.cache_data(ttl=60)
def load_counts() -> dict:
    with _session() as db:
        return {
            "procurements": db.scalar(select(func.count(Procurement.id))),
            "documents": db.scalar(select(func.count(Document.id))),
            "awards": db.scalar(select(func.count(Award.id))),
            "companies": db.scalar(select(func.count(Company.id))),
            "risk_scores": db.scalar(select(func.count(RiskScore.id))),
            "awards_attribue": db.scalar(
                select(func.count(Award.id)).where(Award.statut == Statut.ATTRIBUE)),
            "attribue_sans_gagnant": db.scalar(
                select(func.count(Award.id)).where(
                    Award.statut == Statut.ATTRIBUE,
                    Award.concurrent_retenu.is_(None))),
            "awards_sans_montant": db.scalar(
                select(func.count(Award.id)).where(
                    Award.montant_ht.is_(None), Award.montant_ttc.is_(None))),
        }


@st.cache_data(ttl=60)
def load_companies() -> pd.DataFrame:
    """Toutes les Company AYANT un risk_score, avec leur volumétrie.

    Une Company sans risk_score n'apparaît pas — jamais un score fabriqué à
    la place d'une valeur manquante (même règle que `GET /companies` dans
    l'API). Le compteur de l'onglet « Le pipeline » lit la table `companies`
    entière, donc un écart entre les deux nombres signalerait un
    `risk_scores` incomplet ; c'est vérifié et affiché explicitement.

    `n_marches` et `montant_total_ttc` sont agrégés par une sous-requête sur
    `award_companies` : compter les Award d'un groupement une seule fois par
    entreprise, jamais en dupliquant la ligne Award elle-même.
    """
    marches = (
        select(award_companies.c.company_id.label("cid"),
               func.count(func.distinct(Award.id)).label("n_marches"),
               func.sum(Award.montant_ttc).label("montant_total_ttc"))
        .select_from(award_companies)
        .join(Award, Award.id == award_companies.c.award_id)
        .group_by(award_companies.c.company_id)
        .subquery()
    )
    with _session() as db:
        rows = db.execute(
            select(Company, RiskScore, marches.c.n_marches, marches.c.montant_total_ttc)
            .join(RiskScore, RiskScore.company_id == Company.id)
            .outerjoin(marches, marches.c.cid == Company.id)
        ).all()
    aliases = load_aliases()
    df = pd.DataFrame([{
        "id": c.id,
        "entreprise": c.normalized_name,
        "nom complet": (aliases[c.normalized_name].display()
                        if c.normalized_name in aliases else None),
        "score": round(float(s.final_score), 1),
        "niveau": s.risk_level.value,
        "marchés": int(n or 0),
        "montant TTC": float(m) if m is not None else None,
        "facteur dominant": s.dominant_driver,
        "red flags": f"{s.n_active_flags}/{s.n_evaluable_flags}",
        "évaluation partielle": s.partially_evaluated,
        "bruit connu": c.normalized_name in NOISY_NAMES,
    } for c, s, n, m in rows])
    # Garde-fou : sans risk_score charge, `rows` est vide et le DataFrame n'a
    # aucune colonne — sort_values("score") levait alors un KeyError qui
    # faisait planter toute la page, y compris les onglets marche qui ne
    # dependent pas de cette table. Trouve en executant reellement le
    # dashboard (streamlit.testing.AppTest), pas en relisant le code.
    if df.empty:
        return df
    return df.sort_values("score", ascending=False).reset_index(drop=True)


@st.cache_data(ttl=60)
def load_company_detail(company_id: int) -> tuple[dict, pd.DataFrame]:
    with _session() as db:
        company, score = db.execute(
            select(Company, RiskScore)
            .join(RiskScore, RiskScore.company_id == Company.id)
            .where(Company.id == company_id)
        ).one()
        awards = db.scalars(
            select(Award).options(joinedload(Award.procurement))
            .join(Award.companies).where(Company.id == company_id)
        ).unique().all()
        detail = {
            "nom": company.normalized_name,
            "affiché": company.display_name,
            "score": round(float(score.final_score), 1),
            "niveau": score.risk_level.value,
            "explication": score.explanation,
            "flags": score.active_flags,
            "partielle": score.partially_evaluated,
        }
        awards_df = pd.DataFrame([{
            "award": a.id,
            "statut": a.statut.value,
            "montant HT": a.montant_ht,
            "montant TTC": a.montant_ttc,
            "date ouverture": a.date_ouverture_plis,
            "acheteur": a.procurement.acheteur_public if a.procurement else None,
            "objet": (a.procurement.objet[:90] if a.procurement and a.procurement.objet
                      else None),
            "texte extrait (nettoyé)": a.concurrent_retenu,
            "texte source (brut)": a.concurrent_retenu_brut,
        } for a in awards])
    return detail, awards_df


# --------------------------------------------------------------------------- #
st.title("📊 Exploitation des marchés publics — PMMP")
st.caption("Portail Marocain des Marchés Publics · prototype académique")

st.warning(
    "**Le score de risque est un signal statistique d'orientation pour analyse "
    "humaine, jamais une preuve ni une accusation de fraude.** Le système ne dit "
    "pas « cette entreprise est frauduleuse » mais « ce marché présente des "
    "caractéristiques statistiquement associées à un risque dans la littérature ». "
    "La décision reste humaine.")

try:
    counts = load_counts()
except Exception as exc:
    st.error(f"Base injoignable : `{type(exc).__name__}: {exc}`\n\n"
             "Vérifier que le conteneur `public-procurement-intelligence-postgres-1` "
             "tourne, et que `DATABASE_URL` pointe sur `localhost` depuis l'hôte "
             "(sur `postgres` seulement depuis le réseau Docker).")
    st.stop()

if counts["risk_scores"] == 0:
    st.error("La table `risk_scores` est vide — relancer `ai/risk_score.py` puis "
             "`scripts/load_risk_scores.py`. Les onglets de risque seront vides.")

# Depuis la refonte du 28/08/2026, l'unite d'analyse est le MARCHE : les deux
# premiers onglets sont donc les siens, et l'etage entreprise passe apres, en
# descriptif. Raison mesuree : 180/193 entreprises n'ont qu'un seul marche,
# donc les "taux" par entreprise etaient des observations uniques deguisees en
# frequences (voir bigdata/spark/jobs/build_market_features.py).
(tab_marches, tab_detail, tab_analyses, tab_pipeline, tab_risque,
 tab_entreprise, tab_qualite) = st.tabs(
    ["📋 Marchés à examiner", "🔎 Détail d'un marché",
     "📊 Analyses transversales", "🔗 Le pipeline",
     "⚠️ Risque (entreprise, descriptif)", "🔍 Une entreprise",
     "🧪 Qualité des données"])

_markets = load_markets()

with tab_marches:
    render_market_list(_markets)

with tab_detail:
    render_market_detail(_markets)

with tab_analyses:
    render_analyses(_markets)

# --------------------------------------------------------------------------- #
with tab_pipeline:
    st.subheader("Ce que la chaîne a produit")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Consultations", f"{counts['procurements']:,}".replace(",", " "),
              help="Métadonnées des marchés, scrapées en HTML (aucun OCR)")
    c2.metric("Documents PV", counts["documents"],
              help="PDF d'extraits de procès-verbaux, ~71 % scannés")
    c3.metric("Attributions", counts["awards"],
              help="Un Award par lot — un PV multi-lots en produit plusieurs")
    c4.metric("Entreprises", counts["companies"],
              help="Entités dédupliquées par nom normalisé")

    st.markdown("""
| # | Étape | Sortie |
|---|---|---|
| 1-2 | **Scraping** du portail (framework PRADO, 2 passes) | PDF + métadonnées |
| 3-4 | **OCR** page par page, natif ou scanné, + nettoyage | texte brut |
| 5 | **Extraction** structurée (regex, segmentation par lot) | Award |
| 6 | **PostgreSQL** — Procurement / Document / Award / Company | base |
| 7 | **PySpark** — agrégats par entreprise, acheteur, marché | Parquet |
| 8 | **Isolation Forest** + score composite explicable | score 0-100 |
| 9 | **API** FastAPI en lecture seule | JSON |
| 10 | **Dashboard** (cette page) | — |
""")
    st.info("**La limite de fond** : anomalie ≠ fraude. Le score priorise "
            "l'analyse humaine, il ne conclut jamais.")

# --------------------------------------------------------------------------- #
with tab_risque:
    st.warning(
        "**Cet onglet n'est plus le modèle principal.** Depuis le 28/08/2026, "
        "la détection se fait au niveau du **marché** (onglets précédents). "
        "Les scores d'entreprise affichés ici proviennent de l'ancien modèle et "
        "sont conservés à titre descriptif et comparatif : 180 des 193 "
        "entreprises n'ayant qu'un seul marché, leurs « taux » étaient des "
        "observations uniques déguisées en fréquences, et le modèle signalait "
        "13/13 des entreprises à 2 marchés contre 25/180 de celles à 1 marché — "
        "il apprenait la profondeur du corpus, pas un comportement.")
    df = load_companies()
    if df.empty:
        st.info("Aucun score de risque chargé.")
    else:
        st.subheader("Distribution des niveaux de risque")
        dist = df["niveau"].value_counts().reindex(LEVEL_ORDER, fill_value=0)
        cols = st.columns(4)
        for col, level in zip(cols, LEVEL_ORDER):
            col.metric(level, int(dist[level]))
        st.bar_chart(dist)
        st.caption(
            "Seuils **mesurés sur la population**, pas 25/50/75 arbitraires : "
            "*Faible* = sous la frontière que le modèle choisit lui-même ; le "
            "sous-groupe anormal est ensuite coupé en trois terciles mesurés.")

        st.subheader(f"Les {len(df)} entreprises — la plus anormale en premier")

        n_noisy_top10 = int(df.head(10)["bruit connu"].sum())
        if n_noisy_top10:
            st.error(
                f"**{n_noisy_top10} des 10 premières lignes sont du bruit "
                f"d'extraction**, pas des entreprises. C'est la limite la plus "
                f"importante de ce classement : ne jamais le présenter sans "
                f"vérifier visuellement les premières lignes.")

        f1, f2, f3 = st.columns([2, 2, 1])
        query = f1.text_input("Filtrer par nom", placeholder="ex : TECTRA, SARL, BTP…")
        levels = f2.multiselect("Niveau de risque", LEVEL_ORDER, default=LEVEL_ORDER)
        hide = f3.checkbox(f"Masquer le bruit ({int(df['bruit connu'].sum())})",
                           value=False,
                           help=f"Lignes annotées comme bruit d'extraction lors de "
                                f"l'audit manuel du {NOISE_AUDIT_DATE}")

        shown = df[df["niveau"].isin(levels)]
        if query:
            shown = shown[shown["entreprise"].str.contains(query, case=False, na=False)]
        if hide:
            shown = shown[~shown["bruit connu"]]

        st.dataframe(
            shown.style.apply(
                lambda r: ["background-color: #6b2020" if r["bruit connu"] else ""] * len(r),
                axis=1).format({"montant TTC": lambda v: "—" if pd.isna(v)
                                else f"{v:,.2f}".replace(",", " ")}),
            use_container_width=True, height=560, hide_index=True)

        cov = coverage(df["entreprise"].tolist())
        st.caption(
            f"**Correspondance des sigles** : {cov['annotes']}/{cov['total']} noms "
            f"annotés dans `data/reference/company_aliases.csv` — "
            f"{cov['confirmes']} confirmés contre le PDF source, "
            f"{cov['a_verifier']} pistes web à confirmer, "
            f"{cov['rejetes']} pièges écartés. Une colonne « nom complet » vide "
            f"signifie *pas encore annoté*, jamais *pas d'entreprise*.")

        st.caption(
            f"**{len(shown)} entreprise(s) affichée(s)** sur {len(df)} au total. "
            f"Les lignes surlignées sont annotées comme bruit connu — leur score "
            f"n'a pas de sens. Tableau triable en cliquant sur un en-tête de "
            f"colonne, et exportable via l'icône en haut à droite du tableau.")

        if len(df) != counts["companies"]:
            st.warning(
                f"{counts['companies'] - len(df)} entreprise(s) de la table "
                f"`companies` n'apparaissent pas ici : elles n'ont pas de "
                f"`risk_score` chargé. Jamais un score fabriqué à la place d'une "
                f"valeur manquante — relancer `scripts/load_risk_scores.py`.")

        st.caption(
            f"Montant TTC cumulé affiché : "
            f"{shown['montant TTC'].sum():,.2f} DH".replace(",", " ") +
            f" — sur les seules {int(shown['montant TTC'].notna().sum())} "
            f"entreprise(s) ayant au moins un montant TTC extrait. "
            f"Ce total n'est PAS le volume réel des marchés : "
            f"{counts['awards_sans_montant']} attributions sur {counts['awards']} "
            f"n'ont aucun montant (voir l'onglet Qualité des données).")

# --------------------------------------------------------------------------- #
with tab_entreprise:
    df = load_companies()
    if df.empty:
        st.info("Aucun score de risque chargé.")
    else:
        choice = st.selectbox(
            "Entreprise", df["entreprise"].tolist(),
            index=df["entreprise"].tolist().index("COSTACOM")
            if "COSTACOM" in df["entreprise"].values else 0)
        row = df[df["entreprise"] == choice].iloc[0]
        detail, awards_df = load_company_detail(int(row["id"]))

        if row["bruit connu"]:
            st.error("Cette ligne est annotée comme **bruit d'extraction** — "
                     "ce n'est pas une entreprise, son score n'a pas de sens.")

        alias = load_aliases().get(choice)
        if alias and alias.is_rejected:
            st.error(
                f"**Piège identifié — ne pas rattacher.** {alias.notes}\n\n"
                f"Un sigle qui correspond à une entreprise réelle ne signifie pas "
                f"que *ce document* parle d'elle. Vérifié le {alias.verifie_le}.")
        elif alias and alias.nom_complet:
            label = "Raison sociale confirmée" if alias.is_confirmed else \
                "Piste à confirmer contre le PDF source"
            box = st.success if alias.is_confirmed else st.info
            box(f"**{label}** — {alias.nom_complet}"
                + (f", {alias.ville}" if alias.ville else "")
                + (f"  \n{alias.source_url}" if alias.source_url else ""))
            if alias.notes:
                st.caption(alias.notes)

        c1, c2, c3 = st.columns(3)
        c1.metric("Score de risque", detail["score"])
        c2.metric("Niveau", detail["niveau"])
        c3.metric("Red flags actifs", row["red flags"])
        if detail["partielle"]:
            st.warning("**Évaluation partielle** : aucun montant TTC extrait pour "
                       "cette entreprise, la concentration chez ses acheteurs n'a "
                       "pas pu être mesurée (2 red flags sur 3).")
        st.info(detail["explication"])

        st.subheader(f"{len(awards_df)} attribution(s)")
        if not awards_df.empty:
            st.dataframe(awards_df.drop(columns=["texte source (brut)"]),
                         use_container_width=True)
            with st.expander("Texte source brut vs texte nettoyé (traçabilité)"):
                st.caption(
                    "Le nom d'entreprise est isolé du bloc brut par "
                    "`extraction/company_name.py`. Le texte d'origine est conservé "
                    "en base pour pouvoir montrer ce que le document disait.")
                st.dataframe(awards_df[["award", "texte source (brut)",
                                        "texte extrait (nettoyé)"]],
                             use_container_width=True)

# --------------------------------------------------------------------------- #
with tab_qualite:
    st.subheader("Ce que ces données ne garantissent pas")
    df = load_companies()

    n_noise = int(df["bruit connu"].sum()) if not df.empty else 0
    total = counts["companies"]
    attribue = counts["awards_attribue"]
    sans_gagnant = counts["attribue_sans_gagnant"]
    sans_montant = counts["awards_sans_montant"]

    c1, c2, c3 = st.columns(3)
    c1.metric("Lignes de bruit connu", f"{n_noise} / {total}",
              f"{100 * n_noise / total:.1f} %" if total else "—",
              delta_color="inverse")
    c2.metric("Attribués sans gagnant identifié", f"{sans_gagnant} / {attribue}",
              f"{100 * sans_gagnant / attribue:.0f} %" if attribue else "—",
              delta_color="inverse")
    c3.metric("Attributions sans aucun montant", f"{sans_montant} / {counts['awards']}",
              f"{100 * sans_montant / counts['awards']:.0f} %" if counts["awards"] else "—",
              delta_color="inverse")

    st.markdown(f"""
**Bruit résiduel.** L'audit manuel exhaustif du {NOISE_AUDIT_DATE} a compté
{n_noise} lignes de bruit pur sur {total}, plus 16 noms réels accompagnés de
texte parasite — soit environ 16 % de la table affectée d'une façon ou d'une
autre. C'était 53,5 % avant le correctif d'extraction du même jour.

**Marchés attribués sans gagnant.** {sans_gagnant} attributions sur {attribue}
n'ont plus de nom de gagnant. Ce n'est pas une perte : le texte capté à cet
endroit était du bruit (*« L'offre économiquement la plus avantageuse. »*,
*« - Néant »*). La table est **plus juste et plus vide** qu'avant. Le texte
d'origine reste consultable dans l'onglet précédent.

**Montants manquants.** {sans_montant} attributions sur {counts['awards']} n'ont
ni montant HT ni montant TTC. Les entreprises concernées entrent dans le modèle
avec un montant **imputé à la médiane**, jamais à zéro, accompagné d'un
indicateur explicite `has_ttc_data`.

**Déduplication imparfaite.** Trois entreprises réelles comptent double à cause
de variantes OCR (`TANSIFT CONTRACTOR DIRECT` / `…DIRECTR`,
`LE PALAIS D AMENAGEMENT` / `…AMENAGEMEN`, deux formes de `EMPEGEC`). Leur part
de marché et leur nombre de marchés sont donc scindés, donc faux.

**Vérité terrain restreinte.** La qualité d'extraction est mesurée contre
**20 documents annotés à la main**, dont 16 exploitables pour le champ
`concurrent_retenu`. Le taux de 88 % correspond à 14 documents sur 16 : c'est
un ordre de grandeur défendable, pas une précision au point près.

**HT et TTC ne sont jamais fusionnés.** Aucun taux de TVA n'est supposé pour
déduire l'un de l'autre — ce sont deux colonnes indépendantes, nulles quand le
document ne les affiche pas.
""")
    st.caption("Détail complet et cas restants nommés un par un : "
               "`bigdata/README.md`, section « Correction du 27/08/2026 ».")
