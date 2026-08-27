"""
Issue 12 — score de risque final 0-100, explicable, par entreprise.

Articulation entre les deux scores existants (confirmée avec l'utilisateur
avant implémentation) :

  - Isolation Forest (ai/train_isolation_forest.py) est le SIGNAL PRINCIPAL
    — il capture des combinaisons de features inhabituelles qui ne
    correspondent à aucun red flag nommé individuellement, ce qu'un score
    composite à liste fixe de red flags ne peut structurellement jamais
    faire.
  - Le score composite (ai/scoring.py, 3 red flags nommés) devient la
    COUCHE D'EXPLICATION — son `active_flags` fournit le texte qui
    justifie le score, jamais une seconde contribution numérique fusionnée
    arithmétiquement avec le score Isolation Forest (un score combiné par
    pondération serait plus opaque que chacun pris séparément, contraire à
    l'objectif "score explicable" de cette Issue).

`final_score` : `anomaly_score` (sortie brute d'Isolation Forest, plus bas
= plus anormal) rescalé LINÉAIREMENT en 0-100 (jamais un rang/percentile,
qui aplatirait artificiellement la vraie forme mesurée de la distribution
— 165/200 entreprises très regroupées près du minimum de risque, une
queue longue jusqu'au maximum).

Seuils Faible/Modéré/Élevé/Critique — mesurés sur les 200 Company, pas
25/50/75 arbitraires :
  - Faible   : `final_score` sous la frontière que le modèle a lui-même
    choisie (`is_anomaly == False`, 165/200) — mesuré, pas devine.
  - Le reste (35/200, `is_anomaly == True`) est coupé en 3 TERCILES
    mesurés de son propre `final_score` : Modéré / Élevé / Critique.

Principe absolu, répété depuis le début du projet : ce score ne répond
JAMAIS à "ce marché/cette entreprise est-il frauduleux ?" mais à "cette
entreprise présente-t-elle des caractéristiques statistiquement associées
à un risque de corruption dans la littérature ?" — un signal pour
prioriser l'analyse humaine, jamais une accusation automatisée
(docs/ideas.md Sec 2.6, "Principe directeur"). Chaque explication
textuelle générée par ce module respecte cette formulation.

    python -m ai.risk_score
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from database.crud.counts import check_against_database, company_count  # noqa: E402

from ai.scoring import RISK_SCORES_PATH  # noqa: E402
from ai.train_isolation_forest import (  # noqa: E402
    COMPANY_FEATURES_PATH as _COMPANY_FEATURES_PATH, MODEL_FEATURE_COLUMNS, MODEL_PATH,
    _load_features, prepare_model_matrix,
)

ANOMALY_SCORES_PATH = REPO / "data/processed/analytics/company_anomaly_scores.parquet"
FINAL_RISK_PATH = REPO / "data/processed/analytics/company_final_risk.parquet"

LEVEL_ORDER = ["Faible", "Modere", "Eleve", "Critique"]

# Mis a jour apres le correctif de redondance (ai/train_isolation_forest.py) :
# average_amount_ttc et market_share_global_ttc ne sont PLUS des colonnes
# du modele (r=0.996 et r=1.000 avec total_amount_ttc, mesure — retirees,
# gardees seulement pour le reporting). Le "cluster montant" ici ne
# contient donc plus que les 2 colonnes montant reellement presentes dans
# MODEL_FEATURE_COLUMNS. Voir _compute_dominant_driver().
AMOUNT_CLUSTER = ["total_amount_ttc", "has_ttc_data"]
BEHAVIOR_CLUSTER = [c for c in MODEL_FEATURE_COLUMNS if c not in AMOUNT_CLUSTER]
# En dessous de ce delta, l'effet comportemental mesure est traite comme
# nul plutot que comme un signal faible — mesure sur COSTACOM (#1
# anomalie) : delta EXACTEMENT 0.0000 quand isole par le montant seul,
# donc ce seuil n'a besoin d'etre qu'au-dessus du bruit numerique, pas
# ajuste finement.
BEHAVIOR_DELTA_NEGLIGIBLE = 0.005


def _rescale_to_0_100(anomaly_score: pd.Series) -> pd.Series:
    """Plus bas anomaly_score = plus anormal -> plus haut final_score.
    Rescale lineaire min-max (PAS un rang/percentile, qui aplatirait
    artificiellement la vraie forme mesuree de la distribution — voir
    docstring du module)."""
    lo, hi = anomaly_score.min(), anomaly_score.max()
    return 100 * (hi - anomaly_score) / (hi - lo)


def _measure_thresholds(anomaly_pdf: pd.DataFrame) -> dict:
    """Faible = frontiere choisie par le modele lui-meme (is_anomaly),
    Modere/Eleve/Critique = terciles mesures du sous-groupe anormal —
    jamais 25/50/75 devines. Retourne les 3 bornes superieures
    (faible_max, modere_max, eleve_max), Critique = tout au-dessus."""
    normal_max = anomaly_pdf.loc[~anomaly_pdf["is_anomaly"], "final_score"].max()
    anomalous = anomaly_pdf.loc[anomaly_pdf["is_anomaly"], "final_score"]
    t1, t2 = anomalous.quantile([1 / 3, 2 / 3])
    return {"faible_max": float(normal_max), "modere_max": float(t1), "eleve_max": float(t2)}


def _classify(final_score: float, thresholds: dict) -> str:
    if final_score <= thresholds["faible_max"]:
        return "Faible"
    if final_score <= thresholds["modere_max"]:
        return "Modere"
    if final_score <= thresholds["eleve_max"]:
        return "Eleve"
    return "Critique"


def _compute_dominant_driver() -> pd.DataFrame:
    """Group-ablation (neutraliser le cluster comportemental a la mediane
    de population, remesurer decision_function) pour distinguer un signal
    "surtout montant" d'un signal ou le comportement contribue vraiment.

    Trouve en verifiant, pas en supposant : une premiere version de ce
    module presentait COSTACOM (#1 anomalie) comme une "combinaison
    montant eleve + single_bidder_rate bas" — mesure ensuite par cette
    meme ablation que neutraliser TOUT le cluster comportemental
    (single_bidder_rate, groupement_rate, concurrents_ecartes_rate,
    pentes de tendance) ne change RIEN a son score (delta = 0.0000
    exactement) : son isolement est explique a 100% par le montant. INNOVATIVE BUILDING SOLUTIONS
    INNOVATIVE BUILDING SOLUTIONS, en comparaison, montre un delta reel
    (+0.018) — un vrai effet comportemental, meme modeste. Voir
    bigdata/README.md pour le detail complet de cette verification."""
    model = joblib.load(MODEL_PATH)
    features_pdf = _load_features()
    matrix = prepare_model_matrix(features_pdf)
    X = matrix[MODEL_FEATURE_COLUMNS].to_numpy()
    medians = np.median(X, axis=0)
    behavior_idx = [MODEL_FEATURE_COLUMNS.index(c) for c in BEHAVIOR_CLUSTER]

    baseline = model.decision_function(X)
    X_no_behavior = X.copy()
    X_no_behavior[:, behavior_idx] = medians[behavior_idx]
    score_no_behavior = model.decision_function(X_no_behavior)
    behavior_delta = score_no_behavior - baseline

    dominant_driver = np.where(
        behavior_delta > BEHAVIOR_DELTA_NEGLIGIBLE, "comportement_et_montant", "surtout_montant")
    return pd.DataFrame({
        "company_id": matrix["company_id"].to_numpy(),
        "behavior_delta": behavior_delta,
        "dominant_driver": dominant_driver,
    })


def build_explanation(row: pd.Series) -> str:
    """Texte en langage clair listant les facteurs contributifs — reutilise
    active_flags du score composite (ai/scoring.py), jamais une formulation
    d'accusation (voir docstring du module)."""
    name = row["company_normalized_name"]
    level = row["risk_level"]

    if row["n_active_flags"] == 0:
        base = f"{name} : aucun red flag actif parmi ceux mesures — signal Isolation Forest {level.lower()}."
    else:
        base = (f"{name} : signal {level.lower()} justifiant une analyse — "
                f"facteurs contributifs mesures : {row['active_flags']}.")

    if row["partially_evaluated"]:
        base += (" ATTENTION : evaluation partielle (2 red flags sur 3, "
                 "aucun montant TTC extrait pour cette entreprise — la "
                 "concentration chez ses acheteurs n'a pas pu etre mesuree, "
                 "voir has_ttc_data).")

    if row["risk_level"] in ("Eleve", "Critique") and row.get("dominant_driver") == "surtout_montant":
        base += (" NUANCE (verifiee par ablation, pas devinee) : ce signal est"
                 " porte presque exclusivement par la taille du contrat"
                 " (montant/concentration) — neutraliser tous les indicateurs"
                 " de comportement (soumissionnaire unique, exclusion de"
                 " concurrents, groupement) ne change pas le score. Pas un"
                 " exemple de comportement suspect combine, juste un contrat"
                 " statistiquement tres au-dessus des autres.")

    base += " Ceci est un signal statistique, PAS une preuve de fraude."
    return base


def main() -> int:
    anomaly_pdf = pd.read_parquet(ANOMALY_SCORES_PATH)
    composite_pdf = pd.read_parquet(RISK_SCORES_PATH)

    n_companies = len(anomaly_pdf)
    check_against_database(n_companies, company_count(), "Company chargees")
    if len(composite_pdf) != n_companies:
        raise RuntimeError(
            f"recoupement echoue : {len(composite_pdf)} lignes dans "
            f"company_risk_scores.parquet contre {n_companies} dans "
            f"company_anomaly_scores.parquet — rejouer ai/scoring.py")

    anomaly_pdf["final_score"] = _rescale_to_0_100(anomaly_pdf["anomaly_score"])
    thresholds = _measure_thresholds(anomaly_pdf)
    print("\nSeuils mesures (pas arbitraires) :")
    print(f"  Faible   : final_score <= {thresholds['faible_max']:.1f}")
    print(f"  Modere   : {thresholds['faible_max']:.1f} < final_score <= {thresholds['modere_max']:.1f}")
    print(f"  Eleve    : {thresholds['modere_max']:.1f} < final_score <= {thresholds['eleve_max']:.1f}")
    print(f"  Critique : final_score > {thresholds['eleve_max']:.1f}")

    anomaly_pdf["risk_level"] = anomaly_pdf["final_score"].apply(_classify, thresholds=thresholds)

    driver_pdf = _compute_dominant_driver()
    n_amount_only = (driver_pdf["dominant_driver"] == "surtout_montant").sum()
    print(f"\nCompany dont l'isolement est explique surtout par le montant"
          f" (ablation, pas suppose) : {n_amount_only}/{n_companies}")

    result = anomaly_pdf.merge(
        composite_pdf[["company_id", "n_active_flags", "n_evaluable_flags",
                       "active_flags", "partially_evaluated"]],
        on="company_id", how="left")
    result = result.merge(driver_pdf, on="company_id", how="left")
    result["explanation"] = result.apply(build_explanation, axis=1)

    dist = result["risk_level"].value_counts().reindex(LEVEL_ORDER, fill_value=0)
    print("\nDistribution des niveaux de risque :")
    print(dist.to_string())

    print("\n=== exemples concrets : TECTRA, COSTACOM, EL6 (2e plus anormale) ===")
    examples = result[result["company_normalized_name"].isin(
        ["TECTRA", "COSTACOM", "INNOVATIVE BUILDING SOLUTIONS"])]
    for _, row in examples.sort_values("final_score", ascending=False).iterrows():
        print(f"\n{row['company_normalized_name']} — final_score={row['final_score']:.1f}"
              f" ({row['risk_level']})")
        print(f"  {row['explanation']}")

    print("\n  Rappel : 8,8% de bruit pur + 7,4% de noms contamines dans Company"
          " (audit du 27/08/2026, bigdata/README.md) — un score/niveau eleve sur"
          " un nom de bruit n'est pas un vrai signal de risque, verifier le nom"
          " avant toute interpretation.")

    FINAL_RISK_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(FINAL_RISK_PATH, index=False)
    print(f"\nEcrit : {FINAL_RISK_PATH}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
