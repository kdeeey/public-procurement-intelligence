"""
Verrous sur la comparaison a des marches comparables (Phase 3, 28/08/2026).

Ce que ces tests protegent :

  1. Le marche evalue est EXCLU de ses propres comparables. Sur des groupes
     de 10 a 30, s'inclure tire la mediane vers soi.
  2. DEUX minimums, pas un : avoir 10 comparables ne suffit pas, il faut
     10 comparables portant la MEME dimension. 63 % du corpus n'a pas de
     montant extrait.
  3. Aucune reference n'est inventee : sous le minimum, NOT_ENOUGH_PEERS.
  4. La cascade descend du plus fin au plus grossier, et le niveau
     reellement utilise est publie.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

from ai.market_peer_analysis import (  # noqa: E402
    MIN_PEERS, NOT_ENOUGH_PEERS, assign_peer_groups, build_peer_comparison,
)


def corpus(n_travaux_ouvert=30, n_services=3, montants=True) -> pd.DataFrame:
    """Corpus synthetique minimal : un gros groupe homogene + un groupe trop
    petit pour atteindre le minimum au niveau fin."""
    rows = []
    aid = 0
    for i in range(n_travaux_ouvert):
        aid += 1
        rows.append({
            "award_id": aid, "statut": "ATTRIBUE",
            "categorie_principale": "TRAVAUX", "mode_passation": "AO ouvert",
            "annee": 2025,
            "montant_ttc": (1_000_000.0 + i * 1000) if montants else None,
            "has_competitor_data": 1, "nb_soumissionnaires": 3,
            "has_exclusion_data": 1, "exclusion_rate": 0.0,
            "date_ouverture_plis": pd.Timestamp("2025-03-01"), "has_winner": 1,
        })
    for i in range(n_services):
        aid += 1
        rows.append({
            "award_id": aid, "statut": "ATTRIBUE",
            "categorie_principale": "SERVICES", "mode_passation": "AO restreint",
            "annee": 2025, "montant_ttc": 500_000.0,
            "has_competitor_data": 1, "nb_soumissionnaires": 2,
            "has_exclusion_data": 1, "exclusion_rate": 0.0,
            "date_ouverture_plis": pd.Timestamp("2025-03-01"), "has_winner": 1,
        })
    return pd.DataFrame(rows)


def test_le_marche_est_exclu_de_ses_propres_comparables():
    """n_peers compte les AUTRES marches du groupe."""
    df = assign_peer_groups(corpus(n_travaux_ouvert=30, n_services=0))
    assert df["n_peers"].iloc[0] == 29


def test_groupe_trop_petit_descend_la_cascade_puis_abandonne():
    """3 marches SERVICES : aucun niveau n'atteint le minimum, donc
    NOT_ENOUGH_PEERS — jamais une reference inventee sur 2 comparables."""
    df = assign_peer_groups(corpus(n_travaux_ouvert=30, n_services=3))
    services = df[df["categorie_principale"] == "SERVICES"]
    assert (services["peer_group_level"] == NOT_ENOUGH_PEERS).all()
    assert (services["n_peers"] == 0).all()

    travaux = df[df["categorie_principale"] == "TRAVAUX"]
    assert (travaux["peer_group_level"] == "fin").all()


def test_pas_de_comparaison_sans_assez_de_pairs_portant_la_dimension():
    """LE piege que le second minimum evite : un groupe assez grand dont
    presque aucun membre n'a de montant ne peut pas fournir de mediane."""
    df = corpus(n_travaux_ouvert=30, n_services=0)
    # Un seul marche conserve son montant : le groupe reste grand, mais la
    # dimension "montant" n'est plus exploitable.
    df.loc[df.index[1:], "montant_ttc"] = None
    peers = build_peer_comparison(df)
    assert (peers["n_peers"] >= MIN_PEERS).all(), "le groupe reste valide"
    assert peers["amount_vs_peer_median"].isna().all(), (
        "aucune comparaison de montant ne doit etre produite sans assez de "
        "comparables portant eux-memes un montant")
    # La comparaison de concurrence, elle, reste calculable.
    assert peers["competitors_vs_peer_median"].notna().any()


def test_comparaison_de_montant_produit_ratio_et_percentile():
    df = corpus(n_travaux_ouvert=30, n_services=0)
    df.loc[df.index[0], "montant_ttc"] = 100_000_000.0  # tres au-dessus
    peers = build_peer_comparison(df).set_index("award_id")
    haut = peers.loc[1]
    assert haut["amount_vs_peer_median"] > 1
    assert haut["amount_percentile_peer"] == 1.0
    assert bool(haut["amount_above_peer_p90"]) is True
    assert haut["n_peers_amount"] == 29


def test_montant_absent_ne_produit_aucune_comparaison():
    """Un montant non extrait ne doit jamais etre compare — ni impute, ni
    remplace par la mediane du groupe."""
    df = corpus(n_travaux_ouvert=30, n_services=0)
    df.loc[df.index[0], "montant_ttc"] = None
    peers = build_peer_comparison(df).set_index("award_id")
    assert pd.isna(peers.loc[1, "amount_vs_peer_median"])
    assert peers.loc[1, "n_peers_amount"] == 0


def test_niveau_de_groupe_publie_avec_la_comparaison():
    """Une comparaison faite sur 'secteur seul' ne vaut pas celle faite sur
    'secteur x procedure x annee' : le niveau doit rester lisible."""
    peers = build_peer_comparison(corpus(n_travaux_ouvert=30, n_services=0))
    assert set(peers["peer_group_level"]) == {"fin"}
    assert peers["peer_group_key"].notna().all()
