"""
Page « XAI · Explicabilite » — pourquoi ce marche, et avec quelles reserves.

C'est la page qui justifie le produit : elle repond a "pourquoi celui-la"
plutot qu'a "lequel". Elle enchaine, dans l'ordre de la maquette :
selecteur, plafond de confiance eventuel, fiche du marche, jauge, SHAP,
controle par ablation, red flags, comparaison aux pairs, qualite des
donnees, explication en langage simple, avis de l'analyste.

CE QUE SHAP EXPLIQUE, ET CE QU'IL N'EXPLIQUE PAS
--------------------------------------------------
Sur un Isolation Forest, SHAP attribue une part d'une PROFONDEUR
D'ISOLEMENT, pas une probabilite — et il explique le modele, pas le monde.
Une feature mal extraite produit une explication parfaitement coherente
d'un score parfaitement faux. Les deux avertissements sont affiches sous
le graphique, pas relegues dans la documentation.

LES DELTAS D'ABLATION NE SONT PAS AFFICHES, ET C'EST VOULU
------------------------------------------------------------
`ai/market_explain.py` ne persiste que le CLASSEMENT des facteurs obtenus
par ablation (`ablation_top_features`), pas les ecarts numeriques. La
maquette montrait des deltas chiffres : les fabriquer aurait ete inventer
une donnee. Seul le rang est affiche, et l'absence est dite.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard import charts  # noqa: E402
from dashboard import data_access as da  # noqa: E402
from dashboard import design_system as ds  # noqa: E402
from dashboard import detail_panel as dp  # noqa: E402

# Correspondance colonne imputable -> drapeau d'imputation, telle que
# `ai/train_market_model.py::IMPUTED_COLUMNS` la definit. Sert a marquer
# une contribution SHAP assise sur une mediane substituee.
IMPUTED_FLAG = {
    "log_montant_ttc": "log_montant_ttc_imputed",
    "nb_soumissionnaires": "nb_soumissionnaires_imputed",
    "nb_concurrents_ecartes": "nb_concurrents_ecartes_imputed",
    "exclusion_rate": "exclusion_rate_imputed",
}


def _feature_labels() -> dict:
    """Libelles lisibles, lus dans `ai/market_explain.py` — jamais
    redefinis ici, sinon les deux finiraient par diverger."""
    try:
        from ai.market_explain import FEATURE_LABELS
        return dict(FEATURE_LABELS)
    except Exception:  # noqa: BLE001
        return {}


def _parse_json_list(value) -> list:
    if ds.is_missing(value):
        return []
    try:
        out = json.loads(value)
        return out if isinstance(out, list) else []
    except (ValueError, TypeError):
        return []


def _split_first_sentence(text: str) -> tuple[str, str]:
    """(phrase factuelle visible, reste en nuance) — coupe a la premiere
    fin de phrase, ne reformule ni n'invente rien. Le registre red flags
    ecrit systematiquement le declencheur factuel en premiere phrase et la
    nuance/l'exemple en seconde : c'est ce decoupage qu'on rend visible."""
    for sep in (". ", " : "):
        if sep in text:
            first, rest = text.split(sep, 1)
            return first.strip() + ".", rest.strip()
    return text, ""


def _option_label(row: pd.Series) -> str:
    prio = ds.priority_display(row.get("priority_level"))
    ach = ds.fmt_texte(row.get("acheteur_public"), "acheteur non renseigné")
    return f"{dp.market_title(row)} — {ach[:46]} — {prio}"


# --------------------------------------------------------------------------- #
# Blocs
# --------------------------------------------------------------------------- #

