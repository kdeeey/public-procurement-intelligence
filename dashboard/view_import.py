"""
Page « Importation » — validation de fichier, puis calcul des features
d'analyse sur les lignes deposees. Toujours rien ecrit dans le corpus.

PERIMETRE HONNETE, PAS UNE PROMESSE
-------------------------------------
`dashboard.md` Sec 9 est explicite : la chaine ingere des PDF (scraping →
OCR → extraction), elle n'accepte pas de CSV. Une page qui proposerait
« importez vos donnees » mentirait sur les capacites du produit. Cette
page controle un fichier — format, colonnes reconnues et manquantes,
apercu, valeurs incoherentes — et n'ecrit rien : ni dans le corpus, ni en
base, ni dans un parquet. Aucun OCR, aucune extraction.

Elle calcule en revanche, EN MEMOIRE et pour affichage seul, les memes red
flags et le meme score que le pipeline reel (voir `_score_uploaded`
ci-dessous) — reutilise le registre de red flags (`ai/market_red_flags.py`),
le modele Isolation Forest deja entraine SUR ces flags
(`ai/train_market_model.py`) et la formule de priorite
(`ai/priority_score.py`), jamais reimplemente en double.

LE SCHEMA ATTENDU EST LU, PAS ECRIT
-------------------------------------
Les colonnes proposees viennent de `market_features.parquet` lui-meme, et
le caractere « attendu » de chacune est MESURE : une colonne renseignee
sur 100 % du corpus est presentee comme attendue, les autres comme
facultatives avec leur taux de remplissage reel. Aucune liste de colonnes
n'est ecrite en dur ici.

CE QUI EST RECALCULE, ET CE QUI VIENT DU PIPELINE REEL
----------------------------------------------------------
Depuis la refonte "red flags only", le modele s'entraine SUR RF01/RF02/RF03
(ai/train_market_model.py) : reproduire son entree revient donc a evaluer
ces 3 red flags sur les lignes deposees, avec les MEMES seuils que le
pipeline reel (`red_flag_thresholds.json`, jamais recalcules sur le
fichier). Le niveau de priorite reste une fonction pure du compte de flags
actifs (`ai/priority_score.py::assign_level`) — le score du modele ne sert
qu'a departager des lignes a egalite de compte, exactement comme dans la
chaine reelle.

FIABILITE DU SCORE SUR DES DONNEES HORS CORPUS
-------------------------------------------------
Le modele a ete entraine sur les marches ATTRIBUE du corpus reel. Les memes
seuils de red flags et le meme modele sont reutilises tels quels — RIEN
n'est reentraine sur le fichier depose. Un score obtenu ici mesure un ECART
A LA POPULATION D'ENTRAINEMENT, pas une verite sur des donnees nouvelles ou
synthetiques : voir l'avertissement affiche avec chaque resultat.
"""

from __future__ import annotations

import io
import json

import joblib
import numpy as np
import pandas as pd
import streamlit as st

from dashboard import data_access as da
from dashboard import design_system as ds

MODELS_DIR = ds.REPO / "ai" / "models"
ANALYTICS_DIR = ds.REPO / "data" / "processed" / "analytics"
MODEL_PATH = MODELS_DIR / "isolation_forest_market.joblib"
FEATURE_COLUMNS_PATH = MODELS_DIR / "market_feature_columns.json"
SCORES_PATH = ANALYTICS_DIR / "market_anomaly_scores.parquet"
RED_FLAG_THRESHOLDS_PATH = ANALYTICS_DIR / "red_flag_thresholds.json"

# Au-dela de ce nombre de lignes, les red flags et le score de priorite
# (boucle Python ligne par ligne, contrairement au score d'anomalie qui est
# vectorise via sklearn) ne sont calcules que sur un echantillon, pour que
# la page reste utilisable sur un fichier volumineux. Le score d'anomalie,
# lui, reste calcule sur TOUTES les lignes.
MAX_ROWS_RED_FLAGS = 1000

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


