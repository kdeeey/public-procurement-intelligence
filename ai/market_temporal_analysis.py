"""
Analyse temporelle au grain marche (Phase 4, 28/08/2026).

CE QUI EST CALCULE, ET CE QUI EST REFUSE
-----------------------------------------
ANNUEL uniquement. Mesure faite avant d'ecrire ce module :

    marches attribues par annee : 2023 -> 68, 2024 -> 80, 2025 -> 86, 2026 -> 80
    granularite mensuelle       : mediane 4 marches/mois, et seulement
                                  7 mois sur 22 atteignent n >= 10

Une serie mensuelle a 4 observations par point ne mesure rien : ses
variations seraient du bruit d'echantillonnage presente comme une
tendance. Le module calcule donc l'annuel et REFUSE le mensuel, en
publiant le comptage mensuel a titre de justification plutot qu'en le
passant sous silence.

CE N'EST PAS UN RETOUR DES ANCIENNES FEATURES TEMPORELLES
-----------------------------------------------------------
Les pentes `single_bidder_rate_trend_slope` et
`number_of_awards_trend_slope` ont ete supprimees en meme temps que la
bascule vers le marche : elles etaient calculees PAR ENTREPRISE, sur 3
entreprises seulement (3/193 avaient les >= 2 points annuels requis).

Ce module fait autre chose : il agrege AU NIVEAU DU CORPUS, pas par
entreprise. Une statistique annuelle sur 68 a 86 marches est solide ; une
pente par entreprise sur 1 ou 2 marches ne l'etait pas. Aucune feature
produite ici n'entre dans le modele — c'est une lecture de contexte pour
l'analyste.

DEUX PIEGES DE LECTURE, SIGNALES A CHAQUE SORTIE
-------------------------------------------------
  * 2026 est une annee TRONQUEE (corpus arrete en aout). Ses totaux ne se
    comparent pas aux annees pleines ; elle est exclue de tout calcul
    d'evolution et marquee comme telle.
  * Chaque taux est calcule sur les seuls marches ou l'information existe.
    L'effectif de ce denominateur est publie a cote de chaque taux : un
    taux de 60 % sur 78 marches et un taux de 60 % sur 5 marches ne se
    lisent pas pareil.

    python -m ai.market_temporal_analysis
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

from features.data_quality import State, assess_market  # noqa: E402

ANALYTICS = REPO / "data/processed/analytics"
SCORES_PATH = ANALYTICS / "market_anomaly_scores.parquet"
PRIORITY_PATH = ANALYTICS / "market_priority.parquet"
TEMPORAL_PATH = ANALYTICS / "market_temporal.parquet"
TEMPORAL_REPORT_PATH = ANALYTICS / "temporal_report.json"

# Effectif minimal pour publier un taux annuel. En dessous, la valeur est
# calculee mais marquee non fiable plutot que masquee.
MIN_N_PAR_ANNEE = 20

# Effectif minimal par point pour qu'une granularite soit exploitable.
MIN_N_PAR_POINT = 10

# 2026 est tronquee (corpus arrete en aout) : exclue des evolutions.
ANNEE_TRONQUEE = 2026


def _taux(serie_valeurs: pd.Series, etats: list, dimension: str,
          condition) -> tuple[float | None, int]:
    """Taux calcule sur les seules observations KNOWN, avec son effectif.

    Renvoie (None, 0) plutot que 0.0 quand aucune observation n'est
    exploitable : un taux sans denominateur n'existe pas.
    """
    mask = [e[dimension] is State.KNOWN for e in etats]
    valeurs = serie_valeurs[mask].dropna()
    if len(valeurs) == 0:
        return None, 0
    return float(condition(valeurs).mean()), int(len(valeurs))


def build_yearly(pdf: pd.DataFrame) -> pd.DataFrame:
    etats_par_id = {int(r["award_id"]): assess_market(r) for _, r in pdf.iterrows()}
    lignes = []
    for annee, groupe in pdf.groupby("annee"):
        etats = [etats_par_id[int(i)] for i in groupe["award_id"]]

        taux_sb, n_sb = _taux(groupe["nb_soumissionnaires"], etats, "concurrents",
                              lambda v: v <= 1)
        taux_ex, n_ex = _taux(groupe["exclusion_rate"], etats, "exclusions",
                              lambda v: v >= 0.5)

        mask_montant = [e["montant"] is State.KNOWN for e in etats]
        montants = pd.to_numeric(groupe["montant_ttc"][mask_montant],
                                 errors="coerce").dropna()

        lignes.append({
            "annee": int(annee),
            "annee_tronquee": int(annee) == ANNEE_TRONQUEE,
            "n_marches": len(groupe),
            "taux_faible_concurrence": taux_sb,
            "n_avec_donnee_concurrence": n_sb,
            "taux_exclusions_elevees": taux_ex,
            "n_avec_donnee_exclusions": n_ex,
            "montant_median": float(montants.median()) if len(montants) else None,
            "n_avec_montant": int(len(montants)),
            "part_ao_ouvert": float((groupe["mode_passation"]
                                     == "Appel d'offres ouvert").mean()),
            "taux_marches_atypiques": (
                float(groupe.loc[groupe["scorable"] == True, "is_anomaly"].mean())  # noqa: E712
                if (groupe["scorable"] == True).any() else None),  # noqa: E712
            "n_scorables": int((groupe["scorable"] == True).sum()),  # noqa: E712
            "fiable": len(groupe) >= MIN_N_PAR_ANNEE,
        })
    return pd.DataFrame(lignes).sort_values("annee").reset_index(drop=True)


def detect_ruptures(yearly: pd.DataFrame, colonne: str) -> list[dict]:
    """Ecarts d'une annee a l'autre, hors annee tronquee.

    Aucune inference statistique : avec 3 points pleins, aucun test de
    rupture n'aurait de puissance. On rapporte l'ecart brut et les deux
    effectifs, et on laisse l'analyste juger.
    """
    pleines = yearly[~yearly["annee_tronquee"]].dropna(subset=[colonne])
    ruptures = []
    for i in range(1, len(pleines)):
        avant, apres = pleines.iloc[i - 1], pleines.iloc[i]
        ruptures.append({
            "de": int(avant["annee"]), "a": int(apres["annee"]),
            "valeur_avant": float(avant[colonne]),
            "valeur_apres": float(apres[colonne]),
            "ecart": float(apres[colonne] - avant[colonne]),
            "n_avant": int(avant["n_marches"]), "n_apres": int(apres["n_marches"]),
        })
    return ruptures


def check_monthly(pdf: pd.DataFrame) -> dict:
    """Verifie, plutot que d'affirmer, que le mensuel est inexploitable."""
    dates = pd.to_datetime(pdf["date_ouverture_plis"], errors="coerce")
    avec_date = dates.dropna()
    if len(avec_date) == 0:
        return {"exploitable": False, "raison": "aucune date exploitable"}
    par_mois = avec_date.dt.to_period("M").value_counts()
    return {
        "exploitable": bool((par_mois >= MIN_N_PAR_POINT).mean() > 0.5),
        "n_marches_dates": int(len(avec_date)),
        "n_mois": int(len(par_mois)),
        "mediane_par_mois": float(par_mois.median()),
        "mois_au_dessus_du_minimum": int((par_mois >= MIN_N_PAR_POINT).sum()),
        "minimum_par_point": MIN_N_PAR_POINT,
    }


