"""
Isolation Forest au grain MARCHE, entraine sur les RED FLAGS (refonte
"red flags only" — remplace la version du 28/08/2026 entrainee sur 11
features numeriques/one-hot).

CE QUI CHANGE, ET POURQUOI
--------------------------
Avant cette refonte, le modele lisait `log_montant_ttc`, `nb_soumissionnaires`,
`exclusion_rate`, et des one-hot procedure/secteur — des grandeurs
continues, dans lesquelles Isolation Forest peut genuinement trouver des
combinaisons rares. Decision (confirmee avec l'utilisateur) : le modele
s'entraine desormais sur les **3 red flags prioritaires** eux-memes —
RF01 (faible concurrence), RF02 (exclusions atypiques), RF03 (montant
atypique), calcules en amont par `ai/market_red_flags.py` — plutot que sur
les grandeurs brutes qui les ont produits.

CONSEQUENCE MECANIQUE, A NE PAS SE CACHER : avec 3 entrees booleennes, il
n'existe que 2^3 = 8 combinaisons possibles. Isolation Forest ne peut plus
trouver "un point rare dans un espace continu" — il ne peut plus que classer
ces 8 combinaisons par leur rarete respective dans le corpus. C'est un
signal reel mais etroit, donc son role est desormais precisement borne :

  * `priority_level` (le niveau : Faible / A surveiller / Prioritaire /
    Tres prioritaire) est decide UNIQUEMENT par le COMPTE de flags actifs
    parmi {RF01, RF02, RF03} — voir `ai/priority_score.py`. Le modele ne
    peut JAMAIS faire changer un marche de niveau.
  * `anomaly_score_0_100` (produit ici) ne sert plus qu'a DEPARTAGER des
    marches a EGALITE de compte de flags actifs — deux marches "2/3" sont
    ordonnes par la combinaison que le modele juge la plus rare, plutot que
    par un ordre arbitraire. Voir `ai/priority_score.py::priority_raw`
    (compte de flags x1000 + anomaly_score_0_100 : le compte domine
    toujours, l'anomalie ne fait que trier a l'interieur d'un meme compte).

POPULATION MODELISEE : LES MARCHES ATTRIBUES, AU MOINS 2/3 FLAGS EVALUABLES
----------------------------------------------------------------------------
Inchange dans son principe (voir `ai/market_population.py` pour la fonction
partagee) : seuls les marches ATTRIBUE entrent dans le modele — un marche
INFRUCTUEUX n'a par construction aucun attributaire, donc aucun des 3 red
flags prioritaires n'a de sens a lui appliquer une detection d'anomalie.
La porte `data_completeness >= MIN_DATA_COMPLETENESS` (2 des 3 informations
montant/concurrents/exclusions reellement extraites) reste la meme —
elle correspond exactement a "au moins 2 des 3 red flags prioritaires sont
evaluables", puisque ce sont les memes 3 dimensions. Un marche sous ce
seuil recoit `scorable = False` et aucun score, jamais un niveau invente.

IMPUTATION DES RED FLAGS NON EVALUABLES — 0, PAS UNE MEDIANE
----------------------------------------------------------------
Isolation Forest n'accepte pas de NaN/None. Contrairement aux grandeurs
continues de l'ancien modele (imputees a leur mediane), un red flag
booleen non evaluable est impute a 0 ("non declenche") — imputer a une
"mediane" n'aurait aucun sens sur un booleen — toujours accompagne de son
drapeau de disponibilite deja present dans market_features.parquet
(`has_competitor_data` pour RF01, `has_exclusion_data` pour RF02,
`has_amount_data` pour RF03), pour que le modele puisse au moins
distinguer "flag non declenche, lu" de "flag non declenche, invente".
Meme discipline que le reste du projet (jamais un 0 silencieux), appliquee
a un type booleen plutot qu'a une valeur continue.

    python -m ai.train_market_model
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
from sklearn.ensemble import IsolationForest  # noqa: E402

from ai.market_population import MIN_DATA_COMPLETENESS  # noqa: E402
from ai.market_red_flags import PRIORITY_FLAG_IDS  # noqa: E402

RED_FLAGS_PATH = REPO / "data/processed/analytics/market_red_flags.parquet"
MODEL_PATH = REPO / "ai/models/isolation_forest_market.joblib"
FEATURE_COLUMNS_PATH = REPO / "ai/models/market_feature_columns.json"
SCORES_PATH = REPO / "data/processed/analytics/market_anomaly_scores.parquet"
CONTAMINATION_REPORT_PATH = REPO / "data/processed/analytics/contamination_study.json"

RANDOM_STATE = 42

STABILITY_SEEDS = list(range(10))
STABILITY_TOP_N = 20

# Les 3 red flags prioritaires -> leur drapeau de disponibilite deja
# present dans market_features.parquet (repris tel quel dans
# market_red_flags.parquet). Une entree non evaluable (None) est imputee
# a 0, jamais a une mediane — voir la docstring du module.
IMPUTED_COLUMNS = dict(zip(PRIORITY_FLAG_IDS,
                          ("has_competitor_data", "has_exclusion_data", "has_amount_data")))

# Les drapeaux de disponibilite eux-memes : ce sont les 3 memes informations
# que data_completeness/scorable, donc jamais moins de 2 des 3 a 1 dans la
# population scoree — mais les 3 restent des colonnes du modele (elles
# peuvent varier individuellement meme quand leur somme est fixee au-dessus
# du seuil).
COMPLETE_COLUMNS = list(IMPUTED_COLUMNS.values())

MODEL_FEATURE_COLUMNS = list(IMPUTED_COLUMNS) + COMPLETE_COLUMNS


def prepare_market_matrix(pdf: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """market_red_flags.parquet -> matrice numerique sans NaN.

    Retourne aussi les valeurs d'imputation utilisees (toujours 0 pour un
    red flag, jamais une mediane), pour qu'elles soient ecrites dans le
    rapport plutot que de rester invisibles dans le code.
    """
    df = pdf.copy()
    imputed_values = {}
    for col in IMPUTED_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")  # True/False/None -> 1.0/0.0/NaN
        df[f"{col}_imputed"] = df[col].isna().astype(int)
        df[col] = df[col].fillna(0.0)
        imputed_values[col] = 0.0

    for col in COMPLETE_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    matrix = df[["award_id"] + MODEL_FEATURE_COLUMNS].copy()
    assert not matrix[MODEL_FEATURE_COLUMNS].isna().any().any(), (
        "NaN residuel apres imputation — diagnostiquer avant d'entrainer")
    return matrix, imputed_values


def drop_constant_features(matrix: pd.DataFrame) -> list[str]:
    """Ecarte les colonnes qui ne varient plus dans la population scoree.

    Avec seulement 6 colonnes booleennes, une colonne constante est
    plausible (ex. si tous les marches scores ont has_amount_data=1) — le
    controle reste necessaire pour la meme raison qu'avant : une colonne
    constante n'apporte rien a un modele qui tire ses features au hasard,
    et la correlation ne peut pas la detecter (NaN sur une constante).
    """
    dropped = []
    for col in matrix.columns:
        if col == "award_id":
            continue
        if matrix[col].nunique(dropna=False) <= 1:
            dropped.append(col)
            print(f"  colonne constante ({matrix[col].iloc[0]} partout, "
                  f"{len(matrix)} lignes) : {col!r} -> retiree du modele")
    return dropped


def drop_redundant_features(matrix: pd.DataFrame, threshold: float = 0.95) -> list[str]:
    """Ecarte une colonne d'une paire trop correlee.

    Meme raisonnement que l'ancien modele marche/entreprise : Isolation
    Forest tire un sous-ensemble de features au hasard a chaque coupe, donc
    un signal present en double a deux fois plus de chances d'etre choisi.
    Ici, un red flag et son propre drapeau de disponibilite pourraient
    corréler fortement si le flag est presque toujours evaluable ET presque
    toujours inactif quand il l'est — mesure, pas suppose.
    """
    corr = matrix[MODEL_FEATURE_COLUMNS].corr().abs()
    dropped = []
    for i, a in enumerate(MODEL_FEATURE_COLUMNS):
        for b in MODEL_FEATURE_COLUMNS[i + 1:]:
            if a in dropped or b in dropped:
                continue
            r = corr.loc[a, b]
            if r >= threshold:
                dropped.append(b)
                print(f"  redondance mesuree r={r:.3f} entre {a!r} et {b!r} "
                      f"-> {b!r} retiree du modele")
    return dropped


def study_contamination(X: np.ndarray, candidates=(0.05, 0.10, 0.15, "auto")) -> dict:
    """Compare plusieurs valeurs de `contamination` au lieu d'en retenir une
    a l'aveugle.

    Reste utile meme si `anomaly_score_0_100` ne pilote plus le niveau de
    priorite : `is_anomaly`/`risk_level` restent ecrits a titre diagnostic
    (voir docstring du module), et ce curseur decide combien de marches
    portent `is_anomaly=True`.
    """
    report = {}
    for c in candidates:
        model = IsolationForest(n_estimators=200, contamination=c,
                                random_state=RANDOM_STATE)
        labels = model.fit_predict(X)
        n = int((labels == -1).sum())
        report[str(c)] = {"n_flagged": n, "pct": round(100 * n / len(X), 1)}
        print(f"  contamination={str(c):<6} -> {n:3d} marches signales "
              f"({100 * n / len(X):.1f} %)")
    return report


def measure_stability(X: np.ndarray, award_ids: np.ndarray,
                      contamination) -> pd.DataFrame:
    """Reentraine le modele avec 10 graines et compte, pour chaque marche,
    dans combien de Top 20 il apparait.

    Avec seulement 8 combinaisons possibles de red flags, de nombreux
    marches partagent exactement le meme profil — attendre beaucoup plus
    d'ex aequo qu'avec l'ancien modele continu est le comportement mesure,
    pas une anomalie de cette fonction. Lire le rapport imprime avant de
    juger les bandes de confiance qui en decoulent (ai/priority_score.py).
    """
    tops = []
    for seed in STABILITY_SEEDS:
        model = IsolationForest(n_estimators=200, contamination=contamination,
                                random_state=seed)
        model.fit(X)
        scores = model.decision_function(X)
        order = np.argsort(scores)[:STABILITY_TOP_N]  # plus bas = plus anormal
        tops.append(set(award_ids[order]))

    counts = pd.Series(0, index=pd.Index(award_ids, name="award_id"), dtype=int)
    for top in tops:
        counts.loc[list(top)] += 1

    jaccards = [len(a & b) / len(a | b)
                for i, a in enumerate(tops) for b in tops[i + 1:]]
    print(f"  recouvrement moyen entre deux Top {STABILITY_TOP_N} "
          f"(Jaccard) : {np.mean(jaccards):.2f}")
    print(f"  marches apparaissant dans les 10/10 Top {STABILITY_TOP_N} : "
          f"{int((counts == 10).sum())}")
    print(f"  marches apparaissant dans 1 seul Top {STABILITY_TOP_N} : "
          f"{int((counts == 1).sum())}")
    return pd.DataFrame({"award_id": counts.index.to_numpy(),
                         "stability_frequency": counts.to_numpy()})


def main() -> int:
    pdf = pd.read_parquet(RED_FLAGS_PATH)
    total_attribue = len(pdf)

    print("=== population modelisee (marches ATTRIBUE, depuis market_red_flags.parquet) ===")
    print(f"  {total_attribue} marches attribues")
    print(pdf["scorable"].value_counts().rename({True: "scorable", False: "non scorable"})
          .to_string())

    print(f"\n=== features du modele : {MODEL_FEATURE_COLUMNS} ===")
    print(f"  RF01/RF02/RF03 (imputes a 0 si non evaluables) + leurs drapeaux "
          f"de disponibilite — voir docstring du module pour le role de ce "
          f"modele (depart en tie-break uniquement, jamais le niveau).")

    print("\n=== completude des donnees (marches attribues) ===")
    for k, g in pdf.groupby("data_completeness"):
        marque = "   -> NON SCORABLES" if k < MIN_DATA_COMPLETENESS else ""
        print(f"  {k} information(s) connue(s) sur 3 : {len(g):3d} marches{marque}")
    n_skipped = int((~pdf["scorable"]).sum())
    print(f"\n  {n_skipped}/{total_attribue} marches "
          f"({100 * n_skipped / total_attribue:.1f} %) ne sont PAS scores : "
          f"moins de {MIN_DATA_COMPLETENESS} informations extraites.")
    print("  Ils ne sont pas supprimes — ils ressortent avec scorable=False et")
    print("  aucun score, et s'affichent comme 'donnees insuffisantes'.")

    scored = pdf[pdf["scorable"]].reset_index(drop=True)
    matrix, imputed_values = prepare_market_matrix(scored)
    print("\n=== imputation (red flag non evaluable -> 0, jamais une mediane) ===")
    for col, value in imputed_values.items():
        n_imputed = int(matrix.shape[0] - scored[col].notna().sum())
        print(f"  {col:<8} impute a {value:.0f}  ({n_imputed} marches concernes)")

    print("\n=== colonnes constantes dans la population scoree ===")
    constantes = drop_constant_features(matrix[["award_id"] + MODEL_FEATURE_COLUMNS])
    if not constantes:
        print("  aucune — toutes les colonnes varient")

    print("\n=== redondance entre features (mesuree) ===")
    dropped = constantes + [c for c in drop_redundant_features(matrix)
                            if c not in constantes]
    features = [c for c in MODEL_FEATURE_COLUMNS if c not in dropped]
    if not dropped:
        print("  aucune paire au-dessus du seuil — toutes les colonnes conservees")
    print(f"  {len(features)} colonnes retenues : {features}")

    X = matrix[features].to_numpy(dtype=float)

    print("\n=== etude de contamination ===")
    print("  Sert desormais uniquement is_anomaly/risk_level (diagnostic) —")
    print("  priority_level ne lit plus ce curseur (voir ai/priority_score.py).")
    study = study_contamination(X)

    chosen = 0.10
    print(f"\n  RETENU : contamination={chosen} (coherent avec le choix historique)")

    model = IsolationForest(n_estimators=200, contamination=chosen,
                            random_state=RANDOM_STATE)
    model.fit(X)
    scores = model.decision_function(X)
    labels = model.predict(X)

    result = scored.copy()
    result["anomaly_score"] = scores
    result["is_anomaly"] = labels == -1
    # 0-100, plus haut = plus atypique. Rescale lineaire (pas un rang, qui
    # aplatirait la forme reelle de la distribution). Role UNIQUE
    # desormais : departager des marches a egalite de priority_flag_count
    # dans ai/priority_score.py — jamais decider un niveau seul.
    lo, hi = scores.min(), scores.max()
    result["anomaly_score_0_100"] = (
        100 * (hi - scores) / (hi - lo) if hi > lo else 50.0)
    for col in IMPUTED_COLUMNS:
        result[f"{col}_imputed"] = scored[col].isna().astype(int)

    unscorable = pdf[~pdf["scorable"]].copy()
    for col in ("anomaly_score", "anomaly_score_0_100", "stability_frequency"):
        unscorable[col] = None
    unscorable["is_anomaly"] = False
    unscorable["risk_level"] = "Non evaluable"

    # --- risk_level : DIAGNOSTIC uniquement desormais, jamais lu par
    # ai/priority_score.py (voir docstring du module). Conserve pour la
    # continuite du schema (dashboard/API) et pour comparer, a titre
    # d'interet technique, ce que le modele isole vs. le compte de flags.
    normal_max = float(result.loc[~result["is_anomaly"], "anomaly_score_0_100"].max())
    anormaux = result.loc[result["is_anomaly"], "anomaly_score_0_100"]

    def _level(score: float) -> str:
        if score <= normal_max:
            return "Faible"
        if anormaux.empty:
            return "Critique"
        t1, t2 = (float(x) for x in anormaux.quantile([1 / 3, 2 / 3]))
        if score <= t1:
            return "Modere"
        if score <= t2:
            return "Eleve"
        return "Critique"

    result["risk_level"] = result["anomaly_score_0_100"].apply(_level)
    print("\n=== risk_level (DIAGNOSTIC du modele, ne pilote plus priority_level) ===")
    print(result["risk_level"].value_counts().to_string())

    print("\n=== stabilite sur 10 graines aleatoires ===")
    stability = measure_stability(X, matrix["award_id"].to_numpy(), chosen)
    result = result.merge(stability, on="award_id", how="left")

    print(f"\n=== marches signales par le modele (diagnostic) : "
          f"{int(result['is_anomaly'].sum())}/{len(result)} ===")

    print("\n=== recoupement avec le compte de flags prioritaires ===")
    print("  Verifie plutot que suppose : le modele, entraine SUR ces flags,")
    print("  doit isoler en priorite les combinaisons les plus rares — pas")
    print("  forcement les comptes les plus eleves (8 combinaisons distinctes,")
    print("  pas 4 : 2/3 actifs peut regrouper deux combinaisons de rarete")
    print("  differente, c'est exactement ce que le score sert a departager).")
    for n, g in result.groupby("priority_flag_count"):
        print(f"  {int(n)}/3 actif(s) : {len(g):3d} marches, score d'anomalie "
              f"moyen {g['anomaly_score_0_100'].mean():5.1f}")

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    FEATURE_COLUMNS_PATH.write_text(json.dumps(features, indent=2), encoding="utf-8")
    CONTAMINATION_REPORT_PATH.write_text(json.dumps(
        {"candidates": study, "chosen": chosen, "n_scored": len(result),
         "imputed_values": imputed_values,
         "dropped_for_redundancy": dropped}, indent=2), encoding="utf-8")

    final = pd.concat([result, unscorable], ignore_index=True)
    final.to_parquet(SCORES_PATH, index=False)
    print(f"\nSortie : {len(result)} marches scores + {len(unscorable)} non "
          f"scorables = {len(final)} lignes")
    print(f"\nEcrit : {MODEL_PATH}")
    print(f"Ecrit : {SCORES_PATH}")
    print(f"Ecrit : {CONTAMINATION_REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
