"""
Graphiques Plotly du dashboard, aux couleurs du design system.

AUCUNE DONNEE DE DEMONSTRATION
-------------------------------
Chaque fonction recoit un DataFrame deja calcule par
`dashboard/data_access.py`. Aucune ne fabrique de valeur, aucune ne
complete une serie manquante : si la donnee est vide, la fonction renvoie
None et la vue affiche un etat vide explicite plutot qu'un graphique
trompeur.

CE QUI EST DELIBEREMENT ABSENT
-------------------------------
Pas d'anneau sur la procedure de passation : deux modalites couvrent la
quasi-totalite du corpus, l'anneau serait un cercle plein. Des barres
horizontales le disent honnetement — c'est la consigne de `dashboard.md`
Sec 5, verifiee a l'execution par `bar_procedures()` qui lit la
distribution reelle.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard import design_system as ds

FONT = dict(family="Inter, system-ui, sans-serif", size=12,
            color=ds.TOKENS["n800"])

PLOTLY_CONFIG = {"displayModeBar": False, "responsive": True}

SECTOR_COLORS = [ds.TOKENS["a800"], ds.TOKENS["accent"], ds.TOKENS["a400"],
                 ds.TOKENS["a300"], ds.TOKENS["n400"]]


def _layout(fig: go.Figure, height: int, margin=None) -> go.Figure:
    fig.update_layout(
        height=height, font=FONT,
        margin=margin or dict(l=8, r=8, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(bgcolor=ds.TOKENS["surface"], font_size=12,
                        bordercolor=ds.TOKENS["divider"]),
        showlegend=False,
        # Convention francaise : virgule decimale, espace pour les milliers.
        # Plotly lit ces deux caracteres dans cet ordre.
        separators=", ",
    )
    return fig


# --------------------------------------------------------------------------- #
# Vue generale
# --------------------------------------------------------------------------- #

def bar_years(df: pd.DataFrame) -> go.Figure | None:
    """Marchés par année. L'année tronquée est hachurée et bordée en
    pointillé — son volume n'est pas comparable aux années pleines."""
    if df.empty:
        return None
    colors, patterns, lines = [], [], []
    for tronquee in df["tronquee"]:
        colors.append(ds.TOKENS["a200"] if tronquee else ds.TOKENS["accent"])
        patterns.append("/" if tronquee else "")
        lines.append(ds.TOKENS["a400"] if tronquee else ds.TOKENS["accent"])

    fig = go.Figure(go.Bar(
        x=df["annee"].astype(str), y=df["n"],
        text=df["n"], textposition="outside",
        textfont=dict(size=12, color=ds.TOKENS["text"]),
        marker=dict(color=colors, line=dict(color=lines, width=1),
                    pattern=dict(shape=patterns, fgcolor=ds.TOKENS["a400"],
                                 size=4, solidity=0.35)),
        hovertemplate="%{x} · %{y} marchés<extra></extra>",
        width=0.55,
    ))
    # `type="category"` explicite : des annees rendues en chaines restent
    # lues comme des nombres par Plotly, qui intercalait alors des graduations
    # inventees ("2 023,5") entre les barres.
    fig.update_xaxes(type="category", showgrid=False,
                     tickfont=dict(size=11.5, color=ds.TOKENS["n600"]))
    fig.update_yaxes(visible=False, range=[0, df["n"].max() * 1.22])
    return _layout(fig, 210, dict(l=8, r=8, t=18, b=8))


def donut_sectors(df: pd.DataFrame, total: int | None = None) -> go.Figure | None:
    """Répartition par secteur — trois modalités équilibrées, le seul
    découpage du corpus qui se prête honnêtement à un anneau."""
    if df.empty:
        return None
    labels = [str(c).capitalize() for c in df["categorie"]]
    fig = go.Figure(go.Pie(
        labels=labels, values=df["n"], hole=0.62, sort=False,
        marker=dict(colors=SECTOR_COLORS[: len(df)],
                    line=dict(color=ds.TOKENS["surface"], width=2)),
        textinfo="none",
        hovertemplate="%{label} · %{value} marchés (%{percent})<extra></extra>",
    ))
    if total:
        fig.add_annotation(
            text=(f'<span style="font-size:19px;color:{ds.TOKENS["text"]}">'
                  f'{total}</span><br>'
                  f'<span style="font-size:10.5px;color:{ds.TOKENS["n600"]}">'
                  f'marchés</span>'),
            showarrow=False, font=FONT)
    return _layout(fig, 210)


