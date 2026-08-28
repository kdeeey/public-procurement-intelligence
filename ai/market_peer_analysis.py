"""
Comparaison a des marches comparables (Phase 3, 28/08/2026).

LA QUESTION QUE CE MODULE CORRIGE
----------------------------------
Jusqu'ici, "montant atypique" voulait dire "eleve par rapport aux 454
marches du corpus" — toutes categories et toutes procedures confondues. Un
marche de travaux a 12 M DH et une prestation de services a 12 M DH n'ont
pourtant rien de comparable. La question pertinente n'est pas "ce marche
est-il gros ?" mais "ce marche est-il gros POUR CE QU'IL EST ?".

LA CASCADE, ET POURQUOI ELLE EXISTE
------------------------------------
Un groupe trop fin devient vide, un groupe trop large redevient le corpus.
Mesure sur les 314 marches attribues (couverture a n>=10 comparables) :

    secteur x procedure x annee : 29 groupes,  81,2 % du corpus couvert
    secteur x procedure         : 10 groupes,  98,1 %
    secteur x annee             : 12 groupes, 100,0 %
    secteur seul                :  3 groupes, 100,0 %

D'ou une cascade du plus fin au plus grossier : on descend d'un cran
seulement quand le niveau courant n'atteint pas MIN_PEERS. Le niveau
reellement utilise est publie avec chaque comparaison (`peer_group_level`)
— une comparaison faite sur "secteur seul" ne vaut pas celle faite sur
"secteur x procedure x annee", et l'analyste doit pouvoir le voir.

Si meme le niveau le plus grossier n'atteint pas MIN_PEERS :
NOT_ENOUGH_PEERS. Aucune reference n'est inventee.

DEUX MINIMUMS, PAS UN — LE PIEGE EVITE
----------------------------------------
La taille du groupe ne dit rien de sa capacite a servir de reference sur
une dimension donnee. Un groupe de 40 marches dont seuls 3 portent un
montant ne peut pas fournir une mediane de montant credible : 63 % du
corpus n'a pas de montant extrait.

Chaque comparaison exige donc DEUX conditions :
  1. le marche lui-meme a la valeur (etat KNOWN, jamais imputee) ;
  2. au moins MIN_PEERS_PER_DIMENSION comparables ont AUSSI la valeur.

`n_peers` (taille du groupe) et `n_peers_amount` / `n_peers_competitors`
(comparables reellement exploitables) sont publies separement.

LE MARCHE EST EXCLU DE SES PROPRES COMPARABLES
------------------------------------------------
Une mediane calculee en incluant le marche compare est tiree vers lui,
d'autant plus fort que le groupe est petit. Avec des groupes de 10 a 30
marches, l'effet n'est pas negligeable. Chaque statistique de reference
est donc calculee sur le groupe PRIVE du marche evalue.

    python -m ai.market_peer_analysis
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from features.data_quality import State, assess_market  # noqa: E402

SCORES_PATH = REPO / "data/processed/analytics/market_anomaly_scores.parquet"
PEER_PATH = REPO / "data/processed/analytics/market_peer_comparison.parquet"
PEER_REPORT_PATH = REPO / "data/processed/analytics/peer_group_report.json"

# Taille minimale d'un groupe de comparaison. En dessous, la mediane et les
# quantiles reposent sur trop peu d'observations pour distinguer un marche
# atypique d'une fluctuation.
MIN_PEERS = 10

# Minimum de comparables PORTANT REELLEMENT la dimension comparee. Fixe au
# meme niveau que MIN_PEERS : il n'y a pas de raison d'etre plus tolerant
# sur une mediane de montant que sur la taille du groupe.
MIN_PEERS_PER_DIMENSION = 10

# Du plus fin au plus grossier. L'ordre est celui de la mesure ci-dessus.
CASCADE = (
    ("fin", ("categorie_principale", "mode_passation", "annee")),
    ("moyen", ("categorie_principale", "mode_passation")),
    ("large", ("categorie_principale", "annee")),
    ("tres_large", ("categorie_principale",)),
)

NOT_ENOUGH_PEERS = "NOT_ENOUGH_PEERS"


def assign_peer_groups(pdf: pd.DataFrame) -> pd.DataFrame:
    """Ajoute `peer_group_level`, `peer_group_key` et `n_peers`.

    Descend la cascade jusqu'a trouver un niveau atteignant MIN_PEERS.
    `n_peers` compte les AUTRES marches du groupe (le marche lui-meme est
    exclu partout — voir la docstring du module).
    """
    result = pdf.copy()
    result["peer_group_level"] = NOT_ENOUGH_PEERS
    result["peer_group_key"] = None
    result["n_peers"] = 0

    for level, keys in CASCADE:
        a_placer = result["peer_group_level"] == NOT_ENOUGH_PEERS
        if not a_placer.any():
            break
        tailles = result.groupby(list(keys), dropna=False)["award_id"].transform("size")
        # -1 : le marche evalue ne compte pas parmi ses propres comparables.
        assez = (tailles - 1) >= MIN_PEERS
        cible = a_placer & assez
        result.loc[cible, "peer_group_level"] = level
        result.loc[cible, "peer_group_key"] = (
            result.loc[cible, list(keys)].astype(str).agg(" | ".join, axis=1))
        result.loc[cible, "n_peers"] = (tailles - 1)[cible]
    return result


def _compare(value: float, peers: pd.Series) -> dict:
    """Une valeur face a la distribution de ses comparables.

    `peers` ne contient jamais le marche evalue. Le percentile est la part
    de comparables strictement inferieurs — donc 0,90 signifie "plus eleve
    que 90 % des comparables", ce qui se lit directement.
    """
    peers = peers.dropna()
    median = float(peers.median())
    return {
        "n": int(len(peers)),
        "median": median,
        "p90": float(peers.quantile(0.90)),
        # Ratio non defini si la mediane est nulle — on renvoie None plutot
        # qu'un infini ou un 0 trompeur.
        "ratio": float(value / median) if median else None,
        "percentile": float((peers < value).mean()),
    }


def build_peer_comparison(pdf: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par marche : sa position face a ses comparables."""
    grouped = assign_peer_groups(pdf)
    states = {int(r["award_id"]): assess_market(r) for _, r in grouped.iterrows()}

    rows = []
    for _, row in grouped.iterrows():
        award_id = int(row["award_id"])
        record = {
            "award_id": award_id,
            "peer_group_level": row["peer_group_level"],
            "peer_group_key": row["peer_group_key"],
            "n_peers": int(row["n_peers"]),
            "amount_vs_peer_median": None, "amount_percentile_peer": None,
            "amount_above_peer_p90": None, "n_peers_amount": 0,
            "competitors_vs_peer_median": None, "competitors_percentile_peer": None,
            "n_peers_competitors": 0,
            "peer_status": row["peer_group_level"],
        }
        if row["peer_group_level"] == NOT_ENOUGH_PEERS:
            rows.append(record)
            continue

        peers = grouped[(grouped["peer_group_key"] == row["peer_group_key"])
                        & (grouped["award_id"] != award_id)]
        peer_states = [states[int(i)] for i in peers["award_id"]]

        # --- montant : exige KNOWN chez le marche ET chez ses comparables --
        if states[award_id]["montant"] is State.KNOWN:
            mask = [s["montant"] is State.KNOWN for s in peer_states]
            valeurs = pd.to_numeric(peers.loc[mask, "montant_ttc"], errors="coerce")
            if len(valeurs.dropna()) >= MIN_PEERS_PER_DIMENSION:
                comp = _compare(float(row["montant_ttc"]), valeurs)
                record["amount_vs_peer_median"] = comp["ratio"]
                record["amount_percentile_peer"] = comp["percentile"]
                record["amount_above_peer_p90"] = bool(float(row["montant_ttc"]) >= comp["p90"])
                record["n_peers_amount"] = comp["n"]

        # --- concurrence : meme double condition -------------------------- #
        if states[award_id]["concurrents"] is State.KNOWN:
            mask = [s["concurrents"] is State.KNOWN for s in peer_states]
            valeurs = pd.to_numeric(peers.loc[mask, "nb_soumissionnaires"], errors="coerce")
            if len(valeurs.dropna()) >= MIN_PEERS_PER_DIMENSION:
                comp = _compare(float(row["nb_soumissionnaires"]), valeurs)
                record["competitors_vs_peer_median"] = comp["ratio"]
                record["competitors_percentile_peer"] = comp["percentile"]
                record["n_peers_competitors"] = comp["n"]

        rows.append(record)
    return pd.DataFrame(rows)


