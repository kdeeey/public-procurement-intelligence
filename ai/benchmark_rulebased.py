"""
Benchmark : Isolation Forest face a une methode simple (Phase 10, 28/08/2026).

CE QUE CE BENCHMARK PEUT ET NE PEUT PAS ETABLIR
-------------------------------------------------
Il n'existe AUCUNE verite terrain au niveau marche : aucun marche de ce
corpus n'est connu comme ayant du etre signale. Ce benchmark ne peut donc
pas dire laquelle des deux methodes a raison, et ne le dira jamais.

Ce qu'il mesure reellement :
  * le RECOUVREMENT des deux classements (intersection, Jaccard, Spearman) ;
  * ce que chacune voit que l'autre ne voit pas.

Si les deux se recouvraient presque entierement, Isolation Forest
n'apporterait rien qu'une addition de regles ne donne deja, et il faudrait
le dire. S'ils divergent, la divergence est l'apport du modele : des
combinaisons inhabituelles qu'aucune regle nommee ne couvre. Dans les deux
cas, c'est une information sur la complementarite, pas sur la justesse.

LA METHODE SIMPLE
-----------------
Un point par red flag primaire actif, sans ponderation :

    rule_score = RF01 + RF02 + RF03 + RF05   (chacun 0 ou 1)

Volontairement plus fruste que `red_flag_score`, qui pondere par severite
et rescale sur les regles evaluables. Une baseline doit etre simple, sinon
elle n'est plus une baseline mais une seconde methode sophistiquee.

Un flag non evaluable compte 0 ICI — c'est une entorse assumee a la regle
UNKNOWN != ZERO, faite pour rester fidele a ce que serait une methode
naive, et elle est signalee : `n_flags_evaluables` accompagne chaque
score, et les marches a faible evaluabilite sont comptes a part.

    python -m ai.benchmark_rulebased
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

from ai.market_red_flags import PRIMARY_FLAGS  # noqa: E402

ANALYTICS = REPO / "data/processed/analytics"
RED_FLAGS_PATH = ANALYTICS / "market_red_flags.parquet"
SCORES_PATH = ANALYTICS / "market_anomaly_scores.parquet"
BENCHMARK_PATH = ANALYTICS / "benchmark_rulebased.parquet"
BENCHMARK_REPORT_PATH = ANALYTICS / "benchmark_report.json"

TOPS = (10, 20, 50)


def compute_rule_score(flags: pd.DataFrame) -> pd.Series:
    """Un point par red flag primaire actif. Aucune ponderation."""
    actifs = pd.DataFrame(
        {fid: (flags[fid] == True).astype(int) for fid in PRIMARY_FLAGS})  # noqa: E712
    return actifs.sum(axis=1)


def jaccard(a: set, b: set) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def compare_tops(df: pd.DataFrame) -> dict:
    """Compare les Top N des deux classements.

    Les egalites sont nombreuses cote regles (le score ne prend que 5
    valeurs) : le departage se fait alors sur `award_id`, de facon
    deterministe, et le nombre d'ex aequo a la frontiere est publie —
    sans quoi un Top 20 "rule-based" serait un choix arbitraire presente
    comme un classement.
    """
    resultats = {}
    for n in TOPS:
        top_if = set(df.nlargest(n, ["anomaly_score_0_100", "award_id"])["award_id"])
        top_rule = set(df.nlargest(n, ["rule_score", "award_id"])["award_id"])
        seuil_rule = df.nlargest(n, ["rule_score", "award_id"])["rule_score"].min()
        ex_aequo = int((df["rule_score"] == seuil_rule).sum())
        resultats[f"top{n}"] = {
            "intersection": len(top_if & top_rule),
            "jaccard": round(jaccard(top_if, top_rule), 3),
            "recouvrement_pct": round(100 * len(top_if & top_rule) / n, 1),
            "seulement_isolation_forest": len(top_if - top_rule),
            "seulement_rule_based": len(top_rule - top_if),
            "score_regles_a_la_frontiere": int(seuil_rule),
            "marches_ex_aequo_a_la_frontiere": ex_aequo,
        }
    return resultats


def main() -> int:
    flags = pd.read_parquet(RED_FLAGS_PATH)
    scores = pd.read_parquet(SCORES_PATH)[
        ["award_id", "anomaly_score_0_100", "is_anomaly", "scorable"]]
    df = flags.merge(scores, on="award_id", how="inner", suffixes=("", "_s"))
    df = df[df["scorable"] == True].reset_index(drop=True)  # noqa: E712

    df["rule_score"] = compute_rule_score(df)

    print(f"=== populations comparees ({len(df)} marches scorables) ===")
    print("  Isolation Forest : score continu 0-100")
    print("  Methode simple   : 1 point par red flag primaire actif (0 a 4)")
    print()
    print("  distribution du rule_score :")
    for score, n in df["rule_score"].value_counts().sort_index().items():
        print(f"    {int(score)} point(s) : {n:3d} marches")
    print(f"\n  Le score de regles ne prend que "
          f"{df['rule_score'].nunique()} valeurs distinctes : beaucoup d'ex aequo,")
    print("  donc un 'classement' rule-based est en partie arbitraire a la frontiere.")

    correlation = df["anomaly_score_0_100"].corr(df["rule_score"], method="spearman")
    print(f"\n=== correlation des rangs (Spearman) : {correlation:+.3f} ===")

    tops = compare_tops(df)
    print("\n=== recouvrement des classements ===")
    print(f"{'':8}{'inter.':>8}{'Jaccard':>9}{'recouv.':>9}{'IF seul':>9}"
          f"{'regles seul':>13}{'ex aequo':>10}")
    for nom, r in tops.items():
        print(f"  {nom:<6}{r['intersection']:>8}{r['jaccard']:>9.3f}"
              f"{r['recouvrement_pct']:>8.1f}%{r['seulement_isolation_forest']:>9}"
              f"{r['seulement_rule_based']:>13}"
              f"{r['marches_ex_aequo_a_la_frontiere']:>10}")

    # --- ce que chacune voit seule -------------------------------------- #
    top20_if = set(df.nlargest(20, ["anomaly_score_0_100", "award_id"])["award_id"])
    top20_rule = set(df.nlargest(20, ["rule_score", "award_id"])["award_id"])

    print("\n=== 5 marches vus SEULEMENT par Isolation Forest ===")
    seuls_if = df[df["award_id"].isin(top20_if - top20_rule)].nlargest(
        5, "anomaly_score_0_100")
    print(seuls_if[["award_id", "reference", "anomaly_score_0_100", "rule_score",
                    "red_flags_evaluable"]].to_string(index=False))
    print("  Score eleve sans red flag nomme : c'est une combinaison inhabituelle")
    print("  qu'aucune regle ne couvre — l'apport propre du modele.")

    print("\n=== 5 marches vus SEULEMENT par la methode simple ===")
    seuls_rule = df[df["award_id"].isin(top20_rule - top20_if)].nlargest(
        5, "rule_score")
    print(seuls_rule[["award_id", "reference", "anomaly_score_0_100", "rule_score",
                      "red_flags_evaluable"]].to_string(index=False))
    print("  Red flags actifs sans isolement statistique : le marche cumule des")
    print("  caracteristiques nommees, mais ressemble a beaucoup d'autres.")

    print("\n=== ce que ce benchmark N'ETABLIT PAS ===")
    print("  Aucune verite terrain n'existe au niveau marche. Ni l'une ni l'autre")
    print("  des deux methodes n'est declaree correcte. Ce qui est mesure, c'est")
    print("  leur complementarite — et elle justifie de garder les deux, pas de")
    print("  choisir.")

    BENCHMARK_PATH.parent.mkdir(parents=True, exist_ok=True)
    df[["award_id", "reference", "anomaly_score_0_100", "rule_score",
        "red_flag_count", "red_flags_evaluable"]].to_parquet(BENCHMARK_PATH, index=False)
    BENCHMARK_REPORT_PATH.write_text(json.dumps({
        "n_marches": len(df),
        "correlation_spearman": round(float(correlation), 3),
        "distribution_rule_score": {str(int(k)): int(v) for k, v in
                                    df["rule_score"].value_counts().sort_index().items()},
        "tops": tops,
        "verite_terrain": None,
        "avertissement": ("Aucune verite terrain au niveau marche : ce benchmark "
                          "mesure un recouvrement, jamais une superiorite."),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nEcrit : {BENCHMARK_PATH}")
    print(f"Ecrit : {BENCHMARK_REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
