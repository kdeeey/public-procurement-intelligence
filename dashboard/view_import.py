"""
Page « Importation » — validation de fichier, et rien d'autre.

PERIMETRE HONNETE, PAS UNE PROMESSE
-------------------------------------
`dashboard.md` Sec 9 est explicite : la chaine ingere des PDF (scraping →
OCR → extraction), elle n'accepte pas de CSV. Une page qui proposerait
« importez vos donnees » mentirait sur les capacites du produit. Cette
page controle donc un fichier — format, colonnes reconnues et manquantes,
apercu, valeurs incoherentes — et n'ecrit rien : ni dans le corpus, ni en
base, ni dans un parquet. Aucun OCR, aucune extraction, aucun score.

LE SCHEMA ATTENDU EST LU, PAS ECRIT
-------------------------------------
Les colonnes proposees viennent de `market_features.parquet` lui-meme, et
le caractere « attendu » de chacune est MESURE : une colonne renseignee
sur 100 % du corpus est presentee comme attendue, les autres comme
facultatives avec leur taux de remplissage reel. Aucune liste de colonnes
n'est ecrite en dur ici.
"""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from dashboard import data_access as da
from dashboard import design_system as ds

PAGE_DOES = [
    "Sélection du fichier et contrôle du format",
    "Détection des colonnes reconnues et des colonnes manquantes",
    "Aperçu des premières lignes",
    "Signalement des colonnes entièrement vides",
]
PAGE_DOES_NOT = [
    "Aucun OCR ni extraction de document",
    "Aucun calcul de score ni entraînement de modèle",
    "Aucune écriture dans le corpus analytique ni en base",
    "Aucun historique d'importation : il n'existe pas de journal d'import "
    "dans le projet",
]


def _schema() -> pd.DataFrame:
    """[(colonne, taux de remplissage, attendue)] lus dans le corpus reel."""
    corpus = da.load_corpus()
    if corpus.empty:
        return pd.DataFrame(columns=["colonne", "rempli", "pct", "attendue"])
    n = len(corpus)
    rows = []
    for col in corpus.columns:
        rempli = int(corpus[col].notna().sum())
        rows.append({"colonne": col, "rempli": rempli,
                     "pct": 100.0 * rempli / n, "attendue": rempli == n})
    return pd.DataFrame(rows).sort_values(
        ["attendue", "colonne"], ascending=[False, True]).reset_index(drop=True)


def _render_schema(schema: pd.DataFrame) -> None:
    with ds.card("Colonnes attendues par la validation",
                   f"{len(schema)} colonnes lues dans market_features.parquet"):
        ds.render_caption(
            "Schéma lu depuis la table analytique de référence. Une colonne est "
            "présentée comme <strong>attendue</strong> lorsqu'elle est renseignée sur "
            "100 % du corpus, <strong>facultative</strong> sinon — avec son taux de "
            "remplissage réel. Aucune importation antérieure n'est affichée : il "
            "n'existe pas de journal d'import dans le projet.")
        chips = []
        for _, row in schema.iterrows():
            attendue = bool(row["attendue"])
            color = ds.TOKENS["a800"] if attendue else ds.TOKENS["n600"]
            bg = ds.TOKENS["a100"] if attendue else ds.TOKENS["n200"]
            border = ds.TOKENS["a300"] if attendue else ds.TOKENS["divider"]
            tip = (f"{row['colonne']} — renseignée sur {int(row['rempli'])} marchés "
                   f"({row['pct']:.0f} %)")
            chips.append(
                f'<span class="tag" title="{ds.esc(tip)}" style="font-size:11.5px;'
                f'font-family:ui-monospace,SFMono-Regular,Menlo,monospace;'
                f'padding:4px 9px;color:{color};background:{bg};'
                f'border:1px solid {border}">{ds.esc(row["colonne"])}</span>')
        st.markdown(
            f'<div style="display:flex;flex-wrap:wrap;gap:var(--space-2);'
            f'margin-top:var(--space-6)">{"".join(chips)}</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div style="display:flex;gap:var(--space-6);margin-top:var(--space-4);'
            f'padding-top:var(--space-4);border-top:1px solid {ds.TOKENS["divider"]};'
            f'font-size:11.5px;color:{ds.TOKENS["n600"]};flex-wrap:wrap">'
            f'<span style="display:inline-flex;align-items:center;gap:var(--space-2)">'
            f'<span style="width:9px;height:9px;border-radius:2px;'
            f'background:{ds.TOKENS["accent"]}"></span>Attendue '
            f'(renseignée sur 100 % du corpus)</span>'
            f'<span style="display:inline-flex;align-items:center;gap:var(--space-2)">'
            f'<span style="width:9px;height:9px;border-radius:2px;'
            f'background:{ds.TOKENS["n400"]}"></span>Facultative</span></div>',
            unsafe_allow_html=True)