def _selector(markets: pd.DataFrame) -> pd.Series | None:
    """Selecteur + navigation precedent / suivant.

    Ne propose que les marches SCORABLES : un marche non score n'a ni
    jauge, ni SHAP, ni ablation. Le dire dans la legende vaut mieux que
    d'ouvrir une page vide.
    """
    scorables = markets[markets["scorable"] == True].copy()  # noqa: E712
    if scorables.empty:
        return None
    order = {p: i for i, p in enumerate(ds.PRIORITY_ORDER)}
    scorables["_rank"] = scorables["priority_level"].map(order).fillna(len(order))
    scorables = scorables.sort_values(
        ["_rank", "anomaly_score_0_100"], ascending=[True, False])

    ids = scorables["award_id"].astype(int).tolist()
    labels = {int(r["award_id"]): _option_label(r) for _, r in scorables.iterrows()}

    # `xai_select` est la cle du widget ; `xai_award_id` porte la selection
    # partagee entre les pages (le panneau de detail l'ecrit avant de
    # basculer ici). Streamlit interdit d'ecrire la cle d'un widget APRES son
    # instanciation : les boutons Precedent / Suivant deposent donc leur
    # cible dans `_xai_pending`, consommee ici avant que le selecteur
    # n'existe. Sans ce detour, la valeur memorisee du widget l'emportait et
    # la navigation ne bougeait pas.
    pending = st.session_state.pop("_xai_pending", None)
    requested = pending if pending in ids else st.session_state.get("xai_award_id")
    current = st.session_state.get("xai_select")
    if requested in ids and requested != current:
        st.session_state["xai_select"] = int(requested)
    elif current not in ids:
        st.session_state["xai_select"] = ids[0]

    with ds.card():
        col_sel, col_prev, col_next = st.columns([4, 1, 1])
        with col_sel:
            chosen = int(st.selectbox(
                "Marché analysé · recherche par référence, acheteur ou objet",
                ids, format_func=lambda i: labels[i], key="xai_select"))
        st.session_state["xai_award_id"] = chosen
        with col_prev:
            st.markdown('<div style="height:26px"></div>', unsafe_allow_html=True)
            if st.button("Précédent", key="xai_prev", use_container_width=True):
                st.session_state["_xai_pending"] = ids[(ids.index(chosen) - 1) % len(ids)]
                st.rerun()
        with col_next:
            st.markdown('<div style="height:26px"></div>', unsafe_allow_html=True)
            if st.button("Suivant", key="xai_next", use_container_width=True):
                st.session_state["_xai_pending"] = ids[(ids.index(chosen) + 1) % len(ids)]
                st.rerun()
        st.markdown(
            f'<div class="card-meta" style="font-size:11.5px;margin-top:var(--space-3)">'
            f'{len(ids)} marché(s) scorable(s) proposé(s) · les marchés non scorés '
            f'n\'ont ni jauge ni explication et sont exclus de ce sélecteur · '
            f'sélection conservée entre les pages</div>', unsafe_allow_html=True)

    row = markets[markets["award_id"] == chosen]
    return None if row.empty else row.iloc[0]


