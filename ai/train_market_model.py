"""
Isolation Forest au grain MARCHE (refonte du 28/08/2026).

Remplace ai/train_isolation_forest.py comme modele principal. La
justification complete de la bascule est dans
bigdata/spark/jobs/build_market_features.py ; en une phrase : 93,3 % des
entreprises n'ont qu'un seul marche, donc les "taux" par entreprise etaient
des observations uniques deguisees en frequences, et le modele apprenait la
profondeur de presence dans le corpus (100 % des entreprises a 2 marches
signalees anormales contre 13,9 % de celles a 1 marche).

POPULATION MODELISEE : LES MARCHES ATTRIBUES
--------------------------------------------
Sur 454 marches, 314 sont ATTRIBUE et 140 INFRUCTUEUX. Seuls les premiers
entrent dans le modele. Ce n'est pas un filtrage de confort, et la
justification a ete MESUREE plutot qu'affirmee :

    ATTRIBUE     314 marches — gagnant 205 (65,3 %), montant 142 (45,2 %)
    INFRUCTUEUX  140 marches — gagnant   0 ( 0,0 %), montant  25 (17,9 %)

Un marche infructueux n'a AUCUN attributaire — 0/140, sans exception. Il
n'y a donc rien a comparer : les red flags de ce projet portent tous sur une
attribution (qui a gagne, a quel montant, avec combien de concurrents
ecartes). Melanger les deux populations apprendrait surtout au modele a
separer les deux statuts, une tautologie, pas un signal de risque.

Nuance a ne pas gommer : 25 marches infructueux (17,9 %) portent quand meme
un montant. Ce n'est donc pas "aucune donnee par construction" — c'est
l'ABSENCE D'ATTRIBUTAIRE qui est structurelle et qui fonde l'exclusion, pas
l'absence de montant.

Les 140 marches infructueux ne sont pas perdus : ils restent dans
market_features.parquet, comptes et affichables, simplement non scores.
Le rapport le dit explicitement plutot que de laisser croire que le corpus
fait 314 marches.

MARCHES NON SCORABLES — LE PIEGE TROUVE EN VERIFIANT, PAS EN RELISANT
---------------------------------------------------------------------
Premiere version de ce modele, Top 10 inspecte : les marches les plus
"atypiques" etaient ceux dont on ne savait RIEN. Mesure faite aussitot,
sur les 314 marches attribues, selon le nombre d'informations reellement
extraites parmi montant / concurrents / exclusions :

    0 information connue :   7 marches ->  7 signales (100,0 %)
    1 information connue :  28 marches ->  9 signales ( 32,1 %)
    2 informations       : 151 marches ->  8 signales (  5,3 %)
    3 informations       : 128 marches ->  8 signales (  6,3 %)

Le modele detectait donc le TROU D'EXTRACTION, pas le marche atypique —
exactement la meme classe d'artefact que la profondeur de corpus au niveau
entreprise, que cette refonte etait censee supprimer. Un marche dont tout
est impute ressemble forcement a peu d'autres : c'est l'imputation qui le
rend rare, pas son contenu.

REGLE RETENUE : un marche n'est score que si AU MOINS 2 des 3 informations
sont reellement presentes (`data_completeness >= 2`). Les autres recoivent
`scorable = False` et AUCUN score — comptes et affiches comme "donnees
insuffisantes pour analyser", jamais comme "atypiques".

Le seuil vient de la mesure ci-dessus, il n'est pas choisi a priori : les
deux groupes >= 2 ont des taux de signalement quasi identiques (5,3 % et
6,3 %), les deux groupes < 2 sont a 32 % et 100 %. La rupture est entre 1
et 2, pas ailleurs.

Ce que ca coute, dit franchement : 35 marches sur 314 (11,1 %) sortent de
l'analyse. Les signaler aurait ete pire — c'est presenter un defaut de
notre propre chaine d'extraction comme une anomalie de marche public.

IMPUTATION — EXPLICITE, SIGNALEE, JAMAIS UN ZERO
-------------------------------------------------
Isolation Forest n'accepte pas de NaN. Chaque colonne a valeurs manquantes
est donc imputee A LA MEDIANE des marches qui ont la donnee, jamais a 0 (un
0 se lit comme une valeur extreme basse, pas comme un inconnu), et toujours
accompagnee de son drapeau `has_*_data` qui reste, lui, une vraie
observation. Le modele peut ainsi apprendre que "impute" n'est pas en soi
un signal.

`single_bidder` n'est PAS une entree du modele : il est entierement
derivable de `nb_soumissionnaires`, donc redondant, et l'imputer forcerait
a choisir 0 ou 1 pour un marche dont on ignore le nombre de
soumissionnaires — exactement la confusion UNKNOWN/ZERO que cette refonte
supprime. Il reste calcule pour le red flag RF01, qui, lui, ne se declenche
que lorsque `has_competitor_data = 1`.

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

MARKET_FEATURES_PATH = REPO / "data/processed/analytics/market_features.parquet"
MODEL_PATH = REPO / "ai/models/isolation_forest_market.joblib"
FEATURE_COLUMNS_PATH = REPO / "ai/models/market_feature_columns.json"
SCORES_PATH = REPO / "data/processed/analytics/market_anomaly_scores.parquet"
CONTAMINATION_REPORT_PATH = REPO / "data/processed/analytics/contamination_study.json"

RANDOM_STATE = 42

# Nombre minimal d'informations reellement extraites (parmi montant,
# concurrents, exclusions) pour qu'un marche soit scorable — seuil MESURE,
# voir la docstring du module.
MIN_DATA_COMPLETENESS = 2

STABILITY_SEEDS = list(range(10))
STABILITY_TOP_N = 20

# Colonnes numeriques imputees a la mediane, chacune avec son drapeau.
IMPUTED_COLUMNS = {
    "log_montant_ttc": "has_amount_data",
    "nb_soumissionnaires": "has_competitor_data",
    "nb_concurrents_ecartes": "has_exclusion_data",
    "exclusion_rate": "has_exclusion_data",
}

# Colonnes deja completes a 100 % (mesure sur les 454 marches) : aucune
# imputation, aucun drapeau necessaire.
COMPLETE_COLUMNS = [
    "has_amount_data", "has_competitor_data", "has_exclusion_data",
    "mode_ao_ouvert", "mode_ao_simplifie", "mode_autre",
    "cat_travaux", "cat_fournitures", "cat_services",
]

MODEL_FEATURE_COLUMNS = list(IMPUTED_COLUMNS) + COMPLETE_COLUMNS


def prepare_market_matrix(pdf: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """market_features.parquet -> matrice numerique sans NaN.

    Retourne aussi les medianes utilisees, pour qu'elles soient ecrites dans
    le rapport plutot que de rester invisibles dans le code.
    """
    df = pdf.copy()
    medians = {}
    for col in IMPUTED_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        median = float(df[col].median())
        medians[col] = median
        df[f"{col}_imputed"] = df[col].isna().astype(int)
        df[col] = df[col].fillna(median)

    for col in COMPLETE_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    matrix = df[["award_id"] + MODEL_FEATURE_COLUMNS].copy()
    assert not matrix[MODEL_FEATURE_COLUMNS].isna().any().any(), (
        "NaN residuel apres imputation — diagnostiquer avant d'entrainer")
    return matrix, medians


def drop_constant_features(matrix: pd.DataFrame) -> list[str]:
    """Ecarte les colonnes qui ne varient plus dans la population scoree.

    Trouve en verifiant les sorties SHAP, pas en relisant le code :
    `has_competitor_data` ressortait avec une importance EXACTEMENT nulle
    (0.00000) dans les deux methodes d'explication. Cause : le filtre de
    completude (MIN_DATA_COMPLETENESS) ne laisse passer que des marches
    ayant au moins 2 informations sur 3, et il se trouve que tous les
    marches retenus ont la rubrique concurrents — la colonne vaut donc 1
    partout, 279 fois sur 279.

    Une colonne constante n'apporte aucune information a un modele qui
    tire ses features au hasard : elle occupe une place dans le tirage
    sans jamais pouvoir separer deux points. La correlation ne peut pas la
    detecter (elle vaut NaN sur une constante), d'ou ce controle separe.
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

    Meme raisonnement que le correctif de redondance deja applique au modele
    entreprise (ai/train_isolation_forest.py) : Isolation Forest tire un
    sous-ensemble de features au hasard a chaque coupe, donc un signal
    present en double a deux fois plus de chances d'etre choisi, sans etre
    deux fois plus informatif. La correlation est MESUREE ici, pas supposee.
    """
    corr = matrix[MODEL_FEATURE_COLUMNS].corr().abs()
    dropped = []
    for i, a in enumerate(MODEL_FEATURE_COLUMNS):
        for b in MODEL_FEATURE_COLUMNS[i + 1:]:
            if a in dropped or b in dropped:
                continue
            r = corr.loc[a, b]
            if r >= threshold:
                # On retire la SECONDE, en gardant la plus interpretable
                # (l'ordre de MODEL_FEATURE_COLUMNS place les grandeurs
                # metier avant les drapeaux).
                dropped.append(b)
                print(f"  redondance mesuree r={r:.3f} entre {a!r} et {b!r} "
                      f"-> {b!r} retiree du modele")
    return dropped


def study_contamination(X: np.ndarray, candidates=(0.05, 0.10, 0.15, "auto")) -> dict:
    """Compare plusieurs valeurs de `contamination` au lieu d'en retenir une
    a l'aveugle.

    `contamination` ne mesure RIEN dans les donnees : c'est un curseur qui
    fixe combien d'observations seront etiquetees anormales. Le modele
    entreprise utilisait "auto" et sortait 19,7 % d'anomalies, un chiffre
    que rien ne justifiait et qui pouvait se lire, a tort, comme "19,7 % des
    marches sont suspects".
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

    Sans verite terrain, on ne peut pas mesurer une precision. On peut en
    revanche mesurer si un resultat TIENT : un marche present dans 10/10 des
    classements est une anomalie robuste ; un marche present dans 1/10 est
    un artefact de la graine aleatoire, et le dashboard doit le dire.
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

    # Recouvrement moyen entre deux Top 20 (indice de Jaccard) : une mesure
    # d'ensemble, en plus de la frequence par marche.
    jaccards = [len(a & b) / len(a | b)
                for i, a in enumerate(tops) for b in tops[i + 1:]]
    print(f"  recouvrement moyen entre deux Top {STABILITY_TOP_N} "
          f"(Jaccard) : {np.mean(jaccards):.2f}")
    print(f"  marches apparaissant dans les 10/10 Top {STABILITY_TOP_N} : "
          f"{int((counts == 10).sum())}")
    print(f"  marches apparaissant dans 1 seul Top {STABILITY_TOP_N} : "
          f"{int((counts == 1).sum())}")
    # DataFrame construit explicitement : Series.reset_index(names=...) n'est
    # pas disponible dans la version de pandas de l'image ppi-spark.
    return pd.DataFrame({"award_id": counts.index.to_numpy(),
                         "stability_frequency": counts.to_numpy()})


