"""
Population marche partagee — filtre ATTRIBUE + porte de completude
(refonte "red flags only", priorite pilotee par le compte de flags actifs
plutot que par le score d'anomalie).

Extrait de ce qui vivait en dur dans ai/train_market_model.py::main().
Desormais partage entre ai/market_red_flags.py (qui doit filtrer sur la
meme population et tourne maintenant AVANT train_market_model.py dans la
chaine, puisque le modele s'entraine sur les red flags) et
train_market_model.py lui-meme — une seule definition, jamais deux qui
pourraient diverger.

    from ai.market_population import MIN_DATA_COMPLETENESS, compute_population
"""

from __future__ import annotations

import pandas as pd

# Nombre minimal d'informations reellement extraites (parmi montant,
# concurrents, exclusions) pour qu'un marche soit scorable — seuil MESURE,
# voir ai/train_market_model.py pour la mesure qui l'a impose (correlation
# score/completude ramenee de -0,249 a +0,063 avec ce seuil).
MIN_DATA_COMPLETENESS = 2


def compute_population(pdf: pd.DataFrame) -> pd.DataFrame:
    """market_features.parquet (tout statut) -> marches ATTRIBUE, avec
    data_completeness et scorable ajoutes.

    Ne filtre PAS sur `scorable` : le retour contient tous les marches
    ATTRIBUE, scorables ou non, pour que chaque etage aval (red flags,
    entrainement) decide lui-meme ce qu'il fait des non-scorables plutot
    que de les perdre silencieusement ici.
    """
    attribue = pdf[pdf["statut"] == "ATTRIBUE"].reset_index(drop=True).copy()
    attribue["data_completeness"] = attribue[
        ["has_amount_data", "has_competitor_data", "has_exclusion_data"]].sum(axis=1)
    attribue["scorable"] = attribue["data_completeness"] >= MIN_DATA_COMPLETENESS
    return attribue
