"""
Tableau de marches partage — filtres, rendu et selection de ligne.

La maquette utilise le meme tableau a trois endroits (Marches publics,
onglet "Vue tableau des marches", Anomalies et priorites) avec deux jeux de
colonnes. Il vit donc ici une seule fois, parametre par son jeu de
colonnes, et les trois vues l'appellent.

CONTRAINTE STREAMLIT ASSUMEE, DEJA ANTICIPEE PAR LE BRIEF
-----------------------------------------------------------
`dashboard.md` Sec 11 note que les cellules HTML riches dans un tableau
natif sont hors de portee de Streamlit. Le clic de ligne, lui, est
indispensable — c'est ce qui ouvre le panneau de detail. On garde donc
`st.dataframe(on_select="rerun")` pour le clic, et on obtient les pastilles
colorees de la maquette par un `Styler` pandas : fond et texte teintes par
cellule sur les colonnes Priorite et Qualite, italique gris sur les valeurs
non extraites. Les codes de red flag restent textuels.

LES FILTRES SONT CONSTRUITS DEPUIS LES DONNEES
-----------------------------------------------
Aucune liste de modalites n'est ecrite ici : `data_access.filter_options()`
les lit dans le corpus charge. Si une procedure disparait du corpus, elle
disparait du filtre.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard import data_access as da  # noqa: E402
from dashboard import design_system as ds  # noqa: E402

OBJET_MAX = 78          # troncature mesuree : mediane 124 car., p90 281
ACHETEUR_MAX = 46       # mediane 60 car.

PRIMARY_FLAG_CODES = ("RF01", "RF02", "RF03", "RF05")


# --------------------------------------------------------------------------- #
# Filtres
# --------------------------------------------------------------------------- #

def render_filters(key_prefix: str) -> dict:
    """Barre de recherche + 5 filtres + reinitialisation.

    Renvoie l'etat courant des filtres. "Toutes"/"Tous" est ajoute en tete
    de chaque liste, le reste vient des valeurs presentes dans les donnees.
    """
    opts = da.filter_options()
    state_keys = [f"{key_prefix}_q", f"{key_prefix}_an", f"{key_prefix}_proc",
                  f"{key_prefix}_cat", f"{key_prefix}_prio", f"{key_prefix}_qual"]

    if st.session_state.pop(f"{key_prefix}_reset", False):
        for k in state_keys:
            st.session_state.pop(k, None)

    with ds.card():
        query = st.text_input(
            "Rechercher", key=state_keys[0], label_visibility="collapsed",
            placeholder="Rechercher un marché, un objet, un organisme…")

        c1, c2, c3, c4, c5, c6 = st.columns([1, 1.3, 1.1, 1.2, 1.2, 0.8])
        annee = c1.selectbox("Année", ["Toutes"] + [str(a) for a in opts["annee"]],
                             key=state_keys[1])
        proc = c2.selectbox("Procédure", ["Toutes"] + opts["procedure"], key=state_keys[2])
        cat = c3.selectbox("Catégorie", ["Toutes"] + opts["categorie"], key=state_keys[3])
        prio = c4.selectbox(
            "Priorité", ["Toutes"] + opts["priorite"], key=state_keys[4],
            format_func=lambda v: v if v == "Toutes" else ds.priority_display(v))
        qual = c5.selectbox(
            "Qualité des données", ["Toutes"] + opts["qualite"], key=state_keys[5],
            format_func=lambda v: v if v == "Toutes" else ds.quality_display(v))
        c6.markdown('<div style="height:26px"></div>', unsafe_allow_html=True)
        if c6.button("Réinitialiser", key=f"{key_prefix}_reset_btn",
                     use_container_width=True):
            st.session_state[f"{key_prefix}_reset"] = True
            st.rerun()

    return {"q": query, "annee": annee, "proc": proc, "cat": cat,
            "prio": prio, "qual": qual}


def apply_filters(df: pd.DataFrame, f: dict) -> pd.DataFrame:
    out = df
    needle = (f.get("q") or "").strip().lower()
    if needle:
        hay = (out["reference"].fillna("").astype(str) + " "
               + out["objet"].fillna("").astype(str) + " "
               + out["acheteur_public"].fillna("").astype(str)).str.lower()
        out = out[hay.str.contains(needle, regex=False, na=False)]
    if f.get("annee", "Toutes") != "Toutes":
        out = out[out["annee"].astype("Int64").astype(str) == f["annee"]]
    if f.get("proc", "Toutes") != "Toutes":
        out = out[out["mode_passation"] == f["proc"]]
    if f.get("cat", "Toutes") != "Toutes":
        out = out[out["categorie_principale"] == f["cat"]]
    if f.get("prio", "Toutes") != "Toutes":
        out = out[out["priority_level"] == f["prio"]]
    if f.get("qual", "Toutes") != "Toutes":
        out = out[out["data_quality_level"] == f["qual"]]
    return out


def sort_by_priority(df: pd.DataFrame) -> pd.DataFrame:
    """Tri par priorite decroissante, puis par score d'anomalie.

    Les marches sans priorite (infructueux, non scores) passent en fin de
    liste sans etre masques : les cacher reviendrait a dissimuler une
    limite du systeme.
    """
    if df.empty:
        return df
    out = df.copy()
    order = {p: i for i, p in enumerate(ds.PRIORITY_ORDER)}
    out["_prio_rank"] = out["priority_level"].map(order).fillna(len(order))
    out["_score"] = pd.to_numeric(out.get("priority_score"), errors="coerce").fillna(-1)
    out["_ano"] = pd.to_numeric(out.get("anomaly_score_0_100"),
                                errors="coerce").fillna(-1)
    return (out.sort_values(["_prio_rank", "_score", "_ano"],
                            ascending=[True, False, False])
            .drop(columns=["_prio_rank", "_score", "_ano"]))


# --------------------------------------------------------------------------- #
# Mise en forme des cellules
# --------------------------------------------------------------------------- #

def _truncate(value, limit: int) -> str:
    text = ds.fmt_texte(value, "—")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _flag_cell(row: pd.Series) -> str:
    """"actifs / évaluables · codes actifs".

    Le denominateur porte l'information de non-evaluabilite : 2/4 et 2/2
    ne disent pas la meme chose. La regle est rappelee dans l'aide de la
    colonne, jamais laissee a deviner.
    """
    count, evaluable = row.get("red_flag_count"), row.get("red_flags_evaluable")
    if ds.is_missing(count) or ds.is_missing(evaluable):
        return "Non applicable"
    actifs = [c for c in PRIMARY_FLAG_CODES
              if ds.flag_state(row.get(c)) == "active"]
    base = f"{int(count)}/{int(evaluable)}"
    return f"{base} · {' '.join(actifs)}" if actifs else base


def _stability_cell(value) -> str:
    if ds.is_missing(value):
        return ds.MISSING_GENERIC
    return f"{int(value)}/10"


def build_display(df: pd.DataFrame, variant: str) -> pd.DataFrame:
    """DataFrame d'affichage. Une valeur absente devient un libelle
    explicite, jamais 0 ni une chaine vide."""
    ref = df.apply(lambda r: ds.display_reference(r.get("reference"), r), axis=1)

    base = pd.DataFrame({
        "Référence": ref.values,
        "Objet": df["objet"].apply(lambda v: _truncate(v, OBJET_MAX)).values,
        "Acheteur": df["acheteur_public"].apply(
            lambda v: _truncate(v, ACHETEUR_MAX)).values,
    })

    # L'icone de marche, a gauche de chaque ligne comme dans la maquette.
    # `st.dataframe` ne rend pas de HTML dans une cellule : la colonne est
    # declaree en `ImageColumn` et recoit un data URI. Si l'asset manque,
    # la colonne n'est simplement pas creee.
    icon = ds.market_icon_uri()
    if icon:
        base.insert(0, "", [icon] * len(base))

    if variant == "catalogue":
        base["Procédure"] = df["mode_passation"].apply(
            lambda v: _truncate(v, 30)).values
        base["Montant TTC"] = df["montant_ttc"].apply(ds.fmt_montant).values
        base["Priorité"] = df["priority_level"].apply(
            lambda v: ds.priority_display(v) if not ds.is_missing(v)
            else "Non applicable").values
        base["Qualité"] = df.apply(
            lambda r: (f"{ds.fmt_score(r.get('data_quality_score'), 0, '—')} · "
                       f"{ds.quality_display(r.get('data_quality_level'))}")
            if not ds.is_missing(r.get("data_quality_level")) else ds.MISSING_GENERIC,
            axis=1).values
        base["Red flags"] = df.apply(_flag_cell, axis=1).values
    else:  # variant == "anomalies"
        base["Priorité"] = df["priority_level"].apply(
            lambda v: ds.priority_display(v) if not ds.is_missing(v)
            else "Non applicable").values
        base["Score"] = df["anomaly_score_0_100"].apply(
            lambda v: ds.fmt_score(v, 1, "—")).values
        base["Stabilité"] = df["stability_frequency"].apply(_stability_cell).values
        base["Red flags"] = df.apply(_flag_cell, axis=1).values
        base["Qualité"] = df.apply(
            lambda r: (f"{ds.fmt_score(r.get('data_quality_score'), 0, '—')} · "
                       f"{ds.quality_display(r.get('data_quality_level'))}")
            if not ds.is_missing(r.get("data_quality_level")) else ds.MISSING_GENERIC,
            axis=1).values
    return base


def _style(display: pd.DataFrame, source: pd.DataFrame):
    """Teinte les colonnes Priorite et Qualite avec la semantique du design.

    "Données insuffisantes" recoit le role neutre `none` : ni le vert de
    "Faible", ni un rouge. Une valeur non extraite passe en italique gris.
    """
    prio_roles = source["priority_level"].map(ds.PRIORITY_ROLE)
    qual_levels = source["data_quality_level"]

    def _prio_css(col: pd.Series) -> list[str]:
        out = []
        for role in prio_roles:
            if ds.is_missing(role):
                out.append(f"color:{ds.TOKENS['n500']};font-style:italic")
            else:
                k = ds.RISK[role]
                out.append(f"background-color:{k['bg']};color:{k['text']};"
                           f"font-weight:500")
        return out

    def _qual_css(col: pd.Series) -> list[str]:
        out = []
        for level in qual_levels:
            style = ds.QUALITY_STYLE.get(level)
            if style is None:
                out.append(f"color:{ds.TOKENS['n500']};font-style:italic")
            else:
                out.append(f"background-color:{style['bg']};color:{style['c']};"
                           f"font-weight:500")
        return out

    def _missing_css(col: pd.Series) -> list[str]:
        return [f"color:{ds.TOKENS['n500']};font-style:italic"
                if v in (ds.MISSING_TEXT, ds.MISSING_GENERIC, ds.MISSING_ID,
                         "Sans référence", "Non applicable", "—") else ""
                for v in col]

    styler = display.style
    if "Priorité" in display.columns:
        styler = styler.apply(_prio_css, subset=["Priorité"])
    if "Qualité" in display.columns:
        styler = styler.apply(_qual_css, subset=["Qualité"])
    for col in ["Référence", "Montant TTC", "Score", "Stabilité", "Red flags"]:
        if col in display.columns:
            styler = styler.apply(_missing_css, subset=[col])
    return styler


COLUMN_CONFIG = {
    "": st.column_config.ImageColumn("", width="small",
                                     help="Marché public — un lot du corpus"),
    "Référence": st.column_config.TextColumn("Référence", width="small"),
    "Objet": st.column_config.TextColumn(
        "Objet", width="large",
        help="Tronqué à l'affichage — l'objet fait 124 caractères de médiane. "
             "Le texte complet est dans la fiche du marché."),
    "Acheteur": st.column_config.TextColumn("Acheteur", width="medium"),
    "Procédure": st.column_config.TextColumn("Procédure", width="small"),
    "Montant TTC": st.column_config.TextColumn(
        "Montant TTC", width="small",
        help="« Non extrait » signifie que le document ne porte pas le montant, "
             "jamais qu'il vaut zéro."),
    "Priorité": st.column_config.TextColumn(
        "Priorité", width="small",
        help="Ordre de lecture, pas un verdict. « Données insuffisantes » est un "
             "état distinct, pas un niveau faible."),
    "Qualité": st.column_config.TextColumn(
        "Qualité", width="small",
        help="Qualité de l'information extraite du document, et non qualité ou "
             "régularité du marché."),
    "Red flags": st.column_config.TextColumn(
        "Red flags", width="small",
        help="Règles actives / règles évaluables, puis les codes actifs. Un "
             "dénominateur inférieur au nombre total de règles signale des "
             "règles non évaluables faute d'information lisible."),
    "Score": st.column_config.TextColumn(
        "Score", width="small", help="Score d'anomalie 0-100 du modèle."),
    "Stabilité": st.column_config.TextColumn(
        "Stabilité", width="small",
        help="Nombre de réentraînements (sur 10) où ce marché ressort dans le "
             "Top 20. 0 signifie « jamais entré dans un Top 20 », pas « instable »."),
}


# --------------------------------------------------------------------------- #
# Rendu
# --------------------------------------------------------------------------- #

def render_table(df: pd.DataFrame, key: str, variant: str = "catalogue",
                 height: int = 460):
    """Affiche le tableau et renvoie l'`award_id` de la ligne selectionnee,
    ou None. La selection est ce qui ouvre le panneau de detail."""
    if df.empty:
        ds.render_empty_state(
            "Aucun marché ne correspond à ces critères",
            "Élargissez la recherche ou réinitialisez les filtres.")
        return None

    display = build_display(df, variant)
    event = st.dataframe(
        _style(display, df.reset_index(drop=True)),
        hide_index=True, use_container_width=True, height=height,
        on_select="rerun", selection_mode="single-row", key=key,
        column_config={k: v for k, v in COLUMN_CONFIG.items()
                       if k in display.columns})

    # Le petit repere dans la marge gauche de chaque ligne est le marqueur de
    # selection natif de `st.dataframe` (bibliotheque Streamlit) : il
    # apparait des qu'une selection de ligne est activee et ne peut pas etre
    # masque sans abandonner la selection native. Ce n'est pas une case a
    # cocher multi-selection : un seul clic n'importe ou sur la ligne ouvre
    # la fiche, ce repere ne pilote rien de plus.
    ds.render_caption(
        "Le repere dans la marge gauche vient du tableau Streamlit — il ne "
        "sert pas a cocher plusieurs marches. Cliquer n'importe où sur une "
        "ligne ouvre sa fiche.")

    rows = event.selection.rows if event and event.selection else []
    if not rows:
        return None
    return df.reset_index(drop=True).iloc[rows[0]]["award_id"]
