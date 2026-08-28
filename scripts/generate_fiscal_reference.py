"""
Issue 12 — référentiel fiscal SYNTHÉTIQUE, pas des données DGI réelles.

Pourquoi synthétique, par construction et pas par choix : l'ICE et le RC
des entreprises gagnantes ne sont jamais publiés sur le portail PMMP
(vérifié sur l'ensemble de l'échantillon, docs/rapport_avancement.md §3 —
"Limitation confirmée"). Sans identifiant fiscal fiable, aucun croisement
avec de vraies données DGI n'est possible sur ce projet — le
regroupement ne peut reposer que sur le nom normalisé de l'entreprise
(database/normalization.py), déjà notre clé partout ailleurs dans ce
pipeline. Décision déjà actée avec l'encadrante (§5.3, "le mécanisme de
croisement sera démontré, pas validé sur des données réelles") — ce
script démontre ce mécanisme, il ne le valide pas.

Précaution explicite : les valeurs fiscales ci-dessous sont générées
ALÉATOIREMENT (seed fixe, np.random.default_rng(42)), INDÉPENDAMMENT de
tout signal de risque déjà calculé par ce projet (ai/risk_score.py,
ai/scoring.py). Ce n'est pas un hasard — coupler un chiffre "fiscal"
fabriqué au score de risque d'une entreprise RÉELLEMENT NOMMÉE
produirait quelque chose qui ressemble à une accusation, alors que ce
fichier ne prouve absolument rien sur la situation fiscale réelle de qui
que ce soit. Chaque ligne du CSV porte une colonne `source` répétant
explicitement "SYNTHETIQUE_DEMO_PAS_DGI".

    python -m scripts.generate_fiscal_reference
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

COMPANY_FEATURES_PATH = REPO / "data/processed/analytics/company_features.parquet"
OUTPUT_PATH = REPO / "data/synthetic/fiscal_reference.csv"

SEED = 42
SOURCE_LABEL = "SYNTHETIQUE_DEMO_PAS_DGI"


def generate_fiscal_reference(features_pdf: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    n = len(features_pdf)

    # Chiffre d'affaires declare : loi log-normale plausible pour des PME
    # marocaines (ordre de grandeur 100K-50M DH), generee INDEPENDAMMENT du
    # montant reel gagne par l'entreprise sur ce projet — voir docstring.
    chiffre_affaires_declare_dhs = np.round(rng.lognormal(mean=14.5, sigma=1.2, size=n), -3)
    # Taux d'imposition effectif : plage plausible IS marocain (10%-31%),
    # bruit uniforme, sans lien avec un vrai bareme applique a une vraie
    # entreprise.
    taux_imposition_effectif = np.round(rng.uniform(0.10, 0.31, size=n), 3)
    resultat_net_declare_dhs = np.round(
        chiffre_affaires_declare_dhs * rng.uniform(0.03, 0.15, size=n), -2)
    annee_declaration = rng.choice([2022, 2023, 2024], size=n)

    return pd.DataFrame({
        "company_id": features_pdf["company_id"].to_numpy(),
        "company_normalized_name": features_pdf["company_normalized_name"].to_numpy(),
        "annee_declaration": annee_declaration,
        "chiffre_affaires_declare_dhs": chiffre_affaires_declare_dhs,
        "resultat_net_declare_dhs": resultat_net_declare_dhs,
        "taux_imposition_effectif": taux_imposition_effectif,
        "source": SOURCE_LABEL,
    })


def _demo_crosscheck_mechanism(features_pdf: pd.DataFrame, fiscal_pdf: pd.DataFrame) -> None:
    """Demontre — n'ecrit RIEN sur disque, imprime seulement — comment un
    vrai croisement marches<->fiscal calculerait un ratio montant gagne /
    chiffre d'affaires declare, red flag classique de la litterature
    (un montant remporte proche ou superieur au CA declare signale une
    sous-declaration potentielle). Le mecanisme est reel, l'ENTREE ne
    l'est pas (chiffre_affaires_declare_dhs est fabrique) — le ratio
    resultant n'est donc lui-meme qu'une DEMONSTRATION, jamais un
    resultat a interpreter ou a ecrire dans un fichier de sortie perenne."""
    real = features_pdf[["company_id", "company_normalized_name", "total_amount_ttc",
                         "has_ttc_data"]].copy()
    real["total_amount_ttc"] = pd.to_numeric(real["total_amount_ttc"], errors="coerce")

    merged = real.merge(
        fiscal_pdf[["company_id", "chiffre_affaires_declare_dhs"]], on="company_id", how="inner")
    merged = merged[merged["has_ttc_data"]]
    merged["ratio_marche_vs_ca_declare"] = (
        merged["total_amount_ttc"] / merged["chiffre_affaires_declare_dhs"])

    print("\n=== DEMONSTRATION du mecanisme de croisement (rien n'est ecrit) ===")
    print("Ratio montant marche reel / chiffre d'affaires declare SYNTHETIQUE —")
    print("mecanisme demontre, entree fiscale fabriquee : ne signifie RIEN sur")
    print("une vraie entreprise. Top 3 par ratio, a titre d'exemple technique :")
    top = merged.sort_values("ratio_marche_vs_ca_declare", ascending=False).head(3)
    print(top[["company_normalized_name", "total_amount_ttc",
              "chiffre_affaires_declare_dhs", "ratio_marche_vs_ca_declare"]].to_string(index=False))


def main() -> int:
    features_pdf = pd.read_parquet(COMPANY_FEATURES_PATH)
    n_companies = len(features_pdf)
    print(f"Company chargees : {n_companies}")
    if n_companies != 200:
        raise RuntimeError("recoupement echoue — diagnostiquer avant de continuer")

    fiscal_pdf = generate_fiscal_reference(features_pdf)
    print(f"Lignes generees : {len(fiscal_pdf)} (attendu {n_companies})")
    if len(fiscal_pdf) != n_companies:
        raise RuntimeError("recoupement echoue — diagnostiquer avant de continuer")

    print("\n=== exemple concret : TECTRA (valeurs 100% synthetiques) ===")
    example = fiscal_pdf[fiscal_pdf["company_normalized_name"] == "TECTRA"]
    print(example.to_string(index=False))

    _demo_crosscheck_mechanism(features_pdf, fiscal_pdf)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    header_comment = (
        "# SYNTHETIQUE - donnees fiscales entierement FICTIVES, generees\n"
        "# aleatoirement (seed=42), AUCUN lien avec de vraies declarations\n"
        "# DGI. Demontre le mecanisme de croisement marches<->fiscal par nom\n"
        "# d'entreprise normalise, ne le valide pas. Voir\n"
        "# scripts/generate_fiscal_reference.py et docs/rapport_avancement.md\n"
        "# Sec 5.3.\n"
    )
    with open(OUTPUT_PATH, "w", encoding="utf-8", newline="") as f:
        f.write(header_comment)
        fiscal_pdf.to_csv(f, index=False)
    print(f"\nEcrit : {OUTPUT_PATH}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
