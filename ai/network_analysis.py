"""
Analyse relationnelle (Phase 5, 28/08/2026) — cote ACHETEUR uniquement.

CE MODULE REFUSE LA MOITIE DE CE QUI LUI ETAIT DEMANDE, ET DIT POURQUOI
-----------------------------------------------------------------------
La demande couvrait un graphe Administration -> Marche -> Entreprise, avec
des metriques de concentration et de co-occurrence des deux cotes. Mesure
faite avant d'ecrire une ligne :

    degre des entreprises : 180 a 1 marche, 13 a 2 marches, MAXIMUM = 2
    marches a >= 2 entreprises (groupement) : 1
    paires (entreprise, acheteur) repetees : 11, toutes a exactement 2

Consequences, toutes verifiees plutot que supposees :

  * "Entreprise apparaissant sur beaucoup de marches" n'existe pas : aucune
    n'atteint 3. La metrique serait un booleen 1-ou-2 deguise en degre.
  * Le graphe entreprise <-> entreprise a UNE arete. Il n'y a pas de
    structure a analyser.
  * Surtout : un `market_count` par entreprise EST la variable dont ce
    projet a demontre qu'elle produisait 13/13 d'anomalies contre 25/180 —
    l'artefact de couverture du scraping que la bascule vers le marche a
    ete faite pour eliminer. La calculer a nouveau, meme sous le nom de
    "centralite", la reintroduirait par la porte de derriere.

Le cote ACHETEUR, lui, porte une vraie structure : 128 acheteurs, jusqu'a
25 marches, 19 avec au moins 5. C'est donc le seul cote analyse.

VOCABULAIRE
-----------
"Concentration", "relation atypique", "structure relationnelle
inhabituelle". Jamais "reseau de corruption", jamais "entente". Une
concentration eleve chez un acheteur a des causes ordinaires (marche local
etroit, specialite technique, faible nombre d'operateurs qualifies) avant
d'en avoir d'extraordinaires.

LIMITE STRUCTURELLE DE TOUT CE QUI SUIT
-----------------------------------------
Le gagnant n'est identifie que sur 205 des 314 marches attribues (65,3 %).
Toute concentration calculee ici porte donc sur les seuls marches ou le
titulaire a pu etre lu, et cet effectif est publie a cote de chaque
mesure. Un acheteur dont 2 marches sur 12 ont un gagnant identifie peut
afficher 100 % de concentration sans que cela signifie quoi que ce soit.

    python -m ai.network_analysis
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

ANALYTICS = REPO / "data/processed/analytics"
FEATURES_PATH = ANALYTICS / "market_features.parquet"
NETWORK_PATH = ANALYTICS / "acheteur_network.parquet"
NETWORK_REPORT_PATH = ANALYTICS / "network_report.json"

# Nombre minimal de marches AVEC gagnant identifie pour qu'une
# concentration soit publiee comme exploitable.
MIN_MARCHES_AVEC_GAGNANT = 5


def _companies(valeur) -> list[str]:
    if valeur is None:
        return []
    return [str(c) for c in valeur if c is not None]


def measure_company_side(pdf: pd.DataFrame) -> dict:
    """Mesure le cote entreprise pour JUSTIFIER son refus, pas pour le
    publier comme une analyse."""
    degres = Counter()
    for valeur in pdf["companies"]:
        for c in _companies(valeur):
            degres[c] += 1
    distribution = Counter(degres.values())
    groupements = int(sum(1 for v in pdf["companies"] if len(_companies(v)) > 1))
    paires = Counter()
    for _, row in pdf.iterrows():
        for c in _companies(row["companies"]):
            paires[(c, row["acheteur_public"])] += 1
    repetees = [v for v in paires.values() if v > 1]
    return {
        "n_entreprises": len(degres),
        "degre_max": max(degres.values()) if degres else 0,
        "distribution_degres": {str(k): int(v) for k, v in sorted(distribution.items())},
        "marches_avec_groupement": groupements,
        "aretes_entreprise_entreprise": groupements,
        "paires_entreprise_acheteur_repetees": len(repetees),
        "exploitable": bool(degres and max(degres.values()) >= 3),
    }


def build_acheteur_network(pdf: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par acheteur : volume, diversite des titulaires,
    concentration."""
    lignes = []
    for acheteur, groupe in pdf.groupby("acheteur_public"):
        titulaires = Counter()
        for valeur in groupe["companies"]:
            for c in _companies(valeur):
                titulaires[c] += 1

        n_avec_gagnant = int(groupe["has_winner"].sum())
        top_part = (max(titulaires.values()) / n_avec_gagnant
                    if titulaires and n_avec_gagnant else None)
        # Herfindahl sur les parts de marches attribues a chaque titulaire
        # identifie : 1,0 = un seul titulaire, proche de 0 = tres disperse.
        hhi = (sum((v / n_avec_gagnant) ** 2 for v in titulaires.values())
               if titulaires and n_avec_gagnant else None)

        montants = pd.to_numeric(groupe["montant_ttc"], errors="coerce").dropna()
        lignes.append({
            "acheteur_public": acheteur,
            "n_marches": len(groupe),
            "n_marches_avec_gagnant": n_avec_gagnant,
            "n_titulaires_distincts": len(titulaires),
            "part_du_premier_titulaire": top_part,
            "indice_concentration_hhi": hhi,
            "titulaire_le_plus_frequent": (titulaires.most_common(1)[0][0]
                                           if titulaires else None),
            "n_marches_du_premier": (titulaires.most_common(1)[0][1]
                                     if titulaires else 0),
            "montant_total_ttc_connu": float(montants.sum()) if len(montants) else None,
            "n_avec_montant": int(len(montants)),
            # Une concentration calculee sur 1 ou 2 marches ne veut rien dire.
            "concentration_exploitable": n_avec_gagnant >= MIN_MARCHES_AVEC_GAGNANT,
        })
    return pd.DataFrame(lignes).sort_values("n_marches", ascending=False).reset_index(drop=True)


