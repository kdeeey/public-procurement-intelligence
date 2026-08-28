"""
Data Quality Score par marche (Phase 1, 28/08/2026).

CE QUE CE MODULE MESURE, ET CE QU'IL NE MESURE PAS
---------------------------------------------------
Il mesure ce que NOUS savons d'un marche, pas ce que ce marche vaut. Un
Data Quality Score bas ne dit rien du marche : il dit que notre chaine
d'extraction n'a pas reussi a en lire grand-chose. Les deux ne doivent
jamais etre confondus dans l'affichage — c'est la raison d'etre de ce
score, et la raison pour laquelle il est presente A COTE du score
d'anomalie, jamais additionne avec lui.

QUATRE ETATS, PAS DEUX
-----------------------
Le projet a deja paye le prix de la confusion UNKNOWN/ZERO (77 marches
comptes a "0 soumissionnaire" alors que le document ne disait rien). Ce
module pousse la distinction plus loin, avec quatre etats :

  KNOWN          la valeur a ete lue dans le document. Inclut le zero
                 REELLEMENT observe ("aucun concurrent ecarte").
  UNKNOWN        le document ne porte pas l'information. On ne sait pas.
  NOT_APPLICABLE l'information n'a pas de sens pour ce marche. Cas mesure :
                 le gagnant d'un marche INFRUCTUEUX — 0/140 en ont un, par
                 construction. Compter cela comme "manquant" penaliserait
                 un marche pour une information qui ne pouvait pas exister.
  INVALID        l'information a ete lue mais elle est incoherente. Ce
                 n'est ni un manque ni une donnee : c'est un defaut connu,
                 qui doit se voir.

Seul NOT_APPLICABLE sort du denominateur. UNKNOWN et INVALID y restent
tous les deux : ne pas savoir et savoir faux sont deux facons de ne pas
pouvoir conclure.

LES CAS INVALID SONT MESURES, PAS IMAGINES
-------------------------------------------
Chaque regle INVALID ci-dessous correspond a des cas reellement presents
dans le corpus au 28/08/2026, comptes avant d'ecrire la regle :

  * exclusion_rate > 1 (18 marches) — plus de concurrents ecartes que de
    concurrents listes. Arithmetiquement impossible.
  * marche ATTRIBUE avec 0 soumissionnaire exploitable (56 marches) — on
    ne peut pas attribuer un marche a personne. Sur ces 56, 35 avaient des
    noms dans le document, tous rejetes par le filtre de plausibilite :
    l'information EXISTAIT et nous ne savons pas la lire. C'est un defaut
    d'extraction, pas un marche sans concurrence.
  * annee de la date d'ouverture ecartee de 2 ans ou plus de l'annee du
    marche (1 marche, ecart de 7 ans). Un ecart de 1 an est garde comme
    valide : une procedure a cheval sur deux annees est ordinaire.

Aucune regle n'a ete ecrite pour un cas absent du corpus : montant negatif
ou nul (0 cas), nombre de soumissionnaires negatif (0 cas), date hors de
la plage 2015-2027 (0 cas). Les ajouter "au cas ou" donnerait l'illusion
d'un controle qui n'a jamais rien vu.

CONSEQUENCE CONNUE, CORRIGEE EN PHASE 2
----------------------------------------
Les 56 marches ci-dessus declenchent aujourd'hui RF01 ("soumissionnaire
unique") parce que la regle actuelle est `nb <= 1`, et 0 <= 1. Sur les 152
RF01 actifs, 56 (37 %) viennent donc d'un marche ou AUCUN nom n'a pu etre
lu. Ce module marque desormais leur dimension "concurrents" INVALID ;
RF01 sera reecrit pour la lire en Phase 2. Signale ici plutot que corrige
en silence, pour que l'ecart entre les deux phases soit visible.

    python -m features.data_quality
"""

from __future__ import annotations

import enum
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

MARKET_FEATURES_PATH = REPO / "data/processed/analytics/market_features.parquet"
DATA_QUALITY_PATH = REPO / "data/processed/analytics/market_data_quality.parquet"

