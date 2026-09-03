"""
Panneau de detail d'un marche — le "slide-over" de la maquette.

UN SEUL COMPOSANT, TROIS POINTS D'APPEL
----------------------------------------
La maquette fait glisser le meme panneau depuis la droite depuis trois
endroits : "Marches publics", l'onglet "Vue tableau des marches" de la Vue
generale, et "Anomalies et priorites". Le composant vit donc ici une seule
fois et les trois vues l'appellent — le dupliquer aurait garanti qu'il
diverge.

COMPROMIS TECHNIQUE ASSUME
---------------------------
Streamlit n'a pas de tiroir lateral natif. `st.dialog` est la primitive la
plus proche : c'est une vraie surface modale, avec fond assombri,
fermeture au clic exterieur et a l'echap, et elle survit au re-run du
script. Elle s'ouvre centree ; `dashboard/design_system.py` la repositionne
contre le bord droit sur toute la hauteur et lui ajoute la transition
d'entree. Le rendu final est celui de la maquette ; le compromis est que
la position vient d'une surcharge CSS de la structure de Streamlit, donc
une refonte du DOM de Streamlit pourrait la faire retomber au centre. Le
contenu resterait intact.

TOUT VIENT DES DONNEES REELLES
-------------------------------
Les noms, descriptions et severites des red flags sont lus dans le registre
de `ai/market_red_flags.py`, jamais recopies : la maquette nommait RF05
"Attribution repetee" et donnait a RF02 une severite elevee, deux libelles
faux que le registre corrige. Les etats de qualite viennent des colonnes
`dq_*` produites par `features/data_quality.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard import design_system as ds  # noqa: E402

SEVERITY_LABEL = {"elevee": "sévérité élevée", "moyenne": "sévérité moyenne",
                  "faible": "sévérité faible"}

STATUT_DISPLAY = {"ATTRIBUE": "Attribué", "INFRUCTUEUX": "Infructueux",
                  "OFFRE_EXCESSIVE": "Offre excessive"}

DIMENSION_LABEL = {"montant": "Montant", "concurrents": "Concurrence",
                   "exclusions": "Exclusions", "date": "Date d'ouverture",
                   "gagnant": "Attributaire"}


# --------------------------------------------------------------------------- #
# Lecture du registre reel
# --------------------------------------------------------------------------- #

def red_flag_registry() -> list[dict]:
    """Le registre de `ai/market_red_flags.py`, ou une liste vide si le
    module n'est pas importable — la page reste affichable sans lui."""
    try:
        from ai.market_red_flags import REGISTRY
    except Exception:  # noqa: BLE001
        return []
    return [{"id": f.id, "name": f.name, "desc": f.description,
             "sev": SEVERITY_LABEL.get(f.severity.value, f.severity.value),
             "derived": f.derived} for f in REGISTRY]


def market_row(markets: pd.DataFrame, award_id) -> pd.Series | None:
    if markets.empty or award_id is None:
        return None
    hit = markets[markets["award_id"] == award_id]
    return None if hit.empty else hit.iloc[0]


# --------------------------------------------------------------------------- #
# Fragments de contenu — reutilises par le panneau ET par la page XAI
# --------------------------------------------------------------------------- #

def market_title(row: pd.Series) -> str:
    base = ds.display_reference(row.get("reference"), row)
    lot = row.get("lot_numero")
    return base if ds.is_missing(lot) else f"{base} · Lot {int(lot)}"


def winner_text(row: pd.Series) -> str:
    """Attributaire lu dans le document, ou "Non identifié".

    Jamais une chaine vide : 35 % des marches attribues n'ont pas de
    titulaire lisible, et cette absence doit se voir.
    """
    companies = row.get("companies")
    if companies is None:
        return ds.MISSING_ID
    try:
        names = [str(c) for c in companies if c is not None and str(c).strip()]
    except TypeError:
        return ds.MISSING_ID
    return " + ".join(names) if names else ds.MISSING_ID