def main() -> int:
    pdf = pd.read_parquet(SCORES_PATH)
    peers = build_peer_comparison(pdf)

    print(f"=== groupes de comparaison ({len(peers)} marches attribues) ===")
    print(f"minimum requis : {MIN_PEERS} comparables (le marche lui-meme exclu)")
    for level, n in peers["peer_group_level"].value_counts().items():
        keys = dict(CASCADE).get(level)
        libelle = " x ".join(keys) if keys else "aucun groupe atteignant le minimum"
        print(f"  {level:<16} {n:3d} marches  ({libelle})")

    print(f"\n  taille des groupes : mediane={int(peers['n_peers'].median())}, "
          f"min={int(peers['n_peers'].min())}, max={int(peers['n_peers'].max())}")

    print("\n=== comparaisons reellement calculables ===")
    n_amount = int(peers["amount_vs_peer_median"].notna().sum())
    n_comp = int(peers["competitors_vs_peer_median"].notna().sum())
    print(f"  montant     : {n_amount}/{len(peers)} "
          f"({100 * n_amount / len(peers):.1f} %)")
    print(f"  concurrence : {n_comp}/{len(peers)} "
          f"({100 * n_comp / len(peers):.1f} %)")
    print("  L'ecart avec le nombre de marches ayant un groupe vient du SECOND")
    print("  minimum : il ne suffit pas d'avoir 10 comparables, il faut 10")
    print("  comparables qui portent LA MEME dimension. 63 % du corpus n'a pas")
    print("  de montant extrait.")

    with_amount = peers[peers["amount_vs_peer_median"].notna()]
    if len(with_amount):
        print("\n=== position face aux comparables (montant) ===")
        print(f"  ratio au median : mediane={with_amount['amount_vs_peer_median'].median():.2f}, "
              f"max={with_amount['amount_vs_peer_median'].max():.1f}")
        print(f"  au-dessus du P90 de leurs comparables : "
              f"{int(with_amount['amount_above_peer_p90'].sum())} marches")
        top = with_amount.nlargest(5, "amount_vs_peer_median")[
            ["award_id", "peer_group_level", "n_peers_amount",
             "amount_vs_peer_median", "amount_percentile_peer"]]
        print(top.to_string(index=False))

    PEER_PATH.parent.mkdir(parents=True, exist_ok=True)
    peers.to_parquet(PEER_PATH, index=False)
    PEER_REPORT_PATH.write_text(json.dumps({
        "min_peers": MIN_PEERS,
        "min_peers_per_dimension": MIN_PEERS_PER_DIMENSION,
        "cascade": [{"level": lv, "keys": list(k)} for lv, k in CASCADE],
        "levels": {k: int(v) for k, v in peers["peer_group_level"].value_counts().items()},
        "n_amount_comparisons": n_amount,
        "n_competitor_comparisons": n_comp,
        "n_markets": len(peers),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nEcrit : {PEER_PATH}")
    print(f"Ecrit : {PEER_REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
