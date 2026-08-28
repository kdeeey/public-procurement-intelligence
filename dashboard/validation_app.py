"""
PMMP — Validation-seule (28/08/2026).

ETAPE INTERMEDIAIRE, PAS LE DASHBOARD FINAL. Objectif unique : rendre
visibles les resultats reellement produits par la chaine, pour decider
ensuite du design definitif sur pieces plutot que sur intuition.

CE FICHIER NE CALCULE RIEN
---------------------------
Il consomme les parquet deja produits par ai/ et features/. Aucune regle
metier n'est redefinie ici : les red flags viennent du registre de
ai/market_red_flags.py, la jointure des sources vient de
dashboard/market_view.py::load_markets(), les etats de qualite viennent de
features/data_quality.py. Si un chiffre est faux, il est faux en amont —
cette page ne peut pas le corriger, et ne doit pas essayer.

Aucun fichier existant n'est modifie : ni le pipeline, ni les autres
dashboards, ni les parquet.

REGLE APPLIQUEE PARTOUT : UNKNOWN != ZERO
-------------------------------------------
Une valeur absente s'affiche "Non disponible", jamais 0. Un montant
manquant n'est pas un montant nul, un gagnant non identifie n'est pas une
absence de gagnant, et "donnees insuffisantes" n'est pas "risque faible" —
ce sont deux etats distincts, affiches distinctement.

    streamlit run dashboard/validation_app.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from ai.market_red_flags import FLAGS_BY_ID, PRIMARY_FLAGS, REGISTRY  # noqa: E402
from dashboard.market_view import load_markets  # noqa: E402

ANALYTICS = REPO / "data/processed/analytics"
FEATURES_PATH = ANALYTICS / "market_features.parquet"

AVERTISSEMENT = (
    "Les résultats présentés sont des **signaux statistiques destinés à "
    "prioriser l'analyse humaine**. Ils ne constituent pas une preuve de "
    "fraude ou de corruption.")

PRIORITY_ICON = {"Tres prioritaire": "🔴", "Prioritaire": "🟠",
                 "A surveiller": "🟡", "Faible": "🟢",
                 "Donnees insuffisantes": "⚪"}
STATE_ICON = {"KNOWN": "✓", "UNKNOWN": "?", "INVALID": "⚠", "NOT_APPLICABLE": "–"}
FLAG_ICON = {True: "🔴", False: "🟢", None: "⚪"}
FLAG_TEXT = {True: "signal actif", False: "inactif", None: "non évaluable"}

NON_DISPO = "Non disponible"

st.set_page_config(page_title="PMMP — Validation-seule", layout="wide",
                   page_icon="📊")

# CSS volontairement minimal : fond clair, cartes KPI encadrees, accent
# bleu institutionnel. Rien de plus — cette version sert a lire des
# donnees, pas a fixer une identite visuelle.
st.markdown("""
<style>
  .stApp { background-color: #f7f8fa; }
  section[data-testid="stSidebar"] { background-color: #ffffff;
      border-right: 1px solid #e3e6ea; }
  div[data-testid="stMetric"] { background-color: #ffffff;
      border: 1px solid #e3e6ea; border-radius: 8px; padding: 14px 16px; }
  div[data-testid="stMetricValue"] { color: #123a6b; font-size: 1.7rem; }
  h1, h2, h3 { color: #123a6b; }
</style>
""", unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Chargement — aucune logique metier, uniquement de la lecture
# --------------------------------------------------------------------------- #

@st.cache_data(ttl=60)
def load_corpus() -> pd.DataFrame:
    """Les 454 marches du corpus, attribues ET infructueux.

    `load_markets()` ne couvre que les marches attribues (ceux que le
    modele score). Le total du corpus se lit donc ici, pour que le KPI
    "total marches" ne fasse pas disparaitre les marches infructueux.
    """
    return pd.read_parquet(FEATURES_PATH) if FEATURES_PATH.exists() else pd.DataFrame()


def _val(row, col, defaut=NON_DISPO):
    """Valeur affichable, ou 'Non disponible'. Jamais 0 par defaut."""
    if col not in row or row[col] is None:
        return defaut
    v = row[col]
    if isinstance(v, float) and pd.isna(v):
        return defaut
    return v


def _montant(row, col="montant_ttc") -> str:
    v = _val(row, col, None)
    if v is None:
        return NON_DISPO
    return f"{float(v):,.2f} DH".replace(",", " ")


def _entier(row, col) -> str:
    v = _val(row, col, None)
    return NON_DISPO if v is None else str(int(v))


def _gagnant(row) -> str:
    c = row.get("companies")
    if c is None or (hasattr(c, "__len__") and len(c) == 0):
        return "Non identifié"
    return " + ".join(str(x) for x in c)


# --------------------------------------------------------------------------- #
# Tableau partage — pages 2 et 3 utilisent EXACTEMENT le meme composant
# --------------------------------------------------------------------------- #

def build_table(df: pd.DataFrame) -> pd.DataFrame:
    """DataFrame d'affichage. Une valeur absente devient un tiret, jamais 0."""
    def _num(col):
        return df[col] if col in df.columns else pd.Series(index=df.index, dtype="float")

    return pd.DataFrame({
        "Référence": df["reference"].fillna("—"),
        "Objet": df["objet"].fillna("—").astype(str).str.slice(0, 60),
        "Acheteur": df["acheteur_public"].fillna("—").astype(str).str.slice(0, 38),
        "Procédure": df["mode_passation"].fillna("—").astype(str).str.slice(0, 28),
        "Montant TTC": _num("montant_ttc"),
        "Score anomalie": _num("anomaly_score_0_100"),
        "Priorité": df.get("priority_level", pd.Series(index=df.index, dtype="object"))
                      .map(lambda v: "—" if pd.isna(v) else f"{PRIORITY_ICON.get(v, '')} {v}"),
        "Data Quality": _num("data_quality_score"),
        "Red flags": df.apply(
            lambda r: "—" if pd.isna(r.get("red_flags_evaluable"))
            else f"{int(r['red_flag_count'])}/{int(r['red_flags_evaluable'])}", axis=1),
    }, index=df.index)


def render_filters(df: pd.DataFrame, prefixe: str) -> pd.DataFrame:
    """Filtres construits uniquement sur les colonnes reellement presentes."""
    c1, c2, c3 = st.columns([3, 1, 1])
    requete = c1.text_input("Rechercher (référence, objet, acheteur)",
                            key=f"q_{prefixe}", placeholder="ex : 2025, COMMUNE, travaux…")
    annees = sorted(a for a in df["annee"].dropna().unique())
    annee = c2.multiselect("Année", annees, default=annees, key=f"an_{prefixe}")
    procedures = sorted(p for p in df["mode_passation"].dropna().unique())
    proc = c3.multiselect("Procédure", procedures, default=procedures, key=f"pr_{prefixe}")

    c4, c5, c6 = st.columns([1, 1, 1])
    niveaux = [n for n in PRIORITY_ICON if n in set(df.get("priority_level", []))]
    prio = c4.multiselect("Priorité", niveaux, default=niveaux, key=f"pl_{prefixe}")
    flags_dispo = [f.id for f in REGISTRY if f.id in df.columns]
    flag = c5.selectbox("Red flag actif", ["(tous)"] + flags_dispo, key=f"rf_{prefixe}")
    seuil_dq = c6.slider("Data Quality minimum", 0, 100, 0, step=10, key=f"dq_{prefixe}")

    out = df.copy()
    if requete:
        masque = pd.Series(False, index=out.index)
        for col in ("reference", "objet", "acheteur_public"):
            masque |= out[col].astype(str).str.contains(requete, case=False, na=False)
        out = out[masque]
    if annee:
        out = out[out["annee"].isin(annee)]
    if proc:
        out = out[out["mode_passation"].isin(proc)]
    if prio and "priority_level" in out.columns:
        out = out[out["priority_level"].isin(prio)]
    if flag != "(tous)":
        out = out[out[flag] == True]  # noqa: E712
    if seuil_dq > 0 and "data_quality_score" in out.columns:
        # Un marche sans Data Quality n'est pas filtre a 0 : il est ecarte
        # explicitement du filtre, pas note zero.
        out = out[out["data_quality_score"].fillna(-1) >= seuil_dq]
    return out


def render_market_table(df: pd.DataFrame, prefixe: str) -> None:
    """Tableau + panneau de detail. Utilise a l'identique par les pages 2 et 3."""
    filtre = render_filters(df, prefixe)
    st.caption(f"**{len(filtre)} marché(s)** affiché(s) sur {len(df)}.")

    if filtre.empty:
        st.info("Aucun marché ne correspond à ces filtres.")
        return

    table = build_table(filtre)
    evenement = st.dataframe(
        table, use_container_width=True, hide_index=True, height=420,
        on_select="rerun", selection_mode="single-row", key=f"tbl_{prefixe}",
        column_config={
            "Montant TTC": st.column_config.NumberColumn(format="%.2f"),
            "Score anomalie": st.column_config.NumberColumn(format="%.1f"),
            "Data Quality": st.column_config.NumberColumn(format="%.0f"),
        })

    lignes = evenement.selection.rows if evenement and evenement.selection else []
    if not lignes:
        st.info("Sélectionnez une ligne du tableau pour afficher le détail du marché.")
        return
    render_detail(filtre.iloc[lignes[0]])


# --------------------------------------------------------------------------- #
# Panneau de detail
# --------------------------------------------------------------------------- #

def render_detail(row: pd.Series) -> None:
    st.divider()
    st.subheader(f"Détail — {_val(row, 'reference', '(sans référence)')}")

    scorable = row.get("scorable") is True
    c1, c2, c3, c4 = st.columns(4)
    if scorable:
        c1.metric("Score anomalie", f"{row['anomaly_score_0_100']:.1f}")
        niveau = _val(row, "priority_level", "—")
        c2.metric("Priorité", f"{PRIORITY_ICON.get(niveau, '')} {niveau}")
        stab = _val(row, "stability_frequency", None)
        c3.metric("Stabilité", NON_DISPO if stab is None else f"{int(stab)}/10")
    else:
        c1.metric("Score anomalie", "—")
        c2.metric("Priorité", "⚪ Données insuffisantes")
        c3.metric("Stabilité", "—")
    dq = _val(row, "data_quality_score", None)
    c4.metric("Data Quality",
              NON_DISPO if dq is None else f"{dq:.0f}/100 — {row['data_quality_level']}")

    if not scorable:
        st.warning(
            "**Données insuffisantes pour analyser ce marché.** Le modèle ne "
            "produit aucun score. Ce n'est **pas** un risque faible : c'est un "
            "état différent, où les informations disponibles ne permettent pas "
            "de conclure.")

    # --- informations du marche -------------------------------------------- #
    st.markdown("##### Informations du marché")
    g, d = st.columns(2)
    g.markdown(
        f"- **Objet** : {_val(row, 'objet')}\n"
        f"- **Acheteur** : {_val(row, 'acheteur_public')}\n"
        f"- **Procédure** : {_val(row, 'mode_passation')}\n"
        f"- **Secteur** : {_val(row, 'categorie_principale')}\n"
        f"- **Statut** : {_val(row, 'statut')}")
    date = _val(row, "date_ouverture_plis", None)
    d.markdown(
        f"- **Date d'ouverture** : "
        f"{NON_DISPO if date is None else pd.Timestamp(date).strftime('%d/%m/%Y')}\n"
        f"- **Montant TTC** : {_montant(row)}\n"
        f"- **Montant HT** : {_montant(row, 'montant_ht')}\n"
        f"- **Gagnant** : {_gagnant(row)}\n"
        f"- **Soumissionnaires** : {_entier(row, 'nb_soumissionnaires')}\n"
        f"- **Concurrents écartés** : {_entier(row, 'nb_concurrents_ecartes')}")
    st.caption("« Non disponible » signifie que l'information n'a pas été extraite "
               "du document — jamais qu'elle vaut zéro.")

    # --- red flags ---------------------------------------------------------- #
    st.markdown("##### Red flags")
    presents = [f for f in REGISTRY if f.id in row.index]
    if not presents:
        st.info("Red flags non calculés pour ce marché.")
    else:
        for f in presents:
            v = row.get(f.id)
            v = None if v is None or (isinstance(v, float) and pd.isna(v)) else bool(v)
            derive = " *(dérivé)*" if f.derived else ""
            st.markdown(f"{FLAG_ICON[v]} **{f.id} — {f.name}**{derive} · "
                        f"{FLAG_TEXT[v]} · sévérité {f.severity.value}")
            if v is True:
                st.caption(f"　{f.description}")
            elif v is None:
                st.caption("　Non évaluable : l'information nécessaire n'a pas été "
                           "lue dans le document.")
        st.caption("RF04 (écart estimation / attribution) n'existe pas : "
                   "l'estimation est absente de 100 % des marchés attribués.")

    # --- SHAP --------------------------------------------------------------- #
    st.markdown("##### Explication du modèle (SHAP)")
    brut = _val(row, "shap_top_features", None)
    if brut is None:
        st.info("Aucune explication SHAP pour ce marché "
                "(marchés non scorés uniquement).")
    else:
        try:
            noms = json.loads(brut)
            valeurs = json.loads(row["shap_top_values"])
            st.bar_chart(pd.DataFrame({"contribution": valeurs}, index=noms),
                         horizontal=True)
        except (TypeError, ValueError):
            st.caption("Contributions illisibles.")
        st.caption(str(_val(row, "explication_modele", "")))
        accord = _val(row, "accord_shap_ablation", None)
        if accord is not None:
            st.caption(f"Cohérence SHAP / ablation sur le Top 3 : **{accord:.0%}**.")

    # --- qualite des donnees ------------------------------------------------ #
    st.markdown("##### Qualité des données")
    dims = [("Montant", "dq_montant"), ("Concurrence", "dq_concurrents"),
            ("Exclusions", "dq_exclusions"), ("Date", "dq_date"),
            ("Gagnant", "dq_gagnant")]
    lignes = []
    for label, col in dims:
        etat = _val(row, col, None)
        if etat is None:
            continue
        lignes.append(f"{STATE_ICON.get(str(etat), '?')} **{label}** — {etat}")
    if lignes:
        st.markdown("  \n".join(lignes))
        st.caption("KNOWN = lu dans le document · UNKNOWN = absent · "
                   "INVALID = lu mais incohérent · NOT_APPLICABLE = sans objet.")
    else:
        st.info("Data Quality non disponible pour ce marché.")

    if row.get("extraction_warning"):
        st.warning("L'extraction de ce marché a produit des avertissements : "
                   "score à lire avec prudence.")


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #

def page_vue_generale(corpus: pd.DataFrame, marches: pd.DataFrame) -> None:
    st.title("Vue générale")
    st.caption("Synthèse du corpus et des signaux produits par la chaîne d'analyse.")

    total = len(corpus)
    attribues = int((corpus["statut"] == "ATTRIBUE").sum()) if total else 0
    scores = marches[marches["scorable"] == True] if not marches.empty else marches  # noqa: E712
    insuffisants = len(marches) - len(scores) if not marches.empty else 0
    atypiques = int(scores["is_anomaly"].sum()) if len(scores) else 0
    dq_moyen = corpus_dq = None
    if "data_quality_score" in marches.columns and not marches.empty:
        dq_moyen = marches["data_quality_score"].mean()
        corpus_dq = marches["data_quality_level"].mode()
        corpus_dq = corpus_dq.iloc[0] if len(corpus_dq) else None

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total marchés", total,
              help=f"{attribues} attribués, {total - attribues} infructueux.")
    c2.metric("Marchés analysés", len(scores),
              help="Marchés effectivement scorés par le modèle.")
    c3.metric("Marchés atypiques", atypiques,
              help="Signalés par le modèle pour une analyse humaine.")
    c4.metric("Données insuffisantes", insuffisants,
              help="Analyse non fiable — état distinct d'un risque faible.")
    c5.metric("Qualité moyenne",
              NON_DISPO if dq_moyen is None or pd.isna(dq_moyen)
              else f"{dq_moyen:.0f}/100" + (f" — {corpus_dq}" if corpus_dq else ""))

    st.info(AVERTISSEMENT)
    st.divider()

    g1, g2 = st.columns(2)
    with g1:
        st.markdown("##### Marchés par année")
        par_annee = corpus.groupby("annee").size()
        st.bar_chart(par_annee)
        st.caption(f"{total} marchés au total. La dernière année du corpus est "
                   "tronquée (collecte arrêtée en cours d'année).")
    with g2:
        st.markdown("##### Répartition des procédures")
        proc = corpus["mode_passation"].value_counts()
        st.bar_chart(proc, horizontal=True)
        st.caption(f"{len(proc)} procédures présentes ; les deux premières "
                   f"couvrent {100 * proc.head(2).sum() / total:.0f} % du corpus.")

    if "priority_level" in marches.columns and not marches.empty:
        st.markdown("##### Priorité d'analyse")
        dist = marches["priority_level"].value_counts()
        st.bar_chart(dist)
        st.caption("« Données insuffisantes » est un état distinct, jamais "
                   "assimilé à une priorité faible.")


def page_marches(marches: pd.DataFrame) -> None:
    st.title("Marchés publics")
    st.caption("Tous les marchés attribués disponibles dans le corpus.")
    render_market_table(marches, prefixe="tous")


def page_anomalies(marches: pd.DataFrame) -> None:
    st.title("Marchés atypiques")
    st.caption("Marchés actuellement signalés par le modèle pour une analyse humaine.")
    st.info(AVERTISSEMENT)

    # PREREGLAGE de la page 2 : meme composant, meme code, filtre pose en amont.
    signales = marches[marches["is_anomaly"] == True]  # noqa: E712
    insuffisants = int((marches["scorable"] != True).sum())  # noqa: E712

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Marchés signalés", len(signales))
    if len(signales):
        c2.metric("Score maximum", f"{signales['anomaly_score_0_100'].max():.1f}")
        c3.metric("Score moyen", f"{signales['anomaly_score_0_100'].mean():.1f}")
    else:
        c2.metric("Score maximum", "—")
        c3.metric("Score moyen", "—")
    c4.metric("Données insuffisantes", insuffisants,
              help="Non scorés — état distinct d'un risque faible.")

    st.divider()
    if signales.empty:
        st.info("Aucun marché signalé.")
        return
    render_market_table(signales, prefixe="atypiques")


# --------------------------------------------------------------------------- #
def main() -> None:
    st.sidebar.markdown("### PMMP")
    st.sidebar.caption("Validation-seule")
    page = st.sidebar.radio(
        "Navigation",
        ["Vue générale", "Marchés publics", "Marchés atypiques"],
        label_visibility="collapsed")
    st.sidebar.divider()
    st.sidebar.caption(
        "**Version de validation.** Sert à visualiser les résultats réels de la "
        "chaîne avant de concevoir l'interface définitive. Aucun calcul n'est "
        "fait ici : toutes les valeurs proviennent des artefacts du pipeline.")

    corpus = load_corpus()
    marches = load_markets()

    if corpus.empty or marches.empty:
        st.error("Artefacts absents. Lancer la chaîne d'analyse "
                 "(`bigdata/spark/jobs/`, puis `ai/`) avant d'ouvrir cette page.")
        return

    if page == "Vue générale":
        page_vue_generale(corpus, marches)
    elif page == "Marchés publics":
        page_marches(marches)
    else:
        page_anomalies(marches)


main()