def identification_fields(row: pd.Series) -> list[tuple[str, str, bool]]:
    """[(libelle, valeur affichee, valeur_presente)] — le drapeau de
    presence pilote le style : une absence s'affiche en italique gris."""
    ref = row.get("reference")
    ref_display = ds.display_reference(ref, row)
    lot = row.get("lot_numero")
    fields = [
        ("Référence", ref_display, ref_display != "Sans référence"),
        ("Lot", ds.MISSING_GENERIC if ds.is_missing(lot) else f"Lot {int(lot)}",
         not ds.is_missing(lot)),
        ("Acheteur public", ds.fmt_texte(row.get("acheteur_public")),
         not ds.is_missing(row.get("acheteur_public"))),
        ("Procédure", ds.fmt_texte(row.get("mode_passation")),
         not ds.is_missing(row.get("mode_passation"))),
        ("Catégorie", ds.fmt_texte(row.get("categorie_principale")),
         not ds.is_missing(row.get("categorie_principale"))),
        ("Année", ds.fmt_int(row.get("annee"), ds.MISSING_GENERIC),
         not ds.is_missing(row.get("annee"))),
        ("Statut", STATUT_DISPLAY.get(row.get("statut"),
                                      ds.fmt_texte(row.get("statut"))),
         not ds.is_missing(row.get("statut"))),
        ("Date d'ouverture", ds.fmt_date(row.get("date_ouverture_plis")),
         not ds.is_missing(row.get("date_ouverture_plis"))),
        ("Montant TTC", ds.fmt_montant(row.get("montant_ttc")),
         not ds.is_missing(row.get("montant_ttc"))),
        ("Montant HT", ds.fmt_montant(row.get("montant_ht")),
         not ds.is_missing(row.get("montant_ht"))),
        ("Attributaire", winner_text(row), winner_text(row) != ds.MISSING_ID),
        ("Soumissionnaires", ds.fmt_int(row.get("nb_soumissionnaires")),
         not ds.is_missing(row.get("nb_soumissionnaires"))),
        ("Concurrents écartés", ds.fmt_int(row.get("nb_concurrents_ecartes")),
         not ds.is_missing(row.get("nb_concurrents_ecartes"))),
    ]
    return fields


def peer_rows(row: pd.Series) -> list[tuple[str, str, bool]] | None:
    """La comparaison aux marches comparables, ou None si elle n'existe pas.

    Aucune mediane n'est inventee : quand `amount_vs_peer_median` est
    absent, le bloc entier est remplace par un etat vide explicite. La
    mediane du groupe est DEDUITE du ratio (ratio = montant / mediane,
    voir `ai/market_peer_analysis.py::_compare`), donc exacte, jamais
    estimee.
    """
    level = row.get("peer_group_level")
    if ds.is_missing(level) or level == "NOT_ENOUGH_PEERS":
        return None
    ratio = row.get("amount_vs_peer_median")
    montant = row.get("montant_ttc")
    out = [
        ("Groupe de comparaison", ds.fmt_texte(row.get("peer_group_key")), True),
        ("Niveau de regroupement", ds.fmt_texte(level), True),
        ("Marchés comparables", ds.fmt_int(row.get("n_peers"), ds.MISSING_GENERIC),
         not ds.is_missing(row.get("n_peers"))),
    ]
    if ds.is_missing(ratio) or ds.is_missing(montant) or float(ratio) == 0:
        out.append(("Montant comparé",
                    "Non comparable — moins de comparables portant un montant",
                    False))
        return out
    mediane = float(montant) / float(ratio)
    pct = row.get("amount_percentile_peer")
    out += [
        ("Comparables portant un montant",
         ds.fmt_int(row.get("n_peers_amount"), ds.MISSING_GENERIC), True),
        ("Médiane du groupe", ds.fmt_montant(mediane), True),
        ("Ce marché", ds.fmt_montant(montant), True),
        ("Écart à la médiane", f"{(float(ratio) - 1) * 100:+.0f} %".replace(".", ","),
         True),
    ]
    if not ds.is_missing(pct):
        out.append(("Position",
                    f"au-dessus de {float(pct) * 100:.0f} % des comparables", True))
    p90 = row.get("amount_above_peer_p90")
    if not ds.is_missing(p90):
        out.append(("Par rapport au P90 du groupe",
                    "au-delà du P90" if bool(p90) else "sous le P90", True))
    return out