@st.cache_resource(show_spinner=False)
def _load_scoring_artifacts():
    """Charge une seule fois les artefacts du pipeline reel : modele
    entraine (sur RF01/RF02/RF03), colonnes de features, et seuils de red
    flags. Retourne None si l'un d'eux est absent — la page continue alors
    a valider sans scorer, plutot que de planter."""
    try:
        model = joblib.load(MODEL_PATH)
        features = json.loads(FEATURE_COLUMNS_PATH.read_text(encoding="utf-8"))
        rf_thresholds = json.loads(
            RED_FLAG_THRESHOLDS_PATH.read_text(encoding="utf-8"))
        ref_scores = pd.read_parquet(SCORES_PATH)
    except Exception:  # noqa: BLE001 — artefact manquant = pas de scoring
        return None
    lo, hi = float(ref_scores["anomaly_score"].min()), float(ref_scores["anomaly_score"].max())
    return {
        "model": model, "features": features,
        "lo": lo, "hi": hi, "rf_thresholds": rf_thresholds,
    }


def _derive_model_features(flags_df: pd.DataFrame, raw_df: pd.DataFrame) -> pd.DataFrame:
    """RF01/RF02/RF03 (True/False/None) -> matrice numerique pour le modele,
    exactement comme `ai/train_market_model.py::prepare_market_matrix()` :
    un flag non evaluable est impute a 0, jamais a une mediane (un booleen
    n'en a pas), avec son drapeau de disponibilite a cote. Les drapeaux
    eux-memes sont approximes depuis les colonnes brutes deposees
    (`nb_soumissionnaires`, `exclusion_rate`/`nb_concurrents_ecartes`,
    `montant_ttc`) — le pipeline reel les lit dans le document source, ce
    qu'un fichier tabulaire depose ne porte pas."""
    from ai.train_market_model import IMPUTED_COLUMNS

    out = pd.DataFrame(index=flags_df.index)
    for flag_col in IMPUTED_COLUMNS:
        out[flag_col] = pd.to_numeric(flags_df[flag_col], errors="coerce").fillna(0.0)

    out["has_competitor_data"] = (
        pd.to_numeric(raw_df.get("nb_soumissionnaires"), errors="coerce").notna().astype(int)
        if "nb_soumissionnaires" in raw_df.columns else 0)
    if "exclusion_rate" in raw_df.columns:
        out["has_exclusion_data"] = pd.to_numeric(
            raw_df["exclusion_rate"], errors="coerce").notna().astype(int)
    elif "nb_concurrents_ecartes" in raw_df.columns:
        out["has_exclusion_data"] = pd.to_numeric(
            raw_df["nb_concurrents_ecartes"], errors="coerce").notna().astype(int)
    else:
        out["has_exclusion_data"] = 0
    out["has_amount_data"] = (
        pd.to_numeric(raw_df.get("montant_ttc"), errors="coerce").notna().astype(int)
        if "montant_ttc" in raw_df.columns else 0)
    return out