def bars_horizontal(df: pd.DataFrame, label_col: str, value_col: str,
                    total: int, colors: list[str] | None = None,
                    height: int = 210) -> go.Figure | None:
    """Barres horizontales — utilisées pour la procédure de passation et la
    répartition de la qualité des données."""
    if df.empty:
        return None
    d = df.iloc[::-1]           # Plotly empile de bas en haut
    pct = (d[value_col] / total * 100) if total else d[value_col] * 0
    labels = [str(v) for v in d[label_col]]
    palette = (colors[::-1] if colors else [ds.TOKENS["accent"]] * len(d))
    fig = go.Figure(go.Bar(
        x=d[value_col], y=labels, orientation="h",
        marker=dict(color=palette),
        text=[f"{int(v)} · {p:.0f} %" for v, p in zip(d[value_col], pct)],
        textposition="outside",
        textfont=dict(size=11.5, color=ds.TOKENS["n700"]),
        hovertemplate="%{y} · %{x} marchés<extra></extra>",
    ))
    fig.update_xaxes(visible=False, range=[0, d[value_col].max() * 1.3])
    fig.update_yaxes(tickfont=dict(size=11.5, color=ds.TOKENS["n800"]),
                     showgrid=False)
    return _layout(fig, height, dict(l=8, r=8, t=8, b=8))


# --------------------------------------------------------------------------- #
# Anomalies et priorites
# --------------------------------------------------------------------------- #

def donut_priorities(df: pd.DataFrame) -> tuple[go.Figure, int] | None:
    """Répartition des priorités d'analyse, niveau « Faible » exclu.

    « Données insuffisantes » y figure en gris, hors de l'échelle de
    gravité : c'est un état distinct, jamais un niveau bas.
    """
    if df.empty:
        return None
    order = [p for p in ds.PRIORITY_ORDER if p != "Faible"]
    d = (df[df["niveau"].isin(order)]
         .set_index("niveau").reindex(order).dropna().reset_index())
    if d.empty:
        return None
    total = int(d["n"].sum())
    colors = [ds.RISK[ds.PRIORITY_ROLE[n]]["base"] for n in d["niveau"]]
    fig = go.Figure(go.Pie(
        labels=[ds.priority_display(n) for n in d["niveau"]],
        values=d["n"], hole=0.6, sort=False,
        marker=dict(colors=colors, line=dict(color=ds.TOKENS["surface"], width=2)),
        textinfo="none",
        hovertemplate="%{label} · %{value} marchés (%{percent})<extra></extra>",
    ))
    fig.add_annotation(
        text=(f'<span style="font-size:19px;color:{ds.TOKENS["text"]}">{total}</span>'
              f'<br><span style="font-size:10px;color:{ds.TOKENS["n600"]}">'
              f'marchés hors niveau Faible</span>'),
        showarrow=False, font=FONT)
    return _layout(fig, 240), total


def scatter_anomaly_flags(markets: pd.DataFrame) -> go.Figure | None:
    """Score d'anomalie contre score de red flags.

    Deux signaux quasi indépendants (c'est ce que mesure leur faible
    corrélation) : un marché peut être atypique sans red flag nommé, ou
    cumuler des red flags sans être isolé par le modèle. La taille du point
    traduit la confiance ; les points évidés signalent une confiance faible
    ou insuffisante.
    """
    if markets.empty:
        return None
    d = markets[markets["anomaly_score_0_100"].notna()
                & markets["red_flag_score"].notna()].copy()
    if d.empty:
        return None

    size_by_conf = {"Elevee": 11, "Moyenne": 9}
    open_conf = {"Faible", "Insuffisante"}

    fig = go.Figure()
    for level in ds.PRIORITY_ORDER:
        sub = d[d["priority_level"] == level]
        if sub.empty:
            continue
        color = ds.RISK[ds.PRIORITY_ROLE[level]]["base"]
        is_open = sub["confidence_level"].isin(open_conf)
        fig.add_trace(go.Scatter(
            x=sub["anomaly_score_0_100"], y=sub["red_flag_score"],
            mode="markers", name=ds.priority_display(level),
            marker=dict(
                size=[size_by_conf.get(c, 7) for c in sub["confidence_level"]],
                color=[ds.TOKENS["surface"] if o else color for o in is_open],
                opacity=0.85,
                line=dict(color=color, width=1.4),
            ),
            customdata=sub[["reference", "acheteur_public", "confidence_level"]].fillna(
                "Sans référence").values,
            hovertemplate=("<b>%{customdata[0]}</b><br>%{customdata[1]}"
                           "<br>Anomalie %{x:.1f} · Red flags %{y:.0f}"
                           "<br>Confiance : %{customdata[2]}<extra></extra>"),
        ))
    fig.update_xaxes(title_text="Score d'anomalie (0–100)", range=[-3, 103],
                     gridcolor=ds.TOKENS["n200"], zeroline=False,
                     title_font=dict(size=11, color=ds.TOKENS["n600"]),
                     tickfont=dict(size=10.5, color=ds.TOKENS["n500"]))
    fig.update_yaxes(title_text="Score red flags", range=[-3, 103],
                     gridcolor=ds.TOKENS["n200"], zeroline=False,
                     title_font=dict(size=11, color=ds.TOKENS["n600"]),
                     tickfont=dict(size=10.5, color=ds.TOKENS["n500"]))
    fig = _layout(fig, 300, dict(l=8, r=8, t=8, b=8))
    fig.update_layout(showlegend=True, legend=dict(
        orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
        font=dict(size=10.5, color=ds.TOKENS["n600"]), bgcolor="rgba(0,0,0,0)"))
    return fig


