"""
Page « Vue generale » — trois onglets, comme la maquette.

  Vue generale            KPI du corpus + volumes par annee et par secteur
  Vue tableau des marches le tableau partage, avec ses filtres et sa fiche
  Vue analytique          KPI etendus + procedures + qualite des donnees

Tous les compteurs viennent de `data_access.corpus_kpis()`, recalcules a
chaque execution. La maquette portait des valeurs de gabarit (454 / 279 /
28 / 35 / 69) : celles affichees ici sont celles des parquet charges, et
elles different deja sur la qualite moyenne.
"""

from __future__ import annotations

import streamlit as st

from dashboard import charts
from dashboard import data_access as da
from dashboard import design_system as ds
from dashboard import view_marches


def _period_tags(kpis: dict) -> str:
    annees = kpis.get("annees")
    tags = []
    if annees:
        tags.append(
            f'<span class="tag" style="background:{ds.TOKENS["surface"]};'
            f'box-shadow:var(--shadow-sm);color:{ds.TOKENS["n600"]};'
            f'white-space:nowrap">Période couverte : {annees[0]} – {annees[1]}</span>')
    years = da.counts_by_year()
    tronquee = years[years["tronquee"]] if not years.empty else years
    if not tronquee.empty:
        an = int(tronquee.iloc[0]["annee"])
        tags.append(
            f'<span class="tag" style="background:{ds.TOKENS["n200"]};'
            f'color:{ds.TOKENS["n600"]};border:1px dashed {ds.TOKENS["n400"]};'
            f'white-space:nowrap">{an} incomplète</span>')
    return "".join(tags)


def _kpis_general(kpis: dict) -> list[str]:
    total, att, inf = kpis["total"], kpis["attribues"], kpis["infructueux"]
    sub_total = (f"{att} attribués · {inf} infructueux"
                 if att is not None and inf is not None else "")
    qualite = kpis["qualite_moyenne"]
    sub_q = (f"sur 100 · niveau {ds.quality_display(kpis['qualite_niveau'])}"
             if kpis["qualite_niveau"] else "sur 100")
    return [
        ds.render_metric_card(
            "Total marchés", ds.fmt_int(total, ds.MISSING_GENERIC), sub_total,
            "Nombre de marchés / lots présents dans le corpus analytique."),
        ds.render_metric_card(
            "Marchés analysés", ds.fmt_int(kpis["scorables"], ds.MISSING_GENERIC),
            "scorables par le modèle",
            "Marchés contenant au moins deux des trois informations nécessaires : "
            "montant, concurrence et exclusions."),
        ds.render_metric_card(
            "Marchés atypiques", ds.fmt_int(kpis["atypiques"], ds.MISSING_GENERIC),
            "signalés pour analyse humaine",
            "Signalés par le modèle selon un paramètre de priorisation. C'est une "
            "charge d'analyse, pas un taux d'irrégularité."),
        ds.render_metric_card(
            "Données insuffisantes",
            ds.fmt_int(kpis["insuffisants"], ds.MISSING_GENERIC),
            "état distinct, hors échelle",
            "Marchés non scorés car les informations extraites sont insuffisantes. "
            "Ce n'est pas un niveau de risque faible.", muted=True),
        ds.render_metric_card(
            "Qualité moyenne", ds.fmt_score(qualite, 0, ds.MISSING_GENERIC), sub_q,
            "Qualité de l'information extraite du document, et non qualité ou "
            "régularité du marché."),
    ]


def _kpis_analytique(kpis: dict) -> list[str]:
    total, scorables = kpis["total"], kpis["scorables"]
    part = (f"{100 * scorables / total:.0f} % du corpus"
            if total and scorables is not None else "scorables par le modèle")
    att, inf = kpis["attribues"], kpis["infructueux"]
    return [
        ds.render_metric_card(
            "Marchés", ds.fmt_int(total, ds.MISSING_GENERIC),
            f"{att} attribués · {inf} infructueux" if att is not None else "",
            "Nombre de marchés / lots présents dans le corpus analytique.", size=26),
        ds.render_metric_card(
            "Acheteurs publics", ds.fmt_int(kpis["acheteurs"], ds.MISSING_GENERIC),
            "organismes distincts",
            "Acheteurs identifiés dans le corpus, toutes années confondues.", size=26),
        ds.render_metric_card(
            "Marchés analysés", ds.fmt_int(scorables, ds.MISSING_GENERIC), part,
            "Marchés contenant assez d'informations pour être scorés.", size=26),
        ds.render_metric_card(
            "Marchés atypiques", ds.fmt_int(kpis["atypiques"], ds.MISSING_GENERIC),
            "signalés pour analyse humaine",
            "Signalés selon un paramètre de priorisation, pas comme preuve "
            "d'irrégularité.", size=26),
        ds.render_metric_card(
            "Données insuffisantes",
            ds.fmt_int(kpis["insuffisants"], ds.MISSING_GENERIC),
            "état distinct, hors échelle",
            "Marchés non scorés faute d'informations suffisantes.",
            muted=True, size=26),
    ]


