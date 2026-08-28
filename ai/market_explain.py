"""
Explicabilite du modele marche — SHAP + controle par ablation (28/08/2026).

DEUX METHODES, DELIBEREMENT
----------------------------
SHAP est l'explication principale ; l'ablation sert de CONTROLE DE
COHERENCE. Ce n'est pas de la redondance decorative : les deux repondent a
la meme question par des chemins independants, donc un desaccord entre
elles est une information exploitable en soutenance.

  * SHAP (TreeExplainer) attribue a chaque feature une part du score, en
    moyennant sa contribution marginale sur les ordres d'inclusion
    possibles. Il lit la STRUCTURE INTERNE des arbres.
  * L'ablation (deja utilisee dans ai/risk_score.py::_compute_dominant_driver
    pour le modele entreprise, reprise ici) neutralise une feature en la
    ramenant a la mediane de population et remesure `decision_function`.
    Elle ne regarde pas dans le modele, seulement ce qu'il repond.

Quand les deux classements se rejoignent, l'explication est solide. Quand
ils divergent, le marche merite d'etre lu avant d'etre commente — et le
dashboard le signale.

CE QUE SHAP EXPLIQUE, ET CE QU'IL N'EXPLIQUE PAS
--------------------------------------------------
A dire tel quel en soutenance, sans arrondir :

  * Sur un Isolation Forest, SHAP explique la PROFONDEUR D'ISOLEMENT — a
    quel point chaque feature contribue a ce que ce point soit separe
    rapidement du reste. Ce n'est PAS une probabilite, encore moins une
    probabilite de fraude.
  * SHAP explique le MODELE, pas le monde. Il dit "le score vient surtout
    du montant", jamais "le montant est anormal parce que le marche est
    irregulier". Une feature mal extraite produira une explication SHAP
    parfaitement coherente d'un score parfaitement faux.
  * Les contributions portent sur des valeurs parfois IMPUTEES. Une
    explication qui repose sur une valeur imputee est signalee comme telle
    (`repose_sur_impute`), sinon elle donnerait a une mediane substituee
    l'apparence d'une observation.

    python -m ai.market_explain
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ai.train_market_model import (  # noqa: E402
    FEATURE_COLUMNS_PATH, IMPUTED_COLUMNS, MIN_DATA_COMPLETENESS, MODEL_PATH,
    SCORES_PATH, prepare_market_matrix,
)

MARKET_FEATURES_PATH = REPO / "data/processed/analytics/market_features.parquet"
EXPLANATIONS_PATH = REPO / "data/processed/analytics/market_explanations.parquet"
AGREEMENT_PATH = REPO / "data/processed/analytics/explanation_agreement.json"

TOP_K = 3

# Libelles lisibles par un analyste — le dashboard n'affiche jamais un nom
# de colonne brut.
FEATURE_LABELS = {
    "log_montant_ttc": "montant du marche",
    "nb_soumissionnaires": "nombre de soumissionnaires",
    "nb_concurrents_ecartes": "nombre de concurrents ecartes",
    "exclusion_rate": "part de concurrents ecartes",
    "has_amount_data": "disponibilite du montant",
    "has_competitor_data": "disponibilite de la liste des concurrents",
    "has_exclusion_data": "disponibilite de la liste des ecartes",
    "mode_ao_ouvert": "procedure : appel d'offres ouvert",
    "mode_ao_simplifie": "procedure : appel d'offres simplifie",
    "mode_autre": "procedure : autre",
    "cat_travaux": "secteur : travaux",
    "cat_fournitures": "secteur : fournitures",
    "cat_services": "secteur : services",
}


def compute_shap(model, X: np.ndarray, features: list[str]) -> np.ndarray:
    """Valeurs SHAP par (marche, feature).

    TreeExplainer accepte IsolationForest : il parcourt les arbres
    d'isolement comme n'importe quel ensemble d'arbres. La valeur expliquee
    est la sortie brute du modele (plus basse = plus isolee), donc une
    contribution NEGATIVE pousse vers l'anomalie. On renvoie l'oppose pour
    que, partout ailleurs dans le projet, "plus haut = plus atypique" reste
    vrai sans avoir a se souvenir d'une inversion de signe.
    """
    import shap
    explainer = shap.TreeExplainer(model)
    values = explainer.shap_values(X, check_additivity=False)
    return -np.asarray(values)


def compute_ablation(model, X: np.ndarray) -> np.ndarray:
    """Controle independant : effet de la neutralisation de chaque feature.

    Pour chaque colonne, on remplace sa valeur par la mediane de population
    et on remesure `decision_function`. Un delta positif signifie que la
    valeur reelle rendait le marche PLUS isole que la mediane — donc
    qu'elle contribue a l'atypisme.

    Methode volontairement identique a celle deja employee pour le modele
    entreprise, pour que les deux etages du projet se comparent.
    """
    baseline = model.decision_function(X)
    medians = np.median(X, axis=0)
    deltas = np.zeros_like(X, dtype=float)
    for j in range(X.shape[1]):
        X_ablated = X.copy()
        X_ablated[:, j] = medians[j]
        deltas[:, j] = model.decision_function(X_ablated) - baseline
    return deltas


def top_features(row_values: np.ndarray, features: list[str], k: int = TOP_K):
    order = np.argsort(-row_values)[:k]
    return [(features[j], float(row_values[j])) for j in order]


def build_sentence(tops, imputed_cols: set[str]) -> str:
    parts = []
    for name, value in tops:
        label = FEATURE_LABELS.get(name, name)
        if name in imputed_cols:
            label += " (valeur imputee, non lue dans le document)"
        parts.append(label)
    return ("Facteurs qui contribuent le plus au score de ce marche, par ordre "
            "de contribution : " + " ; ".join(parts) + ". "
            "Ces facteurs expliquent la SORTIE DU MODELE, pas une irregularite : "
            "ils indiquent en quoi ce marche se distingue des autres du corpus.")


def main() -> int:
    model = joblib.load(MODEL_PATH)
    features = json.loads(FEATURE_COLUMNS_PATH.read_text(encoding="utf-8"))

    scores = pd.read_parquet(SCORES_PATH)
    scored = scores[scores["scorable"] == True].reset_index(drop=True)  # noqa: E712
    matrix, _ = prepare_market_matrix(scored)
    X = matrix[features].to_numpy(dtype=float)
    print(f"{len(scored)} marches scorables, {len(features)} features")

    print("\n=== SHAP (TreeExplainer) ===")
    shap_values = compute_shap(model, X, features)
    print(f"  matrice de contributions : {shap_values.shape}")
    mean_abs = np.abs(shap_values).mean(axis=0)
    ordre = np.argsort(-mean_abs)
    print("  importance moyenne (|SHAP| moyen) :")
    for j in ordre:
        print(f"    {features[j]:<26}{mean_abs[j]:8.5f}")

    print("\n=== controle par ablation ===")
    ablation = compute_ablation(model, X)
    mean_abl = np.abs(ablation).mean(axis=0)
    ordre_abl = np.argsort(-mean_abl)
    print("  importance moyenne (|delta| moyen) :")
    for j in ordre_abl:
        print(f"    {features[j]:<26}{mean_abl[j]:8.5f}")

    # --- accord entre les deux methodes ---------------------------------- #
    rows = []
    accords = 0
    for i in range(len(scored)):
        imputed = {c for c in IMPUTED_COLUMNS
                   if pd.isna(scored.loc[i, c])}
        tops_shap = top_features(shap_values[i], features)
        tops_abl = top_features(ablation[i], features)
        set_shap = {n for n, _ in tops_shap}
        set_abl = {n for n, _ in tops_abl}
        recouvrement = len(set_shap & set_abl) / TOP_K
        accords += recouvrement == 1.0
        rows.append({
            "award_id": int(scored.loc[i, "award_id"]),
            "shap_top_features": json.dumps([n for n, _ in tops_shap]),
            "shap_top_values": json.dumps([round(v, 5) for _, v in tops_shap]),
            "ablation_top_features": json.dumps([n for n, _ in tops_abl]),
            "accord_shap_ablation": round(recouvrement, 2),
            "repose_sur_impute": bool(set_shap & imputed),
            "explication_modele": build_sentence(tops_shap, imputed),
        })

    result = pd.DataFrame(rows)
    moyen = result["accord_shap_ablation"].mean()
    print(f"\n=== accord SHAP / ablation sur le Top {TOP_K} ===")
    print(f"  recouvrement moyen : {moyen:.2f}")
    print(f"  marches ou les deux methodes donnent le MEME Top {TOP_K} : "
          f"{accords}/{len(result)}")
    print(f"  marches dont l'explication repose sur au moins une valeur "
          f"imputee : {int(result['repose_sur_impute'].sum())}/{len(result)}")
    print("\n  Un desaccord n'invalide ni l'une ni l'autre : SHAP lit la")
    print("  structure des arbres, l'ablation ne regarde que la reponse du")
    print("  modele. Le dashboard signale les marches ou elles divergent.")

    EXPLANATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(EXPLANATIONS_PATH, index=False)
    AGREEMENT_PATH.write_text(json.dumps({
        "accord_moyen_top3": round(float(moyen), 3),
        "n_accord_parfait": int(accords),
        "n_marches": len(result),
        "importance_shap": {features[j]: round(float(mean_abs[j]), 5) for j in ordre},
        "importance_ablation": {features[j]: round(float(mean_abl[j]), 5) for j in ordre_abl},
        "min_data_completeness": MIN_DATA_COMPLETENESS,
    }, indent=2), encoding="utf-8")
    print(f"\nEcrit : {EXPLANATIONS_PATH}")
    print(f"Ecrit : {AGREEMENT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