# --------------------------------------------------------------------------- #
# XAI
# --------------------------------------------------------------------------- #

def gauge_anomaly(value: float, bands: dict | None) -> go.Figure:
    """Jauge circulaire du score d'anomalie.

    Les bandes ne sont PAS des quarts arbitraires : elles reprennent les
    bornes mesurées sur la distribution réelle (`data_access
    .measured_risk_bands()`), c'est-à-dire la frontière que le modèle
    choisit lui-même pour « Faible » puis les terciles du sous-groupe
    signalé. Sans bandes mesurables, la jauge s'affiche nue.
    """
    steps = []
    if bands:
        edges = [(0, bands["faible_max"], "low"),
                 (bands["faible_max"], bands["modere_max"], "mid"),
                 (bands["modere_max"], bands["eleve_max"], "high"),
                 (bands["eleve_max"], 100, "crit")]
        # Teinte `line` et non `bg` : le fond des bandes doit rester lisible
        # sur une surface blanche sans crier — verifie a l'ecran, les tons
        # `bg` y etaient quasi invisibles.
        steps = [dict(range=[a, b], color=ds.RISK[role]["line"]) for a, b, role in edges]

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=float(value),
        # Domaine explicite, avec de la marge en haut : sans elle, le label
        # "50" (au sommet de l'arc, la ou la courbure est la plus forte)
        # touche le bord du canevas et parait tronque — les quatre autres
        # labels ont de la place car ils sont plus bas sur l'arc. Reserver
        # 14 % de hauteur au-dessus de l'arc suffit a le degager partout.
        domain=dict(x=[0.04, 0.96], y=[0, 0.86]),
        number=dict(font=dict(size=34, color=ds.TOKENS["text"],
                              family="Inter, system-ui, sans-serif"),
                    valueformat=".1f",
                    suffix="<span style='font-size:14px;color:#64748B'> / 100</span>"),
        gauge=dict(
            axis=dict(range=[0, 100], tickwidth=1, tickcolor=ds.TOKENS["n400"],
                      tickfont=dict(size=10.5, color=ds.TOKENS["n500"]),
                      tickvals=[0, 25, 50, 75, 100], ticklen=6),
            bar=dict(color=ds.TOKENS["text"], thickness=0.16),
            bgcolor=ds.TOKENS["n100"], borderwidth=0,
            steps=steps,
        ),
    ))
    return _layout(fig, 250, dict(l=20, r=20, t=38, b=4))


def bars_shap(labels: list[str], values: list[float],
              imputed: list[bool] | None = None) -> go.Figure | None:
    """Trois contributions SHAP les plus fortes.

    Une contribution assise sur une valeur imputée est marquée : elle
    n'explique pas une observation, mais une médiane substituée.
    """
    if not labels:
        return None
    imputed = imputed or [False] * len(labels)
    texts = [f"{v:+.3f}".replace(".", ",") for v in values]
    ticks = [f"{lab} ⚠" if imp else lab for lab, imp in zip(labels, imputed)]
    fig = go.Figure(go.Bar(
        x=values[::-1], y=ticks[::-1], orientation="h",
        marker=dict(color=[ds.TOKENS["a400"] if imp else ds.TOKENS["accent"]
                           for imp in imputed][::-1]),
        text=texts[::-1], textposition="outside",
        textfont=dict(size=11.5, color=ds.TOKENS["n700"]),
        hovertemplate="%{y} · contribution %{x:.3f}<extra></extra>",
    ))
    span = max(abs(min(values)), abs(max(values))) or 1
    fig.update_xaxes(visible=False, range=[min(0, min(values) * 1.35), span * 1.35])
    fig.update_yaxes(tickfont=dict(size=11.5, color=ds.TOKENS["n800"]), showgrid=False)
    return _layout(fig, 190, dict(l=8, r=8, t=8, b=8))
