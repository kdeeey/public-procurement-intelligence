"""
Issue 11 — score de risque composite, poids ÉGAUX (pas les poids Fazekas :
corpus trop petit pour les ré-estimer, voir docs/ideas.md Sec "Score de
risque composite" — décision déjà actée, réutilisée ici, pas retranchée).

3 red flags actifs, chacun mesuré sur la distribution réelle des 200
Company, pas des seuils devinés :

  1. single_bidder_rate >= 0.5   (bimodal : 103 a 0.0, 91 a 1.0, 6 a 0.5 —
     le seuil 0.5 capture aussi les entreprises a 2 awards dont la moitie
     etait a soumissionnaire unique)
  2. market_share_global_ttc >= 0.010952   (quartile superieur mesure
     parmi les 96/200 Company AVEC donnee TTC — voir has_ttc_data)
  3. concurrents_ecartes_rate >= 0.5   (meme bimodalite que #1 : 105 a
     0.0, 92 a 1.0, 3 a 0.5)

Un 4e red flag ("tendance croissante du taux de soumissionnaire unique")
a ete retire — confirme avec l'utilisateur apres mesure : 0/200 Company
ont assez de points annuels (2023-2025) pour une pente de regression
(voir bigdata/spark/jobs/build_features.py et bigdata/README.md pour le
detail mesure). Les colonnes de pente restent dans company_features pour
quand le corpus grossira, mais n'entrent pas dans le score.

Le red flag #2 (concentration) n'est evaluable que pour les 96/200
Company avec has_ttc_data — PAS traite comme "non declenche" par defaut
(ce qui plafonnerait mecaniquement le score des 104 Company sans donnee
TTC, un biais, pas un vrai signal de risque plus faible). Le score est
plutot RESCALE sur le nombre de red flags reellement evaluables pour
cette entreprise (2 au lieu de 3 quand has_ttc_data est faux), avec un
flag explicite `partially_evaluated` — meme traitement que le montant
manquant (build_features.py : flag explicite, jamais une valeur
silencieuse). Decision confirmee avec l'utilisateur avant implementation.

    python -m ai.scoring
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

COMPANY_FEATURES_PATH = REPO / "data/processed/analytics/company_features.parquet"
ANOMALY_SCORES_PATH = REPO / "data/processed/analytics/company_anomaly_scores.parquet"
RISK_SCORES_PATH = REPO / "data/processed/analytics/company_risk_scores.parquet"

SINGLE_BIDDER_THRESHOLD = 0.5
CONCENTRATION_THRESHOLD = 0.010952
CONCURRENTS_ECARTES_THRESHOLD = 0.5

RED_FLAG_LABELS = {
    "single_bidder": "taux de soumissionnaire unique eleve (>=50% de ses marches)",
    "concentration": "concentration elevee chez ses acheteurs (top quartile mesure)",
    "concurrents_ecartes": "taux d'exclusion de concurrents eleve (>=50% de ses marches)",
}


def compute_composite_score(row: pd.Series) -> dict:
    """Une ligne de company_features -> {risk_score, n_evaluable, n_active,
    active_flags, partially_evaluated}. Poids egaux : chaque red flag actif
    contribue 100 / n_evaluable_pour_cette_entreprise points, jamais 100/3
    fixe — sinon une entreprise sans donnee TTC serait mecaniquement
    plafonnee a 66/100 meme si ses 2 flags evaluables sont tous les deux
    actifs."""
    evaluable = ["single_bidder", "concurrents_ecartes"]
    active = []

    if row["single_bidder_rate"] >= SINGLE_BIDDER_THRESHOLD:
        active.append("single_bidder")
    if row["concurrents_ecartes_rate"] >= CONCURRENTS_ECARTES_THRESHOLD:
        active.append("concurrents_ecartes")

    if row["has_ttc_data"]:
        evaluable.append("concentration")
        if row["market_share_global_ttc"] >= CONCENTRATION_THRESHOLD:
            active.append("concentration")

    n_evaluable = len(evaluable)
    n_active = len(active)
    risk_score = round(100 * n_active / n_evaluable, 1) if n_evaluable else 0.0

    return {
        "risk_score": risk_score,
        "n_evaluable_flags": n_evaluable,
        "n_active_flags": n_active,
        "active_flags": ", ".join(RED_FLAG_LABELS[f] for f in active) if active else "aucun",
        "partially_evaluated": not row["has_ttc_data"],
    }


def main() -> int:
    features_pdf = pd.read_parquet(COMPANY_FEATURES_PATH)
    features_pdf["market_share_global_ttc"] = pd.to_numeric(
        features_pdf["market_share_global_ttc"], errors="coerce")
    n_companies = len(features_pdf)
    print(f"Company chargees : {n_companies} (attendu 200)")
    if n_companies != 200:
        raise RuntimeError("recoupement echoue — diagnostiquer avant de continuer")

    scores = features_pdf.apply(compute_composite_score, axis=1, result_type="expand")
    result = pd.concat([features_pdf[["company_id", "company_normalized_name"]], scores], axis=1)

    n_partial = int(result["partially_evaluated"].sum())
    print(f"Company evaluees partiellement (2/3 red flags, pas de donnee TTC) : "
          f"{n_partial}/{n_companies}")
    print(f"Company evaluees completement (3/3 red flags)                    : "
          f"{n_companies - n_partial}/{n_companies}")

    print("\n=== exemple concret : TECTRA, COSTACOM ===")
    example = result[result["company_normalized_name"].isin(["TECTRA", "COSTACOM"])]
    print(example.to_string(index=False))

    print("\n=== top 10 par risk_score ===")
    top = result.sort_values("risk_score", ascending=False).head(10)
    print(top[["company_normalized_name", "risk_score", "n_active_flags",
              "n_evaluable_flags", "partially_evaluated"]].to_string(index=False))

    dist = result["risk_score"].value_counts().sort_index()
    print("\nDistribution des risk_score :")
    print(dist.to_string())
    print("\n  Rappel : ~20% de bruit residuel dans Company malgre le filtre de"
          " plausibilite (database/README.md) — un score eleve sur un nom de"
          " bruit (fragment de phrase, pas une entreprise) n'est pas un vrai"
          " signal de risque, verifier le nom avant toute interpretation.")

    RISK_SCORES_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(RISK_SCORES_PATH, index=False)
    print(f"\nEcrit : {RISK_SCORES_PATH}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
