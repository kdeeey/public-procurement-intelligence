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
from dashboard.detail_panel import market_title, winner_text  # noqa: E402

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


def _etrp_marche_cell(row: pd.Series) -> str:
    """"Entreprise / Marché" — combine les deux identifiants deja affiches
    separement (colonne Entreprise et colonne Reference) sans recalculer
    quoi que ce soit : reutilise `detail_panel.winner_text`/`market_title`."""
    return f"{winner_text(row)} / {market_title(row)}"


def _info_dispo_cell(row: pd.Series) -> str:
    """Regroupe les informations deja affichees ailleurs dans le tableau
    (procedure, categorie, date d'ouverture, lot) en une seule cellule de
    synthese. Aucune nouvelle donnee : uniquement des colonnes deja lues
    par `data_access.table_frame()`."""
    parts = []
    procedure = row.get("mode_passation")
    if not ds.is_missing(procedure):
        parts.append(str(procedure))
    categorie = row.get("categorie_principale")
    if not ds.is_missing(categorie):
        parts.append(str(categorie))
    date = row.get("date_ouverture_plis")
    if not ds.is_missing(date):
        parts.append(f"Ouverture {date}")
    lot = row.get("lot_numero")
    if not ds.is_missing(lot):
        parts.append(f"Lot {int(lot)}")
    if not parts:
        return ds.MISSING_GENERIC
    return _truncate(" · ".join(parts), 90)


def _concurrents_cell(value) -> str:
    if ds.is_missing(value):
        return ds.MISSING_GENERIC
    return str(int(value))


def _anomaly_cell(row: pd.Series) -> str:
    """Oui/Non lu tel quel dans `is_anomaly` (logique de
    `ai/train_market_model.py`, non recalculee). Un marche non scorable a
    `is_anomaly=False` par construction du pipeline — ce n'est pas une
    absence d'anomalie mais une absence d'evaluation, donc N/A plutot que
    Non."""
    if not bool(row.get("scorable", False)):
        return "N/A"
    value = row.get("is_anomaly")
    if ds.is_missing(value):
        return "N/A"
    return "Oui" if bool(value) else "Non"


