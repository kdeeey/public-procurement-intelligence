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


def bars_flag_count(df: pd.DataFrame) -> go.Figure | None:
    """Répartition des marchés scorables par nombre de red flags
    prioritaires actifs (0 à 3, RF01+RF02+RF03) — remplace le nuage
    anomalie/red flags depuis la refonte "red flags only" : c'est
    directement ce compte qui décide `priority_level`
    (ai/priority_score.py), donc c'est lui que ce graphique montre, pas une
    corrélation entre deux scores qui n'entrent plus tous les deux dans la
    décision.
    """
    if df.empty:
        return None
    d = df.copy()
    d["compte"] = d["compte"].astype(int)
    labels = {0: "0/3 — Faible", 1: "1/3 — À surveiller",
              2: "2/3 — Prioritaire", 3: "3/3 — Très prioritaire"}
    roles = {0: "low", 1: "mid", 2: "high", 3: "crit"}
    d = d.set_index("compte").reindex([0, 1, 2, 3], fill_value=0).reset_index()
    colors = [ds.RISK[roles[c]]["base"] for c in d["compte"]]
    fig = go.Figure(go.Bar(
        x=[labels[c] for c in d["compte"]], y=d["n"],
        marker=dict(color=colors),
        text=[str(int(v)) for v in d["n"]], textposition="outside",
        textfont=dict(size=11.5, color=ds.TOKENS["n700"]),
        hovertemplate="%{x} · %{y} marchés<extra></extra>",
    ))
    fig.update_xaxes(tickfont=dict(size=10.5, color=ds.TOKENS["n700"]), showgrid=False)
    fig.update_yaxes(visible=False, range=[0, max(d["n"].max() * 1.25, 1)])
    return _layout(fig, 260, dict(l=8, r=8, t=18, b=8))


# --------------------------------------------------------------------------- #
# XAI
# --------------------------------------------------------------------------- #


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