def _score_uploaded(df: pd.DataFrame, artifacts: dict) -> pd.DataFrame:
    """Evalue RF01/RF02/RF03, le score du modele (entraine sur ces memes
    flags) et le niveau de priorite sur les lignes deposees. Renvoie un
    DataFrame de resultats ALIGNE sur l'index de `df` — rien n'est ecrit
    sur disque.

    La boucle Python (`evaluate_market` par ligne) borne desormais AUSSI le
    score du modele, pas seulement les red flags : les deux partagent la
    meme entree depuis la refonte "red flags only" — d'ou l'echantillon
    unique `MAX_ROWS_RED_FLAGS` applique aux deux.
    """
    from ai.market_red_flags import evaluate_market, summarize
    from ai.priority_score import assign_level, compute_priority_raw

    n = len(df)
    sample_idx = df.index[:MAX_ROWS_RED_FLAGS]
    rf_thresholds = artifacts["rf_thresholds"]
    rf_rows = []
    for i in sample_idx:
        flags = evaluate_market(df.loc[i], rf_thresholds)
        row = summarize(flags)
        for f in ("RF01", "RF02", "RF03"):
            row[f] = flags[f]
        rf_rows.append(row)
    rf_df = pd.DataFrame(rf_rows, index=sample_idx)
    rf_df["priority_flag_count"] = sum(
        (rf_df[f] == True).astype(int) for f in ("RF01", "RF02", "RF03"))  # noqa: E712

    feat_df = _derive_model_features(rf_df, df.loc[sample_idx])
    features = artifacts["features"]
    X = feat_df[features].to_numpy(dtype=float)

    raw = artifacts["model"].decision_function(X)
    lo, hi = artifacts["lo"], artifacts["hi"]
    anomaly_0_100 = np.clip(100 * (hi - raw) / (hi - lo), 0, 100) if hi > lo else raw * 0 + 50.0

    result = rf_df.copy()
    result["anomaly_score_0_100"] = anomaly_0_100
    result["priority_raw"] = [
        compute_priority_raw(pd.Series({"anomaly_score_0_100": a, "priority_flag_count": c}))
        for a, c in zip(anomaly_0_100, rf_df["priority_flag_count"])]
    result["priority_level"] = [assign_level(r, "Elevee") for r in result["priority_raw"]]

    result.attrs["sampled_red_flags"] = n > MAX_ROWS_RED_FLAGS
    result.attrs["sample_size"] = len(sample_idx)
    return result


_IDENTITY_COLS = ["reference", "objet", "acheteur_public", "categorie_principale",
                  "mode_passation", "montant_ttc"]