def _summary(row: pd.Series) -> None:
    left, right = st.columns([1.1, 1])

    with left, ds.card():
        st.markdown(
            f'<div style="display:flex;align-items:flex-start;'
            f'justify-content:space-between;gap:var(--space-6)">'
            f'<div style="min-width:0;display:flex;gap:var(--space-3);'
            f'align-items:flex-start">{ds.market_icon(20)}<div style="min-width:0">'
            f'<h6 style="margin:0;color:{ds.TOKENS["n600"]}">Marché sélectionné</h6>'
            f'<h5 style="margin:var(--space-2) 0 0">{ds.esc(dp.market_title(row))}</h5>'
            f'<div style="font-size:12.5px;color:{ds.TOKENS["n800"]};'
            f'margin-top:var(--space-2);line-height:1.5">'
            f'{ds.esc(ds.fmt_texte(row.get("objet")))}</div>'
            f'<div class="card-meta" style="font-size:12px;margin-top:var(--space-2)">'
            f'{ds.esc(ds.fmt_texte(row.get("acheteur_public")))}</div></div></div>'
            f'{ds.render_priority_badge(row.get("priority_level"), big=True)}</div>',
            unsafe_allow_html=True)

        tiles = [
            ("Score d'anomalie", ds.fmt_score(row.get("anomaly_score_0_100"), 1, "—"),
             "sur 100"),
            ("Score red flags", ds.fmt_score(row.get("red_flag_score"), 0, "—"),
             "règles métier"),
            ("Score de priorité", ds.fmt_score(row.get("priority_score"), 0, "—"),
             "ordre de lecture"),
            ("Confiance", ds.confidence_display(row.get("confidence_level")),
             "niveau"),
        ]
        cells = "".join(
            f'<div style="border-radius:var(--radius-md);padding:var(--space-3);'
            f'background:{ds.TOKENS["n100"]}">'
            f'<div style="font-size:10.5px;color:{ds.TOKENS["n600"]}">{label}</div>'
            f'<div style="font-family:var(--font-heading);font-size:17px;'
            f'font-weight:500;margin-top:3px;letter-spacing:-0.02em">{value}</div>'
            f'<div class="card-meta" style="font-size:10.5px">{sub}</div></div>'
            for label, value, sub in tiles)
        st.markdown(
            f'<div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));'
            f'gap:var(--space-3);margin-top:var(--space-6)">{cells}</div>',
            unsafe_allow_html=True)
        st.markdown(
            f'<div style="margin-top:var(--space-4);display:flex;align-items:center;'
            f'gap:var(--space-3);flex-wrap:wrap">'
            f'<span style="font-size:11.5px;color:{ds.TOKENS["n600"]}">Stabilité</span>'
            f'{ds.render_stability_dots(row.get("stability_frequency"))}</div>',
            unsafe_allow_html=True)

    bands_tip = ("Bornes mesurées sur la distribution réelle, jamais 25/50/75 "
                ": la frontière « Faible » est celle que le modèle choisit "
                "lui-même (le score maximal parmi les marchés non signalés) ; "
                "Modéré et Élevé sont les terciles mesurés du sous-groupe "
                "signalé.")
    with right, ds.card("Score d'anomalie sur l'échelle du corpus", help=bands_tip):
        bands = da.measured_risk_bands()
        score = row.get("anomaly_score_0_100")
        if ds.is_missing(score):
            ds.render_empty_state("Ce marché n'est pas scoré par le modèle.")
        else:
            st.plotly_chart(charts.gauge_anomaly(float(score), bands),
                            use_container_width=True, config=charts.PLOTLY_CONFIG,
                            key="chart_gauge")
            level = row.get("risk_level")
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:var(--space-3);'
                f'flex-wrap:wrap"><span style="font-size:11.5px;'
                f'color:{ds.TOKENS["n600"]}">Zone atteinte</span>'
                f'{ds.render_status_badge(ds.risk_display(level), ds.RISK_LEVEL_ROLE.get(level, "none"), big=True)}'
                f'</div>', unsafe_allow_html=True)
            if bands:
                # Chaque borne est formatee individuellement : un
                # `.replace(".", ",")` applique a la phrase entiere
                # transformait aussi sa ponctuation en virgules.
                faible = ds.fmt_score(bands["faible_max"])
                modere = ds.fmt_score(bands["modere_max"])
                eleve = ds.fmt_score(bands["eleve_max"])
                # Legende structuree plutot qu'une phrase continue : chaque
                # zone porte son carre de couleur, la meme que sur l'arc de
                # la jauge — le nombre de marches et la nuance methodologique
                # ("frontiere que le modele choisit") vont dans le tooltip du
                # titre de la carte, pas dans ce texte visible.
                legend = "".join(
                    f'<span style="display:inline-flex;align-items:center;'
                    f'gap:6px;font-size:11px;color:{ds.TOKENS["n700"]}">'
                    f'<span style="width:8px;height:8px;border-radius:2px;'
                    f'background:{ds.RISK[role]["base"]};flex:0 0 8px"></span>'
                    f'{name} {bound}</span>'
                    for name, bound, role in (
                        ("Faible", f"≤ {faible}", "low"),
                        ("Modéré", f"≤ {modere}", "mid"),
                        ("Élevé", f"≤ {eleve}", "high"),
                        ("Critique", f"> {eleve}", "crit")))
                st.markdown(
                    f'<div style="display:flex;flex-wrap:wrap;'
                    f'gap:var(--space-4);margin-top:var(--space-4)">{legend}</div>',
                    unsafe_allow_html=True)
                st.markdown(
                    f'<div class="card-meta" style="font-size:10.5px;'
                    f'margin-top:var(--space-2)">Bornes mesurées sur '
                    f'{bands["n_scored"]} marchés scorés.</div>',
                    unsafe_allow_html=True)
            st.markdown(
                f'<div style="margin-top:var(--space-4);padding-top:var(--space-3);'
                f'border-top:1px solid {ds.TOKENS["divider"]}">'
                f'<div class="pmmp-caption">Le score exprime un écart '
                f'statistique au corpus. Il ne s\'agit pas d\'une probabilité '
                f'd\'irrégularité, et les bornes 0 et 100 sont relatives à ce '
                f'corpus.</div></div>', unsafe_allow_html=True)


