"""
Page « Anomalies et priorites » — les marches a examiner en premier.

Structure de la maquette : avertissement, anneau des priorites a gauche,
nuage anomalie / red flags a droite, puis le tableau des marches a
examiner avec ses deux filtres rapides.

CE QUE CETTE PAGE NE DIT PAS
-----------------------------
Le nombre de marches signales depend du parametre de priorisation du
modele (`contamination`, etudie et fixe dans `ai/train_market_model.py`).
Il exprime une CHARGE D'EXAMEN, pas un taux d'irregularite — le pied du
tableau le rappelle a chaque affichage, pas seulement dans la
documentation.
"""

from __future__ import annotations

import streamlit as st

from dashboard import charts
from dashboard import data_access as da
from dashboard import design_system as ds
from dashboard import detail_panel
from dashboard import market_table

# Niveaux presentes comme "a examiner". "Faible" en est exclu, et
# "Donnees insuffisantes" aussi : ce dernier n'est pas un niveau bas, il
# occupe sa propre ligne de compte.
A_EXAMINER = ["Tres prioritaire", "Prioritaire", "A surveiller"]


def _kpi_cards(markets, prio_counts) -> list[str]:
    counts = dict(zip(prio_counts["niveau"], prio_counts["n"])) if not \
        prio_counts.empty else {}
    atypiques = int(markets["is_anomaly"].fillna(False).astype(bool).sum()) \
        if not markets.empty else None
    study = da.load_json_report("contamination_study.json")
    chosen = study.get("chosen")
    help_atypique = ("Nombre fixé par le paramètre de priorisation du modèle"
                     + (f" (contamination = {chosen})." if chosen else ".")
                     + " C'est une capacité d'examen, pas un taux d'irrégularité.")
    return [
        ds.render_metric_card(
            "Marchés signalés", ds.fmt_int(atypiques, ds.MISSING_GENERIC),
            "atypiques selon le modèle", help_atypique, size=26),
        ds.render_metric_card(
            "Très prioritaires",
            ds.fmt_int(counts.get("Tres prioritaire"), ds.MISSING_GENERIC),
            "à examiner en premier", ds.PRIORITY_HELP["Tres prioritaire"], size=26),
        ds.render_metric_card(
            "Prioritaires", ds.fmt_int(counts.get("Prioritaire"), ds.MISSING_GENERIC),
            "à examiner", ds.PRIORITY_HELP["Prioritaire"], size=26),
        ds.render_metric_card(
            "À surveiller", ds.fmt_int(counts.get("A surveiller"), ds.MISSING_GENERIC),
            "à revoir si le temps le permet", ds.PRIORITY_HELP["A surveiller"],
            size=26),
        ds.render_metric_card(
            "Données insuffisantes",
            ds.fmt_int(counts.get("Donnees insuffisantes"), ds.MISSING_GENERIC),
            "état distinct, hors échelle",
            ds.PRIORITY_HELP["Donnees insuffisantes"], muted=True, size=26),
    ]


def render() -> None:
    ds.render_section_header(
        "Anomalies et priorités",
        "Marchés à examiner en priorité selon les signaux statistiques et les "
        "règles métier.")
    ds.render_disclaimer(compact=True)

    markets = da.load_markets()
    if markets.empty:
        ds.render_empty_state(
            "Aucun résultat de modèle",
            "market_anomaly_scores.parquet est absent. Relancer "
            "`python -m ai.train_market_model`, puis `ai.market_red_flags` et "
            "`ai.priority_score`.")
        return

    prio_counts = da.counts_by_priority()
    st.markdown('<div style="height:var(--space-4)"></div>', unsafe_allow_html=True)
    ds.render_metric_row(_kpi_cards(markets, prio_counts))
    st.markdown('<div style="height:var(--space-4)"></div>', unsafe_allow_html=True)

    left, right = st.columns([1, 1.25])

    with left, ds.card("Répartition des priorités d'analyse"):
        result = charts.donut_priorities(prio_counts)
        if result is None:
            ds.render_empty_state(
                "Priorités non calculées",
                "market_priority.parquet est absent — relancer "
                "`python -m ai.priority_score`.")
        else:
            fig, total = result
            st.plotly_chart(fig, use_container_width=True,
                            config=charts.PLOTLY_CONFIG, key="chart_prio")
            legend = "".join(
                f'<div style="display:flex;align-items:center;gap:var(--space-3);'
                f'padding:2px 0">'
                f'{ds.render_status_badge(ds.priority_display(row["niveau"]), ds.PRIORITY_ROLE[row["niveau"]], square_dot=(ds.PRIORITY_ROLE[row["niveau"]] == "none"))}'
                f'<span class="card-meta" style="font-size:11.5px">{int(row["n"])} '
                f'marchés · {100 * int(row["n"]) / total:.0f} %</span></div>'
                for _, row in prio_counts.iterrows()
                if row["niveau"] in ds.PRIORITY_ORDER and row["niveau"] != "Faible")
            st.markdown(legend, unsafe_allow_html=True)
            ds.render_caption(
                "« Données insuffisantes » est représenté en gris, hors de "
                "l'échelle de gravité : c'est un état distinct, et non un niveau "
                "faible.")

    with right, ds.card("Score d'anomalie et score de red flags"):
        fig = charts.scatter_anomaly_flags(markets)
        if fig is None:
            ds.render_empty_state(
                "Nuage indisponible",
                "Les scores de red flags manquent — relancer "
                "`python -m ai.market_red_flags`.")
        else:
            st.plotly_chart(fig, use_container_width=True,
                            config=charts.PLOTLY_CONFIG, key="chart_scatter")
            ds.render_caption(
                "Un marché peut être atypique sans red flag explicite, ou "
                "présenter des red flags sans être fortement isolé par le modèle. "
                "La taille du point traduit le niveau de confiance ; les points "
                "évidés signalent une confiance faible ou insuffisante.")

    # --- tableau des marches a examiner ---------------------------------- #
    st.markdown('<div style="height:var(--space-6)"></div>', unsafe_allow_html=True)
    head_left, head_right = st.columns([2, 1])
    with head_left:
        st.markdown(
            '<h5 style="margin:0">Marchés à examiner</h5>'
            '<p class="text-muted" style="font-size:12px;margin:var(--space-1) 0 0">'
            'Niveaux Très prioritaire, Prioritaire et À surveiller · tri par score '
            'de priorité décroissant.</p>', unsafe_allow_html=True)
    with head_right:
        c1, c2 = st.columns(2)
        rf_only = c1.toggle("Red flag actif", key="ano_rf_only")
        stab8 = c2.toggle("Stabilité ≥ 8/10", key="ano_stab8")

    table = da.table_frame()
    subset = table[table["priority_level"].isin(A_EXAMINER)]
    if rf_only:
        subset = subset[subset["red_flag_count"].fillna(0) > 0]
    if stab8:
        subset = subset[subset["stability_frequency"].fillna(-1) >= 8]
    subset = market_table.sort_by_priority(subset)

    st.markdown(
        f'<div style="font-size:12.5px;color:{ds.TOKENS["n600"]};'
        f'margin:var(--space-3) 0 var(--space-2)">{len(subset)} marché(s) '
        f'affiché(s)</div>', unsafe_allow_html=True)

    selected = market_table.render_table(
        subset, key="table_anomalies", variant="anomalies", height=420)
    detail_panel.handle_selection(selected, table, "anomalies")

    ds.render_caption(
        "Le nombre de marchés signalés dépend du paramètre de priorisation du "
        "modèle. Il représente une capacité d'examen, pas un taux d'irrégularité.")