def main() -> int:
    pdf = pd.read_parquet(FEATURES_PATH)
    pdf = pdf[pdf["statut"] == "ATTRIBUE"].reset_index(drop=True)

    cote_entreprise = measure_company_side(pdf)
    print("=== cote ENTREPRISE : mesure, puis REFUS ===")
    print(f"  entreprises nommees        : {cote_entreprise['n_entreprises']}")
    print(f"  degre maximum              : {cote_entreprise['degre_max']} marches")
    print(f"  distribution des degres    : {cote_entreprise['distribution_degres']}")
    print(f"  aretes entreprise<->entreprise : "
          f"{cote_entreprise['aretes_entreprise_entreprise']}")
    print(f"  paires (entreprise, acheteur) repetees : "
          f"{cote_entreprise['paires_entreprise_acheteur_repetees']}")
    print(f"  exploitable : {cote_entreprise['exploitable']}")
    print("  Aucune entreprise n'atteint 3 marches : un 'degre' y serait un")
    print("  booleen 1-ou-2. Et un market_count par entreprise EST la variable")
    print("  qui produisait 13/13 d'anomalies contre 25/180 avant la bascule")
    print("  vers le marche. Ce cote n'est donc pas publie.")

    reseau = build_acheteur_network(pdf)
    print(f"\n=== cote ACHETEUR : {len(reseau)} acheteurs ===")
    print(f"  marches par acheteur : mediane={int(reseau['n_marches'].median())}, "
          f"max={int(reseau['n_marches'].max())}")
    print(f"  acheteurs avec >= 5 marches  : {int((reseau['n_marches'] >= 5).sum())}")
    print(f"  acheteurs avec >= 10 marches : {int((reseau['n_marches'] >= 10).sum())}")

    exploitables = reseau[reseau["concentration_exploitable"]]
    print(f"\n  concentration exploitable (>= {MIN_MARCHES_AVEC_GAGNANT} marches avec "
          f"gagnant identifie) : {len(exploitables)}/{len(reseau)} acheteurs")
    print("  Le gagnant n'est lu que sur 205/314 marches : une concentration")
    print("  calculee sur 2 marches identifies sur 12 ne mesure rien.")

    if len(exploitables):
        top = exploitables.nlargest(8, "indice_concentration_hhi")[
            ["acheteur_public", "n_marches", "n_marches_avec_gagnant",
             "n_titulaires_distincts", "part_du_premier_titulaire",
             "indice_concentration_hhi"]]
        top = top.copy()
        top["acheteur_public"] = top["acheteur_public"].str.slice(0, 42)
        print("\n=== concentrations les plus elevees (structure, pas verdict) ===")
        print(top.to_string(index=False))
        print("\n  Une concentration elevee a des causes ordinaires avant d'en")
        print("  avoir d'extraordinaires : marche local etroit, specialite")
        print("  technique, faible nombre d'operateurs qualifies. C'est une")
        print("  structure a regarder, jamais une entente constatee.")

    NETWORK_PATH.parent.mkdir(parents=True, exist_ok=True)
    reseau.to_parquet(NETWORK_PATH, index=False)
    NETWORK_REPORT_PATH.write_text(json.dumps({
        "cote_entreprise_refuse": cote_entreprise,
        "n_acheteurs": len(reseau),
        "n_concentration_exploitable": int(len(exploitables)),
        "min_marches_avec_gagnant": MIN_MARCHES_AVEC_GAGNANT,
        "marches_avec_gagnant_identifie": int(pdf["has_winner"].sum()),
        "marches_attribues": len(pdf),
    }, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    print(f"\nEcrit : {NETWORK_PATH}")
    print(f"Ecrit : {NETWORK_REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