def _explainability(row: pd.Series) -> None:
    labels = _feature_labels()
    left, right = st.columns(2)

    with left, ds.card("Facteurs principaux selon SHAP"):
        feats = _parse_json_list(row.get("shap_top_features"))
        vals = _parse_json_list(row.get("shap_top_values"))
        if not feats or not vals:
            ds.render_empty_state(
                "Aucune explication disponible",
                "Ce marché n'est pas expliqué par le modèle, ou "
                "market_explanations.parquet est absent — relancer "
                "`python -m ai.market_explain`.")
        else:
            imputed = [bool(row.get(IMPUTED_FLAG.get(f), 0) or 0) for f in feats]
            fig = charts.bars_shap([labels.get(f, f) for f in feats],
                                   [float(v) for v in vals], imputed)
            st.plotly_chart(fig, use_container_width=True,
                            config=charts.PLOTLY_CONFIG, key="chart_shap")
            if any(imputed):
                ds.render_warning(
                    "Au moins un facteur repose sur une valeur imputée, "
                    "c'est-à-dire remplacée par la médiane du corpus faute d'avoir "
                    "été lue dans le document (marquée ⚠ sur le graphique). Ce "
                    "n'est pas une observation.")
            shap_tip = (
                "Il indique en quoi ce marché se distingue des autres du corpus, "
                "jamais qu'il serait irrégulier. Sur un Isolation Forest, la "
                "grandeur expliquée est une profondeur d'isolement, pas une "
                "probabilité.")
            st.markdown(
                f'<div class="pmmp-caption">SHAP explique la sortie du '
                f'<strong>modèle</strong>, pas la réalité du marché. '
                f'{ds.info_icon(shap_tip)}</div>', unsafe_allow_html=True)

    with right, ds.card("Contrôle par ablation"):
        ds.render_caption(
            "Méthode indépendante : chaque variable est neutralisée à la médiane "
            "de population et la réponse du modèle est remesurée.")
        abl = _parse_json_list(row.get("ablation_top_features"))
        if not abl:
            ds.render_empty_state("Contrôle par ablation non disponible.")
        else:
            rows_html = "".join(
                f'<div style="display:flex;align-items:center;gap:var(--space-3);'
                f'padding:var(--space-3);border-radius:var(--radius-md);'
                f'background:{ds.TOKENS["n100"]};margin-top:var(--space-2)">'
                f'<span style="width:20px;height:20px;flex:0 0 20px;'
                f'border-radius:var(--radius-sm);background:{ds.TOKENS["a100"]};'
                f'color:{ds.TOKENS["a800"]};font-size:11px;font-weight:500;'
                f'display:inline-flex;align-items:center;justify-content:center">'
                f'{i + 1}</span>'
                f'<div style="flex:1;min-width:0;font-size:12.5px;'
                f'color:{ds.TOKENS["n800"]}">{ds.esc(labels.get(f, f))}</div></div>'
                for i, f in enumerate(abl))
            st.markdown(f'<div style="margin-top:var(--space-4)">{rows_html}</div>',
                        unsafe_allow_html=True)
            abl_tip = ("ai/market_explain.py ne persiste que l'ordre des facteurs "
                      "(ablation_top_features), pas les écarts numériques : les "
                      "chiffrer ici reviendrait à les inventer.")
            st.markdown(
                f'<div class="pmmp-caption">Seul le classement est affiché, '
                f'jamais d\'écart chiffré. {ds.info_icon(abl_tip)}</div>',
                unsafe_allow_html=True)

            accord = row.get("accord_shap_ablation")
            if not ds.is_missing(accord):
                low = float(accord) < 1.0
                style = ds.RISK["mid"] if low else ds.RISK["low"]
                note = ("Les deux méthodes divergent partiellement. SHAP lit la "
                        "structure des arbres, l'ablation ne mesure que la réponse "
                        "du modèle : lire le document avant de commenter ce marché."
                        if low else
                        "Les deux méthodes désignent les mêmes facteurs principaux.")
                st.markdown(
                    f'<div style="margin-top:var(--space-4);padding:var(--space-4);'
                    f'border-radius:var(--radius-md);background:{style["bg"]};'
                    f'box-shadow:0 0 0 1px {style["line"]};color:{style["text"]}">'
                    f'<div style="display:flex;align-items:center;'
                    f'justify-content:space-between;gap:var(--space-4)">'
                    f'<div style="font-size:12.5px;font-weight:500">Accord SHAP / '
                    f'ablation sur le Top 3</div>'
                    f'<div style="font-size:13px;font-weight:500">'
                    f'{float(accord) * 100:.0f} %</div></div>'
                    f'<div style="font-size:11.5px;line-height:1.55;'
                    f'margin-top:var(--space-2)">{note}</div></div>',
                    unsafe_allow_html=True)