def _validate(uploaded, schema: pd.DataFrame) -> None:
    """Lit le fichier depose et rapporte ce qu'il contient. N'ecrit rien."""
    name = uploaded.name
    try:
        if name.lower().endswith(".parquet"):
            df = pd.read_parquet(io.BytesIO(uploaded.getvalue()))
        else:
            df = pd.read_csv(io.BytesIO(uploaded.getvalue()))
    except Exception as exc:  # noqa: BLE001 — tout echec de lecture est un resultat
        ds.render_warning(f"Le fichier n'a pas pu être lu : {exc}",
                          "Format non exploitable")
        return

    attendues = set(schema.loc[schema["attendue"], "colonne"])
    connues = set(schema["colonne"])
    presentes = set(df.columns)
    reconnues = sorted(presentes & connues)
    manquantes = sorted(attendues - presentes)
    inconnues = sorted(presentes - connues)
    vides = sorted(c for c in df.columns if df[c].notna().sum() == 0)

    st.markdown('<div style="height:var(--space-4)"></div>', unsafe_allow_html=True)
    ds.render_metric_row([
        ds.render_metric_card("Lignes lues", f"{len(df)}", name, size=24),
        ds.render_metric_card("Colonnes reconnues", f"{len(reconnues)}",
                              f"sur {len(presentes)} présentes", size=24),
        ds.render_metric_card("Colonnes attendues manquantes", f"{len(manquantes)}",
                              "bloquantes pour le pipeline",
                              muted=len(manquantes) == 0, size=24),
        ds.render_metric_card("Colonnes entièrement vides", f"{len(vides)}",
                              "aucune valeur lisible",
                              muted=len(vides) == 0, size=24),
    ])

    if manquantes:
        ds.render_warning(", ".join(manquantes),
                          "Colonnes attendues absentes du fichier")
    if vides:
        ds.render_warning(
            ", ".join(vides),
            "Colonnes présentes mais entièrement vides — une colonne vide n'est "
            "pas une colonne à zéro")
    if inconnues:
        ds.render_caption(
            f"{len(inconnues)} colonne(s) non reconnue(s), ignorée(s) par la "
            f"validation : {', '.join(inconnues[:12])}"
            + (" …" if len(inconnues) > 12 else ""))
    if not manquantes and not vides:
        st.markdown(
            f'<div class="pmmp-note" style="border-left-color:{ds.RISK["low"]["base"]}">'
            f'Toutes les colonnes attendues sont présentes et renseignées. '
            f'Aucune donnée n\'a été ajoutée au corpus : cette page valide, elle '
            f'n\'importe pas.</div>', unsafe_allow_html=True)

    st.markdown('<div style="height:var(--space-4)"></div>', unsafe_allow_html=True)
    st.markdown('<h6 style="margin:0;color:var(--color-neutral-600)">Aperçu — '
                '20 premières lignes</h6>', unsafe_allow_html=True)
    st.dataframe(df.head(20), use_container_width=True, hide_index=True)


def render() -> None:
    ds.render_section_header(
        "Importation",
        "Préparer et vérifier de nouvelles données avant traitement.")

    ds.render_warning(
        "Validation seule : aucune donnée n'est ajoutée au corpus. L'intégration "
        "automatique dans le pipeline n'est pas activée — la chaîne réelle ingère "
        "des PDF (scraping → OCR → extraction), pas des tableaux.")

    st.markdown('<div style="height:var(--space-4)"></div>', unsafe_allow_html=True)
    with ds.card():
        uploaded = st.file_uploader(
            "Déposer un fichier à vérifier", type=["csv", "parquet"],
            help="Le contrôle porte sur le format et les colonnes attendues ; aucun "
                 "traitement OCR, extraction ou modèle n'est déclenché.")

        left, right = st.columns(2)
        left.markdown(
            '<div style="border-radius:var(--radius-md);padding:var(--space-4);'
            f'background:{ds.TOKENS["n100"]}">'
            '<div style="font-size:12.5px;font-weight:500">Ce que la page fait</div>'
            + "".join(
                f'<div style="display:flex;gap:var(--space-2);font-size:12px;'
                f'color:{ds.TOKENS["n800"]};line-height:1.5;margin-top:var(--space-2)">'
                f'<span style="color:{ds.TOKENS["n400"]}">—</span><span>{ds.esc(i)}</span>'
                f'</div>' for i in PAGE_DOES)
            + "</div>", unsafe_allow_html=True)
        right.markdown(
            '<div style="border-radius:var(--radius-md);padding:var(--space-4);'
            f'background:{ds.TOKENS["n100"]}">'
            '<div style="font-size:12.5px;font-weight:500">Ce qu\'elle ne fait pas</div>'
            + "".join(
                f'<div style="display:flex;gap:var(--space-2);font-size:12px;'
                f'color:{ds.TOKENS["n600"]};line-height:1.5;margin-top:var(--space-2)">'
                f'<span style="color:{ds.TOKENS["n400"]}">—</span><span>{ds.esc(i)}</span>'
                f'</div>' for i in PAGE_DOES_NOT)
            + "</div>", unsafe_allow_html=True)

    schema = _schema()
    if schema.empty:
        ds.render_empty_state(
            "Schéma de référence indisponible",
            "market_features.parquet est absent : la validation n'a aucune "
            "référence à laquelle comparer un fichier déposé.")
        return

    if uploaded is not None:
        _validate(uploaded, schema)

    st.markdown('<div style="height:var(--space-4)"></div>', unsafe_allow_html=True)
    _render_schema(schema)
