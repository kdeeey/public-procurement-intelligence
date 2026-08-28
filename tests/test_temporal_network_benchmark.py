"""
Verrous sur les analyses transversales (Phases 4, 5, 10 — 28/08/2026).

Ce que ces tests protegent :

  TEMPOREL — un taux est toujours accompagne de son effectif, et une
  granularite trop fine est refusee plutot que produite avec 4 observations
  par point.

  RESEAU — le volet entreprise reste refuse tant qu'aucune entreprise
  n'atteint 3 marches. Le recalculer sous un autre nom reintroduirait
  l'artefact de couverture du corpus que la bascule vers le marche a
  elimine.

  BENCHMARK — aucune des deux methodes n'est declaree correcte, et le
  nombre d'ex aequo a la frontiere d'un Top N reste visible.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

from ai.benchmark_rulebased import compare_tops, compute_rule_score, jaccard  # noqa: E402
from ai.market_temporal_analysis import (  # noqa: E402
    ANNEE_TRONQUEE, build_yearly, check_monthly, detect_ruptures,
)
from ai.network_analysis import build_acheteur_network, measure_company_side  # noqa: E402


def marches(n_par_annee=(("2023", 30), ("2024", 30))) -> pd.DataFrame:
    lignes, aid = [], 0
    for annee, n in n_par_annee:
        for i in range(n):
            aid += 1
            lignes.append({
                "award_id": aid, "annee": int(annee), "statut": "ATTRIBUE",
                "montant_ttc": 500_000.0,
                "has_competitor_data": 1, "nb_soumissionnaires": 1 if i % 2 else 4,
                "has_exclusion_data": 1, "exclusion_rate": 0.0,
                "date_ouverture_plis": pd.Timestamp(f"{annee}-03-01"),
                "has_winner": 1, "mode_passation": "Appel d'offres ouvert",
                "scorable": True, "is_anomaly": i == 0,
                "companies": [f"ENTREPRISE {aid}"],
                "acheteur_public": "ACHETEUR A",
            })
    return pd.DataFrame(lignes)


# --------------------------------------------------------------------------- #
# Temporel
# --------------------------------------------------------------------------- #

def test_chaque_taux_porte_son_effectif():
    y = build_yearly(marches())
    for _, ligne in y.iterrows():
        assert ligne["n_avec_donnee_concurrence"] > 0
        assert ligne["n_avec_montant"] > 0
    assert set(y.columns) >= {"n_avec_donnee_concurrence", "n_avec_donnee_exclusions",
                              "n_avec_montant", "n_scorables"}


def test_taux_none_quand_aucune_donnee_exploitable():
    """Un taux sans denominateur n'existe pas : None, jamais 0.0."""
    df = marches()
    df["has_competitor_data"] = 0
    df["nb_soumissionnaires"] = None
    y = build_yearly(df)
    assert y["taux_faible_concurrence"].isna().all()
    assert (y["n_avec_donnee_concurrence"] == 0).all()


def test_annee_tronquee_exclue_des_evolutions():
    df = marches((("2024", 30), (str(ANNEE_TRONQUEE), 30)))
    y = build_yearly(df)
    assert y.loc[y["annee"] == ANNEE_TRONQUEE, "annee_tronquee"].all()
    # Une seule annee pleine : aucune evolution calculable.
    assert detect_ruptures(y, "taux_faible_concurrence") == []


def test_granularite_mensuelle_refusee_quand_trop_peu_par_point():
    """4 marches par mois ne font pas une serie temporelle."""
    lignes = []
    for m in range(1, 13):
        for i in range(4):
            lignes.append({"date_ouverture_plis": pd.Timestamp(f"2025-{m:02d}-05")})
    verdict = check_monthly(pd.DataFrame(lignes))
    assert verdict["exploitable"] is False
    assert verdict["mediane_par_mois"] == 4.0


# --------------------------------------------------------------------------- #
# Reseau
# --------------------------------------------------------------------------- #

def test_cote_entreprise_refuse_quand_le_degre_max_est_deux():
    """Aucune entreprise a 3 marches -> un 'degre' serait un booleen 1-ou-2
    deguise, et un market_count par entreprise reintroduirait l'artefact de
    couverture du corpus."""
    df = marches()
    df.loc[df.index[1], "companies"] = df.loc[df.index[0], "companies"]  # une a 2
    mesure = measure_company_side(df)
    assert mesure["degre_max"] == 2
    assert mesure["exploitable"] is False


def test_cote_entreprise_redevient_exploitable_a_trois_marches():
    """Le refus est conditionnel a la mesure, pas grave dans le marbre :
    un corpus plus profond doit pouvoir le lever."""
    df = marches()
    for idx in df.index[:3]:
        df.at[idx, "companies"] = ["ENTREPRISE RECURRENTE"]
    mesure = measure_company_side(df)
    assert mesure["degre_max"] == 3
    assert mesure["exploitable"] is True


def test_concentration_non_exploitable_sous_le_seuil():
    df = marches((("2025", 3),))
    reseau = build_acheteur_network(df)
    assert (~reseau["concentration_exploitable"]).all(), (
        "une concentration calculee sur 3 marches ne mesure rien")


def test_concentration_calculee_sur_les_marches_avec_gagnant():
    df = marches((("2025", 10),))
    df["companies"] = [["TITULAIRE UNIQUE"]] * len(df)
    reseau = build_acheteur_network(df)
    ligne = reseau.iloc[0]
    assert ligne["n_titulaires_distincts"] == 1
    assert ligne["part_du_premier_titulaire"] == 1.0
    assert ligne["indice_concentration_hhi"] == 1.0
    assert ligne["concentration_exploitable"]


# --------------------------------------------------------------------------- #
# Benchmark
# --------------------------------------------------------------------------- #

def test_rule_score_compte_un_point_par_flag_actif():
    flags = pd.DataFrame({"RF01": [True, False, None], "RF02": [True, True, None],
                          "RF03": [False, None, None], "RF05": [False, False, True]})
    scores = compute_rule_score(flags)
    assert list(scores) == [2, 1, 1]


def test_jaccard():
    assert jaccard({1, 2, 3}, {2, 3, 4}) == 0.5
    assert jaccard(set(), set()) == 0.0


def test_comparaison_publie_les_ex_aequo_a_la_frontiere():
    """Le score de regles ne prend que quelques valeurs : un Top N est en
    partie arbitraire a la frontiere, et cette limite doit rester visible."""
    df = pd.DataFrame({
        "award_id": range(1, 31),
        "anomaly_score_0_100": [float(i) for i in range(30)],
        "rule_score": [1] * 30,
    })
    res = compare_tops(df)
    assert res["top10"]["marches_ex_aequo_a_la_frontiere"] == 30
    assert 0.0 <= res["top10"]["jaccard"] <= 1.0