def extraction_warnings(row: pd.Series) -> list[str]:
    """Avertissements REELS : le drapeau d'extraction du pipeline, plus une
    ligne par dimension lue mais incohérente. Rien n'est rédigé au-delà de
    ce que les colonnes portent."""
    out: list[str] = []
    if bool(row.get("extraction_warning") or 0):
        out.append("L'extraction de ce document a produit au moins un "
                   "avertissement : la segmentation en lots ou le nettoyage du "
                   "texte a signalé une incertitude.")
    for key, label in DIMENSION_LABEL.items():
        if row.get(f"dq_{key}") == "INVALID":
            out.append(f"{label} : information lue dans le document mais "
                       f"incohérente. À vérifier sur le PV source avant toute "
                       f"interprétation.")
    ref = row.get("reference")
    if ds.is_missing(ref):
        out.append("Référence absente du document : le marché est identifié par "
                   "son identifiant interne de lot.")
    elif ds.is_suspicious_reference(ref, row):
        out.append("Référence lue dans le document mais rejetée à l'affichage : "
                   "la valeur extraite ne ressemble pas à une référence de "
                   "marché. Le marché est identifié par son identifiant interne "
                   "de lot.")
    return out


# --------------------------------------------------------------------------- #
# Rendu HTML des blocs
# --------------------------------------------------------------------------- #

def _fields_grid(fields: list[tuple[str, str, bool]], columns: int = 2) -> str:
    cells = []
    for label, value, present in fields:
        style = (f'font-size:12.5px;margin-top:3px;line-height:1.4;'
                 f'font-weight:{"500" if present else "400"};'
                 f'color:{ds.TOKENS["text"] if present else ds.TOKENS["n500"]};'
                 f'font-style:{"normal" if present else "italic"};'
                 f'word-break:break-word')
        cells.append(f'<div><div style="font-size:11px;color:{ds.TOKENS["n600"]}">'
                     f'{ds.esc(label)}</div>'
                     f'<div style="{style}">{ds.esc(value)}</div></div>')
    return (f'<div style="display:grid;grid-template-columns:repeat({columns},'
            f'minmax(0,1fr));gap:var(--space-4) var(--space-8);'
            f'margin-top:var(--space-4)">{"".join(cells)}</div>')


def _score_tiles(tiles: list[tuple[str, str]]) -> str:
    cells = "".join(
        f'<div style="border-radius:var(--radius-md);padding:var(--space-3);'
        f'background:{ds.TOKENS["n100"]}">'
        f'<div style="font-size:10.5px;color:{ds.TOKENS["n600"]}">{ds.esc(label)}</div>'
        f'<div style="font-family:var(--font-heading);font-size:15px;font-weight:500;'
        f'margin-top:3px;letter-spacing:-0.01em">{value}</div></div>'
        for label, value in tiles)
    return (f'<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));'
            f'gap:var(--space-3);margin-top:var(--space-3)">{cells}</div>')


