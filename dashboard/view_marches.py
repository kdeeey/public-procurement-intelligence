"""
Page « Marches publics » — catalogue explorable du corpus entier.

Le meme composant sert l'onglet « Vue tableau des marches » de la Vue
generale : meme tableau, memes filtres, meme fiche de detail. Un
`key_prefix` distinct suffit a isoler les deux etats de widget.

CE QUE MONTRE CETTE PAGE, ET POURQUOI
--------------------------------------
Le corpus ENTIER, marches infructueux compris. Ceux-ci n'ont ni score ni
priorite — leurs cellules affichent « Non applicable », jamais 0 ni une
priorite basse. Les masquer aurait fait disparaitre un tiers du corpus
d'un catalogue qui se presente comme complet.
"""

from __future__ import annotations

import streamlit as st

from dashboard import data_access as da
from dashboard import design_system as ds
from dashboard import detail_panel
from dashboard import market_table


def render_catalogue(key_prefix: str = "marches", show_header: bool = True) -> None:
    if show_header:
        ds.render_section_header(
            "Marchés publics",
            "Rechercher, filtrer et consulter les marchés du corpus.")

    # Le catalogue affiche des priorites et des red flags : l'avertissement
    # accompagne donc ce tableau, comme toute surface qui montre un score.
    ds.render_disclaimer(compact=True)

    table = da.table_frame()
    if table.empty:
        ds.render_empty_state(
            "Corpus analytique introuvable",
            "market_features.parquet est absent. Relancer "
            "`python -m bigdata.spark.jobs.build_market_features`.")
        return

    filters = market_table.render_filters(key_prefix)
    filtered = market_table.sort_by_priority(
        market_table.apply_filters(table, filters))

    st.markdown(
        f'<div style="display:flex;align-items:center;justify-content:space-between;'
        f'gap:var(--space-4);flex-wrap:wrap;margin:var(--space-4) 0 var(--space-2)">'
        f'<div style="font-size:12.5px;color:{ds.TOKENS["n600"]}">'
        f'{len(filtered)} marché(s) affiché(s) sur {len(table)}</div>'
        f'<div class="card-meta" style="font-size:11.5px">Tri par priorité '
        f'décroissante · objet tronqué · cliquer une ligne ouvre sa fiche</div></div>',
        unsafe_allow_html=True)

    selected = market_table.render_table(
        filtered, key=f"table_{key_prefix}", variant="catalogue", height=470)
    detail_panel.handle_selection(selected, table, key_prefix)


def render() -> None:
    render_catalogue(key_prefix="marches", show_header=True)