def _score_sur3_cell(row: pd.Series) -> str:
    """`priority_flag_count`/3, calcule dans `ai/market_red_flags.py`. N/A
    quand moins de 2 des 3 red flags prioritaires sont evaluables — le meme
    seuil que la gate de scorabilite existante, pas un nouveau seuil."""
    count, evaluable = row.get("priority_flag_count"), row.get("priority_flags_evaluable")
    if ds.is_missing(count) or ds.is_missing(evaluable) or evaluable < 2:
        return "N/A"
    return f"{int(count)}/3"


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
        base.insert(1 if icon else 0, "Entreprise / Marché",
                    df.apply(_etrp_marche_cell, axis=1).values)
        base["Toute info dispo"] = df.apply(_info_dispo_cell, axis=1).values
        base["Procédure"] = df["mode_passation"].apply(
            lambda v: _truncate(v, 30)).values
        base["Entreprise"] = df.apply(winner_text, axis=1).values
        base["Montant TTC"] = df["montant_ttc"].apply(ds.fmt_montant).values
        base["Concurrents"] = df["nb_soumissionnaires"].apply(_concurrents_cell).values
        base["Anomaly (Oui/Non)"] = df.apply(_anomaly_cell, axis=1).values
        base["Red flags"] = df.apply(_flag_cell, axis=1).values
        base["Score (/3)"] = df.apply(_score_sur3_cell, axis=1).values
        base["Commentaires"] = df["priority_level"].apply(
            lambda v: ds.priority_display(v) if not ds.is_missing(v)
            else "Non applicable").values
        base["Qualité"] = df.apply(
            lambda r: (f"{ds.fmt_score(r.get('data_quality_score'), 0, '—')} · "
                       f"{ds.quality_display(r.get('data_quality_level'))}")
            if not ds.is_missing(r.get("data_quality_level")) else ds.MISSING_GENERIC,
            axis=1).values
        base["Data Quality"] = df["data_quality_level"].apply(
            lambda v: ds.quality_display(v) if not ds.is_missing(v)
            else ds.MISSING_GENERIC).values
    else:  # variant == "anomalies"
        base["Priorité"] = df["priority_level"].apply(
            lambda v: ds.priority_display(v) if not ds.is_missing(v)
            else "Non applicable").values
        base["Red flags"] = df.apply(_flag_cell, axis=1).values
        base["Score (diagnostic)"] = df["anomaly_score_0_100"].apply(
            lambda v: ds.fmt_score(v, 1, "—")).values
        base["Stabilité"] = df["stability_frequency"].apply(_stability_cell).values
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
                         "Sans référence", "Non applicable", "N/A", "—") else ""
                for v in col]

    styler = display.style
    for col in ["Priorité", "Commentaires"]:
        if col in display.columns:
            styler = styler.apply(_prio_css, subset=[col])
    for col in ["Qualité", "Data Quality"]:
        if col in display.columns:
            styler = styler.apply(_qual_css, subset=[col])
    for col in ["Référence", "Montant TTC", "Score (diagnostic)", "Stabilité", "Red flags",
                "Entreprise / Marché", "Toute info dispo", "Entreprise", "Concurrents",
                "Anomaly (Oui/Non)", "Score (/3)"]:
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
    "Score (diagnostic)": st.column_config.TextColumn(
        "Score (diagnostic)", width="small",
        help="Score du modèle (entraîné sur RF01/RF02/RF03), 0-100. Ne décide "
             "jamais la priorité — il ne fait que départager des marchés à "
             "égalité de red flags actifs. Voir la colonne « Red flags »."),
    "Stabilité": st.column_config.TextColumn(
        "Stabilité", width="small",
        help="Nombre de réentraînements (sur 10) où ce marché ressort dans le "
             "Top 20. 0 signifie « jamais entré dans un Top 20 », pas « instable »."),
    "Entreprise / Marché": st.column_config.TextColumn(
        "Entreprise / Marché", width="medium",
        help="Attributaire (ou « Non identifié ») et référence du marché, "
             "affichés ensemble pour repérer la ligne d'un coup d'œil."),
    "Toute info dispo": st.column_config.TextColumn(
        "Toute info dispo", width="large",
        help="Synthèse des informations déjà disponibles sur le marché "
             "(procédure, catégorie, date d'ouverture des plis, lot). "
             "Le détail complet reste dans la fiche du marché."),
    "Entreprise": st.column_config.TextColumn(
        "Entreprise", width="medium",
        help="Attributaire lu dans le document. « Non identifié » quand le "
             "document ne permet pas de l'extraire de façon fiable."),
    "Concurrents": st.column_config.TextColumn(
        "Concurrents", width="small",
        help="Nombre de soumissionnaires. Le projet ne dispose pas des noms "
             "des concurrents, seulement de leur nombre."),
    "Anomaly (Oui/Non)": st.column_config.TextColumn(
        "Anomaly (Oui/Non)", width="small",
        help="Résultat du modèle d'anomalie (entraîné sur RF01/RF02/RF03). "
             "N/A quand le marché n'est pas scorable, jamais assimilé à « Non »."),
    "Score (/3)": st.column_config.TextColumn(
        "Score (/3)", width="small",
        help="Nombre de red flags prioritaires actifs (RF01/RF02/RF03) sur 3. "
             "N/A quand moins de 2 des 3 sont évaluables."),
    "Commentaires": st.column_config.TextColumn(
        "Commentaires", width="small",
        help="Interprétation du résultat, reprise du niveau de priorité déjà "
             "calculé (colonne « Priorité »). « Données insuffisantes » est un "
             "état distinct, pas un niveau faible."),
    "Data Quality": st.column_config.TextColumn(
        "Data Quality", width="small",
        help="Niveau de qualité des données déjà calculé (colonne « Qualité »), "
             "sans le score numérique."),
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