def _red_flags(row: pd.Series) -> None:
    severity_help = (
        "Les sévérités traduisent une priorité de lecture issue de la "
        "littérature, pas un effet mesuré : sans vérité terrain, aucun effet "
        "ne peut être estimé sur ce corpus. RF04 (écart estimation / "
        "attribution) n'existe pas : l'estimation administrative est absente "
        "de la totalité des marchés attribués du corpus.")
    with ds.card(
            "Red flags métier",
            "RF06 est dérivé : il ne compte pas dans le score.",
            help=severity_help):
        registry = dp.red_flag_registry()
        if not registry:
            ds.render_empty_state("Registre des red flags indisponible.")
        else:
            cards = []
            for flag in registry:
                state = ds.flag_state(row.get(flag["id"]))
                style = ds.FLAG_STYLE[state]
                # `outline`, pas `border` : l'outline ne participe pas au
                # box model (aucun risque de decaler le calcul des pistes de
                # la grille) et reste toujours contenu dans son propre
                # element. Un `border` en pointilles a 1px, sur un ecran a
                # mise a l'echelle non entiere (125 %, 112,5 %...), se
                # traduit par une largeur fractionnaire (ex. 0,89px) que
                # Chrome antialiase de façon incoherente d'un bord a
                # l'autre — c'est ce qui donnait l'impression d'un trait
                # qui deborde sur les cartes voisines.
                border = (f"outline:1.5px dashed {ds.TOKENS['n400']};"
                          f"outline-offset:-1.5px;" if style["dashed"] else "")
                trigger, nuance = _split_first_sentence(flag["desc"])
                badge = ds.render_status_badge(
                    f'{style["label"]} · {flag["sev"]}', style["role"], dot=False)
                cards.append(
                    f'<div style="border-radius:var(--radius-md);padding:var(--space-4);'
                    f'background:{ds.TOKENS["n100"]};box-sizing:border-box;'
                    f'overflow:hidden;{border}">'
                    f'<div style="display:flex;align-items:center;gap:var(--space-2);'
                    f'flex-wrap:wrap">'
                    f'<span style="width:3px;height:14px;border-radius:2px;'
                    f'background:{style["bar"]}"></span>'
                    f'<span style="font-size:12.5px;font-weight:500">{flag["id"]} · '
                    f'{ds.esc(flag["name"])}</span></div>'
                    f'<div style="margin-top:var(--space-2)">{badge}</div>'
                    f'<div style="font-size:12.5px;color:{ds.TOKENS["n700"]};'
                    f'margin-top:var(--space-3);line-height:1.5">'
                    f'{ds.esc(trigger)} {ds.info_icon(nuance)}</div></div>')
            st.markdown(
                f'<div style="display:grid;grid-template-columns:'
                f'repeat(2,minmax(0,1fr));gap:var(--space-4);'
                f'margin-top:var(--space-6)">{"".join(cards)}</div>',
                unsafe_allow_html=True)
            ref = row.get("rf03_reference")
            if not ds.is_missing(ref):
                ref_tip = ("« pairs » = comparaison à des marchés comparables ; "
                          "« corpus » = repli sur le quantile de tout le corpus, "
                          "moins pertinent.")
                ds.render_caption(
                    f"Référence employée par RF03 pour ce marché : "
                    f"<strong>{ref}</strong>. {ds.info_icon(ref_tip)}")


