"""
Priority Score — quels marches examiner en premier (Phases 6 et 7, 28/08/2026).

CE QUE CE SCORE EST, ET CE QU'IL N'EST PAS
--------------------------------------------
Il repond a "quels marches un analyste devrait-il examiner en priorite ?",
jamais a "quels marches sont irreguliers ?". C'est un ordre de lecture,
pas un verdict. Deux marches de meme priorite ne partagent rien d'autre que
le fait de meriter un coup d'oeil.

LA FORMULE, ET POURQUOI ELLE N'ADDITIONNE PAS TOUT
----------------------------------------------------
    priority_raw = 0,5 x anomaly_score_0_100  +  0,5 x red_flag_score

Deux composantes seulement. Trois raisons, toutes verifiees :

1. **La comparaison aux pairs n'est PAS un troisieme terme.** Elle alimente
   deja RF03 (ai/market_red_flags.py depuis la Phase 3) : l'ajouter
   separement compterait deux fois le meme signal. C'est exactement le
   piege que le projet a deja rencontre au niveau entreprise, ou
   `market_share`, `total_amount` et `average_amount` etaient un seul
   signal compte trois fois (r = 1,000 et 0,996 mesures).

2. **Poids egaux, parce que rien ne justifie de les differencier.**
   Mesure : la correlation entre `anomaly_score` et le nombre de red flags
   actifs vaut +0,195 — les deux signaux sont largement independants, donc
   tous deux informatifs, et aucun n'est demontrablement superieur. Sans
   verite terrain, un poids asymetrique serait une preference deguisee en
   connaissance. Trois formulations sont neanmoins comparees a l'execution
   (voir `compare_formulations`) pour montrer ce que le choix change.

3. **La qualite des donnees n'entre PAS dans le score.** Elle agit comme
   CONFIANCE, separement — voir ci-dessous.

LA QUALITE DES DONNEES EST UN GARDE-FOU, PAS UN BONUS
-------------------------------------------------------
Exigence explicite du cahier des charges, et elle change tout : un marche
tres atypique dont on ne sait presque rien ne doit PAS remonter en tete.
Son score eleve viendrait alors surtout de ce qu'on ignore.

Deux mecanismes distincts, jamais melanges au score :

  * `confidence_level` combine la qualite des donnees (part d'informations
    reellement lues) et la stabilite du score (nombre de reentrainements
    sur 10 ou le marche ressort dans le Top 20).
  * un PLAFOND : une confiance faible interdit les deux niveaux les plus
    hauts. Le marche reste visible, avec son score, mais il est presente
    comme "a verifier — donnees faibles" et non comme prioritaire.

Ajouter la qualite au score aurait eu l'effet inverse de celui recherche :
un marche bien documente aurait ete recompense d'etre bien documente.

    python -m ai.priority_score
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

ANALYTICS = REPO / "data/processed/analytics"
SCORES_PATH = ANALYTICS / "market_anomaly_scores.parquet"
RED_FLAGS_PATH = ANALYTICS / "market_red_flags.parquet"
DATA_QUALITY_PATH = ANALYTICS / "market_data_quality.parquet"
PRIORITY_PATH = ANALYTICS / "market_priority.parquet"
PRIORITY_REPORT_PATH = ANALYTICS / "priority_report.json"

W_ANOMALY = 0.5
W_RED_FLAGS = 0.5

# Seuils de CONFIANCE. La qualite des donnees est deja une mesure sur 100 ;
# 75 est la frontiere "Bon" de features/data_quality.py, reutilisee ici
# plutot que d'en inventer une seconde. La stabilite est un comptage sur 10.
CONFIDENCE_RULES = (
    ("Elevee", 75.0, 8),
    ("Moyenne", 50.0, 5),
)

# Niveaux de priorite. "Donnees insuffisantes" n'est PAS un niveau bas :
# c'est un etat distinct, qui ne doit jamais se lire comme rassurant.
LEVEL_ORDER = ["Tres prioritaire", "Prioritaire", "A surveiller", "Faible",
               "Donnees insuffisantes"]
CAPPED_LEVEL = "A surveiller"   # plafond applique quand la confiance est faible


def compute_confidence(row) -> str:
    """Confiance dans le score d'un marche : ce que valent les donnees et
    la stabilite du resultat, jamais le score lui-meme."""
    if row.get("scorable") is not True:
        return "Insuffisante"
    dq = row.get("data_quality_score")
    stab = row.get("stability_frequency")
    if pd.isna(dq):
        return "Faible"

    # `stability_frequency` compte les Top 20 (sur 10 reentrainements) ou ce
    # marche apparait. Elle ne discrimine donc QUE parmi les marches que le
    # modele remonte : un marche jamais entre dans un Top 20 vaut 0, ce qui
    # ne veut pas dire "instable" mais "hors de la zone que cette mesure
    # observe".
    #
    # Bug corrige le 28/08/2026 : la version precedente ne neutralisait que
    # la valeur MANQUANTE, pas le 0. Resultat mesure, 264/314 marches
    # (84 %) tombaient en confiance "Faible" et le plafond s'appliquait
    # presque partout — le garde-fou, cense proteger quelques cas, devenait
    # la regle generale et ecrasait toute la hierarchie de priorite.
    #
    # La stabilite n'est donc prise en compte que lorsqu'elle a un sens :
    # quand le marche est effectivement apparu au moins une fois.
    stabilite_applicable = pd.notna(stab) and float(stab) > 0
    for label, seuil_dq, seuil_stab in CONFIDENCE_RULES:
        if dq < seuil_dq:
            continue
        if stabilite_applicable and float(stab) < seuil_stab:
            continue
        return label
    return "Faible"


def compute_priority_raw(row, w_anomaly=W_ANOMALY, w_flags=W_RED_FLAGS):
    """Combinaison lineaire des deux composantes.

    `red_flag_score` peut etre None (aucune regle evaluable sur ce marche).
    Dans ce cas la combinaison est REPONDEREE sur la seule composante
    disponible plutot que de traiter l'absence comme un zero — sinon un
    marche dont aucune regle n'est applicable verrait sa priorite divisee
    par deux par notre propre manque de donnees.
    """
    anomaly = row.get("anomaly_score_0_100")
    flags = row.get("red_flag_score")
    if pd.isna(anomaly):
        return None
    if flags is None or pd.isna(flags):
        return float(anomaly)
    return float(w_anomaly * anomaly + w_flags * flags)


def measure_levels(priorities: pd.Series) -> dict:
    """Seuils MESURES sur la distribution, jamais 25/50/75.

    Terciles du sous-groupe le plus prioritaire, meme methode que les
    niveaux de risque du modele : le corpus decide ou sont ses propres
    ruptures.
    """
    valides = priorities.dropna()
    return {
        "p60": float(valides.quantile(0.60)),
        "p80": float(valides.quantile(0.80)),
        "p90": float(valides.quantile(0.90)),
    }


def assign_level(raw, confidence: str, seuils: dict) -> str:
    if raw is None or pd.isna(raw):
        return "Donnees insuffisantes"
    if raw >= seuils["p90"]:
        level = "Tres prioritaire"
    elif raw >= seuils["p80"]:
        level = "Prioritaire"
    elif raw >= seuils["p60"]:
        level = "A surveiller"
    else:
        level = "Faible"

    # LE garde-fou : une confiance faible interdit les deux niveaux hauts.
    # Un marche tres atypique dont on ne sait presque rien voit son score
    # porte surtout par ce qu'on ignore.
    if confidence == "Faible" and level in ("Tres prioritaire", "Prioritaire"):
        return CAPPED_LEVEL
    return level


def compare_formulations(df: pd.DataFrame) -> dict:
    """Trois ponderations comparees, pour montrer ce que le choix change.

    Sans verite terrain, aucune ne peut etre declaree meilleure. Ce qu'on
    peut mesurer, c'est leur ACCORD : si les trois classent les marches
    presque pareil, le choix du poids importe peu et le resultat est
    robuste ; si elles divergent, le poids devient une decision lourde
    qu'il faut assumer explicitement.
    """
    variantes = {"equilibre_50_50": (0.5, 0.5),
                 "anomalie_dominante_70_30": (0.7, 0.3),
                 "red_flags_dominants_30_70": (0.3, 0.7)}
    scores = {}
    for nom, (wa, wf) in variantes.items():
        scores[nom] = df.apply(lambda r: compute_priority_raw(r, wa, wf), axis=1)

    ref = scores["equilibre_50_50"]
    out = {}
    for nom, serie in scores.items():
        commun = pd.concat([ref, serie], axis=1).dropna()
        top20_ref = set(ref.dropna().nlargest(20).index)
        top20_var = set(serie.dropna().nlargest(20).index)
        out[nom] = {
            "correlation_rangs_vs_equilibre": round(
                float(commun.iloc[:, 0].corr(commun.iloc[:, 1], method="spearman")), 3),
            "top20_communs_avec_equilibre": len(top20_ref & top20_var),
        }
    return out


def main() -> int:
    df = pd.read_parquet(SCORES_PATH)[
        ["award_id", "reference", "acheteur_public", "statut", "scorable",
         "anomaly_score_0_100", "is_anomaly", "stability_frequency",
         "data_completeness", "risk_level"]]
    flags = pd.read_parquet(RED_FLAGS_PATH)[
        ["award_id", "red_flag_score", "red_flag_count", "red_flags_evaluable",
         "red_flags_triggered"]]
    dq = pd.read_parquet(DATA_QUALITY_PATH)[
        ["award_id", "data_quality_score", "data_quality_level",
         "invalid_fields_count"]]
    df = df.merge(flags, on="award_id", how="left").merge(dq, on="award_id", how="left")

    df["confidence_level"] = df.apply(compute_confidence, axis=1)
    df["priority_raw"] = df.apply(compute_priority_raw, axis=1)
    seuils = measure_levels(df["priority_raw"])
    df["priority_score"] = df["priority_raw"].round(1)
    df["priority_level"] = df.apply(
        lambda r: assign_level(r["priority_raw"], r["confidence_level"], seuils), axis=1)

    print("=== formule ===")
    print(f"  priority_raw = {W_ANOMALY} x anomaly_score + {W_RED_FLAGS} x red_flag_score")
    print("  La comparaison aux pairs n'est PAS un terme separe : elle alimente")
    print("  deja RF03, donc red_flag_score. L'ajouter compterait deux fois.")
    print("  La qualite des donnees n'est PAS dans le score : elle plafonne le")
    print("  niveau (voir plus bas).")

    print("\n=== comparaison de trois ponderations ===")
    comp = compare_formulations(df)
    for nom, res in comp.items():
        print(f"  {nom:<28} rho(Spearman)={res['correlation_rangs_vs_equilibre']:+.3f}  "
              f"Top20 communs={res['top20_communs_avec_equilibre']}/20")
    print("  Aucune n'est 'meilleure' : sans verite terrain, on ne mesure que")
    print("  leur accord. Le 50/50 est retenu parce qu'aucune mesure ne justifie")
    print("  d'avantager l'une des deux composantes.")

    print("\n=== seuils mesures sur la distribution ===")
    print(f"  Tres prioritaire : priority >= {seuils['p90']:.1f}  (P90)")
    print(f"  Prioritaire      : >= {seuils['p80']:.1f}  (P80)")
    print(f"  A surveiller     : >= {seuils['p60']:.1f}  (P60)")

    print("\n=== confiance ===")
    print(df["confidence_level"].value_counts().to_string())

    print("\n=== niveaux de priorite ===")
    dist = df["priority_level"].value_counts().reindex(LEVEL_ORDER, fill_value=0)
    for level, n in dist.items():
        print(f"  {level:<22} {n:3d}  ({100 * n / len(df):4.1f} %)")
    part_max = dist.max() / len(df)
    print(f"\n  classe la plus chargee : {100 * part_max:.1f} %")
    if part_max > 0.60:
        print("  ATTENTION : une classe absorbe plus de 60 % du corpus.")
    else:
        print("  Aucune classe n'absorbe plus de 60 % : les niveaux separent.")

    # --- le garde-fou a-t-il servi ? ------------------------------------- #
    sans_plafond = df.apply(
        lambda r: assign_level(r["priority_raw"], "Elevee", seuils), axis=1)
    plafonnes = int(((sans_plafond.isin(["Tres prioritaire", "Prioritaire"]))
                     & (df["priority_level"] == CAPPED_LEVEL)).sum())
    print(f"\n=== effet du plafond de confiance ===")
    print(f"  {plafonnes} marches auraient ete classes prioritaires sur leur seul")
    print(f"  score, mais leur confiance est faible : ils sont ramenes a "
          f"'{CAPPED_LEVEL}'.")
    print("  Ils restent visibles et gardent leur score — ils ne sont pas caches,")
    print("  ils sont presentes pour ce qu'ils sont : un signal sur peu de donnees.")

    print("\n=== 10 marches en tete ===")
    top = df.nlargest(10, "priority_raw")[
        ["award_id", "reference", "priority_score", "priority_level",
         "confidence_level", "data_quality_score", "red_flag_count",
         "stability_frequency"]]
    print(top.to_string(index=False))

    PRIORITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PRIORITY_PATH, index=False)
    PRIORITY_REPORT_PATH.write_text(json.dumps({
        "formule": {"w_anomaly": W_ANOMALY, "w_red_flags": W_RED_FLAGS},
        "seuils": seuils,
        "formulations_comparees": comp,
        "distribution_niveaux": {k: int(v) for k, v in dist.items()},
        "distribution_confiance": {k: int(v) for k, v in
                                   df["confidence_level"].value_counts().items()},
        "n_plafonnes_par_confiance_faible": plafonnes,
        "n_marches": len(df),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nEcrit : {PRIORITY_PATH}")
    print(f"Ecrit : {PRIORITY_REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