# Ecart maximal tolere entre l'annee de la date d'ouverture et l'annee du
# marche. 1 an est ordinaire (procedure a cheval sur deux annees) ; au-dela
# c'est une lecture fausse — mesure : 2 ecarts dans le corpus, de -1 an
# (garde valide) et -7 ans (marque invalide).
MAX_YEAR_GAP = 1


class State(str, enum.Enum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INVALID = "INVALID"


# Dimensions NOTEES : uniquement celles qui varient reellement d'un marche
# a l'autre. Mesure au 28/08/2026 sur les 454 marches :
#
#   procedure, secteur, annee, objet, acheteur, ref_consultation : 454/454
#
# Les inclure donnerait a tous les marches le meme plancher de points, ce
# qui ne distingue rien et gonfle artificiellement le score. Elles sont
# listees separement (ALWAYS_AVAILABLE) et rapportees comme telles, pour
# que leur exclusion soit un choix visible et non un oubli.
ALWAYS_AVAILABLE = ("mode_passation", "categorie_principale", "annee",
                    "objet", "acheteur_public", "ref_consultation")

SCORED_DIMENSIONS = ("montant", "concurrents", "exclusions", "date", "gagnant")

# Poids EGAUX, comme le score composite d'ai/scoring.py et pour la meme
# raison, deja actee dans ce projet : le corpus est trop petit pour
# estimer des poids differencies sans les inventer. Un poids devine
# ressemble a une connaissance ; il n'en est pas une.
DIMENSION_WEIGHTS = {d: 1.0 for d in SCORED_DIMENSIONS}


def _num(value):
    return pd.to_numeric(value, errors="coerce")


def assess_montant(row) -> State:
    montant = _num(row.get("montant_ttc"))
    if pd.isna(montant):
        return State.UNKNOWN
    # Aucun montant <= 0 dans le corpus (mesure) ; la regle existe parce
    # qu'un montant nul serait ininterpretable, pas parce qu'un cas a ete
    # observe.
    return State.INVALID if montant <= 0 else State.KNOWN


def assess_concurrents(row) -> State:
    if not row.get("has_competitor_data"):
        return State.UNKNOWN
    nb = _num(row.get("nb_soumissionnaires"))
    if pd.isna(nb):
        return State.UNKNOWN
    # Un marche ATTRIBUE a forcement eu au moins un soumissionnaire : on ne
    # peut pas attribuer a personne. 0 signale donc une lecture ratee, pas
    # une absence de concurrence (56 marches, dont 35 ou des noms etaient
    # bien presents mais tous rejetes par le filtre de plausibilite).
    if nb <= 0 and row.get("statut") == "ATTRIBUE":
        return State.INVALID
    return State.KNOWN


def assess_exclusions(row) -> State:
    if not row.get("has_exclusion_data"):
        return State.UNKNOWN
    taux = _num(row.get("exclusion_rate"))
    if pd.notna(taux) and taux > 1:
        # Plus d'ecartes que de soumissionnaires : incoherence entre les
        # deux rubriques extraites (18 marches mesures).
        return State.INVALID
    return State.KNOWN


def assess_date(row) -> State:
    date = pd.to_datetime(row.get("date_ouverture_plis"), errors="coerce")
    if pd.isna(date):
        return State.UNKNOWN
    annee = _num(row.get("annee"))
    if pd.notna(annee) and abs(int(date.year) - int(annee)) > MAX_YEAR_GAP:
        return State.INVALID
    return State.KNOWN


def assess_gagnant(row) -> State:
    # Un marche INFRUCTUEUX n'a pas d'attributaire par construction —
    # verifie : 0/140 en ont un. Le compter comme une information manquante
    # penaliserait le marche pour une information qui ne pouvait pas
    # exister. C'est le seul NOT_APPLICABLE du corpus.
    if row.get("statut") == "INFRUCTUEUX":
        return State.NOT_APPLICABLE
    return State.KNOWN if row.get("has_winner") else State.UNKNOWN


ASSESSORS = {
    "montant": assess_montant,
    "concurrents": assess_concurrents,
    "exclusions": assess_exclusions,
    "date": assess_date,
    "gagnant": assess_gagnant,
}


def assess_market(row) -> dict[str, State]:
    return {name: fn(row) for name, fn in ASSESSORS.items()}


def compute_quality(states: dict[str, State]) -> dict:
    """Etats des dimensions -> score 0-100 et ses composantes.

    Le denominateur exclut NOT_APPLICABLE : un marche infructueux est note
    sur 4 dimensions, pas sur 5. UNKNOWN et INVALID restent au
    denominateur — ne pas savoir et savoir faux empechent tous les deux de
    conclure, meme si la cause differe.

    Un marche dont TOUTES les dimensions seraient NOT_APPLICABLE n'aurait
    pas de score (None), pas un score de 0 : ce cas n'existe pas dans le
    corpus actuel, mais un 0 y serait faux plutot que prudent.
    """
    known = sum(DIMENSION_WEIGHTS[d] for d, s in states.items() if s is State.KNOWN)
    unknown = sum(DIMENSION_WEIGHTS[d] for d, s in states.items() if s is State.UNKNOWN)
    invalid = sum(DIMENSION_WEIGHTS[d] for d, s in states.items() if s is State.INVALID)
    not_applicable = sum(DIMENSION_WEIGHTS[d] for d, s in states.items()
                         if s is State.NOT_APPLICABLE)
    denominator = known + unknown + invalid
    score = round(100 * known / denominator, 1) if denominator else None
    return {
        "data_quality_score": score,
        "known_fields_count": int(known),
        "missing_fields_count": int(unknown),
        "invalid_fields_count": int(invalid),
        "not_applicable_fields_count": int(not_applicable),
        "evaluable_fields_count": int(denominator),
    }


# Seuils VERIFIES sur la distribution reelle avant d'etre figes — voir
# `describe_distribution()` et la sortie de main().
#
# Le score n'est pas continu : avec 5 dimensions notees (4 pour un marche
# infructueux, dont le gagnant est NOT_APPLICABLE), il ne peut prendre que
# 9 valeurs, mesurees sur le corpus :
#
#     0 / 20 / 25 / 40 / 50 / 60 / 75 / 80 / 100
#
# Precision qui compte, contre une premiere formulation trop commode : 90
# tombe bien entre deux valeurs atteignables (80 et 100), mais 75 et 50
# sont EXACTEMENT des valeurs atteignables, portees respectivement par 26
# et 38 marches. Ce sont des bornes INFERIEURES INCLUSIVES : ces marches
# basculent donc dans la classe superieure (Bon et Moyen). C'est un choix
# — placer la borne a 76 ou 51 les ferait tous basculer d'un cran — et il
# est ici assume plutot que masque derriere "les seuils tombent entre deux
# paliers", ce qui aurait ete faux pour deux d'entre eux.
#
# Distribution obtenue : Bon 31,1 %, Moyen 30,2 %, Faible 25,1 %,
# Excellent 13,7 %. Aucune classe n'absorbe plus de 60 % du corpus, donc
# les seuils separent reellement la population.
QUALITY_LEVELS = (
    (90.0, "Excellent"),
    (75.0, "Bon"),
    (50.0, "Moyen"),
    (0.0, "Faible"),
)


def quality_level(score: float | None) -> str:
    if score is None:
        return "Non evaluable"
    for seuil, label in QUALITY_LEVELS:
        if score >= seuil:
            return label
    return "Faible"


def add_data_quality(pdf: pd.DataFrame) -> pd.DataFrame:
    """market_features -> les memes lignes + les colonnes de qualite.

    N'ecrase aucune colonne existante et ne retire aucune ligne : ce module
    ajoute une lecture, il ne filtre pas.
    """
    rows = []
    for _, row in pdf.iterrows():
        states = assess_market(row)
        record = compute_quality(states)
        for dim, state in states.items():
            record[f"dq_{dim}"] = state.value
        record["award_id"] = row["award_id"]
        rows.append(record)
    quality = pd.DataFrame(rows)
    quality["data_quality_level"] = quality["data_quality_score"].apply(quality_level)
    return pdf.merge(quality, on="award_id", how="left")


def describe_distribution(df: pd.DataFrame) -> None:
    """Verifie que les seuils separent reellement la population, plutot que
    de les figer parce qu'ils ont l'air raisonnables."""
    print("\n=== distribution du data_quality_score ===")
    counts = df["data_quality_score"].value_counts().sort_index()
    for score, n in counts.items():
        print(f"  {score:5.1f} : {n:3d} marches ({100 * n / len(df):4.1f} %) "
              f"-> {quality_level(score)}")

    print("\n=== distribution des niveaux ===")
    levels = df["data_quality_level"].value_counts()
    biggest = levels.max() / len(df)
    for level, n in levels.items():
        print(f"  {level:<14} {n:3d} ({100 * n / len(df):4.1f} %)")
    print(f"\n  classe la plus chargee : {100 * biggest:.1f} % du corpus")
    if biggest > 0.60:
        print("  ATTENTION : une classe absorbe plus de 60 % des marches — les")
        print("  seuils ne separent pas grand-chose et doivent etre rediscutes.")
    else:
        print("  Aucune classe n'absorbe plus de 60 % : les seuils separent.")


def main() -> int:
    pdf = pd.read_parquet(MARKET_FEATURES_PATH)
    enriched = add_data_quality(pdf)

    print(f"=== Data Quality Score sur {len(enriched)} marches ===")
    print(f"dimensions notees      : {', '.join(SCORED_DIMENSIONS)}")
    print(f"dimensions ecartees    : {', '.join(ALWAYS_AVAILABLE)}")
    print("  (renseignees a 100 % — les noter donnerait le meme plancher a tous)")
    print("dimensions impossibles : estimation (0/454), localisation (absente "
          "de la table de faits)")

    print("\n=== etat par dimension ===")
    print(f"{'dimension':<16}{'KNOWN':>8}{'UNKNOWN':>9}{'INVALID':>9}{'N/A':>7}")
    for dim in SCORED_DIMENSIONS:
        col = enriched[f"dq_{dim}"]
        print(f"  {dim:<14}{int((col == 'KNOWN').sum()):>8}"
              f"{int((col == 'UNKNOWN').sum()):>9}"
              f"{int((col == 'INVALID').sum()):>9}"
              f"{int((col == 'NOT_APPLICABLE').sum()):>7}")

    n_invalid = int((enriched["invalid_fields_count"] > 0).sum())
    print(f"\n  marches portant au moins une donnee INVALIDE : {n_invalid}/{len(enriched)}")
    print("  (rappel : INVALIDE = lue mais incoherente, distinct de manquante)")

    describe_distribution(enriched)

    print("\n=== recoupement avec le seuil de scorabilite du modele ===")
    # data_completeness vit dans market_anomaly_scores.parquet (produit par
    # ai/train_market_model.py), pas dans market_features : on le joint ici
    # plutot que de le recalculer, pour qu'il ne puisse pas diverger.
    scores_path = REPO / "data/processed/analytics/market_anomaly_scores.parquet"
    if scores_path.exists():
        scores = pd.read_parquet(scores_path)[["award_id", "data_completeness", "scorable"]]
        joined = enriched.merge(scores, on="award_id", how="inner")
        print(joined.groupby("data_completeness")["data_quality_score"]
              .agg(["count", "mean", "min", "max"]).to_string())
        print()
        print(joined.groupby("scorable")["data_quality_score"]
              .agg(["count", "mean", "min", "max"]).to_string())
    else:
        print("  (market_anomaly_scores.parquet absent — recoupement non fait)")
    print("  data_completeness (0-3) reste la regle qui decide si un marche est")
    print("  score par le modele ; data_quality_score (0-100) est une lecture")
    print("  plus fine, destinee a l'analyste. Les deux ne sont pas redondants :")
    print("  le premier est une porte, le second un contexte.")

    DATA_QUALITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    keep = ["award_id", "data_quality_score", "data_quality_level",
            "known_fields_count", "missing_fields_count", "invalid_fields_count",
            "not_applicable_fields_count", "evaluable_fields_count"]
    keep += [f"dq_{d}" for d in SCORED_DIMENSIONS]
    enriched[keep].to_parquet(DATA_QUALITY_PATH, index=False)
    print(f"\nEcrit : {DATA_QUALITY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