def _charts_row(kpis: dict, suffix: str) -> None:
    years, sectors = da.counts_by_year(), da.counts_by_sector()
    left, right = st.columns([1.35, 1])

    with left, ds.card("Marchés par année",
                       f"{ds.fmt_int(kpis['total'], '—')} marchés"):
        fig = charts.bar_years(years)
        if fig is None:
            ds.render_empty_state(
                "Volumes annuels indisponibles",
                "market_features.parquet est absent — relancer "
                "`python -m bigdata.spark.jobs.build_market_features`.")
        else:
            st.plotly_chart(fig, use_container_width=True,
                            config=charts.PLOTLY_CONFIG, key=f"chart_years_{suffix}")
            tronquee = years[years["tronquee"]]
            if not tronquee.empty:
                an = int(tronquee.iloc[0]["annee"])
                ds.render_caption(
                    f"La barre hachurée signale que {an} est une année en cours : "
                    f"son volume n'est pas comparable aux années complètes et elle "
                    f"est exclue de tout calcul d'évolution.")

    with right, ds.card("Répartition par secteur"):
        fig = charts.donut_sectors(sectors, kpis["total"])
        if fig is None:
            ds.render_empty_state("Répartition sectorielle indisponible")
        else:
            st.plotly_chart(fig, use_container_width=True,
                            config=charts.PLOTLY_CONFIG, key=f"chart_sectors_{suffix}")
            ds.render_caption(
                "La procédure n'est pas représentée en anneau : deux modalités "
                "couvrent la quasi-totalité du corpus, l'anneau serait un cercle "
                "plein. Elle est lue en barres dans l'onglet analytique.")


def _analytique_charts(kpis: dict) -> None:
    total = kpis["total"] or 0
    procs, quals = da.counts_by_procedure(), da.counts_by_quality_level()
    left, right = st.columns(2)

    with left, ds.card("Type de procédure", f"{ds.fmt_int(total, '—')} marchés"):
        fig = charts.bars_horizontal(procs.head(6), "procedure", "n", total,
                                     height=max(190, 34 * min(len(procs), 6)))
        if fig is None:
            ds.render_empty_state("Répartition par procédure indisponible")
        else:
            st.plotly_chart(fig, use_container_width=True,
                            config=charts.PLOTLY_CONFIG, key="chart_proc")
            if len(procs) > 6:
                ds.render_caption(
                    f"{len(procs) - 6} modalité(s) supplémentaire(s) non affichée(s), "
                    f"chacune sous le seuil de lisibilité du graphique.")
            if len(procs) >= 2 and total:
                part = 100 * (procs.iloc[0]["n"] + procs.iloc[1]["n"]) / total
                ds.render_caption(
                    f"Les deux modalités dominantes couvrent {part:.0f} % du corpus : "
                    f"la lecture en barres reste plus honnête qu'un anneau.")

    moyenne = kpis["qualite_moyenne"]
    meta = (f"score moyen {ds.fmt_score(moyenne, 0, '—')} / 100"
            if moyenne is not None else "score moyen indisponible")
    with right, ds.card("Qualité des données extraites", meta):
        ordered = quals.set_index("niveau").reindex(
            [q for q in ds.QUALITY_ORDER if q in set(quals["niveau"])]).reset_index()
        colors = [ds.QUALITY_BAR_COLOR.get(n, ds.RISK["none"]["base"])
                  for n in ordered["niveau"]] if not ordered.empty else None
        fig = charts.bars_horizontal(ordered, "niveau", "n", total, colors,
                                     height=max(190, 40 * max(len(ordered), 1)))
        if fig is None:
            ds.render_empty_state(
                "Qualité des données indisponible",
                "market_data_quality.parquet est absent — relancer "
                "`python -m features.data_quality`.")
        else:
            st.plotly_chart(fig, use_container_width=True,
                            config=charts.PLOTLY_CONFIG, key="chart_qual")
            ds.render_caption(
                "Qualité de l'information extraite du document, et non qualité ou "
                "régularité du marché.")


def render() -> None:
    kpis = da.corpus_kpis()
    ds.render_section_header(
        "Vue générale",
        "Synthèse du corpus de marchés publics et des résultats d'analyse.",
        _period_tags(kpis))

    if kpis["total"] is None:
        ds.render_empty_state(
            "Corpus analytique introuvable",
            "market_features.parquet est absent. Relancer "
            "`python -m bigdata.spark.jobs.build_market_features`, puis les "
            "étapes du module 4.")
        return

    tab_general, tab_tableau, tab_analytique = st.tabs(
        ["Vue générale", "Vue tableau des marchés", "Vue analytique"])

    with tab_general:
        ds.render_metric_row(_kpis_general(kpis))
        if kpis["atypiques"] is not None and kpis["scorables"]:
            st.markdown(
                f'<div class="pmmp-note" style="margin-top:var(--space-4)">'
                f'{kpis["atypiques"]} marchés sur {kpis["scorables"]} analysés '
                f'présentent des caractéristiques atypiques.</div>',
                unsafe_allow_html=True)
        st.markdown('<div style="height:var(--space-4)"></div>',
                    unsafe_allow_html=True)
        _charts_row(kpis, "general")
        st.markdown('<div style="height:var(--space-4)"></div>',
                    unsafe_allow_html=True)
        st.markdown(
            '<div class="pmmp-panel">'
            '<h6 style="margin:0;color:var(--color-neutral-600)">'
            'Avertissement méthodologique</h6>'
            f'<p style="font-size:13px;color:{ds.TOKENS["n800"]};line-height:1.6;'
            f'margin:var(--space-2) 0 0;max-width:900px">{ds.DISCLAIMER}</p></div>',
            unsafe_allow_html=True)

    with tab_tableau:
        view_marches.render_catalogue(key_prefix="apercu", show_header=False)

    with tab_analytique:
        ds.render_metric_row(_kpis_analytique(kpis))
        st.markdown('<div style="height:var(--space-4)"></div>',
                    unsafe_allow_html=True)
        _charts_row(kpis, "analytique")
        st.markdown('<div style="height:var(--space-4)"></div>',
                    unsafe_allow_html=True)
        _analytique_charts(kpis)