def main() -> int:
    pdf = pd.read_parquet(SCORES_PATH)
    if PRIORITY_PATH.exists():
        prio = pd.read_parquet(PRIORITY_PATH)[["award_id", "priority_level"]]
        pdf = pdf.merge(prio, on="award_id", how="left")

    yearly = build_yearly(pdf)
    print(f"=== agregats annuels ({len(pdf)} marches attribues) ===")
    affich = yearly.copy()
    for col in ("taux_faible_concurrence", "taux_exclusions_elevees",
                "part_ao_ouvert", "taux_marches_atypiques"):
        affich[col] = affich[col].map(lambda v: "—" if pd.isna(v) else f"{100 * v:.1f}%")
    affich["montant_median"] = affich["montant_median"].map(
        lambda v: "—" if pd.isna(v) else f"{v:,.0f}".replace(",", " "))
    print(affich.to_string(index=False))

    print(f"\n  2026 est TRONQUEE (corpus arrete en aout) : exclue des evolutions.")
    print(f"  Chaque taux porte son effectif : un taux sur {MIN_N_PAR_ANNEE} marches")
    print("  et le meme taux sur 5 marches ne se lisent pas pareil.")

    print("\n=== evolutions d'une annee a l'autre (annees pleines) ===")
    ruptures = {}
    for col in ("taux_faible_concurrence", "taux_exclusions_elevees"):
        ruptures[col] = detect_ruptures(yearly, col)
        print(f"  {col} :")
        for r in ruptures[col]:
            print(f"    {r['de']} -> {r['a']} : {100 * r['valeur_avant']:.1f}% -> "
                  f"{100 * r['valeur_apres']:.1f}%  (ecart {100 * r['ecart']:+.1f} pts, "
                  f"n={r['n_avant']} puis {r['n_apres']})")
    print("  Aucun test de rupture n'est applique : avec 3 annees pleines,")
    print("  aucun n'aurait de puissance. Ecarts bruts et effectifs, rien de plus.")

    monthly = check_monthly(pdf)
    print("\n=== granularite mensuelle : REFUSEE ===")
    print(f"  {monthly['n_marches_dates']} marches dates, repartis sur "
          f"{monthly['n_mois']} mois")
    print(f"  mediane : {monthly['mediane_par_mois']:.0f} marches/mois")
    print(f"  mois atteignant n >= {MIN_N_PAR_POINT} : "
          f"{monthly['mois_au_dessus_du_minimum']}/{monthly['n_mois']}")
    print("  Une serie a 4 observations par point mesurerait du bruit")
    print("  d'echantillonnage. Le comptage est publie ; la serie ne l'est pas.")

    TEMPORAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    yearly.to_parquet(TEMPORAL_PATH, index=False)
    TEMPORAL_REPORT_PATH.write_text(json.dumps({
        "annuel": yearly.to_dict(orient="records"),
        "ruptures": ruptures,
        "mensuel": monthly,
        "annee_tronquee": ANNEE_TRONQUEE,
        "min_n_par_annee": MIN_N_PAR_ANNEE,
    }, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    print(f"\nEcrit : {TEMPORAL_PATH}")
    print(f"Ecrit : {TEMPORAL_REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