def main() -> int:
    pdf = pd.read_parquet(MARKET_FEATURES_PATH)
    total = len(pdf)

    print("=== population modelisee ===")
    print(pdf["statut"].value_counts().to_string())
    # Verifie plutot que suppose : les montants manquent-ils VRAIMENT par
    # construction chez les infructueux ?
    for statut, group in pdf.groupby("statut"):
        n_amount = int(group["has_amount_data"].sum())
        print(f"  {statut:<12} montant renseigne : {n_amount}/{len(group)} "
              f"({100 * n_amount / len(group):.1f} %)")

    attribue = pdf[pdf["statut"] == "ATTRIBUE"].reset_index(drop=True)
    print(f"\n{len(attribue)}/{total} marches ATTRIBUE ; "
          f"{total - len(attribue)} marches INFRUCTUEUX restent dans la table, "
          f"non scores (voir docstring).")

    # --- completude, et mise a l'ecart des marches non analysables ------- #
    attribue["data_completeness"] = attribue[
        ["has_amount_data", "has_competitor_data", "has_exclusion_data"]].sum(axis=1)
    attribue["scorable"] = attribue["data_completeness"] >= MIN_DATA_COMPLETENESS

    print("\n=== completude des donnees (marches attribues) ===")
    for k, g in attribue.groupby("data_completeness"):
        marque = "   -> NON SCORABLES" if k < MIN_DATA_COMPLETENESS else ""
        print(f"  {k} information(s) connue(s) sur 3 : {len(g):3d} marches{marque}")
    n_skipped = int((~attribue["scorable"]).sum())
    print(f"\n  {n_skipped}/{len(attribue)} marches "
          f"({100 * n_skipped / len(attribue):.1f} %) ne sont PAS scores : "
          f"moins de {MIN_DATA_COMPLETENESS} informations extraites.")
    print("  Ils ne sont pas supprimes — ils ressortent avec scorable=False et")
    print("  aucun score, et s'affichent comme 'donnees insuffisantes'.")

    scored = attribue[attribue["scorable"]].reset_index(drop=True)
    matrix, medians = prepare_market_matrix(scored)
    print("\n=== imputation (mediane des marches AYANT la donnee) ===")
    for col, median in medians.items():
        n_imputed = int(matrix.shape[0] - scored[col].notna().sum())
        print(f"  {col:<26} mediane={median:>12.4f}  imputes={n_imputed}")

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
    study = study_contamination(X)

    # Choix argumente, pas arbitraire — voir le commentaire ci-dessous et le
    # rapport ecrit dans contamination_study.json.
    chosen = 0.10
    print(f"\n  RETENU : contamination={chosen}")
    print("  Pourquoi : 'auto' ne repond a aucune question metier et sortait")
    print("  19,7 % au niveau entreprise, un chiffre qu'aucune mesure ne")
    print("  soutenait. 10 % fixe une CHARGE DE TRAVAIL D'ANALYSE (~31")
    print("  marches a examiner sur 314), pas un taux d'irregularite. C'est")
    print("  un curseur de priorisation : le faire varier change le nombre")
    print("  de marches remontes, jamais leur classement.")

    model = IsolationForest(n_estimators=200, contamination=chosen,
                            random_state=RANDOM_STATE)
    model.fit(X)
    scores = model.decision_function(X)
    labels = model.predict(X)

    result = scored.copy()
    result["anomaly_score"] = scores
    result["is_anomaly"] = labels == -1
    # 0-100, plus haut = plus atypique. Rescale lineaire (pas un rang, qui
    # aplatirait la forme reelle de la distribution).
    lo, hi = scores.min(), scores.max()
    result["anomaly_score_0_100"] = 100 * (hi - scores) / (hi - lo)
    for col in IMPUTED_COLUMNS:
        result[f"{col}_imputed"] = scored[col].isna().astype(int)

    # Les marches non scorables sont RECOLLES a la sortie, sans score : ils
    # doivent rester visibles et comptes, jamais disparaitre silencieusement.
    unscorable = attribue[~attribue["scorable"]].copy()
    for col in ("anomaly_score", "anomaly_score_0_100", "stability_frequency"):
        unscorable[col] = None
    unscorable["is_anomaly"] = False
    # Ni "Faible" ni un niveau quelconque : l'absence de niveau EST
    # l'information. Un marche non analysable ne doit jamais apparaitre
    # comme rassurant.
    unscorable["risk_level"] = "Non evaluable"

    # --- niveaux de risque, seuils MESURES ------------------------------- #
    # Meme principe que l'etage entreprise : "Faible" est la frontiere que le
    # modele choisit lui-meme (is_anomaly), et le sous-groupe signale est
    # coupe en terciles mesures de sa propre distribution. Jamais 25/50/75.
    normal_max = float(result.loc[~result["is_anomaly"], "anomaly_score_0_100"].max())
    anormaux = result.loc[result["is_anomaly"], "anomaly_score_0_100"]
    t1, t2 = (float(x) for x in anormaux.quantile([1 / 3, 2 / 3]))

    def _level(score: float) -> str:
        if score <= normal_max:
            return "Faible"
        if score <= t1:
            return "Modere"
        if score <= t2:
            return "Eleve"
        return "Critique"

    result["risk_level"] = result["anomaly_score_0_100"].apply(_level)
    print("\n=== niveaux de risque (seuils mesures, pas 25/50/75) ===")
    print(f"  Faible   : score <= {normal_max:.1f}  (frontiere choisie par le modele)")
    print(f"  Modere   : {normal_max:.1f} < score <= {t1:.1f}")
    print(f"  Eleve    : {t1:.1f} < score <= {t2:.1f}")
    print(f"  Critique : score > {t2:.1f}")
    print(result["risk_level"].value_counts().to_string())

    print("\n=== stabilite sur 10 graines aleatoires ===")
    stability = measure_stability(X, matrix["award_id"].to_numpy(), chosen)
    result = result.merge(stability, on="award_id", how="left")

    print(f"\n=== marches signales : {int(result['is_anomaly'].sum())}/{len(result)} ===")
    top = result.sort_values("anomaly_score").head(10)
    print(top[["award_id", "reference", "anomaly_score_0_100", "stability_frequency",
               "nb_soumissionnaires", "montant_ttc", "has_amount_data"]].to_string(index=False))

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    FEATURE_COLUMNS_PATH.write_text(json.dumps(features, indent=2), encoding="utf-8")
    CONTAMINATION_REPORT_PATH.write_text(json.dumps(
        {"candidates": study, "chosen": chosen, "n_scored": len(result),
         "medians_used_for_imputation": medians,
         "dropped_for_redundancy": dropped}, indent=2), encoding="utf-8")
    # Controle explicite que le seuil a bien retire l'effet mesure.
    corr = result["anomaly_score_0_100"].corr(result["data_completeness"])
    print()
    print("=== controle : le modele score-t-il encore le manque de donnees ? ===")
    print(f"  correlation score vs completude : {corr:+.3f} (etait -0,249 sans le seuil)")
    for k, g in result.groupby("data_completeness"):
        print(f"    {k} info(s) : {len(g):3d} marches, {int(g['is_anomaly'].sum()):2d} "
              f"signales ({100 * g['is_anomaly'].mean():.1f} %)")

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