def red_flag_rows_html(row: pd.Series) -> str:
    """Une ligne par regle du registre reel, avec ses trois etats
    distingues visuellement : trait rouge (actif), trait vert (inactif),
    trait gris pointille (non evaluable)."""
    registry = red_flag_registry()
    if not registry:
        return ('<div class="pmmp-caption">Registre des red flags indisponible : '
                'le module <code>ai/market_red_flags.py</code> n\'a pas pu être '
                'chargé.</div>')
    blocks = []
    for flag in registry:
        state = ds.flag_state(row.get(flag["id"]))
        style = ds.FLAG_STYLE[state]
        bar = (f'width:3px;flex:0 0 3px;align-self:stretch;min-height:22px;'
               f'border-radius:2px;background:{style["bar"]};'
               + ("opacity:.55;" if style["dashed"] else ""))
        badge = ds.render_status_badge(style["label"], style["role"], dot=False)
        derived = (' <span class="card-meta" style="font-size:10.5px">dérivé — ne '
                   'compte pas dans le score</span>') if flag["derived"] else ""
        blocks.append(
            f'<div style="display:flex;align-items:stretch;gap:var(--space-3);'
            f'padding:var(--space-3) 0;border-bottom:1px solid {ds.TOKENS["divider"]}">'
            f'<span style="{bar}"></span><div style="min-width:0;flex:1">'
            f'<div style="display:flex;align-items:center;gap:var(--space-2);'
            f'flex-wrap:wrap"><span style="font-size:12.5px;font-weight:500">'
            f'{flag["id"]} — {ds.esc(flag["name"])}</span>{badge}'
            f'<span class="card-meta" style="font-size:11px">{flag["sev"]}</span>'
            f'{derived}</div>'
            f'<div style="font-size:11.5px;color:{ds.TOKENS["n600"]};margin-top:2px;'
            f'line-height:1.45">{ds.esc(flag["desc"])}</div></div></div>')
    return "".join(blocks)


def _dimension_row(label: str, desc: str, role: str, badge_label: str,
                   dashed: bool = False) -> str:
    """Une ligne état-de-qualité : barre d'accent + libellé/sous-texte +
    badge, tous alignés sur le MEME role de couleur (`ds.STATUS_ROLES`).

    `align-items:stretch` sur la ligne et `align-self:stretch` sur la barre
    (au lieu d'une hauteur fixe) : la barre couvre alors toute la hauteur du
    bloc de texte à deux lignes, qu'il fasse une ligne ou trois. `dashed`
    distingue "Sans objet" d'"Absent" — même role neutre, même couleur,
    seule la bordure de la barre change, comme demandé pour ne pas les
    confondre quand les deux apparaissent dans la même carte.
    """
    k = ds.STATUS_ROLES.get(role, ds.STATUS_ROLES["none"])
    bar = (f'width:3px;flex:0 0 3px;align-self:stretch;border-radius:2px;'
           f'background:{k["base"]};'
           + (f'outline:1px dashed {ds.TOKENS["n500"]};outline-offset:1px;'
              if dashed else ""))
    badge = ds.render_status_badge(badge_label, role, dot=False)
    return (f'<div style="display:flex;align-items:stretch;gap:var(--space-3);'
            f'padding:var(--space-3);border-radius:var(--radius-md);'
            f'background:{ds.TOKENS["n100"]}">'
            f'<span style="{bar}"></span>'
            f'<div style="flex:1;min-width:0;align-self:center">'
            f'<div style="font-size:12.5px;font-weight:500">{label}</div>'
            f'<div style="font-size:11.5px;color:{ds.TOKENS["n600"]};margin-top:2px">'
            f'{desc}</div></div>'
            f'<span style="align-self:center">{badge}</span></div>')


def dimension_rows_html(row: pd.Series) -> str:
    """Les cinq dimensions de `features/data_quality.py`, chacune avec son
    etat. Une dimension absente de la ligne n'est pas rendue par un etat
    par defaut : elle est signalee comme non calculee."""
    blocks = []
    for key, label in DIMENSION_LABEL.items():
        raw = row.get(f"dq_{key}")
        state = None if ds.is_missing(raw) else ds.STATE_DISPLAY.get(str(raw))
        if state is None:
            blocks.append(_dimension_row(
                label, "qualité non calculée pour ce marché", "none", "Non calculé"))
        else:
            blocks.append(_dimension_row(
                label, state["desc"], state["role"], state["label"], state["dashed"]))
    return ('<div style="display:flex;flex-direction:column;gap:var(--space-2);'
            f'margin-top:var(--space-4)">{"".join(blocks)}</div>')


