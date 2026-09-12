"""
Priority Score — quels marches examiner en premier (refonte "red flags
only" ; remplace la formule ponderee 50/50 anomalie+red flags du 28/08/2026).

CE QUE CE SCORE EST, ET CE QU'IL N'EST PAS
--------------------------------------------
Il repond a "quels marches un analyste devrait-il examiner en priorite ?",
jamais a "quels marches sont irreguliers ?". C'est un ordre de lecture,
pas un verdict.

LE NIVEAU EST DECIDE PAR LE COMPTE DE RED FLAGS, JAMAIS PAR LE MODELE
-------------------------------------------------------------------------
`priority_level` est une fonction PURE de `priority_flag_count`
(ai/market_red_flags.py — nombre de flags actifs parmi RF01/RF02/RF03,
les 3 "red flags prioritaires") :

    0/3 actif  -> Faible
    1/3 actif  -> A surveiller   (~33 %)
    2/3 actifs -> Prioritaire    (~66 %)
    3/3 actifs -> Tres prioritaire (~99-100 %)

Isolation Forest (ai/train_market_model.py, entraine SUR ces 3 flags) ne
decide plus rien ici — voir la docstring de ce module pour la mecanique.
Son `anomaly_score_0_100` sert uniquement a construire `priority_raw`, une
cle de tri qui DEPARTAGE les marches a egalite de compte sans jamais
pouvoir changer leur niveau :

    priority_raw = 1000 * priority_flag_count + anomaly_score_0_100

Le compte est multiplie par 1000 et le score du modele reste dans [0, 100] :
un marche a 2/3 vaut donc toujours entre 2000 et 2100, strictement en
dessous du plus bas score a 3/3 (3000) et au-dessus du plus haut a 1/3
(1100). Trier par `priority_raw` revient donc a trier par compte d'abord,
par rarete de la combinaison de flags ensuite — un seul champ, aucune
regle particuliere a ecrire dans chaque appelant (tableau, API, page XAI).

LA QUALITE DES DONNEES EST UN GARDE-FOU, PAS UN BONUS
-------------------------------------------------------
Inchange : un marche tres prioritaire dont on ne sait presque rien ne doit
PAS remonter en tete. Deux mecanismes distincts, jamais melanges au score :

  * `confidence_level` combine la qualite des donnees (part d'informations
    reellement lues) et la stabilite du score (nombre de reentrainements
    sur 10 ou le marche ressort dans le Top 20 — desormais un diagnostic du
    modele, pas un signal en soi, voir ai/train_market_model.py).
  * un PLAFOND : une confiance faible interdit les deux niveaux les plus
    hauts. Le marche reste visible, avec son score, mais il est presente
    comme "a verifier — donnees faibles" et non comme prioritaire.

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

# Cle de tri composite : le compte de flags prioritaires domine toujours
# (multiplie par cette constante), le score du modele (0-100) ne fait que
# departager a l'interieur d'un meme compte. Doit rester strictement > 100
# (la plage de anomaly_score_0_100) pour que la separation soit garantie.
COUNT_MULTIPLIER = 1000.0

LEVEL_BY_COUNT = {0: "Faible", 1: "A surveiller", 2: "Prioritaire", 3: "Tres prioritaire"}

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
    # observe". La stabilite n'est donc prise en compte que lorsqu'elle a un
    # sens : quand le marche est effectivement apparu au moins une fois.
    stabilite_applicable = pd.notna(stab) and float(stab) > 0
    for label, seuil_dq, seuil_stab in CONFIDENCE_RULES:
        if dq < seuil_dq:
            continue
        if stabilite_applicable and float(stab) < seuil_stab:
            continue
        return label
    return "Faible"


def compute_priority_raw(row):
    """Cle de tri composite — voir la docstring du module.

    None quand le marche n'est pas scorable (moins de 2 des 3 flags
    prioritaires evaluables) : pas de score, pas de niveau invente.
    """
    anomaly = row.get("anomaly_score_0_100")
    count = row.get("priority_flag_count")
    if pd.isna(anomaly) or pd.isna(count):
        return None
    return COUNT_MULTIPLIER * int(count) + float(anomaly)


def assign_level(raw, confidence: str) -> str:
    """Le niveau se lit directement sur la tranche de `raw` (le compte de
    flags actifs, avant le point flottant du score) — jamais sur un seuil
    mesure/quantile : c'est deja discret 0-3, ca ne beneficie d'aucun
    lissage supplementaire."""
    if raw is None or pd.isna(raw):
        return "Donnees insuffisantes"
    level = LEVEL_BY_COUNT[int(raw // COUNT_MULTIPLIER)]

    # LE garde-fou : une confiance faible interdit les deux niveaux hauts.
    # Un marche a 3/3 flags dont on ne sait presque rien voit son niveau
    # porte surtout par ce qu'on ignore.
    if confidence == "Faible" and level in ("Tres prioritaire", "Prioritaire"):
        return CAPPED_LEVEL
    return level


def main() -> int:
    df = pd.read_parquet(SCORES_PATH)[
        ["award_id", "reference", "acheteur_public", "statut", "scorable",
         "anomaly_score_0_100", "is_anomaly", "stability_frequency",
         "data_completeness", "risk_level"]]
    flags = pd.read_parquet(RED_FLAGS_PATH)[
        ["award_id", "red_flag_score", "red_flag_count", "red_flags_evaluable",
         "red_flags_triggered", "priority_flag_count", "priority_flags_evaluable"]]
    dq = pd.read_parquet(DATA_QUALITY_PATH)[
        ["award_id", "data_quality_score", "data_quality_level",
         "invalid_fields_count"]]
    df = df.merge(flags, on="award_id", how="left").merge(dq, on="award_id", how="left")

    df["confidence_level"] = df.apply(compute_confidence, axis=1)
    df["priority_raw"] = df.apply(compute_priority_raw, axis=1)
    df["priority_score"] = df["priority_raw"].round(1)
    df["priority_level"] = df.apply(
        lambda r: assign_level(r["priority_raw"], r["confidence_level"]), axis=1)

    print("=== formule ===")
    print("  niveau = f(priority_flag_count, nombre de RF01/RF02/RF03 actifs) :")
    for count, level in LEVEL_BY_COUNT.items():
        print(f"    {count}/3 actif(s) -> {level}")
    print(f"  priority_raw = {COUNT_MULTIPLIER:.0f} x priority_flag_count + "
          f"anomaly_score_0_100 (0-100)")
    print("  Le compte fixe TOUJOURS le niveau ; le score du modele (entraine")
    print("  sur ces memes 3 flags, ai/train_market_model.py) ne fait que")
    print("  departager les marches a egalite de compte, jamais changer de niveau.")

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
        lambda r: assign_level(r["priority_raw"], "Elevee"), axis=1)
    plafonnes = int(((sans_plafond.isin(["Tres prioritaire", "Prioritaire"]))
                     & (df["priority_level"] == CAPPED_LEVEL)).sum())
    print(f"\n=== effet du plafond de confiance ===")
    print(f"  {plafonnes} marches auraient ete classes prioritaires sur leur seul")
    print(f"  compte de flags, mais leur confiance est faible : ils sont ramenes a "
          f"'{CAPPED_LEVEL}'.")
    print("  Ils restent visibles et gardent leur score — ils ne sont pas caches,")
    print("  ils sont presentes pour ce qu'ils sont : un signal sur peu de donnees.")

    print("\n=== 10 marches en tete ===")
    top = df.nlargest(10, "priority_raw")[
        ["award_id", "reference", "priority_score", "priority_level",
         "confidence_level", "data_quality_score", "priority_flag_count",
         "stability_frequency"]]
    print(top.to_string(index=False))

    PRIORITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PRIORITY_PATH, index=False)
    PRIORITY_REPORT_PATH.write_text(json.dumps({
        "formule": {"count_multiplier": COUNT_MULTIPLIER,
                    "level_by_count": LEVEL_BY_COUNT},
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