def _peer_and_quality(row: pd.Series) -> None:
    with ds.card("Comparaison aux marchés comparables"):
        st.markdown(dp.peer_block_html(row), unsafe_allow_html=True)


def _explanation(row: pd.Series) -> None:
    modele = row.get("explication_modele")
    metier = row.get("explication")
    if ds.is_missing(modele) and ds.is_missing(metier):
        return
    blocks = ""
    if not ds.is_missing(modele):
        blocks += (f'<p style="font-size:14px;color:{ds.TOKENS["a800"]};'
                   f'line-height:1.65;margin:var(--space-2) 0 0;max-width:940px">'
                   f'{ds.esc(modele)}</p>')
    if not ds.is_missing(metier):
        blocks += (f'<p style="font-size:13px;color:{ds.TOKENS["a800"]};'
                   f'line-height:1.6;margin:var(--space-4) 0 0;max-width:940px">'
                   f'{ds.esc(metier)}</p>')
    st.markdown(
        f'<div style="padding:var(--space-6) var(--space-8);'
        f'background:{ds.TOKENS["a100"]};box-shadow:0 0 0 1px {ds.TOKENS["a300"]};'
        f'border-radius:var(--radius-md)">'
        f'<h6 style="margin:0;color:{ds.TOKENS["a700"]}">Explication en langage '
        f'simple</h6>{blocks}'
        f'<p style="font-size:12.5px;color:{ds.TOKENS["a700"]};line-height:1.55;'
        f'margin:var(--space-4) 0 0;font-weight:500">Ces facteurs expliquent la '
        f'sortie du modèle, pas une irrégularité.</p></div>',
        unsafe_allow_html=True)


