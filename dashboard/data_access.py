"""
Acces aux donnees du dashboard — une seule porte d'entree, en lecture seule.

CE MODULE NE CALCULE AUCUN SCORE
---------------------------------
Il lit les parquet deja produits par le pipeline (`ai/`, `features/`,
`bigdata/`) et se contente d'agreger pour l'affichage. Aucun seuil, aucun
score, aucune regle metier n'est redefini ici : les red flags viennent du
registre de `ai/market_red_flags.py`, les etats de qualite de
`features/data_quality.py`, les niveaux de risque et de priorite des
colonnes deja ecrites par `ai/train_market_model.py` et
`ai/priority_score.py`.

REUTILISATION PLUTOT QUE DUPLICATION
-------------------------------------
`load_markets()` delegue a `dashboard/market_view.py::load_markets()`, la
fonction de chargement deja en place : meme jointure, meme cache, meme
tolerance aux fichiers absents. La dupliquer aurait cree deux verites sur
la meme table.

`load_corpus()` est nouveau et necessaire : `load_markets()` ne couvre que
les 314 marches ATTRIBUE que le modele score, alors que la Vue generale
compte le corpus entier. Il lit `market_features.parquet` (tous les
marches, infructueux compris) et y joint la qualite des donnees.

AUCUN CHIFFRE N'EST ECRIT EN DUR
---------------------------------
Les bornes de l'echelle de risque elles-memes sont RELUES depuis la
distribution reelle (`measured_risk_bands()`), avec exactement la regle
d'`ai/train_market_model.py` : la frontiere "Faible" est celle que le
modele choisit lui-meme (`is_anomaly`), le sous-groupe signale est coupe
en terciles mesures. Les recopier en constantes les aurait laissees se
perimer au premier reentrainement — c'est le motif que
`database/crud/counts.py` a ete cree pour supprimer.
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

from dashboard import design_system as ds  # noqa: E402
from dashboard.market_view import load_markets as _load_markets_joined  # noqa: E402

ANALYTICS = REPO / "data/processed/analytics"

FEATURES_PATH = ANALYTICS / "market_features.parquet"
DATA_QUALITY_PATH = ANALYTICS / "market_data_quality.parquet"
SCORES_PATH = ANALYTICS / "market_anomaly_scores.parquet"
RED_FLAGS_PATH = ANALYTICS / "market_red_flags.parquet"
EXPLANATIONS_PATH = ANALYTICS / "market_explanations.parquet"
PEER_PATH = ANALYTICS / "market_peer_comparison.parquet"
PRIORITY_PATH = ANALYTICS / "market_priority.parquet"

# Chaque source, avec la commande qui la produit — un message d'erreur qui
# dit quoi relancer vaut mieux qu'un "fichier introuvable".
SOURCES = {
    "market_features.parquet": ("corpus complet, marchés infructueux compris",
                                "python -m bigdata.spark.jobs.build_market_features"),
    "market_data_quality.parquet": ("qualité des données",
                                    "python -m features.data_quality"),
    "market_anomaly_scores.parquet": ("scores d'anomalie",
                                      "python -m ai.train_market_model"),
    "market_red_flags.parquet": ("red flags métier", "python -m ai.market_red_flags"),
    "market_explanations.parquet": ("explications SHAP", "python -m ai.market_explain"),
    "market_peer_comparison.parquet": ("comparaison aux pairs",
                                       "python -m ai.market_peer_analysis"),
    "market_priority.parquet": ("score de priorité", "python -m ai.priority_score"),
}


# --------------------------------------------------------------------------- #
# Etat des sources
# --------------------------------------------------------------------------- #

def missing_sources() -> list[tuple[str, str, str]]:
    """[(fichier, ce qu'il porte, commande a relancer)] pour les absents."""
    return [(name, label, cmd) for name, (label, cmd) in SOURCES.items()
            if not (ANALYTICS / name).exists()]


def has_source(name: str) -> bool:
    return (ANALYTICS / name).exists()


# --------------------------------------------------------------------------- #
# Chargements
# --------------------------------------------------------------------------- #

def load_markets() -> pd.DataFrame:
    """314 marchés ATTRIBUE, scores et red flags joints — délègue à
    `dashboard/market_view.py::load_markets()`, déjà en place et déjà en
    cache. Renvoie un DataFrame vide si le parquet de scores manque."""
    return _load_markets_joined()


@st.cache_data(ttl=60)
def load_corpus() -> pd.DataFrame:
    """Le corpus ENTIER (attribués + infructueux), avec la qualité jointe.

    Distinct de `load_markets()` : les marchés infructueux ne sont pas
    scorés par le modèle mais ils existent, ils sont comptés, et la Vue
    générale doit les montrer — le total du corpus ne doit pas les faire
    disparaître.
    """
    if not FEATURES_PATH.exists():
        return pd.DataFrame()
    df = pd.read_parquet(FEATURES_PATH)
    if DATA_QUALITY_PATH.exists():
        df = df.merge(pd.read_parquet(DATA_QUALITY_PATH), on="award_id", how="left")
    return df


@st.cache_data(ttl=60)
def load_json_report(name: str) -> dict:
    path = ANALYTICS / name
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


# --------------------------------------------------------------------------- #
# Agregats derives — tous relus, aucun fige
# --------------------------------------------------------------------------- #

@st.cache_data(ttl=60)
def corpus_kpis() -> dict:
    """Les compteurs de la Vue générale, calculés à l'instant.

    `None` partout où la source manque : une valeur absente s'affiche
    "Non disponible", jamais 0.
    """
    corpus, markets = load_corpus(), load_markets()
    out = {
        "total": None, "attribues": None, "infructueux": None,
        "scorables": None, "atypiques": None, "insuffisants": None,
        "qualite_moyenne": None, "qualite_niveau": None,
        "acheteurs": None, "annees": None,
    }
    if not corpus.empty:
        out["total"] = len(corpus)
        statuts = corpus["statut"].value_counts()
        out["attribues"] = int(statuts.get("ATTRIBUE", 0))
        out["infructueux"] = int(statuts.get("INFRUCTUEUX", 0))
        out["acheteurs"] = int(corpus["acheteur_public"].nunique())
        annees = corpus["annee"].dropna()
        if len(annees):
            out["annees"] = (int(annees.min()), int(annees.max()))
        if "data_quality_score" in corpus.columns:
            moyenne = corpus["data_quality_score"].mean()
            if pd.notna(moyenne):
                out["qualite_moyenne"] = float(moyenne)
                # Le niveau vient de la MEME fonction que le pipeline, jamais
                # d'un second jeu de seuils recopie ici.
                from features.data_quality import quality_level
                out["qualite_niveau"] = quality_level(float(moyenne))
    if not markets.empty:
        out["scorables"] = int((markets["scorable"] == True).sum())  # noqa: E712
        out["atypiques"] = int(markets["is_anomaly"].fillna(False).astype(bool).sum())
        out["insuffisants"] = int((markets["scorable"] != True).sum())  # noqa: E712
    return out


@st.cache_data(ttl=60)
def counts_by_year() -> pd.DataFrame:
    """Marchés par année sur le corpus entier, avec le drapeau d'année
    tronquée lu depuis `ai/market_temporal_analysis.py` — pas une année
    écrite en dur ici."""
    corpus = load_corpus()
    if corpus.empty or "annee" not in corpus.columns:
        return pd.DataFrame(columns=["annee", "n", "tronquee"])
    try:
        from ai.market_temporal_analysis import ANNEE_TRONQUEE
    except Exception:  # noqa: BLE001 — le module reste optionnel pour l'affichage
        ANNEE_TRONQUEE = None
    grp = (corpus["annee"].dropna().astype(int).value_counts()
           .sort_index().rename_axis("annee").reset_index(name="n"))
    grp["tronquee"] = grp["annee"] == ANNEE_TRONQUEE
    return grp


@st.cache_data(ttl=60)
def counts_by_sector() -> pd.DataFrame:
    corpus = load_corpus()
    if corpus.empty or "categorie_principale" not in corpus.columns:
        return pd.DataFrame(columns=["categorie", "n"])
    return (corpus["categorie_principale"].fillna("Non renseigné").value_counts()
            .rename_axis("categorie").reset_index(name="n"))


@st.cache_data(ttl=60)
def counts_by_procedure() -> pd.DataFrame:
    corpus = load_corpus()
    if corpus.empty or "mode_passation" not in corpus.columns:
        return pd.DataFrame(columns=["procedure", "n"])
    return (corpus["mode_passation"].fillna("Non renseigné").value_counts()
            .rename_axis("procedure").reset_index(name="n"))


@st.cache_data(ttl=60)
def counts_by_quality_level() -> pd.DataFrame:
    corpus = load_corpus()
    if corpus.empty or "data_quality_level" not in corpus.columns:
        return pd.DataFrame(columns=["niveau", "n"])
    return (corpus["data_quality_level"].dropna().value_counts()
            .rename_axis("niveau").reset_index(name="n"))


@st.cache_data(ttl=60)
def counts_by_priority() -> pd.DataFrame:
    markets = load_markets()
    if markets.empty or "priority_level" not in markets.columns:
        return pd.DataFrame(columns=["niveau", "n"])
    return (markets["priority_level"].dropna().value_counts()
            .rename_axis("niveau").reset_index(name="n"))


@st.cache_data(ttl=60)
def measured_risk_bands() -> dict | None:
    """Les bornes RÉELLES de l'échelle de risque, relues sur la
    distribution — mêmes règles qu'`ai/train_market_model.py` :

      Faible   : jusqu'à la frontière que le modèle choisit lui-même
                 (le score maximal parmi les marchés NON signalés)
      Modéré / Élevé / Critique : terciles mesurés du sous-groupe signalé

    Renvoie None si le corpus scoré est vide ou ne contient aucun marché
    signalé : dans ce cas la jauge affiche une échelle nue plutôt que des
    bandes inventées.
    """
    markets = load_markets()
    if markets.empty or "anomaly_score_0_100" not in markets.columns:
        return None
    scored = markets[markets["scorable"] == True]  # noqa: E712
    scored = scored[scored["anomaly_score_0_100"].notna()]
    if scored.empty:
        return None
    normaux = scored.loc[~scored["is_anomaly"].astype(bool), "anomaly_score_0_100"]
    anormaux = scored.loc[scored["is_anomaly"].astype(bool), "anomaly_score_0_100"]
    if normaux.empty or anormaux.empty:
        return None
    return {
        "faible_max": float(normaux.max()),
        "modere_max": float(anormaux.quantile(1 / 3)),
        "eleve_max": float(anormaux.quantile(2 / 3)),
        "min": float(scored["anomaly_score_0_100"].min()),
        "max": float(scored["anomaly_score_0_100"].max()),
        "n_scored": int(len(scored)),
    }


@st.cache_data(ttl=60)
def capped_awards() -> set:
    """Les marchés dont le niveau de priorité a été PLAFONNÉ par une
    confiance faible.

    Recalculé avec les fonctions réelles d'`ai/priority_score.py`
    (`measure_levels`, `assign_level`, `CAPPED_LEVEL`), jamais avec une
    règle réécrite ici : on compare le niveau obtenu avec la confiance
    réelle au niveau qu'aurait donné une confiance élevée. La différence
    est exactement l'effet du garde-fou.
    """
    if not PRIORITY_PATH.exists():
        return set()
    try:
        from ai.priority_score import CAPPED_LEVEL, assign_level, measure_levels
    except Exception:  # noqa: BLE001
        return set()
    prio = pd.read_parquet(PRIORITY_PATH)
    if "priority_raw" not in prio.columns:
        return set()
    seuils = measure_levels(prio["priority_raw"])
    sans_plafond = prio.apply(
        lambda r: assign_level(r["priority_raw"], "Elevee", seuils), axis=1)
    capped = ((sans_plafond.isin(["Tres prioritaire", "Prioritaire"]))
              & (prio["priority_level"] == CAPPED_LEVEL))
    return set(prio.loc[capped, "award_id"].astype(int))


@st.cache_data(ttl=60)
def fill_rates() -> dict:
    """Taux de remplissage réels, pour les panneaux d'information. Chaque
    entrée porte son effectif : un taux sans dénominateur ne se lit pas."""
    corpus = load_corpus()
    if corpus.empty:
        return {}
    n = len(corpus)
    attribues = corpus[corpus["statut"] == "ATTRIBUE"]

    def _rate(mask_true: int, total: int) -> dict:
        return {"n": int(mask_true), "total": int(total),
                "pct": (100.0 * mask_true / total) if total else None}

    ref_credible = corpus.apply(
        lambda r: r.get("reference") is not None
        and not pd.isna(r.get("reference"))
        and not ds.is_suspicious_reference(r.get("reference"), r),
        axis=1)
    out = {
        "montant_ttc": _rate(corpus["montant_ttc"].notna().sum(), n),
        "reference": _rate(int(ref_credible.sum()), n),
        "date_ouverture": _rate(corpus["date_ouverture_plis"].notna().sum(), n),
        "nb_soumissionnaires": _rate(corpus["nb_soumissionnaires"].notna().sum(), n),
    }
    if "has_winner" in attribues.columns and len(attribues):
        out["gagnant_attribues"] = _rate(
            attribues["has_winner"].fillna(0).astype(int).sum(), len(attribues))
    return out


@st.cache_data(ttl=60)
def filter_options() -> dict:
    """Options de filtre construites DEPUIS les valeurs réellement présentes
    dans le corpus chargé — jamais une liste écrite en dur. Si une modalité
    disparaît du corpus, elle disparaît du filtre."""
    corpus, markets = load_corpus(), load_markets()
    opts: dict[str, list] = {"annee": [], "procedure": [], "categorie": [],
                             "priorite": [], "qualite": []}
    if not corpus.empty:
        opts["annee"] = sorted(int(a) for a in corpus["annee"].dropna().unique())
        opts["procedure"] = sorted(corpus["mode_passation"].dropna().unique().tolist())
        opts["categorie"] = sorted(
            corpus["categorie_principale"].dropna().unique().tolist())
        if "data_quality_level" in corpus.columns:
            from dashboard.design_system import QUALITY_ORDER
            present = set(corpus["data_quality_level"].dropna().unique())
            opts["qualite"] = [q for q in QUALITY_ORDER if q in present]
    if not markets.empty and "priority_level" in markets.columns:
        from dashboard.design_system import PRIORITY_ORDER
        present = set(markets["priority_level"].dropna().unique())
        opts["priorite"] = [p for p in PRIORITY_ORDER if p in present]
    return opts


@st.cache_data(ttl=60)
def table_frame() -> pd.DataFrame:
    """Le corpus entier enrichi des colonnes de score, pour le tableau
    "Marchés publics".

    LEFT JOIN depuis le corpus, pas depuis les scores : les 140 marchés
    infructueux doivent rester visibles dans le catalogue même s'ils n'ont
    ni score ni priorité. Leurs colonnes de score restent NULL, et
    l'affichage les rend par "Non applicable", jamais par 0.
    """
    corpus = load_corpus()
    if corpus.empty:
        return corpus
    markets = load_markets()
    if markets.empty:
        return corpus
    keep = [c for c in ["award_id", "anomaly_score_0_100", "is_anomaly", "risk_level",
                        "scorable", "stability_frequency", "priority_score",
                        "priority_level", "confidence_level", "red_flag_count",
                        "red_flags_evaluable", "red_flag_score", "red_flags_triggered",
                        "RF01", "RF02", "RF03", "RF05", "RF06", "data_completeness"]
            if c in markets.columns]
    return corpus.merge(markets[keep], on="award_id", how="left")