def peer_block_html(row: pd.Series) -> str:
    rows = peer_rows(row)
    if rows is None:
        return ('<div class="pmmp-empty" style="margin-top:var(--space-3)">'
                'Comparaison non disponible : nombre insuffisant de marchés '
                'comparables disposant de cette information. Aucune référence '
                'n\'est inventée pour combler ce vide.</div>')
    lines = "".join(
        f'<div style="display:flex;align-items:baseline;justify-content:space-between;'
        f'gap:var(--space-6);padding:var(--space-1) 0">'
        f'<div style="font-size:12px;color:{ds.TOKENS["n600"]}">{ds.esc(label)}</div>'
        f'<div style="font-size:12.5px;font-weight:500;text-align:right;max-width:60%;'
        f'color:{ds.TOKENS["text"] if present else ds.TOKENS["n500"]};'
        f'font-style:{"normal" if present else "italic"}">{ds.esc(value)}</div></div>'
        for label, value, present in rows)
    return (f'<div style="border-radius:var(--radius-md);padding:var(--space-4);'
            f'background:{ds.TOKENS["n100"]};margin-top:var(--space-3)">{lines}</div>')


# --------------------------------------------------------------------------- #
# Le panneau
# --------------------------------------------------------------------------- #

def _render_body(row: pd.Series) -> None:
    scorable = bool(row.get("scorable") is True)

    # Pas de sur-titre « Fiche marché » ici : `st.dialog` en pose deja un en
    # tete de panneau, et le repeter faisait doublon a l'ecran.
    head = (f'<div style="display:flex;align-items:flex-start;gap:var(--space-3)">'
            f'{ds.market_icon(20)}<div style="min-width:0">'
            f'<h5 style="margin:0">{ds.esc(market_title(row))}</h5>'
            f'<div style="font-size:12.5px;color:{ds.TOKENS["n800"]};'
            f'margin-top:var(--space-2);line-height:1.5">'
            f'{ds.esc(ds.fmt_texte(row.get("objet")))}</div></div></div>')
    st.markdown(head, unsafe_allow_html=True)

    if not scorable:
        st.markdown(
            '<div class="pmmp-warn" style="margin-top:var(--space-4)">'
            '<strong>Données insuffisantes pour analyser ce marché.</strong> '
            "Moins de deux informations sur trois (montant, concurrents, "
            "exclusions) ont pu être extraites. Ce marché n'est pas scoré : "
            "l'absence de score est une information, pas un score faible.</div>",
            unsafe_allow_html=True)

    st.markdown('<h6 style="margin:var(--space-6) 0 0;color:var(--color-neutral-600)">'
                'Identification</h6>', unsafe_allow_html=True)
    st.markdown(_fields_grid(identification_fields(row)), unsafe_allow_html=True)

    st.markdown('<h6 style="margin:var(--space-8) 0 0;color:var(--color-neutral-600)">'
                'Scores</h6>', unsafe_allow_html=True)
    tiles = [
        ("Score d'anomalie",
         ds.fmt_score(row.get("anomaly_score_0_100"), 1, "—") if scorable else "—"),
        ("Priorité d'analyse", ds.render_priority_badge(row.get("priority_level"))),
        ("Confiance", ds.confidence_display(row.get("confidence_level"))),
        ("Stabilité", ds.render_stability_dots(row.get("stability_frequency"))),
    ]
    st.markdown(_score_tiles(tiles), unsafe_allow_html=True)

    st.markdown('<h6 style="margin:var(--space-8) 0 0;color:var(--color-neutral-600)">'
                'Red flags</h6>', unsafe_allow_html=True)
    st.markdown(f'<div style="margin-top:var(--space-3)">{red_flag_rows_html(row)}</div>',
                unsafe_allow_html=True)

    st.markdown('<h6 style="margin:var(--space-8) 0 0;color:var(--color-neutral-600)">'
                'Données source et limites</h6>', unsafe_allow_html=True)
    ds.render_caption("État de chaque information dans le document analysé.")
    st.markdown(dimension_rows_html(row), unsafe_allow_html=True)

    st.markdown('<h6 style="margin:var(--space-8) 0 0;color:var(--color-neutral-600)">'
                'Comparaison aux marchés comparables</h6>', unsafe_allow_html=True)
    st.markdown(peer_block_html(row), unsafe_allow_html=True)

    st.markdown('<h6 style="margin:var(--space-8) 0 0;color:var(--color-neutral-600)">'
                "Avertissements d'extraction</h6>", unsafe_allow_html=True)
    warns = extraction_warnings(row)
    if warns:
        for w in warns:
            st.markdown(f'<div class="pmmp-warn" style="margin-top:var(--space-2)">'
                        f'{ds.esc(w)}</div>', unsafe_allow_html=True)
    else:
        ds.render_caption("Aucun avertissement d'extraction pour ce marché.")