def _analyst_review(row: pd.Series) -> None:
    """Avis de l'analyste — ecrit par `dashboard/feedback.py`.

    Aucune boucle de retour vers le modele : la dependance ne va que dans
    un sens (dashboard -> fichier versionne). C'est une contrainte de
    conception, pas une etape non encore faite.
    """
    try:
        from dashboard.feedback import (FALSE_POSITIVE, RELEVANT, STATUS_LABELS,
                                        TO_REVIEW, load_reviews, upsert_review)
    except Exception as exc:  # noqa: BLE001
        ds.render_empty_state("Module d'avis indisponible", str(exc))
        return

    award_id = int(row["award_id"])
    with ds.card("Avis de l'analyste"):
        ds.render_caption(
            "Cet avis est enregistré pour la traçabilité de l'examen dans "
            "<code>data/reference/analyst_reviews.csv</code>, versionné. "
            "<strong>Il ne modifie ni le modèle, ni les seuils, ni les red "
            "flags.</strong>")

        existing = load_reviews().get(award_id)
        if existing:
            detail = (f" — « {existing.analyst_comment} »"
                      if existing.analyst_comment else "")
            label = STATUS_LABELS.get(existing.review_status,
                                      existing.review_status)
            st.markdown(
                f'<div class="pmmp-note" style="margin-top:var(--space-3)">'
                f'Avis enregistré : <strong>{ds.esc(label)}</strong> · '
                f'{ds.esc(existing.review_timestamp)}{ds.esc(detail)}</div>',
                unsafe_allow_html=True)

        comment = st.text_area(
            "Commentaire d'examen (optionnel)",
            value=existing.analyst_comment if existing else "",
            key=f"xai_comment_{award_id}",
            placeholder="Ce que le PV source dit réellement, ce qui manque…")

        c1, c2, c3 = st.columns(3)
        choice = None
        if c1.button("Pertinent", key=f"xai_ok_{award_id}",
                     use_container_width=True):
            choice = RELEVANT
        if c2.button("Faux positif", key=f"xai_fp_{award_id}",
                     use_container_width=True):
            choice = FALSE_POSITIVE
        if c3.button("À examiner", key=f"xai_tr_{award_id}",
                     use_container_width=True):
            choice = TO_REVIEW
        if choice:
            upsert_review(award_id, choice, analyst_comment=comment)
            st.success(f"Avis enregistré : {STATUS_LABELS[choice]}. "
                       "Il n'entraîne aucune modification du modèle.")


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

def render() -> None:
    ds.render_section_header(
        "XAI · Explicabilité",
        "Comprendre les facteurs qui contribuent au score du modèle.")
    # Page de score : l'avertissement y est obligatoire, au meme titre que
    # sur la page des anomalies.
    ds.render_disclaimer(compact=True)

    markets = da.load_markets()
    if markets.empty:
        ds.render_empty_state(
            "Aucun résultat de modèle",
            "market_anomaly_scores.parquet est absent. Relancer "
            "`python -m ai.train_market_model`.")
        return

    row = _selector(markets)
    if row is None:
        ds.render_empty_state(
            "Aucun marché scorable",
            "Le modèle n'a scoré aucun marché : moins de deux informations sur "
            "trois ont pu être extraites partout.")
        return

    if int(row["award_id"]) in da.capped_awards():
        st.markdown('<div style="height:var(--space-4)"></div>',
                    unsafe_allow_html=True)
        ds.render_warning(
            "Le niveau de priorité est plafonné par la confiance : trop peu "
            "d'informations ont été lues dans le document pour que le score soit "
            "exploitable. Le marché reste visible avec son score, mais il ne peut "
            "pas être hiérarchisé.",
            "Score élevé, mais données faibles — marché non classé prioritaire")

    st.markdown('<div style="height:var(--space-6)"></div>', unsafe_allow_html=True)
    _summary(row)
    st.markdown('<div style="height:var(--space-6)"></div>', unsafe_allow_html=True)
    _explainability(row)
    st.markdown('<div style="height:var(--space-6)"></div>', unsafe_allow_html=True)
    _red_flags(row)
    st.markdown('<div style="height:var(--space-6)"></div>', unsafe_allow_html=True)
    _peer_and_quality(row)
    st.markdown('<div style="height:var(--space-6)"></div>', unsafe_allow_html=True)
    _explanation(row)
    st.markdown('<div style="height:var(--space-6)"></div>', unsafe_allow_html=True)
    _analyst_review(row)