def _render_scoring(df: pd.DataFrame, artifacts: dict) -> None:
    st.markdown('<div style="height:var(--space-6)"></div>', unsafe_allow_html=True)
    try:
        scored = _score_uploaded(df, artifacts)
    except Exception as exc:  # noqa: BLE001 — colonnes insuffisantes pour scorer
        with ds.card("Features calculées et score"):
            ds.render_empty_state(
                "Scoring impossible sur ce fichier",
                f"Colonnes insuffisantes pour reconstituer les features du modèle : {exc}")
        return

    meta = (f"échantillon {scored.attrs['sample_size']} lignes pour les red flags"
           if scored.attrs.get("sampled_red_flags") else "")
    with ds.card("Features calculées et score",
                meta, help="Mêmes formules que le pipeline réel "
                "(ai/train_market_model.py, ai/market_red_flags.py, "
                "ai/priority_score.py), appliquées ici en mémoire — rien n'est écrit."):
        ds.render_warning(
            "Modèle entraîné sur les 314 marchés ATTRIBUÉ du corpus réel, PAS "
            "réentraîné ici. Un score obtenu sur ce fichier mesure un écart à cette "
            "population d'entraînement, pas une vérité sur des données nouvelles ou "
            "synthétiques.",
            "Fiabilité non garantie hors corpus d'entraînement")

        st.markdown('<div style="height:var(--space-4)"></div>', unsafe_allow_html=True)
        n_tres_prio = int((scored["priority_level"] == "Tres prioritaire").sum())
        n_prio = int((scored["priority_level"] == "Prioritaire").sum())
        n_trois_flags = int((scored["priority_flag_count"] == 3).sum())
        cards = [
            ds.render_metric_card("Lignes scorées", f"{len(scored)}",
                                  "red flags + score du modèle", size=22),
            ds.render_metric_card("Très prioritaire", f"{n_tres_prio}", "", size=22,
                                  muted=n_tres_prio == 0),
            ds.render_metric_card("Prioritaire", f"{n_prio}", "", size=22,
                                  muted=n_prio == 0),
            ds.render_metric_card("3/3 red flags actifs", f"{n_trois_flags}",
                                  "RF01+RF02+RF03", size=22, muted=n_trois_flags == 0),
        ]
        ds.render_metric_row(cards)

        st.markdown('<div style="height:var(--space-4)"></div>', unsafe_allow_html=True)
        st.markdown('<h6 style="margin:0 0 var(--space-2);color:var(--color-neutral-600)">'
                    'Résultat par ligne — 20 premières</h6>', unsafe_allow_html=True)
        score_cols = [c for c in (
            "priority_flag_count", "anomaly_score_0_100", "red_flag_count",
            "red_flags_triggered", "priority_level") if c in scored.columns]
        identity_cols = [c for c in _IDENTITY_COLS if c in df.columns][:3]
        preview = df.loc[scored.index, identity_cols].join(scored[score_cols]).head(20)
        st.dataframe(preview, use_container_width=True, hide_index=True)

        with st.expander("Voir toutes les colonnes calculées et déposées"):
            all_cols = [c for c in (
                "RF01", "RF02", "RF03", "priority_flag_count", "anomaly_score_0_100",
                "red_flag_count", "red_flags_triggered", "red_flag_score",
                "priority_raw", "priority_level") if c in scored.columns]
            st.dataframe(df.loc[scored.index].join(scored[all_cols]).head(20),
                        use_container_width=True, hide_index=True)


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

    st.markdown('<div style="height:var(--space-6)"></div>', unsafe_allow_html=True)
    with ds.card("Résultat de la validation", f"{name}"):
        ds.render_metric_row([
            ds.render_metric_card("Lignes lues", f"{len(df)}", "", size=22),
            ds.render_metric_card("Colonnes reconnues", f"{len(reconnues)}",
                                  f"sur {len(presentes)} présentes", size=22),
            ds.render_metric_card("Colonnes attendues manquantes", f"{len(manquantes)}",
                                  "bloquantes pour le pipeline",
                                  muted=len(manquantes) == 0, size=22),
            ds.render_metric_card("Colonnes entièrement vides", f"{len(vides)}",
                                  "aucune valeur lisible",
                                  muted=len(vides) == 0, size=22),
        ])
        st.markdown('<div style="height:var(--space-4)"></div>', unsafe_allow_html=True)

        if manquantes:
            ds.render_warning(
                ", ".join(manquantes[:6]) + (f" … (+{len(manquantes) - 6})"
                                             if len(manquantes) > 6 else ""),
                "Colonnes attendues absentes du fichier")
            if len(manquantes) > 6:
                with st.expander(f"Voir les {len(manquantes)} colonnes manquantes"):
                    st.write(", ".join(manquantes))
        if vides:
            ds.render_warning(
                ", ".join(vides[:6]) + (f" … (+{len(vides) - 6})" if len(vides) > 6 else ""),
                "Colonnes présentes mais entièrement vides — une colonne vide n'est "
                "pas une colonne à zéro")
            if len(vides) > 6:
                with st.expander(f"Voir les {len(vides)} colonnes vides"):
                    st.write(", ".join(vides))
        if inconnues:
            with st.expander(f"{len(inconnues)} colonne(s) non reconnue(s), ignorée(s) "
                             "par la validation"):
                st.write(", ".join(inconnues))
        if not manquantes and not vides:
            st.markdown(
                f'<div class="pmmp-note" style="border-left-color:{ds.RISK["low"]["base"]}">'
                f'Toutes les colonnes attendues sont présentes et renseignées. '
                f'Aucune donnée n\'a été ajoutée au corpus : cette page valide, elle '
                f'n\'importe pas.</div>', unsafe_allow_html=True)

    st.markdown('<div style="height:var(--space-4)"></div>', unsafe_allow_html=True)
    with ds.card("Aperçu", "20 premières lignes du fichier déposé"):
        st.dataframe(df.head(20), use_container_width=True, hide_index=True, height=250)

    artifacts = _load_scoring_artifacts()
    if artifacts is None:
        st.markdown('<div style="height:var(--space-4)"></div>', unsafe_allow_html=True)
        ds.render_empty_state(
            "Modèle de scoring indisponible",
            "Le modèle entraîné ou ses artefacts sont absents — lancer "
            "`python -m ai.train_market_model`, `python -m ai.market_red_flags` "
            "et `python -m ai.priority_score` pour les générer.")
        return
    _render_scoring(df, artifacts)


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