def handle_selection(selected, markets: pd.DataFrame, key_prefix: str) -> None:
    """Ouvre le panneau quand la ligne selectionnee CHANGE.

    Le declencheur est un evenement, pas un etat persistant — c'est le
    motif documente par Streamlit pour `st.dialog`, et c'est ce qui permet
    a la fermeture (croix, echap, clic exterieur) de fonctionner : sans
    evenement nouveau, le panneau ne se rouvre pas tout seul au re-run
    suivant. Le revers est qu'un second clic sur la MEME ligne ne rouvre
    rien, faute de changement ; d'ou le bouton de reouverture explicite.
    """
    state_key = f"_panel_opened_{key_prefix}"
    if selected is None:
        st.session_state.pop(state_key, None)
        return

    selected = int(selected)
    if st.session_state.get(state_key) != selected:
        st.session_state[state_key] = selected
        open_detail_panel(selected, markets)
        return

    row = market_row(markets, selected)
    label = market_title(row) if row is not None else str(selected)
    if st.button(f"Rouvrir la fiche · {label}", key=f"reopen_{key_prefix}"):
        open_detail_panel(selected, markets)


@st.dialog("Fiche marché", width="large")
def open_detail_panel(award_id, markets: pd.DataFrame) -> None:
    """Ouvre le panneau. Le pied de panneau reprend les deux actions de la
    maquette : ouvrir le marche dans XAI, ou fermer."""
    row = market_row(markets, award_id)
    if row is None:
        ds.render_empty_state(
            "Marché introuvable",
            "Cet identifiant n'existe pas dans la table de scores chargée.")
        return

    _render_body(row)

    st.markdown('<div style="height:var(--space-6)"></div>', unsafe_allow_html=True)
    scorable = bool(row.get("scorable") is True)
    left, right = st.columns(2)
    # Le bouton XAI n'est propose que pour un marche SCORABLE : la page
    # d'explicabilite n'a ni jauge, ni SHAP, ni ablation pour un marche non
    # score, et y renvoyer afficherait un autre marche que celui demande.
    if left.button("Ouvrir dans XAI", key=f"panel_xai_{award_id}",
                   type="primary", use_container_width=True,
                   disabled=not scorable,
                   help=None if scorable else
                   "Ce marché n'est pas scoré : il n'a aucune explication à "
                   "afficher dans la page XAI."):
        st.session_state["xai_award_id"] = int(award_id)
        st.session_state["xai_select"] = int(award_id)
        st.session_state["nav_page"] = "XAI · Explicabilité"
        st.rerun()
    if right.button("Fermer", key=f"panel_close_{award_id}",
                    use_container_width=True):
        st.rerun()
